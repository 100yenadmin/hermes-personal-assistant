#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import math
import os
import re
import sqlite3
import stat
import sys
import uuid
from pathlib import Path


TRAVEL_LEDGER_DB_ENV = "TRAVEL_LEDGER_DB"
HERMES_HOME_ENV = "HERMES_HOME"
HERMES_WORKSPACE_ROOT_ENV = "HERMES_WORKSPACE_ROOT"
LEDGER_RELATIVE_PATH = Path("state") / "travel-ledger" / "travel.sqlite"

CONNECTIVITY_SCHEMA_VERSION = 1
CONNECTIVITY_DEFAULT_STALE_DAYS = 45.0
CONNECTIVITY_FIELDS = (
    "device_model", "region", "carrier_unlocked", "esim_supported", "os",
    "uses", "livestream_direction", "stream_bitrate_mbps", "hours_per_day",
    "hotspot_devices", "data_gb_per_day", "min_upload_mbps", "max_latency_ms",
    "budget_currency", "budget_total", "router_carry_ok", "redundancy",
    "trip_countries", "trip_start", "trip_end", "owned_connectivity",
)
CONNECTIVITY_FIELD_SET = frozenset(CONNECTIVITY_FIELDS)
CONNECTIVITY_BOOL_FIELDS = frozenset({"carrier_unlocked", "esim_supported", "router_carry_ok"})
CONNECTIVITY_NUMBER_FIELDS = frozenset({
    "stream_bitrate_mbps", "hours_per_day", "hotspot_devices", "data_gb_per_day",
    "min_upload_mbps", "max_latency_ms", "budget_total",
})
CONNECTIVITY_STRING_FIELDS = frozenset({
    "device_model", "region", "os", "livestream_direction", "budget_currency",
    "trip_start", "trip_end",
})
CONNECTIVITY_LIST_FIELDS = frozenset({"uses", "trip_countries"})
CONNECTIVITY_FLEXIBLE_FIELDS = frozenset({"redundancy", "owned_connectivity"})
CONNECTIVITY_FIELD_ALIASES = {
    "model": "device_model", "countries": "trip_countries", "start": "trip_start", "end": "trip_end",
    "device.model": "device_model", "device.region": "region",
    "device.carrier_unlocked": "carrier_unlocked", "device.esim_supported": "esim_supported",
    "device.os": "os", "workload.uses": "uses",
    "workload.livestream_direction": "livestream_direction",
    "workload.stream_bitrate_mbps": "stream_bitrate_mbps", "workload.hours_per_day": "hours_per_day",
    "workload.hotspot_devices": "hotspot_devices", "workload.data_gb_per_day": "data_gb_per_day",
    "workload.min_upload_mbps": "min_upload_mbps", "workload.max_latency_ms": "max_latency_ms",
    "workload.budget_currency": "budget_currency", "workload.budget_total": "budget_total",
    "workload.router_carry_ok": "router_carry_ok", "workload.redundancy": "redundancy",
    "trip.countries": "trip_countries", "trip.start": "trip_start", "trip.end": "trip_end",
    "trip.owned_connectivity": "owned_connectivity",
}
CONNECTIVITY_SENSITIVE_PATTERN = re.compile(
    r"\b(?:imei|eid|qr(?:[_ -]?code)?|password|passwd|passcode|pass|pin|otp|"
    r"one[- ]?time(?:[- ]?code)?|verification[- ]?code|auth(?:entication)?[- ]?code|"
    r"access[- ]?code|secret|token|"
    r"api[_ -]?key|private[_ -]?key|passport|cvc|cvv|card[_ -]?number|"
    r"credit[_ -]?card|phone[_ -]?number|telephone[_ -]?number)\b",
    re.IGNORECASE,
)
CONNECTIVITY_SENSITIVE_NUMERIC_PATTERN = re.compile(r"(?<!\d)\d{15,20}(?!\d)")


class LedgerPermissionError(RuntimeError):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _validate_root_components(path, name):
    """Reject user-controlled root ancestors that resolve through symlinks."""
    current = Path(path.anchor)
    symlink_seen = False
    directory_seen = False
    for part in path.parts:
        if part == path.anchor:
            continue
        current /= part
        try:
            entry = current.lstat()
        except FileNotFoundError as exc:
            raise RuntimeError(f"{name} must name an existing directory") from exc
        except OSError as exc:
            raise RuntimeError(f"cannot inspect {name}") from exc
        if stat.S_ISLNK(entry.st_mode):
            # macOS commonly exposes /tmp and /var as leading aliases. Allow
            # only those platform aliases, but reject any later or
            # user-controlled symlink component or a symlink used as the root.
            if current not in (Path("/tmp"), Path("/var")) or symlink_seen or directory_seen or current == path:
                raise RuntimeError(f"{name} must not contain symlink components")
            symlink_seen = True
        elif stat.S_ISDIR(entry.st_mode):
            directory_seen = True


