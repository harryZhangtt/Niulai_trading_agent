"""Synthetic spreadsheet ingress and stock-P&L contract checks, fully offline."""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import warnings
import zipfile

from shared.calculation.operators.spreadsheet import screen_xlsx

ROOT = Path(__file__).resolve().parents[3]
LEGACY = ROOT / 'shared/calculation/legacy'
PROTOCOL = Path(__file__).with_name('contracts_protocol.md')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _book(path, *, formula=None, growth=.02):
    import openpyxl
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = 'DCF'
    sheet['A1'], sheet['B1'] = 'Terminal growth', growth
    sheet['A2'], sheet['B2'] = 'WACC', .1
    book.create_sheet('WACC')
    book['WACC']['A1'], book['WACC']['B1'] = 'WACC', .1
    book.create_sheet('Sensitivity')
    if formula:
        sheet['A10'] = formula
    book.save(path)
    book.close()
    path.chmod(0o600)


def _rewrite(source, destination, transform, extras=()):
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as dst:
        for member in src.infolist():
            dst.writestr(member.filename, transform(member.filename, src.read(member.filename)))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            for name, data in extras:
                dst.writestr(name, data)
    destination.chmod(0o600)


def _pnl_case(fills=(), closing_quantity='10'):
    identity = {'account_ref': 'synthetic-contract-account', 'contract_id': 'synthetic-stock', 'currency': 'USD'}
    def mark(quantity, price, session):
        return {**identity, 'quantity': quantity, 'price': price, 'session': session,
                'source_ref': 'synthetic:'+session, 'price_basis': 'regular_session_close'}
    return {**identity, 'security_type': 'STK', 'multiplier': '1',
            'opening': mark('10', '100', '2026-10-29'),
            'closing': mark(closing_quantity, '105', '2026-10-30'),
            'executions': [{**identity, **fill} for fill in fills],
            'ledger': {'complete': True, 'source_ref': 'synthetic:complete-ledger',
                       'start_utc': '2026-10-29T20:00:00Z', 'end_utc': '2026-10-30T20:00:00Z'},
            'corporate_actions': {'status': 'verified_none', 'source_ref': 'synthetic:no-actions'}}


def _fill(side, quantity, price, fee, identity='a', timestamp='2026-10-30T15:00:00Z'):
    return {'side': side, 'quantity': quantity, 'price': price, 'fee': fee,
            'source_ref': 'synthetic:execution:'+identity, 'timestamp': timestamp}


def _pnl_oracle(case):
    F = Fraction
    final_price = F(case['closing']['price'])
    gross = F(case['opening']['quantity'])*(final_price-F(case['opening']['price']))
    for fill in case['executions']:
        sign = 1 if fill['side'] == 'BUY' else -1
        gross += sign*F(fill['quantity'])*(final_price-F(fill['price']))
    return gross, gross-sum((F(fill['fee']) for fill in case['executions']), F(0))


