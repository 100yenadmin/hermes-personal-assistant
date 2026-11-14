"""Read-only life-admin radar: renewals, important dates, deadlines and unanswered offers."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, localcontext
from typing import Any, Callable

from .expenses import _number
from .location import timezone_check

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


def _annual_cost(cost: Any) -> str | None:
    if not isinstance(cost, dict) or set(cost) != {"amount", "currency", "per"}:
        return None
    amount, currency = cost["amount"], cost["currency"]
    if (not isinstance(amount, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", amount)
            or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)
            or cost["per"] not in ("month", "year")):
        return None
    with localcontext() as ctx:
        ctx.prec = max(ctx.prec, len(amount) + 2)
        return _number(Decimal(amount) * (12 if cost["per"] == "month" else 1))


def radar_item(action: dict[str, Any], today: dt.date) -> dict[str, Any] | None:
    """Surface before the occurrence, or before a renewal's notice deadline."""

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
    if kind == "renewal":
        for key, value_type in (("auto_renews", bool), ("counterparty", str)):
            if isinstance(fields.get(key), value_type):
                item[key] = fields[key]
        if "cost" in fields:
            annual = _annual_cost(fields["cost"])
            if annual is None:
                item["gap"] = "cost must be {amount, currency, per month|year}"
            else:
                item.update(cost=fields["cost"], annual_cost=annual)
    raw = str(fields.get("expires_on") or fields.get("event_date") or "").strip()
    base = _date(raw)
    if base and len(raw) == 7:
        item["date_precision"] = "month: surface_at uses the first of the month"
    if base is None:
        return {**item, "date": None, "surface_at": None, "days_until": None, "surfaced": True,
                "gap": "record has no expires_on or event_date; ask the owner for the date" + (
                    "; " + item["gap"] if "gap" in item else "")}
    date = _occurrence(base, item["recurs"] == "yearly", today)
    surface_at = date - dt.timedelta(days=lead)
    notice = fields.get("notice_days")
    limit = 364 if item["recurs"] == "yearly" else 730  # A yearly notice of a year or more could never be met.
    if kind == "renewal" and type(notice) is int and 0 <= notice <= limit:
        decide_by = date - dt.timedelta(days=notice)
        item.update(decide_by=decide_by.isoformat(), days_until_decide_by=(decide_by - today).days)
        surface_at = decide_by - dt.timedelta(days=lead)
        if decide_by < today <= date:
            item["notice"] = f"missed: the last day to give notice was {decide_by.isoformat()}"
    elif kind == "renewal" and "notice_days" in fields:
        # Never fall back silently to the renewal date: the real deadline may already be past.
        gap = f"notice_days must be an integer from 0 to {limit}; surface_at uses the renewal date"
        item["gap"] = item["gap"] + "; " + gap if "gap" in item else gap
        surface_at = min(surface_at, today)  # Surface now, as a missing date does, so the owner fixes the terms.
    return {**item, "date": date.isoformat(), "surface_at": surface_at.isoformat(),
            "days_until": (date - today).days, "surfaced": surface_at <= today}


def _contracts(items: list[dict[str, Any]]) -> dict[str, Any]:
    currencies, renewing = {}, {"30": [], "60": [], "90": []}
    missing_cost = 0
    for item in sorted(items, key=lambda row: (row.get("date") or "", row["action_id"])):
        if item["days_until"] is not None and item["days_until"] < 0:
            continue  # Ended and not yearly: no longer an active cost.
        annual = item.get("annual_cost")
        currency = item["cost"]["currency"] if annual is not None else None
        if annual is None:
            missing_cost += 1
        else:
            bucket = currencies.setdefault(currency, {"annual_cost": "0", "active": 0})
            with localcontext() as ctx:
                ctx.prec = max(ctx.prec, len(annual) + len(bucket["annual_cost"]) + 2)
                bucket["annual_cost"] = _number(Decimal(bucket["annual_cost"]) + Decimal(annual))
            bucket["active"] += 1
        if item["days_until"] is None:
            continue
        row = {key: item.get(key) for key in ("action_id", "title", "date", "decide_by", "auto_renews", "annual_cost")}
        row["currency"] = currency
        for window in renewing:
            if item["days_until"] <= int(window):
                renewing[window].append(row)
    return {"currencies": currencies, "renewing": renewing, "missing_cost": missing_cost}


