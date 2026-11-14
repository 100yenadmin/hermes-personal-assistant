"""Invoice bookkeeping and existing deadline/loop projections; never payments."""
import datetime as dt
import json
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP, localcontext

from jsonschema import Draft7Validator, FormatChecker

from .context import evaluation_moment, loop_chase, owner_zone
from .evidence import _date, _enum, _text
from .expenses import CATEGORIES, FIELDS as EXPENSE_FIELDS, _number
from .privacy import clean
from .profile import _private
from .state import legacy, now, stable_id

DIRECTIONS = ["receivable", "payable"]
STATUSES = ["open", "paid", "void"]
MINOR_UNITS = {"JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "ISK": 0, "UGX": 0,
               "BHD": 3, "KWD": 3, "OMR": 3, "JOD": 3, "TND": 3}
TEXT_LIMITS = {"counterparty": 120, "reference": 80, "description": 200, "evidence_ref": 1000,
               "trip_id": 1000, "invoice_id": 1000, "evidence": 200, "reason": 200}
FIELDS = {**{k: {"type": "string", "minLength": 1, "maxLength": n} for k, n in TEXT_LIMITS.items()},
          "direction": {"enum": DIRECTIONS}, "status": {"enum": STATUSES},
          "amount": EXPENSE_FIELDS["amount"], "currency": EXPENSE_FIELDS["currency"],
          "category": {"enum": sorted(set(CATEGORIES + ["products"]))},
          **{k: {"type": "string", "format": "date"} for k in ("issue_date", "due_date", "paid_on")},
          "remind_days_before": {"type": "integer", "minimum": 0, "maximum": 60}}
FIELDS.update({
    "terms_days": {"type": "integer", "minimum": 0, "maximum": 120},
    "lines": {"type": "array", "minItems": 1, "maxItems": 50, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["description", "quantity", "unit_price"], "properties": {
            "description": FIELDS["description"],
            "quantity": {"type": "string", "pattern": r"^[0-9]+(?:\.[0-9]{1,3})?$"},
            "unit_price": {"type": "string", "pattern": r"^[0-9]+(?:\.[0-9]{1,4})?$"}}}},
    "tax": {"type": "object", "additionalProperties": False, "required": ["label", "rate_percent"],
            "properties": {"label": {"type": "string", "minLength": 1, "maxLength": 40},
                           "rate_percent": {"type": "string", "pattern": r"^(?:[0-9]{1,2}(?:\.[0-9]{1,3})?|100)$"}}},
})
RECORD = {"direction", "counterparty", "reference", "amount", "currency", "issue_date", "due_date",
          "category", "evidence_ref"}
PREPARE = {"counterparty", "currency", "issue_date", "lines"}
ALLOWED = {"record": RECORD | {"description", "trip_id", "remind_days_before"},
           "paid": {"invoice_id", "paid_on", "evidence"}, "void": {"invoice_id", "reason"},
           "list": {"direction", "status", "trip_id"},
           "prepare": PREPARE | {"due_date", "terms_days", "reference", "tax", "category", "description", "trip_id"}}
OP_SCHEMA = {"oneOf": [
    {"type": "object", "additionalProperties": False,
     "properties": {"action": {"const": action}, **{k: FIELDS[k] for k in keys}},
     "required": ["action", *sorted(RECORD if action == "record" else keys if action != "list" else [])],
     **({"allOf": [{"if": {"properties": {"direction": {"const": "receivable"}}},
                    "then": {"properties": {"category": {"enum": ["services", "products", "other"]}}},
                    "else": {"properties": {"category": {"enum": CATEGORIES}}}}]} if action == "record" else {})}
    for action, keys in ALLOWED.items() if action != "prepare"] + [
        {"type": "object", "additionalProperties": False,
         "properties": {"action": {"const": "prepare"}, **{k: FIELDS[k] for k in ALLOWED["prepare"]},
                        "category": {"enum": ["services", "products", "other"]}},
         "required": ["action", *sorted(PREPARE)],
         "oneOf": [{"required": ["due_date"]}, {"required": ["terms_days"]}]}]}


