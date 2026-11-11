"""Clock coverage and behaviour, offline: no model, process clock or provider IO."""
import ast
import datetime as dt
import importlib.util
import os
import re
import socket
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import personal_assistant
from evals.lab import clock, cos


def unpatched_clocks(source, path):
    """Resolve imported clock aliases, including direct time-function imports."""
    tree, imports = ast.parse(source), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                imports[item.asname or item.name] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module in {"datetime", "time"}:
            for item in node.names:
                imports[item.asname or item.name] = node.module + "." + item.name

    def resolve(node):
        if isinstance(node, ast.Name):
            return imports.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return resolve(node.value) + "." + node.attr
        return ""

    errors = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = resolve(node.func)
        if name == "time.time":
            # Conversation delivery is disabled in lab homes; its epoch clock
            # must stay real, just like TLS, credentials and process deadlines.
            allowed = "personal_assistant/conversation_delivery/" in str(path)
        elif name in {f"datetime.{kind}.{method}" for kind in ("datetime", "date")
                      for method in ("now", "utcnow", "today")}:
            base = node.func.value
            allowed = (isinstance(base, ast.Name) and imports.get(base.id) in {"datetime.datetime", "datetime.date"}
                       or isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name)
                       and base.value.id in clock.MODULE_NAMES and imports.get(base.value.id) == "datetime")
        else:
            continue
        if not allowed:
            errors.append(f"{path}:{node.lineno}: unpatched wall clock {ast.unparse(node.func)}")
    return errors


def test_pa_clock_ast_coverage():
    root = Path(personal_assistant.__file__).parent
    errors = [error for path in root.rglob("*.py")
              for error in unpatched_clocks(path.read_text(), path)]
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize("source", ["from time import time as clock; clock()",
                                   "import datetime as unpatched; unpatched.datetime.now()",
                                   "import time; time.time()"])
def test_clock_lint_positive_controls(source):
    assert unpatched_clocks(source, "personal_assistant/control.py")


@pytest.fixture
def prompt_modules(monkeypatch):
    """Minimal local Hermes surface; exercise real pinned function bodies when requested."""
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.delenv("DAILY_OPS_NOW", raising=False)
    timer = ModuleType("hermes_time")
    timer.now = lambda: dt.datetime.now(dt.timezone.utc)
    timer.get_timezone = lambda: dt.timezone.utc
    timer.safe_strftime = lambda value, fmt: value.strftime(fmt)
    prompt = ModuleType("agent.system_prompt")
    compressor = ModuleType("agent.context_compressor")
    source = os.environ.get("PA_LAB_HERMES_SOURCE")
    if source:
        for module, relative, helpers in (
            (prompt, "agent/system_prompt.py", {"_session_start_like", "_zone_bits", "_timestamp_line"}),
            (compressor, "agent/context_compressor.py", {"_today_for_prompt"}),
        ):
            path = Path(source) / relative
            tree = ast.parse(path.read_text())
            selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in helpers]
            assert {n.name for n in selected} == helpers
            # Load only these pure function bodies, never the agent or its clients.
            module.__dict__.update(Any=object, re=re)
            exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), module.__dict__)
    else:
        exec("def _timestamp_line(agent):\n from hermes_time import now\n return now().isoformat()\n", prompt.__dict__)
        exec("def _today_for_prompt():\n from hermes_time import now\n return now().strftime('%Y-%m-%d')\n", compressor.__dict__)
    for module in (timer, prompt, compressor):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    return timer, prompt, compressor


