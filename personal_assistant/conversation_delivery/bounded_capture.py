"""Bounded subprocess capture shared by provider and collector runners."""
from __future__ import annotations

import os
import selectors
import subprocess
import time
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class CaptureResult:
    returncode: int
    stdout: bytes
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool


def run_bounded(
    command: Sequence[str],
    *,
    timeout: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int = 8 * 1024,
) -> CaptureResult:
    """Capture bounded prefixes and kill the child on timeout or overflow.

    Stderr is deliberately never returned. A child that exceeds either stream
    bound is killed and its output is not eligible for JSON publication.
    """
    if not command:
        raise ValueError("command is required")
    if timeout <= 0 or max_stdout_bytes < 1 or max_stderr_bytes < 1:
        raise ValueError("capture bounds must be positive")
    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": max_stdout_bytes, "stderr": max_stderr_bytes}
    truncated = {"stdout": False, "stderr": False}
    deadline = time.monotonic() + timeout
    timed_out = False
    killed = False

    def kill_child() -> None:
        nonlocal killed
        if killed or process.poll() is not None:
            return
        killed = True
        try:
            process.kill()
        except ProcessLookupError:
            pass

    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0 and process.poll() is None:
                timed_out = True
                kill_child()
                remaining = 0.25
            events = selector.select(timeout=min(max(remaining, 0.0), 0.1))
            if not events:
                if process.poll() is not None:
                    # Closed pipes still need one short EOF pass.
                    if not selector.select(timeout=0.05):
                        break
                continue
            for key, _ in events:
                stream = key.data
                try:
                    chunk = os.read(key.fileobj.fileno(), 4096)
                except (OSError, ValueError):
                    chunk = b""
                if not chunk:
                    try:
                        selector.unregister(key.fileobj)
                    except Exception:
                        pass
                    try:
                        key.fileobj.close()
                    except OSError:
                        pass
                    continue
                remaining_bytes = limits[stream] - len(buffers[stream])
                if remaining_bytes > 0:
                    buffers[stream].extend(chunk[:remaining_bytes])
                if len(chunk) > max(remaining_bytes, 0):
                    truncated[stream] = True
                    kill_child()
            if killed and process.poll() is not None and not selector.select(timeout=0.05):
                break
    finally:
        for key in list(selector.get_map().values()):
            try:
                selector.unregister(key.fileobj)
            except Exception:
                pass
            try:
                key.fileobj.close()
            except OSError:
                pass
        selector.close()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            kill_child()
            process.wait(timeout=1.0)
            timed_out = True
    return CaptureResult(
        returncode=int(process.returncode),
        stdout=bytes(buffers["stdout"]),
        timed_out=timed_out,
        stdout_truncated=truncated["stdout"],
        stderr_truncated=truncated["stderr"],
    )