def guarded(identity, action_type=None, existing=None, *, bookkeeping=False):
    if action_type == "invoice" or existing and existing["action_type"] == "invoice":
        return True
    if not str(identity).startswith("invoice:"):
        return False
    # Follow-through uses separate nudge transactions under the writable loop.
    return ":loop:" not in str(identity) and not (bookkeeping and str(identity).endswith(":loop"))


def _iban(value):
    """A real IBAN (mod-97 valid), not ordinary words like FY26 or AB12 Studio."""
    for match in re.finditer(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){11,30}\b", value):
        text_ = match.group()
        # Only lengths that end a written group (or the whole match): far fewer chance hits.
        ends = {len(re.sub(r"[ -]", "", text_[:i])) for i, c in enumerate(text_) if c in " -"} | {len(re.sub(r"[ -]", "", text_))}
        compact = re.sub(r"[ -]", "", text_)
        for n in sorted(e for e in ends if 15 <= e <= 34):
            text = compact[4:n] + compact[:4]
            if int("".join(str(int(c, 36)) for c in text)) % 97 == 1:
                return True
    return False


# Key names the hint may echo: PA's own field names and the wrappers models send. Any
# other key is only counted, since a key can carry an IBAN, card number or secret.
KNOWN_KEYS = set(FIELDS) | {"fields", "answers", "data", "args", "arguments", "action_id", "id",
                            "at", "date", "proof", "note", "notes", "payment_evidence"}
VALUE_HINTS = {"amount": 'amount as a string like "850.00"', "currency": "currency as 3 capital letters like GBP",
               "direction": "direction receivable or payable", "status": "status open, paid or void",
               "category": "category services, products or other for a receivable",
               "remind_days_before": "remind_days_before a whole number from 0 to 60",
               "terms_days": "terms_days a whole number from 0 to 120",
               "lines": "lines as 1 to 50 objects with description, quantity and unit_price decimal strings",
               "tax": "tax with label and rate_percent as a decimal string from 0 to 100",
               **{k: f"{k} as YYYY-MM-DD" for k in ("issue_date", "due_date", "paid_on")},
               **{k: f"{k} as text up to {n} characters" for k, n in TEXT_LIMITS.items()}}


def _shape_hint(data):
    """Name the fields the action takes, so a model can correct its call (key names only, never values)."""
    action = data.get("action")
    if not isinstance(action, str) or action not in ALLOWED:
        return "action must be one of " + ", ".join([*sorted(ALLOWED.keys() - {"prepare"}), "prepare"])
    required = sorted(PREPARE if action == "prepare" else RECORD if action == "record"
                      else ALLOWED[action] if action != "list" else ())
    optional = sorted(ALLOWED[action] - set(required))
    extra = [k for k in data if k != "action" and k not in ALLOWED[action]]
    named = sorted(k for k in extra if k in KNOWN_KEYS)[:5]
    others = len(extra) - len(named)
    missing = sorted(set(required) - set(data))
    hint = f"{action} takes " + (", ".join(required) or "no required fields")
    if action == "prepare":
        hint += "; exactly one of due_date or terms_days"
    hint += f"; optional: {', '.join(optional)}" if optional else ""
    hint += f"; missing: {', '.join(missing)}" if missing else ""
    hint += f"; not accepted: {', '.join(named)}" if named else ""
    hint += f"; plus {others} other key{'s' if others != 1 else ''} not accepted" if others else ""
    if not extra and not missing:
        sent = [VALUE_HINTS[k] for k in sorted(data) if k in VALUE_HINTS]
        return hint + "; the field names are right, so check the values: " + ", ".join(sent)
    return hint + "; send them at the top level of data, dates as YYYY-MM-DD"


