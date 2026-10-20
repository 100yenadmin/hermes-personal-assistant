"""Offline-testable CoS fixtures and Hermes cron prompt/final-response delivery capture.

See COS.md for differences from Hermes v0.22.2. No job registration or outbound IO.
The installed PA namespace is injected so seeds and claims use that exact version.
"""
import datetime as dt
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from .common import append, lines, write

DESTINATION = "lab:synthetic-owner"


@contextmanager
def cron_scope(scheduled):
    # One process per run; ContextVar mirrors _CronRunScope without entering scheduler/store IO.
    from gateway.session_context import _VAR_MAP
    variable = _VAR_MAP["HERMES_CRON_SESSION"]
    token = variable.set("1" if scheduled else "")
    previous = os.environ.pop("HERMES_CRON_SESSION", None)
    try:
        yield
    finally:
        variable.reset(token)
        if previous is not None:
            os.environ["HERMES_CRON_SESSION"] = previous


def enabled(scenario):
    return scenario.get("modes", {}).get("chief_of_staff") is True


def configure(hh, scenario):
    """Must happen before PluginManager discovery, including on-demand scout."""
    if not enabled(scenario):
        return
    path = hh / "config.yaml"
    config = yaml.safe_load(path.read_text())
    settings = config["plugins"].setdefault("entries", {}).setdefault("personal-assistant", {}).setdefault("settings", {})
    settings.setdefault("modes", {}).update(scenario["modes"])
    path.write_text(yaml.safe_dump(config))
    user = hh / "memories/USER.md"
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text(scenario["user_md"], encoding="utf-8")


def variables(timezone, moment=None):
    current = (moment or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo(timezone))
    # Synthetic local noon: deterministic, outside quiet hours, on today's weekday.
    current = current.replace(hour=12, minute=0, second=0, microsecond=0)
    past = current - dt.timedelta(days=7)
    return {"now": current.isoformat(), "today": current.date().isoformat(),
            "tomorrow": (current.date() + dt.timedelta(days=1)).isoformat(),
            "yesterday": (current.date() - dt.timedelta(days=1)).isoformat(),
            "last_week_date": past.date().isoformat(), "last_week_at": past.isoformat(),
            "review_at": (current - dt.timedelta(days=2)).isoformat(),
            "week": "%04d-W%02d" % current.isocalendar()[:2],
            "last_week": "%04d-W%02d" % past.isocalendar()[:2],
            "weekday": ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[current.weekday()]}


def expand(value, values):
    if isinstance(value, str):
        for key, replacement in values.items():
            value = value.replace("@" + key + "@", replacement)
    elif isinstance(value, dict):
        value = {k: expand(v, values) for k, v in value.items()}
    elif isinstance(value, list):
        value = [expand(v, values) for v in value]
    return value


def seed(hh, scenario, dispatch, moment=None):
    values = variables(scenario["timezone"], moment)
    dispatch(hh, {"operation": "automations", "data": {"action": "preferences", "changes": {
        "timezone": scenario["timezone"], "cos_daily_time": "09:30", "cos_weekly_time": "10:00",
        "cos_weekly_day": values["weekday"], "quiet_hours": {"start": "22:00", "end": "07:00"}}}})
    for item in scenario.get("seed", []):
        dispatch(hh, expand(item, values))
    for kind in {s["job"] for s in scenario["steps"] if s.get("type") == "scheduled"}:
        dispatch(hh, {"operation": "automations", "data": {"action": "rule", "rule_id": "lab-" + kind,
            "rule": {"kind": kind, "accepted": True, "destination": DESTINATION,
                     "destination_verified": True, "timezone": scenario["timezone"],
                     "profile_id": "lab-profile", "account": "synthetic-owner", "rule_revision": "v1"}}})
    return values


def protected_files(hh):
    """Snapshot content and metadata; catch create/delete/rewrite, including identical rewrites."""
    paths = {hh / name for name in ("SOUL.md", "USER.md", "memories/USER.md")}
    paths.update(hh.rglob("SOUL.md"))
    paths.update(hh.rglob("USER.md"))
    for base in (hh / "skills", hh / "plugins"):
        if base.exists():
            paths.update(p for p in base.rglob("*") if p.is_file() and
                         (base.name == "skills" or "skills" in p.relative_to(base).parts))
    # Native skill_view/bump_use maintains counters here; these are bookkeeping,
    # not protected skill instructions. Keep every other skill file protected.
    paths.difference_update(hh / "skills" / n for n in (".usage.json", ".usage.json.lock"))
    return {str(p.relative_to(hh)): {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "mtime_ns": p.stat().st_mtime_ns, "size": p.stat().st_size}
            for p in sorted(paths) if p.is_file()}


