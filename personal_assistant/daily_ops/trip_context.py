"""Trip context sourced from the existing PA trip ledger.

Daily-ops never maintains a second itinerary store. Coordinates are optional
facts on a ledger trip and are used only with the customer's explicit geocoder
consent; missing or overlapping origins remain visibly unknown.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any
from zoneinfo import ZoneInfo

from . import geo
from .common import run_calendar
from .config import profile_root
from .gog_collector import DailyOpsError, alias_emails, iter_events, unwrap
from ..state import Ledger, stable_id


def _today_in(cfg: dict, now_utc: dt.datetime) -> str:
    return now_utc.astimezone(ZoneInfo(cfg.get("timezone") or "UTC")).date().isoformat()


def _valid_point(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        lat, lng = float(value["lat"]), float(value.get("lng", value.get("lon")))
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def _row_fields(row: dict) -> dict:
    fields = row.get("fields", {}) if isinstance(row, dict) else {}
    return fields if isinstance(fields, dict) else {}


def _trip_base(fields: dict, today: str) -> tuple[tuple[float, float] | None, str | None]:
    # These are names already used by PA trip records, not a new file schema.
    for key in ("base", "origin", "current_base", "default_base"):
        point = _valid_point(fields.get(key))
        if point:
            value = fields[key]
            return point, str(value.get("label") or value.get("city") or value.get("base") or "trip base")
    segments = fields.get("segments")
    if isinstance(segments, list):
        matches = []
        for segment in segments:
            if not isinstance(segment, dict) or not (segment.get("start") and segment.get("end")):
                continue
            if segment["start"] <= today <= segment["end"] and _valid_point(segment):
                matches.append(segment)
        if matches:
            selected = sorted(matches, key=lambda value: value["start"])[-1]
            return _valid_point(selected), str(selected.get("label") or selected.get("city") or "trip base")
    return None, None


def load_trip_store(profile: str | None = None) -> list[dict]:
    try:
        root = profile_root() if profile is None else profile
        return Ledger(root).list("trip")
    except (DailyOpsError, OSError, ValueError, RuntimeError) as exc:
        raise DailyOpsError("PA trip store is unavailable; travel context is unknown") from exc


def trip_context(cfg: dict, now_utc: dt.datetime, profile: str | None = None) -> dict:
    """Return bounded, redacted context from active PA trip-store records."""
    today = _today_in(cfg, now_utc)
    rows = load_trip_store(profile)
    active = [row for row in rows if row.get("status", "active") == "active"]
    candidates = []
    for row in active:
        fields = _row_fields(row)
        point, label = _trip_base(fields, today)
        events = fields.get("events") if isinstance(fields.get("events"), list) else []
        if point or events:
            candidates.append((row, point, label, events))
    if len(candidates) != 1:
        reason = "no active trip" if not candidates else "multiple active trip origins or no usable origin"
        return {"source": "pa_trip_store", "date": today, "status": "unknown", "reason": reason}
    row, point, label, events = candidates[0]
    data = {
        "source": "pa_trip_store",
        "date": today,
        "status": "known" if point else "unknown",
        "trip_id": row.get("trip_id"),
        "title": alias_emails(str(row.get("title") or "trip"))[0],
        "source_revision": row.get("updated_at"),
        "events": len(events),
    }
    data["base"] = {"label": label, "coordinates": {"lat": point[0], "lng": point[1]}} if point else None
    if not point:
        data["reason"] = "active PA trip has no unambiguous coordinate origin"
    return data


def physical_location(event: dict) -> str | None:
    location = unwrap(str(event.get("location") or "")).strip()
    if not location:
        return None
    lowered = location.lower()
    if any(marker in lowered for marker in ("http", "zoom.us", "meet.google", "teams.microsoft")):
        return None
    return alias_emails(location.split("·")[0].strip(" ,"))[0] or None


def _event_identity(event: dict, start: str, revision: str | None) -> str:
    raw = event.get("id") or event.get("uid") or event.get("iCalUID")
    return stable_id("pa-leave-by", str(raw or "event"), start, str(revision or event.get("sequence") or "none"))


def leave_by_alerts(cfg: dict, events: list[dict], now_utc: dt.datetime, route_minutes, *, base=None, departures=()) -> list[dict]:
    travel = cfg.get("travel") or {}
    geocoder = travel.get("geocoder") or {}
    watched = []
    for item in departures:
        try:
            watched.append((dt.datetime.fromisoformat(item["departure_at"].replace("Z", "+00:00")),
                            dt.datetime.fromisoformat(item["leave_by_at"].replace("Z", "+00:00"))))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    if travel.get("leave_by") is not True or (not watched and (geocoder.get("consent") is not True or not base)):
        return []
    try:
        heads_up = int(travel.get("heads_up_min", 45))
        buffer_min = int(travel.get("buffer_min", 15))
    except (TypeError, ValueError):
        raise DailyOpsError("travel window settings must be integers")
    alerts = []
    for event in iter_events(events or []):
        start_data = event.get("start")
        if not isinstance(start_data, dict) or not isinstance(start_data.get("dateTime"), str):
            continue  # all-day events have no exact leave time
        iso = start_data["dateTime"]
        try:
            starts = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            continue
        if starts.tzinfo is None:
            continue
        delta = starts - now_utc
        if delta < dt.timedelta(0) or delta > dt.timedelta(hours=6):
            continue
        matched = sorted((abs((starts - departure).total_seconds()), leave) for departure, leave in watched
                         if departure.tzinfo and leave.tzinfo and abs((starts - departure).total_seconds()) <= 90 * 60)
        if matched:
            leave_at = matched[0][1]  # The flight closest to the event, not the earliest leave time.
        else:
            if geocoder.get("consent") is not True or not base:
                continue
            origin, label = base
            address = physical_location(event)
            if not address:
                continue
            try:
                destination = geo.geocode(address, geocoder)
                minutes = route_minutes(origin, destination) if destination else None
            except (DailyOpsError, OSError, ValueError, TypeError):
                continue
            if minutes is None:
                continue
            leave_at = starts - dt.timedelta(minutes=int(minutes) + buffer_min)
        remaining = round((leave_at - now_utc).total_seconds() / 60)
        # A 15–20-minute tick can miss a five-minute departure window.
        # Keep the stable `now` phase eligible through event start; the
        # earlier delta check excludes past events and the state key dedups.
        if remaining > heads_up:
            continue
        local = starts.astimezone(ZoneInfo(cfg.get("timezone") or "UTC")).strftime("%H:%M")
        title = alias_emails(unwrap(str(event.get("summary") or "")).strip() or "(untitled)")[0]
        phase = "now" if remaining <= 0 else "heads"
        revision = event.get("etag") or event.get("updated") or event.get("sequence")
        occurrence = _event_identity(event, iso, revision)
        if matched:
            occurrence = stable_id(occurrence, leave_at.isoformat())
        airport_time = leave_at.astimezone(ZoneInfo(cfg.get("timezone") or "UTC")).strftime("%H:%M")
        line = (f"✈️ {'LEAVE NOW' if phase == 'now' else f'leave in {remaining}m'} — {title} · airport leave-by {airport_time}" if matched else
                f"🚗 {'LEAVE NOW' if phase == 'now' else f'leave in {remaining}m'} — {title} "
                f"at {local} · {int(minutes)}m drive + {buffer_min}m buffer · from {label}")
        alerts.append({
            "line": line,
            "key": stable_id(occurrence, phase),
            "occurrence": occurrence,
            "phase": phase,
            "start": iso,
        })
    return alerts


def run_calendar_events(cfg: dict, profile: str | None = None):
    account = (cfg.get("accounts") or {}).get("work")
    if not account:
        raise DailyOpsError("accounts.work is required for leave-by calendar reads")
    return run_calendar(cfg, 1, profile=profile)


def collect_trip(cfg: dict, now_utc: dt.datetime, route_minutes, profile: str | None = None) -> tuple[dict, list[dict], bool, bool]:
    context = trip_context(cfg, now_utc, profile)
    if cfg.get("travel", {}).get("leave_by") is not True:
        return context, [], True, False
    calendar = run_calendar_events(cfg, profile)
    context = dict(context)
    context["calendar_coverage"] = calendar.coverage
    events = calendar.items
    base_data = context.get("base")
    base = None
    if isinstance(base_data, dict) and isinstance(base_data.get("coordinates"), dict):
        point = _valid_point(base_data["coordinates"])
        if point:
            base = (point, base_data.get("label") or "trip base")
    try:
        from .. import trip_watch
        departures = trip_watch.departures(Ledger(profile if profile is not None else profile_root()))
    except Exception:
        departures = ()
    return context, leave_by_alerts(cfg, events, now_utc, route_minutes, base=base, departures=departures), calendar.complete, calendar.truncated


def trip_sections(cfg: dict, now_utc: dt.datetime, route_minutes, profile: str | None = None):
    """Compatibility entrypoint returning only leave-by alerts."""
    return collect_trip(cfg, now_utc, route_minutes, profile)[1]
