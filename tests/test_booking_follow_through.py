"""Synthetic provider readbacks: no provider, model or calendar calls."""
import copy
import datetime as dt
import json
from pathlib import Path

import pytest
from icalendar import Calendar
from jsonschema import Draft7Validator

from personal_assistant.action_gateway import ActionAuthorizationStore, Gateway, GatewayPolicy
from personal_assistant.automation import upsert_automation_rule
from personal_assistant.automation_workflow import cron_precheck, preferences
from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.state import Ledger, stable_id


ACTION = "fixture-booking"
TRIP = "fixture-trip"
SUMMARY = {"provider": "fixture-provider", "final_action": "reserve room"}
READBACK = {
    "item": {"kind": "hotel", "title": "Fixture stay", "start": "2026-11-12T15:00:00+09:00",
             "end": "2026-11-13T10:00:00+09:00", "timezone": "Asia/Tokyo",
             "location": "Fixture hotel", "reference": "SYNTHETIC-123"},
    "reminders": [{"label": "Cancellation deadline", "due_at": "2026-11-10T15:00:00+09:00"},
                  {"label": "Leave for hotel", "due_at": "2026-11-12T13:00:00+09:00"}],
}
OTHER = {"uid": "untouched", "summary": "Existing event", "start": "2026-11-14T15:00:00+09:00",
         "timezone": "Asia/Tokyo", "all_day": False, "source_record_id": "other"}


def daily_ops(write):
    """A configuration daily-ops itself accepts, with the given calendar write scope."""
    return {"tenant": {"profile_id": "fixture-profile", "owner_email": "owner@example.invalid"},
            "delivery": {"target": "fixture-topic", "verified": True}, "timezone": "Asia/Tokyo",
            "accounts": {"work": "owner@example.invalid", "personal": None},
            "calendar": {"provider": "gog", "read_scope": {"accepted": True, "calendar_ids": ["primary"]},
                         "write_scope": write}}


VALID_WRITE = {"accepted": True, "calendar_ids": ["primary"], "invites": False}


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)
    monkeypatch.setenv("DAILY_OPS_CONFIG", str(tmp_path / "missing-config.json"))
    result = Ledger(tmp_path)
    result.put("trip", TRIP, {"events": [OTHER], "timezone": "Asia/Tokyo"}, status="active")
    return result


def prepare(ledger, *, governed=True, trip_id=TRIP, claim=True):
    if trip_id:
        ledger.put("action", ACTION, {}, action_type="note", trip_id=trip_id)
    data = {"action_id": ACTION, "summary": SUMMARY}
    scope = {"session_id": "fixture-session", "task_id": "fixture-task"}
    if governed:
        data.update({
            "enforcement_profile": "exact_action", "action_revision": "r1", "workflow_id": "booking",
            "workflow_revision": "v1", "tool_name": "fixture_reserve", "tool_args": {"room": "fixture"},
            "semantic_target": {"paths": [["room"]], "value": ["fixture"]},
            "fresh_until": "2030-01-01T00:00:00+00:00", "execution_budget": 1,
            "required_pre_action_projections": ["authority"], "preconditions": {"authority": "confirmed"},
            "expected_readback": "booking/v1",
        })
    dispatch(ledger.root, {"operation": "action_prepare", "data": data}, runtime_scope=scope)
    dispatch(ledger.root, {"operation": "action_confirm", "data": {
        "action_id": ACTION, "summary": SUMMARY, "confirmation": "Reserve these exact details",
    }}, runtime_scope=scope)
    if claim:
        if governed:
            store = ActionAuthorizationStore(ledger, ledger.root.name)
            policy = GatewayPolicy.from_dict({"protocol": "pa.gateway-policy/v1", "version": "fixture-v1",
                                              "pass_through_tools": [], "denied_tools": []})
            gateway = Gateway(store, policy, now=lambda: "2026-11-09T00:00:00+00:00")
            assert gateway.evaluate({"tool_name": "fixture_reserve", "tool_input": {"room": "fixture"},
                                     **scope}) is None
        else:
            dispatch(ledger.root, {"operation": "action_claim", "data": data})


