"""Validated, profile-bound configuration and atomic watchdog state."""
from __future__ import annotations

import contextlib
import datetime as datetime_module
import fcntl
import json
import os
import secrets
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from .gog_collector import DailyOpsError

REQUIRED_TOP = ("tenant", "delivery", "timezone", "accounts")
_BOOL_FIELDS = (
    ("delivery", "verified"),
    ("travel", "leave_by"),
    ("travel.geocoder", "consent"),
    ("priority.connectors.clients_sync", "enabled"),
    ("priority.connectors.clients_sync", "consent"),
    ("priority.connectors.clients_sync", "stripe_live"),
    ("autoclean", "enabled"),
    ("calendar.read_scope", "accepted"),
    ("calendar.read_scope", "include_pa_binding"),
)


def config_path() -> str:
    value = os.environ.get("DAILY_OPS_CONFIG") or "daily_ops.config.json"
    if "\x00" in value:
        raise DailyOpsError("DAILY_OPS_CONFIG contains an invalid byte")
    return value


def config_dir(path: str | os.PathLike[str] | None = None) -> str:
    raw = Path(path or config_path()).expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    return str(raw.resolve().parent)


def load_config(path: str | os.PathLike[str] | None = None) -> dict:
    selected = Path(path or config_path()).expanduser()
    try:
        with selected.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise DailyOpsError("configuration is missing or invalid; repair the profile config") from exc
    if not isinstance(data, dict):
        raise DailyOpsError("configuration must be a JSON object")
    return data


def _lookup(data: dict, path: str):
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def _is_bool(value) -> bool:
    return isinstance(value, bool)


