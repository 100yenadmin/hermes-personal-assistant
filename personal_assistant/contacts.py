"""Deterministic profile-local contact cleanup; no ledger or provider writes."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import unicodedata

from jsonschema import Draft7Validator
from .state import legacy

OP_SCHEMA = {"type": "object", "additionalProperties": False,
             "required": ["action", "path", "name"], "properties": {
                 "action": {"const": "dedupe"}, "path": {"type": "string", "minLength": 1},
                 "name": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{0,40}$"},
                 "default_country_code": {"type": "string", "pattern": r"^[0-9]{1,3}$"}}}
LIMIT = 5 * 1024 * 1024
COLUMNS = "contact_id name given_name family_name emails phones company title notes invalid_emails source_rows".split()
ALIASES = {"name": ["name", "full name", "display name"], "first": ["first name", "given name"],
           "last": ["last name", "family name"], "email": ["email", "e-mail", "email address", "e-mail address", "e-mail 2 address", "e-mail 3 address"],
           "phone": ["phone", "mobile", "phone number", "mobile phone", "business phone", "home phone", "primary phone"],
           "company": ["company", "organization", "organization 1 - name"],
           "title": ["title", "job title", "organization 1 - title"], "notes": ["notes"]}


def _space(value):
    return " ".join(value.split())


EXTENSION = re.compile(r"\s*(?:;\s*ext=|(?<![a-z])ext\.?|(?<![a-z])extension|(?<![a-z])x|#)\s*([0-9]{1,6})\s*$", re.I)
PHONE_CELL = r"\+?[0-9]+(?: ext\. [0-9]+)?"
KEEP_ZERO = {"39", "378", "225"}  # Italy, San Marino, Côte d'Ivoire: the leading 0 belongs to the number.


def _phone(value, code):
    match = EXTENSION.search(value)  # Keep an extension apart; its digits are not subscriber digits.
    extension = match.group(1) if match else ""
    value = value[:match.start()] if match else value
    value = ("+" if value.startswith(("+", "00")) else "") + re.sub(r"[^0-9]", "", value[2:] if value.startswith("00") else value)
    if code and value and not value.startswith("+"):
        rest = value[len(code):]
        # Already carries the code, without the +. Where the leading 0 is part of the number,
        # national numbers can start with the code digits (Italian mobiles 39x), so need more.
        coded = value.startswith(code) and ((rest.startswith("0") or len(rest) >= 10) if code in KEEP_ZERO else len(rest) >= 8)
        if value.startswith("0"):  # A national number: drop one trunk 0, unless the 0 is part of it.
            value = "+" + code + (value if code in KEEP_ZERO else value[1:])
        elif coded:
            value = "+" + value
        else:
            value = "+" + code + value
    return value + (" ext. " + extension if extension and value else "")


def _tokens(name):
    text = "".join(c for c in unicodedata.normalize("NFKD", name.casefold())
                   if not unicodedata.combining(c) and not unicodedata.category(c).startswith("P"))
    return frozenset(text.split())


def _unique(values):
    return list(dict.fromkeys(values))


def _read(root, data):
    if not Draft7Validator(OP_SCHEMA).is_valid(data):
        raise ValueError("invalid contacts action, name or country code")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", data["name"]) or ("default_country_code" in data and not re.fullmatch(r"[0-9]{1,3}", data["default_country_code"])):
        raise ValueError("invalid contacts name or country code")
    relative = Path(data["path"])
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 2 or relative.parts[0] != "imports":
        raise ValueError("contacts path must be relative under imports/")
    path = root / relative
    current = root
    for part in relative.parts:  # Read-only input: refuse symlinks, but not the owner's file permissions.
        current = current / part
        if current.is_symlink():
            raise ValueError("contacts path must not contain a symlink")
    if not path.is_file():
        raise ValueError("contacts path is not a regular file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        content = handle.read(LIMIT + 1)
    if len(content) > LIMIT:
        raise ValueError("contacts file exceeds 5 MB")
    text = content.decode("utf-8-sig")
    if "\x00" in text:
        raise ValueError("NUL in contacts CSV")
    previous = csv.field_size_limit(LIMIT)
    try:
        table = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    finally:
        csv.field_size_limit(previous)
    if not table or len(set(table[0])) != len(table[0]):
        raise ValueError("missing or duplicate CSV headers")
    headers, rows = table[0], table[1:]
    if any(row and len(row) != len(headers) for row in rows):
        raise ValueError("inconsistent CSV row width")
    kinds = []
    for header in headers:
        key = header.strip().casefold()
        kind = next((k for k, names in ALIASES.items() if key in names), None)
        if re.fullmatch(r"e-?mail \d+ - value", key):
            kind = "email"
        if re.fullmatch(r"phone \d+ - value", key):
            kind = "phone"
        kinds.append(kind)
    if not set(kinds) & {"name", "first", "last", "email", "phone"}:
        raise ValueError("no name, email or phone column")
    return headers, kinds, rows


def _dedupe(headers, kinds, table, code):
    changes, rows = [], []
    extras = {i: ("extra:" + h if h in [*COLUMNS, "first", "last"] else h) for i, (h, k) in enumerate(zip(headers, kinds)) if k is None}
    def log(kind, **values):
        changes.append({"kind": kind, **values})
    for number, raw in enumerate(table, 1):
        row = {k: [] for k in ("name", "first", "last", "emails", "phones", "invalid_emails", "company", "title", "notes", *extras.values())}
        for i, before in enumerate(raw):
            kind, after = kinds[i], _space(before)
            if kind in {"email", "phone"}:
                parts = [_space(p) for p in re.split(r"\s*:::\s*|[;,](?!\s*ext=)", after) if _space(p)]
                values = [p.lower() if kind == "email" else _phone(p, code) for p in parts]
                after = "; ".join(values)
                for value in values:
                    valid = bool(re.fullmatch(r"[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+", value))
                    key = "phones" if kind == "phone" else "emails" if valid else "invalid_emails"
                    row[key].append(value)
                    if key == "invalid_emails":
                        log("invalid_email", row=number, value=value)
            else:
                row[kind or extras[i]].append(after)
            if before != after:
                log("normalised", row=number, field=headers[i], before=before, after=after)
        row["name"] = [n for n in row["name"] if n] or [_space(" ".join(row["first"] + row["last"]))]
        if not any(value for values in row.values() for value in values):
            log("blank_row", row=number)
            continue
        rows.append((number, row))
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    for i, (_, row) in enumerate(rows):
        keys = [("email", v) for v in row["emails"]] + [("phone", v) for v in row["phones"] if len(re.sub(r"\D", "", v.split(" ext. ")[0])) >= 7]
        for key in keys:
            if key in seen:
                parent[find(i)] = find(seen[key])
            seen[key] = i
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(find(i), []).append(row)
    conflicts, kept_groups = [], []
    for group in groups.values():
        # One name set per row: display names plus the given and family names.
        tokens = [t for _, row in group for t in [frozenset().union(*map(_tokens, row["name"] + [" ".join(row["first"] + row["last"])]))] if t]
        widest = max(tokens, key=len, default=frozenset())
        if all(t <= widest for t in tokens):
            kept_groups.append(group)
            continue
        # A shared phone or email links different names (a switchboard, info@): the owner decides.
        item = {"rows": [n for n, _ in group], "names": _unique(n for _, row in group for n in row["name"] if n)}
        conflicts.append(item)
        log("name_conflict", **item)
        kept_groups.extend([member] for member in group)
    contacts, names = [], {}
    for group in kept_groups:
        numbers = [n for n, _ in group]
        contact = {"contact_id": "c-" + hashlib.sha256(",".join(map(str, sorted(numbers))).encode()).hexdigest()[:10], "source_rows": numbers}
        origins = {}
        for field in ("name", "first", "last", "emails", "phones", "company", "title", "notes", "invalid_emails", *extras.values()):
            out = {"first": "given_name", "last": "family_name"}.get(field, field)  # Structured names survive a display name.
            values = [(v, n) for n, row in group for v in row[field] if v]
            unique = _unique(v for v, _ in values)
            if field in {"emails", "phones", "invalid_emails", "notes"}:
                contact[out] = " | ".join(unique) if field == "notes" else unique
                origins[out] = {v: next(n for x, n in values if x == v) for v in unique}
            else:
                kept = max(unique, key=len) if field == "name" and unique else next(iter(unique), "")
                contact[out] = kept
                origins[out] = next((n for v, n in values if v == kept), None)
                for v in unique:
                    if v != kept:
                        log("alternate", field=out, kept=kept, other=v, row=next(n for x, n in values if x == v))
        if len(group) > 1:
            log("merged", rows=numbers, contact_id=contact["contact_id"], kept_from=origins)
        contacts.append(contact)
        for raw_name in _unique(n for _, row in group for n in row["name"] if n):
            name = "".join(c for c in unicodedata.normalize("NFKD", raw_name.casefold()) if not unicodedata.combining(c) and not unicodedata.category(c).startswith("P"))
            bucket = names.setdefault(_space(name), []) if name.strip() else []
            if not any(c[0] is contact for c in bucket):
                bucket.append((contact, raw_name))
    possible, listed = [], set()
    for group in names.values():  # One review item per shared name, never every pair.
        rows_ = sorted(r for contact, _ in group for r in contact["source_rows"])
        if len(group) > 1 and tuple(rows_) not in listed:
            listed.add(tuple(rows_))
            item = {"rows": rows_, "name": group[0][1]}
            possible.append(item)
            log("possible_duplicate", **item)
    counts = {"rows_read": len(table), "contacts_out": len(contacts), "rows_merged": len(rows) - len(contacts)}
    counts.update({key: sum(c["kind"] == kind for c in changes) for key, kind in (
        ("blank_rows", "blank_row"), ("merged_clusters", "merged"), ("normalised_fields", "normalised"),
        ("invalid_emails", "invalid_email"), ("alternates", "alternate"), ("possible_duplicates", "possible_duplicate"),
        ("name_conflicts", "name_conflict"))})
    return contacts, changes, possible, conflicts, counts, list(extras.values())


def _cell(value):
    if isinstance(value, list):
        return "; ".join(map(str, value))
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, dict) else str(value)


def _csv(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    for row in [columns, *[[_cell(r.get(k, "")) for k in columns] for r in rows]]:
        writer.writerow(["'" + v if v.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) and not re.fullmatch(PHONE_CELL + "(?:; " + PHONE_CELL + ")*", v) else v
                         for v in row])
    return stream.getvalue()


def dispatch(ledger, data):
    try:
        headers, kinds, rows = _read(ledger.root, data)
        contacts, changes, possible, conflicts, counts, extras = _dedupe(headers, kinds, rows, data.get("default_country_code"))
        columns = "kind row field before after value rows contact_id kept other kept_from name names".split()
        def md(value):
            return _cell(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")
        markdown = ["# Contact changes", "", "| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
        markdown += ["| " + " | ".join(md(c.get(k, "")) for k in columns) + " |" for c in changes]
        output = ledger.root / "exports" / "contacts"
        paths = {k: output / (data["name"] + suffix) for k, suffix in (
            ("clean", "-clean.csv"), ("changes_csv", "-changes.csv"), ("changes_markdown", "-changes.md"))}
        for path in paths.values():
            legacy._validate_existing_path(ledger.root, path)
            if path.exists() and path.stat().st_nlink > 1:
                raise ValueError("contacts output must not be hard-linked")
        texts = {"clean": _csv(COLUMNS + extras, contacts), "changes_csv": _csv(columns, changes),
                 "changes_markdown": "\n".join(markdown) + "\n"}
        legacy._ensure_directory(ledger.root, output)
        for kind, path in paths.items():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(texts[kind])
        return {"counts": counts, "paths": {k: str(p) for k, p in paths.items()},
                "possible_duplicates": possible[:20], "name_conflicts": conflicts[:20], "source_unchanged": True}
    except (ValueError, OSError, RuntimeError, csv.Error) as exc:
        return {"error": str(exc)}
