"""Focused deterministic contract tests for common-factor attribution."""
from __future__ import annotations

from dataclasses import asdict, replace
import inspect
import json
import math
import unittest
from unittest import mock
import warnings

import numpy as np
from scipy import linalg

from shared.calculation.operators import common_factor_attribution as cfa


DATES = tuple(f"2025-01-{day:02d}" for day in range(2, 16))
ESTIMATION = cfa.DateWindow(DATES[0], DATES[8])
DECOMPOSITION = cfa.DateWindow(DATES[9], DATES[-1])


def identity(series_id: str, basis=cfa.ReturnBasis.BENCHMARK, *, proxy=False,
             benchmark_id="BENCHMARK-TR", source_hash=None):
    return cfa.SeriesIdentity(
        series_id=series_id,
        exact_or_proxy=cfa.IdentityKind.PROXY if proxy else cfa.IdentityKind.EXACT,
        return_basis=basis,
        benchmark_id=benchmark_id,
        source_sha256=source_hash or (series_id[0].lower() * 64),
        proxy_for=benchmark_id if proxy else None,
    )


def request(ticker="SOXL", *, factor_order=("market", "sector"), target_identity=None):
    market = (-.030, .020, .011, -.007, .014, .004, -.013, .025, -.019,
              .008, -.005, .012, .003, -.009)
    sector = (.012, -.016, .022, .006, -.010, .019, .004, -.014, .009,
              -.006, .015, -.003, .018, .005)
    intercept = .0007
    target = tuple(intercept + 1.8 * m - .65 * s for m, s in zip(market, sector))
    values = {"market": market, "sector": sector}
    identities = {
        "market": identity("MARKET-TR", source_hash="b" * 64),
        "sector": identity("SECTOR-TR", source_hash="c" * 64),
    }
    factors = tuple(cfa.ReturnSeries(name, identities[name], values[name])
                    for name in factor_order)
    return cfa.AttributionRequest(
        schema_version=cfa.SCHEMA_VERSION,
        api_version=cfa.API_VERSION,
        dates=DATES,
        target=cfa.ReturnSeries(
            ticker,
            target_identity or identity(
                ticker, cfa.ReturnBasis.NAV, benchmark_id="SECTOR-TR",
                source_hash=("d" if ticker == "SOXL" else "e") * 64,
            ),
            target,
        ),
        factors=factors,
        groups=(cfa.FactorGroup("broad", ("market",)),
                cfa.FactorGroup("industry", ("sector",))),
        estimation_window=ESTIMATION,
        decomposition_window=DECOMPOSITION,
    )


def coefficient_map(result):
    return {row.name: row.value for row in result.factor_coefficients}


