#!/usr/bin/env python3
"""Transparent Decimal valuation primitives; forecasts remain analyst-owned."""

from decimal import Decimal, localcontext
import json
import sys

POLICY_VERSION = "2026-10-15-growth-aware-1"


def d(value):
    value = value if isinstance(value, Decimal) else Decimal(str(value))
    if not value.is_finite():
        raise ValueError("Inputs must be finite")
    return value


def pv(cashflows, rate):
    rate = d(rate)
    if rate <= -1:
        raise ValueError("Discount rate must exceed -100%")
    return sum((d(cf) / (1 + rate) ** t
                for t, cf in enumerate(cashflows, 1)), Decimal(0))


def gross_debt_wacc(market_equity, gross_financial_debt, cost_equity,
                    pretax_cost_debt, tax_rate):
    """Use financing weights E/(E+D), D/(E+D); cash is outside this denominator."""
    equity, debt, ke, kd, tax = map(
        d, (market_equity, gross_financial_debt, cost_equity, pretax_cost_debt, tax_rate))
    if equity <= 0 or debt < 0 or ke < 0 or kd < 0 or not 0 <= tax <= 1:
        raise ValueError("Require E > 0, gross D >= 0, nonnegative costs and 0 <= tax <= 1")
    ew = equity / (equity + debt)
    dw = debt / (equity + debt)
    return {"equity_weight": ew, "debt_weight": dw,
            "wacc": ke * ew + kd * (1 - tax) * dw}


def terminal_fcff(next_nopat, growth, roic, wacc):
    """Value at the explicit forecast's end, with next-year NOPAT input."""
    nopat, growth, roic, wacc = map(d, (next_nopat, growth, roic, wacc))
    if not (0 <= growth < wacc and roic > growth and nopat >= 0):
        raise ValueError("Require 0 <= g < WACC, ROIC > g, NOPAT >= 0")
    reinvestment = nopat * growth / roic
    fcff = nopat - reinvestment
    return {"reinvestment": reinvestment, "fcff": fcff,
            "terminal_ev": fcff / (wacc - growth)}


def equity_value(fcff, terminal_ev, rate, current_net_debt, shares,
                 current_nonoperating_assets=0, realization_cashflows=None):
    """FCFF enterprise PV minus current net debt; future assets discounted once."""
    fcff = list(fcff)
    if not fcff or d(shares) <= 0:
        raise ValueError("Require explicit cash flows and positive shares")
    if realization_cashflows is None:
        realization_cashflows = [0] * len(fcff)
    if len(realization_cashflows) != len(fcff):
        raise ValueError("Future asset realization dates must align with cash flows")
    with localcontext() as ctx:
        ctx.prec = 40
        enterprise = pv(fcff, rate) + d(terminal_ev) / (1 + d(rate)) ** len(fcff)
        nonoperating = d(current_nonoperating_assets) + pv(realization_cashflows, rate)
        equity = enterprise - d(current_net_debt) + nonoperating
        return {"enterprise_pv": enterprise, "nonoperating_pv": nonoperating,
                "equity_pv": equity, "per_share": equity / d(shares)}


def expected_wealth(outcomes, probabilities):
    wealth = [d(x) for x in outcomes]
    weights = [d(x) for x in probabilities]
    if len(wealth) != len(weights) or not weights:
        raise ValueError("Align outcomes and probabilities")
    if any(x < 0 for x in weights) or abs(sum(weights) - 1) > Decimal("1e-12"):
        raise ValueError("Probabilities must be nonnegative and sum to one")
    return sum((w * x for x, w in zip(wealth, weights)), Decimal(0))


def validate_policy(model):
    """Reject method contradictions, not unfavorable research conclusions."""
    errors = []
    basis = model.get("cashflow_basis")
    if basis == "FCFF":
        if model.get("discount_rate_type") != "WACC":
            errors.append("FCFF requires WACC")
        if model.get("interest_deducted_in_cashflow", False):
            errors.append("Interest must not be deducted inside FCFF")
    elif basis == "FCFE":
        if model.get("discount_rate_type") != "cost_of_equity":
            errors.append("FCFE requires cost_of_equity")
        if model.get("financing_principal_deducted_twice", False):
            errors.append("Financing principal is deducted twice")
    else:
        errors.append("Choose FCFF or FCFE")
    if model.get("sbc_treatment") not in {"expense", "dilution"}:
        errors.append("Choose one recurring SBC treatment")
    if model.get("sbc_treatment") == "expense" and model.get("same_future_sbc_dilution", False):
        errors.append("Recurring future SBC is double counted")
    if model.get("distribution_policy") not in {"distribute", "retain", "reinvest"}:
        errors.append("Choose one distribution policy")
    if model.get("distribute_and_retain_same_cash", False):
        errors.append("The same cash is both distributed and retained")
    if model.get("blanket_haircut_in_expected_value", False):
        errors.append("Keep blanket cash haircuts separate from expected value")
    if model.get("hurdle_labelled_fair_value", False):
        errors.append("Required-return entry price is not fair value")
    if model.get("inverse_labelled_consensus_without_source", False):
        errors.append("A reverse solution is not sourced consensus")
    if model.get("wacc_debt_weight_basis") not in (None, "gross_financial_debt"):
        errors.append("WACC weights require nonnegative gross financial debt, not net debt")
    if model.get("complete_three_statement_claimed", False):
        required = {"balance_sheet", "cash_continuity", "net_income_link",
                    "retained_earnings", "contributed_equity", "capital_assets",
                    "debt_leases", "working_capital_tax", "all_scenarios"}
        evidence = model.get("three_statement_checks", {})
        for key in sorted(required):
            if evidence.get(key) != "passed":
                errors.append(f"Complete three-statement claim lacks passed {key} evidence")
        if not model.get("every_forecast_period_checked", False):
            errors.append("Complete three-statement claim requires every forecast period")
    if model.get("terminal_nopat_growth") is not None and model.get("terminal_fcff_drop_ratio") is not None:
        if (d(model["terminal_nopat_growth"]) >= 0
                and d(model["terminal_fcff_drop_ratio"]) > Decimal(".10")
                and not model.get("terminal_cliff_justified", False)):
            errors.append("Terminal FCFF cliff requires a fade or explicit economic justification")
    if model.get("reverse_bull_probability") is not None:
        base = d(model.get("fixed_base_probability", 0))
        bull = d(model["reverse_bull_probability"])
        if not (0 <= base <= 1 and 0 <= bull <= 1 - base):
            errors.append("Reverse probability solution is infeasible")
    ratio = model.get("central_fair_value_to_price")
    if ratio is not None and (d(ratio) < Decimal(".5") or d(ratio) > 2):
        for field in ("gap_attribution_complete", "strongest_market_case_complete",
                      "reverse_dcf_complete"):
            if not model.get(field, False):
                errors.append(f"Large model-market gap requires {field}")
    return errors


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 valuation_core.py <model-policy.json>")
    with open(sys.argv[1], encoding="utf-8") as handle:
        issues = validate_policy(json.load(handle))
    print(json.dumps({"policy_version": POLICY_VERSION, "pass": not issues,
                      "issues": issues}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(issues))
