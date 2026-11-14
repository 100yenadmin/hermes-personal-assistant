import datetime as dt
import hashlib
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from personal_assistant.automation_workflow import preferences
from personal_assistant.context import next_actions
from personal_assistant.location import timezone_check
from personal_assistant.radar import scan
from personal_assistant.state import Ledger
from personal_assistant.trip_facts import record_facts

MOMENT = dt.datetime.fromisoformat("2026-11-14T12:00:00+00:00")


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path)


def _segment(**changes):
    return {"segment_id": "TG101:2026-11-13", "carrier": "TG", "number": "101",
            "origin": "ICN", "destination": "CNX", "origin_timezone": "Asia/Seoul",
            "destination_timezone": "Asia/Bangkok", "scheduled_departure": "2026-11-13T01:00:00Z",
            "scheduled_arrival": "2026-11-13T06:00:00Z", "status": "landed", "source": "user", **changes}


def _facts(ledger, *segments, identity="synthetic"):
    ledger.put("action", "pa:trip-facts:" + identity, {"segments": list(segments)}, action_type="note")


def test_no_facts_or_home(ledger):
    assert timezone_check(ledger, MOMENT) is None
    preferences(ledger, {"timezone": "Asia/Seoul"})
    assert timezone_check(ledger, MOMENT) is None


def test_landed_bangkok_with_real_fact_writer(ledger):
    preferences(ledger, {"timezone": "Asia/Seoul"})
    record_facts(ledger, "synthetic", [_segment()], "user", observed_at=MOMENT.isoformat())
    assert timezone_check(ledger, MOMENT) == {
        "radar_kind": "timezone_check", "action_id": "pa:preferences", "stored": "Asia/Seoul",
        "suggested": "Asia/Bangkok", "evidence_key": "landed:TG101:2026-11-13", "surfaced": True, "switch": True,
        "evidence": {"kind": "landed", "segment_id": "TG101:2026-11-13", "flight": "TG101",
                     "airport": "CNX", "at": "2026-11-13T13:00:00+07:00"}}


@pytest.mark.parametrize("stored", ["Asia/Bangkok", "Asia/Ho_Chi_Minh"])
def test_same_clock_suppresses_different_zone_names(ledger, stored):
    preferences(ledger, {"timezone": stored})
    _facts(ledger, _segment())
    assert timezone_check(ledger, MOMENT) is None


def test_offsets_compared_at_moment_including_dst(ledger):
    preferences(ledger, {"timezone": "Europe/Berlin", "home_timezone": "Africa/Algiers"})
    assert timezone_check(ledger, MOMENT) is None
    assert timezone_check(ledger, MOMENT.replace(month=7))["suggested"] == "Africa/Algiers"


@pytest.mark.parametrize("at", ["2026-11-13T01:00:00Z", "2026-11-13T03:00:00Z"])
def test_in_flight_suppresses_even_home(ledger, at):
    preferences(ledger, {"timezone": "Asia/Seoul", "home_timezone": "Europe/London"})
    _facts(ledger, _segment())
    assert timezone_check(ledger, dt.datetime.fromisoformat(at)) is None


@pytest.mark.parametrize("origin,zone", [("CNX", "Asia/Bangkok"), ("DMK", "Asia/Bangkok"),
                                        ("CNX", "Asia/Tokyo")])
def test_connection_waits_until_last_leg_lands_across_trip_records(ledger, origin, zone):
    preferences(ledger, {"timezone": "Asia/Seoul"})
    _facts(ledger, _segment())
    _facts(ledger, _segment(segment_id="TG202:2026-11-13", number="202", origin=origin,
                           origin_timezone=zone, destination="LHR", destination_timezone="Europe/London",
                           scheduled_departure="2026-11-14T04:00:00Z", scheduled_arrival="2026-11-14T18:00:00Z"),
           identity="connection")
    for at in ("2026-11-13T06:00:00Z", "2026-11-14T03:00:00Z", "2026-11-14T12:00:00Z"):
        assert timezone_check(ledger, dt.datetime.fromisoformat(at)) is None
    item = timezone_check(ledger, dt.datetime.fromisoformat("2026-11-14T18:00:00Z"))
    assert item["suggested"] == "Europe/London"
    assert item["evidence_key"] == "landed:TG202:2026-11-13"


