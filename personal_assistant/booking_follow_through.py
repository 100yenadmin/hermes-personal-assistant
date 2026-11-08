"""Bookkeeping sourced only from a confirmed provider readback."""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .privacy import clean
from .expenses import SCHEMA as EXPENSE_SCHEMA, from_readback, save as save_expense


FOLLOW_THROUGH_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "anyOf": [{"required": [key]} for key in ("item", "loop", "expense", "replaces")],
    "properties": {
        "replaces": {"type": "string", "minLength": 1},
        "expense": EXPENSE_SCHEMA,
        "trip_id": {"type": "string", "minLength": 1},
        "item": {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "title", "start", "timezone"],
            "properties": {
                "kind": {"type": "string", "enum": ["hotel", "restaurant", "flight", "transfer", "activity", "other", "appointment", "delivery", "errand"]},
                **{key: {"type": "string", "minLength": 1} for key in ("title", "start", "end", "timezone")},
                "location": {"type": "string"}, "reference": {"type": "string"},
            },
        },
        "loop": {
            "type": "object", "additionalProperties": False, "required": ["counterparty", "next_step"],
            "properties": {key: {"type": "string", "minLength": 1} for key in
                           ("counterparty", "next_step", "title", "snoozed_until")},
        },
        "reminders": {
            "type": "array", "maxItems": 3,
            "items": {"type": "object", "additionalProperties": False,
                      "required": ["label", "due_at"],
                      "properties": {key: {"type": "string", "minLength": 1} for key in ("label", "due_at")}},
        },
    },
}


def _object(value, allowed, required, field):
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    for key in value:
        if key not in allowed:
            raise ValueError(f"{field}.{key} is unknown")
    for key in required:
        if key not in value:
            raise ValueError(f"{field}.{key} is required")


def _text(value, field, *, required=True):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{field} must be a {'nonempty ' if required else ''}string")


def _time(value, field):
    _text(value, field)
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} must be an ISO 8601 time with offset") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must carry an offset")
    return parsed


