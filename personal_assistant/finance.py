"""Owner-stated balances and read-only cash summaries; never bank access or payments."""
import datetime as dt
import json
import os
import re
import unicodedata
from decimal import Decimal, localcontext

from jsonschema import Draft7Validator, FormatChecker

from .context import evaluation_moment, owner_zone
from .evidence import _date, _text
from .expenses import FIELDS as EXPENSE_FIELDS, _csv_text, _md, _merchant, _number, _rows, card_duplicates
from .privacy import clean
from .invoices import _iban
from .profile import _private
from .state import legacy, now, stable_id

FIELDS = {"account_label": {"type": "string", "minLength": 1, "maxLength": 60},
          "as_of": {"type": "string", "format": "date"},
          "amount": {"type": "string", "pattern": r"^-?[0-9]+(?:\.[0-9]{1,3})?$"},
          "currency": EXPENSE_FIELDS["currency"],
          "evidence_ref": {"type": "string", "minLength": 1, "maxLength": 1000},
          "month": {"type": "string", "pattern": r"^[0-9]{4}-(0[1-9]|1[0-2])$"},
          **{k: {"type": "string", "format": "date"} for k in ("period_start", "period_end")},
          "export": {"type": "boolean"}}
OP_SCHEMA = {"oneOf": [
    {"type": "object", "additionalProperties": False,
     "properties": {"action": {"const": action}, **{k: FIELDS[k] for k in keys}},
     "required": ["action", *required]}
    for action, keys, required in (
        ("balance", ("account_label", "as_of", "amount", "currency", "evidence_ref"),
         ("account_label", "as_of", "amount", "currency", "evidence_ref")),
        ("cash_position", ("as_of",), ()), ("monthly", ("month", "export"), ("month",)),
        ("tax_pack", ("period_start", "period_end", "export"), ("period_start", "period_end")))]}


def _normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _validate(data):
    if not Draft7Validator(OP_SCHEMA, format_checker=FormatChecker()).is_valid(data):
        raise ValueError("invalid finance action or fields")
    for key, limit in (("account_label", 60), ("evidence_ref", 1000)):
        if key in data:
            _text(data[key], "finance." + key, limit)
            if _private(data[key]) or _iban(data[key]):
                raise ValueError("PA does not store payment or account numbers or credentials")
            if re.search(r"\d{%d,}" % (6 if key == "account_label" else 8), data[key]):
                raise ValueError("PA does not store account numbers")
    if "as_of" in data:
        _date(data["as_of"], "finance.as_of")
    if data["action"] == "tax_pack":
        start, end = (dt.date.fromisoformat(_date(data[k], "finance." + k))
                      for k in ("period_start", "period_end"))
        if end < start:
            raise ValueError("finance.period_end must be on or after period_start")
        if (end - start).days >= 366:
            raise ValueError("a tax pack covers at most 366 days")
    if clean(data) != data:
        raise ValueError("finance text must not contain restricted details")


def _balance(ledger, data):
    fields = {k: v for k, v in data.items() if k != "action"}
    amount = Decimal(fields["amount"])
    fields["amount"] = _number(amount if amount else Decimal(0))
    identity = "balance:" + stable_id("balance", _normalize(fields["account_label"]), fields["as_of"])
    with ledger.connect() as conn:
        conn.execute("begin immediate")
        old = conn.execute("select * from actions where action_id=?", (identity,)).fetchone()
        old = legacy.row_to_dict(old) if old else None
        if old:
            previous = old["fields"]
            if Decimal(previous["amount"]) == amount and previous["currency"] == fields["currency"]:
                return old
            fields["previous"] = {k: previous[k] for k in ("amount", "currency", "evidence_ref")}
        stamp = now()
        conn.execute("insert into actions values(?,?,?,?,?,?,?,?) on conflict(action_id) do update set "
                     "action_type=excluded.action_type,status=excluded.status,"
                     "fields_json=excluded.fields_json,updated_at=excluded.updated_at",
                     (identity, None, "balance", "", "recorded", json.dumps(fields, ensure_ascii=False),
                      (old or {}).get("created_at", stamp), stamp))
    return ledger.get("action", identity)


def _total(rows, *, signed=False):
    return sum((Decimal(r["fields"]["amount"]) *
                (-1 if signed and r["fields"]["kind"] == "refund" else 1) for r in rows), Decimal(0))


