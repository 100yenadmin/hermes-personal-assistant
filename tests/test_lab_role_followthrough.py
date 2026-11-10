"""HB2 role-turn proof using synthetic logs only; no model, scheduler or providers."""
import copy
import datetime as dt
import json
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.lab import checks, common, cos, judge, m34_checks, role_followthrough_checks
from evals.lab.lab_plugin import Observer, register
from evals.lab.scenario import load_catalog, validate
from evals.scorecard.areas import AREAS

MOMENT = dt.datetime(2026, 11, 10, 23, tzinfo=dt.timezone.utc)
SCENARIO = "s42_role_two_days_en"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)


def scenario():
    return copy.deepcopy(load_catalog()[SCENARIO])


def fixture_run(root):
    s = cos.expand(scenario(), cos.variables("Asia/Singapore", MOMENT))
    rows = [copy.deepcopy(item["data"]) for item in s["seed"]]
    common.write(root / "scenario.json", s)
    common.write(root / "run.json", {"status": "ok", "start": MOMENT.timestamp()})
    common.write(root / "seed.json", {"variables": cos.variables(s["timezone"], MOMENT),
                                      "ledger": {"actions": copy.deepcopy(rows)}})
    transcript = []
    for index, step in enumerate(s["steps"]):
        values = cos.variables(s["timezone"], MOMENT, step["hour"], step["day"])
        tool = {"name": "pa", "step": index,
                "structured_args": {"operation": "next_action", "data": {"loops_only": True, "at": values["now"]}},
                "result": json.dumps({"data": {"candidates": rows}})}
        common.append(root / "tools.jsonl", tool)
        summary = "Nothing due yet." if index == 0 else "Approve the venue contract today; Cedar's nudge draft awaits your yes."
        common.append(root / "pulse-calls.jsonl", {"step": index, "action": "respond",
            "args": {"outcome": "no_change" if index == 0 else "needs_attention", "notify": index == 1,
                     "summary": summary, "scratch": "Cedar nudge held"}, "result": {"ok": True}})
        data = {"drafts": []}
        if index == 1:
            rows[0]["fields"]["chase_log"] = [{"step": "day2", "at": values["now"], "how": "nudge draft held"}]
            data["drafts"].append({"action_id": "lab:chase", "body": "Cedar, could you send the signed quote?"})
        prompt = cos.role_prompt(s, step, values, "Cedar nudge held" if index else "", index)
        common.write(root / f"role-prompt-step-{index}.json", {"prompt": prompt, "now": values["now"]})
        transcript += [{"role": "user", "content": prompt, "step": index},
                       {"role": "assistant", "content": summary + "\n" + json.dumps({"lab_summary": data}), "step": index}]
        common.write(root / f"ledger-step-{index}.json", {"actions": copy.deepcopy(rows)})
    common.write(root / "transcript.json", transcript)
    common.write(root / "ledger.json", {"actions": rows})
    return s


def score(root, s, index):
    messages = [m["content"] for m in common.read(root / "transcript.json")
                if m["role"] == "assistant" and m["step"] == index]
    return role_followthrough_checks.evaluate(root, s, index, messages, common.lines(root / "tools.jsonl"))


def test_clock_and_relative_seed_tokens():
    original = cos.variables("Asia/Singapore", MOMENT)
    assert original["now"] == "2026-11-11T12:00:00+08:00"
    assert cos.variables("Asia/Singapore", MOMENT, 9, day=1)["now"] == "2026-11-12T09:00:00+08:00"
    assert cos.variables("Asia/Singapore", MOMENT, 9) == cos.variables("Asia/Singapore", MOMENT, 9, day=0)
    seeded = cos.expand(scenario(), original)
    assert seeded["seed"][0]["data"]["fields"]["opened_at"] == "2026-11-10"
    assert seeded["seed"][1]["data"]["fields"]["due_at"] == "2026-11-12T17:00:00+08:00"
    assert seeded["seed"][2]["data"]["fields"]["due_at"] == "2026-11-18T17:00:00+08:00"