def run(output_dir, sample_path=None):
    start = time.monotonic()
    out = Path(output_dir).resolve()
    if not out.is_relative_to(ROOT / '.job-runtime/calculation'):
        raise ValueError('CONTRACT_OUTPUT_OUTSIDE_CALCULATION_STATE')
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    sheets = out / 'sheets'
    sheets.mkdir(exist_ok=True, mode=0o700)
    checks, findings = [], []
    def check(name, good, details=None, scope='candidate'):
        row = {'id': name, 'scope': scope, 'status': 'passed' if good else 'failed', 'details': details or {}}
        checks.append(row)
        if not good:
            findings.append(row)

    ordinary, uncached = sheets/'literal.xlsx', sheets/'uncached.xlsx'
    _book(ordinary)
    _book(uncached, formula='=1/0')
    baseline = _load('contracts_legacy_dcf', LEGACY/'validation/validate_dcf.py').validate_dcf_model(str(uncached))
    baseline_receipt = {key: baseline[key] for key in ('status', 'error_count', 'warning_count', 'errors', 'warnings', 'info')}
    check('legacy_uncached_formula_not_numerically_accepted', baseline['status'] != 'PASS',
          baseline_receipt, scope='baseline')
    get_warning = any('get' in item and 'attribute' in item for item in baseline['warnings'])
    check('legacy_wacc_range_check_runs', not get_warning,
          {'workbook_get_warning_observed': get_warning}, scope='baseline')

    def screen(path, **overrides):
        return screen_xlsx(path, wacc_cell=overrides.get('wacc_cell', 'WACC!B1'),
                           growth_cell=overrides.get('growth_cell', 'DCF!B1'),
                           allowed_root=overrides.get('allowed_root', sheets))
    result = screen(ordinary)
    check('literal_rates_structurally_screened', result['status'] == 'screened' and
          result['numeric_validated'] is False, result)
    result = screen(uncached)
    check('uncached_formula_unverified', result['status'] == 'unverified' and
          result['uncached_formula_cells'] == 1 and result['numeric_validated'] is False, result)
    cached = sheets/'cached_formula.xlsx'
    _rewrite(uncached, cached, lambda name, raw: re.sub(rb'<f>1/0</f><v(?:\s*/>|></v>)', b'<f>1/0</f><v>5</v>', raw)
             if name == 'xl/worksheets/sheet1.xml' else raw)
    result = screen(cached)
    check('cached_formula_never_numerically_approved', result['status'] == 'screened' and
          result['numeric_validated'] is False and 'FORMULAS_NOT_RECALCULATED' in result['warnings'], result)

    mutations = [
        ('excel_error', lambda name, raw: re.sub(rb'<f>1/0</f><v(?:\s*/>|></v>)', b'<v>#DIV/0!</v>', raw)
         .replace(b'<c r="A10">', b'<c r="A10" t="e">') if name == 'xl/worksheets/sheet1.xml' else raw, ()),
        ('external_relationship', lambda name, raw: raw.replace(b'</Relationships>',
         b'<Relationship Id="unsafe" Type="external" Target="https://example.invalid/" TargetMode="External"/></Relationships>')
         if name == 'xl/_rels/workbook.xml.rels' else raw, ()),
        ('dtd_entity', lambda name, raw: b'<!DOCTYPE x [<!ENTITY e "unsafe">]>'+raw
         if name == 'xl/worksheets/sheet1.xml' else raw, ()),
        ('duplicate_member', lambda name, raw: raw, (('xl/workbook.xml', b'<x/>'),)),
        ('traversal_member', lambda name, raw: raw, (('../outside.xml', b'<x/>'),)),
        ('uncompressed_member_limit', lambda name, raw: raw, (('xl/oversize.xml', b' '*(2*1024*1024+1)),)),
        ('zip_total_size', lambda name, raw: raw, tuple(('xl/large'+str(i)+'.bin', b' '*(2*1024*1024)) for i in range(5))),
        ('zip_member_count', lambda name, raw: raw, tuple(('xl/item'+str(i)+'.bin', b'x') for i in range(130))),
    ]
    for name, transform, extras in mutations:
        path = sheets/(name+'.xlsx')
        _rewrite(uncached, path, transform, extras)
        result = screen(path)
        check(name+'_rejected', result['status'] == 'rejected', result)
    for name, formula in [('webservice', '=WEBSERVICE("https://example.invalid/")'),
                          ('external_workbook', "='[external.xlsx]Sheet1'!A1")]:
        path = sheets/(name+'.xlsx'); _book(path, formula=formula)
        result = screen(path)
        check(name+'_rejected', result['status'] == 'rejected', result)
    for name, value in [('equal_growth', .1), ('greater_growth', .2), ('nonfinite_growth', 'NaN')]:
        path = sheets/(name+'.xlsx'); _book(path, growth=value)
        if value == 'NaN':
            # An OOXML numeric nonfinite, not a benign string cell.
            replaced = sheets/'nonfinite_numeric.xlsx'
            _rewrite(path, replaced, lambda name, raw: raw.replace(b'<c r="B1" t="inlineStr"><is><t>NaN</t></is></c>',
                     b'<c r="B1" t="n"><v>NaN</v></c>') if name == 'xl/worksheets/sheet1.xml' else raw)
            path = replaced
        result = screen(path)
        check(name+'_rejected', result['status'] == 'rejected', result)
    path = sheets/'formula_binding.xlsx';_book(path)
    _rewrite(path, sheets/'formula_binding2.xlsx', lambda name, raw: raw.replace(b'<c r="B1" t="n"><v>0.1</v></c>',
             b'<c r="B1"><f>1/10</f><v>0.1</v></c>') if name == 'xl/worksheets/sheet2.xml' else raw)
    result = screen(sheets/'formula_binding2.xlsx')
    check('formula_binding_unverified', result['status'] == 'unverified', result)
    result = screen(ordinary, growth_cell='DCF!Z99')
    check('missing_binding_unverified', result['status'] == 'unverified', result)
    restricted = out/'restricted'; restricted.mkdir(exist_ok=True, mode=0o700)
    result = screen(ordinary, allowed_root=restricted)
    check('outside_root_rejected', result['status'] == 'rejected', result)
    path = sheets/'compressed_input_limit.xlsx'
    path.write_bytes(ordinary.read_bytes()+b'x'*(2*1024*1024+1));path.chmod(0o600)
    result = screen(path)
    check('compressed_input_limit_rejected', result['status'] == 'rejected' and
          'INPUT_SIZE_OR_TYPE_INVALID' in result['errors'], result)
    link = sheets/'symlink.xlsx'
    if not link.exists():
        link.symlink_to(ordinary.name)
    result = screen(link)
    check('input_symlink_rejected', result['status'] == 'rejected' and
          'INPUT_SYMLINK_REJECTED' in result['errors'], result)
    raw = bytearray(ordinary.read_bytes())
    for signature, offset in ((b'PK\x03\x04', 6), (b'PK\x01\x02', 8)):
        position = 0
        while (position := raw.find(signature, position)) >= 0:
            raw[position+offset] |= 1
            position += len(signature)
    path = sheets/'encrypted.xlsx';path.write_bytes(raw);path.chmod(0o600)
    result = screen(path)
    check('encrypted_zip_rejected', result['status'] == 'rejected', result)

    # Unmodified inherited tests get their own identity and receipt.
    env = {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': '0',
           'PYTHONPATH': str(LEGACY/'holdings'), 'TMPDIR': str(ROOT/'.job-runtime/calculation/tmp')}
    cp = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'test_execution_pnl_independent'],
                        env=env, cwd=out, capture_output=True, text=True, timeout=45)
    output = cp.stdout+cp.stderr
    count = re.search(r'Ran (\d+) tests?', output)
    inherited = {'basis': 'INHERITED_UNMODIFIED_TESTS_NOT_NEW_INDEPENDENT_ORACLE',
                 'exit_code': cp.returncode, 'test_count': int(count[1]) if count else None,
                 'skipped': 'skipped=' in output, 'output': output[-12000:]}
    check('inherited_stock_pnl_suite', cp.returncode == 0 and count is not None
          and not inherited['skipped'], inherited, scope='inherited')

    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(LEGACY/'holdings'))
        pnl = _load('contracts_daily_pnl', LEGACY/'holdings/daily_performance.py')
        cases = [
            _pnl_case(),
            _pnl_case([_fill('BUY', '2.5', '102', '.25')], '12.5'),
            _pnl_case([_fill('SELL', '4', '103', '1.25')], '6'),
            _pnl_case([_fill('BUY', '3', '102', '.5'), _fill('SELL', '3', '104', '.5', identity='b')]),
        ]
        for i, case in enumerate(cases):
            expected = _pnl_oracle(case)
            actual = pnl.compute_close_to_close_pnl(case)
            good = (actual.get('status') == 'computed_gross_and_net' and
                    Fraction(actual['gross_pnl']) == expected[0] and Fraction(actual['net_pnl']) == expected[1])
            check('independent_fraction_pnl_'+str(i), good,
                  {'expected_gross': str(expected[0]), 'expected_net': str(expected[1]),
                   'observed_gross': str(actual.get('gross_pnl')), 'observed_net': str(actual.get('net_pnl')),
                   'observed_status': actual.get('status')}, scope='independent_numeric')
        for name, stamp, included in [('opening_excluded', '2026-10-29T20:00:00Z', False),
                                      ('closing_included', '2026-10-30T20:00:00Z', True),
                                      ('after_close_excluded', '2026-10-30T20:00:01Z', False)]:
            case = _pnl_case([_fill('BUY', '1', '102', '.1', timestamp=stamp)], '11')
            actual = pnl.compute_close_to_close_pnl(case)
            check(name, (actual['status'] == 'computed_gross_and_net') is included,
                  {'observed_status': actual['status'], 'reason': actual.get('reason')}, scope='independent_numeric')
    finally:
        sys.path[:] = old_path

    candidate_failures = [x for x in checks if x['scope'] == 'candidate' and x['status'] == 'failed']
    result = {'suite': 'contracts', 'status': 'failed' if findings else 'passed',
              'checks': checks, 'findings': findings,
              'counts': {'passed': sum(x['status'] == 'passed' for x in checks),
                         'failed': len(findings), 'skipped': 0, 'total': len(checks)},
              'modules_exercised': ['legacy.validation.validate_dcf', 'operators.spreadsheet',
                                    'legacy.holdings.daily_performance'],
              'corrected_operator_status': 'failed' if candidate_failures else 'passed',
              'corrected_operator_claim': 'Bounded offline structural screening only; never numerical Excel/DCF certification.',
              'dependency_versions': {p: importlib.metadata.version(p) for p in ('openpyxl', 'pandas', 'exchange-calendars')},
              'protocol_sha256': hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
              'elapsed_seconds': round(time.monotonic()-start, 4),
              'limitations': ['Synthetic ingress/P&L cases only; live public facts are covered by the other suites.',
                              'Baseline false-PASS and workbook API warning stay failed findings.',
                              'Inherited P&L tests are not counted as newly independent cases.',
                              'No Excel evaluation, external application, network, credentials or production actions.']}
    file = out/'contracts-result.json';file.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n');file.chmod(0o600)
    return result
