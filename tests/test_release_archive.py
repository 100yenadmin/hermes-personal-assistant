"""Exercise the shipped bytes, including the native registration module."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace


def test_built_archive_registers_and_exports(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["bash", str(root / "scripts/package_release.sh"),
                    "--output-dir", str(tmp_path / "dist")], check=True, capture_output=True)
    archive = next((tmp_path / "dist").glob("*.tgz"))
    with tarfile.open(archive) as source:
        names = source.getnames()
        assert not any("/tests/" in f"/{name}" for name in names)
        source.extractall(tmp_path / "unpacked", filter="data")
    package = next((tmp_path / "unpacked").iterdir())
    assert (package / "__init__.py").is_file()
    assert (package / "config/pa-action-gateway-policy.example.json").is_file()
    for relative in ("scripts/pa_observe.py", "personal_assistant/observe.py", "personal_assistant/observe_sources.py"):
        assert (package / relative).is_file()
    assert (package / "scripts/pa_observe.py").stat().st_mode & 0o777 == 0o755  # HB2 runs it via the interpreter; keep the mode stable.
    spec = importlib.util.spec_from_file_location("pa_archive_test", package / "__init__.py",
                                                submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    tools, skills, hooks, commands = {}, {}, {}, {}
    home = tmp_path / "profile"
    home.mkdir()
    ctx = SimpleNamespace(_manager=SimpleNamespace(home_path=home),
                          register_tool=lambda **kw: tools.update({kw["name"]: kw}),
                          register_hook=lambda name, callback: hooks.update({name: callback}),
                          register_command=lambda name, handler, **kw: commands.update({name: handler}),
                          register_skill=lambda name, path, **kw: skills.update({name: path}))
    try:
        spec.loader.exec_module(module)
        module.register(ctx)
        assert {"pa", "pa_call"} <= tools.keys()
        assert {"personal-assistant", "phone-calls", "answering-calls"} <= skills.keys()
        assert (package / "personal_assistant/calls.py").is_file()
        assert (package / "evals/call_sim/server.py").is_file()
        assert (package / "evals/call_sim/voice_check.py").is_file()
        assert (package / "skills/phone-calls/references/phrases.md").is_file()
        assert len(list((package / "evals/call_sim/personas").glob("*.yaml"))) == 5
        prepared = json.loads(tools["pa_call"]["handler"]({
            "action": "prepare", "purpose": "Ask about arrival", "language": "ja",
            "to": {"name": "Synthetic inn"}, "may_share": [], "limits": {}}))
        assert prepared["status"] == "prepared"
        assert "pre_tool_call" in hooks
        assert "pre_llm_call" in hooks and "pa" in commands
        decision = hooks["pre_tool_call"](
            "mcp__evaos_pipedream_future__create_widget", {"name": "synthetic"}
        )
        assert decision is None
        for path in skills.values():
            assert path.is_file() and path.is_relative_to(package)
            text = path.read_text()
            if "Every `references/...` path" in text:
                assert (path.parent / "references").is_dir()
        call = lambda op, data={}: json.loads(tools["pa"]["handler"]({"operation": op, "data": data}))
        assert len(call("recipes")) == 8
        calendar = home / "input.ics"
        calendar.write_text("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:archive-event\n"
                            "DTSTART;VALUE=DATE:20260908\nDTEND;VALUE=DATE:20260909\n"
                            "SUMMARY:Archive check\nEND:VEVENT\nEND:VCALENDAR\n")
        assert call("trip_import", {"trip_id": "archive", "ics_path": str(calendar)})["all_day"] == 1
        result = call("export", {"trip_id": "archive", "output_dir": str(home / "exports")})
        assert "UID:archive-event" in Path(result["calendar"]).read_text()
        assert Path(result["reference"]).is_file()
    finally:
        for name in list(sys.modules):
            if name == spec.name or name.startswith(spec.name + "."):
                sys.modules.pop(name, None)