def validate_config(cfg: dict, *, require_profile: bool = False) -> list[str]:
    """Return actionable errors. JSON booleans are never coerced from strings."""
    errors: list[str] = []
    if not isinstance(cfg, dict):
        return ["configuration must be a JSON object"]
    for key in REQUIRED_TOP:
        if key not in cfg:
            errors.append(f"missing required section: {key}")

    tenant = cfg.get("tenant")
    if not isinstance(tenant, dict):
        errors.append("tenant must be an object")
        tenant = {}
    if not isinstance(tenant.get("profile_id"), str) or not tenant.get("profile_id").strip():
        errors.append("tenant.profile_id is required")
    if not isinstance(tenant.get("owner_email"), str) or "@" not in tenant.get("owner_email", ""):
        errors.append("tenant.owner_email must be an email address")

    delivery = cfg.get("delivery")
    if not isinstance(delivery, dict):
        errors.append("delivery must be an object")
        delivery = {}
    if not isinstance(delivery.get("target"), str) or not delivery.get("target").strip():
        errors.append("delivery.target is required")
    if delivery.get("verified") is not True:
        errors.append("delivery.verified must be the JSON boolean true before operation")

    timezone = cfg.get("timezone")
    if not isinstance(timezone, str) or not timezone.strip():
        errors.append("timezone must be an IANA name")
    else:
        try:
            ZoneInfo(timezone)
        except Exception:
            errors.append(f"timezone '{timezone}' is not a valid IANA zone name")

    accounts = cfg.get("accounts")
    if not isinstance(accounts, dict):
        errors.append("accounts must be an object")
        accounts = {}
    work = accounts.get("work")
    personal = accounts.get("personal")
    if not isinstance(work, str) or "@" not in work:
        errors.append("accounts.work must be the primary account email")
    if personal is not None and (not isinstance(personal, str) or "@" not in personal):
        errors.append("accounts.personal must be an email address or null")

    calendar = cfg.get("calendar")
    if calendar is not None:
        if not isinstance(calendar, dict):
            errors.append("calendar must be an object")
            calendar = {}
        if calendar.get("provider") not in {"profile_google", "gog"}:
            errors.append("calendar.provider must be profile_google or gog")
        calendar_account = calendar.get("account")
        if calendar_account is not None and (not isinstance(calendar_account, str) or "@" not in calendar_account):
            errors.append("calendar.account must be an email address or omitted")
        read_scope = calendar.get("read_scope")
        if not isinstance(read_scope, dict):
            errors.append("calendar.read_scope must be an object")
            read_scope = {}
        if read_scope.get("accepted") is not True:
            errors.append("calendar.read_scope.accepted must be the JSON boolean true")
        calendar_ids = read_scope.get("calendar_ids")
        if not isinstance(calendar_ids, list) or any(
            not isinstance(value, str) or not value.strip() for value in (calendar_ids or [])
        ):
            errors.append("calendar.read_scope.calendar_ids must be a list of calendar IDs")
        elif not calendar_ids and read_scope.get("include_pa_binding") is not True:
            errors.append("calendar.read_scope must include a calendar ID or the accepted PA binding")

    for section, field in _BOOL_FIELDS:
        value = _lookup(cfg, f"{section}.{field}")
        if value is not None and not _is_bool(value):
            errors.append(f"{section}.{field} must be a JSON boolean")

    travel = cfg.get("travel") or {}
    if not isinstance(travel, dict):
        errors.append("travel must be an object")
        travel = {}
    geo = travel.get("geocoder") or {}
    if not isinstance(geo, dict):
        errors.append("travel.geocoder must be an object")
        geo = {}
    if travel.get("leave_by") is True and geo.get("consent") is not True:
        errors.append("travel.leave_by=true requires travel.geocoder.consent=true")
    for name in ("buffer_min", "heads_up_min"):
        if name in travel and (not isinstance(travel[name], int) or isinstance(travel[name], bool) or travel[name] < 0):
            errors.append(f"travel.{name} must be a non-negative integer")

    autoclean = cfg.get("autoclean")
    if autoclean is not None:
        if not isinstance(autoclean, dict):
            errors.append("autoclean must be an object")
        elif autoclean.get("enabled") is True:
            errors.append("autoclean is unsupported: daily-ops never mutates mail")
        if isinstance(autoclean, dict) and "dry_run_ticks" in autoclean:
            ticks = autoclean["dry_run_ticks"]
            if not isinstance(ticks, int) or isinstance(ticks, bool):
                errors.append("autoclean.dry_run_ticks must be an integer")

    priority = cfg.get("priority")
    if priority is not None and not isinstance(priority, dict):
        errors.append("priority must be an object")
        priority = {}
    priority = priority or {}
    if "static_terms" in priority and (not isinstance(priority["static_terms"], list) or any(not isinstance(term, str) for term in priority["static_terms"])):
        errors.append("priority.static_terms must be a list of strings")
    connector = (((priority.get("connectors") or {}).get("clients_sync"))
                 if isinstance(priority.get("connectors"), dict) else None)
    if connector is not None:
        if not isinstance(connector, dict):
            errors.append("priority.connectors.clients_sync must be an object")
            connector = {}
        if connector.get("enabled") is True:
            if connector.get("consent") is not True:
                errors.append("clients_sync.enabled=true requires consent=true")
            if not connector.get("stripe_account") and not connector.get("supabase_ref"):
                errors.append("clients_sync.enabled=true requires a Stripe account or Supabase project")
            if connector.get("client_max_age_h") is not None:
                age = connector["client_max_age_h"]
                if not isinstance(age, int) or isinstance(age, bool) or age < 1 or age > 720:
                    errors.append("clients_sync.client_max_age_h must be an integer from 1 to 720")

    schedules = cfg.get("schedules") or {}
    if travel.get("leave_by") is True:
        watchdog = schedules.get("watchdog")
        if not isinstance(watchdog, str) or not _cadence_minutes(watchdog) or _cadence_minutes(watchdog) > 20:
            errors.append("schedules.watchdog must run every 20 minutes or less when leave_by is enabled")

    if require_profile:
        try:
            profile_root()
        except DailyOpsError as exc:
            errors.append(str(exc))
    return errors


def _cadence_minutes(expression: str) -> int | None:
    # Deliberately only accepts the portable minute-step form used by the docs.
    import re
    match = re.fullmatch(r"\*/(\d+) \* \* \* \*", expression.strip())
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def validate_or_raise(cfg: dict) -> dict:
    errors = validate_config(cfg, require_profile=True)
    try:
        root = profile_root()
        configured = Path(config_path()).expanduser()
        if not configured.is_absolute():
            configured = Path.cwd() / configured
        configured = configured.resolve()
        configured.relative_to(root)
        expected_profile = os.environ.get("DAILY_OPS_PROFILE_ID")
        actual_profile = (cfg.get("tenant") or {}).get("profile_id")
        if expected_profile and actual_profile != expected_profile:
            errors.append("tenant.profile_id does not match the active profile")
    except (DailyOpsError, ValueError):
        # profile errors are already included by validate_config when requested;
        # containment is an additional fail-closed check.
        errors.append("DAILY_OPS_CONFIG must resolve inside the active profile")
    if errors:
        raise DailyOpsError("invalid configuration: " + "; ".join(dict.fromkeys(errors)))
    return cfg


