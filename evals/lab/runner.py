"""One OS process and disposable Hermes home per scenario repetition."""
import concurrent.futures
import hashlib
import importlib.util
import datetime as dt
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
import yaml
from . import common, checks, judge, sim_user
from .common import MODEL, read, write, append
from .scenario import load_catalog

ROOT = Path(__file__).resolve().parents[2]


def plan(catalog, selection="all", runs=1):
    if runs < 1:
        raise ValueError("runs: must be positive")
    return [{"run_id": f"{s['id']}__r{i:03d}", "scenario": s["id"], "index": i, "budget_seconds": s["budget_seconds"]}
            for s in (catalog.values() if selection == "all" else [catalog[selection]]) for i in range(1, runs + 1)]


def skip_reason(scenario, template):
    if scenario.get("requires") == "gateway":
        return "covered by concierge_e2e P3/P4"
    if "calls" in scenario and not (Path(template) / "home/.hermes/plugins/personal-assistant/evals/call_sim/server.py").exists():
        return "call_sim missing"


def execute(command, timeout, **kwargs):
    process = subprocess.Popen(command, start_new_session=True, **kwargs)
    try:
        return "ok" if process.wait(timeout=timeout) == 0 else "error"
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        return "timeout"


def wave(args):
    catalog = load_catalog(args.scenarios)
    jobs = plan(catalog, args.scenario, args.runs)
    soon = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    stale = sorted({j["scenario"] for j in jobs if str(catalog[j["scenario"]]["trip"]["depart_date"]) <= soon})
    if stale and not args.dry_run:
        raise ValueError("scenario catalog expired; move the trip dates forward: " + ", ".join(stale))
    if args.workers < 1:
        raise ValueError("workers: must be positive")
    if args.dry_run:
        return {"workers": args.workers, "jobs": jobs}
    if not args.hermes or not args.home_template or not args.out:
        raise ValueError("run: --hermes, --home-template and --out required")
    output, template = Path(args.out).resolve(), Path(args.home_template).resolve()
    try:
        token()  # Only to scrub child stderr; never written.
    except RuntimeError:
        pass
    output.mkdir(parents=True, exist_ok=True)
    def job(j):
        root = output / j["run_id"]
        root.mkdir(exist_ok=False)
        s = catalog[j["scenario"]]
        write(root / "scenario.json", s)
        meta = {**j, "start": time.time(), "model": MODEL, "status": "ok"}
        write(root / "run.json", meta)
        reason = skip_reason(s, template)
        if reason:
            write(root / "run.json", {**meta, "status": "skipped", "reason": reason, "end": time.time()})
            return j["run_id"]
        for name, value in (("transcript.json", []), ("ledger.json", {}), ("checks.json", {"all_pass": False}), ("judge.json", {"pass": False, "error": "not reached"}), ("cost.json", {"cost_usd": None})):
            write(root / name, value)
        for name in ("tools.jsonl", "tripwire.jsonl"):
            (root / name).touch()
        home = root / "home"
        try:
            shutil.copytree(template / "home", home, symlinks=True)
            write(root / "plugin-refs.json", read(template / "lab-home.json", {}))
            env = {**os.environ, "PYTHONPATH": str(ROOT) + os.pathsep + str(Path(args.hermes).resolve()),
                   "CODEX_HOME": os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
                   "PA_LAB_AUTH": os.environ.get("PA_LAB_AUTH") or str(Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json")}
            cmd = [args.python, "-m", "evals.lab", "run-one", "--hermes", str(Path(args.hermes).resolve()), "--out", str(root), "--judge", args.judge]
            with (root / "stderr.log").open("w") as err:
                status = execute(cmd, s["budget_seconds"] + 120, cwd=home, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err)
            log = root / "stderr.log"
            log.write_text(common.scrub(log.read_text(errors="replace")[-200000:]))
            meta = read(root / "run.json", meta)
            if status != "ok" and meta.get("status") != "timeout":  # Keep the child's own budget timeout.
                meta.update(status=status)
        except Exception as exc:
            meta.update(status="error", error=type(exc).__name__)
        finally:
            meta["end"] = time.time()
            write(root / "run.json", meta)
            if home.exists() and not args.keep_home:
                shutil.rmtree(home)
        return j["run_id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        return list(pool.map(job, jobs))


def token():
    path = Path(os.environ.get("PA_LAB_AUTH", str(Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json")))
    try:
        value = read(path, {}).get("tokens", {}).get("access_token")
        if not value:
            from hermes_cli.auth import _read_codex_tokens
            value = _read_codex_tokens().get("tokens", {}).get("access_token")
    except Exception:
        raise RuntimeError("existing model token unavailable") from None
    if not isinstance(value, str) or not value:
        raise RuntimeError("existing model token unavailable")
    common.SECRET = value
    return value


def hermes_head(hermes):
    """Commit of the Hermes tree: git when it is a checkout, else a sibling `<tree>.COMMIT` from an export."""
    try:
        return subprocess.check_output(["git", "-C", str(hermes), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        stamp = Path(str(hermes) + ".COMMIT")
        return stamp.read_text().strip() if stamp.is_file() else None


def user_view(transcript):
    """The simulated user's own history: its lines are assistant turns, the PA's lines are user turns."""
    swapped = [{"role": "assistant" if m["role"] == "user" else "user", "content": m["content"]} for m in transcript]
    return [{"role": "user", "content": "(The conversation starts; you wrote first.)"}] + swapped


# PA's own bookkeeping rows; its packets and call records ("pa:cancel:…", "pa:call:…") are errand work and still count.
HOUSEKEEPING = ("pa:setup", "pa:preferences", "pa:observe", "pa:trip-watch:", "pa:trip-facts:", "pa:calendar-binding",
                "pa:offer:", "pa:suggestion:")


def packet_booking(row):
    """The booking a packet is about, from its own structured summary (never from free text)."""
    try:
        summary = json.loads(row.get("fields_json") or "{}").get("material_summary")
    except (ValueError, AttributeError):
        return None
    return summary.get("booking_action_id") if isinstance(summary, dict) else None


# Tables an errand writes; the watcher's state-loop tables (pa_events, pa_projections, …) are not errand records.
ERRAND_TABLES = ("trips", "actions", "browser_checkpoints", "pa_action_authorizations", "pa_action_gateway_receipts")


def errand_rows(db):
    """Ledger rows that record errands, without PA's setup, watcher, offer and preference bookkeeping."""
    return {name: [r for r in db.get(name, []) if not str(r.get("action_id", "")).startswith(HOUSEKEEPING)]
            for name in ERRAND_TABLES}


def ledger(hh):
    path = hh / "state/travel-ledger/travel.sqlite"
    if not path.exists():
        return {}
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return {name: [dict(row) for row in db.execute('SELECT * FROM "' + name.replace('"', '""') + '"')]
                for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def one(args):
    root, hermes = Path(args.out).resolve(), Path(args.hermes).resolve()
    s, meta = read(root / "scenario.json"), read(root / "run.json")
    home, hh = root / "home", root / "home/.hermes"
    sys.path.insert(0, str(hermes))
    api_key = token()  # Before HOME changes; no refresh or auth writes.
    os.environ.update(HOME=str(home), HERMES_HOME=str(hh), PA_LAB_OUT=str(root), HERMES_DISABLE_LAZY_INSTALLS="1")
    os.environ.pop("TRAVEL_LEDGER_DB", None)
    os.environ.pop("HERMES_SAFE_MODE", None)
    os.chdir(home)
    from hermes_constants import set_hermes_home_override
    set_hermes_home_override(str(hh))
    calls, manager = None, None
    history, transcript, evidence, metrics, ledger_steps = [], [], [], [], set()
    approval_steps, approval_ids, approval_packets = set(), set(), []
    try:
        from .calls import Calls
        package = hh / "plugins/personal-assistant"
        config = yaml.safe_load((hh / "config.yaml").read_text())
        if "calls" in s:
            calls = Calls(package, sys.executable, s["calls"])
            url = calls.start()
            config["plugins"].setdefault("entries", {}).setdefault("personal-assistant", {}).setdefault("settings", {})["calls"] = {"transport": "sim", "sim_url": url}
        shutil.copytree(Path(__file__).parent / "lab_plugin", hh / "plugins/pa-capability-lab", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        config["plugins"]["enabled"].append("pa-capability-lab")
        (hh / "config.yaml").write_text(yaml.safe_dump(config))
        from hermes_cli import plugins as plugin_api
        from hermes_cli.plugins import PluginManager
        from tools.registry import registry
        from toolsets import TOOLSETS, resolve_toolset
        from run_agent import AIAgent
        manager = PluginManager(scope_key=str(hh))
        plugin_api._plugin_manager = manager  # Pinned Hermes embedding slot used by lifecycle hooks.
        manager.discover_and_load()
        assert registry.get_entry("pa", scope=str(hh)), "pa registration missing"
        if calls:
            assert registry.get_entry("pa_call", scope=str(hh)), "pa_call registration missing"
        observer = manager._plugins["pa-capability-lab"].module.observer
        # Import solely from the installed package, with an isolated namespace.
        spec = importlib.util.spec_from_file_location("lab_installed_pa", package / "personal_assistant/__init__.py", submodule_search_locations=[str(package / "personal_assistant")])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        from lab_installed_pa.entry import dispatch
        for seed in s.get("seed", []):
            dispatch(hh, seed)
        plugin_sets = {registry.get_entry(n, scope=str(hh)).toolset for p in manager._plugins.values() if p.enabled for n in p.tools_registered}
        allowed = sorted(plugin_sets | {n for n in ("browser", "skills", "todo", "vision", "web") if n in TOOLSETS})
        names = sorted({t for n in allowed for t in resolve_toolset(n)})
        forbidden = {"terminal", "file", "code_execution", "delegation", "cronjob", "send_message"}
        assert not forbidden.intersection(allowed), "forbidden toolset"
        blocked = {t for n in forbidden for t in resolve_toolset(n)}
        names = sorted(set(names) - blocked)
        # Restrict to the resolved surface, including any tools added by plugins.
        TOOLSETS["pa_lab_surface"] = {"description": "Lab allowed surface", "tools": names, "includes": []}
        meta.update(toolsets=allowed, tool_list=names, hermes_head=hermes_head(hermes), plugin_refs=read(root / "plugin-refs.json", {}))
        kwargs = dict(base_url="https://chatgpt.com/backend-api/codex", api_key=api_key, provider="openai-codex", model=MODEL, reasoning_config={"effort": "low"}, service_tier="", max_iterations=60, quiet_mode=True, skip_context_files=True, skip_memory=True, skip_background_review=True, save_trajectories=False)
        task_id = "pl" + hashlib.sha256(str(root).encode()).hexdigest()[:8]

        def turn(message, user=False, system="", hist=None):
            remaining = s["budget_seconds"] - (time.time() - meta["start"])
            if remaining <= 0:
                raise TimeoutError("dialogue budget exhausted")
            agent = AIAgent(**kwargs, enabled_toolsets=[] if user else ["pa_lab_surface"], run_budget_seconds=remaining)
            try:
                if user:
                    assert not agent.valid_tool_names, "sim user has tools"
                else:
                    assert set(agent.valid_tool_names) <= set(names), "unexpected tool exposure"
                    meta["tool_list"] = sorted(agent.valid_tool_names)
                # A short task id: Hermes names cloud-browser sockets after it, and a default 36-character UUID
                # overflows the 103-byte macOS socket path limit. One id per run also mirrors one gateway session.
                result = agent.run_conversation(message, conversation_history=hist or None, system_message=system,
                                                task_id=None if user else task_id)
                metrics.append({"agent": "sim_user" if user else "assistant", **{k: getattr(agent, k, 0) for k in ("session_input_tokens", "session_output_tokens", "session_total_tokens")}})
                return result
            finally:
                agent.close()
        system = "You are the user's personal assistant. This is a demo trip: real websites, but you must never complete a booking, payment, reservation, order, change or cancellation. Go as far as the final review page, then stop and give the user a summary for approval. No logins or payment methods. Reply in " + s["language"] + ". The user's details: " + json.dumps(s["persona"], ensure_ascii=False)
        step, message = 0, s["steps"][0]["goal"]
        if calls:
            message = calls.message(s["language"], message)
        for number in range(s["max_user_turns"]):
            observer.step, observer.turn = step, number
            before = ledger(hh)
            transcript.append({"role": "user", "content": message, "step": step})
            result = turn(message, system=system, hist=history)
            history = result.get("messages") or []
            reply = result.get("final_response", "")
            transcript.append({"role": "assistant", "content": reply, "step": step})
            evidence = observer.capture(number)
            after = ledger(hh)
            if errand_rows(after) != errand_rows(before):
                ledger_steps.add(step)
            packets = [r for r in after.get("actions", []) if r not in before.get("actions", []) and r.get("status") in ("prepared", "approval_required") and "material_summary" in r.get("fields_json", "") and r.get("action_id") not in approval_ids]
            if packets:
                approval_steps.add(step)
                approval_ids.update(r["action_id"] for r in packets)
                approval_packets.extend({"step": step, "action_id": r["action_id"], "booking": packet_booking(r)} for r in packets)
            meta.update(pages=observer.pages, evidence=evidence, ledger_steps=sorted(ledger_steps), approval_steps=sorted(approval_steps),
                        approval_packets=approval_packets, usage=metrics)
            write(root / "run.json", meta)
            write(root / "transcript.json", transcript)
            simulated = turn(reply, user=True, system=sim_user.prompt(s, s["steps"][step], step == len(s["steps"]) - 1), hist=user_view(transcript[:-1]))["final_response"]
            simulated, replaced = sim_user.guard(reply, simulated, s["language"])
            if replaced:
                append(root / "guards.jsonl", {"step": step, "guard_replaced": True})
            if "[[END]]" in simulated and step == len(s["steps"]) - 1:
                break
            if "[[NEXT]]" in simulated or "[[END]]" in simulated:
                step += 1
                if step == len(s["steps"]):
                    break
                phrased = turn("Phrase the new goal as the user.", user=True, system=sim_user.prompt(s, s["steps"][step]))["final_response"]
                message = phrased.replace("[[NEXT]]", "").replace("[[END]]", "").strip() or s["steps"][step]["goal"]
            else:
                message = simulated
        meta["status"] = "ok"
    except Exception as exc:
        meta.update(status="timeout" if isinstance(exc, TimeoutError) else "error", error=type(exc).__name__)
    finally:
        if calls:
            try:
                write(root / "calls.json", calls.request("/transcripts"))
            except Exception as exc:
                meta["calls_error"] = type(exc).__name__
            calls.close()
        write(root / "ledger.json", ledger(hh))
        meta.update(end=time.time(), usage=metrics)
        write(root / "run.json", meta)
        write(root / "transcript.json", transcript)
        for name in ("tools.jsonl", "tripwire.jsonl"):
            (root / name).touch(exist_ok=True)
        write(root / "checks.json", checks.evaluate(root, s))
        try:
            verdict = judge.run(root) if args.judge != "none" else {"skipped": True, "reason": "--judge none"}
        except Exception as exc:
            verdict = {"pass": False, "error": type(exc).__name__}
        write(root / "judge.json", verdict)
        write(root / "cost.json", {"model": MODEL, "usage": metrics, "cost_usd": None, "note": "No price assumed; includes assistant and simulator tokens; judge billed separately."})
    return meta
