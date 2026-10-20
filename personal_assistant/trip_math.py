"""Assumption-labelled trip timing, independent of the ledger and providers."""
import datetime as dt
from zoneinfo import ZoneInfo

WEATHER_EXTRA_MINUTES = {"clear": 0, "gusts": 15, "heavy rain": 30, "freezing": 30, "thunderstorm": 30, "snow": 45}
ARRIVAL_DEFAULTS = {"processing_minutes": 45, "transfer_minutes": 60, "buffer_minutes": 15}


def _time(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("trip times must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _minutes(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("minutes must be a nonnegative integer")
    return value


def _zone(name):
    if name.startswith(("UTC+", "UTC-")):
        return dt.datetime.fromisoformat("2000-01-01T00:00:00" + name[3:]).tzinfo
    return ZoneInfo(name)


def at_airport_by(departure, lead_minutes, origin_tz, *, estimated=None, severity=None, included_minutes=0) -> dict:
    scheduled = _time(departure)
    base = _time(estimated) if estimated else scheduled
    lead = _minutes(lead_minutes)
    included = _minutes(included_minutes)
    extra = max(0, WEATHER_EXTRA_MINUTES.get(severity, 0) - included)
    local = (base - dt.timedelta(minutes=lead + extra)).astimezone(_zone(origin_tz))
    local = local.replace(minute=local.minute // 5 * 5, second=0, microsecond=0)
    return {"at": local.isoformat(), "local_time": local.strftime("%H:%M"), "timezone": origin_tz,
            "basis": "estimated" if estimated else "scheduled", "lead_minutes": lead,
            "weather_extra_minutes": extra, "weather_included_minutes": included, "severity": severity or None,
            "assumed": ["weather_extra_minutes"] if extra else []}


def leave_by(departure, lead_minutes, origin_tz, transfer_minutes, **kwargs) -> dict:
    airport = at_airport_by(departure, lead_minutes, origin_tz, **kwargs)
    local = (_time(airport["at"]) - dt.timedelta(minutes=_minutes(transfer_minutes))).astimezone(_zone(origin_tz))
    local = local.replace(minute=local.minute // 5 * 5, second=0, microsecond=0)
    return {**airport, "at": local.isoformat(), "local_time": local.strftime("%H:%M"),
            "transfer_minutes": transfer_minutes, "transfer_source": "recorded",
            "at_airport_by": {k: airport[k] for k in ("at", "local_time")}}


def feasibility(arrival, commitment_at, destination_tz, *, estimated=None, status=None,
                processing_minutes=None, transfer_minutes=None, buffer_minutes=None) -> dict:
    if status in {"cancelled", "canceled", "diverted"}:
        return {"reachable": None, "reason": status}
    scheduled, commitment = _time(arrival), _time(commitment_at)
    landing = _time(estimated) if estimated else scheduled
    values = dict(processing_minutes=processing_minutes, transfer_minutes=transfer_minutes, buffer_minutes=buffer_minutes)
    assumed = [key for key, value in values.items() if value is None]
    values = {key: _minutes(ARRIVAL_DEFAULTS[key] if value is None else value) for key, value in values.items()}
    ready = landing + dt.timedelta(minutes=values["processing_minutes"] + values["transfer_minutes"])
    slack = int((commitment - ready).total_seconds() // 60)
    reachable = slack >= values["buffer_minutes"]
    alternatives = (["tell_them_you_will_be_late", "move_the_commitment", "go_direct_from_airport"] if not reachable
                    else ["go_direct_from_airport"] if slack < values["buffer_minutes"] + 30 else [])
    local = ready.astimezone(_zone(destination_tz))
    return {"reachable": reachable, "basis": "estimated" if estimated else "scheduled",
            "landing_at": landing.isoformat(), "ready_at": local.isoformat(), "ready_local_time": local.strftime("%H:%M"),
            "commitment_at": commitment.isoformat(), "slack_minutes": slack, **values,
            "assumed": assumed, "alternatives": alternatives, "timezone": destination_tz}


def recent_severity(weather, current):
    last = weather.get("last", {})
    return last.get("severity") if last.get("at") and dt.timedelta(0) <= current - _time(last["at"]) <= dt.timedelta(hours=3) else None
