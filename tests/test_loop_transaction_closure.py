"""A loop row promoted to a transaction can still record its chase and close, and nothing else (#92)."""
import tempfile

import pytest

from personal_assistant.context import next_actions
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger

AT = "2026-11-20T10:00:00+09:00"
OPENED = "2026-11-10T09:00:00+09:00"
UNKNOWN = {"status": "unknown", "evidence": "fixture adapter unavailable"}


def _promoted(root, status=None):
    ledger = Ledger(root)
    ledger.put("action", "pa:preferences", {"timezone": "Asia/Tokyo"}, action_type="preferences")
    ledger.put("action", "loop-1", {"title": "Book the table", "loop_kind": "our_promise", "counterparty": "Cedar",
                                    "next_actor": "us", "opened_at": OPENED, "next_step": "Book"}, action_type="commitment")
    ledger.prepare("loop-1", {"provider": "restaurant", "final_action": "reserve"})
    if status:
        with ledger.connect() as conn:
            conn.execute("update actions set status=? where action_id='loop-1'", (status,))
    return ledger


def _upsert(root, **data):
    return dispatch(root, {"operation": "action_upsert", "data": {"action_id": "loop-1", **data}})


def _loops(ledger):
    return next_actions(ledger, {"at": AT, "loops_only": True, "limit": 20},
                        kanban_reader=lambda task_id, board: UNKNOWN)["candidates"]


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_confirmation_closes_a_promoted_loop(status):
    with tempfile.TemporaryDirectory() as root:
        ledger = _promoted(root, status)
        before = ledger.get("action", "loop-1")
        assert [c["action_id"] for c in _loops(ledger)] == ["loop-1"]
        log = [{"at": "2026-11-12T09:00:00+09:00", "step": "day2", "how": "reminder"}]
        _upsert(root, fields={"last_chased_at": "2026-11-12T09:00:00+09:00", "chase_log": log})
        row = _upsert(root, fields={"confirmation": {"by": "Cedar", "at": "2026-11-19T12:00:00+09:00",
                                                     "evidence": "reply in chat"}})
        assert row["action_type"] == "transaction" and row["status"] == before["status"]
        assert row["provider"] == before["provider"] and row["trip_id"] == before["trip_id"]
        for key in ("material_summary", "summary_digest", "loop_kind", "opened_at"):
            assert row["fields"][key] == before["fields"][key]
        assert row["fields"]["chase_log"] == log
        assert _loops(ledger) == []


def test_owner_cancellation_closes_a_promoted_loop():
    with tempfile.TemporaryDirectory() as root:
        ledger = _promoted(root, "completed")
        _upsert(root, fields={"loop_cancelled": {"by": "owner", "at": "2026-11-19T12:00:00+09:00"}})
        assert _loops(ledger) == []
        assert ledger.get("action", "loop-1")["status"] == "completed"


def test_snooze_and_next_step_write_and_clear():
    with tempfile.TemporaryDirectory() as root:
        ledger = _promoted(root)
        row = _upsert(root, fields={"snoozed_until": "2026-11-25T09:00:00+09:00", "next_step": "Wait for Cedar"})
        assert row["fields"]["snoozed_until"] == "2026-11-25T09:00:00+09:00"
        assert _upsert(root, fields={"snoozed_until": ""})["fields"]["snoozed_until"] == ""


@pytest.mark.parametrize("data", [
    {"fields": {"material_summary": {"provider": "x", "final_action": "y"}}},
    {"fields": {"summary_digest": "forged"}},
    {"fields": {"confirmed_at": "2026-11-19T12:00:00+09:00"}},
    {"fields": {"title": "renamed"}},
    {"fields": {"loop_kind": "ask_owner"}},
    {"fields": {"confirmation": {"by": "Cedar", "at": "2026-11-19T12:00:00+09:00", "evidence": "x"}, "status_note": "x"}},
    {"fields": {"next_step": "x"}, "status": "completed"},
    {"fields": {"next_step": "x"}, "action_type": "commitment"},
    {"fields": {"next_step": "x"}, "remove": ["material_summary"]},
    {"fields": {"next_step": "x"}, "provider": "other"},
    {"fields": {}},
])
def test_everything_else_on_a_transaction_loop_row_is_refused(data):
    with tempfile.TemporaryDirectory() as root:
        ledger = _promoted(root)
        before = ledger.get("action", "loop-1")
        with pytest.raises(ValueError, match="use transaction operations"):
            _upsert(root, **data)
        assert ledger.get("action", "loop-1") == before


def test_invalid_bookkeeping_values_are_refused():
    with tempfile.TemporaryDirectory() as root:
        ledger = _promoted(root)
        before = ledger.get("action", "loop-1")
        for fields in ({"confirmation": {"by": "Cedar"}}, {"loop_cancelled": {"by": "owner"}},
                       {"last_chased_at": "soon"}, {"chase_log": [{"step": "day3", "at": OPENED}]}):
            with pytest.raises(ValueError):
                _upsert(root, fields=fields)
        assert ledger.get("action", "loop-1") == before


