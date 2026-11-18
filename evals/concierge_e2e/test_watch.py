"""P3: real HB2 scheduled command probes; all inputs and delivery are loopback."""
import datetime as dt
import json
import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(420, method="signal")


def pa(operation, **data):
    from harness import ToolCall
    return ToolCall("pa", {"operation": operation, "data": data})


def result(record):
    return json.loads(record["body"]["messages"][-1]["content"])


def fields(rig, identity):
    from personal_assistant.state import Ledger
    return (Ledger(rig.gateway.hermes_home, read_only=True).get("action", identity) or {}).get("fields", {})


def watcher(rig):
    return next(row for row in rig.hb2()["wakes"] if row["id"] == rig.wake_id)


def assert_no_errors(rig):
    rows = rig.hb2()
    assert watcher(rig)["error_streak"] == 0, rows
    assert sum(row["errors"] for row in rows["ledger"] if row["wake_id"] == rig.wake_id) == 0, rows
    assert not rig.director.errors, rig.director.errors


def arm_watch(rig, weather=False, *, request_mute_exemption=True):
    from harness import Text, ToolCall
    departure = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0) + dt.timedelta(hours=3)
    arrival = departure + dt.timedelta(hours=2)
    rig.segment = dict(carrier="PA", number="301", origin="LHR", destination="CDG",
                       origin_timezone="UTC", destination_timezone="UTC",
                       scheduled_departure=departure.isoformat(), scheduled_arrival=arrival.isoformat())

    def arm(record):
        rig.plan = result(record)
        entry, = rig.plan["arm"]
        assert entry["requires"]["hb2_probe_command"] == rig.observer_command
        pulse = entry["pulse_create"]
        assert pulse["trigger"]["check_every"] == "15m"
        assert pulse["owner_asked"] is True
        # Shorten the poll cadence and let the held-message case exercise the mute.
        return ToolCall("pulse", {**pulse, "owner_asked": request_mute_exemption,
                                  "trigger": {**pulse["trigger"], "check_every": "2s"}})

    def receipt(record):
        created = result(record)
        assert created["armed"] is True, created
        rig.wake_id = created["wake"]["id"]
        rig.watch_id = rig.plan["inputs"]["watch_argv"][-1]
        owner_requested = created["wake"].get("owner_requested")
        grant = {"owner_asked": owner_requested} if owner_requested is not None else {}
        return pa("trip_watch_plan", action="record_wake", trip_id="T3", moment="watch", wake_id=rig.wake_id, **grant)

    rig.director.actions = [
        pa("automations", action="preferences", changes={"timezone": "UTC", "quiet_hours": {"start": "00:00", "end": "00:00"}}),
        pa("trip_watch_plan", action="record_facts", trip_id="T3", segments=[rig.segment], source="simulated"),
        pa("trip_watch_plan", trip_id="T3", arm=["watch"], weather=weather, hb2_quiet_hours="",
           commitments=[{"title": "Synthetic meeting", "at": (arrival + dt.timedelta(hours=1)).isoformat()}]),
        arm, receipt, Text("Trip watch armed.")]
    rig.owner("Trip T3: please watch it", "Trip watch armed.")
    assert not rig.director.errors, rig.director.errors
    assert watcher(rig)["kind"] == "command" and watcher(rig)["status"] == "active", rig.hb2()
    rig.wait(lambda: bool(fields(rig, "pa:observe:" + rig.watch_id).get("last_run")), "first scheduled observer poll")
    assert fields(rig, "pa:observe:" + rig.watch_id)["last_run"]["result"] == "idle"


@pytest.mark.parametrize("rig", [{"hb2_settings": {"max_unanswered": 4},
                                      "observe_settings": {"weather_provider": "off", "reemit_after_s": 6}}], indirect=True)
