"""Synthetic, offline accountant packs through the public PA interface."""
import csv
from decimal import Decimal
import socket
import stat
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, FormatChecker

from personal_assistant import expenses, finance
from personal_assistant.entry import SCHEMA, dispatch
from tests.test_finance import call, expense, invoice, ledger


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


def pack(ledger, **changes):
    return call(ledger, "tax_pack", **{"period_start": "2026-11-01", "period_end": "2026-11-30", **changes})


def statement(ledger, ref, **changes):
    return expense(ledger, "statement imports/statements/synthetic.csv line " + ref, **changes)


def test_period_boundaries_void_refunds_and_counterparty_spelling(ledger):
    for day in ("2026-10-31", "2026-11-01", "2026-11-30", "2026-12-01"):
        for direction in ("receivable", "payable"):
            invoice(ledger, direction + day, status="paid", paid_on=day, direction=direction,
                    amount="100" if direction == "receivable" else "20",
                    counterparty="First Vendor" if day == "2026-11-01" else " ＦＩＲＳＴ   VENDOR ")
        expense(ledger, day, date=day, amount="10", category="food")
    invoice(ledger, "void", status="void", amount="999")
    expense(ledger, "void", void=True, amount="999")
    expense(ledger, "refund", kind="refund", amount="3", category="food")
    view = pack(ledger)["currencies"]["USD"]
    assert view["income"] == {"by_category": {"services": "200"},
                              "by_counterparty": {"First Vendor": "200"}, "total": "200"}
    assert view["bills_paid"] == {"by_category": {"services": "40"},
                                  "by_counterparty": {"First Vendor": "40"}, "total": "40"}
    assert view["expenses"] == {"by_category": {"food": "17"}, "total": "17"}
    assert view["net"] == "143"


def test_open_at_end_issue_and_payment_cutoffs_and_order(ledger):
    for direction, key in (("receivable", "receivables"), ("payable", "payables")):
        early = invoice(ledger, direction + "early", direction=direction, due_date="2026-11-05", amount="2")
        tied = [invoice(ledger, direction + ref, direction=direction, due_date="2026-11-10", amount="3")
                for ref in ("tie-b", "tie-a")]
        later = invoice(ledger, direction + "later", direction=direction, status="paid", paid_on="2026-12-01",
                        issue_date="2026-11-30", due_date="2026-12-05", amount="4")
        invoice(ledger, direction + "inside", direction=direction, status="paid", paid_on="2026-11-30")
        invoice(ledger, direction + "future", direction=direction, issue_date="2026-12-01", due_date="2026-12-05")
        invoice(ledger, direction + "future-paid", direction=direction, status="paid", paid_on="2026-12-02",
                issue_date="2026-12-01", due_date="2026-12-05")
        invoice(ledger, direction + "void", direction=direction, status="void")
        bucket = pack(ledger)["currencies"]["USD"]["open_at_end"][key]
        assert bucket["total"] == "12"
        assert [r["invoice_id"] for r in bucket["invoices"]] == [early["action_id"],
            *sorted(r["action_id"] for r in tied), later["action_id"]]
        assert set(bucket["invoices"][0]) == {"invoice_id", "counterparty", "amount", "due_date"}


def test_receipt_matching_and_unmatched_card_duplicates(ledger):
    line = statement(ledger, "1", merchant="Cafe *AB12", category="food", amount="10", date="2026-11-10")
    receipt = expense(ledger, "Cafe receipt", merchant="cafe", category="other", amount="10", date="2026-11-12")
    statement(ledger, "2", merchant="Missing", amount="20")
    expense(ledger, "receipt alone", merchant="Alone", amount="7")
    first = statement(ledger, "3", merchant="Twice", amount="5", date="2026-11-15")
    second = statement(ledger, "4", merchant="Twice", amount="5", date="2026-11-16")
    result = pack(ledger)
    view = result["currencies"]["USD"]
    assert view["expenses"] == {"by_category": {"food": "10", "services": "37"}, "total": "47"}
    assert view["matched_receipts"] == 1
    assert view["receipts_missing"]["count"] == 3 and view["receipts_missing"]["total"] == "30"
    assert result["possible_duplicates"] == [{"expense_ids": [first["action_id"], second["action_id"]],
        "merchant": "twice", "amount": "5", "currency": "USD", "dates": ["2026-11-15", "2026-11-16"]}]
    assert not any({line["action_id"], receipt["action_id"]} == set(p["expense_ids"])
                   for p in result["possible_duplicates"])