def _resolved_env_path(name):
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    if "\x00" in value:
        raise RuntimeError(f"{name} contains a NUL byte")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"{name} must be an absolute directory")
    _validate_root_components(path, name)
    try:
        raw_stat = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"{name} must name an existing directory") from exc
    except OSError as exc:
        raise RuntimeError(f"cannot inspect {name}") from exc
    if stat.S_ISLNK(raw_stat.st_mode):
        raise RuntimeError(f"{name} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"cannot resolve {name}") from exc
    _validate_directory(resolved, name, owned=False)
    return resolved


def _validate_directory(path, label, *, owned):
    try:
        directory = path.stat()
    except OSError as exc:
        raise RuntimeError(f"cannot inspect {label}") from exc
    if not stat.S_ISDIR(directory.st_mode):
        raise RuntimeError(f"{label} must be a directory")
    forbidden = 0o022 if owned else 0o002
    if directory.st_mode & forbidden:
        permission = "group/world-writable" if owned else "world-writable"
        raise LedgerPermissionError(f"{label} has {permission} permissions")
    if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError(f"{label} is not readable and writable")


def _authoritative_root():
    profile_root = _resolved_env_path(HERMES_HOME_ENV)
    if profile_root is not None:
        return profile_root
    workspace_root = _resolved_env_path(HERMES_WORKSPACE_ROOT_ENV)
    if workspace_root is None:
        raise RuntimeError(
            f"set {HERMES_HOME_ENV} or {HERMES_WORKSPACE_ROOT_ENV} for a "
            f"profile-scoped {TRAVEL_LEDGER_DB_ENV}"
        )
    return workspace_root


def _validate_symlink_components(raw_root, candidate):
    """Reject symlink components in an explicitly supplied root-relative path."""
    try:
        relative = candidate.relative_to(raw_root)
    except ValueError as exc:
        raise RuntimeError(f"{TRAVEL_LEDGER_DB_ENV} must stay under {raw_root}") from exc
    current = raw_root
    for part in relative.parts:
        current /= part
        try:
            entry = current.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise RuntimeError(f"cannot inspect ledger path {current}") from exc
        if stat.S_ISLNK(entry.st_mode):
            raise RuntimeError(f"ledger path must not contain symlinks: {current}")


def _candidate_path(root):
    explicit = os.environ.get(TRAVEL_LEDGER_DB_ENV, "").strip()
    if "\x00" in explicit:
        raise RuntimeError(f"{TRAVEL_LEDGER_DB_ENV} contains a NUL byte")
    raw_root = None
    if explicit:
        raw_root = os.environ.get(HERMES_HOME_ENV, "").strip() or os.environ.get(HERMES_WORKSPACE_ROOT_ENV, "").strip()
        raw_root = Path(os.path.abspath(os.fspath(Path(raw_root).expanduser())))
    candidate = Path(explicit).expanduser() if explicit else root / LEDGER_RELATIVE_PATH
    if not candidate.is_absolute():
        candidate = raw_root / candidate if raw_root is not None else root / candidate
    if explicit:
        try:
            candidate.relative_to(raw_root)
        except ValueError:
            _validate_symlink_components(root, candidate)
        else:
            _validate_symlink_components(raw_root, candidate)
    else:
        _validate_symlink_components(root, candidate)
    # Normalize dot segments without resolving symlinks. Symlinks are rejected
    # separately below so that a path cannot escape or silently redirect.
    candidate = Path(os.path.abspath(os.fspath(candidate)))
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"{TRAVEL_LEDGER_DB_ENV} must stay under {root}") from exc
    if resolved == root:
        raise RuntimeError(f"{TRAVEL_LEDGER_DB_ENV} must name a database file under {root}, not the root itself")
    return resolved


def _validate_existing_path(root, candidate, *, owned=True, label="ledger directory"):
    """Reject symlinked path components and insecure existing DB paths."""
    if candidate == root:
        raise RuntimeError(f"{TRAVEL_LEDGER_DB_ENV} must name a database file under {root}, not the root itself")
    if candidate.parent == root:
        _validate_directory(root, f"{label} {root}", owned=owned)
    relative = candidate.relative_to(root)
    current = root
    for index, part in enumerate(relative.parts):
        current /= part
        try:
            entry = current.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise RuntimeError(f"cannot inspect ledger path {current}") from exc
        if stat.S_ISLNK(entry.st_mode):
            raise RuntimeError(f"ledger path must not contain symlinks: {current}")
        is_final = index == len(relative.parts) - 1
        if is_final:
            if not stat.S_ISREG(entry.st_mode):
                raise RuntimeError(f"ledger database must be a regular file: {current}")
            if entry.st_mode & 0o022:
                raise LedgerPermissionError(f"ledger database has group/world-writable permissions: {current}")
            if not os.access(current, os.R_OK | os.W_OK):
                raise RuntimeError(f"ledger database is not readable and writable: {current}")
        else:
            if not stat.S_ISDIR(entry.st_mode):
                raise RuntimeError(f"ledger path component must be a directory: {current}")
            _validate_directory(
                current,
                f"{label if current == candidate.parent else 'ledger directory'} {current}",
                owned=owned and current == candidate.parent,
            )


def _ensure_directory(root, path, *, owned=True, label="ledger directory"):
    """Create private directories; the caller selects leaf ownership."""
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        try:
            entry = current.lstat()
        except FileNotFoundError:
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            entry = current.lstat()
        except OSError as exc:
            raise RuntimeError(f"cannot inspect ledger directory {current}") from exc
        if stat.S_ISLNK(entry.st_mode):
            raise RuntimeError(f"ledger path must not contain symlinks: {current}")
        if not stat.S_ISDIR(entry.st_mode):
            raise RuntimeError(f"ledger path component must be a directory: {current}")
        _validate_directory(
            current,
            f"{label if current == path else 'ledger directory'} {current}",
            owned=owned and current == path,
        )


