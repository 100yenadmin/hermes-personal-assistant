"""Bounded PA context retrieval and read-only native Kanban reconciliation."""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .profile import KINDS as _PROFILE_TYPES
from .evidence import EVIDENCE_TYPES


DEFAULT_LIMIT = 8
MAX_LIMIT = 20
MAX_STRING_CHARS = 2000
MAX_GUIDE_CHARS = 4000
_COMMITMENT_TYPES = {"commitment", "transaction", "refund", "return"}
_KANBAN_DONE = {"done", "archived"}
LOOP_KINDS = {"ask_owner", "delegated", "our_promise", "waiting_on_them"}
NEXT_ACTORS = {"owner", "us", "them"}
CHASE_LADDER = (("day2", 2), ("day5", 5), ("day10", 10), ("escalate", 11))
APPROVAL_OVERDUE_DAYS = 2
MAX_CHASE_LOG = 10
_LOOP_SUMMARY = ("loop_kind", "counterparty", "next_actor", "opened_at", "next_step", "chase_at", "last_chased_at",
                 "confirmation")


def _paging(data: dict[str, Any]) -> tuple[int, int]:
    try:
        limit, offset = int(data.get("limit", DEFAULT_LIMIT)), int(data.get("offset", 0))
    except (TypeError, ValueError):
        raise ValueError("limit and offset must be integers") from None
    if not 1 <= limit <= MAX_LIMIT or offset < 0:
        raise ValueError(f"limit must be 1-{MAX_LIMIT} and offset must be non-negative")
    return limit, offset


def _page(items: list[Any], limit: int, offset: int) -> dict[str, Any]:
    selected = items[offset:offset + limit]
    more = offset + len(selected) < len(items)
    return {
        "items": selected,
        "count": len(selected),
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "truncated": more,
        "next_offset": offset + len(selected) if more else None,
    }


def _bounded(value: Any) -> tuple[Any, bool]:
    """Bound nested record content while preserving useful typed values."""

    if isinstance(value, str):
        return (value, False) if len(value) <= MAX_STRING_CHARS else (value[:MAX_STRING_CHARS], True)
    if isinstance(value, list):
        values, truncated = [], len(value) > MAX_LIMIT
        for item in value[:MAX_LIMIT]:
            bounded, cut = _bounded(item)
            values.append(bounded)
            truncated = truncated or cut
        return values, truncated
    if isinstance(value, dict):
        values, truncated = {}, len(value) > 40
        for key in list(value)[:40]:
            bounded, cut = _bounded(value[key])
            values[str(key)] = bounded
            truncated = truncated or cut
        return values, truncated
    return value, False


def _trip_summary(row: dict[str, Any]) -> dict[str, Any]:
    fields = row.get("fields", {})
    events = fields.get("events", [])
    return {
        "trip_id": row["trip_id"], "title": row.get("title"), "status": row.get("status"),
        "timezone": fields.get("timezone"), "event_count": len(events),
        "has_guide": bool(fields.get("guide")), "verified_at": fields.get("verified_at"),
        "updated_at": row.get("updated_at"),
    }


def _action_summary(row: dict[str, Any]) -> dict[str, Any]:
    fields = row.get("fields", {})
    return {
        "action_id": row["action_id"], "trip_id": row.get("trip_id"),
        "action_type": row.get("action_type"), "status": row.get("status"),
        "title": fields.get("title") or fields.get("summary"),
        "due_at": fields.get("due_at"), "next_action": fields.get("next_action"),
        "kanban_task_id": fields.get("kanban_task_id"), "updated_at": row.get("updated_at"),
        **({key: fields.get(key) for key in _LOOP_SUMMARY} if fields.get("loop_kind") else {}),
        **{key: fields[key] for key in ("priority", "blocked_by") if key in fields},
    }


