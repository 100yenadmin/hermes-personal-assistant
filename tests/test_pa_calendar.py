"""Synthetic Google Calendar API tests for the PA adapter."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

from personal_assistant.calendar import (
    CalendarAuthError,
    CalendarSync,
    build_calendar_service,
    stable_event_id,
)


class FakeHttpError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.resp = SimpleNamespace(status=status)


class FakeRequest:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.headers = {}

    def execute(self):
        if self.error:
            raise self.error
        return copy.deepcopy(self.result)


class FakeEvents:
    def __init__(self):
        self.store = {}
        self.insert_bodies = []
        self.update_calls = []
        self.fail_uncertain_insert = False
        self.first_update_412 = False
        self.always_update_412 = False

    def get(self, *, calendarId, eventId):
        del calendarId
        if eventId not in self.store:
            return FakeRequest(error=FakeHttpError(404))
        return FakeRequest(result=self.store[eventId])

    def insert(self, *, calendarId, body):
        del calendarId
        self.insert_bodies.append(copy.deepcopy(body))

        def insert_result():
            stored = copy.deepcopy(body)
            stored["etag"] = "v1"
            self.store[body["id"]] = stored
            if self.fail_uncertain_insert:
                raise TimeoutError("synthetic uncertain insert")
            return stored

        return _CallableRequest(insert_result)

    def update(self, *, calendarId, eventId, body, headers=None):
        del calendarId
        self.update_calls.append({"event_id": eventId, "body": copy.deepcopy(body), "headers": headers})
        request = _CallableRequest(lambda: self._update_result(eventId, body, headers))
        return request

    def _update_result(self, event_id, body, headers):
        if self.first_update_412 or self.always_update_412:
            self.first_update_412 = False
            raise FakeHttpError(412)
        expected = (headers or {}).get("If-Match")
        if expected != self.store[event_id].get("etag"):
            raise FakeHttpError(412)
        stored = copy.deepcopy(body)
        stored["etag"] = f"v{len(self.update_calls) + 1}"
        self.store[event_id] = stored
        return stored


class _CallableRequest(FakeRequest):
    def __init__(self, callback):
        self.callback = callback
        self.headers = {}

    def execute(self):
        return copy.deepcopy(self.callback())


class FakeService:
    def __init__(self):
        self.resource = FakeEvents()

    def events(self):
        return self.resource


class NoHeaderRequest:
    headers = None

    def execute(self):
        raise AssertionError("unconditional update must not execute")


class NoHeaderEvents(FakeEvents):
    def update(self, *, calendarId, eventId, body):
        del calendarId
        self.update_calls.append({"event_id": eventId, "body": copy.deepcopy(body)})
        return NoHeaderRequest()


def timed_event(**overrides):
    event = {
        "uid": "source-1",
        "recurrence_id": "",
        "summary": "Planning",
        "start": "2026-09-07T09:00:00+07:00",
        "end": "2026-09-07T10:00:00+07:00",
        "all_day": False,
        "timezone": "Asia/Bangkok",
        "location": "Room A",
        "description": "Agenda",
        "url": "https://example.invalid/event/source-1",
        "status": "CONFIRMED",
    }
    event.update(overrides)
    return event


class CalendarSyncTests(TestCase):
    def setUp(self):
        self.service = FakeService()
        self.sync = CalendarSync(self.service, "primary", "profile-key")

    def test_insert_is_deterministic_and_replay_is_idempotent(self):
        event = timed_event()
        created = self.sync.sync(event)
        expected_id = stable_event_id("profile-key", "primary", "source-1", "")
        self.assertEqual(created["status"], "created")
        self.assertEqual(created["remote_id"], expected_id)
        self.assertEqual(self.service.resource.insert_bodies[0]["id"], expected_id)
        self.assertEqual(self.service.resource.insert_bodies[0]["status"], "confirmed")
        replay = self.sync.sync(event, created)
        self.assertEqual(replay["status"], "unchanged")
        self.assertEqual(len(self.service.resource.insert_bodies), 1)
        self.assertEqual(len(self.service.resource.update_calls), 0)

    def test_update_sends_if_match_and_preserves_disjoint_user_edit(self):
        event = timed_event()
        created = self.sync.sync(event)
        event_id = created["remote_id"]
        self.service.resource.store[event_id]["location"] = "User Room"
        self.service.resource.store[event_id]["etag"] = "v2"
        desired = timed_event(summary="Changed by source")
        updated = self.sync.sync(desired, created)
        self.assertEqual(updated["status"], "updated")
        self.assertEqual(self.service.resource.update_calls[0]["headers"]["If-Match"], "v2")
        self.assertEqual(self.service.resource.store[event_id]["location"], "User Room")
        self.assertEqual(self.service.resource.store[event_id]["summary"], "Changed by source")

    def test_conflicting_user_edit_does_not_write(self):
        event = timed_event()
        created = self.sync.sync(event)
        event_id = created["remote_id"]
        self.service.resource.store[event_id]["summary"] = "User title"
        self.service.resource.store[event_id]["etag"] = "v2"
        result = self.sync.sync(timed_event(summary="Source title"), created)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["conflict_fields"], ["summary"])
        self.assertEqual(len(self.service.resource.update_calls), 0)

    def test_full_resource_update_preserves_user_fields_and_private_metadata(self):
        event = timed_event()
        created = self.sync.sync(event)
        event_id = created["remote_id"]
        remote = self.service.resource.store[event_id]
        remote.update(
            {
                "colorId": "7",
                "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 15}]},
                "attachments": [{"fileUrl": "https://example.invalid/file"}],
                "extendedProperties": {
                    "private": {
                        "pa_owner": "profile-key",
                        "pa_source_uid": "source-1",
                        "user_private": "retain-me",
                    }
                },
            }
        )
        remote["etag"] = "v2"
        result = self.sync.sync(timed_event(summary="Source title"), created)
        self.assertEqual(result["status"], "updated")
        updated = self.service.resource.store[event_id]
        self.assertEqual(updated["colorId"], "7")
        self.assertEqual(updated["reminders"]["overrides"][0]["minutes"], 15)
        self.assertEqual(updated["attachments"][0]["fileUrl"], "https://example.invalid/file")
        self.assertEqual(updated["extendedProperties"]["private"]["user_private"], "retain-me")

    def test_three_replays_keep_user_title_while_source_changes_location(self):
        event = timed_event()
        created = self.sync.sync(event)
        event_id = created["remote_id"]
        self.service.resource.store[event_id]["summary"] = "User title"
        self.service.resource.store[event_id]["etag"] = "v2"

        replay = self.sync.sync(event, created)
        self.assertEqual(replay["status"], "unchanged")
        self.assertEqual(replay["owned_fields"]["summary"], "Planning")

        moved = self.sync.sync(timed_event(location="Source Room 2"), replay)
        self.assertEqual(moved["status"], "updated")
        self.assertEqual(self.service.resource.store[event_id]["summary"], "User title")
        self.assertEqual(self.service.resource.store[event_id]["location"], "Source Room 2")

        moved_again = self.sync.sync(timed_event(location="Source Room 3"), moved)
        self.assertEqual(moved_again["status"], "updated")
        self.assertEqual(self.service.resource.store[event_id]["summary"], "User title")
        self.assertEqual(self.service.resource.store[event_id]["location"], "Source Room 3")

    def test_missing_source_baseline_does_not_overwrite_existing_owned_event(self):
        event = timed_event()
        created = self.sync.sync(event)
        event_id = created["remote_id"]
        previous = {"remote_id": event_id, "etag": created["etag"]}
        result = self.sync.sync(timed_event(summary="Source title"), previous)
        self.assertEqual(result["status"], "baseline_required")
        self.assertEqual(len(self.service.resource.update_calls), 0)

    def test_if_match_unavailable_fails_closed_before_execute(self):
        event = timed_event()
        created = self.sync.sync(event)
        no_header = NoHeaderEvents()
        no_header.store = copy.deepcopy(self.service.resource.store)
        self.service.resource = no_header
        result = self.sync.sync(timed_event(summary="Source title"), created)
        self.assertEqual(result["status"], "retryable_conflict")
        self.assertIn("if_match_unavailable", result["warnings"])

    def test_attendees_and_recurring_sources_are_not_flattened_or_written(self):
        with_attendees = self.sync.sync(timed_event(attendees=[{"email": "guest@example.invalid"}]))
        self.assertEqual(with_attendees["status"], "cannot_sync")
        self.assertIn("cannot_sync_attendees", with_attendees["warnings"])
        recurring = self.sync.sync(timed_event(recurrence=["RRULE:FREQ=DAILY"]))
        self.assertEqual(recurring["status"], "cannot_sync")
        self.assertIn("cannot_sync_recurring", recurring["warnings"])
        self.assertEqual(self.service.resource.insert_bodies, [])

        created = self.sync.sync(timed_event())
        self.service.resource.store[created["remote_id"]]["attendees"] = [
            {"email": "guest@example.invalid"}
        ]
        retained = self.sync.sync(timed_event(summary="Source title"), created)
        self.assertEqual(retained["status"], "cannot_sync")
        self.assertIn("cannot_sync_attendees", retained["warnings"])
        self.assertEqual(len(self.service.resource.update_calls), 0)

    def test_412_rereads_once_then_retries_with_latest_etag(self):
        event = timed_event()
        created = self.sync.sync(event)
        event_id = created["remote_id"]
        self.service.resource.store[event_id]["location"] = "User Room"
        self.service.resource.store[event_id]["etag"] = "v2"
        self.service.resource.first_update_412 = True
        result = self.sync.sync(timed_event(summary="Source title"), created)
        self.assertEqual(result["status"], "updated")
        self.assertEqual(len(self.service.resource.update_calls), 2)
        self.assertEqual(self.service.resource.update_calls[0]["headers"]["If-Match"], "v2")
        self.assertEqual(self.service.resource.update_calls[1]["headers"]["If-Match"], "v2")

    def test_repeated_412_is_retryable_without_loop(self):
        event = timed_event()
        created = self.sync.sync(event)
        self.service.resource.always_update_412 = True
        result = self.sync.sync(timed_event(summary="Source title"), created)
        self.assertEqual(result["status"], "retryable_conflict")
        self.assertIn("repeated_etag_conflict", result["warnings"])
        self.assertEqual(len(self.service.resource.update_calls), 2)

    def test_unowned_event_is_never_updated(self):
        event = timed_event()
        event_id = stable_event_id("profile-key", "primary", "source-1", "")
        self.service.resource.store[event_id] = {
            "id": event_id,
            "etag": "v1",
            "summary": "Someone else's event",
            "start": {"dateTime": event["start"], "timeZone": event["timezone"]},
            "end": {"dateTime": event["end"], "timeZone": event["timezone"]},
            "extendedProperties": {"private": {"pa_owner": "other", "pa_source_uid": "source-1"}},
        }
        result = self.sync.sync(event)
        self.assertEqual(result["status"], "unowned")
        self.assertEqual(self.service.resource.update_calls, [])

    def test_uncertain_insert_recovers_by_deterministic_id(self):
        self.service.resource.fail_uncertain_insert = True
        result = self.sync.sync(timed_event())
        self.assertEqual(result["status"], "created_recovered")
        self.assertIn("uncertain_insert_recovered", result["warnings"])
        self.assertEqual(len(self.service.resource.insert_bodies), 1)

    def test_all_day_end_is_day_exclusive_and_recurrence_changes_identity(self):
        event = timed_event(
            uid="all-day",
            recurrence_id="2026-09-07",
            all_day=True,
            start="2026-09-07",
            end=None,
            timezone="Asia/Bangkok",
        )
        result = self.sync.sync(event)
        body = self.service.resource.insert_bodies[0]
        self.assertEqual(body["start"], {"date": "2026-09-07"})
        self.assertEqual(body["end"], {"date": "2026-09-08"})
        self.assertNotEqual(
            result["event_id"], stable_event_id("profile-key", "primary", "all-day", "other")
        )

    def test_timed_unknown_end_is_explicitly_blocked(self):
        result = self.sync.sync(timed_event(end=None))
        self.assertEqual(result["status"], "cannot_sync")
        self.assertIn("cannot_sync_unknown_end", result["warnings"])
        self.assertEqual(self.service.resource.insert_bodies, [])

    def test_only_explicit_cancelled_source_cancels_owned_event(self):
        event = timed_event()
        created = self.sync.sync(event)
        cancelled = self.sync.sync(timed_event(status="CANCELLED"), created)
        self.assertEqual(cancelled["status"], "updated")
        self.assertEqual(self.service.resource.store[created["remote_id"]]["status"], "cancelled")

    def test_stable_identity_uses_unambiguous_canonical_json_components(self):
        expected = __import__("hashlib").sha256(
            json.dumps(
                ["ab", "c", "d", ""], ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(stable_event_id("ab", "c", "d", ""), expected)
        self.assertNotEqual(stable_event_id("ab", "c", "d", ""), stable_event_id("a", "bc", "d", ""))


class OAuthFactoryTests(TestCase):
    def test_read_only_profile_scope_is_rejected_before_google_import(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as root:
            Path(root, "google_token.json").write_text(
                json.dumps({"scopes": ["https://www.googleapis.com/auth/calendar.readonly"]}),
                encoding="utf-8",
            )
            with self.assertRaises(CalendarAuthError):
                build_calendar_service(root)
