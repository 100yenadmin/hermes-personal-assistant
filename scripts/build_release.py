#!/usr/bin/env python3
"""Build deterministic PA release bytes and an external integrity manifest."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "travel-agent-skills"
NATIVE_ID = "personal-assistant"
HERMES_PINS = [
    "49c6d4a9e0dddc64d6333c5b1fcc9d911463a8fd",
    "6e2b8e070d28b1a3381a3fb290b6b8d6cce13cef",
]
LOCAL_CONFIG_NAMES = {
    "clients.json", "daily_ops.config.json", "daily_ops.state.json", "location.json",
}
ROOT_FILES = {
    "AGENTS.md", "CHANGELOG.md", "CONTRIBUTING.md", "README.md", "VERSION", "__init__.py",
    "after-install.md", "codex-plugin.json", "openclaw.plugin.json", "plugin.yaml", "requirements.txt",
}
RELEASE_CONFIG_FILES = {"config/pa-action-gateway-policy.example.json"}
PREFIXES = ("docs/", "evals/", "hooks/", "personal_assistant/", "releases/", "scripts/", "skills/", "support-control/")


def git(*arguments: str) -> str:
    completed = subprocess.run(["git", "-C", str(ROOT), *arguments], text=True, capture_output=True)
    if completed.returncode != 0:
        raise ValueError(f"git {' '.join(arguments[:2])} failed")
    return completed.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def top_level_yaml(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line[0].isspace() or ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def validate_version(version: str) -> None:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?", version):
        raise ValueError(f"VERSION is not a supported release version: {version!r}")
    plugin = top_level_yaml(ROOT / "plugin.yaml")
    if plugin.get("name") != NATIVE_ID or plugin.get("version") != version:
        raise ValueError("plugin.yaml native ID or version does not match VERSION")
    manifests = [
        ROOT / "openclaw.plugin.json",
        ROOT / "codex-plugin.json",
        ROOT / "skills/travel-action-pack-manifest/openclaw.plugin.json",
        ROOT / "skills/travel-action-pack-manifest/codex-plugin.json",
    ]
    for path in manifests:
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(data.get("version")) != version:
            raise ValueError(f"{path.relative_to(ROOT)} version does not match VERSION")
    release_path = ROOT / "releases" / version / "manifest.json"
    data = json.loads(release_path.read_text(encoding="utf-8"))
    if data.get("version") != version or data.get("native_id") != NATIVE_ID:
        raise ValueError("release manifest identity or version does not match VERSION")
    if not isinstance(data.get("source_commit"), str) or not data["source_commit"].strip():
        raise ValueError("release manifest source_commit must be meaningful and non-null")


def selected_files() -> list[str]:
    tracked = [item for item in git("ls-files", "-z").split("\0") if item]
    selected = []
    for relative in tracked:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        if "tests" in Path(relative).parts:
            # Tests and provider doubles are repository-only fixtures.  They
            # must not enter the shipped archive or its privacy scan.
            continue
        if Path(relative).name in LOCAL_CONFIG_NAMES:
            continue
        if relative in ROOT_FILES or relative in RELEASE_CONFIG_FILES or relative.startswith(PREFIXES):
            selected.append(relative)
    required = {
        "VERSION", "__init__.py", "after-install.md", "plugin.yaml",
        "config/pa-action-gateway-policy.example.json",
        "scripts/check_release.py", "scripts/probe_installed_version.py",
        "scripts/reinstall_pinned.py",
    }
    missing = sorted(required - set(selected))
    if missing:
        raise ValueError(f"required release files are missing: {missing}")
    return sorted(selected)


def content_digest(stage: Path, files: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((stage / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def normalized_tar(stage: Path, archive: Path, package_dir: str, epoch: int) -> None:
    paths = sorted(stage.rglob("*"), key=lambda path: path.relative_to(stage).as_posix())
    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as output:
                root_info = tarfile.TarInfo(package_dir)
                root_info.type = tarfile.DIRTYPE
                root_info.mode = 0o755
                root_info.mtime = epoch
                root_info.uid = root_info.gid = 0
                root_info.uname = root_info.gname = "root"
                output.addfile(root_info)
                for path in paths:
                    relative = path.relative_to(stage).as_posix()
                    info = output.gettarinfo(str(path), arcname=f"{package_dir}/{relative}")
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    info.mtime = epoch
                    info.mode = 0o755 if path.is_dir() or path.stat().st_mode & stat.S_IXUSR else 0o644
                    if path.is_file():
                        with path.open("rb") as handle:
                            output.addfile(info, handle)
                    else:
                        output.addfile(info)


def build(output_dir: Path, requested_version: str | None) -> dict[str, object]:
    status = git("status", "--porcelain", "--untracked-files=all")
    if status:
        raise ValueError("release input is dirty; commit the exact candidate before packaging")
    source_sha = git("rev-parse", "HEAD")
    epoch = int(git("show", "-s", "--format=%ct", "HEAD"))
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if requested_version and requested_version != version:
        raise ValueError("--version must match the checked-in VERSION")
    validate_version(version)
    files = selected_files()
    package_dir = f"{PACKAGE_NAME}-{version}"
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pa-release-build-") as temporary:
        stage = Path(temporary)
        for relative in files:
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        digest = content_digest(stage, files)
        internal = {
            "package": PACKAGE_NAME,
            "native_id": NATIVE_ID,
            "version": version,
            "source_commit": source_sha,
            "source_state": "clean",
            "content_digest_algorithm": "sha256(relative_path_nul_bytes_nul, sorted paths)",
            "content_digest": digest,
        }
        (stage / ".travel-agent-skills-release.json").write_text(
            json.dumps(internal, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        pii_check = subprocess.run(
            ["bash", str(stage / "scripts" / "check_release_pii.sh"), str(stage)],
            text=True,
            capture_output=True,
        )
        if pii_check.returncode != 0:
            raise ValueError("release privacy scan rejected the staged archive")
        archive = output_dir / f"{package_dir}.tgz"
        normalized_tar(stage, archive, package_dir, epoch)
    archive_digest = sha256(archive)
    checksum = output_dir / f"{archive.name}.sha256"
    checksum.write_text(f"{archive_digest}  {archive.name}\n", encoding="utf-8")
    external = output_dir / f"{package_dir}.manifest.json"
    external.write_text(json.dumps({
        "schema_version": 1,
        "package": PACKAGE_NAME,
        "native_id": NATIVE_ID,
        "version": version,
        "source_sha": source_sha,
        "source_date_epoch": epoch,
        "artifact": {"name": archive.name, "sha256": archive_digest},
        "checksum_asset": checksum.name,
        "tested_hermes_pins": HERMES_PINS,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "archive": str(archive),
        "checksum": str(checksum),
        "manifest": str(external),
        "sha256": archive_digest,
        "source_sha": source_sha,
        "version": version,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version")
    parser.add_argument("--output-dir", default="dist")
    args = parser.parse_args()
    output = Path(args.output_dir)
    if not output.is_absolute():
        output = ROOT / output
    try:
        result = build(output.resolve(), args.version)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
