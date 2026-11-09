"""Private bookkeeping from verified totals; never payment instructions."""
import csv
import datetime as dt
import io
import json
import os
import re
import unicodedata
from decimal import Decimal, localcontext
from pathlib import Path

from jsonschema import Draft7Validator

from .evidence import _date, _enum, _text
from .profile import _private
from .privacy import clean
from .state import legacy, now, stable_id

CATEGORIES = ["lodging", "transport", "food", "activity", "shopping", "services", "fees", "other"]
FIELDS = {
    "amount": {"type": "string", "pattern": r"^[0-9]+(?:\.[0-9]{1,3})?$"},
    "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
    "category": {"enum": CATEGORIES}, "kind": {"enum": ["charge", "refund"]},
    "date": {"type": "string", "format": "date"},
    "merchant": {"type": "string", "maxLength": 120},
    "description": {"type": "string", "maxLength": 200}, "evidence_ref": {"type": "string", "minLength": 1},
}
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["amount", "currency", "category"], "properties": FIELDS}
OP_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["action"], "properties": {
    **FIELDS, "expense": SCHEMA, "action": {"enum": ["record", "void", "list", "export"]},
    **{k: {"type": "string", "minLength": 1} for k in ("trip_id", "source_action_id", "expense_id")},
    "reason": {"type": "string", "maxLength": 200}, "include_void": {"type": "boolean"},
}, "allOf": [
    {"if": {"properties": {"action": {"const": "record"}}}, "then": {"anyOf": [
        {"required": ["amount", "currency", "category", "date", "evidence_ref"]},
        {"required": ["expense"], "properties": {"expense": {"required": ["date", "evidence_ref"]}}}]}},
    {"if": {"properties": {"action": {"const": "void"}}}, "then": {"required": ["expense_id", "reason"]}},
    {"if": {"properties": {"action": {"const": "export"}}}, "then": {"required": ["trip_id"]}},
]}
IMPORT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["action", "path"],
                 "properties": {"action": {"const": "import"}, "path": {"type": "string", "minLength": 1},
                                "currency": FIELDS["currency"], "preview": {"type": "boolean"},
                                "name": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{0,40}$"},
                                "categories": {"type": "array", "items": {
                                    "type": "object", "additionalProperties": False, "required": ["line", "category"],
                                    "properties": {"line": {"type": "integer", "minimum": 1},
                                                   "category": FIELDS["category"]}}}},
                 "if": {"required": ["preview"], "properties": {"preview": {"const": True}}},
                 "then": {"not": {"required": ["categories"]}}, "else": {"required": ["categories"]}}
OP_SCHEMA = {"anyOf": [OP_SCHEMA, IMPORT_SCHEMA]}


def _safe(value):
    if _private(value):
        raise ValueError("expense records prohibit credentials and card/account numbers")


