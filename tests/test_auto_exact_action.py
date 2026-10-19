import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from personal_assistant.action_gateway import ActionAuthorizationStore, Gateway, GatewayPolicy
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger


TOOL = "mcp__evaos_pipedream_google_calendar__google_calendar_create_event"
SESSION_ID = "fixture-session"
TASK_ID = "fixture-task"
NOW = "2027-01-01T00:00:00+00:00"
ARGS = {
    "calendarId": "calendar-a",
    "summary": "Focus time",
    "sendUpdates": "all",
}


def policy():
    return GatewayPolicy.from_dict({
        "protocol": "pa.gateway-policy/v1",
        "version": "auto-exact-action-v1",
        "pass_through_tools": [],
        "denied_tools": [],
    })


def governed_data(action_id="fixture-action", revision="r1", tool_args=None, target="calendar-a"):
    return {
        "action_id": action_id,
        "summary": {
            "provider": "google_calendar",
            "final_action": "create event",
            "calendar_id": target,
            "title": (tool_args or ARGS)["summary"],
            "send_updates": (tool_args or ARGS)["sendUpdates"],
        },
        "enforcement_profile": "exact_action",
        "action_revision": revision,
        "workflow_id": "calendar-create",
        "workflow_revision": "workflow-v1",
        "tool_name": TOOL,
        "tool_args": ARGS if tool_args is None else tool_args,
        "semantic_target": {
            "paths": [["calendarId"], ["summary"]],
            "value": [target, (tool_args or ARGS)["summary"]],
        },
        "fresh_until": "2030-01-01T00:00:00+00:00",
        "execution_budget": 1,
        "required_pre_action_projections": ["authority"],
        "preconditions": {"authority": "confirmed"},
        "expected_readback": "google-calendar-event/v1",
    }


def payload(tool_args=None):
    return {
        "tool_name": TOOL,
        "tool_input": ARGS if tool_args is None else tool_args,
        "session_id": SESSION_ID,
        "task_id": TASK_ID,
    }


class AutomaticExactActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.profile = Path(self.temp.name)
        os.chmod(self.profile, 0o700)
        self.scope = {"session_id": SESSION_ID, "task_id": TASK_ID}
        self.store = ActionAuthorizationStore(Ledger(self.profile), self.profile.name)
        self.gateway = Gateway(self.store, policy(), now=lambda: NOW)
        self.provider_calls = 0

    def tearDown(self):
        self.temp.cleanup()

    def provider_dispatch(self, tool_args=None):
        decision = self.gateway.evaluate(payload(tool_args))
        if decision is None:
            self.provider_calls += 1
        return decision

    def prepare(self, **changes):
        data = governed_data(**changes)
        return dispatch(
            self.profile,
            {"operation": "action_prepare", "data": data},
            runtime_scope=self.scope,
        )

    def confirm(self, data):
        return dispatch(
            self.profile,
            {"operation": "action_confirm", "data": {
                "action_id": data["action_id"],
                "summary": data["summary"],
                "confirmation": "Approve these exact details",
            }},
            runtime_scope=self.scope,
        )

    def test_action_prepare_automatically_registers_pending_scope(self):
        prepared = self.prepare()
        self.assertEqual(prepared["status"], "approval_required")
        self.assertEqual(prepared["fields"]["enforcement_profile"], "exact_action")
        self.assertEqual(prepared["fields"]["action_revision"], "r1")

        blocked = self.provider_dispatch()
        self.assertEqual(blocked["reason_code"], "DENY_APPROVAL_REQUIRED")
        self.assertEqual(self.provider_calls, 0)

    def test_unrelated_same_tool_target_is_not_captured(self):
        self.prepare()
        unrelated = dict(ARGS, summary="Unrelated event")
        self.assertIsNone(self.provider_dispatch(unrelated))
        self.assertEqual(self.provider_calls, 1)

    def test_changed_arguments_for_same_target_are_denied_before_provider(self):
        self.prepare()
        changed = dict(ARGS, sendUpdates="none")
        blocked = self.provider_dispatch(changed)
        self.assertEqual(blocked["reason_code"], "DENY_ACTION_CHANGED")
        self.assertEqual(self.provider_calls, 0)

    def test_exact_approval_allows_once_and_replay_is_denied(self):
        data = governed_data()
        self.prepare()
        confirmed = self.confirm(data)
        self.assertEqual(confirmed["status"], "approved_revision")

        self.assertIsNone(self.provider_dispatch())
        self.assertEqual(self.provider_calls, 1)
        replay = self.provider_dispatch()
        self.assertEqual(replay["reason_code"], "DENY_ALREADY_CLAIMED")
        self.assertEqual(self.provider_calls, 1)

        action = Ledger(self.profile).get("action", data["action_id"])
        self.assertEqual(action["status"], "claimed_once")
        self.assertEqual(action["fields"]["action_revision"], "r1")

    def test_delayed_approval_starts_a_fresh_execution_window(self):
        data = governed_data()
        self.prepare()
        prepared_action = Ledger(self.profile).get("action", data["action_id"])
        prepared_scope = self.store.get(prepared_action["fields"]["gateway_scope_ref"])
        prepared_at = datetime.fromisoformat(prepared_scope["created_at"])
        prepared_until = datetime.fromisoformat(prepared_scope["fresh_until"])
        original_window = prepared_until - prepared_at
        delayed_confirmation = "2031-01-01T00:00:00+00:00"

        confirmed_scope = self.store.confirm_governed(
            data["action_id"],
            Ledger(self.profile).get("action", data["action_id"])["fields"]["summary_digest"],
            "Approve these exact details",
            at=delayed_confirmation,
        )

        expected_until = datetime.fromisoformat(delayed_confirmation) + original_window
        self.assertEqual(datetime.fromisoformat(confirmed_scope["fresh_until"]), expected_until)
        self.assertEqual(
            confirmed_scope["envelope"]["fresh_until"],
            expected_until.isoformat(timespec="microseconds"),
        )
        action = Ledger(self.profile).get("action", data["action_id"])
        self.assertEqual(action["status"], "approved_revision")
        self.assertEqual(action["fields"]["fresh_until"], expected_until.isoformat(timespec="microseconds"))

        delayed_gateway = Gateway(self.store, policy(), now=lambda: delayed_confirmation)
        self.assertIsNone(delayed_gateway.evaluate(payload()))

    def test_new_revision_invalidates_old_approval(self):
        first = governed_data()
        self.prepare()
        self.confirm(first)

        changed_args = dict(ARGS, summary="Changed title")
        self.prepare(revision="r2", tool_args=changed_args)
        old = self.provider_dispatch()
        self.assertEqual(old["reason_code"], "DENY_ACTION_SUPERSEDED")
        current = self.provider_dispatch(changed_args)
        self.assertEqual(current["reason_code"], "DENY_APPROVAL_REQUIRED")
        self.assertEqual(self.provider_calls, 0)

    def test_ambiguous_matching_pending_actions_fail_closed(self):
        self.prepare(action_id="first")
        self.prepare(action_id="second")
        blocked = self.provider_dispatch()
        self.assertEqual(blocked["reason_code"], "DENY_ACTION_AMBIGUOUS")
        self.assertEqual(self.provider_calls, 0)

    def test_new_ambiguous_scope_between_check_and_claim_fails_closed(self):
        data = governed_data(action_id="first")
        self.prepare(action_id="first")
        self.confirm(data)
        original = self.store.requires_claim

        def inject_scope(*args, **kwargs):
            required = original(*args, **kwargs)
            self.prepare(action_id="second")
            return required

        self.store.requires_claim = inject_scope
        blocked = self.provider_dispatch()
        self.assertEqual(blocked["reason_code"], "DENY_ACTION_AMBIGUOUS")
        self.assertEqual(self.provider_calls, 0)

    def test_stale_and_cancelled_governed_actions_fail_closed(self):
        stale = governed_data(action_id="stale")
        stale["fresh_until"] = "2026-01-01T00:00:00+00:00"
        dispatch(
            self.profile,
            {"operation": "action_prepare", "data": stale},
            runtime_scope=self.scope,
        )
        self.assertEqual(self.provider_dispatch()["reason_code"], "DENY_STALE")

        cancelled_args = dict(ARGS, calendarId="calendar-c")
        self.prepare(action_id="cancelled", tool_args=cancelled_args, target="calendar-c")
        cancelled = dispatch(
            self.profile,
            {"operation": "action_cancel", "data": {"action_id": "cancelled"}},
            runtime_scope=self.scope,
        )
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.provider_dispatch(cancelled_args)["reason_code"], "DENY_ACTION_CANCELLED")
        self.assertEqual(self.provider_calls, 0)

    def test_verified_result_keeps_action_revision_and_readback_contract(self):
        data = governed_data()
        self.prepare()
        self.confirm(data)
        self.assertIsNone(self.provider_dispatch())

        result = dispatch(self.profile, {"operation": "action_result", "data": {
            "action_id": data["action_id"],
            "outcome": "confirmed",
            "proof": {"provider_object_id": "event-123", "readback": "matched"},
        }})
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["fields"]["action_revision"], "r1")
        self.assertEqual(result["fields"]["expected_readback"], "google-calendar-event/v1")
        self.assertEqual(result["fields"]["provider_proof"]["provider_object_id"], "event-123")

    def test_failed_confirmation_does_not_partially_approve_action(self):
        data = governed_data(action_id="open-precondition")
        data["preconditions"] = {"authority": "pending"}
        dispatch(
            self.profile,
            {"operation": "action_prepare", "data": data},
            runtime_scope=self.scope,
        )
        with self.assertRaisesRegex(ValueError, "precondition"):
            self.confirm(data)
        action = Ledger(self.profile).get("action", data["action_id"])
        self.assertEqual(action["status"], "approval_required")
        self.assertEqual(self.provider_dispatch()["reason_code"], "DENY_APPROVAL_REQUIRED")
        self.assertEqual(self.provider_calls, 0)

    def test_legacy_action_prepare_and_ordinary_calls_remain_unchanged(self):
        ordinary = dispatch(self.profile, {"operation": "action_prepare", "data": {
            "action_id": "legacy",
            "summary": {"provider": "fixture", "final_action": "fixture"},
        }})
        self.assertEqual(ordinary["status"], "prepared")
        self.assertIsNone(self.provider_dispatch())
        self.assertEqual(self.provider_calls, 1)


if __name__ == "__main__":
    unittest.main()
