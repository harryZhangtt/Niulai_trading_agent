"""Executable fail-closed contract coverage for the inert Claude adapter."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

from shared.job_runtime.candidates.r6_one_off_claude_adapter_v1.contracts import (
    ContractError,
    EFFORT,
    LIMITS,
    MODEL,
    UNKNOWN_FENCE,
    canonical_bytes,
    sha256_json,
    validate_stage_b_seal,
)
from shared.job_runtime.tests.candidates.r6_one_off_claude_adapter_v1._support import (
    FIXTURES,
    ROOT,
    build_seal,
    write_artifact,
    write_json_artifact,
)


class ExecutableContractInertnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=FIXTURES)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.seal, self.now, self.registry, self.ledger = build_seal(self.base)

    def assert_exact_reject(self, value, code, historical_ids=()):
        with self.assertRaisesRegex(ContractError, "^" + re.escape(code) + "$"):
            validate_stage_b_seal(value, ROOT, self.now, historical_ids, self.registry, self.ledger)

    @staticmethod
    def set_path(value, dotted, replacement):
        target = value
        parts = dotted.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = replacement

    def mutated(self, dotted, replacement):
        value = copy.deepcopy(self.seal)
        self.set_path(value, dotted, replacement)
        return value

    def rewritten_json(self, ref_path, field, replacement, name):
        value = copy.deepcopy(self.seal)
        target = value
        for part in ref_path.split("."):
            target = target[part]
        doc = json.loads((ROOT / target["path"]).read_text())
        doc[field] = replacement
        replacement_ref = write_json_artifact(self.base, "mutated/" + name + ".json", doc)
        holder = value
        parts = ref_path.split(".")
        for part in parts[:-1]:
            holder = holder[part]
        holder[parts[-1]] = replacement_ref
        return value

    def test_valid_complete_seal_is_accepted_before_mutation_matrix(self):
        self.assertIs(validate_stage_b_seal(self.seal, ROOT, self.now, (), self.registry, self.ledger), self.seal)

    def test_exact_authority_review_grant_and_design_binding_rejections(self):
        direct = (
            ("authority_owner", "candidate_owner", "STAGE_B_NO_SELF_MINT"),
            ("self_minted", True, "STAGE_B_NO_SELF_MINT"),
            ("independent_review_clean", False, "STAGE_B_NO_SELF_MINT"),
            ("frozen_bindings.authorization.sha256", "0" * 64, "FROZEN_AUTHORIZATION_IDENTITY"),
            ("frozen_bindings.authorization_review.sha256", "0" * 64, "FROZEN_AUTHORIZATION_REVIEW_IDENTITY"),
            ("frozen_bindings.design.sha256", "0" * 64, "FROZEN_DESIGN_IDENTITY"),
            ("frozen_bindings.design_review.sha256", "0" * 64, "FROZEN_DESIGN_REVIEW_IDENTITY"),
            ("frozen_bindings.canonical_engine.sha256", "0" * 64, "FROZEN_CANONICAL_ENGINE_IDENTITY"),
            ("stage_a_source_closure.path", "tuning/architecture/r6_one_off_codex_adapter_v1/source-closure-v1.json", "STAGE_A_SOURCE_CLOSURE_DRIFT"),
        )
        for dotted, replacement, code in direct:
            with self.subTest(gate=dotted):
                self.assert_exact_reject(self.mutated(dotted, replacement), code)

        documents = (
            ("claude_final_grant", "authorization_sha256", "0" * 64, "claude-authorization", "FINAL_GRANT_AUTHORIZATION_DRIFT"),
            ("claude_final_grant", "authorization_review_sha256", "0" * 64, "claude-authorization-review", "FINAL_GRANT_AUTHORIZATION_REVIEW_DRIFT"),
            ("claude_final_grant", "design_sha256", "0" * 64, "claude-design", "FINAL_GRANT_DESIGN_DRIFT"),
            ("claude_final_grant", "design_review_sha256", "0" * 64, "claude-design-review", "FINAL_GRANT_DESIGN_REVIEW_DRIFT"),
            ("claude_final_grant", "stage_a_source_closure_sha256", "0" * 64, "claude-closure", "FINAL_GRANT_CLOSURE_DRIFT"),
            ("claude_final_grant", "self_minted", True, "claude-self-mint", "FINAL_GRANT_SELF_MINTED"),
            ("other_provider_final_grant", "provider", "claude_cli", "other-provider", "OTHER_PROVIDER_INVALID"),
            ("claude_final_grant_review", "decision", "DIRTY", "claude-review", "FINAL_GRANT_REVIEW_NOT_CLEAN"),
            ("other_provider_final_grant_review", "self_review", True, "other-self-review", "FINAL_GRANT_REVIEW_SELF_MINTED"),
        )
        for ref_path, field, replacement, name, code in documents:
            with self.subTest(gate=name):
                self.assert_exact_reject(
                    self.rewritten_json(ref_path, field, replacement, name), code
                )

    def test_binary_command_config_and_catalog_mutation_matrix(self):
        cases = (
            ("held_bindings.binary.canonical_path", "relative/claude", "BINARY_CANONICAL_PATH_INVALID"),
            ("held_bindings.binary.descriptor_identity_sha256", "0" * 64, "BINARY_DESCRIPTOR_MISMATCH"),
            ("held_bindings.binary.device", 8, "BINARY_DESCRIPTOR_MISMATCH"),
            ("held_bindings.binary.inode", 102, "BINARY_DESCRIPTOR_MISMATCH"),
            ("held_bindings.binary.owner_uid", 502, "BINARY_DESCRIPTOR_MISMATCH"),
            ("held_bindings.binary.mode", 0o644, "BINARY_MODE_INVALID"),
            ("held_bindings.binary.artifact.sha256", "0" * 64, "BINARY_ARTIFACT_DRIFT"),
            ("held_bindings.binary.official_asset.sha256", "0" * 64, "BINARY_OFFICIAL_ASSET_DRIFT"),
            ("held_bindings.command.shell", True, "COMMAND_SHELL_OR_BINARY_INVALID"),
            ("held_bindings.command.argv", ["/opt/held/other", "--model", MODEL, "--effort", EFFORT], "COMMAND_SHELL_OR_BINARY_INVALID"),
            ("held_bindings.command.model_occurrences", 2, "COMMAND_MODEL_COUNT_INVALID"),
            ("held_bindings.command.effort_occurrences", 2, "COMMAND_EFFORT_COUNT_INVALID"),
            ("held_bindings.command.environment_allowlist_sha256", "0" * 64, "COMMAND_ENVIRONMENT_DRIFT"),
            ("held_bindings.config.environment_allowlist", ["HOME", "HOME"], "ENV_ALLOWLIST_DUPLICATE"),
            ("held_bindings.config.environment_allowlist_sha256", "0" * 64, "ENV_ALLOWLIST_HASH_INVALID"),
            ("held_bindings.catalog.model", "other-model", "CATALOG_MODEL_COUNT_INVALID"),
            ("held_bindings.catalog.model_occurrence_count", 2, "CATALOG_MODEL_COUNT_INVALID"),
            ("held_bindings.catalog.membership_verified", False, "CATALOG_MEMBERSHIP_INVALID"),
            ("held_bindings.catalog.entitlement_verified", False, "CATALOG_MEMBERSHIP_INVALID"),
            ("held_bindings.catalog.check_count", 2, "CATALOG_MEMBERSHIP_INVALID"),
        )
        for dotted, replacement, code in cases:
            with self.subTest(gate=dotted):
                bad = self.mutated(dotted, replacement)
                if dotted == "held_bindings.command.argv":
                    bad["held_bindings"]["command"]["artifact"] = write_artifact(
                        self.base, "mutated/argv-other.json", canonical_bytes(replacement)
                    )
                self.assert_exact_reject(bad, code)

        for flag, code in (("--model", "COMMAND_MODEL_COUNT_INVALID"), ("--effort", "COMMAND_EFFORT_COUNT_INVALID")):
            bad = copy.deepcopy(self.seal)
            argv = bad["held_bindings"]["command"]["argv"]
            argv[argv.index(flag)] = "--wrong-selection"
            bad["held_bindings"]["command"]["artifact"] = write_artifact(
                self.base, "mutated/argv-" + flag[2:] + ".json", canonical_bytes(argv)
            )
            with self.subTest(gate=flag + "-missing"):
                self.assert_exact_reject(bad, code)

        duplicate = copy.deepcopy(self.seal)
        duplicate["held_bindings"]["catalog"]["artifact"] = write_artifact(
            self.base, "mutated/catalog-duplicate.txt", (MODEL + "\n" + MODEL + "\n").encode("ascii")
        )
        self.assert_exact_reject(duplicate, "CATALOG_RAW_MODEL_COUNT_INVALID")

        secret_config = copy.deepcopy(self.seal)
        secret_config["held_bindings"]["config"]["artifact"] = write_artifact(
            self.base, "mutated/config-secret.json", b'{"api_key":"synthetic-not-a-secret"}\n'
        )
        self.assert_exact_reject(secret_config, "CONFIG_SECRET_FORBIDDEN")

    def test_prompt_engine_process_request_and_observer_cross_binding_matrix(self):
        cases = (
            ("held_bindings.prompt.payload_sha256", "0" * 64, "PROMPT_PAYLOAD_DRIFT"),
            ("held_bindings.prompt.source_cutoff_sha256", "0" * 64, "PROMPT_CUTOFF_DRIFT"),
            ("held_bindings.prompt.operation_id", "operation/substitute", "PROMPT_ENGINE_ID_DRIFT"),
            ("held_bindings.prompt.job_id", "job/substitute", "PROMPT_ENGINE_ID_DRIFT"),
            ("held_bindings.prompt.slot_id", "slot/substitute", "PROMPT_ENGINE_ID_DRIFT"),
            ("held_bindings.prompt.attempt_id", "attempt/substitute", "PROMPT_ENGINE_ID_DRIFT"),
            ("held_bindings.prompt.provider_process_id", 7, "PROMPT_PROCESS_DRIFT"),
            ("held_bindings.engine.readback", {"job_id":"job/substitute","slot_id":"slot/fresh-0001","attempt_id":"attempt/fresh-0001","operation_id":"operation/fresh-0001"}, "ENGINE_READBACK_ID_MISMATCH"),
            ("held_bindings.engine.job_count", 2, "ENGINE_NOT_ONE_TO_ONE"),
            ("held_bindings.engine.slot_count", 2, "ENGINE_NOT_ONE_TO_ONE"),
            ("held_bindings.engine.attempt_count", 2, "ENGINE_NOT_ONE_TO_ONE"),
            ("held_bindings.engine.operation_count", 2, "ENGINE_NOT_ONE_TO_ONE"),
            ("held_bindings.engine.operation_equal", False, "ENGINE_EQUALITY_INVALID"),
            ("held_bindings.engine.native_prompt_equal", False, "ENGINE_EQUALITY_INVALID"),
            ("held_bindings.engine.prompt_sha256", "0" * 64, "ENGINE_PROMPT_DRIFT"),
            ("held_bindings.process.process_id", 0, "PROCESS_ID_INVALID"),
            ("held_bindings.process.process_group_id", 0, "PROCESS_GROUP_INVALID"),
            ("held_bindings.process.new_process_group", False, "PROCESS_MODE_INVALID"),
            ("held_bindings.process.shell", True, "PROCESS_MODE_INVALID"),
            ("held_bindings.process.binary_descriptor_identity_sha256", "0" * 64, "PROCESS_BINARY_DRIFT"),
            ("held_bindings.process.stdout.sha256", "0" * 64, "PROCESS_STDOUT_DRIFT"),
            ("held_bindings.process.stderr.sha256", "0" * 64, "PROCESS_STDERR_DRIFT"),
            ("held_bindings.process.terminal.sha256", "0" * 64, "PROCESS_TERMINAL_DRIFT"),
            ("held_bindings.process.cleanup_receipt.sha256", "0" * 64, "PROCESS_CLEANUP_RECEIPT_DRIFT"),
            ("held_bindings.request.request_fingerprint_sha256", "0" * 64, "REQUEST_OPERATION_BINDING_INVALID"),
            ("held_bindings.request.operation_binding_sha256", "0" * 64, "REQUEST_OPERATION_BINDING_INVALID"),
            ("held_bindings.request.operation_id", "operation/substitute", "REQUEST_IDENTITY_DRIFT"),
            ("held_bindings.request.provider_process_id", 7, "REQUEST_IDENTITY_DRIFT"),
            ("held_bindings.observer.request_fingerprint_sha256", "0" * 64, "OBSERVER_REQUEST_FINGERPRINT_DRIFT"),
            ("held_bindings.observer.model", "other-model", "OBSERVER_MODEL_DRIFT"),
            ("held_bindings.observer.native_prompt_sha256", "0" * 64, "OBSERVER_PROMPT_DRIFT"),
            ("held_bindings.observer.engine_ids", {"job_id":"job/substitute","slot_id":"slot/fresh-0001","attempt_id":"attempt/fresh-0001","operation_id":"operation/fresh-0001"}, "OBSERVER_ENGINE_IDS_DRIFT"),
            ("held_bindings.observer.attempt_id", "attempt/substitute", "OBSERVER_IDENTITY_DRIFT"),
            ("held_bindings.observer.process_id", 7, "OBSERVER_IDENTITY_DRIFT"),
            ("held_bindings.observer.admission_count", 2, "OBSERVER_COUNT_INVALID"),
            ("held_bindings.observer.observed_upstream_count", 2, "OBSERVER_COUNT_INVALID"),
            ("held_bindings.observer.grant_seal_sha256", "0" * 64, "OBSERVER_GRANT_DRIFT"),
        )
        for dotted, replacement, code in cases:
            with self.subTest(gate=dotted):
                self.assert_exact_reject(self.mutated(dotted, replacement), code)

    def test_custody_publication_cleanup_unknown_and_limit_matrix(self):
        custody = (
            ("held_bindings.custody.root", ".job-runtime/wrong/", "CUSTODY_ROOT_INVALID"),
            ("held_bindings.custody.owner_uid", -1, "CUSTODY_OWNER_INVALID"),
            ("held_bindings.custody.mode", 0o755, "CUSTODY_MODE_INVALID"),
            ("held_bindings.custody.nofollow_path_walk", False, "CUSTODY_POLICY_INVALID"),
            ("held_bindings.custody.separate_root", False, "CUSTODY_POLICY_INVALID"),
            ("held_bindings.custody.owner_private", False, "CUSTODY_POLICY_INVALID"),
            ("held_bindings.custody.workspace_local", False, "CUSTODY_POLICY_INVALID"),
        )
        for dotted, replacement, code in custody:
            with self.subTest(gate=dotted):
                self.assert_exact_reject(self.mutated(dotted, replacement), code)

        for field in set(self.seal["publication"]) - {"receipt"}:
            with self.subTest(publication=field):
                self.assert_exact_reject(
                    self.mutated("publication." + field, False), "PUBLICATION_INCOMPLETE"
                )
        for field in (
            "process_group_terminated", "process_group_reaped", "observer_stopped",
            "endpoint_removed", "descriptors_closed", "only_enumerated_temps_removed",
            "unknown_evidence_preserved",
        ):
            with self.subTest(cleanup=field):
                self.assert_exact_reject(
                    self.mutated("cleanup." + field, False), "CLEANUP_INCOMPLETE"
                )
        for field, replacement in (("residual_children", 1), ("unlisted_effects", True)):
            with self.subTest(cleanup=field):
                self.assert_exact_reject(
                    self.mutated("cleanup." + field, replacement), "CLEANUP_RESIDUAL_EFFECT"
                )

        for field, original in UNKNOWN_FENCE.items():
            replacement = not original if isinstance(original, bool) else original + 1
            with self.subTest(unknown_fence=field):
                self.assert_exact_reject(
                    self.mutated("unknown_fence." + field, replacement), "UNKNOWN_FENCE_INVALID"
                )
        for field, original in LIMITS.items():
            replacement = not original if isinstance(original, bool) else original + 1
            with self.subTest(limit=field):
                self.assert_exact_reject(
                    self.mutated("limits." + field, replacement), "LIMITS_INVALID"
                )

    def test_budget_window_profile_countability_and_freshness_matrix(self):
        cases = (
            ("surface", "other_cli", "STAGE_B_TREATMENT_INVALID"),
            ("model", "other-model", "STAGE_B_TREATMENT_INVALID"),
            ("effort", "high", "STAGE_B_TREATMENT_INVALID"),
            ("observed_profile_fingerprint_sha256", "b" * 64, "PROFILE_MISMATCH"),
            ("model_entitled", False, "MODEL_ENTITLEMENT_INVALID"),
            ("membership_verified", False, "MODEL_ENTITLEMENT_INVALID"),
            ("claude_subcap_usd", 0.02, "CAP_INVALID"),
            ("remaining_combined_budget_usd", 0.009, "REMAINING_BUDGET_INVALID"),
            ("countable_observation", True, "COUNTABLE_OBSERVATION_INVALID"),
            ("identities_fresh", False, "ENGINE_IDS_NOT_FRESH"),
        )
        for dotted, replacement, code in cases:
            with self.subTest(gate=dotted):
                self.assert_exact_reject(self.mutated(dotted, replacement), code)
        self.assert_exact_reject(
            self.seal, "ENGINE_IDS_NOT_FRESH", [self.seal["request_id"]]
        )


if __name__ == "__main__":
    unittest.main()
