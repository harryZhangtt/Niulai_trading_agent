"""Recurring business allocation and operator CLI; native connectors stay in host.

No consent, credential copying, cloud-task invocation or Gmail network client.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import select
import subprocess
import sys
import termios
import time

from .config import load_config, assert_recipient, ConfigError
from .daily_work import Work, private, atomic, require, sha, stamp
from .delivery import DeliveryError, assert_content_parity
from .scheduler import admit, ParallelRunEvidence
from .replay import from_raw

UTC = timezone.utc


def authorization(root, path, policy):
    path = private(root, path)
    require(path.is_file() and path.stat().st_mode & 0o077 == 0, 'DAILY_AUTHORIZATION_PRIVATE_REQUIRED')
    value = json.loads(path.read_text())
    require(set(value) == {'schema_version', 'parallel_sending_authorized', 'runtime_owner', 'automation_id', 'user_instruction', 'recorded_at'}
            and value['schema_version'] == 1 and value['parallel_sending_authorized'] is True
            and value['runtime_owner'] == policy.scheduler_owner and value['automation_id'] == policy.automation_id
            and bool(value['user_instruction']), 'DAILY_PARALLEL_AUTHORIZATION_REQUIRED')
    stamp(value['recorded_at'])
    return ParallelRunEvidence(sha(path.read_bytes()), policy.scheduler_owner)


def initialize(root, options, context):
    root = Path(root).resolve(); now = datetime.now(UTC); work = Work(root)
    require(set(options) <= {'policy', 'source_directory', 'authorization', 'target', 'request_id', 'session', 'fault_prices'}, 'DAILY_OPTIONS_INVALID')
    require(options.get('target') in ('schedule', 'recovery', 'acceptance'), 'DAILY_TARGET_REQUIRED')
    policy_path = private(root, root / options['policy'])
    policy = load_config(policy_path, root)
    if options['target'] == 'recovery':
        require(policy.mode == 'production' and policy.production_enabled, 'DAILY_PRODUCTION_DISABLED')
        authorization(root, root / options['authorization'], policy)
        row = work.due('production', now)
        if not row:
            return {'status': 'succeeded', 'code': 'DAILY_NO_RECOVERY_DUE', 'receipt': {'business_delivery': False}}
    else:
        from .e2e_guard import _preserved
        dates, _ = _preserved(root, 'session_date.py')
        completed = dates.latest_completed_session(now)
        if options['target'] == 'acceptance':
            require(policy.mode == 'manual_test' and not policy.production_enabled, 'DAILY_TEST_POLICY_REQUIRED')
            request = options.get('request_id')
            require(isinstance(request, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', request), 'DAILY_REQUEST_REQUIRED')
            require(options.get('session') == completed['date'], 'DAILY_LATEST_COMPLETED_SESSION_REQUIRED')
            day = completed['date']; slot = '19:00'; purpose = 'test'
            key = f'codex-acceptance:{policy.automation_id}:{request}:{policy.recipient}'
            price_asof = (stamp(completed['close_utc']) + timedelta(minutes=1)).isoformat()
        else:
            require(policy.mode == 'production' and policy.production_enabled, 'DAILY_PRODUCTION_DISABLED')
            from .wake import XNYS
            parallel = authorization(root, root / options['authorization'], policy)
            admitted = admit(policy, now, XNYS(), policy.scheduler_owner, parallel=parallel)
            if not admitted.allowed:
                return {'status': 'succeeded', 'code': 'DAILY_NOT_DUE', 'receipt': {'admission': asdict(admitted), 'business_delivery': False}}
            day = admitted.ny_date; slot = admitted.slot; purpose = 'production'
            key = admitted.delivery_key; price_asof = now.isoformat()
        identity = sha(key.encode())[:32]
        row = work.get(identity)
        if not row:
            source = private(root, root / options['source_directory'])
            target = private(root, root / '.niulai-state/daily' / identity / 'inputs', True)
            hashes = {}
            for name in ('workflow.json', 'alerts.json', 'alerts.sqlite'):
                src = private(root, source / name); require(src.is_file(), 'DAILY_SOURCE_MISSING')
                dst = target / name
                if not dst.exists():
                    if name.endswith('.sqlite'):
                        from .e2e_prepare import clone_database
                        clone_database(src, dst)
                    else:
                        shutil.copyfile(src, dst); dst.chmod(0o600)
                hashes[name] = sha(dst.read_bytes())
            scheduled = stamp(context['scheduled_at'])
            meta = {'schema_version': 1, 'purpose': purpose, 'recipient': policy.recipient,
                'ny_date': day, 'slot': slot, 'scope': identity, 'scheduled_at': scheduled.isoformat(),
                'deadline': (scheduled + timedelta(minutes=60)).isoformat(), 'price_asof': price_asof,
                'holdings_session': completed['date'], 'inputs': str(target), 'input_sha256': hashes,
                'policy': str(policy_path), 'authorization': options.get('authorization'),
                'fault_prices': options.get('fault_prices', False) if purpose == 'test' else False}
            # Current enabled workflow role is required even for acceptance.
            workflow = json.loads((target / 'workflow.json').read_text())
            role = next((r for r in workflow['schedules'] if r['role'] == 'existing_summary'), None)
            require(role is not None and role.get('enabled') is True
                    and role.get('timezone') == policy.timezone and role.get('times') == list(policy.slots)
                    and role.get('runtime_slot_grace_minutes', 60) == policy.grace_minutes
                    and role.get('automation_id') == policy.automation_id
                    and workflow['notifications']['policies']['existing_summary']['enabled'] is True,
                    'DAILY_SOURCE_ROLE_DISABLED')
            row = work.create(key, meta)
    identity = row['id']
    if not work.claim(identity, context['attempt_id'], now):
        return {'status': 'succeeded', 'code': 'DAILY_NO_SENDABLE_WORK',
                'receipt': {'work_id': identity, 'state': work.get(identity)['state'], 'business_delivery': False}}
    row = work.get(identity)
    out = private(root, root / '.niulai-state/daily' / identity, True)
    atomic(out / 'work.json', row['meta'])
    return {'workspace': str(root), 'work_id': identity, 'output_directory': str(out),
        'recipient': policy.recipient, 'purpose': row['meta']['purpose'],
        'tiger_policy': str(root / '.niulai-state/config/tiger.json'),
        'holdings_ready': (out / 'holdings/tiger_status.json').exists(),
        'price_ready': (out / 'prices/branch.json').exists()}


def prepare(options, workspace, context):
    root = Path(workspace).resolve()
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'LANG', 'SSL_CERT_FILE', 'SSL_CERT_DIR') if k in os.environ}
    env.update(PYTHONPATH=str(root) + os.pathsep + str(root / 'niulai-runtime'),
               PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(root / '.niulai-state/tmp'))
    cp = subprocess.run([str(root / '.niulai-state/.venv/bin/python'), '-m', 'niulai_runtime.daily_job',
        'initialize', '--workspace', str(root)], input=json.dumps({'options': options, 'context': context}),
        capture_output=True, text=True, env=env, cwd=root, timeout=30)
    if cp.returncode:
        try:
            code = json.loads(cp.stdout)['error']
        except Exception:
            code = 'DAILY_INITIALIZATION_FAILED'
        return {'status': 'failed', 'code': code}
    return json.loads(cp.stdout)


def load_work(root, identity):
    require(isinstance(identity, str) and re.fullmatch('[a-f0-9]{32}', identity), 'DAILY_WORK_ID_INVALID')
    work = Work(root); row = work.get(identity); require(row is not None, 'DAILY_WORK_MISSING')
    meta = row['meta']; out = private(root, Path(root) / '.niulai-state/daily' / identity)
    return work, row, meta, out


def plan(root, identity):
    from .daily_report import compose, branch_state
    work, row, meta, out = load_work(root, identity)
    initial = work.outbox.get(row['initial_key']) if row['initial_key'] else None
    if initial and (initial['status'] in ('sending', 'unknown') or
                    initial['status'] == 'accepted' and not initial['verified_at']):
        return {'status': 'reconcile', 'message_id': initial['message_id'], 'key': row['initial_key']}
    correction = bool(initial and initial['status'] == 'accepted' and initial['verified_at'])
    if correction:
        state = branch_state(out)
        if state['pending'] or state['blocked']:
            return {'status': 'no_new_delivery'}
        original = json.loads((out / 'mail/initial/integrity.json').read_text())
        if not original['pending'] and not original['blocked']:
            return {'status': 'no_new_delivery'}
    result = compose(root, out, meta, identity, correction, initial['message_id'] if correction else None)
    key = (row['logical_key'] + ':correction:' + result['digest'][:24]) if correction else row['logical_key']
    work.bind_delivery(identity, key, correction)
    sent = work.outbox.get(key)
    return {'status': sent['status'] if sent else 'composed', 'key': key, 'directory': result['directory'],
            'correction': correction, 'message_id': sent['message_id'] if sent else None, **result}


def bind_draft(directory, payload, recipient, draft_id, message_id, encoded):
    require(isinstance(draft_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{5,200}', draft_id), 'DAILY_DRAFT_ID_REQUIRED')
    require(isinstance(message_id, str) and re.fullmatch(r'[a-fA-F0-9]{8,64}', message_id), 'DAILY_DRAFT_MESSAGE_REQUIRED')
    fp = assert_content_parity(payload, from_raw(encoded, recipient), recipient, recipient)
    value = {'draft_id': draft_id, 'draft_message_id': message_id, 'payload_digest': fp['digest'],
             'readback_sha256': sha(encoded.encode())}
    path = directory / 'draft.json'
    if path.exists():
        require(json.loads(path.read_text()) == value, 'DAILY_DRAFT_IMMUTABLE')
    else:
        atomic(path, value)
    return value


def capture_readback(root, out, path, count):
    path = private(root, path)
    require(path.parent in (out / 'mail/initial', out / 'mail/correction') and
            path.name in ('draft_readback.b64', 'gmail_readback.b64'), 'DAILY_READBACK_PATH_REJECTED')
    require(type(count) is int and 0 < count <= 28 * 1024 * 1024, 'DAILY_READBACK_SIZE_INVALID')
    fd = sys.stdin.fileno(); require(os.isatty(fd), 'DAILY_READBACK_TTY_REQUIRED')
    old = termios.tcgetattr(fd); settings = list(old); settings[3] &= ~(termios.ECHO | termios.ICANON)
    received = bytearray(); deadline = time.monotonic() + 60
    try:
        termios.tcsetattr(fd, termios.TCSANOW, settings)
        print('RAW_INPUT_READY', flush=True)
        while len(received) < count:
            left = deadline - time.monotonic(); require(left > 0, 'DAILY_READBACK_INPUT_TIMEOUT')
            ready, _, _ = select.select([fd], [], [], min(left, 1))
            if ready:
                chunk = os.read(fd, min(65536, count - len(received)))
                require(bool(chunk), 'DAILY_READBACK_INPUT_EOF'); received.extend(chunk)
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, old)
    require(re.fullmatch(rb'[A-Za-z0-9_-]+={0,2}', received) is not None, 'DAILY_READBACK_BASE64_INVALID')
    if path.exists():
        require(path.read_bytes() == received, 'DAILY_READBACK_IMMUTABLE')
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(received); stream.flush(); os.fsync(stream.fileno())
    return {'saved': True, 'bytes': len(received)}


def verify(options, workspace, context, result):
    from .daily_report import validate
    root = Path(workspace).resolve(); work = Work(root)
    # Bind the host's attempt claim, not a model-chosen report directory.
    with work.connect() as db:
        rows = db.execute('SELECT id FROM digest_work WHERE lease_owner=?', (context['attempt_id'],)).fetchall()
    # settle clears lease; the immutable host-attempt binding remains in work.json.
    if not rows:
        paths = list((root / '.niulai-state/daily').glob('*/execution.json'))
        rows = [{'id': p.parent.name} for p in paths if json.loads(p.read_text()).get('attempt_id') == context['attempt_id']]
    if len(rows) != 1:
        return {'verified': False}
    _, row, meta, out = load_work(root, rows[0]['id'])
    key = row['correction_key'] or row['initial_key']
    sent = work.outbox.get(key) if key else None
    if not sent or sent['status'] != 'accepted' or not sent['verified_at']:
        return {'verified': False}
    directory = out / 'mail' / ('correction' if row['correction_key'] else 'initial')
    checked = validate(root, directory, meta, row['id'])
    require(sent['digest'] == checked['digest'], 'DAILY_OUTBOX_DIGEST_MISMATCH')
    payload = json.loads((directory / 'payload.json').read_text())
    assert_content_parity(payload, from_raw((directory / 'gmail_readback.b64').read_text(), meta['recipient']), meta['recipient'], meta['recipient'])
    tools = result.get('receipt', {}).get('tool_names', [])
    if not all(any(s in t.replace('__', '.') for t in tools) for s in ('gmail.create_draft', 'gmail.send_draft', 'gmail.read_email')):
        return {'verified': False}
    draft = json.loads((directory / 'draft.json').read_text())
    require(draft['payload_digest'] == sent['digest'], 'DAILY_DRAFT_DIGEST_MISMATCH')
    if checked['holdings_ok']:
        portfolio = json.loads((directory / 'sources/holdings/daily.json').read_text())
        fetched = stamp(portfolio['accounts'][0]['position_totals']['snapshot_query_at'])
        require(fetched >= stamp(meta['scheduled_at']), 'DAILY_FRESH_HOLDINGS_REQUIRED')
    branch = json.loads((directory / 'sources/prices/branch.json').read_text())
    if meta['purpose'] == 'test' and not branch.get('synthetic_fault'):
        require(checked['holdings_ok'], 'DAILY_ACCEPTANCE_REAL_HOLDINGS_REQUIRED')
        require(branch['coverage']['valid_symbols'] > 0, 'DAILY_ACCEPTANCE_REAL_PRICES_REQUIRED')
    if not branch.get('synthetic_fault'):
        import sqlite3
        database = (root / '.niulai-state/databases/daily-prices.sqlite' if meta['purpose'] == 'production'
                    else out / 'prices/observations.sqlite')
        price = json.loads((directory / 'sources/prices/price_result.json').read_text())
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
            observations = [json.loads(r[0]) for r in db.execute('SELECT payload FROM price_sources WHERE run_id=?', (price['id'],))]
        require(len(observations) == price['coverage']['symbols'], 'DAILY_RAW_SCOPE_REQUIRED')
        require(all(o.get('error') or o.get('raw') and o.get('sha256') == sha(o['raw'].encode()) for o in observations), 'DAILY_RAW_PROVENANCE_REQUIRED')
        require(all(stamp(o['retrieved_at']) >= stamp(meta['scheduled_at']) for o in observations), 'DAILY_FRESH_PRICES_REQUIRED')
    return {'verified': True, 'message_id': sent['message_id'], 'verified_at': sent['verified_at'],
            'payload_digest': sent['digest'], 'work_id': row['id'], 'partial': checked['partial'],
            'state': row['state'], 'purpose': meta['purpose']}


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(); p.add_argument('action', choices=['initialize', 'prices', 'prices-failure', 'holdings-failure', 'plan',
        'draft-verify', 'capture-readback',
        'prepare', 'claim', 'accepted', 'unknown', 'verify', 'reconcile', 'settle', 'status'])
    p.add_argument('--workspace', required=True); p.add_argument('--work-id'); p.add_argument('--attempt-id')
    p.add_argument('--message-id'); p.add_argument('--readback'); p.add_argument('--code', default='HOLDINGS_UNAVAILABLE')
    p.add_argument('--draft-id'); p.add_argument('--bytes', type=int)
    a = p.parse_args(); root = Path(a.workspace).resolve(strict=True)
    if a.action == 'initialize':
        data = json.load(sys.stdin); result = initialize(root, data['options'], data['context'])
        if result.get('work_id') and result.get('output_directory'):
            atomic(Path(result['output_directory']) / 'execution.json', {'attempt_id': data['context']['attempt_id']})
    else:
        work, row, meta, out = load_work(root, a.work_id)
        if a.action == 'capture-readback':
            result = capture_readback(root, out, a.readback, a.bytes)
        elif a.action in ('prices', 'prices-failure'):
            from .daily_prices import prepare as prices
            initial = work.outbox.get(row['initial_key']) if row['initial_key'] else None
            if initial and (initial['status'] != 'accepted' or not initial['verified_at']):
                result = json.loads((out / 'prices/branch.json').read_text())
                result['deferred_until_delivery_verified'] = True
            else:
                result = prices(root, out / 'prices', meta, fault=meta['fault_prices'] and row['tries'] == 1,
                                offline=a.action == 'prices-failure')
        elif a.action == 'holdings-failure':
            from .daily_report import failure_holdings
            failure_holdings(root, out / 'holdings', meta['holdings_session'], a.code)
            result = {'status': 'unavailable', 'error': a.code}
        elif a.action == 'plan':
            result = plan(root, a.work_id)
        elif a.action == 'settle':
            from .daily_report import branch_state
            state = branch_state(out)
            result = work.settle(a.work_id, pending=state['pending'], blocked=state['blocked'])
            result = {k: result[k] for k in ('state', 'due_at', 'tries', 'last_code')}
        elif a.action == 'status':
            result = {k: row[k] for k in ('id', 'state', 'due_at', 'tries', 'last_code')}
        else:
            policy = load_config(meta['policy'], root)
            require(policy.recipient == meta['recipient'], 'DAILY_POLICY_RECIPIENT_CHANGED')
            if meta['purpose'] == 'production' and a.action in ('prepare', 'claim'):
                require(policy.mode == 'production' and policy.production_enabled, 'DAILY_PRODUCTION_DISABLED')
                authorization(root, root / meta['authorization'], policy)
            from .daily_report import validate
            correction = bool(row['correction_key']); key = row['correction_key'] or row['initial_key']
            directory = out / 'mail' / ('correction' if correction else 'initial')
            validate(root, directory, meta, a.work_id)
            payload = json.loads((directory / 'payload.json').read_text())
            if a.action == 'draft-verify':
                sent = work.outbox.get(key)
                require(sent and sent['status'] == 'prepared', 'DAILY_DRAFT_REQUIRES_PREPARED')
                result = bind_draft(directory, payload, policy.recipient, a.draft_id, a.message_id,
                                    private(root, a.readback).read_text())
            elif a.action in ('prepare', 'claim'):
                profile = json.load(sys.stdin); assert_recipient(policy, profile.get('email'), payload['to'])
                if a.action == 'prepare':
                    sent = work.outbox.prepare(key, payload, recipient=policy.recipient, profile_email=profile['email'])
                    result = {'status': sent['status'], 'digest': sent['digest']}
                else:
                    draft = json.loads((directory / 'draft.json').read_text())
                    require(draft['draft_id'] == a.draft_id and draft['payload_digest'] == work.outbox.get(key)['digest'],
                            'DAILY_VERIFIED_DRAFT_REQUIRED')
                    encoded = (directory / 'draft_readback.b64').read_text()
                    require(sha(encoded.encode()) == draft['readback_sha256'], 'DAILY_DRAFT_READBACK_CHANGED')
                    bind_draft(directory, payload, policy.recipient, draft['draft_id'], draft['draft_message_id'], encoded)
                    work.outbox.claim(key, a.attempt_id)
                    result = {'draft_id': draft['draft_id']}
            elif a.action == 'accepted':
                result = work.outbox.accepted(key, a.attempt_id, a.message_id)
            elif a.action == 'unknown':
                result = work.outbox.unknown(key, a.attempt_id)
            else:
                actual = from_raw(private(root, a.readback).read_text(), policy.recipient)
                sent = work.outbox.get(key)
                require(sent is not None, 'DAILY_ACCEPTED_RECEIPT_REQUIRED')
                if a.action == 'verify':
                    require(sent['status'] == 'accepted' and sent['message_id'] == a.message_id, 'DAILY_ACCEPTED_RECEIPT_REQUIRED')
                fp = assert_content_parity(payload, actual, policy.recipient, policy.recipient)
                result = work.outbox.reconcile_accepted(key, message_id=a.message_id, verified_digest=fp['digest'])
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        code = str(exc) if isinstance(exc, (ConfigError, DeliveryError)) else 'DAILY_OPERATION_FAILED'
        print(json.dumps({'status': 'failed', 'error': code})); raise SystemExit(2)
