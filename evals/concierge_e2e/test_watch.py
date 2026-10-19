"""P3: real HB2 scheduled command probes; all inputs and delivery are loopback."""
import datetime as dt
import json
import re

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


def arm_watch(rig, weather=False):
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
        # Exercise the real command and poller, shortening only the test cadence.
        return ToolCall("pulse", {**pulse, "trigger": {**pulse["trigger"], "check_every": "2s"}})

    def receipt(record):
        created = result(record)
        assert created["armed"] is True, created
        rig.wake_id = created["wake"]["id"]
        rig.watch_id = rig.plan["inputs"]["watch_argv"][-1]
        return pa("trip_watch_plan", action="record_wake", trip_id="T3", moment="watch", wake_id=rig.wake_id)

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
                                         ("Leave by", "+45 min for snow"))
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


@pytest.mark.parametrize("rig", [{"observe_settings": {"weather_provider": "off", "reemit_after_s": 6}}], indirect=True)
def test_never_replies_hold(rig):
    from harness import Text
    from personal_assistant.entry import dispatch
    arm_watch(rig)
    occurrences, final = [], "OFFER-HOLD: your flight has another delay."
    for index, minutes in enumerate((90, 120, 150)):
        if index < 2:
            rig.director.actions = offer_actions(rig, occurrences, "flight_change", final)
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
    rig.wait(lambda: any(row["state"] == "pending" and row["held_reason"] == "held_unanswered"
                        for row in rig.hb2()["occurrences"]), "third fire held by unanswered gate")
    held_rows = rig.hb2()
    (rig.root / "held-before-reply.json").write_text(json.dumps(held_rows, indent=2))
    assert rig.texts().count(final) == 2
    assert held_rows["sessions"][0]["unanswered_count"] == 2
    held, = [row for row in held_rows["occurrences"] if row["state"] == "pending"]
    assert held["held_reason"] == "held_unanswered" and held["held_since"] is not None
    assert held["delivered"] == 0
    rig.director.actions = [Text("Reply received.")] + offer_actions(rig, occurrences, "flight_change", final)
    rig.owner("Trip T3: any update?", "Reply received.")
    rig.wait(lambda: rig.director.errors or rig.texts().count(final) == 3, "held offer released after owner reply")
    rig.gateway.wait_idle(timeout=30)
    past_reemit(rig)
    assert rig.texts().count(final) == 3
    assert not rig.director.actions
    assert len(set(occurrences)) == 3
    assert set(occurrences) <= fields(rig, "pa:observe-control:" + rig.watch_id)["acks"].keys()
    released = next(row for row in rig.hb2()["occurrences"] if row["dedupe_key"] == held["dedupe_key"])
    assert released["state"] == "done" and released["delivered"] == 1
    assert all(row["state"] == "done" for row in rig.hb2()["occurrences"]), rig.hb2()
