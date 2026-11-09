"""Offline statement reconciliation through the public PA entry contract."""
import csv
import io
import socket
import stat
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from personal_assistant import entry, expenses
from personal_assistant.state import Ledger, stable_id

PATH = "imports/statements/november.csv"
ROWS = [
    ["2026-11-01", "Cafe", "10", "USD", "debit"],
    ["2026-11-02", "Rail", "20", "USD", "debit"],
    ["2026-11-03", "Cafe", "-3", "USD", ""],
    ["2026-11-04", "Rail", "2", "USD", "refund"],
    ["2026-11-05", "Books", "7", "USD", "credit"],
    ["2026-02-30", "Bad date", "1", "USD", ""],
    ["2026-11-07", "Hotel", "100", "JPY", "debit"],
    ["2026-11-08", "Museum", "30", "JPY", ""],
    ["2026-11-09", "Shop", "9", "USD", ""],
    ["2026-11-10", "Fee", "1", "USD", ""],
]
CATEGORIES = dict(zip((1, 2, 3, 4, 5, 7, 8, 9, 10),
                      ("food", "transport", "food", "transport", "shopping", "lodging", "activity", "shopping", "fees")))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)


@pytest.fixture
def home(tmp_path):
    root = tmp_path / "profile"
    (root / "imports/statements").mkdir(parents=True)
    write(root)
    Ledger(root)
    return root


def write(home, rows=ROWS, headers=("DATE", "Merchant", "amount", "currency", "type"), path=PATH):
    text = io.StringIO(newline="")
    writer = csv.writer(text)
    writer.writerow(headers)
    writer.writerows(rows)
    (home / path).write_text(text.getvalue(), encoding="utf-8-sig")


def call(home, **changes):
    return entry.dispatch(home, {"operation": "expense", "data": {"action": "import", "path": PATH, **changes}})


def import_all(home, **changes):
    return call(home, categories=[{"line": n, "category": c} for n, c in CATEGORIES.items()], **changes)


def records(home):
    return expenses._rows(Ledger(home), include_void=True)


def test_preview_ten_lines_refunds_skipped_date_and_no_writes(home):
    ledger = Ledger(home)
    before = ledger.path.read_bytes()
    result = call(home, preview=True)
    assert result["count"] == 9 and len(result["lines"]) == 9
    assert result["lines"][0] == {"line": 1, "date": "2026-11-01", "merchant": "Cafe", "amount": "10",
                                   "currency": "USD", "kind": "charge"}
    for index, amount in ((2, "3"), (3, "2"), (4, "7")):
        assert result["lines"][index]["kind"] == "refund"
        assert result["lines"][index]["amount"] == amount
    assert result["skipped"][0]["line"] == 6 and "date" in result["skipped"][0]["reason"]
    assert records(home) == [] and ledger.path.read_bytes() == before
    assert not (home / "exports").exists()


def test_import_all_categories_private_reconciliation_and_no_send(home):
    result = import_all(home)
    assert result["count"] == 9 and result["sent"] is False
    assert result["by_category"] == {"USD": {"food": "7", "transport": "18", "shopping": "2", "fees": "1"},
                                      "JPY": {"lodging": "100", "activity": "30"}}
    assert result["possible_duplicates"] == [] and result["skipped"][0]["line"] == 6
    assert len(records(home)) == 9
    for number, category in CATEGORIES.items():
        identity = "expense:" + stable_id("statement", PATH, str(number))
        row = Ledger(home).get("action", identity)
        assert row["fields"]["source"] == "statement" and row["fields"]["category"] == category
        assert row["fields"]["evidence_ref"] == f"statement {PATH} line {number}"
    for kind, filename in (("csv", "november.csv"), ("markdown", "november.md")):
        path = Path(result["paths"][kind])
        assert path == home / "exports/statements" / filename
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert "expense:" in path.read_text()
    table = list(csv.DictReader(Path(result["paths"]["csv"]).open()))
    assert len([r for r in table if r["line"]]) == 9
    markdown = Path(result["paths"]["markdown"]).read_text()
    assert "USD food: 7" in markdown and "Possible duplicates" in markdown


@pytest.mark.parametrize("change,match", [("missing", "missing \\[1\\]"), ("unknown", "unknown \\[11\\]"),
                                         ("repeat", "repeated \\[1\\]")])
