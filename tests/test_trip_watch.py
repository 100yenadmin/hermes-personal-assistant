import pytest

from personal_assistant.automation_workflow import preferences
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger
from personal_assistant.state_loop import StateLoop

BASE = {"trip_id": "synthetic", "departure_at": "2026-11-10T12:00:00+09:00",
        "arrival_at": "2026-11-10T22:30:00+01:00", "arrival_timezone": "Europe/Paris",
        "at": "2026-11-08T00:00:00+00:00"}


def call(root, **data):
    return dispatch(root, {"operation": "trip_watch_plan", "data": {**BASE, **data}})


@pytest.mark.parametrize("hour,expected", [("06:00", "2026-11-09T21:30:00+09:00"),
    ("01:30", "2026-11-09T21:30:00+09:00"), ("12:00", "2026-11-10T09:00:00+09:00")])
def test_quiet_shift(tmp_path, hour, expected):
    result = call(tmp_path, departure_at=f"2026-11-10T{hour}:00+09:00")
    assert result["pulse_create"]["trigger"]["at"] == expected
    assert not result["moments"][2]["quiet"]


def test_zones_note_and_payload(tmp_path):
    preferences(Ledger(tmp_path), {"timezone": "Asia/Seoul"})
    result = call(tmp_path, commitments=[{"title": "Synthetic meeting", "at": "2026-11-11T09:30:00+01:00"}])
    moments, pulse = result["moments"], result["pulse_create"]
    assert [m["at"] for m in moments[:2]] == ["2026-11-09T12:00:00+09:00", "2026-11-10T09:00:00+09:00"]
    assert moments[3]["at"] == "2026-11-10T23:00:00+01:00" and moments[3]["quiet"]
    assert moments[4]["slack_minutes"] == 660 and result["late_arrival"]
    assert set(pulse) == {"action", "title", "note", "reason", "trigger", "owner_asked"}
    assert len(pulse["note"]) <= 2000 and "personal-assistant:trip-concierge" in pulse["note"]
    assert all(s in pulse["note"] for s in ("Asia/Seoul", "Europe/Paris", "660", "Late arrival: yes", "pa trip_offer check"))
    payload = StateLoop(Ledger(tmp_path)).get_event(result["event_id"])["payload"]
    assert payload["moments"] == moments and payload["inputs"]["departure_at"] == BASE["departure_at"]
    assert payload["inputs"]["commitments"][0]["title"] == "Synthetic meeting"
    assert not call(tmp_path, arrival_at="2026-11-10T18:00:00+01:00")["late_arrival"]


def test_needs_input_is_read_only(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.put("trip", "synthetic", {"events": [{"start": "2026-11-10", "summary": "Candidate"}] * 10})
    result = call(tmp_path, departure_at=None, arrival_at=None)
    assert result["needs"] == ["departure_at", "arrival_at"] and len(result["candidates"]) == 8
    assert ledger.list("action") == []
    with ledger.connect() as conn:
        assert not conn.execute("select name from sqlite_master where name='pa_events'").fetchone()


def test_replay_receipt_and_stale_wakes(tmp_path):
    planned = call(tmp_path)
    receipt = {"action": "record_wake", "moment": "arrival_logistics", "wake_id": "w_synthetic"}
    for _ in range(2):
        result = dispatch(tmp_path, {"operation": "trip_watch_plan", "data": {"trip_id": "synthetic", **receipt}})
        assert result["wake_id"] == "w_synthetic" and result["moments"][2]["armed"]
    assert call(tmp_path, at="2026-11-08T01:00:00+00:00")["revision"] == planned["revision"]
    ledger = Ledger(tmp_path)
    assert len(ledger.get("action", "pa:trip-watch:synthetic")["fields"]["wakes"]) == 1
    projection = StateLoop(ledger).get_event(planned["event_id"])["projections"][0]
    assert projection["status"] == "confirmed" and projection["result"]["proof"] == {"wake_id": "w_synthetic", "arm_key": result["arms"]["arrival_logistics"]["arm_key"]}
    changed = call(tmp_path, airport_lead_minutes=120)
    assert changed["revision"] != planned["revision"] and changed["stale_wakes"] == [] and changed["armed"]
    data = {"trip_id": "synthetic", "action": "status"}
    assert dispatch(tmp_path, {"operation": "trip_watch_plan", "data": data})["wake_id"] == "w_synthetic"
    with pytest.raises(ValueError):
        dispatch(tmp_path, {"operation": "trip_watch_plan", "data": {"trip_id": "synthetic", **receipt, "wake_id": "invalid"}})


def test_past_and_lifetime(tmp_path):
    result = call(tmp_path, at="2026-11-10T10:00:00+09:00")
    assert result["recommend"] == "offer_now_in_chat" and "pulse_create" not in result
    assert all(m["status"] == "past" for m in result["moments"][:3])
    assert "lifetime_warning" in call(tmp_path, at="2026-10-01T00:00:00+00:00")
    assert "pulse_create" not in call(tmp_path, at="2026-11-12T00:00:00+00:00")


def test_wake_id_without_action_is_rejected_not_replanned(tmp_path):
    # A live model sent record_wake arguments without the action; the default plan dropped them.
    data = {"trip_id": "T1", "moment": "arrival_logistics", "wake_id": "w_synthetic", "armed": True}
    with pytest.raises(ValueError, match="record_wake"):
        dispatch(tmp_path, {"operation": "trip_watch_plan", "data": data})


def test_weather_included_carries_only_with_carried_lead(tmp_path):
    from personal_assistant import trip_watch
    ledger = Ledger(tmp_path)
    first = call(tmp_path, airport_lead_minutes=225, weather_included_minutes=45, arm=["watch"])
    trip_watch.record_wake(ledger, "synthetic", "watch", "w_weather", armed=True)
    watch_id = trip_watch._watch_id("synthetic")
    assert ledger.get("action", "pa:observe-watch:" + watch_id)["fields"]["weather_included_minutes"] == 45
    carried = trip_watch.plan(ledger, trip_id="synthetic", at=BASE["at"])
    assert carried["inputs"]["weather_included_minutes"] == 45
    assert carried["inputs"]["airport_lead_minutes"] == 225
    assert carried["revision"] == first["revision"]
    explicit = call(tmp_path, arm=["watch"])  # New times without a lead: the lead resets, so does the included buffer.
    assert explicit["inputs"]["airport_lead_minutes"] == 180
    assert explicit["inputs"]["weather_included_minutes"] == 0
    reset = trip_watch.plan(ledger, trip_id="synthetic", airport_lead_minutes=210, at=BASE["at"])
    assert reset["inputs"]["weather_included_minutes"] == 0


@pytest.mark.parametrize("value", [-1, True, 1.5, "45", 226])
def test_invalid_weather_included_minutes(tmp_path, value):
    with pytest.raises(ValueError, match="weather_included_minutes"):
        call(tmp_path, airport_lead_minutes=225, weather_included_minutes=value)
