#!/usr/bin/env python3
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess

from packaging.requirements import Requirement


COMPONENT_ID = "addon:travel-agent-skills"
PACKAGE_NAME = "travel-agent-skills"
NATIVE_ID = "personal-assistant"
LEGACY_ALIASES = [
    "openclaw-hermes-travel-action-pack",
    "personal-assistant-travel",
    "addon:travel-action-pack",
]
REQUIRED_SKILLS = [
    "agent-wallet-payments",
    "airline-check-in",
    "browserbase-checkout-lane",
    "daily-ops",
    "food-delivery-to-hotel",
    "hotel-check-in",
    "itinerary-intake",
    "provider-message-refund",
    "restaurant-reservations",
    "rideshare-booking",
    "travel-action-orchestrator",
    "travel-action-pack-references",
    "travel-approval-packet",
    "travel-email-calendar",
    "travel-connectivity",
    "travel-ledger",
    "travel-mode",
    "trip-nudges",
    "tripcom-flight-hotel-booking",
    "weather-trip-briefing",
]


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def read_yaml(path):
    try:
        import yaml
    except ImportError:
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}


def candidate_roots(home, hermes_home):
    workspace = home / ".openclaw" / "workspace"
    return [
        ("native", hermes_home / "plugins" / NATIVE_ID),
        ("legacy", workspace / "packages" / PACKAGE_NAME),
        ("legacy", workspace / "packages" / "openclaw-hermes-travel-action-pack"),
        ("legacy", home / ".openclaw" / "skills" / "travel-action-pack-manifest"),
        ("legacy", workspace / "skills" / "travel-action-pack-manifest"),
    ]


def package_manifest(root):
    native = root / "plugin.yaml"
    if native.exists():
        data = read_yaml(native)
        if data:
            return native, data
    for name in ("openclaw.plugin.json", "codex-plugin.json"):
        path = root / name
        if path.exists():
            data = read_json(path)
            if data:
                return path, data
    return None, {}


def release_info(root):
    candidates = [root / ".travel-agent-skills-release.json"]
    version_file = root / "VERSION"
    if version_file.exists():
        version = version_file.read_text(errors="ignore").strip()
        if version:
            candidates.append(root / "releases" / version / "manifest.json")
    releases = root / "releases"
    if releases.exists():
        candidates.extend(sorted(releases.glob("*/manifest.json"), reverse=True))
    for path in candidates:
        if path.exists():
            data = read_json(path)
            if data:
                return path, data
    return None, {}


def skill_presence(root, home=None, kind=None):
    roots = [root / "skills"] if root else []
    if kind == "legacy" and home is not None:
        roots.extend([home / ".openclaw" / "skills", home / ".openclaw" / "workspace" / "skills"])
    return {
        skill: any((candidate / skill / "SKILL.md").is_file() for candidate in roots)
        for skill in REQUIRED_SKILLS
    }


def install_metadata(hermes_home):
    path = hermes_home / "plugins" / ".install-metadata.json"
    data = read_json(path)
    record = data.get(NATIVE_ID) if isinstance(data.get(NATIVE_ID), dict) else {}
    return path, record


def enabled_state(hermes_home):
    path = hermes_home / "config.yaml"
    if not path.exists():
        return None, path
    data = read_yaml(path)
    plugins = data.get("plugins") if isinstance(data.get("plugins"), dict) else {}
    enabled = plugins.get("enabled") if isinstance(plugins, dict) else None
    return (NATIVE_ID in enabled, path) if isinstance(enabled, list) else (None, path)


def dependency_status(requirements):
    present, missing = [], []
    for raw in requirements:
        try:
            requirement = Requirement(raw)
            version = importlib.metadata.version(requirement.name)
            (present if not requirement.specifier or version in requirement.specifier else missing).append(raw)
        except (importlib.metadata.PackageNotFoundError, ValueError):
            missing.append(raw)
    return sorted(present), sorted(missing)


def checkout_state(root):
    # Prevent git status from refreshing/writing the index during diagnostics.
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True, capture_output=True, env=env, timeout=10,
        )
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            text=True, capture_output=True, env=env, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if head.returncode != 0 or status.returncode != 0:
        return None, None
    return head.stdout.strip() or None, bool(status.stdout.strip())


