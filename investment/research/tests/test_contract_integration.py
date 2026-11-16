"""Cross-component authority boundaries for IXIC, evidence state, and leverage math."""
import unittest

from investment.research.claim_state import ClaimStateError, authorize_use, validate_claim_state
from investment.research.index_identity import validate_packet
from investment.research.tests.test_claim_state import evidence, record
from investment.research.tests.test_index_identity import gated_packet
from shared.calculation.operators import leveraged_funds
from shared.calculation.validation.test_leveraged_operator import packet as leverage_packet


class ContractIntegrationTests(unittest.TestCase):
    def test_gated_ixic_valuation_projects_only_an_unverifiable_gap(self):
        index = validate_packet(gated_packet())
        self.assertEqual(index["identity"]["official_symbol"], "COMP")
        self.assertEqual(index["availability"]["valuation"]["status"], "unverifiable")
        claim = record(
            "unverifiable",
            rows=[],
            access=[{"source_id": "source-1", "status": "gated"}],
            disposition=None,
            reasons=["gated", "no_relevant_evidence"],
            uses=["gap"],
        )
        projection = validate_claim_state(claim)
        self.assertEqual(projection["state"], "unverifiable")
        self.assertTrue(projection["has_excluded_gap_inputs"])
        for effect in ("affirmative_probability", "affirmative_action", "affirmative_sizing", "affirmative_alert"):
            with self.subTest(effect=effect), self.assertRaises(ClaimStateError):
                authorize_use(claim, effect)

    def test_supported_claim_is_only_a_structural_report_candidate(self):
        claim = record(
            "supported", uses=["report_candidate"],
            rows=[evidence(collector_id="forged-collector")],
            author_id="forged-author",
            operator_id="forged-operator",
            reviewer_id="forged-reviewer",
        )
        projection = authorize_use(claim, "report_candidate")
        self.assertEqual(projection["allowed_uses"], ["report_candidate"])
        self.assertEqual(projection["validation_scope"], "structural_only")
        self.assertFalse(projection["authenticity_verified"])
        self.assertFalse(projection["consequential_authority"])
        for effect in (
            "affirmative_conclusion", "model_input", "affirmative_probability",
            "affirmative_action", "affirmative_sizing", "affirmative_alert",
        ):
            with self.subTest(effect=effect), self.assertRaisesRegex(
                    ClaimStateError, "CLAIM_STATE_USE_FORBIDDEN"):
                authorize_use(claim, effect)

    def test_deterministic_operator_exposes_no_probability_or_trade_authority(self):
        output = leveraged_funds.calculate(leverage_packet("simulate_synthetic_reset_path"))
        self.assertIn("compatibility_boundary", output)
        self.assertIn("result", output)
        def keys(value):
            found = set()
            if isinstance(value, dict):
                for key, child in value.items():
                    found.add(key)
                    found.update(keys(child))
            elif isinstance(value, list):
                for child in value:
                    found.update(keys(child))
            return found
        prohibited = {
            "calibrated_probability", "probability_estimate", "entry_signal",
            "position_size", "trade_recommendation", "order", "broker_action",
        }
        self.assertFalse(keys(output) & prohibited)
        self.assertTrue(output["compatibility_boundary"]["arithmetic_reused"])


if __name__ == "__main__":
    unittest.main()
