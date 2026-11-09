from pathlib import Path

import pytest

from personal_assistant import setup
from personal_assistant.commands import ESSENTIAL_READY, MENU, READY, make_pa_command
from personal_assistant.entry import dispatch
from personal_assistant.onboarding_hook import make_pre_llm_call
from personal_assistant.state import Ledger


def test_essentials_order_completion_and_status(tmp_path):
    ledger = Ledger(tmp_path)
    assert setup.ESSENTIAL_QUESTIONS == ("call_and_quiet", "voice_tone", "authority", "first_errands")
    current = dispatch(tmp_path, {"operation": "setup", "data": {"action": "start", "section": "essentials"}})
    for q in setup.ESSENTIAL_QUESTIONS:
        assert current["next_question"] == q
        current = setup.record(ledger, skipped=[q]) if q == "first_errands" else setup.record(
            ledger, {q: {"text": "Synthetic", "source": "user"}}, asked=[q])
    assert current["next_question"] is None
    assert current["sections"]["essentials"] == {"answers": 3, "asked": 3, "skipped": 1, "covered": 0, "total": 4}
    assert "Essentials 4 of 4 (1 skipped)" in make_pa_command(tmp_path)("setup status")
    setup.propose(ledger, [])
    assert setup.applied(ledger, [], "A")["fresh_check"]["section"] == "essentials"
    for section in ("core", "chief_of_staff", "profile"):
        assert "first_errands" not in setup.SECTIONS[section]


@pytest.mark.parametrize("section,remaining", [("core", "worth_a_message"), ("profile", "voice_examples")])
def test_shared_answers_are_never_reasked(tmp_path, section, remaining):
    ledger = Ledger(tmp_path)
    setup.request(ledger, "essentials")
    setup.record(ledger, {q: {"text": "Synthetic", "source": "user"} for q in setup.ESSENTIAL_QUESTIONS})
    if section == "profile":
        setup.record(ledger, skipped=[q for group, ids in setup.PROFILE_GROUPS if group != "voice" for q in ids])
    assert setup.request(ledger, section)["next_question"] == remaining


@pytest.mark.parametrize("command", ["setup", "setup essentials"])
def test_fresh_command_starts_essentials(tmp_path, command):
    assert make_pa_command(tmp_path)(command) == ESSENTIAL_READY
    assert setup.state(Ledger(tmp_path))["requested_section"] == "essentials"


@pytest.mark.parametrize("status", ["offered", "paused", "declined"])
def test_started_core_progress_keeps_core(tmp_path, status):
    ledger = Ledger(tmp_path)
    setup.request(ledger, "core")
    setup.record(ledger, {"call_and_quiet": {"text": "Synthetic", "source": "user"}})
    ledger.put("action", "pa:setup", {"status": status})
    assert make_pa_command(tmp_path)("setup") == READY
    assert setup.state(ledger)["requested_section"] == "core"


def test_unstarted_offer_still_starts_essentials(tmp_path):
    setup.mark_offered(Ledger(tmp_path))
    assert make_pa_command(tmp_path)("setup") == ESSENTIAL_READY


def test_essentials_menu_defers_new_and_offers_core(tmp_path):
    ledger = Ledger(tmp_path)
    setup.request(ledger, "essentials")
    setup.record(ledger, skipped=list(setup.ESSENTIAL_QUESTIONS))
    setup.propose(ledger, [])
    setup.applied(ledger, [], "A")
    before = setup.state(ledger)
    assert make_pa_command(tmp_path)("setup") == MENU
    assert "travel setup (core)" in MENU and "/pa setup core" in MENU
    assert setup.state(ledger) == before


def test_set_me_up_starts_essentials_without_extra_consent_turn(tmp_path):
    note = make_pre_llm_call(tmp_path, lambda k, d: d)(user_message="Hi! Set me up so you can start helping.",
            platform="cli", session_id="A", is_first_turn=True)
    assert "Essentials (first run)" in note["context"] and "no terminal steps" in note["context"]
    assert setup.state(Ledger(tmp_path))["requested_section"] == "essentials"


def test_essentials_skill_contract_and_caps():
    skill = (Path(__file__).resolve().parents[1] / "skills/pa-setup/SKILL.md").read_text()
    subsection = skill.split("### Essentials (first run)\n")[1].split("## Chief of Staff section")[0]
    assert len(subsection.splitlines()) <= 12 and len(skill.splitlines()) <= 165
    for phrase in ("Finish errand 1 right after apply", "No terminal steps", "offer `/new`", "after the first win",
                   "one review and apply", "never a plan or question", "do errand 2 instead"):
        assert phrase in subsection
