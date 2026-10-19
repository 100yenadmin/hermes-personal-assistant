"""Isolated HeartBeat probe with ledger-owned baselines and bounded notices."""
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import unicodedata
import uuid
from zoneinfo import ZoneInfo

from .state import Ledger
from .privacy import clean
from . import observe_sources as sources
from . import trip_math

UTC = dt.timezone.utc


def instant(value):
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("offset required")
    return result


def fields(ledger, identity):
    return (ledger.get("action", identity) or {}).get("fields", {})


def read(conn, identity):
    row = conn.execute("select fields_json from actions where action_id=?", (identity,)).fetchone()
    return json.loads(row[0]) if row else {}


def write(conn, identity, data, kind, trip, stamp):
    conn.execute("insert into actions values(?,?,?,?,?,?,?,?) on conflict(action_id) do update set "
                 "fields_json=excluded.fields_json,updated_at=excluded.updated_at",
                 (identity, trip, kind, "", "active", json.dumps(clean(data)), stamp, stamp))


def ack(ledger, watch_id, notice_id):
    """Merge an acknowledgment without racing a probe or another ack."""
    identity = "pa:observe-control:" + watch_id
    stamp = dt.datetime.now(UTC).isoformat()
    with ledger.connect() as conn:
        conn.execute("begin immediate")
        data = read(conn, identity)
        data.setdefault("acks", {})[notice_id] = stamp
        write(conn, identity, data, "observe_control", None, stamp)


def quiet(watch, now):
    window = watch.get("hb2_quiet_hours", "22:00-08:00")
    if not window:
        return False
    a, b = (dt.time.fromisoformat(x) for x in window.split("-"))
    clock = now.astimezone(ZoneInfo(watch.get("hb2_timezone") or "UTC")).time().replace(tzinfo=None)
    return a <= clock < b if a < b else (clock >= a or clock < b) if a != b else False


def safe(value, limit):
    text = "".join(" " if unicodedata.category(c).startswith("C") else c for c in str(clean(str(value))))
    for char in '<>&⟦':
        text = text.replace(char, " ")
    return " ".join(text.split()).encode()[:limit].decode("utf-8", errors="ignore")


def local(value, zone):
    return instant(value).astimezone(ZoneInfo(zone or "UTC")).isoformat(timespec="minutes")


def message(watch, notice, facts, now):
    trip = json.dumps(watch["trip_id"], ensure_ascii=False)
    for char in '<>&⟦':
        trip = trip.replace(char, f"\\u{ord(char):04x}")
    display = json.dumps(safe(watch["trip_id"], 64), ensure_ascii=False)
    source = safe(", ".join(dict.fromkeys(str(s.get("source", "ledger")) for s in facts.get("segments", []))) or "ledger", 40)
    observed = [instant(s["observed_at"]) for s in facts.get("segments", []) if s.get("observed_at")]
    stamp = max(observed).astimezone(UTC) if observed else now
    prefix = f'Trip watch {display} · notice {notice["id"]}\n'
    suffix = (f'. Source: {source} {stamp:%H:%MZ}.\nNext: load skill personal-assistant:trip-concierge; '
              f'run pa trip_offer check trip_id={trip} offer_type={notice["offer_type"]} '
              f'occurrence={notice["id"]} before messaging.')
    room = 800 - len((prefix + suffix).encode())
    if room < 40:
        raise ValueError("trip identity exceeds message budget")
    return prefix + safe("; ".join(notice["signals"]), min(260, room)) + suffix


def itinerary(facts):
    """The planned itinerary only: estimates, status and terminals are flight changes, not trip changes."""
    return sorted([s.get(k) for k in ("segment_id", "carrier", "number", "origin", "destination", "scheduled_departure",
                                      "scheduled_arrival")] + [s.get("status") == "cancelled"] for s in facts.get("segments", []))


