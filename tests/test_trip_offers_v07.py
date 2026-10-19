from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
import sqlite3
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError, validate

from personal_assistant import concierge, trip_watch as tw
from personal_assistant.daily_ops import trip_context as daily
from personal_assistant.entry import SCHEMA
from personal_assistant.state import Ledger

BASE = dict(trip_id="synthetic", departure_at="2026-11-10T12:00:00Z", arrival_at="2026-11-10T18:00:00Z",
            at="2026-11-09T13:00:00Z", hb2_timezone="UTC", arrival_timezone="UTC",
            commitments=[{"title": "Meeting", "at": "2026-11-10T20:00:00Z"}])


def offer(ledger, **extra):
    return concierge.dispatch(ledger, {"trip_id": "synthetic", "offer_type": "flight_change", **extra})


def test_occurrences_and_legacy_identity(tmp_path):
    ledger = Ledger(tmp_path)
    for occurrence in ("n_00000001", "n_00000002"):
        assert offer(ledger, occurrence=occurrence, reserve=False) == {"allowed": True, "reason": "new_offer"}
        assert offer(ledger, occurrence=occurrence)["reason"] == "new_offer"
        # Reserved but never recorded: a failed turn may retry, and nothing is acknowledged yet.
        assert offer(ledger, occurrence=occurrence) == {"allowed": True, "reason": "retry_reserved"}
        offer(ledger, occurrence=occurrence, action="record", outcome="offered")
        assert offer(ledger, occurrence=occurrence)["reason"] == "already_recorded"
    assert offer(ledger)["reason"] == "new_offer"
    assert offer(ledger)["reason"] == "already_recorded"


def test_decline_first_and_opt_out_precedence(tmp_path):
    ledger = Ledger(tmp_path)
    offer(ledger, action="record", outcome="offered")
    assert offer(ledger, occurrence="n_00000002")["reason"] == "new_offer"
    offer(ledger, action="record", occurrence="n_00000001", outcome="declined")
    assert offer(ledger, occurrence="n_00000002")["reason"] == "declined"
    assert offer(ledger, occurrence="n_00000003")["reason"] == "declined"
    type_row = ledger.get("action", "pa:offer:synthetic:flight_change")
    assert type_row["action_type"] == "offer" and type_row["fields"]["history"][-1]["outcome"] == "declined"
    offer(ledger, action="record", occurrence="n_00000001", outcome="opted_out")
    assert offer(ledger, occurrence="n_00000001")["reason"] == "opted_out"
    assert ledger.get("action", "pa:offer:*:flight_change")["fields"]["outcome"] == "opted_out"
    assert ledger.get("action", "pa:offer:synthetic:flight_change:n_00000001")["fields"]["outcome"] == "opted_out"


@pytest.mark.parametrize("value", [None, "", "n_1", "n_ABCDEF01", "n_123456789", "x_12345678", 123])
def test_occurrence_validation(tmp_path, value):
    with pytest.raises(ValueError, match="occurrence"):
        offer(Ledger(tmp_path), occurrence=value)
    with pytest.raises(ValidationError):
        validate({"operation": "trip_offer", "data": {"occurrence": value}}, SCHEMA["parameters"])


def test_schema_accepts_notice_and_preserves_other_occurrences():
    validate({"operation": "trip_offer", "data": {"occurrence": "n_0123abcd"}}, SCHEMA["parameters"])
    validate({"operation": "action_upsert", "data": {"occurrence": "calendar-event"}}, SCHEMA["parameters"])


@pytest.mark.parametrize("preexisting", [False, True])
def test_decline_both_rows_rollback_when_second_write_fails(tmp_path, preexisting):
    ledger = Ledger(tmp_path)
    identity = "pa:offer:synthetic:flight_change"
    if preexisting:
        offer(ledger, occurrence="n_00000001")
        offer(ledger, action="record", outcome="offered")
    before = ledger.list("action")
    with ledger.connect() as conn:
        conn.execute(f"create trigger reject_type before insert on actions when new.action_id='{identity}' begin select raise(abort, 'second write'); end")
    with pytest.raises(sqlite3.IntegrityError, match="second write"):
        offer(ledger, action="record", occurrence="n_00000001", outcome="declined")
    assert ledger.list("action") == before


def test_legacy_record_merges_concurrent_history(tmp_path):
    ledger = Ledger(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda outcome: offer(ledger, action="record", outcome=outcome), ("accepted", "offered")))
    row = ledger.get("action", "pa:offer:synthetic:flight_change")
    assert {h["outcome"] for h in row["fields"]["history"]} == {"accepted", "offered"}


