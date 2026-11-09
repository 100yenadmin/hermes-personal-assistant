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
        row = next(r for r in records(home) if r["fields"]["evidence_ref"] == f"statement {PATH} line {number}")
        assert row["fields"]["source"] == "statement" and row["fields"]["category"] == category
        assert row["fields"]["evidence_ref"] == f"statement {PATH} line {number}"
    assert records(home)[0]["action_id"] == "expense:" + stable_id("statement", PATH, "2026-11-01", "cafe", "10", "USD", "charge", "1")
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


def test_idempotent_reimport_and_changed_money_gets_a_new_identity(home):
    import_all(home)
    ids = [r["action_id"] for r in records(home)]
    import_all(home)
    assert [r["action_id"] for r in records(home)] == ids
    identity = records(home)[0]["action_id"]
    entry.dispatch(home, {"operation": "expense", "data": {"action": "void", "expense_id": identity, "reason": "duplicate"}})
    import_all(home)
    assert Ledger(home).get("action", identity)["status"] == "void"
    changed = [r[:] for r in ROWS]
    changed[0][2] = "12"
    write(home, changed)
    import_all(home)
    assert Ledger(home).get("action", identity)["status"] == "void"
    new = next(r for r in records(home) if r["fields"]["amount"] == "12")
    assert new["status"] == "recorded" and new["action_id"] not in ids
    assert len(records(home)) == 10 and set(ids) < {r["action_id"] for r in records(home)}


@pytest.mark.parametrize("column,value", [(0, "2026-11-02"), (1, "New merchant")])
def test_changed_date_or_merchant_is_distinct_and_does_not_replace_old_charge(home, column, value):
    import_all(home)
    identity = records(home)[0]["action_id"]
    entry.dispatch(home, {"operation": "expense", "data": {"action": "void", "expense_id": identity, "reason": "void"}})
    changed = [r[:] for r in ROWS]
    changed[0][column] = value
    write(home, changed)
    import_all(home)
    assert Ledger(home).get("action", identity)["status"] == "void"
    assert len(records(home)) == 10
    assert any(r["status"] == "recorded" and r["fields"][("date", "merchant")[column]] == value for r in records(home))


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


def categorized(home, **changes):
    preview = call(home, preview=True, **changes)
    return call(home, categories=[{"line": r["line"], "category": "other"} for r in preview["lines"]], **changes)


@pytest.mark.parametrize("layout", ["date,amount,merchant,currency", "txn date,post date,description,amount",
                                  "date,description,amount"])
def test_common_layouts_do_not_join_digits_across_cells(home, layout):
    amounts = ["107.00", "43.29", "12.99", "200.50", "18.25", "89.95", "3.99", "56.75", "24.00", "125.30",
               "47.21", "6.80", "33.17", "91.42", "15.00", "62.39", "9.55", "78.20", "120.99", "8.75",
               "29.60", "150.40", "11.15", "64.90", "5.25", "99.99", "22.45", "71.30", "16.85", "45.70"]
    headers = layout.split(",")
    rows = []
    for day, amount in enumerate(amounts, 1):
        cells = {"date": f"2026-11-{day:02d}", "txn date": f"2026-11-{day:02d}",
                 "post date": f"2026-11-{day:02d}", "amount": amount,
                 "merchant": "Cafe", "description": "Cafe", "currency": "USD"}
        rows.append([cells[h] for h in headers])
    write(home, rows, headers=headers)
    preview = call(home, preview=True, currency="USD")
    assert preview["count"] == 30 and preview["skipped"] == []
    assert preview["lines"][0]["date"] == "2026-11-01" and preview["lines"][0]["amount"] == "107"
    assert records(home) == [] and not (home / "exports").exists()
    assert categorized(home, currency="USD")["count"] == 30
    assert len(records(home)) == 30


