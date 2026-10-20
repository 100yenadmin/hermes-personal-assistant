"""P4 manual runner, deliberately not collected as a pytest live-model test."""
import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path


def save(path, data):
    path.write_text(json.dumps(data, indent=2))


def run_scenario(auth, pin, scenario, dest):
    from harness import ConciergeRig
    from personal_assistant.entry import dispatch
    from test_watch import fields, watcher
    auth.preflight()
    rig = ConciergeRig(pin, live_auth=auth, weather=scenario == "weather",
                       observe_settings={"weather_provider": "local" if scenario == "weather" else "off",
                                         "reemit_after_s": 6})
    # One explicit scenario folder, with the rig's snapshots retained below it.
    result = dict(scenario=scenario, claim_class="local_e2e_proof", status="FAIL", checks={},
                  evidence=rig.root.name, reason=None)
    baseline, status_before, initial_lead = [], {}, 180
    checkpoints = []

    def call(operation, **data):
        return dispatch(rig.gateway.hermes_home, {"operation": operation, "data": data})

    def status():
        return call("trip_watch_plan", action="status", trip_id="T3")

    def notice_count():
        return len(fields(rig, "pa:observe:" + rig.watch_id).get("notices", []))

    def wait_notice(count, held=False):
        rig.wait(lambda: notice_count() >= count and (
            any(row["held_reason"] == "held_unanswered" for row in rig.hb2().get("occurrences", [])) if held else
            sum(row["state"] == "done" for row in rig.hb2().get("occurrences", [])) >= count),
            "material notice processing", 240)
        rig.settle(240)
        # Three real polls after completion and past the observer re-emission interval.
        before = watcher(rig)["checks"]
        started = dt.datetime.now(dt.timezone.utc)
        rig.wait(lambda: watcher(rig)["checks"] >= before + 3 and
                 (dt.datetime.now(dt.timezone.utc) - started).total_seconds() > 7,
                 "post-notice deduplication polls", 90)
        checkpoints.append(dict(notices=notice_count(), texts=rig.texts()[len(baseline):], hb2=rig.hb2()))

    try:
        rig.start()
        departure = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0) + dt.timedelta(hours=4)
        departure = departure.replace(minute=departure.minute // 5 * 5)
        arrival = departure + dt.timedelta(hours=2)
        segment = dict(carrier="PA", number="301", origin="LHR", destination="CDG",
                       origin_timezone="UTC", destination_timezone="UTC",
                       scheduled_departure=departure.isoformat(), scheduled_arrival=arrival.isoformat())
        call("automations", action="preferences", changes={"timezone": "UTC", "quiet_hours": {"start": "00:00", "end": "00:00"}})
        call("trip_watch_plan", action="record_facts", trip_id="T3", segments=[segment], source="simulated")
        plan_inputs = dict(trip_id="T3", arm=["watch"], weather=scenario == "weather", hb2_quiet_hours="",
                           airport_lead_minutes=initial_lead,
                           commitments=[{"title": "Synthetic meeting", "at": (arrival + dt.timedelta(hours=1)).isoformat()}])
        save(rig.root / "seed-inputs.json", {"segment": segment, "plan_inputs": plan_inputs})
        rig.owner("Trip T3: yes, please watch my synthetic trip. The flight facts are already in PA. "
                  "Load personal-assistant:trip-concierge, call trip_watch_plan with " + json.dumps(plan_inputs) +
                  ", and arm only the watch in this DM; record the wake receipt. "
                  "Use the plan's pulse_create, except set trigger.check_every to 2s for this loopback test. "
                  "Quiet hours are off and I opt in to alerts for this trip. All concierge alternatives must be "
                  "words only: no web, bookings, real messages, or provider actions.", timeout=300)
        state = status()
        save(rig.root / "armed-status.json", state)
        rig.watch_id = state["inputs"]["watch_argv"][-1]
        rig.wake_id = state["arms"]["watch"]["wake_id"]
        assert rig.wake_id and state["arms"]["watch"]["armed"], "live model did not arm and record watch"
        rig.wait(lambda: bool(fields(rig, "pa:observe:" + rig.watch_id).get("last_run")), "initial observer poll", 90)
        baseline, status_before = rig.texts(), state
        save(rig.root / "baseline-visible.json", baseline)
        if scenario == "weather":
            rig.weather.code = 71
            wait_notice(1)
            save(rig.root / "offer-status.json", status())
            rig.owner("yes, leave earlier", timeout=300)
        else:
            for index, minutes in enumerate((90, 120, 150) if scenario == "never-replies" else (90,)):
                call("trip_watch_plan", action="record_facts", trip_id="T3", source="simulated", segments=[{
                    **segment, "estimated_departure": (departure + dt.timedelta(minutes=minutes)).isoformat(),
                    "estimated_arrival": (arrival + dt.timedelta(minutes=minutes)).isoformat()}])
                wait_notice(index + 1, held=index == 2)
        save(rig.root / "final-status.json", status())
    except Exception as exc:
        result["reason"] = auth.scrub(str(exc))
    finally:
        try:
            notices = fields(rig, "pa:observe:" + rig.watch_id).get("notices", []) if hasattr(rig, "watch_id") else []
            control = fields(rig, "pa:observe-control:" + rig.watch_id) if hasattr(rig, "watch_id") else {}
            offers = [fields(rig, "pa:offer:T3:" + n["offer_type"] + ":" + n["id"]) for n in notices]
            rows = rig.hb2()
            held = [r for r in rows.get("occurrences", []) if r["held_reason"] == "held_unanswered" and r["delivered"] == 0]
            delivered = rig.texts()[len(baseline):] if baseline else []
            offer_messages = checkpoints[0]["texts"] if scenario == "weather" and checkpoints else delivered
            count = len(offer_messages)
            final = status() if status_before else {}
            lead = final.get("inputs", {}).get("airport_lead_minutes", 0)
            watch_lead = fields(rig, "pa:observe-watch:" + rig.watch_id).get("airport_lead_minutes") if hasattr(rig, "watch_id") else None
            checks = dict(offer_count=count, occurrence_recorded=sum(o.get("outcome") not in (None, "reserved") for o in offers),
                          ack_present=sum(n["id"] in control.get("acks", {}) for n in notices),
                          replan_done=lead > initial_lead, held_count=len(held),
                          notice_count=len(notices), observer_lead=watch_lead,
                          accepted=any(o.get("outcome") == "accepted" for o in offers),
                          acked_notice_emits_within_cap=all(n["emits"] <= 3 for n in notices if n["id"] in control.get("acks", {})),
                          watcher_error_streak=watcher(rig)["error_streak"] if hasattr(rig, "wake_id") and rig.wake_id else None)
            text = "\n".join(offer_messages)
            if scenario == "delay":
                # Mechanical text checks only; Claude judges meaning and alternative count.
                meeting = dt.datetime.fromisoformat(plan_inputs["commitments"][0]["at"]).strftime("%H:%M")
                # The offer may name the commitment by its title or by its time ("the 13:35 meeting").
                checks.update(commitment_named="synthetic meeting" in text.lower() or meeting in text,
                              assumed_minutes_present=all(str(n) in text for n in (45, 60, 15)),
                              feasibility_word_present=bool(re.search(r"tight|miss|not feasible|won.t work|no longer works|cannot|can.t|late|unfeasible", text, re.I)))
                checks["listed_alternatives"] = len(re.findall(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+", text))
                checks["at_most_three_listed_alternatives"] = checks["listed_alternatives"] <= 3
            if scenario == "weather" and (rig.root / "offer-status.json").exists():
                leave = json.loads((rig.root / "offer-status.json").read_text())["at_airport_by"]
                expected_leave = (departure - dt.timedelta(minutes=initial_lead + leave["weather_extra_minutes"])).strftime("%H:%M")
                checks.update(new_airport_time_present=leave["local_time"] in text,
                              weather_extra_minutes=leave["weather_extra_minutes"],
                              status_at_airport_by_matches_offer=final.get("at_airport_by", {}).get("local_time") == expected_leave
                              and final.get("at_airport_by", {}).get("weather_extra_minutes") == 0
                              and final.get("at_airport_by", {}).get("severity") == leave["severity"])
            expected = dict(offer_count=2 if scenario == "never-replies" else 1,
                            occurrence_recorded=2 if scenario == "never-replies" else 1,
                            ack_present=2 if scenario == "never-replies" else 1,
                            notice_count=3 if scenario == "never-replies" else 1,
                            held_count=1 if scenario == "never-replies" else 0,
                            acked_notice_emits_within_cap=True, watcher_error_streak=0)
            if scenario == "weather":
                expected.update(accepted=True, replan_done=True, observer_lead=225,
                                new_airport_time_present=True, weather_extra_minutes=45, status_at_airport_by_matches_offer=True)
            if scenario == "delay":
                expected.update(commitment_named=True, assumed_minutes_present=True, feasibility_word_present=True,
                                at_most_three_listed_alternatives=True)
            failures = [f"{k}: expected {v!r}, got {checks.get(k)!r}" for k, v in expected.items() if checks.get(k) != v]
            result.update(checks=checks, expected=expected, failures=failures,
                          wording_review="Claude manual review pending; no model judge",
                          replan_lead=lead, baseline_messages=len(baseline))
            if not failures and not result["reason"]:
                result["status"] = "PASS"
            result["reason"] = result["reason"] or "; ".join(failures) or "all deterministic checks passed"
            save(rig.root / "checkpoints.json", checkpoints)
            save(dest / "p4-result.json", result)
        finally:
            rig.close()
        usage = json.loads((rig.root / "usage.json").read_text())
        result["token_use"] = {key: sum(row[key] for row in usage) for key in
                               ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "api_call_count")}
        result["usage_rows"] = usage
        isolation = json.loads((rig.root / "auth-isolation.json").read_text())
        result["auth_isolation"] = isolation
        wirepath = rig.root / "logs/model-wire.jsonl"
        wire = [json.loads(line) for line in wirepath.read_text().splitlines()] if wirepath.exists() else []
        result["wire"] = wire
        result["backend_stop"] = any(r.get("error") or r.get("status", 200) >= 400 for r in wire)
        if not isolation["placeholder_unchanged"] or not isolation["real_auth_mtime_unchanged"]:
            result.update(status="FAIL", backend_stop=True, reason="auth isolation invariant failed")
        model_wire = [r for r in wire if r.get("model")]
        if not model_wire or any(r.get("model") != "gpt-6.1-sol" or (r.get("reasoning") or {}).get("effort") != "low"
                                 or r.get("service_tier") not in (None, "") for r in model_wire):
            result.update(status="FAIL", reason="wire model/effort/tier not verified", backend_stop=True)
        transcript = json.loads((rig.root / "transcript.json").read_text())
        (rig.root / "transcript.md").write_text("\n\n".join(
            "### " + str(row.get("role")) + "\n" + str(row.get("content") or "") +
            ("\nTools: " + str(row.get("tool_calls")) if row.get("tool_calls") else "") for row in transcript))
        save(dest / "p4-result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--scenario", choices=("delay", "weather", "never-replies"))
    parser.add_argument("--round", type=int, choices=(1, 2))
    args = parser.parse_args()
    from codex_live import LiveAuth
    auth = LiveAuth()
    os.environ.pop("CODEX_HOME", None)
    parent = tempfile.mkdtemp(prefix="pa-p4-parent-")
    os.environ.update(HOME=parent, HERMES_HOME=parent + "/.hermes", PYTHONDONTWRITEBYTECODE="1")
    pin = Path(os.environ["PA_E2E_HERMES"]).resolve()
    sys.path[:0] = [str(pin), str(Path(__file__).resolve().parents[2])]
    results = []
    for round_number in ([args.round] if args.round else (1, 2)):
        for scenario in ([args.scenario] if args.scenario else ("delay", "weather", "never-replies")):
            dest = args.results / f"{scenario}-r{round_number}"
            dest.mkdir(parents=True, exist_ok=True)
            os.environ["PA_E2E_RESULTS"] = str(dest)
            existing = json.loads((dest / "p4-result.json").read_text()) if (dest / "p4-result.json").exists() else {}
            if existing.get("status") in ("PASS", "FAIL"):
                results.append(existing)
                print(scenario, round_number, "preserved completed run", flush=True)
                continue
            try:
                result = run_scenario(auth, pin, scenario, dest)
            except RuntimeError as exc:
                if "token expiring" not in str(exc):
                    raise
                result = dict(scenario=scenario, status="NOT_RUN", reason="token expiring", backend_stop=True)
                save(dest / "p4-result.json", result)
            results.append(result)
            save(args.results / "p4-result.json", results)
            print(scenario, round_number, result["status"], result["reason"][:220], flush=True)
            if result.get("backend_stop"):
                raise SystemExit("STOP: auth/backend/wire admission failed; inspect saved receipt")
    raise SystemExit(0 if all(r["status"] == "PASS" for r in results) else 1)


if __name__ == "__main__":
    main()
