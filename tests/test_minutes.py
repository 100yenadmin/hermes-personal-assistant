"""Synthetic transcript-to-minutes through the public entry contract; no network, no sends."""
import copy
import datetime as dt
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
                "quote": "I'll review the Cedar contract and reply to them by November 12.", "due_wording": "by November 12"}],
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
    assert avery["fields"]["loop_kind"] == "our_promise" and avery["fields"]["next_actor"] == "owner"
    assert jordan["fields"]["due_at"] == "2026-11-13T17:00:00+00:00" and jordan["fields"]["opened_at"] == "2026-11-13"
    assert avery["fields"]["opened_at"] == "2026-11-10" and avery["fields"]["meeting_date"] == "2026-11-09"
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
    items[1]["due_date"] = "2026-11-11"  # Still "by November 12".
    moved = save(home, action_items=items[1:])
    rows = loops(home)
    kept = next(i for i in moved["loop_ids"])
    assert kept == ids[1] and rows[kept]["fields"]["due_at"].startswith("2026-11-11") and rows[kept]["status"] == "open"
    dropped = (set(ids) - set(moved["loop_ids"])).pop()
    assert dropped == ids[0]  # The item with a chase history.
    assert rows[dropped]["status"] == "cancelled" and rows[dropped]["fields"]["loop_cancelled"]["reason"] == "removed from the saved minutes"
    revived = save(home)
    back = loops(home)[dropped]
    assert back["status"] == "open" and back["fields"]["chase_log"] == [] and "loop_cancelled" not in back["fields"]
    assert loop_state(back, {}) == "open"


