import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_evaluator():
    spec = importlib.util.spec_from_file_location("pa_agent_evaluator", ROOT / "scripts/evaluate_pa_agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PersonalAssistantScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evaluator = load_evaluator()

    def test_fixture_and_report_contract(self):
        evaluator = self.evaluator
        report = evaluator.run_deterministic_evaluation()
        self.assertEqual((report["status"], report["scenario_count"], report["pass_count"]), ("PASS", 20, 20))
        self.assertGreaterEqual(report["fixture_callbacks"]["provider_readback"], 10)
        recovery = next(row for row in report["scenarios"] if row["scenario"] == "confirmed_submit_recovery")
        self.assertEqual(recovery["status"], "PASS")
        self.assertTrue({"action_claim", "fixture_provider", "action_result"} <= set(recovery["operations"]))
        self.assertEqual(recovery["questions"], 0)
        comparison = evaluator.guidance_comparison()
        self.assertEqual((comparison["baseline_commit"], comparison["same_model"]), ("103d6ef", "gpt-5.6-sol"))
        self.assertTrue(comparison["same_inputs"] and comparison["limitations"])
        self.assertNotIn("messages", json.dumps(comparison))
        metrics = evaluator.turn_metrics({"completed": True, "failed": False, "final_response": "Done.", "messages": [{"role": "assistant", "tool_calls": [{"function": {"name": "pa", "arguments": '{"operation":"status"}'}}]}, {"role": "tool", "name": "pa"}], "input_tokens": 3, "output_tokens": 2, "total_tokens": 5}, 1, 0, ["actual_fact"])
        self.assertEqual((metrics["status"], metrics["observed_tools"], metrics["tool_call_count"], metrics["callback_delta"], metrics["task_outcome_status"], metrics["total_tokens"]), ("PASS", ["pa"], 1, 1, "PASS", 5))
        self.assertNotIn("messages", metrics)


if __name__ == "__main__":
    unittest.main()
