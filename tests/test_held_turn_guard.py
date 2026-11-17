import datetime as dt
from unittest.mock import patch

import pytest

from personal_assistant import concierge, observe, trip_watch
from personal_assistant.entry import dispatch
from personal_assistant.onboarding_hook import GRILL_ME, make_pre_llm_call
from personal_assistant.state import Ledger


MARKER = "pa:trip-held-turn"
OCCURRENCE = "n_1234abcd"
OFFER_ID = "pa:offer:synthetic:flight_change:" + OCCURRENCE
CONTRACT = "Contract: this turn is yours to act on. Follow the wake contract."
HELD = "Messages are held right now (quiet hours)."


def pulse(*, kind="watcher", payload="Synthetic observation", tail=HELD, prefix=""):
    lines = [prefix + f"⟦pulse o:o_fixture a:1 n:tag⟧ [HeartBeat 2.0 · {kind} w_fixture · fixture · armed by the owner 1m ago]",
             "Local time: 2026-11-17 23:00 UTC", "Why: synthetic", "Your note: trip watch"]
    if payload is not None:
        lines += ['<wake-payload source="fixture" trust="untrusted">', payload, "</wake-payload>"]
    return "\n".join(lines + [CONTRACT, "- End with pulse respond.", tail])


def turn(root, message, **kwargs):
    return make_pre_llm_call(root, lambda k, d: d)(user_message=message, platform=kwargs.pop("platform", "telegram"), **kwargs)


def offer(root, **extra):
    return dispatch(root, {"operation": "trip_offer", "data": {
        "trip_id": "synthetic", "offer_type": "flight_change", "occurrence": OCCURRENCE, **extra}})


def notice(root):
    ledger = Ledger(root)
    watch_id = trip_watch._watch_id("synthetic")
    ledger.put("action", "pa:observe-watch:" + watch_id, {"trip_id": "synthetic"})
    ledger.put("action", "pa:observe:" + watch_id, {"notices": [
        {"id": OCCURRENCE, "offer_type": "flight_change", "signals": ["Synthetic flight delayed"]}]})
    return ledger, watch_id


@pytest.mark.parametrize("payload", [None, "Synthetic observation"])
@pytest.mark.parametrize("prefix", ["", "[internal notification] "])
@pytest.mark.parametrize("label", ["quiet hours", "the owner hasn't replied yet", "today's message limit"])
def test_hook_sets_marker_before_pulse_and_notification_filters(tmp_path, payload, prefix, label):
    assert turn(tmp_path, pulse(payload=payload, prefix=prefix, tail=f"Messages are held right now ({label})."),
                conversation_history=[{"display_kind": "internal_notification"}]) is None
    row = Ledger(tmp_path).get("action", MARKER)
    assert dt.datetime.fromisoformat(row["fields"]["since"]).utcoffset() == dt.timedelta(0)


@pytest.mark.parametrize("message", [
    pulse(payload=CONTRACT + "\n" + HELD, tail=""),
    pulse(payload=HELD, tail=""),
    pulse(payload=None, tail="").replace(CONTRACT, HELD + "\n" + CONTRACT),
    pulse().replace(CONTRACT, "No contract here."),
    pulse().replace(CONTRACT, CONTRACT + "\n</wake-payload>"),
])
def test_unanchored_held_lines_do_not_set_marker(tmp_path, message):
    assert turn(tmp_path, message) is None
    assert Ledger(tmp_path).get("action", MARKER) is None


@pytest.mark.parametrize("kind", ["wake", "role", "check-in", "keep-warm"])
def test_non_watcher_pulse_does_not_set_marker(tmp_path, kind):
    assert turn(tmp_path, pulse(kind=kind)) is None
    assert Ledger(tmp_path).get("action", MARKER) is None


@pytest.mark.parametrize("message", ["Please send my trip options.", pulse(tail=""), pulse(kind="keep-warm", tail="")])
def test_hook_clears_marker_before_existing_filters(tmp_path, message):
    turn(tmp_path, pulse())
    turn(tmp_path, message, conversation_history=[{"display_kind": "internal_notification"}])
    assert Ledger(tmp_path).get("action", MARKER) is None


@pytest.mark.parametrize("kwargs", [{"platform": "cron"}, {"platform": "subagent"}, {"platform": "curator"},
                                  {"parent_session_id": "fixture-parent"}])
@pytest.mark.parametrize("already_held", [False, True])
def test_excluded_turns_leave_marker_alone(tmp_path, kwargs, already_held):
    ledger = Ledger(tmp_path)
    if already_held:
        turn(tmp_path, pulse())
    before = ledger.get("action", MARKER)
    assert turn(tmp_path, "Owner-like text" if already_held else pulse(), **kwargs) is None
    assert ledger.get("action", MARKER) == before