def _number(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def validate(value):
    if not isinstance(value, dict) or set(value) - FIELDS.keys():
        raise ValueError("expense must be an object with known fields")
    _safe(value)
    amount = value.get("amount")
    if not isinstance(amount, str) or not re.fullmatch(FIELDS["amount"]["pattern"], amount) or Decimal(amount) <= 0:
        raise ValueError("expense.amount must be a positive decimal string with at most 3 decimal places")
    currency = value.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("expense.currency must be an ISO 4217 code")
    result = {**value, "amount": _number(Decimal(amount)), "currency": currency,
              "category": _enum(value.get("category"), "expense.category", CATEGORIES),
              "kind": _enum(value.get("kind", "charge"), "expense.kind", ["charge", "refund"])}
    for key, limit in (("merchant", 120), ("description", 200), ("evidence_ref", None)):
        if key in value:
            if limit is None:
                if not isinstance(value[key], str) or not value[key].strip():
                    raise ValueError("expense.evidence_ref must be nonempty text")
            else:
                _text(value[key], "expense." + key, limit, allow_empty=True)
    if "date" in value:
        _date(value["date"], "expense.date")
    return result


def from_readback(value, item, identity, verified_at, trip_id):
    # Only the supplied expense is scanned: ids and the provider proof are not expense text.
    fields = validate(value)
    moment = dt.datetime.fromisoformat(item["start"]) if item else dt.datetime.fromisoformat(verified_at)
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(item["timezone"]) if item else dt.timezone.utc
    fields.setdefault("date", moment.astimezone(zone).date().isoformat())
    fields.setdefault("evidence_ref", identity)
    return fields


def save(ledger, identity, fields, source, source_action_id=None, trip_id=None, *, conn=None):
    fields = {**fields, "source": source}
    if source_action_id is not None:
        fields["source_action_id"] = source_action_id
    if trip_id is not None:
        fields["trip_ref"] = trip_id
    if conn is None:
        old = ledger.get("action", identity)
    else:
        old = conn.execute("select * from actions where action_id=?", (identity,)).fetchone()
        old = legacy.row_to_dict(old) if old else None
    # A voided readback stays void unless the money changed (its default date moves with verified_at).
    # A voided receipt recorded again with a changed amount, currency, kind, date or merchant is a correction.
    money = ("amount", "currency", "kind") + (("date",) if source == "owner_receipt" else ())
    if source == "statement":
        money += ("date", "merchant")
    if source == "owner_receipt" and old and old["fields"].get("merchant") and fields.get("merchant"):
        money += ("merchant",)
    keep = old and old["status"] == "void" and all(old["fields"].get(k) == fields.get(k) for k in money)
    remove = [k for k in (*FIELDS, "trip_ref", "source_action_id", "void_reason")
              if k not in fields and not (keep and k == "void_reason")]
    status = "void" if keep else "recorded"
    if conn is None:
        return ledger.put("action", identity, fields, action_type="expense", status=status, remove=remove)
    # Statement batches own this transaction; do not commit individual rows.
    fields = {**(old or {}).get("fields", {}), **clean(fields)}
    for key in remove:
        fields.pop(key, None)
    stamp = now()
    conn.execute("insert into actions values(?,?,?,?,?,?,?,?) on conflict(action_id) do update set "
                 "action_type=excluded.action_type,status=excluded.status,"
                 "fields_json=excluded.fields_json,updated_at=excluded.updated_at",
                 (identity, None, "expense", "", status, json.dumps(fields, ensure_ascii=False),
                  (old or {}).get("created_at", stamp), stamp))
    return legacy.row_to_dict(conn.execute("select * from actions where action_id=?", (identity,)).fetchone())


def _rows(ledger, trip_id=None, include_void=False):
    return sorted([r for r in ledger.list("action") if r["action_type"] == "expense"
                   and (include_void or r["status"] != "void")
                   and (trip_id is None or r["fields"].get("trip_ref") == trip_id)],
                  key=lambda r: (r["fields"]["date"], r["action_id"]))


def _csv_text(columns, table):
    text = io.StringIO(newline="")
    writer = csv.writer(text)
    writer.writerow(columns)
    writer.writerows([["'" + cell if isinstance(cell, str) and cell.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else cell
                       for cell in row] for row in table])
    return text.getvalue()


def _md(text):
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def _merchant(text):
    text = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    return re.sub(r"(?:\s*(?:#[0-9]+|\*(?=[a-z0-9]*[0-9])[a-z0-9]+))+$", "", text).strip()


def card_duplicates(rows):
    """Pure, deterministic charge pairs across sources; a matching later refund resolves the pair."""
    groups, result = {}, []
    for row in rows:
        if row["action_type"] != "expense" or row["status"] == "void":
            continue
        f = row["fields"]
        merchant = _merchant(f.get("merchant", ""))
        if merchant:
            groups.setdefault((merchant, Decimal(f["amount"]), f["currency"]), []).append(row)
    for (merchant, amount, currency), group in sorted(groups.items()):
        charges = sorted([r for r in group if r["fields"]["kind"] == "charge"],
                         key=lambda r: (r["fields"]["date"], r["action_id"]))
        refunds = [r["fields"]["date"] for r in group if r["fields"]["kind"] == "refund"]
        for i, first in enumerate(charges):
            early = first["fields"]["date"]
            if any(date >= early for date in refunds):
                continue
            for second in charges[i + 1:]:
                late = second["fields"]["date"]
                if (dt.date.fromisoformat(late) - dt.date.fromisoformat(early)).days > 3:
                    break
                result.append({"expense_ids": [first["action_id"], second["action_id"]], "merchant": merchant,
                               "amount": _number(amount), "currency": currency, "dates": [early, late]})
    return result


def _statement_lines(root, data, rel):
    from .minutes import _read, LIMIT
    text = _read(root, rel, label="statement")
    previous = csv.field_size_limit(LIMIT)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        table = list(reader)
    except csv.Error as exc:
        raise ValueError(f"malformed statement CSV at line {reader.line_num}: {exc}") from exc
    finally:
        csv.field_size_limit(previous)
    _safe(table)  # Scan every cell, including headers, ignored columns and skipped rows; never join cells.
    headers = [h.strip().casefold() for h in table[0]] if table else []
    headers = ["date" if h == "txn date" else h for h in headers]
    if not headers or len(set(headers)) != len(headers):
        raise ValueError("missing or duplicate statement CSV headers")
    if not {"date", "amount"} <= set(headers) or not {"merchant", "description"} & set(headers):
        raise ValueError("statement requires date, merchant or description, and amount columns")
    if "currency" not in headers and "currency" not in data:
        raise ValueError("statement requires currency column or request currency")
    lines, skipped = [], []
    for number, raw in enumerate(table[1:], 1):
        try:
            if len(raw) != len(headers):
                raise ValueError("inconsistent CSV row width")
            row = dict(zip(headers, raw))
            amount = row["amount"].strip()
            kind = "refund" if amount.startswith("-") or any(row.get(k, "").strip().casefold() in ("refund", "credit")
                                                            for k in ("type", "kind")) else "charge"
            date = row["date"].strip()
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
                raise ValueError("date must be YYYY-MM-DD")
            merchant = row.get("merchant", "").strip() or row.get("description", "").strip()
            if not merchant:
                raise ValueError("merchant or description is required")
            fields = validate({"date": date, "merchant": merchant, "amount": amount[1:] if amount.startswith("-") else amount,
                               "currency": row.get("currency", data.get("currency", "")).strip(),
                               "kind": kind, "category": "other"})
            lines.append({"line": number, **{k: v for k, v in fields.items() if k != "category"}})
        except ValueError as exc:
            skipped.append({"line": number, "reason": str(exc)})
    return lines, skipped


def _import_statement(ledger, data):
    if not Draft7Validator(IMPORT_SCHEMA).is_valid(data):
        raise ValueError("invalid statement import path, preview or categories")
    relative = Path(data["path"])
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 3 or relative.parts[:2] != ("imports", "statements"):
        raise ValueError("statement path must be relative under imports/statements/ without ..")
    rel = relative.as_posix()
    lines, skipped = _statement_lines(ledger.root, data, rel)
    if data.get("preview", False):
        return {"lines": lines, "skipped": skipped, "count": len(lines)}
    categories, repeated = {}, set()
    for item in data["categories"]:
        if item["line"] in categories:
            repeated.add(item["line"])
        categories[item["line"]] = item["category"]
    numbers = {row["line"] for row in lines}
    missing, unknown = sorted(numbers - categories.keys()), sorted(categories.keys() - numbers)
    if missing or unknown or repeated:
        raise ValueError(f"statement category lines: missing {missing}; unknown {unknown}; repeated {sorted(repeated)}")
    name = data.get("name", re.sub(r"[^a-z0-9]+", "-", relative.stem.lower()).strip("-")[:41].rstrip("-") or "statement")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", name):
        raise ValueError("statement report name must be a slug")
    output = ledger.root / "exports" / "statements"
    paths = {k: output / (name + suffix) for k, suffix in (("csv", ".csv"), ("markdown", ".md"))}
    for path in paths.values():
        legacy._validate_existing_path(ledger.root, path)
    rows, totals, prepared, occurrences = [], {}, [], {}
    for line in lines:
        number = line["line"]
        fields = validate({**{k: v for k, v in line.items() if k != "line"}, "category": categories[number],
                           "evidence_ref": f"statement {rel} line {number}"})
        facts = (fields["date"], _merchant(fields["merchant"]), fields["amount"], fields["currency"], fields["kind"])
        occurrences[facts] = occurrences.get(facts, 0) + 1
        identity = "expense:" + stable_id("statement", rel, *facts, str(occurrences[facts]))
        prepared.append((number, identity, fields))
    with localcontext() as ctx:
        ctx.prec = max(28, sum(len(row["amount"]) for row in lines) + 3)
        with ledger.connect() as conn:
            conn.execute("begin immediate")
            for number, identity, fields in prepared:
                saved = save(ledger, identity, fields, "statement", conn=conn)
                rows.append({"line": number, **saved["fields"], "expense_id": identity})
                bucket = totals.setdefault(fields["currency"], {})
                category = fields["category"]
                bucket[category] = bucket.get(category, Decimal(0)) + Decimal(fields["amount"]) * (-1 if fields["kind"] == "refund" else 1)
    totals = {c: {k: _number(v) for k, v in sorted(bucket.items())} for c, bucket in sorted(totals.items())}
    duplicates = card_duplicates(_rows(ledger))
    columns = "line date kind category amount currency merchant evidence_ref expense_id".split()
    table = [[str(row.get(k, "")) for k in columns] for row in rows]
    markdown = [f"# {_md(name)} — statement reconciliation", "", "| " + " | ".join(columns) + " |",
                "| " + " | ".join(["---"] * len(columns)) + " |"]
    markdown.extend("| " + " | ".join(_md(cell) for cell in row) + " |" for row in table)
    markdown += ["", "## Totals by category"]
    for currency, bucket in totals.items():
        for category, total in bucket.items():
            markdown.append(f"- {currency} {category}: {total}")
            table.append(["", "", "category_total", category, Decimal(total), currency, "", "", ""])
    markdown += ["", "## Possible duplicates"]
    for pair in duplicates:
        markdown.append("- " + _md(f"{pair['merchant']}: {pair['amount']} {pair['currency']}; "
                                  f"{', '.join(pair['dates'])}; {', '.join(pair['expense_ids'])}"))
        table.append(["", " / ".join(pair["dates"]), "possible_duplicate", "", pair["amount"], pair["currency"],
                      pair["merchant"], "", " / ".join(pair["expense_ids"])])
    legacy._ensure_directory(ledger.root, output)
    for kind, text in (("csv", _csv_text(columns, table)), ("markdown", "\n".join(markdown) + "\n")):
        fd = os.open(paths[kind], os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)
    return {"count": len(rows), "by_category": totals, "possible_duplicates": duplicates,
            "paths": {k: str(p) for k, p in paths.items()}, "skipped": skipped, "sent": False}


def export(ledger, trip_id):
    trip = ledger.get("trip", trip_id)
    if not trip:
        raise ValueError("trip_id must name an existing trip")
    rows = _rows(ledger, trip_id)
    totals, categories, duplicates = {}, {}, {}
    with localcontext() as ctx:
        ctx.prec = max(28, sum(len(r["fields"]["amount"]) for r in rows) + 3)
        for row in rows:
            f = row["fields"]
            total = totals.setdefault(f["currency"], {"charges": Decimal(0), "refunds": Decimal(0), "net": Decimal(0)})
            amount = Decimal(f["amount"])
            total["charges" if f["kind"] == "charge" else "refunds"] += amount
            signed = amount if f["kind"] == "charge" else -amount
            total["net"] += signed
            key = (f["currency"], f["category"])
            categories[key] = categories.get(key, Decimal(0)) + signed
            duplicates.setdefault((f["amount"], f["currency"], f["date"]), []).append(row["action_id"])
    totals = {currency: {k: _number(v) for k, v in total.items()} for currency, total in sorted(totals.items())}
    columns = "date kind category amount currency merchant description evidence_ref source expense_id".split()
    table = [[str({**r["fields"], "expense_id": r["action_id"]}.get(k, "")) for k in columns] for r in rows]
    csv_text = _csv_text(columns, table)
    md = _md
    lines = [f"# {md(trip['title'])} — expenses", "", "## Totals"]
    for currency, total in totals.items():
        lines.append(f"- {currency}: charges {total['charges']}; refunds {total['refunds']}; net {total['net']}")
        lines.extend(f"  - {category}: {_number(value)}" for (code, category), value in sorted(categories.items()) if code == currency)
    lines += ["", "| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    lines.extend("| " + " | ".join(md(cell) for cell in row) + " |" for row in table)
    output = ledger.root / "exports" / "expenses"
    legacy._ensure_directory(ledger.root, output)
    safe_id = trip_id if re.fullmatch(r"[A-Za-z0-9_-]{1,120}", trip_id) else stable_id(trip_id)
    paths = {kind: output / (safe_id + suffix) for kind, suffix in (("csv", ".csv"), ("markdown", ".md"))}
    for path in paths.values():
        legacy._validate_existing_path(ledger.root, path)
    for kind, text in (("csv", csv_text), ("markdown", "\n".join(lines) + "\n")):
        fd = os.open(paths[kind], os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)
    return {**{k: str(v) for k, v in paths.items()}, "totals": totals, "count": len(rows),
            "possible_duplicates": [ids for ids in duplicates.values() if len(ids) > 1]}


def dispatch(ledger, data):
    if data.get("action") == "import":
        return _import_statement(ledger, data)
    _safe({k: data[k] for k in ("reason", "merchant", "description", "evidence_ref", "source_action_id") if k in data})
    action = data.get("action")
    allowed = {"record": {*FIELDS, "expense", "trip_id", "source_action_id"}, "void": {"expense_id", "reason"},
               "list": {"trip_id", "include_void"}, "export": {"trip_id"}}
    if action not in allowed or set(data) - allowed[action] - {"action"}:
        raise ValueError("unknown expense action or fields")
    trip_id = data.get("trip_id")
    if "trip_id" in data and (not isinstance(trip_id, str) or not trip_id or not ledger.get("trip", trip_id)):
        raise ValueError("trip_id must name an existing trip")
    if action == "record":
        if "expense" in data and FIELDS.keys() & data.keys():
            raise ValueError("supply expense fields once")
        fields = validate(data.get("expense", {k: v for k, v in data.items() if k in FIELDS}))
        if not {"date", "evidence_ref"} <= fields.keys():
            raise ValueError("expense.date and expense.evidence_ref are required")
        if "source_action_id" in data:
            _text(data["source_action_id"], "source_action_id", 1000)
        identity = "expense:" + stable_id("receipt", fields["evidence_ref"])
        old = ledger.get("action", identity)
        # A voided row is history: nothing is inherited from it, and a corrected receipt may replace it.
        live = (old or {}).get("fields", {}) if old and old["status"] != "void" else {}
        if live and (any(live.get(k) != fields.get(k) for k in ("amount", "currency", "date", "kind"))
                     or live.get("merchant") and fields.get("merchant") and live["merchant"] != fields["merchant"]):
            # One evidence_ref is one receipt; a different charge under it would silently replace the first.
            raise ValueError("this evidence_ref already records a different receipt; use the forwarded message id or the merchant plus receipt number, or void the old row first")
        if live.get("trip_ref") and "source_action_id" in data and data["source_action_id"] != live.get("source_action_id") and not trip_id:
            raise ValueError("source_action_id changed: pass trip_id for the new association")
        # A re-record that omits the trip or source keeps them, so the row stays in its trip export.
        return save(ledger, identity, fields, "owner_receipt",
                    data.get("source_action_id", live.get("source_action_id")), trip_id or live.get("trip_ref"))
    if action == "void":
        identity = _text(data.get("expense_id"), "expense_id", 1000)
        reason = _text(data.get("reason"), "reason", 200, allow_empty=True)
        row = ledger.get("action", identity)
        if not row or row["action_type"] != "expense":
            raise ValueError("expense row not found")
        return ledger.put("action", identity, {"void_reason": reason}, status="void")
    if action == "list":
        if "include_void" in data and type(data["include_void"]) is not bool:
            raise ValueError("include_void must be boolean")
        return _rows(ledger, trip_id, data.get("include_void", False))
    if not trip_id:
        raise ValueError("expense export requires trip_id")
    return export(ledger, trip_id)
