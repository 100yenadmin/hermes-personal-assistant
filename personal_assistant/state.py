"""Reuse the travel ledger with deterministic identity and atomic action transitions."""
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sqlite3
from pathlib import Path
import uuid

from .privacy import clean

TRANSACTION_FIELDS = {"material_summary", "summary_digest", "confirmation_text", "confirmed_at", "confirmation_action_id", "confirmation_digest"}

_path = Path(__file__).resolve().parents[1] / "skills/travel-ledger/scripts/travel_ledger.py"
_spec = importlib.util.spec_from_file_location("pa_legacy_ledger", _path)
legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)
LedgerPermissionError = legacy.LedgerPermissionError


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def stable_id(*parts):
    if any(p is None or str(p) == "" for p in parts):
        raise ValueError("stable identity requires every component")
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Ledger:
    def __init__(self, profile_root, *, timeout=10, read_only=False):
        self.timeout, self.read_only = timeout, read_only
        raw = Path(profile_root).expanduser()
        if not raw.is_absolute():
            raise ValueError("absolute profile root required")
        legacy._validate_root_components(raw, "profile")
        self.root = raw.resolve(strict=True)
        legacy._validate_directory(self.root, "profile", owned=False)
        candidate = Path(os.environ.get("TRAVEL_LEDGER_DB", "state/travel-ledger/travel.sqlite"))
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            candidate.relative_to(self.root)
            resolved = candidate.resolve()
            resolved.relative_to(self.root)
        except ValueError:
            raise ValueError("ledger must remain within active profile") from None
        if resolved == self.root:
            raise RuntimeError(f"TRAVEL_LEDGER_DB must name a database file under {self.root}, not the root itself")
        legacy._validate_existing_path(self.root, candidate)
        self.path = candidate
        if read_only:
            return
        legacy._ensure_directory(self.root, candidate.parent)
        legacy._ensure_database_file(self.root, candidate)
        with self.connect() as conn:
            legacy.ensure_schema(conn)

    def connect(self):
        # Re-run the profile/path guard on every native open.  This closes the
        # post-construction symlink replacement gap; as with any pathname
        # check followed by an OS open, a hostile local process can still race
        # the check and open and is outside this helper's sandbox guarantee.
        if self.read_only:
            legacy._validate_root_components(self.root, "profile")
            legacy._validate_directory(self.root, "profile", owned=False)
            legacy._validate_existing_path(self.root, self.path)
            conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=self.timeout)
            conn.row_factory = sqlite3.Row
            return conn
        return legacy.connect_at(self.root, self.path, timeout=self.timeout)

    def get(self, kind, identity):
        table, key = self._table(kind)
        if self.read_only and not self.path.exists():
            return None
        with self.connect() as conn:
            row = conn.execute(f"select * from {table} where {key}=?", (identity,)).fetchone()
        return legacy.row_to_dict(row) if row else None

    def list(self, kind):
        table, _ = self._table(kind)
        with self.connect() as conn:
            rows = conn.execute(f"select * from {table} order by created_at").fetchall()
        return [legacy.row_to_dict(row) for row in rows]

    def get_connectivity_profile(self, subject_id):
        """Read a subject-scoped connectivity profile from the native ledger."""
        with self.connect() as conn:
            return legacy.get_connectivity_profile(conn, subject_id)

    def set_connectivity_fields(self, subject_id, fields, *, confirmed_at=None, source=None):
        """Atomically merge dated allowlisted connectivity fields."""
        with self.connect() as conn:
            return legacy.upsert_connectivity_fields(
                conn, subject_id, fields, confirmed_at=confirmed_at, source=source,
            )

    def remove_connectivity_fields(self, subject_id, fields=(), *, clear_all=False, confirmed=False):
        """Explicitly remove subject-scoped connectivity fields."""
        with self.connect() as conn:
            return legacy.remove_connectivity_fields(
                conn, subject_id, fields, clear_all=clear_all, confirmed=confirmed,
            )

    def connectivity_intake(self, subject_id, *, as_of, stale_days=legacy.CONNECTIVITY_DEFAULT_STALE_DAYS):
        """Classify profile freshness without renewing any confirmation."""
        with self.connect() as conn:
            return legacy.connectivity_intake_report(
                conn, subject_id, as_of=as_of, stale_days=stale_days,
            )

    @staticmethod
    def _table(kind):
        if kind not in {"trip", "action"}:
            raise ValueError("record kind must be trip or action")
        return ("trips", "trip_id") if kind == "trip" else ("actions", "action_id")

    def put(self, kind, identity, fields, *, remove=(), invalidate=None, title=None, status=None, action_type=None, trip_id=None, provider=None):
        table, key = self._table(kind)
        if not identity:
            raise ValueError("record identity required; allocate once before execution")
        fields = clean(fields)
        with self.connect() as conn:
            conn.execute("begin immediate")
            old = conn.execute(f"select * from {table} where {key}=?", (identity,)).fetchone()
            if kind == "action":
                if action_type == "transaction" or (old and old["action_type"] == "transaction"):
                    raise ValueError("use transaction operations for transaction records")
                if TRANSACTION_FIELDS.intersection(fields) or TRANSACTION_FIELDS.intersection(remove):
                    raise ValueError("transaction material and confirmation are lifecycle-owned")
            data = json.loads(old["fields_json"]) if old else {}
            data.update(fields)
            for name in remove:
                data.pop(name, None)
            stamp = now()
            state = status or (old["status"] if old else "pending")
            if kind == "trip":
                conn.execute("insert into trips values(?,?,?,?,?,?) on conflict(trip_id) do update set title=excluded.title,status=excluded.status,fields_json=excluded.fields_json,updated_at=excluded.updated_at", (identity, title or (old["title"] if old else "Untitled trip"), state, json.dumps(data, ensure_ascii=False), old["created_at"] if old else stamp, stamp))
            else:
                conn.execute("insert into actions values(?,?,?,?,?,?,?,?) on conflict(action_id) do update set trip_id=excluded.trip_id,action_type=excluded.action_type,provider=excluded.provider,status=excluded.status,fields_json=excluded.fields_json,updated_at=excluded.updated_at", (identity, trip_id if trip_id is not None else (old["trip_id"] if old else None), action_type or (old["action_type"] if old else "commitment"), provider or (old["provider"] if old else ""), state, json.dumps(data, ensure_ascii=False), old["created_at"] if old else stamp, stamp))
            invalid = dict(invalidate or {})
            if remove:
                invalid[identity] = list(remove)
            if invalid:
                for row in conn.execute("select * from actions").fetchall():
                    f = json.loads(row["fields_json"])
                    changed = set(invalid.get(f.get("source_record_id"), []))
                    if changed and ("status" in changed or set(f.get("source_fields", [])) & changed):
                        f["blocked_reason"] = "source details changed; recompute before resuming"
                        for derived in f.get("derived_fields", []):
                            f.pop(derived, None)
                        # A source refresh cannot undo an attempted provider action.
                        preserve = row["action_type"] == "transaction" and row["status"] in {"submitting", "unknown", "confirmed", "completed"}
                        conn.execute("update actions set status=?,fields_json=?,updated_at=? where action_id=?", (row["status"] if preserve else "paused", json.dumps(f), stamp, row["action_id"]))
        return self.get(kind, identity)

    def action_id(self, source_id=None, action_kind=None, occurrence=None):
        if source_id is None:
            return uuid.uuid4().hex
        return stable_id(str(self.root), source_id, action_kind, occurrence)

    def transition(self, identity, expected, target, fields=None, required_digest=None):
        with self.connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute("select * from actions where action_id=?", (identity,)).fetchone()
            if not row or row["action_type"] != "transaction" or row["status"] not in expected:
                raise ValueError("action state does not permit transition")
            data = json.loads(row["fields_json"])
            if required_digest is not None and data.get("summary_digest") != required_digest:
                raise ValueError("material details changed; new confirmation required")
            if target == "submitting" and (not data.get("confirmed_at") or not data.get("confirmation_text") or data.get("confirmation_action_id") != identity or data.get("confirmation_digest") != required_digest):
                raise ValueError("confirmation must belong to this action and current material")
            data.update(clean(fields or {}))
            conn.execute("update actions set status=?,fields_json=?,updated_at=? where action_id=?", (target, json.dumps(data), now(), identity))
        return self.get("action", identity)

    def prepare(self, identity, summary, *, governed=None):
        if not isinstance(summary, dict) or not summary.get("final_action") or not summary.get("provider"):
            raise ValueError("material summary must include provider and final_action")
        safe = clean(summary)
        digest = stable_id(summary)
        with self.connect() as conn:
            conn.execute("begin immediate")
            old = conn.execute("select * from actions where action_id=?", (identity,)).fetchone()
            if old and old["status"] in {
                "submitting", "unknown", "confirmed", "completed", "claimed_once",
                "provider_result", "verified", "reconciled",
            }:
                raise ValueError("resolve provider outcome before preparing another attempt")
            data = json.loads(old["fields_json"]) if old else {}
            data.update({"material_summary": safe, "summary_digest": digest})
            target_status = "prepared"
            if governed is not None:
                required = {
                    "enforcement_profile", "action_revision", "workflow_id", "workflow_revision",
                    "tool_name", "semantic_target_digest", "args_digest", "fresh_until",
                    "execution_budget", "expected_readback", "gateway_scope_ref",
                }
                if not isinstance(governed, dict) or set(governed) != required:
                    raise ValueError("complete governed action metadata is required")
                if governed["enforcement_profile"] != "exact_action" or governed["execution_budget"] != 1:
                    raise ValueError("unsupported governed action profile")
                data.update(clean(governed))
                target_status = "approval_required"
            for key in ("confirmation_text", "confirmed_at", "confirmation_action_id", "confirmation_digest"):
                data.pop(key, None)
            stamp = now()
            conn.execute("insert into actions values(?,?,?,?,?,?,?,?) on conflict(action_id) do update set action_type=excluded.action_type,provider=excluded.provider,status=excluded.status,fields_json=excluded.fields_json,updated_at=excluded.updated_at", (identity, old["trip_id"] if old else None, "transaction", safe["provider"], target_status, json.dumps(data), old["created_at"] if old else stamp, stamp))
        return self.get("action", identity)

    def confirm(self, identity, summary, confirmation):
        if not confirmation.strip():
            raise ValueError("current material summary and explicit user confirmation required")
        digest = stable_id(summary)
        current = self.get("action", identity)
        governed = current and current["fields"].get("enforcement_profile") == "exact_action"
        return self.transition(
            identity,
            {"approval_required"} if governed else {"prepared"},
            "approved_revision" if governed else "authorized",
            {"confirmation_text": confirmation, "confirmed_at": now(), "confirmation_action_id": identity, "confirmation_digest": digest},
            required_digest=digest,
        )

    def claim_submission(self, identity, summary):
        return self.transition(identity, {"authorized"}, "submitting", required_digest=stable_id(summary))

    def result(self, identity, outcome, proof):
        if outcome not in {"confirmed", "failed", "unknown"}:
            raise ValueError("invalid provider outcome")
        if outcome != "unknown" and not clean(proof):
            raise ValueError("provider evidence required")
        current = self.get("action", identity)
        governed = current and current["fields"].get("enforcement_profile") == "exact_action"
        if governed:
            target = {"confirmed": "verified", "failed": "reconciled", "unknown": "provider_result"}[outcome]
            expected = {"claimed_once", "provider_result"}
        else:
            target = outcome
            expected = {"submitting", "unknown"}
        return self.transition(identity, expected, target, {"provider_proof": proof, "verified_at": now() if proof else None})
