"""Counterexamples from the bounded credential/transaction review."""
import json
from pathlib import Path
import tempfile
import unittest

from personal_assistant.access import sanitize_metadata
from personal_assistant.entry import dispatch
from personal_assistant.privacy import safe_url
from personal_assistant.state import Ledger
from personal_assistant.trips import export_trip, import_trip


class ReviewRegressions(unittest.TestCase):
    def test_source_refresh_cannot_reopen_attempted_submission(self):
        for status in ("submitting", "unknown", "confirmed"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as root:
                ledger = Ledger(root)
                ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:fixture\r\n"
                       "DTSTART;VALUE=DATE:20260906\r\nSUMMARY:Trip\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").encode()
                import_trip(ledger, "trip", ics)
                source = ledger.get("trip", "trip")["fields"]["events"][0]["source_record_id"]
                ledger.put("action", "booking", {"source_record_id": source, "source_fields": ["start"]})
                summary = {"provider": "fixture", "final_action": "book", "total": "10 KRW"}
                ledger.prepare("booking", summary)
                ledger.confirm("booking", summary, "Confirm fixture")
                ledger.claim_submission("booking", summary)
                if status != "submitting":
                    ledger.result("booking", status, None if status == "unknown" else "fixture-proof")
                import_trip(ledger, "trip", ics.replace(b"20260906", b"20260907"))
                self.assertEqual(ledger.get("action", "booking")["status"], status)
                with self.assertRaises(ValueError):
                    Ledger(root).prepare("booking", summary)

    def test_copied_authorization_cannot_create_or_retype_transaction(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            summary = {"provider": "fixture", "final_action": "book", "total": "10 KRW"}
            ledger.prepare("a", summary)
            authorized = ledger.confirm("a", summary, "Confirm this fixture booking")
            for data in (
                {"action_id": "b", "action_type": "transaction", "status": "authorized", "fields": authorized["fields"]},
                {"action_id": "b", "status": "authorized", "fields": authorized["fields"]},
                {"action_id": "a", "action_type": "commitment", "fields": {}},
                {"action_id": "a", "remove": ["confirmation_text"], "fields": {}},
            ):
                with self.assertRaises(ValueError):
                    dispatch(root, {"operation": "action_upsert", "data": data})
            ledger.put("action", "b", {}, status="authorized")
            with self.assertRaises(ValueError):
                ledger.claim_submission("b", summary)
            self.assertEqual(ledger.claim_submission("a", summary)["status"], "submitting")

    def test_changed_material_needs_fresh_same_action_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            summary = {"provider": "fixture", "final_action": "book", "total": "10 KRW"}
            ledger.prepare("a", summary)
            ledger.confirm("a", summary, "Confirm")
            changed = dict(summary, total="20 KRW")
            with self.assertRaises(ValueError):
                ledger.claim_submission("a", changed)
            ledger.prepare("a", changed)
            with self.assertRaises(ValueError):
                ledger.claim_submission("a", changed)
            ledger.confirm("a", changed, "Confirm 20 KRW")
            self.assertEqual(ledger.claim_submission("a", changed)["status"], "submitting")

    def test_metadata_string_leaves_and_shared_auth_urls_are_filtered(self):
        secret = "synthetic-bearer-value"
        auth = "https://example.invalid/login#access_token=synthetic-fragment"
        result = sanitize_metadata({"label": f"Bearer {secret}", "title": auth,
                                    "nested": [auth], "variable_names": ["FIXTURE_PASSWORD"]})
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn("synthetic-fragment", json.dumps(result))
        self.assertEqual(result["variable_names"], ["FIXTURE_PASSWORD"])
        for url in (auth, "https://example.invalid/page#access_token=synthetic-fragment",
                    "https://example.invalid/oauth/authorize", "https://example.invalid/sso"):
            self.assertEqual(safe_url(url), "")
        self.assertEqual(safe_url("https://example.invalid/guide#packing"), "https://example.invalid/guide#packing")
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:fixture\r\n"
                   "DTSTART;VALUE=DATE:20260906\r\nSUMMARY:Trip\r\nURL:" + auth +
                   "\r\nDESCRIPTION:" + auth + "\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").encode()
            import_trip(ledger, "trip", ics, guide=auth)
            exports = export_trip(ledger, "trip", Path(root) / "exports")
            for key in ("calendar", "reference"):
                self.assertNotIn("synthetic-fragment", Path(exports[key]).read_text())


if __name__ == "__main__":
    unittest.main()
