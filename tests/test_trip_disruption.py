"""Synthetic disruption reads; no provider, model or calendar calls."""
import datetime as dt
import json

import pytest

from personal_assistant import trip_watch
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger
from personal_assistant.trip_facts import record_facts
from personal_assistant.trips import add_booked_item


TRIP = "synthetic-disruption"
AT = "2026-11-10T08:00:00+00:00"
SEGMENT = {"carrier": "ZZ", "number": "101", "origin": "HND", "destination": "CTS",
           "origin_timezone": "Asia/Tokyo", "destination_timezone": "Asia/Tokyo",
           "scheduled_departure": "2026-11-10T10:00:00+00:00",
           "scheduled_arrival": "2026-11-10T12:00:00+00:00", "status": "scheduled"}
NEXT_STEP = (
    "Prepare 2 or 3 options as one approval packet. Each option names the replacement leg, what happens to each "
    "affected booking (keep, move or cancel, with its cancellation deadline) and the cost and time difference the "
    "provider pages show. Change nothing until the owner picks one option; then prepare each change as its own "
    "exact action and record each confirmed readback with action_result follow_through.")


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)
    result = Ledger(tmp_path)
    result.put("trip", TRIP, {"events": [], "timezone": "Asia/Tokyo"}, status="active")
    return result


def flight(ledger, **changes):
    return record_facts(ledger, TRIP, [{**SEGMENT, **changes}], source="user")["segments"][0]


def booking(ledger, identity, start, title=None):
    item = {"title": title or identity, "start": start, "end": None, "timezone": "Asia/Tokyo",
            "location": "Synthetic location", "reference": "SYNTHETIC-PRIVATE-REFERENCE"}
    ledger.put("action", identity, {"booked_item": item}, trip_id=TRIP, status="confirmed")
    add_booked_item(ledger, TRIP, item, identity)


def read(ledger, **data):
    return trip_watch.dispatch(ledger, {"action": "disruption", "trip_id": TRIP, "at": AT, **data})