def _validate(data):
    private_data = {k: v for k, v in data.items() if k != "invoice_id"}  # Generated hex ids are not owner text.
    if data.get("action") == "prepare" and isinstance(data.get("lines"), list):
        # Decimal operands are numeric facts; apply the free-text scan to descriptions.
        private_data["lines"] = [line.get("description") for line in data["lines"] if isinstance(line, dict)]
    if _private(private_data):
        raise ValueError("PA does not store payment or account numbers or credentials")
    for key, value in data.items():
        if isinstance(value, str) and (_iban(value)
                or key in {"counterparty", "description", "evidence_ref", "reference"}
                and re.search(r"\d{%d,}" % (17 if key == "reference" else 8), value)):
            raise ValueError("PA does not store payment or account numbers")
    if not Draft7Validator(OP_SCHEMA, format_checker=FormatChecker()).is_valid(data):
        raise ValueError("invalid invoice action or fields: " + _shape_hint(data))
    for key, limit in TEXT_LIMITS.items():
        if key in data:
            _text(data[key], "invoice." + key, limit)
    for key, choices in (("direction", DIRECTIONS), ("status", STATUSES)):
        if key in data:
            _enum(data[key], "invoice." + key, choices)
    for key in ("issue_date", "due_date", "paid_on"):
        if key in data:
            _date(data[key], "invoice." + key)
    if data["action"] == "prepare":
        for line in data["lines"]:
            _text(line["description"], "invoice.lines.description", 200)
            if _iban(line["description"]) or re.search(r"\d{8,}", line["description"]):
                raise ValueError("PA does not store payment or account numbers")
            if any(Decimal(line[k]) <= 0 for k in ("quantity", "unit_price")):
                raise ValueError("invoice line quantity and unit_price must be positive")
        if "tax" in data:
            _text(data["tax"]["label"], "invoice.tax.label", 40)
    if data["action"] == "record":
        if Decimal(data["amount"]) <= 0:
            raise ValueError("invoice.amount must be positive")
    if data["action"] in {"record", "prepare"} and "due_date" in data:
        if data["due_date"] < data["issue_date"]:
            raise ValueError("invoice.due_date must be on or after issue_date")
    if clean(data) != data:
        raise ValueError("invoice text must not contain restricted details")


def _get(conn, identity):
    row = conn.execute("select * from actions where action_id=?", (identity,)).fetchone()
    return legacy.row_to_dict(row) if row else None


def _put(conn, identity, fields, status, trip_id, *, invoice=False, remove=()):
    old = _get(conn, identity)
    merged = {**(old or {}).get("fields", {}), **fields}
    for key in remove:
        merged.pop(key, None)
    stamp = now()
    conn.execute("insert into actions values(?,?,?,?,?,?,?,?) on conflict(action_id) do update set "
                 "trip_id=excluded.trip_id,action_type=excluded.action_type,status=excluded.status,"
                 "fields_json=excluded.fields_json,updated_at=excluded.updated_at",
                 (identity, trip_id, "invoice" if invoice else "commitment", "", status,
                  json.dumps(merged, ensure_ascii=False), (old or {}).get("created_at", stamp), stamp))


def _record(conn, data, zone):
    fields = {k: v for k, v in data.items() if k != "action"}
    fields["amount"] = _number(Decimal(fields["amount"]))
    normalized = " ".join(unicodedata.normalize("NFKC", fields["counterparty"]).casefold().split())
    reference = " ".join(unicodedata.normalize("NFKC", fields["reference"]).casefold().split())
    identity = "invoice:" + fields["direction"] + ":" + stable_id(
        "invoice", fields["direction"], normalized, reference)
    old = _get(conn, identity)
    if old and any(old["fields"].get(k) != fields[k] for k in ("amount", "currency", "issue_date", "due_date")):
        raise ValueError("invoice money facts differ; void it first; void rows revive only with matching money facts")
    revive = old and old["status"] == "void"
    status = "open" if not old or revive else old["status"]
    trip = fields.get("trip_id", (old or {}).get("trip_id"))
    ref, party, due = fields["reference"], fields["counterparty"], fields["due_date"]
    receivable = fields["direction"] == "receivable"
    reminder = {"radar_kind": "deadline", "event_date": due,
                "lead_days": fields.get("remind_days_before", ((_get(conn, identity + ":due") or {}).get("fields") or {}).get("lead_days", 3)),
                "title": f"Invoice {ref} {'to' if receivable else 'from'} {party} due {due}",
                "next_action": (f"Draft a friendly payment reminder to {party} for {ref}; send only after the owner's yes."
                                if receivable else f"Remind the owner to pay {party} {fields['amount']} {fields['currency']} by {due}. PA never pays.")}
    _put(conn, identity, fields, status, trip, invoice=True,
         remove=("void_reason", "paid_on", "paid_evidence") if revive else ())
    _put(conn, identity + ":due", reminder, "pending" if status == "open" else "completed", trip)
    if receivable:
        loop_id = identity + ":loop"
        loop = _get(conn, loop_id)
        loop_fields = {"loop_kind": "waiting_on_them", "counterparty": party, "next_actor": "them",
                       "next_step": f"Payment of {ref}, {fields['amount']} {fields['currency']}, due {due}",
                       "opened_at": due,  # A bare date is read as owner-local midnight, whatever the zone later.
                       "source_action_id": identity}
        if not loop or revive:
            loop_fields["chase_log"] = []
        _put(conn, loop_id, loop_fields, "open" if not loop or revive else loop["status"], trip,
             remove=("confirmation", "loop_cancelled", "last_chased_at", "snoozed_until", "chase_at") if revive else ())
    return identity


