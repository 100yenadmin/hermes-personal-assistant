"""Separate CoS setup progress, using the existing reviewed-write engine."""
from personal_assistant import setup
from personal_assistant.commands import READY, make_pa_command
from personal_assistant.entry import dispatch
from personal_assistant.onboarding_hook import make_pre_llm_call
from personal_assistant.state import Ledger
from personal_assistant.automation_workflow import preferences
import pytest


COS = ("cos_priorities", "cos_radar_topics", "cos_daily_time", "cos_kickoff_slot", "cos_weekly_slot",
       "cos_schedule_choices")
ANSWER = {"text": "Synthetic preference", "source": "user"}


def test_cos_questions_walk_and_sections_keep_independent_counts(tmp_path):
    ledger = Ledger(tmp_path)
    setup.start(ledger)
    setup.record(ledger, {"call_and_quiet": ANSWER}, skipped=["authority"], asked=["call_and_quiet"])
    core = setup.state(ledger)
    current = setup.request(ledger, "chief_of_staff")
    assert current["counts"] == {"asked": 0, "answers": 0, "skipped": 0, "total": 6}
    for question in COS:
        assert current["next_question"] == question
        current = setup.record(ledger, {question: ANSWER}, asked=[question])
    assert current["next_question"] is None
    assert current["counts"] == {"asked": 6, "answers": 6, "skipped": 0, "total": 6}
    setup.request(ledger)
    current = setup.state(ledger)
    assert current["counts"] == core["counts"]
    assert current["next_question"] == core["next_question"]
    setup.record(ledger, {"worth_a_message": ANSWER})
    current = setup.request(ledger, "chief_of_staff")
    assert current["counts"]["answers"] == 6 and current["next_question"] is None
    review = setup.request(ledger, None)
    assert set(review["answers"]) == {*COS, "call_and_quiet", "worth_a_message"}
    assert review["requested_mode"] == "review"
    assert setup.propose(ledger, [])["status"] == "proposed"


def mode_on(root, on=True):
    import yaml
    (root / "config.yaml").write_text(yaml.safe_dump({"plugins": {"enabled": ["personal-assistant"],
        "entries": {"personal-assistant": {"settings": {"modes": {"chief_of_staff": on}}}}}}))


def test_cos_start_dispatch_and_hook_preserve_requested_section(tmp_path):
    mode_on(tmp_path)
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
    assert "6 in all" in command("setup chief-of-staff")
    assert setup.state(Ledger(tmp_path))["requested_section"] == "chief_of_staff"
    assert "of 6" in command("status")
    assert command("setup").startswith("Setup continues here.")  # A bare /pa setup keeps the active section.
    assert setup.state(Ledger(tmp_path))["requested_section"] == "chief_of_staff"
    assert command("setup core") == READY
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
    assert current["next_question"] is None and current["counts"]["skipped"] == 6
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
                                     {"cos_kickoff_time": "22:30"},
                                     {"cos_kickoff_time": "11:00", "quiet_hours": {"start": "10:00", "end": "12:00"}},
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


@pytest.mark.parametrize("kind", ["cos_daily", "cos_kickoff", "cos_weekly"])
def test_cos_suggestion_withheld_when_rules_disagree_on_the_chat(tmp_path, kind):
    from personal_assistant import automation as auto
    ledger = Ledger(tmp_path)
    for rule_id, chat in ((kind, "telegram:one"), (kind + "-2", "telegram:two")):
        auto.upsert_automation_rule(ledger, rule_id, {"kind": kind, "accepted": True, "destination": chat,
                                                      "destination_verified": True, "timezone": "Asia/Tokyo"})
    result = auto.suggest_automation_jobs(ledger=ledger, chief_of_staff=True)
    assert result["jobs"] == [] and f"{kind}: conflicting destinations" in result["missing_inputs"]