_UNRESOLVED_ATTEMPT = {"submitting", "unknown", "claimed_once", "provider_result"}
_TRANSACTION_HOLD = _UNRESOLVED_ATTEMPT | {"paused", "prepared", "approval_required", "authorized",
                                          "approved_revision", "failed"}
_NUDGE_IN_FLIGHT = _TRANSACTION_HOLD - {"failed"}
_TRANSACTION_DONE = {"completed", "confirmed", "verified", "reconciled"}


def nudges_in_flight(actions):
    """Loop id -> (nudge id, status) for each loop whose nudge, <loop action id>:nudge:<step>, is still in flight.

    While one is in flight its loop waits: no new nudge, and no wake for the loop's own deadline."""
    found = {}
    for row in actions:
        parent, marker, _ = str(row.get("action_id", "")).partition(":nudge:")
        if marker and row.get("status") in _NUDGE_IN_FLIGHT:
            found.setdefault(parent, (row["action_id"], row.get("status")))
    return found


def _iso_time(value: Any, *, timestamp: bool = False) -> bool:
    if not isinstance(value, str) or (timestamp and len(value.strip()) <= 10):
        return False
    try:
        dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def loop_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Validate supplied loop fields on write and bound the chase log."""

    if not isinstance(fields, dict):
        return fields
    if "loop_kind" in fields and (not isinstance(fields["loop_kind"], str) or fields["loop_kind"] not in LOOP_KINDS):
        raise ValueError("loop_kind must be ask_owner, delegated, our_promise or waiting_on_them")
    if "next_actor" in fields and (not isinstance(fields["next_actor"], str) or fields["next_actor"] not in NEXT_ACTORS):
        raise ValueError("next_actor must be owner, us or them")
    for name in ("opened_at", "last_chased_at", "snoozed_until", "chase_at"):
        if name in ("snoozed_until", "chase_at") and fields.get(name) in (None, ""):
            continue  # Clearing a snooze or the owner's chase time is allowed.
        if name in fields and not _iso_time(fields[name]):
            raise ValueError(f"{name} must be an ISO date or timestamp")
    if "confirmation" in fields and not _confirmed(fields):
        raise ValueError("confirmation must be an object with by, at and evidence")
    if "loop_cancelled" in fields and not _cancelled(fields):
        raise ValueError("loop_cancelled must be an object with by and at")
    if "chase_log" in fields:
        log = fields["chase_log"]
        if not isinstance(log, list) or any(
            not isinstance(entry, dict) or entry.get("step") not in tuple(step for step, _ in CHASE_LADDER)
            or not _iso_time(entry.get("at"), timestamp=True) for entry in log
        ):
            raise ValueError("chase_log must be a list of objects with ladder step and ISO timestamp at")
        fields = {**fields, "chase_log": fields["chase_log"][-MAX_CHASE_LOG:]}
    return fields


def owner_zone(ledger) -> dt.tzinfo:
    """The profile timezone that quiet hours and briefs use; UTC when unset."""

    name = ((ledger.get("action", "pa:preferences") or {}).get("fields") or {}).get("timezone")
    try:
        return ZoneInfo(name) if name else dt.timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return dt.timezone.utc


def evaluation_moment(data: dict[str, Any]) -> dt.datetime:
    at = data.get("at")
    if not at:
        return dt.datetime.now(dt.timezone.utc)
    moment = dt.datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("at must be a timezone-aware timestamp")
    return moment


def local_time(value: Any, zone: dt.tzinfo) -> dt.datetime | None:
    """An ISO timestamp or date in ``zone``; a naive value is read as owner-local."""

    try:
        parsed = dt.datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)).astimezone(zone)


def approval_wait(fields: dict[str, Any], moment: dt.datetime, zone: dt.tzinfo) -> dict[str, Any] | None:
    """The last held draft awaits approval until any later chase entry replaces it."""

    log = fields.get("chase_log")
    if not isinstance(log, list):
        return None
    # An escalation packet does not decide a held draft, so look past trailing escalate entries.
    decisive = [e for e in log if isinstance(e, dict)
                and (e.get("step") != "escalate" or re.search(r"\bdraft held\b", str(e.get("how") or "").casefold()))]
    if not decisive:
        return None
    entry = decisive[-1]
    how = str(entry.get("how") or "").casefold()
    if not re.search(r"\bdraft held\b", how) or re.search(r"(?<!not )\bsent\b|\bdeclined\b", how):
        return None
    since = local_time(entry.get("at"), zone)
    if since is None:
        return None
    days = (moment.astimezone(zone).date() - since.date()).days
    return {"step": entry.get("step"), "since": entry["at"], "days": days,
            "overdue": days >= APPROVAL_OVERDUE_DAYS}


def loop_chase(fields: dict[str, Any], *, created_at: Any = None, moment: dt.datetime,
               zone: dt.tzinfo) -> dict[str, Any]:
    """Chase ladder on owner-local calendar days from opened_at: day 2, 5, 10, then escalate.

    A step is done when ``last_chased_at`` falls on or after its local date or a ``chase_log``
    entry names it. Escalation completes only with a ``chase_log`` entry whose step is ``escalate``.
    ``chase_at`` is the owner's own time for the next chase, earlier or later than the ladder: the
    steps still pending before it that fall due by then (or else the next one) fold into one chase
    at that exact time, and a chase at or after it completes them. Escalation never moves
    earlier; when the owner's time is after it, it comes a day after the owner's chase.
    """

    today = moment.astimezone(zone).date()
    opened = local_time(fields.get("opened_at"), zone) or local_time(created_at, zone)
    if opened is None:
        return {"step": "none", "next_chase_at": None, "age_days": None, "escalated": False}
    chased = local_time(fields.get("last_chased_at"), zone)
    log = [entry for entry in fields.get("chase_log") or [] if isinstance(entry, dict)] \
        if isinstance(fields.get("chase_log"), list) else []
    escalated = any(entry.get("step") == "escalate" for entry in log)
    ladder = [(step, dt.datetime.combine(opened.date() + dt.timedelta(days=days), dt.time(), zone))
              for step, days in CHASE_LADDER]

    def pending_after(last, steps):
        return [(step, due) for step, due in ladder if not escalated and not (
            step != "escalate" and (step in steps or (last is not None and last.date() >= due.date())))]

    pending = pending_after(chased, {entry.get("step") for entry in log})
    asked = local_time(fields.get("chase_at"), zone) if fields.get("chase_at") else None
    if asked is not None and asked.date() >= opened.date():
        # Fold on the evidence from before the owner's time, so the chase made at it counts once.
        stamp = asked.timestamp()
        times = [(entry, local_time(entry.get("at"), zone)) for entry in log]
        earlier = [at for _, at in times if at is not None and at.timestamp() < stamp]
        earlier += [chased] if chased is not None and chased.timestamp() < stamp else []
        base = [entry for entry in pending_after(max(earlier, key=lambda at: at.timestamp(), default=None),
                                                 {e.get("step") for e, at in times if at and at.timestamp() < stamp})
                if entry[0] != "escalate"]
        folded = [entry for entry in base if entry[1].timestamp() <= stamp] or base[:1]
        answered = (chased is not None and chased.timestamp() >= stamp) or any(
            at is not None and at.timestamp() >= stamp for _, at in times)
        names = {step for step, _ in folded}
        # The owner put the chase off past escalation: escalate a day after their chase instead.
        pending = [(step, asked + dt.timedelta(days=1) if step == "escalate" and due.timestamp() <= stamp else due)
                   for step, due in pending if step not in names]
        if not answered:
            # With day 10 done or the loop escalated, the owner's time is still one more chase.
            pending.append((folded[-1][0] if folded else "day10", asked))
        pending.sort(key=lambda entry: entry[1].timestamp())
    due_now = [entry for entry in pending if entry[1].timestamp() <= moment.timestamp()]
    target = due_now[-1] if due_now else (pending[0] if pending else None)
    step = due_now[-1][0] if due_now else "none"
    next_at = target[1] if target else None
    snoozed = local_time(fields.get("snoozed_until"), zone) if fields.get("snoozed_until") else None
    if snoozed and snoozed > moment:
        step, next_at = "none", max(next_at, snoozed) if next_at else None
    return {"step": step, "next_chase_at": next_at.isoformat() if next_at else None,
            "age_days": (today - opened.date()).days, "escalated": escalated}


def _confirmed(fields: dict[str, Any]) -> bool:
    confirmation = fields.get("confirmation")
    return (isinstance(confirmation, dict)
            and all(isinstance(confirmation.get(key), str) and confirmation[key].strip() for key in ("by", "evidence"))
            and _iso_time(confirmation.get("at"), timestamp=True))


def _cancelled(fields: dict[str, Any]) -> bool:
    cancelled = fields.get("loop_cancelled")
    return (isinstance(cancelled, dict) and isinstance(cancelled.get("by"), str) and bool(cancelled["by"].strip())
            and _iso_time(cancelled.get("at"), timestamp=True))


def loop_state(action: dict[str, Any], kanban: dict[str, Any]) -> str | None:
    fields = action.get("fields", {})
    if not isinstance(fields.get("loop_kind"), str) or fields["loop_kind"] not in LOOP_KINDS:
        return None
    if _confirmed(fields) or _cancelled(fields) or action.get("status") == "cancelled":
        return "closed"
    done = kanban.get("status") in _KANBAN_DONE or action.get("status") in {"completed", "confirmed", "done"}
    return "done_unconfirmed" if done else "open"


def _loop_step(fields: dict[str, Any], item: dict[str, Any], zone: dt.tzinfo) -> str | None:
    who = fields.get("counterparty") or "the other side"
    step = item["chase"]["step"]
    if item["loop_state"] == "done_unconfirmed":
        return (f"Kanban or status shows done, but {who} has not confirmed; ask for confirmation and "
                "record fields.confirmation {by, at, evidence} before treating the loop as closed.")
    waiting = item.get("awaiting_approval")
    if step == "escalate":
        held = ""
        if waiting:
            since = local_time(waiting["since"], zone).date().isoformat()
            held = (f" The {waiting['step']} nudge to {who} was never sent: name it as awaiting the owner's yes "
                    f"since {since}, never as a chase.")
        return ("Escalate to the owner with problem, options (2-3), recommendation and decision_deadline; "
                "load personal-assistant:follow-through." + held)
    if waiting and step in {"none", "day5", "day10"}:
        since = local_time(waiting["since"], zone).date().isoformat()
        prefix = f"Approval overdue ({waiting['days']} days): " if waiting["overdue"] else ""
        if step == "none":
            return (prefix + f"A nudge to {who} ({waiting['step']}) has been awaiting the owner's yes since {since}. "
                    "Show the held draft again: send, edit or drop. It is not a sent chase.")
        return (prefix + f"The {waiting['step']} nudge to {who} is still awaiting the owner's yes (since {since}); "
                "ask the owner to decide on it before drafting another.")
    if step == "none":
        return None
    how = {"them": f"draft a nudge to {who} and hold it for the owner's yes",
           "us": "do our next step now, or tell the owner it has slipped"}.get(
        str(fields.get("next_actor")), "remind the owner of the open ask")
    planned = fields.get("next_step") or fields.get("next_action")
    return (f"Chase {step}: {how}; then record last_chased_at and chase_log."
            + (f" Next step: {planned}" if planned else ""))


def status_snapshot(ledger, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep legacy status keys while replacing full-ledger output with summaries."""

    limit, offset = _paging(data or {})
    trips = _page([_trip_summary(row) for row in ledger.list("trip")], limit, offset)
    actions = _page([_action_summary(row) for row in ledger.list("action") if row["action_type"] not in _PROFILE_TYPES and row["action_type"] not in EVIDENCE_TYPES | {"expense"}], limit, offset)
    return {
        "trips": trips["items"], "actions": actions["items"],
        "trip_count": trips["total"], "action_count": actions["total"],
        "truncated": {"trips": trips["truncated"], "actions": actions["truncated"]},
        "next_offset": {"trips": trips["next_offset"], "actions": actions["next_offset"]},
    }


