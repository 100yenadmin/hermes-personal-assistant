#!/usr/bin/env python3
"""Disposable native Git install/reinstall lifecycle acceptance for Personal Assistant."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml


PLUGIN_ID = "personal-assistant"
CONFIG_NAMES = (
    "clients.json",
    "daily_ops.config.json",
    "daily_ops.state.json",
    "location.json",
)


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
        expect: int = 0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
    if completed.returncode != expect:
        raise RuntimeError(
            f"command returned {completed.returncode}, expected {expect}: {command[0]} {command[1:3]}"
        )
    return completed


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(command: list[str], cwd: Path) -> str:
    return run(["git", *command], cwd=cwd).stdout.strip()


def make_source(source: Path, destination: Path, include_working_tree: bool) -> tuple[str, str]:
    if include_working_tree:
        destination.mkdir()
        listed = run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=source
        ).stdout.split("\0")
        for relative in (item for item in listed if item):
            src = source / relative
            if not src.is_file() or src.is_symlink():
                continue
            dst = destination / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        git(["init", "-q"], destination)
        git(["config", "user.name", "PA lifecycle fixture"], destination)
        git(["config", "user.email", "pa-lifecycle@example.invalid"], destination)
        git(["add", "."], destination)
        git(["commit", "-q", "-m", "synthetic lifecycle revision one"], destination)
    else:
        run(["git", "clone", "--quiet", "--no-hardlinks", str(source), str(destination)])
        git(["checkout", "--detach", "HEAD"], destination)
        git(["config", "user.name", "PA lifecycle fixture"], destination)
        git(["config", "user.email", "pa-lifecycle@example.invalid"], destination)
    first = git(["rev-parse", "HEAD"], destination)
    (destination / "release-lifecycle-marker.txt").write_text("synthetic revision two\n", encoding="utf-8")
    git(["add", "release-lifecycle-marker.txt"], destination)
    git(["commit", "-q", "-m", "synthetic lifecycle revision two"], destination)
    second = git(["rev-parse", "HEAD"], destination)
    return first, second


def write_calendar(path: Path) -> None:
    path.write_text(
        "BEGIN:VCALENDAR\nVERSION:2.0\n"
        "BEGIN:VEVENT\nUID:timed@example.invalid\nDTSTART:20260920T090000Z\n"
        "DTEND:20260920T100000Z\nSUMMARY:Synthetic timed event\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:allday@example.invalid\nDTSTART;VALUE=DATE:20260921\n"
        "DTEND;VALUE=DATE:20260922\nSUMMARY:Synthetic all-day event\nEND:VEVENT\n"
        "END:VCALENDAR\n",
        encoding="utf-8",
    )


def internal_probe(home: Path, hermes_root: Path, ics: Path, trip_id: str) -> dict[str, object]:
    os.environ["HERMES_HOME"] = str(home)
    os.environ.pop("TRAVEL_LEDGER_DB", None)
    os.environ.pop("HERMES_SAFE_MODE", None)
    sys.path.extend(str(path) for path in (hermes_root / "venv" / "lib").glob("python*/site-packages"))
    sys.path.insert(0, str(hermes_root))
    os.chdir(home)
    from hermes_cli.plugins import PluginManager
    from tools.registry import registry

    manager = PluginManager(scope_key=str(home))
    manager.discover_and_load()
    loaded = manager._plugins.get(PLUGIN_ID)
    if not loaded or not loaded.enabled or loaded.error:
        raise RuntimeError("native plugin did not load as enabled")
    tool = registry.get_entry("pa", scope=str(home))
    if not tool:
        raise RuntimeError("pa tool was not registered")

    def call(arguments: dict[str, object]) -> object:
        value = json.loads(registry.dispatch("pa", arguments, scope=str(home)))
        if isinstance(value, dict) and value.get("error"):
            raise RuntimeError("native pa dispatch returned an error")
        return value

    recipes = call({"operation": "recipes"})
    imported = call({
        "operation": "trip_import",
        "data": {"trip_id": trip_id, "ics_path": str(ics), "title": "Synthetic lifecycle"},
    })
    replay = call({
        "operation": "trip_import",
        "data": {"trip_id": trip_id, "ics_path": str(ics), "title": "Synthetic lifecycle"},
    })
    exported = call({
        "operation": "export",
        "data": {
            "trip_id": trip_id,
            "output_dir": str(home / "exports" / trip_id),
            "overwrite": True,
        },
    })
    from icalendar import Calendar

    events = Calendar.from_ical(Path(exported["calendar"]).read_bytes()).walk("VEVENT")
    if imported != replay or imported["timed"] != 1 or imported["all_day"] != 1 or len(events) != 2:
        raise RuntimeError("timed/all-day import, replay, or export contract failed")
    skills = sorted(manager._plugin_skills)
    if "personal-assistant:personal-assistant" not in skills or "personal-assistant:travel-ledger" not in skills:
        raise RuntimeError("qualified Personal Assistant skills were not discovered")
    manager.unload(PLUGIN_ID)
    if registry.get_entry("pa", scope=str(home)) is not None:
        raise RuntimeError("pa tool remained registered after unload")
    return {
        "pa_registered": True,
        "qualified_personal_assistant": True,
        "qualified_travel_ledger": True,
        "recipes": len(recipes),
        "timed": imported["timed"],
        "all_day": imported["all_day"],
        "replay": "PASS",
        "exported_events": len(events),
        "loaded": True,
        "exercised": True,
    }


def write_local_config(installed: Path, revision: str) -> dict[str, str]:
    for index, name in enumerate(CONFIG_NAMES):
        (installed / name).write_text(
            json.dumps({"synthetic": True, "revision": revision, "index": index}) + "\n",
            encoding="utf-8",
        )
    return {name: sha256(installed / name) for name in CONFIG_NAMES}


def state_receipt(paths: dict[str, Path]) -> dict[str, str]:
    return {name: sha256(path) for name, path in paths.items()}


def plugin_activation(home: Path) -> dict[str, bool]:
    value = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}
    plugins = value.get("plugins") if isinstance(value, dict) else {}
    plugins = plugins if isinstance(plugins, dict) else {}
    enabled = plugins.get("enabled") if isinstance(plugins.get("enabled"), list) else []
    disabled = plugins.get("disabled") if isinstance(plugins.get("disabled"), list) else []
    return {"enabled": PLUGIN_ID in enabled, "disabled": PLUGIN_ID in disabled}


def read_metadata(home: Path) -> dict[str, object]:
    value = json.loads((home / "plugins" / ".install-metadata.json").read_text(encoding="utf-8"))
    record = value.get(PLUGIN_ID)
    if not isinstance(record, dict):
        raise RuntimeError("native install metadata is missing")
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes", default="hermes")
    parser.add_argument("--hermes-root", required=True)
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--include-working-tree", action="store_true")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    hermes_root = Path(args.hermes_root).resolve()
    receipt_path = Path(args.receipt).resolve()

    with tempfile.TemporaryDirectory(prefix="pa-release-lifecycle-") as temporary:
        root = Path(temporary)
        fixture_source = root / "source"
        first_ref, second_ref = make_source(source, fixture_source, args.include_working_tree)
        tested_pa_head = git(["rev-parse", "HEAD"], source)
        fixture_delta = git(["diff", "--name-only", first_ref, second_ref], fixture_source).splitlines()
        if not args.include_working_tree and first_ref != tested_pa_head:
            raise RuntimeError("clean fixture baseline is not bound to the tested PA head")
        if fixture_delta != ["release-lifecycle-marker.txt"]:
            raise RuntimeError("synthetic fixture revision contains an unexplained source delta")
        source_url = fixture_source.as_uri()
        home = root / "profile"
        (home / "plugins").mkdir(parents=True)
        (home / "config.yaml").write_text(
            "plugins:\n  enabled: []\n  scan_on_install: false\n", encoding="utf-8"
        )
        env = dict(os.environ)
        env["HERMES_HOME"] = str(home)
        install = run([
            args.hermes, "plugins", "install", source_url, "--ref", first_ref, "--no-enable"
        ], env=env)
        first_metadata = read_metadata(home)
        if first_metadata.get("revision") != first_ref or first_metadata.get("pinned") is not True:
            raise RuntimeError("first native install was not pinned to the requested revision")
        activation_after_install = plugin_activation(home)
        if activation_after_install["enabled"]:
            raise RuntimeError("--no-enable changed the profile to activate the plugin")
        run([args.hermes, "plugins", "enable", PLUGIN_ID, "--no-allow-tool-override"], env=env)
        ics = root / "synthetic.ics"
        write_calendar(ics)
        first_probe = internal_probe(home, hermes_root, ics, "release-lifecycle-first")
        ledger = home / "state" / "travel-ledger" / "travel.sqlite"
        ledger_before = sha256(ledger)

        state_paths = {
            "sessions": home / "state" / "synthetic-sessions.json",
            "memory": home / "state" / "synthetic-memory.json",
            "jobs": home / "state" / "synthetic-jobs.json",
        }
        for name, path in state_paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"accepted": name}) + "\n", encoding="utf-8")

        installed = home / "plugins" / PLUGIN_ID
        config_before = write_local_config(installed, "first")
        reinstall = run([
            sys.executable,
            str(installed / "scripts" / "reinstall_pinned.py"),
            "--source", source_url,
            "--ref", second_ref,
            "--hermes", args.hermes,
            "--hermes-home", str(home),
            "--json",
        ], env=env)
        second_metadata = read_metadata(home)
        if second_metadata.get("revision") != second_ref or second_metadata.get("pinned") is not True:
            raise RuntimeError("second native install was not pinned to the requested revision")
        config_after = {name: sha256((home / "plugins" / PLUGIN_ID / name)) for name in CONFIG_NAMES}
        if config_before != config_after:
            raise RuntimeError("local PA configuration changed during pinned reinstall")
        if ledger_before != sha256(ledger):
            raise RuntimeError("profile ledger changed during pinned reinstall")
        reinstall_result = json.loads(reinstall.stdout)
        if not reinstall_result.get("rollback_snapshot"):
            raise RuntimeError("pinned reinstall did not retain a prior-package rollback snapshot")

        pinned_update = subprocess.run(
            [args.hermes, "plugins", "update", PLUGIN_ID], env=env, text=True, capture_output=True
        )
        if pinned_update.returncode == 0 or "pinned" not in (pinned_update.stdout + pinned_update.stderr).lower():
            raise RuntimeError("native pinned update did not refuse with a truthful pinned message")
        run([args.hermes, "plugins", "disable", PLUGIN_ID], env=env)
        run([args.hermes, "plugins", "enable", PLUGIN_ID, "--no-allow-tool-override"], env=env)
        second_probe = internal_probe(home, hermes_root, ics, "release-lifecycle-second")
        probe_script = home / "plugins" / PLUGIN_ID / "scripts" / "probe_installed_version.py"
        installed_probe = run([
            sys.executable, str(probe_script), "--json", "--home", str(root / "system-home"),
            "--hermes-home", str(home),
        ], env=env)
        installed_status = json.loads(installed_probe.stdout)
        if installed_status.get("source_kind") != "native_git" or installed_status.get("observed_commit") != second_ref:
            raise RuntimeError("installed probe did not identify the native Git revision")

        accepted_git_config = write_local_config(home / "plugins" / PLUGIN_ID, "accepted-after-git")
        accepted_git_ledger = sha256(ledger)
        accepted_external_state = state_receipt(state_paths)
        rollback_git = run([
            sys.executable,
            str(home / "plugins" / PLUGIN_ID / "scripts" / "reinstall_pinned.py"),
            "--rollback", str(reinstall_result["rollback_snapshot"]),
            "--hermes-home", str(home),
            "--json",
        ], env=env)
        if read_metadata(home).get("revision") != first_ref:
            raise RuntimeError("rollback did not restore the prior native package identity")
        if accepted_git_config != {
            name: sha256(home / "plugins" / PLUGIN_ID / name) for name in CONFIG_NAMES
        }:
            raise RuntimeError("rollback rewound accepted local PA configuration")
        if sha256(ledger) != accepted_git_ledger or state_receipt(state_paths) != accepted_external_state:
            raise RuntimeError("rollback rewound state outside the plugin package")

        repeat = run([
            sys.executable,
            str(home / "plugins" / PLUGIN_ID / "scripts" / "reinstall_pinned.py"),
            "--source", source_url,
            "--ref", first_ref,
            "--hermes", args.hermes,
            "--hermes-home", str(home),
            "--json",
        ], env=env)
        if read_metadata(home).get("revision") != first_ref:
            raise RuntimeError("repeat same-revision replacement changed package identity")
        if accepted_git_config != {
            name: sha256(home / "plugins" / PLUGIN_ID / name) for name in CONFIG_NAMES
        } or sha256(ledger) != accepted_git_ledger:
            raise RuntimeError("repeat same-revision replacement changed accepted state")

        assets = root / "release-assets"
        package_source = fixture_source if args.include_working_tree else source
        archive_source_sha = git(["rev-parse", "HEAD"], package_source)
        version = (package_source / "VERSION").read_text(encoding="utf-8").strip()
        package = run([
            "bash", str(package_source / "scripts" / "package_release.sh"), "--output-dir", str(assets)
        ], cwd=package_source)
        archive = run([
            sys.executable,
            str(home / "plugins" / PLUGIN_ID / "scripts" / "reinstall_pinned.py"),
            "--archive-dir", str(assets),
            "--version", version,
            "--hermes-home", str(home),
            "--json",
        ], env=env)
        archive_result = json.loads(archive.stdout)
        archive_probe_script = home / "plugins" / PLUGIN_ID / "scripts" / "probe_installed_version.py"
        archive_probe = json.loads(run([
            sys.executable, str(archive_probe_script), "--json", "--home", str(root / "system-home"),
            "--hermes-home", str(home),
        ], env=env).stdout)
        if (
            archive_probe.get("source_kind") != "native_archive"
            or archive_probe.get("observed_commit") != archive_source_sha
            or archive_probe.get("package_path") != str((home / "plugins" / PLUGIN_ID).resolve())
        ):
            raise RuntimeError(
                "archive replacement identity mismatch: "
                + json.dumps({
                    "expected_commit": archive_source_sha,
                    "expected_path": str((home / "plugins" / PLUGIN_ID).resolve()),
                    "observed_commit": archive_probe.get("observed_commit"),
                    "observed_path": archive_probe.get("package_path"),
                    "source_kind": archive_probe.get("source_kind"),
                }, sort_keys=True)
            )

        archive_runtime = internal_probe(
            home, hermes_root, ics, "release-lifecycle-archive-accepted"
        )
        accepted_archive_config = write_local_config(
            home / "plugins" / PLUGIN_ID, "accepted-after-archive"
        )
        accepted_archive_ledger = sha256(ledger)
        accepted_archive_state = state_receipt(state_paths)
        rollback_archive = run([
            sys.executable,
            str(home / "plugins" / PLUGIN_ID / "scripts" / "reinstall_pinned.py"),
            "--rollback", str(archive_result["rollback_snapshot"]),
            "--hermes-home", str(home),
            "--json",
        ], env=env)
        restored_probe_script = home / "plugins" / PLUGIN_ID / "scripts" / "probe_installed_version.py"
        restored_probe = json.loads(run([
            sys.executable, str(restored_probe_script), "--json", "--home", str(root / "system-home"),
            "--hermes-home", str(home),
        ], env=env).stdout)
        if restored_probe.get("source_kind") != "native_git" or restored_probe.get("observed_commit") != first_ref:
            raise RuntimeError("archive rollback did not restore the retained Git package identity")
        if accepted_archive_config != {
            name: sha256(home / "plugins" / PLUGIN_ID / name) for name in CONFIG_NAMES
        }:
            raise RuntimeError("archive rollback rewound accepted local configuration")
        if sha256(ledger) != accepted_archive_ledger or state_receipt(state_paths) != accepted_archive_state:
            raise RuntimeError("archive rollback rewound accepted external state")

        receipt = {
            "claim": "disposable native pinned install and explicit pinned reinstall lifecycle",
            "hermes_source_commit": git(["rev-parse", "HEAD"], hermes_root),
            "tested_pa_head": tested_pa_head,
            "fixture_baseline_binding": (
                "exact-tested-pa-head" if first_ref == tested_pa_head else "working-tree-synthetic-commit"
            ),
            "first_fixture_revision": first_ref,
            "second_fixture_revision": second_ref,
            "second_fixture_delta": fixture_delta,
            "first_install_pinned": True,
            "first_install_left_disabled": not activation_after_install["enabled"],
            "activation_after_first_install": activation_after_install,
            "first_probe": first_probe,
            "second_probe": second_probe,
            "preserved_config": sorted(config_before),
            "preserved_config_sha256": config_after,
            "ledger_sha256_unchanged": True,
            "pinned_update_refused": True,
            "disable_reenable": "PASS",
            "installed_probe_source_kind": installed_status["source_kind"],
            "installed_probe_revision": installed_status["observed_commit"],
            "reinstall_result": reinstall_result,
            "git_rollback_result": json.loads(rollback_git.stdout),
            "repeat_same_revision_result": json.loads(repeat.stdout),
            "archive_build": json.loads(package.stdout),
            "archive_source_sha": archive_source_sha,
            "archive_replacement_result": archive_result,
            "archive_probe_source_kind": archive_probe["source_kind"],
            "archive_probe_revision": archive_probe["observed_commit"],
            "archive_runtime": archive_runtime,
            "archive_rollback_result": json.loads(rollback_archive.stdout),
            "rollback_preserved_accepted_config": True,
            "rollback_preserved_ledger_sessions_memory_jobs": True,
            "repeat_same_revision_preserved_state": True,
            "live_profile_changed": False,
            "provider_actions": False,
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(receipt, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
