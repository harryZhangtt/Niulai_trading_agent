"""Maintained synthetic/public holdings math with explicit finite boundaries.

No credentials, source acquisition or date inference. attach_totals returns a
copy of the view, leaving caller inputs unchanged even on rejected evidence.
Money/ratios serialize as Decimal strings, with the shared valuation policy.
"""
import copy
from fractions import Fraction

from .valuation import CalculationError, decimal_result, rational, require, vector

VERSION = '2026-10-31-holdings-1'


def _text(value):
    require(isinstance(value, str) and bool(value), 'IDENTITY_MISSING')
    return value


def attach_totals(view, source, rows):
    try:
        result = copy.deepcopy(view)
        account = result['accounts'][0]
        holdings = source['evidence']['holdings']['result']
        require(holdings['ok'] is True and holdings['accountIdentityChecked'] is True
                and holdings['sourceReadStatus'] == 'complete', 'HOLDINGS_INCOMPLETE')
        require(_text(holdings['accountRef']) == _text(account['accountRef']), 'ACCOUNT_MISMATCH')
        currency = _text(account['currency'])
        positions = holdings['positions']
        require(isinstance(positions, list) and len(positions) <= 10000, 'POSITIONS_RESOURCE_BOUND')
        keys, values = set(), []
        for position in positions:
            key = _text(position['contractId'])
            require(key not in keys, 'POSITION_DUPLICATE')
            keys.add(key)
            require(position['currency'] == currency, 'CURRENCY_MISMATCH')
            values.append(None if position.get('marketValue') is None else rational(position['marketValue']))
        complete = all(v is not None for v in values)
        require(isinstance(rows, list) and len(rows) <= 10000, 'CLOSE_ROWS_RESOURCE_BOUND')
        known = []
        for row in rows:
            if row.get('close') is not None:
                price, quantity = rational(row['close']), rational(row['closing_quantity'])
                require(price >= 0, 'CLOSE_PRICE_DOMAIN')
                known.append(price * quantity)
        net = sum(values, Fraction(0)) if complete else None
        text = lambda value: str(decimal_result(value)) if value is not None else None
        totals = {'snapshot_net': text(net),
                  'snapshot_gross': text(sum((abs(v) for v in values), Fraction(0))) if complete else None,
                  'snapshot_count': len(positions), 'snapshot_query_at': holdings.get('queryCompletedAt'),
                  'snapshot_price_timestamp_verified': False, 'close_known_net': text(sum(known, Fraction(0))),
                  'close_known_count': len(known), 'close_expected_count': len(rows),
                  'basis': 'broker_returned_positions_snapshot_not_historical_close'}
        assets = source.get('evidence', {}).get('current_assets', {}).get('result', {})
        if assets.get('ok') is True and assets.get('sourceReadStatus') == 'complete' and assets.get('accountIdentityChecked') is True:
            require(_text(assets['accountRef']) == _text(account['accountRef']), 'ACCOUNT_MISMATCH')
            summary = assets.get('summary') or {}
            require(summary.get('currency') == currency, 'CURRENCY_MISMATCH')
            amounts = summary.get('amounts', {})
            nav = rational(amounts['netLiquidation']) if amounts.get('netLiquidation') is not None else None
            cash = rational(amounts['cash']) if amounts.get('cash') is not None else None
            totals.update(snapshot_nav=text(nav), snapshot_cash=text(cash), assets_query_at=assets.get('queryCompletedAt'))
            if nav is not None and cash is not None and complete and nav > 0:
                residual = nav - cash - net
                totals['snapshot_residual'] = text(residual)
                account.setdefault('metrics', {}).update(nav=text(nav), cash=text(cash),
                    cash_pct=text(cash / nav * 100), positions_nav_pct=text(net / nav * 100),
                    other_net_assets_pct=text(residual / nav * 100))
        account['position_totals'] = totals
        return result
    except (KeyError, IndexError, TypeError):
        raise CalculationError('HOLDINGS_INPUT_INVALID') from None


def daily_return_rate(case, gross):
    """Inherited long-stock capital basis; caller supplies normalized ordering keys."""
    try:
        q, p, gain = rational(case['opening']['quantity']), rational(case['opening']['price']), rational(gross)
        require(q >= 0 and p >= 0, 'LONG_CAPITAL_DOMAIN')
        fills = case['executions']
        require(isinstance(fills, list) and len(fills) <= 10000, 'EXECUTION_RESOURCE_BOUND')
        capital, position = q * p, q
        for fill in sorted(fills, key=lambda f: f['timestamp']):
            size, price = rational(fill['quantity']), rational(fill['price'])
            require(size > 0 and price >= 0, 'EXECUTION_DOMAIN')
            if fill['side'] == 'BUY':
                capital += size * price
                position += size
            elif fill['side'] == 'SELL':
                position -= size
            else:
                raise CalculationError('EXECUTION_SIDE_INVALID')
            if position < 0:
                return None
        if capital <= 0:
            return None
        return {'denominator': str(decimal_result(capital)),
                'percent': str(decimal_result(gain / capital * 100)),
                'basis': 'gross_pnl/(prior_close_market_value+new_long_purchase_amount)'}
    except (KeyError, TypeError):
        raise CalculationError('RETURN_INPUT_INVALID') from None
