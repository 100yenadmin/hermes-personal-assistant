from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

from personal_assistant.conversation_delivery.bridge import BridgeRuntime, signal_gateway_startup
from personal_assistant.conversation_delivery.config import load_settings
from personal_assistant.conversation_delivery.packet import render_packet
from personal_assistant.conversation_delivery.store import QueueError, QueueStore
from personal_assistant.automation import notification_receipt
from personal_assistant.state import Ledger

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class HermesHost:
    source: Path
    python: Path


def discover_hermes_host() -> HermesHost | None:
    """Use CI's explicit host-root override or the installed import provenance."""
    configured = os.environ.get("HERMES_TEST_HERMES_ROOT") or os.environ.get("HERMES_ROOT")
    if configured:
        source = Path(configured).expanduser().resolve()
        if not (source / "gateway" / "hooks.py").is_file():
            raise RuntimeError(f"configured Hermes host root is not a source checkout: {source}")
        raw_python = os.environ.get("HERMES_TEST_HERMES_PYTHON")
        python = Path(raw_python).expanduser().resolve() if raw_python else Path(sys.executable).resolve()
        if not python.is_file():
            raise RuntimeError(f"configured Hermes host Python is unavailable: {python}")
        return HermesHost(source, python)
    try:
        import hermes_cli
    except ImportError:
        return None
    source = Path(hermes_cli.__file__).resolve().parents[1]
    if not (source / "gateway" / "hooks.py").is_file():
        return None
    return HermesHost(source, Path(sys.executable).resolve())


HERMES_HOST = discover_hermes_host()


def route(*, chat_id: str = "fixture-chat", session_key: str | None = None) -> dict:
    key = session_key or f"agent:main:telegram:group:{chat_id}:9"
    destination = {
        "session_key": key,
        "platform": "telegram",
        "chat_type": "group",
        "chat_id": chat_id,
        "thread_id": "9",
    }
    return {
        "source": "existing-host-session",
        "verified": True,
        "profile_name": "default",
        "namespace": "main",
        "destination": destination,
        "allowlist": [destination.copy()],
    }


def packet(destination: dict, *, event_id: str = "morning:fixture", revision: str = "r1",
           value: str = "same", observed: float = 1000.0, expires: float = 2000.0) -> dict:
    return {
        "version": 1,
        "event_id": event_id,
        "revision": revision,
        "kind": "morning_brief",
        "observed_at": observed,
        "expires_at": expires,
        "destination": destination,
        "source": [{"identity": "collector:fixture", "revision": revision, "links": []}],
        "facts": [{"label": "selected evidence", "value": value}],
        "coverage": {"status": "partial", "notes": "synthetic fixture"},
        "failures": [],
    }


def settings(tmp_path: Path):
    return load_settings({
        "state_dir": str(tmp_path / "state"),
        "route": route(),
        "poll_interval_seconds": 0.1,
        "max_packet_bytes": 16 * 1024,
    })


def write_route(home: Path) -> Path:
    path = home / "route.json"
    path.write_text(json.dumps(route()), encoding="utf-8")
    path.chmod(0o600)
    return path


def producer_cmd(home: Path, state: Path, route_file: Path, *extra: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "personal_assistant.conversation_delivery.producer",
        "enqueue",
        "--state-dir",
        str(state),
        "--route-file",
        str(route_file),
        "--kind",
        "morning_brief",
        "--identity",
        "morning:fixture",
        "--observed-at",
        "1000",
        "--expires-at",
        "2000",
        "--quiet",
        *extra,
    ]


def isolated_env(home: Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "HERMES_HOME": str(home),
        "HERMES_PROFILE_NAME": "default",
        "PYTHONPATH": str(ROOT),
        "PATH": os.environ.get("PATH", ""),
        "DENY_NETWORK": "1",
    }


