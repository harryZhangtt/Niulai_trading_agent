#!/usr/bin/env python3
"""Contract tests for actual math and known statistical failure modes."""

from decimal import Decimal, localcontext
from itertools import permutations, product
import math
import random
import unittest

from leveraged_funds import (
    analyze_returns, annual_nav_cost_debits, eligible_start_indices,
    iid_expected_wealth, lower_tail_mean, mix_fund_cash, moving_block_sample,
    simulate_reset_path, summarize_paths, weighted_quantile,
)


def independent_decimal_path(returns, leverage, costs):
    with localcontext() as context:
        context.prec = 50
        wealth = Decimal(1)
        for ret, cost in zip(returns, costs):
            factor = Decimal(1) + Decimal(str(leverage)) * Decimal(str(ret)) - Decimal(str(cost))
            wealth *= max(Decimal(0), factor)
        return float(wealth)


class LinearResetTests(unittest.TestCase):
    def test_same_sign_uptrend_exceeds_simple_multiple(self):
        result = simulate_reset_path([0.1, 0.1], 3)
        self.assertAlmostEqual(result["fund"]["terminal_wealth"], 1.69)
        self.assertAlmostEqual(result["benchmark"]["total_return"], 0.21)
        self.assertGreater(result["fund"]["total_return"], 3 * 0.21)

    def test_same_sign_downtrend_remains_severe_absolute_loss(self):
        result = simulate_reset_path([-0.1, -0.1], 3)
        self.assertAlmostEqual(result["fund"]["total_return"], -0.51)
        self.assertGreater(result["fund"]["total_return"], 3 * -0.19)

    def test_flat_endpoint_round_trip_can_lose(self):
        result = simulate_reset_path([0.1, -1 / 11], 3)
        self.assertAlmostEqual(result["benchmark"]["terminal_wealth"], 1)
        self.assertAlmostEqual(result["fund"]["terminal_wealth"], 0.9454545454545454)

    def test_same_endpoint_different_variation(self):
        smooth = simulate_reset_path([math.sqrt(1.2) - 1] * 2, 3)
        choppy = simulate_reset_path([0.5, -0.2], 3)
        self.assertAlmostEqual(smooth["benchmark"]["terminal_wealth"], 1.2)
        self.assertAlmostEqual(choppy["benchmark"]["terminal_wealth"], 1.2)
        self.assertGreater(smooth["fund"]["terminal_wealth"], choppy["fund"]["terminal_wealth"])

    def test_fixed_observations_permutation_terminal_not_drawdown(self):
        pairs = [(0.1, 0.001), (-0.05, 0.002), (0.07, -0.0005), (-0.04, 0.001)]
        results = [simulate_reset_path([x[0] for x in p], 3, [x[1] for x in p])
                   for p in permutations(pairs)]
        for result in results:
            self.assertAlmostEqual(result["fund"]["terminal_wealth"], results[0]["fund"]["terminal_wealth"])
        self.assertGreater(len({round(x["fund"]["max_drawdown"], 12) for x in results}), 1)

    def test_theoretical_barrier_absorbs_and_records_raw_factor(self):
        result = simulate_reset_path([-0.4, 2.0], 3)
        self.assertEqual(result["fund"]["terminal_wealth"], 0)
        self.assertEqual(result["modeled_net_returns"], [-1, 0])
        self.assertEqual(result["barrier_reset_index"], 0)
        self.assertAlmostEqual(result["barrier_raw_factor"], -0.2)
        self.assertTrue(result["fund"]["log_wealth_is_negative_infinity"])

    def test_inverse_needs_actual_reset_not_total_return_multiple(self):
        result = simulate_reset_path([0.1, 0.1], -2)
        self.assertAlmostEqual(result["fund"]["terminal_wealth"], 0.64)
        self.assertNotAlmostEqual(result["fund"]["total_return"], -2 * 0.21)

    def test_variable_exposure_and_explicit_signed_costs(self):
        result = simulate_reset_path([0.1, -0.1], [2, 1], [0.01, -0.005])
        self.assertAlmostEqual(result["fund"]["terminal_wealth"], 1.19 * 0.905)

    def test_simple_cost_accrual_uses_elapsed_days(self):
        debits = annual_nav_cost_debits([0.08, 0.09], [1 / 365, 3 / 365])
        self.assertAlmostEqual(sum(debits), 0.35 / 365)
        result = simulate_reset_path([0, 0], 3, debits)
        self.assertAlmostEqual(result["fund"]["terminal_wealth"], (1 - debits[0]) * (1 - debits[1]))

    def test_actual_nav_return_not_charged_costs_again(self):
        result = analyze_returns([0.2, -0.1])
        self.assertAlmostEqual(result["terminal_wealth"], 1.08)

    def test_investable_comparator_is_separate(self):
        result = simulate_reset_path([0.1, 0.1], 3, comparison_net_returns=[0.099, 0.099])
        self.assertEqual(result["comparison_basis"], "specified_comparison_net_returns")
        self.assertAlmostEqual(result["comparison"]["terminal_wealth"], 1.099 ** 2)
        self.assertAlmostEqual(result["outperformance"], 1.3 ** 2 - 1.099 ** 2)
        self.assertAlmostEqual(result["benchmark_excess_return"], 1.3 ** 2 - 1.1 ** 2)
        self.assertNotAlmostEqual(result["outperformance"], result["benchmark_excess_return"])

    def test_custom_comparator_can_change_outperformance_sign(self):
        result = simulate_reset_path([0.1], 2, comparison_net_returns=[0.25])
        self.assertGreater(result["benchmark_excess_return"], 0)
        self.assertLess(result["outperformance"], 0)
        summary = summarize_paths([result], [1], "analyst_judgment", 1)
        self.assertEqual(summary["beat_comparison_probability"], 0)

    def test_fifty_digit_independent_crosscheck_many_valid_and_barrier_paths(self):
        rng = random.Random(8675309)
        for leverage in (-3, -1, 1, 2, 3):
            for _ in range(40):
                returns = [rng.uniform(-0.4, 0.4) for _ in range(12)]
                costs = [rng.uniform(-0.001, 0.003) for _ in returns]
                observed = simulate_reset_path(returns, leverage, costs)["fund"]["terminal_wealth"]
                expected = independent_decimal_path(returns, leverage, costs)
                self.assertAlmostEqual(observed, expected, delta=1e-12 * max(1, expected))

    def test_invalid_factors_lengths_and_infinite_inputs_rejected(self):
        invalid = [lambda: simulate_reset_path([], 3),
                   lambda: simulate_reset_path([-1.1], 3),
                   lambda: simulate_reset_path([0.1], [3, 3]),
                   lambda: simulate_reset_path([0.1], 3, float("nan")),
                   lambda: analyze_returns([-1.1]),
                   lambda: analyze_returns([float("inf")]),
                   lambda: annual_nav_cost_debits(0.1, [0]),
                   lambda: simulate_reset_path([0.1], 3, years=-1)]
        for call in invalid:
            with self.assertRaises(ValueError):
                call()


