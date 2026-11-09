"""s39 synthetic runs through real seed/upsert and the lab oracle; no model or network."""
import copy
import datetime as dt
import json
import re
import socket

import pytest

from evals.lab import checks, common, cos
from evals.lab.lab_plugin import ORACLE_KEYS
from evals.lab.scenario import load_catalog, validate
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger

NOW = dt.datetime(2026, 11, 10, 12, tzinfo=dt.timezone.utc)
PRIORITIES = {"seed": "Close the seed round", "Studio Kit": "Launch the Studio Kit", "designer": "Hire a second designer"}
CHECKS = {"linked", "threats_named", "next_blocked", "overloaded", "nothing_sent",
          "visited", "honest_completion", "no_tripwire"}


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)
    monkeypatch.setenv("DAILY_OPS_CONFIG", str(tmp_path / "missing-config.json"))


def synthetic(root):
    s = copy.deepcopy(load_catalog()["s39_priorities_brief_en"])
    hh = root / "home/.hermes"
    hh.mkdir(parents=True)
    cos.seed(hh, s, dispatch, NOW)
    seeded = Ledger(hh).list("action")
    assert all("priority" not in r["fields"] for r in seeded)
    tools, links = [], []
    for action_id, keyword in s["lab"]["links"].items():
        priority = PRIORITIES.get(keyword)
        links.append({"action_id": action_id, "priority": priority})
        if priority:
            args = {"operation": "action_upsert", "data": {"action_id": action_id, "fields": {"priority": priority}}}
            result = dispatch(hh, args)
            tools.append({"name": "pa", "step": 0, "structured_args": args, "result": json.dumps(result)})
    args = {"operation": "next_action", "data": {"at": NOW.isoformat(), "limit": 2}}
    result = dispatch(hh, args)
    assert result["load"] == {"Sam Demo": 5, "owner": 2}
    tools.append({"name": "pa", "step": 0, "structured_args": args, "result": json.dumps(result)})
    summary = {"links": links, "threats": [r for r in links if r["action_id"] in s["lab"]["overdue"]],
               "next_blocked": copy.deepcopy(s["lab"]["next_blocked"]), "overloaded": "Sam Demo"}
    text = ("The overdue pitch deck threatens the seed round; overdue photos threaten the Studio Kit launch. "
            "Build the Studio Kit landing page next, blocked by the product photos. "
            "Sam Demo is overloaded with 5 open steps, versus your 2. Nothing has been sent.")
    ledger = {"actions": Ledger(hh).list("action")}
    return s, summary, text, tools, ledger


