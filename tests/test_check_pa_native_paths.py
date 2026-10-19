import argparse
from pathlib import Path
import tempfile
import unittest

from scripts.native_paths import resolve_cli_paths


class NativePathResolutionTests(unittest.TestCase):
    def test_relative_cli_paths_are_resolved_before_working_directory_changes(self):
        with tempfile.TemporaryDirectory() as root:
            invocation_dir = Path(root) / "invocation"
            invocation_dir.mkdir()
            args = argparse.Namespace(
                hermes="hermes",
                ics="fixtures/trip.ics",
                guide="fixtures/guide.md",
                receipt="receipts/native.json",
                archive="dist/plugin.tar.gz",
            )

            resolved = resolve_cli_paths(args, cwd=invocation_dir)

            for name in ("hermes", "ics", "guide", "receipt", "archive"):
                self.assertTrue(Path(getattr(resolved, name)).is_absolute())
            self.assertEqual(Path(resolved.receipt), invocation_dir / "receipts/native.json")

            unrelated_dir = Path(root) / "temporary-profile"
            unrelated_dir.mkdir()
            self.assertEqual(Path(resolved.ics), invocation_dir / "fixtures/trip.ics")
            self.assertFalse(Path(resolved.receipt).is_relative_to(unrelated_dir))

    def test_optional_and_absolute_paths_keep_their_meaning(self):
        absolute = Path("/tmp/native-check/receipt.json")
        args = argparse.Namespace(
            hermes="/opt/hermes",
            ics="/tmp/trip.ics",
            guide=None,
            receipt=str(absolute),
            archive=None,
        )

        resolved = resolve_cli_paths(args, cwd=Path("/elsewhere"))

        self.assertEqual(Path(resolved.receipt), absolute)
        self.assertIsNone(resolved.guide)
        self.assertIsNone(resolved.archive)


if __name__ == "__main__":
    unittest.main()
