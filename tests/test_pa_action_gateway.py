import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from personal_assistant.action_gateway import (
    ActionAuthorizationStore,
    Gateway,
    GatewayPolicy,
    args_digest,
)
from personal_assistant.entry import OPERATIONS, dispatch
from personal_assistant.state import Ledger


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pa_action_gateway.py"
PROFILE_ID = "fixture-profile"
FUTURE_TOOL = "mcp__evaos_pipedream_future__create_widget"
ARGS = {"widget": {"name": "fixture", "enabled": True}, "recipients": ["fixture@example.test"]}
SESSION_ID = "fixture-session"
TASK_ID = "fixture-task"


def policy():
    return GatewayPolicy.from_dict({
        "protocol": "pa.gateway-policy/v1",
        "version": "fixture-v1",
        "pass_through_tools": ["read_file", "pa"],
        "denied_tools": ["mcp__evaos_pipedream_admin__delete_tenant"],
    })


def envelope(action_id="fixture-action", tool_name=FUTURE_TOOL, tool_args=None):
    return {
        "protocol": "pa.action-authorization/v1",
        "action_id": action_id,
        "workflow_id": "fixture-workflow",
        "workflow_revision": "fixture-workflow-v1",
        "tool_name": tool_name,
        "tool_args": ARGS if tool_args is None else tool_args,
        "reliability_profile": "exact",
        "risk_class": "external_write",
        "authority": {
            "mode": "exact_confirmation",
            "subject": "fixture-owner",
            "scope_digest": "fixture-scope-digest",
        },
        "source_revision": "fixture-source-v1",
        "fresh_until": "2030-01-01T00:00:00+00:00",
        "execution_budget": 1,
        "required_pre_action_projections": ["identity", "intent", "authority"],
        "preconditions": {"identity": "confirmed", "intent": "confirmed", "authority": "confirmed"},
        "expected_readback": "fixture-readback/v1",
    }


def hook_payload(tool_name=FUTURE_TOOL, tool_args=None, session_id=SESSION_ID, task_id=TASK_ID):
    return {
        "tool_name": tool_name,
        "tool_input": ARGS if tool_args is None else tool_args,
        "session_id": session_id,
        "task_id": task_id,
    }


class ActionGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.profile = Path(self.temp.name)
        os.chmod(self.profile, 0o700)
        self.store = ActionAuthorizationStore(Ledger(self.profile), PROFILE_ID)
        self.gateway = Gateway(self.store, policy(), now=lambda: "2027-01-01T00:00:00+00:00")

    def tearDown(self):
        self.temp.cleanup()

    def authorize(self, **changes):
        item = envelope(**changes)
        prepared = self.store.prepare(item, session_id=SESSION_ID, task_id=TASK_ID)
        self.assertNotIn("tool_args", prepared)
        self.store.confirm(item["action_id"], "I approve these exact fixture details", at="2026-09-17T00:00:00+00:00")
        return item

    def test_future_tool_passes_without_scope_then_explicit_scope_allows_once(self):
        self.assertIsNone(self.gateway.evaluate(hook_payload()))

        self.authorize()
        self.assertIsNone(self.gateway.evaluate(hook_payload()))

        replay = self.gateway.evaluate(hook_payload())
        self.assertEqual(replay["reason_code"], "DENY_ALREADY_CLAIMED")

    def test_complete_arguments_are_bound_without_storing_raw_payload(self):
        self.authorize()
        changed = json.loads(json.dumps(ARGS))
        changed["widget"]["enabled"] = False
        decision = self.gateway.evaluate(hook_payload(tool_args=changed))
        self.assertEqual(decision["reason_code"], "DENY_ACTION_MISSING")
        with self.store.ledger.connect() as conn:
            raw = conn.execute("select envelope_json from pa_action_authorizations").fetchone()[0]
        self.assertNotIn("fixture@example.test", raw)
        self.assertIn(args_digest(ARGS), raw)

    def test_prepare_rejects_unrecognized_fields_instead_of_retaining_payloads(self):
        item = envelope(action_id="extra-field")
        item["raw_provider_payload"] = {"secret": "must-not-persist"}
        with self.assertRaisesRegex(ValueError, "unsupported authorization field"):
            self.store.prepare(item, session_id=SESSION_ID, task_id=TASK_ID)

    def test_three_workflow_shapes_use_the_same_generic_gateway(self):
        cases = [
            ("mcp__evaos_pipedream_gmail__gmail_send_email", {"to": ["fixture@example.test"], "body": "fixture"}),
            ("mcp__evaos_pipedream_google_calendar__google_calendar_create_event", {"calendarId": "fixture", "summary": "fixture"}),
            ("mcp__evaos_pipedream_inventory__create_item", {"sku": "fixture", "count": 1}),
        ]
        for index, (tool_name, tool_args) in enumerate(cases):
            self.authorize(action_id=f"action-{index}", tool_name=tool_name, tool_args=tool_args)
            self.assertIsNone(self.gateway.evaluate(hook_payload(tool_name, tool_args)))

    def test_protected_decisions_emit_redacted_receipts(self):
        self.gateway.evaluate(hook_payload())
        self.authorize()
        self.gateway.evaluate(hook_payload())
        with self.store.ledger.connect() as conn:
            receipts = conn.execute(
                "select reason_code,tool_name,args_digest,receipt_json from pa_action_gateway_receipts order by receipt_id"
            ).fetchall()
        self.assertEqual([row["reason_code"] for row in receipts], ["ALLOW_CLAIMED"])
        rendered = json.dumps([dict(row) for row in receipts])
        self.assertNotIn("fixture@example.test", rendered)
        self.assertNotIn('"enabled"', rendered)

    def test_shipped_policy_defaults_to_pass_through_and_is_loadable(self):
        shipped = GatewayPolicy.load(ROOT / "config" / "pa-action-gateway-policy.example.json")
        self.assertEqual(shipped.classify("pa"), "pass_through")
        self.assertEqual(shipped.classify("read_file"), "pass_through")
        for tool_name in ("terminal", "write_file", "browser_exec", "tool_call", FUTURE_TOOL):
            self.assertEqual(shipped.classify(tool_name), "pass_through")

    def test_policy_pass_through_and_admin_deny_do_not_consume_authorizations(self):
        self.assertIsNone(self.gateway.evaluate({"tool_name": "read_file", "tool_input": {"path": "fixture"}}))
        denied = self.gateway.evaluate({
            "tool_name": "mcp__evaos_pipedream_admin__delete_tenant",
            "tool_input": {"tenant": "fixture"},
        })
        self.assertEqual(denied["reason_code"], "DENY_ADMIN_POLICY")

    def test_malformed_identity_expired_scope_and_open_preconditions_are_safe(self):
        self.assertEqual(self.gateway.evaluate({"tool_name": FUTURE_TOOL, "tool_input": []})["reason_code"], "DENY_INVALID_PAYLOAD")

        bad_identity = envelope(action_id="identity-mismatch")
        bad_identity["profile_id"] = "other-profile"
        with self.assertRaisesRegex(ValueError, "unsupported authorization field"):
            self.store.prepare(bad_identity, session_id=SESSION_ID, task_id=TASK_ID)

        stale = envelope(action_id="stale")
        stale["fresh_until"] = "2026-01-01T00:00:00+00:00"
        self.store.prepare(stale, session_id=SESSION_ID, task_id=TASK_ID)
        self.store.confirm("stale", "approved", at="2025-01-01T00:00:00+00:00")
        self.assertIsNone(self.gateway.evaluate(hook_payload()))

        open_item = envelope(action_id="open", tool_args={"fixture": "open"})
        open_item["preconditions"]["authority"] = "pending"
        self.store.prepare(open_item, session_id=SESSION_ID, task_id=TASK_ID)
        with self.assertRaisesRegex(ValueError, "precondition"):
            self.store.confirm("open", "approved")

    def test_concurrent_identical_calls_allow_exactly_one(self):
        self.authorize()
        with ThreadPoolExecutor(max_workers=8) as pool:
            decisions = list(pool.map(
                lambda _: self.gateway.evaluate(hook_payload()),
                range(8),
            ))
        self.assertEqual(sum(decision is None for decision in decisions), 1)
        self.assertEqual(
            {decision["reason_code"] for decision in decisions if decision is not None},
            {"DENY_ALREADY_CLAIMED"},
        )

    def test_pa_tool_prepares_confirms_and_reads_gateway_authorization(self):
        expected = {"authorization_prepare", "authorization_confirm", "authorization_cancel", "authorization_status"}
        self.assertTrue(expected.issubset(set(OPERATIONS)))
        item = envelope()
        prepared = dispatch(
            self.profile,
            {"operation": "authorization_prepare", "data": item},
            runtime_scope={"session_id": SESSION_ID, "task_id": TASK_ID},
        )
        self.assertEqual(prepared["status"], "prepared")
        confirmed = dispatch(self.profile, {
            "operation": "authorization_confirm",
            "data": {
                "action_id": item["action_id"],
                "confirmation": "I approve these exact fixture details",
                "at": "2026-09-17T00:00:00+00:00",
            },
        })
        self.assertEqual(confirmed["status"], "authorized")
        status = dispatch(self.profile, {
            "operation": "authorization_status",
            "data": {"action_id": item["action_id"]},
        })
        self.assertEqual(status["envelope"]["args_digest"], args_digest(ARGS))
        self.assertNotIn("I approve these exact fixture details", json.dumps(status))

    def test_shell_pass_through_does_not_require_pa_state(self):
        policy_path = self.profile / "policy.json"
        policy_path.write_text(json.dumps(policy().to_dict()), encoding="utf-8")
        payload = json.dumps({
            "hook_event_name": "pre_tool_call",
            "tool_name": "read_file",
            "tool_input": {"path": "fixture"},
        })
        command = [
            sys.executable,
            str(SCRIPT),
            "--profile-root", str(self.profile / "missing-profile"),
            "--profile-id", PROFILE_ID,
            "--policy", str(policy_path),
        ]
        result = subprocess.run(command, input=payload, text=True, capture_output=True, check=False)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_shell_derives_profile_id_from_profile_directory(self):
        policy_path = self.profile / "policy.json"
        policy_path.write_text(json.dumps(policy().to_dict()), encoding="utf-8")
        derived_store = ActionAuthorizationStore(Ledger(self.profile), self.profile.resolve().name)
        item = envelope(action_id="derived-profile")
        derived_store.prepare(item, session_id=SESSION_ID, task_id=TASK_ID)
        derived_store.confirm(item["action_id"], "approved", at="2026-09-17T00:00:00+00:00")
        payload = json.dumps({
            "hook_event_name": "pre_tool_call",
            "tool_name": FUTURE_TOOL,
            "tool_input": ARGS,
            "session_id": SESSION_ID,
            "task_id": TASK_ID,
        })
        command = [
            sys.executable,
            str(SCRIPT),
            "--profile-root", str(self.profile),
            "--policy", str(policy_path),
            "--at", "2027-01-01T00:00:00+00:00",
        ]
        result = subprocess.run(command, input=payload, text=True, capture_output=True, check=False)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_shell_hook_wire_blocks_then_allows_then_blocks_replay(self):
        policy_path = self.profile / "policy.json"
        policy_path.write_text(json.dumps(policy().to_dict()), encoding="utf-8")
        payload = json.dumps({
            "hook_event_name": "pre_tool_call",
            "tool_name": FUTURE_TOOL,
            "tool_input": ARGS,
            "session_id": SESSION_ID,
            "task_id": TASK_ID,
            "cwd": str(ROOT),
            "extra": {},
        })
        command = [
            sys.executable,
            str(SCRIPT),
            "--profile-root", str(self.profile),
            "--profile-id", PROFILE_ID,
            "--policy", str(policy_path),
            "--at", "2027-01-01T00:00:00+00:00",
        ]

        first = subprocess.run(command, input=payload, text=True, capture_output=True, check=False)
        self.assertEqual((first.returncode, first.stdout), (0, ""))

        self.authorize()
        allowed = subprocess.run(command, input=payload, text=True, capture_output=True, check=False)
        self.assertEqual((allowed.returncode, allowed.stdout), (0, ""))

        replay = subprocess.run(command, input=payload, text=True, capture_output=True, check=False)
        self.assertEqual(replay.returncode, 2)
        self.assertEqual(json.loads(replay.stdout)["reason_code"], "DENY_ALREADY_CLAIMED")


if __name__ == "__main__":
    unittest.main()
