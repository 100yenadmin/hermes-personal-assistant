"""Synthetic receipt and verified-booking expense paths; no provider calls."""
import copy
import csv
import datetime as dt
import stat
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from personal_assistant import state
from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.state import stable_id
from test_booking_follow_through import ACTION, OTHER, READBACK, TRIP, ledger, prepare, record


EXPENSE = {"amount": "00125.500", "currency": "USD", "category": "lodging"}
RECEIPT = {**EXPENSE, "date": "2026-11-10", "evidence_ref": "synthetic-receipt.pdf"}


def expense(ledger, action, **data):
    return dispatch(ledger.root, {"operation": "expense", "data": {"action": action, **data}})


def test_booking_defaults_and_null_without_expense(ledger):
    prepare(ledger)
    value = copy.deepcopy(READBACK)
    # The timestamp is November 11 UTC, but November 12 in the item's zone.
    value["item"]["start"] = "2026-11-11T23:00:00+00:00"
    value["reminders"] = []
    value["expense"] = EXPENSE
    result = record(ledger, value)
    identity = ACTION + ":expense"
    assert result["follow_through"]["expense_id"] == identity
    row = ledger.get("action", identity)
    assert row["action_type"] == "expense" and row["status"] == "recorded"
    assert row["fields"] == {**EXPENSE, "amount": "125.5", "kind": "charge", "date": "2026-11-12",
                             "evidence_ref": ACTION, "source": "provider_readback",
                             "source_action_id": ACTION, "trip_ref": TRIP}
    assert record(ledger)["follow_through"]["expense_id"] is None


@pytest.mark.parametrize("governed", [True, False])
def test_expense_only_uses_result_utc_date_and_resolved_trip(ledger, monkeypatch, governed):
    monkeypatch.setattr(state, "now", lambda: "2026-11-10T00:30:00+09:00")
    prepare(ledger, governed=governed, trip_id=None)
    result = record(ledger, {"expense": EXPENSE, "trip_id": TRIP})
    row = ledger.get("action", result["follow_through"]["expense_id"])
    stamp = dt.datetime.fromisoformat(result["fields"]["verified_at"])
    assert row["fields"]["date"] == stamp.astimezone(dt.timezone.utc).date().isoformat() == "2026-11-09"
    assert row["fields"]["trip_ref"] == TRIP
    assert result["follow_through"]["ics_path"] is None
    assert result["follow_through"]["next_step"] == ""
    assert not (ledger.root / "exports").exists()


@pytest.mark.parametrize("change", [
    {"amount": "1e309"}, {"amount": 1e309}, {"amount": "-1"}, {"amount": "0"},
    {"amount": "1.0001"}, {"amount": "NaN"}, {"amount": "Infinity"}, {"amount": 1.5},
    {"currency": "usd"}, {"currency": "USDD"}, {"extra": "unknown"},
    {"description": "4111 1111 1111 1111"}, {"merchant": "account number: demo123"},
    {"evidence_ref": "token=synthetic123456"}, {"category": "invented"}, {"kind": "payment"},
    {"date": "2026-02-30"}, {"merchant": "x" * 121}, {"description": "x" * 201},
    {"evidence_ref": ""},
])
def test_invalid_expense_refuses_whole_readback(ledger, change):
    prepare(ledger)
    value = {**copy.deepcopy(READBACK), "expense": {**EXPENSE, **change}}
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="expense"):
        record(ledger, value)
    assert ledger.path.read_bytes() == before
    assert ledger.get("action", ACTION)["status"] == "claimed_once"
    assert ledger.get("action", ACTION + ":expense") is None
    assert not (ledger.root / "exports").exists()


def test_private_scan_covers_only_the_supplied_expense(ledger):
    prepare(ledger)
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="expense"):
        record(ledger, {"expense": {**EXPENSE, "description": "card number: 4111111111111111"}})
    assert ledger.path.read_bytes() == before
    # A masked card line in the provider proof is not expense text; it never blocks the readback.
    result = dispatch(ledger.root, {"operation": "action_result", "data": {
        "action_id": ACTION, "outcome": "confirmed", "proof": "Paid. Card number: **** 1111",
        "follow_through": {"expense": EXPENSE}}})
    assert result["follow_through"]["expense_id"] == ACTION + ":expense"


