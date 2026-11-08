import datetime as dt
import hashlib
from pathlib import Path

import pytest

from personal_assistant.context import next_actions
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger

AT = "2026-11-08T10:00:00+09:00"
UNKNOWN = {"status": "unknown", "evidence": "fixture adapter unavailable"}


def _read(ledger, at=AT, **data):
    return next_actions(ledger, {"radar": True, "at": at, "limit": 20, **data},
                        kanban_reader=lambda task_id, board: UNKNOWN)


def _radar(ledger, action_id, **fields):
    ledger.put("action", action_id, {"title": action_id, **fields}, action_type="commitment")


@pytest.fixture
def ledger(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.put("action", "pa:preferences", {"timezone": "Asia/Tokyo"}, action_type="preferences")
    return ledger


def test_va_bar_profile_passport_birthday_and_car_service(ledger):
    _radar(ledger, "passport", radar_kind="renewal", document="Passport", expires_on="2027-06-08",
           lead_days=183, recurs="none", source_ref="owner chat")
    _radar(ledger, "spouse-birthday", radar_kind="important_date", document="Spouse's birthday",
           event_date="1990-11-29", lead_days=28, recurs="yearly", source_ref="owner chat")
    _radar(ledger, "car-service", radar_kind="deadline", document="Car service", event_date="2026-11-12",
           source_ref="dealer email")
    now = {item["action_id"]: item for item in _read(ledger)["candidates"]}
    assert set(now) == {"spouse-birthday", "car-service"}
    assert now["spouse-birthday"]["date"] == "2026-11-29" and now["spouse-birthday"]["days_until"] == 21
    assert now["spouse-birthday"]["surface_at"] == "2026-11-01"
    assert (now["car-service"]["lead_days"], now["car-service"]["surface_at"]) == (7, "2026-11-05")
    # surface_at = expires_on - lead_days: seven months out with a 183-day lead surfaces on 7 Dec.
    result = _read(ledger, include_upcoming=True)
    passport = next(item for item in result["candidates"] if item["action_id"] == "passport")
    assert (passport["surfaced"], passport["surface_at"], passport["document"]) == (False, "2026-12-07", "Passport")
    assert (result["not_yet_surfaced"], result["next_surface_at"]) == (1, "2026-12-07")
    assert [item["action_id"] for item in _read(ledger, at="2026-12-07T09:00:00+09:00")["candidates"]
            if item["radar_kind"] == "renewal"] == ["passport"]


def test_passport_within_its_lead_surfaces_now(ledger):
    _radar(ledger, "passport", radar_kind="renewal", document="Passport", expires_on="2027-05-01", lead_days=183)
    item = _read(ledger)["candidates"][0]
    assert (item["action_id"], item["surfaced"], item["surface_at"]) == ("passport", True, "2026-10-30")


def test_month_only_date_reads_as_first_of_month(ledger):
    _radar(ledger, "passport", radar_kind="renewal", document="Passport", expires_on="2027-03", lead_days=183)
    item = _read(ledger, include_upcoming=True)["candidates"][0]
    assert (item["date"], item["surface_at"], item["surfaced"]) == ("2027-03-01", "2026-08-30", True)
    assert item["date_precision"].startswith("month")
    _radar(ledger, "full", radar_kind="deadline", event_date="2026-11-12")
    full = next(i for i in _read(ledger)["candidates"] if i["action_id"] == "full")
    assert "date_precision" not in full


def test_yearly_birthday_rolls_to_next_year_after_the_date(ledger):
    _radar(ledger, "spouse-birthday", radar_kind="important_date", event_date="1990-11-29",
           lead_days=28, recurs="yearly")
    on_day = _read(ledger, at="2026-11-29T20:00:00+09:00")["candidates"][0]
    assert (on_day["date"], on_day["days_until"]) == ("2026-11-29", 0)
    after = _read(ledger, at="2026-11-30T09:00:00+09:00", include_upcoming=True)["candidates"][0]
    assert (after["date"], after["surface_at"], after["surfaced"]) == ("2027-11-29", "2027-11-01", False)
    # Owner-local dates: 29 Nov 23:30 UTC is already 30 Nov in Tokyo.
    assert _read(ledger, at="2026-11-29T23:30:00+00:00")["candidates"] == []


def test_unanswered_offers_and_recommendations(ledger):
    dispatch(ledger.root, {"operation": "trip_offer", "data": {
        "action": "record", "trip_id": "seoul", "offer_type": "airport_transfer", "outcome": "offered"}})
    dispatch(ledger.root, {"operation": "trip_offer", "data": {
        "action": "record", "trip_id": "seoul", "offer_type": "dinner", "outcome": "accepted"}})
    stamp = dt.datetime.now(dt.timezone.utc)  # After the offer, so four days later is at least four days.
    ledger.put("action", "cos:daily:2026-11-01", {"title": "CoS: prep the board pack", "cos_skill": "cos-daily",
               "review_at": (stamp + dt.timedelta(days=3)).isoformat(), "outcome": "unknown"},
               action_type="note", status="completed")
    ledger.put("action", "cos:daily:2026-11-02", {"title": "CoS: answered", "review_at": stamp.isoformat(),
               "outcome": "used"}, action_type="note", status="completed")
    later = (stamp + dt.timedelta(days=4)).isoformat()
    by_kind = {item["radar_kind"]: item for item in _read(ledger, at=later)["candidates"]}
    assert set(by_kind) == {"unanswered_offer", "unanswered_recommendation"}
    assert by_kind["unanswered_offer"]["offer_type"] == "airport_transfer"
    assert by_kind["unanswered_offer"]["age_days"] == 4
    assert by_kind["unanswered_recommendation"]["action_id"] == "cos:daily:2026-11-01"
    soon = (stamp + dt.timedelta(days=2)).isoformat()
    assert [item["radar_kind"] for item in _read(ledger, at=soon)["candidates"]] == []
    assert _read(ledger, at=soon, offer_days=1)["candidates"][0]["radar_kind"] == "unanswered_offer"
    with pytest.raises(ValueError):
        _read(ledger, offer_days=0)


def _fingerprint(root):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(root).rglob("*")) if path.is_file()}


