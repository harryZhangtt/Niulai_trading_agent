"""Strict pre-outcome admission policy for the first factor-mining candidate.

This contract freezes scientific choices that are knowable now while refusing to
pretend unresolved point-in-time inventory identities or split dates exist.  It
does not seal a guard protocol, inspect outcomes, run factors, or authorize use.
"""
import hashlib
import json
import math
from pathlib import Path


MAX_POLICY_BYTES = 256 * 1024
POLICY_ID = "joint-easing-overlay-v1"
ASSETS = ["SPY", "ONEQ"]
BLOCKERS = [
    "canonical-ledger-authority-unimplemented",
    "trusted-dataset-split-attestation-unimplemented",
    "guard-issued-runner-nonce-and-trusted-receipt-unimplemented",
    "evaluator-derived-verdict-and-independent-receipt-unimplemented",
    "authorization-bound-performance-publication-unimplemented",
    "outcome-exposure-cutoff-unresolved",
    "source-authority-and-license-unresolved",
    "point-in-time-availability-unverified",
    "observation-and-feature-identities-unresolved",
    "evaluation-population-unresolved",
    "chronological-splits-unresolved",
    "fresh-coverage-and-label-maturity-unverified",
    "cost-model-validity-unverified",
]
SENSITIVITIES = [
    {"id": "lag-3", "lag_sessions": 3, "cost_bps_one_way": 5, "role": "robustness"},
    {"id": "cost-10", "lag_sessions": 1, "cost_bps_one_way": 10, "role": "robustness"},
    {"id": "lag-3-cost-10", "lag_sessions": 3, "cost_bps_one_way": 10, "role": "required-pass-stress"},
    {"id": "lookback-42", "lookback_sessions": 42, "role": "sensitivity"},
    {"id": "lookback-84", "lookback_sessions": 84, "role": "sensitivity"},
    {"id": "credit-only", "component": "credit", "role": "descriptive-ablation"},
    {"id": "real-rate-only", "component": "real-rate", "role": "descriptive-ablation"},
    {"id": "exposure-normalized-baseline", "role": "descriptive-baseline-sensitivity"},
]
CONTROLS = [
    {"id": "adverse-conjunction", "kind": "directional", "can_promote": False},
    {"id": "signal-shift-12m", "kind": "event-time-placebo", "shift_months": 12, "can_promote": False},
    {"id": "label-block-permutation", "kind": "procedural", "replicates": 1000, "block_sessions": 126, "can_promote": False},
    {"id": "availability-plus-1-session", "kind": "timing-audit", "shift_sessions": 1, "can_promote": False},
]
TRIGGERS = [
    {"id": "protected-access-before-seal-count", "operator": "gt", "threshold": 0},
    {"id": "availability-timestamp-missing-rate", "operator": "gt", "threshold": 0},
    {"id": "future-or-same-bar-input-count", "operator": "gt", "threshold": 0},
    {"id": "split-label-overlap-count", "operator": "gt", "threshold": 0},
    {"id": "purge-embargo-violation-count", "operator": "gt", "threshold": 0},
    {"id": "row-alignment-mismatch-count", "operator": "gt", "threshold": 0},
    {"id": "float-roundtrip-decision-flip-count", "operator": "gt", "threshold": 0},
    {"id": "undeclared-exclusion-count", "operator": "gt", "threshold": 0},
    {"id": "holdout-reuse-count", "operator": "gt", "threshold": 0},
    {"id": "unauthorized-variant-count", "operator": "gt", "threshold": 0},
    {"id": "sensitivity-sign-flip-rate", "operator": "gt", "threshold": 0.25},
    {"id": "single-block-positive-contribution-share", "operator": "gt", "threshold": 0.5},
    {"id": "placebo-pass-count", "operator": "gt", "threshold": 0},
]


class PolicyError(ValueError):
    """Stable, sanitized admission-policy rejection."""


def require(condition, code):
    if not condition:
        raise PolicyError(code)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "FACTOR_POLICY_DUPLICATE_KEY")
        value[key] = item
    return value


def _invalid_constant(_value):
    raise PolicyError("FACTOR_POLICY_NONFINITE")


