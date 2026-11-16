#!/usr/bin/env python3
"""Strict deterministic adapter for the maintained leveraged-fund arithmetic.

The adapter validates versioned, source-labelled JSON and delegates arithmetic to
``legacy/valuation/leveraged_funds.py``.  It does not acquire data, calibrate or
normalize probabilities, select entries, size positions, or recommend trades.

Canonical operation names are ``analyze_actual_net_returns``,
``simulate_synthetic_reset_path``, ``mix_fund_cash_portfolio``,
``summarize_synthetic_paths``, and ``sample_joint_moving_blocks``.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import date
from fractions import Fraction
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = 1
ADAPTER_VERSION = "2026-11-07-leveraged-fund-operator-1"
GOVERNING_POLICY_REVISION = 2
LEGACY_BACKEND_REVISION = 1
LEGACY_POLICY_VERSION = "2026-10-18-leveraged-funds-1"
LEGACY_BACKEND_SHA256 = "692e1ce861fd8266adfff0aaac3c4b7ca9457fd5d326d907b51406f7f34552cf"
ANNUALIZATION_DAYS = 365.2425
_CALCULATION_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_PATH = _CALCULATION_ROOT / "legacy" / "valuation" / "leveraged_funds.py"
_MANIFEST_PATH = _CALCULATION_ROOT / "manifest.json"
_legacy = None

MAX_INPUT_BYTES = 2_000_000
MAX_OUTPUT_BYTES = 5_000_000
MAX_PERIODS = 10_000
MAX_SCENARIOS = 10_000
MAX_TOTAL_SCENARIO_PERIODS = 200_000
MAX_SAMPLE_LENGTH = 100_000
MAX_JSON_NODES = 250_000
MAX_JSON_DEPTH = 20
MAX_STRING_LENGTH = 8_192
MAX_ROW_FIELDS = 64
MAX_ABS_JSON_NUMBER = 1e12
MAX_ABS_RETURN = 1e6
MAX_ABS_COST = 10.0
MAX_ABS_LEVERAGE = 100.0
_HASH = re.compile(r"[0-9a-f]{64}\Z")

RETURN_BASES = {
    "benchmark_total_return",
    "nav_total_return",
    "market_price_total_return",
}
OPERATIONS = {
    "analyze_actual_net_returns",
    "simulate_synthetic_reset_path",
    "mix_fund_cash_portfolio",
    "summarize_synthetic_paths",
    "sample_joint_moving_blocks",
}
BARRIER_POLICIES = {
    "analyze_actual_net_returns": "actual_returns_floor_minus_one_zero_absorbing",
    "simulate_synthetic_reset_path": "absorbing_zero_on_nonpositive_modeled_factor",
    "mix_fund_cash_portfolio": "component_ruin_absorbing_no_replacement",
    "summarize_synthetic_paths": "absorbing_zero_on_nonpositive_modeled_factor",
    "sample_joint_moving_blocks": "not_applicable",
}

_ERROR_MESSAGES = {
    "INPUT_JSON_TYPE": "Input must be a JSON object",
    "INPUT_JSON_INVALID": "Input must contain only bounded JSON values",
    "INPUT_SIZE": "Input exceeds the resource limit",
    "FIELD_CONTRACT": "Object fields do not match the operation contract",
    "SCHEMA_VERSION": "Unsupported schema version",
    "ADAPTER_VERSION": "Unsupported adapter version",
    "POLICY_REVISION": "Unsupported governing policy revision",
    "BACKEND_REVISION": "Unsupported legacy backend revision",
    "BACKEND_COMPATIBILITY": "Legacy backend is outside the declared compatibility boundary",
    "POSITIVE_WEALTH_UNDERFLOW": "Positive wealth is not representable by the legacy float backend",
    "OUTPUT_SIZE": "Output exceeds the deterministic resource limit",
    "OPERATION": "Unsupported operation",
    "TEXT": "A required text field is invalid",
    "NUMBER": "A required finite bounded number is invalid",
    "INTEGER": "A required bounded integer is invalid",
    "IDENTITY": "Security or benchmark identity is invalid",
    "BENCHMARK_LABEL": "Benchmark must be labelled as exact or as an explicit proxy",
    "RETURN_BASIS": "Return basis is invalid for this operation",
    "RESET": "Reset period or timezone is invalid",
    "HORIZON": "Dates and horizon are invalid or misaligned",
    "LEVERAGE": "Leverage is invalid or misaligned",
    "COST_BASIS": "Cost basis is inconsistent with the supplied returns",
    "ACTUAL_COST_EMBEDDING": "Actual NAV or market-price returns must not be charged costs again",
    "PROVENANCE": "Source and artifact hashes are invalid",
    "BARRIER_POLICY": "The required barrier policy is missing or incompatible",
    "COMPARATOR": "Comparator definition is missing, incompatible, or mixed",
    "RETURNS": "Return observations are invalid or misaligned",
    "WEIGHTS": "Probabilities must be named, aligned, nonnegative, and sum to one",
    "SCENARIOS": "Scenario paths are invalid or exceed the resource limit",
    "JOINT_ROWS": "Joint moving-block rows are invalid or misaligned",
    "BACKEND_REJECTED": "The maintained legacy arithmetic rejected the validated request",
    "RESULT_NONFINITE": "The arithmetic result cannot be represented as strict JSON",
    "INPUT_FILE": "Cannot read valid bounded UTF-8 JSON input",
    "DUPLICATE_KEY": "JSON object contains a duplicate key",
    "NONFINITE_JSON": "Nonfinite JSON constants are forbidden",
    "OUTPUT_FILE": "Cannot atomically write output file",
    "OUTPUT_DURABILITY_UNKNOWN": "Output was replaced but directory durability could not be verified",
}


class LeveragedFundOperatorError(ValueError):
    """Fixed-code, value-redacted adapter failure."""

    def __init__(self, code, path="$"):
        self.code = code
        self.path = path
        super().__init__(code)

    def as_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "governing_policy_revision": GOVERNING_POLICY_REVISION,
            "legacy_backend_revision": LEGACY_BACKEND_REVISION,
            "status": "error",
            "error": {
                "code": self.code,
                "path": self.path,
                "message": _ERROR_MESSAGES[self.code],
            },
        }


def _fail(code, path="$"):
    raise LeveragedFundOperatorError(code, path)


def _load_legacy():
    """Authenticate the frozen file against both the manifest and pinned digest before execution."""
    global _legacy
    try:
        backend_bytes = _BACKEND_PATH.read_bytes()
        digest = hashlib.sha256(backend_bytes).hexdigest()
        manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        entries = [entry for entry in manifest.get("files", [])
                   if entry.get("copy_path") == "legacy/valuation/leveraged_funds.py"]
        valid = (len(entries) == 1
                 and entries[0].get("sha256") == LEGACY_BACKEND_SHA256
                 and entries[0].get("bytes") == len(backend_bytes)
                 and digest == LEGACY_BACKEND_SHA256)
    except (OSError, UnicodeError, ValueError, TypeError):
        valid = False
    if not valid:
        _fail("BACKEND_COMPATIBILITY")
    if _legacy is None:
        spec = importlib.util.spec_from_file_location("_leveraged_funds_legacy_v1", _BACKEND_PATH)
        if spec is None or spec.loader is None:
            _fail("BACKEND_COMPATIBILITY")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            _fail("BACKEND_COMPATIBILITY")
        _legacy = module
    if getattr(_legacy, "POLICY_VERSION", None) != LEGACY_POLICY_VERSION:
        _fail("BACKEND_COMPATIBILITY")
    return _legacy


def _strict_object(value, fields, path):
    if type(value) is not dict:
        _fail("FIELD_CONTRACT", path)
    expected = set(fields)
    if set(value) != expected:
        _fail("FIELD_CONTRACT", path)
    return value


def _text(value, path, *, maximum=256):
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > maximum:
        _fail("TEXT", path)
    return value


def _number(value, path, *, lower=None, upper=None):
    if type(value) not in (int, float):
        _fail("NUMBER", path)
    try:
        result = float(value)
    except (OverflowError, ValueError):
        _fail("NUMBER", path)
    if not math.isfinite(result):
        _fail("NUMBER", path)
    if lower is not None and result < lower:
        _fail("NUMBER", path)
    if upper is not None and result > upper:
        _fail("NUMBER", path)
    return result


def _integer(value, path, *, lower=None, upper=None):
    if type(value) is not int:
        _fail("INTEGER", path)
    if lower is not None and value < lower:
        _fail("INTEGER", path)
    if upper is not None and value > upper:
        _fail("INTEGER", path)
    return value


def _validate_json_tree(value, path="$", depth=0, counter=None):
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
        _fail("INPUT_SIZE", path)
    if value is None or type(value) is bool:
        return
    if type(value) is str:
        if len(value) > MAX_STRING_LENGTH:
            _fail("INPUT_SIZE", path)
        return
    if type(value) is int:
        if abs(value) > MAX_ABS_JSON_NUMBER:
            _fail("INPUT_JSON_INVALID", path)
        return
    if type(value) is float:
        if not math.isfinite(value) or abs(value) > MAX_ABS_JSON_NUMBER:
            _fail("INPUT_JSON_INVALID", path)
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_json_tree(item, f"{path}[{index}]", depth + 1, counter)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str or len(key) > 256:
                _fail("INPUT_JSON_INVALID", path)
            _validate_json_tree(item, f"{path}.{key}", depth + 1, counter)
        return
    _fail("INPUT_JSON_INVALID", path)


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _parse_date(value, path):
    if type(value) is not str:
        _fail("HORIZON", path)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail("HORIZON", path)
    if parsed.isoformat() != value:
        _fail("HORIZON", path)
    return parsed


def _validate_security(value):
    value = _strict_object(value, ("fund_id", "benchmark"), "$.security")
    fund_id = _text(value["fund_id"], "$.security.fund_id", maximum=128)
    benchmark = value["benchmark"]
    if type(benchmark) is not dict or benchmark.get("kind") not in ("exact", "proxy"):
        _fail("BENCHMARK_LABEL", "$.security.benchmark")
    if benchmark["kind"] == "exact":
        _strict_object(benchmark, ("kind", "benchmark_id"), "$.security.benchmark")
        label = {"kind": "exact", "benchmark_id": _text(
            benchmark["benchmark_id"], "$.security.benchmark.benchmark_id", maximum=128)}
    else:
        _strict_object(benchmark, ("kind", "benchmark_id", "proxy_id", "proxy_reason"),
                       "$.security.benchmark")
        benchmark_id = _text(benchmark["benchmark_id"], "$.security.benchmark.benchmark_id", maximum=128)
        proxy_id = _text(benchmark["proxy_id"], "$.security.benchmark.proxy_id", maximum=128)
        if proxy_id == benchmark_id:
            _fail("BENCHMARK_LABEL", "$.security.benchmark")
        label = {
            "kind": "proxy",
            "benchmark_id": benchmark_id,
            "proxy_id": proxy_id,
            "proxy_reason": _text(benchmark["proxy_reason"],
                                  "$.security.benchmark.proxy_reason", maximum=512),
        }
    return {"fund_id": fund_id, "benchmark": label}


def _validate_horizon(horizon, dates, reset_period):
    horizon = _strict_object(horizon, ("start_date", "end_date", "periods", "years"), "$.horizon")
    periods = _integer(horizon["periods"], "$.horizon.periods", lower=1, upper=MAX_PERIODS)
    years = _number(horizon["years"], "$.horizon.years", lower=1e-12, upper=1000)
    start = _parse_date(horizon["start_date"], "$.horizon.start_date")
    end = _parse_date(horizon["end_date"], "$.horizon.end_date")
    if type(dates) is not list or len(dates) != periods:
        _fail("HORIZON", "$.dates")
    parsed_dates = [_parse_date(value, f"$.dates[{index}]") for index, value in enumerate(dates)]
    if not start < parsed_dates[0] or parsed_dates[-1] != end:
        _fail("HORIZON", "$.horizon")
    if any(left >= right for left, right in zip(parsed_dates, parsed_dates[1:])):
        _fail("HORIZON", "$.dates")
    if reset_period != "daily_close":
        _fail("RESET", "$.reset.period")
    derived_years = (end - start).days / ANNUALIZATION_DAYS
    if derived_years <= 0 or not math.isclose(years, derived_years, rel_tol=0.0, abs_tol=1e-12):
        _fail("HORIZON", "$.horizon.years")
    return periods, derived_years


def _validate_leverage(value, periods):
    def one(item, path):
        result = _number(item, path, lower=-MAX_ABS_LEVERAGE, upper=MAX_ABS_LEVERAGE)
        if result == 0:
            _fail("LEVERAGE", path)
        return result
    if type(value) is list:
        if len(value) != periods:
            _fail("LEVERAGE", "$.leverage")
        return [one(item, f"$.leverage[{index}]") for index, item in enumerate(value)]
    return one(value, "$.leverage")


def _validate_cost_basis(value):
    value = _strict_object(value, ("type", "costs_already_embedded"), "$.cost_basis")
    kind = value["type"]
    embedded = value["costs_already_embedded"]
    if kind not in ("none", "embedded_in_returns", "per_reset_nav_debit") or type(embedded) is not bool:
        _fail("COST_BASIS", "$.cost_basis")
    if (kind == "embedded_in_returns") != embedded:
        _fail("COST_BASIS", "$.cost_basis")
    return {"type": kind, "costs_already_embedded": embedded}


def _validate_provenance(value):
    value = _strict_object(value, ("source_sha256", "artifact_sha256"), "$.provenance")
    if type(value["source_sha256"]) is not str or not _HASH.fullmatch(value["source_sha256"]):
        _fail("PROVENANCE", "$.provenance.source_sha256")
    if type(value["artifact_sha256"]) is not str or not _HASH.fullmatch(value["artifact_sha256"]):
        _fail("PROVENANCE", "$.provenance.artifact_sha256")
    return dict(value)


def _validate_comparator(value, operation):
    if type(value) is not dict or "type" not in value:
        _fail("COMPARATOR", "$.comparator")
    kind = value["type"]
    synthetic = operation in ("simulate_synthetic_reset_path", "summarize_synthetic_paths")
    if not synthetic:
        if kind != "not_applicable":
            _fail("COMPARATOR", "$.comparator")
        _strict_object(value, ("type",), "$.comparator")
        return {"type": kind}
    if kind == "declared_benchmark_or_proxy":
        _strict_object(value, ("type",), "$.comparator")
        return {"type": kind}
    if kind == "specified_net_return_series":
        _strict_object(value, ("type", "comparator_id", "return_basis"), "$.comparator")
        basis = value["return_basis"]
        if basis not in RETURN_BASES:
            _fail("COMPARATOR", "$.comparator.return_basis")
        return {"type": kind,
                "comparator_id": _text(value["comparator_id"], "$.comparator.comparator_id", maximum=128),
                "return_basis": basis}
    _fail("COMPARATOR", "$.comparator")


def _vector(value, path, length, *, lower, upper, code):
    if type(value) is not list or len(value) != length:
        _fail(code, path)
    return [_number(item, f"{path}[{index}]", lower=lower, upper=upper)
            for index, item in enumerate(value)]


def _returns(value, path, length):
    return _vector(value, path, length, lower=-1, upper=MAX_ABS_RETURN, code="RETURNS")


def _costs(value, path, length):
    if type(value) is list:
        return _vector(value, path, length, lower=-MAX_ABS_COST, upper=MAX_ABS_COST,
                       code="COST_BASIS")
    return _number(value, path, lower=-MAX_ABS_COST, upper=MAX_ABS_COST)


def _expanded(value, length):
    return value if type(value) is list else [value] * length


def _backend_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (ValueError, TypeError, OverflowError):
        _fail("BACKEND_REJECTED", "$.inputs")


def _reject_positive_underflow(result, returns, path):
    if result["terminal_wealth"] == 0 and all(value > -1 for value in returns):
        _fail("POSITIVE_WEALTH_UNDERFLOW", path)


def _checked_path(returns, leverage, costs, years, comparison):
    result = _backend_call(_legacy.simulate_reset_path, returns, leverage, costs, years, comparison)
    _reject_positive_underflow(result["benchmark"], returns, "$.inputs.benchmark_returns")
    compared = returns if comparison is None else comparison
    _reject_positive_underflow(result["comparison"], compared, "$.inputs.comparison_net_returns")
    if result["fund"]["terminal_wealth"] == 0 and result["barrier_reset_index"] is None:
        _fail("POSITIVE_WEALTH_UNDERFLOW", "$.inputs")
    return result


def _exact_pairs(values, weights):
    return sorted((Fraction(str(value)), Fraction(str(weight)))
                  for value, weight in zip(values, weights) if weight > 0)


def _exact_weighted_quantile(values, weights, probability):
    pairs = _exact_pairs(values, weights)
    target, mass = Fraction(str(probability)), Fraction(0)
    for value, weight in pairs:
        mass += weight
        if mass >= target:
            return float(value)
    return float(pairs[-1][0])


def _exact_lower_tail_mean(values, weights, tail_mass=0.05):
    remaining, total = Fraction(str(tail_mass)), Fraction(0)
    target = remaining
    for value, weight in _exact_pairs(values, weights):
        take = min(remaining, weight)
        total += take * value
        remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        _fail("WEIGHTS", "$.inputs.weights")
    return float(total / target)


def _analyze(packet, common):
    _strict_object(packet["inputs"], ("net_returns",), "$.inputs")
    basis, cost = packet["return_basis"], common["cost_basis"]
    if basis in ("nav_total_return", "market_price_total_return"):
        if cost != {"type": "embedded_in_returns", "costs_already_embedded": True}:
            _fail("ACTUAL_COST_EMBEDDING", "$.cost_basis")
    elif basis == "benchmark_total_return":
        if cost != {"type": "none", "costs_already_embedded": False}:
            _fail("COST_BASIS", "$.cost_basis")
    else:
        _fail("RETURN_BASIS", "$.return_basis")
    values = _returns(packet["inputs"]["net_returns"], "$.inputs.net_returns", common["periods"])
    result = _backend_call(_legacy.analyze_returns, values, common["years"])
    _reject_positive_underflow(result, values, "$.inputs.net_returns")
    return result


def _validate_synthetic_costs(cost_basis, costs, path="$.cost_basis"):
    if cost_basis["costs_already_embedded"]:
        _fail("COST_BASIS", path)
    if cost_basis["type"] == "none":
        if any(value != 0 for value in costs):
            _fail("COST_BASIS", path)
    elif cost_basis["type"] != "per_reset_nav_debit":
        _fail("COST_BASIS", path)


def _scenario(value, path, common, comparator):
    fields = ["benchmark_returns", "cost_debits"]
    if comparator["type"] == "specified_net_return_series":
        fields.append("comparison_net_returns")
    value = _strict_object(value, fields, path)
    returns = _returns(value["benchmark_returns"], path + ".benchmark_returns", common["periods"])
    costs = _costs(value["cost_debits"], path + ".cost_debits", common["periods"])
    _validate_synthetic_costs(common["cost_basis"], _expanded(costs, common["periods"]))
    comparison = None
    if comparator["type"] == "specified_net_return_series":
        comparison = _returns(value["comparison_net_returns"], path + ".comparison_net_returns",
                              common["periods"])
    return returns, costs, comparison


def _simulate(packet, common):
    if packet["return_basis"] != "benchmark_total_return":
        _fail("RETURN_BASIS", "$.return_basis")
    returns, costs, comparison = _scenario(packet["inputs"], "$.inputs", common, common["comparator"])
    return _checked_path(returns, common["leverage"], costs, common["years"], comparison)


def _mix(packet, common):
    if packet["return_basis"] not in ("nav_total_return", "market_price_total_return"):
        _fail("RETURN_BASIS", "$.return_basis")
    if common["cost_basis"] != {"type": "embedded_in_returns", "costs_already_embedded": True}:
        _fail("ACTUAL_COST_EMBEDDING", "$.cost_basis")
    inputs = _strict_object(packet["inputs"],
                            ("fund_net_returns", "cash_net_returns", "fund_weight", "rebalance_each_reset"),
                            "$.inputs")
    fund = _returns(inputs["fund_net_returns"], "$.inputs.fund_net_returns", common["periods"])
    cash = _returns(inputs["cash_net_returns"], "$.inputs.cash_net_returns", common["periods"])
    weight = _number(inputs["fund_weight"], "$.inputs.fund_weight", lower=0, upper=1)
    if type(inputs["rebalance_each_reset"]) is not bool:
        _fail("FIELD_CONTRACT", "$.inputs.rebalance_each_reset")
    result = _backend_call(_legacy.mix_fund_cash, fund, cash, weight,
                           inputs["rebalance_each_reset"], common["years"])
    if inputs["rebalance_each_reset"]:
        positive = all(not ((weight == 1 and f == -1) or (weight == 0 and c == -1)
                           or (0 < weight < 1 and f == -1 and c == -1))
                       for f, c in zip(fund, cash))
    else:
        positive = ((weight > 0 and all(value > -1 for value in fund))
                    or (weight < 1 and all(value > -1 for value in cash)))
    if result["terminal_wealth"] == 0 and positive:
        _fail("POSITIVE_WEALTH_UNDERFLOW", "$.inputs")
    return result


def _summarize(packet, common):
    if packet["return_basis"] != "benchmark_total_return":
        _fail("RETURN_BASIS", "$.return_basis")
    inputs = _strict_object(packet["inputs"], ("scenarios", "weights", "weight_basis"), "$.inputs")
    scenarios = inputs["scenarios"]
    if type(scenarios) is not list or not 1 <= len(scenarios) <= MAX_SCENARIOS:
        _fail("SCENARIOS", "$.inputs.scenarios")
    if len(scenarios) * common["periods"] > MAX_TOTAL_SCENARIO_PERIODS:
        _fail("SCENARIOS", "$.inputs.scenarios")
    weights = _vector(inputs["weights"], "$.inputs.weights", len(scenarios), lower=0, upper=1,
                      code="WEIGHTS")
    if not math.isclose(sum(weights), 1.0, rel_tol=0.0, abs_tol=1e-10):
        _fail("WEIGHTS", "$.inputs.weights")
    weight_basis = inputs["weight_basis"]
    if weight_basis not in _legacy.WEIGHT_BASES:
        _fail("WEIGHTS", "$.inputs.weight_basis")
    paths = []
    for index, scenario in enumerate(scenarios):
        returns, costs, comparison = _scenario(
            scenario, f"$.inputs.scenarios[{index}]", common, common["comparator"])
        paths.append(_checked_path(returns, common["leverage"], costs,
                                   common["years"], comparison))
    summary = _backend_call(_legacy.summarize_paths, paths, weights, weight_basis, common["years"])
    wealth = [path["fund"]["terminal_wealth"] for path in paths]
    drawdown_losses = [-path["fund"]["max_drawdown"] for path in paths]
    summary["median_terminal_wealth"] = _exact_weighted_quantile(wealth, weights, 0.5)
    summary["terminal_wealth_quantiles"] = {
        str(q): _exact_weighted_quantile(wealth, weights, q)
        for q in (0.05, 0.25, 0.5, 0.75, 0.95)
    }
    summary["worst_5pct_mean_return"] = _exact_lower_tail_mean(wealth, weights) - 1.0
    summary["max_drawdown_loss_p95"] = _exact_weighted_quantile(drawdown_losses, weights, 0.95)
    expected = summary["expected_terminal_wealth"]
    summary["top_1pct_expected_wealth_contribution"] = (
        -_exact_lower_tail_mean([-value for value in wealth], weights, 0.01) * 0.01 / expected
        if expected > 0 else None)
    summary["empirical_boundary_arithmetic"] = "exact_decimal_rational_adapter_oracle"
    summary["probability_basis"] = {
        "label": weight_basis,
        "supplied_by": "caller",
        "normalized_by_adapter": False,
        "interpretation": "stipulated_scenario_weights_not_probability_estimation",
    }
    return summary


def _sample(packet, common):
    inputs = _strict_object(packet["inputs"],
                            ("joint_rows", "sample_length", "block_length", "seed"), "$.inputs")
    rows = inputs["joint_rows"]
    if type(rows) is not list or len(rows) != common["periods"]:
        _fail("JOINT_ROWS", "$.inputs.joint_rows")
    has_cost = []
    for index, row in enumerate(rows):
        path = f"$.inputs.joint_rows[{index}]"
        if type(row) is not dict or not 1 <= len(row) <= MAX_ROW_FIELDS:
            _fail("JOINT_ROWS", path)
        if row.get("date") != packet["dates"][index] or "benchmark_return" not in row:
            _fail("JOINT_ROWS", path)
        _number(row["benchmark_return"], path + ".benchmark_return",
                lower=-1, upper=MAX_ABS_RETURN)
        if "cost_debit" in row:
            _number(row["cost_debit"], path + ".cost_debit",
                    lower=-MAX_ABS_COST, upper=MAX_ABS_COST)
        has_cost.append("cost_debit" in row)
    cost_type = common["cost_basis"]["type"]
    if cost_type == "per_reset_nav_debit" and not all(has_cost):
        _fail("COST_BASIS", "$.inputs.joint_rows")
    if cost_type != "per_reset_nav_debit" and any(has_cost):
        _fail("COST_BASIS", "$.inputs.joint_rows")
    sample_length = _integer(inputs["sample_length"], "$.inputs.sample_length",
                             lower=1, upper=MAX_SAMPLE_LENGTH)
    block_length = _integer(inputs["block_length"], "$.inputs.block_length",
                            lower=1, upper=len(rows))
    seed = _integer(inputs["seed"], "$.inputs.seed", lower=-(2 ** 63), upper=2 ** 63 - 1)
    largest_row = max(len(_canonical_json(row).encode("utf-8")) for row in rows)
    if largest_row * sample_length + 4096 > MAX_OUTPUT_BYTES:
        _fail("OUTPUT_SIZE", "$.inputs.sample_length")
    sampled = _backend_call(_legacy.moving_block_sample, rows, sample_length, block_length, seed)
    return {"sampled_rows": sampled, "sample_length": sample_length,
            "block_length": block_length, "seed": seed}


def _validate_result(value, depth=0):
    if depth > MAX_JSON_DEPTH + 10:
        _fail("RESULT_NONFINITE")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            _fail("RESULT_NONFINITE")
        return
    if type(value) is list:
        for item in value:
            _validate_result(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail("RESULT_NONFINITE")
            _validate_result(item, depth + 1)
        return
    _fail("RESULT_NONFINITE")


def calculate(packet):
    """Validate one strict packet and return a deterministic JSON-compatible result."""
    if type(packet) is not dict:
        _fail("INPUT_JSON_TYPE")
    _validate_json_tree(packet)
    fields = (
        "schema_version", "adapter_version", "governing_policy_revision",
        "legacy_backend_revision", "operation", "security", "return_basis",
        "reset", "horizon", "dates", "leverage", "cost_basis", "provenance",
        "barrier_policy", "comparator", "inputs",
    )
    _strict_object(packet, fields, "$")
    if packet["schema_version"] != SCHEMA_VERSION:
        _fail("SCHEMA_VERSION", "$.schema_version")
    if packet["adapter_version"] != ADAPTER_VERSION:
        _fail("ADAPTER_VERSION", "$.adapter_version")
    if packet["governing_policy_revision"] != GOVERNING_POLICY_REVISION:
        _fail("POLICY_REVISION", "$.governing_policy_revision")
    if packet["legacy_backend_revision"] != LEGACY_BACKEND_REVISION:
        _fail("BACKEND_REVISION", "$.legacy_backend_revision")
    _load_legacy()
    operation = packet["operation"]
    if operation not in OPERATIONS:
        _fail("OPERATION", "$.operation")
    security = _validate_security(packet["security"])
    if packet["return_basis"] not in RETURN_BASES:
        _fail("RETURN_BASIS", "$.return_basis")
    reset = _strict_object(packet["reset"], ("period", "timezone"), "$.reset")
    period = _text(reset["period"], "$.reset.period", maximum=64)
    if period != "daily_close":
        _fail("RESET", "$.reset.period")
    timezone = _text(reset["timezone"], "$.reset.timezone", maximum=128)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        _fail("RESET", "$.reset.timezone")
    periods, years = _validate_horizon(packet["horizon"], packet["dates"], period)
    leverage = _validate_leverage(packet["leverage"], periods)
    cost_basis = _validate_cost_basis(packet["cost_basis"])
    provenance = _validate_provenance(packet["provenance"])
    if packet["barrier_policy"] != BARRIER_POLICIES[operation]:
        _fail("BARRIER_POLICY", "$.barrier_policy")
    comparator = _validate_comparator(packet["comparator"], operation)
    common = {"periods": periods, "years": years, "leverage": leverage,
              "cost_basis": cost_basis, "comparator": comparator}
    dispatch = {
        "analyze_actual_net_returns": _analyze,
        "simulate_synthetic_reset_path": _simulate,
        "mix_fund_cash_portfolio": _mix,
        "summarize_synthetic_paths": _summarize,
        "sample_joint_moving_blocks": _sample,
    }
    result = dispatch[operation](packet, common)
    _validate_result(result)
    response = {
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "governing_policy_revision": GOVERNING_POLICY_REVISION,
        "legacy_backend_revision": LEGACY_BACKEND_REVISION,
        "status": "ok",
        "operation": operation,
        "input_sha256": hashlib.sha256(_canonical_json(packet).encode("utf-8")).hexdigest(),
        "compatibility_boundary": {
            "governing_policy_revision": GOVERNING_POLICY_REVISION,
            "legacy_backend_revision": LEGACY_BACKEND_REVISION,
            "legacy_policy_version": LEGACY_POLICY_VERSION,
            "legacy_backend_sha256": LEGACY_BACKEND_SHA256,
            "manifest_path": "shared/calculation/manifest.json",
            "arithmetic_backend": "shared.calculation.legacy.valuation.leveraged_funds",
            "arithmetic_reused": True,
        },
        "security": security,
        "return_basis": packet["return_basis"],
        "reset": {"period": period, "timezone": timezone},
        "horizon": dict(packet["horizon"]),
        "annualization_basis": "actual_calendar_days/365.2425_from_horizon_dates",
        "cost_basis": cost_basis,
        "provenance": provenance,
        "barrier_policy": packet["barrier_policy"],
        "comparator": comparator,
        "result": result,
    }
    _validate_result(response)
    if len(_canonical_json(response).encode("utf-8")) > MAX_OUTPUT_BYTES:
        _fail("OUTPUT_SIZE")
    return response


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("DUPLICATE_KEY")
        result[key] = value
    return result


def decode_packet(content):
    """Strict-decode bounded UTF-8 JSON bytes, rejecting duplicates and NaN."""
    if type(content) is not bytes:
        _fail("INPUT_FILE")
    if len(content) > MAX_INPUT_BYTES:
        _fail("INPUT_SIZE")
    try:
        packet = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: _fail("NONFINITE_JSON"),
        )
    except LeveragedFundOperatorError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        _fail("INPUT_FILE")
    _validate_json_tree(packet)
    return packet


def load_packet(path):
    try:
        with Path(path).open("rb") as stream:
            content = stream.read(MAX_INPUT_BYTES + 1)
    except OSError:
        _fail("INPUT_FILE")
    if len(content) > MAX_INPUT_BYTES:
        _fail("INPUT_SIZE")
    return decode_packet(content)


def _atomic_output(path, result):
    destination = Path(path)
    temporary = None
    replaced = False
    try:
        encoded = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True,
                             allow_nan=False) + "\n"
        if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
            _fail("OUTPUT_SIZE")
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=destination.parent,
                prefix="." + destination.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
        replaced = True
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except LeveragedFundOperatorError:
        raise
    except (OSError, TypeError, ValueError):
        _fail("OUTPUT_DURABILITY_UNKNOWN" if replaced else "OUTPUT_FILE")
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        try:
            if args.input.resolve() == args.output.resolve():
                _fail("OUTPUT_FILE")
        except OSError:
            _fail("INPUT_FILE")
        result = calculate(load_packet(args.input))
        _atomic_output(args.output, result)
    except LeveragedFundOperatorError as error:
        print(_canonical_json(error.as_dict()), file=sys.stderr)
        return 2
    print(_canonical_json({
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "governing_policy_revision": GOVERNING_POLICY_REVISION,
        "legacy_backend_revision": LEGACY_BACKEND_REVISION,
        "status": "ok",
        "operation": result["operation"],
        "input_sha256": result["input_sha256"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