def test_category_coverage_refuses_without_partial_rows(home, change, match):
    categories = [{"line": n, "category": c} for n, c in CATEGORIES.items()]
    if change == "missing":
        categories = categories[1:]
    else:
        categories.append({"line": 11 if change == "unknown" else 1, "category": "other"})
    before = Ledger(home).path.read_bytes()
    with pytest.raises(ValueError, match=match):
        call(home, categories=categories)
    assert records(home) == [] and Ledger(home).path.read_bytes() == before
    assert not (home / "exports").exists()


def test_idempotent_reimport_updates_amount_and_preserves_void_until_money_changes(home):
    import_all(home)
    ids = [r["action_id"] for r in records(home)]
    import_all(home)
    assert [r["action_id"] for r in records(home)] == ids
    identity = "expense:" + stable_id("statement", PATH, "1")
    entry.dispatch(home, {"operation": "expense", "data": {"action": "void", "expense_id": identity, "reason": "duplicate"}})
    import_all(home)
    assert Ledger(home).get("action", identity)["status"] == "void"
    changed = [r[:] for r in ROWS]
    changed[0][2] = "12"
    write(home, changed)
    import_all(home)
    row = Ledger(home).get("action", identity)
    assert row["status"] == "recorded" and row["fields"]["amount"] == "12"
    assert len(records(home)) == 9 and {r["action_id"] for r in records(home)} == set(ids)


@pytest.mark.parametrize("column,value", [(0, "2026-11-02"), (1, "New merchant")])
def test_statement_date_or_merchant_correction_reopens_void(home, column, value):
    import_all(home)
    identity = "expense:" + stable_id("statement", PATH, "1")
    entry.dispatch(home, {"operation": "expense", "data": {"action": "void", "expense_id": identity, "reason": "void"}})
    changed = [r[:] for r in ROWS]
    changed[0][column] = value
    write(home, changed)
    import_all(home)
    assert Ledger(home).get("action", identity)["status"] == "recorded"


def receipt(home, ref, date="2026-11-10", **changes):
    return entry.dispatch(home, {"operation": "expense", "data": {
        "action": "record", "amount": "10", "currency": "USD", "category": "shopping", "kind": "charge",
        "date": date, "merchant": "amzn mktp", "evidence_ref": ref, **changes}})


def test_duplicate_rules_any_source_normalization_sorting_refunds_and_voids(home):
    first = receipt(home, "first", merchant=" AMZN   Mktp #1234")
    second = receipt(home, "second", date="2026-11-12", merchant="amzn mktp*ABC123")
    receipt(home, "subscription", date="2026-12-10")
    receipt(home, "other-amount", amount="11")
    receipt(home, "other-currency", currency="JPY")
    voided = receipt(home, "voided")
    entry.dispatch(home, {"operation": "expense", "data": {"action": "void", "expense_id": voided["action_id"], "reason": "void"}})
    expected = [{"expense_ids": [first["action_id"], second["action_id"]], "merchant": "amzn mktp",
                 "amount": "10", "currency": "USD", "dates": ["2026-11-10", "2026-11-12"]}]
    assert expenses.card_duplicates(records(home)) == expected
    assert expenses.card_duplicates(list(reversed(records(home)))) == expected
    receipt(home, "earlier-refund", date="2026-11-09", kind="refund")
    assert expenses.card_duplicates(records(home)) == expected
    receipt(home, "later-refund", date="2026-11-13", kind="refund")
    assert expenses.card_duplicates(records(home)) == []


def test_monthly_appends_cross_month_card_pair_preserves_invoice_duplicate_and_exports(home):
    bill = entry.dispatch(home, {"operation": "invoice", "data": {
        "action": "record", "direction": "payable", "counterparty": "amzn mktp", "reference": "synthetic",
        "amount": "10", "currency": "USD", "category": "services", "issue_date": "2026-10-01",
        "due_date": "2026-11-02", "evidence_ref": "Synthetic invoice"}})
    entry.dispatch(home, {"operation": "invoice", "data": {"action": "paid", "invoice_id": bill["action_id"],
                   "paid_on": "2026-11-02", "evidence": "Owner reports payment"}})
    first = receipt(home, "oct-charge", date="2026-10-31", merchant="AMZN Mktp #1234")
    second = receipt(home, "nov-charge", date="2026-11-02")
    result = entry.dispatch(home, {"operation": "finance", "data": {"action": "monthly", "month": "2026-11", "export": True}})
    assert result["possible_duplicates"] == [
        {"invoice_id": bill["action_id"], "expense_id": second["action_id"]},
        {"expense_ids": [first["action_id"], second["action_id"]], "merchant": "amzn mktp", "amount": "10",
         "currency": "USD", "dates": ["2026-10-31", "2026-11-02"]}]
    assert "amzn mktp: 10 USD" in Path(result["export"]["markdown"]).read_text()
    october = entry.dispatch(home, {"operation": "finance", "data": {"action": "monthly", "month": "2026-10"}})
    assert october["possible_duplicates"] == []


