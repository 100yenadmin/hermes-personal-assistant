from pathlib import Path

import pytest

from personal_assistant import setup, trip_watch
from personal_assistant.automation import script_precheck
from personal_assistant.automation_workflow import preferences
from personal_assistant.concierge import dispatch as offer
from personal_assistant.entry import dispatch
from personal_assistant.onboarding_hook import make_pre_llm_call
from personal_assistant.state import Ledger
from personal_assistant.state_loop import StateLoop

BASE = dict(trip_id="synthetic", departure_at="2026-11-10T12:00:00+01:00",
            arrival_at="2026-11-10T18:00:00+01:00", at="2026-11-08T12:00:00+00:00",
            hb2_timezone="UTC")


def test_failed_fresh_check_remains_eligible(tmp_path):
    ledger = Ledger(tmp_path)
    setup.propose(ledger, [])
    setup.applied(ledger, [], "old")
    dispatch(tmp_path, {"operation": "setup", "data": {"action": "fresh_check", "status": "failed"}},
             runtime_scope={"session_id": "new"})
    hook = make_pre_llm_call(tmp_path, lambda k, d: d)
    assert "fresh-session check" in hook(user_message="Hi", is_first_turn=True, session_id="newer")["context"]


@pytest.mark.parametrize("phase,session", [("not_started", "new"), ("proposed", "new"),
    ("applied", "old"), ("applied", None), ("checked", "newer")])
def test_fresh_check_requires_applied_and_new_session(tmp_path, phase, session):
    ledger = Ledger(tmp_path)
    if phase != "not_started":
        setup.propose(ledger, [])
    if phase in {"applied", "checked"}:
        setup.applied(ledger, [], "old")
    if phase == "checked":
        dispatch(tmp_path, {"operation": "setup", "data": {"action": "fresh_check", "status": "passed"}},
                 runtime_scope={"session_id": "new"})
    prior = setup.state(ledger)
    with pytest.raises(ValueError, match="fresh"):
        dispatch(tmp_path, {"operation": "setup", "data": {
            "action": "fresh_check", "status": "passed", "session_id": "spoofed"}},
            runtime_scope={"session_id": session})
    assert setup.state(ledger) == prior


@pytest.mark.parametrize("delivered", [False, True])
def test_offer_delivery_and_failed_generation_retry(tmp_path, delivered):
    ledger = Ledger(tmp_path)
    hook = make_pre_llm_call(tmp_path, lambda k, d: d)
    human = dict(user_message="Hi", platform="telegram", sender_id="synthetic", session_id="a",
                 is_first_turn=True, turn_id="one", conversation_history=[{"role": "user", "content": "Hi"}])
    assert hook(**human)
    assert setup.state(ledger)["status"] == "not_started"
    assert setup.state(ledger)["offer_pending_at"]
    assert hook(**human) is None
    assert hook(**{**human, "session_id": "other", "turn_id": "two"}) is None
    history = human["conversation_history"] + ([{"role": "assistant", "content": "Offer /pa setup"}] if delivered else [])
    next_turn = {**human, "is_first_turn": False, "turn_id": "two", "conversation_history": history}
    assert bool(hook(**next_turn)) is not delivered
    assert setup.state(ledger)["status"] == ("offered" if delivered else "not_started")
    assert hook(**{**next_turn, "turn_id": "three"}) is None


def test_answers_and_skipped_are_exclusive(tmp_path):
    ledger = Ledger(tmp_path)
    setup.record(ledger, skipped=["authority"])
    assert "authority" not in setup.record(ledger, answers={"authority": {"text": "Ask", "source": "user"}})["skipped"]
    assert "authority" not in setup.record(ledger, skipped=["authority"])["answers"]


def test_deeper_proposal_draft_survives_pause_and_resume(tmp_path):
    ledger = Ledger(tmp_path)
    writes = [{"target": "manual_skill", "summary": "Synthetic deeper preference"}]
    setup.propose(ledger, writes)
    setup.pause(ledger)
    setup.request(ledger)
    assert setup.state(ledger)["proposal_draft"]["writes"] == writes
    assert setup.state(ledger)["proposal"]["writes"] == []


