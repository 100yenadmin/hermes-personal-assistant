"""Synthetic offline invoice bookkeeping through the public PA interface."""
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft7Validator, FormatChecker

from personal_assistant import invoices
from personal_assistant.context import loop_state
from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.state import Ledger, stable_id


INVOICE = {"direction": "receivable", "counterparty": "Synthetic Acme", "reference": "DEMO-A",
           "amount": "00125.500", "currency": "USD", "category": "services",
           "issue_date": "2026-11-01", "due_date": "2026-11-10", "evidence_ref": "synthetic-invoice.pdf"}


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)
    result = Ledger(tmp_path)
    result.put("action", "pa:preferences", {"timezone": "Asia/Tokyo"})
    result.put("trip", "synthetic-trip", {})
    return result


def call(ledger, action, **data):
    return dispatch(ledger.root, {"operation": "invoice", "data": {"action": action, **data}})


def record(ledger, **changes):
    return call(ledger, "record", **{**INVOICE, **changes})


def rows(ledger, identity):
    return [ledger.get("action", identity + suffix) for suffix in ("", ":due", ":loop")]


def test_re_record_keeps_existing_lead_days(ledger):
    identity = record(ledger, remind_days_before=10)["action_id"]
    assert record(ledger)["action_id"] == identity
    assert ledger.get("action", identity + ":due")["fields"]["lead_days"] == 10


def test_record_identity_idempotency_and_projection_fields(ledger):
    row = record(ledger, trip_id="synthetic-trip", description="Consulting")
    identity = "invoice:receivable:" + stable_id("invoice", "receivable", "synthetic acme", "demo-a")
    assert row["action_id"] == identity and row["action_type"] == "invoice" and row["status"] == "open"
    assert row["fields"]["amount"] == "125.5"
    same = record(ledger, counterparty="  SYNTHETIC   Acme ", amount="125.50")
    assert same["action_id"] == identity and same["trip_id"] == "synthetic-trip"
    assert len([r for r in ledger.list("action") if r["action_id"].startswith("invoice:")]) == 3
    row, due, loop = rows(ledger, identity)
    assert all(r["trip_id"] == "synthetic-trip" for r in (row, due, loop))
    assert due["action_type"] == loop["action_type"] == "commitment"
    assert due["status"] == "pending" and loop["status"] == "open"
    assert due["fields"] == {
        "radar_kind": "deadline", "event_date": "2026-11-10", "lead_days": 3,
        "title": "Invoice DEMO-A to   SYNTHETIC   Acme  due 2026-11-10",
        "next_action": "Draft a friendly payment reminder to   SYNTHETIC   Acme  for DEMO-A; send only after the owner's yes."}
    assert loop["fields"] == {
        "loop_kind": "waiting_on_them", "counterparty": "  SYNTHETIC   Acme ", "next_actor": "them",
        "next_step": "Payment of DEMO-A, 125.5 USD, due 2026-11-10",
        "opened_at": "2026-11-10", "source_action_id": identity, "chase_log": []}


@pytest.mark.parametrize("status", ["open", "paid", "void"])
@pytest.mark.parametrize("change", [{"amount": "126"}, {"currency": "JPY"},
                                    {"issue_date": "2026-11-02"}, {"due_date": "2026-11-11"}])
def test_money_refusals_are_byte_identical(ledger, status, change):
    row = record(ledger)
    if status == "paid":
        call(ledger, "paid", invoice_id=row["action_id"], paid_on="2026-11-09", evidence="Owner saw remittance")
    elif status == "void":
        call(ledger, "void", invoice_id=row["action_id"], reason="Duplicate")
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="void.*first"):
        record(ledger, **change)
    assert ledger.path.read_bytes() == before


def test_paid_closes_loop_with_local_noon_and_preserves_live_closure(ledger):
    identity = record(ledger)["action_id"]
    paid = call(ledger, "paid", invoice_id=identity, paid_on="2026-11-09", evidence="Remittance email from Acme")
    assert paid["status"] == "paid"
    assert paid["fields"]["paid_on"] == "2026-11-09"
    assert paid["fields"]["paid_evidence"] == "Remittance email from Acme"
    _, due, loop = rows(ledger, identity)
    assert due["status"] == loop["status"] == "completed"
    assert loop["fields"]["confirmation"] == {"by": "Synthetic Acme", "at": "2026-11-09T12:00:00+09:00",
                                               "evidence": "Remittance email from Acme"}
    assert loop_state(loop, {}) == "closed"
    assert call(ledger, "paid", invoice_id=identity, paid_on="2026-11-09", evidence="Remittance email from Acme")["status"] == "paid"
    assert record(ledger, description="Updated memo", remind_days_before=5)["status"] == "paid"
    _, due, refreshed = rows(ledger, identity)
    assert refreshed["fields"]["confirmation"] == loop["fields"]["confirmation"]
    assert loop_state(refreshed, {}) == "closed" and refreshed["status"] == "completed"
    assert due["status"] == "completed" and due["fields"]["lead_days"] == 5


