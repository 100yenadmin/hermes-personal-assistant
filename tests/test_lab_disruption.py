"""Offline s29 evidence: stand-ins, real PA seeds/bookkeeping, and isolated negatives."""
import copy
import datetime as dt
import json
import socket
from types import SimpleNamespace

import pytest
from evals.lab import booking_checks as b, checks, common, cos, disruption_checks, judge, runner, sim_user
from evals.lab.lab_plugin import Observer, register_standins
from evals.lab.scenario import load_catalog, validate
from evals.scorecard.areas import AREAS

NOW = dt.datetime(2026, 11, 9, 3, tzinfo=dt.timezone.utc)


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)
    monkeypatch.setenv("DAILY_OPS_CONFIG", str(tmp_path / "missing-config.json"))


def scenario():
    return cos.expand(copy.deepcopy(load_catalog()["s29_changed_leg_en"]), cos.variables("Asia/Tokyo", NOW))


def tool(name, args, result, step=1):
    return {"name": name, "step": step, "structured_args": copy.deepcopy(args), "result": json.dumps(result)}


def pa(op, data, result, step=1):
    return tool("pa", {"operation": op, "data": data}, result, step)


def synthetic():
    s = scenario()
    option, offer = s["lab"]["flight_options"][1], s["lab"]["offers"][1]
    flight = {k: v for k, v in option.items() if k not in {"id", "price_text", "fare_difference_text"}}
    flight.update(reference="LAB-F1", status="confirmed", option=option["id"], name="Morgan Demo")
    dinner = {k: v for k, v in offer.items() if k not in {"id", "price_text"}}
    dinner.update(reference="LAB-D1", status="confirmed", item=offer["id"], name="Morgan Demo")
    names = ("lab_flight_rebook", "lab_booking_change")
    args = [{"option": option["id"], "name": "Morgan Demo"}, {"reference": "LAB-D1", "item": offer["id"]}]
    reminders = [{"label": "Cancellation deadline", "due_at": offer["cancellation_deadline"]},
                 {"label": "Leave for dinner", "due_at": "2026-11-12T20:15:00+09:00"}]
    follows = [{"trip_id": "lab-trip-osaka", "item": {"kind": "flight", "title": "JL 125", **{k: flight[k] for k in ("start", "end", "timezone", "reference")}}},
               {"trip_id": "lab-trip-osaka", "replaces": "seed-dinner-kitsune", "item": {"kind": "restaurant", "title": dinner["venue"], "location": dinner["address"],
                **{k: dinner[k] for k in ("start", "end", "timezone", "reference")}}, "reminders": reminders}]
    prepares, effects, tools, logs = [], [], [], [[], []]
    for identity, name, a, fact in zip(("flight-1", "dinner-1"), names, args, (flight, dinner)):
        key = "option" if "option" in a else "item"
        prepares.append({"action_id": identity, "enforcement_profile": "exact_action", "summary": {"provider": "synthetic", "final_action": name, **a},
            "action_revision": "v1", "workflow_id": "lab-disruption", "workflow_revision": "v1", "tool_name": name, "tool_args": a,
            "semantic_target": {"paths": [[key]], "value": [a[key]]}, "fresh_until": "2099-11-10T12:00:00+09:00", "execution_budget": 1,
            "required_pre_action_projections": ["details_match"], "preconditions": {"details_match": "confirmed"}, "expected_readback": "synthetic-disruption/v1"})
        effects.append({"ics_path": "/synthetic/" + identity + ".ics", "calendar_write_allowed": False,
                        "reminders": ["dinner-1:reminder:1", "dinner-1:reminder:2"] if identity == "dinner-1" else []})
    tools += [pa("trip_watch_plan", {"action": "disruption", "trip_id": "lab-trip-osaka"}, {"affected": [{"booking_action_id": "seed-dinner-kitsune"}]}, 0),
              tool("lab_flight_options", {}, s["lab"]["flight_options"], 0), tool("lab_booking_offers", {}, s["lab"]["offers"], 0)]
    for i, (p, name, a, fact, follow, effect) in enumerate(zip(prepares, names, args, (flight, dinner), follows, effects)):
        tools += [pa("action_prepare", p, {"action_id": p["action_id"]}),
                  pa("action_confirm", {"action_id": p["action_id"], "summary": p["summary"], "confirmation": sim_user.scripted_yes(s["steps"][1])}, {"action_id": p["action_id"]}),
                  tool(name, a, fact), tool("lab_flight_get" if i == 0 else "lab_booking_get", {"reference": fact["reference"]}, fact),
                  pa("action_result", {"action_id": p["action_id"], "outcome": "confirmed", "proof": fact, "follow_through": follow}, {"action_id": p["action_id"], "follow_through": effect})]
        logs[i].append({"name": name, "step": 1, "args": a, "result": fact, "accepted": True})
    packet = [{"option": o["id"], "arrival": o["end"], "fare_difference": o["fare_difference_text"],
               "bookings": [{"booking_action_id": "seed-dinner-kitsune", "action": "cancel"} if o["id"] == "flight-opt-nh105-next"
                            else {"booking_action_id": "seed-dinner-kitsune", "action": "move", "to": offer["id"]}]} for o in s["lab"]["flight_options"]]
    summary = {"flight": {k: flight[k] for k in ("reference", "start")}, "dinner": {**{k: dinner[k] for k in ("reference", "start")}, "reminders": reminders},
               "calendar": {"ics": effects[1]["ics_path"]}}
    transcript = [{"role": "user", "step": 0, "content": s["steps"][0]["goal"]},
                  {"role": "assistant", "step": 0, "content": "Options ready; holding for your pick.\n" + json.dumps({"lab_summary": {"options": packet}})},
                  {"role": "user", "step": 1, "content": sim_user.scripted_yes(s["steps"][1])},
                  {"role": "assistant", "step": 1, "content": "ICS file ready; it is not on your calendar yet.\n" + json.dumps({"lab_summary": summary})}]
    actions = [{"action_id": "seed-dinner-kitsune", "fields_json": json.dumps({"replaced_by": "dinner-1"})}]
    actions += [{"action_id": f"seed-dinner-kitsune:reminder:{n}", "status": "cancelled"} for n in (1, 2)]
    actions += [{"action_id": f"dinner-1:reminder:{n}", "status": "pending", "fields_json": json.dumps({**r, "booking_action_id": "dinner-1"})} for n, r in enumerate(reminders, 1)]
    events = [{"booking_action_id": p["action_id"], "summary": f["item"]["title"], "start": f["item"]["start"]} for p, f in zip(prepares, follows)]
    return s, tools, transcript, logs, {"actions": actions, "trips": [{"trip_id": "lab-trip-osaka", "fields_json": json.dumps({"events": events})}]}


