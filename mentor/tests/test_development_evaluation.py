"""Negative controls for the development screen's artifact/acceptance gate.

These test the evaluator, not whether a model obeys skill prose.
"""
import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "development_summary", ROOT / "tuning/evals/development-discipline/summarize.py")
SUMMARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUMMARY)


class Encoder:
    def encode(self, text):
        return list(text)


class DevelopmentEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.cases = [
            {"id": "work", "public": {"artifacts": [{"id": "A"}]}, "criteria": ["a"] * 4,
             "expected": {"baseline": {"required": [], "optional": []},
                          "candidate": {"required": ["development-discipline"], "optional": []}}},
            {"id": "control", "public": {"artifacts": []},
             "expected": {a: {"required": [], "optional": []} for a in ("baseline", "candidate")}},
        ]
        self.manifest = {"experiment": "fixture", "jobs": [
            {"id": arm, "arm": arm, "base_instruction_tokens_proxy": 5,
             "skill_files": {"skills/other/SKILL.md": {"tokens_proxy": 100},
                             "skills/development-discipline/SKILL.md": {"tokens_proxy": 10}}}
            for arm in ("baseline", "candidate")]}
        self.responses, self.routes, self.grades = {}, {}, []
        for arm in ("baseline", "candidate"):
            self.responses[arm], self.routes[arm] = [], []
            for case in self.cases:
                skills = ["development-discipline"] if arm == "candidate" and case["id"] == "work" else []
                self.responses[arm].append({"id": case["id"], "skills": skills,
                    "decision": "Accept only scoped result", "next_actions": ["Preserve evidence"],
                    "evidence_ids": ["A"] if case["id"] == "work" else [], "allowed_claim": "Offline result only"})
                self.routes[arm].append({"id": case["id"], "skills": skills.copy()})
            self.grades.append({"id": arm + "/work", "scores": [2] * 4,
                                "evidence": ["Accept only scoped result"] * 4, "critical_failures": []})

    def evaluate(self):
        return SUMMARY.evaluate(self.cases, self.manifest, self.responses, self.routes, self.grades, Encoder())

    def test_complete_scoped_screen_can_pass(self):
        result = self.evaluate()
        self.assertTrue(all(result["gates"].values()))
        self.assertIsNone(result["provider_usage"])

    def test_duplicate_json_keys_and_nonfinite_values_rejected(self):
        for text in ('{"critical_failures":["leak"],"critical_failures":[]}',
                     '{"score":NaN}', '{"score":Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                SUMMARY.parse_json(text)

    def test_cheap_critical_failure_cannot_be_averaged_away(self):
        self.grades[1]["critical_failures"] = ["credential exposure"]
        result = self.evaluate()
        self.assertFalse(result["gates"]["no_critical_failure"])
        self.assertEqual(result["disposition"], "do_not_adopt_under_this_rule")

    def test_case_regression_blocks_even_with_lower_context(self):
        self.grades[1]["scores"] = [2, 2, 2, 1]
        self.assertFalse(self.evaluate()["gates"]["no_case_quality_regression"])

    def test_missing_response_grade_or_duplicate_id_fails_closed(self):
        for kind in ("response", "grade", "duplicate"):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == "response":
                    self.responses["candidate"].pop()
                elif kind == "grade":
                    self.grades.pop()
                else:
                    self.responses["candidate"].append(copy.deepcopy(self.responses["candidate"][0]))
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_invented_evidence_boolean_score_and_unquoted_grade_rejected(self):
        for kind in ("source", "score", "quote"):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == "source":
                    self.responses["candidate"][0]["evidence_ids"] = ["invented"]
                elif kind == "score":
                    self.grades[1]["scores"][0] = True
                else:
                    self.grades[1]["evidence"][0] = "A response that never existed"
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_post_read_route_change_rejected(self):
        self.responses["candidate"][0]["skills"] = []
        with self.assertRaisesRegex(ValueError, "route changed"):
            self.evaluate()

    def test_unnecessary_load_on_control_blocks_routing(self):
        self.responses["candidate"][1]["skills"] = ["development-discipline"]
        self.routes["candidate"][1]["skills"] = ["development-discipline"]
        self.assertFalse(self.evaluate()["gates"]["correct_selective_routing"])

    def test_session_union_does_not_pretend_loaded_text_is_removed(self):
        result = self.evaluate()["arms"]["candidate"]
        self.assertEqual(result["session_instruction_tokens_proxy"], 15)
        self.assertEqual(result["instruction_tokens_proxy"], 20)
        self.assertEqual(result["always_on_session_instruction_tokens_proxy"], 115)


if __name__ == "__main__":
    unittest.main()
