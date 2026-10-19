"""Read-only provider boundary for daily-ops.

The command builder is intentionally narrow: daily-ops can only ask gog for
Gmail searches, Calendar events, and (in the doctor) auth status. There is no
mail-writing command in this package. Provider content is data, never argv.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

BASE_FLAGS = ["--no-input", "--json", "--wrap-untrusted"]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class DailyOpsError(Exception):
    """Redacted failure that scheduled entrypoints surface as one line."""


def gog_binary() -> str:
    path = os.environ.get("GOG_PATH") or shutil.which("gog")
    if not path:
        raise DailyOpsError("gog binary not found; set GOG_PATH or install gog")
    return path


def unwrap(text: str | None) -> str:
    """Extract only the payload of gog's untrusted-content wrapper."""
    text = text or ""
    if "<<<EXTERNAL_UNTRUSTED_CONTENT" not in text:
        return text
    parts = re.findall(r"---\n(.*?)\n<<<END_EXTERNAL_UNTRUSTED_CONTENT", text, re.DOTALL)
    return "\n".join(parts).strip() if parts else text


def alias_emails(text: str, count: dict | None = None):
    """Replace addresses with deterministic per-call aliases."""
    counter = count if count is not None else {}
    mapping: dict[str, str] = {}

    def replace(match: re.Match) -> str:
        addr = match.group(0).lower()
        if addr not in mapping:
            mapping[addr] = f"[email-{len(mapping) + 1}]"
            counter[len(mapping)] = addr
        return mapping[addr]

    return EMAIL_RE.sub(replace, text or ""), counter


def _validate_account(account: Any) -> None:
    if (not isinstance(account, str) or not account.strip() or account.lstrip().startswith("-")
            or _CONTROL_RE.search(account)):
        raise DailyOpsError("provider account is invalid")


