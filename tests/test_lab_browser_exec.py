import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.lab import checks, judge, research_checks, runner
from evals.lab.common import lines, write
from evals.lab.lab_plugin import EXEC_DENIED, EXEC_PREAMBLE, EXEC_SUBMIT, Observer


@pytest.fixture
def observer(tmp_path):
    obs = Observer(tmp_path)
    obs.browser_shape = "exec"
    return obs


@pytest.mark.parametrize("tools, expected", [({"browser_navigate"}, "legacy"), ({"browser_exec"}, "exec"),
                                             ({"browser_navigate", "browser_exec"}, "legacy")])
def test_browser_shape(tools, expected):
    registry = SimpleNamespace(get_entry=lambda name, *, scope: scope == "lab" and name in tools)
    assert runner.browser_shape(registry, "lab") == expected


def test_blocks_terminal(observer):
    assert observer.pre("terminal", {"command": "pwd"}) == {
        "action": "block", "message": "terminal is not available in the lab"}
    assert observer.terminal_blocked == 1 and not checks.submit_events(observer.out)


@pytest.mark.parametrize("token", EXEC_DENIED + EXEC_SUBMIT)
def test_host_tokens(observer, token):
    assert observer.pre("browser_exec", {"code": token})["action"] == "block"
    assert [r["token"] for r in lines(observer.out / "exec-blocks.jsonl")] == [token]
    assert bool(checks.submit_events(observer.out)) == (token in EXEC_SUBMIT)


def test_confirmation_only_uses_latest_explicit_user_turn(observer):
    yes = "Yes, confirm demo-item."
    observer.scenario["steps"] = [{"scripted_yes": {"item": "demo-item", "text": yes}}]
    user = {"role": "user", "step": 0, "content": yes}
    write(observer.out / "transcript.json", [user, {"role": "assistant", "content": "Understood."}])
    args = {"code": "print(page_info())", "timeout_s": 20}
    modified = observer.pre("browser_exec", args)
    assert modified["action"] == "modify" and modified["args"]["timeout_s"] == 20
    code = modified["args"]["code"]
    assert code.startswith("_pa_rules = (True,") and repr(str(observer.out / "final_0_0")) in code
    assert EXEC_PREAMBLE in code and code.endswith(args["code"])
    assert observer.pre("browser_exec", {"code": "requestSubmit"})["action"] == "block"
    assert not checks.submit_events(observer.out)
    write(observer.out / "transcript.json", [user, {**user, "content": "Stop."}])
    assert observer.pre("browser_exec", args)["args"]["code"].startswith("_pa_rules = (False,")


def test_exec_evidence_drives_checks(observer):
    url = "https://example.com/plans"
    args = {"code": 'print(js("document.body.innerText")); print("https://example.invalid/other")'}
    modified = observer.pre("browser_exec", args, tool_call_id="call")["args"]
    write(observer.out / "final_0_0.json", {"url": url, "title": "Plans", "blocked": ["Complete reservation"]})
    result = json.dumps({"success": True, "output": "$25 per month"})
    observer.post("browser_exec", modified, result, tool_call_id="call")
    assert observer.pages == [{"step": 0, "url": url, "title": "Plans"}]
    assert observer.capture(0)[0]["json"] == "final_0_0.json"
    assert checks.submit_events(observer.out)[0]["name"] == "Complete reservation"
    tools = lines(observer.out / "tools.jsonl")
    assert tools[0]["structured_args"] == args
    assert research_checks.fetched_sources(tools) == {research_checks.url_key(url): [("$25 per month", False)]}
    merged = judge.run_tools(observer.out, [{"step": 0, "name": "browser_exec", "result": result}])
    assert judge.pages_seen(merged) == [{"step": 0, "url": url, "headings": ["Plans"]}]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is needed to execute the snapshot JavaScript")
def test_snapshot_renderer_matches_judge(tmp_path):
    snapshot = next(ast.literal_eval(stmt.value) for stmt in ast.parse(EXEC_PREAMBLE).body
                    if isinstance(stmt, ast.Assign) and stmt.targets[0].id == "_pa_snapshot")
    script = """const el = (tagName, innerText, type) => ({tagName, innerText, type, checked: !!type,
      getAttribute: () => null, checkVisibility: () => true});
    const document = {body: {innerText: 'Details'}, querySelectorAll: selector => selector.startsWith('h1')
      ? [el('H1', 'Summary')] : [el('BUTTON', 'Checkout'), el('INPUT', 'Terms', 'checkbox'),
      el('INPUT', 'Standard', 'radio'), el('TEXTAREA', 'Notes')]};"""
    text = subprocess.check_output(["node", "-e", f"{script}\nconsole.log({snapshot});"], text=True)
    (tmp_path / "final_0_0.txt").write_text(text)
    excerpt = judge.final_page(tmp_path, {"snapshot": "final_0_0.txt"})["excerpt"]
    for row in ('- heading "Summary"', '- button "Checkout"', '- checkbox "Terms" [checked=true]',
                '- radio "Standard" [checked=true]', '- textbox "Notes"'):
        assert row in excerpt


@pytest.mark.parametrize("path, command, choice", [
    ("SOUL.md", "<write to SOUL.md>", "once"), ("other/SOUL.md", "<write to SOUL.md>", "deny"),
    ("SOUL.md", "rm SOUL.md", "deny"), ("AGENTS.md", "<write to AGENTS.md>", "deny"),
])
def test_approval_requires_exact_lab_path(observer, monkeypatch, path, command, choice):
    tool_id = "write123"
    home = observer.out / "home"
    monkeypatch.setitem(sys.modules, "tools.approval_context", SimpleNamespace(_approval_tool_call_id=SimpleNamespace(get=lambda: tool_id)))
    monkeypatch.setitem(sys.modules, "tools.file_tools", SimpleNamespace(
        _collect_v4a_header_paths=None, _resolve_path_for_task=lambda path, task: home / Path(path)))
    observer.pre("write_file", {"path": path}, tool_call_id=tool_id)
    callback = observer.approval_callback(home)
    assert callback(command, "Write to protected agent-instruction file(s): SOUL.md.",
                    allow_permanent=False, allow_session=False) == choice
    assert observer.file_approvals == [{"step": 0, "tool": "write_file", "choice": choice}]
