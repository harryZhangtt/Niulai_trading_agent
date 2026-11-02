"""One-host observation CRUD with immutable history and atomic publication.

Storage validates bytes and provenance structure. Claim eligibility belongs to
the decision engine; a stored observation is never globally certified as true.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import re
import sqlite3
import uuid

from .artifacts import SourceError, digest, encoded, private_path, read as read_artifact, require, save


def stamp():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,191}', value), 'STORE_ID_INVALID')
    return value


def positive(value):
    require(type(value) is int and value > 0, 'STORE_REVISION_INVALID')
    return value


def instant(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(result.tzinfo is not None and result.utcoffset() is not None, 'CHECK_TIME_INVALID')
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise SourceError('CHECK_TIME_INVALID') from None


class Store:
    def __init__(self, directory):
        self.directory = private_path(directory, create=True)
        self.blobs = private_path(self.directory / 'blobs', create=True)
        self.path = self.directory / 'index.sqlite'
        require(not self.path.is_symlink(), 'STORE_PATH_REJECTED')
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self._db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS observations(
                id TEXT NOT NULL, revision INTEGER NOT NULL, lifecycle_revision INTEGER NOT NULL,
                state TEXT NOT NULL, source_identity TEXT NOT NULL,
                entity TEXT, metric TEXT, payload_ref TEXT NOT NULL,
                reason TEXT, recorded_at TEXT NOT NULL, PRIMARY KEY(id,revision));
              CREATE TABLE IF NOT EXISTS heads(id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS requests(
                request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, receipt TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS snapshots(
                id TEXT PRIMARY KEY, manifest_ref TEXT NOT NULL, recorded_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS events(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
                request_id TEXT NOT NULL, details TEXT NOT NULL, occurred_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS requirement_checks(
                requirement_sha256 TEXT PRIMARY KEY, generation INTEGER NOT NULL,
                requirement_ref TEXT NOT NULL, outcome_ref TEXT NOT NULL, status TEXT NOT NULL,
                next_check_at REAL, decision_deadline REAL, recorded_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS acquisition_cache(
                key_sha256 TEXT PRIMARY KEY, fetch_key TEXT NOT NULL, generation INTEGER NOT NULL,
                state TEXT NOT NULL, source_ref TEXT NOT NULL, checked_at TEXT NOT NULL,
                reason TEXT);
              CREATE TABLE IF NOT EXISTS acquisition_failures(
                key_sha256 TEXT PRIMARY KEY, fetch_key TEXT NOT NULL, reason TEXT NOT NULL,
                failed_at TEXT NOT NULL, retry_at TEXT);
              CREATE INDEX IF NOT EXISTS observation_search ON observations(entity,metric);
              CREATE TRIGGER IF NOT EXISTS immutable_observations_update BEFORE UPDATE ON observations
                BEGIN SELECT RAISE(ABORT,'immutable observation'); END;
              CREATE TRIGGER IF NOT EXISTS immutable_observations_delete BEFORE DELETE ON observations
                BEGIN SELECT RAISE(ABORT,'immutable observation'); END;
              CREATE TRIGGER IF NOT EXISTS immutable_requests_update BEFORE UPDATE ON requests
                BEGIN SELECT RAISE(ABORT,'immutable request'); END;
              CREATE TRIGGER IF NOT EXISTS immutable_requests_delete BEFORE DELETE ON requests
                BEGIN SELECT RAISE(ABORT,'immutable request'); END;
              CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT,'immutable event'); END;
              CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT,'immutable event'); END;
              CREATE TRIGGER IF NOT EXISTS immutable_snapshots_update BEFORE UPDATE ON snapshots
                BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
              CREATE TRIGGER IF NOT EXISTS immutable_snapshots_delete BEFORE DELETE ON snapshots
                BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
            ''')
            db.execute("INSERT OR IGNORE INTO metadata VALUES('store_id',?)", (str(uuid.uuid4()),))
            self.store_id = db.execute("SELECT value FROM metadata WHERE key='store_id'").fetchone()['value']

    @contextmanager
    def _db(self, write=False, *, timeout=2):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=max(0, min(2, timeout)))
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA synchronous=FULL')
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except sqlite3.Error as exc:
            if db is not None:
                db.rollback()
            message = str(exc).lower()
            raise SourceError('STORE_BUSY' if 'locked' in message or 'busy' in message else 'STORE_IO_FAILED') from None
        except BaseException:
            if db is not None:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def _row(db, observation_id, revision=None):
        if revision is None:
            return db.execute('SELECT o.* FROM observations o JOIN heads h ON o.id=h.id AND o.revision=h.revision WHERE o.id=?', (observation_id,)).fetchone()
        return db.execute('SELECT * FROM observations WHERE id=? AND revision=?', (observation_id, revision)).fetchone()

    @staticmethod
    def _record(row):
        require(row is not None, 'OBSERVATION_NOT_FOUND')
        result = dict(row)
        result['payload_ref'] = json.loads(result['payload_ref'])
        result['payload'] = read_artifact(result['payload_ref'])
        return result

    @staticmethod
    def _withdrawal_record(row):
        """Quarantining damaged data must not require decoding that data."""
        try:
            return Store._record(row)
        except (SourceError, OSError, ValueError, UnicodeError) as exc:
            result = dict(row)
            result['payload_ref'] = json.loads(result['payload_ref'])
            result['payload'] = None
            code = str(exc) if isinstance(exc, SourceError) else 'PAYLOAD_UNAVAILABLE'
            result['payload_error'] = code if re.fullmatch(r'[A-Z_0-9]{1,100}', code) else 'PAYLOAD_UNAVAILABLE'
            return result

    @staticmethod
    def _replay(db, request_id, fingerprint):
        prior = db.execute('SELECT * FROM requests WHERE request_id=?', (request_id,)).fetchone()
        if prior:
            require(prior['fingerprint'] == fingerprint, 'STORE_REQUEST_CONFLICT')
            return dict(json.loads(prior['receipt']), idempotent_replay=True)

    @staticmethod
    def _finish(db, request_id, fingerprint, receipt, event_type, details):
        receipt = {**receipt, 'request_id': request_id, 'idempotent_replay': False}
        db.execute('INSERT INTO requests VALUES(?,?,?)', (request_id, fingerprint, encoded(receipt).decode()))
        db.execute('INSERT INTO events(event_type,request_id,details,occurred_at) VALUES(?,?,?,?)',
                   (event_type, request_id, encoded(details).decode(), stamp()))
        return receipt

    def receipt(self, request_id):
        """Reconcile an uncertain local mutation without repeating acquisition."""
        identifier(request_id)
        with self._db() as db:
            row = db.execute('SELECT receipt FROM requests WHERE request_id=?', (request_id,)).fetchone()
            return json.loads(row['receipt']) if row else None

    def _payload(self, payload):
        require(isinstance(payload, dict), 'OBSERVATION_PAYLOAD_REQUIRED')
        for key in ('entity', 'metric', 'source_identity'):
            require(payload.get(key) is None or isinstance(payload[key], str) and 0 < len(payload[key]) <= 1000,
                    'OBSERVATION_METADATA_INVALID')
        identity = self._source_identity(payload)
        return save(self.blobs, payload), identity

    @staticmethod
    def _source_identity(payload):
        require('source_ref' in payload, 'OBSERVATION_SOURCE_REQUIRED')
        source = read_artifact(payload['source_ref'])
        require(isinstance(source, dict) and all(isinstance(source.get(k), str) and source[k].strip()
                for k in ('provider', 'source_url', 'upstream_id')), 'OBSERVATION_SOURCE_INVALID')
        # Confirm source bytes exist; a receipt alone is insufficient provenance.
        read_artifact(source.get('raw'), json_value=False)
        if source.get('text') is not None:
            read_artifact(source['text'], json_value=False)
        return encoded([source['provider'], payload.get('source_identity') or source['upstream_id']]).decode()

    def create(self, request_id, observation_id, payload):
        return self._put(request_id, observation_id, payload, expected_revision=0)

    def revise(self, request_id, observation_id, payload, expected_revision):
        positive(expected_revision)
        return self._put(request_id, observation_id, payload, expected_revision=expected_revision)

    def _put(self, request_id, observation_id, payload, expected_revision):
        identifier(request_id); identifier(observation_id)
        fingerprint = digest({'action': 'put', 'id': observation_id, 'payload': payload, 'expected_revision': expected_revision})
        payload_ref, identity = self._payload(payload)
        with self._db(write=True) as db:
            replay = self._replay(db, request_id, fingerprint)
            if replay:
                return replay
            prior = self._row(db, observation_id)
            require((prior['revision'] if prior else 0) == expected_revision, 'STORE_REVISION_CONFLICT')
            require(prior is None or prior['state'] == 'active', 'OBSERVATION_WITHDRAWN')
            require(prior is None or prior['source_identity'] == identity, 'OBSERVATION_IDENTITY_CHANGED')
            revision = expected_revision + 1
            db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (observation_id, revision, revision, 'active', identity,
                        payload.get('entity'), payload.get('metric'), encoded(payload_ref).decode(), None, stamp()))
            db.execute('INSERT INTO heads VALUES(?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision', (observation_id, revision))
            record = self._record(self._row(db, observation_id))
            return self._finish(db, request_id, fingerprint, record, 'observation_created' if revision == 1 else 'observation_revised',
                                {'observation_id': observation_id, 'revision': revision})

    def read(self, observation_id, revision=None, include_withdrawn=False):
        identifier(observation_id)
        if revision is not None:
            positive(revision)
        with self._db() as db:
            row = self._row(db, observation_id, revision)
            require(row is not None, 'OBSERVATION_NOT_FOUND')
            require(row['state'] == 'active' or include_withdrawn, 'OBSERVATION_WITHDRAWN')
            record = self._withdrawal_record(row) if row['state'] == 'withdrawn' else self._record(row)
            require(record['state'] == 'active' or include_withdrawn, 'OBSERVATION_WITHDRAWN')
            return record

    def withdraw(self, request_id, observation_id, expected_revision, reason):
        identifier(request_id); identifier(observation_id); positive(expected_revision)
        require(isinstance(reason, str) and 0 < len(reason.strip()) <= 2000, 'WITHDRAWAL_REASON_REQUIRED')
        fingerprint = digest({'action': 'withdraw', 'id': observation_id, 'expected_revision': expected_revision, 'reason': reason})
        with self._db(write=True) as db:
            replay = self._replay(db, request_id, fingerprint)
            if replay:
                return replay
            prior = self._row(db, observation_id)
            require(prior is not None, 'OBSERVATION_NOT_FOUND')
            require(prior['revision'] == expected_revision, 'STORE_REVISION_CONFLICT')
            require(prior['state'] == 'active', 'OBSERVATION_WITHDRAWN')
            revision = expected_revision + 1
            db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (observation_id, revision, revision, 'withdrawn', prior['source_identity'], prior['entity'], prior['metric'],
                        prior['payload_ref'], reason, stamp()))
            db.execute('UPDATE heads SET revision=? WHERE id=?', (revision, observation_id))
            record = self._withdrawal_record(self._row(db, observation_id))
            return self._finish(db, request_id, fingerprint, record, 'observation_withdrawn',
                                {'observation_id': observation_id, 'revision': revision, 'reason': reason,
                                 'payload_error': record.get('payload_error')})

    def find(self, *, entity=None, metric=None, limit=100):
        require(type(limit) is int and 1 <= limit <= 1000, 'STORE_LIMIT_INVALID')
        where, args = ["o.state='active'"], []
        for key, value in (('entity', entity), ('metric', metric)):
            if value is not None:
                require(isinstance(value, str), 'STORE_FILTER_INVALID')
                where.append('o.' + key + '=?'); args.append(value)
        with self._db() as db:
            rows = db.execute('SELECT o.* FROM observations o JOIN heads h ON o.id=h.id AND o.revision=h.revision WHERE ' +
                              ' AND '.join(where) + ' ORDER BY o.id LIMIT ?', (*args, limit)).fetchall()
            return [self._record(row) for row in rows]

    def events(self, after=0, limit=100):
        require(type(after) is int and after >= 0 and type(limit) is int and 1 <= limit <= 1000, 'STORE_CURSOR_INVALID')
        with self._db() as db:
            rows = db.execute('SELECT * FROM events WHERE sequence>? ORDER BY sequence LIMIT ?', (after, limit)).fetchall()
            return [{**dict(row), 'schema_version': 1, 'store_id': self.store_id,
                     'event_id': self.store_id + ':' + str(row['sequence']),
                     'details': json.loads(row['details'])} for row in rows]

    def commit_snapshot(self, request_id, requirement_ref, bindings):
        identifier(request_id)
        read_artifact(requirement_ref)
        require(isinstance(bindings, list) and bool(bindings), 'SNAPSHOT_BINDINGS_REQUIRED')
        seen = set()
        for binding in bindings:
            fields = {'observation_id', 'revision', 'lifecycle_revision'}
            require(isinstance(binding, dict) and fields <= set(binding) <= fields | {'use_receipt_ref'}, 'SNAPSHOT_BINDING_INVALID')
            identifier(binding['observation_id']); positive(binding['revision']); positive(binding['lifecycle_revision'])
            require(binding['observation_id'] not in seen, 'SNAPSHOT_BINDING_DUPLICATE')
            seen.add(binding['observation_id'])
            if 'use_receipt_ref' in binding:
                read_artifact(binding['use_receipt_ref'])
            # Preflight potentially large source bytes outside the write lock;
            # publication then atomically checks the expected lifecycle stamps.
            record = self.read(binding['observation_id'], binding['revision'])
            self._source_identity(record['payload'])
        manifest = {'schema_version': 1, 'requirement_ref': requirement_ref, 'bindings': bindings,
                    'scope': 'evidence_storage', 'claim_support': 'not_established_by_storage'}
        manifest_ref = save(self.blobs, manifest)
        snapshot_id = digest(manifest)
        fingerprint = digest({'action': 'snapshot', 'manifest': manifest})
        with self._db(write=True) as db:
            replay = self._replay(db, request_id, fingerprint)
            if replay:
                return replay
            for binding in bindings:
                current = self._row(db, binding['observation_id'])
                require(current is not None and current['state'] == 'active' and current['revision'] == binding['revision']
                        and current['lifecycle_revision'] == binding['lifecycle_revision'], 'SNAPSHOT_DEPENDENCY_CHANGED')
                self._record(current)  # fail publication if referenced bytes are damaged
            db.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?)', (snapshot_id, encoded(manifest_ref).decode(), stamp()))
            return self._finish(db, request_id, fingerprint, {'snapshot_id': snapshot_id, 'manifest_ref': manifest_ref},
                                'snapshot_committed', {'snapshot_id': snapshot_id, 'bindings': bindings})

    def read_snapshot(self, snapshot_id):
        identifier(snapshot_id)
        with self._db() as db:
            row = db.execute('SELECT manifest_ref FROM snapshots WHERE id=?', (snapshot_id,)).fetchone()
            require(row is not None, 'SNAPSHOT_NOT_FOUND')
            ref = json.loads(row['manifest_ref'])
            return {'snapshot_id': snapshot_id, 'manifest_ref': ref, 'manifest': read_artifact(ref)}

    @staticmethod
    def _check_record(row):
        require(row is not None, 'CHECK_NOT_FOUND')
        result = dict(row)
        for key in ('requirement_ref', 'outcome_ref'):
            result[key] = json.loads(result[key])
        result['outcome'] = read_artifact(result['outcome_ref'])
        for key in ('next_check_at', 'decision_deadline'):
            result[key] = datetime.fromtimestamp(result[key], timezone.utc).isoformat() if result[key] is not None else None
        return result

    def save_check(self, request_id, requirement_ref, outcome, expected_generation=0):
        """Persist one policy-produced due record; no autonomous retries or claim."""
        identifier(request_id)
        require(type(expected_generation) is int and expected_generation >= 0, 'CHECK_GENERATION_INVALID')
        requirement = read_artifact(requirement_ref)
        require(isinstance(requirement, dict), 'CHECK_REQUIREMENT_INVALID')
        keys = {'requirement_sha256', 'policy_version', 'next_check_at', 'resume_condition', 'decision_deadline', 'attempt'}
        require(isinstance(outcome, dict) and set(outcome) == keys, 'CHECK_OUTCOME_INVALID')
        require(outcome['requirement_sha256'] == digest(requirement), 'CHECK_REQUIREMENT_MISMATCH')
        require(isinstance(outcome['policy_version'], str) and 0 < len(outcome['policy_version']) <= 100,
                'CHECK_POLICY_VERSION_REQUIRED')
        require(isinstance(outcome['resume_condition'], str) and 0 < len(outcome['resume_condition']) <= 100,
                'CHECK_RESUME_CONDITION_REQUIRED')
        require(type(outcome['attempt']) is int and 0 <= outcome['attempt'] <= 32, 'CHECK_ATTEMPT_INVALID')
        deadline = instant(requirement['decision_deadline']) if requirement.get('decision_deadline') is not None else None
        supplied_deadline = instant(outcome['decision_deadline']) if outcome['decision_deadline'] is not None else None
        require(supplied_deadline == deadline, 'CHECK_DEADLINE_CHANGED')
        due = instant(outcome['next_check_at']) if outcome['next_check_at'] is not None else None
        require(due is None or deadline is None or due < deadline, 'CHECK_DUE_AFTER_DEADLINE')
        status = 'scheduled' if due is not None else ('restricted' if outcome['resume_condition'] in
                 ('deadline_expired', 'wait_exceeds_deadline') else 'waiting')
        normalized = {**outcome, 'next_check_at': due.isoformat() if due else None,
                      'decision_deadline': deadline.isoformat() if deadline else None}
        outcome_ref = save(self.blobs, normalized)
        fingerprint = digest({'action': 'save_check', 'requirement_ref': requirement_ref,
                              'outcome': normalized, 'expected_generation': expected_generation})
        key = requirement_ref['sha256']
        with self._db(write=True) as db:
            replay = self._replay(db, request_id, fingerprint)
            if replay:
                return replay
            prior = db.execute('SELECT generation FROM requirement_checks WHERE requirement_sha256=?', (key,)).fetchone()
            require((prior['generation'] if prior else 0) == expected_generation, 'CHECK_GENERATION_CONFLICT')
            generation = expected_generation + 1
            db.execute('INSERT INTO requirement_checks VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(requirement_sha256) DO UPDATE SET '
                       'generation=excluded.generation,outcome_ref=excluded.outcome_ref,status=excluded.status,'
                       'next_check_at=excluded.next_check_at,decision_deadline=excluded.decision_deadline,recorded_at=excluded.recorded_at',
                       (key, generation, encoded(requirement_ref).decode(), encoded(outcome_ref).decode(), status,
                        due.timestamp() if due else None, deadline.timestamp() if deadline else None, stamp()))
            row = db.execute('SELECT * FROM requirement_checks WHERE requirement_sha256=?', (key,)).fetchone()
            return self._finish(db, request_id, fingerprint, self._check_record(row), 'requirement_check_saved',
                                {'requirement_sha256': key, 'generation': generation, 'status': status})

    def read_check(self, requirement_ref):
        read_artifact(requirement_ref)
        with self._db() as db:
            row = db.execute('SELECT * FROM requirement_checks WHERE requirement_sha256=?', (requirement_ref['sha256'],)).fetchone()
            return self._check_record(row) if row else None

    def due_checks(self, now, limit=20):
        at = instant(now)
        require(type(limit) is int and 1 <= limit <= 1000, 'STORE_LIMIT_INVALID')
        with self._db() as db:
            rows = db.execute("SELECT * FROM requirement_checks WHERE status='scheduled' AND next_check_at<=? "
                              'ORDER BY decision_deadline IS NULL, decision_deadline, next_check_at, requirement_sha256 LIMIT ?',
                              (at.timestamp(), limit)).fetchall()
            return [{**self._check_record(row), 'deadline_expired': row['decision_deadline'] is not None
                     and at.timestamp() >= row['decision_deadline']} for row in rows]

    def cache_read(self, key_sha256, *, timeout=2):
        """Read an acquisition pointer, never an admitted financial observation."""
        require(isinstance(key_sha256, str) and re.fullmatch('[a-f0-9]{64}', key_sha256), 'CACHE_KEY_INVALID')
        with self._db(timeout=timeout) as db:
            row = db.execute('SELECT * FROM acquisition_cache WHERE key_sha256=?', (key_sha256,)).fetchone()
            if row is None:
                return None
            return {**dict(row), 'fetch_key': json.loads(row['fetch_key']), 'source_ref': json.loads(row['source_ref'])}

    def cache_publish(self, request_id, fetch_key, source_ref, checked_at, expected_generation=0, *, timeout=2):
        """CAS-publish a validated pointer; source and request history stay immutable."""
        identifier(request_id)
        require(isinstance(fetch_key, dict), 'CACHE_KEY_INVALID')
        require(type(expected_generation) is int and expected_generation >= 0, 'CACHE_GENERATION_INVALID')
        checked_at = instant(checked_at).isoformat()
        read_artifact(source_ref)
        key_sha256 = digest(fetch_key)
        fingerprint = digest({'action': 'cache_publish', 'fetch_key': fetch_key, 'source_ref': source_ref,
                              'checked_at': checked_at, 'expected_generation': expected_generation})
        with self._db(write=True, timeout=timeout) as db:
            replay = self._replay(db, request_id, fingerprint)
            if replay:
                return replay
            prior = db.execute('SELECT generation,fetch_key FROM acquisition_cache WHERE key_sha256=?', (key_sha256,)).fetchone()
            require((prior['generation'] if prior else 0) == expected_generation, 'CACHE_GENERATION_CONFLICT')
            require(prior is None or json.loads(prior['fetch_key']) == fetch_key, 'CACHE_KEY_MISMATCH')
            generation = expected_generation + 1
            db.execute('INSERT INTO acquisition_cache VALUES(?,?,?,?,?,?,?) ON CONFLICT(key_sha256) DO UPDATE SET '
                       'generation=excluded.generation,state=excluded.state,source_ref=excluded.source_ref,'
                       'checked_at=excluded.checked_at,reason=excluded.reason',
                       (key_sha256, encoded(fetch_key).decode(), generation, 'active', encoded(source_ref).decode(), checked_at, None))
            db.execute('DELETE FROM acquisition_failures WHERE key_sha256=?', (key_sha256,))
            return self._finish(db, request_id, fingerprint,
                {'key_sha256': key_sha256, 'generation': generation, 'source_ref': source_ref}, 'cache_published',
                {'key_sha256': key_sha256, 'generation': generation, 'source_ref': source_ref})

    def cache_invalidate(self, request_id, key_sha256, expected_generation, reason, *, timeout=2):
        """Fence damaged bytes without deleting their receipt or other observations."""
        identifier(request_id); positive(expected_generation)
        require(isinstance(reason, str) and re.fullmatch('[A-Z][A-Z_0-9]{0,99}', reason), 'CACHE_REASON_INVALID')
        require(isinstance(key_sha256, str) and re.fullmatch('[a-f0-9]{64}', key_sha256), 'CACHE_KEY_INVALID')
        fingerprint = digest({'action': 'cache_invalidate', 'key_sha256': key_sha256,
                              'expected_generation': expected_generation, 'reason': reason})
        with self._db(write=True, timeout=timeout) as db:
            replay = self._replay(db, request_id, fingerprint)
            if replay:
                return replay
            prior = db.execute('SELECT generation FROM acquisition_cache WHERE key_sha256=?', (key_sha256,)).fetchone()
            require(prior is not None and prior['generation'] == expected_generation, 'CACHE_GENERATION_CONFLICT')
            generation = expected_generation + 1
            db.execute("UPDATE acquisition_cache SET generation=?,state='quarantined',reason=? WHERE key_sha256=?",
                       (generation, reason, key_sha256))
            return self._finish(db, request_id, fingerprint, {'key_sha256': key_sha256, 'generation': generation},
                                'cache_quarantined', {'key_sha256': key_sha256, 'generation': generation, 'reason': reason})

    def cache_failure_read(self, key_sha256, *, timeout=2):
        require(isinstance(key_sha256, str) and re.fullmatch('[a-f0-9]{64}', key_sha256), 'CACHE_KEY_INVALID')
        with self._db(timeout=timeout) as db:
            row = db.execute('SELECT * FROM acquisition_failures WHERE key_sha256=?', (key_sha256,)).fetchone()
            return {**dict(row), 'fetch_key': json.loads(row['fetch_key'])} if row else None

    def cache_failure(self, request_id, fetch_key, reason, failed_at, retry_at, expected_generation=0, *, timeout=2):
        """Record an exact-key dependency/cooldown; this never schedules retries."""
        identifier(request_id)
        require(isinstance(fetch_key, dict), 'CACHE_KEY_INVALID')
        require(type(expected_generation) is int and expected_generation >= 0, 'CACHE_GENERATION_INVALID')
        require(isinstance(reason, str) and re.fullmatch('[A-Z][A-Z_0-9]{0,99}', reason), 'CACHE_REASON_INVALID')
        failed_at = instant(failed_at).isoformat()
        retry_at = instant(retry_at).isoformat() if retry_at is not None else None
        require(retry_at is None or instant(retry_at) > instant(failed_at), 'CACHE_COOLDOWN_INVALID')
        key_sha256 = digest(fetch_key)
        receipt = {'key_sha256': key_sha256, 'reason': reason, 'failed_at': failed_at, 'retry_at': retry_at}
        fingerprint = digest({'action': 'cache_failure', 'fetch_key': fetch_key, **receipt,
                              'expected_generation': expected_generation})
        with self._db(write=True, timeout=timeout) as db:
            replay = self._replay(db, request_id, fingerprint)
            if replay:
                return replay
            prior = db.execute('SELECT generation FROM acquisition_cache WHERE key_sha256=?', (key_sha256,)).fetchone()
            require((prior['generation'] if prior else 0) == expected_generation, 'CACHE_GENERATION_CONFLICT')
            db.execute('INSERT INTO acquisition_failures VALUES(?,?,?,?,?) ON CONFLICT(key_sha256) DO UPDATE SET '
                       'reason=excluded.reason,failed_at=excluded.failed_at,retry_at=excluded.retry_at',
                       (key_sha256, encoded(fetch_key).decode(), reason, failed_at, retry_at))
            return self._finish(db, request_id, fingerprint, receipt, 'cache_source_unavailable', receipt)
