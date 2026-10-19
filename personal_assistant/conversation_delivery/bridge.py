"""Gateway-resident poller: supported lifecycle task + ctx.inject_message wake."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from .config import BridgeSettings, atomic_private_write, ensure_private_dir
    from .packet import render_packet
    from .store import QueueStore, QueueError
except ImportError:  # direct producer/test entrypoint
    from config import BridgeSettings, atomic_private_write, ensure_private_dir
    from packet import render_packet
    from store import QueueStore, QueueError


logger = logging.getLogger(__name__)
MARKER_NAME = "gateway-startup.json"


def signal_gateway_startup(state_dir: Path, *, token: str | None = None, platforms: list[str] | None = None) -> str:
    """Called by the installed host ``gateway:startup`` hook after injector publication."""
    ensure_private_dir(Path(state_dir))
    token = token or f"{os.getpid()}-{time.time_ns()}"
    payload = {
        "token": token,
        "pid": os.getpid(),
        "platforms": [str(p)[:32] for p in (platforms or [])[:16]],
        "written_at": time.time(),
    }
    atomic_private_write(Path(state_dir) / MARKER_NAME, json.dumps(payload, sort_keys=True).encode("utf-8"))
    return token


def read_startup_token(state_dir: Path) -> Optional[str]:
    path = Path(state_dir) / MARKER_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        token = raw.get("token")
        marker_pid = raw.get("pid")
        if marker_pid != os.getpid():
            return None
        return token if isinstance(token, str) and 1 <= len(token) <= 128 else None
    except (OSError, ValueError, TypeError):
        return None


class BridgeRuntime:
    """Single-flight queue consumer owned by one loaded gateway plugin instance."""

    def __init__(
        self,
        ctx: Any,
        settings: BridgeSettings,
        *,
        store: QueueStore | None = None,
        clock: Callable[[], float] = time.time,
        session_key_provider: Callable[[], str] | None = None,
    ) -> None:
        self.ctx = ctx
        self.settings = settings
        self.clock = clock
        self.store = store or QueueStore(
            settings.state_dir, clock=clock, max_packet_bytes=settings.max_packet_bytes
        )
        self._session_key_provider = session_key_provider or _host_session_key
        self._startup_baseline = read_startup_token(settings.state_dir)
        self._last_startup_token: Optional[str] = None
        self._consumer_generation: Optional[str] = None
        self._blocked_startup_token: Optional[str] = None
        self._ready = False
        self._stopped = False
        self._wake = asyncio.Event()

    def stop(self) -> None:
        self._stopped = True
        self._ready = False
        self._consumer_generation = None
        self._blocked_startup_token = None
        self.store.release_consumer_lock()
        self._wake.set()

    def wake(self) -> None:
        """Local wake for tests/embedders; producers rely on bounded polling."""
        self._wake.set()

    async def run(self) -> None:
        while not self._stopped:
            try:
                await self.poll_once()
            except Exception:
                logger.warning("PA bridge poll failed; preserving queue rows", exc_info=True)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.settings.poll_interval_seconds)
            except asyncio.TimeoutError:
                pass

    def _ensure_gateway_owner(self, startup_token: str) -> bool:
        """Acquire ownership, then fence old claims; losers never recover active-owner rows."""
        if self._consumer_generation == startup_token and self.store.consumer_generation == startup_token:
            return True
        lock = self.store.acquire_consumer_lock(startup_token)
        if lock is None:
            return False
        if self._consumer_generation is None:
            self.store.recover_inflight()
        self._consumer_generation = lock.generation
        return True

    async def poll_once(self) -> dict[str, Any]:
        token = read_startup_token(self.settings.state_dir)
        if token is None:
            return {"status": "not_ready", "reason": "gateway:startup marker absent"}
        if self._last_startup_token is None and token == self._startup_baseline:
            return {"status": "not_ready", "reason": "waiting for a fresh gateway startup generation"}
        if token != self._last_startup_token:
            self._last_startup_token = token
            self._blocked_startup_token = None
            self._ready = False
        if self._blocked_startup_token == token:
            return {"status": "not_ready", "reason": "waiting for a fresh gateway startup after rejection"}
        if not self._ready:
            try:
                if not self._ensure_gateway_owner(token):
                    return {"status": "not_owner", "reason": "another gateway consumer owns the queue"}
            except QueueError as exc:
                return {"status": "not_ready", "reason": str(exc)}
            self._ready = True

        claim = self.store.claim_next()
        if claim is None:
            return {"status": "idle"}
        if claim.packet["destination"] != self.settings.destination:
            error = "packet destination does not exactly match configured gateway route"
            self.store.mark_failed(claim, error)
            return {"status": "failed", "event_id": claim.event_id, "revision": claim.revision, "error": error}
        try:
            accepted = bool(self.ctx.inject_message(
                render_packet(claim.packet, claim.token),
                role="user",
                session_key=self.settings.destination["session_key"],
            ))
        except Exception as exc:
            accepted = False
            error = f"inject_message raised: {type(exc).__name__}: {exc}"
        else:
            error = "gateway rejected scheduling"
        if accepted:
            # The installed API's True is admission/scheduling only. Never call this delivered.
            self.store.mark_unknown(claim)
            return {
                "status": "unknown",
                "event_id": claim.event_id,
                "revision": claim.revision,
                "reason": "injector accepted scheduling; final delivery unknown",
            }
        self.store.mark_failed(claim, error)
        # A false result is known admission failure. Wait for a fresh host startup marker before
        # considering any later pending row; no tight retry loop and no blind replay.
        self._ready = False
        self._blocked_startup_token = token
        return {"status": "failed", "event_id": claim.event_id, "revision": claim.revision, "error": error}

    def ack_tool(self, args: dict, **_: Any) -> str:
        """Close only the claim named by the packet and the actual invoking host session."""
        import json as _json

        try:
            event_id = args.get("event_id")
            revision = str(args.get("revision"))
            token = args.get("claim_token")
            if not isinstance(event_id, str) or not isinstance(token, str):
                raise QueueError("event_id and claim_token are required")
            # There is deliberately no session_key argument. This value comes from Hermes' bound
            # approval/session context, not from model or packet text.
            actual_session = self._session_key_provider()
            result = self.store.ack(
                event_id=event_id,
                revision=revision,
                token=token,
                actual_session_key=actual_session,
                outcome=args.get("outcome", "handled"),
            )
            return _json.dumps(result, sort_keys=True)
        except Exception as exc:
            return _json.dumps({"ok": False, "error": str(exc)[:500]}, sort_keys=True)


def _host_session_key() -> str:
    """Installed host contextvar is the authority for the invoking gateway route."""
    try:
        from tools.approval_context import get_current_session_key
        return get_current_session_key(default="")
    except Exception:
        return ""