def test_no_watch_does_not_create_ack_control(tmp_path):
    ledger = Ledger(tmp_path)
    offer(ledger, occurrence="n_00000001")
    offer(ledger, occurrence="n_00000001")
    offer(ledger, occurrence="n_00000001", action="record", outcome="offered")
    assert ledger.get("action", "pa:observe-control:" + tw._watch_id("synthetic")) is None


def raw_events(ledger):
    with ledger.connect() as conn:
        return [tuple(r) for r in conn.execute("select * from pa_events")], [tuple(r) for r in conn.execute("select * from pa_event_revisions")]


@pytest.mark.parametrize("with_facts", [False, True])
def test_status_computes_timing_notices_without_changing_payload(tmp_path, with_facts):
    ledger = Ledger(tmp_path)
    planned = tw.plan(ledger, **BASE)
    if with_facts:
        ledger.put("action", "pa:trip-facts:synthetic", {"digest": "test", "segments": [
            dict(segment_id="s1", origin="AAA", destination="BBB", scheduled_departure=BASE["departure_at"],
                 estimated_departure="2026-11-10T12:30:00Z", origin_timezone="Asia/Tokyo",
                 scheduled_arrival=BASE["arrival_at"], estimated_arrival="2026-11-10T19:00:00Z", destination_timezone="UTC", status="delayed")]})
    watch_id = tw._watch_id("synthetic")
    notices = [dict(id=f"n_{i:08x}", offer_type="flight_change", signals=["Changed"],
                    last_at=f"2026-11-09T12:{i:02d}:00Z", emits=1) for i in range(8)]
    ledger.put("action", "pa:observe:" + watch_id, {"notices": notices, "weather": {"last": {"severity": "snow", "at": "2026-11-09T12:00:00Z"}}})
    ledger.put("action", "pa:observe-control:" + watch_id, {"acks": {"n_00000007": "ack"}})
    before = raw_events(ledger)
    result = tw.status(ledger, "synthetic", at=BASE["at"])
    assert raw_events(ledger) == before and result["revision"] == planned["revision"]
    assert result["leave_by"]["basis"] == ("estimated" if with_facts else "scheduled")
    assert result["leave_by"]["at"] == ("2026-11-10T17:45:00+09:00" if with_facts else "2026-11-10T08:15:00+00:00")
    assert [n["id"] for n in result["notices"]] == [f"n_{i:08x}" for i in (6, 5, 4, 3, 2)]
    assert set(result["notices"][0]) == {"id", "offer_type", "signals", "last_at"}
    first = next(m for m in result["moments"] if m["key"] == "first_commitment")
    assert first["slack_minutes"] == 120
    assert first["feasibility"]["reachable"] is (not with_facts)
    assert first["feasibility"]["slack_minutes"] == (-45 if with_facts else 15)
    stale = tw.status(ledger, "synthetic", at="2026-11-09T15:01:00Z")
    assert stale["leave_by"]["weather_extra_minutes"] == 0


def test_status_without_observer_and_missing_departure_inputs(tmp_path):
    ledger = Ledger(tmp_path)
    planned = tw.plan(ledger, **BASE)
    assert planned["notices"] == [] and planned["leave_by"] is not None
    with ledger.connect() as conn:
        payload = json.loads(conn.execute("select payload_json from pa_events").fetchone()[0])
        payload["inputs"].pop("origin_timezone")
        conn.execute("update pa_events set payload_json=?", (json.dumps(payload),))
    assert tw.status(ledger, "synthetic")["leave_by"] is None


def test_accepted_earlier_leave_survives_watch_carry_and_departures(tmp_path):
    ledger = Ledger(tmp_path)
    original = tw.plan(ledger, **BASE, arm=["watch"])
    tw.record_wake(ledger, "synthetic", "watch", "w_watch")
    offer(ledger, action="record", occurrence="n_00000001", outcome="accepted", offer_type="weather_leave_early")
    changed = tw.plan(ledger, trip_id="synthetic", airport_lead_minutes=210, at=BASE["at"])
    before = next(m["at"] for m in original["moments"] if m["key"] == "leave_by")
    after = next(m["at"] for m in changed["moments"] if m["key"] == "leave_by")
    assert dt.datetime.fromisoformat(before) - dt.datetime.fromisoformat(after) == dt.timedelta(minutes=30)
    assert changed["arms"]["watch"]["carried_from"] == original["revision"]
    assert ledger.get("action", "pa:observe-watch:" + tw._watch_id("synthetic"))["fields"]["airport_lead_minutes"] == 210
    assert tw.departures(ledger) == [{"trip_id": "synthetic", "departure_at": changed["inputs"]["departure_at"], "leave_by_at": after, "airport_lead_minutes": 210}]
    assert tw.plan(ledger, trip_id="synthetic", at=BASE["at"])["inputs"]["airport_lead_minutes"] == 210


