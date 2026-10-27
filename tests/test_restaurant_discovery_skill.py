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


def test_discovery_audits_complete_category_area_before_widening():
    text = SKILL.read_text()
    assert "every entry" in text
    assert "pagination" in text
    assert "before widening" in text
    assert "pick, an exclusion or an unverified lead" in text
    assert "coverage gap" in text


def test_discovery_inspects_candidate_photo_pixels_when_available():
    text = SKILL.read_text()
    assert "When image viewing is available" in text
    assert "inspect" in text
    assert "recommended dish" in text
    assert "caption only what is visible" in text
    assert "HTTP 200" in text
    for phrase in ("Finalists only", "Pre-filter before viewing", "3 candidate images per finalist",
                   "2 good", "One batched helper", "keep/reject", "main conversation",
                   "dish photo", "Never inspect during broad"):
        assert phrase in text


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
    assert len(photos) == 8
    assert sum(len(items) for items in photos.values()) == 16
    cases = {
        "luodong-tuesday-lamb.md": ("tw-pick", "tw-alt1", "tw-alt2"),
        "osaka-namba-bib.md": ("jp-pick", "jp-alt1", "jp-alt2"),
        "seoul-local-platforms.md": ("kr-pick", "kr-alt2"),
    }
    for filename, groups in cases.items():
        text = (directory / filename).read_text()
        assert "{{photos:" not in text
        assert "## Condensed live tool transcript" in text
        assert "## Recovery readback" in text
        assert "## Self-grade against #71" in text
        body, block = text.split("## Sources", 1)
        cited = {int(value) for value in re.findall(r"\[(\d+)\]", body)}
        rendered = {int(key): url for key, url in re.findall(r"^\[(\d+)\] (\S+)(?: — .*)?$", block, re.M)}
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
                assert photo["visually_inspected"] is True
                assert photo["caption"] in output
                assert photo["image_sha256"]
        assert "not visually inspected" not in output
        assert "visually inspected" in output
        assert "personal-assistant:restaurant-reservations" in output


def test_osaka_live_eval_accounts_for_all_category_entries_and_minato_conflict():
    directory = ROOT / "evals/restaurant-discovery/2026-10-27"
    audit = json.loads((directory / "osaka-area-audit.json").read_text())
    listed = {name for page in audit["lists"] for name in page["names"]}
    entries = audit["entries"]
    assert len(entries) == len({row["name"] for row in entries}) == audit["declared_total"] == 59
    assert {row["name"] for row in entries} == listed
    assert all(row["address"] and row["excerpt"] and row["url"].startswith("https://guide.michelin.com/") for row in entries)
    assert all(row["disposition"] in {"pick", "alternative", "exclusion", "unverified_lead"} for row in entries)
    minato = next(row for row in entries if row["name"] == "Tonkatsu Minato")
    assert minato["area_scope"] == "in_area"
    assert minato["disposition"] == "unverified_lead"
    output = (directory / "osaka-namba-bib.md").read_text().split("## Final user-facing output", 1)[1].split("## Self-grade", 1)[0]
    assert "みな斗" in output and "10:30–16:00" in output and "17:30–20:50" in output
    assert "59" in output and "conflict" in output
    assert output.index("みな斗") < output.index("### Pick")


def test_photo_inspection_record_links_selected_pixels_not_only_http_probes():
    directory = ROOT / "evals/restaurant-discovery/2026-10-27"
    inspection = json.loads((directory / "photo-inspection.json").read_text())
    photos = json.loads((directory / "photos.json").read_text())
    candidates = {row["id"]: row for row in inspection["viewed_candidates"]}
    selected = [photo for group in photos.values() for photo in group]
    assert len(selected) == 16
    assert inspection["batch_calls"] == 1
    assert inspection["candidate_panel_count"] == 16
    assert inspection["case_candidate_counts"] == {"luodong": 6, "osaka": 6, "seoul": 4}
    assert all(count <= 3 for count in inspection["per_finalist_candidate_counts"].values())
    assert "kr-alt1" not in inspection["per_finalist_candidate_counts"]
    for photo in selected:
        viewed = candidates[photo["candidate_id"]]
        assert viewed["url"] == photo["url"]
        assert viewed["image_sha256"] == photo["image_sha256"]
        assert viewed["method"] == "contact_sheet_pixels"
    rejected = {item["id"] for item in inspection["rejected"]}
    assert {"tw-pick-old2", "jp-pick-old1"} <= rejected
    assert not rejected.intersection(photo["candidate_id"] for photo in selected)
    assert "not_independent_review" in inspection["proof_boundary"]


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
