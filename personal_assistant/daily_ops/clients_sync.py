"""Opt-in, tenant-bound client indexer.

The connector is never used by default. Every enabled source is authenticated
and identity-checked before listing, fully shape-validated, and published by
one atomic replace. Any failure first replaces a trusted index with
``complete: false`` so a stale complete index cannot drive priority matching.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import config_dir as config_dir_of, load_config, validate_or_raise
from .gog_collector import DailyOpsError, alias_emails

FREEMAIL = {"gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "live.com",
            "yahoo.com", "icloud.com", "me.com", "proton.me", "protonmail.com"}
PAGE_LIMIT = 100
MAX_PAGES = 20
SUPABASE_REF_RE = re.compile(r"^[a-z]{20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")


def _run(cmd: list[str], timeout: int = 120) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DailyOpsError("SYNC_TIMEOUT provider operation") from exc
    except OSError as exc:
        raise DailyOpsError("SYNC_FAIL provider unavailable") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        safe = alias_emails(detail[0][:160])[0] if detail else "no output"
        raise DailyOpsError(f"SYNC_FAIL provider: {safe}")
    return result.stdout


def _binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise DailyOpsError(f"SYNC_FAIL {name}: CLI not found")
    return path


def _connector(cfg: dict) -> dict:
    priority = cfg.get("priority") if isinstance(cfg.get("priority"), dict) else {}
    connectors = priority.get("connectors") if isinstance(priority.get("connectors"), dict) else {}
    value = connectors.get("clients_sync") or {}
    if not isinstance(value, dict):
        raise DailyOpsError("clients_sync configuration must be an object")
    return value


def _parse_stripe_config(text: str) -> tuple[str, bool]:
    values = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip().lower()] = value.strip().strip("'\"")
    account = values.get("account_id") or values.get("account")
    if not isinstance(account, str) or not account:
        raise DailyOpsError("SYNC_FAIL stripe: active account identity missing")
    raw_live = values.get("livemode", values.get("live"))
    if raw_live is None:
        raise DailyOpsError("SYNC_FAIL stripe: active mode missing")
    if str(raw_live).lower() not in {"true", "false"}:
        raise DailyOpsError("SYNC_FAIL stripe: active mode invalid")
    return account, str(raw_live).lower() == "true"


def _verify_stripe_account(binary: str, connector: dict) -> None:
    expected = connector.get("stripe_account")
    if not isinstance(expected, str) or not expected:
        raise DailyOpsError("SYNC_FAIL stripe: configured account identity missing")
    output = _run([binary, "config", "--list"], timeout=60)
    actual, live = _parse_stripe_config(output)
    configured_live = connector.get("stripe_live", False)
    if not isinstance(configured_live, bool) or actual != expected or live is not configured_live:
        raise DailyOpsError("SYNC_REFUSED stripe account or mode does not match configured tenant")


def _client(email: Any, name: Any, source: str) -> dict:
    if not isinstance(email, str) or "@" not in email or not email.strip():
        raise DailyOpsError(f"SYNC_FAIL {source}: customer email shape invalid")
    if name is not None and not isinstance(name, str):
        raise DailyOpsError(f"SYNC_FAIL {source}: customer name shape invalid")
    email = email.strip().lower()
    domain = email.rsplit("@", 1)[1]
    return {"name": (name or email).strip(), "email": email,
            "domain": None if domain in FREEMAIL else domain, "source": source}


def stripe_customers(connector: dict) -> tuple[list[dict], bool]:
    binary = _binary("stripe")
    _verify_stripe_account(binary, connector)
    mode = ["--live"] if connector.get("stripe_live") is True else []
    clients: list[dict] = []
    cursor = None
    seen_cursors: set[str] = set()
    for page_number in range(MAX_PAGES):
        command = [binary, "customers", "list"] + mode + ["--limit", str(PAGE_LIMIT)]
        if cursor:
            command += ["--starting-after", cursor]
        try:
            data = json.loads(_run(command))
        except (json.JSONDecodeError, TypeError) as exc:
            raise DailyOpsError("SYNC_FAIL stripe: response was not valid JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("data"), list) or not isinstance(data.get("has_more"), bool):
            raise DailyOpsError("SYNC_FAIL stripe: response shape invalid")
        for customer in data["data"]:
            if not isinstance(customer, dict):
                raise DailyOpsError("SYNC_FAIL stripe: customer member shape invalid")
            if not isinstance(customer.get("id"), str) or not customer["id"]:
                raise DailyOpsError("SYNC_FAIL stripe: customer identity missing")
            if customer.get("email") is not None:
                clients.append(_client(customer["email"], customer.get("name"), "stripe"))
        if not data["has_more"]:
            return clients, True
        if page_number == MAX_PAGES - 1:
            return clients, False
        if not data["data"] or not isinstance(data["data"][-1].get("id"), str):
            raise DailyOpsError("SYNC_FAIL stripe: next-page identity missing")
        cursor = data["data"][-1]["id"]
        if cursor in seen_cursors:
            raise DailyOpsError("SYNC_FAIL stripe: pagination cursor repeated")
        seen_cursors.add(cursor)
    return clients, False


def _project_rows(data: Any) -> list[dict]:
    projects = data if isinstance(data, list) else data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, list) or any(not isinstance(item, dict) for item in projects):
        raise DailyOpsError("SYNC_FAIL supabase: project list shape invalid")
    for project in projects:
        ref = project.get("ref")
        status = project.get("status")
        if not isinstance(ref, str) or not SUPABASE_REF_RE.fullmatch(ref):
            raise DailyOpsError("SYNC_FAIL supabase: project identity shape invalid")
        if not isinstance(status, str) or not status.strip():
            raise DailyOpsError("SYNC_FAIL supabase: project status shape invalid")
        if "id" in project and (not isinstance(project["id"], str) or not project["id"].strip()):
            raise DailyOpsError("SYNC_FAIL supabase: project id shape invalid")
    return projects


def _verify_supabase_project(binary: str, connector: dict) -> None:
    expected = connector.get("supabase_ref")
    if not isinstance(expected, str) or not SUPABASE_REF_RE.fullmatch(expected):
        raise DailyOpsError("SYNC_FAIL supabase: configured project ref missing")
    try:
        data = json.loads(_run([binary, "projects", "list", "--output", "json"], timeout=60))
    except (json.JSONDecodeError, TypeError) as exc:
        raise DailyOpsError("SYNC_FAIL supabase: project identity response invalid") from exc
    matches = [item for item in _project_rows(data) if item.get("ref") == expected]
    if len(matches) != 1:
        raise DailyOpsError("SYNC_REFUSED supabase project is not the uniquely configured tenant project")
    status = matches[0].get("status")
    if status is not None and status not in {"ACTIVE", "active", "RUNNING", "running"}:
        raise DailyOpsError("SYNC_REFUSED supabase configured project is not active")


def supabase_users(connector: dict) -> tuple[list[dict], bool]:
    expected = connector.get("supabase_ref")
    if not isinstance(expected, str) or not SUPABASE_REF_RE.fullmatch(expected):
        raise DailyOpsError("SYNC_FAIL supabase: configured project ref missing")
    binary = _binary("supabase")
    _verify_supabase_project(binary, connector)
    ref = expected
    command = [binary, "db", "query", "select email, coalesce(raw_user_meta_data->>'name','') as name from auth.users where email is not null", "--project-ref", ref, "--output-format", "json"]
    try:
        data = json.loads(_run(command))
    except (json.JSONDecodeError, TypeError) as exc:
        raise DailyOpsError("SYNC_FAIL supabase: query response invalid") from exc
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise DailyOpsError("SYNC_FAIL supabase: rows shape invalid")
    clients = []
    for row in data["rows"]:
        if not isinstance(row, dict):
            raise DailyOpsError("SYNC_FAIL supabase: row member shape invalid")
        email, name = row.get("email"), row.get("name")
        if not isinstance(email, str) or not email.strip() or not EMAIL_RE.fullmatch(email.strip()):
            raise DailyOpsError("SYNC_FAIL supabase: customer email shape invalid")
        if not isinstance(name, str):
            raise DailyOpsError("SYNC_FAIL supabase: customer name shape invalid")
        clients.append(_client(email, name, "supabase"))
    return clients, True


def _write_index(path: str | os.PathLike[str], document: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    if target.is_symlink():
        raise DailyOpsError("SYNC_FAIL client index path is a symlink")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(os.fspath(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    except (OSError, TypeError, ValueError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise DailyOpsError("SYNC_FAIL client index could not be written atomically") from exc


def _read_index(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def sync(cfg: dict, config_directory: str, now_utc: dt.datetime | None = None):
    connector = _connector(cfg)
    if connector.get("enabled") is not True:
        return None, ""
    if connector.get("consent") is not True:
        raise DailyOpsError("SYNC_REFUSED connector consent must be the JSON boolean true")
    for key in ("stripe_live",):
        if key in connector and not isinstance(connector[key], bool):
            raise DailyOpsError(f"SYNC_REFUSED {key} must be a JSON boolean")
    target = Path(config_directory) / "clients.json"
    previous = _read_index(target)
    stamp = (now_utc or dt.datetime.now(dt.timezone.utc)).isoformat()
    # Invalidate before any provider execution so every source failure cannot
    # leave a previously complete index trusted by priority matching.
    _write_index(target, {"synced_at": stamp, "complete": False, "clients": []})
    sources = []
    if connector.get("stripe_account"):
        sources.append(("stripe", lambda: stripe_customers(connector)))
    if connector.get("supabase_ref"):
        sources.append(("supabase", lambda: supabase_users(connector)))
    if not sources:
        raise DailyOpsError("SYNC_REFUSED no enabled client source")
    merged: list[dict] = []
    complete = True
    failures = []
    for name, operation in sources:
        try:
            values, source_complete = operation()
            if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
                raise DailyOpsError(f"SYNC_FAIL {name}: normalized rows invalid")
            merged.extend(values)
            complete = complete and source_complete
            if not source_complete:
                failures.append(f"{name}: source pagination incomplete")
        except Exception as exc:
            complete = False
            failures.append(f"{name}: {exc if isinstance(exc, DailyOpsError) else 'provider response invalid'}")
    unique, seen = [], set()
    for item in merged:
        email = item.get("email")
        if not isinstance(email, str):
            failures.append("client row has invalid email")
            complete = False
            continue
        if email in seen:
            continue
        seen.add(email)
        unique.append(item)
    document = {"synced_at": stamp, "complete": complete and not failures, "clients": unique if not failures else []}
    # Invalidation is attempted even for malformed/null provider members.
    _write_index(target, document)
    if failures:
        raise DailyOpsError("; ".join(failures) + " — wrote incomplete index")
    changed = not (isinstance(previous, dict) and previous.get("clients") == unique and previous.get("complete") is True)
    if not changed:
        return str(target), ""
    counts = {source: sum(item.get("source") == source for item in unique) for source in ("stripe", "supabase")}
    suffix = "" if complete else " (INCOMPLETE — matching degraded to static terms)"
    return str(target), f"clients.json: {len(unique)} entries ({counts['stripe']} stripe, {counts['supabase']} supabase){suffix}"


def main() -> None:
    try:
        cfg = validate_or_raise(load_config())
        path, summary = sync(cfg, config_dir_of())
        if path and summary:
            print(summary)
    except (DailyOpsError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"⚠️ daily-ops clients-sync: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
