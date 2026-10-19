import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.automation_workflow import preferences
from personal_assistant.state import Ledger


def watch(root, **data):
    return dispatch(root, {"operation": "trip_watch_plan", "data": {
        "trip_id": "synthetic", "departure_at": "2026-11-10T12:00:00+09:00",
        "arrival_at": "2026-11-10T22:30:00+01:00", "arrival_timezone": "Europe/Paris",
        "at": "2026-10-20T00:00:00+00:00", **data}})


def test_explicit_hb2_timezone_overrides_hermes(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_time", SimpleNamespace(get_timezone=lambda: ZoneInfo("UTC")))
    result = watch(tmp_path, departure_at="2026-11-10T18:00:00+09:00",
                   hb2_timezone="America/Los_Angeles")
    assert result["pulse_create"]["trigger"]["at"] == "2026-11-10T14:30:00+09:00"
    assert watch(tmp_path, action="status")["inputs"]["hb2_timezone"] == "America/Los_Angeles"
    assert SCHEMA["parameters"]["properties"]["data"]["properties"]["hb2_timezone"]["type"] == "string"


@pytest.mark.parametrize("profile_zone,departure,hours,expected", [
    ("Asia/Seoul", "12:30", "09:00-10:00", "09:30"),
    ("Asia/Seoul", "09:30", "", "21:30"),
    ("UTC", "08:00", "", "12:30"),
])
def test_quiet_windows_stay_in_their_own_zones(tmp_path, profile_zone, departure, hours, expected):
    preferences(Ledger(tmp_path), {"timezone": profile_zone})
    result = watch(tmp_path, departure_at=f"2026-11-10T{departure}:00+09:00",
                   hb2_timezone="America/Los_Angeles", hb2_quiet_hours=hours)
    day = "10" if departure == "12:30" else "09"
    offset = "+00:00" if profile_zone == "UTC" else "+09:00"
    assert result["pulse_create"]["trigger"]["at"] == f"2026-11-{day}T{expected}:00{offset}"


@pytest.mark.parametrize("mode,expected", [("resolved", "14:30"), ("none", "15:00"),
                                          ("error", "15:00"), ("unavailable", "15:00")])
def test_hermes_hb2_timezone_and_fallback(tmp_path, monkeypatch, mode, expected):
    def get_timezone():
        if mode == "error":
            raise RuntimeError("Synthetic host unavailable")
        return ZoneInfo("America/Los_Angeles") if mode == "resolved" else None

    monkeypatch.setitem(sys.modules, "hermes_time",
                        None if mode == "unavailable" else SimpleNamespace(get_timezone=get_timezone))
    result = watch(tmp_path, departure_at="2026-11-10T18:00:00+09:00")
    assert result["pulse_create"]["trigger"]["at"] == f"2026-11-10T{expected}:00+09:00"


@pytest.mark.parametrize("offset,followup", [("+02:00", "02:00"), ("+01:00", "03:00")])
def test_paris_fall_back_arrival_accepts_either_fold(tmp_path, offset, followup):
    result = watch(tmp_path, departure_at="2026-10-24T12:00:00+09:00",
                   arrival_at=f"2026-10-25T02:30:00{offset}")
    assert result["moments"][3]["at"] == f"2026-10-25T{followup}:00+01:00"


@pytest.mark.parametrize("hours", ["22:00", "22:00-08:00-extra", "bad-08:00", "25:00-08:00"])
def test_malformed_hb2_quiet_hours_is_value_error(tmp_path, hours):
    with pytest.raises(ValueError, match="hb2_quiet_hours"):
        watch(tmp_path, hb2_quiet_hours=hours)


@pytest.mark.parametrize("saved,expected", [("22:00–08:00", "22:00-08:00"), (" 22:00 - 08:00 ", "22:00-08:00"),
                                            ("off", ""), ("Off", ""), ("none", "")])
def test_saved_hb2_quiet_hours_spellings_are_accepted(tmp_path, saved, expected):
    result = watch(tmp_path, hb2_quiet_hours=saved)
    assert result["status"] != "needs_input"
    stored = dispatch(tmp_path, {"operation": "trip_watch_plan", "data": {"action": "status", "trip_id": "synthetic"}})
    assert stored["inputs"]["hb2_quiet_hours"] == expected


def test_long_hb2_quiet_hours_is_rejected_quickly(tmp_path):
    import time
    started = time.monotonic()
    with pytest.raises(ValueError, match="hb2_quiet_hours"):
        watch(tmp_path, hb2_quiet_hours="22:00" + " " * 100000 + "08:00")
    assert time.monotonic() - started < 1