def validate(ledger, current, value, verified_at=None):
    """Refuse the whole readback before any result or follow-through write."""
    from .state import now
    _object(value, {"trip_id", "item", "reminders", "loop", "expense", "replaces"}, set(), "follow_through")
    if not {"item", "loop", "expense", "replaces"}.intersection(value):
        raise ValueError("follow_through requires item or loop or expense or replaces")
    item = value.get("item")
    if "item" in value:
        schema = FOLLOW_THROUGH_SCHEMA["properties"]["item"]
        _object(item, schema["properties"], schema["required"], "item")
        for key in item:
            _text(item[key], f"item.{key}", required=key not in {"location", "reference"})
        if item["kind"] not in schema["properties"]["kind"]["enum"]:
            raise ValueError("item.kind is invalid")
        try:
            ZoneInfo(item["timezone"])
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("item.timezone must be a valid IANA zone") from None
        start = _time(item["start"], "item.start")
        if "end" in item and _time(item["end"], "item.end") <= start:
            raise ValueError("item.end must be later than item.start")
    if item is None and "reminders" in value:
        raise ValueError("reminders require item.start")
    loop = value.get("loop")
    if "loop" in value:
        row_id = str((current or {}).get("action_id") or "")
        if ":nudge:" in row_id or ((current or {}).get("fields") or {}).get("loop_kind"):
            # A second ladder for the same counterparty would chase them twice.
            raise ValueError("a nudge or a step on an existing loop records a chase on that loop, not a new loop")
        schema = FOLLOW_THROUGH_SCHEMA["properties"]["loop"]
        _object(loop, schema["properties"], schema["required"], "loop")
        for key in loop:
            _text(loop[key], f"loop.{key}")
        if "snoozed_until" in loop:
            snooze = _time(loop["snoozed_until"], "loop.snoozed_until")
            if not dt.timedelta(0) < snooze - dt.datetime.fromisoformat(now()) <= dt.timedelta(days=30):
                raise ValueError("loop.snoozed_until must be later than now and within 30 days")
    reminders = value.get("reminders", [])
    if not isinstance(reminders, list) or len(reminders) > 3:
        raise ValueError("reminders must contain 0 to 3 reminders")
    for n, reminder in enumerate(reminders, 1):
        field = f"reminders[{n}]"
        _object(reminder, {"label", "due_at"}, {"label", "due_at"}, field)
        _text(reminder["label"], f"{field}.label")
        due = _time(reminder["due_at"], f"{field}.due_at")
        if not dt.timedelta(0) < start - due <= dt.timedelta(days=30):
            raise ValueError(f"{field}.due_at must be before item.start and within 30 days")
    row_trip = (current or {}).get("trip_id")
    recorded = ((current or {}).get("fields") or {}).get("booking_trip_id")
    supplied = value.get("trip_id")
    if "trip_id" in value:
        _text(supplied, "follow_through.trip_id")
        if row_trip and supplied != row_trip:
            raise ValueError("follow_through.trip_id differs from action.trip_id")
        if recorded and supplied != recorded:
            raise ValueError("follow_through.trip_id differs from the trip this booking was recorded on")
        if not ledger.get("trip", supplied):
            raise ValueError("follow_through.trip_id must name an existing trip")
    trip_id = row_trip or supplied or recorded
    if trip_id and not ledger.get("trip", trip_id):
        raise ValueError("action.trip_id must name an existing trip")
    replaces = value.get("replaces")
    if "replaces" in value:
        _text(replaces, "follow_through.replaces")
        if replaces == (current or {}).get("action_id"):
            raise ValueError("follow_through.replaces must name a different action")
        old = ledger.get("action", replaces)
        trips = [t for t in ledger.list("trip") if any(
            e.get("booking_action_id") == replaces for e in t["fields"].get("events", []))]
        # An event-only booking's link is its recorded booking evidence after removal.
        replay = old and current and old["fields"].get("replaced_by") == current["action_id"]
        if not old or not (old["fields"].get("booked_item") or trips or replay):
            raise ValueError("follow_through.replaces must name an existing recorded booking")
        if old["fields"].get("replaced_by") not in {None, (current or {}).get("action_id")}:
            raise ValueError("follow_through.replaces is already replaced by another action")
        old_trip = old["fields"].get("booking_trip_id") or old.get("trip_id")
        if trip_id and (old_trip and old_trip != trip_id or any(t["trip_id"] != trip_id for t in trips)):
            raise ValueError("follow_through.replaces belongs to a different trip")
    expense = None
    if "expense" in value:
        expense = from_readback(value["expense"], item, (current or {}).get("action_id"), verified_at or now(), trip_id)
    return clean(item), clean(reminders), trip_id, clean(loop), expense, replaces


_HANDLED = {"completed", "confirmed", "dismissed"}


