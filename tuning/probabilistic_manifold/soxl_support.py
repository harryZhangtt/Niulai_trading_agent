"""Frozen, provider-free SOXL descriptive support geometry.

This module reads only explicitly identity-bound adjusted-price files. It has no
outcome, protected-data, report, scheduler, provider, or write capability.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from .core import (
    DataContractError, FeaturePanelRow, PriceSeries, calibration_k_distances,
    canonical_json_bytes, classify_geometry, dependence_adjusted_ess,
    fit_robust_scaler, is_stale, load_bound_price_series, nearest_neighbors,
    nonoverlap_episode_count, open_root_anchor, select_support_training_rows,
    validate_relative_path,
)

SCHEMA = "soxl-descriptive-support-config-v1"
SYMBOLS = ("SOXL", "SOXX", "SMH", "SPY", "TLT", "HYG")
REQUIRED = ("SOXL", "SOXX")
DISTANCE_FEATURES = (
    "soxl_return_21", "soxl_return_63", "soxl_return_126",
    "soxl_distance_from_126_high", "soxl_realized_vol_21",
    "soxl_downside_semivariance_63", "soxx_return_21", "soxx_return_63",
    "soxx_return_126", "soxl_vs_3x_soxx_gap_21",
)
DIAGNOSTICS = ("smh_return_21", "spy_return_21", "tlt_return_21", "hyg_return_21")
FORBIDDEN_OUTPUTS = (
    "outcomes", "rolling_outcomes", "labels", "future_returns", "probability",
    "forecast", "confidence", "position", "recommendation", "action",
)
PRICE_FIELD = "chart.result[0].indicators.adjclose[0].adjclose"
METHOD_CONTRACT_SPEC = {
    "contract_id": "leveraged-price-path-support-v1",
    "version": 1,
    "design_scope": "shared_generic_design_specification_not_proven_soxl_tqqq_predictive_parity_or_soxl_validation",
    "formula_constants": {"return_windows_sessions": [21, 63, 126], "annualization_sessions": 252, "high_window_sessions": 126, "realized_volatility_window_sessions": 21, "downside_semivariance_window_sessions": 63, "benchmark_gap_window_sessions": 21, "benchmark_compounding_multiple": 3},
    "formula_definitions": {"simple_return": "price_t / price_t_minus_window - 1", "realized_volatility": "sqrt(252 * mean((log_return - mean_log_return)^2))", "distance_from_126_high": "price_t / max(price_t_minus_125_through_t) - 1", "downside_semivariance": "252 * mean(min(log_return, 0)^2)", "soxl_vs_3x_soxx_gap_21": "soxl_return_21 - ((1 + soxx_return_21)^3 - 1)"},
    "claim_limit": "This is a shared generic design specification, not evidence of SOXL/TQQQ predictive parity, SOXL validation, probability calibration, or outcome support.",
}

DESIGN_PARAMETER_PROVENANCE = {
    "method_family": "generic_support_v1",
    "reuse_status": "shared_method_design_constants_not_independently_validated_for_soxl",
    "shared_constants": {"k": 12, "calibration_stride": 21, "q95": 0.95, "q99": 0.99, "minimum_training_rows": 252, "minimum_nonoverlap_episodes": 3, "minimum_dependence_adjusted_ess": 2.5, "maximum_staleness_calendar_days": 7, "horizon_sessions": 126, "purge_sessions": 126},
    "target_derived_quantities": ["soxl_training_loo_k_distance_q95", "soxl_training_loo_k_distance_q99"],
    "transport_rule": "Fitted SOXL q95/q99 distances are target-derived from SOXL training rows and are not transported from TQQQ or another asset.",
    "claim_limit": "Reuse of generic support-v1 design constants is not independent SOXL validation and makes no predictive, outcome, probability, or action claim.",
}
ALLOWED_STATUS = {"inside", "edge", "outside", "inconclusive"}


def _keys(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != expected:
        actual = set(value) if type(value) is dict else set()
        raise DataContractError(f"{label} keys mismatch: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
    return value


def _date(value: Any, label: str) -> dt.date:
    if type(value) is not str:
        raise DataContractError(f"{label} must be ISO date")
    try:
        result = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise DataContractError(f"{label} must be ISO date") from exc
    if result.isoformat() != value:
        raise DataContractError(f"{label} must be canonical ISO date")
    return result


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise DataContractError(f"{label} must be integer >= {minimum}")
    return value


def _number(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise DataContractError(f"{label} must be finite number")
    return float(value)


def load_soxl_config(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataContractError("SOXL configuration is unreadable JSON") from exc
    config = dict(_keys(raw, {"schema_version", "origin_date", "price_basis", "sources", "distance_features", "informational_diagnostics", "geometry", "method_contract", "design_parameter_provenance", "integration", "forbidden_outputs"}, "config"))
    if config["schema_version"] != SCHEMA or config["origin_date"] != "2026-11-05":
        raise DataContractError("frozen schema or origin mismatch")
    basis = _keys(config["price_basis"], {"field", "label"}, "price_basis")
    if basis != {"field": PRICE_FIELD, "label": "adjusted_market_price"}:
        raise DataContractError("adjusted market price basis mismatch")
    sources = _keys(config["sources"], set(SYMBOLS), "sources")
    for symbol in SYMBOLS:
        spec = _keys(sources[symbol], {"symbol", "required", "path", "sha256", "bytes", "rows", "expected_start", "expected_end"}, f"sources.{symbol}")
        if spec["symbol"] != symbol or type(spec["required"]) is not bool or spec["required"] != (symbol in REQUIRED):
            raise DataContractError(f"sources.{symbol} identity/required mismatch")
        validate_relative_path(spec["path"], f"sources.{symbol}.path")
        if type(spec["sha256"]) is not str or len(spec["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in spec["sha256"]):
            raise DataContractError(f"sources.{symbol}.sha256 invalid")
        _integer(spec["bytes"], f"sources.{symbol}.bytes", 1)
        _integer(spec["rows"], f"sources.{symbol}.rows", 1)
        if _date(spec["expected_end"], f"sources.{symbol}.expected_end") < _date(spec["expected_start"], f"sources.{symbol}.expected_start"):
            raise DataContractError(f"sources.{symbol} date range invalid")
    if tuple(config["distance_features"]) != DISTANCE_FEATURES or tuple(config["informational_diagnostics"]) != DIAGNOSTICS:
        raise DataContractError("frozen feature lists mismatch")
    if tuple(config["forbidden_outputs"]) != FORBIDDEN_OUTPUTS:
        raise DataContractError("frozen forbidden outputs mismatch")
    g = _keys(config["geometry"], {"horizon_sessions", "purge_sessions", "calibration_stride", "metric", "k", "q95", "q99", "minimum_training_rows", "minimum_nonoverlap_episodes", "minimum_dependence_adjusted_ess", "maximum_staleness_calendar_days", "scaler"}, "geometry")
    exact = {"horizon_sessions":126, "purge_sessions":126, "calibration_stride":21, "metric":"euclidean", "k":12, "q95":0.95, "q99":0.99, "minimum_training_rows":252, "minimum_nonoverlap_episodes":3, "minimum_dependence_adjusted_ess":2.5, "maximum_staleness_calendar_days":7, "scaler":"training_only_median_mad"}
    if g != exact:
        raise DataContractError("frozen geometry mismatch")
    method = _keys(config["method_contract"], set(METHOD_CONTRACT_SPEC) | {"code_sha256"}, "method_contract")
    _keys(method["formula_constants"], set(METHOD_CONTRACT_SPEC["formula_constants"]), "method_contract.formula_constants")
    _keys(method["formula_definitions"], set(METHOD_CONTRACT_SPEC["formula_definitions"]), "method_contract.formula_definitions")
    code_hashes = _keys(method["code_sha256"], {"core.py", "soxl_support.py"}, "method_contract.code_sha256")
    if {key: method[key] for key in METHOD_CONTRACT_SPEC} != METHOD_CONTRACT_SPEC:
        raise DataContractError("frozen method contract mismatch")
    for name, digest in code_hashes.items():
        if type(digest) is not str or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise DataContractError(f"method_contract.code_sha256.{name} invalid")
        observed = hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        if observed != digest:
            raise DataContractError(f"method contract code hash mismatch for {name}")
    provenance = _keys(config["design_parameter_provenance"], set(DESIGN_PARAMETER_PROVENANCE), "design_parameter_provenance")
    _keys(provenance["shared_constants"], set(DESIGN_PARAMETER_PROVENANCE["shared_constants"]), "design_parameter_provenance.shared_constants")
    if provenance != DESIGN_PARAMETER_PROVENANCE:
        raise DataContractError("frozen design parameter provenance mismatch")
    integration = _keys(config["integration"], {"policy_scope", "probability_feature_compatible"}, "integration")
    if integration != {"policy_scope":"descriptive_training_cloud_v1", "probability_feature_compatible":False}:
        raise DataContractError("frozen integration mismatch")
    return config


def build_preregistration(config: Mapping[str, Any], config_bytes: bytes) -> dict[str, Any]:
    return {
        "schema_version": "soxl-descriptive-support-preregistration-v1",
        "origin_date": config["origin_date"],
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "price_basis": config["price_basis"],
        "sources": config["sources"],
        "distance_features": config["distance_features"],
        "informational_diagnostics": config["informational_diagnostics"],
        "geometry": config["geometry"],
        "method_contract": config["method_contract"],
        "design_parameter_provenance": config["design_parameter_provenance"],
        "forbidden_outputs": config["forbidden_outputs"],
        "packet_cardinality": "one_origin_only_no_cohort",
        "outcomes_accessed": False,
        "protected_outcomes_accessed": False,
        "probability_feature_compatible": False,
    }


def _ret(prices: Sequence[float], i: int, sessions: int) -> float | None:
    return None if i < sessions else prices[i] / prices[i-sessions] - 1.0


def _logs(prices: Sequence[float], i: int, sessions: int) -> list[float] | None:
    if i < sessions:
        return None
    return [math.log(prices[j] / prices[j-1]) for j in range(i-sessions+1, i+1)]


def build_soxl_feature_panel(series: Mapping[str, PriceSeries], origin_date: dt.date) -> list[FeaturePanelRow]:
    primary = series["SOXL"]
    if origin_date not in primary.by_date():
        raise DataContractError("required origin date is missing from SOXL")
    soxx = series["SOXX"].by_date()
    dates = [d for d in primary.dates if d <= origin_date]
    if any(d not in soxx for d in dates):
        raise DataContractError("SOXX is missing an exact SOXL date; no forward fill allowed")
    p = [primary.by_date()[d] for d in dates]
    q = [soxx[d] for d in dates]
    optional = {s: item.by_date() for s, item in series.items() if s not in REQUIRED}
    rows: list[FeaturePanelRow] = []
    for i, date in enumerate(dates):
        p21, q21 = _ret(p, i, 21), _ret(q, i, 21)
        logs21, logs63 = _logs(p, i, 21), _logs(p, i, 63)
        vol = None
        if logs21 is not None:
            center = sum(logs21)/len(logs21)
            vol = math.sqrt(252.0*sum((x-center)**2 for x in logs21)/len(logs21))
        semivar = None if logs63 is None else 252.0*sum(min(x, 0.0)**2 for x in logs63)/len(logs63)
        f: dict[str, float | None] = {
            "soxl_return_21": p21, "soxl_return_63": _ret(p,i,63), "soxl_return_126": _ret(p,i,126),
            "soxl_distance_from_126_high": None if i < 125 else p[i]/max(p[i-125:i+1])-1.0,
            "soxl_realized_vol_21": vol, "soxl_downside_semivariance_63": semivar,
            "soxx_return_21": q21, "soxx_return_63": _ret(q,i,63), "soxx_return_126": _ret(q,i,126),
            "soxl_vs_3x_soxx_gap_21": None if p21 is None or q21 is None else p21-((1.0+q21)**3-1.0),
        }
        for symbol in ("SMH","SPY","TLT","HYG"):
            m = optional.get(symbol, {})
            prior = dates[i-21] if i >= 21 else None
            f[f"{symbol.lower()}_return_21"] = None if prior is None or date not in m or prior not in m else m[date]/m[prior]-1.0
        era = "pre_covid" if date < dt.date(2020,2,19) else "covid_recovery" if date < dt.date(2022,1,1) else "tightening_bear" if date < dt.date(2023,1,1) else "recent"
        rows.append(FeaturePanelRow(date, p[i], era, f))
    return rows


def _quantile(values: Sequence[float], p: float) -> float:
    ordered=sorted(values)
    if not ordered: raise DataContractError("empty calibration support")
    x=(len(ordered)-1)*p; lo=math.floor(x); hi=math.ceil(x)
    return ordered[lo] if lo==hi else ordered[lo]+(ordered[hi]-ordered[lo])*(x-lo)


def _manifest(config: Mapping[str, Any], loaded: Mapping[str, PriceSeries], failures: Mapping[str, str]) -> dict[str, Any]:
    rows=[]
    for symbol in SYMBOLS:
        spec=config["sources"][symbol]; item=loaded.get(symbol)
        rows.append({"symbol":symbol,"required":spec["required"],"path":spec["path"],"sha256":spec["sha256"],"bytes":spec["bytes"],"expected_rows":spec["rows"],"expected_start":spec["expected_start"],"expected_end":spec["expected_end"],"identity_status":"passed" if item else "failed","observed_rows":len(item.dates) if item else None,"failure":failures.get(symbol)})
    return {"schema_version":"soxl-descriptive-support-source-manifest-v1","price_basis":config["price_basis"],"method_contract":config["method_contract"],"sources":rows}


def _base_packet(config: Mapping[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {"schema_version":"soxl-descriptive-support-packet-v1","status":"inconclusive","status_reasons":reasons,"origin_id":"origin_2026-11-05","policy_scope":"descriptive_training_cloud_v1","probability_feature_compatible":False,"method_contract":config["method_contract"],"design_parameter_provenance":config["design_parameter_provenance"],"claim_scope":"descriptive historical training-cloud geometry only","origin":{"date":"2026-11-05","adjusted_market_price":None,"features":None},"support_geometry":{"status":"inconclusive","status_reasons":list(reasons),"training":{"rows":0,"date_start":None,"date_end":None,"robust_scaler":{}},"knn":{"k":12,"metric":"euclidean_after_training_only_median_mad","neighbors":[],"training_loo_k_distance_thresholds":{},"calibration_rows":0,"nonoverlap_episode_count_126":0,"dependence_adjusted_ess_overlap_kernel":0.0}},"panel":{"rows":0,"date_start":None,"date_end":None},"outcomes_accessed":False,"protected_outcomes_accessed":False}


def run_soxl_support(config_path: Path, source_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    config=load_soxl_config(config_path)
    prereg=build_preregistration(config, config_path.read_bytes())
    loaded: dict[str,PriceSeries]={}; failures: dict[str,str]={}
    with open_root_anchor(source_root,"source root") as anchor:
        for symbol in SYMBOLS:
            try:
                item=load_bound_price_series(source_root,symbol,config["sources"][symbol],root_anchor=anchor)
                if len(item.dates)!=config["sources"][symbol]["rows"]: raise DataContractError(f"row-count mismatch for {symbol}")
                loaded[symbol]=item
            except DataContractError as exc:
                failures[symbol]=str(exc)
    manifest=_manifest(config,loaded,failures)
    required_failures=[s for s in REQUIRED if s not in loaded]
    if required_failures:
        return _base_packet(config,["required_source_identity_failed"]),manifest,prereg
    try:
        panel=build_soxl_feature_panel(loaded,dt.date(2026,11,5))
    except DataContractError as exc:
        return _base_packet(config,["required_feature_identity_failed"]),manifest,prereg
    origin_index=len(panel)-1; origin=panel[origin_index]; reasons=[]
    if origin.date != dt.date(2026,11,5): reasons.append("origin_identity_failed")
    if is_stale(dt.date(2026,11,5),origin.date,7): reasons.append("origin_is_stale")
    if any(origin.features.get(n) is None for n in DISTANCE_FEATURES): reasons.append("origin_missing_required_feature")
    training=select_support_training_rows(panel,origin_index,DISTANCE_FEATURES,126)
    if len(training)<252: reasons.append("insufficient_training_support")
    packet=_base_packet(config,reasons)
    packet["origin"]={"date":origin.date.isoformat(),"adjusted_market_price":origin.adjusted_market_price,"features":dict(origin.features)}
    packet["panel"]={"rows":len(panel),"date_start":panel[0].date.isoformat(),"date_end":panel[-1].date.isoformat()}
    geometry=packet["support_geometry"]; geometry["training"].update({"rows":len(training),"date_start":training[0].date.isoformat() if training else None,"date_end":training[-1].date.isoformat() if training else None})
    if not reasons:
        try:
            scaler=fit_robust_scaler(training,DISTANCE_FEATURES)
            neighbors=nearest_neighbors(training,origin,scaler,DISTANCE_FEATURES,12)
            calibration=calibration_k_distances(training,scaler,DISTANCE_FEATURES,12,21)
            q95,q99=_quantile(calibration,.95),_quantile(calibration,.99)
            dates=[dt.date.fromisoformat(n["date"]) for n in neighbors]
            episodes=nonoverlap_episode_count(dates,[r.date for r in panel],126)
            ess=dependence_adjusted_ess(dates,[r.date for r in panel],126)
            status=classify_geometry(neighbors[-1]["distance"],q95,q99)
            if episodes<3: reasons.append("insufficient_nonoverlap_episodes")
            if ess<2.5: reasons.append("insufficient_dependence_adjusted_ess")
            if reasons: status="inconclusive"
            geometry["status"]=status; geometry["status_reasons"]=list(reasons)
            geometry["training"]["robust_scaler"]={n:{"median":scaler.medians[n],"mad":scaler.mads[n],"scale_1_4826_mad":scaler.scales[n]} for n in DISTANCE_FEATURES}
            geometry["knn"].update({"neighbors":neighbors,"training_loo_k_distance_thresholds":{"q95":q95,"q99":q99},"calibration_rows":len(calibration),"query_k_distance":neighbors[-1]["distance"],"nonoverlap_episode_count_126":episodes,"dependence_adjusted_ess_overlap_kernel":ess})
        except DataContractError as exc:
            reasons.append("zero_mad_or_calibration_support_failure")
            geometry["status_reasons"]=list(reasons)
    packet["status"]="inconclusive" if reasons or not config["integration"]["probability_feature_compatible"] else geometry["status"]
    packet["status_reasons"]=list(reasons)+["probability_feature_compatible_false"]
    if geometry["status"] not in ALLOWED_STATUS: raise AssertionError("invalid geometry status")
    return packet,manifest,prereg
