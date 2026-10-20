from pathlib import Path
from unittest import mock

from scripts import check_release


def installed(source_kind="native_git", version="1.0.0-rc1", commit="a" * 40):
    return {
        "installed": True,
        "install_ok": True,
        "dependencies_ok": True,
        "source_kind": source_kind,
        "observed_version": version,
        "observed_commit": commit,
        "package_path": "/synthetic/hermes/plugins/personal-assistant",
    }


def release(version="0.4.0-rc.1", published="2026-09-14T00:00:00Z"):
    return {
        "tagName": f"v{version}",
        "name": f"Personal Assistant v{version}",
        "publishedAt": published,
        "isPrerelease": True,
        "url": "https://example.invalid/release",
        "body": "Synthetic release notes",
        "assets": [{"name": f"travel-agent-skills-{version}.tgz", "size": 42, "digest": "sha256:abc"}],
    }


def test_pilot_selection_uses_publication_order_not_numeric_version():
    listed = [
        {"tagName": "v1.0.0-rc1", "isDraft": False, "isPrerelease": True,
         "publishedAt": "2026-07-07T11:26:00Z"},
        {"tagName": "v0.4.0-rc.1", "isDraft": False, "isPrerelease": True,
         "publishedAt": "2026-09-14T00:00:00Z"},
    ]
    with mock.patch.object(check_release, "gh_json", side_effect=[listed, release()]):
        selected = check_release.select_release("gh", "owner/repo", "pilot")
    assert selected["tagName"] == "v0.4.0-rc.1"


def test_stable_channel_truthfully_reports_no_eligible_release():
    historical = [
        {"tagName": "v0.1.0", "isDraft": False, "isPrerelease": True,
         "publishedAt": "2026-07-07T13:38:00Z"},
    ]
    with mock.patch.object(check_release, "gh_json", return_value=historical):
        assert check_release.select_release("gh", "owner/repo", "stable") is None


def test_explicit_pilot_can_propose_newer_publication_despite_lower_numeric_version(tmp_path):
    with mock.patch.object(check_release, "probe", return_value=installed()), \
         mock.patch.object(check_release, "select_release", return_value=release()), \
         mock.patch.object(check_release, "resolve_tag_commit", return_value="d" * 40):
        result = check_release.check_release(
            gh="gh", repository="owner/repo", channel="pilot",
            system_home=tmp_path, hermes_home=tmp_path / ".hermes",
        )
    assert result["status"] == "update_available"
    assert "reinstall_pinned.py" in result["proposed_command"]
    assert "d" * 40 in result["proposed_command"]
    assert f"--hermes-home {tmp_path / '.hermes'}" in result["proposed_command"]
    assert result["downloaded"] is False and result["executed"] is False


def test_archive_install_gets_canonical_path_and_explicit_replacement_proposal(tmp_path):
    (tmp_path / ".hermes/plugins/personal-assistant").mkdir(parents=True)
    with mock.patch.object(check_release, "probe", return_value=installed(source_kind="native_archive")), \
         mock.patch.object(check_release, "select_release", return_value=release()), \
         mock.patch.object(check_release, "resolve_tag_commit", return_value="e" * 40):
        result = check_release.check_release(
            gh="gh", repository="owner/repo", channel="pilot",
            system_home=tmp_path, hermes_home=tmp_path / ".hermes",
        )
    assert result["operator_archive_path"] == str(tmp_path / ".hermes/plugins/personal-assistant")
    assert "--archive-dir" in result["proposed_command"]
    assert "--hermes-home" in result["proposed_command"]


def test_equal_version_does_not_mask_known_source_mismatch(tmp_path):
    current = installed(version="0.4.0-rc.1", commit="a" * 40)
    with mock.patch.object(check_release, "probe", return_value=current), \
         mock.patch.object(check_release, "select_release", return_value=release()), \
         mock.patch.object(check_release, "resolve_tag_commit", return_value="b" * 40):
        result = check_release.check_release(
            gh="gh", repository="owner/repo", channel="pilot",
            system_home=tmp_path, hermes_home=tmp_path / "profile with space",
        )
    assert result["status"] == "source_mismatch"
    assert "'" in result["proposed_command"]
    assert "--hermes-home" in result["proposed_command"]


def test_invalid_install_and_missing_dependencies_are_not_actionable(tmp_path):
    for field, status in (("install_ok", "installed_invalid"), ("dependencies_ok", "dependencies_missing")):
        current = installed(commit="a" * 40)
        current[field] = False
        with mock.patch.object(check_release, "probe", return_value=current), \
             mock.patch.object(check_release, "select_release", return_value=release()), \
             mock.patch.object(check_release, "resolve_tag_commit", return_value="b" * 40):
            result = check_release.check_release(
                gh="gh", repository="owner/repo", channel="pilot",
                system_home=tmp_path, hermes_home=tmp_path / ".hermes",
            )
        assert result["ok"] is False
        assert result["status"] == status
        assert result["proposed_command"] is None


def test_unknown_source_identity_is_not_reported_ready_or_actionable(tmp_path):
    current = installed(commit=None)
    with mock.patch.object(check_release, "probe", return_value=current), \
         mock.patch.object(check_release, "select_release", return_value=release()), \
         mock.patch.object(check_release, "resolve_tag_commit", return_value="b" * 40):
        result = check_release.check_release(
            gh="gh", repository="owner/repo", channel="pilot",
            system_home=tmp_path, hermes_home=tmp_path / ".hermes",
        )
    assert result["ok"] is False
    assert result["status"] == "installed_source_identity_unknown"
    assert result["proposed_command"] is None


def test_no_release_does_not_mask_unhealthy_installed_profile(tmp_path):
    current = installed()
    current["dependencies_ok"] = False
    with mock.patch.object(check_release, "probe", return_value=current), \
         mock.patch.object(check_release, "select_release", return_value=None):
        result = check_release.check_release(
            gh="gh", repository="owner/repo", channel="stable",
            system_home=tmp_path, hermes_home=tmp_path / ".hermes",
        )
    assert result["ok"] is False
    assert result["status"] == "dependencies_missing"
    assert result["selected_release"] is None


def test_absent_native_target_never_gets_archive_proposal(tmp_path):
    with mock.patch.object(check_release, "probe", return_value=installed(source_kind="native_archive")), \
         mock.patch.object(check_release, "select_release", return_value=release()), \
         mock.patch.object(check_release, "resolve_tag_commit", return_value="e" * 40):
        result = check_release.check_release(
            gh="unused", repository="owner/repo", channel="pilot",
            system_home=tmp_path, hermes_home=tmp_path / ".hermes",
        )
    assert result["proposed_command"] is None
    assert result.get("operator_archive_path") is None
