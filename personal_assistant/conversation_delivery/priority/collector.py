#!/usr/bin/env python3
"""Offline, read-only priority-mail collector.

The collector emits selected message evidence.  It does not send mail, call a
model, write a transcript, or advance its source checkpoint during collection.
Only the integrated publisher records a downstream publication acknowledgement.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import json
import math
import pathlib
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, quote, unquote, urlsplit

try:
    from ..bounded_capture import run_bounded
    from ...automation import notification_occurrence_id
except ImportError:  # direct collector entrypoint
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "personal_assistant" / "conversation_delivery"))
    from bounded_capture import run_bounded
    from personal_assistant.automation import notification_occurrence_id


VERSION = 1
KIND = "priority_mail"
DEFAULT_LIMITS = {
    "max_pages": 4,
    "page_size": 25,
    "max_threads": 40,
    "max_events": 16,
    "max_provider_output_bytes": 2 * 1024 * 1024,
    "sender_bytes": 512,
    "subject_bytes": 1024,
    "snippet_bytes": 768,
    "body_bytes": 4096,
    "source_link_bytes": 1024,
    "expiry_seconds": 7 * 24 * 3600,
    "max_packet_bytes": 64 * 1024,
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+@-]{0,191}$")
_SAFE_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SAFE_RULE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_SAFE_SELECTOR = re.compile(r"^(?:[0-9]{1,3}|[A-Za-z0-9][A-Za-z0-9._%+\-]{0,191}@[A-Za-z0-9.-]{1,191})$")
_ALLOWED_SEARCH_KEYS = {"externalContent", "messages", "nextPageToken"}
_ALLOWED_GET_KEYS = {"body", "externalContent", "headers", "message"}
_SEARCH_ROW_KEYS = {"date", "from", "id", "labels", "subject", "threadId"}
_GET_MESSAGE_KEYS = {"body", "headers", "id", "internalDate", "labelIds", "sizeEstimate", "snippet", "threadId"}
_ALLOWED_RULE_FIELDS = {"sender", "subject"}
_ALLOWED_SOURCE_HOSTS = {"mail.google.com"}
_UNTRUSTED_START = "<<<EXTERNAL_UNTRUSTED_CONTENT"
_UNTRUSTED_END = re.compile(r"<<<END_[^>]*>>>")


class CollectorError(ValueError):
    """Configuration, state, or source data prevented a trustworthy result."""


class ShapeError(CollectorError):
    """Provider JSON was not one of the explicitly supported shapes."""


class ProviderError(CollectorError):
    """The read-only connector command failed or exceeded its bound."""


@dataclass(frozen=True)
class Account:
    alias: str
    account: str
    account_selector: str


@dataclass(frozen=True)
class Rule:
    rule_id: str
    field: str
    pattern: str
    query: str
    preserve_query: bool = False


@dataclass(frozen=True)
class Settings:
    command: str
    accounts: tuple[Account, ...]
    rules: tuple[Rule, ...]
    limits: Mapping[str, int]
    self_emails: frozenset[str]
    self_domains: frozenset[str]
    source_link_template: str
    enabled: bool = True


@dataclass(frozen=True)
class SearchHit:
    account_alias: str
    thread_id: str
    summary: Mapping[str, Any]
    message_ids: tuple[str, ...]
    search_rules: tuple[str, ...]


@dataclass(frozen=True)
class Message:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    body: str
    date: str
    source_link: str | None
    labels: tuple[str, ...]


def _str(value: Any, field: str, *, max_bytes: int = 4096) -> str:
    if not isinstance(value, str) or not value:
        raise CollectorError(f"{field} must be a non-empty string")
    if len(value.encode("utf-8")) > max_bytes:
        raise CollectorError(f"{field} exceeds its configured byte bound")
    return value


def _optional_str(value: Any, field: str, *, max_bytes: int = 2 * 1024 * 1024) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ShapeError(f"{field} has an unsupported type")
    if len(value.encode("utf-8")) > max_bytes:
        raise ShapeError(f"{field} exceeds the provider output bound")
    return value


def _external_content(value: Any) -> None:
    """Validate GOG's metadata without ever treating it as message content."""
    if value is None:
        return
    if not isinstance(value, Mapping) or set(value) - {"source", "untrusted", "wrapped"}:
        raise ShapeError("externalContent has an unsupported shape")
    source = value.get("source")
    if source is not None and (not isinstance(source, str) or len(source.encode("utf-8")) > 256):
        raise ShapeError("externalContent.source is not bounded text")
    for name in ("untrusted", "wrapped"):
        flag = value.get(name)
        if flag is not None and not isinstance(flag, bool):
            raise ShapeError(f"externalContent.{name} must be boolean")


def _strip_untrusted_wrapper(value: str, field: str) -> str:
    """Remove only the deterministic GOG wrapper; payload remains inert data."""
    if not value.startswith(_UNTRUSTED_START):
        return value
    marker_end = value.find(">>>")
    if marker_end < 0:
        raise ShapeError(f"{field} has a malformed untrusted wrapper")
    payload = value[marker_end + 3:]
    delimiter = re.search(r"\n---\s*payload\s*---\s*\n", payload)
    if delimiter:
        payload = payload[delimiter.end():]
    end = _UNTRUSTED_END.search(payload)
    if end:
        payload = payload[:end.start()]
    return payload.strip()


