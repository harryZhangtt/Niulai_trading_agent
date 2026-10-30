#!/usr/bin/env python3
"""Deterministic standard-US-equity option expiry arithmetic; never a recommendation.

Public API: decode_packet(bytes) -> dict; calculate(dict) -> JSON-safe dict.
Money/stock prices/strikes are nonnegative decimal strings; counts are integers.
See test_options_payoff_checks.example_packet() for the exact small interface.
Supports one long call or one same-expiry bull call debit spread only. Confirmed
standard deliverable=100 shares is mandatory for live input eligibility. Research
mode may use an explicit hypothetical standard-100 assumption when unverified;
known adjusted contracts are always rejected.
Contract IDs must use canonical compact or six-character-root-padded OCC format;
encoded expiry/right/strike must agree with the leg. Distinct root/underlying
notations require an explicit verified root_mapping with a source reference.
Numeric/adjusted roots are outside this standard-contract calculator's scope.

Opening cash uses long ask, short bid, stock ask and explicit opening fees.
Budget cases include the requested budget and USD 1,000. Integer options and
explicit fractional-share increments prevent accidental fractional contracts.
Modeled quantity is affordability capped by relevant displayed size when known;
unknown depth is disclosed, not treated as proof of fillability. Unknown quote
timestamps may be null only in research mode, with freshness unknown. Never
substitute last-trade or response timestamps for bid/ask quote time. Live mode rejects
stale/future/non-realtime quotes; historical/indicative calculations remain
research-only. Quote freshness is measured against the caller's supplied actual
cutoff, not the machine clock. Feed identity and truth are not authenticated.

Expiry P&L is an intrinsic-value CASH-EQUIVALENT diagnostic with idle cash earning
zero. These US equity calls are physically settled: exercise/assignment funding,
early exercise, dividends, pin risk, closing/exercise fees and taxes are NOT
modeled. Opening affordability is NOT exercise affordability. No IV, probability,
pre-expiry mark, theta/vega estimate or expected return is inferred.
"""
import argparse
from datetime import date, datetime, timezone
from decimal import Context, Decimal, localcontext, ROUND_FLOOR
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

VERSION = '2026-10-24-options-payoff-1'
EXPIRY_ASSUMPTION = 'intrinsic_cash_equivalent_before_exercise_fees_and_taxes'
_CONTEXT = Context(prec=256)
_NUMBER = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z')
_TIME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z')


class OptionsCheckError(ValueError):
    def __init__(self, code, path, message):
        self.code, self.path, self.message = code, path, message
        super().__init__(f'{code} at {path}: {message}')
    def as_dict(self):
        return {'version': VERSION, 'status': 'error', 'error': {'code': self.code, 'path': self.path, 'message': self.message}}


def fail(code, path, message): raise OptionsCheckError(code, path, message)


def obj(value, path, keys):
    if type(value) is not dict or set(value) != set(keys):
        fail('shape', path, 'Expected exactly: ' + ', '.join(keys))
    return value


def text(value, path):
    if type(value) is not str or not value or value != value.strip() or len(value) > 4096 or any(ord(c) < 32 for c in value):
        fail('text', path, 'Expected bounded nonempty text')
    return value


def number(value, path, positive=False):
    if type(value) is not str or len(value) > 80 or not _NUMBER.fullmatch(value):
        fail('number', path, 'Expected finite nonnegative plain decimal string')
    result = Decimal(value)
    if len(result.as_tuple().digits) > 72 or (positive and result <= 0):
        fail('number', path, 'Number outside supported precision/positive range')
    return result


def count(value, path, minimum=0, maximum=10**9):
    if type(value) is not int or not minimum <= value <= maximum:
        fail('count', path, f'Expected integer in [{minimum},{maximum}]')
    return value


def stamp(value, path):
    if type(value) is not str or not _TIME.fullmatch(value):
        fail('timestamp', path, 'Expected strict RFC3339 timestamp with timezone')
    try: return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, OverflowError): fail('timestamp', path, 'Invalid timestamp')


def day(value, path):
    if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        fail('date', path, 'Expected ISO date')
    try: return date.fromisoformat(value)
    except ValueError: fail('date', path, 'Invalid date')


