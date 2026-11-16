"""Frozen synthetic portfolio canary; no private-input or broker entry point."""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import hashlib
import json
import os
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from investment.portfolio.snapshot import (
    SnapshotError, admit_snapshot, analyze_admitted, analyze_snapshot, digest)
from tuning.langchain_pilot.holdings_contract_fixtures import canonical as contract_fixture

AS_OF = '2026-11-15T12:01:00+00:00'
QUERY_AT = '2026-11-15T12:00:00+00:00'
SCOPE = 'public_synthetic_portfolio_v1'
RATE_DECIMAL_PLACES = 12
ROOT = Path(__file__).resolve().parents[2]


def cases():
    rows = [{'symbol': 'SYNTH_X', 'contractId': 'synthetic-x', 'securityType': 'STK',
             'currency': 'USD', 'marketValue': '60', 'unrealizedPnl': '5'},
            {'symbol': 'SYNTH_Y', 'contractId': 'synthetic-y', 'securityType': 'STK',
             'currency': 'USD', 'marketValue': '40', 'unrealizedPnl': '-2'}]
    account = {'accountRef': 'synthetic-account', 'accountIdentityChecked': True,
               'ok': True, 'sourceReadStatus': 'complete', 'queryCompletedAt': QUERY_AT}
    holding = {**account, 'positions': rows, 'freshSourceResponse': True,
               'cachedFallbackUsed': False,
               'typeReads': [{'securityType': 'STK', 'ok': True, 'positionCount': 2}],
               'coverage': {'requestedSecurityTypes': ['STK'], 'successfulSecurityTypes': ['STK'],
                            'failedSecurityTypes': [], 'positionCount': 2,
                            'wholePortfolioVerified': False, 'paginationCompletenessVerified': False}}
    asset = {**account, 'summary': {'currency': 'USD', 'amounts': {
        'netLiquidation': '125', 'cash': '25', 'buyingPower': '500'}}}
    nominal = {'envelope': {'schema_version': 1, 'provider': 'tiger', 'tool': 'snapshot',
                'query_started_at': QUERY_AT, 'query_completed_at': QUERY_AT,
                'source_read_status': 'complete', 'cached_fallback_used': False,
                'request': {'tool': 'snapshot', 'arguments': {'security_types': ['STK']}},
                'data': {'holdings': holding, 'assets': asset}},
               'receipt': {'status': 'queried', 'mode': 'query', 'tool': 'snapshot',
                'source_read_status': 'complete', 'committed': True, 'release_requested': True,
                'holdings_read': True, 'assets_read': True, 'attempt_id': 'synthetic-attempt'},
               'taxonomy': {'positions': {
                   'SYNTH_X': {'primary_sector': 'synthetic-sector-x', 'daily_leverage': 2},
                   'SYNTH_Y': {'primary_sector': 'synthetic-sector-y', 'daily_leverage': 1}}},
               'as_of': AS_OF}
    metrics = {'positions_value': '100', 'gross_positions_value': '100', 'nav': '125',
               'cash': '25', 'cash_pct': '20', 'top1_pct': '60', 'hhi': '5200',
               'embedded_gross_nav_multiple': '1.28', 'unrealized_pnl': '3',
               'daily_pnl': None}
    expected = {'status': 'analyzed', 'accounts': [{'currency': 'USD', 'metrics': metrics,
                'whole_portfolio_verified': False, 'market_value_complete': True,
                'quote_time': None}]}
    roster = [{'id': 'nominal', 'inputs': nominal, 'outputs': expected}]
    empty = deepcopy(nominal)
    empty['envelope']['data']['holdings']['positions'] = []
    empty['envelope']['data']['holdings']['coverage']['positionCount'] = 0
    empty['envelope']['data']['holdings']['typeReads'][0]['positionCount'] = 0
    empty_expected = deepcopy(expected)
    empty_expected['accounts'][0]['metrics'].update(positions_value='0', gross_positions_value='0',
        top1_pct=None, hhi=None, embedded_gross_nav_multiple='0', unrealized_pnl='0')
    roster.append({'id': 'empty-requested-scope', 'inputs': empty, 'outputs': empty_expected})
    missing = deepcopy(nominal)
    missing['envelope']['data']['holdings']['positions'][0]['marketValue'] = None
    missing_expected = deepcopy(expected)
    missing_expected['accounts'][0]['metrics'].update(positions_value=None, gross_positions_value=None,
        top1_pct=None, hhi=None, embedded_gross_nav_multiple=None)
    missing_expected['accounts'][0]['market_value_complete'] = False
    roster.append({'id': 'missing-market-value', 'inputs': missing, 'outputs': missing_expected})
    currency = deepcopy(nominal)
    currency['envelope']['data']['assets']['summary']['currency'] = 'HKD'
    currency_expected = deepcopy(expected)
    currency_expected['accounts'][0]['metrics'].update(nav=None, cash=None, cash_pct=None,
                                                     embedded_gross_nav_multiple=None)
    roster.append({'id': 'currency-mismatch', 'inputs': currency, 'outputs': currency_expected})
    for name, error in [('partial-read', 'SNAPSHOT_READ_INCOMPLETE'),
                        ('unknown-checkpoint', 'SNAPSHOT_RECEIPT_UNCONFIRMED'),
                        ('stale-query', 'SNAPSHOT_QUERY_STALE_OR_FUTURE'),
                        ('account-mismatch', 'SNAPSHOT_ACCOUNT_MISMATCH')]:
        value = deepcopy(nominal)
        if name == 'partial-read': value['envelope']['source_read_status'] = 'partial'
        if name == 'unknown-checkpoint': value['receipt']['committed'] = False
        if name == 'stale-query': value['as_of'] = '2026-11-15T12:10:00+00:00'
        if name == 'account-mismatch': value['envelope']['data']['assets']['accountRef'] = 'synthetic-other'
        roster.append({'id': name, 'inputs': value, 'outputs': {'status': 'rejected', 'error': error}})

    def admitted_case(name, value, changes=None, *, whole=False):
        output = deepcopy(expected)
        output['accounts'][0]['metrics'].update(changes or {})
        output['accounts'][0]['whole_portfolio_verified'] = whole
        roster.append({'id': name, 'inputs': value, 'outputs': output})

    full = deepcopy(nominal)
    full['envelope']['request']['arguments']['security_types'] = ['STK', 'OPT']
    full_holding = full['envelope']['data']['holdings']
    full_holding['positions'][1]['securityType'] = 'OPT'
    full_holding['coverage'].update(requestedSecurityTypes=['STK', 'OPT'],
        successfulSecurityTypes=['STK', 'OPT'], wholePortfolioVerified=True,
        paginationCompletenessVerified=True)
    full_holding['typeReads'] = [{'securityType': 'STK', 'ok': True, 'positionCount': 1},
                                {'securityType': 'OPT', 'ok': True, 'positionCount': 1}]
    admitted_case('declared-stock-option-cash-scope', full, whole=True)
    full_empty = deepcopy(full)
    full_empty['envelope']['data']['holdings']['positions'] = []
    full_empty['envelope']['data']['holdings']['coverage']['positionCount'] = 0
    for read in full_empty['envelope']['data']['holdings']['typeReads']:
        read['positionCount'] = 0
    admitted_case('declared-complete-empty', full_empty,
        dict(positions_value='0', gross_positions_value='0', top1_pct=None,
             hhi=None, embedded_gross_nav_multiple='0', unrealized_pnl='0'), whole=True)
    short = deepcopy(nominal)
    short['envelope']['data']['holdings']['positions'][1]['marketValue'] = '-40'
    admitted_case('mixed-long-short', short, dict(positions_value='20'))
    decimal = deepcopy(nominal)
    decimal_rows = decimal['envelope']['data']['holdings']['positions']
    decimal_rows[0].update(marketValue='0.10', unrealizedPnl='0.01')
    decimal_rows[1].update(marketValue='0.15', unrealizedPnl='-0.02')
    decimal['envelope']['data']['assets']['summary']['amounts'].update(
        netLiquidation='0.50', cash='0.25')
    admitted_case('exact-decimal-money', decimal,
        dict(positions_value='0.25', gross_positions_value='0.25', nav='0.5',
             cash='0.25', cash_pct='50', embedded_gross_nav_multiple='0.7',
             unrealized_pnl='-0.01'))
    negative_cash = deepcopy(nominal)
    negative_cash['envelope']['data']['assets']['summary']['amounts']['cash'] = '-25'
    admitted_case('negative-cash', negative_cash, dict(cash='-25', cash_pct='-20'))
    zero_nav = deepcopy(nominal)
    zero_nav['envelope']['data']['assets']['summary']['amounts']['netLiquidation'] = '0'
    admitted_case('zero-nav-denominator', zero_nav,
        dict(nav='0', cash_pct=None, embedded_gross_nav_multiple=None))
    unknown_leverage = deepcopy(nominal)
    unknown_leverage['taxonomy']['positions']['SYNTH_X'].pop('daily_leverage')
    admitted_case('unknown-leverage', unknown_leverage, dict(embedded_gross_nav_multiple=None))
    prime = deepcopy(nominal)
    prime['envelope']['data']['assets']['summary'] = None
    admitted_case('missing-aggregate-summary', prime,
        dict(nav=None, cash=None, cash_pct=None, embedded_gross_nav_multiple=None))
    mixed = deepcopy(nominal)
    mixed['envelope']['data']['holdings']['positions'][1]['currency'] = 'HKD'
    mixed_output = deepcopy(expected)
    mixed_output['accounts'][0]['metrics'].update(positions_value='60', gross_positions_value='60',
        top1_pct='100', hhi='10000', embedded_gross_nav_multiple='0.96', unrealized_pnl='5')
    hkd = deepcopy(mixed_output['accounts'][0])
    hkd['currency'] = 'HKD'
    hkd['metrics'].update(positions_value='40', gross_positions_value='40', nav=None,
        cash=None, cash_pct=None, embedded_gross_nav_multiple=None, unrealized_pnl='-2')
    mixed_output['accounts'].append(hkd)
    roster.append({'id': 'mixed-currency-unaggregated', 'inputs': mixed, 'outputs': mixed_output})
    unknown_currency = deepcopy(nominal)
    unknown_currency['envelope']['data']['holdings']['positions'][0]['currency'] = None
    unknown_output = deepcopy(expected)
    unknown_output['accounts'][0].update(currency='币种未知', market_value_complete=False)
    unknown_output['accounts'][0]['metrics'] = {key: None for key in metrics}
    usd = deepcopy(expected['accounts'][0])
    usd['metrics'].update(positions_value='40', gross_positions_value='40', top1_pct='100',
        hhi='10000', embedded_gross_nav_multiple='0.32', unrealized_pnl='-2')
    unknown_output['accounts'].append(usd)
    roster.append({'id': 'missing-currency-unresolved', 'inputs': unknown_currency, 'outputs': unknown_output})
    duplicate = deepcopy(nominal)
    duplicate['envelope']['data']['holdings']['positions'][1]['contractId'] = 'synthetic-x'
    roster.append({'id': 'duplicate-contract', 'inputs': duplicate,
                   'outputs': {'status': 'rejected', 'error': 'SNAPSHOT_POSITION_IDENTITY_INVALID'}})
    future = deepcopy(nominal)
    future['as_of'] = '2026-11-15T11:59:59+00:00'
    roster.append({'id': 'future-query', 'inputs': future,
                   'outputs': {'status': 'rejected', 'error': 'SNAPSHOT_QUERY_STALE_OR_FUTURE'}})
    # Exact aliases for the independent designer's public/cloud roster. These
    # use its concrete values and scope, rather than similarly named old cases.
    independent_empty = {'status': 'analyzed', 'accounts': [{'currency': 'USD',
        'metrics': dict(positions_value='0', gross_positions_value='0', nav='1000', cash='300',
            cash_pct='30', top1_pct=None, hhi=None, embedded_gross_nav_multiple='0',
            unrealized_pnl='0', daily_pnl=None), 'whole_portfolio_verified': False,
        'market_value_complete': True, 'quote_time': '2026-11-15T15:59:00Z'}]}
    independent_short = deepcopy(independent_empty)
    independent_short['accounts'][0]['metrics'].update(positions_value='700', gross_positions_value='1100',
        top1_pct='54.545454545455', hhi='4049.586776859504', embedded_gross_nav_multiple='1.1')
    independent_current = deepcopy(independent_empty)
    independent_current['accounts'][0]['metrics'].update(positions_value='700', gross_positions_value='700',
        top1_pct='100', hhi='10000', embedded_gross_nav_multiple='0.7')
    independent = [
        ('public-holdings-empty-requested-scope', 'HOLD-01', independent_empty),
        ('public-holdings-failed-empty', 'HOLD-02',
         {'status': 'rejected', 'error': 'SNAPSHOT_READ_INCOMPLETE'}),
        ('public-holdings-partial-empty', 'HOLD-03',
         {'status': 'rejected', 'error': 'SNAPSHOT_TYPE_COVERAGE_INCOMPLETE',
          'missing_security_types': ['OPT', 'FUT', 'FUND']}),
        ('public-holdings-long-short', 'HOLD-40', independent_short),
        ('public-holdings-no-daily-performance', 'HOLD-47', independent_current),
        ('public-holdings-unknown-checkpoint', 'HOLD-52',
         {'status': 'rejected', 'error': 'SNAPSHOT_CHECKPOINT_UNCONFIRMED'})]
    for selector, criterion_case, output in independent:
        roster.append({'id': selector, 'inputs': contract_fixture(criterion_case), 'outputs': output})
    return roster


