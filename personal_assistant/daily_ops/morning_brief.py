"""Machine-readable morning brief collector (read-only)."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

from .common import envelope, now_utc, run_calendar, run_mail
from .config import config_dir, load_config, profile_root, validate_or_raise
from .gog_collector import DailyOpsError
from . import trip_context

Q_HUMANS = "is:unread -category:promotions -category:updates -category:social -category:forums newer_than:2d"
Q_BULK = "is:unread (category:promotions OR category:updates OR category:social OR category:forums) newer_than:3d"


def collect(cfg: dict, *, profile: str | None = None, moment: dt.datetime | None = None) -> dict:
    current = moment or now_utc()
    work = (cfg.get("accounts") or {}).get("work")
    if not work:
        raise DailyOpsError("accounts.work is required for the morning brief")
    calendar = run_calendar(cfg, 2, profile=profile)
    context = trip_context.trip_context(cfg, current, profile)
    sections = {
        "trip_context": context,
        "calendar_next_36h": {"items": calendar.items, "count": len(calendar.items), "complete": calendar.complete, "truncated": calendar.truncated, "coverage": calendar.coverage},
    }
    complete = calendar.complete
    truncated = calendar.truncated
    calendar_first = (cfg.get("calendar") or {}).get("provider") == "profile_google"
    for index, account in enumerate((value for value in ((cfg.get("accounts") or {}).get("work"), (cfg.get("accounts") or {}).get("personal")) if value), 1):
        try:
            humans = run_mail(account, Q_HUMANS, page_size=25, max_items=500)
        except DailyOpsError:
            if not calendar_first:
                raise
            humans = None
        try:
            bulk = run_mail(account, Q_BULK, page_size=100, max_items=2000)
        except DailyOpsError:
            if not calendar_first:
                raise
            bulk = None
        if humans is None:
            sections[f"humans_{index}"] = {"items": [], "count": 0, "complete": False, "truncated": False, "status": "mail provider unavailable"}
            complete = False
        else:
            sections[f"humans_{index}"] = {
                "items": humans.items[:25], "count": len(humans.items), "complete": humans.complete, "truncated": humans.truncated,
            }
            complete = complete and humans.complete
            truncated = truncated or humans.truncated
        if bulk is None:
            sections[f"bulk_{index}"] = {"count": 0, "exact": False, "lower_bound": 0, "sample": [], "complete": False, "truncated": False, "status": "mail provider unavailable"}
            complete = False
        else:
            bulk_count = bulk.total if bulk.total is not None else len(bulk.items)
            sections[f"bulk_{index}"] = {
                "count": bulk_count, "exact": bulk.total is not None and bulk.complete,
                "lower_bound": len(bulk.items), "sample": bulk.items[:3],
                "complete": bulk.complete, "truncated": bulk.truncated,
            }
            complete = complete and bulk.complete
            truncated = truncated or bulk.truncated
        booking_query = (cfg.get("travel") or {}).get("booking_query")
        if isinstance(booking_query, str) and booking_query.strip():
            try:
                travel = run_mail(account, booking_query, page_size=25, max_items=200)
            except DailyOpsError:
                if not calendar_first:
                    raise
                travel = None
            if travel is None:
                sections[f"travel_detect_{index}"] = {"items": [], "count": 0, "complete": False, "truncated": False, "status": "mail provider unavailable"}
                complete = False
            else:
                sections[f"travel_detect_{index}"] = {
                    "items": travel.items[:10], "count": len(travel.items), "complete": travel.complete, "truncated": travel.truncated,
                }
                complete = complete and travel.complete
                truncated = truncated or travel.truncated
    return envelope("morning_brief", cfg, current, current + dt.timedelta(hours=36), sections, complete=complete, truncated=truncated)


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
