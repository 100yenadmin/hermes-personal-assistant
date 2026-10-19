import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_recipes():
    spec = importlib.util.spec_from_file_location("pa_recipes_catalog", ROOT / "personal_assistant/recipes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class PersonalAssistantRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recipes = load_recipes()

    def test_catalog_is_finite_and_namespaced(self):
        ids = tuple(f"R{i}" for i in range(1, 9)); catalog = self.recipes.catalog()
        self.assertEqual(self.recipes.recipe_ids(), ids); self.assertEqual(set(catalog), set(ids))
        for key, recipe in catalog.items():
            self.assertTrue(recipe["lazy"] and recipe["steps"] and recipe["expected_outcome"])
            self.assertEqual((recipe["id"], recipe["skill"]), (key, recipe["skill_qualified_name"]))
            self.assertRegex(recipe["skill"], r"^personal-assistant:[a-z0-9-]+$")
            self.assertIsInstance(recipe["confirmation_required"], bool)

    def test_routes_accept_id_slug_and_qualified_skill(self):
        for key, recipe in self.recipes.catalog().items():
            for alias in (key, key.lower(), recipe["recipe_id"], recipe["skill"], recipe["skill"].upper()):
                self.assertEqual(self.recipes.route(alias), recipe)
        with self.assertRaises(KeyError): self.recipes.route("R9")

    def test_workflow_and_operations_are_bounded(self):
        from personal_assistant.entry import OPERATIONS
        known = set(OPERATIONS)
        capabilities = {"portable_files", "calendar", "email", "browser", "automation", "messaging", "kanban", "secure_access"}
        workflow = ["capture", "next_action", "prepare", "verify", "followup"]
        for recipe in self.recipes.catalog().values():
            self.assertEqual([step["id"] for step in recipe["workflow"]], workflow)
            self.assertTrue(set(recipe["operations"]) <= known and set(recipe["required_capabilities"]) <= capabilities)
            self.assertEqual(next(step for step in recipe["workflow"] if step["id"] == "prepare")["operation"], "action_upsert")
            if "action_confirm" in recipe["operations"]: self.assertTrue(recipe["confirmation_required"])
            if recipe["transaction_paths"]:
                self.assertEqual([step["operation"] for step in recipe["transaction_protocol"]], ["action_prepare", "action_confirm", "action_result"])
                self.assertEqual(recipe["execution_claim"]["mode"], "native_gateway")
                self.assertEqual(recipe["execution_claim"]["trigger"], "matching_provider_call")
                self.assertIn("action_cancel", recipe["operations"])
            else:
                self.assertIsNone(recipe["execution_claim"])

    def test_lazy_docs_match_routes(self):
        for recipe in self.recipes.catalog().values():
            slug = recipe["skill"].split(":", 1)[1]; path = ROOT / "skills/personal-assistant" / slug / "SKILL.md"
            self.assertTrue(path.is_file(), path); text = path.read_text()
            self.assertIn(f"name: {recipe['skill']}", text); self.assertIn(f"recipe: {recipe['id']}", text)
            for operation in ("pa.context", "pa.action_upsert"): self.assertIn(operation, text)
            if recipe["transaction_paths"]:
                for operation in ("pa.action_cancel", "pa.action_result", "enforcement_profile", "exact_action"):
                    self.assertIn(operation, text)
                self.assertIn("native gateway", text.lower())
                self.assertNotIn("pa.action_claim", text)

    def test_base_skill_distinguishes_governed_and_legacy_claims(self):
        text = (ROOT / "skills/personal-assistant/SKILL.md").read_text()
        governed = text.index("Governed exact-action transaction")
        legacy = text.index("Legacy transaction")
        self.assertIn('enforcement_profile="exact_action"', text[governed:legacy])
        self.assertIn("native gateway", text[governed:legacy].lower())
        self.assertNotIn("source revision", text[governed:legacy].lower())
        self.assertNotIn("action_claim", text[governed:legacy])
        self.assertIn("action_claim", text[legacy:])

    def test_synthetic_eval_covers_all_recipes_and_r2_actions(self):
        data = json.loads((ROOT / "evals/pa-local-eva-v1.json").read_text()); self.assertEqual(data["schema"], "pa-local-eva-v1")
        self.assertIn("synthetic", data["claim_boundary"].lower()); by_id = {recipe["id"]: recipe for recipe in data["recipes"]}
        self.assertEqual(set(by_id), set(self.recipes.recipe_ids()))
        required = {"booking", "checkin", "ground", "reservation", "confirmed_submit_recovery"}
        self.assertTrue(required <= {case["name"] for case in by_id["R2"]["scenarios"]})
        for recipe in by_id.values():
            allowed = set(self.recipes.catalog()[recipe["id"]]["operations"])
            for case in recipe["scenarios"]: self.assertTrue(case["input"] and case["expected"]["outcome"] and set(case["expected"]["operations"]) <= allowed)

    def test_existing_reference_links_are_skill_relative(self):
        for path in (ROOT / "skills").glob("*/SKILL.md"):
            text = path.read_text()
            if "references/" not in text: continue
            self.assertIn("relative to this skill directory", text, path); self.assertNotIn("skills/references/", text)
            for ref in set(re.findall(r"references/[A-Za-z0-9._-]+\.md", text)): self.assertTrue((path.parent / ref).is_file(), (path, ref))


if __name__ == "__main__": unittest.main()
