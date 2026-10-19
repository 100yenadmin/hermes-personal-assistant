"""Machine-readable evening register collector (read-only)."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

from .common import envelope, now_utc, run_calendar
from .config import load_config, profile_root, validate_or_raise
from .gog_collector import DailyOpsError
from . import trip_context


def _event_start(event: dict, zone: ZoneInfo):
    start = event.get("start") if isinstance(event, dict) else None
    if not isinstance(start, dict):
        return None
    raw = start.get("dateTime") or start.get("date")
    if not isinstance(raw, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00")) if "T" in raw else dt.datetime.combine(dt.date.fromisoformat(raw), dt.time(), zone)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def _tomorrow_events(events: list[dict], zone: ZoneInfo, tomorrow: dt.date) -> list[dict]:
    selected = []
    for event in events:
        when = _event_start(event, zone)
        if when is None or when.date() != tomorrow:
            continue
        selected.append(event)
    return sorted(selected, key=lambda item: _event_start(item, zone) or dt.datetime.max.replace(tzinfo=zone))


def _timeline_item(event: dict, zone: ZoneInfo) -> dict:
    start = _event_start(event, zone)
    start_data = event.get("start") if isinstance(event, dict) else {}
    end_data = event.get("end") if isinstance(event, dict) else {}
    return {
        "id": str(event.get("id") or event.get("iCalUID") or "event"),
        "summary": str(event.get("summary") or "(untitled)"),
        "start": start.isoformat() if start else start_data,
        "end": end_data,
        "location": str(event.get("location") or ""),
    }


def collect(cfg: dict, *, profile: str | None = None, moment: dt.datetime | None = None) -> dict:
    current = (moment or now_utc()).astimezone(ZoneInfo(cfg["timezone"]))
    zone = ZoneInfo(cfg["timezone"])
    tomorrow = current.date() + dt.timedelta(days=1)
    start_local = dt.datetime.combine(tomorrow, dt.time(), zone)
    end_local = start_local + dt.timedelta(days=1)
    work = (cfg.get("accounts") or {}).get("work")
    if not work:
        raise DailyOpsError("accounts.work is required for the evening register")
    calendar = run_calendar(cfg, 2, profile=profile)
    events = _tomorrow_events(calendar.items, zone, tomorrow)
    timeline = [_timeline_item(event, zone) for event in events]
    first = timeline[0] if timeline else None
    prep_flags = []
    for item in timeline:
        if not item["location"]:
            prep_flags.append({"event_id": item["id"], "flag": "location not supplied"})
        if not item["end"]:
            prep_flags.append({"event_id": item["id"], "flag": "duration not supplied"})
    sections = {
        "trip_context": trip_context.trip_context(cfg, current.astimezone(dt.timezone.utc), profile),
        "tomorrow_timeline": {"items": timeline, "count": len(timeline), "coverage": calendar.coverage},
        "first_commitment": first,
        "prep_flags": prep_flags,
    }
    return envelope("evening_register", cfg, start_local, end_local, sections, complete=calendar.complete, truncated=calendar.truncated)


def main() -> None:
    try:
        cfg = validate_or_raise(load_config())
        result = collect(cfg, profile=os.fspath(profile_root()))
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    except DailyOpsError as exc:
        print(f"⚠️ daily-ops pipeline failure: {exc}")
        raise SystemExit(1)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"⚠️ daily-ops pipeline failure: {type(exc).__name__} — fix before next run")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