def record(ledger, value=READBACK, outcome="confirmed"):
    return dispatch(ledger.root, {"operation": "action_result", "data": {
        "action_id": ACTION, "outcome": outcome, "proof": "Synthetic provider readback",
        "follow_through": copy.deepcopy(value),
    }})


@pytest.mark.parametrize("governed", [True, False])
def test_confirmed_bookkeeping_through_dispatch(ledger, governed):
    prepare(ledger, governed=governed)
    result = record(ledger)
    assert result["status"] == ("verified" if governed else "confirmed")
    assert ledger.get("action", ACTION)["fields"]["booked_item"] == READBACK["item"]
    assert ledger.get("action", ACTION)["trip_id"] == TRIP
    events = ledger.get("trip", TRIP)["fields"]["events"]
    assert len(events) == 2 and events[0] == OTHER
    event = events[1]
    source_id = stable_id(TRIP, f"pa-booking:{ACTION}", "master")
    assert event == {
        "uid": f"pa-booking:{ACTION}", "recurrence_id": "", "summary": "Fixture stay",
        "start": READBACK["item"]["start"], "end": READBACK["item"]["end"],
        "all_day": False, "timezone": "Asia/Tokyo", "location": "Fixture hotel",
        "description": "Booked", "url": "", "status": "CONFIRMED",
        "source_url": "", "warnings": [], "verified_at": event["verified_at"],
        "source_record_id": source_id, "source": "provider_readback", "booking_action_id": ACTION,
    }
    assert dt.datetime.fromisoformat(event["verified_at"]).utcoffset() == dt.timedelta(0)
    for n, reminder in enumerate(READBACK["reminders"], 1):
        row = ledger.get("action", f"{ACTION}:reminder:{n}")
        assert row["action_type"] == "commitment" and row["trip_id"] is None
        assert row["fields"] == {"title": reminder["label"], "due_at": reminder["due_at"],
                                 "timezone": "Asia/Tokyo", "booking_action_id": ACTION,
                                 "reminder_kind": "booking", "trip_ref": TRIP}
    follow = result["follow_through"]
    assert follow["trip_item"] == source_id and follow["trip_note"] == f"added to {TRIP}"
    assert follow["reminders"] == [f"{ACTION}:reminder:1", f"{ACTION}:reminder:2"]
    path = Path(follow["ics_path"])
    assert path == ledger.root / "exports" / "bookings" / f"{ACTION}.ics"
    parsed = Calendar.from_ical(path.read_bytes()).walk("VEVENT")
    assert len(parsed) == 1
    for name, field in (("DTSTART", "start"), ("DTEND", "end")):
        assert parsed[0].decoded(name) == dt.datetime.fromisoformat(READBACK["item"][field])
    assert str(parsed[0]["SUMMARY"]) == "Fixture stay"
    assert str(parsed[0]["UID"]) == f"pa-booking:{ACTION}"
    assert "ATTENDEE" not in parsed[0] and not parsed[0].walk("VALARM")
    assert not (path.parent / "Trip.ics").exists()
    assert follow["calendar_write_allowed"] is False
    assert follow["next_step"] == "Calendar write is not granted: give the owner the ICS file and say the booking is not on their calendar yet."


@pytest.mark.parametrize("governed", [True, False])
def test_rerecord_replaces_event_and_cancels_dropped_reminders(ledger, governed):
    prepare(ledger, governed=governed)
    first = record(ledger)
    updated = copy.deepcopy(READBACK)
    updated["item"]["title"] = "Updated readback title"
    updated["reminders"] = updated["reminders"][:1]
    second = record(ledger, updated)
    events = ledger.get("trip", TRIP)["fields"]["events"]
    assert len(events) == 2 and events[0] == OTHER
    assert events[1]["summary"] == updated["item"]["title"]
    assert second["follow_through"]["ics_path"] == first["follow_through"]["ics_path"]
    assert ledger.get("action", f"{ACTION}:reminder:2")["status"] == "cancelled"
    updated["reminders"] = []
    record(ledger, updated)
    assert ledger.get("action", f"{ACTION}:reminder:1")["status"] == "cancelled"


