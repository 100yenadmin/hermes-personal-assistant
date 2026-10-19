"""Bind once to the intended Google account/calendar; persist each sync receipt."""
from collections.abc import Mapping

from .calendar import CalendarSync, build_calendar_service
from .state import now


def bind(ledger, calendar_id, expected_account, *, service=None):
    if not calendar_id or calendar_id == "primary" or not expected_account:
        raise ValueError("explicit destination calendar ID and expected account required")
    service = service or build_calendar_service(ledger.root)
    primary = service.calendars().get(calendarId="primary").execute()
    if primary.get("id", "").casefold() != expected_account.casefold():
        raise ValueError("Google account does not match intended owner")
    destination = service.calendarList().get(calendarId=calendar_id).execute()
    if destination.get("accessRole") != "owner":
        raise ValueError("destination calendar must be owned by the bound account")
    # Account identity belongs to private profile state, never shared trip exports.
    return ledger.put("action", "pa:calendar-binding", {"calendar_id": calendar_id,
                      "expected_account": expected_account, "verified_at": now()},
                      action_type="calendar_binding", provider="google", status="bound")


def _bound_adapter(ledger, service=None):
    binding = ledger.get("action", "pa:calendar-binding")
    if not binding or binding["status"] != "bound":
        raise ValueError("bind the explicitly authorized calendar first")
    settings = binding["fields"]
    service = service or build_calendar_service(ledger.root)
    primary = service.calendars().get(calendarId="primary").execute()
    if primary.get("id", "").casefold() != settings["expected_account"].casefold():
        raise ValueError("Google account changed; stop and rebind")
    destination = service.calendarList().get(calendarId=settings["calendar_id"]).execute()
    if destination.get("accessRole") != "owner":
        raise ValueError("destination calendar is no longer owned by the bound account")
    return CalendarSync(service, settings["calendar_id"], str(ledger.root)), settings


def _sync_action(ledger, action_id, adapter):
    action = ledger.get("action", action_id)
    if not action:
        raise ValueError("action not found")
    if action.get("trip_id"):
        raise ValueError("trip-linked actions must sync through trip_id")
    if action.get("action_type") in {"transaction", "calendar_binding", "automation_rule"}:
        raise ValueError("action type cannot be synchronized to Calendar")
    fields = action.get("fields") if isinstance(action.get("fields"), Mapping) else {}
    source = fields.get("calendar_event")
    if not isinstance(source, Mapping):
        raise ValueError("action fields must include a calendar_event object")
    event = dict(source)
    supplied_uid = event.get("uid")
    if supplied_uid not in {None, "", action_id}:
        raise ValueError("calendar_event.uid must be omitted or match action_id")
    event["uid"] = action_id
    previous = fields.get("calendar_mapping")
    ledger.put("action", action_id, {"calendar_intended_at": now()})
    receipt = adapter.sync(event, previous if isinstance(previous, Mapping) else None)
    update = {"calendar_last_attempt": receipt, "calendar_verified_at": now()}
    if receipt["status"] in {"created", "created_recovered", "updated", "unchanged"}:
        update["calendar_mapping"] = receipt
    ledger.put("action", action_id, update)
    return {"action_id": action_id, "status": receipt["status"], "warnings": receipt.get("warnings", [])}


def sync_trip(ledger, trip_id=None, action_id=None, *, service=None):
    """Sync exactly one trip or one existing non-trip action."""
    if bool(trip_id) == bool(action_id):
        raise ValueError("provide exactly one of trip_id or action_id")
    adapter, settings = _bound_adapter(ledger, service)
    if action_id:
        return _sync_action(ledger, action_id, adapter)
    trip = ledger.get("trip", trip_id)
    if not trip:
        raise ValueError("trip not found")
    results = []
    for event in trip["fields"]["events"]:
        identity = ledger.action_id(event["source_record_id"], "calendar_sync", settings["calendar_id"])
        previous = ledger.get("action", identity)
        if event.get("source_missing"):
            results.append({"action_id": identity, "status": "source_gap"})
            continue
        ledger.put("action", identity, {"source_record_id": event["source_record_id"], "intended_at": now()}, action_type="calendar_sync", trip_id=trip_id, provider="google")
        receipt = adapter.sync(event, (previous or {}).get("fields", {}).get("mapping"))
        # Retain the accepted baseline on errors/conflicts and uncertain outcomes.
        data = {"last_attempt": receipt, "verified_at": now()}
        if receipt["status"] in {"created", "created_recovered", "updated", "unchanged"}:
            data["mapping"] = receipt
        ledger.put("action", identity, data, status=receipt["status"])
        results.append({"action_id": identity, "status": receipt["status"], "warnings": receipt.get("warnings", [])})
    return {"trip_id": trip_id, "events": results}
