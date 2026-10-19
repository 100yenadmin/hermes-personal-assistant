#!/usr/bin/env python3
"""Narrow isolated native-loader/export check. No provider calls or live profile reads."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import tarfile

try:
    from .native_paths import resolve_cli_paths
except ImportError:
    from native_paths import resolve_cli_paths

parser = argparse.ArgumentParser()
parser.add_argument("--hermes", required=True)
parser.add_argument("--ics", required=True)
parser.add_argument("--guide")
parser.add_argument("--full", action="store_true")
parser.add_argument("--receipt", required=True)
parser.add_argument("--archive", help="Validate the built archive rather than the checkout")
args = resolve_cli_paths(parser.parse_args())
package = Path(__file__).resolve().parents[1]
from icalendar import Calendar

with tempfile.TemporaryDirectory(prefix="pa-isolated-") as temporary:
    home = Path(temporary)
    if args.archive:
        extracted = home / "archive"
        extracted.mkdir()
        with tarfile.open(args.archive, "r:gz") as archive:
            archive.extractall(extracted, filter="data")
        roots = list(extracted.iterdir())
        assert len(roots) == 1 and roots[0].is_dir(), "archive must contain one package"
        package = roots[0]
        assert (package / "__init__.py").is_file(), "archive lacks native registration"
    os.environ["HERMES_HOME"] = str(home)
    os.environ.pop("TRAVEL_LEDGER_DB", None)
    os.environ.pop("HERMES_SAFE_MODE", None)
    (home / "plugins").mkdir()
    (home / "plugins/personal-assistant").symlink_to(package, target_is_directory=True)
    (home / "config.yaml").write_text("plugins:\n  enabled: [personal-assistant]\n")
    os.chdir(home)
    # Reuse the installed build's libraries without installing into its venv.
    sys.path.extend(str(p) for p in (Path(args.hermes) / "venv/lib").glob("python*/site-packages"))
    sys.path.insert(0, args.hermes)
    from hermes_cli.plugins import PluginManager
    from tools.registry import registry
    manager = PluginManager(scope_key=str(home))
    manager.discover_and_load()
    loaded = manager._plugins.get("personal-assistant")
    assert loaded and loaded.enabled and not loaded.error, "native plugin failed to load"
    tool = registry.get_entry("pa", scope=str(home))
    assert tool, "PA tool absent"
    def call(arguments):
        result = json.loads(registry.dispatch("pa", arguments, scope=str(home)))
        assert not (isinstance(result, dict) and result.get("error")), "native tool pipeline returned an error"
        return result
    assert "personal-assistant:travel-ledger" in manager._plugin_skills
    recipes = call({"operation": "recipes"})
    assert len(recipes) == 8
    assert all(recipe["skill"] in manager._plugin_skills for recipe in recipes)
    source = Calendar.from_ical(Path(args.ics).read_bytes())
    events = source.walk("VEVENT")
    if not args.full:
        events = [next(e for e in events if isinstance(e.decoded("DTSTART"), dt.datetime)),
                  next(e for e in events if not isinstance(e.decoded("DTSTART"), dt.datetime))]
    selected = Calendar()
    selected.add("version", "2.0")
    for event in events:
        selected.add_component(event)
    input_path = home / "input.ics"
    input_path.write_bytes(selected.to_ical())
    data = {"trip_id": "native-check", "ics_path": str(input_path), "title": "Trip export acceptance"}
    if args.guide:
        data["guide_path"] = args.guide
    imported = call({"operation": "trip_import", "data": data})
    replay = call({"operation": "trip_import", "data": data})
    assert imported == replay
    result = call({"operation": "export", "data": {"trip_id": "native-check", "output_dir": str(home / "export")}})
    exported = Calendar.from_ical(Path(result["calendar"]).read_bytes()).walk("VEVENT")
    assert len(exported) == len(events)
    for before, after in zip(events, exported):
        for key in ("UID", "DTSTART", "DTEND"):
            if key in before:
                assert before.decoded(key) == after.decoded(key), f"changed {key}"
        for key in ("SUMMARY", "LOCATION", "URL"):
            if key in before:
                assert str(before[key]) == str(after[key]), f"changed shared {key}"
    guide_coverage = None
    if args.guide:
        reference = Path(result["reference"]).read_text()
        expected = ("## Onboarding guide", "## Accommodation guide", "## Coworking guide")
        guide_coverage = all(section in reference for section in expected)
        assert guide_coverage
        assert "WKND" in reference.upper() and "11:00" in reference and "13:00" in reference
    names = set(manager._plugin_skills)
    manager.unload("personal-assistant")
    assert registry.get_entry("pa", scope=str(home)) is None
    manager.discover_and_load(force=True)
    assert names == set(manager._plugin_skills)
    assert registry.get_entry("pa", scope=str(home))
    receipt = {"claim": "isolated native registry dispatch and static export", "events": len(events), "registry_result_contract": "PASS",
               "timed": imported["timed"], "all_day": imported["all_day"],
               "replay": "PASS", "native_unload_reload": "PASS", "uid_and_boundaries": "PASS",
               "source_sha256": hashlib.sha256(Path(args.ics).read_bytes()).hexdigest(),
               "calendar_sha256": hashlib.sha256(Path(result["calendar"]).read_bytes()).hexdigest(),
               "qualified_skills": len(names), "recipes_discoverable": len(recipes),
               "three_guide_sections": guide_coverage, "live_profile_changed": False}
    if args.archive:
        receipt["archive_sha256"] = hashlib.sha256(Path(args.archive).read_bytes()).hexdigest()
        receipt["source"] = "built archive"
    Path(args.receipt).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
