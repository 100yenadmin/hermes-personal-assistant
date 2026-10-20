#!/usr/bin/env python3
"""Read-only GitHub release comparison for a Personal Assistant installation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import urllib.parse

from packaging.version import InvalidVersion, Version

try:
    from .probe_installed_version import probe
except ImportError:
    from probe_installed_version import probe


DEFAULT_REPOSITORY = "100yenadmin/hermes-personal-assistant"
FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


class GithubUnavailable(RuntimeError):
    pass


def gh_json(gh: str, arguments: list[str]) -> object:
    completed = subprocess.run([gh, *arguments], text=True, capture_output=True)
    if completed.returncode != 0:
        raise GithubUnavailable(f"GitHub CLI request failed with exit {completed.returncode}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GithubUnavailable("GitHub CLI returned invalid JSON") from exc


def select_release(gh: str, repository: str, channel: str) -> dict[str, object] | None:
    releases = gh_json(gh, [
        "release", "list", "--repo", repository, "--limit", "100",
        "--json", "tagName,isDraft,isPrerelease,publishedAt,name",
    ])
    if not isinstance(releases, list):
        raise GithubUnavailable("GitHub CLI returned an invalid release list")
    eligible = [
        item for item in releases
        if isinstance(item, dict)
        and not item.get("isDraft")
        and bool(item.get("isPrerelease")) == (channel == "pilot")
        and item.get("publishedAt")
    ]
    if not eligible:
        return None
    selected = max(eligible, key=lambda item: str(item["publishedAt"]))
    detail = gh_json(gh, [
        "release", "view", str(selected["tagName"]), "--repo", repository,
        "--json", "tagName,name,isDraft,isPrerelease,publishedAt,url,body,assets,targetCommitish",
    ])
    if not isinstance(detail, dict):
        raise GithubUnavailable("GitHub CLI returned invalid release detail")
    return detail


def resolve_tag_commit(gh: str, repository: str, tag: str) -> str:
    encoded = urllib.parse.quote(tag, safe="")
    value = gh_json(gh, ["api", f"repos/{repository}/git/ref/tags/{encoded}"])
    if not isinstance(value, dict) or not isinstance(value.get("object"), dict):
        raise GithubUnavailable("GitHub tag response did not contain an object")
    obj = value["object"]
    for _ in range(2):
        if obj.get("type") == "commit" and isinstance(obj.get("sha"), str):
            return obj["sha"]
        if obj.get("type") != "tag" or not isinstance(obj.get("sha"), str):
            break
        value = gh_json(gh, ["api", f"repos/{repository}/git/tags/{obj['sha']}"])
        obj = value.get("object", {}) if isinstance(value, dict) else {}
    raise GithubUnavailable("GitHub tag did not resolve to a commit")


def version_from_tag(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def newer_stable(selected: str, installed: str | None) -> bool:
    if not installed:
        return True
    try:
        return Version(selected) > Version(installed)
    except InvalidVersion:
        return False


def asset_summary(assets: object) -> list[dict[str, object]]:
    if not isinstance(assets, list):
        return []
    return [
        {"name": item.get("name"), "size": item.get("size"), "digest": item.get("digest")}
        for item in assets if isinstance(item, dict)
    ]


def _shell_command(arguments: list[str], *, hermes_home: Path | None = None) -> str:
    command = " ".join(shlex.quote(str(item)) for item in arguments)
    if hermes_home is not None:
        return f"HERMES_HOME={shlex.quote(str(hermes_home))} {command}"
    return command


def _replacement_script(installed: dict[str, object], hermes_home: Path) -> Path:
    package_path = installed.get("package_path")
    root = Path(str(package_path)).expanduser() if package_path else hermes_home / "plugins" / "personal-assistant"
    return root.resolve() / "scripts" / "reinstall_pinned.py"


def check_release(*, gh: str, repository: str, channel: str,
                  system_home: Path, hermes_home: Path) -> dict[str, object]:
    installed = probe(system_home, hermes_home)
    selected = select_release(gh, repository, channel)
    base: dict[str, object] = {
        "ok": True,
        "channel": channel,
        "repository": repository,
        "downloaded": False,
        "executed": False,
        "installed": installed,
        "selected_release": None,
        "status": "no_release_on_channel",
        "proposed_command": None,
        "operator_archive_path": None,
        "release_changes": None,
    }
    observed_commit = installed.get("observed_commit")
    observed_version = installed.get("observed_version")
    migration_required = installed.get("source_kind") == "legacy_openclaw"
    if migration_required:
        base.pop("operator_archive_path")
    unhealthy_status = None
    if installed.get("installed"):
        if installed.get("invalid_reason"):
            unhealthy_status = "installed_invalid"
        elif migration_required:
            unhealthy_status = "migration_required"
        elif installed.get("source_kind") == "native_git" and installed.get("source_identity_reason") in {
            "local_edits", "source_mismatch",
        }:
            unhealthy_status = installed["source_identity_reason"]
        elif installed.get("install_ok") is not True:
            unhealthy_status = "installed_invalid"
        elif installed.get("dependencies_ok") is not True:
            unhealthy_status = "dependencies_missing"
        elif (installed.get("source_identity_known") is False
              or not isinstance(observed_commit, str) or not FULL_SHA.fullmatch(observed_commit)):
            unhealthy_status = "installed_source_identity_unknown"
    if selected is None:
        if unhealthy_status:
            base["ok"] = False
            base["status"] = unhealthy_status
        return base
    tag = str(selected.get("tagName") or "")
    release_version = version_from_tag(tag)
    source_sha = resolve_tag_commit(gh, repository, tag)
    summary = {
        "tag": tag,
        "version": release_version,
        "name": selected.get("name"),
        "published_at": selected.get("publishedAt"),
        "prerelease": bool(selected.get("isPrerelease")),
        "url": selected.get("url"),
        "source_sha": source_sha,
        "assets": asset_summary(selected.get("assets")),
    }
    base["selected_release"] = summary
    base["release_changes"] = selected.get("body") or ""
    if unhealthy_status and unhealthy_status != "migration_required":
        base["ok"] = False
        base["status"] = unhealthy_status
        return base
    if not installed.get("installed") or migration_required:
        base["status"] = "migration_required" if migration_required else "not_installed"
        if migration_required:
            base["ok"] = False
        base["proposed_command"] = _shell_command(
            ["hermes", "plugins", "install", repository, "--ref", source_sha, "--no-enable"],
            hermes_home=hermes_home,
        )
        return base
    if observed_commit.lower() == source_sha.lower():
        base["status"] = "up_to_date"
        return base

    same_version_mismatch = observed_version == release_version
    update_available = (
        channel == "pilot"
        or same_version_mismatch
        or newer_stable(release_version, str(observed_version or "") or None)
    )
    if not update_available:
        base["status"] = "installed_newer_or_off_channel"
        return base
    base["status"] = "source_mismatch" if same_version_mismatch else "update_available"
    replacement = _replacement_script(installed, hermes_home)
    if installed.get("source_kind") == "native_git":
        base["proposed_command"] = _shell_command(
            [
                "python3", str(replacement), "--source", repository, "--ref", source_sha,
                "--hermes-home", str(hermes_home),
            ]
        )
    elif installed.get("source_kind") in {"native_archive", "native_copy"} and (
        hermes_home / "plugins" / "personal-assistant"
    ).is_dir():
        base["operator_archive_path"] = str((hermes_home / "plugins" / "personal-assistant").resolve())
        base["proposed_command"] = _shell_command(
            [
                "python3", str(replacement), "--archive-dir", "<verified-release-assets-directory>",
                "--version", release_version, "--hermes-home", str(hermes_home),
            ]
        )
    return base


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", choices=("stable", "pilot"), default="stable")
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY)
    parser.add_argument("--home", default=os.path.expanduser("~"))
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", "~/.hermes"))
    parser.add_argument("--gh", default="gh")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    gh = shutil.which(args.gh) if os.path.sep not in args.gh else args.gh
    if not gh or not Path(gh).exists():
        result = {"ok": False, "status": "github_access_missing", "reason": "gh executable unavailable"}
        print(json.dumps(result, separators=(",", ":")) if args.json else json.dumps(result, indent=2))
        return 2
    try:
        result = check_release(
            gh=gh,
            repository=args.repo,
            channel=args.channel,
            system_home=Path(args.home).expanduser().resolve(),
            hermes_home=Path(args.hermes_home).expanduser().resolve(),
        )
    except GithubUnavailable as exc:
        result = {"ok": False, "status": "github_access_missing", "reason": str(exc)}
        print(json.dumps(result, separators=(",", ":")) if args.json else json.dumps(result, indent=2))
        return 2
    print(json.dumps(result, separators=(",", ":")) if args.json else json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
