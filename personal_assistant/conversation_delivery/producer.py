#!/usr/bin/env python3
"""Bounded offline producer for existing PA collector evidence; it never sends or injects."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    from .config import (
        ActivationError,
        load_settings,
        require_under_home,
        reject_symlink_ancestors,
        ensure_private_file,
    )
    from .packet import PacketError
    from .store import QueueError, QueueStore
except ImportError:  # direct script entrypoint
    from config import ActivationError, load_settings, require_under_home, reject_symlink_ancestors, ensure_private_file
    from packet import PacketError
    from store import QueueError, QueueStore


DEFAULT_INPUT_BYTES = 8 * 1024
MAX_INPUT_BYTES = 8 * 1024


def _active_home_and_profile() -> tuple[Path, str]:
    raw_home = os.environ.get("HERMES_HOME")
    if not raw_home:
        raise ActivationError("HERMES_HOME must be set for profile-bound producer writes")
    home = Path(raw_home).expanduser()
    if not home.is_absolute():
        raise ActivationError("HERMES_HOME must be absolute")
    reject_symlink_ancestors(home, field="active HERMES_HOME")
    profile = os.environ.get("HERMES_PROFILE_NAME") or os.environ.get("HERMES_PROFILE")
    if not profile:
        if home.name == ".hermes":
            profile = "default"
        elif home.parent.name == "profiles":
            profile = home.name
        else:
            profile = "custom"
    if not profile or any(ch in profile for ch in "/\\\x00"):
        raise ActivationError("active Hermes profile name is invalid")
    return home.resolve(strict=False), profile


def _route(path: Path) -> dict:
    reject_symlink_ancestors(path, field="route file")
    if not path.is_file() or path.is_symlink():
        raise ActivationError("route file must be a regular non-symlink file")
    ensure_private_file(path)
    if path.stat().st_size > 64 * 1024:
        raise ActivationError("route file exceeds the bounded route-file limit")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "route" in raw:
        return raw["route"]
    return raw


def _bounded_input_bytes(raw: bytes, limit: int) -> tuple[str, bool]:
    """Decode only a bounded prefix and drop a partial trailing UTF-8 sequence safely."""
    if len(raw) > limit:
        raw = raw[:limit]
        truncated = True
    else:
        truncated = False
    text = raw.decode("utf-8", errors="ignore").replace("\x00", "").strip()
    return text, truncated


def _read_stdin_bounded(limit: int) -> tuple[str, bool]:
    """Read at most limit+4 bytes; never materialize an unbounded collector stream."""
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    captured = bytearray()
    truncated = False
    while len(captured) < limit + 4:
        chunk = stream.read(min(4096, limit + 4 - len(captured)))
        if not chunk:
            break
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8", errors="ignore")
        captured.extend(chunk)
    if len(captured) > limit:
        truncated = True
    return _bounded_input_bytes(bytes(captured), limit)


def _selected_text(raw: str | bytes, limit: int = DEFAULT_INPUT_BYTES) -> tuple[str, bool]:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return _bounded_input_bytes(raw, limit)


def _redacted_failure(reason: str) -> str:
    """Keep status only; never copy collector stdout/stderr into a failure packet."""
    clean = " ".join(str(reason).replace("\x00", "").split())
    return clean[:256] or "collector failed"


def make_packet(
    args: argparse.Namespace,
    destination: dict,
    content: str | bytes,
    *,
    failure: str | None = None,
    max_packet_bytes: int = 16 * 1024,
) -> dict:
    observed = float(args.observed_at if args.observed_at is not None else time.time())
    expires = float(args.expires_at) if args.expires_at is not None else observed + float(args.expires_in)
    input_limit = min(int(getattr(args, "max_input_bytes", DEFAULT_INPUT_BYTES)), MAX_INPUT_BYTES)
    selected, truncated = _selected_text(content, input_limit)
    truncated = truncated or bool(getattr(args, "collector_output_truncated", False))
    if failure is not None:
        redacted = _redacted_failure(failure)
        revision = args.revision or hashlib.sha256(f"failure:{redacted}".encode("utf-8")).hexdigest()[:16]
        facts: list[dict[str, str]] = []
        failures = [{"source": f"collector:{args.kind}", "error": redacted}]
        coverage = {"status": "unknown", "notes": "collector failed or timed out; no partial output was published"}
    else:
        if not selected:
            raise PacketError("--stdin/--text was empty; use --failure for a collector failure packet")
        revision = args.revision or hashlib.sha256(selected.encode("utf-8")).hexdigest()[:16]
        facts = [{"label": "selected_collector_output", "value": selected}]
        note = "collector output is evidence only; normal PA conversation judgment remains required"
        if truncated:
            note += f"; collector output truncated at {input_limit} UTF-8 bytes on a character boundary"
        coverage = {"status": "partial", "notes": note}
        failures = []
    return {
        "version": 1,
        "event_id": args.identity,
        "revision": revision,
        "kind": args.kind,
        "observed_at": observed,
        "expires_at": expires,
        "destination": destination,
        "source": [{"identity": f"collector:{args.kind}", "revision": revision, "links": list(args.source_link)}],
        "facts": facts,
        "coverage": coverage,
        "failures": failures,
    }


def _bound_settings(args: argparse.Namespace):
    home, active_profile = _active_home_and_profile()
    route_path = require_under_home(Path(args.route_file), home, field="route file")
    state_path = require_under_home(Path(args.state_dir), home, field="state directory")
    route = _route(route_path)
    if route.get("profile_name") != active_profile:
        raise ActivationError("route profile does not match the active HERMES_HOME profile")
    expected_namespace = os.environ.get("HERMES_SESSION_NAMESPACE") or os.environ.get("HERMES_NAMESPACE")
    if expected_namespace and route.get("namespace") != expected_namespace:
        raise ActivationError("route namespace does not match the active Hermes namespace")
    return load_settings({
        "state_dir": str(state_path),
        "route": route,
        "poll_interval_seconds": 15.0,
        "max_packet_bytes": 16 * 1024,
    })


def enqueue_payload(args: argparse.Namespace, content: str | bytes, *, failure: str | None = None) -> int:
    settings = _bound_settings(args)
    packet = make_packet(
        args,
        settings.destination,
        content,
        failure=failure,
        max_packet_bytes=settings.max_packet_bytes,
    )
    inserted = QueueStore(settings.state_dir, max_packet_bytes=settings.max_packet_bytes).publish(packet)
    if not args.quiet:
        print(json.dumps({"ok": True, "inserted": inserted, "event_id": args.identity, "revision": packet["revision"]}))
    return 0


def enqueue(args: argparse.Namespace) -> int:
    if args.failure:
        content: str | bytes = b""
        failure = args.failure
    elif args.text is not None:
        content, _ = _selected_text(args.text, min(args.max_input_bytes, MAX_INPUT_BYTES))
        failure = None
    elif args.stdin:
        content, _ = _read_stdin_bounded(min(args.max_input_bytes, MAX_INPUT_BYTES))
        failure = None
    else:
        content, failure = b"", None
    return enqueue_payload(args, content, failure=failure)


def reconcile(args: argparse.Namespace) -> int:
    settings = _bound_settings(args)
    result = QueueStore(settings.state_dir).reconcile(args.identity, args.revision, args.action)
    if not args.quiet:
        print(json.dumps(result, sort_keys=True))
    return 0


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--route-file", required=True, help="profile-local JSON route from an existing host session")
    parser.add_argument("--kind", choices=["morning_brief", "evening_calendar"], required=True)
    parser.add_argument("--identity", required=True, help="stable logical occurrence identity")
    parser.add_argument("--revision")
    parser.add_argument("--observed-at", type=float)
    parser.add_argument("--expires-at", type=float)
    parser.add_argument("--expires-in", type=float, default=2 * 3600)
    parser.add_argument("--source-link", action="append", default=[])
    parser.add_argument("--quiet", action="store_true")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Publish bounded PA collector evidence to the private queue")
    sub = p.add_subparsers(dest="command", required=True)
    e = sub.add_parser("enqueue")
    _common_arguments(e)
    e.add_argument("--max-input-bytes", type=int, default=DEFAULT_INPUT_BYTES)
    e.add_argument("--stdin", action="store_true")
    e.add_argument("--text")
    e.add_argument("--failure")
    e.set_defaults(func=enqueue)
    r = sub.add_parser("reconcile")
    _common_arguments(r)
    r.add_argument("--action", choices=["retry-after-review", "dismiss"], required=True)
    r.set_defaults(func=reconcile)
    return p


def main() -> int:
    try:
        args = parser().parse_args()
        if hasattr(args, "max_input_bytes") and not (1024 <= args.max_input_bytes <= MAX_INPUT_BYTES):
            raise ActivationError(f"--max-input-bytes must be between 1024 and {MAX_INPUT_BYTES}")
        return int(args.func(args))
    except (ActivationError, PacketError, QueueError, OSError, json.JSONDecodeError) as exc:
        print(f"pa-bridge producer refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