@pytest.mark.parametrize("supplied_trip", [None, TRIP])
def test_trip_fallback_or_no_trip(ledger, supplied_trip):
    prepare(ledger, trip_id=None)
    value = copy.deepcopy(READBACK)
    if supplied_trip:
        value["trip_id"] = supplied_trip
    result = record(ledger, value)
    assert ledger.get("action", ACTION)["trip_id"] is None
    follow = result["follow_through"]
    if supplied_trip:
        assert follow["trip_item"] and follow["trip_note"] == f"added to {TRIP}"
        assert len(ledger.get("trip", TRIP)["fields"]["events"]) == 2
    else:
        assert follow["trip_item"] is None and follow["trip_note"] == "no trip on this action"
        assert ledger.get("trip", TRIP)["fields"]["events"] == [OTHER]
        assert "trip_ref" not in ledger.get("action", f"{ACTION}:reminder:1")["fields"]


@pytest.mark.parametrize("change,field,outcome", [
    ({}, "follow_through", "failed"), ({}, "follow_through", "unknown"),
    ({"item.end": "2026-11-12T14:00:00+09:00"}, "item.end", "confirmed"),
    ({"item.start": "2026-11-12T15:00:00"}, "item.start", "confirmed"),
    ({"item.end": "2026-11-13T10:00:00"}, "item.end", "confirmed"),
    ({"item.timezone": "Invalid/Zone"}, "item.timezone", "confirmed"),
    ({"item.kind": "invented"}, "item.kind", "confirmed"),
    ({"item.title": ""}, "item.title", "confirmed"),
    ({"item.extra": "unknown"}, "item.extra", "confirmed"),
    ({"extra": "unknown"}, "follow_through.extra", "confirmed"),
    ({"reminders": [{"label": "late", "due_at": "2026-11-12T16:00:00+09:00"}]}, "due_at", "confirmed"),
    ({"reminders": [{"label": "early", "due_at": "2026-10-12T14:00:00+09:00"}]}, "due_at", "confirmed"),
    ({"reminders": [{"label": "floating", "due_at": "2026-11-10T14:00:00"}]}, "due_at", "confirmed"),
    ({"reminders": [{"label": "x", "due_at": "2026-11-10T14:00:00+09:00", "x": 1}]}, "reminders", "confirmed"),
    ({"reminders": READBACK["reminders"] * 2}, "reminders", "confirmed"),
    ({"trip_id": "missing"}, "trip_id", "confirmed"),
])
def test_refusals_write_nothing(ledger, change, field, outcome):
    prepare(ledger, trip_id=None)
    value = copy.deepcopy(READBACK)
    for key, changed in change.items():
        if key.startswith("item."):
            value["item"][key.split(".")[1]] = changed
        else:
            value[key] = changed
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match=field):
        record(ledger, value, outcome)
    assert ledger.path.read_bytes() == before
    assert not (ledger.root / "exports").exists()
    assert not any(":reminder:" in row["action_id"] for row in ledger.list("action"))


def test_different_existing_trip_refused(ledger):
    ledger.put("trip", "other-trip", {"events": []})
    prepare(ledger)
    value = {**READBACK, "trip_id": "other-trip"}
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="follow_through.trip_id"):
        record(ledger, value)
    assert ledger.path.read_bytes() == before
    assert not (ledger.root / "exports").exists()


@pytest.mark.parametrize("field", ["kind", "title", "start", "timezone"])
def test_required_item_fields(ledger, field):
    prepare(ledger)
    value = copy.deepcopy(READBACK)
    del value["item"][field]
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match=f"item.{field}"):
        record(ledger, value)
    assert ledger.path.read_bytes() == before


def test_failed_transition_does_not_bookkeep(ledger):
    prepare(ledger, claim=False)
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="state"):
        record(ledger)
    assert ledger.path.read_bytes() == before
    assert not (ledger.root / "exports").exists()


