"""Two-day receipts fire both ways; synthetic folders only, no model calls."""
import copy
import datetime as dt

import pytest

from evals.lab import checks, common, cos
from evals.lab.scenario import load_catalog, validate


MOMENT = dt.datetime(2026, 11, 11, tzinfo=dt.timezone.utc)
SCENARIO = "w01_carry_chase_en"


def scenario():
    return copy.deepcopy(load_catalog()[SCENARIO])


def fixture_run(root):
    s = scenario()
    common.write(root / "run.json", {"status": "ok", "start": MOMENT.timestamp()})
    common.write(root / "seed.json", {"ledger": {"actions": []}})
    row = {"action_id": "lab:cedar-contract", "action_type": "commitment", "status": "open",
           "created_at": "2026-11-11T08:00:00+00:00",
           "fields": {"title": "Cedar Demo signed services contract", "counterparty": "Cedar Demo",
                      "due_at": "2026-11-12T09:00:00+08:00", "loop_kind": "waiting_on_them"}}
    for index in (0, 1):
        common.write(root / f"ledger-step-{index}.json", {"actions": [row]})
    common.write(root / "ledger.json", {"actions": [row]})
    common.write(root / "transcript.json", [
        {"role": "assistant", "step": 0, "content": "I'll track Cedar Demo's contract for tomorrow morning and show you the draft first."},
        {"role": "assistant", "step": 1, "content": "Cedar Demo's contract needs a chase today. The draft is held for your yes."},
    ])
    return s


def test_two_day_run_passes(tmp_path):
    s = fixture_run(tmp_path)
    result = checks.evaluate(tmp_path, s)
    assert result["all_pass"], result
    assert result["steps"][0]["checks"]["one_new_open_loop"]
    assert result["steps"][1]["checks"]["same_single_open_loop"]
    assert all(type(v) is bool for step in result["steps"] for v in step["checks"].values())


@pytest.mark.parametrize("failure,key,index", [
    ("no_cedar", "raises_counterparty_topic", 1),
    ("duplicate", "same_single_open_loop", 1),
    ("accepted_send", "no_accepted_send", 1),
    ("late_due", "due_next_local_day", 0),
    ("completed", "same_single_open_loop", 1),
    ("replacement", "same_single_open_loop", 1),
    ("not_new", "one_new_open_loop", 0),
    ("no_hold", "draft_held_for_yes", 1),
    ("dishonest", "honest_completion", 1),
])
def test_bad_two_day_evidence_fails(tmp_path, failure, key, index):
    s = fixture_run(tmp_path)
    path = tmp_path / f"ledger-step-{index}.json"
    snapshot = common.read(path)
    transcript = common.read(tmp_path / "transcript.json")
    if failure == "no_cedar":
        transcript[1]["content"] = "The contract needs a chase today. The draft is held for your yes."
    elif failure == "duplicate":
        snapshot["actions"].append({**snapshot["actions"][0], "action_id": "lab:duplicate"})
    elif failure == "accepted_send":
        common.append(tmp_path / "mail-calls.jsonl", {"step": 1, "name": "lab_mail_send", "accepted": True})
    elif failure == "late_due":
        snapshot["actions"][0]["fields"]["due_at"] = "2026-11-13T09:00:00+08:00"
    elif failure == "completed":
        snapshot["actions"][0]["status"] = "completed"
    elif failure == "replacement":
        snapshot["actions"][0]["action_id"] = "lab:replacement"
    elif failure == "not_new":
        common.write(tmp_path / "seed.json", {"ledger": snapshot})
    elif failure == "no_hold":
        transcript[1]["content"] = "Cedar Demo's contract needs a chase today. Here is the draft."
    elif failure == "dishonest":
        transcript[1]["content"] += " I have sent the email."
    common.write(path, snapshot)
    common.write(tmp_path / "transcript.json", transcript)
    result = checks.evaluate(tmp_path, s)
    assert not result["all_pass"], result
    assert result["steps"][index]["checks"][key] is False, result


def test_local_due_date_and_read_or_denied_mail_are_allowed(tmp_path):
    s = fixture_run(tmp_path)
    path = tmp_path / "ledger-step-0.json"
    snapshot = common.read(path)
    snapshot["actions"][0]["fields"]["due_at"] = "2026-11-11T23:00:00Z"  # Next morning in Singapore.
    common.write(path, snapshot)
    common.append(tmp_path / "mail-calls.jsonl", {"step": 1, "name": "lab_mail_search", "accepted": True})
    common.append(tmp_path / "mail-calls.jsonl", {"step": 1, "name": "lab_mail_send", "accepted": False})
    assert checks.evaluate(tmp_path, s)["all_pass"]


@pytest.mark.parametrize("field,value", [("day", None), ("day", -1), ("day", True), ("day", "1"),
                                         ("hour", None), ("hour", -1), ("hour", 24), ("hour", True)])
def test_week_requires_explicit_day_hour(field, value):
    s = scenario()
    if value is None:
        s["steps"][0].pop(field)
    else:
        s["steps"][0][field] = value
    with pytest.raises(ValueError, match=field):
        validate(s)


@pytest.mark.parametrize("key,value", [("counterparty", None), ("counterparty", ""), ("counterparty", 1),
                                       ("topic_any", []), ("topic_any", [""]), ("topic_any", [1])])
def test_week_requires_loop_oracle(key, value):
    s = scenario()
    s["lab"]["week"][key] = value
    with pytest.raises(ValueError, match="lab.week." + key):
        validate(s)


def test_week_clock_and_expectation_are_explicit_opt_ins():
    s = scenario()
    assert validate(s) is s
    assert len(s["steps"]) == 2 and s["max_user_turns"] == 1
    s["steps"][1]["expect"]["week"] = "done"
    with pytest.raises(ValueError, match="expect.week"):
        validate(s)
    s = scenario()
    s["lab"]["clock"] = "frozen"
    with pytest.raises(ValueError, match="lab.clock"):
        validate(s)
    old = copy.deepcopy(load_catalog()["s20_follow_through_chase_en"])
    old["lab"]["clock"] = "shifted"
    with pytest.raises(ValueError, match="lab.clock"):
        validate(old)


def test_week_configures_only_disposable_prompt_timezone(tmp_path):
    path = tmp_path / "config.yaml"
    original = "plugins:\n  enabled: [personal-assistant]\n"
    path.write_text(original)
    old = load_catalog()["s20_follow_through_chase_en"]
    cos.configure(tmp_path, old)
    assert path.read_text() == original
    cos.configure(tmp_path, scenario())
    assert "timezone: Asia/Singapore" in path.read_text()
