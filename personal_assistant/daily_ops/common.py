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
