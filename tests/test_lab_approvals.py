"""Approval-day oracle fixtures only; never invoke a model or provider."""
import copy
import json
import socket

import pytest

from evals.lab import booking_checks as b, checks, common, cos, judge, runner
from evals.lab.lab_plugin import Observer, register_standins
from evals.lab.scenario import load_catalog, validate
from test_lab_booking import MOMENT, pa, save as save_booking, synthetic as booking_run, tool


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


def scenario():
    return cos.expand(copy.deepcopy(load_catalog()["s37_approval_day_en"]), cos.variables("Asia/Tokyo", MOMENT))


def synthetic():
    _, tools, transcript, receipts = booking_run()
    # Reuse the unchanged s27 fixture with s37's synthetic owner and offer names.
    tools, transcript, receipts = json.loads(json.dumps([tools, transcript, receipts])
        .replace("Morgan Demo", "Riley Demo").replace("Kitsune", "Maple").replace("kitsune", "maple"))
    s = scenario()
    summary = b.report(transcript[1]["content"])
    summary["decisions"] = [{**seed, "problem": "A synthetic decision needs your answer.",
        "options": ["Accept", "Decline"], "recommendation": "accept", "decide_by": seed["due"],
        "draft": "Thank you; we accept the proposed option."} for seed in s["lab"]["decisions"]]
    summary["approval_packet"].update(decide_by=s["lab"]["offers"][0]["cancellation_deadline"][:10], recommendation="Choose the 19:30 table.")
    transcript[1]["content"] = "Ready; waiting for your yes.\n" + json.dumps({"lab_summary": summary})
    transcript += [{"role": "user", "step": 2, "content": s["steps"][2]["scripted_yes"]["text"]},
        {"role": "assistant", "step": 2, "content": 'Already booked: LAB-1. Nothing new was done.\n'
         + json.dumps({"lab_summary": {"booking_reference": "LAB-1", "new_actions": 0}})}]
    tools.append(pa("action_get", {"action_id": "booking-1"}, {"status": "confirmed", "reference": "LAB-1"}, 2))
    ledger = {"pa_action_authorizations": [{"action_id": "authorization-1", "pa_action_id": "booking-1",
        "status": "claimed", "tool_name": "lab_booking_submit", "session_id": "session-1",
        "envelope_json": json.dumps({"reliability_profile": "exact", "pa_action_id": "booking-1",
            "authority": {"rebound_from": {"session_id": "session-0", "task_id": "task", "at": "2026-11-09T03:00:00Z"}}})}]}
    meta = {"status": "ok", "sessions": {str(i): f"session-{i}" for i in range(3)}}
    return s, tools, transcript, receipts, ledger, meta


def save(root, data):
    s, tools, transcript, receipts, ledger, meta = data
    save_booking(root, s, tools, transcript, receipts)
    common.write(root / "ledger.json", ledger)
    common.write(root / "run.json", meta)
    return checks.evaluate(root, s)


@pytest.mark.parametrize("reference_in_prose", [True, False])
def test_synthetic_approval_day_passes(tmp_path, reference_in_prose):
    data = synthetic()
    if not reference_in_prose:
        data[2][-1]["content"] = data[2][-1]["content"].replace("Already booked: LAB-1.", "Already booked.")
    result = save(tmp_path, data)
    assert result["all_pass"], result
    assert judge.digest(tmp_path)["m34"]["booking_calls"] == data[3]
    assert "lab_booking_*" in runner.system_prompt(data[0])
    for index in range(3):
        missing = copy.deepcopy(data)
        missing[2][:] = [m for m in missing[2] if m.get("step") != index]
        assert not save(tmp_path, missing)["steps"][index]["pass"]


@pytest.mark.parametrize("failure,step,key", [
    ("draft", 0, "decisions_finished"), ("recommendation", 0, "decisions_finished"),
    ("late", 0, "decisions_finished"), ("packet", 0, "packet_finished"),
    ("same_session", 1, "new_session"), ("rebound", 1, "rebound"),
    ("confirm", 2, "no_double"), ("prepare", 2, "no_double"),
    ("refused_submit", 2, "no_double"), ("reference", 2, "reported_existing"),
    ("step2_session", 2, "new_session"), ("step0_write", 0, "nothing_sent")])