def flight_changes(watch, facts, state, settings, now, is_quiet):
    notified = state.setdefault("flight", {}).setdefault("notified", {k: {} for k in ("out", "in", "status", "terminal")})
    signals, updates, critical = [], [], False
    for index, segment in enumerate(facts.get("segments", [])):
        sid = str(segment.get("segment_id", index))
        label = safe(str(segment.get("carrier", "")) + str(segment.get("number", sid)), 24)
        for key, scheduled, estimated, threshold, zone in (
            ("out", "scheduled_departure", "estimated_departure", float(settings.get("delay_minutes", 20)), "origin_timezone"),
            ("in", "scheduled_arrival", "estimated_arrival", 30, "destination_timezone")):
            baseline = notified[key].setdefault(sid, segment[scheduled])
            current = segment.get(estimated) or segment[scheduled]
            delta = abs((instant(current) - instant(baseline)).total_seconds()) / 60
            delay = (instant(current) - instant(segment[scheduled])).total_seconds() / 60
            urgent = delay >= 60 and abs((instant(segment["scheduled_departure"]) - now).total_seconds()) <= 12 * 3600
            if delta >= threshold and (key == "out" or now >= instant(segment["scheduled_departure"])) and (not is_quiet or urgent):
                signals.append(f'{label} {key} {local(baseline, segment.get(zone))}→{local(current, segment.get(zone))}')
                if key == "out":
                    leave = trip_math.leave_by(segment[scheduled], watch.get("airport_lead_minutes", 180), segment[zone],
                                              estimated=current, severity=trip_math.recent_severity(state.get("weather", {}), now),
                                              included_minutes=watch.get("weather_included_minutes") or 0)
                    extra = leave["weather_extra_minutes"]
                    signals.append(f'Leave by {leave["local_time"]}' + (f' (+{extra} min for {leave["severity"]})' if extra else ""))
                updates.append((key, sid, current))
                critical |= urgent
        previous = notified["status"].setdefault(sid, "scheduled")
        status = str(segment.get("status", "scheduled")).lower()
        if status != previous and status in {"cancelled", "canceled", "diverted"}:
            signals.append(f"{label} status {previous}→{status}")
            updates.append(("status", sid, status))
            critical = True
        elif status not in {"cancelled", "canceled", "diverted"}:
            notified["status"][sid] = status
        terminals = {k: segment.get("terminal_" + k) for k in ("departure", "arrival")}
        old = notified["terminal"].setdefault(sid, terminals.copy())
        for key, value in terminals.items():
            if old.get(key) is None:
                old[key] = value
            elif value is not None and old[key] != value and not is_quiet:
                signals.append(f"{label} terminal {key} {old[key]}→{value}")
                updates.append(("terminal", sid, {**old, **{k: v for k, v in terminals.items() if v is not None}}))
    return signals, updates, critical