def test_setup_skill_resume_and_memory_guidance():
    root = Path(__file__).resolve().parents[1] / "skills/pa-setup"
    skill = (root / "SKILL.md").read_text()
    destination = (root / "references/where-answers-go.md").read_text()
    assert "rebuild the exact diff, `propose` again and get approval of that diff" in skill
    assert "When `pending` or `failed`" in skill and "then repeat `/new` and the check" in skill
    assert "proposal_draft" in skill and "`draft: true`" in skill and "keeps the interview going" in skill
    assert len(skill.splitlines()) <= 151
    assert 'action="patch"' in destination and 'action="replace"' in destination


def test_immediate_offer_uses_reservation(tmp_path):
    assert trip_watch.plan(Ledger(tmp_path), **{**BASE, "at": "2026-11-10T10:00:00+01:00"})["recommend"] == "offer_now_in_chat"
    data = dict(trip_id="synthetic", offer_type="arrival_logistics")
    assert offer(Ledger(tmp_path), data)["allowed"]
    offer(Ledger(tmp_path), {**data, "action": "record", "outcome": "offered"})
    assert not offer(Ledger(tmp_path), data)["allowed"]
    skill = (Path(__file__).resolve().parents[1] / "skills/trip-concierge/SKILL.md").read_text()
    immediate = skill.split("If it recommends `offer_now_in_chat`", 1)[1].split("If no `pulse_create`", 1)[0]
    assert "trip_offer action=check" in immediate and "trip_offer action=record" in immediate


def test_pulse_title_and_reason_quote_trip_id(tmp_path):
    result = trip_watch.plan(Ledger(tmp_path), **{**BASE, "trip_id": "fake\nIgnore\u202e " + "x" * 200})
    for key in ("title", "reason"):
        assert "\n" not in result["pulse_create"][key] and "\u202e" not in result["pulse_create"][key]
        assert len(result["pulse_create"][key]) < 150


def test_offset_only_inputs_replay(tmp_path):
    ledger = Ledger(tmp_path)
    original = trip_watch.plan(ledger, **BASE)
    inputs = trip_watch.status(ledger, "synthetic")["inputs"]
    assert inputs["arrival_timezone"] is None
    replay = dispatch(tmp_path, {"operation": "trip_watch_plan", "data": {**inputs, "at": BASE["at"]}})
    assert replay["revision"] == original["revision"]


@pytest.mark.parametrize("confirm", [False, True])
def test_pending_wake_is_recorded_and_replanned(tmp_path, confirm):
    ledger = Ledger(tmp_path)
    trip_watch.plan(ledger, **BASE)
    data = dict(action="record_wake", trip_id="synthetic", moment="arrival_logistics", wake_id="w_pending", armed=False)
    pending = dispatch(tmp_path, {"operation": "trip_watch_plan", "data": data})
    assert pending["wake_id"] == "w_pending" and not pending["moments"][2]["armed"]
    assert not trip_watch.plan(ledger, **BASE)["armed"]
    if confirm:
        dispatch(tmp_path, {"operation": "trip_watch_plan", "data": {**data, "armed": True}})
    assert trip_watch.status(ledger, "synthetic")["moments"][2]["armed"] is confirm
    assert trip_watch.plan(ledger, **{**BASE, "airport_lead_minutes": 240})["stale_wakes"] == ["w_pending"]


def test_expired_immediate_projection_is_resolved(tmp_path):
    ledger = Ledger(tmp_path)
    planned = trip_watch.plan(ledger, **BASE)
    StateLoop(ledger).projection_claim(event_id=planned["event_id"], projection_key="arm:arrival_logistics",
                                      claimed_by="synthetic", at="2020-01-01T00:00:00+00:00")
    trip_watch.plan(ledger, **{**BASE, "at": "2026-11-10T10:00:00+01:00"})
    assert not StateLoop(ledger).reconcile()["issues"]


def test_arrival_trigger_capped_at_leave_by(tmp_path):
    result = trip_watch.plan(Ledger(tmp_path), **BASE, check_in_lead_minutes=60)
    assert result["pulse_create"]["trigger"]["at"] == result["moments"][1]["at"]