@pytest.mark.parametrize("config,allowed", [
    (daily_ops(VALID_WRITE), True),
    (daily_ops(dict(VALID_WRITE, accepted=False)), False),
    (daily_ops(dict(VALID_WRITE, accepted="true")), False),
    # Accepted but rejected by daily-ops validation: no calendar IDs, or a calendar it cannot read.
    (daily_ops(dict(VALID_WRITE, calendar_ids=[])), False),
    (daily_ops(dict(VALID_WRITE, calendar_ids=["elsewhere"])), False),
    ({"calendar": {"write_scope": {"accepted": True}}}, False),
    ({"calendar": None}, False), (None, False), ("unreadable", False),
])
def test_calendar_scope_is_explicit_and_config_failure_is_safe(ledger, monkeypatch, config, allowed):
    path = ledger.root / "config-fixture.json"
    if config == "unreadable":
        path.mkdir()
    elif config is not None:
        path.write_text(json.dumps(config))
    monkeypatch.setenv("DAILY_OPS_CONFIG", str(path))
    prepare(ledger)
    result = record(ledger)["follow_through"]
    assert result["calendar_write_allowed"] is allowed
    assert result["calendar_ids"] == (["primary"] if allowed else [])
    if allowed:
        assert result["next_step"] == "Create a private event on one of calendar_ids with these exact fields (no attendees, no notifications), read it back, then record it with action_upsert."


def test_reminder_wakes_before_trip_starts(ledger):
    preferences(ledger, {"timezone": "UTC"})
    upsert_automation_rule(ledger, "due_source_check", {
        "kind": "due_source_check", "accepted": True, "timezone": "UTC",
        "destination": "fixture-owner", "destination_verified": True,
    })
    prepare(ledger)
    record(ledger)
    wake = cron_precheck(ledger, "due_source_check", enabled=True,
                         moment=dt.datetime.fromisoformat("2026-11-10T08:00:00+00:00"))
    assert wake["wakeAgent"] and f"{ACTION}:reminder:1" in wake["due_action_ids"]


def test_without_follow_through_preserves_result_contract(ledger):
    prepare(ledger, governed=False)
    result = dispatch(ledger.root, {"operation": "action_result", "data": {
        "action_id": ACTION, "outcome": "confirmed", "proof": "Synthetic readback",
    }})
    assert result["status"] == "confirmed" and "follow_through" not in result
    assert "booked_item" not in result["fields"]
    assert ledger.get("trip", TRIP)["fields"]["events"] == [OTHER]
    assert not (ledger.root / "exports").exists()
    with pytest.raises(ValueError, match="state"):
        ledger.result(ACTION, "confirmed", "Synthetic readback")


def test_optional_readback_fields_are_not_invented(ledger):
    prepare(ledger)
    value = {"item": {k: v for k, v in READBACK["item"].items() if k in {"kind", "title", "start", "timezone"}}}
    result = record(ledger, value)
    assert result["fields"]["booked_item"] == value["item"]
    event = ledger.get("trip", TRIP)["fields"]["events"][-1]
    assert event["end"] is None and event["description"] == "Booked"
    assert "DTEND" not in Calendar.from_ical(Path(result["follow_through"]["ics_path"]).read_bytes()).walk("VEVENT")[0]


def test_follow_through_schema():
    validator = Draft7Validator(SCHEMA["parameters"])
    request = {"operation": "action_result", "data": {
        "action_id": ACTION, "outcome": "confirmed", "follow_through": READBACK,
    }}
    assert not list(validator.iter_errors(request))
    for value in ({**READBACK, "extra": True}, {**READBACK, "item": {**READBACK["item"], "extra": True}},
                  {**READBACK, "reminders": READBACK["reminders"] * 2}):
        request["data"]["follow_through"] = value
        assert list(validator.iter_errors(request))
    request["data"]["follow_through"] = READBACK
    request["data"]["outcome"] = "failed"
    assert list(validator.iter_errors(request))


