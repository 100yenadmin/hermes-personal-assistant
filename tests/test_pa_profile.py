"""Synthetic owner-memory dispatch and new-session regression coverage."""
import sys
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate, ValidationError

from personal_assistant.entry import dispatch, SCHEMA
from personal_assistant.onboarding_hook import OWNER_MEMORY, make_pre_llm_call
from personal_assistant.state import Ledger, legacy
from personal_assistant.profile import remember, session_note


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


@pytest.mark.parametrize("initial,source,change,expected", [
    ("confirmed", "inferred", {}, "active"),
    ("confirmed", "inferred", {"text": "Prefer detailed replies"}, "refused"),
    ("filed", "said", {}, "filed"),
    ("filed", "said", {"text": "Prefer detailed replies"}, "active"),
    ("filed", "said", {"category": "voice"}, "active"),
    ("filed", "inferred", {}, "filed"),
    ("filed", "inferred", {"text": "Prefer detailed replies"}, "refused"),
    ("confirmed", "said", {"text": "Prefer detailed replies"}, "active"),
    ("retired", "said", {}, "active"),
    ("retired", "inferred", {}, "proposed"),
    ("proposed", "inferred", {"text": "Prefer detailed replies"}, "proposed"),
    ("proposed", "inferred", {}, "proposed"),
    ("proposed", "said", {}, "active"),
    ("proposed", "corrected", {}, "active"),
    ("filed-unconfirmed", "inferred", {"text": "Prefer detailed replies"}, "refused"),
])
def test_preference_remember_preserves_lifecycle(tmp_path, initial, source, change, expected):
    original = pref(tmp_path, slug="replies", source="inferred" if initial != "filed-unconfirmed" else "said")
    if initial not in {"proposed", "filed-unconfirmed"}:
        call(tmp_path, "confirm", identity=original["action_id"])
    if initial.startswith("filed"):
        call(tmp_path, "mark_filed", identities=[original["action_id"]])
    elif initial == "retired":
        call(tmp_path, "forget", identity=original["action_id"])
    before = Ledger(tmp_path).get("action", original["action_id"])["fields"]
    if expected == "refused":  # An inference never rewrites what the owner stated or confirmed.
        with pytest.raises(ValueError, match="ask the owner"):
            pref(tmp_path, slug="replies", source=source, **change)
        assert Ledger(tmp_path).get("action", original["action_id"])["fields"] == before
        return
    updated = pref(tmp_path, slug="replies", source=source, **change)["fields"]
    assert updated["state"] == expected
    assert updated["owner_confirmed_at"] == before["owner_confirmed_at"]
    assert bool(call(tmp_path, "pending_files")) == (expected == "active")


@pytest.mark.parametrize("retire", ["forget", "supersede", "person"])
def test_filed_text_changed_before_review_is_still_removed(tmp_path, retire):
    if retire == "person":
        data = dict(kind="person", slug="alex", name="Synthetic Alex")
        identity = call(tmp_path, **data)["action_id"]
        call(tmp_path, "mark_filed", identities=[identity])
        assert call(tmp_path, **data, channel="email")["fields"]["state"] == "active"  # Changed: the file needs the new text.
        call(tmp_path, **data, channel="email", state="retired")
    else:
        identity = pref(tmp_path, slug="replies")["action_id"]
        call(tmp_path, "mark_filed", identities=[identity])
        assert pref(tmp_path, "Prefer detailed replies", slug="replies")["fields"]["state"] == "active"
        if retire == "forget":
            call(tmp_path, "forget", identity=identity)
        else:
            pref(tmp_path, "Prefer bullet replies", source="corrected", supersedes=identity)
    row = Ledger(tmp_path).get("action", identity)["fields"]
    assert row["state"] == "retired" and row["remove_from_files"] is True
    filed = "Synthetic Alex" if retire == "person" else "Prefer short replies"  # What the files hold, not the later text.
    pending = {r["identity"]: r for r in call(tmp_path, "pending_files")}
    assert pending[identity]["filed_text"] == filed
    assert "FORGOTTEN, do not use (still in files until the next review): " + filed in session_note(Ledger(tmp_path))
    call(tmp_path, "mark_filed", identities=[identity])
    row = Ledger(tmp_path).get("action", identity)["fields"]
    assert "remove_from_files" not in row and row["filed_text"] is None
    assert identity not in [r["identity"] for r in call(tmp_path, "pending_files")]
    call(tmp_path, "forget", identity=identity)  # Already out of the files: nothing is listed again.
    assert "remove_from_files" not in Ledger(tmp_path).get("action", identity)["fields"]