METRICS = ('positions_value', 'gross_positions_value', 'nav', 'cash', 'cash_pct',
           'top1_pct', 'hhi', 'embedded_gross_nav_multiple', 'unrealized_pnl', 'daily_pnl')


def project(result):
    def number(v, *, rate=False):
        if v is None:
            return None
        value = Decimal(v)
        if rate:
            with localcontext() as context:
                context.prec = max(50, value.adjusted() + RATE_DECIMAL_PLACES + 8)
                value = value.quantize(Decimal(1).scaleb(-RATE_DECIMAL_PLACES), rounding=ROUND_HALF_EVEN)
        value = format(value, 'f')
        return value.rstrip('0').rstrip('.') if '.' in value else value
    return {'status': result['status'], 'accounts': [
        {'currency': a['currency'], 'metrics': {k: number(a['metrics'][k],
            rate=k in ('cash_pct', 'top1_pct', 'hhi', 'embedded_gross_nav_multiple')) for k in METRICS},
         'whole_portfolio_verified': a['quality']['whole_portfolio_verified'],
         'market_value_complete': a['quality']['market_value_complete'],
         'quote_time': a['quality']['quote_time']} for a in result['analysis']['accounts']]}


class PortfolioState(TypedDict, total=False):
    inputs: dict
    admitted: dict
    result: dict