class DistributionTests(unittest.TestCase):
    def test_iid_variance_changes_log_but_not_same_mean_expected_wealth(self):
        periods, drift, volatility = 4, 0.01, 0.05
        smooth = simulate_reset_path([drift] * periods, 3)
        paths = [simulate_reset_path(returns, 3)
                 for returns in product((drift - volatility, drift + volatility), repeat=periods)]
        weights = [1 / len(paths)] * len(paths)
        summary = summarize_paths(paths, weights, "calibrated_model", years=1)
        theoretical = iid_expected_wealth(3 * drift, periods)
        self.assertAlmostEqual(summary["expected_terminal_wealth"], theoretical)
        self.assertAlmostEqual(summary["expected_terminal_wealth"], smooth["fund"]["terminal_wealth"])
        self.assertLess(summary["expected_log_wealth"], smooth["fund"]["log_wealth"])

    def test_mean_median_log_and_bull_tail_concentration_are_separate(self):
        paths = [simulate_reset_path([-0.5], 1), simulate_reset_path([99], 1)]
        summary = summarize_paths(paths, [0.99, 0.01], "analyst_judgment", years=2)
        self.assertAlmostEqual(summary["expected_terminal_wealth"], 1.495)
        self.assertAlmostEqual(summary["median_terminal_wealth"], 0.5)
        self.assertLess(summary["expected_log_wealth"], 0)
        self.assertAlmostEqual(summary["top_1pct_expected_wealth_contribution"], 1 / 1.495)
        self.assertNotAlmostEqual(summary["cagr_of_expected_wealth"], summary["expected_scenario_cagr"])

    def test_positive_weight_ruin_makes_expected_log_negative_infinity(self):
        paths = [simulate_reset_path([-0.4], 3), simulate_reset_path([0.1], 3)]
        summary = summarize_paths(paths, [0.01, 0.99], "analyst_judgment", years=1)
        self.assertEqual(summary["ruin_probability"], 0.01)
        self.assertIsNone(summary["expected_log_wealth"])
        self.assertTrue(summary["expected_log_is_negative_infinity"])
        self.assertEqual(summary["annualized_geometric_wealth_growth"], -1)

    def test_zero_weight_ruin_does_not_contaminate_log(self):
        paths = [simulate_reset_path([-0.4], 3), simulate_reset_path([0.1], 3)]
        summary = summarize_paths(paths, [0, 1], "illustrative_equal", years=1)
        self.assertAlmostEqual(summary["expected_log_wealth"], math.log(1.3))

    def test_weighted_quantiles_ignore_zero_mass(self):
        self.assertEqual(weighted_quantile([0, 1, 2], [0, 0.7, 0.3], 0), 1)
        self.assertEqual(weighted_quantile([0, 1, 2], [0, 0.7, 0.3], 0.95), 2)

    def test_expected_shortfall_partially_uses_discrete_boundary(self):
        self.assertAlmostEqual(lower_tail_mean([0, 0.5, 2], [0.02, 0.08, 0.90], 0.05), 0.3)

    def test_max_drawdown_includes_initial_capital_peak(self):
        result = analyze_returns([-0.3, 0.5, -0.1])
        self.assertAlmostEqual(result["max_drawdown"], -0.3)

    def test_probabilities_not_silently_normalized_or_unnamed(self):
        paths = [simulate_reset_path([0.1], 3)]
        for weights, basis in [([0.9], "analyst_judgment"), ([-1], "analyst_judgment"),
                               ([1], "measured_future_odds")]:
            with self.assertRaises(ValueError):
                summarize_paths(paths, weights, basis, 1)

    def test_comparator_definitions_cannot_mix(self):
        paths = [simulate_reset_path([0.1], 3),
                 simulate_reset_path([0.1], 3, comparison_net_returns=[0.09])]
        with self.assertRaises(ValueError):
            summarize_paths(paths, [0.5, 0.5], "analyst_judgment", 1)


