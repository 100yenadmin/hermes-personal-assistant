"""Regression coverage for required release archive contents."""
import hashlib
import io
import json
import tarfile
import unittest

from scripts.verify_release_assets import verify


def _write_member(archive, name, content=b"fixture"):
    info = tarfile.TarInfo(name)
    info.size = len(content)
    archive.addfile(info, io.BytesIO(content))


class ReleaseAssetVerificationTests(unittest.TestCase):
    def test_verifier_rejects_archive_without_action_gateway_policy(self):
        with self.subTest("runtime policy is a required archive member"):
            from tempfile import TemporaryDirectory
            from pathlib import Path

            with TemporaryDirectory() as temporary:
                directory = Path(temporary)
                version = "9.9.9-test"
                stem = f"travel-agent-skills-{version}"
                archive_path = directory / f"{stem}.tgz"
                source_sha = "a" * 40
                internal = json.dumps({
                    "source_commit": source_sha,
                    "version": version,
                }).encode()
                with tarfile.open(archive_path, "w:gz") as archive:
                    _write_member(archive, f"{stem}/__init__.py")
                    _write_member(archive, f"{stem}/after-install.md")
                    _write_member(
                        archive,
                        f"{stem}/plugin.yaml",
                        b"provides_hooks:\n  - pre_tool_call\n",
                    )
                    _write_member(
                        archive,
                        f"{stem}/.travel-agent-skills-release.json",
                        internal,
                    )

                digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
                (directory / f"{stem}.tgz.sha256").write_text(
                    f"{digest}  {archive_path.name}\n", encoding="utf-8"
                )
                (directory / f"{stem}.manifest.json").write_text(
                    json.dumps({
                        "version": version,
                        "native_id": "personal-assistant",
                        "source_sha": source_sha,
                        "artifact": {
                            "name": archive_path.name,
                            "sha256": digest,
                        },
                    }),
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "config/pa-action-gateway-policy.example.json",
                ):
                    verify(directory, version)


if __name__ == "__main__":
    unittest.main()
