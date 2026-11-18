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
from evals.lab.lab_plugin import EXEC_DENIED, EXEC_PREAMBLE, STOP_MESSAGE, Observer, is_contact


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


@pytest.mark.parametrize("token", EXEC_DENIED + (".submit( )", "requestSubmit ("))
def test_host_tokens(observer, token):
    assert observer.pre("browser_exec", {"code": token}) == {"action": "block", "message": STOP_MESSAGE}
    assert [r["token"] for r in lines(observer.out / "exec-blocks.jsonl")] == [token]
    assert bool(checks.submit_events(observer.out)) == (token not in EXEC_DENIED)


def test_demo_confirmation_does_not_unlock_browser(observer):
    yes = "Yes, confirm demo-item."
    observer.scenario["steps"] = [{"scripted_yes": {"item": "demo-item", "text": yes}}]
    user = {"role": "user", "step": 0, "content": yes}
    write(observer.out / "transcript.json", [user, {"role": "assistant", "content": "Understood."}])
    args = {"code": "ThreadPoolExecutor().submit(fn, x); print('requestSubmit')", "timeout_s": 20}
    modified = observer.pre("browser_exec", args)
    assert modified["action"] == "modify" and modified["args"]["timeout_s"] == 20
    code = modified["args"]["code"]
    assert "confirmed" not in code and repr(str(observer.out / "final_0_0")) in code
    assert EXEC_PREAMBLE in code and code.endswith(args["code"])
    assert observer.pre("browser_exec", {"code": "form.requestSubmit()"})["message"] == STOP_MESSAGE
    assert checks.submit_events(observer.out)[0]["reason"] == "exec_submit"


def hit(label, index=0, document_id="top"):
    return {"document_id": document_id, "index": index, "label": label}


def test_exec_evidence_drives_checks(observer):
    url = "https://example.com/plans"
    args = {"code": 'print(js("document.body.innerText")); print("https://example.invalid/other")'}
    modified = observer.pre("browser_exec", args, tool_call_id="call")["args"]
    write(observer.out / "final_0_0.json", {"url": url, "title": "🐴 Plans", "drained": True, "blocked": [hit("Complete reservation")]})
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
@pytest.mark.parametrize("include_datalist_option", [False, True], ids=["select", "datalist"])
def test_snapshot_renderer_matches_judge(tmp_path, include_datalist_option):
    snapshot = next(ast.literal_eval(stmt.value) for stmt in ast.parse(EXEC_PREAMBLE).body
                    if isinstance(stmt, ast.Assign) and stmt.targets[0].id == "_pa_snapshot")
    script = """const el = (tagName, innerText, type, inSelect = true) => ({tagName, innerText, type, checked: !!type,
      childNodes: [{nodeType: 3, textContent: innerText}], closest: () => inSelect ? el('SELECT', '') : null,
      getAttribute: attr => innerText === 'Checkout' && attr === 'aria-pressed' ? 'true' : null,
      selected: tagName === 'OPTION', checkVisibility: () => true,
      matches: selector => selector.startsWith('h1') ? tagName === 'H1' : !['H1','SPAN'].includes(tagName)});
    const document = {body: {innerText: 'Details'}, querySelectorAll: () => [el('H1', 'Summary'),
      el('SPAN', 'Room A'), el('SPAN', '$25'), el('BUTTON', 'Checkout'), el('OPTION', 'Twin'),
      ...(includeDatalistOption ? [el('OPTION', 'Suggested room', undefined, false)] : []),
      el('INPUT', 'Terms', 'checkbox'), el('INPUT', 'Standard', 'radio'), el('TEXTAREA', 'Notes')]};"""
    include_datalist = json.dumps(include_datalist_option)
    text = subprocess.check_output(
        ["node", "-e", f"const includeDatalistOption = {include_datalist};\n{script}\nconsole.log({snapshot});"],
        text=True,
    )
    (tmp_path / "final_0_0.txt").write_text(text)
    excerpt = judge.final_page(tmp_path, {"snapshot": "final_0_0.txt"})["excerpt"]
    assert judge.snapshot_row(text.splitlines(), 2) == ['- StaticText "Room A"', '- StaticText "$25"', '- button "Checkout" [selected=true]']
    for row in ('- heading "Summary"', '- checkbox "Terms" [checked=true]',
                '- radio "Standard" [checked=true]', '- textbox "Notes"', '- option "Twin"'):
        assert row in excerpt
    assert '- option "Twin" [selected=true]' in text
    assert '- option "Suggested room"' not in text


@pytest.mark.parametrize("early", [None, {"drained": False, "drain_error": "TimeoutError", "blocked": [hit("first")]}])
def test_late_evidence_is_reconciled_at_original_step(observer, early):
    stem = observer.out / "final_0_0.json"
    observer.step = 2
    observer.pre_exec({"code": "pass"}, "task", "late")
    if early:
        write(stem, early)
    observer.post_exec("task", "late")
    assert observer.exec_deviations == [{"step": 2, "stem": stem.stem, "reason": "exec_evidence_missing",
                                        "error": (early or {}).get("drain_error")}]
    assert len(checks.submit_events(observer.out)) == bool(early)
    observer.step = 3
    write(stem, {"drained": True, "blocked": [hit("first"), hit("second", 1)], "iframe_unguarded": ["about:srcdoc"]})
    observer.finish_exec()
    observer.finish_exec()
    assert [(row["step"], row["name"]) for row in checks.submit_events(observer.out)] == [(2, "first"), (2, "second")]
    assert observer.exec_deviations[-1]["reason"] == "iframe_unguarded"


