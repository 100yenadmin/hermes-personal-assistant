"""Synthetic offline finance views through the public PA interface."""
import csv
import datetime as dt
import json
import stat
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, FormatChecker

from personal_assistant import finance
from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.state import Ledger, stable_id


BALANCE = {"account_label": "Main business account", "as_of": "2026-11-10",
           "amount": "001000.000", "currency": "USD", "evidence_ref": "Owner statement"}


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)
    monkeypatch.setattr(finance, "evaluation_moment", lambda data: dt.datetime.fromisoformat("2026-11-09T15:30:00+00:00"))
    result = Ledger(tmp_path)
    result.put("action", "pa:preferences", {"timezone": "Asia/Tokyo"})
    return result


def call(ledger, action, **data):
    return dispatch(ledger.root, {"operation": "finance", "data": {"action": action, **data}})


def balance(ledger, **changes):
    return call(ledger, "balance", **{**BALANCE, **changes})


def invoice(ledger, ref, *, status="open", **changes):
    paid_on = changes.pop("paid_on", "2026-11-10")
    data = {"action": "record", "direction": "receivable", "counterparty": "Synthetic Vendor",
            "reference": ref, "amount": "10", "currency": "USD", "category": "services",
            "issue_date": "2026-10-01", "due_date": "2026-11-10", "evidence_ref": "Synthetic invoice", **changes}
    row = dispatch(ledger.root, {"operation": "invoice", "data": data})
    if status != "open":
        data = {"action": "paid", "paid_on": paid_on, "evidence": "Owner reports payment"} if status == "paid" else {"action": "void", "reason": "Duplicate"}
        row = dispatch(ledger.root, {"operation": "invoice", "data": {"invoice_id": row["action_id"], **data}})
    return row


def expense(ledger, ref, *, void=False, **changes):
    data = {"action": "record", "amount": "10", "currency": "USD", "category": "services",
            "kind": "charge", "date": "2026-11-10", "merchant": "Synthetic Vendor", "evidence_ref": ref, **changes}
    row = dispatch(ledger.root, {"operation": "expense", "data": data})
    if void:
        row = dispatch(ledger.root, {"operation": "expense", "data": {
            "action": "void", "expense_id": row["action_id"], "reason": "Duplicate"}})
    return row


def test_balance_identity_idempotency_corrections_and_negative_amount(ledger):
    row = balance(ledger)
    identity = "balance:" + stable_id("balance", "main business account", "2026-11-10")
    assert row["action_id"] == identity and row["action_type"] == "balance" and row["status"] == "recorded"
    assert row["fields"]["amount"] == "1000"
    before = ledger.path.read_bytes()
    same = balance(ledger, account_label="  ＭＡＩＮ  Business ACCOUNT ", amount="1000.0", evidence_ref="Same facts")
    assert same == row and ledger.path.read_bytes() == before
    corrected = balance(ledger, amount="-20.125", evidence_ref="Corrected owner statement")
    assert corrected["action_id"] == identity and corrected["fields"]["amount"] == "-20.125"
    assert corrected["fields"]["previous"] == {"amount": "1000", "currency": "USD", "evidence_ref": "Owner statement"}
    changed_currency = balance(ledger, amount="-20.125", currency="JPY")
    assert changed_currency["fields"]["previous"] == {
        "amount": "-20.125", "currency": "USD", "evidence_ref": "Corrected owner statement"}
    assert len([r for r in ledger.list("action") if r["action_type"] == "balance"]) == 1
    assert balance(ledger, account_label="Zero", amount="-0.000")["fields"]["amount"] == "0"


@pytest.mark.parametrize("change,match", [
    ({"account_label": "Account 123456"}, "PA does not store account numbers"),
    ({"account_label": "card number: 4111 1111 1111 1111"}, "does not store"),
    ({"evidence_ref": "card number: 4111 1111 1111 1111"}, "does not store"),
    ({"account_label": "token=synthetic123456"}, "does not store"),
    ({"evidence_ref": "token=synthetic123456"}, "does not store"),
    ({"as_of": "2026-11-11"}, "owner-local today"),
    ({"evidence_ref": "mail-12345678"}, "does not store account numbers"),
    ({"evidence_ref": "https://example.com/login"}, "restricted details"),
    ({"account_label": " "}, "non-empty"), ({"evidence_ref": " "}, "non-empty"),
    ({"as_of": "2026-02-30"}, "invalid finance"),
    ({"amount": "1.0001"}, "invalid finance"),
])
def test_balance_refusals_are_byte_identical(ledger, change, match):
    balance(ledger)
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match=match):
        balance(ledger, **change)
    assert ledger.path.read_bytes() == before


