"""Synthetic verified vendor sends and booking readbacks; no external calls."""
import copy
import datetime as dt
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from personal_assistant import state
from personal_assistant.action_gateway import ActionAuthorizationStore, Gateway, GatewayPolicy
from personal_assistant.automation_workflow import preferences
from personal_assistant.entry import SCHEMA, dispatch
from test_booking_follow_through import ACTION, OTHER, READBACK, TRIP, ledger, prepare, record


STAMP = "2026-11-09T15:30:00+00:00"  # November 10 in the owner's timezone.
LOOP_ID = f"{ACTION}:loop"
LOOP = {"counterparty": "Landlord Demo", "next_step": "Book the repair visit"}


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(state, "now", lambda: STAMP)


def prepare_vendor(ledger, action_id=ACTION):
    summary = {"provider": "fixture-provider", "final_action": "send repair request"}
    scope = {"session_id": "fixture-session", "task_id": "fixture-task"}
    args = {"recipient": "landlord@example.invalid", "message": "Please repair the heater"}
    dispatch(ledger.root, {"operation": "action_prepare", "data": {
        "action_id": action_id, "summary": summary, "enforcement_profile": "exact_action",
        "action_revision": "r1", "workflow_id": "vendor-request", "workflow_revision": "v1",
        "tool_name": "fixture_send", "tool_args": args,
        "semantic_target": {"paths": [["recipient"]], "value": [args["recipient"]]},
        "fresh_until": "2030-01-01T00:00:00+00:00", "execution_budget": 1,
        "required_pre_action_projections": ["authority"], "preconditions": {"authority": "confirmed"},
        "expected_readback": "sent/v1",
    }}, runtime_scope=scope)
    dispatch(ledger.root, {"operation": "action_confirm", "data": {
        "action_id": action_id, "summary": summary, "confirmation": "Send this exact repair request",
    }}, runtime_scope=scope)
    policy = GatewayPolicy.from_dict({"protocol": "pa.gateway-policy/v1", "version": "fixture-v1",
                                      "pass_through_tools": [], "denied_tools": []})
    gateway = Gateway(ActionAuthorizationStore(ledger, ledger.root.name), policy, now=lambda: STAMP)
    assert gateway.evaluate({"tool_name": "fixture_send", "tool_input": args, **scope}) is None
    assert ledger.get("action", action_id)["status"] == "claimed_once"


def next_loop(ledger, at):
    preferences(ledger, {"timezone": "Asia/Tokyo"})
    result = dispatch(ledger.root, {"operation": "next_action", "data": {"loops_only": True, "at": at}})
    return next(row for row in result["candidates"] if row["action_id"] == LOOP_ID)


def test_verified_vendor_send_opens_chased_loop_without_booking(ledger):
    prepare_vendor(ledger)
    result = record(ledger, {"loop": LOOP})
    assert result["status"] == "verified"
    assert "booked_item" not in result["fields"] and "booking_trip_id" not in result["fields"]
    row = ledger.get("action", LOOP_ID)
    assert row["action_type"] == "commitment" and row["status"] == "open"
    assert row["fields"] == {**LOOP, "title": "Waiting on Landlord Demo", "loop_kind": "waiting_on_them",
                             "next_actor": "them", "opened_at": result["fields"]["verified_at"],
                             "source_action_id": ACTION, "chase_log": []}
    assert dt.datetime.fromisoformat(row["fields"]["opened_at"]).utcoffset() is not None
    follow = result["follow_through"]
    assert follow["loop_id"] == LOOP_ID and follow["trip_item"] is None
    assert follow["ics_path"] is None and follow["reminders"] == []
    assert follow["calendar_write_allowed"] is False and follow["calendar_ids"] == []
    assert "tracked" in follow["next_step"] and "chased" in follow["next_step"]
    assert "ICS" not in follow["next_step"]
    assert not (ledger.root / "exports").exists()
    assert ledger.get("trip", TRIP)["fields"]["events"] == [OTHER]
    today = next_loop(ledger, "2026-11-10T23:59:00+09:00")
    assert today["next_actor"] == "them" and today["chase"]["step"] == "none"
    day2 = next_loop(ledger, "2026-11-12T00:00:00+09:00")
    assert day2["chase"]["step"] == "day2" and day2["chase"]["age_days"] == 2