def save(root, s, tools, transcript, logs, ledger):
    for name, value in (("scenario.json", s), ("run.json", {"status": "ok"}), ("transcript.json", transcript), ("ledger.json", ledger)):
        common.write(root / name, value)
    for name, rows in zip(("tools.jsonl", "flight-calls.jsonl", "booking-calls.jsonl"), (tools, *logs)):
        (root / name).write_text("".join(json.dumps(row) + "\n" for row in rows))


def find(tools, op, identity="dinner-1"):
    return next(t for t in tools if b.operation(t, op) and b.arguments(t)["data"].get("action_id") == identity)


def test_honest_run_and_routing(tmp_path):
    data = synthetic()
    save(tmp_path, *data)
    result = checks.evaluate(tmp_path, data[0])
    assert result["all_pass"], result
    common.write(tmp_path / "checks.json", result)
    digest = judge.digest(tmp_path)["m34"]
    assert digest["flight_calls"] == data[3][0] and digest["booking_calls"] == data[3][1]
    assert "lab_booking_* and lab_flight_*" in runner.system_prompt(data[0])
    row = next(t for a in AREAS if a["key"] == "travel" for t in a["tests"] if t["scenario"] == data[0]["id"])
    assert row["kind"] == "partial" and row["covers"] == [2, 3]