@pytest.mark.parametrize("card", ["4111 1111 1111 1111", "4111111111111111", "card number: 4111…"])
@pytest.mark.parametrize("location", ["merchant", "ignored", "skipped", "header"])
@pytest.mark.parametrize("preview", [True, False])
def test_card_in_any_cell_refuses_entire_import(home, card, location, preview):
    headers = ["date", "merchant", "amount", "currency", "ignored"]
    rows = [["2026-11-01", "Cafe", "107.00", "USD", ""],
            ["2026-11-02", "Books", "12.99", "USD", ""]]
    if location == "header":
        headers[-1] = card
    elif location == "ignored":
        rows[1][-1] = card
    else:
        rows[1][1] = card
        if location == "skipped":
            rows[1][0] = "invalid date"
    write(home, rows, headers=headers)
    before = Ledger(home).path.read_bytes()
    request = {"preview": True} if preview else {"categories": [{"line": n, "category": "other"} for n in (1, 2)]}
    with pytest.raises(ValueError, match="card/account"):
        call(home, **request)
    assert records(home) == [] and Ledger(home).path.read_bytes() == before
    assert not (home / "exports").exists()


def test_path_spellings_share_identity_and_canonical_evidence(home):
    for path in (PATH, "./" + PATH, PATH.replace("/november", "//november")):
        import_all(home, path=path)
        assert len(records(home)) == 9
    assert {r["fields"]["evidence_ref"] for r in records(home)} == {
        f"statement {PATH} line {n}" for n in CATEGORIES}


@pytest.mark.parametrize("existing", [False, True])
def test_failed_nth_save_rolls_back_all_rows_and_writes_no_report(home, monkeypatch, existing):
    if existing:
        import_all(home)
        write(home, ROWS + [["2026-11-11", "New charge", "14", "USD", ""]])
    before = records(home)
    original = expenses.save
    calls = []

    def fail_after_save(*args, **kwargs):
        saved = original(*args, **kwargs)
        calls.append(saved)
        if len(calls) == 3:
            raise RuntimeError("synthetic save failure")
        return saved

    monkeypatch.setattr(expenses, "save", fail_after_save)
    with pytest.raises(RuntimeError, match="synthetic save failure"):
        categorized(home, name="failed-batch")
    assert len(calls) == 3 and records(home) == before
    assert not (home / "exports/statements/failed-batch.csv").exists()
    assert not (home / "exports/statements/failed-batch.md").exists()
    if not existing:
        assert not (home / "exports").exists()


def test_reexport_insert_then_shrink_preserves_charge_identity_and_void(home):
    rows = [["2026-11-01", "Cafe", "10", "USD", ""], ["2026-11-02", "Books", "20", "USD", ""]]
    write(home, rows)
    categorized(home)
    identity = records(home)[0]["action_id"]
    entry.dispatch(home, {"operation": "expense", "data": {"action": "void", "expense_id": identity, "reason": "void"}})
    write(home, [["2026-10-31", "Rail", "30", "USD", ""], *rows])
    categorized(home)
    row = Ledger(home).get("action", identity)
    assert row["status"] == "void" and row["fields"]["void_reason"] == "void"
    assert row["fields"]["merchant"] == "Cafe" and row["fields"]["evidence_ref"] == f"statement {PATH} line 2"
    before_ids = {r["action_id"] for r in records(home)}
    before_total = sum(int(r["fields"]["amount"]) for r in records(home))
    write(home, [rows[1]])
    categorized(home)
    assert {r["action_id"] for r in records(home)} == before_ids
    assert sum(int(r["fields"]["amount"]) for r in records(home)) == before_total == 60
    assert Ledger(home).get("action", identity)["status"] == "void"


def test_identical_charges_keep_occurrences_and_one_duplicate_pair(home):
    charge = ["2026-11-01", "Cafe", "10.00", "USD", ""]
    write(home, [charge, charge])
    result = categorized(home)
    ids = {"expense:" + stable_id("statement", PATH, "2026-11-01", "cafe", "10", "USD", "charge", str(n)) for n in (1, 2)}
    assert {r["action_id"] for r in records(home)} == ids
    assert len(result["possible_duplicates"]) == 1
    assert set(result["possible_duplicates"][0]["expense_ids"]) == ids
    categorized(home)
    assert len(records(home)) == 2
    write(home, [charge])
    categorized(home)
    assert {r["action_id"] for r in records(home)} == ids


