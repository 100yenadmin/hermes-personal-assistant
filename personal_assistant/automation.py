"""Local-only PA cron suggestions, prechecks, and notification receipts."""
import datetime as dt
import json
from zoneinfo import ZoneInfo
from .privacy import clean
from .state import Ledger, stable_id

DEFAULTS = {
    "brief_time": "08:00",
    "cos_daily_time": "09:30",
    "cos_weekly_day": "mon",
    "cos_weekly_time": "10:00",
    "quiet_hours": {"start": "22:00", "end": "07:00"},
    "due_interval_minutes": 5,
    "travel_source_refresh_minutes": 15,
    "normal_source_refresh_minutes": 360,
    "inbox_refresh_minutes": 30,
    "authenticated_guides": "manual",
}
_SKILLS = {
    "cos_daily": ["personal-assistant:cos-daily"],
    "cos_weekly": ["personal-assistant:cos-weekly", "personal-assistant:cos-radar"],
    "daily_brief": [
        "personal-assistant:r5-brief-reminders",
        "personal-assistant:daily-ops",
    ],
    "due_source_check": [
        "personal-assistant:itinerary-intake",
        "personal-assistant:travel-email-calendar",
        "personal-assistant:provider-message-refund",
        "personal-assistant:daily-ops",
    ],
}
COS_JOBS = {"cos_daily": "personal-assistant-cos-daily", "cos_weekly": "personal-assistant-cos-weekly"}
_TERMINAL_RECEIPTS = {"delivered", "suppressed", "unknown"}

def _value_time(value, timezone):
    """Parse an ISO timestamp or date, returning an aware datetime."""
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, dt.date):
        parsed = dt.datetime.combine(value, dt.time())
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = dt.datetime.combine(dt.date.fromisoformat(text), dt.time())
            except ValueError:
                return None
    zone = ZoneInfo(timezone)
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed
def _now(value, timezone):
    if callable(value):
        value = value()
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if not isinstance(value, dt.datetime):
        value = _value_time(value, timezone)
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(timezone))
    return value
def _canonical_kind(value):
    key = str(value or "").strip().lower().replace(" ", "_")
    return key if key in _SKILLS else ""
def _rule_data(item):
    """Flatten an action row or a direct rule without losing source identity."""
    if not isinstance(item, dict):
        return {}
    base = dict(item)
    fields = item.get("fields", {})
    if isinstance(fields, dict):
        base = {**fields, **{k: v for k, v in item.items() if k != "fields"}}
        nested = fields.get("automation_rule")
        if isinstance(nested, dict):
            base = {**base, **nested}
    if isinstance(item.get("automation_rule"), dict): base = {**base, **item["automation_rule"]}
    return base
def _accepted(rule):
    return rule.get("accepted") is True
def _destination(rule, default, default_verified):
    value = rule.get("destination", default); verified = rule.get("destination_verified")
    if verified is None and isinstance(value, dict):
        verified = value.get("verified") is True
        value = value.get("target") or value.get("destination")
    if verified is None:
        verified = default_verified
    if isinstance(value, str):
        value = value.strip()
    return value, verified is True
def _timezone(rule, default):
    value = rule.get("timezone", default)
    if not isinstance(value, str) or not value.strip():
        return None, "timezone is required"
    try:
        ZoneInfo(value)
    except Exception:
        return None, f"invalid timezone: {value}"
    return value, None
def source_rule_fields(rule):
    """Return canonical rule fields suitable for an existing action record."""
    data = _rule_data(rule)
    kind = _canonical_kind(data.get("kind"))
    if not kind:
        raise ValueError("automation rule kind is required")
    canonical = {"kind": kind, "accepted": data.get("accepted") is True, "destination": data.get("destination"), "destination_verified": data.get("destination_verified", False) is True, "timezone": data.get("timezone"), "source_ref": data.get("source_ref"), "snooze_until": data.get("snooze_until"), "trip_end": data.get("trip_end")}
    for key in (
        "source_type", "last_checked_at", "due_at", "on_request",
        "refresh_interval_minutes", "paused", "profile_id", "account",
        "accepted_at", "verified_at", "receipt_reference", "rule_revision", "revision",
    ):
        if key in data:
            canonical[key] = data[key]
    canonical = {key: value for key, value in canonical.items() if value is not None}
    return {
        "automation_rule": clean(canonical),
        "automation_kind": kind,
        "automation_accepted": canonical["accepted"],
        "automation_destination_verified": canonical.get("destination_verified", False),
    }