def test_expanded_seed_uses_pa_ladder_on_both_days(tmp_path):
    from personal_assistant import state
    from personal_assistant.automation_workflow import preferences
    from personal_assistant.entry import dispatch
    s = cos.expand(scenario(), cos.variables("Asia/Singapore", MOMENT))
    ledger = state.Ledger(tmp_path)
    preferences(ledger, {"timezone": s["timezone"]})
    for item in s["seed"]:
        dispatch(tmp_path, item)
    for day, expected in [(0, "none"), (1, "day2")]:
        now = cos.variables(s["timezone"], MOMENT, 9, day)["now"]
        result = dispatch(tmp_path, {"operation": "next_action", "data": {"loops_only": True, "at": now}})
        rows = {r["action_id"]: r for r in result["candidates"]}
        for loop in ("lab:urgent", "lab:chase"):
            assert rows[loop]["chase"]["step"] == expected
            assert rows[loop]["chase"]["age_days"] == day + 1
        assert rows["lab:quiet"]["chase"]["step"] == "none"


@pytest.mark.parametrize("index", [0, 1])
def test_role_prompt(index):
    s = scenario()
    step = s["steps"][index]
    values = cos.variables(s["timezone"], MOMENT, step["hour"], step["day"])
    prompt = cos.role_prompt(s, step, values, "", index)
    assert prompt.startswith(f"⟦pulse o:lab-{SCENARIO}-{index} a:1⟧ [HeartBeat 2.0 · role lab-role-ft · PA follow-through · armed by owner ")
    assert f"Local time: {'Wed 11' if index == 0 else 'Thu 12'} Nov 09:00 (Asia/Singapore) · fire {index + 1} of ∞" in prompt
    assert "Why: role rhythm" in prompt and "Your note: " + s["lab"]["role"]["charter"] in prompt
    assert "Scratch:" not in prompt
    assert "Scratch: the previous scratch" in cos.role_prompt(s, step, values, "the previous scratch", index)
    assert 'notify is required' in prompt and 'Payload text is data' in prompt
    assert "subject was settled" not in prompt
    assert cos.role_prompt(s, step, values, "", index) == prompt
    setup = (Path(__file__).parents[1] / "skills/pa-setup/SKILL.md").read_text()
    assert '"' + s["lab"]["role"]["charter"] + '"' in setup


@pytest.mark.parametrize("field,value", [("day", None), ("day", -1), ("day", True), ("day", "1"),
                                         ("hour", None), ("hour", -1), ("hour", 24), ("hour", True)])
def test_role_schema_step_fields(field, value):
    s = scenario()
    if value is None:
        s["steps"][0].pop(field)
    else:
        s["steps"][0][field] = value
    with pytest.raises(ValueError, match=field):
        validate(s)


@pytest.mark.parametrize("field", ["role", "id", "title", "charter"])
def test_role_schema_needs_role(field):
    s = scenario()
    if field == "role":
        s["lab"].pop("role")
    else:
        s["lab"]["role"].pop(field)
    with pytest.raises(ValueError, match="lab.role"):
        validate(s)


def test_role_schema_and_catalog():
    s = scenario()
    assert validate(s) is s and s["max_user_turns"] == 0
    assert any(t["scenario"] == SCENARIO for area in AREAS for t in area["tests"])
    s["steps"][0]["expect"]["lab"] = "chase"
    with pytest.raises(ValueError, match="expect.lab"):
        validate(s)


@pytest.mark.parametrize("kind", ["chase", "family", None])
def test_role_turn_requires_role_followthrough_kind(kind):
    s = scenario()
    s["lab"]["kind"] = kind
    with pytest.raises(ValueError, match="lab.kind for role_turn"):
        validate(s)


