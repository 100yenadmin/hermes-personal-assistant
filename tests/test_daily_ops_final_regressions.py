"""Two independently reported final regressions, provider-free."""
import datetime as dt
from personal_assistant.daily_ops import doctor, trip_context


def test_doctor_accepts_canonical_identity_scope_but_rejects_broader_scope(monkeypatch):
    account = "owner@example.com"
    scopes = ["https://www.googleapis.com/auth/gmail.readonly",
              "https://www.googleapis.com/auth/calendar.readonly",
              "https://www.googleapis.com/auth/userinfo.email", "openid"]
    entry = {"email": account, "valid": True, "scopes": scopes}
    monkeypatch.setattr(doctor, "gog_binary", lambda: "fake-gog")
    monkeypatch.setattr(doctor, "auth_check", lambda: {"accounts": [entry]})
    cfg = {"accounts": {"work": account}}
    assert doctor.check_scopes(cfg)[0] is True
    entry["scopes"] = scopes + ["https://www.googleapis.com/auth/gmail.send"]
    assert doctor.check_scopes(cfg)[0] is False
    entry["scopes"] = scopes
    entry["valid"] = "true"
    assert doctor.check_scopes(cfg)[0] is False


def test_leave_now_catches_late_tick_until_start_with_stable_phase_key(monkeypatch):
    monkeypatch.setattr(trip_context.geo, "geocode", lambda *a: (3.0, 4.0))
    cfg = {"timezone": "UTC", "travel": {"leave_by": True, "buffer_min": 15,
            "heads_up_min": 45, "geocoder": {"consent": True}}}
    event = {"id": "event-example", "summary": "Client meeting", "location": "Example office",
             "start": {"dateTime": "2026-09-08T10:00:00+00:00"}}
    def tick(hour, minute):
        return trip_context.leave_by_alerts(cfg, [event],
            dt.datetime(2026, 9, 8, hour, minute, tzinfo=dt.timezone.utc),
            lambda *a: 20, base=((1.0, 2.0), "Example base"))
    # Departure 09:25; a supported 20-minute tick crosses it at 09:35.
    heads = tick(9, 15)
    late = tick(9, 35)
    assert len(heads) == len(late) == 1
    assert heads[0]["phase"] == "heads" and late[0]["phase"] == "now"
    assert heads[0]["key"] != late[0]["key"]
    assert tick(9, 55)[0]["key"] == late[0]["key"]
    assert tick(10, 1) == []
