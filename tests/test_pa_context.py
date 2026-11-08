import datetime as dt
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from personal_assistant.context import next_actions, read_kanban_task, retrieve, status_snapshot
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger
from personal_assistant.trips import import_trip


ICS = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:source-1\r\nDTSTART;TZID=Asia/Seoul:20260906T130000\r\nDTEND;TZID=Asia/Seoul:20260906T140000\r\nSUMMARY:Meet\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"


class ContextTests(unittest.TestCase):
    def test_l39_infers_context_kind_from_one_id(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            import_trip(ledger, "trip-1", ICS)
            ledger.put("action", "action-1", {"source_record_id": "source-1"})
            for kind, identity in (("trip", "trip-1"), ("action", "action-1"), ("source", "source-1")):
                for explicit in ({}, {"kind": ""}, {"kind": None}):
                    with self.subTest(kind=kind, explicit=explicit):
                        result = retrieve(ledger, {kind + "_id": identity, **explicit})
                        self.assertEqual(result["kind"], kind)

    def test_l39_context_kind_errors_are_actionable(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            for data in ({}, {"trip_id": "t", "action_id": "a"}, {"trip_id": "t", "source_id": "s"},
                         {"action_id": "a", "source_id": "s"}, {"trip_id": "t", "query": "rain"},
                         {"kind": "invalid", "source_id": "s"}):
                with self.subTest(data=data), self.assertRaises(ValueError) as exc:
                    retrieve(ledger, data)
                self.assertEqual(str(exc.exception), "context needs kind (trip, action, source, or guide); guide takes trip_id plus optional query")

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


AT = "2026-11-20T10:00:00+09:00"
UNKNOWN = {"status": "unknown", "evidence": "fixture adapter unavailable"}


def _loop(ledger, action_id, age_days, **fields):
    opened = (dt.datetime.fromisoformat(AT) - dt.timedelta(days=age_days)).isoformat()
    ledger.put("action", action_id, {"title": action_id, "loop_kind": "waiting_on_them", "counterparty": "Landlord",
                                     "next_actor": "them", "opened_at": opened, **fields}, action_type="commitment")


class OpenLoopTests(unittest.TestCase):
    def _read(self, ledger, states=None, **data):
        return next_actions(ledger, {"at": AT, "limit": 20, **data},
                            kanban_reader=lambda task_id, board: (states or {}).get(task_id, UNKNOWN))

    def test_chase_ladder_steps_by_age_in_owner_timezone(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            ledger.put("action", "pa:preferences", {"timezone": "Asia/Tokyo"}, action_type="preferences")
            for age in (1, 2, 5, 10, 11):
                _loop(ledger, f"loop-{age:02d}", age)
            result = self._read(ledger, loops_only=True)
            steps = {item["action_id"]: item["chase"]["step"] for item in result["candidates"]}
            self.assertEqual(steps, {"loop-01": "none", "loop-02": "day2", "loop-05": "day5",
                                     "loop-10": "day10", "loop-11": "escalate"})
            by_id = {item["action_id"]: item for item in result["candidates"]}
            self.assertEqual(by_id["loop-01"]["chase"]["age_days"], 1)
            self.assertEqual(by_id["loop-01"]["chase"]["next_chase_at"], "2026-11-21T00:00:00+09:00")
            self.assertEqual(result["owner_timezone"], "Asia/Tokyo")
            self.assertIn("hold it for the owner's yes", by_id["loop-05"]["next_step"])
            self.assertIn("decision_deadline", by_id["loop-11"]["next_step"])

    def test_age_counts_owner_local_days(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            ledger.put("action", "pa:preferences", {"timezone": "Asia/Tokyo"}, action_type="preferences")
            # 23:30 Tokyo two days earlier is 14:30 UTC; local days give day2, UTC hours alone would not.
            _loop(ledger, "late-evening", 0, opened_at="2026-11-18T14:30:00+00:00")
            item = self._read(ledger, loops_only=True)["candidates"][0]
            self.assertEqual((item["chase"]["age_days"], item["chase"]["step"]), (2, "day2"))

    def test_recorded_chase_moves_the_step_on(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            chased = (dt.datetime.fromisoformat(AT) - dt.timedelta(hours=1)).isoformat()
            _loop(ledger, "chased-day5", 5, last_chased_at=chased,
                  chase_log=[{"at": chased, "step": "day5", "how": "nudge draft approved"}])
            _loop(ledger, "chased-day2-only", 6,
                  last_chased_at=(dt.datetime.fromisoformat(AT) - dt.timedelta(days=4)).isoformat())
            _loop(ledger, "escalated", 12, last_chased_at=chased,
                  chase_log=[{"at": chased, "step": "escalate", "how": "packet in brief"}])
            by_id = {item["action_id"]: item["chase"] for item in self._read(ledger)["candidates"]}
            self.assertEqual(by_id["chased-day5"]["step"], "none")
            self.assertEqual(by_id["chased-day5"]["next_chase_at"], "2026-11-25T00:00:00+00:00")
            self.assertEqual(by_id["chased-day2-only"]["step"], "day5")
            self.assertEqual((by_id["escalated"]["step"], by_id["escalated"]["escalated"]), ("none", True))
            self.assertIsNone(by_id["escalated"]["next_chase_at"])

    def test_snooze_holds_the_ladder(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            _loop(ledger, "snoozed", 5, snoozed_until="2026-11-22T09:00:00+00:00")
            chase = self._read(ledger)["candidates"][0]["chase"]
            self.assertEqual((chase["step"], chase["next_chase_at"]), ("none", "2026-11-22T09:00:00+00:00"))

    def test_only_confirmation_closes_a_loop(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            _loop(ledger, "done-unconfirmed", 3, kanban_task_id="done-task")
            _loop(ledger, "completed-unconfirmed", 3, status_note="no reply")
            ledger.put("action", "completed-unconfirmed", {}, status="completed")
            _loop(ledger, "confirmed", 3, kanban_task_id="done-task2",
                  confirmation={"by": "Landlord", "at": AT, "evidence": "email reply read back"})
            _loop(ledger, "withdrawn", 3)
            ledger.put("action", "withdrawn", {}, status="cancelled")
            ledger.put("action", "plain-done", {"kanban_task_id": "done-task3"}, action_type="commitment")
            states = {f"done-task{n}": {"status": "done", "evidence": "fixture"} for n in ("", "2", "3")}
            result = self._read(ledger, states)
            by_id = {item["action_id"]: item for item in result["candidates"]}
            self.assertEqual(set(by_id), {"done-unconfirmed", "completed-unconfirmed"})
            self.assertEqual(by_id["done-unconfirmed"]["loop_state"], "done_unconfirmed")
            self.assertEqual(by_id["done-unconfirmed"]["commitment_status"], "done")
            self.assertEqual(by_id["completed-unconfirmed"]["loop_state"], "done_unconfirmed")
            self.assertIn("record fields.confirmation", by_id["done-unconfirmed"]["next_step"])
            self.assertEqual((result["excluded_closed_loops"], result["excluded_completed"]), (2, 1))

    def test_non_loop_commitments_are_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            ledger.put("action", "r7-renewal", {"title": "Renew insurance", "due_at": "2026-11-25",
                                                "next_action": "Decide renew or cancel", "kanban_task_id": "t1"},
                       action_type="commitment")
            ledger.put("action", "r5-done", {"kanban_task_id": "t2"}, action_type="commitment")
            _loop(ledger, "a-loop", 2)
            result = self._read(ledger, {"t1": {"status": "ready", "evidence": "fixture"},
                                         "t2": {"status": "done", "evidence": "fixture"}})
            plain = next(item for item in result["candidates"] if item["action_id"] == "r7-renewal")
            self.assertEqual(plain["next_step"], "Decide renew or cancel")
            self.assertNotIn("chase", plain)
            self.assertNotIn("loop_kind", plain)
            self.assertEqual(result["excluded_completed"], 1)
            only = self._read(ledger, {"t1": {"status": "ready", "evidence": "fixture"}}, loops_only=True)
            self.assertEqual([item["action_id"] for item in only["candidates"]], ["a-loop"])

    def test_upsert_validates_loop_enums_and_bounds_chase_log(self):
        with tempfile.TemporaryDirectory() as root:
            log = [{"at": f"2026-11-{day:02d}T09:00:00+00:00", "step": "day2", "how": "reminder"} for day in range(1, 16)]
            saved = dispatch(root, {"operation": "action_upsert", "data": {
                "action_id": "ask-1", "action_type": "commitment", "fields": {
                    "loop_kind": "ask_owner", "counterparty": "owner", "next_actor": "owner",
                    "opened_at": "2026-11-01T09:00:00+00:00", "next_step": "Book once the owner picks a date",
                    "chase_log": log}}})
            self.assertEqual(len(saved["fields"]["chase_log"]), 10)
            self.assertEqual(saved["fields"]["chase_log"][-1], log[-1])
            for bad in ({"loop_kind": "someday"}, {"next_actor": "anyone"}, {"confirmation": "yes"}):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    dispatch(root, {"operation": "action_upsert", "data": {
                        "action_id": "ask-2", "action_type": "commitment", "fields": bad}})
            listed = dispatch(root, {"operation": "next_action", "data": {"loops_only": True, "at": AT}})
            self.assertEqual(listed["candidates"][0]["loop_kind"], "ask_owner")


if __name__ == "__main__":
    unittest.main()
