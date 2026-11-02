#!/usr/bin/env python3
"""Deterministic linear-reset-fund math, not a forecasting model.

Returns/costs are decimals and costs are explicit NAV debits per actual reset.
Inputs must already use matching reset times and total-return conventions.
The default leverage is intentional: no security is silently presumed 3x.
"""

import copy
import math
import random

POLICY_VERSION = "2026-10-18-leveraged-funds-1"
WEIGHT_BASES = {"historical_frequency", "calibrated_model", "analyst_judgment",
                "illustrative_equal"}


def _number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Inputs must be finite")
    return value


def _series(value, length, name):
    if isinstance(value, (str, bytes)):
        return [_number(value)] * length
    try:
        iterator = iter(value)
    except TypeError:
        return [_number(value)] * length
    result = [_number(x) for x in iterator]
    if len(result) != length:
        raise ValueError(f"{name} must align with reset returns")
    return result


def analyze_returns(returns, years=None):
    """Compound actual net returns with no extra costs; zero wealth is absorbing.

    Negative factors are invalid actual returns. For synthetic theoretical
    factors <= 0 use simulate_reset_path's explicitly flagged barrier handling.
    """
    returns = [_number(x) for x in returns]
    if not returns or any(x < -1 for x in returns):
        raise ValueError("Require nonempty net returns >= -100%")
    if years is not None:
        years = _number(years)
        if years <= 0:
            raise ValueError("Years must be positive")
    wealth, peak, max_dd = 1.0, 1.0, 0.0
    wealth_path = [wealth]
    for ret in returns:
        wealth *= 1.0 + ret
        if not math.isfinite(wealth):
            raise ValueError("Nonfinite compounded wealth")
        peak = max(peak, wealth)
        max_dd = min(max_dd, wealth / peak - 1.0)
        wealth_path.append(wealth)
    return {"terminal_wealth": wealth, "total_return": wealth - 1.0,
            "log_wealth": math.log(wealth) if wealth > 0 else None,
            "log_wealth_is_negative_infinity": wealth == 0,
            "cagr": wealth ** (1.0 / years) - 1.0 if years else None,
            "max_drawdown": max_dd, "wealth_path": wealth_path,
            "reset_periods": len(returns)}


def simulate_reset_path(benchmark_returns, leverage, cost_debits=0.0, years=None,
                        comparison_net_returns=None):
    """Compute 1 + L_t*r_t - c_t at each specified reset; barrier is absorbing.

    Leverage and costs may be scalar or aligned arrays. Costs can be signed
    (e.g. collateral income); do not deduct costs again from actual NAV data.
    This is not an intraperiod or options/futures-roll/liquidation simulator.
    """
    returns = [_number(x) for x in benchmark_returns]
    if not returns or any(x < -1 for x in returns):
        raise ValueError("Require nonempty benchmark returns >= -100%")
    multiples = _series(leverage, len(returns), "Leverage")
    costs = _series(cost_debits, len(returns), "Costs")
    net, barrier, raw_barrier_factor, alive = [], None, None, True
    for t, (ret, multiple, cost) in enumerate(zip(returns, multiples, costs)):
        factor = 1.0 + multiple * ret - cost
        if not math.isfinite(factor):
            raise ValueError("Nonfinite modeled factor")
        if not alive:
            net.append(0.0)
        elif factor <= 0:
            net.append(-1.0)
            barrier, raw_barrier_factor, alive = t, factor, False
        else:
            net.append(factor - 1.0)
    fund = analyze_returns(net, years)
    benchmark = analyze_returns(returns, years)
    comparison = benchmark
    comparison_basis = "benchmark_without_additional_fund_fees"
    if comparison_net_returns is not None:
        comparison_returns = _series(comparison_net_returns, len(returns), "Comparison")
        comparison = analyze_returns(comparison_returns, years)
        comparison_basis = "specified_comparison_net_returns"
    return {"policy_version": POLICY_VERSION, "fund": fund,
            "benchmark": benchmark, "comparison": comparison,
            "comparison_basis": comparison_basis, "modeled_net_returns": net,
            "barrier_reset_index": barrier,
            "barrier_raw_factor": raw_barrier_factor,
            "benchmark_excess_return": fund["total_return"] - benchmark["total_return"],
            "outperformance": fund["total_return"] - comparison["total_return"]}


