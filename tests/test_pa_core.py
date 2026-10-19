import datetime as dt
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from icalendar import Calendar
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger
from personal_assistant.trips import import_trip, export_trip

ROOT = Path(__file__).resolve().parents[1]
ICS = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:timed-1\r\nDTSTART;TZID=Asia/Seoul:20260906T130000\r\nDTEND;TZID=Asia/Seoul:20260906T140000\r\nSUMMARY:Meet\r\nDESCRIPTION:Map https://example.org/map\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:day-1\r\nDTSTART;VALUE=DATE:20260907\r\nDTEND;VALUE=DATE:20260909\r\nSUMMARY:Travel\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"


class CoreTests(unittest.TestCase):
    def test_managed_ancestors_allow_status_and_existing_default_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o2770)
            state = root / "state"
            state.mkdir(mode=0o770)
            state.chmod(0o770)
            self.assertEqual(dispatch(root, {"operation": "status"})["plugin"], "personal-assistant")
            ledger = Ledger(root)
            ledger.put("trip", "existing", {}, title="Existing", status="planning")
            self.assertEqual(dispatch(root, {"operation": "status"})["trip_count"], 1)
            self.assertEqual(stat.S_IMODE(ledger.path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(ledger.path.stat().st_mode), 0o600)

    def test_cli_reports_permission_diagnostic_without_masking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            state.mkdir(mode=0o770)
            state.chmod(0o770)
            command = [sys.executable, "-m", "personal_assistant", "--profile-root", str(root)]
            request = json.dumps({"operation": "status"})
            ok = subprocess.run(command, input=request, text=True, capture_output=True, cwd=ROOT)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(ok.stdout)["plugin"], "personal-assistant")
            state.chmod(0o777)
            rejected = subprocess.run(command, input=request, text=True, capture_output=True, cwd=ROOT)
            self.assertEqual(rejected.returncode, 1)
            error = json.loads(rejected.stdout)
            self.assertEqual(error["error"], "RuntimeError")
            self.assertIn(f"ledger directory {state.resolve()} has world-writable permissions", error["message"])

    def test_native_override_is_honoured_and_confined(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "profile"
            root.mkdir(mode=0o700)
            outside = Path(tmp) / "outside"
            with patch.dict(os.environ, {"TRAVEL_LEDGER_DB": "custom/travel.sqlite"}):
                self.assertEqual(Ledger(root).path, (root / "custom" / "travel.sqlite").resolve())
            with patch.dict(os.environ, {"TRAVEL_LEDGER_DB": str(outside / "travel.sqlite")}):
                with self.assertRaisesRegex(ValueError, "remain within active profile"):
                    Ledger(root)

    def test_explicit_action_id_accepts_documented_identity_components(self):
        with tempfile.TemporaryDirectory() as root:
            args = {"operation": "action_upsert", "data": {"action_id": "request-1", "source_id": "fixture-source", "action_kind": "booking", "occurrence": "one", "fields": {"next_action": "prepare"}}}
            self.assertEqual(dispatch(root, args)["action_id"], "request-1")
            dispatch(root, args)
            self.assertEqual(len(Ledger(root).list("action")), 1)

    def test_import_export_restart_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(tmp)
            result = import_trip(ledger, "synthetic-trip", ICS, guide="Shared guide: 가져오세요")
            self.assertEqual((result["timed"], result["all_day"]), (1, 1))
            import_trip(Ledger(tmp), "synthetic-trip", ICS)
            self.assertEqual(len(ledger.list("trip")), 1)
            out = export_trip(ledger, "synthetic-trip", Path(tmp) / "export")
            events = Calendar.from_ical(Path(out["calendar"]).read_bytes()).walk("VEVENT")
            self.assertEqual([str(e["UID"]) for e in events], ["timed-1", "day-1"])
            self.assertEqual(events[0].decoded("DTSTART").astimezone(dt.timezone.utc).hour, 4)
            self.assertEqual(events[1].decoded("DTEND"), dt.date(2026, 9, 9))
            self.assertIn("가져오세요", Path(out["reference"]).read_text())
            self.assertEqual(dispatch(tmp, {"operation": "status"})["plugin"], "personal-assistant")

    def test_uncertain_transaction_never_reclaims(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(tmp)
            identity = ledger.action_id("source", "booking", "occurrence-1")
            self.assertEqual(identity, Ledger(tmp).action_id("source", "booking", "occurrence-1"))
            summary = {"provider": "fixture", "final_action": "book", "total": "10 KRW"}
            ledger.prepare(identity, summary)
            ledger.confirm(identity, summary, "Explicit fixture confirmation")
            ledger.claim_submission(identity, summary)
            ledger.result(identity, "unknown", None)
            with self.assertRaises(ValueError):
                Ledger(tmp).claim_submission(identity, summary)
            with self.assertRaises(ValueError):
                ledger.prepare(identity, summary)

    def test_source_removal_pauses_derived_reminder_and_partial_keeps_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(tmp)
            import_trip(ledger, "trip", ICS)
            source = ledger.get("trip", "trip")["fields"]["events"][0]["source_record_id"]
            ledger.put("action", "reminder", {"source_record_id": source, "source_fields": ["end"], "derived_fields": ["due_at"], "due_at": "2026-09-06T15:00:00+09:00"})
            partial = Calendar.from_ical(ICS)
            partial.subcomponents.pop()
            import_trip(ledger, "trip", partial.to_ical(), complete=False, removals={source: ["end"]})
            self.assertEqual(len(ledger.get("trip", "trip")["fields"]["events"]), 2)
            row = ledger.get("action", "reminder")
            self.assertEqual(row["status"], "paused")
            self.assertNotIn("due_at", row["fields"])

    def test_recurrence_timezone_and_private_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(tmp)
            data = ICS.replace(b"SUMMARY:Meet", b"RRULE:FREQ=DAILY;COUNT=3\r\nEXDATE;TZID=Asia/Seoul:20260907T130000\r\nSUMMARY:Meet")
            import_trip(ledger, "trip", data, guide="Door code: 9182736\nMap https://example.org/map\nInvite https://example.org/join?token=secret")
            out = export_trip(ledger, "trip", Path(tmp) / "export")
            event = Calendar.from_ical(Path(out["calendar"]).read_bytes()).walk("VEVENT")[0]
            self.assertEqual(event["EXDATE"].params["TZID"], "Asia/Seoul")
            text = Path(out["reference"]).read_text()
            self.assertNotIn("9182736", text)  # 7 digits: never inside a timestamp
            self.assertNotIn("token=secret", text)
            self.assertIn("https://example.org/map", text)


if __name__ == "__main__":
    unittest.main()