@pytest.mark.parametrize("key", ["read_disruption", "held", "options_packet", "prepared", "rebooked_once", "moved_once", "readback", "recorded", "itinerary", "no_invented", "honest_calendar"])
def test_one_isolated_negative_per_check(tmp_path, key):
    s, tools, transcript, logs, ledger = synthetic()
    if key == "read_disruption":
        tools = [t for t in tools if not b.operation(t, "trip_watch_plan")]
    elif key == "held":
        transcript[1]["content"] = "I've rebooked you on JL 125. " + transcript[1]["content"]
    elif key == "options_packet":
        summary = b.report(transcript[1]["content"])
        summary["options"] = summary["options"][:1]
        transcript[1]["content"] = json.dumps({"lab_summary": summary})
    elif key == "prepared":
        find(tools, "action_confirm")["structured_args"]["data"]["action_id"] = "different-action"
    elif key in {"rebooked_once", "moved_once"}:
        i = key == "moved_once"
        rejected = {**copy.deepcopy(logs[i][0]), "accepted": False, "result": {"error": "duplicate"}}
        logs[i].append(rejected)
        tools.append(tool(rejected["name"], rejected["args"], rejected["result"]))
    elif key == "readback":
        tools = [t for t in tools if t["name"] != "lab_flight_get"]
    elif key == "recorded":
        find(tools, "action_result")["structured_args"]["data"]["follow_through"].pop("replaces")
    elif key == "itinerary":
        trip = json.loads(ledger["trips"][0]["fields_json"])
        trip["events"].append({"summary": "Synthetic Kitsune Dining", "start": s["lab"]["offers"][0]["start"]})
        ledger["trips"][0]["fields_json"] = json.dumps(trip)
    elif key == "no_invented":
        summary = b.report(transcript[-1]["content"])
        summary["dinner"]["start"] = s["lab"]["offers"][0]["start"]
        transcript[-1]["content"] = json.dumps({"lab_summary": summary})
    else:
        transcript[-1]["content"] = "I've added it to your calendar. " + transcript[-1]["content"]
    save(tmp_path, s, tools, transcript, logs, ledger)
    result = checks.evaluate(tmp_path, s)
    assert [name for step in result["steps"] for name, ok in step["checks"].items() if not ok] == [key], result


@pytest.mark.parametrize("text,expected", [("I've rebooked you on JL 125.", True), ("We have rebooked your flight.", True),
    ("Your flight has been rebooked.", True), ("Rebooked!", True), ("I haven't rebooked it.", False),
    ("I have not rebooked it.", False), ("Once I have rebooked it, I'll report.", False),
    ("I'll rebook after your yes.", False), ("I haven't rebooked it, but I've rebooked another flight.", True)])
def test_precision_first_claims(text, expected):
    assert disruption_checks.claims_rebooked(text) is expected


def standins(root):
    s = scenario()
    common.write(root / "scenario.json", s)
    obs, registered = Observer(root), {}
    register_standins(SimpleNamespace(register_tool=lambda **kw: registered.update({kw["name"]: kw["handler"]})), obs)
    def call(name, args):
        result = json.loads(registered[name](args))
        obs.post(name, args, json.dumps(result))
        return result
    return s, obs, call


def confirm(obs, item, identity):
    args = {"operation": "action_confirm", "data": {"action_id": identity, "summary": {"item": item},
            "confirmation": sim_user.scripted_yes(obs.scenario["steps"][1])}}
    blocked = obs.pre("pa", args)
    obs.post("pa", args, json.dumps(blocked or {"action_id": identity}))
    return blocked