def test_cash_position_all_buckets_boundaries_gaps_and_read_only(ledger):
    ids = {}
    for currency, age in (("USD", 8), ("JPY", 7)):
        label = currency + " main"
        balance(ledger, account_label=label, as_of="2026-11-01", amount="500", currency=currency)
        balance(ledger, account_label=label.upper(), as_of=f"2026-11-{10-age:02}", currency=currency)
        balance(ledger, account_label=currency + " spare", amount="100", currency=currency)
        for direction in ("receivable", "payable"):
            amounts = ("11", "20", "30", "40") if direction == "receivable" else ("7", "5", "8", "90")
            for offset, amount in zip((-1, 0, 7, 8), amounts):
                due = (dt.date(2026, 11, 10) + dt.timedelta(days=offset)).isoformat()
                ids[currency, direction, offset] = invoice(ledger, f"{currency}-{direction}-{offset}",
                    direction=direction, currency=currency, due_date=due, amount=amount)["action_id"]
        invoice(ledger, currency + "paid", status="paid", currency=currency, amount="900")
        invoice(ledger, currency + "void", status="void", currency=currency, amount="800")
        expense(ledger, currency + "start", date="2026-11-04", currency=currency, amount="10")
        expense(ledger, currency + "outside", date="2026-11-03", currency=currency, amount="100")
        expense(ledger, currency + "refund", kind="refund", currency=currency, amount="3")
        expense(ledger, currency + "void", void=True, currency=currency, amount="999")
        expense(ledger, currency + "future", date="2026-11-11", currency=currency, amount="200")
    invoice(ledger, "EUR-later", currency="EUR", due_date="2026-11-18")
    expense(ledger, "CAD-recent", currency="CAD")
    before = ledger.path.read_bytes()
    result = call(ledger, "cash_position")
    assert ledger.path.read_bytes() == before and result["as_of"] == "2026-11-10"
    assert result == call(ledger, "cash_position", as_of="2026-11-10")
    assert set(result["currencies"]) == {"USD", "JPY", "EUR", "CAD"}
    for currency, age in (("USD", 8), ("JPY", 7)):
        view = result["currencies"][currency]
        assert len(view["balances"]) == 2
        assert sorted(r["age_days"] for r in view["balances"]) == [0, age]
        for direction, name, total, overdue in (("receivable", "receivables", "50", "11"), ("payable", "payables", "13", "7")):
            buckets = view[name]
            assert buckets["overdue"]["total"] == overdue and buckets["due_7d"]["total"] == total
            assert [r["invoice_id"] for r in buckets["overdue"]["invoices"]] == [ids[currency, direction, -1]]
            assert [r["invoice_id"] for r in buckets["due_7d"]["invoices"]] == [ids[currency, direction, 0], ids[currency, direction, 7]]
            assert set(buckets["due_7d"]["invoices"][0]) == {"invoice_id", "amount", "counterparty", "due_date"}
        assert view["spent_7d"] == {"charges": "10", "refunds": "3", "net": "7"}
        assert view["projected_7d"] == {"basis": "projection", "amount": "1130"}
    for currency in ("EUR", "CAD"):
        assert "projected_7d" not in result["currencies"][currency]
    assert result["gaps"] == [{"currency": "CAD", "reason": "no_balance"}, {"currency": "EUR", "reason": "no_balance"},
                              {"currency": "USD", "account_label": "USD MAIN", "reason": "stale_balance", "age_days": 8}]


def test_cash_latest_label_across_currency_and_as_of_cutoff(ledger):
    balance(ledger, account_label="Main", as_of="2026-11-08", currency="USD")
    balance(ledger, account_label=" ＭＡＩＮ ", as_of="2026-11-09", currency="JPY", amount="200")
    balance(ledger, account_label="Main", as_of="2026-11-10", currency="EUR", amount="300")
    view = call(ledger, "cash_position", as_of="2026-11-09")
    # The same label in another currency never hides the earlier currency's balance.
    assert set(view["currencies"]) == {"USD", "JPY"}
    assert view["currencies"]["JPY"]["projected_7d"]["amount"] == "200"
    assert [b["age_days"] for b in view["currencies"]["USD"]["balances"]] == [1]
    later = call(ledger, "cash_position", as_of="2026-11-10")
    assert set(later["currencies"]) == {"USD", "JPY", "EUR"}
    assert call(ledger, "cash_position", as_of="2026-11-07") == {"as_of": "2026-11-07", "currencies": {}, "gaps": []}


