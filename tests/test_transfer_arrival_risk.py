"""Structural checks for synthetic transfer/arrival-risk reviewer fixtures.

These tests only read the skill/reference Markdown and inspect source-shaped
fixtures. They do not evaluate itineraries, call providers, and do not prove
live-agent behavior.
"""

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "itinerary-intake"
SKILL_PATH = SKILL_DIR / "SKILL.md"
REFERENCE_PATH = SKILL_DIR / "references" / "transfer-arrival-risk.md"


def _discovered_skill_metadata():
    """Call the plugin's real lazy frontmatter reader without registering it."""
    spec = importlib.util.spec_from_file_location(
        "pa_discovery_fixture", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the native discovery entrypoint")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._skill_metadata(SKILL_PATH)


def _read_optional(path):
    return path.read_text() if path.is_file() else ""


# Synthetic reviewer fixtures are source-shaped facts, not provider data.
CASES = {
    "explicit_same_ticket_proof": {
        "ticket_relationship": "one issued ticket and booking reference",
        "carrier_handoff": "same operating carrier",
        "through_bag_source": "issued itinerary explicitly says baggage is checked through",
        "terminal": "same terminal, source-confirmed",
        "arrival_access": "property confirmation explicitly documents self-check-in",
        "expected": ("proven", "explicit", "same-terminal does not mean airside"),
    },
    "same_pnr_explicit_separate_ticket_contracts": {
        "booking_reference_relation": "same PNR/booking reference ZX7Q2, source-confirmed",
        "ticket_relationship": (
            "issued sources explicitly state separate tickets/contracts; distinct ticket "
            "numbers are retained but numbers alone are not proof"
        ),
        "source_facts": (
            "different operating carrier; same terminal is source-confirmed; "
            "no through-bag statement"
        ),
        "expected": (
            "booking reference/pnr",
            "explicitly separate tickets/contracts",
            "ticket relationship",
            "not proven",
            "through-bag status is not proven",
        ),
    },
    "separate_reference_unknown_bag": {
        "booking_reference_relation": "separate booking references, source-confirmed",
        "ticket_relationship": "separate tickets and booking references",
        "carrier_handoff": "marketing carrier changes to a different operating carrier",
        "through_bag_source": "aggregator shows both flights but the issued sources are silent",
        "terminal": "same terminal shown, airside path unknown",
        "arrival_access": "late-arrival property access is absent from the confirmation",
        "expected": ("not proven", "unknown", "reclaim", "re-check", "operating-carrier"),
    },
    "through_bag_but_border_security_unknown": {
        "through_bag_source": (
            "origin carrier's issued itinerary explicitly says the bag is tagged to the "
            "final destination"
        ),
        "border_security_path": (
            "international arrival to domestic departure; immigration and customs are "
            "required or unknown; airside status, security, terminal movement, and onward "
            "check-in are not stated"
        ),
        "cutoffs": "onward boarding cutoff and authoritative MCT are absent",
        "expected": (
            "for that claim only",
            "immigration",
            "customs",
            "security",
            "airside",
            "terminal movement",
            "onward check-in",
            "protected-connection guarantee",
        ),
    },
    "transit_permission_authority_grant": {
        "authorized_context": (
            "authorized profile context supplies passport issuing country/citizenship and "
            "residence or visa status only when the relevant authority requires them"
        ),
        "authority_result": (
            "relevant official immigration authority explicitly permits this traveler to "
            "make the exact airside transfer"
        ),
        "expected": ("traveler-specific", "official", "proven", "safe claim"),
    },
    "transit_permission_missing_context": {
        "authorized_context": "no authorized traveler context is available",
        "authority_result": "generic visa list does not resolve the traveler-specific case",
        "expected": (
            "recover authorized context before asking",
            "transit/entry eligibility: unknown",
            "blocks a safe claim",
            "blanket visa advice",
        ),
    },
    "overnight_schengen_late_arrival": {
        "source_local_times": (
            "international arrival at AMS: 2026-10-01 23:40 +02:00",
            "onward Schengen departure at AMS: 2026-10-02 01:10 +02:00",
        ),
        "elapsed_time_check": "1h30m after timezone-aware calculation",
        "ticket_relationship": "one reference, ticket relationship not explicit",
        "carrier_handoff": "non-Schengen arrival followed by onward Schengen carrier",
        "through_bag_source": "no explicit through-bag statement",
        "terminal": "same airport, terminal movement not stated",
        "cutoffs_and_mct": (
            "carrier bag-drop and boarding cutoffs and an authoritative MCT are absent"
        ),
        "arrival_access": (
            "hotel reservation is present, but late check-in, self-check-in, concierge, "
            "locker, building-registration, key, and ID instructions are absent"
        ),
        "expected": (
            "immigration",
            "customs",
            "baggage reclaim",
            "late-arrival property access",
            "unknown",
        ),
    },
}


class TransferArrivalRiskStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = _read_optional(SKILL_PATH)
        cls.reference = _read_optional(REFERENCE_PATH)
        cls.skill_lower = cls.skill.lower()
        cls.reference_lower = cls.reference.lower()

    def test_reference_is_resolved_relative_to_itinerary_skill_directory(self):
        self.assertTrue(REFERENCE_PATH.is_file())
        self.assertEqual(Path("references") / REFERENCE_PATH.name,
                         Path("references/transfer-arrival-risk.md"))
        self.assertIn("relative to this skill directory", self.skill_lower)
        self.assertIn("references/transfer-arrival-risk.md", self.skill_lower)

    def test_frontmatter_description_is_used_by_native_discovery(self):
        frontmatter, description = _discovered_skill_metadata()
        self.assertEqual(description, frontmatter["description"])
        self.assertNotIn("# ", description)
        for trigger in ("flight connections", "transfer risk", "late-arrival property access"):
            with self.subTest(trigger=trigger):
                self.assertIn(trigger, description.lower())

    def test_itinerary_skill_wires_risk_review_into_output(self):
        self.assertIn("transfer and arrival risk", self.skill_lower)
        self.assertIn("transfer/arrival risks", self.skill_lower)
        self.assertIn("before calling a connection safe", self.skill_lower)
        self.assertIn("booking_reference_relation", self.skill_lower)
        self.assertIn("ticket_relationship", self.skill_lower)
        self.assertIn("source facts", self.skill_lower)
        self.assertIn("unknown", self.skill_lower)
        self.assertIn("flight-to-flight connection", self.skill_lower)
        self.assertIn("rail-to-rail or rail-to-air", self.skill_lower)
        self.assertIn("transit/entry eligibility", self.skill_lower)

    def test_reference_covers_required_provider_neutral_fields(self):
        required = (
            "exact issued itinerary",
            "exact travel date",
            "booking_reference_relation",
            "ticket_relationship",
            "booking reference/pnr",
            "ticket numbers",
            "operating carrier",
            "carrier handoff",
            "airport code and terminal",
            "immigration",
            "customs",
            "baggage reclaim",
            "re-check",
            "operating carrier's exact",
            "through-bag proof",
            "aggregator",
            "same-terminal does not mean airside",
            "late-arrival property access",
            "retain the source",
            "required source or factual input",
            "air-connection scope",
            "flight-to-flight",
            "rail-to-rail or rail-to-air",
            "official immigration or border authority",
            "passport issuing country/citizenship",
            "residence or visa status",
            "recover authorized context before asking",
            "transit/entry eligibility: unknown",
            "blocks a safe claim",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.reference_lower)

    def test_reference_forbids_invented_time_rules(self):
        self.assertIn("do not calculate durations mentally", self.reference_lower)
        self.assertIn("timezone-aware datetimes", self.reference_lower)
        self.assertIn("keep each source-local date and timezone visible", self.reference_lower)
        self.assertIn("date/time ambiguity: unknown", self.reference_lower)
        self.assertIn("do not invent a minimum connection time (mct)", self.reference_lower)
        self.assertIn("do not invent a carrier cutoff", self.reference_lower)
        self.assertIn("report it as unknown", self.reference_lower)

    def test_evidence_labels_are_mutually_exclusive_with_concrete_cases(self):
        inspected_but_silent = CASES["separate_reference_unknown_bag"]
        unavailable_value = CASES["overnight_schengen_late_arrival"]
        self.assertIn("issued sources are silent", inspected_but_silent["through_bag_source"])
        self.assertIn("not proven", inspected_but_silent["expected"])
        self.assertIn("authoritative MCT", unavailable_value["cutoffs_and_mct"])
        self.assertIn("absent", unavailable_value["cutoffs_and_mct"])
        self.assertIn("unknown", unavailable_value["expected"])
        self.assertIn("source was inspected", self.reference_lower)
        self.assertIn("do not use this label when the required source", self.reference_lower)
        self.assertIn("do not relabel an inspected source that is merely silent as unknown", self.reference_lower)
        self.assertNotIn("silent ... report it as unknown", self.reference_lower)

    def test_structural_fixture_boundary_is_explicit(self):
        module_doc = (__doc__ or "").lower()
        self.assertIn("structural checks", module_doc)
        self.assertIn("source-shaped", module_doc)
        self.assertIn("do not evaluate itineraries", module_doc)
        self.assertIn("do not prove", module_doc)
        self.assertIn("live-agent behavior", module_doc)


class SyntheticTransferArrivalRiskDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = _read_optional(SKILL_PATH)
        cls.skill_lower = cls.skill.lower()
        cls.reference = _read_optional(REFERENCE_PATH).lower()

    def test_positive_explicit_proof_is_scoped_to_the_connection(self):
        case = CASES["explicit_same_ticket_proof"]
        self.assertIn("explicitly", case["through_bag_source"])
        self.assertIn("one issued ticket", case["ticket_relationship"])
        self.assertIn("proven", case["expected"])
        self.assertIn("explicit source statement", self.reference)
        self.assertIn("for this connection", self.reference)
        self.assertIn("one proven connection does not prove another", self.reference)

    def test_air_worksheet_does_not_claim_multimodal_coverage(self):
        self.assertIn("air-connection scope", self.reference)
        self.assertIn("limited to a flight-to-flight connection", self.reference)
        self.assertIn("rail-to-rail or rail-to-air transfers", self.reference)
        self.assertIn("does not cover the multimodal transfer", self.reference)
        self.assertIn("late-arrival property-access checks remain in scope", self.reference)

    def test_same_pnr_and_separate_contract_evidence_stay_independent(self):
        case = CASES["same_pnr_explicit_separate_ticket_contracts"]
        self.assertIn("same pnr", case["booking_reference_relation"].lower())
        self.assertIn("explicitly state separate tickets/contracts", case["ticket_relationship"])
        self.assertIn("numbers alone are not proof", case["ticket_relationship"])
        for expected in case["expected"]:
            self.assertIn(expected, self.reference)
        self.assertNotIn(
            "share one ticket/booking reference or have separate tickets/references",
            self.reference,
        )

    def test_negative_aggregator_and_separate_ticket_case_stays_unproven(self):
        case = CASES["separate_reference_unknown_bag"]
        self.assertIn("separate tickets", case["ticket_relationship"])
        self.assertIn("aggregator", case["through_bag_source"])
        for expected in case["expected"]:
            self.assertIn(expected, self.reference)
        self.assertIn("through-bag status is not proven", self.reference)
        self.assertIn("do not call the itinerary protected", self.reference)

    def test_same_terminal_does_not_satisfy_airside_or_baggage_proof(self):
        case = CASES["separate_reference_unknown_bag"]
        self.assertIn("same terminal", case["terminal"])
        self.assertIn("same-terminal does not mean airside", self.reference)
        self.assertIn("does not prove baggage-through", self.reference)

    def test_through_bag_proof_does_not_close_border_or_security_claims(self):
        case = CASES["through_bag_but_border_security_unknown"]
        self.assertIn("explicitly", case["through_bag_source"])
        self.assertIn("required or unknown", case["border_security_path"])
        self.assertIn("absent", case["cutoffs"])
        for expected in case["expected"]:
            self.assertIn(expected, self.reference)
        self.assertIn("through-bag proof is claim-scoped", self.reference)
        self.assertIn("does not by itself prove airside status", self.reference)
        self.assertIn("does not prove baggage-through", self.reference)

    def test_overnight_timezone_and_late_lodging_keep_unknowns_visible(self):
        case = CASES["overnight_schengen_late_arrival"]
        times = [
            datetime.strptime(value.split(": ", 1)[1], "%Y-%m-%d %H:%M %z")
            for value in case["source_local_times"]
        ]
        for value in times:
            self.assertEqual(
                value.utcoffset(),
                value.replace(tzinfo=ZoneInfo("Europe/Amsterdam")).utcoffset(),
            )
        elapsed = times[1].astimezone(timezone.utc) - times[0].astimezone(timezone.utc)
        self.assertEqual(elapsed.total_seconds(), 90 * 60)
        source_local_times = " ".join(case["source_local_times"])
        self.assertIn("2026-10-01 23:40 +02:00", source_local_times)
        self.assertIn("2026-10-02 01:10 +02:00", source_local_times)
        self.assertIn("1h30m", case["elapsed_time_check"])
        self.assertIn("authoritative MCT", case["cutoffs_and_mct"])
        self.assertIn("late check-in", case["arrival_access"])
        for expected in case["expected"]:
            self.assertIn(expected, self.reference)
        self.assertIn("late-arrival property access: unknown", self.reference)
        self.assertIn("source evidence for the property's late check-in", self.reference)
        self.assertIn("boarding cutoff", self.reference)

    def test_transit_permission_grant_requires_authorized_context_and_official_match(self):
        case = CASES["transit_permission_authority_grant"]
        self.assertIn("authorized profile context", case["authorized_context"])
        self.assertIn("relevant official immigration authority explicitly permits", case["authority_result"])
        self.assertIn("passport issuing country/citizenship", case["authorized_context"])
        self.assertIn("traveler-specific", self.reference)
        self.assertIn("relevant official authority", self.reference)
        self.assertIn("official result explicitly matching those factors can prove permission", self.reference)
        self.assertIn("safe claim", case["expected"])

    def test_missing_transit_context_is_unknown_and_privacy_safe(self):
        case = CASES["transit_permission_missing_context"]
        for expected in case["expected"]:
            self.assertIn(expected, self.reference + self.skill_lower)
        fixture_text = repr(case).lower()
        for forbidden in ("passport number:", "raw passport scan", "data:image/", "-----begin"):
            self.assertNotIn(forbidden, fixture_text)
        self.assertIn("never ask for or retain a passport number", self.reference)
        self.assertIn("never request or retain passport numbers", self.skill_lower)
        self.assertIn("do not assume citizenship", self.reference)


    def test_not_proven_transit_permission_also_blocks_safe_claim(self):
        self.assertIn("transit/entry eligibility: not proven", self.reference)
        self.assertIn("both `not proven` and `unknown` block calling the connection safe or complete", self.reference)
        self.assertIn("both block a safe or complete claim", self.skill_lower)

    def test_ticket_protection_is_reported_independently_of_eligibility(self):
        self.assertIn("governs the planning judgment, not the ticket fact", self.reference)
        self.assertIn("still reported as proven", self.reference)
        self.assertNotIn("so do not call the connection safe, protected, or complete", self.reference)

    def test_aggregator_only_evidence_has_exactly_one_label(self):
        not_proven = self.reference.split("- **not proven:**", 1)[1].split("- **unknown:**", 1)[0]
        unknown = self.reference.split("- **unknown:**", 1)[1].split("- **planning judgment:**", 1)[0]
        self.assertNotIn("aggregator", not_proven)
        self.assertIn("only an aggregator display is available", unknown)

if __name__ == "__main__":
    unittest.main()
