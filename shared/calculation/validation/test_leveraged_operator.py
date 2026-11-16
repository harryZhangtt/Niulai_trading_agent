#!/usr/bin/env python3
"""Contract and parity tests for the common leveraged-fund operator adapter."""

import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from shared.calculation.legacy.valuation import leveraged_funds as legacy
from shared.calculation.operators import leveraged_funds as operator

SCRIPT = Path(operator.__file__)
YEARS = 2 / operator.ANNUALIZATION_DAYS


def packet(operation="simulate_synthetic_reset_path"):
    value = {
        "schema_version": operator.SCHEMA_VERSION,
        "adapter_version": operator.ADAPTER_VERSION,
        "governing_policy_revision": 2,
        "legacy_backend_revision": 1,
        "operation": operation,
        "security": {
            "fund_id": "TQQQ",
            "benchmark": {"kind": "exact", "benchmark_id": "NASDAQ-100-TR"},
        },
        "return_basis": "benchmark_total_return",
        "reset": {"period": "daily_close", "timezone": "America/New_York"},
        "horizon": {
            "start_date": "2025-01-01",
            "end_date": "2025-01-03",
            "periods": 2,
            "years": YEARS,
        },
        "dates": ["2025-01-02", "2025-01-03"],
        "leverage": 3,
        "cost_basis": {"type": "none", "costs_already_embedded": False},
        "provenance": {"source_sha256": "a" * 64, "artifact_sha256": "b" * 64},
        "barrier_policy": "absorbing_zero_on_nonpositive_modeled_factor",
        "comparator": {"type": "declared_benchmark_or_proxy"},
        "inputs": {"benchmark_returns": [0.1, -0.05], "cost_debits": 0},
    }
    if operation == "analyze_actual_net_returns":
        value.update(
            return_basis="nav_total_return",
            cost_basis={"type": "embedded_in_returns", "costs_already_embedded": True},
            barrier_policy="actual_returns_floor_minus_one_zero_absorbing",
            comparator={"type": "not_applicable"},
            inputs={"net_returns": [0.2, -0.1]},
        )
    elif operation == "mix_fund_cash_portfolio":
        value.update(
            return_basis="nav_total_return",
            cost_basis={"type": "embedded_in_returns", "costs_already_embedded": True},
            barrier_policy="component_ruin_absorbing_no_replacement",
            comparator={"type": "not_applicable"},
            inputs={"fund_net_returns": [0.3, 0.3], "cash_net_returns": [0, 0],
                    "fund_weight": 1 / 3, "rebalance_each_reset": False},
        )
    elif operation == "sample_joint_moving_blocks":
        value.update(
            leverage=3,
            cost_basis={"type": "none", "costs_already_embedded": False},
            barrier_policy="not_applicable",
            comparator={"type": "not_applicable"},
            inputs={
                "joint_rows": [
                    {"date": "2025-01-02", "benchmark_return": 0.1},
                    {"date": "2025-01-03", "benchmark_return": -0.05},
                ],
                "sample_length": 2,
                "block_length": 1,
                "seed": 0,
            },
        )
    return value


