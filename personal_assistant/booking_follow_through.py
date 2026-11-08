"""Bookkeeping sourced only from a confirmed provider readback."""
import datetime as dt
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .privacy import clean


FOLLOW_THROUGH_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
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


def validate(ledger, current, value):
    """Refuse the whole readback before any result or follow-through write."""
    from .state import now
    _object(value, {"trip_id", "item", "reminders", "loop"}, set(), "follow_through")
    if not {"item", "loop"}.intersection(value):
        raise ValueError("follow_through requires item or loop")
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
    return clean(item), clean(reminders), trip_id, clean(loop)


_HANDLED = {"completed", "confirmed", "dismissed"}


def complete(ledger, identity, item, reminders, trip_id, loop=None):
    from .trips import add_booked_item, export_booked_item
    from .daily_ops import config

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
        if not closed:
            refresh = {**loop, "title": loop.get("title", f"Waiting on {loop['counterparty']}")}
            if not old:
                refresh.update(loop_kind="waiting_on_them", next_actor="them", chase_log=[],
                               opened_at=ledger.get("action", identity)["fields"]["verified_at"], source_action_id=identity)
            ledger.put("action", loop_id, refresh, action_type="commitment", status=None if old else "open",
                       remove=[] if "snoozed_until" in loop else ["snoozed_until"])
            tracked = True
    result = {
        "trip_item": trip_item, "trip_note": ("no item in this readback" if item is None else
                                             f"added to {trip_id}" if trip_id else "no trip on this action"),
        "reminders": reminder_ids, "ics_path": ics_path, "calendar_write_allowed": allowed, "calendar_ids": calendar_ids,
        "loop_id": loop_id,
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
