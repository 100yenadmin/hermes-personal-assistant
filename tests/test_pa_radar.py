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