def test_departing_beats_october_landing_incident(ledger):
    preferences(ledger, {"timezone": "Asia/Seoul"})
    _facts(ledger, _segment(destination="ICN", destination_timezone="Asia/Seoul",
                           scheduled_departure=(MOMENT - dt.timedelta(days=40, hours=5)).isoformat(),
                           scheduled_arrival=(MOMENT - dt.timedelta(days=40)).isoformat()),
           _segment(segment_id="FD3430:2026-11-21", carrier="FD", number="3430", origin="CNX",
                    destination="DMK", origin_timezone="Asia/Bangkok", status="scheduled",
                    scheduled_departure=(MOMENT + dt.timedelta(days=7)).isoformat(),
                    scheduled_arrival=(MOMENT + dt.timedelta(days=7, hours=1)).isoformat()))
    item = timezone_check(ledger, MOMENT)
    assert item["suggested"] == "Asia/Bangkok"
    assert item["evidence"] == {"kind": "departing", "segment_id": "FD3430:2026-11-21",
                                "flight": "FD3430", "airport": "CNX", "at": "2026-11-21T19:00:00+07:00"}


@pytest.mark.parametrize("days,kind", [(1, "departing"), (2, "landed"), (3, "landed")])
def test_nearest_evidence_and_landed_tie_break(ledger, days, kind):
    preferences(ledger, {"timezone": "UTC"})
    _facts(ledger, _segment(scheduled_departure=(MOMENT - dt.timedelta(days=2, hours=5)).isoformat(),
                           scheduled_arrival=(MOMENT - dt.timedelta(days=2)).isoformat()),
           _segment(segment_id="future", origin="NRT", origin_timezone="Asia/Tokyo",
                    scheduled_departure=(MOMENT + dt.timedelta(days=days)).isoformat(),
                    scheduled_arrival=(MOMENT + dt.timedelta(days=days, hours=5)).isoformat()))
    assert timezone_check(ledger, MOMENT)["evidence"]["kind"] == kind


@pytest.mark.parametrize("side", ["past", "future"])
@pytest.mark.parametrize("days,expected", [(30, True), (31, False)])
def test_thirty_day_evidence_window(ledger, side, days, expected):
    preferences(ledger, {"timezone": "UTC"})
    at = MOMENT + dt.timedelta(days=days * (-1 if side == "past" else 1))
    departure, arrival = (at - dt.timedelta(hours=5), at) if side == "past" else (at, at + dt.timedelta(hours=5))
    _facts(ledger, _segment(scheduled_departure=departure.isoformat(), scheduled_arrival=arrival.isoformat()))
    assert (timezone_check(ledger, MOMENT) is not None) is expected


@pytest.mark.parametrize("field,value", [("status", "cancelled"), ("source", "simulated")])
def test_cancelled_and_simulated_are_not_evidence_or_connections(ledger, field, value):
    preferences(ledger, {"timezone": "Asia/Seoul"})
    _facts(ledger, _segment(**{field: value}))
    assert timezone_check(ledger, MOMENT) is None
    _facts(ledger, _segment(), _segment(segment_id="ignored-connection", origin="CNX", origin_timezone="Asia/Bangkok",
           scheduled_departure="2026-11-14T04:00:00Z", scheduled_arrival="2026-11-14T18:00:00Z", **{field: value}))
    assert timezone_check(ledger, MOMENT)["evidence"]["kind"] == "landed"


def test_home_fallback_and_only_own_kept_key_suppressed(ledger):
    preferences(ledger, {"timezone": "Asia/Seoul", "home_timezone": "Asia/Bangkok"})
    _facts(ledger, _segment(scheduled_departure="2026-09-01T01:00:00Z", scheduled_arrival="2026-09-01T06:00:00Z"))
    item = timezone_check(ledger, MOMENT)
    assert item["suggested"] == "Asia/Bangkok"
    assert item["evidence"] == {"kind": "home"}
    assert item["evidence_key"] == "home:Asia/Bangkok"
    preferences(ledger, {"timezone_kept": item["evidence_key"]})
    assert timezone_check(ledger, MOMENT) is None
    _facts(ledger, _segment())
    assert timezone_check(ledger, MOMENT)["evidence_key"] == "landed:TG101:2026-11-13"
    preferences(ledger, {"timezone_kept": "landed:TG101:2026-11-13"})
    assert timezone_check(ledger, MOMENT) is None
    _facts(ledger, _segment(segment_id="new-flight"))
    assert timezone_check(ledger, MOMENT)["evidence_key"] == "landed:new-flight"


@pytest.mark.parametrize("stored", [None, "Mars/Olympus", 7, ""])
def test_missing_or_invalid_stored_is_none_in_item(ledger, stored):
    ledger.put("action", "pa:preferences", {"timezone": stored}, action_type="preferences")
    _facts(ledger, _segment())
    assert timezone_check(ledger, MOMENT)["stored"] is None


