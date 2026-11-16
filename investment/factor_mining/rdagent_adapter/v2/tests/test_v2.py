import copy
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from investment.factor_mining.rdagent_adapter import contracts as v1_contracts
from investment.factor_mining.rdagent_adapter.v2 import contracts, runner
from investment.factor_mining.rdagent_adapter.v2 import fixed_worker
from tuning.factor_mining.admission_authority import authority

ROOT = Path(__file__).resolve().parents[5]
DATASET = ROOT / "factor/dataset/fixtures/synthetic-pit-v1"
SHA_A = "a" * 64


def concurrent_runner(workspace, nonce, request, queue):
    try:
        opened = authority.open_fixture_authority(workspace)
        result = runner.run_fixed(request, nonce, runner.RunnerState(), opened)
        queue.put(("ok", result["receipt"]["status"], result["artifact"] is not None))
    except Exception as error:
        queue.put(("error", str(error), False))


class RunnerV2Tests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / "investment/factor_mining/runtime/v2-runner-tests"
        runtime.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        authority.provision_fixture_authority(self.workspace)
        self.opened = authority.open_fixture_authority(self.workspace)
        self.dataset_event = self.opened.bind_fixture_dataset(DATASET)
        self.issued = self.opened.issue_fixture_nonce(self.dataset_event["event_sha256"], SHA_A)
        payload = self.dataset_event["event"]["payload"]
        self.binding = {
            "authority_id": contracts.AUTHORITY_ID,
            "authority_policy_sha256": contracts.AUTHORITY_POLICY_SHA256,
            "genesis_sha256": contracts.GENESIS_SHA256,
            "admission_policy_sha256": contracts.ADMISSION_POLICY_SHA256,
            "dataset_event_sha256": self.dataset_event["event_sha256"],
            "nonce_event_sha256": self.issued["event_sha256"],
            "nonce_sha256": self.issued["nonce_sha256"],
            "builder_receipt_sha256": payload["builder_receipt_sha256"],
            "observation_set_sha256": payload["observation_set_sha256"],
            "feature_snapshot_sha256": payload["feature_snapshot_sha256"],
            "evaluation_population_sha256": payload["evaluation_population_sha256"],
            "split_fingerprints": payload["split_fingerprints"],
            "semantic_config_sha256": SHA_A,
        }
        self.request = {
            "schema_version": 2,
            "kind": "rdagent_synthetic_runner_request",
            "request_id": "synthetic-authority-run",
            "purpose": contracts.PURPOSE,
            "authority_binding": self.binding,
            "engine": contracts.engine_contract(),
            "limits": {"artifact_bytes": 65536},
        }

    def test_success_binds_request_dataset_nonce_and_withholds_outcomes(self):
        state = runner.RunnerState()
        result = runner.run_fixed(self.request, self.issued["nonce"], state, self.opened)
        receipt = contracts.validate_receipt(result["receipt"], self.request)
        self.assertEqual(receipt["status"], "synthetic-structural-complete")
        self.assertEqual(result["receipt_sha256"], contracts.digest(receipt))
        self.assertEqual(receipt["artifact"]["sha256"],
                         __import__("hashlib").sha256(result["artifact"]).hexdigest())
        serialized = contracts.canonical({"receipt": receipt,
                                          "artifact": result["artifact"].decode()}).decode()
        self.assertNotIn(self.issued["nonce"], serialized)
        for marker in ("label_values", "protected_metric", "point_estimate", "metrics"):
            self.assertNotIn(marker, result["artifact"].decode())
        self.assertIn('"performance_claim":"withheld"', result["artifact"].decode())
        authority_result = self.opened.record_fixture_runner_receipt(
            self.issued["nonce"], self.request, receipt, result["artifact"])
        self.assertEqual(authority_result["event"]["payload"]["runner_receipt_sha256"],
                         result["receipt_sha256"])

    def test_nonce_is_out_of_band_exact_and_one_time(self):
        state = runner.RunnerState()
        with self.assertRaisesRegex(runner.RunnerError, "NONCE_MISMATCH"):
            runner.run_fixed(self.request, "0" * 64, state, self.opened)
        runner.run_fixed(self.request, self.issued["nonce"], state, self.opened)
        with self.assertRaisesRegex(runner.RunnerError, "NONCE_CLAIM_REJECTED"):
            runner.run_fixed(self.request, self.issued["nonce"], state, self.opened)
        self.assertNotIn(self.issued["nonce"], contracts.canonical(self.request).decode())

    def test_fabricated_authority_lineage_fails_before_nonce_consumption(self):
        for key in ("dataset_event_sha256", "nonce_event_sha256",
                    "observation_set_sha256", "semantic_config_sha256"):
            request = copy.deepcopy(self.request)
            request["authority_binding"][key] = "b" * 64
            with self.subTest(key=key), self.assertRaisesRegex(
                    runner.RunnerError, "AUTHORITY_BINDING_INVALID"):
                runner.run_fixed(request, self.issued["nonce"],
                                 runner.RunnerState(), self.opened)
        valid = runner.run_fixed(self.request, self.issued["nonce"],
                                 runner.RunnerState(), self.opened)
        self.assertEqual(valid["receipt"]["status"], "synthetic-structural-complete")

    def test_wrong_authority_object_is_rejected(self):
        for value in (None, object(), "authority"):
            with self.subTest(value=type(value).__name__), self.assertRaisesRegex(
                    runner.RunnerError, "AUTHORITY_INVALID"):
                runner.run_fixed(self.request, self.issued["nonce"],
                                 runner.RunnerState(), value)

    def test_valid_artifact_budget_failure_is_recorded_and_nonce_stays_claimed(self):
        request = copy.deepcopy(self.request)
        request["limits"]["artifact_bytes"] = 256
        state = runner.RunnerState()
        result = runner.run_fixed(request, self.issued["nonce"], state, self.opened)
        self.assertEqual(result["receipt"]["status"], "failed")
        self.assertEqual(result["receipt"]["failure_code"], "FIXED_WORKER_REJECTED")
        recorded = self.opened.record_fixture_runner_receipt(
            self.issued["nonce"], request, result["receipt"], None)
        self.assertEqual(recorded["event"]["payload"]["terminal_status"], "failed")
        with self.assertRaisesRegex(runner.RunnerError, "NONCE_CLAIM_REJECTED"):
            runner.run_fixed(request, self.issued["nonce"], runner.RunnerState(), self.opened)

    def test_contracts_reject_hidden_controls_bad_types_and_nonfinite(self):
        for key, value in (("command", ["/bin/sh"]), ("environment", {"TOKEN": "x"}),
                           ("credential_refs", ["secret"])):
            changed = copy.deepcopy(self.request); changed[key] = value
            with self.subTest(key=key), self.assertRaises(contracts.ContractError):
                contracts.validate_request(changed)
        changed = copy.deepcopy(self.request); changed["limits"]["timeout_seconds"] = 10
        with self.assertRaises(contracts.ContractError):
            contracts.validate_request(changed)
        with self.assertRaisesRegex(contracts.ContractError, "NONFINITE"):
            contracts.parse_request(b'{"value":NaN}')
        with self.assertRaisesRegex(contracts.ContractError, "SIZE"):
            contracts.parse_request(b"x" * (contracts.MAX_REQUEST_BYTES + 1))

    def test_receipt_binding_artifact_and_fixture_claims_fail_closed(self):
        result = runner.run_fixed(self.request, self.issued["nonce"],
                                  runner.RunnerState(), self.opened)
        mutations = []
        wrong_request = copy.deepcopy(result["receipt"]); wrong_request["request_sha256"] = "f" * 64; mutations.append(wrong_request)
        outcome = copy.deepcopy(result["receipt"]); outcome["outcome_accessed"] = True; mutations.append(outcome)
        protected = copy.deepcopy(result["receipt"]); protected["protected_labels_accessed"] = True; mutations.append(protected)
        claim = copy.deepcopy(result["receipt"]); claim["performance_claim"] = "available"; mutations.append(claim)
        artifact = copy.deepcopy(result["receipt"]); artifact["artifact"]["size_bytes"] = 0; mutations.append(artifact)
        for changed in mutations:
            with self.assertRaises(contracts.ContractError):
                contracts.validate_receipt(changed, self.request)

    def test_claimed_unknown_outcome_blocks_replay_before_worker(self):
        self.opened.claim_fixture_nonce(self.issued["nonce"], self.binding)
        with mock.patch.object(fixed_worker, "build_artifact", wraps=fixed_worker.build_artifact) as worker:
            with self.assertRaisesRegex(runner.RunnerError, "NONCE_CLAIM_REJECTED"):
                runner.run_fixed(self.request, self.issued["nonce"],
                                 runner.RunnerState(), self.opened)
            worker.assert_not_called()

    def test_concurrent_processes_only_claim_winner_reaches_worker(self):
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        workers = [context.Process(target=concurrent_runner,
                    args=(str(self.workspace), self.issued["nonce"], self.request, queue))
                   for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(15)
        results = [queue.get(timeout=2) for _ in workers]
        self.assertEqual(sum(item[0] == "ok" and item[2] for item in results), 1)
        self.assertEqual(sum(item[0] == "error" and "NONCE_CLAIM_REJECTED" in item[1]
                             for item in results), 1)

    def test_runner_does_not_read_label_value_files(self):
        original = Path.read_bytes
        reads = []
        def guarded(path):
            if "label-values" in path.name:
                reads.append(str(path))
                raise AssertionError("label values must not be read")
            return original(path)
        with mock.patch.object(Path, "read_bytes", guarded):
            result = runner.run_fixed(self.request, self.issued["nonce"],
                                      runner.RunnerState(), self.opened)
        self.assertEqual(result["receipt"]["status"], "synthetic-structural-complete")
        self.assertEqual(reads, [])

    def test_behavior_identities_bind_contract_worker_and_authority_semantics(self):
        contract_identity = contracts.implementation_sha256()
        worker_identity = fixed_worker.implementation_sha256()
        runner_identity = runner.implementation_sha256()
        with mock.patch.object(contracts, "BINDING_KEYS", set(contracts.BINDING_KEYS) | {"extra"}):
            self.assertNotEqual(contract_identity, contracts.implementation_sha256())
            self.assertNotEqual(runner_identity, runner.implementation_sha256())
        with mock.patch.object(fixed_worker, "REQUIRED_BINDINGS",
                               tuple(fixed_worker.REQUIRED_BINDINGS) + ("extra",)):
            self.assertNotEqual(worker_identity, fixed_worker.implementation_sha256())
            self.assertNotEqual(runner_identity, runner.implementation_sha256())
        with mock.patch.object(authority, "MAX_JSON", authority.MAX_JSON + 1):
            self.assertNotEqual(runner_identity, runner.implementation_sha256())

    def test_runner_identity_is_repeatable_across_calls_runs_and_fresh_process(self):
        expected = runner.implementation_sha256()
        self.assertEqual(expected, runner.implementation_sha256())
        result = runner.run_fixed(self.request, self.issued["nonce"],
                                  runner.RunnerState(), self.opened)
        self.assertEqual(result["receipt"]["runner_implementation_sha256"], expected)
        self.assertEqual(runner.implementation_sha256(), expected)
        process = subprocess.run(
            [sys.executable, "-B", "-c",
             "from investment.factor_mining.rdagent_adapter.v2.runner import implementation_sha256; print(implementation_sha256())"],
            cwd=ROOT, capture_output=True, text=True, timeout=20, check=True)
        self.assertEqual(process.stdout.strip(), expected)

    def test_schemas_are_exact_and_v1_v2_namespaces_are_isolated(self):
        for name in ("request-v2.schema.json", "receipt-v2.schema.json"):
            value = json.loads((Path(__file__).resolve().parents[1] / name).read_text())
            self.assertEqual(set(value["required"]), set(value["properties"]))
        self.assertEqual(v1_contracts.ADAPTER_VERSION, "rdagent-adapter-v1")
        self.assertEqual(v1_contracts.engine_contract()["adapter_version"],
                         "rdagent-adapter-v1")
        self.assertNotEqual(contracts.engine_contract()["adapter_version"],
                            v1_contracts.engine_contract()["adapter_version"])


if __name__ == "__main__":
    unittest.main()
