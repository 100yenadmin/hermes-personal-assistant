from argparse import Namespace
import hashlib
import json
from pathlib import Path
from unittest import mock

import pytest

from scripts import publish_release
from scripts import verify_release_recovery


def assets(tmp_path, version="0.4.0-rc.1"):
    names = [
        f"travel-agent-skills-{version}.tgz",
        f"travel-agent-skills-{version}.tgz.sha256",
        f"travel-agent-skills-{version}.manifest.json",
    ]
    for index, name in enumerate(names):
        (tmp_path / name).write_bytes(f"asset-{index}".encode())
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes\n")
    return names, notes


def release(asset_names, *, draft=True, name="Personal Assistant v0.4.0-rc.1",
            body="Release notes\n", prerelease=True, tag_name="v0.4.0-rc.1"):
    return {
        "id": 42,
        "tag_name": tag_name,
        "draft": draft,
        "name": name,
        "body": body,
        "prerelease": prerelease,
        "html_url": "https://example.invalid/release",
        "assets": [{"name": name, "digest": "sha256:fixture"} for name in asset_names],
    }


def test_release_for_tag_finds_exact_draft_when_tag_endpoint_returns_404():
    draft = release([])
    with mock.patch.object(publish_release, "gh_json", return_value=None) as direct, \
         mock.patch.object(
             publish_release,
             "gh_json_pages",
             return_value=[release([], tag_name="v0.3.0"), draft],
         ) as pages:
        assert publish_release.release_for_tag("owner/repo", "v0.4.0-rc.1") == draft
    direct.assert_called_once_with(
        ["api", "repos/owner/repo/releases/tags/v0.4.0-rc.1"], missing_ok=True
    )
    pages.assert_called_once_with([
        "api", "--paginate", "--slurp", "repos/owner/repo/releases?per_page=100",
    ])


def test_release_for_tag_refuses_duplicate_exact_matches():
    with mock.patch.object(publish_release, "gh_json", return_value=None), \
         mock.patch.object(
             publish_release, "gh_json_pages", return_value=[release([]), release([])]
         ):
        with pytest.raises(publish_release.PublishError, match="multiple releases"):
            publish_release.release_for_tag("owner/repo", "v0.4.0-rc.1")


def test_recovery_verifier_binds_run_source_and_all_file_digests(tmp_path):
    version = "0.4.0-rc.1"
    stem = f"travel-agent-skills-{version}"
    assets_dir = tmp_path / "dist"
    assets_dir.mkdir()
    files = [f"{stem}.tgz", f"{stem}.tgz.sha256", f"{stem}.manifest.json", "release-notes.md"]
    for name in files:
        (assets_dir / name).write_bytes(name.encode())
    run = {"id": 7, "head_sha": "b" * 40, "conclusion": "failure",
           "repository": {"full_name": "owner/repo"}}
    jobs = {"jobs": [{"name": name, "conclusion": result} for name, result in (
        ("classify", "success"), ("build", "success"), ("publish", "failure"))]}
    (tmp_path / "run.json").write_text(json.dumps(run))
    (tmp_path / "jobs.json").write_text(json.dumps(jobs))
    args = Namespace(
        dir=str(assets_dir), run_json=str(tmp_path / "run.json"),
        jobs_json=str(tmp_path / "jobs.json"), repository="owner/repo", run_id=7,
        run_head_sha="b" * 40, source_sha="a" * 40, version=version,
        archive_sha256=hashlib.sha256(files[0].encode()).hexdigest(),
        checksum_sha256=hashlib.sha256(files[1].encode()).hexdigest(),
        manifest_sha256=hashlib.sha256(files[2].encode()).hexdigest(),
        notes_sha256=hashlib.sha256(files[3].encode()).hexdigest(),
    )
    with mock.patch.object(
        verify_release_recovery, "verify_release_assets", return_value={"source_sha": "a" * 40}
    ):
        assert verify_release_recovery.verify(args)["ok"] is True
        (assets_dir / files[0]).write_bytes(b"substituted")
        with pytest.raises(ValueError, match="artifact digest mismatch"):
            verify_release_recovery.verify(args)


def test_existing_tag_must_match_source_commit():
    with mock.patch.object(publish_release, "tag_commit", return_value="b" * 40):
        with pytest.raises(publish_release.PublishError, match="different commit"):
            publish_release.ensure_tag("owner/repo", "v0.4.0-rc.1", "a" * 40)


