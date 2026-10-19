#!/usr/bin/env python3
"""Bounded collector runner: publish only after a clean collector exit."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    from .bounded_capture import run_bounded
    from .producer import enqueue_payload
    from .config import ActivationError
except ImportError:  # direct CLI entrypoint
    from bounded_capture import run_bounded
    from producer import enqueue_payload
    from config import ActivationError


DEFAULT_OUTPUT_BYTES = 8 * 1024


def collect(command: list[str], *, timeout: float, max_output_bytes: int) -> tuple[int, bytes, bool, bool, bool]:
    """Return bounded output; overflow kills the child before publication."""
    if not command:
        raise ActivationError("collector command is required after --")
    result = run_bounded(
        command,
        timeout=timeout,
        max_stdout_bytes=max_output_bytes,
        max_stderr_bytes=max_output_bytes,
    )
    return (result.returncode, result.stdout, result.timed_out, result.stdout_truncated, result.stderr_truncated)


def _args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded PA collector and publish its result safely")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--state-dir", required=True)
    run.add_argument("--route-file", required=True)
    run.add_argument("--kind", choices=["morning_brief", "evening_calendar"], required=True)
    run.add_argument("--identity", required=True)
    run.add_argument("--revision")
    run.add_argument("--observed-at", type=float)
    run.add_argument("--expires-at", type=float)
    run.add_argument("--expires-in", type=float, default=2 * 3600)
    run.add_argument("--source-link", action="append", default=[])
    run.add_argument("--timeout", type=float, default=30.0)
    run.add_argument("--max-output-bytes", type=int, default=DEFAULT_OUTPUT_BYTES)
    run.add_argument("--quiet", action="store_true")
    run.add_argument("collector", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    try:
        args = _args().parse_args()
        if args.command != "run":
            raise ActivationError("unsupported runner command")
        if not (0.1 <= args.timeout <= 300.0):
            raise ActivationError("--timeout must be between 0.1 and 300 seconds")
        if not (1024 <= args.max_output_bytes <= DEFAULT_OUTPUT_BYTES):
            raise ActivationError(f"--max-output-bytes must be between 1024 and {DEFAULT_OUTPUT_BYTES}")
        command = list(args.collector)
        if command and command[0] == "--":
            command.pop(0)
        args.max_input_bytes = args.max_output_bytes
        rc, stdout, timed_out, stdout_truncated, stderr_truncated = collect(
            command, timeout=args.timeout, max_output_bytes=args.max_output_bytes
        )
        if timed_out:
            enqueue_payload(args, b"", failure=f"collector timed out after {args.timeout:g}s")
            if not args.quiet:
                print("pa-bridge runner: collector timed out; redacted failure packet queued", file=sys.stderr)
            return 124
        # This runner's contract is bounded plain-text evidence: a stdout
        # overflow is an explicit partial result, while stderr overflow or a
        # nonzero exit remains a redacted failure. Provider JSON uses the
        # stricter priority_runner path, which fails closed on any overflow.
        if rc != 0 and not (stdout_truncated and not stderr_truncated and stdout):
            enqueue_payload(args, b"", failure=f"collector exited with status {rc}")
            if not args.quiet:
                print(f"pa-bridge runner: collector exited {rc}; redacted failure packet queued", file=sys.stderr)
            return rc if 1 <= rc <= 125 else 1
        if not stdout:
            enqueue_payload(args, b"", failure="collector produced no selected output")
            if not args.quiet:
                print("pa-bridge runner: collector produced no output; redacted failure packet queued", file=sys.stderr)
            return 2
        args.collector_output_truncated = stdout_truncated
        enqueue_payload(args, stdout, failure=None)
        return 0
    except (ActivationError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"pa-bridge runner refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