def test_void_and_matching_revive_reset_only_invoice_closure_and_chases(ledger):
    identity = record(ledger)["action_id"]
    dispatch(ledger.root, {"operation": "action_upsert", "data": {"action_id": identity + ":loop", "fields": {
        "last_chased_at": "2026-11-12T10:00:00+09:00", "snoozed_until": "2026-11-13T10:00:00+09:00",
        "chase_at": "2026-11-12T09:00:00+09:00",
        "chase_log": [{"at": "2026-11-12T10:00:00+09:00", "step": "day2", "how": "draft held"}]}}})
    voided = call(ledger, "void", invoice_id=identity, reason="Wrong recipient")
    assert voided["status"] == "void" and voided["fields"]["void_reason"] == "Wrong recipient"
    _, due, loop = rows(ledger, identity)
    assert due["status"] == loop["status"] == "cancelled" and loop_state(loop, {}) == "closed"
    assert loop["fields"]["loop_cancelled"]["by"] == "owner"
    assert dt.datetime.fromisoformat(loop["fields"]["loop_cancelled"]["at"]).tzinfo is not None
    assert "confirmation" not in loop["fields"]
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="revive"):
        call(ledger, "paid", invoice_id=identity, paid_on="2026-11-12", evidence="Owner evidence")
    assert ledger.path.read_bytes() == before
    revived = record(ledger, amount="125.5", description="Owner corrected memo")
    assert revived["status"] == "open"
    assert not {"void_reason", "paid_on", "paid_evidence"} & revived["fields"].keys()
    _, due, loop = rows(ledger, identity)
    assert due["status"] == "pending" and loop["status"] == "open" and loop_state(loop, {}) == "open"
    assert loop["fields"]["chase_log"] == []
    assert not {"confirmation", "loop_cancelled", "last_chased_at", "snoozed_until"} & loop["fields"].keys()
    assert "chase_at" not in loop["fields"]


def test_live_rerecord_never_reopens_an_owner_closed_loop(ledger):
    identity = record(ledger)["action_id"]
    closure = {"by": "Owner", "at": "2026-11-11T10:00:00+09:00", "evidence": "Confirmed separately"}
    dispatch(ledger.root, {"operation": "action_upsert", "data": {
        "action_id": identity + ":loop", "status": "completed", "fields": {"confirmation": closure}}})
    record(ledger, description="Refreshed")
    loop = ledger.get("action", identity + ":loop")
    assert loop["status"] == "completed" and loop["fields"]["confirmation"] == closure


@pytest.mark.parametrize("direction", ["receivable", "payable"])
@pytest.mark.parametrize("lead", [0, 3, 60])
def test_radar_surfaces_exactly_on_lead_date_and_hides_settled(ledger, direction, lead):
    identity = record(ledger, direction=direction, remind_days_before=lead)["action_id"]
    surface = dt.date(2026, 11, 10) - dt.timedelta(days=lead)
    def radar(day):
        return dispatch(ledger.root, {"operation": "next_action", "data": {
            "radar": True, "at": day.isoformat() + "T00:00:00+09:00"}})
    assert radar(surface - dt.timedelta(days=1))["candidates"] == []
    item, = radar(surface)["candidates"]
    assert item["action_id"] == identity + ":due" and item["surface_at"] == surface.isoformat()
    assert item["date"] == "2026-11-10" and item["lead_days"] == lead
    if direction == "payable":
        assert ledger.get("action", identity + ":loop") is None
        assert item["title"] == "Invoice DEMO-A from Synthetic Acme due 2026-11-10"
        assert item["next_action"] == "Remind the owner to pay Synthetic Acme 125.5 USD by 2026-11-10. PA never pays."
    call(ledger, "paid", invoice_id=identity, paid_on="2026-11-10", evidence="Owner reports payment")
    assert radar(surface)["candidates"] == []
    with pytest.raises(ValueError, match="paid invoice cannot be voided"):
        call(ledger, "void", invoice_id=identity, reason="Duplicate")
    assert radar(surface)["candidates"] == []