def test_monthly_categories_currency_net_duplicates_and_read_only(ledger):
    invoice(ledger, "income-service", status="paid", amount="100")
    invoice(ledger, "income-product", status="paid", amount="20", category="products")
    bill = invoice(ledger, "bill", status="paid", direction="payable", amount="30", counterparty="Ｓｙｎｔｈｅｔｉｃ Vendor")
    invoice(ledger, "fees", status="paid", direction="payable", amount="5", category="fees")
    duplicate = expense(ledger, "match-three", amount="30", date="2026-11-13", merchant=" synthetic   VENDOR ")
    expense(ledger, "not-four", amount="30", date="2026-11-14")
    expense(ledger, "food", amount="10", category="food")
    expense(ledger, "refund", amount="4", category="food", kind="refund")
    invoice(ledger, "yen-income", status="paid", amount="500", currency="JPY")
    expense(ledger, "yen-spend", amount="50", currency="JPY", category="food")
    invoice(ledger, "prior", status="paid", paid_on="2026-10-31", amount="999")
    invoice(ledger, "next", status="paid", paid_on="2026-12-01", amount="999")
    invoice(ledger, "open", amount="999")
    invoice(ledger, "void", status="void", amount="999")
    expense(ledger, "prior-spend", date="2026-10-31", amount="999")
    expense(ledger, "next-spend", date="2026-12-01", amount="999")
    expense(ledger, "void-spend", void=True, amount="999")
    before = ledger.path.read_bytes()
    result = call(ledger, "monthly", month="2026-11")
    assert ledger.path.read_bytes() == before and not (ledger.root / "exports").exists()
    assert result["currencies"] == {
        "USD": {"income": {"by_category": {"products": "20", "services": "100"}, "total": "120"},
                "bills_paid": {"by_category": {"fees": "5", "services": "30"}, "total": "35"},
                "expenses": {"by_category": {"food": "6", "services": "60"}, "total": "66"}, "net": "19"},
        "JPY": {"income": {"by_category": {"services": "500"}, "total": "500"},
                "bills_paid": {"by_category": {}, "total": "0"},
                "expenses": {"by_category": {"food": "50"}, "total": "50"}, "net": "450"}}
    assert result["possible_duplicates"] == [{"invoice_id": bill["action_id"], "expense_id": duplicate["action_id"]}]
    assert call(ledger, "monthly", month="2025-01") == {"month": "2025-01", "currencies": {}, "possible_duplicates": []}


def test_duplicate_requires_same_amount_currency_and_normalized_party(ledger):
    invoice(ledger, "bill", status="paid", direction="payable", amount="30")
    expense(ledger, "other-amount", amount="31")
    expense(ledger, "other-currency", amount="30", currency="JPY")
    expense(ledger, "other-merchant", amount="30", merchant="Other Vendor")
    assert call(ledger, "monthly", month="2026-11")["possible_duplicates"] == []


def test_decimal_precision_large_and_fractional_totals(ledger):
    amount = "111111111111111111111111111111.123"
    balance(ledger, amount=amount)
    invoice(ledger, "fraction", amount="0.001")
    invoice(ledger, "paid-fraction", amount="2.123", status="paid")
    expense(ledger, "fraction-spend", amount="0.002")
    assert call(ledger, "cash_position")["currencies"]["USD"]["projected_7d"]["amount"] == "111111111111111111111111111111.124"
    assert call(ledger, "monthly", month="2026-11")["currencies"]["USD"]["net"] == "2.121"