def test_radar_read_writes_nothing(ledger):
    _radar(ledger, "car-service", radar_kind="deadline", document="Car service", event_date="2026-11-12")
    dispatch(ledger.root, {"operation": "trip_offer", "data": {
        "action": "record", "trip_id": "seoul", "offer_type": "airport_transfer", "outcome": "offered"}})
    rows, files = ledger.list("action"), _fingerprint(ledger.root)
    result = dispatch(ledger.root, {"operation": "next_action", "data": {"radar": True, "at": AT}})
    assert result["read_only"] is True and result["candidates"]
    assert ledger.list("action") == rows and _fingerprint(ledger.root) == files


def test_passport_renewal_survives_privacy_cleaner(ledger):
    fields = {"title": "Renew passport", "radar_kind": "renewal", "document": "Passport",
              "expires_on": "2027-06-08", "lead_days": 183, "recurs": "none", "source_ref": "owner chat 2026-11-08"}
    saved = dispatch(ledger.root, {"operation": "action_upsert", "data": {
        "action_id": "radar-passport", "action_type": "commitment",
        "fields": {**fields, "passport_expiry": "2027-06-08"}}})
    assert saved["fields"] == fields  # The neutral keys survive; a passport-named key is dropped.
    read = dispatch(ledger.root, {"operation": "context", "data": {"kind": "action", "action_id": "radar-passport"}})
    assert read["action"]["fields"] == fields
    listed = dispatch(ledger.root, {"operation": "next_action", "data": {
        "radar": True, "include_upcoming": True, "at": AT}})["candidates"][0]
    assert (listed["document"], listed["date"], listed["source_ref"]) == ("Passport", "2027-06-08", "owner chat 2026-11-08")