def probe(ledger, watch_id, watch, settings, deadline, started):
    now = dt.datetime.now(UTC)
    stamp = now.isoformat()
    departure, arrival = instant(watch["departure_at"]), instant(watch["arrival_at"])
    checks = watch.get("checks", {})
    flight_due = checks.get("flight") and departure - dt.timedelta(hours=float(settings.get("flight_window_hours", 24))) <= now <= arrival + dt.timedelta(hours=3)
    weather_due = checks.get("weather") and settings.get("weather_provider", "open_meteo") != "off" and departure - dt.timedelta(hours=float(settings.get("weather_window_hours", 48))) <= now <= departure
    identity = "pa:observe:" + watch_id
    initial = fields(ledger, identity)
    result, error, usage = None, None, {}
    coords = dict(initial.get("weather", {}).get("coords") or {})
    if weather_due:
        leave = departure - dt.timedelta(minutes=float(watch.get("airport_lead_minutes", 120)) + 60)
        try:
            result = sources.weather(settings, watch.get("origin", {}), coords,
                                     leave.timestamp(), departure.timestamp(), deadline, usage)
        except sources.ProviderError as exc:
            error = str(exc)
    # Network is complete. Re-read all decision inputs under the emission lock.
    with ledger.connect() as conn:
        conn.execute("begin immediate")
        watch = read(conn, "pa:observe-watch:" + watch_id)
        if watch.get("profile_root") != str(ledger.root):
            raise ValueError("profile mismatch")
        if watch.get("status") in {"cancelled", "canceled", "ended", "completed"}:
            return {"fire": False, "message": "", "state": {"watch": watch_id}}
        facts = read(conn, "pa:trip-facts:" + watch["trip_id"])
        state = read(conn, identity) or {"schema": 1, "trip_id": watch["trip_id"], "notices": [], "usage": {}}
        control = read(conn, "pa:observe-control:" + watch_id)
        is_quiet = quiet(watch, now)
        signals, offer, critical, updates = [], "trip_change", False, []
        revision, plan = facts.get("revision"), itinerary(facts)
        changed_trip = checks.get("trip_change") and revision != state.get("facts_revision")
        # Back on plan is news only when the traveller was told about a different itinerary.
        announced, back_to_plan = state.get("facts_itinerary"), facts.get("digest") == watch.get("planned_facts_digest")
        if changed_trip and (plan == announced or back_to_plan and announced is None):
            state["facts_revision"], state["facts_itinerary"] = revision, plan
            changed_trip = False
        if changed_trip and not is_quiet:
            signals.append("Trip is back to the planned itinerary" if back_to_plan else "Trip facts changed from the planned itinerary")
        if flight_due:
            flight = state.setdefault("flight", {})
            flight["checked_at"] = stamp
            flight_signals, updates, critical = flight_changes(watch, facts, state, settings, now, is_quiet)
            signals += flight_signals
            if flight_signals and (not changed_trip or is_quiet):
                offer = "flight_change"
        weather = state.setdefault("weather", {})
        severity, attention = None, False
        weather_extra_minutes = None
        if weather_due:
            weather["checked_at"] = stamp
            if coords:
                weather["coords"] = coords
            if error:
                weather["clear_streak"] = 0
                previous = weather.get("error", {})
                weather["error"] = {"kind": error, "at": stamp, "streak": previous.get("streak", 0) + 1,
                                    "attention": previous.get("attention", False)}
                attention = weather["error"]["streak"] >= 8 and dt.timedelta(0) <= departure - now <= dt.timedelta(hours=6) and not weather["error"]["attention"]
                if attention and not is_quiet:
                    signals.append("Weather watch needs attention after repeated provider errors")
                    if not signals[:-1]:
                        offer = "watch_attention"
            else:
                weather.pop("error", None)
                weather["coords"], severity = result
                weather["last"] = {"severity": severity, "at": stamp}
                old = weather.setdefault("notified", {}).setdefault("severity", "clear")
                weather["clear_streak"] = weather.get("clear_streak", 0) + 1 if severity == "clear" else 0
                if not is_quiet and (sources.SEVERITIES.index(severity) > sources.SEVERITIES.index(old) or severity == "clear" and old != "clear" and weather["clear_streak"] >= 2):
                    signals.append(f"Weather {old}→{severity if severity != 'clear' else 'cleared'}")
                    if not signals[:-1]:
                        offer = "weather_leave_early"
                    if severity != "clear":
                        try:
                            leave = trip_math.leave_by(watch["departure_at"], watch.get("airport_lead_minutes", 180),
                                                      watch["origin"]["tz"], severity=severity,
                                                      included_minutes=watch.get("weather_included_minutes") or 0)
                            weather_extra_minutes = leave["weather_extra_minutes"]
                            signals.append(f'Leave by {leave["local_time"]} (+{leave["weather_extra_minutes"]} min for {severity})')
                        except (KeyError, ValueError, TypeError):
                            pass
                else:
                    severity = None
        notice = None
        if signals and (not is_quiet or critical):
            notice = {"id": "n_" + uuid.uuid4().hex[:8], "signals": [safe(s, 400) for s in signals],
                      "offer_type": offer, "first_at": stamp, "last_at": stamp, "emits": 1}
            if weather_extra_minutes is not None:
                notice["weather_extra_minutes"] = weather_extra_minutes
            state["notices"] = (state.get("notices", []) + [notice])[-10:]
            if changed_trip and not is_quiet:
                state["facts_revision"], state["facts_itinerary"] = revision, plan
            for key, sid, value in updates:
                state["flight"]["notified"][key][sid] = value
            if severity is not None:
                weather["notified"]["severity"] = severity
            if attention and not is_quiet:
                weather["error"]["attention"] = True
        elif not is_quiet:
            for pending in state.get("notices", []):
                if pending["id"] not in control.get("acks", {}) and pending["emits"] < 3 and (now - instant(pending["last_at"])).total_seconds() >= float(settings.get("reemit_after_s", 1200)):
                    pending["emits"] += 1
                    pending["last_at"] = stamp
                    notice = pending
                    break
        ms = int((time.monotonic() - started) * 1000)
        day = now.date().isoformat()
        daily = state.setdefault("usage", {}).setdefault(day, dict.fromkeys(("runs", "fires", "errors", "open_meteo", "local", "ms_max"), 0))
        for key, value in {"runs": 1, "fires": int(notice is not None), "errors": int(error is not None), **usage}.items():
            daily[key] += value
        daily["ms_max"] = max(daily["ms_max"], ms)
        cutoff = (now.date() - dt.timedelta(days=13)).isoformat()
        state["usage"] = {k: state["usage"][k] for k in sorted(state["usage"])[-14:] if cutoff <= k <= day}
        state["last_run"] = {"at": stamp, "ms": ms, "result": "fire" if notice else "error" if error else "quiet" if is_quiet else "idle",
                             "checks": {"trip_change": bool(checks.get("trip_change")), "flight": bool(flight_due), "weather": bool(weather_due)}}
        payload = {"fire": notice is not None, "message": message(watch, notice, facts, now) if notice else "",
                   "state": {"watch": watch_id, **({"notice": notice["id"]} if notice else {})}}
        write(conn, identity, state, "observe_state", watch["trip_id"], stamp)
    return payload


