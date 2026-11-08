"""Accepted calendar reads through the gog CLI for every daily-ops consumer; PA holds no Google token."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .common import MAX_ITEMS, Collected, collect_pages
from .gog_collector import DailyOpsError, iter_events


def _calendar_config(cfg: dict) -> tuple[str, dict, bool]:
    account = (cfg.get("accounts") or {}).get("work")
    settings = cfg.get("calendar")
    if settings is None:
        # Existing daily-ops profiles retain their previously accepted gog
        # primary-calendar behavior until they opt into the v0.3 read scope.
        return account, {"calendar_ids": ["primary"]}, True
    if not isinstance(settings, dict):
        raise DailyOpsError("calendar configuration must be an object")
    read_scope = settings.get("read_scope")
    if settings.get("provider") != "gog":
        # PA holds no Google token; profile_google was removed with Calendar sync.
        raise DailyOpsError("calendar.provider must be gog")
    if not isinstance(read_scope, dict) or read_scope.get("accepted") is not True:
        raise DailyOpsError("calendar.read_scope.accepted must be true")
    if read_scope.get("include_pa_binding") not in {None, False}:
        raise DailyOpsError("calendar.read_scope.include_pa_binding was removed with Calendar sync")
    account = settings.get("account") or account
    if not isinstance(account, str) or "@" not in account:
        raise DailyOpsError("calendar account is missing or invalid")
    return account, read_scope, False


def _accepted_sources(cfg: dict) -> tuple[str, list[str], bool]:
    account, read_scope, legacy = _calendar_config(cfg)
    raw_ids = read_scope.get("calendar_ids")
    if not isinstance(raw_ids, list) or any(not isinstance(value, str) or not value.strip() for value in raw_ids):
        raise DailyOpsError("calendar.read_scope.calendar_ids must be a list of calendar IDs")
    deduped: list[str] = []
    seen: set[str] = set()
    for calendar_id in (value.strip() for value in raw_ids):
        if calendar_id.casefold() not in seen:
            seen.add(calendar_id.casefold())
            deduped.append(calendar_id)
    if not deduped:
        raise DailyOpsError("calendar read scope contains no accepted calendars")
    return account, deduped, legacy


def _time_value(value: Any, field: str) -> dict:
    if isinstance(value, str):
        key = "dateTime" if "T" in value else "date"
        return {key: value}
    if not isinstance(value, Mapping):
        raise DailyOpsError(f"calendar event {field} is missing or invalid")
    result = {}
    for key in ("date", "dateTime", "timeZone"):
        if key in value:
            if not isinstance(value[key], str):
                raise DailyOpsError(f"calendar event {field}.{key} is invalid")
            result[key] = value[key]
    if not (result.get("date") or result.get("dateTime")):
        raise DailyOpsError(f"calendar event {field} has no typed value")
    return result


def _event_packet(event: Mapping[str, Any], source: str) -> dict:
    if not isinstance(event.get("id") or event.get("iCalUID"), (str, int)):
        raise DailyOpsError("calendar event identity is missing or invalid")
    start = _time_value(event.get("start"), "start")
    end = _time_value(event.get("end"), "end")
    packet = {
        "id": str(event.get("id") or event.get("iCalUID")),
        "summary": str(event.get("summary") or "(untitled)"),
        "start": start,
        "end": end,
        "timezone": str(start.get("timeZone") or end.get("timeZone") or event.get("timezone") or ""),
        "url": str(event.get("htmlLink") or event.get("url") or ((event.get("source") or {}).get("url") if isinstance(event.get("source"), Mapping) else "") or ""),
        "location": str(event.get("location") or ""),
        "description": str(event.get("description") or ""),
        "status": str(event.get("status") or ""),
        "calendar_source": source,
    }
    for key in ("iCalUID", "recurringEventId", "originalStartTime", "updated", "etag", "sequence"):
        if key in event:
            packet[key] = copy.deepcopy(event[key])
    return packet


def _sort_key(event: dict) -> str:
    start = event.get("start") or {}
    return str(start.get("dateTime") or start.get("date") or "")


def collect_calendar_scope(cfg: dict, days: int, *, profile: str | None = None, service=None) -> Collected:
    """Read each explicitly accepted source through gog and expose source-level coverage."""
    if not isinstance(days, int) or isinstance(days, bool) or not 0 <= days <= 366:
        raise DailyOpsError("calendar read days must be an integer from 0 to 366")
    account, sources, legacy = _accepted_sources(cfg)
    events: list[dict] = []
    coverage: list[dict] = []
    successful = 0
    aggregate_complete = True
    aggregate_truncated = False
    for index, calendar_id in enumerate(sources, 1):
        label = f"calendar-{index}"
        try:
            result = collect_pages(account, ["calendar", "events", calendar_id, f"--days={days}"], iter_events, page_size=40, max_items=MAX_ITEMS)
            packets = (
                [copy.deepcopy(dict(item)) for item in result.items]
                if legacy
                else [_event_packet(item, label) for item in result.items]
            )
        except Exception:
            coverage.append({"source": label, "origin": "configured", "provider": "gog", "status": "error", "complete": False, "truncated": False})
            aggregate_complete = False
            continue
        successful += 1
        events.extend(packets)
        coverage.append({"source": label, "origin": "configured", "provider": "gog", "status": "complete" if result.complete else "partial", "complete": result.complete, "truncated": result.truncated})
        aggregate_complete = aggregate_complete and result.complete
        aggregate_truncated = aggregate_truncated or result.truncated
    if successful == 0:
        raise DailyOpsError("calendar read failed for every accepted source")
    events.sort(key=_sort_key)
    if len(events) > MAX_ITEMS:
        events = events[:MAX_ITEMS]
        aggregate_complete = False
        aggregate_truncated = True
    if legacy and coverage:
        coverage[0]["scope"] = "legacy-primary"
    return Collected(events, aggregate_complete, aggregate_truncated, None, coverage)


__all__ = ["collect_calendar_scope"]
