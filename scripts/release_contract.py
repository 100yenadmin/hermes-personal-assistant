#!/usr/bin/env python3
"""Validate PR release intent and classify an exact merged release PR."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
IMPACT = re.compile(r"(?im)^Release impact:\s*(none|publish)\s*$")
LINK = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|related)\s+#\d+\b")
NOTES = re.compile(r"(?ims)^## Release notes\s*$\n(.*?)(?=^##\s|\Z)")


def git(*arguments: str) -> str:
    completed = subprocess.run(["git", "-C", str(ROOT), *arguments], text=True, capture_output=True)
    if completed.returncode != 0:
        raise ValueError(f"git {' '.join(arguments[:2])} failed")
    return completed.stdout.strip()


def text_at(revision: str, path: str) -> str:
    return git("show", f"{revision}:{path}").strip()


def parse_body(body: str) -> tuple[str, str]:
    impact_matches = IMPACT.findall(body)
    if len(impact_matches) != 1:
        raise ValueError("PR body must contain exactly one 'Release impact: none|publish' line")
    if not LINK.search(body):
        raise ValueError("PR body must link an issue with Closes/Fixes/Resolves/Related #N")
    notes_match = NOTES.search(body)
    notes = re.sub(r"<!--.*?-->", "", notes_match.group(1), flags=re.DOTALL).strip() if notes_match else ""
    return impact_matches[0].lower(), notes


def validate_release_files(revision: str, version: str) -> None:
    plugin = text_at(revision, "plugin.yaml")
    if not re.search(rf"(?m)^name:\s*personal-assistant\s*$", plugin):
        raise ValueError("release plugin.yaml native ID is not personal-assistant")
    if not re.search(rf"(?m)^version:\s*{re.escape(version)}\s*$", plugin):
        raise ValueError("release plugin.yaml version does not match VERSION")
    manifest_text = text_at(revision, f"releases/{version}/manifest.json")
    manifest = json.loads(manifest_text)
    if manifest.get("version") != version or manifest.get("native_id") != "personal-assistant":
        raise ValueError("release manifest identity or version does not match VERSION")
    if not isinstance(manifest.get("source_commit"), str) or not manifest["source_commit"].strip():
        raise ValueError("release manifest source_commit must be meaningful and non-null")
    version_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?", version)
    if not version_match:
        raise ValueError("release version must be major.minor.patch with an optional prerelease suffix")
    if tuple(map(int, version_match.groups())) < (0, 10, 0):
        return
    scorecards = {}
    for extension in ("json", "md"):
        path = f"releases/{version}/scorecard.{extension}"
        try:
            scorecards[extension] = text_at(revision, path)
        except ValueError as exc:
            raise ValueError(f"release scorecard missing: {path}") from exc
    try:
        scorecard = json.loads(scorecards["json"])
    except json.JSONDecodeError as exc:
        raise ValueError("release scorecard.json is not valid JSON") from exc
    if not isinstance(scorecard, dict):
        raise ValueError("release scorecard.json must be a JSON object")
    if type(scorecard.get("schema")) is not int or scorecard["schema"] != 1:
        raise ValueError("scorecard schema must be 1")
    if scorecard.get("version") != version:
        raise ValueError("scorecard version does not match the release version")
    commit = scorecard.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("scorecard commit must be a 40-hex string")
    if commit != manifest.get("reviewed_implementation_commit"):
        raise ValueError("scorecard commit does not match the manifest's reviewed_implementation_commit")
    areas = scorecard.get("areas")
    if not isinstance(areas, (list, dict)) or len(areas) != 14:
        raise ValueError("scorecard areas must have 14 entries")
    if not scorecards["md"].startswith(f"# PA {version} VA scorecard"):
        raise ValueError("scorecard.md must start with the release's VA scorecard heading")


def validate_pull_request(event: dict[str, object], *, require_merged: bool = False) -> dict[str, object]:
    pull = event.get("pull_request")
    if not isinstance(pull, dict):
        raise ValueError("event is not a pull_request event")
    if require_merged and pull.get("merged") is not True:
        raise ValueError("release classification requires a merged pull request")
    body = str(pull.get("body") or "")
    impact, notes = parse_body(body)
    base = pull.get("base") if isinstance(pull.get("base"), dict) else {}
    head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
    head_sha = str((pull.get("merge_commit_sha") if require_merged else None) or head.get("sha") or "")
    base_sha = git("rev-parse", f"{head_sha}^1") if require_merged and head_sha else str(base.get("sha") or "")
    if require_merged and str(base.get("ref") or "") != "main":
        raise ValueError("release publication requires a pull request merged to main")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", base_sha) or not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        raise ValueError("event lacks exact base/head commit identities")
    base_version = text_at(base_sha, "VERSION")
    head_version = text_at(head_sha, "VERSION")
    changed = set(git("diff", "--name-only", base_sha, head_sha).splitlines())
    if impact == "none":
        if base_version != head_version:
            raise ValueError("VERSION changed but Release impact is none")
    else:
        if base_version == head_version:
            raise ValueError("Release impact is publish but VERSION did not change")
        if not notes or notes.lower() in {"none", "n/a", "not applicable"}:
            raise ValueError("release PR must contain substantive release notes")
        required = {"VERSION", "CHANGELOG.md", f"releases/{head_version}/manifest.json"}
        missing = sorted(required - changed)
        if missing:
            raise ValueError(f"release PR does not change required release files: {missing}")
        validate_release_files(head_sha, head_version)
    return {
        "ok": True,
        "impact": impact,
        "publish": impact == "publish",
        "base_sha": base_sha,
        "head_sha": head_sha,
        "base_version": base_version,
        "version": head_version,
        "release_notes": notes,
    }


def write_output(path: str | None, result: dict[str, object]) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"publish={'true' if result['publish'] else 'false'}\n")
        handle.write(f"version={result['version']}\n")
        handle.write(f"source_sha={result['head_sha']}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("pr", "merge", "notes"))
    parser.add_argument("--event", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    parser.add_argument("--output")
    args = parser.parse_args()
    if not args.event:
        print(json.dumps({"ok": False, "error": "event path is required"}))
        return 1
    try:
        event = json.loads(Path(args.event).read_text(encoding="utf-8"))
        result = validate_pull_request(event, require_merged=args.mode in {"merge", "notes"})
        if args.mode == "merge":
            write_output(args.github_output, result)
        elif args.mode == "notes":
            if not result["publish"] or not args.output:
                raise ValueError("notes mode requires a publishing release PR and --output")
            Path(args.output).write_text(str(result["release_notes"]).strip() + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "release_notes"}, separators=(",", ":")))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
