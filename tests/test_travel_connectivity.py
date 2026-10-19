import contextlib
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "travel-ledger" / "scripts" / "travel_ledger.py"


def load_ledger():
    spec = importlib.util.spec_from_file_location("travel_ledger_connectivity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TravelConnectivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="travel-connectivity-")
        self.profile = Path(self.temp.name) / "profile"
        self.profile.mkdir(mode=0o700)
        self.original_home = os.environ.get("HERMES_HOME")
        self.original_workspace = os.environ.get("HERMES_WORKSPACE_ROOT")
        self.original_db = os.environ.get("TRAVEL_LEDGER_DB")
        os.environ["HERMES_HOME"] = str(self.profile)
        os.environ.pop("HERMES_WORKSPACE_ROOT", None)
        os.environ.pop("TRAVEL_LEDGER_DB", None)
        self.ledger = load_ledger()
        self.conn = self.ledger.connect()
        self.as_of = "2026-09-20T12:00:00+07:00"

    def tearDown(self):
        self.conn.close()
        for name, value in (
            ("HERMES_HOME", self.original_home),
            ("HERMES_WORKSPACE_ROOT", self.original_workspace),
            ("TRAVEL_LEDGER_DB", self.original_db),
        ):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp.cleanup()

    @staticmethod
    def record(value, confirmed_at="2026-09-20T11:00:00+07:00", source="synthetic-test"):
        return {"value": value, "confirmed_at": confirmed_at, "source": source}

    def test_update_readback_and_native_ledger_schema(self):
        profile = self.ledger.upsert_connectivity_fields(
            self.conn,
            "traveler-a",
            {"device_model": self.record("Example handset"), "esim_supported": self.record(True)},
        )
        profile = self.ledger.upsert_connectivity_fields(
            self.conn,
            "traveler-a",
            {"region": "APAC"},
            confirmed_at=self.as_of,
            source="user",
        )
        self.assertEqual(profile["schema_version"], 1)
        self.assertEqual(profile["subject_id"], "traveler-a")
        self.assertEqual(profile["fields"]["device_model"]["value"], "Example handset")
        self.assertEqual(profile["fields"]["region"]["confirmed_at"], self.as_of)
        columns = [row[1] for row in self.conn.execute("pragma table_info(connectivity_profiles)")]
        self.assertEqual(
            columns,
            ["subject_id", "field_name", "value_json", "confirmed_at", "source", "created_at", "updated_at"],
        )

    def test_exactly_45_days_is_current_and_over_45_days_is_stale(self):
        self.ledger.upsert_connectivity_fields(
            self.conn,
            "traveler-a",
            {
                "device_model": self.record("Example handset", "2026-08-06T12:00:00+07:00"),
                "os": self.record("Example OS", "2026-08-06T11:59:59+07:00"),
            },
        )
        report = self.ledger.connectivity_intake_report(
            self.conn, "traveler-a", as_of=self.as_of,
        )
        self.assertNotIn("device_model", report["stale"])
        self.assertIn("os", report["stale"])

    def test_missing_invalid_and_future_timestamps_need_confirmation(self):
        self.ledger.upsert_connectivity_fields(
            self.conn,
            "traveler-a",
            {"region": self.record("APAC", "2026-09-20T12:00:01+07:00"), "os": self.record("Example OS")},
        )
        self.conn.execute(
            "update connectivity_profiles set confirmed_at=? where subject_id=? and field_name=?",
            ("not-a-timestamp", "traveler-a", "os"),
        )
        self.conn.commit()
        report = self.ledger.connectivity_intake_report(
            self.conn, "traveler-a", as_of=self.as_of,
        )
        confirmations = {item["field"]: item["reason"] for item in report["needs_confirmation"]}
        self.assertEqual(confirmations["region"], "future_timestamp")
        self.assertEqual(confirmations["os"], "invalid_timestamp")
        self.assertIn("device_model", report["missing"])
        self.assertNotIn("region", report["stale"])
        self.assertNotIn("os", report["stale"])

    def test_stored_null_is_unknown_and_does_not_break_profile_intake(self):
        self.ledger.upsert_connectivity_fields(
            self.conn, "traveler-a", {"region": self.record("APAC")}
        )
        stamp = self.ledger.now()
        self.conn.execute(
            """
            insert into connectivity_profiles
            (subject_id, field_name, value_json, confirmed_at, source, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            ("traveler-a", "os", "null", stamp, "legacy-null", stamp, stamp),
        )
        self.conn.commit()

        profile = self.ledger.get_connectivity_profile(self.conn, "traveler-a")
        report = self.ledger.connectivity_intake_report(
            self.conn, "traveler-a", as_of=self.as_of,
        )
        self.assertNotIn("os", profile["fields"])
        self.assertIn("os", report["missing"])
        self.assertNotIn("os", report["needs_confirmation"])

    def test_read_and_intake_do_not_renew_confirmation_or_write(self):
        self.ledger.upsert_connectivity_fields(
            self.conn,
            "traveler-a",
            {"device_model": self.record("Example handset", "2026-08-01T12:00:00+07:00")},
        )
        before = dict(self.conn.execute(
            "select confirmed_at, source, updated_at from connectivity_profiles "
            "where subject_id=? and field_name=?", ("traveler-a", "device_model")
        ).fetchone())
        loaded = self.ledger.get_connectivity_profile(self.conn, "traveler-a")
        report = self.ledger.connectivity_intake_report(
            self.conn, "traveler-a", as_of=self.as_of,
        )
        after = dict(self.conn.execute(
            "select confirmed_at, source, updated_at from connectivity_profiles "
            "where subject_id=? and field_name=?", ("traveler-a", "device_model")
        ).fetchone())
        self.assertEqual(loaded["fields"]["device_model"]["confirmed_at"], before["confirmed_at"])
        self.assertIn("device_model", report["stale"])
        self.assertEqual(before, after)

    def test_reddit_uses_inclusive_six_calendar_months_and_end_of_month_clipping(self):
        self.assertTrue(self.ledger.connectivity_reddit_eligible(
            "2024-02-29T00:00:00Z", "2024-08-31T00:00:00Z"
        ))
        self.assertFalse(self.ledger.connectivity_reddit_eligible(
            "2024-02-28T23:59:59Z", "2024-08-31T00:00:00Z"
        ))
        self.assertTrue(self.ledger.connectivity_reddit_eligible(
            "2024-03-01T00:00:00Z", "2024-09-01T00:00:00Z"
        ))
        self.assertFalse(self.ledger.connectivity_reddit_eligible(None, self.as_of))
        self.assertFalse(self.ledger.connectivity_reddit_eligible("2026-09-20T12:00:01+07:00", self.as_of))
        self.assertFalse(self.ledger.connectivity_reddit_eligible("2026-09-01", self.as_of))
        self.assertFalse(self.ledger.connectivity_reddit_eligible(
            "2026-03-20T00:00:00Z", "2026-09-20T12:00:00Z"
        ))
        self.assertTrue(self.ledger.connectivity_reddit_eligible(
            "2026-03-20T05:00:00Z", "2026-09-20T12:00:00+07:00"
        ))
        self.assertFalse(self.ledger.connectivity_reddit_eligible(
            "2026-03-20T04:59:59Z", "2026-09-20T12:00:00+07:00"
        ))

    def test_whitespace_text_list_and_flexible_values_are_normalized_or_rejected_atomically(self):
        profile = self.ledger.upsert_connectivity_fields(
            self.conn,
            "traveler-a",
            {
                "device_model": self.record("  Example handset  "),
                "uses": self.record([" browsing ", "\thotspot\t"]),
                "redundancy": self.record("  backup link  "),
            },
        )
        self.assertEqual(profile["fields"]["device_model"]["value"], "Example handset")
        self.assertEqual(profile["fields"]["uses"]["value"], ["browsing", "hotspot"])
        self.assertEqual(profile["fields"]["redundancy"]["value"], "backup link")

        for field, value in (
            ("os", " \t"),
            ("uses", ["browsing", " "]),
            ("redundancy", "\n"),
            ("owned_connectivity", ["backup", "\t"]),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.ledger.upsert_connectivity_fields(
                        self.conn, "traveler-a", {field: self.record(value)}
                    )

        after = self.ledger.get_connectivity_profile(self.conn, "traveler-a")
        self.assertNotIn("os", after["fields"])
        self.assertEqual(after["fields"]["device_model"]["value"], "Example handset")

    def test_overflowing_workload_estimate_is_unknown_and_strict_json_safe(self):
        self.assertIsNone(self.ledger.connectivity_workload_data_estimate(1e308, 24))
        self.ledger.upsert_connectivity_fields(
            self.conn,
            "traveler-a",
            {
                "stream_bitrate_mbps": self.record(1e308),
                "hours_per_day": self.record(24),
            },
        )
        report = self.ledger.connectivity_intake_report(
            self.conn, "traveler-a", as_of=self.as_of,
        )
        self.assertIsNone(report["workload_estimate"])
        json.dumps(report, allow_nan=False)

    def test_sensitive_keys_and_values_are_rejected_without_rows(self):
        for field in ("imei", "eid", "qr_code", "passport", "password", "card_number"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.ledger.upsert_connectivity_fields(
                        self.conn, "traveler-a", {field: self.record("not stored")}
                    )
        for value in ("passport number 123", "phone number 555-0100", "api token abc"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.ledger.upsert_connectivity_fields(
                        self.conn, "traveler-a", {"owned_connectivity": self.record(value)}
                    )
        for field, value in (
            ("owned_connectivity", "8901234567890123456"),
            ("owned_connectivity", "my pass 123456"),
            ("device_model", "356938035643809"),
            ("uses", ["otp 123456"]),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    self.ledger.upsert_connectivity_fields(
                        self.conn, "traveler-a", {field: self.record(value)}
                    )
        with self.assertRaises(ValueError):
            self.ledger.upsert_connectivity_fields(
                self.conn, "traveler-a", {"region": self.record("APAC", source="otp import")}
            )
        count = self.conn.execute("select count(*) from connectivity_profiles").fetchone()[0]
        self.assertEqual(count, 0)

    def test_data_usage_missing_and_stale_are_optional_questions_not_invented_budget(self):
        self.ledger.upsert_connectivity_fields(
            self.conn, "traveler-a", {"uses": self.record(["browsing"])}
        )
        missing = self.ledger.connectivity_intake_report(
            self.conn, "traveler-a", as_of=self.as_of,
        )
        missing_question = next(
            item for item in missing["questions"] if "data_gb_per_day" in item["fields"]
        )
        self.assertIn("actual observed", missing_question["question"])
        self.assertIn("unknown", missing_question["question"])
        self.assertIn("data_gb_per_day", missing["missing"])
        self.assertIsNone(missing["workload_estimate"])

        self.ledger.upsert_connectivity_fields(
            self.conn,
            "traveler-a",
            {"data_gb_per_day": self.record(2.0, "2026-08-01T12:00:00+07:00")},
        )
        stale = self.ledger.connectivity_intake_report(
            self.conn, "traveler-a", as_of=self.as_of,
        )
        self.assertIn("data_gb_per_day", stale["stale"])
        self.assertTrue(any("data_gb_per_day" in item["fields"] for item in stale["questions"]))

    def test_subject_scoped_containment_and_isolation(self):
        self.ledger.upsert_connectivity_fields(
            self.conn, "traveler-a", {"region": self.record("A")}
        )
        self.ledger.upsert_connectivity_fields(
            self.conn, "traveler-b", {"region": self.record("B")}
        )
        self.assertEqual(
            self.ledger.get_connectivity_profile(self.conn, "traveler-a")["fields"]["region"]["value"],
            "A",
        )
        self.assertEqual(
            self.ledger.get_connectivity_profile(self.conn, "traveler-b")["fields"]["region"]["value"],
            "B",
        )
        self.assertEqual(self.ledger.get_connectivity_profile(self.conn, "traveler-c")["fields"], {})
        with self.assertRaises(ValueError):
            self.ledger.upsert_connectivity_fields(
                self.conn,
                "traveler-a",
                {"subject_id": "traveler-b", "os": self.record("Example OS")},
            )

    def test_personal_assistant_ledger_wrapper_uses_native_connectivity_table(self):
        from personal_assistant.state import Ledger as PALedger

        native = PALedger(self.profile)
        saved = native.set_connectivity_fields(
            "traveler-native", {"region": self.record("APAC")}
        )
        self.assertEqual(
            native.get_connectivity_profile("traveler-native"), saved
        )
        self.assertEqual(native.get_connectivity_profile("other")["fields"], {})

    def test_native_revalidates_path_after_post_init_directory_replacement(self):
        from personal_assistant.state import Ledger as PALedger

        native = PALedger(self.profile)
        native.set_connectivity_fields("traveler-native", {"region": self.record("APAC")})
        ledger_dir = self.profile / "state" / "travel-ledger"
        original_dir = self.profile / "state" / "travel-ledger-original"
        outside = Path(self.temp.name) / "outside-ledger"
        outside.mkdir(mode=0o700)
        shutil.copy2(native.path, outside / "travel.sqlite")
        ledger_dir.rename(original_dir)
        ledger_dir.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                native.set_connectivity_fields("traveler-native", {"os": self.record("Example OS")})
            with sqlite3.connect(outside / "travel.sqlite") as conn:
                self.assertEqual(
                    conn.execute(
                        "select count(*) from connectivity_profiles where subject_id=?",
                        ("traveler-native",),
                    ).fetchone()[0],
                    1,
                )
        finally:
            ledger_dir.unlink()
            original_dir.rename(ledger_dir)

        self.assertNotIn("os", native.get_connectivity_profile("traveler-native")["fields"])

    def test_subject_scoped_removal_requires_confirmation_and_supports_one_or_all(self):
        self.ledger.upsert_connectivity_fields(
            self.conn,
            "traveler-a",
            {"region": self.record("APAC"), "os": self.record("Example OS")},
        )
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            self.ledger.remove_connectivity_fields(self.conn, "traveler-a", ["region"])
        with self.assertRaisesRegex(ValueError, "unknown connectivity field"):
            self.ledger.remove_connectivity_fields(
                self.conn, "traveler-a", ["not_a_field"], confirmed=True
            )
        one = self.ledger.remove_connectivity_fields(
            self.conn, "traveler-a", ["region"], confirmed=True
        )
        self.assertNotIn("region", one["fields"])
        self.assertIn("os", one["fields"])

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.ledger.main([
                "connectivity-remove", "--subject-id", "traveler-a",
                "--clear-all", "--confirm", "--json",
            ])
        self.assertEqual(json.loads(output.getvalue())["fields"], {})
        self.assertEqual(
            self.ledger.get_connectivity_profile(self.conn, "traveler-a")["fields"], {}
        )

    def test_numeric_flexible_identifier_values_are_rejected(self):
        for value in (356938035643809, 356938035643809.0):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "identifier"):
                    self.ledger.upsert_connectivity_fields(
                        self.conn, "traveler-a", {"owned_connectivity": self.record(value)}
                    )
        count = self.conn.execute("select count(*) from connectivity_profiles").fetchone()[0]
        self.assertEqual(count, 0)
        profile = self.ledger.upsert_connectivity_fields(
            self.conn, "traveler-a", {"redundancy": self.record(2)}
        )
        self.assertEqual(profile["fields"]["redundancy"]["value"], 2)

    def test_reversed_trip_range_is_rejected_including_against_stored_value(self):
        with self.assertRaisesRegex(ValueError, "trip_end must not be before trip_start"):
            self.ledger.upsert_connectivity_fields(self.conn, "traveler-a", {
                "trip_start": self.record("2026-10-10"), "trip_end": self.record("2026-10-01"),
            })
        self.ledger.upsert_connectivity_fields(
            self.conn, "traveler-a", {"trip_start": self.record("2026-10-10")}
        )
        with self.assertRaisesRegex(ValueError, "trip_end must not be before trip_start"):
            self.ledger.upsert_connectivity_fields(
                self.conn, "traveler-a", {"trip_end": self.record("2026-10-01")}
            )
        profile = self.ledger.upsert_connectivity_fields(
            self.conn, "traveler-a", {"trip_end": self.record("2026-10-10")}
        )
        self.assertEqual(profile["fields"]["trip_end"]["value"], "2026-10-10")
        self.assertNotIn("trip_end", self.ledger.get_connectivity_profile(self.conn, "traveler-b")["fields"])

    def test_use_matching_is_word_level_not_substring(self):
        self.ledger.upsert_connectivity_fields(
            self.conn, "traveler-a", {"uses": self.record(["delivery apps", "olive oil shopping"])}
        )
        report = self.ledger.connectivity_intake_report(self.conn, "traveler-a", as_of=self.as_of)
        asked = {field for item in report["questions"] for field in item["fields"]}
        self.assertNotIn("stream_bitrate_mbps", asked)
        self.assertNotIn("hotspot_devices", asked)
        self.ledger.upsert_connectivity_fields(
            self.conn, "traveler-a", {"uses": self.record(["Live-streaming", "tethering laptop"])}
        )
        report = self.ledger.connectivity_intake_report(self.conn, "traveler-a", as_of=self.as_of)
        asked = {field for item in report["questions"] for field in item["fields"]}
        self.assertIn("stream_bitrate_mbps", asked)
        self.assertIn("hotspot_devices", asked)

    def test_workload_estimate_requires_current_inputs(self):
        self.ledger.upsert_connectivity_fields(self.conn, "traveler-a", {
            "stream_bitrate_mbps": self.record(5.0), "hours_per_day": self.record(2.0),
        })
        fresh = self.ledger.connectivity_intake_report(self.conn, "traveler-a", as_of=self.as_of)
        self.assertEqual(fresh["workload_estimate"]["estimate_gb_decimal_per_day"], 4.5)
        self.ledger.upsert_connectivity_fields(self.conn, "traveler-a", {
            "hours_per_day": self.record(2.0, "2026-06-01T12:00:00+07:00"),
        })
        stale = self.ledger.connectivity_intake_report(self.conn, "traveler-a", as_of=self.as_of)
        self.assertIn("hours_per_day", stale["stale"])
        self.assertIsNone(stale["workload_estimate"])
        self.ledger.upsert_connectivity_fields(self.conn, "traveler-a", {
            "hours_per_day": self.record(2.0, "2026-12-01T12:00:00+07:00"),
        })
        future = self.ledger.connectivity_intake_report(self.conn, "traveler-a", as_of=self.as_of)
        self.assertIsNone(future["workload_estimate"])

    def test_cli_accepts_stdin_so_no_profile_file_is_staged(self):
        payload = json.dumps({
            "subject_id": "traveler-stdin",
            "fields": {"device_model": self.record("Example handset")},
        })
        before = set(ROOT.rglob("*.json"))
        output = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(payload)), contextlib.redirect_stdout(output):
            self.ledger.main([
                "connectivity-upsert", "--subject-id", "traveler-stdin", "--input", "-", "--json",
            ])
        self.assertEqual(json.loads(output.getvalue())["subject_id"], "traveler-stdin")
        self.assertEqual(set(ROOT.rglob("*.json")), before)
        skill = (ROOT / "skills" / "travel-connectivity" / "SKILL.md").read_text()
        self.assertIn("--input -", skill)
        self.assertNotIn("--input connectivity-facts.json", skill)

    def test_cli_round_trip_uses_the_same_sqlite_ledger(self):
        input_path = self.profile / "connectivity-facts.json"
        input_path.write_text(json.dumps({
            "subject_id": "traveler-cli",
            "fields": {"device_model": self.record("Example handset")},
        }), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.ledger.main([
                "connectivity-upsert", "--subject-id", "traveler-cli",
                "--input", str(input_path), "--json",
            ])
        self.assertEqual(json.loads(output.getvalue())["subject_id"], "traveler-cli")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.ledger.main(["connectivity-show", "--subject-id", "traveler-cli"])
        shown = json.loads(output.getvalue())
        self.assertEqual(shown["fields"]["device_model"]["value"], "Example handset")
        self.assertTrue((self.profile / "state" / "travel-ledger" / "travel.sqlite").exists())

    def test_skill_and_packaging_registration_are_present(self):
        skill = ROOT / "skills" / "travel-connectivity"
        self.assertTrue((skill / "SKILL.md").is_file())
        self.assertTrue((skill / "references" / "profile-and-integration.md").is_file())
        self.assertTrue((skill / "templates" / "worker-contract.md").is_file())
        self.assertIn("state/travel-ledger/travel.sqlite", (skill / "SKILL.md").read_text())
        self.assertNotIn("connectivity.json", (skill / "SKILL.md").read_text())
        for manifest_path, prefix in (
            (ROOT / "openclaw.plugin.json", "skills/"),
            (ROOT / "skills/travel-action-pack-manifest/openclaw.plugin.json", "../"),
        ):
            manifest = json.loads(manifest_path.read_text())
            self.assertIn(prefix + "travel-connectivity", manifest["skills"])
        validate = (ROOT / "scripts/validate_pack.py").read_text()
        component = json.loads((ROOT / "support-control/component.json").read_text())
        self.assertIn('"travel-connectivity"', validate)
        self.assertIn("travel-connectivity", component["required_skills"])
        from personal_assistant.entry import OPERATIONS
        self.assertNotIn("connectivity_profile", OPERATIONS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
