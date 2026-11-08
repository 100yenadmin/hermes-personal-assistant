"""The skills give the exact envelopes and a rejected envelope names what to fix (#97)."""
import json
import os
import re
import tempfile
from pathlib import Path

import pytest

from personal_assistant.entry import GOVERNED_PREPARE_KEYS, dispatch
from tests.test_auto_exact_action import SESSION_ID, TASK_ID, governed_data

ROOT = Path(__file__).resolve().parents[1]
SCOPE = {"session_id": SESSION_ID, "task_id": TASK_ID}


@pytest.fixture
def profile():
    with tempfile.TemporaryDirectory() as temp:
        os.chmod(temp, 0o700)
        yield Path(temp)


def _prepare(profile, data):
    return dispatch(profile, {"operation": "action_prepare", "data": data}, runtime_scope=SCOPE)


def test_a_governed_prepare_names_its_missing_keys(profile):
    data = governed_data()
    for key in ("fresh_until", "expected_readback"):
        data.pop(key)
    with pytest.raises(ValueError, match="governed action_prepare is missing: fresh_until, expected_readback"):
        _prepare(profile, data)


def test_incomplete_authority_says_to_omit_it(profile):
    with pytest.raises(ValueError, match="omit authority on action_prepare"):
        _prepare(profile, {**governed_data(), "authority": {"mode": "exact_confirmation"}})
    assert _prepare(profile, governed_data())["status"] == "approval_required"


def test_preconditions_name_the_required_keys(profile):
    with pytest.raises(ValueError, match="each of authority"):
        _prepare(profile, {**governed_data(), "preconditions": {"other": "confirmed"}})


def test_an_unconfirmed_precondition_is_named_at_confirmation(profile):
    data = {**governed_data(), "preconditions": {"authority": "pending"}}
    _prepare(profile, data)
    with pytest.raises(ValueError, match='not confirmed: authority; check each on the live page, then prepare again with a new action_revision'):
        dispatch(profile, {"operation": "action_confirm", "data": {
            "action_id": data["action_id"], "summary": data["summary"], "confirmation": "yes"}}, runtime_scope=SCOPE)
    # Following the message works: a new revision with the precondition confirmed is accepted.
    assert _prepare(profile, {**governed_data(revision="r2")})["status"] == "approval_required"


def test_the_documented_envelope_matches_the_code():
    text = (ROOT / "skills/personal-assistant/SKILL.md").read_text()
    block = re.search(r'```json\n(\{"operation":"action_prepare".*?)\n```', text, re.S).group(1)
    data = json.loads(block)["data"]
    assert set(GOVERNED_PREPARE_KEYS) <= set(data) and "authority" not in data
    assert data["execution_budget"] == 1 and data["enforcement_profile"] == "exact_action"
    assert set(data["preconditions"]) == set(data["required_pre_action_projections"])
    assert all(v == "confirmed" for v in data["preconditions"].values())
    assert [data["tool_args"][p[0]] for p in data["semantic_target"]["paths"]] == data["semantic_target"]["value"]


def test_the_routine_recipe_uses_real_automation_actions(profile):
    text = (ROOT / "skills/personal-assistant/r5-brief-reminders/SKILL.md").read_text()
    for action in ("preferences", "rule", "suggest"):
        assert f'"action":"{action}"' in text
    assert "/suggestions accept" in text and "PA never creates" in text and '"destination":"origin"' in text
    assert "never guess a chat ID" in text and "accept_command" in text
    dispatch(profile, {"operation": "automations", "data": {"action": "preferences", "changes": {"timezone": "Asia/Tokyo", "brief_time": "07:30"}}})
    dispatch(profile, {"operation": "automations", "data": {"action": "rule", "rule_id": "daily_brief", "rule": {
        "kind": "daily_brief", "accepted": True, "destination": "origin", "destination_verified": True, "timezone": "Asia/Tokyo"}}})
    status = dispatch(profile, {"operation": "automations", "data": {"action": "status"}})
    assert status["preferences"]["brief_time"] == "07:30" and status["rules"][0]["fields"]["automation_rule"]["accepted"]
