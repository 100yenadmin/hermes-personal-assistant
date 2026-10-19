import pytest
from icalendar import Calendar

from personal_assistant.state import Ledger
from personal_assistant.trips import import_trip, export_trip
from tests.test_pa_core import ICS


def test_reference_keeps_the_official_event_link(tmp_path):
    ledger = Ledger(tmp_path)
    calendar = Calendar.from_ical(ICS)
    calendar.walk("VEVENT")[0]["URL"] = "https://example.invalid/events/orientation"
    import_trip(ledger, "trip", calendar.to_ical())
    output = tmp_path / "exports"
    export_trip(ledger, "trip", output)
    for name in ("Trip.ics", "Trip-Reference.md"):
        assert "https://example.invalid/events/orientation" in (output / name).read_text()


def test_refresh_reuses_outputs_and_preserves_user_edits(tmp_path):
    ledger = Ledger(tmp_path)
    import_trip(ledger, "trip", ICS)
    output = tmp_path / "exports"
    export_trip(ledger, "trip", output)
    with pytest.raises(ValueError, match="fresh"):
        export_trip(ledger, "trip", output)
    import_trip(ledger, "trip", ICS.replace(b"130000", b"150000").replace(b"140000", b"160000"))
    export_trip(Ledger(tmp_path), "trip", output, overwrite=True)
    assert Calendar.from_ical((output / "Trip.ics").read_bytes()).walk("VEVENT")[0].decoded("DTSTART").hour == 15
    assert len(ledger.list("action")) == 1
    assert len(list(output.iterdir())) == 2
    reference = output / "Trip-Reference.md"
    reference.write_text("My own additions")
    with pytest.raises(ValueError, match="user-modified"):
        export_trip(ledger, "trip", output, overwrite=True)
    assert reference.read_text() == "My own additions"


def test_refresh_refuses_unowned_files(tmp_path):
    ledger = Ledger(tmp_path)
    import_trip(ledger, "trip", ICS)
    output = tmp_path / "exports"
    output.mkdir()
    (output / "Trip.ics").write_bytes(ICS)
    with pytest.raises(ValueError, match="unrelated"):
        export_trip(ledger, "trip", output, overwrite=True)
    assert (output / "Trip.ics").read_bytes() == ICS