def test_each_new_check_fails_in_isolation(tmp_path, failure, step, key):
    data = synthetic()
    s, tools, transcript, receipts, ledger, meta = data
    summary = b.report(transcript[1]["content"])
    if failure == "draft":
        summary["decisions"][0].pop("draft")
    elif failure == "recommendation":
        summary["decisions"][0]["recommendation"] = "Neither option"
    elif failure == "late":
        summary["decisions"][0]["decide_by"] = "2099-01-01"
    elif failure == "packet":
        summary["approval_packet"].pop("decide_by")
    elif failure == "same_session":
        meta["sessions"]["1"] = meta["sessions"]["0"]
    elif failure == "step2_session":
        meta["sessions"]["2"] = meta["sessions"]["0"]
    elif failure == "rebound":
        ledger["pa_action_authorizations"][0]["envelope_json"] = json.dumps({"reliability_profile": "exact", "authority": {}})
    elif failure in {"confirm", "prepare"}:
        tools.append(pa("action_" + failure, {"action_id": "booking-1"}, {"error": "already claimed"}, 2))
    elif failure == "refused_submit":
        tools.append(tool("lab_booking_submit", receipts[0]["args"], {"error": "duplicate"}, 2))
        receipts.append({**receipts[0], "step": 2, "accepted": False, "result": {"error": "duplicate"}})
    elif failure == "reference":
        transcript[-1]["content"] = 'Already booked; nothing new was done. {"lab_summary":{"new_actions":0}}'
    elif failure == "step0_write":
        common.append(tmp_path / "calendar-writes.jsonl", {"name": "lab_calendar_create", "step": 0, "args": {}, "accepted": True})
    transcript[1]["content"] = "Ready; waiting for your yes.\n" + json.dumps({"lab_summary": summary})
    result = save(tmp_path, data)
    failed = [(i, k) for i, row in enumerate(result["steps"]) for k, ok in row["checks"].items() if not ok]
    assert failed == [(step, key)], result


@pytest.mark.parametrize("step,kind,value", [(0, "approvals", True), (1, "chase", True), (1, "approvals", "true")])
def test_new_session_schema_rejections(step, kind, value):
    s = scenario()
    s["lab"]["kind"] = kind
    for entry in s["steps"]:
        entry["expect"]["lab"] = kind
        entry.pop("new_session", None)
    s["steps"][step]["new_session"] = value
    with pytest.raises(ValueError, match="new_session"):
        validate(s)


def test_decisions_hidden_and_seeded_only_in_ledger(tmp_path):
    from types import SimpleNamespace
    from personal_assistant.entry import dispatch
    s = scenario()
    s["lab"]["decisions"][0]["oracle_only"] = "NEVER_EXPOSE_THIS_ORACLE"
    common.write(tmp_path / "scenario.json", s)
    hh = tmp_path / "home/.hermes"
    hh.mkdir(parents=True)
    cos.seed(hh, s, dispatch, MOMENT)
    rows = runner.ledger(hh)["actions"]
    for decision in s["lab"]["decisions"]:
        row = next(r for r in rows if r["action_id"] == decision["action_id"])
        fields = json.loads(row["fields_json"])
        assert row["status"] == "open" and fields["loop_kind"] == "ask_owner"
        assert fields["question"] and len(fields["options"]) >= 2
    registered = {}
    register_standins(SimpleNamespace(register_tool=lambda **kw: registered.update({kw["name"]: kw["handler"]})), Observer(tmp_path))
    exposed = registered["lab_booking_offers"]({})
    assert "NEVER_EXPOSE_THIS_ORACLE" not in exposed + runner.system_prompt(s) + json.dumps(rows)
    assert "lab:supplier-date" not in exposed + runner.system_prompt(s)