def _bucket(rows):
    return {"invoices": [{"invoice_id": r["action_id"], **{k: r["fields"][k]
                         for k in ("amount", "counterparty", "due_date")}} for r in rows],
            "total": _number(_total(rows))}


def _cash_position(rows, expenses, as_of):
    day = dt.date.fromisoformat(as_of)
    end = (day + dt.timedelta(days=7)).isoformat()
    start = (day - dt.timedelta(days=6)).isoformat()
    latest = {}
    for row in sorted(rows, key=lambda r: (r["fields"].get("as_of", ""), r["action_id"])):
        if row["action_type"] == "balance" and row["fields"]["as_of"] <= as_of:
            # One account label can hold several currencies; each keeps its own latest balance.
            latest[(_normalize(row["fields"]["account_label"]), row["fields"]["currency"])] = row
    balances = list(latest.values())
    # Every open invoice counts (an early-dated bill is still owed). A paid one counts when it was
    # issued by as_of and paid after it. Void rows carry no date and stay out.
    invoices = [r for r in rows if r["action_type"] == "invoice" and (r["status"] == "open" or (
        r["status"] == "paid" and r["fields"]["issue_date"] <= as_of < r["fields"]["paid_on"]))]
    # A receipt matched to a card line is that purchase, counted once on the line's date, as in the tax pack.
    suppressed = set(_receipt_matches(expenses).values())
    recent = [r for r in expenses if start <= r["fields"]["date"] <= as_of and r["action_id"] not in suppressed]
    currencies = sorted({r["fields"]["currency"] for r in balances + invoices + recent})
    result = {"as_of": as_of, "currencies": {}, "gaps": []}
    for currency in currencies:
        held = [r for r in balances if r["fields"]["currency"] == currency]
        spent = [r for r in recent if r["fields"]["currency"] == currency]
        view = {"balances": [{**r, "age_days": (day - dt.date.fromisoformat(r["fields"]["as_of"])).days}
                             for r in held]}
        for direction, key in (("receivable", "receivables"), ("payable", "payables")):
            selected = sorted([r for r in invoices if r["fields"]["currency"] == currency
                               and r["fields"]["direction"] == direction],
                              key=lambda r: (r["fields"]["due_date"], r["action_id"]))
            view[key] = {"overdue": _bucket([r for r in selected if r["fields"]["due_date"] < as_of]),
                         "due_7d": _bucket([r for r in selected if as_of <= r["fields"]["due_date"] <= end])}
        view["spent_7d"] = {"charges": _number(_total([r for r in spent if r["fields"]["kind"] == "charge"])),
                            "refunds": _number(_total([r for r in spent if r["fields"]["kind"] == "refund"])),
                            "net": _number(_total(spent, signed=True))}
        if held:
            projected = (_total(held) + Decimal(view["receivables"]["due_7d"]["total"])
                         - Decimal(view["payables"]["due_7d"]["total"])
                         - Decimal(view["payables"]["overdue"]["total"]))
            view["projected_7d"] = {"basis": "projection", "amount": _number(projected)}
        else:
            result["gaps"].append({"currency": currency, "reason": "no_balance"})
        for balance in view["balances"]:
            if balance["age_days"] > 7:
                result["gaps"].append({"currency": currency, "account_label": balance["fields"]["account_label"],
                                       "reason": "stale_balance", "age_days": balance["age_days"]})
        result["currencies"][currency] = view
    return result


def _categories(rows, *, signed=False):
    categories = {}
    for row in rows:
        category = row["fields"]["category"]
        categories[category] = categories.get(category, Decimal(0)) + _total([row], signed=signed)
    return {"by_category": {k: _number(v) for k, v in sorted(categories.items())},
            "total": _number(_total(rows, signed=signed))}