def test_appointment_and_quote_loop_land_together(ledger):
    prepare(ledger)
    value = copy.deepcopy(READBACK)
    value["item"].update(kind="appointment", title="Garage visit")
    value["loop"] = {"counterparty": "Garage Demo", "next_step": "Approve the quote", "title": "Garage quote"}
    follow = record(ledger, value)["follow_through"]
    assert follow["loop_id"] == LOOP_ID and follow["trip_item"]
    assert ledger.get("action", LOOP_ID)["fields"]["title"] == "Garage quote"
    assert ledger.get("trip", TRIP)["fields"]["events"][-1]["summary"] == "Garage visit"
    assert ledger.get("action", ACTION)["fields"]["booked_item"] == value["item"]
    assert follow["reminders"] == [f"{ACTION}:reminder:1", f"{ACTION}:reminder:2"]
    for n, reminder in enumerate(value["reminders"], 1):
        assert ledger.get("action", f"{ACTION}:reminder:{n}")["fields"]["due_at"] == reminder["due_at"]
    assert Path(follow["ics_path"]).is_file()


@pytest.mark.parametrize("value,field", [
    ({"loop": LOOP, "reminders": []}, "reminders.*item"),
    ({}, "item or loop"),
    ({"loop": {**LOOP, "counterparty": " "}}, "loop.counterparty"),
    ({"loop": {**LOOP, "snoozed_until": "2026-11-11T12:00:00"}}, "loop.snoozed_until"),
    ({"loop": {**LOOP, "snoozed_until": "2026-11-09T15:29:59+00:00"}}, "loop.snoozed_until"),
    ({"loop": {**LOOP, "snoozed_until": "2026-12-09T15:30:01+00:00"}}, "loop.snoozed_until"),
    ({"loop": {**LOOP, "next_step": ""}}, "loop.next_step"),
    ({"item": READBACK["item"], "loop": {**LOOP, "title": ""}}, "loop.title"),
    ({"loop": {**LOOP, "extra": True}}, "loop.extra"),
])
def test_invalid_follow_through_refuses_entire_readback(ledger, value, field):
    prepare_vendor(ledger)
    before = ledger.path.read_bytes()
    rows = ledger.list("action"), ledger.list("trip")
    with pytest.raises(ValueError, match=field):
        record(ledger, value)
    assert ledger.path.read_bytes() == before
    assert (ledger.list("action"), ledger.list("trip")) == rows
    assert ledger.get("action", ACTION)["status"] == "claimed_once"
    assert ledger.get("action", LOOP_ID) is None
    assert not (ledger.root / "exports").exists()


def test_rerecord_refreshes_details_but_keeps_chase_history(ledger, monkeypatch):
    prepare_vendor(ledger)
    record(ledger, {"loop": {**LOOP, "snoozed_until": "2026-11-14T00:00:00+09:00"}})
    history = [{"at": "2026-11-12T00:00:00+09:00", "step": "day2", "how": "nudge sent"}]
    ledger.put("action", LOOP_ID, {"chase_log": history, "last_chased_at": history[0]["at"]})
    before = ledger.get("action", LOOP_ID)
    monkeypatch.setattr(state, "now", lambda: "2026-11-12T00:01:00+09:00")
    revised = {"counterparty": "Landlord Office Demo", "next_step": "Choose the repair slot", "title": "Repair reply"}
    record(ledger, {"loop": revised})
    after = ledger.get("action", LOOP_ID)
    assert after["status"] == before["status"] == "open"
    for key in ("opened_at", "chase_log", "last_chased_at"):
        assert after["fields"][key] == before["fields"][key]
    assert all(after["fields"][key] == value for key, value in revised.items())
    assert "snoozed_until" not in after["fields"]


@pytest.mark.parametrize("status,closure", [
    ("open", {"confirmation": {"by": "Landlord Demo", "at": STAMP, "evidence": "Synthetic reply"}}),
    ("open", {"loop_cancelled": {"by": "owner", "at": STAMP}}),
    ("cancelled", {}), ("completed", {}), ("dismissed", {}),
])
def test_rerecord_never_changes_closed_loop(ledger, monkeypatch, status, closure):
    prepare_vendor(ledger)
    record(ledger, {"loop": LOOP})
    ledger.put("action", LOOP_ID, closure, status=status)
    before = ledger.get("action", LOOP_ID)
    monkeypatch.setattr(state, "now", lambda: "2026-11-12T00:01:00+09:00")
    follow = record(ledger, {"loop": {**LOOP, "next_step": "A different step"}})["follow_through"]
    assert follow["loop_id"] == LOOP_ID
    assert ledger.get("action", LOOP_ID) == before


