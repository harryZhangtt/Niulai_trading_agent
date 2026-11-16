"""Explicit schema mapping of independent atomic-contract-v1.1 HOLD givens.

Only authored public synthetic values occur here. This module never opens an
account file, invokes acquisition or changes receipts to recover an outcome.
"""
from copy import deepcopy

from investment.portfolio.snapshot import digest

QUERY = '2026-11-15T16:00:00Z'
AS_OF = '2026-11-15T16:01:00Z'
TYPES = ['STK', 'OPT', 'FUT', 'FUND']


def row(value='100', *, identity='STK:A', kind='STK', currency='USD', symbol='SYNTH_A'):
    return dict(symbol=symbol, contractId=identity, securityType=kind,
                currency=currency, marketValue=value, unrealizedPnl='0')


def synchronize(value, types=None):
    holding = value['envelope']['data']['holdings']
    types = list(types or TYPES)
    value['envelope']['request']['arguments']['security_types'] = types
    holding['coverage'].update(requestedSecurityTypes=types, successfulSecurityTypes=list(types),
        failedSecurityTypes=[], positionCount=len(holding['positions']))
    holding['typeReads'] = [dict(securityType=kind, ok=True,
        positionCount=sum(p['securityType'] == kind for p in holding['positions'])) for kind in types]
    return value


def base():
    account = dict(accountRef='SYNTHETIC-A', accountIdentityChecked=True, ok=True,
                   sourceReadStatus='complete', queryCompletedAt=QUERY)
    value = dict(envelope=dict(schema_version=1, provider='tiger', tool='snapshot',
        query_started_at=QUERY, query_completed_at=QUERY, source_read_status='complete',
        cached_fallback_used=False, request=dict(tool='snapshot', arguments=dict(security_types=TYPES)),
        quote_observation=dict(quote_at='2026-11-15T15:59:00Z', cutoff=None),
        data=dict(holdings={**account, 'positions': [], 'freshSourceResponse': True,
            'cachedFallbackUsed': False, 'coverage': dict(wholePortfolioVerified=False,
            paginationCompletenessVerified=False)},
            assets={**account, 'summary': dict(currency='USD', amounts=dict(netLiquidation='1000', cash='300'))})),
        receipt=dict(status='queried', mode='query', tool='snapshot', source_read_status='complete',
            committed=True, release_requested=True, holdings_read=True, assets_read=True,
            attempt_id='SYNTHETIC-CHECKPOINT-1'),
        taxonomy=dict(positions={}), as_of=AS_OF)
    return synchronize(value)


