"""s34 minutes oracle over the run's own tool log, saved files and ledger; no provider or model IO."""
import json
from pathlib import Path

from .common import read
from .m34_checks import calls, fields, report

SENDS = {"lab_mail_send", "send_message"}


def _text(value):
    return " ".join(str(value or "").casefold().split())


def _same(a, b):
    """One name is a leading part of the other: "Avery" and "Avery Demo"."""
    short, long = sorted((_text(a).split(), _text(b).split()), key=len)
    return bool(short) and long[:len(short)] == short


def _has(text, keywords):
    return all(k in _text(text) for k in keywords)


def _rows(value):
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def _matches(rows, expected, text_key):
    """Each expected item is exactly one row by its keywords, with its owner and date, and there are no extra rows."""
    rows = _rows(rows)

    def one(e):
        found = [r for r in rows if _has(r.get(text_key, ""), e["keywords"])]
        return len(found) == 1 and _same(found[0].get("owner"), e["owner"]) and str(found[0].get("due_date", ""))[:10] == e["due_date"]
    return len(rows) == len(expected) and all(one(e) for e in expected)


def _saves(local):
    out = []
    for t in calls(local, "minutes"):
        try:
            data = t["structured_args"].get("data", {})
            data = json.loads(data) if isinstance(data, str) else data
            value = t.get("result", {})
            value = json.loads(value) if isinstance(value, str) else value
            value = value.get("data", value) if isinstance(value, dict) else {}
        except (TypeError, ValueError, AttributeError):
            continue
        if (t.get("accepted") is not False and isinstance(data, dict) and data.get("action") == "save"
                and isinstance(value, dict) and "error" not in value and isinstance(value.get("loop_ids"), list)):
            out.append((data, value))
    return out


def evaluate(root, scenario, index, messages, tools):
    lab = scenario["lab"]
    hh = root / "home/.hermes"
    source = next(iter(lab["files"]))
    name = Path(source).stem
    owner, expected = lab["owner_name"], lab["expected_items"]
    local = [t for t in tools if t.get("step") == index]
    saves = _saves(local)
    saved, result = saves[-1] if saves else ({}, {})
    items = _rows(saved.get("action_items"))
    questions = [q.get("question", "") for q in _rows(saved.get("open_questions"))]
    decisions = [d.get("text", "") for d in _rows(saved.get("decisions"))]

    def resolved(value):
        if not isinstance(value, str) or not value:
            return None
        path = Path(value) if Path(value).is_absolute() else hh / value
        return path.resolve() if path.is_file() else None
    markdown = resolved(result.get("paths", {}).get("markdown") if isinstance(result.get("paths"), dict) else None)

    db = read(root / f"ledger-step-{index}.json", read(root / "ledger.json", {}))
    loops = [r for r in db.get("actions", []) if str(r.get("action_id", "")).startswith(f"minutes:{name}:")]

    def loop_ok(e):
        found = [r for r in loops if _has(fields(r).get("title", ""), e["keywords"])]
        f = fields(found[0]) if len(found) == 1 else {}
        return (len(found) == 1 and found[0].get("status") == "open" and str(f.get("due_at", ""))[:10] == e["due_date"]
                and f.get("next_actor") == ("owner" if _same(e["owner"], owner) else "them"))

    summary = report(messages[-1] if messages else "")
    told = summary.get("open_questions") if isinstance(summary.get("open_questions"), list) else []
    return {
        "ran_minutes": bool(saves) and saved.get("path") == source and saved.get("name") == name
                       and saved.get("meeting_date") == lab["meeting_date"] and _same(saved.get("owner_name"), owner)
                       and markdown is not None,
        "action_items_exact": _matches(items, expected, "text"),
        # Unowned or undated items stay questions for the owner; none of them becomes an action item.
        "open_questions_kept": all(any(_has(q, k) for q in questions) and not any(_has(i.get("text", ""), k) for i in items)
                                   for k in lab["open_questions"]),
        "decisions_right": all(any(_has(d, k) for d in decisions) for k in lab["decisions"]),
        # One open loop per action item: the owner's own is a reminder to the owner, the rest wait on them.
        "loops_recorded": len(loops) == len(expected) and all(loop_ok(e) for e in expected),
        "reported": _matches(summary.get("action_items"), expected, "action")
                    and all(any(_has(q, k) for q in told) for k in lab["open_questions"])
                    and markdown is not None and resolved(summary.get("minutes")) == markdown,
        "nothing_sent": not [t for t in local if t.get("name") in SENDS] and not calls(local, "action_confirm"),
    }