def test_next_action_existing_day_ladder_and_bookkeeping(ledger):
    identity = record(ledger)["action_id"]
    before = ledger.path.read_bytes()
    for day, step in ((1, "none"), (2, "day2"), (5, "day5"), (10, "day10"), (11, "escalate")):
        result = dispatch(ledger.root, {"operation": "next_action", "data": {
            "loops_only": True, "at": f"2026-11-{10 + day:02}T00:00:00+09:00"}})
        item, = result["candidates"]
        assert item["action_id"] == identity + ":loop" and item["chase"]["step"] == step
        assert item["chase"]["age_days"] == day
    assert ledger.path.read_bytes() == before
    dispatch(ledger.root, {"operation": "action_upsert", "data": {"action_id": identity + ":loop", "fields": {
        "last_chased_at": "2026-11-12T09:00:00+09:00",
        "chase_log": [{"at": "2026-11-12T09:00:00+09:00", "step": "day2", "how": "draft held"}]}}})
    result = dispatch(ledger.root, {"operation": "next_action", "data": {
        "loops_only": True, "at": "2026-11-12T10:00:00+09:00"}})
    assert result["candidates"][0]["chase"]["step"] == "none"
    assert result["candidates"][0]["chase"]["next_chase_at"] == "2026-11-15T00:00:00+09:00"
    # Separate nudge actions remain available to the established follow-through path.
    nudge = dispatch(ledger.root, {"operation": "action_prepare", "data": {
        "action_id": identity + ":loop:nudge:day5", "summary": {"provider": "synthetic", "final_action": "send"}}})
    assert nudge["status"] == "prepared"
    call(ledger, "paid", invoice_id=identity, paid_on="2026-11-12", evidence="Owner reports receipt")
    assert loop_state(ledger.get("action", identity + ":loop"), {}) == "closed"
    assert dispatch(ledger.root, {"operation": "next_action", "data": {"loops_only": True}})["candidates"] == []


def test_owner_chase_time_before_invoice_synthetic_opening(ledger, monkeypatch):
    identity = record(ledger, due_date="2026-11-30")["action_id"]
    ledger.put("action", identity + ":loop", {"chase_at": "2026-11-20T09:00:00+09:00"})
    with ledger.connect() as conn:
        conn.execute("update actions set created_at=? where action_id=?",
                     ("2026-11-13T00:00:00+09:00", identity + ":loop"))
    assert ledger.get("action", identity + ":loop")["fields"]["opened_at"] == "2026-11-30"
    for hour, step in ((8, "none"), (10, "owner_time")):  # #233: an extra chase; day 2 stays on 2 December
        moment = dt.datetime.fromisoformat(f"2026-11-20T{hour:02}:00:00+09:00")
        monkeypatch.setattr(invoices, "evaluation_moment", lambda data: moment)
        row, = call(ledger, "list")
        assert (row["chase"]["step"], row["chase"]["next_chase_at"]) == (step, "2026-11-20T09:00:00+09:00")


def test_list_order_filters_owner_local_overdue_and_chase(ledger, monkeypatch):
    monkeypatch.setattr(invoices, "evaluation_moment", lambda data: dt.datetime.fromisoformat("2026-11-11T15:30:00+00:00"))
    late = record(ledger, reference="LATER", due_date="2026-11-14")
    early = record(ledger, reference="EARLIER", due_date="2026-11-09", trip_id="synthetic-trip")
    payable = record(ledger, direction="payable", category="lodging")
    paid = record(ledger, reference="PAID")
    call(ledger, "paid", invoice_id=paid["action_id"], paid_on="2026-11-10", evidence="Owner confirms")
    voided = record(ledger, reference="VOID")
    call(ledger, "void", invoice_id=voided["action_id"], reason="Duplicate")
    listed = call(ledger, "list")
    assert len(listed) == 5 and listed[0]["action_id"] == early["action_id"] and listed[-1]["action_id"] == late["action_id"]
    by_id = {r["action_id"]: r for r in listed}
    assert by_id[early["action_id"]]["days_overdue"] == 3
    assert by_id[early["action_id"]]["chase"]["step"] == "day2"
    assert by_id[payable["action_id"]]["days_overdue"] == 2 and "chase" not in by_id[payable["action_id"]]
    assert all(by_id[r["action_id"]]["days_overdue"] == 0 for r in (late, paid, voided))
    assert len(call(ledger, "list", direction="receivable", status="open")) == 2
    assert call(ledger, "list", trip_id="synthetic-trip")[0]["action_id"] == early["action_id"]
    assert len(call(ledger, "list", status="paid")) == len(call(ledger, "list", status="void")) == 1


