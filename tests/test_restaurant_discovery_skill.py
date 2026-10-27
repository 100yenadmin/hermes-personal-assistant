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


def _policy_block(path, start, end=None):
    """Scope wording guards to the governing block, not incidental mentions.

    These are static policy guardrails, not behavioural proof or live acceptance.
    """
    text = path.read_text()
    assert text.count(start) == 1, (path, start)
    block = text.split(start, 1)[1]
    if end is not None:
        assert end in block, (path, end)
        block = block.split(end, 1)[0]
    return " ".join(block.replace("**", "").split())


def _has_policy(block, *phrases):
    for phrase in phrases:
        assert phrase in block, phrase


EVIDENCE = SKILL.parent / "references/evidence-and-evals.md"
PLATFORMS = SKILL.parent / "references/local-platforms.md"


def test_round3_deadline_and_guide_scope_preserve_in_scope_area_accounting():
    binding = _policy_block(SKILL, "## Read and bind the request", "## Find candidates")
    _has_policy(binding, "Before research", "end-to-end deadline", "15 minutes",
                "hours/identity checks, finalist photos and the final response",
                "never silently extend the budget")
    curated = _policy_block(SKILL, "1. **Curated lists first.**", "2. **Search as a local.**")
    _has_policy(curated, "scope URL, edition/year and caveat", "scope excludes the city",
                "skip the out-of-scope national category sweep",
                "in-scope category/location request", "every entry", "pagination",
                "before widening", "declared total, unique entries checked",
                "each entry's area evidence", "pick, an exclusion or an unverified lead",
                "timebox prevents completion", "do not claim the local category is exhausted")
    for path, start, end in (
        (EVIDENCE, "## Deadline and guide-scope accounting", "## Private routes"),
        (PLATFORMS, "## Deadline, guide scope and route privacy", "## Japan"),
    ):
        block = _policy_block(path, start, end)
        _has_policy(block, "end-to-end deadline", "15 minutes", "scope URL, edition/year and caveat",
                    "skip the out-of-scope national category sweep", "paginated entry-area accounting",
                    "timebox", "coverage gap")


def test_round3_recent_photo_window_distinguishes_capture_and_publication_proxy():
    photo = _policy_block(SKILL, "4. **Menu and visual pre-filter.**", "5. **Verify the actual day")
    _has_policy(photo, "within 12 months before the local meal date", "stricter window",
                "publication proxy", "not verified recent capture",
                "Prefer qualifying candidates before historical ones within the same cap and deadline",
                "Never manufacture capture dates from filenames, upload dates or retrieval time",
                "say exactly “No verified recent photo found”", "historical/undated")
    evidence = _policy_block(EVIDENCE, "## Photo freshness and pixel evidence", "## Meal-window")
    platforms = _policy_block(PLATFORMS, "## Photo dates and meal-window checks", "Gate conflicts")
    for block in (evidence, platforms):
        _has_policy(block, "within 12 months before the local meal date", "stricter",
                    "publication proxy", "filenames, upload dates", "retrieval",
                    "Prefer qualifying candidates before historical ones",
                    "No verified recent photo found", "historical/undated")


def test_round3_conflicts_gate_the_requested_meal_not_immaterial_lunch_hours():
    hours = _policy_block(SKILL, "5. **Verify the actual day", "6. **Rank for this owner.**")
    _has_policy(hours, "requested arrival and entire meal interval", "last order/entry",
                "closures, address and essential dietary suitability", "lunch-opening",
                "all credible sources support the entire dinner window", "disclose it",
                "do not exclude that dinner candidate for lunch alone",
                "dinner-overlapping conflict", "quarantines", "unverified leads")
    for path, start, end in (
        (EVIDENCE, "## Meal-window conflict gates", "## Deadline"),
        (PLATFORMS, "Gate conflicts", "## Elsewhere"),
    ):
        block = _policy_block(path, start, end)
        _has_policy(block, "entire meal interval", "last order/entry", "essential dietary",
                    "lunch-opening", "all credible sources support the entire dinner window",
                    "dinner-overlapping conflict quarantines", "unverified lead")


def test_round3_photo_prefilter_leads_cannot_become_visual_claims_or_extra_budget():
    photo = _policy_block(SKILL, "4. **Menu and visual pre-filter.**", "5. **Verify the actual day")
    _has_policy(photo, "adjacency, alt text and filenames only as leads, not proof of image content",
                "caption only what is visible", "Do not infer meat species, ingredients, exact dish names",
                "neighbouring article text or image position", "pixels alone ground captions",
                "3 candidate images per finalist", "9 total", "once 2 good photos",
                "One batched helper", "existing authorized model lane", "keep/reject",
                "Do not change runtime or silently use a paid/provider fallback")
    evidence = _policy_block(EVIDENCE, "## Photo freshness and pixel evidence", "## Meal-window")
    _has_policy(evidence, "Adjacency, alt text and filenames are leads only",
                "Never infer species or exact dish names from neighbouring article text or image position",
                "captions must come from pixels", "3 candidates per finalist", "about 9 total",
                "stop at 2 good photos", "one batched, existing-lane", "switching paid/provider routes")
    platforms = _policy_block(PLATFORMS, "## Photo dates and meal-window checks", "Gate conflicts")
    _has_policy(platforms, "prefilter leads only", "caption pixels, not neighbouring article text or image position",
                "never infer species or exact dish names from those leads")


