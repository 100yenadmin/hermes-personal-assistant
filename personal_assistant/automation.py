"""Local-only PA cron suggestions, prechecks, and notification receipts."""
import datetime as dt
import json
from zoneinfo import ZoneInfo
from .privacy import clean
from .state import Ledger, stable_id

DEFAULTS = {
    "brief_time": "08:00",
    "eod_time": "18:00",
    "cos_daily_time": "09:30",
    "cos_kickoff_day": "mon",
    "cos_kickoff_time": "11:00",
    "cos_weekly_day": "fri",  # The weekly closeout.
    "cos_weekly_time": "15:00",
    "quiet_hours": {"start": "22:00", "end": "07:00"},
    "due_interval_minutes": 5,
    "travel_source_refresh_minutes": 15,
    "normal_source_refresh_minutes": 360,
    "inbox_refresh_minutes": 30,
    "authenticated_guides": "manual",
}
_SKILLS = {
    "cos_daily": ["personal-assistant:cos-daily"],
    "cos_kickoff": ["personal-assistant:cos-kickoff"],
    "cos_weekly": ["personal-assistant:cos-weekly", "personal-assistant:cos-radar"],
    "daily_brief": [
        "personal-assistant:r5-brief-reminders",
        "personal-assistant:daily-ops",
        "personal-assistant:r4-calendar-meeting",
        "personal-assistant:r6-inbox-replies",
    ],
    "due_source_check": [
        "personal-assistant:itinerary-intake",
        "personal-assistant:travel-email-calendar",
        "personal-assistant:provider-message-refund",
        "personal-assistant:daily-ops",
        "personal-assistant:follow-through",
        "personal-assistant:r5-brief-reminders",
        "personal-assistant:r4-calendar-meeting",
        "personal-assistant:r6-inbox-replies",
    ],
}
COS_JOBS = {"cos_daily": "personal-assistant-cos-daily", "cos_kickoff": "personal-assistant-cos-kickoff",
            "cos_weekly": "personal-assistant-cos-weekly"}
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
def rule_timezone(rule, prefs):
    """Only an explicit owner pin overrides the owner's current timezone."""
    data = _rule_data(rule)
    return data.get("timezone") if data.get("timezone_pinned") is True else prefs.get("timezone")
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
    value = rule_timezone(rule, {"timezone": default})
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
        "timezone_pinned", "source_type", "last_checked_at", "due_at", "on_request",
        "refresh_interval_minutes", "paused", "profile_id", "account",
        "quiet_hours_exceptions", "accepted_at", "verified_at", "receipt_reference", "rule_revision", "revision",
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
def snooze_released(old, new, zone="UTC"):
    """True when a snooze still running now is cleared or moved earlier; values without an offset read in `zone`."""
    current = _now(None, "UTC")
    before = _value_time(old, zone) if old else None
    if not before or before <= current:
        return False
    after = _value_time(new, zone) if new else None
    return after is None or after < before


def upsert_automation_rule(ledger, rule_id, rule):
    """Store an accepted rule as a ledger action, without creating a job."""
    fields = source_rule_fields(rule)
    fields["automation_rule_id"] = str(rule_id)
    action_id = ledger.action_id("pa-automation-rule", "rule", str(rule_id))
    prior = ledger.get("action", action_id)
    old = _rule_data(prior) if prior else {}
    # A resume (unpause, or a snooze ended early) starts the routine's health grace again.
    if prior and ((old.get("paused") and not _rule_data(rule).get("paused"))
                  or snooze_released(old.get("snooze_until"), _rule_data(rule).get("snooze_until"),
                                     rule_timezone(rule, (ledger.get("action", "pa:preferences") or {}).get("fields", {})) or "UTC")):
        fields["routine_resumed_at"] = _now(None, "UTC").isoformat()
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
def _due_sources(sources, current, active=False, prefs=None):
    due, default = [], DEFAULTS["travel_source_refresh_minutes"] if active else DEFAULTS["normal_source_refresh_minutes"]
    for source in sources or []:
        source = _rule_data(source); ref = source.get("source_ref")
        if source.get("accepted") is not True or not ref or source.get("on_request") is True or source.get("source_type") == "authenticated_guide" or source.get("paused") is True: continue
        zone = rule_timezone(source, prefs or {}) or "UTC"; due_at, checked = source.get("due_at"), source.get("last_checked_at")
        due_time = _value_time(due_at, zone) if due_at else None; last = _value_time(checked, zone) if checked else None
        interval = DEFAULTS["inbox_refresh_minutes"] if source.get("source_type") == "inbox" else default
        if (due_time and due_time <= current) or not checked or (last and current >= last + dt.timedelta(minutes=int(source.get("refresh_interval_minutes", interval)))): due.append(ref)
    return due