def _ensure_database_file(root, path):
    try:
        path.lstat()
    except FileNotFoundError:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(os.fspath(path), flags, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
    except OSError as exc:
        raise RuntimeError(f"cannot inspect ledger database {path}") from exc
    _validate_existing_path(root, path)


def db_path():
    """Resolve the ledger only inside the active Hermes root."""
    root = _authoritative_root()
    candidate = _candidate_path(root)
    _validate_existing_path(root, candidate)
    return str(candidate)


def connect():
    root = _authoritative_root()
    path = _candidate_path(root)
    conn = connect_at(root, path)
    ensure_schema(conn)
    return conn


def connect_at(root, path, *, timeout=None):
    """Open a ledger path after revalidating its profile containment."""
    root = Path(root)
    path = Path(path)
    if not root.is_absolute() or not path.is_absolute():
        raise RuntimeError("profile and ledger paths must be absolute")
    # Normalize dot segments without resolving symlinks, so a root-equivalent path
    # gets the root rejection before any directory is created.
    path = Path(os.path.abspath(os.fspath(path)))
    _validate_root_components(root, "profile")
    _validate_directory(root, "profile", owned=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"{TRAVEL_LEDGER_DB_ENV} must stay under {root}") from exc
    _validate_existing_path(root, path)
    _ensure_directory(root, path.parent)
    _validate_existing_path(root, path)
    _ensure_database_file(root, path)
    _validate_existing_path(root, path)
    kwargs = {} if timeout is None else {"timeout": timeout}
    conn = sqlite3.connect(os.fspath(path), **kwargs)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn):
    conn.executescript(
        """
        create table if not exists trips (
          trip_id text primary key,
          title text,
          status text,
          fields_json text not null default '{}',
          created_at text not null,
          updated_at text not null
        );
        create table if not exists actions (
          action_id text primary key,
          trip_id text,
          action_type text,
          provider text,
          status text,
          fields_json text not null default '{}',
          created_at text not null,
          updated_at text not null
        );
        create table if not exists browser_checkpoints (
          checkpoint_id text primary key,
          action_id text,
          provider text,
          lane text,
          session_id text,
          context_id text,
          url text,
          state text,
          fields_json text not null default '{}',
          created_at text not null,
          updated_at text not null
        );
        create table if not exists payment_readiness (
          readiness_id text primary key,
          provider text,
          status text,
          descriptor text,
          budget text,
          currency text,
          fields_json text not null default '{}',
          created_at text not null,
          updated_at text not null
        );
        create table if not exists connectivity_profiles (
          subject_id text not null,
          field_name text not null,
          value_json text not null,
          confirmed_at text not null,
          source text not null,
          created_at text not null,
          updated_at text not null,
          primary key (subject_id, field_name)
        );
        """
    )
    conn.commit()


def parse_value(value):
    value = str(value)
    try:
        return json.loads(value)
    except Exception:
        return value


def parse_fields(pairs):
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"--field must be key=value, got: {pair}")
        key, value = pair.split("=", 1)
        out[key] = parse_value(value)
    return out


def row_to_dict(row):
    data = dict(row)
    if "fields_json" in data:
        data["fields"] = json.loads(data.pop("fields_json") or "{}")
    return data


def print_result(data, as_json=False):
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        if isinstance(data, list):
            for item in data:
                print(json.dumps(item, sort_keys=True))
        else:
            print(json.dumps(data, sort_keys=True))


def _connectivity_subject(subject_id):
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise ValueError("connectivity subject_id is required")
    if "\x00" in subject_id:
        raise ValueError("connectivity subject_id contains a NUL byte")
    return subject_id


def _connectivity_datetime(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be an ISO-8601 timestamp with timezone")
    candidate = value.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include an explicit timezone")
    return parsed


def _connectivity_date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label} must be YYYY-MM-DD")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid YYYY-MM-DD date") from exc


def _connectivity_reject_sensitive_text(value, label):
    if isinstance(value, str) and (
        CONNECTIVITY_SENSITIVE_PATTERN.search(value)
        or CONNECTIVITY_SENSITIVE_NUMERIC_PATTERN.search(value)
    ):
        raise ValueError(f"sensitive or identifier value is forbidden in {label}")


def _canonical_connectivity_field(name):
    if not isinstance(name, str) or not name:
        raise ValueError("connectivity field names must be non-empty strings")
    canonical = CONNECTIVITY_FIELD_ALIASES.get(name, name)
    if canonical not in CONNECTIVITY_FIELD_SET:
        if CONNECTIVITY_SENSITIVE_PATTERN.search(name):
            raise ValueError(f"secret or identifier field is forbidden: {name}")
        raise ValueError(f"unknown connectivity field is not accepted: {name}")
    return canonical


def canonical_connectivity_field(name):
    """Return the canonical allowlisted connectivity field name."""
    return _canonical_connectivity_field(name)


def _validate_connectivity_value(value, field):
    if value is None:
        raise ValueError(f"{field} cannot be null")
    if field in CONNECTIVITY_BOOL_FIELDS:
        if not isinstance(value, bool):
            raise ValueError(f"{field} must be boolean")
        return value
    if field in CONNECTIVITY_NUMBER_FIELDS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} must be a finite non-negative number")
        if not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError(f"{field} must be a finite non-negative number")
        if field == "hotspot_devices" and int(value) != value:
            raise ValueError("hotspot_devices must be an integer")
        return value
    if field in CONNECTIVITY_STRING_FIELDS:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a non-empty string")
        value = value.strip()
        if not value:
            raise ValueError(f"{field} must be a non-empty string")
        _connectivity_reject_sensitive_text(value, field)
        if field in {"trip_start", "trip_end"}:
            _connectivity_date(value, field)
        if field == "budget_currency" and not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("budget_currency must be a three-letter uppercase code")
        return value
    if field in CONNECTIVITY_LIST_FIELDS:
        if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
            raise ValueError(f"{field} must be a non-empty list of strings")
        value = [item.strip() for item in value]
        if any(not item for item in value):
            raise ValueError(f"{field} must contain only non-empty strings")
        for item in value:
            _connectivity_reject_sensitive_text(item, field)
        return value
    if field in CONNECTIVITY_FLEXIBLE_FIELDS:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError(f"{field} cannot be empty")
            _connectivity_reject_sensitive_text(value, field)
            return value
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{field} contains a non-finite number")
            # Numbers get the same identifier guard as text: an IMEI/ICCID-sized
            # integer must not slip through because it arrived unquoted.
            numeric_text = str(int(value)) if float(value).is_integer() else repr(value)
            if CONNECTIVITY_SENSITIVE_NUMERIC_PATTERN.search(numeric_text):
                raise ValueError(f"sensitive or identifier value is forbidden in {field}")
            return value
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            value = [item.strip() for item in value]
            if not value or any(not item for item in value):
                raise ValueError(f"{field} must contain only non-empty strings")
            for item in value:
                _connectivity_reject_sensitive_text(item, field)
            return value
        raise ValueError(f"{field} must be a string, boolean, number, or string list")
    raise ValueError(f"no validator exists for connectivity field: {field}")