def parse_contract_id(value, path='$.contract_id'):
    """Parse a supported OCC ID; no broker prefixes, guesses or century pivot.

    Fixed suffix = YYMMDD + C/P + eight strike digits in thousandths. Years
    2000-2099 only. A root is 1-6 upper-case letters/digits/dots; padded IDs
    must pad that root to exactly six characters with trailing ASCII spaces.
    Parsing alone does NOT establish listing, deliverable or source authenticity.
    """
    text(value, path)
    if not 16 <= len(value) <= 21:
        fail('contract_symbol', path, 'Expected compact or 21-character padded OCC symbol')
    prefix, suffix = value[:-15], value[-15:]
    root = prefix.rstrip(' ')
    if (not re.fullmatch(r'[A-Z][A-Z0-9.]{0,5}', root)
            or (' ' in prefix and prefix != root.ljust(6))
            or not re.fullmatch(r'[0-9]{6}[CP][0-9]{8}', suffix)):
        fail('contract_symbol', path, 'Malformed OCC root, padding, date/right or eight-digit strike')
    try:
        expiry = date(2000 + int(suffix[:2]), int(suffix[2:4]), int(suffix[4:6]))
    except ValueError:
        fail('contract_symbol', path, 'OCC symbol encodes an invalid calendar date')
    strike = Decimal(int(suffix[7:])) / Decimal(1000)
    if strike <= 0:
        fail('contract_symbol', path, 'OCC strike must be positive and uses thousandths, not contract dollars')
    return {'root': root, 'expiry': expiry, 'right': 'call' if suffix[6] == 'C' else 'put',
            'strike': strike, 'canonical_id': root + suffix}


def bind_contract_id(value, path, subject, expiry, strike):
    parsed = parse_contract_id(value['contract_id'], path + '.contract_id')
    if parsed['expiry'] != expiry or parsed['strike'] != strike or parsed['right'] != value['right']:
        fail('contract_identity', path, 'Encoded expiry/right/strike differs from separate leg fields')
    # Digits can indicate nonstandard roots; this narrow calculator cannot prove
    # their deliverable. Do not let a standard100 boolean bypass that uncertainty.
    if any(c.isdigit() for c in parsed['root']):
        fail('unsupported_root', path, 'Numeric/nonstandard option roots require an unsupported contract-adjustment workflow')
    mapping = value.get('root_mapping')
    if 'root_mapping' in value:
        obj(mapping, path + '.root_mapping', ('root', 'underlying', 'verified', 'source_ref'))
        text(mapping['source_ref'], path + '.root_mapping.source_ref')
        if mapping['verified'] is not True or mapping['root'] != parsed['root'] or mapping['underlying'] != subject:
            fail('root_mapping', path, 'Explicit verified mapping must bind the exact root and underlying')
    elif parsed['root'] != subject:
        fail('root_mapping', path, 'Distinct root and underlying require an explicit verified source-backed mapping')
    return parsed['canonical_id']