def _monthly(rows, expenses, month):
    paid = [r for r in rows if r["action_type"] == "invoice" and r["status"] == "paid"
            and r["fields"]["paid_on"].startswith(month + "-")]
    candidates = expenses  # A duplicate may straddle the month boundary; it is listed in the bill's month.
    # A receipt matched to a card line is that purchase: it counts once, on the line's date, and the pair is
    # not a possible duplicate. The tax pack matches the same way, so twelve months add up to its year.
    matches = _receipt_matches(candidates)
    suppressed = set(matches.values())
    matched_pairs = {frozenset(pair) for pair in matches.items()}
    expenses = [r for r in expenses if r["fields"]["date"].startswith(month + "-") and r["action_id"] not in suppressed]
    result = {"month": month, "currencies": {}, "possible_duplicates": []}
    for currency in sorted({r["fields"]["currency"] for r in paid + expenses}):
        incoming = [r for r in paid if r["fields"]["currency"] == currency and r["fields"]["direction"] == "receivable"]
        bills = [r for r in paid if r["fields"]["currency"] == currency and r["fields"]["direction"] == "payable"]
        spent = [r for r in expenses if r["fields"]["currency"] == currency]
        result["currencies"][currency] = {"income": _categories(incoming), "bills_paid": _categories(bills),
                                           "expenses": _categories(spent, signed=True),
                                           "net": _number(_total(incoming) - _total(bills) - _total(spent, signed=True))}
        result["possible_duplicates"].extend(_bill_duplicates(bills, candidates))
    result["possible_duplicates"].extend(p for p in card_duplicates(candidates) if p["dates"][-1].startswith(month + "-")
                                         and frozenset(p["expense_ids"]) not in matched_pairs)
    return result, paid, expenses, sum(r["action_id"] in matches for r in expenses)


def _bill_duplicates(bills, expenses):
    result = []
    for bill in bills:
        f = bill["fields"]
        for expense in expenses:
            e = expense["fields"]
            if (e["currency"] == f["currency"] and e["kind"] == "charge"
                    and Decimal(f["amount"]) == Decimal(e["amount"])
                    and _normalize(f["counterparty"]) == _normalize(e.get("merchant", ""))
                    and abs((dt.date.fromisoformat(f["paid_on"]) - dt.date.fromisoformat(e["date"])).days) <= 3):
                result.append({"invoice_id": bill["action_id"], "expense_id": expense["action_id"]})
    return result


def _receipt_matches(expenses):
    """Pair each forwarded receipt with at most one card-statement line for the same purchase.

    Matching ignores the period, so every pack pairs the same records and adjacent packs add up.
    Within one merchant, amount, currency and kind it makes as many pairs as possible (an unmatched
    receipt counts as a separate purchase); among those it prefers the closest dates.
    """
    groups, matched = {}, {}
    for row in expenses:
        f = row["fields"]
        merchant = _merchant(f.get("merchant", ""))
        if merchant:
            groups.setdefault((merchant, Decimal(f["amount"]), f["currency"], f["kind"]), []).append(row)
    def day(row):
        return dt.date.fromisoformat(row["fields"]["date"])
    def order(row):
        return (row["fields"]["date"], row["action_id"])
    for group in groups.values():
        statements = sorted((r for r in group if r["fields"]["evidence_ref"].startswith("statement ")), key=order)
        receipts = sorted((r for r in group if not r["fields"]["evidence_ref"].startswith("statement ")), key=order)
        # Closest dates first, ties by statement date and ids.
        candidates = sorted((abs((day(s) - day(r)).days), order(s), s["action_id"], r["action_id"])
                            for s in statements for r in receipts if abs((day(s) - day(r)).days) <= 3)
        closest, taken = {}, set()
        for _, _, statement, receipt in candidates:
            if statement not in taken and receipt not in taken:
                closest[statement] = receipt
                taken.update((statement, receipt))
        # Every window is the same 7 days, so giving each statement, in date order, the earliest free
        # receipt in its window makes the most pairs. Keep the closest pairing only if it is as large.
        most, used = {}, set()
        for statement in statements:
            for receipt in receipts:
                gap = (day(receipt) - day(statement)).days
                if gap > 3:
                    break
                if gap >= -3 and receipt["action_id"] not in used:
                    most[statement["action_id"]] = receipt["action_id"]
                    used.add(receipt["action_id"])
                    break
        matched.update(closest if len(closest) == len(most) else most)
    return matched


def _counterparties(rows):
    totals, spellings = {}, {}
    for row in rows:
        party = row["fields"]["counterparty"]
        key = _normalize(party)
        spellings.setdefault(key, party)
        totals[key] = totals.get(key, Decimal(0)) + Decimal(row["fields"]["amount"])
    return {spellings[k]: _number(v) for k, v in sorted(totals.items())}


