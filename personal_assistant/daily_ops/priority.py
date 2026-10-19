"""Priority matching against bounded, redacted message records."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any

from ..state import stable_id

ADDR_RE = re.compile(r"[\w.+-]+@[\w.-]+")
CLIENTS_FILENAME = "clients.json"
FREEMAIL = {"gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "live.com",
            "yahoo.com", "icloud.com", "me.com", "proton.me", "protonmail.com"}


def _parse_synced_at(raw: Any) -> dt.datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _as_term(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if len(value) >= 3 and "\n" not in value and "\r" not in value else None


def build_terms(cfg: dict, config_dir: str, now_utc: dt.datetime | None = None) -> tuple[list[str], str | None]:
    priority = cfg.get("priority") if isinstance(cfg.get("priority"), dict) else {}
    raw_static = priority.get("static_terms", [])
    terms = {_as_term(term) for term in raw_static} if isinstance(raw_static, list) else set()
    terms.discard(None)
    note = None
    connector = ((priority.get("connectors") or {}).get("clients_sync")
                 if isinstance(priority.get("connectors"), dict) else None) or {}
    if connector.get("enabled") is True and connector.get("consent") is True:
        path = os.path.join(config_dir, CLIENTS_FILENAME)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                index = json.load(handle)
        except (OSError, json.JSONDecodeError, UnicodeError):
            index = None
        entries = index.get("clients") if isinstance(index, dict) else None
        complete = index.get("complete") if isinstance(index, dict) else None
        synced = _parse_synced_at(index.get("synced_at") if isinstance(index, dict) else None)
        if not isinstance(entries, list):
            note = "client index missing — static terms only"
        elif complete is not True:
            note = "client index incomplete — static terms only"
        elif synced is None:
            note = "client index timestamp invalid — static terms only"
        elif now_utc is not None:
            age = (now_utc - synced).total_seconds() / 3600
            max_age = connector.get("client_max_age_h", 48)
            if not isinstance(max_age, int) or isinstance(max_age, bool) or max_age < 1:
                note = "client index age policy invalid — static terms only"
            elif age < 0 or age > max_age:
                note = "client index timestamp outside accepted window — static terms only"
            else:
                valid = _valid_client_index(entries)
                if not valid:
                    note = "client index malformed — static terms only"
                else:
                    _add_client_terms(terms, entries)
        else:
            if _valid_client_index(entries):
                _add_client_terms(terms, entries)
            else:
                note = "client index malformed — static terms only"
    return sorted(term for term in terms if term), note


def _valid_client_index(entries: list) -> bool:
    for client in entries:
        if not isinstance(client, dict) or not isinstance(client.get("email"), str) or "@" not in client["email"]:
            return False
        if client.get("name") is not None and not isinstance(client.get("name"), str):
            return False
        if client.get("domain") is not None and not isinstance(client.get("domain"), str):
            return False
        if client.get("source") is not None and not isinstance(client.get("source"), str):
            return False
    return True


def _add_client_terms(terms: set, entries: list) -> None:
    for client in entries:
        if not isinstance(client, dict):
            continue
        email = _as_term(client.get("email"))
        domain_raw = client.get("domain")
        domain = _as_term(domain_raw) if domain_raw is not None else None
        if not domain and email and "@" in email:
            domain = email.rsplit("@", 1)[1]
        freemail = domain in FREEMAIL
        if email:
            terms.add(email)
        if not freemail and domain:
            terms.add(domain)
            local = email.split("@", 1)[0] if email and "@" in email else None
            if local and len(local) >= 4:
                terms.add(local)
        name = _as_term(client.get("name"))
        if name and " " not in name:
            terms.add(name)


def self_exclusions(cfg: dict) -> tuple[set[str], set[str]]:
    emails: set[str] = set()
    for value in (cfg.get("self_emails"),):
        if isinstance(value, list):
            emails.update(str(item).strip().lower() for item in value if isinstance(item, str) and "@" in item)
    tenant = cfg.get("tenant") if isinstance(cfg.get("tenant"), dict) else {}
    accounts = cfg.get("accounts") if isinstance(cfg.get("accounts"), dict) else {}
    for value in (tenant.get("owner_email"), accounts.get("work"), accounts.get("personal")):
        if isinstance(value, str) and "@" in value:
            emails.add(value.lower())
    domains = set()
    configured = cfg.get("self_domains")
    if isinstance(configured, list):
        domains.update(str(item).strip().lower() for item in configured if isinstance(item, str))
    for email in emails:
        domain = email.rsplit("@", 1)[1]
        if domain not in FREEMAIL:
            domains.add(domain)
    return emails, domains


def hits_in_messages(cfg: dict, terms: list[str], messages: list[dict]) -> dict[str, list[str]]:
    if not isinstance(messages, list):
        raise ValueError("message collection must be a list")
    patterns = {term: re.compile(r"\b" + re.escape(term) + r"\b") for term in terms if isinstance(term, str)}
    self_emails, self_domains = self_exclusions(cfg)
    hits: dict[str, list[str]] = {}
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("message member must be an object")
        sender = message.get("from", message.get("sender", ""))
        subject = message.get("subject", "")
        if sender is None:
            sender = ""
        if subject is None:
            subject = ""
        if not isinstance(sender, str) or not isinstance(subject, str):
            raise ValueError("message sender and subject must be strings")
        addresses = {address.lower() for address in ADDR_RE.findall(sender)}
        if addresses & self_emails or {address.rsplit("@", 1)[1] for address in addresses} & self_domains:
            continue
        identity = message.get("id") or message.get("threadId")
        if not isinstance(identity, (str, int)) or not str(identity):
            raise ValueError("message identity is required")
        blob = f"{sender.lower()} {subject.lower()}"
        for term, pattern in patterns.items():
            if pattern.search(blob):
                hits.setdefault(term, []).append(str(identity))
    return {term: sorted(set(ids)) for term, ids in hits.items()}


def opaque_priority_key(account_index: int, term: str, thread_ids: list[str]) -> str:
    # Raw client addresses never enter a delivery or persisted dedup key.
    return stable_id("pa-priority", str(account_index), term, sorted(thread_ids))