def out(value):
    if not value: return '0'
    result = format(value, 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def seconds(delta):
    return Decimal(delta.days) * 86400 + Decimal(delta.seconds) + Decimal(delta.microseconds) / 1000000


def quote(value, path, cutoff, mode, policy):
    obj(value, path, ('bid', 'ask', 'bid_size', 'ask_size', 'timestamp', 'feed_status', 'feed_id', 'source_ref'))
    bid, ask = number(value['bid'], path + '.bid'), number(value['ask'], path + '.ask', True)
    if bid > ask: fail('crossed_quote', path, 'Bid exceeds ask')
    for key in ('bid_size', 'ask_size'):
        if value[key] is not None: count(value[key], path + '.' + key)
    for key in ('feed_id', 'source_ref'): text(value[key], path + '.' + key)
    if value['feed_status'] not in ('realtime', 'delayed', 'historical', 'indicative', 'unknown'):
        fail('feed', path, 'Unsupported feed status')
    if value['timestamp'] is None and mode != 'live':
        timestamp, age = None, None
    else:
        timestamp = stamp(value['timestamp'], path + '.timestamp')
        age = seconds(cutoff - timestamp)
    if age is not None and age < 0: fail('future_quote', path, 'Quote was unavailable at the supplied cutoff')
    if mode == 'live':
        if value['feed_status'] != 'realtime': fail('feed', path, 'Live mode requires a declared realtime feed')
        if age > policy['max_age_seconds']: fail('stale_quote', path, 'Quote exceeds configured freshness limit')
    return {'bid': bid, 'ask': ask, 'timestamp': timestamp, 'age_seconds': age,
            'bid_size': value['bid_size'], 'ask_size': value['ask_size'], 'feed_status': value['feed_status'],
            'feed_id': value['feed_id'], 'source_ref': value['source_ref']}


def leg(value, path, subject, cutoff, mode, policy):
    base_keys = ('underlying', 'contract_id', 'right', 'strike', 'expiry', 'exercise_style',
                 'multiplier', 'standard_deliverable_confirmed', 'quote')
    extra_keys = ('deliverable_assumption', 'adjustment_status')
    expected_keys = base_keys
    if type(value) is dict:
        if any(key in value for key in extra_keys): expected_keys += extra_keys
        if 'root_mapping' in value: expected_keys += ('root_mapping',)
    obj(value, path, expected_keys)
    if value['underlying'] != subject: fail('underlying', path, 'Leg underlying differs from packet subject')
    text(value['contract_id'], path + '.contract_id')
    if value['right'] != 'call' or value['exercise_style'] != 'american':
        fail('contract', path, 'Only standard US equity American calls are supported')
    if type(value['multiplier']) is not int or value['multiplier'] != 100:
        fail('deliverable', path, 'Only standard-100 arithmetic supported')
    verified = value['standard_deliverable_confirmed'] is True
    if verified:
        if value.get('adjustment_status', 'not_adjusted') != 'not_adjusted' or value.get('deliverable_assumption') is not None:
            fail('deliverable', path, 'Verified standard declaration conflicts with adjustment/assumption fields')
    elif not (value['standard_deliverable_confirmed'] is False and mode != 'live'
              and value.get('deliverable_assumption') == 'hypothetical_standard_100_shares'
              and value.get('adjustment_status') in ('not_adjusted', 'unknown')):
        fail('deliverable', path, 'Live requires verified standard100; research needs explicit hypothetical standard100 assumption, never known adjusted')
    expiry = day(value['expiry'], path + '.expiry')
    strike = number(value['strike'], path + '.strike', True)
    contract_id = bind_contract_id(value, path, subject, expiry, strike)
    q = quote(value['quote'], path + '.quote', cutoff, mode, policy)
    if q['timestamp'] is not None and q['timestamp'].date() > expiry: fail('expired_quote', path, 'Quote timestamp is after expiry date')
    if mode == 'live' and cutoff.date() > expiry: fail('expired_contract', path, 'Live contract has expired')
    return {'strike': strike, 'expiry': expiry, 'quote': q, 'contract_id': contract_id, 'deliverable_verified': verified}


def affordable(budget, fixed, unit, increment):
    if budget <= fixed: return Decimal(0)
    quantity = ((budget - fixed) / unit / increment).to_integral_value(rounding=ROUND_FLOOR) * increment
    if quantity > 10**9: fail('quantity', '$.budget', 'Modeled quantity exceeds supported bound')
    return quantity


def option_case(budget, debit, fees, legs, long, short, prices, depth, depth_complete):
    fixed, variable = fees['option_fixed_per_leg'] * legs, fees['option_per_contract_per_leg'] * legs
    maximum = int(affordable(budget, fixed, debit * 100 + variable, Decimal(1)))
    contracts = maximum if depth is None else min(maximum, depth)
    opening_fees = fixed + variable * contracts if contracts else Decimal(0)
    opening_cost = debit * 100 * contracts + opening_fees
    width = None if short is None else short['strike'] - long['strike']
    max_gain = None if width is None and contracts else (Decimal(0) if not contracts else width * 100 * contracts - opening_cost)
    breakeven = None if not contracts else long['strike'] + opening_cost / (100 * contracts)
    # A fee-dominated vertical may never reach zero P&L despite a valid premium debit.
    if width is not None and max_gain < 0: breakeven = None
    outcomes = []
    for price in prices:
        intrinsic = max(price - long['strike'], Decimal(0))
        if short is not None: intrinsic -= max(price - short['strike'], Decimal(0))
        payoff = intrinsic * 100 * contracts
        pnl = payoff - opening_cost
        outcomes.append({'expiry_stock_price': out(price), 'expiry_intrinsic_value': out(payoff),
                         'pnl': out(pnl), 'ending_wealth': out(budget + pnl)})
    return {'max_affordable_contracts': maximum, 'displayed_depth_capacity_contracts': depth if depth_complete else None,
            'known_leg_depth_cap_contracts': depth, 'displayed_depth_complete': depth_complete,
            'modeled_contracts': contracts, 'opening_fees': out(opening_fees), 'opening_cash_required': out(opening_cost),
            'unallocated_cash': out(budget - opening_cost), 'breakeven_stock_price': None if breakeven is None else out(breakeven),
            'max_loss_amount': out(opening_cost), 'max_profit': None if max_gain is None else out(max_gain),
            'max_profit_kind': 'unbounded' if max_gain is None else ('no_position' if not contracts else 'bounded'),
            'positive_profit_possible_at_expiry': bool(contracts and (max_gain is None or max_gain > 0)),
            'grid': outcomes}


def share_case(budget, ask, fees, increment, prices, depth):
    maximum = affordable(budget, fees['stock_fixed'], ask + fees['stock_per_share'], increment)
    shares = maximum if depth is None else min(maximum, (Decimal(depth) / increment).to_integral_value(rounding=ROUND_FLOOR) * increment)
    opening_fees = fees['stock_fixed'] + fees['stock_per_share'] * shares if shares else Decimal(0)
    opening_cost = shares * ask + opening_fees
    return {'max_affordable_shares': out(maximum), 'displayed_depth_capacity_shares': depth, 'modeled_shares': out(shares),
            'opening_fees': out(opening_fees), 'opening_cash_required': out(opening_cost), 'unallocated_cash': out(budget - opening_cost),
            'breakeven_stock_price': None if not shares else out(opening_cost / shares),
            'max_loss_amount': out(opening_cost), 'max_profit': None if shares else '0',
            'max_profit_kind': 'unbounded' if shares else 'no_position',
            'grid': [{'expiry_stock_price': out(price), 'pnl': out(shares * price - opening_cost),
                      'ending_wealth': out(budget + shares * price - opening_cost)} for price in prices]}


def _calculate(packet):
    obj(packet, '$', ('version', 'subject', 'as_of', 'mode', 'quote_policy', 'budget', 'fees',
                      'strategy', 'underlying_quote', 'share_comparison', 'expiry_assumption', 'expiry_stock_prices'))
    if packet['version'] != VERSION: fail('version', '$', 'Unsupported packet version')
    subject, cutoff = text(packet['subject'], '$.subject'), stamp(packet['as_of'], '$.as_of')
    mode = packet['mode']
    if mode not in ('live', 'historical', 'indicative'): fail('mode', '$', 'Expected live, historical or indicative')
    policy = obj(packet['quote_policy'], '$.quote_policy', ('max_age_seconds', 'max_quote_skew_seconds'))
    count(policy['max_age_seconds'], '$.quote_policy.max_age_seconds', 1, 86400)
    count(policy['max_quote_skew_seconds'], '$.quote_policy.max_quote_skew_seconds', 0, policy['max_age_seconds'])
    obj(packet['budget'], '$.budget', ('amount', 'currency', 'idle_cash_return'))
    if packet['budget']['currency'] != 'USD' or packet['budget']['idle_cash_return'] != '0':
        fail('budget', '$.budget', 'Only USD and explicit zero return on idle cash are supported')
    amount = number(packet['budget']['amount'], '$.budget.amount', True)
    fee_keys = ('option_per_contract_per_leg', 'option_fixed_per_leg', 'stock_per_share', 'stock_fixed')
    obj(packet['fees'], '$.fees', fee_keys)
    fees = {key: number(packet['fees'][key], '$.fees.' + key) for key in fee_keys}
    strategy = obj(packet['strategy'], '$.strategy', ('kind', 'long_leg', 'short_leg'))
    if strategy['kind'] not in ('long_call', 'bull_call_debit_spread'): fail('strategy', '$.strategy', 'Unsupported option topology')
    if (strategy['kind'] == 'long_call') != (strategy['short_leg'] is None):
        fail('strategy', '$.strategy', 'Long call requires no short leg; vertical requires exactly one short leg')
    long = leg(strategy['long_leg'], '$.strategy.long_leg', subject, cutoff, mode, policy)
    short = None if strategy['short_leg'] is None else leg(strategy['short_leg'], '$.strategy.short_leg', subject, cutoff, mode, policy)
    if short is not None:
        if long['expiry'] != short['expiry'] or long['strike'] >= short['strike'] or long['contract_id'] == short['contract_id']:
            fail('spread', '$.strategy', 'Require distinct same-expiry calls, long lower strike and short higher strike')
    obj(packet['underlying_quote'], '$.underlying_quote', ('symbol', 'quote'))
    if packet['underlying_quote']['symbol'] != subject: fail('underlying', '$.underlying_quote', 'Underlying quote identity mismatch')
    stock = quote(packet['underlying_quote']['quote'], '$.underlying_quote.quote', cutoff, mode, policy)
    qs = [stock, long['quote']] + ([] if short is None else [short['quote']])
    skew = None if any(q['timestamp'] is None for q in qs) else seconds(max(q['timestamp'] for q in qs) - min(q['timestamp'] for q in qs))
    if mode == 'live' and skew > policy['max_quote_skew_seconds']:
        fail('asynchronous_quotes', '$', 'Quote timestamps exceed configured cross-leg/stock skew')
    obj(packet['share_comparison'], '$.share_comparison', ('fractional', 'increment'))
    fractional = packet['share_comparison']['fractional']
    if type(fractional) is not bool: fail('fractional', '$.share_comparison', 'Explicit boolean fractional-share choice required')
    increment = number(packet['share_comparison']['increment'], '$.share_comparison.increment', True)
    if (not fractional and increment != 1) or (fractional and (increment > 1 or (Decimal(1) / increment) != (Decimal(1) / increment).to_integral_value())):
        fail('fractional', '$.share_comparison', 'Use increment 1 for integer shares; fractional increment must divide one share exactly')
    if packet['expiry_assumption'] != EXPIRY_ASSUMPTION:
        fail('expiry_assumption', '$', 'Explicit intrinsic cash-equivalent assumption required')
    grid = packet['expiry_stock_prices']
    if type(grid) is not list or not 1 <= len(grid) <= 200: fail('grid', '$', 'Supply 1..200 expiry stock-price scenarios')
    prices = sorted(number(price, '$.expiry_stock_prices') for price in grid)
    if len(set(prices)) != len(prices): fail('grid', '$', 'Duplicate expiry prices')
    with localcontext(_CONTEXT):
        debit = long['quote']['ask'] - (short['quote']['bid'] if short else Decimal(0))
        if debit <= 0 or (short and debit >= short['strike'] - long['strike']):
            fail('debit', '$.strategy', 'Conservative premium debit must be positive and strictly below spread width')
        relevant_depth = [long['quote']['ask_size']] + ([] if short is None else [short['quote']['bid_size']])
        depth_complete = all(value is not None for value in relevant_depth)
        known_depths = [value for value in relevant_depth if value is not None]
        depth = min(known_depths) if known_depths else None
        budgets = {}
        for name, budget in (('requested', amount), ('usd_1000', Decimal(1000))):
            budgets[name] = {'budget': out(budget), 'options': option_case(budget, debit, fees, 1 if short is None else 2, long, short, prices, depth, depth_complete),
                             'shares': share_case(budget, stock['ask'], fees, increment, prices, stock['ask_size'])}
    warnings = [
        'Payoff scenarios are conditional, not probabilities or a recommendation; no pre-expiry valuation or IV model is supplied.',
        'Physical exercise/assignment cash requirements and early assignment, dividends, pin risk, closing/exercise fees and taxes are excluded. Opening affordability does not establish exercise affordability.',
        'Displayed quotes and size are not guaranteed fills. Feed identity, standard deliverable and source truth require independent verification.',
        'Residual cash earns zero; same-budget comparisons use ask/bid plus declared opening fees.']
    if not depth_complete or stock['ask_size'] is None: warnings.append('Relevant displayed depth is unknown; modeled affordability is not verified executable size.')
    if long['expiry'] <= cutoff.date(): warnings.append('Expiry is on/before the cutoff date; session-specific expiry timing requires review.')
    if mode != 'live': warnings.append('Historical/indicative input: research-only calculation, not a current trade assessment.')
    if any(q['age_seconds'] is None for q in qs): warnings.append('Quote timestamp is unknown: freshness and simultaneity cannot be verified; collection time and last trade time are not substitutes.')
    if not long['deliverable_verified'] or (short and not short['deliverable_verified']): warnings.append('Hypothetical standard100 deliverable assumption only: actual contract terms are unverified; results are not an executable contract assessment.')
    if any(q['age_seconds'] is not None and q['age_seconds'] > policy['max_age_seconds'] for q in qs): warnings.append('Research inputs include quotes older than the live freshness threshold.')
    if skew is not None and skew > policy['max_quote_skew_seconds']: warnings.append('Research quotes are asynchronous beyond the live skew threshold.')
    eligible = mode == 'live' and depth_complete and depth is not None and depth > 0 and stock['ask_size'] is not None and stock['ask_size'] > 0 and long['expiry'] > cutoff.date()
    result = {'version': VERSION, 'status': 'calculated', 'subject': subject, 'as_of': packet['as_of'],
              'mode': mode, 'research_only': not eligible, 'live_input_gate_passed': eligible, 'recommendation': None,
              'strategy': strategy['kind'], 'expiry': long['expiry'].isoformat(), 'contract_multiplier': 100,
              'conservative_debit_per_share': out(debit), 'stock_ask': out(stock['ask']),
              'contract_deliverable_verified': long['deliverable_verified'] and (short is None or short['deliverable_verified']),
              'quote_freshness': 'unknown' if any(q['age_seconds'] is None for q in qs) else ('within_declared_limit' if all(q['age_seconds'] <= policy['max_age_seconds'] for q in qs) else 'stale'),
              'quote_provenance': [{'timestamp': None if q['timestamp'] is None else q['timestamp'].isoformat(), 'age_seconds': None if q['age_seconds'] is None else out(q['age_seconds']),
                                    'feed_status': q['feed_status'], 'feed_id': q['feed_id'], 'source_ref': q['source_ref']} for q in qs],
              'quote_skew_seconds': None if skew is None else out(skew), 'budget_cases': budgets, 'warnings': warnings,
              'semantic_truth_verified': False, 'expiry_assumption': EXPIRY_ASSUMPTION}
    result['input_sha256'] = hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return result


def calculate(packet):
    with localcontext(_CONTEXT):
        return _calculate(packet)


def decode_packet(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: fail('duplicate_key', '$', 'Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value): fail('json_number', '$', 'Use decimal strings, not floating/NaN/Infinity JSON numbers')
    def integer(value):
        if len(value) > 10: fail('json_number', '$', 'JSON integers are bounded counts')
        return int(value)
    try: packet = json.loads(raw, object_pairs_hook=pairs, parse_float=invalid, parse_constant=invalid, parse_int=integer)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, RecursionError) as exc: fail('json', '$', 'Invalid UTF-8 JSON: ' + str(exc))
    if type(packet) is not dict: fail('shape', '$', 'Expected a packet object')
    return packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try: result, code = calculate(decode_packet(Path(args.input).read_bytes())), 0
    except OptionsCheckError as exc: result, code = exc.as_dict(), 2
    except OSError as exc: result, code = OptionsCheckError('input_io', '$', str(exc)).as_dict(), 2
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + '.', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False, allow_nan=False); handle.write('\n')
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return code


if __name__ == '__main__': sys.exit(main())
