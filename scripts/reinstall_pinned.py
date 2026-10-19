#!/usr/bin/env python3
"""Explicit approved replacement and rollback for the native PA package."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import uuid

import yaml

try:
    from .verify_release_assets import verify as verify_release_assets
except ImportError:
    from verify_release_assets import verify as verify_release_assets


PLUGIN_ID = "personal-assistant"
CONFIG_NAMES = (
    "clients.json",
    "daily_ops.config.json",
    "daily_ops.state.json",
    "location.json",
)
FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
SNAPSHOT_ID = re.compile(r"^[0-9TZ-]+-[0-9a-f]{12}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_plugin_dir(home: Path, plugin_id: str) -> Path:
    plugins = (home / "plugins").resolve()
    target = plugins / plugin_id
    if target.is_symlink():
        raise ValueError(f"refusing symlinked plugin directory: {target}")
    resolved = target.resolve(strict=False)
    if resolved.parent != plugins or resolved.name != plugin_id:
        raise ValueError(f"plugin target escapes the profile plugin directory: {resolved}")
    return target


def _collect_config(target: Path) -> dict[str, dict[str, object]]:
    saved: dict[str, dict[str, object]] = {}
    for name in CONFIG_NAMES:
        path = target / name
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"refusing non-regular local configuration: {path}")
        saved[name] = {
            "bytes": path.read_bytes(),
            "mode": path.stat().st_mode & 0o777,
            "sha256": _sha256(path),
        }
    return saved


def _write_backup(backup: Path, saved: dict[str, dict[str, object]]) -> None:
    backup.mkdir(mode=0o700)
    for name, record in saved.items():
        path = backup / name
        path.write_bytes(record["bytes"])
        path.chmod(int(record["mode"]))


def _restore_config(target: Path, saved: dict[str, dict[str, object]]) -> None:
    for name, record in saved.items():
        path = target / name
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise ValueError(f"refusing to overwrite non-regular destination: {path}")
        path.write_bytes(record["bytes"])
        path.chmod(int(record["mode"]))
        if _sha256(path) != record["sha256"]:
            raise RuntimeError(f"restored configuration digest mismatch: {name}")


def _activation_state(home: Path) -> dict[str, bool]:
    config = home / "config.yaml"
    try:
        value = yaml.safe_load(config.read_text(encoding="utf-8")) if config.exists() else {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"could not read profile plugin activation settings: {exc}") from exc
    plugins = value.get("plugins") if isinstance(value, dict) else {}
    plugins = plugins if isinstance(plugins, dict) else {}
    enabled = plugins.get("enabled") if isinstance(plugins.get("enabled"), list) else []
    disabled = plugins.get("disabled") if isinstance(plugins.get("disabled"), list) else []
    return {"enabled": PLUGIN_ID in enabled, "disabled": PLUGIN_ID in disabled}


def _metadata_path(home: Path) -> Path:
    return home / "plugins" / ".install-metadata.json"


def _read_metadata(home: Path) -> dict[str, object]:
    path = _metadata_path(home)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read native install metadata: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("native install metadata must be a JSON object")
    return value


def _write_metadata(home: Path, value: dict[str, object]) -> None:
    path = _metadata_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f"{path.name}.tmp-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _set_metadata_record(home: Path, record: object) -> None:
    metadata = _read_metadata(home)
    if isinstance(record, dict):
        metadata[PLUGIN_ID] = record
    else:
        metadata.pop(PLUGIN_ID, None)
    _write_metadata(home, metadata)


def _package_identity(target: Path, home: Path) -> dict[str, object]:
    metadata = _read_metadata(home).get(PLUGIN_ID)
    release_path = target / ".travel-agent-skills-release.json"
    release = {}
    if release_path.is_file():
        try:
            release = json.loads(release_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            release = {}
    manifest = {}
    manifest_path = target / "plugin.yaml"
    if manifest_path.is_file():
        try:
            value = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            manifest = value if isinstance(value, dict) else {}
        except (OSError, yaml.YAMLError):
            manifest = {}
    git_revision = None
    if (target / ".git").exists():
        completed = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"], text=True, capture_output=True
        )
        if completed.returncode == 0 and FULL_SHA.fullmatch(completed.stdout.strip()):
            git_revision = completed.stdout.strip().lower()
    return {
        "source_kind": "native_git" if git_revision else "native_archive" if release else "native_copy",
        "version": str(manifest.get("version") or "") or None,
        "source_commit": git_revision or release.get("source_commit"),
        "install_metadata": metadata if isinstance(metadata, dict) else None,
    }


def _snapshot_root(home: Path) -> Path:
    return home / "plugin-backups" / PLUGIN_ID


def _create_snapshot(home: Path, target: Path, activation: dict[str, bool]) -> tuple[str, Path]:
    root = _snapshot_root(home)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot_id = (
        dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-" + uuid.uuid4().hex[:12]
    )
    snapshot = root / snapshot_id
    snapshot.mkdir(mode=0o700)

    def ignore_local_config(_directory: str, names: list[str]) -> set[str]:
        return set(names) & set(CONFIG_NAMES)

    shutil.copytree(target, snapshot / "package", symlinks=True, ignore=ignore_local_config)
    record = {
        "schema_version": 1,
        "plugin_id": PLUGIN_ID,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "activation": activation,
        "package": _package_identity(target, home),
        "local_config_excluded": list(CONFIG_NAMES),
        "state_outside_plugin_tree_excluded": True,
    }
    manifest = snapshot / "snapshot.json"
    manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest.chmod(0o600)
    return snapshot_id, snapshot


def _snapshot(home: Path, snapshot_id: str) -> tuple[Path, dict[str, object]]:
    if not SNAPSHOT_ID.fullmatch(snapshot_id):
        raise ValueError("invalid rollback snapshot identifier")
    root = _snapshot_root(home).resolve()
    path = (root / snapshot_id).resolve()
    if path.parent != root or not (path / "package").is_dir():
        raise ValueError(f"rollback snapshot is unavailable: {snapshot_id}")
    try:
        manifest = json.loads((path / "snapshot.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"rollback snapshot metadata is invalid: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("plugin_id") != PLUGIN_ID:
        raise ValueError("rollback snapshot identity mismatch")
    return path, manifest


def _verify_activation(home: Path, expected: dict[str, bool]) -> None:
    observed = _activation_state(home)
    if observed != expected:
        raise RuntimeError(
            "profile plugin activation settings changed during package replacement; "
            "restore them explicitly before activation"
        )


def _swap_package(target: Path, staged: Path, home: Path, metadata_record: object) -> None:
    plugins = target.parent
    displaced = Path(tempfile.mkdtemp(prefix=".pa-displaced-", dir=plugins)) / PLUGIN_ID
    os.replace(target, displaced)
    try:
        os.replace(staged, target)
        _set_metadata_record(home, metadata_record)
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        os.replace(displaced, target)
        raise
    shutil.rmtree(displaced.parent)


def reinstall(source: str, revision: str, hermes: str, home: Path) -> dict[str, object]:
    if not FULL_SHA.fullmatch(revision):
        raise ValueError("--ref must be a full 40-character commit SHA")
    target = _safe_plugin_dir(home, PLUGIN_ID)
    if not target.is_dir():
        raise ValueError(f"native plugin is not installed at {target}")
    saved = _collect_config(target)
    activation = _activation_state(home)
    snapshot_id, snapshot = _create_snapshot(home, target, activation)
    config_recovery = Path(tempfile.mkdtemp(prefix=".pa-config-recovery-", dir=home))
    config_recovery.chmod(0o700)
    _write_backup(config_recovery / "config", saved)
    command = [
        hermes,
        "plugins",
        "install",
        source,
        "--force",
        "--ref",
        revision.lower(),
        "--no-enable",
    ]
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    try:
        completed = subprocess.run(command, env=env, text=True, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError(
                "Hermes pinned reinstall failed; the native installer retained the prior tree. "
                f"Prior package snapshot retained as {snapshot_id}"
            )
        _restore_config(_safe_plugin_dir(home, PLUGIN_ID), saved)
        _verify_activation(home, activation)
    except Exception:
        print(f"Prior package snapshot retained as {snapshot_id}", file=sys.stderr)
        print(f"Configuration recovery retained at {config_recovery}", file=sys.stderr)
        raise
    shutil.rmtree(config_recovery)
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "revision": revision.lower(),
        "preserved_config": sorted(saved),
        "preserved_activation": activation,
        "rollback_snapshot": snapshot_id,
        "rollback_snapshot_path": str(snapshot),
        "config_recovery_retained": False,
        "activation_changed": False,
        "gateway_restarted": False,
        "ledger_copied": False,
    }


def replace_archive(directory: Path, version: str, home: Path) -> dict[str, object]:
    target = _safe_plugin_dir(home, PLUGIN_ID)
    if not target.is_dir():
        raise ValueError(f"native plugin is not installed at {target}")
    directory = directory.expanduser().resolve()
    verified = verify_release_assets(directory, version)
    activation = _activation_state(home)
    saved = _collect_config(target)
    snapshot_id, snapshot = _create_snapshot(home, target, activation)
    archive = directory / f"travel-agent-skills-{version}.tgz"
    staging_parent = Path(tempfile.mkdtemp(prefix=".pa-archive-", dir=target.parent))
    try:
        with tarfile.open(archive, "r:gz") as source:
            source.extractall(staging_parent, filter="data")
        staged = staging_parent / f"travel-agent-skills-{version}"
        if not staged.is_dir():
            raise ValueError("verified archive did not extract to its declared package root")
        _restore_config(staged, saved)
        _swap_package(target, staged, home, None)
        _verify_activation(home, activation)
    except Exception:
        print(f"Prior package snapshot retained as {snapshot_id}", file=sys.stderr)
        raise
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "version": version,
        "source_commit": verified.get("source_sha"),
        "source_kind": "native_archive",
        "package_path": str(target),
        "preserved_config": sorted(saved),
        "preserved_activation": activation,
        "rollback_snapshot": snapshot_id,
        "rollback_snapshot_path": str(snapshot),
        "activation_changed": False,
        "gateway_restarted": False,
        "ledger_copied": False,
    }


def rollback(snapshot_id: str, home: Path) -> dict[str, object]:
    target = _safe_plugin_dir(home, PLUGIN_ID)
    if not target.is_dir():
        raise ValueError(f"native plugin is not installed at {target}")
    snapshot, manifest = _snapshot(home, snapshot_id)
    current_config = _collect_config(target)
    activation = _activation_state(home)
    recovery_id, recovery = _create_snapshot(home, target, activation)
    staging_parent = Path(tempfile.mkdtemp(prefix=".pa-rollback-", dir=target.parent))
    staged = staging_parent / PLUGIN_ID
    try:
        shutil.copytree(snapshot / "package", staged, symlinks=True)
        _restore_config(staged, current_config)
        package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
        _swap_package(target, staged, home, package.get("install_metadata"))
        _verify_activation(home, activation)
    except Exception:
        print(f"Current package recovery snapshot retained as {recovery_id}", file=sys.stderr)
        raise
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "restored_snapshot": snapshot_id,
        "restored_package": manifest.get("package"),
        "current_config_preserved": sorted(current_config),
        "activation_preserved": activation,
        "recovery_snapshot": recovery_id,
        "recovery_snapshot_path": str(recovery),
        "state_outside_plugin_tree_changed": False,
        "gateway_restarted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source")
    parser.add_argument("--ref")
    parser.add_argument("--archive-dir")
    parser.add_argument("--version")
    parser.add_argument("--rollback")
    parser.add_argument("--hermes", default="hermes")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", "~/.hermes"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        home = Path(args.hermes_home).expanduser().resolve()
        modes = sum(bool(item) for item in (args.source or args.ref, args.archive_dir or args.version, args.rollback))
        if modes != 1:
            raise ValueError("choose exactly one of Git replacement, archive replacement, or rollback")
        if args.rollback:
            result = rollback(args.rollback, home)
        elif args.archive_dir or args.version:
            if not args.archive_dir or not args.version:
                raise ValueError("archive replacement requires --archive-dir and --version")
            result = replace_archive(Path(args.archive_dir), args.version, home)
        else:
            if not args.source or not args.ref:
                raise ValueError("Git replacement requires --source and --ref")
            result = reinstall(args.source, args.ref, args.hermes, home)
    except (OSError, ValueError, RuntimeError) as exc:
        payload = {"ok": False, "error": str(exc)}
        print(json.dumps(payload) if args.json else f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")) if args.json else json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