def probe(home, hermes_home):
    chosen_kind = None
    chosen_root = None
    manifest_path = None
    manifest = {}
    for kind, root in candidate_roots(home, hermes_home):
        path, data = package_manifest(root)
        if data:
            chosen_kind, chosen_root, manifest_path, manifest = kind, root, path, data
            break

    raw_dependencies = manifest.get("python_dependencies")
    if raw_dependencies is None:
        raw_dependencies = []
    if not isinstance(raw_dependencies, list):
        return {
            "ok": False,
            "installed": chosen_root is not None,
            "install_ok": False,
            "invalid_reason": f"python_dependencies must be a list (got {type(raw_dependencies).__name__})",
        }

    rel_path, rel = release_info(chosen_root) if chosen_root else (None, {})
    metadata_path, metadata = install_metadata(hermes_home)
    enabled, config_path = enabled_state(hermes_home)
    skills = skill_presence(chosen_root, home, chosen_kind)
    missing_skills = sorted(name for name, ok in skills.items() if not ok)
    declared_dependencies = [
        item.strip() for item in raw_dependencies
        if isinstance(item, str) and item.strip()
    ]
    dependencies_present, dependencies_missing = dependency_status(declared_dependencies)
    observed_id = manifest.get("name") if chosen_kind == "native" else (manifest.get("id") or manifest.get("name"))
    observed_version = str(manifest.get("version") or "") or None
    observed_commit = rel.get("source_commit")
    source_kind = "not_installed"
    source = None
    pinned = None
    checkout_commit = checkout_dirty = metadata_matches_checkout = None
    source_identity_reason = None
    if chosen_kind == "native":
        if metadata and chosen_root and (chosen_root / ".git").exists():
            source_kind = "native_git"
            source = metadata.get("source")
            pinned = metadata.get("pinned") if isinstance(metadata.get("pinned"), bool) else None
            observed_commit = metadata.get("revision")
            checkout_commit, checkout_dirty = checkout_state(chosen_root)
            if checkout_commit:
                metadata_matches_checkout = (
                    isinstance(observed_commit, str)
                    and observed_commit.lower() == checkout_commit.lower()
                )
            if checkout_dirty:
                source_identity_reason = "local_edits"
            elif metadata_matches_checkout is False:
                source_identity_reason = "source_mismatch"
            elif checkout_commit is None or checkout_dirty is None:
                source_identity_reason = "checkout_unavailable"
        elif rel_path and rel_path.name == ".travel-agent-skills-release.json":
            source_kind = "native_archive"
            source = None
            pinned = None
            observed_commit = rel.get("source_commit")
        else:
            source_kind = "native_copy"
            source = metadata.get("source") if metadata else None
            pinned = metadata.get("pinned") if isinstance(metadata.get("pinned"), bool) else None
            observed_commit = None
    elif chosen_kind == "legacy":
        source_kind = "legacy_openclaw"

    installed = chosen_root is not None
    identity_ok = observed_id == NATIVE_ID if chosen_kind == "native" else observed_id in {PACKAGE_NAME, *LEGACY_ALIASES}
    install_ok = bool(installed and observed_version and identity_ok and not missing_skills)
    if source_identity_reason in {"local_edits", "source_mismatch"}:
        install_ok = False
    # Local config and state files are untracked, so only tracked edits or a moved HEAD
    # make the checkout's identity unknown; an unreadable checkout keeps the metadata answer.
    source_identity_known = bool(isinstance(observed_commit, str) and observed_commit)
    if source_identity_reason in {"local_edits", "source_mismatch"}:
        source_identity_known = False
    dependencies_ok = not dependencies_missing
    return {
        "ok": bool(install_ok and dependencies_ok),
        "component_id": COMPONENT_ID,
        "native_id": NATIVE_ID,
        "package_name": PACKAGE_NAME,
        "installed": installed,
        "enabled": enabled,
        "loaded": None,
        "exercised": None,
        "runtime_evidence": "loaded and exercised are not observable from this read-only disk probe",
        "install_ok": install_ok,
        "dependencies_ok": dependencies_ok,
        "source_kind": source_kind,
        "source": source,
        "pinned": pinned,
        "observed_id": observed_id,
        "observed_version": observed_version,
        "observed_commit": observed_commit,
        "package_path": str(chosen_root) if chosen_root else None,
        "manifest_path": str(manifest_path) if manifest_path else None,
        "release_info_path": str(rel_path) if rel_path else None,
        "install_metadata_path": str(metadata_path),
        "install_metadata_present": bool(metadata),
        "source_identity_known": source_identity_known,
        "checkout_commit": checkout_commit,
        "checkout_dirty": checkout_dirty,
        "metadata_matches_checkout": metadata_matches_checkout,
        "source_identity_reason": source_identity_reason,
        "migration_required": source_kind == "legacy_openclaw",
        "config_path": str(config_path),
        "legacy_alias": observed_id in LEGACY_ALIASES,
        "legacy_aliases": LEGACY_ALIASES,
        "required_skills_missing": missing_skills,
        "required_skills_present": sorted(name for name, ok in skills.items() if ok),
        "python_dependencies_declared": declared_dependencies,
        "python_dependencies_present": dependencies_present,
        "python_dependencies_missing": dependencies_missing,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--home", default=os.path.expanduser("~"), help="System home for legacy lookup")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", "~/.hermes"))
    args = parser.parse_args()
    result = probe(Path(args.home).expanduser().resolve(), Path(args.hermes_home).expanduser().resolve())

    if args.json:
        print(json.dumps(result, separators=(",", ":")))
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
