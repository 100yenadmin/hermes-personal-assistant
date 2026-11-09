"""Held drafts are approval waits, never evidence of contact; synthetic profiles only."""
import datetime as dt
from pathlib import Path
import socket
from zoneinfo import ZoneInfo

import pytest

from personal_assistant.context import APPROVAL_OVERDUE_DAYS, approval_wait, next_actions
from personal_assistant.state import Ledger


ZONE = ZoneInfo("Asia/Tokyo")
HELD_AT = "2026-11-11T14:30:00+00:00"  # 23:30 in the owner's timezone.
HELD = {"step": "day2", "at": HELD_AT, "how": "nudge draft held"}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)


@pytest.mark.parametrize("log", [
    [], [HELD, {**HELD, "how": "reminder"}], [HELD, {**HELD, "how": "nudge sent"}],
    [HELD, {**HELD, "how": "nudge declined"}], [HELD, {**HELD, "how": "escalate"}],
    [HELD, {**HELD, "how": "nudge draft approved"}],
])
def test_approval_wait_ends_at_last_nonheld_entry(log):
    moment = dt.datetime.fromisoformat("2026-11-13T00:30:00+09:00")
    assert approval_wait({"chase_log": log}, moment, ZONE) is None


@pytest.mark.parametrize("how", ["nudge draft held", "draft held", "NUDGE DRAFT HELD"])
@pytest.mark.parametrize("day,days,overdue", [(11, 0, False), (12, 1, False), (13, 2, True)])
def test_approval_wait_counts_owner_local_calendar_days(how, day, days, overdue):
    moment = dt.datetime.fromisoformat(f"2026-11-{day}T00:30:00+09:00")
    if days == 0:
        moment = moment.replace(hour=23, minute=45)
    fields = {"chase_log": [{**HELD, "how": how}]}
    assert APPROVAL_OVERDUE_DAYS == 2
    assert approval_wait(fields, moment, ZONE) == {
        "step": "day2", "since": HELD_AT, "days": days, "overdue": overdue,
    }
    assert fields["chase_log"] == [{**HELD, "how": how}]


@pytest.fixture
def ledger(tmp_path):
    result = Ledger(tmp_path)
    result.put("action", "pa:preferences", {"timezone": "Asia/Tokyo"})
    result.put("action", "fixture-loop", {
        "loop_kind": "waiting_on_them", "counterparty": "Jordan Demo", "next_actor": "them",
        "opened_at": "2026-11-09", "last_chased_at": HELD_AT, "chase_log": [HELD],
    }, action_type="commitment", status="open")
    return result


def read_loop(ledger, at):
    packet = next_actions(ledger, {"loops_only": True, "at": at},
                          kanban_reader=lambda *_: {"status": "unknown", "evidence": "fixture"})
    return packet["candidates"][0]


@pytest.mark.parametrize("day,days,prefix", [(12, 1, ""), (13, 2, "Approval overdue (2 days): ")])
def test_next_action_reports_held_draft_honestly(ledger, day, days, prefix):
    item = read_loop(ledger, f"2026-11-{day}T00:30:00+09:00")
    assert item["chase"]["step"] == "none"
    assert item["awaiting_approval"] == {
        "step": "day2", "since": HELD_AT, "days": days, "overdue": days >= 2,
    }
    assert item["next_step"] == (
        prefix + "A nudge to Jordan Demo (day2) has been awaiting the owner's yes since 2026-11-11. "
        "Show the held draft again: send, edit or drop. It is not a sent chase.")


@pytest.mark.parametrize("day,step,days", [(14, "day5", 3), (19, "day10", 8)])
def test_later_step_waits_for_decision_on_held_draft(ledger, day, step, days):
    item = read_loop(ledger, f"2026-11-{day}T00:30:00+09:00")
    assert item["chase"]["step"] == step
    assert item["next_step"] == (
        f"Approval overdue ({days} days): The day2 nudge to Jordan Demo is still awaiting the owner's yes "
        "(since 2026-11-11); ask the owner to decide on it before drafting another.")


def test_sent_entry_clears_wait_and_restores_ladder_guidance(ledger):
    sent = {**HELD, "at": "2026-11-12T09:00:00+09:00", "how": "nudge sent"}
    ledger.put("action", "fixture-loop", {"last_chased_at": sent["at"], "chase_log": [HELD, sent]})
    item = read_loop(ledger, "2026-11-14T00:30:00+09:00")
    assert "awaiting_approval" not in item
    assert item["chase"]["step"] == "day5"
    assert item["next_step"].startswith("Chase day5: draft a nudge to Jordan Demo")


def test_snooze_wins_over_approval_wait(ledger):
    until = "2026-11-21T09:00:00+09:00"
    ledger.put("action", "fixture-loop", {"snoozed_until": until})
    item = read_loop(ledger, "2026-11-14T00:30:00+09:00")
    assert item["awaiting_approval"]["overdue"] is True
    assert item["chase"]["step"] == "none"
    assert item["next_step"].startswith(f"Wait until {until}")


def test_escalation_guidance_survives_held_draft(ledger):
    item = read_loop(ledger, "2026-11-20T00:30:00+09:00")
    assert item["awaiting_approval"]["overdue"] is True
    assert item["chase"]["step"] == "escalate"
    assert item["next_step"].startswith("Escalate to the owner with problem, options (2-3)")


def test_skill_reports_held_drafts_as_awaiting_approval():
    text = (Path(__file__).resolve().parents[1] / "skills/follow-through/SKILL.md").read_text()
    assert "awaiting your yes" in text
    assert "never as chased" in text


def test_escalation_names_the_unsent_draft_and_an_escalate_entry_keeps_the_wait(ledger):
    item = read_loop(ledger, "2026-11-20T00:30:00+09:00")
    assert item["next_step"].endswith("The day2 nudge to Jordan Demo was never sent: name it as awaiting the owner's yes "
                                      "since 2026-11-11, never as a chase.")
    escalated = {"step": "escalate", "at": "2026-11-20T09:00:00+09:00", "how": "escalation packet in the brief"}
    moment = dt.datetime.fromisoformat("2026-11-21T00:30:00+09:00")
    assert approval_wait({"chase_log": [HELD, escalated]}, moment, ZONE)["since"] == HELD_AT


@pytest.mark.parametrize("how", ["nudge withheld by owner", "held back by owner", "upheld",
                                 "nudge sent after being held", "draft held, then declined"])
def test_only_a_held_draft_counts_as_waiting(how):
    moment = dt.datetime.fromisoformat("2026-11-13T00:30:00+09:00")
    assert approval_wait({"chase_log": [{**HELD, "how": how}]}, moment, ZONE) is None


def test_a_nudge_in_flight_is_not_awaiting_the_owners_yes(ledger):
    ledger.prepare("fixture-loop:nudge:day2", {"provider": "fixture-mail", "final_action": "send the held nudge"})
    item = read_loop(ledger, "2026-11-13T00:30:00+09:00")
    assert "awaiting_approval" not in item and "in progress" in item["next_step"]


@pytest.mark.parametrize("entry", [{**HELD, "how": "nudge draft held, not sent"},
                                   {**HELD, "step": "escalate", "how": "nudge draft held"}])
def test_held_wording_and_a_held_escalation_nudge_still_wait(entry):
    moment = dt.datetime.fromisoformat("2026-11-13T00:30:00+09:00")
    assert approval_wait({"chase_log": [entry]}, moment, ZONE)["since"] == HELD_AT
