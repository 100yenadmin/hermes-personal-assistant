"""Synthetic owner-memory dispatch and new-session regression coverage."""
import sys
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate, ValidationError

from personal_assistant.entry import dispatch, SCHEMA
from personal_assistant.onboarding_hook import make_pre_llm_call
from personal_assistant.state import Ledger, legacy
from personal_assistant.profile import remember


def call(root, action="remember", **data):
    args = {"operation": "profile", "data": {"action": action, **data}}
    validate(args, SCHEMA["parameters"])
    return dispatch(root, args)


def pref(root, text="Prefer short replies", **data):
    return call(root, kind="preference", text=text, **data)


def test_remember_update_correction_confirm_forget(tmp_path):
    old = pref(tmp_path, category="communication")
    unrelated = pref(tmp_path, "Use bullet points", category="communication")
    updated = pref(tmp_path, evidence="Owner said this in chat")
    assert updated["action_id"] == old["action_id"]
    corrected = pref(tmp_path, "Prefer detailed replies", source="corrected", category="communication", supersedes=old["action_id"])
    assert corrected["fields"]["supersedes"] == old["action_id"]
    assert Ledger(tmp_path).get("action", old["action_id"])["fields"]["state"] == "retired"
    assert Ledger(tmp_path).get("action", unrelated["action_id"])["fields"]["state"] == "active"
    inferred = pref(tmp_path, "No meetings before ten", source="inferred")
    assert inferred["fields"]["state"] == "proposed"
    confirmed = call(tmp_path, "confirm", identity=inferred["action_id"])
    assert confirmed["fields"]["state"] == "active" and confirmed["fields"]["owner_confirmed_at"]
    assert "confirmed_at" not in confirmed["fields"]
    assert call(tmp_path, "forget", identity=confirmed["action_id"])["fields"]["state"] == "retired"
    with pytest.raises(ValueError, match="lifecycle-owned"):
        Ledger(tmp_path).put("action", "pref:guard", {"confirmed_at": "2026-10-21T00:00:00+00:00"}, action_type="preference")
    with pytest.raises(ValueError, match="unsupported profile fields"):
        dispatch(tmp_path, {"operation": "profile", "data": {"action": "remember", "kind": "preference", "text": "Brief", "confirmed_at": "x"}})


@pytest.mark.parametrize("data", [
    {"text": "Card 4111 1111 1111 1111"}, {"text": "password: synthetic-only"},
    {"text": "account number: 123456"}, {"text": "passport number: A1234567"},
    {"text": "api key: synthetic-only"},
    {"text": "Safe", "password": "synthetic-only"}, {"text": "Safe", "raw_message": "synthetic body"},
])
def test_private_values_rejected_without_write(tmp_path, data):
    with pytest.raises(ValueError, match="prohibit"):
        dispatch(tmp_path, {"operation": "profile", "data": {"action": "remember", "kind": "preference", **data}})
    assert Ledger(tmp_path).list("action") == []


def test_people_filing_and_action_readers(tmp_path, monkeypatch, capsys):
    p = pref(tmp_path)
    person = call(tmp_path, kind="person", name="Synthetic Alex", relationship="colleague", channel="email", rules=["Use a formal greeting"])
    assert call(tmp_path, "list", name="alex")[0]["rules"] == ["Use a formal greeting"]
    assert len(call(tmp_path, "pending_files")) == 2
    call(tmp_path, "mark_filed", identities=[p["action_id"], person["action_id"]])
    assert call(tmp_path, "pending_files") == []
    assert len(call(tmp_path, "list", state="filed")) == 2
    ledger = Ledger(tmp_path)
    ledger.put("action", "real-task", {}, action_type="commitment")
    assert [r["action_id"] for r in dispatch(tmp_path, {"operation": "next_action"})["candidates"]] == ["real-task"]
    assert [r["action_id"] for r in dispatch(tmp_path, {"operation": "status"})["actions"]] == ["real-task"]
    assert dispatch(tmp_path, {"operation": "context", "data": {"kind": "action"}})["total"] == 1
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    legacy.summary(SimpleNamespace(json=True))
    assert [r["action_id"] for r in json.loads(capsys.readouterr().out)["actions"]] == ["real-task"]
    call(tmp_path, kind="person", name="Synthetic Alex", rules=["Use a short greeting"])
    assert call(tmp_path, "pending_files")[0]["rules"] == ["Use a short greeting"]


def test_sop_versions_and_default_trust(tmp_path):
    data = dict(kind="sop", title="Weekly prep", trigger="Friday", steps=["Read calendar"], tools=["calendar"], done_when="Draft ready", escalation="Ask owner")
    first = call(tmp_path, **data)
    assert first["fields"]["state"] == "draft" and first["fields"]["version"] == 1
    assert call(tmp_path, **data)["fields"]["version"] == 1
    second = call(tmp_path, **{**data, "steps": ["Read calendar", "Draft agenda"]}, change="Add agenda")
    assert second["fields"]["version"] == 2 and len(second["fields"]["changelog"]) == 2
    assert second["fields"]["changelog"][-1]["change"] == "Add agenda"
    assert call(tmp_path, **{**data, "steps": second["fields"]["steps"], "state": "owned"})["fields"]["state"] == "owned"
    assert call(tmp_path, kind="trust", task_type="meeting prep")["fields"]["level"] == "shadow"


