"""Native suggestion integration and the script gate for two optional routines."""
import datetime as dt
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from . import automation as auto
from .state import stable_id, legacy


def preferences(ledger, changes=None):
    prior = ledger.get("action", "pa:preferences")
    if changes is not None:
        allowed = {"timezone", "brief_time", "quiet_hours", "paused", "snooze_until"}
        if set(changes) - allowed:
            raise ValueError("unknown preference")
        if "timezone" in changes:
            ZoneInfo(changes["timezone"])
        prior = ledger.put("action", "pa:preferences", changes, action_type="preferences", status="configured")
    return (prior or {}).get("fields", {})


def _precheck_path(ledger, kind):
    suffix = "brief" if kind == "daily_brief" else "due"
    return ledger.root / "scripts" / f"personal_assistant_pa_{suffix}_precheck.py"


def _install_precheck(ledger, kind):
    """Register the existing precheck under Hermes's native script boundary."""
    if kind not in {"daily_brief", "due_source_check"}:
        raise ValueError("unknown PA routine kind")
    target = _precheck_path(ledger, kind)
    package = Path(__file__).resolve().parents[1]
    content = ("# Personal Assistant Plugin precheck; no jobs are enabled here.\n"
               "import sys\n"
               f"sys.path.insert(0, {str(package)!r})\n"
               "from personal_assistant.automation_workflow import script_main\n"
               f"script_main({kind!r})\n").encode("utf-8")
    legacy._ensure_directory(ledger.root, target.parent, owned=False, label="Hermes scripts directory")
    legacy._validate_existing_path(ledger.root, target, owned=False, label="Hermes scripts directory")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        legacy._validate_existing_path(ledger.root, target, owned=False, label="Hermes scripts directory")
        if target.read_bytes() != content:
            raise ValueError(f"PA precheck path already contains different content: {target}")
    else:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
    return str(target)


def prepare_suggestions(ledger, *, native=False):
    prefs = preferences(ledger)
    result = auto.suggest_automation_jobs(ledger=ledger, timezone=prefs.get("timezone"))
    for job in result["jobs"]:
        brief = job["kind"] == "daily_brief"
        collector = "personal_assistant.daily_ops.morning_brief" if brief else "personal_assistant.daily_ops.evening_register"
        due_rule = (
            "run after the configured local brief time for the current local date"
            if brief else
            "run only when an accepted source is due_at<=now or its refresh interval has elapsed in that source timezone"
        )
        skills = ["personal-assistant:personal-assistant", *job["skills"]]
        skills = list(dict.fromkeys(skills))
        # Hermes accepts only create_job arguments in job_spec. Keep display
        # metadata outside it so accepting the suggestion creates a native job.
        job["collector"] = collector
        job["due_rule"] = due_rule
        job["job_spec"] = {"name": job["name"], "schedule": "*/5 * * * *",
            "script": str(_precheck_path(ledger, job["kind"])),
            "skills": skills,
            "deliver": "local",
            "prompt": job["prompt"] + f" Use the accepted daily-ops source in its configured timezone; {due_rule}. Invoke the read-only collector {collector} only after the local precheck. The evening collector is the due-source check, not a third scheduled job. The script supplies an already claimed notification occurrence and verified destination. Use the existing message tool only for a useful accepted owner notification. Record delivered with its provider receipt, suppressed if nothing useful, or unknown if delivery is uncertain using pa automations receipt. Never resend an existing occurrence. Refresh source checkpoints only after successful reads. Do not create jobs or make purchases. Cron delivery is local to avoid sending your response twice."}
    if native:
        from gateway.session_context import get_session_env
        if get_session_env("HERMES_CRON_SESSION"):
            raise ValueError("scheduled children cannot change routine suggestions")
        # Native stores are scoped by Hermes; refuse cross-profile invocation.
        from hermes_constants import get_hermes_home
        if Path(get_hermes_home()).resolve() != ledger.root:
            raise ValueError("native scheduler profile differs from PA profile")
        from cron.jobs import list_jobs
        from cron.suggestions import add_suggestion
        existing = {job.get("name") for job in list_jobs(include_disabled=True)}
        for job in result["jobs"]:
            _install_precheck(ledger, job["kind"])
            if job["name"] in existing:
                continue
            item = add_suggestion(title=job["name"], description="Optional PA routine; accepting enables it. Briefs use your configured local time.", source="integration", job_spec=job["job_spec"], dedup_key="personal-assistant:" + job["kind"])
            if item:
                ledger.put("action", "pa:suggestion:" + job["kind"], {"suggestion_id": item["id"]}, action_type="automation_reference", status="suggested")
    return result


