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


def _next_journey(all_segments, current):
    """The next departure plus segments within 24 h of it (connections, rebooked alternatives).

    A flight back to the journey's origin, or one more than 24 h later, starts a later journey."""
    ordered = sorted(all_segments, key=lambda s: _time(s["scheduled_departure"]))
    upcoming = [s for s in ordered if _time(s["scheduled_departure"]) >= current] or ordered
    journey = upcoming[:1]
    for s in upcoming[1:]:
        if (_time(s["scheduled_departure"]) - _time(journey[-1]["scheduled_arrival"]) > dt.timedelta(hours=24)
                or s["destination"] == journey[0]["origin"]):
            break
        journey.append(s)
    return journey


def _latest_arrival(leg):
    scheduled = _time(leg["scheduled_arrival"])
    estimated = leg.get("estimated_arrival")
    return max(scheduled, _time(estimated)) if estimated else scheduled


def _in_progress_journeys(segments, current, *, first_watched=None):
    """Yield unfinished journeys in scheduled order, optionally starting at the watched part of each."""
    remaining = sorted(segments, key=lambda s: _time(s["scheduled_departure"]))
    floor = _time(first_watched["scheduled_departure"]) if first_watched is not None else None
    while remaining:
        scheduled_start = _time(remaining[0]["scheduled_departure"])
        journey = _next_journey(remaining, scheduled_start)
        remaining = remaining[len(journey):]
        # Keep the cutoff from the full itinerary, even for a watch that began during a layover.
        if remaining and current >= _time(remaining[0]["scheduled_departure"]):
            continue
        if floor is not None:
            # A same-origin replacement can leave earlier than the leg it replaces.
            start = next((i for i, leg in enumerate(journey)
                          if _time(leg["scheduled_departure"]) >= floor or leg["origin"] == first_watched["origin"]),
                         len(journey))
            journey = journey[start:]
        for leg in journey:
            if leg.get("status") in {"cancelled", "landed"}:
                continue
            departure = _time(leg["scheduled_departure"])
            if leg.get("estimated_departure"):
                departure = min(departure, _time(leg["estimated_departure"]))
            # Only a sign the flight is not over (departed, delayed, diverted, or an estimate) earns the grace;
            # a plain "scheduled" or "unknown" leg is taken as landed at its scheduled arrival.
            disrupted = (leg.get("status") in {"departed", "delayed", "diverted"}
                         or leg.get("estimated_departure") or leg.get("estimated_arrival"))
            if departure <= current < _latest_arrival(leg) + (dt.timedelta(hours=6) if disrupted else dt.timedelta(0)):
                yield journey
                break


def journey_start(segments, current):
    """Scheduled start of the latest unfinished journey, or None if none qualifies."""
    return max((_time(journey[0]["scheduled_departure"]) for journey in _in_progress_journeys(segments, current)),
               default=None)


def itinerary(facts):
    """The planned itinerary only: estimates, status and terminals are flight changes, not trip changes."""
    return sorted([s.get(k) for k in ("segment_id", "carrier", "number", "origin", "destination", "scheduled_departure",
                                      "scheduled_arrival")] + [s.get("status") == "cancelled"] for s in facts.get("segments", []))


def watched_journey(segments, departure_at, planned_ids):
    planned_departures = (_time(s["scheduled_departure"]) for s in segments if s["segment_id"] in planned_ids)
    start = min(planned_departures, default=departure_at - dt.timedelta(minutes=45))
    return _next_journey(segments, start)


def journey_itinerary(segments, departure_at, planned_ids):
    return itinerary({"segments": watched_journey(segments, departure_at, planned_ids)})


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


def transfer_for(record, segment) -> int | None:
    """Transfer minutes that apply to this departure, or None.

    A transfer belongs to the departure it was given for: its origin airport when bound, otherwise
    the recorded departure_at within 45 minutes. It never carries to another leg."""
    minutes = record.get("airport_transfer_minutes")
    if minutes is None:
        return None
    segment = segment or {}
    if record.get("airport_transfer_origin"):
        return minutes if record["airport_transfer_origin"] == segment.get("origin") else None
    leg, given = segment.get("scheduled_departure"), record.get("departure_at")
    if not leg:
        return minutes
    return minutes if given and abs(_time(leg) - _time(given)) <= dt.timedelta(minutes=45) else None


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