def load_root_plugin():
    spec = importlib.util.spec_from_file_location(
        "pa_conversation_delivery_plugin_test",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PluginContext:
    profile_name = "default"

    def __init__(self, home: Path, *, enabled: bool):
        state = home / "plugin-data" / "bridge"
        self.values = {
            "conversation_delivery": {
                "enabled": enabled,
                "state_dir": str(state),
                "route": route(),
                "poll_interval_seconds": 0.1,
                "max_packet_bytes": 16 * 1024,
            } if enabled else {},
        }
        self.tools = []
        self.hooks = {}
        self.tasks = []
        self.unload_callbacks = []

    def get_config(self, key, default=None):
        return self.values.get(key, default)

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_command(self, name, handler, **kwargs):
        self.commands = {name: handler}

    def register_skill(self, *args, **kwargs):
        return None

    def spawn_task(self, coroutine, *, name=None):
        task = asyncio.create_task(coroutine, name=name)
        self.tasks.append(task)
        return task

    def on_unload(self, callback):
        self.unload_callbacks.append(callback)



def test_disabled_native_registration_has_no_delivery_side_effects(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HERMES_HOME", str(home))
    context = PluginContext(home, enabled=False)
    load_root_plugin().register(context)
    assert [tool["name"] for tool in context.tools] == ["pa", "pa_call"]
    assert context.tasks == []
    assert "pre_llm_call" in context.hooks and "pa" in context.commands
    assert context.unload_callbacks == []
    assert not (home / "plugin-data").exists()



def test_opt_in_native_registration_uses_supervised_task_and_unload(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HERMES_HOME", str(home))
    # This is a hostless unit test: provide only the host contract used by
    # registration, rather than importing a developer Hermes installation.
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: str(home))
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    async def scenario():
        context = PluginContext(home, enabled=True)
        load_root_plugin().register(context)
        assert [tool["name"] for tool in context.tools] == ["pa", "pa_call", "pa_delivery_ack"]
        assert len(context.tasks) == 1
        assert len(context.unload_callbacks) == 1
        # No startup marker exists yet, so the supervised consumer cannot claim.
        await asyncio.sleep(0)
        assert not (home / "plugin-data" / "bridge" / "gateway-startup.json").exists()
        context.unload_callbacks[0]()
        await asyncio.wait_for(context.tasks[0], timeout=1)
        assert context.tasks[0].done()
        assert context.tasks[0].cancelled() is False

    asyncio.run(scenario())


class Host:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.calls = []

    def inject_message(self, content, role="user", *, session_key=None):
        self.calls.append((content, role, session_key))
        return self.accepted



def test_queue_unchanged_repeat_is_silent_and_revision_is_new(tmp_path):
    destination = route()["destination"]
    store = QueueStore(tmp_path / "state", clock=lambda: 1000.0)
    assert stat.S_IMODE(store.db_path.stat().st_mode) == 0o600
    assert store.publish(packet(destination)) is True
    assert store.publish(packet(destination, observed=1001, expires=3000)) is False
    assert store.publish(packet(destination, revision="r2", value="new evidence")) is True
    with pytest.raises(QueueError, match="collision"):
        store.publish(packet(destination, value="different evidence"))
    claim = store.claim_next()
    assert claim is not None
    assert claim.packet["observed_at"] == 1000.0
    assert store.counts()["pending"] == 1



def test_route_mismatch_fails_before_host_injection(tmp_path):
    cfg = settings(tmp_path)
    store = QueueStore(cfg.state_dir, clock=lambda: 1000.0)
    wrong = route(chat_id="different-chat")["destination"]
    store.publish(packet(wrong))
    host = Host()
    runtime = BridgeRuntime(host, cfg, store=store, clock=lambda: 1000.0)
    signal_gateway_startup(cfg.state_dir, token="fixture-startup")
    result = asyncio.run(runtime.poll_once())
    assert result["status"] == "failed"
    assert host.calls == []
    assert store.row("morning:fixture", "r1")["state"] == "failed"
    runtime.stop()



def test_admission_unknown_is_not_transport_receipt_and_ack_is_session_bound(tmp_path):
    cfg = settings(tmp_path)
    store = QueueStore(cfg.state_dir, clock=lambda: 1000.0)
    store.publish(packet(cfg.destination))
    host = Host()
    runtime = BridgeRuntime(
        host,
        cfg,
        store=store,
        clock=lambda: 1000.0,
        session_key_provider=lambda: "wrong-session",
    )
    signal_gateway_startup(cfg.state_dir, token="fixture-startup")
    result = asyncio.run(runtime.poll_once())
    assert result["status"] == "unknown"
    assert "final delivery unknown" in result["reason"]
    claim_token = store.row("morning:fixture", "r1")["claim_token"]
    bad = json.loads(runtime.ack_tool({
        "event_id": "morning:fixture",
        "revision": "r1",
        "claim_token": claim_token,
        "outcome": "handled",
    }))
    assert bad["ok"] is False
    runtime._session_key_provider = lambda: cfg.destination["session_key"]
    good = json.loads(runtime.ack_tool({
        "event_id": "morning:fixture",
        "revision": "r1",
        "claim_token": claim_token,
        "outcome": "silent",
        "session_key": "spoofed-argument-is-ignored",
    }))
    assert good["ok"] is True and good["state"] == "silent"
    assert store.row("morning:fixture", "r1")["state"] == "silent"



def test_private_concurrent_producers_keep_both_rows(tmp_path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    route_file = write_route(home)
    state = home / "plugin-data" / "bridge"
    env = isolated_env(home)
    first = subprocess.Popen(
        producer_cmd(home, state, route_file, "--identity", "morning:first", "--text", "A"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    second = subprocess.Popen(
        producer_cmd(home, state, route_file, "--identity", "morning:second", "--text", "B"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    first_out, first_err = first.communicate(timeout=15)
    second_out, second_err = second.communicate(timeout=15)
    assert first.returncode == 0, first_err.decode()
    assert second.returncode == 0, second_err.decode()
    assert first_out == second_out == b""
    store = QueueStore(state)
    assert store.counts() == {"pending": 2}
    assert stat.S_IMODE(store.db_path.stat().st_mode) == 0o600



def test_producer_module_entrypoint_isolated_and_revision_aware(tmp_path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    route_file = write_route(home)
    state = home / "state"
    env = isolated_env(home)
    base = producer_cmd(home, state, route_file, "--text", "same evidence")
    first = subprocess.run(base, capture_output=True, env=env)
    repeat = subprocess.run(base, capture_output=True, env=env)
    changed = subprocess.run(
        producer_cmd(home, state, route_file, "--text", "revised evidence"),
        capture_output=True,
        env=env,
    )
    assert first.returncode == repeat.returncode == changed.returncode == 0
    assert first.stdout == repeat.stdout == changed.stdout == b""
    assert QueueStore(state).counts() == {"pending": 2}



def test_runner_module_entrypoint_publishes_bounded_fixture(tmp_path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    route_file = write_route(home)
    state = home / "state"
    env = isolated_env(home)
    command = [
        sys.executable,
        "-m",
        "personal_assistant.conversation_delivery.runner",
        "run",
        "--state-dir",
        str(state),
        "--route-file",
        str(route_file),
        "--kind",
        "morning_brief",
        "--identity",
        "morning:runner",
        "--observed-at",
        "1000",
        "--expires-at",
        "2000",
        "--quiet",
        "--",
        sys.executable,
        "-c",
        "print('synthetic collector evidence')",
    ]
    result = subprocess.run(command, capture_output=True, env=env)
    assert result.returncode == 0, result.stderr.decode()
    claim = QueueStore(state, clock=lambda: 1000.0).claim_next()
    assert claim is not None
    assert claim.packet["facts"][0]["value"] == "synthetic collector evidence"
    assert claim.packet["coverage"]["status"] == "partial"


def test_priority_collector_module_entrypoint_publishes_selected_fixture(tmp_path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    route_file = write_route(home)
    state = home / "state"
    fixture_file = home / "fixture.json"
    wrapped = (
        "<<<EXTERNAL_UNTRUSTED_CONTENT id=fixture>>>\n"
        "--- payload ---\nPlease review this fixture.\n"
        "<<<END_EXTERNAL_UNTRUSTED_CONTENT id=fixture>>>"
    )
    fixture_file.write_text(json.dumps({
        "work|search|": {
            "externalContent": {"source": "gmail", "untrusted": True, "wrapped": True},
            "messages": [{
                "date": "2026-09-17T10:00:00+00:00",
                "from": "Alerts <alerts@wise.example>",
                "id": "m1",
                "labels": ["CATEGORY_UPDATES"],
                "subject": "Account review",
                "threadId": "t1",
            }],
        },
        "work|get|m1": {
            "body": wrapped,
            "externalContent": {"source": "gmail", "untrusted": True, "wrapped": True},
            "headers": {
                "date": "Thu, 17 Sep 2026 10:00:00 +0000",
                "from": "Alerts <alerts@wise.example>",
                "message_id": "m1",
                "subject": "Account review",
                "to": "owner@example.invalid",
            },
            "message": {
                "body": wrapped,
                "headers": {},
                "id": "m1",
                "internalDate": "1789639200000",
                "labelIds": ["CATEGORY_UPDATES"],
                "sizeEstimate": len(wrapped.encode("utf-8")),
                "snippet": "Please review this fixture.",
                "threadId": "t1",
            },
        },
    }), encoding="utf-8")
    config = home / "priority.json"
    config.write_text(json.dumps({
        "version": 1,
        "enabled": True,
        "connector": {"command": str(ROOT / "personal_assistant/conversation_delivery/priority/tests/fake_gog.py")},
        "accounts": [{"alias": "work", "account": "work", "account_selector": "0"}],
        "rules": [{"id": "wise", "field": "sender", "pattern": "wise.example", "query": "from:(wise.example)"}],
        "filters": {"self_emails": [], "self_domains": []},
        "limits": {"expiry_seconds": 604800},
        "source_link_template": "https://mail.google.com/mail/u/?authuser={account_selector}#all/{thread_id}/{message_id}",
    }), encoding="utf-8")
    config.chmod(0o600)
    (home / "config.yaml").write_text(
        "plugins:\n"
        "  entries:\n"
        "    personal-assistant:\n"
        "      settings:\n"
        "        conversation_delivery:\n"
        "          enabled: true\n"
        "          priority_mail: true\n",
        encoding="utf-8",
    )
    (home / "config.yaml").chmod(0o600)
    env = dict(isolated_env(home), FAKE_GOG_FIXTURE=str(fixture_file), DENY_NETWORK="1")
    result = subprocess.run([
        sys.executable, "-m", "personal_assistant.conversation_delivery.priority_runner", "run",
        "--config", str(config), "--bridge-state-dir", str(state), "--route-file", str(route_file),
        "--gog-command", str(ROOT / "personal_assistant/conversation_delivery/priority/tests/fake_gog.py"),
        "--observed-at", "1789639200", "--quiet",
    ], capture_output=True, env=env)
    assert result.returncode == 0, result.stderr.decode()
    store = QueueStore(state, clock=lambda: 1789639200.0)
    assert store.counts() == {"pending": 1}
    claim = store.claim_next()
    assert claim is not None
    assert claim.event_id == "priority-mail/work/m1"
    assert "Please review this fixture." in render_packet(claim.packet, claim.token)
    linkage = claim.packet["native_linkage"]
    assert linkage["owner"] == "personal_assistant.automation"
    assert linkage["final_notification"] == "none"
    assert linkage["rule_id"] == "priority_mail"
    assert notification_receipt(Ledger(home), linkage["automation_occurrence_id"]) is None


@pytest.mark.parametrize("host_config", [None, """plugins:
  entries:
    personal-assistant:
      settings:
        conversation_delivery:
          enabled: true
          priority_mail: false
"""])
def test_priority_runner_requires_explicit_host_ownership_before_provider_or_queue(tmp_path, host_config):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    if host_config is not None:
        host_path = home / "config.yaml"
        host_path.write_text(host_config, encoding="utf-8")
        host_path.chmod(0o600)
    argv_log = home / "provider-argv.log"
    env = dict(isolated_env(home), FAKE_GOG_ARGV_LOG=str(argv_log), DENY_NETWORK="1")
    result = subprocess.run([
        sys.executable, "-m", "personal_assistant.conversation_delivery.priority_runner", "run",
        "--config", str(home / "priority.json"),
        "--bridge-state-dir", str(home / "state"),
        "--route-file", str(home / "route.json"),
        "--gog-command", str(ROOT / "personal_assistant/conversation_delivery/priority/tests/fake_gog.py"),
        "--observed-at", "1789639200", "--quiet",
    ], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "" and result.stderr == ""
    assert not argv_log.exists()
    assert not (home / "state").exists()
    assert not (home / ".pa-priority-collection.lock").exists()


def test_priority_lease_requires_explicit_opt_in_and_prevents_sequential_duplicate_owner(tmp_path):
    from personal_assistant.priority_ownership import priority_collection_lease

    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    with priority_collection_lease(home, "legacy") as legacy:
        assert legacy.state == "owned"
    with priority_collection_lease(home, "conversation") as conversation:
        assert conversation.state == "disabled"

    enabled_home = tmp_path / "enabled-home"
    enabled_home.mkdir(mode=0o700)
    config_path = enabled_home / "config.yaml"
    config_path.write_text(
        "plugins:\n"
        "  entries:\n"
        "    personal-assistant:\n"
        "      settings:\n"
        "        conversation_delivery:\n"
        "          enabled: true\n"
        "          priority_mail: true\n",
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    with priority_collection_lease(enabled_home, "legacy") as legacy:
        assert legacy.state == "delegated"
    with priority_collection_lease(enabled_home, "conversation") as conversation:
        assert conversation.state == "owned"


@pytest.mark.parametrize("host_config", [
    "plugins: [",
    """plugins:
  entries:
    personal-assistant:
      settings:
        conversation_delivery:
          enabled: true
          priority_mail: all
""",
])
def test_actual_watchdog_preserves_urgent_p0_on_priority_arbitration_failure(tmp_path, monkeypatch, capsys, host_config):
    from personal_assistant.daily_ops import watchdog

    root = tmp_path / "profile"
    root.mkdir(mode=0o700)
    daily_config = {
        "tenant": {"profile_id": "fixture-profile", "owner_email": "owner@example.invalid"},
        "delivery": {"target": "fixture-topic", "verified": True},
        "timezone": "UTC",
        "accounts": {"work": "owner@example.invalid", "personal": None},
        "priority": {"static_terms": []},
        "travel": {"leave_by": False, "buffer_min": 15, "heads_up_min": 45, "geocoder": {"consent": False}},
        "schedules": {"watchdog": "*/15 * * * *"},
        "autoclean": {"enabled": False},
    }
    daily_path = root / "daily_ops.config.json"
    daily_path.write_text(json.dumps(daily_config), encoding="utf-8")
    daily_path.chmod(0o600)
    host_path = root / "config.yaml"
    host_path.write_text(host_config, encoding="utf-8")
    host_path.chmod(0o600)
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("DAILY_OPS_PROFILE_ROOT", str(root))
    monkeypatch.setenv("DAILY_OPS_CONFIG", str(daily_path))
    monkeypatch.setenv("DAILY_OPS_NOW", "2026-09-18T03:00:00+00:00")
    monkeypatch.setattr(watchdog.trip_context, "collect_trip", lambda *args, **kwargs: (
        {"calendar_coverage": [{"account": "fixture", "status": "complete"}]},
        [{"key": "leave:urgent", "line": "urgent leave-by alert"}],
        True,
        False,
    ))

    def mailbox_must_not_be_called(*args, **kwargs):
        raise AssertionError("P1 mailbox collection ran after arbitration failure")

    monkeypatch.setattr(watchdog, "p1_alerts", mailbox_must_not_be_called)
    watchdog.main()
    output = capsys.readouterr().out
    packet = json.loads(output)
    assert packet["complete"] is False
    assert packet["sections"]["alerts"] == [{
        "kind": "leave_by", "message": "urgent leave-by alert", "identity": "leave:urgent",
    }]
    assert packet["sections"]["degraded"]["priority_complete"] is False
    assert packet["sections"]["degraded"]["reason"] == "provider coverage incomplete"
    assert "priority mail coverage unavailable" not in output
    assert "priority_mail: all" not in output and "plugins: [" not in output


def test_hook_setup_preview_install_idempotency_and_collision(tmp_path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    script = ROOT / "scripts" / "install_conversation_hook.py"

    def invoke(*extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), "setup", "--hermes-home", str(home), "--json", *extra],
            capture_output=True, text=True, env=dict(os.environ, HERMES_HOME=str(home)), check=False,
        )

    preview = invoke("--dry-run")
    assert preview.returncode == 0, preview.stderr
    preview_data = json.loads(preview.stdout)
    assert preview_data["dry_run"] is True
    assert preview_data["permission"]["allow_gateway_injection"]["configured"] is False
    assert preview_data["permission"]["allow_gateway_injection"]["action"] == "operator_must_set_explicitly"
    assert not (home / "hooks").exists()

    first = invoke()
    assert first.returncode == 0, first.stderr
    first_data = json.loads(first.stdout)
    assert first_data["readback"]["performed"] is True
    target = home / "hooks" / "personal-assistant-conversation-delivery-startup"
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert all(stat.S_IMODE((target / name).stat().st_mode) == 0o600 for name in ("HOOK.yaml", "handler.py"))

    repeat = invoke()
    assert repeat.returncode == 0, repeat.stderr
    assert json.loads(repeat.stdout)["action"] == "already_installed"
    handler = target / "handler.py"
    handler.write_bytes(b"different hook")
    collision = invoke()
    assert collision.returncode == 2
    assert "different content" in collision.stderr
    assert handler.read_bytes() == b"different hook"


def test_real_host_hook_discovery_and_bridge_round_trip(tmp_path):
    if HERMES_HOST is None:
        pytest.skip("installed Hermes host source is unavailable; CI injects the pinned root explicitly")
    host = HERMES_HOST
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    (home / "plugins").mkdir()
    installed = home / "plugins" / "personal-assistant"
    shutil.copytree(ROOT, installed, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    state = home / "plugin-data" / "bridge"
    route_file = write_route(home)
    config = home / "config.yaml"
    config.write_text(
        "plugins:\n"
        "  enabled: [personal-assistant]\n"
        "  entries:\n"
        "    personal-assistant:\n"
        "      allow_gateway_injection: true\n"
        "      settings:\n"
        "        conversation_delivery:\n"
        "          enabled: true\n"
        "          priority_mail: true\n"
        f"          state_dir: {str(state)!r}\n"
        "          route:\n"
        "            source: existing-host-session\n"
        "            verified: true\n"
        "            profile_name: default\n"
        "            namespace: main\n"
        "            destination:\n"
        "              session_key: agent:main:telegram:group:fixture-chat:9\n"
        "              platform: telegram\n"
        "              chat_type: group\n"
        "              chat_id: fixture-chat\n"
        "              thread_id: '9'\n"
        "            allowlist:\n"
        "              - session_key: agent:main:telegram:group:fixture-chat:9\n"
        "                platform: telegram\n"
        "                chat_type: group\n"
        "                chat_id: fixture-chat\n"
        "                thread_id: '9'\n",
        encoding="utf-8",
    )
    config.chmod(0o600)
    installer = subprocess.run(
        [sys.executable, str(ROOT / "scripts/install_conversation_hook.py"), "setup",
         "--hermes-home", str(home), "--json"],
        capture_output=True, text=True, env=dict(os.environ, HERMES_HOME=str(home)), check=False,
    )
    assert installer.returncode == 0, installer.stderr
    install_receipt = json.loads(installer.stdout)
    assert install_receipt["readback"]["performed"] is True
    assert install_receipt["permission"]["allow_gateway_injection"]["configured"] is True

    host_code = '''
import asyncio, json, os, subprocess, sys
from pathlib import Path
from gateway.hooks import HookRegistry
from personal_assistant.conversation_delivery.bridge import BridgeRuntime
from personal_assistant.conversation_delivery.config import load_settings
from personal_assistant.conversation_delivery.store import QueueStore

home = Path(os.environ["HERMES_HOME"])
state = home / "plugin-data" / "bridge"
destination = {
    "session_key": "agent:main:telegram:group:fixture-chat:9", "platform": "telegram",
    "chat_type": "group", "chat_id": "fixture-chat", "thread_id": "9",
}
settings = load_settings({"state_dir": str(state), "route": {
    "source": "existing-host-session", "verified": True, "profile_name": "default",
    "namespace": "main", "destination": destination, "allowlist": [dict(destination)],
}, "poll_interval_seconds": 0.1, "max_packet_bytes": 16 * 1024})

class Host:
    def __init__(self): self.calls = []
    def inject_message(self, content, role="user", *, session_key=None):
        self.calls.append((content, role, session_key))
        return True

async def main():
    host = Host()
    # Construct the production consumer before startup so the fresh marker is a gate.
    runtime = BridgeRuntime(host, settings, clock=lambda: 1000.0,
                            session_key_provider=lambda: destination["session_key"])
    registry = HookRegistry()
    registry.discover_and_load()
    await registry.emit("gateway:startup", {"platforms": ["fixture"]})
    producer = subprocess.run([
        sys.executable, "-m", "personal_assistant.conversation_delivery.producer", "enqueue",
        "--state-dir", str(state), "--route-file", str(home / "route.json"),
        "--kind", "morning_brief", "--identity", "morning:host-discovery",
        "--observed-at", "1000", "--expires-at", "2000", "--text", "host evidence", "--quiet",
    ], capture_output=True, text=True, env=os.environ.copy(), check=False)
    poll = await runtime.poll_once()
    row = QueueStore(state).row("morning:host-discovery", "" + __import__("hashlib").sha256(b"host evidence").hexdigest()[:16])
    if row is None:
        rows = QueueStore(state)._connect().execute("select event_id,revision,claim_token,state from packets").fetchall()
        row = dict(rows[0])
    ack = json.loads(runtime.ack_tool({"event_id": row["event_id"], "revision": row["revision"],
                                       "claim_token": row["claim_token"], "outcome": "silent"}))
    print(json.dumps({"loaded_hooks": registry.loaded_hooks, "marker": json.loads(
        (state / "gateway-startup.json").read_text()), "producer_rc": producer.returncode,
        "producer_stderr": producer.stderr, "poll": poll, "host_calls": len(host.calls),
        "session_key": host.calls[0][2] if host.calls else None, "ack": ack,
        "final_state": QueueStore(state).row(row["event_id"], row["revision"])["state"]}, sort_keys=True))

asyncio.run(main())
'''
    env = dict(os.environ, HOME=str(home), HERMES_HOME=str(home), HERMES_PROFILE_NAME="default",
               PYTHONPATH=os.pathsep.join((str(installed), str(host.source))))
    result = subprocess.run([str(host.python), "-c", host_code], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout.splitlines()[-1])
    assert any(item["name"] == "personal-assistant-conversation-delivery-startup"
               for item in observed["loaded_hooks"])
    assert observed["marker"]["platforms"] == ["fixture"]
    assert observed["producer_rc"] == 0, observed["producer_stderr"]
    assert observed["poll"]["status"] == "unknown"
    assert observed["host_calls"] == 1
    assert observed["session_key"] == route()["destination"]["session_key"]
    assert observed["ack"] == {"event_id": "morning:host-discovery", "ok": True,
                                 "revision": observed["ack"]["revision"], "state": "silent"}
    assert observed["final_state"] == "silent"


def test_real_installed_loader_keeps_opt_in_on_same_native_plugin(tmp_path):
    if HERMES_HOST is None:
        pytest.skip("installed Hermes host source is unavailable; CI injects the pinned root explicitly")
    host = HERMES_HOST
    def run_loader(home: Path, enabled: bool) -> dict:
        home.mkdir(mode=0o700)
        plugin = home / "plugins" / "personal-assistant"
        plugin.parent.mkdir(parents=True)
        plugin.symlink_to(ROOT, target_is_directory=True)
        state = home / "plugin-data" / "bridge"
        if enabled:
            settings = (
                "        conversation_delivery:\n"
                "          enabled: true\n"
                f"          state_dir: {str(state)!r}\n"
                "          route:\n"
                "            source: existing-host-session\n"
                "            verified: true\n"
                "            profile_name: default\n"
                "            namespace: main\n"
                "            destination:\n"
                "              session_key: agent:main:telegram:group:fixture-chat:9\n"
                "              platform: telegram\n"
                "              chat_type: group\n"
                "              chat_id: fixture-chat\n"
                "              thread_id: nine\n"
                "            allowlist:\n"
                "              - session_key: agent:main:telegram:group:fixture-chat:9\n"
                "                platform: telegram\n"
                "                chat_type: group\n"
                "                chat_id: fixture-chat\n"
                "                thread_id: nine\n"
            )
        else:
            settings = ""
        (home / "config.yaml").write_text(
            "plugins:\n  enabled:\n    - personal-assistant\n  entries:\n    personal-assistant:\n      settings:\n" + settings,
            encoding="utf-8",
        )
        code = (
            "import json\n"
            "from hermes_cli.plugins import discover_plugins, get_plugin_manager\n"
            "from tools.registry import registry\n"
            "discover_plugins()\n"
            "m=get_plugin_manager(); p=m._plugins['personal-assistant']\n"
            "print(json.dumps({'enabled':p.enabled, 'error':p.error, 'tools':p.tools_registered, "
            "'ack':registry.get_entry('pa_delivery_ack', scope=m.scope_key) is not None}))\n"
        )
        env = {
            "HOME": str(home),
            "HERMES_HOME": str(home),
            "PYTHONPATH": str(host.source),
            "PATH": os.environ.get("PATH", ""),
            "HERMES_SAFE_MODE": "0",
        }
        result = subprocess.run(
            [str(host.python), "-c", code], capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.splitlines()[-1])

    disabled = run_loader(tmp_path / "disabled", False)
    assert disabled["enabled"] is True and disabled["error"] is None
    assert disabled["ack"] is False
    assert not (tmp_path / "disabled" / "plugin-data").exists()
    enabled = run_loader(tmp_path / "enabled", True)
    assert enabled["enabled"] is True and enabled["error"] is None
    assert enabled["ack"] is True
    assert "pa_delivery_ack" in enabled["tools"]
    assert (tmp_path / "enabled" / "plugin-data" / "bridge" / "queue.sqlite3").exists()