def _due_actions(actions, current):
    terminal = {"paused", "completed", "confirmed", "failed", "cancelled", "dismissed"}
    for action in actions or []:
        fields = action.get("fields", action) if isinstance(action, dict) else {}
        if action.get("status") in terminal or fields.get("status") in terminal: continue
        due_at = (fields.get("next_chase_at") if fields.get("loop_kind") else None) or fields.get("due_at", action.get("due_at")); zone = fields.get("timezone", "UTC")
        if fields.get("due") is True or (due_at and _value_time(due_at, zone) and _value_time(due_at, zone) <= current): return True
    return False
def suggest_automation_jobs(source=None, *, destination=None, destination_verified=False,
                            timezone=None, now=None, ledger=None, chief_of_staff=False):
    """Build inert native cron suggestions from accepted rules and enabled modes."""
    raw_rules, trips = _rules_from(source, ledger)
    owner_ledger = ledger if ledger is not None else source if isinstance(source, Ledger) else None
    if timezone is None and owner_ledger is not None:
        timezone = (owner_ledger.get("action", "pa:preferences") or {}).get("fields", {}).get("timezone")
    # Use UTC solely to inspect explicit trip dates when no configured timezone exists.
    current = _now(now, timezone or "UTC")
    grouped, missing, seen, conflicted = {}, [], set(), set()
    for item in raw_rules:
        rule = _rule_data(item)
        kind = _canonical_kind(rule.get("kind"))
        if kind in COS_JOBS and (chief_of_staff is not True or rule.get("paused")):
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
            conflicted.add(kind)
            continue
        entry["rules"].append(identity)
        source_ref = rule.get("source_ref")
        if source_ref and source_ref not in entry["sources"]:
            entry["sources"].append(source_ref)
    active = _trip_active(trips, current)
    jobs = []
    for kind in ("daily_brief", "due_source_check", *COS_JOBS):
        if kind not in grouped or (kind in COS_JOBS and kind in conflicted):
            continue  # A CoS job whose rules disagree on the chat would never wake.
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
            prompt = f"Load skill {skills[0]} and run it. Your final response is the owner message, or exactly [SILENT]; record the receipt with pa automations receipt as the skill says before you reply."
        elif kind == "daily_brief":
            schedule, name = "0 8 * * *", "personal-assistant-daily-brief"
            prompt = "Run the accepted PA daily brief or end-of-day note indicated by the local precheck using the qualified skills; respect quiet hours."
            skills = _SKILLS[kind]
        else:
            schedule, name = "*/5 * * * *", "personal-assistant-due-source-check"
            prompt = "Check accepted PA due actions and chase steps, and refresh only accepted sources reported due by the local precheck. Preserve valid facts on failures. Do not create or modify cron jobs."
            skills = _SKILLS[kind]
            settings["due_interval_minutes"] = DEFAULTS["due_interval_minutes"]
            settings["accepted_sources"] = entry["sources"]
            settings["due_sources"] = _due_sources(raw_rules, current, active, {"timezone": timezone})
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
        "suggestions": jobs, "jobs": jobs, "max_jobs": 5 if chief_of_staff is True else 2, "install": False,
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
    due_sources = _due_sources(data.get("accepted_sources", data.get("sources", [])), current, data.get("active_travel") is True, {"timezone": timezone})
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


