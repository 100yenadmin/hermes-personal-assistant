import datetime as dt, tempfile, unittest

from personal_assistant.automation import (claim_notification, notification_occurrence_id,
    notification_receipt, record_notification, script_precheck, source_rule_fields,
    suggest_automation_jobs)
from personal_assistant.state import Ledger

class AutomationTests(unittest.TestCase):
    def test_suggestions_are_bounded_and_inert(self):
        result = suggest_automation_jobs([{"kind": "daily_brief", "accepted": True}, {"kind": "due_source_check", "accepted": True, "source_ref": "official-feed"}], destination="local-eva", destination_verified=True, timezone="Asia/Seoul")
        self.assertEqual((result["status"], len(result["jobs"]), result["install"]), ("suggested", 2, False))
        self.assertTrue(all(j["destination_verified"] and all(s.startswith("personal-assistant:") for s in j["skills"]) for j in result["jobs"]))
        due = next(j for j in result["jobs"] if j["kind"] == "due_source_check"); self.assertEqual((due["settings"]["accepted_sources"], due["settings"]["source_refresh_minutes"]), (["official-feed"], 360))
        self.assertEqual(source_rule_fields({"kind": "daily_brief", "accepted": True})["automation_kind"], "daily_brief")

    def test_precheck_handles_all_gates(self):
        at = dt.datetime(2026, 9, 6, 23, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(script_precheck({"timezone": "UTC", "actions": [{"due_at": "2026-09-06T22:00:00+00:00"}]}, now=at)["reason"], "quiet_hours")
        self.assertEqual(script_precheck(timezone="UTC", now=at, snooze_until="2026-09-07T01:00:00+00:00")["reason"], "snoozed")
        self.assertEqual(script_precheck(timezone="UTC", now=at, trip_end="2026-09-06T20:00:00+00:00")["reason"], "trip_ended"); self.assertTrue(script_precheck(timezone="UTC", now=at, trip_end="2026-09-06T20:00:00+00:00", unresolved_refunds=True, urgent=True)["run"])
        self.assertEqual(script_precheck(timezone="bad/zone")["reason"], "invalid_timezone")

    def test_notification_claim_is_replay_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, occ = Ledger(tmp), notification_occurrence_id("brief", "2026-09-06")
            self.assertTrue(claim_notification(ledger, occ, rule_id="brief", payload={"text": "hello"})["claimed"]); self.assertFalse(claim_notification(Ledger(tmp), occ)["claimed"])
            self.assertEqual(record_notification(ledger, occ, "unknown")["state"], "unknown"); self.assertEqual(claim_notification(Ledger(tmp), occ)["state"], "unknown")
            self.assertEqual(notification_receipt(ledger, occ)["receipt"], "unknown")
            with self.assertRaises(ValueError): record_notification(ledger, occ, "delivered")
            self.assertTrue(record_notification(ledger, occ, "delivered", proof={"provider": "fixture", "receipt_reference": "r1"})["resolved_from_unknown"])
            self.assertEqual(notification_receipt(ledger, occ)["provider_proof"]["receipt_reference"], "r1")

if __name__ == "__main__":
    unittest.main()
