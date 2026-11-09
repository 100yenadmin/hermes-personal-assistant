"""Machine-readable morning brief collector (read-only)."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

from .common import Q_AWAITING, Q_BULK, Q_HUMANS, envelope, mail_accounts, mail_sections, now_utc, run_calendar, run_mail
from .config import config_dir, load_config, profile_root, validate_or_raise
from .gog_collector import DailyOpsError
from . import trip_context


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
    for index, account in enumerate(mail_accounts(cfg), 1):
        mail, mail_complete, mail_truncated = mail_sections(account, index, run_mail)
        sections.update(mail)
        complete = complete and mail_complete
        truncated = truncated or mail_truncated
        booking_query = (cfg.get("travel") or {}).get("booking_query")
        if isinstance(booking_query, str) and booking_query.strip():
            travel = run_mail(account, booking_query, page_size=25, max_items=200)
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