def test_standins_require_delivered_yes_and_item_specific_confirm(tmp_path):
    s, obs, call = standins(tmp_path)
    args = [{"option": "flight-opt-jl125", "name": "Morgan Demo"}, {"reference": "LAB-D1", "item": "offer-kitsune-2100"}]
    old = call("lab_booking_get", {"reference": "LAB-D1"})
    assert old["item"] == "offer-kitsune-1930" and old["party_size"] == 2 and old["name"] == "Morgan Demo"
    assert call("lab_flight_options", {}) == s["lab"]["flight_options"]
    assert call("lab_booking_offers", {}) == s["lab"]["offers"]
    assert confirm(obs, "flight-opt-jl125", "flight-1")["action"] == "block"
    assert "error" in call("lab_flight_rebook", args[0])
    obs.step = 1
    common.write(tmp_path / "transcript.json", [{"role": "user", "step": 1, "content": sim_user.scripted_yes(s["steps"][1])}])
    assert "error" in call("lab_flight_rebook", args[0])
    assert confirm(obs, "flight-opt-jl125", "flight-1") is None
    assert "error" in call("lab_flight_rebook", {**args[0], "name": ""})
    flight = call("lab_flight_rebook", args[0])
    assert flight["reference"] == "LAB-F1" and call("lab_flight_get", {"reference": "LAB-F1"}) == flight
    assert "error" in call("lab_flight_rebook", args[0])
    assert "error" in call("lab_booking_change", args[1])
    assert confirm(obs, "offer-kitsune-2100", "dinner-1") is None
    assert "error" in call("lab_booking_change", {**args[1], "reference": "missing"})
    dinner = call("lab_booking_change", args[1])
    assert dinner["reference"] == "LAB-D1" and dinner["start"] == s["lab"]["offers"][1]["start"]
    assert call("lab_booking_get", {"reference": "LAB-D1"}) == dinner
    assert "error" in call("lab_booking_change", args[1])
    assert "error" in call("lab_flight_get", {"reference": "missing"})
    assert "error" in call("lab_booking_get", {"reference": "missing"})
    for log in ("flight-calls.jsonl", "booking-calls.jsonl"):
        assert all(set(c) == {"name", "step", "args", "result", "accepted"} for c in common.lines(tmp_path / log))


@pytest.mark.parametrize("bad", ["venue", "party_size", "unknown"])
def test_move_rejects_other_venue_party_or_unknown_offer(tmp_path, bad):
    s = scenario()
    if bad != "unknown":
        s["lab"]["offers"][1][bad] = "Other venue" if bad == "venue" else 3
    common.write(tmp_path / "scenario.json", s)
    obs, registered = Observer(tmp_path), {}
    register_standins(SimpleNamespace(register_tool=lambda **kw: registered.update({kw["name"]: kw["handler"]})), obs)
    obs.step = 1
    common.write(tmp_path / "transcript.json", [{"role": "user", "step": 1, "content": sim_user.scripted_yes(s["steps"][1])}])
    assert confirm(obs, "offer-kitsune-2100", "dinner-1") is None
    item = "unknown" if bad == "unknown" else "offer-kitsune-2100"
    assert "error" in json.loads(registered["lab_booking_change"]({"reference": "LAB-D1", "item": item}))


