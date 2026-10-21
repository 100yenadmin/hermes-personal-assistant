"""Build a scorecard from immutable lab artifacts and optional live evidence."""
import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

from evals.lab.checks import submit_events
from ._portable import portable
from .areas import AREAS, PARITY


def _read(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path.name}: {exc}") from exc


def _require(condition, field):
    if not condition:
        raise ValueError(f"invalid {field}")


def _date(value, field):
    try:
        _require(isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), field)
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: expected ISO date") from exc


def _number(value, field, positive=False):
    _require(type(value) in (int, float) and math.isfinite(value)
             and (value > 0 if positive else value >= 0), field)


def _live(value):
    if value is None:
        return {"tasks": [], "baselines": {}, "day30": {}}
    _require(isinstance(value, dict), "live")
    _require(isinstance(value.get("tasks"), list), "tasks")
    keys, ids = {a["key"] for a in AREAS}, set()
    for i, task in enumerate(value["tasks"]):
        field = f"tasks[{i}]"
        _require(isinstance(task, dict), field)
        for name in ("id", "area", "owner", "title", "started", "due", "status", "correction"):
            _require(isinstance(task.get(name), str) and bool(task[name]), f"{field}.{name}")
        _require(task["area"] in keys, f"{field}.area")
        _require((task["owner"], task["id"]) not in ids, f"{field}.id (duplicate for this owner)")
        ids.add((task["owner"], task["id"]))
        _require(task["status"] in {"pass", "fail", "pending"}, f"{field}.status")
        _require(task["correction"] in {"none", "minor", "material"}, f"{field}.correction")
        _require(task.get("owner_accepted") is None or type(task["owner_accepted"]) is bool,
                 f"{field}.owner_accepted")
        _require(_date(task["due"], f"{field}.due") >= _date(task["started"], f"{field}.started"), f"{field}.due")
        _require(isinstance(task.get("facts"), list), f"{field}.facts")
        for j, fact in enumerate(task["facts"]):
            ff = f"{field}.facts[{j}]"
            _require(isinstance(fact, dict), ff)
            for name in ("item", "facing"):
                _require(isinstance(fact.get(name), str) and bool(fact[name].strip()), f"{ff}.{name}")
            _require(fact["facing"] in {"money", "customer", "internal"}, f"{ff}.facing")
            _require(type(fact.get("ok")) is bool, f"{ff}.ok")
            _require(fact.get("source") is None or isinstance(fact["source"], str), f"{ff}.source")
    for name in ("baselines", "day30"):
        _require(isinstance(value.get(name, {}), dict), name)
        for owner, record in value.get(name, {}).items():
            field = f"{name}.{owner}"
            _require(isinstance(record, dict), field)
            metric = "total_minutes" if name == "baselines" else "minutes"
            _number(record.get(metric), f"{field}.{metric}", positive=name == "baselines")
            if name == "day30":
                types = record.get("first_pass_task_types")
                _require(isinstance(types, list) and all(isinstance(t, str) and t for t in types),
                         f"{field}.first_pass_task_types")
    return {"tasks": value["tasks"], "baselines": value.get("baselines", {}), "day30": value.get("day30", {})}


def _day30(live):
    owners = sorted({t["owner"] for t in live["tasks"]})
    results = {}
    for owner in owners:
        base, end = live["baselines"].get(owner), live["day30"].get(owner)
        if base is None or end is None:
            results[owner] = {"state": "unproven"}
            continue
        saving = 1 - end["minutes"] / base["total_minutes"]
        types = len({t.strip().casefold() for t in end["first_pass_task_types"] if t.strip()})
        passed = saving >= PARITY["DAY30_MIN_SAVING"] - 1e-12 and types >= PARITY["DAY30_MIN_TYPES"]
        results[owner] = {"state": "pass" if passed else "fail", "saving": saving, "types": types}
    state = "unproven" if not owners or any(r["state"] == "unproven" for r in results.values()) else (
        "pass" if all(r["state"] == "pass" for r in results.values()) else "fail")
    return {"state": state, "owners": results}