@pytest.mark.parametrize("field", ["counterparty", "reference", "description", "evidence_ref", "trip_id"])
@pytest.mark.parametrize("private", ["card number: 4111 1111 1111 1111", "token=synthetic123456"])
def test_private_scan_every_record_text_leaves_bytes_unchanged(ledger, field, private):
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="does not store"):
        record(ledger, **{field: private})
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("counterparty", "Vendor 12345678"), ("description", "Account 12345678"),
    ("evidence_ref", "mail-12345678"), ("reference", "12345678901234567"),
    ("counterparty", "GB82 WEST 1234 5698 7654 32"), ("description", "DE89370400440532013000"),
    ("evidence_ref", "FR14 2004 1010 0505 0001 3M02 606"), ("reference", "GB82WEST12345698765432"),
])
def test_account_patterns_leave_bytes_unchanged(ledger, field, value):
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="payment or account numbers"):
        record(ledger, **{field: value})
    assert ledger.path.read_bytes() == before


def test_invoice_reference_digit_exception_and_non_account_numbers(ledger):
    # Synthetic, non-card digit sequences may be invoice numbers up to 16 digits.
    assert record(ledger, reference="1111111111111111")["status"] == "open"
    assert record(ledger, reference="12345678", description="Team of 1234567")["status"] == "open"


@pytest.mark.parametrize("action,fields", [
    ("paid", {"paid_on": "2026-11-10", "evidence": "card number: synthetic123"}),
    ("void", {"reason": "token=synthetic123456"}),
    ("paid", {"paid_on": "2026-10-31", "evidence": "Owner evidence"}),
    ("paid", {"paid_on": "2026-02-30", "evidence": "Owner evidence"}),
    ("paid", {"paid_on": "2026-11-10", "evidence": ""}),
    ("void", {"reason": ""}),
])
def test_paid_void_refusals_are_byte_identical(ledger, action, fields):
    identity = record(ledger)["action_id"]
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError):
        call(ledger, action, invoice_id=identity, **fields)
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("change", [
    {"amount": "0"}, {"amount": "1e3"}, {"amount": 12}, {"amount": "1.0001"}, {"amount": "-2"},
    {"currency": "usd"}, {"currency": "USDD"}, {"direction": "transfer"}, {"category": "food"},
    {"due_date": "2026-10-31"}, {"issue_date": "2026-02-30"}, {"due_date": "20261110"},
    {"counterparty": "x" * 121}, {"reference": "x" * 81}, {"description": "x" * 201},
    {"evidence_ref": "x" * 1001}, {"evidence_ref": ""}, {"counterparty": " "},
    {"trip_id": "unknown"}, {"remind_days_before": True}, {"remind_days_before": -1},
    {"remind_days_before": 61}, {"payment_method": "cash"},
])
def test_invalid_record_refusals(ledger, change):
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError):
        record(ledger, **change)
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("operation", ["action_upsert", "action_prepare", "action_confirm", "action_cancel", "action_claim", "action_result"])
@pytest.mark.parametrize("target", ["main", "due", "reserved", "typed", "existing"])
def test_both_entry_guards_protect_invoice_rows(ledger, operation, target):
    identity = record(ledger)["action_id"]
    ledger.put("action", "existing-invoice", {}, action_type="invoice")
    target_id = {"main": identity, "due": identity + ":due", "reserved": "invoice:reserved",
                 "typed": "arbitrary", "existing": "existing-invoice"}[target]
    data = {"action_id": target_id, "fields": {"tampered": True}}
    if target == "typed":
        data["action_type"] = "invoice"
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="invoice records are written"):
        dispatch(ledger.root, {"operation": operation, "data": data})
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("action", ["record", "paid", "void"])
def test_transaction_rolls_back_all_rows_on_projection_failure(ledger, action):
    identity = record(ledger)["action_id"]
    with ledger.connect() as conn:
        conn.execute("create trigger synthetic_fail before insert on actions when NEW.action_id like '%:due' "
                     "begin select raise(ABORT, 'synthetic projection failure'); end")
    before = ledger.path.read_bytes()
    with pytest.raises(Exception, match="synthetic projection failure"):
        if action == "record":
            record(ledger, reference="NEW", description="Must roll back")
        else:
            call(ledger, action, invoice_id=identity, **({"paid_on": "2026-11-10", "evidence": "Owner evidence"}
                                                       if action == "paid" else {"reason": "Duplicate"}))
    assert ledger.path.read_bytes() == before