def test_ordinary_next_action_waits_for_radar_lead(ledger):
    _radar(ledger, "passport", radar_kind="renewal", document="Passport", expires_on="2027-06-08", lead_days=183)
    _radar(ledger, "car-service", radar_kind="deadline", document="Car service", event_date="2026-11-12")
    _radar(ledger, "done-renewal", radar_kind="renewal", expires_on="2026-11-20")
    ledger.put("action", "done-renewal", {}, status="completed")
    ledger.put("action", "plain", {"next_action": "call the bank"}, action_type="commitment")
    result = next_actions(ledger, {"at": AT}, kanban_reader=lambda task_id, board: UNKNOWN)
    by_id = {item["action_id"]: item for item in result["candidates"]}
    assert set(by_id) == {"car-service", "plain"}
    assert by_id["car-service"]["radar"] == {"radar_kind": "deadline", "date": "2026-11-12",
                                             "surface_at": "2026-11-05", "days_until": 4}
    assert "radar" not in by_id["plain"]
    assert result["excluded_radar_upcoming"] == 1
    assert [item["action_id"] for item in _read(ledger)["candidates"]] == ["car-service"]


def test_radar_text_contract():
    root = Path(__file__).resolve().parents[1]
    reference = (root / "skills/personal-assistant/references/radar.md").read_text()
    for name in ("radar_kind", "document", "expires_on", "event_date", "lead_days", "recurs", "source_ref"):
        assert f"`{name}`" in reference, name
    assert "never write `passport_expiry`" in reference
    assert "`references/radar.md`" in (root / "skills/personal-assistant/SKILL.md").read_text()


@pytest.mark.parametrize("field,value", [
    ("opened_at", "tomorrow"), ("last_chased_at", "tomorrow"), ("snoozed_until", "tomorrow"),
    ("loop_kind", []), ("next_actor", []), ("chase_log", "not a list"),
    ("chase_log", [{"step": "escalate"}]), ("chase_log", ["day2"]),
    ("chase_log", [{"step": "invalid", "at": AT}]),
    ("chase_log", [{"step": "day2", "at": "2026-11-08"}]),
    ("confirmation", {"by": ["Sam"], "evidence": {"ok": True}}),
    ("confirmation", {"by": "Sam", "at": "tomorrow", "evidence": "reply"}),
    ("confirmation", {"by": "Sam", "at": "2026-11-08", "evidence": "reply"}),
    ("confirmation", {"by": " ", "at": AT, "evidence": "reply"}),
    ("confirmation", {"by": "Sam", "at": AT, "evidence": {"ok": True}}),
])
def test_upsert_rejects_malformed_loop_fields(ledger, field, value):
    with pytest.raises(ValueError, match=field):
        dispatch(ledger.root, {"operation": "action_upsert", "data": {
            "action_id": "bad-loop", "action_type": "commitment", "fields": {field: value}}})
    assert ledger.get("action", "bad-loop") is None


def test_upsert_accepts_documented_loop_fields_and_dates(ledger):
    fields = {"loop_kind": "waiting_on_them", "next_actor": "them", "opened_at": "2026-11-01",
              "last_chased_at": AT, "snoozed_until": "2026-11-09",
              "chase_log": [{"step": step, "at": AT, "how": "fixture"}
                            for step in ("day2", "day5", "day10", "escalate")],
              "confirmation": {"by": "Sam", "at": AT, "evidence": "reply"}}
    saved = dispatch(ledger.root, {"operation": "action_upsert", "data": {
        "action_id": "valid-loop", "action_type": "commitment", "fields": fields}})
    assert saved["fields"] == fields


@pytest.mark.parametrize("confirmation", [
    {"by": ["Sam"], "evidence": {"ok": True}}, {"by": "Sam", "evidence": "reply"},
    {"by": "Sam", "at": "tomorrow", "evidence": "reply"},
])
def test_old_malformed_loop_fields_remain_readable_and_unconfirmed(ledger, confirmation):
    _radar(ledger, "old-loop", loop_kind="waiting_on_them", next_actor=[], opened_at="tomorrow",
           chase_log="not a list", confirmation=confirmation, radar_kind="deadline", event_date="2026-11-09")
    for radar in (False, True):
        result = next_actions(ledger, {"radar": radar, "at": AT}, kanban_reader=lambda *_: UNKNOWN)
        assert result["candidates"][0]["loop_state"] == "open"


