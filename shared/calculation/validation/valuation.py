"""Network-free independent rational validation of the inactive calculation copy.

Source acquisition is separate. All generated inputs are synthetic or the saved
public issuer rows. This module never reads accounts, credentials or portfolios.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import (Decimal as D, DecimalException, Context, Inexact, InvalidOperation,
                     DivisionByZero, Overflow, localcontext, ROUND_DOWN, ROUND_HALF_EVEN)
from fractions import Fraction as F
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'shared/calculation'
STATE = ROOT / '.job-runtime/calculation/validation'
CAPTURE = STATE / 'valuation'
DEFAULT_SAMPLE = STATE / 'valuation/public_sample.json'
SAMPLE_SHA256 = '5826c3f3e7e05b86f4a9cc0f87dd95954ef4851ff33ff3074b03911d4d8a6082'
SOURCE_SHA256 = '513b5a3161adde8c8b2e7d0edc6723d34e9c652cc47d4ab43e6eeb84a84370d0'
PROTOCOL = Path(__file__).with_name('valuation_protocol.md')
VERSION = '2026-10-31-valuation-validation-1'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _capture_read(path, maximum):
    """Read only a bounded, non-symlink public-capture file, before opening it."""
    raw_path = Path(path)
    if '..' in raw_path.parts:
        raise ValueError('PUBLIC_CAPTURE_PATH_INVALID')
    path = Path(os.path.abspath(raw_path))
    if not path.is_relative_to(CAPTURE) or not path.resolve().is_relative_to(CAPTURE.resolve()):
        raise ValueError('PUBLIC_CAPTURE_OUTSIDE_BOUNDARY')
    for ancestor in [path, *path.parents]:
        if ancestor == ROOT.parent:
            break
        if ancestor.is_symlink():
            raise ValueError('PUBLIC_CAPTURE_SYMLINK')
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('PUBLIC_CAPTURE_SIZE_INVALID')
    with path.open('rb') as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError('PUBLIC_CAPTURE_SIZE_INVALID')
    return path, value


def _load(relative):
    path = BASE / relative
    spec = importlib.util.spec_from_file_location('_validation_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rational(value):
    return F(str(value))


def _decimal(value):
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN,
                              traps=[InvalidOperation, DivisionByZero, Overflow])):
        return D(value.numerator) / D(value.denominator) if isinstance(value, F) else D(str(value))


def _pv(flows, rate):
    # Independently exact rational discount factors, not Decimal accumulation.
    discount = F(1) / (F(1) + _rational(rate))
    return sum((_rational(cf) * discount ** t for t, cf in enumerate(flows, 1)), F(0))


def _annuity(cashflow, rate, terms):
    r = _rational(rate)
    return _rational(cashflow) * terms if not r else _rational(cashflow) * (1 - (1 + r) ** -terms) / r


def _close(actual, expected):
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN,
                              traps=[InvalidOperation, DivisionByZero, Overflow])):
        a, e = _decimal(actual), _decimal(expected)
        return a.is_finite() and abs(a - e) <= max(D('1e-18'), abs(e) * D('1e-24'))


def _plain(value):
    if isinstance(value, F):
        # Keep huge exact references bounded without changing Python's global
        # integer-string safety limit or reducing oracle/comparison precision.
        return {'decimal80': str(_decimal(value)), 'exact_rational_reference': True,
                'numerator_bits': value.numerator.bit_length(),
                'denominator_bits': value.denominator.bit_length()}
    if isinstance(value, D):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(x) for x in value]
    return value


def _totals_case(values=('10', '-4'), nav='100', cash='20', currency='USD'):
    # All identifiers deliberately synthetic; no broker/account fixtures loaded.
    holdings = {'ok': True, 'accountIdentityChecked': True,
                'sourceReadStatus': 'complete', 'accountRef': 'synthetic-account',
                'queryCompletedAt': '2026-10-30T20:00:00Z',
                'positions': [{'contractId': str(i), 'currency': currency, 'marketValue': v}
                              for i, v in enumerate(values)]}
    assets = {'ok': True, 'sourceReadStatus': 'complete', 'accountIdentityChecked': True,
              'accountRef': 'synthetic-account', 'queryCompletedAt': '2026-10-30T20:00:00Z',
              'summary': {'currency': 'USD', 'amounts': {'netLiquidation': nav, 'cash': cash}}}
    return ({'accounts': [{'accountRef': 'synthetic-account', 'currency': 'USD', 'metrics': {}}]},
            {'evidence': {'holdings': {'result': holdings}, 'current_assets': {'result': assets}}}, [])


def run(output_dir, sample_path=None, variant='both'):
    """Run frozen checks and return a JSON-safe report; network access is absent."""
    out = Path(output_dir).resolve()
    if not out.is_relative_to(STATE.resolve()):
        raise ValueError('VALIDATION_OUTPUT_OUTSIDE_BOUNDARY')
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    if variant == 'both':
        baseline = run(out / 'legacy', sample_path=sample_path, variant='legacy')
        maintained = run(out / 'maintained', sample_path=sample_path, variant='maintained')
        result = {'version': VERSION, 'variant': 'baseline_and_maintained',
                  'status': maintained['status'],
                  'cases_total': maintained['cases_total'], 'cases_passed': maintained['cases_passed'],
                  'cases_failed': maintained['cases_failed'],
                  'baseline_cases_total': baseline['cases_total'], 'baseline_cases_failed': baseline['cases_failed'],
                  'baseline_status': baseline['status'], 'baseline_findings': baseline['findings'],
                  'findings': maintained['findings'], 'groups': maintained['groups'],
                  'baseline_groups': baseline['groups'],
                  'modules_exercised': maintained['modules_exercised'],
                  'public_sample': maintained['public_sample'],
                  'protocol_sha256': maintained['protocol_sha256'], 'runner_sha256': _sha(__file__),
                  'candidate_hashes': maintained['candidate_hashes'],
                  'baseline_candidate_hashes': baseline['candidate_hashes'],
                  'workload_timings': maintained['workload_timings'],
                  'evidence_paths': baseline['evidence_paths'] + maintained['evidence_paths'],
                  'claims': 'Maintained scoped arithmetic passes; original eight baseline failures remain retained. No fair-value or prediction certification.',
                  'scheduled_acceptance': 'pending_root_scheduled_codex_run_and_verified_email',
                  'generated_at': datetime.now(timezone.utc).isoformat()}
        with (out / 'valuation_result.json').open('w') as stream:
            os.chmod(out / 'valuation_result.json', 0o600)
            json.dump(_plain(result), stream, indent=2, allow_nan=False)
            stream.write('\n')
        result['evidence_paths'].append(str((out / 'valuation_result.json').relative_to(ROOT)))
        return result
    sample_path, sample_bytes = _capture_read(sample_path or DEFAULT_SAMPLE, 256 * 1024)
    rows, timings = [], []
    if variant not in ('legacy', 'maintained'):
        raise ValueError('VALIDATION_VARIANT_INVALID')
    core = _load('legacy/valuation/valuation_core.py')
    totals = _load('legacy/holdings/position_totals.py')
    analytics = _load('legacy/holdings/analytics.py')
    returns = _load('legacy/holdings/daily_return_rate.py')
    if variant == 'maintained':
        from shared.calculation.operators import valuation as core
        from shared.calculation.operators import holdings as totals
        returns = totals

    def check(name, group, fn, expected, *, comparator=_close, note='', inputs=None):
        started = time.monotonic()
        try:
            actual = fn()
            ok = comparator(actual, expected)
            row = {'id': name, 'group': group, 'status': 'passed' if ok else 'failed',
                   'observed': _plain(actual), 'expected': _plain(expected)}
        except Exception as exc:
            row = {'id': name, 'group': group, 'status': 'failed',
                   'exception_type': type(exc).__name__, 'expected': _plain(expected)}
        row.update(elapsed_seconds=round(time.monotonic() - started, 6), note=note)
        if inputs is not None:
            row['inputs'] = _plain(inputs)
        rows.append(row)
        return row

    def rejects(fn):
        try:
            fn()
        except (ValueError, TypeError, DecimalException, AssertionError, OverflowError):
            return True
        return False

    equal = lambda a, e: a == e
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        # Hash-bound public data is input evidence, not a fair-value oracle.
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('PUBLIC_SAMPLE_DUPLICATE_KEY')
                result[key] = value
            return result
        sample = json.loads(sample_bytes, object_pairs_hook=unique)
        sample_hash = hashlib.sha256(sample_bytes).hexdigest()
        pin = sample_path.with_suffix('.sha256')
        _, pin_bytes = _capture_read(pin, 128)
        if pin_bytes.decode().strip() != sample_hash or sample_hash != SAMPLE_SHA256:
            raise ValueError('PUBLIC_SAMPLE_HASH_MISMATCH')
        if not (sample.get('schema_version') == 1 and sample.get('issuer') == 'Microsoft'
                and sample.get('ticker') == 'MSFT' and sample.get('data_asof') == '2026-06-30'
                and sample['facts']['currency'] == 'USD'
                and sample['facts']['financial_amount_unit'] == 'million'
                and sample['sources'][0]['url'] == 'https://www.microsoft.com/investor/reports/ar26/index.html'):
            raise ValueError('PUBLIC_SAMPLE_IDENTITY_MISMATCH')
        source = sample_path.parent / sample['sources'][0]['source_path']
        _, source_bytes = _capture_read(source, 3 * 1024 * 1024)
        if hashlib.sha256(source_bytes).hexdigest() != sample['sources'][0]['source_sha256'] or sample['sources'][0]['source_sha256'] != SOURCE_SHA256:
            raise ValueError('PUBLIC_SOURCE_HASH_MISMATCH')
        facts = sample['facts']
        proxy = [str(int(a) - int(b)) for a, b in zip(facts['cfo'], facts['cash_capex_positive_outflow'])]
        check('public_cfo_capex_transform', 'public_sample', lambda: proxy,
              sample['transforms'][0]['values'], comparator=equal,
              note='Historical USD-million cash-flow proxy; not FCFF or a forecast.')
        flows = list(reversed(proxy))
        check('public_sample_pv_at_assumed_10pct', 'public_sample', lambda: core.pv(flows, '.10'),
              _pv(flows, '.10'), inputs={'cashflows': flows, 'discount_rate': '.10'},
              note='Artificial end-period PV timing test using public amounts; not MSFT fair value.')
        ni, shares = D(facts['net_income'][0]), D(facts['diluted_shares'][0])
        check('public_reported_eps_roundtrip', 'public_sample',
              lambda: analytics.ratio(ni, shares).quantize(D('.01')), D('17.95'), comparator=equal)

        rng = random.Random(20261031)
        for i in range(90):
            n = rng.randint(1, 40)
            cf = [str(D(rng.randint(-10**10, 10**10)) / 100) for _ in range(n)]
            rate = str(D(rng.randint(-75, 100)) / 100)
            check(f'pv_rational_{i}', 'default_accuracy', lambda c=cf, r=rate: core.pv(c, r),
                  _pv(cf, rate), inputs={'terms': n, 'rate': rate})
        for rate in ['0', '.000001', '.1', '-.75', '1']:
            for n in [1, 10, 1000]:
                check(f'annuity_{rate}_{n}', 'default_accuracy',
                      lambda r=rate, n=n: core.pv(['1234567.89012345'] * n, r),
                      _annuity('1234567.89012345', rate, n), inputs={'terms': n, 'rate': rate})
        for i in range(35):
            e, debt = rng.randint(1, 10**12), rng.randint(0, 10**12)
            ke, kd, tax = [D(rng.randint(0, 100)) / 100 for _ in range(3)]
            ref = _rational(ke) * F(e, e + debt) + _rational(kd) * (1 - _rational(tax)) * F(debt, e + debt)
            check(f'wacc_{i}', 'default_accuracy', lambda e=e, debt=debt, ke=ke, kd=kd, tax=tax:
                  core.gross_debt_wacc(e, debt, ke, kd, tax)['wacc'], ref)
        for g, roic, wacc in [('0', '.2', '.1'), ('.03', '.2', '.1'),
                               ('.09999999999999999999', '.2', '.1')]:
            nopat = F(1234567, 100)
            ref = nopat * (1 - _rational(g) / _rational(roic)) / (_rational(wacc) - _rational(g))
            check('terminal_' + g, 'default_accuracy', lambda g=g, roic=roic, wacc=wacc:
                  core.terminal_fcff('12345.67', g, roic, wacc)['terminal_ev'], ref)
        expected_enterprise = _pv(['100', '120', '130'], '.1') + F(1000) / F(11, 10)**3
        expected_nonoperating = F(20) + _pv(['0', '30', '0'], '.1')
        check('equity_bridge_and_discount_once', 'default_accuracy',
              lambda: core.equity_value(['100', '120', '130'], '1000', '.1', '70', '10',
                                       '20', ['0', '30', '0'])['per_share'],
              (expected_enterprise - 70 + expected_nonoperating) / 10)
        for i in range(30):
            a, b, c = [rng.randint(-10**8, 10**8) for _ in range(3)]
            check(f'weighted_ev_{i}', 'default_accuracy',
                  lambda a=a, b=b, c=c: core.expected_wealth([a, b, c], ['.2', '.3', '.5']),
                  F(a, 5) + F(3 * b, 10) + F(c, 2))

        base = core.pv(['100', '200', '300'], '.1')
        check('pv_linear_scaling', 'metamorphic', lambda: core.pv(['700', '1400', '2100'], '.1'), base * 7)
        check('positive_pv_monotone_rate', 'metamorphic',
              lambda: core.pv(['100'] * 40, '.2') < core.pv(['100'] * 40, '.1'), True, comparator=equal)
        check('wacc_financing_scale', 'metamorphic',
              lambda: core.gross_debt_wacc('8000', '2000', '.1', '.05', '.25')['wacc'],
              core.gross_debt_wacc('80', '20', '.1', '.05', '.25')['wacc'])
        check('equity_share_scaling', 'metamorphic',
              lambda: core.equity_value(['100'], '500', '.1', '30', '20')['per_share'] * 2,
              core.equity_value(['100'], '500', '.1', '30', '10')['per_share'])
        for name, fn in [('rate_minus_one', lambda: core.pv(['1'], '-1')),
                         ('rate_nan', lambda: core.pv(['1'], 'NaN')),
                         ('cashflow_inf', lambda: core.pv(['Infinity'], '.1')),
                         ('zero_shares', lambda: core.equity_value(['1'], 0, '.1', 0, 0)),
                         ('negative_debt_wacc', lambda: core.gross_debt_wacc(1, -1, '.1', '.1', '.2')),
                         ('terminal_growth_eq_rate', lambda: core.terminal_fcff(1, '.1', '.2', '.1')),
                         ('negative_probability', lambda: core.expected_wealth([1, 2], ['-.1', '1.1']))]:
            check(name, 'invalid_input', lambda fn=fn: rejects(fn), True, comparator=equal)

        check('pv_finite_cancellation', 'finite_stress',
              lambda: core.pv(['1e28', '1', '-1e28'], '0'), F(1),
              note='Finite inputs accepted by API; target declares no magnitude/precision bound.')
        check('ev_finite_cancellation', 'finite_stress',
              lambda: core.expected_wealth(['3e28', '3', '-3e28'], ['.25', '.5', '.25']), F(3, 2))
        check('pv_near_minus_one', 'finite_stress', lambda: core.pv(['.01'] * 100, '-.99'),
              _annuity('.01', '-.99', 100))
        for prec in [6, 28, 50]:
            for rounding in [ROUND_HALF_EVEN, ROUND_DOWN]:
                with localcontext() as c:
                    c.prec = prec
                    c.rounding = rounding
                    check(f'ambient_pv_{prec}_{rounding}', 'context_dependence',
                          lambda: core.pv(['1234567.89'] * 30, '.073'), _annuity('1234567.89', '.073', 30))
        for vals in [('10', '-4', '3.25'), ('0',), ('1e28', '1', '-1e28')]:
            view, source, marks = _totals_case(vals)
            check('totals_net_' + '_'.join(vals), 'holdings_accuracy',
                  lambda v=view, s=source, m=marks: D(totals.attach_totals(v, s, m)['accounts'][0]['position_totals']['snapshot_net']),
                  sum((_rational(x) for x in vals), F(0)))
        view, source, marks = _totals_case()
        result = totals.attach_totals(view, source, marks)['accounts'][0]['position_totals']
        check('holdings_nav_residual', 'holdings_accuracy', lambda: D(result['snapshot_residual']), F(74))
        view, source, marks = _totals_case()
        marks = [{'closing_quantity': '1', 'close': 'NaN'}]
        def close_mark_probe():
            try:
                value = totals.attach_totals(view, source, marks)['accounts'][0]['position_totals']['close_known_net']
                return {'rejected': False, 'close_known_net': value}
            except (ValueError, TypeError, DecimalException, AssertionError):
                return {'rejected': True}
        check('close_mark_nonfinite_rejected', 'boundary_validation',
              close_mark_probe, {'rejected': True}, comparator=lambda a, e: a['rejected'] is True,
              note='Upstream callers may prevalidate; reusable operator boundary currently does not.')
        view, source, marks = _totals_case(('1',), nav='1e400', cash='0')
        def nav_probe():
            nav = totals.attach_totals(view, source, marks)['accounts'][0]['metrics']['nav']
            return {'finite': D(str(nav)).is_finite(), 'nav_metric': nav}
        check('finite_nav_no_float_infinity', 'finite_stress',
              nav_probe, {'finite': True}, comparator=lambda a, e: a['finite'] is True,
              note='Finite Decimal input must not become silent nonfinite JSON metric.')
        for q, p, gross, fills, ref in [('10', '100', '25', [], F(5, 2)),
                                       ('0', '100', '25', [{'timestamp': '1', 'side': 'BUY', 'quantity': '2.5', 'price': '40'}], F(25))]:
            case = {'opening': {'quantity': q, 'price': p}, 'executions': fills}
            check('capital_return_' + q, 'holdings_accuracy',
                  lambda case=case, gross=gross: D(returns.daily_return_rate(case, gross)['percent']), ref)

        # This probes the actual copied boundary under optimization in a fresh
        # credential-free subprocess; no private identifiers or provider calls.
        code = """import importlib,importlib.util,json,sys
