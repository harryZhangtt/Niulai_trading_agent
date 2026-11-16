from datetime import datetime, timezone
import unittest

from shared.job_runtime.provider_contract import (
    ContractError, FailureKind, Phase, ProviderResultV1, ReconciliationProofV1,
    ReplayContractV1, ResultStatus, Submission, TerminalProof, from_legacy_result,
    validate_replay,
)


BASE = dict(provider="codex_cli", operation_id="slot/operation-1", phase="connecting",
            submission="not_submitted", terminal_proof="absent", status="retryable",
            code="MODEL_TRANSIENT_FAILURE", failure_kind="connection")


class ProviderContractTests(unittest.TestCase):
    def make(self, **changes):
        return ProviderResultV1(**(BASE | changes))

    def proof(self, result, *, attempt_id="attempt/1", scope="slot/op", evidence="a" * 64):
        return ReconciliationProofV1(attempt_id, result.operation_id, scope,
                                     result.canonical_sha256, "absent", evidence,
                                     datetime(2026, 11, 6, tzinfo=timezone.utc))

    def validate_bound(self, contract, result, proof):
        return validate_replay(
            contract, result, reconciliation_proof=proof,
            expected_attempt_id=proof.attempt_id,
            expected_provider_result_sha256=proof.provider_result_sha256,
            expected_evidence_sha256=proof.evidence_sha256,
            expected_proof_sha256=proof.canonical_sha256)

    def test_success_truth_table_requires_terminal_verified(self):
        for phase in Phase:
            for proof in TerminalProof:
                values = BASE | dict(phase=phase, submission="definitely_submitted", terminal_proof=proof,
                                     status="succeeded", code="PROVIDER_SUCCEEDED", failure_kind="none")
                if phase is Phase.TERMINAL and proof is TerminalProof.VERIFIED:
                    self.assertEqual(ProviderResultV1(**values).status, ResultStatus.SUCCEEDED)
                else:
                    with self.assertRaises(ContractError):
                        ProviderResultV1(**values)

    def test_retryable_requires_safe_pre_submission_phase(self):
        for phase in Phase:
            for submission in Submission:
                values = BASE | {"phase": phase, "submission": submission}
                safe = phase in (Phase.NOT_STARTED, Phase.CONNECTING) and submission is Submission.NOT_SUBMITTED
                if safe:
                    self.assertTrue(ProviderResultV1(**values).safe_retry_candidate)
                else:
                    with self.assertRaises(ContractError):
                        ProviderResultV1(**values)

    def test_post_submit_transport_ambiguity_must_be_unknown(self):
        for failure in ("timeout", "connection_reset", "partial_response", "missing_terminal"):
            for phase in ("submitted", "streaming"):
                value = self.make(phase=phase, submission="possibly_submitted", status="unknown",
                                  failure_kind=failure, code="PROVIDER_OUTCOME_UNKNOWN")
                self.assertEqual(value.status, ResultStatus.UNKNOWN)
                with self.assertRaisesRegex(ContractError, "PROVIDER_OUTCOME_MUST_BE_UNKNOWN"):
                    self.make(phase=phase, submission="possibly_submitted", status="failed",
                              failure_kind=failure)

    def test_permanent_failure_kinds_are_failed(self):
        for failure in ("auth", "config", "model", "policy", "local_config"):
            with self.assertRaisesRegex(ContractError, "PROVIDER_(RETRY_CONTRADICTED|PERMANENT_FAILURE_STATUS)"):
                self.make(failure_kind=failure)
            result = self.make(phase="terminal", submission="not_submitted", terminal_proof="verified",
                               status="failed", failure_kind=failure, code="PERMANENT_FAILURE")
            self.assertEqual(result.status, ResultStatus.FAILED)

    def test_provider_false_wins_and_true_does_not_override_unsafe(self):
        with self.assertRaisesRegex(ContractError, "PROVIDER_RETRY_CONTRADICTED"):
            self.make(provider_should_retry=False)
        with self.assertRaisesRegex(ContractError, "PROVIDER_RETRY_UNSAFE"):
            self.make(phase="streaming", submission="possibly_submitted", provider_should_retry=True)

    def test_typed_http_retry_candidates(self):
        retryable = {408, 409, 429, 529, *range(500, 600)}
        for status in (200, 400, 408, 409, 429, 500, 528, 529, 599):
            value = self.make(failure_kind="http", http_status=status)
            self.assertEqual(value.typed_http_retry_candidate, status in retryable)
        with self.assertRaisesRegex(ContractError, "PROVIDER_HTTP_KIND_REQUIRED"):
            self.make(http_status=429)

    def test_quota_exhausted_is_typed_terminal_and_not_http_rate_limit(self):
        quota = self.make(
            status="failed", code="MODEL_QUOTA_EXHAUSTED",
            failure_kind="quota_exhausted", provider_should_retry=False)
        self.assertEqual(quota.failure_kind, FailureKind.QUOTA_EXHAUSTED)
        self.assertEqual((quota.status, quota.http_status, quota.retry_after_at),
                         (ResultStatus.FAILED, None, None))
        self.assertFalse(quota.safe_retry_candidate)
        with self.assertRaisesRegex(ContractError, "PROVIDER_(RETRY_CONTRADICTED|PERMANENT_FAILURE_STATUS)"):
            self.make(failure_kind="quota_exhausted")

        wait = datetime(2026, 11, 6, 0, 0, 4, tzinfo=timezone.utc)
        rate_limit = self.make(
            code="CODEX_HTTP_RETRY_CANDIDATE", failure_kind="http",
            http_status=429, provider_should_retry=True, retry_after_at=wait,
            retry_after_source="retry-after-seconds")
        self.assertEqual(rate_limit.failure_kind, FailureKind.HTTP)
        self.assertEqual((rate_limit.status, rate_limit.http_status, rate_limit.retry_after_at),
                         (ResultStatus.RETRYABLE, 429, wait))
        self.assertTrue(rate_limit.safe_retry_candidate)

    def test_receipt_is_deeply_detached_immutable_and_bounded(self):
        original = {"request_id": "abc", "usage": {"input_units": 3}, "flags": [True]}
        value = self.make(receipt=original)
        original["usage"]["input_units"] = 999
        original["flags"].append(False)
        self.assertEqual(value.receipt["usage"]["input_units"], 3)
        self.assertEqual(value.receipt["flags"], (True,))
        with self.assertRaises(TypeError):
            value.receipt["new"] = 1
        with self.assertRaisesRegex(ContractError, "PROVIDER_RECEIPT_BOUNDS"):
            self.make(receipt={"nested": {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}})
        with self.assertRaisesRegex(ContractError, "PROVIDER_RECEIPT_BOUNDS"):
            self.make(receipt={"id": "x" * 2049})

    def test_receipt_cycles_are_stable_errors_and_shared_dags_are_detached(self):
        cyclic = []
        cyclic.append(cyclic)
        with self.assertRaisesRegex(ContractError, "PROVIDER_RECEIPT_CYCLE"):
            self.make(receipt={"items": cyclic})
        shared = {"request_id": "abc"}
        value = self.make(receipt={"left": shared, "right": shared})
        shared["request_id"] = "mutated"
        self.assertEqual(value.receipt["left"]["request_id"], "abc")
        self.assertEqual(value.receipt["right"]["request_id"], "abc")

    def test_versions_reject_scalar_confusion(self):
        for version in (True, 1.0, "1"):
            with self.subTest(kind="result", version=version), self.assertRaisesRegex(
                    ContractError, "PROVIDER_RESULT_VERSION_INVALID"):
                self.make(version=version)
            with self.subTest(kind="replay", version=version), self.assertRaisesRegex(
                    ContractError, "REPLAY_VERSION_INVALID"):
                ReplayContractV1("none", (Phase.CONNECTING,), "slot/op", version=version)
            with self.subTest(kind="proof", version=version), self.assertRaisesRegex(
                    ContractError, "RECONCILIATION_PROOF_VERSION_INVALID"):
                ReconciliationProofV1("attempt/1", "slot/operation-1", "slot/op", "a" * 64,
                                      "absent", "b" * 64,
                                      datetime(2026, 11, 6, tzinfo=timezone.utc), version=version)
        with self.assertRaisesRegex(ContractError, "RECONCILIATION_PROOF_RECORDED_AT_INVALID"):
            ReconciliationProofV1("attempt/1", "slot/operation-1", "slot/op", "a" * 64,
                                  "absent", "b" * 64, datetime(2026, 11, 6))

    def test_receipt_rejects_secrets_and_arbitrary_provider_text(self):
        for key in ("access_token", "password", "authorization", "raw_error", "stderr", "message"):
            with self.subTest(key=key), self.assertRaises(ContractError):
                self.make(receipt={key: "SYNTHETIC-SENSITIVE-TEXT"})

    def test_retry_timestamp_is_aware_and_typed(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(self.make(retry_after_at=now, retry_after_source="typed-timestamp").retry_after_at, now)
        for changes in ({"retry_after_at": now},
                        {"retry_after_at": datetime(2026, 1, 1), "retry_after_source": "typed-timestamp"},
                        {"retry_after_at": now, "retry_after_source": "guess"}):
            with self.assertRaises(ContractError):
                self.make(**changes)

    def test_replay_effect_phase_scope_and_reconciliation(self):
        safe = self.make()
        for effect in ("none", "idempotent"):
            contract = ReplayContractV1(effect, (Phase.NOT_STARTED, Phase.CONNECTING), "slot/op")
            self.assertTrue(validate_replay(contract, safe))
        contract = ReplayContractV1("reconcile_before_replay", (Phase.CONNECTING,),
                                    "slot/op", "ledger-v1")
        unknown = self.make(phase="streaming", submission="possibly_submitted", status="unknown",
                            failure_kind="timeout", code="PROVIDER_OUTCOME_UNKNOWN")
        proof = self.proof(unknown)
        self.assertTrue(self.validate_bound(contract, unknown, proof))
        self.assertFalse(validate_replay(contract, unknown, reconciliation_proof=proof))
        self.assertFalse(validate_replay(contract, unknown, reconciliation_proof=True))
        self.assertFalse(self.validate_bound(contract, safe, proof))
        operation_mismatch = ReconciliationProofV1(
            "attempt/1", "different/op", "slot/op", unknown.canonical_sha256,
            "absent", "a" * 64, datetime(2026, 11, 6, tzinfo=timezone.utc))
        scope_mismatch = self.proof(unknown, scope="different/scope")
        for mismatch in (operation_mismatch, scope_mismatch):
            self.assertFalse(self.validate_bound(contract, unknown, mismatch))
        with self.assertRaisesRegex(ContractError, "REPLAY_ADAPTER_REQUIRED"):
            ReplayContractV1("reconcile_before_replay", (Phase.CONNECTING,), "slot/op")
        with self.assertRaisesRegex(ContractError, "REPLAY_PHASES_INVALID"):
            ReplayContractV1("none", (Phase.SUBMITTED,), "slot/op")

    def test_reconciliation_handles_missing_terminal_but_never_auto_replays_it(self):
        unknown = self.make(phase="terminal", submission="definitely_submitted", status="unknown",
                            failure_kind="missing_terminal", code="PROVIDER_OUTCOME_UNKNOWN")
        proof = self.proof(unknown, evidence="b" * 64)
        reconcile = ReplayContractV1("reconcile_before_replay", (Phase.CONNECTING,),
                                     "slot/op", "ledger-v1")
        automatic = ReplayContractV1("idempotent", (Phase.CONNECTING,), "slot/op")
        self.assertTrue(self.validate_bound(reconcile, unknown, proof))
        self.assertFalse(self.validate_bound(automatic, unknown, proof))

    def test_reconciliation_persisted_bindings_deny_forgery_and_replacement(self):
        contract = ReplayContractV1("reconcile_before_replay", (Phase.CONNECTING,),
                                    "slot/op", "ledger-v1")
        unknown = self.make(phase="streaming", submission="possibly_submitted", status="unknown",
                            failure_kind="timeout", code="PROVIDER_OUTCOME_UNKNOWN",
                            receipt={"request_id": "original"})
        proof = self.proof(unknown)
        persisted = dict(expected_attempt_id=proof.attempt_id,
                         expected_provider_result_sha256=proof.provider_result_sha256,
                         expected_evidence_sha256=proof.evidence_sha256,
                         expected_proof_sha256=proof.canonical_sha256)
        for key, replacement in (("expected_attempt_id", "attempt/forged"),
                                 ("expected_provider_result_sha256", "b" * 64),
                                 ("expected_evidence_sha256", "b" * 64),
                                 ("expected_proof_sha256", "b" * 64)):
            changed = persisted | {key: replacement}
            self.assertFalse(validate_replay(contract, unknown, reconciliation_proof=proof, **changed))
        forged = self.proof(unknown, evidence="b" * 64)
        self.assertFalse(validate_replay(contract, unknown, reconciliation_proof=forged, **persisted))
        replaced = self.make(phase="streaming", submission="possibly_submitted", status="unknown",
                             failure_kind="timeout", code="PROVIDER_OUTCOME_UNKNOWN",
                             receipt={"request_id": "replacement"})
        self.assertNotEqual(replaced.canonical_sha256, unknown.canonical_sha256)
        self.assertFalse(validate_replay(contract, replaced, reconciliation_proof=proof, **persisted))
        with self.assertRaises(TypeError):
            unknown.to_mapping()["code"] = "REPLACED"

    def test_legacy_retryables_are_conservative_and_detached(self):
        legacy = {"status": "retryable", "code": "MODEL_TRANSIENT_FAILURE",
                  "receipt": {"request_id": "abc"}}
        result = from_legacy_result(legacy, provider="claude_host", operation_id="legacy/1")
        legacy["receipt"]["request_id"] = "mutated"
        self.assertEqual(result.status, ResultStatus.UNKNOWN)
        self.assertEqual(result.submission, Submission.POSSIBLY_SUBMITTED)
        self.assertEqual(result.receipt["request_id"], "abc")
        self.assertFalse(result.safe_retry_candidate)


if __name__ == "__main__":
    unittest.main()
