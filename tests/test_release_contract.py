import json
import re
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


@pytest.fixture
def release_files():
    version = "0.10.0-rc.1"
    files = {
        "plugin.yaml": f"name: personal-assistant\nversion: {version}\n",
        f"releases/{version}/manifest.json": json.dumps({
            "version": version, "native_id": "personal-assistant", "source_commit": "release-merge",
            "reviewed_implementation_commit": "a" * 40,
        }),
        f"releases/{version}/scorecard.json": json.dumps({
            "schema": 1, "version": version, "commit": "a" * 40,
            "areas": {f"area-{index}": {} for index in range(14)},
        }),
        f"releases/{version}/scorecard.md": f"# PA {version} VA scorecard\n",
    }

    def read(_revision, path):
        if path not in files:
            raise ValueError("git show failed")
        return files[path]

    with mock.patch.object(release_contract, "text_at", side_effect=read):
        yield files


@pytest.mark.parametrize("extension", ["json", "md"])
def test_release_requires_both_scorecard_files(release_files, extension):
    path = f"releases/0.10.0-rc.1/scorecard.{extension}"
    del release_files[path]
    with pytest.raises(ValueError, match="release scorecard missing: " + re.escape(path)):
        release_contract.validate_release_files("candidate", "0.10.0-rc.1")


@pytest.mark.parametrize(("field", "value", "message"), [
    ("schema", 2, "scorecard schema must be 1"),
    ("schema", True, "scorecard schema must be 1"),
    ("version", "0.9.0-rc.3", "scorecard version does not match"),
    ("commit", "b" * 40, "scorecard commit does not match the manifest"),
    ("commit", "not-a-commit", "scorecard commit must be a 40-hex string"),
    ("areas", [{}] * 13, "scorecard areas must have 14 entries"),
    ("areas", "x" * 14, "scorecard areas must have 14 entries"),
])
def test_invalid_scorecard_fields_are_rejected(release_files, field, value, message):
    path = "releases/0.10.0-rc.1/scorecard.json"
    scorecard = json.loads(release_files[path])
    scorecard[field] = value
    release_files[path] = json.dumps(scorecard)
    with pytest.raises(ValueError, match=message):
        release_contract.validate_release_files("candidate", "0.10.0-rc.1")


@pytest.mark.parametrize(("content", "message"), [
    ("{", "not valid JSON"),
    ("[]", "must be a JSON object"),
])
def test_invalid_scorecard_json_is_rejected(release_files, content, message):
    release_files["releases/0.10.0-rc.1/scorecard.json"] = content
    with pytest.raises(ValueError, match=message):
        release_contract.validate_release_files("candidate", "0.10.0-rc.1")


def test_scorecard_markdown_requires_versioned_heading(release_files):
    release_files["releases/0.10.0-rc.1/scorecard.md"] = "# PA 0.9.0 VA scorecard"
    with pytest.raises(ValueError, match="scorecard.md must start"):
        release_contract.validate_release_files("candidate", "0.10.0-rc.1")


def test_correct_scorecard_passes(release_files):
    release_contract.validate_release_files("candidate", "0.10.0-rc.1")


@pytest.mark.parametrize(("version", "required"), [
    ("0.9.0-rc.3", False), ("0.9.9", False), ("0.10.0", True), ("1.0.0-rc.1", True),
])
def test_scorecard_version_threshold(version, required):
    files = {
        "plugin.yaml": f"name: personal-assistant\nversion: {version}\n",
        f"releases/{version}/manifest.json": json.dumps({
            "version": version, "native_id": "personal-assistant", "source_commit": "historical",
        }),
    }

    def read(_revision, path):
        if path not in files:
            raise ValueError("git show failed")
        return files[path]

    with mock.patch.object(release_contract, "text_at", side_effect=read):
        if required:
            with pytest.raises(ValueError, match="release scorecard missing"):
                release_contract.validate_release_files("candidate", version)
        else:
            release_contract.validate_release_files("candidate", version)


def test_release_notes_strip_multiline_comments_before_bot_summary():
    body = (
        "Related #48\nRelease impact: publish\n## Release notes\n"
        "Ships the release scorecard.\n<!-- a\nmultiline -->\n<!-- b -->\n## Summary by Bot\nBot text."
    )
    assert release_contract.parse_body(body) == ("publish", "Ships the release scorecard.")


def test_comment_only_notes_are_not_substantive():
    body = "Related #48\nRelease impact: publish\n## Release notes\n<!-- only\ncomment -->\n"
    base, head = "a" * 40, "b" * 40
    with mock.patch.object(release_contract, "text_at", side_effect=["0.9.0", "0.10.0"]):
        with mock.patch.object(release_contract, "git", return_value="VERSION\nCHANGELOG.md"):
            with pytest.raises(ValueError, match="substantive release notes"):
                release_contract.validate_pull_request(event(base, head, body))
