import copy
import json
from pathlib import Path
import unittest

from investment.factor_mining.rdagent_adapter import contracts


ROOT = Path(__file__).resolve().parents[4]
SHA_A = "a" * 64
SHA_B = "b" * 64


def request():
    return {
        "schema_version": 1,
        "kind": "rdagent_factor_request",
        "request_id": "synthetic-one-loop",
        "engine": contracts.engine_contract(),
        "task": {
            "mode": "fin-factor-one-loop",
            "hypothesis": "A synthetic declared factor should produce one nonempty output artifact.",
            "constraints": ["Synthetic fixture only", "No network or upstream imports"],
            "base_features_sha256": None,
            "expected_factor_ids": ["synthetic-factor"],
        },
        "limits": {"timeout_seconds": 10, "stdout_bytes": 65536,
                   "artifact_bytes": 1048576, "max_factors": 1},
        "credential_refs": ["credential-ref-synthetic-provider"],
    }


def receipt(req=None, status="succeeded"):
    req = req or request()
    stages = [{"id": stage_id, "status": "succeeded", "duration_seconds": 0.01,
               "evidence_sha256": SHA_A} for stage_id in contracts.STAGE_IDS]
    artifacts = [
        {"id": "generated-factor-code", "kind": "generated-code", "path": "artifacts/factor.py",
         "sha256": SHA_A, "size_bytes": 10, "factor_ids": ["synthetic-factor"]},
        {"id": "factor-output", "kind": "factor-data", "path": "artifacts/factor.json",
         "sha256": SHA_B, "size_bytes": 20, "factor_ids": ["synthetic-factor"]},
    ]
    failure = None
    if status != "succeeded":
        stages[2] = {"id": "factor-output", "status": "failed", "duration_seconds": 0.01,
                     "evidence_sha256": None}
        artifacts = []
        failure = "FACTOR_OUTPUT_MISSING"
    return {
        "schema_version": 1,
        "kind": "rdagent_factor_receipt",
        "request_sha256": contracts.request_sha256(req),
        "status": status,
        "execution_mode": "synthetic-fixture",
        "engine": contracts.engine_contract(),
        "stages": stages,
        "artifacts": artifacts,
        "failure_code": failure,
        "resources": {"wall_seconds": 0.04, "cpu_seconds": 0.01, "peak_rss_bytes": 1024},
        "process_group_cleanup_verified": True,
    }


