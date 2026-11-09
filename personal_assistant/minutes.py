"""Meeting minutes from a transcript inside the profile: every action item has an owner and a date. Never sends."""
import datetime as dt
import json
import os
import re
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft7Validator, FormatChecker

from .context import owner_zone
from .privacy import clean
from .profile import _private
from .state import legacy, now, stable_id

LIMIT = 2 * 1024 * 1024
TEXT = {"type": "string", "minLength": 1, "maxLength": 500}
QUOTE = {"type": "string", "minLength": 8, "maxLength": 500}
DATE = {"type": "string", "format": "date"}
OP_SCHEMA = {"type": "object", "additionalProperties": False,
             "required": ["action", "path", "name", "title", "meeting_date", "owner_name", "attendees", "overview",
                          "decisions", "action_items"],
             "properties": {
                 "action": {"const": "save"}, "path": {"type": "string", "minLength": 1},
                 "name": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{0,40}$"},
                 "title": {"type": "string", "minLength": 1, "maxLength": 200}, "meeting_date": DATE,
                 "timezone": {"type": "string", "minLength": 1, "maxLength": 64},
                 "owner_name": {"type": "string", "minLength": 1, "maxLength": 100},
                 "attendees": {"type": "array", "minItems": 1, "maxItems": 50, "items": {"type": "string", "minLength": 1, "maxLength": 100}},
                 "overview": {"type": "string", "maxLength": 2000},
                 "decisions": {"type": "array", "maxItems": 50, "items": {
                     "type": "object", "additionalProperties": False, "required": ["text", "quote"],
                     "properties": {"text": TEXT, "quote": QUOTE}}},
                 "action_items": {"type": "array", "maxItems": 100, "items": {
                     "type": "object", "additionalProperties": False, "required": ["text", "owner", "due_date", "quote"],
                     "properties": {"text": TEXT, "owner": {"type": "string", "minLength": 1, "maxLength": 100},
                                    "due_date": DATE, "quote": QUOTE,
                                    "due_wording": {"type": "string", "minLength": 1, "maxLength": 100}}}},
                 "open_questions": {"type": "array", "maxItems": 50, "items": {
                     "type": "object", "additionalProperties": False, "required": ["question"],
                     "properties": {"question": TEXT, "quote": QUOTE}}}}}
PLACEHOLDER = {"tbd", "tba", "unknown", "unassigned", "someone", "anyone", "n/a", "na", "none", "?", "-", "owner tbd"}


def _norm(text):
    text = unicodedata.normalize("NFKC", str(text)).casefold()
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}))
    return " ".join(text.split())


