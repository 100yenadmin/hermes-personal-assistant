"""Meeting minutes from a transcript inside the profile: every action item has an owner and a date. Never sends."""
import datetime as dt
import json
import os
import re
import unicodedata
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft7Validator, FormatChecker
from jsonschema.exceptions import best_match

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
                     "type": "object", "additionalProperties": False, "required": ["text", "owner", "due_date", "quote", "due_wording"],
                     "properties": {"text": TEXT, "owner": {"type": "string", "minLength": 1, "maxLength": 100},
                                    "due_date": DATE, "quote": QUOTE,
                                    "due_wording": {"type": "string", "minLength": 1, "maxLength": 100}}}},
                 "open_questions": {"type": "array", "maxItems": 50, "items": {
                     "type": "object", "additionalProperties": False, "required": ["question"],
                     "properties": {"question": TEXT, "quote": QUOTE}}}}}
PLACEHOLDER = {"tbd", "tba", "unknown", "unassigned", "someone", "anyone", "n/a", "na", "none", "?", "-", "owner tbd",
               "i", "me", "we", "us", "you", "they", "them", "team", "the team", "all", "everyone", "everybody"}
STOP = {"the", "and", "for", "you", "our", "but", "not", "all", "any", "can", "has", "had", "was", "are", "its",
        "his", "her", "him", "she", "who", "how", "let", "get", "got", "one", "too", "yes", "now", "off", "out",
        "with", "that", "this", "will", "from", "have", "about", "them", "they", "their", "there", "then", "than",
        "next", "week", "what", "when", "should", "would", "could", "into", "your", "just", "also", "make", "sure"}
SPEAKER = re.compile(r"^\s*(?:\[[^\]]*\]\s*|\(?\d{1,2}:\d{2}(?::\d{2})?(?:\s*[aApP]\.?[mM]\.?(?!\w))?\)?\s*)?([^\W\d][\w .'-]{0,40}?)\s*:", re.M)
COMMITMENT = re.compile(r"\bi(?:'ll| will| can|'m going to| am going to| shall)\b")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _norm(text):
    text = unicodedata.normalize("NFKC", str(text)).casefold()
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}))
    return " ".join(text.split())


def _same(a, b):
    """One name is the other or its leading words: "Jordan" and "Jordan Lee" are the same person."""
    short, long = sorted((a.split(), b.split()), key=len)
    return bool(short) and long[:len(short)] == short


def _words(text):
    return {w for w in re.findall(r"[^\W\d_]{3,}", _norm(text))} - STOP


def _within(owner, person):
    """The owner is the person's name or its leading words ("Jordan" for "Jordan Lee"), never an extension of it."""
    owner, person = owner.split(), person.split()
    return bool(owner) and person[:len(owner)] == owner


def _turns(transcript):
    """(speaker, text) for each transcript line; a line without a label continues the previous speaker."""
    turns, speaker = [], None
    for line in transcript.splitlines():
        label = SPEAKER.match(line)
        if label:
            speaker, line = _norm(label.group(1)), line[label.end():]
        turns.append((speaker, _norm(line)))
    return turns


def _date_fits(wording, due, meeting):
    """Checks only the plainest spoken forms; any other wording ("a week from today", "before the 12th") passes."""
    plain = " ".join(re.sub(r"[^\w\s]", " ", _norm(wording)).split())
    span = (due - meeting).days
    weekday = re.fullmatch(r"(?:(by|on|this|next) )?(" + "|".join(WEEKDAYS) + ")", plain)
    if weekday:  # "by Friday" is the coming Friday; "next Friday" at most two weeks out.
        return due.weekday() == WEEKDAYS.index(weekday.group(2)) and 0 <= span <= (14 if weekday.group(1) == "next" else 7)
    relative = re.fullmatch(r"(?:by )?(today|tomorrow)", plain)
    if relative:
        return span == ("today", "tomorrow").index(relative.group(1))
    day = re.fullmatch(r"(?:by |on )?(?:the (\d{1,2})(?:st|nd|rd|th)?|(\d{1,2})(?:st|nd|rd|th))", plain)
    return not day or int(day.group(1) or day.group(2)) == due.day  # "the 12th", never a bare "by 5" (a time).


