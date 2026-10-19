"""Remember trip offers and explicit lasting opt-outs without provider actions."""
import json
import re

from .state import now

OUTCOMES = {"offered", "accepted", "declined", "completed", "useful", "not_useful", "opted_out"}


def _record(conn, identity, trip_id, outcome):
    old = conn.execute("select * from actions where action_id=?", (identity,)).fetchone()
    fields = json.loads(old["fields_json"]) if old else {}
    stamp = now()
    fields.update(outcome=outcome, history=(fields.get("history", []) + [{"outcome": outcome, "at": stamp}])[-20:])
    conn.execute("insert into actions values(?,?,?,?,?,?,?,?) on conflict(action_id) do update set "
                 "trip_id=excluded.trip_id,action_type=excluded.action_type,fields_json=excluded.fields_json,updated_at=excluded.updated_at",
                 (identity, trip_id, "offer", old["provider"] if old else "", old["status"] if old else "pending",
                  json.dumps(fields), old["created_at"] if old else stamp, stamp))
    row = dict(conn.execute("select * from actions where action_id=?", (identity,)).fetchone())
    row["fields"] = json.loads(row.pop("fields_json"))
    return row


def _ack(ledger, trip_id, occurrence):
    from .trip_watch import _watch_id
    from .observe import ack
    watch_id = _watch_id(trip_id)
    if ledger.get("action", "pa:observe-watch:" + watch_id):
        ack(ledger, watch_id, occurrence)


def _weather_replan(conn, trip_id, occurrence, saved):
    from .observe import read
    from .trip_watch import _event_id, _watch_id
    fields = saved["fields"]
    key = "replan_airport_lead_minutes"
    if key not in fields:
        state = read(conn, "pa:observe:" + _watch_id(trip_id))
        notice = next((n for n in state.get("notices", []) if n.get("id") == occurrence), {})
        extra = notice.get("weather_extra_minutes")
        event = conn.execute("select payload_json from pa_events where event_id=?", (_event_id(trip_id),)).fetchone() if conn.execute(
            "select 1 from sqlite_master where type='table' and name='pa_events'").fetchone() else None
        inputs = json.loads(event[0]).get("inputs", {}) if event else {}
        lead, included = inputs.get("airport_lead_minutes"), inputs.get("weather_included_minutes") or 0
        known = all(type(v) is int and v >= 0 for v in (lead, extra, included))
        fields[key] = lead + extra if known else None
        # The notice adds only weather beyond what the lead already covers, so the buffer is cumulative.
        fields["replan_weather_included_minutes"] = included + extra if known else None
        conn.execute("update actions set fields_json=? where action_id=?", (json.dumps(fields), saved["action_id"]))
    target = fields[key]
    saved["next"] = {"operation": "trip_watch_plan", "data": {
        "action": "plan", "trip_id": trip_id, "airport_lead_minutes": target,
        "weather_included_minutes": fields.get("replan_weather_included_minutes", 0)}} if target is not None else None
    if target is None:
        saved["next_note"] = "replan manually: lead unknown"


def dispatch(ledger, data):
    action, trip_id, offer_type = data.get("action", "check"), data.get("trip_id"), data.get("offer_type") or ""
    if not trip_id or trip_id == "*" or not re.fullmatch(r"[a-z][a-z_]{1,39}", offer_type):
        raise ValueError("invalid trip_id or offer_type")
    occurrence_data = data
    if "occurrence" not in data and isinstance(data.get("fields"), dict):
        occurrence_data = data["fields"]
    occurrence = occurrence_data.get("occurrence")
    if "occurrence" in occurrence_data and (not isinstance(occurrence, str) or not re.fullmatch(r"n_[0-9a-f]{8}", occurrence)):
        raise ValueError("invalid occurrence")
    type_id = f"pa:offer:{trip_id}:{offer_type}"
    identity = type_id + ":" + occurrence if occurrence else type_id
    opt_out = f"pa:offer:*:{offer_type}"
    if action == "check":
        with ledger.connect() as conn:
            conn.execute("begin immediate")
            seen = {row["action_id"]: json.loads(row["fields_json"]) for row in conn.execute(
                "select action_id,fields_json from actions where action_id in (?,?,?)", (identity, type_id, opt_out))}
            # A reservation that never became an outcome is a retry after a failed turn, not a handled offer.
            reason = ("opted_out" if opt_out in seen else "declined" if occurrence and seen.get(type_id, {}).get("outcome") == "declined"
                      else "retry_reserved" if occurrence and seen.get(identity, {}).get("outcome") == "reserved"
                      else "already_recorded" if identity in seen else "new_offer")
            if reason == "new_offer" and data.get("reserve", True):
                stamp = now()
                fields = {"outcome": "reserved", "history": [{"outcome": "reserved", "at": stamp}]}
                conn.execute("insert into actions values(?,?,?,?,?,?,?,?)",
                             (identity, trip_id, "offer", "", "reserved", json.dumps(fields), stamp, stamp))
        if occurrence and reason in {"opted_out", "declined", "already_recorded"}:
            _ack(ledger, trip_id, occurrence)
        return {"allowed": reason in {"new_offer", "retry_reserved"}, "reason": reason}
    outcome = data.get("outcome")
    if action != "record" or outcome not in OUTCOMES:
        raise ValueError("invalid offer action or outcome")
    if outcome == "opted_out" and not occurrence:
        identity = opt_out
    with ledger.connect() as conn:
        conn.execute("begin immediate")
        saved = _record(conn, identity, "*" if identity == opt_out else trip_id, outcome)
        if occurrence and outcome == "accepted" and offer_type == "weather_leave_early":
            _weather_replan(conn, trip_id, occurrence, saved)
        if occurrence and outcome == "declined":
            _record(conn, type_id, trip_id, outcome)
        if occurrence and outcome == "opted_out":
            _record(conn, opt_out, "*", outcome)
    if occurrence:
        _ack(ledger, trip_id, occurrence)
    return saved
