"""Behavioral v3 evidence: all provider-facing checks use isolated fake executables.

No test in this file invokes a real gog/Stripe/Supabase/geo service.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from personal_assistant.daily_ops import clients_sync, config, geo, priority, watchdog
from personal_assistant.state import Ledger

REPO = Path(__file__).resolve().parents[1]
NOW = "2026-09-08T03:00:00+00:00"


def base_config():
    return {
        "tenant": {"profile_id": "example-profile", "owner_email": "owner@example.com"},
        "delivery": {"target": "example-topic", "verified": True},
        "timezone": "Asia/Bangkok",
        "accounts": {"work": "owner@example.com", "personal": None},
        "priority": {"static_terms": ["invoice", "payment"], "connectors": {"clients_sync": {"enabled": False, "consent": False, "stripe_live": False}}},
        "travel": {"leave_by": False, "buffer_min": 15, "heads_up_min": 45, "geocoder": {"consent": False}},
        "schedules": {"brief": "0 10 * * *", "watchdog": "*/15 * * * *", "evening": "0 21 * * *"},
        "autoclean": {"enabled": False},
    }


def fake_provider(tmp_path: Path) -> Path:
    script = tmp_path / "gog"
    script.write_text("""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
log = os.environ.get('FAKE_LOG')
if log:
    with open(log, 'a', encoding='utf-8') as h: h.write(json.dumps(args) + '\\n')
if any(x in {'modify', 'send', 'reply', 'forward', 'archive', 'delete'} for x in args):
    print('mutation forbidden', file=sys.stderr); raise SystemExit(91)
if 'auth' in args:
    print(json.dumps({'accounts': [{'email':'owner@example.com','valid':True,'scopes':['https://www.googleapis.com/auth/gmail.readonly','https://www.googleapis.com/auth/calendar.readonly','openid']}]})); raise SystemExit
if 'calendar' in args:
    print(json.dumps({'events': [{'id':'ev1','summary':'Planning','start':{'dateTime':'2026-09-09T02:00:00+00:00'},'end':{'dateTime':'2026-09-09T03:00:00+00:00'},'location':'Example office'}], 'has_more':False})); raise SystemExit
if 'gmail' in args:
    query = args[args.index('search') + 1]
    ident = os.environ.get('FAKE_ID', 't1')
    if 'category:' in query:
        rows = [{'id': 'bulk1', 'from':'Offers <offers@vendor.invalid>', 'subject':'Weekly offers'}]
        print(json.dumps({'threads': rows, 'has_more':False, 'total_count':7})); raise SystemExit
    rows = [{'id': ident, 'from':'Billing <billing@vendor.invalid>', 'subject':'Invoice payment due'}]
    print(json.dumps({'threads': rows, 'has_more':False})); raise SystemExit
print('unexpected command', file=sys.stderr); raise SystemExit(92)
""")
    script.chmod(0o700)
    return script


def fake_stripe(tmp_path: Path) -> Path:
    script = tmp_path / "stripe"
    script.write_text("""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
log = os.environ.get('FAKE_LOG')
if log:
    with open(log, 'a', encoding='utf-8') as h: h.write('stripe ' + json.dumps(args) + '\\n')
if args[:2] == ['config','--list']:
    print('account_id=acct_example\\nlivemode=false'); raise SystemExit
if args[:2] == ['customers','list']:
    if os.environ.get('STRIPE_BAD'):
        print('{}'); raise SystemExit
    after = ' '.join(args)
    if '--starting-after' in args:
        print(json.dumps({'data':[{'id':'cus_2','email':'two@client.example','name':'Two'}], 'has_more':False})); raise SystemExit
    print(json.dumps({'data':[{'id':'cus_1','email':'one@client.example','name':'One'}], 'has_more':True})); raise SystemExit
