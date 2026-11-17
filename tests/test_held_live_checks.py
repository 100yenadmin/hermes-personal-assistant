"""P6's oracle uses synthetic snapshots, never a live backend."""
import copy
import json

import pytest

from evals.concierge_e2e.test_held_live import score_held


def passing_snapshot():
    offer = dict(outcome="offered")
    record = dict(role="assistant", content="", tool_calls=json.dumps([{"function": {
        "name": "tool_call", "arguments": json.dumps(dict(calls=[dict(name="pa", arguments=dict(operation="trip_offer", data=dict(
            action="record", occurrence="n_third", outcome="offered")))]))}}]))
    text = "Flight PA301 now departs 18:30; here are your options."
    owner = [dict(role="user", content="Any update on my trip?"), record, dict(role="assistant", content=text)]
    return dict(notice="n_third", wake_id="w1", changed_time="18:30", visible=["first", "second", text],
        sendable=[dict(offer=offer, acked=True, texts=["offer"]) for _ in range(2)],
        held=dict(texts=[], offer={}, acked=False, hb2=dict(sessions=[dict(unanswered_count=2)], occurrences=[dict(
            wake_id="w1", held_reason="message_held:unanswered", state="done", force_silent=1, delivered=0,
            outcome="needs_attention", notify=1, summary="PA301 now departs 18:30. Reply for options.")])),
        after=dict(offer=offer, acked=True, texts=[text], watcher=dict(status="active", error_streak=0)),
        owner_turn=owner, transcript=owner)


def test_p6_snapshot_passes():
    assert all(score_held(passing_snapshot()).values())
    assert not any(score_held({}).values())


@pytest.mark.parametrize("field,value", [("outcome", "done"), ("notify", 0), ("summary", ""), ("summary", "x" * 159 + " ")])
def test_p6_rejects_bad_held_respond(field, value):
    snapshot = passing_snapshot()
    snapshot["held"]["hb2"]["occurrences"][0][field] = value
    assert not score_held(snapshot)["held_respond"]


@pytest.mark.parametrize("stage,key,value,check", [
    ("held", "offer", {"outcome": "offered"}, "held_unrecorded"), ("held", "acked", True, "held_unrecorded"),
    ("held", "texts", ["leaked offer"], "held_silent"), ("after", "acked", False, "owner_recorded"),
    ("after", "texts", ["Flight 18:30", "Flight 18:30"], "owner_offer_once")])
def test_p6_rejects_delivery_errors(stage, key, value, check):
    snapshot = copy.deepcopy(passing_snapshot())
    snapshot[stage][key] = value
    assert not score_held(snapshot)[check]


def test_p6_rejects_record_only_in_a_later_wake():
    snapshot = passing_snapshot()
    snapshot["owner_turn"] = []
    assert not score_held(snapshot)["owner_turn"]


def test_p6_rejects_provider_tool_and_duplicate_record():
    snapshot = passing_snapshot()
    snapshot["transcript"] = snapshot["transcript"] + [snapshot["transcript"][1], dict(tool_calls=[
        {"function": {"name": "browser_navigate", "arguments": "{}"}}])]
    checks = score_held(snapshot)
    assert not checks["no_provider_actions"] and not checks["one_record"]