class PortfolioAndSamplingTests(unittest.TestCase):
    def test_initial_one_third_mix_is_not_daily_rebalanced_mix(self):
        static = mix_fund_cash([0.3, 0.3], 0, 1 / 3)
        rebalanced = mix_fund_cash([0.3, 0.3], 0, 1 / 3, True)
        self.assertAlmostEqual(static["terminal_wealth"], 1.23)
        self.assertAlmostEqual(rebalanced["terminal_wealth"], 1.21)

    def test_portfolio_can_survive_fund_ruin(self):
        result = mix_fund_cash([-1, 0], [0.01, 0.01], 0.1)
        self.assertAlmostEqual(result["terminal_wealth"], 0.9 * 1.01 ** 2)
        self.assertFalse(result["log_wealth_is_negative_infinity"])

    def test_portfolio_expected_log_is_not_weighted_fund_log(self):
        fund_logs = [math.log(0.5), math.log(100)]
        portfolio = [mix_fund_cash([-0.5], 0, 0.01), mix_fund_cash([99], 0, 0.01)]
        fund_expected_log = 0.99 * fund_logs[0] + 0.01 * fund_logs[1]
        portfolio_expected_log = 0.99 * portfolio[0]["log_wealth"] + 0.01 * portfolio[1]["log_wealth"]
        self.assertLess(fund_expected_log, 0)
        self.assertGreater(portfolio_expected_log, 0)
        self.assertNotAlmostEqual(portfolio_expected_log, 0.01 * fund_expected_log)

    def test_block_sampling_keeps_joint_rows_and_contiguous_within_blocks(self):
        rows = [{"return": i, "cost": i / 10} for i in range(10)]
        sampled = moving_block_sample(rows, 11, 3, 12345)
        self.assertEqual(sampled, moving_block_sample(rows, 11, 3, 12345))
        for i, row in enumerate(sampled):
            self.assertEqual(row["cost"], row["return"] / 10)
            if i % 3:
                self.assertEqual(row["return"], sampled[i - 1]["return"] + 1)
        sampled[0]["return"] = -999
        self.assertNotEqual(rows[0]["return"], -999)

    def test_entry_filter_past_only_complete_horizon_and_nonoverlap(self):
        wealth = [100, 120, 102, 85, 70, 65, 90, 100]
        self.assertEqual(eligible_start_indices(wealth, 2, 2, -0.1), [2, 3, 4])
        self.assertEqual(eligible_start_indices(wealth, 2, 2, -0.1, True), [2, 4])
        # Altering future observations cannot change an already eligible start.
        altered = wealth[:5] + [1000, 1000, 1000]
        self.assertEqual(eligible_start_indices(altered, 2, 2, -0.1)[:3], [2, 3, 4])

    def test_bad_portfolio_component_cannot_hide_in_small_weight(self):
        with self.assertRaises(ValueError):
            mix_fund_cash([-2], 0, 0.01, True)

    def test_rebalanced_portfolio_needs_policy_after_component_closure(self):
        with self.assertRaises(ValueError):
            mix_fund_cash([-1, 0.1], 0.01, 0.1, True)

    def test_decimal_scalar_and_string_year_are_converted_consistently(self):
        result = simulate_reset_path([0.1], Decimal(3), Decimal("0.01"), years="1")
        self.assertAlmostEqual(result["fund"]["cagr"], 0.29)


if __name__ == "__main__":
    unittest.main(verbosity=2)