def _real_work(tasks, as_of):
    eligible = [t for t in tasks if _date(t["started"], "started") <= as_of
                and (t["status"] in {"pass", "fail"} or _date(t["due"], "due") < as_of)]
    passed = sum(t["status"] == "pass" and t.get("owner_accepted") is True
                 and t["correction"] != "material" for t in eligible)
    owners = len({t["owner"] for t in eligible})
    # The export has no completion timestamp; never count beyond as_of.
    end = min(max(_date(t["due"], "due") for t in eligible), as_of) if eligible else as_of
    days = max(0, (end - min(_date(t["started"], "started") for t in eligible)).days + 1) if eligible else 0
    rate = passed / len(eligible) if eligible else 0
    enough = len(eligible) >= PARITY["REAL_MIN_TASKS"] and owners >= PARITY["REAL_MIN_OWNERS"] and days >= PARITY["REAL_MIN_DAYS"]
    return {"state": ("pass" if rate >= PARITY["REAL_PASS_RATE"] else "fail") if enough else "unproven",
            "tasks": len(eligible), "passed": passed, "owners": owners, "days": days, "pass_rate": rate}


def _count(value):
    """A check count may be a number or a list of structured errors (fixtures add factual_errors as they land)."""
    return len(value) if isinstance(value, list) else value if type(value) in (int, float) and value > 0 else 0


def _facts(tasks, runs):
    facts = [(t["id"], f) for t in tasks for f in t["facts"]]
    errors = [r["run"] for r in runs if _count(r["checks"].get("fabricated_confirmations"))
              or _count(r["checks"].get("factual_errors"))]
    errors += [task_id for task_id, f in facts if f["ok"] is False and f["facing"] in {"money", "customer"}]
    missing = any(f["facing"] in {"money", "customer"} and not (f.get("source") or "").strip() for _, f in facts)
    return {"state": "fail" if errors else "unproven" if not facts or missing else "pass", "errors": errors}


def _pa_ref(refs):
    """PA's installed ref. Hand-built lab homes list heartbeat2 first, so match PA by name or source;
    home.py installs --pa first, so fall back to the first entry (a wrong pick reads as other_commit)."""
    plugins = refs.get("plugins") if isinstance(refs, dict) else None
    entries = [p for p in plugins if isinstance(p, dict)] if isinstance(plugins, list) else []
    named = [p for p in entries if p.get("name") == "personal-assistant"]
    sourced = [p for p in entries if re.search(r"personal-assistant|travel-agent-skills", str(p.get("source", "")), re.I)]
    other = re.compile(r"heartbeat2|fish-audio|lcm", re.I)  # Plugins a lab home installs next to PA.
    anonymous = [p for p in entries if not p.get("name") and not other.search(str(p.get("source", "")))]
    pick = named or sourced or anonymous[:1]
    return pick[0].get("ref") if pick else None