@pytest.mark.parametrize("change", [{"amount": "126"}, {"currency": "JPY"}, {"kind": "refund"}])
def test_rerecord_refresh_preserves_void_until_money_changes(ledger, change):
    prepare(ledger)
    record(ledger, {"expense": {**EXPENSE, "merchant": "Old"}})
    identity = ACTION + ":expense"
    expense(ledger, "void", expense_id=identity, reason="duplicate")
    record(ledger, {"expense": {**EXPENSE, "merchant": "Updated"}})
    row = ledger.get("action", identity)
    assert row["status"] == "void" and row["fields"]["merchant"] == "Updated"
    assert row["fields"]["void_reason"] == "duplicate"
    record(ledger, {"expense": {**EXPENSE, **change}})
    row = ledger.get("action", identity)
    assert row["status"] == "recorded"
    assert "void_reason" not in row["fields"] and "merchant" not in row["fields"]


def test_receipt_idempotency_trip_validation_and_void_list(ledger):
    row = expense(ledger, "record", **RECEIPT, trip_id=TRIP, source_action_id=ACTION)
    assert row["action_id"] == "expense:" + stable_id("receipt", RECEIPT["evidence_ref"])
    assert row["fields"]["source"] == "owner_receipt"
    assert row["fields"]["source_action_id"] == ACTION
    changed = expense(ledger, "record", expense={**RECEIPT, "amount": "20"}, trip_id=TRIP)
    assert changed["action_id"] == row["action_id"]
    assert len(expense(ledger, "list")) == 1
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="existing trip"):
        expense(ledger, "record", **RECEIPT, trip_id="unknown")
    assert ledger.path.read_bytes() == before
    expense(ledger, "void", expense_id=row["action_id"], reason="duplicate")
    assert expense(ledger, "list", trip_id=TRIP) == []
    assert expense(ledger, "list", trip_id=TRIP, include_void=True)[0]["status"] == "void"
    ledger.put("action", "ordinary-note", {}, action_type="note")
    with pytest.raises(ValueError, match="expense row"):
        expense(ledger, "void", expense_id="ordinary-note", reason="not an expense")


@pytest.mark.parametrize("data", [
    {"action": "record", "expense": EXPENSE},
    {"action": "record", **RECEIPT, "payment_method": "cash"},
    {"action": "record", **RECEIPT, "description": "4111111111111111"},
    {"action": "record", **RECEIPT, "expense": RECEIPT},
    {"action": "void", "expense_id": "missing", "reason": "x" * 201},
    {"action": "list", "include_void": "false"}, {"action": "list", "extra": 1},
    {"action": "export"},
])
def test_operation_refusals(ledger, data):
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError):
        dispatch(ledger.root, {"operation": "expense", "data": data})
    assert ledger.path.read_bytes() == before


