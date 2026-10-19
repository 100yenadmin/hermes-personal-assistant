"""Generic exact-action authorization and fail-closed tool gateway."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable


AUTHORIZATION_PROTOCOL = "pa.action-authorization/v1"
POLICY_PROTOCOL = "pa.gateway-policy/v1"
_REASON_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class GatewayDenied(RuntimeError):
    """A stable, non-sensitive denial returned to the Hermes hook."""

    def __init__(self, reason_code: str):
        if not _REASON_PATTERN.fullmatch(reason_code):
            raise ValueError("invalid gateway reason code")
        super().__init__(reason_code)
        self.reason_code = reason_code


def _validate_json(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            _validate_json(item, f"{path}.{key}")
        return
    raise ValueError(f"{path} contains an unsupported JSON value")


def canonical_json(value: Any) -> str:
    _validate_json(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def args_digest(args: dict[str, Any]) -> str:
    if not isinstance(args, dict):
        raise ValueError("tool arguments must be a JSON object")
    return hashlib.sha256(canonical_json(args).encode("utf-8")).hexdigest()


def _timestamp(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("timezone-aware timestamp required")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("valid timezone-aware timestamp required") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


@dataclass(frozen=True)
class GatewayPolicy:
    version: str
    pass_through_tools: frozenset[str]
    denied_tools: frozenset[str]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GatewayPolicy":
        if not isinstance(value, dict) or value.get("protocol") != POLICY_PROTOCOL:
            raise ValueError("unknown gateway policy protocol")
        version = value.get("version")
        if not isinstance(version, str) or not version:
            raise ValueError("gateway policy version is required")

        def names(key: str) -> frozenset[str]:
            items = value.get(key, [])
            if not isinstance(items, list) or any(not isinstance(item, str) or not item for item in items):
                raise ValueError(f"{key} must contain non-empty tool names")
            if len(items) != len(set(items)):
                raise ValueError(f"{key} must not contain duplicates")
            return frozenset(items)

        pass_through = names("pass_through_tools")
        denied = names("denied_tools")
        if pass_through & denied:
            raise ValueError("a tool cannot be both pass-through and denied")
        return cls(version=version, pass_through_tools=pass_through, denied_tools=denied)

    @classmethod
    def load(cls, path) -> "GatewayPolicy":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle, object_pairs_hook=_reject_duplicate_pairs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": POLICY_PROTOCOL,
            "version": self.version,
            "pass_through_tools": sorted(self.pass_through_tools),
            "denied_tools": sorted(self.denied_tools),
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def classify(self, tool_name: str) -> str:
        if tool_name in self.denied_tools:
            return "denied"
        return "pass_through"


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class ActionAuthorizationStore:
    """Persist and atomically consume generic provider-call authorizations."""

    def __init__(self, ledger, profile_id: str):
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("profile_id is required")
        self.ledger = ledger
        self.profile_id = profile_id
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.ledger.connect() as conn:
            conn.executescript(
                """
                create table if not exists pa_action_authorizations(
                    action_id text primary key,
                    profile_id text not null,
                    tool_name text not null,
                    args_digest text not null,
                    status text not null,
                    execution_budget integer not null,
                    fresh_until text not null,
                    envelope_json text not null,
                    confirmed_at text,
                    confirmation_digest text,
                    claimed_at text,
                    created_at text not null,
                    updated_at text not null
                );
                create index if not exists pa_action_authorization_lookup
                    on pa_action_authorizations(profile_id,tool_name,args_digest,status);
                create table if not exists pa_action_gateway_receipts(
                    receipt_id integer primary key autoincrement,
                    correlation_id text not null,
                    action_id text,
                    reason_code text not null,
                    tool_name text not null,
                    args_digest text not null,
                    policy_digest text not null,
                    receipt_json text not null,
                    recorded_at text not null
                );
                """
            )
            columns = {row[1] for row in conn.execute("pragma table_info(pa_action_authorizations)")}
            for name in (
                "session_id", "task_id", "reliability_profile", "pa_action_id",
                "action_revision", "target_path_json", "target_digest",
            ):
                if name not in columns:
                    conn.execute(
                        f"alter table pa_action_authorizations add column {name} text not null default ''"
                    )
            conn.execute(
                """create index if not exists pa_action_authorization_scope_lookup
                   on pa_action_authorizations(
                       profile_id,session_id,task_id,tool_name,status,fresh_until
                   )"""
            )
            conn.execute(
                """create index if not exists pa_action_authorization_pa_action_lookup
                   on pa_action_authorizations(profile_id,pa_action_id,status,updated_at)"""
            )

    def prepare(
        self,
        envelope: dict[str, Any],
        *,
        session_id: str,
        task_id: str,
        at: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(envelope, dict) or envelope.get("protocol") != AUTHORIZATION_PROTOCOL:
            raise ValueError("unknown action authorization protocol")
        allowed_fields = {
            "protocol", "action_id", "workflow_id", "workflow_revision", "tool_name",
            "tool_args", "risk_class", "authority", "source_revision", "fresh_until", "execution_budget",
            "required_pre_action_projections", "preconditions", "expected_readback", "reliability_profile",
            "pa_action_id", "action_revision", "semantic_target",
        }
        unsupported = sorted(set(envelope) - allowed_fields)
        if unsupported:
            raise ValueError(f"unsupported authorization field: {unsupported[0]}")
        required_strings = (
            "action_id", "workflow_id", "workflow_revision", "tool_name", "reliability_profile",
            "risk_class", "source_revision", "fresh_until", "expected_readback",
        )
        if any(not isinstance(envelope.get(key), str) or not envelope[key] for key in required_strings):
            raise ValueError("authorization envelope is missing required fields")
        if not isinstance(session_id, str) or not session_id or not isinstance(task_id, str) or not task_id:
            raise ValueError("trusted session_id and task_id are required")
        if envelope["reliability_profile"] != "exact":
            raise ValueError("unsupported reliability profile")
        tool_args = envelope.get("tool_args")
        if not isinstance(tool_args, dict):
            raise ValueError("tool_args must be an object")
        digest = args_digest(tool_args)
        if isinstance(envelope.get("execution_budget"), bool) or envelope.get("execution_budget") != 1:
            raise ValueError("execution_budget must be exactly one")
        fresh_until = _timestamp(envelope["fresh_until"])
        authority = envelope.get("authority")
        if not isinstance(authority, dict) or any(
            not isinstance(authority.get(key), str) or not authority[key]
            for key in ("mode", "subject", "scope_digest")
        ):
            raise ValueError("complete authority metadata is required")
        required = envelope.get("required_pre_action_projections")
        preconditions = envelope.get("preconditions")
        if not isinstance(required, list) or not required or any(not isinstance(key, str) or not key for key in required):
            raise ValueError("required_pre_action_projections must be a non-empty list")
        if len(required) != len(set(required)) or not isinstance(preconditions, dict):
            raise ValueError("preconditions must uniquely cover required projections")
        if set(preconditions) != set(required) or any(not isinstance(value, str) for value in preconditions.values()):
            raise ValueError("preconditions must uniquely cover required projections")

        pa_action_id = envelope.get("pa_action_id", "")
        action_revision = envelope.get("action_revision", "")
        if bool(pa_action_id) != bool(action_revision) or (
            pa_action_id and (not isinstance(pa_action_id, str) or not isinstance(action_revision, str))
        ):
            raise ValueError("pa_action_id and action_revision must be supplied together")
        target_path_json = ""
        target_digest = ""
        semantic_target = envelope.get("semantic_target")
        if pa_action_id:
            if not isinstance(semantic_target, dict) or set(semantic_target) != {"paths", "value"}:
                raise ValueError("governed actions require semantic target paths and a value")
            paths = semantic_target["paths"]
            if (
                not isinstance(paths, list)
                or not paths
                or any(
                    not isinstance(path, list)
                    or not path
                    or any(not isinstance(key, str) or not key for key in path)
                    for path in paths
                )
            ):
                raise ValueError("semantic target paths must contain non-empty key paths")
            actual = []
            try:
                for path in paths:
                    value = tool_args
                    for key in path:
                        value = value[key]
                    actual.append(value)
            except (KeyError, TypeError):
                raise ValueError("semantic target paths do not resolve in tool arguments") from None
            if canonical_json(actual) != canonical_json(semantic_target["value"]):
                raise ValueError("semantic target value does not match tool arguments")
            target_path_json = canonical_json(paths)
            target_digest = hashlib.sha256(canonical_json(actual).encode("utf-8")).hexdigest()

        stored = dict(envelope)
        stored.pop("tool_args", None)
        stored["profile_id"] = self.profile_id
        stored["args_digest"] = digest
        stored["fresh_until"] = fresh_until
        stored["authority"] = dict(authority)
        if semantic_target is not None:
            stored["semantic_target"] = {
                "paths": json.loads(target_path_json),
                "value_digest": target_digest,
            }
        stored["scope"] = {
            "mode": "opt_in",
            "session_id": session_id,
            "task_id": task_id,
            "reliability_profile": stored["reliability_profile"],
        }
        stored_json = canonical_json(stored)
        stamp = _timestamp(at) if at else _utc_now()
        with self.ledger.connect() as conn:
            conn.execute("begin immediate")
            if pa_action_id:
                claimed = conn.execute(
                    """select 1 from pa_action_authorizations
                       where profile_id=? and pa_action_id=? and status='claimed' limit 1""",
                    (self.profile_id, pa_action_id),
                ).fetchone()
                if claimed:
                    raise ValueError("resolve claimed governed action before preparing a new revision")
                conn.execute(
                    """update pa_action_authorizations set status='superseded',updated_at=?
                       where profile_id=? and pa_action_id=? and status in ('prepared','authorized','cancelled')
                         and action_id<>?""",
                    (stamp, self.profile_id, pa_action_id, stored["action_id"]),
                )
            old = conn.execute(
                "select envelope_json,status from pa_action_authorizations where action_id=?",
                (stored["action_id"],),
            ).fetchone()
            if old:
                if old["envelope_json"] != stored_json or old["status"] != "prepared":
                    raise ValueError("action_id already has different or consumed authorization state")
            else:
                conn.execute(
                    """insert into pa_action_authorizations(
                           action_id,profile_id,tool_name,args_digest,status,execution_budget,fresh_until,
                           envelope_json,confirmed_at,confirmation_digest,claimed_at,created_at,updated_at,
                           session_id,task_id,reliability_profile,pa_action_id,action_revision,
                           target_path_json,target_digest)
                       values(?,?,?,?, 'prepared',1,?,?,null,null,null,?,?,?,?,?,?,?,?,?)""",
                    (
                        stored["action_id"], self.profile_id, stored["tool_name"], digest,
                        fresh_until, stored_json, stamp, stamp,
                        session_id, task_id, stored["reliability_profile"],
                        pa_action_id, action_revision, target_path_json, target_digest,
                    ),
                )
        return self.get(stored["action_id"])

    def prepare_governed(
        self,
        envelope: dict[str, Any],
        *,
        session_id: str,
        task_id: str,
        at: str | None = None,
    ) -> dict[str, Any]:
        pa_action_id = envelope.get("action_id")
        action_revision = envelope.get("action_revision")
        if not isinstance(pa_action_id, str) or not pa_action_id or not isinstance(action_revision, str) or not action_revision:
            raise ValueError("governed action identity and revision are required")
        stored = dict(envelope)
        stored["pa_action_id"] = pa_action_id
        stored["action_id"] = hashlib.sha256(
            f"{self.profile_id}:{pa_action_id}:{action_revision}".encode("utf-8")
        ).hexdigest()
        return self.prepare(stored, session_id=session_id, task_id=task_id, at=at)

    def confirm(self, action_id: str, confirmation: str, *, at: str | None = None) -> dict[str, Any]:
        if not isinstance(confirmation, str) or not confirmation.strip():
            raise ValueError("explicit confirmation is required")
        stamp = _timestamp(at) if at else _utc_now()
        confirmation_digest = hashlib.sha256(confirmation.strip().encode("utf-8")).hexdigest()
        with self.ledger.connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                "select * from pa_action_authorizations where action_id=?", (action_id,)
            ).fetchone()
            if not row or row["status"] != "prepared":
                raise ValueError("authorization is not prepared for confirmation")
            envelope = json.loads(row["envelope_json"])
            if any(envelope["preconditions"].get(key) != "confirmed" for key in envelope["required_pre_action_projections"]):
                raise ValueError("required precondition is not confirmed")
            envelope["authority"]["confirmed_at"] = stamp
            conn.execute(
                """update pa_action_authorizations
                   set status='authorized',envelope_json=?,confirmed_at=?,confirmation_digest=?,updated_at=?
                   where action_id=?""",
                (canonical_json(envelope), stamp, confirmation_digest, stamp, action_id),
            )
        return self.get(action_id)

    def cancel(self, action_id: str, *, at: str | None = None) -> dict[str, Any]:
        stamp = _timestamp(at) if at else _utc_now()
        with self.ledger.connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                "select status from pa_action_authorizations where action_id=?", (action_id,)
            ).fetchone()
            if not row or row["status"] not in {"prepared", "authorized"}:
                raise ValueError("authorization is not open for cancellation")
            conn.execute(
                "update pa_action_authorizations set status='cancelled',updated_at=? where action_id=?",
                (stamp, action_id),
            )
        return self.get(action_id)

    def get(self, action_id: str) -> dict[str, Any]:
        with self.ledger.connect() as conn:
            row = conn.execute(
                "select * from pa_action_authorizations where action_id=?", (action_id,)
            ).fetchone()
        if not row:
            raise ValueError("unknown action authorization")
        result = dict(row)
        result["envelope"] = json.loads(result.pop("envelope_json"))
        result.pop("confirmation_digest", None)
        return result

    def confirm_governed(
        self,
        pa_action_id: str,
        summary_digest: str,
        confirmation: str,
        *,
        at: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(confirmation, str) or not confirmation.strip():
            raise ValueError("explicit confirmation is required")
        stamp = _timestamp(at) if at else _utc_now()
        confirmation_digest = hashlib.sha256(confirmation.strip().encode("utf-8")).hexdigest()
        with self.ledger.connect() as conn:
            conn.execute("begin immediate")
            rows = conn.execute(
                """select * from pa_action_authorizations
                   where profile_id=? and pa_action_id=? and status<>'superseded'
                   order by updated_at desc,action_id""",
                (self.profile_id, pa_action_id),
            ).fetchall()
            if len(rows) != 1 or rows[0]["status"] != "prepared":
                raise ValueError("governed authorization is not prepared for confirmation")
            authorization = rows[0]
            envelope = json.loads(authorization["envelope_json"])
            if any(
                envelope["preconditions"].get(key) != "confirmed"
                for key in envelope["required_pre_action_projections"]
            ):
                raise ValueError("required precondition is not confirmed")
            action = conn.execute(
                "select status,fields_json from actions where action_id=?", (pa_action_id,)
            ).fetchone()
            if not action or action["status"] != "approval_required":
                raise ValueError("governed action is not awaiting approval")
            fields = json.loads(action["fields_json"])
            if (
                fields.get("summary_digest") != summary_digest
                or fields.get("action_revision") != authorization["action_revision"]
                or fields.get("gateway_scope_ref") != authorization["action_id"]
            ):
                raise ValueError("material details changed; new confirmation required")
            prepared_at = dt.datetime.fromisoformat(authorization["created_at"])
            prepared_until = dt.datetime.fromisoformat(authorization["fresh_until"])
            freshness_window = prepared_until - prepared_at
            if freshness_window <= dt.timedelta(0):
                raise ValueError("governed authorization freshness window must be positive")
            refreshed_until = (
                dt.datetime.fromisoformat(stamp) + freshness_window
            ).astimezone(dt.timezone.utc).isoformat()
            envelope["fresh_until"] = refreshed_until
            envelope["authority"]["confirmed_at"] = stamp
            fields.update({
                "confirmation_text": confirmation,
                "confirmed_at": stamp,
                "confirmation_action_id": pa_action_id,
                "confirmation_digest": summary_digest,
                "fresh_until": refreshed_until,
            })
            conn.execute(
                """update pa_action_authorizations
                   set status='authorized',fresh_until=?,envelope_json=?,confirmed_at=?,
                       confirmation_digest=?,updated_at=?
                   where action_id=? and status='prepared'""",
                (
                    refreshed_until,
                    canonical_json(envelope),
                    stamp,
                    confirmation_digest,
                    stamp,
                    authorization["action_id"],
                ),
            )
            conn.execute(
                "update actions set status='approved_revision',fields_json=?,updated_at=? where action_id=?",
                (json.dumps(fields, ensure_ascii=False), stamp, pa_action_id),
            )
        return self.get(authorization["action_id"])

    def cancel_governed(self, pa_action_id: str, *, at: str | None = None) -> dict[str, Any]:
        stamp = _timestamp(at) if at else _utc_now()
        with self.ledger.connect() as conn:
            conn.execute("begin immediate")
            rows = conn.execute(
                """select * from pa_action_authorizations
                   where profile_id=? and pa_action_id=? and status<>'superseded'
                   order by updated_at desc,action_id""",
                (self.profile_id, pa_action_id),
            ).fetchall()
            if len(rows) != 1 or rows[0]["status"] not in {"prepared", "authorized"}:
                raise ValueError("governed authorization is not open for cancellation")
            authorization = rows[0]
            action = conn.execute(
                "select status from actions where action_id=?", (pa_action_id,)
            ).fetchone()
            if not action or action["status"] not in {"approval_required", "approved_revision"}:
                raise ValueError("governed action is not open for cancellation")
            conn.execute(
                "update pa_action_authorizations set status='cancelled',updated_at=? where action_id=?",
                (stamp, authorization["action_id"]),
            )
            conn.execute(
                "update actions set status='cancelled',updated_at=? where action_id=?",
                (stamp, pa_action_id),
            )
        return self.get(authorization["action_id"])

    @staticmethod
    def _matching_governed(rows, tool_args: dict[str, Any]):
        matches = []
        for row in rows:
            if not row["pa_action_id"]:
                continue
            try:
                values = []
                for path in json.loads(row["target_path_json"]):
                    value = tool_args
                    for key in path:
                        value = value[key]
                    values.append(value)
                target_digest = hashlib.sha256(canonical_json(values).encode("utf-8")).hexdigest()
            except (KeyError, TypeError, ValueError):
                continue
            if hmac.compare_digest(row["target_digest"], target_digest):
                matches.append(row)
        return matches

    def requires_claim(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        session_id: str,
        task_id: str,
        at: str | None = None,
    ) -> bool:
        """Return whether an explicit scope currently governs this tool call."""
        if not isinstance(session_id, str) or not session_id or not isinstance(task_id, str) or not task_id:
            return False
        stamp = _timestamp(at) if at else _utc_now()
        with self.ledger.connect() as conn:
            rows = conn.execute(
                """select * from pa_action_authorizations
                   where profile_id=? and session_id=? and task_id=? and tool_name=?
                   order by created_at,action_id""",
                (self.profile_id, session_id, task_id, tool_name),
            ).fetchall()
        digest = args_digest(tool_args)
        matching = self._matching_governed(rows, tool_args)
        governed = [row for row in matching if row["status"] != "superseded"]
        superseded = [row for row in matching if row["status"] == "superseded"]
        if len(governed) > 1:
            raise GatewayDenied("DENY_ACTION_AMBIGUOUS")
        if governed:
            row = governed[0]
            if row["fresh_until"] <= stamp:
                raise GatewayDenied("DENY_STALE")
            if not hmac.compare_digest(row["args_digest"], digest):
                raise GatewayDenied("DENY_ACTION_CHANGED")
            if row["status"] == "prepared":
                raise GatewayDenied("DENY_APPROVAL_REQUIRED")
            if row["status"] == "cancelled":
                raise GatewayDenied("DENY_ACTION_CANCELLED")
            if row["status"] in {"authorized", "claimed"}:
                return True
            raise GatewayDenied("DENY_ACTION_MALFORMED")
        if superseded:
            raise GatewayDenied("DENY_ACTION_SUPERSEDED")
        if any(
            not row["pa_action_id"]
            and row["status"] == "authorized"
            and row["fresh_until"] > stamp
            for row in rows
        ):
            return True
        return any(
            not row["pa_action_id"]
            and row["status"] == "claimed"
            and row["fresh_until"] > stamp
            and hmac.compare_digest(row["args_digest"], digest)
            for row in rows
        )

    def claim(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        session_id: str,
        task_id: str,
        at: str | None = None,
    ) -> dict[str, Any]:
        digest = args_digest(tool_args)
        stamp = _timestamp(at) if at else _utc_now()
        with self.ledger.connect() as conn:
            conn.execute("begin immediate")
            candidates = conn.execute(
                """select * from pa_action_authorizations
                   where profile_id=? and session_id=? and task_id=? and tool_name=?
                     and status<>'superseded'
                   order by created_at,action_id""",
                (self.profile_id, session_id, task_id, tool_name),
            ).fetchall()
            governed = self._matching_governed(candidates, tool_args)
            if len(governed) > 1:
                raise GatewayDenied("DENY_ACTION_AMBIGUOUS")
            if governed:
                row = governed[0]
                if row["fresh_until"] <= stamp:
                    raise GatewayDenied("DENY_STALE")
                if not hmac.compare_digest(row["args_digest"], digest):
                    raise GatewayDenied("DENY_ACTION_CHANGED")
                if row["status"] == "prepared":
                    raise GatewayDenied("DENY_APPROVAL_REQUIRED")
                if row["status"] == "cancelled":
                    raise GatewayDenied("DENY_ACTION_CANCELLED")
                if row["status"] == "claimed":
                    raise GatewayDenied("DENY_ALREADY_CLAIMED")
                if row["status"] != "authorized":
                    raise GatewayDenied("DENY_ACTION_MALFORMED")
                authorized = [row]
                rows = []
            else:
                rows = [
                    row for row in candidates
                    if not row["pa_action_id"] and hmac.compare_digest(row["args_digest"], digest)
                ]
                authorized = [row for row in rows if row["status"] == "authorized"]
            fresh = [row for row in authorized if row["fresh_until"] > stamp]
            if len(fresh) > 1:
                raise GatewayDenied("DENY_ACTION_AMBIGUOUS")
            if fresh:
                row = fresh[0]
                updated = conn.execute(
                    """update pa_action_authorizations
                       set status='claimed',execution_budget=0,claimed_at=?,updated_at=?
                       where action_id=? and status='authorized' and execution_budget=1""",
                    (stamp, stamp, row["action_id"]),
                )
                if updated.rowcount != 1:
                    raise GatewayDenied("DENY_ALREADY_CLAIMED")
                if row["pa_action_id"]:
                    action = conn.execute(
                        "select status,fields_json from actions where action_id=?",
                        (row["pa_action_id"],),
                    ).fetchone()
                    if not action or action["status"] != "approved_revision":
                        raise GatewayDenied("DENY_ACTION_STATE_MISMATCH")
                    fields = json.loads(action["fields_json"])
                    if fields.get("action_revision") != row["action_revision"]:
                        raise GatewayDenied("DENY_ACTION_CHANGED")
                    fields["gateway_claimed_at"] = stamp
                    fields["gateway_scope_ref"] = row["action_id"]
                    conn.execute(
                        "update actions set status='claimed_once',fields_json=?,updated_at=? where action_id=?",
                        (json.dumps(fields, ensure_ascii=False), stamp, row["pa_action_id"]),
                    )
                return {
                    "action_id": row["pa_action_id"] or row["action_id"],
                    "authorization_id": row["action_id"],
                    "tool_name": tool_name,
                    "args_digest": digest,
                    "claimed_at": stamp,
                }
            if not governed and any(row["status"] == "claimed" and row["fresh_until"] > stamp for row in rows):
                raise GatewayDenied("DENY_ALREADY_CLAIMED")
            raise GatewayDenied("DENY_ACTION_MISSING")

    def record_receipt(
        self,
        *,
        reason_code: str,
        tool_name: str,
        digest: str,
        policy_digest: str,
        correlation_id: str,
        action_id: str | None = None,
        at: str | None = None,
    ) -> None:
        stamp = _timestamp(at) if at else _utc_now()
        receipt = {
            "protocol": "pa.action-gateway-receipt/v1",
            "correlation_id": correlation_id,
            "action_id": action_id,
            "reason_code": reason_code,
            "tool_name": tool_name,
            "args_digest": digest,
            "policy_digest": policy_digest,
            "recorded_at": stamp,
        }
        with self.ledger.connect() as conn:
            conn.execute(
                """insert into pa_action_gateway_receipts(
                       correlation_id,action_id,reason_code,tool_name,args_digest,policy_digest,receipt_json,recorded_at)
                   values(?,?,?,?,?,?,?,?)""",
                (
                    correlation_id, action_id, reason_code, tool_name, digest, policy_digest,
                    canonical_json(receipt), stamp,
                ),
            )


class Gateway:
    def __init__(self, store: ActionAuthorizationStore, policy: GatewayPolicy, *, now: Callable[[], str] | None = None):
        self.store = store
        self.policy = policy
        self.now = now or _utc_now

    @staticmethod
    def _correlation(reason_code: str, tool_name: str = "", digest: str = "") -> str:
        return hashlib.sha256(f"{reason_code}:{tool_name}:{digest}".encode("utf-8")).hexdigest()[:16]

    @classmethod
    def _block(cls, reason_code: str, tool_name: str = "", digest: str = "") -> dict[str, str]:
        correlation = cls._correlation(reason_code, tool_name, digest)
        return {
            "action": "block",
            "message": f"PA_ACTION_GATEWAY_DENIED:{reason_code}:{correlation}",
            "reason_code": reason_code,
            "correlation_id": correlation,
        }

    def evaluate(self, payload: dict[str, Any]) -> dict[str, str] | None:
        try:
            if not isinstance(payload, dict) or payload.get("hook_event_name", "pre_tool_call") != "pre_tool_call":
                raise GatewayDenied("DENY_INVALID_PAYLOAD")
            tool_name = payload.get("tool_name")
            tool_args = payload.get("tool_input", payload.get("args"))
            if not isinstance(tool_name, str) or not tool_name or not isinstance(tool_args, dict):
                raise GatewayDenied("DENY_INVALID_PAYLOAD")
            classification = self.policy.classify(tool_name)
            if classification == "denied":
                raise GatewayDenied("DENY_ADMIN_POLICY")
            digest = args_digest(tool_args)
            stamp = self.now()
            session_id = payload.get("session_id")
            task_id = payload.get("task_id")
            if not self.store.requires_claim(
                tool_name,
                tool_args,
                session_id=session_id,
                task_id=task_id,
                at=stamp,
            ):
                return None
            claim = self.store.claim(
                tool_name,
                tool_args,
                session_id=session_id,
                task_id=task_id,
                at=stamp,
            )
            self.store.record_receipt(
                reason_code="ALLOW_CLAIMED",
                tool_name=tool_name,
                digest=digest,
                policy_digest=self.policy.digest,
                correlation_id=self._correlation("ALLOW_CLAIMED", tool_name, digest),
                action_id=claim["action_id"],
                at=stamp,
            )
            return None
        except GatewayDenied as exc:
            safe_tool = payload.get("tool_name", "") if isinstance(payload, dict) else ""
            safe_args = payload.get("tool_input", payload.get("args")) if isinstance(payload, dict) else None
            try:
                digest = args_digest(safe_args) if isinstance(safe_args, dict) else ""
            except ValueError:
                digest = ""
            if isinstance(safe_tool, str) and safe_tool and digest:
                self.store.record_receipt(
                    reason_code=exc.reason_code,
                    tool_name=safe_tool,
                    digest=digest,
                    policy_digest=self.policy.digest,
                    correlation_id=self._correlation(exc.reason_code, safe_tool, digest),
                    at=self.now(),
                )
            return self._block(exc.reason_code, safe_tool if isinstance(safe_tool, str) else "", digest)
        except Exception:
            return self._block("DENY_INTERNAL_ERROR")
