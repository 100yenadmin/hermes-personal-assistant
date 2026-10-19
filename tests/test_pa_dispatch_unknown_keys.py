import tempfile
from unittest.mock import ANY, patch

from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger


def test_action_upsert_drops_schema_valid_limit_and_writes_action():
    with tempfile.TemporaryDirectory() as root:
        result = dispatch(root, {
            "operation": "action_upsert",
            "data": {
                "action_id": "synthetic-action",
                "fields": {"note": "synthetic"},
                "status": "completed",
                "limit": 1,
            },
        })

        assert result["action_id"] == "synthetic-action"
        stored = Ledger(root).get("action", "synthetic-action")
        assert stored["fields"] == {"note": "synthetic"}
        assert stored["status"] == "completed"


def test_calendar_sync_drops_stray_key_and_forwards_accepted_keys():
    with tempfile.TemporaryDirectory() as root:
        with patch(
            "personal_assistant.calendar_workflow.sync_trip",
            autospec=True,
            return_value={"synced": True},
        ) as sync_trip:
            result = dispatch(root, {
                "operation": "calendar_sync",
                "data": {"trip_id": "synthetic-trip", "action_id": "synthetic-action", "limit": 2},
            })

        assert result == {"synced": True}
        sync_trip.assert_called_once_with(
            ANY,
            trip_id="synthetic-trip",
            action_id="synthetic-action",
        )


def test_trip_export_drops_stray_key_and_forwards_accepted_keys():
    with tempfile.TemporaryDirectory() as root:
        output_dir = f"{root}/export"
        with patch(
            "personal_assistant.trips.export_trip",
            autospec=True,
            return_value={"calendar": "synthetic.ics"},
        ) as export_trip:
            result = dispatch(root, {
                "operation": "export",
                "data": {
                    "trip_id": "synthetic-trip",
                    "output_dir": output_dir,
                    "overwrite": True,
                    "limit": 3,
                },
            })

        assert result == {"calendar": "synthetic.ics"}
        export_trip.assert_called_once_with(
            ANY,
            trip_id="synthetic-trip",
            output_dir=output_dir,
            overwrite=True,
        )
