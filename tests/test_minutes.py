"""Synthetic transcript-to-minutes through the public entry contract; no network, no sends."""
import copy
import json
from pathlib import Path
import socket
import stat

import pytest
from jsonschema import Draft7Validator

from personal_assistant import entry
from personal_assistant.context import loop_state
from personal_assistant.state import Ledger

TRANSCRIPT = """Weekly studio sync, Monday 9 November 2026.
Avery: Thanks all. First, the Birch rebrand. We agreed to go with the teal palette.
Jordan: Great, I'll send Birch the revised logo files by Friday.
Avery: I'll review the Cedar contract and reply to them by November 12.
Sam: Someone should book the photographer for the Maple shoot, not sure who.
Jordan: And the invoice template needs updating at some point.
Avery: Let's also move the sync to Tuesdays from next week.
"""
MINUTES = {"action": "save", "path": "imports/meetings/sync.txt", "name": "studio-sync-2026-11-09",
           "title": "Weekly studio sync", "meeting_date": "2026-11-09", "owner_name": "Avery",
           "attendees": ["Avery", "Jordan", "Sam"], "overview": "Rebrand palette chosen; contract review; sync moves to Tuesdays.",
           "decisions": [{"text": "Use the teal palette for the Birch rebrand", "quote": "We agreed to go with the teal palette."},
                         {"text": "Move the sync to Tuesdays", "quote": "move the sync to Tuesdays from next week"}],
           "action_items": [
               {"text": "Send Birch the revised logo files", "owner": "Jordan", "due_date": "2026-11-13",
                "quote": "I'll send Birch the revised logo files by Friday.", "due_wording": "by Friday"},
               {"text": "Review the Cedar contract and reply", "owner": "Avery", "due_date": "2026-11-12",
                "quote": "I'll review the Cedar contract and reply to them by November 12."}],
           "open_questions": [{"question": "Who books the photographer for the Maple shoot, and by when?",
                               "quote": "Someone should book the photographer for the Maple shoot"},
                              {"question": "When should the invoice template be updated, and who owns it?"}]}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)


@pytest.fixture
def home(tmp_path):
    root = tmp_path / "home"
    (root / "imports/meetings").mkdir(parents=True)
    (root / "imports/meetings/sync.txt").write_text(TRANSCRIPT, encoding="utf-8")
    Ledger(root).put("action", "pa:preferences", {"timezone": "Europe/London"})
    return root


def save(home, **changes):
    return entry.dispatch(home, {"operation": "minutes", "data": {**copy.deepcopy(MINUTES), **changes}})


def loops(home):
    return {r["action_id"]: r for r in Ledger(home).list("action") if r["action_id"].startswith("minutes:")}


def test_save_writes_private_minutes_and_one_loop_per_item(home):
    result = save(home)
    assert "error" not in result, result
    assert result["action_items"] == 2 and result["decisions"] == 2 and result["open_questions"] == 2 and result["sent"] is False
    markdown = Path(result["paths"]["markdown"]).read_text()
    assert "| Jordan | Send Birch the revised logo files | 2026-11-13 (by Friday) |" in markdown
    assert "Who books the photographer" in markdown and "Date: 2026-11-09 (Europe/London)" in markdown
    record = json.loads(Path(result["paths"]["json"]).read_text())
    assert record["loop_ids"] == result["loop_ids"] and record["source"] == "imports/meetings/sync.txt"
    for path in result["paths"].values():
        assert stat.S_IMODE(Path(path).stat().st_mode) == 0o600
        assert Path(path).parent == home / "exports/minutes"
    rows = loops(home)
    assert sorted(rows) == result["loop_ids"]
    by_owner = {r["fields"]["next_step"].split(":")[0]: r for r in rows.values()}
    jordan, avery = by_owner["Jordan"], by_owner["Avery"]
    assert jordan["status"] == avery["status"] == "open"
    assert jordan["fields"]["loop_kind"] == "waiting_on_them" and jordan["fields"]["next_actor"] == "them" and jordan["fields"]["counterparty"] == "Jordan"
    assert avery["fields"]["loop_kind"] == "our_promise" and avery["fields"]["next_actor"] == "us"
    assert jordan["fields"]["due_at"] == "2026-11-13T17:00:00+00:00" and jordan["fields"]["opened_at"] == "2026-11-09"
    assert loop_state(jordan, {}) == "open"
    assert (home / "imports/meetings/sync.txt").read_text() == TRANSCRIPT


