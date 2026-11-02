"""Finite review/capture continuation; no parent-thread autoresume or acquisition.

The parent stages immutable public work packets. Actual read-only Codex sessions
produce closed-schema results, checked against parent-owned postconditions. The
primary scheduler, credentials, code and immutable experiment inputs are untouched.
"""
from datetime import datetime, timedelta, timezone
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import sqlite3
import subprocess
import time
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator
from .engine import Engine
from .model import _private_path, run_codex
from .service import atomic
from shared.research_sources.artifacts import ROOT, SOURCE_STATE, digest, encoded, private_path, read, require, save

UTC = timezone.utc
STUDY = SOURCE_STATE / 'runtime/acquisition-ab-now-20261102'
KINDS = {'trace_diagnosis', 'pooled_review_order1', 'pooled_review_order2', 'regression_review'}
TERMINAL = {'expired', 'stopped_manual', 'stopped_budget', 'stopped_stalled', 'stopped_failed', 'unknown'}
VERSION = 'review-continuation-1.0.1'


def now(): return datetime.now(UTC)
def load(path): return json.loads(Path(path).read_bytes())
def fingerprint(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pins(root):
    names = ['shared/job_runtime/' + name for name in ['review_campaign.py', 'engine.py', 'model.py', 'service.py']]
    names += ['shared/research_sources/artifacts.py']
    names += ['mentor/session_init.py', 'mentor/AGENTS.md', 'mentor/ROUTING.md']
    return {name: fingerprint(root / name) for name in names}


def profile(root): return load(root / '.job-runtime/config/runtime.json')['model_profiles']['default']


def artifact(ref, category):
    path = private_path(ref['path'])
    require(path.is_relative_to(STUDY / 'continuation' / category) and path.stat().st_size <= 256 * 1024, 'REVIEW_PACKET_PATH_REJECTED')
    return read(ref)


def packet(ref):
    value = artifact(ref, 'work')
    require(isinstance(value, dict) and value.get('schema_version') == 1 and value.get('kind') in KINDS
            and isinstance(value.get('work_id'), str) and re.fullmatch('[A-Za-z0-9_.-]{1,96}', value['work_id'])
            and isinstance(value.get('objective'), str) and 0 < len(value['objective']) <= 6000
            and isinstance(value.get('role'), str) and len(value['role']) <= 80, 'REVIEW_PACKET_INVALID')
    refs = value.get('input_refs'); schema = value.get('output_schema')
    require(isinstance(refs, list) and 0 < len(refs) <= 12 and len({item['name'] for item in refs}) == len(refs), 'REVIEW_INPUT_LIMIT')
    require(isinstance(schema, dict) and schema.get('type') == 'object' and schema.get('additionalProperties') is False
            and isinstance(schema.get('properties'), dict) and set(schema.get('required', [])) == set(schema['properties'])
            and len(encoded(schema)) <= 32768, 'REVIEW_OUTPUT_SCHEMA_INVALID')
    Draft202012Validator.check_schema(schema)
    inputs = {item['name']: artifact(item['ref'], 'public-inputs') for item in refs}
    require(len(encoded(inputs)) <= 256 * 1024, 'REVIEW_INPUT_BYTES_EXCEEDED')
    policy = artifact(value['postcondition_ref'], 'policies')
    require(isinstance(policy, dict) and policy.get('owner') == 'root:review_campaign_v1'
            and isinstance(policy.get('checks'), list) and 0 < len(policy['checks']) <= 40, 'REVIEW_POSTCONDITION_OWNER_INVALID')
    return value, inputs, policy


def work_key(value):
    return digest({'inputs': [(item['name'], item['ref']['sha256']) for item in value['input_refs']],
                   'policy': value['postcondition_ref']['sha256'], 'role': value['role'], 'kind': value['kind']})


def pointer(value, path):
    require(isinstance(path, str) and path.startswith('/') and len(path) <= 300, 'REVIEW_POINTER_INVALID')
    for part in path[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def verify(value, inputs, policy, output):
    require(Draft202012Validator(value['output_schema']).is_valid(output), 'REVIEW_RESPONSE_SCHEMA_INVALID')
    require(output.get('work_id') == value['work_id'], 'REVIEW_RESPONSE_WORK_MISMATCH')
    for check in policy['checks']:
        actual = pointer(output, check['output_pointer']); operation = check['op']
        if operation == 'equals_input':
            require(actual == pointer(inputs[check['input_name']], check['input_pointer']), 'REVIEW_FACT_BINDING_FAILED')
        elif operation == 'equals': require(actual == check['value'], 'REVIEW_POSTCONDITION_FAILED')
        elif operation == 'minimum_length': require(isinstance(actual, str) and len(actual.strip()) >= check['minimum'], 'REVIEW_DIAGNOSIS_EMPTY')
        elif operation == 'contains_codes':
            require(isinstance(actual, list) and set(check['codes']) <= {item.get('code') for item in actual if isinstance(item, dict)}, 'REVIEW_REQUIRED_DIAGNOSIS_MISSING')
        elif operation == 'input_hashes':
            require(actual == [item['ref']['sha256'] for item in value['input_refs']], 'REVIEW_INPUT_HASH_BINDING_FAILED')
        elif operation == 'source_span':
            source = read(check['source_ref'])
            require(source.get('text') == check['text_ref']
                    and pointer(output, check['source_sha_output_pointer']) == check['source_ref']['sha256'], 'REVIEW_SOURCE_IDENTITY_MISMATCH')
            text = read(check['text_ref'], json_value=False).decode()
            require(type(check['start']) is int and type(check['end']) is int and 0 <= check['start'] < check['end'] <= len(text)
                    and actual == text[check['start']:check['end']], 'REVIEW_SOURCE_QUOTE_MISMATCH')
        else: raise ValueError('REVIEW_POSTCONDITION_UNSUPPORTED')
    return {'verified': True, 'checks': len(policy['checks']), 'owner': policy['owner'],
            'scope': 'bound_review_result_not_acquisition_or_semantic_truth_guarantee'}


def decision(config, state, at):
    if state['status'] in TERMINAL: return state['status']
    if at.timestamp() >= config['expires_at']: return 'expired'
    if at.timestamp() < state.get('last_tick', 0) - 5 or state.get('active_attempt'): return 'unknown'
    if state['calls'] >= config['max_calls'] or state['model_seconds'] >= config['max_model_seconds'] or state['tokens'] >= config['max_tokens']: return 'stopped_budget'
    if state['no_progress'] >= 2 or state['same_failure'] >= 2: return 'stopped_stalled'
    return None


def production_priority(root, duration, at=None):
    at = at or now(); config = load(root / '.job-runtime/config/runtime.json')
    jobs = [job for relative in config['allocation_files'] for job in load(root / relative)['jobs']]
    enabled = {job['id'] for job in jobs if job['enabled']}
    dbpath = root / '.job-runtime/engine/schedule.sqlite'; ignored = 0
    if dbpath.exists():
        with sqlite3.connect('file:' + str(dbpath) + '?mode=ro', uri=True) as db:
            for job, status in db.execute("SELECT job_id,status FROM slots WHERE status IN ('running','unknown','ready','retry_wait')"):
                if status == 'running' or job in enabled: return {'busy': True, 'reason': 'active_primary_slot', 'disabled_unknown_fences_preserved': ignored}
                if status == 'unknown': ignored += 1
    for job in jobs:
        if not job['enabled'] or job['schedule']['kind'] != 'daily': continue
        schedule = job['schedule']; local = at.astimezone(ZoneInfo(schedule['timezone']))
        for days in [0, 1]:
            for clock in schedule['times']:
                hour, minute = map(int, clock.split(':'))
                due = (local + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
                if 0 <= (due - local).total_seconds() <= duration + 120:
                    return {'busy': True, 'reason': 'imminent_daily_business', 'disabled_unknown_fences_preserved': ignored}
    return {'busy': False, 'reason': 'no_active_primary_claim', 'disabled_unknown_fences_preserved': ignored}


def reconcile_process(base, state):
    active = state.get('active_attempt')
    if not active: return
    path = base / 'attempts' / active / 'process.json'
    if not path.exists(): return
    saved = load(path)
    observed = subprocess.run(['/bin/ps', '-p', str(saved['pid']), '-o', 'lstart=', '-o', 'command='], capture_output=True, text=True, timeout=5)
    if saved['birth'] and saved['birth'] in observed.stdout and saved['attempt_directory'] in observed.stdout:
        for sig in [signal.SIGTERM, signal.SIGKILL]:
            try: os.killpg(saved['pid'], sig)
            except ProcessLookupError: break


def dispatch(root, base, config, state, context):
    guard = decision(config, state, now())
    if guard:
        state['status'] = guard; return {'status': 'failed', 'code': 'REVIEW_CAMPAIGN_GUARD_STOP', 'receipt': {'guard': guard}}
    priority = production_priority(root, config['slice_seconds'])
    if priority['busy']: return {'status': 'succeeded', 'code': 'REVIEW_CAMPAIGN_YIELDED', 'receipt': priority}
    entries = sorted((base / 'queue').glob('*.json'))
    require(len(entries) <= 64, 'REVIEW_QUEUE_LIMIT')
    chosen = None
    for entry in entries:
        require(not entry.is_symlink(), 'REVIEW_QUEUE_UNSAFE')
        ref = load(entry); work, inputs, policy = packet(ref); identifier = work_key(work)
        if identifier not in state['work']:
            chosen = (ref, work, inputs, policy, identifier); break
    if chosen is None: return {'status': 'succeeded', 'code': 'REVIEW_QUEUE_EMPTY', 'receipt': {'model_started': False}}
    ref, work, inputs, policy, identifier = chosen
    remaining = min(config['slice_seconds'], config['expires_at'] - now().timestamp() - 5, config['max_model_seconds'] - state['model_seconds'])
    if remaining < 10:
        state['status'] = 'stopped_budget'; return {'status': 'failed', 'code': 'REVIEW_TIME_EXHAUSTED', 'receipt': {}}
    require(digest(profile(root)) == config['profile_sha256'] and pins(root) == config['pins'], 'REVIEW_SOURCE_CHANGED')
    attempt = _private_path(base / 'attempts' / context['attempt_id'], root, directory=True)
    from mentor.session_init import initialize
    manual_context = initialize(root, {'hook_event_name': 'SessionStart', 'source': 'resume', 'cwd': str(root)})
    mentor_context = manual_context['hookSpecificOutput']['additionalContext']
    atomic(attempt / 'manual-mentor-context.json', {'origin': 'explicit_controller_load_not_automatic_app_hook', 'result': manual_context})
    require(mentor_context.startswith('MENTOR_INIT_OK\n'), 'REVIEW_MENTOR_CONTEXT_INVALID')
    state['active_attempt'] = context['attempt_id']; state['calls'] += 1
    state['work'][identifier] = {'work_id': work['work_id'], 'status': 'running', 'packet_sha256': ref['sha256'], 'attempt_id': context['attempt_id']}
    atomic(base / 'state.json', state)
    class Cancel:
        def is_set(self): return (base / 'stop-requested').exists() or now().timestamp() >= config['expires_at']
    def observe(pid):
        birth = subprocess.check_output(['/bin/ps', '-p', str(pid), '-o', 'lstart='], text=True, timeout=5).strip()
        require(bool(birth), 'REVIEW_PROCESS_IDENTITY_UNAVAILABLE')
        atomic(attempt / 'process.json', {'pid': pid, 'birth': birth, 'attempt_directory': str(attempt)})
    prompt = json.dumps({'objective': work['objective'], 'role': work['role'], 'work_id': work['work_id'],
        'mentor_context': mentor_context,
        'input_sha256s': [item['ref']['sha256'] for item in work['input_refs']], 'inputs': inputs,
        'instructions': ['Use only these staged public inputs. No web, apps, shell, credentials or other-arm/private gold data.',
            'This is actual trace/capture review, not new acquisition or proof that a model review is true.',
            'Return the closed-schema result with evidence-bound counts, quotations and concrete limitations.']}, ensure_ascii=False)
    began = time.monotonic()
    result = run_codex(dict(profile(root), timeout_seconds=min(remaining, profile(root)['timeout_seconds'])), prompt, root,
        attempt / 'model', context={'response_schema': work['output_schema'], 'cancel_event': Cancel(), 'process_observer': observe})
    elapsed = time.monotonic() - began
    if result.get('code') == 'MODEL_AUTH_CACHE_BUSY':
        state['calls'] -= 1; state['active_attempt'] = None; state['work'].pop(identifier, None)
        return {'status': 'succeeded', 'code': 'REVIEW_CAMPAIGN_YIELDED_AUTH', 'receipt': {'model_started': False}}
    state['model_seconds'] += elapsed; receipt = result.get('receipt', {}); usage = receipt.get('usage')
    telemetry = isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0 for key in ['input_tokens', 'output_tokens'])
    if telemetry: state['tokens'] += usage['input_tokens'] + usage['output_tokens']
    proof = None; output_ref = None; failure = result.get('code', 'REVIEW_RESULT_UNAVAILABLE')
    if result.get('status') == 'succeeded' and telemetry:
        try:
            response = _private_path(root / receipt['response_path'], root)
            require(response.stat().st_size <= 256 * 1024 and fingerprint(response) == receipt['response_sha256']
                    and receipt.get('turn_completed') is True and receipt.get('thread_id'), 'REVIEW_TRANSPORT_BINDING_INVALID')
            output = load(response); proof = verify(work, inputs, policy, output)
            output_ref = save(STUDY / 'continuation/model-outputs', {'work_id': work['work_id'], 'packet_sha256': ref['sha256'],
                'result': output, 'postcondition': proof, 'model_response_sha256': receipt['response_sha256']})
        except Exception as error:
            proof = None
            failure = str(error) if re.fullmatch('[A-Z_]{1,100}', str(error)) else 'REVIEW_POSTCONDITION_FAILED'
    progressed = proof is not None
    if progressed and receipt['response_sha256'] in state['seen_outputs']:
        progressed = False; failure = 'REVIEW_OUTPUT_CYCLE'
    if progressed:
        state['seen_outputs'].append(receipt['response_sha256']); state['no_progress'] = 0; state['same_failure'] = 0; state['last_failure'] = None
        state['work'][identifier].update(status='verified', output_ref=output_ref)
    else:
        state['no_progress'] += 1
        state['same_failure'] = state['same_failure'] + 1 if failure == state.get('last_failure') else 1
        state['last_failure'] = failure; state['work'][identifier]['status'] = 'failed'
        if result.get('status') == 'unknown' or not telemetry:
            state['status'] = 'unknown'; state['work'][identifier]['status'] = 'unknown'
        elif failure == 'REVIEW_OUTPUT_CYCLE' or state['no_progress'] >= 2 or state['same_failure'] >= 2: state['status'] = 'stopped_stalled'
    state['active_attempt'] = None
    report = {'context': context, 'work_id': work['work_id'], 'work_key': identifier, 'packet_ref': ref, 'result': result,
        'postcondition': proof, 'output_ref': output_ref, 'progressed': progressed, 'elapsed_seconds': elapsed,
        'telemetry_known': telemetry, 'failure': None if progressed else failure, 'priority': priority, 'ended_at': now().isoformat()}
    atomic(attempt / 'receipt.json', report); state['last_receipt'] = str((attempt / 'receipt.json').relative_to(root))
    atomic(base / 'state.json', state)
    return {'status': 'succeeded' if progressed else 'unknown' if state['status'] == 'unknown' else 'failed',
            'code': 'REVIEW_RESULT_VERIFIED' if progressed else failure, 'receipt': {'report': state['last_receipt'], 'progressed': progressed}}


def tick(root, base):
    fd = os.open(base / 'campaign.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return {'status': 'busy'}
        config = load(base / 'config.json'); state = load(base / 'state.json')
        guard = decision(config, state, now())
        if (base / 'stop-requested').exists(): guard = 'stopped_manual'
        if config['pins'] != pins(root) or config['profile_sha256'] != digest(profile(root)): guard = 'unknown'
        if guard: state['status'] = guard
        state['last_tick'] = now().timestamp(); atomic(base / 'state.json', state)
        if state['status'] in TERMINAL:
            reconcile_process(base, state)
            subprocess.run(['/bin/launchctl', 'bootout', 'gui/%d/%s' % (os.getuid(), config['label'])], capture_output=True, timeout=10)
            return state
        engine = Engine(base / 'engine', config['jobs'], {'max_attempts': 1, 'backoff_seconds': 30, 'max_backoff_seconds': 30},
            lambda job, context: dispatch(root, base, config, state, context), workspace_root=root, max_workers=1)
        try: result = engine.tick(now())
        except BaseException:
            state['status'] = 'unknown'; atomic(base / 'state.json', state); raise
        atomic(base / 'state.json', state)
        return {'status': state['status'], 'scheduler': result}
    finally: os.close(fd)


def create(root, name, predecessor=None):
    require(isinstance(name, str) and re.fullmatch('[A-Za-z0-9-]{1,60}', name), 'REVIEW_CAMPAIGN_NAME_INVALID')
    base = _private_path(root / '.job-runtime/review-campaigns' / name, root)
    require(not base.exists(), 'REVIEW_CAMPAIGN_EXISTS'); _private_path(base / 'queue', root, directory=True)
    at = now(); expires = (at + timedelta(hours=6)).timestamp(); usage = {'calls': 0, 'model_seconds': 0, 'tokens': 0}; lineage = None
    if predecessor is not None:
        predecessor = _private_path(predecessor, root)
        require(predecessor.is_relative_to(root / '.job-runtime/review-campaigns') and predecessor != base, 'REVIEW_PREDECESSOR_INVALID')
        prior_config = load(predecessor / 'config.json'); prior_state = load(predecessor / 'state.json')
        require(prior_state['status'] == 'stopped_manual' and not prior_state.get('active_attempt')
                and prior_config['expires_at'] > at.timestamp() + 100
                and (prior_config['max_calls'], prior_config['max_model_seconds'], prior_config['max_tokens']) == (6, 1800, 400000), 'REVIEW_PREDECESSOR_NOT_STOPPED')
        expires = prior_config['expires_at']; usage = {key: prior_state[key] for key in usage}
        require(all(type(value) in (int, float) and value >= 0 for value in usage.values()), 'REVIEW_PREDECESSOR_USAGE_INVALID')
        lineage = {'predecessor': str(predecessor.relative_to(root)), 'config_sha256': fingerprint(predecessor / 'config.json'),
            'state_sha256': fingerprint(predecessor / 'state.json'), 'inherited_usage': usage,
            'scope': 'replacement_runtime_revalidation_not_new_study_progress'}
    config = {'schema_version': 1, 'version': VERSION, 'created_at': at.isoformat(), 'expires_at': expires, 'lineage': lineage,
        'label': 'com.local.trading-agent.review-campaign.' + name, 'pins': pins(root), 'profile_sha256': digest(profile(root)),
        'controller_python': str(root / '.research-sources/.venv/bin/python'),
        'slice_seconds': 360, 'max_calls': 6, 'max_model_seconds': 1800, 'max_tokens': 400000, 'jobs': [
            {'id': 'review.%02d' % index, 'enabled': True, 'replay_safe': False,
             'schedule': {'kind': 'once', 'at': (at + timedelta(seconds=90 + 1800 * index)).isoformat(), 'grace_seconds': 90}} for index in range(12)
            if (at + timedelta(seconds=90 + 1800 * index)).timestamp() < expires]}
    atomic(base / 'config.json', config)
    atomic(base / 'state.json', {'status': 'active', **usage, 'no_progress': 0,
        'same_failure': 0, 'last_failure': None, 'active_attempt': None, 'work': {}, 'seen_outputs': [], 'last_tick': at.timestamp()})
    return base


def enqueue(root, base, ref):
    value, _, _ = packet(ref); identifier = work_key(value)
    destination = base / 'queue' / (identifier + '.json')
    require(not destination.is_symlink(), 'REVIEW_QUEUE_UNSAFE')
    if destination.exists(): require(load(destination) == ref, 'REVIEW_QUEUE_CONFLICT')
    else: atomic(destination, ref)
    return identifier


def install(root, base):
    config = load(base / 'config.json')
    interpreter = Path(config['controller_python'])
    require(interpreter.is_file() and interpreter.is_relative_to(root), 'REVIEW_CONTROLLER_PYTHON_UNAVAILABLE')
    value = {'Label': config['label'], 'ProgramArguments': [str(interpreter), '-B', '-m', 'shared.job_runtime.review_campaign', 'tick', '--workspace', str(root), '--state', str(base)],
        'WorkingDirectory': str(root), 'EnvironmentVariables': {'PYTHONPATH': str(root), 'PYTHONDONTWRITEBYTECODE': '1', 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin',
            'HOME': str(Path.home()), 'TMPDIR': str(root / '.job-runtime/tmp')},
        'StartInterval': 30, 'RunAtLoad': False, 'ProcessType': 'Background', 'Umask': 0o077, 'ExitTimeOut': 5,
        'StandardOutPath': str(base / 'launchd.stdout.log'), 'StandardErrorPath': str(base / 'launchd.stderr.log')}
    path = base / 'campaign.plist'; path.write_bytes(plistlib.dumps(value)); path.chmod(0o600)
    result = subprocess.run(['/bin/launchctl', 'bootstrap', 'gui/%d' % os.getuid(), str(path)], capture_output=True, timeout=15)
    require(result.returncode == 0, 'REVIEW_CAMPAIGN_BOOTSTRAP_FAILED')
    return {'label': config['label'], 'first_due': config['jobs'][0]['schedule']['at'], 'expires_at': datetime.fromtimestamp(config['expires_at'], UTC).isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('command', choices=['create', 'enqueue', 'install', 'tick', 'status', 'stop'])
    parser.add_argument('--workspace', default=str(ROOT)); parser.add_argument('--state'); parser.add_argument('--name'); parser.add_argument('--packet-ref'); parser.add_argument('--predecessor-state')
    args = parser.parse_args(); root = Path(args.workspace).resolve(strict=True)
    if args.command == 'create': print(json.dumps({'state': str(create(root, args.name, args.predecessor_state))})); return
    base = _private_path(args.state, root)
    if args.command == 'enqueue': print(json.dumps({'work_key': enqueue(root, base, json.loads(args.packet_ref))}))
    elif args.command == 'install': print(json.dumps(install(root, base)))
    elif args.command == 'tick': print(json.dumps(tick(root, base)))
    elif args.command == 'stop': (base / 'stop-requested').touch(mode=0o600); print(json.dumps({'stop_requested': True}))
    else: print(json.dumps(load(base / 'state.json'), indent=2))


if __name__ == '__main__': main()
