"""Strict schema, custody, admission, and publication tests."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import unittest

from shared.job_runtime.candidates.r6_one_off_evidence_v1.contracts import (
    ContractError, admission_key, request_fingerprint, validate_evidence,
    validate_grant, validate_publication_receipt,
)
from shared.job_runtime.candidates.r6_one_off_evidence_v1.custody import (
    AdmissionLedger, CustodyError, CustodySession,
)
from shared.job_runtime.candidates.r6_one_off_evidence_v1.publication import (
    PublicationError, publish_evidence,
)
from shared.job_runtime.candidates.r6_one_off_evidence_v1.runner import (
    execute_provider_free, materialize_provider_free_case,
)
from shared.job_runtime.tests.candidates.r6_one_off_evidence_v1._support import (
    FIXTURES, historical, temporary_parent, transport_for,
)

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None

SOURCE = Path(__file__).resolve().parents[3] / "candidates" / "r6_one_off_evidence_v1"


class ContractsCustodyPublicationTests(unittest.TestCase):
    def setUp(self):
        self.jobs, self.nonces, _ = historical()
        self.temp = temporary_parent()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def prepare(self, scenario="nominal", name="workspace"):
        prepared = materialize_provider_free_case(
            self.base / name, scenario, self.jobs, self.nonces)
        self.addCleanup(prepared.close)
        return prepared

    def test_custom_contracts_reject_extra_authority_and_partial_pass(self):
        prepared = self.prepare()
        validate_grant(prepared.grant, self.jobs, self.nonces)
        extra = copy.deepcopy(prepared.grant)
        extra["operation_id"] = "reserved"
        with self.assertRaisesRegex(ContractError, "GRANT_KEYS_INVALID"):
            validate_grant(extra, self.jobs, self.nonces)
        authorized = copy.deepcopy(prepared.grant)
        authorized["provider_authorized"] = True
        with self.assertRaisesRegex(ContractError, "PROVIDER_FREE_CONSTANT_INVALID"):
            validate_grant(authorized, self.jobs, self.nonces)
        result = execute_provider_free(
            prepared, transport_for("nominal", []), self.jobs, self.nonces)
        partial_pass = copy.deepcopy(result.evidence)
        partial_pass["terminal"] = "truncated"
        with self.assertRaisesRegex(ContractError, "EVIDENCE_STATE_CONFLICT"):
            validate_evidence(partial_pass)

    @unittest.skipUnless(Draft202012Validator is not None,
                         "Draft 2020-12 validator unavailable")
    def test_four_draft202012_schemas_are_strict_and_validate_instances(self):
        schemas = {}
        for name in (
                "one-off-grant-v1.schema.json",
                "engine-execution-binding-v1.schema.json",
                "r6-evidence-v1.schema.json",
                "publication-receipt-v1.schema.json"):
            schema = json.loads((SOURCE / name).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self.assertFalse(schema["additionalProperties"])
            schemas[name] = schema
        prepared = self.prepare()
        result = execute_provider_free(
            prepared, transport_for("nominal", []), self.jobs, self.nonces)
        instances = {
            "one-off-grant-v1.schema.json": result.grant,
            "engine-execution-binding-v1.schema.json": result.binding,
            "r6-evidence-v1.schema.json": result.evidence,
            "publication-receipt-v1.schema.json": result.publication,
        }
        for name, instance in instances.items():
            Draft202012Validator(schemas[name], format_checker=None).validate(instance)
            bad = copy.deepcopy(instance)
            bad["unexpected"] = True
            self.assertFalse(Draft202012Validator(schemas[name]).is_valid(bad))

    def test_descriptor_custody_rejects_drift_symlink_and_public_raw(self):
        prepared = self.prepare()
        prepared.custody.verify()
        prepared.inject_drift("parser")
        with self.assertRaises(CustodyError):
            prepared.custody.verify()

        unsafe_root = self.base / "unsafe"
        unsafe_root.mkdir(mode=0o700)
        target = unsafe_root / "target"
        target.write_bytes(b"synthetic")
        target.chmod(0o600)
        (unsafe_root / "alias").symlink_to(target)
        with self.assertRaises(CustodyError):
            CustodySession.seal(unsafe_root, {"prompt": "alias"})

    def test_admission_key_is_exact_durable_single_use_before_forward(self):
        root = self.base / "ledger"
        ledger = AdmissionLedger(root)
        request = {"version": 1, "operation_id": "operation/synthetic"}
        fingerprint = request_fingerprint(request)
        expected = admission_key("operation/synthetic", fingerprint)
        receipt = ledger.admit("operation/synthetic", fingerprint, "attempt/synthetic")
        self.assertEqual(receipt["admission_key"], expected)
        self.assertTrue(receipt["durable_before_forward"])
        path = root / (expected + ".json")
        self.assertTrue(path.is_file())
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(CustodyError, "CUSTODY_NO_OVERWRITE"):
            ledger.admit("operation/synthetic", fingerprint, "attempt/synthetic")

    def test_publication_is_allowlisted_atomic_no_overwrite(self):
        prepared = self.prepare()
        result = execute_provider_free(
            prepared, transport_for("nominal", []), self.jobs, self.nonces)
        validate_publication_receipt(result.publication)
        public_path = prepared.public_root / "r6-evidence.json"
        public = json.loads(public_path.read_text(encoding="ascii"))
        self.assertEqual(public, result.evidence)
        encoded = public_path.read_bytes()
        self.assertNotIn(b"synthetic.completed", encoded)
        self.assertNotIn(str(prepared.workspace).encode(), encoded)
        with self.assertRaisesRegex(PublicationError, "PUBLICATION_NO_OVERWRITE"):
            publish_evidence(result.evidence, prepared.public_root)
        self.assertEqual(public_path.read_bytes(), encoded)


if __name__ == "__main__":
    unittest.main()