def _content_text(value: Any, field: str, *, max_bytes: int = 2 * 1024 * 1024) -> str:
    return _strip_untrusted_wrapper(_optional_str(value, field, max_bytes=max_bytes), field)


def _internal_date(value: Any) -> str:
    """Convert Gmail's millisecond internalDate to an unambiguous UTC date."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ShapeError("internalDate is not a supported millisecond timestamp")
    if isinstance(value, str) and not value.isdigit():
        raise ShapeError("internalDate is not an integer millisecond timestamp")
    if isinstance(value, float) and not value.is_integer():
        raise ShapeError("internalDate is not an integer millisecond timestamp")
    try:
        millis = float(value)
    except (TypeError, ValueError) as exc:
        raise ShapeError("internalDate is not a numeric millisecond timestamp") from exc
    if not math.isfinite(millis) or millis < 0:
        raise ShapeError("internalDate is not a finite positive timestamp")
    try:
        parsed = dt.datetime.fromtimestamp(millis / 1000.0, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ShapeError("internalDate is outside the supported date range") from exc
    return parsed.isoformat().replace("+00:00", "Z")


def _bound_text(value: str, byte_limit: int) -> tuple[str, bool]:
    """Return a UTF-8-safe prefix and whether bytes were removed."""
    raw = value.encode("utf-8")
    if len(raw) <= byte_limit:
        return value, False
    # Ignore only a split trailing code point; all complete preceding code
    # points, including instruction-like mail text, remain data.
    return raw[:byte_limit].decode("utf-8", errors="ignore"), True


def _safe_identity(value: Any, field: str) -> str:
    value = _str(value, field, max_bytes=192)
    if not _SAFE_ID.fullmatch(value):
        raise ShapeError(f"{field} contains unsupported identity characters")
    return value


def _parse_date(value: str, field: str = "date") -> float:
    text = _str(value, field, max_bytes=256)
    candidate = text.replace("Z", "+00:00")
    parsed: dt.datetime | None = None
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError, OverflowError):
            parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise ShapeError(f"{field} is not a timezone-aware date")
    return parsed.timestamp()


def _first_string(mapping: Mapping[str, Any], names: Iterable[str]) -> str:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, str) and value:
            return value
    return ""


def _headers(raw: Mapping[str, Any]) -> dict[str, str]:
    headers = raw.get("headers")
    if headers is None:
        return {}
    if not isinstance(headers, Mapping) or len(headers) > 128:
        raise ShapeError("headers is not a bounded mapping")
    result: dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ShapeError("header names and values must be strings")
        if len(name.encode("utf-8")) > 128 or len(value.encode("utf-8")) > 2 * 1024 * 1024:
            raise ShapeError("header exceeds the provider output bound")
        result[name.casefold()] = value
    return result


def _value_with_headers(raw: Mapping[str, Any], names: Iterable[str], headers: Mapping[str, str]) -> str:
    value = _first_string(raw, names)
    if value:
        return value
    for name in names:
        value = headers.get(name.casefold(), "")
        if value:
            return value
    return ""


def _labels(raw: Mapping[str, Any], fallback: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    values: Any = raw.get("labels", raw.get("labelIds"))
    if values is None and fallback is not None:
        values = fallback.get("labels", fallback.get("labelIds"))
    if values is None:
        return ()
    if not isinstance(values, list) or len(values) > 64 or any(not isinstance(v, str) or not v or len(v.encode("utf-8")) > 256 for v in values):
        raise ShapeError("labels must be a bounded list of strings")
    return tuple(sorted(set(v for v in values if v) )[:16])


def _message_from_raw(
    raw: Mapping[str, Any],
    *,
    parent_thread_id: str,
    fallback: Mapping[str, Any] | None = None,
) -> Message:
    if not isinstance(raw, Mapping):
        raise ShapeError("message item is not an object")
    fallback = fallback or {}
    envelope_headers = raw.get("_envelope_headers")
    headers = _headers({"headers": envelope_headers}) if envelope_headers is not None else {}
    if not headers:
        headers = _headers(raw)
    message_id = _value_with_headers(raw, ("messageId", "message_id", "id"), {})
    thread_id = _value_with_headers(raw, ("threadId", "thread_id", "thread"), {}) or parent_thread_id
    sender = _value_with_headers(raw, ("from", "sender", "fromAddress"), headers)
    subject = _value_with_headers(raw, ("subject", "title"), headers)
    internal_date = raw.get("internalDate")
    date = _internal_date(internal_date) if internal_date is not None else _value_with_headers(raw, ("date", "timestamp"), headers)
    if not message_id:
        message_id = _value_with_headers(fallback, ("messageId", "message_id", "id"), {})
    if not thread_id:
        thread_id = _value_with_headers(fallback, ("threadId", "thread_id", "thread"), {}) or parent_thread_id
    if not sender:
        sender = _value_with_headers(fallback, ("from", "sender", "fromAddress"), _headers(fallback))
    if not subject:
        subject = _value_with_headers(fallback, ("subject", "title"), _headers(fallback))
    if not date:
        date = _value_with_headers(fallback, ("date", "timestamp"), _headers(fallback))
    if not (message_id and thread_id and sender and subject and date):
        raise ShapeError("message lacks one of id, thread, sender, subject, or date")
    message_id = _safe_identity(message_id, "message id")
    thread_id = _safe_identity(thread_id, "thread id")
    sender = _str(_strip_untrusted_wrapper(sender, "sender"), "sender", max_bytes=4096)
    subject = _str(_strip_untrusted_wrapper(subject, "subject"), "subject", max_bytes=2 * 1024 * 1024)
    date = _str(date, "date", max_bytes=256)
    _parse_date(date)
    snippet = _content_text(
        _first_string(raw, ("snippet", "preview")) or _first_string(fallback, ("snippet", "preview")),
        "snippet",
    )
    envelope_body = raw.get("_envelope_body")
    body_value = envelope_body if isinstance(envelope_body, str) else _first_string(raw, ("body",))
    if not body_value:
        body_value = _first_string(fallback, ("body", "text", "plainText", "bodyText"))
    body = _content_text(body_value, "body")
    source_link = _first_string(raw, ("link", "url", "webLink", "source_link"))
    if not source_link:
        source_link = _first_string(fallback, ("link", "url", "webLink", "source_link")) or None
    if source_link is not None and len(source_link.encode("utf-8")) > 4096:
        raise ShapeError("source link exceeds the provider output bound")
    return Message(
        message_id=message_id,
        thread_id=thread_id,
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
        date=date,
        source_link=source_link,
        labels=_labels(raw, fallback),
    )


def _validate_config(raw: Any) -> Settings:
    if not isinstance(raw, Mapping):
        raise CollectorError("config must be an object")
    unknown = set(raw) - {"version", "connector", "accounts", "rules", "limits", "filters", "source_link_template", "enabled"}
    if unknown:
        raise CollectorError("config contains unsupported fields")
    if raw.get("version") != VERSION:
        raise CollectorError(f"config version must be {VERSION}")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise CollectorError("enabled must be boolean")
    connector = raw.get("connector")
    if not isinstance(connector, Mapping):
        raise CollectorError("connector must be an object")
    command = _str(connector.get("command"), "connector command", max_bytes=1024)
    # Only the executable is configurable.  Service, read-only flags, and
    # verbs are fixed below so a config cannot turn this into a sender.
    if set(connector) - {"command"}:
        raise CollectorError("connector contains unsupported fields")

    account_rows = raw.get("accounts")
    if not isinstance(account_rows, list) or not account_rows or len(account_rows) > 8:
        raise CollectorError("accounts must be a bounded non-empty list")
    accounts: list[Account] = []
    aliases: set[str] = set()
    for row in account_rows:
        if not isinstance(row, Mapping) or set(row) not in ({"alias", "account"}, {"alias", "account", "account_selector"}):
            raise CollectorError("each account must contain alias, account, and optional account_selector")
        alias = _str(row.get("alias"), "account alias", max_bytes=64)
        account = _str(row.get("account"), "configured account", max_bytes=512)
        selector = _str(row.get("account_selector", account), "account selector", max_bytes=256)
        if not _SAFE_ALIAS.fullmatch(alias) or alias in aliases:
            raise CollectorError("account aliases must be unique and safe")
        if not _SAFE_SELECTOR.fullmatch(selector):
            raise CollectorError("account_selector must be a numeric Gmail index or actual account selector")
        aliases.add(alias)
        accounts.append(Account(alias, account, selector))

    rule_rows = raw.get("rules")
    if not isinstance(rule_rows, list) or not rule_rows or len(rule_rows) > 256:
        raise CollectorError("rules must be a bounded non-empty list")
    rules: list[Rule] = []
    rule_ids: set[str] = set()
    for row in rule_rows:
        if not isinstance(row, Mapping) or set(row) != {"id", "field", "pattern", "query"}:
            raise CollectorError("each rule must contain only id, field, pattern, and query")
        rule_id = _str(row.get("id"), "rule id", max_bytes=64)
        field = _str(row.get("field"), "rule field", max_bytes=32)
        pattern = _str(row.get("pattern"), "rule pattern", max_bytes=4096)
        query = _str(row.get("query"), "rule query", max_bytes=4096)
        if not _SAFE_RULE.fullmatch(rule_id) or rule_id in rule_ids:
            raise CollectorError("rule ids must be unique and safe")
        if field not in _ALLOWED_RULE_FIELDS:
            raise CollectorError("rule field must be sender or subject")
        if "\x00" in query or "\n" in query or "\r" in query:
            raise CollectorError("rule query contains a forbidden control character")
        rule_ids.add(rule_id)
        rules.append(Rule(rule_id, field, pattern, query))

    limits = dict(DEFAULT_LIMITS)
    supplied_limits = raw.get("limits", {})
    if not isinstance(supplied_limits, Mapping):
        raise CollectorError("limits must be an object")
    if set(supplied_limits) - set(DEFAULT_LIMITS):
        raise CollectorError("limits contains an unsupported field")
    for name, default in DEFAULT_LIMITS.items():
        if name in supplied_limits:
            value = supplied_limits[name]
            if isinstance(value, bool) or not isinstance(value, int):
                raise CollectorError(f"limit {name} must be an integer")
            limits[name] = value
    if not 1 <= limits["max_pages"] <= 20 or not 1 <= limits["page_size"] <= 100:
        raise CollectorError("pagination limits are outside the safe range")
    if not 1 <= limits["max_threads"] <= 200 or not 1 <= limits["max_events"] <= 64:
        raise CollectorError("candidate limits are outside the safe range")
    if not (64 <= limits["sender_bytes"] <= 4096 and 128 <= limits["subject_bytes"] <= 8192):
        raise CollectorError("sender or subject bounds are outside the safe range")
    if not (64 <= limits["snippet_bytes"] <= 8192 and 128 <= limits["body_bytes"] <= 16384):
        raise CollectorError("snippet or body bounds are outside the safe range")
    if not (1024 <= limits["max_provider_output_bytes"] <= 16 * 1024 * 1024):
        raise CollectorError("provider output bound is outside the safe range")
    if not (3600 <= limits["expiry_seconds"] <= 30 * 24 * 3600):
        raise CollectorError("expiry bound is outside the safe range")
    if not (8 * 1024 <= limits["max_packet_bytes"] <= 256 * 1024):
        raise CollectorError("packet bound is outside the safe range")

    filters = raw.get("filters", {})
    if not isinstance(filters, Mapping) or set(filters) - {"self_emails", "self_domains"}:
        raise CollectorError("filters contains an unsupported field")
    def text_set(name: str) -> frozenset[str]:
        values = filters.get(name, [])
        if not isinstance(values, list) or len(values) > 32 or any(not isinstance(v, str) or not v for v in values):
            raise CollectorError(f"filters.{name} must be a bounded string list")
        return frozenset(v.casefold() for v in values)

    template = _str(raw.get("source_link_template"), "source link template", max_bytes=2048)
    parsed_template = urlsplit(template)
    if parsed_template.scheme != "https" or parsed_template.hostname not in _ALLOWED_SOURCE_HOSTS:
        raise CollectorError("source link template must use the validated mail.google.com HTTPS host")
    placeholders = set(re.findall(r"{([^}]+)}", template))
    if placeholders - {"account_selector", "thread_id", "message_id"}:
        raise CollectorError("source link template contains unsupported placeholders")
    if not {"account_selector", "thread_id", "message_id"} <= placeholders:
        raise CollectorError("source link template must contain account_selector, thread_id, and message_id")
    return Settings(
        command=command,
        accounts=tuple(accounts),
        rules=tuple(rules),
        limits=limits,
        self_emails=text_set("self_emails"),
        self_domains=text_set("self_domains"),
        source_link_template=template,
        enabled=enabled,
    )


def _legacy_settings(raw: Mapping[str, Any], clients_path: pathlib.Path | None, gog_command: str | None) -> Settings:
    """Adapt legacy inputs without silently rewriting explicit provider queries."""
    enabled = raw.get("priority_mail_alerts_enabled", True)
    if not isinstance(enabled, bool):
        raise CollectorError("legacy priority_mail_alerts_enabled must be a literal boolean")
    # An explicit pause is authoritative and must not touch optional client data
    # or require a provider executable.
    if not enabled:
        return Settings(
            command=gog_command or "",
            accounts=(),
            rules=(),
            limits=dict(DEFAULT_LIMITS),
            self_emails=frozenset(),
            self_domains=frozenset(),
            source_link_template="https://mail.google.com/mail/u/?authuser={account_selector}#all/{thread_id}/{message_id}",
            enabled=False,
        )
    if not gog_command:
        raise CollectorError("legacy priority config requires an explicit connector command")
    accounts: list[dict[str, str]] = []
    for index, (alias, key) in enumerate((("work", "work_account"), ("personal", "personal_account"))):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            raise CollectorError("legacy account input is invalid")
        selector = raw.get(f"{alias}_account_selector", value)
        if not isinstance(selector, str) or not _SAFE_SELECTOR.fullmatch(selector):
            raise CollectorError(f"legacy {alias} account selector is missing or invalid")
        accounts.append({"alias": alias, "account": value, "account_selector": selector})
    if not accounts:
        raise CollectorError("legacy priority config has no configured accounts")
    candidates: list[tuple[str, str, str, bool]] = []

    def add(field: str, pattern: Any, query: str | None = None, *, preserve_query: bool = False) -> None:
        if not isinstance(pattern, str) or not pattern.strip():
            return
        if len(candidates) >= 256:
            raise CollectorError("legacy priority candidates exceed the bounded rule limit")
        pattern = pattern.strip()
        if len(pattern.encode("utf-8")) > 4096:
            raise CollectorError("legacy priority candidate exceeds its bound")
        if query is None:
            query_field = "from" if field == "sender" else "subject"
            escaped = pattern.replace("\\", "\\\\").replace('"', '\\"')
            query = f'in:anywhere {query_field}:"{escaped}"'
        if not isinstance(query, str) or not query or len(query.encode("utf-8")) > 4096 or any(c in query for c in "\x00\n\r"):
            raise CollectorError("legacy client query is unsupported or exceeds its bound")
        candidates.append((field, pattern, query, preserve_query))

    terms = raw.get("static_terms", [])
    if not isinstance(terms, list) or len(terms) > 128:
        raise CollectorError("legacy static terms input is invalid")
    for term in terms:
        add("sender", term)
        add("subject", term)
    if clients_path is not None:
        try:
            clients = json.loads(clients_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CollectorError("clients input is missing") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise CollectorError("clients input could not be read") from exc
        if not isinstance(clients, list) or len(clients) > 10000:
            raise CollectorError("clients input is not a bounded list")
        for client in clients:
            if not isinstance(client, Mapping):
                raise CollectorError("clients input contains an invalid row")
            explicit_query = client.get("query")
            if explicit_query is not None:
                predicates = (("sender", client.get("email")), ("sender", client.get("domain")), ("subject", client.get("name")))
                usable = 0
                for field, pattern in predicates:
                    if isinstance(pattern, str) and pattern.strip():
                        add(field, pattern, explicit_query, preserve_query=True)
                        usable += 1
                if not usable:
                    raise CollectorError("legacy client query requires a bounded local email, domain, or name predicate")
                continue
            add("sender", client.get("email"))
            add("sender", client.get("domain"))
            add("subject", client.get("name"))

    unique: list[tuple[str, str, str, bool]] = []
    seen: set[tuple[str, str, str]] = set()
    for field, pattern, query, preserve_query in candidates:
        key = (field, pattern.casefold(), query)
        if key not in seen:
            seen.add(key)
            unique.append((field, pattern, query, preserve_query))
    if not unique:
        raise CollectorError("legacy priority config has no sender/subject candidates")
    rules = []
    for index, (field, pattern, query, preserve_query) in enumerate(unique, start=1):
        rules.append({"id": f"legacy-{field}-{index:04d}", "field": field, "pattern": pattern,
                      "query": query, "preserve_query": preserve_query})
    transformed = {
        "version": VERSION,
        "connector": {"command": gog_command},
        "accounts": accounts,
        "rules": rules,
        "filters": {"self_emails": raw.get("self_emails", []), "self_domains": raw.get("self_domains", [])},
        "limits": {},
        "source_link_template": "https://mail.google.com/mail/u/?authuser={account_selector}#all/{thread_id}/{message_id}",
        "enabled": True,
    }
    # preserve_query is an adapter-only marker, consumed before strict config validation.
    for row, (_, _, _, preserve) in zip(transformed["rules"], unique):
        row.pop("preserve_query", None)
    settings = _validate_config(transformed)
    return Settings(settings.command, settings.accounts,
                    tuple(Rule(r.rule_id, r.field, r.pattern, r.query, unique[i][3]) for i, r in enumerate(settings.rules)),
                    settings.limits, settings.self_emails, settings.self_domains,
                    settings.source_link_template, settings.enabled)


def load_settings(path: pathlib.Path, *, clients_path: pathlib.Path | None = None, gog_command: str | None = None) -> Settings:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CollectorError("config file is missing") from exc
    except json.JSONDecodeError as exc:
        raise CollectorError("config JSON is invalid") from exc
    if isinstance(raw, Mapping) and "connector" not in raw and ("work_account" in raw or "personal_account" in raw):
        return _legacy_settings(raw, clients_path, gog_command)
    return _validate_config(raw)


def _failure(source: str, reason: str) -> dict[str, str]:
    clean = " ".join(str(reason).replace("\x00", "").split())
    return {"source": source[:192], "error": (clean[:256] or "collector failure")}


def _run_gog(settings: Settings, account: Account, verb: str, args: list[str]) -> Any:
    if verb not in {"search", "get"}:
        raise AssertionError("internal command allowlist violation")
    gmail_command = ["gmail", "messages", "search"] if verb == "search" else ["gmail", "get"]
    cmd = [
        settings.command,
        "-a", account.account,
        "--no-input", "--json", "--wrap-untrusted", "--readonly", "--gmail-no-send",
        "--enable-commands-exact", "gmail.messages.search,gmail.get",
        *gmail_command,
        *args,
    ]
    try:
        result = run_bounded(
            cmd,
            timeout=90,
            max_stdout_bytes=settings.limits["max_provider_output_bytes"],
            max_stderr_bytes=min(settings.limits["max_provider_output_bytes"], 16 * 1024),
        )
    except (OSError, ValueError) as exc:
        raise ProviderError(f"{verb} command did not complete") from exc
    if result.timed_out:
        raise ProviderError(f"{verb} command timed out")
    if result.stdout_truncated or result.stderr_truncated:
        raise ProviderError(f"{verb} output exceeded the configured bound")
    if result.returncode != 0:
        raise ProviderError(f"{verb} command failed")
    try:
        return json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"{verb} returned invalid JSON") from exc


def _search_page(payload: Any, *, max_items: int) -> tuple[list[Mapping[str, Any]], str | None, str]:
    if not isinstance(payload, Mapping):
        raise ShapeError("search response is not a recognized list or envelope")
    unknown = set(payload) - _ALLOWED_SEARCH_KEYS
    if unknown or set(payload) < {"externalContent", "messages"}:
        raise ShapeError("search response does not match the GOG messages.search envelope")
    _external_content(payload.get("externalContent"))
    items = payload["messages"]
    token = payload.get("nextPageToken")
    if token is not None and (not isinstance(token, str) or len(token.encode("utf-8")) > 4096):
        raise ShapeError("search page token is not a string")
    token = token or None
    collection = "messages"
    if not isinstance(items, list):
        raise ShapeError("search collection is not a list")
    if len(items) > max_items:
        raise ShapeError("search collection exceeds the configured page-item bound")
    clean: list[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ShapeError("search item is not an object")
        if set(item) - _SEARCH_ROW_KEYS:
            raise ShapeError("search message row has unsupported fields")
        thread_id = _first_string(item, ("threadId", "thread_id", "id"))
        if not thread_id:
            raise ShapeError("search item lacks a thread identity")
        _safe_identity(thread_id, "search thread id")
        clean.append(item)
    return clean, token, collection


def _search_message_ids(item: Mapping[str, Any], collection: str) -> tuple[str, ...]:
    """Extract message identities without mistaking a thread id for one.

    Calibrated ``gmail messages search`` rows carry a message-level ``id``.
    A message get requires that explicit ID plus a thread identity; the old
    thread-level ``gmail search`` command is not accepted or emulated.
    """
    if collection != "messages":
        raise ShapeError("search collection is not the calibrated messages collection")
    message_id = _first_string(item, ("id",))
    if not message_id or not _first_string(item, ("threadId",)):
        raise ShapeError("search result has no explicit message identity for gmail get")
    return (_safe_identity(message_id, "search message id"),)


def _get_messages(payload: Any, parent_thread_id: str) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping) or set(payload) != _ALLOWED_GET_KEYS:
        raise ShapeError("get response does not match the GOG get envelope")
    message = payload.get("message")
    if not isinstance(message, Mapping):
        raise ShapeError("get response contains no message object")
    if set(message) != _GET_MESSAGE_KEYS:
        raise ShapeError("get message does not match the calibrated GOG shape")
    _external_content(payload.get("externalContent"))
    headers = payload.get("headers")
    if not isinstance(headers, Mapping):
        raise ShapeError("get response headers are not a mapping")
    body = payload.get("body")
    if not isinstance(body, str):
        raise ShapeError("get response body is not a string")
    item = dict(message)
    item["_envelope_headers"] = dict(headers)
    item["_envelope_body"] = body
    item["_parent_thread_id"] = parent_thread_id
    return [item]


def _query(rule: Rule) -> str:
    query = rule.query.strip()
    if rule.preserve_query:
        return query
    # Generated rules explicitly cross Gmail categories; modern rules retain the
    # candidate's familiar default while client-supplied queries remain verbatim.
    if "in:anywhere" not in query.casefold():
        query = "in:anywhere " + query
    return query


def _sender_is_self(sender: str, settings: Settings) -> bool:
    addresses = {value.casefold() for value in re.findall(r"[\w.+-]+@[\w.-]+", sender)}
    if addresses & settings.self_emails:
        return True
    domains = {value.rsplit("@", 1)[-1] for value in addresses}
    return bool(domains & settings.self_domains)


def _match_rules(message: Message, settings: Settings) -> list[Rule]:
    if _sender_is_self(message.sender, settings):
        return []
    sender = message.sender.casefold()
    subject = message.subject.casefold()
    matched: list[Rule] = []
    for rule in settings.rules:
        haystack = sender if rule.field == "sender" else subject
        if rule.pattern.casefold() in haystack:
            matched.append(rule)
    return matched


def _validated_provider_link(link: str, account: Account, message: Message) -> str:
    parsed = urlsplit(link)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_SOURCE_HOSTS:
        raise CollectorError("provider source link has an unapproved domain")
    selector = parse_qs(parsed.query).get("authuser", [None])[0]
    if selector is None:
        match = re.search(r"/mail/u/([^/]+)/", parsed.path)
        selector = unquote(match.group(1)) if match else None
    if selector != account.account_selector:
        raise CollectorError("provider source link account selector does not match configured account")
    decoded = unquote(link)
    if message.thread_id not in decoded or message.message_id not in decoded:
        raise CollectorError("provider source link does not identify the requested message")
    return link


def _source_link(settings: Settings, account: Account, message: Message) -> str:
    if message.source_link:
        link, truncated = _bound_text(message.source_link, settings.limits["source_link_bytes"])
        if truncated:
            raise CollectorError("provider source link exceeded its byte bound")
        return _validated_provider_link(link, account, message)
    try:
        link = settings.source_link_template.format(
            account_selector=quote(account.account_selector, safe=""),
            thread_id=quote(message.thread_id, safe=""),
            message_id=quote(message.message_id, safe=""),
        )
    except (KeyError, ValueError) as exc:
        raise CollectorError("source link template could not be rendered") from exc
    link, truncated = _bound_text(link, settings.limits["source_link_bytes"])
    if truncated:
        raise CollectorError("source link exceeded its byte bound")
    return _validated_provider_link(link, account, message)


def _canonical_rule_revision(rules: list[Rule]) -> str:
    payload = [
        {"id": rule.rule_id, "field": rule.field, "pattern": rule.pattern, "query": rule.query}
        for rule in sorted(rules, key=lambda item: item.rule_id)
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _event(settings: Settings, account: Account, message: Message, now: float) -> dict[str, Any]:
    rules = _match_rules(message, settings)
    if not rules:
        raise CollectorError("internal event requested without a matched rule")
    sender, sender_truncated = _bound_text(message.sender, settings.limits["sender_bytes"])
    subject, subject_truncated = _bound_text(message.subject, settings.limits["subject_bytes"])
    snippet, snippet_truncated = _bound_text(message.snippet, settings.limits["snippet_bytes"])
    body, body_truncated = _bound_text(message.body, settings.limits["body_bytes"])
    link = _source_link(settings, account, message)
    matched_rules = sorted(rule.rule_id for rule in rules)
    semantic = {
        "account_alias": account.alias,
        "account_selector": account.account_selector,
        "message_id": message.message_id,
        "thread_id": message.thread_id,
        "sender": message.sender,
        "subject": message.subject,
        "snippet": message.snippet,
        "body": message.body,
        "date": message.date,
        "matched_rules": matched_rules,
        "categories": list(message.labels),
        "source_link": link,
    }
    digest = hashlib.sha256(
        json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    source_epoch = _parse_date(message.date)
    expires_at = source_epoch + settings.limits["expiry_seconds"]
    status = "expired" if now >= expires_at else "new"
    rule_revision = _canonical_rule_revision(rules)
    occurrence = f"{account.alias}:{message.message_id}"
    automation_id = notification_occurrence_id("priority_mail", occurrence, digest)
    return {
        "event_id": f"priority-mail/{account.alias}/{message.message_id}",
        "revision": digest,
        "content_digest": digest,
        "status": status,
        "account_alias": account.alias,
        "account_selector": account.account_selector,
        "message_id": message.message_id,
        "thread_id": message.thread_id,
        "sender": sender,
        "sender_truncated": sender_truncated,
        "subject": subject,
        "subject_truncated": subject_truncated,
        "snippet": snippet,
        "snippet_truncated": snippet_truncated,
        "body": body,
        "body_truncated": body_truncated,
        "date": message.date,
        "expires_at": expires_at,
        "matched_rules": matched_rules,
        "categories": list(message.labels),
        "source_link": link,
        "content_is_untrusted_data": True,
        "selection_note": "matched configured sender/subject rule; keyword match is candidate selection only; urgency was not inferred",
        "observed_at": now,
        "automation_rule_id": "priority_mail",
        "automation_rule_revision": rule_revision,
        "automation_occurrence": occurrence,
        "automation_occurrence_id": automation_id,
    }


def _coverage(failures: list[dict[str, str]], truncated: bool, notes: list[str], searches_ok: int) -> dict[str, Any]:
    if failures and not searches_ok:
        status = "unknown"
    elif failures or truncated:
        status = "partial"
    else:
        status = "complete"
    if not notes:
        notes.append("searched configured priority sender/subject rules across Gmail categories; urgency was not inferred")
    return {"status": status, "truncated": bool(truncated), "notes": "; ".join(notes)[:2000]}


def collect(settings: Settings, now: float, *, collector_state: pathlib.Path | None = None) -> tuple[dict[str, Any] | None, int]:
    if collector_state is not None:
        raise CollectorError("collector state is deprecated and unsupported; QueueStore is the sole publication authority")
    if not settings.enabled:
        return {
            "version": VERSION,
            "kind": KIND,
            "observed_at": now,
            "events": [],
            "coverage": {
                "status": "unknown",
                "truncated": False,
                "notes": "priority mail collection is disabled by configuration; no provider read was attempted",
            },
            "failures": [_failure("collector:priority-mail", "collection disabled by configuration")],
        }, 2
    failures: list[dict[str, str]] = []
    notes: list[str] = []
    truncated = False
    searches_ok = 0
    thread_hits: dict[tuple[str, str], SearchHit] = {}
    stop_search = False

    for account in settings.accounts:
        for rule in settings.rules:
            if stop_search:
                break
            token: str | None = None
            seen_tokens: set[str] = set()
            pages = 0
            while True:
                pages += 1
                args = [_query(rule), "--max", str(settings.limits["page_size"])]
                if token:
                    args.append(f"--page={token}")
                try:
                    payload = _run_gog(settings, account, "search", args)
                    items, next_token, collection = _search_page(
                        payload, max_items=settings.limits["page_size"]
                    )
                    parsed_items = [
                        (item, _first_string(item, ("threadId", "thread_id", "id")), _search_message_ids(item, collection))
                        for item in items
                    ]
                    searches_ok += 1
                except (ProviderError, ShapeError, CollectorError) as exc:
                    failures.append(_failure(f"search:{account.alias}:{rule.rule_id}", str(exc)))
                    break
                for item, thread_id, message_ids in parsed_items:
                    key = (account.alias, thread_id)
                    prior = thread_hits.get(key)
                    if prior is None and len(thread_hits) >= settings.limits["max_threads"]:
                        truncated = True
                        notes.append("thread candidate bound reached while parsing provider pages")
                        stop_search = True
                        break
                    if prior is None:
                        thread_hits[key] = SearchHit(account.alias, thread_id, item, message_ids, (rule.rule_id,))
                    else:
                        thread_hits[key] = SearchHit(
                            account.alias,
                            thread_id,
                            prior.summary,
                            tuple(sorted(set(prior.message_ids) | set(message_ids))),
                            tuple(sorted(set(prior.search_rules) | {rule.rule_id})),
                        )
                if stop_search:
                    break
                if not next_token:
                    break
                if next_token in seen_tokens:
                    failures.append(_failure(f"search:{account.alias}:{rule.rule_id}", "pagination token repeated"))
                    break
                seen_tokens.add(next_token)
                if pages >= settings.limits["max_pages"]:
                    truncated = True
                    notes.append(f"pagination bound reached for {account.alias}/{rule.rule_id}; more source pages may exist")
                    break
                token = next_token

    ordered_threads = sorted(thread_hits.values(), key=lambda hit: (hit.thread_id, hit.search_rules))
    if len(ordered_threads) > settings.limits["max_threads"]:
        truncated = True
        notes.append("thread candidate bound reached; additional source threads were not fetched")
        ordered_threads = ordered_threads[: settings.limits["max_threads"]]

    events_by_id: dict[str, dict[str, Any]] = {}
    stop_events = False
    for hit in ordered_threads:
        if stop_events:
            break
        account = next(a for a in settings.accounts if a.alias == hit.account_alias)
        for message_id in hit.message_ids:
            if len(events_by_id) >= settings.limits["max_events"]:
                truncated = True
                notes.append("selected-event bound reached while parsing provider messages")
                stop_events = True
                break
            try:
                payload = _run_gog(settings, account, "get", [message_id, "--sanitize-content"])
                raw_messages = _get_messages(payload, hit.thread_id)
            except (ProviderError, ShapeError, CollectorError) as exc:
                failures.append(_failure(f"get:{account.alias}:{message_id}", str(exc)))
                continue
            for raw in raw_messages:
                try:
                    message = _message_from_raw(raw, parent_thread_id=hit.thread_id, fallback=hit.summary)
                    if message.thread_id != hit.thread_id:
                        raise ShapeError("get message thread identity conflicts with search result")
                    if message.message_id != message_id:
                        raise ShapeError("get message identity conflicts with requested message")
                    matched = _match_rules(message, settings)
                    if not matched:
                        continue
                    event = _event(settings, account, message, now)
                except (ShapeError, CollectorError) as exc:
                    failures.append(_failure(f"get:{account.alias}:{message_id}", str(exc)))
                    continue
                prior = events_by_id.get(event["event_id"])
                if prior is not None and prior["revision"] != event["revision"]:
                    failures.append(_failure(f"get:{account.alias}:{message_id}", "message identity returned conflicting revisions"))
                    continue
                if prior is None:
                    events_by_id[event["event_id"]] = event

    events = sorted(events_by_id.values(), key=lambda item: item["event_id"])
    if len(events) > settings.limits["max_events"]:
        truncated = True
        notes.append("selected-event bound reached; additional matching messages were not emitted")
        events = events[: settings.limits["max_events"]]
    if len(failures) > 64:
        truncated = True
        failures = failures[:64]
        notes.append("failure bound reached; additional failure details were omitted")
    coverage = _coverage(failures, truncated, notes, searches_ok)
    if not events and not failures and coverage["status"] == "complete":
        return None, 0
    packet: dict[str, Any] = {
        "version": VERSION,
        "kind": KIND,
        "observed_at": now,
        "events": events,
        "coverage": coverage,
        "failures": failures,
    }
    encoded = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    while len(encoded) > settings.limits["max_packet_bytes"] and packet["events"]:
        packet["events"].pop()
        packet["coverage"]["truncated"] = True
        packet["coverage"]["status"] = "partial"
        packet["coverage"]["notes"] = (packet["coverage"]["notes"] + "; packet byte bound reached; fewer events emitted")[:2000]
        encoded = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    while len(encoded) > settings.limits["max_packet_bytes"] and len(packet["failures"]) > 1:
        packet["failures"].pop()
        packet["coverage"]["truncated"] = True
        packet["coverage"]["notes"] = (packet["coverage"]["notes"] + "; packet byte bound reached; fewer failure details emitted")[:2000]
        encoded = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > settings.limits["max_packet_bytes"]:
        packet["events"] = []
        packet["failures"] = [_failure("collector:packet", "packet exceeded its configured byte bound")]
        packet["coverage"] = _coverage(packet["failures"], True, ["packet byte bound prevented selected evidence publication"], searches_ok)
    return packet, 2 if failures or packet["coverage"]["truncated"] else 0


def _print_packet(packet: Mapping[str, Any]) -> None:
    print(json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only, config-driven priority mail evidence collector")
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--config", required=True, type=pathlib.Path)
    collect_parser.add_argument("--clients", type=pathlib.Path, help="read-only clients.json for legacy priority config")
    collect_parser.add_argument("--gog-command", help="explicit connector executable for legacy priority config")
    collect_parser.add_argument("--state", type=pathlib.Path, help="deprecated compatibility option; rejected because the collector is stateless")
    collect_parser.add_argument("--observed-at", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = load_settings(args.config, clients_path=args.clients, gog_command=args.gog_command)
        observed = float(args.observed_at if args.observed_at is not None else time.time())
        if not math.isfinite(observed):
            raise CollectorError("observed-at must be finite")
        packet, status = collect(settings, observed, collector_state=args.state)
        if packet is not None:
            _print_packet(packet)
        return status
    except (CollectorError, OSError) as exc:
        # A malformed config/state cannot be allowed to look like a quiet tick.
        error_observed = getattr(args, "observed_at", None)
        if isinstance(error_observed, (int, float)) and math.isfinite(float(error_observed)):
            error_observed = float(error_observed)
        else:
            error_observed = time.time()
        _print_packet({
            "version": VERSION,
            "kind": KIND,
            "observed_at": error_observed,
            "events": [],
            "coverage": {"status": "unknown", "truncated": False, "notes": "collector could not establish source coverage"},
            "failures": [_failure("collector", str(exc))],
        })
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
