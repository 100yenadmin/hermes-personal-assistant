#!/usr/bin/env python3
"""Verify the frozen v0.4.0-rc.1 build before publication recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.verify_release_assets import verify as verify_release_assets


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(args: argparse.Namespace) -> dict[str, object]:
    directory = Path(args.dir).resolve()
    run = json.loads(Path(args.run_json).read_text(encoding="utf-8"))
    jobs = json.loads(Path(args.jobs_json).read_text(encoding="utf-8"))
    repository = run.get("repository") if isinstance(run.get("repository"), dict) else {}
    if (
        run.get("id") != args.run_id
        or run.get("head_sha") != args.run_head_sha
        or run.get("conclusion") != "failure"
        or repository.get("full_name") != args.repository
    ):
        raise ValueError("original workflow run identity or result mismatch")
    job_items = jobs.get("jobs") if isinstance(jobs.get("jobs"), list) else []
    job_results = {
        item.get("name"): item.get("conclusion") for item in job_items if isinstance(item, dict)
    }
    if job_results != {"classify": "success", "build": "success", "publish": "failure"}:
        raise ValueError("original workflow job results mismatch")

    stem = f"travel-agent-skills-{args.version}"
    expected = {
        f"{stem}.tgz": args.archive_sha256,
        f"{stem}.tgz.sha256": args.checksum_sha256,
        f"{stem}.manifest.json": args.manifest_sha256,
        "release-notes.md": args.notes_sha256,
    }
    actual = {path.name for path in directory.iterdir() if path.is_file()}
    if actual != set(expected):
        raise ValueError("original artifact file set mismatch")
    for name, digest in expected.items():
        if sha256(directory / name) != digest:
            raise ValueError(f"original artifact digest mismatch: {name}")

    release = verify_release_assets(directory, args.version)
    if release.get("source_sha") != args.source_sha:
        raise ValueError("original artifact source commit mismatch")
    return {
        "ok": True,
        "repository": args.repository,
        "run_id": args.run_id,
        "source_sha": args.source_sha,
        "version": args.version,
        "archive_sha256": args.archive_sha256,
        "executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--run-json", required=True)
    parser.add_argument("--jobs-json", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-head-sha", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--checksum-sha256", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--notes-sha256", required=True)
    args = parser.parse_args()
    try:
        result = verify(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
