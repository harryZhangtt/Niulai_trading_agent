"""Deterministic single-target common-factor attribution.

The caller owns acquisition, alignment, factor/group selection and presentation.
This module fits one supplied target on one supplied estimation window and
mechanically decomposes a later, nonoverlapping window.  Components remain in
log-total-return units; only each complete target total is converted to an
arithmetic return.
"""
from __future__ import annotations

from dataclasses import dataclass as _dataclass
from datetime import date
from enum import Enum
import hashlib
import json
import math
from numbers import Real
from typing import Optional

import numpy as np

SCHEMA_VERSION = 1
API_VERSION = "common-factor-attribution-1"
NUMPY_VERSION = "2.3.5"
LINEAR_ALGEBRA = "numpy.linalg.svd-max-abs-column-scaled-float64"
CANONICALIZATION = "utf8-json-sorted-keys-float64-hex-v1"
MAX_CONDITION_NUMBER = 100_000_000.0
RANK_TOLERANCE_MULTIPLIER = 1.0
MIN_FACTOR_SPAN_MULTIPLIER = 64.0
MAX_POINTS = 10_000
MAX_FACTORS = 32
MAX_GROUPS = 32
MAX_RESULT_COMPONENTS = 100_000
MAX_NAME_BYTES = 256


class IdentityKind(str, Enum):
    EXACT = "exact"
    PROXY = "proxy"


class ReturnBasis(str, Enum):
    NAV = "nav_total_return"
    MARKET = "market_total_return"
    BENCHMARK = "benchmark_total_return"


@_dataclass(frozen=True)
class SeriesIdentity:
    """Explicit exact/proxy, NAV/market/benchmark and source-hash identity."""

    series_id: str
    exact_or_proxy: IdentityKind
    return_basis: ReturnBasis
    benchmark_id: str
    source_sha256: str
    proxy_for: Optional[str] = None


@_dataclass(frozen=True)
class ReturnSeries:
    name: str
    identity: SeriesIdentity
    log_total_returns: tuple[float, ...]


@_dataclass(frozen=True)
class FactorGroup:
    name: str
    factor_names: tuple[str, ...]


@_dataclass(frozen=True)
class DateWindow:
    start_date: str
    end_date: str


@_dataclass(frozen=True)
class AttributionRequest:
    schema_version: int
    api_version: str
    dates: tuple[str, ...]
    target: ReturnSeries
    factors: tuple[ReturnSeries, ...]
    groups: tuple[FactorGroup, ...]
    estimation_window: DateWindow
    decomposition_window: DateWindow


@_dataclass(frozen=True)
class NamedValue:
    name: str
    value: float


@_dataclass(frozen=True)
class NamedIdentity:
    name: str
    identity: SeriesIdentity


@_dataclass(frozen=True)
class RankDiagnostics:
    method: str
    numpy_version: str
    rows: int
    columns: int
    rank: int
    rank_tolerance: float
    singular_values: tuple[float, ...]
    condition_number: float
    maximum_condition_number: float
    column_scales: tuple[NamedValue, ...]
    factor_spans: tuple[NamedValue, ...]
    minimum_factor_span: float


@_dataclass(frozen=True)
class DailyAttribution:
    date: str
    target_log_total_return: float
    intercept_log_return: float
    factor_log_returns: tuple[NamedValue, ...]
    group_log_returns: tuple[NamedValue, ...]
    common_log_return: float
    residual_log_return: float
    total_log_return: float
    total_arithmetic_return: float


@_dataclass(frozen=True)
class AggregateAttribution:
    target_log_total_return: float
    intercept_log_return: float
    factor_log_returns: tuple[NamedValue, ...]
    group_log_returns: tuple[NamedValue, ...]
    common_log_return: float
    residual_log_return: float
    total_log_return: float
    total_arithmetic_return: float


@_dataclass(frozen=True)
class AttributionResult:
    schema_version: int
    api_version: str
    canonical_input_sha256: str
    canonicalization: str
    target_identity: SeriesIdentity
    factor_identities: tuple[NamedIdentity, ...]
    estimation_window: DateWindow
    decomposition_window: DateWindow
    intercept_coefficient: float
    factor_coefficients: tuple[NamedValue, ...]
    diagnostics: RankDiagnostics
    daily: tuple[DailyAttribution, ...]
    aggregate: AggregateAttribution


class AttributionError(ValueError):
    """Fixed-code validation or numerical failure with optional diagnostics."""

    def __init__(self, code: str, diagnostics: Optional[RankDiagnostics] = None):
        super().__init__(code)
        self.code = code
        self.diagnostics = diagnostics


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AttributionError(code)


def _text(value: object, code: str) -> str:
    _require(type(value) is str, code)
    encoded = value.encode("utf-8")
    _require(0 < len(encoded) <= MAX_NAME_BYTES, code)
    _require(value == value.strip(), code)
    return value


def _identity(value: object) -> SeriesIdentity:
    _require(type(value) is SeriesIdentity, "SERIES_IDENTITY")
    _text(value.series_id, "SERIES_IDENTITY")
    _require(type(value.exact_or_proxy) is IdentityKind, "SERIES_IDENTITY_KIND")
    _require(type(value.return_basis) is ReturnBasis, "RETURN_BASIS")
    _text(value.benchmark_id, "BENCHMARK_IDENTITY")
    _require(
        type(value.source_sha256) is str
        and len(value.source_sha256) == 64
        and value.source_sha256 == value.source_sha256.lower()
        and all(character in "0123456789abcdef" for character in value.source_sha256),
        "SOURCE_HASH",
    )
    if value.exact_or_proxy is IdentityKind.EXACT:
        _require(value.proxy_for is None, "EXACT_PROXY_IDENTITY")
    else:
        proxy_for = _text(value.proxy_for, "PROXY_IDENTITY")
        _require(proxy_for != value.series_id, "PROXY_IDENTITY")
    return value


def _finite_float(value: object, code: str) -> float:
    _require(isinstance(value, Real) and not isinstance(value, (bool, np.bool_)), code)
    result = float(value)
    _require(math.isfinite(result), code)
    return result


def _date_value(value: object) -> date:
    _require(type(value) is str and len(value) == 10, "DATE_FORMAT")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AttributionError("DATE_FORMAT") from None
    _require(parsed.isoformat() == value, "DATE_FORMAT")
    return parsed


def _window_indices(window: object, dates: tuple[str, ...], code: str) -> tuple[int, int]:
    _require(type(window) is DateWindow, code)
    start = _date_value(window.start_date)
    end = _date_value(window.end_date)
    _require(start <= end, code)
    try:
        first = dates.index(window.start_date)
        last = dates.index(window.end_date)
    except ValueError:
        raise AttributionError(code) from None
    _require(first <= last, code)
    return first, last + 1


