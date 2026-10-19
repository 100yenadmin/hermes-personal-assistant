import datetime as dt
import time

import pytest

from personal_assistant import observe, trip_watch
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger


OCCURRENCE = "n_1234abcd"


def plan(root, lead=180):
    return dispatch(root, {"operation": "trip_watch_plan", "data": {
        "action": "plan", "trip_id": "synthetic", "airport_lead_minutes": lead,
        "departure_at": "2026-11-10T12:00:00+00:00",
        "arrival_at": "2026-11-10T18:00:00+00:00", "hb2_timezone": "UTC",
        "at": "2026-11-09T12:00:00+00:00"}})


def seed(root):
    plan(root)
    ledger = Ledger(root)
    watch_id = trip_watch._watch_id("synthetic")
    ledger.put("action", "pa:observe-watch:" + watch_id,
               {"trip_id": "synthetic", "airport_lead_minutes": 90})  # Stale; use the latest plan.
    ledger.put("action", "pa:observe:" + watch_id, {"notices": [
        {"id": "n_aaaaaaaa", "weather_extra_minutes": 10},
        {"id": OCCURRENCE, "offer_type": "weather_leave_early", "weather_extra_minutes": 45,
         "signals": ["Leave by 08:15 (+45 min for snow)"]}]})
    return ledger, watch_id


def accept(root, location="top"):
    data = {
        "action": "record", "trip_id": "synthetic", "offer_type": "weather_leave_early",
        "outcome": "accepted"}
    data.update({"fields": {"occurrence": OCCURRENCE}} if location == "fields" else {"occurrence": OCCURRENCE})
    return dispatch(root, {"operation": "trip_offer", "data": data})


def expected_next():
    return {"operation": "trip_watch_plan", "data": {
        "action": "plan", "trip_id": "synthetic", "airport_lead_minutes": 225, "weather_included_minutes": 45}}


@pytest.mark.parametrize("location", ["top", "fields"])
def test_accepted_weather_returns_exact_executable_replan(tmp_path, location):
    ledger, watch_id = seed(tmp_path)
    saved = accept(tmp_path, location)
    assert saved["action_id"] == "pa:offer:synthetic:weather_leave_early:" + OCCURRENCE
    assert saved["next"] == expected_next()
    assert saved["fields"]["outcome"] == "accepted"
    stored = ledger.get("action", "pa:offer:synthetic:weather_leave_early:" + OCCURRENCE)
    assert stored["fields"] == saved["fields"]
    assert ledger.get("action", "pa:offer:synthetic:weather_leave_early") is None
    assert OCCURRENCE in ledger.get("action", "pa:observe-control:" + watch_id)["fields"]["acks"]
    assert dispatch(tmp_path, saved["next"])["inputs"]["airport_lead_minutes"] == 225


@pytest.mark.parametrize("location", ["top", "fields"])
@pytest.mark.parametrize("value", [None, "", "n_1", "n_ABCDEF01", "n_123456789", "x_12345678", 123])
def test_record_invalid_occurrence_raises_same_error(tmp_path, location, value):
    data = {"action": "record", "trip_id": "synthetic", "offer_type": "weather_leave_early",
            "outcome": "accepted"}
    data.update({"fields": {"occurrence": value}} if location == "fields" else {"occurrence": value})
    with pytest.raises(ValueError, match="^invalid occurrence$"):
        dispatch(tmp_path, {"operation": "trip_offer", "data": data})


@pytest.mark.parametrize("value", [OCCURRENCE, None])
def test_top_level_occurrence_takes_precedence(tmp_path, value):
    ledger, watch_id = seed(tmp_path)
    data = {"action": "record", "trip_id": "synthetic", "offer_type": "weather_leave_early",
            "outcome": "accepted", "occurrence": value, "fields": {"occurrence": "n_aaaaaaaa"}}
    if value is None:
        with pytest.raises(ValueError, match="^invalid occurrence$"):
            dispatch(tmp_path, {"operation": "trip_offer", "data": data})
    else:
        saved = dispatch(tmp_path, {"operation": "trip_offer", "data": data})
        assert saved["next"] == expected_next()
        assert set(ledger.get("action", "pa:observe-control:" + watch_id)["fields"]["acks"]) == {OCCURRENCE}


def test_occurrence_is_not_read_from_other_relocations(tmp_path):
    ledger, watch_id = seed(tmp_path)
    saved = dispatch(tmp_path, {"operation": "trip_offer", "occurrence": OCCURRENCE, "data": {
        "action": "record", "trip_id": "synthetic", "offer_type": "weather_leave_early",
        "outcome": "accepted", "metadata": {"occurrence": OCCURRENCE},
        "fields": {"metadata": {"occurrence": OCCURRENCE}}}})
    assert saved["action_id"] == "pa:offer:synthetic:weather_leave_early"
    assert "next" not in saved
    assert ledger.get("action", "pa:observe-control:" + watch_id) is None


def test_accepted_weather_replay_after_replan_keeps_original_target(tmp_path):
    ledger, watch_id = seed(tmp_path)
    accept(tmp_path)
    plan(tmp_path, lead=225)
    ledger.put("action", "pa:observe-watch:" + watch_id, {"airport_lead_minutes": 225})
    ledger.put("action", "pa:observe:" + watch_id, {"notices": []})
    assert accept(tmp_path)["next"] == expected_next()


