"""Bounded read-only scheduler projection. Never instantiate Engine or dispatch work."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from zoneinfo import ZoneInfo

from . import config as runtime_config
from .config import inside, load
from .engine import validate_job
from .provider_contract import ProviderResultV1, ReconciliationProofV1, validate_replay
from .retry_policy import RetryDecision, decide_retry, validate_retry_policy

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc


class DashboardError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise DashboardError(code)


def read_file(root, path, maximum=1024 * 1024):
    path = inside(Path(path), root)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_size <= maximum, 'DASHBOARD_FILE_INVALID')
        raw = stream.read(maximum + 1)
        require(len(raw) <= maximum, 'DASHBOARD_FILE_LIMIT')
        return raw


def read_json(root, path):
    return json.loads(read_file(root, path))


@contextmanager
def database(root, path):
    path = inside(path, root)
    require(path.is_file() and not path.is_symlink(), 'DASHBOARD_DATABASE_UNAVAILABLE')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    deadline = time.monotonic() + 1
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        yield db
    finally:
        db.close()


@contextmanager
def packet_database(root, path):
    manager = database(root, path)
    try:
        db = manager.__enter__()
    except (OSError, ValueError, sqlite3.Error):
        yield None
        return
    try:
        yield db
    finally:
        manager.__exit__(None, None, None)


def instant(value):
    if value is None:
        return None
    if type(value) in (int, float):
        require(math.isfinite(value), 'DASHBOARD_TIME_INVALID')
        return datetime.fromtimestamp(value, UTC).isoformat()
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(dt.tzinfo is not None, 'DASHBOARD_TIME_INVALID')
    return dt.astimezone(UTC).isoformat()


def schedule_instant(value):
    require(isinstance(value, str) and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)', value),
        'DASHBOARD_TIME_INVALID')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(UTC)
    except ValueError:
        raise DashboardError('DASHBOARD_TIME_INVALID') from None


def scrub(text):
    """Defense in depth for task text; never expose configuration/auth blobs."""
    text = re.sub(r'''(?i)(["'](?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret)["']\s*:\s*)("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')''', r'\1"[redacted]"', text)
    text = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~-]+', r'\1[redacted]', text)
    text = re.sub(r'(?im)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret)\s*[=:]\s*)[^\s,;]+', r'\1[redacted]', text)
    text = re.sub(r'\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{30,}|gh[pousr]_[A-Za-z0-9]{30,})', '[redacted]', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b', '[redacted]', text)
    text = re.sub(r'https?://[^\s/@:]+:[^\s/@]+@', 'https://[redacted]@', text)
    text = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----', '[redacted private key]', text)
    return text


def next_tick(schedule, at, eligible=lambda _: True):
    kind = schedule['kind']
    if kind == 'interval':
        return datetime.fromtimestamp((math.floor(at.timestamp() / schedule['seconds']) + 1) * schedule['seconds'], UTC).isoformat()
    if kind == 'once':
        due = schedule_instant(schedule['at'])
        return due.isoformat() if due > at else None
    if kind == 'sequence':
        for value in schedule['timestamps']:
            due = schedule_instant(value)
            if due > at:
                return due.isoformat()
        return None
    local = at.astimezone(ZoneInfo(schedule['timezone']))
    for offset in range(370):
        day = local.date() + timedelta(days=offset)
        if not eligible(day):
            continue
        for clock in sorted(schedule['times']):
            h, m = map(int, clock.split(':'))
            due = datetime(day.year, day.month, day.day, h, m, tzinfo=local.tzinfo)
            if due > at:
                return due.astimezone(UTC).isoformat()
    return None


def safe_code(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Z0-9_]{0,100}', value) else 'DETAIL_UNAVAILABLE'


def health(root, at, stale):
    result = {'state': 'unavailable', 'heartbeat_at': None, 'watchdog_healthy': None}
    try:
        beat = read_json(root, root / '.job-runtime/heartbeat.json')
        stamp = datetime.fromisoformat(instant(beat['at']))
        age = (at - stamp).total_seconds()
        alive = False
        if type(beat.get('pid')) is int and beat['pid'] > 1:
            try:
                os.kill(beat['pid'], 0)
                alive = True
            except (ProcessLookupError, PermissionError):
                pass
        result.update(state='healthy' if alive and -5 <= age <= stale else 'stale',
                      heartbeat_at=stamp.isoformat(), heartbeat_age_seconds=round(age, 1))
        watch = read_json(root, root / '.job-runtime/watchdog.json')
        checked = datetime.fromisoformat(instant(watch['checked_at']))
        if -5 <= (at - checked).total_seconds() <= stale:
            result['watchdog_healthy'] = watch.get('healthy') is True
    except (OSError, ValueError, KeyError):
        pass
    return result


def history(root, job_id, db=None):
    path = root / '.job-runtime/engine/schedule.sqlite'
    if not path.exists():
        return []
    if db is None:
        with database(root, path) as connection:
            rows = connection.execute('SELECT slot_id,scheduled_at,status,attempts,code,updated_at FROM slots WHERE job_id=? ORDER BY scheduled_at DESC LIMIT 20', (job_id,)).fetchall()
    else:
        rows = db.execute('SELECT slot_id,scheduled_at,status,attempts,code,updated_at FROM slots WHERE job_id=? ORDER BY scheduled_at DESC LIMIT 20', (job_id,)).fetchall()
    return [{'id': hashlib.sha256(r['slot_id'].encode()).hexdigest()[:20],
             'scheduled_at': instant(r['scheduled_at']), 'updated_at': instant(r['updated_at']),
             'status': r['status'] if r['status'] in ('ready', 'running', 'retry_wait', 'succeeded', 'failed', 'unknown', 'missed', 'coalesced') else 'unknown',
             'attempts': r['attempts'], 'code': safe_code(r['code'])} for r in rows]


_PROVIDER = frozenset(('codex_cli', 'claude_host'))
_PHASE = frozenset(('not_started', 'connecting', 'submitted', 'streaming', 'terminal'))
_SUBMISSION = frozenset(('not_submitted', 'definitely_submitted', 'possibly_submitted'))
_TERMINAL_PROOF = frozenset(('verified', 'absent', 'contradictory'))
_RESULT_STATUS = frozenset(('succeeded', 'retryable', 'failed', 'unknown'))
_FAILURE_KIND = frozenset(('none', 'timeout', 'connection_reset', 'connection', 'partial_response',
                           'missing_terminal', 'http', 'auth', 'config', 'model', 'policy',
                           'local_config', 'provider', 'unknown'))
_ATTEMPT_STATUS = frozenset(('running', 'retry_wait', 'succeeded', 'failed', 'unknown'))
_RETRY_REASON = frozenset((
    'PROVIDER_SUCCEEDED', 'PROVIDER_OUTCOME_UNKNOWN', 'PROVIDER_TERMINAL_FAILURE',
    'PERMANENT_LOCAL_FAILURE', 'PROVIDER_RETRY_DENIED', 'REPLAY_AUTHORITY_ABSENT',
    'HTTP_STATUS_NOT_RETRYABLE', 'ATTEMPTS_EXHAUSTED', 'PROVIDER_WAIT_INVALID',
    'PROVIDER_WAIT_EXCEEDS_MAX', 'RETRY_DEADLINE_EXCEEDED', 'RETRY_SCHEDULED',
    'PROCESS_EXITED_OUTCOME_UNKNOWN', 'RECONCILIATION_ABSENT_RETRY'))


def _enum(value, allowed):
    require(isinstance(value, str) and value in allowed, 'DASHBOARD_PROVIDER_ROW_INVALID')
    return value


def _canonical_row(encoded, digest):
    require(isinstance(encoded, str) and len(encoded.encode()) <= 65536
            and isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest),
            'DASHBOARD_PROVIDER_ROW_INVALID')
    require(hashlib.sha256(encoded.encode()).hexdigest() == digest,
            'DASHBOARD_PROVIDER_ROW_INVALID')
    value = json.loads(encoded)
    require(type(value) is dict, 'DASHBOARD_PROVIDER_ROW_INVALID')
    return value


def _resource_scope(profile):
    identity = json.dumps({'provider': profile['provider'],
                           'auth_home': str(Path(profile['auth_home']).resolve())},
                          sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(identity).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False)


def _finite_epoch(value, *, nullable=True):
    if value is None:
        require(nullable, 'DASHBOARD_PROVIDER_ROW_INVALID')
        return None
    require(type(value) in (int, float) and math.isfinite(value),
            'DASHBOARD_PROVIDER_ROW_INVALID')
    return float(value)


def _typed_result(row, attempt_id, provider):
    value = _canonical_row(row['canonical_json'], row['canonical_sha256'])
    require(set(value) == {'version', 'provider', 'operation_id', 'phase', 'submission',
                           'terminal_proof', 'status', 'code', 'failure_kind', 'http_status',
                           'provider_should_retry', 'retry_after_at', 'retry_after_source', 'receipt'},
            'DASHBOARD_PROVIDER_ROW_INVALID')
    retry_after = value['retry_after_at']
    if retry_after is not None:
        retry_after = datetime.fromisoformat(instant(retry_after))
    result = ProviderResultV1(
        provider=value['provider'], operation_id=value['operation_id'], phase=value['phase'],
        submission=value['submission'], terminal_proof=value['terminal_proof'],
        status=value['status'], code=value['code'], failure_kind=value['failure_kind'],
        http_status=value['http_status'], provider_should_retry=value['provider_should_retry'],
        retry_after_at=retry_after, retry_after_source=value['retry_after_source'],
        receipt=value['receipt'], version=value['version'])
    require(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
            == row['canonical_json'] and result.canonical_sha256 == row['canonical_sha256']
            and result.provider.value == provider
            and (result.operation_id == f'attempt/{attempt_id}'
                 or re.fullmatch(rf'attempt/{re.escape(attempt_id)}/prompt/[0-9a-f]{{64}}',
                                 result.operation_id))
            and row['result_operation_id'] == result.operation_id
            and row['result_attempt_id'] == attempt_id
            and row['result_slot_id'] == row['attempt_slot_id']
            and all(value[key] == row[key] for key in
                    ('provider', 'phase', 'submission', 'terminal_proof', 'status', 'failure_kind')),
            'DASHBOARD_PROVIDER_ROW_INVALID')
    return result


def _provider_safety_snapshot(root, config, job, at, db):
    """Project one consistent Engine v5 snapshot without advancing state."""
    profile_name = job['model_profile']
    profile = config['model_profiles'][profile_name]
    provider = _enum(profile['provider'], _PROVIDER)
    resource_hash = _resource_scope(profile)
    schema_version = db.execute('PRAGMA user_version').fetchone()[0]
    require(schema_version in (5, 6, 7, 8, 9), 'DASHBOARD_PROVIDER_SCHEMA_UNAVAILABLE')
    circuit_columns = {row[1] for row in db.execute('PRAGMA table_info(circuits)')}
    require({'scope_sha256', 'config_sha256', 'state', 'transient_failures',
             'opened_until', 'probe_owner', 'probe_expires', 'updated_at'} <= circuit_columns,
            'DASHBOARD_PROVIDER_SCHEMA_UNAVAILABLE')
    generation = 'generation' if 'generation' in circuit_columns else '0 AS generation'
    slot = db.execute(
        '''SELECT slot_id,status,attempts,operation_id,next_attempt_at,updated_at,
                  substr(replay_contract,1,65537) AS replay_contract,replay_contract_sha256,
                  substr(retry_policy,1,65537) AS retry_policy,retry_policy_fingerprint,
                  retry_deadline,circuit_profile,circuit_resource_hash,
                  substr(circuit_config,1,65537) AS circuit_config,circuit_config_sha256
           FROM slots WHERE job_id=? AND provider=? AND circuit_profile=?
             AND circuit_resource_hash=? ORDER BY updated_at DESC,slot_id DESC LIMIT 1''',
        (job['id'], provider, profile_name, resource_hash)).fetchone()
    attempt = db.execute(
        '''SELECT a.attempt_id,a.slot_id AS attempt_slot_id,a.attempt_no,a.started_at,a.ended_at,
                  a.status AS attempt_status,p.attempt_id AS result_attempt_id,
                  p.slot_id AS result_slot_id,substr(p.canonical_json,1,65537) AS canonical_json,
                  p.canonical_sha256,p.operation_id AS result_operation_id,
                  p.provider,p.phase,p.submission,p.terminal_proof,
                  p.status,p.failure_kind,p.recorded_at AS result_recorded_at
           FROM attempts a JOIN slots s ON s.slot_id=a.slot_id
           LEFT JOIN provider_results p ON p.attempt_id=a.attempt_id
           WHERE s.job_id=? AND s.provider=? AND s.circuit_profile=?
             AND s.circuit_resource_hash=?
           ORDER BY a.started_at DESC,a.attempt_no DESC LIMIT 1''',
        (job['id'], provider, profile_name, resource_hash)).fetchone()
    circuit = db.execute(
        f'''SELECT scope_sha256,config_sha256,{generation},state,transient_failures,
                   opened_until,probe_owner,probe_expires,updated_at FROM circuits
            WHERE provider=? AND profile=? AND resource_hash=?''',
        (provider, profile_name, resource_hash)).fetchone()
    queue = db.execute(
        '''SELECT COUNT(*) AS depth,MIN(next_attempt_at) AS oldest
           FROM slots WHERE provider=? AND circuit_profile=? AND circuit_resource_hash=?
             AND status='retry_wait' AND next_attempt_at>?''',
        (provider, profile_name, resource_hash, at.astimezone(UTC).timestamp())).fetchone()
    decision = None
    reconciliation = None
    if slot is not None:
        decision = db.execute(
            '''SELECT attempt_id,slot_id,substr(canonical_json,1,65537) AS canonical_json,
                      policy_fingerprint,policy_version,delay_seconds,
                      retry_after_at,next_attempt_at,deadline,recorded_at
               FROM retry_decisions WHERE slot_id=? ORDER BY recorded_at DESC LIMIT 1''',
            (slot['slot_id'],)).fetchone()
        reconciliation = db.execute(
            '''SELECT c.reconciliation_id,c.attempt_id AS consumed_attempt_id,
                      c.retry_decision_attempt_id,c.consumed_at,
                      r.attempt_id AS record_attempt_id,r.slot_id AS record_slot_id,
                      r.operation_id,r.slot_operation_scope,
                      substr(r.proof_json,1,65537) AS proof_json,r.proof_sha256,
                      r.evidence_sha256,r.recorded_at
               FROM retry_decisions d
               JOIN reconciliation_consumptions c ON c.retry_decision_attempt_id=d.attempt_id
               JOIN reconciliation_records r ON r.reconciliation_id=c.reconciliation_id
               WHERE d.slot_id=? ORDER BY d.recorded_at DESC LIMIT 1''',
            (slot['slot_id'],)).fetchone()

    latest = None
    result = None
    attempt_status = None
    if attempt is not None:
        require(slot is not None and attempt['attempt_slot_id'] == slot['slot_id']
                and type(attempt['attempt_no']) is int
                and attempt['attempt_no'] == slot['attempts'],
                'DASHBOARD_PROVIDER_ROW_INVALID')
        _finite_epoch(attempt['started_at'], nullable=False)
        _finite_epoch(attempt['ended_at'])
        attempt_status = _enum(attempt['attempt_status'], _ATTEMPT_STATUS)
        if attempt['canonical_json'] is None:
            require(attempt_status == 'running' and attempt['ended_at'] is None
                    and all(attempt[key] is None for key in
                            ('canonical_sha256', 'result_attempt_id', 'result_slot_id',
                             'result_operation_id', 'provider', 'phase', 'submission',
                             'terminal_proof', 'status', 'failure_kind')),
                    'DASHBOARD_PROVIDER_ROW_INVALID')
            latest = {'phase': 'unavailable', 'submission': 'unavailable',
                      'terminal_proof': 'unavailable', 'status': 'running',
                      'failure': 'unavailable'}
        else:
            result_recorded = _finite_epoch(attempt['result_recorded_at'], nullable=False)
            require(attempt['started_at'] <= result_recorded == attempt['ended_at'],
                    'DASHBOARD_PROVIDER_ROW_INVALID')
            result = _typed_result(attempt, attempt['attempt_id'], provider)
            latest = {'phase': result.phase.value, 'submission': result.submission.value,
                      'terminal_proof': result.terminal_proof.value, 'status': result.status.value,
                      'failure': result.failure_kind.value}

    delayed_until = None
    delay_source = None
    retry_reason = None
    replay_authorization = 'unavailable'
    unknown_fence = bool(slot is not None and slot['status'] == 'unknown')
    if slot is not None:
        _finite_epoch(slot['updated_at'], nullable=False)
        _finite_epoch(slot['next_attempt_at'])
        require(slot['status'] in ('ready', 'running', 'retry_wait', 'succeeded', 'failed',
                                   'unknown', 'missed', 'coalesced')
                and type(slot['attempts']) is int and slot['attempts'] >= 0
                and slot['circuit_profile'] == profile_name
                and slot['circuit_resource_hash'] == resource_hash,
                'DASHBOARD_PROVIDER_ROW_INVALID')
        if slot['status'] == 'ready':
            require(slot['attempts'] == 0 and attempt is None and slot['operation_id'] is None
                    and slot['next_attempt_at'] is None,
                    'DASHBOARD_PROVIDER_ROW_INVALID')
        elif slot['status'] == 'running':
            require(slot['attempts'] >= 1 and attempt_status == 'running'
                    and result is None and decision is None and slot['operation_id'] is None,
                    'DASHBOARD_PROVIDER_ROW_INVALID')
        else:
            require(slot['status'] in ('retry_wait', 'succeeded', 'failed', 'unknown')
                    and slot['attempts'] >= 1 and attempt is not None
                    and result is not None and decision is not None,
                    'DASHBOARD_PROVIDER_ROW_INVALID')
        contract = _canonical_row(slot['replay_contract'], slot['replay_contract_sha256'])
        configured = job['_replay_contract']
        expected_contract = {'version': configured.version, 'effect': configured.effect.value,
                             'automatic_phases': [phase.value for phase in configured.automatic_phases],
                             'slot_operation_scope': configured.slot_operation_scope,
                             'reconciliation_adapter': configured.reconciliation_adapter}
        circuit_settings = profile.get('circuit', {'failure_threshold': 3, 'open_seconds': 60,
                                                   'probe_seconds': 10})
        expected_circuit = {'profile': profile_name, 'resource_hash': resource_hash,
                            **circuit_settings}
        policy_value = json.loads(slot['retry_policy'])
        policy = validate_retry_policy(policy_value)
        deadline_epoch = _finite_epoch(slot['retry_deadline'], nullable=False)
        deadline = datetime.fromtimestamp(deadline_epoch, UTC)
        require(_canonical(policy_value) == slot['retry_policy']
                and policy.fingerprint == slot['retry_policy_fingerprint'],
                'DASHBOARD_PROVIDER_ROW_INVALID')
        require(contract == expected_contract
                and _canonical_row(slot['circuit_config'], slot['circuit_config_sha256']) == expected_circuit,
                'DASHBOARD_PROVIDER_ROW_INVALID')
        if decision is None:
            require(attempt_status in (None, 'running') and slot['status'] in ('ready', 'running'),
                    'DASHBOARD_PROVIDER_ROW_INVALID')
        else:
            require(attempt is not None and decision['slot_id'] == slot['slot_id']
                    and decision['policy_version'] == 2
                    and decision['policy_fingerprint'] == slot['retry_policy_fingerprint'],
                    'DASHBOARD_PROVIDER_ROW_INVALID')
            _finite_epoch(decision['deadline'])
            recorded = _finite_epoch(decision['recorded_at'], nullable=False)
            retry_after = _finite_epoch(decision['retry_after_at'])
            next_at = _finite_epoch(decision['next_attempt_at'])
            encoded_decision = decision['canonical_json']
            require(isinstance(encoded_decision, str) and len(encoded_decision.encode()) <= 65536,
                    'DASHBOARD_PROVIDER_ROW_INVALID')
            retry = json.loads(encoded_decision)
            require(type(retry) is dict and set(retry) == {
                        'disposition', 'reason', 'attempt', 'policy_fingerprint', 'delay_seconds',
                        'selected_next_at', 'persistable_next_at'}
                    and _canonical(retry) == encoded_decision
                    and retry.get('disposition') in ('succeeded', 'terminal_failed', 'unknown', 'retry')
                    and retry.get('policy_fingerprint') == decision['policy_fingerprint']
                    and type(retry.get('attempt')) is int
                    and retry['attempt'] == attempt['attempt_no']
                    and retry.get('delay_seconds') == decision['delay_seconds']
                    and instant(retry.get('persistable_next_at')) == instant(next_at)
                    and retry.get('selected_next_at') == retry.get('persistable_next_at'),
                    'DASHBOARD_PROVIDER_ROW_INVALID')
            disposition = retry['disposition']
            retry_reason = retry['reason']
            if disposition == 'retry':
                require(type(decision['delay_seconds']) in (int, float)
                        and math.isfinite(decision['delay_seconds'])
                        and decision['delay_seconds'] > 0 and next_at is not None
                        and next_at > recorded
                        and math.isclose(decision['delay_seconds'], next_at - recorded,
                                         rel_tol=0, abs_tol=1e-6)
                        and (retry_after is None or retry_after <= next_at)
                        and slot['status'] == 'retry_wait' and slot['next_attempt_at'] == next_at,
                        'DASHBOARD_PROVIDER_ROW_INVALID')
            else:
                require(decision['delay_seconds'] is None and next_at is None
                        and slot['next_attempt_at'] is None,
                        'DASHBOARD_PROVIDER_ROW_INVALID')
            reconciled = retry_reason == 'RECONCILIATION_ABSENT_RETRY'
            recovered = retry_reason == 'PROCESS_EXITED_OUTCOME_UNKNOWN'
            decision_now = datetime.fromtimestamp(recorded, UTC)
            if recovered:
                require(recorded == attempt['result_recorded_at']
                        and result is not None and result.status.value == 'unknown'
                        and result.code == 'PROCESS_EXITED_OUTCOME_UNKNOWN'
                        and result.phase.value == 'terminal'
                        and result.submission.value == 'possibly_submitted'
                        and result.terminal_proof.value == 'absent'
                        and result.failure_kind.value == 'unknown',
                        'DASHBOARD_PROVIDER_ROW_INVALID')
                expected = RetryDecision('unknown', 'PROCESS_EXITED_OUTCOME_UNKNOWN',
                                         attempt['attempt_no'], policy.fingerprint)
                expected_reason = expected.reason
                expected_retry_after = None
            elif reconciled:
                candidate = ProviderResultV1(
                    result.provider, result.operation_id, 'connecting', 'not_submitted', 'absent',
                    'retryable', 'RECONCILIATION_ABSENCE_VERIFIED', failure_kind='connection')
                expected = decide_retry(candidate, policy, slot_id=slot['slot_id'],
                                        attempt=attempt['attempt_no'], now=decision_now,
                                        deadline=deadline)
                expected_reason = 'RECONCILIATION_ABSENT_RETRY'
                expected_retry_after = None
            else:
                require(recorded == attempt['result_recorded_at'],
                        'DASHBOARD_PROVIDER_ROW_INVALID')
                expected = decide_retry(result, policy, slot_id=slot['slot_id'],
                                        attempt=attempt['attempt_no'], now=decision_now,
                                        deadline=deadline)
                if expected.disposition == 'retry' and not validate_replay(configured, result):
                    expected = RetryDecision('unknown', 'REPLAY_AUTHORITY_ABSENT',
                                             attempt['attempt_no'], policy.fingerprint)
                expected_reason = expected.reason
                expected_retry_after = (result.retry_after_at.timestamp()
                                        if result.retry_after_at is not None else None)
            expected_next = (expected.persistable_next_at.timestamp()
                             if expected.persistable_next_at is not None else None)
            expected_mapping = {
                'disposition': expected.disposition, 'reason': expected_reason,
                'attempt': expected.attempt, 'policy_fingerprint': expected.policy_fingerprint,
                'delay_seconds': expected.delay_seconds,
                'selected_next_at': (expected.selected_next_at.astimezone(UTC).isoformat()
                                     if expected.selected_next_at else None),
                'persistable_next_at': (expected.persistable_next_at.astimezone(UTC).isoformat()
                                        if expected.persistable_next_at else None)}
            require(retry == expected_mapping
                    and decision['policy_fingerprint'] == expected.policy_fingerprint
                    and decision['policy_version'] == policy.version
                    and decision['delay_seconds'] == expected.delay_seconds
                    and decision['retry_after_at'] == expected_retry_after
                    and decision['next_attempt_at'] == expected_next
                    and decision['deadline'] == (None if recovered else deadline_epoch)
                    and (slot['operation_id'] is None if recovered
                         else slot['operation_id'] == result.operation_id),
                    'DASHBOARD_PROVIDER_ROW_INVALID')
            expected_status = {'succeeded': 'succeeded', 'terminal_failed': 'failed',
                               'unknown': 'unknown', 'retry': 'retry_wait'}[disposition]
            if reconciled:
                require(decision['attempt_id'] == f"{attempt['attempt_id']}:reconciliation"
                        and attempt_status == 'unknown' and result is not None
                        and result.status.value == 'unknown' and reconciliation is not None,
                        'DASHBOARD_PROVIDER_ROW_INVALID')
                proof_value = json.loads(reconciliation['proof_json'])
                require(type(proof_value) is dict and set(proof_value) == {
                            'version', 'attempt_id', 'operation_id', 'slot_operation_scope',
                            'provider_result_sha256', 'outcome', 'evidence_sha256', 'recorded_at'}
                        and _canonical(proof_value) == reconciliation['proof_json'],
                        'DASHBOARD_PROVIDER_ROW_INVALID')
                proof = ReconciliationProofV1(
                    attempt_id=proof_value['attempt_id'], operation_id=proof_value['operation_id'],
                    slot_operation_scope=proof_value['slot_operation_scope'],
                    provider_result_sha256=proof_value['provider_result_sha256'],
                    outcome=proof_value['outcome'], evidence_sha256=proof_value['evidence_sha256'],
                    recorded_at=datetime.fromisoformat(instant(proof_value['recorded_at'])),
                    version=proof_value['version'])
                require(reconciliation['retry_decision_attempt_id'] == decision['attempt_id']
                        and reconciliation['consumed_attempt_id'] == attempt['attempt_id']
                        and reconciliation['record_attempt_id'] == attempt['attempt_id']
                        and reconciliation['record_slot_id'] == slot['slot_id']
                        and reconciliation['operation_id'] == result.operation_id
                        and reconciliation['slot_operation_scope'] == configured.slot_operation_scope
                        and proof.canonical_sha256 == reconciliation['proof_sha256']
                        and proof.evidence_sha256 == reconciliation['evidence_sha256']
                        and validate_replay(configured, result, reconciliation_proof=proof,
                            expected_attempt_id=attempt['attempt_id'],
                            expected_provider_result_sha256=attempt['canonical_sha256'],
                            expected_evidence_sha256=reconciliation['evidence_sha256'],
                            expected_proof_sha256=reconciliation['proof_sha256']),
                        'DASHBOARD_PROVIDER_ROW_INVALID')
                _finite_epoch(reconciliation['consumed_at'], nullable=False)
                _finite_epoch(reconciliation['recorded_at'], nullable=False)
            else:
                require(decision['attempt_id'] == attempt['attempt_id']
                        and reconciliation is None and attempt_status == expected_status
                        and slot['status'] == expected_status and result is not None,
                        'DASHBOARD_PROVIDER_ROW_INVALID')
                if disposition == 'retry':
                    require(validate_replay(configured, result),
                            'DASHBOARD_PROVIDER_ROW_INVALID')
            if disposition == 'retry':
                replay_authorization = 'authorized'
                if next_at > at.astimezone(UTC).timestamp():
                    delayed_until = instant(next_at)
                    delay_source = ('retry_after' if retry_after is not None
                                    and next_at == retry_after else 'backoff')
            elif unknown_fence:
                replay_authorization = ('reconciliation_required'
                                        if contract['effect'] == 'reconcile_before_replay'
                                        else 'not_authorized')
            else:
                replay_authorization = 'not_applicable'

    circuit_value = {'state': 'unavailable', 'open_until': None, 'probe_until': None,
                     'probe_eligible': False}
    if circuit is not None:
        state = _enum(circuit['state'], frozenset(('closed', 'open', 'half_open')))
        opened = _finite_epoch(circuit['opened_until'])
        probe = _finite_epoch(circuit['probe_expires'])
        _finite_epoch(circuit['updated_at'], nullable=False)
        scope_digest = hashlib.sha256(_canonical({
            'provider': provider, 'profile': profile_name,
            'resource_hash': resource_hash}).encode()).hexdigest()
        require(slot is not None and circuit['scope_sha256'] == scope_digest
                and circuit['config_sha256'] == slot['circuit_config_sha256']
                and type(circuit['generation']) is int and circuit['generation'] >= 0
                and type(circuit['transient_failures']) is int
                and circuit['transient_failures'] >= 0
                and ((state == 'closed' and opened is None
                      and circuit['probe_owner'] is None and probe is None)
                     or (state == 'open' and opened is not None
                         and circuit['probe_owner'] is None and probe is None)
                     or (state == 'half_open' and opened is None
                         and attempt_status == 'running' and slot['status'] == 'running'
                         and circuit['probe_owner'] == attempt['attempt_id']
                         and probe is not None)),
                'DASHBOARD_PROVIDER_ROW_INVALID')
        now = at.astimezone(UTC).timestamp()
        probe_eligible = ((state == 'open' and opened <= now)
                          or (state == 'half_open' and probe <= now))
        circuit_value = {'state': state, 'open_until': instant(opened),
                         'probe_until': instant(probe), 'probe_eligible': probe_eligible}
        if state == 'open' and opened > now:
            current = (datetime.fromisoformat(delayed_until).timestamp()
                       if delayed_until is not None else None)
            if current is None or opened > current:
                delayed_until, delay_source = instant(opened), 'circuit'

    require(type(queue['depth']) is int and 0 <= queue['depth'] <= 100000
            and ((queue['depth'] == 0 and queue['oldest'] is None)
                 or (queue['depth'] > 0
                     and _finite_epoch(queue['oldest'], nullable=False)
                     > at.astimezone(UTC).timestamp())),
            'DASHBOARD_PROVIDER_ROW_INVALID')
    return {'status': 'available', 'provider': provider, 'latest_attempt': latest,
            'delayed_until': delayed_until, 'delay_source': delay_source,
            'retry_reason': retry_reason, 'replay_authorization': replay_authorization,
            'circuit': circuit_value, 'unknown_fence': unknown_fence,
            'queue': {'depth': queue['depth'], 'oldest_delayed_at': instant(queue['oldest'])}}


def provider_safety(root, config, job, at, db=None):
    if db is not None:
        return _provider_safety_snapshot(root, config, job, at, db)
    path = root / '.job-runtime/engine/schedule.sqlite'
    with database(root, path) as snapshot:
        snapshot.execute('BEGIN')
        value = _provider_safety_snapshot(root, config, job, at, snapshot)
        snapshot.execute('COMMIT')
        return value


def domain(root, job, at, *, detail=False, output_id=None):
    # Fixed providers, never import a module named by an HTTP request/job string.
    if job.get('adapter') == 'niulai_runtime.daily_job:prepare':
        from niulai_runtime.scheduler_view import describe
        return describe(root, job, at, next_tick=next_tick, detail=detail, output_id=output_id)
    if job.get('adapter') == 'mentor.scheduler.job_adapter:prepare':
        from mentor.scheduler.scheduler_view import describe
        return describe(root, job, at, next_tick=next_tick, detail=detail, output_id=output_id)
    require(output_id is None, 'DASHBOARD_OUTPUT_NOT_FOUND')
    return {'title': job['id'], 'description': 'Scheduled Codex task',
            'delivery': {'mode': 'unspecified', 'next_send_at': None,
                         'note': 'This job does not declare a message delivery schedule.'}, 'outputs': []}


def _projection_config(root):
    """Load scheduler structure without opening or snapshotting prompt bodies."""
    optional = getattr(runtime_config, 'load_projection', None)
    if callable(optional):
        return optional(root / '.job-runtime/config/runtime.json', root)
    value = read_json(root, root / '.job-runtime/config/runtime.json')
    if value.get('schema_version') == 1:
        return load(root / '.job-runtime/config/runtime.json', root)
    require(value.get('schema_version') == 2, 'CONFIG_VERSION_INVALID')
    validate_retry_policy(value['retry'])
    require(isinstance(value.get('model_profiles'), dict) and value['model_profiles'], 'MODEL_PROFILES_REQUIRED')
    for name, profile in value['model_profiles'].items():
        require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', name), 'PROFILE_NAME_INVALID')
        runtime_config._v2_profile(profile, root)
    jobs = []
    for relative in value.get('allocation_files', []):
        require(isinstance(relative, str) and not Path(relative).is_absolute(), 'ALLOCATION_PATH_INVALID')
        allocation = read_json(root, inside(root / relative, root))
        require(set(allocation) == {'schema_version', 'jobs'} and allocation['schema_version'] == 2 and isinstance(allocation['jobs'], list), 'ALLOCATION_SCHEMA_INVALID')
        for source in allocation['jobs']:
            require(type(source) is dict and set(source) == runtime_config._V2_JOB_KEYS, 'JOB_KEYS_INVALID')
            require(source.get('model_profile') in value['model_profiles'], 'MODEL_PROFILE_NOT_FOUND')
            job = {key: item for key, item in source.items() if key != 'replay_contract'}
            job['_replay_contract'] = runtime_config._replay_contract(source['replay_contract'])
            jobs.append(job)
    return value, jobs


def prompt_custody(job_id, db):
    """Project proof counts only; never select prompt material or proof values."""
    if db is None:
        return {'status': 'unavailable', 'attempts_bound': 0}
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version == 8:
        return {'status': 'legacy_unbound', 'attempts_bound': 0}
    if version != 9:
        return {'status': 'unavailable', 'attempts_bound': 0}
    proof = {'artifact_ref', 'sha256', 'length', 'version', 'source_identity_sha256',
             'binding_sha256', 'generation', 'proof_origin'}
    slot_columns = {row[1] for row in db.execute('PRAGMA table_info(slots)')}
    attempt_columns = {row[1] for row in db.execute('PRAGMA table_info(attempts)')}
    if not proof <= slot_columns or not proof <= attempt_columns:
        return {'status': 'unavailable', 'attempts_bound': 0}
    material = sorted(proof - {'proof_origin'})
    slot_complete = ' AND '.join(f's.{name} IS NOT NULL' for name in material)
    attempt_complete = ' AND '.join(f'a.{name} IS NOT NULL' for name in material)
    row = db.execute(
        f'''SELECT COUNT(a.attempt_id) AS attempts_total,
                   COALESCE(SUM(CASE WHEN {attempt_complete}
                     AND a.proof_origin IN ('native_v1','backfilled_v8') THEN 1 ELSE 0 END),0) AS attempts_bound,
                   MAX(CASE WHEN {slot_complete} AND s.proof_origin='native_v1' THEN 1 ELSE 0 END) AS native_slot,
                   MAX(CASE WHEN {slot_complete} AND s.proof_origin='backfilled_v8' THEN 1 ELSE 0 END) AS backfilled_slot,
                   MAX(CASE WHEN s.proof_origin='legacy_unbound' THEN 1 ELSE 0 END) AS legacy_slot
            FROM slots s LEFT JOIN attempts a ON a.slot_id=s.slot_id
            WHERE s.slot_id=(SELECT slot_id FROM slots WHERE job_id=?
                             ORDER BY updated_at DESC,slot_id DESC LIMIT 1)''', (job_id,)).fetchone()
    if row is None:
        return {'status': 'unavailable', 'attempts_bound': 0}
    if row['legacy_slot'] == 1:
        return {'status': 'legacy_unbound', 'attempts_bound': 0}
    if row['attempts_bound'] != row['attempts_total'] or row['native_slot'] + row['backfilled_slot'] != 1:
        return {'status': 'unavailable', 'attempts_bound': 0}
    status = 'bound' if row['native_slot'] == 1 else 'backfilled'
    return {'status': status, 'attempts_bound': row['attempts_bound']}


def project(root=ROOT, *, job_id=None, output_id=None, at=None):
    root = Path(root).resolve(strict=True)
    at = at or datetime.now(UTC)
    require(at.tzinfo is not None, 'DASHBOARD_TIME_INVALID')
    config, jobs = _projection_config(root)
    require(len(jobs) <= 1000, 'DASHBOARD_JOB_LIMIT')
    require(job_id is None or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', job_id), 'DASHBOARD_JOB_INVALID')
    require(output_id is None or re.fullmatch(r'[a-f0-9]{64}', output_id), 'DASHBOARD_OUTPUT_INVALID')
    require(output_id is None or job_id is not None, 'DASHBOARD_JOB_REQUIRED')
    if job_id:
        jobs = [j for j in jobs if j['id'] == job_id]
        require(len(jobs) == 1, 'DASHBOARD_JOB_NOT_FOUND')
    projected, warnings = [], []
    engine_path = root / '.job-runtime/engine/schedule.sqlite'
    manager = packet_database(root, engine_path) if engine_path.exists() else nullcontext(None)
    with manager as snapshot:
        if snapshot is not None:
            snapshot.execute('BEGIN')
        for job in jobs:
            if config['schema_version'] == 1:
                validate_job(job)
            replay_safe = (job['replay_safe'] if config['schema_version'] == 1
                           else job['_replay_contract'].effect.value == 'none')
            item = {'id': job['id'], 'enabled': job['enabled'], 'schedule': job['schedule'],
                    'next_run_at': next_tick(job['schedule'], at) if job['enabled'] else None,
                    'replay_safe': replay_safe, 'model': config['model_profiles'][job['model_profile']].get('model'),
                    'effort': config['model_profiles'][job['model_profile']].get('effort'),
                    'history': [], 'outputs': []}
            try:
                item.update(domain(root, job, at, detail=bool(job_id), output_id=output_id))
                if item.get('job_type') == 'mentor' and item.get('mentor') == {'status': 'unavailable'}:
                    warnings.append({'job_id': job['id'], 'code': 'JOB_DETAILS_UNAVAILABLE'})
                if item.get('job_type') != 'mentor':
                    item['history'] = history(root, job['id'], snapshot) if job_id else history(root, job['id'], snapshot)[:1]
            except (OSError, ValueError, KeyError, sqlite3.Error):
                if output_id:
                    raise DashboardError('DASHBOARD_OUTPUT_UNAVAILABLE') from None
                item.update(title=job['id'], description='Job details are temporarily unavailable.',
                            delivery={'mode': 'unknown', 'next_send_at': None, 'note': 'Delivery evidence could not be read.'})
                warnings.append({'job_id': job['id'], 'code': 'JOB_DETAILS_UNAVAILABLE'})
            if config['schema_version'] == 2:
                try:
                    item['provider_safety'] = provider_safety(root, config, job, at, snapshot)
                except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
                    item['provider_safety'] = {'status': 'unavailable'}
                    warnings.append({'job_id': job['id'], 'code': 'PROVIDER_SAFETY_UNAVAILABLE'})
            if item.get('job_type') != 'mentor':
                try:
                    item['prompt_custody'] = prompt_custody(job['id'], snapshot)
                except (ValueError, KeyError, TypeError, sqlite3.Error):
                    item['prompt_custody'] = {'status': 'unavailable', 'attempts_bound': 0}
                    warnings.append({'job_id': job['id'], 'code': 'PROMPT_CUSTODY_UNAVAILABLE'})
            projected.append(item)
        if snapshot is not None:
            snapshot.execute('COMMIT')
    provider_items = [item['provider_safety'] for item in projected if 'provider_safety' in item]
    available = [item for item in provider_items if item.get('status') == 'available']
    provider_summary = {
        'status': ('not_applicable' if not provider_items else
                   'available' if len(available) == len(provider_items) else
                   'unavailable' if not available else 'partial'),
        'jobs': len(provider_items), 'available_jobs': len(available),
        'unknown_fences': sum(item.get('unknown_fence') is True for item in available),
        'delayed_jobs': sum(item.get('delayed_until') is not None for item in available),
        'queue_depth': sum(item.get('queue', {}).get('depth', 0) for item in available),
        'circuits': {state: sum(item.get('circuit', {}).get('state') == state for item in available)
                     for state in ('closed', 'open', 'half_open', 'unavailable')},
    }
    return {'schema_version': 1, 'generated_at': at.astimezone(UTC).isoformat(),
            'read_only': True, 'scope': 'local_codex_scheduler', 'status': 'partial' if warnings else 'ok',
            'health': health(root, at, config['stale_seconds']),
            'provider_safety': provider_summary, 'jobs': projected, 'warnings': warnings}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--job-id'); p.add_argument('--output-id')
    args = p.parse_args()
    try:
        value = project(job_id=args.job_id, output_id=args.output_id)
    except Exception:
        print(json.dumps({'schema_version': 1, 'status': 'unavailable', 'error': {'code': 'SCHEDULER_UNAVAILABLE'}}))
        raise SystemExit(1) from None
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
