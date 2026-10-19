"""Strict, profile-scoped configuration for the PA conversation bridge."""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DESTINATION_KEYS = frozenset({"session_key", "platform", "chat_type", "chat_id", "thread_id"})
ALLOWED_CHAT_TYPES = frozenset({"dm", "group", "forum"})
ROUTE_SOURCE = "existing-host-session"


class ActivationError(ValueError):
    """Configuration cannot safely activate the bridge."""


@dataclass(frozen=True)
class BridgeSettings:
    state_dir: Path
    profile_name: str
    namespace: str
    destination: dict[str, str]
    poll_interval_seconds: float
    max_packet_bytes: int
    priority_mail: bool = False


def _bounded_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ActivationError(f"{field} must be a non-empty string of at most {limit} characters")
    if any(ord(ch) < 32 and ch not in "\n\t\r" for ch in value):
        raise ActivationError(f"{field} contains a control character")
    return value


def validate_destination(value: Any) -> dict[str, str]:
    """Validate one exact Telegram topic destination; no wildcards or defaults."""
    if not isinstance(value, Mapping) or set(value) != DESTINATION_KEYS:
        raise ActivationError(
            "destination must contain exactly session_key, platform, chat_type, chat_id, thread_id"
        )
    result = {
        key: _bounded_text(value[key], f"destination.{key}", 512)
        for key in DESTINATION_KEYS
    }
    if result["platform"].lower() != "telegram":
        raise ActivationError("only the installed Telegram injection route is supported")
    result["platform"] = "telegram"
    if result["chat_type"] not in ALLOWED_CHAT_TYPES:
        raise ActivationError("destination.chat_type must be dm, group, or forum")
    if result["thread_id"] == "":
        raise ActivationError("destination.thread_id is required for PA topic delivery")
    if result["session_key"].startswith("synthetic-") or any(
        marker in result["session_key"] for marker in ("<", ">", "REPLACE")
    ):
        raise ActivationError("destination.session_key must be the exact non-placeholder host key")
    if any(marker in result["chat_id"] or marker in result["thread_id"] for marker in ("<", ">", "REPLACE")):
        raise ActivationError("destination chat/topic identifiers must be exact non-placeholder values")
    return result


def _private_state_dir(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ActivationError("settings.state_dir is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ActivationError("settings.state_dir must be an absolute path")
    return path


def reject_symlink_ancestors(path: Path, *, field: str = "path") -> None:
    """Reject a symlink at any existing component before a private write."""
    path = Path(path).expanduser()
    probe = path
    while True:
        try:
            if probe.is_symlink():
                raise ActivationError(f"{field} has a symlink ancestor: {probe}")
        except OSError as exc:
            raise ActivationError(f"cannot inspect {field}: {probe}") from exc
        if probe.parent == probe:
            return
        probe = probe.parent


def require_under_home(path: Path, home: Path, *, field: str) -> Path:
    """Return a canonical path only when it stays inside the active profile home."""
    path = Path(path).expanduser()
    home = Path(home).expanduser()
    if not path.is_absolute() or not home.is_absolute():
        raise ActivationError(f"{field} and active HERMES_HOME must be absolute")
    reject_symlink_ancestors(home, field="active HERMES_HOME")
    reject_symlink_ancestors(path, field=field)
    try:
        resolved_home = home.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        resolved_path.relative_to(resolved_home)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ActivationError(f"{field} must remain inside the active Hermes profile") from exc
    return resolved_path


def load_settings(raw: Mapping[str, Any]) -> BridgeSettings:
    """Parse settings and require a single, verified, exact existing-session route."""
    if not isinstance(raw, Mapping):
        raise ActivationError("plugin settings must be a mapping")
    route = raw.get("route")
    if not isinstance(route, Mapping):
        raise ActivationError("settings.route is required")
    if route.get("source") != ROUTE_SOURCE:
        raise ActivationError(f"route.source must be exactly {ROUTE_SOURCE!r}")
    if route.get("verified") is not True:
        raise ActivationError("route.verified must be true after an exact host session readback")
    profile_name = _bounded_text(route.get("profile_name"), "route.profile_name", 128)
    namespace = _bounded_text(route.get("namespace"), "route.namespace", 128)
    destination = validate_destination(route.get("destination"))
    if not destination["session_key"].startswith(f"agent:{namespace}:"):
        raise ActivationError("destination.session_key does not match the exact route namespace")
    allowlist = route.get("allowlist")
    if not isinstance(allowlist, list) or len(allowlist) != 1:
        raise ActivationError("route.allowlist must contain exactly one destination")
    if validate_destination(allowlist[0]) != destination:
        raise ActivationError("route.destination must equal the sole exact allowlist entry")

    state_dir = _private_state_dir(raw.get("state_dir"))
    try:
        interval = float(raw.get("poll_interval_seconds", 15.0))
    except (TypeError, ValueError) as exc:
        raise ActivationError("poll_interval_seconds must be a number") from exc
    if "claim_lease_seconds" in raw:
        raise ActivationError("claim_lease_seconds is unsupported; crash fencing is explicit at gateway startup")
    if not (0.1 <= interval <= 300.0):
        raise ActivationError("poll_interval_seconds must be between 0.1 and 300")
    max_packet_bytes = raw.get("max_packet_bytes", 16 * 1024)
    if isinstance(max_packet_bytes, bool) or not isinstance(max_packet_bytes, int):
        raise ActivationError("max_packet_bytes must be an integer")
    if not (4096 <= max_packet_bytes <= 16 * 1024):
        raise ActivationError("max_packet_bytes must be between 4096 and 16384")
    priority_mail = raw.get("priority_mail", False)
    if not isinstance(priority_mail, bool):
        raise ActivationError("priority_mail must be a boolean")
    return BridgeSettings(state_dir, profile_name, namespace, destination, interval, max_packet_bytes, priority_mail)


def _check_private_stat(path: Path, *, field: str, directory: bool) -> None:
    try:
        info = path.stat()
    except OSError as exc:
        raise ActivationError(f"cannot stat {field}: {path}") from exc
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ActivationError(f"{field} is not owned by the active user: {path}")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        kind = "directory" if directory else "file"
        raise ActivationError(f"private {kind} must not be group/world accessible: {path}")


def ensure_private_dir(path: Path) -> None:
    """Create/check a private, active-user-owned directory."""
    path = Path(path)
    reject_symlink_ancestors(path, field="state directory")
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise ActivationError(f"state directory is not a private directory: {path}")
    else:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    # Another publisher may have created it after the existence check.
    # Revalidate rather than treating benign concurrent creation as failure.
    reject_symlink_ancestors(path, field="state directory")
    if path.is_symlink() or not path.is_dir():
        raise ActivationError(f"state directory is not a private directory: {path}")
    _check_private_stat(path, field="state directory", directory=True)


def ensure_private_file(path: Path) -> None:
    """Reject symlinks, foreign owners, and group/world-readable files."""
    path = Path(path)
    reject_symlink_ancestors(path, field="private file")
    if path.is_symlink():
        raise ActivationError(f"refusing symlinked private file: {path}")
    if path.exists():
        if not path.is_file():
            raise ActivationError(f"private file is not a regular file: {path}")
        _check_private_stat(path, field="private file", directory=False)


def atomic_private_write(path: Path, data: bytes) -> None:
    """Write a bounded private marker by rename, never by in-place truncation."""
    import tempfile

    ensure_private_dir(path.parent)
    ensure_private_file(path)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass
