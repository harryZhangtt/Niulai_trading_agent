import dataclasses
from datetime import datetime, timedelta, timezone
import json
import unittest
from pathlib import Path

from _authority import HMACObservationAuthority, proof_for
from shared.job_runtime.candidates.claude_campaign_v1 import (
    CampaignContractError, CampaignStateV1, EvidenceV1, apply_evidence, create_initial_state,
    compute_evidence_sha256, evidence_from_mapping, named_unknown_reconciliation,
    restore_state, retry_ready,
)

HERE = Path(__file__).resolve()
FIXTURES = HERE.parents[2] / "fixtures" / "claude_campaign_v1"
SOURCE = HERE.parents[3] / "candidates" / "claude_campaign_v1"


def evidence(name): return evidence_from_mapping(json.loads((FIXTURES / name).read_text()))

def initial(item, authority=None, max_attempts=None):
    authority = authority or HMACObservationAuthority()
    state = create_initial_state(item.identity, item.evidence_sha256, authority, authority)
    if max_attempts is not None and state.max_attempts != max_attempts:
        raise CampaignContractError("TEST_MAX_ATTEMPTS_MISMATCH")
    return state

def next_retry_evidence(first):
    identity = dataclasses.replace(
        first.identity, attempt_id="r7-attempt-2", operation_id="r7-operation-2",
        request_id="r7-request-2", gateway_id="gateway-fixture-2", process_id="r7-process-2")
    digest = compute_evidence_sha256(
        identity, first.gateway_disposition, first.terminal_disposition,
        first.upstream_forward_count, first.submission, first.typed_transient,
        first.http_status, first.retry_after_seconds, first.code)
    return dataclasses.replace(first, identity=identity, evidence_sha256=digest)


