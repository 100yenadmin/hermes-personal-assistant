"""Short, private task evidence in the existing profile ledger."""
import hashlib
import re
import secrets
from datetime import date, datetime, timezone

from .privacy import clean
from .profile import _private
from .state import now

AREAS = ["inbox", "calendar", "travel", "errands", "phone", "research", "documents",
         "finance", "personal_admin", "customer_comms", "social", "recurring_ops"]
EVIDENCE_TYPES = {"va_task", "va_baseline", "va_day30"}
EVIDENCE_PREFIXES = ("va-task:", "va-baseline:", "va-day30:")
_STATUSES = {"pending", "pass", "fail"}


def _text(value, field, limit, *, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or len(value) > limit:
        raise ValueError(f"{field} must be non-empty text of at most {limit} characters")
    return value


def _date(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field} must be an ISO date")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} must be an ISO date") from None
    return value


def _enum(value, field, choices):
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"invalid {field}")
    return value


def _minutes(value, field):
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _keys(data, allowed):
    if set(data) - set(allowed.split()) - {"action"}:
        raise ValueError("unsupported evidence fields")


def _refused(data):
    """Credentials, card/account numbers and raw bodies stay out. Free text must survive clean() unchanged; source URLs
    and task-type names need only be free of credential and card patterns, because clean() also rewrites login paths and
    drops words such as "passport" that are ordinary in evidence."""
    facts = data.get("facts") if isinstance(data.get("facts"), list) else []
    free = {k: data[k] for k in ("title", "agreed_outcome", "correction_note") if isinstance(data.get(k), str)}
    free["items"] = [f["item"] for f in facts if isinstance(f, dict) and isinstance(f.get("item"), str)]
    keys = list(data["minutes_by_type"]) if isinstance(data.get("minutes_by_type"), dict) else []
    return clean(free) != free or _private(data) or _private(keys)


def _tasks(ledger):
    rows = [r for r in ledger.list("action")
            if r["action_type"] == "va_task" and r["action_id"].startswith("va-task:")]
    return [{"identity": r["action_id"], **r["fields"]}
            for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]


def _profile(ledger):
    """A random id for this profile's evidence, so one ledger exported under two owner labels is caught."""
    rows = [r for r in ledger.list("action") if r["action_type"] in EVIDENCE_TYPES and r["fields"].get("profile")]
    return rows[0]["fields"]["profile"] if rows else None


def _save(ledger, identity, fields, row_type):
    fields = {**fields, "profile": fields.get("profile") or _profile(ledger) or secrets.token_hex(6)}
    # The ledger stores clean() output. Refuse what it would change, so evidence is never silently lost.
    changed = sorted(k for k, v in fields.items() if clean({k: v}) != {k: v})
    if changed:
        raise ValueError(f"evidence would be stored redacted ({', '.join(changed)}); rephrase it without login, "
                         "tracking or private-looking parts, e.g. cite the page title and site, or rename the task type")
    ledger.put("action", identity, fields, action_type=row_type,
               status=fields["status"] if row_type == "va_task" else "recorded",
               remove=("closed_at",) if row_type == "va_task" and "closed_at" not in fields else ())
    return {"identity": identity, **ledger.get("action", identity)["fields"]}  # What was stored, never what was sent.


