"""Profile-scoped arbitration for the two supported P1 entrypoints.

The lock is a coordination primitive, not a second occurrence or receipt
ledger.  When conversation delivery explicitly owns P1, the legacy watchdog
is a no-read/no-publish route; otherwise the legacy watchdog keeps its existing
output.  The production conversation runner requires both host opt-ins to be
literal ``true``; absent or false settings leave P1 with the legacy route.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    import yaml
except ImportError:  # pragma: no cover - host Hermes supplies PyYAML
    yaml = None


LOCK_NAME = ".pa-priority-collection.lock"


class PriorityOwnershipError(ValueError):
    """Profile arbitration could not be established safely."""


@dataclass(frozen=True)
class PriorityCollectionDecision:
    state: str  # owned, delegated, disabled, busy
    reason: str

    @property
    def owned(self) -> bool:
        return self.state == "owned"


def _private_profile(home: Path) -> Path:
    home = Path(home).expanduser()
    if not home.is_absolute() or home.is_symlink() or not home.is_dir():
        raise PriorityOwnershipError("active Hermes profile must be an existing directory")
    info = home.stat()
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise PriorityOwnershipError("active Hermes profile is not owned by the active user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise PriorityOwnershipError("active Hermes profile must not be group/world accessible")
    probe = home
    while True:
        if probe.is_symlink():
            raise PriorityOwnershipError("active Hermes profile has a symlink ancestor")
        if probe.parent == probe:
            break
        probe = probe.parent
    return home.resolve(strict=True)


def conversation_priority_setting(home: Path) -> bool | None:
    """Return explicit conversation P1 ownership, or ``None`` if unconfigured."""
    home = _private_profile(home)
    config_path = home / "config.yaml"
    if not config_path.exists():
        return None
    if config_path.is_symlink() or not config_path.is_file():
        raise PriorityOwnershipError("Hermes config.yaml is not a regular file")
    info = config_path.stat()
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise PriorityOwnershipError("Hermes config.yaml is not owned by the active user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise PriorityOwnershipError("Hermes config.yaml must not be group/world accessible")
    if yaml is None:
        raise PriorityOwnershipError("PyYAML is required to read Hermes config.yaml")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise PriorityOwnershipError("Hermes config.yaml could not be read") from exc
    if not isinstance(config, Mapping):
        raise PriorityOwnershipError("Hermes config.yaml must contain a mapping")
    plugins = config.get("plugins")
    if not isinstance(plugins, Mapping):
        return None
    entries = plugins.get("entries")
    if not isinstance(entries, Mapping):
        return None
    entry = entries.get("personal-assistant")
    if not isinstance(entry, Mapping):
        return None
    settings = entry.get("settings")
    if not isinstance(settings, Mapping):
        return None
    delivery = settings.get("conversation_delivery")
    if not isinstance(delivery, Mapping):
        return None
    priority_mail = delivery.get("priority_mail")
    if priority_mail is not None and not isinstance(priority_mail, bool):
        raise PriorityOwnershipError("conversation_delivery.priority_mail must be a JSON/YAML boolean")
    enabled = delivery.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise PriorityOwnershipError("conversation_delivery.enabled must be a JSON/YAML boolean")
    if priority_mail is True and enabled is True:
        return True
    if priority_mail is False or enabled is False:
        return False
    return None


def _lock_path(home: Path) -> Path:
    # Keep the coordination file at the profile root so it is shared by the
    # legacy daily-ops state and the conversation bridge state without making
    # either state directory the other's parent.
    lock_path = home / LOCK_NAME
    if lock_path.exists() or lock_path.is_symlink():
        if lock_path.is_symlink() or not lock_path.is_file():
            raise PriorityOwnershipError("priority collection lock is not a regular file")
        info = lock_path.stat()
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise PriorityOwnershipError("priority collection lock is not user-owned")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise PriorityOwnershipError("priority collection lock must be private")
    return lock_path


@contextlib.contextmanager
def priority_collection_lease(home: Path, publisher: str) -> Iterator[PriorityCollectionDecision]:
    """Choose exactly one P1 publisher and hold its profile lock during collection.

    ``legacy`` is delegated without opening the provider when conversation P1 is
    explicitly enabled.  ``conversation`` is disabled unless both host opt-ins
    are explicitly true; direct collector helpers remain independently usable
    for offline tests without granting the production runner ownership.
    """
    if publisher not in {"legacy", "conversation"}:
        raise PriorityOwnershipError("publisher must be legacy or conversation")
    home = _private_profile(home)
    setting = conversation_priority_setting(home)
    if publisher == "legacy" and setting is True:
        yield PriorityCollectionDecision("delegated", "conversation_delivery owns priority_mail for this profile")
        return
    if publisher == "conversation" and setting is not True:
        yield PriorityCollectionDecision(
            "disabled",
            "conversation_delivery priority_mail ownership is not explicitly enabled",
        )
        return

    lock_path = _lock_path(home)
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        raise PriorityOwnershipError("priority collection lock could not be opened") from exc
    try:
        # Do not chmod an existing file; reject a non-private lock instead.
        info = os.fstat(fd)
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise PriorityOwnershipError("priority collection lock must be private")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield PriorityCollectionDecision("busy", "another P1 publisher owns the profile collection lock")
            return
        yield PriorityCollectionDecision("owned", f"{publisher} owns the profile priority collection")
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