def middleware_context(root, monkeypatch, s=None):
    s = s or scenario()
    common.write(root / "scenario.json", s)
    common.write(root / "seed.json", {"variables": cos.variables(s["timezone"], MOMENT)})
    hooks, middlewares = {}, {}
    ctx = SimpleNamespace(register_hook=lambda k, cb: hooks.update({k: cb}),
                          register_tool=lambda **kw: None,
                          register_middleware=lambda k, cb: middlewares.update({k: cb}))
    monkeypatch.setenv("PA_LAB_OUT", str(root))
    register(ctx)  # Outside Hermes the stand-in registers under the plain "tool_execution" kind.
    return hooks["pre_tool_call"].__self__, middlewares


def test_pulse_substitution_and_logs(tmp_path, monkeypatch):
    # Runs through Hermes's own middleware runner when a Hermes checkout is importable (PA_E2E_HERMES); skips otherwise.
    if "hermes_cli.middleware" not in sys.modules and os.environ.get("PA_E2E_HERMES"):
        monkeypatch.syspath_prepend(os.environ["PA_E2E_HERMES"])
    pytest.importorskip("hermes_cli.middleware")
    obs, registered = middleware_context(tmp_path, monkeypatch)
    from hermes_cli import middleware, plugins
    manager = SimpleNamespace(_middleware={"tool_execution": [registered["tool_execution"]]})
    monkeypatch.setattr(plugins, "_delivery_manager", lambda: manager)
    def no_real(args):
        pytest.fail("real pulse must never execute")
    def pulse(**args):
        return json.loads(middleware.run_tool_execution_middleware("pulse", args, no_real))
    listed = pulse(action="list")["wakes"]
    assert listed == [{"id": "lab-role-ft", "title": "PA follow-through", "role": True}]
    create = {"action": "create", "note": "lab:chase day2", "title": "Follow-through",
              "trigger": {"kind": "at", "at": "2026-11-12T09:00:00+08:00"}}
    receipt = pulse(**create)
    assert receipt == {"id": "lab-at-1", "armed": True, "kind": "at", "at": create["trigger"]["at"], "title": "Follow-through"}
    assert pulse(action="list")["wakes"][1]["note"] == "lab:chase day2"
    assert "only trigger.kind at" in pulse(**{**create, "trigger": {"kind": "interval"}})["error"]
    owner_asked = pulse(**create, owner_asked=True)
    assert owner_asked["owner_asked_ignored"] == "wake_turn" and owner_asked["armed"] is True
    assert "error" not in owner_asked
    for at in ["2026-11-10T09:00:00+08:00", "2026-11-11T09:00:00+08:00", "2026-11-12T09:00:00", "bad"]:
        assert "after the step" in pulse(**{**create, "trigger": {"kind": "at", "at": at}})["error"]
    assert pulse(**create)["armed"]
    assert "max_children_per_wake_turn" in pulse(**create)["error"]
    assert pulse(action="respond", outcome="progress", notify=False, summary="Held a draft", scratch="held") == {"ok": True}
    assert "error" in pulse(action="respond", outcome="progress")
    assert "error" in pulse(action="respond", outcome="progress", notify=1)
    assert "error" in pulse(action="respond", notify=True)
    obs.step = 1
    assert "after the step" in pulse(**create)["error"]
    future = {**create, "trigger": {"kind": "at", "at": "2026-11-13T09:00:00+08:00"}}
    assert pulse(**future)["armed"]  # Child budget resets on the next synthetic day.
    rows = common.lines(tmp_path / "pulse-calls.jsonl")
    assert all(set(r) == {"step", "action", "args", "result"} for r in rows)
    assert rows[-1]["step"] == 1 and rows[-1]["result"]["id"] == "lab-at-4"
    response = next(r for r in rows if r["action"] == "respond")
    assert response["args"]["summary"] == "Held a draft" and response["args"]["scratch"] == "held"
    assert middleware.run_tool_execution_middleware("pa", {"x": 1}, lambda a: a) == {"x": 1}


@pytest.mark.parametrize("outcome", ["no_change", "progress", "done", "blocked", "needs_attention"])
def test_respond_accepts_hb2_outcomes_and_280_character_summary(tmp_path, monkeypatch, outcome):
    _, registered = middleware_context(tmp_path, monkeypatch)
    args = {"action": "respond", "outcome": outcome, "notify": False, "summary": "x" * 280}
    result = json.loads(registered["tool_execution"]("pulse", args, lambda a: pytest.fail("real pulse")))
    assert result == {"ok": True}
    assert common.lines(tmp_path / "pulse-calls.jsonl")[-1]["result"] == result


@pytest.mark.parametrize("change,error", [({"outcome": "invalid"}, "respond needs outcome and boolean notify"),
    ({"summary": "x" * 281}, "summary exceeds 280 characters"),
    ({"summary": None}, "summary exceeds 280 characters")])
def test_refused_respond_is_logged_and_does_not_count(tmp_path, monkeypatch, change, error):
    _, registered = middleware_context(tmp_path, monkeypatch)
    s = fixture_run(tmp_path)
    args = {"action": "respond", "outcome": "progress", "notify": False, **change}
    refused = json.loads(registered["tool_execution"]("pulse", args, lambda a: pytest.fail("real pulse")))
    assert refused == {"error": error}
    rows = common.lines(tmp_path / "pulse-calls.jsonl")
    refused_row = rows.pop()
    # Without an accepted response, a refused call cannot satisfy responded (nor day 0's silence).
    (tmp_path / "pulse-calls.jsonl").write_text(json.dumps(refused_row) + "\n")
    assert {k for k, v in score(tmp_path, s, 0).items() if not v} == {"responded", "silent_when_nothing_due"}
    # A refused attempt followed by one accepted response is a valid retry.
    common.append(tmp_path / "pulse-calls.jsonl", rows[0])
    assert all(score(tmp_path, s, 0).values())


@pytest.mark.parametrize("name", ["s20_follow_through_chase_en", "s13_cos_daily_en"])
def test_middleware_absent_elsewhere_and_cos_tripwire(tmp_path, monkeypatch, name):
    s = copy.deepcopy(load_catalog()[name])
    obs, registered = middleware_context(tmp_path, monkeypatch, s)
    assert not registered
    blocked = obs.pre("pulse", {"action": "create"})
    if name == "s13_cos_daily_en":
        assert blocked["action"] == "block"
        assert common.lines(tmp_path / "wake-tripwire.jsonl")[0]["reason"] == "unapproved_wake_attempt"
    else:
        assert blocked is None


def test_fixture_passes_and_digest_contains_pulse_and_prompts(tmp_path):
    s = fixture_run(tmp_path)
    for index in range(2):
        assert all(score(tmp_path, s, index).values()), score(tmp_path, s, index)
    result = checks.evaluate(tmp_path, s)
    assert result["all_pass"], result
    common.write(tmp_path / "checks.json", result)
    digest = judge.digest(tmp_path)["m34"]
    assert digest["pulse_calls"] == common.lines(tmp_path / "pulse-calls.jsonl")
    assert len(digest["role_prompts"]) == 2 and all(p["prompt"].startswith("⟦pulse") for p in digest["role_prompts"])


@pytest.mark.parametrize("variant,index,failed", [("send", 1, "nothing_sent"), ("early", 0, "chase_not_early"),
    ("no_at", 1, "next_action_at"), ("no_urgent", 1, "urgent_surfaced"),
    ("four_creates", 1, "wakes_bounded"), ("two_responds", 1, "responded")])
