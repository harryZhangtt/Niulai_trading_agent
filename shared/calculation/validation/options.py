"""Offline numerical evaluation of copied option diagnostics using public inputs.

Source acquisition is deliberately absent. The optional public capture is inert
JSON data. This module never reads account configuration, credentials or mail.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
LEGACY = ROOT / 'shared/calculation/legacy/workflow'
PROTOCOL = Path(__file__).with_name('options_protocol.md')
DEFAULT_SAMPLE = ROOT / '.job-runtime/calculation/validation/options/public-cboe-aapl.json'


def _targets():
    old = list(sys.path)
    try:
        sys.path.insert(0, str(LEGACY))
        modules = [importlib.import_module(name) for name in
                   ('options_scenario_checks', 'options_surface_checks', 'options_american_checks')]
        if any(Path(m.__file__).resolve().parent != LEGACY for m in modules):
            raise ValueError('WRONG_TARGET_ORIGIN')
        return modules
    finally:
        sys.path[:] = old


def _reference(mp, kind, S, K, T, r, q, sigma, digits=80):
    with mp.workdps(digits):
        S, K, T, r, q, sigma = [mp.mpf(str(x)) for x in (S, K, T, r, q, sigma)]
        if not T:
            return {'price': float(max(S-K, 0) if kind == 'call' else max(K-S, 0))}
        N = lambda x: mp.erfc(-x/mp.sqrt(2))/2
        d1 = (mp.log(S/K)+(r-q+sigma*sigma/2)*T)/(sigma*mp.sqrt(T))
        d2 = d1-sigma*mp.sqrt(T)
        asset, bond = S*mp.exp(-q*T), K*mp.exp(-r*T)
        density = mp.exp(-d1*d1/2)/mp.sqrt(2*mp.pi)
        if kind == 'call':
            value = asset*N(d1)-bond*N(d2)
            delta = mp.exp(-q*T)*N(d1)
            theta = -asset*density*sigma/(2*mp.sqrt(T))+q*asset*N(d1)-r*bond*N(d2)
            rho = T*bond*N(d2)/100
        else:
            value = bond*N(-d2)-asset*N(-d1)
            delta = -mp.exp(-q*T)*N(-d1)
            theta = -asset*density*sigma/(2*mp.sqrt(T))-q*asset*N(-d1)+r*bond*N(-d2)
            rho = -T*bond*N(-d2)/100
        return {name: float(x) for name, x in {
            'price': max(value, 0), 'delta': delta,
            'gamma': mp.exp(-q*T)*density/(S*sigma*mp.sqrt(T)),
            'vega_per_vol_point': asset*density*mp.sqrt(T)/100,
            'theta_per_calendar_day': theta/365, 'rho_per_rate_point': rho}.items()}


def _crr(kind, S, K, T, r, q, sigma, steps, american=True):
    """Independent recombining CRR tree, without QuantLib or target formulas."""
    import numpy as np
    dt = T/steps
    u, d = math.exp(sigma*math.sqrt(dt)), math.exp(-sigma*math.sqrt(dt))
    probability = (math.exp((r-q)*dt)-d)/(u-d)
    if not 0 <= probability <= 1:
        raise ValueError('CRR_PROBABILITY_OUTSIDE_DOMAIN')
    discount = math.exp(-r*dt)
    j = np.arange(steps+1)
    stock = S*np.exp((2*j-steps)*math.log(u))
    values = np.maximum(stock-K, 0) if kind == 'call' else np.maximum(K-stock, 0)
    for n in range(steps-1, -1, -1):
        values = discount*((1-probability)*values[:-1]+probability*values[1:])
        if american:
            stock = S*np.exp((2*np.arange(n+1)-n)*math.log(u))
            intrinsic = np.maximum(stock-K, 0) if kind == 'call' else np.maximum(K-stock, 0)
            values = np.maximum(values, intrinsic)
    return float(values[0])


def _reference_iv(mp, kind, S, K, T, r, q, premium):
    # Independent bracket/bisection calls only the mpmath reference, never target.
    low, high = 1e-12, 10.
    for _ in range(90):
        mid = (low+high)/2
        value = _reference(mp, kind, S, K, T, r, q, mid)['price']
        if value < premium:
            low = mid
        else:
            high = mid
    return (low+high)/2


class _Recorder:
    def __init__(self):
        self.groups = {}
        self.findings = []

    def check(self, group, condition, detail=None):
        row = self.groups.setdefault(group, {'id': group, 'passed': 0, 'failed': 0})
        row['passed' if condition else 'failed'] += 1
        if not condition:
            self.findings.append({'check': group, 'severity': 'failure', **(detail or {})})

    def skip(self, group, reason):
        self.groups[group] = {'id': group, 'passed': 0, 'failed': 0, 'skipped': 1, 'reason': reason}


def _packet(kind='put', S=100., K=100., r=.05, q=0., sigma=.2, exercise='american'):
    return {'version': 1, 'kind': kind, 'strike': K, 'exercise': exercise,
            'as_of': '2026-10-30', 'expiry': '2027-10-30', 'spot': S,
            'rate': r, 'yield': q, 'volatility': sigma,
            'units': {'price': 'USD_per_share', 'rate': 'annual_continuous_decimal',
                      'yield': 'annual_continuous_decimal', 'volatility': 'annual_decimal'},
            'grids': [100, 200, 400], 'tolerance_per_share': .005}


def run(output_dir, sample_path=None):
    started = time.perf_counter()
    output_dir = Path(output_dir).resolve()
    if not output_dir.is_relative_to(ROOT / '.job-runtime/calculation'):
        raise ValueError('OUTPUT_OUTSIDE_CALCULATION_STATE')
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    scenario, surface, american = _targets()
    rec = _Recorder()
    versions = {}
    for package in ('mpmath', 'QuantLib', 'numpy'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    try:
        import mpmath as mp
    except ImportError:
        rec.skip('independent_analytic_reference', 'mpmath_unavailable')
        mp = None

    maxima = {'price_absolute_error': 0., 'greek_absolute_error': 0., 'iv_volatility_error': 0.}
    cases = []
    for scale in (.01, 1., 100., 10000.):
        for money in (.5, .9, 1., 1.1, 2.):
            for T in (1/365, .25, 1., 10.):
                for sigma in (.03, .2, 1., 3.):
                    j = len(cases)
                    cases.append((scale*money, scale, T, (-.05, 0., .05)[j % 3],
                                  (0., .02, .2)[(j//3) % 3], sigma))
    cases += [(S, K, T, r, q, sigma) for S, K, T, r, q, sigma in [
        (1e-12, 1e-12, 1e-12, 0., 0., 1e-12),
        (1e12, 1e12, 1e-12, 0., 0., 1e-12),
        (1e12, 1e-12, 30., -1., 1., 10.),
        (1e-12, 1e12, 30., 1., -1., 10.),
        (100., 100., 1e-9, .05, 0., 1e-8),
        (100., 100., 30., -1., 1., 10.)]]
    if mp:
        for case in cases:
            S, K, T, r, q, sigma = case
            tolerance = max(1e-9, 3e-14*max(S, K))
            got = {}
            for kind in ('call', 'put'):
                expected = _reference(mp, kind, *case)
                actual = scenario.bsm(kind, *case)
                got[kind] = actual
                error = abs(actual['price']-expected['price'])
                maxima['price_absolute_error'] = max(maxima['price_absolute_error'], error)
                if actual['price'] == 0 and expected['price'] > 1e-12:
                    rec.findings.append({'check': 'tail_value_cancellation', 'severity': 'warning',
                                         'kind': kind, 'inputs': list(case),
                                         'target_price': 0., 'reference_price': expected['price'],
                                         'absolute_error': error, 'absolute_tolerance': tolerance,
                                         'meaning': 'Positive model value lost to floating-point cancellation; within frozen absolute budget, not relative-accuracy certification.'})
                rec.check('bsm_high_precision_price', math.isfinite(actual['price']) and error <= tolerance,
                          {'kind': kind, 'inputs': list(case), 'absolute_error': error, 'tolerance': tolerance})
                if .01 <= S <= 10000 and .01 <= K <= 10000 and T >= 1/365 and sigma >= .03:
                    for key in ('delta', 'gamma', 'vega_per_vol_point', 'theta_per_calendar_day', 'rho_per_rate_point'):
                        error = abs(actual[key]-expected[key])
                        maxima['greek_absolute_error'] = max(maxima['greek_absolute_error'], error)
                        tol = 1e-9+2e-8*abs(expected[key])
                        rec.check('analytic_greeks', math.isfinite(actual[key]) and error <= tol,
                                  {'field': key, 'kind': kind, 'inputs': list(case), 'absolute_error': error, 'tolerance': tol})
                # Only well-conditioned, bracket-supported cases have identifiable IV.
                intrinsic_bound = scenario.bounds(kind, S, K, T, r, q)[0]
                if (.03 <= sigma <= 2 and T >= 1/365 and
                        expected['vega_per_vol_point']*100 > 1e-5 and
                        expected['price']-intrinsic_bound > 1e-7):
                    try:
                        recovered = scenario.implied_vol(kind, S, K, T, r, q, expected['price'])
                        error = abs(recovered-sigma)
                        maxima['iv_volatility_error'] = max(maxima['iv_volatility_error'], error)
                        rec.check('identifiable_iv_roundtrip', error <= 2e-6,
                                  {'kind': kind, 'inputs': list(case), 'volatility_error': error})
                    except ValueError as exc:
                        rec.check('identifiable_iv_roundtrip', False,
                                  {'kind': kind, 'inputs': list(case), 'error': str(exc)})
                if .01 <= S <= 10000 and .01 <= K <= 10000 and kind == 'call':
                    scaled = scenario.bsm(kind, 2*S, 2*K, T, r, q, sigma)['price']
                    rec.check('linear_homogeneity', abs(scaled-2*actual['price']) <= 2*tolerance,
                              {'inputs': list(case), 'absolute_error': abs(scaled-2*actual['price'])})
            parity = got['call']['price']-got['put']['price']-(S*math.exp(-q*T)-K*math.exp(-r*T))
            rec.check('put_call_parity', abs(parity) <= 2*tolerance,
                      {'inputs': list(case), 'absolute_error': abs(parity), 'tolerance': 2*tolerance})
        for case in ((100., 100., 1., .05, .02, .2), (1e12, 1e12, 1e-12, 0., 0., 1e-12)):
            a = _reference(mp, 'call', *case, digits=80)['price']
            z = _reference(mp, 'call', *case, digits=120)['price']
            rec.check('reference_precision_escalation', a == z, {'inputs': list(case), '80digit': a, '120digit': z})
        for kind, S, K, T, r, q, vol in [('call', 100., 100., .25, .04, .01, .2),
                                       ('put', 100., 110., 1., -.02, .03, .7),
                                       ('call', 347.35, 350., 2., .04, 0., 1.2)]:
            premium = _reference(mp, kind, S, K, T, r, q, vol)['price']
            actual = scenario.implied_vol(kind, S, K, T, r, q, premium)
            independent = _reference_iv(mp, kind, S, K, T, r, q, premium)
            rec.check('independent_iv_bisection', abs(actual-independent) <= 2e-6,
                      {'kind': kind, 'absolute_volatility_error': abs(actual-independent)})

    for kind in ('call', 'put'):
        expired = scenario.bsm(kind, 80., 100., 0., .05, .02, .2)
        rec.check('expiry_payoff', expired['price'] == (0 if kind == 'call' else 20)
                  and expired['delta'] is None)
    for bad in (True, False, float('nan'), float('inf'), -float('inf')):
        try:
            scenario.bsm('call', bad, 100., 1., .05, 0., .2)
            rejected = False
        except ValueError:
            rejected = True
        rec.check('invalid_input_rejection', rejected, {'input_kind': type(bad).__name__})
    invalid_american = []
    p = _packet(); p['units']['price'] = 'USD_per_contract'; invalid_american.append(p)
    p = _packet(); p['spot'] = float('nan'); invalid_american.append(p)
    p = _packet(); p['grids'] = [100, 200, 401]; invalid_american.append(p)
    p = _packet(); p['yield'] = .02
    p['dividends'] = [{'date': '2027-03-15', 'cash_per_share': 1.}]; invalid_american.append(p)
    p = _packet(); p['contract_id'] = 'ABC271030C00100000'; invalid_american.append(p)
    for p in invalid_american:
        try:
            american.validate(p)
            rejected = False
        except ValueError:
            rejected = True
        rec.check('american_malformed_terms_rejected', rejected)

    # Independent linear surface oracle; no target-produced prices seed the surface.
    slices = {1.: [{'log_moneyness': -.2, 'variance_mid': .04},
                    {'log_moneyness': .2, 'variance_mid': .12}],
              2.: [{'log_moneyness': -.1, 'variance_mid': .12},
                    {'log_moneyness': .1, 'variance_mid': .20}]}
    for T, k, expected in [(1., 0., .08), (2., 0., .16), (1.5, 0., .12)]:
        rec.check('surface_linear_reference', abs(surface.surface(slices, T, k)-expected) <= 1e-14)
    for T, k in ((.9, 0.), (2.1, 0.), (1.5, .15)):
        rec.check('surface_no_extrapolation', surface.surface(slices, T, k) is None)
    for rows, expected in [([{'strike': 90, 'mid': 10}, {'strike': 100, 'mid': 11}], 'call_price_increases_with_strike'),
                           ([{'strike': 90, 'mid': 30}, {'strike': 100, 'mid': 10}], 'vertical_spread_exceeds_discounted_width'),
                           ([{'strike': 90, 'mid': 20}, {'strike': 100, 'mid': 18}, {'strike': 110, 'mid': 10}], 'negative_discrete_butterfly')]:
        rec.check('surface_invalid_static_detection', expected in surface.price_checks(rows, 1.))
    if mp:
        p = {'version': surface.VERSION, 'symbol': 'ABC', 'valuation_at': '2026-10-30T20:00:00Z',
             'spot': 100., 'rate': .04, 'yield': .01, 'mode': 'historical_diagnostic',
             'policy': {'max_age_seconds': 60, 'max_skew_seconds': 10, 'max_relative_spread': .5},
             'contracts': []}
        for expiry in ('2027-01-15T21:00:00Z', '2027-04-16T20:00:00Z'):
            t = (datetime.fromisoformat(expiry.replace('Z', '+00:00'))-
                 datetime.fromisoformat(p['valuation_at'].replace('Z', '+00:00'))).total_seconds()/(365*86400)
            for strike in (80., 90., 100., 110., 120.):
                price = _reference(mp, 'call', 100., strike, t, .04, .01, .5)['price']
                p['contracts'].append({'contract_id': 'ABC'+expiry[2:10].replace('-', '')+'C'+f'{round(strike*1000):08d}',
                                       'expiry_at': expiry, 'strike': strike, 'bid': price*.995, 'ask': price*1.005,
                                       'quote_at': None, 'source_ref': 'synthetic:independent-mpmath-80dps'})
        fitted = surface.calculate(p)
        rec.check('surface_independent_nodes', len(fitted['nodes']) == 10 and
                  all(abs(n['iv_mid']-.5) <= 2e-6 for n in fitted['nodes']),
                  {'coverage': fitted['coverage']})
        rec.check('surface_no_false_certification', not fitted['arbitrage_free_certified'] and
                  not fitted['executable'] and fitted['forecast_probability'] is None)

    sources = []
    sample_path = Path(sample_path) if sample_path else DEFAULT_SAMPLE
    if (sample_path.is_symlink() or
            not sample_path.resolve().is_relative_to(ROOT / '.job-runtime/calculation')):
        raise ValueError('PUBLIC_SAMPLE_OUTSIDE_CALCULATION_STATE')
    if sample_path.is_file():
        raw = sample_path.read_bytes()
        if len(raw) > 100000:
            raise ValueError('PUBLIC_SAMPLE_TOO_LARGE')
        sample = json.loads(raw)
        if sample.get('source_url') != 'https://cdn.cboe.com/api/global/delayed_quotes/options/AAPL.json':
            raise ValueError('PUBLIC_SAMPLE_SOURCE_NOT_ALLOWED')
        sources.append({k: sample.get(k) for k in ('source_url', 'source_page', 'retrieved_at', 'data_asof_raw',
                        'data_asof_timezone', 'delay_status', 'raw_payload_sha256', 'transform_lineage')})
        sources[-1]['capture_sha256'] = hashlib.sha256(raw).hexdigest()
        for row in sample['contracts'][:12]:
            sane = 0 < row['bid'] <= row['ask'] and row['strike'] > 0
            rec.check('public_quote_sanity', sane, {'contract': row['option']})
            terms = surface.parse_contract_id(row['option'])
            rec.check('public_contract_identity', terms['root'] == 'AAPL'
                      and terms['right'] == row['kind']
                      and terms['expiry'].isoformat() == row['expiry']
                      and float(terms['strike']) == row['strike'], {'contract': row['option']})
            if mp:
                # The scenario volatility/rates are assumptions, NOT vendor calibration.
                # Provider date only: timestamp timezone and intraday cutoff unknown.
                T = (date.fromisoformat(row['expiry'])-
                     date.fromisoformat(sample['data_asof_raw'][:10])).days/365
                case = (sample['spot'], row['strike'], T, .04, .01, .30)
                actual = scenario.bsm(row['kind'], *case)
                expected = _reference(mp, row['kind'], *case)
                tol = max(1e-9, 3e-14*max(case[0], case[1]))
                rec.check('public_contract_scale_numeric_crosscheck', abs(actual['price']-expected['price']) <= tol,
                          {'contract': row['option'], 'absolute_error': abs(actual['price']-expected['price'])})
    else:
        rec.skip('public_sample', 'bounded_public_capture_missing')

    if versions['QuantLib'] == '1.44' and versions['numpy'] and mp:
        import QuantLib as ql
        previous_date = str(ql.Settings.instance().evaluationDate)
        for packet in [_packet(), _packet(kind='call'), _packet(S=80., K=100.), _packet(kind='call', q=.08)]:
            try:
                actual = american.calculate(packet)['base']['price']
                args = (packet['kind'], packet['spot'], packet['strike'], 1., packet['rate'], packet['yield'], packet['volatility'])
                a = _crr(*args, 1599)
                b = _crr(*args, 1600)
                coarse = _crr(*args, 800)
                expected = (a+b)/2
                rec.check('american_independent_crr', abs(actual-expected) <= .02 and abs(b-coarse) <= .02,
                          {'kind': packet['kind'], 'spot': packet['spot'], 'yield': packet['yield'],
                           'target': actual, 'crr_reference': expected, 'crr_grid_difference': abs(b-coarse)})
                if packet['kind'] == 'call' and packet['yield'] == 0:
                    expected = _reference(mp, *args)['price']
                    rec.check('american_nondividend_analytic_identity', abs(actual-expected) <= .005,
                              {'target': actual, 'reference': expected})
            except ValueError as exc:
                rec.check('american_independent_crr', False, {'error': str(exc)})
        rec.check('quantlib_date_restored', str(ql.Settings.instance().evaluationDate) == previous_date)
    else:
        rec.skip('american_independent_crr', 'requires_QuantLib1.44_numpy_mpmath')

    failed = sum(v['failed'] for v in rec.groups.values())
    skipped = sum(v.get('skipped', 0) for v in rec.groups.values())
    result = {'component': 'options', 'status': 'failed' if failed else ('partial' if skipped else 'passed'),
              'protocol_sha256': hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
              'passed': sum(v['passed'] for v in rec.groups.values()), 'failed': failed, 'skipped': skipped,
              'checks': list(rec.groups.values()), 'findings': rec.findings, 'maxima': maxima,
              'modules_exercised': [Path(m.__file__).name for m in (scenario, surface, american)],
              'sources': sources, 'dependency_versions': versions,
              'elapsed_seconds': round(time.perf_counter()-started, 4),
              'generated_at': datetime.now(timezone.utc).isoformat(),
              'limitations': ['Public delayed market samples supply real contract scales; assumptions are not calibrated to quotes.',
                              'Sampled surfaces do not establish global arbitrage freedom.',
                              'mpmath and finite CRR trees are numerical references, not formal proofs.',
                              'No discrete cash-dividend independent American oracle is claimed.',
                              'Scheduled Codex acceptance and result email are root-owned and separate.']}
    path = output_dir / 'options-result.json'
    path.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    path.chmod(0o600)
    return result


if __name__ == '__main__':
    result = run(ROOT / '.job-runtime/calculation/validation/options/run')
    print(json.dumps({k: result[k] for k in ('component', 'status', 'passed', 'failed', 'skipped', 'elapsed_seconds')}))