def test_schema_valid_payloads_and_category_direction_rules():
    validator = Draft7Validator(SCHEMA["parameters"], format_checker=FormatChecker())
    for data in ({"action": "record", **INVOICE}, {"action": "record", **INVOICE, "direction": "payable", "category": "food"},
                 {"action": "paid", "invoice_id": "invoice:demo", "paid_on": "2026-11-10", "evidence": "Owner saw remittance"},
                 {"action": "void", "invoice_id": "invoice:demo", "reason": "Duplicate"},
                 {"action": "list"}, {"action": "list", "direction": "payable", "status": "paid", "trip_id": "demo"}):
        assert not list(validator.iter_errors({"operation": "invoice", "data": data}))
    for data in ({}, {"action": "send"}, {"action": "record"}, {"action": "paid", "invoice_id": "demo"},
                 {"action": "record", **INVOICE, "category": "food"},
                 {"action": "record", **INVOICE, "direction": "payable", "category": "products"},
                 {"action": "record", **INVOICE, "due_date": "2026-02-30"},
                 {"action": "record", **INVOICE, "remind_days_before": 61},
                 {"action": "list", "status": "pending"}, {"action": "list", "extra": 1}):
        assert list(validator.iter_errors({"operation": "invoice", "data": data}))
    assert list(validator.iter_errors({"operation": "invoice"}))


def test_finance_skill_registered_and_routes_with_safe_instructions():
    root = Path(__file__).resolve().parents[1]
    for name, key, value in (("openclaw.plugin.json", "skills", "skills/finance-admin"),
                             ("skills/travel-action-pack-manifest/openclaw.plugin.json", "skills", "../finance-admin"),
                             ("support-control/component.json", "required_skills", "finance-admin")):
        assert value in json.loads((root / name).read_text())[key]
    skill = (root / "skills/finance-admin/SKILL.md").read_text()
    front = yaml.safe_load(skill.split("---")[1])
    assert front["name"] == front["metadata"]["openclaw"]["skillKey"] == "finance-admin"
    assert "Never initiate a payment or transfer" in skill
    assert "authorised mail" in skill and "evidence_ref" in skill and "owner's yes" in skill
    assert "personal-assistant:finance-admin" in (root / "skills/personal-assistant/SKILL.md").read_text()


@pytest.mark.parametrize("reference", ["DEMO-A", "demo-a", " DEMO-A  "])
def test_reference_case_and_spacing_name_one_invoice(ledger, reference):
    first = record(ledger)["action_id"]
    assert record(ledger, reference=reference)["action_id"] == first


@pytest.mark.parametrize("key,value", [("description", "FY26 marketing retainer"), ("counterparty", "AB12 Creative Studio"),
    ("reference", "PO2026-000123-ABC"), ("description", "SS26 collection samples")])
def test_ordinary_codes_are_not_ibans(ledger, key, value):
    assert record(ledger, **{key: value})["status"] == "open"


def test_reference_codes_and_generated_ids_are_not_payment_data(ledger, monkeypatch):
    assert record(ledger, reference="SN18-OYAUYE1H65P4ELT")["status"] == "open"
    identity = record(ledger)["action_id"]
    import personal_assistant.invoices as inv
    seen = []
    real = inv._private
    monkeypatch.setattr(inv, "_private", lambda value: seen.append(value) or real(value))
    call(ledger, "paid", invoice_id=identity, paid_on="2026-11-12", evidence="Remittance email from Acme")
    assert all("invoice_id" not in v for v in seen if isinstance(v, dict))


def test_a_real_iban_in_the_reference_is_refused(ledger):
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="payment or account"):
        record(ledger, reference="FR14 2004 1010 0505 0001 3M02 606")
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("data,names,unknown", [
    # The three shapes a 0.18 lab run (s33) tried before giving up on marking an invoice paid.
    ({"action": "paid", "fields": {"invoice_id": "x", "paid_on": "2026-11-10", "evidence_ref": "RA-5521"}},
     "evidence, invoice_id, paid_on", "fields"),
    ({"action": "paid", "answers": {"invoice_id": "x"}}, "evidence, invoice_id, paid_on", "answers"),
    ({"action": "paid", "action_id": "x", "at": "2026-11-10T10:00:00+00:00", "proof": "RA-5521"},
     "evidence, invoice_id, paid_on", "action_id, at, proof"),
])
def test_invalid_call_names_the_fields_the_action_takes(tmp_path, data, names, unknown):
    with pytest.raises(ValueError) as error:
        dispatch(tmp_path, {"operation": "invoice", "data": data})
    message = str(error.value)
    assert f"paid takes {names}" in message and f"not accepted: {unknown}" in message
    assert "top level of data" in message and "RA-5521" not in message  # Key names only, never values.