def test_watch_delay_offer_once(rig):
    from harness import Director, Text, ToolCall
    from personal_assistant.entry import dispatch

    arm_watch(rig)
    occurrences = []

    def wake(record):
        user = next(m for m in reversed(record["body"]["messages"]) if m["role"] == "user")
        text = Director._text(user)
        assert "⟦pulse" in text and "Trip watch" in text, text
        occurrence = re.search(r"occurrence=(n_[0-9a-f]{8})", text).group(1)
        offer_type = re.search(r"offer_type=([a-z_]+)", text).group(1)
        (rig.root / "delay-wake.json").write_text(json.dumps({"text": text, "occurrence": occurrence,
                                                            "offer_type": offer_type}, indent=2))
        assert offer_type == "flight_change", text
        occurrences.append(occurrence)
        return pa("trip_offer", action="check", trip_id="T3", offer_type=offer_type, occurrence=occurrence)

    def offer(record):
        assert result(record)["allowed"] is True, result(record)
        return pa("trip_offer", action="record", trip_id="T3", offer_type="flight_change",
                  occurrence=occurrences[-1], outcome="offered")

    final = "OFFER-DELAY: your flight is delayed by 90 minutes."
    rig.director.actions = [wake, offer,
        ToolCall("pulse", {"action": "respond", "outcome": "progress", "notify": True, "summary": "One delay offer."}), Text(final)]
    injected = dispatch(rig.gateway.hermes_home, {"operation": "trip_watch_plan", "data": {
        "action": "record_facts", "trip_id": "T3", "source": "simulated",
        "segments": [{**rig.segment, "estimated_departure":
                      (dt.datetime.fromisoformat(rig.segment["scheduled_departure"]) + dt.timedelta(minutes=90)).isoformat()}]}})
    assert injected["changed"] is True
    rig.wait(lambda: rig.director.errors or final in rig.texts(), "scheduled delay offer")
    rig.gateway.wait_idle(timeout=30)
    assert_no_errors(rig)
    before = watcher(rig)["checks"]
    emitted_at = dt.datetime.now(dt.timezone.utc)
    rig.wait(lambda: watcher(rig)["checks"] >= before + 3 and
             (dt.datetime.now(dt.timezone.utc) - emitted_at).total_seconds() > 6, "post-ack polls past reemit interval")
    assert rig.texts().count(final) == 1
    assert not rig.director.actions
    assert len(rig.hb2()["occurrences"]) == 1, rig.hb2()
    occurrence, = occurrences
    assert fields(rig, "pa:offer:T3:flight_change:" + occurrence)["outcome"] == "offered"
    assert occurrence in fields(rig, "pa:observe-control:" + rig.watch_id)["acks"]
    notice, = fields(rig, "pa:observe:" + rig.watch_id)["notices"]
    assert notice["emits"] == 1
    assert_no_errors(rig)


def notice_check(rig, occurrences, offer_type, signals=()):
    def wake(record):
        from harness import Director
        user = next(m for m in reversed(record["body"]["messages"]) if m["role"] == "user")
        text = Director._text(user)
        assert "⟦pulse" in text and "Trip watch" in text, text
        assert "offer_type=" + offer_type in text, text
        assert all(signal in text for signal in signals), text
        occurrence = re.search(r"occurrence=(n_[0-9a-f]{8})", text).group(1)
        occurrences.append(occurrence)
        return pa("trip_offer", action="check", trip_id="T3", offer_type=offer_type, occurrence=occurrence)
    return wake


def offer_actions(rig, occurrences, offer_type, final, signals=()):
    from harness import Text, ToolCall

    def record_offer(record):
        assert result(record)["allowed"] is True, result(record)
        return pa("trip_offer", action="record", trip_id="T3", offer_type=offer_type,
                  occurrence=occurrences[-1], outcome="offered")

    def respond(record):
        assert result(record)["fields"]["outcome"] == "offered", result(record)
        return ToolCall("pulse", {"action": "respond", "outcome": "progress", "notify": True,
                                  "summary": "Synthetic offer for " + occurrences[-1]})

    return [notice_check(rig, occurrences, offer_type, signals), record_offer, respond, Text(final)]


def past_reemit(rig):
    before, emitted_at = watcher(rig)["checks"], dt.datetime.now(dt.timezone.utc)
    rig.wait(lambda: watcher(rig)["checks"] >= before + 3 and
             (dt.datetime.now(dt.timezone.utc) - emitted_at).total_seconds() > 6,
             "three scheduled polls past reemit interval")
    assert_no_errors(rig)