def test_cos_section_with_core_progress_still_gets_its_intro(tmp_path):
    ledger = Ledger(tmp_path)
    setup.start(ledger)
    setup.record(ledger, {"call_and_quiet": ANSWER}, skipped=["authority"], asked=["call_and_quiet"])
    setup.request(ledger, "chief_of_staff")
    note = make_pre_llm_call(tmp_path, lambda k, d=None: {"chief_of_staff": True} if k == "modes" else d)(
        user_message="Ready", platform="telegram", sender_id="synthetic")
    assert "Chief of Staff section's intro and consent flow" in note["context"]
    setup.record(ledger, asked=["cos_priorities"])
    note = make_pre_llm_call(tmp_path, lambda k, d=None: {"chief_of_staff": True} if k == "modes" else d)(
        user_message="Next", platform="telegram", sender_id="synthetic")
    assert "ask only the next question (cos_priorities)" in note["context"]


def test_setup_operation_refuses_cos_while_mode_is_off(tmp_path):
    with pytest.raises(ValueError, match="mode is off"):
        dispatch(tmp_path, {"operation": "setup", "data": {"action": "start", "section": "chief_of_staff"}})
    setup.request(Ledger(tmp_path), "chief_of_staff")
    for data in ({"action": "start"}, {"action": "record", "answers": {"cos_priorities": ANSWER}}):
        with pytest.raises(ValueError, match="mode is off"):
            dispatch(tmp_path, {"operation": "setup", "data": data})
    assert setup.state(Ledger(tmp_path))["counts"]["answers"] == 0
    mode_on(tmp_path)
    assert dispatch(tmp_path, {"operation": "setup", "data": {"action": "record",
                    "answers": {"cos_priorities": ANSWER}}})["counts"]["answers"] == 1
    setup.request(Ledger(tmp_path))  # Core setup is never gated by the mode.
    mode_on(tmp_path, False)
    assert dispatch(tmp_path, {"operation": "setup", "data": {"action": "start"}})["requested_section"] == "core"


def test_review_mode_reports_combined_progress_without_a_next_question(tmp_path):
    ledger = Ledger(tmp_path)
    setup.request(ledger, "chief_of_staff")
    setup.record(ledger, {question: ANSWER for question in COS})
    current = setup.request(ledger, None)
    assert current["next_question"] is None
    assert current["counts"] == {"asked": 0, "answers": 6, "skipped": 0, "total": 14}


def test_fresh_session_check_branches_for_cos():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "skills/pa-setup/SKILL.md").read_text()
    check = text[text.index("## Fresh-session check"):]
    assert "If `requested_section` is `chief_of_staff`" in check.split("When would you check in")[0]


def test_cos_count_reply_follows_the_question_tuple(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "CHIEF_OF_STAFF_QUESTIONS", (*setup.CHIEF_OF_STAFF_QUESTIONS, "fixture"))
    command = make_pa_command(tmp_path, get_config=lambda k, d=None: {"chief_of_staff": True} if k == "modes" else d)
    assert "7 in all" in command("setup chief-of-staff")


def test_kickoff_slot_precedes_the_closeout_and_keeps_its_id():
    assert setup.CHIEF_OF_STAFF_QUESTIONS.index("cos_kickoff_slot") + 1 == setup.CHIEF_OF_STAFF_QUESTIONS.index("cos_weekly_slot")


def test_kickoff_time_quiet_hours_refusal_names_the_kickoff(tmp_path):
    ledger = Ledger(tmp_path)
    preferences(ledger, {"cos_kickoff_day": "mon", "cos_kickoff_time": "11:00"})
    with pytest.raises(ValueError, match="cos_kickoff_time 11:00 is inside quiet hours"):
        preferences(ledger, {"quiet_hours": {"start": "10:30", "end": "12:00"}})
    assert preferences(ledger) == {"cos_kickoff_day": "mon", "cos_kickoff_time": "11:00"}


def test_question_bank_names_kickoff_and_closeout():
    from pathlib import Path
    text = " ".join((Path(__file__).resolve().parents[1] / "skills/pa-setup/references/question-bank.md").read_text().split())
    assert "Ask only the six CoS questions" in text
    assert "| `cos_kickoff_slot` | “When should we kick off the week?” |" in text
    assert "Monday 11:00" in text and "`cos_kickoff_day` (mon..sun), `cos_kickoff_time` (HH:MM)" in text
    assert "| `cos_weekly_slot` | “When should we close out the week?” |" in text
    assert "Friday 15:00" in text and "earlier" in text
    assert text.index("`cos_kickoff_slot`") < text.index("`cos_weekly_slot`")
    assert "daily, kickoff and closeout" in text and "its own explicit yes" in text
