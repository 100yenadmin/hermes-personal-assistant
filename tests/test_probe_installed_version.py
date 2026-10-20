import json
from pathlib import Path
import subprocess
from unittest import mock

import pytest

from scripts import check_release, probe_installed_version


def make_native_profile(tmp_path):
    home = tmp_path / "home"
    hermes = tmp_path / "hermes"
    plugin = hermes / "plugins" / "personal-assistant"
    plugin.mkdir(parents=True)
    (plugin / ".git").mkdir()
    (plugin / "plugin.yaml").write_text(
        "name: personal-assistant\nversion: 0.3.0\npython_dependencies:\n  - icalendar==6.3.1\n"
    )
    for skill in probe_installed_version.REQUIRED_SKILLS:
        path = plugin / "skills" / skill
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(f"# {skill}\n")
    (hermes / "config.yaml").write_text("plugins:\n  enabled: [personal-assistant]\n")
    (hermes / "plugins" / ".install-metadata.json").write_text(json.dumps({
        "personal-assistant": {
            "pinned": True,
            "revision": "a" * 40,
            "source": "https://example.invalid/skill-personal-assistant.git",
        }
    }))
    return home, hermes


def test_native_profile_precedes_legacy_and_separates_runtime_evidence(tmp_path):
    home, hermes = make_native_profile(tmp_path)
    legacy = home / ".openclaw" / "workspace" / "packages" / "travel-agent-skills"
    legacy.mkdir(parents=True)
    (legacy / "openclaw.plugin.json").write_text(json.dumps({"id": "travel-agent-skills", "version": "9"}))
    with mock.patch.object(probe_installed_version.importlib.metadata, "version", return_value="6.3.1"):
        result = probe_installed_version.probe(home, hermes)
    assert result["ok"] is True
    assert result["source_kind"] == "native_git"
    assert result["observed_id"] == "personal-assistant"
    assert result["observed_commit"] == "a" * 40
    assert result["installed"] is True and result["enabled"] is True
    assert result["loaded"] is None and result["exercised"] is None


def test_missing_declared_dependency_is_truthful_failure(tmp_path):
    home, hermes = make_native_profile(tmp_path)
    with mock.patch.object(
        probe_installed_version.importlib.metadata,
        "version",
        side_effect=probe_installed_version.importlib.metadata.PackageNotFoundError,
    ):
        result = probe_installed_version.probe(home, hermes)
    assert result["install_ok"] is True
    assert result["dependencies_ok"] is False
    assert result["python_dependencies_missing"] == ["icalendar==6.3.1"]
    assert result["ok"] is False


def test_malformed_profile_yaml_returns_unknown_activation_without_traceback(tmp_path):
    home, hermes = make_native_profile(tmp_path)
    (hermes / "config.yaml").write_text("plugins: [unterminated\n")
    with mock.patch.object(probe_installed_version.importlib.metadata, "version", return_value="6.3.1"):
        result = probe_installed_version.probe(home, hermes)
    assert result["installed"] is True
    assert result["enabled"] is None


def make_git_profile(tmp_path):
    home, hermes = make_native_profile(tmp_path)
    plugin = hermes / "plugins" / "personal-assistant"
    (plugin / "plugin.yaml").write_text("name: personal-assistant\nversion: 0.3.0\n")
    git = ["git", "-C", str(plugin)]
    subprocess.run([*git, "init", "-q"], check=True, capture_output=True)
    subprocess.run([*git, "add", "."], check=True, capture_output=True)
    subprocess.run([
        *git, "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "synthetic fixture",
    ], check=True, capture_output=True)
    head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    metadata = hermes / "plugins" / ".install-metadata.json"
    data = json.loads(metadata.read_text())
    data["personal-assistant"]["revision"] = head
    metadata.write_text(json.dumps(data))
    return home, hermes, plugin, head


def test_clean_git_checkout_retains_current_identity(tmp_path):
    home, hermes, _, head = make_git_profile(tmp_path)
    result = probe_installed_version.probe(home, hermes)
    assert result["ok"] is True and result["install_ok"] is True
    assert result["observed_commit"] == head
    assert result["checkout_commit"] == head
    assert result["checkout_dirty"] is False
    assert result["metadata_matches_checkout"] is True
    assert result["source_identity_known"] is True


def test_git_checkout_metadata_mismatch_is_not_current(tmp_path):
    home, hermes, _, head = make_git_profile(tmp_path)
    metadata = hermes / "plugins" / ".install-metadata.json"
    data = json.loads(metadata.read_text())
    data["personal-assistant"]["revision"] = "b" * 40
    metadata.write_text(json.dumps(data))
    result = probe_installed_version.probe(home, hermes)
    assert result["checkout_commit"] == head
    assert result["metadata_matches_checkout"] is False
    assert result["source_identity_known"] is False
    assert result["install_ok"] is False and result["ok"] is False
    assert result["source_identity_reason"] == "source_mismatch"


def test_edited_git_checkout_is_not_current(tmp_path):
    home, hermes, plugin, head = make_git_profile(tmp_path)
    with (plugin / "plugin.yaml").open("a") as output:
        output.write("# synthetic edit\n")
    result = probe_installed_version.probe(home, hermes)
    assert result["checkout_commit"] == head
    assert result["checkout_dirty"] is True
    assert result["metadata_matches_checkout"] is True
    assert result["source_identity_known"] is False
    assert result["install_ok"] is False and result["ok"] is False
    assert result["source_identity_reason"] == "local_edits"