def dispatch(ledger, data):
    if _refused(data):
        raise ValueError("evidence records prohibit credentials, card/account/passport numbers and raw message bodies")
    action = data.get("action")
    if action == "record":
        _keys(data, "area title due agreed_outcome started cohort task_id")
        fields = {"area": _enum(data.get("area"), "area", AREAS),
                  "title": _text(data.get("title"), "title", 120),
                  "due": _date(data.get("due"), "due"),
                  "agreed_outcome": _text(data.get("agreed_outcome"), "agreed_outcome", 200),
                  # Without an explicit owner-local start, never start after the due date (UTC runs ahead of the Americas).
                  "started": _date(data["started"], "started") if "started" in data
                  else min(datetime.now(timezone.utc).date().isoformat(), _date(data.get("due"), "due")),
                  "cohort": _text(data.get("cohort", "default"), "cohort", 40),
                  "status": "pending", "owner_accepted": None, "correction": "none",
                  "facts": [], "created_at": now()}
        if fields["due"] < fields["started"]:
            raise ValueError("due must not be before started")  # The scorecard rejects such tasks.
        slug = re.sub(r"[^a-z0-9]+", "-", fields["title"].lower()).strip("-")
        digest = hashlib.sha1(fields["title"].encode()).hexdigest()[:6]  # Titles in any script stay distinct.
        task_id = data.get("task_id", (slug[:40].rstrip("-") or "task") + "-" + digest + "-" + fields["started"])
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-z0-9-]{3,60}", task_id):
            raise ValueError("task_id must be a slug of 3-60 characters")
        identity = "va-task:" + task_id
        if ledger.get("action", identity):
            raise ValueError(f"evidence task exists ({identity}): for this same task use update with that identity; "
                             "for a different task, record it with a more specific title or its own task_id")
        return _save(ledger, identity, fields, "va_task")
    if action == "update":
        _keys(data, "identity status owner_accepted correction correction_note facts due agreed_outcome title closed_on")
        identity = data.get("identity")
        if not isinstance(identity, str) or not identity.startswith("va-task:"):
            raise ValueError("evidence task not found")
        row = ledger.get("action", identity)
        if not row or row["action_type"] != "va_task":
            raise ValueError("evidence task not found")
        fields = dict(row["fields"])
        for key, limit in (("title", 120), ("agreed_outcome", 200), ("correction_note", 160)):
            if key in data:
                fields[key] = _text(data[key], key, limit, allow_empty=key == "correction_note")
        if "due" in data:
            fields["due"] = _date(data["due"], "due")
            if fields["due"] < fields["started"]:
                raise ValueError("due must not be before started")
        if "status" in data:
            fields["status"] = _enum(data["status"], "status", _STATUSES)
            fields.pop("closed_at", None)
            if fields["status"] != "pending":
                # The owner-local close date, like started and due: a UTC date runs a day off either side of it.
                if "closed_on" not in data:
                    raise ValueError("closed_on (the owner's local date) is required to close a task")
                fields["closed_at"] = _date(data["closed_on"], "closed_on")
                if fields["closed_at"][:10] < fields["started"]:
                    raise ValueError("closed_on must not be before started")
        if "owner_accepted" in data:
            if data["owner_accepted"] is not None and type(data["owner_accepted"]) is not bool:
                raise ValueError("owner_accepted must be bool or null")
            fields["owner_accepted"] = data["owner_accepted"]
        if "correction" in data:
            fields["correction"] = _enum(data["correction"], "correction", {"none", "minor", "material"})
        if "facts" in data:
            facts = data["facts"]
            if not isinstance(facts, list) or len(facts) > 20:
                raise ValueError("facts must be a list of at most 20 items")
            for fact in facts:
                if not isinstance(fact, dict) or set(fact) != {"item", "source", "ok", "facing"}:
                    raise ValueError("fact requires item, source, ok and facing")
                _text(fact["item"], "fact.item", 120)
                _text(fact["source"], "fact.source", 200)
                if type(fact["ok"]) is not bool:
                    raise ValueError("fact.ok must be bool")
                _enum(fact["facing"], "fact.facing", {"money", "customer", "internal"})
            fields["facts"] = facts
        return _save(ledger, identity, fields, "va_task")
    if action == "list":
        _keys(data, "area status")
        if "area" in data:
            _enum(data["area"], "area", AREAS)
        if "status" in data:
            _enum(data["status"], "status", _STATUSES)
        return [r for r in _tasks(ledger) if all(r[k] == data[k] for k in ("area", "status") if k in data)][:50]
    if action == "baseline":
        _keys(data, "week_of minutes_by_type")
        minutes = data.get("minutes_by_type")
        if not isinstance(minutes, dict) or len(minutes) > 12:
            raise ValueError("minutes_by_type must contain at most 12 entries")
        for key, value in minutes.items():
            _text(key, "task type", 60)
            _minutes(value, "minutes_by_type")
        if not sum(minutes.values()):
            raise ValueError("baseline needs the minutes spent on at least one delegated task type")  # Day-30 divides by it.
        fields = {"week_of": _date(data.get("week_of"), "week_of"), "minutes_by_type": minutes,
                  "total_minutes": sum(minutes.values()), "recorded_at": now()}
        return _save(ledger, "va-baseline:owner", fields, "va_baseline")
    if action == "day30":
        _keys(data, "week_ending minutes first_pass_task_types")
        types = data.get("first_pass_task_types")
        if not isinstance(types, list) or len(types) > 12:
            raise ValueError("first_pass_task_types must contain at most 12 strings")
        for value in types:
            _text(value, "first_pass_task_types", 60)
        fields = {"week_ending": _date(data.get("week_ending"), "week_ending"),
                  "minutes": _minutes(data.get("minutes"), "minutes"),
                  "first_pass_task_types": types, "recorded_at": now()}
        return _save(ledger, "va-day30:owner", fields, "va_day30")
    if action == "export":
        _keys(data, "owner")
        owner = _text(data.get("owner", "owner"), "owner", 40)
        keys = "area title started due status owner_accepted correction facts".split()
        result = {"tasks": [{"id": r["identity"][len("va-task:"):], "owner": owner, **{k: r[k] for k in keys},
                             **({"closed_at": r["closed_at"]} if r.get("closed_at") else {})} for r in _tasks(ledger)],
                  "baselines": {}, "day30": {}, "profile": _profile(ledger)}
        for name, prefix, keys in (("baselines", "va-baseline:", "week_of minutes_by_type total_minutes"),
                                   ("day30", "va-day30:", "week_ending minutes first_pass_task_types")):
            row = ledger.get("action", prefix + "owner")
            if row:
                result[name][owner] = {k: row["fields"][k] for k in keys.split()}
        return result
    raise ValueError("unknown evidence action")
