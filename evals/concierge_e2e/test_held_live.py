"""P6 manual live held-watcher/owner-handback runner; never a pytest test."""
import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

__test__ = False


def save(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def tool_calls(messages):
    for row in messages:
        calls = row.get("tool_calls") or []
        for call in json.loads(calls) if isinstance(calls, str) else calls:
            fn = call["function"]
            args = fn.get("arguments") or {}
            args = json.loads(args) if isinstance(args, str) else args
            entries = args.get("calls", [args]) if fn["name"] == "tool_call" else [dict(name=fn["name"], arguments=args)]
            for entry in entries:
                value = entry.get("arguments") or {}
                yield entry["name"], json.loads(value) if isinstance(value, str) else value


def score_held(snapshot):
    """Score immutable checkpoints; wording is a strict time/flight phrase check."""
    held, after = snapshot.get("held", {}), snapshot.get("after", {})
    notice = snapshot.get("notice")
    rows = [r for r in held.get("hb2", {}).get("occurrences", [])
            if r.get("wake_id") == snapshot.get("wake_id") and r.get("held_reason") == "message_held:unanswered"]
    def names_change(text):
        return snapshot.get("changed_time", "MISSING") in text and bool(re.search(r"flight|PA\s*301", text, re.I))
    def records(messages):
        return sum(name == "pa" and args.get("operation") == "trip_offer" and
                   args.get("data", {}).get("action") == "record" and args["data"].get("occurrence") == notice
                   for name, args in tool_calls(messages))
    return dict(
        two_unanswered=len(snapshot.get("sendable", [])) == 2 and all(
            s.get("offer", {}).get("outcome") == "offered" and s.get("acked") and s.get("texts")
            for s in snapshot.get("sendable", [])) and any(
                s.get("unanswered_count") == 2 for s in held.get("hb2", {}).get("sessions", [])),
        held_silent=bool(held) and held.get("texts") == [],
        held_unrecorded=bool(notice) and held.get("offer") == {} and held.get("acked") is False,
        held_respond=bool(rows) and all(r.get("state") == "done" and r.get("force_silent") == 1
            and r.get("delivered") == 0 and r.get("outcome") == "needs_attention" and r.get("notify") == 1
            and bool((r.get("summary") or "").strip()) and len(r.get("summary") or "") < 160 for r in rows),
        owner_recorded=bool(after) and after.get("offer", {}).get("outcome") == "offered" and after.get("acked") is True,
        owner_offer_once=sum(names_change(t) for t in after.get("texts", [])) == 1
            and sum(names_change(t) for t in snapshot.get("visible", [])) == 1,
        owner_turn=any(names_change(str(r.get("content") or "")) for r in snapshot.get("owner_turn", [])
                       if r.get("role") == "assistant") and records(snapshot.get("owner_turn", [])) == 1,
        one_record=bool(notice) and records(snapshot.get("transcript", [])) == 1,
        no_provider_actions=bool(snapshot.get("transcript")) and all(
            name in {"pulse", "skills_list", "skill_view", "tool_search", "tool_describe"} or name == "pa" and args.get("operation") in
            {"trip_watch_plan", "trip_offer", "context", "capabilities", "recipes"}
            for name, args in tool_calls(snapshot.get("transcript", []))),
        watcher_active=after.get("watcher", {}).get("status") == "active"
            and after.get("watcher", {}).get("error_streak") == 0)


def run_scenario(auth, pin, dest):
    from harness import ConciergeRig
    from personal_assistant.entry import dispatch
    from test_watch import fields, watcher
    auth.preflight()
    rig = ConciergeRig(pin, live_auth=auth, observe_settings={"weather_provider": "off", "reemit_after_s": 60})
    result = dict(status="INCOMPLETE", claim_class="local_e2e_proof", evidence=rig.root.name)
    snapshot = {"sendable": []}
    save(dest / "p6-result.json", result)
    def call(operation, **data):
        return dispatch(rig.gateway.hermes_home, {"operation": operation, "data": data})
    def notices():
        return fields(rig, "pa:observe:" + rig.watch_id).get("notices", [])
    def checkpoint(notice, start):
        return dict(notice=notice, hb2=rig.hb2(), texts=rig.texts()[start:], watcher=watcher(rig),
                    offer=fields(rig, "pa:offer:T3:flight_change:" + notice),
                    acked=notice in fields(rig, "pa:observe-control:" + rig.watch_id).get("acks", {}))
    try:
        rig.start()
        departure = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0) + dt.timedelta(hours=4)
        segment = dict(carrier="PA", number="301", origin="LHR", destination="CDG", origin_timezone="UTC",
                       destination_timezone="UTC", scheduled_departure=departure.isoformat(),
                       scheduled_arrival=(departure + dt.timedelta(hours=2)).isoformat())
        call("automations", action="preferences", changes={"timezone": "UTC", "quiet_hours": {"start": "00:00", "end": "00:00"}})
        call("trip_watch_plan", action="record_facts", trip_id="T3", segments=[segment], source="simulated")
        inputs = dict(trip_id="T3", arm=["watch"], weather=False, hb2_quiet_hours="",
                      commitments=[{"title": "Synthetic meeting", "at": (departure + dt.timedelta(hours=5)).isoformat()}])
        save(rig.root / "seed-inputs.json", dict(segment=segment, plan_inputs=inputs))
        rig.owner("Trip T3: watch my synthetic trip; its facts are already in PA. Load personal-assistant:trip-concierge. "
                  "Call trip_watch_plan with " + json.dumps(inputs) + ". Arm only the watch in this DM and record its receipt. "
                  "Use its pulse_create except trigger.check_every=2s for this loopback test. I opt in to trip alerts. "
                  "All options are words only: no web, bookings, provider actions or messages to anyone else.", timeout=300)
        state = call("trip_watch_plan", action="status", trip_id="T3")
        rig.watch_id, rig.wake_id = state["inputs"]["watch_argv"][-1], state["arms"]["watch"]["wake_id"]
        snapshot["wake_id"] = rig.wake_id
        assert watcher(rig)["kind"] == "command" and json.loads(watcher(rig)["trigger_json"])["check_every"] in (2, "2s")
        rig.wait(lambda: bool(fields(rig, "pa:observe:" + rig.watch_id).get("last_run")), "initial observer poll")
        save(rig.root / "armed-status.json", state)
        for index, minutes in enumerate((90, 120, 150)):
            start = len(rig.texts())
            prior = {(r["wake_id"], r["dedupe_key"]) for r in rig.hb2().get("occurrences", [])}
            changed = departure + dt.timedelta(minutes=minutes)
            call("trip_watch_plan", action="record_facts", trip_id="T3", source="simulated",
                 segments=[{**segment, "estimated_departure": changed.isoformat()}])
            rig.wait(lambda: len(notices()) == index + 1, "new delay notice", 240)
            notice = notices()[-1]["id"]
            rig.wait(lambda: any((r["wake_id"], r["dedupe_key"]) not in prior and r["wake_id"] == rig.wake_id and r["state"] == "done"
                     and (r.get("held_reason") == "message_held:unanswered" if index == 2 else r["delivered"] == 1)
                     for r in rig.hb2().get("occurrences", [])
                     if index == 2 or fields(rig, "pa:offer:T3:flight_change:" + notice).get("outcome") == "offered"),
                     "completed delay turn", 300)
            rig.settle(240)
            point = checkpoint(notice, start)
            if index < 2:
                snapshot["sendable"].append(point)
            else:
                snapshot.update(held=point, notice=notice, changed_time=changed.strftime("%H:%M"))
            save(rig.root / "held-snapshot.json", snapshot)
        # Preserve and score the held state before any owner event can change it.
        checks = score_held(snapshot)
        assert all(checks[k] for k in ("two_unanswered", "held_silent", "held_unrecorded", "held_respond")), checks
        with sqlite3.connect(rig.gateway.db_path) as db:
            before = db.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0]
        start = len(rig.texts())
        rig.owner("Any update on my trip?", timeout=300)
        snapshot["after"] = checkpoint(notice, start)
        polls = watcher(rig)["checks"]
        tail = dt.datetime.now(dt.timezone.utc)
        rig.wait(lambda: watcher(rig)["checks"] >= polls + 3 and
                 (dt.datetime.now(dt.timezone.utc) - tail).total_seconds() > 60, "post-ack polls past reemit", 120)
        rig.settle(240)
        snapshot["after"] = checkpoint(notice, start)
        with sqlite3.connect(rig.gateway.db_path) as db:
            db.row_factory = sqlite3.Row
            messages = [dict(r) for r in db.execute("SELECT * FROM messages WHERE id > ? ORDER BY id", (before,))]
        owner = next(i for i, r in enumerate(messages) if r["role"] == "user" and "Any update on my trip?" in str(r["content"]))
        end = next((i for i in range(owner + 1, len(messages)) if messages[i]["role"] == "user"), len(messages))
        snapshot["owner_turn"] = messages[owner:end]
    except Exception as exc:
        result.update(status="FAIL", reason=auth.scrub(str(exc)))
    finally:
        try:
            snapshot["visible"] = rig.texts()
            save(rig.root / "held-snapshot.json", snapshot)
        finally:
            rig.close()
        transcript = json.loads((rig.root / "transcript.json").read_text())
        snapshot["transcript"] = transcript
        save(rig.root / "held-snapshot.json", snapshot)
        checks = score_held(snapshot)
        (rig.root / "transcript.md").write_text("\n\n".join(
            "### " + str(r.get("role")) + "\n" + str(r.get("content") or "") + "\nTools: " + str(r.get("tool_calls") or "") for r in transcript))
        isolation = json.loads((rig.root / "auth-isolation.json").read_text())
        wirepath = rig.root / "logs/model-wire.jsonl"
        wire = [json.loads(line) for line in wirepath.read_text().splitlines()] if wirepath.exists() else []
        admission = bool(wire) and all(not r.get("error") and r.get("status", 0) == 200
            and r.get("model") == "gpt-6.1-sol" and (r.get("reasoning") or {}).get("effort") == "low"
            and r.get("service_tier") in (None, "") for r in wire) and isolation["placeholder_unchanged"]
        usage = json.loads((rig.root / "usage.json").read_text())
        result.update(checks=checks, wire=wire, auth_isolation=isolation, usage_rows=usage,
                      token_use={k: sum(r[k] for r in usage) for k in
                                 ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "api_call_count")})
        result.update(status="PASS" if all(checks.values()) and admission and not result.get("reason") else "FAIL",
                      failures=[k for k, v in checks.items() if not v], admission=bool(admission))
        result.setdefault("reason", "all checks passed" if result["status"] == "PASS" else "check/admission failure; inspect transcript.md")
        if result["status"] == "FAIL":
            result["transcript_excerpt"] = transcript[-8:]
        save(dest / "p6-result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    dest = args.results.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "p6-result.json").exists():
        raise SystemExit("Use a fresh --results directory; preserve prior evidence")
    save(dest / "p6-result.json", dict(status="INCOMPLETE", reason="initialization pending"))
    from codex_live import LiveAuth
    try:
        auth = LiveAuth()
    except Exception:
        save(dest / "p6-result.json", dict(status="NOT_RUN", reason="token missing, invalid or expiring"))
        raise SystemExit(1)
    os.environ.pop("CODEX_HOME", None)
    parent = tempfile.mkdtemp(prefix="pa-p6-parent-", dir=os.environ["TMPDIR"])
    os.environ.update(HOME=parent, HERMES_HOME=parent + "/.hermes", PYTHONDONTWRITEBYTECODE="1", PA_E2E_RESULTS=str(dest))
    from test_follow_live import bind_paths
    pin = Path(os.environ["PA_E2E_HERMES"]).resolve()
    assert pin.name == "v0.23.1-3b42157", "P6 requires the prepared Hermes v0.23.1 pin"
    assert re.search(r'^version:\s*[\"\']?0\.4\.16[\"\']?\s*$',
                     (Path(os.environ["PA_E2E_HEARTBEAT2"]) / "plugin.yaml").read_text(), re.M), "P6 requires HB2 0.4.16"
    bind_paths(pin)
    result = run_scenario(auth, pin, dest)
    print(result["status"], result["reason"][:220], flush=True)
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