def _validated(request: object):
    _require(type(request) is AttributionRequest, "REQUEST_TYPE")
    _require(request.schema_version == SCHEMA_VERSION, "SCHEMA_VERSION")
    _require(request.api_version == API_VERSION, "API_VERSION")
    _require(type(request.dates) is tuple and 2 <= len(request.dates) <= MAX_POINTS, "DATES")
    parsed_dates = tuple(_date_value(day) for day in request.dates)
    _require(all(left < right for left, right in zip(parsed_dates, parsed_dates[1:])),
             "DATES_ORDER")

    _require(type(request.target) is ReturnSeries, "TARGET_SERIES")
    target_name = _text(request.target.name, "TARGET_NAME")
    _identity(request.target.identity)
    _require(type(request.target.log_total_returns) is tuple, "TARGET_SHAPE")
    _require(len(request.target.log_total_returns) == len(request.dates), "TARGET_SHAPE")
    target_values = tuple(_finite_float(value, "TARGET_NONFINITE")
                          for value in request.target.log_total_returns)

    _require(type(request.factors) is tuple and 1 <= len(request.factors) <= MAX_FACTORS,
             "FACTORS")
    factor_rows = []
    for factor in request.factors:
        _require(type(factor) is ReturnSeries, "FACTOR_SERIES")
        name = _text(factor.name, "FACTOR_NAME")
        _identity(factor.identity)
        _require(type(factor.log_total_returns) is tuple, "FACTOR_SHAPE")
        _require(len(factor.log_total_returns) == len(request.dates), "FACTOR_SHAPE")
        values = tuple(_finite_float(value, "FACTOR_NONFINITE")
                       for value in factor.log_total_returns)
        factor_rows.append((name, factor.identity, values))
    factor_rows.sort(key=lambda row: row[0])
    factor_names = tuple(row[0] for row in factor_rows)
    _require(len(set(factor_names)) == len(factor_names), "FACTOR_NAMES_UNIQUE")
    _require(target_name not in factor_names, "SERIES_NAMES_UNIQUE")

    _require(type(request.groups) is tuple and 1 <= len(request.groups) <= MAX_GROUPS,
             "GROUPS")
    groups = []
    members = []
    for group in request.groups:
        _require(type(group) is FactorGroup, "FACTOR_GROUP")
        group_name = _text(group.name, "GROUP_NAME")
        _require(type(group.factor_names) is tuple and group.factor_names, "GROUP_MEMBERS")
        names = tuple(sorted(_text(name, "GROUP_MEMBER") for name in group.factor_names))
        _require(len(set(names)) == len(names), "GROUP_MEMBERS_UNIQUE")
        groups.append((group_name, names))
        members.extend(names)
    groups.sort(key=lambda row: row[0])
    group_names = tuple(row[0] for row in groups)
    _require(len(set(group_names)) == len(group_names), "GROUP_NAMES_UNIQUE")
    _require(not set(group_names).intersection(factor_names), "FACTOR_GROUP_NAMES_UNIQUE")
    _require(len(members) == len(set(members)), "FACTOR_GROUP_MEMBERS_UNIQUE")
    _require(set(members) == set(factor_names), "FACTOR_GROUP_PARTITION")

    estimation = _window_indices(request.estimation_window, request.dates,
                                 "ESTIMATION_WINDOW")
    decomposition = _window_indices(request.decomposition_window, request.dates,
                                    "DECOMPOSITION_WINDOW")
    _require(estimation[1] <= decomposition[0], "WINDOWS_OVERLAP_OR_ORDER")
    _require(estimation[1] - estimation[0] >= len(factor_rows) + 1,
             "ESTIMATION_ROWS")
    decomposition_rows = decomposition[1] - decomposition[0]
    result_components = decomposition_rows * (len(factor_rows) + len(groups) + 6)
    _require(result_components <= MAX_RESULT_COMPONENTS, "RESULT_SIZE")
    return target_values, tuple(factor_rows), tuple(groups), estimation, decomposition


def _float_hex(value: float) -> str:
    return float(value).hex()


def _identity_payload(identity: SeriesIdentity) -> dict[str, object]:
    return {
        "benchmark_id": identity.benchmark_id,
        "exact_or_proxy": identity.exact_or_proxy.value,
        "proxy_for": identity.proxy_for,
        "return_basis": identity.return_basis.value,
        "series_id": identity.series_id,
        "source_sha256": identity.source_sha256,
    }