def _named(name, transcript, speakers):
    """A person the transcript names: a speaker label, or the name's words as whole words in the text."""
    if any(_same(name, s) for s in speakers):
        return True
    return bool(name) and re.search(r"(?<!\w)" + re.escape(name.split()[0]) + r"(?!\w)", transcript) is not None


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
    error = best_match(Draft7Validator(OP_SCHEMA, format_checker=FormatChecker()).iter_errors(data))
    if error:
        where = "/".join(map(str, error.absolute_path)) or "data"
        hint = (" (each action item needs text, owner, due_date YYYY-MM-DD, due_wording and a transcript quote of 8+ characters)"
                if where.startswith("action_items") else "")
        raise ValueError(f"invalid minutes at {where}: {error.message[:200]}{hint}")
    if _private(data) or clean(data) != data:
        raise ValueError("minutes must not contain card, account or phone numbers or credentials")
    source = _norm(transcript)
    turns = _turns(transcript)
    speakers = {_norm(m) for m in SPEAKER.findall(transcript)}
    people = {_norm(a) for a in data["attendees"]} | speakers
    meeting = dt.date.fromisoformat(data["meeting_date"])
    if not any(_same(_norm(data["owner_name"]), p) for p in people):
        raise ValueError("owner_name must be one of the attendees or speakers")

    def quoted(value, what, minimum=8):
        if len(_norm(value)) < minimum:
            raise ValueError(f"{what} quote is too short: {value[:80]}")
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
            raise ValueError(f"action item has no named owner (use owner_name for the owner's own items, "
                             f"or move it to open_questions): {item['text'][:80]}")
        # An owner is a speaker, or an attendee the transcript names; a word in the text is not a person.
        if not (any(_within(owner, s) for s in speakers)
                or any(_within(owner, a) for a in people) and _named(owner, source, speakers)):
            raise ValueError(f"action item owner is not a speaker or an attendee named in the transcript: {item['owner']}")
        if dt.date.fromisoformat(item["due_date"]) < meeting:
            raise ValueError(f"action item due date is before the meeting: {item['text'][:80]}")
        quoted(item["quote"], "action item")
        if _words(item["text"]) and not _words(item["text"]) & _words(item["quote"]):
            raise ValueError(f"action item quote does not mention this action: {item['text'][:80]}")
        quoted(item["due_wording"], "due wording", minimum=1)
        # Bind the item to the line its quote comes from: an "I'll ..." promise belongs to its speaker, and the
        # due wording is on that line or a following line by the same speaker or the owner.
        quote = _norm(item["quote"])
        line = next((i for i, (_, text) in enumerate(turns) if quote in text), None)
        if line is not None:
            speaker = turns[line][0]
            if speaker and COMMITMENT.search(quote) and not _same(owner, speaker):
                raise ValueError(f"action item owner {item['owner']} did not make this promise; {speaker} did: {item['text'][:80]}")
            nearby = [turns[line][1]] + [text for who, text in turns[line + 1:line + 4] if who and (who == speaker or _same(owner, who))]
            if not any(_norm(item["due_wording"]) in text for text in nearby):
                raise ValueError(f"action item due wording is not on the quote's line or a following line by its speaker "
                                 f"or owner (quote the line that holds both, or move it to open_questions): {item['text'][:80]}")
        if not _date_fits(item["due_wording"], dt.date.fromisoformat(item["due_date"]), meeting):
            raise ValueError(f"action item due_date does not match its wording \"{item['due_wording']}\": {item['text'][:80]}")
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


def _stage(root, path, text):
    """Write a private temporary beside path; the caller replaces path with it, so a failure leaves the old file."""
    legacy._validate_existing_path(root, path)
    if path.exists() and path.stat().st_nlink > 1:
        raise ValueError("minutes output must not be hard-linked")
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return temp


def _get(conn, identity):
    row = conn.execute("select * from actions where action_id=?", (identity,)).fetchone()
    return legacy.row_to_dict(row) if row else None


