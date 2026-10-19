import contextlib
import importlib.util
import io
import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "travel-ledger" / "scripts" / "travel_ledger.py"


def load_ledger():
    spec = importlib.util.spec_from_file_location("travel_ledger", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TravelLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = {name: os.environ.get(name) for name in ("TRAVEL_LEDGER_DB", "HERMES_HOME", "HERMES_WORKSPACE_ROOT")}
        for name in self.original:
            os.environ.pop(name, None)
        self.ledger = load_ledger()

    def tearDown(self):
        for name, value in self.original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp.cleanup()

    def run_command(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.ledger.main(list(args))
        return output.getvalue()

    def make_root(self, name="profiles/alice"):
        root = Path(self.temp.name) / name
        root.mkdir(parents=True, mode=0o700)
        return root

    def test_default_is_profile_scoped(self):
        profile = self.make_root()
        os.environ["HERMES_HOME"] = str(profile)
        expected = profile / "state" / "travel-ledger" / "travel.sqlite"

        self.assertEqual(Path(self.ledger.db_path()), expected.resolve())
        self.assertEqual(Path(self.run_command("init").strip()), expected.resolve())
        self.assertTrue(expected.exists())
        self.assertEqual(stat.S_IMODE(expected.stat().st_mode), 0o600)

    def test_workspace_root_is_supported_when_profile_root_is_absent(self):
        workspace = self.make_root("workspace")
        os.environ["HERMES_WORKSPACE_ROOT"] = str(workspace)
        expected = workspace / "state" / "travel-ledger" / "travel.sqlite"

        self.assertEqual(Path(self.ledger.db_path()), expected.resolve())
        self.run_command("init")
        self.assertTrue(expected.exists())

    def test_valid_profile_root_wins_before_invalid_workspace_root_is_checked(self):
        profile = self.make_root()
        os.environ["HERMES_HOME"] = str(profile)
        os.environ["HERMES_WORKSPACE_ROOT"] = str(Path(self.temp.name) / "missing-workspace")
        expected = profile / "state" / "travel-ledger" / "travel.sqlite"

        self.assertEqual(Path(self.ledger.db_path()), expected.resolve())
        self.run_command("init")
        self.assertTrue(expected.exists())

    def test_requires_explicit_binding_without_legacy_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "TRAVEL_LEDGER_DB"):
            self.ledger.db_path()
        os.environ["TRAVEL_LEDGER_DB"] = str(Path(self.temp.name) / "outside.sqlite")
        with self.assertRaisesRegex(RuntimeError, "HERMES_HOME|HERMES_WORKSPACE_ROOT"):
            self.ledger.db_path()

    def test_missing_or_insecure_root_fails_closed(self):
        os.environ["HERMES_HOME"] = str(Path(self.temp.name) / "missing")
        with self.assertRaisesRegex(RuntimeError, "existing directory"):
            self.ledger.db_path()

        profile = self.make_root()
        profile.chmod(0o777)
        os.environ["HERMES_HOME"] = str(profile)
        with self.assertRaisesRegex(RuntimeError, "world-writable"):
            self.ledger.db_path()

    def test_managed_ancestors_keep_the_owned_ledger_private(self):
        profile = self.make_root()
        profile.chmod(0o2770)
        state = profile / "state"
        state.mkdir(mode=0o770)
        state.chmod(0o770)
        os.environ["HERMES_HOME"] = str(profile)
        self.run_command("init")
        ledger_dir = state / "travel-ledger"
        self.assertEqual(stat.S_IMODE(ledger_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((ledger_dir / "travel.sqlite").stat().st_mode), 0o600)

        ledger_dir.chmod(0o770)
        with self.assertRaisesRegex(RuntimeError, "group/world-writable"):
            self.ledger.db_path()

        ledger_dir.chmod(0o700)
        state.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, "world-writable"):
            self.ledger.db_path()

    def test_symlinked_root_ancestor_fails_before_creation(self):
        real_profile = Path(self.temp.name) / "real" / "profile"
        real_profile.mkdir(parents=True, mode=0o700)
        alias = Path(self.temp.name) / "link"
        alias.symlink_to(real_profile.parent, target_is_directory=True)
        os.environ["HERMES_HOME"] = str(alias / "profile")

        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.ledger.db_path()
        self.assertFalse((real_profile / "state").exists())

    def test_override_containment(self):
        profile = self.make_root()
        os.environ["HERMES_HOME"] = str(profile)
        for value, expected in (
            (str(profile / "absolute.sqlite"), profile / "absolute.sqlite"),
            (str(profile.resolve() / "canonical.sqlite"), profile / "canonical.sqlite"),
            ("nested/relative.sqlite", profile / "nested/relative.sqlite"),
        ):
            os.environ["TRAVEL_LEDGER_DB"] = value
            self.assertEqual(Path(self.ledger.db_path()), expected.resolve())
        profile.chmod(0o2770)
        for value in (str(Path(self.temp.name) / "outside.sqlite"), "../../outside.sqlite", str(profile / "root.sqlite")):
            os.environ["TRAVEL_LEDGER_DB"] = value
            with self.assertRaisesRegex(RuntimeError, "must stay under|group/world-writable"):
                self.ledger.db_path()

    def test_symlink_file_type_and_directory_permissions_fail_closed(self):
        profile = self.make_root()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir(mode=0o700)
        os.environ["HERMES_HOME"] = str(profile)

        default_target = profile / "target"
        default_target.mkdir(mode=0o700)
        (profile / "state").symlink_to(default_target, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "symlinks"):
            self.ledger.db_path()

        symlink = profile / "link.sqlite"
        symlink.symlink_to(outside / "ledger.sqlite")
        os.environ["TRAVEL_LEDGER_DB"] = str(symlink)
        with self.assertRaisesRegex(RuntimeError, "symlinks|must stay under"):
            self.ledger.db_path()

        symlink_parent = profile / "link-parent"
        symlink_parent.symlink_to(outside, target_is_directory=True)
        os.environ["TRAVEL_LEDGER_DB"] = "link-parent/ledger.sqlite"
        with self.assertRaisesRegex(RuntimeError, "symlinks|must stay under"):
            self.ledger.db_path()
        os.environ["TRAVEL_LEDGER_DB"] = "link-parent/../safe.sqlite"
        with self.assertRaisesRegex(RuntimeError, "symlinks|must stay under"):
            self.ledger.db_path()

        db_directory = profile / "database.sqlite"
        db_directory.mkdir(mode=0o700)
        os.environ["TRAVEL_LEDGER_DB"] = str(db_directory)
        with self.assertRaisesRegex(RuntimeError, "regular file"):
            self.ledger.db_path()

        parent = profile / "unsafe-parent"
        parent.mkdir(mode=0o700)
        parent.chmod(0o777)
        os.environ["TRAVEL_LEDGER_DB"] = "unsafe-parent/ledger.sqlite"
        with self.assertRaisesRegex(RuntimeError, "group/world-writable"):
            self.ledger.db_path()

        insecure_file = profile / "insecure.sqlite"
        insecure_file.touch(mode=0o600)
        insecure_file.chmod(0o666)
        os.environ["TRAVEL_LEDGER_DB"] = str(insecure_file)
        with self.assertRaisesRegex(RuntimeError, "group/world-writable"):
            self.ledger.db_path()

    def test_logical_schema_and_row_parity(self):
        profile = self.make_root()
        os.environ["HERMES_HOME"] = str(profile)
        db = profile / "ledger.sqlite"
        os.environ["TRAVEL_LEDGER_DB"] = str(db)
        self.run_command("init")
        self.run_command(
            "trip-upsert", "--trip-id", "trip-1", "--title", "Test trip",
            "--field", 'destinations=["HKG"]', "--field", "source_confidence=high",
        )
        self.run_command(
            "action-upsert", "--action-id", "action-1", "--trip-id", "trip-1",
            "--type", "booking", "--provider", "Example Air", "--status", "prepared",
        )
        self.run_command(
            "browser-checkpoint", "--checkpoint-id", "checkpoint-1", "--action-id", "action-1",
            "--provider", "Example Air", "--state", "awaiting confirmation",
        )
        self.run_command(
            "payment-readiness", "--readiness-id", "payment-1", "--provider", "wallet",
            "--status", "ready", "--budget", "250", "--currency", "USD",
        )
        summary = json.loads(self.run_command("summary", "--json"))
        self.assertEqual(summary["db"], str(db.resolve()))
        self.assertEqual(summary["trips"][0]["fields"], {"destinations": ["HKG"], "source_confidence": "high"})
        self.assertEqual(summary["actions"][0]["status"], "prepared")
        self.assertEqual(summary["browser_checkpoints"][0]["state"], "awaiting confirmation")
        self.assertEqual(summary["payment_readiness"][0]["status"], "ready")
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            tables = [row[0] for row in conn.execute("select name from sqlite_master where type='table' order by name")]
            self.assertEqual(tables, ["actions", "browser_checkpoints", "connectivity_profiles", "payment_readiness", "trips"])
            expected_columns = {
                "trips": ["trip_id", "title", "status", "fields_json", "created_at", "updated_at"],
                "actions": ["action_id", "trip_id", "action_type", "provider", "status", "fields_json", "created_at", "updated_at"],
                "browser_checkpoints": ["checkpoint_id", "action_id", "provider", "lane", "session_id", "context_id", "url", "state", "fields_json", "created_at", "updated_at"],
                "payment_readiness": ["readiness_id", "provider", "status", "descriptor", "budget", "currency", "fields_json", "created_at", "updated_at"],
                "connectivity_profiles": ["subject_id", "field_name", "value_json", "confirmed_at", "source", "created_at", "updated_at"],
            }
            for table, columns in expected_columns.items():
                actual = [row[1] for row in conn.execute(f"pragma table_info({table})")]
                self.assertEqual(actual, columns)

            rows = {}
            for table in expected_columns:
                rows[table] = [dict(row) for row in conn.execute(f"select * from {table}")]

        self.assertEqual(
            {key: value for key, value in rows["trips"][0].items() if key not in ("created_at", "updated_at")},
            {
                "trip_id": "trip-1",
                "title": "Test trip",
                "status": "planning",
                "fields_json": '{"destinations": ["HKG"], "source_confidence": "high"}',
            },
        )
        self.assertEqual(
            {key: value for key, value in rows["actions"][0].items() if key not in ("created_at", "updated_at")},
            {
                "action_id": "action-1",
                "trip_id": "trip-1",
                "action_type": "booking",
                "provider": "Example Air",
                "status": "prepared",
                "fields_json": "{}",
            },
        )
        self.assertEqual(
            {key: value for key, value in rows["browser_checkpoints"][0].items() if key not in ("created_at", "updated_at")},
            {
                "checkpoint_id": "checkpoint-1",
                "action_id": "action-1",
                "provider": "Example Air",
                "lane": "browserbase",
                "session_id": "",
                "context_id": "",
                "url": "",
                "state": "awaiting confirmation",
                "fields_json": "{}",
            },
        )
        self.assertEqual(
            {key: value for key, value in rows["payment_readiness"][0].items() if key not in ("created_at", "updated_at")},
            {
                "readiness_id": "payment-1",
                "provider": "wallet",
                "status": "ready",
                "descriptor": "",
                "budget": "250",
                "currency": "USD",
                "fields_json": "{}",
            },
        )

    def test_generic_summary_does_not_disclose_subject_scoped_connectivity(self):
        profile = self.make_root()
        os.environ["HERMES_HOME"] = str(profile)
        input_path = Path(self.temp.name) / "connectivity-facts.json"
        input_path.write_text(json.dumps({
            "fields": {
                "region": {
                    "value": "APAC",
                    "confirmed_at": "2026-09-20T11:00:00+07:00",
                    "source": "synthetic-test",
                },
            },
        }), encoding="utf-8")
        self.run_command(
            "connectivity-upsert", "--subject-id", "traveler-a",
            "--input", str(input_path), "--json",
        )
        summary = json.loads(self.run_command("summary", "--json"))
        self.assertNotIn("connectivity_profiles", summary)


if __name__ == "__main__":
    unittest.main()
