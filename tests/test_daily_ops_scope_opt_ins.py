"""Owner opt-in write scopes for drafts and calendar writes; provider-free."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_assistant.daily_ops import config, doctor

ROOT = Path(__file__).resolve().parents[1]
G = "https://www.googleapis.com/auth/"
READ = [G + "gmail.readonly", G + "calendar.readonly", "openid"]
WORK, PERSONAL = "owner@example.com", "personal@example.net"


def cfg(*, drafts=None, write=None, personal=None):
    data = {
        "tenant": {"profile_id": "example-profile", "owner_email": WORK},
        "delivery": {"target": "example-topic", "verified": True},
        "timezone": "Asia/Bangkok",
        "accounts": {"work": WORK, "personal": personal},
        "calendar": {"provider": "gog", "read_scope": {"accepted": True, "calendar_ids": ["primary", "team"]}},
    }
    if drafts is not None:
        data["inbox"] = {"drafts": {"accepted": drafts}}
    if write is not None:
        data["calendar"]["write_scope"] = write
    return data


def scopes(monkeypatch, *entries):
    monkeypatch.setattr(doctor, "gog_binary", lambda: "/bin/gog")
    monkeypatch.setattr(doctor, "auth_check", lambda: {"accounts": [
        {"email": email, "valid": True, "scopes": list(granted)} for email, granted in entries]})


WRITE = {"accepted": True, "calendar_ids": ["primary"], "invites": False}


@pytest.mark.parametrize("granted,settings,ok,needle", [
    (READ, {}, True, "required least-privilege scopes present"),
    (READ, {"drafts": True, "write": WRITE}, True, "required least-privilege scopes present"),
    (READ + [G + "gmail.compose"], {}, False, "unsupported extra scopes"),
    (READ + [G + "gmail.compose"], {"drafts": False}, False, "unsupported extra scopes"),
    (READ + [G + "gmail.compose"], {"drafts": True}, True, "owner opt-in write scopes: account-1 gmail.compose"),
    (READ + [G + "calendar.events"], {}, False, "unsupported extra scopes"),
    (READ + [G + "calendar.events"], {"write": dict(WRITE, accepted=False)}, False, "unsupported extra scopes"),
    (READ + [G + "calendar.events"], {"write": WRITE}, True, "account-1 calendar.events"),
    ([G + "gmail.compose", G + "calendar.events"], {"drafts": True, "write": WRITE}, False, "missing required scopes (calendar, gmail)"),
    (READ + [G + "gmail.modify"], {"drafts": True, "write": WRITE}, False, "broad scopes present"),
    (READ + ["https://mail.google.com/"], {"drafts": True}, False, "broad scopes present"),
    (READ + [G + "calendar"], {"write": WRITE}, False, "broad scopes present"),
    (READ + [G + "drive"], {"drafts": True, "write": WRITE}, False, "broad scopes present"),
    (READ + [G + "gmail.send"], {"drafts": True}, False, "unsupported extra scopes"),
])
def test_doctor_scope_matrix(monkeypatch, granted, settings, ok, needle):
    scopes(monkeypatch, (WORK, granted))
    result, message = doctor.check_scopes(cfg(**settings))
    assert result is ok and needle in message


def test_calendar_events_is_accepted_only_on_the_calendar_account(monkeypatch):
    scopes(monkeypatch, (WORK, READ), (PERSONAL, [G + "gmail.readonly", G + "calendar.events"]))
    ok, message = doctor.check_scopes(cfg(write=WRITE, personal=PERSONAL))
    assert not ok and "account-2: unsupported extra scopes" in message
    scopes(monkeypatch, (WORK, READ), (PERSONAL, [G + "gmail.readonly", G + "gmail.compose"]))
    ok, message = doctor.check_scopes(cfg(drafts=True, personal=PERSONAL))
    assert ok and message.endswith("owner opt-in write scopes: account-2 gmail.compose")


def test_config_validates_write_scope_and_drafts_opt_in():
    assert config.validate_config(cfg(drafts=True, write=WRITE)) == []
    assert config.validate_config(cfg(write={"accepted": False})) == []
    cases = {
        "calendar.write_scope.calendar_ids must also be in": dict(WRITE, calendar_ids=["elsewhere"]),
        "calendar.write_scope.calendar_ids must be a non-empty list": dict(WRITE, calendar_ids=[]),
        "calendar.write_scope.invites must be the JSON boolean": {"accepted": True, "calendar_ids": ["primary"]},
        "calendar.write_scope.accepted must be a JSON boolean": dict(WRITE, accepted="true"),
        "calendar.write_scope must be an object": ["primary"],
    }
    for needle, write in cases.items():
        assert any(needle in error for error in config.validate_config(cfg(write=write))), needle
    assert config.validate_config(cfg(write=dict(WRITE, calendar_ids=["TEAM"]))) == []
    assert any("inbox.drafts.accepted must be a JSON boolean" in error
               for error in config.validate_config(cfg(drafts="yes")))
    bad = cfg(); bad["inbox"] = ["drafts"]
    assert any("inbox must be an object" in error for error in config.validate_config(bad))


def test_example_config_ships_both_opt_ins_off():
    example = json.loads((ROOT / "personal_assistant/daily_ops/config.example.json").read_text())
    assert example["inbox"] == {"drafts": {"accepted": False}}
    assert example["calendar"]["write_scope"] == {"accepted": False, "calendar_ids": [], "invites": False}


def test_daily_ops_skill_gives_exact_opt_in_auth_commands():
    text = " ".join((ROOT / "skills/daily-ops/SKILL.md").read_text().split())
    assert "`gog auth add <work email> --services gmail,calendar --readonly`" in text
    assert ("`gog auth add <work email> --services gmail,calendar --readonly --extra-scopes "
            "https://www.googleapis.com/auth/gmail.compose,https://www.googleapis.com/auth/calendar.events --force-consent`") in text
    assert ("`gog auth add <personal email> --services gmail --readonly --extra-scopes "
            "https://www.googleapis.com/auth/gmail.compose --force-consent`") in text
    assert "never automatic" in text and "always rejects `gmail.modify`, full mail" in text
