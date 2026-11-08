"""A scheduled brief always lists open loops and due items, even when a source is missing."""
from pathlib import Path

from personal_assistant import automation as auto
from personal_assistant.automation_workflow import prepare_suggestions, preferences
from personal_assistant.state import Ledger

ROOT = Path(__file__).resolve().parents[1]


def test_brief_guidance_never_trades_open_loops_for_a_source_gap():
    r5 = (ROOT / "skills/personal-assistant/r5-brief-reminders/SKILL.md").read_text()
    for fragment in ("## What every brief contains", "`loops_only: true`", "day-2\nnudge due.", "drafted only when `next_action` shows one in progress", "remaining (non-loop) candidates",
                     "Never send a brief that only reports a source gap while open\nloops exist",
                     "no open loops, no due items and nothing useful from the sources"):
        assert fragment in r5
    daily = (ROOT / "skills/daily-ops/SKILL.md").read_text()
    assert "never replace PA's own\nopen loops and due items" in daily and "What every brief contains" in daily


def test_the_brief_job_prompt_carries_the_rule(tmp_path):
    ledger = Ledger(tmp_path)
    preferences(ledger, {"timezone": "Asia/Tokyo"})
    auto.upsert_automation_rule(ledger, "daily_brief", {"kind": "daily_brief", "accepted": True, "timezone": "Asia/Tokyo",
                                                       "destination": "origin", "destination_verified": True})
    auto.upsert_automation_rule(ledger, "due_source_check", {"kind": "due_source_check", "accepted": True, "timezone": "Asia/Tokyo",
                                                            "destination": "origin", "destination_verified": True})
    jobs = {j["kind"]: j for j in prepare_suggestions(ledger)["jobs"]}
    assert "Every brief lists" not in jobs["due_source_check"]["job_spec"]["prompt"]
    prompt = jobs["daily_brief"]["job_spec"]["prompt"]
    assert "Every brief lists PA's open loops (pa next_action with loops_only true) and due items" in prompt
    assert "never instead of them" in prompt