def graph():
    analysis_tool = StructuredTool.from_function(
        analyze_admitted, name='portfolio_analysis_tool',
        description='Analyze only an admitted synthetic snapshot with explicit taxonomy; no acquisition.')
    def admit(state):
        value = state['inputs']
        return {'admitted': admit_snapshot(value['envelope'], value['receipt'], as_of=value['as_of'])}
    def analyze(state, config: RunnableConfig):
        return {'result': analysis_tool.invoke(
            {'admitted': state['admitted'], 'taxonomy': state['inputs']['taxonomy']}, config=config)}
    builder = StateGraph(PortfolioState)
    builder.add_node('snapshot_admission', admit)
    builder.add_node('portfolio_analysis', analyze)
    builder.add_edge(START, 'snapshot_admission')
    builder.add_edge('snapshot_admission', 'portfolio_analysis')
    builder.add_edge('portfolio_analysis', END)
    return builder.compile(name='synthetic_portfolio')


def public_case(case_id):
    # Resolve before any traced runnable invocation. Callers cannot pass account
    # objects or paths; all traced values originate in this frozen public roster.
    if not isinstance(case_id, str): raise SnapshotError('PORTFOLIO_PUBLIC_CASE_ONLY')
    selected = next((c for c in cases() if c['id'] == case_id), None)
    if selected is None: raise SnapshotError('PORTFOLIO_PUBLIC_CASE_ONLY')
    return selected


