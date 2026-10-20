"""Native Hermes entry point; installation registers capabilities but starts no jobs."""
from pathlib import Path
import json
import os
import threading


def _skill_metadata(path):
    """Read only YAML frontmatter so discovery stays lazy."""
    with path.open(encoding="utf-8") as handle:
        text = handle.read(8192)
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return {}, ""
    header = text.split("\n---\n", 1)[0][4:]
    try:
        import yaml
        frontmatter = yaml.safe_load(header) or {}
    except Exception:
        frontmatter = {}
        for line in header.splitlines():
            if line and not line[0].isspace() and ":" in line:
                key, value = line.split(":", 1)
                frontmatter[key.strip()] = value.strip().strip("\"'")
    return frontmatter, str(frontmatter.get("description", ""))


def register(ctx):
    from .personal_assistant.entry import dispatch, SCHEMA
    from .personal_assistant.action_gateway import GatewayPolicy
    from .personal_assistant.native_gateway_runtime import (
        NativeActionAuthorizationStore,
        NativeGateway,
    )
    from .personal_assistant.state import Ledger
    from .personal_assistant.conversation_delivery import register_if_enabled
    from .personal_assistant.modes import cos_enabled

    get_config = getattr(ctx, "get_config", lambda key, default: default)
    chief_of_staff = cos_enabled(get_config)

    configured_home = os.environ.get("HERMES_HOME")
    manager_home = getattr(getattr(ctx, "_manager", None), "home_path", None)
    root = Path(configured_home or manager_home or Path.home() / ".hermes").resolve()
    policy_path = Path(__file__).parent / "config" / "pa-action-gateway-policy.example.json"
    policy = GatewayPolicy.load(policy_path)
    gateway_lock = threading.RLock()
    gateway = None

    def runtime_gateway():
        nonlocal gateway
        with gateway_lock:
            if gateway is None:
                store = NativeActionAuthorizationStore(Ledger(root), root.name)
                gateway = NativeGateway(store, policy)
            return gateway

    def handle(args, **kwargs):
        active_gateway = runtime_gateway()
        return json.dumps(dispatch(root, args, runtime_scope={
            "session_id": kwargs.get("session_id"),
            "task_id": kwargs.get("task_id"),
            "observe_settings": get_config("observe", {}) if callable(get_config) else {},
            "get_config": get_config,
            "authorization_store": active_gateway.store,
        }), ensure_ascii=False)

    ctx.register_tool(name="pa", toolset="personal_assistant", schema=SCHEMA,
                      handler=handle, description=SCHEMA["description"])

    from .personal_assistant.calls import dispatch as call_dispatch, SCHEMA as CALL_SCHEMA

    def handle_call(args, **kwargs):
        get_calls_config = getattr(ctx, "get_config", None)
        config = get_calls_config("calls", {}) if callable(get_calls_config) else {}
        return json.dumps(call_dispatch(root, args, config=config,
                                       session_id=kwargs.get("session_id")), ensure_ascii=False)

    ctx.register_tool(name="pa_call", toolset="personal_assistant", schema=CALL_SCHEMA,
                      handler=handle_call, description=CALL_SCHEMA["description"])

    def enforce_action_authorization(tool_name, args, **kwargs):
        # Read-only diagnostics never need PA state, so they are classified before
        # the ledger is touched and stay usable when durable state is broken.
        if NativeGateway.is_diagnostic_call(policy, tool_name, args):
            return None
        try:
            active_gateway = runtime_gateway()
        except Exception as exc:
            # Construction failures are not cached; a later call retries and
            # self-heals once storage is readable again.
            return NativeGateway.state_unavailable_block(tool_name, exc)
        try:
            return active_gateway.evaluate({
                "hook_event_name": "pre_tool_call",
                "tool_name": tool_name,
                "tool_input": args,
                "session_id": kwargs.get("session_id"),
                "task_id": kwargs.get("task_id"),
            })
        except Exception as exc:
            return NativeGateway.internal_block(tool_name, "EVALUATION", exc)

    ctx.register_hook("pre_tool_call", enforce_action_authorization)
    from .personal_assistant.commands import make_pa_command
    from .personal_assistant.onboarding_hook import make_pre_llm_call
    register_command = getattr(ctx, "register_command", None)
    if callable(register_command):
        register_command("pa", make_pa_command(root, get_config, getattr(ctx, "set_config", None)), description="Personal Assistant: guided setup, modes and status",
                         args_hint="setup | setup review | status | mode | help")
    get_config = getattr(ctx, "get_config", None)
    ctx.register_hook("pre_llm_call", make_pre_llm_call(
        root, lambda key, default: get_config(key, default) if callable(get_config) else default))
    register_if_enabled(ctx)
    for path in sorted((Path(__file__).parent / "skills").rglob("SKILL.md")):
        frontmatter, description = _skill_metadata(path)
        metadata = frontmatter.get("metadata") or {}
        hermes = metadata.get("hermes") if isinstance(metadata, dict) else None
        if isinstance(hermes, dict) and hermes.get("pa_mode") == "chief_of_staff" and not chief_of_staff:
            continue
        ctx.register_skill(path.parent.name, path, description=description, frontmatter=frontmatter)
