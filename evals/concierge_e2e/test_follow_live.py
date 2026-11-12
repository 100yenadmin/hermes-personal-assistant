"""P5 manual chase-at runner; never collected as a pytest live-model test."""
import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

__test__ = False


def save(path, data):
    path.write_text(json.dumps(data, indent=2))


def run_scenario(auth, pin, scenario, dest):
    from harness import ConciergeRig
    from personal_assistant.entry import dispatch
    from personal_assistant.state import Ledger
    from evals.concierge_e2e.follow_checks import owner_wakes, score_chase_at

    assert scenario == "chase-at"
    auth.preflight()
    rig = ConciergeRig(pin, live_auth=auth)
    result = dict(scenario=scenario, claim_class="local_e2e_proof", status="FAIL", checks={},
                  evidence=rig.root.name, reason=None)
    snapshot = dict(loops=[], hb2={}, day0_texts=[], wake_texts=[], wake_text_times=[], late_texts=[])
    observed = []

    def call(operation, **data):
        return dispatch(rig.gateway.hermes_home, {"operation": operation, "data": data})

    def observe():
        # rig.texts() has no timestamps. Retain first observation times throughout
        # the quiet interval; never infer quietness from the final transcript.
        texts = rig.texts()[len(snapshot["day0_texts"]):]
        while len(observed) < len(texts):
            observed.append(dt.datetime.now(dt.timezone.utc).isoformat())
        return texts

    try:
        rig.start()
        call("automations", action="preferences", changes={"timezone": "UTC", "quiet_hours": {"start": "00:00", "end": "00:00"}})
        now = dt.datetime.now(dt.timezone.utc)
        asked = (now + dt.timedelta(minutes=10)).replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
        snapshot["asked"] = asked.isoformat()
        save(rig.root / "seed-inputs.json", {"asked": snapshot["asked"]})
        sent = dt.datetime.now(dt.timezone.utc)
        snapshot["dm_sent_at"] = sent.isoformat()
        rig.owner("Cedar Demo still owes us the signed services contract; I checked and no signed copy has arrived. "
                  "If it hasn't arrived by " + asked.strftime("%H:%M") + " UTC today, chase them, but show me the draft first. "
                  "No inbox is connected in this test, so take my word as the source. "
                  "Words only: no web, bookings, real messages or provider actions.", timeout=300)
        snapshot["day0_texts"] = rig.texts()
        snapshot["day0_settled_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        snapshot["hb2"]["before"] = rig.hb2()
        save(rig.root / "baseline-visible.json", snapshot["day0_texts"])
        save(rig.root / "hb2-before.json", snapshot["hb2"]["before"])
        wakes = owner_wakes(snapshot["hb2"]["before"], snapshot["dm_sent_at"], snapshot["asked"])
        wake_ids = {row["id"] for row in wakes}

        def woke():
            texts, rows = observe(), rig.hb2()
            return bool(texts) and any(row["state"] == "done" and row["wake_id"] in wake_ids
                                       and row.get("delivered") in (1, True) for row in rows.get("occurrences", []))

        deadline = min(asked + dt.timedelta(minutes=6), sent + dt.timedelta(minutes=18))
        rig.wait(woke, "owner-asked chase wake and visible DM", max(0, (deadline - dt.datetime.now(dt.timezone.utc)).total_seconds()))
        rig.settle(240)
        snapshot["wake_texts"] = observe()
        snapshot["wake_text_times"] = observed.copy()
        snapshot["hb2"]["after"] = rig.hb2()
        snapshot["loops"] = Ledger(rig.gateway.hermes_home, read_only=True).list("action")
        save(rig.root / "wake-snapshot.json", snapshot)
        tail_start = dt.datetime.now(dt.timezone.utc)
        snapshot["tail_started_at"] = tail_start.isoformat()
        rig.wait(lambda: (dt.datetime.now(dt.timezone.utc) - tail_start).total_seconds() >= 180,
                 "three-minute no-repeat tail", 190)
        snapshot["late_texts"] = rig.texts()[len(snapshot["day0_texts"]) + len(snapshot["wake_texts"]):]
        snapshot["hb2"]["tail"] = rig.hb2()
        snapshot["tail_ended_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    except Exception as exc:
        result["reason"] = auth.scrub(str(exc))
    finally:
        try:
            # Partial evidence is still saved on a wait or product failure.
            if "after" not in snapshot["hb2"] and "day0_settled_at" in snapshot:
                snapshot["wake_texts"] = observe()
                snapshot["wake_text_times"] = observed.copy()
                snapshot["hb2"]["after"] = rig.hb2()
                snapshot["loops"] = Ledger(rig.gateway.hermes_home, read_only=True).list("action")
            save(rig.root / "chase-snapshot.json", snapshot)
            checks = score_chase_at(snapshot)
            expected = {key: True for key in checks}
            failures = [key + ": expected True, got False" for key, value in checks.items() if not value]
            result.update(checks=checks, expected=expected, failures=failures,
                          baseline_messages=len(snapshot["day0_texts"]))
            if not failures and not result["reason"]:
                result["status"] = "PASS"
            result["reason"] = result["reason"] or "; ".join(failures) or "all deterministic checks passed"
            # A PASS is written only after the admission checks below; a crash before them leaves INCOMPLETE, which reruns.
            save(dest / "p5-result.json", {**result, "status": "INCOMPLETE"} if result["status"] == "PASS" else result)
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
        if result["backend_stop"]:
            result.update(status="FAIL", reason="auth/backend admission failed")
        if not isolation["placeholder_unchanged"]:
            result.update(status="FAIL", backend_stop=True, reason="auth isolation invariant failed")
        model_wire = [r for r in wire if r.get("model")]
        if not model_wire or any(r.get("model") != "gpt-6.1-sol" or (r.get("reasoning") or {}).get("effort") != "low"
                                 or r.get("service_tier") not in (None, "") for r in model_wire):
            result.update(status="FAIL", reason="wire model/effort/tier not verified", backend_stop=True)
        transcript = json.loads((rig.root / "transcript.json").read_text())
        (rig.root / "transcript.md").write_text("\n\n".join(
            "### " + str(row.get("role")) + "\n" + str(row.get("content") or "") +
            ("\nTools: " + str(row.get("tool_calls")) if row.get("tool_calls") else "") for row in transcript))
        save(dest / "p5-result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--scenario", choices=("chase-at",), default="chase-at")
    parser.add_argument("--round", type=int, choices=(1, 2))
    args = parser.parse_args()
    from codex_live import LiveAuth
    auth = LiveAuth()
    os.environ.pop("CODEX_HOME", None)
    parent = tempfile.mkdtemp(prefix="pa-p5-parent-")
    os.environ.update(HOME=parent, HERMES_HOME=parent + "/.hermes", PYTHONDONTWRITEBYTECODE="1")
    pin = Path(os.environ["PA_E2E_HERMES"]).resolve()
    sys.path[:0] = [str(pin), str(Path(__file__).resolve().parents[2])]
    results = []
    for round_number in ([args.round] if args.round else (1, 2)):
        scenario = args.scenario
        dest = args.results / f"{scenario}-r{round_number}"
        dest.mkdir(parents=True, exist_ok=True)
        os.environ["PA_E2E_RESULTS"] = str(dest)
        existing = json.loads((dest / "p5-result.json").read_text()) if (dest / "p5-result.json").exists() else {}
        if existing.get("status") in ("PASS", "FAIL"):
            result = existing
            print(scenario, round_number, "preserved completed run", flush=True)
        else:
            try:
                result = run_scenario(auth, pin, scenario, dest)
            except RuntimeError as exc:
                if "token expiring" not in str(exc):
                    raise
                result = dict(scenario=scenario, claim_class="local_e2e_proof", status="NOT_RUN",
                              reason="token expiring", backend_stop=True)
                save(dest / "p5-result.json", result)
            print(scenario, round_number, result["status"], result["reason"][:220], flush=True)
        results.append(result)
        save(args.results / "p5-result.json", results)
        if result.get("backend_stop"):
            raise SystemExit("STOP: auth/backend/wire admission failed; inspect saved receipt")
    raise SystemExit(0 if all(r["status"] == "PASS" for r in results) else 1)


if __name__ == "__main__":
    main()
