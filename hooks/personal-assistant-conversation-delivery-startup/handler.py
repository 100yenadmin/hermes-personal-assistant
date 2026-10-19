"""Supported Hermes gateway hook for the bridge's startup-only crash fence."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def _settings() -> dict[str, Any]:
    from hermes_cli.config import load_config

    config = load_config() or {}
    entry = ((config.get("plugins") or {}).get("entries") or {}).get("personal-assistant") or {}
    settings = entry.get("settings") if isinstance(entry, dict) else None
    delivery = settings.get("conversation_delivery") if isinstance(settings, dict) else None
    return delivery if isinstance(delivery, dict) else {}


def _bridge_signal(state_dir: Path, platforms: list[Any]) -> None:
    """Delegate marker creation to the installed plugin's production helper.

    The host discovers this file outside the plugin tree.  In a native install
    the package lives at ``$HERMES_HOME/plugins/personal-assistant``; the
    fallback also works when the plugin was loaded from an editable checkout.
    """
    try:
        from personal_assistant.conversation_delivery.bridge import signal_gateway_startup
    except ImportError:
        from hermes_constants import get_hermes_home

        plugin_root = Path(get_hermes_home()).expanduser() / "plugins" / "personal-assistant"
        package_root = plugin_root / "personal_assistant"
        if not package_root.is_dir():
            raise
        added = str(plugin_root)
        sys.path.insert(0, added)
        try:
            from personal_assistant.conversation_delivery.bridge import signal_gateway_startup
        finally:
            if sys.path and sys.path[0] == added:
                sys.path.pop(0)
    signal_gateway_startup(state_dir, platforms=[str(item) for item in platforms[:16]])


def _private_state_dir(raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        return None
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home()).expanduser()
    try:
        for candidate in (home, path):
            probe = candidate
            while True:
                if probe.is_symlink():
                    return None
                if probe.parent == probe:
                    break
                probe = probe.parent
        resolved_home = home.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        resolved_path.relative_to(resolved_home)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved_path


def handle(event_type: str, context: dict[str, Any]) -> None:
    if event_type != "gateway:startup":
        return None
    settings = _settings()
    if settings.get("enabled") is not True:
        return None
    state_dir = _private_state_dir(settings.get("state_dir"))
    if state_dir is not None:
        _bridge_signal(state_dir, list(context.get("platforms") or []))
    return None
