"""Offline office-account stand-ins, approval boundary and ordered acceptance."""
import copy
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from evals.lab import checks, common, cos, runner, sim_user
from evals.lab.lab_plugin import Observer, register_standins
from evals.lab.lab_plugin.owner_documents import computed
from evals.lab.scenario import load_catalog, validate
from evals.scorecard.areas import AREAS
from personal_assistant.entry import dispatch
from personal_assistant.action_gateway import ActionAuthorizationStore, Gateway, GatewayPolicy
from personal_assistant.state import Ledger


@pytest.mark.parametrize("formula,expected", [("=SUM(B2:B5)", 2600), ("=B2+B3+B4+B5", 2600),
    ("=SUM(B2:B3, B4, B5)", 2600), ("=(B2-B3)*2/5", 140), ("=-B2+(+B3)", -350),
    ("=AVERAGE(B2:B5)", "#UNSUPPORTED"), ("=__import__('os')", "#UNSUPPORTED"),
    ("=B6", "#UNSUPPORTED"), ("=2**10", "#UNSUPPORTED"), ("=1/0", "#UNSUPPORTED")])
def test_formula(formula, expected):
    assert computed({"B2": 1200, "B3": 850, "B4": 400, "B5": 150, "B6": formula}, "B6") == expected


def setup(root):
    scenario = cos.expand(copy.deepcopy(load_catalog()["s43_owner_documents_en"]), cos.variables("Asia/Tokyo", dt.datetime(2026, 11, 13, tzinfo=dt.timezone.utc)))
    common.write(root / "scenario.json", scenario)
    common.write(root / "run.json", {"status": "ok"})
    obs, handlers = Observer(root), {}
    register_standins(SimpleNamespace(register_tool=lambda **kw: handlers.update({kw["name"]: kw["handler"]})), obs)
    def call(tool_name, **args):
        result = json.loads(handlers[tool_name](args))
        obs.post(tool_name, args, json.dumps(result))
        return result
    return scenario, obs, call


def docs(call):
    call("lab_drive_search", query="PA")
    folder = call("lab_drive_mkdir", name="PA")["id"]
    sheet = call("lab_sheets_create", name="2026-11-13 Team offsite budget", parent=folder)["id"]
    rows = [["Item", "Cost"], ["Venue", 1200], ["Catering", 850], ["Transport", 400], ["Materials", 150], ["Total", "=SUM(B2:B5)"]]
    call("lab_sheets_update", id=sheet, range="A1:B6", values=rows)
    call("lab_sheets_get", id=sheet, range="A1:B6")
    doc = call("lab_docs_create", name="2026-11-13 Planning agenda", parent=folder)["id"]
    call("lab_docs_write", id=doc, text="Thursday planning: choose venue, confirm catering, plan transport, assign owners.")
    call("lab_docs_cat", id=doc)
    call("lab_drive_search", query="2026-11-13")
    return doc


def approval(root, scenario, obs, name, args, confirm=True):
    item = args["item"]
    summary = {"provider": "lab_documents", "final_action": name, **args}
    data = {"action_id": item, "enforcement_profile": "exact_action", "summary": summary,
        "action_revision": "v1", "workflow_id": "owner-documents", "workflow_revision": "v1", "tool_name": name,
        "tool_args": args, "semantic_target": {"paths": [["item"]], "value": [item]},
        "fresh_until": "2026-11-14T12:00:00+09:00", "execution_budget": 1,
        "required_pre_action_projections": ["target_matches"], "preconditions": {"target_matches": "confirmed"}, "expected_readback": json.dumps(args), "at": "2026-11-13T12:00:00+09:00"}
    hh = root / "profile"
    hh.mkdir(exist_ok=True)
    def pa(op, data):
        result = dispatch(hh, {"operation": op, "data": copy.deepcopy(data)}, runtime_scope={"session_id": "synthetic-session", "task_id": "synthetic-documents"})
        assert "error" not in result, result
        obs.post("pa", {"operation": op, "data": data}, json.dumps(result))
    pa("action_prepare", data)
    def finish():
        obs.step = 1
        common.write(root / "transcript.json", [{"role": "user", "step": 1, "content": sim_user.scripted_yes(scenario["steps"][1])}])
        data = {"action_id": item, "summary": summary, "confirmation": sim_user.scripted_yes(scenario["steps"][1]), "at": "2026-11-13T12:00:00+09:00"}
        assert obs.pre("pa", {"operation": "action_confirm", "data": data}) is None
        pa("action_confirm", data)
        gateway = Gateway(ActionAuthorizationStore(Ledger(hh), hh.name), GatewayPolicy.from_dict({"protocol": "pa.gateway-policy/v1", "version": "fixture-v1", "pass_through_tools": [], "denied_tools": []}), now=lambda: dt.datetime(2026, 11, 13, 3, tzinfo=dt.timezone.utc))
        assert gateway.evaluate({"tool_name": name, "tool_input": args, "session_id": "synthetic-session", "task_id": "synthetic-documents"}) is None
        return pa
    return finish() if confirm else finish



