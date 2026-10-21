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

    def loads(value):
        try:
            value = json.loads(value) if isinstance(value, str) else value
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def recorded_asks(rows):
        """IDs in setup `record` calls' `asked`; the saved `asked` list is deduplicated and hides re-asks."""
        asked = set()
        for row in rows:
            for call in (((row.get("response") or {}).get("choices") or [{}])[0].get("message") or {}).get("tool_calls") or []:
                function = call.get("function") or {}
                arguments = loads(function.get("arguments"))
                data = loads(arguments.get("data"))
                if function.get("name") == "pa" and arguments.get("operation") == "setup" and data.get("action") == "record":
                    asked |= {q for q in data.get("asked") or [] if isinstance(q, str)}
        return asked

    def answer_until_review(since, consents=0, answered=None):
        """Answer whatever PA's setup record says is next, so skipped questions cannot misalign answers."""
        kept = False
        for _ in range(14):
            current, last = setup_state(), "\n".join(rig.texts()[since:][-3:]).lower()
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
                if answered is not None:
                    answered.add(current["next_question"])
                owner(persona["answers"].get(current["next_question"], "You decide."))
        return setup_state()

    def interview():
        section = persona.get("section", "core")
        owner("/pa setup" + (" " + section if section != "core" else ""))
        begin = setup_state()
        sitting, asked_before = begin.get("sitting_group"), set(begin.get("asked") or [])
        from personal_assistant.setup import PROFILE_GROUPS  # Importable once setup_state() has run.
        groups = dict(PROFILE_GROUPS)
        owner("hi")
        current = answer_until_review(0)
        first_asked, first_answered = set(current.get("asked") or []), set(current.get("answers") or {})
        sittings = [{"group": sitting, "asked": sorted(first_asked - asked_before),
                     "discovered": sorted(k for k, v in (current.get("answers") or {}).items() if v.get("source") == "discovered")}]
        failures = [name for name, bad in (
            ("not at the review", current.get("status") != "proposed"),
            ("sitting questions left open", not next((g["done"] for g in current.get("groups", []) if g["group"] == sitting), False)
             if section == "profile" else current.get("next_question") is not None),
            ("asked outside the sitting", section == "profile" and first_asked - asked_before
             - set(groups.get(sitting, ())))) if bad]
        if section == "profile" and persona.get("sittings", 1) == 2:
            owner("Apply all.")
            while setup_state().get("status") != "applied" and turns < 40 and len(rig.texts()) < 40:
                owner("Apply all.")
            if setup_state().get("status") != "applied":
                failures.append("apply did not complete")
            else:
                owner("/new")
                seen, start, answered = len(rig.texts()), len(exchanges), set()  # Sitting 1's review must not end sitting 2.
                owner("grill me")
                current = answer_until_review(seen, consents=1, answered=answered)
                second = current.get("sitting_group")
                second_asked = recorded_asks(exchanges[start:]) | answered
                first_request = exchanges[start]["request"]["messages"] if len(exchanges) > start else None
                stale = first_request is None or any(m.get("role") == "user" and "Apply all." in json.dumps(
                    m.get("content"), ensure_ascii=False) for m in first_request if isinstance(m, dict))
                sittings.append({"group": second, "asked": sorted(second_asked),
                                 "discovered": sorted(k for k, v in (current.get("answers") or {}).items()
                                                      if v.get("source") == "discovered" and k not in sittings[0]["discovered"])})
                failures += [name for name, bad in (
                    ("/new did not start a fresh session", stale),
                    ("sitting 2 not at the review", current.get("status") != "proposed"),
                    ("sitting 2 questions left open", not next((g["done"] for g in current.get("groups", []) if g["group"] == second), False)),
                    ("re-asked across sittings", second_asked & (set(persona.get("expected_discovered", [])) | first_answered | first_asked)),
                    ("asked outside sitting 2", second_asked - set(groups.get(second, ()))),
                    ("sitting 2 did not move on", second == sitting)) if bad]
        current = setup_state()
        answers = current.get("answers") or {}
        discovered = sorted(k for k, v in answers.items() if v.get("source") == "discovered")
        result = {"persona": persona["name"], "status": current.get("status"), "asked": current.get("asked"),
                  "discovered": discovered, "expected_discovered": persona.get("expected_discovered", []),
                  "asked_and_discovered": sorted(set(discovered) & set(current.get("asked") or [])), "sittings": sittings}
        (rig.root / "persona-result.json").write_text(json.dumps(result, indent=2))
        transcript.append("Result: " + json.dumps(result))
        failures += [name for name, bad in (
            ("discovered set differs from expected", set(result["expected_discovered"]) != set(discovered)),
            ("discovered question asked", result["asked_and_discovered"]),
            ("partly known question marked discovered", set(persona.get("must_not_discover", [])) & set(discovered))) if bad]
        if failures:  # Evidence is written first; the exit code then reports the regression.
            raise AssertionError("persona expectations failed: " + ", ".join(failures))

    def profile_rows():
        sys.path.insert(0, str(ROOT))
        from personal_assistant.profile import _rows
        from personal_assistant.state import Ledger
        try:
            return [{"identity": r["action_id"], "kind": r["action_type"], **r["fields"]}
                    for r in _rows(Ledger(rig.gateway.hermes_home, read_only=True))]
        except Exception:
            return []

    def owner_memory():
        """Statements in one session; after /new, PA's first-turn note and the agent's replies must honour them."""
        for text in persona["statements"]:
            owner(text)
        rows = profile_rows()
        failures = [f"no active record matching {want!r}" for want in persona["recorded"]
                    if not any(r["state"] in {"active", "filed"} and want.casefold() in json.dumps(r, ensure_ascii=False).casefold()
                               for r in rows)]
        failures += [f"superseded text still active: {old!r}" for old in persona.get("retired", [])
                     if any(r["state"] in {"active", "filed"} and r["kind"] == "preference" and old.casefold() in r["text"].casefold()
                            for r in rows)]
        owner("/new")
        start, checks = len(exchanges), []
        for check in persona["after_new"]:
            seen = len(rig.texts())
            owner(check["ask"])
            reply = "\n".join(rig.texts()[seen:])
            checks.append({"ask": check["ask"], "passed": any(w.casefold() in reply.casefold() for w in check["expect_any"])})
        first = json.dumps(exchanges[start]["request"]["messages"], ensure_ascii=False) if len(exchanges) > start else ""
        failures += [name for name, bad in (
            ("/new did not start a fresh session", not first or persona["statements"][0] in first),
            ("first-turn note missing after /new", "Owner preferences and people from PA" not in first)) if bad]
        failures += ["not honoured after /new: " + c["ask"] for c in checks if not c["passed"]]
        result = {"persona": persona["name"], "profile": rows, "after_new": checks, "failures": failures}
        (rig.root / "persona-result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        transcript.append("Result: " + json.dumps(result, ensure_ascii=False))
        if failures:  # Evidence is written first; the exit code then reports the regression.
            raise AssertionError("persona expectations failed: " + ", ".join(failures))

    try:
        rig.start()
        if persona:
            owner_memory() if persona.get("mode") == "owner_memory" else interview()
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