@pytest.mark.parametrize("rig", [{"weather": True, "hb2_settings": {"max_unanswered": 4},
                                      "observe_settings": {"reemit_after_s": 6}}], indirect=True)
def test_weather_offer_then_decline(rig):
    from harness import Text, ToolCall
    arm_watch(rig, weather=True)
    assert fields(rig, "pa:observe:" + rig.watch_id)["weather"]["last"]["severity"] == "clear"
    occurrences, final = [], "OFFER-WEATHER: leave earlier for snow."
    rig.director.actions = offer_actions(rig, occurrences, "weather_leave_early", final,
                                         ("Be at the airport by", "+45 min for snow"))
    rig.weather.code = 71
    rig.wait(lambda: rig.director.errors or final in rig.texts(), "snow leave-earlier offer")
    rig.gateway.wait_idle(timeout=30)
    assert_no_errors(rig)
    rig.director.actions = [pa("trip_offer", action="record", trip_id="T3", offer_type="weather_leave_early",
                              occurrence=occurrences[0], outcome="declined"), Text("Decline recorded.")]
    rig.owner("no thanks", "Decline recorded.")
    assert fields(rig, "pa:offer:T3:weather_leave_early")["outcome"] == "declined"

    def silence(record):
        assert result(record) == {"allowed": False, "reason": "declined"}, result(record)
        return ToolCall("pulse", {"action": "respond", "outcome": "progress", "notify": False,
                                  "summary": "Declined weather offer stays silent."})

    visible_before = rig.texts()
    rig.director.actions = [notice_check(rig, occurrences, "weather_leave_early", ("thunderstorm",)),
                            silence, Text("")]
    rig.weather.code = 95
    rig.wait(lambda: rig.director.errors or len(occurrences) == 2 and not rig.director.actions,
             "declined thunderstorm notice handled silently")
    rig.gateway.wait_idle(timeout=30)
    past_reemit(rig)
    assert rig.texts() == visible_before
    assert rig.texts().count(final) == 1
    assert len(set(occurrences)) == 2
    assert set(occurrences) <= fields(rig, "pa:observe-control:" + rig.watch_id)["acks"].keys()
    notices = fields(rig, "pa:observe:" + rig.watch_id)["notices"]
    assert len(notices) == 2 and all(n["emits"] == 1 for n in notices), notices
    assert len(rig.hb2()["occurrences"]) == 2
    assert all(row["errors"] == 0 for row in fields(rig, "pa:observe:" + rig.watch_id)["usage"].values())


def hb2_before(minimum):
    checkout = os.getenv("PA_E2E_HEARTBEAT2")
    if not checkout:
        return False  # The opt-in collection hook handles an unconfigured rig.
    manifest = (Path(checkout) / "plugin.yaml").read_text()
    version = re.search(r'^version:\s*[\"\']?(\d+)\.(\d+)\.(\d+)', manifest, re.MULTILINE)
    assert version, "HB2 plugin.yaml must declare a semantic version"
    return tuple(map(int, version.groups())) < minimum


def hb2_before_held_turns():
    return hb2_before((0, 4, 8))


