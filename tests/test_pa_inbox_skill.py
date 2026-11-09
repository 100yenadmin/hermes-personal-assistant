"""R6 inbox skill text: five buckets, short digest, tracked threads, voice-first drafts, no silent mutation."""
from pathlib import Path

from personal_assistant.recipes import route

ROOT = Path(__file__).resolve().parents[1]
R6 = ROOT / "skills/personal-assistant/r6-inbox-replies"
BUCKETS = ("urgent", "needs you", "handled", "FYI", "junk")


def flat(path: Path) -> str:
    return " ".join(path.read_text().split())


def test_r6_skill_names_buckets_digest_tracking_and_no_silent_mutation():
    text = flat(R6 / "SKILL.md")
    assert "five buckets: urgent, needs you, handled, FYI, junk" in text
    assert "digest of 5 lines or fewer that names every urgent item and every decision needed" in text
    assert "Junk is report-only during triage" in text and "never delete or label" in text
    assert "`pa:inbox:<account-alias>:<thread_id>`" in text
    for field in ("`thread_id`", "`bucket`", "`waiting_for`", "`due_at`", "`decision_needed`", "`loop_kind`"):
        assert field in text
    assert "`ask_owner`" in text and "`waiting_on_them`" in text
    assert "read the owner's voice and each person's rules first" in text
    assert "never a mailbox draft" in text and 'enforcement_profile: "exact_action"' in text
    for ref in ("references/triage.md", "references/drafts-and-sends.md"):
        assert ref in text and (R6 / ref).is_file()
    assert len((R6 / "SKILL.md").read_bytes()) < 6000


def test_triage_reference_reuses_two_routines_and_keeps_coverage():
    text = flat(R6 / "references/triage.md")
    assert "the morning brief and the evening register both carry `humans_N`" in text
    assert "There is no third job." in text
    assert "A failed mail read is a failure to report, never an empty inbox." in text
    for bucket in BUCKETS:
        assert f"| {bucket} |" in text
    assert "The coverage line is never dropped" in text
    digest = (R6 / "references/triage.md").read_text().split("```text\n", 1)[1].split("```", 1)[0]
    assert len(digest.strip().splitlines()) <= 5


def test_tracking_rows_use_lane_a_loop_fields_and_close_on_confirmation():
    text = flat(R6 / "references/triage.md")
    assert "Daily Ops account key (`work` or `personal`), never an address" in text
    assert "`action_type`: `commitment`" in text
    for field in ("`counterparty`", "`next_actor`", "`opened_at`", "`next_step`", "`confirmation`"):
        assert field in text
    assert "Chase dates live in `next_chase_at`, never `due_at`" in text
    assert "A Kanban card marked done is not confirmation." in text


def test_drafts_read_voice_first_and_send_only_after_a_yes():
    text = flat(R6 / "references/drafts-and-sends.md")
    voice = text.index('"category":"voice"')
    person = text.index('"name":"<name>"')
    drafting = text.index("## Drafting")
    assert voice < drafting and person < drafting
    assert "`inbox.drafts.accepted: true`" in text and "`gmail.compose`" in text
    assert "A scheduled run never saves provider drafts." in text
    assert "Only after the owner's explicit yes" in text and "`pa.action_confirm`" in text
    assert "gmail drafts send <draftId>" in text and "Read the sent message back" in text


def test_r6_recipe_describes_triage_and_keeps_the_send_protocol():
    recipe = route("R6")
    assert "five buckets" in recipe["description"]
    assert recipe["transaction_paths"] == ["send reply"]
    assert any("urgent, needs you, handled, FYI and junk" in step for step in recipe["steps"])
