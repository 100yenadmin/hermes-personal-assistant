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
    assert "closed only when the other side confirms" in section
    assert "Kanban done is not confirmation" in section
    assert "`personal-assistant:follow-through`" in section
    assert "never put chase dates in `due_at`" in section


def test_open_loops_reference_details_fields_and_close():
    text = (ROOT / "skills/personal-assistant/references/open-loops.md").read_text()
    for name in LOOP_FIELDS + ("next_chase_at", "day2", "day5", "day10", "escalate"):
        assert f"`{name}`" in text, name
    assert '"done_unconfirmed"' in text
    assert "closes only on the other side's confirmation" in text
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
