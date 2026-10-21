import importlib.util
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from personal_assistant.capabilities import discover
from personal_assistant.recipes import catalog


ROOT = Path(__file__).resolve().parents[1]


class _Entry:
    def __init__(self, name, check_fn=None):
        self.name = name
        self.check_fn = check_fn


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch("shutil.which", return_value=None).start()
        patch.dict("os.environ", {"GOG_PATH": ""}).start()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.gog = Path(tmp.name) / "gog"
        self.gog.write_text("#!/bin/sh\nexit 9\n")
        self.gog.chmod(0o755)

    def test_gog_path_is_presence_only_and_preserves_registration_states(self):
        with patch.dict("os.environ", {"GOG_PATH": str(self.gog)}), patch("subprocess.run") as run:
            for verdict in (False, None, True):
                with self.subTest(verdict=verdict):
                    rows = {r["id"]: r for r in discover([
                        _Entry("mcp__notion__notion_calendar_list", lambda: None),
                        _Entry("gmail_search", lambda: None)], lambda fn: verdict)["capabilities"]}
                    for capability, tool in (("calendar", "mcp__notion__notion_calendar_list"), ("email", "gmail_search")):
                        row = rows[capability]
                        self.assertEqual(row["tools"], ["gog", tool])
                        self.assertEqual(row["status"], "available" if verdict is True else "unverified")
                        self.assertIn("gog CLI", row["evidence"])
                        self.assertIn("account authorisation is unverified", row["evidence"])
                        self.assertIn("gog CLI", row["reuse"])
                        self.assertEqual(row["authentication"], "unverified")
            run.assert_not_called()

    def test_gog_lookup_and_unregistered_calendar_email(self):
        from unittest.mock import Mock
        lookup = Mock(side_effect=lambda name: "/fixture/gog" if name == "gog" else None)
        rows = {r["id"]: r for r in discover([], which=lookup)["capabilities"]}
        for capability in ("calendar", "email"):
            self.assertEqual(rows[capability]["tools"], ["gog"])
            self.assertEqual(rows[capability]["status"], "unverified")
        lookup.assert_called_once_with("gog")
        with patch("shutil.which", side_effect=lookup):
            self.assertEqual(discover([])["capabilities"], list(rows.values()))
        with patch.dict("os.environ", {"GOG_PATH": str(self.gog)}):
            lookup.reset_mock()
            discover([], which=lookup)
            lookup.assert_not_called()
        missing = Mock(return_value=None)
        for stale in (str(self.gog.parent / "missing-gog"), str(self.gog.parent)):
            with self.subTest(stale=stale), patch.dict("os.environ", {"GOG_PATH": stale}):
                stale_rows = {r["id"]: r for r in discover([], which=missing)["capabilities"]}
                for capability in ("calendar", "email"):
                    self.assertNotIn("gog", stale_rows[capability]["tools"])
                missing.assert_called_with("gog")

    def test_remote_browser_requires_cli_on_this_host(self):
        from unittest.mock import Mock
        lookup = Mock(return_value=None)
        rows = {r["id"]: r for r in discover([], secret_present=lambda name: True, which=lookup)["capabilities"]}
        row = rows["remote_browser"]
        self.assertEqual(row["status"], "needs-setup")
        self.assertEqual(row["evidence"], "Browserbase key and project present; agent-browser CLI not found on PATH")
        self.assertEqual(row["recovery_action"], "Install agent-browser on this host, then rerun capability discovery.")
        self.assertEqual([c.args[0] for c in lookup.call_args_list], ["gog", "agent-browser"])
        present = lambda name: "/fixture/agent-browser" if name == "agent-browser" else None
        row = next(r for r in discover([], secret_present=lambda name: True, which=present)["capabilities"]
                   if r["id"] == "remote_browser")
        self.assertEqual(row["status"], "available")
        self.assertEqual(row["evidence"], "browser_session operation; credentials present")

    def test_profile_native_route_does_not_override_failed_or_uncached_tools(self):
        with tempfile.TemporaryDirectory() as root:
            check = lambda: False
            for cached, expected in ((False, "needs-setup"), (None, "unverified")):
                result = discover([_Entry("calendar_list", check)], lambda fn: cached, profile_root=root)
                row = next(r for r in result["capabilities"] if r["id"] == "calendar")
                self.assertEqual(row["status"], expected)
            (Path(root) / "google_token.json").write_text("not valid credentials")
            row = next(r for r in discover([_Entry("calendar_list", check)], lambda fn: False, profile_root=root)["capabilities"] if r["id"] == "calendar")
            self.assertEqual(row["status"], "needs-setup")

    def test_native_google_route_is_discovered_without_reading_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "google_token.json").write_text("not valid credentials")
            rows = {r["id"]: r for r in discover([], profile_root=root)["capabilities"]}
            self.assertEqual(rows["calendar"]["status"], "unverified")
            self.assertEqual(rows["calendar"]["authentication"], "unverified")
            self.assertIn("pa", rows["calendar"]["tools"])

    def test_capabilities_distinguish_runtime_states_without_auth_claim(self):
        calendar_check = lambda: True
        email_check = lambda: False
        browser_check = lambda: True
        cached = {calendar_check: True, email_check: False, browser_check: None}.get
        result = discover([
            _Entry("pa"), _Entry("calendar_list", calendar_check),
            _Entry("gmail_search", email_check), _Entry("browser_open", browser_check),
            _Entry("kanban_show"),
        ], cached)
        rows = {row["id"]: row for row in result["capabilities"]}
        self.assertEqual(rows["calendar"]["status"], "available")
        self.assertEqual(rows["email"]["status"], "needs-setup")
        self.assertEqual(rows["browser"]["status"], "unverified")
        self.assertEqual(rows["messaging"]["status"], "unavailable")
        self.assertTrue(all(row["authentication"] == "unverified" for row in rows.values()))
        self.assertTrue(all(isinstance(row["recovery_action"], str) and row["recovery_action"]
                            for row in rows.values()))

    def test_recipes_separate_ordinary_work_from_provider_transactions(self):
        recipes = catalog()
        self.assertEqual(recipes["R1"]["transaction_protocol"], [])
        self.assertEqual(recipes["R4"]["transaction_protocol"], [])
        self.assertEqual(recipes["R5"]["transaction_protocol"], [])
        for recipe_id in ("R2", "R3", "R6", "R7", "R8"):
            operations = [step["operation"] for step in recipes[recipe_id]["transaction_protocol"]]
            self.assertEqual(operations,
                             ["action_prepare", "action_confirm", "action_result"])
            self.assertEqual(recipes[recipe_id]["execution_claim"]["mode"], "native_gateway")
            self.assertIn("action_cancel", recipes[recipe_id]["operations"])
        self.assertEqual(recipes["R1"]["required_capabilities"], ["portable_files"])

    def test_native_registration_uses_frontmatter_descriptions_lazily(self):
        spec = importlib.util.spec_from_file_location(
            "pa_plugin_fixture", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as root:
            registrations = []

            class Context:
                _manager = SimpleNamespace(home_path=root)

                def register_tool(self, **kwargs):
                    self.tools = getattr(self, "tools", {})
                    self.tools[kwargs["name"]] = kwargs

                def register_hook(self, name, callback):
                    self.hooks = getattr(self, "hooks", {})
                    self.hooks[name] = callback

                def register_command(self, name, handler, **kwargs):
                    self.commands = {name: handler}

                def register_skill(self, name, path, description="", frontmatter=None):
                    registrations.append((name, path, description, frontmatter))

            ctx = Context()
            module.register(ctx)
        sys.modules.pop(spec.name, None)
        self.assertEqual(ctx.tools["pa"]["description"], ctx.tools["pa"]["schema"]["description"])
        self.assertIn("pa_call", ctx.tools)
        self.assertIn("pre_tool_call", ctx.hooks)
        self.assertIn("pre_llm_call", ctx.hooks)
        self.assertIn("pa", ctx.commands)
        self.assertGreaterEqual(len(registrations), 9)
        for name, path, description, frontmatter in registrations:
            self.assertEqual(name, path.parent.name)
            self.assertEqual(description, frontmatter["description"])
            self.assertNotIn("# ", description)


if __name__ == "__main__":
    unittest.main()
