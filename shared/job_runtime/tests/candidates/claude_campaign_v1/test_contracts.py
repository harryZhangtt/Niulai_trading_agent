import dataclasses
import hashlib
import json
import unittest
from pathlib import Path

from _schema import validate as schema_errors

from shared.job_runtime.candidates.claude_campaign_v1 import (
    Authority, CampaignContractError, CampaignIdentityV1, EvidenceV1,
    classify_authority, evidence_from_json_bytes, evidence_from_mapping,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "claude_campaign_v1"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def rehash(value):
    core = {key: item for key, item in value.items() if key != "evidence_sha256"}
    value["evidence_sha256"] = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return value


class ContractTests(unittest.TestCase):
    def test_r6_r7_r8_authority_table(self):
        expected = {"r6-evidence.json": Authority.SUCCEEDED,
                    "r7-evidence.json": Authority.UNKNOWN,
                    "r8-evidence.json": Authority.UNKNOWN}
        for filename, authority in expected.items():
            with self.subTest(filename=filename):
                item = evidence_from_mapping(load(filename))
                self.assertEqual(classify_authority(item), authority)

    def test_terminal_coherent_failure_and_all_contradictions(self):
        source = load("r6-evidence.json")
        source.update(terminal_disposition="failure", code="TERMINAL_FAILURE")
        self.assertEqual(classify_authority(evidence_from_mapping(rehash(source))), Authority.TERMINAL_FAILED)
        contradictions = [
            {"gateway_disposition": "pass_through", "upstream_forward_count": 0,
             "submission": "not_submitted"},
            {"gateway_disposition": "rejected_before_forward", "upstream_forward_count": 1},
            {"terminal_disposition": "contradictory"},
            {"gateway_disposition": "cut", "upstream_forward_count": 0,
             "submission": "not_submitted"},
            {"typed_transient": True},
        ]
        for mutation in contradictions:
            candidate = load("r6-evidence.json"); candidate.update(mutation)
            self.assertEqual(classify_authority(evidence_from_mapping(rehash(candidate))), Authority.UNKNOWN)

    def test_any_semantic_mutation_rejects_stale_evidence_hash(self):
        base = load("r6-evidence.json")
        mutations = [
            ("upstream_forward_count", lambda value: value.update(
                upstream_forward_count=0, submission="not_submitted")),
            ("typed_transient", lambda value: value.update(typed_transient=True)),
            ("operation_id", lambda value: value["identity"].update(operation_id="changed-operation")),
            ("request_id", lambda value: value["identity"].update(request_id="changed-request")),
            ("source_sha256", lambda value: value["identity"].update(source_sha256="f" * 64)),
            ("code", lambda value: value.update(code="DIFFERENT_CODE")),
        ]
        for name, mutate in mutations:
            with self.subTest(field=name):
                candidate = json.loads(json.dumps(base)); mutate(candidate)
                with self.assertRaisesRegex(CampaignContractError, "EVIDENCE_SHA256_MISMATCH"):
                    evidence_from_mapping(candidate)

    def test_identity_is_frozen_and_every_binding_is_checked(self):
        evidence = evidence_from_mapping(load("r6-evidence.json"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            evidence.identity.slot_id = "slot-2"
        replacements = {
            "campaign_id": "R7", "run_id": "different-run", "job_id": "different-job", "slot_id": "slot-2",
            "attempt_id": "different-attempt", "operation_id": "different-operation",
            "request_id": "different-request", "prompt_id": "different-prompt", "gateway_id": "different-gateway",
            "process_id": "different-process", "prompt_sha256": "a" * 64,
            "source_sha256": "b" * 64, "config_sha256": "c" * 64,
        }
        for field, value in replacements.items():
            with self.subTest(field=field), self.assertRaises(CampaignContractError):
                changed = dataclasses.replace(evidence.identity, **{field: value})
                evidence.validate_binding(changed)

    def test_closed_mapping_rejects_extra_missing_and_bad_hash(self):
        base = load("r6-evidence.json")
        for mutate in (
            lambda value: value.update(extra=True),
            lambda value: value.pop("code"),
            lambda value: value["identity"].update(extra=True),
            lambda value: value["identity"].pop("gateway_id"),
        ):
            candidate = json.loads(json.dumps(base)); mutate(candidate)
            with self.assertRaises(CampaignContractError): evidence_from_mapping(candidate)
        proof = load("r7-evidence.json"); proof["proof_kind"] = "verified_pre_forward"
        with self.assertRaisesRegex(CampaignContractError, "EVIDENCE_KEYS_INVALID"):
            evidence_from_mapping(proof)
        base["evidence_sha256"] = "not-a-hash"
        with self.assertRaisesRegex(CampaignContractError, "EVIDENCE_SHA256_INVALID"):
            evidence_from_mapping(base)

    def test_evidence_schema_and_runtime_contracts(self):
        schema = load("evidence-v1.schema.json")
        for filename in ("r6-evidence.json", "r7-evidence.json", "r8-evidence.json",
                         "r8-forwarded-502-evidence.json"):
            value = load(filename)
            self.assertEqual(schema_errors(value, schema), [])
            evidence_from_mapping(value)
        mutations = [
            lambda value: value["identity"].update(campaign_id="R9"),
            lambda value: value["identity"].update(slot_id="slot-3"),
            lambda value: value["identity"].update(slot_id="slot-2"),
            lambda value: value["identity"].update(job_id="claude-campaign-v1.r7.slot-1"),
            lambda value: value.update(upstream_forward_count=0.5),
            lambda value: value.update(upstream_forward_count=True),
            lambda value: value.update(typed_transient=1),
            lambda value: value.update(version=True),
            lambda value: value.update(extra=False),
        ]
        for mutate in mutations:
            candidate = json.loads(json.dumps(load("r6-evidence.json"))); mutate(candidate)
            self.assertTrue(schema_errors(candidate, schema))
            with self.assertRaises(CampaignContractError):
                evidence_from_mapping(candidate)
        string_fields = ("campaign_id", "run_id", "job_id", "slot_id", "attempt_id", "operation_id",
                         "request_id", "prompt_id", "gateway_id", "process_id", "prompt_sha256",
                         "source_sha256", "config_sha256")
        for field in string_fields:
            candidate = json.loads(json.dumps(load("r6-evidence.json")))
            candidate["identity"][field] = 1
            self.assertTrue(schema_errors(candidate, schema), field)
            with self.assertRaises(CampaignContractError):
                evidence_from_mapping(candidate)
        root_invalid = {
            "gateway_disposition": 1, "terminal_disposition": 1, "code": 1,
            "evidence_sha256": 1, "typed_transient": 0, "upstream_forward_count": False,
        }
        for field, invalid in root_invalid.items():
            candidate = json.loads(json.dumps(load("r6-evidence.json"))); candidate[field] = invalid
            self.assertTrue(schema_errors(candidate, schema), field)
            with self.assertRaises(CampaignContractError):
                evidence_from_mapping(candidate)

    def test_evidence_schema_integral_float_and_runtime_lexical_limit(self):
        schema = load("evidence-v1.schema.json")
        candidate = load("r7-evidence.json")
        candidate["upstream_forward_count"] = 0.0
        self.assertEqual(schema_errors(candidate, schema), [])
        with self.assertRaises(CampaignContractError):
            evidence_from_mapping(candidate)
        candidate["upstream_forward_count"] = False
        self.assertTrue(schema_errors(candidate, schema))

    def test_canonical_json_ingestion_rejects_float_integer_and_duplicates(self):
        raw = (FIXTURES / "r7-evidence.json").read_bytes()
        self.assertEqual(evidence_from_json_bytes(raw), evidence_from_mapping(load("r7-evidence.json")))
        float_count = raw.replace(b'"upstream_forward_count": 0',
                                  b'"upstream_forward_count": 0.0')
        with self.assertRaises(CampaignContractError):
            evidence_from_json_bytes(float_count)
        duplicate = raw.replace(b'{', b'{"version":1,', 1)
        with self.assertRaisesRegex(CampaignContractError, "EVIDENCE_JSON_DUPLICATE_KEY"):
            evidence_from_json_bytes(duplicate)
        with self.assertRaises(CampaignContractError):
            evidence_from_json_bytes(b'{"x": NaN}')

    def test_retry_after_schema_and_runtime_require_positive_exact_integer(self):
        schema = load("evidence-v1.schema.json")
        for invalid in (0, -1, 1.0, True):
            candidate = load("r7-evidence.json")
            candidate["retry_after_seconds"] = invalid
            self.assertTrue(schema_errors(candidate, schema), invalid)
            with self.assertRaises(CampaignContractError):
                evidence_from_mapping(candidate)
        candidate = load("r7-evidence.json")
        self.assertIs(type(candidate["retry_after_seconds"]), int)
        self.assertEqual(schema_errors(candidate, schema), [])
        evidence_from_mapping(candidate)

    def test_schema_documents_close_every_object(self):
        for filename in ("evidence-v1.schema.json", "manifest-v1.schema.json"):
            schema = load(filename)
            stack = [schema]
            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    if item.get("type") == "object":
                        self.assertIs(item.get("additionalProperties"), False, filename)
                    stack.extend(item.values())
                elif isinstance(item, list):
                    stack.extend(item)


if __name__ == "__main__":
    unittest.main()
