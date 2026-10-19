#!/usr/bin/env python3
"""Publish or safely resume one immutable PA GitHub release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.parse


class PublishError(RuntimeError):
    pass


def call(arguments: list[str], *, expect: int = 0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(arguments, text=True, capture_output=True)
    if completed.returncode != expect:
        raise PublishError(f"command failed with exit {completed.returncode}: {arguments[0]} {arguments[1:3]}")
    return completed


def gh_json(arguments: list[str], *, missing_ok: bool = False) -> dict[str, object] | None:
    completed = subprocess.run(["gh", *arguments], text=True, capture_output=True)
    if completed.returncode != 0:
        error = completed.stderr or completed.stdout
        if missing_ok and ("HTTP 404" in error or "Not Found" in error):
            return None
        raise PublishError(f"GitHub API request failed with exit {completed.returncode}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PublishError("GitHub API returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise PublishError("GitHub API returned an unexpected response")
    return value


def gh_json_pages(arguments: list[str]) -> list[dict[str, object]]:
    completed = subprocess.run(["gh", *arguments], text=True, capture_output=True)
    if completed.returncode != 0:
        raise PublishError(f"GitHub API request failed with exit {completed.returncode}")
    try:
        pages = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PublishError("GitHub API returned invalid JSON") from exc
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise PublishError("GitHub paginated API returned an unexpected response")
    releases = [item for page in pages for item in page]
    if any(not isinstance(item, dict) for item in releases):
        raise PublishError("GitHub paginated API returned an unexpected release")
    return releases


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tag_commit(repository: str, tag: str) -> str | None:
    encoded = urllib.parse.quote(tag, safe="")
    value = gh_json(["api", f"repos/{repository}/git/ref/tags/{encoded}"], missing_ok=True)
    if value is None:
        return None
    obj = value.get("object") if isinstance(value.get("object"), dict) else {}
    for _ in range(2):
        if obj.get("type") == "commit" and isinstance(obj.get("sha"), str):
            return str(obj["sha"])
        if obj.get("type") != "tag" or not isinstance(obj.get("sha"), str):
            break
        value = gh_json(["api", f"repos/{repository}/git/tags/{obj['sha']}"])
        obj = value.get("object") if value and isinstance(value.get("object"), dict) else {}
    raise PublishError("existing tag does not resolve to a commit")


def ensure_tag(repository: str, tag: str, source_sha: str) -> None:
    existing = tag_commit(repository, tag)
    if existing and existing != source_sha:
        raise PublishError(f"existing tag {tag} targets a different commit")
    if existing:
        return
    gh_json([
        "api", "--method", "POST", f"repos/{repository}/git/refs",
        "-f", f"ref=refs/tags/{tag}", "-f", f"sha={source_sha}",
    ])
    if tag_commit(repository, tag) != source_sha:
        raise PublishError("created tag did not read back at the requested source commit")


def release_for_tag(repository: str, tag: str) -> dict[str, object] | None:
    encoded = urllib.parse.quote(tag, safe="")
    release = gh_json(["api", f"repos/{repository}/releases/tags/{encoded}"], missing_ok=True)
    if release is not None:
        return release
    releases = gh_json_pages([
        "api", "--paginate", "--slurp", f"repos/{repository}/releases?per_page=100",
    ])
    matches = [item for item in releases if item.get("tag_name") == tag]
    if len(matches) > 1:
        raise PublishError(f"multiple releases found for exact tag {tag}")
    return matches[0] if matches else None


DRAFT_READBACK_ATTEMPTS = 6
DRAFT_READBACK_DELAY_SECONDS = 2.0


def read_back_release(
    repository: str,
    tag: str,
    *,
    attempts: int = DRAFT_READBACK_ATTEMPTS,
    delay: float = DRAFT_READBACK_DELAY_SECONDS,
) -> dict[str, object] | None:
    """Read a just-created release back.

    A draft is never served by the tag endpoint and the release list can lag a
    fresh draft by a few seconds, so a single immediate read-back fails the run
    even though the draft exists (v0.4.0-rc.1 and v0.4.1-rc.1 both died here on
    their first attempt). Bounded retries keep the same-byte contract intact.
    """
    for attempt in range(attempts):
        release = release_for_tag(repository, tag)
        if release is not None:
            return release
        if attempt + 1 < attempts:
            time.sleep(delay)
    return None


def create_draft(repository: str, tag: str, version: str, notes: Path) -> dict[str, object]:
    command = [
        "gh", "release", "create", tag, "--repo", repository, "--verify-tag", "--draft",
        "--title", f"Personal Assistant v{version}", "--notes-file", str(notes),
    ]
    if "-" in version:
        command.append("--prerelease")
    call(command)
    release = read_back_release(repository, tag)
    if release is None or release.get("draft") is not True:
        raise PublishError("draft release was not created or could not be read back")
    return release


def existing_assets(release: dict[str, object]) -> dict[str, dict[str, object]]:
    assets = release.get("assets") if isinstance(release.get("assets"), list) else []
    return {
        str(item["name"]): item for item in assets
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def validate_release_metadata(release: dict[str, object], version: str, notes: Path) -> None:
    expected_name = f"Personal Assistant v{version}"
    expected_body = notes.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n")
    observed_body = str(release.get("body") or "").replace("\r\n", "\n").rstrip("\n")
    expected_prerelease = "-" in version
    mismatches = []
    if release.get("name") != expected_name:
        mismatches.append("name")
    if observed_body != expected_body:
        mismatches.append("body")
    if release.get("prerelease") is not expected_prerelease:
        mismatches.append("prerelease")
    if mismatches:
        raise PublishError(
            "existing release metadata differs from the approved release input: "
            + ", ".join(mismatches)
        )


def download_asset(repository: str, tag: str, name: str, directory: Path) -> Path:
    call([
        "gh", "release", "download", tag, "--repo", repository,
        "--pattern", name, "--dir", str(directory), "--clobber",
    ])
    path = directory / name
    if not path.is_file():
        raise PublishError(f"downloaded release asset is missing: {name}")
    return path


def matching_existing_asset(repository: str, tag: str, asset: dict[str, object], local: Path) -> bool:
    digest = asset.get("digest")
    local_digest = sha256(local)
    if isinstance(digest, str) and digest.startswith("sha256:"):
        return digest == f"sha256:{local_digest}"
    with tempfile.TemporaryDirectory(prefix="pa-release-existing-") as temporary:
        downloaded = download_asset(repository, tag, local.name, Path(temporary))
        return sha256(downloaded) == local_digest


def verify_download(repository: str, tag: str, version: str, expected: list[Path]) -> None:
    with tempfile.TemporaryDirectory(prefix="pa-release-download-") as temporary:
        directory = Path(temporary)
        for asset in expected:
            downloaded = download_asset(repository, tag, asset.name, directory)
            if sha256(downloaded) != sha256(asset):
                raise PublishError(f"post-download digest mismatch: {asset.name}")
        verifier = Path(__file__).with_name("verify_release_assets.py")
        call([sys.executable, str(verifier), "--dir", str(directory), "--version", version])


def publish(repository: str, source_sha: str, version: str, assets_dir: Path, notes: Path) -> dict[str, object]:
    tag = f"v{version}"
    expected = [
        assets_dir / f"travel-agent-skills-{version}.tgz",
        assets_dir / f"travel-agent-skills-{version}.tgz.sha256",
        assets_dir / f"travel-agent-skills-{version}.manifest.json",
    ]
    if any(not path.is_file() for path in expected):
        raise PublishError("local release asset set is incomplete")
    ensure_tag(repository, tag, source_sha)
    release = release_for_tag(repository, tag) or create_draft(repository, tag, version, notes)
    validate_release_metadata(release, version, notes)
    current = existing_assets(release)
    expected_names = {path.name for path in expected}
    unexpected = sorted(set(current) - {path.name for path in expected})
    if unexpected:
        raise PublishError(f"existing release contains unexpected assets: {unexpected}")
    if release.get("draft") is not True and set(current) != expected_names:
        raise PublishError("published release has an incomplete asset set and cannot be resumed")
    uploaded: list[str] = []
    for path in expected:
        if path.name in current:
            if not matching_existing_asset(repository, tag, current[path.name], path):
                raise PublishError(f"existing release asset has different bytes: {path.name}")
            continue
        call(["gh", "release", "upload", tag, str(path), "--repo", repository])
        uploaded.append(path.name)
    release = release_for_tag(repository, tag)
    current = existing_assets(release or {})
    if set(current) != expected_names:
        raise PublishError("release asset set did not read back exactly")
    for path in expected:
        if not matching_existing_asset(repository, tag, current[path.name], path):
            raise PublishError(f"uploaded release asset has different bytes: {path.name}")
    verify_download(repository, tag, version, expected)
    if release and release.get("draft") is True:
        release_id = release.get("id")
        if not isinstance(release_id, int):
            raise PublishError("draft release lacks a numeric ID")
        gh_json([
            "api", "--method", "PATCH", f"repos/{repository}/releases/{release_id}",
            "-F", "draft=false", "-F", f"prerelease={'true' if '-' in version else 'false'}",
        ])
    final = release_for_tag(repository, tag)
    if final is None or final.get("draft") is True:
        raise PublishError("release did not publish")
    validate_release_metadata(final, version, notes)
    verify_download(repository, tag, version, expected)
    return {
        "ok": True,
        "tag": tag,
        "source_sha": source_sha,
        "assets": [path.name for path in expected],
        "uploaded": uploaded,
        "prerelease": bool(final.get("prerelease")),
        "url": final.get("html_url"),
        "post_download_verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--assets-dir", required=True)
    parser.add_argument("--notes-file", required=True)
    args = parser.parse_args()
    if not args.repo:
        print(json.dumps({"ok": False, "error": "repository is required"}))
        return 1
    try:
        result = publish(
            args.repo, args.source_sha.lower(), args.version,
            Path(args.assets_dir).resolve(), Path(args.notes_file).resolve(),
        )
    except (OSError, PublishError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
