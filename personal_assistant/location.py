"""Read-only timezone evidence from recorded flights and the owner's home zone."""
import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .trip_facts import SCHEDULE, _time


def _zone(value):
    try:
        return ZoneInfo(value) if isinstance(value, str) else None
    except (ValueError, ZoneInfoNotFoundError):
        return None


def timezone_check(ledger, moment) -> dict | None:
    """Suggest a zone only when nearby evidence disagrees with the stored clock."""
    moment = moment.astimezone(dt.timezone.utc)
    prefs = (ledger.get("action", "pa:preferences") or {}).get("fields", {})
    stored, home = _zone(prefs.get("timezone")), _zone(prefs.get("home_timezone"))
    segments = []
    for action in ledger.list("action"):
        if not action["action_id"].startswith("pa:trip-facts:"):
            continue
        fields = action.get("fields", {})
        raw = fields.get("segments") if isinstance(fields, dict) else None
        for seg in raw if isinstance(raw, list) else []:
            if not isinstance(seg, dict) or seg.get("status") == "cancelled" or seg.get("source") == "simulated":
                continue
            try:
                if any(not isinstance(seg.get(k), str) or not seg[k] for k in (*SCHEDULE, "segment_id")):
                    continue
                origin, destination = _zone(seg["origin_timezone"]), _zone(seg["destination_timezone"])
                departure = _time(seg.get("estimated_departure", seg["scheduled_departure"]))
                arrival = _time(seg.get("estimated_arrival", seg["scheduled_arrival"]))
                if origin is None or destination is None or arrival < departure:
                    continue
            except (ValueError, TypeError, AttributeError, OverflowError):
                continue
            segments.append((seg, departure, arrival, origin, destination))
    if any(departure <= moment < arrival for _, departure, arrival, _, _ in segments):
        return None
    landed = max((s for s in segments if s[2] <= moment), key=lambda s: s[2], default=None)
    if landed and any(s is not landed and landed[2] <= s[1] <= landed[2] + dt.timedelta(hours=24)
                      and s[1] > moment and (s[0]["origin"] == landed[0]["destination"]
                      or s[3] == landed[4]) for s in segments):
        return None  # Still between connecting legs; do not adopt the stopover's clock.
    departing = min((s for s in segments if s[1] > moment), key=lambda s: s[1], default=None)
    candidates = []
    for kind, segment, index in (("landed", landed, 2), ("departing", departing, 1)):
        if segment:
            distance = abs(moment - segment[index])
            if distance <= dt.timedelta(days=30):
                candidates.append((distance, kind, segment))
    if candidates:
        _, kind, (seg, departure, arrival, origin, destination) = min(candidates, key=lambda s: s[0])
        zone = destination if kind == "landed" else origin
        at, airport = (arrival, seg["destination"]) if kind == "landed" else (departure, seg["origin"])
        key = kind + ":" + seg["segment_id"]
        evidence = {"kind": kind, "segment_id": seg["segment_id"], "flight": seg["carrier"] + seg["number"],
                    "airport": airport, "at": at.astimezone(zone).isoformat()}
    elif home:
        zone, key, evidence = home, "home:" + str(home), {"kind": "home"}
    else:
        return None
    if (stored and moment.astimezone(stored).utcoffset() == moment.astimezone(zone).utcoffset()
            or prefs.get("timezone_kept") == key):
        return None
    return {"radar_kind": "timezone_check", "action_id": "pa:preferences",
            "stored": str(stored) if stored else None, "suggested": str(zone),
            "evidence": evidence, "evidence_key": key, "surfaced": True,
            # Switch without asking only on a fresh landing; older evidence may predate the owner's own correction.
            "switch": evidence["kind"] == "landed" and moment - arrival <= dt.timedelta(hours=48)}