def _put(conn, identity, fields, status, remove=()):
    old = _get(conn, identity)
    merged = {**(old or {}).get("fields", {}), **fields}
    for key in remove:
        merged.pop(key, None)
    stamp = now()
    # A row a provider step has taken over keeps its transaction type (Ledger.put_loop_bookkeeping does the same).
    conn.execute("insert into actions values(?,?,?,?,?,?,?,?) on conflict(action_id) do update set "
                 "action_type=excluded.action_type,status=excluded.status,"
                 "fields_json=excluded.fields_json,updated_at=excluded.updated_at",
                 (identity, None, (old or {}).get("action_type") or "commitment", "", status, json.dumps(merged, ensure_ascii=False),
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
        meeting = dt.date.fromisoformat(data["meeting_date"])
        for item in data["action_items"]:
            mine = _same(_norm(item["owner"]), me)
            day = dt.date.fromisoformat(item["due_date"])
            due = dt.datetime.combine(day, dt.time(17), zone).isoformat()
            # The chase ladder counts from opened_at: someone else's item is chased from two days after its
            # due date; the owner's own item reaches its day-2 reminder on the due date.
            opened = day - dt.timedelta(days=2) if mine else day
            loops[prefix + stable_id("minutes", data["name"], _norm(item["text"]))] = {
                "title": item["text"], "loop_kind": "our_promise" if mine else "waiting_on_them",
                "counterparty": "Owner" if mine else item["owner"], "next_actor": "owner" if mine else "them",
                "opened_at": opened.isoformat(), "meeting_date": data["meeting_date"], "due_at": due,
                "next_step": f"{item['owner']}: {item['text']} by {item['due_date']}",
                "source_ref": f"minutes {data['name']}: \"{item['quote']}\""}
        record = {k: v for k, v in data.items() if k not in {"action", "path"}}
        record.update({"timezone": zone_name, "source": data["path"], "loop_ids": sorted(loops)})
        legacy._ensure_directory(ledger.root, output)
        staged = {}
        try:
            staged = {"markdown": _stage(ledger.root, paths["markdown"], _markdown(data, zone_name))}
            staged["json"] = _stage(ledger.root, paths["json"], json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            _commit(ledger, prefix, loops, staged, paths)
        finally:
            for temp in staged.values():
                temp.unlink(missing_ok=True)
        return {"paths": {k: str(p) for k, p in paths.items()}, "action_items": len(data["action_items"]),
                "decisions": len(data["decisions"]), "open_questions": len(data.get("open_questions", [])),
                "loop_ids": sorted(loops), "sent": False}
    except (ValueError, OSError, RuntimeError) as exc:
        return {"error": str(exc)}


def _commit(ledger, prefix, loops, staged, paths):
    with ledger.connect() as conn:
        conn.execute("begin immediate")
        # Item loops only: nudges and other provider actions under a loop ("<loop>:nudge:day2") are not items.
        existing = [r[0] for r in conn.execute("select action_id from actions where action_id like ?", (prefix + "%",))
                    if ":" not in r[0][len(prefix):]]
        for identity, fields in loops.items():
            old = _get(conn, identity)
            reopen = not old or old["status"] == "cancelled"
            if reopen:
                fields = {**fields, "chase_log": []}
            _put(conn, identity, fields, "open" if reopen else old["status"], remove=("loop_cancelled",) if reopen else ())
        for identity in set(existing) - set(loops):  # An item dropped on re-save stops being chased.
            old = _get(conn, identity)
            if (old and old.get("action_type") == "commitment" and old["status"] != "cancelled"
                    and not (old.get("fields") or {}).get("confirmation")):
                _put(conn, identity, {"loop_cancelled": {"by": "owner", "at": now(), "reason": "removed from the saved minutes"}}, "cancelled")
        for kind in ("markdown", "json"):  # Refuse a linked output before either file changes.
            legacy._validate_existing_path(ledger.root, paths[kind])
        for kind in ("markdown", "json"):  # A failed replace raises inside the transaction, so no loop change commits.
            os.replace(staged[kind], paths[kind])
