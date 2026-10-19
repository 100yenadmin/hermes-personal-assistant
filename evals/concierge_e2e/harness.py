"""Glue adapted from heartbeat2/tests/e2e/harness.py at HB2 commit 3ed7a21."""
import dataclasses
import html
import importlib.util
import json
import os
import shutil
import shlex
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from tests.e2e.core.platforms._drv_telegram import TelegramDriver
from tests.e2e.core.platforms._helpers import Director, GatewayUnderTest, _deep_merge, REPO_ROOT
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall
from tests.fakes.platforms._standin import wait_until

ROOT = Path(__file__).resolve().parents[2]


class WakeDirector(Director):
    def __init__(self):
        super().__init__()
        self.actions, self.errors = [], []

    def __call__(self, record):
        current = next((self._text(m) for m in reversed(record["body"]["messages"]) if m["role"] == "user"), "")
        if not current.startswith(("hi", "Trip T1:", "Trip T3:", "no thanks", "⟦pulse")):
            return super().__call__(record)
        try:
            assert self.actions, "Unexpected model request"
            action = self.actions.pop(0)
            return action(record) if callable(action) else action
        except Exception:
            import traceback
            self.errors.append(traceback.format_exc())
            return Text("RIG-FAILED")


class ConciergeRig:
    def __init__(self, pin, director=None, toolsets=(), *, hb2_settings=None,
                 observe_settings=None, weather=False, live_auth=None):
        assert pin == REPO_ROOT.resolve() and ".hermes" not in pin.parts
        dest = Path(os.environ["PA_E2E_RESULTS"])
        dest.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="concierge-", dir=dest))
        self.driver, self.director = TelegramDriver(), director or WakeDirector()
        self.weather = None
        self.live_auth = live_auth
        if weather:
            from weather import WeatherServer
            self.weather = WeatherServer()
            observe_settings = {**(observe_settings or {}), "weather_provider": "local",
                                "local_base_url": self.weather.url}
        self.llm = FakeLLMServer(self.director, aux=lambda r: Text("No auxiliary work."))
        self.driver.start()
        self.llm.start()
        try:
            self._build(toolsets, hb2_settings or {}, observe_settings or {})
        except BaseException:
            self.llm.stop()
            self.driver.stop()
            if self.weather:
                self.weather.close()
            raise

    def _build(self, toolsets, hb2_settings, observe_settings):
        runtime = Path(tempfile.mkdtemp(prefix="pa-rig-", dir="/private/tmp")).resolve()
        observer = runtime / "home/.hermes/plugins/personal-assistant/scripts/pa_observe.py"
        self.observer_command = shlex.join([sys.executable, "-I", str(observer)])
        cfg = {"plugins": {"enabled": ["heartbeat2", "personal-assistant"], "entries": {
            "heartbeat2": {"enabled": True, "allow_gateway_injection": True, "settings": {
                "quiet_hours": "", "timezone": "UTC", "wake_spacing_minutes": 0,
                "min_interval_minutes": 1, "agent_ungated_floor_minutes": 1,
                "probe_floor_seconds": 1, "max_unanswered": 2, "max_active": 10,
                "max_messages_per_day": 20, "max_model_wakes_per_day": 40,
                "owner_silent_checkin": False, **hb2_settings,
                "probe_commands": self.observer_command}},
            "personal-assistant": {"enabled": True, "settings": {
                "setup_offer": True, "observe": observe_settings}}}},
            "display": {"tool_progress": "off", "show_reasoning": False,
                        "platforms": {"telegram": {"tool_progress": "off", "streaming": False}}},
            "streaming": {"enabled": False}, "compression": {"enabled": False},
            "tools": {"tool_search": {"enabled": "off"}},
            "platform_toolsets": {"telegram": ["heartbeat2", "personal_assistant", "skills", *toolsets]},
            "agent": {"api_max_retries": 1, "max_turns": 40}}
        env = {**self.driver.gateway_env(), "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONPATH_PREPEND": str(Path(__file__).parent), "PA_E2E_CHILD": "1",
               "HERMES_GATEWAY_EXTERNAL_SUPERVISOR": "1"}
        self.gateway = GatewayUnderTest(runtime, llm_base_url=self.llm.base_url,
            config=_deep_merge(self.driver.gateway_config(), cfg), env=env, ready=self.ready)
        if self.live_auth:
            self.live_auth.configure(self.gateway)
        spec = importlib.util.spec_from_file_location("pa_release", ROOT / "scripts/build_release.py")
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        pa_files = [p for p in release.selected_files() if not p.startswith("evals/")]
        for name, source, files in (("personal-assistant", ROOT, pa_files),
                ("heartbeat2", Path(os.environ["PA_E2E_HEARTBEAT2"]),
                 ["plugin.yaml", "__init__.py", "heartbeat2", "skills"])):
            for part in files:
                src, target = source / part, self.gateway.hermes_home / "plugins" / name / part
                target.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                else:
                    shutil.copyfile(src, target)

    def ready(self):
        log = self.gateway.hermes_home / "logs/gateway.log"
        return self.driver.connected() and log.exists() and "Press Ctrl+C to stop" in log.read_text()

    def start(self):
        self.gateway._env["PWD"] = str(self.gateway.home)
        self.gateway.start(timeout=50)
        from hermes_state import SessionDB
        db = SessionDB(self.gateway.db_path)
        db.create_session("rig-prior", "test")
        db.close()

    def texts(self):
        return [html.unescape(v.text).replace("\\", "") for v in self.driver.visible(self.driver.user_id)]

    def wait(self, predicate, what, timeout=90):
        return wait_until(predicate, what, timeout=timeout, on_timeout=self.diagnostics)

    def hb2(self):
        path = self.gateway.hermes_home / "plugin-data/heartbeat2/pulse.db"
        if not path.exists():
            return {}
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            return {table: [dict(row) for row in conn.execute('SELECT * FROM "' + table + '"')]
                    for table in ("wakes", "occurrences", "sessions", "ledger")}

    def diagnostics(self):
        return self.gateway.tail() + "\nHB2 rows:\n" + json.dumps(self.hb2(), indent=2)

    def owner(self, text, reply=None, timeout=90):
        before = {v.message_id for v in self.driver.visible(self.driver.user_id)}
        self.driver.dm(text)
        self.wait(lambda: getattr(self.director, "errors", []) or any(v.message_id not in before and (reply is None or reply in
            html.unescape(v.text).replace("\\", "")) for v in self.driver.visible(self.driver.user_id)),
            "reply to " + text[:40], timeout)
        assert not getattr(self.director, "errors", []), self.director.errors
        self.settle(timeout)

    def settle(self, timeout=90, quiet=3.0):
        """Wait until no agent runs and no new bot message arrived for `quiet` seconds.

        A live model can send an interim message before its final reply, and the Telegram
        adapter batches texts sent close together, so the next owner message waits for this.
        """
        deadline, count, since = time.monotonic() + timeout, -1, time.monotonic()
        while time.monotonic() < deadline:
            seen = len(self.driver.visible(self.driver.user_id))
            if seen != count or self.gateway.active_agents():
                count, since = seen, time.monotonic()
            elif time.monotonic() - since >= quiet:
                return
            time.sleep(0.25)
        raise AssertionError(f"gateway did not settle within {timeout}s\n{self.gateway.tail()}")

    def close(self):
        try:
            try:
                self.gateway.stop(timeout=15)
            finally:
                self._keep_evidence()
        finally:
            self.llm.stop()
            self.driver.stop()
            if self.weather:
                self.weather.close()
            print("E2E evidence:", self.root)

    def _keep_evidence(self):
        for step in (self._copy_logs, self._copy_messages, self._copy_ledger, self._copy_hb2):
            try:
                step()
            except Exception as exc:  # Keep whatever evidence the other steps can still save.
                print("E2E evidence step failed:", step.__name__, type(exc).__name__)
        if self.live_auth:
            self.live_auth.finish(self.gateway, self.root)

    def _copy_logs(self):
        shutil.copyfile(self.gateway.log_path, self.root / "gateway.log")
        shutil.copytree(self.gateway.hermes_home / "logs", self.root / "logs")

    def _copy_messages(self):
        for name, data in (("requests", self.llm.main_requests()), ("visible",
                [dataclasses.asdict(v) for v in self.driver.visible(self.driver.user_id)])):
            (self.root / (name + ".json")).write_text(json.dumps(data, indent=2))
        (self.root / "director-errors.json").write_text(json.dumps(getattr(self.director, "errors", []), indent=2))
        if self.weather:
            (self.root / "weather-requests.json").write_text(json.dumps(self.weather.requests, indent=2))

    def _copy_hb2(self):
        (self.root / "hb2.json").write_text(json.dumps(self.hb2(), indent=2))

    def _copy_ledger(self):
        path = self.gateway.hermes_home / "state/travel-ledger/travel.sqlite"
        if path.exists():
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as src:
                with sqlite3.connect(self.root / "ledger.sqlite") as dst:
                    src.backup(dst)
                state = {t: src.execute('SELECT * FROM "' + t + '"').fetchall()
                         for (t,) in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            (self.root / "ledger.json").write_text(json.dumps(state, indent=2))