def test_export_totals_table_duplicates_privacy_and_sort(ledger):
    rows = []
    for i, fields in enumerate([
        {"amount": "10.001", "description": "=SUM(1,2)", "date": "2026-11-12"},
        {"amount": "10.001", "merchant": "+formula", "date": "2026-11-12"},
        {"amount": "2.001", "kind": "refund", "category": "fees"},
        {"amount": "12000", "currency": "JPY", "merchant": "@formula"},
        {"amount": "999", "currency": "JPY"},
    ]):
        rows.append(expense(ledger, "record", trip_id=TRIP, **{**RECEIPT, "evidence_ref": f"receipt-{i}", **fields}))
    expense(ledger, "void", expense_id=rows[-1]["action_id"], reason="void")
    result = expense(ledger, "export", trip_id=TRIP)
    assert result["totals"] == {"USD": {"charges": "20.002", "refunds": "2.001", "net": "18.001"},
                                "JPY": {"charges": "12000", "refunds": "0", "net": "12000"}}
    assert result["count"] == 4
    assert result["possible_duplicates"] == [sorted([r["action_id"] for r in rows[:2]])]
    for kind, suffix in (("csv", ".csv"), ("markdown", ".md")):
        path = Path(result[kind])
        assert path == ledger.root / "exports" / "expenses" / (TRIP + suffix)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert rows[-1]["action_id"] not in path.read_text()
    with Path(result["csv"]).open(newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == "date kind category amount currency merchant description evidence_ref source expense_id".split()
        cells = list(reader)
    assert [r["date"] for r in cells] == sorted(r["date"] for r in cells)
    assert any(r["description"] == "'=SUM(1,2)" for r in cells)
    assert any(r["merchant"] == "'+formula" for r in cells)
    assert any(r["merchant"] == "'@formula" for r in cells)
    markdown = Path(result["markdown"]).read_text()
    assert "Untitled trip" in markdown and "lodging: 20.002" in markdown and "fees: -2.001" in markdown
    assert ledger.get("trip", TRIP)["fields"]["events"] == [OTHER]
    assert len(expense(ledger, "list", trip_id=TRIP)) == 4


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_formula_prefixes(ledger, prefix):
    expense(ledger, "record", trip_id=TRIP, **{**RECEIPT, "merchant": prefix + "formula"})
    result = expense(ledger, "export", trip_id=TRIP)
    with Path(result["csv"]).open(newline="") as handle:
        merchant = next(csv.DictReader(handle))["merchant"]
    # Ledger clean() normalizes carriage-return line boundaries to newlines.
    assert merchant == "'" + ("\n" if prefix == "\r" else prefix) + "formula"


@pytest.mark.parametrize("target", ["directory", "csv", "markdown"])
def test_export_refuses_symlinks(ledger, tmp_path, target):
    outside = tmp_path / "outside"
    outside.mkdir()
    exports = ledger.root / "exports"
    exports.mkdir()
    if target == "directory":
        (exports / "expenses").symlink_to(outside, target_is_directory=True)
    else:
        (exports / "expenses").mkdir()
        path = exports / "expenses" / (TRIP + (".csv" if target == "csv" else ".md"))
        path.symlink_to(outside / "must-not-write")
    with pytest.raises((ValueError, RuntimeError, PermissionError)):
        expense(ledger, "export", trip_id=TRIP)
    assert list(outside.iterdir()) == []


def test_unsafe_trip_filename_is_hashed(ledger):
    trip = "../../unsafe trip"
    ledger.put("trip", trip, {}, title="Synthetic trip")
    result = expense(ledger, "export", trip_id=trip)
    assert Path(result["csv"]).name == stable_id(trip) + ".csv"
    assert result["count"] == 0 and result["totals"] == {}


@pytest.mark.parametrize("op", ["action_upsert", "action_prepare", "action_confirm", "action_claim", "action_result", "action_cancel"])
@pytest.mark.parametrize("identity,action_type", [("expense:reserved", None), ("booking:expense", None),
                                                 ("arbitrary", "expense"), ("existing-expense", None)])
def test_generic_action_write_guards(ledger, op, identity, action_type):
    ledger.put("action", "existing-expense", {}, action_type="expense", status="recorded")
    data = {"action_id": identity}
    if action_type:
        data["action_type"] = action_type
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="expense records are written with operation expense or follow_through.expense"):
        dispatch(ledger.root, {"operation": op, "data": data})
    assert ledger.path.read_bytes() == before


def test_expenses_hidden_from_work_and_context_lists(ledger):
    row = expense(ledger, "record", **RECEIPT, trip_id=TRIP)
    for op, data, key in [("next_action", {}, "candidates"), ("next_action", {"loops_only": True}, "candidates"),
                          ("context", {"kind": "action"}, "items"), ("status", {}, "actions")]:
        result = dispatch(ledger.root, {"operation": op, "data": data})
        assert row["action_id"] not in [r["action_id"] for r in result[key]]


def test_schema_describes_expenses_without_breaking_existing_reason(ledger):
    validator = Draft7Validator(SCHEMA["parameters"])
    for data in ({"action": "record", "expense": RECEIPT, "trip_id": TRIP},
                 {"action": "record", **RECEIPT, "kind": "refund"},
                 {"action": "void", "expense_id": "booking:expense", "reason": "duplicate"},
                 {"action": "list", "include_void": True}, {"action": "export", "trip_id": TRIP}):
        assert list(validator.iter_errors({"operation": "expense", "data": data})) == []
    assert list(validator.iter_errors({"operation": "action_result", "data": {
        "outcome": "confirmed", "follow_through": {"expense": EXPENSE}}})) == []
    assert list(validator.iter_errors({"operation": "trip_watch_plan", "data": {"reason": "invented"}}))
