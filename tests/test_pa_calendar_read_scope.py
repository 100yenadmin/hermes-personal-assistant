"""Synthetic evidence for accepted Calendar reads and non-trip writes."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from personal_assistant.calendar import stable_event_id
from personal_assistant.calendar_workflow import bind, sync_trip
from personal_assistant.daily_ops.calendar_source import collect_calendar_scope
from personal_assistant.daily_ops.gog_collector import DailyOpsError
from personal_assistant.state import Ledger


class Request:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.headers = {}

    def execute(self):
        if self.error:
            raise self.error
        return copy.deepcopy(self.value)


class Calendars:
    def __init__(self, account):
        self.account = account

    def get(self, *, calendarId):
        assert calendarId == "primary"
        return Request({"id": self.account})


class CalendarList:
    def __init__(self, roles=None):
        self.roles = roles or {}

    def get(self, *, calendarId):
        return Request({"id": calendarId, "accessRole": self.roles.get(calendarId, "owner")})


class Events:
    def __init__(self, pages=None):
        self.pages = pages or {}
        self.list_calls = []
        self.store = {}
        self.insert_calls = []
        self.update_calls = []

    def list(self, **kwargs):
        self.list_calls.append(dict(kwargs))
        value = self.pages.get(kwargs["calendarId"], {"items": []})
        if isinstance(value, Exception):
            return Request(error=value)
        return Request(value)

    def get(self, *, calendarId, eventId):
        del calendarId
        if eventId not in self.store:
            error = RuntimeError("synthetic missing")
            error.status_code = 404
            return Request(error=error)
        return Request(self.store[eventId])

    def insert(self, *, calendarId, body):
        self.insert_calls.append({"calendar_id": calendarId, "body": copy.deepcopy(body)})
        stored = copy.deepcopy(body)
        stored["etag"] = "v1"
        self.store[body["id"]] = stored
        return Request(stored)

    def update(self, *, calendarId, eventId, body, headers=None):
        self.update_calls.append({"calendar_id": calendarId, "event_id": eventId, "body": copy.deepcopy(body), "headers": headers})
        stored = copy.deepcopy(body)
        stored["etag"] = "v2"
        self.store[eventId] = stored
        return Request(stored)


class Service:
    def __init__(self, account="owner@example.com", pages=None, roles=None):
        self._calendars = Calendars(account)
        self._calendar_list = CalendarList(roles)
        self._events = Events(pages)

    def calendars(self):
        return self._calendars

    def calendarList(self):
        return self._calendar_list

    def events(self):
        return self._events


def profile(tmp_path: Path) -> Path:
    root = tmp_path / "profile"
    root.mkdir(mode=0o700)
    return root


def config(*, calendar_ids=None, include_binding=False, provider="profile_google"):
    return {
        "accounts": {"work": "owner@example.com", "personal": None},
        "calendar": {
            "provider": provider,
            "read_scope": {
                "accepted": True,
                "calendar_ids": list(calendar_ids or []),
                "include_pa_binding": include_binding,
            },
        },
    }


def test_profile_read_scope_preserves_typed_times_url_and_expands_occurrences(tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_OPS_NOW", "2026-09-08T00:00:00+00:00")
    root = profile(tmp_path)
    Ledger(root).put(
        "action",
        "pa:calendar-binding",
        {"calendar_id": "pa-owned", "expected_account": "owner@example.com"},
        action_type="calendar_binding",
        status="bound",
    )
    service = Service(
        pages={
            "primary": {"items": [{
                "id": "timed", "summary": "Planning",
                "start": {"dateTime": "2026-09-08T09:00:00+07:00", "timeZone": "Asia/Bangkok"},
                "end": {"dateTime": "2026-09-08T10:00:00+07:00", "timeZone": "Asia/Bangkok"},
                "htmlLink": "https://calendar.example.invalid/timed",
                "recurringEventId": "series-1",
                "originalStartTime": {"dateTime": "2026-09-08T09:00:00+07:00", "timeZone": "Asia/Bangkok"},
            }]},
            "pa-owned": {"items": [{
                "id": "all-day", "summary": "Away",
                "start": {"date": "2026-09-09"}, "end": {"date": "2026-09-10"},
                "source": {"url": "https://calendar.example.invalid/all-day"},
            }]},
        }
    )

    result = collect_calendar_scope(
        config(calendar_ids=["primary", "pa-owned"], include_binding=True),
        2,
        profile=str(root),
        service=service,
    )

    assert result.complete is True and result.truncated is False
    assert [call["calendarId"] for call in service.events().list_calls] == ["primary", "pa-owned"]
    assert all(call["singleEvents"] is True and call["orderBy"] == "startTime" for call in service.events().list_calls)
    assert result.items[0]["start"] == {"dateTime": "2026-09-08T09:00:00+07:00", "timeZone": "Asia/Bangkok"}
    assert result.items[0]["timezone"] == "Asia/Bangkok"
    assert result.items[0]["url"].endswith("/timed")
    assert result.items[0]["recurringEventId"] == "series-1"
    assert result.items[1]["start"] == {"date": "2026-09-09"}
    assert len(result.coverage) == 2
    assert result.coverage[1]["origin"] == "configured+pa-binding"


def test_profile_read_scope_rejects_account_mismatch_before_event_read(tmp_path):
    root = profile(tmp_path)
    service = Service(account="different@example.com")
    with pytest.raises(DailyOpsError, match="does not match"):
        collect_calendar_scope(config(calendar_ids=["primary"]), 2, profile=str(root), service=service)
    assert service.events().list_calls == []


def test_partial_calendar_failure_stays_visible(tmp_path):
    root = profile(tmp_path)
    service = Service(pages={
        "primary": {"items": [{"id": "ok", "start": {"date": "2026-09-08"}, "end": {"date": "2026-09-09"}}]},
        "missing": RuntimeError("synthetic provider failure"),
    })
    result = collect_calendar_scope(config(calendar_ids=["primary", "missing"]), 2, profile=str(root), service=service)
    assert [item["id"] for item in result.items] == ["ok"]
    assert result.complete is False and result.truncated is False
    assert [entry["status"] for entry in result.coverage] == ["complete", "error"]


def test_gog_is_only_used_as_configured_alternative(monkeypatch):
    calls = []

    def fake_collect(account, args, parser, **kwargs):
        del parser, kwargs
        calls.append((account, args))
        from personal_assistant.daily_ops.common import Collected
        return Collected([{"id": "gog", "start": "2026-09-08", "end": "2026-09-09"}], True, False, None)

    monkeypatch.setattr("personal_assistant.daily_ops.calendar_source.collect_pages", fake_collect)
    result = collect_calendar_scope(config(calendar_ids=["accepted-calendar"], provider="gog"), 2)
    assert calls == [("owner@example.com", ["calendar", "events", "accepted-calendar", "--days=2"])]
    assert result.items[0]["start"] == {"date": "2026-09-08"}


def test_non_trip_action_sync_uses_action_identity_and_owned_event_markers(tmp_path):
    root = profile(tmp_path)
    ledger = Ledger(root)
    service = Service(roles={"pa-owned": "owner"})
    bind(ledger, "pa-owned", "owner@example.com", service=service)
    action_id = "stable-action"
    ledger.put("action", action_id, {"calendar_event": {
        "summary": "Dentist",
        "start": "2026-09-09T13:00:00+07:00",
        "end": "2026-09-09T14:00:00+07:00",
        "timezone": "Asia/Bangkok",
        "url": "https://example.invalid/appointment",
    }}, action_type="commitment")

    created = sync_trip(ledger, action_id=action_id, service=service)
    expected = stable_event_id(str(root), "pa-owned", action_id)
    body = service.events().insert_calls[0]["body"]
    assert created["status"] == "created" and body["id"] == expected
    assert body["extendedProperties"]["private"] == {
        "pa_owner": str(root), "pa_source_uid": action_id,
        "pa_source_url": "https://example.invalid/appointment",
    }
    replay = sync_trip(ledger, action_id=action_id, service=service)
    assert replay["status"] == "unchanged" and len(service.events().insert_calls) == 1
    stored = ledger.get("action", action_id)
    assert stored["fields"]["calendar_mapping"]["etag"] == "v1"


def test_non_trip_sync_rejects_ambiguous_input_and_never_updates_unowned_event(tmp_path):
    root = profile(tmp_path)
    ledger = Ledger(root)
    service = Service()
    bind(ledger, "pa-owned", "owner@example.com", service=service)
    with pytest.raises(ValueError, match="exactly one"):
        sync_trip(ledger, service=service)
    with pytest.raises(ValueError, match="exactly one"):
        sync_trip(ledger, trip_id="trip", action_id="action", service=service)

    action_id = "unowned-action"
    ledger.put("action", action_id, {"calendar_event": {
        "summary": "Private appointment",
        "start": "2026-09-09T13:00:00+07:00",
        "end": "2026-09-09T14:00:00+07:00",
        "timezone": "Asia/Bangkok",
    }}, action_type="commitment")
    event_id = stable_event_id(str(root), "pa-owned", action_id)
    service.events().store[event_id] = {
        "id": event_id, "etag": "v1", "summary": "Other owner",
        "start": {"dateTime": "2026-09-09T13:00:00+07:00", "timeZone": "Asia/Bangkok"},
        "end": {"dateTime": "2026-09-09T14:00:00+07:00", "timeZone": "Asia/Bangkok"},
        "extendedProperties": {"private": {"pa_owner": "other", "pa_source_uid": action_id}},
    }
    result = sync_trip(ledger, action_id=action_id, service=service)
    assert result["status"] == "unowned"
    assert service.events().update_calls == []
