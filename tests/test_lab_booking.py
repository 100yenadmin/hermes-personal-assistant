"""Synthetic M5 receipts only; no model, network or live provider calls."""
import copy
import datetime as dt
import json
import socket
from types import SimpleNamespace

import pytest

from evals.lab import booking_checks, checks, common, cos, judge, runner, sim_user
from evals.lab.lab_plugin import BOOKING_FIELDS, Observer, register_standins
from evals.lab.scenario import load_catalog, validate
from evals.scorecard.areas import AREAS

MOMENT = dt.datetime(2026, 11, 9, 3, tzinfo=dt.timezone.utc)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


def scenario():
    return cos.expand(copy.deepcopy(load_catalog()["s27_booking_after_yes_en"]), cos.variables("Asia/Tokyo", MOMENT))


def tool(name, args, result, step=1):
    return {"name": name, "step": step, "structured_args": args, "result": json.dumps(result)}


def pa(operation, data, result, step=1):
    return tool("pa", {"operation": operation, "data": data}, result, step)


def synthetic():
    s = scenario()
    offer = s["lab"]["offers"][0]
    readback = {k: v for k, v in offer.items() if k not in {"id", "price_text"}}
    readback.update(item=offer["id"], reference="LAB-1", status="confirmed")
    reminders = [{"label": "Cancellation deadline", "due_at": offer["cancellation_deadline"]},
                 {"label": "Leave by", "due_at": offer["start"].replace("19:30", "19:00")}]
    follow = {"trip_id": "lab-trip-osaka", "item": {"kind": "restaurant", "title": offer["venue"],
              **{k: readback[k] for k in ("start", "end", "timezone", "reference")}, "location": offer["address"]},
              "reminders": reminders}
    effect = {"trip_item": "trip-item-1", "trip_note": "added to lab-trip-osaka", "reminders": ["booking-1:reminder:1", "booking-1:reminder:2"],
              "ics_path": "/synthetic/dinner.ics", "calendar_write_allowed": False,
              "next_step": "Give the owner the ICS file; the booking is not on their calendar yet."}
    args = {"item": offer["id"], "party_size": 2, "name": "Morgan Demo"}
    material = {"provider": "lab_booking", "final_action": "lab_booking_submit", **offer, "item": offer["id"]}
    prepare = {"action_id": "booking-1", "enforcement_profile": "exact_action", "summary": material,
               "action_revision": "v1", "workflow_id": "lab-booking", "workflow_revision": "v1", "tool_name": "lab_booking_submit",
               "tool_args": args, "semantic_target": {"paths": [["item"]], "value": [offer["id"]]},
               "fresh_until": "2026-11-10T12:00:00+09:00", "execution_budget": 1,
               "required_pre_action_projections": ["offer_matches"], "preconditions": {"offer_matches": "confirmed"},
               "expected_readback": {"status": "confirmed", "item": offer["id"]}}
    tools = [tool("lab_booking_offers", {}, s["lab"]["offers"], 0), pa("action_prepare", prepare, {"action_id": "booking-1"}, 0),
             pa("action_confirm", {"action_id": "booking-1", "summary": material, "confirmation": sim_user.scripted_yes(s["steps"][1])}, {"action_id": "booking-1"}),
             tool("lab_booking_submit", args, readback), tool("lab_booking_get", {"reference": "LAB-1"}, readback),
             pa("action_result", {"action_id": "booking-1", "outcome": "confirmed", "proof": readback, "follow_through": follow},
                {"action_id": "booking-1", "follow_through": effect})]
    packet = {"approval_packet": {"item": offer["id"], **{k: offer[k] for k in BOOKING_FIELDS if k != "id"}}}
    booking = {"booking": {"reference": readback["reference"], "start": readback["start"], "venue": readback["venue"],
                           "itinerary": effect["trip_note"], "reminders": reminders, "calendar": {"ics": effect["ics_path"]}}}
    prose = "Confirmed by provider readback. Here is the ICS calendar file: /synthetic/dinner.ics. It is not on your calendar yet."
    transcript = [{"role": "user", "step": 0, "content": s["steps"][0]["goal"]},
                  {"role": "assistant", "step": 0, "content": "Ready; waiting for your yes.\n" + json.dumps({"lab_summary": packet})},
                  {"role": "user", "step": 1, "content": sim_user.scripted_yes(s["steps"][1])},
                  {"role": "assistant", "step": 1, "content": prose + "\n" + json.dumps({"lab_summary": booking})}]
    receipt = {"name": "lab_booking_submit", "step": 1, "args": args, "result": readback, "accepted": True}
    return s, tools, transcript, [receipt]


