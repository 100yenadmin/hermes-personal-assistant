"""Degraded native gateway behavior when PA durable state cannot initialize (#71)."""
import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FUTURE_TOOL = "mcp__evaos_pipedream_future__create_widget"
ARGS = {"widget": {"name": "fixture", "enabled": True}}
DIAGNOSTIC_CALLS = [
    ("read_file", {"path": "fixture"}),
    ("search_files", {"pattern": "fixture"}),
    ("session_search", {"query": "fixture"}),
    ("skill_view", {"name": "fixture"}),
    ("skills_list", {}),
]
BLOCKED_CALLS = [
    (FUTURE_TOOL, ARGS),
    ("terminal", {"command": "true"}),
    ("write_file", {"path": "fixture", "content": "x"}),
    ("pa", {"operation": "status"}),
]


def load_plugin_entrypoint():
    spec = importlib.util.spec_from_file_location(
        "personal_assistant_state_unavailable_test",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Context:
    def __init__(self):
        self.hooks = {}
        self.tools = {}

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs

    def register_skill(self, *args, **kwargs):
        return None

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_command(self, name, handler, **kwargs):
        self.commands = {name: handler}


def ledger_path(profile):
    return Path(profile) / "state" / "travel-ledger" / "travel.sqlite"


class GatewayStateUnavailableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.previous_home = os.environ.get("HERMES_HOME")
        self.addCleanup(self.restore_home)

    def restore_home(self):
        if self.previous_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self.previous_home

    def register(self, profile):
        os.environ["HERMES_HOME"] = str(profile)
        context = Context()
        load_plugin_entrypoint().register(context)
        self.assertIn("pre_llm_call", context.hooks)
        self.assertIn("pa", context.commands)
        return context, context.hooks["pre_tool_call"]

    def assert_degraded(self, callback, kind):
        for tool_name, args in DIAGNOSTIC_CALLS:
            with self.subTest(diagnostic=tool_name):
                self.assertIsNone(callback(tool_name=tool_name, args=args, session_id="s", task_id="t"))
        for tool_name, args in BLOCKED_CALLS:
            with self.subTest(blocked=tool_name):
                decision = callback(tool_name=tool_name, args=args, session_id="s", task_id="t")
                self.assertEqual(decision["action"], "block")
                self.assertEqual(decision["reason_code"], "DENY_STATE_UNAVAILABLE")
                self.assertEqual(decision["diagnostic_code"], f"STATE_UNAVAILABLE_{kind}")
                self.assertIn("Read-only diagnostic tools remain available", decision["recovery"])
                rendered = repr(decision)
                self.assertNotIn(str(self.tmp.name), rendered)
                self.assertNotIn("travel.sqlite", rendered)

    def test_malformed_ledger_on_first_hook_call(self):
        profile = Path(self.tmp.name) / "profile"
        ledger = ledger_path(profile)
        ledger.parent.mkdir(parents=True, mode=0o700)
        ledger.write_bytes(b"this is not a sqlite database" * 64)
        ledger.chmod(0o600)
        _, callback = self.register(profile)
        self.assert_degraded(callback, "MALFORMED")

    def test_missing_profile_root_on_first_hook_call(self):
        _, callback = self.register(Path(self.tmp.name) / "missing-profile")
        self.assert_degraded(callback, "MISSING")

    def skip_if_chmod_ineffective(self, path):
        if os.access(path, os.R_OK):
            self.skipTest("filesystem or user ignores chmod permission bits")

    def test_permission_denied_ledger_file_on_first_hook_call(self):
        profile = Path(self.tmp.name) / "profile"
        state = ledger_path(profile).parent
        state.mkdir(parents=True, mode=0o700)
        sqlite3.connect(ledger_path(profile)).close()
        ledger_path(profile).chmod(0o000)
        self.addCleanup(ledger_path(profile).chmod, 0o600)
        self.skip_if_chmod_ineffective(ledger_path(profile))
        _, callback = self.register(profile)
        self.assert_degraded(callback, "PERMISSION_DENIED")

    def test_permission_denied_ledger_directory_on_first_hook_call(self):
        profile = Path(self.tmp.name) / "profile"
        state = ledger_path(profile).parent
        state.mkdir(parents=True, mode=0o700)
        sqlite3.connect(ledger_path(profile)).close()
        ledger_path(profile).chmod(0o600)
        state.chmod(0o000)
        self.addCleanup(state.chmod, 0o700)
        self.skip_if_chmod_ineffective(state)
        _, callback = self.register(profile)
        self.assert_degraded(callback, "PERMISSION_DENIED")

    def test_locked_ledger_on_first_hook_call(self):
        profile = Path(self.tmp.name) / "profile"
        ledger = ledger_path(profile)
        ledger.parent.mkdir(parents=True, mode=0o700)
        sqlite3.connect(ledger).close()
        ledger.chmod(0o600)
        blocker = sqlite3.connect(ledger)
        blocker.execute("begin exclusive")
        self.addCleanup(blocker.close)
        self.addCleanup(blocker.rollback)
        _, callback = self.register(profile)
        for tool_name, args in DIAGNOSTIC_CALLS:
            self.assertIsNone(callback(tool_name=tool_name, args=args))
        decision = callback(tool_name=FUTURE_TOOL, args=ARGS, session_id="s", task_id="t")
        self.assertEqual(decision["reason_code"], "DENY_STATE_UNAVAILABLE")
        self.assertEqual(decision["diagnostic_code"], "STATE_UNAVAILABLE_LOCKED")

    def test_gateway_recovers_and_enforces_exact_action_after_state_returns(self):
        profile = Path(self.tmp.name) / "profile"
        context, callback = self.register(profile)
        missing = callback(tool_name=FUTURE_TOOL, args=ARGS, session_id="s", task_id="t")
        self.assertEqual(missing["diagnostic_code"], "STATE_UNAVAILABLE_MISSING")

        profile.mkdir(mode=0o700)
        handler = context.tools["pa"]["handler"]
        handler(
            {"operation": "authorization_prepare", "data": {
                "protocol": "pa.action-authorization/v1",
                "action_id": "fixture-recovery",
                "workflow_id": "fixture-workflow",
                "workflow_revision": "fixture-workflow-v1",
                "tool_name": FUTURE_TOOL,
                "tool_args": ARGS,
                "reliability_profile": "exact",
                "risk_class": "external_write",
                "authority": {"mode": "exact_confirmation", "subject": "fixture-owner", "scope_digest": "fixture-scope"},
                "source_revision": "fixture-source-v1",
                "fresh_until": "2030-01-01T00:00:00+00:00",
                "execution_budget": 1,
                "required_pre_action_projections": ["authority"],
                "preconditions": {"authority": "confirmed"},
                "expected_readback": "fixture-readback/v1",
            }},
            session_id="s",
            task_id="t",
        )
        handler({"operation": "authorization_confirm", "data": {
            "action_id": "fixture-recovery",
            "confirmation": "approved",
            "at": "2026-09-17T00:00:00+00:00",
        }})
        mutated = callback(tool_name=FUTURE_TOOL, args={"widget": {"name": "other"}}, session_id="s", task_id="t")
        self.assertEqual(mutated["action"], "block")
        self.assertIsNone(callback(tool_name=FUTURE_TOOL, args=ARGS, session_id="s", task_id="t"))
        replay = callback(tool_name=FUTURE_TOOL, args=ARGS, session_id="s", task_id="t")
        self.assertEqual(replay["reason_code"], "DENY_ALREADY_CLAIMED")

    def test_diagnostic_tools_cannot_carry_a_governed_scope(self):
        profile = Path(self.tmp.name) / "profile"
        profile.mkdir(mode=0o700)
        context, _ = self.register(profile)
        with self.assertRaisesRegex(ValueError, "cannot carry a governed scope"):
            context.tools["pa"]["handler"](
            {"operation": "authorization_prepare", "data": {
                "protocol": "pa.action-authorization/v1",
                "action_id": "fixture-diagnostic-scope",
                "workflow_id": "fixture-workflow",
                "workflow_revision": "fixture-workflow-v1",
                "tool_name": "read_file",
                "tool_args": {"path": "fixture"},
                "reliability_profile": "exact",
                "risk_class": "external_write",
                "authority": {"mode": "exact_confirmation", "subject": "fixture-owner", "scope_digest": "fixture-scope"},
                "source_revision": "fixture-source-v1",
                "fresh_until": "2030-01-01T00:00:00+00:00",
                "execution_budget": 1,
                "required_pre_action_projections": ["authority"],
                "preconditions": {"authority": "confirmed"},
                "expected_readback": "fixture-readback/v1",
            }},
            session_id="s",
            task_id="t",
            )

    def test_scope_without_trusted_runtime_identity_is_rejected(self):
        # Outside the native hook (CLI/__main__ dispatch) there is no trusted
        # session/task, so the base store cannot create any scope at all.
        from personal_assistant.entry import dispatch

        profile = Path(self.tmp.name) / "profile"
        profile.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, "trusted session_id and task_id are required"):
            dispatch(profile, {"operation": "authorization_prepare", "data": {
                "protocol": "pa.action-authorization/v1",
                "action_id": "fixture-cli-scope",
                "workflow_id": "fixture-workflow",
                "workflow_revision": "fixture-workflow-v1",
                "tool_name": "read_file",
                "tool_args": {"path": "fixture"},
                "reliability_profile": "exact",
                "risk_class": "external_write",
                "authority": {"mode": "exact_confirmation", "subject": "fixture-owner", "scope_digest": "fixture-scope"},
                "source_revision": "fixture-source-v1",
                "fresh_until": "2030-01-01T00:00:00+00:00",
                "execution_budget": 1,
                "required_pre_action_projections": ["authority"],
                "preconditions": {"authority": "confirmed"},
                "expected_readback": "fixture-readback/v1",
            }})

    def test_admin_denied_diagnostic_name_is_not_passed_through(self):
        from personal_assistant.action_gateway import GatewayPolicy
        from personal_assistant.native_gateway_runtime import NativeGateway

        denied = GatewayPolicy.from_dict({
            "protocol": "pa.gateway-policy/v1",
            "version": "fixture",
            "pass_through_tools": [],
            "denied_tools": ["read_file"],
        })
        self.assertFalse(NativeGateway.is_diagnostic_call(denied, "read_file", {"path": "fixture"}))
        self.assertFalse(NativeGateway.is_diagnostic_call(denied, "read_file", []))


if __name__ == "__main__":
    unittest.main()
