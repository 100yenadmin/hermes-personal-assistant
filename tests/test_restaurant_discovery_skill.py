"""Packaging/routing contracts only; live restaurant quality needs the saved evals."""
import json
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/restaurant-discovery/SKILL.md"


def test_discovery_skill_is_read_only_and_has_local_references():
    text = SKILL.read_text()
    front = yaml.safe_load(text.split("---", 2)[1])
    assert front["name"] == "restaurant-discovery"
    assert front["description"].startswith("Use when")
    assert front["metadata"]["openclaw"]["skillKey"] == "restaurant-discovery"
    assert front["metadata"]["hermes"]["category"] == "travel"
    assert "read-only" in text
    assert "personal-assistant:restaurant-reservations" in text
    assert "no bookings" in text
    references = re.findall(r"`(references/[a-z-]+\.md)`", text)
    assert set(references) == {"references/local-platforms.md", "references/evidence-and-evals.md"}
    for reference in references:
        assert (SKILL.parent / reference).is_file()


def test_both_entry_routes_name_discovery_before_booking():
    for name in ("restaurant-reservations", "travel-mode"):
        text = (ROOT / "skills" / name / "SKILL.md").read_text()
        assert "personal-assistant:restaurant-discovery" in text
    reservations = (ROOT / "skills/restaurant-reservations/SKILL.md").read_text()
    assert "final-state confirmation" in reservations
    assert "Whenever you stop before step 8" in reservations


def test_legacy_inventories_include_discovery_without_version_change():
    for path in (ROOT / "openclaw.plugin.json",
                 ROOT / "skills/travel-action-pack-manifest/openclaw.plugin.json"):
        manifest = json.loads(path.read_text())
        assert "restaurant-discovery" in {Path(item).name for item in manifest["skills"]}
        assert manifest["version"] == (ROOT / "VERSION").read_text().strip()
    from scripts import probe_installed_version, validate_pack
    component = json.loads((ROOT / "support-control/component.json").read_text())
    for inventory in (probe_installed_version.REQUIRED_SKILLS,
                      validate_pack.REQUIRED_SKILLS, component["required_skills"]):
        assert "restaurant-discovery" in inventory


def test_discovery_reads_saved_preferences_without_owner_record_id_coupling():
    text = SKILL.read_text()
    assert 'pa(operation="profile", data={"action":"list","kind":"preference"})' in text
    assert "active" in text and "filed" in text and "proposed" in text
    assert "before searching" in text
    assert "runtime lacks" in text
    assert "pref:loves-lamb" not in text
    assert "pref:restaurant-photos-menu" not in text


def test_discovery_contract_keeps_unknowns_and_freshness_explicit():
    text = SKILL.read_text()
    for phrase in ("Bib Gourmand", "last 6 months", "last order", "capture date",
                   "publication date", "unknown", "closed", "one pick plus two alternatives"):
        assert phrase in text
    platforms = (SKILL.parent / "references/local-platforms.md").read_text()
    for phrase in ("Tabelog", "Naver", "Kakao", "Blue Ribbon", "iFoodie", "羊肉爐", "ビブグルマン", "블루리본"):
        assert phrase in platforms


def test_saved_live_evals_have_resolvable_citations_and_dated_photo_provenance():
    """Artifact integrity only: the separate reviewer still checks source truth."""
    directory = ROOT / "evals/restaurant-discovery/2026-10-27"
    ledger = json.loads((directory / "sources.json").read_text())
    sources = {item["id"]: item["url"] for item in ledger["sources"]}
    photos = json.loads((directory / "photos.json").read_text())
    assert len(photos) == 9
    assert sum(len(items) for items in photos.values()) == 18
    cases = {
        "luodong-tuesday-lamb.md": ("tw-pick", "tw-alt1", "tw-alt2"),
        "osaka-namba-bib.md": ("jp-pick", "jp-alt1", "jp-alt2"),
        "seoul-local-platforms.md": ("kr-pick", "kr-alt1", "kr-alt2"),
    }
    for filename, groups in cases.items():
        text = (directory / filename).read_text()
        assert "{{photos:" not in text
        assert "## Condensed live tool transcript" in text
        assert "## Recovery readback" in text
        assert "## Self-grade against #71" in text
        body, block = text.split("## Sources", 1)
        cited = {int(value) for value in re.findall(r"\[(\d+)\]", body)}
        rendered = {int(key): url for key, url in re.findall(r"^\[(\d+)\] (\S+)$", block, re.M)}
        assert rendered == {key: sources[key] for key in cited}
        output = body.split("## Final user-facing output", 1)[1].split("## Self-grade", 1)[0]
        for line in output.splitlines():
            if line.startswith("- "):
                assert re.search(r"\[\d+\]", line), (filename, line)
        for group in groups:
            for photo in photos[group]:
                assert photo["url"] in output
                assert photo["source"] in output
                assert photo["date"] in output
                assert photo["citation"] in cited
        assert "not visually inspected" in output
        assert "personal-assistant:restaurant-reservations" in output


def test_saved_hour_and_photo_readbacks_preserve_real_failures():
    directory = ROOT / "evals/restaurant-discovery/2026-10-27"
    hours = json.loads((directory / "hours-evidence.json").read_text())
    assert {item["source_id"] for item in hours} == {37, 47, 48}
    assert all(not item["authenticated"] and item["hours"] for item in hours)
    probes = json.loads((directory / "photo-probes.json").read_text())
    fallbacks = json.loads((directory / "photo-curl-fallback.json").read_text())
    failed = {item["requested_url"] for item in probes if item["error"]}
    assert len(probes) == 18
    assert len(failed) == 2
    assert failed == {item["url"] for item in fallbacks}
    assert all(item["returncode"] == 0 and item["result"].startswith("200 image/") for item in fallbacks)
