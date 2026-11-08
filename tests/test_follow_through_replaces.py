"""Synthetic move/cancel readbacks and the two expense replay regressions."""
import copy

import pytest
from jsonschema import Draft7Validator

from personal_assistant.entry import SCHEMA, dispatch
from test_booking_follow_through import ACTION, OTHER, READBACK, TRIP, ledger, prepare, record


NEW = "fixture-replacement"
EXPENSE = {"amount": "25", "currency": "JPY", "category": "food"}


def replace(ledger, value):
    return dispatch(ledger.root, {"operation": "action_result", "data": {
        "action_id": NEW, "outcome": "confirmed", "proof": "Synthetic replacement readback",
        "follow_through": value,
    }})["follow_through"]


def booked(ledger, *, governed=True, trip_id=TRIP):
    prepare(ledger, governed=governed, trip_id=trip_id)
    record(ledger, {**copy.deepcopy(READBACK), "expense": EXPENSE})


@pytest.mark.parametrize("governed", [True, False])
@pytest.mark.parametrize("handled", ["completed", "confirmed", "dismissed", "cancelled"])
def test_move_retires_only_old_event_and_pending_reminders(ledger, governed, handled):
    booked(ledger, governed=governed)
    ledger.put("action", f"{ACTION}:reminder:2", {}, status=handled)
    ledger.put("action", f"{ACTION}:reminder:3", {"title": "Paused deadline"}, status="paused")
    old = ledger.get("action", ACTION)
    expense = ledger.get("action", f"{ACTION}:expense")
    handled_row = ledger.get("action", f"{ACTION}:reminder:2")
    prepare(ledger, action_id=NEW, governed=governed)
    value = {**copy.deepcopy(READBACK), "replaces": ACTION}
    value["item"]["title"] = "Moved stay"
    value["item"]["start"] = "2026-11-12T16:00:00+09:00"
    result = replace(ledger, value)
    events = ledger.get("trip", TRIP)["fields"]["events"]
    assert len(events) == 2 and events[0] == OTHER
    assert events[1]["booking_action_id"] == NEW and events[1]["summary"] == "Moved stay"
    assert result["replaced"] == ACTION
    assert result["cancelled_reminders"] == [f"{ACTION}:reminder:1", f"{ACTION}:reminder:3"]
    for n in (1, 3):
        assert ledger.get("action", f"{ACTION}:reminder:{n}")["status"] == "cancelled"
    assert ledger.get("action", f"{ACTION}:reminder:2") == handled_row
    replacement_link = ledger.get("action", ACTION)
    assert replacement_link["fields"] == {**old["fields"], "replaced_by": NEW}
    for key in ("status", "action_type", "provider", "trip_id", "created_at"):
        assert replacement_link[key] == old[key]
    assert ledger.get("action", f"{ACTION}:expense") == expense
    assert ledger.get("action", f"{NEW}:reminder:1")["status"] == "pending"
    # The internal replacement link does not open generic writes to the old transaction.
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="transaction"):
        dispatch(ledger.root, {"operation": "action_upsert", "data": {
            "action_id": ACTION, "fields": {"replaced_by": "unrelated"}}})
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("event_only", [False, True])
def test_replaces_alone_cancels_booking_even_if_only_event_records_it(ledger, event_only):
    if event_only:
        from personal_assistant.trips import add_booked_item
        ledger.put("action", ACTION, {}, trip_id=TRIP)
        add_booked_item(ledger, TRIP, READBACK["item"], ACTION)
        ledger.put("action", f"{ACTION}:reminder:1", {}, status="pending")
    else:
        booked(ledger)
    prepare(ledger, action_id=NEW)
    expense = ledger.get("action", f"{ACTION}:expense")
    result = replace(ledger, {"replaces": ACTION})
    assert ledger.get("trip", TRIP)["fields"]["events"] == [OTHER]
    assert ledger.get("action", ACTION)["fields"]["replaced_by"] == NEW
    assert ledger.get("action", f"{ACTION}:reminder:1")["status"] == "cancelled"
    assert result["trip_item"] is None and result["ics_path"] is None
    assert result["replaced"] == ACTION and result["cancelled_reminders"]
    assert ledger.get("action", f"{ACTION}:expense") == expense
    assert replace(ledger, {"replaces": ACTION})["cancelled_reminders"] == []
    assert ledger.get("trip", TRIP)["fields"]["events"] == [OTHER]


@pytest.mark.parametrize("case", ["unknown", "self", "no-booking", "already-replaced",
                                  "trip-mismatch", "recorded-trip-mismatch", "empty", "whitespace", "nonstring"])
