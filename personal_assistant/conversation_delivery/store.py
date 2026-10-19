"""Private SQLite queue with atomic identity/revision claims and crash fencing."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported host is POSIX
    fcntl = None

try:
    from .config import ensure_private_dir, ensure_private_file
    from .packet import serialize_packet, validate_packet
except ImportError:  # direct producer/test entrypoint
    from config import ensure_private_dir, ensure_private_file
    from packet import serialize_packet, validate_packet


STATES = frozenset({"pending", "claimed", "unknown", "handled", "silent", "failed", "expired"})


class QueueError(RuntimeError):
    """Queue transition was rejected or could not be made safely."""


@dataclass(frozen=True)
class Claim:
    event_id: str
    revision: str
    token: str
    packet: dict


@dataclass(frozen=True)
class ConsumerLock:
    generation: str


class QueueStore:
    def __init__(self, state_dir: Path, *, clock=time.time, max_packet_bytes: int = 16 * 1024) -> None:
        self.state_dir = Path(state_dir)
        ensure_private_dir(self.state_dir)
        self.db_path = self.state_dir / "queue.sqlite3"
        # Establish private mode atomically, before SQLite or another publisher
        # can observe this file. Never chmod an existing untrusted database.
        try:
            fd = os.open(
                self.db_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except FileExistsError:
            pass
        else:
            os.close(fd)
        ensure_private_file(self.db_path)
        self.clock = clock
        self.max_packet_bytes = max_packet_bytes
        self._consumer_fd: int | None = None
        self._consumer_generation: str | None = None
        self._initialize()
        ensure_private_file(self.db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS packets (
                    event_id TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    packet_json TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('pending','claimed','unknown','handled','silent','failed','expired')),
                    claim_token TEXT,
                    claimed_at REAL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (event_id, revision)
                );
                CREATE INDEX IF NOT EXISTS packets_pending_idx
                    ON packets (state, created_at, event_id, revision);
                """
            )
        finally:
            conn.close()

    def acquire_consumer_lock(self, generation: str) -> ConsumerLock | None:
        """Hold the profile-local single-consumer lock before any crash recovery."""
        if not isinstance(generation, str) or not generation:
            raise QueueError("consumer generation is required")
        if self._consumer_fd is not None:
            return ConsumerLock(self._consumer_generation or generation)
        if fcntl is None:
            raise QueueError("single-consumer process locking is unavailable on this host")
        lock_path = self.state_dir / ".consumer.lock"
        ensure_private_file(lock_path)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            os.close(fd)
            return None
        self._consumer_fd = fd
        self._consumer_generation = generation
        return ConsumerLock(generation)

    def release_consumer_lock(self) -> None:
        fd, self._consumer_fd = self._consumer_fd, None
        self._consumer_generation = None
        if fd is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    @property
    def consumer_generation(self) -> str | None:
        return self._consumer_generation

    @staticmethod
    def _semantic_packet(packet: dict) -> bytes:
        """Stable identity/revision content; observation and expiry are intentionally volatile."""
        semantic = {key: value for key, value in packet.items() if key not in {"observed_at", "expires_at"}}
        if packet.get("kind") == "priority_mail":
            # Collector status can move from new to expired without a source
            # content revision. Queue expiry is the durable truth for that
            # transition; it must not become an identity collision.
            semantic["facts"] = [
                fact for fact in semantic.get("facts", [])
                if fact.get("label") != "event_status"
            ]
        return serialize_packet(semantic)

    def publish(self, packet: dict) -> bool:
        packet = validate_packet(packet, max_bytes=self.max_packet_bytes)
        encoded = serialize_packet(packet)
        now = float(self.clock())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT packet_json FROM packets WHERE event_id=? AND revision=?",
                (packet["event_id"], packet["revision"]),
            ).fetchone()
            if row is not None:
                existing = json.loads(row["packet_json"])
                if self._semantic_packet(existing) != self._semantic_packet(packet):
                    raise QueueError("identity/revision collision contains different semantic packet data")
                # Keep the first packet's evidence and timing; this is an unchanged quiet repeat.
                conn.commit()
                return False
            conn.execute(
                "INSERT INTO packets(event_id,revision,packet_json,expires_at,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (packet["event_id"], packet["revision"], encoded.decode("utf-8"), packet["expires_at"], "pending", now, now),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _expire_pending(self, conn: sqlite3.Connection, now: float) -> None:
        conn.execute(
            "UPDATE packets SET state='expired', last_error='packet expired before claim', updated_at=? "
            "WHERE state='pending' AND expires_at <= ?",
            (now, now),
        )

    def claim_next(self) -> Optional[Claim]:
        now = float(self.clock())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._expire_pending(conn, now)
            row = conn.execute(
                "SELECT event_id, revision, packet_json FROM packets WHERE state='pending' "
                "ORDER BY created_at, event_id, revision LIMIT 1"
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            token = uuid.uuid4().hex
            updated = conn.execute(
                "UPDATE packets SET state='claimed', claim_token=?, claimed_at=?, attempts=attempts+1, updated_at=? "
                "WHERE event_id=? AND revision=? AND state='pending'",
                (token, now, now, row["event_id"], row["revision"]),
            ).rowcount
            if updated != 1:
                conn.rollback()
                return None
            conn.commit()
            return Claim(row["event_id"], row["revision"], token, json.loads(row["packet_json"]))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def recover_inflight(self) -> int:
        """Fence prior claims only while this process holds the startup-owner lock."""
        if self._consumer_fd is None:
            raise QueueError("in-flight recovery requires the held gateway consumer lock")
        now = float(self.clock())
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE packets SET state='unknown', last_error='process restart fenced in-flight claim', "
                "updated_at=? WHERE state='claimed'",
                (now,),
            )
            return int(cur.rowcount)
        finally:
            conn.close()

    def _transition_claim(self, claim: Claim, state: str, error: Optional[str] = None) -> bool:
        if state not in {"unknown", "failed"}:
            raise QueueError(f"invalid claim transition {state}")
        now = float(self.clock())
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE packets SET state=?, last_error=?, updated_at=? "
                "WHERE event_id=? AND revision=? AND claim_token=? AND state='claimed'",
                (state, error, now, claim.event_id, claim.revision, claim.token),
            )
            return cur.rowcount == 1
        finally:
            conn.close()

    def mark_unknown(self, claim: Claim) -> bool:
        return self._transition_claim(claim, "unknown", "injector accepted scheduling; final delivery unknown")

    def mark_failed(self, claim: Claim, error: str) -> bool:
        return self._transition_claim(claim, "failed", str(error)[:1000])

    def ack(self, *, event_id: str, revision: str, token: str, actual_session_key: str, outcome: str) -> dict:
        if outcome not in {"handled", "silent"}:
            raise QueueError("outcome must be handled or silent")
        now = float(self.clock())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT packet_json,state,claim_token FROM packets WHERE event_id=? AND revision=?",
                (event_id, str(revision)),
            ).fetchone()
            if row is None:
                raise QueueError("event claim not found")
            if row["state"] not in {"claimed", "unknown"}:
                raise QueueError(f"event claim is already {row['state']}")
            if not token or row["claim_token"] != token:
                raise QueueError("claim token does not match")
            packet = json.loads(row["packet_json"])
            expected = packet["destination"]["session_key"]
            if not actual_session_key or actual_session_key != expected:
                raise QueueError("ack must come from the exact invoking gateway session")
            if now >= float(packet["expires_at"]):
                raise QueueError("event claim has expired")
            conn.execute(
                "UPDATE packets SET state=?, last_error=NULL, updated_at=? "
                "WHERE event_id=? AND revision=? AND claim_token=? AND state IN ('claimed','unknown')",
                (outcome, now, event_id, str(revision), token),
            )
            conn.commit()
            return {"ok": True, "state": outcome, "event_id": event_id, "revision": str(revision)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def reconcile(self, event_id: str, revision: str, action: str) -> dict:
        """Operator-only explicit reconciliation; unknown rows are never retried automatically."""
        if action not in {"retry-after-review", "dismiss"}:
            raise QueueError("action must be retry-after-review or dismiss")
        now = float(self.clock())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state FROM packets WHERE event_id=? AND revision=?", (event_id, str(revision))
            ).fetchone()
            if row is None:
                raise QueueError("event not found")
            allowed = {"failed", "unknown", "expired"}
            if row["state"] not in allowed:
                raise QueueError(f"cannot reconcile event in state {row['state']}")
            state = "pending" if action == "retry-after-review" else "handled"
            conn.execute(
                "UPDATE packets SET state=?, claim_token=NULL, claimed_at=NULL, last_error=?, updated_at=? "
                "WHERE event_id=? AND revision=?",
                (state, "operator reconciled after review", now, event_id, str(revision)),
            )
            conn.commit()
            return {"ok": True, "state": state, "event_id": event_id, "revision": str(revision)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def has_incomplete_coverage(self, event_id: str) -> bool:
        """Read prior coverage rows; the queue remains the only durable ledger."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT packet_json FROM packets WHERE event_id=? ORDER BY created_at ASC",
                (event_id,),
            ).fetchall()
            for row in rows:
                packet = json.loads(row["packet_json"])
                if packet.get("coverage", {}).get("status") in {"partial", "unknown"} or packet.get("failures"):
                    return True
            return False
        finally:
            conn.close()

    def latest_packet(self, event_id: str) -> Optional[dict[str, Any]]:
        """Return the most recently published packet for one queue identity."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT packet_json FROM packets WHERE event_id=? ORDER BY created_at DESC LIMIT 1",
                (event_id,),
            ).fetchone()
            return json.loads(row["packet_json"]) if row else None
        finally:
            conn.close()

    def row(self, event_id: str, revision: str) -> Optional[dict[str, Any]]:
        conn = self._connect()
        try:
            item = conn.execute(
                "SELECT event_id,revision,state,claim_token,attempts,last_error FROM packets "
                "WHERE event_id=? AND revision=?", (event_id, str(revision))
            ).fetchone()
            return dict(item) if item else None
        finally:
            conn.close()

    def counts(self) -> dict[str, int]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT state,COUNT(*) AS n FROM packets GROUP BY state").fetchall()
            return {state: int(n) for state, n in rows}
        finally:
            conn.close()
