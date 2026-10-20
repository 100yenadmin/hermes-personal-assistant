"""Synthetic L31 mode, schedule and stale-wake contracts; no native stores."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import yaml

from personal_assistant import automation as auto
from personal_assistant.automation_workflow import (
    _install_precheck, cron_precheck, preferences, prepare_suggestions, script_main,
)
from personal_assistant.commands import make_pa_command
from personal_assistant.entry import dispatch
from personal_assistant.onboarding_hook import make_pre_llm_call
from personal_assistant.state import Ledger

ROOT = Path(__file__).resolve().parents[1]
COS = ("cos_daily", "cos_weekly")
NAMES = ("personal-assistant-cos-daily", "personal-assistant-cos-weekly")


def config(root, modes=True, *, legacy=False, enabled=True):
    entry = {"config" if legacy else "settings": {"modes": {"chief_of_staff": modes}}}
    (root / "config.yaml").write_text(yaml.safe_dump({"plugins": {
        "enabled": ["personal-assistant"] if enabled else [],
        "entries": {"personal-assistant": entry},
    }}))


def rule(ledger, kind, **extra):
    return auto.upsert_automation_rule(ledger, kind, {
        "kind": kind, "accepted": True, "destination": "telegram:fixture-owner",
        "destination_verified": True, "timezone": "Asia/Tokyo", **extra,
    })


def ledger_at(root, kind="cos_daily"):
    config(root)
    ledger = Ledger(root)
    preferences(ledger, {"timezone": "Asia/Tokyo"})
    rule(ledger, kind)
    return ledger


def native(monkeypatch, root, *, child=False, jobs=(), suggestions=()):
    cron = SimpleNamespace(
        list_jobs=Mock(return_value=list(jobs)), pause_job=Mock(return_value={}),
        remove_job=Mock(return_value=True),
    )
    pending = {s["id"]: s for s in suggestions}
    suggest = SimpleNamespace(get_suggestion=lambda ref: pending.get(ref),
        dismiss_suggestion=Mock(return_value=True), load_suggestions=lambda: list(pending.values()),
        add_suggestion=Mock(side_effect=lambda **kw: {"id": kw["dedup_key"]}))
    monkeypatch.setitem(sys.modules, "cron.jobs", cron)
    monkeypatch.setitem(sys.modules, "cron.suggestions", suggest)
    monkeypatch.setitem(sys.modules, "gateway.session_context", SimpleNamespace(
        get_session_env=lambda key, default=None: "1" if child and key == "HERMES_CRON_SESSION" else default))
    monkeypatch.setitem(sys.modules, "hermes_constants", SimpleNamespace(get_hermes_home=lambda: root))
    return cron, suggest


@pytest.mark.parametrize("modes,expected", [(None, False), ({}, False), ("bad", False),
    ({"chief_of_staff": "true"}, False), ({"chief_of_staff": 1}, False),
    ({"chief_of_staff": True}, True)])
def test_registration_marker(tmp_path, monkeypatch, modes, expected):
    marked = tmp_path / "cos-fixture" / "SKILL.md"
    plain = tmp_path / "plain-fixture" / "SKILL.md"
    marked.parent.mkdir(); plain.parent.mkdir()
    marked.write_text("---\nname: cos-fixture\ndescription: fixture\nmetadata:\n  hermes:\n    pa_mode: chief_of_staff\n---\nfixture")
    plain.write_text("---\nname: plain-fixture\ndescription: fixture\n---\nfixture")
    spec = importlib.util.spec_from_file_location("l31_fixture_plugin", ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    registered = []
    getter = Mock(side_effect=lambda key, default=None: modes if key == "modes" else default)
    ctx = SimpleNamespace(get_config=getter, set_config=Mock(), register_tool=Mock(),
        register_command=Mock(), register_hook=Mock(),
        register_skill=lambda name, *a, **kw: registered.append(name))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with patch.object(Path, "rglob", return_value=iter([marked, plain])):
        module.register(ctx)
    assert "plain-fixture" in registered
    assert ("cos-fixture" in registered) is expected
    assert sum(c.args[0] == "modes" for c in getter.call_args_list) == 1


def test_mode_command_stops_only_cos(tmp_path, monkeypatch):
    ledger = ledger_at(tmp_path)
    for kind in ("cos_weekly", "daily_brief"):
        rule(ledger, kind)
    for kind in COS:
        ledger.put("action", "pa:suggestion:" + kind, {"suggestion_id": kind},
            action_type="automation_reference", status="suggested")
    cron, suggest = native(monkeypatch, tmp_path, jobs=[
        {"id": "daily", "name": "personal-assistant-daily-brief"},
        {"id": "foreign", "name": "cos-daily"},
        *[{"id": kind, "name": name} for kind, name in zip(COS, NAMES)],
    ], suggestions=[{"id": kind, "status": "pending", "job_spec": {"name": name}}
                    for kind, name in zip(COS, NAMES)])
    settings = {"modes": {"other": True}}
    setter = Mock(side_effect=lambda k, v: settings.update({k: v}))
    command = make_pa_command(tmp_path, settings.get, setter)
    assert "Chief of Staff: off" in command("mode")
    assert "/pa mode" in command("help")
    reply = command("mode chief-of-staff on")
    assert settings["modes"] == {"other": True, "chief_of_staff": True}
    assert "hermes gateway restart" in reply and "new session" in reply
    assert "Chief of Staff: on" in command("status")
    reply = command("mode chief-of-staff off")
    assert settings["modes"]["chief_of_staff"] is False
    assert "2" in reply and "paused" in reply and "removed" in reply
    assert {c.args[0] for c in cron.pause_job.call_args_list} == set(COS)
    assert {c.args[0] for c in cron.remove_job.call_args_list} == set(COS)
    assert {c.args[0] for c in suggest.dismiss_suggestion.call_args_list} == set(COS)
    cron.list_jobs.assert_called_once_with(include_disabled=True)
    for row in ledger.list("action"):
        if row["action_type"] == "automation_rule":
            r = auto._rule_data(row)
            assert bool(r.get("paused")) == (r["kind"] in COS)


@pytest.mark.parametrize("cross_profile", [False, True])
def test_mode_refuses_native_guard(tmp_path, monkeypatch, cross_profile):
    cron, _ = native(monkeypatch, tmp_path / "other" if cross_profile else tmp_path,
                     child=not cross_profile)
    setter = Mock()
    reply = make_pa_command(tmp_path, lambda k, d: {}, setter)("mode chief-of-staff off")
    assert "scheduled children" in reply or "profile differs" in reply
    setter.assert_not_called()
    cron.list_jobs.assert_not_called()


@pytest.mark.parametrize("legacy", [False, True])
def test_config_reader_matches_native_fallback(tmp_path, legacy):
    from personal_assistant.modes import cos_enabled, config_getter
    config(tmp_path, legacy=legacy)
    assert cos_enabled(config_getter(tmp_path))
    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    data["plugins"]["entries"]["personal-assistant"]["settings"] = {"modes": {}}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(data))
    assert not cos_enabled(config_getter(tmp_path))


@pytest.mark.parametrize("case,reason", [
    ("disabled", "disabled_or_timezone_missing"), ("off", "chief_of_staff_off"),
    ("unaccepted", "no_accepted_routine"), ("unverified", "no_accepted_routine"),
    ("rule_pause", "no_accepted_routine"), ("rule_snooze", "routine_snoozed"),
    ("pause", "paused"), ("snooze", "snoozed"), ("quiet", "quiet_hours"),
    ("early", "before_cos_time"),
])
@pytest.mark.parametrize("kind", COS)
def test_cos_false_gates(tmp_path, case, reason, kind):
    ledger = ledger_at(tmp_path, kind)
    now = dt.datetime.fromisoformat("2026-10-20T12:00:00+09:00")
    if case == "off": config(tmp_path, False)
    if case == "unaccepted": rule(ledger, kind, accepted=False)
    if case == "unverified": rule(ledger, kind, destination_verified=False)
    if case == "rule_pause": rule(ledger, kind, paused=True)
    if case == "rule_snooze": rule(ledger, kind, snooze_until="2026-10-21T12:00:00+09:00")
    if case == "pause": preferences(ledger, {"paused": True})
    if case == "snooze": preferences(ledger, {"snooze_until": "2026-10-21T12:00:00+09:00"})
    if case == "quiet": now = now.replace(hour=23)
    if case == "early": now = now.replace(hour=9, minute=29)
    if case == "early" and kind == "cos_weekly": now = now.replace(day=19)
    assert cron_precheck(ledger, kind, enabled=case != "disabled", moment=now) == {
        "wakeAgent": False, "reason": reason}
    assert not any(a["action_type"] == "notification" for a in ledger.list("action"))


@pytest.mark.parametrize("kind", COS)
def test_cos_occurrence_once(tmp_path, kind):
    ledger = ledger_at(tmp_path, kind)
    preferences(ledger, {"cos_daily_time": "09:45", "cos_weekly_day": "wed", "cos_weekly_time": "10:15"})
    now = dt.datetime.fromisoformat("2026-12-30T10:15:00+09:00")
    before = now.replace(hour=9, minute=44) if kind == "cos_daily" else now - dt.timedelta(minutes=1)
    assert not cron_precheck(ledger, kind, enabled=True, moment=before)["wakeAgent"]
    if kind == "cos_weekly":
        assert not cron_precheck(ledger, kind, enabled=True, moment=now - dt.timedelta(days=1))["wakeAgent"]
    first = cron_precheck(ledger, kind, enabled=True, moment=now)
    assert first["wakeAgent"]
    auto.record_notification(ledger, first["occurrence_id"], "suppressed")
    assert not cron_precheck(Ledger(tmp_path), kind, enabled=True, moment=now + dt.timedelta(hours=1))["wakeAgent"]
    if kind == "cos_weekly":
        assert not cron_precheck(ledger, kind, enabled=True, moment=now + dt.timedelta(days=4))["wakeAgent"]
    later = now + dt.timedelta(days=1 if kind == "cos_daily" else 7)
    assert cron_precheck(ledger, kind, enabled=True, moment=later)["wakeAgent"]


@pytest.mark.parametrize("changes", [{"cos_daily_time": "25:00"}, {"cos_weekly_time": "9:00"},
    {"cos_weekly_day": "monday"}])
def test_preferences_validate_clock_and_day(tmp_path, changes):
    with pytest.raises(ValueError): preferences(Ledger(tmp_path), changes)


def test_suggestions_and_script_gate(tmp_path, monkeypatch, capsys):
    ledger = ledger_at(tmp_path)
    rule(ledger, COS[1])
    config(tmp_path, False)
    assert prepare_suggestions(ledger)["jobs"] == []
    config(tmp_path)
    cron, suggest = native(monkeypatch, tmp_path)
    jobs = prepare_suggestions(ledger, native=True)["jobs"]
    assert {j["kind"] for j in jobs} == set(COS)
    for job in jobs:
        kind = job["kind"]
        expected = ["personal-assistant:personal-assistant", "personal-assistant:cos-" + kind[4:]]
        if kind == "cos_weekly": expected.append("personal-assistant:cos-radar")
        spec = job["job_spec"]
        assert spec["skills"] == expected
        assert spec["schedule"] == "*/5 * * * *" and spec["deliver"] == "local"
        assert "receipt" in spec["prompt"] and expected[1] in spec["prompt"]
        path = Path(_install_precheck(ledger, kind))
        assert str(path) == spec["script"] and kind in path.read_text()
    assert suggest.add_suggestion.call_count == 2
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config(tmp_path, False, legacy=True)
    script_main(COS[0])
    assert json.loads(capsys.readouterr().out) == {"wakeAgent": False, "reason": "chief_of_staff_off"}


@pytest.mark.parametrize("prefix", ["", "[internal notification] "])
def test_stale_wake_only_cos_while_off(tmp_path, prefix):
    header = prefix + "⟦pulse o:o_fixture a:1 n:tag⟧ [HeartBeat 2.0 · wake w_fixture · fixture · armed by the owner 1m ago]\n"
    hook = make_pre_llm_call(tmp_path, lambda k, d: {} if k == "modes" else d)
    text = header + "Your note: Load personal-assistant:cos-daily and run it."
    result = hook(user_message=text, platform="telegram")
    assert "Chief of Staff mode is off" in result["context"]
    assert all(word in result["context"] for word in ("pulse", "cancel", "record nothing", "send no message"))
    assert hook(user_message=text.replace("cos-daily", "travel-mode"), platform="telegram") is None
    assert hook(user_message="Please load personal-assistant:cos-daily", platform="telegram") is None
    assert make_pre_llm_call(tmp_path, lambda k, d: {"chief_of_staff": True} if k == "modes" else d)(user_message=text) is None


def test_status_mode(tmp_path):
    config(tmp_path)
    assert dispatch(tmp_path, {"operation": "status"})["modes"]["chief_of_staff"] is True


@pytest.mark.parametrize("kind", COS)
def test_cos_rule_revision_cannot_repeat_report(tmp_path, kind):
    ledger = ledger_at(tmp_path, kind)
    now = dt.datetime.fromisoformat("2026-10-20T12:00:00+09:00")
    rule(ledger, kind, profile_id="fixture-profile", account="fixture-account", rule_revision="v1")
    assert cron_precheck(ledger, kind, enabled=True, moment=now)["wakeAgent"]
    rule(ledger, kind, profile_id="fixture-profile", account="fixture-account", rule_revision="v2")
    assert not cron_precheck(ledger, kind, enabled=True, moment=now)["wakeAgent"]


def test_setup_error_response_is_unchanged(tmp_path):
    with patch("personal_assistant.commands.setup.state", side_effect=ValueError("fixture error")):
        assert make_pa_command(tmp_path)("status") == "Sorry, setup is unavailable right now. Please try again."


def test_mode_off_uses_ledger_refs_and_exact_names(tmp_path, monkeypatch):
    ledger = ledger_at(tmp_path)
    ledger.put("action", "pa:suggestion:cos_daily", {"suggestion_id": "referenced"},
               action_type="automation_reference")
    cron, suggest = native(monkeypatch, tmp_path,
        jobs=[{"id": "cos", "name": NAMES[0]}, {"id": "unrelated", "name": "unrelated"}],
        suggestions=[{"id": "referenced", "status": "pending", "job_spec": {"name": "old-name"}},
            {"id": "pending", "status": "pending", "job_spec": {"name": NAMES[1]}},
            {"id": "foreign", "status": "pending", "job_spec": {"name": "foreign"}}])
    make_pa_command(tmp_path, lambda k, d: {}, Mock())("mode chief-of-staff off")
    cron.remove_job.assert_called_once_with("cos")
    assert {c.args[0] for c in suggest.dismiss_suggestion.call_args_list} == {"referenced", "pending"}


@pytest.mark.parametrize("raw", ["[]", "plugins: []", "plugins: {entries: {personal-assistant: []}}", "malformed: ["])
def test_bad_config_is_off(tmp_path, raw):
    from personal_assistant.modes import cos_enabled, config_getter
    (tmp_path / "config.yaml").write_text(raw)
    assert not cos_enabled(config_getter(tmp_path))


@pytest.mark.parametrize("startup_on", [True, False])
def test_registered_cos_skills_are_gated_after_mode_off(tmp_path, monkeypatch, startup_on):
    native(monkeypatch, tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("l31b_fixture_plugin", ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    settings = {"modes": {"chief_of_staff": startup_on}, "setup_offer": False}
    hooks, commands, skills = {}, {}, []
    ctx = SimpleNamespace(get_config=settings.get, set_config=lambda k, v: settings.update({k: v}),
        register_tool=Mock(), register_skill=lambda name, *a, **kw: skills.append(name),
        register_command=lambda name, handler, **kw: commands.update({name: handler}),
        register_hook=lambda name, handler: hooks.update({name: handler}))
    module.register(ctx)
    assert ("cos-daily" in skills) is startup_on
    reply = commands["pa"]("mode chief-of-staff off")
    expected = {"context": "Chief of Staff mode is off: do not load or run personal-assistant:cos-* skills; if asked, say it is off and how to turn it on."}
    for message in ("Hello", "Please run cos-daily", "And now?"):
        assert hooks["pre_llm_call"](user_message=message, platform="telegram") == (expected if startup_on else None)
    assert "CoS schedules and follow-ups have stopped now" in reply
    assert "CoS skills disappear after hermes gateway restart and a new session" in reply
    assert hooks["pre_llm_call"](user_message="Machine tick", platform="cron") is None
    wake = ("⟦pulse o:o_fixture a:1⟧ [HeartBeat 2.0 · wake w_fixture · fixture · armed by the owner 1m ago]\n"
            "Load personal-assistant:cos-daily")
    assert "cancel this wake" in hooks["pre_llm_call"](user_message=wake)["context"]
    commands["pa"]("mode chief-of-staff on")
    assert hooks["pre_llm_call"](user_message="Hello again", platform="telegram") is None


@pytest.mark.parametrize("kind", COS)
@pytest.mark.parametrize("timezone", ["UTC", None])
def test_cos_precheck_uses_rule_timezone_or_preference(tmp_path, kind, timezone):
    ledger = ledger_at(tmp_path, kind)
    rule(ledger, kind, timezone=timezone)
    zone = timezone or "Asia/Tokyo"
    now = dt.datetime.fromisoformat("2026-10-19T10:00:00" + ("+00:00" if timezone else "+09:00"))
    before = now.replace(hour=9, minute=29 if kind == "cos_daily" else 59)
    assert cron_precheck(ledger, kind, enabled=True, moment=before) == {
        "wakeAgent": False, "reason": "before_cos_time"}
    assert prepare_suggestions(ledger)["jobs"][0]["timezone"] == zone
    # Tokyo is already in quiet hours and on the next date; UTC is still Monday afternoon.
    if timezone:
        now = now.replace(hour=15)
    result = cron_precheck(ledger, kind, enabled=True, moment=now)
    logical = "2026-10-19" if kind == "cos_daily" else "2026-W43"
    assert result["wakeAgent"]
    assert result["occurrence_id"] == auto.notification_occurrence_id(kind, logical)


@pytest.mark.parametrize("kind", COS)
def test_paused_cos_rules_require_reacceptance_for_suggestions(tmp_path, monkeypatch, kind):
    ledger = ledger_at(tmp_path, kind)
    for other in ("daily_brief", "due_source_check"):
        rule(ledger, other, paused=True)
    native(monkeypatch, tmp_path)
    settings = {"modes": {"chief_of_staff": True}}
    command = make_pa_command(tmp_path, settings.get, lambda k, v: settings.update({k: v}))
    assert kind in {j["kind"] for j in prepare_suggestions(ledger)["jobs"]}
    command("mode chief-of-staff off")
    command("mode chief-of-staff on")
    remaining = {"daily_brief", "due_source_check"}
    assert {j["kind"] for j in prepare_suggestions(ledger)["jobs"]} == remaining
    rule(ledger, kind, paused=False)
    assert {j["kind"] for j in prepare_suggestions(ledger)["jobs"]} == remaining | {kind}