def iid_expected_wealth(mean_net_return, periods):
    """Arithmetic expectation with iid finite-mean NET returns, not log growth.

    Caller must justify iid/nonnegative wealth factors. This mean alone does
    not describe median, tails, temporal dependence or an absorbing barrier.
    """
    mean = _number(mean_net_return)
    if mean < -1 or not isinstance(periods, int) or periods < 0:
        raise ValueError("Require mean net return >= -100% and integer periods >= 0")
    return (1.0 + mean) ** periods


def mix_fund_cash(fund_net_returns, cash_net_returns, fund_weight,
                   rebalance_each_reset=False, years=None):
    """Actual portfolio math for a fixed initial mix or fixed rebalanced weight.

    Returns must include component frictions. Rebalancing transaction/tax
    costs are not supplied and must be deducted separately when applicable.
    """
    fund_returns = [_number(x) for x in fund_net_returns]
    cash_returns = _series(cash_net_returns, len(fund_returns), "Cash")
    weight = _number(fund_weight)
    if (not fund_returns or not 0 <= weight <= 1
            or any(x < -1 for x in fund_returns + cash_returns)):
        raise ValueError("Require component returns and weight in [0, 1]")
    if rebalance_each_reset:
        if -1 in fund_returns[:-1] or -1 in cash_returns[:-1]:
            raise ValueError("Rebalancing after component ruin needs an explicit closure/replacement policy")
        returns = [weight * f + (1 - weight) * c
                   for f, c in zip(fund_returns, cash_returns)]
    else:
        fund = analyze_returns(fund_returns)["wealth_path"]
        cash = analyze_returns(cash_returns)["wealth_path"]
        levels = [weight * f + (1 - weight) * c for f, c in zip(fund, cash)]
        returns = [b / a - 1.0 if a > 0 else 0.0
                   for a, b in zip(levels, levels[1:])]
    result = analyze_returns(returns, years)
    result["fund_weight"] = weight
    result["rebalance_each_reset"] = bool(rebalance_each_reset)
    return result


def annual_nav_cost_debits(annual_cost, year_fractions):
    """Explicit SIMPLE accrual convention, not a universal fund cost formula."""
    fractions = [_number(x) for x in year_fractions]
    if not fractions or any(x <= 0 for x in fractions):
        raise ValueError("Require positive elapsed year fractions")
    costs = _series(annual_cost, len(fractions), "Annual NAV cost")
    return [rate * fraction for rate, fraction in zip(costs, fractions)]


def _validate_weights(weights, length):
    weights = [_number(x) for x in weights]
    if len(weights) != length or any(x < 0 for x in weights):
        raise ValueError("Align nonnegative weights with observations")
    if not math.isclose(sum(weights), 1.0, rel_tol=0.0, abs_tol=1e-10):
        raise ValueError("Weights must sum to one; no silent normalization")
    return weights


def weighted_quantile(values, weights, probability):
    """Left inverse of the weighted empirical CDF; no interpolation."""
    values = [_number(x) for x in values]
    weights = _validate_weights(weights, len(values))
    probability = _number(probability)
    if not values or not 0 <= probability <= 1:
        raise ValueError("Require observations and 0 <= quantile <= 1")
    pairs = sorted((v, w) for v, w in zip(values, weights) if w > 0)
    mass = 0.0
    for value, weight in pairs:
        mass += weight
        if mass + 1e-14 >= probability:
            return value
    return pairs[-1][0]


def lower_tail_mean(values, weights, tail_mass=0.05):
    """Mean of worst tail_mass, taking partial mass at a discrete boundary."""
    values = [_number(x) for x in values]
    weights = _validate_weights(weights, len(values))
    tail_mass = _number(tail_mass)
    if not values or not 0 < tail_mass <= 1:
        raise ValueError("Require observations and 0 < tail mass <= 1")
    remaining, weighted_total = tail_mass, 0.0
    for value, weight in sorted(zip(values, weights)):
        take = min(remaining, weight)
        weighted_total += take * value
        remaining -= take
        if remaining <= 1e-14:
            break
    return weighted_total / tail_mass


