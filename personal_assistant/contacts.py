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
COLUMNS = "contact_id name emails phones company title notes invalid_emails source_rows".split()
ALIASES = {"name": ["name", "full name", "display name"], "first": ["first name", "given name"],
           "last": ["last name", "family name"], "email": ["email", "e-mail", "email address"],
           "phone": ["phone", "mobile", "phone number"],
           "company": ["company", "organization", "organization 1 - name"],
           "title": ["title", "job title", "organization 1 - title"], "notes": ["notes"]}


def _space(value):
    return " ".join(value.split())


def _phone(value, code):
    value = ("+" if value.startswith(("+", "00")) else "") + re.sub(r"[^0-9]", "", value[2:] if value.startswith("00") else value)
    if code and value and not value.startswith("+"):
        if value.startswith("0"):  # A national number: drop one trunk 0.
            value = "+" + code + value[1:]
        elif value.startswith(code) and len(value) - len(code) >= 8:  # Already carries the code, without the +.
            value = "+" + value
        else:
            value = "+" + code + value
    return value


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
    legacy._validate_existing_path(root, path)
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
                parts = [_space(p) for p in re.split(r"\s*:::\s*|[;,]", after) if _space(p)]
                values = [p.lower() if kind == "email" else _phone(p, code) for p in parts]
                after = "; ".join(values)
                for value in values:
                    valid = value.count("@") == 1 and "." in value.split("@")[-1] and not re.search(r"\s", value)
                    key = "phones" if kind == "phone" else "emails" if valid else "invalid_emails"
                    row[key].append(value)
                    if key == "invalid_emails":
                        log("invalid_email", row=number, value=value)
            else:
                row[kind or extras[i]].append(after)
            if before != after:
                log("normalised", row=number, field=headers[i], before=before, after=after)
        row["name"] = [n for n in row["name"] if n] or [_space(" ".join(row["first"] + row["last"]))]
        if not any(row["name"] + row["emails"] + row["phones"] + row["invalid_emails"]):
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
        keys = [("email", v) for v in row["emails"]] + [("phone", v) for v in row["phones"] if len(re.sub(r"\D", "", v)) >= 7]
        for key in keys:
            if key in seen:
                parent[find(i)] = find(seen[key])
            seen[key] = i
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(find(i), []).append(row)
    contacts, names = [], {}
    for group in groups.values():
        numbers = [n for n, _ in group]
        contact = {"contact_id": "c-" + hashlib.sha256(",".join(map(str, sorted(numbers))).encode()).hexdigest()[:10], "source_rows": numbers}
        origins = {}
        for field in ("name", "emails", "phones", "company", "title", "notes", "invalid_emails", *extras.values()):
            values = [(v, n) for n, row in group for v in row[field] if v]
            unique = _unique(v for v, _ in values)
            if field in {"emails", "phones", "invalid_emails", "notes"}:
                contact[field] = " | ".join(unique) if field == "notes" else unique
                origins[field] = {v: next(n for x, n in values if x == v) for v in unique}
            else:
                kept = max(unique, key=len) if field == "name" and unique else next(iter(unique), "")
                contact[field] = kept
                origins[field] = next((n for v, n in values if v == kept), None)
                for v in unique:
                    if v != kept:
                        log("alternate", field=field, kept=kept, other=v, row=next(n for x, n in values if x == v))
        if len(group) > 1:
            log("merged", rows=numbers, contact_id=contact["contact_id"], kept_from=origins)
        contacts.append(contact)
        for raw_name in _unique(n for _, row in group for n in row["name"] if n):
            name = "".join(c for c in unicodedata.normalize("NFKD", raw_name.casefold()) if not unicodedata.combining(c) and not unicodedata.category(c).startswith("P"))
            bucket = names.setdefault(_space(name), []) if name.strip() else []
            if not any(c[0] is contact for c in bucket):
                bucket.append((contact, raw_name))
    possible = []
    for group in names.values():
        for i, (a, name) in enumerate(group):
            for b, _ in group[i + 1:]:
                item = {"rows": sorted(a["source_rows"] + b["source_rows"]), "name": name}
                possible.append(item)
                log("possible_duplicate", **item)
    counts = {"rows_read": len(table), "contacts_out": len(contacts), "rows_merged": len(rows) - len(contacts)}
    counts.update({key: sum(c["kind"] == kind for c in changes) for key, kind in (
        ("blank_rows", "blank_row"), ("merged_clusters", "merged"), ("normalised_fields", "normalised"),
        ("invalid_emails", "invalid_email"), ("alternates", "alternate"), ("possible_duplicates", "possible_duplicate"))})
    return contacts, changes, possible, counts, list(extras.values())


def _cell(value):
    if isinstance(value, list):
        return "; ".join(map(str, value))
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, dict) else str(value)


def _csv(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    for row in [columns, *[[_cell(r.get(k, "")) for k in columns] for r in rows]]:
        writer.writerow(["'" + v if v.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else v for v in row])
    return stream.getvalue()


def dispatch(ledger, data):
    try:
        headers, kinds, rows = _read(ledger.root, data)
        contacts, changes, possible, counts, extras = _dedupe(headers, kinds, rows, data.get("default_country_code"))
        columns = "kind row field before after value rows contact_id kept other kept_from name".split()
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
                "possible_duplicates": possible[:20], "source_unchanged": True}
    except (ValueError, OSError, RuntimeError, csv.Error) as exc:
        return {"error": str(exc)}