def rejection(error):
    result = {'status': 'rejected', 'error': str(error)}
    if error.missing_security_types:
        result['missing_security_types'] = list(error.missing_security_types)
    return result


def run_case(case_id, *, callbacks=(), run_id=None):
    selected = public_case(case_id)
    value = selected['inputs']
    try:
        result = graph().invoke({'inputs': value}, config={'callbacks': list(callbacks),
            'run_id': run_id or uuid4(), 'recursion_limit': 8,
            'metadata': {'scope': SCOPE, 'case_id': case_id, 'cases_sha256': digest(cases())}})
        return project(result['result'])
    except SnapshotError as error:
        return rejection(error)


class Events(BaseCallbackHandler):
    def __init__(self): self.rows = []
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        self.rows.append({'event': 'start', 'run_id': str(run_id),
            'parent_run_id': str(parent_run_id) if parent_run_id else None,
            'name': kwargs.get('name')})
    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self.rows.append({'event': 'end', 'run_id': str(run_id)})
    def on_chain_error(self, error, *, run_id, **kwargs):
        self.rows.append({'event': 'error', 'run_id': str(run_id), 'error_type': type(error).__name__})
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        self.rows.append({'event': 'tool_start', 'run_id': str(run_id),
            'parent_run_id': str(parent_run_id) if parent_run_id else None,
            'name': serialized.get('name')})
    def on_tool_end(self, output, *, run_id, **kwargs):
        self.rows.append({'event': 'tool_end', 'run_id': str(run_id)})
    def on_tool_error(self, error, *, run_id, **kwargs):
        self.rows.append({'event': 'tool_error', 'run_id': str(run_id),
                          'error_type': type(error).__name__})