def _connectivity_record(record, field, *, strict_timestamp=True):
    if not isinstance(record, dict) or set(record) != {"value", "confirmed_at", "source"}:
        raise ValueError(f"{field} record must contain exactly value, confirmed_at, and source")
    value = _validate_connectivity_value(record["value"], field)
    confirmed_at = record["confirmed_at"]
    if not isinstance(confirmed_at, str):
        raise ValueError(f"{field}.confirmed_at must be a string")
    if strict_timestamp:
        _connectivity_datetime(confirmed_at, f"{field}.confirmed_at")
    source = record["source"]
    if not isinstance(source, str) or not source.strip() or "\n" in source or "\r" in source:
        raise ValueError(f"{field}.source must be a non-empty single-line string")
    if len(source) > 256:
        raise ValueError(f"{field}.source is too long")
    _connectivity_reject_sensitive_text(source, f"{field}.source")
    return {"value": value, "confirmed_at": confirmed_at, "source": source}


def _flatten_connectivity_input(data):
    if not isinstance(data, dict):
        raise ValueError("connectivity input must be an object")
    subject = data.get("subject_id")
    default_confirmed = data.get("confirmed_at")
    default_source = data.get("source")
    reserved = {"subject_id", "confirmed_at", "source", "fields", "device", "workload", "trip"}
    flattened = {}

    def add(raw_name, value):
        field = _canonical_connectivity_field(raw_name)
        if field in flattened and flattened[field] != value:
            raise ValueError(f"duplicate conflicting connectivity value for {field}")
        flattened[field] = value

    if "fields" in data:
        if not isinstance(data["fields"], dict):
            raise ValueError("connectivity fields must be an object")
        for key, value in data["fields"].items():
            add(key, value)
    for group in ("device", "workload", "trip"):
        if group not in data:
            continue
        if not isinstance(data[group], dict):
            raise ValueError(f"connectivity input group {group} must be an object")
        for key, value in data[group].items():
            add(f"{group}.{key}", value)
    for key, value in data.items():
        if key not in reserved:
            add(key, value)
    return flattened, subject, default_confirmed, default_source


def normalize_connectivity_fields(data, *, confirmed_at=None, source=None):
    """Validate dated allowlisted connectivity input without touching SQLite."""
    flattened, input_subject, top_confirmed, top_source = _flatten_connectivity_input(data)
    effective_confirmed = confirmed_at if confirmed_at is not None else top_confirmed
    effective_source = source if source is not None else top_source
    records = {}
    for field, raw_value in flattened.items():
        if isinstance(raw_value, dict) and "value" in raw_value:
            record = _connectivity_record(raw_value, field)
        else:
            if effective_confirmed is None or effective_source is None:
                raise ValueError(
                    f"raw connectivity value for {field} needs confirmed_at and source"
                )
            record = _connectivity_record(
                {"value": raw_value, "confirmed_at": effective_confirmed, "source": effective_source},
                field,
            )
        records[field] = record
    if not records:
        raise ValueError("connectivity input contains no allowlisted fields")
    return records, input_subject


def get_connectivity_profile(conn, subject_id):
    """Read one subject-scoped profile without renewing or writing timestamps."""
    subject_id = _connectivity_subject(subject_id)
    rows = conn.execute(
        "select field_name, value_json, confirmed_at, source from connectivity_profiles "
        "where subject_id=? order by field_name",
        (subject_id,),
    ).fetchall()
    fields = {}
    for row in rows:
        field = _canonical_connectivity_field(row["field_name"])
        if field != row["field_name"]:
            raise ValueError(f"stored connectivity field is not canonical: {row['field_name']}")
        try:
            value = json.loads(row["value_json"], parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"stored connectivity value is invalid for {field}") from exc
        # Null is a legacy/externally-written unknown marker.  Treat it like
        # an absent fact at read time; write-time validation remains strict so
        # mixed valid+null updates still fail atomically.
        if value is None:
            continue
        fields[field] = _connectivity_record(
            {"value": value, "confirmed_at": row["confirmed_at"], "source": row["source"]},
            field,
            strict_timestamp=False,
        )
    return {"schema_version": CONNECTIVITY_SCHEMA_VERSION, "subject_id": subject_id, "fields": fields}