def test_round3_default_chat_is_compact_first_not_an_unsolicited_card_dump():
    output = _policy_block(SKILL, "## Show, then hand off", "End with a concrete choice:")
    _has_policy(output, "Telegram/default chat: compact FIRST", "one pick plus two alternatives",
                "about 10 lines of recommendation text", "credited/dated photo group captions",
                "local meal date, timezone, assumed arrival and party size",
                "Recent reviews unchecked", "up front", "price per person or unknown",
                "relevant dinner schedule/last order or entry", "no seats guarantee",
                "Cite factual lines with source links", "Fewer supported options",
                "2 photos per finalist", "a third only if already justified under the cap",
                "on request or in a separate attachment",
                "Do not dump all cards after compact text unsolicited")
    compact = _policy_block(EVIDENCE, "## Compact response contract", "## Full evidence card")
    _has_policy(compact, "compact FIRST", "about 10 lines", "assumed arrival and party size",
                "Recent reviews unchecked", "up front", "price per person or unknown",
                "relevant dinner schedule/last order or entry", "no seats guarantee",
                "source links on factual lines", "Target 2 suitable photos per finalist",
                "a third only if already justified under the cap", "on request or in a separate attachment",
                "do not dump all cards after compact text unsolicited")
    assert "```text" not in compact  # Expanded template belongs only in the separate card block.
    card = _policy_block(EVIDENCE, "## Full evidence card", "## Photo freshness")
    _has_policy(card, "branch address", "order math", "Practical:", "Photos (target 2)")
    assert "2–3" not in compact + card


def test_round3_route_evidence_never_publishes_stay_or_origin_links():
    route = _policy_block(SKILL, "## Private route evidence", "## Show, then hand off")
    _has_policy(route, "authorized stay may be used privately", "never in a public or broad query",
                "hotel/origin in a public map URL or shared artifact",
                "destination-only Maps/search/place links", "strip origin-bearing route URLs",
                "redact private data from screenshots", "Cite the safe destination separately",
                "does not prove travel time unless actually routed", "distance/travel time unknown")
    for path, start, end in (
        (EVIDENCE, "## Private routes and shared links", "## Recent-review"),
        (PLATFORMS, "An authorized stay is private route input only", "## Japan"),
    ):
        block = _policy_block(path, start, end)
        _has_policy(block, "public/broad", "shared artifact", "destination-only Maps/search/place links",
                    "origin-bearing route URLs", "redact private", "safe destination separately",
                    "actually routed", "unknown")
    card = _policy_block(EVIDENCE, "## Full evidence card", "## Photo freshness")
    _has_policy(card, "safe destination-only link", "never share an origin URL")
    assert "[map route]" not in card


def test_round3_review_fallback_is_bounded_independent_and_visit_dated():
    reviews = _policy_block(SKILL, "3. **Read recent evidence.**", "4. **Menu and visual pre-filter.**")
    _has_policy(reviews, "last 6 months", "sample size", "two failures with the same cause",
                "one materially different public no-login fallback", "within the deadline",
                "exact-branch dated visit records", "opened original independent visit posts",
                "iFoodie → original blog", "Tabelog", "public Naver/Kakao",
                "visit date, not an article update date", "Sponsored, press and venue posts are not independent visits",
                "Recent reviews unchecked", "up front", "No “no complaints” claim from an empty sample",
                "one visit is not a trend")
    for path, start, end in (
        (EVIDENCE, "## Recent-review fallback", "## Repeatable live-eval"),
        (PLATFORMS, "## Recent reviews and blocked-platform fallback", "## Photo dates"),
    ):
        block = _policy_block(path, start, end)
        _has_policy(block, "two failures with the same cause", "one materially different public no-login fallback",
                    "within the deadline", "exact-branch dated visit records",
                    "opened original independent visit posts", "iFoodie → original blog",
                    "Tabelog", "public Naver/Kakao", "not independent visits", "last 6 months",
                    "sample size", "One visit is not a trend", "Recent reviews unchecked", "up front",
                    "“no complaints” from an empty sample")
    protocol = _policy_block(EVIDENCE, "## Repeatable live-eval protocol")
    _has_policy(protocol, "guardrails, not behavioural proof", "separate non-author reviewer")


def test_round3_taipei_outputs_have_standalone_provenance_and_bounded_receipts():
    """Saved-output integrity, not an assertion of restaurant quality or live delivery."""
    from datetime import datetime

    directory = ROOT / "evals/restaurant-discovery/2026-10-27-round3"
    compact = (directory / "telegram.md").read_text()
    photos = (directory / "telegram-photos.md").read_text()
    # These two files are independently shareable: numeric refs cannot rely on
    # a Sources block available only in the separate full report.
    for standalone in (compact, photos):
        assert not re.search(r"\[\d+\](?!\()", standalone), "unresolved standalone source reference"
        assert not re.search(r"/Users/|[?&]origin=|start_latitude=", standalone)
    assert len(compact.splitlines()) == 10
    assert len(compact.encode("utf-16-le")) // 2 <= 4096
    assert compact.index("Recent reviews unchecked") < compact.index("Pick:")
    inspection = json.loads((directory / "photo-inspection.json").read_text())
    viewed = inspection["viewed_candidates"]
    assert inspection["batch_calls"] == 1
    assert len(viewed) == inspection["candidate_count"] == 6
    for group in ("pick", "alt1", "alt2"):
        assert sum(item["id"].startswith(group + "-") for item in viewed) == 2
    for image in viewed:
        assert image["visually_inspected"] and image["decision"] == "keep"
        assert image["sha256"] and image["capture_date"] is None
        assert image["url"] in photos
        assert "](" + image["source"] + ")" in photos, "photo source page must be linked directly"
    timing = json.loads((directory / "run-timing.json").read_text())
    start = datetime.fromisoformat(timing["start_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(timing["finish_utc"].replace("Z", "+00:00"))
    elapsed = (end - start).total_seconds()
    assert 0 < elapsed <= timing["budget_seconds"] == 900
    assert abs(elapsed - timing["elapsed_seconds"]) < 0.001
