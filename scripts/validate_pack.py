#!/usr/bin/env python3
import ast
import json
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
PACKAGE_NAME = "travel-agent-skills"
DISPLAY_NAME = "Personal Assistant Plugin"
VERSION = (ROOT / "VERSION").read_text().strip()
COMPONENT_ID = "addon:travel-agent-skills"
LEGACY_ALIASES = {
    "openclaw-hermes-travel-action-pack",
    "personal-assistant-travel",
    "addon:travel-action-pack",
}
REQUIRED_SKILLS = {
    "agent-wallet-payments",
    "airline-check-in",
    "browserbase-checkout-lane",
    "daily-ops",
    "food-delivery-to-hotel",
    "hotel-check-in",
    "itinerary-intake",
    "provider-message-refund",
    "restaurant-discovery",
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
}


def fail(errors, msg):
    errors.append(msg)


def observer_import_errors(path):
    """Inspect imports at every AST depth, including optional certifi guards."""
    tree = ast.parse(path.read_text())
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    allowed = {"personal_assistant.state", "personal_assistant.privacy", "personal_assistant.observe_sources", "personal_assistant.trip_math"}
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level > 1:
                base = "." * node.level + base  # Outside the package: never an allowed observer import.
            elif node.level:
                base = "personal_assistant" + ("." + base if base else "")
            names = [base + "." + item.name for item in node.names] if base == "personal_assistant" else [base]
        else:
            continue
        for name in names:
            if name in allowed or name.split(".")[0] in sys.stdlib_module_names:
                continue
            current, guarded = node, False
            while current in parents:
                parent = parents[current]
                if isinstance(parent, ast.Try) and current in parent.body:
                    for handler in parent.handlers:
                        types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
                        guarded |= any(isinstance(t, ast.Name) and t.id in {"ImportError", "ModuleNotFoundError"} for t in types)
                current = parent
            if name != "certifi" or not guarded:
                errors.append(f"{path.name}:{node.lineno}: forbidden observer import {name}")
    return errors