def attach_automation_rule(ledger, action_id, rule):
    """Attach a rule to an existing ledger action; commitment status is untouched."""
    row = ledger.get("action", action_id)
    if not row:
        raise ValueError("action not found")
    return ledger.put("action", action_id, source_rule_fields(rule))
def upsert_automation_rule(ledger, rule_id, rule):
    """Store an accepted rule as a ledger action, without creating a job."""
    fields = source_rule_fields(rule)
    fields["automation_rule_id"] = str(rule_id)
    action_id = ledger.action_id("pa-automation-rule", "rule", str(rule_id))
    return ledger.put(
        "action", action_id, fields, status="configured", action_type="automation_rule", provider="local"
    )
def _trip_active(trips, current):
    for trip in trips or []:
        fields = trip.get("fields", trip) if isinstance(trip, dict) else {}
        if fields.get("active_travel") is True or fields.get("travel_active") is True:
            return True
        if trip.get("status") not in (None, "active"):
            continue
        end = fields.get("end_date") or fields.get("trip_end")
        start = fields.get("start_date") or fields.get("trip_start")
        if end:
            parsed = _value_time(end, fields.get("timezone", "UTC")); began = _value_time(start, fields.get("timezone", "UTC")) if start else None
            if parsed and current <= parsed and (not start or began and current >= began): return True
        elif fields.get("events"):
            events = fields["events"]
            starts = [_value_time(e["start"], e.get("timezone", "UTC")) for e in events if e.get("start")]
            ends = [_value_time(e.get("end") or e["start"], e.get("timezone", "UTC")) for e in events if e.get("start")]
            if starts and min(starts) <= current <= max(ends): return True
    return False
def _rules_from(source, ledger=None):
    if ledger is not None:
        return ledger.list("action"), ledger.list("trip")
    if isinstance(source, Ledger):
        return source.list("action"), source.list("trip")
    if isinstance(source, dict):
        if source.get("kind"):
            return [source], []
        return source.get("rules", source.get("actions", [])), source.get("trips", [])
    return list(source or []), []
def _due_sources(sources, current, active=False):
    due, default = [], DEFAULTS["travel_source_refresh_minutes"] if active else DEFAULTS["normal_source_refresh_minutes"]
    for source in sources or []:
        source = _rule_data(source); ref = source.get("source_ref")
        if source.get("accepted") is not True or not ref or source.get("on_request") is True or source.get("source_type") == "authenticated_guide" or source.get("paused") is True: continue
        zone = source.get("timezone", "UTC"); due_at, checked = source.get("due_at"), source.get("last_checked_at")
        due_time = _value_time(due_at, zone) if due_at else None; last = _value_time(checked, zone) if checked else None
        interval = DEFAULTS["inbox_refresh_minutes"] if source.get("source_type") == "inbox" else default
        if (due_time and due_time <= current) or not checked or (last and current >= last + dt.timedelta(minutes=int(source.get("refresh_interval_minutes", interval)))): due.append(ref)
    return due
def _due_actions(actions, current):
    terminal = {"paused", "completed", "confirmed", "failed", "cancelled", "dismissed"}
    for action in actions or []:
        fields = action.get("fields", action) if isinstance(action, dict) else {}
        if action.get("status") in terminal or fields.get("status") in terminal: continue
        due_at = fields.get("due_at", action.get("due_at")); zone = fields.get("timezone", "UTC")
        if fields.get("due") is True or (due_at and _value_time(due_at, zone) and _value_time(due_at, zone) <= current): return True
    return False
