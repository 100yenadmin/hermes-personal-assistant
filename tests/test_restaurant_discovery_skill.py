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


def test_discovery_contract_keeps_unknowns_and_freshness_explicit():
    text = SKILL.read_text()
    for phrase in ("Bib Gourmand", "last 6 months", "last order", "capture date",
                   "publication date", "unknown", "closed", "one pick plus two alternatives"):
        assert phrase in text
    platforms = (SKILL.parent / "references/local-platforms.md").read_text()
    for phrase in ("Tabelog", "Naver", "Kakao", "Blue Ribbon", "iFoodie", "羊肉爐", "ビブグルマン", "블루리본"):
        assert phrase in platforms