def _flag_value(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or _CONTROL_RE.search(value) or value.lstrip().startswith("-"):
        raise DailyOpsError(f"provider flag {name} has an invalid value")
    return value


def _typed_int(value: str, name: str, *, minimum: int = 0, maximum: int = 1000) -> None:
    try:
        parsed = int(_flag_value(value, name), 10)
    except (TypeError, ValueError) as exc:
        raise DailyOpsError(f"provider flag {name} requires an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise DailyOpsError(f"provider flag {name} is outside the supported range")


def _validate_read_args(args: list[Any]) -> None:
    if not isinstance(args, list) or len(args) < 3 or any(not isinstance(x, str) for x in args):
        raise DailyOpsError("provider operation is not an allowed read command")
    if any(_CONTROL_RE.search(item) for item in args):
        raise DailyOpsError("provider operation contains control characters")
    if args[0:2] == ["gmail", "search"]:
        query = args[2]
        if not query or query.lstrip().startswith("-"):
            raise DailyOpsError("gmail query must be data, not an option")
        specs = {"--max": "int", "--page": "page", "--all": "bool"}
    elif args[0:2] == ["calendar", "events"]:
        _flag_value(args[2], "calendar-id")
        specs = {"--days": "days", "--max": "int", "--page": "page", "--all-pages": "bool", "--all": "bool"}
    else:
        raise DailyOpsError("provider operation is not an allowed read command")

    seen: set[str] = set()
    index = 3 if args[0:2] == ["gmail", "search"] else 3
    while index < len(args):
        item = args[index]
        if not item.startswith("-"):
            raise DailyOpsError("provider operation contains an extra positional value")
        if item.startswith("-") and not item.startswith("--"):
            raise DailyOpsError("short or unknown provider flags are not allowed")
        name, separator, value = item.partition("=")
        kind = specs.get(name)
        if kind is None:
            raise DailyOpsError("provider operation contains an unsupported flag")
        if name in seen:
            raise DailyOpsError("provider operation repeats a flag")
        seen.add(name)
        if kind == "bool":
            if separator:
                raise DailyOpsError(f"provider flag {name} is boolean")
        else:
            if not separator:
                index += 1
                if index >= len(args) or args[index].startswith("-"):
                    raise DailyOpsError(f"provider flag {name} requires a value")
                value = args[index]
            if kind == "int":
                _typed_int(value, name, minimum=1)
            elif kind == "days":
                _typed_int(value, name, minimum=0, maximum=366)
            else:
                _flag_value(value, name)
        index += 1


def run(account: str, args: list[str], readonly: bool = True, extra_flags: list[str] | None = None, timeout: int = 90):
    """Execute one allowlisted, argv-vector read and parse a JSON response."""
    _validate_account(account)
    _validate_read_args(args)
    if readonly is not True:
        raise DailyOpsError("daily-ops provider calls must be readonly")
    if extra_flags:
        if any(flag not in {"--gmail-no-send"} for flag in extra_flags):
            raise DailyOpsError("unsupported provider flag")
    binary = gog_binary()
    cmd = [binary, "-a", account] + BASE_FLAGS + ["--readonly"]
    if args[:2] == ["gmail", "search"]:
        cmd.append("--gmail-no-send")
    cmd += list(extra_flags or []) + args
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DailyOpsError(f"GOG_TIMEOUT {args[0]} {args[1]} (account redacted)") from exc
    except OSError as exc:
        raise DailyOpsError(f"GOG_FAIL {args[0]} {args[1]} (provider unavailable)") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        safe = alias_emails(detail[0][:160])[0] if detail else "no output"
        raise DailyOpsError(f"GOG_FAIL rc={completed.returncode} {args[0]} {args[1]}: {safe}")
    raw = completed.stdout.strip()
    if not raw:
        raise DailyOpsError(f"GOG_BADJSON {args[0]} {args[1]}: empty response")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DailyOpsError(f"GOG_BADJSON {args[0]} {args[1]}: non-JSON response") from exc
    if data is None:
        raise DailyOpsError(f"GOG_BADSHAPE {args[0]} {args[1]}: null response")
    return data


def auth_check() -> Any:
    """Allowlisted identity/scope read used by doctor."""
    binary = gog_binary()
    command = [binary, "auth", "list", "--check", "--json", "--no-input", "--readonly"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DailyOpsError("GOG_FAIL auth check unavailable") from exc
    if result.returncode != 0:
        raise DailyOpsError("GOG_FAIL auth check failed")
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DailyOpsError("GOG_BADJSON auth check response") from exc



def iter_threads(data: Any) -> list[dict]:
    """Strictly extract a non-null list of message maps with identities."""
    items = data if isinstance(data, list) else None
    if isinstance(data, dict):
        for key in ("threads", "messages", "data", "items"):
            if key in data:
                items = data[key]
                break
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise DailyOpsError("GOG_BADSHAPE: gmail search returned non-object members")
    for item in items:
        identity = item.get("id") or item.get("threadId")
        if isinstance(identity, bool) or not isinstance(identity, (str, int)) or not str(identity):
            raise DailyOpsError("GOG_BADSHAPE: gmail member identity has wrong type")
        for field in ("from", "sender", "subject"):
            if field in item and item[field] is not None and not isinstance(item[field], str):
                raise DailyOpsError("GOG_BADSHAPE: gmail text field has wrong type")
    return items


def iter_events(data: Any) -> list[dict]:
    items = data if isinstance(data, list) else None
    if isinstance(data, dict):
        for key in ("events", "items", "data"):
            if key in data:
                items = data[key]
                break
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise DailyOpsError("GOG_BADSHAPE: calendar response returned non-object members")
    return items


def page(data: Any, parser, *, page_size: int) -> tuple[list[dict], bool, str | None, int | None]:
    """Return (items, has_more, cursor, provider_total), validating cursors."""
    items = parser(data)
    if isinstance(data, list):
        # A bare full-size list has no completeness metadata, so it is bounded
        # evidence rather than an invented complete result.
        return items, len(items) >= page_size, None, None
    if not isinstance(data, dict):
        raise DailyOpsError("GOG_BADSHAPE: paginated response must be an object")
    cursor = data.get("next_page_token", data.get("nextPageToken", data.get("next_cursor")))
    if cursor is not None and not isinstance(cursor, str):
        raise DailyOpsError("GOG_BADSHAPE: pagination cursor must be a string")
    if cursor is not None and (_CONTROL_RE.search(cursor) or any(char.isspace() for char in cursor)
                               or cursor.lstrip().startswith("-")):
        raise DailyOpsError("GOG_BADSHAPE: pagination cursor is invalid")
    if "has_more" in data:
        has_more = data["has_more"]
    elif "hasNextPage" in data:
        has_more = data["hasNextPage"]
    else:
        # gog's schema-preserving JSON keeps nextPageToken in the envelope;
        # --results-only would remove it and make safe pagination impossible.
        has_more = bool(cursor)
    if not isinstance(has_more, bool):
        raise DailyOpsError("GOG_BADSHAPE: has_more must be boolean")
    total = data.get("total_count", data.get("result_count", data.get("total")))
    if total is not None and (not isinstance(total, int) or isinstance(total, bool) or total < 0):
        raise DailyOpsError("GOG_BADSHAPE: provider total must be a non-negative integer")
    if has_more and not cursor:
        raise DailyOpsError("GOG_BADSHAPE: more results reported without a cursor")
    return items, has_more, cursor, total


def extract_thread_ids(data: Any) -> list[str]:
    return [str(item.get("id") or item.get("threadId")) for item in iter_threads(data)]


def dump(label: str, data: Any, cap: int = 6000) -> None:
    """Compatibility helper for interactive callers; all content is redacted."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    redacted, _ = alias_emails(text)
    print(f"== {label} ==\n{redacted[:cap]}")
