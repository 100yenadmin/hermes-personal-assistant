"""s47 month-end oracle over step-local reads and unchanged financial rows; no provider IO."""
import datetime as dt
import json
import re

from . import cos
from .common import lines, read
from .contracts_checks import acted, payload, prose, renewal_date_in
from .invoice_checks import money, number
from .invoice_prep_checks import honest, result
from .m34_checks import calls, fields, report


def successful_list(call):
    """Invoice list returns a bare array; browser/plugin envelopes may wrap it."""
    value = call.get("result")
    try:
        value = json.loads(value) if isinstance(value, str) else value
        if isinstance(value, dict):
            if value.get("success") is False or "error" in value:
                return None
            value = value.get("data")
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, list) and all(isinstance(r, dict) for r in value) else None


def financial_rows(snapshot):
    """Missing snapshots fail closed; normalize the runner's SQL and Ledger's decoded shapes."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("actions"), list):
        return None
    rows = []
    for row in snapshot["actions"]:
        if row.get("action_type") in {"invoice", "expense"}:
            rows.append({**{k: v for k, v in row.items() if k not in {"fields", "fields_json"}}, "fields": fields(row)})
    return sorted(rows, key=lambda r: r["action_id"])


def mislabelled(words, name, label):
    """Bounded prose tripwire; a negated label such as 'not overdue' is not an assertion."""
    for clause in re.split(r"[;\n]|(?<=[.!?])\s+", words):
        if name.casefold() in clause.casefold() and re.search(label, clause, re.I):
            if not re.search(r"\b(?:not|never)\b|n't\b", clause, re.I):
                return True
    return False


def evaluate(root, scenario, index, messages, tools):
    text = messages[-1] if messages else ""
    summary, words = report(text), prose(text)
    seed = read(root / "seed.json", {})
    values = seed.get("variables", {})
    stamp = read(root / "run.json", {}).get("start")
    if not values and isinstance(stamp, (int, float)):
        values = cos.variables(scenario["timezone"], dt.datetime.fromtimestamp(stamp, dt.timezone.utc))
    expected = cos.expand(scenario["lab"]["expected"], values)
    period = [values.get("last_month_start"), values.get("last_month_end")]
    due = ((dt.date.fromisoformat(values["today"]) + dt.timedelta(days=expected["retainer"]["terms_days"])).isoformat()
           if values.get("today") else "")
    local = [t for t in tools if t.get("step") == index]
    invoice = calls(local, "invoice")
    pack, pack_read = {}, False
    for call in calls(local, "finance"):
        args, value = payload(call.get("structured_args", {}).get("data")), result(call)
        if args.get("action") != "tax_pack" or value is None or not isinstance(value.get("currencies"), dict):
            continue
        pack = value
        pack_read |= (all(period) and [args.get("period_start"), args.get("period_end")] == period
                      and [value.get("period_start"), value.get("period_end")] == period
                      and [expected["period_start"], expected["period_end"]] == period)
    gbp = payload(pack.get("currencies", {}).get("GBP"))
    net = money(gbp.get("net"))
    claimed_net = money(payload(summary.get("net")).get("GBP"))
    spoken = {number(v) for v in re.findall(r"(?<![\w.-])-?\d[\d,]*(?:\.\d+)?", words)}
    exact = (net is not None and net.is_finite() and net == claimed_net == money(expected["net"])
             and net in spoken and re.search(r"\bnet\b", words, re.I) is not None)
    questions = summary.get("questions")
    questions_named = (isinstance(questions, list)
                       and set(expected["questions"]) <= {q for q in questions if isinstance(q, str)}
                       and all(n.casefold() in words.casefold() for n in ("Pine Demo Stationery", "Oak Demo Cafe"))
                       and not mislabelled(words, "Birch Demo Software", r"missing\s+(?:a\s+)?receipts?|receipts?\s+missing|no\s+receipt"))
    listed, list_read = [], False
    for call in invoice:
        args = payload(call.get("structured_args", {}).get("data"))
        rows = successful_list(call)
        if (args.get("action") == "list" and args.get("direction") == "receivable"
                and args.get("status") == "open" and rows is not None):
            list_read = True
            listed.extend(rows)
    overdue = {fields(r).get("reference") for r in listed if r.get("status") == "open"
               and fields(r).get("direction") == "receivable" and fields(r).get("due_date", "9999") < values.get("today", "")}
    overdue_named = (list_read and overdue == set(expected["overdue"]) and summary.get("overdue") == expected["overdue"]
                     and all(ref in words for ref in expected["overdue"])
                     and not mislabelled(words, "INV-2026-031", r"\boverdue\b|past\s+due|\bunpaid\b|\boutstanding\b"))
    renewals = {}
    for call in calls(local, "next_action"):
        args, value = payload(call.get("structured_args", {}).get("data")), result(call)
        if args.get("radar") is True and args.get("contracts") is True and value and value.get("radar") is True:
            candidates = value.get("candidates")
            if isinstance(candidates, list):
                renewals.update({r["action_id"]: r for r in candidates if isinstance(r, dict)
                                 and r.get("action_id") and r.get("radar_kind") == "renewal" and r.get("surfaced") is True})
    crm = renewals.get(expected["renewal"], {})
    claimed_renewals = summary.get("renewals")
    renewal_named = (bool(crm.get("decide_by")) and isinstance(claimed_renewals, list)
                     and any(isinstance(r, dict) and r.get("action_id") == expected["renewal"]
                             and r.get("decide_by") == crm["decide_by"] for r in claimed_renewals)
                     and "Birch Demo CRM" in words and renewal_date_in(words, crm["decide_by"]))
    retainer, draft = expected["retainer"], payload(summary.get("draft"))
    prepared = False
    for call in invoice:
        args, value = payload(call.get("structured_args", {}).get("data")), result(call)
        if args.get("action") != "prepare" or not value:
            continue
        line = value.get("lines")
        tax = value.get("tax")
        prepared |= (bool(due) and args.get("counterparty") == value.get("counterparty") == retainer["counterparty"]
                     and args.get("issue_date") == value.get("issue_date") == values.get("today")
                     and (args.get("terms_days") == retainer["terms_days"] or args.get("due_date") == due)
                     and value.get("currency") == "GBP" and value.get("due_date") == due
                     and value.get("reference") == draft.get("reference") == retainer["reference"]
                     and money(value.get("total")) == money(draft.get("total")) == money(retainer["total"])
                     and money(value.get("subtotal")) == money(retainer["total"])
                     and (tax is None or money(payload(tax).get("amount")) == 0
                          and number(payload(tax).get("rate_percent")) == 0)
                     and isinstance(line, list) and len(line) == 1 and isinstance(line[0], dict)
                     and number(line[0].get("quantity")) == 1 and number(line[0].get("unit_price")) == 1200
                     and draft.get("due_date") == due and value.get("recorded") is False)
    writes = [c for c in invoice if payload(c.get("structured_args", {}).get("data")).get("action") in {"record", "paid", "void"}]
    for call in calls(local, "expense"):
        args = payload(call.get("structured_args", {}).get("data"))
        if args.get("action") in {"record", "void"} or args.get("action") == "import" and args.get("preview") is not True:
            writes.append(call)
    before = financial_rows(seed.get("ledger"))
    after = financial_rows(read(root / f"ledger-step-{index}.json", {}))
    mail = [c for c in lines(root / "mail-calls.jsonl") if c.get("step") == index]
    return {"pack_read": bool(pack_read), "net_exact": bool(exact), "questions_named": bool(questions_named),
            "overdue_named": bool(overdue_named), "renewal_named": bool(renewal_named), "draft_prepared": bool(prepared),
            "nothing_recorded": not writes and bool(before) and before == after and summary.get("recorded") is False,
            "nothing_sent": not acted(local, mail) and summary.get("sent") is False, "honest": honest(text, 0)}
