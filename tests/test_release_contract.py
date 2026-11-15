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
    git(repo, "-c", "user.name=Release contract fixture", "-c", "user.email=release-contract@example.invalid",
        "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
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


@pytest.mark.parametrize("merged", [False, True])
@pytest.mark.parametrize("implementation_changed", [False, True])
def test_release_pr_requires_version_manifest_changelog_and_notes(tmp_path, merged, implementation_changed):
    repo, base = make_repo(tmp_path)
    (repo / "VERSION").write_text("0.4.0-rc.1\n")
    (repo / "plugin.yaml").write_text("name: personal-assistant\nversion: 0.4.0-rc.1\n")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## 0.4.0-rc.1\n\n- Pilot.\n")
    release = repo / "releases" / "0.4.0-rc.1"
    release.mkdir()
    (release / "manifest.json").write_text(json.dumps({
        "version": "0.4.0-rc.1", "native_id": "personal-assistant", "source_commit": "release-merge",
        "reviewed_implementation_commit": base,
    }))
    if implementation_changed:
        (repo / "scripts").mkdir()
        (repo / "scripts" / "implementation.py").write_text("unreviewed = True\n")
    head = commit(repo, "release")
    body = (
        "## Tracking\nCloses #30\n\n## Release impact\nRelease impact: publish\n\n"
        "## Release notes\nAdds explicit native pinned installation and verified release assets.\n"
    )
    with mock.patch.object(release_contract, "ROOT", repo):
        if merged and implementation_changed:
            with pytest.raises(ValueError, match="scripts/implementation.py"):
                release_contract.validate_pull_request(event(base, head, body, merged=True), require_merged=True)
            return
        result = release_contract.validate_pull_request(event(base, head, body, merged=merged), require_merged=merged)
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


def test_comment_holding_a_heading_does_not_leak_into_notes():
    body = ("Related #48\nRelease impact: publish\n## Release notes\nShips the release scorecard.\n"
            "<!-- bot metadata\n## Not a section\n-->\n## Summary by Bot\nBot text.")
    assert release_contract.parse_body(body) == ("publish", "Ships the release scorecard.")


@pytest.mark.parametrize("heading", ["# PA 0.10.0-rc.1 VA scorecard for another report", "# PA 0.10.0-rc.1 VA scorecard-old", ""])
def test_scorecard_heading_must_match_exactly(release_files, heading):
    release_files["releases/0.10.0-rc.1/scorecard.md"] = heading + "\n"
    with pytest.raises(ValueError, match="scorecard.md must start"):
        release_contract.validate_release_files("candidate", "0.10.0-rc.1")


def test_scorecard_commit_compares_case_insensitively(release_files):
    card = json.loads(release_files["releases/0.10.0-rc.1/scorecard.json"])
    card["commit"] = "A" * 40
    release_files["releases/0.10.0-rc.1/scorecard.json"] = json.dumps(card)
    release_contract.validate_release_files("candidate", "0.10.0-rc.1")


@pytest.fixture
def reviewed_repo(tmp_path):
    repo, _ = make_repo(tmp_path)
    for path in ("README.md", "AGENTS.md", "CONTRIBUTING.md", "LICENSE", "after-install.md"):
        (repo / path).write_text("Reviewed document\n")
    for path in release_contract.VERSION_FILES - {"plugin.yaml"}:
        destination = repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text('version = "0.3.0"\n')
    (repo / "personal_assistant" / "state.py").write_text("reviewed = True\n")
    reviewed = commit(repo, "reviewed implementation")
    return repo, reviewed


def release_candidate(repo, reviewed, version="0.4.0-rc.1"):
    (repo / "VERSION").write_text(version + "\n")
    for path in release_contract.VERSION_FILES:
        destination = repo / path
        destination.write_text(destination.read_text().replace("0.3.0", version))
    for path in ("CHANGELOG.md", "ROADMAP.md", "VISION.md", "docs/release.md"):
        destination = repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("Release documents\n")
    release = repo / "releases" / version
    release.mkdir()
    (release / "manifest.json").write_text(json.dumps({"reviewed_implementation_commit": reviewed}))
    return version


def test_reviewed_guard_allows_release_documents_and_version_bumps(reviewed_repo):
    repo, reviewed = reviewed_repo
    version = release_candidate(repo, reviewed)
    revision = commit(repo, "release metadata")
    with mock.patch.object(release_contract, "ROOT", repo):
        release_contract.check_reviewed_implementation(revision, version)


@pytest.mark.parametrize("path", ["README.md", "AGENTS.md", "CONTRIBUTING.md", "LICENSE", "after-install.md"])
@pytest.mark.parametrize("skill_changed", [False, True])
def test_reviewed_guard_allows_root_documents_but_rejects_skill_changes(reviewed_repo, path, skill_changed):
    repo, reviewed = reviewed_repo
    version = release_candidate(repo, reviewed, version="0.4.0")
    (repo / path).write_text("Updated release document\n")
    skill_path = "skills/example/SKILL.md"
    if skill_changed:
        destination = repo / skill_path
        destination.parent.mkdir(parents=True)
        destination.write_text("Unreviewed skill implementation\n")
    revision = commit(repo, "stable release documents")
    with mock.patch.object(release_contract, "ROOT", repo):
        if skill_changed:
            with pytest.raises(ValueError, match=re.escape(skill_path)):
                release_contract.check_reviewed_implementation(revision, version)
        else:
            release_contract.check_reviewed_implementation(revision, version)


def test_main_merge_returns_one_on_reviewed_guard_failure(reviewed_repo, capsys):
    repo, reviewed = reviewed_repo
    version = release_candidate(repo, reviewed, version="0.4.0")
    (repo / "README.md").write_text("Updated release document\n")
    destination = repo / "skills" / "example" / "SKILL.md"
    destination.parent.mkdir(parents=True)
    destination.write_text("Unreviewed skill implementation\n")
    (repo / "releases" / version / "manifest.json").write_text(json.dumps({
        "version": version, "native_id": "personal-assistant", "source_commit": "release-merge",
        "reviewed_implementation_commit": reviewed,
    }))
    revision = commit(repo, "unreviewed stable release")
    body = "Related #285\nRelease impact: publish\n## Release notes\nUpdates stable release documentation.\n"
    event_path = repo.parent / "event.json"
    event_path.write_text(json.dumps(event(reviewed, revision, body, merged=True)))
    with mock.patch.object(release_contract, "ROOT", repo):
        with mock.patch("sys.argv", ["release_contract.py", "merge", "--event", str(event_path)]):
            assert release_contract.main() == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["ok"] is False
    assert "packaged implementation differs from reviewed commit" in result["error"]
    assert "skills/example/SKILL.md" in result["error"]
    assert captured.err == ""


def test_reviewed_guard_rejects_packaged_implementation_changes(reviewed_repo):
    repo, reviewed = reviewed_repo
    version = release_candidate(repo, reviewed)
    (repo / "personal_assistant" / "state.py").write_text("reviewed = False\n")
    revision = commit(repo, "unreviewed implementation")
    with mock.patch.object(release_contract, "ROOT", repo):
        with pytest.raises(ValueError, match="personal_assistant/state.py"):
            release_contract.check_reviewed_implementation(revision, version)


@pytest.mark.parametrize("path", sorted(release_contract.VERSION_FILES))
def test_reviewed_guard_rejects_extra_version_file_changes(reviewed_repo, path):
    repo, reviewed = reviewed_repo
    version = release_candidate(repo, reviewed)
    destination = repo / path
    destination.write_text(destination.read_text() + "extra non-version change\n")
    revision = commit(repo, "unreviewed version file change")
    with mock.patch.object(release_contract, "ROOT", repo):
        with pytest.raises(ValueError, match=re.escape(path)):
            release_contract.check_reviewed_implementation(revision, version)


def test_reviewed_guard_rejects_non_ancestor(reviewed_repo):
    repo, base = reviewed_repo
    (repo / "side.txt").write_text("side branch\n")
    reviewed = commit(repo, "not an ancestor of release")
    git(repo, "checkout", "--detach", base)
    version = release_candidate(repo, reviewed)
    revision = commit(repo, "release on another lineage")
    with mock.patch.object(release_contract, "ROOT", repo):
        with pytest.raises(ValueError) as error:
            release_contract.check_reviewed_implementation(revision, version)
    assert "ancestor" in str(error.value)
    assert reviewed in str(error.value) and revision in str(error.value)


@pytest.mark.parametrize("reviewed", [None, "not-hex", "a" * 39, 123])
def test_reviewed_guard_rejects_missing_or_invalid_reviewed_commit(reviewed_repo, reviewed):
    repo, _ = reviewed_repo
    version = release_candidate(repo, reviewed)
    if reviewed is None:
        (repo / "releases" / version / "manifest.json").write_text("{}")
    revision = commit(repo, "invalid reviewed identity")
    with mock.patch.object(release_contract, "ROOT", repo):
        with pytest.raises(ValueError, match="reviewed_implementation_commit must be a 40-hex string"):
            release_contract.check_reviewed_implementation(revision, version)


def test_reviewed_guard_fails_loudly_when_reviewed_commit_is_unavailable(reviewed_repo):
    repo, _ = reviewed_repo
    reviewed = "f" * 40
    version = release_candidate(repo, reviewed)
    revision = commit(repo, "unavailable reviewed commit")
    with mock.patch.object(release_contract, "ROOT", repo):
        with pytest.raises(ValueError, match=f"{reviewed}.*{revision}"):
            release_contract.check_reviewed_implementation(revision, version)


@pytest.mark.parametrize("path", ["tests/test_state.py", "personal_assistant/tests/double.py",
                                  "personal_assistant/clients.json"])
def test_reviewed_guard_ignores_unpackaged_changes(reviewed_repo, path):
    repo, reviewed = reviewed_repo
    version = release_candidate(repo, reviewed)
    destination = repo / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("synthetic repository-only fixture\n")
    revision = commit(repo, "unpackaged change")
    with mock.patch.object(release_contract, "ROOT", repo):
        release_contract.check_reviewed_implementation(revision, version)


def test_reviewed_guard_accepts_real_026_release_history():
    revision = "c15fb31841f07f58c9e8980adda4457e29060c55"
    reviewed = "631626a06eded0345a2e939e540101f13fddae21"
    for sha in (revision, reviewed):
        try:
            release_contract.git("cat-file", "-e", f"{sha}^{{commit}}")
        except ValueError:
            pytest.skip(f"historical commit {sha} is not available locally")
    assert json.loads(release_contract.text_at(revision, "releases/0.26.0-rc.1/manifest.json"))[
        "reviewed_implementation_commit"
    ] == reviewed
    release_contract.check_reviewed_implementation(revision, "0.26.0-rc.1")