def test_imported_statement_matches_receipt_just_outside_period(ledger):
    directory = ledger.root / "imports/statements"
    directory.mkdir(parents=True)
    with (directory / "synthetic.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows([["date", "merchant", "amount", "currency"], ["2027-01-02", "Cafe #12", "10", "USD"]])
    dispatch(ledger.root, {"operation": "expense", "data": {"action": "import",
        "path": "imports/statements/synthetic.csv", "categories": [{"line": 1, "category": "food"}]}})
    expense(ledger, "year end receipt", date="2026-12-31", merchant="Cafe", category="other")
    result = pack(ledger, period_start="2027-01-01", period_end="2027-01-31", export=True)
    view = result["currencies"]["USD"]
    assert view["matched_receipts"] == 1 and view["receipts_missing"]["count"] == 0
    assert view["expenses"] == {"by_category": {"food": "10"}, "total": "10"}
    assert result["possible_duplicates"] == []
    table = list(csv.DictReader(Path(result["export"]["csv"]).open()))
    details = [r for r in table if r["record_id"]]
    assert len(details) == 1 and details[0]["receipt"] == "matched:year end receipt"
    # The purchase counts once, on its statement line's date: the December pack does not count the receipt.
    december = pack(ledger, period_start="2026-12-01", period_end="2026-12-31")
    assert "USD" not in december["currencies"]


def test_consecutive_packs_add_up_across_the_boundary(ledger):
    # Two charges on statement lines either side of the year end, and one receipt for the later one.
    statement(ledger, "1", date="2026-12-29", merchant="Shop")
    statement(ledger, "2", date="2027-01-01", merchant="Shop")
    expense(ledger, "shop receipt", date="2026-12-31", merchant="Shop")
    totals = [pack(ledger, period_start=start, period_end=end)["currencies"].get("USD", {}).get("expenses", {}).get("total", "0")
              for start, end in (("2026-01-01", "2026-12-31"), ("2027-01-01", "2027-12-31"))]
    assert sum(Decimal(t) for t in totals) == Decimal("20")


def test_greedy_matching_prefers_distance_then_statement_date_and_ids(ledger):
    a = statement(ledger, "1", date="2026-11-10")
    b = statement(ledger, "2", date="2026-11-12")
    c = statement(ledger, "3", date="2026-11-12")
    x = expense(ledger, "receipt x", date="2026-11-12")
    y = expense(ledger, "receipt y", date="2026-11-12")
    matches = finance._receipt_matches(expenses._rows(ledger))
    assert matches == dict(zip(sorted([b["action_id"], c["action_id"]]), sorted([x["action_id"], y["action_id"]])))
    assert a["action_id"] not in matches
    # Equal distance uses the earlier statement date before either generated identity.
    matches = finance._receipt_matches([a, b, expense(ledger, "middle", date="2026-11-11")])
    assert list(matches) == [a["action_id"]]


@pytest.mark.parametrize("change", [{"merchant": ""}, {"merchant": "Other"}, {"amount": "11"},
                                   {"currency": "JPY"}, {"kind": "refund"}, {"date": "2026-11-14"}])
def test_matching_requires_every_money_fact_and_three_day_window(ledger, change):
    statement(ledger, "1")
    expense(ledger, "different receipt", **change)
    view = pack(ledger)["currencies"]["USD"]
    assert view["matched_receipts"] == 0 and view["receipts_missing"]["count"] == 1


def test_refund_pairs_match_and_net_in_statement_category(ledger):
    statement(ledger, "1", kind="refund", amount="3", category="food")
    expense(ledger, "refund receipt", kind="refund", amount="3", category="other", date="2026-11-12")
    view = pack(ledger)["currencies"]["USD"]
    assert view["expenses"] == {"by_category": {"food": "-3"}, "total": "-3"}
    assert view["net"] == "3" and view["matched_receipts"] == 1 and view["receipts_missing"]["count"] == 0


def test_mixed_questions_order_details_and_separate_currencies(ledger):
    bill = invoice(ledger, "bill", status="paid", direction="payable", amount="30", paid_on="2026-11-01")
    duplicate = expense(ledger, "outside bill duplicate", amount="30", date="2026-10-31")
    first = statement(ledger, "1", merchant="Repeat", amount="2", date="2026-10-31")
    second = statement(ledger, "2", merchant="Repeat", amount="2", category="other", date="2026-11-01")
    statement(ledger, "3", currency="JPY", merchant="Yen", amount="50", category="other")
    invoice(ledger, "open-r", amount="4")
    invoice(ledger, "open-p", amount="5", direction="payable")
    result = pack(ledger)
    assert result["currencies"]["USD"]["net"] == "-32"
    assert result["currencies"]["JPY"]["net"] == "-50"
    assert result["questions"] == [
        {"kind": "possible_duplicate", "expense_ids": [first["action_id"], second["action_id"]],
         "merchant": "repeat", "amount": "2", "currency": "USD", "dates": ["2026-10-31", "2026-11-01"]},
        {"kind": "possible_duplicate", "invoice_id": bill["action_id"], "expense_id": duplicate["action_id"],
         "merchant": "Synthetic Vendor", "amount": "30", "currency": "USD", "dates": ["2026-11-01", "2026-10-31"]},
        {"kind": "uncategorised", "currency": "JPY", "count": 1, "total": "50"},
        {"kind": "uncategorised", "currency": "USD", "count": 1, "total": "2"},
        {"kind": "receipts_missing", "currency": "JPY", "count": 1, "total": "50"},
        {"kind": "receipts_missing", "currency": "USD", "count": 1, "total": "2"},
        {"kind": "unpaid_at_end", "currency": "USD", "direction": "payable", "count": 1, "total": "5"},
        {"kind": "unpaid_at_end", "currency": "USD", "direction": "receivable", "count": 1, "total": "4"},
        {"kind": "several_currencies", "currencies": ["JPY", "USD"], "message": "totals are per currency and not converted"}]
    assert result["basis"] == "ledger records only; no currency conversion; not tax advice"


def test_missing_receipt_preview_is_capped_but_totals_are_complete(ledger):
    for n in range(53):
        statement(ledger, str(n), merchant=f"Merchant {n}", amount="1")
    missing = pack(ledger)["currencies"]["USD"]["receipts_missing"]
    assert (missing["count"], missing["total"], len(missing["lines"]), missing["more"]) == (53, "53", 50, 3)
    assert [r["expense_id"] for r in missing["lines"]] == sorted(r["expense_id"] for r in missing["lines"])


@pytest.mark.parametrize("change,message", [
    ({"period_end": "2026-10-31"}, "finance.period_end must be on or after period_start"),
    ({"period_start": "2024-01-01", "period_end": "2025-01-01"}, "a tax pack covers at most 366 days"),
    ({"period_start": None}, "invalid finance"), ({"period_end": "2026-02-30"}, "invalid finance"),
    ({"extra": True}, "invalid finance")])
def test_refusals_leave_ledger_unchanged(ledger, change, message):
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match=message):
        pack(ledger, **change)
    assert ledger.path.read_bytes() == before