def prepare(ledger, data):
    """Compute a draft from validated input and existing rows, without recording it."""
    issue = dt.date.fromisoformat(data["issue_date"])
    try:
        due = data.get("due_date") or (issue + dt.timedelta(days=data["terms_days"])).isoformat()
    except OverflowError:
        raise ValueError("invoice due_date is outside the supported date range") from None
    currency = data["currency"]
    places = MINOR_UNITS.get(currency, 2)
    with localcontext() as ctx:
        # Product coefficients, summation carry, and tax multiplication all fit exactly.
        ctx.prec = max(28, max(len(line["quantity"]) + len(line["unit_price"])
                               for line in data["lines"]) + 20)
        quantum = Decimal(1).scaleb(-places)

        def money(value):
            return format(value.quantize(quantum, rounding=ROUND_HALF_UP), f".{places}f")

        lines = [{"description": line["description"], "quantity": _number(Decimal(line["quantity"])),
                  "unit_price": line["unit_price"],
                  "amount": money(Decimal(line["quantity"]) * Decimal(line["unit_price"]))}
                 for line in data["lines"]]
        subtotal = sum((Decimal(line["amount"]) for line in lines), Decimal(0))
        tax = ({**data["tax"], "amount": money(subtotal * Decimal(data["tax"]["rate_percent"]) / 100)}
               if "tax" in data else None)
        total = subtotal + (Decimal(tax["amount"]) if tax else Decimal(0))
        if total <= 0:
            raise ValueError("invoice total must be positive after rounding")
        subtotal_text, total_text = money(subtotal), money(total)

    receivables = [r for r in ledger.list("action")
                   if r["action_type"] == "invoice" and r["fields"].get("direction") == "receivable"]
    reference, source, basis = data.get("reference"), "given" if "reference" in data else "none", None
    if reference is None:
        series = []
        for row in receivables:
            fields = row["fields"]
            match = re.fullmatch(r"(.*?)([0-9]+)", fields.get("reference", ""))
            if match:
                series.append((fields["issue_date"], int(match[2]), match[1], len(match[2]), fields["reference"]))
        if series:
            prefix = max(series)[2]
            matching = [s for s in series if s[2] == prefix]
            followed = max(matching, key=lambda s: (s[1], s[3], s[4]))
            reference = prefix + str(followed[1] + 1).zfill(max(s[3] for s in matching))
            source, basis = "next_in_series", followed[4]

    def normalized(value):
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    warnings = []
    for row in receivables:
        fields = row["fields"]
        if normalized(fields["counterparty"]) != normalized(data["counterparty"]):
            continue
        if source == "given" and normalized(fields["reference"]) == normalized(reference):
            warning = f"reference already used for {data['counterparty']}: {reference}"
            if warning not in warnings:
                warnings.append(warning)
        if (row["status"] == "open" and fields["currency"] == currency and Decimal(fields["amount"]) == total
                and abs((issue - dt.date.fromisoformat(fields["issue_date"])).days) <= 31):
            warnings.append(f"possible duplicate of {fields['reference']} issued {fields['issue_date']}")
    category = data.get("category", "services")
    record_args = ({"action": "record", "direction": "receivable", "counterparty": data["counterparty"],
                    "reference": reference, "amount": total_text, "currency": currency,
                    "issue_date": data["issue_date"], "due_date": due, "category": category,
                    "evidence_ref": "draft:prepared-invoice",
                    **{k: data[k] for k in ("description", "trip_id") if k in data}}
                   if reference is not None else None)
    return {"prepared": True, "recorded": False, "direction": "receivable", "counterparty": data["counterparty"],
            "currency": currency, "issue_date": data["issue_date"], "due_date": due,
            "terms_days": data.get("terms_days"), "reference": reference, "reference_source": source,
            "reference_basis": basis, "lines": lines, "subtotal": subtotal_text, "tax": tax, "total": total_text,
            "category": category, "description": data.get("description"), "warnings": warnings,
            "missing": [] if reference is not None else ["reference"], "record_args": record_args,
            "next_step": "Show the owner this draft invoice. Record it with record_args only after the owner's explicit yes; replace evidence_ref with where it was sent or saved."}