def test_filed_text_is_lifecycle_owned(tmp_path):
    with pytest.raises(ValueError, match="unsupported profile fields"):
        pref(tmp_path, filed_text="Prefer short replies")
    assert Ledger(tmp_path).list("action") == []


def test_changed_filed_record_carries_the_text_to_replace(tmp_path):
    identity = call(tmp_path, kind="person", slug="alex", name="Synthetic Alex", channel="email", rules=["Formal"])["action_id"]
    call(tmp_path, "mark_filed", identities=[identity])
    assert Ledger(tmp_path).get("action", identity)["fields"]["filed_text"] == "Synthetic Alex: email; Formal"
    call(tmp_path, kind="person", slug="alex", name="Synthetic Alex", channel="phone", rules=["Formal"])
    row = {r["identity"]: r for r in call(tmp_path, "pending_files")}[identity]
    assert row["state"] == "active" and row["channel"] == "phone" and row["filed_text"] == "Synthetic Alex: email; Formal"
    call(tmp_path, "mark_filed", identities=[identity])
    assert Ledger(tmp_path).get("action", identity)["fields"]["filed_text"] == "Synthetic Alex: phone; Formal"
    secret = call(tmp_path, kind="person", slug="kim", name="Synthetic Kim", rules=["Private matter"], sensitive=True)["action_id"]
    call(tmp_path, "mark_filed", identities=[secret])
    assert Ledger(tmp_path).get("action", secret)["fields"]["filed_text"] == "Synthetic Kim"  # Referenced, never quoted.


def test_forgotten_records_leave_lookups_and_since_is_lifecycle_owned(tmp_path):
    alex = call(tmp_path, kind="person", name="Synthetic Alex", rules=["Never call before 10"])["action_id"]
    call(tmp_path, "forget", identity=alex)
    assert call(tmp_path, "list", name="Alex") == []  # A forgotten rule no longer guides drafts.
    assert [r["identity"] for r in call(tmp_path, "list", name="Alex", state="retired")] == [alex]
    trust = call(tmp_path, kind="trust", task_type="inbox triage")
    with pytest.raises(ValueError, match="unsupported profile fields"):
        call(tmp_path, kind="trust", task_type="inbox triage", since="2020-01-01T00:00:00+00:00")
    assert call(tmp_path, kind="trust", task_type="inbox triage", level="own")["fields"]["since"] == trust["fields"]["since"]


@pytest.mark.parametrize("kind,data,active", [
    ("trust", {"task_type": "inbox triage"}, "active"),
    ("sop", {"title": "Weekly invoices", "trigger": "Friday", "steps": ["Collect"], "tools": ["mail"],
             "done_when": "Sent", "escalation": "Ask the owner"}, "draft"),
])
def test_remembering_a_forgotten_record_reactivates_it(tmp_path, kind, data, active):
    identity = call(tmp_path, kind=kind, **data)["action_id"]
    call(tmp_path, "forget", identity=identity)
    assert call(tmp_path, kind=kind, **data)["fields"]["state"] == active
    call(tmp_path, "forget", identity=identity)
    assert call(tmp_path, kind=kind, **data, state="retired")["fields"]["state"] == "retired"  # An explicit state wins.


