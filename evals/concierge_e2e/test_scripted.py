"""P1: real gateway, synthetic owner and scripted model; imports stay opt-in."""
import datetime as dt
import json


def test_setup_to_offer(rig):
    from harness import Director, Text, ToolCall
    from personal_assistant.state import Ledger
    from personal_assistant.entry import dispatch

    def pa(op, **data):
        return ToolCall("pa", {"operation": op, "data": data})

    def result(record):
        return json.loads(record["body"]["messages"][-1]["content"])

    def setup(record):
        user = next(m for m in reversed(record["body"]["messages"]) if m["role"] == "user")
        assert all(s in Director._text(user) for s in ("Guided setup is active", "personal-assistant:pa-setup"))
        return pa("setup", action="record", answers={"call_and_quiet": {"text": "Call me Alex; UTC.", "source": "user"}})

    def arm(record):
        plan = result(record)
        rig.plan = plan
        return ToolCall("pulse", plan["pulse_create"])

    def receipt(record):
        created = result(record)
        assert created["armed"] is True, created
        rig.wake_id = created["wake"]["id"]
        return pa("trip_watch_plan", action="record_wake", trip_id="T1",
                  moment="arrival_logistics", wake_id=rig.wake_id)

    def wake(record):
        user = next(m for m in reversed(record["body"]["messages"]) if m["role"] == "user")
        assert "⟦pulse" in Director._text(user)
        assert "Guided setup is active" not in Director._text(user)
        return pa("trip_offer", action="check", trip_id="T1", offer_type="arrival_logistics")

    def offer(record):
        assert result(record)["allowed"] is True
        return pa("trip_offer", action="record", trip_id="T1", offer_type="arrival_logistics", outcome="offered")

    rig.owner("/pa setup", "Setup is ready")
    assert not rig.llm.main_requests()
    rig.director.actions = [setup, Text("What is worth a message?")]
    rig.owner("hi", "What is worth a message?")
    now = dt.datetime.now(dt.timezone.utc)
    quiet = {k: (now + dt.timedelta(hours=h)).strftime("%H:%M") for k, h in (("start", 6), ("end", 7))}
    # Planning floors departure to five minutes. Keep the real wake 60-120s
    # ahead using minute-valued leads, independent of the current clock phase.
    departure = now + dt.timedelta(hours=3, minutes=5)
    departure = departure.replace(minute=departure.minute // 5 * 5, second=0, microsecond=0)
    lead = int((departure - now).total_seconds() // 60) - 1
    final = "OFFER-DELIVERED: food to the hotel, a late check-in note, or a pickup?"
    rig.director.actions = [pa("automations", action="preferences", changes={"timezone": "UTC", "quiet_hours": quiet}),
        pa("trip_watch_plan", trip_id="T1", departure_at=departure.isoformat(),
           arrival_at=(departure + dt.timedelta(hours=11)).isoformat(), hb2_quiet_hours="",
           airport_lead_minutes=lead, check_in_lead_minutes=lead),
        arm, receipt, Text("Trip watch armed."), wake, offer,
        ToolCall("pulse", {"action": "respond", "outcome": "done", "notify": True, "summary": "Sent one arrival offer."}), Text(final)]
    rig.owner("Trip T1: please watch it", "Trip watch armed.")
    rig.wait(lambda: final in rig.texts(), "same-DM offer", 150)
    rig.gateway.wait_idle(timeout=30)
    assert not rig.director.errors, rig.director.errors
    assert not rig.director.actions
    assert rig.texts().count(final) == 1
    home = rig.gateway.hermes_home
    ledger = Ledger(home, read_only=True)
    assert ledger.get("action", "pa:setup")["status"] == "in_progress"
    assert ledger.get("action", "pa:setup")["fields"]["answers"]["call_and_quiet"]["source"] == "user"
    with ledger.connect() as conn:
        projection = conn.execute("SELECT status,result_json FROM pa_projections WHERE event_id=? AND projection_key='arm:arrival_logistics'", (rig.plan["event_id"],)).fetchone()
    assert projection["status"] == "confirmed"
    assert json.loads(projection["result_json"])["proof"]["wake_id"] == rig.wake_id
    assert ledger.get("action", "pa:offer:T1:arrival_logistics")["fields"]["outcome"] == "offered"
    assert dispatch(home, {"operation": "trip_offer", "data": {
        "action": "check", "trip_id": "T1", "offer_type": "arrival_logistics", "reserve": False}})["allowed"] is False