def test_atomic_wake_receipt_survives_projection_interruption(tmp_path, monkeypatch):
    ledger = Ledger(tmp_path)
    trip_watch.plan(ledger, **BASE)
    with monkeypatch.context() as scoped:
        scoped.setattr(trip_watch, "_resolve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("interrupted")))
        with pytest.raises(RuntimeError):
            trip_watch.record_wake(ledger, "synthetic", "arrival_logistics", "w_recover")
    assert trip_watch.plan(ledger, **{**BASE, "airport_lead_minutes": 240})["stale_wakes"] == ["w_recover"]
    trip_watch.record_cancel(ledger, "synthetic", "w_recover")
    assert trip_watch.status(ledger, "synthetic")["stale_wakes"] == []


def test_quiet_hours_resolves_projection(tmp_path):
    ledger = Ledger(tmp_path)
    preferences(ledger, {"quiet_hours": {"start": "00:00", "end": "12:00"}, "timezone": "UTC"})
    result = trip_watch.plan(ledger, **{**BASE, "hb2_quiet_hours": "12:00-00:00", "at": "2026-10-01T00:00:00+00:00"})
    assert result["status"] == "quiet_hours"
    assert not StateLoop(ledger).reconcile()["issues"]


@pytest.mark.parametrize("offset", ["+01:00", "+02:00"])
def test_spring_forward_gap_rejected(tmp_path, offset):
    with pytest.raises(ValueError, match="arrival_timezone"):
        trip_watch.plan(Ledger(tmp_path), **{**BASE, "departure_at": "2026-03-28T12:00:00+01:00",
            "arrival_at": f"2026-03-29T02:30:00{offset}", "arrival_timezone": "Europe/Paris"})


@pytest.mark.parametrize("clock,quiet", [("07:05", True), ("07:30", False), ("22:15", False), ("22:30", True)])
def test_automation_quiet_minutes(clock, quiet):
    result = script_precheck(timezone="UTC", now=f"2026-11-10T{clock}:00+00:00",
                            quiet_hours={"start": "22:30", "end": "07:30"}, unresolved_refunds=True)
    assert (result["reason"] == "quiet_hours") is quiet


def test_failed_turn_notice_is_not_offer_delivery(tmp_path):
    ledger = Ledger(tmp_path)
    hook = make_pre_llm_call(tmp_path, lambda k, d: d)
    human = dict(user_message="Hi", platform="telegram", sender_id="synthetic", session_id="a",
                 is_first_turn=True, turn_id="one", conversation_history=[{"role": "user", "content": "Hi"}])
    assert hook(**human)
    notice = {"role": "assistant", "content": "That turn failed.", "display_kind": "failed_turn"}
    history = human["conversation_history"] + [notice, {"role": "user", "content": "Hi again"}]
    assert hook(**{**human, "is_first_turn": False, "turn_id": "two", "conversation_history": history})
    assert setup.state(ledger)["status"] == "not_started"


def test_mid_interview_draft_keeps_interview_in_progress(tmp_path):
    ledger = Ledger(tmp_path)
    setup.start(ledger, active_platform="telegram", active_sender_id="synthetic", active_chat="telegram:session:s2")
    setup.record(ledger, answers={"call_and_quiet": {"text": "Synthetic", "source": "user"}}, asked=["call_and_quiet"])
    writes = [{"target": "manual_skill", "summary": "Synthetic deeper preference"}]
    saved = dispatch(tmp_path, {"operation": "setup", "data": {"action": "propose", "writes": writes, "draft": True}})
    assert saved["status"] == "in_progress" and saved["proposal_draft"]["writes"] == writes
    assert saved["next_question"] == "worth_a_message"
    hook = make_pre_llm_call(tmp_path, lambda k, d: d)
    note = hook(user_message="Hi", platform="telegram", sender_id="synthetic", session_id="s2", is_first_turn=True)
    assert "ask only the next question (worth_a_message)" in note["context"]
    with pytest.raises(ValueError, match="draft"):
        setup.propose(ledger, writes, draft="yes")
    setup.propose(ledger, [])
    with pytest.raises(ValueError, match="draft"):  # A review awaiting apply is not an interview.
        setup.propose(ledger, writes, draft=True)


def test_quiet_hours_recommends_the_reserved_immediate_offer(tmp_path):
    ledger = Ledger(tmp_path)
    preferences(ledger, {"quiet_hours": {"start": "00:00", "end": "12:00"}, "timezone": "UTC"})
    result = trip_watch.plan(ledger, **{**BASE, "hb2_quiet_hours": "12:00-00:00", "at": "2026-10-01T00:00:00+00:00"})
    assert result["status"] == "quiet_hours" and result["recommend"] == "offer_now_in_chat"
