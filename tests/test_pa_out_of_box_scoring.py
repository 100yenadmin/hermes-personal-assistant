import tempfile
import unittest
from pathlib import Path

from evals.pa_out_of_box_cases import ICS, GUIDE, artifact_checks


class ExportLocationTests(unittest.TestCase):
    def test_replaced_unsubmitted_quote_is_not_a_duplicate_booking(self):
        old = {"offer_id": "flight-booking", "submit_count": 0, "duplicate_count": 0,
               "effect_count": 0, "receipt_id": None}
        booked = {**old, "submit_count": 1, "effect_count": 1, "receipt_id": "fixture-receipt"}
        with tempfile.TemporaryDirectory() as directory:
            checks = artifact_checks(Path(directory), "R2", "change", {"transactions": [old, booked]})
            self.assertTrue(all(checks.values()))
            checks = artifact_checks(Path(directory), "R2", "change", {"transactions": [booked, booked]})
            self.assertFalse(checks["correct_single_provider_action"])
            self.assertFalse(checks["no_duplicate_attempt"])

    def test_export_subfolder_is_allowed_but_duplicate_calendars_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            output = home / "exports" / "trip"
            output.mkdir(parents=True)
            (output / "Trip.ics").write_text(ICS)
            (output / "Reference.md").write_text(GUIDE + "\nOfficial time: 13:00\n")
            self.assertTrue(all(artifact_checks(home, "R1", "ordinary", {}).values()))
            (home / "exports" / "duplicate.ics").write_text(ICS)
            checks = artifact_checks(home, "R1", "ordinary", {})
            self.assertFalse(checks["calendar_exists"])
            self.assertFalse(all(checks.values()))


if __name__ == "__main__":
    unittest.main()
