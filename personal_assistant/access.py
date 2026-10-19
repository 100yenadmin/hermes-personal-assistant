"""Secret-safe, callback-injected access routing for the PA pilot."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from .privacy import safe_text

ROUTE_SECURE_ACCESS = "secure_access"
ROUTE_MANAGED_BROWSERBASE = "managed_browserbase"
ROUTE_LOCAL_BROWSERBASE = "local_browserbase"
ROUTE_ONEPASSWORD = "onepassword"
_ROUTES = {
    "secure": ROUTE_SECURE_ACCESS, ROUTE_SECURE_ACCESS: ROUTE_SECURE_ACCESS,
    "managed": ROUTE_MANAGED_BROWSERBASE, ROUTE_MANAGED_BROWSERBASE: ROUTE_MANAGED_BROWSERBASE,
    "local": ROUTE_LOCAL_BROWSERBASE, ROUTE_LOCAL_BROWSERBASE: ROUTE_LOCAL_BROWSERBASE,
    "1password": ROUTE_ONEPASSWORD, "one_password": ROUTE_ONEPASSWORD,
    ROUTE_ONEPASSWORD: ROUTE_ONEPASSWORD,
}
_DENIED = {"denied", "revoked", "rejected", "forbidden", "unauthorized", "not_allowed", "blocked"}
_EXPIRED = {"expired", "lease_expired", "timed_out"}
_READY = {"ready", "approved", "granted", "authorized", "active", "connected", "ok", "materialized"}
_SECRET_PARTS = (
    "password", "passphrase", "secret", "token", "cookie", "authorization", "bearer",
    "privatekey", "apikey", "clientsecret", "credential", "plaintext", "rawbytes",
)


class AccessError(RuntimeError):
    code = "access_error"
    def __init__(self, message: str, *, route: Optional[str] = None):
        super().__init__(message)
        self.route = route


class RouteUnavailableError(AccessError):
    code = "route_unavailable"


class UnsupportedRouteError(AccessError):
    code = "unsupported_route"


class AccessDeniedError(AccessError):
    code = "access_denied"


class AccessExpiredError(AccessError):
    code = "access_expired"


class IdentityMismatchError(AccessError):
    code = "identity_mismatch"


class AccessUnavailableError(AccessError):
    code = "access_unavailable"


class AccessResponseError(AccessError):
    code = "invalid_access_response"


class AccessCallbackError(AccessError):
    code = "access_callback_failed"


class OptionalResolverUnavailableError(RouteUnavailableError):
    code = "optional_resolver_unavailable"


Callback = Callable[..., Any]


def _key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _bearer_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.lower()
    return any(x in text for x in ("token=", "bearer ", "authorization=", "secret=", "api_key=", "apikey="))


def _secret_key(key: Any, value: Any, persistent: bool) -> bool:
    name = _key(key)
    if name in {"value", "values", "raw", "liveviewurl", "connecturl", "debugurl"}:
        return True
    if any(part in name for part in _SECRET_PARTS):
        return True
    return persistent and name in {"url", "uri", "href"} and _bearer_url(value)


def sanitize_metadata(value: Any, *, persistent: bool = True) -> Any:
    """Recursively remove fields that can contain credentials or bearer URLs."""
    if isinstance(value, Mapping):
        return {
            str(k): sanitize_metadata(v, persistent=persistent)
            for k, v in value.items()
            if not _secret_key(k, v, persistent) and _key(k) not in {"liveviewurl", "connecturl", "debugurl", "ownerid", "accountid", "customerid", "agentid", "userid", "email", "phone", "username", "login"}
        }
    if isinstance(value, datetime):
        return _expiry(value)[0]
    if isinstance(value, str):
        # Uppercase environment variable names are references, not values.
        return value if re.fullmatch(r"[A-Z][A-Z0-9_]*", value) else safe_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [sanitize_metadata(v, persistent=persistent) for v in value]
    return None


def _metadata(raw: Mapping[str, Any]) -> Dict[str, Any]:
    # Provider payloads can put secret values in arbitrary text fields. Return
    # only the small metadata contract needed by the access workflow.
    allowed = {"source_ref", "session_id", "session_ref", "context_id", "context_ref",
               "state", "status", "expires_at", "expiry", "path", "file_path",
               "env_file", "variable_names", "variables", "label", "title"}
    result = sanitize_metadata({key: value for key, value in raw.items() if key in allowed})
    if not isinstance(result, dict):
        raise AccessResponseError("access callback returned invalid metadata")
    for name in list(result):
        if _key(name) in {"ownerid", "accountid", "customerid", "agentid", "userid", "email", "phone", "username", "login"}:
            result.pop(name, None)
    return result


def _expiry(value: Any) -> tuple[Optional[str], Optional[datetime]]:
    if value is None:
        return None, None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, (int, float)):
        moment = datetime.fromtimestamp(float(value), timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            raise AccessResponseError("access expiry is invalid")
    else:
        raise AccessResponseError("access expiry is invalid")
    if moment.tzinfo is None:
        raise AccessResponseError("access expiry must include a timezone")
    moment = moment.astimezone(timezone.utc)
    return moment.isoformat().replace("+00:00", "Z"), moment


def _pick(raw: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw:
            return raw[name]
    return None


def _state(raw: Mapping[str, Any]) -> str:
    value = _pick(raw, "state", "status", "access_state", "grant_state", "decision")
    if value is None:
        if raw.get("allowed") is True or raw.get("authorized") is True or raw.get("ready") is True:
            return "ready"
        return "unknown"
    return str(value).strip().lower().replace("-", "_")


def _expires(raw: Mapping[str, Any]) -> tuple[Optional[str], Optional[datetime]]:
    return _expiry(_pick(raw, "expires_at", "expiry", "expires", "lease_expires_at"))


def _fingerprint(value: Optional[str]) -> Optional[str]:
    return None if value is None else hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _ref(value: Optional[str], label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AccessResponseError("%s reference is required" % label)
    return value


@dataclass
class AccessManager:
    """Use existing native callbacks while returning metadata only."""

    secure_access_list: Optional[Callback] = None
    secure_access_check: Optional[Callback] = None
    secure_access_materialize: Optional[Callback] = None
    managed_create: Optional[Callback] = None
    managed_release: Optional[Callback] = None
    browserbase_handoff: Optional[Callback] = None
    onepassword_resolver: Optional[Callback] = None
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise AccessResponseError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _route(route: str) -> str:
        try:
            return _ROUTES[str(route).strip().lower()]
        except (AttributeError, KeyError):
            raise UnsupportedRouteError("unsupported access route")

    @staticmethod
    def _callback(callback: Optional[Callback], operation: str, route: str) -> Callback:
        if callback is None:
            raise RouteUnavailableError("%s is not configured" % operation, route=route)
        return callback

    @staticmethod
    def _call(callback: Callback, operation: str, route: str, **kwargs: Any) -> Any:
        try:
            return callback(**kwargs)
        except PermissionError:
            raise AccessDeniedError("%s was denied" % operation, route=route)
        except AccessError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(getattr(exc, "resp", None), "status", None)
            if status in (401, 403):
                raise AccessDeniedError("%s was denied" % operation, route=route) from None
            raise AccessCallbackError("%s failed" % operation, route=route)

    @staticmethod
    def _mapping(raw: Any, operation: str, route: str) -> Mapping[str, Any]:
        if not isinstance(raw, Mapping):
            raise AccessResponseError("%s returned invalid metadata" % operation, route=route)
        return raw

    @staticmethod
    def _identity(raw: Mapping[str, Any], owner: str, context: Optional[str], require_context=False) -> tuple[bool, bool]:
        got_owner = _pick(raw, "owner_id", "account_id", "agent_id")
        if got_owner is not None and got_owner != owner:
            raise IdentityMismatchError("access owner does not match request")
        got_context = _pick(raw, "context_id", "context_ref")
        if context is not None:
            if require_context and got_context is None:
                raise IdentityMismatchError("access context is missing")
            if got_context is not None and got_context != context:
                raise IdentityMismatchError("access context does not match request")
        return got_owner == owner, context is None or got_context == context

    def route_capabilities(self, route: str) -> Dict[str, Any]:
        route = self._route(route)
        if route == ROUTE_SECURE_ACCESS:
            return {"route": route, "list": self.secure_access_list is not None, "check": self.secure_access_check is not None, "materialize": self.secure_access_materialize is not None, "live_view": False, "debug": False, "durable_context": False, "verified": False}
        if route == ROUTE_MANAGED_BROWSERBASE:
            return {"route": route, "create": self.managed_create is not None, "release": self.managed_release is not None, "context": False, "durable_context": False, "live_view": False, "debug": False, "attended_handoff": False, "verified": False}
        if route == ROUTE_LOCAL_BROWSERBASE:
            configured = self.browserbase_handoff is not None
            return {"route": route, "attended_handoff": configured, "durable_context": configured, "live_view": configured, "debug": False, "verified": False}
        return {"route": route, "configured": self.onepassword_resolver is not None, "optional": True, "verified": False}

    def list_secure_access(self, *, owner_id: Optional[str] = None, context_id: Optional[str] = None) -> list[Dict[str, Any]]:
        callback = self._callback(self.secure_access_list, "Secure Access list", ROUTE_SECURE_ACCESS)
        raw = self._call(callback, "Secure Access list", ROUTE_SECURE_ACCESS, owner_id=owner_id, context_id=context_id)
        items = _pick(raw, "items", "sources", "entries", "data") if isinstance(raw, Mapping) else raw
        items = [raw] if isinstance(raw, Mapping) and items is None else items
        if not isinstance(items, Iterable) or isinstance(items, (str, bytes, bytearray)):
            raise AccessResponseError("Secure Access list returned invalid entries", route=ROUTE_SECURE_ACCESS)
        return [_metadata(self._mapping(item, "Secure Access list", ROUTE_SECURE_ACCESS)) for item in items]

    def check_secure_access(self, *, source_ref: str, owner_id: str, context_id: Optional[str] = None) -> Dict[str, Any]:
        source_ref, owner_id = _ref(source_ref, "source"), _ref(owner_id, "owner")
        callback = self._callback(self.secure_access_check, "Secure Access check", ROUTE_SECURE_ACCESS)
        raw = self._mapping(self._call(callback, "Secure Access check", ROUTE_SECURE_ACCESS, source_ref=source_ref, owner_id=owner_id, context_id=context_id), "Secure Access check", ROUTE_SECURE_ACCESS)
        owner_match, context_match = self._identity(raw, owner_id, context_id)
        state, expiry, moment = _state(raw), *_expires(raw)
        if state in _DENIED:
            raise AccessDeniedError("Secure Access source is denied or revoked", route=ROUTE_SECURE_ACCESS)
        if state in _EXPIRED or moment is not None and moment <= self._now():
            raise AccessExpiredError("Secure Access source is expired", route=ROUTE_SECURE_ACCESS)
        if state not in _READY:
            raise AccessUnavailableError("Secure Access source is not ready", route=ROUTE_SECURE_ACCESS)
        return {"route": ROUTE_SECURE_ACCESS, "source_ref": source_ref, "state": "ready", "allowed": True, "owner_match": owner_match, "context_match": context_match, "expires_at": expiry, "metadata": _metadata(raw)}

    def materialize_secure_access(self, *, source_ref: str, owner_id: str, context_id: Optional[str] = None) -> Dict[str, Any]:
        checked = self.check_secure_access(source_ref=source_ref, owner_id=owner_id, context_id=context_id)
        callback = self._callback(self.secure_access_materialize, "Secure Access materialize", ROUTE_SECURE_ACCESS)
        raw = self._mapping(self._call(callback, "Secure Access materialize", ROUTE_SECURE_ACCESS, source_ref=source_ref, owner_id=owner_id, context_id=context_id), "Secure Access materialize", ROUTE_SECURE_ACCESS)
        material_state = _state(raw)
        if material_state in _DENIED:
            raise AccessDeniedError("Secure Access grant was denied during materialization", route=ROUTE_SECURE_ACCESS)
        if material_state in _EXPIRED:
            raise AccessExpiredError("Secure Access grant expired during materialization", route=ROUTE_SECURE_ACCESS)
        owner_match, context_match = self._identity(raw, owner_id, context_id)
        expiry, moment = _expires(raw)
        expiry = expiry or checked["expires_at"]
        if moment is not None and moment <= self._now():
            raise AccessExpiredError("materialized access is expired", route=ROUTE_SECURE_ACCESS)
        metadata = _metadata(raw)
        if "variable_names" not in metadata and isinstance(metadata.get("variables"), list):
            variables = metadata.pop("variables")
            metadata["variable_names"] = [v.get("name") for v in variables if isinstance(v, Mapping) and isinstance(v.get("name"), str)]
        return {"route": ROUTE_SECURE_ACCESS, "source_ref": source_ref, "state": "materialized", "owner_match": owner_match, "context_match": context_match, "expires_at": expiry, "metadata": metadata}

    def acquire(self, *, source_ref: str, owner_id: str, context_id: Optional[str] = None, cached_session: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        try:
            return self.materialize_secure_access(source_ref=source_ref, owner_id=owner_id, context_id=context_id)
        except (AccessDeniedError, AccessExpiredError, IdentityMismatchError):
            raise
        except (RouteUnavailableError, AccessUnavailableError, AccessCallbackError):
            if cached_session is None:
                raise
            raw = self._mapping(cached_session, "cached session", "cached_session")
            owner_match, context_match = self._identity(raw, _ref(owner_id, "owner"), context_id)
            if not owner_match or not context_match:
                raise IdentityMismatchError("cached session identity must be verified")
            state = _state(raw)
            if state in _DENIED:
                raise AccessDeniedError("cached session is denied or revoked")
            expiry, moment = _expires(raw)
            if state in _EXPIRED or moment is not None and moment <= self._now():
                raise AccessExpiredError("cached session is expired")
            if state not in _READY or moment is None:
                raise AccessUnavailableError("cached session readiness and expiry must be verified")
            return {"route": "cached_session", "state": "cached", "fallback_used": True, "fallback_reason": "secure_access_unavailable", "expires_at": expiry, "metadata": _metadata(raw)}

    def attended_browserbase_handoff(self, *, owner_id: str, context_id: Optional[str] = None, provider: Optional[str] = None) -> Dict[str, Any]:
        owner_id = _ref(owner_id, "owner")
        callback = self._callback(self.browserbase_handoff, "local Browserbase handoff", ROUTE_LOCAL_BROWSERBASE)
        raw = self._mapping(self._call(callback, "local Browserbase handoff", ROUTE_LOCAL_BROWSERBASE, owner_id=owner_id, context_id=context_id, provider=provider, attended=True), "local Browserbase handoff", ROUTE_LOCAL_BROWSERBASE)
        owner_match, context_match = self._identity(raw, owner_id, context_id, require_context=context_id is not None)
        if not owner_match:
            raise IdentityMismatchError("verify the intended account before resuming the browser")
        mode = str(raw.get("mode", "")).lower()
        if raw.get("attended") is False or raw.get("attended") is not True and mode not in {"attended", "human"}:
            raise AccessUnavailableError("attended handoff was not verified", route=ROUTE_LOCAL_BROWSERBASE)
        state = _state(raw)
        if state in _DENIED:
            raise AccessDeniedError("Browserbase handoff was denied", route=ROUTE_LOCAL_BROWSERBASE)
        if state in _EXPIRED:
            raise AccessExpiredError("Browserbase handoff is expired", route=ROUTE_LOCAL_BROWSERBASE)
        if raw.get("ready") is False or state not in _READY:
            raise AccessUnavailableError("Browserbase handoff is not ready", route=ROUTE_LOCAL_BROWSERBASE)
        expiry, moment = _expires(raw)
        if expiry is None:
            raise AccessResponseError("Browserbase handoff expiry is required", route=ROUTE_LOCAL_BROWSERBASE)
        if moment is not None and moment <= self._now():
            raise AccessExpiredError("Browserbase handoff is expired", route=ROUTE_LOCAL_BROWSERBASE)
        handoff_context = _pick(raw, "context_id", "context_ref") or context_id
        session_id = _pick(raw, "session_id", "session_ref")
        checkpoint = {"route": ROUTE_LOCAL_BROWSERBASE, "state": "ready", "owner_match": owner_match, "context_match": context_match, "owner_fingerprint": _fingerprint(owner_id), "context_fingerprint": _fingerprint(handoff_context), "attended": True, "ready_verified": True, "session_id": session_id if isinstance(session_id, str) else None, "context_id": handoff_context if isinstance(handoff_context, str) else None, "expires_at": expiry, "live_view_transient": any(_key(k) == "liveviewurl" for k in raw), "capabilities": self.route_capabilities(ROUTE_LOCAL_BROWSERBASE)}
        return {"route": ROUTE_LOCAL_BROWSERBASE, "state": "ready", "checkpoint": checkpoint, "metadata": _metadata(raw)}

    def verify_checkpoint(self, checkpoint: Mapping[str, Any], *, owner_id: str, context_id: Optional[str] = None) -> Dict[str, Any]:
        if not isinstance(checkpoint, Mapping) or self._route(checkpoint.get("route", "")) != ROUTE_LOCAL_BROWSERBASE:
            raise UnsupportedRouteError("checkpoint route is unsupported")
        if checkpoint.get("state") != "ready":
            raise AccessUnavailableError("checkpoint is not ready", route=ROUTE_LOCAL_BROWSERBASE)
        expiry, moment = _expires(checkpoint)
        if expiry is None or moment is None:
            raise AccessResponseError("checkpoint expiry is required", route=ROUTE_LOCAL_BROWSERBASE)
        if moment <= self._now():
            raise AccessExpiredError("checkpoint is expired", route=ROUTE_LOCAL_BROWSERBASE)
        owner_id = _ref(owner_id, "owner")
        if checkpoint.get("owner_fingerprint") != _fingerprint(owner_id):
            raise IdentityMismatchError("checkpoint owner does not match request")
        if checkpoint.get("context_fingerprint") != _fingerprint(context_id):
            raise IdentityMismatchError("checkpoint context does not match request")
        result = _metadata(checkpoint)
        result.update({"route": ROUTE_LOCAL_BROWSERBASE, "state": "ready", "owner_match": True, "context_match": True, "expires_at": expiry, "context_id": checkpoint.get("context_id") if isinstance(checkpoint.get("context_id"), str) else None, "live_view_transient": bool(checkpoint.get("live_view_transient"))})
        result.pop("live_view_url", None)
        return result

    def managed_browserbase_create(self, *, owner_id: str, provider: Optional[str] = None) -> Dict[str, Any]:
        owner_id = _ref(owner_id, "owner")
        callback = self._callback(self.managed_create, "managed Browserbase create", ROUTE_MANAGED_BROWSERBASE)
        raw = self._mapping(self._call(callback, "managed Browserbase create", ROUTE_MANAGED_BROWSERBASE, owner_id=owner_id, provider=provider), "managed Browserbase create", ROUTE_MANAGED_BROWSERBASE)
        owner_match, _ = self._identity(raw, owner_id, None)
        state = _state(raw)
        if state in _DENIED:
            raise AccessDeniedError("managed Browserbase create was denied", route=ROUTE_MANAGED_BROWSERBASE)
        if state in _EXPIRED:
            raise AccessExpiredError("managed Browserbase session is expired", route=ROUTE_MANAGED_BROWSERBASE)
        if state not in _READY and raw.get("ok") is not True:
            raise AccessUnavailableError("managed Browserbase session is not ready", route=ROUTE_MANAGED_BROWSERBASE)
        expiry, _ = _expires(raw)
        return {"route": ROUTE_MANAGED_BROWSERBASE, "state": "active", "owner_match": owner_match, "session_id": _pick(raw, "session_id", "session_ref"), "expires_at": expiry, "capabilities": self.route_capabilities(ROUTE_MANAGED_BROWSERBASE), "metadata": _metadata(raw)}

    def managed_browserbase_release(self, *, owner_id: str, session_id: str) -> Dict[str, Any]:
        owner_id, session_id = _ref(owner_id, "owner"), _ref(session_id, "session")
        callback = self._callback(self.managed_release, "managed Browserbase release", ROUTE_MANAGED_BROWSERBASE)
        raw = self._mapping(self._call(callback, "managed Browserbase release", ROUTE_MANAGED_BROWSERBASE, owner_id=owner_id, session_id=session_id), "managed Browserbase release", ROUTE_MANAGED_BROWSERBASE)
        owner_match, _ = self._identity(raw, owner_id, None)
        if _state(raw) in _DENIED:
            raise AccessDeniedError("managed Browserbase release was denied", route=ROUTE_MANAGED_BROWSERBASE)
        return {"route": ROUTE_MANAGED_BROWSERBASE, "state": "released", "owner_match": owner_match, "session_id": session_id, "metadata": _metadata(raw)}

    def resolve_onepassword(self, *, item_ref: str, owner_id: Optional[str] = None, context_id: Optional[str] = None) -> Dict[str, Any]:
        item_ref = _ref(item_ref, "1Password item")
        callback = self.onepassword_resolver
        if callback is None:
            raise OptionalResolverUnavailableError("optional 1Password resolver is not configured", route=ROUTE_ONEPASSWORD)
        raw = self._mapping(self._call(callback, "1Password resolve", ROUTE_ONEPASSWORD, item_ref=item_ref, owner_id=owner_id, context_id=context_id), "1Password resolve", ROUTE_ONEPASSWORD)
        owner_for_check = owner_id or _pick(raw, "owner_id", "account_id", "agent_id") or "optional-owner"
        self._identity(raw, owner_for_check, context_id)
        state = _state(raw)
        if state in _DENIED:
            raise AccessDeniedError("1Password resolve was denied", route=ROUTE_ONEPASSWORD)
        expiry, moment = _expires(raw)
        if moment is not None and moment <= self._now():
            raise AccessExpiredError("1Password result is expired", route=ROUTE_ONEPASSWORD)
        return {"route": ROUTE_ONEPASSWORD, "state": "metadata_only", "item_ref": item_ref, "expires_at": expiry, "metadata": _metadata(raw)}


__all__ = ["AccessCallbackError", "AccessDeniedError", "AccessError", "AccessExpiredError", "AccessManager", "AccessResponseError", "AccessUnavailableError", "IdentityMismatchError", "OptionalResolverUnavailableError", "RouteUnavailableError", "UnsupportedRouteError", "ROUTE_LOCAL_BROWSERBASE", "ROUTE_MANAGED_BROWSERBASE", "ROUTE_ONEPASSWORD", "ROUTE_SECURE_ACCESS", "sanitize_metadata"]
