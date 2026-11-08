"""Synthetic evidence for accepted Calendar reads; PA holds no Google token."""
from __future__ import annotations

import pytest

from personal_assistant.daily_ops.calendar_source import collect_calendar_scope
from personal_assistant.daily_ops.common import Collected
from personal_assistant.daily_ops.config import validate_config as validate
from personal_assistant.daily_ops.gog_collector import DailyOpsError
from personal_assistant.entry import OPERATIONS, dispatch


def config(*, calendar_ids=None, provider="gog", **read_scope):
    return {
        "accounts": {"work": "owner@example.com", "personal": None},
        "calendar": {
            "provider": provider,
            "read_scope": {"accepted": True, "calendar_ids": list(calendar_ids or []), **read_scope},
        },
    }


def fake_pages(pages, calls):
    def collect(account, args, parser, **kwargs):
        del parser, kwargs
        calls.append((account, args))
        value = pages.get(args[2], [])
        if isinstance(value, Exception):
            raise value
        return Collected(value, True, False, None)
    return collect


def test_gog_read_scope_preserves_typed_times_url_and_dedupes(monkeypatch):
    calls = []
    monkeypatch.setattr("personal_assistant.daily_ops.calendar_source.collect_pages", fake_pages({
        "primary": [{
            "id": "timed", "summary": "Planning",
            "start": {"dateTime": "2026-09-08T09:00:00+07:00", "timeZone": "Asia/Bangkok"},
            "end": {"dateTime": "2026-09-08T10:00:00+07:00", "timeZone": "Asia/Bangkok"},
            "htmlLink": "https://calendar.example.invalid/timed",
            "recurringEventId": "series-1",
        }],
        "accepted-calendar": [{"id": "gog", "start": "2026-09-09", "end": "2026-09-10"}],
    }, calls))
    result = collect_calendar_scope(config(calendar_ids=["primary", "PRIMARY", "accepted-calendar"]), 2)
    assert calls == [("owner@example.com", ["calendar", "events", "primary", "--days=2"]),
                     ("owner@example.com", ["calendar", "events", "accepted-calendar", "--days=2"])]
    assert result.complete is True and result.truncated is False
    assert result.items[0]["start"] == {"dateTime": "2026-09-08T09:00:00+07:00", "timeZone": "Asia/Bangkok"}
    assert result.items[0]["url"].endswith("/timed") and result.items[0]["recurringEventId"] == "series-1"
    assert result.items[1]["start"] == {"date": "2026-09-09"}
    assert [entry["provider"] for entry in result.coverage] == ["gog", "gog"]


def test_partial_calendar_failure_stays_visible(monkeypatch):
    monkeypatch.setattr("personal_assistant.daily_ops.calendar_source.collect_pages", fake_pages({
        "primary": [{"id": "ok", "start": {"date": "2026-09-08"}, "end": {"date": "2026-09-09"}}],
        "missing": DailyOpsError("synthetic provider failure"),
    }, []))
    result = collect_calendar_scope(config(calendar_ids=["primary", "missing"]), 2)
    assert [item["id"] for item in result.items] == ["ok"]
    assert result.complete is False and result.truncated is False
    assert [entry["status"] for entry in result.coverage] == ["complete", "error"]


@pytest.mark.parametrize("cfg,message", [
    (config(calendar_ids=["primary"], provider="profile_google"), "provider must be gog"),
    (config(calendar_ids=["primary"], include_pa_binding=True), "removed with Calendar sync"),
    (config(), "no accepted calendars"),
])
def test_removed_profile_token_paths_are_refused_clearly(cfg, message, monkeypatch):
    monkeypatch.setattr("personal_assistant.daily_ops.calendar_source.collect_pages",
                        lambda *a, **k: pytest.fail("no read may start"))
    with pytest.raises(DailyOpsError, match=message):
        collect_calendar_scope(cfg, 2)


def test_config_validation_names_the_removed_calendar_paths():
    base = {"tenant": {}, "delivery": {}, "timezone": "UTC", "accounts": {"work": "owner@example.com"}}
    errors = validate({**base, **config(calendar_ids=["primary"], provider="profile_google", include_pa_binding=True)})
    assert "calendar.provider must be gog" in errors
    assert "calendar.read_scope.include_pa_binding was removed with Calendar sync" in errors


def test_calendar_write_operations_are_gone(tmp_path):
    assert not {"calendar_bind", "calendar_sync"} & set(OPERATIONS)
    for operation in ("calendar_bind", "calendar_sync"):
        with pytest.raises(ValueError, match="unknown PA operation"):
            dispatch(tmp_path, {"operation": operation, "data": {"calendar_id": "x", "expected_account": "a@b.c"}})
    assert not list(tmp_path.rglob("google_token.json"))