@pytest.fixture
def human_hook(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "agent.session_source", None)
    monkeypatch.setitem(sys.modules, "gateway.session_context", None)
    for key in ("HERMES_SESSION_SOURCE", "HERMES_SINGLE_QUERY_SESSION", "HERMES_KANBAN_TASK"):
        monkeypatch.delenv(key, raising=False)
    return make_pre_llm_call(tmp_path, lambda k, d: False)


@pytest.mark.parametrize("override", [{"platform": "cron"}, {"platform": "subagent"}, {"parent_session_id": "p"},
    {"user_message": "⟦pulse wake"}, {"user_message": "[stamp] ⟦pulse wake"}, {"is_first_turn": False},
    {"conversation_history": [{"display_kind": "internal_notification"}]}])
def test_hook_omits_nonhuman_or_later_turns(tmp_path, human_hook, override):
    pref(tmp_path)
    assert human_hook(**{**dict(user_message="Hello", is_first_turn=True, session_id="next"), **override}) is None


def test_new_session_note_bounds_order_and_filing(tmp_path, human_hook):
    filed = pref(tmp_path, "Filed rule")
    call(tmp_path, "mark_filed", identities=[filed["action_id"]])
    for n in range(12):
        pref(tmp_path, f"Rule {n}", slug=f"rule-{n}")
    corrected = pref(tmp_path, "Corrected newest", source="corrected")
    call(tmp_path, kind="person", name="Sensitive Alex", sensitive=True, rules=["Private synthetic rule"])
    note = human_hook(user_message="Hello", is_first_turn=True, session_id="new")["context"]
    assert note.startswith("Owner preferences and people from PA (not yet in your files)")
    assert note.splitlines()[2].startswith("- " + corrected["action_id"])
    assert note.count("\n- ") == 10 and len(note) <= 1200
    assert "Filed rule" not in note and "Private synthetic rule" not in note
    pref(tmp_path, "Long " + "x" * 290, source="corrected")
    assert len(human_hook(user_message="Hello", is_first_turn=True)["context"]) <= 1200
    assert len(call(tmp_path, "list")) <= 50


def test_schema_limits_and_review_paths(tmp_path):
    with pytest.raises(ValidationError):
        call(tmp_path, kind="person", name="Alex", rules=["x"] * 6)
    with pytest.raises(ValueError, match="invalid profile field"):
        dispatch(tmp_path, {"operation": "profile", "data": {"action": "remember", "kind": "preference", "text": "x" * 301}})
    root = Path(__file__).resolve().parents[1] / "skills"
    for path in ("cos-weekly/SKILL.md", "daily-ops/SKILL.md"):
        text = (root / path).read_text()
        assert "Is this saving you time? Roughly how much?" in text and "30 days" in text
    assert "mark_filed" in (root / "pa-setup/references/where-answers-go.md").read_text()


def test_list_limit_and_category_filter(tmp_path):
    ledger = Ledger(tmp_path)
    for n in range(55):
        ledger.put("action", f"pref:synthetic-{n}", {"text": f"Rule {n}", "category": "work", "state": "active"}, action_type="preference")
    assert len(call(tmp_path, "list", kind="preference", category="work", state="active")) == 50
    assert call(tmp_path, "list", category="food") == []


@pytest.mark.parametrize("data", [
    dict(kind="person", name="Alex", rules=["password: synthetic-only"]),
    dict(kind="sop", title="Weekly prep", steps=["token: synthetic-only"]),
    dict(kind="trust", task_type="prep", evidence="account number: 123456"),
])
def test_nested_privacy_for_all_record_types(tmp_path, data):
    with pytest.raises(ValueError, match="prohibit"):
        remember(Ledger(tmp_path), data)
    assert Ledger(tmp_path).list("action") == []


def test_identity_scope_and_supersedes_cycle(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.put("action", "pref:reserved", {}, action_type="commitment")
    with pytest.raises(ValueError, match="another action type"):
        pref(tmp_path, "Reserved")
    a = pref(tmp_path, "Short replies")
    b = pref(tmp_path, "Long replies", source="corrected", supersedes=a["action_id"])
    with pytest.raises(ValueError, match="cannot loop"):
        pref(tmp_path, "Short replies", source="corrected", supersedes=b["action_id"])
    assert ledger.get("action", a["action_id"])["fields"]["state"] == "retired"
    assert ledger.get("action", b["action_id"])["fields"]["state"] == "active"