def test_rerecord_keeps_handled_reminders(ledger):
    prepare(ledger)
    record(ledger)
    first, second = f"{ACTION}:reminder:1", f"{ACTION}:reminder:2"
    ledger.put("action", first, {}, status="completed")
    ledger.put("action", second, {}, status="dismissed")
    one = copy.deepcopy(READBACK)
    one["reminders"] = one["reminders"][:1]
    record(ledger, one)
    # Same time: a handled reminder is not reopened; a dropped handled one is not cancelled.
    assert ledger.get("action", first)["status"] == "completed"
    assert ledger.get("action", second)["status"] == "dismissed"
    moved = copy.deepcopy(one)
    moved["reminders"][0]["due_at"] = "2026-11-10T18:00:00+09:00"
    record(ledger, moved)
    assert ledger.get("action", first)["status"] == "pending"


def test_calendar_scope_read_from_the_profile_config(ledger, monkeypatch):
    monkeypatch.delenv("DAILY_OPS_CONFIG", raising=False)
    monkeypatch.chdir(ledger.root.parent)
    (ledger.root / "daily_ops.config.json").write_text(json.dumps(daily_ops(VALID_WRITE)), encoding="utf-8")
    prepare(ledger)
    assert record(ledger)["follow_through"]["calendar_write_allowed"] is True


def test_trip_reimport_keeps_the_booked_item(ledger):
    from personal_assistant.trips import import_trip
    prepare(ledger)
    record(ledger)
    ics = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//fixture//EN\r\nBEGIN:VEVENT\r\nUID:flight-1\r\n"
           b"DTSTAMP:20261101T000000Z\r\nDTSTART:20261112T010000Z\r\nDTEND:20261112T030000Z\r\n"
           b"SUMMARY:Fixture flight\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    import_trip(ledger, TRIP, ics, title="Fixture trip", timezone="Asia/Tokyo")
    events = ledger.get("trip", TRIP)["fields"]["events"]
    booked = [e for e in events if e.get("uid") == f"pa-booking:{ACTION}"]
    assert len(booked) == 1 and not booked[0].get("source_missing")
    assert any(e.get("uid") == "untouched" and e.get("source_missing") for e in events)


def test_fallback_trip_sticks_across_rerecords(ledger):
    ledger.put("trip", "other-trip", {"events": [], "timezone": "Asia/Tokyo"}, status="active")
    prepare(ledger, trip_id=None)
    record(ledger, dict(copy.deepcopy(READBACK), trip_id=TRIP))
    with pytest.raises(ValueError, match="recorded on"):
        record(ledger, dict(copy.deepcopy(READBACK), trip_id="other-trip"))
    assert ledger.get("trip", "other-trip")["fields"]["events"] == []
    # Omitting the trip on a later re-record keeps the booking on its trip.
    assert record(ledger)["follow_through"]["trip_note"] == f"added to {TRIP}"
    booked = [e for e in ledger.get("trip", TRIP)["fields"]["events"] if e.get("uid") == f"pa-booking:{ACTION}"]
    assert len(booked) == 1


def test_trip_event_carries_no_booking_reference(ledger):
    prepare(ledger)
    follow = record(ledger)["follow_through"]
    event = next(e for e in ledger.get("trip", TRIP)["fields"]["events"] if e.get("uid") == f"pa-booking:{ACTION}")
    assert "SYNTHETIC-123" not in json.dumps(event)
    # The owner's own booking file keeps the reference for their calendar.
    assert "SYNTHETIC-123" in Path(follow["ics_path"]).read_text()


def test_moved_booking_pauses_derived_actions(ledger):
    prepare(ledger)
    follow = record(ledger)["follow_through"]
    ledger.put("action", "fixture-derived", {"title": "Leave for the hotel", "source_record_id": follow["trip_item"],
               "source_fields": ["start"], "derived_fields": ["leave_by"], "leave_by": "x"}, status="pending")
    record(ledger)  # Same readback: nothing changed, nothing paused.
    assert ledger.get("action", "fixture-derived")["status"] == "pending"
    moved = copy.deepcopy(READBACK)
    moved["item"]["start"] = "2026-11-12T16:00:00+09:00"
    record(ledger, moved)
    derived = ledger.get("action", "fixture-derived")
    assert derived["status"] == "paused" and "leave_by" not in derived["fields"]