def build(version, commit, lab_dirs, live=None, as_of=None):
    """Count only full-SHA-matching completed runs; retain an exclusion for all others."""
    _require(isinstance(version, str) and bool(version.strip()), "version")
    _require(isinstance(commit, str) and bool(re.fullmatch(r"[0-9a-fA-F]{40}", commit)), "commit")
    today = _date(as_of, "as_of") if as_of is not None else datetime.now(timezone.utc).date()
    live = _live(live)
    day30 = _day30(live)
    catalogue = deepcopy(AREAS)
    mapped = {t["scenario"] for a in catalogue for t in a["tests"]}
    runs, excluded, roots, seen = [], [], [], set()
    for directory in lab_dirs:
        root = Path(directory)
        _require(root.is_dir(), "lab_dirs")
        lab_name = root.name if root.name not in {"", ".", ".."} else root.resolve().name
        roots.append(lab_name)
        for path in sorted(root.glob("*/run.json")):
            folder, run = path.parent, _read(path)
            scenario = _read(folder / "scenario.json", {})
            _require(isinstance(run, dict), f"{folder.name}.run")
            _require(isinstance(scenario, dict) and isinstance(scenario.get("id"), str), f"{folder.name}.scenario.id")
            sid = scenario["id"]
            run_id = f"{lab_name}/{folder.name}"
            identity = (folder.name, sid, run["start"] if "start" in run
                        else hashlib.sha256(path.read_bytes()).hexdigest())
            if identity in seen:  # Only counted runs reserve an identity, so a damaged copy never hides its original.
                excluded.append({"run": run_id, "scenario": sid, "reason": "duplicate"})
                continue
            ref = _pa_ref(_read(folder / "plugin-refs.json", {}))
            if run.get("status") == "skipped":
                reason = f"skipped:{run.get('reason', 'unspecified')}"
            elif "end" not in run:
                reason = "incomplete"
            elif not isinstance(ref, str) or not ref:
                reason = "no_plugin_refs"
            elif not re.fullmatch(r"[0-9a-fA-F]{40}", ref) or ref.lower() != commit.lower():
                reason = f"other_commit:{ref[:12]}"
            elif sid not in mapped:
                reason = "unmapped_scenario"
            else:
                reason = None
            if reason:
                excluded.append({"run": run_id, "scenario": sid, "reason": reason})
                continue
            checks, judge = _read(folder / "checks.json", {}), _read(folder / "judge.json", {})
            _require(isinstance(checks, dict), f"{folder.name}.checks")
            _require(isinstance(judge, dict), f"{folder.name}.judge")
            overall = checks.get("overall", {"missing": False})
            _require(isinstance(overall, dict), f"{folder.name}.checks.overall")
            hits = len(submit_events(folder))
            # Stricter than the lab report: an empty or non-boolean overall map is malformed, never a pass.
            safe = "end" in run and run.get("status") == "ok" and not hits and bool(overall) \
                and all(v is True for v in overall.values())
            passed = bool(safe and checks.get("all_pass", False) and judge.get("pass") is True)
            seen.add(identity)
            runs.append({"run": run_id, "scenario": sid, "passed": passed, "checks": checks})
    for area in catalogue:
        for test in area["tests"]:
            test.setdefault("covers", [])
            selected = [r for r in runs if r["scenario"] == test["scenario"]]
            n, passed = len(selected), sum(r["passed"] for r in selected)
            state = "not_run" if not n else "fail" if passed < n else "insufficient_runs" if n < PARITY["LAB_RUNS"] else "pass"
            test.update(runs=n, passed=passed, run_ids=[r["run"] for r in selected], state=state)
        full = [t["state"] for t in area["tests"] if t["kind"] == "full"]
        partial = [t["state"] for t in area["tests"] if t["kind"] == "partial"]
        area["lab"] = "not_exercised" if not area["tests"] else "fail" if "fail" in full else "pass" if full and all(s == "pass" for s in full) else "unproven"
        area["partial"] = {"state": "none" if not partial else "fail" if "fail" in partial else "pass" if all(s == "pass" for s in partial) else "incomplete"}
        covered = {i for t in area["tests"] if t["state"] == "pass" for i in t["covers"]}
        area["uncovered_duties"] = [duty for i, duty in enumerate(area["duties"]) if i not in covered]
        tasks = [t for t in live["tasks"] if t["area"] == area["key"] and _date(t["started"], "started") <= today]
        area_runs = [r for r in runs if r["scenario"] in {t["scenario"] for t in area["tests"]}]
        area["real_work"], area["facts"] = _real_work(tasks, today), _facts(tasks, area_runs)
        states = [area["lab"], area["real_work"]["state"], area["facts"]["state"], day30["state"]]
        area["parity"] = "fail" if "fail" in states else "pass" if all(s == "pass" for s in states) else "unproven"
        area["notes"] = []
        if area["parity"] == "pass" and area["uncovered_duties"]:  # One passing example cannot stand for the whole area.
            area["parity"] = "unproven"
            area["notes"].append(f"{len(area['uncovered_duties'])} duties lack a passing lab test")
    counts = {"lab": {s: sum(a["lab"] == s for a in catalogue) for s in ("pass", "fail", "unproven", "not_exercised")},
              "partial": {s: sum(a["partial"]["state"] == s for a in catalogue) for s in ("pass", "fail", "incomplete", "none")},
              "parity": {s: sum(a["parity"] == s for a in catalogue) for s in ("pass", "fail", "unproven")}}
    return portable({"version": version, "commit": commit, "as_of": today.isoformat(), "areas": catalogue,
                     "day30": day30, "excluded": excluded, "counts": counts, "lab_dirs": roots, "schema": 1})
