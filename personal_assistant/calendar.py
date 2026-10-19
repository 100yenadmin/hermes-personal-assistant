"""Small, ownership-safe Google Calendar synchronisation adapter.

The adapter deliberately accepts an already constructed Google API service.
OAuth is kept in :func:`build_calendar_service` so callers can inject a fake
service for tests and so this module does not grow a second auth flow.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping


CALENDAR_WRITE_SCOPES = frozenset(
    {
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.app.created",
        "https://www.googleapis.com/auth/calendar.events.owned",
    }
)
CALENDAR_READ_SCOPES = frozenset(
    {
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events.readonly",
        *CALENDAR_WRITE_SCOPES,
    }
)

_MUTABLE_FIELDS = (
    "summary",
    "start",
    "end",
    "all_day",
    "timezone",
    "location",
    "description",
    "url",
    "status",
)
_MISSING = object()


class IfMatchUnavailable(RuntimeError):
    """Raised before execution when a request cannot carry ``If-Match``."""


class CalendarAuthError(RuntimeError):
    """Raised when the existing profile token cannot write calendar events."""


def stable_event_id(
    profile_key: str,
    calendar_id: str,
    uid: str,
    recurrence_id: str = "",
) -> str:
    """Return the deterministic, Google-compatible event ID for a source item."""

    material = json.dumps(
        [str(profile_key), str(calendar_id), str(uid), str(recurrence_id)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _status_code(exc: BaseException) -> int | None:
    """Read an HTTP-ish status without depending on googleapiclient."""

    for candidate in (
        getattr(exc, "status_code", None),
        getattr(exc, "status", None),
        getattr(getattr(exc, "resp", None), "status", None),
    ):
        try:
            if candidate is not None:
                return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _execute(request: Any) -> Any:
    execute = getattr(request, "execute", None)
    return execute() if callable(execute) else request


def _as_date(value: Any, timezone_name: str = "") -> str:
    if isinstance(value, datetime):
        if value.tzinfo is not None and timezone_name:
            try:
                from zoneinfo import ZoneInfo

                value = value.astimezone(ZoneInfo(timezone_name))
            except Exception as exc:
                raise ValueError("invalid calendar timezone") from exc
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or "T" in value:
        raise ValueError("all-day calendar values must be ISO dates")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("all-day calendar values must be ISO dates") from exc


def _as_datetime(value: Any, timezone_name: str = "") -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("timed calendar values must be ISO datetimes") from exc
    else:
        raise ValueError("timed calendar values must be ISO datetimes")

    if parsed.tzinfo is None:
        if not timezone_name:
            raise ValueError("timed calendar values must be timezone-aware")
        try:
            from zoneinfo import ZoneInfo

            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        except Exception as exc:
            raise ValueError("invalid calendar timezone") from exc
    # A canonical RFC3339 value makes replay comparisons stable.  Keep the
    # source offset (rather than converting all values to UTC), since the
    # event's explicit IANA timezone remains meaningful to Calendar.
    result = parsed.isoformat(timespec="seconds")
    return result[:-6] + "Z" if result.endswith("+00:00") else result


def _values_equal(field: str, left: Any, right: Any) -> bool:
    if left is _MISSING or right is _MISSING:
        return left is right
    if field in {"start", "end"} and isinstance(left, str) and isinstance(right, str):
        try:
            return _as_datetime(left) == _as_datetime(right)
        except ValueError:
            return left == right
    return left == right


def _normalise_event(event: Mapping[str, Any]) -> tuple[dict[str, Any], set[str], list[str]]:
    if not isinstance(event, Mapping):
        raise TypeError("calendar event must be a mapping")

    uid = str(event.get("uid", "")).strip()
    if not uid:
        raise ValueError("calendar event uid is required")
    recurrence_id = str(event.get("recurrence_id") or "")
    timezone_name = str(event.get("timezone") or "")
    all_day = bool(event.get("all_day", False))
    if "start" not in event or event.get("start") in (None, ""):
        raise ValueError("calendar event start is required")

    warnings: list[str] = []
    if all_day:
        start = _as_date(event["start"], timezone_name)
        end = (
            _as_date(event["end"], timezone_name)
            if event.get("end") not in (None, "")
            else (date.fromisoformat(start) + timedelta(days=1)).isoformat()
        )
    else:
        start = _as_datetime(event["start"], timezone_name)
        if event.get("end") in (None, ""):
            # Calendar cannot represent an event with an unknown duration.
            end = None
            warnings = ["cannot_sync_unknown_end"]
        else:
            end = _as_datetime(event["end"], timezone_name)

    status = str(event.get("status") or "CONFIRMED").upper()
    if status not in {"CONFIRMED", "CANCELLED"}:
        raise ValueError("calendar event status must be CONFIRMED or CANCELLED")

    normalised = {
        "uid": uid,
        "recurrence_id": recurrence_id,
        "summary": str(event.get("summary") or ""),
        "start": start,
        "end": end,
        "all_day": all_day,
        "timezone": timezone_name,
        "location": str(event.get("location") or ""),
        "description": str(event.get("description") or ""),
        "url": str(event.get("url") or ""),
        "status": status,
    }
    for recurrence_key in ("recurrence", "rrule", "recurrence_rule"):
        if recurrence_key in event:
            normalised[recurrence_key] = copy.deepcopy(event[recurrence_key])
    # Omitted optional source values must not erase a known value on a
    # partial refresh.  Required identity/time fields are always present.
    supplied = {"start", "all_day", "status"}
    supplied.update(field for field in _MUTABLE_FIELDS if field in event)
    if "end" in event and event.get("end") not in (None, ""):
        supplied.add("end")
    if "timezone" in event:
        supplied.add("timezone")
    return normalised, supplied, warnings


def _has_recurrence(event: Mapping[str, Any]) -> bool:
    """Identify a recurrence rule without flattening it into one event."""

    return bool(
        event.get("recurrence")
        or event.get("rrule")
        or event.get("recurrence_rule")
        or event.get("recurring")
    )


def _has_attendees(event: Mapping[str, Any]) -> bool:
    attendees = event.get("attendees")
    return bool(attendees)


def _event_body(fields: Mapping[str, Any], event_id: str, profile_key: str) -> dict[str, Any]:
    all_day = bool(fields.get("all_day", False))
    if all_day:
        start = {"date": fields["start"]}
        end = {"date": fields["end"]}
    else:
        start = {"dateTime": fields["start"]}
        end = {"dateTime": fields["end"]}
        if fields.get("timezone"):
            start["timeZone"] = fields["timezone"]
            end["timeZone"] = fields["timezone"]

    private = {
        "pa_owner": profile_key,
        "pa_source_uid": fields["uid"],
    }
    if fields.get("recurrence_id"):
        private["pa_recurrence_id"] = fields["recurrence_id"]
    if fields.get("url"):
        # Keep a private copy so replay and conflict checks retain the source
        # URL even if a client omits the writable top-level source field.
        private["pa_source_url"] = fields["url"]

    body = {
        "id": event_id,
        "summary": fields.get("summary", ""),
        "start": start,
        "end": end,
        "location": fields.get("location", ""),
        "description": fields.get("description", ""),
        "status": str(fields.get("status", "CONFIRMED")).lower(),
        "extendedProperties": {"private": private},
    }
    if fields.get("url"):
        body["source"] = {"url": fields["url"], "title": fields.get("summary", "")}
    return body


def _remote_fields(remote: Mapping[str, Any]) -> dict[str, Any]:
    private = (
        remote.get("extendedProperties", {}).get("private", {})
        if isinstance(remote.get("extendedProperties", {}), Mapping)
        else {}
    )
    start = remote.get("start", {}) or {}
    end = remote.get("end", {}) or {}
    all_day = "date" in start
    timezone_name = "" if all_day else str(start.get("timeZone") or "")
    url = str(private.get("pa_source_url") or "")
    if not url and isinstance(remote.get("source"), Mapping):
        url = str(remote["source"].get("url") or "")
    return {
        "uid": str(private.get("pa_source_uid") or ""),
        "recurrence_id": str(private.get("pa_recurrence_id") or ""),
        "summary": str(remote.get("summary") or ""),
        "start": start.get("date") if all_day else start.get("dateTime"),
        "end": end.get("date") if all_day else end.get("dateTime"),
        "all_day": all_day,
        "timezone": timezone_name,
        "location": str(remote.get("location") or ""),
        "description": str(remote.get("description") or ""),
        "url": url,
        "status": str(remote.get("status") or "CONFIRMED").upper(),
    }


def _previous_fields(previous: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(previous, Mapping):
        return {}
    for key in (
        "last_source_fields",
        "source_baseline",
        "owned_fields",
        "last_exported",
        "exported_fields",
        "fields",
    ):
        value = previous.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _accepted_source_fields(
    baseline: Mapping[str, Any],
    desired: Mapping[str, Any],
    supplied: set[str],
) -> dict[str, Any]:
    """Advance only the source baseline; remote-only edits stay out of it."""

    accepted = dict(baseline)
    accepted["uid"] = desired["uid"]
    accepted["recurrence_id"] = desired["recurrence_id"]
    for field in supplied:
        accepted[field] = desired[field]
    return accepted


def _update_body(
    remote: Mapping[str, Any],
    merged: Mapping[str, Any],
    changed: set[str],
    event_id: str,
    profile_key: str,
) -> dict[str, Any]:
    """Apply owned source changes to the complete fetched resource."""

    body = copy.deepcopy(dict(remote))
    # ETag is carried by the HTTP header, not as a replacement resource field.
    body.pop("etag", None)
    body["id"] = event_id

    if changed.intersection({"start", "end", "all_day", "timezone"}):
        canonical = _event_body(merged, event_id, profile_key)
        body["start"] = canonical["start"]
        body["end"] = canonical["end"]
    for field in ("summary", "location", "description"):
        if field in changed:
            body[field] = merged.get(field, "")
    if "status" in changed:
        body["status"] = str(merged.get("status", "CONFIRMED")).lower()

    extended = body.setdefault("extendedProperties", {})
    if not isinstance(extended, dict):
        extended = {}
        body["extendedProperties"] = extended
    private = extended.setdefault("private", {})
    if not isinstance(private, dict):
        private = {}
        extended["private"] = private
    private["pa_owner"] = profile_key
    private["pa_source_uid"] = merged["uid"]
    if merged.get("recurrence_id"):
        private["pa_recurrence_id"] = merged["recurrence_id"]
    else:
        private.pop("pa_recurrence_id", None)

    if "url" in changed:
        if merged.get("url"):
            private["pa_source_url"] = merged["url"]
            source = body.get("source")
            if not isinstance(source, dict):
                source = {}
            source["url"] = merged["url"]
            source.setdefault("title", merged.get("summary", ""))
            body["source"] = source
        else:
            private.pop("pa_source_url", None)
            body.pop("source", None)
    return body


class CalendarSync:
    """Synchronise one PA source event through an injected Calendar service."""

    def __init__(self, service: Any, calendar_id: str, profile_key: str):
        self.service = service
        self.calendar_id = str(calendar_id)
        self.profile_key = str(profile_key)

    def _get(self, event_id: str) -> tuple[str, Mapping[str, Any] | None]:
        try:
            remote = _execute(
                self.service.events()
                .get(calendarId=self.calendar_id, eventId=event_id)
            )
            if not isinstance(remote, Mapping):
                return "error", None
            return "found", remote
        except Exception as exc:
            if _status_code(exc) == 404:
                return "missing", None
            return "error", None

    def _update(self, event_id: str, body: Mapping[str, Any], etag: str) -> Any:
        updater = self.service.events().update
        try:
            request = updater(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=copy.deepcopy(body),
                headers={"If-Match": etag},
            )
        except TypeError:
            # googleapiclient's generated resource rejects arbitrary keyword
            # headers.  Set the same HTTP header on its request object instead.
            request = updater(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=copy.deepcopy(body),
            )
            headers = getattr(request, "headers", None)
            if headers is None:
                raise IfMatchUnavailable("update request has no headers")
            try:
                headers["If-Match"] = etag
            except (TypeError, AttributeError, KeyError) as exc:
                raise IfMatchUnavailable("update request headers are not writable") from exc
        else:
            headers = getattr(request, "headers", None)
            if headers is None:
                # A small injected fake may execute the update immediately and
                # return the response mapping.  The accepted ``headers``
                # keyword is the only attach point in that shape.
                if not isinstance(request, Mapping):
                    raise IfMatchUnavailable("update request has no headers")
            else:
                try:
                    headers["If-Match"] = etag
                except (TypeError, AttributeError, KeyError) as exc:
                    raise IfMatchUnavailable("update request headers are not writable") from exc
        return _execute(request)

    def _result(
        self,
        status: str,
        event_id: str,
        *,
        remote_id: str | None = None,
        etag: str | None = None,
        owned_fields: Mapping[str, Any] | None = None,
        current_fields: Mapping[str, Any] | None = None,
        warnings: list[str] | None = None,
        conflict_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        source_fields = dict(owned_fields or {})
        result = {
            "status": status,
            "action": status,
            "event_id": event_id,
            "remote_id": remote_id,
            "etag": etag,
            "owned_fields": source_fields,
            "last_source_fields": source_fields,
            "source_baseline": source_fields,
            "warnings": list(dict.fromkeys(warnings or [])),
        }
        if current_fields is not None:
            result["current_fields"] = dict(current_fields)
        if conflict_fields:
            result["conflict_fields"] = list(conflict_fields)
        return result

    def _owned(self, remote: Mapping[str, Any], fields: Mapping[str, Any]) -> bool:
        private = (
            remote.get("extendedProperties", {}).get("private", {})
            if isinstance(remote.get("extendedProperties", {}), Mapping)
            else {}
        )
        if private.get("pa_owner") != self.profile_key:
            return False
        if private.get("pa_source_uid") != fields["uid"]:
            return False
        remote_recurrence = private.get("pa_recurrence_id")
        return not remote_recurrence or remote_recurrence == fields["recurrence_id"]

    def _plan_update(
        self,
        current: Mapping[str, Any],
        baseline: Mapping[str, Any],
        desired: Mapping[str, Any],
        supplied: set[str],
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        merged = dict(current)
        changed: list[str] = []
        conflicts: list[str] = []
        for field in _MUTABLE_FIELDS:
            if field not in supplied:
                continue
            base = baseline.get(field, _MISSING)
            now = current.get(field, _MISSING)
            want = desired.get(field, _MISSING)
            source_changed = base is _MISSING or not _values_equal(field, want, base)
            remote_changed = base is not _MISSING and not _values_equal(field, now, base)
            if source_changed and remote_changed and not _values_equal(field, want, now):
                conflicts.append(field)
                continue
            if source_changed and not _values_equal(field, want, now):
                merged[field] = want
                changed.append(field)
        return merged, changed, conflicts

    def sync(
        self,
        event: Mapping[str, Any],
        previous: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        fields, supplied, warnings = _normalise_event(event)
        event_id = stable_event_id(
            self.profile_key,
            self.calendar_id,
            fields["uid"],
            fields["recurrence_id"],
        )
        if _has_attendees(event):
            return self._result(
                "cannot_sync",
                event_id,
                owned_fields=fields,
                warnings=["cannot_sync_attendees"],
            )
        if _has_recurrence(event):
            return self._result(
                "cannot_sync",
                event_id,
                owned_fields=fields,
                warnings=["cannot_sync_recurring"],
            )
        if warnings:
            return self._result(
                "cannot_sync", event_id, owned_fields=fields, warnings=warnings
            )

        state, remote = self._get(event_id)
        remote_id = event_id
        # Older ledger rows may contain an API-generated ID.  We only fall
        # back to it after the deterministic lookup misses, then still enforce
        # the private ownership markers before any write.
        previous_id = previous.get("remote_id") if isinstance(previous, Mapping) else None
        if state == "missing" and previous_id and str(previous_id) != event_id:
            state, remote = self._get(str(previous_id))
            if state == "found":
                remote_id = str(previous_id)

        if state == "error":
            return self._result("error", event_id, warnings=["calendar_get_failed"])

        if state == "missing":
            if fields["status"] == "CANCELLED":
                return self._result(
                    "cancelled_untracked",
                    event_id,
                    warnings=["cancelled_source_without_owned_event"],
                )
            body = _event_body(fields, event_id, self.profile_key)
            try:
                created = _execute(
                    self.service.events().insert(
                        calendarId=self.calendar_id,
                        body=copy.deepcopy(body),
                    )
                )
                if not isinstance(created, Mapping):
                    created = body
                created_fields = _remote_fields(created)
                if not created_fields.get("uid"):
                    created_fields = dict(fields)
                return self._result(
                    "created",
                    event_id,
                    remote_id=str(created.get("id") or event_id),
                    etag=created.get("etag"),
                    owned_fields=fields,
                    current_fields=created_fields,
                    warnings=warnings,
                )
            except Exception:
                # Insert is an uncertain operation.  A deterministic ID makes
                # one read sufficient to recover a successful remote insert.
                recovery_state, recovery = self._get(event_id)
                if recovery_state == "found":
                    if not self._owned(recovery, fields):
                        return self._result(
                            "unowned",
                            event_id,
                            remote_id=event_id,
                            warnings=["insert_id_claimed_by_unowned_event"],
                        )
                    return self._result(
                        "created_recovered",
                        event_id,
                        remote_id=str(recovery.get("id") or event_id),
                        etag=recovery.get("etag"),
                        owned_fields=fields,
                        current_fields=_remote_fields(recovery),
                        warnings=["uncertain_insert_recovered"],
                    )
                return self._result(
                    "retryable_insert",
                    event_id,
                    warnings=["uncertain_insert"],
                )

        assert remote is not None
        if _has_attendees(remote):
            return self._result(
                "cannot_sync",
                event_id,
                remote_id=str(remote.get("id") or remote_id),
                warnings=["cannot_sync_attendees"],
            )
        if _has_recurrence(remote):
            return self._result(
                "cannot_sync",
                event_id,
                remote_id=str(remote.get("id") or remote_id),
                warnings=["cannot_sync_recurring"],
            )
        if not self._owned(remote, fields):
            return self._result(
                "unowned",
                event_id,
                remote_id=str(remote.get("id") or remote_id),
                warnings=["remote_event_not_pa_owned"],
            )

        remote_id = str(remote.get("id") or remote_id)
        baseline = _previous_fields(previous)
        current = _remote_fields(remote)
        missing_baseline = [
            field
            for field in supplied
            if field not in baseline
            and not _values_equal(field, fields.get(field, _MISSING), current.get(field, _MISSING))
        ]
        if missing_baseline:
            return self._result(
                "baseline_required",
                event_id,
                remote_id=remote_id,
                etag=remote.get("etag"),
                current_fields=current,
                warnings=["missing_source_baseline"],
            )
        merged, changed, conflicts = self._plan_update(
            current, baseline, fields, supplied
        )
        if conflicts:
            return self._result(
                "conflict",
                event_id,
                remote_id=remote_id,
                etag=remote.get("etag"),
                owned_fields=baseline,
                current_fields=current,
                conflict_fields=conflicts,
                warnings=["three_way_conflict"],
            )
        if not changed:
            accepted_source = baseline or _accepted_source_fields({}, fields, supplied)
            return self._result(
                "unchanged",
                event_id,
                remote_id=remote_id,
                etag=remote.get("etag"),
                owned_fields=accepted_source,
                current_fields=current,
            )

        if not remote.get("etag"):
            return self._result(
                "retryable_conflict",
                event_id,
                remote_id=remote_id,
                owned_fields=baseline,
                current_fields=current,
                warnings=["missing_etag"],
            )

        merged["uid"] = fields["uid"]
        merged["recurrence_id"] = fields["recurrence_id"]
        # An all-day toggle changes both boundary representations.  Keep the
        # body internally consistent even when only one source field changed.
        if merged.get("all_day"):
            merged["end"] = merged.get("end") or (
                date.fromisoformat(merged["start"]) + timedelta(days=1)
            ).isoformat()
        body = _update_body(
            remote, merged, set(changed), remote_id, self.profile_key
        )
        try:
            updated = _execute(self._update(remote_id, body, str(remote["etag"])))
        except IfMatchUnavailable:
            return self._result(
                "retryable_conflict",
                event_id,
                remote_id=remote_id,
                etag=remote.get("etag"),
                owned_fields=baseline,
                current_fields=current,
                warnings=["if_match_unavailable"],
            )
        except Exception as exc:
            if _status_code(exc) != 412:
                return self._result(
                    "error",
                    event_id,
                    remote_id=remote_id,
                    etag=remote.get("etag"),
                    owned_fields=baseline,
                    current_fields=current,
                    warnings=["calendar_update_failed"],
                )

            # Re-read exactly once, then run the same three-way decision.  A
            # second precondition failure is surfaced to the caller instead of
            # looping over a moving event.
            reread_state, reread = self._get(remote_id)
            if reread_state != "found" or reread is None:
                return self._result(
                    "retryable_conflict",
                    event_id,
                    remote_id=remote_id,
                    warnings=["etag_conflict_reread_failed"],
                )
            if _has_attendees(reread):
                return self._result(
                    "cannot_sync",
                    event_id,
                    remote_id=remote_id,
                    warnings=["cannot_sync_attendees"],
                )
            if _has_recurrence(reread):
                return self._result(
                    "cannot_sync",
                    event_id,
                    remote_id=remote_id,
                    warnings=["cannot_sync_recurring"],
                )
            if not self._owned(reread, fields):
                return self._result(
                    "unowned",
                    event_id,
                    remote_id=remote_id,
                    warnings=["remote_event_not_pa_owned"],
                )
            latest = _remote_fields(reread)
            merged, changed, conflicts = self._plan_update(
                latest, baseline, fields, supplied
            )
            if conflicts:
                return self._result(
                    "conflict",
                    event_id,
                    remote_id=remote_id,
                    etag=reread.get("etag"),
                    owned_fields=baseline,
                    current_fields=latest,
                    conflict_fields=conflicts,
                    warnings=["three_way_conflict_after_412"],
                )
            if not changed:
                accepted_source = baseline or _accepted_source_fields({}, fields, supplied)
                return self._result(
                    "unchanged",
                    event_id,
                    remote_id=remote_id,
                    etag=reread.get("etag"),
                    owned_fields=accepted_source,
                    current_fields=latest,
                )
            if not reread.get("etag"):
                return self._result(
                    "retryable_conflict",
                    event_id,
                    remote_id=remote_id,
                    owned_fields=baseline,
                    current_fields=latest,
                    warnings=["missing_etag"],
                )
            merged["uid"] = fields["uid"]
            merged["recurrence_id"] = fields["recurrence_id"]
            if merged.get("all_day"):
                merged["end"] = merged.get("end") or (
                    date.fromisoformat(merged["start"]) + timedelta(days=1)
                ).isoformat()
            retry_body = _update_body(
                reread, merged, set(changed), remote_id, self.profile_key
            )
            body = retry_body
            try:
                updated = _execute(
                    self._update(remote_id, retry_body, str(reread["etag"]))
                )
            except IfMatchUnavailable:
                return self._result(
                    "retryable_conflict",
                    event_id,
                    remote_id=remote_id,
                    etag=reread.get("etag"),
                    owned_fields=baseline,
                    current_fields=latest,
                    warnings=["if_match_unavailable"],
                )
            except Exception as retry_exc:
                if _status_code(retry_exc) == 412:
                    return self._result(
                        "retryable_conflict",
                        event_id,
                        remote_id=remote_id,
                        etag=reread.get("etag"),
                        owned_fields=baseline,
                        current_fields=latest,
                        warnings=["repeated_etag_conflict"],
                    )
                return self._result(
                    "error",
                    event_id,
                    remote_id=remote_id,
                    etag=reread.get("etag"),
                    owned_fields=baseline,
                    current_fields=latest,
                    warnings=["calendar_update_failed"],
                )

        if not isinstance(updated, Mapping):
            updated = dict(body)
        final_fields = _remote_fields(updated)
        if not final_fields.get("uid"):
            final_fields = dict(merged)
        accepted_source = _accepted_source_fields(baseline, fields, supplied)
        return self._result(
            "updated",
            event_id,
            remote_id=str(updated.get("id") or remote_id),
            etag=updated.get("etag"),
            owned_fields=accepted_source,
            current_fields=final_fields,
        )


def build_calendar_service(profile_root: str | Path, *, access: str = "write") -> Any:
    """Build Calendar v3 using an existing profile OAuth token.

    The factory reads only token metadata needed to verify the requested
    Calendar access. It never starts consent or creates a second OAuth flow.
    """

    token_path = Path(profile_root) / "google_token.json"
    try:
        payload = json.loads(token_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CalendarAuthError("existing Google profile token is unavailable") from exc
    if access not in {"read", "write"}:
        raise ValueError("calendar service access must be read or write")
    scopes = payload.get("scopes") or payload.get("required_scopes")
    if isinstance(scopes, str):
        scopes = scopes.split()
    accepted_scopes = CALENDAR_READ_SCOPES if access == "read" else CALENDAR_WRITE_SCOPES
    if not isinstance(scopes, list) or not accepted_scopes.intersection(scopes):
        raise CalendarAuthError(f"existing Google token lacks calendar {access} scope")

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise CalendarAuthError("Google API libraries are unavailable") from exc

    try:
        credentials = Credentials.from_authorized_user_file(
            str(token_path), list(scopes)
        )
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials.valid:
            raise CalendarAuthError("existing Google profile token is invalid")
        return build("calendar", "v3", credentials=credentials)
    except CalendarAuthError:
        raise
    except Exception as exc:
        raise CalendarAuthError("existing Google profile token could not be loaded") from exc


# Explicit aliases keep the integration seam easy to discover without adding
# another implementation or auth path.
calendar_service_from_profile = build_calendar_service
oauth_calendar_service = build_calendar_service


__all__ = [
    "CALENDAR_READ_SCOPES",
    "CALENDAR_WRITE_SCOPES",
    "CalendarAuthError",
    "CalendarSync",
    "IfMatchUnavailable",
    "build_calendar_service",
    "calendar_service_from_profile",
    "oauth_calendar_service",
    "stable_event_id",
]
