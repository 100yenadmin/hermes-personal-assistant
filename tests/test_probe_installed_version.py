import json
from pathlib import Path
from unittest import mock

from scripts import probe_installed_version


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