def main(argv):
    original = sys.stdout
    sys.stdout = io.StringIO()
    timer = None
    lock, written = threading.Lock(), False
    started = time.monotonic()

    def emit(payload):
        nonlocal written
        with lock:
            if not written:
                os.write(1, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
                written = True

    try:
        if len(argv) != 2 or argv[0] != "trip" or not argv[1] or len(argv[1].encode()) > 80:
            return 2
        watch_id = argv[1]

        def timeout():
            emit({"fire": False, "message": "", "state": {"watch": watch_id, "timeout": True}})
            os._exit(0)

        timer = threading.Timer(22, timeout)
        timer.daemon = True
        timer.start()
        root = Path.cwd().resolve(strict=True)
        if not (root / "config.yaml").is_file() or not (root / "state/travel-ledger/travel.sqlite").is_file():
            return 3
        ledger = Ledger(root, timeout=5)
        watch = fields(ledger, "pa:observe-watch:" + watch_id)
        if not watch:
            return 4
        if watch.get("profile_root") != str(root):
            return 3
        settings = fields(ledger, "pa:observe-settings")
        budget = min(25, max(.1, float(settings.get("budget_s", 22))))
        timer.cancel()
        timer = threading.Timer(max(.001, budget - (time.monotonic() - started)), timeout)
        timer.daemon = True
        timer.start()
        payload = ({"fire": False, "message": "", "state": {"watch": watch_id}} if watch.get("status") in
                   {"cancelled", "canceled", "ended", "completed"} else probe(ledger, watch_id, watch, settings, started + budget, started))
        emit(payload)
        return 0
    except Exception:
        return 5
    finally:
        if timer:
            timer.cancel()
        sys.stdout = original