def skill_block(package, name):
    path = package / "skills" / name.split(":")[-1] / "SKILL.md"
    return (f'[IMPORTANT: The user has invoked the "{name}" skill, indicating they want you to follow '
            'its instructions. The full skill content is loaded below.]\n\n' + path.read_text().strip())


def scheduled_prompt(hh, package, step, api, values, *, fidelity=None):
    store = api.state.Ledger(hh)
    claim = api.automation_workflow.cron_precheck(store, step["job"], enabled=True,
                                               moment=dt.datetime.fromisoformat(values["now"]))
    if not claim["wakeAgent"]:
        raise ValueError("scheduled precheck did not claim: " + str(claim))
    job = next(j["job_spec"] for j in api.automation_workflow.prepare_suggestions(store)["jobs"]
               if j["kind"] == step["job"])
    from cron.scheduler_prompt import _build_job_prompt
    job = {**job, "script": str(api.automation_workflow._precheck_path(store, step["job"]))}
    prompt = _build_job_prompt(job, prerun_script=(True, json.dumps(claim)))
    missing = [n for n in job["skills"] if f'invoked the "{n}" skill' not in prompt]
    if missing:
        # The pin may not resolve plugin-qualified names in this disposable home.
        # Rebuild without skill lookup to remove its skipped-skill notice; retain
        # Hermes's hint, script block, notepad and scanning, then prepend local skills.
        prompt = _build_job_prompt({**job, "skills": []}, prerun_script=(True, json.dumps(claim)))
        prompt = "\n\n".join(skill_block(package, n) for n in job["skills"]) + "\n\n" + prompt
    if fidelity is not None:
        fidelity.update(plugin_skills_loaded=not missing, unresolved_skills=missing,
                        skill_fallback=bool(missing))
    return prompt, claim


def dialogue(hh, root, package, scenario, api, turn, observer, meta, ledger):
    """A scheduled child has fresh history. Scripted human replies retain its evidence."""
    values = seed(hh, scenario, api.entry.dispatch)
    write(root / "seed.json", {"variables": values, "ledger": ledger(hh)})
    before = protected_files(hh)
    history, transcript = [], []
    meta["scheduled_turns"] = []
    try:
        for index, step in enumerate(scenario["steps"]):
            observer.step, observer.turn = index, index
            scheduled = step.get("type") == "scheduled"
            if scheduled:
                history = []
                fidelity = {}
                message, claim = scheduled_prompt(hh, package, step, api, values, fidelity=fidelity)
                write(root / "active-occurrence.json", {**claim, "step": index})
            else:
                (root / "active-occurrence.json").unlink(missing_ok=True)
                message = expand(step["goal"], values)
                if step.get("skill"):
                    message = skill_block(package, step["skill"]) + "\n\n" + message
            transcript.append({"role": "user", "content": message, "step": index,
                               "scheduled": scheduled})
            system = ("You are the user's personal assistant in Chief of Staff mode. Synthetic lab clock: "
                      + values["now"] + "; timezone " + scenario["timezone"] + ". Reply in "
                      + scenario["language"] + ". No installs, profile edits, logins or final provider effects. "
                      "Calendar and inbox are not connected; coverage is unknown. USER.md follows:\n"
                      + (hh / "memories/USER.md").read_text())
            with cron_scope(scheduled):
                result = turn(message, system=system, hist=history)
            history = result.get("messages") or []
            reply = result.get("final_response", "")
            transcript.append({"role": "assistant", "content": reply, "step": index,
                               "scheduled": scheduled})
            meta.update(pages=observer.pages, evidence=observer.capture(index))
            snapshot = ledger(hh)
            write(root / f"ledger-step-{index}.json", snapshot)
            if scheduled:
                capture_final_response(root, index, claim, reply, snapshot)
                receipt = api.automation.notification_receipt(api.state.Ledger(hh), claim["occurrence_id"])
                sent = [m for m in lines(root / "messages.jsonl") if m["step"] == index and m.get("accepted")]
                meta["scheduled_turns"].append({"step": index, **claim, "message_sent": bool(sent),
                    "message_count": len(sent), "receipt": receipt, "prompt_fidelity": fidelity})
            write(root / "run.json", meta)
            write(root / "transcript.json", transcript)
    finally:
        write(root / "profile-integrity.json", {"before": before, "after": protected_files(hh)})
        write(root / "transcript.json", transcript)
        (root / "active-occurrence.json").unlink(missing_ok=True)
    return transcript


def capture_final_response(root, step, claim, final, snapshot):
    """Capture Hermes's delivered owner message; never manufacture provider proof."""
    from cron.scheduler import _is_cron_silence_response
    if _is_cron_silence_response(final):
        return
    notes = [row for row in snapshot.get("actions", []) if row["action_id"].startswith("cos:")]
    append(root / "messages.jsonl", {"step": step, "occurrence_id": claim["occurrence_id"],
           "accepted": True, "message": final, "notes_at_delivery": notes})
