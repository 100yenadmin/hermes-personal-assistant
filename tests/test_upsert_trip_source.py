"""Trip-source linking through real PA dispatch with synthetic profile data."""
from pathlib import Path

import pytest

from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.state import Ledger


TRIP = "trip-demo-a"
OTHER_TRIP = "trip-demo-b"
LOOP = {
    "loop_kind": "waiting_on_them", "counterparty": "Demo hotel",
    "next_actor": "them", "opened_at": "2026-11-01T09:00:00+09:00",
    "next_step": "Confirm the arrival time",
}


@pytest.fixture
def ledger(tmp_path):
    ledger = Ledger(tmp_path)
    for trip_id in (TRIP, OTHER_TRIP):
        ledger.put("trip", trip_id, {}, title=trip_id)
    return ledger


def upsert(ledger, source_id=TRIP, **data):
    return dispatch(ledger.root, {"operation": "action_upsert", "data": {
        "source_id": source_id, "action_kind": "call", "occurrence": "arrival",
        "action_type": "commitment", "fields": LOOP, **data,
    }})


@pytest.mark.parametrize("loops_only", [False, True])
def test_trip_source_links_open_loop_and_repeated_upsert(ledger, loops_only):
    saved = upsert(ledger)
    assert saved["trip_id"] == TRIP
    result = dispatch(ledger.root, {"operation": "next_action", "data": {
        "trip_id": TRIP, "loops_only": loops_only, "at": "2026-11-14T12:00:00+09:00",
    }})
    assert [row["action_id"] for row in result["candidates"]] == [saved["action_id"]]
    assert result["candidates"][0]["loop_state"] == "open"

    updated = upsert(ledger, fields={"next_step": "Confirm the revised arrival time"})
    assert updated["action_id"] == saved["action_id"]
    assert updated["trip_id"] == TRIP
    assert updated["fields"]["next_step"] == "Confirm the revised arrival time"
    assert len(ledger.list("action")) == 1


@pytest.mark.parametrize("source_id", ["errand-dentist", TRIP + "-errand"])
def test_non_trip_source_never_infers_a_link(ledger, source_id):
    saved = upsert(ledger, source_id=source_id, fields={**LOOP, "source_id": TRIP})
    assert saved["trip_id"] is None


def test_explicit_trip_link_wins_over_source(ledger):
    assert upsert(ledger, trip_id=OTHER_TRIP)["trip_id"] == OTHER_TRIP
    assert upsert(ledger, source_id="errand-dentist", trip_id=OTHER_TRIP)["trip_id"] == OTHER_TRIP


def test_explicit_null_prevents_inference(ledger):
    assert upsert(ledger, trip_id=None)["trip_id"] is None


def test_explicit_null_keeps_an_existing_link(ledger):
    # put treats None as "keep the stored value", so a linked row stays linked.
    assert upsert(ledger)["trip_id"] == TRIP
    assert upsert(ledger, trip_id=None)["trip_id"] == TRIP


def test_existing_different_trip_link_is_preserved(ledger):
    saved = upsert(ledger, trip_id=OTHER_TRIP)
    updated = upsert(ledger, fields={"next_step": "Read back the arrival time"})
    assert updated["action_id"] == saved["action_id"]
    assert updated["trip_id"] == OTHER_TRIP
    assert updated["fields"]["next_step"] == "Read back the arrival time"


def test_existing_unlinked_action_gains_trip_link(ledger):
    saved = upsert(ledger, trip_id=None)
    updated = upsert(ledger)
    assert updated["action_id"] == saved["action_id"]
    assert updated["trip_id"] == TRIP


@pytest.mark.parametrize("source_id", [None, "", 123])
def test_only_nonempty_string_source_can_infer(ledger, source_id):
    # Even a matching stored ID must not turn a numeric source into a trip link.
    ledger.put("trip", "123", {})
    assert upsert(ledger, source_id=source_id, action_id="synthetic-loop")["trip_id"] is None


def test_transaction_bookkeeping_does_not_infer_or_accept_trip_column(ledger):
    saved = upsert(ledger, trip_id=None)
    dispatch(ledger.root, {"operation": "action_prepare", "data": {
        "action_id": saved["action_id"],
        "summary": {"provider": "fixture-provider", "final_action": "Ask about arrival"},
    }})
    bookkeeping = {"source_id": TRIP, "action_kind": "call", "occurrence": "arrival",
                   "fields": {"next_step": "Read back the reply"}}
    updated = dispatch(ledger.root, {"operation": "action_upsert", "data": bookkeeping})
    assert updated["action_type"] == "transaction"
    assert updated["trip_id"] is None
    assert updated["fields"]["next_step"] == "Read back the reply"
    with pytest.raises(ValueError, match="use transaction operations"):
        dispatch(ledger.root, {"operation": "action_upsert", "data": {**bookkeeping, "trip_id": TRIP}})
    assert ledger.get("action", saved["action_id"]) == updated


def test_tool_and_skill_explain_exact_trip_source_linking():
    description = SCHEMA["parameters"]["properties"]["data"]["description"]
    assert (
        "action_upsert: optional action_id/source_id/action_kind/occurrence, trip_id, fields; "
        "a source_id that is an existing trip ID also links the record to that trip "
        "(other source IDs never do: pass trip_id to link an errand to a trip)."
    ) in description
    text = (Path(__file__).resolve().parents[1] / "skills/travel-ledger/SKILL.md").read_text()
    assert (
        "The same `source_id`, `action_kind` and `occurrence` update one record. "
        "A `source_id` that is a trip ID from `trip_import` also links the record to that trip, "
        "so `next_action` with `trip_id` lists it when it is a commitment, refund or return; "
        "for an errand that belongs to a trip, "
        'pass `"trip_id": "<trip id>"` as well.'
    ) in " ".join(text.split())