def dispatch(ledger, data):
    _validate(data)
    action, zone = data["action"], owner_zone(ledger)
    trip = data.get("trip_id")
    if trip is not None and not ledger.get("trip", trip):
        raise ValueError("trip_id must name an existing trip")
    if action == "prepare":
        return prepare(ledger, data)
    if action == "list":
        moment = evaluation_moment({})
        today = moment.astimezone(zone).date()
        rows = []
        for row in ledger.list("action"):
            fields = row["fields"]
            if row["action_type"] != "invoice" or any(
                    data.get(k) is not None and data[k] != (row.get(k) if k in {"status", "trip_id"} else fields.get(k))
                    for k in ("direction", "status", "trip_id")):
                continue
            overdue = (today - dt.date.fromisoformat(fields["due_date"])).days
            row["days_overdue"] = max(0, overdue) if row["status"] == "open" else 0
            if fields["direction"] == "receivable":
                loop = ledger.get("action", row["action_id"] + ":loop")
                row["chase"] = loop_chase(loop["fields"], created_at=loop.get("created_at"), moment=moment,
                                          zone=zone) if loop and row["status"] == "open" else None
            rows.append(row)
        return sorted(rows, key=lambda r: (r["fields"]["due_date"], r["action_id"]))
    with ledger.connect() as conn:
        conn.execute("begin immediate")
        if action == "record":
            identity = _record(conn, data, zone)
        else:
            identity = data["invoice_id"]
            row = _get(conn, identity)
            if not row or row["action_type"] != "invoice":
                raise ValueError("invoice row not found")
            if action == "void" and row["status"] == "paid":
                raise ValueError("a paid invoice cannot be voided")
            if action == "paid" and row["status"] == "void":
                raise ValueError("record a matching invoice to revive it before marking paid")
            if action == "paid" and data["paid_on"] < row["fields"]["issue_date"]:
                raise ValueError("paid_on must not be before issue_date")
            paid = action == "paid"
            fields = {"paid_on": data["paid_on"], "paid_evidence": data["evidence"]} if paid else {"void_reason": data["reason"]}
            _put(conn, identity, fields, "paid" if paid else "void", row["trip_id"], invoice=True)
            _put(conn, identity + ":due", {}, "completed" if paid else "cancelled", row["trip_id"])
            if row["fields"]["direction"] == "receivable":
                closure = ({"confirmation": {"by": row["fields"]["counterparty"], "at": dt.datetime.combine(
                    dt.date.fromisoformat(data["paid_on"]), dt.time(12), zone).isoformat(), "evidence": data["evidence"]}}
                    if paid else {"loop_cancelled": {"by": "owner", "at": now(), "reason": data["reason"]}})
                _put(conn, identity + ":loop", closure, "completed" if paid else "cancelled", row["trip_id"],
                     remove=("loop_cancelled",) if paid else ("confirmation",))
    return ledger.get("action", identity)
