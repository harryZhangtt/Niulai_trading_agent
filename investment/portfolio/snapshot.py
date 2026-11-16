"""Pure adapter for an already acquired Tiger snapshot and its gateway receipt.

No provider, credential, file, mutation or replay operation is exposed here.
The caller owns private evidence custody and admission; supplied objects are
not an authenticated gateway receipt or proof that a live query took place.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re

from niulai.holdings.analytics import build


class SnapshotError(ValueError):
    """Closed diagnostic codes; never include account data in exceptions."""

    def __init__(self, code, *, missing_security_types=()):
        super().__init__(code)
        self.missing_security_types = tuple(missing_security_types)


def require(condition, code):
    if not condition:
        raise SnapshotError(code)


def digest(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise SnapshotError('SNAPSHOT_JSON_INVALID') from None
    require(len(raw) <= 2_000_000, 'SNAPSHOT_SIZE_LIMIT')
    return hashlib.sha256(raw).hexdigest()


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.tzinfo is not None, 'SNAPSHOT_TIME_INVALID')
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise SnapshotError('SNAPSHOT_TIME_INVALID') from None


def currency(value):
    """Absent currency is unknown; malformed currency is never an identity."""
    require(value is None or (isinstance(value, str) and
            re.fullmatch(r'[A-Z]{3}', value) is not None),
            'SNAPSHOT_CURRENCY_INVALID')


def position_identity(row):
    identifier = row.get('contractId')
    require(identifier is None or (type(identifier) in (str, int)
            and bool(identifier) and (not isinstance(identifier, str)
                                     or (bool(identifier.strip()) and identifier == identifier.strip()))),
            'SNAPSHOT_POSITION_IDENTITY_INVALID')
    symbol = row.get('symbol')
    require(symbol is None or (isinstance(symbol, str) and bool(symbol.strip())),
            'SNAPSHOT_POSITION_IDENTITY_INVALID')
    for key in ('expiry', 'putCall'):
        require(row.get(key) is None or isinstance(row[key], str),
                'SNAPSHOT_POSITION_IDENTITY_INVALID')
    require(row.get('strike') is None or type(row['strike']) in (str, int, float),
            'SNAPSHOT_POSITION_IDENTITY_INVALID')
    if identifier is not None:
        # Contract identity is account-wide, even when currencies disagree.
        return ('contract', str(identifier))
    require(bool(symbol), 'SNAPSHOT_POSITION_IDENTITY_INVALID')
    if row['securityType'] == 'OPT':
        require(bool(row.get('expiry')) and row.get('strike') is not None
                and row.get('putCall') in ('PUT', 'CALL', 'P', 'C'),
                'SNAPSHOT_POSITION_IDENTITY_INVALID')
    strike = row.get('strike')
    if strike is not None:
        try:
            strike = Decimal(str(strike))
            require(strike.is_finite() and strike >= 0, 'SNAPSHOT_POSITION_IDENTITY_INVALID')
        except InvalidOperation:
            raise SnapshotError('SNAPSHOT_POSITION_IDENTITY_INVALID') from None
    right = {'PUT': 'P', 'CALL': 'C'}.get(row.get('putCall'), row.get('putCall'))
    return ('terms', symbol, row['securityType'], row.get('expiry'),
            strike, right, row.get('currency'))


def arithmetic_precision(value):
    """Keep monetary sums exact beyond Decimal's default 28 significant digits.

    Ratios use at least 50 digits. JSON byte admission already bounds input;
    extreme exponent expansion is additionally bounded before arithmetic.
    Invalid measurements remain unavailable in the maintained analytics.
    """
    integers, fractions = 1, 0
    count = 0
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif type(item) in (str, int, float):
            try:
                number = Decimal(str(item))
            except InvalidOperation:
                continue
            if not number.is_finite():
                continue
            exponent = number.as_tuple().exponent
            require(abs(exponent) <= 4096 and len(number.as_tuple().digits) <= 4096,
                    'SNAPSHOT_AMOUNT_SIZE_LIMIT')
            integers = max(integers, number.adjusted() + 1)
            fractions = max(fractions, -exponent)
            count += 1
    # Carry digits for adding all admitted values, plus room for multiplication.
    return max(50, 2 * (integers + fractions) + len(str(max(count, 1))) + 8)


def admit_snapshot(envelope, receipt, *, as_of, max_age_seconds=300):
    """Map the gateway's single-account data to analytics.accountResults.

    Freshness here bounds query age only. It does not establish quote age,
    historical PIT validity, full-account coverage or lease-release completion.
    """
    source_hash = digest(envelope)
    receipt_hash = digest(receipt)
    require(type(max_age_seconds) is int and 0 <= max_age_seconds <= 86400,
            'SNAPSHOT_AGE_POLICY_INVALID')
    require(isinstance(receipt, dict) and receipt.get('status') == 'queried'
            and receipt.get('mode') == 'query' and receipt.get('tool') == 'snapshot'
            and receipt.get('source_read_status') == 'complete'
            and receipt.get('committed') is True and receipt.get('release_requested') is True
            and receipt.get('holdings_read') is True and receipt.get('assets_read') is True
            and receipt.get('reconciliation_required', False) is False
            and isinstance(receipt.get('attempt_id'), str) and bool(receipt['attempt_id']),
            'SNAPSHOT_RECEIPT_UNCONFIRMED')
    require(isinstance(envelope, dict) and type(envelope.get('schema_version')) is int
            and envelope['schema_version'] == 1 and envelope.get('provider') == 'tiger'
            and envelope.get('tool') == 'snapshot'
            and envelope.get('source_read_status') == 'complete'
            and envelope.get('cached_fallback_used') is False,
            'SNAPSHOT_READ_INCOMPLETE')
    checkpoint = envelope.get('checkpoint')
    if checkpoint is not None:
        require(isinstance(checkpoint, dict)
                and set(checkpoint) == {'state', 'attempt_id', 'receipt_sha256'}
                and checkpoint.get('state') == 'committed',
                'SNAPSHOT_CHECKPOINT_UNCONFIRMED')
        require(checkpoint['attempt_id'] == receipt['attempt_id']
                and checkpoint['receipt_sha256'] == receipt_hash,
                'SNAPSHOT_CHECKPOINT_MISMATCH')
    request = envelope.get('request')
    require(isinstance(request, dict) and set(request) == {'tool', 'arguments'}
            and request['tool'] == 'snapshot' and isinstance(request['arguments'], dict)
            and set(request['arguments']) == {'security_types'}, 'SNAPSHOT_REQUEST_INVALID')
    types = request['arguments']['security_types']
    require(isinstance(types, list) and types
            and all(isinstance(t, str) and t in {'STK', 'OPT', 'FUT', 'FUND'} for t in types)
            and len(set(types)) == len(types), 'SNAPSHOT_REQUEST_INVALID')
    data = envelope.get('data')
    require(isinstance(data, dict) and set(data) == {'holdings', 'assets'},
            'SNAPSHOT_DATA_INVALID')
    holding, asset = data['holdings'], data['assets']
    for item in (holding, asset):
        require(isinstance(item, dict) and item.get('ok') is True
                and item.get('sourceReadStatus') == 'complete'
                and item.get('accountIdentityChecked') is True,
                'SNAPSHOT_ACCOUNT_UNVERIFIED')
    require(isinstance(holding.get('accountRef'), str) and bool(holding['accountRef'])
            and holding['accountRef'] == asset.get('accountRef'), 'SNAPSHOT_ACCOUNT_MISMATCH')
    require(holding.get('cachedFallbackUsed') is False
            and holding.get('freshSourceResponse') is True, 'SNAPSHOT_CACHED_READ_REJECTED')
    coverage = holding.get('coverage')
    if isinstance(coverage, dict) and isinstance(coverage.get('successfulSecurityTypes'), list):
        successful = coverage['successfulSecurityTypes']
        missing = [kind for kind in types if kind not in successful]
        if missing:
            raise SnapshotError('SNAPSHOT_TYPE_COVERAGE_INCOMPLETE', missing_security_types=missing)
    require(isinstance(coverage, dict) and coverage.get('requestedSecurityTypes') == types
            and coverage.get('successfulSecurityTypes') == types
            and coverage.get('failedSecurityTypes') == [], 'SNAPSHOT_TYPE_COVERAGE_INCOMPLETE')
    rows = holding.get('positions')
    require(isinstance(rows, list) and all(isinstance(p, dict) for p in rows)
            and type(coverage.get('positionCount')) is int
            and coverage['positionCount'] == len(rows), 'SNAPSHOT_POSITIONS_INVALID')
    require(all(isinstance(p.get('securityType'), str) and p['securityType'] in types
                for p in rows), 'SNAPSHOT_POSITION_SCOPE_MISMATCH')
    for row in rows:
        currency(row.get('currency'))
    identities = [position_identity(p) for p in rows]
    require(len(set(identities)) == len(identities), 'SNAPSHOT_POSITION_IDENTITY_INVALID')
    reads = holding.get('typeReads')
    require(isinstance(reads, list) and len(reads) == len(types)
            and all(isinstance(r, dict) and r.get('ok') is True for r in reads)
            and [r.get('securityType') for r in reads] == types,
            'SNAPSHOT_TYPE_COVERAGE_INCOMPLETE')
    require(all(type(r.get('positionCount')) is int and r['positionCount'] ==
                sum(p['securityType'] == r['securityType'] for p in rows) for r in reads),
            'SNAPSHOT_TYPE_COUNT_MISMATCH')
    now = timestamp(as_of)
    completed = timestamp(envelope.get('query_completed_at'))
    started = timestamp(envelope.get('query_started_at'))
    require(started <= completed, 'SNAPSHOT_TIME_ORDER_INVALID')
    for moment in (completed, timestamp(holding.get('queryCompletedAt')),
                   timestamp(asset.get('queryCompletedAt'))):
        require(started <= moment <= completed, 'SNAPSHOT_TIME_ORDER_INVALID')
        require(0 <= (now - moment).total_seconds() <= max_age_seconds,
                'SNAPSHOT_QUERY_STALE_OR_FUTURE')
    observation = envelope.get('quote_observation')
    quote = {'quote_at': None, 'cutoff': None, 'freshness': 'unknown',
             'cutoff_policy': 'inclusive', 'authority': 'caller_supplied_unverified'}
    if observation is not None:
        require(isinstance(observation, dict) and set(observation) == {'quote_at', 'cutoff'},
                'SNAPSHOT_QUOTE_OBSERVATION_INVALID')
        quote_at = timestamp(observation['quote_at']) if observation['quote_at'] is not None else None
        cutoff = timestamp(observation['cutoff']) if observation['cutoff'] is not None else None
        require(quote_at is None or quote_at <= completed, 'SNAPSHOT_QUOTE_TIME_FUTURE')
        require(cutoff is None or cutoff <= now, 'SNAPSHOT_QUOTE_CUTOFF_FUTURE')
        quote.update(quote_at=observation['quote_at'], cutoff=observation['cutoff'])
        if quote_at is not None and cutoff is not None:
            quote['freshness'] = 'at_or_after_cutoff' if quote_at >= cutoff else 'stale'
    summary = asset.get('summary')
    require(summary is None or (isinstance(summary, dict)
            and isinstance(summary.get('amounts'), dict)), 'SNAPSHOT_ASSET_SUMMARY_INVALID')
    if summary is not None:
        currency(summary.get('currency'))
    arithmetic_precision(envelope)
    mapped_holding, mapped_asset = deepcopy(holding), deepcopy(asset)
    # prime_assets can provide segments without an aggregate summary. Keep NAV
    # unknown; never manufacture a summary by adding segments/currencies.
    if summary is None:
        mapped_asset['summary'] = {}
    return {'holdings': {'accountResults': [mapped_holding]},
            'assets': {'accountResults': [mapped_asset]},
            'provenance': {'snapshot_sha256': source_hash, 'receipt_sha256': receipt_hash,
                           'gateway_attempt_id': receipt['attempt_id'],
                           'query_completed_at': envelope['query_completed_at'],
                           'analyzed_as_of': as_of, 'max_query_age_seconds': max_age_seconds,
                           'requested_security_types': list(types),
                           'successful_security_types': list(coverage['successfulSecurityTypes']),
                           'failed_security_types': list(coverage['failedSecurityTypes']),
                           'position_count': len(rows), 'type_reads': deepcopy(reads),
                           'quote_observation': quote,
                           'source_authority': 'caller_supplied_unverified',
                           'source_authentication_verified': False,
                           'live_read_verified': False,
                           'lease_release_verified': False}}


def analyze_admitted(admitted, taxonomy):
    """Reuse the maintained arithmetic unchanged; retain unknown measurements."""
    taxonomy_hash = digest(taxonomy)
    require(isinstance(taxonomy, dict), 'SNAPSHOT_TAXONOMY_INVALID')
    require(isinstance(admitted, dict) and isinstance(admitted.get('provenance'), dict)
            and isinstance(admitted['provenance'].get('analyzed_as_of'), str)
            and isinstance(admitted['provenance'].get('quote_observation'), dict),
            'SNAPSHOT_ANALYTICS_INPUT_INVALID')
    try:
        precision = max(arithmetic_precision(admitted), arithmetic_precision(taxonomy))
        with localcontext() as context:
            context.prec = precision
            result = build(admitted['holdings'], admitted['assets'], deepcopy(taxonomy))
    except SnapshotError:
        raise
    except Exception:
        raise SnapshotError('SNAPSHOT_ANALYTICS_INPUT_INVALID') from None
    require(bool(result['accounts']) and all(not a['quality']['integrity_errors']
            for a in result['accounts']), 'SNAPSHOT_POSITION_IDENTITY_INVALID')
    # Expose exact decimal strings; do not call analytics.serial's float encoder.
    def exact(value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {k: exact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [exact(v) for v in value]
        return value
    result['generated_at'] = admitted['provenance']['analyzed_as_of']
    quote = admitted['provenance']['quote_observation']
    result['source_times']['quote_time'] = quote['quote_at']
    for account in result['accounts']:
        account['quality']['quote_time'] = quote['quote_at']
        account['quality']['quote_freshness'] = quote['freshness']
    return {'status': 'analyzed', 'analysis': exact(result),
            'provenance': {**admitted['provenance'], 'taxonomy_sha256': taxonomy_hash}}


def analyze_snapshot(envelope, receipt, taxonomy, *, as_of, max_age_seconds=300):
    return analyze_admitted(admit_snapshot(envelope, receipt, as_of=as_of,
                                          max_age_seconds=max_age_seconds), taxonomy)
