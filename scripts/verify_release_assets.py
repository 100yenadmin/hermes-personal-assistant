#!/usr/bin/env python3
"""Verify a PA archive, checksum, and external manifest without executing them."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(directory: Path, version: str) -> dict[str, object]:
    stem = f"travel-agent-skills-{version}"
    archive = directory / f"{stem}.tgz"
    checksum = directory / f"{stem}.tgz.sha256"
    manifest_path = directory / f"{stem}.manifest.json"
    for path in (archive, checksum, manifest_path):
        if not path.is_file():
            raise ValueError(f"missing release asset: {path.name}")
    digest = sha256(archive)
    checksum_parts = checksum.read_text(encoding="utf-8").strip().split()
    if checksum_parts != [digest, archive.name]:
        raise ValueError("checksum must contain the archive digest and portable basename only")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != version or manifest.get("native_id") != "personal-assistant":
        raise ValueError("external manifest identity or version mismatch")
    artifact = manifest.get("artifact") if isinstance(manifest.get("artifact"), dict) else {}
    if artifact.get("name") != archive.name or artifact.get("sha256") != digest:
        raise ValueError("external manifest artifact digest mismatch")
    expected_root = PurePosixPath(stem)
    required = {
        expected_root / "__init__.py",
        expected_root / "after-install.md",
        expected_root / "plugin.yaml",
        expected_root / ".travel-agent-skills-release.json",
    }
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        names = {PurePosixPath(member.name) for member in members}
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != stem:
                raise ValueError(f"unsafe archive member: {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"unsupported archive member type: {member.name}")
        plugin_member = source.getmember(f"{stem}/plugin.yaml")
        plugin_handle = source.extractfile(plugin_member)
        plugin_text = plugin_handle.read().decode("utf-8") if plugin_handle else ""
        if "pre_tool_call" in plugin_text:
            required.add(expected_root / "config/pa-action-gateway-policy.example.json")
        missing = sorted(str(path) for path in required - names)
        if missing:
            raise ValueError(f"archive lacks required files: {missing}")
        internal_member = source.getmember(f"{stem}/.travel-agent-skills-release.json")
        handle = source.extractfile(internal_member)
        internal = json.loads(handle.read()) if handle else {}
    if internal.get("source_commit") != manifest.get("source_sha") or internal.get("version") != version:
        raise ValueError("internal and external release identities disagree")
    return {
        "ok": True,
        "version": version,
        "archive": archive.name,
        "sha256": digest,
        "source_sha": manifest.get("source_sha"),
        "tested_hermes_pins": manifest.get("tested_hermes_pins"),
        "executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        result = verify(Path(args.dir).resolve(), args.version)
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
