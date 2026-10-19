#!/usr/bin/env python3
"""Hermes pre_tool_call shell gateway for generic PA authorizations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from personal_assistant.action_gateway import ActionAuthorizationStore, Gateway, GatewayPolicy, _reject_duplicate_pairs
from personal_assistant.state import Ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-root", required=True)
    parser.add_argument("--profile-id", help="Defaults to the managed profile directory name.")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--at", help="Deterministic synthetic-test timestamp; omit in managed deployment.")
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin, object_pairs_hook=_reject_duplicate_pairs)
        policy = GatewayPolicy.load(args.policy)
        tool_name = payload.get("tool_name") if isinstance(payload, dict) else None
        tool_input = payload.get("tool_input", payload.get("args")) if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("hook_event_name", "pre_tool_call") != "pre_tool_call"
            or not isinstance(tool_name, str)
            or not tool_name
            or not isinstance(tool_input, dict)
        ):
            decision = Gateway._block("DENY_INVALID_PAYLOAD")
            print(json.dumps(decision, sort_keys=True, separators=(",", ":")))
            return 2
        if policy.classify(tool_name) == "denied":
            decision = Gateway._block("DENY_ADMIN_POLICY", tool_name)
            print(json.dumps(decision, sort_keys=True, separators=(",", ":")))
            return 2
        profile_root = Path(args.profile_root).expanduser()
        if not profile_root.exists():
            return 0
        profile_id = args.profile_id or profile_root.resolve().name
        store = ActionAuthorizationStore(Ledger(profile_root), profile_id)
        gateway = Gateway(store, policy, now=(lambda: args.at) if args.at else None)
        decision = gateway.evaluate(payload)
    except Exception:
        decision = Gateway._block("DENY_INTERNAL_ERROR")
    if decision:
        print(json.dumps(decision, sort_keys=True, separators=(",", ":")))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