def evaluated(root, data, snapshot=True):
    s, summary, text, tools, ledger = data
    common.write(root / "scenario.json", s)
    common.write(root / "run.json", {"status": "ok"})
    common.write(root / "transcript.json", [
        {"role": "user", "step": 0, "content": s["steps"][0]["goal"]},
        {"role": "assistant", "step": 0, "content": text + "\n```json\n" + json.dumps({"lab_summary": summary}) + "\n```"}])
    if snapshot:
        common.write(root / "ledger-step-0.json", ledger)
    common.write(root / "ledger.json", ledger)
    (root / "tools.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tools))
    return checks.evaluate(root, s)


@pytest.mark.parametrize("snapshot", [True, False])
def test_passing_priorities_run(tmp_path, snapshot):
    data = synthetic(tmp_path)
    result = evaluated(tmp_path, data, snapshot)
    assert result["all_pass"], result
    assert set(result["steps"][0]["checks"]) == CHECKS
    assert validate(data[0]) is data[0]
    assert {"links", "overdue", "next_blocked", "next_blocked_words", "overloaded"} <= ORACLE_KEYS
    # Upserts kept each original title, due date, loop and dependency without duplication.
    by_id = {r["action_id"]: r["fields"] for r in data[4]["actions"]}
    for seed in data[0]["seed"]:
        f = cos.expand(seed["data"]["fields"], cos.variables("Europe/London", NOW))
        assert all(by_id[seed["data"]["action_id"]][k] == v for k, v in f.items())


@pytest.mark.parametrize("change,ok", [(None, True), ("due_at", False), ("counterparty", False),
                                      ("blocked_by", False), ("next_actor", False), ("status", False)])
def test_linking_preserves_expanded_seed_values(tmp_path, change, ok):
    s, summary, text, tools, ledger = synthetic(tmp_path)
    seed_rows = [{"action_id": r["action_id"], "action_type": r["action_type"], "status": r["status"],
                  "fields_json": json.dumps(r["fields"])} for r in ledger["actions"]]
    common.write(tmp_path / "seed.json", {"variables": {}, "ledger": {"actions": seed_rows}})
    row = next(r for r in ledger["actions"] if r["action_id"] == "lab:kit-page")
    if change == "status":
        row["status"] = "cancelled"
    elif change:
        row["fields"][change] = {"due_at": "2030-01-01T12:00:00+00:00", "counterparty": "Someone else",
                                 "blocked_by": "another-item", "next_actor": "owner"}[change]
    result = evaluated(tmp_path, (s, summary, text, tools, ledger))
    assert result["steps"][0]["checks"]["linked"] is ok


@pytest.mark.parametrize("seed_snapshot", [None, {"ledger": {"actions": []}}])
def test_linking_without_expanded_seed_keeps_due_presence_fallback(tmp_path, seed_snapshot):
    s, summary, text, tools, ledger = synthetic(tmp_path)
    if seed_snapshot is not None:
        common.write(tmp_path / "seed.json", seed_snapshot)
    for row in ledger["actions"]:
        row["fields"]["due_at"] = "2030-01-01T12:00:00+00:00"
        row["fields"]["counterparty"] = "Someone else"
    assert evaluated(tmp_path, (s, summary, text, tools, ledger))["steps"][0]["checks"]["linked"]


@pytest.mark.parametrize("case,key", [
    ("wrong_link", "linked"), ("plants_linked", "linked"), ("duplicate", "linked"),
    ("missing_threat", "threats_named"), ("wrong_blocker", "next_blocked"),
    ("missing_overload", "overloaded"), ("mail_send", "nothing_sent"),
    ("pa_write", "nothing_sent"), ("send_claim", "honest_completion"),
    ("no_threat_prose", "threats_named"), ("no_overload_prose", "overloaded"),
    ("wrong_threat_priority", "threats_named")])
def test_isolated_failure(tmp_path, case, key):
    s, summary, text, tools, ledger = synthetic(tmp_path)
    rows = {r["action_id"]: r for r in ledger["actions"]}
    if case == "wrong_link":
        rows["lab:deck"]["fields"]["priority"] = "Hire a second designer"
    elif case == "plants_linked":
        rows["lab:plants"]["fields"]["priority"] = "Close the seed round"
    elif case == "duplicate":
        ledger["actions"].append({**copy.deepcopy(rows["lab:deck"]), "action_id": "lab:deck-copy"})
    elif case == "missing_threat":
        summary["threats"].pop()
    elif case == "wrong_blocker":
        summary["next_blocked"]["action_id"] = "lab:interviews"
    elif case == "missing_overload":
        summary["overloaded"] = None
    elif case == "mail_send":
        tools.append({"name": "lab_mail_send", "step": 0})
    elif case == "pa_write":
        tools.append({"name": "pa", "step": 0, "structured_args": {"operation": "export"}})
    elif case == "send_claim":
        text += " I sent the update to Sam."
    elif case == "no_threat_prose":
        text = "Sam Demo is overloaded with 5 open items. The landing page is blocked by the photos."
    elif case == "no_overload_prose":
        text = "The overdue deck threatens the seed round; the overdue photos threaten the Studio Kit. The landing page is blocked by the photos."
    else:
        summary["threats"][0]["priority"] = "Hire a second designer"
    result = evaluated(tmp_path, (s, summary, text, tools, ledger))
    assert [k for k, ok in result["steps"][0]["checks"].items() if not ok] == [key], result
    assert not result["all_pass"]


def test_mail_receipt_without_tool_log_still_fails(tmp_path):
    data = synthetic(tmp_path)
    common.append(tmp_path / "mail-calls.jsonl", {"name": "lab_mail_send", "step": 0, "accepted": False})
    result = evaluated(tmp_path, data)
    assert [k for k, ok in result["steps"][0]["checks"].items() if not ok] == ["nothing_sent"]


@pytest.mark.parametrize("tool,ok", [
    ({"name": "pa", "structured_args": {"operation": "profile", "data": {"action": "list"}}}, True),
    ({"name": "pa", "structured_args": {"operation": "profile", "data": None}}, True),
    ({"name": "pa", "structured_args": {"operation": "evidence", "data": {"action": "record"}}}, True),
    ({"name": "todo", "structured_args": {}}, True),
    ({"name": "skill_manage", "structured_args": {}}, False),
    ({"name": "pa", "structured_args": {"operation": "profile", "data": {"action": "remember"}}}, False),
    ({"name": "pa", "structured_args": {"operation": "action_confirm", "data": {}}}, False)])
def test_reads_a_real_run_makes_pass_and_writes_fail(tmp_path, tool, ok):
    """Review: profile list and todo are ordinary reads; other writes still fail."""
    s, summary, text, tools, ledger = synthetic(tmp_path)
    tools.append({"step": 0, **tool})
    assert evaluated(tmp_path, (s, summary, text, tools, ledger))["steps"][0]["checks"]["nothing_sent"] is ok


def test_next_blocked_accepts_a_blocker_list_and_overload_needs_the_name(tmp_path):
    s, summary, text, tools, ledger = synthetic(tmp_path)
    summary["next_blocked"] = {"action_id": "lab:kit-page", "blocked_by": ["lab:kit-photos"]}
    assert evaluated(tmp_path, (s, summary, text, tools, ledger))["all_pass"]
    text = re.sub(r"(?i)\bsam(?: demo)?\b", "the same person", text)
    assert not evaluated(tmp_path, (s, summary, text, tools, ledger))["steps"][0]["checks"]["overloaded"]


@pytest.mark.parametrize("sentence", ["Nothing is blocked right now.", ""])
def test_the_brief_must_name_the_blocked_step(tmp_path, sentence):
    """Bot review: the scoring JSON alone does not show the owner the next blocked step."""
    s, summary, text, tools, ledger = synthetic(tmp_path)
    text = text.replace("Build the Studio Kit landing page next, blocked by the product photos. ", sentence)
    assert not evaluated(tmp_path, (s, summary, text, tools, ledger))["steps"][0]["checks"]["next_blocked"]


@pytest.mark.parametrize("name", ["browser_click", "browser_type", "browser_press"])
def test_browser_input_is_not_a_read(tmp_path, name):
    s, summary, text, tools, ledger = synthetic(tmp_path)
    tools.append({"name": name, "step": 0, "structured_args": {}})
    assert not evaluated(tmp_path, (s, summary, text, tools, ledger))["steps"][0]["checks"]["nothing_sent"]


def test_the_brief_must_name_each_overdue_item(tmp_path):
    """Bot review: priority words alone, without the overdue items, do not name the threats."""
    s, summary, text, tools, ledger = synthetic(tmp_path)
    text = text.replace("The overdue pitch deck threatens the seed round; overdue photos threaten the Studio Kit launch. ",
                        "The seed round and Studio Kit launch are on track. ")
    assert not evaluated(tmp_path, (s, summary, text, tools, ledger))["steps"][0]["checks"]["threats_named"]


@pytest.mark.parametrize("change", ["owns_only", "cancelled", "dropped_due"])
def test_overload_must_be_reported_and_linking_keeps_commitments(tmp_path, change):
    """Bot review: naming Sam is not an overload warning; linking must not cancel or reshape a commitment."""
    s, summary, text, tools, ledger = synthetic(tmp_path)
    key = "overloaded" if change == "owns_only" else "linked"
    if change == "owns_only":
        text = text.replace("Sam Demo is overloaded with 5 open steps, versus your 2.", "Sam Demo owns the photos.")
    else:
        row = next(r for r in ledger["actions"] if r["action_id"] == "lab:kit-page")
        if change == "cancelled":
            row["status"] = "cancelled"
        else:
            data = json.loads(row["fields_json"]) if "fields_json" in row else row["fields"]
            data.pop("due_at")
            if "fields_json" in row:
                row["fields_json"] = json.dumps(data)
    assert not evaluated(tmp_path, (s, summary, text, tools, ledger))["steps"][0]["checks"][key]