def suggest_automation_jobs(source=None, *, destination=None, destination_verified=False,
                            timezone=None, now=None, ledger=None, chief_of_staff=False):
    """Build inert native cron suggestions from accepted rules and enabled modes."""
    raw_rules, trips = _rules_from(source, ledger)
    # Use UTC solely to inspect explicit trip dates when no configured timezone exists.
    current = _now(now, timezone or "UTC")
    grouped, missing, seen = {}, [], set()
    for item in raw_rules:
        rule = _rule_data(item)
        kind = _canonical_kind(rule.get("kind"))
        if kind in COS_JOBS and chief_of_staff is not True:
            continue
        if not kind or not _accepted(rule):
            continue
        identity = str(rule.get("automation_rule_id", rule.get("source_ref", item.get("action_id", len(seen)))))
        if identity in seen:
            continue
        seen.add(identity)
        tz, error = _timezone(rule, timezone)
        target, verified = _destination(rule, destination, destination_verified)
        if error:
            missing.append(f"{kind}: {error}")
        if not target:
            missing.append(f"{kind}: destination is required")
        elif not verified:
            missing.append(f"{kind}: destination must be explicitly verified")
        if error or not target or not verified:
            continue
        grouped.setdefault(kind, {"rules": [], "sources": [], "timezone": tz, "destination": target})
        entry = grouped[kind]
        if entry["timezone"] != tz:
            missing.append(f"{kind}: conflicting timezones")
            continue
        if entry["destination"] != target:
            missing.append(f"{kind}: conflicting destinations")
            continue
        entry["rules"].append(identity)
        source_ref = rule.get("source_ref")
        if source_ref and source_ref not in entry["sources"]:
            entry["sources"].append(source_ref)
    active = _trip_active(trips, current)
    jobs = []
    for kind in ("daily_brief", "due_source_check", *COS_JOBS):
        if kind not in grouped:
            continue
        entry = grouped[kind]
        settings = {
            "quiet_hours": dict(DEFAULTS["quiet_hours"]),
            "source_refresh_minutes": DEFAULTS["travel_source_refresh_minutes"] if active else DEFAULTS["normal_source_refresh_minutes"],
            "inbox_refresh_minutes": DEFAULTS["inbox_refresh_minutes"],
            "authenticated_guides": DEFAULTS["authenticated_guides"],
        }
        if kind in COS_JOBS:
            schedule, name = "*/5 * * * *", COS_JOBS[kind]
            skills = _SKILLS[kind]
            prompt = f"Load skill {skills[0]} and run it; record its delivered, suppressed or unknown receipt using pa automations receipt."
        elif kind == "daily_brief":
            schedule, name = "0 8 * * *", "personal-assistant-daily-brief"
            prompt = "Run the accepted PA daily brief using the qualified skills; respect the local precheck and quiet hours."
            skills = _SKILLS[kind]
        else:
            schedule, name = "*/5 * * * *", "personal-assistant-due-source-check"
            prompt = "Check accepted PA due actions and refresh only accepted sources reported due by the local precheck. Preserve valid facts on failures. Do not create or modify cron jobs."
            skills = _SKILLS[kind]
            settings["due_interval_minutes"] = DEFAULTS["due_interval_minutes"]
            settings["accepted_sources"] = entry["sources"]
            settings["due_sources"] = _due_sources(raw_rules, current, active)
        jobs.append({
            "name": name, "kind": kind, "schedule": schedule, "timezone": entry["timezone"],
            "schedule_timezone": entry["timezone"], "destination": entry["destination"],
            "deliver": entry["destination"], "destination_verified": True,
            "verified_destination": True, "skills": list(skills), "prompt": prompt,
            "rules": list(entry["rules"]), "settings": settings,
            "install": False, "creates_jobs": False,
        })
    return {
        "status": "suggested" if jobs else ("missing_inputs" if missing else "no_accepted_rules"),
        "suggestions": jobs, "jobs": jobs, "max_jobs": 4 if chief_of_staff is True else 2, "install": False,
        "missing_inputs": sorted(set(missing)), "network_requests": 0,
    }
