#!/usr/bin/env python3
"""Compare two normalized supplied numeric observations, never fetch or average.

API: calculate(packet), decode_packet(raw); CLI: --input JSON --output JSON.
Required packet fields are shown in calculate(). Observation metadata must agree
exactly: subject, metric, definition, period {start,end}, unit, basis. Allowed
bases: close/quote/last/indicative/reported/estimate/calculated. Numeric values and
tolerances are plain decimal strings. Caller predeclares freshness and tolerances.
For option_quote, contract_key and side (bid/ask/mid/last/mark/settlement) must match. The caller must canonicalize
root, expiry, strike, put/call, exchange/currency and deliverable/multiplier into
contract_key; this module cannot authenticate that identity or option adjustments.
source.origin means original publisher/dataset identity, not a generic category.
Agreement means |a-b| <= max(abs_tol, rel_tol * max(|a|,|b|)). Matching source
origin, provider OR upstream_family cannot establish independent corroboration.
"""
import argparse
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

VERSION = '2026-10-24-evidence-crosscheck-1'
BASES = {'close', 'quote', 'last', 'indicative', 'reported', 'estimate', 'calculated'}
META = ('subject', 'metric', 'definition', 'unit', 'basis')
SOURCES = ('origin', 'provider', 'upstream_family', 'ref', 'sha256')


class CrosscheckError(ValueError):
    pass


def _object(value, required, optional=()):
    if type(value) is not dict or set(required) - set(value) or set(value) - set(required) - set(optional):
        raise CrosscheckError('Object has missing or unknown fields')
    return value


def _text(value):
    if value is None:
        return None
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise CrosscheckError('Metadata requires bounded nonempty text or null')
    return value


