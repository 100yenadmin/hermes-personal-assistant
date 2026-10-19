import importlib.util
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FUTURE_TOOL = "mcp__evaos_pipedream_future__create_widget"
ARGS = {"widget": {"name": "fixture", "enabled": True}}


def load_plugin_entrypoint():
    spec = importlib.util.spec_from_file_location(
        "personal_assistant_native_hook_test",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class NativeHookRegistrationTests(unittest.TestCase):
    def test_plugin_registers_pre_tool_call_and_passes_unknown_unscoped_tool(self):
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

        with tempfile.TemporaryDirectory() as profile:
            previous_home = os.environ.get("HERMES_HOME")
            os.environ["HERMES_HOME"] = profile
            try:
                context = Context()
                load_plugin_entrypoint().register(context)
                self.assertIn("pre_tool_call", context.hooks)
                self.assertIn("pre_llm_call", context.hooks)
                self.assertIn("pa", context.commands)
                callback = context.hooks["pre_tool_call"]
                self.assertIsNone(callback(tool_name="pa", args={"operation": "setup"}))
                self.assertIsNone(callback(tool_name="read_file", args={"path": "fixture"}))
                # Read-only diagnostics bypass PA state entirely (#71), so an
                # unscoped non-diagnostic call initializes the lazy gateway.
                self.assertIsNone(callback(tool_name="web_search", args={"query": "fixture"}))
                ledger = Path(profile) / "state" / "travel-ledger" / "travel.sqlite"
                blocker = sqlite3.connect(ledger)
                blocker.execute("begin exclusive")
                started = time.monotonic()
                try:
                    locked_decisions = [
                        callback(
                            tool_name=tool_name,
                            args=args,
                            session_id="fixture-session",
                            task_id="fixture-task",
                        )
                        for tool_name, args in (
                            ("read_file", {"path": "fixture"}),
                            ("web_search", {"query": "fixture"}),
                        )
                    ]
                finally:
                    elapsed = time.monotonic() - started
                    blocker.rollback()
                    blocker.close()
                self.assertEqual(locked_decisions, [None, None])
                self.assertLess(elapsed, 1.0)
                envelope = {
                    "protocol": "pa.action-authorization/v1",
                    "action_id": "fixture-authorization",
                    "workflow_id": "fixture-workflow",
                    "workflow_revision": "fixture-workflow-v1",
                    "tool_name": FUTURE_TOOL,
                    "tool_args": ARGS,
                    "reliability_profile": "exact",
                    "risk_class": "external_write",
                    "authority": {
                        "mode": "exact_confirmation",
                        "subject": "fixture-owner",
                        "scope_digest": "fixture-scope",
                    },
                    "source_revision": "fixture-source-v1",
                    "fresh_until": "2030-01-01T00:00:00+00:00",
                    "execution_budget": 1,
                    "required_pre_action_projections": ["authority"],
                    "preconditions": {"authority": "confirmed"},
                    "expected_readback": "fixture-readback/v1",
                }
                self.assertIn("pa_call", context.tools)
                handler = context.tools["pa"]["handler"]
                if handler is None:
                    self.fail("PA tool handler was not registered")
                handler(
                    {"operation": "authorization_prepare", "data": envelope},
                    session_id="fixture-session",
                    task_id="fixture-task",
                )
                handler({
                    "operation": "authorization_confirm",
                    "data": {
                        "action_id": envelope["action_id"],
                        "confirmation": "approved",
                        "at": "2026-09-17T00:00:00+00:00",
                    },
                })
                decision = callback(
                    tool_name=FUTURE_TOOL,
                    args=ARGS,
                    session_id="fixture-session",
                    task_id="fixture-task",
                )
                replay = callback(
                    tool_name=FUTURE_TOOL,
                    args=ARGS,
                    session_id="fixture-session",
                    task_id="fixture-task",
                )
            finally:
                if previous_home is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = previous_home

        self.assertIsNone(decision)
        self.assertEqual(replay["reason_code"], "DENY_ALREADY_CLAIMED")


if __name__ == "__main__":
    unittest.main()