def main():
    errors = []
    for name in ("observe.py", "observe_sources.py"):
        path = ROOT / "personal_assistant" / name
        if not path.is_file():
            fail(errors, f"missing observer: {name}")
        else:
            errors.extend(observer_import_errors(path))
    shim = ROOT / "scripts/pa_observe.py"
    if not shim.is_file() or len(shim.read_text().splitlines()) > 10:
        fail(errors, "observer shim must exist and have at most 10 lines")
    for name in sorted(REQUIRED_SKILLS):
        if not (SKILLS / name / "SKILL.md").exists():
            fail(errors, f"missing required skill: {name}")

    manifest_paths = [
        ROOT / "openclaw.plugin.json",
        ROOT / "codex-plugin.json",
        SKILLS / "travel-action-pack-manifest" / "openclaw.plugin.json",
        SKILLS / "travel-action-pack-manifest" / "codex-plugin.json",
    ]
    for manifest_path in manifest_paths:
        if not manifest_path.exists():
            fail(errors, f"missing manifest: {manifest_path}")
            continue
        data = json.loads(manifest_path.read_text())
        if data.get("version") != VERSION:
            fail(errors, f"{manifest_path} has wrong version {data.get('version')}")
        if manifest_path.name == "openclaw.plugin.json":
            if data.get("id") != PACKAGE_NAME:
                fail(errors, f"{manifest_path} has wrong id {data.get('id')}")
            if data.get("name") != DISPLAY_NAME:
                fail(errors, f"{manifest_path} has wrong name {data.get('name')}")
            support = data.get("supportControl") or {}
            if support.get("componentId") != COMPONENT_ID:
                fail(errors, f"{manifest_path} has wrong support-control component id {support.get('componentId')}")
            aliases = set(support.get("legacyAliases") or [])
            if aliases != LEGACY_ALIASES:
                fail(errors, f"{manifest_path} has wrong legacy aliases {sorted(aliases)}")
        if manifest_path.name == "openclaw.plugin.json":
            manifest_skills = {Path(s).name for s in data.get("skills", [])}
            missing = sorted(REQUIRED_SKILLS - manifest_skills)
            if missing:
                fail(errors, f"{manifest_path} missing skills: {missing}")
            if "travel-action-pack-manifest" in str(manifest_path):
                bad_paths = [s for s in data.get("skills", []) if not s.startswith("../")]
                if bad_paths:
                    fail(errors, f"{manifest_path} has embedded manifest paths that are not relative to skill dir: {bad_paths}")
            else:
                bad_paths = [s for s in data.get("skills", []) if not s.startswith("skills/")]
                if bad_paths:
                    fail(errors, f"{manifest_path} has root manifest paths that are not package-root relative: {bad_paths}")
        if manifest_path.name == "codex-plugin.json":
            if data.get("name") != PACKAGE_NAME:
                fail(errors, f"{manifest_path} has wrong package name {data.get('name')}")
            interface = data.get("interface") or {}
            if interface.get("displayName") != DISPLAY_NAME:
                fail(errors, f"{manifest_path} has wrong display name {interface.get('displayName')}")
            expected = "../" if "travel-action-pack-manifest" in str(manifest_path) else "./skills/"
            if data.get("skills") != expected:
                fail(errors, f"{manifest_path} has skills={data.get('skills')!r}, expected {expected!r}")

    required_files = [
        ROOT / "AGENTS.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "__init__.py",
        ROOT / "after-install.md",
        ROOT / "plugin.yaml",
        ROOT / "VERSION",
        ROOT / "CHANGELOG.md",
        ROOT / ".github" / "workflows" / "validate.yml",
        ROOT / ".github" / "workflows" / "release.yml",
        ROOT / ".github" / "pull_request_template.md",
        ROOT / "docs" / "release-process.md",
        ROOT / "docs" / "support-control-version-contract.md",
        ROOT / "support-control" / "component.json",
        ROOT / "releases" / VERSION / "manifest.json",
        ROOT / "scripts" / "package_release.sh",
        ROOT / "scripts" / "build_release.py",
        ROOT / "scripts" / "check_release.py",
        ROOT / "scripts" / "check_pa_release_lifecycle.py",
        ROOT / "scripts" / "publish_release.py",
        ROOT / "scripts" / "probe_installed_version.py",
        ROOT / "scripts" / "reinstall_pinned.py",
        ROOT / "scripts" / "release_contract.py",
        ROOT / "scripts" / "verify_release_assets.py",
    ]
    for path in required_files:
        if not path.exists():
            fail(errors, f"missing productization file: {path}")

    version_text = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else ""
    if version_text != VERSION:
        fail(errors, f"VERSION is {version_text!r}, expected {VERSION!r}")

    native_manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text()) or {}
    requirements = {
        line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if native_manifest.get("name") != "personal-assistant":
        fail(errors, "plugin.yaml must keep native ID personal-assistant")
    if str(native_manifest.get("version")) != VERSION:
        fail(errors, "plugin.yaml version does not match VERSION")
    modes = (native_manifest.get("config_schema") or {}).get("modes", {})
    if modes.get("type") != "dict" or modes.get("default") != {} or not modes.get("description"):
        fail(errors, "plugin.yaml modes must be an inert dict setting")
    for path in SKILLS.glob("cos-*/SKILL.md"):
        header = path.read_text().split("---", 2)
        front = yaml.safe_load(header[1]) if len(header) == 3 else {}
        if (front or {}).get("metadata", {}).get("hermes", {}).get("pa_mode") != "chief_of_staff":
            fail(errors, f"{path.parent.name} must declare the chief_of_staff mode marker")
    if set(native_manifest.get("provides_tools") or []) != {"pa", "pa_delivery_ack", "pa_call"}:
        fail(errors, "plugin.yaml must declare pa, pa_call and conditional pa_delivery_ack tools")
    if set(native_manifest.get("python_dependencies") or []) != requirements:
        fail(errors, "plugin.yaml python_dependencies must exactly match requirements.txt")

    release_manifest = json.loads((ROOT / "releases" / VERSION / "manifest.json").read_text())
    if release_manifest.get("native_id") != "personal-assistant":
        fail(errors, "release manifest native ID is not personal-assistant")
    if not isinstance(release_manifest.get("source_commit"), str) or not release_manifest["source_commit"].strip():
        fail(errors, "release manifest source_commit must be meaningful and non-null")

    component = json.loads((ROOT / "support-control" / "component.json").read_text())
    if component.get("component_id") != COMPONENT_ID:
        fail(errors, f"support-control component id is {component.get('component_id')}")
    if component.get("package_name") != PACKAGE_NAME:
        fail(errors, f"support-control package name is {component.get('package_name')}")
    missing_component_skills = sorted(REQUIRED_SKILLS - set(component.get("required_skills") or []))
    if missing_component_skills:
        fail(errors, f"support-control component missing skills: {missing_component_skills}")

    text = "\n".join(p.read_text(errors="ignore") for p in SKILLS.rglob("*.md"))
    stale_terms = ["skills-only-wave-2", "Wave 2 skill-only", "version\": \"0.2.1\"", "wave2", "operator-observed beta"]
    for term in stale_terms:
        if term in text:
            fail(errors, f"stale term remains in skill markdown: {term}")
    if "beta" in text.lower():
        fail(errors, "generic beta wording remains in skill markdown")

    required_phrases = [
        "travel-ledger",
        "Browserbase",
        "reattach",
        "payment readiness",
        "final-state confirmation",
        "provider-visible",
    ]
    all_text = text + "\n" + (ROOT / "openclaw.plugin.json").read_text()
    for phrase in required_phrases:
        if phrase not in all_text:
            fail(errors, f"missing required phrase: {phrase}")

    canaries = ROOT / "evals" / "v0.1-canaries.json"
    if not canaries.exists():
        fail(errors, "missing v0.1 canaries")
    else:
        data = json.loads(canaries.read_text())
        if data.get("version") != "0.1.0":
            fail(errors, "legacy v0.1 canary identity must remain pinned")
        if len(data.get("canaries", [])) < 7:
            fail(errors, "expected at least 7 canaries")

    disallowed_terms = [
        "Had" + "ley",
        "10" + "03",
        "Ral" + "eigh",
        "Vietnam" + " trip",
        "vietnam" + "-2026",
        "Lobster travel card" + " ending 1234",
    ]
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(part in {".git", "dist", ".venv", ".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        if path.suffix not in {".md", ".json", ".py", ".sh", ".yml", ".yaml", ".toml", ".txt"} and path.name not in {"VERSION"}:
            continue
        content = path.read_text(errors="ignore")
        for term in disallowed_terms:
            if term in content:
                fail(errors, f"customer-specific fixture term {term!r} remains in {rel}")

    ledger = SKILLS / "travel-ledger" / "scripts" / "travel_ledger.py"
    if not ledger.exists():
        fail(errors, "missing travel ledger helper")

    if errors:
        print(json.dumps({"ok": False, "errors": errors}, indent=2))
        return 1
    print(json.dumps({"ok": True, "required_skills": sorted(REQUIRED_SKILLS)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
