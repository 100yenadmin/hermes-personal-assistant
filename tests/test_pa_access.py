import importlib.util
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_access():
    sys.path.insert(0, str(ROOT))
    return importlib.import_module("personal_assistant.access")


access = load_access()


class PersonalAssistantAccessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)

    def manager(self, **callbacks):
        callbacks["clock"] = lambda: self.now
        return access.AccessManager(**callbacks)

    def test_secure_access_metadata_drops_secret_fields_and_values(self):
        materialize_calls = []

        def listed(**_kwargs):
            return [{
                "source_ref": "provider://fixture",
                "status": "approved",
                "label": "fixture provider",
                "password": "fixture-password",
                "nested": {"api_key": "fixture-api-key", "safe": "kept"},
            }]

        def checked(**_kwargs):
            return {
                "status": "approved",
                "expires_at": self.now + timedelta(minutes=20),
                "password": "fixture-password",
                "live_view_url": "https://fixture.invalid/?token=fixture-token",
            }

        def materialized(**kwargs):
            materialize_calls.append(kwargs)
            return {
                "path": "/private/fixture-materialized",
                "variable_names": ["FIXTURE_USER", "FIXTURE_PASSWORD"],
                "expires_at": self.now + timedelta(minutes=20),
                "values": {
                    "FIXTURE_USER": "fixture-user",
                    "FIXTURE_PASSWORD": "fixture-password",
                },
                "authorization": "Bearer fixture-token",
            }

        manager = self.manager(
            secure_access_list=listed,
            secure_access_check=checked,
            secure_access_materialize=materialized,
        )
        listed_result = manager.list_secure_access(owner_id="owner-fixture")
        result = manager.materialize_secure_access(
            source_ref="provider://fixture", owner_id="owner-fixture"
        )
        encoded = json.dumps({"listed": listed_result, "result": result})
        self.assertNotIn("fixture-password", encoded)
        self.assertNotIn("fixture-api-key", encoded)
        self.assertNotIn("fixture-token", encoded)
        self.assertEqual(result["metadata"]["path"], "/private/fixture-materialized")
        self.assertEqual(result["metadata"]["variable_names"], ["FIXTURE_USER", "FIXTURE_PASSWORD"])
        self.assertEqual(materialize_calls[0]["source_ref"], "provider://fixture")

    def test_denied_or_revoked_source_never_uses_cached_session(self):
        materialize_calls = []

        def checked(**_kwargs):
            return {"status": "revoked"}

        def materialized(**_kwargs):
            materialize_calls.append(True)
            return {"path": "/private/should-not-be-used"}

        manager = self.manager(
            secure_access_check=checked,
            secure_access_materialize=materialized,
        )
        with self.assertRaises(access.AccessDeniedError):
            manager.acquire(
                source_ref="provider://fixture",
                owner_id="owner-fixture",
                cached_session={
                    "status": "ready",
                    "session_id": "cached-fixture-session",
                    "expires_at": self.now + timedelta(minutes=10),
                },
            )
        self.assertEqual(materialize_calls, [])

    def test_unavailable_source_fallback_is_explicit(self):
        manager = self.manager(secure_access_check=lambda **_kwargs: {"status": "pending"})
        result = manager.acquire(
            source_ref="provider://fixture",
            owner_id="owner-fixture",
            cached_session={
                "status": "ready",
                "owner_id": "owner-fixture",
                "session_id": "cached-fixture-session",
                "expires_at": self.now + timedelta(minutes=10),
            },
        )
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["fallback_reason"], "secure_access_unavailable")

    def test_handoff_rejects_expired_grant(self):
        def handoff(**_kwargs):
            return {
                "owner_id": "owner-fixture",
                "context_id": "context-fixture",
                "status": "ready",
                "attended": True,
                "ready": True,
                "expires_at": self.now - timedelta(seconds=1),
            }

        manager = self.manager(browserbase_handoff=handoff)
        with self.assertRaises(access.AccessExpiredError):
            manager.attended_browserbase_handoff(
                owner_id="owner-fixture", context_id="context-fixture"
            )

    def test_handoff_requires_exact_owner_and_context(self):
        def wrong_owner(**_kwargs):
            return {
                "owner_id": "other-owner-fixture",
                "context_id": "context-fixture",
                "status": "ready",
                "attended": True,
                "ready": True,
                "expires_at": self.now + timedelta(minutes=10),
            }

        manager = self.manager(browserbase_handoff=wrong_owner)
        with self.assertRaises(access.IdentityMismatchError):
            manager.attended_browserbase_handoff(
                owner_id="owner-fixture", context_id="context-fixture"
            )

        def wrong_context(**_kwargs):
            return {
                "owner_id": "owner-fixture",
                "context_id": "other-context-fixture",
                "status": "ready",
                "attended": True,
                "ready": True,
                "expires_at": self.now + timedelta(minutes=10),
            }

        manager = self.manager(browserbase_handoff=wrong_context)
        with self.assertRaises(access.IdentityMismatchError):
            manager.attended_browserbase_handoff(
                owner_id="owner-fixture", context_id="context-fixture"
            )

    def test_ready_handoff_has_safe_resumable_checkpoint(self):
        def handoff(**_kwargs):
            return {
                "owner_id": "owner-fixture",
                "context_id": "context-fixture",
                "session_id": "session-fixture",
                "status": "ready",
                "attended": True,
                "ready": True,
                "expires_at": self.now + timedelta(minutes=10),
                "live_view_url": "https://fixture.invalid/live?token=fixture-token",
                "debug_url": "https://fixture.invalid/debug?token=fixture-token",
                "metadata": {"label": "fixture", "token": "fixture-token"},
            }

        manager = self.manager(browserbase_handoff=handoff)
        result = manager.attended_browserbase_handoff(
            owner_id="owner-fixture", context_id="context-fixture"
        )
        checkpoint = result["checkpoint"]
        encoded = json.dumps(checkpoint)
        self.assertNotIn("live_view_url", checkpoint)
        self.assertNotIn("debug_url", checkpoint)
        self.assertNotIn("fixture-token", encoded)
        self.assertTrue(checkpoint["owner_match"])
        self.assertTrue(checkpoint["context_match"])
        self.assertTrue(checkpoint["ready_verified"])
        self.assertTrue(checkpoint["live_view_transient"])
        resumed = manager.verify_checkpoint(
            checkpoint, owner_id="owner-fixture", context_id="context-fixture"
        )
        self.assertTrue(resumed["owner_match"])
        with self.assertRaises(access.IdentityMismatchError):
            manager.verify_checkpoint(
                checkpoint, owner_id="other-owner-fixture", context_id="context-fixture"
            )

    def test_managed_route_reports_no_context_live_view_or_debug(self):
        capabilities = self.manager().route_capabilities("managed_browserbase")
        self.assertFalse(capabilities["context"])
        self.assertFalse(capabilities["durable_context"])
        self.assertFalse(capabilities["live_view"])
        self.assertFalse(capabilities["debug"])
        self.assertFalse(capabilities["attended_handoff"])

    def test_unsupported_routes_and_optional_1password_are_clear(self):
        manager = self.manager()
        with self.assertRaises(access.RouteUnavailableError):
            manager.attended_browserbase_handoff(owner_id="owner-fixture")
        with self.assertRaises(access.OptionalResolverUnavailableError):
            manager.resolve_onepassword(item_ref="op://fixture/item")
        with self.assertRaises(access.UnsupportedRouteError):
            manager.route_capabilities("unknown-fixture-route")

    def test_configured_1password_is_metadata_only(self):
        def resolve(**_kwargs):
            return {
                "status": "approved",
                "title": "fixture item",
                "username": "fixture-user",
                "password": "fixture-password",
                "fields": {"safe": "kept", "secret": "fixture-secret"},
            }

        manager = self.manager(onepassword_resolver=resolve)
        result = manager.resolve_onepassword(item_ref="op://fixture/item")
        encoded = json.dumps(result)
        self.assertNotIn("fixture-user", encoded)
        self.assertNotIn("fixture-password", encoded)
        self.assertNotIn("fixture-secret", encoded)
        self.assertEqual(result["metadata"]["title"], "fixture item")


if __name__ == "__main__":
    unittest.main()
