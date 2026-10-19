#!/usr/bin/env python3
"""Run priority collection, publish durable packets, then checkpoint source state.

The collector is deliberately a subprocess: its stdout is bounded and parsed
only after its exit status is known.  A source acknowledgement is generated
internally only after the integrated bridge queue read-back proves that the
packet exists.  This command never injects, sends, or calls a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlsplit

try:
    from .config import ActivationError, ensure_private_file, require_under_home
    from .packet import PacketError, validate_packet
    from .producer import _active_home_and_profile, _bound_settings
    from .runner import collect as collect_subprocess
    from .store import QueueError, QueueStore
    from .priority import collector as priority_collector
    from ..priority_ownership import PriorityOwnershipError, priority_collection_lease
    from ..automation import notification_occurrence_id
except ImportError:  # direct CLI entrypoint
    from config import ActivationError, ensure_private_file, require_under_home
    from packet import PacketError, validate_packet
    from producer import _active_home_and_profile, _bound_settings
    from runner import collect as collect_subprocess
    from store import QueueError, QueueStore
    from priority import collector as priority_collector
    from personal_assistant.priority_ownership import PriorityOwnershipError, priority_collection_lease
    from personal_assistant.automation import notification_occurrence_id


DEFAULT_OUTPUT_BYTES = 128 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
FAILURE_REALERT_SECONDS = 6 * 3600
COVERAGE_EVENT_ID = "priority-mail/coverage"
_EVENT_KEYS = frozenset({
    "event_id", "revision", "content_digest", "status", "account_alias", "account_selector",
    "message_id", "thread_id", "sender", "sender_truncated", "subject", "subject_truncated",
    "snippet", "snippet_truncated", "body", "body_truncated", "date", "expires_at",
    "matched_rules", "categories", "source_link", "content_is_untrusted_data", "selection_note",
    "observed_at", "automation_rule_id", "automation_rule_revision", "automation_occurrence",
    "automation_occurrence_id",
})
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+@-]{0,191}$")


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise PacketError(f"{field} must be a finite number")
    return float(value)


def _text(value: Any, field: str, limit: int = 8192) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > limit:
        raise PacketError(f"{field} is missing or exceeds its bound")
    return value


def _failure_rows(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise PacketError("collector failures must be a list")
    result: list[dict[str, str]] = []
    for row in value[:8]:
        if not isinstance(row, Mapping):
            raise PacketError("collector failure is not an object")
        result.append({
            "source": _text(row.get("source"), "failure.source", 128)[:128],
            "error": _text(row.get("error"), "failure.error", 1000)[:1000],
        })
    return result


def _collector_packet(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketError("priority collector returned invalid JSON") from exc
    if not isinstance(payload, Mapping) or set(payload) != {"version", "kind", "observed_at", "events", "coverage", "failures"}:
        raise PacketError("priority collector packet has an unsupported shape")
    if payload["version"] != 1 or payload["kind"] != "priority_mail":
        raise PacketError("priority collector packet version or kind is invalid")
    observed = _finite(payload["observed_at"], "collector observed_at")
    events = payload["events"]
    if not isinstance(events, list) or len(events) > 64:
        raise PacketError("priority collector events are not bounded")
    coverage = payload["coverage"]
    if not isinstance(coverage, Mapping) or set(coverage) != {"status", "truncated", "notes"}:
        raise PacketError("priority collector coverage has an unsupported shape")
    if coverage["status"] not in {"complete", "partial", "unknown"} or not isinstance(coverage["truncated"], bool):
        raise PacketError("priority collector coverage is invalid")
    notes = _text(coverage["notes"], "collector coverage.notes", 2000)
    return {
        "version": 1,
        "kind": "priority_mail",
        "observed_at": observed,
        "events": [dict(event) if isinstance(event, Mapping) else event for event in events],
        "coverage": {"status": coverage["status"], "truncated": coverage["truncated"], "notes": notes},
        "failures": _failure_rows(payload["failures"]),
    }


def _fact(label: str, value: Any, *, limit: int = 4096) -> dict[str, str]:
    if isinstance(value, (list, tuple)):
        value = json.dumps(list(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"label": label, "value": _text(value, f"event.{label}", limit)}


def _validated_source_link(event: Mapping[str, Any]) -> str:
    link = _text(event["source_link"], "event source_link", 1024)
    parsed = urlsplit(link)
    if parsed.scheme != "https" or parsed.hostname != "mail.google.com":
        raise PacketError("priority event source_link uses an unapproved provider domain")
    selector = parse_qs(parsed.query).get("authuser", [None])[0]
    if selector is None:
        match = re.search(r"/mail/u/([^/]+)/", parsed.path)
        selector = unquote(match.group(1)) if match else None
    if selector != event["account_selector"]:
        raise PacketError("priority event source_link account selector does not match event")
    decoded = unquote(link)
    if event["thread_id"] not in decoded or event["message_id"] not in decoded:
        raise PacketError("priority event source_link identity does not match event")
    return link


def _native_linkage(event: Mapping[str, Any]) -> dict[str, str]:
    """Attach the existing automation identity without claiming its ledger row."""
    rule_id = _text(event["automation_rule_id"], "automation_rule_id", 128)
    rule_revision = _text(event["automation_rule_revision"], "automation_rule_revision", 128)
    occurrence = _text(event["automation_occurrence"], "automation_occurrence", 256)
    source_revision = _text(event["revision"], "event revision", 128)
    occurrence_id = _text(event["automation_occurrence_id"], "automation_occurrence_id", 256)
    expected = notification_occurrence_id(rule_id, occurrence, source_revision)
    if occurrence_id != expected:
        raise PacketError("priority event automation occurrence is not canonical")
    return {
        "owner": "personal_assistant.automation",
        "source": f"gmail:{event['account_selector']}:{event['message_id']}",
        "source_revision": source_revision,
        "rule_id": rule_id,
        "rule_revision": rule_revision,
        "occurrence": occurrence,
        "automation_occurrence_id": occurrence_id,
        "final_notification": "none",
    }


def _event_packet(event: Mapping[str, Any], source: Mapping[str, Any], destination: dict[str, str]) -> dict[str, Any]:
    if set(event) != _EVENT_KEYS:
        missing = sorted(_EVENT_KEYS - set(event))
        extra = sorted(set(event) - _EVENT_KEYS)
        raise PacketError(f"priority event schema is not closed (missing={missing}, extra={extra})")
    event_id = _text(event["event_id"], "event_id", 192)
    revision = _text(event["revision"], "revision", 64)
    if not re.fullmatch(r"[0-9a-f]{64}", revision) or event["content_digest"] != revision:
        raise PacketError("priority event revision/content_digest is not a canonical digest")
    status = event["status"]
    if status not in {"new", "changed", "expired"}:
        raise PacketError("priority event status is invalid")
    observed = _finite(source["observed_at"], "collector observed_at")
    event_observed = _finite(event["observed_at"], "event observed_at")
    if event_observed != observed:
        raise PacketError("priority event observation does not match collector packet")
    account_alias = _text(event["account_alias"], "event account_alias", 64)
    account_selector = _text(event["account_selector"], "event account_selector", 256)
    message_id = _text(event["message_id"], "event message_id", 192)
    thread_id = _text(event["thread_id"], "event thread_id", 192)
    for label, identity in (("account_alias", account_alias), ("account_selector", account_selector),
                           ("message_id", message_id), ("thread_id", thread_id)):
        if not _IDENTITY_RE.fullmatch(identity):
            raise PacketError(f"event {label} contains an invalid identity")
    if event_id != f"priority-mail/{account_alias}/{message_id}":
        raise PacketError("event_id does not bind account alias and message identity")
    expires = _finite(event["expires_at"], "event expires_at")
    if status != "expired" and expires <= observed:
        raise PacketError("non-expired priority evidence is already stale")
    if status == "expired" and expires > observed:
        raise PacketError("expired priority evidence has a future source expiry")
    if event["content_is_untrusted_data"] is not True:
        raise PacketError("priority content must remain explicitly untrusted")
    if not isinstance(event["sender_truncated"], bool) or not isinstance(event["subject_truncated"], bool):
        raise PacketError("priority text truncation flags must be boolean")
    if not isinstance(event["snippet_truncated"], bool) or not isinstance(event["body_truncated"], bool):
        raise PacketError("priority text truncation flags must be boolean")
    source_link = _validated_source_link(event)
    facts = [
        _fact("account_alias", account_alias, limit=64),
        _fact("message_id", message_id, limit=192),
        _fact("thread_id", thread_id, limit=192),
        _fact("sender", event["sender"], limit=512),
        _fact("subject", event["subject"], limit=1024),
        _fact("snippet", event["snippet"], limit=768),
        _fact("body", event["body"], limit=4096),
        _fact("date", event["date"], limit=256),
        _fact("matched_rules", event["matched_rules"], limit=2048),
        _fact("categories", event["categories"], limit=2048),
        _fact("event_status", status, limit=32),
    ]
    coverage = source["coverage"]
    notes = coverage["notes"]
    if coverage["truncated"]:
        notes = f"{notes}; source selection was truncated"
    failures = _failure_rows(source["failures"])
    # Source expiry is provenance, not the queue TTL. Expired source evidence is
    # retained only as an explicit annotation, never as a fresh actionable alert.
    packet_expires = observed + 2 * 3600 if status == "expired" else expires
    return validate_packet({
        "version": 1,
        "event_id": event_id,
        "revision": revision,
        "kind": "priority_mail",
        "observed_at": observed,
        "expires_at": packet_expires,
        "destination": destination,
        "source": [{"identity": event_id, "revision": revision, "links": [source_link]}],
        "facts": facts,
        "coverage": {"status": coverage["status"], "notes": notes[:1000]},
        "failures": failures,
        "native_linkage": _native_linkage(event),
    })


def _coverage_linkage(revision: str) -> dict[str, str]:
    occurrence = "priority-mail-coverage"
    return {
        "owner": "personal_assistant.automation",
        "source": "gmail:priority-mail-coverage",
        "source_revision": revision,
        "rule_id": "priority_mail_coverage",
        "rule_revision": "priority-mail-v1",
        "occurrence": occurrence,
        "automation_occurrence_id": notification_occurrence_id("priority_mail_coverage", occurrence, revision),
        "final_notification": "none",
    }


def _coverage_packet(
    source: Mapping[str, Any],
    destination: dict[str, str],
    *,
    store: QueueStore,
) -> dict[str, Any]:
    coverage = source["coverage"]
    failures = _failure_rows(source["failures"])
    observed = _finite(source["observed_at"], "collector observed_at")
    if not failures:
        raise PacketError("coverage failure packet requires at least one failure")
    # The queue owns deduplication. Anchor the re-alert window to the latest
    # queue publication rather than to wall-clock buckets, so a repeat near a
    # bucket boundary remains quiet. A recovery or changed failure is a new
    # outage even when it occurs inside the prior outage's window.
    semantic = {
        "status": coverage["status"],
        "failures": failures,
    }
    prior = store.latest_packet(COVERAGE_EVENT_ID)
    prior_semantic = None
    prior_observed = None
    if prior is not None:
        prior_coverage = prior.get("coverage", {})
        prior_failures = prior.get("failures", [])
        if isinstance(prior_coverage, Mapping) and isinstance(prior_failures, list):
            prior_semantic = {
                "status": prior_coverage.get("status"),
                "failures": prior_failures,
            }
            try:
                prior_observed = float(prior.get("observed_at"))
            except (TypeError, ValueError):
                prior_observed = None
    same_outage = (
        prior is not None
        and prior_semantic == semantic
        and prior_observed is not None
        and 0 <= observed - prior_observed < FAILURE_REALERT_SECONDS
    )
    if same_outage:
        revision = str(prior["revision"])
    else:
        revision = hashlib.sha256(
            json.dumps({**semantic, "occurrence": observed}, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    notes = f"priority coverage failure; re-alert window {FAILURE_REALERT_SECONDS}s"
    return validate_packet({
        "version": 1,
        "event_id": COVERAGE_EVENT_ID,
        "revision": revision,
        "kind": "priority_mail",
        "observed_at": observed,
        "expires_at": observed + 2 * 3600,
        "destination": destination,
        "source": [{"identity": "collector:priority-mail", "revision": revision, "links": []}],
        "facts": [],
        "coverage": {"status": coverage["status"], "notes": notes},
        "failures": failures,
        "native_linkage": _coverage_linkage(revision),
    })


def _recovery_packet(observed: float, destination: dict[str, str]) -> dict[str, Any]:
    revision = hashlib.sha256(b"priority-coverage-recovered-v1").hexdigest()
    return validate_packet({
        "version": 1,
        "event_id": COVERAGE_EVENT_ID,
        "revision": revision,
        "kind": "priority_mail",
        "observed_at": observed,
        "expires_at": observed + 2 * 3600,
        "destination": destination,
        "source": [{"identity": "collector:priority-mail", "revision": revision, "links": []}],
        "facts": [{"label": "coverage_recovery", "value": "priority mail collection recovered; no current outage is asserted"}],
        "coverage": {"status": "complete", "notes": "priority mail collection recovered after a prior connector outage"},
        "failures": [],
        "native_linkage": _coverage_linkage(revision),
    })


def _durable_publish(store: QueueStore, packet: dict[str, Any]) -> str:
    """Publish and read back the queue row; no second publication ledger exists."""
    store.publish(packet)
    row = store.row(packet["event_id"], packet["revision"])
    if not row or row["event_id"] != packet["event_id"] or row["revision"] != packet["revision"]:
        raise QueueError("durable queue publication receipt read-back failed")
    if row["state"] not in {"pending", "claimed", "unknown", "handled", "silent", "failed", "expired"}:
        raise QueueError("durable queue receipt has an invalid state")
    return "queue-v1:" + hashlib.sha256(
        f"{packet['event_id']}\0{packet['revision']}".encode("utf-8")
    ).hexdigest()


def _failure_source(observed: float, reason: str) -> dict[str, Any]:
    return {
        "observed_at": observed,
        "events": [],
        "coverage": {"status": "unknown", "truncated": False, "notes": "priority collector process did not establish source coverage"},
        "failures": [{"source": "collector:priority-mail", "error": reason[:1000]}],
    }


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    """Run only while this profile's selected P1 route owns the collection lock."""
    home, _ = _active_home_and_profile()
    with priority_collection_lease(home, "conversation") as ownership:
        if not ownership.owned:
            return {"status": ownership.state, "published": [], "reason": ownership.reason, "collector_status": None}
        return _run_once_owned(args, home)


