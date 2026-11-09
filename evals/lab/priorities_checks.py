"""s39 priorities oracle over synthetic ledger snapshots and reports; no model or provider IO."""
import json
import re

from .common import lines, read
from .m34_checks import fields, report
from .minutes_checks import nothing_sent

# Any tool whose name reads as a write fails; harmless Hermes reads (todo, skills_list, web_search) pass.
WRITE_NAME = re.compile(r"post|publish|tweet|manage|(?:^|_)(?:write|save|draft|send|create|update|delete|archive|label|patch|"
                        r"remember|forget|execute|terminal|submit|click|type|press|fill|select|upload)(?:_|$)", re.I)
READ_OPS = {"status", "capabilities", "context", "recipes", "next_action", "evidence"}


def _allowed(tool):
    name = str(tool.get("name") or "")
    if name != "pa":
        return not WRITE_NAME.search(name)
    args = tool.get("structured_args") or {}
    data = args.get("data") or {}
    try:
        data = json.loads(data) if isinstance(data, str) else data
    except ValueError:
        return False
    action = data.get("action") if isinstance(data, dict) else None
    op = args.get("operation")
    return op in READ_OPS | {"action_upsert"} or op == "profile" and action in {None, "list", "pending_files"}


def _prose(text):
    for match in re.finditer(r"\{", text):
        try:
            value, _ = json.JSONDecoder().raw_decode(text[match.start():])
        except ValueError:
            continue
        if isinstance(value, dict) and "lab_summary" in value:
            return text[:match.start()]
    return text


def _contains(value, keyword):
    return isinstance(value, str) and keyword.casefold() in value.casefold()


def evaluate(root, scenario, index, messages, tools):
    lab = scenario["lab"]
    text = messages[-1] if messages else ""
    summary, prose = report(text), _prose(text)
    db = read(root / f"ledger-step-{index}.json", read(root / "ledger.json", {}))
    rows = [r for r in db.get("actions", []) if r.get("action_type") == "commitment"]
    by_id = {r.get("action_id"): fields(r) for r in rows}
    seeded = [s["data"] for s in scenario.get("seed", []) if s.get("operation") == "action_upsert"
              and s["data"].get("action_type") == "commitment"]
    linked = (len(rows) == len(seeded) and set(by_id) == set(lab["links"]) and all(
        _contains(by_id[k].get("priority"), keyword) if keyword else not by_id[k].get("priority")
        for k, keyword in lab["links"].items() if k in by_id))
    threats = summary.get("threats")
    threats = [r for r in threats if isinstance(r, dict)] if isinstance(threats, list) else []
    local = [t for t in tools if t.get("step") == index]
    allowed = all(_allowed(t) for t in local)
    blocked = summary.get("next_blocked") if isinstance(summary.get("next_blocked"), dict) else {}
    by = blocked.get("blocked_by")
    mail = [t for t in lines(root / "mail-calls.jsonl") if t.get("step") == index]
    return {
        "linked": linked,
        "threats_named": len(threats) == len(lab["overdue"])
                         and {r.get("action_id") for r in threats} == set(lab["overdue"])
                         and all(_contains(r.get("priority"), lab["links"][r["action_id"]])
                                 and _contains(prose, lab["links"][r["action_id"]]) for r in threats
                                 if r.get("action_id") in lab["overdue"]),
        "next_blocked": blocked.get("action_id") == lab["next_blocked"]["action_id"]
                        and (by == lab["next_blocked"]["blocked_by"]
                             or isinstance(by, list) and lab["next_blocked"]["blocked_by"] in by)
                        and all(_contains(prose, word) for word in lab.get("next_blocked_words", [])),
        "overloaded": _contains(summary.get("overloaded"), lab["overloaded"])
                      and bool(re.search(r"\b" + re.escape(lab["overloaded"]) + r"\b", prose, re.I)),
        "nothing_sent": allowed and nothing_sent(local + mail),
    }