@pytest.mark.skipif(hb2_before_held_turns(), reason="held watcher turns require HeartBeat 2.0 >= 0.4.8")
@pytest.mark.parametrize("rig", [{"observe_settings": {"weather_provider": "off", "reemit_after_s": 6}}], indirect=True)
def test_never_replies_hold(rig):
    from harness import Director, Text, ToolCall
    from personal_assistant.entry import dispatch
    from personal_assistant.state import Ledger

    arm_watch(rig, request_mute_exemption=False)
    occurrences, final = [], "OFFER-HOLD: your flight has another delay."
    held_notices = []
    summary = "Flight PA301 now departs 150 minutes late. Options ready."

    def check_notice(record, *, reserve):
        notice, = result(record)["notices"]
        assert notice["offer_type"] == "flight_change", notice
        assert notice["id"] == held_notices[-1], notice
        data = dict(action="check", trip_id="T3", offer_type="flight_change", occurrence=notice["id"])
        if not reserve:
            data["reserve"] = False
        return pa("trip_offer", **data)

    def held_check(record):
        return check_notice(record, reserve=False)

    def held_report(record):
        assert result(record)["allowed"] is True, result(record)
        return ToolCall("pulse", {"action": "respond", "outcome": "needs_attention", "notify": True,
                                  "summary": summary})

    def silent_end(record):
        # Every re-emission is a new silent model turn for the same unacked notice.
        rig.director.actions.append(route_turn)
        return Text("")

    def owner_check(record):
        return check_notice(record, reserve=True)

    def owner_offer(record):
        assert result(record)["allowed"] is True, result(record)
        action = pa("trip_offer", action="record", trip_id="T3", offer_type="flight_change",
                    occurrence=held_notices[-1], outcome="offered")
        action.text = final  # Offer in this reply before recording its receipt.
        return action

    def owner_end(record):
        assert result(record)["fields"]["outcome"] == "offered", result(record)
        return Text("")

    def route_turn(record):
        messages = record["body"]["messages"]
        text = Director._text(next(m for m in reversed(messages) if m["role"] == "user"))
        if text.startswith("⟦pulse"):
            assert "Messages are held right now" in text, text
            assert "offer_type=flight_change" in text, text
            held_notices.append(re.search(r"occurrence=(n_[0-9a-f]{8})", text).group(1))
            rig.director.actions.extend([held_check, held_report, silent_end])
        else:
            assert text.startswith("Trip T3: any update?"), text
            # intake.pre_llm_call -> desk.held_report_lines injects this into the
            # owner's request, rather than merely leaving it in tool history.
            context = [Director._text(m) for m in messages
                       if "while the owner's limits held your messages" in Director._text(m)]
            assert any(summary in message for message in context), record["body"]
            (rig.root / "owner-report-request.json").write_text(json.dumps(record["body"], indent=2))
            rig.director.actions.extend([owner_check, owner_offer, owner_end])
        return pa("trip_watch_plan", action="status", trip_id="T3")

    for index, minutes in enumerate((90, 120, 150)):
        if index < 2:
            rig.director.actions = offer_actions(rig, occurrences, "flight_change", final)
        else:
            visible_before = rig.texts()
            rig.director.actions = [route_turn]
        injected = dispatch(rig.gateway.hermes_home, {"operation": "trip_watch_plan", "data": {
            "action": "record_facts", "trip_id": "T3", "source": "simulated", "segments": [{**rig.segment,
            "estimated_departure": (dt.datetime.fromisoformat(rig.segment["scheduled_departure"]) +
                                    dt.timedelta(minutes=minutes)).isoformat()}]}})
        assert injected["changed"] is True
        if index < 2:
            rig.wait(lambda: rig.director.errors or rig.texts().count(final) == index + 1, "unanswered delay offer")
            rig.gateway.wait_idle(timeout=30)
            assert_no_errors(rig)
            assert not rig.director.actions
    def held_reports():
        # HB2 pulse.db occurrences is the held-report store (store.held_reports).
        return [row for row in rig.hb2()["occurrences"] if row["wake_id"] == rig.wake_id
                and row["state"] == "done" and row["held_reason"] == "message_held:unanswered"]

    rig.wait(lambda: rig.director.errors or len(held_reports()) >= 2,
             "third notice and its re-emission complete as silent held turns")
    rig.gateway.wait_idle(timeout=30)
    assert_no_errors(rig)
    held_rows = rig.hb2()
    (rig.root / "held-before-reply.json").write_text(json.dumps(held_rows, indent=2))
    assert rig.texts() == visible_before
    assert held_rows["sessions"][0]["unanswered_count"] == 2
    assert len(set(held_notices)) == 1
    notice, = set(held_notices)
    assert notice not in occurrences
    for held in held_reports():
        assert held["force_silent"] == 1 and held["delivered"] == 0, held
        assert held["outcome"] == "needs_attention" and held["notify"] == 1, held
        assert held["summary"] == summary and len(held["summary"]) < 160, held
    assert notice not in fields(rig, "pa:observe-control:" + rig.watch_id)["acks"]
    assert Ledger(rig.gateway.hermes_home, read_only=True).get("action", "pa:offer:T3:flight_change:" + notice) is None
    assert [n["id"] for n in dispatch(rig.gateway.hermes_home, {"operation": "trip_watch_plan", "data": {
        "action": "status", "trip_id": "T3"}})["notices"]] == [notice]

    rig.owner("Trip T3: any update?", final)
    rig.gateway.wait_idle(timeout=30)
    past_reemit(rig)
    assert rig.texts().count(final) == 3
    assert not rig.director.actions
    assert len(set(occurrences + [notice])) == 3
    assert set(occurrences + [notice]) <= fields(rig, "pa:observe-control:" + rig.watch_id)["acks"].keys()
    assert fields(rig, "pa:offer:T3:flight_change:" + notice)["outcome"] == "offered"
    # heartbeat2.model.TERMINAL_OCCURRENCE_STATES on the pinned HB2 checkout.
    terminal = {"done", "skipped", "missed", "dead", "interrupted", "orphaned", "superseded"}
    rig.wait(lambda: all(row["state"] in terminal for row in rig.hb2()["occurrences"]),
             "all watcher and report-back occurrences terminal")
    reported = [row for row in rig.hb2()["occurrences"] if row["wake_id"] == rig.wake_id
                and row["held_reason"] == "reported:unanswered"]
    assert len(reported) >= 2 and all(row["delivered"] == 0 for row in reported), rig.hb2()
    assert_no_errors(rig)


