"""Accepted, profile-bound calendar reads for every daily-ops consumer."""
from __future__ import annotations

import copy
import datetime as dt
from collections.abc import Mapping
from typing import Any

from ..calendar import CalendarAuthError, build_calendar_service
from ..state import Ledger
from .common import MAX_ITEMS, MAX_PAGES, Collected, collect_pages, now_utc
from .gog_collector import DailyOpsError, iter_events

PAGE_SIZE = 250


def _execute(request: Any) -> Any:
    execute = getattr(request, "execute", None)
    return execute() if callable(execute) else request


def _calendar_config(cfg: dict) -> tuple[str, str, dict, bool]:
    account = (cfg.get("accounts") or {}).get("work")
    settings = cfg.get("calendar")
    if settings is None:
        # Existing daily-ops profiles retain their previously accepted gog
        # primary-calendar behavior until they opt into the v0.3 read scope.
        return "gog", account, {"calendar_ids": ["primary"], "include_pa_binding": False}, True
    if not isinstance(settings, dict):
        raise DailyOpsError("calendar configuration must be an object")
    provider = settings.get("provider")
    read_scope = settings.get("read_scope")
    if provider not in {"profile_google", "gog"}:
        raise DailyOpsError("calendar.provider must be profile_google or gog")
    if not isinstance(read_scope, dict) or read_scope.get("accepted") is not True:
        raise DailyOpsError("calendar.read_scope.accepted must be true")
    account = settings.get("account") or account
    if not isinstance(account, str) or "@" not in account:
        raise DailyOpsError("calendar account is missing or invalid")
    return provider, account, read_scope, False


def _accepted_sources(cfg: dict, profile: str | None) -> tuple[str, str, list[tuple[str, str]], list[dict], bool]:
    provider, account, read_scope, legacy = _calendar_config(cfg)
    raw_ids = read_scope.get("calendar_ids")
    if not isinstance(raw_ids, list) or any(not isinstance(value, str) or not value.strip() for value in raw_ids):
        raise DailyOpsError("calendar.read_scope.calendar_ids must be a list of calendar IDs")
    sources: list[tuple[str, str]] = [(value.strip(), "configured") for value in raw_ids]
    unavailable: list[dict] = []
    if read_scope.get("include_pa_binding") is True:
        if not profile:
            unavailable.append({"source": "pa-binding", "status": "unavailable", "reason": "profile not supplied"})
        else:
            binding = Ledger(profile).get("action", "pa:calendar-binding")
            fields = binding.get("fields", {}) if isinstance(binding, dict) else {}
            if not binding or binding.get("status") != "bound" or not isinstance(fields, dict):
                unavailable.append({"source": "pa-binding", "status": "unavailable", "reason": "binding not active"})
            elif str(fields.get("expected_account", "")).casefold() != account.casefold():
                raise DailyOpsError("PA calendar binding account does not match the accepted read account")
            else:
                calendar_id = fields.get("calendar_id")
                if not isinstance(calendar_id, str) or not calendar_id.strip():
                    unavailable.append({"source": "pa-binding", "status": "unavailable", "reason": "binding calendar missing"})
                else:
                    sources.append((calendar_id.strip(), "pa-binding"))
    elif read_scope.get("include_pa_binding") not in {None, False}:
        raise DailyOpsError("calendar.read_scope.include_pa_binding must be a boolean")

    deduped: list[tuple[str, str]] = []
    seen: dict[str, int] = {}
    for calendar_id, origin in sources:
        folded = calendar_id.casefold()
        if folded in seen:
            index = seen[folded]
            prior_id, prior_origin = deduped[index]
            if origin not in prior_origin.split("+"):
                deduped[index] = (prior_id, f"{prior_origin}+{origin}")
            continue
        seen[folded] = len(deduped)
        deduped.append((calendar_id, origin))
    if not deduped and not unavailable:
        raise DailyOpsError("calendar read scope contains no accepted calendars")
    return provider, account, deduped, unavailable, legacy


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


def _profile_pages(service: Any, calendar_id: str, start: dt.datetime, end: dt.datetime) -> Collected:
    items: list[dict] = []
    token = None
    truncated = False
    complete = True
    for _ in range(MAX_PAGES):
        kwargs = {
            "calendarId": calendar_id,
            "timeMin": start.isoformat().replace("+00:00", "Z"),
            "timeMax": end.isoformat().replace("+00:00", "Z"),
            "maxResults": PAGE_SIZE,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if token:
            kwargs["pageToken"] = token
        data = _execute(service.events().list(**kwargs))
        if not isinstance(data, Mapping) or not isinstance(data.get("items", []), list):
            raise DailyOpsError("Google Calendar returned an invalid event page")
        batch = data.get("items", [])
        if any(not isinstance(item, Mapping) for item in batch):
            raise DailyOpsError("Google Calendar returned an invalid event member")
        items.extend(batch)
        if len(items) > MAX_ITEMS:
            items = items[:MAX_ITEMS]
            complete = False
            truncated = True
            break
        token = data.get("nextPageToken")
        if token is None:
            break
        if not isinstance(token, str) or not token:
            raise DailyOpsError("Google Calendar returned an invalid page token")
    else:
        complete = False
        truncated = True
    return Collected(items, complete, truncated, None)


def _sort_key(event: dict) -> str:
    start = event.get("start") or {}
    return str(start.get("dateTime") or start.get("date") or "")


def collect_calendar_scope(cfg: dict, days: int, *, profile: str | None = None, service=None) -> Collected:
    """Read each explicitly accepted source and expose source-level coverage."""
    if not isinstance(days, int) or isinstance(days, bool) or not 0 <= days <= 366:
        raise DailyOpsError("calendar read days must be an integer from 0 to 366")
    provider, account, sources, coverage, legacy = _accepted_sources(cfg, profile)
    current = now_utc()
    end = current + dt.timedelta(days=days)
    if provider == "profile_google":
        if not profile:
            raise DailyOpsError("profile_google calendar reads require the active profile")
        try:
            service = service or build_calendar_service(profile, access="read")
            identity = _execute(service.calendars().get(calendarId="primary"))
        except (CalendarAuthError, OSError, ValueError, TypeError) as exc:
            raise DailyOpsError("existing profile Google Calendar authorization is unavailable") from exc
        if not isinstance(identity, Mapping) or str(identity.get("id", "")).casefold() != account.casefold():
            raise DailyOpsError("Google Calendar account does not match the accepted read account")

    events: list[dict] = []
    successful = 0
    aggregate_complete = not coverage
    aggregate_truncated = False
    for index, (calendar_id, origin) in enumerate(sources, 1):
        label = f"calendar-{index}"
        try:
            if provider == "profile_google":
                result = _profile_pages(service, calendar_id, current, end)
            else:
                result = collect_pages(account, ["calendar", "events", calendar_id, f"--days={days}"], iter_events, page_size=40, max_items=MAX_ITEMS)
            packets = (
                [copy.deepcopy(dict(item)) for item in result.items]
                if legacy
                else [_event_packet(item, label) for item in result.items]
            )
        except Exception:
            coverage.append({"source": label, "origin": origin, "provider": provider, "status": "error", "complete": False, "truncated": False})
            aggregate_complete = False
            continue
        successful += 1
        events.extend(packets)
        coverage.append({"source": label, "origin": origin, "provider": provider, "status": "complete" if result.complete else "partial", "complete": result.complete, "truncated": result.truncated})
        aggregate_complete = aggregate_complete and result.complete
        aggregate_truncated = aggregate_truncated or result.truncated
    if sources and successful == 0:
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
