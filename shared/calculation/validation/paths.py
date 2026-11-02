"""Offline, bounded development validation of copied path/replay calculators.

Acquisition is deliberately outside this module. Public sample provenance and
synthetic assumptions remain distinct. No model calibration/alpha claim is made.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal, Inexact, ROUND_DOWN, Rounded, localcontext
from fractions import Fraction
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
LEGACY = ROOT / 'shared/calculation/legacy'
PROTOCOL = Path(__file__).with_name('paths_protocol.md')
DEFAULT_SAMPLE = ROOT / '.job-runtime/calculation/validation/paths/public-sample.json'


class CheckFailure(AssertionError):
    def __init__(self, code, **details):
        super().__init__(code)
        self.code, self.details = code, details


def require(condition, code, **details):
    if not condition:
        raise CheckFailure(code, **details)


def close(actual, expected, *, atol=1e-12, rtol=2e-11):
    actual, expected = float(actual), float(expected)
    error = abs(actual - expected)
    require(math.isfinite(actual) and math.isfinite(expected)
            and error <= atol + rtol * abs(expected),
            'NUMERICAL_MISMATCH', actual=actual, expected=expected,
            absolute_error=error, atol=atol, rtol=rtol)


def reject(function):
    try:
        function()
    except (ValueError, OverflowError):
        return
    raise CheckFailure('INVALID_INPUT_ACCEPTED')


def load_module(name, path, aliases=None):
    """Load the exact local copy; sibling aliases exist only during import."""
    alias = aliases or {}
    previous = {key: sys.modules.get(key) for key in alias}
    try:
        sys.modules.update(alias)
        spec = importlib.util.spec_from_file_location('_calc_validation_' + name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for key, old in previous.items():
            if old is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = old


def decimal_path(returns):
    with localcontext() as context:
        context.prec = 100
        values = [Decimal(1)]
        for value in returns:
            values.append(values[-1] * (1 + Decimal(str(value))))
        peak, dd = Decimal(1), Decimal(0)
        for value in values:
            peak = max(peak, value)
            dd = min(dd, value / peak - 1)
        return values[-1], dd


def simplex_vertices(values, lower, upper):
    """Independent exact LP oracle: enumerate all bounded-simplex vertices."""
    n = len(values)
    answers = []
    for free in range(n):
        fixed = [i for i in range(n) if i != free]
        for choices in itertools.product((0, 1), repeat=n - 1):
            weights = [Fraction(0)] * n
            for index, high in zip(fixed, choices):
                weights[index] = upper[index] if high else lower[index]
            weights[free] = 1 - sum(weights)
            if lower[free] <= weights[free] <= upper[free]:
                answers.append(sum(v * w for v, w in zip(values, weights)))
    require(bool(answers), 'REFERENCE_INFEASIBLE')
    return min(answers), max(answers)


def entry_packet():
    def row(t, price, dividend=0, invalid=False):
        return {'time_years': t, 'price': price, 'dividend_per_share': dividend,
                'invalidated': invalid}
    return {'budget': 120., 'horizon_years': 2., 'cash_rate': 0.,
            'fee_fraction': 0., 'price_basis': 'split_adjusted_price_only',
            'invalidation_action': 'hold_no_new', 'probability_basis': 'judgment',
            'policies': [{'id': 'now', 'kind': 'now', 'starter_fraction': 1.},
                         {'id': 'stage', 'kind': 'staged', 'starter_fraction': .5, 'limit_price': 40.},
                         {'id': 'wait', 'kind': 'wait', 'starter_fraction': 0., 'limit_price': 40.}],
            'scenarios': [{'id': 'up', 'probability': .25,
                           'observations': [row(0., 60.), row(1., 80.), row(2., 90.)]},
                          {'id': 'dip', 'probability': .5,
                           'observations': [row(0., 60.), row(1., 40.), row(2., 80.)]},
                          {'id': 'terminal_touch', 'probability': .25,
                           'observations': [row(0., 60.), row(1., 70.), row(2., 30.)]}]}


def vintage_packet(version):
    scope = {'series_id': 'synthetic_units', 'period': {'start': '2026-01-01', 'end': '2026-03-31'},
             'unit': 'quantity:units'}
    return {'version': version, 'subject': 'SYNTHETIC', 'as_of': '2026-05-01T00:00:00Z',
            'expected': [scope], 'observations': [{**copy.deepcopy(scope), 'value': '100',
             'available_at': '2026-04-15T12:00:00Z', 'vintage_id': 'v1',
             'source_ref': 'synthetic:validation-only'}]}


def cycle_packet(version):
    obs = {}
    for name, value, day, definition in [('ss', '100', '2025-10-23', 'annual supply'),
                                        ('se', '125', '2026-10-23', 'annual supply'),
                                        ('ds', '80', '2025-10-23', 'annual demand'),
                                        ('de', '100', '2026-10-23', 'annual demand')]:
        obs[name] = {'value': value, 'unit': 'quantity:units', 'period': {'start': day, 'end': day},
                     'available_at': '2026-10-23T21:00:00Z', 'source_ref': 'synthetic:arithmetic',
                     'definition': definition, 'origin': 'reported', 'market_scope': 'Synthetic matched universe',
                     'measurement_basis': 'Annualized matched units at snapshot'}
    return {'version': version, 'subject': 'SYNTHETIC', 'as_of': '2026-10-23T21:00:00Z',
            'observations': obs, 'calculations': [{'id': 'balance', 'kind': 'supply_demand',
             'supply_start': 'ss', 'supply_end': 'se', 'demand_start': 'ds', 'demand_end': 'de'}]}


def path_packet(payoff_module, paths=5000, seed=314159, sigma=.35):
    def quote(bid, ask, size=10000):
        return {'bid': str(bid), 'ask': str(ask), 'bid_size': size, 'ask_size': size,
                'timestamp': '2026-10-23T20:59:30Z', 'feed_status': 'realtime',
                'feed_id': 'SYNTHETIC-validation', 'source_ref': 'synthetic:assumed-not-market-quote'}
    payoff = {'version': payoff_module.VERSION, 'subject': 'SYNTH', 'as_of': '2026-10-23T21:00:00Z',
              'mode': 'historical', 'quote_policy': {'max_age_seconds': 60, 'max_quote_skew_seconds': 10},
              'budget': {'amount': '1200', 'currency': 'USD', 'idle_cash_return': '0'},
              'fees': {'option_per_contract_per_leg': '1', 'option_fixed_per_leg': '0',
                       'stock_per_share': '0', 'stock_fixed': '0'},
              'strategy': {'kind': 'long_call', 'long_leg': {'underlying': 'SYNTH',
                'contract_id': 'SYNTH261120C00100000', 'right': 'call', 'strike': '100',
                'expiry': '2026-11-20', 'exercise_style': 'american', 'multiplier': 100,
                'standard_deliverable_confirmed': True, 'quote': quote('4.5', '5')}, 'short_leg': None},
              'underlying_quote': {'symbol': 'SYNTH', 'quote': quote('99', '100')},
              'share_comparison': {'fractional': False, 'increment': '1'},
              'expiry_assumption': payoff_module.EXPIRY_ASSUMPTION,
              'expiry_stock_prices': ['0', '100', '105.01', '120']}
    return {'version': 1, 'payoff_packet': payoff, 'start_session': '2026-10-23', 'spot': 100.,
            'clock': 'XNYS_close_to_close_252', 'position_mode': 'one_contract',
            'simulation': {'method': 'gbm', 'paths': paths, 'seed': seed,
                'annual_trading_days': 252, 'annual_arithmetic_drift': .08, 'sigma': sigma,
                'drift_treatment': 'explicit_gbm_arithmetic',
                'assumption_source_ref': 'synthetic:fixed-validation-assumptions', 'block_size': None},
            'history': None}


def run(output_dir, sample_path=None):
    started = time.monotonic()
    out = Path(output_dir).absolute()
    boundary = ROOT / '.job-runtime/calculation/validation/paths'
    require(out.resolve().is_relative_to(boundary.resolve()), 'OUTPUT_OUTSIDE_CALCULATION_STATE')
    out.mkdir(parents=True, exist_ok=True)
    result = {'suite': 'paths', 'protocol': 'paths-v1', 'checks': [], 'findings': [],
              'modules_exercised': [], 'public_sources': [], 'evidence_paths': [],
              'limits': ['Development validation; no calibration, alpha, executable-fill or full16-module claim.',
                         'No network or private account/credential access in run().',
                         'Root owns scheduled acceptance and owner-email verification.']}

    def check(name, module, function, *, case_count=1):
        begin = time.monotonic()
        row = {'id': name, 'module': module, 'case_count': case_count}
        try:
            details = function()
            row.update(status='passed', details=details or {})
        except CheckFailure as error:
            row.update(status='failed', code=error.code, details=error.details)
        except Exception as error:
            row.update(status='failed', code='UNEXPECTED_EXCEPTION', details={'type': type(error).__name__})
        row['elapsed_seconds'] = round(time.monotonic() - begin, 6)
        result['checks'].append(row)
        if row['status'] == 'failed':
            result['findings'].append({k: row[k] for k in ('id', 'module', 'code', 'details')})
        if module not in result['modules_exercised']:
            result['modules_exercised'].append(module)

    def skip(name, module, code):
        result['checks'].append({'id': name, 'module': module, 'status': 'skipped', 'code': code})

    lev = load_module('leveraged', LEGACY / 'valuation/leveraged_funds.py')
    entry = load_module('entry', LEGACY / 'workflow/entry_policy_ev.py')
    payoff = load_module('payoff', LEGACY / 'workflow/options_payoff_checks.py')
    aliases = {'options_payoff_checks': payoff}
    bounds = load_module('bounds', LEGACY / 'workflow/options_decision_bounds.py', aliases)
    vintage = load_module('vintage', LEGACY / 'workflow/cycle_vintage_checks.py')
    cycle = load_module('cycle', LEGACY / 'workflow/cycle_checks.py')

    def compounded():
        rng = random.Random(712)
        largest = 0.
        for n in (1, 2, 10, 30, 100):
            for _ in range(20):
                returns = [rng.randint(-400, 400) / 10000 for _ in range(n)]
                wealth, drawdown = decimal_path(returns)
                actual = lev.analyze_returns(returns)
                close(actual['terminal_wealth'], wealth)
                close(actual['max_drawdown'], drawdown)
                reversed_actual = lev.analyze_returns(list(reversed(returns)))
                close(reversed_actual['terminal_wealth'], wealth)
                largest = max(largest, abs(actual['terminal_wealth'] - float(wealth)))
        return {'decimal_precision': 100, 'largest_absolute_wealth_error': largest}
    check('compounding_decimal_and_permutation', 'leveraged_funds', compounded, case_count=100)

    def stress():
        rows = [0.000001, -0.000001] * 50000
        actual = lev.analyze_returns(rows)
        with localcontext() as context:
            context.prec = 100
            expected = (Decimal(1) - Decimal('0.000001') ** 2) ** 50000
        close(actual['terminal_wealth'], expected)
        return {'resets': len(rows), 'terminal_wealth': actual['terminal_wealth']}
    check('bounded_100k_reset_stress', 'leveraged_funds', stress)

    def underflow():
        returns = [-.999] * 200
        expected, _ = decimal_path(returns)
        try:
            actual = lev.analyze_returns(returns)
        except (ValueError, OverflowError):
            return {'numerical_domain_rejected': True}
        require(actual['terminal_wealth'] > 0 and not actual['log_wealth_is_negative_infinity'],
                'POSITIVE_WEALTH_MISCLASSIFIED_AS_RUIN', exact_positive_wealth=str(expected),
                actual_terminal_wealth=actual['terminal_wealth'],
                actual_log_ruin=actual['log_wealth_is_negative_infinity'])
    check('underflow_is_not_mathematical_ruin', 'leveraged_funds', underflow)
    check('absorbing_actual_ruin', 'leveraged_funds',
          lambda: require(lev.analyze_returns([.1, -1, 99])['terminal_wealth'] == 0, 'RUIN_NOT_ABSORBING'))
    check('reject_nonfinite_and_below_minus100pct', 'leveraged_funds',
          lambda: [reject(lambda x=x: lev.analyze_returns([x])) for x in [float('nan'), float('inf'), -1.01]], case_count=3)

    def reset():
        for returns, leverage, costs in [([.1, -.05, .03], 3., .001), ([-.6, .9, .3], 2., 0.), ([.02, -.01], -1., -.001)]:
            actual = lev.simulate_reset_path(returns, leverage, costs)
            wealth = Decimal(1)
            with localcontext() as context:
                context.prec = 100
                for r in returns:
                    wealth *= max(Decimal(0), 1 + Decimal(str(leverage)) * Decimal(str(r)) - Decimal(str(costs)))
            close(actual['fund']['terminal_wealth'], wealth)
    check('reset_leverage_independent_product', 'leveraged_funds', reset, case_count=3)

    def mix():
        f, c, w = [.1, -.2, .3], [.001, .002, .001], Decimal('.4')
        fw, _ = decimal_path(f); cw, _ = decimal_path(c)
        close(lev.mix_fund_cash(f, c, .4)['terminal_wealth'], w * fw + (1 - w) * cw)
        rr = [w * Decimal(str(a)) + (1 - w) * Decimal(str(b)) for a, b in zip(f, c)]
        ew, _ = decimal_path(rr)
        close(lev.mix_fund_cash(f, c, .4, rebalance_each_reset=True)['terminal_wealth'], ew)
    check('fixed_mix_and_rebalanced_mix', 'leveraged_funds', mix, case_count=2)

    def quantiles():
        values = [-2., 4., 100.]
        weights = [.2, .3, .5]
        for q, expected in [(0., -2.), (.2, -2.), (.3, 4.), (.5, 4.), (.9, 100.), (1., 100.)]:
            require(lev.weighted_quantile(values, weights, q) == expected, 'EMPIRICAL_QUANTILE_MISMATCH', q=q)
    check('weighted_empirical_quantiles', 'leveraged_funds', quantiles, case_count=6)
    check('quantile_positive_mass_above_boundary', 'leveraged_funds',
          lambda: require(lev.weighted_quantile([0., 1.], [.5, .5], .5 + 5e-15) == 1.,
                          'QUANTILE_BOUNDARY_MASS_ERASED', probability=.5 + 5e-15, expected=1.,
                          actual=lev.weighted_quantile([0., 1.], [.5, .5], .5 + 5e-15)))
    check('tail_partial_mass', 'leveraged_funds',
          lambda: close(lev.lower_tail_mean([10., 20., 100.], [.02, .03, .95], .04), 15.))
    check('tiny_tail_zero_weight_invariance', 'leveraged_funds',
          lambda: close(lev.lower_tail_mean([0., 100.], [0., 1.], 1e-15), 100.))

    def blocks():
        rows = [{'id': i, 'joint': [i, -i]} for i in range(50)]
        actual = lev.moving_block_sample(rows, 200, 5, 91)
        require(actual == lev.moving_block_sample(rows, 200, 5, 91), 'NONDETERMINISTIC_BLOCK_SEED')
        require(len(actual) == 200 and all(r['joint'] == [r['id'], -r['id']] for r in actual), 'JOINT_SAMPLE_BROKEN')
        require(all(actual[j + k]['id'] == actual[j]['id'] + k for j in range(0, 200, 5) for k in range(5)), 'BLOCK_CONTIGUITY_BROKEN')
        actual[0]['joint'][0] = -999
        require(rows[0]['joint'] == [0, 0] and all(r['joint'][0] == r['id'] for r in rows), 'BLOCK_SAMPLE_ALIASES_SOURCE')
    check('joint_block_resampling_and_source_immutability', 'leveraged_funds', blocks)

    def starts():
        a = [100., 110., 90., 95., 100., 80., 120., 125.]
        selected = lev.eligible_start_indices(a, 2, 3, -.05)
        b = list(a); b[-2:] = [1e8, 1e-8]
        require([t for t in selected if t <= 4] == [t for t in lev.eligible_start_indices(b, 2, 3, -.05) if t <= 4], 'FUTURE_FILTER_LEAKAGE')
        expected = [t for t in range(2, len(a)-2) if Fraction(str(a[t])) / max(Fraction(str(x)) for x in a[t-2:t+1]) - 1 <= Fraction('-0.05')]
        require(selected == expected, 'ELIGIBLE_START_SCOPE_MISMATCH', actual=selected, expected=expected)
    check('past_only_eligible_starts', 'leveraged_funds', starts)

    def lp():
        rng = random.Random(612)
        for n in range(2, 6):
            for _ in range(10):
                values = [Decimal(rng.randint(-100, 100)) for _ in range(n)]
                lo = [Decimal('0.05')] * n
                hi = [Decimal('0.8')] * n
                exact = simplex_vertices(list(map(Fraction, values)), list(map(Fraction, lo)), list(map(Fraction, hi)))
                minimum, maximum, lw, hw = bounds.expectation_bounds(values, lo, hi)
                require(abs(Fraction(minimum)-exact[0]) <= Fraction(1,10**24)
                        and abs(Fraction(maximum)-exact[1]) <= Fraction(1,10**24), 'BOUNDED_SIMPLEX_OPTIMUM_MISMATCH')
                require(sum(lw) == 1 and sum(hw) == 1 and all(l <= w <= h for ws in (lw, hw) for l,w,h in zip(lo,ws,hi)), 'BOUNDED_SIMPLEX_WEIGHTS_INVALID')
    check('simplex_bounds_independent_vertex_oracle', 'options_decision_bounds', lp, case_count=40)
    check('simplex_infeasible_rejected', 'options_decision_bounds',
          lambda: reject(lambda: bounds.expectation_bounds([Decimal(1),Decimal(2)], [Decimal('.6')]*2, [Decimal('.8')]*2)))

    def lp_stress():
        n = 5000
        lo, hi, lw, hw = bounds.expectation_bounds([Decimal(i) for i in range(n)], [Decimal(0)]*n, [Decimal(1)]*n)
        require(lo == 0 and hi == n-1 and sum(lw) == 1 and sum(hw) == 1, 'STRESS_SIMPLEX_INVALID')
        return {'states': n}
    check('bounded_5000_state_simplex_stress', 'options_decision_bounds', lp_stress)

    def replay():
        p = entry_packet(); actual = entry.compare(p)
        expected = {'up': {'now':180., 'stage':150., 'wait':120.},
                    'dip': {'now':160., 'stage':200., 'wait':240.},
                    'terminal_touch': {'now':60., 'stage':90., 'wait':120.}}
        for sid, outcomes in expected.items():
            for policy, amount in outcomes.items():
                close(actual['scenarios'][sid][policy]['terminal_wealth'], amount)
        for policy in ('now','stage','wait'):
            close(actual['policies'][policy]['expected_terminal_wealth'],
                  .25*expected['up'][policy]+.5*expected['dip'][policy]+.25*expected['terminal_touch'][policy])
        changed = copy.deepcopy(p); changed['scenarios'][1]['observations'][-1]['price'] = 800.
        other = entry.compare(changed)
        for policy in ('now','stage','wait'):
            require(actual['scenarios']['dip'][policy]['events'][:-1] == other['scenarios']['dip'][policy]['events'][:-1], 'ENTRY_REPLAY_LOOKAHEAD')
        require(not actual['scenarios']['terminal_touch']['wait']['remainder_triggered'], 'TERMINAL_FILL_INVENTED')
    check('entry_case_replay_hand_ledger_and_no_lookahead', 'entry_policy_ev', replay, case_count=13)

    def unknown_ev():
        p = entry_packet();p['probability_basis'] = 'unknown'
        for s in p['scenarios']:s.pop('probability')
        actual = entry.compare(p)
        require(all('expected_terminal_wealth' not in row for row in actual['policies'].values()), 'UNKNOWN_WEIGHTS_GENERATE_EV')
    check('unknown_probabilities_remain_unknown', 'entry_policy_ev', unknown_ev)

    def costs_and_carry():
        p = entry_packet();p['fee_fraction'] = .01
        actual = entry.compare(p)
        with localcontext() as context:
            context.prec = 100
            expected = Decimal(120)/(Decimal(60)*Decimal('1.01'))*Decimal(90)*Decimal('.99')
        close(actual['scenarios']['up']['now']['terminal_wealth'], expected)
        p = entry_packet();p['cash_rate'] = .1
        close(entry.compare(p)['scenarios']['up']['wait']['terminal_wealth'], Decimal(120)*Decimal('1.1')**2)
    check('entry_fee_and_unfilled_cash_carry', 'entry_policy_ev', costs_and_carry, case_count=2)

    def vintages():
        p = vintage_packet(vintage.VERSION); before = vintage.calculate(p)
        p['observations'].append({**p['observations'][0], 'value': '999', 'vintage_id': 'future', 'available_at': '2027-01-01T00:00:00Z'})
        require(before == vintage.calculate(p), 'VINTAGE_FUTURE_LEAKAGE')
        p['observations'].reverse()
        require(before == vintage.calculate(p), 'VINTAGE_ORDER_DEPENDENT')
        p['as_of'] = '2026-04-30T20:00:00-04:00'
        require(before == vintage.calculate(p), 'VINTAGE_TIMEZONE_MISMATCH')
        p = vintage_packet(vintage.VERSION);p['observations'][0]['unit'] = 'currency:USD'
        reject(lambda: vintage.calculate(p))
        p = vintage_packet(vintage.VERSION);p['observations'] = []
        require(vintage.calculate(p)['coverage']['missing_as_of'] == 1, 'MISSING_VINTAGE_NOT_EXPLICIT')
        p['expected'][0]['period'] = {'start':'2027-01-01','end':'2027-03-31'}
        require(vintage.calculate(p)['coverage']['pending_period'] == 1, 'PENDING_PERIOD_NOT_EXPLICIT')
    check('vintage_point_in_time_and_units', 'cycle_vintage_checks', vintages, case_count=6)

    def cycle_arithmetic():
        p = cycle_packet(cycle.VERSION); actual = cycle.calculate(p)
        rows = actual.get('results')
        row = rows['balance'] if isinstance(rows, dict) else next(r for r in rows if r.get('id') == 'balance')
        for name, expected in [('supply_growth_fraction','.25'),('demand_growth_fraction','.25'),
                               ('demand_to_supply_start_ratio','.8'),('demand_to_supply_end_ratio','.8')]:
            require(Decimal(row[name]) == Decimal(expected), 'CYCLE_RATIO_MISMATCH', field=name)
        p['observations']['se']['available_at'] = '2027-01-01T00:00:00Z'
        reject(lambda: cycle.calculate(p))
        p = cycle_packet(cycle.VERSION);p['observations']['se']['unit'] = 'quantity:other_units'
        reject(lambda: cycle.calculate(p))
        p = cycle_packet(cycle.VERSION);p['observations']['se']['market_scope'] = 'Different universe'
        reject(lambda: cycle.calculate(p))
    check('cycle_supply_demand_exact_ratios', 'cycle_checks', cycle_arithmetic, case_count=7)

    # All network activity is outside run(): a coordinator supplies this saved
    # bounded public sample. Its source labels remain part of the receipt.
    public_path = Path(sample_path) if sample_path else DEFAULT_SAMPLE
    if public_path.is_file() and public_path.resolve().is_relative_to(boundary.resolve()) and not public_path.is_symlink():
        raw = public_path.read_bytes()
        require(len(raw) <= 1_000_000, 'PUBLIC_SAMPLE_TOO_LARGE')
        sample = json.loads(raw)
        result['public_sources'].append({k: sample.get(k) for k in
            ('source_url','metadata_url','retrieved_at','data_asof','adjustment','source_retrieval','sample_kind',
             'acquisition_route','independent_csv_crosscheck','source_capture_kind','source_capture_sha256')})
        result['public_sources'][-1]['saved_sample_sha256'] = hashlib.sha256(raw).hexdigest()
        def public_returns():
            rows = sample['rows'];require(2 <= len(rows) <= 1000, 'PUBLIC_SAMPLE_ROWS_INVALID')
            levels = [Decimal(row['value']) for row in rows]
            require(all(v.is_finite() and v > 0 for v in levels), 'PUBLIC_SAMPLE_LEVEL_INVALID')
            require([row['date'] for row in rows] == sorted(set(row['date'] for row in rows)), 'PUBLIC_SAMPLE_DATE_ORDER')
            with localcontext() as context:
                context.prec = 100
                returns = [b/a-1 for a,b in zip(levels,levels[1:])]
                expected = levels[-1]/levels[0]
            actual = lev.analyze_returns([float(r) for r in returns])
            close(actual['terminal_wealth'], expected)
            visible = {r['date']: r['value'] for r in sample.get('extraction_consistency_rows', [])}
            require(all(Decimal(visible[r['date']]) == Decimal(r['value']) for r in rows if r['date'] in visible), 'SOURCE_EXTRACTION_ROW_INCONSISTENCY')
            capture=Path(sample['source_capture_path'])
            if not capture.is_absolute():capture=ROOT/capture
            require(capture.resolve().is_relative_to(boundary.resolve()) and not capture.is_symlink()
                    and hashlib.sha256(capture.read_bytes()).hexdigest()==sample['source_capture_sha256'],
                    'PUBLIC_EXTRACT_CAPTURE_HASH_MISMATCH')
            return {'observations':len(rows), 'returns':len(returns), 'first_date':rows[0]['date'],
                    'last_date':rows[-1]['date'], 'terminal_ratio_reference':str(expected),
                    'retrieval_kind':sample['source_retrieval'], 'adjustment':sample['adjustment'],
                    'consistency_check':'Same primary-page extraction rows; no independent CSV corroboration',
                    'independent_csv_crosscheck':False}
        check('public_daily_close_return_telescoping', 'leveraged_funds', public_returns)
    else:
        skip('public_daily_close_return_telescoping', 'leveraged_funds', 'PUBLIC_SAMPLE_UNAVAILABLE')

    try:
        import numpy as np
        import exchange_calendars as xc
    except ImportError:
        skip('gbm_and_bootstrap', 'options_path_checks', 'OPTIONAL_NUMPY_CALENDAR_UNAVAILABLE')
    else:
        path = load_module('paths', LEGACY / 'workflow/options_path_checks.py', aliases)
        def deterministic_paths():
            p = path_packet(payoff, sigma=0.); actual = path.calculate(p); other = path.calculate(p)
            require(actual == other, 'PATH_SEED_NONDETERMINISTIC')
            t = actual['calendar']['trading_steps']/252
            expected = 100*math.exp(.08*t)
            for price in actual['terminal_stock_prices']:
                close(price, expected, atol=1e-10, rtol=2e-11)
            return {'paths':5000, 'steps':actual['calendar']['trading_steps'], 'analytic_terminal':expected}
        check('gbm_zero_vol_analytic_and_seed', 'options_path_checks', deterministic_paths)
        def moments():
            diagnostics = []
            for seed in (314159, 271828):
                p=path_packet(payoff,seed=seed);a=path.calculate(p);values=np.asarray(a['terminal_stock_prices']);t=a['calendar']['trading_steps']/252
                mean=100*math.exp(.08*t);variance=100**2*math.exp(2*.08*t)*math.expm1(.35**2*t)
                se=math.sqrt(variance/len(values));actual_mean=float(values.mean());actual_var=float(np.var(np.log(values/100),ddof=1));log_var=.35**2*t
                require(abs(actual_mean-mean)<=6*se, 'GBM_MEAN_OUTSIDE_6_MC_SE', seed=seed, actual=actual_mean,expected=mean,mc_se=se)
                require(abs(actual_var-log_var)<=.12*log_var, 'GBM_LOG_VARIANCE_MISMATCH',seed=seed,actual=actual_var,expected=log_var)
                diagnostics.append({'seed':seed,'mean_error_mc_se':abs(actual_mean-mean)/se,'relative_log_variance_error':abs(actual_var-log_var)/log_var})
            return {'diagnostics':diagnostics, 'interpretation':'Numerical sampler checks conditional on fixed assumptions, not calibrated forecasts.'}
        check('gbm_analytic_moments_two_fixed_seeds', 'options_path_checks', moments, case_count=2)
        def resource_reject():
            p=path_packet(payoff,paths=100000);p['payoff_packet']['strategy']['long_leg'].update(expiry='2027-11-19',contract_id='SYNTH271119C00100000')
            reject(lambda:path.calculate(p))
        check('pathstep_budget_rejected', 'options_path_checks', resource_reject)
        def bootstrap():
            try:
                import arch
            except ImportError:
                return {'skipped_dependency':'arch'}
            require(arch.__version__=='8.0.0', 'ARCH_VERSION_UNSUPPORTED',actual_version=arch.__version__)
            p=path_packet(payoff,paths=1000);p['simulation'].update(method='stationary_bootstrap',sigma=None,annual_arithmetic_drift=None,drift_treatment='raw_empirical',block_size=4)
            calendar=xc.get_calendar('XNYS');dates=calendar.sessions_in_range('2026-07-01','2026-10-23')
            p['history']={'source_ref':'synthetic:constant-log-returns','observed_at':'2026-10-23T20:01:00Z','returns':[{'session':d.date().isoformat(),'log_return':.001} for d in dates]}
            actual=path.calculate(p);require(actual==path.calculate(p),'BOOTSTRAP_SEED_NONDETERMINISTIC')
            expected=100*math.exp(.001*actual['calendar']['trading_steps'])
            for price in actual['terminal_stock_prices']:close(price,expected,atol=1e-10,rtol=2e-11)
            missing=copy.deepcopy(p);missing['history']['returns'].pop(10);reject(lambda:path.calculate(missing))
            p['history']['observed_at']='2026-10-24T00:00:00Z';reject(lambda:path.calculate(p))
            return {'synthetic_history':True,'history_returns':len(dates),'paths':1000,'constant_log_return':.001,'analytic_terminal':expected}
        try:
            import arch
        except ImportError:
            skip('bootstrap_constant_path_and_no_lookahead', 'options_path_checks', 'OPTIONAL_ARCH_UNAVAILABLE')
        else:
            check('bootstrap_constant_path_and_no_lookahead', 'options_path_checks', bootstrap)

    # Root authorized these isolated corrections after the original witnesses
    # failed. Keep the same criteria and the failed baseline rows above.
    corrected_path = ROOT / 'shared/calculation/operators/paths.py'
    if corrected_path.is_file():
        corrected = load_module('corrected_paths', corrected_path)
        def corrected_reference_cases():
            rng = random.Random(712)
            for n in (1,2,10,30,100):
                for _ in range(20):
                    returns=[rng.randint(-400,400)/10000 for _ in range(n)]
                    expected,dd=decimal_path(returns);actual=corrected.analyze_returns(returns)
                    close(actual['terminal_wealth'],expected);close(actual['max_drawdown'],dd)
                    close(corrected.analyze_returns(list(reversed(returns)))['terminal_wealth'],expected)
            require(corrected.analyze_returns([.1,-1,99])['terminal_wealth']==0,'CORRECTED_ACTUAL_RUIN_NOT_ABSORBING')
            for value in [float('nan'),float('inf'),-1.01]:reject(lambda value=value:corrected.analyze_returns([value]))
        check('corrected_compounding_same_decimal_oracle', 'operators.paths', corrected_reference_cases,case_count=204)
        def corrected_underflow():
            try:corrected.analyze_returns([-.999]*200)
            except corrected.ArithmeticDomainError as error:
                require(error.code=='FLOAT_REPRESENTATION_UNDERFLOW','CORRECTED_UNDERFLOW_WRONG_REASON',actual=error.code)
                return {'explicit_domain_rejection':error.code,'exact_positive_wealth':'1E-600'}
            raise CheckFailure('CORRECTED_FALSE_RUIN_NOT_REJECTED')
        check('corrected_underflow_same_witness', 'operators.paths', corrected_underflow)
        def corrected_quantile():
            for q,expected in [(.5,0.),(.5+5e-15,1.),(0.,0.),(1.,1.)]:
                require(corrected.weighted_quantile([0.,1.],[.5,.5],q)==expected,'CORRECTED_EMPIRICAL_QUANTILE_MISMATCH',probability=q,expected=expected)
            for q,expected in [(0.,-2.),(.2,-2.),(.3,4.),(.5,4.),(.9,100.),(1.,100.)]:
                require(corrected.weighted_quantile([-2.,4.,100.],[.2,.3,.5],q)==expected,'CORRECTED_ORDINARY_QUANTILE_MISMATCH',probability=q,expected=expected)
        check('corrected_quantile_same_boundary_and_ordinary_witnesses', 'operators.paths', corrected_quantile,case_count=10)
        def corrected_tail():
            for values,weights,tail,expected in [([0.,100.],[0.,1.],1e-15,100.),([10.,20.,100.],[.02,.03,.95],.04,15.),([0.,100.],[0.,1.],1.,100.)]:
                close(corrected.lower_tail_mean(values,weights,tail),expected)
        check('corrected_tail_same_zero_weight_witness', 'operators.paths', corrected_tail,case_count=3)
        def corrected_expanded_frequency_oracle():
            rng=random.Random(852)
            for _ in range(20):
                values=[rng.randint(-100,100) for _ in range(5)];counts=[10,20,30,40,0]
                expanded=sorted(v for v,n in zip(values,counts) for _ in range(n))
                weights=[Decimal(n)/100 for n in counts]
                for k in (1,5,50,95,100):
                    q=Decimal(k)/100
                    require(corrected.weighted_quantile(values,weights,q)==expanded[k-1], 'CORRECTED_EXPANDED_CDF_MISMATCH')
                    expected=Fraction(sum(expanded[:k]),k)
                    close(corrected.lower_tail_mean(values,weights,q),expected)
        check('corrected_quantile_tail_expanded_frequency_oracle', 'operators.paths',corrected_expanded_frequency_oracle,case_count=200)
        def corrected_stress():
            rows=[.000001,-.000001]*50000
            with localcontext() as context:
                context.prec=100;expected=(Decimal(1)-Decimal('.000001')**2)**50000
            actual=corrected.analyze_returns(rows);close(actual['terminal_wealth'],expected)
            return {'resets':len(rows),'decimal_rounded':actual['decimal_rounded']}
        check('corrected_bounded_100k_reset_stress', 'operators.paths', corrected_stress)
        def corrected_owned_decimal_context():
            returns=['.123456789123456789','-.023456789123456789','.333333333333333333']
            expected=corrected.analyze_returns(returns,years='.7')
            with localcontext() as hostile:
                hostile.prec=2;hostile.rounding=ROUND_DOWN;hostile.Emin=-10;hostile.Emax=10
                hostile.traps[Inexact]=True;hostile.traps[Rounded]=True
                hostile.flags[Inexact]=True
                def snapshot():
                    return (hostile.prec,hostile.rounding,hostile.Emin,hostile.Emax,
                            dict(hostile.traps),dict(hostile.flags))
                before=snapshot()
                actual=corrected.analyze_returns(returns,years='.7')
                require(actual==expected,'CORRECTED_AMBIENT_CONTEXT_AFFECTS_RESULT')
                require(snapshot()==before,'CORRECTED_MUTATES_CALLER_DECIMAL_CONTEXT')
            return {'hostile_precision':2,'hostile_rounding':'ROUND_DOWN',
                    'hostile_inexact_rounded_traps':True,'caller_state_unchanged':True}
        check('corrected_owned_decimal_context_and_nonmutation','operators.paths',corrected_owned_decimal_context)
        def corrected_weighted_vector_budget():
            class Endless:
                def __init__(self):self.consumed=0
                def __iter__(self):return self
                def __next__(self):self.consumed+=1;return 1
            for function in (corrected.weighted_quantile,corrected.lower_tail_mean):
                for field in ('values','weights'):
                    endless=Endless()
                    values=endless if field=='values' else [0]
                    weights=endless if field=='weights' else [1]
                    try:function(values,weights,.5)
                    except corrected.ArithmeticDomainError as error:
                        require(error.code=='WEIGHTED_VECTOR_BUDGET_EXCEEDED',
                                'CORRECTED_VECTOR_WRONG_REJECTION',actual=error.code)
                        require(endless.consumed==corrected.MAX_WEIGHTED_ROWS+1,
                                'CORRECTED_VECTOR_CAPTURE_UNBOUNDED',actual=endless.consumed)
                    else:raise CheckFailure('CORRECTED_VECTOR_BUDGET_NOT_ENFORCED')
            values=list(range(corrected.MAX_WEIGHTED_ROWS))
            weights=[0]*(corrected.MAX_WEIGHTED_ROWS-1)+[1]
            require(corrected.weighted_quantile(values,weights,.5)==corrected.MAX_WEIGHTED_ROWS-1,
                    'CORRECTED_EXACT_VECTOR_LIMIT_REJECTED')
            require(corrected.lower_tail_mean(values,weights,.5)==corrected.MAX_WEIGHTED_ROWS-1,
                    'CORRECTED_EXACT_TAIL_VECTOR_LIMIT_REJECTED')
            return {'weighted_vector_limit':corrected.MAX_WEIGHTED_ROWS,
                    'overflow_detection_consumes_at_most_limit_plus_one':True}
        check('corrected_bounded_weighted_iterables','operators.paths',corrected_weighted_vector_budget,case_count=6)

    counts = {name:sum(row['status']==name for row in result['checks']) for name in ('passed','failed','skipped')}
    counts['total']=len(result['checks']);counts['input_cases']=sum(row.get('case_count',0) for row in result['checks'])
    result.update(status='failed' if counts['failed'] else ('partial' if counts['skipped'] else 'passed'),counts=counts,
                  elapsed_seconds=round(time.monotonic()-started,6),
                  protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
                  generated_at=datetime.now(timezone.utc).isoformat())
    corrected_rows=[row for row in result['checks'] if row['module']=='operators.paths']
    result['corrected_operator_status']=('failed' if any(row['status']=='failed' for row in corrected_rows)
                                         else 'passed' if corrected_rows else 'not_evaluated')
    output=out/'paths-result.json';result['evidence_paths']=[str(output.relative_to(ROOT))]
    output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result
