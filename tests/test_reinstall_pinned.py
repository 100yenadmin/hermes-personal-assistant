import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from unittest import mock

import pytest

from scripts import reinstall_pinned
from scripts.probe_installed_version import probe


def make_install(tmp_path):
    home = tmp_path / "hermes"
    target = home / "plugins" / "personal-assistant"
    target.mkdir(parents=True)
    (home / "config.yaml").write_text(
        "plugins:\n  enabled: [personal-assistant]\n  disabled: []\n"
    )
    (home / "plugins" / ".install-metadata.json").write_text(json.dumps({
        "personal-assistant": {
            "source": "example.invalid/repository", "revision": "1" * 40, "pinned": True,
        }
    }))
    (target / "plugin.yaml").write_text("name: personal-assistant\nversion: 0.3.0\n")
    (target / "old-source.txt").write_text("old revision\n")
    for index, name in enumerate(reinstall_pinned.CONFIG_NAMES):
        (target / name).write_text(json.dumps({"synthetic": index}) + "\n")
    return home, target


def install_replacement(target, revision):
    shutil.rmtree(target)
    target.mkdir()
    (target / "plugin.yaml").write_text("name: personal-assistant\nversion: 0.3.0\n")
    (target / "new-source.txt").write_text(f"new revision {revision}\n")
    metadata = target.parent / ".install-metadata.json"
    metadata.write_text(json.dumps({"personal-assistant": {
        "source": "example.invalid/repository", "revision": revision, "pinned": True,
    }}))


def test_reinstall_restores_only_allowlisted_local_config(tmp_path):
    home, target = make_install(tmp_path)
    before = {name: (target / name).read_bytes() for name in reinstall_pinned.CONFIG_NAMES}
    (target / "not-preserved.txt").write_text("old\n")

    def fake_hermes(command, **kwargs):
        assert command[-1] == "--no-enable"
        install_replacement(target, "a" * 40)
        return subprocess.CompletedProcess(command, 0, "installed\n", "")

    with mock.patch.object(reinstall_pinned.subprocess, "run", side_effect=fake_hermes):
        result = reinstall_pinned.reinstall(
            "example.invalid/repository", "a" * 40, "hermes", home
        )

    assert result["preserved_config"] == sorted(reinstall_pinned.CONFIG_NAMES)
    assert result["activation_changed"] is False
    assert result["ledger_copied"] is False
    assert not (target / "not-preserved.txt").exists()
    assert (target / "new-source.txt").is_file()
    assert {name: (target / name).read_bytes() for name in reinstall_pinned.CONFIG_NAMES} == before
    snapshot = home / "plugin-backups" / "personal-assistant" / result["rollback_snapshot"]
    assert (snapshot / "package" / "old-source.txt").is_file()
    assert not any((snapshot / "package" / name).exists() for name in reinstall_pinned.CONFIG_NAMES)
    assert result["preserved_activation"] == {"enabled": True, "disabled": False}


def test_reinstall_requires_full_sha_and_regular_config(tmp_path):
    home, target = make_install(tmp_path)
    with pytest.raises(ValueError, match="40-character"):
        reinstall_pinned.reinstall("example.invalid/repository", "main", "hermes", home)
    (target / "clients.json").unlink()
    (target / "clients.json").symlink_to(target / "location.json")
    with pytest.raises(ValueError, match="non-regular"):
        reinstall_pinned.reinstall("example.invalid/repository", "b" * 40, "hermes", home)


def test_failed_native_reinstall_keeps_backup_for_recovery(tmp_path):
    home, _target = make_install(tmp_path)
    failed = subprocess.CompletedProcess(["hermes"], 1, "", "failed")
    with mock.patch.object(reinstall_pinned.subprocess, "run", return_value=failed):
        with pytest.raises(RuntimeError, match="snapshot retained"):
            reinstall_pinned.reinstall("example.invalid/repository", "c" * 40, "hermes", home)
    backup = next((home / "plugin-backups" / "personal-assistant").iterdir())
    assert (backup / "package" / "old-source.txt").is_file()


