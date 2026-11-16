import copy
import dataclasses
from datetime import datetime, timedelta, timezone
import json
import threading
import unittest
from pathlib import Path

from _authority import HMACObservationAuthority, proof_for
from shared.job_runtime.candidates.claude_campaign_v1 import (
    Authority, CampaignContractError, CampaignStateV1, EvidenceV1, apply_evidence, create_initial_state,
    classify_authority, compute_evidence_sha256, evidence_from_mapping,
    restore_state, retry_ready,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "claude_campaign_v1"


def load(name):
    return evidence_from_mapping(json.loads((FIXTURES / name).read_text()))


def state_for(item, authority, max_attempts):
    state = create_initial_state(item.identity, item.evidence_sha256, authority, authority)
    if state.max_attempts != max_attempts:
        raise AssertionError("campaign max mismatch")
    return state


def successful_second_attempt(first):
    identity = dataclasses.replace(
        first.identity, attempt_id="r7-attempt-2", operation_id="r7-operation-2",
        request_id="r7-request-2", gateway_id="gateway-fixture-2",
        process_id="r7-process-2")
    fields = dict(gateway_disposition="pass_through", terminal_disposition="success",
                  upstream_forward_count=1, submission="definitely_submitted",
                  typed_transient=False, http_status=200, retry_after_seconds=None,
                  code="TERMINAL_SUCCESS")
    digest = compute_evidence_sha256(
        identity, fields["gateway_disposition"], fields["terminal_disposition"],
        fields["upstream_forward_count"], fields["submission"], fields["typed_transient"],
        fields["http_status"], fields["retry_after_seconds"], fields["code"])
    return EvidenceV1(identity=identity, evidence_sha256=digest, **fields)


class SyntheticHttp502Tests(unittest.TestCase):
    def test_pre_forward_502_consumes_proof_restarts_then_forwards_once(self):
        first = load("r7-evidence.json")
        self.assertEqual(classify_authority(first), Authority.UNKNOWN)
        authority = HMACObservationAuthority()
        observed_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
        proof = proof_for(authority, first, observed_at)
        waiting = apply_evidence(state_for(first, authority, 2), first, proof_mapping=proof)
        self.assertEqual(authority.verification_calls, 1)
        self.assertIs(authority.last_proof, proof)
        retry_at = observed_at + timedelta(seconds=30)
        self.assertEqual((waiting.status, waiting.retry_observed_at,
                          waiting.retry_after_seconds, waiting.next_retry_at),
                         ("retry_wait", observed_at, 30, retry_at))
        restarted = restore_state(json.loads(json.dumps(waiting.to_mapping())),
                                  verifier=authority, pinned_verifier=authority)
        second = successful_second_attempt(first)
        ready = retry_ready(restarted, retry_at, next_identity=second.identity,
                            next_evidence_sha256=second.evidence_sha256)
        terminal = apply_evidence(ready, second)
        self.assertEqual((terminal.status, terminal.attempts), ("succeeded", 2))
        self.assertEqual(first.upstream_forward_count + second.upstream_forward_count, 1)
        self.assertEqual(first.identity.run_id, second.identity.run_id)
        for field in ("attempt_id", "operation_id", "request_id", "gateway_id", "process_id"):
            self.assertNotEqual(getattr(first.identity, field), getattr(second.identity, field))

    def test_missing_plain_populated_copy_and_reused_proofs_fail_closed(self):
        first = load("r7-evidence.json")
        observed = datetime(2030, 1, 1, tzinfo=timezone.utc)
        authority = HMACObservationAuthority()
        proof = proof_for(authority, first, observed)
        missing = apply_evidence(state_for(first, authority, 2), first)
        self.assertEqual(missing.status, "unknown")
        plain = apply_evidence(state_for(first, authority, 2), first,
                               proof_mapping=dict(proof))
        self.assertEqual(plain.status, "unknown")
        copied = copy.copy(proof)
        copied_result = apply_evidence(state_for(first, authority, 2), first,
                                       proof_mapping=copied)
        self.assertEqual(copied_result.status, "unknown")
        forged = type(proof)(dict(proof))
        forged_result = apply_evidence(state_for(first, authority, 2), first,
                                       proof_mapping=forged)
        self.assertEqual(forged_result.status, "unknown")
        accepted = apply_evidence(state_for(first, authority, 2), first, proof_mapping=proof)
        self.assertEqual(accepted.status, "retry_wait")
        reused = apply_evidence(state_for(first, authority, 2), first, proof_mapping=proof)
        self.assertEqual(reused.status, "unknown")

    def test_wrong_verifier_cross_binding_and_altered_proof_fail_closed(self):
        first = load("r7-evidence.json")
        observed = datetime(2030, 1, 1, tzinfo=timezone.utc)
        authority = HMACObservationAuthority()
        wrong = HMACObservationAuthority()
        wrong_proof = proof_for(wrong, first, observed)
        result = apply_evidence(state_for(first, authority, 2), first, proof_mapping=wrong_proof)
        self.assertEqual(result.status, "unknown")
        with self.assertRaises(CampaignContractError):
            restore_state(state_for(first, authority, 2).to_mapping(),
                          verifier=wrong, pinned_verifier=authority)

        other_identity = dataclasses.replace(
            first.identity, attempt_id="cross-attempt", operation_id="cross-operation",
            request_id="cross-request", gateway_id="cross-gateway", process_id="cross-process")
        digest = compute_evidence_sha256(
            other_identity, first.gateway_disposition, first.terminal_disposition,
            first.upstream_forward_count, first.submission, first.typed_transient,
            first.http_status, first.retry_after_seconds, first.code)
        other = dataclasses.replace(first, identity=other_identity, evidence_sha256=digest)
        cross = proof_for(authority, other, observed)
        cross_result = apply_evidence(state_for(first, authority, 2), first, proof_mapping=cross)
        self.assertEqual(cross_result.status, "unknown")

        altered = proof_for(authority, first, observed)
        altered["payload"]["bindings"]["request_id"] = "altered-request"
        altered_result = apply_evidence(state_for(first, authority, 2), first,
                                        proof_mapping=altered)
        self.assertEqual(altered_result.status, "unknown")

    def test_revoked_and_restarted_verifier_generations_fail_closed(self):
        first = load("r7-evidence.json")
        observed = datetime(2030, 1, 1, tzinfo=timezone.utc)
        authority = HMACObservationAuthority()
        state = state_for(first, authority, 2)
        proof = proof_for(authority, first, observed)
        authority.close()
        with self.assertRaises(CampaignContractError):
            apply_evidence(state, first, proof_mapping=proof)
        self.assertIsNone(authority.last_proof)

        old = HMACObservationAuthority()
        persisted = state_for(first, old, 2).to_mapping()
        replacement = HMACObservationAuthority()
        with self.assertRaises(CampaignContractError):
            restore_state(persisted, verifier=replacement, pinned_verifier=replacement)
        same_strings = HMACObservationAuthority()
        same_strings.generation_id = old.generation_id
        same_strings.anchor_id = old.anchor_id
        with self.assertRaises(CampaignContractError):
            restore_state(persisted, verifier=same_strings, pinned_verifier=same_strings)

    def test_concurrent_same_proof_and_state_has_one_transition(self):
        first = load("r7-evidence.json")
        authority = HMACObservationAuthority()
        state = state_for(first, authority, 2)
        proof = proof_for(authority, first, datetime(2030, 1, 1, tzinfo=timezone.utc))
        barrier = threading.Barrier(2)
        results = []
        def run():
            try:
                barrier.wait()
                results.append(("state", apply_evidence(state, first, proof_mapping=proof)))
            except Exception as error:
                results.append(("error", error))
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sorted(kind for kind, _ in results), ["error", "state"])
        accepted = [value for kind, value in results if kind == "state"][0]
        self.assertEqual(accepted.status, "retry_wait")
        self.assertEqual(authority.verification_calls, 1)

    def test_zero_delay_rejected_before_any_consumption_and_proof_remains_usable(self):
        first = load("r7-evidence.json")
        authority = HMACObservationAuthority()
        state = state_for(first, authority, 2)
        proof = proof_for(authority, first, datetime(2030, 1, 1, tzinfo=timezone.utc))
        forged = object.__new__(EvidenceV1)
        for field in EvidenceV1.__dataclass_fields__:
            object.__setattr__(forged, field, getattr(first, field))
        object.__setattr__(forged, "retry_after_seconds", 0)
        with self.assertRaisesRegex(CampaignContractError, "STATE_RETRY_AFTER_INVALID"):
            apply_evidence(state, forged, proof_mapping=proof)
        self.assertEqual(authority.verification_calls, 0)
        self.assertEqual(authority.gateway_consumed_count, 0)
        self.assertEqual(authority.state_consumed_count, 0)
        authority.verify_state(state.body_mapping(), state.state_attestation)
        accepted = apply_evidence(state, first, proof_mapping=proof)
        self.assertEqual(accepted.status, "retry_wait")
        self.assertEqual((authority.gateway_consumed_count,
                          authority.state_consumed_count), (1, 1))

    def test_submitted_and_forwarded_502_are_unknown_without_replay(self):
        first = load("r7-evidence.json")
        digest = compute_evidence_sha256(
            first.identity, first.gateway_disposition, first.terminal_disposition,
            first.upstream_forward_count, "possibly_submitted", first.typed_transient,
            first.http_status, first.retry_after_seconds, "UPSTREAM_502_SUBMITTED")
        submitted = dataclasses.replace(
            first, submission="possibly_submitted", code="UPSTREAM_502_SUBMITTED",
            evidence_sha256=digest)
        authority = HMACObservationAuthority()
        submitted_state = apply_evidence(state_for(submitted, authority, 2), submitted)
        self.assertEqual(submitted_state.status, "unknown")

        forwarded = load("r8-forwarded-502-evidence.json")
        forwarded_state = apply_evidence(state_for(forwarded, authority, 1), forwarded)
        self.assertEqual((classify_authority(forwarded), forwarded_state.status),
                         (Authority.UNKNOWN, "unknown"))
        with self.assertRaises(CampaignContractError):
            retry_ready(forwarded_state, datetime(2030, 1, 1, tzinfo=timezone.utc),
                        next_identity=forwarded.identity,
                        next_evidence_sha256=forwarded.evidence_sha256)


if __name__ == "__main__": unittest.main()
