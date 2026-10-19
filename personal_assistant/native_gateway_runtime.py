"""Process-local scope index for the native PA pre-tool hook."""
from __future__ import annotations

import errno
import sqlite3
import threading
from typing import Any

from .action_gateway import ActionAuthorizationStore, Gateway, GatewayPolicy

# Local, read-only Hermes tools that stay available when PA durable state cannot
# initialize, so an operator can still inspect the host. They can never carry a
# governed exact-action scope, so passing them without the ledger cannot bypass
# an approval. Every other tool stays blocked until PA state is readable.
DIAGNOSTIC_TOOLS = frozenset({
    "read_file",
    "search_files",
    "session_search",
    "skill_view",
    "skills_list",
})

STATE_UNAVAILABLE_RECOVERY = (
    "PA durable state is unavailable. Read-only diagnostic tools remain available; "
    "governed and other tool calls stay blocked until the PA ledger can be opened."
)

_SCOPE_LOCK = threading.RLock()
_SCOPE_INDEXES: dict[tuple[str, str], set[tuple[str, str, str]]] = {}


class NativeActionAuthorizationStore(ActionAuthorizationStore):
    """Authorization store with a conservative process-local scope index."""

    def __init__(self, ledger, profile_id: str):
        self._scope_lock = _SCOPE_LOCK
        key = (str(ledger.path.resolve()), profile_id)
        with self._scope_lock:
            self._scope_keys = _SCOPE_INDEXES.setdefault(key, set())
        super().__init__(ledger, profile_id)
        with self.ledger.connect() as conn:
            rows = conn.execute(
                """select distinct session_id,task_id,tool_name
                   from pa_action_authorizations
                   where profile_id=? and session_id<>'' and task_id<>'' and tool_name<>''""",
                (self.profile_id,),
            ).fetchall()
        with self._scope_lock:
            self._scope_keys.update(
                (row["session_id"], row["task_id"], row["tool_name"])
                for row in rows
            )

    def prepare(
        self,
        envelope: dict[str, Any],
        *,
        session_id: str,
        task_id: str,
        at: str | None = None,
    ) -> dict[str, Any]:
        tool_name = envelope.get("tool_name")
        if tool_name in DIAGNOSTIC_TOOLS:
            raise ValueError("read-only diagnostic tools cannot carry a governed scope")
        if isinstance(tool_name, str) and tool_name and session_id and task_id:
            with self._scope_lock:
                self._scope_keys.add((session_id, task_id, tool_name))
        return super().prepare(envelope, session_id=session_id, task_id=task_id, at=at)

    def has_indexed_scope(self, tool_name: str, session_id: object, task_id: object) -> bool:
        if any(not isinstance(value, str) or not value for value in (tool_name, session_id, task_id)):
            return False
        with self._scope_lock:
            return (session_id, task_id, tool_name) in self._scope_keys


class NativeGateway(Gateway):
    """Short-circuit unrelated calls before touching PA storage."""

    def __init__(self, store: NativeActionAuthorizationStore, policy: GatewayPolicy):
        super().__init__(store, policy)

    @staticmethod
    def diagnostic(stage: str, exc: Exception) -> str:
        return f"{stage}_{type(exc).__name__}".upper()

    @classmethod
    def internal_block(cls, tool_name: object, stage: str, exc: Exception) -> dict[str, str]:
        result = cls._block(
            "DENY_INTERNAL_ERROR",
            tool_name if isinstance(tool_name, str) else "",
        )
        result["diagnostic_code"] = cls.diagnostic(stage, exc)
        return result

    @staticmethod
    def is_diagnostic_call(policy: GatewayPolicy, tool_name: object, tool_args: object) -> bool:
        """True for a read-only diagnostic call that never needs PA state."""
        return (
            isinstance(tool_name, str)
            and tool_name in DIAGNOSTIC_TOOLS
            and isinstance(tool_args, dict)
            and policy.classify(tool_name) != "denied"
        )

    @staticmethod
    def state_failure_kind(exc: Exception) -> str:
        """Map a storage failure to a sanitized category; never echo paths or messages."""
        chain = []
        current: BaseException | None = exc
        while current is not None and len(chain) < 8:
            chain.append(current)
            current = current.__cause__ or current.__context__
        # Structured OS errors anywhere in the chain are the most reliable signal;
        # the legacy ledger validators wrap them in RuntimeError.
        for item in chain:
            if isinstance(item, PermissionError) or getattr(item, "errno", None) in (errno.EACCES, errno.EPERM):
                return "PERMISSION_DENIED"
            if isinstance(item, FileNotFoundError):
                return "MISSING"
        text = " ".join(str(item).lower() for item in chain)
        if (
            any(type(item).__name__ == "LedgerPermissionError" for item in chain)
            or "permission" in text
            or "not readable and writable" in text
            or "readonly" in text
        ):
            return "PERMISSION_DENIED"
        if any(isinstance(item, sqlite3.OperationalError) for item in chain) and ("locked" in text or "busy" in text):
            return "LOCKED"
        if any(isinstance(item, sqlite3.DatabaseError) for item in chain) and (
            "malformed" in text or "not a database" in text
        ):
            return "MALFORMED"
        if "existing directory" in text or "unable to open" in text:
            return "MISSING"
        return "UNKNOWN"

    @classmethod
    def state_unavailable_block(cls, tool_name: object, exc: Exception) -> dict[str, str]:
        result = cls._block(
            "DENY_STATE_UNAVAILABLE",
            tool_name if isinstance(tool_name, str) else "",
        )
        result["diagnostic_code"] = "STATE_UNAVAILABLE_" + cls.state_failure_kind(exc)
        result["recovery"] = STATE_UNAVAILABLE_RECOVERY
        return result

    def evaluate(self, payload: dict[str, Any]) -> dict[str, str] | None:
        if isinstance(payload, dict):
            store = self.store
            assert isinstance(store, NativeActionAuthorizationStore)
            tool_name = payload.get("tool_name")
            tool_args = payload.get("tool_input", payload.get("args"))
            if (
                isinstance(tool_name, str)
                and tool_name
                and isinstance(tool_args, dict)
                and self.policy.classify(tool_name) != "denied"
                and not store.has_indexed_scope(
                    tool_name,
                    payload.get("session_id"),
                    payload.get("task_id"),
                )
            ):
                return None
        result = super().evaluate(payload)
        if result and result.get("reason_code") == "DENY_INTERNAL_ERROR":
            result["diagnostic_code"] = "GOVERNED_SCOPE_STATE_UNAVAILABLE"
        return result