def loads_strict(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except PolicyError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise PolicyError("FACTOR_POLICY_JSON_INVALID") from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError):
        raise PolicyError("FACTOR_POLICY_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _strict(value, keys, code):
    require(isinstance(value, dict) and set(value) == set(keys), code)
    return value


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _same_typed(value, expected):
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (set(value) == set(expected) and
                all(_same_typed(value[key], expected[key]) for key in expected))
    if isinstance(expected, list):
        return (len(value) == len(expected) and
                all(_same_typed(item, expected_item)
                    for item, expected_item in zip(value, expected)))
    return value == expected


def _exact(value, expected, code):
    require(_same_typed(value, expected), code)


def validate_policy(policy):
    """Validate the frozen draft without resolving or reading outcome data."""
    _strict(policy, {
        "schema_version", "kind", "policy_id", "version", "status", "claim",
        "universe", "signal", "portfolio", "baseline", "execution", "evaluation",
        "multiplicity", "budget", "decision", "sensitivities", "controls",
        "quarantine_triggers", "stopping", "inventory", "publication",
    }, "FACTOR_POLICY_SCHEMA")
    _exact(policy["schema_version"], 1, "FACTOR_POLICY_VERSION")
    _exact(policy["kind"], "factor_admission_policy", "FACTOR_POLICY_KIND")
    _exact(policy["policy_id"], POLICY_ID, "FACTOR_POLICY_ID")
    _exact(policy["version"], 1, "FACTOR_POLICY_VERSION")
    _exact(policy["status"], "draft_blocked", "FACTOR_POLICY_STATUS")

    claim = _strict(policy["claim"], {"type", "hypothesis", "mechanism", "contradiction"},
                    "FACTOR_POLICY_CLAIM")
    _exact(claim["type"], "predictive-economic-association", "FACTOR_POLICY_CLAIM")
    for key in ("hypothesis", "mechanism", "contradiction"):
        require(isinstance(claim[key], str) and 20 <= len(claim[key]) <= 4000,
                "FACTOR_POLICY_CLAIM")

    universe = _strict(policy["universe"], {"assets", "substitution_allowed", "decision_unit"},
                       "FACTOR_POLICY_UNIVERSE")
    _exact(universe["assets"], ASSETS, "FACTOR_POLICY_UNIVERSE")
    _exact(universe["substitution_allowed"], False, "FACTOR_POLICY_UNIVERSE")
    _exact(universe["decision_unit"], "etf-month-end-origin", "FACTOR_POLICY_UNIVERSE")

    signal = _strict(policy["signal"], {
        "id", "family", "real_rate_series", "credit_series", "lookback_sessions",
        "formula", "equality_active", "learned_weights", "max_degrees_of_freedom",
        "point_in_time_required",
    }, "FACTOR_POLICY_SIGNAL")
    _exact(signal, {
        "id": "joint-real-credit-easing-63",
        "family": "macro-financial-conditions",
        "real_rate_series": "DFII5",
        "credit_series": "BAMLC0A0CM",
        "lookback_sessions": 63,
        "formula": "real-rate-63d-change<0-and-credit-oas-63d-change<0",
        "equality_active": False,
        "learned_weights": False,
        "max_degrees_of_freedom": 1,
        "point_in_time_required": True,
    }, "FACTOR_POLICY_SIGNAL")

    _exact(policy["portfolio"], {
        "mapping": "long-cash-overlay",
        "rv_window_sessions": 20,
        "annualized_volatility_target": 0.10,
        "exposure_cap": 1.0,
        "leverage_allowed": False,
        "shorting_allowed": False,
        "inactive_exposure": 0.0,
    }, "FACTOR_POLICY_PORTFOLIO")
    _exact(policy["baseline"], {
        "id": "development-frequency-matched-rv20",
        "formula": "development-signal-incidence-by-asset-times-rv20-scaler",
        "uses_target_returns": False,
        "frozen_before_validation": True,
        "shared_execution_and_cost_policy": True,
    }, "FACTOR_POLICY_BASELINE")
    _exact(policy["execution"], {
        "origin": "last-regular-xnys-session-of-month",
        "information_cutoff": "16:00-America/New_York",
        "trade_at": "next-regular-session-close",
        "signal_lag_sessions": 1,
        "rebalance": "monthly",
        "cost_bps_one_way": 5,
        "cash_series": "DFF",
        "cash_point_in_time_required": True,
        "same_bar_execution_allowed": False,
    }, "FACTOR_POLICY_EXECUTION")
    _exact(policy["evaluation"], {
        "primary_metric": "annualized-net-log-growth-difference",
        "metric_unit": "annual-percentage-points",
        "target": "126-session-forward-total-return-log-minus-realizable-cash",
        "horizon_sessions": 126,
        "purge_sessions": 126,
        "embargo_sessions": 21,
        "uncertainty": {
            "method": "paired-stationary-block-bootstrap",
            "block_sessions": 126,
            "replicates": 20000,
            "confidence_level": 0.95,
            "seed": "first-64-bits-of-sealed-protocol-sha256",
        },
        "required_reporting_units": ["daily-observations", "monthly-origins", "nonoverlapping-126-session-blocks"],
    }, "FACTOR_POLICY_EVALUATION")
    _exact(policy["multiplicity"], {
        "family_id": "joint-easing-entry-2026-v1",
        "members": ["SPY-protected-delta-g", "ONEQ-protected-delta-g"],
        "method": "holm-one-sided-fwer",
        "alpha": 0.05,
        "simultaneous_lower_bounds_required": True,
    }, "FACTOR_POLICY_MULTIPLICITY")
    _exact(policy["budget"], {
        "candidate_specifications": 1,
        "confirmatory_variants": 1,
        "protocol_versions_after_outcome_access": 0,
        "pipeline_attempts": 1,
        "protected_uses": 1,
        "protected_looks": 1,
        "post_seal_formula_changes": 0,
    }, "FACTOR_POLICY_BUDGET")

    decision = _strict(policy["decision"], {"pass", "fail", "inconclusive"},
                       "FACTOR_POLICY_DECISION")
    _exact(decision["pass"], {
        "required_assets": ASSETS,
        "protected_origins_per_asset": 36,
        "minimum_effective_blocks": 6,
        "point_estimate_gt": 0.0,
        "holm_adjusted_one_sided_p_lt": 0.05,
        "simultaneous_lower_bound_gt": 0.0,
        "combined_stress_point_gt": 0.0,
        "validation_guardrail_annual_pp_ge": -1.0,
        "favorable_exceeds_adverse": True,
        "all_controls_complete": True,
        "no_quarantine_trigger": True,
    }, "FACTOR_POLICY_PASS_RULE")
    _exact(decision["fail"], {
        "simultaneous_upper_bound_le": 0.0,
        "combined_stress_annual_pp_le": -1.0,
        "mechanism_contradiction_is_failure": True,
    }, "FACTOR_POLICY_FAIL_RULE")
    _exact(decision["inconclusive"], {
        "default_nonpass_nonfail": True,
        "consumes_protected_use": True,
        "retry_same_population_allowed": False,
        "reasons": [
            "interval-crosses-zero", "adjusted-p-misses-alpha", "insufficient-effective-information",
            "required-data-missing", "uncertainty-invalid", "fresh-chronological-coverage-unavailable",
        ],
    }, "FACTOR_POLICY_INCONCLUSIVE_RULE")

    _exact(policy["sensitivities"], SENSITIVITIES, "FACTOR_POLICY_SENSITIVITIES")
    _exact(policy["controls"], CONTROLS, "FACTOR_POLICY_CONTROLS")
    triggers = policy["quarantine_triggers"]
    _exact(triggers, TRIGGERS, "FACTOR_POLICY_TRIGGERS")
    require(len({item["id"] for item in triggers}) == len(triggers), "FACTOR_POLICY_TRIGGERS")
    _exact(policy["stopping"], {
        "rule": "one-seal-one-fixed-analysis-one-terminal-protected-read",
        "terminal_verdicts": ["pass", "fail", "inconclusive", "quarantined"],
        "preserve_all_attempts": True,
        "outcome_dependent_changes_allowed": False,
        "fresh_protected_population_required_for_remediation": True,
    }, "FACTOR_POLICY_STOPPING")

    inventory = _strict(policy["inventory"], {
        "sealable", "blockers", "canonical_authority_policy_sha256",
        "dataset_attestation_policy_sha256", "runner_receipt_policy_sha256",
        "evaluator_receipt_policy_sha256", "publication_authorization_policy_sha256",
        "outcome_exposure_cutoff", "source_authority_receipt_sha256",
        "observation_set_sha256", "feature_snapshot_sha256", "evaluation_population_sha256",
        "builder_receipt_sha256", "split_spec_sha256", "chronological_splits",
        "coverage_assessment",
    }, "FACTOR_POLICY_INVENTORY")
    _exact(inventory["sealable"], False, "FACTOR_POLICY_BLOCKERS_REQUIRED")
    _exact(inventory["blockers"], BLOCKERS, "FACTOR_POLICY_BLOCKERS_REQUIRED")
    for key in set(inventory) - {"sealable", "blockers"}:
        _exact(inventory[key], None, "FACTOR_POLICY_UNRESOLVED_INVENTORY")

    _exact(policy["publication"], {
        "ev_allowed": False,
        "kelly_allowed": False,
        "performance_allowed": False,
        "pass_authorizes_sizing_protocol_only": True,
        "requires_current_guard_authorization": True,
    }, "FACTOR_POLICY_PUBLICATION")
    require(not any(key in policy for key in ("results", "performance", "metrics", "verdict")),
            "FACTOR_POLICY_OUTCOME_FIELD_FORBIDDEN")
    return policy


def load_policy(path):
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError:
        raise PolicyError("FACTOR_POLICY_FILE_UNAVAILABLE") from None
    require(0 < len(raw) <= MAX_POLICY_BYTES, "FACTOR_POLICY_FILE_SIZE")
    return validate_policy(loads_strict(raw))
