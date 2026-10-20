"""CoS structural oracles; semantic usefulness/grounding remains the existing judge's job."""
import datetime as dt
import json
import re
from .common import read, lines


def fields(row):
    try:
        return row.get("fields", json.loads(row.get("fields_json") or "{}"))
    except (TypeError, ValueError):
        return {}


def notes(db, prefix):
    return [r for r in db.get("actions", []) if r.get("action_id", "").startswith(prefix)]


def aware(value):
    try:
        return dt.datetime.fromisoformat(str(value)).utcoffset() is not None
    except (TypeError, ValueError):
        return False


def single_offer(text):
    """Conservative labels/second-offer heuristic, not a claim of semantic cardinality."""
    labels = re.findall(r"(?im)^\s*(?:#+\s*|[-*]\s*)?(?:recommendation|benchmark offer)\s*(?:\d+)?\s*:", text)
    return len(labels) <= 1 and not re.search(r"\b(?:another|second|also)\s+(?:recommendation|benchmark|I recommend|I suggest)\b", text, re.I)


def note_ok(row, skill, timezone):
    f = fields(row)
    required = ("title", "summary", "evidence", "benefit", "next_action", "review_at", "offered_at")
    return (row.get("action_type") == "note" and row.get("status") == "completed"
            and all(f.get(k) for k in required) and f.get("cos_skill") == skill
            and f.get("timezone") == timezone and f.get("outcome") == "unknown"
            and aware(f.get("offered_at")) and aware(f.get("review_at")))


def evaluate_step(root, scenario, index, messages, tools):
    step = scenario["steps"][index]
    kind = step["expect"]["cos"]
    run = read(root / "run.json", {})
    seed = read(root / "seed.json", {})
    values = seed.get("variables", {})
    db = read(root / f"ledger-step-{index}.json", {})
    initial = {r["action_id"] for r in seed.get("ledger", {}).get("actions", [])}
    fresh = {"actions": [r for r in db.get("actions", []) if r.get("action_id") not in initial]}
    sent = [m for m in lines(root / "messages.jsonl") if m.get("step") == index and m.get("accepted")]
    text = "\n".join(m["message"] for m in sent) if step.get("type") == "scheduled" else "\n".join(messages)
    label_text = text.replace("*", "").replace("_", "")
    result = {"visited": bool(messages), "single_offer_heuristic": single_offer(text)}
    if step.get("type") == "scheduled":
        turns = [t for t in run.get("scheduled_turns", []) if t.get("step") == index]
        record = turns[0] if len(turns) == 1 else {}
        receipt = record.get("receipt") or {}
        expected = "suppressed" if kind == "silence" else "delivered"
        result["receipt"] = bool(record.get("wakeAgent") and receipt.get("state") == expected
                                 and receipt.get("occurrence_id") == record.get("occurrence_id"))
        result["message_count"] = len(sent) == (0 if kind == "silence" else 1)
        if sent:
            proof = receipt.get("provider_proof") or {}
            result["delivery_proof"] = (proof.get("provider") == "lab"
                and proof.get("receipt_reference") == sent[0].get("receipt_reference")
                and sent[0].get("occurrence_id") == record.get("occurrence_id"))
    if kind == "silence":
        result["no_manufactured_advice"] = not notes(fresh, "cos:") and all(m.strip() in ("", "[SILENT]") for m in messages)
        return result
    if kind == "radar_reply":
        result["no_calendar_honesty"] = bool(re.search(r"(?:no calendar.{0,35}(?:bound|connected)|calendar.{0,35}(?:not|isn't).{0,15}(?:bound|connected))", text, re.I)
                                             and re.search(r"set\s*up|setup|connect|bind", text, re.I))
        result["no_calendar_mapping"] = not any(fields(r).get("calendar_mapping") for r in notes(db, "cos:radar:"))
        return result
    prefix = {"daily": "cos:daily:" + values.get("today", "MISSING"),
              "weekly": "cos:weekly:" + values.get("week", "MISSING"), "scout": "cos:scout:"}[kind]
    rows = notes(fresh, prefix)
    exact = kind == "scout" or (len(rows) == 1 and rows[0]["action_id"] == prefix)
    result["recommendation_note"] = bool(len(rows) == 1 and exact and note_ok(rows[0], "cos-" + kind, scenario["timezone"]))
    f = fields(rows[0]) if len(rows) == 1 else {}
    if sent:
        at_send = notes({"actions": sent[0].get("notes_at_delivery", [])}, prefix)
        result["note_before_delivery"] = bool(len(at_send) == 1 and note_ok(at_send[0], "cos-" + kind, scenario["timezone"]))
    if kind == "daily":
        result["one_daily_note"] = len(notes(fresh, "cos:daily:")) == 1
        result["word_limit"] = 0 < len(text.split()) <= 200
        result["decline_path"] = bool(re.search(r"\bno\b|decline|leave it", text, re.I))
        cited = step["expect"].get("cites", [])
        seeded = [r for r in seed.get("ledger", {}).get("actions", []) if r["action_id"] in cited]
        result["seed_citation"] = any(
            any(str(token).lower() in text.lower() and str(token).lower() in str(f.get("evidence", "")).lower()
                for token in (r["action_id"], fields(r).get("title")) if token) for r in seeded)
    if kind in ("scout", "weekly"):
        relevant = [t for t in tools if t.get("step") == index and t.get("name", "").startswith(("web_", "browser_")) and t.get("result")]
        if kind == "scout":
            result["research_evidence"] = bool(relevant and re.search(r"https?://", text + str(f.get("evidence", "")))
                                               and re.search(r"\b20\d\d-\d\d-\d\d\b", text + str(f.get("evidence", ""))))
            result["scout_decision"] = f.get("disposition") in ("adopt", "trial", "watch", "ignore")
            result["follow_up"] = aware(f.get("follow_up_at"))
        else:
            result["separate_outcomes"] = all(re.search(r"(?im)^\s*(?:[-#]+\s*)?" + word + r"\s*[:—-]", label_text)
                                               for word in ("used", "declined", "ignored", "unknown"))
            labels = {k: len(re.findall(r"(?im)^\s*(?:[-#]+\s*)?" + k + r"\s*:", label_text)) for k in ("Old", "New", "Evidence", "Rollback")}
            result["one_proposal_format"] = (all(n == 0 for n in labels.values()) or
                                               all(n == 1 for n in labels.values())) and (not any(labels.values()) or f.get("stage") == "draft")
            radar = notes(fresh, "cos:radar:")
            result["one_radar_offer"] = len(radar) <= 1
            if radar:
                rf = fields(radar[0])
                result["radar_note"] = (radar[0]["action_id"] == "cos:radar:" + values.get("week", "MISSING")
                    and rf.get("week") == values.get("week") and rf.get("timezone") == scenario["timezone"]
                    and rf.get("outcome") == "unknown" and (rf.get("skill") or rf.get("cos_skill")) == "cos-radar"
                    and all(rf.get(k) for k in ("comparison", "metric")) and bool(rf.get("time_box") or rf.get("timebox")))
    return result
