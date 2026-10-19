import datetime as dt

import pytest

from personal_assistant.trip_math import ARRIVAL_DEFAULTS, feasibility, leave_by

DEPARTURE = "2026-11-10T12:03:59Z"
ARRIVAL = "2026-11-10T18:00:00Z"


def test_leave_by_basis_floor_and_local_time():
    scheduled = leave_by(DEPARTURE, 180, "Asia/Tokyo")
    assert scheduled == {"at": "2026-11-10T18:00:00+09:00", "local_time": "18:00", "timezone": "Asia/Tokyo",
                         "basis": "scheduled", "lead_minutes": 180, "weather_extra_minutes": 0, "weather_included_minutes": 0, "severity": None, "assumed": []}
    estimated = leave_by(DEPARTURE, 180, "Asia/Tokyo", estimated="2026-11-10T12:29:00Z")
    assert estimated["basis"] == "estimated" and estimated["local_time"] == "18:25"


@pytest.mark.parametrize("departure,expected", [
    ("2026-03-08T08:33:00Z", "2026-03-08T01:30:00-05:00"),
    ("2026-11-01T07:33:00Z", "2026-11-01T01:30:00-04:00"),
    ("2026-11-01T08:33:00Z", "2026-11-01T01:30:00-05:00")])
def test_dst_safe_elapsed_minutes(departure, expected):
    assert leave_by(departure, 120, "America/New_York")["at"] == expected


@pytest.mark.parametrize("severity,extra", [(None, 0), ("clear", 0), ("unknown", 0), ("gusts", 15),
    ("heavy rain", 30), ("freezing", 30), ("thunderstorm", 30), ("snow", 45)])
def test_weather_extras_and_assumptions(severity, extra):
    result = leave_by(DEPARTURE, 180, "UTC", severity=severity)
    assert result["weather_extra_minutes"] == extra
    assert result["assumed"] == (["weather_extra_minutes"] if extra else [])
    assert dt.datetime.fromisoformat(result["at"]) == dt.datetime(2026, 11, 10, 9, tzinfo=dt.timezone.utc) - dt.timedelta(minutes=extra)


@pytest.mark.parametrize("value", [-1, 1.5, True, "20"])
def test_minutes_require_nonnegative_ints(value):
    with pytest.raises(ValueError):
        leave_by(DEPARTURE, value, "UTC")
    for key in ARRIVAL_DEFAULTS:
        with pytest.raises(ValueError):
            feasibility(ARRIVAL, "2026-11-10T22:00:00Z", "UTC", **{key: value})


@pytest.mark.parametrize("kwargs", [{"departure": "2026-11-10T12:00:00"}, {"estimated": "2026-11-10T12:00:00"}])
def test_leave_rejects_naive_times(kwargs):
    with pytest.raises(ValueError):
        leave_by(**{"departure": DEPARTURE, "lead_minutes": 180, "origin_tz": "UTC", **kwargs})


@pytest.mark.parametrize("key", ["arrival", "estimated", "commitment_at"])
def test_feasibility_rejects_naive_times(key):
    with pytest.raises(ValueError):
        feasibility(**{"arrival": ARRIVAL, "commitment_at": "2026-11-10T22:00:00Z", "destination_tz": "UTC",
                       key: "2026-11-10T20:00:00"})


@pytest.mark.parametrize("commitment,reachable,alternatives,slack", [
    ("22:00", True, [], 135), ("20:00", True, ["go_direct_from_airport"], 15),
    ("19:59", False, ["tell_them_you_will_be_late", "move_the_commitment", "go_direct_from_airport"], 14)])
def test_feasibility_options_and_named_defaults(commitment, reachable, alternatives, slack):
    result = feasibility(ARRIVAL, f"2026-11-10T{commitment}:00Z", "Europe/Paris")
    assert result["reachable"] is reachable and result["alternatives"] == alternatives
    assert result["slack_minutes"] == slack and result["assumed"] == list(ARRIVAL_DEFAULTS)
    assert result["ready_at"] == "2026-11-10T20:45:00+01:00" and result["ready_local_time"] == "20:45"
    assert result["basis"] == "scheduled" and result["landing_at"] == "2026-11-10T18:00:00+00:00"


def test_estimate_and_overrides_remove_assumptions():
    result = feasibility(ARRIVAL, "2026-11-10T22:00:00Z", "UTC", estimated="2026-11-10T19:00:00Z",
                         processing_minutes=0, transfer_minutes=20, buffer_minutes=0)
    assert result["basis"] == "estimated" and result["slack_minutes"] == 160 and result["assumed"] == []
    partial = feasibility(ARRIVAL, "2026-11-10T22:00:00Z", "UTC", transfer_minutes=20)
    assert partial["assumed"] == ["processing_minutes", "buffer_minutes"]


@pytest.mark.parametrize("status", ["cancelled", "canceled", "diverted"])
def test_cancelled_or_diverted_has_no_math(status):
    assert feasibility("unused", "unused", "unused", status=status) == {"reachable": None, "reason": status}


def test_fixed_offset_zone_from_manual_trip_inputs():
    assert leave_by(DEPARTURE, 180, "UTC+09:00")["local_time"] == "18:00"


@pytest.mark.parametrize("included,extra,time", [(45, 0, "07:45"), (30, 15, "07:45"), (60, 0, "07:30")])
def test_weather_already_in_lead_adds_only_the_difference(included, extra, time):
    result = leave_by("2026-11-10T11:30:00Z", 180 + included, "UTC",
                      severity="snow", included_minutes=included)
    assert result["local_time"] == time
    assert result["weather_extra_minutes"] == extra
    assert result["weather_included_minutes"] == included
    assert result["assumed"] == (["weather_extra_minutes"] if extra else [])


@pytest.mark.parametrize("value", [-1, 1.5, True, "20", None])
def test_included_minutes_require_nonnegative_ints(value):
    with pytest.raises(ValueError):
        leave_by(DEPARTURE, 180, "UTC", included_minutes=value)