@pytest.mark.parametrize("bad", [None, "segment", {}, {"segment_id": "only-id"},
    _segment(scheduled_departure="yesterday"), _segment(scheduled_arrival="2026-11-13T06:00:00"),
    _segment(estimated_arrival=[]), _segment(estimated_departure=""), _segment(origin_timezone="bad-zone"),
    _segment(destination_timezone=None), _segment(scheduled_arrival="2026-11-12T00:00:00Z"),
    _segment(segment_id=5), _segment(carrier=None)])
def test_malformed_segments_are_ignored(ledger, bad):
    _facts(ledger, bad)
    assert timezone_check(ledger, MOMENT) is None
    _facts(ledger, bad, _segment())
    assert timezone_check(ledger, MOMENT)["suggested"] == "Asia/Bangkok"


def test_malformed_containers_and_non_fact_actions_ignored(ledger):
    ledger.put("action", "pa:trip-facts:bad", {"segments": "not-a-list"}, action_type="note")
    ledger.put("action", "not-trip-facts", {"segments": [_segment()]}, action_type="note")
    assert timezone_check(ledger, MOMENT) is None
    ledger.put("action", "pa:preferences", {"home_timezone": "not-a-zone"}, action_type="preferences")
    assert timezone_check(ledger, MOMENT) is None


def test_estimated_times_override_scheduled_times(ledger):
    _facts(ledger, _segment(estimated_departure="2026-11-14T11:00:00Z", estimated_arrival="2026-11-14T13:00:00Z"))
    assert timezone_check(ledger, MOMENT) is None
    later = MOMENT + dt.timedelta(hours=1)
    assert timezone_check(ledger, later)["evidence"]["at"] == "2026-11-14T20:00:00+07:00"


def test_radar_and_next_action_include_item_without_writes(ledger):
    preferences(ledger, {"timezone": "Asia/Seoul"})
    _facts(ledger, _segment())
    ledger.put("action", "deadline", {"radar_kind": "deadline", "event_date": "2026-11-14"}, action_type="commitment")
    before = ledger.list("action")
    files = {p.relative_to(ledger.root): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in ledger.root.rglob("*") if p.is_file()}
    readonly = Ledger(ledger.root, read_only=True)
    result = scan(readonly, {}, kanban_reader=lambda *_: {}, moment=MOMENT, zone=ZoneInfo("Asia/Seoul"))
    assert result["read_only"] is True
    assert [i["action_id"] for i in result["candidates"]] == ["pa:preferences", "deadline"]
    assert result["candidates"][0] == timezone_check(readonly, MOMENT)
    integrated = next_actions(readonly, {"radar": True, "at": MOMENT.isoformat()}, kanban_reader=lambda *_: {})
    assert json.dumps(integrated) == json.dumps(result)
    assert ledger.list("action") == before
    assert {p.relative_to(ledger.root): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in ledger.root.rglob("*") if p.is_file()} == files


@pytest.mark.parametrize("data", [{"trip_id": "synthetic"}, {"loops_only": True}])
def test_radar_filters_omit_timezone_item(ledger, data):
    _facts(ledger, _segment())
    assert timezone_check(ledger, MOMENT) is not None
    assert scan(ledger, data, kanban_reader=lambda *_: {}, moment=MOMENT, zone=dt.timezone.utc)["candidates"] == []


def test_preferences_accept_new_fields_without_changing_schedule(ledger):
    preferences(ledger, {"timezone": "Asia/Seoul"})
    result = preferences(ledger, {"home_timezone": "Asia/Bangkok", "timezone_kept": "home:Asia/Bangkok"})
    assert result == {"timezone": "Asia/Seoul", "home_timezone": "Asia/Bangkok", "timezone_kept": "home:Asia/Bangkok"}
    assert preferences(ledger) == result


@pytest.mark.parametrize("value", ["", "x" * 121, 123, []])
def test_preferences_reject_invalid_kept_key_atomically(ledger, value):
    with pytest.raises(ValueError, match="timezone_kept"):
        preferences(ledger, {"home_timezone": "Asia/Bangkok", "timezone_kept": value})
    assert preferences(ledger) == {}


@pytest.mark.parametrize("value", ["x", "x" * 120])
def test_preferences_accept_kept_key_length_bounds(ledger, value):
    assert preferences(ledger, {"timezone_kept": value})["timezone_kept"] == value


