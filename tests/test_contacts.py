"""Synthetic file-to-file contact cleanup through the public entry contract."""
import csv
import hashlib
import io
import json
from pathlib import Path
import socket
import stat

import pytest
import yaml
from jsonschema import Draft7Validator

from personal_assistant import contacts, entry

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)


def source(home, text):
    path = home / "imports/contacts/input.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def call(home, **changes):
    return entry.dispatch(home, {"operation": "contacts", "data": {
        "action": "dedupe", "path": "imports/contacts/input.csv", "name": "demo", **changes}})


def table(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def changes(result):
    return table(result["paths"]["changes_csv"])


def snapshot(home):
    return {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}


def test_normalisation_and_google_columns(tmp_path):
    source(tmp_path, '\ufeff  Display Name ,E-mail 1 - Value,E-mail 2 - Value,Phone 1 - Value,Company,Job Title,Notes,Extra\n'
           '  Casey   Demo ," A@EXAMPLE.INVALID ; b@example.invalid, C@example.invalid ::: bad-address ",a@example.invalid,00 44 (20) 5550 1010,  Demo   Co , Lead   Dev ,  a   note ,  extra   value  \n')
    result = call(tmp_path)
    row = table(result["paths"]["clean"])[0]
    assert row == {"contact_id": "c-" + hashlib.sha256(b"1").hexdigest()[:10], "name": "Casey Demo", "given_name": "", "family_name": "",
                   "emails": "a@example.invalid; b@example.invalid; c@example.invalid", "phones": "+442055501010",
                   "company": "Demo Co", "title": "Lead Dev", "notes": "a note", "invalid_emails": "bad-address",
                   "source_rows": "1", "Extra": "extra value"}
    assert result["counts"]["normalised_fields"] == 7
    assert result["counts"]["invalid_emails"] == 1
    assert len([c for c in changes(result) if c["kind"] == "normalised"]) == 7


@pytest.mark.parametrize("header", ["name", "full name", "display name", "NAME"])
def test_full_name_aliases(tmp_path, header):
    source(tmp_path, header + ',email\nCasey Demo,c@example.invalid\n')
    assert table(call(tmp_path)["paths"]["clean"])[0]["name"] == "Casey Demo"


@pytest.mark.parametrize("first,last", [("first name", "last name"), ("given name", "family name")])
def test_split_name_aliases(tmp_path, first, last):
    source(tmp_path, f'{first},{last}\n Casey , Demo \n')
    assert table(call(tmp_path)["paths"]["clean"])[0]["name"] == "Casey Demo"


@pytest.mark.parametrize("header", ["email", "e-mail", "email address", "E-mail 2 - Value", "Email 3 - Value"])
def test_email_aliases(tmp_path, header):
    source(tmp_path, header + '\nA@EXAMPLE.INVALID\na@example.invalid\n')
    assert call(tmp_path)["counts"]["contacts_out"] == 1


@pytest.mark.parametrize("header", ["phone", "mobile", "phone number", "Phone 2 - Value"])
def test_phone_aliases(tmp_path, header):
    source(tmp_path, header + '\n(202) 555-0101\n2025550101\n')
    assert call(tmp_path)["counts"]["contacts_out"] == 1


@pytest.mark.parametrize("header,field", [("organization", "company"), ("organization 1 - name", "company"),
                                         ("title", "title"), ("organization 1 - title", "title")])
def test_company_title_aliases(tmp_path, header, field):
    source(tmp_path, f'name,{header}\nCasey,  Demo   Value \n')
    assert table(call(tmp_path)["paths"]["clean"])[0][field] == "Demo Value"


@pytest.mark.parametrize("number,code,expected", [
    ("(202) 555-0101", None, "2025550101"), ("+1 (202) 555-0101", "1", "+12025550101"),
    ("001 (202) 555-0101", None, "+12025550101"), ("0202.555.0101", "1", "+12025550101"),
    ("202.555.0101", "1", "+12025550101"), ("1-202-555-0101", "1", "+12025550101"),
    ("6591234567", "65", "+6591234567"), ("9123 4567", "65", "+6591234567"),
    ("090-1234-5678", "81", "+819012345678"), ("819012345678", "81", "+819012345678"), ("010-1234-5678", "82", "+821012345678"),
    ("123-45", None, "12345"), ("00", None, "+"),
    ("06 1234 5678", "39", "+390612345678"), ("333 123 4567", "39", "+393331234567"),
    ("393 123 4567", "39", "+393931234567"), ("39 393 123 4567", "39", "+393931234567"), ("39 02 1234 567", "39", "+39021234567"),
    ("07 07 12 34 56", "225", "+2250707123456"), ("225 07 07 12 34 56", "225", "+2250707123456"), ("020 7946 0018", "44", "+442079460018")])
def test_phone_rules(tmp_path, number, code, expected):
    source(tmp_path, f'name,phone\nCasey,{number}\n')
    result = call(tmp_path, **({"default_country_code": code} if code else {}))
    assert table(result["paths"]["clean"])[0]["phones"].removeprefix("'") == expected


def test_transitive_matching_not_name_alone_and_short_phone_kept(tmp_path):
    source(tmp_path, 'name,email,phone\nCasey,a@example.invalid,\nCasey Demo,A@EXAMPLE.INVALID,2025550101\n'
           'casey demo,c@example.invalid,(202)555-0101\nJosé-Li,d@example.invalid,12345\nJoseLi,e@example.invalid,12345\n')
    result = call(tmp_path)
    assert [r["source_rows"] for r in table(result["paths"]["clean"])] == ["1; 2; 3", "4", "5"]
    assert result["possible_duplicates"] == [{"rows": [4, 5], "name": "José-Li"}]
    assert result["counts"]["rows_merged"] == 2
    assert table(result["paths"]["clean"])[1]["phones"] == "12345"


def test_merge_choices_alternates_and_kept_origins(tmp_path):
    source(tmp_path, 'name,email,company,title,notes,Custom\n'
           'Long,a@example.invalid,First,Lead,one,\n'
           'Long Name,a@example.invalid,Second,Other,two,Extra\n'
           'name long,a@example.invalid,First,Lead,one,Alternate\n')
    result = call(tmp_path)
    row = table(result["paths"]["clean"])[0]
    assert row["name"] == "Long Name" and row["company"] == "First" and row["title"] == "Lead"
    assert row["notes"] == "one | two" and row["Custom"] == "Extra"
    log = changes(result)
    assert {(c["field"], c["other"]) for c in log if c["kind"] == "alternate"} == {
        ("name", "Long"), ("name", "name long"), ("company", "Second"), ("title", "Other"), ("Custom", "Alternate")}
    merged = next(c for c in log if c["kind"] == "merged")
    origins = json.loads(merged["kept_from"])
    assert origins["name"] == 2 and origins["company"] == 1 and origins["Custom"] == 2
    assert origins["notes"] == {"one": 1, "two": 2}


def test_invalid_emails_do_not_match_and_blank_rows_count(tmp_path):
    source(tmp_path, 'name,email,notes\nA,bad,\nB,bad,\nC,a@@example.invalid,\nD,a@example,\n,,only notes\n\n')
    result = call(tmp_path)
    assert result["counts"]["contacts_out"] == 5 and result["counts"]["invalid_emails"] == 4
    assert result["counts"]["blank_rows"] == 1 and result["counts"]["rows_read"] == 6
    assert all(not r["emails"] for r in table(result["paths"]["clean"]))
    assert [c["row"] for c in changes(result) if c["kind"] == "blank_row"] == ["6"]


def test_determinism_source_ledger_unchanged_modes_and_formula_escaping(tmp_path):
    p = source(tmp_path, 'name,email,notes,Extra\n=SUM(1),a@example.invalid,<tag>|note,=HYPERLINK()\n'
               '+Name,b@example.invalid,@note,-extra\n')
    before = p.read_bytes()
    result = call(tmp_path)
    outputs = {k: Path(v).read_bytes() for k, v in result["paths"].items()}
    for path in result["paths"].values():
        assert stat.S_IMODE(Path(path).stat().st_mode) == 0o600
        Path(path).chmod(0o644)
    assert call(tmp_path) == result
    assert {k: Path(v).read_bytes() for k, v in result["paths"].items()} == outputs
    assert p.read_bytes() == before and result["source_unchanged"] is True
    assert not (tmp_path / 'state').exists()
    rows = table(result["paths"]["clean"])
    assert rows[0]["name"] == "'=SUM(1)" and rows[0]["Extra"] == "'=HYPERLINK()"
    assert rows[1]["notes"] == "'@note" and rows[1]["Extra"] == "'-extra"
    # Force a change log value containing markup and a pipe.
    p.write_text('name,email,notes\nCasey,a@example.invalid, <tag>|note \n')
    result = call(tmp_path)
    md = Path(result["paths"]["changes_markdown"]).read_text()
    assert '&lt;tag&gt;\\|note' in md
    assert all(stat.S_IMODE(Path(v).stat().st_mode) == 0o600 for v in result["paths"].values())


@pytest.mark.parametrize("data", [
    {"path": "/etc/passwd"}, {"path": "outside.csv"}, {"path": "imports/../input.csv"},
    {"path": "imports"}, {"path": "imports/missing.csv"}, {"path": "imports/contacts"},
    {"path": "imports/contacts/\x00.csv"}, {"path": ""}, {"name": "../bad"}, {"name": ""},
    {"name": "A"}, {"name": "-bad"}, {"name": "a" * 42}, {"name": "valid\n"},
    {"default_country_code": "1234"}, {"default_country_code": "+1"}, {"default_country_code": 1},
    {"default_country_code": ""}, {"default_country_code": "1\n"}, {"action": "other"}, {"unknown": True}])
def test_bad_parameters_write_nothing(tmp_path, data):
    source(tmp_path, 'name\nCasey\n')
    before = snapshot(tmp_path)
    assert "error" in call(tmp_path, **data)
    assert snapshot(tmp_path) == before
    assert not (tmp_path / "exports").exists() and not (tmp_path / "state").exists()


@pytest.mark.parametrize("content", [b"\xff", b"name\n\x00\n", b'name,email\n"unterminated',
                                     b'name,email\nA,b,c\n', b"company\nDemo\n", b"", b"name,name\nA,B\n",
                                     b"name\n" + b"x" * (5 * 1024 * 1024)])
def test_bad_files_write_nothing(tmp_path, content):
    p = source(tmp_path, 'name\nCasey\n')
    p.write_bytes(content)
    before = snapshot(tmp_path)
    assert "error" in call(tmp_path)
    assert snapshot(tmp_path) == before and not (tmp_path / "exports").exists()


@pytest.mark.parametrize("target", ["source", "source_parent", "output", "output_parent"])
def test_symlinks_refused_before_any_output(tmp_path, target):
    original = source(tmp_path, 'name\nCasey\n')
    if target == "source":
        (original.parent / "link.csv").symlink_to(original)
        data = {"path": "imports/contacts/link.csv"}
    elif target == "source_parent":
        (tmp_path / "imports/link").symlink_to(original.parent, target_is_directory=True)
        data = {"path": "imports/link/input.csv"}
    else:
        exports = tmp_path / "exports"
        exports.mkdir()
        if target == "output":
            (exports / "contacts").mkdir()
            (exports / "contacts/demo-changes.md").symlink_to(original)
        else:
            (exports / "contacts").symlink_to(original.parent, target_is_directory=True)
        data = {}
    before = snapshot(tmp_path)
    assert "error" in call(tmp_path, **data)
    assert snapshot(tmp_path) == before and not (tmp_path / "state").exists()


def test_large_legal_cell_and_header_only(tmp_path):
    source(tmp_path, 'name,notes\nCasey,' + 'x' * 140000 + '\n')
    assert call(tmp_path)["counts"]["contacts_out"] == 1
    source(tmp_path, 'name\n')
    assert call(tmp_path)["counts"]["contacts_out"] == 0


def test_fixture_through_entry_exact_key(tmp_path):
    fixture = ROOT / "evals/lab/fixtures"
    p = source(tmp_path, (fixture / "contacts-300.csv").read_text())
    before = p.read_bytes()
    result = call(tmp_path, default_country_code="1")
    key = json.loads((fixture / "contacts-300.key.json").read_text())
    assert result["counts"] == key["counts"]
    assert [list(map(int, r["source_rows"].split("; "))) for r in table(result["paths"]["clean"])] == key["clusters"]
    assert result["possible_duplicates"] == key["possible_duplicates"]
    assert p.read_bytes() == before and not (tmp_path / "state").exists()
    from evals.lab.fixtures.make_contacts import build
    content, generated = build()
    assert content.encode() == (fixture / "contacts-300.csv").read_bytes() and generated == key


def test_schema_branch_and_registration():
    validator = Draft7Validator(entry.SCHEMA["parameters"])
    assert not list(validator.iter_errors({"operation": "contacts", "data": {
        "action": "dedupe", "path": "imports/contacts/a.csv", "name": "a"}}))
    for data in ({}, {"action": "other"}, {"action": "dedupe", "path": "x", "name": "A"}):
        assert list(validator.iter_errors({"operation": "contacts", "data": data}))
    assert list(validator.iter_errors({"operation": "contacts"}))
    assert not list(validator.iter_errors({"operation": "finance", "data": {"action": "cash_position"}}))
    for name, key, value in (("openclaw.plugin.json", "skills", "skills/documents-admin"),
                            ("skills/travel-action-pack-manifest/openclaw.plugin.json", "skills", "../documents-admin"),
                            ("support-control/component.json", "required_skills", "documents-admin")):
        assert value in json.loads((ROOT / name).read_text())[key]
    skill = (ROOT / "skills/documents-admin/SKILL.md").read_text()
    front = yaml.safe_load(skill.split("---")[1])
    assert front["name"] == front["metadata"]["openclaw"]["skillKey"] == "documents-admin"
    assert "Never write contacts back" in skill and "owner's yes" in skill and "profile" in skill
    assert "personal-assistant:documents-admin" in (ROOT / "skills/personal-assistant/SKILL.md").read_text()


def test_shared_switchboard_or_role_email_never_merges_different_people(tmp_path):
    source(tmp_path, 'name,email,phone\nAlice Smith,alice@example.invalid,+1 202 555 0000\n'
           'Bob Jones,bob@example.invalid,+1 202 555 0000\nCarol,info@example.invalid,\nDan,INFO@example.invalid,\n')
    result = call(tmp_path)
    assert [r["source_rows"] for r in table(result["paths"]["clean"])] == ["1", "2", "3", "4"]
    assert result["name_conflicts"] == [{"rows": [1, 2], "names": ["Alice Smith", "Bob Jones"]},
                                        {"rows": [3, 4], "names": ["Carol", "Dan"]}]
    assert result["counts"]["name_conflicts"] == 2 and result["counts"]["merged_clusters"] == 0
    assert [c["kind"] for c in changes(result)].count("name_conflict") == 2


def test_group_writable_owner_file_is_read(tmp_path):
    source(tmp_path, 'name,email\nCasey,c@example.invalid\n')
    path = next((tmp_path / "imports").rglob("*.csv"))
    path.chmod(0o664)
    path.parent.chmod(0o775)
    assert "error" not in call(tmp_path)


def test_importable_phone_cells_and_outlook_headers(tmp_path):
    source(tmp_path, 'First Name,Last Name,E-mail Address,Mobile Phone\nCasey,Demo,c@example.invalid,+1 202 555 0101\n')
    text = Path(call(tmp_path)["paths"]["clean"]).read_text()
    assert "+12025550101" in text and "'+1" not in text and "c@example.invalid" in text


def test_read_only_owner_file_is_read(tmp_path):
    source(tmp_path, 'name,email\nCasey,c@example.invalid\n')
    path = next((tmp_path / "imports").rglob("*.csv"))
    path.chmod(0o400)
    assert "error" not in call(tmp_path)


def test_malformed_emails_are_invalid_and_never_merge_keys(tmp_path):
    source(tmp_path, 'name,email\nAlice,@example.invalid\nAlice,@example.invalid\nBob,a@.\nDan,d@example.\nEve,e@example.invalid\n')
    result = call(tmp_path)
    assert [r["source_rows"] for r in table(result["paths"]["clean"])] == ["1", "2", "3", "4", "5"]
    assert result["counts"]["invalid_emails"] == 4 and result["counts"]["merged_clusters"] == 0


def test_same_name_set_is_one_review_item(tmp_path):
    source(tmp_path, "name,email\n" + "".join(f"Unknown,u{i}@example.invalid\n" for i in range(400)))
    result = call(tmp_path)
    assert result["counts"]["possible_duplicates"] == 1
    assert result["possible_duplicates"] == [{"rows": list(range(1, 401)), "name": "Unknown"}]


def test_phone_extension_kept_apart(tmp_path):
    source(tmp_path, 'name,phone\nCasey,+1 202 555 0101 ext. 23\nCasey,202-555-0101 x23\nDana,202-555-0101x24\n'
           'Eli,+1 202 555 0101\nFay,+1 202 555 0102;ext=7\n')
    result = call(tmp_path, default_country_code="1")
    rows = table(result["paths"]["clean"])
    assert [r["source_rows"] for r in rows] == ["1; 2", "3", "4", "5"]
    assert [r["phones"] for r in rows] == ["+12025550101 ext. 23", "+12025550101 ext. 24", "+12025550101", "+12025550102 ext. 7"]


def test_structured_names_survive_a_display_name(tmp_path):
    source(tmp_path, 'Name,Given Name,Family Name,E-mail 1 - Value\nMom,Jane,Smith,jane@example.invalid\n'
           ',Lee,,lee@example.invalid\nJo,Joanne,Park,jo@example.invalid\nJo,Jo,Park,JO@example.invalid\n')
    result = call(tmp_path)
    rows = table(result["paths"]["clean"])
    assert [(r["name"], r["given_name"], r["family_name"], r["source_rows"]) for r in rows] == [
        ("Mom", "Jane", "Smith", "1"), ("Lee", "Lee", "", "2"), ("Jo", "Joanne", "Park", "3; 4")]
    assert any((c["kind"], c["field"], c["kept"], c["other"], c["row"]) == ("alternate", "given_name", "Joanne", "Jo", "4")
               for c in changes(result))


def test_same_display_name_with_different_structured_names_is_a_conflict(tmp_path):
    source(tmp_path, 'Name,Given Name,Family Name,Phone 1 - Value\nDoctor,Jane,Smith,+12025550101\n'
           'Doctor,John,Jones,+12025550101\nMom,Ana,Lee,+12025550102\n,Ana,Lee,+12025550102\n')
    result = call(tmp_path)
    assert [r["source_rows"] for r in table(result["paths"]["clean"])] == ["1", "2", "3; 4"]
    assert result["counts"]["name_conflicts"] == 1 and result["counts"]["merged_clusters"] == 1


# 0.20 wave, s32 r002: PA sent an empty "fields" object, then nested every parameter under fields, and the old
# error ("invalid contacts action, name or country code") said nothing about either.
@pytest.mark.parametrize("data, expected, absent", [
    ({"fields": {}}, "not accepted: fields; send them at the top level of data", ()),
    ({"path": None, "name": None, "fields": {"path": "imports/contacts/input.csv", "name": "demo"}},
     "not accepted: fields", ("imports/contacts", "demo")),
    ({"secret_token": "abc123"}, "plus 1 other key not accepted", ("secret_token", "abc123")),
    ({"action": "merge"}, "action must be dedupe", ("merge",)),
    ({"name": "Bad Name"}, "the key names are right, so check the values: name is 1 to 41", ("Bad Name",)),
])
def test_errors_name_the_shape_never_values(tmp_path, data, expected, absent):
    source(tmp_path, 'name\nCasey\n')
    payload = {"action": "dedupe", "path": "imports/contacts/input.csv", "name": "demo", **data}
    payload = {k: v for k, v in payload.items() if v is not None}
    error = entry.dispatch(tmp_path, {"operation": "contacts", "data": payload})["error"]
    assert expected in error
    assert all(a not in error for a in absent)


def test_missing_keys_are_listed(tmp_path):
    error = entry.dispatch(tmp_path, {"operation": "contacts", "data": {"action": "dedupe"}})["error"]
    assert "missing: path, name" in error and "fields" not in error


def test_everything_nested_under_fields_is_named(tmp_path):
    nested = {"fields": {"action": "dedupe", "path": "imports/contacts/input.csv", "name": "demo"}}
    error = entry.dispatch(tmp_path, {"operation": "contacts", "data": nested})["error"]
    assert "missing: action, path, name; not accepted: fields; send them at the top level of data" in error
    assert "imports/contacts" not in error and "demo" not in error


def test_country_key_points_to_default_country_code(tmp_path):
    error = call(tmp_path, country_code="1")["error"]
    assert "not accepted: country_code; the country code key is default_country_code" in error


def test_bad_value_after_schema_names_the_rules(tmp_path):
    source(tmp_path, 'name\nCasey\n')
    error = call(tmp_path, name="valid\n")["error"]
    assert "name is 1 to 41 lowercase letters" in error and "valid\n" not in error


def test_non_object_data_gets_a_plain_hint():
    assert contacts._shape_hint(["x"]) == "data must be an object with action, path and name"