class CommonFactorAttributionTests(unittest.TestCase):
    def assertIdentitySums(self, result):
        for row in result.daily:
            factor_sum = math.fsum(item.value for item in row.factor_log_returns)
            group_sum = math.fsum(item.value for item in row.group_log_returns)
            self.assertAlmostEqual(factor_sum, row.common_log_return, places=15)
            self.assertAlmostEqual(group_sum, row.common_log_return, places=15)
            self.assertAlmostEqual(
                row.intercept_log_return + row.common_log_return + row.residual_log_return,
                row.total_log_return,
                places=15,
            )
            self.assertEqual(row.target_log_total_return, row.total_log_return)
            self.assertAlmostEqual(math.expm1(row.total_log_return),
                                   row.total_arithmetic_return, places=15)
        aggregate = result.aggregate
        self.assertAlmostEqual(math.fsum(item.value for item in aggregate.factor_log_returns),
                               aggregate.common_log_return, places=15)
        self.assertAlmostEqual(math.fsum(item.value for item in aggregate.group_log_returns),
                               aggregate.common_log_return, places=15)
        self.assertAlmostEqual(
            aggregate.intercept_log_return + aggregate.common_log_return
            + aggregate.residual_log_return,
            aggregate.total_log_return,
            places=15,
        )
        self.assertAlmostEqual(math.expm1(aggregate.total_log_return),
                               aggregate.total_arithmetic_return, places=15)

    def test_exact_synthetic_recovery_and_all_identities(self):
        result = cfa.attribute_common_factors(request())
        self.assertAlmostEqual(result.intercept_coefficient, .0007, places=14)
        coefficients = coefficient_map(result)
        self.assertAlmostEqual(coefficients["market"], 1.8, places=13)
        self.assertAlmostEqual(coefficients["sector"], -.65, places=13)
        self.assertLess(result.diagnostics.condition_number,
                        result.diagnostics.maximum_condition_number)
        for row in result.daily:
            self.assertAlmostEqual(row.residual_log_return, 0.0, places=14)
        self.assertIdentitySums(result)

    def test_soxl_and_tqqq_are_independent_single_target_requests(self):
        soxl_request = request("SOXL")
        tqqq_request = request("TQQQ")
        tqqq_values = tuple(value + .0003 * (index - 7)
                            for index, value in enumerate(tqqq_request.target.log_total_returns))
        tqqq_request = replace(tqqq_request, target=replace(
            tqqq_request.target, log_total_returns=tqqq_values
        ))
        soxl = cfa.attribute_common_factors(soxl_request)
        tqqq = cfa.attribute_common_factors(tqqq_request)
        self.assertEqual(soxl.target_identity.series_id, "SOXL")
        self.assertEqual(tqqq.target_identity.series_id, "TQQQ")
        self.assertNotEqual(soxl.canonical_input_sha256, tqqq.canonical_input_sha256)
        self.assertNotEqual(soxl.intercept_coefficient, tqqq.intercept_coefficient)
        self.assertEqual(len(soxl.daily), len(tqqq.daily))

    def test_factor_permutation_is_canonicalized_by_name(self):
        left = cfa.attribute_common_factors(request(factor_order=("market", "sector")))
        right = cfa.attribute_common_factors(request(factor_order=("sector", "market")))
        self.assertEqual(left, right)
        self.assertEqual(tuple(item.name for item in left.factor_coefficients),
                         ("market", "sector"))

    def test_canonical_hash_is_frozen_deterministic_and_has_no_timestamp(self):
        first = cfa.attribute_common_factors(request())
        second = cfa.attribute_common_factors(request())
        self.assertEqual(first.canonical_input_sha256, second.canonical_input_sha256)
        self.assertEqual(first.canonical_input_sha256, "fbd67a41ec019410d15f17145eb98e6390f945ec579903c77da7f36535bd799b")
        changed_values = list(request().target.log_total_returns)
        changed_values[-1] += 1e-12
        changed_request = request()
        changed_request = replace(changed_request, target=replace(
            changed_request.target, log_total_returns=tuple(changed_values)
        ))
        changed_identity_request = request()
        changed_identity_request = replace(changed_identity_request, target=replace(
            changed_identity_request.target,
            identity=replace(changed_identity_request.target.identity,
                             source_sha256="9" * 64),
        ))
        self.assertNotEqual(
            first.canonical_input_sha256,
            cfa.attribute_common_factors(changed_request).canonical_input_sha256,
        )
        self.assertNotEqual(
            first.canonical_input_sha256,
            cfa.attribute_common_factors(changed_identity_request).canonical_input_sha256,
        )
        encoded = json.dumps(asdict(first), sort_keys=True, allow_nan=False)
        self.assertNotIn("timestamp", encoded.lower())
        self.assertNotIn("generated_at", encoded.lower())
        self.assertNotIn("probability", encoded.lower())
        self.assertNotIn("causal", encoded.lower())
        self.assertNotIn("action", encoded.lower())

    def test_exact_and_proxy_source_identity_is_preserved(self):
        target_id = identity(
            "SOXL-MARKET", cfa.ReturnBasis.MARKET, proxy=True,
            benchmark_id="SOXL-NAV", source_hash="f" * 64,
        )
        value = request(target_identity=target_id)
        result = cfa.attribute_common_factors(value)
        self.assertIs(result.target_identity, target_id)
        self.assertEqual(result.target_identity.exact_or_proxy, cfa.IdentityKind.PROXY)
        self.assertEqual(result.target_identity.return_basis, cfa.ReturnBasis.MARKET)
        self.assertEqual(result.target_identity.proxy_for, "SOXL-NAV")
        self.assertEqual(result.target_identity.benchmark_id, "SOXL-NAV")
        self.assertEqual(result.target_identity.source_sha256, "f" * 64)
        self.assertTrue(all(row.identity.exact_or_proxy is cfa.IdentityKind.EXACT
                            for row in result.factor_identities))

    def test_independent_pivoted_qr_coefficient_recomputation(self):
        value = request()
        observed = cfa.attribute_common_factors(value)
        names = [factor.name for factor in sorted(value.factors, key=lambda row: row.name)]
        factor_lookup = {factor.name: factor.log_total_returns for factor in value.factors}
        stop = DATES.index(ESTIMATION.end_date) + 1
        matrix = np.column_stack((
            np.ones(stop),
            *[np.asarray(factor_lookup[name][:stop], dtype=np.float64) for name in names],
        ))
        y = np.asarray(value.target.log_total_returns[:stop], dtype=np.float64)
        q, r, pivots = linalg.qr(matrix, mode="economic", pivoting=True)
        pivoted = linalg.solve_triangular(r, q.T @ y)
        expected = np.empty_like(pivoted)
        expected[pivots] = pivoted
        np.testing.assert_allclose(
            np.asarray([observed.intercept_coefficient]
                       + [coefficient_map(observed)[name] for name in names]),
            expected,
            rtol=1e-12,
            atol=1e-14,
        )

    def test_malformed_dates_shapes_and_nonfinite_values_fail(self):
        cases = []
        value = request()
        cases.append((replace(value, dates=value.dates[:3] + (value.dates[2],) + value.dates[4:]),
                      "DATES_ORDER"))
        cases.append((replace(value, dates=("2025-1-02",) + value.dates[1:]), "DATE_FORMAT"))
        cases.append((replace(value, target=replace(
            value.target, log_total_returns=value.target.log_total_returns[:-1])), "TARGET_SHAPE"))
        factors = list(value.factors)
        factors[0] = replace(factors[0], log_total_returns=factors[0].log_total_returns[:-1])
        cases.append((replace(value, factors=tuple(factors)), "FACTOR_SHAPE"))
        target_values = list(value.target.log_total_returns)
        target_values[0] = math.inf
        cases.append((replace(value, target=replace(
            value.target, log_total_returns=tuple(target_values))), "TARGET_NONFINITE"))
        factors = list(value.factors)
        bad = list(factors[0].log_total_returns)
        bad[0] = math.nan
        factors[0] = replace(factors[0], log_total_returns=tuple(bad))
        cases.append((replace(value, factors=tuple(factors)), "FACTOR_NONFINITE"))
        for bad_request, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(cfa.AttributionError) as caught:
                    cfa.attribute_common_factors(bad_request)
                self.assertEqual(caught.exception.code, code)

    def test_windows_must_exist_be_ordered_and_not_overlap(self):
        value = request()
        cases = (
            (replace(value, estimation_window=cfa.DateWindow("2024-12-31", DATES[8])),
             "ESTIMATION_WINDOW"),
            (replace(value, decomposition_window=cfa.DateWindow(DATES[8], DATES[-1])),
             "WINDOWS_OVERLAP_OR_ORDER"),
            (replace(value, estimation_window=cfa.DateWindow(DATES[8], DATES[0])),
             "ESTIMATION_WINDOW"),
            (replace(value, estimation_window=cfa.DateWindow(DATES[4], DATES[5])),
             "ESTIMATION_ROWS"),
        )
        for bad_request, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(cfa.AttributionError) as caught:
                    cfa.attribute_common_factors(bad_request)
                self.assertEqual(caught.exception.code, code)

    def test_duplicate_factor_and_group_contracts_fail(self):
        value = request()
        duplicate_factor = replace(value.factors[1], name=value.factors[0].name)
        cases = (
            (replace(value, factors=(value.factors[0], duplicate_factor)),
             "FACTOR_NAMES_UNIQUE"),
            (replace(value, groups=(cfa.FactorGroup("same", ("market",)),
                                    cfa.FactorGroup("same", ("sector",)))),
             "GROUP_NAMES_UNIQUE"),
            (replace(value, groups=(cfa.FactorGroup("all", ("market",)),)),
             "FACTOR_GROUP_PARTITION"),
            (replace(value, groups=(cfa.FactorGroup("first", ("market", "sector")),
                                    cfa.FactorGroup("second", ("sector",)))),
             "FACTOR_GROUP_MEMBERS_UNIQUE"),
        )
        for bad_request, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(cfa.AttributionError) as caught:
                    cfa.attribute_common_factors(bad_request)
                self.assertEqual(caught.exception.code, code)

    def test_rank_deficiency_fails_closed_with_diagnostics(self):
        value = request()
        market = value.factors[0]
        duplicate = replace(value.factors[1], log_total_returns=market.log_total_returns)
        with self.assertRaises(cfa.AttributionError) as caught:
            cfa.attribute_common_factors(replace(value, factors=(market, duplicate)))
        self.assertEqual(caught.exception.code, "RANK_DEFICIENT")
        diagnostics = caught.exception.diagnostics
        self.assertIsNotNone(diagnostics)
        self.assertLess(diagnostics.rank, diagnostics.columns)
        self.assertTrue(math.isfinite(diagnostics.rank_tolerance))

    def test_near_collinearity_fails_closed_with_condition_diagnostics(self):
        value = request()
        base = value.factors[0].log_total_returns
        near = tuple(item + 1e-10 * math.sin(index)
                     for index, item in enumerate(base))
        second = replace(value.factors[1], log_total_returns=near)
        with self.assertRaises(cfa.AttributionError) as caught:
            cfa.attribute_common_factors(replace(value, factors=(value.factors[0], second)))
        self.assertEqual(caught.exception.code, "ILL_CONDITIONED")
        diagnostics = caught.exception.diagnostics
        self.assertEqual(diagnostics.rank, diagnostics.columns)
        self.assertGreater(diagnostics.condition_number,
                           diagnostics.maximum_condition_number)

    def test_factor_scale_weakness_fails_closed(self):
        value = request()
        weak = tuple(1e-16 * index for index in range(len(DATES)))
        first = replace(value.factors[0], log_total_returns=weak)
        with self.assertRaises(cfa.AttributionError) as caught:
            cfa.attribute_common_factors(replace(value, factors=(first, value.factors[1])))
        self.assertEqual(caught.exception.code, "FACTOR_SCALE_WEAK")
        self.assertGreater(caught.exception.diagnostics.minimum_factor_span,
                           max(weak) - min(weak))

    def test_materially_scaled_independent_factor_remains_supported(self):
        value = request()
        factor = value.factors[0]
        scaled = tuple(item * 1e-6 for item in factor.log_total_returns)
        factors = (replace(factor, log_total_returns=scaled), value.factors[1])
        target = tuple(.0007 + 1.8e6 * m - .65 * s
                       for m, s in zip(scaled, value.factors[1].log_total_returns))
        result = cfa.attribute_common_factors(replace(
            value, factors=factors,
            target=replace(value.target, log_total_returns=target),
        ))
        self.assertAlmostEqual(coefficient_map(result)["market"], 1.8e6, places=6)
        self.assertAlmostEqual(coefficient_map(result)["sector"], -.65, places=10)

    def test_extreme_target_and_component_fail_with_stable_codes(self):
        extreme_target_request = request()
        target_values = list(extreme_target_request.target.log_total_returns)
        target_values[9] = 1e308
        extreme_target_request = replace(
            extreme_target_request,
            target=replace(extreme_target_request.target,
                           log_total_returns=tuple(target_values)),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            with self.assertRaises(cfa.AttributionError) as caught:
                cfa.attribute_common_factors(extreme_target_request)
        self.assertEqual(caught.exception.code, "ARITHMETIC_CONVERSION")

        extreme_component_request = request()
        factors = list(extreme_component_request.factors)
        market_values = list(factors[0].log_total_returns)
        market_values[9] = 10.0
        factors[0] = replace(factors[0], log_total_returns=tuple(market_values))
        target_values = list(extreme_component_request.target.log_total_returns)
        sector_values = factors[1].log_total_returns
        for index in range(9):
            target_values[index] = 8e307 * market_values[index] - .65 * sector_values[index]
        target_values[9] = 0.0
        extreme_component_request = replace(
            extreme_component_request,
            target=replace(extreme_component_request.target,
                           log_total_returns=tuple(target_values)),
            factors=tuple(factors),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            with self.assertRaises(cfa.AttributionError) as caught:
                cfa.attribute_common_factors(extreme_component_request)
        self.assertEqual(caught.exception.code, "OUTPUT_NONFINITE")

        aggregate_overflow_request = request()
        factors = list(aggregate_overflow_request.factors)
        market_values = list(factors[0].log_total_returns)
        target_values = list(aggregate_overflow_request.target.log_total_returns)
        sector_values = factors[1].log_total_returns
        for index in range(9):
            target_values[index] = 8e307 * market_values[index] - .65 * sector_values[index]
        for index in range(9, len(market_values)):
            market_values[index] = 1.5
            target_values[index] = 0.0
        factors[0] = replace(factors[0], log_total_returns=tuple(market_values))
        aggregate_overflow_request = replace(
            aggregate_overflow_request,
            target=replace(aggregate_overflow_request.target,
                           log_total_returns=tuple(target_values)),
            factors=tuple(factors),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            with self.assertRaises(cfa.AttributionError) as caught:
                cfa.attribute_common_factors(aggregate_overflow_request)
        self.assertEqual(caught.exception.code, "OUTPUT_NONFINITE")

    def test_max_abs_scaling_handles_extreme_independent_factors_and_spans(self):
        value = request()
        market_pattern = (1, -1, .8, -.8, .6, -.6, .4, -.4, .2, -.2, .9, -.9, .7, -.7)
        sector_pattern = (.2, .4, -.6, .8, -1, .6, -.2, -.8, 1, -.4, .7, -.9, .3, -.5)
        market = tuple(item * 1e308 for item in market_pattern)
        sector = tuple(item * 1e308 for item in sector_pattern)
        target = tuple(.001 + 1e-308 * left - 5e-309 * right
                       for left, right in zip(market, sector))
        factors = (
            replace(value.factors[0], log_total_returns=market),
            replace(value.factors[1], log_total_returns=sector),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            result = cfa.attribute_common_factors(replace(
                value, factors=factors,
                target=replace(value.target, log_total_returns=target),
            ))
        coefficients = coefficient_map(result)
        self.assertAlmostEqual(coefficients["market"] / 1e-308, 1.0, places=12)
        self.assertAlmostEqual(coefficients["sector"] / -5e-309, 1.0, places=12)
        spans = {item.name: item.value for item in result.diagnostics.factor_spans}
        self.assertTrue(all(math.isfinite(span) and span > 1e308
                            for span in spans.values()))
        self.assertEqual(result.diagnostics.method,
                         "numpy.linalg.svd-max-abs-column-scaled-float64")

    def test_result_size_is_rejected_before_numpy_panel_materialization(self):
        with mock.patch.object(cfa, "MAX_RESULT_COMPONENTS", 1), \
                mock.patch.object(cfa.np, "asarray",
                                  side_effect=AssertionError("materialized")):
            with self.assertRaises(cfa.AttributionError) as caught:
                cfa.attribute_common_factors(request())
        self.assertEqual(caught.exception.code, "RESULT_SIZE")
        self.assertLessEqual(cfa.MAX_POINTS * cfa.MAX_FACTORS, 320_000)
        self.assertLessEqual(cfa.MAX_RESULT_COMPONENTS, 100_000)

    def test_identity_contract_rejects_ambiguous_or_invalid_source(self):
        value = request()
        bad_exact = replace(value.target.identity, proxy_for="OTHER")
        bad_proxy = replace(value.target.identity,
                            exact_or_proxy=cfa.IdentityKind.PROXY, proxy_for=None)
        bad_hash = replace(value.target.identity, source_sha256="A" * 64)
        for bad_identity, code in ((bad_exact, "EXACT_PROXY_IDENTITY"),
                                   (bad_proxy, "PROXY_IDENTITY"),
                                   (bad_hash, "SOURCE_HASH")):
            with self.subTest(code=code):
                bad_request = replace(value, target=replace(value.target, identity=bad_identity))
                with self.assertRaises(cfa.AttributionError) as caught:
                    cfa.attribute_common_factors(bad_request)
                self.assertEqual(caught.exception.code, code)

    def test_versions_and_pinned_dependency_are_fail_closed(self):
        value = request()
        for bad_request, code in (
            (replace(value, schema_version=2), "SCHEMA_VERSION"),
            (replace(value, api_version="other"), "API_VERSION"),
        ):
            with self.assertRaises(cfa.AttributionError) as caught:
                cfa.attribute_common_factors(bad_request)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(cfa.NUMPY_VERSION, np.__version__)
        self.assertEqual(cfa.LINEAR_ALGEBRA,
                         "numpy.linalg.svd-max-abs-column-scaled-float64")
        self.assertEqual(cfa.MAX_CONDITION_NUMBER, 100_000_000.0)
        public_functions = [
            name for name, member in inspect.getmembers(cfa, inspect.isfunction)
            if not name.startswith("_")
        ]
        self.assertEqual(public_functions, ["attribute_common_factors"])
        self.assertEqual(str(inspect.signature(cfa.attribute_common_factors)),
                         "(request: 'AttributionRequest') -> 'AttributionResult'")


if __name__ == "__main__":
    unittest.main()
