import copy
import datetime as dt
import json

import pytest
from jsonschema import Draft7Validator, FormatChecker

from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.state import Ledger

AT = "2026-11-14T10:00:00+09:00"


def note(ledger, identity="cos:old", days=20, **fields):
    return ledger.put("action", identity, {
        "title": identity, "cos_skill": "cos-daily", "outcome": "unknown", "stage": "draft",
        "review_at": (dt.datetime.fromisoformat(AT) - dt.timedelta(days=days)).isoformat(),
        "summary": "Synthetic preparation", **fields,
    }, action_type="note", status="completed", trip_id="fixture")


def call(root, **data):
    return dispatch(root, {"operation": "recommendations", "data": {"action": "retire", "at": AT, **data}})


def snapshot(ledger):
    with ledger.connect() as conn:
        rows = [tuple(row) for row in conn.execute("select * from actions order by action_id")]
    return rows, ledger.path.read_bytes()


def test_default_preview_is_read_only_and_sorted(tmp_path, monkeypatch):
    ledger = Ledger(tmp_path)
    for identity, days in (("cos:new", 5), ("cos:z", 30), ("cos:a", 30), ("cos:old", 20)):
        note(ledger, identity, days)
    note(ledger, "cos:boundary", 14)
    note(ledger, "cos:retired", retired={})
    note(ledger, "cos:used", outcome="used")
    before = snapshot(ledger)
    original = Ledger.__init__

    def readonly(self, root, **kwargs):
        assert kwargs.get("read_only") is True
        original(self, root, **kwargs)

    monkeypatch.setattr(Ledger, "__init__", readonly)
    result = call(tmp_path)
    assert result == {"preview": True, "would_retire": [
        {"action_id": identity, **{key: ledger.get("action", identity)["fields"][key]
                                  for key in ("title", "cos_skill", "review_at")}}
        for identity in ("cos:a", "cos:z", "cos:old")], "skipped": [], "count": 3}
    assert snapshot(ledger) == before


def test_preview_on_fresh_profile_creates_nothing(tmp_path):
    assert call(tmp_path) == {"preview": True, "would_retire": [], "skipped": [], "count": 0}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("by", ["owner", "agent"])
def test_explicit_retire_preserves_fields_and_all_skip_reasons(tmp_path, by):
    ledger = Ledger(tmp_path)
    note(ledger, history=[{"at": "2026-10-20T00:00:00Z", "event": "drafted"}], other={"keep": [1, 2]})
    note(ledger, "cos:young", days=5, history="legacy non-list")
    note(ledger, "ordinary")
    note(ledger, "cos:wrong-type")
    ledger.put("action", "cos:wrong-type", {}, action_type="commitment")
    note(ledger, "cos:answered", outcome="declined")
    note(ledger, "cos:future", days=-1)
    note(ledger, "cos:due-now", days=0)
    note(ledger, "cos:already", retired={"by": "owner"})
    before = {row["action_id"]: copy.deepcopy(row) for row in ledger.list("action")}
    ids = ["cos:old", "cos:young", "missing", "ordinary", "cos:wrong-type", "cos:answered",
           "cos:future", "cos:due-now", "cos:already"]
    result = call(tmp_path, preview=False, by=by, action_ids=ids)
    assert result == {"preview": False, "retired": ["cos:old", "cos:young"], "count": 2,
                      "skipped": [{"action_id": identity, "reason": reason} for identity, reason in (
                          ("missing", "not_found"), ("ordinary", "not_a_recommendation"),
                          ("cos:wrong-type", "not_a_recommendation"), ("cos:answered", "outcome_recorded"),
                          ("cos:future", "not_yet_due"), ("cos:due-now", "not_yet_due"),
                          ("cos:already", "already_retired"))]}
    for identity in ("cos:old", "cos:young"):
        after = ledger.get("action", identity)
        expected = copy.deepcopy(before[identity])
        expected["fields"]["retired"] = {"at": AT, "by": by, "reason": "no outcome recorded"}
        history = expected["fields"].get("history")
        expected["fields"]["history"] = (history if isinstance(history, list) else [{"legacy": history}]) + [
            {"at": AT, "event": "retired", "by": by}]
        after.pop("updated_at")
        expected.pop("updated_at")
        assert after == expected
    for identity in ids[3:]:
        assert ledger.get("action", identity) == before[identity]
    assert call(tmp_path, preview=False, by=by, action_ids=["cos:old"])["skipped"] == [
        {"action_id": "cos:old", "reason": "already_retired"}]
    radar = dispatch(tmp_path, {"operation": "next_action", "data": {"radar": True, "at": AT}})
    assert "stale_recommendations" not in radar and radar["candidates"] == []


@pytest.mark.parametrize("data", [
    {"preview": False, "by": "owner"}, {"preview": False, "action_ids": ["cos:old"]},
    {"preview": "false"}, {"action": "ignore"}, {"action_ids": []}, {"action_ids": [1]},
    {"action_ids": ["cos:old"] * 101}, {"by": "other"}, {"at": "2026-11-14T00:00:00"},
    {"at": "bad"}, {"at": ""}, {"private-extra-value": "must never echo"},
])
def test_invalid_shape_is_short_and_writes_nothing(tmp_path, data):
    ledger = Ledger(tmp_path)
    note(ledger)
    before = snapshot(ledger)
    with pytest.raises(ValueError) as exc:
        call(tmp_path, **data)
    message = str(exc.value)
    assert len(message) < 400 and "accepted keys: action, preview, action_ids, by, at" in message
    assert "schema" not in message and "private-extra-value" not in message and "must never echo" not in message
    assert snapshot(ledger) == before


def test_explicit_preview_can_list_younger_notes(tmp_path):
    ledger = Ledger(tmp_path)
    note(ledger, days=5)
    before = snapshot(ledger)
    assert call(tmp_path, action_ids=["cos:old"])["count"] == 1
    assert snapshot(ledger) == before


def test_tool_schema_and_descriptions():
    validator = Draft7Validator(SCHEMA["parameters"], format_checker=FormatChecker())
    base = {"operation": "recommendations", "data": {"action": "retire"}}
    assert validator.is_valid(base)
    assert not validator.is_valid({**base, "data": {"action": "retire", "preview": False}})
    assert validator.is_valid({**base, "data": {"action": "retire", "preview": False,
                                              "action_ids": ["cos:old"], "by": "owner"}})
    text = json.dumps(SCHEMA)
    assert "recommendations: action retire lists" in text and "never records an outcome" in text
    assert "outcome used, declined, ignored or unknown (unknown when evidence is missing)" in text


def test_repeated_ids_once_and_preview_capped_at_100(tmp_path):
    ledger = Ledger(tmp_path)
    note(ledger, "cos:a")
    assert call(tmp_path, preview=False, by="owner", action_ids=["cos:a", "cos:a"]) == {
        "preview": False, "retired": ["cos:a"], "skipped": [], "count": 1}
    for i in range(103):
        note(ledger, f"cos:n{i:03d}")
    preview = call(tmp_path)
    assert preview["count"] == 100 and preview["more"] == 3 and len(preview["would_retire"]) == 100


def test_malformed_write_on_fresh_profile_creates_nothing(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    with pytest.raises(ValueError):
        dispatch(root, {"operation": "recommendations", "data": {"action": "retire", "preview": False, "by": "owner"}})
    assert list(root.rglob("*")) == []