def routine_occurrence(kind, logical, rules):
    """Share the native claim identity with read-only health and scorecards."""
    rule = rules[0] if len(rules) == 1 else {}
    rule_id = str(rule.get("automation_rule_id", kind))
    revision = rule.get("rule_revision", rule.get("revision"))
    complete = all(isinstance(v, str) and v.strip() for v in (rule.get("profile_id"), rule.get("account"), revision))
    return notification_occurrence_id(kind, logical) if kind in COS_JOBS else notification_occurrence_id(rule_id, logical, revision if complete else None)


def routine_time(value):
    """Accept only canonical HH:MM clock preferences, including stored values."""
    if not isinstance(value, str) or len(value) != 5 or dt.time.fromisoformat(value).strftime("%H:%M") != value:
        raise ValueError("time must be HH:MM")
    return dt.time.fromisoformat(value)


def eod_clock(prefs):
    """The end-of-day slot's HH:MM, or None when it does not fall after the brief: an evening brief replaces it."""
    eod = routine_time(prefs.get("eod_time", DEFAULTS["eod_time"]))
    return eod.strftime("%H:%M") if eod > routine_time(prefs.get("brief_time", DEFAULTS["brief_time"])) else None


def _after_quiet(prefs, at, zone):
    """The first moment at or after `at` outside the profile's quiet hours; preferences only, never current state."""
    quiet = prefs.get("quiet_hours") or DEFAULTS["quiet_hours"]
    try:
        start, end = routine_time(quiet.get("start", "22:00")), routine_time(quiet.get("end", "07:00"))
    except (AttributeError, TypeError, ValueError):
        raise ValueError("invalid_quiet_hours") from None
    local = at.astimezone(ZoneInfo(zone))
    clock = local.time().replace(tzinfo=None)
    if not (clock >= start or clock < end if start > end else start <= clock < end):
        return at
    moved = dt.datetime.combine(local.date(), end, ZoneInfo(zone))
    return moved + dt.timedelta(days=1) if moved <= local else moved


def _eligible_slot(prefs, rules, at, zone):
    """Today's health clock starts after intentional holds (snooze, pause, resume) and quiet hours end."""
    if prefs.get("paused") is True or prefs.get("disabled") is True or prefs.get("enabled") is False:
        return None
    holds = [_value_time(value, zone) for value in (
        prefs.get("snooze_until"), prefs.get("routine_resumed_at"),
        *(r.get(key) for r in rules for key in ("snooze_until", "routine_resumed_at"))) if value]
    if any(value is None for value in holds):
        raise ValueError("invalid_snooze")
    return _after_quiet(prefs, max(at, *holds) if holds else at, zone)