def _tax_pack(rows, expenses, start, end):
    invoices = [r for r in rows if r["action_type"] == "invoice" and r["status"] != "void"]
    paid = [r for r in invoices if r["status"] == "paid" and start <= r["fields"]["paid_on"] <= end]
    opened = sorted([r for r in invoices if r["fields"]["issue_date"] <= end and (
        r["status"] == "open" or r["status"] == "paid" and r["fields"]["paid_on"] > end)],
        key=lambda r: (r["fields"]["due_date"], r["action_id"]))
    matches = _receipt_matches(expenses)
    by_id = {r["action_id"]: r for r in expenses + invoices}
    # A matched purchase counts once, on its statement line's date: a receipt on the other side of a
    # period boundary never counts on its own, so consecutive packs never count it twice.
    suppressed = set(matches.values())
    spent = [r for r in expenses if start <= r["fields"]["date"] <= end and r["action_id"] not in suppressed]
    matched_pairs = {frozenset(pair) for pair in matches.items()}
    duplicates = _bill_duplicates([r for r in paid if r["fields"]["direction"] == "payable"], expenses)
    duplicates.extend(p for p in card_duplicates(expenses) if any(start <= d <= end for d in p["dates"])
                      and frozenset(p["expense_ids"]) not in matched_pairs)
    result = {"period_start": start, "period_end": end, "currencies": {}, "possible_duplicates": duplicates,
              "questions": [], "basis": "ledger records only; no currency conversion; not tax advice"}
    for pair in duplicates:
        facts = pair
        if "invoice_id" in pair:
            bill, expense = (by_id[pair[k]]["fields"] for k in ("invoice_id", "expense_id"))
            facts = {**pair, "merchant": bill["counterparty"], "amount": bill["amount"],
                     "currency": bill["currency"], "dates": [bill["paid_on"], expense["date"]]}
        result["questions"].append({"kind": "possible_duplicate", **facts})
    for currency in sorted({r["fields"]["currency"] for r in paid + spent + opened}):
        incoming, bills = ([r for r in paid if r["fields"]["currency"] == currency and r["fields"]["direction"] == d]
                           for d in ("receivable", "payable"))
        selected = [r for r in spent if r["fields"]["currency"] == currency]
        missing = [r for r in selected if r["fields"]["evidence_ref"].startswith("statement ")
                   and r["fields"]["kind"] == "charge" and r["action_id"] not in matches]
        view = {"income": {**_categories(incoming), "by_counterparty": _counterparties(incoming)},
                "bills_paid": {**_categories(bills), "by_counterparty": _counterparties(bills)},
                "expenses": _categories(selected, signed=True),
                "net": _number(_total(incoming) - _total(bills) - _total(selected, signed=True)),
                "open_at_end": {}, "receipts_missing": {"count": len(missing), "total": _number(_total(missing)),
                    "lines": [{"expense_id": r["action_id"], **{k: r["fields"].get(k, "")
                               for k in ("date", "merchant", "amount")}} for r in missing[:50]],
                    "more": max(0, len(missing) - 50)},
                "matched_receipts": sum(r["action_id"] in matches for r in selected)}
        other = [r for r in selected if r["fields"]["category"] == "other"]
        for kind, group in (("uncategorised", other), ("receipts_missing", missing)):
            if group:
                result["questions"].append({"kind": kind, "currency": currency, "count": len(group),
                                            "total": _number(_total(group, signed=kind == "uncategorised"))})
        for direction, key in (("receivable", "receivables"), ("payable", "payables")):
            group = [r for r in opened if r["fields"]["currency"] == currency and r["fields"]["direction"] == direction]
            view["open_at_end"][key] = _bucket(group)
            if group:
                result["questions"].append({"kind": "unpaid_at_end", "currency": currency,
                                            "direction": direction, "count": len(group), "total": _number(_total(group))})
        result["currencies"][currency] = view
    if len(result["currencies"]) > 1:
        result["questions"].append({"kind": "several_currencies", "currencies": list(result["currencies"]),
                                    "message": "totals are per currency and not converted"})
    kinds = ["possible_duplicate", "uncategorised", "receipts_missing", "unpaid_at_end", "several_currencies"]
    result["questions"].sort(key=lambda q: (kinds.index(q["kind"]), q.get("currency", ""),
        q.get("invoice_id", ""), q.get("expense_id", ""), q.get("expense_ids", []), q.get("direction", "")))
    return result, paid, spent, opened, matches, by_id