def _canonical_hash(request: AttributionRequest, target_values, factor_rows, groups) -> str:
    payload = {
        "api_version": request.api_version,
        "dates": list(request.dates),
        "decomposition_window": {
            "end_date": request.decomposition_window.end_date,
            "start_date": request.decomposition_window.start_date,
        },
        "estimation_window": {
            "end_date": request.estimation_window.end_date,
            "start_date": request.estimation_window.start_date,
        },
        "factors": [
            {
                "identity": _identity_payload(identity),
                "log_total_returns_float64_hex": [_float_hex(value) for value in values],
                "name": name,
            }
            for name, identity, values in factor_rows
        ],
        "groups": [
            {"factor_names": list(names), "name": name} for name, names in groups
        ],
        "schema_version": request.schema_version,
        "target": {
            "identity": _identity_payload(request.target.identity),
            "log_total_returns_float64_hex": [_float_hex(value) for value in target_values],
            "name": request.target.name,
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _stable_span(column: np.ndarray) -> float:
    lower = float(np.min(column))
    upper = float(np.max(column))
    maximum = float(np.finfo(np.float64).max)
    if lower < 0.0 < upper and upper > maximum + lower:
        return maximum
    span = upper - lower
    return span if math.isfinite(span) else maximum


def _stable_sum(values, code: str = "OUTPUT_NONFINITE") -> float:
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError):
        raise AttributionError(code) from None
    _require(math.isfinite(result), code)
    return result


def _stable_product(left: float, right: float) -> float:
    result = float(left) * float(right)
    _require(math.isfinite(result), "OUTPUT_NONFINITE")
    return result


def _diagnostics_and_coefficients(matrix: np.ndarray, y: np.ndarray,
                                  factor_names: tuple[str, ...]) -> tuple[RankDiagnostics, np.ndarray]:
    _require(np.__version__ == NUMPY_VERSION, "NUMPY_VERSION")
    scales = np.max(np.abs(matrix), axis=0)
    factor_spans_array = np.asarray(
        [_stable_span(matrix[:, position]) for position in range(1, matrix.shape[1])],
        dtype=np.float64,
    )
    minimum_span = MIN_FACTOR_SPAN_MULTIPLIER * np.finfo(np.float64).eps
    span_rows = tuple(NamedValue(name, float(span))
                      for name, span in zip(factor_names, factor_spans_array))
    scale_rows = (NamedValue("intercept", float(scales[0])),) + tuple(
        NamedValue(name, float(scale)) for name, scale in zip(factor_names, scales[1:])
    )
    if (not np.all(np.isfinite(scales)) or np.any(scales == 0.0)
            or np.any(factor_spans_array <= minimum_span)):
        diagnostics = RankDiagnostics(
            method=LINEAR_ALGEBRA, numpy_version=np.__version__, rows=matrix.shape[0],
            columns=matrix.shape[1], rank=0, rank_tolerance=0.0,
            singular_values=(), condition_number=math.inf,
            maximum_condition_number=MAX_CONDITION_NUMBER,
            column_scales=scale_rows, factor_spans=span_rows,
            minimum_factor_span=float(minimum_span),
        )
        raise AttributionError("FACTOR_SCALE_WEAK", diagnostics)

    with np.errstate(over="ignore", invalid="ignore", divide="ignore", under="ignore"):
        normalized = matrix / scales
    _require(np.all(np.isfinite(normalized)), "SCALE_NONFINITE")
    try:
        left, singular, right_t = np.linalg.svd(normalized, full_matrices=False)
    except np.linalg.LinAlgError:
        raise AttributionError("SVD_FAILURE") from None
    tolerance = (RANK_TOLERANCE_MULTIPLIER * np.finfo(np.float64).eps
                 * max(normalized.shape) * singular[0])
    rank = int(np.count_nonzero(singular > tolerance))
    largest_singular = float(singular[0])
    smallest_singular = float(singular[-1])
    if (smallest_singular == 0.0
            or smallest_singular < largest_singular / float(np.finfo(np.float64).max)):
        condition = math.inf
    else:
        condition = largest_singular / smallest_singular
    diagnostics = RankDiagnostics(
        method=LINEAR_ALGEBRA, numpy_version=np.__version__, rows=matrix.shape[0],
        columns=matrix.shape[1], rank=rank, rank_tolerance=float(tolerance),
        singular_values=tuple(float(value) for value in singular),
        condition_number=condition, maximum_condition_number=MAX_CONDITION_NUMBER,
        column_scales=scale_rows, factor_spans=span_rows,
        minimum_factor_span=float(minimum_span),
    )
    if rank != matrix.shape[1]:
        raise AttributionError("RANK_DEFICIENT", diagnostics)
    if not math.isfinite(condition) or condition > MAX_CONDITION_NUMBER:
        raise AttributionError("ILL_CONDITIONED", diagnostics)

    with np.errstate(over="ignore", invalid="ignore", divide="ignore", under="ignore"):
        projected = left.T @ y
        scaled_coefficients = right_t.T @ (projected / singular)
        coefficients = scaled_coefficients / scales
    if not (np.all(np.isfinite(projected)) and np.all(np.isfinite(scaled_coefficients))
            and np.all(np.isfinite(coefficients))):
        raise AttributionError("COEFFICIENT_NONFINITE", diagnostics)
    return diagnostics, coefficients


def _arithmetic_total(log_total: float) -> float:
    try:
        value = math.expm1(log_total)
    except (OverflowError, ValueError):
        raise AttributionError("ARITHMETIC_CONVERSION") from None
    _require(math.isfinite(value), "ARITHMETIC_CONVERSION")
    return value

def attribute_common_factors(request: AttributionRequest) -> AttributionResult:
    """Attribute one target using all caller-supplied factors and groups.

    This is the only calculation entry point.  It performs no acquisition,
    alignment, selection, reporting, probability, causal or action decision.
    """

    target_values, factor_rows, groups, estimation, decomposition = _validated(request)
    factor_names = tuple(row[0] for row in factor_rows)
    factors = np.asarray([row[2] for row in factor_rows], dtype=np.float64).T
    target = np.asarray(target_values, dtype=np.float64)
    estimation_matrix = np.column_stack(
        (np.ones(estimation[1] - estimation[0], dtype=np.float64),
         factors[estimation[0]:estimation[1], :])
    )
    diagnostics, coefficients = _diagnostics_and_coefficients(
        estimation_matrix, target[estimation[0]:estimation[1]], factor_names
    )
    intercept = float(coefficients[0])
    betas = coefficients[1:]
    factor_coefficients = tuple(
        NamedValue(name, float(value)) for name, value in zip(factor_names, betas)
    )
    factor_positions = {name: index for index, name in enumerate(factor_names)}

    daily = []
    for index in range(decomposition[0], decomposition[1]):
        factor_values = tuple(
            NamedValue(name, _stable_product(factors[index, position], betas[position]))
            for position, name in enumerate(factor_names)
        )
        common = _stable_sum(item.value for item in factor_values)
        group_values = tuple(
            NamedValue(group_name, _stable_sum(
                factor_values[factor_positions[name]].value for name in members
            ))
            for group_name, members in groups
        )
        total = float(target[index])
        residual = _stable_sum((total, -intercept, -common))
        values_to_check = (intercept, common, residual, total) + tuple(
            item.value for item in factor_values + group_values
        )
        _require(all(math.isfinite(value) for value in values_to_check), "OUTPUT_NONFINITE")
        daily.append(DailyAttribution(
            date=request.dates[index], target_log_total_return=total,
            intercept_log_return=intercept, factor_log_returns=factor_values,
            group_log_returns=group_values, common_log_return=common,
            residual_log_return=residual, total_log_return=total,
            total_arithmetic_return=_arithmetic_total(total),
        ))
    daily_tuple = tuple(daily)
    aggregate_factors = tuple(
        NamedValue(name, _stable_sum(
            row.factor_log_returns[position].value for row in daily_tuple
        ))
        for position, name in enumerate(factor_names)
    )
    aggregate_groups = tuple(
        NamedValue(name, _stable_sum(
            row.group_log_returns[position].value for row in daily_tuple
        ))
        for position, (name, _members) in enumerate(groups)
    )
    aggregate_target = _stable_sum(row.target_log_total_return for row in daily_tuple)
    aggregate_intercept = _stable_sum(row.intercept_log_return for row in daily_tuple)
    aggregate_common = _stable_sum(row.common_log_return for row in daily_tuple)
    aggregate_residual = _stable_sum(row.residual_log_return for row in daily_tuple)
    aggregate = AggregateAttribution(
        target_log_total_return=aggregate_target,
        intercept_log_return=aggregate_intercept,
        factor_log_returns=aggregate_factors, group_log_returns=aggregate_groups,
        common_log_return=aggregate_common, residual_log_return=aggregate_residual,
        total_log_return=aggregate_target,
        total_arithmetic_return=_arithmetic_total(aggregate_target),
    )
    return AttributionResult(
        schema_version=SCHEMA_VERSION, api_version=API_VERSION,
        canonical_input_sha256=_canonical_hash(request, target_values, factor_rows, groups),
        canonicalization=CANONICALIZATION, target_identity=request.target.identity,
        factor_identities=tuple(NamedIdentity(name, identity)
                                for name, identity, _values in factor_rows),
        estimation_window=request.estimation_window,
        decomposition_window=request.decomposition_window,
        intercept_coefficient=intercept, factor_coefficients=factor_coefficients,
        diagnostics=diagnostics, daily=daily_tuple, aggregate=aggregate,
    )
