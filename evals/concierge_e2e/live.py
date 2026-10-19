"""P2: opt-in real model forwarding; gateway traffic remains loopback-only."""
import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--url", required=True, help="OpenAI-compatible base URL (ending /v1)")
    parser.add_argument("--key-env", required=True)
    parser.add_argument("--answers", type=Path, default=Path(__file__).with_name("owner_answers.json"))
    parser.add_argument("--toolsets", nargs="+", default=["memory", "file"])
    parser.add_argument("--persona", type=Path, help="Persona JSON (seed files, answers by question id); "
                        "runs the interview to its review only")
    args = parser.parse_args()
    key = os.environ.pop(args.key_env)
    pin = Path(os.environ["PA_E2E_HERMES"]).resolve()
    os.environ.update(HOME=tempfile.mkdtemp(prefix="pa-live-parent-"), PYTHONDONTWRITEBYTECODE="1")
    os.environ["HERMES_HOME"] = os.environ["HOME"] + "/.hermes"
    sys.path.insert(0, str(pin))
    from harness import ROOT, ConciergeRig, Text, ToolCall
    from tests.fakes.fake_llm_provider import Error
    exchanges, transcript, turns = [], [], 0

    escaped = (json.dumps(key)[1:-1], json.dumps(key, ensure_ascii=False)[1:-1])

    def redact(value):  # Structural, plus the JSON-escaped forms inside encoded tool arguments.
        if isinstance(value, str):
            for form in (key, *escaped):
                value = value.replace(form, "[REDACTED]")
            return value
        if isinstance(value, dict):
            return {redact(k): redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(v) for v in value]
        return value

    def forward(record):
        nonlocal turns
        body = {**record["body"], "model": args.model, "stream": False}
        if body["messages"][-1]["role"] == "user":
            turns += 1
        if turns > 40:
            return Error(400, "40 bot turn limit reached")
        try:
            request = urllib.request.Request(args.url.rstrip("/") + "/chat/completions",
                json.dumps(body).encode(), {"Content-Type": "application/json", "Authorization": "Bearer " + key})
            with urllib.request.urlopen(request, timeout=90) as response:
                completion = json.load(response)
            safe = redact({"request": body, "response": completion})
            exchanges.append(safe)
            message = safe["response"]["choices"][0]["message"]
            calls = [(c["function"]["name"], json.loads(c["function"]["arguments"])) for c in message.get("tool_calls", [])]
            return ToolCall(*calls[0], parallel=calls[1:], text=message.get("content")) if calls else Text(message.get("content") or "")
        except Exception:
            return Error(502, "Live forwarding failed; endpoint details withheld")

    rig = ConciergeRig(pin, director=forward, toolsets=args.toolsets)
    persona = json.loads(args.persona.read_text()) if args.persona else None
    home = rig.gateway.hermes_home.resolve()
    for relative, text in (persona or {}).get("seed", {}).items():  # Profile files discovery should find.
        path = (home / relative).resolve()
        if Path(relative).is_absolute() or ".." in Path(relative).parts or home not in path.parents:
            rig.close()
            raise SystemExit(f"persona seed must stay inside the temporary profile: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def owner(text):
        assert turns < 40 and len(rig.texts()) < 40, "40 bot turn limit reached"
        start, seen = len(exchanges), len(rig.texts())
        transcript.append("Owner: " + text)
        rig.owner(text, timeout=300)  # Live models need several tool calls on "apply".
        for row in exchanges[start:]:
            transcript.append("Tools: " + json.dumps(row["response"]["choices"][0]["message"].get("tool_calls", [])))
        transcript.extend("Bot: " + t for t in rig.texts()[seen:])

    def setup_state():
        sys.path.insert(0, str(ROOT))
        from personal_assistant import setup
        from personal_assistant.state import Ledger
        try:
            return setup.state(Ledger(rig.gateway.hermes_home, read_only=True))
        except Exception:
            return {}

    def interview():
        """Answer whatever PA's setup record says is next, so skipped questions cannot misalign answers."""
        owner("/pa setup")
        owner("hi")
        consents, kept = 0, False
        for _ in range(14):
            current, last = setup_state(), "\n".join(rig.texts()[-3:]).lower()
            if current.get("status") == "proposed" or "apply all" in last or "apply some" in last:
                break
            if not kept and consents and ("already know" in last or "correction" in last):
                kept = True
                owner("Those are right; keep them.")
            elif not (current.get("answers") or current.get("asked")) and consents < persona.get("consent_rounds", 2):
                consents += 1
                owner(persona["consent"])
            elif current.get("next_question") is None:
                owner("Show the review now.")
            else:
                owner(persona["answers"].get(current["next_question"], "You decide."))
        current = setup_state()
        answers = current.get("answers") or {}
        discovered = sorted(k for k, v in answers.items() if v.get("source") == "discovered")
        result = {"persona": persona["name"], "status": current.get("status"), "asked": current.get("asked"),
                  "discovered": discovered, "expected_discovered": persona.get("expected_discovered", []),
                  "asked_and_discovered": sorted(set(discovered) & set(current.get("asked") or []))}
        (rig.root / "persona-result.json").write_text(json.dumps(result, indent=2))
        transcript.append("Result: " + json.dumps(result))
        failures = [name for name, bad in (
            ("not at the review", result["status"] != "proposed"),
            ("core questions left open", current.get("next_question") is not None),
            ("discovered set differs from expected", set(result["expected_discovered"]) != set(discovered)),
            ("discovered question asked", result["asked_and_discovered"]),
            ("partly known question marked discovered", set(persona.get("must_not_discover", [])) & set(discovered))) if bad]
        if failures:  # Evidence is written first; the exit code then reports the regression.
            raise AssertionError("persona expectations failed: " + ", ".join(failures))

    try:
        rig.start()
        if persona:
            interview()
            return
        for text in ["/pa setup", "hi", *json.loads(args.answers.read_text()), "/new",
                     "When would you check in before my next flight?"]:
            owner(text)
        # The wake is due 8 minutes out, leaving the arming turn time for several model calls.
        departure = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3, minutes=8)
        owner("yes, watch trip T1; departure " + departure.isoformat() + "; arrival " +
              (departure + dt.timedelta(hours=11)).isoformat() + "; check in 180 minutes before departure. "
              "For this synthetic trip I opt in during quiet hours; use hb2_quiet_hours empty and PA quiet hours 00:00 to 00:00.")
        seen = len(rig.texts())
        start_wake = len(exchanges)
        rig.wait(lambda: turns >= 40 or len(rig.texts()) >= 40 or (len(rig.texts()) > seen and any(
            "⟦pulse" in json.dumps(r["request"]["messages"][-1], ensure_ascii=False) for r in exchanges)), "wake and offer", 720)
        assert turns < 40 and len(rig.texts()) < 40, "40 bot turn limit reached"
        rig.settle(300)
        for row in exchanges[start_wake:]:
            transcript.append("Wake tools: " + json.dumps(row["response"]["choices"][0]["message"].get("tool_calls", [])))
        transcript.extend("Bot: " + t for t in rig.texts()[seen:])
    finally:
        try:
            rig.close()
        finally:
            (rig.root / "exchanges.json").write_text(json.dumps(exchanges, indent=2))
            (rig.root / "transcript.md").write_text("\n\n".join(transcript))


if __name__ == "__main__":
    main()
