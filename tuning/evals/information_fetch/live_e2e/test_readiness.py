from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from tuning.evals.information_fetch.live_e2e.readiness import (
    CASE_PACKET_PATH,
    VERSION_V2,
    ReadinessError,
    canonical_bytes,
    canonical_effective_config,
    load_and_validate,
    seal_packet,
    validate_case_packet_envelope,
    validate_envelope,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.envelope = json.loads((HERE / "readiness-template.json").read_bytes())

    def ready_packet(self):
        packet = deepcopy(self.envelope["packet"])
        packet["status"] = "ready"
        packet["unresolved"] = []
        packet["budgets"].update({"run_wall_seconds": 60, "provider_call_seconds": 10})
        packet["artifacts"].update({
            "artifact_root": "investment/runtime/acquisition",
            "runtime_root": "investment/runtime", "raw_retention": "delete_after_review",
            "reconciliation_owner": "runtime-owner", "retention_owner": "custody-owner",
            "rollback_target": "candidate-parent",
        })
        packet["source_contract"]["cutoff"] = "2026-11-05T00:00:00+00:00"
        packet["effective_config"] = canonical_effective_config(ROOT)
        return packet

    def test_v2_derives_exact_live_authority_and_rejects_mutation(self):
        packet = self.ready_packet()
        validate_envelope(seal_packet(packet), root=ROOT)
        contract = __import__(
            "tuning.evals.information_fetch.live_e2e.readiness",
            fromlist=["derive_live_contract"]).derive_live_contract(packet)
        self.assertEqual(contract["run_kind"], "narrow")
        self.assertEqual(contract["question"]["question"], packet["case"]["question"])
        self.assertEqual(contract["proposals"][0]["arguments"]["search_query"][0]["q"],
                         packet["case"]["search_query"])
        self.assertEqual(contract["proposals"][1]["arguments"]["open"][0]["ref_id"],
                         packet["case"]["primary_pdf_url"])
        self.assertEqual(contract["proposals"][1]["alternates"][0]["exact_arguments"]["open"][0]["ref_id"],
                         packet["case"]["alternate_html_url"])

        smoke = deepcopy(packet)
        smoke["run_kind"] = "smoke"
        smoke["budgets"].update({"open_items": 0, "provider_items": 1, "fallbacks": 0})
        validate_envelope(seal_packet(smoke), root=ROOT)
        self.assertEqual(len(__import__(
            "tuning.evals.information_fetch.live_e2e.readiness",
            fromlist=["derive_live_contract"]).derive_live_contract(smoke)["proposals"]), 1)

    def test_repository_derived_template_has_approved_pair_but_is_not_operationally_ready(self):
        verdict = validate_envelope(self.envelope, root=ROOT)
        self.assertTrue(verdict["seal_valid"])
        self.assertTrue(verdict["structural_evidence_only"])
        self.assertFalse(verdict["ready_for_provider_authorization_request"])
        self.assertEqual(verdict["reason"], "READINESS_UNRESOLVED")
        packet = self.envelope["packet"]
        self.assertFalse(packet["case"]["quote_preselected"])
        self.assertEqual(packet["equivalence_review"]["status"], "approved")
        self.assertIn("Q4 CDN", packet["equivalence_review"]["caveat"])
        self.assertNotIn("exact_equivalent_pdf_html_pair", packet["unresolved"])

    def test_mutation_breaks_seal(self):
        changed = deepcopy(self.envelope)
        changed["packet"]["budgets"]["provider_items"] = 4
        with self.assertRaisesRegex(ReadinessError, "READINESS_SEAL_INVALID"):
            validate_envelope(changed, root=ROOT)

    def test_resealed_budget_expansion_and_quote_are_rejected(self):
        changed = deepcopy(self.envelope["packet"])
        changed["budgets"]["provider_items"] = 4
        with self.assertRaisesRegex(ReadinessError, "READINESS_BUDGET_INVALID"):
            validate_envelope(seal_packet(changed), root=ROOT)
        changed = deepcopy(self.envelope["packet"])
        changed["case"]["selected_quote"] = "must never be frozen in readiness"
        with self.assertRaisesRegex(ReadinessError, "READINESS_QUOTE_PRESELECTED"):
            validate_envelope(seal_packet(changed), root=ROOT)

    def test_repository_evidence_hash_is_recomputed(self):
        changed = deepcopy(self.envelope["packet"])
        changed["repository_evidence"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ReadinessError, "READINESS_EVIDENCE_CHANGED"):
            validate_envelope(seal_packet(changed), root=ROOT)

    def test_complete_repository_bound_packet_can_request_authorization(self):
        verdict = validate_envelope(seal_packet(self.ready_packet()), root=ROOT)
        self.assertTrue(verdict["ready_for_provider_authorization_request"])

    def test_ready_claim_rejects_malformed_urls_and_empty_review(self):
        packet = self.ready_packet()
        packet["case"]["primary_pdf_url"] = "not-a-url"
        with self.assertRaisesRegex(ReadinessError, "READINESS_URL_INVALID"):
            validate_envelope(seal_packet(packet), root=ROOT)

        packet = self.ready_packet()
        packet["equivalence_review"]["reviewer_id"] = ""
        with self.assertRaisesRegex(ReadinessError, "READINESS_EQUIVALENCE_INVALID"):
            validate_envelope(seal_packet(packet), root=ROOT)

    def test_ready_claim_rejects_bogus_config_and_missing_owners(self):
        packet = self.ready_packet()
        packet["effective_config"]["sha256"] = "not-a-hash"
        with self.assertRaisesRegex(ReadinessError, "READINESS_EFFECTIVE_CONFIG_INVALID"):
            validate_envelope(seal_packet(packet), root=ROOT)

        packet = self.ready_packet()
        packet["effective_config"]["inputs"]["runner"] = dict(
            packet["effective_config"]["inputs"]["checker"])
        with self.assertRaisesRegex(ReadinessError, "READINESS_EFFECTIVE_CONFIG_INVALID"):
            validate_envelope(seal_packet(packet), root=ROOT)

        packet = self.ready_packet()
        packet["artifacts"]["retention_owner"] = ""
        with self.assertRaisesRegex(ReadinessError, "READINESS_ARTIFACTS_INVALID"):
            validate_envelope(seal_packet(packet), root=ROOT)

    def test_quote_key_variants_are_rejected(self):
        packet = deepcopy(self.envelope["packet"])
        packet["case"]["selectedQuote"] = "forbidden"
        with self.assertRaisesRegex(ReadinessError, "READINESS_QUOTE_PRESELECTED"):
            validate_envelope(seal_packet(packet), root=ROOT)

    def test_v3_effective_config_is_acyclic_and_byte_stable(self):
        first = canonical_effective_config(ROOT)
        second = canonical_effective_config(ROOT)
        self.assertEqual(first, second)
        self.assertEqual(first, self.envelope["packet"]["effective_config"])
        case_row = first["inputs"]["case_packet"]
        self.assertEqual(case_row["path"], CASE_PACKET_PATH)
        self.assertNotEqual(case_row["path"],
                            "tuning/evals/information_fetch/live_e2e/readiness-template.json")
        case_envelope = json.loads((ROOT / case_row["path"]).read_text())
        validate_case_packet_envelope(case_envelope)
        self.assertNotIn("effective_config", case_envelope["case_packet"])
        self.assertNotIn("seal", case_envelope["case_packet"])
        rebuilt = seal_packet({**deepcopy(self.envelope["packet"]),
                               "effective_config": first})
        self.assertEqual(canonical_bytes(rebuilt), canonical_bytes(self.envelope))

    def test_v2_self_reference_fixed_fails(self):
        changed = deepcopy(self.envelope["packet"])
        changed["schema_version"] = VERSION_V2
        with self.assertRaisesRegex(ReadinessError,
                                    "READINESS_SELF_REFERENCE_DISABLED"):
            validate_envelope(seal_packet(changed), root=ROOT)

    def test_case_packet_mutation_and_template_drift_fail(self):
        case_path = ROOT / CASE_PACKET_PATH
        case_envelope = json.loads(case_path.read_text())
        changed_case = deepcopy(case_envelope)
        changed_case["case_packet"]["case"]["question"] += " changed"
        with self.assertRaisesRegex(ReadinessError,
                                    "READINESS_CASE_PACKET_INVALID"):
            validate_case_packet_envelope(changed_case)
        changed_template = deepcopy(self.envelope["packet"])
        changed_template["case"]["question"] += " changed"
        with self.assertRaisesRegex(ReadinessError,
                                    "READINESS_CASE_PACKET_MISMATCH"):
            validate_envelope(seal_packet(changed_template), root=ROOT)

    def test_effective_config_missing_or_extra_ref_fails(self):
        missing = deepcopy(self.envelope["packet"])
        del missing["effective_config"]["inputs"]["case_packet"]
        with self.assertRaisesRegex(ReadinessError,
                                    "READINESS_EFFECTIVE_CONFIG_INVALID"):
            validate_envelope(seal_packet(missing), root=ROOT)
        extra = deepcopy(self.envelope["packet"])
        extra["effective_config"]["inputs"]["unexpected"] = {
            "path": CASE_PACKET_PATH,
            "sha256": hashlib.sha256((ROOT / CASE_PACKET_PATH).read_bytes()).hexdigest(),
        }
        with self.assertRaisesRegex(ReadinessError,
                                    "READINESS_EFFECTIVE_CONFIG_INVALID"):
            validate_envelope(seal_packet(extra), root=ROOT)

    def test_readiness_and_case_packet_schemas_validate(self):
        for name, value in (
            ("readiness.schema.json", self.envelope),
            ("readiness-case-packet.schema.json",
             json.loads((HERE / "readiness-case-packet.json").read_text())),
        ):
            schema = json.loads((HERE / name).read_text())
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(value)

    def test_runtime_closed_shapes_reject_unknown_members(self):
        for location in ("packet", "seal", "effective_config", "case", "budgets",
                         "identity_rules", "artifacts", "source_contract", "url_policy",
                         "equivalence_review", "question_contract"):
            changed = deepcopy(self.envelope)
            if location == "packet":
                target = changed["packet"]
            elif location == "seal":
                target = changed["seal"]
            else:
                target = changed["packet"][location]
            target["self_reference"] = "tuning/evals/information_fetch/live_e2e/readiness-template.json"
            if location != "seal":
                changed = seal_packet(changed["packet"])
            with self.subTest(location=location):
                with self.assertRaises(ReadinessError):
                    validate_envelope(changed, root=ROOT)

    def test_alternate_relative_case_packet_paths_rejected(self):
        for path in ("./" + CASE_PACKET_PATH,
                     "tuning/evals/information_fetch/live_e2e/../live_e2e/readiness-case-packet.json",
                     CASE_PACKET_PATH.replace("/", "//")):
            changed = deepcopy(self.envelope["packet"])
            changed["effective_config"]["inputs"]["case_packet"]["path"] = path
            with self.subTest(path=path):
                with self.assertRaisesRegex(ReadinessError,
                                            "READINESS_EFFECTIVE_CONFIG_INVALID"):
                    validate_envelope(seal_packet(changed), root=ROOT)

    def test_derive_requires_prior_ready_v3_validation(self):
        derive = __import__(
            "tuning.evals.information_fetch.live_e2e.readiness",
            fromlist=["derive_live_contract"]).derive_live_contract
        unresolved = deepcopy(self.envelope["packet"])
        with self.assertRaisesRegex(ReadinessError, "READINESS_NOT_VALIDATED"):
            derive(unresolved)
        with self.assertRaisesRegex(ReadinessError,
                                    "READINESS_SELF_REFERENCE_DISABLED"):
            derive({**unresolved, "schema_version": VERSION_V2,
                    "effective_config": unresolved["effective_config"]})
        stripped = deepcopy(unresolved)
        stripped["schema_version"] = VERSION_V2
        stripped.pop("effective_config")
        with self.assertRaisesRegex(ReadinessError,
                                    "READINESS_SELF_REFERENCE_DISABLED"):
            derive(stripped)
        ready = self.ready_packet()
        with self.assertRaisesRegex(ReadinessError, "READINESS_NOT_VALIDATED"):
            derive(ready)
        validate_envelope(seal_packet(ready), root=ROOT)
        self.assertEqual(derive(ready)["run_kind"], "narrow")
        with self.assertRaisesRegex(ReadinessError, "READINESS_NOT_VALIDATED"):
            derive(ready)

    def test_mutated_ready_packet_cannot_reuse_validation_receipt(self):
        derive = __import__(
            "tuning.evals.information_fetch.live_e2e.readiness",
            fromlist=["derive_live_contract"]).derive_live_contract
        ready = self.ready_packet()
        validate_envelope(seal_packet(ready), root=ROOT)
        changed = deepcopy(ready)
        changed["identity_rules"]["experiment_id"] = "different"
        with self.assertRaisesRegex(ReadinessError, "READINESS_NOT_VALIDATED"):
            derive(changed)
        with self.assertRaisesRegex(ReadinessError, "READINESS_NOT_VALIDATED"):
            derive(ready)
        validate_envelope(seal_packet(ready), root=ROOT)
        self.assertEqual(derive(ready)["run_kind"], "narrow")

    def test_semantic_error_precedes_binding_error_for_ready_packet(self):
        changed = self.ready_packet()
        changed["case"]["primary_pdf_url"] = "not-a-url"
        changed["effective_config"]["inputs"]["case_packet"]["path"] = "./" + CASE_PACKET_PATH
        with self.assertRaisesRegex(ReadinessError, "READINESS_URL_INVALID"):
            validate_envelope(seal_packet(changed), root=ROOT)

    def test_bounded_lists_fixed_fail_for_unresolved_and_ready(self):
        bases = (("unresolved", deepcopy(self.envelope["packet"])),
                 ("ready", self.ready_packet()))
        for state, base in bases:
            cases = []
            for field, code in (("prohibitions", "READINESS_PROHIBITIONS_INVALID"),
                                ("limitations", "READINESS_LIMITATIONS_INVALID"),
                                ("stop_rules", "READINESS_STOP_RULES_INVALID")):
                for label, value in (
                    ("object", [{"self_reference": "readiness-template.json"}]),
                    ("self_reference_string", ["self_reference=readiness-template.json"]),
                    ("private_path", ["../niulai-private/secret.json"]),
                    ("credential_shape", ["github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ"]),
                    ("nonstring", [1]),
                    ("unhashable", [["nested"]]),
                    ("oversized", ["x" * 2049]),
                ):
                    changed = deepcopy(base)
                    changed[field] = value
                    cases.append((field, label, code, changed))
            stops = list(base["stop_rules"])
            for label, value in (
                ("extra", stops + ["unexpected_stop"]),
                ("duplicate", stops[:-1] + [stops[0], stops[0]]),
                ("missing", stops[:-1]),
            ):
                changed = deepcopy(base)
                changed["stop_rules"] = value
                cases.append(("stop_rules", label, "READINESS_STOP_RULES_INVALID", changed))
            for field, label, code, changed in cases:
                with self.subTest(state=state, field=field, mutation=label):
                    with self.assertRaisesRegex(ReadinessError, code):
                        validate_envelope(seal_packet(changed), root=ROOT)

    def test_file_loader_rejects_symlink(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            link = Path(directory) / "packet.json"
            link.symlink_to(HERE / "readiness-template.json")
            with self.assertRaisesRegex(ReadinessError, "READINESS_PATH_INVALID"):
                load_and_validate(link, root=ROOT)


if __name__ == "__main__":
    unittest.main()
