"""Synthetic cross-session approval flows; no provider or model calls."""
import copy
import json

import pytest

from personal_assistant.action_gateway import ActionAuthorizationStore, Gateway
from personal_assistant.entry import dispatch
from personal_assistant.native_gateway_runtime import NativeActionAuthorizationStore, NativeGateway
from personal_assistant.state import Ledger, stable_id
from test_auto_exact_action import ARGS, TOOL, governed_data, policy
from test_booking_follow_through import ACTION, ledger  # noqa: F401 (shared fixture)


A = {"session_id": "fixture-session-a", "task_id": "fixture-task-a"}
B = {"session_id": "fixture-session-b", "task_id": "fixture-task-b"}
PREPARED_AT = "2026-11-09T00:00:00+00:00"
CONFIRMED_AT = "2026-11-10T00:00:00+00:00"


def prepare(ledger, store, **changes):
    data = governed_data(action_id=ACTION)
    data.update({"at": PREPARED_AT, **changes})
    dispatch(ledger.root, {"operation": "action_prepare", "data": copy.deepcopy(data)},
             runtime_scope={**A, "authorization_store": store})
    return data


def confirm(ledger, data, scope):
    return dispatch(ledger.root, {"operation": "action_confirm", "data": {
        "action_id": ACTION, "summary": data["summary"],
        "confirmation": "Approve these exact details", "at": CONFIRMED_AT,
    }}, runtime_scope=scope)


def snapshot(ledger):
    with ledger.connect() as conn:
        return {
            table: [dict(row) for row in conn.execute(f"select * from {table} order by action_id")]
            for table in ("pa_action_authorizations", "actions")
        }


@pytest.mark.parametrize("native", [False, True], ids=["base", "native"])
@pytest.mark.parametrize("scope", [B, {**A, "task_id": B["task_id"]},
                                   {**A, "session_id": B["session_id"]}],
                         ids=["session-and-task", "task-only", "session-only"])
def test_confirming_scope_claims_once_and_records_readback(ledger, native, scope):
    store_type, gateway_type = ((NativeActionAuthorizationStore, NativeGateway) if native
                               else (ActionAuthorizationStore, Gateway))
    store = store_type(ledger, ledger.root.name)
    gateway = gateway_type(store, policy())
    gateway.now = lambda: CONFIRMED_AT
    # A second native store represents an already-created hook in the same process.
    observer = store_type(ledger, ledger.root.name)
    data = prepare(ledger, store)
    before = snapshot(ledger)["pa_action_authorizations"][0]
    if native:
        assert observer.has_indexed_scope(TOOL, **A)
        assert not observer.has_indexed_scope(TOOL, **scope)
    approved = confirm(ledger, data, {**scope, "authorization_store": store})
    assert approved["status"] == "approved_revision"
    if native:
        assert observer.has_indexed_scope(TOOL, **scope)
        assert observer.has_indexed_scope(TOOL, **A)  # stale hint is harmless
    rebound = snapshot(ledger)["pa_action_authorizations"][0]
    assert gateway.evaluate({"tool_name": TOOL, "tool_input": ARGS, **scope}) is None
    claimed_status = ledger.get("action", ACTION)["status"]
    result_data = {"action_id": ACTION, "outcome": "confirmed",
                   "proof": {"provider_object_id": "fixture-readback", "readback": "matched"}}
    if claimed_status != "claimed_once":
        # Capture the original bug: the hook passes through and result refuses.
        with pytest.raises(ValueError, match="state"):
            dispatch(ledger.root, {"operation": "action_result", "data": result_data})
    assert claimed_status == "claimed_once"
    assert (rebound["session_id"], rebound["task_id"]) == (scope["session_id"], scope["task_id"])
    envelope = json.loads(rebound["envelope_json"])
    assert envelope["scope"] == json.loads(before["envelope_json"])["scope"]
    assert envelope["authority"]["rebound_from"] == {**A, "at": CONFIRMED_AT}
    for key in ("args_digest", "target_digest", "target_path_json", "execution_budget"):
        assert rebound[key] == before[key]

    assert store.get(rebound["action_id"])["execution_budget"] == 0
    assert gateway.evaluate({"tool_name": TOOL, "tool_input": ARGS, **scope})["reason_code"] == "DENY_ALREADY_CLAIMED"
    result = dispatch(ledger.root, {"operation": "action_result", "data": result_data}, runtime_scope=scope)
    assert result["status"] == "verified"
    assert result["fields"]["provider_proof"]["readback"] == "matched"


@pytest.mark.parametrize("native", [False, True], ids=["base", "native"])
def test_old_scope_does_not_claim_after_rebind(ledger, native):
    store_type, gateway_type = ((NativeActionAuthorizationStore, NativeGateway) if native
                               else (ActionAuthorizationStore, Gateway))
    store = store_type(ledger, ledger.root.name)
    data = prepare(ledger, store)
    confirm(ledger, data, {**B, "authorization_store": store})
    before = snapshot(ledger)
    gateway = gateway_type(store, policy())
    gateway.now = lambda: CONFIRMED_AT
    # The stale index hint must defer to the database lookup.
    assert gateway.evaluate({"tool_name": TOOL, "tool_input": ARGS, **A}) is None
    assert snapshot(ledger) == before
    assert ledger.get("action", ACTION)["status"] == "approved_revision"
    assert gateway.evaluate({"tool_name": TOOL, "tool_input": ARGS, **B}) is None
    assert ledger.get("action", ACTION)["status"] == "claimed_once"
    assert gateway.evaluate({"tool_name": TOOL, "tool_input": ARGS, **B})["reason_code"] == "DENY_ALREADY_CLAIMED"