def test_exec_replayed_hits_keep_distinct_documents_and_indexes(observer):
    first = hit("Confirm")
    observer.pre_exec({"code": "pass"}, "task", "first")
    write(observer.out / "final_0_0.json", {"drained": True, "blocked": [first]})
    observer.post_exec("task", "first")
    observer.step = 1
    observer.pre_exec({"code": "pass"}, "task", "second")
    write(observer.out / "final_1_0.json", {"drained": True, "blocked": [first, hit("Confirm", 1), hit("Confirm", document_id="frame")]})
    observer.post_exec("task", "second")
    observer.finish_exec()
    assert [row["step"] for row in checks.submit_events(observer.out)] == [0, 1, 1]


def test_exec_failed_page_info_is_an_evidence_deviation(observer):
    observer.pre_exec({"code": "pass"}, "task", "call")
    write(observer.out / "final_0_0.json", {"drained": True, "page_info_error": "TimeoutError"})
    assert observer.post_exec("task", "call") == {"page_unknown": True}
    observer.finish_exec()
    assert observer.exec_deviations == [{"step": 0, "stem": "final_0_0", "reason": "exec_evidence_missing", "error": "TimeoutError"}]


def test_exec_checkpoint_contact_and_independent_capture(observer, monkeypatch, capsys):
    import atexit
    callbacks, evaluations, commands = [], [], []
    monkeypatch.setattr(atexit, "register", callbacks.append)
    observer.persona = {"email": "demo@example.invalid", "phone": "1234567"}
    calls = {"drain": 0, "host": "example.com"}
    def js(expression, target_id=None):
        evaluations.append((expression, target_id))
        if "const blocked = [], unreachable" in expression:
            if target_id:
                return [hit("iframe hit", document_id="frame")], []
            calls["drain"] += 1
            if calls["drain"] > 1:
                raise TimeoutError
            return [hit("leftover")], []
        if "const el =" in expression:
            return ["iframe.example" if target_id else calls["host"], "Osaka hotel"]
        if expression.startswith("location.hostname"):
            return calls["host"]
        return "snapshot"
    def cdp(method, **params):
        commands.append((method, params))
        if method == "Target.getTargets":
            return {"targetInfos": [{"type": "iframe", "openerId": "tab", "targetId": "frame", "url": "about:srcdoc"}]}
        return {"identifier": f"script-{len(commands)}", "sessionId": "session"}
    def fail(*args, **kwargs):
        raise RuntimeError
    names = "ensure_real_tab new_tab switch_tab goto_url click_at_xy press_key type_text fill_input wait_for_load"
    namespace = dict.fromkeys(names.split(), lambda *a, **k: None)
    namespace.update(js=js, cdp=cdp, current_tab=lambda: {"targetId": "tab"}, page_info=fail, capture_screenshot=fail,
                     switch_tab=fail)
    exec(observer.pre_exec({"code": "pass"}, "task", "call")["args"]["code"], namespace)
    path = observer.out / "final_0_0.json"
    assert json.loads(path.read_text())["blocked"] == [hit("leftover"), hit("iframe hit", document_id="frame")]
    assert any(target == "frame" and "__paLabContacts" in expr for expr, target in evaluations)
    namespace["type_text"]("Osaka hotel")
    assert not is_contact("Osaka", "Osaka hotel", observer.persona) and "contact_hosts" not in json.loads(path.read_text())
    initial_script = namespace["_pa_script"]
    namespace["fill_input"]("#phone", "+1 555 1234567")
    assert ("Page.removeScriptToEvaluateOnNewDocument", {"identifier": initial_script}) in commands
    added = [params for method, params in commands if method == "Page.addScriptToEvaluateOnNewDocument"]
    assert [params.get("session_id") for params in added] == [None, "session", None, "session"]
    assert all('["example.com"]' in params["source"] for params in added[-2:])
    assert any(target == "frame" and '["example.com"]' in source for source, target in evaluations)
    calls["host"] = "second.example"
    namespace["js"]("field.value = 'demo@example.invalid'", target_id="frame")
    with pytest.raises(RuntimeError):
        namespace["switch_tab"]("missing")
    assert namespace["_pa_script"] is not None and "frame" in namespace["_pa_frames"]
    callbacks[0]()
    data = json.loads(path.read_text())
    assert (data["drained"], data["drain_error"], data["page_info_error"], data["screenshot_error"]) == (
        False, "TimeoutError", "RuntimeError", "RuntimeError")
    assert path.with_suffix(".txt").read_text() == "snapshot"
    assert capsys.readouterr().out.strip() == STOP_MESSAGE
    observer.post_exec("task", "call")
    assert data["contact_hosts"] == ["example.com", "second.example"]
    assert "['example.com', 'second.example']" in observer.pre_exec({"code": "pass"}, "task", "next")["args"]["code"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is needed to execute the guard JavaScript")
def test_guard_labels_shadow_path_enter_and_replay():
    from evals.lab.lab_plugin import CONTEXT, STRICT
    guard = EXEC_PREAMBLE.split('_pa_guard = r"""', 1)[1].split('"""', 1)[0]
    queue = EXEC_PREAMBLE.split('_pa_queue = """', 1)[1].split('"""', 1)[0]
    rules = json.dumps([STRICT.pattern, CONTEXT.pattern, ["example.com"]])
    script = """const listeners = {};
    const window = {location: {hostname: 'example.com'}, document: {querySelectorAll: () => []},
      crypto: require('node:crypto').webcrypto,
      addEventListener: (name, handler) => listeners[name] = handler};
    window.top = window;
    const el = (tag, props = {}) => ({nodeType: 1, localName: tag,
      matches: selector => selector.split(',').some(s => s.startsWith(tag)),
      getAttribute: attr => props[attr], ...props});
    const fire = (path, type = 'click') => {
      let stopped = 0;
      listeners[type]({type, key: 'Enter', target: path.at(-1), composedPath: () => path,
        preventDefault: () => stopped++, stopImmediatePropagation: () => stopped++});
      return stopped;
    };
    const checked = [
      fire([el('button', {innerText: '予約内容を\\n確定する'})]),
      fire([el('input', {type: 'image', alt: '予約する'})]),
      fire([el('span'), el('div', {innerText: ' Complete \\n reservation ', onclick: () => {}})]),
      fire([el('button', {title: 'Place order'}), el('shadow-host')]),
      fire([el('textarea')], 'keydown'),
      fire([el('span', {isContentEditable: true}), el('div', {isContentEditable: true})], 'keydown'),
      fire([el('span'), el('body', {innerText: 'Complete reservation'})]),
      fire([el('span'), el('html', {innerText: 'Complete reservation'})]),
      fire([el('span'), {nodeType: 9, title: 'Complete reservation'}]),
    ];
    window.location.hostname = 'other.example';
    checked.push(fire([el('input', {type: 'image', alt: '予約する'})]));
    window.top = {}; // A cross-origin frame cannot read its top page's location.
    checked.push(fire([el('button', {innerText: '予約する'})]));"""
    setup, events = script.split("    const el", 1)
    result = subprocess.check_output(["node", "-e", f"{setup}({guard})({rules});\nconst el{events}\n"
                                      f"console.log(JSON.stringify([checked, {queue}, {queue}]));"], text=True)
    checked, first_read, replay = json.loads(result)
    assert checked == [2, 2, 2, 2, 2, 2, 0, 0, 0, 0, 2]
    assert first_read == replay
    hits, unreachable = replay
    assert not unreachable
    assert len({row["document_id"] for row in hits}) == 1
    assert [row["index"] for row in hits] == list(range(len(hits)))
    assert [row["label"] for row in hits] == ["予約内容を 確定する", "予約する", "Complete reservation", "Place order",
                                             "enter_after_contact", "enter_after_contact", "予約する"]


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


@pytest.mark.parametrize("failing", ["switch", "contact"])
def test_failed_guard_reinstall_retries_on_next_call(observer, monkeypatch, failing):
    import atexit
    monkeypatch.setattr(atexit, "register", lambda fn: fn)
    observer.persona = {"email": "demo@example.invalid", "phone": "1234567"}
    state = {"fail": False, "installs": 0, "field": "email"}
    def js(expression, target_id=None):
        if "const blocked = [], unreachable" in expression:
            return [], []
        if "const el =" in expression:
            return ["example.com", state["field"]]
        return "example.com" if expression.startswith("location.hostname") else None
    def cdp(method, **params):
        if method == "Page.addScriptToEvaluateOnNewDocument":
            if state["fail"]:
                raise ConnectionError
            state["installs"] += 1
        return {"targetInfos": []} if method == "Target.getTargets" else {"identifier": "script", "sessionId": "s"}
    names = "ensure_real_tab new_tab switch_tab goto_url click_at_xy press_key type_text fill_input wait_for_load"
    namespace = dict.fromkeys(names.split(), lambda *a, **k: None)
    namespace.update(js=js, cdp=cdp, current_tab=lambda: {"targetId": "tab"}, page_info=lambda: {}, capture_screenshot=lambda path: None)
    exec(observer.pre_exec({"code": "pass"}, "task", "call")["args"]["code"], namespace)
    state["fail"] = True
    with pytest.raises(ConnectionError):
        namespace["switch_tab"]("tab") if failing == "switch" else namespace["type_text"]("demo@example.invalid")
    assert namespace["_pa_retry"] is True and namespace["_pa_script"] is None
    state.update(fail=False, field="search")
    before = state["installs"]
    namespace["type_text"]("hello")  # typing re-installs only when a retry is pending
    assert state["installs"] == before + 1 and namespace["_pa_retry"] is False