def test_monthly_export_paths_modes_formula_safety_and_markdown(ledger):
    for n, prefix in enumerate(("=", "+", "-", "@", "\t")):
        expense(ledger, "export-" + str(n), merchant=prefix + "Synthetic|<Vendor>\\name")
    # Synthetic stored rows exercise CR/LF escaping without relying on normal write-time cleaning.
    for n, merchant in enumerate(("\rSynthetic\nVendor", "\nSynthetic\rVendor")):
        row = expense(ledger, "export-lines-" + str(n), amount="5")
        with ledger.connect() as conn:
            conn.execute("update actions set fields_json=? where action_id=?",
                         (json.dumps({**row["fields"], "merchant": merchant}), row["action_id"]))
    expense(ledger, "export-refund", amount="100", kind="refund", merchant="Refund")
    before = ledger.path.read_bytes()
    result = call(ledger, "monthly", month="2026-11", export=True)
    assert ledger.path.read_bytes() == before
    assert result["export"] == {"csv": str(ledger.root / "exports/finance/monthly-2026-11.csv"),
                                "markdown": str(ledger.root / "exports/finance/monthly-2026-11.md")}
    paths = {k: Path(v) for k, v in result["export"].items()}
    for path in paths.values():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with paths["csv"].open(newline="") as handle:
        table = list(csv.DictReader(handle))
    merchants = [r["counterparty"] for r in table if r["record_id"]]
    for prefix in ("=", "+", "-", "@", "\t", "\r", "\n"):
        assert any(cell.startswith("'" + prefix) for cell in merchants)
    assert all(not cell.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) for r in table for cell in r.values())
    assert any(r["kind"] == "expenses_total" and r["amount"] == "'-40" for r in table)
    assert any(r["kind"] == "net" and r["amount"] == "40" for r in table)
    markdown = paths["markdown"].read_text()
    assert "Synthetic\\|&lt;Vendor&gt;\\\\name" in markdown and " Synthetic Vendor" in markdown
    assert "Possible duplicates" in markdown
    # Existing exports are brought back to the same private mode on rewrite.
    paths["csv"].chmod(0o644)
    call(ledger, "monthly", month="2026-11", export=True)
    assert stat.S_IMODE(paths["csv"].stat().st_mode) == 0o600


@pytest.mark.parametrize("target", ["directory", "csv", "markdown"])
def test_monthly_export_refuses_symlinks(ledger, target):
    outside = ledger.root / "untouched"
    outside.write_text("Keep this")
    output = ledger.root / "exports/finance"
    output.parent.mkdir()
    if target == "directory":
        output.symlink_to(ledger.root, target_is_directory=True)
    else:
        output.mkdir()
        (output / ("monthly-2026-11" + (".csv" if target == "csv" else ".md"))).symlink_to(outside)
    before = ledger.path.read_bytes()
    with pytest.raises((ValueError, RuntimeError, OSError)):
        call(ledger, "monthly", month="2026-11", export=True)
    assert outside.read_text() == "Keep this" and ledger.path.read_bytes() == before


@pytest.mark.parametrize("operation", ["action_upsert", "action_prepare", "action_confirm", "action_cancel", "action_claim", "action_result"])
@pytest.mark.parametrize("target", ["balance", "reserved", "typed", "existing"])
def test_both_entry_guards_protect_balance_rows(ledger, operation, target):
    identity = balance(ledger)["action_id"]
    ledger.put("action", "existing-balance", {}, action_type="balance")
    data = {"action_id": {"balance": identity, "reserved": "balance:reserved", "typed": "arbitrary", "existing": "existing-balance"}[target],
            "fields": {"tampered": True}}
    if target == "typed":
        data["action_type"] = "balance"
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="balance records are written with operation finance"):
        dispatch(ledger.root, {"operation": operation, "data": data})
    assert ledger.path.read_bytes() == before


def test_schema_accepts_valid_payloads_rejects_unknown_extra_month_amount(ledger):
    validator = Draft7Validator(SCHEMA["parameters"], format_checker=FormatChecker())
    for data in ({"action": "balance", **BALANCE}, {"action": "balance", **BALANCE, "amount": "-3.125"},
                 {"action": "cash_position"}, {"action": "cash_position", "as_of": "2026-11-10"},
                 {"action": "monthly", "month": "2026-11"}, {"action": "monthly", "month": "2026-11", "export": True}):
        assert not list(validator.iter_errors({"operation": "finance", "data": data}))
    invalid = [{}, {"action": "send"}, {"action": "balance"}, {"action": "cash_position", "extra": True},
               {"action": "cash_position", "as_of": "2026-02-30"}, {"action": "monthly"},
               {"action": "monthly", "month": "2026-13"}, {"action": "monthly", "month": "2026-1"},
               {"action": "monthly", "month": "2026-11", "export": "true"}]
    invalid += [{"action": "balance", **BALANCE, **change} for change in (
        {"amount": "1e3"}, {"amount": "+1"}, {"amount": "1.0001"}, {"amount": 1},
        {"currency": "usd"}, {"account_label": "x" * 61}, {"evidence_ref": "x" * 1001}, {"extra": True})]
    for data in invalid:
        assert list(validator.iter_errors({"operation": "finance", "data": data}))
        before = ledger.path.read_bytes()
        with pytest.raises(ValueError):
            finance.dispatch(ledger, data)
        assert ledger.path.read_bytes() == before
    assert list(validator.iter_errors({"operation": "finance"}))
    assert "finance" in dispatch(ledger.root, {"operation": "status"})["operations"]