def test_partial_draft_resumes_only_missing_same_byte_assets(tmp_path):
    names, notes = assets(tmp_path)
    initial = release(names[:1])
    complete = release(names)
    final = release(names, draft=False)
    calls = []
    with mock.patch.object(publish_release, "ensure_tag"), \
         mock.patch.object(publish_release, "release_for_tag", side_effect=[initial, complete, final]), \
         mock.patch.object(publish_release, "matching_existing_asset", return_value=True), \
         mock.patch.object(publish_release, "verify_download"), \
         mock.patch.object(publish_release, "gh_json", return_value={}), \
         mock.patch.object(publish_release, "call", side_effect=lambda command: calls.append(command)):
        result = publish_release.publish("owner/repo", "a" * 40, "0.4.0-rc.1", tmp_path, notes)
    uploads = [command for command in calls if command[:3] == ["gh", "release", "upload"]]
    assert len(uploads) == 2
    assert all("--clobber" not in command for command in uploads)
    assert result["uploaded"] == names[1:]
    assert result["post_download_verified"] is True


def test_mismatched_existing_asset_fails_without_upload(tmp_path):
    names, notes = assets(tmp_path)
    with mock.patch.object(publish_release, "ensure_tag"), \
         mock.patch.object(publish_release, "release_for_tag", return_value=release(names[:1])), \
         mock.patch.object(publish_release, "matching_existing_asset", return_value=False), \
         mock.patch.object(publish_release, "call") as call:
        with pytest.raises(publish_release.PublishError, match="different bytes"):
            publish_release.publish("owner/repo", "a" * 40, "0.4.0-rc.1", tmp_path, notes)
    call.assert_not_called()


def test_same_assets_with_wrong_draft_metadata_refuse_without_mutation(tmp_path):
    names, notes = assets(tmp_path)
    stored = release(names, name="Unapproved title", body="Edited notes\n", prerelease=False)
    reads = []

    def persistent_release(_repository, _tag):
        reads.append(stored.copy())
        return stored

    with mock.patch.object(publish_release, "ensure_tag"), \
         mock.patch.object(publish_release, "release_for_tag", side_effect=persistent_release), \
         mock.patch.object(publish_release, "matching_existing_asset", return_value=True), \
         mock.patch.object(publish_release, "gh_json") as gh_json, \
         mock.patch.object(publish_release, "call") as call:
        with pytest.raises(publish_release.PublishError, match="name, body, prerelease"):
            publish_release.publish("owner/repo", "a" * 40, "0.4.0-rc.1", tmp_path, notes)
    assert len(reads) == 1
    assert stored["draft"] is True
    gh_json.assert_not_called()
    call.assert_not_called()


def test_create_draft_retries_readback_until_the_fresh_draft_is_listed(tmp_path):
    draft = release([])
    _, notes = assets(tmp_path)
    with mock.patch.object(publish_release, "call") as create, \
         mock.patch.object(
             publish_release, "release_for_tag", side_effect=[None, None, draft]
         ) as readback, \
         mock.patch.object(publish_release.time, "sleep") as sleep:
        assert publish_release.create_draft("owner/repo", "v0.4.0-rc.1", "0.4.0-rc.1", notes) == draft
    create.assert_called_once()
    assert readback.call_count == 3
    assert sleep.call_count == 2


def test_create_draft_fails_closed_when_the_draft_never_reads_back(tmp_path):
    _, notes = assets(tmp_path)
    with mock.patch.object(publish_release, "call"), \
         mock.patch.object(publish_release, "release_for_tag", return_value=None) as readback, \
         mock.patch.object(publish_release.time, "sleep") as sleep:
        with pytest.raises(publish_release.PublishError, match="could not be read back"):
            publish_release.create_draft("owner/repo", "v0.4.0-rc.1", "0.4.0-rc.1", notes)
    assert readback.call_count == publish_release.DRAFT_READBACK_ATTEMPTS
    assert sleep.call_count == publish_release.DRAFT_READBACK_ATTEMPTS - 1


def test_create_draft_rejects_a_readback_that_is_not_a_draft(tmp_path):
    _, notes = assets(tmp_path)
    with mock.patch.object(publish_release, "call"), \
         mock.patch.object(publish_release, "release_for_tag", return_value=release([], draft=False)), \
         mock.patch.object(publish_release.time, "sleep") as sleep:
        with pytest.raises(publish_release.PublishError, match="could not be read back"):
            publish_release.create_draft("owner/repo", "v0.4.0-rc.1", "0.4.0-rc.1", notes)
    sleep.assert_not_called()
