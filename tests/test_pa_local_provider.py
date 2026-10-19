import json
from pathlib import Path
import tempfile
import unittest
from urllib.request import Request, urlopen

from evals.local_provider import LocalProvider, LostResponse, ProviderError, start_http_server


class LocalProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "provider.sqlite"
        self.provider = LocalProvider(self.db_path)

    def prepare(self, offer_id, correlation_id):
        return self.provider.operate({
            "operation": "prepare", "offer_id": offer_id, "correlation_id": correlation_id,
        })

    def submit(self, prepared):
        return self.provider.operate({
            "operation": "submit",
            "correlation_id": prepared["correlation_id"],
            "form_revision": prepared["form_revision"],
            "user_confirmed": True,
        })

    def test_seeded_forms_have_material_choices(self):
        result = self.provider.operate({"operation": "list"})
        by_recipe = {}
        for offer in result["offers"]:
            by_recipe.setdefault(offer["recipe"], []).append(offer)
        self.assertTrue({"booking", "check-in", "ride", "reservation", "purchase",
                         "refund", "message", "notification"} <= set(by_recipe))
        self.assertEqual(len(by_recipe["purchase"]), 3)
        purchases = {row["offer_id"]: row["material_details"] for row in by_recipe["purchase"]}
        self.assertEqual(purchases["headphones-purchase"]["color"], "black")
        self.assertEqual(purchases["premium-headphones-purchase"]["price"]["amount"], "299.00")
        for offer in result["offers"]:
            self.assertTrue(offer["material_details"])
            self.assertEqual(offer["form_revision"], 1)

    def test_submit_restart_and_blind_replay_are_visible(self):
        prepared = self.prepare("flight-booking", "corr-durable")
        self.assertEqual((prepared["status"], prepared["effect_count"]), ("prepared", 0))
        submitted = self.submit(prepared)
        self.assertEqual((submitted["status"], submitted["effect_count"]), ("accepted", 1))
        restarted = LocalProvider(self.db_path)
        lookup = restarted.operate({"operation": "lookup", "correlation_id": "corr-durable"})
        self.assertEqual((lookup["status"], lookup["submit_count"], lookup["effect_count"]),
                         ("accepted", 1, 1))
        duplicate = restarted.operate({
            "operation": "submit", "correlation_id": "corr-durable",
            "form_revision": prepared["form_revision"], "user_confirmed": True,
        })
        self.assertEqual((duplicate["status"], duplicate["original_status"]),
                         ("duplicate", "accepted"))
        self.assertEqual((duplicate["submit_count"], duplicate["duplicate_count"],
                          duplicate["effect_count"]), (2, 1, 1))
        self.assertEqual([row["outcome"] for row in duplicate["attempts"]],
                         ["accepted", "duplicate"])

    def test_change_expiry_and_confirmation_fail_closed(self):
        changed = self.prepare("airport-ride", "corr-change")
        self.provider.change_price("airport-ride", "27.50")
        stale = self.submit(changed)
        self.assertEqual(stale["status"], "changed")
        self.assertEqual(stale["material_details"]["price"]["amount"], "27.50")
        self.assertEqual(stale["form_revision"], 2)
        accepted = self.provider.operate({
            "operation": "submit", "correlation_id": "corr-change",
            "form_revision": 2, "user_confirmed": True,
        })
        self.assertEqual(accepted["status"], "accepted")

        expired = self.prepare("fixture-message", "corr-expired")
        self.provider.expire_session("corr-expired")
        self.assertEqual(self.submit(expired)["status"], "expired")
        unconfirmed = self.prepare("dinner-reservation", "corr-unconfirmed")
        result = self.provider.operate({
            "operation": "submit", "correlation_id": "corr-unconfirmed",
            "form_revision": 1, "user_confirmed": False,
        })
        self.assertEqual((result["status"], result["effect_count"]), ("confirmation_required", 0))

    def test_decline_and_lost_response_after_commit(self):
        declined = self.prepare("headphones-purchase", "corr-decline")
        self.provider.decline_next("corr-decline")
        result = self.submit(declined)
        self.assertEqual((result["status"], result["effect_count"]), ("declined", 0))

        lost = self.prepare("flight-checkin", "corr-lost")
        self.provider.lose_response_next("corr-lost")
        with self.assertRaises(LostResponse) as raised:
            self.submit(lost)
        self.assertEqual(raised.exception.correlation_id, "corr-lost")
        recovered = LocalProvider(self.db_path).operate({
            "operation": "lookup", "correlation_id": "corr-lost",
        })
        self.assertEqual((recovered["status"], recovered["submit_count"],
                          recovered["effect_count"]), ("accepted", 1, 1))
        duplicate = self.submit(lost)
        self.assertEqual((duplicate["status"], duplicate["submit_count"],
                          duplicate["duplicate_count"], duplicate["effect_count"]),
                         ("duplicate", 2, 1, 1))

    def test_refund_settlement_and_draft_revision_stay_distinct(self):
        refund = self.prepare("order-refund", "corr-refund")
        requested = self.submit(refund)
        self.assertEqual((requested["status"], requested["provider_state"]),
                         ("accepted", "refund_requested"))
        settled = self.provider.settle_refund("corr-refund")
        self.assertEqual((settled["status"], settled["provider_state"], settled["effect_count"]),
                         ("refunded", "refunded", 2))

        draft = self.provider.operate({
            "operation": "draft", "offer_id": "fixture-message", "draft_id": "draft-fixed",
            "subject": "First fixture subject",
        })
        revised = self.provider.operate({
            "operation": "draft", "offer_id": "fixture-message", "draft_id": "draft-fixed",
            "subject": "Revised fixture subject",
        })
        self.assertEqual((draft["revision"], revised["revision"], revised["mailbox_state"]),
                         (1, 2, "draft"))
        message = self.prepare("fixture-message", "corr-message")
        self.assertEqual(self.submit(message)["status"], "sent")
        snapshot = LocalProvider(self.db_path).snapshot()
        self.assertEqual(len(snapshot["drafts"]), 1)
        self.assertEqual(snapshot["drafts"][0]["state"], "draft")
        self.assertEqual(snapshot["drafts"][0]["material_details"]["subject"],
                         "Revised fixture subject")
        states = {row["provider_state"] for row in snapshot["transactions"]}
        self.assertEqual(states, {"refunded", "sent"})

    def test_loopback_review_and_json_use_same_state(self):
        prepared = self.prepare("dinner-reservation", "corr-http")
        server = start_http_server(self.provider)
        self.addCleanup(server.close)
        with urlopen(f"{server.base_url}{prepared['review_path']}", timeout=2) as response:
            html = response.read().decode()
        self.assertIn("Review transaction", html)
        self.assertIn("Fixture Table", html)
        request = Request(
            f"{server.base_url}/api/operate",
            data=json.dumps({"operation": "lookup", "correlation_id": "corr-http"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(request, timeout=2) as response:
            result = json.load(response)
        self.assertEqual((result["status"], result["effect_count"]), ("prepared", 0))
        with self.assertRaises(ProviderError):
            start_http_server(self.provider, host="0.0.0.0")


if __name__ == "__main__":
    unittest.main()