@pytest.mark.parametrize("missing", ["notice", "lead", "extra"])
def test_accepted_weather_unknown_inputs_return_manual_note(tmp_path, missing):
    ledger, watch_id = seed(tmp_path)
    if missing == "notice":
        ledger.put("action", "pa:observe:" + watch_id, {"notices": [
            {"id": "n_aaaaaaaa", "weather_extra_minutes": 10}]})
    elif missing == "lead":
        with ledger.connect() as conn:
            conn.execute("delete from pa_events where event_id=?", (trip_watch._event_id("synthetic"),))
    else:
        ledger.put("action", "pa:observe:" + watch_id, {"notices": [
            {"id": OCCURRENCE, "signals": ["Leave by 08:15 (+45 min for snow)"]}]})
    saved = accept(tmp_path)
    assert saved["next"] is None
    assert saved["next_note"] == "replan manually: lead unknown"
    assert saved["fields"]["outcome"] == "accepted"


def test_accepted_weather_without_plan_table_returns_manual_note(tmp_path):
    Ledger(tmp_path)
    saved = accept(tmp_path)
    assert saved["next"] is None
    assert saved["next_note"] == "replan manually: lead unknown"


def test_weather_notice_carries_extra_minutes(tmp_path, monkeypatch):
    ledger = Ledger(tmp_path)
    current = dt.datetime.now(dt.timezone.utc)
    watch_id = trip_watch._watch_id("synthetic")
    watch = {"trip_id": "synthetic", "profile_root": str(ledger.root), "status": "active",
             "departure_at": (current + dt.timedelta(hours=4)).isoformat(),
             "arrival_at": (current + dt.timedelta(hours=7)).isoformat(),
             "airport_lead_minutes": 180, "checks": {"weather": True},
             "origin": {"tz": "UTC"}, "hb2_quiet_hours": ""}
    ledger.put("action", "pa:observe-watch:" + watch_id, watch)
    monkeypatch.setattr(observe.sources, "weather", lambda *args: ({}, "snow"))
    result = observe.probe(ledger, watch_id, watch, {}, time.monotonic() + 10, time.monotonic())
    assert result["fire"] and "+45 min for snow" in result["message"]
    [notice] = ledger.get("action", "pa:observe:" + watch_id)["fields"]["notices"]
    assert notice["offer_type"] == "weather_leave_early"
    assert notice["weather_extra_minutes"] == 45


def test_accepted_weather_status_keeps_offered_leave_by(tmp_path):
    ledger, watch_id = seed(tmp_path)
    trip_watch.plan(ledger, trip_id="synthetic", departure_at="2026-11-10T11:30:00Z",
                    arrival_at="2026-11-10T18:00:00Z", at="2026-11-10T06:00:00Z")
    saved = accept(tmp_path)
    dispatch(tmp_path, saved["next"])
    ledger.put("action", "pa:observe:" + watch_id, {"notices": [], "weather": {
        "last": {"severity": "snow", "at": "2026-11-10T06:00:00Z"}}})
    result = trip_watch.status(ledger, "synthetic", at="2026-11-10T06:00:00Z")
    assert result["leave_by"]["local_time"] == "07:45"
    assert result["leave_by"]["weather_extra_minutes"] == 0
    assert result["inputs"]["weather_included_minutes"] == 45
    assert next(m for m in result["moments"] if m["key"] == "leave_by")["at"] == "2026-11-10T07:45:00+00:00"


def test_accepted_worse_weather_keeps_the_cumulative_buffer(tmp_path):
    # Heavy rain (30) was accepted earlier; snow (45) adds only 15 more. The included buffer must become 45, not 15.
    ledger = Ledger(tmp_path)
    dispatch(tmp_path, {"operation": "trip_watch_plan", "data": {
        "action": "plan", "trip_id": "synthetic", "airport_lead_minutes": 210, "weather_included_minutes": 30,
        "departure_at": "2026-11-10T11:30:00+00:00", "arrival_at": "2026-11-10T18:00:00+00:00",
        "hb2_timezone": "UTC", "at": "2026-11-10T06:00:00+00:00"}})
    watch_id = trip_watch._watch_id("synthetic")
    ledger.put("action", "pa:observe:" + watch_id, {"notices": [
        {"id": OCCURRENCE, "offer_type": "weather_leave_early", "weather_extra_minutes": 15}]})
    saved = accept(tmp_path)
    assert saved["next"]["data"]["airport_lead_minutes"] == 225
    assert saved["next"]["data"]["weather_included_minutes"] == 45
    dispatch(tmp_path, saved["next"])
    ledger.put("action", "pa:observe:" + watch_id, {"notices": [], "weather": {
        "last": {"severity": "snow", "at": "2026-11-10T06:00:00Z"}}})
    assert trip_watch.status(ledger, "synthetic", at="2026-11-10T06:00:00Z")["leave_by"]["local_time"] == "07:45"


def test_legacy_plan_without_included_buffer_writes_zero_to_the_watch(tmp_path):
    import json
    ledger = Ledger(tmp_path)
    dispatch(tmp_path, {"operation": "trip_watch_plan", "data": {
        "action": "plan", "trip_id": "synthetic", "arm": ["watch"], "departure_at": "2026-11-10T11:30:00+00:00",
        "arrival_at": "2026-11-10T18:00:00+00:00", "hb2_timezone": "UTC", "at": "2026-11-10T06:00:00+00:00"}})
    with ledger.connect() as conn:  # A plan saved before this field existed.
        row = conn.execute("select event_id, payload_json from pa_events").fetchone()
        payload = json.loads(row["payload_json"])
        payload["inputs"].pop("weather_included_minutes")
        conn.execute("update pa_events set payload_json=? where event_id=?", (json.dumps(payload), row["event_id"]))
    trip_watch.record_wake(ledger, "synthetic", "watch", "w_legacy", armed=True)
    watch = ledger.get("action", "pa:observe-watch:" + trip_watch._watch_id("synthetic"))["fields"]
    assert watch["weather_included_minutes"] == 0
