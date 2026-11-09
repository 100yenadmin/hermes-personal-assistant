"""Owner-stated balances and read-only cash summaries; never bank access or payments."""
import csv
import datetime as dt
import io
import json
import os
import re
import unicodedata
from decimal import Decimal, localcontext

from jsonschema import Draft7Validator, FormatChecker

from .context import evaluation_moment, owner_zone
from .evidence import _date, _text
from .expenses import FIELDS as EXPENSE_FIELDS, _number, _rows, card_duplicates
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
          "export": {"type": "boolean"}}
OP_SCHEMA = {"oneOf": [
    {"type": "object", "additionalProperties": False,
     "properties": {"action": {"const": action}, **{k: FIELDS[k] for k in keys}},
     "required": ["action", *required]}
    for action, keys, required in (
        ("balance", ("account_label", "as_of", "amount", "currency", "evidence_ref"),
         ("account_label", "as_of", "amount", "currency", "evidence_ref")),
        ("cash_position", ("as_of",), ()), ("monthly", ("month", "export"), ("month",)))]}


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
    recent = [r for r in expenses if start <= r["fields"]["date"] <= as_of]
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
    expenses = [r for r in expenses if r["fields"]["date"].startswith(month + "-")]
    result = {"month": month, "currencies": {}, "possible_duplicates": []}
    for currency in sorted({r["fields"]["currency"] for r in paid + expenses}):
        incoming = [r for r in paid if r["fields"]["currency"] == currency and r["fields"]["direction"] == "receivable"]
        bills = [r for r in paid if r["fields"]["currency"] == currency and r["fields"]["direction"] == "payable"]
        spent = [r for r in expenses if r["fields"]["currency"] == currency]
        result["currencies"][currency] = {"income": _categories(incoming), "bills_paid": _categories(bills),
                                           "expenses": _categories(spent, signed=True),
                                           "net": _number(_total(incoming) - _total(bills) - _total(spent, signed=True))}
        for bill in bills:
            f = bill["fields"]
            for expense in [r for r in candidates if r["fields"]["currency"] == currency]:
                e = expense["fields"]
                if (e["kind"] == "charge" and Decimal(f["amount"]) == Decimal(e["amount"])
                        and _normalize(f["counterparty"]) == _normalize(e.get("merchant", ""))
                        and abs((dt.date.fromisoformat(f["paid_on"]) - dt.date.fromisoformat(e["date"])).days) <= 3):
                    result["possible_duplicates"].append({"invoice_id": bill["action_id"], "expense_id": expense["action_id"]})
    result["possible_duplicates"].extend(p for p in card_duplicates(candidates) if p["dates"][-1].startswith(month + "-"))
    return result, paid, expenses


def _export(ledger, summary, paid, expenses):
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
    csv_text = io.StringIO(newline="")
    writer = csv.writer(csv_text)
    writer.writerow(columns)
    writer.writerows([["'" + cell if cell.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else cell
                       for cell in row] for row in table])
    def md(text):
        return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")
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
    output = ledger.root / "exports" / "finance"
    legacy._ensure_directory(ledger.root, output)
    paths = {kind: output / ("monthly-" + summary["month"] + suffix)
             for kind, suffix in (("csv", ".csv"), ("markdown", ".md"))}
    for path in paths.values():
        legacy._validate_existing_path(ledger.root, path)
    for kind, text in (("csv", csv_text.getvalue()), ("markdown", "\n".join(lines) + "\n")):
        fd = os.open(paths[kind], os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)
    return {k: str(v) for k, v in paths.items()}


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
        result, paid, spent = _monthly(rows, expenses, data["month"])
    if data.get("export", False):
        result["export"] = _export(ledger, result, paid, spent)
    return result
