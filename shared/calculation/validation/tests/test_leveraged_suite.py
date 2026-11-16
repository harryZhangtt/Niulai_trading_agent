"""Maintained-suite binding for the leveraged-fund operator."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from shared.calculation.validation import acceptance, leveraged_operator, runner, worker


class LeveragedOperatorSuiteTests(unittest.TestCase):
    def test_suite_runs_focused_and_legacy_tests_with_hashes(self):
        parent = runner.STATE / "tests"
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            output = Path(directory) / "result"
            result = leveraged_operator.run(output)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["tests"]["focused_observed"], 22)
            self.assertEqual(result["tests"]["legacy_observed"], 31)
            self.assertEqual(result["tests"]["total_observed"], 53)
            self.assertEqual(result["tests"]["failures"], [])
            self.assertEqual(result["tests"]["errors"], [])
            self.assertIn(
                "shared/calculation/operators/leveraged_funds.py",
                result["candidate_hashes"],
            )
            evidence = runner.ROOT / result["evidence_paths"][0]
            self.assertTrue(evidence.is_file())

    def test_suite_set_has_one_owner_and_acceptance_freezes_baseline_findings(self):
        self.assertIs(worker.SUITES, runner.SUITES)
        suites = {name: {"completed": True, "result": {"status": "passed"}}
                  for name in runner.SUITES}
        suites["paths"]["result"] = {
            "status": "failed",
            "findings": [{"id": finding} for finding in sorted(
                acceptance.RETAINED_BASELINE_FINDINGS["paths"])],
        }
        suites["contracts"]["result"] = {
            "status": "failed",
            "findings": [{"id": finding, "scope": "baseline"} for finding in sorted(
                acceptance.RETAINED_BASELINE_FINDINGS["contracts"])],
        }
        self.assertTrue(acceptance.suite_results_acceptable({"suites": suites}))
        changed = deepcopy(suites)
        changed["leveraged_operator"]["result"]["status"] = "failed"
        self.assertFalse(acceptance.suite_results_acceptable({"suites": changed}))
        changed = deepcopy(suites)
        changed["common_factor_attribution"]["result"]["status"] = "failed"
        self.assertFalse(acceptance.suite_results_acceptable({"suites": changed}))
        changed = deepcopy(suites)
        changed["paths"]["result"]["findings"].pop()
        self.assertFalse(acceptance.suite_results_acceptable({"suites": changed}))
        changed = deepcopy(suites)
        changed["paths"]["result"]["findings"].append({"id": "new_failure"})
        self.assertFalse(acceptance.suite_results_acceptable({"suites": changed}))
        changed = deepcopy(suites)
        changed["contracts"]["result"]["findings"][0]["scope"] = "candidate"
        self.assertFalse(acceptance.suite_results_acceptable({"suites": changed}))
        changed = deepcopy(suites)
        changed.pop("leveraged_operator")
        self.assertFalse(acceptance.suite_results_acceptable({"suites": changed}))


if __name__ == "__main__":
    unittest.main()