@pytest.mark.parametrize("change,message", [
    ({"owner": "TBD"}, "no named owner"),
    ({"owner": "someone"}, "no named owner"),
    ({"owner": "team"}, "no named owner"),
    ({"owner": "I"}, "no named owner"),
    ({"owner": "we"}, "no named owner"),
    ({"owner": "birch"}, "not a speaker"),  # A word in the transcript is not a person.
    ({"owner": "Riley"}, "not a speaker"),
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
    items[1] = {**items[0], "owner": "Jordan"}
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


def test_owner_name_matching_and_speakers(home):
    items = copy.deepcopy(MINUTES["action_items"])
    # The profile's full name still marks the owner's own item said as "Avery".
    result = save(home, owner_name="Avery Chen", action_items=items)
    assert "error" not in result, result
    owner_item = next(r for r in loops(home).values() if r["fields"]["title"].startswith("Review the Cedar"))
    assert owner_item["fields"]["loop_kind"] == "our_promise" and owner_item["fields"]["next_actor"] == "owner"
    assert "owner_name must be one of the attendees" in save(home, owner_name="Riley")["error"]
    # A speaker label counts as a person even when the attendee list misses them.
    assert "error" not in save(home, attendees=["Avery", "Jordan"])


@pytest.mark.parametrize("change,where", [
    ({"summary": "x"}, "invalid minutes at data"), ({"overview": None}, "overview"),
    ({"name": "Studio Sync"}, "invalid minutes at name"),
    ({"open_questions": [{"text": "Who?"}]}, "invalid minutes at open_questions/0")])
def test_schema_errors_name_the_field(home, change, where):
    data = {**copy.deepcopy(MINUTES), **change}
    if change.get("overview", "") is None:
        del data["overview"]
    result = entry.dispatch(home, {"operation": "minutes", "data": data})
    assert where in result["error"], result


def test_short_quote_names_the_item_field(home):
    items = copy.deepcopy(MINUTES["action_items"])
    items[0]["quote"] = "Will do"
    error = save(home, action_items=items)["error"]
    assert "action_items/0/quote" in error and "8+ characters" in error


def test_chases_start_after_the_due_date_and_owner_items_remind_on_the_day(home):
    save(home)
    def steps(day):
        packet = entry.dispatch(home, {"operation": "next_action", "data": {"loops_only": True, "at": day + "T10:00:00+00:00"}})
        return {c["counterparty"]: c["chase"]["step"] for c in packet["candidates"] if c["action_id"].startswith("minutes:")}
    assert steps("2026-11-11") == {"Owner": "none", "Jordan": "none"}
    assert steps("2026-11-12") == {"Owner": "day2", "Jordan": "none"}  # The owner's own item: reminded on its due day.
    assert steps("2026-11-15") == {"Owner": "day5", "Jordan": "day2"}  # Jordan's item: two days after it was due.


def test_failed_file_replace_leaves_old_files_and_no_loop_change(home, monkeypatch):
    first = save(home)
    before = {k: Path(p).read_text() for k, p in first["paths"].items()}
    rows = {k: (r["status"], r["fields"]) for k, r in loops(home).items()}
    import os as real_os
    from personal_assistant import minutes
    original = real_os.replace
    def replace(src, dst):
        if str(dst).endswith(".json"):
            raise OSError("disk full")
        return original(src, dst)
    monkeypatch.setattr(minutes.os, "replace", replace)
    items = copy.deepcopy(MINUTES["action_items"])[:1]
    assert "disk full" in save(home, action_items=items)["error"]
    assert {k: (r["status"], r["fields"]) for k, r in loops(home).items()} == rows  # The dropped item stays open.
    assert Path(first["paths"]["json"]).read_text() == before["json"]
    assert not list((home / "exports/minutes").glob(".*.tmp"))


def test_dropped_completed_unconfirmed_item_is_cancelled_but_confirmed_kept(home):
    ids = save(home)["loop_ids"]
    with Ledger(home).connect() as conn:
        conn.execute("update actions set status='completed' where action_id=?", (ids[0],))
        row = conn.execute("select fields_json from actions where action_id=?", (ids[1],)).fetchone()[0]
        fields = json.loads(row)
        fields["confirmation"] = {"by": "Jordan", "at": "2026-11-12T10:00:00+00:00", "evidence": "Files received"}
        conn.execute("update actions set status='completed', fields_json=? where action_id=?", (json.dumps(fields), ids[1]))
    save(home, action_items=[], decisions=MINUTES["decisions"])
    rows = loops(home)
    assert rows[ids[0]]["status"] == "cancelled" and rows[ids[1]]["status"] == "completed"


@pytest.mark.parametrize("change,message", [
    ({"quote": "        "}, "too short"),
    ({"quote": "Let's also move the sync to Tuesdays from next week."}, "does not mention this action"),
    ({"owner": "contract"}, "not a speaker"),
    ({"due_wording": "by Thursday"}, "not in the transcript")])
def test_grounding_refusals(home, change, message):
    items = copy.deepcopy(MINUTES["action_items"])
    items[0].update(change)
    assert message in save(home, action_items=items)["error"]
    assert not loops(home)


def test_attendee_never_named_in_transcript_cannot_own_an_item(home):
    items = copy.deepcopy(MINUTES["action_items"])
    items[0]["owner"] = "Riley"
    assert "not a speaker" in save(home, attendees=["Avery", "Jordan", "Sam", "Riley"], action_items=items)["error"]


@pytest.mark.parametrize("change,ok", [
    ({"due_date": "2026-11-12"}, False),  # "by Friday" on a Thursday.
    ({"due_date": "2026-11-13"}, True),
    ({"due_date": "2026-12-25"}, False),  # A Friday, but not the coming one.
    ({"owner": "Jordan Fictional"}, False),  # An extension of a speaker's name is not that person.
])
def test_date_wording_and_owner_extension(home, change, ok):
    items = copy.deepcopy(MINUTES["action_items"])
    items[0].update(change)
    assert ("error" not in save(home, action_items=items)) is ok


def test_day_number_tomorrow_short_items_and_plain_timestamps(home):
    transcript = TRANSCRIPT + "00:04:10 Riley: Fix bug tomorrow, I promise.\nAvery: And the report by the 12th please, Riley.\n"
    (home / "imports/meetings/sync.txt").write_text(transcript, encoding="utf-8")
    items = copy.deepcopy(MINUTES["action_items"]) + [
        {"text": "Fix bug", "owner": "Riley", "due_date": "2026-11-10", "quote": "Fix bug tomorrow, I promise.", "due_wording": "tomorrow"},
        {"text": "Send the report", "owner": "Riley", "due_date": "2026-11-12", "quote": "And the report by the 12th please", "due_wording": "by the 12th"}]
    assert "error" not in save(home, action_items=items)  # Riley is a speaker after a plain timestamp.
    items[2]["due_date"] = "2026-11-11"
    assert "does not match its wording" in save(home, action_items=items)["error"]
    items[2]["due_date"], items[3]["due_date"] = "2026-11-10", "2026-11-13"
    assert "does not match its wording" in save(home, action_items=items)["error"]


def test_failed_staging_write_leaves_no_temporary(home, monkeypatch):
    from personal_assistant import minutes
    real = minutes.os.fdopen
    def broken(fd, *args, **kwargs):
        handle = real(fd, *args, **kwargs)
        handle.write = lambda text: (_ for _ in ()).throw(OSError("disk full"))
        return handle
    monkeypatch.setattr(minutes.os, "fdopen", broken)
    assert "disk full" in save(home)["error"]
    monkeypatch.setattr(minutes.os, "fdopen", real)
    assert not list((home / "exports/minutes").glob(".*.tmp"))
    assert "error" not in save(home)  # A retry in the same process works.


@pytest.mark.parametrize("wording,due,meeting,ok", [
    ("by Friday", "2026-11-13", "2026-11-09", True), ("Friday", "2026-11-13", "2026-11-13", True),
    ("next Monday", "2026-11-16", "2026-11-09", True), ("on the 3rd", "2026-12-03", "2026-11-30", True),
    ("by 5", "2026-11-09", "2026-11-09", True), ("today or tomorrow", "2026-11-10", "2026-11-09", True),
    ("Friday in two weeks", "2026-11-27", "2026-11-09", True), ("by Friday, December 25", "2026-12-25", "2026-11-09", True),
    ("a week from today", "2026-11-16", "2026-11-09", True), ("a week from tomorrow", "2026-11-17", "2026-11-09", True),
    ("before the 12th", "2026-11-11", "2026-11-09", True), ("by end of week", "2026-11-13", "2026-11-09", True),
    ("by Friday", "2026-11-12", "2026-11-09", False), ("by Friday.", "2026-12-25", "2026-11-09", False),
    ("tomorrow", "2026-11-11", "2026-11-09", False), ("by the 12th", "2026-11-13", "2026-11-09", False),
    ("next Friday", "2026-12-04", "2026-11-09", False)])
def test_date_wording_checks_only_plain_forms(wording, due, meeting, ok):
    from personal_assistant.minutes import _date_fits
    assert _date_fits(wording, dt.date.fromisoformat(due), dt.date.fromisoformat(meeting)) is ok


def test_speaker_labels_with_twelve_hour_times():
    from personal_assistant.minutes import SPEAKER
    assert SPEAKER.findall("12:03 PM Riley: hi\n(9:15 a.m.) Jordan: yes\n12:04 Amy: ok\n12:05 Pam: sure\n") == ["Riley", "Jordan", "Amy", "Pam"]


def test_hard_linked_json_leaves_the_markdown_unchanged(home, tmp_path):
    first = save(home)
    markdown = Path(first["paths"]["markdown"])
    before = markdown.read_text()
    outside = tmp_path / "outside.json"
    outside.write_text("keep")
    Path(first["paths"]["json"]).unlink()
    Path(first["paths"]["json"]).hardlink_to(outside)
    assert "hard-linked" in save(home, overview="Changed overview.")["error"]
    assert markdown.read_text() == before and outside.read_text() == "keep"


def test_owner_and_due_wording_bind_to_the_quote_line(home):
    items = copy.deepcopy(MINUTES["action_items"])
    items[0].update(owner="Sam")  # Jordan said "I'll send Birch ..."; Sam did not promise it.
    assert "did not make this promise; jordan did" in save(home, action_items=items)["error"]
    items = copy.deepcopy(MINUTES["action_items"])
    items[0].update(due_date="2026-11-12", due_wording="by November 12")  # Avery's deadline, on Avery's line.
    assert "due wording is not on the quote's line" in save(home, action_items=items)["error"]


def test_date_agreed_on_a_later_line_by_the_owner(home):
    transcript = "Avery: Jordan, can you get the revised logo files to Birch?\nSam: Busy week.\nJordan: Sure, by Friday.\n"
    (home / "imports/meetings/sync.txt").write_text(transcript, encoding="utf-8")
    item = {"text": "Get the revised logo files to Birch", "owner": "Jordan", "due_date": "2026-11-13",
            "quote": "can you get the revised logo files to Birch", "due_wording": "by Friday"}
    result = save(home, decisions=[], open_questions=[], action_items=[item])
    assert "error" not in result, result
    transcript = "Avery: Jordan, can you get the revised logo files to Birch?\nSam: I can do it by Friday.\n"
    (home / "imports/meetings/sync.txt").write_text(transcript, encoding="utf-8")
    assert "due wording is not on the quote's line" in save(home, decisions=[], open_questions=[], action_items=[item])["error"]


def test_resave_leaves_provider_rows_and_transaction_owned_loops_alone(home):
    ids = save(home)["loop_ids"]
    child = ids[0] + ":nudge:day2"
    with Ledger(home).connect() as conn:
        conn.execute("insert into actions values(?,?,?,?,?,?,?,?)",
                     (child, None, "transaction", "", "prepared", json.dumps({"exact_action": "send"}), "2026-11-11", "2026-11-11"))
        conn.execute("update actions set action_type='transaction', status='prepared' where action_id=?", (ids[1],))
    assert save(home)["loop_ids"] == ids
    with Ledger(home).connect() as conn:
        rows = {r[0]: (r[1], r[2]) for r in conn.execute("select action_id, action_type, status from actions where action_id like 'minutes:%'")}
    assert rows[child] == ("transaction", "prepared") and rows[ids[1]] == ("transaction", "prepared")
    assert rows[ids[0]] == ("commitment", "open")


@pytest.mark.parametrize("transcript,item", [
    # The requester names the date on the next line.
    ("Jordan: I'll send the deck.\nSam: Can we have it by Friday?\nJordan: Yes.\n",
     {"owner": "Jordan", "quote": "I'll send the deck.", "due_wording": "by Friday"}),
    # Blank lines, cue numbers and timestamp lines do not use up the window.
    ("Jordan: I'll send the deck.\n\n2\n00:00:05.000 --> 00:00:07.000\nSam: ok\n\nJordan: by Friday then.\n",
     {"owner": "Jordan", "quote": "I'll send the deck.", "due_wording": "by Friday"}),
    # "I can't" is not a promise.
    ("Avery: I can't send the deck, so Jordan will send the deck by Friday.\n",
     {"owner": "Jordan", "quote": "I can't send the deck, so Jordan will send the deck by Friday", "due_wording": "by Friday"}),
    # The same words said by two people: the owner's own line counts.
    ("Sam: I'll send the deck by Friday.\nJordan: I'll send the deck by Friday.\n",
     {"owner": "Jordan", "quote": "I'll send the deck by Friday.", "due_wording": "by Friday"}),
    # A date alone on the next line still counts.
    ("Jordan: I'll send the deck.\n2026-11-13\n", {"owner": "Jordan", "quote": "I'll send the deck.", "due_wording": "2026-11-13"}),
    # A "Me:" label is the profile owner.
    ("Me: I'll send the deck by Friday.\nJordan: ok\n",
     {"owner": "Avery", "quote": "I'll send the deck by Friday.", "due_wording": "by Friday"})])
def test_messy_transcripts_keep_correct_items(home, transcript, item):
    (home / "imports/meetings/sync.txt").write_text(transcript, encoding="utf-8")
    item = {"text": "Send the deck", "due_date": "2026-11-13", **item}
    result = save(home, decisions=[], open_questions=[], action_items=[item])
    assert "error" not in result, result