if sys.argv[3]=='maintained':m=importlib.import_module('shared.calculation.operators.holdings')
else:
 s=importlib.util.spec_from_file_location('totals',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
v,source,rows=json.loads(sys.argv[2])
try:
 m.attach_totals(v,source,rows);print('accepted')
except (AssertionError,ValueError,TypeError):print('rejected')
"""
        mismatch = _totals_case(currency='EUR')
        env = {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': '0', 'PYTHONPATH': str(ROOT)}
        for optimize in [False, True]:
            command = [sys.executable, '-B'] + (['-O'] if optimize else [])
            command += ['-c', code, str(BASE / 'legacy/holdings/position_totals.py'), json.dumps(mismatch), variant]
            cp = subprocess.run(command, env=env, cwd=out, capture_output=True, text=True, timeout=5)
            check('currency_rejection_optimized_' + str(optimize), 'boundary_validation',
                  lambda cp=cp: cp.stdout.strip() if cp.returncode == 0 else 'probe_failed',
                  'rejected', comparator=equal, note='Identity/currency safety must survive -O.')
        started = time.monotonic()
        view, source, marks = _totals_case(tuple(str(i % 100 - 50) for i in range(10000)), nav='1000000', cash='0')
        check('positions_10000_exact_sum', 'workload_stress',
              lambda: D(totals.attach_totals(view, source, marks)['accounts'][0]['position_totals']['snapshot_net']), F(-5000))
        timings.append({'case': 'positions_10000', 'elapsed_seconds': round(time.monotonic() - started, 6),
                        'exploratory_budget_seconds': 5})
        if variant == 'maintained':
            # New explicit maintained contract checks are additive; the original
            # 208 paired criteria/tolerances above remain unchanged.
            for label, call in [
                ('binary_float', lambda: core.pv(['1'], 0.1)),
                ('boolean', lambda: core.pv([True], '.1')),
                ('magnitude_bound', lambda: core.pv(['1e401'], '.1')),
                ('significant_digit_bound', lambda: core.pv(['1.' + '1' * 80], '.1')),
                ('period_bound', lambda: core.pv(['1'] * 1001, '.1')),
                ('vector_bound', lambda: core.expected_wealth(['1'] * 10001, ['0'] * 10001))]:
                check('maintained_reject_' + label, 'maintained_contract',
                      lambda call=call: rejects(call), True, comparator=equal)
            view, source, marks = _totals_case()
            original_view = copy.deepcopy(view)
            totals.attach_totals(view, source, marks)
            check('maintained_inputs_not_mutated', 'maintained_contract', lambda: view,
                  original_view, comparator=equal)
            view, source, marks = _totals_case(currency='EUR')
            original_view = copy.deepcopy(view)
            rejects(lambda: totals.attach_totals(view, source, marks))
            check('maintained_rejection_atomic', 'maintained_contract', lambda: view,
                  original_view, comparator=equal)
            with localcontext() as hostile:
                hostile.prec = 6
                hostile.traps[Inexact] = True
                check('maintained_ambient_inexact_trap_isolation', 'maintained_contract',
                      lambda: core.pv(['1234567.89'] * 30, '.073'),
                      _annuity('1234567.89', '.073', 30))

    groups = {}
    for row in rows:
        count = groups.setdefault(row['group'], {'passed': 0, 'failed': 0})
        count[row['status']] += 1
    failed = [r for r in rows if r['status'] == 'failed']
    target_paths = ([BASE / 'operators/valuation.py', BASE / 'operators/holdings.py']
                    if variant == 'maintained' else [BASE / 'legacy/valuation/valuation_core.py',
                    BASE / 'legacy/holdings/position_totals.py', BASE / 'legacy/holdings/daily_return_rate.py'])
    target_paths.append(BASE / 'legacy/holdings/analytics.py')
    result = {'version': VERSION, 'variant': variant, 'status': 'failed' if failed else 'passed',
              'cases_total': len(rows), 'cases_passed': len(rows) - len(failed), 'cases_failed': len(failed),
              'frozen_paired_cases': 208, 'additional_maintained_contract_cases': 9 if variant == 'maintained' else 0,
              'groups': groups, 'findings': failed, 'workload_timings': timings,
              'modules_exercised': ['valuation_core', 'position_totals', 'daily_return_rate', 'analytics.ratio'],
              'public_sample': {'path': str(sample_path.relative_to(ROOT)), 'sha256': sample_hash,
                                'data_asof': sample['data_asof'], 'retrieved_at': sample['retrieved_at'],
                                'source_urls': [s['url'] for s in sample['sources']]},
              'protocol_sha256': _sha(PROTOCOL),
              'runner_sha256': _sha(__file__),
              'candidate_hashes': {str(p.relative_to(ROOT)): _sha(p) for p in target_paths},
              'recommendations': ['Own a documented local numeric context and finite magnitude contract.',
                                  'Use stable/exact accumulation or reject unresolved cancellation.',
                                  'Keep money as Decimal strings through serialization and reject nonfinite close inputs.',
                                  'Replace reusable-boundary asserts with explicit validation errors.'],
              'claims': 'Arithmetic/implementation evidence only; no issuer fair-value or prediction claim.',
              'scheduled_acceptance': 'pending_root_scheduled_codex_run_and_verified_email',
              'generated_at': datetime.now(timezone.utc).isoformat()}
    result['evidence_paths'] = [str((out / name).relative_to(ROOT))
                                for name in ('valuation_cases.json', 'valuation_result.json')]
    for name, value in [('valuation_cases.json', rows), ('valuation_result.json', result)]:
        path = out / name
        with path.open('w') as f:
            os.chmod(path, 0o600)
            json.dump(_plain(value), f, indent=2, allow_nan=False)
            f.write('\n')
    return result


if __name__ == '__main__':
    print(json.dumps(run(STATE / 'valuation/run-initial'), indent=2, allow_nan=False))