def complete(ledger, identity, item, reminders, trip_id, loop=None, expense=None, replaces=None):
    from .trips import add_booked_item, export_booked_item
    from .daily_ops import config

    expense_id = f"{identity}:expense" if expense is not None else None
    if expense is not None:
        stored = ledger.get("action", expense_id)
        expense_trip = trip_id or (stored or {}).get("fields", {}).get("trip_ref")
        save_expense(ledger, expense_id, expense, "provider_readback", identity, expense_trip)
    cancelled_reminders = []
    if replaces is not None:
        # This internal write owns only the replacement link, including on governed rows.
        with ledger.connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute("select fields_json from actions where action_id=?", (replaces,)).fetchone()
            fields = json.loads(row["fields_json"])
            if fields.get("replaced_by") != identity:
                fields["replaced_by"] = identity
                from .state import now
                conn.execute("update actions set fields_json=?,updated_at=? where action_id=?",
                             (json.dumps(fields, ensure_ascii=False), now(), replaces))
        for trip in ledger.list("trip"):
            events = trip["fields"].get("events", [])
            kept = [e for e in events if e.get("booking_action_id") != replaces]
            if len(kept) != len(events):
                ledger.put("trip", trip["trip_id"], {"events": kept})
        for n in range(1, 4):
            reminder_id = f"{replaces}:reminder:{n}"
            old = ledger.get("action", reminder_id)
            if old and old["status"] not in _HANDLED | {"cancelled"}:
                ledger.put("action", reminder_id, {}, status="cancelled")
                cancelled_reminders.append(reminder_id)
    trip_item = add_booked_item(ledger, trip_id, item, identity) if item is not None and trip_id else None
    reminder_ids = []
    for n in (range(1, 4) if item is not None else ()):
        reminder_id = f"{identity}:reminder:{n}"
        if n <= len(reminders):
            reminder = reminders[n - 1]
            fields = {"title": reminder["label"], "due_at": reminder["due_at"],
                      "timezone": item["timezone"], "booking_action_id": identity, "reminder_kind": "booking"}
            if trip_id:
                fields["trip_ref"] = trip_id
            old = ledger.get("action", reminder_id)
            # A reminder the owner already handled stays handled unless its time changed.
            keep = old and old["status"] in _HANDLED and old["fields"].get("due_at") == reminder["due_at"]
            ledger.put("action", reminder_id, fields, action_type="commitment", status=None if keep else "pending",
                       remove=[] if trip_id else ["trip_ref"])
            reminder_ids.append(reminder_id)
        else:
            old = ledger.get("action", reminder_id)
            if old and old["status"] not in _HANDLED | {"cancelled"}:
                ledger.put("action", reminder_id, {}, status="cancelled")
    ics_path = export_booked_item(ledger, identity, item) if item is not None else None
    try:
        # pa-setup writes daily_ops.config.json in the profile; the plugin process does not run from there.
        path = os.environ.get("DAILY_OPS_CONFIG") or str(ledger.root / "daily_ops.config.json")
        cfg = config.load_config(path) if item is not None else {}
        scope = cfg.get("calendar", {}).get("write_scope", {})
        # Only a configuration daily-ops itself accepts grants a write, and only to its consented calendars.
        allowed = scope.get("accepted") is True and not config.validate_config(cfg)
        calendar_ids = list(scope["calendar_ids"]) if allowed else []
    except Exception:
        # A missing, malformed or unreadable config never grants calendar scope.
        allowed = False
        calendar_ids = []
    loop_id = f"{identity}:loop" if loop is not None else None
    tracked = False
    if loop is not None:
        old = ledger.get("action", loop_id)
        fields = old["fields"] if old else {}
        closed = old and ("confirmation" in fields or "loop_cancelled" in fields
                          or old["status"] in {"completed", "cancelled", "dismissed"})
        if not closed and old and old["action_type"] == "transaction":
            # A step prepared on the loop's own row now owns it; refresh only the chase bookkeeping it allows.
            ledger.put_loop_bookkeeping(loop_id, {k: loop[k] for k in ("next_step", "snoozed_until") if k in loop})
            tracked = True
        elif not closed:
            refresh = {**loop, "title": loop.get("title", f"Waiting on {loop['counterparty']}")}
            if not old:
                refresh.update(loop_kind="waiting_on_them", next_actor="them", chase_log=[],
                               opened_at=ledger.get("action", identity)["fields"]["verified_at"], source_action_id=identity)
            ledger.put("action", loop_id, refresh, action_type="commitment", status=None if old else "open",
                       remove=[] if "snoozed_until" in loop else ["snoozed_until"], trip_id=trip_id)
            tracked = True
    result = {
        "trip_item": trip_item, "trip_note": ("no item in this readback" if item is None else
                                             f"added to {trip_id}" if trip_id else "no trip on this action"),
        "reminders": reminder_ids, "ics_path": ics_path, "calendar_write_allowed": allowed, "calendar_ids": calendar_ids,
        "loop_id": loop_id, "expense_id": expense_id,
        "replaced": replaces, "cancelled_reminders": cancelled_reminders,
        "next_step": (
            "Create a private event on one of calendar_ids with these exact fields (no attendees, no notifications), read it back, then record it with action_upsert."
            if allowed else
            "Calendar write is not granted: give the owner the ICS file and say the booking is not on their calendar yet."
        ),
    }
    if item is None:
        result["next_step"] = ""
    if tracked:
        result["next_step"] = (result["next_step"] + " The reply is now tracked and chased on the usual ladder.").strip()
    return result