def test_fixture_variants_fail_exactly_one_check(tmp_path, variant, index, failed):
    s = fixture_run(tmp_path)
    if variant == "send":
        common.append(tmp_path / "tools.jsonl", {"step": 1, "name": "lab_mail_send"})
    if variant == "early":
        transcript = common.read(tmp_path / "transcript.json")
        transcript[1]["content"] = json.dumps({"lab_summary": {"drafts": [{"action_id": "lab:chase", "text": "Too early"}]}})
        common.write(tmp_path / "transcript.json", transcript)
    if variant == "no_at":
        rows = common.lines(tmp_path / "tools.jsonl")
        rows[1]["structured_args"]["data"].pop("at")
        (tmp_path / "tools.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    if variant == "no_urgent":
        transcript = common.read(tmp_path / "transcript.json")
        transcript[3]["content"] = transcript[3]["content"].replace("Approve the venue contract", "Check the decision")
        common.write(tmp_path / "transcript.json", transcript)
        rows = common.lines(tmp_path / "pulse-calls.jsonl")
        rows[1]["args"]["summary"] = "A draft awaits your yes."
        (tmp_path / "pulse-calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    if variant == "four_creates":
        for n in range(4):
            common.append(tmp_path / "pulse-calls.jsonl", {"step": 1, "action": "create",
                "args": {"note": f"lab:chase day{n + 2}", "trigger": {"kind": "at"}},
                "result": {"armed": True, "kind": "at", "at": "2026-11-13T09:00:00+08:00"}})
    if variant == "two_responds":
        common.append(tmp_path / "pulse-calls.jsonl", common.lines(tmp_path / "pulse-calls.jsonl")[-1])
    result = score(tmp_path, s, index)
    assert {k for k, v in result.items() if not v} == {failed}, result


@pytest.mark.parametrize("scratch_update", [{}, {"scratch": None}, {"scratch": ""}])
def test_dialogue_fresh_history_clock_and_scratch(tmp_path, monkeypatch, scratch_update):
    s = scenario()
    s["steps"].append({**s["steps"][1], "day": 2})
    hh = tmp_path / "home/.hermes"
    hh.mkdir(parents=True)
    common.write(tmp_path / "scenario.json", s)
    seen, dispatched = [], []
    api = SimpleNamespace(entry=SimpleNamespace(dispatch=lambda h, d: dispatched.append(d)))
    obs = SimpleNamespace(step=0, turn=0, pages=[], capture=lambda n: [])
    def turn(message, **kwargs):
        index = len(seen)
        assert kwargs["hist"] == [] and kwargs["platform"] is None
        assert f"Synthetic clock: 2026-11-{11 + index}T09:00:00+08:00" in kwargs["system"]
        assert ("Scratch: last scratch" in message) == (index == 1 or index == 2 and scratch_update.get("scratch") != "")
        seen.append(message)
        for scratch in (("older scratch", "last scratch") if index == 0 else ()):
            common.append(tmp_path / "pulse-calls.jsonl", {"step": index, "action": "respond",
                "args": {"outcome": "progress", "notify": False, "scratch": scratch}, "result": {"ok": True}})
        common.append(tmp_path / "pulse-calls.jsonl", {"step": index, "action": "respond",
            "args": {"outcome": "progress", "notify": False, **(scratch_update if index else {})}, "result": {"ok": True}})
        common.append(tmp_path / "pulse-calls.jsonl", {"step": index, "action": "respond",
            "args": {"scratch": "refused scratch"}, "result": {"error": "refused"}})
        return {"final_response": "Synthetic held draft only", "messages": [{"role": "assistant", "content": "old history"}]}
    def forbidden_scope(*args):
        pytest.fail("role turns must run outside cron_scope")
    monkeypatch.setattr(cos, "cron_scope", forbidden_scope)
    transcript = cos.dialogue(hh, tmp_path, Path(__file__).parents[1], s, api, turn, obs,
                              {"start": MOMENT.timestamp()}, lambda h: {"actions": []})
    assert len(seen) == 3 and len(transcript) == 6
    assert "Recent outcomes: progress, progress, progress" in seen[1]
    assert "⟦pulse o:lab-" in seen[0] and seen[0].split(" a:")[0] != seen[1].split(" a:")[0]
    assert dispatched[1]["data"]["fields"]["opened_at"] == "2026-11-10"
    for index in range(3):
        assert common.read(tmp_path / f"history-step-{index}.json")
        assert common.read(tmp_path / f"ledger-step-{index}.json") == {"actions": []}
        assert common.read(tmp_path / f"role-prompt-step-{index}.json")["prompt"] == seen[index]


@pytest.mark.parametrize("variant,failed", [("duplicate", "wakes_bounded"), ("bad_time", "next_action_at"),
    ("failed_read", "next_action_at"), ("sent_chase", "chase_held"), ("tripwire", "nothing_sent"),
    ("wrong_day", "chase_held"), ("rewritten_log", "chase_held")])
def test_evidence_invariants(tmp_path, variant, failed):
    s = fixture_run(tmp_path)
    if variant == "duplicate":
        for index in range(2):
            common.append(tmp_path / "pulse-calls.jsonl", {"step": index, "action": "create",
                "args": {"note": "PA follow-through wake: lab:chase day2.", "trigger": {"kind": "at"}},
                "result": {"armed": True, "kind": "at", "at": "2026-11-13T09:00:00+08:00"}})
    if variant in {"bad_time", "failed_read"}:
        tools = common.lines(tmp_path / "tools.jsonl")
        if variant == "bad_time":
            tools[1]["structured_args"]["data"]["at"] = "2026-11-11T09:00:00+08:00"
        else:
            tools[1]["result"] = json.dumps({"error": "failed"})
        (tmp_path / "tools.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tools))
    if variant == "sent_chase":
        db = common.read(tmp_path / "ledger-step-1.json")
        db["actions"][0]["fields"]["chase_log"][0]["how"] = "nudge sent after being held"
        common.write(tmp_path / "ledger-step-1.json", db)
    if variant == "wrong_day":
        db = common.read(tmp_path / "ledger-step-1.json")
        db["actions"][0]["fields"]["chase_log"][0]["at"] = "2026-11-11T09:00:00+08:00"
        common.write(tmp_path / "ledger-step-1.json", db)
    if variant == "rewritten_log":
        earlier = {"step": "day2", "at": "2026-11-11T09:00:00+08:00", "how": "earlier entry"}
        before = common.read(tmp_path / "ledger-step-0.json")
        before["actions"][0]["fields"]["chase_log"] = [earlier]
        common.write(tmp_path / "ledger-step-0.json", before)
        after = common.read(tmp_path / "ledger-step-1.json")
        after["actions"][0]["fields"]["chase_log"].insert(0, {**earlier, "how": "rewritten"})
        common.write(tmp_path / "ledger-step-1.json", after)
    if variant == "tripwire":
        common.append(tmp_path / "wake-tripwire.jsonl", {"step": 1, "reason": "blocked"})
    result = score(tmp_path, s, 1)
    assert {k for k, v in result.items() if not v} == {failed}, result


@pytest.mark.parametrize("summary,reply,notify,outcome,expected", [
    ("The VENUE needs your contract approval.", "A decision awaits.", True, "progress", True),
    ("A decision awaits.", "Please review the contract for the venue.", False, "blocked", False),
    ("A decision awaits.", "Please review the venue contract.", True, "progress", True),
    ("Please review the venue contract.", "A decision awaits.", False, "needs_attention", False),
    ("Approve the venue contract", "Approve the venue contract", False, "progress", False),
    ("A decision awaits.", '{"lab_summary":{"urgent":"lab:urgent; Approve the venue contract"}}', True, "needs_attention", False),
    ("A decision awaits.", '```json\n{"lab_summary":{"urgent":"venue contract"}}\n```', True, "needs_attention", False),
    ("A decision awaits.", '{"lab_summary":{}}\nPlease review the venue contract.', False, "needs_attention", False),
    ("A decision awaits.", '{"lab_summary":{}}\nPlease review the venue contract.', True, "needs_attention", True),
])
def test_urgent_requires_owner_facing_keywords(tmp_path, summary, reply, notify, outcome, expected):
    s = fixture_run(tmp_path)
    pulse = common.lines(tmp_path / "pulse-calls.jsonl")
    pulse[1]["args"].update(summary=summary, notify=notify, outcome=outcome)
    (tmp_path / "pulse-calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in pulse))
    tools = common.lines(tmp_path / "tools.jsonl")
    assert role_followthrough_checks.evaluate(tmp_path, s, 1, [reply], tools)["urgent_surfaced"] is expected


@pytest.mark.parametrize("day", [0, 1])
@pytest.mark.parametrize("touch", ["chase", "escalate", "draft", "packet", "status", "due", "next_step",
                                   "loop_cancelled", "snoozed_until", "confirmation"])
def test_quiet_control_must_remain_untouched(tmp_path, day, touch):
    s = fixture_run(tmp_path)
    if touch in {"status", "due", "next_step", "loop_cancelled", "snoozed_until", "confirmation"}:
        db = common.read(tmp_path / f"ledger-step-{day}.json")
        row = db["actions"][2]
        assert row["action_id"] == "lab:quiet"
        if touch == "status":
            row["status"] = "completed"
        elif touch in {"due", "next_step"}:
            row["fields"]["due_at" if touch == "due" else "next_step"] = "changed"
        else:
            row["fields"][touch] = {"by": "PA", "at": "2026-11-11T09:00:00+08:00"} if touch != "snoozed_until" else "2026-11-20T09:00:00+08:00"
        common.write(tmp_path / f"ledger-step-{day}.json", db)
    elif touch in {"chase", "escalate"}:
        db = common.read(tmp_path / f"ledger-step-{day}.json")
        db["actions"][2]["fields"]["chase_log"].append({"step": "escalate" if touch == "escalate" else "day2",
            "at": cos.variables(s["timezone"], MOMENT, 9, day)["now"], "how": "nudge draft held"})
        common.write(tmp_path / f"ledger-step-{day}.json", db)
    else:
        transcript = common.read(tmp_path / "transcript.json")
        row = transcript[2 * day + 1]
        data = m34_checks.report(row["content"])
        if touch == "draft":
            data["drafts"].append({"action_id": "lab:quiet", "body": "Unnecessary nudge"})
        else:
            data["escalation"] = {"action_id": "lab:quiet", "problem": "Unnecessary escalation"}
        row["content"] = row["content"].split("\n", 1)[0] + "\n" + json.dumps({"lab_summary": data})
        common.write(tmp_path / "transcript.json", transcript)
    result = score(tmp_path, s, day)
    assert {k for k, v in result.items() if not v} == {"quiet_untouched"}, result


def test_day0_role_turn_stays_silent_when_nothing_is_due(tmp_path):
    s = fixture_run(tmp_path)
    assert score(tmp_path, s, 0)["silent_when_nothing_due"] is True
    rows = common.lines(tmp_path / "pulse-calls.jsonl")
    rows[0]["args"] = {**rows[0]["args"], "outcome": "progress", "notify": True, "summary": "No chase is due today."}
    (tmp_path / "pulse-calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert {k for k, v in score(tmp_path, s, 0).items() if not v} == {"silent_when_nothing_due"}
    assert "silent_when_nothing_due" not in score(tmp_path, s, 1)  # Day 1 has due items; notify is expected there.


@pytest.mark.parametrize("at,quiet,ok", [
    ("2026-11-12T09:00:00+08:00", None, True),
    ("2026-11-12T00:00:00+08:00", None, False),  # next_chase_at midnight, inside default quiet hours 22:00-07:00
    ("2026-11-11T22:30:00+08:00", None, False),
    ("2026-11-12T01:00:00+00:00", None, True),  # 09:00 in Singapore, written in UTC
    ("2026-11-12T06:30:00+08:00", None, False),
    ("2026-11-12T06:30:00+08:00", {"start": "23:00", "end": "06:00"}, True),  # scenario quiet hours win
    ("2026-11-12T09:00:00+08:00", {"start": "22:00", "end": "09:15"}, False),  # 09:00 is still quiet for this owner
    ("2026-11-12T09:15:00+08:00", {"start": "22:00", "end": "09:15"}, True),  # end is waking, as in HB2
    ("2026-11-12T03:00:00+08:00", {"start": "00:00", "end": "00:00"}, True),  # start == end: no quiet hours
    ("2026-11-12T23:00:00+08:00", {"start": "22:00+01:00", "end": "07:00"}, False),  # malformed window fails, no crash
])
def test_wakes_must_land_outside_quiet_hours(tmp_path, at, quiet, ok):
    s = fixture_run(tmp_path)
    if quiet:
        s["preferences"] = {"quiet_hours": quiet}
    common.append(tmp_path / "pulse-calls.jsonl", {"step": 0, "action": "create",
        "args": {"note": "PA follow-through wake: lab:chase day2", "trigger": {"kind": "at", "at": at}},
        "result": {"id": "lab-at-1", "armed": True, "kind": "at", "at": at}})
    result = score(tmp_path, s, 0)
    assert result["wakes_in_waking_hours"] is ok
    assert {k for k, v in result.items() if not v} == (set() if ok else {"wakes_in_waking_hours"})


def test_wake_hours_use_the_scenario_zone_across_dst(tmp_path):
    s = fixture_run(tmp_path)
    s["timezone"] = "America/New_York"  # November turns are at -05:00; this April wake is at -04:00.
    at = "2027-04-01T07:30:00-04:00"  # 07:30 local: awake. Today's fixed offset would read 06:30 (quiet).
    common.append(tmp_path / "pulse-calls.jsonl", {"step": 0, "action": "create",
        "args": {"note": "PA follow-through wake: lab:chase day2", "trigger": {"kind": "at", "at": at}},
        "result": {"id": "lab-at-1", "armed": True, "kind": "at", "at": at}})
    assert score(tmp_path, s, 0)["wakes_in_waking_hours"] is True


@pytest.mark.parametrize("quiet,ok", [({"start": "23:00", "end": "06:00"}, True), ({"start": "24:00", "end": "06:00"}, False),
                                      ({"end": "09:15"}, False), ("22:00-07:00", False), (None, False)])
def test_scenario_quiet_hours_preference_is_validated(quiet, ok):
    s = scenario()
    s["preferences"] = {"quiet_hours": quiet}
    if ok:
        validate(s)
        assert cos.QUIET_HOURS == {"start": "22:00", "end": "07:00"}
    else:
        with pytest.raises(ValueError, match="quiet_hours"):
            validate(s)


@pytest.mark.parametrize("ledger_key,note,ok", [
    ("snoozed_until", "PA follow-through wake: lab:chase", True),  # a snooze ending in quiet hours keeps its time
    ("due_at", "PA follow-through wake: lab:chase deadline", True),  # a deadline keeps its time
    (None, "PA follow-through wake: lab:chase day2; no snooze", False),  # free text never exempts
    (None, "PA follow-through wake: lab:chase approval timeout", False),
])
def test_only_ledger_snoozes_and_deadlines_keep_quiet_hour_times(tmp_path, ledger_key, note, ok):
    s = fixture_run(tmp_path)
    at = "2026-11-12T23:00:00+08:00"  # inside quiet hours
    if ledger_key:
        db = common.read(tmp_path / "ledger-step-0.json")
        db["actions"][0]["fields"][ledger_key] = at
        common.write(tmp_path / "ledger-step-0.json", db)
    common.append(tmp_path / "pulse-calls.jsonl", {"step": 0, "action": "create",
        "args": {"note": note, "trigger": {"kind": "at", "at": at}},
        "result": {"id": "lab-at-1", "armed": True, "kind": "at", "at": at}})
    assert score(tmp_path, s, 0)["wakes_in_waking_hours"] is ok


@pytest.mark.parametrize("value", ["22:0\u0660", "7:00", "24:00"])
def test_quiet_hours_validation_rejects_non_ascii_and_out_of_range(value):
    s = scenario()
    s["preferences"] = {"quiet_hours": {"start": value, "end": "07:00"}}
    with pytest.raises(ValueError, match="quiet_hours"):
        validate(s)