def test_due_loop_is_not_hidden_by_upcoming_radar(ledger):
    _radar(ledger, "due-loop", loop_kind="waiting_on_them", opened_at="2026-11-01T23:30:00Z",
           radar_kind="renewal", expires_on="2027-06-01")
    result = next_actions(ledger, {"loops_only": True, "at": "2026-11-08T12:00:00Z"},
                          kanban_reader=lambda *_: UNKNOWN)
    assert result["candidates"][0]["chase"]["step"] == "day5"
    assert result["candidates"][0]["radar"]["date"] == "2027-06-01"
    assert result["excluded_radar_upcoming"] == 0


def test_radar_honours_trip_and_loops_only_filters(ledger):
    for identity, trip, kind in (("plain", "other-trip", None), ("other-loop", "other-trip", "ask_owner"),
                                 ("requested", "requested-trip", "ask_owner"), ("bad", "requested-trip", [])):
        fields = {"radar_kind": "deadline", "event_date": "2026-11-09", "loop_kind": kind}
        ledger.put("action", identity, fields, action_type="commitment", trip_id=trip)
    ledger.put("action", "offer", {"outcome": "offered", "history": [{"outcome": "offered", "at": "2026-11-01T00:00:00Z"}]},
               action_type="offer", trip_id="requested-trip")
    data = {"trip_id": "requested-trip", "at": "2026-11-08T12:00:00Z"}
    assert {i["action_id"] for i in _read(ledger, **data)["candidates"]} == {"requested", "bad", "offer"}
    assert [i["action_id"] for i in _read(ledger, loops_only=True, **data)["candidates"]] == ["requested"]


@pytest.mark.parametrize("status,task,confirmed,expected", [
    ("completed", None, False, "done_unconfirmed"), ("pending", "done-task", False, "done_unconfirmed"),
    ("pending", None, True, None), ("cancelled", None, False, None),
])
def test_radar_and_next_actions_share_loop_closure(ledger, status, task, confirmed, expected):
    fields = {"loop_kind": "waiting_on_them", "opened_at": "2026-11-01T23:30:00Z",
              "radar_kind": "deadline", "event_date": "2026-11-09", "kanban_task_id": task}
    if confirmed:
        fields["confirmation"] = {"by": "Sam", "at": AT, "evidence": "reply"}
    ledger.put("action", "loop", fields, action_type="commitment", status=status)
    for radar in (False, True):
        result = next_actions(ledger, {"radar": radar, "at": "2026-11-08T12:00:00Z"},
                              kanban_reader=lambda *_: {"status": "done" if task else "unknown"})
        assert [i["loop_state"] for i in result["candidates"]] == ([expected] if expected else [])


@pytest.mark.parametrize("status,extra,instruction", [
    ("unknown", {}, "Read provider state for the claimed attempt; do not submit again."),
    ("submitting", {}, "Read provider state for the claimed attempt; do not submit again."),
    ("pending", {"waiting_for": "owner reply"}, "Wait for owner reply;"),
    ("paused", {}, "Keep paused for"),
    ("pending", {"stale": True}, "Refresh stale or unknown source evidence"),
    ("pending", {"freshness": "unknown"}, "Refresh stale or unknown source evidence"),
    ("pending", {"snoozed_until": "2026-11-10T10:00:00+09:00"}, "Wait until 2026-11-10"),
    ("claimed_once", {}, "Read provider state for the claimed attempt; do not submit again."),
    ("provider_result", {}, "Read provider state for the claimed attempt; do not submit again."),
    ("prepared", {}, "Present the current material details for explicit confirmation."),
    ("approval_required", {}, "Present the current material details for explicit confirmation."),
    ("authorized", {}, "Recheck details, then claim immediately"),
    ("approved_revision", {}, "Recheck details, then claim immediately"),
    ("failed", {}, "Reconcile the provider result"),
])
def test_loop_chase_preserves_safety_and_wait_instructions(ledger, status, extra, instruction):
    opened = (dt.datetime.fromisoformat(AT) - dt.timedelta(days=6)).isoformat()
    ledger.put("action", "our-promise", {"loop_kind": "our_promise", "next_actor": "us",
               "opened_at": opened, **extra}, action_type="commitment", status=status)
    item = next_actions(ledger, {"at": AT}, kanban_reader=lambda *_: UNKNOWN)["candidates"][0]
    assert item["loop_state"] == "open"
    assert item["next_step"].startswith(instruction)
    assert "do our next step now" not in item["next_step"]