def test_a_transaction_that_is_not_a_loop_accepts_no_upsert():
    with tempfile.TemporaryDirectory() as root:
        ledger = Ledger(root)
        ledger.prepare("tx-1", {"provider": "airline", "final_action": "book"})
        before = ledger.get("action", "tx-1")
        with pytest.raises(ValueError, match="use transaction operations"):
            dispatch(root, {"operation": "action_upsert", "data": {"action_id": "tx-1", "fields": {"next_step": "x"}}})
        with pytest.raises(ValueError, match="use transaction operations"):
            ledger.put_loop_bookkeeping("tx-1", {"next_step": "x"})
        with pytest.raises(ValueError, match="use transaction operations"):
            ledger.put_loop_bookkeeping("missing", {"next_step": "x"})
        assert ledger.get("action", "tx-1") == before


def test_loop_cancelled_closes_an_ordinary_loop_too():
    with tempfile.TemporaryDirectory() as root:
        ledger = Ledger(root)
        ledger.put("action", "loop-2", {"title": "Ask", "loop_kind": "ask_owner", "counterparty": "owner",
                                        "next_actor": "owner", "opened_at": OPENED}, action_type="commitment")
        dispatch(root, {"operation": "action_upsert", "data": {"action_id": "loop-2", "fields": {
            "loop_cancelled": {"by": "owner", "at": "2026-11-19T12:00:00+09:00"}}}})
        assert _loops(ledger) == []


CONFIRM = {"confirmation": {"by": "Cedar", "at": "2026-11-19T12:00:00+09:00", "evidence": "reply"}}
WITHDRAW = {"loop_cancelled": {"by": "owner", "at": "2026-11-19T12:00:00+09:00"}}


def _govern(ledger):
    with ledger.connect() as conn:
        row = conn.execute("select fields_json from actions where action_id='loop-1'").fetchone()
        fields = {**__import__("json").loads(row["fields_json"]), "enforcement_profile": "exact_action"}
        conn.execute("update actions set fields_json=? where action_id='loop-1'", (__import__("json").dumps(fields),))


@pytest.mark.parametrize("status,closure,governed", [
    *[(s, CONFIRM, False) for s in (None, "approval_required", "authorized", "approved_revision", "submitting",
                                    "unknown", "claimed_once", "provider_result", "paused")],
    *[(s, WITHDRAW, False) for s in ("submitting", "unknown", "claimed_once", "provider_result")],
    *[(s, WITHDRAW, True) for s in ("approval_required", "approved_revision", "submitting")],
])
def test_a_pending_or_unresolved_transaction_blocks_closure(status, closure, governed):
    with tempfile.TemporaryDirectory() as root:
        ledger = _promoted(root, status)
        if governed:
            _govern(ledger)
        before = ledger.get("action", "loop-1")
        with pytest.raises(ValueError, match="pending or unresolved"):
            _upsert(root, fields=closure)
        assert ledger.get("action", "loop-1") == before
        assert [c["action_id"] for c in _loops(ledger)] == ["loop-1"]
        _upsert(root, fields={"last_chased_at": "2026-11-12T09:00:00+09:00"})  # Chase bookkeeping still works.


@pytest.mark.parametrize("status", ["prepared", "unknown", "approved_revision"])
def test_a_closed_loop_with_a_live_transaction_stays_listed(status):
    with tempfile.TemporaryDirectory() as root:
        ledger = Ledger(root)
        ledger.put("action", "pa:preferences", {"timezone": "Asia/Tokyo"}, action_type="preferences")
        ledger.put("action", "loop-1", {"title": "Book", "loop_kind": "our_promise", "counterparty": "Cedar",
                                        "next_actor": "us", "opened_at": OPENED,
                                        "confirmation": {"by": "Cedar", "at": "2026-11-15T12:00:00+09:00", "evidence": "reply"}},
                   action_type="commitment")
        assert _loops(ledger) == []
        ledger.prepare("loop-1", {"provider": "restaurant", "final_action": "reserve"})
        with ledger.connect() as conn:
            conn.execute("update actions set status=? where action_id='loop-1'", (status,))
        listed = _loops(ledger)
        assert [c["action_id"] for c in listed] == ["loop-1"]
        assert "Chase" not in listed[0]["next_step"]


@pytest.mark.parametrize("status", [None, "authorized", "paused"])
def test_owner_withdraws_an_ungoverned_loop_before_any_attempt(status):
    with tempfile.TemporaryDirectory() as root:
        ledger = _promoted(root, status)
        before = ledger.get("action", "loop-1")
        row = _upsert(root, fields=WITHDRAW)
        assert row["status"] == before["status"] and row["fields"]["material_summary"] == before["fields"]["material_summary"]
        assert _loops(ledger) == []