class ContractTests(unittest.TestCase):
    def test_request_and_receipt_round_trip_are_canonical(self):
        req = request()
        raw = contracts.canonical(req)
        self.assertEqual(contracts.parse_request(raw), req)
        self.assertEqual(contracts.request_sha256(req), contracts.request_sha256(contracts.parse_request(raw)))
        rec = receipt(req)
        self.assertEqual(contracts.parse_receipt(contracts.canonical(rec), req), rec)

    def test_unknown_duplicate_nonfinite_and_oversize_inputs_fail(self):
        changed = request(); changed["command"] = ["rm", "-rf"]
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_REQUEST_SCHEMA"):
            contracts.validate_request(changed)
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_JSON_DUPLICATE_KEY"):
            contracts.parse_request('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_JSON_NONFINITE"):
            contracts.parse_request('{"value":NaN}')
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_REQUEST_SIZE_LIMIT"):
            contracts.parse_request(b"x" * (contracts.MAX_REQUEST_BYTES + 1))

    def test_engine_command_environment_and_path_injection_fail(self):
        changed = request(); changed["engine"]["qlib_revision"] = "f" * 40
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_ENGINE_MISMATCH"):
            contracts.validate_request(changed)
        changed = request(); changed["task"]["environment"] = {"PATH": "/tmp"}
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_TASK_SCHEMA"):
            contracts.validate_request(changed)
        changed = receipt(); changed["artifacts"][0]["path"] = "../../secret"
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_ARTIFACT_PATH_INVALID"):
            contracts.validate_receipt(changed)
        changed = receipt(); changed["artifacts"][0]["path"] = "/tmp/factor.py"
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_ARTIFACT_PATH_INVALID"):
            contracts.validate_receipt(changed)

    def test_credential_values_and_bad_references_fail(self):
        for value in ("sk-secret-value", "ANTHROPIC_API_KEY=secret", "../credential-ref-x"):
            changed = request(); changed["credential_refs"] = [value]
            with self.subTest(value=value), self.assertRaises(contracts.ContractError):
                contracts.validate_request(changed)

    def test_success_requires_all_stages_and_nonempty_code_and_factor_output(self):
        changed = receipt(); changed["stages"][1]["status"] = "skipped"
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_SUCCESS_STAGES_INVALID"):
            contracts.validate_receipt(changed)
        changed = receipt(); changed["artifacts"] = changed["artifacts"][:1]
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_SUCCESS_ARTIFACTS_MISSING"):
            contracts.validate_receipt(changed)
        changed = receipt(); changed["artifacts"][0]["size_bytes"] = 0
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_ARTIFACT_INVALID"):
            contracts.validate_receipt(changed)

    def test_failure_and_timeout_receipts_are_closed(self):
        failed = receipt(status="failed")
        self.assertEqual(contracts.validate_receipt(failed)["failure_code"], "FACTOR_OUTPUT_MISSING")
        timed = receipt(status="timed_out")
        timed["stages"][2]["status"] = "timed_out"
        timed["failure_code"] = "RUNTIME_TIMEOUT"
        self.assertEqual(contracts.validate_receipt(timed)["status"], "timed_out")
        changed = copy.deepcopy(timed); changed["failure_code"] = "RUNTIME_NONZERO"
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_TIMEOUT_CODE_INVALID"):
            contracts.validate_receipt(changed)

    def test_cleanup_and_request_binding_are_required(self):
        changed = receipt(); changed["process_group_cleanup_verified"] = False
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_CLEANUP_UNVERIFIED"):
            contracts.validate_receipt(changed)
        changed = receipt(); changed["request_sha256"] = SHA_A
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_RECEIPT_REQUEST_MISMATCH"):
            contracts.validate_receipt(changed, request())

    def test_malformed_json_types_raise_contract_errors(self):
        malformed = request(); malformed["credential_refs"] = [{}]
        with self.assertRaises(contracts.ContractError):
            contracts.validate_request(malformed)
        malformed = receipt(); malformed["execution_mode"] = []
        with self.assertRaises(contracts.ContractError):
            contracts.validate_receipt(malformed)
        malformed = receipt(); malformed["artifacts"][0]["kind"] = []
        with self.assertRaises(contracts.ContractError):
            contracts.validate_receipt(malformed)
        malformed = receipt(); malformed["failure_code"] = []
        with self.assertRaises(contracts.ContractError):
            contracts.validate_receipt(malformed)

    def test_success_factor_binding_and_aggregate_budget_are_enforced(self):
        req = request()
        changed = receipt(req); changed["artifacts"][1]["factor_ids"] = ["other-factor"]
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_FACTOR_OUTPUT_MISMATCH"):
            contracts.validate_receipt(changed, req)
        changed = receipt(req)
        changed["artifacts"][0]["size_bytes"] = req["limits"]["artifact_bytes"]
        changed["artifacts"][1]["size_bytes"] = 1
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_ARTIFACT_BUDGET_EXCEEDED"):
            contracts.validate_receipt(changed, req)

    def test_boolean_versions_and_oversized_factor_rosters_are_rejected(self):
        changed = request(); changed["schema_version"] = True
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_REQUEST_VERSION"):
            contracts.validate_request(changed)
        changed = receipt(); changed["schema_version"] = True
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_RECEIPT_VERSION"):
            contracts.validate_receipt(changed)
        changed = receipt(); changed["artifacts"][0]["factor_ids"] = [f"factor-{index}" for index in range(17)]
        with self.assertRaisesRegex(contracts.ContractError, "ADAPTER_ARTIFACT_INVALID"):
            contracts.validate_receipt(changed)

    def test_documented_schemas_are_valid_json_and_match_pins(self):
        base = ROOT / "investment/factor_mining/rdagent_adapter"
        request_schema = json.loads((base / "request-v1.schema.json").read_text())
        receipt_schema = json.loads((base / "receipt-v1.schema.json").read_text())
        self.assertFalse(request_schema["additionalProperties"])
        self.assertFalse(receipt_schema["additionalProperties"])
        self.assertEqual(request_schema["properties"]["engine"]["properties"]["rdagent_revision"]["const"],
                         contracts.RDAGENT_REVISION)
        self.assertEqual(receipt_schema["properties"]["engine"]["properties"]["qlib_revision"]["const"],
                         contracts.QLIB_REVISION)


if __name__ == "__main__":
    unittest.main()
