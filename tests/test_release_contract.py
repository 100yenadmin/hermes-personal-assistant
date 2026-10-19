import json
from pathlib import Path
import subprocess
from unittest import mock

import pytest

from scripts import release_contract


def git(repo, *args):
    completed = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
    return completed.stdout.strip()


def commit(repo, message):
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Release contract fixture")
    git(repo, "config", "user.email", "release-contract@example.invalid")
    (repo / "VERSION").write_text("0.3.0\n")
    (repo / "plugin.yaml").write_text("name: personal-assistant\nversion: 0.3.0\n")
    (repo / "CHANGELOG.md").write_text("# Changelog\n")
    release = repo / "releases" / "0.3.0"
    release.mkdir(parents=True)
    (release / "manifest.json").write_text(json.dumps({
        "version": "0.3.0", "native_id": "personal-assistant", "source_commit": "historical"
    }))
    return repo, commit(repo, "base")


def event(base, head, body, *, merged=False):
    return {
        "pull_request": {
            "body": body,
            "merged": merged,
            "merge_commit_sha": head if merged else None,
            "base": {"sha": base, "ref": "main"},
            "head": {"sha": head, "ref": "release"},
        }
    }


def test_ordinary_pr_links_issue_and_cannot_change_version(tmp_path):
    repo, base = make_repo(tmp_path)
    (repo / "feature.txt").write_text("implementation\n")
    head = commit(repo, "feature")
    body = "## Tracking\nCloses #31\n\n## Release impact\nRelease impact: none\n\n## Release notes\nN/A\n"
    with mock.patch.object(release_contract, "ROOT", repo):
        result = release_contract.validate_pull_request(event(base, head, body))
    assert result["publish"] is False and result["version"] == "0.3.0"


def test_release_pr_requires_version_manifest_changelog_and_notes(tmp_path):
    repo, base = make_repo(tmp_path)
    (repo / "VERSION").write_text("0.4.0-rc.1\n")
    (repo / "plugin.yaml").write_text("name: personal-assistant\nversion: 0.4.0-rc.1\n")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## 0.4.0-rc.1\n\n- Pilot.\n")
    release = repo / "releases" / "0.4.0-rc.1"
    release.mkdir()
    (release / "manifest.json").write_text(json.dumps({
        "version": "0.4.0-rc.1", "native_id": "personal-assistant", "source_commit": "release-merge"
    }))
    head = commit(repo, "release")
    body = (
        "## Tracking\nCloses #30\n\n## Release impact\nRelease impact: publish\n\n"
        "## Release notes\nAdds explicit native pinned installation and verified release assets.\n"
    )
    with mock.patch.object(release_contract, "ROOT", repo):
        result = release_contract.validate_pull_request(event(base, head, body, merged=True), require_merged=True)
    assert result["publish"] is True and result["version"] == "0.4.0-rc.1"


def test_publish_intent_without_version_change_is_rejected(tmp_path):
    repo, base = make_repo(tmp_path)
    (repo / "feature.txt").write_text("implementation\n")
    head = commit(repo, "feature")
    body = "Closes #30\nRelease impact: publish\n## Release notes\nSubstantive notes.\n"
    with mock.patch.object(release_contract, "ROOT", repo):
        with pytest.raises(ValueError, match="VERSION did not change"):
            release_contract.validate_pull_request(event(base, head, body))
