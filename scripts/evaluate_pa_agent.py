#!/usr/bin/env python3
"""Bounded synthetic PA evaluation with an optional isolated Hermes run.

The default path exercises every fixture locally. ``--live`` adds at most ten
sequential Codex turns (one per recipe plus one baseline/candidate comparison)
using a temporary Hermes home and an in-memory token.
"""
from __future__ import annotations
import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# The PA package's existing venv supplies its declared calendar dependency.
# Keep this read-only bootstrap so --live uses Hermes' runtime interpreter
# without making the deterministic fixture arm depend on that venv's extras.
for site in sorted((Path(os.environ.get("PA_EVAL_VENV", ROOT / ".venv")).expanduser() / "lib").glob("python*/site-packages")):
    if str(site) not in sys.path:
        sys.path.insert(0, str(site))
DEFAULT_HERMES_PATH = Path(os.environ.get("HERMES_AGENT_PATH", Path.home() / ".hermes" / "hermes-agent")).expanduser()
EVAL_OUTPUT_ROOT = Path(os.environ.get("PA_EVAL_DIR", Path.home() / "Codex" / "personal-assistant" / "agent-eval")).expanduser()
BASELINE_COMMIT = "103d6ef"
EXPECTED_RUNTIME_HEAD = "98198a12bea152c055fbc4587d1016bcc5e5b618"
EXPECTED_MODEL = "gpt-5.6-sol"
SAFE_AGENT_TOOLS = frozenset({"pa", "skill_view", "pa_fixture_provider"})
EVAL_PATH = ROOT / "evals" / "pa-local-eva-v1.json"
R2_GUIDANCE_PATH = ROOT / "skills" / "personal-assistant" / "r2-travel-transaction" / "SKILL.md"
ICS = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:fixture-timed\r
DTSTART;TZID=Asia/Seoul:20260906T130000\r
DTEND;TZID=Asia/Seoul:20260906T140000\r
SUMMARY:Fixture meeting\r
LOCATION:Terminal 1\r
DESCRIPTION:Synthetic itinerary\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:fixture-day\r
DTSTART;VALUE=DATE:20260907\r
DTEND;VALUE=DATE:20260909\r
SUMMARY:Fixture travel\r
END:VEVENT\r
END:VCALENDAR\r
"""
ICS_CHANGED = ICS.replace(b"DTSTART;TZID=Asia/Seoul:20260906T130000", b"DTSTART;TZID=Asia/Seoul:20260906T150000").replace(b"DTEND;TZID=Asia/Seoul:20260906T140000", b"DTEND;TZID=Asia/Seoul:20260906T160000").replace(b"\r\nLOCATION:Terminal 1", b"")
def load_eval_spec() -> dict[str, Any]:
    data = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    if data.get("schema") != "pa-local-eva-v1":
        raise ValueError("unexpected PA eval schema")
    recipes = data.get("recipes")
    if not isinstance(recipes, list) or {r.get("id") for r in recipes} != {f"R{i}" for i in range(1, 9)}:
        raise ValueError("eval must contain R1 through R8")
    return data
class FixtureProvider:
    """Safe synthetic provider and automation callbacks; no external calls."""
    def __init__(self) -> None:
        self.provider_calls = 0
        self.automation_calls = 0

    def readback(self, outcome: str = "confirmed") -> dict[str, Any]:
        self.provider_calls += 1
        if outcome not in {"confirmed", "failed", "unknown"}:
            raise ValueError("invalid fixture outcome")
        return {"fixture": "provider", "status": outcome, "proof": "synthetic-proof" if outcome != "unknown" else None}

    def automation(self) -> dict[str, Any]:
        self.automation_calls += 1
        return {"fixture": "automation", "status": "suggested", "job_started": False}
def _dispatch(profile: Path, operation: str, data: dict[str, Any], operations: list[str]) -> Any:
    from personal_assistant.entry import dispatch

    operations.append(operation)
    return dispatch(profile, {"operation": operation, "data": data})
def _upsert(profile: Path, action_id: str, scenario: str, operations: list[str], *, status: str | None = None, fields: dict[str, Any] | None = None) -> Any:
    data: dict[str, Any] = {"action_id": action_id, "fields": {"scenario": scenario, "context": "fully supplied synthetic fixture", **(fields or {})}}
    if status:
        data["status"] = status
    return _dispatch(profile, "action_upsert", data, operations)
def _transaction(profile: Path, action_id: str, final_action: str, operations: list[str], fixture: FixtureProvider, *, outcome: str = "confirmed") -> Any:
    summary = {"provider": "synthetic-provider", "final_action": final_action, "total": "10 KRW"}
    _dispatch(profile, "action_prepare", {"action_id": action_id, "summary": summary}, operations)
    _dispatch(profile, "action_confirm", {"action_id": action_id, "summary": summary, "confirmation": "Confirm synthetic action"}, operations)
    _dispatch(profile, "action_claim", {"action_id": action_id, "summary": summary}, operations)
    reply = fixture.readback(outcome)
    operations.append("fixture_provider")
    return _dispatch(profile, "action_result", {"action_id": action_id, "outcome": reply["status"], "proof": reply["proof"]}, operations)
def _nontransaction(profile: Path, action_id: str, final_action: str, operations: list[str], fixture: FixtureProvider) -> Any:
    _upsert(profile, action_id, final_action, operations, fields={"stage": "prepared", "final_action": final_action})
    reply = fixture.readback()
    operations.append("fixture_provider")
    return _upsert(profile, action_id, final_action, operations, status=reply["status"], fields={"stage": "readback", "provider_status": reply["status"], "provider_proof": reply["proof"]})
def _run_case(profile: Path, recipe_id: str, name: str, fixture: FixtureProvider, input_path: Path) -> tuple[list[str], list[str]]:
    operations: list[str] = []
    checks: list[str] = []
    _dispatch(profile, "status", {}, operations)
    action_id = f"fixture-{recipe_id.lower()}-{name}"
    if recipe_id == "R1" and name == "trip_import":
        first = _dispatch(profile, "trip_import", {"trip_id": "fixture-trip", "ics_path": str(input_path), "title": "Synthetic trip"}, operations)
        replay = _dispatch(profile, "trip_import", {"trip_id": "fixture-trip", "ics_path": str(input_path), "title": "Synthetic trip"}, operations)
        _upsert(profile, action_id, name, operations)
        if first == replay and first["timed"] == 1 and first["all_day"] == 1:
            checks.append("timed_and_all_day_facts")
    elif recipe_id == "R1" and name == "trip_change":
        _dispatch(profile, "trip_import", {"trip_id": "fixture-change", "ics_path": str(input_path)}, operations)
        before = _dispatch(profile, "context", {"kind": "trip", "trip_id": "fixture-change"}, operations)
        _dispatch(profile, "trip_import", {"trip_id": "fixture-change", "ics_path": str(input_path), "source_notes": {"fixture-timed": ["departure changed"]}}, operations)
        changed_path = input_path.with_name("changed.ics")
        changed_path.write_bytes(ICS_CHANGED)
        _dispatch(profile, "trip_import", {"trip_id": "fixture-change", "ics_path": str(changed_path)}, operations)
        after = _dispatch(profile, "context", {"kind": "trip", "trip_id": "fixture-change"}, operations)
        old, new = before["events"][0], after["events"][0]
        _upsert(profile, action_id, name, operations)
        if new["start"] != old["start"] and new["location"] == "Terminal 1":
            checks.append("changed_start_and_retained_omitted_location")
    elif recipe_id == "R1" and name == "trip_export":
        _dispatch(profile, "trip_import", {"trip_id": "fixture-export", "ics_path": str(input_path)}, operations)
        export = _dispatch(profile, "export", {"trip_id": "fixture-export", "output_dir": str(profile / "export")}, operations)
        _upsert(profile, action_id, name, operations)
        calendar = Path(export["calendar"])
        reference = Path(export["reference"])
        calendar_text = calendar.read_text(encoding="utf-8") if calendar.is_file() else ""
        reference_text = reference.read_text(encoding="utf-8") if reference.is_file() else ""
        if (calendar.is_file() and reference.is_file() and "UID:fixture-timed" in calendar_text
                and "## Complete itinerary" in reference_text
                and not re.search(r"(?i)\\b(?:token|password|secret)\\b", calendar_text + reference_text)):
            checks.append("credential_free_export_files")
    elif recipe_id == "R2":
        _upsert(profile, action_id, name, operations)
        result = _transaction(profile, action_id, name, operations, fixture, outcome="unknown" if name == "confirmed_submit_recovery" else "confirmed")
        if name == "confirmed_submit_recovery":
            try:
                _dispatch(profile, "action_claim", {"action_id": action_id, "summary": {"provider": "synthetic-provider", "final_action": name, "total": "10 KRW"}}, operations)
            except ValueError:
                checks.append("unknown_submit_not_replayed")
            state = _dispatch(profile, "context", {"kind": "action", "action_id": action_id}, operations)
            stored = state["action"]
            if result["status"] == "unknown" and stored["status"] == "unknown":
                checks.append("unknown_status_preserved")
        elif (result["status"] == "confirmed"
              and result["fields"].get("provider_proof") == "synthetic-proof"
              and result["fields"].get("confirmation_action_id") == action_id):
            checks.append("confirmed_fixture_result")
    elif recipe_id == "R3":
        _upsert(profile, action_id, name, operations)
        result = _transaction(profile, action_id, name, operations, fixture)
        if (result["status"] == "confirmed" and result["fields"].get("provider_proof") == "synthetic-proof"
                and result["fields"].get("confirmation_action_id") == action_id):
            checks.append("confirmed_request_with_fixture_proof")
    elif recipe_id == "R4":
        result = _nontransaction(profile, action_id, name, operations, fixture)
        if (result["status"] == "confirmed" and result["fields"].get("stage") == "readback"
                and result["fields"].get("provider_proof") == "synthetic-proof"
                and "action_prepare" not in operations and "action_result" not in operations):
            checks.append("prepared_packet_readback")
    elif recipe_id == "R5" and name == "daily_brief":
        result = _nontransaction(profile, action_id, name, operations, fixture)
        if (result["status"] == "confirmed" and result["fields"].get("provider_status") == "confirmed"
                and "action_result" not in operations):
            checks.append("current_brief_receipt")
    elif recipe_id == "R5":
        automation_status = _dispatch(profile, "automations", {"action": "status"}, operations)
        suggestion = fixture.automation()
        operations.append("fixture_automation")
        stored = _upsert(profile, action_id, name, operations, status="suggested", fields={"automation_status": suggestion["status"], "job_started": suggestion["job_started"]})
        if (automation_status["install_enabled_jobs"] == 0 and suggestion["job_started"] is False
                and stored["status"] == "suggested"):
            checks.append("suggestion_without_started_job")
    elif recipe_id == "R6" and name == "inbox_review":
        stored = _upsert(profile, action_id, name, operations, fields={"scope": "accepted inbox", "next_action": "draft reply"})
        if stored["fields"].get("scope") == "accepted inbox" and stored["fields"].get("next_action") == "draft reply":
            checks.append("next_action_recorded")
    elif recipe_id == "R6":
        _upsert(profile, action_id, name, operations)
        result = _transaction(profile, action_id, name, operations, fixture)
        if result["status"] == "confirmed" and result["fields"].get("provider_proof") == "synthetic-proof":
            checks.append("confirmed_reply_fixture_result")
    elif recipe_id == "R7" and name == "receipt":
        result = _nontransaction(profile, action_id, name, operations, fixture)
        if (result["status"] == "confirmed" and result["fields"].get("provider_status") == "confirmed"
                and "action_result" not in operations):
            checks.append("receipt_reconciled")
    elif recipe_id == "R7":
        _upsert(profile, action_id, name, operations)
        result = _transaction(profile, action_id, name, operations, fixture)
        if result["status"] == "confirmed" and result["fields"].get("provider_proof") == "synthetic-proof":
            checks.append("confirmed_renewal_decision")
    elif recipe_id == "R8":
        _upsert(profile, action_id, name, operations)
        result = _transaction(profile, action_id, name, operations, fixture)
        if result["status"] == "confirmed" and result["fields"].get("provider_proof") == "synthetic-proof":
            checks.append("confirmed_service_or_order")
    else:
        raise ValueError(f"unhandled fixture {recipe_id}/{name}")
    return operations, checks
def run_deterministic_evaluation(spec: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = spec or load_eval_spec()
    rows: list[dict[str, Any]] = []
    fixture = FixtureProvider()
    with tempfile.TemporaryDirectory(prefix="pa-agent-eval-") as temporary:
        profile = Path(temporary)
        input_path = profile / "input.ics"
        input_path.write_bytes(ICS)
        for recipe in spec["recipes"]:
            for case in recipe["scenarios"]:
                started = time.monotonic()
                try:
                    operations, checks = _run_case(profile, recipe["id"], case["name"], fixture, input_path)
                    missing = sorted(set(case["expected"]["operations"]) - set(operations))
                    status = "PASS" if checks and not missing else "FAIL"
                    row = {"recipe": recipe["id"], "scenario": case["name"], "status": status, "operations": operations, "outcome_facts": checks, "checks": checks, "missing_expected_operations": missing, "questions": 0, "latency_ms": round((time.monotonic() - started) * 1000, 2)}
                except Exception as exc:
                    row = {"recipe": recipe["id"], "scenario": case["name"], "status": "FAIL", "operations": [], "outcome_facts": [], "checks": [], "missing_expected_operations": [], "questions": 0, "latency_ms": round((time.monotonic() - started) * 1000, 2), "failure_type": type(exc).__name__}
                rows.append(row)
    return {"status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL", "scenario_count": len(rows), "pass_count": sum(row["status"] == "PASS" for row in rows), "scenarios": rows, "fixture_callbacks": {"provider_readback": fixture.provider_calls, "automation_suggest": fixture.automation_calls}}
def _git_show(commit: str, path: str) -> str:
    # The public repository starts from a snapshot, so historical baselines are vendored.
    vendored = ROOT / "evals/baselines" / commit / path.replace("skills/", "").replace("/SKILL.md", "-SKILL.md")
    if vendored.is_file():
        return vendored.read_text(encoding="utf-8")
    result = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, text=True, capture_output=True, check=True)
    return result.stdout
def guidance_comparison() -> dict[str, Any]:
    candidate = (ROOT / "skills/personal-assistant/SKILL.md").read_text(encoding="utf-8")
    baseline = _git_show(BASELINE_COMMIT, "skills/travel-mode/SKILL.md")
    return {"baseline_commit": BASELINE_COMMIT, "baseline_sha256": hashlib.sha256(baseline.encode()).hexdigest(), "candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest(), "same_model": EXPECTED_MODEL, "same_inputs": True, "baseline_interface": "travel-mode/travel-ledger guidance", "candidate_interface": "personal-assistant entry guidance", "limitations": ["Only the current safe pa, skill_view, and synthetic fixture tools are exposed to both turns.", "The baseline text is evaluated as prompt guidance and is not mounted as its historical provider/browser tool environment.", "Equal model and prompt do not isolate the effects of the changed tool surface or provider integrations."], "baseline_chars": len(baseline), "candidate_chars": len(candidate)}
def _object_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _call_name(call: Any) -> str | None:
    function = _object_value(call, "function")
    return _object_value(function, "name") or _object_value(call, "name")


def _call_arguments(call: Any) -> dict[str, Any]:
    function = _object_value(call, "function")
    raw = _object_value(function, "arguments") or _object_value(call, "arguments") or {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            return decoded if isinstance(decoded, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _tool_invocations(messages: Any) -> list[dict[str, Any]]:
    """Return assistant-issued calls once; tool result messages are responses."""
    calls: list[dict[str, Any]] = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                name = _call_name(call)
                if name:
                    calls.append({"name": str(name), "arguments": _call_arguments(call)})
        elif message.get("type") == "function_call" and message.get("name"):
            calls.append({"name": str(message["name"]), "arguments": _call_arguments(message)})
    return calls


def _tool_names(messages: Any) -> list[str]:
    return [call["name"] for call in _tool_invocations(messages)]


def _pa_calls(messages: Any) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    for call in _tool_invocations(messages):
        if call["name"] != "pa":
            continue
        args = call["arguments"]
        operation = args.get("operation")
        data = args.get("data")
        if isinstance(operation, str):
            calls.append((operation, data if isinstance(data, dict) else {}))
    return calls


def turn_metrics(result: Any, callback_delta: int, started: float, outcome_facts: list[str] | None = None, missing_outcome_facts: list[str] | None = None, *, callback_before: int | None = None, callback_after: int | None = None, agent: Any = None) -> dict[str, Any]:
    result = result if isinstance(result, dict) else {}
    tools = _tool_names(result.get("messages"))
    final = result.get("final_response") if isinstance(result.get("final_response"), str) else ""
    questions = len(re.findall(r"\?", final))
    facts = list(outcome_facts or [])
    missing = sorted(set(missing_outcome_facts or []))
    api_completed = bool(result.get("completed"))
    api_ok = api_completed and not result.get("failed") and not questions and set(tools) <= SAFE_AGENT_TOOLS
    task_outcome_status = "PASS" if not missing else "FAIL"
    def metric(name: str) -> int:
        value = result.get(name)
        if value is None and agent is not None:
            value = getattr(agent, f"session_{name}", 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
    return {"status": "PASS" if api_ok and task_outcome_status == "PASS" else "FAIL", "api_completed": api_completed, "task_outcome_status": task_outcome_status, "task_outcome_facts": facts, "missing_outcome_facts": missing, "observed_tools": tools, "tool_call_count": len(tools), "callback_delta": int(callback_after - callback_before) if callback_before is not None and callback_after is not None else int(callback_delta), "callback_before": callback_before, "callback_after": callback_after, "questions": questions, "final_response_chars": len(final), "latency_ms": round((time.monotonic() - started) * 1000, 2), "completed": api_completed, "failed": bool(result.get("failed")), "input_tokens": metric("input_tokens"), "output_tokens": metric("output_tokens"), "total_tokens": metric("total_tokens")}
@contextlib.contextmanager
def _isolated_runtime(repo: Path, hermes: Path, token: str) -> Iterator[tuple[Any, Any, Any, FixtureProvider]]:
    original_home = os.environ.get("HERMES_HOME")
    original_db = os.environ.get("TRAVEL_LEDGER_DB")
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="pa-agent-hermes-") as temporary:
        home = Path(temporary)
        (home / "fixture.ics").write_bytes(ICS)
        (home / "plugins").mkdir()
        (home / "plugins" / "personal-assistant").symlink_to(repo, target_is_directory=True)
        (home / "config.yaml").write_text("plugins:\n  enabled: [personal-assistant]\ntools:\n  tool_search: false\n", encoding="utf-8")
        os.environ["HERMES_HOME"] = str(home)
        os.environ.pop("TRAVEL_LEDGER_DB", None)
        os.chdir(home)
        for site in sorted((hermes / "venv" / "lib").glob("python*/site-packages")):
            if str(site) not in sys.path:
                sys.path.insert(0, str(site))
        if str(hermes) not in sys.path:
            sys.path.insert(0, str(hermes))
        from hermes_constants import hermes_home_key, reset_hermes_home_override, set_hermes_home_override
        from hermes_cli.plugins import PluginManager
        from tools.registry import registry
        from toolsets import TOOLSETS
        home_token = set_hermes_home_override(str(home))
        scope = hermes_home_key(str(home))
        previous_skill_toolset = TOOLSETS.get("pa_eval_skills")
        TOOLSETS["pa_eval_skills"] = {"description": "Bounded skill read", "tools": ["skill_view"], "includes": []}
        try:
            manager = PluginManager(scope_key=scope)
            manager.discover_and_load()
            loaded = manager._plugins.get("personal-assistant")
            if not loaded or not loaded.enabled or loaded.error:
                raise RuntimeError("personal-assistant plugin did not load")
            fixture = FixtureProvider()
            schema = {"name": "pa_fixture_provider", "parameters": {"type": "object", "properties": {"operation": {"type": "string", "enum": ["provider_readback", "automation_suggest"]}, "outcome": {"type": "string", "enum": ["confirmed", "failed", "unknown"]}}, "required": ["operation"]}}
            def handle(args: dict[str, Any], **_: Any) -> str:
                if args.get("operation") == "automation_suggest":
                    return json.dumps(fixture.automation())
                return json.dumps(fixture.readback(str(args.get("outcome") or "confirmed")))
            registry.register(name="pa_fixture_provider", toolset="pa_fixture", schema=schema, handler=handle, scope=scope, description="Synthetic provider readback; never contacts a real provider.")
            try:
                yield home, manager, registry, fixture
            finally:
                try:
                    manager.unload("personal-assistant")
                except Exception:
                    pass
        finally:
            if previous_skill_toolset is None:
                TOOLSETS.pop("pa_eval_skills", None)
            else:
                TOOLSETS["pa_eval_skills"] = previous_skill_toolset
            reset_hermes_home_override(home_token)
    if original_home is None:
        os.environ.pop("HERMES_HOME", None)
    else:
        os.environ["HERMES_HOME"] = original_home
    if original_db is None:
        os.environ.pop("TRAVEL_LEDGER_DB", None)
    else:
        os.environ["TRAVEL_LEDGER_DB"] = original_db
    os.chdir(original_cwd)


BOOKING_ACTION_ID = "live-r2-booking"
BOOKING_CONFIRMATION = "Confirm booking synthetic-airline SFO-ICN on 2026-09-20 total 10 KRW."
RETURN_ACTION_ID = "live-r3-return"
RETURN_CONFIRMATION = "Confirm return synthetic-store order-77 black suitcase by 2026-09-30."
RENEWAL_ACTION_ID = "live-r7-renewal"
RENEWAL_CONFIRMATION = "Confirm renewal synthetic-cloud monthly at 10 KRW."


def _recipe_prompts(home: Path) -> list[dict[str, Any]]:
    ics_path = home / "fixture.ics"
    export_dir = home / "exports-r1"
    bundles = [
        {"recipes": ["R1", "R4", "R5"], "required_facts": ["R1_import_export_inputs", "R4_conflict_readback", "R5_brief_and_automation"], "prompt": f"Exercise R1, R4, and R5 with the exact synthetic facts below. All inputs are complete; ask zero questions. Start with pa.status, then pa.recipes for each listed recipe. R1: import trip_id live-trip from the local ICS file {ics_path}, whose synthetic facts are route SFO-ICN, timed event UID fixture-timed, and all-day travel on 2026-09-07; then export trip_id live-trip as credential-free ICS and reference files to {export_dir}. R4: record action_id live-r4-conflict with timezone Asia/Seoul, overlapping events fixture-A 2026-09-06 13:00-14:00 and fixture-B 2026-09-06 13:30-14:30, conflict overlap, and next_action choose non-conflicting slot. R5: record action_id live-r5-brief with timezone UTC, sources calendar and tasks, and next_action review current brief; call pa automations with action status and the synthetic fixture automation_suggest callback. Use action_upsert for R4 and R5 preparation/readback; never use action_prepare or action_result for these nontransaction records. Use pa_fixture_provider only for deterministic synthetic readback after recording the stage; it does not contact a provider. Never send, invite, purchase, install, or change a real calendar. Return one concise outcome sentence."},
        {"recipes": ["R2"], "required_facts": ["R2_exact_booking_lifecycle"], "prompt": f"Exercise R2 booking with these fully supplied synthetic details and no questions: action_id {BOOKING_ACTION_ID}; provider synthetic-airline; route SFO-ICN; date 2026-09-20; total 10 KRW; submit label Book. Start with pa.status and pa.recipes recipe_id R2. Use action_upsert to record the action, then action_prepare, action_confirm with exactly this confirmation text: {BOOKING_CONFIRMATION} Then action_claim, call pa_fixture_provider operation provider_readback with outcome confirmed, and record its deterministic proof with action_result. Do not invent any provider receipt and do not contact an airline. Return one concise outcome sentence."},
        {"recipes": ["R3", "R6"], "required_facts": ["R3_return_deadline_lifecycle", "R6_selected_draft"], "prompt": f"Exercise R3 and R6 with complete synthetic inputs; ask zero questions. Start with pa.status, then pa.recipes for R3 and R6. R3 is a return: action_id {RETURN_ACTION_ID}, provider synthetic-store, order-77, item black suitcase, deadline 2026-09-30. Prepare the exact scope, confirm with exactly: {RETURN_CONFIRMATION} Then claim, call pa_fixture_provider provider_readback with outcome confirmed, and record only its returned deterministic proof. R6 is selected-inbox draft only: action_id live-r6-draft, accepted scope inbox:travel, recipient alex@example.invalid, body Draft only: confirm the synthetic itinerary. Use action_upsert for this draft and do not prepare, confirm, claim, result, or send it. Never contact a real provider or recipient. Return one concise outcome sentence."},
        {"recipes": ["R7", "R8"], "required_facts": ["R7_receipt_and_renewal_lifecycle", "R8_shopping_comparison"], "prompt": f"Exercise R7 and R8 with fully supplied synthetic inputs and no questions. Start with pa.status, then pa.recipes for R7 and R8. R7 receipt: action_id live-r7-receipt, service synthetic-cloud, receipt_id receipt-42, amount 10 KRW; store the receipt reconciliation with action_upsert. R7 renewal: action_id {RENEWAL_ACTION_ID}, provider synthetic-cloud, term monthly, total 10 KRW; prepare and confirm with exactly: {RENEWAL_CONFIRMATION} Then claim, call pa_fixture_provider provider_readback outcome confirmed, and record its deterministic proof with action_result. R8 shopping comparison only: action_id live-r8-shopping, item synthetic-laptop, budget 100 KRW, options option-a and option-b, selected option-a; record the comparison with action_upsert and do not purchase or use transaction lifecycle operations for it. Never contact a real service. Return one concise outcome sentence."},
    ]
    summaries = {
        1: {"provider": "synthetic-airline", "final_action": "book", "route": "SFO-ICN", "date": "2026-09-20", "total": "10 KRW", "terms": "fully refundable synthetic booking", "submit_label": "Book"},
        2: {"provider": "synthetic-store", "final_action": "return", "item": "black suitcase", "deadline": "2026-09-30", "total": "0 KRW", "terms": "return accepted by deadline", "submit_label": "Request return"},
        3: {"provider": "synthetic-cloud", "final_action": "renew", "term": "monthly", "total": "10 KRW", "terms": "monthly renewal; no other fees", "submit_label": "Renew"},
    }
    for index, summary in summaries.items():
        bundles[index]["prompt"] += " Use this exact material summary JSON for prepare, confirm, and claim: " + json.dumps(summary) + "."
    return bundles



def _bundle_outcome_facts(bundle: dict[str, Any], messages: Any, home: Path, callback_delta: int) -> tuple[list[str], list[str]]:
    """Score committed state and exported bytes, not intended tool arguments."""
    from personal_assistant.state import Ledger
    from icalendar import Calendar
    ledger = Ledger(home)
    calls = _pa_calls(messages)
    facts = []
    recipes = set(bundle["recipes"])
    if all(any(op == "recipes" and data.get("recipe_id") == rid for op, data in calls) for rid in recipes):
        facts.append("recipe_catalog_calls")
    def fields(identity):
        record = ledger.get("action", identity)
        return record["fields"] if record else {}
    def has_values(identity, values):
        serialized = json.dumps(fields(identity), ensure_ascii=False)
        return all(value in serialized for value in values)
    def contains(actual, expected):
        return all(actual.get(key) == value for key, value in expected.items())
    def transaction(identity, expected, confirmation):
        record = ledger.get("action", identity)
        return bool(record and record["status"] == "confirmed" and callback_delta > 0
                    and contains(record["fields"].get("material_summary", {}), expected)
                    and record["fields"].get("confirmation_text") == confirmation
                    and "synthetic-proof" in json.dumps(record["fields"].get("provider_proof")))
    if "R1" in recipes:
        trip = ledger.get("trip", "live-trip")
        calendar = home / "exports-r1" / "Trip.ics"
        reference = home / "exports-r1" / "Trip-Reference.md"
        if trip and calendar.is_file() and reference.is_file():
            events = Calendar.from_ical(calendar.read_bytes()).walk("VEVENT")
            if {str(e["UID"]) for e in events} == {"fixture-timed", "fixture-day"}:
                facts.append("R1_import_export_inputs")
    if "R4" in recipes and contains(fields("live-r4-conflict"), {"conflict": "overlap", "next_action": "choose non-conflicting slot", "timezone": "Asia/Seoul"}):
        facts.append("R4_conflict_readback")
    if "R5" in recipes and contains(fields("live-r5-brief"), {"timezone": "UTC", "sources": ["calendar", "tasks"]}) and callback_delta > 0 and any(op == "automations" for op, _ in calls):
        facts.append("R5_brief_and_automation")
    if "R2" in recipes and transaction(BOOKING_ACTION_ID, {"provider": "synthetic-airline", "route": "SFO-ICN", "date": "2026-09-20", "total": "10 KRW"}, BOOKING_CONFIRMATION):
        facts.append("R2_exact_booking_lifecycle")
    if "R3" in recipes and transaction(RETURN_ACTION_ID, {"provider": "synthetic-store", "item": "black suitcase", "deadline": "2026-09-30"}, RETURN_CONFIRMATION):
        facts.append("R3_return_deadline_lifecycle")
    if "R6" in recipes:
        draft = ledger.get("action", "live-r6-draft")
        if draft and draft["action_type"] != "transaction" and has_values("live-r6-draft", ["inbox:travel", "alex@example.invalid", "Draft only: confirm the synthetic itinerary."]):
            facts.append("R6_selected_draft")
    if "R7" in recipes and has_values("live-r7-receipt", ["synthetic-cloud", "receipt-42", "10 KRW"]) and transaction(RENEWAL_ACTION_ID, {"provider": "synthetic-cloud", "term": "monthly", "total": "10 KRW"}, RENEWAL_CONFIRMATION):
        facts.append("R7_receipt_and_renewal_lifecycle")
    if "R8" in recipes and has_values("live-r8-shopping", ["synthetic-laptop", "100 KRW", "option-a", "option-b"]) and fields("live-r8-shopping").get("selected") == "option-a":
        facts.append("R8_shopping_comparison")
    return facts, sorted(set(bundle["required_facts"]) - set(facts))


def run_live_agent_evaluation(hermes_path: str | Path, case: str | None = None) -> dict[str, Any]:
    hermes = Path(hermes_path).resolve()
    try:
        runtime_head = subprocess.run(["git", "-C", str(hermes), "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
    except Exception:
        return {"status": "ENVIRONMENT_BLOCKED", "reason": "runtime_head_unreadable"}
    if runtime_head != EXPECTED_RUNTIME_HEAD:
        return {"status": "ENVIRONMENT_BLOCKED", "reason": "runtime_head_mismatch", "observed_head": runtime_head}
    try:
        for site in sorted((hermes / "venv" / "lib").glob("python*/site-packages")):
            if str(site) not in sys.path:
                sys.path.insert(0, str(site))
        if str(hermes) not in sys.path:
            sys.path.insert(0, str(hermes))
        from hermes_cli.auth import _read_codex_tokens
        token = str(_read_codex_tokens()["tokens"]["access_token"])
        if not token:
            raise ValueError("empty token")
    except Exception as exc:
        return {"status": "ENVIRONMENT_BLOCKED", "reason": "codex_authorization_unavailable", "failure_type": type(exc).__name__}
    comparison = guidance_comparison()
    rows = []
    choices = {"travel": 0, "booking": 1, "returns_inbox": 2, "household": 3,
               "candidate": 1, "baseline": 1, "inbox": 2}
    if case is not None and case not in choices:
        raise ValueError("unknown bounded live case")
    for label in ([case] if case else choices):
        # Each turn gets identical empty state. No comparison arm inherits a
        # confirmed/uncertain transaction from another arm.
        try:
            with _isolated_runtime(ROOT, hermes, token) as (home, manager, registry, fixture):
                from model_tools import get_tool_definitions
                from run_agent import AIAgent
                allowed = ["personal_assistant", "pa_eval_skills", "pa_fixture"]
                definitions = get_tool_definitions(allowed, quiet_mode=True, skip_tool_search_assembly=True)
                assert {item["function"]["name"] for item in definitions} == SAFE_AGENT_TOOLS
                bundle = _recipe_prompts(home)[choices[label]]
                if label == "inbox":
                    bundle = {"recipes": ["R6"], "required_facts": ["R6_selected_draft"], "prompt": "Prepare and save the selected email draft using R6. All context is supplied: action_id live-r6-draft; accepted inbox scope inbox:travel; recipient alex@example.invalid; exact body: Draft only: confirm the synthetic itinerary. Recover status, load the recipe, and save this as a nontransaction draft. Do not send, use a transaction, or ask for already supplied details. Return one concise outcome sentence."}
                guidance = (_git_show(BASELINE_COMMIT, "skills/travel-mode/SKILL.md") if label == "baseline"
                            else (ROOT / "skills/personal-assistant/SKILL.md").read_text())
                agent = AIAgent(base_url="https://chatgpt.com/backend-api/codex", api_key=token,
                    provider="openai-codex", model=EXPECTED_MODEL, enabled_toolsets=allowed,
                    max_iterations=20, run_budget_seconds=120, quiet_mode=True,
                    skip_context_files=True, skip_memory=True, skip_background_review=True,
                    save_trajectories=False)
                started = time.monotonic()
                try:
                    result = agent.run_conversation(bundle["prompt"], system_message="Bounded synthetic PA evaluation. " + guidance)
                    messages = result.get("messages") if isinstance(result, dict) else []
                    callbacks = fixture.provider_calls + fixture.automation_calls
                    facts, missing = _bundle_outcome_facts(bundle, messages, home, callbacks)
                    errors = []
                    for message in messages or []:
                        if isinstance(message, dict) and message.get("role") == "tool":
                            try:
                                payload = json.loads(message.get("content", "{}"))
                            except (TypeError, ValueError):
                                continue
                            if isinstance(payload, dict) and payload.get("error"):
                                from personal_assistant.privacy import safe_text
                                errors.append(safe_text(str(payload["error"]))[:240])
                    from personal_assistant.state import Ledger
                    shape = [{"action_id": item["action_id"], "status": item["status"], "field_names": sorted(item["fields"])} for item in Ledger(home).list("action")]
                    row = {"stored_record_shapes": shape, "case": label, "recipes": bundle["recipes"], "tool_errors": errors,
                        **turn_metrics(result, callbacks, started, facts, missing, callback_before=0,
                                       callback_after=callbacks, agent=agent)}
                    if label in {"candidate", "baseline"}:
                        row["comparison_arm"] = label
                    rows.append(row)
                finally:
                    agent.close()
        except Exception as exc:
            rows.append({"case": label, "status": "ENVIRONMENT_BLOCKED", "failure_type": type(exc).__name__})
    end_head = subprocess.run(["git", "-C", str(hermes), "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
    return {"status": "PASS" if rows and all(row["status"] == "PASS" for row in rows) and end_head == runtime_head else "FAIL",
            "runtime_head": runtime_head, "runtime_head_after": end_head, "model": EXPECTED_MODEL,
            "tool_surface": sorted(SAFE_AGENT_TOOLS), "turn_count": len(rows), "turns": rows,
            "comparison": comparison, "isolation": "fresh native profile per turn"}


def build_report(hermes_path: str | Path | None = None, live: bool = False, case: str | None = None) -> dict[str, Any]:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    report: dict[str, Any] = {"schema": "pa-agent-eval-v1", "claim_class": "advisory", "status": "PASS", "source": {"pwd": str(ROOT), "head": head}, "runtime": {"expected_head": EXPECTED_RUNTIME_HEAD, "status": "NOT_RUN"}, "model": EXPECTED_MODEL, "deterministic": run_deterministic_evaluation(), "comparison": guidance_comparison(), "claim_boundary": load_eval_spec()["claim_boundary"]}
    if live:
        report["live_agent"] = run_live_agent_evaluation(hermes_path or DEFAULT_HERMES_PATH, case=case)
        report["runtime"]["status"] = report["live_agent"].get("status", "UNKNOWN")
    report["status"] = "PASS" if report["deterministic"]["status"] == "PASS" and (not live or report["live_agent"]["status"] == "PASS") else report["deterministic"]["status"] if not live else report["live_agent"]["status"]
    return report


def write_artifact(report: dict[str, Any], target: str | Path) -> Path:
    root = EVAL_OUTPUT_ROOT.resolve()
    path = Path(target).expanduser().resolve()
    if root not in path.parents or path.exists():
        raise ValueError("artifact must be a new file inside the approved eval directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes", default=str(DEFAULT_HERMES_PATH))
    parser.add_argument("--live", action="store_true", help="run bounded isolated Hermes turns")
    parser.add_argument("--case", choices=["travel", "booking", "returns_inbox", "household", "candidate", "baseline", "inbox"], help="one live case per local invocation")
    parser.add_argument("--output", help="new aggregate JSON artifact inside PA_EVAL_DIR (default: ~/Codex/personal-assistant/agent-eval)")
    args = parser.parse_args()
    report = build_report(args.hermes, args.live, case=args.case)
    if args.output:
        write_artifact(report, args.output)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
