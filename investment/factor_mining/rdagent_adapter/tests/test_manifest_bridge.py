from pathlib import Path
import tempfile
import unittest

from investment.factor_mining.rdagent_adapter import manifest_bridge, runner
from investment.factor_mining.rdagent_adapter.tests.test_contracts import request
from shared.factor_mining import manifest


ROOT = Path(__file__).resolve().parents[4]
class ManifestBridgeTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / "investment/factor_mining/runtime/manifest-bridge-tests"
        runtime.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.boundary_root = self.base / "boundary"
        self.registry = self.base / "registry"

    def execute(self, mode):
        req = request(); req["request_id"] = "manifest-" + mode
        result = runner.run_synthetic(req, mode, self.boundary_root)
        value = manifest_bridge.build(req, result, "2026-11-04T00:00:00Z")
        value = manifest_bridge.bind_receipt_size(value, self.boundary_root)
        published = manifest.publish(value, self.registry, self.boundary_root)
        loaded = manifest.load_head(self.registry, req["request_id"])["manifest"]
        return result, published, loaded

    def test_success_is_fixture_only_and_withholds_performance(self):
        result, published, loaded = self.execute("success")
        self.assertEqual(loaded["status"], "succeeded")
        self.assertEqual(loaded["provenance"],
                         {"origin": "synthetic_fixture", "evidence": "fixture_only"})
        self.assertEqual(next(g for g in loaded["gates"] if g["id"] == "implementation")["status"],
                         "pass")
        for gate_id in ("predictive", "economic", "publication"):
            self.assertEqual(next(g for g in loaded["gates"] if g["id"] == gate_id)["status"],
                             "withheld")
        self.assertEqual(loaded["factors"], [])
        self.assertTrue(published["manifest_sha256"])

    def test_missing_output_is_immutable_failed_fixture_manifest(self):
        result, _, loaded = self.execute("missing-output")
        self.assertEqual(result["receipt"]["failure_code"], "FACTOR_OUTPUT_MISSING")
        self.assertEqual(loaded["status"], "failed")
        self.assertEqual(loaded["failures"][0]["code"], "factor-output-missing")
        self.assertEqual(next(g for g in loaded["gates"] if g["id"] == "implementation")["status"],
                         "fail")
        self.assertEqual(next(g for g in loaded["gates"] if g["id"] == "publication")["status"],
                         "withheld")


if __name__ == "__main__":
    unittest.main()