def cron_precheck(ledger, kind, *, enabled, moment=None):
    """Return Hermes wakeAgent JSON; no network or LLM on an empty tick."""
    prefs = preferences(ledger)
    zone = prefs.get("timezone")
    if not enabled or not zone:
        return {"wakeAgent": False, "reason": "disabled_or_timezone_missing"}
    current = moment or dt.datetime.now(dt.timezone.utc)
    actions = ledger.list("action")
    rules = [auto._rule_data(a) for a in actions if a["action_type"] == "automation_rule"]
    rules = [r for r in rules if r.get("kind") == kind and r.get("accepted") and r.get("destination_verified") and not r.get("paused")]
    if not rules:
        return {"wakeAgent": False, "reason": "no_accepted_routine"}
    destinations = {r.get("destination") for r in rules}
    if len(destinations) != 1 or not next(iter(destinations)):
        return {"wakeAgent": False, "reason": "destination_conflict"}
    if any(r.get("snooze_until") and auto._value_time(r["snooze_until"], zone) > current for r in rules):
        return {"wakeAgent": False, "reason": "routine_snoozed"}
    local = current.astimezone(ZoneInfo(zone))
    trips = ledger.list("trip")
    due = []
    for row in actions:
        fields = row["fields"]
        if fields.get("kanban_task_id"):
            from .context import read_kanban_task
            task = read_kanban_task(fields["kanban_task_id"], fields.get("kanban_board"))
            if task.get("status") in {"done", "archived"}:
                continue
        if fields.get("snooze_until") and auto._value_time(fields["snooze_until"], zone) > current:
            continue
        trip = next((t for t in trips if t["trip_id"] == row.get("trip_id")), None)
        if trip and not auto._trip_active([trip], current) and row["action_type"] not in {"refund", "return"}:
            continue
        if auto._due_actions([row], current):
            due.append(row)
    active = auto._trip_active(trips, current)
    state = {**prefs, "actions": due, "accepted_sources": rules, "active_travel": active}
    if kind == "daily_brief":
        if local.strftime("%H:%M") < prefs.get("brief_time", "08:00"):
            return {"wakeAgent": False, "reason": "before_brief_time"}
        state["actions"] = [{"due": True}]
        logical = local.date().isoformat()
    else:
        logical = stable_id([(a["action_id"], a["fields"].get("due_at")) for a in due], [(r.get("source_ref"), r.get("last_checked_at")) for r in rules])
    check = auto.script_precheck(state, now=current)
    if not check["run"]:
        return {"wakeAgent": False, "reason": check["reason"]}
    # Complete accepted rules bind the existing notification action to the
    # canonical delivery payload. Legacy rules without these fields retain the
    # old claim shape, but cannot satisfy daily-ops delivery verification.
    selected_rule = rules[0] if len(rules) == 1 else {}
    rule_id = str(selected_rule.get("automation_rule_id", kind))
    revision = selected_rule.get("rule_revision", selected_rule.get("revision"))
    profile_id = selected_rule.get("profile_id")
    account = selected_rule.get("account")
    payload = None
    if all(isinstance(value, str) and value.strip() for value in (profile_id, account, revision)):
        payload = auto.canonical_notification_payload(
            profile_id=profile_id, account=account, timezone=zone,
            destination=next(iter(destinations)), rule_id=rule_id, rule_revision=revision,
        )
    occurrence = auto.notification_occurrence_id(rule_id, logical, revision if payload else None)
    claim = auto.claim_notification(ledger, occurrence, rule_id=rule_id, payload=payload)
    return {"wakeAgent": claim["claimed"], "occurrence_id": occurrence,
            "destination": next(iter(destinations)), "due_sources": check.get("due_sources", []),
            "due_action_ids": [a["action_id"] for a in due]}


def dispatch(ledger, data):
    action = data.pop("action", "status")
    if action == "status":
        return {"preferences": preferences(ledger), "rules": [a for a in ledger.list("action") if a["action_type"] == "automation_rule"], "install_enabled_jobs": 0}
    if action == "suggest":
        return prepare_suggestions(ledger, **data)
    if action == "rule":
        return auto.upsert_automation_rule(ledger, **data)
    if action == "preferences":
        return preferences(ledger, data["changes"])
    if action in {"pause", "resume", "snooze"}:
        return preferences(ledger, {"snooze_until": data["until"]} if action == "snooze" else {"paused": action == "pause"})
    if action == "claim":
        return auto.claim_notification(ledger, **data)
    if action == "receipt":
        return auto.record_notification(ledger, **data)
    raise ValueError("unknown automation control")


def script_main(kind):
    import json
    try:
        import yaml
        from .state import Ledger
        root = Path(os.environ["HERMES_HOME"]).resolve()
        config = yaml.safe_load((root / "config.yaml").read_text()) or {}
        plugins = config.get("plugins", {})
        enabled = "personal-assistant" in (plugins.get("enabled") or []) and "personal-assistant" not in (plugins.get("disabled") or [])
        result = cron_precheck(Ledger(root), kind, enabled=enabled)
    except Exception:
        result = {"wakeAgent": False, "reason": "precheck_requires_attention"}
    print(json.dumps(result))