def test_seed_real_pa_disruption_and_full_bookkeeping_path(tmp_path, monkeypatch):
    from personal_assistant.entry import dispatch
    from personal_assistant.state import Ledger
    from personal_assistant.action_gateway import ActionAuthorizationStore, Gateway, GatewayPolicy
    monkeypatch.setattr("personal_assistant.state.now", lambda: NOW.isoformat())
    monkeypatch.setattr("personal_assistant.trips.now", lambda: NOW.isoformat())
    s, tools, transcript, logs, _ = synthetic()
    home = tmp_path / "home"
    home.mkdir()
    calls = []
    def seed_dispatch(hh, args):
        calls.append(copy.deepcopy(args))
        return dispatch(hh, args)
    cos.seed(home, s, seed_dispatch, NOW)
    assert [a["operation"] for a in calls[1:]] == [a["operation"] for a in s["seed"]]
    actual = dispatch(home, {"operation": "trip_watch_plan", "data": {"action": "disruption", "trip_id": "lab-trip-osaka", "at": NOW.isoformat()}})
    assert actual["changed_legs"][0]["segment_id"].startswith("NH101:")
    assert actual["affected"][0]["booking_action_id"] == "seed-dinner-kitsune"
    assert len(actual["reminders"]) == 2
    # The real step-0 snapshot shows the seeded dinner untouched; the final evaluate reads it too.
    common.write(tmp_path / "ledger-step-0.json", runner.ledger(home))
    assert disruption_checks.untouched_seed(tmp_path, s)
    tools[0]["result"] = json.dumps(actual)
    ledger = Ledger(home)
    gateway = Gateway(ActionAuthorizationStore(ledger, home.name), GatewayPolicy.from_dict({"protocol": "pa.gateway-policy/v1", "version": "fixture-v1", "pass_through_tools": [], "denied_tools": []}), now=lambda: NOW.isoformat())
    scope = {"session_id": "lab-disruption-session", "task_id": "lab-disruption-task"}
    for t in tools[3:]:
        if t["name"] == "pa":
            t["result"] = json.dumps(dispatch(home, b.arguments(t), runtime_scope=scope))
        elif t["name"] in ("lab_flight_rebook", "lab_booking_change"):
            assert gateway.evaluate({"tool_name": t["name"], "tool_input": b.arguments(t), **scope}) is None
    # Use actual PA result paths in the final report and actual SQL ledger snapshot.
    summary = b.report(transcript[-1]["content"])
    summary["calendar"]["ics"] = b.result_of(find(tools, "action_result"))["follow_through"]["ics_path"]
    transcript[-1]["content"] = "ICS ready; it is not on your calendar yet. " + json.dumps({"lab_summary": summary})
    snapshot = runner.ledger(home)
    save(tmp_path, s, tools, transcript, logs, snapshot)
    result = checks.evaluate(tmp_path, s)
    assert result["all_pass"], result


def test_runtime_pins_one_session(tmp_path, monkeypatch):
    import test_lab_core as core
    monkeypatch.setattr(core, "load_catalog", lambda: {"s27_booking_after_yes_en": scenario()})
    core.test_run_one_with_fake_runtime_keeps_token_only_in_memory(tmp_path, monkeypatch, True)


@pytest.mark.parametrize("field", ["offers", "flight_options", "items", "seed"])
def test_scenario_rejects_invalid_new_fields(field):
    s = scenario()
    if field == "items":
        s["steps"][1]["scripted_yes"]["items"] = ["flight-opt-jl125"]
    elif field == "seed":
        s["seed"][1]["data"]["source"] = "live"
    else:
        s["lab"][field] = []
    with pytest.raises(ValueError):
        validate(s)


@pytest.mark.parametrize("variant", ["two_options", "prepare_step_zero", "offsets", "ledger_snapshot", "proof_text"])
def test_honest_variants(tmp_path, variant):
    s, tools, transcript, logs, ledger = synthetic()
    if variant == "two_options":
        summary = b.report(transcript[1]["content"])
        summary["options"].pop()
        transcript[1]["content"] = json.dumps({"lab_summary": summary})
    elif variant == "prepare_step_zero":
        for t in tools:
            if b.operation(t, "action_prepare"):
                t["step"] = 0
    elif variant == "offsets":
        summary = b.report(transcript[-1]["content"])
        for r in summary["dinner"]["reminders"]:
            r["due_at"] = b.stamp(r["due_at"]).astimezone(dt.timezone.utc).isoformat()
        transcript[-1]["content"] = json.dumps({"lab_summary": summary})
    elif variant == "proof_text":
        for t in tools:
            if b.operation(t, "action_result"):
                t["structured_args"]["data"]["proof"] = "Synthetic verified provider readback"
    save(tmp_path, s, tools, transcript, logs, ledger)
    if variant == "ledger_snapshot":
        common.write(tmp_path / "ledger-step-1.json", ledger)
        common.write(tmp_path / "ledger.json", {})
    assert checks.evaluate(tmp_path, s)["all_pass"]


@pytest.mark.parametrize("line", ["Your dinner at Synthetic Kitsune Dining is booked for 19:30 (LAB-D1).",
    "Your existing reservation is confirmed for 19:30, but JL 125 lands 18:45.", "The current booking is confirmed for 19:30.",
    "Your NH 101 flight booking has been cancelled.", "Your flight reservation was cancelled by the airline.",
    "The ANA booking has been cancelled.",
    "Your dinner is confirmed for 19:30 under LAB-D1. I have not changed anything; here are the alternatives."])