def test_schema_missing_fields_and_future_leap_year_period(ledger):
    validator = Draft7Validator(SCHEMA["parameters"], format_checker=FormatChecker())
    valid = {"action": "tax_pack", "period_start": "2028-01-01", "period_end": "2028-12-31", "export": True}
    assert not list(validator.iter_errors({"operation": "finance", "data": valid}))
    assert pack(ledger, period_start="2028-01-01", period_end="2028-12-31")["currencies"] == {}
    for data in ({k: v for k, v in valid.items() if k != "period_start"},
                 {k: v for k, v in valid.items() if k != "period_end"}, {**valid, "extra": True},
                 {**valid, "export": "true"}):
        assert list(validator.iter_errors({"operation": "finance", "data": data}))
        with pytest.raises(ValueError, match="invalid finance"):
            finance.dispatch(ledger, data)


def test_export_paths_modes_formula_guard_markdown_and_read_only(ledger):
    invoice(ledger, "income", status="paid", amount="100")
    invoice(ledger, "bill", status="paid", direction="payable", amount="5")
    invoice(ledger, "unpaid", counterparty="Open|Vendor")
    statement(ledger, "1", merchant="Cafe", category="food")
    expense(ledger, "proof | cafe", merchant="Cafe", date="2026-11-12")
    statement(ledger, "2", merchant='=HYPERLINK("synthetic")|Vendor', amount="7")
    expense(ledger, "refund", kind="refund", amount="30", merchant="Refund")
    before, rows = ledger.path.read_bytes(), ledger.list("action")
    plain = pack(ledger)
    assert ledger.path.read_bytes() == before and ledger.list("action") == rows
    result = pack(ledger, export=True)
    assert ledger.path.read_bytes() == before and ledger.list("action") == rows
    assert {k: v for k, v in result.items() if k != "export"} == plain
    base = ledger.root / "exports/finance/tax-pack-2026-11-01_2026-11-30"
    assert result["export"] == {"csv": str(base) + ".csv", "markdown": str(base) + ".md"}
    for path in result["export"].values():
        assert stat.S_IMODE(Path(path).stat().st_mode) == 0o600
    with Path(result["export"]["csv"]).open(newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == "section date kind category amount currency counterparty evidence_ref record_id receipt".split()
        table = list(reader)
    assert all(None not in r for r in table)
    assert [r["section"] for r in table if r["record_id"]][:2] == ["income", "bills_paid"]
    assert any(r["receipt"] == "matched:proof | cafe" for r in table)
    assert any(r["receipt"] == "missing" and r["counterparty"].startswith("'=HYPERLINK") for r in table)
    assert any(r["kind"] == "expenses_total" and r["amount"] == "'-13" for r in table)
    assert all(not cell.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) for r in table for cell in r.values())
    markdown = Path(result["export"]["markdown"]).read_text()
    for text in ("# Tax pack 2026-11-01 to 2026-11-30", "Open\\|Vendor", "synthetic", "\\|Vendor",
                 "Income", "Bills paid", "Expenses", "Net: 108", "Open at the end", "Receipts missing",
                 "Possible duplicates (listed, never merged)", "Questions", "Ledger records only; no currency conversion; not tax advice.",
                 "card lines have no receipt", "| Date | Merchant | Amount | Record |", "By counterparty:"):
        assert text in markdown
    assert '{"kind"' not in markdown and "\\\"" not in markdown
    Path(result["export"]["csv"]).chmod(0o644)
    pack(ledger, export=True)
    assert stat.S_IMODE(Path(result["export"]["csv"]).stat().st_mode) == 0o600


