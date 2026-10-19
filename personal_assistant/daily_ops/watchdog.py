"""Silent priority and leave-by watchdog.

There is deliberately no mailbox mutation path here. Autoclean is an
unsupported feature, and an enable request is rejected before any provider call.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from . import geo, priority as prio, trip_context
from .common import collect_pages, envelope, now_utc
from .config import config_dir, load_config, profile_root, state_transaction, validate_or_raise
from .gog_collector import DailyOpsError, iter_threads
from ..priority_ownership import PriorityOwnershipError, priority_collection_lease

Q_PRIORITY = "is:unread newer_than:2d"
DEDUP_HOURS = 12
LEAVE_EXPIRY_HOURS = 24


def _redact_term(term: str) -> str:
    from .gog_collector import alias_emails
    return alias_emails(term)[0] if "@" in term else term


def _route_minutes(cfg):
    geo_cfg = (cfg.get("travel") or {}).get("geocoder") or {}
    return lambda origin, destination: geo.drive_minutes(origin, destination, geo_cfg)


def _accounts(cfg):
    accounts = cfg.get("accounts") or {}
    return [account for account in (accounts.get("work"), accounts.get("personal")) if account]


def p1_alerts(cfg: dict, config_dir_: str, now: dt.datetime, *, details: bool = False, coverage: dict | None = None):
    """Return alert records and opaque key-to-thread identity mapping."""
    terms, stale_note = prio.build_terms(cfg, config_dir_, now)
    records = []
    key_index = {}
    if coverage is not None:
        coverage.update({"complete": True, "truncated": False})
    if stale_note:
        key = prio.opaque_priority_key(0, "index-status", [stale_note])
        records.append({"key": key, "line": f"ℹ️ {stale_note}", "thread_ids": []})
        key_index[key] = []
    if not terms:
        return (records, key_index) if details else ([item["line"] for item in records], key_index)
    complete, truncated = True, False
    for index, account in enumerate(_accounts(cfg), 1):
        try:
            found = collect_pages(account, ["gmail", "search", Q_PRIORITY], iter_threads, page_size=25, max_items=1000)
        except DailyOpsError:
            if (cfg.get("calendar") or {}).get("provider") != "profile_google":
                raise
            if coverage is not None:
                coverage.update({"complete": False, "truncated": False, "status": "mail provider unavailable"})
            complete = False
            continue
        if coverage is not None:
            coverage["complete"] = coverage["complete"] and found.complete
            coverage["truncated"] = coverage["truncated"] or found.truncated
        complete = complete and found.complete
        truncated = truncated or found.truncated
        hits = prio.hits_in_messages(cfg, terms, found.items)
        for term, thread_ids in sorted(hits.items(), key=lambda pair: (-len(pair[1]), pair[0])):
            key = prio.opaque_priority_key(index, term, thread_ids)
            record = {"key": key, "line": f"🔴 priority mail [account-{index}]: {_redact_term(term)}×{len(thread_ids)}", "thread_ids": thread_ids}
            records.append(record)
            key_index[key] = thread_ids
    for record in records:
        record["complete"] = complete
        record["truncated"] = truncated
    return (records, key_index) if details else ([item["line"] for item in records], key_index)


def _parse_stamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _dedup_filter(records: list[dict], state: dict, current: dt.datetime) -> list[dict]:
    seen = state.setdefault("priority_alerts", {})
    if not isinstance(seen, dict):
        raise DailyOpsError("daily-ops state priority_alerts is corrupt")
    cutoff = current - dt.timedelta(hours=DEDUP_HOURS)
    cleaned = {}
    for key, stamp in seen.items():
        parsed = _parse_stamp(stamp)
        if parsed is None:
            raise DailyOpsError("daily-ops state contains an invalid alert timestamp")
        if parsed >= cutoff:
            cleaned[key] = stamp
    emitted = []
    for record in records:
        key = record["key"]
        if key not in cleaned:
            emitted.append(record)
            cleaned[key] = current.isoformat()  # only actual emission refreshes suppression
    state["priority_alerts"] = cleaned
    return emitted


def _leave_filter(alerts: list[dict], state: dict, current: dt.datetime) -> list[dict]:
    seen = state.setdefault("leaveby_alerts", {})
    if not isinstance(seen, dict):
        raise DailyOpsError("daily-ops state leaveby_alerts is corrupt")
    cutoff = current - dt.timedelta(hours=LEAVE_EXPIRY_HOURS)
    cleaned = {}
    for key, stamp in seen.items():
        parsed = _parse_stamp(stamp)
        if parsed is None:
            raise DailyOpsError("daily-ops state contains an invalid leave-by timestamp")
        if parsed >= cutoff:
            cleaned[key] = stamp
    emitted = []
    for alert in alerts:
        if alert["key"] not in cleaned:
            emitted.append(alert)
            cleaned[alert["key"]] = current.isoformat()
    state["leaveby_alerts"] = cleaned
    return emitted


def autoclean(cfg, *_args, **_kwargs):
    """Compatibility shim: daily-ops mailbox cleanup is unsupported."""
    value = (cfg.get("autoclean") or {}).get("enabled") if isinstance(cfg, dict) else None
    if value is not None and value is not False:
        raise DailyOpsError("autoclean is unsupported; daily-ops never mutates mail")
    return 0, []


def _failure(exc: Exception) -> None:
    print(f"⚠️ daily-ops pipeline failure: {exc}")
    raise SystemExit(1)


def main() -> None:
    try:
        cfg = validate_or_raise(load_config())
        # This gate runs before opening gog, reading calendar, or calling geo.
        autoclean(cfg)
        current = now_utc()
        root = os.fspath(profile_root())
        cdir = config_dir()
        with state_transaction() as state:
            context, leave_candidates, calendar_complete, calendar_truncated = trip_context.collect_trip(cfg, current, _route_minutes(cfg), root)
            priority_coverage = {}
            priority_records = []
            try:
                with priority_collection_lease(Path(root), "legacy") as ownership:
                    if ownership.state == "owned":
                        priority_records, _ = p1_alerts(cfg, cdir, current, details=True, coverage=priority_coverage)
                    elif ownership.state == "delegated":
                        # Conversation delivery owns P1 collection/publication for this exact profile.
                        # Leave-by/calendar (P0) work above remains independent.
                        priority_coverage.update({
                            "complete": True,
                            "truncated": False,
                            "owner": "conversation_delivery",
                        })
                    else:
                        # A competing publisher is never allowed to fetch the same mailbox. Report
                        # unavailable coverage rather than pretending this tick was quiet.
                        priority_coverage.update({
                            "complete": False,
                            "truncated": False,
                            "status": "priority mail coverage unavailable",
                        })
            except (DailyOpsError, PriorityOwnershipError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                # P0 collection already succeeded.  Keep its urgent output while
                # making P1 uncertainty explicit; never expose provider/config data.
                priority_records = []
                priority_coverage.update({
                    "complete": False,
                    "truncated": False,
                    "status": "priority mail coverage unavailable",
                })
            leave = _leave_filter(leave_candidates, state, current)
            priority = _dedup_filter(priority_records, state, current)
            alerts = [{"kind": "leave_by", "message": item["line"], "identity": item["key"]} for item in leave]
            alerts += [{"kind": "priority", "message": item["line"], "identity": item["key"]} for item in priority]
            scan_complete = calendar_complete and priority_coverage.get("complete", True)
            scan_truncated = calendar_truncated or priority_coverage.get("truncated", False)
            if not alerts and scan_complete:
                return  # exact zero-byte quiet contract, including disabled travel
            sections = {"alerts": alerts, "trip_context": context}
            if not scan_complete:
                sections["degraded"] = {
                    "reason": "provider coverage incomplete",
                    "calendar_complete": calendar_complete,
                    "priority_complete": priority_coverage.get("complete", True),
                    "truncated": scan_truncated,
                    "calendar_coverage": context.get("calendar_coverage", []),
                }
            result = envelope("watchdog", cfg, current, current, sections,
                              complete=scan_complete, truncated=scan_truncated)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    except SystemExit:
        raise
    except (DailyOpsError, PriorityOwnershipError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        _failure(exc)


if __name__ == "__main__":
    main()