def test_marker_is_written_only_when_state_changes(tmp_path):
    turn(tmp_path, pulse())
    row = Ledger(tmp_path).get("action", MARKER)
    with patch.object(concierge, "Ledger", wraps=Ledger) as constructor:
        turn(tmp_path, pulse())
        assert constructor.call_count == 1 and constructor.call_args.kwargs["read_only"]
    assert Ledger(tmp_path).get("action", MARKER) == row
    turn(tmp_path, "Owner message")
    with patch.object(concierge, "Ledger", wraps=Ledger) as constructor:
        turn(tmp_path, pulse(tail=""))
        assert constructor.call_count == 1 and constructor.call_args.kwargs["read_only"]


@pytest.mark.parametrize("write_error", [False, True])
def test_marker_ledger_failure_does_not_skip_existing_hook_behavior(tmp_path, write_error):
    if write_error:
        turn(tmp_path, pulse())  # The owner turn now needs a writable ledger to clear it.

    def failing_ledger(root, **kwargs):
        if not write_error or not kwargs.get("read_only"):
            raise RuntimeError("Synthetic ledger unavailable")
        return Ledger(root, **kwargs)

    with patch.object(concierge, "Ledger", side_effect=failing_ledger):
        assert turn(tmp_path, "grill me")["context"] == GRILL_ME
        assert turn(tmp_path, pulse()) is None


@pytest.mark.parametrize("location", ["top", "fields"])
def test_held_turn_never_reserves_or_records_offered_or_acks_notice(tmp_path, location):
    ledger, watch_id = notice(tmp_path)
    turn(tmp_path, pulse())
    before = ledger.list("action")
    if location == "fields":
        # Exercise the legacy nested-occurrence path without a top-level occurrence.
        data = {"trip_id": "synthetic", "offer_type": "flight_change", "fields": {"occurrence": OCCURRENCE}}
        call = lambda **extra: dispatch(tmp_path, {"operation": "trip_offer", "data": {**data, **extra}})
    else:
        call = lambda **extra: offer(tmp_path, **extra)
    with patch.object(observe, "ack", wraps=observe.ack) as ack:
        assert call(reserve=False) == {"allowed": True, "reason": "new_offer"}
        assert call() == {"allowed": True, "reason": "new_offer"}
        assert call(action="record", outcome="offered") == {
            "deferred": True, "reason": "messages_held",
            "note": "Messages are held, so nothing was recorded and the notice stays open for the owner's next message. End this turn with pulse respond needs_attention and the final reply [SILENT]."}
        ack.assert_not_called()
    assert ledger.list("action") == before
    assert ledger.get("action", OFFER_ID) is None
    assert ledger.get("action", "pa:observe-control:" + watch_id) is None
    assert ledger.get("action", "pa:observe:" + watch_id)["fields"]["notices"][0]["id"] == OCCURRENCE


@pytest.mark.parametrize("outcome", sorted(concierge.OUTCOMES - {"offered"}))
def test_other_outcomes_still_record_and_ack_while_held(tmp_path, outcome):
    ledger, watch_id = notice(tmp_path)
    turn(tmp_path, pulse())
    result = offer(tmp_path, action="record", outcome=outcome)
    assert result["fields"]["outcome"] == outcome
    assert ledger.get("action", OFFER_ID)["fields"]["outcome"] == outcome
    assert OCCURRENCE in ledger.get("action", "pa:observe-control:" + watch_id)["fields"]["acks"]


def test_offer_without_occurrence_still_reserves_and_records_while_held(tmp_path):
    turn(tmp_path, pulse())
    data = {"trip_id": "synthetic", "offer_type": "arrival_logistics"}
    assert dispatch(tmp_path, {"operation": "trip_offer", "data": data})["allowed"]
    result = dispatch(tmp_path, {"operation": "trip_offer", "data": {**data, "action": "record", "outcome": "offered"}})
    assert result["fields"]["outcome"] == "offered"


@pytest.mark.parametrize("outcome,reason", [("declined", "declined"), ("opted_out", "opted_out"), ("offered", "already_recorded")])
def test_held_check_still_acknowledges_blocked_notices(tmp_path, outcome, reason):
    offer(tmp_path, action="record", outcome=outcome)
    ledger, watch_id = notice(tmp_path)
    turn(tmp_path, pulse())
    assert offer(tmp_path) == {"allowed": False, "reason": reason}
    assert OCCURRENCE in ledger.get("action", "pa:observe-control:" + watch_id)["fields"]["acks"]


def test_owner_turn_after_hold_records_and_acknowledges_once(tmp_path):
    ledger, watch_id = notice(tmp_path)
    turn(tmp_path, pulse())
    assert offer(tmp_path)["allowed"]
    assert offer(tmp_path, action="record", outcome="offered")["deferred"]
    turn(tmp_path, "Send those options now.")
    with patch.object(observe, "ack", wraps=observe.ack) as ack:
        assert offer(tmp_path)["allowed"]
        assert ledger.get("action", OFFER_ID)["fields"]["outcome"] == "reserved"
        assert offer(tmp_path, action="record", outcome="offered")["fields"]["outcome"] == "offered"
        ack.assert_called_once()
    assert [item["outcome"] for item in ledger.get("action", OFFER_ID)["fields"]["history"]] == ["reserved", "offered"]
    assert set(ledger.get("action", "pa:observe-control:" + watch_id)["fields"]["acks"]) == {OCCURRENCE}