def canonical(case_id):
    """Map one frozen semantic case into the adapter's actual receipt schema."""
    number = int(case_id.split('-')[1])
    if not 1 <= number <= 60:
        raise ValueError('HOLD_CASE_UNKNOWN')
    value = base()
    envelope = value['envelope']
    holding, asset = envelope['data']['holdings'], envelope['data']['assets']
    rows = holding['positions']
    amounts = asset['summary']['amounts']
    if number == 2:
        envelope['source_read_status'] = 'failed'
        holding.update(ok=False, sourceReadStatus='failed')
    elif number == 3:
        holding['coverage'].update(successfulSecurityTypes=['STK'], failedSecurityTypes=TYPES[1:])
        holding['typeReads'] = [dict(securityType='STK', ok=True, positionCount=0)]
    elif number == 4:
        value['receipt'].update(status='unknown', committed=False)
    elif number == 6:
        rows.extend([row(identity='STK:A'), row(identity='OPT:B', kind='OPT'),
                     row(identity='OPT:C', kind='OPT'), row(identity='FUND:D', kind='FUND')])
        synchronize(value)
    elif number == 7:
        rows.append(row())
        synchronize(value, ['STK'])
    elif number == 8:
        holding['coverage'].update(successfulSecurityTypes=['STK', 'FUT', 'FUND'], failedSecurityTypes=['OPT'])
    elif number == 9:
        rows.append(row())
        synchronize(value)
        holding['typeReads'][0]['positionCount'] = 2
    elif number == 12:
        asset['accountRef'] = 'SYNTHETIC-B'
    elif number == 13:
        envelope['data']['holdings'] = [deepcopy(holding), {**deepcopy(holding), 'accountRef': 'SYNTHETIC-B'}]
    elif number == 14:
        holding['accountRef'] = None
    elif number == 15:
        holding['sourceAccountMetadata'] = {'permission': 'admin'}
    elif number in (16, 17, 18, 20):
        rows.append(row(currency='USD' if number == 16 else (None if number == 18 else 'HKD')))
        synchronize(value)
    elif number == 19:
        rows.extend([row('10', identity='STK:A', currency='USD'),
                     row('20', identity='STK:B', currency='HKD')])
        synchronize(value)
    elif number in (21, 22):
        rows.extend([row(), row('100' if number == 21 else '120')])
        synchronize(value)
    elif number in (23, 24, 25):
        terms = [('2027-01-15', '100', 'C'), ('2027-02-19', '100', 'C')] if number == 23 else [
            ('2027-01-15', '100', 'C'), ('2027-01-15', '110', 'C'), ('2027-01-15', '100', 'P')]
        if number == 25:
            rows.append(row(identity=None))
            terms = [('2027-01-15', '100', 'C')]
        for expiry, strike, right in terms:
            rows.append({**row(identity=None, kind='OPT'), 'expiry': expiry, 'strike': strike, 'putCall': right})
        synchronize(value)
    elif number in (26, 27, 28, 29, 30, 31):
        replacements = {26: '0', 27: None, 28: None, 29: 'abc', 30: True, 31: 'Infinity'}
        rows.append(row(replacements[number]))
        if number == 27:
            rows[0].pop('marketValue')
        synchronize(value)
    elif number == 32:
        amounts['netLiquidation'] = '0'
    elif number == 33:
        rows.append(row())
        synchronize(value)
    elif 34 <= number <= 39:
        quote = {34: '2026-11-14T16:00:00Z', 35: None, 36: '2026-11-15T15:59:00Z',
                 37: '2026-11-15T15:58:59Z', 38: '2026-11-16T00:00:00Z', 39: '2026-11-15 09:00'}[number]
        envelope['quote_observation'].update(quote_at=quote, cutoff='2026-11-15T15:59:00Z')
    elif number in (40, 41, 42, 45, 46, 47):
        numbers = {40: ['600', '-200', '300'], 41: ['0.1', '0.2'],
                   42: ['100', '-100'], 45: ['1500'], 46: ['600'], 47: ['700']}[number]
        rows.extend(row(amount, identity=f'STK:{index}', symbol=f'SYNTH_{index}') for index, amount in enumerate(numbers))
        amounts['netLiquidation'] = '1' if number == 41 else ('100' if number == 42 else '1000')
        synchronize(value)
    elif number == 43:
        rows.append({**row('-250', kind='OPT', identity='OPT:A'),
                     'quantity': '-2', 'multiplier': '100', 'latestPrice': '1.25'})
        synchronize(value)
    elif number == 44:
        amounts['cash'] = '-50'
    elif number == 48:
        rows.append({**row(), 'unrealizedPnl': '123'})
        synchronize(value)
    elif number == 50 or 56 <= number <= 59:
        rows.append(row())
        synchronize(value)
    elif number == 60:
        rows.append(row())
        synchronize(value, ['STK'])
    if 51 <= number <= 56:
        envelope['checkpoint'] = dict(state='committed', attempt_id=value['receipt']['attempt_id'],
                                      receipt_sha256=digest(value['receipt']))
        if number in (52, 53, 55):
            envelope['checkpoint']['state'] = 'stale' if number == 53 else 'unknown'
        if number == 54:
            envelope['checkpoint']['receipt_sha256'] = 'foreign hash'
    # Explicit unit leverage is authored for arithmetic cases, never inferred
    # from the ticker or security type. It does not attest real instrument beta.
    if isinstance(envelope['data']['holdings'], dict):
        value['taxonomy']['positions'] = {p['symbol']: {'daily_leverage': 1} for p in rows}
    return value