def test_unknown_action_lists_the_actions(tmp_path):
    with pytest.raises(ValueError, match="action must be one of list, paid, record, void"):
        dispatch(tmp_path, {"operation": "invoice", "data": {"action": "pay"}})


def test_skill_shows_the_flat_paid_call():
    skill = " ".join((Path(__file__).resolve().parents[1] / "skills/finance-admin/SKILL.md").read_text().split())
    assert '{"action":"paid", "invoice_id":"<id from list>", "paid_on":"YYYY-MM-DD", "evidence":' in skill


@pytest.mark.parametrize("key", ["GB82WEST12345698765432", "4111 1111 1111 1111", "card number 4111111111111111 exp 12/29",
                                 "password=hunter2hunter2", "Smith", "correct_horse_battery_staple",
                                 "sk_live_abcdefghijklmnop"])
def test_hint_never_echoes_a_key_that_could_carry_data(tmp_path, key):
    with pytest.raises(ValueError) as error:
        dispatch(tmp_path, {"operation": "invoice", "data": {"action": "list", key: "x"}})
    message = str(error.value)
    assert key not in message and "4111" not in message and "hunter2" not in message and "sk_live" not in message
    assert "plus 1 other key not accepted" in message


@pytest.mark.parametrize("data", [{"action": "paid", "invoice_id": "x", "paid_on": "10/11/2026", "evidence": "RA"},
                                  {"action": "list", "status": "closed"}])
def test_right_names_wrong_values_point_at_the_values(tmp_path, data):
    with pytest.raises(ValueError, match="the field names are right, so check the values"):
        dispatch(tmp_path, {"operation": "invoice", "data": data})


def test_missing_fields_are_named(tmp_path):
    with pytest.raises(ValueError, match="missing: evidence, paid_on"):
        dispatch(tmp_path, {"operation": "invoice", "data": {"action": "paid", "invoice_id": "x"}})


def test_value_hint_lists_only_the_fields_sent(tmp_path):
    data = {"action": "record", "direction": "receivable", "counterparty": "Cedar Demo Co", "reference": "INV-1037",
            "amount": 850, "currency": "GBP", "issue_date": "2026-11-01", "due_date": "2026-11-15",
            "category": "services", "evidence_ref": "Owner message"}
    with pytest.raises(ValueError) as error:
        dispatch(tmp_path, {"operation": "invoice", "data": data})
    message = str(error.value)
    assert 'amount as a string like "850.00"' in message and "currency as 3 capital letters" in message
    assert "status open" not in message and "paid_on" not in message


DRAFT = {"counterparty": "Synthetic Acme", "currency": "GBP", "issue_date": "2026-11-30",
         "terms_days": 14, "lines": [{"description": "Consulting", "quantity": "12.500", "unit_price": "95.00"},
                                    {"description": "Materials", "quantity": "2", "unit_price": "40.00"}],
         "tax": {"label": "VAT", "rate_percent": "20"}}


def prepare(ledger, **changes):
    data = {**DRAFT, **changes}
    # None removes optional fields, making due-date and no-tax examples easy to read.
    data = {k: v for k, v in data.items() if v is not None}
    before = ledger.path.read_bytes()
    with ledger.connect() as conn:
        action_bytes = conn.execute("select * from actions order by action_id").fetchall()
        action_bytes = [tuple(row) for row in action_bytes]
    result = call(ledger, "prepare", **data)
    assert ledger.path.read_bytes() == before
    with ledger.connect() as conn:
        assert [tuple(row) for row in conn.execute("select * from actions order by action_id")] == action_bytes
    return result


def test_prepare_services_invoice_exact_totals_next_reference_and_no_writes(ledger):
    record(ledger, counterparty="Other Synthetic Client", reference="INV-2026-013",
           issue_date="2026-09-30", due_date="2026-10-14")
    record(ledger, reference="INV-2026-014", issue_date="2026-10-31", due_date="2026-11-14")
    draft = prepare(ledger)
    assert draft == {
        "prepared": True, "recorded": False, "direction": "receivable", "counterparty": "Synthetic Acme",
        "currency": "GBP", "issue_date": "2026-11-30", "due_date": "2026-12-14", "terms_days": 14,
        "reference": "INV-2026-015", "reference_source": "next_in_series", "reference_basis": "INV-2026-014",
        "lines": [{"description": "Consulting", "quantity": "12.5", "unit_price": "95.00", "amount": "1187.50"},
                  {"description": "Materials", "quantity": "2", "unit_price": "40.00", "amount": "80.00"}],
        "subtotal": "1267.50", "tax": {"label": "VAT", "rate_percent": "20", "amount": "253.50"},
        "total": "1521.00", "category": "services", "description": None, "warnings": [], "missing": [],
        "record_args": {"action": "record", "direction": "receivable", "counterparty": "Synthetic Acme",
                        "reference": "INV-2026-015", "amount": "1521.00", "currency": "GBP",
                        "issue_date": "2026-11-30", "due_date": "2026-12-14", "category": "services",
                        "evidence_ref": "draft:prepared-invoice"},
        "next_step": "Show the owner this draft invoice. Record it with record_args only after the owner's explicit yes; replace evidence_ref with where it was sent or saved."}