class StateAndPrivacyTests(unittest.TestCase):
    def test_nominal_and_unknown_states(self):
        r6 = evidence("r6-evidence.json"); r8 = evidence("r8-evidence.json")
        self.assertEqual(apply_evidence(initial(r6), r6).status, "succeeded")
        unknown = apply_evidence(initial(r8), r8)
        self.assertEqual((unknown.status, unknown.blocked_slots), ("unknown", ("slot-1", "slot-2")))
        reconciled = named_unknown_reconciliation(
            unknown, adapter=unknown.reconciliation_adapter, resolved=True)
        self.assertEqual(reconciled.status, "reconciled")

    def test_exact_identity_evidence_and_stable_run_binding(self):
        item = evidence("r6-evidence.json"); state = initial(item)
        mutations = {
            "run_id": {"run_id": "other-run"},
            "attempt_id": {"attempt_id": "other-attempt"},
            "operation_id": {"operation_id": "other-operation"},
            "request_id": {"request_id": "other-request"},
            "gateway_id": {"gateway_id": "other-gateway"},
            "process_id": {"process_id": "other-process"},
            "source_sha256": {"source_sha256": "e" * 64},
            "config_sha256": {"config_sha256": "d" * 64},
        }
        for field, replacements in mutations.items():
            identity = dataclasses.replace(item.identity, **replacements)
            digest = compute_evidence_sha256(
                identity, item.gateway_disposition, item.terminal_disposition,
                item.upstream_forward_count, item.submission, item.typed_transient,
                item.http_status, item.retry_after_seconds, item.code)
            changed = dataclasses.replace(item, identity=identity, evidence_sha256=digest)
            with self.subTest(field=field), self.assertRaises(CampaignContractError):
                apply_evidence(state, changed)

    def test_retry_timing_is_verified_derived_and_restore_tamper_evident(self):
        first = evidence("r7-evidence.json"); authority = HMACObservationAuthority()
        observed = datetime(2030, 1, 1, tzinfo=timezone.utc)
        waiting = apply_evidence(initial(first, authority), first,
                                 proof_mapping=proof_for(authority, first, observed))
        self.assertEqual(waiting.next_retry_at, observed + timedelta(seconds=30))
        value = json.loads(json.dumps(waiting.to_mapping()))
        restored = restore_state(value, verifier=authority, pinned_verifier=authority)
        self.assertEqual(restored, waiting)
        mutations = [
            lambda v: v.update(next_retry_at=observed.isoformat()),
            lambda v: v.update(next_retry_at=(observed + timedelta(seconds=29)).isoformat()),
            lambda v: v.update(retry_observed_at=(observed + timedelta(seconds=1)).isoformat()),
            lambda v: v.update(retry_after_seconds=29),
            lambda v: v.update(verifier_identity="wrong.verifier"),
            lambda v: v.update(verifier_generation="wrong-generation"),
        ]
        for mutate in mutations:
            candidate = json.loads(json.dumps(value)); mutate(candidate)
            with self.assertRaises(CampaignContractError):
                restore_state(candidate, verifier=authority, pinned_verifier=authority)

    def test_cooldown_fresh_fields_and_run_stability(self):
        first = evidence("r7-evidence.json"); authority = HMACObservationAuthority()
        observed = datetime(2030, 1, 1, tzinfo=timezone.utc)
        waiting = apply_evidence(initial(first, authority), first,
                                 proof_mapping=proof_for(authority, first, observed))
        second = next_retry_evidence(first)
        with self.assertRaisesRegex(CampaignContractError, "STATE_COOLDOWN_ACTIVE"):
            retry_ready(waiting, waiting.next_retry_at - timedelta(microseconds=1),
                        next_identity=second.identity, next_evidence_sha256=second.evidence_sha256)
        reused = dataclasses.replace(second.identity, gateway_id=first.identity.gateway_id)
        with self.assertRaisesRegex(CampaignContractError, "STATE_NEXT_IDENTITY_NOT_FRESH"):
            retry_ready(waiting, waiting.next_retry_at,
                        next_identity=reused, next_evidence_sha256=second.evidence_sha256)
        ready = retry_ready(waiting, waiting.next_retry_at,
                            next_identity=second.identity, next_evidence_sha256=second.evidence_sha256)
        self.assertEqual(ready.expected_identity.run_id, first.identity.run_id)

    def test_campaign_caps_status_and_verifier_binding(self):
        r6=evidence("r6-evidence.json"); r7=evidence("r7-evidence.json")
        authority=HMACObservationAuthority(); wrong=HMACObservationAuthority()
        with self.assertRaises(CampaignContractError):
            dataclasses.replace(initial(r6, authority), max_attempts=2)
        with self.assertRaises(CampaignContractError):
            dataclasses.replace(initial(r7, authority), max_attempts=1)
        signed = initial(r6, authority)
        with self.assertRaises(CampaignContractError):
            dataclasses.replace(signed, _verifier=wrong)
        with self.assertRaises(CampaignContractError):
            dataclasses.replace(signed, status="unknown", attempts=1,
                                unknown_slot_id="slot-1", blocked_slots=("slot-1", "slot-2"))

    def test_restore_closed_shape_and_malformed_fences(self):
        item=evidence("r8-evidence.json"); authority=HMACObservationAuthority()
        valid=apply_evidence(initial(item,authority),item).to_mapping()
        mutations=[lambda v:v.update(version=2),lambda v:v.update(campaign_id="R7"),
                   lambda v:v.update(slot_scope=["slot-1","slot-1"]),
                   lambda v:v.update(blocked_slots=["slot-2","slot-1"]),
                   lambda v:v.update(reconciliation_adapter="wrong.adapter")]
        for mutate in mutations:
            candidate=json.loads(json.dumps(valid)); mutate(candidate)
            with self.assertRaises(CampaignContractError):
                restore_state(candidate,verifier=authority,pinned_verifier=authority)

    def test_signed_state_attestation_rejects_coherent_status_and_signature_tamper(self):
        r6 = evidence("r6-evidence.json"); authority = HMACObservationAuthority()
        ready = initial(r6, authority)
        coherent_retry = json.loads(json.dumps(ready.to_mapping()))
        coherent_retry.update(status="retry_wait", attempts=1, max_attempts=2,
                              next_retry_at="2030-01-01T00:00:30+00:00",
                              retry_observed_at="2030-01-01T00:00:00+00:00",
                              retry_after_seconds=30.0)
        with self.assertRaises(CampaignContractError):
            restore_state(coherent_retry, verifier=authority, pinned_verifier=authority)

        terminal = apply_evidence(ready, r6)
        terminal_tamper = json.loads(json.dumps(terminal.to_mapping()))
        terminal_tamper["status"] = "terminal_failed"
        with self.assertRaises(CampaignContractError):
            restore_state(terminal_tamper, verifier=authority, pinned_verifier=authority)

        r8=evidence("r8-evidence.json"); auth2=HMACObservationAuthority()
        unknown=apply_evidence(initial(r8,auth2),r8)
        reconciled=named_unknown_reconciliation(
            unknown,adapter=unknown.reconciliation_adapter,resolved=True)
        reconciled_tamper=json.loads(json.dumps(reconciled.to_mapping()))
        reconciled_tamper.update(status="unknown",unknown_slot_id="slot-1",
                                 blocked_slots=["slot-1","slot-2"])
        with self.assertRaises(CampaignContractError):
            restore_state(reconciled_tamper,verifier=auth2,pinned_verifier=auth2)

        signed=json.loads(json.dumps(reconciled.to_mapping()))
        signed["state_attestation"]["hmac_sha256"]="0"*64
        with self.assertRaises(CampaignContractError):
            restore_state(signed,verifier=auth2,pinned_verifier=auth2)

    def test_every_state_status_has_owner_verified_attestation(self):
        r6=evidence("r6-evidence.json"); auth1=HMACObservationAuthority()
        ready=create_initial_state(r6.identity,r6.evidence_sha256,auth1,auth1)
        success=apply_evidence(ready,r6)
        r8=evidence("r8-evidence.json"); auth2=HMACObservationAuthority()
        unknown=apply_evidence(initial(r8,auth2),r8)
        reconciled=named_unknown_reconciliation(unknown,adapter=unknown.reconciliation_adapter,resolved=True)
        r7=evidence("r7-evidence.json"); auth3=HMACObservationAuthority()
        waiting=apply_evidence(initial(r7,auth3),r7,proof_mapping=proof_for(
            auth3,r7,datetime(2030,1,1,tzinfo=timezone.utc)))
        second=next_retry_evidence(r7)
        ready2=retry_ready(waiting,waiting.next_retry_at,
                           next_identity=second.identity,next_evidence_sha256=second.evidence_sha256)
        failed=apply_evidence(ready2,second,proof_mapping=proof_for(
            auth3,second,datetime(2030,1,2,tzinfo=timezone.utc)))
        for state in (ready,success,unknown,reconciled,waiting,ready2,failed):
            self.assertIsInstance(state.state_attestation, dict)
        # Linear transitions consume predecessor attestations; only current leaves verify.
        for state in (success,reconciled,failed):
            state._verifier.verify_state(state.body_mapping(),state.state_attestation)
        fresh_ready_auth=HMACObservationAuthority()
        fresh_ready=initial(r6,fresh_ready_auth)
        fresh_ready._verifier.verify_state(fresh_ready.body_mapping(),fresh_ready.state_attestation)
        fresh_unknown_auth=HMACObservationAuthority()
        fresh_unknown=apply_evidence(initial(r8,fresh_unknown_auth),r8)
        fresh_unknown._verifier.verify_state(fresh_unknown.body_mapping(),fresh_unknown.state_attestation)
        self.assertEqual(failed.status,"terminal_failed")

    def test_no_provider_network_process_or_sensitive_payload_surface(self):
        forbidden=("subprocess","socket","requests","urllib","Popen","os.system","anthropic","api_key","authorization","cookie","hmac")
        for path in SOURCE.glob("*.py"):
            text=path.read_text().lower()
            for token in forbidden: self.assertNotIn(token.lower(),text,path.name)


if __name__ == "__main__": unittest.main()