@pytest.mark.parametrize("change,expected", [
    ({}, "filed"), ({"source": "inferred"}, "filed"),
    ({"name": "Synthetic Sam"}, "active"), ({"relationship": "colleague"}, "active"),
    ({"channel": "email"}, "active"), ({"rules": ["Use a formal greeting"]}, "active"),
    ({"sensitive": True}, "active"), ({"state": "active"}, "active"),
])
def test_person_remember_preserves_filing(tmp_path, change, expected):
    data = dict(kind="person", slug="alex", name="Synthetic Alex")
    person = call(tmp_path, **data)
    call(tmp_path, "mark_filed", identities=[person["action_id"]])
    assert call(tmp_path, **{**data, **change})["fields"]["state"] == expected
    assert bool(call(tmp_path, "pending_files")) == (expected == "active")


def test_retired_person_is_reactivated_unless_state_is_explicit(tmp_path):
    data = dict(kind="person", name="Synthetic Alex")
    person = call(tmp_path, **data)
    call(tmp_path, "forget", identity=person["action_id"])
    assert call(tmp_path, **data)["fields"]["state"] == "active"
    assert call(tmp_path, **data, state="retired")["fields"]["state"] == "retired"


@pytest.mark.parametrize("channel", ["+44 20 7946 0958", "+81 90-1234-5678"])
def test_person_phone_channel_is_accepted(tmp_path, channel):
    person = call(tmp_path, kind="person", name="Synthetic Alex", channel=channel)
    assert person["fields"]["channel"] == channel


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
    with ledger.connect() as conn:  # A legacy row without a type stays visible in the summary.
        conn.execute("insert into actions values(?,?,?,?,?,?,?,?)", ("legacy-null", None, None, "", "pending", "{}",
                     "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    legacy.summary(SimpleNamespace(json=True))
    assert [r["action_id"] for r in json.loads(capsys.readouterr().out)["actions"]] == ["real-task", "legacy-null"]
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


def test_failing_session_note_keeps_setup_context(tmp_path, human_hook, monkeypatch):
    from personal_assistant import profile, setup
    pref(tmp_path)
    setup.request(Ledger(tmp_path))
    monkeypatch.setattr(profile, "session_note", lambda ledger: 1 / 0)
    reply = human_hook(user_message="Hello", is_first_turn=True, platform="telegram", sender_id="u1", session_id="s1")
    assert "Guided setup is active" in reply["context"]


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


def test_session_note_never_cuts_a_rule_and_names_replaced_filed_text(tmp_path):
    filed = pref(tmp_path, "Prefer short replies", slug="replies")["action_id"]
    call(tmp_path, "mark_filed", identities=[filed])
    pref(tmp_path, "Prefer detailed replies", slug="replies")  # Same slug: the files still hold the old text.
    assert "Prefer detailed replies (replaces the filed text, do not use: Prefer short replies)" in session_note(Ledger(tmp_path))
    long_rules = [pref(tmp_path, f"Rule {n} " + "x" * 280, slug=f"long-{n}")["fields"]["text"] for n in range(6)]
    note = session_note(Ledger(tmp_path))
    lines = [line for line in note.splitlines() if line.startswith("- ")]
    assert len(note) <= 1200 and note.endswith("(More owner memory is waiting: call profile pending_files.)")
    assert all(any(line.endswith(": " + text) for text in long_rules) or "replaces the filed text" in line for line in lines)


def test_session_note_keeps_sensitive_filed_details_out_and_fits_shorter_rows(tmp_path):
    alex = call(tmp_path, kind="person", slug="alex", name="Synthetic Alex", rules=["Private synthetic rule"])["action_id"]
    call(tmp_path, "mark_filed", identities=[alex])
    call(tmp_path, kind="person", slug="alex", name="Synthetic Alex", rules=["Private synthetic rule"], sensitive=True)
    note = session_note(Ledger(tmp_path))
    assert "Synthetic Alex [sensitive: consult profile by identity] (replaces its filed entry" in note
    assert "Private synthetic rule" not in note
    pref(tmp_path, "Tiny rule", slug="tiny")
    for n in range(4):
        pref(tmp_path, f"Long {n} " + "x" * 280, slug=f"long-{n}")
    note = session_note(Ledger(tmp_path))
    assert len(note) <= 1200 and note.count("Long ") < 4 and note.endswith("(More owner memory is waiting: call profile pending_files.)")
    assert "Tiny rule" in note  # The oldest long row does not fit, but the shorter row after it does.


@pytest.mark.parametrize("message,routed", [
    ("From now on, keep your replies to three lines or fewer.", True), ("Correction: five lines is right.", True),
    ("Always copy my partner on travel plans.", True), ("Please don't call me before 10.", True),
    ("Keep your replies to three lines.", True), ("Use a formal greeting with Alex.", True),
    ("Never mind, thanks.", False), ("What is on my calendar tomorrow?", False)])
def test_stated_preferences_are_routed_to_owner_memory(tmp_path, human_hook, message, routed):
    result = human_hook(user_message=message, is_first_turn=False, session_id="s")
    assert bool(result and OWNER_MEMORY in result["context"]) == routed


def test_setup_answers_are_not_routed_to_owner_memory(tmp_path, human_hook):
    from personal_assistant import setup
    setup.request(Ledger(tmp_path), "profile")
    result = human_hook(user_message="Always copy my partner on travel plans.", is_first_turn=False, session_id="s")
    assert result and "Guided setup is active" in result["context"] and OWNER_MEMORY not in result["context"]


def test_owner_memory_is_routed_in_a_chat_other_than_active_setup(tmp_path, human_hook):
    from personal_assistant import setup
    setup.request(Ledger(tmp_path), "profile", active_chat="telegram:setup-chat:")
    result = human_hook(user_message="From now on, keep replies short.", is_first_turn=False, session_id="s")
    assert result and OWNER_MEMORY in result["context"]


def test_schema_limits_and_review_paths(tmp_path):
    with pytest.raises(ValidationError):
        call(tmp_path, kind="person", name="Alex", rules=["x"] * 6)
    with pytest.raises(ValueError, match="invalid profile field"):
        dispatch(tmp_path, {"operation": "profile", "data": {"action": "remember", "kind": "preference", "text": "x" * 301}})
    root = Path(__file__).resolve().parents[1] / "skills"
    for path in ("cos-weekly/SKILL.md", "daily-ops/SKILL.md"):
        text = (root / path).read_text()
        assert "30 days" in text and "day-30 time check" in text and "`personal-assistant`" in text
        assert "profile remember kind=preference source=said category=work" not in text
    text = (root / "personal-assistant/SKILL.md").read_text()
    assert "28 or more days ago" in text and "action_id=pa:day30-evidence" in text and "`week_ending` = the date of the answer" in text
    assert "How many minutes did the work you hand me take you in the last seven days" in text
    assert "action_id=pa:baseline-ask" in text and text.count("add `declined: true` if the owner declines") == 2
    assert "mark_filed" in (root / "pa-setup/references/where-answers-go.md").read_text()


def test_list_limit_and_category_filter(tmp_path):
    ledger = Ledger(tmp_path)
    for n in range(55):
        ledger.put("action", f"pref:synthetic-{n}", {"text": f"Rule {n}", "category": "work", "state": "active"}, action_type="preference")
    assert len(call(tmp_path, "list", kind="preference", category="work", state="active")) == 50
    assert call(tmp_path, "list", category="food") == []


@pytest.mark.parametrize("data", [
    dict(kind="person", name="Alex", rules=["password: synthetic-only"]),
    dict(kind="person", name="Alex", rules=["4111 1111 1111 1111"]),
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


def test_filed_state_is_set_only_by_mark_filed(tmp_path):
    with pytest.raises(ValueError, match="only by mark_filed"):
        call(tmp_path, kind="person", name="Synthetic Alex", state="filed")
    with pytest.raises(ValueError, match="unsupported profile fields"):
        pref(tmp_path, remove_from_files=True)


def test_forget_or_supersede_filed_records_lists_their_removal(tmp_path, human_hook):
    forgotten, replaced = pref(tmp_path, "Call before 10"), pref(tmp_path, "Prefer short replies", slug="replies")
    call(tmp_path, "mark_filed", identities=[forgotten["action_id"], replaced["action_id"]])
    assert call(tmp_path, "forget", identity=forgotten["action_id"])["fields"]["remove_from_files"] is True
    new = pref(tmp_path, "Prefer detailed replies", source="corrected", supersedes=replaced["action_id"])
    old = Ledger(tmp_path).get("action", replaced["action_id"])["fields"]
    assert old["state"] == "retired" and old["remove_from_files"] is True
    assert {r["identity"] for r in call(tmp_path, "pending_files")} == {forgotten["action_id"], replaced["action_id"], new["action_id"]}
    note = human_hook(user_message="Hello", is_first_turn=True, session_id="s")["context"]
    assert "FORGOTTEN, do not use (still in files until the next review): Call before 10" in note
    filed = call(tmp_path, "mark_filed", identities=[forgotten["action_id"], replaced["action_id"], new["action_id"]])
    assert [r["fields"]["state"] for r in filed] == ["retired", "retired", "filed"]
    assert all("remove_from_files" not in r["fields"] for r in filed) and call(tmp_path, "pending_files") == []


def test_repeated_correction_finishes_an_interrupted_supersession(tmp_path):
    old = pref(tmp_path, "Prefer short replies", slug="replies")
    new = dict(text="Prefer detailed replies", source="corrected", supersedes=old["action_id"])
    pref(tmp_path, **new)
    ledger = Ledger(tmp_path)  # Simulate a crash between the two writes: the old row is still active.
    ledger.put("action", old["action_id"], {**ledger.get("action", old["action_id"])["fields"], "state": "active"}, status="active")
    pref(tmp_path, **new)
    assert ledger.get("action", old["action_id"])["fields"]["state"] == "retired"
    assert pref(tmp_path, **new)["fields"]["state"] == "active"  # A later repeat is a no-op for the retired row.


def test_generic_actions_cannot_use_profile_records(tmp_path, human_hook):
    for data in ({"action_type": "person", "fields": {}}, {"action_id": "pref:synthetic", "fields": {}}):
        with pytest.raises(ValueError, match="operation profile"):
            dispatch(tmp_path, {"operation": "action_upsert", "data": data})
    with pytest.raises(ValueError, match="operation profile"):
        dispatch(tmp_path, {"operation": "action_prepare", "data": {"action_id": "pref:synthetic", "summary": "x"}})
    Ledger(tmp_path).put("action", "legacy-row", {"note": "untyped"}, action_type="person")  # A pre-upgrade row.
    pref(tmp_path)
    assert [r["identity"] for r in call(tmp_path, "list")] == ["pref:prefer-short-replies"]
    assert "pref:prefer-short-replies" in human_hook(user_message="Hello", is_first_turn=True, session_id="s")["context"]


@pytest.mark.parametrize("text", ["API key sk-live-abc12345", "token is abc123def456", "Use password Hunter2024x"])
def test_delimiter_free_credentials_are_rejected(tmp_path, text):
    with pytest.raises(ValueError, match="prohibit credentials"):
        pref(tmp_path, text)


def test_review_round_three_lifecycle(tmp_path):
    assert pref(tmp_path, "Keep the launch date secret")["fields"]["state"] == "active"
    with pytest.raises(ValueError, match="unsupported profile fields"):
        pref(tmp_path, "Prefer calls", source="inferred", owner_confirmed_at="2026-10-21T00:00:00+00:00")
    alex = call(tmp_path, kind="person", name="Synthetic Alex", rules=["Formal greeting"])
    sam = call(tmp_path, kind="person", name="Synthetic Sam")
    call(tmp_path, "mark_filed", identities=[alex["action_id"]])
    filed = call(tmp_path, "mark_filed", identities=[alex["action_id"], sam["action_id"]])  # A retried batch.
    assert [r["fields"]["state"] for r in filed] == ["filed", "filed"]
    retired = call(tmp_path, kind="person", name="Synthetic Alex", rules=["Formal greeting"], state="retired")
    assert retired["fields"]["remove_from_files"] is True
    with pytest.raises(ValidationError):
        call(tmp_path, kind="sop", title="Prep", trigger="Fri", steps=["x" * 301], tools=["cal"], done_when="ok", escalation="ask")
