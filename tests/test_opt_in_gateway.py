import os
import tempfile
import unittest
from pathlib import Path

from personal_assistant.action_gateway import ActionAuthorizationStore, Gateway, GatewayPolicy
from personal_assistant.state import Ledger


PROFILE_ID = "fixture-profile"
TOOL = "mcp__evaos_pipedream_google_calendar__google_calendar_create_event"
ARGS = {"calendarId": "fixture", "summary": "Focus time"}
NOW = "2027-01-01T00:00:00+00:00"
SESSION_ID = "fixture-session"
TASK_ID = "fixture-task"


def policy():
    return GatewayPolicy.from_dict({
        "protocol": "pa.gateway-policy/v1",
        "version": "opt-in-fixture-v1",
        "pass_through_tools": [],
        "denied_tools": ["mcp__evaos_pipedream_admin__delete_tenant"],
    })


def envelope(action_id="fixture-action", tool_args=None, fresh_until="2030-01-01T00:00:00+00:00"):
    return {
        "protocol": "pa.action-authorization/v1",
        "action_id": action_id,
        "workflow_id": "fixture-workflow",
        "workflow_revision": "fixture-v1",
        "tool_name": TOOL,
        "tool_args": ARGS if tool_args is None else tool_args,
        "reliability_profile": "exact",
        "risk_class": "external_write",
        "authority": {"mode": "exact_confirmation", "subject": "fixture-owner", "scope_digest": "fixture-scope"},
        "source_revision": "fixture-source-v1",
        "fresh_until": fresh_until,
        "execution_budget": 1,
        "required_pre_action_projections": ["authority"],
        "preconditions": {"authority": "confirmed"},
        "expected_readback": "fixture-readback/v1",
    }


def payload(tool_args=None, session_id=SESSION_ID, task_id=TASK_ID):
    return {
        "tool_name": TOOL,
        "tool_input": ARGS if tool_args is None else tool_args,
        "session_id": session_id,
        "task_id": task_id,
    }


class OptInGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.profile = Path(self.temp.name)
        os.chmod(self.profile, 0o700)
        self.store = ActionAuthorizationStore(Ledger(self.profile), PROFILE_ID)
        self.gateway = Gateway(self.store, policy(), now=lambda: NOW)

    def tearDown(self):
        self.temp.cleanup()

    def authorize(self, **changes):
        item = envelope(**changes)
        self.store.prepare(
            item,
            session_id=SESSION_ID,
            task_id=TASK_ID,
            at="2026-12-31T00:00:00+00:00",
        )
        self.store.confirm(item["action_id"], "approved", at="2026-12-31T00:00:01+00:00")

    def test_ordinary_unscoped_tool_passes_by_default(self):
        self.assertEqual(policy().classify(TOOL), "pass_through")
        self.assertIsNone(self.gateway.evaluate(payload()))

    def test_reviewed_always_denied_tool_stays_blocked(self):
        blocked = self.gateway.evaluate({
            "tool_name": "mcp__evaos_pipedream_admin__delete_tenant",
            "tool_input": {"tenant": "fixture"},
            "session_id": SESSION_ID,
            "task_id": TASK_ID,
        })
        self.assertEqual(blocked["reason_code"], "DENY_ADMIN_POLICY")

    def test_active_scope_binds_arguments_and_allows_once(self):
        self.authorize()
        changed = dict(ARGS, summary="Changed")
        blocked = self.gateway.evaluate(payload(changed))
        self.assertEqual(blocked["reason_code"], "DENY_ACTION_MISSING")
        self.assertIsNone(self.gateway.evaluate(payload()))
        replay = self.gateway.evaluate(payload())
        self.assertEqual(replay["reason_code"], "DENY_ALREADY_CLAIMED")

    def test_expired_scope_no_longer_governs_ordinary_call(self):
        self.authorize(action_id="stale", fresh_until="2026-01-01T00:00:00+00:00")
        self.assertIsNone(self.gateway.evaluate(payload()))

    def test_scope_is_isolated_to_server_bound_session_and_task(self):
        self.authorize()
        self.assertIsNone(self.gateway.evaluate(payload(session_id="other-session")))
        self.assertIsNone(self.gateway.evaluate(payload(task_id="other-task")))
        changed = dict(ARGS, summary="Changed")
        self.assertEqual(self.gateway.evaluate(payload(changed))["reason_code"], "DENY_ACTION_MISSING")

    def test_two_active_exact_scopes_fail_closed_as_ambiguous(self):
        self.authorize(action_id="first")
        self.authorize(action_id="second")
        blocked = self.gateway.evaluate(payload())
        self.assertEqual(blocked["reason_code"], "DENY_ACTION_AMBIGUOUS")

    def test_cancelled_scope_no_longer_governs_ordinary_call(self):
        self.authorize()
        self.store.cancel("fixture-action", at="2026-12-31T00:00:02+00:00")
        self.assertIsNone(self.gateway.evaluate(payload()))

    def test_prepare_injects_scope_and_rejects_caller_identity(self):
        prepared = self.store.prepare(
            envelope(action_id="server-bound"),
            session_id=SESSION_ID,
            task_id=TASK_ID,
            at="2026-12-31T00:00:00+00:00",
        )
        self.assertEqual(prepared["envelope"]["profile_id"], PROFILE_ID)
        self.assertEqual(prepared["envelope"]["scope"], {
            "mode": "opt_in",
            "session_id": SESSION_ID,
            "task_id": TASK_ID,
            "reliability_profile": "exact",
        })

        caller_bound = envelope(action_id="caller-bound")
        caller_bound["session_id"] = "caller-controlled"
        with self.assertRaisesRegex(ValueError, "unsupported authorization field"):
            self.store.prepare(caller_bound, session_id=SESSION_ID, task_id=TASK_ID)


if __name__ == "__main__":
    unittest.main()