def test_preferences_reject_invalid_home_zone(ledger):
    with pytest.raises((ValueError, ZoneInfoNotFoundError)):
        preferences(ledger, {"home_timezone": "Mars/Olympus"})
    assert preferences(ledger) == {}


@pytest.mark.parametrize("hours, expected", [(47, True), (48, True), (49, False), (24 * 20, False)])
def test_switch_only_on_a_landing_in_the_last_48_hours(ledger, hours, expected):
    preferences(ledger, {"timezone": "Asia/Seoul"})
    arrival = MOMENT - dt.timedelta(hours=hours)
    _facts(ledger, _segment(scheduled_departure=(arrival - dt.timedelta(hours=5)).isoformat(),
                            scheduled_arrival=arrival.isoformat()))
    item = timezone_check(ledger, MOMENT)
    assert item["evidence"]["kind"] == "landed" and item["switch"] is expected


def test_departing_and_home_evidence_never_switch_without_asking(ledger):
    preferences(ledger, {"timezone": "Asia/Seoul", "home_timezone": "Asia/Bangkok"})
    assert timezone_check(ledger, MOMENT)["switch"] is False  # home
    _facts(ledger, _segment(scheduled_departure="2026-11-15T01:00:00Z", scheduled_arrival="2026-11-15T06:00:00Z",
                            origin="CNX", destination="DMK", origin_timezone="Asia/Bangkok", status="scheduled"))
    item = timezone_check(ledger, MOMENT)
    assert item["evidence"]["kind"] == "departing" and item["switch"] is False


def test_preferences_clear_home_and_kept_with_none(ledger):
    preferences(ledger, {"timezone": "Asia/Seoul", "home_timezone": "Asia/Bangkok", "timezone_kept": "home:Asia/Bangkok"})
    assert timezone_check(ledger, MOMENT) is None
    preferences(ledger, {"timezone_kept": None})
    assert timezone_check(ledger, MOMENT)["evidence_key"] == "home:Asia/Bangkok"
    preferences(ledger, {"home_timezone": None})
    assert timezone_check(ledger, MOMENT) is None


def test_delay_without_new_arrival_moves_the_arrival(ledger):
    # ICN->HKG landed 2 h ago; HKG->CNX is delayed past its scheduled arrival with no estimated arrival.
    preferences(ledger, {"timezone": "Asia/Seoul"})
    _facts(ledger,
           _segment(segment_id="KE1:2026-11-14", carrier="KE", number="1", destination="HKG",
                    destination_timezone="Asia/Hong_Kong", scheduled_departure="2026-11-14T06:30:00Z",
                    scheduled_arrival="2026-11-14T10:00:00Z"),
           _segment(segment_id="CX9:2026-11-14", carrier="CX", number="9", origin="HKG", origin_timezone="Asia/Hong_Kong",
                    scheduled_departure="2026-11-14T11:00:00Z", scheduled_arrival="2026-11-14T13:00:00Z",
                    estimated_departure="2026-11-14T14:00:00Z", status="delayed"))
    assert timezone_check(ledger, MOMENT) is None  # Between legs at the hub.
    assert timezone_check(ledger, MOMENT + dt.timedelta(hours=3)) is None  # In the air on the delayed leg.
    item = timezone_check(ledger, MOMENT + dt.timedelta(hours=5))
    assert item["evidence"]["segment_id"] == "CX9:2026-11-14" and item["suggested"] == "Asia/Bangkok"
    assert item["evidence"]["at"] == "2026-11-14T23:00:00+07:00"  # 13:00Z scheduled + 3 h delay


def test_diverted_flight_is_not_landed_evidence(ledger):
    preferences(ledger, {"timezone": "Asia/Seoul"})
    _facts(ledger, _segment(status="diverted"))
    assert timezone_check(ledger, MOMENT) is None


def test_diverted_last_leg_does_not_fall_back_to_the_hub(ledger):
    preferences(ledger, {"timezone": "Asia/Seoul"})
    _facts(ledger,
           _segment(segment_id="KE1:2026-11-14", carrier="KE", number="1", destination="HKG",
                    destination_timezone="Asia/Hong_Kong", scheduled_departure="2026-11-13T23:00:00Z",
                    scheduled_arrival="2026-11-14T03:00:00Z"),
           _segment(segment_id="CX9:2026-11-14", carrier="CX", number="9", origin="HKG", origin_timezone="Asia/Hong_Kong",
                    scheduled_departure="2026-11-14T07:00:00Z", scheduled_arrival="2026-11-14T10:00:00Z", status="diverted"))
    assert timezone_check(ledger, MOMENT) is None
