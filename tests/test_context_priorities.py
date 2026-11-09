"""Priority context and workload counts with synthetic commitments only."""
import pytest

from personal_assistant.context import _action_summary, next_actions
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger

AT = "2026-11-10T12:00:00+00:00"


def packet(ledger, **data):
    return next_actions(ledger, {"at": AT, **data}, kanban_reader=lambda *_: {"status": "unknown"})


@pytest.mark.parametrize("blocked_by", ["lab:photos", ["lab:photos", "lab:copy"]])
def test_priority_and_blocker_pass_through_without_loop_fields(tmp_path, blocked_by):
    ledger = Ledger(tmp_path)
    expected = {"priority": "Launch the Studio Kit", "blocked_by": blocked_by}
    ledger.put("action", "linked", {"title": "Landing page", **expected}, action_type="commitment", status="open")
    ledger.put("action", "unlinked", {"title": "Plants"}, action_type="commitment", status="open")
    items = {r["action_id"]: r for r in packet(ledger)["candidates"]}
    for row in (items["linked"], _action_summary(ledger.get("action", "linked"))):
        assert {k: row[k] for k in expected} == expected
    for row in (items["unlinked"], _action_summary(ledger.get("action", "unlinked"))):
        assert "priority" not in row and "blocked_by" not in row
    assert "load" not in packet(ledger)


def test_load_counts_beyond_page_and_handles_non_loop_items(tmp_path):
    ledger = Ledger(tmp_path)
    for i, actor in enumerate(["them"] * 5 + ["owner"] * 2):
        fields = {"next_actor": actor, "counterparty": "Sam Demo" if actor == "them" else "Owner",
                  "due_at": "2026-11-12"}
        if i != 0:  # A named next actor still counts when loop fields are absent.
            fields.update(loop_kind="delegated" if actor == "them" else "ask_owner", opened_at="2026-11-10")
        ledger.put("action", f"item:{i}", fields, action_type="commitment", status="open")
    ledger.put("action", "no-actor", {}, action_type="commitment", status="open")
    ledger.put("action", "done", {"next_actor": "them"}, action_type="commitment", status="completed")
    ledger.put("action", "note", {"next_actor": "them"}, action_type="note", status="open")
    for offset in (0, 3, 20):
        result = packet(ledger, limit=2, offset=offset)
        assert result["load"] == {"Sam Demo": 5, "owner": 2}
        assert result["total"] == 8
        assert len(result["candidates"]) <= 2
    loop_only = packet(ledger, loops_only=True)
    assert loop_only["load"] == {"Sam Demo": 4, "owner": 2}


@pytest.mark.parametrize("actor,counterparty,holder", [
    ("owner", "Sam Demo", "owner"), ("us", "Sam Demo", "us"),
    ("them", None, "them"), ("them", "", "them"), ("them", "Sam Demo", "Sam Demo")])
def test_load_holder_is_counterparty_only_for_them(tmp_path, actor, counterparty, holder):
    ledger = Ledger(tmp_path)
    fields = {"next_actor": actor}
    if counterparty is not None:
        fields["counterparty"] = counterparty
    ledger.put("action", "item", fields, action_type="commitment", status="open")
    assert packet(ledger)["load"] == {holder: 1}


def test_linking_by_id_merges_existing_fields(tmp_path):
    original = {"title": "Send deck", "next_actor": "owner", "due_at": "2026-11-09", "blocked_by": "lab:copy"}
    dispatch(tmp_path, {"operation": "action_upsert", "data": {
        "action_id": "lab:deck", "action_type": "commitment", "status": "open", "fields": original}})
    dispatch(tmp_path, {"operation": "action_upsert", "data": {
        "action_id": "lab:deck", "fields": {"priority": "Close the seed round"}}})
    rows = Ledger(tmp_path).list("action")
    assert len(rows) == 1
    assert rows[0]["fields"] == {**original, "priority": "Close the seed round"}


@pytest.mark.parametrize("counterparty", [{"name": "Sam", "email": "sam@example.invalid"}, ["Sam", "Lee"], 42, "  "])
def test_a_structured_counterparty_never_breaks_next_action(tmp_path, counterparty):
    """Review: a dict or list counterparty is accepted by action_upsert, so load must not hash it."""
    hh = tmp_path / "home"
    hh.mkdir()
    result = dispatch(hh, {"operation": "action_upsert", "data": {"action_id": "odd", "action_type": "commitment",
              "status": "open", "fields": {"title": "Odd loop", "loop_kind": "delegated", "next_actor": "them",
                                           "counterparty": counterparty, "opened_at": "2026-11-10"}}})
    assert "error" not in result, result
    out = dispatch(hh, {"operation": "next_action", "data": {"at": AT}})
    assert "error" not in out and out["load"] == {"them": 1}