def verify_local():
    records = []
    for case in cases():
        events = Events()
        actual = run_case(case['id'], callbacks=[events])
        try:
            value = case['inputs']
            direct = project(analyze_snapshot(value['envelope'], value['receipt'], value['taxonomy'],
                                              as_of=value['as_of']))
        except SnapshotError as error:
            direct = rejection(error)
        if actual != case['outputs'] or actual != direct:
            raise SnapshotError('PORTFOLIO_FROZEN_CONTRACT_FAILED')
        records.append({'case_id': case['id'], 'result': actual, 'direct_parity': True,
                        'events': events.rows})
    paths = ('investment/portfolio/snapshot.py', 'niulai/holdings/analytics.py',
             'tuning/langchain_pilot/holdings.py', 'tuning/langchain_pilot/holdings_contract_fixtures.py',
             'tuning/langchain_pilot/requirements.lock.txt')
    return {'scope': SCOPE, 'status': 'passed_local_synthetic_only', 'case_count': len(records),
        'cases_sha256': digest(cases()), 'sources': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                                   for p in paths},
        'broker_calls': 0, 'model_calls': 0, 'cloud_calls': 0, 'records': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['verify'])
    parser.parse_args()
    evidence = verify_local()
    directory = ROOT / '.langchain-pilot/runtime/portfolio' / str(uuid4())
    directory.mkdir(parents=True, mode=0o700)
    path = directory / 'acceptance.json'
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'status': evidence['status'], 'case_count': evidence['case_count'],
                      'evidence': str(path.relative_to(ROOT))}))


if __name__ == '__main__': main()
