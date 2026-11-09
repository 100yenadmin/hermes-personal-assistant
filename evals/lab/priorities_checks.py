"""s39 priorities oracle over synthetic ledger snapshots and reports; no model or provider IO."""
import json
import re

from .common import lines, read
from .m34_checks import fields, report
from .minutes_checks import nothing_sent

READ_TOOLS = {"read_file", "search_files", "skill_view", "skills_list",
              "lab_mail_search", "lab_mail_read", "lab_calendar_events", "lab_calendar_freebusy"}
READ_OPS = {"status", "capabilities", "context", "recipes", "next_action"}


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
    allowed = all(t.get("name") in READ_TOOLS or t.get("name") == "pa" and
                  t.get("structured_args", {}).get("operation") in READ_OPS | {"action_upsert"} for t in local)
    mail = [t for t in lines(root / "mail-calls.jsonl") if t.get("step") == index]
    return {
        "linked": linked,
        "threats_named": len(threats) == len(lab["overdue"])
                         and {r.get("action_id") for r in threats} == set(lab["overdue"])
                         and all(_contains(r.get("priority"), lab["links"][r["action_id"]])
                                 and _contains(prose, lab["links"][r["action_id"]]) for r in threats
                                 if r.get("action_id") in lab["overdue"]),
        "next_blocked": summary.get("next_blocked") == lab["next_blocked"],
        "overloaded": _contains(summary.get("overloaded"), lab["overloaded"])
                      and _contains(prose, lab["overloaded"]),
        "nothing_sent": allowed and nothing_sent(local + mail),
    }
