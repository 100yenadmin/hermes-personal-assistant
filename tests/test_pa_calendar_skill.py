"""R4 calendar skill text: writes with buffers, invites after a yes, find a time, 24h confirmations."""
from pathlib import Path

from personal_assistant.recipes import route

ROOT = Path(__file__).resolve().parents[1]
R4 = ROOT / "skills/personal-assistant/r4-calendar-meeting"


def flat(path: Path) -> str:
    return " ".join(path.read_text().split())


def test_r4_skill_routes_writes_invites_times_and_briefs_to_references():
    text = flat(R4 / "SKILL.md")
    for ref in ("references/calendar-writes.md", "references/find-a-time.md", "references/meeting-brief.md"):
        assert ref in text and (R4 / ref).is_file()
    assert "relative to this skill directory" in text
    assert "Recurring series writes and attendee sends are outside this candidate" not in text
    assert "`--send-updates all` appears only after the yes" in text
    assert 'never say "invited" before the readback shows the attendees' in text
    assert 'enforcement_profile: "exact_action"' in text and "pa.action_cancel" in text
    assert "`meetings_to_confirm`" in text and "No hold or invite without a yes" in text
    assert len((R4 / "SKILL.md").read_bytes()) < 6000


def test_calendar_writes_reference_names_zone_dry_run_notification_and_readback():
    text = flat(R4 / "references/calendar-writes.md")
    assert "RFC3339" in text and "IANA zone" in text and "abbreviation" in text
    assert "`--dry-run` first" in text and "The dry run carries no `--send-updates`" in text
    assert "whether guests will be notified" in text and "every attendee address" in text
    assert "no calendar call carries it until the owner's yes and `pa.action_confirm`" in text
    assert "`--send-updates` defaults to `none`" in text
    assert "buffer before and after" in text and "protected focus block" in text
    assert "`calendar.write_scope`" in text and "`invites: true`" in text
    assert "Only then say \"booked\" or \"invited\"" in text and "every attendee" in text
    for command in ("calendar create", "calendar update", "calendar respond", "--scope single", "focus-time"):
        assert command in text


def test_find_a_time_reference_keeps_s19_behaviour():
    text = flat(R4 / "references/find-a-time.md")
    assert "calendar freebusy" in text and "Unknown is not free" in text
    assert "working hours in their own IANA zone" in text
    assert "every participant's local time and UTC offset" in text
    assert "DST" in text and "flag it" in text
    assert "Propose 2–3 slots" in text and "No hold, tentative event or invite without the owner's yes" in text
    assert "focus blocks" in text


def test_meeting_brief_reference_is_one_page_and_held_for_a_yes():
    text = flat(R4 / "references/meeting-brief.md")
    assert "one page" in text
    for part in ("**Purpose:**", "**Attendees:**", "**Agenda:**", "**Open items:**", "**Prep links:**"):
        assert part in text
    assert "local time and offset" in text and "never invented" in text
    assert "send only after the owner's yes" in text and "`pa.action_confirm`" in text
    assert "within 24 hours with `pa.action_upsert`" in text and "Kanban" in text
    assert "`attendees_known` is false" in text


def test_r4_recipe_uses_the_governed_protocol_for_guest_notifications():
    recipe = route("R4")
    assert recipe["transaction_paths"] == ["invite send", "guest-notifying update", "decline or reschedule"]
    assert [step["operation"] for step in recipe["transaction_protocol"]] == [
        "action_prepare", "action_confirm", "action_result"]
    assert "attendees read back" in recipe["expected_outcome"]
    assert "outside this candidate" not in recipe["expected_outcome"]