def test_shifted_pa_helpers_and_restoration(prompt_modules):
    from personal_assistant import access, automation, context, state
    from personal_assistant.daily_ops import common
    original = state.dt, access.datetime
    offset = dt.timedelta(days=2)
    before = dt.datetime.now(dt.timezone.utc) + offset
    with clock.shifted(personal_assistant, offset) as names:
        moments = [dt.datetime.fromisoformat(state.now()), context.evaluation_moment({}),
                   automation._now(None, "UTC"), common.now_utc(), access.AccessManager()._now()]
        after = dt.datetime.now(dt.timezone.utc) + offset
        assert all(before <= moment <= after for moment in moments)
        assert "personal_assistant.state" in names and "personal_assistant.access" in names
        assert "agent.system_prompt" in names
        assert isinstance(dt.datetime(2026, 1, 1), state.dt.datetime)
        assert issubclass(dt.datetime, state.dt.datetime)
        assert isinstance(dt.date(2026, 1, 1), state.dt.date)
        with pytest.raises(RuntimeError, match="nested"):
            with clock.shifted(personal_assistant, offset):
                pass
    assert (state.dt, access.datetime) == original
    assert abs((dt.datetime.fromisoformat(state.now()) - dt.datetime.now(dt.timezone.utc)).total_seconds()) < 1


def test_real_constructors_and_shifted_classmethods(prompt_modules):
    with clock.shifted(personal_assistant, dt.timedelta(days=2)):
        shim = personal_assistant.state.dt
        for value in (shim.datetime(2026, 1, 1), shim.datetime.fromisoformat("2026-01-01"),
                      shim.datetime.fromtimestamp(0), shim.datetime.combine(dt.date(2026, 1, 1), dt.time()),
                      shim.datetime.strptime("2026-01-01", "%Y-%m-%d")):
            assert type(value) is dt.datetime
        assert type(shim.date(2026, 1, 1)) is dt.date
        assert type(shim.date.fromisoformat("2026-01-01")) is dt.date
        assert shim.date.fromtimestamp(0) == dt.date.fromtimestamp(0)
        before = dt.datetime.now() + dt.timedelta(days=2)
        assert before <= shim.datetime.today() <= dt.datetime.now() + dt.timedelta(days=2)
        before = dt.datetime.utcnow() + dt.timedelta(days=2)
        assert before <= shim.datetime.utcnow() <= dt.datetime.utcnow() + dt.timedelta(days=2)
        assert shim.date.today() == (dt.datetime.now() + dt.timedelta(days=2)).date()
        assert shim.timezone is dt.timezone and shim.timedelta is dt.timedelta and shim.time is dt.time


def test_plugin_namespace_copy_and_exception_restore(monkeypatch, prompt_modules):
    name = "hermes_plugins.lab_clock.personal_assistant"
    for parent in ("hermes_plugins", "hermes_plugins.lab_clock"):
        if parent not in sys.modules:
            namespace = ModuleType(parent)
            namespace.__path__ = []
            monkeypatch.setitem(sys.modules, parent, namespace)
    spec = importlib.util.spec_from_file_location(name, personal_assistant.__file__,
                                                submodule_search_locations=list(personal_assistant.__path__))
    api = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, api)
    spec.loader.exec_module(api)
    try:
        with pytest.raises(ValueError, match="restore"):
            with clock.shifted(personal_assistant, dt.timedelta(days=2)) as names:
                assert name + ".daily_ops.config" in names
                assert api.state.dt is personal_assistant.state.dt
                assert api.access.datetime is personal_assistant.access.datetime
                raise ValueError("restore")
        assert api.state.dt is dt and api.access.datetime is dt.datetime
    finally:
        for key in list(sys.modules):
            if key.startswith(name + "."):
                del sys.modules[key]


