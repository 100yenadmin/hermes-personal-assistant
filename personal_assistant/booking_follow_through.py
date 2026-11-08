"""Bookkeeping sourced only from a confirmed provider readback."""
import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .privacy import clean


FOLLOW_THROUGH_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["item"],
    "properties": {
        "trip_id": {"type": "string", "minLength": 1},
        "item": {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "title", "start", "timezone"],
            "properties": {
                "kind": {"type": "string", "enum": ["hotel", "restaurant", "flight", "transfer", "activity", "other"]},
                **{key: {"type": "string", "minLength": 1} for key in ("title", "start", "end", "timezone")},
                "location": {"type": "string"}, "reference": {"type": "string"},
            },
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
    _object(value, {"trip_id", "item", "reminders"}, {"item"}, "follow_through")
    item = value["item"]
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
    supplied = value.get("trip_id")
    if "trip_id" in value:
        _text(supplied, "follow_through.trip_id")
        if row_trip and supplied != row_trip:
            raise ValueError("follow_through.trip_id differs from action.trip_id")
        if not ledger.get("trip", supplied):
            raise ValueError("follow_through.trip_id must name an existing trip")
    trip_id = row_trip or supplied
    if trip_id and not ledger.get("trip", trip_id):
        raise ValueError("action.trip_id must name an existing trip")
    return clean(item), clean(reminders), trip_id


def complete(ledger, identity, item, reminders, trip_id):
    from .trips import add_booked_item, export_booked_item
    from .daily_ops import config

    trip_item = add_booked_item(ledger, trip_id, item, identity) if trip_id else None
    reminder_ids = []
    for n in range(1, 4):
        reminder_id = f"{identity}:reminder:{n}"
        if n <= len(reminders):
            reminder = reminders[n - 1]
            fields = {"title": reminder["label"], "due_at": reminder["due_at"],
                      "timezone": item["timezone"], "booking_action_id": identity, "reminder_kind": "booking"}
            if trip_id:
                fields["trip_ref"] = trip_id
            ledger.put("action", reminder_id, fields, action_type="commitment", status="pending",
                       remove=[] if trip_id else ["trip_ref"])
            reminder_ids.append(reminder_id)
        elif ledger.get("action", reminder_id):
            ledger.put("action", reminder_id, {}, status="cancelled")
    ics_path = export_booked_item(ledger, identity, item)
    try:
        allowed = config.load_config().get("calendar", {}).get("write_scope", {}).get("accepted") is True
    except Exception:
        # A missing, malformed or unreadable config never grants calendar scope.
        allowed = False
    return {
        "trip_item": trip_item, "trip_note": f"added to {trip_id}" if trip_id else "no trip on this action",
        "reminders": reminder_ids, "ics_path": ics_path, "calendar_write_allowed": allowed,
        "next_step": (
            "Create a private event on the owner's calendar with these exact fields (no attendees, no notifications), read it back, then record it with action_upsert."
            if allowed else
            "Calendar write is not granted: give the owner the ICS file and say the booking is not on their calendar yet."
        ),
    }
