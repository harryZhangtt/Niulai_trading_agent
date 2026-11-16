"""Canonical EIY v5 metric-policy authority.

The file bytes, path, digest, gate order, population and decisive bits are one
closed authority. Registry membership and this self-hash are integrity checks,
not remote attestation or protection from a malicious same-user process.
"""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

CANONICAL_METRIC_POLICY_V5_PATH = Path(__file__).resolve().with_name("metric-policy-v5.json")
CANONICAL_METRIC_POLICY_V5_REF_PATH = "tuning/evals/information_fetch/information_yield/metric-policy-v5.json"
CANONICAL_METRIC_POLICY_V5_SHA256 = "b25d0e9dd7fd5d1db6f95c1114a179d0963d2bc55b7ef839227364e300df887f"
CANONICAL_GATE_ORDER_V5 = (
    "confirmation_cohort", "richness_mean", "richness_positive_cases",
    "depth_mean", "depth_positive_cases", "case_delta_floor", "issuer_loo",
    "precision_delta", "arm_wall_limit", "case_wall_ratio",
    "aggregate_wall_ratio", "complete_trace_ratio", "complete_pooled_review",
    "zero_critical_unsupported", "lineage", "execution_custody",
    "zero_hard_failures", "unknown_semantics",
)
_GATE_POPULATIONS = ("C",)*8 + ("E",)*10
GATE_SPECS_V5 = tuple(
    {"ordinal": index, "name": name, "population": population,
      "decisive": 12 <= index <= 17}
    for index, (name, population) in enumerate(
        zip(CANONICAL_GATE_ORDER_V5, _GATE_POPULATIONS), 1)
)
GATE_RECORD_FIELDS_V5 = frozenset((
    "ordinal", "name", "population", "decisive", "population_case_ids",
    "status", "observed", "threshold", "numerator", "denominator",
    "case_results", "reason_codes",
))

class PolicyV5Error(ValueError):
    pass

def _fail(code: str) -> None:
    raise PolicyV5Error(code)

def canonical_policy_bytes_v5(path: Union[Path, str] = CANONICAL_METRIC_POLICY_V5_PATH) -> bytes:
    candidate = Path(path)
    try:
        if candidate != CANONICAL_METRIC_POLICY_V5_PATH:
            _fail("ACQ_EIY_POLICY_NOT_CANONICAL")
        raw = candidate.read_bytes()
    except (OSError, RuntimeError):
        _fail("ACQ_EIY_POLICY_NOT_CANONICAL")
    if sha256(raw).hexdigest() != CANONICAL_METRIC_POLICY_V5_SHA256:
        _fail("ACQ_EIY_POLICY_NOT_CANONICAL")
    return raw

def canonical_policy_ref_v5() -> dict[str, str]:
    canonical_policy_bytes_v5()
    return {"path": CANONICAL_METRIC_POLICY_V5_REF_PATH,
            "sha256": CANONICAL_METRIC_POLICY_V5_SHA256}

def load_canonical_metric_policy_v5(path: Union[Path, str] = CANONICAL_METRIC_POLICY_V5_PATH) -> dict[str, Any]:
    try:
        value = json.loads(canonical_policy_bytes_v5(path))
    except (json.JSONDecodeError, UnicodeDecodeError):
        _fail("ACQ_EIY_POLICY_NOT_CANONICAL")
    if not isinstance(value, dict) or value.get("schema_version") != "information-yield-metric-policy-5":
        _fail("ACQ_EIY_POLICY_NOT_CANONICAL")
    return deepcopy(value)

def require_canonical_policy_ref_v5(ref: Mapping[str, Any]) -> dict[str, str]:
    expected = canonical_policy_ref_v5()
    if not isinstance(ref, Mapping) or set(ref) != {"path", "sha256"}:
        _fail("ACQ_EIY_POLICY_NOT_CANONICAL")
    same_path = ref["path"] == CANONICAL_METRIC_POLICY_V5_REF_PATH
    if not same_path or ref.get("sha256") != expected["sha256"]:
        _fail("ACQ_EIY_POLICY_NOT_CANONICAL")
    canonical_policy_bytes_v5(CANONICAL_METRIC_POLICY_V5_PATH)
    return expected

def verify_gate_set_v5(gates: Sequence[Mapping[str, Any]], *,
                       population_case_ids: Optional[Mapping[str, Sequence[str]]] = None) -> None:
    if not isinstance(gates, Sequence) or isinstance(gates, (str, bytes)) or len(gates) != 18:
        _fail("EIY_V5_GATE_ORDER")
    expected_ids = population_case_ids or {}
    for gate, spec in zip(gates, GATE_SPECS_V5):
        if not isinstance(gate, Mapping) or set(gate) != GATE_RECORD_FIELDS_V5:
            _fail("EIY_V5_GATE_ORDER")
        if any(gate.get(key) != spec[key] for key in ("ordinal", "name", "population", "decisive")):
            _fail("EIY_V5_GATE_ORDER" if gate.get("name") != spec["name"] or gate.get("ordinal") != spec["ordinal"] else "EIY_V5_GATE_POPULATION")
        ids = gate.get("population_case_ids")
        if not isinstance(ids, list) or len(ids) != len(set(ids)) or not all(isinstance(x, str) and x for x in ids):
            _fail("EIY_V5_GATE_POPULATION")
        if spec["population"] in expected_ids and ids != list(expected_ids[spec["population"]]):
            _fail("EIY_V5_GATE_POPULATION")
        if gate.get("status") not in {"pass", "fail", "unknown", "not_applicable"}:
            _fail("EIY_V5_GATE_ORDER")
        if not isinstance(gate.get("case_results"), list) or not isinstance(gate.get("reason_codes"), list):
            _fail("EIY_V5_GATE_ORDER")