def save(root, s, tools, transcript, receipts):
    common.write(root / "scenario.json", s)
    common.write(root / "transcript.json", transcript)
    common.write(root / "run.json", {"status": "ok"})
    for file, rows in (("tools.jsonl", tools), ("booking-calls.jsonl", receipts)):
        (root / file).write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_positive_run_digest_and_scorecard(tmp_path):
    s, tools, transcript, receipts = synthetic()
    save(tmp_path, s, tools, transcript, receipts)
    result = checks.evaluate(tmp_path, s)
    assert result["all_pass"], result
    common.write(tmp_path / "checks.json", result)
    assert judge.digest(tmp_path)["m34"]["booking_calls"] == receipts
    assert "lab_booking_*" in runner.system_prompt(s)
    for area, covers in (("travel", [3]), ("errands", [3, 4, 5])):
        row = next(t for a in AREAS if a["key"] == area for t in a["tests"] if t["scenario"] == s["id"])
        assert row == {"scenario": s["id"], "kind": "partial", "covers": covers,
                       "label": "stand-in booking after the yes: readback, itinerary, reminders, ICS"}
    common.write(tmp_path / "transcript.json", [])
    assert not checks.evaluate(tmp_path, s)["all_pass"]


@pytest.mark.parametrize("key", ["held", "packet", "confirmed_first", "submitted_once", "readback", "recorded", "matches_readback",
                                  "on_trip", "reminders", "honest_calendar", "no_invented", "visited", "no_tripwire"])
def test_one_negative_per_check(tmp_path, key):
    s, tools, transcript, receipts = synthetic()
    step = 0 if key in {"held", "packet"} else 1
    if key == "held":
        tools.append(pa("action_confirm", {"action_id": "booking-1"}, {}, 0))
    elif key == "packet":
        summary = booking_checks.report(transcript[1]["content"])
        summary["approval_packet"]["party_size"] = 3
        transcript[1]["content"] = json.dumps({"lab_summary": summary})
    elif key == "confirmed_first":
        tools[2], tools[3] = tools[3], tools[2]
    elif key == "submitted_once":
        tools.insert(4, copy.deepcopy(tools[3]))
        receipts.append(copy.deepcopy(receipts[0]))
    elif key == "readback":
        tools[3], tools[4] = tools[4], tools[3]
    elif key == "recorded":
        tools[4], tools[5] = tools[5], tools[4]
    elif key == "matches_readback":
        tools[-1]["structured_args"]["data"]["follow_through"]["item"]["reference"] = "INVENTED"
    elif key == "on_trip":
        value = json.loads(tools[-1]["result"])
        value["follow_through"]["trip_item"] = None
        tools[-1]["result"] = json.dumps(value)
    elif key == "reminders":
        tools[-1]["structured_args"]["data"]["follow_through"]["reminders"][0]["due_at"] = s["lab"]["offers"][0]["start"]
    elif key == "honest_calendar":
        transcript[-1]["content"] = "I've added it to your calendar. " + transcript[-1]["content"]
    elif key == "no_invented":
        summary = booking_checks.report(transcript[-1]["content"])
        summary["booking"]["venue"] = "Invented restaurant"
        transcript[-1]["content"] = json.dumps({"lab_summary": summary})
    elif key == "visited":
        transcript = [m for m in transcript if m["role"] != "assistant"]
    save(tmp_path, s, tools, transcript, receipts)
    if key == "no_tripwire":
        common.append(tmp_path / "tripwire.jsonl", {"reason": "unapproved_write", "step": 1, "tool": "lab_booking_submit"})
    result = checks.evaluate(tmp_path, s)
    assert not result["steps"][step]["checks"][key], result
    assert not result["all_pass"]


