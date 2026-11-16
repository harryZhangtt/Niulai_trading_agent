import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from investment.factor_mining.rdagent_adapter.v2 import contracts as runner_contracts
from investment.factor_mining.rdagent_adapter.v2 import runner
from tuning.factor_mining.admission_authority import authority
from tuning.factor_mining.evaluator import contract


ROOT = Path(__file__).resolve().parents[4]
DATASET = ROOT / "factor/dataset/fixtures/synthetic-pit-v1"
SEMANTIC_SHA = "a" * 64
SHA_B = "b" * 64


class EvaluatorContractTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / "tuning/factor_mining/runtime/evaluator-contract-tests"
        runtime.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temp.cleanup)
        workspace = Path(self.temp.name) / "workspace"; workspace.mkdir()
        authority.provision_fixture_authority(workspace)
        self.opened = authority.open_fixture_authority(workspace)
        dataset = self.opened.bind_fixture_dataset(DATASET)
        issued = self.opened.issue_fixture_nonce(dataset["event_sha256"], SEMANTIC_SHA)
        payload = dataset["event"]["payload"]
        binding = {
            "authority_id": runner_contracts.AUTHORITY_ID,
            "authority_policy_sha256": runner_contracts.AUTHORITY_POLICY_SHA256,
            "genesis_sha256": runner_contracts.GENESIS_SHA256,
            "admission_policy_sha256": runner_contracts.ADMISSION_POLICY_SHA256,
            "dataset_event_sha256": dataset["event_sha256"],
            "nonce_event_sha256": issued["event_sha256"],
            "nonce_sha256": issued["nonce_sha256"],
            "builder_receipt_sha256": payload["builder_receipt_sha256"],
            "observation_set_sha256": payload["observation_set_sha256"],
            "feature_snapshot_sha256": payload["feature_snapshot_sha256"],
            "evaluation_population_sha256": payload["evaluation_population_sha256"],
            "split_fingerprints": payload["split_fingerprints"],
            "semantic_config_sha256": SEMANTIC_SHA,
        }
        self.runner_request = runner_contracts.validate_request({
            "schema_version": 2, "kind": "rdagent_synthetic_runner_request",
            "request_id": "evaluator-contract-run", "purpose": runner_contracts.PURPOSE,
            "authority_binding": binding, "engine": runner_contracts.engine_contract(),
            "limits": {"artifact_bytes": 65536},
        })
        self.runner_result = runner.run_fixed(self.runner_request, issued["nonce"],
                                              runner.RunnerState(), self.opened)
        self.runner_event = self.opened.record_fixture_runner_receipt(
            issued["nonce"], self.runner_request, self.runner_result["receipt"],
            self.runner_result["artifact"])
        self.evaluator_request = contract.create_request(
            self.runner_request, self.runner_result["receipt"], self.runner_result["artifact"],
            self.runner_event["event_sha256"], self.opened)

    def test_request_and_receipt_are_deterministic_bound_and_outcome_free(self):
        receipt = contract.create_receipt(self.evaluator_request)
        self.assertEqual(receipt, contract.create_receipt(copy.deepcopy(self.evaluator_request)))
        self.assertEqual(receipt["runner_receipt_sha256"],
                         runner_contracts.digest(self.runner_result["receipt"]))
        self.assertEqual(receipt["request_sha256"], contract.digest(self.evaluator_request))
        self.assertEqual(receipt["authority_binding"],
                         self.runner_request["authority_binding"])
        self.assertEqual(receipt["scientific_verdict"], "withheld")
        self.assertEqual(receipt["performance_claim"], "withheld")
        self.assertEqual(receipt["independent_check_status"], "unavailable")
        policy = contract._load_policy()
        self.assertEqual(receipt["registered_sensitivity_ids"],
                         [item["id"] for item in policy["sensitivities"]])
        self.assertEqual(receipt["registered_control_ids"],
                         [item["id"] for item in policy["controls"]])
        self.assertEqual(receipt["registered_quarantine_trigger_ids"],
                         [item["id"] for item in policy["quarantine_triggers"]])
        serialized = json.dumps(receipt)
        for forbidden in ("metrics", "p_value", "interval", "prediction", "position"):
            self.assertNotIn(forbidden, serialized)

    def test_forged_runner_request_receipt_artifact_and_event_fail(self):
        wrong_request = copy.deepcopy(self.evaluator_request)
        wrong_request["runner_request"]["request_id"] = "forged-request"
        wrong_receipt = copy.deepcopy(self.evaluator_request)
        wrong_receipt["runner_receipt"]["request_sha256"] = SHA_B
        wrong_artifact = copy.deepcopy(self.evaluator_request)
        wrong_artifact["runner_artifact"]["observation_set_sha256"] = SHA_B
        wrong_event = copy.deepcopy(self.evaluator_request)
        wrong_event["runner_event_sha256"] = SHA_B
        for value in (wrong_request, wrong_receipt, wrong_artifact, wrong_event):
            with self.subTest(value=value), self.assertRaises(contract.EvaluatorError):
                contract.validate_request(value, fixture_authority=self.opened)

    def test_failed_runner_and_outcome_claims_fail(self):
        failed = copy.deepcopy(self.runner_result["receipt"])
        failed.update(status="failed", artifact=None, failure_code="FIXED_WORKER_REJECTED")
        with self.assertRaisesRegex(contract.EvaluatorError, "RUNNER_NOT_SUCCESSFUL"):
            contract.validate_runner_receipt(failed, self.runner_request)
        outcome = copy.deepcopy(self.runner_result["receipt"]); outcome["outcome_accessed"] = True
        protected = copy.deepcopy(self.runner_result["receipt"]); protected["protected_labels_accessed"] = True
        claim = copy.deepcopy(self.runner_result["receipt"]); claim["performance_claim"] = "available"
        for value in (outcome, protected, claim):
            with self.assertRaises(contract.EvaluatorError):
                contract.validate_runner_receipt(value, self.runner_request)

    def test_receipt_rosters_binding_and_hidden_outcomes_fail(self):
        receipt = contract.create_receipt(self.evaluator_request)
        mutations = []
        missing = copy.deepcopy(receipt); missing["registered_control_ids"].pop(); mutations.append(missing)
        extra = copy.deepcopy(receipt); extra["registered_quarantine_trigger_ids"].append("extra"); mutations.append(extra)
        wrong = copy.deepcopy(receipt); wrong["runner_receipt_sha256"] = SHA_B; mutations.append(wrong)
        metric = copy.deepcopy(receipt); metric["metrics"] = []; mutations.append(metric)
        result = copy.deepcopy(receipt); result["results"] = {}; mutations.append(result)
        secret = copy.deepcopy(receipt); secret["limitations"] = ["api_key=synthetic-canary"]; mutations.append(secret)
        path = copy.deepcopy(receipt); path["limitations"] = ["/Users/private/result.json"]; mutations.append(path)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(contract.EvaluatorError):
                contract.validate_receipt(value, request=self.evaluator_request)

    def test_duplicate_evaluation_and_strict_json_policy_fail(self):
        receipt = contract.create_receipt(self.evaluator_request)
        with self.assertRaisesRegex(contract.EvaluatorError, "DUPLICATE_EVALUATION"):
            contract.validate_receipt_set([receipt, copy.deepcopy(receipt)])
        with self.assertRaisesRegex(contract.EvaluatorError, "DUPLICATE_KEY"):
            contract.loads_strict('{"a":1,"a":2}')
        with self.assertRaisesRegex(contract.EvaluatorError, "NONFINITE"):
            contract.loads_strict('{"a":NaN}')
        with self.assertRaisesRegex(contract.EvaluatorError, "JSON_SIZE"):
            contract.loads_strict(b"x" * (contract.MAX_JSON_BYTES + 1))
        self.assertRegex(contract.evaluator_implementation_sha256(), r"^[a-f0-9]{64}$")
        with mock.patch.object(contract.admission_policy, "digest", return_value=SHA_B):
            with self.assertRaisesRegex(contract.EvaluatorError, "POLICY_MISMATCH"):
                contract.create_receipt(self.evaluator_request)

    def test_schema_documents_reference_actual_runner_contracts(self):
        schemas = sorted(Path(contract.PACKAGE).glob("*.schema.json"))
        self.assertEqual(len(schemas), 2)
        for path in schemas:
            value = json.loads(path.read_text())
            self.assertEqual(set(value["required"]), set(value["properties"]))
        request_schema = json.loads((contract.PACKAGE / "evaluator-request-v1.schema.json").read_text())
        receipt_schema = json.loads((contract.PACKAGE / "evaluator-receipt-v1.schema.json").read_text())
        self.assertEqual(request_schema["properties"]["runner_request"]["$ref"],
                         "../../../investment/factor_mining/rdagent_adapter/v2/request-v2.schema.json")
        self.assertEqual(request_schema["properties"]["runner_receipt"]["$ref"],
                         "../../../investment/factor_mining/rdagent_adapter/v2/receipt-v2.schema.json")
        self.assertEqual(receipt_schema["properties"]["authority_binding"]["$ref"],
                         "../../../investment/factor_mining/rdagent_adapter/v2/request-v2.schema.json#/$defs/binding")
        self.assertEqual(contract.BINDING_FIELDS, frozenset(runner_contracts.BINDING_KEYS))


if __name__ == "__main__":
    unittest.main()
