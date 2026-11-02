#!/usr/bin/env python3
"""Freeze a declared series/period scope using only available reported vintages.

No downloads, forecasts, statistical filters, cycle labels or source authentication.
Public API: calculate(packet) -> JSON-safe result; decode_packet(raw) -> packet.
All values are finite decimal strings. `period` has inclusive ISO date bounds.
Expected rows: series_id, period, unit. Observations add value, available_at,
vintage_id, source_ref. Observations must belong to the declared expected scope.
The selected-view hash excludes later vintages, so valid future data cannot
rewrite the frozen historical view. Preserve the original packet separately.
"""

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

VERSION = '2026-10-23-cycle-vintage-1'
_DECIMAL = re.compile(r'[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z')
_DATE = re.compile(r'\d{4}-\d{2}-\d{2}\Z', re.ASCII)
_TIME = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z', re.ASCII)


class VintageError(ValueError):
    pass


def _object(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise VintageError(label + ': exact fields required: ' + ', '.join(fields))
    return value


def _text(value, label):
    if (type(value) is not str or not value.strip() or value != value.strip()
            or len(value) > 2048 or any(ord(c) < 32 for c in value)):
        raise VintageError(label + ': nonempty bounded text required')
    return value


def _date(value):
    if type(value) is not str or not _DATE.fullmatch(value):
        raise VintageError('period: YYYY-MM-DD required')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise VintageError('period: invalid date') from exc


def _time(value):
    if type(value) is not str or not _TIME.fullmatch(value):
        raise VintageError('timestamp: RFC3339 with seconds and timezone required')
    try:
        # Reject UTC offsets which datetime would permissively normalize.
        if value[-1] != 'Z' and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            raise ValueError('invalid offset')
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise VintageError('timestamp: invalid date/time') from exc


def _utc(value):
    return value.isoformat().replace('+00:00', 'Z')


def _value(value):
    if type(value) is not str or len(value) > 80 or not _DECIMAL.fullmatch(value):
        raise VintageError('value: finite plain decimal string required')
    number = Decimal(value)
    if not number.is_finite():
        raise VintageError('value: finite decimal required')
    if not number:
        return '0'
    result = format(number, 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def _identity(row):
    sid = _text(row['series_id'], 'series_id')
    unit = _text(row['unit'], 'unit')
    period = _object(row['period'], ('start', 'end'), 'period')
    start, end = _date(period['start']), _date(period['end'])
    if end < start:
        raise VintageError('period: end precedes start')
    return (sid, start.isoformat(), end.isoformat()), unit, end


def _rows(value, label, minimum=0):
    if type(value) is not list or not minimum <= len(value) <= 100000:
        raise VintageError(label + ': bounded list required')
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def decode_packet(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise VintageError('duplicate JSON key: ' + key)
            result[key] = value
        return result

    def invalid(value):
        raise VintageError('nonstandard JSON constant: ' + value)

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise VintageError('invalid JSON') from exc


def calculate(packet):
    _object(packet, ('version', 'subject', 'as_of', 'expected', 'observations'), 'packet')
    if packet['version'] != VERSION:
        raise VintageError('unsupported version')
    subject = _text(packet['subject'], 'subject')
    cutoff = _time(packet['as_of'])
    scope = {}
    for row in _rows(packet['expected'], 'expected', 1):
        _object(row, ('series_id', 'period', 'unit'), 'expected row')
        key, unit, end = _identity(row)
        if key in scope:
            raise VintageError('duplicate expected series/period')
        scope[key] = (unit, end)

    observations = {}
    for row in _rows(packet['observations'], 'observations'):
        _object(row, ('series_id', 'period', 'unit', 'value', 'available_at',
                      'vintage_id', 'source_ref'), 'observation')
        key, unit, end = _identity(row)
        if key not in scope:
            raise VintageError('observation outside declared expected scope')
        if unit != scope[key][0]:
            raise VintageError('unit differs from declared series/period')
        released = _time(row['available_at'])
        if end > released.date():
            raise VintageError('reported period ends after release; forecasts must be stored separately')
        vintage = _text(row['vintage_id'], 'vintage_id')
        item = {'value': _value(row['value']), 'available_at': _utc(released),
                'vintage_id': vintage, 'source_ref': _text(row['source_ref'], 'source_ref')}
        identity = key + (vintage,)
        if identity in observations and observations[identity] != item:
            raise VintageError('conflicting duplicate vintage identity')
        observations[identity] = item

    eligible = {}
    for identity, item in observations.items():
        key = identity[:3]
        released = _time(item['available_at'])
        if released <= cutoff and scope[key][1] <= cutoff.date():
            eligible.setdefault(key, []).append((released, item))

    rows = []
    counts = {'selected': 0, 'missing_as_of': 0, 'pending_period': 0}
    for key in sorted(scope):
        row = {'series_id': key[0], 'period': {'start': key[1], 'end': key[2]},
               'unit': scope[key][0]}
        choices = eligible.get(key, [])
        if choices:
            newest = max(t for t, _ in choices)
            latest = [item for t, item in choices if t == newest]
            if len(latest) != 1:
                raise VintageError('ambiguous latest release: distinct vintages share a timestamp')
            row.update(status='selected', observation=latest[0])
        else:
            # A future row's mere existence must not alter historical coverage.
            row.update(status='pending_period' if scope[key][1] > cutoff.date() else 'missing_as_of',
                       observation=None)
        counts[row['status']] += 1
        rows.append(row)

    view = {'version': VERSION, 'subject': subject, 'as_of': _utc(cutoff), 'rows': rows}
    return {'version': VERSION, 'selected_view': view,
            'selected_view_sha256': hashlib.sha256(_canonical(view).encode()).hexdigest(),
            'coverage': {'expected': len(scope), **counts},
            'status': 'complete' if counts['selected'] == len(scope) else 'partial',
            'semantic_truth_verified': False,
            'meaning': 'Availability-consistent supplied data only; no cycle estimate or predictive-skill claim.'}


def _save(path, result):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=target.parent, delete=False) as stream:
            name = stream.name
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    code = 0
    try:
        result = calculate(decode_packet(Path(args.input).read_bytes()))
    except (VintageError, OSError, TypeError, ValueError) as exc:
        result = {'version': VERSION, 'status': 'error', 'error': str(exc)}
        code = 2
    _save(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