@pytest.mark.skipif(hb2_before((0, 4, 25)), reason="owner-asked watchers require HeartBeat 2.0 >= 0.4.25")
@pytest.mark.parametrize("rig", [{"observe_settings": {"weather_provider": "off", "reemit_after_s": 6}}], indirect=True)
def test_owner_asked_watch_not_muted(rig):
    """A watch armed in the owner's turn keeps alerting after two unanswered messages (#327)."""
    from personal_assistant.entry import dispatch

    arm_watch(rig)
    assert watcher(rig)["owner_requested"] == 1, watcher(rig)
    state = dispatch(rig.gateway.hermes_home, {"operation": "trip_watch_plan", "data": {"action": "status", "trip_id": "T3"}})
    assert state["arms"]["watch"]["owner_asked"] is True, state
    assert state["arms"]["watch"]["unanswered_mute"] == "exempt", state
    occurrences, final = [], "OFFER-OWNER-ASKED: your flight has another delay."
    for index, minutes in enumerate((90, 120, 150)):
        if index == 2:
            # Default max_unanswered is 2: a watch without owner_asked would now be held.
            assert rig.hb2()["sessions"][0]["unanswered_count"] == 2, rig.hb2()
        rig.director.actions = offer_actions(rig, occurrences, "flight_change", final)
        injected = dispatch(rig.gateway.hermes_home, {"operation": "trip_watch_plan", "data": {
            "action": "record_facts", "trip_id": "T3", "source": "simulated", "segments": [{**rig.segment,
            "estimated_departure": (dt.datetime.fromisoformat(rig.segment["scheduled_departure"]) +
                                    dt.timedelta(minutes=minutes)).isoformat()}]}})
        assert injected["changed"] is True
        rig.wait(lambda: rig.director.errors or rig.texts().count(final) == index + 1, "owner-asked delay offer")
        rig.gateway.wait_idle(timeout=30)
        assert_no_errors(rig)
        assert not rig.director.actions
    rows = rig.hb2()
    (rig.root / "owner-asked-after-third.json").write_text(json.dumps(rows, indent=2))
    held = [row for row in rows["occurrences"] if row["wake_id"] == rig.wake_id and row["held_reason"]]
    assert not held, held
    assert len(set(occurrences)) == 3
    assert set(occurrences) <= fields(rig, "pa:observe-control:" + rig.watch_id)["acks"].keys()