def _export(ledger, summary, paid, expenses, matched=0):
    columns = "date kind category amount currency counterparty evidence_ref record_id".split()
    table = []
    for row in sorted(paid + expenses, key=lambda r: r["action_id"]):
        f = row["fields"]
        invoice = row["action_type"] == "invoice"
        values = {**f, "date": f["paid_on"] if invoice else f["date"],
                  "kind": f["direction"] if invoice else f["kind"],
                  "counterparty": f["counterparty"] if invoice else f.get("merchant", ""),
                  "record_id": row["action_id"]}
        table.append([str(values.get(k, "")) for k in columns])
    # Summary rows make the exported totals match the view, while detail rows retain source identities.
    for currency, view in summary["currencies"].items():
        for kind in ("income", "bills_paid", "expenses"):
            table.extend(["", kind + "_category", category, amount, currency, "", "", ""]
                         for category, amount in view[kind]["by_category"].items())
            table.append(["", kind + "_total", "", view[kind]["total"], currency, "", "", ""])
        table.append(["", "net", "", view["net"], currency, "", "", ""])
    md = _md
    lines = [f"# {summary['month']} — monthly finance", "", "| " + " | ".join(columns) + " |",
             "| " + " | ".join(["---"] * len(columns)) + " |"]
    lines.extend("| " + " | ".join(md(cell) for cell in row) + " |" for row in table)
    lines += ["", "## Possible duplicates (listed, never merged)"]
    for pair in summary["possible_duplicates"]:
        if "invoice_id" in pair:
            lines.append(f"- {md(pair['invoice_id'])} / {md(pair['expense_id'])}")
        else:
            lines.append("- " + md(f"{pair['merchant']}: {pair['amount']} {pair['currency']}; "
                                  f"{', '.join(pair['dates'])}; {', '.join(pair['expense_ids'])}"))
    if matched:
        lines += ["", f"Receipts matched to card lines: {matched}. A receipt within 3 days of a card line for the same "
                  "merchant and amount is taken as that purchase's receipt and counted once, on the card line's date. "
                  "If one was a separate cash purchase, tell the owner."]
    return _write_export(ledger, "monthly-" + summary["month"], columns, table, lines)


def _write_export(ledger, name, columns, table, lines):
    output = ledger.root / "exports" / "finance"
    legacy._ensure_directory(ledger.root, output)
    paths = {kind: output / (name + suffix)
             for kind, suffix in (("csv", ".csv"), ("markdown", ".md"))}
    for path in paths.values():
        legacy._validate_existing_path(ledger.root, path)
    for kind, text in (("csv", _csv_text(columns, table)), ("markdown", "\n".join(lines) + "\n")):
        fd = os.open(paths[kind], os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)
    return {k: str(v) for k, v in paths.items()}


def _text_md(text):
    """Markdown-escape record text for a file the accountant opens: no live links or emphasis from merchant names."""
    return re.sub(r"([\[\]()*_`#!~])", r"\\\1", _md(str(text)))


def _question_text(q):
    kind = q["kind"]
    if kind == "possible_duplicate":
        ids = q.get("expense_ids") or [q["invoice_id"], q["expense_id"]]
        text = (f"Possible duplicate: {q['merchant']}, {q['amount']} {q['currency']} on "
                f"{' and '.join(q['dates'])} ({', '.join(ids)}).")
    elif kind == "uncategorised":
        text = f"{q['count']} {q['currency']} expenses are in category other, total {q['total']}: which category?"
    elif kind == "receipts_missing":
        text = f"{q['count']} {q['currency']} card lines have no receipt, total {q['total']}."
    elif kind == "unpaid_at_end":
        text = f"{q['count']} {q['direction']} invoices in {q['currency']} were unpaid at the end, total {q['total']}."
    else:
        text = f"Several currencies ({', '.join(q['currencies'])}): totals are per currency and not converted."
    return _text_md(text)