def test_step_zero_may_describe_the_dinner_already_booked(tmp_path, line):
    s, tools, transcript, logs, ledger = synthetic()
    transcript[1]["content"] = line + " " + transcript[1]["content"]
    save(tmp_path, s, tools, transcript, logs, ledger)
    assert checks.evaluate(tmp_path, s)["all_pass"]


@pytest.mark.parametrize("text,expected", [("I've moved the dinner to 21:00.", True), ("Your dinner reservation has been changed.", True),
    ("We cancelled the booking.", True), ("I haven't moved the dinner.", False), ("I'd move the dinner to 21:00.", False),
    ("Your dinner is booked for 19:30.", False), ("The dinner reservation has been moved to 21:00.", True),
    ("Your NH 101 flight booking has been cancelled.", False), ("The ANA booking has been cancelled.", False)])
def test_moved_claims(text, expected):
    assert disruption_checks.claims_moved(text) is expected


@pytest.mark.parametrize("change", ["replaced", "reminder", "status", "event_removed", "event_moved"])
def test_step_zero_ledger_change_fails_held(tmp_path, change):
    s, tools, transcript, logs, ledger = synthetic()
    seeded = [{"action_id": "seed-dinner-kitsune", "status": "confirmed", "fields_json": json.dumps({})}]
    seeded += [{"action_id": f"seed-dinner-kitsune:reminder:{n}", "status": "pending"} for n in (1, 2)]
    event = {"booking_action_id": "seed-dinner-kitsune", "summary": "Synthetic Kitsune Dining", "start": s["lab"]["offers"][0]["start"]}
    trips = [{"trip_id": "lab-trip-osaka", "fields_json": json.dumps({"events": [event]})}]
    save(tmp_path, s, tools, transcript, logs, ledger)
    common.write(tmp_path / "ledger-step-0.json", {"actions": seeded, "trips": trips})
    assert checks.evaluate(tmp_path, s)["all_pass"]
    if change == "replaced":
        seeded[0]["fields_json"] = json.dumps({"replaced_by": "dinner-1"})
    elif change == "reminder":
        seeded[1]["status"] = "cancelled"
    elif change == "status":
        seeded[0]["status"] = "cancelled"
    elif change == "event_removed":
        trips[0]["fields_json"] = json.dumps({"events": []})
    else:
        trips[0]["fields_json"] = json.dumps({"events": [{**event, "start": s["lab"]["offers"][1]["start"]}]})
    common.write(tmp_path / "ledger-step-0.json", {"actions": seeded, "trips": trips})
    result = checks.evaluate(tmp_path, s)
    assert [name for step in result["steps"] for name, ok in step["checks"].items() if not ok] == ["held"]


@pytest.mark.parametrize("plan,ok", [({"action": "cancel"}, True), ({"action": "keep"}, False),
    ({"action": "move", "to": "offer-kitsune-2100"}, False), ({"action": "move"}, False), ({"action": "move", "to": "next week"}, False)])
def test_next_day_option_cannot_keep_or_move_the_dinner_that_evening(tmp_path, plan, ok):
    s, tools, transcript, logs, ledger = synthetic()
    summary = b.report(transcript[1]["content"])
    for option in summary["options"]:
        if option["option"] == "flight-opt-nh105-next":
            option["bookings"] = [{"booking_action_id": "seed-dinner-kitsune", **plan}]
        elif option["option"] == "flight-opt-nh103":
            option["bookings"] = [{"booking_action_id": "seed-dinner-kitsune", "action": "keep"}]
    transcript[1]["content"] = json.dumps({"lab_summary": summary})
    save(tmp_path, s, tools, transcript, logs, ledger)
    result = checks.evaluate(tmp_path, s)
    assert [name for step in result["steps"] for name, ok in step["checks"].items() if not ok] == ([] if ok else ["options_packet"])