@pytest.mark.parametrize("status,kanban_status", [("completed", "unknown"), ("pending", "done")])
def test_done_unconfirmed_loop_waits_for_snooze_then_asks(ledger, status, kanban_status):
    snooze = (dt.datetime.fromisoformat(AT) + dt.timedelta(days=2)).isoformat()
    ledger.put("action", "done-loop", {"loop_kind": "our_promise", "next_actor": "us",
               "opened_at": "2026-11-02", "snoozed_until": snooze, "kanban_task_id": "task"},
               action_type="commitment", status=status)
    for at, instruction in ((AT, f"Wait until {snooze}"),
                            ("2026-11-11T10:00:00+09:00", "Kanban or status shows done")):
        item = next_actions(ledger, {"at": at}, kanban_reader=lambda *_: {
            "status": kanban_status})["candidates"][0]
        assert item["loop_state"] == "done_unconfirmed"
        assert item["next_step"].startswith(instruction)


@pytest.mark.parametrize("opt_out", [False, True])
@pytest.mark.parametrize("trip_id", [None, "seoul"])
def test_unanswered_offer_respects_lasting_type_opt_out(ledger, opt_out, trip_id):
    offered = (dt.datetime.fromisoformat(AT) - dt.timedelta(days=5)).isoformat()
    for offer_type in ("airport_transfer", "dinner"):
        ledger.put("action", f"pa:offer:seoul:{offer_type}:n_1234abcd", {
            "outcome": "offered", "history": [{"outcome": "offered", "at": offered}]},
            action_type="offer", trip_id="seoul")
    if opt_out:
        ledger.put("action", "pa:offer:*:airport_transfer", {"outcome": "opted_out"},
                   action_type="offer", trip_id="*")
    rows, files = ledger.list("action"), _fingerprint(ledger.root)
    items = _read(ledger, trip_id=trip_id)["candidates"]
    assert {item["offer_type"] for item in items} == ({"dinner"} if opt_out else {"airport_transfer", "dinner"})
    assert all(item["radar_kind"] == "unanswered_offer" and item["age_days"] == 5 for item in items)
    assert ledger.list("action") == rows and _fingerprint(ledger.root) == files


@pytest.mark.parametrize("trip_id", ["trip:seoul", "seoul"])
def test_offer_type_is_read_after_a_trip_id_with_colons(ledger, trip_id):
    offered = (dt.datetime.fromisoformat(AT) - dt.timedelta(days=5)).isoformat()
    for suffix in ("", ":n_1234abcd"):
        ledger.put("action", f"pa:offer:{trip_id}:airport_transfer{suffix}", {
            "outcome": "offered", "history": [{"outcome": "offered", "at": offered}]},
            action_type="offer", trip_id=trip_id)
    assert {item["offer_type"] for item in _read(ledger)["candidates"]} == {"airport_transfer"}
    ledger.put("action", "pa:offer:*:airport_transfer", {"outcome": "opted_out"}, action_type="offer", trip_id="*")
    assert _read(ledger)["candidates"] == []


@pytest.mark.parametrize("value", [None, ""])
def test_a_loop_snooze_can_be_cleared(value):
    from personal_assistant.context import loop_fields
    assert loop_fields({"loop_kind": "ask_owner", "snoozed_until": value})["snoozed_until"] == value