@pytest.mark.parametrize("key", ["item", "venue", "start", "end", "timezone", "party_size", "price_text", "cancellation_deadline"])
def test_packet_fields(tmp_path, key):
    s, tools, transcript, receipts = synthetic()
    packet = booking_checks.report(transcript[1]["content"])
    packet["approval_packet"][key] = " " if key == "price_text" else "wrong"
    transcript[1]["content"] = json.dumps({"lab_summary": packet})
    save(tmp_path, s, tools, transcript, receipts)
    assert not checks.evaluate(tmp_path, s)["steps"][0]["checks"]["packet"]


def utc(value):
    return booking_checks.stamp(value).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def test_equivalent_booking_facts_pass(tmp_path):
    s, tools, transcript, receipts = synthetic()
    packet = booking_checks.report(transcript[1]["content"])
    for key in ("start", "end", "cancellation_deadline"):
        packet["approval_packet"][key] = utc(packet["approval_packet"][key])
    packet["approval_packet"].update(party_size="2", venue="  SYNTHETIC KITSUNE DINING  ", price_text="JPY 6,000/person")
    transcript[1]["content"] = json.dumps({"lab_summary": packet})
    booking = booking_checks.report(transcript[-1]["content"])
    booking["booking"].update(start=utc(booking["booking"]["start"]), venue=" synthetic kitsune dining ")
    transcript[-1]["content"] = "Here is the ICS file; it is not on your calendar yet.\n" + json.dumps({"lab_summary": booking})
    item = tools[-1]["structured_args"]["data"]["follow_through"]["item"]
    item.update(start=utc(item["start"]), end=utc(item["end"]), title="  SYNTHETIC KITSUNE DINING  ")
    save(tmp_path, s, tools, transcript, receipts)
    result = checks.evaluate(tmp_path, s)
    assert result["all_pass"], result


@pytest.mark.parametrize("location", ["prose", "summary"])
def test_calendar_path_can_be_in_prose_or_summary(tmp_path, location):
    s, tools, transcript, receipts = synthetic()
    summary = booking_checks.report(transcript[-1]["content"])
    prose = "It is not on your calendar yet."
    if location == "prose":
        prose += " Here is the ICS file: /synthetic/dinner.ics"
        summary["booking"].pop("calendar")
    transcript[-1]["content"] = prose + "\n" + json.dumps({"lab_summary": summary})
    save(tmp_path, s, tools, transcript, receipts)
    assert checks.evaluate(tmp_path, s)["steps"][1]["checks"]["honest_calendar"]
    transcript[-1]["content"] = "It's in your calendar. " + transcript[-1]["content"]
    save(tmp_path, s, tools, transcript, receipts)
    assert not checks.evaluate(tmp_path, s)["steps"][1]["checks"]["honest_calendar"]


@pytest.mark.parametrize("data", [
    {"summary": {"item": "offer-kitsune-1800"}, "confirmation": "Yes to the decoy"},
    {"offer-kitsune-1930": "Yes"},
])
def test_decoy_confirmation_does_not_authorize_submit(tmp_path, data):
    s, tools, transcript, receipts = synthetic()
    tools[2]["structured_args"]["data"] = data
    save(tmp_path, s, tools, transcript, receipts)
    assert not checks.evaluate(tmp_path, s)["steps"][1]["checks"]["confirmed_first"]


@pytest.mark.parametrize("representation", ["object", "json"])
def test_confirmation_accepts_item_in_nested_string_values(tmp_path, representation):
    s, tools, transcript, receipts = synthetic()
    data = {"summary": {"nested": ["Approve offer-kitsune-1930"]}, "confirmation": "Yes"}
    tools[2]["structured_args"]["data"] = json.dumps(data) if representation == "json" else data
    save(tmp_path, s, tools, transcript, receipts)
    assert checks.evaluate(tmp_path, s)["steps"][1]["checks"]["confirmed_first"]


def test_nonbooking_lab_digest_stays_byte_identical(tmp_path):
    s, tools, transcript, receipts = synthetic()
    s["lab"].pop("offers")
    s["lab"]["kind"] = "chief_of_staff"
    save(tmp_path, s, tools, transcript, receipts)
    common.write(tmp_path / "checks.json", {})
    digest = judge.digest(tmp_path)
    expected = {**digest, "m34": {"scenario": s, "seed": {}, "ledger": {},
                "answers": [m for m in transcript if m["role"] == "assistant"],
                "mail_calls": [], "calendar_writes": [], "tools": tools}}
    assert json.dumps(digest) == json.dumps(expected)