def _connectivity_check_trip_range(conn, subject_id, records):
    """Reject a reversed trip range, including one formed with the stored counterpart."""
    merged = {}
    for field in ("trip_start", "trip_end"):
        if field in records:
            merged[field] = records[field]["value"]
        else:
            row = conn.execute(
                "select value_json from connectivity_profiles where subject_id=? and field_name=?",
                (subject_id, field),
            ).fetchone()
            if row is not None:
                try:
                    stored = json.loads(row["value_json"])
                except (TypeError, ValueError):
                    stored = None
                if isinstance(stored, str):
                    merged[field] = stored
    if "trip_start" in merged and "trip_end" in merged:
        start = _connectivity_date(merged["trip_start"], "trip_start")
        end = _connectivity_date(merged["trip_end"], "trip_end")
        if end < start:
            raise ValueError("trip_end must not be before trip_start")


def upsert_connectivity_fields(conn, subject_id, fields, *, confirmed_at=None, source=None):
    """Atomically merge dated connectivity fields into the existing PA ledger."""
    subject_id = _connectivity_subject(subject_id)
    records, input_subject = normalize_connectivity_fields(
        fields, confirmed_at=confirmed_at, source=source
    )
    if input_subject is not None and input_subject != subject_id:
        raise ValueError("connectivity input subject_id does not match requested subject_id")
    stamp = now()
    conn.execute("begin immediate")
    try:
        _connectivity_check_trip_range(conn, subject_id, records)
        for field, record in records.items():
            conn.execute(
                """
                insert into connectivity_profiles
                (subject_id, field_name, value_json, confirmed_at, source, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(subject_id, field_name) do update set
                  value_json=excluded.value_json,
                  confirmed_at=excluded.confirmed_at,
                  source=excluded.source,
                  updated_at=excluded.updated_at
                """,
                (
                    subject_id, field, json.dumps(record["value"], ensure_ascii=False, allow_nan=False),
                    record["confirmed_at"], record["source"], stamp, stamp,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_connectivity_profile(conn, subject_id)


def remove_connectivity_fields(conn, subject_id, fields=(), *, clear_all=False, confirmed=False):
    """Remove confirmed subject-scoped fields from the existing ledger."""
    subject_id = _connectivity_subject(subject_id)
    if confirmed is not True:
        raise ValueError("connectivity removal requires explicit confirmation")
    raw_fields = list(fields or ())
    if clear_all:
        if raw_fields:
            raise ValueError("clear_all cannot be combined with field names")
    elif not raw_fields:
        raise ValueError("at least one field is required unless clear_all is set")
    canonical = []
    for name in raw_fields:
        field = _canonical_connectivity_field(name)
        if field not in canonical:
            canonical.append(field)
    conn.execute("begin immediate")
    try:
        if clear_all:
            conn.execute("delete from connectivity_profiles where subject_id=?", (subject_id,))
        else:
            placeholders = ",".join("?" for _ in canonical)
            conn.execute(
                f"delete from connectivity_profiles where subject_id=? and field_name in ({placeholders})",
                (subject_id, *canonical),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_connectivity_profile(conn, subject_id)


def list_connectivity_profiles(conn):
    subjects = conn.execute(
        "select distinct subject_id from connectivity_profiles order by subject_id"
    ).fetchall()
    return [get_connectivity_profile(conn, row["subject_id"]) for row in subjects]


def connectivity_workload_data_estimate(stream_bitrate_mbps, hours_per_day):
    """Estimate decimal GB/day from supplied bitrate and hours; never observed usage."""
    if stream_bitrate_mbps is None or hours_per_day is None:
        return None
    bitrate = _validate_connectivity_value(stream_bitrate_mbps, "stream_bitrate_mbps")
    hours = _validate_connectivity_value(hours_per_day, "hours_per_day")
    if not isinstance(bitrate, (int, float)) or not isinstance(hours, (int, float)):
        raise ValueError("workload estimate inputs must be numeric")
    try:
        estimate = round(float(bitrate) * float(hours) * 0.45, 12)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(estimate):
        return None
    return {
        "label": "deterministic_workload_estimate",
        "estimate_gb_decimal_per_day": estimate,
        "unit": "GB_decimal_per_day",
        "is_estimate": True,
        "basis": {"stream_bitrate_mbps": bitrate, "hours_per_day": hours},
        "formula": "stream_bitrate_mbps * hours_per_day * 0.45",
    }


def _connectivity_subtract_calendar_months(value, months):
    year, month = value.year, value.month - months
    while month <= 0:
        year -= 1
        month += 12
    first_next = dt.date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    last_day = (first_next - dt.timedelta(days=1)).day
    return value.replace(year=year, month=month, day=min(value.day, last_day))


def connectivity_reddit_eligible(published_at, as_of):
    """Check an inclusive six-calendar-month publication window."""
    try:
        published = _connectivity_datetime(published_at, "published_at")
        reference = _connectivity_datetime(as_of, "as_of")
    except ValueError:
        return False
    if published > reference:
        return False
    lower = _connectivity_subtract_calendar_months(reference, 6)
    return lower <= published <= reference


def _connectivity_record_status(record, as_of, stale_days):
    if record is None or record.get("value") is None:
        return "missing", None
    try:
        confirmed = _connectivity_datetime(record.get("confirmed_at"), "confirmed_at")
    except ValueError:
        return "needs_confirmation", "invalid_timestamp"
    if confirmed > as_of:
        return "needs_confirmation", "future_timestamp"
    if as_of - confirmed > dt.timedelta(days=stale_days):
        return "stale", None
    return "current", None


def _connectivity_uses_contain(uses, terms):
    """Match whole words/phrases, so 'delivery apps' never matches 'live'."""
    values = [uses] if isinstance(uses, str) else uses if isinstance(uses, list) else []
    text = " ".join(item for item in values if isinstance(item, str)).lower()
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text)
    normalized = " " + " ".join(words) + " "
    return any(f" {term} " in normalized for term in terms)


def _connectivity_questions(unresolved, fields):
    questions = []

    def add(question, names):
        selected = [name for name in names if name in unresolved]
        if selected:
            questions.append({"fields": selected, "question": question})

    add("What device model, OS, region, and SIM-lock/eSIM capabilities should be supported?",
        ("device_model", "region", "carrier_unlocked", "esim_supported", "os"))
    add("Which countries and dates are in the trip?", ("trip_countries", "trip_start", "trip_end"))
    add("What connectivity do you already own, if any?", ("owned_connectivity",))
    add("What will the connection be used for?", ("uses",))
    uses_record = fields.get("uses")
    uses_value = uses_record.get("value") if isinstance(uses_record, dict) else None
    if _connectivity_uses_contain(uses_value, (
        "live", "livestream", "livestreaming", "live-stream", "live-streaming", "stream",
        "streaming", "broadcast", "broadcasting",
    )):
        add("For livestreaming, what direction, bitrate, and hours per day are required?",
            ("livestream_direction", "stream_bitrate_mbps", "hours_per_day"))
    if _connectivity_uses_contain(uses_value, (
        "hotspot", "tether", "tethering", "multi-device",
    )):
        add("How many hotspot devices need service?", ("hotspot_devices",))
    if uses_value is not None:
        add("If known, what actual observed data usage or allowance per day should we plan around? Leave it unknown if unmeasured; do not invent a budget.",
            ("data_gb_per_day",))
        add("What upload floor and maximum latency are acceptable?", ("min_upload_mbps", "max_latency_ms"))
    add("What budget currency and total budget should be respected?", ("budget_currency", "budget_total"))
    add("Can you carry a router, and what redundancy is required?", ("router_carry_ok", "redundancy"))
    return questions


def connectivity_intake_report(conn, subject_id, *, as_of, stale_days=CONNECTIVITY_DEFAULT_STALE_DAYS):
    """Classify profile facts without changing the profile or timestamps."""
    subject_id = _connectivity_subject(subject_id)
    as_of_dt = _connectivity_datetime(as_of, "as_of")
    if isinstance(stale_days, bool) or not isinstance(stale_days, (int, float)):
        raise ValueError("stale_days must be a finite non-negative number")
    if not math.isfinite(float(stale_days)) or float(stale_days) < 0:
        raise ValueError("stale_days must be a finite non-negative number")
    profile = get_connectivity_profile(conn, subject_id)
    fields = profile["fields"]
    missing, stale, needs_confirmation, current = [], [], [], []
    for field in CONNECTIVITY_FIELDS:
        status, reason = _connectivity_record_status(fields.get(field), as_of_dt, float(stale_days))
        if status == "missing":
            missing.append(field)
        elif status == "stale":
            stale.append(field)
        elif status == "needs_confirmation":
            needs_confirmation.append({"field": field, "reason": reason or "confirmation_required"})
        else:
            current.append(field)
    estimate = None
    bitrate = fields.get("stream_bitrate_mbps")
    hours = fields.get("hours_per_day")
    # Only derive from facts that are current; stale or unconfirmed inputs leave the
    # estimate unavailable instead of producing a normal-looking number.
    if (
        bitrate is not None and hours is not None
        and "stream_bitrate_mbps" in current and "hours_per_day" in current
    ):
        try:
            estimate = connectivity_workload_data_estimate(bitrate.get("value"), hours.get("value"))
        except ValueError:
            estimate = None
    unresolved = set(missing) | set(stale) | {item["field"] for item in needs_confirmation}
    return {
        "schema_version": CONNECTIVITY_SCHEMA_VERSION,
        "subject_id": subject_id,
        "as_of": as_of,
        "stale_days": float(stale_days),
        "missing": missing,
        "stale": stale,
        "needs_confirmation": needs_confirmation,
        "current": current,
        "questions": _connectivity_questions(unresolved, fields),
        "workload_estimate": estimate,
    }


def connectivity_profile_markdown(profile):
    lines = ["| Field | Value | Confirmed at | Source |", "|---|---|---|---|"]
    for field in CONNECTIVITY_FIELDS:
        if field not in profile.get("fields", {}):
            continue
        record = profile["fields"][field]
        cells = [field, json.dumps(record["value"], ensure_ascii=False, sort_keys=True), record["confirmed_at"], record["source"]]
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
    if len(lines) == 2:
        lines.append("| *(no confirmed fields)* | | | |")
    return "\n".join(lines)


def connectivity_intake_markdown(report):
    lines = ["| Status | Field | Detail |", "|---|---|---|"]
    for field in report.get("missing", []):
        lines.append(f"| missing | {field} | |")
    for field in report.get("stale", []):
        lines.append(f"| stale | {field} | confirmation is older than stale_days |")
    for item in report.get("needs_confirmation", []):
        lines.append(f"| needs confirmation | {item['field']} | {item['reason']} |")
    if len(lines) == 2:
        lines.append("| current | *(all tracked fields)* | |")
    if report.get("questions"):
        lines.extend(["", "Questions:"])
        lines.extend(f"- {item['question']}" for item in report["questions"])
    if report.get("workload_estimate"):
        lines.extend([
            "",
            "Workload estimate (not observed usage): "
            + json.dumps(report["workload_estimate"], ensure_ascii=False, sort_keys=True),
        ])
    return "\n".join(lines)


def _read_json_input(path):
    def reject_constant(value):
        raise ValueError(f"non-finite JSON number is not allowed: {value}")
    try:
        if path == "-":
            data = json.load(sys.stdin, parse_constant=reject_constant)
        else:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle, parse_constant=reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"cannot read connectivity input JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("connectivity input JSON must be an object")
    return data


def connectivity_upsert(args):
    conn = connect()
    profile = upsert_connectivity_fields(
        conn, args.subject_id, _read_json_input(args.input),
        confirmed_at=args.confirmed_at, source=args.source,
    )
    print_result(profile, args.json)


def connectivity_show(args):
    conn = connect()
    profile = get_connectivity_profile(conn, args.subject_id)
    if args.format == "markdown":
        print(connectivity_profile_markdown(profile))
    else:
        print_result(profile, True)


def connectivity_intake(args):
    conn = connect()
    report = connectivity_intake_report(
        conn, args.subject_id, as_of=args.as_of, stale_days=args.stale_days,
    )
    if args.format == "markdown":
        print(connectivity_intake_markdown(report))
    else:
        print_result(report, True)


def upsert_trip(args):
    conn = connect()
    t = now()
    fields = parse_fields(args.field)
    existing = conn.execute("select fields_json, created_at from trips where trip_id=?", (args.trip_id,)).fetchone()
    if existing:
        old = json.loads(existing["fields_json"] or "{}")
        old.update(fields)
        created_at = existing["created_at"]
    else:
        old = fields
        created_at = t
    conn.execute(
        """
        insert into trips (trip_id, title, status, fields_json, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?)
        on conflict(trip_id) do update set
          title=excluded.title,
          status=excluded.status,
          fields_json=excluded.fields_json,
          updated_at=excluded.updated_at
        """,
        (args.trip_id, args.title, args.status, json.dumps(old, sort_keys=True), created_at, t),
    )
    conn.commit()
    row = conn.execute("select * from trips where trip_id=?", (args.trip_id,)).fetchone()
    print_result(row_to_dict(row), args.json)


def upsert_action(args):
    conn = connect()
    t = now()
    action_id = args.action_id or f"{args.type}-{uuid.uuid4().hex[:10]}"
    fields = parse_fields(args.field)
    existing = conn.execute("select fields_json, created_at from actions where action_id=?", (action_id,)).fetchone()
    if existing:
        old = json.loads(existing["fields_json"] or "{}")
        old.update(fields)
        created_at = existing["created_at"]
    else:
        old = fields
        created_at = t
    conn.execute(
        """
        insert into actions (action_id, trip_id, action_type, provider, status, fields_json, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(action_id) do update set
          trip_id=excluded.trip_id,
          action_type=excluded.action_type,
          provider=excluded.provider,
          status=excluded.status,
          fields_json=excluded.fields_json,
          updated_at=excluded.updated_at
        """,
        (action_id, args.trip_id, args.type, args.provider, args.status, json.dumps(old, sort_keys=True), created_at, t),
    )
    conn.commit()
    row = conn.execute("select * from actions where action_id=?", (action_id,)).fetchone()
    print_result(row_to_dict(row), args.json)


def browser_checkpoint(args):
    conn = connect()
    t = now()
    checkpoint_id = args.checkpoint_id or f"browser-{uuid.uuid4().hex[:10]}"
    fields = parse_fields(args.field)
    conn.execute(
        """
        insert into browser_checkpoints
        (checkpoint_id, action_id, provider, lane, session_id, context_id, url, state, fields_json, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(checkpoint_id) do update set
          action_id=excluded.action_id,
          provider=excluded.provider,
          lane=excluded.lane,
          session_id=excluded.session_id,
          context_id=excluded.context_id,
          url=excluded.url,
          state=excluded.state,
          fields_json=excluded.fields_json,
          updated_at=excluded.updated_at
        """,
        (
            checkpoint_id,
            args.action_id,
            args.provider,
            args.lane,
            args.session_id,
            args.context_id,
            args.url,
            args.state,
            json.dumps(fields, sort_keys=True),
            t,
            t,
        ),
    )
    conn.commit()
    row = conn.execute("select * from browser_checkpoints where checkpoint_id=?", (checkpoint_id,)).fetchone()
    print_result(row_to_dict(row), args.json)


def payment_readiness(args):
    conn = connect()
    t = now()
    readiness_id = args.readiness_id or f"payment-{args.provider}-{uuid.uuid4().hex[:8]}"
    fields = parse_fields(args.field)
    conn.execute(
        """
        insert into payment_readiness
        (readiness_id, provider, status, descriptor, budget, currency, fields_json, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(readiness_id) do update set
          provider=excluded.provider,
          status=excluded.status,
          descriptor=excluded.descriptor,
          budget=excluded.budget,
          currency=excluded.currency,
          fields_json=excluded.fields_json,
          updated_at=excluded.updated_at
        """,
        (
            readiness_id,
            args.provider,
            args.status,
            args.descriptor,
            args.budget,
            args.currency,
            json.dumps(fields, sort_keys=True),
            t,
            t,
        ),
    )
    conn.commit()
    row = conn.execute("select * from payment_readiness where readiness_id=?", (readiness_id,)).fetchone()
    print_result(row_to_dict(row), args.json)


def latest(table, where=None, value=None):
    conn = connect()
    sql = f"select * from {table}"
    args = ()
    if where:
        sql += f" where {where}=?"
        args = (value,)
    sql += " order by updated_at desc limit 20"
    return [row_to_dict(r) for r in conn.execute(sql, args).fetchall()]


def summary(args):
    conn = connect()
    data = {
        "db": db_path(),
        "trips": [row_to_dict(r) for r in conn.execute("select * from trips order by updated_at desc limit 20")],
        "actions": [row_to_dict(r) for r in conn.execute("select * from actions order by updated_at desc limit 20")],
        "browser_checkpoints": [row_to_dict(r) for r in conn.execute("select * from browser_checkpoints order by updated_at desc limit 20")],
        "payment_readiness": [row_to_dict(r) for r in conn.execute("select * from payment_readiness order by updated_at desc limit 20")],
    }
    print_result(data, args.json)


def build_parser():
    p = argparse.ArgumentParser(description="Travel Action Pack durable trip/action ledger")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")

    trip = sub.add_parser("trip-upsert")
    trip.add_argument("--trip-id", required=True)
    trip.add_argument("--title", required=True)
    trip.add_argument("--status", default="planning")
    trip.add_argument("--field", action="append", default=[])
    trip.add_argument("--json", action="store_true")

    action = sub.add_parser("action-upsert")
    action.add_argument("--action-id")
    action.add_argument("--trip-id")
    action.add_argument("--type", required=True)
    action.add_argument("--provider", required=True)
    action.add_argument("--status", default="prepared")
    action.add_argument("--field", action="append", default=[])
    action.add_argument("--json", action="store_true")

    browser = sub.add_parser("browser-checkpoint")
    browser.add_argument("--checkpoint-id")
    browser.add_argument("--action-id")
    browser.add_argument("--provider", required=True)
    browser.add_argument("--lane", default="browserbase")
    browser.add_argument("--session-id", default="")
    browser.add_argument("--context-id", default="")
    browser.add_argument("--url", default="")
    browser.add_argument("--state", required=True)
    browser.add_argument("--field", action="append", default=[])
    browser.add_argument("--json", action="store_true")

    pay = sub.add_parser("payment-readiness")
    pay.add_argument("--readiness-id")
    pay.add_argument("--provider", required=True)
    pay.add_argument("--status", required=True, choices=["ready", "missing", "underfunded", "unknown", "blocked"])
    pay.add_argument("--descriptor", default="")
    pay.add_argument("--budget", default="")
    pay.add_argument("--currency", default="USD")
    pay.add_argument("--field", action="append", default=[])
    pay.add_argument("--json", action="store_true")

    connectivity = sub.add_parser("connectivity-upsert", help="merge dated allowlisted connectivity fields")
    connectivity.add_argument("--subject-id", required=True)
    connectivity.add_argument("--input", required=True, help="JSON object containing connectivity fields; use '-' to read stdin so no profile file is written")
    connectivity.add_argument("--confirmed-at", help="timezone-aware timestamp for raw values")
    connectivity.add_argument("--source", help="short source label for raw values")
    connectivity.add_argument("--json", action="store_true")

    show_connectivity = sub.add_parser("connectivity-show", help="read one connectivity profile")
    show_connectivity.add_argument("--subject-id", required=True)
    show_connectivity.add_argument("--format", choices=("json", "markdown"), default="json")

    intake = sub.add_parser("connectivity-intake", help="classify current, stale, and missing connectivity facts")
    intake.add_argument("--subject-id", required=True)
    intake.add_argument("--as-of", required=True, help="timezone-aware evaluation timestamp")
    intake.add_argument("--stale-days", type=float, default=CONNECTIVITY_DEFAULT_STALE_DAYS)
    intake.add_argument("--format", choices=("json", "markdown"), default="json")

    remove = sub.add_parser("connectivity-remove", help="remove confirmed subject-scoped connectivity fields")
    remove.add_argument("--subject-id", required=True)
    remove.add_argument("--field", action="append", default=[])
    remove.add_argument("--clear-all", action="store_true", help="remove every field for the subject")
    remove.add_argument("--confirm", action="store_true", help="confirm this destructive profile edit")
    remove.add_argument("--json", action="store_true")

    reddit = sub.add_parser("connectivity-reddit-eligible", help="check an inclusive six-calendar-month window")
    reddit.add_argument("--published-at", required=True)
    reddit.add_argument("--as-of", required=True)

    latest_cmd = sub.add_parser("latest")
    latest_cmd.add_argument("table", choices=["trips", "actions", "browser_checkpoints", "payment_readiness"])
    latest_cmd.add_argument("--provider")
    latest_cmd.add_argument("--trip-id")
    latest_cmd.add_argument("--json", action="store_true")

    s = sub.add_parser("summary")
    s.add_argument("--json", action="store_true")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "init":
        connect().close()
        print(db_path())
    elif args.cmd == "trip-upsert":
        upsert_trip(args)
    elif args.cmd == "action-upsert":
        upsert_action(args)
    elif args.cmd == "browser-checkpoint":
        browser_checkpoint(args)
    elif args.cmd == "payment-readiness":
        payment_readiness(args)
    elif args.cmd == "connectivity-upsert":
        connectivity_upsert(args)
    elif args.cmd == "connectivity-show":
        connectivity_show(args)
    elif args.cmd == "connectivity-intake":
        connectivity_intake(args)
    elif args.cmd == "connectivity-remove":
        conn = connect()
        profile = remove_connectivity_fields(
            conn, args.subject_id, args.field, clear_all=args.clear_all, confirmed=args.confirm,
        )
        print_result(profile, args.json)
    elif args.cmd == "connectivity-reddit-eligible":
        print_result({"eligible": connectivity_reddit_eligible(args.published_at, args.as_of)}, True)
    elif args.cmd == "latest":
        where = value = None
        if args.provider and args.table in ("actions", "browser_checkpoints", "payment_readiness"):
            where, value = "provider", args.provider
        if args.trip_id and args.table == "actions":
            where, value = "trip_id", args.trip_id
        print_result(latest(args.table, where, value), args.json)
    elif args.cmd == "summary":
        summary(args)


if __name__ == "__main__":
    main()
