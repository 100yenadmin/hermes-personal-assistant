"""action_prepare keeps the trip it was prepared for (#273), through real PA dispatch with synthetic data."""
import os
import tempfile
from pathlib import Path

import pytest

from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger
from tests.test_auto_exact_action import SESSION_ID, TASK_ID, governed_data

TRIP = "trip-demo-a"
OTHER_TRIP = "trip-demo-b"
SCOPE = {"session_id": SESSION_ID, "task_id": TASK_ID}
AT = "2026-11-14T12:00:00+09:00"
SUMMARY = {
    "provider": "demo_booking", "final_action": "book", "item": "offer-demo-1930",
    "venue": "Demo Dining", "party_size": 2,
}


@pytest.fixture
def profile():
    with tempfile.TemporaryDirectory() as temp:
        os.chmod(temp, 0o700)
        ledger = Ledger(Path(temp))
        for trip_id in (TRIP, OTHER_TRIP):
            ledger.put("trip", trip_id, {}, title=trip_id)
        yield Path(temp)


def prepare(profile, governed=False, **data):
    payload = governed_data(action_id="demo-booking") if governed else {"action_id": "demo-booking", "summary": SUMMARY}
    return dispatch(profile, {"operation": "action_prepare", "data": {**payload, **data}},
                    runtime_scope=SCOPE if governed else None)


def listed(profile, trip_id):
    result = dispatch(profile, {"operation": "next_action", "data": {"trip_id": trip_id, "at": AT}})
    return [row["action_id"] for row in result["candidates"]]


@pytest.mark.parametrize("governed", [False, True])
def test_a_prepared_action_lists_under_its_trip(profile, governed):
    saved = prepare(profile, governed, trip_id=TRIP)
    assert saved["trip_id"] == TRIP
    assert saved["status"] == ("approval_required" if governed else "prepared")
    assert listed(profile, TRIP) == ["demo-booking"]
    assert listed(profile, OTHER_TRIP) == []


@pytest.mark.parametrize("governed", [False, True])
def test_preparing_again_without_a_trip_keeps_the_link(profile, governed):
    prepare(profile, governed, trip_id=TRIP)
    again = prepare(profile, governed, **({"action_revision": "r2"} if governed else {}))
    assert again["trip_id"] == TRIP
    assert listed(profile, TRIP) == ["demo-booking"]


def test_an_explicit_trip_moves_the_link(profile):
    prepare(profile, trip_id=TRIP)
    assert prepare(profile, trip_id=OTHER_TRIP)["trip_id"] == OTHER_TRIP
    assert listed(profile, TRIP) == []


@pytest.mark.parametrize("governed", [False, True])
def test_no_trip_stays_unlinked(profile, governed):
    assert prepare(profile, governed)["trip_id"] is None


@pytest.mark.parametrize("governed", [False, True])
@pytest.mark.parametrize("bad", ["", 7, {"trip_id": TRIP}, "trip-ghost", f" {TRIP} "])
def test_a_trip_id_that_names_no_trip_is_refused_before_the_action_is_written(profile, governed, bad):
    with pytest.raises(ValueError, match="trip_id must name an existing trip"):
        prepare(profile, governed, trip_id=bad)
    assert Ledger(profile).get("action", "demo-booking") is None


def test_a_refused_trip_leaves_an_earlier_prepare_and_its_link_unchanged(profile):
    first = prepare(profile, trip_id=TRIP)
    with pytest.raises(ValueError, match="trip_id must name an existing trip"):
        prepare(profile, trip_id="trip-ghost")
    kept = Ledger(profile).get("action", "demo-booking")
    assert kept["trip_id"] == TRIP and kept["updated_at"] == first["updated_at"]


@pytest.mark.parametrize("governed", [False, True])
@pytest.mark.parametrize("writer_type", ["offer", "call", "observe_watch", "trip_watch"])
def test_a_stored_link_that_names_no_trip_is_not_inherited(profile, governed, writer_type):
    # trip_offer, pa_call prepare and trip-watch rows may link a trip that was never imported (#281).
    Ledger(profile).put("action", "demo-booking", {"title": "Earlier row"}, action_type=writer_type, trip_id="trip-ghost")
    row = prepare(profile, governed)
    assert row["trip_id"] is None
    assert Ledger(profile).get("action", "demo-booking")["trip_id"] is None


def test_a_trip_offer_reservation_for_an_unimported_trip_leaves_the_prepare_unlinked(profile):
    identity = "pa:offer:trip-ghost:hotel"
    assert dispatch(profile, {"operation": "trip_offer", "data": {"action": "check", "trip_id": "trip-ghost", "offer_type": "hotel"}})["allowed"]
    assert Ledger(profile).get("action", identity)["trip_id"] == "trip-ghost"
    row = dispatch(profile, {"operation": "action_prepare", "data": {"action_id": identity, "summary": SUMMARY}})
    assert row["trip_id"] is None


def test_a_stored_link_to_an_existing_trip_is_still_inherited(profile):
    Ledger(profile).put("action", "demo-booking", {"title": "Hotel offer"}, action_type="offer", trip_id=TRIP)
    assert prepare(profile)["trip_id"] == TRIP