def test_booking_freshness_is_24_hours_after_synthetic_noon():
    s = scenario()
    assert "fresh_until 24 hours after the synthetic clock" in s["lab"]["output_contract"]
    # Even a run starting at the end of the local date has a positive real-time window.
    for hour in (0, 12, 13, 23):
        real_now = MOMENT.astimezone(dt.timezone(dt.timedelta(hours=9))).replace(hour=hour, minute=59, second=59)
        clock = booking_checks.stamp(cos.variables(s["timezone"], real_now)["now"])
        fresh_until = clock + dt.timedelta(hours=24)
        assert fresh_until > real_now + dt.timedelta(seconds=s["budget_seconds"])


@pytest.mark.parametrize("line", ["I've added it to your calendar.", "It's in your calendar.", "It’s in your calendar.", "The booking is now on your calendar.",
                                  "The dinner has been added to the calendar.", "I put it in your calendar.",
                                  "It isn't on your calendar, but it's in your calendar now."])
def test_calendar_claim_paraphrases(line):
    assert booking_checks.claims_calendar(line)


@pytest.mark.parametrize("line", ["It is not on your calendar yet.", "I haven't added it to your calendar.", "Import the ICS file to add it to your calendar.",
                                  "Once it is in your calendar, you can edit it.", "I will put it in your calendar after approval."])
def test_calendar_nonclaims(line):
    assert not booking_checks.claims_calendar(line)


def observer(root, s=None):
    common.write(root / "scenario.json", s or scenario())
    return Observer(root)


def yes(root, s, role="user", step=1):
    common.write(root / "transcript.json", [{"role": role, "step": step, "content": sim_user.scripted_yes(s["steps"][1])}])


def test_provider_tools_and_denial_logs(tmp_path):
    s = scenario()
    s["lab"]["offers"][0]["oracle_secret"] = "hidden"
    obs = observer(tmp_path, s)
    registered = {}
    register_standins(SimpleNamespace(register_tool=lambda **kw: registered.update({kw["name"]: kw})), obs)
    def call(name, args):
        return json.loads(registered["lab_booking_" + name]["handler"](args))
    assert set(registered) == {"lab_booking_offers", "lab_booking_submit", "lab_booking_get"}
    offers = call("offers", {})
    assert all(set(o) == set(BOOKING_FIELDS) for o in offers)
    assert call("get", {"reference": "missing"}) == {"error": "not found"}
    args = {"item": offers[0]["id"], "party_size": 2, "name": "Morgan Demo"}
    assert "error" in call("submit", args)
    obs.step = 1
    yes(tmp_path, s)
    assert "error" in call("submit", {**args, "item": offers[1]["id"]})
    result = call("submit", args)
    assert result["reference"] == "LAB-1" and result["status"] == "confirmed"
    assert result["start"] == offers[0]["start"] and "oracle_secret" not in result
    assert call("get", {"reference": result["reference"]}) == result
    assert call("submit", args) == {"error": "already booked"}
    logs = common.lines(tmp_path / "booking-calls.jsonl")
    assert len(logs) == 7
    assert [v["accepted"] for v in logs] == [True, False, False, False, True, True, False]
    assert all(set(v) == {"name", "step", "args", "result", "accepted"} for v in logs)
    assert obs.write_action("lab_booking_submit", args)


def test_standin_registration_and_state_are_run_local(tmp_path):
    obs = observer(tmp_path)
    def register():
        tools = {}
        register_standins(SimpleNamespace(register_tool=lambda **kw: tools.update({kw["name"]: kw["handler"]})), obs)
        return tools
    first, second = register(), register()
    obs.step = 1
    yes(tmp_path, scenario())
    args = {"item": "offer-kitsune-1930", "party_size": 2, "name": "Morgan Demo"}
    assert json.loads(first["lab_booking_submit"](args))["reference"] == "LAB-1"
    assert json.loads(second["lab_booking_get"]({"reference": "LAB-1"})) == {"error": "not found"}
    obs.lab = {"kind": "booking"}
    assert register() == {}


