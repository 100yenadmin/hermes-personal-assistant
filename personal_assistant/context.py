"""Bounded PA context retrieval and read-only native Kanban reconciliation."""

from __future__ import annotations

import sqlite3
from typing import Any, Callable
from .profile import KINDS as _PROFILE_TYPES
from .evidence import EVIDENCE_TYPES


DEFAULT_LIMIT = 8
MAX_LIMIT = 20
MAX_STRING_CHARS = 2000
MAX_GUIDE_CHARS = 4000
_COMMITMENT_TYPES = {"commitment", "transaction", "refund", "return"}
_KANBAN_DONE = {"done", "archived"}


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
    }


def status_snapshot(ledger, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep legacy status keys while replacing full-ledger output with summaries."""

    limit, offset = _paging(data or {})
    trips = _page([_trip_summary(row) for row in ledger.list("trip")], limit, offset)
    actions = _page([_action_summary(row) for row in ledger.list("action") if row["action_type"] not in _PROFILE_TYPES and row["action_type"] not in EVIDENCE_TYPES], limit, offset)
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
            return {"kind": kind, **_page([_action_summary(row) for row in ledger.list("action") if row["action_type"] not in _PROFILE_TYPES and row["action_type"] not in EVIDENCE_TYPES], limit, offset)}
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
    candidates = []
    excluded_completed = 0
    excluded_terminal_unlinked = 0
    for action in ledger.list("action"):
        if action.get("action_type") not in _COMMITMENT_TYPES:
            continue
        if data.get("trip_id") and action.get("trip_id") != data["trip_id"]:
            continue
        fields = action.get("fields", {})
        task_id = fields.get("kanban_task_id")
        kanban = reader(task_id, fields.get("kanban_board"))
        if kanban.get("status") in _KANBAN_DONE:
            excluded_completed += 1
            continue
        status = action.get("status")
        if not task_id and status in {"completed", "confirmed", "failed", "cancelled"}:
            excluded_terminal_unlinked += 1
            continue
        item = _action_summary(action)
        item["commitment_status"] = kanban.get("status", "unknown")
        item["commitment_evidence"] = kanban.get("evidence", "native Kanban evidence unavailable")
        waiting_for = fields.get("waiting_for")
        snoozed_until = fields.get("snoozed_until")
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
        elif status in {"submitting", "unknown"}:
            item["next_step"] = "Read provider state for the claimed attempt; do not submit again."
        elif status == "prepared":
            item["next_step"] = "Present the current material details for explicit confirmation."
        elif status == "authorized":
            item["next_step"] = "Recheck details, then claim immediately before one provider submission."
        elif status in {"confirmed", "failed"}:
            item["next_step"] = "Reconcile the provider result with the linked Kanban commitment."
        else:
            item["next_step"] = fields.get("next_action") or fields.get("blocked_reason") or "Review current source facts and choose one action."
        candidates.append(item)
    candidates.sort(key=lambda row: (row.get("due_at") is None, row.get("due_at") or "", row["action_id"]))
    page = _page(candidates, limit, offset)
    return {"candidates": page.pop("items"), "excluded_completed": excluded_completed,
            "excluded_terminal_unlinked": excluded_terminal_unlinked, **page,
            "commitment_authority": "native Hermes Kanban; unknown when readback is unavailable"}