def test_resave_is_idempotent_updates_in_place_and_cancels_dropped_items(home):
    first = save(home)
    ids = first["loop_ids"]
    with Ledger(home).connect() as conn:  # A recorded chase survives a re-save.
        row = conn.execute("select fields_json from actions where action_id=?", (ids[0],)).fetchone()[0]
        fields = json.loads(row)
        fields["chase_log"] = [{"step": "day2", "at": "2026-11-11T09:00:00+00:00"}]
        conn.execute("update actions set fields_json=? where action_id=?", (json.dumps(fields), ids[0]))
    again = save(home)
    assert again["loop_ids"] == ids and len(loops(home)) == 2
    assert loops(home)[ids[0]]["fields"]["chase_log"]
    items = copy.deepcopy(MINUTES["action_items"])
    items[0]["due_date"] = "2026-11-16"
    moved = save(home, action_items=items[:1])
    rows = loops(home)
    kept = next(i for i in moved["loop_ids"])
    assert rows[kept]["fields"]["due_at"].startswith("2026-11-16") and rows[kept]["status"] == "open"
    dropped = (set(ids) - set(moved["loop_ids"])).pop()
    assert rows[dropped]["status"] == "cancelled" and rows[dropped]["fields"]["loop_cancelled"]["reason"] == "removed from the saved minutes"
    revived = save(home)
    assert loops(home)[dropped]["status"] == "open" and loops(home)[dropped]["fields"]["chase_log"] == []


@pytest.mark.parametrize("change,message", [
    ({"owner": "TBD"}, "no real owner"),
    ({"owner": "someone"}, "no real owner"),
    ({"owner": "Riley"}, "not an attendee"),
    ({"due_date": "2026-11-02"}, "before the meeting"),
    ({"due_date": "Friday"}, "invalid minutes"),
    ({"quote": "I'll send Birch the final logo files tomorrow."}, "not in the transcript"),
    ({"due_wording": "by Thursday"}, "not in the transcript")])
def test_action_item_refusals(home, change, message):
    items = copy.deepcopy(MINUTES["action_items"])
    items[0].update(change)
    result = save(home, action_items=items)
    assert message in result["error"]
    assert not loops(home) and not (home / "exports/minutes").exists()


@pytest.mark.parametrize("drop", ["owner", "due_date", "quote", "text"])
def test_action_item_missing_field_refused(home, drop):
    items = copy.deepcopy(MINUTES["action_items"])
    del items[0][drop]
    assert "each action item needs text, owner, due_date" in save(home, action_items=items)["error"]
    assert not loops(home)


def test_other_refusals(home, tmp_path):
    assert "not in the transcript" in save(home, decisions=[{"text": "x", "quote": "We agreed to go with the red palette."}])["error"]
    assert "not in the transcript" in save(home, open_questions=[{"question": "Who?", "quote": "Nobody said this sentence."}])["error"]
    items = copy.deepcopy(MINUTES["action_items"])
    items[1]["text"] = items[0]["text"]
    assert "duplicate action item" in save(home, action_items=items)["error"]
    assert "phone numbers" in save(home, overview="Pay by card number: 4242 4242 4242 4242.")["error"]
    assert "relative under imports/" in save(home, path="../outside.txt")["error"]
    assert "relative under imports/" in save(home, path="exports/sync.txt")["error"]
    assert "regular file" in save(home, path="imports/meetings/missing.txt")["error"]
    (home / "imports/meetings/link.txt").symlink_to(home / "imports/meetings/sync.txt")
    assert "symlink" in save(home, path="imports/meetings/link.txt")["error"]
    assert "IANA" in save(home, timezone="Mars/Olympus")["error"]
    assert "invalid minutes" in save(home, name="Bad Name")["error"]
    (home / "imports/meetings/big.txt").write_bytes(b"a" * (2 * 1024 * 1024 + 1))
    assert "2 MB" in save(home, path="imports/meetings/big.txt")["error"]
    assert not loops(home)


def test_quote_matching_tolerates_case_spacing_and_curly_quotes(home):
    items = copy.deepcopy(MINUTES["action_items"])
    items[0]["quote"] = "I’ll   SEND Birch the revised\nlogo files"
    assert "error" not in save(home, action_items=items)


def test_output_symlink_and_hard_link_refused(home, tmp_path):
    (home / "exports").mkdir()
    (home / "exports/minutes").symlink_to(tmp_path, target_is_directory=True)
    assert "error" in save(home)
    assert not loops(home)


def test_explicit_meeting_timezone_sets_due_instants(home):
    result = save(home, timezone="America/New_York")
    rows = loops(home)
    assert all(r["fields"]["due_at"].endswith("-05:00") for r in rows.values())
    assert "(America/New_York)" in Path(result["paths"]["markdown"]).read_text()


def test_public_schema_covers_minutes():
    validator = Draft7Validator(entry.SCHEMA["parameters"])
    assert not list(validator.iter_errors({"operation": "minutes", "data": copy.deepcopy(MINUTES)}))
    assert list(validator.iter_errors({"operation": "minutes"}))
    bad = copy.deepcopy(MINUTES)
    del bad["action_items"][0]["owner"]
    assert list(validator.iter_errors({"operation": "minutes", "data": bad}))


def test_hard_linked_output_refused(home, tmp_path):
    (home / "exports/minutes").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("keep")
    (home / "exports/minutes/studio-sync-2026-11-09.md").hardlink_to(outside)
    assert "hard-linked" in save(home)["error"]
    assert outside.read_text() == "keep" and not loops(home)
