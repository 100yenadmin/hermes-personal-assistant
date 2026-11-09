from pathlib import Path

from personal_assistant.entry import SCHEMA

ROOT = Path(__file__).resolve().parents[1]
LOOP_FIELDS = ("loop_kind", "counterparty", "next_actor", "opened_at", "next_step",
               "last_chased_at", "chase_log", "confirmation")


def test_pa_skill_states_open_loop_contract():
    text = (ROOT / "skills/personal-assistant/SKILL.md").read_text()
    section = text[text.index("## Open loops"):text.index("## Governed exact-action transaction")]
    for name in LOOP_FIELDS + ("ask_owner", "delegated", "our_promise", "waiting_on_them"):
        assert name in section, name
    assert "Record every question or\nask you put to the owner as an `ask_owner` loop" in section
    assert "A loop closes when the other side confirms" in section and "or when the owner cancels it" in section
    assert "Kanban done is not confirmation" in section
    assert "`personal-assistant:follow-through`" in section
    assert "never put chase dates in `due_at`" in section


def test_open_loops_reference_details_fields_and_close():
    text = (ROOT / "skills/personal-assistant/references/open-loops.md").read_text()
    for name in LOOP_FIELDS + ("next_chase_at", "day2", "day5", "day10", "escalate"):
        assert f"`{name}`" in text, name
    assert '"done_unconfirmed"' in text
    assert "closes on the other side's confirmation, or when the owner cancels it" in text
    assert "Kanban done is not confirmation" in text
    assert '"loop_kind":"ask_owner"' in text


def test_schema_and_docs_name_loop_fields():
    data = SCHEMA["parameters"]["properties"]["data"]
    action_type = data["properties"]["action_type"]["description"]
    for name in LOOP_FIELDS:
        assert name in action_type, name
    assert "never put chase dates in due_at" in action_type
    assert data["properties"]["loops_only"]["type"] == "boolean"
    assert "loops_only" in data["description"]
    docs = (ROOT / "docs/personal-assistant.md").read_text()
    section = docs[docs.index("## Open loops and follow-through"):docs.index("## Generic state loop")]
    for name in LOOP_FIELDS:
        assert name in section, name
    assert "done_unconfirmed" in section and "day 2, day 5, day 10, then escalate" in section


SKILL = ROOT / "skills/follow-through/SKILL.md"
REFERENCES = ROOT / "skills/follow-through/references"


def _skill_text():
    return SKILL.read_text()


def test_follow_through_skill_front_matter_and_size():
    import yaml

    # 6000 until the HB2 role rule (#151); keep the skill lean.
    assert SKILL.stat().st_size < 6500
    front = yaml.safe_load(_skill_text().split("---", 2)[1])
    assert front["name"] == "follow-through" and front["description"]
    assert front["metadata"]["openclaw"]["skillKey"] == "follow-through"
    assert front["metadata"]["hermes"]["category"] == "productivity"
    assert "pa_mode" not in front["metadata"]["hermes"]  # Core PA, not a Chief of Staff skill.


def test_follow_through_uses_real_operations_and_loops_only():
    import re

    text = _skill_text() + "".join(p.read_text() for p in REFERENCES.glob("*.md"))
    operations = set(re.findall(r'pa\(\s*operation="([a-z_]+)"', text))
    assert operations and operations <= set(SCHEMA["parameters"]["properties"]["operation"]["enum"])
    assert 'pa(operation="next_action", data={"loops_only":true' in text
    for path in ("references/escalation-packet.md", "references/reminders-and-wakes.md"):
        assert path in _skill_text() and (SKILL.parent / path).is_file()


def test_follow_through_ladder_steps_and_actions():
    text = _skill_text()
    for step in ("`day2`", "`day5`", "`day10`", "`escalate`", "`none`"):
        assert step in text, step
    assert "remind the owner" in text
    assert "hold it for the owner's yes" in text and "A draft is not a send." in text
    assert "Kanban done is not confirmation" in text
    assert '"last_chased_at"' in text and '"chase_log"' in text
    assert "never put chase dates in `due_at`" in text


def test_follow_through_escalation_packet_has_four_fixed_fields():
    text = _skill_text()
    section = text[text.index("## Escalate"):text.index("## Scheduled runs")]
    for name in ("`problem`", "`options` (2 or 3)", "`recommendation`", "`decision_deadline`"):
        assert name in section, name
    assert "daily brief" in section and "same chat as the original ask" in section
    assert 'step: "escalate"' in section
    packet = (REFERENCES / "escalation-packet.md").read_text()
    for name in ("problem", "options", "recommendation", "decision_deadline"):
        assert f"`{name}`" in packet and f"**{name}:**" in packet, name


def test_follow_through_never_sends_without_confirm():
    text = _skill_text()
    assert 'enforcement_profile="exact_action"' in text and "`action_confirm`" in text
    assert "Never send without that confirmation" in text
    assert "There is no other send path." in text
    reference = (REFERENCES / "reminders-and-wakes.md").read_text()
    assert 'enforcement_profile="exact_action"' in reference and "`action_confirm`" in reference


def test_follow_through_scheduled_run_uses_receipt_or_silent_and_no_message_tool():
    text = _skill_text()
    section = text[text.index("## Scheduled runs"):text.index("## Wakes")]
    assert "Never use a message tool in a scheduled run." in section
    assert '"receipt":"unknown","note":"Final response handed to Hermes cron delivery"' in section
    assert '`receipt: "suppressed"`' in section and "reply exactly `[SILENT]` (nothing else)" in section
    assert "already claimed `occurrence_id`" in section


def test_follow_through_role_wakes_and_owner_approved_dates_outside_roles():
    text = _skill_text()
    section = text[text.index("## Wakes"):]
    outside = section.split("Outside a role turn:", 1)[1]
    assert "only for a date the owner approved" in outside and "`owner_asked: true`" in outside
    reference = (REFERENCES / "reminders-and-wakes.md").read_text()
    assert '"trigger":{"kind":"at"' in reference and '"owner_asked":true' in reference
    outside_reference = reference.split("Outside a role turn:", 1)[1]
    assert "Only when the owner approves a specific follow-up date in a human turn in this\nchat" in outside_reference
    assert "never create\nanother wake from a follow-up turn" in outside_reference
    for text in (section, reference):
        normalized = " ".join(text.split())
        assert "Inside a PA follow-through role turn" in normalized
        assert 'note starts "PA follow-through role"' in normalized
        assert "plain `at` wakes (no `owner_asked`)" in normalized
        assert "chase date or approval timeout" in normalized
        assert "at most 3 per turn" in normalized
        assert "none already armed for the same loop and step" in normalized
        assert "HB2 header `role`" in normalized
        assert "within HB2's limits" in normalized
        assert "Report a refusal; never work around it" in normalized
        assert "On any HB2 wake turn, HB2 delivers the final reply; never also use a message tool" in normalized
    assert "never for your own chase dates or from a follow-up turn" in " ".join(outside.split())
    assert "`pulse` `list`" in reference and "PA follow-through wake: <action id> <step>" in reference
    child = reference.split("Inside a PA follow-through role turn", 1)[1].split("Outside a role turn:", 1)[0]
    assert "owner_asked\":" not in child.replace("(no `owner_asked`)", "")


def test_nudges_are_prepared_as_their_own_action():
    text = SKILL.read_text(encoding="utf-8")
    assert "`<loop action id>:nudge:<step>`" in text
    assert "never on the loop's own action" in text