def _read(root, relative_text):
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 2 or relative.parts[0] != "imports":
        raise ValueError("minutes path must be relative under imports/")
    current = root
    for part in relative.parts:  # Read-only input: refuse symlinks, but not the owner's file permissions.
        current = current / part
        if current.is_symlink():
            raise ValueError("minutes path must not contain a symlink")
    path = root / relative
    if not path.is_file():
        raise ValueError("minutes path is not a regular file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        content = handle.read(LIMIT + 1)
    if len(content) > LIMIT:
        raise ValueError("transcript exceeds 2 MB")
    text = content.decode("utf-8-sig")
    if "\x00" in text:
        raise ValueError("NUL in transcript")
    return text


def _validate(data, transcript):
    if not Draft7Validator(OP_SCHEMA, format_checker=FormatChecker()).is_valid(data):
        raise ValueError("invalid minutes: each action item needs text, owner, due_date (YYYY-MM-DD) and a transcript quote")
    if _private(data) or clean(data) != data:
        raise ValueError("minutes must not contain card, account or phone numbers or credentials")
    source = _norm(transcript)
    people = {_norm(a) for a in data["attendees"]}
    meeting = dt.date.fromisoformat(data["meeting_date"])

    def quoted(value, what):
        if _norm(value) not in source:
            raise ValueError(f"{what} quote is not in the transcript: {value[:80]}")
    for item in data["decisions"]:
        quoted(item["quote"], "decision")
    for question in data.get("open_questions", []):
        if "quote" in question:
            quoted(question["quote"], "open question")
    for item in data["action_items"]:
        owner = _norm(item["owner"])
        if owner in PLACEHOLDER:
            raise ValueError(f"action item has no real owner; put it under open_questions: {item['text'][:80]}")
        if owner not in people and owner not in source:
            raise ValueError(f"action item owner is not an attendee or named in the transcript: {item['owner']}")
        if dt.date.fromisoformat(item["due_date"]) < meeting:
            raise ValueError(f"action item due date is before the meeting: {item['text'][:80]}")
        quoted(item["quote"], "action item")
        if "due_wording" in item:
            quoted(item["due_wording"], "due wording")
    texts = [_norm(i["text"]) for i in data["action_items"]]
    if len(set(texts)) != len(texts):
        raise ValueError("duplicate action item text")


def _markdown(data, zone_name):
    def cell(value):
        return " ".join(str(value).split()).replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
    lines = [f"# {cell(data['title'])}", "", f"Date: {data['meeting_date']} ({zone_name})",
             f"Attendees: {cell(', '.join(data['attendees']))}", "", "## Summary", "", cell(data["overview"]) or "None.", "",
             "## Decisions", ""]
    lines += [f"- {cell(d['text'])} (\"{cell(d['quote'])}\")" for d in data["decisions"]] or ["None."]
    lines += ["", "## Action items", "", "| Owner | Action | Due | Said |", "| --- | --- | --- | --- |"]
    lines += [f"| {cell(i['owner'])} | {cell(i['text'])} | {i['due_date']}"
              + (f" ({cell(i['due_wording'])})" if i.get("due_wording") else "") + f" | \"{cell(i['quote'])}\" |"
              for i in data["action_items"]]
    lines += ["", "## Open questions for the owner", ""]
    lines += [f"- {cell(q['question'])}" for q in data.get("open_questions", [])] or ["None."]
    return "\n".join(lines) + "\n"


def _write(root, path, text):
    legacy._validate_existing_path(root, path)
    if path.exists() and path.stat().st_nlink > 1:
        raise ValueError("minutes output must not be hard-linked")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(text)


def _get(conn, identity):
    row = conn.execute("select * from actions where action_id=?", (identity,)).fetchone()
    return legacy.row_to_dict(row) if row else None


def _put(conn, identity, fields, status):
    old = _get(conn, identity)
    merged = {**(old or {}).get("fields", {}), **fields}
    stamp = now()
    conn.execute("insert into actions values(?,?,?,?,?,?,?,?) on conflict(action_id) do update set "
                 "action_type=excluded.action_type,status=excluded.status,"
                 "fields_json=excluded.fields_json,updated_at=excluded.updated_at",
                 (identity, None, "commitment", "", status, json.dumps(merged, ensure_ascii=False),
                  (old or {}).get("created_at", stamp), stamp))


def dispatch(ledger, data):
    try:
        transcript = _read(ledger.root, data.get("path", "")) if isinstance(data.get("path"), str) else ""
        _validate(data, transcript)
        try:
            zone = ZoneInfo(data["timezone"]) if data.get("timezone") else owner_zone(ledger)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("minutes timezone must be an IANA zone") from None
        zone_name = getattr(zone, "key", "UTC")
        output = ledger.root / "exports" / "minutes"
        paths = {"markdown": output / (data["name"] + ".md"), "json": output / (data["name"] + ".json")}
        me = _norm(data["owner_name"])
        prefix = "minutes:" + data["name"] + ":"
        loops = {}
        for item in data["action_items"]:
            mine = _norm(item["owner"]) == me
            due = dt.datetime.combine(dt.date.fromisoformat(item["due_date"]), dt.time(17), zone).isoformat()
            loops[prefix + stable_id("minutes", data["name"], _norm(item["text"]))] = {
                "title": item["text"], "loop_kind": "our_promise" if mine else "waiting_on_them",
                "counterparty": "Owner" if mine else item["owner"], "next_actor": "us" if mine else "them",
                "opened_at": data["meeting_date"], "due_at": due,
                "next_step": f"{item['owner']}: {item['text']} by {item['due_date']}",
                "source_ref": f"minutes {data['name']}: \"{item['quote']}\""}
        record = {k: v for k, v in data.items() if k not in {"action", "path"}}
        record.update({"timezone": zone_name, "source": data["path"], "loop_ids": sorted(loops)})
        legacy._ensure_directory(ledger.root, output)
        for path in paths.values():
            legacy._validate_existing_path(ledger.root, path)
        with ledger.connect() as conn:
            conn.execute("begin immediate")
            existing = [r[0] for r in conn.execute("select action_id from actions where action_id like ?", (prefix + "%",))]
            for identity, fields in loops.items():
                old = _get(conn, identity)
                if not old or old["status"] == "cancelled":
                    fields = {**fields, "chase_log": []}
                _put(conn, identity, fields, "open" if not old or old["status"] == "cancelled" else old["status"])
            for identity in set(existing) - set(loops):  # An item dropped on re-save stops being chased.
                old = _get(conn, identity)
                if old and old["status"] == "open":
                    _put(conn, identity, {"loop_cancelled": {"by": "owner", "at": now(), "reason": "removed from the saved minutes"}}, "cancelled")
            _write(ledger.root, paths["markdown"], _markdown(data, zone_name))
            _write(ledger.root, paths["json"], json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        return {"paths": {k: str(p) for k, p in paths.items()}, "action_items": len(data["action_items"]),
                "decisions": len(data["decisions"]), "open_questions": len(data.get("open_questions", [])),
                "loop_ids": sorted(loops), "sent": False}
    except (ValueError, OSError, RuntimeError) as exc:
        return {"error": str(exc)}
