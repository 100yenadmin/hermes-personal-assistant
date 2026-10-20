"""Separate CoS setup progress, using the existing reviewed-write engine."""
from personal_assistant import setup
from personal_assistant.commands import READY, make_pa_command
from personal_assistant.entry import dispatch
from personal_assistant.onboarding_hook import make_pre_llm_call
from personal_assistant.state import Ledger
from personal_assistant.automation_workflow import preferences
import pytest


COS = ("cos_priorities", "cos_radar_topics", "cos_daily_time", "cos_weekly_slot", "cos_schedules")
ANSWER = {"text": "Synthetic preference", "source": "user"}


def test_cos_questions_walk_and_sections_keep_independent_counts(tmp_path):
    ledger = Ledger(tmp_path)
    setup.start(ledger)
    setup.record(ledger, {"call_and_quiet": ANSWER}, skipped=["authority"], asked=["call_and_quiet"])
    core = setup.state(ledger)
    current = setup.request(ledger, "chief_of_staff")
    assert current["counts"] == {"asked": 0, "answers": 0, "skipped": 0, "total": 5}
    for question in COS:
        assert current["next_question"] == question
        current = setup.record(ledger, {question: ANSWER}, asked=[question])
    assert current["next_question"] is None
    assert current["counts"] == {"asked": 5, "answers": 5, "skipped": 0, "total": 5}
    setup.request(ledger)
    current = setup.state(ledger)
    assert current["counts"] == core["counts"]
    assert current["next_question"] == core["next_question"]
    setup.record(ledger, {"worth_a_message": ANSWER})
    current = setup.request(ledger, "chief_of_staff")
    assert current["counts"]["answers"] == 5 and current["next_question"] is None
    review = setup.request(ledger, None)
    assert set(review["answers"]) == {*COS, "call_and_quiet", "worth_a_message"}
    assert review["requested_mode"] == "review"
    assert setup.propose(ledger, [])["status"] == "proposed"


def test_cos_start_dispatch_and_hook_preserve_requested_section(tmp_path):
    ledger = Ledger(tmp_path)
    current = dispatch(tmp_path, {"operation": "setup", "data": {"action": "start", "section": "chief_of_staff"}})
    assert current["next_question"] == COS[0]
    setup.request(ledger, "chief_of_staff")
    note = make_pre_llm_call(tmp_path, lambda k, d=None: {"chief_of_staff": True} if k == "modes" else d)(
        user_message="Ready", platform="telegram", sender_id="synthetic")
    assert "pa-setup" in note["context"]
    assert setup.state(ledger)["requested_section"] == "chief_of_staff"
    assert setup.state(ledger)["next_question"] == COS[0]


def test_cos_command_maps_hyphenated_section_and_leaves_core_review_alone(tmp_path):
    command = make_pa_command(tmp_path, get_config=lambda k, d=None: {"chief_of_staff": True} if k == "modes" else d)
    assert "5" in command("setup chief-of-staff")
    assert setup.state(Ledger(tmp_path))["requested_section"] == "chief_of_staff"
    assert "of 5" in command("status")
    assert command("setup") == READY
    assert setup.state(Ledger(tmp_path))["requested_section"] == "core"
    assert command("setup review") == READY
    assert setup.state(Ledger(tmp_path))["requested_mode"] == "review"


def test_cos_command_off_stops_before_setup_mutation(tmp_path):
    command = make_pa_command(tmp_path)
    before = setup.state(Ledger(tmp_path))
    message = command("setup chief-of-staff")
    assert "/pa mode chief-of-staff on" in message
    assert "hermes gateway restart" in message and "new session" in message
    assert setup.state(Ledger(tmp_path)) == before


def test_cos_skips_do_not_skip_core_questions(tmp_path):
    ledger = Ledger(tmp_path)
    setup.request(ledger, "chief_of_staff")
    current = setup.record(ledger, skipped=list(COS))
    assert current["next_question"] is None and current["counts"]["skipped"] == 5
    current = setup.request(ledger)
    assert current["next_question"] == "call_and_quiet"
    assert current["counts"]["skipped"] == 0


def test_pending_cos_setup_stops_if_mode_is_turned_off(tmp_path):
    ledger = Ledger(tmp_path)
    setup.request(ledger, "chief_of_staff")
    before = setup.state(ledger)
    note = make_pre_llm_call(tmp_path, lambda k, d=None: d)(user_message="Ready", platform="telegram")
    assert "Do not record answers, create rules or suggest jobs" in note["context"]
    assert setup.state(ledger) == before


@pytest.mark.parametrize("changes", [{"cos_daily_time": "23:00"}, {"cos_weekly_time": "06:30"},
                                     {"cos_daily_time": "10:00", "quiet_hours": {"start": "09:00", "end": "11:00"}}])
def test_cos_time_inside_quiet_hours_is_refused(tmp_path, changes):
    ledger = Ledger(tmp_path)
    with pytest.raises(ValueError, match="inside quiet hours"):
        preferences(ledger, changes)
    assert preferences(ledger) == {}


def test_quiet_hours_check_only_covers_saved_cos_times(tmp_path):
    ledger = Ledger(tmp_path)
    preferences(ledger, {"quiet_hours": {"start": "08:00", "end": "10:00"}})  # No CoS times saved.
    preferences(ledger, {"cos_daily_time": "21:59", "cos_weekly_time": "10:00"})
    with pytest.raises(ValueError, match="cos_weekly_time 10:00"):
        preferences(ledger, {"quiet_hours": {"start": "09:00", "end": "11:00"}})
    assert preferences(ledger)["quiet_hours"] == {"start": "08:00", "end": "10:00"}