class LeveragedOperatorTests(unittest.TestCase):
    def test_actual_and_synthetic_parity_with_legacy(self):
        actual = packet("analyze_actual_net_returns")
        observed = operator.calculate(actual)["result"]
        self.assertEqual(observed, legacy.analyze_returns([0.2, -0.1], YEARS))

        synthetic = packet()
        observed = operator.calculate(synthetic)["result"]
        expected = legacy.simulate_reset_path([0.1, -0.05], 3, 0, YEARS)
        self.assertEqual(observed, expected)

    def test_smooth_and_volatile_paths_share_endpoint_but_not_fund_wealth(self):
        smooth = packet()
        smooth["inputs"]["benchmark_returns"] = [math.sqrt(1.2) - 1] * 2
        volatile = packet()
        volatile["inputs"]["benchmark_returns"] = [0.5, -0.2]
        smooth_result = operator.calculate(smooth)["result"]
        volatile_result = operator.calculate(volatile)["result"]
        self.assertAlmostEqual(smooth_result["benchmark"]["terminal_wealth"], 1.2)
        self.assertAlmostEqual(volatile_result["benchmark"]["terminal_wealth"], 1.2)
        self.assertGreater(smooth_result["fund"]["terminal_wealth"],
                           volatile_result["fund"]["terminal_wealth"])

    def test_absorbing_barrier_is_explicit_and_preserved(self):
        value = packet()
        value["inputs"]["benchmark_returns"] = [-0.4, 2.0]
        result = operator.calculate(value)
        self.assertEqual(result["barrier_policy"],
                         "absorbing_zero_on_nonpositive_modeled_factor")
        self.assertEqual(result["result"]["fund"]["terminal_wealth"], 0)
        self.assertEqual(result["result"]["barrier_reset_index"], 0)
        self.assertAlmostEqual(result["result"]["barrier_raw_factor"], -0.2)
        del value["barrier_policy"]
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "FIELD_CONTRACT")

    def test_synthetic_costs_are_applied_exactly_once(self):
        value = packet()
        value["cost_basis"] = {"type": "per_reset_nav_debit", "costs_already_embedded": False}
        value["inputs"]["cost_debits"] = [0.01, 0.02]
        result = operator.calculate(value)["result"]
        expected = legacy.simulate_reset_path([0.1, -0.05], 3, [0.01, 0.02], YEARS)
        self.assertEqual(result, expected)
        self.assertAlmostEqual(result["fund"]["terminal_wealth"], 1.29 * 0.83)

    def test_actual_nav_or_market_history_rejects_extra_costs(self):
        value = packet("analyze_actual_net_returns")
        value["cost_basis"] = {"type": "per_reset_nav_debit", "costs_already_embedded": False}
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "ACTUAL_COST_EMBEDDING")
        value = packet("analyze_actual_net_returns")
        value["inputs"]["cost_debits"] = [0.01, 0.01]
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "FIELD_CONTRACT")

    def test_proxy_is_explicitly_labelled_not_rewritten_as_exact(self):
        value = packet()
        value["security"]["benchmark"] = {
            "kind": "proxy",
            "benchmark_id": "NASDAQ-100-TR",
            "proxy_id": "QQQ-TR",
            "proxy_reason": "Exact index history unavailable in supplied artifact",
        }
        result = operator.calculate(value)
        self.assertEqual(result["security"]["benchmark"]["kind"], "proxy")
        self.assertEqual(result["security"]["benchmark"]["proxy_id"], "QQQ-TR")
        bad = copy.deepcopy(value)
        bad["security"]["benchmark"]["proxy_id"] = "NASDAQ-100-TR"
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(bad)
        self.assertEqual(caught.exception.code, "BENCHMARK_LABEL")

    def test_path_summary_parity_and_probability_labels(self):
        value = packet("summarize_synthetic_paths")
        value["inputs"] = {
            "scenarios": [
                {"benchmark_returns": [0.1, 0.1], "cost_debits": 0},
                {"benchmark_returns": [-0.1, -0.1], "cost_debits": 0},
            ],
            "weights": [0.25, 0.75],
            "weight_basis": "analyst_judgment",
        }
        result = operator.calculate(value)["result"]
        paths = [legacy.simulate_reset_path([0.1, 0.1], 3, 0, YEARS),
                 legacy.simulate_reset_path([-0.1, -0.1], 3, 0, YEARS)]
        expected = legacy.summarize_paths(paths, [0.25, 0.75], "analyst_judgment", YEARS)
        for key, expected_value in expected.items():
            self.assertEqual(result[key], expected_value)
        self.assertEqual(result["probability_basis"], {
            "label": "analyst_judgment",
            "supplied_by": "caller",
            "normalized_by_adapter": False,
            "interpretation": "stipulated_scenario_weights_not_probability_estimation",
        })
        value["inputs"]["weights"] = [0.2, 0.2]
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "WEIGHTS")

    def test_summary_rejects_mixed_or_omitted_comparator_definitions(self):
        value = packet("summarize_synthetic_paths")
        value["inputs"] = {
            "scenarios": [
                {"benchmark_returns": [0.1, 0.1], "cost_debits": 0},
                {"benchmark_returns": [0.1, 0.1], "cost_debits": 0,
                 "comparison_net_returns": [0.09, 0.09]},
            ],
            "weights": [0.5, 0.5],
            "weight_basis": "illustrative_equal",
        }
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "FIELD_CONTRACT")

    def test_joint_block_sampling_is_deterministic_and_can_use_final_start(self):
        value = packet("sample_joint_moving_blocks")
        value["horizon"].update(end_date="2025-01-05", periods=4,
                                years=4 / operator.ANNUALIZATION_DAYS)
        value["dates"] = ["2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05"]
        rows = [{"date": day, "benchmark_return": index, "regime": "r" + str(index)}
                for index, day in enumerate(value["dates"])]
        value["inputs"].update(joint_rows=rows, sample_length=2, block_length=2, seed=5)
        expected = legacy.moving_block_sample(rows, 2, 2, 5)
        observed = operator.calculate(value)["result"]["sampled_rows"]
        self.assertEqual(observed, expected)
        self.assertEqual(observed, operator.calculate(value)["result"]["sampled_rows"])
        self.assertEqual([row["benchmark_return"] for row in observed], [2, 3])
        observed[0]["benchmark_return"] = -999
        self.assertEqual(rows[2]["benchmark_return"], 2)

    def test_fund_cash_portfolio_mix_parity(self):
        value = packet("mix_fund_cash_portfolio")
        result = operator.calculate(value)["result"]
        expected = legacy.mix_fund_cash([0.3, 0.3], [0, 0], 1 / 3, False, YEARS)
        self.assertEqual(result, expected)
        self.assertAlmostEqual(result["terminal_wealth"], 1.23)

    def test_dates_arrays_finite_values_and_sizes_are_bounded(self):
        value = packet()
        value["dates"] = ["2025-01-02"]
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "HORIZON")
        value = packet()
        value["inputs"]["benchmark_returns"][0] = float("inf")
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "INPUT_JSON_INVALID")
        value = packet()
        value["horizon"]["periods"] = operator.MAX_PERIODS + 1
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "INTEGER")

    def test_positive_wealth_underflow_is_rejected_not_reported_as_ruin(self):
        value = packet("analyze_actual_net_returns")
        count = 100
        value["horizon"].update(end_date="2025-04-11", periods=count,
                                years=100 / operator.ANNUALIZATION_DAYS)
        from datetime import date, timedelta
        start = date.fromisoformat("2025-01-01")
        value["dates"] = [(start + timedelta(days=index)).isoformat()
                          for index in range(1, count + 1)]
        value["inputs"]["net_returns"] = [-0.999999] * count
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "POSITIVE_WEALTH_UNDERFLOW")

    def test_annualization_is_derived_and_reset_semantics_are_bounded(self):
        value = packet()
        value["horizon"]["years"] = 1
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "HORIZON")
        value = packet()
        value["reset"]["period"] = "monthly_close"
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "RESET")
        result = operator.calculate(packet())
        self.assertEqual(result["annualization_basis"],
                         "actual_calendar_days/365.2425_from_horizon_dates")

    def test_joint_rows_require_bounded_numeric_benchmark_and_cost_fields(self):
        value = packet("sample_joint_moving_blocks")
        del value["inputs"]["joint_rows"][0]["benchmark_return"]
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "JOINT_ROWS")
        value = packet("sample_joint_moving_blocks")
        value["inputs"]["joint_rows"][0]["benchmark_return"] = "0.1"
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "NUMBER")
        value = packet("sample_joint_moving_blocks")
        value["cost_basis"] = {"type": "per_reset_nav_debit", "costs_already_embedded": False}
        for row in value["inputs"]["joint_rows"]:
            row["cost_debit"] = 0.01
        value["inputs"]["joint_rows"][0]["cost_debit"] = float("inf")
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "INPUT_JSON_INVALID")

    def test_exact_empirical_boundary_oracle_corrects_legacy_tolerance(self):
        value = packet("summarize_synthetic_paths")
        value["inputs"] = {
            "scenarios": [
                {"benchmark_returns": [-0.1, -0.1], "cost_debits": 0},
                {"benchmark_returns": [0.1, 0.1], "cost_debits": 0},
            ],
            "weights": [0.499999999999995, 0.500000000000005],
            "weight_basis": "analyst_judgment",
        }
        result = operator.calculate(value)["result"]
        high = legacy.simulate_reset_path([0.1, 0.1], 3, 0, YEARS)["fund"]["terminal_wealth"]
        self.assertEqual(result["median_terminal_wealth"], high)
        self.assertEqual(result["empirical_boundary_arithmetic"],
                         "exact_decimal_rational_adapter_oracle")

    def test_output_size_is_preflighted_and_capped_for_every_operation(self):
        value = packet("sample_joint_moving_blocks")
        value["inputs"]["joint_rows"][0]["payload"] = "x" * 8000
        value["inputs"]["sample_length"] = 1000
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "OUTPUT_SIZE")
        with mock.patch.object(operator, "MAX_OUTPUT_BYTES", 100):
            with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
                operator.calculate(packet())
        self.assertEqual(caught.exception.code, "OUTPUT_SIZE")

    def test_backend_digest_manifest_and_policy_are_authenticated(self):
        with mock.patch.object(operator, "LEGACY_BACKEND_SHA256", "0" * 64):
            with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
                operator.calculate(packet())
        self.assertEqual(caught.exception.code, "BACKEND_COMPATIBILITY")

    def test_strict_json_rejects_duplicate_and_nonfinite_values(self):
        for raw, code in ((b'{"schema_version":1,"schema_version":1}', "DUPLICATE_KEY"),
                          (b'{"value":NaN}', "NONFINITE_JSON"),
                          (b'{"value":Infinity}', "NONFINITE_JSON")):
            with self.subTest(code=code):
                with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
                    operator.decode_packet(raw)
                self.assertEqual(caught.exception.code, code)
                encoded = json.dumps(caught.exception.as_dict(), allow_nan=False)
                self.assertNotIn("NaN", encoded)

    def test_version_fields_and_backend_boundary_are_explicit(self):
        value = packet()
        result = operator.calculate(value)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["governing_policy_revision"], 2)
        self.assertEqual(result["legacy_backend_revision"], 1)
        self.assertEqual(result["compatibility_boundary"], {
            "governing_policy_revision": 2,
            "legacy_backend_revision": 1,
            "legacy_policy_version": legacy.POLICY_VERSION,
            "legacy_backend_sha256": operator.LEGACY_BACKEND_SHA256,
            "manifest_path": "shared/calculation/manifest.json",
            "arithmetic_backend": "shared.calculation.legacy.valuation.leveraged_funds",
            "arithmetic_reused": True,
        })
        value["governing_policy_revision"] = 1
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "POLICY_REVISION")
        value = packet()
        value["legacy_backend_revision"] = 2
        with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
            operator.calculate(value)
        self.assertEqual(caught.exception.code, "BACKEND_REVISION")

    def test_cli_is_deterministic_strict_and_preserves_output_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            output = Path(directory) / "output.json"
            source.write_text(json.dumps(packet()), encoding="utf-8")
            command = [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(output)]
            first = subprocess.run(command, cwd=SCRIPT.parents[3], capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            saved = output.read_bytes()
            self.assertEqual(json.loads(saved), operator.calculate(packet()))
            second = subprocess.run(command, cwd=SCRIPT.parents[3], capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(output.read_bytes(), saved)
            source.write_text('{"value":NaN}', encoding="utf-8")
            failed = subprocess.run(command, cwd=SCRIPT.parents[3], capture_output=True, text=True)
            self.assertEqual(failed.returncode, 2)
            self.assertEqual(failed.stdout, "")
            self.assertEqual(json.loads(failed.stderr)["error"]["code"], "NONFINITE_JSON")
            self.assertEqual(output.read_bytes(), saved)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_post_replace_directory_fsync_failure_is_durability_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.json"
            output.write_text("previous", encoding="utf-8")
            real_fsync = operator.os.fsync
            calls = 0
            def fail_second(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("private detail")
                return real_fsync(fd)
            with mock.patch.object(operator.os, "fsync", side_effect=fail_second):
                with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
                    operator._atomic_output(output, {"status": "ok"})
            self.assertEqual(caught.exception.code, "OUTPUT_DURABILITY_UNKNOWN")
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"status": "ok"})
            self.assertNotIn("private detail", json.dumps(caught.exception.as_dict()))

    def test_atomic_replace_failure_preserves_previous_file_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.json"
            output.write_text("previous", encoding="utf-8")
            with mock.patch.object(operator.os, "replace", side_effect=OSError("private detail")):
                with self.assertRaises(operator.LeveragedFundOperatorError) as caught:
                    operator._atomic_output(output, {"status": "ok"})
            self.assertEqual(caught.exception.code, "OUTPUT_FILE")
            self.assertEqual(output.read_text(encoding="utf-8"), "previous")
            self.assertEqual(list(Path(directory).iterdir()), [output])
            self.assertNotIn("private detail", json.dumps(caught.exception.as_dict()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