@pytest.mark.parametrize("target", ["directory", "csv", "markdown"])
def test_tax_pack_export_refuses_symlinks(ledger, target):
    outside = ledger.root / "untouched"
    outside.write_text("Keep this")
    output = ledger.root / "exports/finance"
    output.parent.mkdir()
    if target == "directory":
        output.symlink_to(ledger.root, target_is_directory=True)
    else:
        output.mkdir()
        (output / ("tax-pack-2026-11-01_2026-11-30" + (".csv" if target == "csv" else ".md"))).symlink_to(outside)
    before = ledger.path.read_bytes()
    with pytest.raises((ValueError, RuntimeError, OSError)):
        pack(ledger, export=True)
    assert outside.read_text() == "Keep this" and ledger.path.read_bytes() == before


def test_tax_pack_decimal_precision(ledger):
    row = invoice(ledger, "large", status="paid")
    # Stored synthetic money exercises precision without the invoice text/card-number scan.
    ledger.put("action", row["action_id"], {"amount": "111111111111111111111111111111.123"})
    expense(ledger, "fraction", amount="0.002")
    assert pack(ledger)["currencies"]["USD"]["net"] == "111111111111111111111111111111.121"


def test_skill_tax_pack_held_email_and_no_tax_advice():
    root = Path(__file__).resolve().parents[1]
    skill = (root / "skills/finance-admin/SKILL.md").read_text()
    assert len(skill.encode()) < 8192
    section = skill.split("## Tax-season pack\n", 1)[1]
    assert skill.index("## Card statements") < skill.index("## Tax-season pack")
    for text in ("tax_pack", "period_start", "period_end", "export: true", "owner's profile", "ask once",
                 "cover email", "Hold it for the owner's yes to the exact recipient and text", "governed send path",
                 "Never send on PA's own", "no tax advice", "Never initiate a payment"):
        assert text.lower() in section.lower()