def test_prompt_only_clock_and_session_date(prompt_modules):
    timer, prompt, compressor = prompt_modules
    original = prompt._timestamp_line, compressor._today_for_prompt, timer.now
    simulated = cos.variables("Asia/Singapore", dt.datetime(2026, 11, 11, tzinfo=dt.timezone.utc), 0, 1)["now"]
    moment = dt.datetime.fromisoformat(simulated)
    # Use the owner's prompt zone, as cos.configure does in a shifted lab home.
    timer.get_timezone = lambda: moment.tzinfo
    timer.now = lambda: dt.datetime.now(moment.tzinfo)
    real_now = timer.now
    agent = SimpleNamespace(session_id=cos.session_id("run", moment.timestamp(), 1, local=True),
                            pass_session_id=False, model="synthetic", provider="offline", platform=None)
    with clock.shifted(personal_assistant, moment - dt.datetime.now(dt.timezone.utc)):
        rendered = prompt._timestamp_line(agent)
        expected = moment.strftime("%A, %B %d, %Y") if "Conversation started:" in rendered else moment.isoformat()[:10]
        assert expected in rendered
        assert compressor._today_for_prompt() == moment.date().isoformat()
        agent.session_id = None  # Exercises the renderer's now fallback too.
        assert expected in prompt._timestamp_line(agent)
        assert timer.now is real_now
        assert abs((timer.now() - dt.datetime.now(moment.tzinfo)).total_seconds()) < 1
    assert (prompt._timestamp_line, compressor._today_for_prompt) == original[:2]
    assert timer.now is real_now


@pytest.mark.parametrize("shifted_clock", [True, False])
def test_dialogue_clock_opt_in_preserves_legacy_path(tmp_path, monkeypatch, prompt_modules, shifted_clock):
    from evals.lab import common, runner
    from evals.lab.scenario import load_catalog
    from personal_assistant import entry, state
    import copy

    s = copy.deepcopy(load_catalog()["w01_carry_chase_en"])
    if not shifted_clock:
        s["lab"].pop("clock")
    # Test the step loop without a Hermes gateway or model.
    monkeypatch.setattr(cos, "cron_scope", lambda _: __import__("contextlib").nullcontext())
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)
    hh = tmp_path / "home/.hermes"
    hh.mkdir(parents=True)
    observer = SimpleNamespace(step=0, turn=0, pages=[], capture=lambda _: [])
    start = dt.datetime(2026, 11, 11, tzinfo=dt.timezone.utc)
    meta = {"start": start.timestamp(), "status": "ok"}
    seen = []

    def turn(message, system, hist, platform=None, session_id=None):
        index = observer.step
        now = dt.datetime.fromisoformat(state.now())
        if index == 0:
            values = cos.variables(s["timezone"], start, 16, 0)
            due = (dt.datetime.fromisoformat(values["now"]) + dt.timedelta(days=1)).replace(hour=9)
            state.Ledger(hh).put("action", "lab:cedar", {"counterparty": "Cedar Demo", "due_at": due.isoformat()},
                                 action_type="commitment", status="open")
        else:
            assert state.Ledger(hh).get("action", "lab:cedar")["status"] == "open"
        seen.append((now, hist, session_id))
        return {"final_response": "Cedar Demo's contract draft is held for your yes.",
                "messages": [{"role": "assistant", "content": "prior chat"}]}

    cos.dialogue(hh, tmp_path, Path(__file__).parents[1], s, personal_assistant,
                 turn, observer, meta, runner.ledger)
    assert len(seen) == 2 and not seen[0][1] and not seen[1][1]
    assert seen[0][2] != seen[1][2]
    if shifted_clock:
        assert set(meta["clock_offsets"]) == {"0", "1"}
        assert "personal_assistant.state" in meta["clock_modules"]["1"]
        for index, (now, _, session) in enumerate(seen):
            step = s["steps"][index]
            moment = dt.datetime.fromisoformat(cos.variables(s["timezone"], start, step["hour"], step["day"])["now"])
            assert abs((now - moment).total_seconds()) < 5
            assert session == cos.session_id(tmp_path, moment.timestamp(), index, local=True)
        created = common.read(tmp_path / "ledger-step-0.json")["actions"]
        row = next(r for r in created if r["action_id"] == "lab:cedar")
        assert dt.datetime.fromisoformat(row["created_at"]).date() == start.date()
    else:
        assert "clock_offsets" not in meta and "clock_modules" not in meta
        assert seen[0][2] == cos.session_id(tmp_path, start.timestamp())
        assert seen[1][2] == cos.session_id(tmp_path, start.timestamp(), 1)
        assert all(abs((now - dt.datetime.now(dt.timezone.utc)).total_seconds()) < 5 for now, _, _ in seen)
