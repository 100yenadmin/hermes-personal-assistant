"""HB2 pulse substitute for role_followthrough only; no engine or provider calls."""
import datetime as dt
import json

from evals.lab.common import append, read
from evals.lab.cos import variables


def register(ctx, obs):
    from hermes_cli.middleware import TOOL_EXECUTION_MIDDLEWARE
    wakes, counts = [], {}

    def middleware(tool_name, args, next_call, **kw):
        if tool_name != "pulse":
            return next_call(args)
        with obs.lock:
            action = args.get("action")
            result = {"error": "Unsupported lab pulse action; use list, create or respond."}
            if action == "list":
                role = obs.lab["role"]
                result = {"wakes": [{"id": role["id"], "title": role["title"], "role": True}, *wakes]}
            elif action == "respond":
                if isinstance(args.get("outcome"), str) and args["outcome"].strip() and type(args.get("notify")) is bool:
                    result = {"ok": True}
                else:
                    result = {"error": "respond requires outcome and boolean notify."}
            elif action == "create":
                trigger = args.get("trigger")
                trigger = trigger if isinstance(trigger, dict) else {}
                if trigger.get("kind") != "at":
                    result = {"error": "Lab pulse accepts only trigger.kind at."}
                elif args.get("owner_asked") is True:
                    result = {"error": "owner_asked is ignored in a role turn; omit it.", "owner_asked_ignored": "wake_turn"}
                elif counts.get(obs.step, 0) >= 3:
                    result = {"error": "max_children_per_wake_turn: 3"}
                else:
                    try:
                        start = dt.datetime.fromisoformat(read(obs.out / "seed.json")["variables"]["now"])
                        step = obs.scenario["steps"][obs.step]
                        now = dt.datetime.fromisoformat(variables(obs.scenario["timezone"], start,
                            step.get("hour", 12), step.get("day", 0))["now"])
                        at = dt.datetime.fromisoformat(trigger["at"].replace("Z", "+00:00"))
                        if at.tzinfo is None or at <= now:
                            raise ValueError("future offset timestamp required")
                    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
                        result = {"error": "at must be an ISO timestamp with offset after the step's synthetic now."}
                    else:
                        receipt = {"id": f"lab-at-{len(wakes) + 1}", "armed": True, "kind": "at",
                                   "at": at.isoformat(), "title": args.get("title", "")}
                        wakes.append({**receipt, "note": args.get("note", "")})
                        counts[obs.step] = counts.get(obs.step, 0) + 1
                        result = receipt
            append(obs.out / "pulse-calls.jsonl", {"step": obs.step, "action": action, "args": args, "result": result})
            return json.dumps(result)

    ctx.register_middleware(TOOL_EXECUTION_MIDDLEWARE, middleware)