def script_precheck(state=None, *, now=None, timezone=None, kind=None, quiet_hours=None,
                    snooze_until=None, trip_end=None, trip_ended=None,
                    unresolved_refunds=False, urgent=False):
    """Pure local gate used before a scheduled child performs any work."""
    data = state if isinstance(state, dict) else {}
    if kind in COS_JOBS and data.get("chief_of_staff") is not True:
        return {"run": False, "allowed": False, "status": "suppressed", "reason": "chief_of_staff_off"}
    timezone = timezone or data.get("timezone")
    if not timezone:
        return {"run": False, "allowed": False, "status": "blocked", "reason": "timezone_required"}
    try:
        zone = ZoneInfo(timezone)
    except Exception:
        return {"run": False, "allowed": False, "status": "blocked", "reason": "invalid_timezone"}
    current = _now(now or data.get("now"), timezone)
    if data.get("enabled") is False or data.get("plugin_enabled") is False or data.get("disabled") is True:
        return {"run": False, "allowed": False, "status": "suppressed", "reason": "disabled", "timezone": timezone}
    if data.get("paused") is True or data.get("status") == "paused":
        return {"run": False, "allowed": False, "status": "suppressed", "reason": "paused", "timezone": timezone}
    quiet = quiet_hours or data.get("quiet_hours") or DEFAULTS["quiet_hours"]
    start = dt.time.fromisoformat(quiet.get("start", "22:00"))
    end = dt.time.fromisoformat(quiet.get("end", "07:00"))
    local = current.astimezone(zone)
    clock = local.time().replace(tzinfo=None)
    in_quiet = clock >= start or clock < end if start > end else start <= clock < end
    snooze = snooze_until or data.get("snooze_until")
    if snooze:
        until = _value_time(snooze, timezone)
        if until is None:
            return {"run": False, "allowed": False, "status": "blocked", "reason": "invalid_snooze", "timezone": timezone}
        if until and current < until:
            return {"run": False, "allowed": False, "status": "suppressed", "reason": "snoozed", "timezone": timezone}
    ended = trip_ended if trip_ended is not None else data.get("trip_ended", False)
    end_value = trip_end or data.get("trip_end")
    if end_value:
        parsed_end = _value_time(end_value, timezone)
        if parsed_end is None:
            return {"run": False, "allowed": False, "status": "blocked", "reason": "invalid_trip_end", "timezone": timezone}
        ended = ended or bool(parsed_end and current >= parsed_end)
    refunds = unresolved_refunds or data.get("unresolved_refunds")
    if isinstance(refunds, (list, tuple, set, dict)):
        refunds = bool(refunds)
    urgent = urgent or data.get("urgent") is True
    if ended and not refunds:
        return {"run": False, "allowed": False, "status": "suppressed", "reason": "trip_ended", "timezone": timezone}
    if in_quiet and not urgent:
        return {"run": False, "allowed": False, "status": "suppressed", "reason": "quiet_hours", "timezone": timezone}
    due_sources = _due_sources(data.get("accepted_sources", data.get("sources", [])), current, data.get("active_travel") is True)
    due_actions = _due_actions(data.get("actions", data.get("due_actions", [])), current)
    if not (due_sources or due_actions or refunds):
        return {"run": False, "allowed": False, "status": "suppressed", "reason": "no_due_work", "timezone": timezone, "due_sources": due_sources}
    return {"run": True, "allowed": True, "status": "ready", "reason": "unresolved_refunds" if refunds and ended else "ready", "timezone": timezone, "due_sources": due_sources}
precheck = script_precheck
def notification_occurrence_id(rule_id, occurrence, source_revision=None):
    revision = "none" if source_revision is None else str(source_revision)
    return stable_id("pa-notification", str(rule_id), str(occurrence), revision)
def _notification_action_id(ledger, occurrence_id):
    return ledger.action_id("pa-notification", "notification", str(occurrence_id))
def claim_notification(ledger, occurrence_id, *, rule_id=None, payload=None, now=None):
    """Atomically claim one occurrence; any existing claim is never retried."""
    if occurrence_id is None or str(occurrence_id).strip() == "":
        raise ValueError("notification occurrence is required")
    identity = _notification_action_id(ledger, occurrence_id)
    stamp = now() if callable(now) else now
    stamp = stamp.isoformat() if isinstance(stamp, dt.datetime) else (str(stamp) if stamp else dt.datetime.now(dt.timezone.utc).isoformat())
    fields = {"notification_occurrence_id": str(occurrence_id), "notification_state": "claimed", "claimed_at": stamp}
    if rule_id is not None:
        fields["rule_id"] = str(rule_id)
    if payload is not None:
        fields["payload_digest"] = stable_id(clean(payload))
    with ledger.connect() as conn:
        conn.execute("begin immediate")
        row = conn.execute("select * from actions where action_id=?", (identity,)).fetchone()
        if row:
            stored = json.loads(row["fields_json"] or "{}")
            return {"claimed": False, "action_id": identity, "occurrence_id": str(occurrence_id), "state": stored.get("notification_state", row["status"]), "receipt": stored.get("receipt")}
        conn.execute(
            "insert into actions values(?,?,?,?,?,?,?,?)",
            (identity, None, "notification", "local", "claimed", json.dumps(fields, ensure_ascii=False), stamp, stamp),
        )
    return {"claimed": True, "action_id": identity, "occurrence_id": str(occurrence_id), "state": "claimed", "receipt": None}
def _proof_fields(proof):
    if not isinstance(proof, dict) or not proof.get("provider") or not (proof.get("receipt_reference") or proof.get("receipt_id") or proof.get("reference")): return {}
    allowed = {"provider", "receipt_reference", "receipt_id", "reference", "status", "observed_at"}
    return {"provider_proof": clean({k: v for k, v in proof.items() if k in allowed})}
def record_notification(ledger, occurrence_id, receipt, *, note=None, proof=None, now=None):
    """Record delivered, suppressed, or unknown exactly once."""
    if isinstance(receipt, dict):
        state = receipt.get("state", receipt.get("status", receipt.get("receipt")))
    else:
        state = receipt
    state = str(state or "").lower()
    if state not in _TERMINAL_RECEIPTS:
        raise ValueError("notification receipt must be delivered, suppressed, or unknown")
    proof_fields = _proof_fields(proof)
    if state == "delivered" and not proof_fields:
        raise ValueError("delivered notification requires provider receipt evidence")
    identity = _notification_action_id(ledger, occurrence_id)
    stamp = now() if callable(now) else now
    stamp = stamp.isoformat() if isinstance(stamp, dt.datetime) else (str(stamp) if stamp else dt.datetime.now(dt.timezone.utc).isoformat())
    with ledger.connect() as conn:
        conn.execute("begin immediate")
        row = conn.execute("select * from actions where action_id=?", (identity,)).fetchone()
        if not row:
            raise ValueError("notification occurrence was not claimed")
        fields = json.loads(row["fields_json"] or "{}")
        prior = fields.get("notification_state", row["status"])
        if prior == "unknown" and state == "delivered":
            fields.update({"notification_state": state, "receipt": state, "receipt_status": state, "receipt_at": stamp, "resolved_from_unknown": True, **proof_fields})
            conn.execute("update actions set status=?,fields_json=?,updated_at=? where action_id=?", (state, json.dumps(fields, ensure_ascii=False), stamp, identity))
            return {"recorded": True, "resolved_from_unknown": True, "action_id": identity, "occurrence_id": str(occurrence_id), "state": state, "receipt": state}
        if prior in _TERMINAL_RECEIPTS:
            return {"recorded": False, "action_id": identity, "occurrence_id": str(occurrence_id), "state": prior, "receipt": fields.get("receipt", prior)}
        if prior != "claimed":
            raise ValueError("notification occurrence is not claimable")
        fields.update({"notification_state": state, "receipt": state, "receipt_status": state, "receipt_at": stamp, **proof_fields})
        if note:
            fields["receipt_note_digest"] = stable_id(clean(note))
        conn.execute("update actions set status=?,fields_json=?,updated_at=? where action_id=?", (state, json.dumps(fields, ensure_ascii=False), stamp, identity))
    return {"recorded": True, "action_id": identity, "occurrence_id": str(occurrence_id), "state": state, "receipt": state}
def notification_receipt(ledger, occurrence_id):
    row = ledger.get("action", _notification_action_id(ledger, occurrence_id))
    if not row:
        return None
    fields = row["fields"]
    return {
        "action_id": row["action_id"],
        "occurrence_id": fields.get("notification_occurrence_id"),
        "state": fields.get("notification_state", row["status"]),
        "receipt": fields.get("receipt"),
        "rule_id": fields.get("rule_id"),
        "payload_digest": fields.get("payload_digest"),
        "claimed_at": fields.get("claimed_at"),
        "receipt_at": fields.get("receipt_at"),
        "provider_proof": fields.get("provider_proof"),
    }


def canonical_notification_payload(*, profile_id, account, timezone, destination, rule_id, rule_revision):
    """Build the stable payload identity used by existing notification claims."""
    values = {
        "profile_id": profile_id,
        "account": account,
        "timezone": timezone,
        "destination": destination,
        "rule_id": rule_id,
        "rule_revision": rule_revision,
    }
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise ValueError("notification verification payload fields are required")
    return clean(values)
