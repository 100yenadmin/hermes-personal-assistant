"""Read-only life-admin radar: renewals, important dates, deadlines and unanswered offers."""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable

RADAR_KINDS = {"renewal", "important_date", "deadline"}
DEFAULT_LEAD_DAYS = {"renewal": 30, "important_date": 14, "deadline": 7}
DEFAULT_OFFER_DAYS = 3
_CLOSED = {"completed", "cancelled"}
_KANBAN_DONE = {"done", "archived"}


def _date(value: Any) -> dt.date | None:
    """YYYY-MM-DD, or a month-only YYYY-MM read as the first of that month."""
    text = str(value or "").strip()
    try:
        return dt.date.fromisoformat(text[:10] if len(text) != 7 else text + "-01")
    except ValueError:
        return None


def _occurrence(base: dt.date, yearly: bool, today: dt.date) -> dt.date:
    """The date itself, or for a yearly date the next one on or after today."""

    if not yearly:
        return base
    for year in (today.year, today.year + 1):
        try:
            candidate = base.replace(year=year)
        except ValueError:  # 29 February in a non-leap year.
            candidate = dt.date(year, 2, 28)
        if candidate >= today:
            return candidate
    return candidate


def radar_item(action: dict[str, Any], today: dt.date) -> dict[str, Any] | None:
    """Surface timing for one radar record: surface_at = next date - lead_days."""

    fields = action.get("fields", {})
    kind = fields.get("radar_kind")
    if kind not in RADAR_KINDS:
        return None
    lead = fields.get("lead_days")
    lead = lead if type(lead) is int and 0 <= lead <= 3660 else DEFAULT_LEAD_DAYS[kind]
    item = {"action_id": action["action_id"], "radar_kind": kind,
            "title": fields.get("title") or fields.get("document"), "document": fields.get("document"),
            "lead_days": lead, "recurs": "yearly" if fields.get("recurs") == "yearly" else "none",
            "source_ref": fields.get("source_ref"), "next_action": fields.get("next_action")}
    raw = str(fields.get("expires_on") or fields.get("event_date") or "").strip()
    base = _date(raw)
    if base and len(raw) == 7:
        item["date_precision"] = "month: surface_at uses the first of the month"
    if base is None:
        return {**item, "date": None, "surface_at": None, "days_until": None, "surfaced": True,
                "gap": "record has no expires_on or event_date; ask the owner for the date"}
    date = _occurrence(base, item["recurs"] == "yearly", today)
    surface_at = date - dt.timedelta(days=lead)
    return {**item, "date": date.isoformat(), "surface_at": surface_at.isoformat(),
            "days_until": (date - today).days, "surfaced": surface_at <= today}


def _offered_at(fields: dict[str, Any]) -> str | None:
    history = fields.get("history") if isinstance(fields.get("history"), list) else []
    stamps = [entry.get("at") for entry in history if isinstance(entry, dict) and entry.get("outcome") == "offered"]
    return stamps[-1] if stamps else None


def _unanswered(action: dict[str, Any], moment: dt.datetime, offer_days: int, local) -> dict[str, Any] | None:
    fields, identity = action.get("fields", {}), action["action_id"]
    if action.get("action_type") == "offer" and fields.get("outcome") == "offered":
        offered = local(_offered_at(fields) or action.get("updated_at"))
        if offered is None or moment - offered <= dt.timedelta(days=offer_days):
            return None
        offer_type = identity.split(":")[3] if identity.count(":") >= 3 else None
        return {"action_id": identity, "radar_kind": "unanswered_offer", "trip_id": action.get("trip_id"),
                "offer_type": offer_type, "offered_at": offered.isoformat(),
                "age_days": (moment - offered).days, "surfaced": True}
    if identity.startswith("cos:") and fields.get("outcome") == "unknown":
        review_at = local(fields.get("review_at"))
        if review_at is None or review_at >= moment:
            return None
        return {"action_id": identity, "radar_kind": "unanswered_recommendation",
                "title": fields.get("title"), "cos_skill": fields.get("cos_skill"),
                "offered_at": fields.get("offered_at"), "review_at": review_at.isoformat(), "surfaced": True}
    return None


def scan(ledger, data: dict[str, Any], *, kanban_reader: Callable[[str, str | None], dict[str, Any]],
         moment: dt.datetime, zone: dt.tzinfo) -> dict[str, Any]:
    """List surfaced radar items and unanswered offers; reads the ledger and writes nothing."""

    from .context import _page, _paging, local_time

    limit, offset = _paging(data)
    offer_days = data.get("offer_days", DEFAULT_OFFER_DAYS)
    if type(offer_days) is not int or not 1 <= offer_days <= 60:
        raise ValueError("offer_days must be an integer from 1 to 60")
    include_upcoming = data.get("include_upcoming") is True
    today = moment.astimezone(zone).date()
    items, upcoming = [], []
    for action in ledger.list("action"):
        fields = action.get("fields", {})
        if fields.get("radar_kind") in RADAR_KINDS:
            if action.get("status") in _CLOSED:
                continue
            task_id = fields.get("kanban_task_id")
            if task_id and kanban_reader(task_id, fields.get("kanban_board")).get("status") in _KANBAN_DONE:
                continue
            item = radar_item(action, today)
            if not item["surfaced"]:
                upcoming.append(item["surface_at"])
                if not include_upcoming:
                    continue
            items.append(item)
            continue
        offer = _unanswered(action, moment, offer_days, lambda value: local_time(value, zone) if value else None)
        if offer:
            items.append(offer)
    items.sort(key=lambda row: (not row["surfaced"], row.get("date") or row.get("offered_at") or row.get("review_at") or "",
                                row["action_id"]))
    page = _page(items, limit, offset)
    return {"radar": True, "candidates": page.pop("items"), **page,
            "not_yet_surfaced": len(upcoming), "next_surface_at": min(upcoming) if upcoming else None,
            "offer_days": offer_days, "owner_timezone": str(zone), "read_only": True}
