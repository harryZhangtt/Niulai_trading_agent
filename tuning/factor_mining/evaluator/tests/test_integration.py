from pathlib import Path
import tempfile
import unittest

from factor.dataset import build_snapshot
from investment.factor_mining.rdagent_adapter.v2 import contracts as runner_contracts
from investment.factor_mining.rdagent_adapter.v2 import runner
from tuning.factor_mining.admission_authority import authority
from tuning.factor_mining.evaluator import contract


ROOT = Path(__file__).resolve().parents[4]
DATASET = ROOT / "factor/dataset/fixtures/synthetic-pit-v1"
SEMANTIC_SHA = "a" * 64


class EvaluatorIntegrationTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / "tuning/factor_mining/runtime/evaluator-tests"
        runtime.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        authority.provision_fixture_authority(self.workspace)
        self.opened = authority.open_fixture_authority(self.workspace)
        self.dataset_event = self.opened.bind_fixture_dataset(DATASET)
        self.build = build_snapshot(DATASET)

    def issue(self):
        issued = self.opened.issue_fixture_nonce(self.dataset_event["event_sha256"], SEMANTIC_SHA)
        payload = self.dataset_event["event"]["payload"]
        binding = {
            "authority_id": runner_contracts.AUTHORITY_ID,
            "authority_policy_sha256": runner_contracts.AUTHORITY_POLICY_SHA256,
            "genesis_sha256": runner_contracts.GENESIS_SHA256,
            "admission_policy_sha256": runner_contracts.ADMISSION_POLICY_SHA256,
            "dataset_event_sha256": self.dataset_event["event_sha256"],
            "nonce_event_sha256": issued["event_sha256"],
            "nonce_sha256": issued["nonce_sha256"],
            "builder_receipt_sha256": payload["builder_receipt_sha256"],
            "observation_set_sha256": payload["observation_set_sha256"],
            "feature_snapshot_sha256": payload["feature_snapshot_sha256"],
            "evaluation_population_sha256": payload["evaluation_population_sha256"],
            "split_fingerprints": payload["split_fingerprints"],
            "semantic_config_sha256": SEMANTIC_SHA,
        }
        request = {
            "schema_version": 2, "kind": "rdagent_synthetic_runner_request",
            "request_id": "synthetic-authority-evaluator-run",
            "purpose": runner_contracts.PURPOSE,
            "authority_binding": binding,
            "engine": runner_contracts.engine_contract(),
            "limits": {"artifact_bytes": 65536},
        }
        return issued, runner_contracts.validate_request(request)

    def test_full_authority_runner_evaluator_chain_reconciles_hashes(self):
        issued, request = self.issue()
        runner_result = runner.run_fixed(request, issued["nonce"],
                                         runner.RunnerState(), self.opened)
        runner_receipt = runner_contracts.validate_receipt(runner_result["receipt"], request)
        runner_event = self.opened.record_fixture_runner_receipt(
            issued["nonce"], request, runner_receipt, runner_result["artifact"])
        evaluator_request = contract.create_request(
            request, runner_receipt, runner_result["artifact"],
            runner_event["event_sha256"], self.opened)
        evaluator_receipt = contract.create_receipt(evaluator_request)
        self.assertEqual(evaluator_receipt["runner_receipt_sha256"],
                         runner_result["receipt_sha256"])
        evaluator_sha = contract.digest(evaluator_receipt)
        evaluator_event = self.opened.record_fixture_evaluator_receipt(
            runner_event["event_sha256"], evaluator_request, evaluator_receipt)
        self.assertEqual(evaluator_event["event"]["payload"]["runner_receipt_sha256"],
                         runner_result["receipt_sha256"])
        self.assertEqual(evaluator_event["event"]["payload"]["evaluator_receipt_sha256"],
                         evaluator_sha)
        self.assertEqual(self.opened.status()["sequence"], 5)
        self.assertEqual(evaluator_receipt["scientific_verdict"], "withheld")
        self.assertFalse(evaluator_receipt["outcome_accessed"])
        self.assertFalse(evaluator_receipt["protected_labels_accessed"])

    def test_failed_actual_runner_is_not_evaluable(self):
        issued, request = self.issue()
        request["limits"]["artifact_bytes"] = 256
        request = runner_contracts.validate_request(request)
        result = runner.run_fixed(request, issued["nonce"],
                                  runner.RunnerState(), self.opened)
        self.assertEqual(result["receipt"]["status"], "failed")
        with self.assertRaisesRegex(contract.EvaluatorError, "RUNNER_NOT_SUCCESSFUL"):
            contract.create_request(request, result["receipt"], {}, "b" * 64, self.opened)


if __name__ == "__main__":
    unittest.main()