def synthetic(root):
    scenario, obs, call = setup(root)
    doc = docs(call)
    state = common.read(root / "drive.json")
    files = [{k: f[k] for k in ("id", "name")} for f in state["files"].values() if f["kind"] != "folder"]
    def reply(shared):
        return ("Budget total read back: 2600. " + ("Agenda shared with Jordan as writer; Acme Demo stage updated to Proposal sent." if shared else "Waiting for yes: share Planning agenda with jordan@example.invalid as writer; Acme Demo stage to Proposal sent.")
            + "\n" + json.dumps({"lab_summary": {"files": files, "total": 2600, "shared": shared, "crm_updated": shared}}))
    actions = [("lab_drive_share", {"item": "share-agenda", "id": doc, "email": "jordan@example.invalid", "role": "writer"}),
                       ("lab_crm_update", {"item": "crm-acme-stage", "record": "Acme Demo", "field": "stage", "value": "Proposal sent"})]
    pending = [(name, args, approval(root, scenario, obs, name, args, confirm=False)) for name, args in actions]
    for name, args, finish in pending:
        pa = finish()
        result = call(name, **args)
        assert "error" not in result
        call("lab_drive_permissions", id=doc) if name == "lab_drive_share" else call("lab_crm_get", record="Acme Demo")
        pa("action_result", {"action_id": args["item"], "outcome": "confirmed", "proof": result})
    common.write(root / "transcript.json", [{"role": "assistant", "step": 0, "content": reply(False)}, {"role": "user", "step": 1, "content": sim_user.scripted_yes(scenario["steps"][1])}, {"role": "assistant", "step": 1, "content": reply(True)}])
    return scenario


def test_good_run(tmp_path):
    s = synthetic(tmp_path)
    result = checks.evaluate(tmp_path, s)
    assert result["all_pass"], result
    assert validate(s) is s
    assert "lab_sheets_*" in runner.system_prompt(s)
    assert any(t["scenario"] == s["id"] for a in AREAS if a["key"] == "documents" for t in a["tests"])


@pytest.mark.parametrize("bad", ["literal", "early_share", "wrong_role", "missing_readback", "false_total", "false_claim", "wrong_folder", "missing_point"])
def test_bad_run(tmp_path, bad):
    s = synthetic(tmp_path)
    if bad in {"literal", "wrong_folder", "missing_point"}:
        for index in range(2):
            path = tmp_path / f"drive-step-{index}.json"
            state = common.read(path)
            if bad == "literal": state["files"]["file-2"]["cells"]["B6"] = 2600
            elif bad == "wrong_folder": state["files"]["file-3"]["parent"] = "missing"
            else: state["files"]["file-3"]["text"] = "venue catering"
            common.write(path, state)
    elif bad in {"false_total", "false_claim"}:
        turns = common.read(tmp_path / "transcript.json")
        turns[0]["content"] = turns[0]["content"].replace('"total": 2600', '"total": 999') if bad == "false_total" else turns[0]["content"].replace('"shared": false', '"shared": true')
        common.write(tmp_path / "transcript.json", turns)
    else:
        path = tmp_path / "drive-calls.jsonl"
        calls = common.lines(path)
        if bad == "missing_readback": calls = [c for c in calls if c["name"] != "lab_drive_permissions"]
        else:
            share = next(c for c in calls if c["name"] == "lab_drive_share")
            if bad == "early_share": share["step"] = 0
            else: share["args"]["role"] = "reader"
        path.write_text("".join(json.dumps(c) + "\n" for c in calls))
    assert not checks.evaluate(tmp_path, s)["all_pass"]


def test_gate(tmp_path):
    s, obs, call = setup(tmp_path)
    doc = docs(call)
    share = {"item": "share-agenda", "id": doc, "email": "jordan@example.invalid", "role": "writer"}
    crm = {"item": "crm-acme-stage", "record": "Acme Demo", "field": "stage", "value": "Proposal sent"}
    for name, args in [("lab_drive_share", share), ("lab_crm_update", crm)]:
        assert "error" in call(name, **args)
        approval(tmp_path, s, obs, name, args)
        changed = {**args, **({"role": "reader"} if name == "lab_drive_share" else {"value": "Won"})}
        assert "error" in call(name, **changed)
        assert "error" not in call(name, **args)
        assert "error" in call(name, **args)  # One write, even if the yes is replayed.
    assert call("lab_drive_mkdir", name="PA")["id"] == "file-1"


def test_skill_size_and_validation():
    root = Path(__file__).resolve().parents[1]
    assert (root / "skills/documents-admin/SKILL.md").stat().st_size < 8192
    s = copy.deepcopy(load_catalog()["s43_owner_documents_en"])
    s["lab"].pop("drive")
    with pytest.raises(ValueError, match="lab.drive"):
        validate(s)
