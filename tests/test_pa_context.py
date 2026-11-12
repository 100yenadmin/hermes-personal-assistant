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

    def test_owner_chase_time_pulls_the_next_chase_earlier(self):
        # #215: "chase them tomorrow morning" on a loop opened yesterday; the ladder alone says day 2.
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            ledger.put("action", "pa:preferences", {"timezone": "Asia/Tokyo"}, action_type="preferences")
            _loop(ledger, "asked-due", 1, chase_at="2026-11-20T09:00:00+09:00")
            _loop(ledger, "asked-later-today", 1, chase_at="2026-11-20T11:00:00+09:00")
            _loop(ledger, "asked-after-day2", 1, chase_at="2026-11-23T09:00:00+09:00")
            _loop(ledger, "asked-date-only", 1, chase_at="2026-11-20")
            result = self._read(ledger, loops_only=True)
            by_id = {item["action_id"]: item for item in result["candidates"]}
            chase = {key: (item["chase"]["step"], item["chase"]["next_chase_at"]) for key, item in by_id.items()}
            self.assertEqual(chase["asked-due"], ("day2", "2026-11-20T09:00:00+09:00"))
            self.assertEqual(chase["asked-later-today"], ("none", "2026-11-20T11:00:00+09:00"))
            self.assertEqual(chase["asked-after-day2"], ("none", "2026-11-23T09:00:00+09:00"))  # Later too.
            self.assertEqual(chase["asked-date-only"], ("day2", "2026-11-20T00:00:00+09:00"))
            self.assertEqual(by_id["asked-due"]["chase_at"], "2026-11-20T09:00:00+09:00")

    def test_a_chase_at_the_owner_time_completes_that_step_once(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            ledger.put("action", "pa:preferences", {"timezone": "Asia/Tokyo"}, action_type="preferences")
            _loop(ledger, "chased-then", 1, chase_at="2026-11-20T09:00:00+09:00",
                  last_chased_at="2026-11-20T09:30:00+09:00",
                  chase_log=[{"at": "2026-11-20T09:30:00+09:00", "step": "day2", "how": "nudge draft held"}])
            _loop(ledger, "chased-before", 1, chase_at="2026-11-20T09:00:00+09:00",
                  last_chased_at="2026-11-20T08:00:00+09:00")
            by_id = {item["action_id"]: item["chase"] for item in self._read(ledger)["candidates"]}
            # Day 2 is done; the next chase is day 5 from opened_at, not day 2 again tomorrow.
            self.assertEqual((by_id["chased-then"]["step"], by_id["chased-then"]["next_chase_at"]),
                             ("none", "2026-11-24T00:00:00+09:00"))
            # A chase before the owner's time leaves the asked chase due.
            self.assertEqual((by_id["chased-before"]["step"], by_id["chased-before"]["next_chase_at"]),
                             ("day2", "2026-11-20T09:00:00+09:00"))
            day2 = next_actions(ledger, {"at": "2026-11-21T10:00:00+09:00", "limit": 20},
                                kanban_reader=lambda task_id, board: UNKNOWN)
            self.assertEqual({i["action_id"]: i["chase"]["step"] for i in day2["candidates"]}["chased-then"], "none")

    def test_owner_chase_time_review_cases(self):
        # Reviews of #217: same-day reschedule, a replaced time after a chase, a chase with no log,
        # a DST fold, a stale time from before the loop, a far time, and a log entry naming its step.
        def chase(zone, at, age_or_opened, **fields):
            with tempfile.TemporaryDirectory() as root:
                ledger = Ledger(root)
                ledger.put("action", "pa:preferences", {"timezone": zone}, action_type="preferences")
                if isinstance(age_or_opened, str):
                    _loop(ledger, "loop", 0, opened_at=age_or_opened, **fields)
                else:
                    _loop(ledger, "loop", age_or_opened, **fields)
                item = next_actions(ledger, {"at": at, "limit": 20},
                                    kanban_reader=lambda task_id, board: UNKNOWN)["candidates"][0]["chase"]
                return item["step"], item["next_chase_at"]

        tokyo = "Asia/Tokyo"
        # Day 2 is due today; "chase them at 15:00 today" holds it until 15:00, then it is one chase.
        self.assertEqual(chase(tokyo, AT, 2, chase_at="2026-11-20T15:00:00+09:00"),
                         ("none", "2026-11-20T15:00:00+09:00"))
        self.assertEqual(chase(tokyo, "2026-11-20T16:00:00+09:00", 2, chase_at="2026-11-20T15:00:00+09:00",
                               last_chased_at="2026-11-20T15:05:00+09:00"), ("none", "2026-11-23T00:00:00+09:00"))
        # A pulled chase made with no log entry still completes day 2; a new time later replaces day 2's date.
        self.assertEqual(chase(tokyo, "2026-11-21T10:00:00+09:00", 1, chase_at="2026-11-20T09:00:00+09:00",
                               last_chased_at="2026-11-20T09:30:00+09:00"), ("none", "2026-11-24T00:00:00+09:00"))
        self.assertEqual(chase(tokyo, "2026-11-21T10:00:00+09:00", 1, chase_at="2026-11-22T09:00:00+09:00",
                               last_chased_at="2026-11-20T09:30:00+09:00"), ("none", "2026-11-22T09:00:00+09:00"))
        # DST fold: 01:45 EDT is 45 minutes before 01:30 EST. That chase was day 2's; the owner's
        # 01:30 EST chase is still due as the next one, not answered by it.
        self.assertEqual(chase("America/New_York", "2026-11-01T02:00:00-05:00", "2026-10-30T09:00:00-04:00",
                               chase_at="2026-11-01T01:30:00-05:00", last_chased_at="2026-11-01T01:45:00-04:00"),
                         ("day5", "2026-11-01T01:30:00-05:00"))
        # A time from before the loop opened is ignored.
        self.assertEqual(chase(tokyo, AT, 1, chase_at="2026-11-02T09:00:00+09:00",
                               last_chased_at="2026-11-02T09:30:00+09:00")[1], "2026-11-21T00:00:00+09:00")
        # A far time folds day 2, 5 and 10; escalation waits until a day after the owner's chase.
        far = "2026-12-05T09:00:00+09:00"
        self.assertEqual(chase(tokyo, AT, 1, chase_at=far), ("none", far))
        self.assertEqual(chase(tokyo, "2026-11-30T10:00:00+09:00", 1, chase_at=far), ("none", far))
        self.assertEqual(chase(tokyo, "2026-12-05T10:00:00+09:00", 1, chase_at=far)[0], "day10")
        self.assertEqual(chase(tokyo, "2026-12-05T10:00:00+09:00", 1, chase_at=far,
                               last_chased_at="2026-12-05T09:10:00+09:00"), ("none", "2026-12-06T09:00:00+09:00"))
        self.assertEqual(chase(tokyo, "2026-12-06T10:00:00+09:00", 1, chase_at=far,
                               last_chased_at="2026-12-05T09:10:00+09:00")[0], "escalate")
        # After day 10 or an escalation, the owner's "chase them once more" is still a chase (Claude round 3).
        late = [{"at": "2026-11-29T09:05:00+09:00", "step": "day10", "how": "nudge sent"}]
        self.assertEqual(chase(tokyo, "2026-12-07T09:01:00+09:00", 1, chase_at="2026-12-07T09:00:00+09:00",
                               last_chased_at="2026-11-30T09:00:00+09:00",
                               chase_log=late + [{"at": "2026-11-30T09:00:00+09:00", "step": "escalate",
                                                  "how": "packet in brief"}]),
                         ("day10", "2026-12-07T09:00:00+09:00"))
        thursday = "2026-12-04T09:00:00+09:00"
        self.assertEqual(chase(tokyo, "2026-12-02T10:00:00+09:00", 1, chase_at=thursday,
                               last_chased_at="2026-11-29T09:05:00+09:00", chase_log=late), ("none", thursday))
        self.assertEqual(chase(tokyo, "2026-12-04T09:01:00+09:00", 1, chase_at=thursday,
                               last_chased_at="2026-11-29T09:05:00+09:00", chase_log=late)[0], "day10")
        self.assertEqual(chase(tokyo, "2026-12-04T10:00:00+09:00", 1, chase_at=thursday,
                               last_chased_at="2026-12-04T09:10:00+09:00", chase_log=late),
                         ("none", "2026-12-05T09:00:00+09:00"))
        # A chase_log entry naming day2 completes it even before day 2's date.
        early = (dt.datetime.fromisoformat(AT) - dt.timedelta(hours=1)).isoformat()
        self.assertEqual(chase(tokyo, "2026-11-21T10:00:00+09:00", 1, last_chased_at=early,
                               chase_log=[{"at": early, "step": "day2", "how": "nudge draft held"}]),
                         ("none", "2026-11-24T00:00:00+09:00"))

    def test_chase_at_is_validated_and_clearable(self):
        with tempfile.TemporaryDirectory() as root:
            base = {"loop_kind": "waiting_on_them", "counterparty": "Cedar", "next_actor": "them",
                    "opened_at": "2026-11-19T10:00:00+09:00", "next_step": "Chase the contract"}
            for bad in ("tomorrow morning", 20261120, {"at": "2026-11-20"}):
                with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "chase_at"):
                    dispatch(root, {"operation": "action_upsert", "data": {
                        "action_id": "cedar", "action_type": "commitment", "fields": {**base, "chase_at": bad}}})
            saved = dispatch(root, {"operation": "action_upsert", "data": {
                "action_id": "cedar", "action_type": "commitment",
                "fields": {**base, "chase_at": "2026-11-20T09:00:00+09:00"}}})
            self.assertEqual(saved["fields"]["chase_at"], "2026-11-20T09:00:00+09:00")
            cleared = dispatch(root, {"operation": "action_upsert", "data": {
                "action_id": "cedar", "fields": {"chase_at": ""}}})
            self.assertEqual(cleared["fields"]["chase_at"], "")

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

    def test_inbox_rows_are_loops_and_close_on_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            ledger.put("action", "pa:inbox:work:thread-1", {"loop_kind": "ask_owner", "counterparty": "owner",
                       "next_actor": "owner", "opened_at": "2026-11-17T09:00:00+09:00"}, action_type="commitment")
            ledger.put("action", "pa:inbox:personal:thread-2", {"loop_kind": "waiting_on_them", "counterparty": "Sam",
                       "next_actor": "them", "opened_at": "2026-11-15T09:00:00+09:00",
                       "confirmation": {"by": "Sam", "at": AT, "evidence": "reply read back"}}, action_type="commitment")
            result = self._read(ledger, loops_only=True)
            self.assertEqual([item["action_id"] for item in result["candidates"]], ["pa:inbox:work:thread-1"])
            self.assertEqual(result["candidates"][0]["chase"]["step"], "day2")
            self.assertEqual(result["excluded_closed_loops"], 1)

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


def test_chase_receipt_key_keeps_legacy_loops_and_times_owner_chases():
    # Claude review of #217: an owner's extra chase reuses a step label, so its receipt carries the time.
    from personal_assistant import automation as auto
    from personal_assistant.automation_workflow import _chase_marker
    ladder = {"action_id": "loop", "chase": {"step": "day10", "next_chase_at": "2026-11-29T00:00:00+09:00"}}
    assert _chase_marker(ladder) == auto.notification_occurrence_id("chase-step", "loop", "day10")
    owner = {**ladder, "chase_at": "2026-12-07T09:00:00+09:00",
             "chase": {"step": "day10", "next_chase_at": "2026-12-07T09:00:00+09:00"}}
    again = {**owner, "chase": {"step": "day10", "next_chase_at": "2026-12-14T09:00:00+09:00"}}
    assert len({_chase_marker(ladder), _chase_marker(owner), _chase_marker(again)}) == 3
    assert _chase_marker(owner) == _chase_marker(dict(owner))
