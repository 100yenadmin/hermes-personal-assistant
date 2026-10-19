import sqlite3
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from personal_assistant.context import next_actions, read_kanban_task, retrieve, status_snapshot
from personal_assistant.state import Ledger
from personal_assistant.trips import import_trip


ICS = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:source-1\r\nDTSTART;TZID=Asia/Seoul:20260906T130000\r\nDTEND;TZID=Asia/Seoul:20260906T140000\r\nSUMMARY:Meet\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"


class ContextTests(unittest.TestCase):
    def test_native_kanban_reader_uses_exact_read_only_store(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "kanban.db"
            with sqlite3.connect(path) as conn:
                conn.execute("create table tasks(id text primary key, status text)")
                conn.execute("insert into tasks values('linked-task', 'done')")
            fake_kb = SimpleNamespace(
                kanban_db_path=lambda board=None: path,
                get_task=lambda conn, task_id: (
                    SimpleNamespace(status=row["status"])
                    if (row := conn.execute("select status from tasks where id=?", (task_id,)).fetchone())
                    else None),
            )
            hermes_cli = ModuleType("hermes_cli")
            hermes_cli.kanban_db = fake_kb
            with patch.dict(sys.modules, {"hermes_cli": hermes_cli}):
                result = read_kanban_task("linked-task")
            self.assertEqual(result["status"], "done")
            self.assertIn("read-only", result["evidence"])

    def test_trip_source_guide_and_status_are_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            import_trip(ledger, "trip-1", ICS, guide="Packing\nBring a rain coat\nMeeting notes")
            trip = retrieve(ledger, {"kind": "trip", "trip_id": "trip-1", "limit": 1})
            self.assertEqual((trip["total"], trip["events"][0]["uid"]), (1, "source-1"))
            source_id = trip["events"][0]["source_record_id"]
            source = retrieve(ledger, {"kind": "source", "source_id": source_id})
            self.assertEqual(source["items"][0]["record_kind"], "trip_event")
            guide = retrieve(ledger, {"kind": "guide", "trip_id": "trip-1", "query": "rain"})
            self.assertTrue(guide["matched"])
            self.assertIn("rain coat", guide["content"])
            status = status_snapshot(ledger)
            self.assertEqual((status["trip_count"], status["trips"][0]["event_count"]), (1, 1))
            self.assertNotIn("fields", status["trips"][0])

    def test_next_action_excludes_native_done_and_keeps_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            for action_id, task_id, next_step in (
                    ("done-action", "done-task", "should disappear"),
                    ("ready-action", "ready-task", "continue ready work"),
                    ("unknown-action", "unknown-task", "keep unknown work")):
                ledger.put("action", action_id,
                           {"kanban_task_id": task_id, "next_action": next_step},
                           action_type="commitment")
            states = {
                "done-task": {"status": "done", "evidence": "fixture native read"},
                "ready-task": {"status": "ready", "evidence": "fixture native read"},
                "unknown-task": {"status": "unknown", "evidence": "fixture adapter unavailable"},
            }

            result = next_actions(ledger, kanban_reader=lambda task_id, board: states[task_id])
            ids = {item["action_id"] for item in result["candidates"]}
            self.assertEqual(ids, {"ready-action", "unknown-action"})
            self.assertEqual(result["excluded_completed"], 1)
            unknown = next(item for item in result["candidates"] if item["action_id"] == "unknown-action")
            self.assertEqual(unknown["commitment_status"], "unknown")

    def test_transaction_recovery_step_never_suggests_resubmit(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            summary = {"provider": "fixture", "final_action": "submit", "total": "10"}
            ledger.prepare("tx", summary)
            ledger.confirm("tx", summary, "confirm fixture")
            ledger.claim_submission("tx", summary)
            ledger.result("tx", "unknown", None)
            result = next_actions(
                ledger, kanban_reader=lambda task_id, board: {
                    "status": "unknown", "evidence": "no linked Kanban task"})
            self.assertIn("do not submit again", result["candidates"][0]["next_step"])

    def test_waiting_paused_and_unlinked_terminal_are_not_fresh_execution(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            ledger.put("action", "paused", {"waiting_for": "owner response", "recheck_at": "tomorrow"},
                       status="paused", action_type="commitment")
            ledger.put("action", "snoozed", {"snoozed_until": "2026-09-10T09:00:00+07:00"},
                       action_type="commitment")
            ledger.put("action", "old", {"next_action": "should not run"},
                       status="completed", action_type="commitment")
            result = next_actions(
                ledger, kanban_reader=lambda task_id, board: {
                    "status": "unknown", "evidence": "no linked Kanban task"})
            by_id = {item["action_id"]: item for item in result["candidates"]}
            self.assertEqual(set(by_id), {"paused", "snoozed"})
            self.assertIn("do not execute now", by_id["paused"]["next_step"])
            self.assertIn("do not execute now", by_id["snoozed"]["next_step"])
            self.assertEqual(result["excluded_terminal_unlinked"], 1)


if __name__ == "__main__":
    unittest.main()
