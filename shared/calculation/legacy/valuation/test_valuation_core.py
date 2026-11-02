#!/usr/bin/env python3
"""Check economically material invariants, without company forecasts."""

from decimal import Decimal
import unittest
from valuation_core import (equity_value, expected_wealth, gross_debt_wacc,
                            terminal_fcff, validate_policy)


class ValuationChecks(unittest.TestCase):
    def base(self):
        return {"cashflow_basis": "FCFF", "discount_rate_type": "WACC",
                "sbc_treatment": "expense", "distribution_policy": "distribute"}

    def test_sustainable_growth_has_reinvestment_cost(self):
        value = terminal_fcff(100, ".03", ".20", ".10")
        self.assertEqual(value["reinvestment"], 15)
        self.assertEqual(value["fcff"], 85)
        self.assertAlmostEqual(value["terminal_ev"], Decimal(85) / Decimal(".07"))
        with self.assertRaises(ValueError):
            terminal_fcff(100, ".10", ".20", ".10")

    def test_current_bridge_is_not_discounted_as_terminal_debt(self):
        result = equity_value([11, 12.1], 121, ".10", 20, 10)
        self.assertAlmostEqual(result["enterprise_pv"], 120)
        self.assertAlmostEqual(result["per_share"], 10)

    def test_future_private_asset_realization_discounted_once(self):
        result = equity_value([0, 0], 0, ".10", 0, 1,
                              realization_cashflows=[0, 121])
        self.assertAlmostEqual(result["per_share"], 100)

    def test_negative_cash_year_is_not_deleted(self):
        result = equity_value([-11, 0], 121, ".10", 0, 1)
        self.assertAlmostEqual(result["per_share"], 90)

    def test_required_return_is_separate_from_fair_value(self):
        fair = equity_value([10] * 10, 100, ".10", 0, 1)["per_share"]
        entry = equity_value([10] * 10, 100, ".15", 0, 1)["per_share"]
        self.assertAlmostEqual(fair, 100)
        self.assertLess(entry, fair)
        self.assertEqual(validate_policy(self.base()), [])

    def test_rejects_double_sbc_mixed_financing_and_cash(self):
        model = self.base() | {"same_future_sbc_dilution": True,
                               "interest_deducted_in_cashflow": True,
                               "distribute_and_retain_same_cash": True}
        self.assertEqual(len(validate_policy(model)), 3)

    def test_large_gap_requires_market_case_and_attribution(self):
        model = self.base() | {"central_fair_value_to_price": ".1"}
        self.assertEqual(len(validate_policy(model)), 3)
        model |= {"gap_attribution_complete": True,
                  "strongest_market_case_complete": True, "reverse_dcf_complete": True}
        self.assertEqual(validate_policy(model), [])

    def test_expected_wealth_does_not_average_growth_rates(self):
        self.assertEqual(expected_wealth([50, 200], [".5", ".5"]), 125)
        with self.assertRaises(ValueError):
            expected_wealth([50, 200], [".5", ".6"])

    def test_terminal_cash_cliff_requires_an_explanation(self):
        model = self.base() | {"terminal_nopat_growth": ".03",
                               "terminal_fcff_drop_ratio": ".20"}
        self.assertEqual(len(validate_policy(model)), 1)
        model["terminal_cliff_justified"] = True
        self.assertEqual(validate_policy(model), [])

    def test_reverse_probability_must_be_feasible(self):
        model = self.base() | {"fixed_base_probability": ".50",
                               "reverse_bull_probability": ".599"}
        self.assertEqual(len(validate_policy(model)), 1)
        model["reverse_bull_probability"] = ".499"
        self.assertEqual(validate_policy(model), [])

    def test_wacc_uses_nonnegative_gross_debt_financing_weights(self):
        value = gross_debt_wacc(100, 20, ".10", ".05", ".20")
        self.assertAlmostEqual(value["equity_weight"] + value["debt_weight"], 1)
        self.assertAlmostEqual(value["wacc"], Decimal(".09"))
        self.assertEqual(gross_debt_wacc(100, 0, ".10", ".05", ".20")["wacc"], Decimal(".10"))
        with self.assertRaises(ValueError):
            gross_debt_wacc(100, -20, ".10", ".05", ".20")

    def test_reading_a_skill_is_not_complete_three_statement_execution(self):
        model = self.base() | {"complete_three_statement_claimed": True}
        self.assertEqual(len(validate_policy(model)), 10)
        model["complete_three_statement_claimed"] = False
        self.assertEqual(validate_policy(model), [])

    def test_net_debt_wacc_basis_rejected(self):
        model = self.base() | {"wacc_debt_weight_basis": "net_debt"}
        self.assertEqual(len(validate_policy(model)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
