#!/usr/bin/env python3
"""Explicitly install the PA gateway-startup hook into one Hermes profile.

This is deliberately separate from plugin registration.  It never enables the
plugin, grants gateway injection, creates jobs, changes an existing file's
mode, or restarts Hermes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Mapping

try:
    import yaml
except ImportError:  # pragma: no cover - Hermes supplies PyYAML
    yaml = None


HOOK_NAME = "personal-assistant-conversation-delivery-startup"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_HOOK = SOURCE_ROOT / "hooks" / HOOK_NAME
FILES = ("HOOK.yaml", "handler.py")
PERMISSION_KEY = "plugins.entries.personal-assistant.allow_gateway_injection"


class SetupError(ValueError):
    """The requested profile or hook target is not safe to inspect/change."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mode(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode))


def _check_private(path: Path, *, directory: bool, field: str) -> None:
    if path.is_symlink() or (directory and not path.is_dir()) or (not directory and not path.is_file()):
        raise SetupError(f"{field} must be a regular private {'directory' if directory else 'file'}")
    info = path.stat()
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise SetupError(f"{field} is not owned by the active user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise SetupError(f"{field} must not be group/world accessible")


def _reject_symlink_ancestors(path: Path, *, field: str) -> None:
    probe = path
    while True:
        if probe.is_symlink():
            raise SetupError(f"{field} has a symlink ancestor: {probe}")
        if probe.parent == probe:
            return
        probe = probe.parent


def _profile_name(home: Path) -> str:
    value = os.environ.get("HERMES_PROFILE_NAME") or os.environ.get("HERMES_PROFILE")
    if value:
        if not value or any(ch in value for ch in "/\\\x00"):
            raise SetupError("HERMES_PROFILE_NAME is invalid")
        return value
    if home.name == ".hermes":
        return "default"
    if home.parent.name == "profiles":
        return home.name
    return "custom"


def _home_from_args(raw: str | None) -> Path:
    selected = raw or os.environ.get("HERMES_HOME")
    if not selected:
        raise SetupError("set HERMES_HOME or pass --hermes-home; the target is never guessed")
    home = Path(selected).expanduser()
    if not home.is_absolute():
        raise SetupError("Hermes home must be an absolute path")
    _reject_symlink_ancestors(home, field="Hermes home")
    _check_private(home, directory=True, field="Hermes home")
    return home.resolve(strict=True)


def _load_host_config(home: Path) -> tuple[dict[str, Any], str | None]:
    path = home / "config.yaml"
    if not path.exists():
        return {}, "config.yaml is missing"
    _check_private(path, directory=False, field="config.yaml")
    try:
        if yaml is None:
            raise SetupError("PyYAML is required to inspect Hermes config.yaml")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except SetupError:
        raise
    except Exception as exc:
        return {}, f"config.yaml is invalid: {type(exc).__name__}"
    if not isinstance(raw, dict):
        return {}, "config.yaml must contain a mapping"
    return raw, None


def _settings_report(home: Path) -> dict[str, Any]:
    config, config_error = _load_host_config(home)
    entries = ((config.get("plugins") or {}).get("entries") or {}) if isinstance(config, Mapping) else {}
    entry = entries.get("personal-assistant") if isinstance(entries, Mapping) else None
    entry = entry if isinstance(entry, Mapping) else {}
    settings = entry.get("settings") if isinstance(entry.get("settings"), Mapping) else {}
    delivery = settings.get("conversation_delivery") if isinstance(settings.get("conversation_delivery"), Mapping) else {}
    permission = entry.get("allow_gateway_injection")
    report: dict[str, Any] = {
        "config_error": config_error,
        "plugin_enabled": "personal-assistant" in ((config.get("plugins") or {}).get("enabled") or []) if isinstance(config, Mapping) else False,
        "conversation_delivery_enabled": delivery.get("enabled") is True,
        "allow_gateway_injection": {
            "key": PERMISSION_KEY,
            "configured": permission is True,
            "value_type": type(permission).__name__ if permission is not None else "missing",
            "action": "already_granted" if permission is True else "operator_must_set_explicitly",
        },
        "active_profile": _profile_name(home),
        "route": {"status": "not_configured"},
    }
    if config_error or delivery.get("enabled") is not True:
        return report
    try:
        sys.path.insert(0, str(SOURCE_ROOT))
        from personal_assistant.conversation_delivery.config import load_settings, require_under_home
        parsed = load_settings(delivery)
        contained = require_under_home(parsed.state_dir, home, field="conversation_delivery.state_dir")
        if parsed.profile_name != report["active_profile"]:
            raise SetupError("route.profile_name does not match the active Hermes profile")
        report["route"] = {
            "status": "valid",
            "profile_name": parsed.profile_name,
            "namespace": parsed.namespace,
            "session_key": parsed.destination["session_key"],
            "state_dir": str(contained),
            "priority_mail_scope": delivery.get("priority_mail") is True,
        }
    except Exception as exc:
        report["route"] = {"status": "invalid", "error": str(exc)[:500]}
    finally:
        if sys.path and sys.path[0] == str(SOURCE_ROOT):
            sys.path.pop(0)
    return report


def _target(home: Path) -> Path:
    hooks = home / "hooks"
    _reject_symlink_ancestors(hooks, field="hooks target")
    if hooks.exists():
        _check_private(hooks, directory=True, field="hooks target")
    return hooks / HOOK_NAME


def _preflight_target(target: Path) -> tuple[str, dict[str, dict[str, Any]]]:
    if target.exists() or target.is_symlink():
        _check_private(target, directory=True, field="hook target")
        action = "already_installed"
    else:
        action = "install"
    files: dict[str, dict[str, Any]] = {}
    for name in FILES:
        source = SOURCE_HOOK / name
        if not source.is_file() or source.is_symlink():
            raise SetupError(f"packaged hook file is missing or unsafe: {source}")
        data = source.read_bytes()
        destination = target / name
        if destination.exists() or destination.is_symlink():
            _check_private(destination, directory=False, field=f"existing hook file {name}")
            existing = destination.read_bytes()
            if existing != data:
                raise SetupError(f"existing hook file has different content; refusing collision: {destination}")
            status = "unchanged"
        else:
            status = "create"
            if action == "already_installed":
                action = "repair_missing_file"
        files[name] = {"status": status, "sha256": _sha256(data), "bytes": len(data), "mode": "0o600"}
    return action, files


def _ensure_directory(path: Path, *, field: str) -> None:
    _reject_symlink_ancestors(path, field=field)
    if path.exists():
        _check_private(path, directory=True, field=field)
        return
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _check_private(path, directory=True, field=field)


def _create_if_absent(path: Path, data: bytes) -> None:
    _reject_symlink_ancestors(path, field="hook file")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        _check_private(path, directory=False, field="existing hook file")
        if path.read_bytes() != data:
            raise SetupError(f"existing hook file has different content; refusing collision: {path}")
        return
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def _readback(target: Path, files: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for name, expected in files.items():
        path = target / name
        _check_private(path, directory=False, field=f"installed hook file {name}")
        data = path.read_bytes()
        observed[name] = {"sha256": _sha256(data), "bytes": len(data), "mode": _mode(path)}
        if observed[name]["sha256"] != expected["sha256"] or observed[name]["bytes"] != expected["bytes"]:
            raise SetupError(f"hook readback did not match packaged bytes: {path}")
    return observed


def install(home: Path, *, dry_run: bool) -> dict[str, Any]:
    if not SOURCE_HOOK.is_dir():
        raise SetupError(f"packaged hook directory is missing: {SOURCE_HOOK}")
    hooks = home / "hooks"
    if hooks.exists():
        _check_private(hooks, directory=True, field="hooks target")
    elif dry_run:
        # No filesystem mutation is allowed in preview mode.
        pass
    target = _target(home)
    action, files = _preflight_target(target) if target.exists() else ("install", {
        name: {"status": "create", "sha256": _sha256((SOURCE_HOOK / name).read_bytes()),
               "bytes": (SOURCE_HOOK / name).stat().st_size, "mode": "0o600"}
        for name in FILES
    })
    result: dict[str, Any] = {
        "ok": True,
        "dry_run": dry_run,
        "action": "would_" + action if dry_run else action,
        "hermes_home": str(home),
        "hook_target": str(target),
        "files": files,
        "permission": _settings_report(home),
        "jobs_created": False,
        "plugin_enabled": False,
        "gateway_restarted": False,
    }
    if dry_run:
        result["readback"] = {"performed": False, "reason": "dry-run does not write"}
        return result
    _ensure_directory(hooks, field="hooks target")
    _ensure_directory(target, field="hook target")
    for name in FILES:
        _create_if_absent(target / name, (SOURCE_HOOK / name).read_bytes())
    result["readback"] = {"performed": True, "files": _readback(target, files)}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicitly install the PA gateway-startup hook")
    parser.add_argument("command", nargs="?", choices=("install", "setup"), default="install")
    parser.add_argument("--hermes-home", help="caller-approved absolute Hermes profile home")
    parser.add_argument("--dry-run", action="store_true", help="validate and report without writing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        home = _home_from_args(args.hermes_home)
        result = install(home, dry_run=args.dry_run)
    except (OSError, SetupError, ValueError) as exc:
        result = {"ok": False, "error": str(exc)[:500]}
        text = json.dumps(result, sort_keys=True, separators=(",", ":") if args.json else None)
        print(text, file=sys.stderr)
        return 2
    text = json.dumps(result, sort_keys=True, separators=(",", ":") if args.json else None)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
