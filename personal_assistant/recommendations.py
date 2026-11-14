"""Retire unanswered Chief of Staff notes without recording an outcome."""
import datetime as dt

from jsonschema import Draft7Validator, FormatChecker

from .context import evaluation_moment, local_time, owner_zone
from .radar import STALE_AFTER_DAYS

OP_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["action"],
    "properties": {
        "action": {"const": "retire"},
        "preview": {"type": "boolean", "default": True},
        "action_ids": {"type": "array", "minItems": 1, "maxItems": 100,
                       "items": {"type": "string"}},
        "by": {"enum": ["owner", "agent"]},
        "at": {"type": "string", "format": "date-time",
               "pattern": r"^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$"},
    },
    "allOf": [{"if": {"required": ["preview"], "properties": {"preview": {"const": False}}},
               "then": {"required": ["action_ids", "by"]}}],
}


def validate(data):
    valid = Draft7Validator(OP_SCHEMA, format_checker=FormatChecker()).is_valid(data)
    if valid:
        try:
            evaluation_moment(data)  # date-time checking may be an optional jsonschema dependency.
        except (ValueError, OverflowError):
            valid = False
    if not valid:
        raise ValueError("invalid recommendations call: action retire; accepted keys: action, preview, "
                         "action_ids, by, at; preview defaults true; preview false requires "
                         "action_ids (1 to 100 strings) and by owner|agent; at is ISO with offset")


def _skip(action, moment, zone):
    if action is None:
        return "not_found"
    fields = action.get("fields", {})
    if not action["action_id"].startswith("cos:") or action.get("action_type") != "note":
        return "not_a_recommendation"
    if isinstance(fields.get("retired"), dict):
        return "already_retired"
    if fields.get("outcome") != "unknown":
        return "outcome_recorded"
    review_at = local_time(fields.get("review_at"), zone)
    if review_at is None or review_at >= moment:
        return "not_yet_due"
    return None


def dispatch(ledger, data):
    validate(data)
    moment, zone = evaluation_moment(data), owner_zone(ledger)
    preview = data.get("preview", True)
    identities = data.get("action_ids")
    if identities is None:
        actions = ledger.list("action") if ledger.path.exists() else []
        stale = [row for row in actions if _skip(row, moment, zone) is None
                 and moment - local_time(row["fields"]["review_at"], zone) > dt.timedelta(days=STALE_AFTER_DAYS)]
        stale.sort(key=lambda row: (local_time(row["fields"]["review_at"], zone), row["action_id"]))
        identities = [row["action_id"] for row in stale]
    retired, would_retire, skipped = [], [], []
    stamp = moment.isoformat()
    for identity in identities:
        action = ledger.get("action", identity)
        reason = _skip(action, moment, zone)
        if reason:
            skipped.append({"action_id": identity, "reason": reason})
            continue
        fields = action["fields"]
        if preview:
            would_retire.append({"action_id": identity, **{
                key: fields.get(key) for key in ("title", "cos_skill", "review_at")}})
            continue
        history = fields.get("history") if isinstance(fields.get("history"), list) else []
        ledger.put("action", identity, {
            "retired": {"at": stamp, "by": data["by"], "reason": "no outcome recorded"},
            "history": history + [{"at": stamp, "event": "retired", "by": data["by"]}],
        })
        retired.append(identity)
    rows = would_retire if preview else retired
    return {"preview": preview, "would_retire" if preview else "retired": rows,
            "skipped": skipped, "count": len(rows)}