@pytest.mark.parametrize("currency,quantity,price,amount", [
    ("GBP", "3", "0.335", "1.01"), ("JPY", "3", "333.3", "1000"), ("KWD", "2", "1.2345", "2.469")])
def test_prepare_line_rounding_half_up_and_currency_precision(ledger, currency, quantity, price, amount):
    draft = prepare(ledger, currency=currency, tax=None, reference="DEMO-P",
                    lines=[{"description": "Service", "quantity": quantity, "unit_price": price}])
    assert draft["lines"][0]["amount"] == draft["subtotal"] == draft["total"] == amount
    assert draft["tax"] is None


def test_prepare_rounds_lines_before_subtotal_and_tax(ledger):
    draft = prepare(ledger, lines=[{"description": "Service", "quantity": "1", "unit_price": "0.005"}] * 2,
                    tax={"label": "Tax", "rate_percent": "25"})
    assert [line["amount"] for line in draft["lines"]] == ["0.01", "0.01"]
    assert (draft["subtotal"], draft["tax"]["amount"], draft["total"]) == ("0.02", "0.01", "0.03")


def test_prepare_large_operands_preserve_all_digits(ledger):
    operand = "1" * 40
    draft = prepare(ledger, lines=[{"description": "Service", "quantity": operand, "unit_price": operand}],
                    tax={"label": "Tax", "rate_percent": "100"})
    expected = str(int(operand) ** 2)
    assert draft["lines"][0]["amount"] == draft["subtotal"] == draft["tax"]["amount"] == expected + ".00"
    assert draft["total"] == str(2 * int(expected)) + ".00"


def test_prepare_explicit_due_date_and_given_reference(ledger):
    draft = prepare(ledger, terms_days=None, due_date="2026-11-30", reference="DEMO-P", tax=None)
    assert draft["due_date"] == "2026-11-30" and draft["terms_days"] is None
    assert draft["reference"] == "DEMO-P" and draft["reference_source"] == "given"
    assert draft["reference_basis"] is None


@pytest.mark.parametrize("changes", [{"due_date": "2026-12-14"}, {"terms_days": None}])
def test_prepare_needs_exactly_one_due_date_or_terms_days(ledger, changes):
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="exactly one of due_date or terms_days"):
        prepare(ledger, **changes)
    assert ledger.path.read_bytes() == before


def test_prepare_no_usable_receivable_series_asks_owner_for_reference(ledger):
    record(ledger)  # A reference without a trailing number cannot define a series.
    record(ledger, direction="payable", category="other", reference="BILL-099")
    draft = prepare(ledger)
    assert draft["reference"] is draft["record_args"] is draft["reference_basis"] is None
    assert draft["reference_source"] == "none" and draft["missing"] == ["reference"]


def test_prepare_selects_latest_series_then_max_number_and_widest_width_including_void(ledger):
    record(ledger, reference="OLD-999", issue_date="2026-09-30", due_date="2026-10-01")
    record(ledger, reference="NEW-0012", issue_date="2026-10-30", due_date="2026-10-31")
    voided = record(ledger, reference="NEW-25", issue_date="2026-10-01", due_date="2026-10-02")
    call(ledger, "void", invoice_id=voided["action_id"], reason="Cancelled draft")
    draft = prepare(ledger)
    assert (draft["reference"], draft["reference_basis"]) == ("NEW-0026", "NEW-25")


def test_prepare_series_date_tie_uses_larger_number_and_accepts_plain_numbers(ledger):
    record(ledger, reference="INV-007")
    record(ledger, reference="1043", counterparty="Other Synthetic Client")
    draft = prepare(ledger)
    assert (draft["reference"], draft["reference_basis"]) == ("1044", "1043")


def test_prepare_duplicate_warnings_use_record_counterparty_and_reference_normalization(ledger):
    record(ledger, reference="DEMO-P", amount="1521", currency="GBP")
    draft = prepare(ledger, counterparty="  ＳＹＮＴＨＥＴＩＣ   Acme ", reference="demo-p")
    assert draft["warnings"] == [
        "reference already used for   ＳＹＮＴＨＥＴＩＣ   Acme : demo-p",
        "possible duplicate of DEMO-P issued 2026-11-01"]


