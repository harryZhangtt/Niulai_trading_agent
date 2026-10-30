#!/usr/bin/env python3
"""Revisioned research evidence/assessment store; offline, additive, no trading.

Restore research.sqlite first. `commit` atomically applies a request's operations;
read/export never create or migrate a database. This validates storage/provenance,
not investment truth or full research-harness completion. Persist the resulting
SQLite through Library with a fresh version guard; local commit is not publication.
"""
import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

VERSION = '2026-10-20-research-store-1'

class StoreError(ValueError):
    pass


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise StoreError(name + ' must be nonempty text')
    return value


def integer(value, name):
    if type(value) is not int or value < 0:
        raise StoreError(name + ' must be a nonnegative integer')
    return value


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as exc:
        raise StoreError('Timezone-aware ISO timestamp required') from exc


def connect(path, readonly=False):
    path = Path(path).resolve()
    if not path.is_file():
        raise StoreError('Restore existing research.sqlite first')
    db = sqlite3.connect(path.as_uri() + ('?mode=ro' if readonly else '?mode=rw'), uri=True, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    required = {'securities', 'artifacts', 'job_runs'}
    present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not required <= present:
        db.close()
        raise StoreError('Not a restored Niulai research database')
    return db


DDL = [
    '''CREATE TABLE IF NOT EXISTS research_store_requests(
       request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, run_id TEXT NOT NULL,
       committed_at TEXT NOT NULL, receipt TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS research_store_revisions(
       id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
       ticker TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('evidence','assessment')),
       state TEXT NOT NULL CHECK(state IN ('active','retracted')), payload TEXT NOT NULL,
       reason TEXT, run_id TEXT NOT NULL, request_id TEXT NOT NULL,
       recorded_at TEXT NOT NULL, PRIMARY KEY(id,revision))''',
    '''CREATE TABLE IF NOT EXISTS research_store_heads(
       id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
       FOREIGN KEY(id,revision) REFERENCES research_store_revisions(id,revision))''',
    '''CREATE TRIGGER IF NOT EXISTS research_store_no_revision_update
       BEFORE UPDATE ON research_store_revisions BEGIN
       SELECT RAISE(ABORT,'Research history is immutable'); END''',
    '''CREATE TRIGGER IF NOT EXISTS research_store_no_revision_delete
       BEFORE DELETE ON research_store_revisions BEGIN
       SELECT RAISE(ABORT,'Research history is immutable'); END''',
    '''CREATE TRIGGER IF NOT EXISTS research_store_no_request_update
       BEFORE UPDATE ON research_store_requests BEGIN
       SELECT RAISE(ABORT,'Request history is immutable'); END''',
    '''CREATE TRIGGER IF NOT EXISTS research_store_no_request_delete
       BEFORE DELETE ON research_store_requests BEGIN
       SELECT RAISE(ABORT,'Request history is immutable'); END''',
]


def exists(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='research_store_heads'").fetchone() is not None


def read(db, record_id, revision=None):
    if not exists(db):
        return None
    if revision is None:
        row = db.execute('''SELECT r.* FROM research_store_revisions r JOIN research_store_heads h
                            ON h.id=r.id AND h.revision=r.revision WHERE r.id=?''', (record_id,)).fetchone()
    else:
        integer(revision, 'revision')
        row = db.execute('SELECT * FROM research_store_revisions WHERE id=? AND revision=?', (record_id, revision)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result['payload'] = json.loads(result['payload'])
    return result


def validate_payload(kind, payload, now):
    if not isinstance(payload, dict):
        raise StoreError('payload must be an object')
    encode(payload)
    if kind == 'evidence':
        text(payload.get('claim'), 'claim')
        url = payload.get('source_url')
        library = payload.get('library_file_id')
        if not ((isinstance(url, str) and re.match(r'^https?://[^/\s]+', url)) or
                (isinstance(library, str) and library.startswith('libfile_'))):
            raise StoreError('Evidence needs a source URL or Library identity')
        cutoff = text(payload.get('source_cutoff'), 'source_cutoff')
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', cutoff):
            try:
                source = datetime.fromisoformat(cutoff).replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise StoreError('Invalid source date') from exc
        else:
            source = instant(cutoff)
        retrieved = instant(payload.get('retrieved_at'))
        if source > retrieved or retrieved > now:
            raise StoreError('Evidence date ordering is invalid')
    elif kind == 'assessment':
        if payload.get('status') not in ('completed', 'partial', 'no_new_edge'):
            raise StoreError('Invalid assessment status')
        if not isinstance(payload.get('baseline_refs'), list):
            raise StoreError('baseline_refs required; use [] and baseline_gap when unavailable')
        if not payload['baseline_refs']:
            text(payload.get('baseline_gap'), 'baseline_gap')
        if not isinstance(payload.get('input_revisions'), dict) or not payload['input_revisions']:
            raise StoreError('input_revisions required')
        refs = payload.get('evidence_refs')
        if not isinstance(refs, list):
            raise StoreError('evidence_refs must be a list')
        if not refs:
            text(payload.get('no_new_evidence_reason'), 'no_new_evidence_reason')
        seen = set()
        for ref in refs:
            if not isinstance(ref, dict):
                raise StoreError('Invalid evidence reference')
            rid = text(ref.get('id'), 'evidence id')
            rev = integer(ref.get('revision'), 'evidence revision')
            if rev < 1 or (rid, rev) in seen:
                raise StoreError('Invalid or duplicate evidence reference')
            seen.add((rid, rev))
    else:
        raise StoreError('Unknown record kind')


def commit(db, request, *, manage_transaction=True):
    if not isinstance(request, dict):
        raise StoreError('Request must be an object')
    request_id = text(request.get('request_id'), 'request_id')
    run_id = text(request.get('run_id'), 'run_id')
    fingerprint = hashlib.sha256(encode(request).encode()).hexdigest()
    operations = request.get('operations')
    if not isinstance(operations, list) or not operations:
        raise StoreError('Nonempty operations required')
    now = datetime.now(timezone.utc)
    if manage_transaction: db.execute('BEGIN IMMEDIATE')
    elif not db.in_transaction: raise StoreError('Caller-owned transaction required')
    try:
        for sql in DDL:
            db.execute(sql)
        old = db.execute('SELECT fingerprint,receipt FROM research_store_requests WHERE request_id=?', (request_id,)).fetchone()
        if old:
            if old['fingerprint'] != fingerprint:
                raise StoreError('Request ID reused with different content')
            receipt = json.loads(old['receipt'])
            if manage_transaction: db.rollback()
            return dict(receipt, idempotent_replay=True)
        seen = set()
        receipts = []
        for op in operations:
            rid = text(op.get('id'), 'id')
            if rid in seen:
                raise StoreError('Duplicate record ID in transaction')
            seen.add(rid)
            ticker = op.get('ticker')
            if not isinstance(ticker, str) or not re.fullmatch(r'[A-Z0-9.^=-]{1,20}', ticker):
                raise StoreError('Invalid ticker')
            kind = op.get('kind')
            if kind not in ('evidence', 'assessment'):
                raise StoreError('Invalid record kind')
            expected = integer(op.get('expected_revision'), 'expected_revision')
            prior = read(db, rid)
            current = prior['revision'] if prior else 0
            if current != expected:
                raise StoreError(f'Stale revision for {rid}: expected {expected}, actual {current}')
            if prior and (prior['ticker'] != ticker or prior['kind'] != kind):
                raise StoreError('Cannot change stable record identity')
            action = op.get('action')
            if action == 'put':
                if prior and prior['state'] == 'retracted':
                    raise StoreError('Retracted ID cannot be revived; use a new ID')
                payload = op.get('payload')
                validate_payload(kind, payload, now)
                reason = text(op.get('reason'), 'revision reason') if prior else op.get('reason')
                state = 'active'
            elif action == 'retract':
                if not prior or prior['state'] == 'retracted':
                    raise StoreError('Only an active record can be retracted')
                reason = text(op.get('reason'), 'retraction reason')
                payload = prior['payload']
                state = 'retracted'
            else:
                raise StoreError('action must be put or retract')
            revision = current + 1
            db.execute('INSERT INTO research_store_revisions VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (rid, revision, ticker, kind, state, encode(payload), reason, run_id, request_id, now.isoformat()))
            db.execute('INSERT INTO research_store_heads VALUES(?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision', (rid, revision))
            receipts.append({'id': rid, 'revision': revision, 'state': state})
        # Resolve after all writes, so evidence and assessment can arrive in either order.
        for item in receipts:
            record = read(db, item['id'])
            if record['kind'] != 'assessment' or record['state'] != 'active':
                continue
            for ref in record['payload']['evidence_refs']:
                evidence = read(db, ref['id'])
                if not evidence or evidence['kind'] != 'evidence' or evidence['state'] != 'active' or evidence['revision'] != ref['revision']:
                    raise StoreError('Assessment references missing, superseded or retracted evidence')
                if evidence['ticker'] != record['ticker'] and not ref.get('cross_ticker_reason'):
                    raise StoreError('Cross-ticker evidence needs an explicit reason')
        receipt = {'version': VERSION, 'request_id': request_id, 'run_id': run_id,
                   'committed_at': now.isoformat(), 'records': receipts, 'idempotent_replay': False,
                   'durability': 'local_sqlite_only_requires_guarded_library_writeback'}
        db.execute('INSERT INTO research_store_requests VALUES(?,?,?,?,?)',
                   (request_id, fingerprint, run_id, now.isoformat(), encode(receipt)))
        if manage_transaction: db.commit()
        return receipt
    except Exception:
        if manage_transaction: db.rollback()
        raise


def annotate_dependencies(db, record):
    if record is None:
        return None
    issues = []
    current = read(db, record['id'])
    if current['revision'] != record['revision']:
        issues.append('record_superseded')
    if record['state'] == 'retracted':
        issues.append('record_retracted')
    if record['kind'] == 'assessment':
        for ref in record['payload']['evidence_refs']:
            head = read(db, ref['id'])
            if not head or head['state'] != 'active' or head['revision'] != ref['revision']:
                issues.append('evidence_not_current_active:' + ref['id'])
    return dict(record, dependency_issues=issues, eligible_for_reuse=not issues)


def read_ticker_current(db, ticker):
    """Read-only next-run inheritance, retaining retractions and stale dependency flags."""
    if not exists(db):
        return []
    ids = [r[0] for r in db.execute(
        "SELECT r.id FROM research_store_revisions r JOIN research_store_heads h "
        "ON r.id=h.id AND r.revision=h.revision WHERE r.ticker=? ORDER BY r.id", (ticker,))]
    return [annotate_dependencies(db, read(db, rid)) for rid in ids]


def export(db, ticker=None):
    if not exists(db):
        return {'version': VERSION, 'records': [], 'requests': []}
    params = () if ticker is None else (ticker,)
    where = '' if ticker is None else ' WHERE ticker=?'
    records = [dict(r) for r in db.execute('SELECT * FROM research_store_revisions' + where + ' ORDER BY id,revision', params)]
    for record in records:
        record['payload'] = json.loads(record['payload'])
        record['is_current'] = read(db, record['id'])['revision'] == record['revision']
    request_ids = {r['request_id'] for r in records}
    requests = [dict(r) for r in db.execute('SELECT * FROM research_store_requests ORDER BY committed_at,request_id') if ticker is None or r['request_id'] in request_ids]
    for request in requests:
        request['receipt'] = json.loads(request['receipt'])
    return {'version': VERSION, 'records': records, 'requests': requests}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('commit', 'read', 'export'):
        p = sub.add_parser(name); p.add_argument('--db', required=True)
        p.add_argument('--output')
        if name == 'commit': p.add_argument('--file', required=True)
        if name == 'read':
            p.add_argument('--id', required=True); p.add_argument('--revision', type=int)
        if name == 'export': p.add_argument('--ticker')
    args = parser.parse_args()
    with connect(args.db, readonly=args.command != 'commit') as db:
        if args.command == 'commit':
            result = commit(db, json.loads(Path(args.file).read_text()))
        elif args.command == 'read': result = annotate_dependencies(db, read(db, args.id, args.revision))
        else: result = export(db, args.ticker)
    output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output: Path(args.output).write_text(output)
    else: print(output, end='')

if __name__ == '__main__':
    main()
