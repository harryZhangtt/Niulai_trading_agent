from datetime import timedelta
import unittest

from shared.job_runtime.candidates.claude_next_phase_v1 import (
    IntegrationContractError, adapt_authenticated_summary, complete_retry)
from ._support import identity, o1, raw, stack

class AdapterTests(unittest.TestCase):
    def authenticate(self, fixture, campaign):
        verifier, gateway = stack(); item = identity(campaign)
        summary = verifier._issue_authenticated_summary(raw(fixture), identity=item, o1_binding=o1(item))
        return verifier, gateway, item, summary

    def test_nominal_maps_to_r6_success(self):
        verifier, gateway, item, summary = self.authenticate("nominal.json", "R6")
        result = adapt_authenticated_summary(item, summary, verifier=verifier, o1_binding=o1(item))
        self.assertEqual((result.route, result.status, result.request_count, result.upstream_forward_count),
                         ("R6", "succeeded", 1, 1))
        self.assertEqual(gateway.calls, 0)

    def test_pre_forward_maps_to_r7_retry_wait_and_verifies_owner_call(self):
        verifier, gateway, item, summary = self.authenticate("pre-forward-502.json", "R7")
        result = adapt_authenticated_summary(item, summary, verifier=verifier, o1_binding=o1(item))
        self.assertEqual((result.route, result.status, result.action, result.retry_after_seconds),
                         ("R7", "retry_wait", "restart", 30))
        self.assertEqual(gateway.calls, 1)
        self.assertEqual(gateway.proofs[0][2], 1)
        self.assertEqual(verifier.verification_calls, 1)

    def test_retry_wait_survives_mapping_restart_and_allows_one_later_forward(self):
        verifier, _, item, summary = self.authenticate("pre-forward-502.json", "R7")
        first = adapt_authenticated_summary(item, summary, verifier=verifier, o1_binding=o1(item))
        restored = first.state.to_mapping()
        from shared.job_runtime.candidates.claude_campaign_v1 import restore_state
        first_state = restore_state(restored, verifier=verifier, pinned_verifier=verifier)
        object.__setattr__(first, "state", first_state)
        next_item = identity("R7", attempt="2", operation="2", request="2", process="2")
        next_summary = verifier._issue_authenticated_summary(raw("nominal.json"), identity=next_item, o1_binding=o1(next_item))
        self.assertEqual(verifier.summary_consumption_calls, 1)
        result = complete_retry(first, next_item, next_summary, verifier=verifier,
                                o1_binding=o1(next_item), now=first.state.next_retry_at + timedelta(seconds=1))
        self.assertEqual((result.route, result.status, result.request_count, result.state.attempts),
                         ("R6", "succeeded", 2, 2))
        self.assertEqual(verifier.summary_consumption_calls, 2)

    def test_forwarded_502_maps_to_unknown_no_replay(self):
        verifier, _, item, summary = self.authenticate("forwarded-502.json", "R8")
        result = adapt_authenticated_summary(item, summary, verifier=verifier, o1_binding=o1(item))
        self.assertEqual((result.route, result.status, result.action), ("R8", "unknown", "reconcile_only"))
        self.assertFalse(result.replay_permitted); self.assertTrue(result.unknown_fenced)
        self.assertEqual(result.state.blocked_slots, ("slot-1", "slot-2"))

    def test_cut_maps_to_unknown_no_replay(self):
        verifier, _, item, summary = self.authenticate("cut.json", "R8")
        result = adapt_authenticated_summary(item, summary, verifier=verifier, o1_binding=o1(item))
        self.assertEqual((result.route, result.status, result.upstream_forward_count), ("R8", "unknown", 1))
        self.assertFalse(result.replay_permitted)

    def test_raw_summary_is_rejected_by_adapter(self):
        verifier, _, item, _ = self.authenticate("nominal.json", "R6")
        with self.assertRaises((IntegrationContractError, TypeError, AttributeError)):
            adapt_authenticated_summary(item, raw("nominal.json"), verifier=verifier, o1_binding=o1(item))

    def test_bad_gateway_proof_is_rejected(self):
        verifier, _, item, _ = self.authenticate("nominal.json", "R6")
        value = raw("pre-forward-502.json"); value["proof"] = {"forged": True}
        with self.assertRaises(IntegrationContractError):
            verifier._issue_authenticated_summary(value, identity=identity("R7"), o1_binding=o1(identity("R7")))

    def test_o1_operation_and_prompt_identity_are_bound(self):
        verifier, _, item, _ = self.authenticate("nominal.json", "R6")
        bad = type(o1(item))("different-operation", item.prompt_id, "4"*64, "5"*64)
        with self.assertRaises(IntegrationContractError):
            verifier._issue_authenticated_summary(raw("nominal.json"), identity=item, o1_binding=bad)

if __name__ == "__main__": unittest.main()