@pytest.mark.parametrize("until", ["2026-11-14T00:00:00+09:00", "2026-12-09T15:30:00+00:00"])
def test_snooze_holds_existing_ladder_until_reply_date(ledger, until):
    prepare_vendor(ledger)
    record(ledger, {"loop": {**LOOP, "snoozed_until": until}})
    before = (dt.datetime.fromisoformat(until) - dt.timedelta(seconds=1)).isoformat()
    held = next_loop(ledger, before)
    assert held["chase"]["step"] == "none"
    assert dt.datetime.fromisoformat(held["chase"]["next_chase_at"]) == dt.datetime.fromisoformat(until)
    assert held["next_step"].startswith(f"Wait until {until}")
    resumed = next_loop(ledger, until)
    assert resumed["chase"]["step"] != "none"
    assert not resumed["next_step"].startswith("Wait until")


@pytest.mark.parametrize("kind", ["appointment", "delivery", "errand"])
def test_new_item_kinds_accepted_and_unknown_refused(ledger, kind):
    prepare(ledger)
    value = copy.deepcopy(READBACK)
    value["item"]["kind"] = kind
    assert record(ledger, value)["fields"]["booked_item"]["kind"] == kind
    before = ledger.path.read_bytes()
    value["item"]["kind"] = "unknown-kind"
    with pytest.raises(ValueError, match="item.kind"):
        record(ledger, value)
    assert ledger.path.read_bytes() == before


def test_plain_booking_has_no_loop(ledger):
    prepare(ledger)
    assert record(ledger)["follow_through"]["loop_id"] is None
    assert ledger.get("action", LOOP_ID) is None


def test_tool_schema_accepts_loop_only_and_keeps_loop_closed_to_extra_fields():
    validator = Draft7Validator(SCHEMA["parameters"])
    request = {"operation": "action_result", "data": {
        "action_id": ACTION, "outcome": "confirmed", "follow_through": {"loop": LOOP},
    }}
    assert not list(validator.iter_errors(request))
    request["data"]["follow_through"]["loop"] = {**LOOP, "extra": True}
    assert list(validator.iter_errors(request))



def test_nudge_send_records_a_chase_not_a_second_loop(ledger):
    """A nudge on an existing loop must not open its own ladder for the same counterparty."""
    nudge = f"{LOOP_ID}:nudge:day2"
    prepare_vendor(ledger, nudge)
    before = ledger.get("action", nudge)
    with pytest.raises(ValueError, match="records a chase on that loop"):
        dispatch(ledger.root, {"operation": "action_result", "data": {
            "action_id": nudge, "outcome": "confirmed", "proof": "Synthetic provider readback",
            "follow_through": {"loop": dict(LOOP)}}})
    assert ledger.get("action", nudge) == before
    assert ledger.get("action", f"{nudge}:loop") is None


def test_rerecord_refreshes_only_bookkeeping_on_a_transaction_owned_loop(ledger):
    """A step prepared on the generated loop's own row makes it a transaction; a re-record must not fail half-way."""
    prepare_vendor(ledger)
    record(ledger, {"loop": LOOP})
    ledger.prepare(LOOP_ID, {"provider": "fixture-provider", "final_action": "book the repair visit"})
    before = ledger.get("action", LOOP_ID)
    assert before["action_type"] == "transaction"
    result = record(ledger, {"loop": {**LOOP, "next_step": "Confirm the repair slot"}})
    assert result["status"] == "verified" and result["follow_through"]["loop_id"] == LOOP_ID
    after = ledger.get("action", LOOP_ID)
    assert (after["action_type"], after["status"], after["trip_id"]) == (
        before["action_type"], before["status"], before["trip_id"])
    assert after["fields"]["next_step"] == "Confirm the repair slot"
    assert {k: v for k, v in after["fields"].items() if k != "next_step"} == {
        k: v for k, v in before["fields"].items() if k != "next_step"}


def test_loop_keeps_the_trip_of_its_request(ledger):
    """A vendor request on a trip opens a loop that trip-scoped next_action still lists."""
    prepare_vendor(ledger)
    record(ledger, {"trip_id": TRIP, "loop": LOOP})
    assert ledger.get("action", LOOP_ID)["trip_id"] == TRIP
    preferences(ledger, {"timezone": "Asia/Tokyo"})
    scoped = dispatch(ledger.root, {"operation": "next_action", "data": {
        "loops_only": True, "trip_id": TRIP, "at": STAMP}})
    assert LOOP_ID in [row["action_id"] for row in scoped["candidates"]]