@pytest.mark.parametrize("scope", [A, None], ids=["same-scope", "no-runtime-scope"])
def test_unchanged_confirm_matches_legacy_rows(ledger, tmp_path, scope):
    store = ActionAuthorizationStore(ledger, ledger.root.name)
    data = prepare(ledger, store)
    before = snapshot(ledger)
    baseline_root = tmp_path / "baseline"
    baseline_root.mkdir(mode=0o700)
    baseline_ledger = Ledger(baseline_root)
    with ledger.connect() as source, baseline_ledger.connect() as destination:
        source.backup(destination)
    baseline = ActionAuthorizationStore(baseline_ledger, ledger.root.name)
    assert snapshot(baseline_ledger) == before
    baseline.confirm_governed(ACTION, stable_id(data["summary"]), "Approve these exact details",
                             at=CONFIRMED_AT)
    assert confirm(ledger, data, scope)["status"] == "approved_revision"
    assert snapshot(ledger) == snapshot(baseline_ledger)  # includes raw envelope/digest columns
    row = snapshot(ledger)["pa_action_authorizations"][0]
    assert (row["session_id"], row["task_id"]) == (A["session_id"], A["task_id"])
    assert "rebound_from" not in json.loads(row["envelope_json"])["authority"]
    gateway = Gateway(store, policy(), now=lambda: CONFIRMED_AT)
    assert gateway.evaluate({"tool_name": TOOL, "tool_input": ARGS, **A}) is None
    assert ledger.get("action", ACTION)["status"] == "claimed_once"


@pytest.mark.parametrize("scope", [
    {"session_id": B["session_id"]}, {"task_id": B["task_id"]},
    {"session_id": "", "task_id": B["task_id"]},
    {"session_id": B["session_id"], "task_id": 7},
])
def test_incomplete_or_non_string_scope_does_not_rebind(ledger, scope):
    store = NativeActionAuthorizationStore(ledger, ledger.root.name)
    data = prepare(ledger, store)
    confirmed = store.confirm_governed(ACTION, stable_id(data["summary"]), "yes",
                                      at=CONFIRMED_AT, **scope)
    assert (confirmed["session_id"], confirmed["task_id"]) == (A["session_id"], A["task_id"])
    assert "rebound_from" not in confirmed["envelope"]["authority"]
    assert not store.has_indexed_scope(TOOL, **B)


@pytest.mark.parametrize("reason", [
    "material-summary", "material-revision", "material-ref", "not-prepared",
    "freshness-zero", "freshness-negative", "precondition", "action-state", "confirmation",
])
def test_refused_confirmation_preserves_all_state_and_index(ledger, reason):
    store = NativeActionAuthorizationStore(ledger, ledger.root.name)
    changes = {}
    if reason.startswith("freshness-"):
        changes["fresh_until"] = PREPARED_AT if reason == "freshness-zero" else "2026-11-08T00:00:00+00:00"
    if reason == "precondition":
        changes["preconditions"] = {"authority": "pending"}
    data = prepare(ledger, store, **changes)
    expected_error = "material details changed"
    if reason == "material-summary":
        data["summary"]["title"] = "Changed details"
    elif reason in {"material-revision", "material-ref"}:
        fields = ledger.get("action", ACTION)["fields"]
        fields["action_revision" if reason == "material-revision" else "gateway_scope_ref"] = "different"
        with ledger.connect() as conn:
            conn.execute("update actions set fields_json=? where action_id=?", (json.dumps(fields), ACTION))
    elif reason == "not-prepared":
        store.cancel_governed(ACTION, at=CONFIRMED_AT)
        expected_error = "not prepared"
    elif reason.startswith("freshness-"):
        expected_error = "freshness window must be positive"
    elif reason == "precondition":
        expected_error = "precondition"
    elif reason == "action-state":
        with ledger.connect() as conn:
            conn.execute("update actions set status='paused' where action_id=?", (ACTION,))
        expected_error = "not awaiting approval"
    elif reason == "confirmation":
        expected_error = "explicit confirmation"
    before = snapshot(ledger)
    with pytest.raises(ValueError, match=expected_error):
        store.confirm_governed(ACTION, stable_id(data["summary"]),
                              "" if reason == "confirmation" else "yes",
                              at=CONFIRMED_AT, **B)
    assert snapshot(ledger) == before
    assert store.has_indexed_scope(TOOL, **A)
    # The confirming scope is published before the commit, so a refused confirm can
    # leave it as a hint; the hint defers to the database and changes nothing.
    gateway = NativeGateway(store, policy())
    gateway.now = lambda: CONFIRMED_AT
    assert gateway.evaluate({"tool_name": TOOL, "tool_input": ARGS, **B}) is None
    assert snapshot(ledger) == before


def test_provider_call_racing_the_confirm_commit_is_claimed(ledger, monkeypatch):
    """B's hook runs after the confirm commits but before confirm_governed returns."""
    store = NativeActionAuthorizationStore(ledger, ledger.root.name)
    gateway = NativeGateway(store, policy())
    gateway.now = lambda: CONFIRMED_AT
    data = prepare(ledger, store)
    seen = []
    readback = store.get

    def hook_then_readback(action_id):
        if not seen:
            seen.append(gateway.evaluate({"tool_name": TOOL, "tool_input": ARGS, **B}))
            seen.append(ledger.get("action", ACTION)["status"])
        return readback(action_id)

    monkeypatch.setattr(store, "get", hook_then_readback)
    store.confirm_governed(ACTION, stable_id(data["summary"]), "yes", at=CONFIRMED_AT, **B)
    assert seen == [None, "claimed_once"]
    assert gateway.evaluate({"tool_name": TOOL, "tool_input": ARGS, **B})["reason_code"] == "DENY_ALREADY_CLAIMED"