def profile_root() -> Path:
    raw = os.environ.get("DAILY_OPS_PROFILE_ROOT") or os.environ.get("HERMES_HOME")
    if not raw:
        raise DailyOpsError("set DAILY_OPS_PROFILE_ROOT or HERMES_HOME; profile binding is required")
    if "\x00" in raw:
        raise DailyOpsError("profile root contains an invalid byte")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise DailyOpsError("profile root must be absolute")
    try:
        if path.is_symlink() or not path.is_dir():
            raise DailyOpsError("profile root must be an existing directory, not a symlink")
        if path.stat().st_mode & 0o022:
            raise DailyOpsError("profile root must not be group/world writable")
        return path.resolve(strict=True)
    except OSError as exc:
        raise DailyOpsError("profile root cannot be inspected") from exc


def state_path(root: str | os.PathLike[str] | None = None) -> Path:
    profile = Path(root).expanduser().resolve() if root else profile_root()
    raw = os.environ.get("DAILY_OPS_STATE")
    candidate = Path(raw).expanduser() if raw else profile / "state" / "daily-ops" / "state.json"
    if not candidate.is_absolute():
        candidate = profile / candidate
    candidate = Path(os.path.abspath(os.fspath(candidate)))
    try:
        candidate.relative_to(profile)
    except ValueError as exc:
        raise DailyOpsError("DAILY_OPS_STATE must remain inside the active profile") from exc
    current = profile
    for part in candidate.relative_to(profile).parts:
        current = current / part
        try:
            if current.is_symlink():
                raise DailyOpsError("daily-ops state path must not contain symlinks")
        except OSError as exc:
            raise DailyOpsError("daily-ops state path cannot be inspected") from exc
    return candidate


def _ensure_private_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.parent.is_symlink():
        raise DailyOpsError("daily-ops state directory must not be a symlink")


def _read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise DailyOpsError("daily-ops state is corrupt; refusing to reset dedup or consent") from exc
    if not isinstance(data, dict):
        raise DailyOpsError("daily-ops state must be a JSON object")
    return data


def load_state(path: str | os.PathLike[str] | None = None) -> dict:
    selected = Path(path).expanduser() if path else state_path()
    return _read_state(selected)


def _atomic_write(path: Path, state: dict) -> None:
    _ensure_private_parent(path)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    try:
        fd = os.open(os.fspath(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except (OSError, TypeError, ValueError) as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise DailyOpsError("daily-ops state could not be written atomically") from exc


def save_state(state: dict, path: str | os.PathLike[str] | None = None) -> None:
    selected = Path(path).expanduser() if path else state_path()
    if not isinstance(state, dict):
        raise DailyOpsError("daily-ops state must be a JSON object")
    _atomic_write(selected, state)


@contextlib.contextmanager
def state_transaction(path: str | os.PathLike[str] | None = None) -> Iterator[dict]:
    selected = Path(path).expanduser() if path else state_path()
    _ensure_private_parent(selected)
    lock_path = selected.with_name(selected.name + ".lock")
    try:
        fd = os.open(os.fspath(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        os.chmod(lock_path, 0o600)
    except OSError as exc:
        raise DailyOpsError("daily-ops state lock could not be opened") from exc
    try:
        with os.fdopen(fd, "r+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = _read_state(selected)
            yield state
            _atomic_write(selected, state)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except DailyOpsError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise DailyOpsError("daily-ops state transaction failed") from exc


# Kept for callers that want to validate an old, unrelated approval object. Daily
# ops itself never calls it because mailbox mutation is explicitly unsupported.
def _approval_valid(approval, now_iso=None) -> bool:
    if not isinstance(approval, dict):
        return False
    try:
        granted = datetime_module.datetime.fromisoformat(str(approval["granted_at"]).replace("Z", "+00:00"))
        expires = datetime_module.datetime.fromisoformat(str(approval["expires_at"]).replace("Z", "+00:00"))
        now = datetime_module.datetime.fromisoformat(now_iso.replace("Z", "+00:00")) if now_iso else datetime_module.datetime.now(datetime_module.timezone.utc)
        cap = approval["per_run_cap"]
        return isinstance(cap, int) and not isinstance(cap, bool) and 1 <= cap <= 50 and granted <= now < expires
    except (KeyError, TypeError, ValueError):
        return False