def test_successful_native_replace_with_restore_failure_retains_configuration_recovery(tmp_path):
    home, target = make_install(tmp_path)
    before = {name: (target / name).read_bytes() for name in reinstall_pinned.CONFIG_NAMES}

    def fake_hermes(command, **kwargs):
        install_replacement(target, "c" * 40)
        return subprocess.CompletedProcess(command, 0, "installed\n", "")

    with mock.patch.object(reinstall_pinned.subprocess, "run", side_effect=fake_hermes), \
         mock.patch.object(reinstall_pinned, "_restore_config", side_effect=OSError("synthetic restore failure")):
        with pytest.raises(OSError, match="synthetic restore failure"):
            reinstall_pinned.reinstall("example.invalid/repository", "c" * 40, "hermes", home)

    recovery = next(home.glob(".pa-config-recovery-*"))
    assert recovery.stat().st_mode & 0o777 == 0o700
    assert {
        name: (recovery / "config" / name).read_bytes()
        for name in reinstall_pinned.CONFIG_NAMES
    } == before
    assert (target / "new-source.txt").is_file()
    snapshot = next((home / "plugin-backups" / "personal-assistant").iterdir())
    assert (snapshot / "package" / "old-source.txt").is_file()


def test_rollback_restores_prior_package_but_preserves_accepted_state_and_can_repeat(tmp_path):
    home, target = make_install(tmp_path)
    state = home / "state" / "travel-ledger"
    state.mkdir(parents=True)
    ledger = state / "travel.sqlite"
    ledger.write_bytes(b"accepted-before")
    sessions = home / "sessions.json"
    sessions.write_text("accepted session state\n")

    def fake_hermes(command, **kwargs):
        install_replacement(target, "d" * 40)
        return subprocess.CompletedProcess(command, 0, "installed\n", "")

    with mock.patch.object(reinstall_pinned.subprocess, "run", side_effect=fake_hermes):
        replaced = reinstall_pinned.reinstall(
            "example.invalid/repository", "d" * 40, "hermes", home
        )
    (target / "clients.json").write_text('{"accepted": "new"}\n')
    ledger.write_bytes(b"accepted-after")
    sessions.write_text("accepted session state after replacement\n")
    result = reinstall_pinned.rollback(replaced["rollback_snapshot"], home)

    assert (target / "old-source.txt").is_file()
    assert not (target / "new-source.txt").exists()
    assert (target / "clients.json").read_text() == '{"accepted": "new"}\n'
    assert ledger.read_bytes() == b"accepted-after"
    assert sessions.read_text() == "accepted session state after replacement\n"
    assert result["activation_preserved"] == {"enabled": True, "disabled": False}
    metadata = json.loads((home / "plugins" / ".install-metadata.json").read_text())
    assert metadata["personal-assistant"]["revision"] == "1" * 40

    def fake_repeat(command, **kwargs):
        install_replacement(target, "1" * 40)
        return subprocess.CompletedProcess(command, 0, "installed\n", "")

    with mock.patch.object(reinstall_pinned.subprocess, "run", side_effect=fake_repeat):
        repeated = reinstall_pinned.reinstall(
            "example.invalid/repository", "1" * 40, "hermes", home
        )
    assert repeated["revision"] == "1" * 40
    assert ledger.read_bytes() == b"accepted-after"
    assert (target / "clients.json").read_text() == '{"accepted": "new"}\n'


def write_archive_assets(directory, version="0.3.0", source_sha="e" * 40):
    root = directory / f"travel-agent-skills-{version}"
    root.mkdir(parents=True)
    (root / "__init__.py").write_text("\n")
    (root / "after-install.md").write_text("Synthetic handoff\n")
    (root / "plugin.yaml").write_text(f"name: personal-assistant\nversion: {version}\n")
    (root / ".travel-agent-skills-release.json").write_text(json.dumps({
        "version": version, "source_commit": source_sha,
    }))
    archive = directory / f"travel-agent-skills-{version}.tgz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(root, arcname=root.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (directory / f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n")
    (directory / f"travel-agent-skills-{version}.manifest.json").write_text(json.dumps({
        "version": version,
        "native_id": "personal-assistant",
        "source_sha": source_sha,
        "artifact": {"name": archive.name, "sha256": digest},
    }))


def test_archive_replacement_uses_canonical_path_and_probe_identity(tmp_path):
    home, target = make_install(tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    write_archive_assets(assets)
    before = {name: (target / name).read_bytes() for name in reinstall_pinned.CONFIG_NAMES}

    result = reinstall_pinned.replace_archive(assets, "0.3.0", home)

    assert result["package_path"] == str(target)
    assert {name: (target / name).read_bytes() for name in reinstall_pinned.CONFIG_NAMES} == before
    assert "personal-assistant" not in json.loads(
        (home / "plugins" / ".install-metadata.json").read_text()
    )
    status = probe(tmp_path / "system-home", home)
    assert status["source_kind"] == "native_archive"
    assert status["observed_commit"] == "e" * 40
    assert status["package_path"] == str(target)