def _export_tax_pack(ledger, summary, paid, spent, opened, matches, by_id):
    columns = "section date kind category amount currency counterparty evidence_ref record_id receipt".split()
    table = []
    for section, rows in (("income", [r for r in paid if r["fields"]["direction"] == "receivable"]),
                          ("bills_paid", [r for r in paid if r["fields"]["direction"] == "payable"]),
                          ("expenses", spent), ("open_at_end", opened)):
        for row in sorted(rows, key=lambda r: r["action_id"]):
            f, identity = row["fields"], row["action_id"]
            invoice = row["action_type"] == "invoice"
            receipt = ""
            if not invoice and f["evidence_ref"].startswith("statement "):
                receipt = ("matched:" + by_id[matches[identity]]["fields"]["evidence_ref"] if identity in matches
                           else "missing" if f["kind"] == "charge" else "")
            values = {**f, "section": section, "date": f["issue_date"] if section == "open_at_end" else
                      f["paid_on"] if invoice else f["date"], "kind": f["direction"] if invoice else f["kind"],
                      "counterparty": f["counterparty"] if invoice else f.get("merchant", ""),
                      "record_id": identity, "receipt": receipt}
            table.append([str(values.get(k, "")) for k in columns])
    lines = [f"# Tax pack {summary['period_start']} to {summary['period_end']}"]
    for currency, view in summary["currencies"].items():
        lines += ["", "## " + currency]
        for kind in ("income", "bills_paid", "expenses"):
            lines += ["", "### " + kind.replace("_", " ").capitalize()]
            for category, amount in view[kind]["by_category"].items():
                lines.append(f"- {_text_md(category)}: {amount}")
                table.append(["summary", "", kind + "_category", category, amount, currency, "", "", "", ""])
            lines.append("- Total: " + view[kind]["total"])
            table.append(["summary", "", kind + "_total", "", view[kind]["total"], currency, "", "", "", ""])
            if view[kind].get("by_counterparty"):
                lines.append("- By counterparty:")
                lines.extend(f"  - {_text_md(party)}: {amount}" for party, amount in view[kind]["by_counterparty"].items())
        lines += ["", "Net: " + view["net"], "", "### Open at the end"]
        table.append(["summary", "", "net", "", view["net"], currency, "", "", "", ""])
        for direction, bucket in view["open_at_end"].items():
            lines.append(f"- {direction}: {bucket['total']}")
            for invoice in bucket["invoices"]:
                lines.append("  - " + _text_md(f"{invoice['counterparty']}, {invoice['amount']}, due "
                                               f"{invoice['due_date']} ({invoice['invoice_id']})"))
        missing = view["receipts_missing"]
        lines += ["", "### Receipts missing", "",
                  f"{missing['count']} card lines have no receipt, total {missing['total']}."]
        if missing["lines"]:
            lines += ["", "| Date | Merchant | Amount | Record |", "| --- | --- | --- | --- |"]
            lines.extend("| " + " | ".join(_text_md(line[k]) for k in ("date", "merchant", "amount", "expense_id")) + " |"
                         for line in missing["lines"])
        if missing["more"]:
            lines.append(f"\n{missing['more']} more are in the CSV.")
        lines += ["", f"Receipts matched to card lines: {view['matched_receipts']}. A receipt within 3 days of a card "
                  "line for the same merchant and amount is taken as that purchase's receipt and counted once, on the "
                  "card line's date; the CSV's receipt column names each match. If one was a separate cash purchase, "
                  "tell the owner."]
    duplicates = [q for q in summary["questions"] if q["kind"] == "possible_duplicate"]
    lines += ["", "## Possible duplicates (listed, never merged)", ""]
    lines.extend("- " + _question_text(q) for q in duplicates)
    if not duplicates:
        lines.append("None found.")
    lines += ["", "## Questions", ""]
    lines.extend("- " + _question_text(q) for q in summary["questions"] if q["kind"] != "possible_duplicate")
    if duplicates:
        lines.append("- Check each possible duplicate above.")
    lines += ["", summary["basis"].capitalize() + "."]
    return _write_export(ledger, f"tax-pack-{summary['period_start']}_{summary['period_end']}", columns, table, lines)


def dispatch(ledger, data):
    _validate(data)
    action = data["action"]
    today = evaluation_moment({}).astimezone(owner_zone(ledger)).date().isoformat()
    if action == "balance":
        if data["as_of"] > today:
            raise ValueError("finance.as_of must not be after owner-local today")
        return _balance(ledger, data)
    # Only finance rows: other commitments may carry arbitrary fields such as a numeric amount.
    rows = [r for r in ledger.list("action") if r["action_type"] in ("balance", "invoice")]
    expenses = _rows(ledger)
    with localcontext() as ctx:
        ctx.prec = max(28, sum(len(r["fields"]["amount"]) for r in rows + expenses) + 3)
        if action == "cash_position":
            return _cash_position(rows, expenses, data.get("as_of", today))
        if action == "tax_pack":
            result, *details = _tax_pack(rows, expenses, data["period_start"], data["period_end"])
            if data.get("export", False):
                result["export"] = _export_tax_pack(ledger, result, *details)
            return result
        result, paid, spent, matched = _monthly(rows, expenses, data["month"])
    if data.get("export", False):
        result["export"] = _export(ledger, result, paid, spent, matched)
    return result
