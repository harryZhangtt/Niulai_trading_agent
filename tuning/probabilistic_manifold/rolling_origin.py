"""Frozen rolling-origin development protocol. Metadata/preregistration only CLI."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import random
import stat
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from .core import DataContractError, _read_stable_source, _validate_trusted_stat, canonical_json_bytes, open_root_anchor, write_canonical_json

ERROR_CODES = {"CONFIG_INVALID", "DATA_CHRONOLOGY", "SPLIT_VIOLATION", "PROTECTED_ACCESS_DENIED", "NUMERIC_FAILURE", "SUPPORT_ABSTENTION", "LEDGER_CONFLICT", "UNKNOWN_WRITE"}
EXPECTED_PRICE_FIELD = "chart.result[0].indicators.adjclose[0].adjclose"
BASE_FEATURES = {"tqqq_return_21", "tqqq_return_63", "tqqq_return_126", "distance_from_126_high", "realized_volatility_21", "downside_semivariance_63", "qqq_return_126"}
MACRO_FEATURES = {"spy_return_21", "tlt_return_21", "hyg_return_21"}
TARGETS = {"return", "max_drawdown", "relative_qqq_return", "material_loss"}


class RollingError(DataContractError):
    def __init__(self, code: str, message: str):
        if code not in ERROR_CODES: raise ValueError("unknown error code")
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class RollingOrigin:
    origin_id: str
    origin_index: int
    origin_date: dt.date
    maturity_index: int
    maturity_date: dt.date
    horizon_sessions: int
    stride_sessions: int


@dataclass(frozen=True)
class RidgeModel:
    coefficients: tuple[float, ...]


@dataclass(frozen=True)
class LogisticModel:
    coefficients: tuple[float, ...]
    clip: float


def _exact(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != keys: raise RollingError("CONFIG_INVALID", f"{label} keys mismatch")
    return value


def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)): raise RollingError("CONFIG_INVALID", f"{label} must be finite")
    return float(value)


def _positive(value: Any, label: str, *, integer: bool = False) -> float:
    if integer and type(value) is not int: raise RollingError("CONFIG_INVALID", f"{label} must be integer")
    result = _finite(value, label)
    if result <= 0: raise RollingError("CONFIG_INVALID", f"{label} must be positive")
    return result


def _iso(value: Any, label: str) -> dt.date:
    if type(value) is not str: raise RollingError("CONFIG_INVALID", f"{label} must be date")
    try: result = dt.date.fromisoformat(value)
    except ValueError as exc: raise RollingError("CONFIG_INVALID", f"{label} must be date") from exc
    if result.isoformat() != value: raise RollingError("CONFIG_INVALID", f"{label} must be canonical date")
    return result


def _sha(value: Any, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value): raise RollingError("CONFIG_INVALID", f"{label} must be sha256")
    return value


def _rooted_json(root: Path, name: str) -> tuple[dict[str, Any], bytes]:
    try:
        with open_root_anchor(root, "rolling root") as anchor: payload = _read_stable_source(anchor, name)
        value = json.loads(payload)
    except (DataContractError, json.JSONDecodeError) as exc: raise RollingError("CONFIG_INVALID", "rooted JSON unreadable") from exc
    if type(value) is not dict: raise RollingError("CONFIG_INVALID", "rooted JSON must be object")
    return value, payload


def load_rolling_config(root: Path, name: str = "rolling-config.v1.json") -> dict[str, Any]:
    c, _ = _rooted_json(root, name)
    _exact(c, {"schema_version", "protocol_id", "claim_scope", "source_contract", "calendar", "price_basis", "targets", "rolling", "target_baselines", "scoring_population", "feature_families", "candidates", "variant_budget", "no_budget_reset_after_failure", "no_retuning_after_protected", "models", "calibration", "metrics", "decision_policy", "support_gate", "attempt_ledger", "evaluator", "artifacts"}, "config")
    if (c["schema_version"], c["protocol_id"], c["claim_scope"]) != ("rolling-origin-config-v1", "tqqq-rolling-origin-development-v1", "predictive_development_only_no_action"): raise RollingError("CONFIG_INVALID", "protocol identity")
    source = _exact(c["source_contract"], {"owned_source_manifest_v2_sha256", "upstream_source_manifest_sha256", "source_family_version", "retrieved_at"}, "source_contract")
    _sha(source["owned_source_manifest_v2_sha256"], "owned manifest"); _sha(source["upstream_source_manifest_sha256"], "upstream manifest")
    if source != {"owned_source_manifest_v2_sha256":"5ca62dc8cf180203b71e5e1e232d53d934285baa7242e54e72786abaa9b8436f","upstream_source_manifest_sha256":"22642370963b65b0ac242c644f6643ea780ff4ca2f23ec4e29a08548382428d3","source_family_version":"yahoo-leveraged-history-v2","retrieved_at":"2026-11-09T14:00:03.506148+00:00"}: raise RollingError("CONFIG_INVALID", "source family")
    cal = _exact(c["calendar"], {"calendar_id", "calendar_version", "timezone", "session_roster_sha256", "session_count", "session_start", "session_end", "fixed_origin_anchor_index", "fixed_origin_anchor_date", "calendar_limit"}, "calendar")
    if (cal["calendar_id"], cal["calendar_version"], cal["timezone"]) != ("XNYS", "observed-yahoo-session-roster-v1", "America/New_York"): raise RollingError("CONFIG_INVALID", "calendar identity")
    _sha(cal["session_roster_sha256"], "roster hash")
    if cal["session_roster_sha256"] != "f2b0358d1dfa9f44d34c62947eb52a6dacdaec314931b405a4390a77fdceabb8" or cal["session_count"] != 4211 or cal["session_start"] != "2010-02-11" or cal["session_end"] != "2026-11-06" or cal["fixed_origin_anchor_index"] != 126 or cal["fixed_origin_anchor_date"] != "2010-08-12": raise RollingError("CONFIG_INVALID", "calendar roster/anchor")
    _iso(cal["session_start"], "session start"); _iso(cal["session_end"], "session end")
    basis = _exact(c["price_basis"], {"field", "label", "adjustment_vintage", "point_in_time_adjustment_vintage", "limitations"}, "price_basis")
    if basis["field"] != EXPECTED_PRICE_FIELD or basis["label"] != "yahoo_adjusted_market_price" or basis["adjustment_vintage"] != "retrieved_2026-11-09T14:00:03.506148+00:00" or basis["point_in_time_adjustment_vintage"] is not False: raise RollingError("CONFIG_INVALID", "price basis")
    targets = _exact(c["targets"], {"primary_126", "secondary_252"}, "targets")
    p = _exact(targets["primary_126"], {"horizon_sessions", "return_formula", "max_drawdown_formula", "relative_qqq_formula", "material_loss_formula", "material_loss_threshold", "continuous_unit", "binary_unit"}, "primary")
    s = _exact(targets["secondary_252"], set(p) | {"status"}, "secondary")
    expected_primary={"horizon_sessions":126,"return_formula":"P_TQQQ[t+126]/P_TQQQ[t]-1","max_drawdown_formula":"min_u(P_TQQQ[u]/max_v<=u(P_TQQQ[v])-1),u=t..t+126","relative_qqq_formula":"return_TQQQ_126-return_QQQ_126","material_loss_formula":"1[max_drawdown_126<=-0.25]","material_loss_threshold":-0.25,"continuous_unit":"decimal_return","binary_unit":"zero_or_one"}
    expected_secondary={"horizon_sessions":252,"return_formula":"P_TQQQ[t+252]/P_TQQQ[t]-1","max_drawdown_formula":"min_u(P_TQQQ[u]/max_v<=u(P_TQQQ[v])-1),u=t..t+252","relative_qqq_formula":"return_TQQQ_252-return_QQQ_252","material_loss_formula":"1[max_drawdown_252<=-0.40]","material_loss_threshold":-0.40,"continuous_unit":"decimal_return","binary_unit":"zero_or_one","status":"exploratory_nonselective"}
    if p != expected_primary or s != expected_secondary: raise RollingError("CONFIG_INVALID", "target freeze")
    if any(item["continuous_unit"] != "decimal_return" or item["binary_unit"] != "zero_or_one" for item in (p, s)): raise RollingError("CONFIG_INVALID", "target units")
    rolling = _exact(c["rolling"], {"mode", "development_maturity_cutoff", "embargo_sessions", "protected_origin_start", "protected_access", "minimum_training_origins", "primary", "secondary", "diagnostic"}, "rolling")
    if rolling["mode"] != "expanding_past_only" or rolling["embargo_sessions"] != 21 or rolling["protected_access"] != "unopened" or rolling["minimum_training_origins"] != 24: raise RollingError("CONFIG_INVALID", "rolling policy")
    if (_iso(rolling["development_maturity_cutoff"], "cutoff"), _iso(rolling["protected_origin_start"], "protected")) != (dt.date(2023,12,29), dt.date(2024,2,1)): raise RollingError("CONFIG_INVALID", "split dates")
    expected_rolls = {"primary": (126,126,126,21), "secondary": (252,252,252,21), "diagnostic": (126,21,126,21)}
    for key, expected in expected_rolls.items():
        allowed = {"horizon_sessions", "stride_sessions", "purge_sessions", "embargo_sessions"} | ({"status"} if key=="secondary" else {"status", "selection_allowed"} if key=="diagnostic" else set())
        item = _exact(rolling[key], allowed, key)
        if tuple(item[x] for x in ("horizon_sessions","stride_sessions","purge_sessions","embargo_sessions")) != expected: raise RollingError("CONFIG_INVALID", f"{key} rolling freeze")
    if rolling["secondary"]["status"] != "exploratory_nonselective" or rolling["diagnostic"] != {"horizon_sessions":126,"stride_sessions":21,"purge_sessions":126,"embargo_sessions":21,"status":"diagnostic_nonselective","selection_allowed":False}: raise RollingError("CONFIG_INVALID", "nonselective freeze")
    baselines = _exact(c["target_baselines"], TARGETS, "baselines")
    expected_baselines={"return":["unconditional_mean","trend_volatility","qqq_3x_proxy","cash_zero"],"max_drawdown":["unconditional_mean","trend_volatility","qqq_drawdown_3x_proxy","cash_zero"],"relative_qqq_return":["unconditional_mean","trend_volatility","qqq_gap_proxy","cash_zero"],"material_loss":["unconditional_training_prevalence","trend_volatility_logistic","qqq_loss_prevalence_proxy","cash_no_loss_probability"]}
    if baselines != expected_baselines or c["scoring_population"] != "same_retained_origin_ids_for_candidate_and_all_target_baselines": raise RollingError("CONFIG_INVALID", "baseline matching")
    families = _exact(c["feature_families"], {"price_path_base","macro_optional"}, "families")
    if set(families["price_path_base"]) != BASE_FEATURES or set(families["macro_optional"]) != MACRO_FEATURES: raise RollingError("CONFIG_INVALID", "feature families")
    expected_candidates = [{"id":"price_path_base","feature_families":["price_path_base"],"models":["ridge","logistic"]},{"id":"price_path_plus_macro","feature_families":["price_path_base","macro_optional"],"models":["ridge","logistic"],"status":"exploratory_ablation"}]
    if c["candidates"] != expected_candidates or c["variant_budget"] != 2 or c["no_budget_reset_after_failure"] is not True or c["no_retuning_after_protected"] is not True: raise RollingError("CONFIG_INVALID", "candidate budget")
    models = _exact(c["models"], {"ridge_l2","logistic_l2","logistic_learning_rate","logistic_iterations","probability_clip"}, "models")
    if _positive(models["ridge_l2"],"ridge_l2") <= 0 or _positive(models["logistic_l2"],"logistic_l2") <= 0: raise RollingError("CONFIG_INVALID", "l2")
    if not 0 < _positive(models["logistic_learning_rate"],"learning_rate") <= 1 or _positive(models["logistic_iterations"],"iterations",integer=True) < 1 or not 0 < _finite(models["probability_clip"],"clip") < .5: raise RollingError("CONFIG_INVALID", "logistic settings")
    calibration = _exact(c["calibration"], {"method","quantiles","tail_quantile","tail_threshold_scope"}, "calibration")
    if calibration != {"method":"empirical_training_residuals","quantiles":[0.05,0.5,0.95],"tail_quantile":0.10,"tail_threshold_scope":"all_training_eligible_origins_before_support_abstention"}: raise RollingError("CONFIG_INVALID", "calibration")
    metrics = _exact(c["metrics"], {"continuous","binary"}, "metrics")
    if metrics["continuous"] != ["mae","rmse","empirical_crps","interval_coverage","tail_mae","abstention_rate"] or metrics["binary"] != ["brier","log_loss","abstention_rate"]: raise RollingError("CONFIG_INVALID", "metrics")
    decision = _exact(c["decision_policy"], {"primary_comparison","secondary_descriptive","exploratory_nonselective","uncertainty_method","bootstrap_repetitions","bootstrap_seed","multiplicity","adopt_rule","reject_rule","tie_rule","otherwise","diagnostic_selection_allowed"}, "decision")
    if decision["primary_comparison"] != "primary_126_material_loss_brier_candidate_minus_unconditional_prevalence" or decision["secondary_descriptive"] != ["primary_126_return_empirical_crps","primary_126_return_mae","primary_126_return_tail_mae"] or decision["exploratory_nonselective"] != ["primary_126_max_drawdown","primary_126_relative_qqq_return","secondary_252_all_targets","diagnostic_stride_21","macro_optional_ablation"] or decision["uncertainty_method"] != "paired_nonoverlap_origin_bootstrap_percentile_95" or decision["bootstrap_repetitions"] != 1000 or decision["bootstrap_seed"] != 1262024 or decision["multiplicity"] != "single_frozen_primary_no_adjustment; all_other_results_descriptive_or_exploratory" or decision["adopt_rule"] != "adopt_only_if_delta_brier<0_and_95pct_upper<0" or decision["reject_rule"] != "reject_if_95pct_lower>0" or decision["tie_rule"] != "exact_delta_zero_is_tie" or decision["diagnostic_selection_allowed"] is not False or decision["otherwise"] != "inconclusive": raise RollingError("CONFIG_INVALID", "decision hierarchy")
    gate = _exact(c["support_gate"], {"allow","abstain"}, "support gate")
    if gate != {"allow":["inside","edge"],"abstain":["outside","inconclusive"]}: raise RollingError("CONFIG_INVALID", "support gate")
    ledger = _exact(c["attempt_ledger"], {"schema_version","allowed_statuses","legal_transitions","append_only_hash_chain"}, "ledger")
    if ledger["schema_version"] != "rolling-attempt-ledger-v1" or ledger["allowed_statuses"] != ["registered","completed","failed"] or ledger["append_only_hash_chain"] is not True: raise RollingError("CONFIG_INVALID", "ledger")
    if _exact(c["evaluator"], {"evaluator_id","evaluator_version"}, "evaluator") != {"evaluator_id":"rolling-origin-evaluator","evaluator_version":"1.0.0"}: raise RollingError("CONFIG_INVALID", "evaluator")
    if _exact(c["artifacts"], {"session_roster","preregistration","development_split","protected_split","attempt_ledger"}, "artifacts") != {"session_roster":"session-roster.v1.json","preregistration":"rolling-preregistration.v1.json","development_split":"development-split.v1.json","protected_split":"protected-split.v1.json","attempt_ledger":"rolling-attempt-ledger.v1.json"}: raise RollingError("CONFIG_INVALID", "artifact names")
    return c


def load_session_roster(root: Path, name: str, config: Mapping[str, Any]) -> list[dt.date]:
    value, _ = _rooted_json(root, name)
    _exact(value, {"schema_version","calendar_id","calendar_version","timezone","source_manifest_v2_sha256","roster_sha256","session_count","session_start","session_end","sessions","contains_prices","contains_outcomes"}, "roster")
    sessions = value["sessions"]
    if type(sessions) is not list or any(type(item) is not str for item in sessions): raise RollingError("CONFIG_INVALID", "session list")
    roster_hash = hashlib.sha256((json.dumps(sessions,separators=(",",":"))+"\n").encode()).hexdigest()
    cal = config["calendar"]
    if value["roster_sha256"] != roster_hash or roster_hash != cal["session_roster_sha256"] or len(sessions) != cal["session_count"] or value["contains_prices"] is not False or value["contains_outcomes"] is not False: raise RollingError("CONFIG_INVALID", "roster identity")
    dates = [_iso(item,"session") for item in sessions]
    if dates != sorted(dates) or len(set(dates)) != len(dates) or dates[0].isoformat()!=cal["session_start"] or dates[-1].isoformat()!=cal["session_end"]: raise RollingError("DATA_CHRONOLOGY", "roster chronology")
    if dates[cal["fixed_origin_anchor_index"]].isoformat()!=cal["fixed_origin_anchor_date"]: raise RollingError("CONFIG_INVALID", "anchor mismatch")
    cutoff_index=dates.index(dt.date.fromisoformat(config["rolling"]["development_maturity_cutoff"])); protected_index=cutoff_index+config["rolling"]["embargo_sessions"]+1
    if dates[protected_index].isoformat()!=config["rolling"]["protected_origin_start"]: raise RollingError("CONFIG_INVALID", "protected start is not after embargo")
    return dates


def origin_id(protocol_id: str, date: dt.date, horizon: int, stride: int) -> str:
    return "origin_" + hashlib.sha256(f"{protocol_id}|{date.isoformat()}|{horizon}|{stride}".encode()).hexdigest()[:20]


def build_origins(dates: Sequence[dt.date], config: Mapping[str, Any], family: str) -> list[RollingOrigin]:
    if list(dates)!=sorted(dates) or len(set(dates))!=len(dates): raise RollingError("DATA_CHRONOLOGY", "sessions not increasing")
    spec=config["rolling"][family]; anchor=config["calendar"]["fixed_origin_anchor_index"]; cutoff=dt.date.fromisoformat(config["rolling"]["development_maturity_cutoff"])
    result=[]
    for i in range(anchor,len(dates)-spec["horizon_sessions"],spec["stride_sessions"]):
        maturity=i+spec["horizon_sessions"]
        if dates[maturity] > cutoff: continue
        result.append(RollingOrigin(origin_id(config["protocol_id"],dates[i],spec["horizon_sessions"],spec["stride_sessions"]),i,dates[i],maturity,dates[maturity],spec["horizon_sessions"],spec["stride_sessions"]))
    return result


def expanding_training_origins(origins: Sequence[RollingOrigin], evaluation: RollingOrigin, purge: int, embargo: int, minimum: int) -> list[RollingOrigin]:
    result=[item for item in origins if item.maturity_index <= evaluation.origin_index-purge-embargo]
    if len(result)<minimum: raise RollingError("SPLIT_VIOLATION", "insufficient purged/embargoed origins")
    return result


class DevelopmentDataAdapter:
    """Metadata/features first; lazy labels for allowlisted matured development IDs only."""
    def __init__(self, metadata: Mapping[str,Any], features: Mapping[str,Mapping[str,float]], allowed_maturity: Mapping[str,str], label_loader: Callable[[Sequence[str]],Mapping[str,Mapping[str,Any]]], config: Mapping[str,Any]):
        expected={"source_manifest_v2_sha256":config["source_contract"]["owned_source_manifest_v2_sha256"],"calendar_id":config["calendar"]["calendar_id"],"calendar_version":config["calendar"]["calendar_version"],"session_roster_sha256":config["calendar"]["session_roster_sha256"],"protected_outcomes_accessed":False}
        if dict(metadata)!=expected: raise RollingError("CONFIG_INVALID", "adapter metadata")
        if set(features)-set(allowed_maturity): raise RollingError("PROTECTED_ACCESS_DENIED", "features include non-development IDs")
        self.metadata=dict(metadata); self.features={k:dict(v) for k,v in features.items()}; self.allowed_maturity=dict(allowed_maturity); self._loader=label_loader; self._cutoff=dt.date.fromisoformat(config["rolling"]["development_maturity_cutoff"])
    def load_labels(self, ids: Sequence[str]) -> Mapping[str,Mapping[str,Any]]:
        if any(item not in self.allowed_maturity for item in ids): raise RollingError("PROTECTED_ACCESS_DENIED", "ID not in development allowlist")
        if any(dt.date.fromisoformat(self.allowed_maturity[item])>self._cutoff for item in ids): raise RollingError("SPLIT_VIOLATION", "label matures after cutoff")
        labels=self._loader(tuple(ids))
        if set(labels)!=set(ids): raise RollingError("SPLIT_VIOLATION", "loader returned mismatched IDs")
        return labels


def _validate_matrix(x: Sequence[Sequence[float]], y: Sequence[Any], *, binary: bool=False) -> None:
    if not x or len(x)!=len(y) or not x[0] or any(len(row)!=len(x[0]) for row in x): raise RollingError("NUMERIC_FAILURE", "dimension mismatch")
    if any(type(v) not in (int,float) or not math.isfinite(float(v)) for row in x for v in row): raise RollingError("NUMERIC_FAILURE", "nonfinite feature")
    if binary:
        if any(type(v) is not int or v not in (0,1) for v in y): raise RollingError("NUMERIC_FAILURE", "binary target required")
    elif any(type(v) not in (int,float) or not math.isfinite(float(v)) for v in y): raise RollingError("NUMERIC_FAILURE", "nonfinite target")


def _solve(a:list[list[float]],b:list[float])->list[float]:
    n=len(b); aug=[a[i][:]+[b[i]] for i in range(n)]
    for col in range(n):
        pivot=max(range(col,n),key=lambda r:abs(aug[r][col]))
        if abs(aug[pivot][col])<1e-12: raise RollingError("NUMERIC_FAILURE","singular")
        aug[col],aug[pivot]=aug[pivot],aug[col]; scale=aug[col][col]; aug[col]=[v/scale for v in aug[col]]
        for r in range(n):
            if r!=col:
                f=aug[r][col]; aug[r]=[u-f*v for u,v in zip(aug[r],aug[col])]
    return [aug[i][-1] for i in range(n)]


def fit_ridge(x:Sequence[Sequence[float]],y:Sequence[float],l2:float)->RidgeModel:
    _validate_matrix(x,y); l2=_finite(l2,"l2")
    if l2<=0: raise RollingError("NUMERIC_FAILURE","l2 positive")
    d=[[1.0]+[float(v) for v in row] for row in x]; w=len(d[0]); gram=[[sum(r[i]*r[j] for r in d)+(l2 if i==j and i else 0) for j in range(w)] for i in range(w)]; rhs=[sum(r[i]*float(t) for r,t in zip(d,y)) for i in range(w)]
    return RidgeModel(tuple(_solve(gram,rhs)))


def predict_ridge(m:RidgeModel,row:Sequence[float])->float:
    if len(row)+1!=len(m.coefficients) or any(not math.isfinite(float(v)) for v in row): raise RollingError("NUMERIC_FAILURE","ridge prediction input")
    return m.coefficients[0]+sum(a*float(b) for a,b in zip(m.coefficients[1:],row))


def _sigmoid(v:float)->float:
    if v>=0: z=math.exp(-v); return 1/(1+z)
    z=math.exp(v); return z/(1+z)


def fit_logistic(x:Sequence[Sequence[float]],y:Sequence[int],l2:float,lr:float,iterations:int,clip:float)->LogisticModel:
    _validate_matrix(x,y,binary=True); l2=_finite(l2,"l2"); lr=_finite(lr,"lr"); clip=_finite(clip,"clip")
    if l2<=0 or not 0<lr<=1 or type(iterations) is not int or iterations<=0 or not 0<clip<.5: raise RollingError("NUMERIC_FAILURE","logistic hyperparameters")
    d=[[1.0]+[float(v) for v in row] for row in x]; beta=[0.0]*len(d[0])
    for _ in range(iterations):
        grad=[0.0]*len(beta)
        for row,target in zip(d,y):
            e=_sigmoid(sum(a*b for a,b in zip(beta,row)))-target
            for j,v in enumerate(row): grad[j]+=e*v
        for j in range(len(beta)): beta[j]-=lr*(grad[j]/len(d)+(0 if j==0 else l2*beta[j]/len(d)))
    return LogisticModel(tuple(beta),clip)


def predict_logistic(m:LogisticModel,row:Sequence[float])->float:
    if len(row)+1!=len(m.coefficients) or not 0<m.clip<.5 or any(not math.isfinite(float(v)) for v in row): raise RollingError("NUMERIC_FAILURE","logistic prediction input")
    p=_sigmoid(m.coefficients[0]+sum(a*float(b) for a,b in zip(m.coefficients[1:],row))); return min(1-m.clip,max(m.clip,p))


def empirical_quantile(values:Sequence[float],q:float)->float:
    if not 0<=q<=1 or not values or any(type(v) not in (int,float) or not math.isfinite(float(v)) for v in values): raise RollingError("NUMERIC_FAILURE","invalid quantile")
    o=sorted(float(v) for v in values); pos=(len(o)-1)*q; lo,hi=math.floor(pos),math.ceil(pos); return o[lo] if lo==hi else o[lo]+(o[hi]-o[lo])*(pos-lo)


def freeze_tail_threshold(training_actual:Sequence[float],q:float=.10)->float:
    return empirical_quantile(training_actual,q)


def empirical_crps(actual:float,point:float,residuals:Sequence[float])->float:
    values=[actual,point,*residuals]
    if not residuals or any(type(v) not in (int,float) or not math.isfinite(float(v)) for v in values): raise RollingError("NUMERIC_FAILURE","finite nonempty CRPS inputs required")
    ensemble=[float(point)+float(r) for r in residuals]; first=sum(abs(float(actual)-v) for v in ensemble)/len(ensemble); second=sum(abs(a-b) for a in ensemble for b in ensemble)/(2*len(ensemble)**2); return first-second


def _aligned(actual:Sequence[Any],*arrays:Sequence[Any])->None:
    if any(len(a)!=len(actual) for a in arrays): raise RollingError("NUMERIC_FAILURE","equal lengths required")


def regression_metrics(actual:Sequence[float],predicted:Sequence[float|None],lower:Sequence[float|None],upper:Sequence[float|None],residual_samples:Sequence[float],tail_threshold:float)->dict[str,Any]:
    _aligned(actual,predicted,lower,upper)
    if any(type(a) not in (int,float) or not math.isfinite(float(a)) for a in actual) or not math.isfinite(float(tail_threshold)): raise RollingError("NUMERIC_FAILURE","finite regression inputs")
    kept=[]
    for a,p,lo,hi in zip(actual,predicted,lower,upper):
        if p is None or lo is None or hi is None:
            if not (p is None and lo is None and hi is None): raise RollingError("NUMERIC_FAILURE","partial abstention interval")
            continue
        if any(type(v) not in (int,float) or not math.isfinite(float(v)) for v in (p,lo,hi)) or lo>hi: raise RollingError("NUMERIC_FAILURE","invalid interval")
        kept.append((float(a),float(p),float(lo),float(hi)))
    if not kept: return {"status":"inconclusive","mae":None,"rmse":None,"empirical_crps":None,"interval_coverage":None,"tail_mae":None,"abstention_rate":1.0,"retained":0}
    errors=[a-p for a,p,_,_ in kept]; tails=[abs(a-p) for a,p,_,_ in kept if a<=tail_threshold]
    return {"status":"scored","mae":sum(abs(e) for e in errors)/len(errors),"rmse":math.sqrt(sum(e*e for e in errors)/len(errors)),"empirical_crps":sum(empirical_crps(a,p,residual_samples) for a,p,_,_ in kept)/len(kept),"interval_coverage":sum(lo<=a<=hi for a,_,lo,hi in kept)/len(kept),"tail_mae":None if not tails else sum(tails)/len(tails),"abstention_rate":1-len(kept)/len(actual),"retained":len(kept)}


def binary_metrics(actual:Sequence[int],probabilities:Sequence[float|None],clip:float)->dict[str,Any]:
    _aligned(actual,probabilities)
    if any(type(a) is not int or a not in (0,1) for a in actual) or not 0<float(clip)<.5: raise RollingError("NUMERIC_FAILURE","binary/clip validation")
    kept=[]
    for a,p in zip(actual,probabilities):
        if p is None: continue
        if type(p) not in (int,float) or not math.isfinite(float(p)) or not 0<=p<=1: raise RollingError("NUMERIC_FAILURE","probability validation")
        kept.append((a,min(1-clip,max(clip,float(p)))))
    if not kept: return {"status":"inconclusive","brier":None,"log_loss":None,"abstention_rate":1.0,"retained":0}
    return {"status":"scored","brier":sum((p-a)**2 for a,p in kept)/len(kept),"log_loss":-sum(a*math.log(p)+(1-a)*math.log(1-p) for a,p in kept)/len(kept),"abstention_rate":1-len(kept)/len(actual),"retained":len(kept)}


def matched_retained_ids(actual:Mapping[str,Any],prediction_sets:Mapping[str,Mapping[str,float|None]])->list[str]:
    if not actual or not prediction_sets: raise RollingError("NUMERIC_FAILURE","empty evaluation population")
    if any(type(v) not in (int,float) or not math.isfinite(float(v)) for v in actual.values()): raise RollingError("NUMERIC_FAILURE","nonfinite actual")
    ids=set(actual)
    for values in prediction_sets.values():
        if set(values)!=set(actual): raise RollingError("NUMERIC_FAILURE","prediction ID mismatch")
        if any(v is not None and (type(v) not in (int,float) or not math.isfinite(float(v))) for v in values.values()): raise RollingError("NUMERIC_FAILURE","nonfinite prediction")
        ids &= {k for k,v in values.items() if v is not None}
    return sorted(ids)


def baseline_predictions(target:str,train_y:Sequence[float],features:Sequence[Mapping[str,float]])->dict[str,list[float]]:
    if target not in TARGETS or not train_y or any(not math.isfinite(float(v)) for v in train_y): raise RollingError("NUMERIC_FAILURE","baseline inputs")
    mean=sum(float(v) for v in train_y)/len(train_y)
    if target=="material_loss":
        if any(type(v) not in (int,float) or v not in (0,1) for v in train_y): raise RollingError("NUMERIC_FAILURE","binary prevalence")
        return {"unconditional_training_prevalence":[mean]*len(features),"trend_volatility_logistic":[min(1,max(0,mean-.2*f["tqqq_return_63"]+.1*f["realized_volatility_21"])) for f in features],"qqq_loss_prevalence_proxy":[min(1,max(0,mean-.2*f["qqq_return_126"])) for f in features],"cash_no_loss_probability":[0.0]*len(features)}
    names={"return":["unconditional_mean","trend_volatility","qqq_3x_proxy","cash_zero"],"max_drawdown":["unconditional_mean","trend_volatility","qqq_drawdown_3x_proxy","cash_zero"],"relative_qqq_return":["unconditional_mean","trend_volatility","qqq_gap_proxy","cash_zero"]}[target]
    return {names[0]:[mean]*len(features),names[1]:[mean+.25*f["tqqq_return_63"]-.1*f["realized_volatility_21"] for f in features],names[2]:[(3*f["qqq_return_126"] if target=="return" else min(0,3*f["qqq_return_126"]) if target=="max_drawdown" else 2*f["qqq_return_126"]) for f in features],names[3]:[0.0]*len(features)}


def paired_bootstrap_decision(candidate_losses:Sequence[float],baseline_losses:Sequence[float],repetitions:int=1000,seed:int=1262024)->dict[str,Any]:
    _aligned(candidate_losses,baseline_losses)
    if not candidate_losses or any(not math.isfinite(float(v)) for v in list(candidate_losses)+list(baseline_losses)) or type(repetitions) is not int or repetitions<=0: raise RollingError("NUMERIC_FAILURE","bootstrap inputs")
    delta=sum(c-b for c,b in zip(candidate_losses,baseline_losses))/len(candidate_losses)
    if math.isclose(delta,0.0,rel_tol=0.0,abs_tol=1e-15): return {"decision":"tie","delta_brier":0.0,"ci95":[0.0,0.0]}
    rng=random.Random(seed); samples=[]; n=len(candidate_losses)
    for _ in range(repetitions):
        idx=[rng.randrange(n) for _ in range(n)]; samples.append(sum(candidate_losses[i]-baseline_losses[i] for i in idx)/n)
    lo,hi=empirical_quantile(samples,.025),empirical_quantile(samples,.975)
    decision="adopt" if delta<0 and hi<0 else "reject" if lo>0 else "inconclusive"
    return {"decision":decision,"delta_brier":delta,"ci95":[lo,hi]}


def apply_support_gate(status:str,value:float,config:Mapping[str,Any])->float|None:
    if status in config["support_gate"]["allow"]: return value
    if status in config["support_gate"]["abstain"]: return None
    raise RollingError("CONFIG_INVALID","support status")


def candidate_feature_names(config:Mapping[str,Any],candidate_id:str)->list[str]:
    item=next((v for v in config["candidates"] if v["id"]==candidate_id),None)
    if item is None: raise RollingError("CONFIG_INVALID","candidate")
    return [name for family in item["feature_families"] for name in config["feature_families"][family]]


def past_price_features(tqqq:Sequence[float],qqq:Sequence[float],index:int)->dict[str,float]:
    if index<126 or len(tqqq)<=index or len(qqq)<=index or any(not math.isfinite(float(v)) or float(v)<=0 for v in list(tqqq[:index+1])+list(qqq[:index+1])): raise RollingError("DATA_CHRONOLOGY","past feature inputs")
    logs=[math.log(tqqq[j]/tqqq[j-1]) for j in range(index-20,index+1)]; center=sum(logs)/len(logs); downside=[math.log(tqqq[j]/tqqq[j-1]) for j in range(index-62,index+1)]
    return {"tqqq_return_21":tqqq[index]/tqqq[index-21]-1,"tqqq_return_63":tqqq[index]/tqqq[index-63]-1,"tqqq_return_126":tqqq[index]/tqqq[index-126]-1,"distance_from_126_high":tqqq[index]/max(tqqq[index-125:index+1])-1,"realized_volatility_21":math.sqrt(252*sum((v-center)**2 for v in logs)/len(logs)),"downside_semivariance_63":252*sum(min(v,0)**2 for v in downside)/len(downside),"qqq_return_126":qqq[index]/qqq[index-126]-1}


def residual_quantiles(actual:Sequence[float],predicted:Sequence[float],probabilities:Sequence[float])->dict[str,float]:
    _aligned(actual,predicted)
    if list(probabilities)!=sorted(set(probabilities)) or any(not 0<=q<=1 for q in probabilities): raise RollingError("NUMERIC_FAILURE","quantile probabilities")
    residuals=[]
    for a,b in zip(actual,predicted):
        if any(type(v) not in (int,float) or not math.isfinite(float(v)) for v in (a,b)): raise RollingError("NUMERIC_FAILURE","residual inputs")
        residuals.append(float(a)-float(b))
    return {str(q):empirical_quantile(residuals,q) for q in probabilities}


def validate_ledger(ledger:Mapping[str,Any],config:Mapping[str,Any])->None:
    required={"schema_version","ledger_id","bindings","variant_budget","no_budget_reset_after_failure","genesis_hash","head_hash","events","protected_outcomes_accessed"}
    if type(ledger) is not dict or set(ledger)!=required or ledger["variant_budget"]!=2 or ledger["no_budget_reset_after_failure"] is not True or ledger["protected_outcomes_accessed"] is not False: raise RollingError("LEDGER_CONFLICT","ledger envelope")
    head=ledger["genesis_hash"]
    attempts={}; registered=set()
    for sequence,event in enumerate(ledger["events"],1):
        expected={"sequence","attempt_id","candidate_id","target_id","status","error_code","protected_outcomes_accessed","previous_hash","bindings","event_hash"}
        if type(event) is not dict or set(event)!=expected or event["sequence"]!=sequence or event["previous_hash"]!=head or event["bindings"]!=ledger["bindings"] or event["protected_outcomes_accessed"] is not False: raise RollingError("LEDGER_CONFLICT","event chain")
        unhashed={k:v for k,v in event.items() if k!="event_hash"}
        if hashlib.sha256(canonical_json_bytes(unhashed)).hexdigest()!=event["event_hash"]: raise RollingError("LEDGER_CONFLICT","event hash")
        prior=attempts.get(event["attempt_id"],"none")
        if event["status"] not in config["attempt_ledger"]["legal_transitions"][prior]: raise RollingError("LEDGER_CONFLICT","transition")
        if prior=="none": registered.add(event["candidate_id"])
        attempts[event["attempt_id"]]=event["status"]; head=event["event_hash"]
    if len(registered)>2 or head!=ledger["head_hash"]: raise RollingError("LEDGER_CONFLICT","budget/head")


def build_development_split(config:Mapping[str,Any],dates:Sequence[dt.date])->dict[str,Any]:
    families={name:[{"origin_id":o.origin_id,"origin_date":o.origin_date.isoformat(),"maturity_date":o.maturity_date.isoformat(),"horizon_sessions":o.horizon_sessions,"stride_sessions":o.stride_sessions} for o in build_origins(dates,config,name)] for name in ("primary","secondary","diagnostic")}
    return {"schema_version":"development-split-v1","split_id":"tqqq-development-origins-through-2023-v1","protocol_id":config["protocol_id"],"session_roster_sha256":config["calendar"]["session_roster_sha256"],"development_maturity_cutoff":config["rolling"]["development_maturity_cutoff"],"protected_origin_start":config["rolling"]["protected_origin_start"],"origins":families,"contains_outcomes":False,"protected_outcomes_accessed":False}


def build_preregistration(config:Mapping[str,Any],bindings:Mapping[str,str])->dict[str,Any]:
    return {"schema_version":"rolling-preregistration-v2","protocol_id":config["protocol_id"],"bindings":dict(bindings),"frozen_protocol":dict(config),"attempt_ledger_initial_state":"empty_hash_chained","real_outcomes_executed":False,"protected_outcomes_accessed":False}


def build_protected_split(config:Mapping[str,Any],bindings:Mapping[str,str])->dict[str,Any]:
    return {"schema_version":"protected-split-v2","split_id":"tqqq-protected-origins-post-embargo-v2","protocol_id":config["protocol_id"],"bindings":dict(bindings),"partition_identity":"origins_on_or_after_2024-02-01","origin_ids":[],"origin_ids_state":"unmaterialized_unopened","access_status":"unopened","contains_outcomes":False,"protected_outcomes_accessed":False}


def evaluator_sha256(config:Mapping[str,Any])->str:
    spec={k:config[k] for k in ("targets","target_baselines","scoring_population","models","calibration","metrics","decision_policy","support_gate","evaluator")}
    return hashlib.sha256(canonical_json_bytes(spec)).hexdigest()


def build_empty_ledger(bindings:Mapping[str,str],config:Mapping[str,Any])->dict[str,Any]:
    genesis=hashlib.sha256(canonical_json_bytes({"ledger_id":"rolling-attempt-ledger-v1","bindings":dict(bindings),"variant_budget":2})).hexdigest()
    return {"schema_version":"rolling-attempt-ledger-v1","ledger_id":"rolling-attempt-ledger-v1","bindings":dict(bindings),"variant_budget":2,"no_budget_reset_after_failure":True,"genesis_hash":genesis,"head_hash":genesis,"events":[],"protected_outcomes_accessed":False}


def append_ledger_event(ledger:Mapping[str,Any],event:Mapping[str,Any],config:Mapping[str,Any])->dict[str,Any]:
    expected={"sequence","attempt_id","candidate_id","target_id","status","error_code","protected_outcomes_accessed"}
    if type(event) is not dict or set(event)!=expected or event["protected_outcomes_accessed"] is not False: raise RollingError("LEDGER_CONFLICT","event contract")
    events=[dict(v) for v in ledger["events"]]; attempt_events=[v for v in events if v["attempt_id"]==event["attempt_id"]]; prior="none" if not attempt_events else attempt_events[-1]["status"]
    legal=config["attempt_ledger"]["legal_transitions"]
    if event["status"] not in legal[prior] or event["sequence"]!=len(events)+1 or event["candidate_id"] not in {v["id"] for v in config["candidates"]}: raise RollingError("LEDGER_CONFLICT","illegal transition/sequence/candidate")
    if event["status"] in {"registered","completed"} and event["error_code"] is not None: raise RollingError("LEDGER_CONFLICT","nonfailed event cannot carry error")
    if event["status"]=="failed" and event["error_code"] not in ERROR_CODES: raise RollingError("LEDGER_CONFLICT","failed event requires stable error")
    if attempt_events and (event["candidate_id"]!=attempt_events[0]["candidate_id"] or event["target_id"]!=attempt_events[0]["target_id"]): raise RollingError("LEDGER_CONFLICT","attempt binding changed")
    if event["target_id"] not in {"primary_126.material_loss","primary_126.return","primary_126.max_drawdown","primary_126.relative_qqq_return","secondary_252.exploratory"}: raise RollingError("LEDGER_CONFLICT","target binding")
    registered={v["candidate_id"] for v in events if v["status"]=="registered"}
    if prior=="none" and (event["candidate_id"] in registered or len(registered)>=ledger["variant_budget"]): raise RollingError("LEDGER_CONFLICT","variant budget consumed")
    payload={**event,"previous_hash":ledger["head_hash"],"bindings":ledger["bindings"]}; event_hash=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(); payload["event_hash"]=event_hash
    result=dict(ledger); result["events"]=events+[payload]; result["head_hash"]=event_hash; return result


def write_attempt_ledger(output_root:Path,name:str,ledger:Mapping[str,Any])->str:
    return write_canonical_json(output_root,name,ledger)


def preregister(config_root:Path,config_name:str,output_root:Path)->dict[str,str]:
    config=load_rolling_config(config_root,config_name); _,config_bytes=_rooted_json(config_root,config_name); dates=load_session_roster(output_root,config["artifacts"]["session_roster"],config)
    config_sha=hashlib.sha256(config_bytes).hexdigest(); code_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(); eval_sha=evaluator_sha256(config)
    base={"config_sha256":config_sha,"source_manifest_v2_sha256":config["source_contract"]["owned_source_manifest_v2_sha256"],"calendar_roster_sha256":config["calendar"]["session_roster_sha256"],"code_sha256":code_sha,"evaluator_sha256":eval_sha}
    with open_root_anchor(output_root,"rolling output root") as anchor:
        dev=build_development_split(config,dates); dev_sha=write_canonical_json(output_root,config["artifacts"]["development_split"],dev,root_anchor=anchor)
        pre=build_preregistration(config,{**base,"development_split_sha256":dev_sha}); pre_sha=write_canonical_json(output_root,config["artifacts"]["preregistration"],pre,root_anchor=anchor)
        bindings={**base,"development_split_sha256":dev_sha,"preregistration_sha256":pre_sha}
        protected_sha=write_canonical_json(output_root,config["artifacts"]["protected_split"],build_protected_split(config,bindings),root_anchor=anchor)
        ledger_sha=write_canonical_json(output_root,config["artifacts"]["attempt_ledger"],build_empty_ledger(bindings,config),root_anchor=anchor)
    return {"development_split_sha256":dev_sha,"preregistration_sha256":pre_sha,"protected_split_sha256":protected_sha,"attempt_ledger_sha256":ledger_sha}


def main()->int:
    parser=argparse.ArgumentParser(description="Generate frozen rolling metadata only; no real outcome run")
    parser.add_argument("--config-root",type=Path,required=True); parser.add_argument("--config-name",default="rolling-config.v1.json"); parser.add_argument("--output-root",type=Path,required=True); args=parser.parse_args()
    hashes=preregister(args.config_root,args.config_name,args.output_root)
    print("real_outcomes_executed=false"); print("protected_outcomes_accessed=false")
    for key,value in hashes.items(): print(f"{key}={value}")
    return 0




# --- Linked protocol v2 authority and development-only runner ---

def load_v2_config(root:Path,name:str="rolling-config.v2.json")->dict[str,Any]:
    c,_=_rooted_json(root,name)
    expected={"schema_version","protocol_id","claim_scope","bindings","input_sources","targets","rolling","primary_candidate_id","candidates","features","baselines","models","calibration","decision","support_gate","ledger","retired_contracts","support_geometry","artifacts"}
    if set(c)!=expected or c["schema_version"]!="rolling-origin-config-v2" or c["protocol_id"]!="tqqq-rolling-origin-development-v2": raise RollingError("CONFIG_INVALID","v2 envelope")
    b=c["bindings"]
    if set(b)!={"source_manifest_v2_sha256","upstream_source_manifest_sha256","calendar_id","calendar_version","calendar_roster_sha256","timezone","session_start","session_end","origin_anchor_index","origin_anchor_date","adjustment_basis","adjustment_vintage"}: raise RollingError("CONFIG_INVALID","v2 bindings")
    for key in ("source_manifest_v2_sha256","upstream_source_manifest_sha256","calendar_roster_sha256"): _sha(b[key],key)
    if (b["source_manifest_v2_sha256"],b["calendar_id"],b["calendar_version"],b["calendar_roster_sha256"],b["origin_anchor_index"],b["origin_anchor_date"]) != ("5ca62dc8cf180203b71e5e1e232d53d934285baa7242e54e72786abaa9b8436f","XNYS","observed-yahoo-session-roster-v1","f2b0358d1dfa9f44d34c62947eb52a6dacdaec314931b405a4390a77fdceabb8",126,"2010-08-12"): raise RollingError("CONFIG_INVALID","v2 frozen bindings")
    expected_inputs={"tqqq_path":"mentor/runtime/market-drawdown-ai-valuation-20261105/data/raw/yahoo-leveraged-history-20261106-v2/TQQQ.json","tqqq_sha256":"4455da6ae90303183ddf0866dfd23ba50c1e8b56e1d2454418cd8852d298c257","tqqq_bytes":475421,"qqq_path":"mentor/runtime/market-drawdown-ai-valuation-20261105/data/raw/yahoo-leveraged-history-20261106-v2/QQQ.json","qqq_sha256":"51f5a08f6f32fdf795d3b270491e7e0437c4c700e1f95508719748d51c494bb5","qqq_bytes":466946}
    if c["input_sources"]!=expected_inputs: raise RollingError("CONFIG_INVALID","v2 raw source bindings")
    if c["targets"]["primary_126"]["horizon"]!=126 or c["targets"]["primary_126"]["material_loss_threshold"]!=-0.25 or c["targets"]["secondary_252"]["horizon"]!=252 or c["targets"]["secondary_252"]["material_loss_threshold"]!=-0.40 or c["targets"]["secondary_252"]["execute_in_initial_runner"] is not False: raise RollingError("CONFIG_INVALID","v2 targets")
    roll=c["rolling"]
    if roll["primary"]!={"stride":126,"purge":126,"embargo":21,"minimum_training_origins":18,"minimum_retained_evaluation_origins":5}: raise RollingError("CONFIG_INVALID","v2 primary grid")
    if roll["secondary"]!={"stride":252,"purge":252,"embargo":21,"minimum_training_origins":8,"role":"exploratory_nonselective"} or roll["diagnostic"]["selection_allowed"] is not False: raise RollingError("CONFIG_INVALID","v2 exploratory grids")
    if c["primary_candidate_id"]!="price_path_base" or c["candidates"]!= [{"id":"price_path_base","role":"primary_selectable","families":["price_path_base"]},{"id":"price_path_plus_macro","role":"exploratory_ablation","families":["price_path_base","macro_optional"]}]: raise RollingError("CONFIG_INVALID","v2 candidates")
    m=c["models"]
    if _finite(m["ridge_l2"],"ridge")<=0 or _finite(m["logistic_l2"],"logistic")<=0 or not 0<_finite(m["learning_rate"],"lr")<=1 or type(m["iterations"]) is not int or m["iterations"]<=0 or not 0<_finite(m["clip"],"clip")<.5: raise RollingError("CONFIG_INVALID","v2 model settings")
    if c["decision"]["minimum_retained_n"]!=5 or c["decision"]["primary_metric"]!="primary_126_material_loss_brier_delta_vs_unconditional_prevalence": raise RollingError("CONFIG_INVALID","v2 decision")
    if c["support_geometry"]!={"k":12,"inside_quantile":0.95,"edge_quantile":0.99,"minimum_training_rows":18,"distance":"euclidean_training_median_mad_scaled","calibration":"training_leave_one_out_kth_neighbor"}: raise RollingError("CONFIG_INVALID","support geometry")
    expected_ledger={"schema":"rolling-attempt-ledger-v3","ledger_id":"tqqq-rolling-attempt-ledger-v3","legal_transitions":{"none":["registered"],"registered":["completed","failed"],"completed":[],"failed":[]},"variant_budget":2,"no_budget_reset":True,"cas_required":True,"cooperative_lock_scope":"same_host_processes_honoring_fcntl_lock","allowed_candidates":{"price_path_base":"primary_selectable","price_path_plus_macro":"exploratory_ablation"},"allowed_targets":["primary_126.material_loss","primary_126.return","primary_126.max_drawdown","primary_126.relative_qqq","secondary_252.exploratory"]}
    if c["ledger"]!=expected_ledger: raise RollingError("CONFIG_INVALID","v2 ledger")
    if c["retired_contracts"]!={"outcomes_config_v1_sha256":"f20848d2d30f8b9378c915fd8525939f9186d9b2b29c5d241e4c2c5fc8ed7803","retired_material_loss_threshold":-0.30,"status":"not_part_of_protocol_v2"}: raise RollingError("CONFIG_INVALID","retired outcomes contract")
    return c


def _hash_file(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()

def build_v2_development_split(config:Mapping[str,Any],dates:Sequence[dt.date])->dict[str,Any]:
    anchor=config["bindings"]["origin_anchor_index"]; cutoff=dt.date.fromisoformat(config["rolling"]["development_cutoff"]); groups={}
    for family,horizon in (("primary",126),("secondary",252),("diagnostic",126)):
        stride=config["rolling"][family]["stride"]; rows=[]
        for index in range(anchor,len(dates)-horizon,stride):
            maturity=index+horizon
            if dates[maturity]>cutoff: continue
            rows.append({"origin_id":origin_id(config["protocol_id"],dates[index],horizon,stride),"origin_index":index,"origin_date":dates[index].isoformat(),"maturity_index":maturity,"maturity_date":dates[maturity].isoformat(),"horizon":horizon,"stride":stride})
        groups[family]=rows
    return {"schema_version":"development-split-v2","protocol_id":config["protocol_id"],"calendar_roster_sha256":config["bindings"]["calendar_roster_sha256"],"groups":groups,"contains_outcomes":False,"protected_outcomes_accessed":False}


def v2_evaluator_hash(config:Mapping[str,Any])->str:
    return hashlib.sha256(canonical_json_bytes({k:config[k] for k in ("targets","rolling","primary_candidate_id","candidates","features","baselines","models","calibration","decision","support_gate","support_geometry","ledger")})).hexdigest()


def _acquire_v3_lock(output_root:Path,ledger_name:str)->tuple[int,Any]:
    anchor=open_root_anchor(output_root,"ledger output root"); lock_path=anchor.path/("."+ledger_name+".lock")
    try:
        fd=os.open(lock_path,os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600)
        observed=os.fstat(fd); _validate_trusted_stat(observed,"ledger lock",directory=False,device=anchor.device)
        if stat.S_IMODE(observed.st_mode)!=0o600: raise RollingError("LEDGER_CONFLICT","ledger lock mode")
        fcntl.flock(fd,fcntl.LOCK_EX); return fd,anchor
    except Exception:
        anchor.close(); raise


def _release_v3_lock(fd:int,anchor:Any)->None:
    fcntl.flock(fd,fcntl.LOCK_UN); os.close(fd); anchor.close()


def preregister_v2(config_root:Path,output_root:Path,source_root:Path)->dict[str,str]:
    config,config_bytes=_rooted_json(config_root,"rolling-config.v2.json"); config=load_v2_config(config_root)
    roster,roster_bytes=_rooted_json(output_root,"session-roster.v1.json"); dates=load_session_roster(output_root,"session-roster.v1.json",{"calendar":{"session_roster_sha256":config["bindings"]["calendar_roster_sha256"],"session_count":4211,"session_start":config["bindings"]["session_start"],"session_end":config["bindings"]["session_end"],"fixed_origin_anchor_index":config["bindings"]["origin_anchor_index"],"fixed_origin_anchor_date":config["bindings"]["origin_anchor_date"]},"source_contract":{"owned_source_manifest_v2_sha256":config["bindings"]["source_manifest_v2_sha256"]},"rolling":{"development_maturity_cutoff":config["rolling"]["development_cutoff"],"embargo_sessions":21,"protected_origin_start":config["rolling"]["protected_start"]}})
    outcomes_path=Path(__file__).with_name("rolling_outcomes.py"); builder_path=Path(__file__).with_name("development_inputs.py")
    base={"config_sha256":hashlib.sha256(config_bytes).hexdigest(),"source_manifest_v2_sha256":config["bindings"]["source_manifest_v2_sha256"],"calendar_roster_sha256":config["bindings"]["calendar_roster_sha256"],"runner_code_sha256":_hash_file(Path(__file__)),"outcomes_code_sha256":_hash_file(outcomes_path),"builder_code_sha256":_hash_file(builder_path),"evaluator_sha256":v2_evaluator_hash(config),"tqqq_raw_sha256":config["input_sources"]["tqqq_sha256"],"qqq_raw_sha256":config["input_sources"]["qqq_sha256"]}
    dev=build_v2_development_split(config,dates); dev_bytes=canonical_json_bytes(dev); dev_sha=hashlib.sha256(dev_bytes).hexdigest(); authority_base={**base,"development_split_sha256":dev_sha}
    from .development_inputs import compute_development_inputs
    feature_artifact,support_artifact=compute_development_inputs(config,dev,source_root,roster,authority_base); feature_bytes=canonical_json_bytes(feature_artifact); support_bytes=canonical_json_bytes(support_artifact); feature_sha=hashlib.sha256(feature_bytes).hexdigest(); support_sha=hashlib.sha256(support_bytes).hexdigest()
    pre_bindings={**authority_base,"development_features_sha256":feature_sha,"development_support_sha256":support_sha}
    pre={"schema_version":"rolling-preregistration-v4","protocol_id":config["protocol_id"],"bindings":pre_bindings,"frozen_protocol":config,"real_outcomes_executed":False,"protected_outcomes_accessed":False}; pre_bytes=canonical_json_bytes(pre); pre_sha=hashlib.sha256(pre_bytes).hexdigest(); authority={**pre_bindings,"preregistration_sha256":pre_sha}
    protected={"schema_version":"protected-split-v4","protocol_id":config["protocol_id"],"bindings":authority,"partition":"origins_on_or_after_2024-02-01","origin_ids":[],"access":"unopened","contains_outcomes":False,"protected_outcomes_accessed":False}; protected_bytes=canonical_json_bytes(protected); protected_sha=hashlib.sha256(protected_bytes).hexdigest(); ledger=build_v2_empty_ledger(authority,config); ledger_bytes=canonical_json_bytes(ledger); ledger_sha=hashlib.sha256(ledger_bytes).hexdigest()
    names=config["artifacts"]; expected={names["development_split"]:dev_bytes,names["development_features"]:feature_bytes,names["development_support"]:support_bytes,names["preregistration"]:pre_bytes,names["protected_split"]:protected_bytes,names["attempt_ledger"]:ledger_bytes}
    lock_fd,anchor=_acquire_v3_lock(output_root,names["attempt_ledger"])
    try:
        ledger_path=output_root/names["attempt_ledger"]; existing=[name for name in expected if (output_root/name).exists()]
        if ledger_path.exists():
            current=json.loads(ledger_path.read_text()); validate_v2_ledger(current,config,current.get("authority_bindings"))
            if current["events"]: raise RollingError("LEDGER_CONFLICT","refuse nonempty ledger overwrite")
            if set(existing)!=set(expected) or any((output_root/name).read_bytes()!=payload for name,payload in expected.items()): raise RollingError("LEDGER_CONFLICT","existing receipt set differs; no partial replacement")
            return {"development_split_sha256":dev_sha,"development_features_sha256":feature_sha,"development_support_sha256":support_sha,"preregistration_sha256":pre_sha,"protected_split_sha256":protected_sha,"attempt_ledger_sha256":ledger_sha}
        if existing: raise RollingError("LEDGER_CONFLICT","partial receipt set without authority ledger")
        for name,obj in ((names["development_split"],dev),(names["development_features"],feature_artifact),(names["development_support"],support_artifact),(names["preregistration"],pre),(names["protected_split"],protected),(names["attempt_ledger"],ledger)): write_canonical_json(output_root,name,obj,root_anchor=anchor)
        return {"development_split_sha256":dev_sha,"development_features_sha256":feature_sha,"development_support_sha256":support_sha,"preregistration_sha256":pre_sha,"protected_split_sha256":protected_sha,"attempt_ledger_sha256":ledger_sha}
    finally: _release_v3_lock(lock_fd,anchor)


def build_v2_empty_ledger(bindings:Mapping[str,str],config:Mapping[str,Any])->dict[str,Any]:
    genesis=hashlib.sha256(canonical_json_bytes({"schema":config["ledger"]["schema"],"ledger_id":config["ledger"]["ledger_id"],"bindings":dict(bindings),"variant_budget":2})).hexdigest()
    return {"schema_version":config["ledger"]["schema"],"ledger_id":config["ledger"]["ledger_id"],"authority_bindings":dict(bindings),"legal_transitions":config["ledger"]["legal_transitions"],"allowed_candidates":config["ledger"]["allowed_candidates"],"allowed_targets":config["ledger"]["allowed_targets"],"variant_budget":2,"no_budget_reset":True,"cooperative_lock_scope":config["ledger"]["cooperative_lock_scope"],"genesis_hash":genesis,"head_hash":genesis,"events":[],"protected_outcomes_accessed":False}


def validate_v2_ledger(ledger:Mapping[str,Any],config:Mapping[str,Any],authority:Mapping[str,str]|None=None)->None:
    required={"schema_version","ledger_id","authority_bindings","legal_transitions","allowed_candidates","allowed_targets","variant_budget","no_budget_reset","cooperative_lock_scope","genesis_hash","head_hash","events","protected_outcomes_accessed"}
    lcfg=config["ledger"]
    if type(ledger) is not dict or set(ledger)!=required or ledger["schema_version"]!=lcfg["schema"] or ledger["ledger_id"]!=lcfg["ledger_id"] or ledger["legal_transitions"]!=lcfg["legal_transitions"] or ledger["allowed_candidates"]!=lcfg["allowed_candidates"] or ledger["allowed_targets"]!=lcfg["allowed_targets"] or ledger["variant_budget"]!=2 or ledger["no_budget_reset"] is not True or ledger["cooperative_lock_scope"]!=lcfg["cooperative_lock_scope"] or ledger["protected_outcomes_accessed"] is not False: raise RollingError("LEDGER_CONFLICT","v3 ledger envelope")
    expected_authority_keys={"config_sha256","source_manifest_v2_sha256","calendar_roster_sha256","runner_code_sha256","outcomes_code_sha256","builder_code_sha256","evaluator_sha256","tqqq_raw_sha256","qqq_raw_sha256","development_split_sha256","development_features_sha256","development_support_sha256","preregistration_sha256"}
    if set(ledger["authority_bindings"])!=expected_authority_keys or any(type(v) is not str or len(v)!=64 or any(ch not in "0123456789abcdef" for ch in v) for v in ledger["authority_bindings"].values()): raise RollingError("LEDGER_CONFLICT","authority schema")
    if authority is not None and ledger["authority_bindings"]!=dict(authority): raise RollingError("LEDGER_CONFLICT","authority mismatch")
    expected_genesis=hashlib.sha256(canonical_json_bytes({"schema":lcfg["schema"],"ledger_id":lcfg["ledger_id"],"bindings":ledger["authority_bindings"],"variant_budget":2})).hexdigest()
    if ledger["genesis_hash"]!=expected_genesis: raise RollingError("LEDGER_CONFLICT","genesis rollback/reset")
    head=ledger["genesis_hash"]; attempts={}; attempt_binding={}; registered=set()
    for i,event in enumerate(ledger["events"],1):
        keys={"sequence","attempt_id","candidate_id","target_id","role","status","error_code","run_digest","evidence_digest","result_digest","protected_outcomes_accessed","previous_hash","authority_bindings","event_hash"}
        if type(event) is not dict or set(event)!=keys or event["sequence"]!=i or event["previous_hash"]!=head or event["authority_bindings"]!=ledger["authority_bindings"] or event["protected_outcomes_accessed"] is not False: raise RollingError("LEDGER_CONFLICT","event envelope")
        for key in ("run_digest","evidence_digest"):
            if type(event[key]) is not str or len(event[key])!=64 or any(ch not in "0123456789abcdef" for ch in event[key]): raise RollingError("LEDGER_CONFLICT","event digest")
        if event["result_digest"] is not None and (type(event["result_digest"]) is not str or len(event["result_digest"])!=64 or any(ch not in "0123456789abcdef" for ch in event["result_digest"])): raise RollingError("LEDGER_CONFLICT","result digest")
        if event["candidate_id"] not in ledger["allowed_candidates"] or event["role"]!=ledger["allowed_candidates"][event["candidate_id"]] or event["target_id"] not in ledger["allowed_targets"]: raise RollingError("LEDGER_CONFLICT","candidate/role/target")
        if event["status"]=="registered" and (event["error_code"] is not None or event["result_digest"] is not None): raise RollingError("LEDGER_CONFLICT","registered semantics")
        if event["status"]=="completed" and (event["error_code"] is not None or event["result_digest"] is None): raise RollingError("LEDGER_CONFLICT","completed semantics")
        if event["status"]=="failed" and (event["error_code"] not in ERROR_CODES or event["result_digest"] is not None): raise RollingError("LEDGER_CONFLICT","failed semantics")
        unhashed={k:v for k,v in event.items() if k!="event_hash"}
        if hashlib.sha256(canonical_json_bytes(unhashed)).hexdigest()!=event["event_hash"]: raise RollingError("LEDGER_CONFLICT","event hash")
        prior=attempts.get(event["attempt_id"],"none")
        if event["status"] not in ledger["legal_transitions"][prior]: raise RollingError("LEDGER_CONFLICT","transition")
        binding=(event["candidate_id"],event["target_id"],event["role"],event["run_digest"],event["evidence_digest"])
        if prior=="none":
            if event["candidate_id"] in registered or len(registered)>=2: raise RollingError("LEDGER_CONFLICT","budget reset")
            registered.add(event["candidate_id"]); attempt_binding[event["attempt_id"]]=binding
        elif attempt_binding[event["attempt_id"]]!=binding: raise RollingError("LEDGER_CONFLICT","attempt binding changed")
        attempts[event["attempt_id"]]=event["status"]; head=event["event_hash"]
    if head!=ledger["head_hash"]: raise RollingError("LEDGER_CONFLICT","stale head")


def append_v2_event(ledger:Mapping[str,Any],event:Mapping[str,Any],config:Mapping[str,Any],authority:Mapping[str,str])->dict[str,Any]:
    validate_v2_ledger(ledger,config,authority)
    keys={"sequence","attempt_id","candidate_id","target_id","role","status","error_code","run_digest","evidence_digest","result_digest","protected_outcomes_accessed"}
    if type(event) is not dict or set(event)!=keys or event["protected_outcomes_accessed"] is not False: raise RollingError("LEDGER_CONFLICT","v2 event contract")
    prior_events=[e for e in ledger["events"] if e["attempt_id"]==event["attempt_id"]]; prior="none" if not prior_events else prior_events[-1]["status"]
    if event["sequence"]!=len(ledger["events"])+1 or event["status"] not in ledger["legal_transitions"][prior]: raise RollingError("LEDGER_CONFLICT","v2 sequence/transition")
    candidate_roles={v["id"]:v["role"] for v in config["candidates"]}
    if event["candidate_id"] not in candidate_roles or event["role"]!=candidate_roles[event["candidate_id"]]: raise RollingError("LEDGER_CONFLICT","v2 candidate role")
    if event["status"]=="registered" and event["result_digest"] is not None: raise RollingError("LEDGER_CONFLICT","registered result")
    if event["status"]=="failed" and event["error_code"] not in ERROR_CODES: raise RollingError("LEDGER_CONFLICT","failed error")
    if event["status"]=="completed" and (event["error_code"] is not None or not event["result_digest"]): raise RollingError("LEDGER_CONFLICT","completed result")
    registered={e["candidate_id"] for e in ledger["events"] if e["status"]=="registered"}
    if prior=="none" and (event["candidate_id"] in registered or len(registered)>=2): raise RollingError("LEDGER_CONFLICT","variant budget consumed")
    if prior_events and any(event[k]!=prior_events[0][k] for k in ("candidate_id","target_id","role","run_digest","evidence_digest")): raise RollingError("LEDGER_CONFLICT","attempt binding changed")
    payload={**event,"previous_hash":ledger["head_hash"],"authority_bindings":dict(authority)}; payload["event_hash"]=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(); result=dict(ledger); result["events"]=[dict(e) for e in ledger["events"]]+[payload]; result["head_hash"]=payload["event_hash"]; return result


def cas_update_v2_ledger(output_root:Path,name:str,expected_head:str,event:Mapping[str,Any],config:Mapping[str,Any],authority:Mapping[str,str])->dict[str,Any]:
    lock_fd,anchor=_acquire_v3_lock(output_root,name)
    try:
        ledger=json.loads((output_root/name).read_text()); validate_v2_ledger(ledger,config,authority)
        if ledger["head_hash"]!=expected_head: raise RollingError("LEDGER_CONFLICT","stale expected head")
        updated=append_v2_event(ledger,event,config,authority)
        try: write_canonical_json(output_root,name,updated,root_anchor=anchor)
        except Exception as exc:
            try:
                observed=json.loads((output_root/name).read_text())
                if observed.get("head_hash")==updated["head_hash"]: return observed
            except Exception: pass
            raise RollingError("UNKNOWN_WRITE","ledger outcome unknown; reconcile before retry") from exc
        return updated
    finally: _release_v3_lock(lock_fd,anchor)


class V2DevelopmentDataAdapter:
    def __init__(self,config:Mapping[str,Any],authority:Mapping[str,str],allowed:Mapping[str,str],primary_rows:Sequence[Mapping[str,Any]],split_rows_digest:str,features:Mapping[str,Mapping[str,Any]],support:Mapping[str,Mapping[str,Any]],label_loader:Any,state_root:Path):
        self.config=MappingProxyType(dict(config)); self.authority=MappingProxyType(dict(authority)); self.allowed=MappingProxyType(dict(allowed)); self.primary_rows=tuple(MappingProxyType(dict(row)) for row in primary_rows); self.split_rows_digest=split_rows_digest; self.features=MappingProxyType({k:MappingProxyType(dict(v)) for k,v in features.items()}); self.support=MappingProxyType({k:MappingProxyType(dict(v)) for k,v in support.items()}); self._label_loader=label_loader; self.state_root=state_root.resolve()
    @classmethod
    def from_receipts(cls,config_root:Path,state_root:Path,source_root:Path)->"V2DevelopmentDataAdapter":
        config,config_bytes=_rooted_json(config_root,"rolling-config.v2.json"); config=load_v2_config(config_root); names=config["artifacts"]
        pre,pre_bytes=_rooted_json(state_root,names["preregistration"]); dev,dev_bytes=_rooted_json(state_root,names["development_split"]); feature_artifact,feature_bytes=_rooted_json(state_root,names["development_features"]); support_artifact,support_bytes=_rooted_json(state_root,names["development_support"]); protected,protected_bytes=_rooted_json(state_root,names["protected_split"]); ledger,ledger_bytes=_rooted_json(state_root,names["attempt_ledger"]); source,source_bytes=_rooted_json(state_root,"source-manifest.v2.json"); roster,roster_bytes=_rooted_json(state_root,"session-roster.v1.json")
        authority=ledger["authority_bindings"]; validate_v2_ledger(ledger,config,authority)
        expected={"config_sha256":hashlib.sha256(config_bytes).hexdigest(),"source_manifest_v2_sha256":hashlib.sha256(source_bytes).hexdigest(),"calendar_roster_sha256":roster["roster_sha256"],"runner_code_sha256":_hash_file(Path(__file__)),"outcomes_code_sha256":_hash_file(Path(__file__).with_name("rolling_outcomes.py")),"builder_code_sha256":_hash_file(Path(__file__).with_name("development_inputs.py")),"evaluator_sha256":v2_evaluator_hash(config),"tqqq_raw_sha256":config["input_sources"]["tqqq_sha256"],"qqq_raw_sha256":config["input_sources"]["qqq_sha256"],"development_split_sha256":hashlib.sha256(dev_bytes).hexdigest(),"development_features_sha256":hashlib.sha256(feature_bytes).hexdigest(),"development_support_sha256":hashlib.sha256(support_bytes).hexdigest(),"preregistration_sha256":hashlib.sha256(pre_bytes).hexdigest()}
        pre_authority={k:v for k,v in expected.items() if k!="preregistration_sha256"}
        if authority!=expected or pre.get("bindings")!=pre_authority or pre.get("frozen_protocol")!=config or protected.get("bindings")!=authority or protected.get("origin_ids")!=[] or source.get("sources",[{}])[0].get("symbol") is None or roster.get("contains_outcomes") is not False or dev.get("contains_outcomes") is not False or feature_artifact.get("authority")!={k:v for k,v in pre_authority.items() if k not in {"development_features_sha256","development_support_sha256"}} or support_artifact.get("authority")!=feature_artifact.get("authority"): raise RollingError("CONFIG_INVALID","receipt authority mismatch")
        rows=tuple(dict(row) for row in dev["groups"]["primary"]); digest=hashlib.sha256(canonical_json_bytes(rows)).hexdigest(); allowed={row["origin_id"]:row["maturity_date"] for row in rows}; features={row["origin_id"]:row["features"] for row in feature_artifact["records"]}; support={row["origin_id"]:{k:v for k,v in row.items() if k!="origin_id"} for row in support_artifact["records"]}
        if set(features)!=set(allowed) or set(support)!=set(allowed): raise RollingError("CONFIG_INVALID","feature/support ID mismatch")
        from .development_inputs import ConcreteDevelopmentLabelLoader
        loader=ConcreteDevelopmentLabelLoader(config,source_root,rows)
        return cls(config,authority,allowed,rows,digest,features,support,loader,state_root)
    def load_labels(self,ids:Sequence[str])->Mapping[str,Mapping[str,Any]]:
        if not ids or any(i not in self.allowed for i in ids): raise RollingError("PROTECTED_ACCESS_DENIED","nonallowlisted label ID")
        labels=self._label_loader.load(tuple(ids))
        if set(labels)!=set(ids): raise RollingError("SPLIT_VIOLATION","wrong label IDs")
        for values in labels.values():
            if set(values)!={"return","max_drawdown","relative_qqq","material_loss","qqq_3x_path_drawdown"} or type(values["material_loss"]) is not int or values["material_loss"] not in (0,1) or any(type(values[k]) not in (int,float) or not math.isfinite(float(values[k])) for k in ("return","max_drawdown","relative_qqq","qqq_3x_path_drawdown")): raise RollingError("NUMERIC_FAILURE","invalid labels")
        return labels


def qqq_daily_3x_path_drawdown(path:Sequence[float])->float:
    if len(path)<2 or any(type(v) not in (int,float) or not math.isfinite(float(v)) or float(v)<=0 for v in path): raise RollingError("NUMERIC_FAILURE","QQQ path")
    value=1.0; peak=1.0; draw=0.0
    for left,right in zip(path,path[1:]):
        multiplier=1+3*(float(right)/float(left)-1)
        if multiplier<=0: raise RollingError("NUMERIC_FAILURE","QQQ daily 3x proxy liquidation/floor reached")
        value*=multiplier; peak=max(peak,value); draw=min(draw,value/peak-1)
    return draw


def write_result_with_fence(output_root:Path,name:str,result:Mapping[str,Any])->str:
    expected=hashlib.sha256(canonical_json_bytes(result)).hexdigest()
    try: return write_canonical_json(output_root,name,result)
    except Exception as exc:
        try:
            if hashlib.sha256((output_root/name).read_bytes()).hexdigest()==expected: return expected
        except Exception: pass
        raise RollingError("UNKNOWN_WRITE","result outcome unknown; ledger completion forbidden") from exc


def compute_evidence_digest(value:Any)->str:
    def normalize(item:Any)->Any:
        if type(item) is float and not math.isfinite(item): return {"__nonfinite__":"nan" if math.isnan(item) else "positive_infinity" if item>0 else "negative_infinity"}
        if isinstance(item,Mapping): return {str(k):normalize(v) for k,v in item.items()}
        if isinstance(item,(list,tuple)): return [normalize(v) for v in item]
        return item
    return hashlib.sha256(canonical_json_bytes(normalize(value))).hexdigest()


def run_v2_development(adapter:V2DevelopmentDataAdapter,state_root:Path,attempt_id:str)->dict[str,Any]:
    if state_root.resolve()!=adapter.state_root: raise RollingError("CONFIG_INVALID","receipt_root must equal output_root trusted state root")
    output_root=state_root; config=adapter.config; ledger_name=config["artifacts"]["attempt_ledger"]; ledger=json.loads((state_root/ledger_name).read_text()); authority=ledger["authority_bindings"]; validate_v2_ledger(ledger,config,authority)
    if authority!=dict(adapter.authority) or ledger["events"] or ledger["head_hash"]!=ledger["genesis_hash"]: raise RollingError("LEDGER_CONFLICT","runner requires empty authority ledger head")
    primary_rows=[dict(row) for row in adapter.primary_rows]
    evidence_digest=compute_evidence_digest({"features":adapter.features,"split_rows_digest":adapter.split_rows_digest}); run_digest=hashlib.sha256(canonical_json_bytes({"attempt_id":attempt_id,"candidate_id":"price_path_base","authority":authority,"split_rows_digest":adapter.split_rows_digest})).hexdigest()
    register={"sequence":len(ledger["events"])+1,"attempt_id":attempt_id,"candidate_id":"price_path_base","target_id":"primary_126.material_loss","role":"primary_selectable","status":"registered","error_code":None,"run_digest":run_digest,"evidence_digest":evidence_digest,"result_digest":None,"protected_outcomes_accessed":False}
    ledger=cas_update_v2_ledger(output_root,ledger_name,ledger["head_hash"],register,config,authority)
    evaluated=[]; candidate_losses=[]; baseline_losses=[]; retained_ids=[]; fold_return_scores=[]
    try:
        for idx,row in enumerate(primary_rows):
            prior=primary_rows[:idx]; eval_index=row["origin_index"]
            training=[p for p in prior if p["maturity_index"]<=eval_index-126-21]
            if len(training)<18: continue
            evaluated.append(row["origin_id"]); ids=[p["origin_id"] for p in training]+[row["origin_id"]]
            labels=adapter.load_labels(ids); feature_names=config["features"]["price_path_base"]
            if any(i not in adapter.features or any(name not in adapter.features[i] for name in feature_names) for i in ids): raise RollingError("SPLIT_VIOLATION","missing features")
            x=[[float(adapter.features[i][name]) for name in feature_names] for i in ids[:-1]]; query=[float(adapter.features[ids[-1]][name]) for name in feature_names]
            yb=[labels[i]["material_loss"] for i in ids[:-1]]; prevalence=sum(yb)/len(yb); model=fit_logistic(x,yb,config["models"]["logistic_l2"],config["models"]["learning_rate"],config["models"]["iterations"],config["models"]["clip"]); p=predict_logistic(model,query)
            support=adapter.support[ids[-1]].get("status")
            if support not in config["support_gate"]["allow"]: continue
            actual=labels[ids[-1]]["material_loss"]; retained_ids.append(ids[-1]); candidate_losses.append((p-actual)**2); baseline_losses.append((prevalence-actual)**2)
            yr=[labels[i]["return"] for i in ids[:-1]]; ridge=fit_ridge(x,yr,config["models"]["ridge_l2"]); fitted=[predict_ridge(ridge,rowx) for rowx in x]; residuals=[a-b for a,b in zip(yr,fitted)]; prediction=predict_ridge(ridge,query); qs=residual_quantiles(yr,fitted,config["calibration"]["residual_quantiles"]); tail=freeze_tail_threshold(yr,.10); fold_return_scores.append(regression_metrics([labels[ids[-1]]["return"]],[prediction],[prediction+qs["0.05"]],[prediction+qs["0.95"]],residuals,tail))
        retained_n=len(retained_ids); evaluated_n=len(evaluated)
        if retained_n<5: decision={"decision":"inconclusive","reason":"minimum_retained_n_not_met","delta_brier":None,"ci95":None}
        else: decision=paired_bootstrap_decision(candidate_losses,baseline_losses,config["decision"]["bootstrap_repetitions"],config["decision"]["bootstrap_seed"])
        if fold_return_scores:
            names=("mae","rmse","empirical_crps","interval_coverage","tail_mae"); exploratory_return={"status":"scored","folds":len(fold_return_scores),**{name:sum(v[name] for v in fold_return_scores if v[name] is not None)/sum(v[name] is not None for v in fold_return_scores) if any(v[name] is not None for v in fold_return_scores) else None for name in names}}
        else: exploratory_return={"status":"inconclusive","folds":0,"mae":None,"rmse":None,"empirical_crps":None,"interval_coverage":None,"tail_mae":None}
        candidate_brier=None if not candidate_losses else sum(candidate_losses)/len(candidate_losses); baseline_brier=None if not baseline_losses else sum(baseline_losses)/len(baseline_losses)
        result={"schema_version":"development-result-v3","attempt_id":attempt_id,"candidate_id":"price_path_base","evaluated_n":evaluated_n,"retained_n":retained_n,"retained_origin_ids":retained_ids,"primary":{"metric":"brier_delta_vs_unconditional_prevalence","candidate_brier":candidate_brier,"baseline_brier":baseline_brier,"decision":decision},"exploratory":{"return_126_fold_local":exploratory_return,"secondary_252":{"status":"not_executed_preregistered_exploratory"},"macro_ablation":{"status":"not_executed_nonselective"}},"protected_outcomes_accessed":False}
        result_digest=write_result_with_fence(output_root,config["artifacts"]["development_result"],result)
        complete={"sequence":len(ledger["events"])+1,"attempt_id":attempt_id,"candidate_id":"price_path_base","target_id":"primary_126.material_loss","role":"primary_selectable","status":"completed","error_code":None,"run_digest":run_digest,"evidence_digest":evidence_digest,"result_digest":result_digest,"protected_outcomes_accessed":False}
        cas_update_v2_ledger(output_root,ledger_name,ledger["head_hash"],complete,config,authority); return result
    except Exception as exc:
        code=exc.code if isinstance(exc,RollingError) else "NUMERIC_FAILURE"
        failed={"sequence":len(ledger["events"])+1,"attempt_id":attempt_id,"candidate_id":"price_path_base","target_id":"primary_126.material_loss","role":"primary_selectable","status":"failed","error_code":code,"run_digest":run_digest,"evidence_digest":evidence_digest,"result_digest":None,"protected_outcomes_accessed":False}
        try: cas_update_v2_ledger(output_root,ledger_name,ledger["head_hash"],failed,config,authority)
        except Exception: pass
        raise


def main_dispatch()->int:
    import sys
    if len(sys.argv)>1 and sys.argv[1]=="preregister-v2":
        parser=argparse.ArgumentParser(); parser.add_argument("preregister-v2"); parser.add_argument("--config-root",type=Path,required=True); parser.add_argument("--output-root",type=Path,required=True); parser.add_argument("--source-root",type=Path,required=True); args=parser.parse_args(); hashes=preregister_v2(args.config_root,args.output_root,args.source_root); print("real_outcomes_executed=false"); print("protected_outcomes_accessed=false"); [print(f"{k}={v}") for k,v in hashes.items()]; return 0
    # Development execution requires an in-process lazy adapter; intentionally no protected CLI.
    return main()


if __name__=="__main__": raise SystemExit(main_dispatch())