def _run_once_owned(args: argparse.Namespace, home: Path) -> dict[str, Any]:
    if args.observed_at is not None and not math.isfinite(float(args.observed_at)):
        raise ActivationError("--observed-at must be finite")
    if getattr(args, "collector_state", None) is not None:
        raise ActivationError("--collector-state is deprecated and rejected; QueueStore is the sole publication authority")
    route_args = SimpleNamespace(state_dir=args.bridge_state_dir, route_file=args.route_file)
    settings = _bound_settings(route_args)
    config_path = require_under_home(Path(args.config), home, field="priority config")
    ensure_private_file(config_path)
    if args.clients:
        clients_path = require_under_home(Path(args.clients), home, field="priority clients input")
        ensure_private_file(clients_path)
    else:
        clients_path = None
    store = QueueStore(settings.state_dir, max_packet_bytes=settings.max_packet_bytes)
    observed = float(args.observed_at if args.observed_at is not None else time.time())
    command = [
        sys.executable,
        str(Path(__file__).resolve().parent / "priority" / "collector.py"),
        "collect",
        "--config", str(config_path),
        "--observed-at", str(observed),
    ]
    if clients_path:
        command.extend(["--clients", str(clients_path)])
    if args.gog_command:
        command.extend(["--gog-command", args.gog_command])
    rc, stdout, timed_out, stdout_truncated, stderr_truncated = collect_subprocess(
        command, timeout=args.timeout, max_output_bytes=args.max_output_bytes
    )
    truncated = stdout_truncated or stderr_truncated
    if timed_out:
        source = _failure_source(observed, f"priority collector timed out after {args.timeout:g}s")
    elif truncated:
        # A killed/bounded stream is never parsed as a partial JSON packet.
        source = _failure_source(observed, "priority collector output exceeded the runner bound")
    elif stdout:
        try:
            source = _collector_packet(stdout)
        except PacketError as exc:
            source = _failure_source(observed, str(exc))
        if rc != 0:
            source["coverage"]["status"] = "unknown" if source["coverage"]["status"] == "unknown" else "partial"
            source["coverage"]["notes"] = (source["coverage"]["notes"] + f"; collector exited with status {rc}")[:2000]
            source["failures"].append({"source": "collector:priority-mail", "error": f"collector exited with status {rc}"})
    elif rc == 0:
        source = {
            "observed_at": observed,
            "events": [],
            "coverage": {"status": "complete", "truncated": False, "notes": "priority collector completed with no selected events"},
            "failures": [],
        }
    else:
        source = _failure_source(observed, f"priority collector exited with status {rc}")

    if truncated:
        source["coverage"]["status"] = "partial"
        source["coverage"]["truncated"] = True
        source["coverage"]["notes"] = (source["coverage"]["notes"] + "; collector output was bounded by the runner")[:2000]
    published: list[str] = []
    packets: list[dict[str, Any]] = []
    for event in source["events"]:
        if not isinstance(event, Mapping):
            source["failures"].append({"source": "adapter", "error": "priority event is not an object"})
            continue
        try:
            packets.append(_event_packet(event, source, settings.destination))
        except (PacketError, KeyError, TypeError) as exc:
            source["failures"].append({"source": "adapter", "error": str(exc)[:1000]})
    incomplete = bool(source["failures"] or source["coverage"]["status"] != "complete" or source["coverage"]["truncated"])
    if incomplete:
        packets.append(_coverage_packet(source, settings.destination, store=store))
    elif store.has_incomplete_coverage(COVERAGE_EVENT_ID):
        packets.append(_recovery_packet(observed, settings.destination))
    if not packets:
        return {"status": "quiet", "published": [], "collector_status": rc}
    for packet in packets:
        try:
            receipt = _durable_publish(store, packet)
        except (QueueError, PacketError, OSError, ValueError) as exc:
            return {"status": "failed", "published": published, "error": str(exc)[:500], "collector_status": rc}
        published.append(receipt)
    status = "partial" if incomplete else "published"
    return {"status": status, "published": published, "collector_status": rc}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect priority mail and publish through the offline PA bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--config", required=True)
    run.add_argument("--collector-state", help="deprecated compatibility option; rejected because QueueStore is authoritative")
    run.add_argument("--bridge-state-dir", required=True)
    run.add_argument("--route-file", required=True)
    run.add_argument("--clients")
    run.add_argument("--gog-command")
    run.add_argument("--observed-at", type=float)
    run.add_argument("--timeout", type=float, default=90.0)
    run.add_argument("--max-output-bytes", type=int, default=DEFAULT_OUTPUT_BYTES)
    run.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if not (0.1 <= args.timeout <= 300.0):
            raise ActivationError("--timeout must be between 0.1 and 300 seconds")
        if not (1024 <= args.max_output_bytes <= MAX_OUTPUT_BYTES):
            raise ActivationError(f"--max-output-bytes must be between 1024 and {MAX_OUTPUT_BYTES}")
        result = run_once(args)
        if not args.quiet:
            print(json.dumps(result, sort_keys=True))
        return 2 if result["status"] in {"partial", "failed", "busy"} else 0
    except (ActivationError, PacketError, QueueError, PriorityOwnershipError, OSError, ValueError) as exc:
        print(f"pa-priority runner refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
