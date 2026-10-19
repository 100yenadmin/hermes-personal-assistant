import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from jsonschema import Draft7Validator

from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.state import Ledger
from personal_assistant.state_loop import StateLoop


EVENT = {
    "source_type": "fixture-meeting",
    "source_id": "meeting-42",
    "source_revision": "rev-1",
    "payload": {"summary_digest": "fixture-digest"},
    "occurred_at": "2026-09-11T01:00:00+00:00",
    "projections": [
        {"projection_key": "account", "target_type": "brain-page", "target_id": "accounts/fixture"},
        {"projection_key": "commitment", "target_type": "linear", "target_id": "fixture-project"},
    ],
}


def _initialize_state_loop(root):
    try:
        StateLoop(Ledger(root))
    except Exception as exc:  # Return worker failures to the test thread.
        return exc
    return None


class StateLoopTests(unittest.TestCase):
    def call(self, root, operation, data=None):
        return dispatch(root, {"operation": operation, "data": data or {}})

    def finish(self, root, event_id, key, outcome="confirmed", proof=None):
        claim = self.call(root, "projection_claim", {
            "event_id": event_id, "projection_key": key, "claimed_by": "fixture-worker"
        })
        return self.call(root, "projection_result", {
            "event_id": event_id,
            "projection_key": key,
            "claim_token": claim["claim_token"],
            "outcome": outcome,
            "proof": proof,
        })

    def test_schema_scopes_not_applicable_to_projection_results(self):
        Draft7Validator.check_schema(SCHEMA["parameters"])
        validator = Draft7Validator(SCHEMA["parameters"])

        projection_errors = list(validator.iter_errors({
            "operation": "projection_result",
            "data": {"outcome": "not_applicable"},
        }))
        native_errors = list(validator.iter_errors({
            "operation": "action_result",
            "data": {"outcome": "not_applicable"},
        }))
        native_confirmed_errors = list(validator.iter_errors({
            "operation": "action_result",
            "data": {"outcome": "confirmed"},
        }))

        self.assertEqual(projection_errors, [])
        self.assertEqual(native_confirmed_errors, [])
        self.assertEqual(len(native_errors), 1)
        self.assertEqual(native_errors[0].validator, "enum")

    def test_event_two_projections_complete_and_replay_without_duplicates(self):
        with tempfile.TemporaryDirectory() as root:
            created = self.call(root, "event_upsert", EVENT)
            self.assertFalse(created["replayed"])
            self.assertEqual(len(created["projections"]), 2)
            event_id = created["event_id"]

            self.finish(root, event_id, "account", proof={"readback_revision": "a1"})
            completed = self.finish(root, event_id, "commitment", proof={"provider_id": "fixture-1"})
            self.assertEqual(completed["status"], "complete")
            self.assertEqual(self.call(root, "reconcile"), {"issues": [], "count": 0})

            replayed = self.call(root, "event_upsert", EVENT)
            self.assertTrue(replayed["replayed"])
            self.assertEqual(replayed["status"], "complete")
            with Ledger(root).connect() as conn:
                self.assertEqual(conn.execute("select count(*) from pa_events").fetchone()[0], 1)
                self.assertEqual(conn.execute("select count(*) from pa_projections").fetchone()[0], 2)

    def test_new_source_revision_reopens_projections_and_archives_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            created = self.call(root, "event_upsert", EVENT)
            self.finish(root, created["event_id"], "account", proof={"readback_revision": "a1"})
            revised = dict(EVENT)
            revised["source_revision"] = "rev-2"
            revised["payload"] = {"summary_digest": "fixture-digest-2"}
            reopened = self.call(root, "event_upsert", revised)
            self.assertFalse(reopened["replayed"])
            self.assertEqual(reopened["status"], "pending")
            self.assertEqual({p["status"] for p in reopened["projections"]}, {"pending"})
            with Ledger(root).connect() as conn:
                history = conn.execute(
                    "select status from pa_projection_history where event_id=? and source_revision='rev-1' and projection_key='account'",
                    (created["event_id"],),
                ).fetchone()
            self.assertEqual(history[0], "confirmed")

    def test_same_revision_rejects_changed_content(self):
        with tempfile.TemporaryDirectory() as root:
            self.call(root, "event_upsert", EVENT)
            changed = dict(EVENT)
            changed["payload"] = {"summary_digest": "changed-without-revision"}
            with self.assertRaisesRegex(ValueError, "new source_revision"):
                self.call(root, "event_upsert", changed)

    def test_claim_token_guards_results_and_unknown_cannot_reclaim(self):
        with tempfile.TemporaryDirectory() as root:
            event_id = self.call(root, "event_upsert", EVENT)["event_id"]
            claim = self.call(root, "projection_claim", {
                "event_id": event_id, "projection_key": "account", "claimed_by": "fixture-worker"
            })
            with self.assertRaisesRegex(ValueError, "claim"):
                self.call(root, "projection_result", {
                    "event_id": event_id, "projection_key": "account", "claim_token": "wrong",
                    "outcome": "confirmed", "proof": {"readback": "fixture"}
                })
            self.call(root, "projection_result", {
                "event_id": event_id, "projection_key": "account", "claim_token": claim["claim_token"],
                "outcome": "unknown"
            })
            with self.assertRaisesRegex(ValueError, "does not permit"):
                self.call(root, "projection_claim", {
                    "event_id": event_id, "projection_key": "account", "claimed_by": "replay-worker"
                })
            issues = self.call(root, "reconcile", {"event_id": event_id})["issues"]
            self.assertEqual({row["status"] for row in issues}, {"unknown", "pending"})

    def test_failed_projection_is_reconcilable_and_may_be_explicitly_reclaimed(self):
        with tempfile.TemporaryDirectory() as root:
            event_id = self.call(root, "event_upsert", EVENT)["event_id"]
            self.finish(root, event_id, "account", outcome="failed", proof={"error": "fixture failure"})
            issues = self.call(root, "reconcile", {"event_id": event_id})
            self.assertEqual(issues["count"], 2)
            claim = self.call(root, "projection_claim", {
                "event_id": event_id, "projection_key": "account", "claimed_by": "recovery-worker"
            })
            self.assertTrue(claim["claim_token"])

    def test_old_source_revision_cannot_overwrite_newer_state(self):
        with tempfile.TemporaryDirectory() as root:
            self.call(root, "event_upsert", EVENT)
            revised = dict(EVENT)
            revised["source_revision"] = "rev-2"
            revised["payload"] = {"summary_digest": "fixture-digest-2"}
            self.call(root, "event_upsert", revised)
            with self.assertRaisesRegex(ValueError, "already processed"):
                self.call(root, "event_upsert", EVENT)

    def test_result_replay_is_idempotent_and_failed_attempt_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            event_id = self.call(root, "event_upsert", EVENT)["event_id"]
            claim = self.call(root, "projection_claim", {
                "event_id": event_id, "projection_key": "account", "claimed_by": "fixture-worker"
            })
            result = {
                "event_id": event_id, "projection_key": "account", "claim_token": claim["claim_token"],
                "outcome": "failed", "proof": {"error": "fixture failure"}
            }
            self.call(root, "projection_result", result)
            replayed = self.call(root, "projection_result", result)
            self.assertEqual(replayed["status"], "attention")
            self.call(root, "projection_claim", {
                "event_id": event_id, "projection_key": "account", "claimed_by": "recovery-worker"
            })
            with Ledger(root).connect() as conn:
                attempt = conn.execute(
                    "select outcome from pa_projection_attempts where claim_token=?", (claim["claim_token"],)
                ).fetchone()
            self.assertEqual(attempt[0], "failed")

    def test_unknown_projection_can_be_reconciled_with_same_claim(self):
        with tempfile.TemporaryDirectory() as root:
            event_id = self.call(root, "event_upsert", EVENT)["event_id"]
            claim = self.call(root, "projection_claim", {
                "event_id": event_id, "projection_key": "account", "claimed_by": "fixture-worker"
            })
            self.call(root, "projection_result", {
                "event_id": event_id, "projection_key": "account", "claim_token": claim["claim_token"],
                "outcome": "unknown"
            })
            reconciled = self.call(root, "projection_result", {
                "event_id": event_id, "projection_key": "account", "claim_token": claim["claim_token"],
                "outcome": "confirmed", "proof": {"provider_readback": "fixture-confirmed"}
            })
            self.assertEqual(
                next(p for p in reconciled["projections"] if p["projection_key"] == "account")["status"],
                "confirmed",
            )
            with Ledger(root).connect() as conn:
                outcomes = conn.execute(
                    "select outcome from pa_projection_attempts where claim_token=? order by outcome",
                    (claim["claim_token"],),
                ).fetchall()
            self.assertEqual({row[0] for row in outcomes}, {"unknown", "confirmed"})

    def test_new_revision_waits_for_unknown_or_active_projection_claim(self):
        with tempfile.TemporaryDirectory() as root:
            event_id = self.call(root, "event_upsert", EVENT)["event_id"]
            claim = self.call(root, "projection_claim", {
                "event_id": event_id, "projection_key": "account", "claimed_by": "fixture-worker"
            })
            revised = dict(EVENT)
            revised["source_revision"] = "rev-2"
            revised["payload"] = {"summary_digest": "fixture-digest-2"}
            with self.assertRaisesRegex(ValueError, "active projection claim"):
                self.call(root, "event_upsert", revised)
            self.call(root, "projection_result", {
                "event_id": event_id, "projection_key": "account", "claim_token": claim["claim_token"],
                "outcome": "unknown"
            })
            with self.assertRaisesRegex(ValueError, "unknown projection"):
                self.call(root, "event_upsert", revised)

    def test_expired_claim_cannot_finish_and_can_be_reclaimed(self):
        with tempfile.TemporaryDirectory() as root:
            event_id = self.call(root, "event_upsert", EVENT)["event_id"]
            claim = self.call(root, "projection_claim", {
                "event_id": event_id, "projection_key": "account", "claimed_by": "fixture-worker",
                "lease_seconds": 1, "at": "2026-09-11T01:00:00+00:00"
            })
            with self.assertRaisesRegex(ValueError, "lease expired"):
                self.call(root, "projection_result", {
                    "event_id": event_id, "projection_key": "account", "claim_token": claim["claim_token"],
                    "outcome": "confirmed", "proof": {"readback": "fixture"},
                    "at": "2026-09-11T01:00:02+00:00"
                })
            reclaimed = self.call(root, "projection_claim", {
                "event_id": event_id, "projection_key": "account", "claimed_by": "recovery-worker",
                "at": "2026-09-11T01:00:02+00:00"
            })
            self.assertNotEqual(reclaimed["claim_token"], claim["claim_token"])

    def test_confirmed_projection_becomes_stale_at_exact_freshness_deadline(self):
        with tempfile.TemporaryDirectory() as root:
            event = dict(EVENT)
            event["projections"] = [{
                "projection_key": "account",
                "target_type": "brain-page",
                "target_id": "accounts/fixture",
                "freshness_seconds": 3600,
            }]
            event_id = self.call(root, "event_upsert", event)["event_id"]
            claim = self.call(root, "projection_claim", {
                "event_id": event_id,
                "projection_key": "account",
                "claimed_by": "fixture-worker",
                "at": "2026-09-11T01:00:00+00:00",
            })
            self.call(root, "projection_result", {
                "event_id": event_id,
                "projection_key": "account",
                "claim_token": claim["claim_token"],
                "outcome": "confirmed",
                "proof": {"readback_revision": "a1"},
                "at": "2026-09-11T01:00:01+00:00",
            })

            before = self.call(root, "freshness", {
                "event_id": event_id,
                "at": "2026-09-11T02:00:00+00:00",
            })
            self.assertEqual(before, {
                "issues": [], "count": 0, "evaluated_at": "2026-09-11T02:00:00+00:00"
            })

            at_deadline = self.call(root, "freshness", {
                "event_id": event_id,
                "at": "2026-09-11T02:00:01+00:00",
            })
            self.assertEqual(at_deadline["count"], 1)
            self.assertEqual(at_deadline["issues"][0]["reason"], "freshness_expired")
            self.assertEqual(at_deadline["issues"][0]["fresh_until"], "2026-09-11T02:00:01+00:00")

    def test_new_revision_archives_freshness_and_starts_a_new_deadline(self):
        with tempfile.TemporaryDirectory() as root:
            event = dict(EVENT)
            event["projections"] = [{
                "projection_key": "account",
                "target_type": "brain-page",
                "target_id": "accounts/fixture",
                "freshness_seconds": 60,
            }]
            event_id = self.call(root, "event_upsert", event)["event_id"]
            claim = self.call(root, "projection_claim", {
                "event_id": event_id,
                "projection_key": "account",
                "claimed_by": "fixture-worker",
                "at": "2026-09-11T01:00:00+00:00",
            })
            self.call(root, "projection_result", {
                "event_id": event_id,
                "projection_key": "account",
                "claim_token": claim["claim_token"],
                "outcome": "confirmed",
                "proof": {"readback": "rev-1"},
                "at": "2026-09-11T01:00:01+00:00",
            })

            revised = dict(event)
            revised["source_revision"] = "rev-2"
            revised["payload"] = {"summary_digest": "fixture-digest-2"}
            reopened = self.call(root, "event_upsert", revised)

            self.assertIsNone(reopened["projections"][0]["fresh_until"])
            with Ledger(root).connect() as conn:
                archived = conn.execute(
                    """select freshness_seconds,fresh_until from pa_projection_freshness_history
                       where event_id=? and source_revision='rev-1' and projection_key='account'""",
                    (event_id,),
                ).fetchone()
            self.assertEqual(tuple(archived), (60, "2026-09-11T01:01:01+00:00"))

    def test_freshness_reports_pending_expired_failed_and_unknown_but_not_active_claims(self):
        with tempfile.TemporaryDirectory() as root:
            event = dict(EVENT)
            event["projections"] = [
                {"projection_key": key, "target_type": "fixture", "target_id": key}
                for key in ("active", "expired", "failed", "pending", "unknown")
            ]
            event_id = self.call(root, "event_upsert", event)["event_id"]
            for key, claimed_at, outcome in (
                ("active", "2026-09-11T01:00:00+00:00", None),
                ("expired", "2026-09-11T00:59:00+00:00", None),
                ("failed", "2026-09-11T01:00:00+00:00", "failed"),
                ("unknown", "2026-09-11T01:00:00+00:00", "unknown"),
            ):
                claim = self.call(root, "projection_claim", {
                    "event_id": event_id,
                    "projection_key": key,
                    "claimed_by": "fixture-worker",
                    "lease_seconds": 60 if key == "expired" else 300,
                    "at": claimed_at,
                })
                if outcome:
                    self.call(root, "projection_result", {
                        "event_id": event_id,
                        "projection_key": key,
                        "claim_token": claim["claim_token"],
                        "outcome": outcome,
                        "proof": {"error": "fixture"},
                        "at": "2026-09-11T01:00:01+00:00",
                    })

            result = self.call(root, "freshness", {
                "event_id": event_id,
                "at": "2026-09-11T01:00:30+00:00",
            })
            self.assertEqual(
                {item["projection_key"]: item["reason"] for item in result["issues"]},
                {
                    "expired": "overdue_projection",
                    "failed": "failed_projection",
                    "pending": "never_processed",
                    "unknown": "unknown_projection",
                },
            )

    def test_event_replay_preserves_confirmed_freshness_deadline(self):
        with tempfile.TemporaryDirectory() as root:
            event = dict(EVENT)
            event["projections"] = [{
                "projection_key": "account",
                "target_type": "brain-page",
                "target_id": "accounts/fixture",
                "freshness_seconds": 60,
            }]
            event_id = self.call(root, "event_upsert", event)["event_id"]
            claim = self.call(root, "projection_claim", {
                "event_id": event_id,
                "projection_key": "account",
                "claimed_by": "fixture-worker",
                "at": "2026-09-11T01:00:00+00:00",
            })
            self.call(root, "projection_result", {
                "event_id": event_id,
                "projection_key": "account",
                "claim_token": claim["claim_token"],
                "outcome": "confirmed",
                "proof": {"readback": "a1"},
                "at": "2026-09-11T01:00:01+00:00",
            })

            replayed = self.call(root, "event_upsert", event)

            self.assertTrue(replayed["replayed"])
            self.assertEqual(replayed["projections"][0]["fresh_until"], "2026-09-11T01:01:01+00:00")

    def test_freshness_requires_explicit_evaluation_time(self):
        with tempfile.TemporaryDirectory() as root:
            self.call(root, "event_upsert", EVENT)
            with self.assertRaisesRegex(ValueError, "explicit at"):
                self.call(root, "freshness")

    def test_freshness_duration_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as root:
            for invalid in (True, 0, -1, 315360001, 1.5, "60"):
                event = dict(EVENT)
                event["source_id"] = f"fixture-{invalid!r}"
                event["projections"] = [{
                    "projection_key": "account",
                    "target_type": "brain-page",
                    "target_id": "accounts/fixture",
                    "freshness_seconds": invalid,
                }]
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "freshness_seconds"):
                    self.call(root, "event_upsert", event)

    def test_concurrent_initializers_create_freshness_schema_without_races(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            with ledger.connect() as conn:
                conn.executescript("""
                    create table pa_projections(
                        event_id text not null, projection_key text not null, source_revision text not null,
                        target_type text not null, target_id text not null, expected_revision text,
                        status text not null, claim_token text, claimed_by text, claimed_at text,
                        lease_until text, result_json text, updated_at text not null,
                        primary key(event_id, projection_key));
                    create table pa_projection_history(
                        event_id text not null, source_revision text not null, projection_key text not null,
                        target_type text not null, target_id text not null, expected_revision text,
                        status text not null, claim_token text, claimed_by text, claimed_at text,
                        lease_until text, result_json text, archived_at text not null,
                        primary key(event_id, source_revision, projection_key));
                """)

            with ThreadPoolExecutor(max_workers=16) as pool:
                errors = [
                    error
                    for error in pool.map(
                        lambda _: _initialize_state_loop(root),
                        range(64),
                    )
                    if error is not None
                ]

            self.assertEqual(errors, [])
            with ledger.connect() as conn:
                table = conn.execute(
                    "select name from sqlite_master where type='table' and name='pa_projection_freshness'"
                ).fetchone()
            self.assertIsNotNone(table)

    def test_freshness_migration_preserves_previous_positional_inserts(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            StateLoop(ledger)
            with ledger.connect() as conn:
                conn.execute(
                    "insert into pa_events values(?,?,?,?,?,?,?,?,?)",
                    ("legacy-event", "fixture", "legacy", "rev-1", None, "{}", "pending",
                     "2026-09-11T00:00:00+00:00", "2026-09-11T00:00:00+00:00"),
                )
                conn.execute(
                    "insert into pa_projections values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("legacy-event", "account", "rev-1", "brain-page", "accounts/legacy", None,
                     "pending", None, None, None, None, None, "2026-09-11T00:00:00+00:00"),
                )
                conn.execute(
                    "insert into pa_projection_history values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("legacy-event", "rev-0", "account", "brain-page", "accounts/legacy", None,
                     "confirmed", None, None, None, None, "{}", "2026-09-10T00:00:00+00:00"),
                )
                history_table = conn.execute(
                    "select name from sqlite_master where type='table' and name='pa_projection_freshness_history'"
                ).fetchone()
                projection_count = conn.execute("select count(*) from pa_projections").fetchone()[0]
                history_count = conn.execute("select count(*) from pa_projection_history").fetchone()[0]

            self.assertIsNotNone(history_table)
            self.assertEqual(projection_count, 1)
            self.assertEqual(history_count, 1)

    def test_reenable_after_previous_package_revision_does_not_reuse_stale_freshness(self):
        with tempfile.TemporaryDirectory() as root:
            revision_one = {
                "source_type": "fixture-meeting",
                "source_id": "rollback-round-trip",
                "source_revision": "rev-1",
                "payload": {"summary_digest": "fixture-digest-1"},
                "occurred_at": "2026-09-11T01:00:00+00:00",
                "projections": [{
                    "projection_key": "account",
                    "target_type": "brain-page",
                    "target_id": "accounts/fixture",
                    "freshness_seconds": 60,
                }],
            }
            created = self.call(root, "event_upsert", revision_one)
            event_id = created["event_id"]
            claim = self.call(root, "projection_claim", {
                "event_id": event_id,
                "projection_key": "account",
                "claimed_by": "fixture-worker",
                "at": "2026-09-11T01:00:00+00:00",
            })
            self.call(root, "projection_result", {
                "event_id": event_id,
                "projection_key": "account",
                "claim_token": claim["claim_token"],
                "outcome": "confirmed",
                "proof": {"readback_revision": "a1"},
                "at": "2026-09-11T01:00:01+00:00",
            })

            # Reproduce the previous package's positional revision transition. It
            # cannot know about or update the candidate's freshness sidecar.
            ledger = Ledger(root)
            with ledger.connect() as conn:
                conn.execute("begin immediate")
                conn.execute(
                    """insert or replace into pa_projection_history
                       select event_id,source_revision,projection_key,target_type,target_id,expected_revision,status,
                              claim_token,claimed_by,claimed_at,lease_until,result_json,?
                       from pa_projections where event_id=?""",
                    ("2026-09-11T02:00:00+00:00", event_id),
                )
                conn.execute("delete from pa_projections where event_id=?", (event_id,))
                conn.execute(
                    """update pa_events set source_revision='rev-2',payload_json=?,status='complete',updated_at=?
                       where event_id=?""",
                    ('{"summary_digest":"fixture-digest-2"}', "2026-09-11T02:00:01+00:00", event_id),
                )
                conn.execute(
                    "insert into pa_event_revisions values(?,?,?,?,?)",
                    (event_id, "rev-2", "2026-09-11T01:00:00+00:00",
                     '{"summary_digest":"fixture-digest-2"}', "2026-09-11T02:00:00+00:00"),
                )
                conn.execute(
                    "insert into pa_projections values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, "account", "rev-2", "brain-page", "accounts/fixture", None,
                     "confirmed", None, None, None, None,
                     '{"outcome":"confirmed","proof":{"readback_revision":"a2"},"recorded_at":"2026-09-11T02:00:01+00:00"}',
                     "2026-09-11T02:00:01+00:00"),
                )

            StateLoop(ledger)  # Re-enable the candidate after rollback.
            self.assertEqual(self.call(root, "freshness", {
                "event_id": event_id,
                "at": "2026-09-11T03:00:00+00:00",
            })["issues"], [])

            revision_two = dict(revision_one)
            revision_two["source_revision"] = "rev-2"
            revision_two["payload"] = {"summary_digest": "fixture-digest-2"}
            revision_two["projections"] = [{
                "projection_key": "account",
                "target_type": "brain-page",
                "target_id": "accounts/fixture",
            }]
            self.assertTrue(self.call(root, "event_upsert", revision_two)["replayed"])
            with ledger.connect() as conn:
                current_count = conn.execute(
                    "select count(*) from pa_projection_freshness where event_id=?", (event_id,)
                ).fetchone()[0]
                archived = conn.execute(
                    """select freshness_seconds,fresh_until from pa_projection_freshness_history
                       where event_id=? and source_revision='rev-1' and projection_key='account'""",
                    (event_id,),
                ).fetchone()
            self.assertEqual(current_count, 0)
            self.assertEqual(tuple(archived), (60, "2026-09-11T01:01:01+00:00"))

    def test_schema_is_additive_and_preserves_existing_actions(self):
        with tempfile.TemporaryDirectory() as root:
            action = self.call(root, "action_upsert", {
                "action_id": "fixture-action", "fields": {"next_action": "preserve"}
            })
            self.assertEqual(action["action_id"], "fixture-action")
            self.call(root, "event_upsert", EVENT)
            preserved = Ledger(root).get("action", "fixture-action")
            self.assertEqual(preserved["fields"]["next_action"], "preserve")


if __name__ == "__main__":
    unittest.main()