def _offered_at(fields: dict[str, Any]) -> str | None:
    history = fields.get("history") if isinstance(fields.get("history"), list) else []
    stamps = [entry.get("at") for entry in history if isinstance(entry, dict) and entry.get("outcome") == "offered"]
    return stamps[-1] if stamps else None


def _offer_type(identity: str, trip_id: Any) -> str | None:
    """The type in pa:offer:<trip_id>:<type>[:<occurrence>]; trip IDs may contain colons."""

    prefix = f"pa:offer:{trip_id}:" if isinstance(trip_id, str) and trip_id else None
    if prefix and identity.startswith(prefix):
        return identity[len(prefix):].split(":")[0] or None
    return identity.split(":")[3] if identity.count(":") >= 3 else None


def _unanswered(action: dict[str, Any], moment: dt.datetime, offer_days: int, local,
                opt_outs: set[str]) -> dict[str, Any] | None:
    fields, identity = action.get("fields", {}), action["action_id"]
    if action.get("action_type") == "offer" and fields.get("outcome") == "offered":
        offered = local(_offered_at(fields) or action.get("updated_at"))
        if offered is None or moment - offered <= dt.timedelta(days=offer_days):
            return None
        offer_type = _offer_type(identity, action.get("trip_id"))
        if f"pa:offer:*:{offer_type}" in opt_outs:
            return None
        return {"action_id": identity, "radar_kind": "unanswered_offer", "trip_id": action.get("trip_id"),
                "offer_type": offer_type, "offered_at": offered.isoformat(),
                "age_days": (moment - offered).days, "lead_days": offer_days, "surfaced": True}
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

    from .context import _page, _paging, local_time, loop_state

    limit, offset = _paging(data)
    offer_days = data.get("offer_days", DEFAULT_OFFER_DAYS)
    if type(offer_days) is not int or not 1 <= offer_days <= 60:
        raise ValueError("offer_days must be an integer from 1 to 60")
    include_upcoming = data.get("include_upcoming") is True
    contracts = data.get("contracts") is True
    today = moment.astimezone(zone).date()
    items, upcoming = [], []
    renewals = []
    actions = ledger.list("action")
    opt_outs = {action["action_id"] for action in actions
                if action.get("action_type") == "offer" and action.get("fields", {}).get("outcome") == "opted_out"}
    for action in actions:
        if data.get("trip_id") and action.get("trip_id") != data["trip_id"]:
            continue
        fields = action.get("fields", {})
        state = loop_state(action, {})
        if data.get("loops_only") is True and state is None:
            continue
        if fields.get("radar_kind") in RADAR_KINDS:
            task_id = fields.get("kanban_task_id")
            kanban = kanban_reader(task_id, fields.get("kanban_board")) if task_id else {}
            state = loop_state(action, kanban)
            if state == "closed" or (state is None and (
                action.get("status") in _CLOSED or kanban.get("status") in _KANBAN_DONE
            )):
                continue
            item = radar_item(action, today)
            # Only records with contract terms; a passport or visa renewal is not a contract and has no cost.
            if contracts and item["radar_kind"] == "renewal" and any(
                    key in fields for key in ("cost", "notice_days", "auto_renews", "counterparty")):
                renewals.append(item)
            if state:
                item["loop_state"] = state
            if not item["surfaced"]:
                upcoming.append(item["surface_at"])
                if not include_upcoming:
                    continue
            items.append(item)
            continue
        offer = _unanswered(action, moment, offer_days, lambda value: local_time(value, zone) if value else None,
                            opt_outs)
        if offer:
            items.append(offer)
    if not data.get("trip_id") and data.get("loops_only") is not True:
        timezone_item = timezone_check(ledger, moment)
        if timezone_item:
            items.append(timezone_item)
    items.sort(key=lambda row: (not row["surfaced"], row.get("date") or row.get("offered_at") or row.get("review_at")
                                or row.get("evidence", {}).get("at") or "",
                                row["action_id"]))
    page = _page(items, limit, offset)
    result = {"radar": True, "candidates": page.pop("items"), **page,
            "not_yet_surfaced": len(upcoming), "next_surface_at": min(upcoming) if upcoming else None,
            "offer_days": offer_days, "owner_timezone": str(zone), "read_only": True}
    if contracts:
        result["contracts"] = _contracts(renewals)
    return result