def test_untracked_local_config_does_not_make_checkout_dirty(tmp_path):
    # PA keeps its local config and state (clients.json, daily_ops.*, location.json)
    # untracked inside the installed package; that is not an edit to the release.
    home, hermes, plugin, head = make_git_profile(tmp_path)
    for name in ("clients.json", "daily_ops.config.json", "daily_ops.state.json", "location.json"):
        (plugin / name).write_text("{}\n")
    result = probe_installed_version.probe(home, hermes)
    assert result["checkout_commit"] == head
    assert result["checkout_dirty"] is False
    assert result["source_identity_reason"] is None
    assert result["source_identity_known"] is True


def test_git_unavailable_keeps_metadata_identity(tmp_path):
    home, hermes = make_native_profile(tmp_path)
    with mock.patch("subprocess.run", side_effect=FileNotFoundError):
        result = probe_installed_version.probe(home, hermes)
    assert result["checkout_commit"] is None
    assert result["checkout_dirty"] is None
    assert result["metadata_matches_checkout"] is None
    # An unreadable checkout keeps the install-metadata answer and says why.
    assert result["source_identity_known"] is True
    assert result["source_identity_reason"] == "checkout_unavailable"


@pytest.mark.parametrize("value", ["true", "false", "42", "'private-sentinel'", "{private-sentinel: true}"])
def test_non_list_dependencies_return_sanitized_invalid_json(tmp_path, value):
    home, hermes = make_native_profile(tmp_path)
    plugin = hermes / "plugins" / "personal-assistant"
    (plugin / "plugin.yaml").write_text(
        f"name: personal-assistant\nversion: 0.3.0\npython_dependencies: {value}\n"
    )
    result = probe_installed_version.probe(home, hermes)
    assert result["ok"] is False and result["install_ok"] is False
    assert "python_dependencies" in result["invalid_reason"]
    assert "private-sentinel" not in json.dumps(result)


def make_legacy_profile(tmp_path):
    home = tmp_path / "home"
    hermes = tmp_path / "hermes"
    legacy = home / ".openclaw" / "workspace" / "packages" / "travel-agent-skills"
    legacy.mkdir(parents=True)
    (legacy / "openclaw.plugin.json").write_text(json.dumps({
        "id": "travel-agent-skills", "version": "0.3.0",
    }))
    for skill in probe_installed_version.REQUIRED_SKILLS:
        path = legacy / "skills" / skill
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(f"# {skill}\n")
    return home, hermes


def test_legacy_only_requires_native_migration(tmp_path):
    home, hermes = make_legacy_profile(tmp_path)
    result = probe_installed_version.probe(home, hermes)
    assert result["source_kind"] == "legacy_openclaw"
    assert result["migration_required"] is True
    assert not (hermes / "plugins" / "personal-assistant").exists()


def test_native_archive_identity_is_unchanged(tmp_path):
    home, hermes = make_native_profile(tmp_path)
    plugin = hermes / "plugins" / "personal-assistant"
    (plugin / ".git").rmdir()
    (plugin / ".travel-agent-skills-release.json").write_text(json.dumps({"source_commit": "c" * 40}))
    with mock.patch.object(probe_installed_version.importlib.metadata, "version", return_value="6.3.1"):
        result = probe_installed_version.probe(home, hermes)
    assert result["ok"] is True and result["install_ok"] is True
    assert result["source_kind"] == "native_archive"
    assert result["observed_commit"] == "c" * 40
    assert result["source_identity_known"] is True


@pytest.mark.parametrize("case, status", [
    ("clean", "up_to_date"), ("mismatch", "source_mismatch"),
    ("dirty", "local_edits"), ("legacy", "migration_required"),
])
@pytest.mark.parametrize("has_release", [False, True])
def test_release_checker_uses_actual_install_diagnostics(tmp_path, case, status, has_release):
    if case == "legacy":
        home, hermes = make_legacy_profile(tmp_path)
        head = "a" * 40
    else:
        home, hermes, plugin, head = make_git_profile(tmp_path)
        if case == "mismatch":
            metadata = hermes / "plugins" / ".install-metadata.json"
            data = json.loads(metadata.read_text())
            data["personal-assistant"]["revision"] = "b" * 40
            metadata.write_text(json.dumps(data))
            head = "b" * 40  # Release matches metadata, but not the actual checkout.
        elif case == "dirty":
            (plugin / "plugin.yaml").write_text((plugin / "plugin.yaml").read_text() + "# edit\n")
    selected = {"tagName": "v0.3.0"} if has_release else None
    with mock.patch.object(check_release, "select_release", return_value=selected), \
         mock.patch.object(check_release, "resolve_tag_commit", return_value=head):
        result = check_release.check_release(
            gh="unused", repository="owner/repo", channel="pilot",
            system_home=home, hermes_home=hermes,
        )
    expected = "no_release_on_channel" if case == "clean" and not has_release else status
    assert result["status"] == expected
    assert result.get("operator_archive_path") is None
    if case == "legacy" and has_release:
        assert f"hermes plugins install owner/repo --ref {head} --no-enable" in result["proposed_command"]
        assert "--archive-dir" not in result["proposed_command"]
    else:
        assert result["proposed_command"] is None