def retrieve(ledger, data: dict[str, Any]) -> dict[str, Any]:
    kind = str(data.get("kind") or "").strip().lower()
    if not kind and not (data.get("trip_id") and "query" in data):
        inferred = [name for name in ("trip", "action", "source") if data.get(name + "_id")]
        if len(inferred) == 1:
            kind = inferred[0]
    if kind not in {"trip", "action", "source", "guide"}:
        raise ValueError("context needs kind (trip, action, source, or guide); guide takes trip_id plus optional query")
    limit, offset = _paging(data)
    if kind == "trip":
        trip_id = data.get("trip_id")
        if not trip_id:
            return {"kind": kind, **_page([_trip_summary(row) for row in ledger.list("trip")], limit, offset)}
        row = ledger.get("trip", trip_id)
        if not row:
            raise ValueError("trip not found")
        events = list(row.get("fields", {}).get("events", []))
        event_page = _page(events, limit, offset)
        bounded, cut = _bounded(event_page["items"])
        return {"kind": kind, "trip": _trip_summary(row), "events": bounded,
                "count": len(bounded), "total": len(events), "limit": limit, "offset": offset,
                "truncated": event_page["truncated"] or cut, "next_offset": event_page["next_offset"]}
    if kind == "action":
        action_id = data.get("action_id")
        if not action_id:
            return {"kind": kind, **_page([_action_summary(row) for row in ledger.list("action") if row["action_type"] not in _PROFILE_TYPES and row["action_type"] not in EVIDENCE_TYPES | {"expense"}], limit, offset)}
        row = ledger.get("action", action_id)
        if not row:
            raise ValueError("action not found")
        bounded, cut = _bounded(row)
        return {"kind": kind, "action": bounded, "truncated": cut}
    if kind == "source":
        source_id = str(data.get("source_id") or data.get("query") or "").strip()
        if not source_id:
            raise ValueError("source context requires source_id or query")
        matches = []
        for trip in ledger.list("trip"):
            for event in trip.get("fields", {}).get("events", []):
                if source_id in {str(event.get("source_record_id", "")), str(event.get("uid", ""))}:
                    item, cut = _bounded(event)
                    matches.append({"record_kind": "trip_event", "trip_id": trip["trip_id"],
                                    "record": item, "truncated": cut})
        for action in ledger.list("action"):
            if str(action.get("fields", {}).get("source_record_id", "")) == source_id:
                matches.append({"record_kind": "action", "record": _action_summary(action), "truncated": False})
        return {"kind": kind, "source_id": source_id, **_page(matches, limit, offset)}
    trip_id = data.get("trip_id")
    if not trip_id:
        raise ValueError("guide context requires trip_id")
    trip = ledger.get("trip", trip_id)
    if not trip:
        raise ValueError("trip not found")
    guide = str(trip.get("fields", {}).get("guide") or "")
    query = str(data.get("query") or "").strip()
    if query:
        found = guide.lower().find(query.lower())
        if found < 0:
            return {"kind": kind, "trip_id": trip_id, "query": query, "content": "",
                    "matched": False, "truncated": False}
        start = max(0, found - MAX_GUIDE_CHARS // 4)
    else:
        start = offset
    content = guide[start:start + MAX_GUIDE_CHARS]
    return {"kind": kind, "trip_id": trip_id, "query": query or None, "content": content,
            "matched": bool(content), "offset": start,
            "truncated": start > 0 or start + len(content) < len(guide),
            "next_offset": start + len(content) if start + len(content) < len(guide) else None}


def read_kanban_task(task_id: str, board: str | None = None) -> dict[str, Any]:
    """Read one exact linked task from the native board without schema writes."""

    if not task_id:
        return {"task_id": None, "status": "unknown", "evidence": "no linked Kanban task"}
    try:
        from hermes_cli import kanban_db as kb

        path = kb.kanban_db_path(board=board)
        if not path.is_file():
            return {"task_id": task_id, "status": "unknown", "evidence": "native Kanban database unavailable"}
        uri = path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        try:
            task = kb.get_task(conn, task_id)
        finally:
            conn.close()
        if task is None:
            return {"task_id": task_id, "status": "unknown", "evidence": "linked native Kanban task not found"}
        return {"task_id": task_id, "status": task.status, "evidence": "native read-only Kanban task readback"}
    except Exception as exc:
        return {"task_id": task_id, "status": "unknown",
                "evidence": f"native Kanban read unavailable ({type(exc).__name__})"}


def next_actions(ledger, data: dict[str, Any] | None = None,
                 kanban_reader: Callable[[str, str | None], dict[str, Any]] | None = None) -> dict[str, Any]:
    data = data or {}
    limit, offset = _paging(data)
    reader = kanban_reader or read_kanban_task
    moment, zone = evaluation_moment(data), owner_zone(ledger)
    from .radar import radar_item, scan
    if data.get("radar") is True:
        return scan(ledger, data, kanban_reader=reader, moment=moment, zone=zone)
    loops_only = data.get("loops_only") is True
    today = moment.astimezone(zone).date()
    excluded_radar_upcoming = 0
    candidates = []
    load = {}
    excluded_completed = 0
    excluded_terminal_unlinked = 0
    excluded_closed_loops = 0
    actions = ledger.list("action")
    nudging = nudges_in_flight(actions)
    for action in actions:
        if action.get("action_type") not in _COMMITMENT_TYPES:
            continue
        if data.get("trip_id") and action.get("trip_id") != data["trip_id"]:
            continue
        fields = action.get("fields", {})
        loop = isinstance(fields.get("loop_kind"), str) and fields["loop_kind"] in LOOP_KINDS
        if loops_only and not loop:
            continue
        task_id = fields.get("kanban_task_id")
        kanban = reader(task_id, fields.get("kanban_board"))
        state = loop_state(action, kanban)
        status = action.get("status")
        if loop:
            # The other side's confirmation closes a loop, and so does the owner's cancellation.
            # A pending or unresolved transaction stays listed even on a closed loop, so its step still shows.
            live = action.get("action_type") == "transaction" and status in _NUDGE_IN_FLIGHT and not (
                _cancelled(fields) and fields.get("enforcement_profile") != "exact_action" and status not in _UNRESOLVED_ATTEMPT)
            if state == "closed" and not live:
                excluded_closed_loops += 1
                continue
        elif kanban.get("status") in _KANBAN_DONE:
            excluded_completed += 1
            continue
        elif not task_id and status in {"completed", "confirmed", "failed", "cancelled", "verified", "reconciled"}:
            excluded_terminal_unlinked += 1
            continue
        radar = radar_item(action, today)
        if radar and not radar["surfaced"] and not loop:
            excluded_radar_upcoming += 1  # A renewal or date waits on the radar until its lead time.
            continue
        item = _action_summary(action)
        if radar:
            item["radar"] = {key: radar[key] for key in ("radar_kind", "date", "surface_at", "days_until")}
        item["commitment_status"] = kanban.get("status", "unknown")
        item["commitment_evidence"] = kanban.get("evidence", "native Kanban evidence unavailable")
        waiting_for = fields.get("waiting_for")
        snoozed_until = fields.get("snoozed_until")
        if loop and snoozed_until:
            snoozed = local_time(snoozed_until, zone)
            if snoozed is not None and snoozed <= moment:
                snoozed_until = None
        stale = fields.get("stale") is True or fields.get("freshness") in {"stale", "unknown"}
        if snoozed_until:
            item["next_step"] = f"Wait until {snoozed_until}, then re-read source and Kanban state; do not execute now."
        elif waiting_for:
            recheck = fields.get("recheck_at") or fields.get("due_at") or "the recorded follow-up"
            item["next_step"] = f"Wait for {waiting_for}; recheck at {recheck} and do not execute now."
        elif status == "paused":
            reason = fields.get("blocked_reason") or "the paused condition"
            recheck = fields.get("recheck_at") or fields.get("due_at") or "the next owner update"
            item["next_step"] = f"Keep paused for {reason}; recheck at {recheck} before resuming."
        elif stale:
            item["next_step"] = "Refresh stale or unknown source evidence before choosing an execution step."
        elif status in _UNRESOLVED_ATTEMPT:
            item["next_step"] = "Read provider state for the claimed attempt; do not submit again."
        elif status in {"prepared", "approval_required"}:
            item["next_step"] = "Present the current material details for explicit confirmation."
        elif status in {"authorized", "approved_revision"}:
            item["next_step"] = "Recheck details, then claim immediately before one provider submission."
        elif (status == "failed" or (status == "confirmed" and not loop)
              or (action.get("action_type") == "transaction" and status in _TRANSACTION_DONE)):
            item["next_step"] = "Reconcile the provider result with the linked Kanban commitment."
        else:
            item["next_step"] = (fields.get("next_action") or (loop and fields.get("next_step"))
                                 or fields.get("blocked_reason") or "Review current source facts and choose one action.")
        if loop:
            item["loop_state"] = state
            item["chase"] = loop_chase(fields, created_at=action.get("created_at"), moment=moment, zone=zone)
            waiting = approval_wait(fields, moment, zone)
            if waiting is not None and not nudging.get(action["action_id"]):  # A yes already given is in flight.
                item["awaiting_approval"] = waiting
            # A loop row in a transaction lifecycle keeps its transaction instruction; chase
            # guidance never replaces an approval step or an unresolved provider attempt.
            nudge = nudging.get(action["action_id"])
            if nudge and not (snoozed_until or waiting_for or stale or status in _TRANSACTION_HOLD):
                item["next_step"] = (f"A nudge for this loop is in progress ({nudge[0]}, {nudge[1]}): finish or "
                                     "reconcile it first; do not draft or send another.")
            hold = (snoozed_until or waiting_for or stale or status in _TRANSACTION_HOLD or nudge
                    or action.get("action_type") == "transaction")
            guidance = None if hold else _loop_step(fields, item, zone)
            if guidance:
                item["next_step"] = guidance
        candidates.append(item)
        actor = fields.get("next_actor")
        if action.get("action_type") == "commitment" and isinstance(actor, str) and actor:
            counterparty = fields.get("counterparty")
            if actor == "them" and isinstance(counterparty, str) and counterparty.strip():
                actor = counterparty.strip()  # Only text names a holder; structured values never break the brief.
            load[actor] = load.get(actor, 0) + 1
    candidates.sort(key=lambda row: (row.get("due_at") is None, row.get("due_at") or "", row["action_id"]))
    page = _page(candidates, limit, offset)
    return {"candidates": page.pop("items"), "excluded_completed": excluded_completed,
            "excluded_terminal_unlinked": excluded_terminal_unlinked,
            "excluded_closed_loops": excluded_closed_loops,
            "excluded_radar_upcoming": excluded_radar_upcoming, **page,
            "owner_timezone": str(zone),
            **({"load": load} if load else {}),
            "commitment_authority": "native Hermes Kanban; unknown when readback is unavailable"}