@pytest.mark.parametrize("path", ["imports/wrong.csv", "imports/statements/../november.csv", "/outside.csv"])
def test_refuse_path_escape(home, path):
    with pytest.raises(ValueError, match="under imports/statements"):
        call(home, path=path, preview=True)
    assert records(home) == []


@pytest.mark.parametrize("target", ["file", "directory"])
def test_refuse_symlink(home, target):
    if target == "file":
        (home / "imports/statements/link.csv").symlink_to(home / PATH)
        path = "imports/statements/link.csv"
    else:
        (home / "imports/statements/link").symlink_to(home / "imports/statements", target_is_directory=True)
        path = "imports/statements/link/november.csv"
    with pytest.raises(ValueError, match="symlink"):
        call(home, path=path, preview=True)


@pytest.mark.parametrize("text", ["date,merchant,amount,currency\n2026-11-01,4111 1111 1111 1111,10,USD\n",
                                  "date,merchant,amount,currency,ignored\nwrong,Cafe,10,USD,account number: 12345678\n",
                                  "card number: 4111 1111 1111 1111,merchant,date,amount,currency\n"])
def test_whole_file_private_data_refusal(home, text):
    (home / PATH).write_text(text)
    with pytest.raises(ValueError, match="card/account"):
        call(home, preview=True)
    assert records(home) == [] and not (home / "exports").exists()


def test_size_limit_missing_currency_and_currency_fallback(home):
    (home / PATH).write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="2 MB"):
        call(home, preview=True)
    write(home, [["2026-11-01", "Cafe", "10"]], headers=["date", "description", "amount"])
    with pytest.raises(ValueError, match="currency"):
        call(home, preview=True)
    assert call(home, preview=True, currency="USD")["lines"][0]["currency"] == "USD"
    assert records(home) == []


def test_public_schema_import_shapes_and_required_path(home):
    validator = Draft7Validator(entry.SCHEMA["parameters"])
    for data in ({"action": "import", "path": PATH, "preview": True},
                 {"action": "import", "path": PATH, "categories": [{"line": 1, "category": "food"}]}):
        assert validator.is_valid({"operation": "expense", "data": data})
    for data in ({"action": "import", "preview": True}, {"action": "import", "path": PATH}):
        assert not validator.is_valid({"operation": "expense", "data": data})
        with pytest.raises(ValueError):
            call(home, **{**data, "path": data.get("path", "")})


def test_report_escaping_totals_duplicates_and_private_rewrite(home):
    rows = [["2026-11-01", "=Shop|<test>\\name", "10", "USD", ""],
            ["2026-11-03", "=Shop|<test>\\name", "10", "USD", ""]]
    write(home, rows)
    result = call(home, categories=[{"line": n, "category": "shopping"} for n in (1, 2)], name="custom")
    assert len(result["possible_duplicates"]) == 1
    with Path(result["paths"]["csv"]).open(newline="") as handle:
        table = list(csv.DictReader(handle))
    assert table[0]["merchant"] == "'=Shop|<test>\\name"
    assert table[-1]["kind"] == "possible_duplicate" and table[-2]["amount"] == "20"
    assert "=Shop\\|&lt;test&gt;\\\\name" in Path(result["paths"]["markdown"]).read_text()
    for path in result["paths"].values():
        Path(path).chmod(0o644)
    call(home, categories=[{"line": n, "category": "shopping"} for n in (1, 2)], name="custom")
    assert all(stat.S_IMODE(Path(p).stat().st_mode) == 0o600 for p in result["paths"].values())
