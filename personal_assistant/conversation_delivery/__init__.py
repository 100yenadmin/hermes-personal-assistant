"""Opt-in PA conversation delivery: bounded evidence, queue, and gateway bridge.

The package is inert until the native personal-assistant plugin receives an
explicit ``conversation_delivery.enabled: true`` setting.  Producer and
collector entrypoints remain usable with synthetic providers in an isolated
profile; no provider or gateway work occurs at import time.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from .bridge import BridgeRuntime
from .config import ActivationError, load_settings, require_under_home

logger = logging.getLogger(__name__)

ACK_SCHEMA = {
    "name": "pa_delivery_ack",
    "description": (
        "Acknowledge or silence the currently processed PA automation packet. "
        "The invoking gateway session is bound by Hermes; do not provide a destination."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "event_id": {"type": "string", "description": "event_id from the packet"},
            "revision": {"type": "string", "description": "revision from the packet"},
            "claim_token": {"type": "string", "description": "ack_claim_token from the packet"},
            "outcome": {"type": "string", "enum": ["handled", "silent"]},
        },
        "required": ["event_id", "revision", "claim_token", "outcome"],
        "additionalProperties": False,
    },
}


def _enabled_settings(ctx: Any) -> Mapping[str, Any] | None:
    """Read only the native plugin setting; absent/false means fully inert."""
    getter = getattr(ctx, "get_config", None)
    if not callable(getter):
        return None
    raw = getter("conversation_delivery", None)
    if not isinstance(raw, Mapping) or raw.get("enabled") is not True:
        return None
    return raw


def register_if_enabled(ctx: Any) -> BridgeRuntime | None:
    """Wire the bridge only after explicit opt-in and exact route validation.

    This is called from the existing ``personal-assistant`` plugin registration;
    it never registers a second plugin or starts work when disabled.  A
    no-event-loop surface (CLI/cron discovery) still gets the ack registration
    and private queue, but deliberately does not start a consumer task.
    """
    raw = _enabled_settings(ctx)
    if raw is None:
        return None

    settings = load_settings(raw)
    active_profile = getattr(ctx, "profile_name", "")
    if active_profile != settings.profile_name:
        raise ActivationError(
            "conversation_delivery.route.profile_name must match the active Hermes profile"
        )

    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home()).expanduser()
    state_dir = require_under_home(settings.state_dir, home, field="conversation_delivery.state_dir")
    settings = replace(settings, state_dir=state_dir)
    runtime = BridgeRuntime(ctx, settings)
    ctx.register_tool(
        name=ACK_SCHEMA["name"],
        toolset="personal_assistant",
        schema=ACK_SCHEMA,
        handler=runtime.ack_tool,
        description=ACK_SCHEMA["description"],
    )

    coroutine = runtime.run()
    try:
        ctx.spawn_task(coroutine, name="personal-assistant-conversation-delivery")
    except RuntimeError:
        # Plugin discovery also occurs on CLI/cron surfaces without a running
        # gateway loop.  Queue publication remains available; consumption is
        # gated to the gateway startup hook and host-supervised task.
        coroutine.close()
        logger.info("PA conversation delivery consumer not started: no running gateway loop")
    ctx.on_unload(runtime.stop)
    return runtime


__all__ = ["ACK_SCHEMA", "ActivationError", "BridgeRuntime", "register_if_enabled"]