def routine_slots(ledger, *, now=None, date=None, findings=None, health=False):
    """Known calendar slots for accepted rules, without claiming or repairing.

    The schedule comes from preferences alone, so historical scoring never depends on today's holds.
    `health=True` (today only) also starts each slot's clock after intentional holds end."""
    prefs = (ledger.get("action", "pa:preferences") or {}).get("fields", {})
    current = _now(now, "UTC")
    grouped = {}
    for row in ledger.list("action"):
        rule = _rule_data(row)
        if row["action_type"] == "automation_rule" and rule.get("accepted") and rule.get("destination_verified") and not rule.get("paused"):
            grouped.setdefault(rule.get("kind"), []).append(rule)
    slots = []
    for kind, rules in grouped.items():
        if kind not in {"daily_brief", *COS_JOBS}: continue
        zone = rule_timezone(rules[0], prefs)
        if len({r.get("destination") for r in rules}) != 1 or not rules[0].get("destination"): continue
        if any(rule_timezone(r, prefs) != zone for r in rules): continue
        if kind == "daily_brief" and prefs.get("timezone") != zone: continue
        try:
            local = current.astimezone(ZoneInfo(zone))
        except (ValueError, TypeError, KeyError):
            continue
        day = dt.date.fromisoformat(date) if date else local.date()
        clocks = [(kind + "_time", "")]
        if kind == "daily_brief":
            try:
                eod_at = eod_clock(prefs)
            except (ValueError, TypeError):
                eod_at = prefs.get("eod_time", DEFAULTS["eod_time"])  # The loop below reports the invalid clock.
            clocks = [("brief_time", "")] + ([("eod_time", ":eod")] if eod_at else [])
        for key, suffix in clocks:
            if kind in {"cos_kickoff", "cos_weekly"} and day.weekday() != ("mon", "tue", "wed", "thu", "fri", "sat", "sun").index(prefs.get(kind + "_day", DEFAULTS[kind + "_day"])): continue
            try:
                clock = routine_time(prefs.get(key, DEFAULTS[key]))
            except (ValueError, TypeError):
                if findings is not None:
                    findings.append({"id": stable_id(kind, key, str(prefs.get(key))), "kind": kind,
                                     "reason": "invalid_" + key, "at": current.isoformat()})
                continue
            at = dt.datetime.combine(day, clock, ZoneInfo(zone))
            # The acceptance day's slot before acceptance is not scored: the precheck may catch it up, but a re-acceptance
            # or a weekly cutoff would make a due time from acceptance report work that already passed or cannot run.
            if at > current or any(_value_time(r.get("accepted_at"), zone) and _value_time(r["accepted_at"], zone) > at for r in rules): continue
            try:
                at = _eligible_slot(prefs, rules, at, zone) if health else _after_quiet(prefs, at, zone)
            except ValueError as error:
                if findings is not None:
                    findings.append({"id": stable_id(kind, str(error)), "kind": kind, "reason": str(error), "at": current.isoformat()})
                continue
            if at is None or at > current: continue
            eligible = at.astimezone(ZoneInfo(zone))
            if eligible.date() != day: continue  # The precheck only claims today's period.
            if kind == "daily_brief" and not suffix and eod_at and eligible.strftime("%H:%M") >= eod_at: continue
            logical = day.isoformat() + suffix if kind in {"daily_brief", "cos_daily"} else "%04d-W%02d" % day.isocalendar()[:2]
            slots.append({"kind": kind, "logical": logical, "due_at": at.isoformat(),
                          "occurrence_id": routine_occurrence(kind, logical, rules)})
    return slots


def routine_health(ledger, *, now=None, grace_minutes=60):
    """Read-only findings; unknown hand-offs are terminal, never delivery proof."""
    current = _now(now, "UTC")
    if ledger.read_only and not ledger.path.exists():
        return {"status": "no ledger yet", "findings": [], "read_only": True}
    grace = dt.timedelta(minutes=max(0, int(grace_minutes)))
    rows = ledger.list("action")
    findings = []
    for row in rows:
        fields = row["fields"]
        if fields.get("routine_kind") == "routine-health" or fields.get("rule_id") == "routine-health": continue
        if row["action_id"].startswith("pa:routine-health:") and fields.get("reason"):
            findings.append({"id": stable_id(row["action_id"], fields["reason"], fields["failed_at"]),
                             "kind": fields.get("kind"), "reason": fields["reason"],
                             "at": fields["failed_at"], "note_id": row["action_id"], "recovered_at": fields.get("recovered_at")})
        if row["action_type"] != "notification" or fields.get("notification_state") in _TERMINAL_RECEIPTS: continue
        claimed = _value_time(fields.get("claimed_at"), "UTC")
        if claimed and current >= claimed + grace:
            findings.append({"id": stable_id("receipt_missing", row["action_id"]), "kind": fields.get("routine_kind", fields.get("rule_id")),
                             "reason": "receipt_missing", "at": claimed.isoformat(), "occurrence_id": fields.get("notification_occurrence_id")})
    invalid = []
    for slot in routine_slots(ledger, now=current, findings=invalid, health=True):
        if current >= _value_time(slot["due_at"], "UTC") + grace and not notification_receipt(ledger, slot["occurrence_id"]):
            findings.append({"id": stable_id("slot_unclaimed", slot["occurrence_id"]), "reason": "slot_unclaimed", **slot})
    for finding in invalid:  # One finding per routine and cause, even when both of its clocks hit it.
        if not any((finding["kind"], finding["reason"]) == (old.get("kind"), old.get("reason")) for old in findings):
            findings.append(finding)
    return {"status": "attention" if any(not f.get("recovered_at") for f in findings) else "healthy", "findings": findings, "read_only": True}