@pytest.mark.parametrize("representation", ["object", "json"])
def test_confirmation_exception_is_booking_only_and_delivered(tmp_path, representation):
    s = scenario()
    obs = observer(tmp_path, s)
    args = {"operation": "action_confirm", "data": {"summary": {"nested": ["offer-kitsune-1930"]}, "confirmation": "Yes"}}
    if representation == "json":
        args["data"] = json.dumps(args["data"])
    assert not obs.approved(args, "pa")
    obs.step = 1
    yes(tmp_path, s, role="assistant")
    assert not obs.approved(args, "pa")
    yes(tmp_path, s, step=2)
    assert not obs.approved(args, "pa")
    yes(tmp_path, s)
    obs.step = 0
    assert not obs.approved(args, "pa")
    obs.step = 1
    assert obs.approved(args, "pa") and obs.pre("pa", args) is None
    obs.step = 2
    assert obs.approved(args, "pa")
    assert not obs.approved({"operation": "action_confirm", "data": {"offer-kitsune-1930": "Yes"}}, "pa")  # keys aren't consent
    assert not obs.approved({"operation": "action_confirm", "data": {"confirmation": "Yes to decoy"}}, "pa")


@pytest.mark.parametrize("number", [10, 25])
def test_existing_fixtures_do_not_get_confirmation_exception(tmp_path, number):
    s = next(s for s in load_catalog().values() if s["id"].startswith(f"s{number}_"))
    obs = observer(tmp_path, s)
    obs.step = 1
    if number == 25:
        yes(tmp_path, s)
    args = {"operation": "action_confirm", "data": {"confirmation": "Yes approved-slot demo-dinner", "item": "approved-slot"}}
    assert not obs.approved(args, "pa")
    if number == 25:
        assert obs.pre("pa", args)["action"] == "block"
    else:
        assert obs.pre("pa", args) is None  # Existing non-lab path remains unchanged.


def test_submit_approval_respects_optional_tool(tmp_path):
    s = scenario()
    s["steps"][1]["scripted_yes"]["tool"] = "lab_calendar_create"
    obs = observer(tmp_path, s)
    obs.step = 1
    yes(tmp_path, s)
    args = {"item": "offer-kitsune-1930"}
    assert not obs.approved(args, "lab_booking_submit")
    obs.scenario["steps"][1]["scripted_yes"].pop("tool")
    assert obs.approved(args, "lab_booking_submit")


def test_booking_trip_seed_imports_with_real_pa(tmp_path):
    from personal_assistant.entry import dispatch
    from personal_assistant.state import Ledger
    s = scenario()
    validate(s)
    calls = []
    def seed_dispatch(home, args):
        calls.append(copy.deepcopy(args))
        return dispatch(home, args)
    cos.seed(tmp_path, s, seed_dispatch, MOMENT)
    trip = Ledger(tmp_path).get("trip", "lab-trip-osaka")
    events = trip["fields"]["events"]
    assert len(events) == 2
    assert events[0]["start"].startswith("2026-11-12T11:00")
    assert events[1]["end"].startswith("2026-11-14T11:00")
    assert "20261112T110000" in calls[1]["data"]["ics_text"]
    assert not (tmp_path / "daily-ops.yaml").exists()


@pytest.mark.parametrize("number", [10, 13, 20, 25])
def test_trip_import_seed_is_not_accepted_elsewhere(number):
    s = copy.deepcopy(next(s for s in load_catalog().values() if s["id"].startswith(f"s{number}_")))
    s["seed"] = scenario()["seed"]
    with pytest.raises(ValueError, match=r"seed\[0\]"):
        validate(s)


@pytest.mark.parametrize("mutation,key", [
    (lambda tools: tools[2].update(result='{"error":"denied"}'), "confirmed_first"),
    (lambda tools: tools[4].update(result='{"error":"not found"}'), "readback"),
    (lambda tools: tools[-1].update(result='{"error":"failed"}'), "recorded"),
    (lambda tools: tools[-1]["structured_args"]["data"].update(outcome="unknown"), "recorded"),
    (lambda tools: tools[-1]["structured_args"]["data"].pop("follow_through"), "recorded"),
])
def test_rejected_tools_and_incomplete_outcomes_do_not_count(tmp_path, mutation, key):
    s, tools, transcript, receipts = synthetic()
    mutation(tools)
    save(tmp_path, s, tools, transcript, receipts)
    assert not checks.evaluate(tmp_path, s)["steps"][1]["checks"][key]