print('unexpected stripe command', file=sys.stderr); raise SystemExit(92)
""")
    script.chmod(0o700)
    return script


def write_runtime(tmp_path: Path, cfg=None):
    root = tmp_path / "profile"
    root.mkdir(mode=0o700)
    cfg_path = root / "daily_ops.config.json"
    cfg_path.write_text(json.dumps(cfg or base_config()))
    log = root / "provider.log"
    return root, cfg_path, log


def env_for(root: Path, cfg_path: Path, log: Path, provider_dir: Path, **extra):
    env = os.environ.copy()
    env.update({"PYTHONPATH": str(REPO), "HERMES_HOME": str(root), "DAILY_OPS_PROFILE_ROOT": str(root), "DAILY_OPS_CONFIG": str(cfg_path), "DAILY_OPS_NOW": NOW, "FAKE_LOG": str(log), "PATH": str(provider_dir) + os.pathsep + "/usr/bin:/bin"})
    env.update(extra)
    return env


def run_module(name, env, cwd):
    return subprocess.run([sys.executable, "-m", name], cwd=cwd, env=env, text=True, capture_output=True, timeout=30)


def seed_trip(root: Path):
    Ledger(root).put("trip", "trip-example", {"base": {"label": "Example base", "lat": 1.0, "lng": 2.0}, "events": []}, title="Example trip", status="active")


def test_config_literal_booleans_and_cadence():
    cfg = base_config()
    cfg["delivery"]["verified"] = "true"
    assert any("delivery.verified" in error for error in config.validate_config(cfg))
    cfg = base_config()
    cfg["autoclean"]["enabled"] = True
    assert any("unsupported" in error for error in config.validate_config(cfg))
    cfg = base_config()
    cfg["travel"]["leave_by"] = True
    cfg["travel"]["geocoder"]["consent"] = True
    cfg["schedules"]["watchdog"] = "0 * * * *"
    assert any("20 minutes" in error for error in config.validate_config(cfg))


def test_actual_morning_and_evening_entrypoints(tmp_path):
    provider = fake_provider(tmp_path)
    root, cfg_path, log = write_runtime(tmp_path)
    seed_trip(root)
    env = env_for(root, cfg_path, log, tmp_path)
    morning = run_module("personal_assistant.daily_ops.morning_brief", env, tmp_path)
    evening = run_module("personal_assistant.daily_ops.evening_register", env, tmp_path)
    assert morning.returncode == 0, morning.stderr
    assert evening.returncode == 0, evening.stderr
    m, e = json.loads(morning.stdout), json.loads(evening.stdout)
    assert m["schema"] == e["schema"] == "personal-assistant.daily-ops.v3"
    assert m["kind"] == "morning_brief" and "calendar_next_36h" in m["sections"]
    assert m["sections"]["bulk_1"]["count"] == 7 and m["sections"]["bulk_1"]["exact"] is True
    assert e["kind"] == "evening_register" and "tomorrow_timeline" in e["sections"]
    assert "billing@vendor.invalid" not in morning.stdout + evening.stdout


def test_watchdog_quiet_is_exactly_zero_bytes(tmp_path):
    fake_provider(tmp_path)
    root, cfg_path, log = write_runtime(tmp_path)
    cfg = json.loads(cfg_path.read_text()); cfg["priority"]["static_terms"] = []; cfg_path.write_text(json.dumps(cfg))
    env = env_for(root, cfg_path, log, tmp_path)
    result = run_module("personal_assistant.daily_ops.watchdog", env, tmp_path)
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""
    assert not log.exists() or log.read_text() == ""


def test_watchdog_multi_tick_same_count_and_expiry(tmp_path):
    fake_provider(tmp_path)
    root, cfg_path, log = write_runtime(tmp_path)
    env = env_for(root, cfg_path, log, tmp_path, FAKE_ID="t1")
    first = run_module("personal_assistant.daily_ops.watchdog", env, tmp_path)
    second = run_module("personal_assistant.daily_ops.watchdog", env, tmp_path)
    env2 = dict(env, FAKE_ID="t2", DAILY_OPS_NOW="2026-09-08T04:00:00+00:00")
    replacement = run_module("personal_assistant.daily_ops.watchdog", env2, tmp_path)
    env3 = dict(env2, DAILY_OPS_NOW="2026-09-08T17:00:00+00:00")
    expired = run_module("personal_assistant.daily_ops.watchdog", env3, tmp_path)
    assert first.returncode == replacement.returncode == expired.returncode == 0
    assert json.loads(first.stdout)["sections"]["alerts"]
    assert second.stdout == ""
    assert json.loads(replacement.stdout)["sections"]["alerts"]
    assert json.loads(expired.stdout)["sections"]["alerts"]
    state = json.loads((root / "state" / "daily-ops" / "state.json").read_text())
    assert len(state["priority_alerts"]) == 2


def test_unsupported_autoclean_rejected_before_provider(tmp_path):
    fake_provider(tmp_path)
    cfg = base_config(); cfg["autoclean"]["enabled"] = True
    root, cfg_path, log = write_runtime(tmp_path, cfg)
    result = run_module("personal_assistant.daily_ops.watchdog", env_for(root, cfg_path, log, tmp_path), tmp_path)
    assert result.returncode == 1 and "unsupported" in result.stdout and not log.exists()
    cfg["autoclean"]["enabled"] = "false"; cfg_path.write_text(json.dumps(cfg))
    result = run_module("personal_assistant.daily_ops.watchdog", env_for(root, cfg_path, log, tmp_path), tmp_path)
    assert result.returncode == 1 and "boolean" in result.stdout


def test_priority_updates_and_email_exclusions():
    cfg = base_config()
    messages = [{"id":"a", "from":"Owner <owner@example.com>", "subject":"invoice"}, {"id":"b", "from":"News <news@vendor.invalid>", "subject":"invoice"}, {"id":"c", "from":"Updates <updates@vendor.invalid>", "subject":"payment"}]
    hits = priority.hits_in_messages(cfg, ["invoice", "payment"], messages)
    assert hits == {"invoice": ["b"], "payment": ["c"]}


def test_incomplete_client_index_is_not_used(tmp_path):
    cfg = base_config()
    cfg["priority"]["connectors"]["clients_sync"] = {"enabled": True, "consent": True, "stripe_account":"acct_example", "stripe_live":False}
    (tmp_path / "clients.json").write_text(json.dumps({"synced_at": NOW, "complete": False, "clients":[{"email":"x@client.example"}]}))
    terms, note = priority.build_terms(cfg, str(tmp_path), __import__("datetime").datetime.fromisoformat(NOW))
    assert "client.example" not in terms and note and "incomplete" in note


def test_connector_pagination_quiet_and_atomic_invalidation(tmp_path):
    fake_stripe(tmp_path)
    cfg = base_config(); cfg["priority"]["connectors"]["clients_sync"] = {"enabled": True, "consent": True, "stripe_account":"acct_example", "stripe_live":False}
    root, cfg_path, log = write_runtime(tmp_path, cfg)
    env = env_for(root, cfg_path, log, tmp_path)
    first = run_module("personal_assistant.daily_ops.clients_sync", env, tmp_path)
    second = run_module("personal_assistant.daily_ops.clients_sync", env, tmp_path)
    assert first.returncode == 0 and first.stdout and second.returncode == 0 and second.stdout == ""
    index = json.loads((root / "clients.json").read_text())
    assert index["complete"] is True and len(index["clients"]) == 2
    assert stat.S_IMODE((root / "clients.json").stat().st_mode) == 0o600
    bad = run_module("personal_assistant.daily_ops.clients_sync", dict(env, STRIPE_BAD="1"), tmp_path)
    assert bad.returncode == 1
    invalid = json.loads((root / "clients.json").read_text())
    assert invalid["complete"] is False and invalid["clients"] == []


def test_connector_tenant_mismatch_stops_before_listing(tmp_path):
    fake_stripe(tmp_path)
    cfg = base_config(); cfg["priority"]["connectors"]["clients_sync"] = {"enabled": True, "consent": True, "stripe_account":"acct_other", "stripe_live":False}
    root, cfg_path, log = write_runtime(tmp_path, cfg)
    result = run_module("personal_assistant.daily_ops.clients_sync", env_for(root, cfg_path, log, tmp_path), tmp_path)
    assert result.returncode == 1 and "REFUSED" in result.stdout
    assert all("customers" not in line for line in log.read_text().splitlines())


def test_state_corruption_fails_closed(tmp_path):
    fake_provider(tmp_path)
    root, cfg_path, log = write_runtime(tmp_path)
    state = root / "state" / "daily-ops" / "state.json"; state.parent.mkdir(mode=0o700, parents=True); state.write_text("{")
    result = run_module("personal_assistant.daily_ops.watchdog", env_for(root, cfg_path, log, tmp_path), tmp_path)
    assert result.returncode == 1 and "pipeline failure" in result.stdout and state.read_text() == "{"


def test_command_allowlist_rejects_mutation_and_injection():
    with pytest.raises(Exception):
        from personal_assistant.daily_ops.gog_collector import run
        run("owner@example.com", ["gmail", "thread", "modify", "id"])


def test_geo_pins_dns_and_disables_proxy(monkeypatch):
    monkeypatch.setattr(geo.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])
    captured = []
    class Result: returncode = 0; stdout = "{}"; stderr = ""
    monkeypatch.setattr(geo.subprocess, "run", lambda command, **kwargs: captured.append(command) or Result())
    geo._curl_json("https://nominatim.openstreetmap.org/search?q=x", pinned=("nominatim.openstreetmap.org", "93.184.216.34"))
    assert "--noproxy" in captured[0] and "*" in captured[0] and "--resolve" in captured[0]


def test_r5_automation_remains_bounded_and_inert(tmp_path):
    from personal_assistant.automation import suggest_automation_jobs
    result = suggest_automation_jobs([{"kind":"daily_brief", "accepted":True}, {"kind":"due_source_check", "accepted":True, "source_ref":"example-feed"}], destination="example-topic", destination_verified=True, timezone="Asia/Bangkok")
    assert len(result["jobs"]) == 2 and result["install"] is False and result["max_jobs"] == 2


def test_r5_api_suggestions_feed_daily_ops_collectors(tmp_path):
    from personal_assistant.entry import dispatch

    fake_provider(tmp_path)
    root, cfg_path, log = write_runtime(tmp_path)
    seed_trip(root)
    dispatch(root, {"operation": "automations", "data": {
        "action": "preferences", "changes": {"timezone": "Asia/Bangkok"}
    }})
    for kind, source_ref in (("daily_brief", None), ("due_source_check", "example-feed")):
        rule = {
            "kind": kind, "accepted": True, "destination": "example-topic",
            "destination_verified": True, "timezone": "Asia/Bangkok",
        }
        if source_ref:
            rule["source_ref"] = source_ref
        dispatch(root, {"operation": "automations", "data": {
            "action": "rule", "rule_id": kind, "rule": rule
        }})
    suggestions = dispatch(root, {"operation": "automations", "data": {"action": "suggest"}})
    assert len(suggestions["jobs"]) == 2
    assert {job["collector"] for job in suggestions["jobs"]} == {
        "personal_assistant.daily_ops.morning_brief",
        "personal_assistant.daily_ops.evening_register",
    }
    env = env_for(root, cfg_path, log, tmp_path)
    morning = run_module("personal_assistant.daily_ops.morning_brief", env, tmp_path)
    evening = run_module("personal_assistant.daily_ops.evening_register", env, tmp_path)
    assert morning.returncode == evening.returncode == 0
    assert json.loads(morning.stdout)["kind"] == "morning_brief"
    assert json.loads(evening.stdout)["kind"] == "evening_register"


def test_doctor_is_actionable_without_registration(tmp_path):
    fake_provider(tmp_path)
    root, cfg_path, log = write_runtime(tmp_path)
    cfg = json.loads(cfg_path.read_text()); cfg["delivery"]["verified"] = False; cfg_path.write_text(json.dumps(cfg))
    result = run_module("personal_assistant.daily_ops.doctor", env_for(root, cfg_path, log, tmp_path), tmp_path)
    assert result.returncode == 1 and "no jobs were registered" in result.stdout and "verified" in result.stdout


def test_profile_state_lock_and_permissions(tmp_path):
    root, _, _ = write_runtime(tmp_path)
    path = root / "state" / "daily-ops" / "state.json"
    with config.state_transaction(path) as state:
        state["x"] = 1
    assert json.loads(path.read_text())["x"] == 1
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_doctor_reads_existing_pa_automation_rule(tmp_path):
    from personal_assistant.automation import (canonical_notification_payload, claim_notification,
                                               record_notification, upsert_automation_rule)

    fake_provider(tmp_path)
    root, cfg_path, log = write_runtime(tmp_path)
    from personal_assistant.state import Ledger
    ledger = Ledger(root)
    upsert_automation_rule(ledger, "daily_ops", {
        "kind": "due_source_check", "accepted": True,
        "destination": "example-topic", "destination_verified": True,
        "timezone": "Asia/Bangkok", "profile_id": "example-profile",
        "account": "owner@example.com", "rule_revision": "r1",
        "accepted_at": NOW, "verified_at": "2026-09-08T03:01:00+00:00",
    })
    payload = canonical_notification_payload(profile_id="example-profile", account="owner@example.com",
                                              timezone="Asia/Bangkok", destination="example-topic",
                                              rule_id="daily_ops", rule_revision="r1")
    claim_notification(ledger, "occ-daily-ops", rule_id="daily_ops", payload=payload,
                       now="2026-09-08T03:02:00+00:00")
    record_notification(ledger, "occ-daily-ops", "delivered",
                        proof={"provider": "fixture", "receipt_reference": "fixture-acceptance",
                               "observed_at": "2026-09-08T03:03:00+00:00"},
                        now="2026-09-08T03:03:00+00:00")
    cfg = json.loads(cfg_path.read_text())
    cfg["delivery"]["verification"] = {"occurrence_id": "occ-daily-ops", "rule_id": "daily_ops",
                                          "rule_revision": "r1", "receipt_reference": "fixture-acceptance"}
    cfg_path.write_text(json.dumps(cfg))
    result = run_module("personal_assistant.daily_ops.doctor", env_for(root, cfg_path, log, tmp_path), tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PA automation receipt match" in result.stdout
    assert "pa:delivery-verification" not in result.stdout
    assert all(not any(verb in json.loads(line) for verb in ("modify", "send", "reply", "forward", "archive", "delete")) for line in log.read_text().splitlines())


def test_doctor_blocks_mismatched_pa_automation_target(tmp_path):
    from personal_assistant.automation import upsert_automation_rule
    from personal_assistant.state import Ledger

    fake_provider(tmp_path)
    root, cfg_path, log = write_runtime(tmp_path)
    upsert_automation_rule(Ledger(root), "daily_ops", {
        "kind": "daily_brief", "accepted": True,
        "destination": "other-topic", "destination_verified": True,
        "timezone": "Asia/Bangkok",
    })
    result = run_module("personal_assistant.daily_ops.doctor", env_for(root, cfg_path, log, tmp_path), tmp_path)
    assert result.returncode == 1 and "matching accepted PA automation rule" in result.stdout
    assert all(not any(verb in json.loads(line) for verb in ("modify", "send", "reply", "forward", "archive", "delete")) for line in log.read_text().splitlines())


def test_supabase_malformed_project_and_row_shapes_fail_closed(monkeypatch):
    from personal_assistant.daily_ops import clients_sync

    connector = {"supabase_ref": "abcdefghijklmnopqrst"}
    monkeypatch.setattr(clients_sync, "_binary", lambda _: "/bin/supabase")
    responses = iter([
        json.dumps({"projects": {"ref": "abcdefghijklmnopqrst"}}),
        json.dumps({"projects": [{"ref": "abcdefghijklmnopqrst", "status": "ACTIVE"}]}),
        json.dumps({"rows": [None]}),
    ])
    monkeypatch.setattr(clients_sync, "_run", lambda *args, **kwargs: next(responses))
    with pytest.raises(clients_sync.DailyOpsError, match="project list shape invalid"):
        clients_sync.supabase_users(connector)
    with pytest.raises(clients_sync.DailyOpsError, match="row member shape invalid"):
        clients_sync.supabase_users(connector)


def test_state_lock_contention_and_interrupted_write_recovery(tmp_path, monkeypatch):
    state_path = tmp_path / "state" / "daily-ops" / "state.json"
    config.save_state({"stable": 1}, state_path)
    real_replace = config.os.replace
    def fail_replace(*args):
        raise OSError("injected interrupted replace")
    monkeypatch.setattr(config.os, "replace", fail_replace)
    with pytest.raises(config.DailyOpsError, match="written atomically"):
        config.save_state({"stable": 2}, state_path)
    monkeypatch.setattr(config.os, "replace", real_replace)
    assert config.load_state(state_path) == {"stable": 1}
    assert not list(state_path.parent.glob("*.tmp"))

    ready = tmp_path / "holder.ready"
    holder = "\n".join([
        "import pathlib, sys, time",
        "from personal_assistant.daily_ops import config",
        "p = pathlib.Path(sys.argv[1])",
        "ready = pathlib.Path(sys.argv[2])",
        "with config.state_transaction(p) as state:",
        "    state['held'] = True",
        "    ready.write_text('ready')",
        "    time.sleep(0.35)",
    ])
    env = dict(os.environ, PYTHONPATH=str(REPO))
    process = subprocess.Popen([sys.executable, "-c", holder, str(state_path), str(ready)], env=env)
    try:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        started = time.monotonic()
        with config.state_transaction(state_path) as state:
            state["after"] = True
        assert time.monotonic() - started >= 0.20
    finally:
        process.wait(timeout=3)
    assert config.load_state(state_path)["after"] is True


def test_canonical_trip_store_wins_over_legacy_location_file(tmp_path):
    from personal_assistant.daily_ops import trip_context
    root, _, _ = write_runtime(tmp_path)
    (root / "location.json").write_text(json.dumps({"default_base": {"label": "wrong", "lat": 9, "lng": 9}}))
    seed_trip(root)
    context = trip_context.trip_context(base_config(), datetime.fromisoformat(NOW), str(root))
    assert context["source"] == "pa_trip_store" and context["base"]["label"] == "Example base"


def test_leave_by_local_date_phase_identity_and_redaction(tmp_path, monkeypatch):
    from personal_assistant.daily_ops import trip_context
    cfg = base_config()
    cfg["travel"].update({"leave_by": True, "geocoder": {"consent": True}})
    event = {"id": "event-1", "summary": "Prep attendee@client.example", "location": "Example office", "start": {"dateTime": "2026-09-08T06:00:00+00:00"}}
    monkeypatch.setattr(trip_context.geo, "geocode", lambda *_: (3.0, 4.0))
    head = trip_context.leave_by_alerts(cfg, [event], datetime.fromisoformat("2026-09-08T04:45:00+00:00"), lambda *_: 20, base=((1.0, 2.0), "Example base"))
    now = trip_context.leave_by_alerts(cfg, [event], datetime.fromisoformat("2026-09-08T05:26:00+00:00"), lambda *_: 20, base=((1.0, 2.0), "Example base"))
    assert head and now and head[0]["phase"] == "heads" and now[0]["phase"] == "now"
    assert head[0]["key"] != now[0]["key"] and "attendee@client.example" not in head[0]["line"]


def test_provider_shape_faults_invalidate_previous_index(tmp_path, monkeypatch):
    cfg = base_config(); cfg["priority"]["connectors"]["clients_sync"] = {"enabled": True, "consent": True, "stripe_account": "acct_example", "stripe_live": False}
    target = tmp_path / "clients.json"
    target.write_text(json.dumps({"complete": True, "clients": [{"email": "old@client.example"}]}))
    import personal_assistant.daily_ops.clients_sync as cs
    monkeypatch.setattr(cs.shutil, "which", lambda _: "/bin/stripe")
    for response in ('{}', '{"data":[null],"has_more":false}', '{"data":[],"has_more":"false"}'):
        def fake_run(command, timeout=120, response=response):
            if command[1:3] == ["config", "--list"]:
                return "account_id=acct_example\\nlivemode=false"
            return response
        monkeypatch.setattr(cs, "_run", fake_run)
        with pytest.raises(cs.DailyOpsError):
            cs.sync(cfg, str(tmp_path), datetime.fromisoformat(NOW))
        invalid = json.loads(target.read_text())
        assert invalid["complete"] is False and invalid["clients"] == []


def test_repeated_cursor_is_not_accepted(monkeypatch):
    from personal_assistant.daily_ops import common
    monkeypatch.setattr(common, "run", lambda *args, **kwargs: {"threads": [{"id": "x"}], "has_more": True, "next_page_token": "same"})
    with pytest.raises(Exception):
        common.collect_pages("owner@example.com", ["gmail", "search", "invoice"], common.iter_threads, page_size=1, max_items=5)


def test_doctor_scope_requirements_are_per_account(monkeypatch):
    from personal_assistant.daily_ops import doctor
    cfg = base_config(); cfg["accounts"]["personal"] = "personal@example.net"
    monkeypatch.setattr(doctor, "gog_binary", lambda: "/bin/gog")
    monkeypatch.setattr(doctor, "auth_check", lambda: {"accounts": [{"email": "owner@example.com", "valid": True, "scopes": ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/calendar.readonly"]}, {"email": "personal@example.net", "valid": True, "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}]})
    ok, message = doctor.check_scopes(cfg)
    assert ok and "required" in message
    monkeypatch.setattr(doctor, "auth_check", lambda: {"accounts": [{"email": "owner@example.com", "valid": True, "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}]})
    ok, message = doctor.check_scopes(cfg)
    assert not ok and "calendar" in message


def test_pii_scan_covers_arbitrary_text_files_and_exact_allowlist(tmp_path):
    poisoned = tmp_path / "latest-customer.md"
    poisoned.write_text("contact customer@outside.example")
    result = subprocess.run(["bash", str(REPO / "scripts" / "check_release_pii.sh"), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0 and "BLOCKED" in result.stderr


def test_gog_grammar_uses_schema_preserving_real_page_flag(monkeypatch):
    from personal_assistant.daily_ops import common, gog_collector

    captured = []

    class Result:
        returncode = 0
        stderr = ""

        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(command, **kwargs):
        captured.append(command)
        if "--page=p1" in command:
            return Result(json.dumps({"threads": [{"id": "second"}]}))
        return Result(json.dumps({"threads": [{"id": "first"}], "nextPageToken": "p1"}))

    monkeypatch.setattr(gog_collector, "gog_binary", lambda: "/bin/gog")
    monkeypatch.setattr(gog_collector.subprocess, "run", fake_run)
    result = common.collect_pages("owner@example.com", ["gmail", "search", "invoice"],
                                  gog_collector.iter_threads, page_size=1, max_items=5)
    assert result.complete and [item["id"] for item in result.items] == ["first", "second"]
    flat = [part for command in captured for part in command]
    assert "--results-only" not in flat and "--page-token=p1" not in flat and "--page=p1" in flat
    with pytest.raises(gog_collector.DailyOpsError):
        gog_collector.run("owner@example.com", ["gmail", "search", "--help"])
    with pytest.raises(gog_collector.DailyOpsError):
        gog_collector.run("owner@example.com", ["gmail", "search", "invoice", "-o", "json"])
    with pytest.raises(gog_collector.DailyOpsError):
        gog_collector.run("owner@example.com", ["gmail", "search", "invoice", "--page-size=10"])


def test_doctor_rejects_broader_scope_and_missing_live_check(monkeypatch):
    from personal_assistant.daily_ops import doctor

    cfg = base_config()
    monkeypatch.setattr(doctor, "gog_binary", lambda: "/bin/gog")
    monkeypatch.setattr(doctor, "auth_check", lambda: {"accounts": [{
        "email": "owner@example.com", "valid": True,
        "scopes": ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/calendar.modify"],
    }]})
    ok, message = doctor.check_scopes(cfg)
    assert not ok and "unsupported" in message
    monkeypatch.setattr(doctor, "auth_check", lambda: {"accounts": [{
        "email": "owner@example.com",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/calendar.readonly"],
    }]})
    ok, message = doctor.check_scopes(cfg)
    assert not ok and "valid refresh token" in message


def test_supabase_ref_and_rows_fail_before_query(monkeypatch):
    from personal_assistant.daily_ops import clients_sync

    called = []
    monkeypatch.setattr(clients_sync, "_binary", lambda name: called.append(name) or "/bin/supabase")
    with pytest.raises(clients_sync.DailyOpsError, match="configured project ref"):
        clients_sync.supabase_users({"supabase_ref": "--help"})
    assert called == []
    valid = "abcdefghijklmnopqrst"
    monkeypatch.setattr(clients_sync, "_binary", lambda _: "/bin/supabase")
    responses = iter([
        json.dumps({"projects": [{"ref": valid, "status": "ACTIVE"}]}),
        json.dumps({"rows": [{"email": None, "name": ""}]}),
    ])
    monkeypatch.setattr(clients_sync, "_run", lambda *args, **kwargs: next(responses))
    with pytest.raises(clients_sync.DailyOpsError, match="email shape invalid"):
        clients_sync.supabase_users({"supabase_ref": valid})


def test_watchdog_uses_second_page_and_emits_degraded_no_hit(monkeypatch, capsys, tmp_path):
    from personal_assistant.daily_ops import common, trip_context, watchdog

    cfg = base_config()
    cfg["priority"]["static_terms"] = ["invoice"]
    pages = iter([
        {"threads": [{"id": "quiet"}], "nextPageToken": "next"},
        {"threads": [{"id": "hit", "from": "billing@vendor.invalid", "subject": "invoice"}]},
    ])
    monkeypatch.setattr(common, "run", lambda *args, **kwargs: next(pages))
    records, _ = watchdog.p1_alerts(cfg, str(tmp_path), datetime.fromisoformat(NOW), details=True)
    assert records and records[0]["thread_ids"] == ["hit"]

    calendar_pages = iter([
        {"events": [{"id": "cal1"}], "nextPageToken": "cal-next"},
        {"events": [{"id": "cal2"}]},
    ])
    monkeypatch.setattr(common, "run", lambda *args, **kwargs: next(calendar_pages))
    calendar = trip_context.run_calendar_events({"accounts": {"work": "owner@example.com"}})
    assert calendar.complete and [item["id"] for item in calendar.items] == ["cal1", "cal2"]

    monkeypatch.setattr(watchdog, "trip_context", type("Trip", (), {
        "collect_trip": staticmethod(lambda *args, **kwargs: ({"status": "unknown"}, [], True, False)),
    }))
    def incomplete_priority(*args, **kwargs):
        kwargs["coverage"].update({"complete": False, "truncated": True})
        return [], {}
    monkeypatch.setattr(watchdog, "p1_alerts", incomplete_priority)
    root = tmp_path / "profile"
    root.mkdir(mode=0o700)
    cfg_path = root / "daily_ops.config.json"
    cfg_path.write_text(json.dumps(cfg))
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("DAILY_OPS_PROFILE_ROOT", str(root))
    monkeypatch.setenv("DAILY_OPS_CONFIG", str(cfg_path))
    monkeypatch.setenv("DAILY_OPS_NOW", NOW)
    watchdog.main()
    output = capsys.readouterr().out
    packet = json.loads(output)
    assert packet["complete"] is False and packet["truncated"] is True
    assert packet["sections"]["degraded"]["reason"] == "provider coverage incomplete"


def test_common_pagination_missing_cursor_and_cap(monkeypatch):
    from personal_assistant.daily_ops import common

    monkeypatch.setattr(common, "run", lambda *args, **kwargs: {"threads": [], "has_more": True})
    with pytest.raises(Exception, match="cursor"):
        common.collect_pages("owner@example.com", ["gmail", "search", "invoice"], common.iter_threads, page_size=1, max_items=5)
    monkeypatch.setattr(common, "MAX_PAGES", 1)
    monkeypatch.setattr(common, "run", lambda *args, **kwargs: {"threads": [{"id": "x"}], "nextPageToken": "next"})
    result = common.collect_pages("owner@example.com", ["gmail", "search", "invoice"], common.iter_threads, page_size=1, max_items=5)
    assert result.complete is False and result.truncated is True and result.items == [{"id": "x"}]