def test_separate_files_keep_separate_charges_and_flag_overlap(home):
    write(home, [ROWS[0]])
    write(home, [ROWS[0]], path="imports/statements/overlap.csv")
    categorized(home)
    result = categorized(home, path="imports/statements/overlap.csv")
    assert len(records(home)) == 2 and len(result["possible_duplicates"]) == 1


def test_malformed_csv_becomes_value_error_with_line_number(home):
    (home / PATH).write_text('date,merchant,amount,currency\n2026-11-01,"Ca"fe,10,USD\n')
    with pytest.raises(ValueError, match="malformed statement CSV at line 2"):
        call(home, preview=True)
    assert records(home) == [] and not (home / "exports").exists()


def test_negative_computed_total_stays_numeric_while_text_is_quoted(home):
    write(home, [["2026-11-01", "-Shop", "10", "USD", ""], ["2026-11-02", "-Shop", "-15", "USD", ""]])
    result = categorized(home)
    with Path(result["paths"]["csv"]).open(newline="") as handle:
        table = list(csv.DictReader(handle))
    assert result["by_category"] == {"USD": {"other": "-5"}}
    assert table[-1]["kind"] == "category_total" and table[-1]["amount"] == "-5"
    assert table[0]["merchant"] == table[1]["merchant"] == "'-Shop"


@pytest.mark.parametrize("first,second,paired", [("SQ *JOES", "SQ *BOBS", False),
                                                ("AMZN MKTP*AB12CD", "amzn mktp", True),
                                                ("ＡＭＺＮ ＭＫＴＰ＃１２３４", "amzn mktp", True),
                                                ("Straße", "STRASSE", True)])
def test_merchant_normalization_preserves_names_and_strips_digit_suffixes(home, first, second, paired):
    receipt(home, "first", merchant=first)
    receipt(home, "second", merchant=second)
    assert len(expenses.card_duplicates(records(home))) == int(paired)


def test_empty_merchant_falls_back_to_description(home):
    write(home, [["2026-11-01", "  ", "Cafe", "10", "USD"]],
          headers=["date", "merchant", "description", "amount", "currency"])
    assert call(home, preview=True)["lines"][0]["merchant"] == "Cafe"
    categorized(home)
    assert records(home)[0]["fields"]["merchant"] == "Cafe"


@pytest.mark.parametrize("stem,slug", [("Nov 2026", "nov-2026"), (" ! November Statements ! ", "november-statements"),
                                     ("X" * 60, "x" * 41), ("!!!", "statement")])
def test_default_report_name_is_slugified_but_explicit_name_stays_strict(home, stem, slug):
    path = f"imports/statements/{stem}.csv"
    write(home, [ROWS[0]], path=path)
    result = categorized(home, path=path)
    assert Path(result["paths"]["csv"]).name == slug + ".csv"
    before = records(home)
    with pytest.raises(ValueError, match="invalid statement import"):
        categorized(home, path=path, name="Nov 2026")
    assert records(home) == before


@pytest.mark.parametrize("case,minutes_message,statement_message", [
    ("missing", "minutes path is not a regular file", "statement path is not a regular file"),
    ("symlink", "minutes path must not contain a symlink", "statement path must not contain a symlink"),
    ("size", "transcript exceeds 2 MB", "statement exceeds 2 MB"),
    ("nul", "NUL in transcript", "NUL in statement")])
def test_reader_error_label_preserves_exact_minutes_defaults(home, case, minutes_message, statement_message):
    from personal_assistant.minutes import _read
    path = "imports/statements/invalid.csv"
    target = home / path
    if case == "symlink":
        target.symlink_to(home / PATH)
    elif case == "size":
        target.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    elif case == "nul":
        target.write_bytes(b"\x00")
    with pytest.raises(ValueError) as original:
        _read(home, path)
    assert str(original.value) == minutes_message
    with pytest.raises(ValueError) as statement:
        call(home, path=path, preview=True)
    assert str(statement.value) == statement_message