def test_replacement_refusals_leave_ledger_byte_identical(ledger, case):
    booked(ledger)
    prepare(ledger, action_id=NEW)
    target = ACTION
    if case == "unknown":
        target = "unknown"
    elif case == "self":
        target = NEW
    elif case == "no-booking":
        target = "ordinary-note"
        ledger.put("action", target, {"title": "No booking"})
    elif case == "already-replaced":
        prepare(ledger, action_id="another-replacement")
        ledger.result("another-replacement", "confirmed", "Synthetic cancellation", {"replaces": ACTION})
    elif case in {"trip-mismatch", "recorded-trip-mismatch"}:
        ledger.put("trip", "another-trip", {"events": []})
        # The target booking may be known through either row-level trip or booking_trip_id.
        with ledger.connect() as conn:
            conn.execute("update actions set trip_id=? where action_id=?", ("another-trip", NEW))
            if case == "recorded-trip-mismatch":
                conn.execute("update actions set trip_id=NULL where action_id=?", (ACTION,))
    elif case == "empty":
        target = ""
    elif case == "whitespace":
        target = "   "
    elif case == "nonstring":
        target = 123
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="replaces"):
        replace(ledger, {"replaces": target})
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("move", [False, True])
def test_replacement_rerecord_is_idempotent(ledger, monkeypatch, move):
    monkeypatch.setattr("personal_assistant.state.now", lambda: "2026-11-09T00:00:00+00:00")
    monkeypatch.setattr("personal_assistant.trips.now", lambda: "2026-11-09T00:00:00+00:00")
    booked(ledger)
    prepare(ledger, action_id=NEW)
    value = {"replaces": ACTION, **(copy.deepcopy(READBACK) if move else {})}
    replace(ledger, value)
    before = ledger.list("trip"), ledger.list("action")
    result = replace(ledger, value)
    assert (ledger.list("trip"), ledger.list("action")) == before
    assert result["replaced"] == ACTION and result["cancelled_reminders"] == []


def test_no_trip_booking_can_be_cancelled(ledger):
    booked(ledger, trip_id=None)
    prepare(ledger, action_id=NEW, trip_id=None)
    assert replace(ledger, {"replaces": ACTION})["replaced"] == ACTION
    assert ledger.get("trip", TRIP)["fields"]["events"] == [OTHER]


def test_schema_and_description_cover_replaces_and_disruption():
    validator = Draft7Validator(SCHEMA["parameters"])
    payload = {"operation": "action_result", "data": {
        "action_id": NEW, "outcome": "confirmed", "proof": "Synthetic", "follow_through": {"replaces": ACTION}}}
    assert list(validator.iter_errors(payload)) == []
    payload["data"]["follow_through"] = {"replaces": ""}
    assert list(validator.iter_errors(payload))
    payload["data"]["follow_through"] = {}
    assert list(validator.iter_errors(payload))
    description = SCHEMA["parameters"]["properties"]["data"]["description"]
    assert "disruption" in description and "follow_through.replaces" in description


def test_expense_only_replay_without_trip_keeps_stored_trip(ledger):
    prepare(ledger, trip_id=None)
    record(ledger, {"trip_id": TRIP, "expense": EXPENSE})
    assert "booking_trip_id" not in ledger.get("action", ACTION)["fields"]
    record(ledger, {"expense": EXPENSE})
    assert ledger.get("action", f"{ACTION}:expense")["fields"]["trip_ref"] == TRIP


def test_voided_owner_receipt_without_merchant_stays_void(ledger):
    receipt = {**EXPENSE, "date": "2026-11-09", "evidence_ref": "synthetic-receipt", "merchant": "Fixture cafe"}
    row = dispatch(ledger.root, {"operation": "expense", "data": {"action": "record", "expense": receipt}})
    dispatch(ledger.root, {"operation": "expense", "data": {
        "action": "void", "expense_id": row["action_id"], "reason": "duplicate"}})
    receipt.pop("merchant")
    row = dispatch(ledger.root, {"operation": "expense", "data": {"action": "record", "expense": receipt}})
    assert row["status"] == "void" and row["fields"]["void_reason"] == "duplicate"


def test_replaced_booking_cannot_come_back_by_rerecording_its_readback(ledger):
    booked(ledger)
    prepare(ledger, action_id=NEW)
    replace(ledger, {**copy.deepcopy(READBACK), "replaces": ACTION})
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="replaced"):
        record(ledger, copy.deepcopy(READBACK))
    assert ledger.path.read_bytes() == before
    assert ledger.get("action", f"{ACTION}:reminder:1")["status"] == "cancelled"


@pytest.mark.parametrize("move", [False, True])
def test_replaces_invalidates_actions_derived_from_retired_event(ledger, move):
    booked(ledger)
    event = next(e for e in ledger.get("trip", TRIP)["fields"]["events"]
                 if e.get("booking_action_id") == ACTION)
    ledger.put("action", "derived-transfer", {
        "source_record_id": event["source_record_id"], "source_fields": ["start"],
        "derived_fields": ["due_at"], "due_at": READBACK["item"]["start"],
        "title": "Transfer to retired booking"}, status="pending")
    ledger.put("action", "other-derived", {"source_record_id": OTHER["source_record_id"],
        "source_fields": ["start"], "derived_fields": ["due_at"], "due_at": OTHER["start"]}, status="pending")
    untouched = ledger.get("action", "other-derived")
    prepare(ledger, action_id=NEW)
    value = {"replaces": ACTION, **(copy.deepcopy(READBACK) if move else {})}
    replace(ledger, value)
    derived = ledger.get("action", "derived-transfer")
    assert derived["status"] == "paused"
    assert derived["fields"]["blocked_reason"] == "source details changed; recompute before resuming"
    assert "due_at" not in derived["fields"]
    assert ledger.get("action", "other-derived") == untouched
    replace(ledger, value)
    assert ledger.get("action", "derived-transfer") == derived