def test_departures_without_events_is_read_only(tmp_path):
    ledger = Ledger(tmp_path)
    with ledger.connect() as conn:
        before = list(conn.execute("select * from sqlite_master"))
        conn.execute("pragma query_only=ON")
        class ReadOnlyLedger:
            def connect(self):
                return conn
        assert tw.departures(ReadOnlyLedger()) == []
        assert list(conn.execute("select * from sqlite_master")) == before


CFG = {"timezone": "Asia/Tokyo", "travel": {"leave_by": True, "heads_up_min": 45, "buffer_min": 15, "geocoder": {"consent": False}}}
EVENT = {"id": "flight", "summary": "Flight", "start": {"dateTime": BASE["departure_at"]}}
DEPARTURES = [{"departure_at": BASE["departure_at"], "leave_by_at": "2026-11-10T09:00:00Z"}]


def test_daily_flight_uses_watch_without_base_geocode_or_drive(monkeypatch):
    def fail(*args):
        pytest.fail("watched departure needs no route or geocode")
    monkeypatch.setattr(daily.geo, "geocode", fail)
    now = dt.datetime.fromisoformat("2026-11-10T08:30:00+00:00")
    first = daily.leave_by_alerts(CFG, [EVENT], now, fail, departures=DEPARTURES)
    assert first[0]["line"] == "✈️ leave in 30m — Flight · airport leave-by 18:00"
    moved = daily.leave_by_alerts(CFG, [EVENT], now, fail, departures=[{**DEPARTURES[0], "leave_by_at": "2026-11-10T08:45:00Z"}])
    assert first[0]["key"] != moved[0]["key"] and first[0]["occurrence"] != moved[0]["occurrence"]
    immediate = daily.leave_by_alerts(CFG, [EVENT], now + dt.timedelta(minutes=31), fail, departures=DEPARTURES)
    assert immediate[0]["phase"] == "now" and "LEAVE NOW" in immediate[0]["line"]


@pytest.mark.parametrize("offset,matched", [(-90, True), (90, True), (91, False)])
def test_daily_departure_matching_window(offset, matched):
    event = {**EVENT, "start": {"dateTime": (dt.datetime.fromisoformat("2026-11-10T12:00:00+00:00") + dt.timedelta(minutes=offset)).isoformat()}}
    assert bool(daily.leave_by_alerts(CFG, [event], dt.datetime.fromisoformat("2026-11-10T09:00:00+00:00"), None, departures=DEPARTURES)) is matched


@pytest.mark.parametrize("fails", [False, True])
def test_collect_trip_passes_departures_and_falls_back(tmp_path, monkeypatch, fails):
    context = {"base": {"coordinates": {"lat": 1, "lng": 2}, "label": "Home"}}
    monkeypatch.setattr(daily, "trip_context", lambda *a: context)
    monkeypatch.setattr(daily, "run_calendar_events", lambda *a: SimpleNamespace(items=[{**EVENT, "location": "Airport"}], coverage={}, complete=True, truncated=False))
    def departures(ledger):
        assert ledger.root == tmp_path
        if fails:
            raise RuntimeError("unavailable")
        return DEPARTURES
    monkeypatch.setattr(tw, "departures", departures)
    monkeypatch.setattr(daily.geo, "geocode", lambda *a: (3, 4))
    cfg = {**CFG, "travel": {**CFG["travel"], "geocoder": {"consent": True}}}
    now = dt.datetime.fromisoformat("2026-11-10T11:30:00+00:00")
    _, alerts, complete, truncated = daily.collect_trip(cfg, now, lambda *a: 20, str(tmp_path))
    assert complete and not truncated
    assert ("🚗" if fails else "✈️") in alerts[0]["line"]
    if fails:
        assert "LEAVE NOW" in alerts[0]["line"] and "20m drive + 15m buffer" in alerts[0]["line"]


