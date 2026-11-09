from pathlib import Path
from types import SimpleNamespace

import pytest

from personal_assistant import capabilities


ROOT = Path(__file__).resolve().parents[1]
ROLE_NOTE = (
    "PA follow-through role: load personal-assistant:follow-through; read next_action with loops_only; "
    "remind the owner, prepare and hold due nudges, list approvals awaiting the owner's yes, "
    "escalate on the ladder; arm at most 3 one-shot wakes for upcoming chase dates or approval "
    "timeouts; never send, book, pay or cancel without the owner's yes."
)


def discover(entries, cached_check=None):
    return capabilities.discover(entries, cached_check, which=lambda name: None,
                                 secret_present=lambda name: False)


def heartbeat(entries, cached_check=None):
    return next(row for row in discover(entries, cached_check)["capabilities"]
                if row["id"] == "heartbeat")


@pytest.mark.parametrize("roles", [True, False])
def test_pulse_schema_reports_role_support(roles):
    properties = {"role": {"type": "boolean"}} if roles else {"action": {"type": "string"}}
    entry = SimpleNamespace(name="pulse", schema={"parameters": {"properties": properties}})
    row = heartbeat([entry])
    assert row["status"] == "available"
    assert row["tools"] == ["pulse"]
    assert row["reuse"] == "HeartBeat 2.0 wakes and roles"
    assert row["roles"] is roles
    assert row["authentication"] == "unverified"


def test_no_pulse_is_unavailable():
    row = heartbeat([SimpleNamespace(name="cronjob_manage")])
    assert row["status"] == "unavailable"
    assert row["tools"] == []
    assert row["roles"] is False


@pytest.mark.parametrize("schema", [None, [], "odd", {}, {"parameters": None},
    {"parameters": []}, {"parameters": "odd"}, {"parameters": {}},
    {"parameters": {"properties": None}}, {"parameters": {"properties": ["role"]}},
    {"parameters": {"properties": "role"}}])
def test_malformed_schema_has_no_roles(schema):
    row = heartbeat([SimpleNamespace(name="pulse", schema=schema)])
    assert row["status"] == "available"
    assert row["roles"] is False


def test_missing_schema_has_no_roles():
    assert heartbeat([SimpleNamespace(name="pulse")])["roles"] is False


@pytest.mark.parametrize("cached, expected", [(True, "available"), (False, "needs-setup"),
                                             (None, "unverified")])
def test_heartbeat_preserves_cached_availability_semantics(cached, expected):
    entry = SimpleNamespace(name="pulse", check_fn=lambda: None,
                            schema={"parameters": {"properties": {"role": {}}}})
    row = heartbeat([entry], lambda check: cached)
    assert row["status"] == expected
    assert row["roles"] is True


def test_other_rows_unchanged_with_same_registry(monkeypatch):
    monkeypatch.setenv("GOG_PATH", "")
    entries = [SimpleNamespace(name=name) for name in
               ("calendar_list", "gmail_search", "browser_open", "send_message",
                "kanban_show", "cronjob_manage", "secure_access", "pulse")]
    current = discover(entries)
    # Before this change the spec table had exactly these rows, without heartbeat.
    monkeypatch.setattr(capabilities, "_SPECS", tuple(
        spec for spec in capabilities._SPECS if spec[0] != "heartbeat"))
    before = discover(entries)
    assert [row for row in current["capabilities"] if row["id"] != "heartbeat"] == before["capabilities"]


def test_setup_role_contract_and_size():
    text = (ROOT / "skills/pa-setup/SKILL.md").read_text()
    section = text.split("## PA on its own schedule\n", 1)[1].split("\n## ", 1)[0]
    assert len(("## PA on its own schedule\n" + section).splitlines()) <= 14
    for required in (
        "hermes plugins install electricsheephq/heartbeat2 --enable", ROLE_NOTE,
        "budget", '"turns_per_day":2', "/pulse ok", "proposed, not set",
        "scheduled delivery is still unreliable on some Hermes versions (#21)",
        "After successful core apply and fresh-session check, or when the owner asks",
        "owner's explicit yes", "09:00 local", "Every send still needs its own yes",
        "Never edit HB2 config",
    ):
        assert required in section


def test_heartbeat_row_is_documented():
    text = (ROOT / "skills/personal-assistant/SKILL.md").read_text()
    assert "The `heartbeat` row" in text and "`roles`" in text