def rows(ledger, *, exempt_settings=False):
    """Compare full raw rows, including timestamps, JSON and StateLoop tables."""
    with ledger.connect() as conn:
        tables = [r[0] for r in conn.execute("select name from sqlite_master where type='table' order by name")]
        snapshot = {}
        for table in tables:
            values = [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"')]
            if table == "actions" and exempt_settings:
                values = [row for row in values if row["action_id"] != "pa:observe-settings"]
            snapshot[table] = sorted(values, key=lambda row: json.dumps(row, sort_keys=True))
    return snapshot


@pytest.mark.parametrize("status", ["cancelled", "diverted"])
def test_cancelled_or_diverted_booking_window_and_no_references(ledger, status):
    first = flight(ledger, status=status)
    record_facts(ledger, TRIP, [{**SEGMENT, "number": "102", "origin": "CTS", "destination": "HND",
        "scheduled_departure": "2026-11-11T10:00:00Z", "scheduled_arrival": "2026-11-11T12:00:00Z"}], source="user")
    for identity, start in [("before", "2026-11-10T09:00:00Z"), ("at-departure", "2026-11-10T10:00:00Z"),
                            ("hotel", "2026-11-10T15:00:00Z"), ("dinner", "2026-11-10T18:00:00Z"),
                            ("at-next", "2026-11-11T10:00:00Z"), ("after-next", "2026-11-11T15:00:00Z")]:
        booking(ledger, identity, start)
    result = read(ledger)
    assert [item["booking_action_id"] for item in result["affected"]] == ["hotel", "dinner"]
    assert result["changed_legs"] == [{k: first[k] for k in ("segment_id", "origin", "destination",
        "scheduled_departure", "scheduled_arrival", "destination_timezone")} | {"reason": status}]
    for affected in result["affected"]:
        assert affected["leg"] == first["segment_id"]
        assert affected["reason"] == f"after_{status}_leg" and affected["feasibility"] is None
        assert set(affected) == {"booking_action_id", "title", "start", "end", "timezone", "location", "leg", "reason", "feasibility"}
    assert "reference" not in json.dumps(result).lower()
    assert "SYNTHETIC-PRIVATE" not in json.dumps(result)
    assert result["next_step"] == NEXT_STEP


def test_90_minute_delay_affects_dinner_but_not_later_check_in(ledger):
    flight(ledger, status="delayed", estimated_arrival="2026-11-10T13:30:00Z")
    booking(ledger, "dinner", "2026-11-10T13:00:00Z", "Synthetic dinner")
    booking(ledger, "check-in", "2026-11-10T18:00:00Z")
    result = read(ledger)
    assert result["changed_legs"][0]["delay_minutes"] == 90
    assert result["changed_legs"][0]["estimated_arrival"] == "2026-11-10T13:30:00+00:00"
    assert len(result["affected"]) == 1
    item = result["affected"][0]
    assert item["title"] == "Synthetic dinner" and item["reason"] == "unreachable"
    assert item["feasibility"]["reachable"] is False
    assert item["feasibility"]["slack_minutes"] == -135
    assert item["feasibility"]["timezone"] == "Asia/Tokyo"
    assert item["feasibility"]["basis"] == "estimated"


@pytest.mark.parametrize("minutes,changed", [(30, False), (44, False), (45, True), (90, True)])
def test_estimate_delay_threshold_without_delayed_status(ledger, minutes, changed):
    estimated = dt.datetime.fromisoformat(SEGMENT["scheduled_arrival"]) + dt.timedelta(minutes=minutes)
    flight(ledger, estimated_arrival=estimated.isoformat())
    result = read(ledger)
    assert bool(result["changed_legs"]) is changed
    if changed:
        assert result["changed_legs"][0]["reason"] == "delayed"
        assert result["changed_legs"][0]["delay_minutes"] == minutes
    else:
        assert result["next_step"] == ""


def test_delayed_status_without_estimate_preserves_unknown_delay(ledger):
    flight(ledger, status="delayed")
    assert read(ledger)["changed_legs"][0]["delay_minutes"] is None


@pytest.mark.parametrize("minutes,reason", [(30, None), (45, "rescheduled"), (50, "rescheduled"), (-50, "rescheduled")])
@pytest.mark.parametrize("field", ["scheduled_departure", "scheduled_arrival"])
def test_schedule_shift_against_saved_baseline(ledger, minutes, reason, field):
    flight(ledger)
    trip_watch.plan(ledger, TRIP, at=AT)
    shifted = dt.datetime.fromisoformat(SEGMENT[field]) + dt.timedelta(minutes=minutes)
    flight(ledger, **{field: shifted.isoformat()})
    result = read(ledger)
    if reason:
        assert result["changed_legs"][0]["reason"] == reason
        assert result["changed_legs"][0]["shift_minutes"] == abs(minutes)
    else:
        assert result["changed_legs"] == [] and result["next_step"] == ""


def test_rescheduled_leg_uses_new_arrival_for_feasibility(ledger):
    flight(ledger)
    trip_watch.plan(ledger, TRIP, at=AT)
    flight(ledger, scheduled_arrival="2026-11-10T12:50:00Z")
    booking(ledger, "dinner", "2026-11-10T14:30:00Z")
    result = read(ledger)
    assert result["changed_legs"][0]["reason"] == "rescheduled"
    assert result["affected"][0]["reason"] == "unreachable"
    assert result["affected"][0]["feasibility"]["landing_at"] == "2026-11-10T12:50:00+00:00"


def test_changed_signature_does_not_compare_unrelated_schedule(ledger):
    flight(ledger)
    trip_watch.plan(ledger, TRIP, at=AT)
    flight(ledger, destination="KIX", scheduled_arrival="2026-11-10T12:50:00Z")
    assert read(ledger)["changed_legs"] == []


@pytest.mark.parametrize("start,reason", [("15:29", "tight"), ("15:30", None)])
def test_tight_slack_boundary(ledger, start, reason):
    flight(ledger, estimated_arrival="2026-11-10T13:00:00Z")
    booking(ledger, "dinner", f"2026-11-10T{start}:00Z")
    result = read(ledger)
    if reason:
        assert result["affected"][0]["reason"] == reason
        assert result["affected"][0]["feasibility"]["reachable"] is True
    else:
        assert result["affected"] == []


def test_reminders_are_only_pending_booking_reminders_for_affected_items(ledger):
    flight(ledger, status="cancelled")
    booking(ledger, "hotel", "2026-11-10T15:00:00Z")
    for identity, parent, status, kind in [("hotel:reminder:1", "hotel", "pending", "booking"),
            ("hotel:reminder:2", "hotel", "completed", "booking"),
            ("other:reminder:1", "other", "pending", "booking"),
            ("ordinary", "hotel", "pending", "other")]:
        ledger.put("action", identity, {"title": "Synthetic deadline", "due_at": AT,
            "reminder_kind": kind, "booking_action_id": parent}, action_type="commitment", status=status)
    assert read(ledger)["reminders"] == [{"action_id": "hotel:reminder:1", "title": "Synthetic deadline", "due_at": AT}]


@pytest.mark.parametrize("through_entry", [False, True])
def test_full_rows_unchanged_except_wrapper_settings_snapshot(ledger, through_entry):
    flight(ledger)
    trip_watch.plan(ledger, TRIP, at=AT)
    flight(ledger, status="cancelled")
    booking(ledger, "hotel", "2026-11-10T15:00:00Z")
    ledger.put("action", "hotel:reminder:1", {"title": "Cancel by", "due_at": AT,
        "reminder_kind": "booking", "booking_action_id": "hotel"}, status="pending")
    ledger.put("action", "hotel:loop", {"loop_kind": "waiting_on_them", "next_step": "Wait"}, status="open")
    trip_watch.snapshot_settings(ledger, {"delay_minutes": 60})
    before = rows(ledger, exempt_settings=through_entry)
    if through_entry:
        result = dispatch(ledger.root, {"operation": "trip_watch_plan", "data": {
            "action": "disruption", "trip_id": TRIP, "at": AT}}, runtime_scope={
                "session_id": "synthetic-session", "observe_settings": {"delay_minutes": 45}})
        assert ledger.get("action", "pa:observe-settings")["fields"] == {"delay_minutes": 45}
    else:
        result = read(Ledger(ledger.root, read_only=True))
    assert result["affected"] and result["reminders"]
    assert rows(ledger, exempt_settings=through_entry) == before


def test_no_facts_hint_and_default_at(ledger):
    before = rows(ledger)
    result = trip_watch.dispatch(ledger, {"action": "disruption", "trip_id": TRIP})
    assert result["changed_legs"] == result["affected"] == result["reminders"] == []
    assert "record_facts" in result["next_step"]
    assert dt.datetime.fromisoformat(result["at"]).utcoffset() is not None
    assert rows(ledger) == before


@pytest.mark.parametrize("elapsed,changed", [(360, True), (361, False)])
def test_old_landed_legs_are_ignored(ledger, elapsed, changed):
    flight(ledger, status="landed", estimated_arrival="2026-11-10T13:00:00Z")
    at = dt.datetime.fromisoformat(SEGMENT["scheduled_departure"]) + dt.timedelta(minutes=elapsed)
    assert bool(read(ledger, at=at.isoformat())["changed_legs"]) is changed


def test_cancelled_leg_is_not_the_next_live_boundary(ledger):
    flight(ledger, status="cancelled")
    record_facts(ledger, TRIP, [{**SEGMENT, "number": "102", "status": "cancelled",
        "scheduled_departure": "2026-11-10T14:00:00Z", "scheduled_arrival": "2026-11-10T16:00:00Z"}], source="user")
    booking(ledger, "hotel", "2026-11-10T18:00:00Z")
    result = read(ledger)
    assert len(result["changed_legs"]) == 2
    assert len(result["affected"]) == 2
    assert {item["leg"] for item in result["affected"]} == {leg["segment_id"] for leg in result["changed_legs"]}


def test_naive_at_is_rejected_without_writes(ledger):
    before = rows(ledger)
    with pytest.raises(ValueError, match="timezone"):
        read(ledger, at="2026-11-10T08:00:00")
    assert rows(ledger) == before