def _decimal(value, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not str or len(value) > 80 or not re.fullmatch(r'[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value):
        raise CrosscheckError('Finite plain decimal string required')
    return Decimal(value)


def _time(value):
    if value is None:
        return None
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value, re.ASCII):
        raise CrosscheckError('RFC3339 timestamp with timezone required')
    try:
        if value[-1] != 'Z' and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            raise ValueError('offset')
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise CrosscheckError('Invalid timestamp') from exc


def _period(value):
    if value is None:
        return None
    _object(value, (), ('start', 'end'))
    for key in ('start', 'end'):
        item = value.get(key)
        if item is not None:
            try:
                if type(item) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', item, re.ASCII):
                    raise ValueError('format')
                date.fromisoformat(item)
            except ValueError as exc:
                raise CrosscheckError('Invalid period date') from exc
    if any(value.get(k) is None for k in ('start', 'end')):
        return None
    if value['end'] < value['start']:
        raise CrosscheckError('Period end precedes start')
    return dict(value)


def _out(value):
    if value is None:
        return None
    if not value:
        return '0'
    result = format(value, 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def decode_packet(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CrosscheckError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise CrosscheckError('Nonstandard JSON constant: ' + value)
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CrosscheckError('Invalid JSON') from exc


def calculate(packet):
    _object(packet, ('version', 'as_of', 'comparison_kind', 'max_age_seconds', 'max_time_skew_seconds',
                     'absolute_tolerance', 'relative_tolerance', 'require_source_hashes', 'observations'))
    if packet['version'] != VERSION or packet['comparison_kind'] not in {'numeric', 'option_quote'}:
        raise CrosscheckError('Unsupported version/comparison kind')
    cutoff = _time(packet['as_of'])
    if cutoff is None:
        raise CrosscheckError('Decision cutoff required')
    for field in ('max_age_seconds', 'max_time_skew_seconds'):
        if type(packet[field]) is not int or packet[field] < 0:
            raise CrosscheckError('Nonnegative integer time limits required')
    absolute, relative = (_decimal(packet[k]) for k in ('absolute_tolerance', 'relative_tolerance'))
    if absolute < 0 or relative < 0 or type(packet['require_source_hashes']) is not bool:
        raise CrosscheckError('Nonnegative tolerances and boolean hash policy required')
    if type(packet['observations']) is not list or len(packet['observations']) != 2:
        raise CrosscheckError('Exactly two observations required')
    rows, missing, stale = [], [], []
    for i, raw in enumerate(packet['observations']):
        _object(raw, (), META + ('period', 'source', 'observed_at', 'available_at', 'value', 'contract_key', 'side'))
        row = {k: _text(raw.get(k)) for k in META + ('contract_key', 'side')}
        row['period'] = _period(raw.get('period'))
        if row['basis'] is not None and row['basis'] not in BASES:
            raise CrosscheckError('Unsupported observation basis')
        if packet['comparison_kind'] == 'option_quote' and row['side'] is not None and row['side'] not in {'bid', 'ask', 'mid', 'last', 'mark', 'settlement'}:
            raise CrosscheckError('Unsupported option quote side')
        source = {} if raw.get('source') is None else raw['source']
        _object(source, (), SOURCES)
        row['source'] = {k: _text(source.get(k)) for k in SOURCES}
        sha = row['source']['sha256']
        if sha is not None and not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise CrosscheckError('SHA256 must be 64 lowercase hexadecimal characters')
        row['value'] = _decimal(raw.get('value'), nullable=True)
        row['observed_at'], row['available_at'] = (_time(raw.get(k)) for k in ('observed_at', 'available_at'))
        for key in ('observed_at', 'available_at'):
            if row[key] is not None and row[key] > cutoff:
                raise CrosscheckError('Future observation/release at decision cutoff')
        if row['observed_at'] is not None and row['available_at'] is not None and row['available_at'] < row['observed_at']:
            raise CrosscheckError('Release precedes observation')
        needed = META + ('period', 'value', 'observed_at', 'available_at') + (('contract_key', 'side') if packet['comparison_kind'] == 'option_quote' else ())
        missing += [f'observations[{i}].{k}' for k in needed if row[k] is None]
        missing += [f'observations[{i}].source.{k}' for k in SOURCES if row['source'][k] is None and (k != 'sha256' or packet['require_source_hashes'])]
        if row['observed_at'] is not None and (cutoff - row['observed_at']).total_seconds() > packet['max_age_seconds']:
            stale.append(i)
        rows.append(row)
    result = {'version': VERSION, 'input_sha256': hashlib.sha256(_canonical(packet).encode()).hexdigest(),
              'status': 'unverified', 'reasons': [], 'semantic_truth_verified': False,
              'values': [_out(r['value']) for r in rows], 'sources': [r['source'] for r in rows]}
    if missing:
        result['reasons'] = ['missing_metadata_or_value'] + missing
        return result
    compare = META + ('period',) + (('contract_key', 'side') if packet['comparison_kind'] == 'option_quote' else ())
    mismatch = [k for k in compare if rows[0][k] != rows[1][k]]
    skew = abs((rows[0]['observed_at'] - rows[1]['observed_at']).total_seconds())
    if mismatch or skew > packet['max_time_skew_seconds']:
        result.update(status='not_comparable', reasons=mismatch + (['observed_time_skew'] if skew > packet['max_time_skew_seconds'] else []))
        return result
    if stale:
        result['reasons'] = ['stale_observation'] + [str(i) for i in stale]
        return result
    with localcontext() as context:
        context.prec = 256
        a, b = (r['value'] for r in rows)
        diff, scale = abs(a - b), max(abs(a), abs(b))
        bound = max(absolute, relative * scale)
        result.update(absolute_difference=_out(diff), allowed_difference=_out(bound))
        if diff > bound:
            result.update(status='disagreement', reasons=['outside_predeclared_tolerance'])
        else:
            shared = [k for k in ('origin', 'provider', 'upstream_family') if rows[0]['source'][k] == rows[1]['source'][k]]
            result.update(status='shared_upstream_corroboration' if shared else 'corroborated', reasons=['shared_' + k for k in shared])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args(); code = 0
    try:
        result = calculate(decode_packet(Path(args.input).read_bytes()))
    except (CrosscheckError, OSError, TypeError, ValueError) as exc:
        result = {'version': VERSION, 'status': 'error', 'error': str(exc)}; code = 2
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=target.parent, delete=False) as stream:
            name = stream.name; json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')
        os.replace(name, target)
    finally:
        if name and os.path.exists(name): os.unlink(name)
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