@pytest.mark.parametrize("status,days,currency,warns", [
    ("open", 31, "GBP", True), ("open", -31, "GBP", True), ("open", 32, "GBP", False),
    ("paid", 0, "GBP", False), ("void", 0, "GBP", False), ("open", 0, "USD", False)])
def test_prepare_possible_duplicate_only_open_same_currency_within_31_days(ledger, status, days, currency, warns):
    issued = (dt.date(2026, 11, 30) + dt.timedelta(days=days)).isoformat()
    row = record(ledger, amount="1521", currency=currency, issue_date=issued, due_date=issued)
    if status == "paid":
        call(ledger, "paid", invoice_id=row["action_id"], paid_on=issued, evidence="Owner confirms")
    elif status == "void":
        call(ledger, "void", invoice_id=row["action_id"], reason="Cancelled")
    assert bool(prepare(ledger, reference="DEMO-P")["warnings"]) is warns


@pytest.mark.parametrize("currency", ["GBP", "JPY", "KWD"])
def test_prepare_record_args_round_trip_creates_open_invoice_and_chase_loop(ledger, currency):
    draft = prepare(ledger, reference="DEMO-P", currency=currency,
                    description="November services", trip_id="synthetic-trip", category="products")
    assert Draft7Validator(invoices.OP_SCHEMA, format_checker=FormatChecker()).is_valid(draft["record_args"])
    args = draft["record_args"]
    row = dispatch(ledger.root, {"operation": "invoice", "data": args})
    assert row["status"] == "open" and row["fields"]["direction"] == "receivable"
    assert row["fields"]["amount"] == invoices._number(Decimal(draft["total"]))
    assert row["fields"]["description"] == "November services" and row["trip_id"] == "synthetic-trip"
    assert ledger.get("action", row["action_id"] + ":loop")["status"] == "open"


@pytest.mark.parametrize("description", ["Account 12345678", "GB82 WEST 1234 5698 7654 32",
    "DE89370400440532013000", "token=synthetic123456", "passport number ABCD", " ", "x" * 201])
def test_prepare_rejects_restricted_or_invalid_line_description_without_writes(ledger, description):
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError):
        prepare(ledger, lines=[{"description": description, "quantity": "1", "unit_price": "1"}])
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("changes", [
    {"lines": []}, {"lines": DRAFT["lines"] * 25 + DRAFT["lines"][:1]},
    {"tax": {"label": "VAT", "rate_percent": "101"}},
    {"tax": {"label": " ", "rate_percent": "20"}}, {"tax": {"label": "VAT", "rate_percent": 20.0}},
    {"tax": {"label": "VAT", "rate_percent": "20", "extra": True}},
    {"due_date": "2026-11-29", "terms_days": None}, {"issue_date": "2026-02-30"},
    {"terms_days": -1}, {"terms_days": 121}, {"terms_days": True}, {"category": "food"},
    {"trip_id": "unknown"}, {"counterparty": " "}, {"reference": " "},
] + [{"lines": [{"description": "Service", "quantity": q, "unit_price": p, **extra}]}
     for q, p, extra in [("0", "1", {}), ("1", "0", {}), (1.5, "1", {}), ("1", 1.5, {}),
                         ("1.0001", "1", {}), ("1", "1.00001", {}), ("1e2", "1", {}),
                         ("1", "1", {"extra": True}), ("1", "0.0001", {})]])
def test_prepare_invalid_fields_without_writes(ledger, changes):
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError):
        prepare(ledger, **changes)
    assert ledger.path.read_bytes() == before


def test_prepare_unknown_keys_hint_names_prepare_fields_without_values(ledger):
    with pytest.raises(ValueError) as error:
        prepare(ledger, fields={"private": "do not echo"})
    message = str(error.value)
    for name in ("prepare takes counterparty, currency, issue_date, lines", "one of due_date or terms_days",
                 "category", "description", "reference", "tax", "trip_id", "not accepted: fields"):
        assert name in message
    assert "do not echo" not in message


def test_prepare_entry_description_and_embedded_schema():
    assert "action prepare" in SCHEMA["parameters"]["properties"]["data"]["description"]
    assert any(branch["properties"]["action"] == {"const": "prepare"} for branch in invoices.OP_SCHEMA["oneOf"])
    payload = {"operation": "invoice", "data": {"action": "prepare", **DRAFT}}
    assert Draft7Validator(SCHEMA["parameters"], format_checker=FormatChecker()).is_valid(payload)