def summarize_paths(paths, weights, weight_basis, years):
    """Describe stipulated weighted outcomes; weight labels are not calibration."""
    paths = list(paths)
    weights = _validate_weights(weights, len(paths))
    years = _number(years)
    if not paths or years <= 0 or weight_basis not in WEIGHT_BASES:
        raise ValueError("Require paths, positive years and explicit weight basis")
    wealth = [_number(p["fund"]["terminal_wealth"]) for p in paths]
    bases = {p["comparison_basis"] for p in paths}
    if len(bases) != 1:
        raise ValueError("Comparison basis must be consistent across paths")
    base = [_number(p["comparison"]["terminal_wealth"]) for p in paths]
    mdd_losses = [-_number(p["fund"]["max_drawdown"]) for p in paths]
    if any(x < 0 for x in wealth):
        raise ValueError("Wealth cannot be negative")
    expected = sum(w * x for w, x in zip(weights, wealth))
    ruin = sum(w for w, x in zip(weights, wealth) if x == 0)
    expected_log = None if ruin > 0 else sum(
        w * math.log(x) for w, x in zip(weights, wealth) if w > 0)
    top_one_percent_contribution = (
        -lower_tail_mean([-x for x in wealth], weights, 0.01) * 0.01 / expected
        if expected > 0 else None)
    return {"policy_version": POLICY_VERSION, "weight_basis": weight_basis,
            "years": years, "path_count": len(paths),
            "expected_terminal_wealth": expected,
            "expected_return": expected - 1.0,
            "median_terminal_wealth": weighted_quantile(wealth, weights, 0.5),
            "cagr_of_expected_wealth": expected ** (1.0 / years) - 1.0,
            "expected_scenario_cagr": sum(w * (x ** (1.0 / years) - 1.0)
                                          for w, x in zip(weights, wealth)),
            "expected_log_wealth": expected_log,
            "expected_log_is_negative_infinity": ruin > 0,
            "annualized_geometric_wealth_growth":
                math.exp(expected_log / years) - 1.0 if expected_log is not None else -1.0,
            "loss_probability": sum(w for w, x in zip(weights, wealth) if x < 1),
            "loss_at_least_50pct_probability":
                sum(w for w, x in zip(weights, wealth) if x <= 0.5),
            "loss_at_least_80pct_probability":
                sum(w for w, x in zip(weights, wealth) if x <= 0.2),
            "ruin_probability": ruin,
            "comparison_basis": next(iter(bases)),
            "beat_comparison_probability":
                sum(w for w, x, b in zip(weights, wealth, base) if x > b),
            "top_1pct_expected_wealth_contribution": top_one_percent_contribution,
            "terminal_wealth_quantiles": {
                str(q): weighted_quantile(wealth, weights, q)
                for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
            "worst_5pct_mean_return": lower_tail_mean(wealth, weights) - 1.0,
            "expected_max_drawdown_loss": sum(w * x for w, x in zip(weights, mdd_losses)),
            "max_drawdown_loss_p95": weighted_quantile(mdd_losses, weights, 0.95)}


def moving_block_sample(joint_rows, sample_length, block_length, seed):
    """Sample contiguous nonwrapping blocks of JOINT observations, reproducibly.

    Dependence survives only inside blocks; seams and unseen regimes remain
    limitations. Caller must retain dates/regimes and report block sensitivity.
    """
    rows = list(joint_rows)
    if (not rows or not isinstance(sample_length, int) or sample_length <= 0
            or not isinstance(block_length, int) or not 1 <= block_length <= len(rows)):
        raise ValueError("Require rows, positive sample length and valid block length")
    rng, result = random.Random(seed), []
    while len(result) < sample_length:
        start = rng.randrange(len(rows) - block_length + 1)
        result.extend(copy.deepcopy(rows[start:start + block_length]))
    return result[:sample_length]


def eligible_start_indices(wealth, horizon, lookback, drawdown_threshold=None,
                           nonoverlap=False):
    """Past-only trailing-peak drawdown filter with complete future windows.

    wealth[t] is observable at entry t. The next horizon reset returns are
    wealth[t+1]/wealth[t]-1, ..., wealth[t+horizon]/wealth[t+horizon-1]-1.
    Require a full lookback at every start; threshold is signed, e.g. -0.15.
    Nonoverlap greedily keeps the earliest eligible start, fixed ex ante.
    """
    values = [_number(x) for x in wealth]
    if (not values or any(x <= 0 for x in values)
            or not isinstance(horizon, int) or horizon <= 0
            or not isinstance(lookback, int) or lookback <= 0):
        raise ValueError("Require positive wealth, horizon and full lookback")
    if drawdown_threshold is not None:
        drawdown_threshold = _number(drawdown_threshold)
        if not -1 < drawdown_threshold <= 0:
            raise ValueError("Drawdown threshold must be in (-1, 0]")
    starts, next_allowed = [], 0
    for t in range(lookback - 1, len(values) - horizon):
        if nonoverlap and t < next_allowed:
            continue
        dd = values[t] / max(values[t - lookback + 1:t + 1]) - 1.0
        if drawdown_threshold is None or dd <= drawdown_threshold:
            starts.append(t)
            next_allowed = t + horizon
    return starts