def test_status_survives_bad_timing_inputs_and_daily_ops_skips_bad_departures(tmp_path, monkeypatch):
    ledger = Ledger(tmp_path)
    tw.plan(ledger, **BASE)
    monkeypatch.setattr(tw.trip_math, "leave_by", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad zone")))
    status = tw.status(ledger, "synthetic", at=BASE["at"])
    assert status["timing_error"] is True and status["leave_by"] is None and status["moments"]
    from personal_assistant.daily_ops import trip_context
    cfg = {"travel": {"leave_by": True}, "timezone": "UTC"}
    bad = [{"departure_at": "not a time", "leave_by_at": "x"}, {"leave_by_at": "2026-11-20T06:00:00+00:00"}, None]
    assert trip_context.leave_by_alerts(cfg, [], dt.datetime(2026, 11, 20, tzinfo=dt.timezone.utc), None, departures=bad) == []


def seg(sid, origin, destination, dep, arr, **extra):
    return dict(segment_id=sid, origin=origin, destination=destination, scheduled_departure=dep, scheduled_arrival=arr,
                origin_timezone="UTC", destination_timezone="UTC", status=extra.pop("status", "scheduled"), **extra)


def test_timing_keeps_the_flight_in_the_air_and_skips_cancelled_legs(tmp_path):
    ledger = Ledger(tmp_path)
    tw.plan(ledger, **BASE)
    outbound = seg("o", "AAA", "BBB", BASE["departure_at"], BASE["arrival_at"], estimated_arrival="2026-11-10T19:30:00Z")
    back = seg("r", "BBB", "AAA", "2026-11-14T12:00:00Z", "2026-11-14T18:00:00Z")
    ledger.put("action", "pa:trip-facts:synthetic", {"digest": "t", "segments": [outbound, back]})
    airborne = tw.status(ledger, "synthetic", at="2026-11-10T15:00:00Z")
    first = next(m for m in airborne["moments"] if m["key"] == "first_commitment")
    assert first["feasibility"]["landing_at"] == "2026-11-10T19:30:00+00:00"  # The outbound flight, not the return.
    cancelled = seg("o", "AAA", "BBB", BASE["departure_at"], BASE["arrival_at"], status="cancelled")
    rebooked = seg("o2", "AAA", "BBB", "2026-11-10T15:00:00Z", "2026-11-10T21:00:00Z")
    ledger.put("action", "pa:trip-facts:synthetic", {"digest": "t2", "segments": [cancelled, rebooked, back]})
    status = tw.status(ledger, "synthetic", at=BASE["at"])
    assert status["leave_by"]["at"] == "2026-11-10T12:00:00+00:00"  # 15:00 rebooked departure minus the 180-minute lead.
    assert tw.departures(ledger, at=BASE["at"])[0]["departure_at"] == "2026-11-10T15:00:00Z"


def test_departures_skip_cancelled_trips_and_follow_computed_leave_by(tmp_path):
    ledger = Ledger(tmp_path)
    tw.plan(ledger, **BASE)
    ledger.put("action", "pa:observe:" + tw._watch_id("synthetic"), {"weather": {"last": {"severity": "snow", "at": "2026-11-10T07:00:00Z"}}})
    [entry] = tw.departures(ledger, at="2026-11-10T08:00:00Z")
    assert entry["leave_by_at"] == "2026-11-10T08:15:00+00:00"  # 12:00 minus 180 minutes minus 45 for snow.
    ledger.put("action", "pa:trip-facts:synthetic", {"digest": "c", "segments": [
        seg("o", "AAA", "BBB", BASE["departure_at"], BASE["arrival_at"], status="cancelled")]})
    assert tw.departures(ledger, at="2026-11-10T08:00:00Z") == []


def test_daily_ops_matches_the_closest_departure():
    cfg = {"travel": {"leave_by": True, "heads_up_min": 600}, "timezone": "UTC"}
    event = {"id": "e1", "summary": "Flight", "start": {"dateTime": "2026-11-20T11:00:00+00:00"}}
    departures = [{"departure_at": "2026-11-20T10:00:00+00:00", "leave_by_at": "2026-11-20T07:00:00+00:00"},
                  {"departure_at": "2026-11-20T11:00:00+00:00", "leave_by_at": "2026-11-20T08:00:00+00:00"}]
    [alert] = daily.leave_by_alerts(cfg, [event], dt.datetime(2026, 11, 20, 6, 0, tzinfo=dt.timezone.utc), None, departures=departures)
    assert "airport leave-by 08:00" in alert["line"]
