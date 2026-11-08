"""Shared bounded collection and JSON-boundary helpers."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .gog_collector import DailyOpsError, alias_emails, iter_events, iter_threads, page, run

PAGE_SIZE = 25
MAX_PAGES = 20
MAX_ITEMS = 1000
# Twice-daily triage reads: the morning brief and the evening register share these.
HUMANS_SHOWN = 25
Q_HUMANS = "is:unread -category:promotions -category:updates -category:social -category:forums newer_than:2d"
Q_BULK = "is:unread (category:promotions OR category:updates OR category:social OR category:forums) newer_than:3d"


@dataclass
class Collected:
    items: list[dict]
    complete: bool
    truncated: bool
    total: int | None
    coverage: list[dict] = field(default_factory=list)


def collect_pages(account: str, base_args: list[str], parser: Callable[[Any], list[dict]], *, page_size: int = PAGE_SIZE, max_items: int = MAX_ITEMS) -> Collected:
    items: list[dict] = []
    cursor = None
    cursors: set[str] = set()
    provider_total = None
    complete = True
    truncated = False
    for page_number in range(MAX_PAGES):
        args = list(base_args)
        args += [f"--max={page_size}"]
        if cursor:
            args.append(f"--page={cursor}")
        data = run(account, args)
        batch, has_more, next_cursor, total = page(data, parser, page_size=page_size)
        if total is not None:
            provider_total = total
        items.extend(batch)
        if len(items) > max_items:
            items = items[:max_items]
            complete = False
            truncated = True
            break
        if not has_more:
            break
        if not next_cursor:
            # Bare arrays have no completeness metadata. Never label a
            # page-sized bare response complete, but do not invent a second
            # provider request with an unknown cursor.
            complete = False
            truncated = True
            break
        if next_cursor in cursors:
            raise DailyOpsError("GOG_BADSHAPE: pagination cursor repeated")
        cursors.add(next_cursor)
        cursor = next_cursor
    else:
        complete = False
        truncated = True
    if cursor and complete is False and len(cursors) >= MAX_PAGES - 1:
        truncated = True
    return Collected(items, complete, truncated, provider_total)


def now_utc() -> dt.datetime:
    import os
    raw = os.environ.get("DAILY_OPS_NOW")
    if raw:
        try:
            value = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DailyOpsError("DAILY_OPS_NOW is not a valid timezone-aware timestamp") from exc
        if value.tzinfo is None:
            raise DailyOpsError("DAILY_OPS_NOW must include a timezone")
        return value.astimezone(dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def redacted(value: Any) -> Any:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    safe, _ = alias_emails(text)
    return json.loads(safe)


def _bounded(value: Any, *, depth: int = 0) -> tuple[Any, bool]:
    """Return bounded content and whether any content was actually removed."""
    if depth > 6:
        return "[truncated]", True
    if isinstance(value, str):
        return value[:800], len(value) > 800
    if isinstance(value, list):
        result = []
        truncated = len(value) > 50
        for item in value[:50]:
            bounded_item, item_truncated = _bounded(item, depth=depth + 1)
            result.append(bounded_item)
            truncated = truncated or item_truncated
        if len(value) > 50:
            result.append("[items truncated]")
        return result, truncated
    if isinstance(value, dict):
        result = {}
        truncated = len(value) > 80
        for key, item in list(value.items())[:80]:
            bounded_item, item_truncated = _bounded(item, depth=depth + 1)
            result[str(key)[:80]] = bounded_item
            truncated = truncated or item_truncated or len(str(key)) > 80
        if len(value) > 80:
            result["_truncated_fields"] = True
        return result, truncated
    return value, False


def bounded(value: Any, *, depth: int = 0) -> Any:
    """Bound every emitted value, not only the number of top-level items."""
    return _bounded(value, depth=depth)[0]


def envelope(kind: str, cfg: dict, window_start: dt.datetime, window_end: dt.datetime, sections: dict, *, complete: bool, truncated: bool) -> dict:
    bounded_sections, content_truncated = _bounded(redacted(sections))
    return {
        "schema": "personal-assistant.daily-ops.v3",
        "kind": kind,
        "window": {
            "timezone": cfg["timezone"],
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
        "complete": bool(complete) and not content_truncated,
        "truncated": bool(truncated) or content_truncated,
        "sections": bounded_sections,
    }


def run_calendar(account_or_config: str | dict, days: int, *, profile: str | None = None, service=None) -> Collected:
    if isinstance(account_or_config, str):
        return collect_pages(account_or_config, ["calendar", "events", "primary", f"--days={days}"], iter_events, page_size=40, max_items=1000)
    from .calendar_source import collect_calendar_scope
    return collect_calendar_scope(account_or_config, days, profile=profile, service=service)


def run_mail(account: str, query: str, *, page_size: int, max_items: int) -> Collected:
    return collect_pages(account, ["gmail", "search", query], iter_threads, page_size=page_size, max_items=max_items)


def mail_accounts(cfg: dict) -> list[str]:
    accounts = cfg.get("accounts") or {}
    return [value for value in (accounts.get("work"), accounts.get("personal")) if value]


def mail_sections(account: str, index: int, read_mail: Callable[..., Collected]) -> tuple[dict, bool, bool]:
    """Humans and bulk sections for one account; a failed read raises, never an empty result."""
    humans = read_mail(account, Q_HUMANS, page_size=25, max_items=500)
    bulk = read_mail(account, Q_BULK, page_size=100, max_items=2000)
    bulk_count = bulk.total if bulk.total is not None else len(bulk.items)
    # The packet lists the first HUMANS_SHOWN threads. Any more were read but not listed: like any
    # bounded section the packet is then incomplete and truncated, and it carries the exact query
    # so the agent can read the rest within the same accepted scope.
    omitted = max(len(humans.items) - HUMANS_SHOWN, 0)
    humans_complete = humans.complete and omitted == 0
    humans_truncated = humans.truncated or omitted > 0
    sections = {
        f"humans_{index}": {
            "items": humans.items[:HUMANS_SHOWN], "count": len(humans.items), "shown": min(len(humans.items), HUMANS_SHOWN),
            "omitted": omitted, "query": Q_HUMANS, "complete": humans_complete, "truncated": humans_truncated,
        },
        f"bulk_{index}": {
            "count": bulk_count, "exact": bulk.total is not None and bulk.complete,
            "lower_bound": len(bulk.items), "sample": bulk.items[:3],
            "complete": bulk.complete, "truncated": bulk.truncated,
        },
    }
    return sections, humans_complete and bulk.complete, humans_truncated or bulk.truncated
