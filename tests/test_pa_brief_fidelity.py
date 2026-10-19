"""Focused packet-fidelity evidence for daily calendar consumers."""
from __future__ import annotations

import datetime as dt

from personal_assistant.daily_ops import config, doctor, evening_register, morning_brief, trip_context
from personal_assistant.daily_ops.common import Collected, envelope
from personal_assistant.daily_ops.gog_collector import DailyOpsError


MOMENT = dt.datetime(2026, 9, 8, 3, 0, tzinfo=dt.timezone.utc)


def cfg():
    return {
        "tenant": {"profile_id": "example-profile", "owner_email": "owner@example.com"},
        "delivery": {"target": "example-topic", "verified": True},
        "timezone": "Asia/Bangkok",
        "accounts": {"work": "owner@example.com", "personal": None},
        "calendar": {
            "provider": "profile_google",
            "read_scope": {"accepted": True, "calendar_ids": ["primary"], "include_pa_binding": False},
        },
        "travel": {"leave_by": False},
    }


def timed_event(**updates):
    event = {
        "id": "event-1",
        "summary": "Planning",
        "start": {"dateTime": "2026-09-09T13:00:00+07:00", "timeZone": "Asia/Bangkok"},
        "end": {"dateTime": "2026-09-09T14:00:00+07:00", "timeZone": "Asia/Bangkok"},
        "timezone": "Asia/Bangkok",
        "url": "https://calendar.example.invalid/event-1",
        "location": "Example office",
    }
    event.update(updates)
    return event


def calendar_result(items=None, *, complete=True, truncated=False):
    return Collected(
        list(items or [timed_event()]),
        complete,
        truncated,
        None,
        [{"source": "calendar-1", "provider": "profile_google", "status": "complete", "complete": complete, "truncated": truncated}],
    )


def test_morning_packet_preserves_nested_time_timezone_and_url(monkeypatch):
    seen = []

    def read_calendar(config, days, *, profile=None, service=None):
        del service
        seen.append((config, days, profile))
        return calendar_result()

    monkeypatch.setattr(morning_brief, "run_calendar", read_calendar)
    monkeypatch.setattr(morning_brief, "run_mail", lambda *args, **kwargs: Collected([], True, False, 0))
    monkeypatch.setattr(morning_brief.trip_context, "trip_context", lambda *args: {"status": "unknown"})
    packet = morning_brief.collect(cfg(), profile="/synthetic/profile", moment=MOMENT)

    event = packet["sections"]["calendar_next_36h"]["items"][0]
    assert seen == [(cfg(), 2, "/synthetic/profile")]
    assert event["start"] == {"dateTime": "2026-09-09T13:00:00+07:00", "timeZone": "Asia/Bangkok"}
    assert event["end"]["dateTime"] == "2026-09-09T14:00:00+07:00"
    assert event["timezone"] == "Asia/Bangkok"
    assert event["url"].endswith("/event-1")
    assert packet["complete"] is True and packet["truncated"] is False


def test_actual_packet_bounding_sets_both_fidelity_flags():
    packet = envelope(
        "morning_brief",
        cfg(),
        MOMENT,
        MOMENT + dt.timedelta(hours=36),
        {"calendar_next_36h": {"items": [timed_event(description="x" * 801)]}},
        complete=True,
        truncated=False,
    )
    event = packet["sections"]["calendar_next_36h"]["items"][0]
    assert event["start"]["dateTime"] == "2026-09-09T13:00:00+07:00"
    assert len(event["description"]) == 800
    assert packet["complete"] is False and packet["truncated"] is True


def test_profile_google_brief_degrades_to_calendar_only_without_gog(monkeypatch):
    monkeypatch.setattr(morning_brief, "run_calendar", lambda *args, **kwargs: calendar_result())
    monkeypatch.setattr(morning_brief, "run_mail", lambda *args, **kwargs: (_ for _ in ()).throw(DailyOpsError("synthetic missing gog")))
    monkeypatch.setattr(morning_brief.trip_context, "trip_context", lambda *args: {"status": "unknown"})
    packet = morning_brief.collect(cfg(), profile="/synthetic/profile", moment=MOMENT)
    assert packet["sections"]["calendar_next_36h"]["count"] == 1
    assert packet["sections"]["humans_1"]["status"] == "mail provider unavailable"
    assert packet["sections"]["humans_1"]["complete"] is False
    assert packet["complete"] is False and packet["truncated"] is False


def test_profile_google_config_requires_explicit_scope_but_not_gog_login(monkeypatch):
    invalid = cfg()
    invalid["calendar"]["read_scope"]["accepted"] = False
    assert any("calendar.read_scope.accepted" in error for error in config.validate_config(invalid))

    def missing_gog():
        raise DailyOpsError("synthetic missing gog")

    monkeypatch.setattr(doctor, "gog_binary", missing_gog)
    assert doctor.check_gog(cfg()) == (
        True,
        "gog mail collector unavailable; calendar-only packets will report incomplete mail coverage",
    )
    assert doctor.check_scopes(cfg())[0] is True


def test_evening_and_watchdog_travel_share_the_same_calendar_scope(monkeypatch):
    calls = []

    def read_calendar(config, days, profile=None, **kwargs):
        calls.append((config, days, profile))
        return calendar_result([timed_event()])

    monkeypatch.setattr(evening_register, "run_calendar", read_calendar)
    monkeypatch.setattr(evening_register.trip_context, "trip_context", lambda *args: {"status": "unknown"})
    evening = evening_register.collect(cfg(), profile="/synthetic/profile", moment=MOMENT)
    assert evening["sections"]["tomorrow_timeline"]["coverage"][0]["source"] == "calendar-1"

    travel_cfg = cfg()
    travel_cfg["travel"] = {"leave_by": True, "geocoder": {"consent": False}}
    monkeypatch.setattr(trip_context, "trip_context", lambda *args: {"status": "unknown"})
    monkeypatch.setattr(trip_context, "run_calendar", read_calendar)
    context, alerts, complete, truncated = trip_context.collect_trip(
        travel_cfg, MOMENT, lambda *_: None, "/synthetic/profile"
    )
    assert alerts == [] and complete is True and truncated is False
    assert context["calendar_coverage"][0]["source"] == "calendar-1"
    assert calls == [
        (cfg(), 2, "/synthetic/profile"),
        (travel_cfg, 1, "/synthetic/profile"),
    ]
