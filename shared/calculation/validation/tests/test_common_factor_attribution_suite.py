"""Standalone suite and frozen-hash binding for common-factor attribution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from shared.calculation.validation import acceptance, common_factor_attribution as suite, runner, worker

ROOT = Path(__file__).resolve().parents[4]
FROZEN_SUPPORT_HASHES = {
    "shared/calculation/operators/common_factor_attribution.py": "f488eaf2e74ac3bf9c17cea31037c1a0336d10980b835926b7cb23e488f512fb",
    "shared/calculation/validation/test_common_factor_attribution.py": "4be7970d5e4b869caed1fa916172c385d96e979aee5f8e972f7f9e367ad8a618",
    "shared/calculation/validation/common_factor_attribution.py": "5ffca61696c8efdf88a221546624cb38c5d753bf10e2593861ad11ef4764c423",
}


def sha(relative_path):
    return hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()


class CommonFactorAttributionSuiteTests(unittest.TestCase):
    def test_focused_suite_passes_and_binds_frozen_hashes_without_timestamp(self):
        parent = ROOT / ".job-runtime/calculation/tests"
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            result = suite.run(Path(directory) / "result")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["protocol"], "common-factor-attribution-validation-1")
            self.assertEqual(result["tests"]["focused_expected"], 18)
            self.assertEqual(result["tests"]["focused_observed"], 18)
            self.assertEqual(result["tests"]["total_observed"], 18)
            self.assertEqual(result["tests"]["failures"], [])
            self.assertEqual(result["tests"]["errors"], [])
            self.assertTrue(result["hashes_match"])
            self.assertEqual(result["candidate_hashes"], suite.FROZEN_CANDIDATE_HASHES)
            self.assertEqual(
                {path: sha(path) for path in FROZEN_SUPPORT_HASHES},
                FROZEN_SUPPORT_HASHES,
            )
            receipt = ROOT / result["evidence_paths"][0]
            self.assertTrue(receipt.is_file())
            payload = json.loads(receipt.read_text())
            self.assertEqual(payload["candidate_hashes"], result["candidate_hashes"])
            encoded = json.dumps(payload, sort_keys=True).lower()
            self.assertNotIn("timestamp", encoded)
            self.assertNotIn("generated_at", encoded)

    def test_harness_is_wired_through_one_suite_owner_and_acceptance(self):
        self.assertIs(worker.SUITES, runner.SUITES)
        self.assertIn("common_factor_attribution", runner.SUITES)
        self.assertIn("common_factor_attribution", acceptance.PASS_SUITES)

    def test_observed_dependencies_lock_tolerances_and_limitations_are_frozen(self):
        parent = ROOT / ".job-runtime/calculation/tests"
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            result = suite.run(Path(directory) / "result")
        dependency = result["dependency_policy"]
        self.assertEqual(dependency["expected"]["python"], "3.12.16")
        self.assertEqual(dependency["observed"]["python"], "3.12.16")
        self.assertEqual(dependency["observed"]["python_major_minor"], "3.12")
        self.assertEqual(dependency["observed"]["numpy"], "2.3.5")
        self.assertEqual(dependency["observed"]["scipy"], "1.18.1")
        self.assertTrue(dependency["environment_match"])
        self.assertEqual(
            dependency["requirements_lock"]["observed_sha256"],
            "e2fc05dec11c31df19955f6e866070a65687596ad3fb107b5be2e7a54f74ccb7",
        )
        self.assertTrue(dependency["requirements_lock"]["matches"])
        self.assertEqual(result["tolerance_policy"]["condition_number_maximum"],
                         100000000.0)
        self.assertEqual(result["tolerance_policy"]["maximum_result_components"], 100000)
        self.assertIn("64*float64_eps", result["tolerance_policy"]["minimum_factor_span"])
        self.assertTrue(any("not causal or probabilistic" in item
                            for item in result["limitations"]))
        self.assertTrue(any("cross-platform BLAS bitwise equivalence is not claimed" in item
                            for item in result["limitations"]))
        self.assertTrue(any("registered through the maintained runner and worker owner" in item
                            for item in result["limitations"]))
        self.assertFalse(any("not registered" in item for item in result["limitations"]))
        self.assertFalse(any("does not declare it directly" in item for item in result["limitations"]))


if __name__ == "__main__":
    unittest.main()
