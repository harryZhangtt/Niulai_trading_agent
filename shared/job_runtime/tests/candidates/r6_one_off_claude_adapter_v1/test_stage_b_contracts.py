from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from shared.job_runtime.candidates.r6_one_off_claude_adapter_v1.contracts import (
    ContractError,
    FROZEN_REFS,
    canonical_bytes,
    sha256_bytes,
    validate_stage_b_seal,
)
from shared.job_runtime.tests.candidates.r6_one_off_claude_adapter_v1._support import (
    FIXTURES,
    ROOT,
    build_seal,
    write_artifact,
    write_json_artifact,
)


class StrictStageBContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=FIXTURES)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.seal, self.now, self.registry, self.ledger = build_seal(self.base)

    def assert_code(self, value, code, historical_ids=()):
        with self.assertRaisesRegex(ContractError, code):
            validate_stage_b_seal(value, ROOT, self.now, historical_ids, self.registry, self.ledger)

    def test_complete_exact_external_seal_passes_validation_only(self):
        validated = validate_stage_b_seal(self.seal, ROOT, self.now, (), self.registry, self.ledger)
        self.assertIs(validated, self.seal)
        self.assertFalse(validated["countable_observation"])
        self.assertFalse(validated["self_minted"])
        self.assertEqual(validated["limits"]["max_attempts"], 1)
        self.assertEqual(validated["limits"]["concurrency"], 1)
        self.assertEqual(validated["limits"]["request_retries"], 0)

    def test_synthetic_authority_cannot_replace_frozen_authorization(self):
        bad = copy.deepcopy(self.seal)
        bad["frozen_bindings"]["authorization"] = write_artifact(
            self.base, "synthetic-authorization.json", b'{"looks":"self-consistent"}\n'
        )
        self.assert_code(bad, "FROZEN_AUTHORIZATION_IDENTITY")

    def test_synthetic_final_grant_and_review_are_rejected(self):
        bad = copy.deepcopy(self.seal)
        bad["claude_final_grant"] = write_json_artifact(
            self.base, "authority/substitute-grant.json", {"decision": "ALLOW"}
        )
        self.assert_code(bad, "FINAL_GRANT_KEYS_INVALID")
        bad = copy.deepcopy(self.seal)
        bad["claude_final_grant_review"] = write_json_artifact(
            self.base, "authority/substitute-review.json", {"decision": "CLEAN"}
        )
        self.assert_code(bad, "FINAL_GRANT_REVIEW_KEYS_INVALID")

    def test_external_registry_is_required_immutable_and_outside_seal(self):
        with self.assertRaisesRegex(ContractError, "TRUSTED_EXTERNAL_GRANT_REGISTRY_REQUIRED"):
            validate_stage_b_seal(self.seal, ROOT, self.now)
        with self.assertRaisesRegex(ContractError, "HISTORICAL_IDENTITY_LEDGER_REQUIRED"):
            validate_stage_b_seal(self.seal, ROOT, self.now, (), self.registry)
        with self.assertRaises(TypeError):
            self.registry.entries["claude_cli"] = self.registry.entries["other_cli"]
        self.assertNotIn("trusted_external_grants", self.seal)

    def test_coherent_caller_created_grant_and_review_alternative_is_rejected(self):
        import json
        bad = copy.deepcopy(self.seal)
        grant_ref = bad["claude_final_grant"]
        grant_doc = json.loads((ROOT / grant_ref["path"]).read_text())
        grant_doc["remaining_combined_budget_usd"] = 0.019
        alternate_grant = write_json_artifact(
            self.base, "caller-created/claude-final-grant.json", grant_doc
        )
        review_ref = bad["claude_final_grant_review"]
        review_doc = json.loads((ROOT / review_ref["path"]).read_text())
        review_doc["grant_sha256"] = alternate_grant["sha256"]
        alternate_review = write_json_artifact(
            self.base, "caller-created/claude-review.json", review_doc
        )
        bad["claude_final_grant"] = alternate_grant
        bad["claude_final_grant_review"] = alternate_review
        bad["held_bindings"]["observer"]["grant_seal_sha256"] = alternate_grant["sha256"]
        self.assert_code(bad, "CLAUDE_FINAL_GRANT_REGISTRY_IDENTITY")

    def test_complete_held_binding_digest_rejects_coherent_substitution(self):
        import json
        from shared.job_runtime.candidates.r6_one_off_claude_adapter_v1.contracts import held_binding_digest

        bad = copy.deepcopy(self.seal)
        bad["held_bindings"]["observer"]["source_fingerprint_sha256"] = "4" * 64
        self.assert_code(bad, "FINAL_GRANT_HELD_BINDING_DIGEST_DRIFT")

        coherent = copy.deepcopy(bad)
        digest = held_binding_digest(coherent["held_bindings"], coherent["publication"], coherent["cleanup"])
        for provider, grant_key, review_key, stem in (
            ("claude_cli", "claude_final_grant", "claude_final_grant_review", "claude"),
            ("other_cli", "other_provider_final_grant", "other_provider_final_grant_review", "other"),
        ):
            grant_doc = json.loads((ROOT / coherent[grant_key]["path"]).read_text())
            grant_doc["held_binding_digest_sha256"] = digest
            grant_ref = write_json_artifact(
                self.base, "caller-created/" + stem + "-digest-grant.json", grant_doc
            )
            review_doc = json.loads((ROOT / coherent[review_key]["path"]).read_text())
            review_doc["grant_sha256"] = grant_ref["sha256"]
            review_ref = write_json_artifact(
                self.base, "caller-created/" + stem + "-digest-review.json", review_doc
            )
            coherent[grant_key] = grant_ref
            coherent[review_key] = review_ref
        coherent["held_bindings"]["observer"]["grant_seal_sha256"] = coherent["claude_final_grant"]["sha256"]
        self.assert_code(coherent, "FINAL_GRANT_HELD_BINDING_REGISTRY_DRIFT")

    def test_held_artifact_semantics_are_parsed(self):
        cases = (
            ("catalog", "parser", {"version":1,"kind":"R6_HELD_CATALOG_PARSER","line_mode":"first","model":"claude-opus-5-5"}, "CATALOG_PARSER_SEMANTICS_INVALID"),
            ("request", "artifact", {"version":1,"kind":"R6_HELD_REQUEST"}, "REQUEST_ARTIFACT_SEMANTICS_INVALID"),
            ("process", "terminal", {"version":1,"kind":"R6_HELD_TERMINAL"}, "PROCESS_TERMINAL_SEMANTICS_INVALID"),
            ("process", "cleanup_receipt", {"version":1,"kind":"R6_PROCESS_CLEANUP"}, "PROCESS_CLEANUP_SEMANTICS_INVALID"),
        )
        for section, field, document, code in cases:
            bad = copy.deepcopy(self.seal)
            bad["held_bindings"][section][field] = write_json_artifact(self.base, "semantic/" + section + "-" + field + ".json", document)
            with self.subTest(section=section, field=field): self.assert_code(bad, code)
        for section, code in (("publication", "PUBLICATION_RECEIPT_SEMANTICS_INVALID"), ("cleanup", "CLEANUP_RECEIPT_SEMANTICS_INVALID")):
            bad = copy.deepcopy(self.seal)
            bad[section]["receipt"] = write_json_artifact(self.base, "semantic/" + section + ".json", {"version":1,"kind":"WRONG"})
            with self.subTest(section=section): self.assert_code(bad, code)

    def test_pinned_historical_identity_ledger_rejects_stale_current_identity(self):
        from shared.job_runtime.candidates.r6_one_off_claude_adapter_v1.contracts import (
            HistoricalIdentityLedger, TrustedArtifactRef,
        )
        identities = set(self.ledger.identities)
        identities.add(self.seal["request_id"])
        ref = write_json_artifact(self.base, "external-ledger/stale-identities.json", {
            "version": 1, "kind": "R6_HISTORICAL_IDENTITY_LEDGER",
            "identities": sorted(identities),
        })
        stale = HistoricalIdentityLedger(TrustedArtifactRef.from_mapping(ref), identities)
        with self.assertRaisesRegex(ContractError, "ENGINE_IDS_NOT_FRESH"):
            validate_stage_b_seal(self.seal, ROOT, self.now, (), self.registry, stale)

    def test_no_self_mint_and_independent_clean_review_are_mandatory(self):
        for field, value in (("self_minted", True), ("independent_review_clean", False)):
            bad = copy.deepcopy(self.seal)
            bad[field] = value
            with self.subTest(field=field):
                self.assert_code(bad, "STAGE_B_NO_SELF_MINT")

    def test_binary_descriptor_and_official_asset_are_bound(self):
        bad = copy.deepcopy(self.seal)
        bad["held_bindings"]["binary"]["inode"] += 1
        self.assert_code(bad, "BINARY_DESCRIPTOR_MISMATCH")
        bad = copy.deepcopy(self.seal)
        bad["held_bindings"]["binary"]["official_asset"]["sha256"] = "0" * 64
        self.assert_code(bad, "BINARY_OFFICIAL_ASSET_DRIFT")

    def test_command_no_shell_model_effort_once_and_environment_bound(self):
        cases = (
            ("shell", True, "COMMAND_SHELL_OR_BINARY_INVALID"),
            ("model_occurrences", 2, "COMMAND_MODEL_COUNT_INVALID"),
            ("effort_occurrences", 2, "COMMAND_EFFORT_COUNT_INVALID"),
            ("environment_allowlist_sha256", "0" * 64, "COMMAND_ENVIRONMENT_DRIFT"),
        )
        for field, value, code in cases:
            bad = copy.deepcopy(self.seal)
            bad["held_bindings"]["command"][field] = value
            with self.subTest(field=field):
                self.assert_code(bad, code)
        for flag, code in (("--model", "COMMAND_MODEL_COUNT_INVALID"), ("--effort", "COMMAND_EFFORT_COUNT_INVALID")):
            bad = copy.deepcopy(self.seal)
            argv = bad["held_bindings"]["command"]["argv"]
            argv[argv.index(flag)] = "--not-selection"
            bad["held_bindings"]["command"]["artifact"] = write_artifact(
                self.base, "held/argv-" + flag[2:] + ".json", canonical_bytes(argv)
            )
            with self.subTest(flag=flag):
                self.assert_code(bad, code)

    def test_catalog_exact_membership_entitlement_and_single_check(self):
        duplicate = copy.deepcopy(self.seal)
        duplicate["held_bindings"]["catalog"]["artifact"] = write_artifact(
            self.base, "held/catalog-duplicate.txt", b"claude-opus-5-5\nclaude-opus-5-5\n"
        )
        self.assert_code(duplicate, "CATALOG_RAW_MODEL_COUNT_INVALID")
        for field, value in (
            ("model_occurrence_count", 2),
            ("membership_verified", False),
            ("entitlement_verified", False),
            ("check_count", 2),
        ):
            bad = copy.deepcopy(self.seal)
            bad["held_bindings"]["catalog"][field] = value
            with self.subTest(field=field):
                self.assert_code(bad, "CATALOG_")

    def test_prompt_engine_process_cross_bindings_are_exact(self):
        cases = (
            ("prompt", "operation_id", "operation/substitute", "PROMPT_ENGINE_ID_DRIFT"),
            ("prompt", "provider_process_id", 9, "PROMPT_PROCESS_DRIFT"),
            ("engine", "job_count", 2, "ENGINE_NOT_ONE_TO_ONE"),
            ("engine", "native_prompt_equal", False, "ENGINE_EQUALITY_INVALID"),
            ("engine", "prompt_sha256", "0" * 64, "ENGINE_PROMPT_DRIFT"),
            ("process", "binary_descriptor_identity_sha256", "0" * 64, "PROCESS_BINARY_DRIFT"),
            ("process", "new_process_group", False, "PROCESS_MODE_INVALID"),
        )
        for section, field, value, code in cases:
            bad = copy.deepcopy(self.seal)
            bad["held_bindings"][section][field] = value
            with self.subTest(section=section, field=field):
                self.assert_code(bad, code)

    def test_observer_admission_upstream_grant_and_request_are_bound(self):
        cases = (
            ("admission_count", 2, "OBSERVER_COUNT_INVALID"),
            ("observed_upstream_count", 2, "OBSERVER_COUNT_INVALID"),
            ("grant_seal_sha256", "0" * 64, "OBSERVER_GRANT_DRIFT"),
            ("attempt_id", "attempt/substitute", "OBSERVER_IDENTITY_DRIFT"),
            ("request_fingerprint_sha256", "0" * 64, "OBSERVER_REQUEST_FINGERPRINT_DRIFT"),
            ("model", "other-model", "OBSERVER_MODEL_DRIFT"),
            ("native_prompt_sha256", "0" * 64, "OBSERVER_PROMPT_DRIFT"),
            ("engine_ids", {"job_id":"job/substitute","slot_id":"slot/fresh-0001","attempt_id":"attempt/fresh-0001","operation_id":"operation/fresh-0001"}, "OBSERVER_ENGINE_IDS_DRIFT"),
        )
        for field, value, code in cases:
            bad = copy.deepcopy(self.seal)
            bad["held_bindings"]["observer"][field] = value
            with self.subTest(field=field):
                self.assert_code(bad, code)
        bad = copy.deepcopy(self.seal)
        bad["held_bindings"]["request"]["operation_binding_sha256"] = "0" * 64
        self.assert_code(bad, "REQUEST_OPERATION_BINDING_INVALID")

    def test_owner_private_0700_nofollow_custody_is_mandatory(self):
        for field, value, code in (
            ("mode", 0o755, "CUSTODY_MODE_INVALID"),
            ("nofollow_path_walk", False, "CUSTODY_POLICY_INVALID"),
            ("owner_private", False, "CUSTODY_POLICY_INVALID"),
            ("workspace_local", False, "CUSTODY_POLICY_INVALID"),
        ):
            bad = copy.deepcopy(self.seal)
            bad["held_bindings"]["custody"][field] = value
            with self.subTest(field=field):
                self.assert_code(bad, code)

    def test_atomic_publication_cleanup_and_unknown_fence_are_mandatory(self):
        bad = copy.deepcopy(self.seal)
        bad["publication"]["atomic"] = False
        self.assert_code(bad, "PUBLICATION_INCOMPLETE")
        bad = copy.deepcopy(self.seal)
        bad["publication"]["partial_final_absent"] = False
        self.assert_code(bad, "PUBLICATION_INCOMPLETE")
        bad = copy.deepcopy(self.seal)
        bad["cleanup"]["process_group_reaped"] = False
        self.assert_code(bad, "CLEANUP_INCOMPLETE")
        bad = copy.deepcopy(self.seal)
        bad["cleanup"]["residual_children"] = 1
        self.assert_code(bad, "CLEANUP_RESIDUAL_EFFECT")
        bad = copy.deepcopy(self.seal)
        bad["unknown_fence"]["retry"] = True
        self.assert_code(bad, "UNKNOWN_FENCE_INVALID")

    def test_caps_window_limits_profile_countability_and_fresh_ids_fail_closed(self):
        cases = (
            ("claude_subcap_usd", 0.02, "CAP_INVALID"),
            ("remaining_combined_budget_usd", 0.009, "REMAINING_BUDGET_INVALID"),
            ("observed_profile_fingerprint_sha256", "b" * 64, "PROFILE_MISMATCH"),
            ("countable_observation", True, "COUNTABLE_OBSERVATION_INVALID"),
            ("identities_fresh", False, "ENGINE_IDS_NOT_FRESH"),
        )
        for field, value, code in cases:
            bad = copy.deepcopy(self.seal)
            bad[field] = value
            with self.subTest(field=field):
                self.assert_code(bad, code)
        bad = copy.deepcopy(self.seal)
        bad["limits"]["max_attempts"] = 2
        self.assert_code(bad, "LIMITS_INVALID")
        bad = copy.deepcopy(self.seal)
        bad["deadline"] = "2099-01-01T00:00:00Z"
        self.assert_code(bad, "WINDOW_NOT_EXACT_30_MINUTES")
        self.assert_code(self.seal, "ENGINE_IDS_NOT_FRESH", [self.seal["request_id"]])

    def test_nofollow_rejects_held_artifact_symlink(self):
        bad = copy.deepcopy(self.seal)
        target = self.base / "held" / "stdout.raw"
        link = self.base / "held" / "stdout-link.raw"
        link.symlink_to(target)
        bad["held_bindings"]["process"]["stdout"] = {
            "path": link.relative_to(ROOT).as_posix(),
            "bytes": target.stat().st_size,
            "sha256": sha256_bytes(target.read_bytes()),
        }
        self.assert_code(bad, "PROCESS_STDOUT_SYMLINK")

    def test_stage_b_schema_accepts_valid_seal_and_rejects_nested_extra(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
        import json
        schema = json.loads((ROOT / "shared/job_runtime/candidates/r6_one_off_claude_adapter_v1/stage-b-seal-v1.schema.json").read_text())
        validator = Draft202012Validator(schema)
        validator.validate(self.seal)
        bad = copy.deepcopy(self.seal)
        bad["held_bindings"]["engine"]["extra"] = True
        self.assertTrue(list(validator.iter_errors(bad)))

    def test_top_level_and_nested_contracts_are_closed(self):
        bad = copy.deepcopy(self.seal)
        bad["extra"] = True
        self.assert_code(bad, "STAGE_B_KEYS_INVALID")
        bad = copy.deepcopy(self.seal)
        bad["held_bindings"]["engine"]["extra"] = True
        self.assert_code(bad, "ENGINE_BINDING_KEYS_INVALID")
        bad = copy.deepcopy(self.seal)
        bad["engine_ids"]["extra"] = "extra/fresh"
        self.assert_code(bad, "ENGINE_IDS_INVALID")


if __name__ == "__main__":
    unittest.main()