def test_skills_document_owner_evidence_cadence_and_projection():
    root = Path(__file__).resolve().parents[1]
    skill = (root / "skills/finance-admin/SKILL.md").read_text()
    for text in ("Cash position and monthly summary", "owner states or shows", "evidence", "Fridays",
                 "existing brief", "on request", "first working day", "previous month", "stale or missing",
                 "Never claim a bank balance PA did not get from the owner", "A projection is a projection"):
        assert text in skill
    route = (root / "skills/personal-assistant/SKILL.md").read_text()
    assert "states a balance, or asks for a cash position or monthly summary" in route


def test_unrelated_commitments_with_odd_fields_do_not_break_views(ledger):
    dispatch(ledger.root, {"operation": "action_upsert", "data": {"action_id": "rent-reminder", "fields": {"amount": 1200, "as_of": 5}}})
    balance(ledger)
    assert call(ledger, "cash_position")["currencies"]
    assert call(ledger, "monthly", month="2026-11")["month"] == "2026-11"


def test_refund_is_not_a_possible_duplicate(ledger):
    invoice(ledger, "bill", status="paid", direction="payable", amount="30", counterparty="Synthetic Vendor")
    expense(ledger, "refund", amount="30", date="2026-11-13", merchant="Synthetic Vendor", kind="refund")
    assert call(ledger, "monthly", month="2026-11")["possible_duplicates"] == []


@pytest.mark.parametrize("key", ["account_label", "evidence_ref"])
def test_grouped_iban_is_refused_byte_identical(ledger, key):
    balance(ledger)
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="account numbers"):
        balance(ledger, **{key: "MT84 MALT 0110 0001 2345 MTLC AST0 01S"})
    assert ledger.path.read_bytes() == before


def test_cross_month_duplicate_is_listed_in_the_bill_month(ledger):
    bill = invoice(ledger, "oct-bill", status="paid", direction="payable", amount="30", paid_on="2026-10-31")
    charge = expense(ledger, "nov-charge", amount="30", date="2026-11-01")
    assert call(ledger, "monthly", month="2026-10")["possible_duplicates"] == [
        {"invoice_id": bill["action_id"], "expense_id": charge["action_id"]}]
    assert call(ledger, "monthly", month="2026-11")["possible_duplicates"] == []


def test_past_as_of_counts_invoices_outstanding_then(ledger):
    balance(ledger, as_of="2026-11-01", amount="1000")
    invoice(ledger, "paid-later", status="paid", direction="payable", amount="100",
            due_date="2026-11-02", paid_on="2026-11-05")
    invoice(ledger, "paid-before", status="paid", direction="payable", amount="5",
            issue_date="2026-11-02", due_date="2026-11-03", paid_on="2026-11-04")
    past = call(ledger, "cash_position", as_of="2026-11-01")["currencies"]["USD"]
    assert past["payables"]["due_7d"]["total"] == "100"  # paid-before was not issued yet on 11-01
    assert past["projected_7d"]["amount"] == "900"
    later = call(ledger, "cash_position", as_of="2026-11-06")["currencies"]["USD"]
    assert later["payables"]["overdue"]["total"] == "0" and later["payables"]["due_7d"]["total"] == "0"


def test_open_bill_issued_after_as_of_still_counts(ledger):
    balance(ledger, amount="1000")
    invoice(ledger, "early-dated", direction="payable", amount="300", issue_date="2026-11-12", due_date="2026-11-15")
    view = call(ledger, "cash_position")["currencies"]["USD"]
    assert view["payables"]["due_7d"]["total"] == "300"
    assert view["projected_7d"]["amount"] == "700"
