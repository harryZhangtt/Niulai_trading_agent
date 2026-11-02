#!/usr/bin/env python3
"""One isolated future-slot UI probe; no production edits, auth copy or email."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import sqlite3
import stat
import subprocess
import threading
from zoneinfo import ZoneInfo

from shared.job_runtime.engine import Engine
from shared.job_runtime.service import atomic
from ui.portable.runtime_verification import run as harness

ROOT = Path(__file__).resolve().parents[3]
PRIVATE = ROOT / '.job-runtime/acceptance/harry-ui-persistence-20261102'
PUBLIC = ROOT / 'ui/runtime/harry-ui-persistence-20261102'
BUNDLE = Path.home() / '.agents/skills/harry-ui-skill-set'
CONFIG = ROOT / '.job-runtime/config/runtime.json'
PROTOCOL = 'ui/portable/runtime_verification/protocol-v3.json'
PROTOCOL_NAME = 'candidate-v3'
PREFIX = 'com.local.trading-agent.ui-persistence-20261102-'
RETRY = {'max_attempts': 1, 'backoff_seconds': 30, 'max_backoff_seconds': 30}
TERMINAL = {'passed', 'failed', 'unverified'}


class ScheduledError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ScheduledError(code)


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sha(path):
    with Path(path).open('rb') as stream:
        result = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def read(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 64 * 1024 * 1024,
            'UI_SCHEDULE_FILE_INVALID')
    return json.loads(path.read_text())


def private(path, create=False):
    path = Path(os.path.abspath(path))
    require(path.is_relative_to(PRIVATE) and '..' not in path.parts
            and path.resolve().is_relative_to(PRIVATE.resolve()), 'UI_SCHEDULE_PATH_REJECTED')
    for parent in [path, *path.parents]:
        if parent == ROOT:
            break
        require(not parent.is_symlink(), 'UI_SCHEDULE_SYMLINK_REJECTED')
    if create:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        for parent in [path, *path.parents]:
            if parent == ROOT:
                break
            parent.chmod(0o700)
    return path


def fingerprint():
    names = ['ui/portable/runtime_verification/' + name for name in ('run.py', 'protocol.json', 'protocol-v2.json', 'protocol-v3.json', 'scheduled.py')]
    names += ['shared/job_runtime/' + name for name in ('engine.py', 'service.py', 'config.py')]
    names += ['AGENTS.md', 'ui/AGENTS.md', 'ui/ROUTING.md', 'mentor/AGENTS.md', 'mentor/ROUTING.md']
    names += ['ui/portable/templates/' + name for name in ('session.py', 'activate.py', 'entrypoint.md', 'resolve.py')]
    source = {name: sha(ROOT / name) for name in names}
    manifest = read(BUNDLE / 'manifest.json')
    installed = {}
    for name, metadata in manifest['files'].items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'UI_BUNDLE_FILE_REJECTED')
        target = BUNDLE / relative
        require(target.resolve().is_relative_to(BUNDLE.resolve()) and not target.is_symlink(), 'UI_BUNDLE_FILE_REJECTED')
        actual = sha(target)
        require(actual == metadata['sha256'], 'UI_BUNDLE_FILE_CHANGED')
        installed[name] = actual
    profile = read(CONFIG)['model_profiles']['default']
    return {'source_files': source, 'source_sha256': digest(source),
            'global_manifest_sha256': sha(BUNDLE / 'manifest.json'),
            'global_payload_sha256': digest(installed), 'global_entrypoint_sha256': sha(BUNDLE / 'SKILL.md'),
            'profile_sha256': digest(profile), 'cli_sha256': sha(profile['codex_bin'])}


def environment():
    """Read-only prerequisite check; never bootstrap or read authentication."""
    domain = 'gui/' + str(os.getuid())
    result = subprocess.run(['/bin/launchctl', 'print', domain], capture_output=True, timeout=10)
    config = read(CONFIG)
    return {'checked_at': now().isoformat(), 'gui_domain_accessible': result.returncode == 0,
            'runtime_python_available': Path(config['python_bin']).is_file(),
            'launchctl_available': Path('/bin/launchctl').is_file()}


def stage(name, delay_seconds=90, variant='fresh-v1'):
    """Prepare only. Parent calls this after candidate checks; never register."""
    require(isinstance(name, str) and re.fullmatch('[a-z0-9][a-z0-9-]{0,29}', name), 'UI_SCHEDULE_NAME_INVALID')
    require(type(delay_seconds) is int and 60 <= delay_seconds <= 3600, 'UI_SCHEDULE_DELAY_INVALID')
    require(variant in (None, 'fresh-v1'), 'UI_SCHEDULE_VARIANT_INVALID')
    prerequisite = environment()
    require(prerequisite['gui_domain_accessible'] and prerequisite['runtime_python_available'], 'UI_SCHEDULER_UNAVAILABLE')
    candidate = fingerprint()
    created = now()
    due = created + timedelta(seconds=delay_seconds)
    base = private(PRIVATE / ('scheduler-' + name))
    require(not base.exists(), 'UI_SCHEDULE_ALREADY_EXISTS')
    private(base, create=True)
    record = {'schema_version': 1, 'change_id': 'harry-ui-persistence-20261102-' + name,
              'created_at': created.isoformat(), 'expires_at': (due + timedelta(seconds=1920)).isoformat(),
              'label': PREFIX + name, 'candidate': candidate, 'variant': variant, 'protocol': PROTOCOL_NAME,
              'criteria': {'max_start_lateness_seconds': 60, 'completion_timeout_seconds': 1800,
                           'required_path': 'future launchd tick -> durable once slot -> real app-server multi-turn UI persistence probe'},
              'jobs': [{'id': 'ui.harry-persistence.20261102.' + name, 'enabled': True, 'replay_safe': False,
                        'schedule': {'kind': 'once', 'at': due.isoformat(), 'grace_seconds': 120}}],
              'retry': RETRY, 'execution_status': 'pending', 'email_status': 'pending', 'attempts': [],
              'environment_preflight': prerequisite}
    path = base / 'record.json'
    atomic(path, record)
    config = read(CONFIG)
    env = {'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1', 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin',
           'HOME': str(Path.home()), 'TMPDIR': str(private(base / 'tmp', create=True))}
    for key in ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY'):
        if os.environ.get(key):
            env[key] = os.environ[key]
    spec = {'Label': record['label'], 'ProgramArguments': [config['python_bin'], '-B', '-m',
            'ui.portable.runtime_verification.scheduled', 'tick', '--record', str(path)],
            'WorkingDirectory': str(ROOT), 'EnvironmentVariables': env, 'StartInterval': 10,
            'RunAtLoad': False, 'ProcessType': 'Background', 'Umask': 0o077, 'ExitTimeOut': 15,
            'StandardOutPath': str(base / 'stdout.log'), 'StandardErrorPath': str(base / 'stderr.log')}
    plist = base / 'once.plist'
    plist.write_bytes(plistlib.dumps(spec))
    plist.chmod(0o600)
    return {'record': str(path), 'plist': str(plist), 'label': record['label'], 'due': due.isoformat(), 'registered': False}


def production_busy(duration, at):
    """Read-only admission: current primary claims and imminent daily/once work.

    Follow review_campaign.production_priority: an idle interval allocation
    reserves no credential capacity. The harness still owns runtime.lock.
    """
    config = read(CONFIG)
    jobs = [job for relative in config['allocation_files'] for job in read(ROOT / relative)['jobs']]
    enabled = {job['id'] for job in jobs if job['enabled']}
    dbpath = ROOT / '.job-runtime/engine/schedule.sqlite'
    if dbpath.exists():
        with sqlite3.connect('file:' + str(dbpath) + '?mode=ro', uri=True) as db:
            if any(status == 'running' or job in enabled for job, status in db.execute(
                    "SELECT job_id,status FROM slots WHERE status IN ('running','unknown','ready','retry_wait')")):
                return True
    for job in jobs:
        if not job['enabled']:
            continue
        schedule = job['schedule']
        if schedule['kind'] == 'once':
            due = datetime.fromisoformat(schedule['at'].replace('Z', '+00:00'))
            if -schedule['grace_seconds'] <= (due - at).total_seconds() <= duration + 120:
                return True
        if schedule['kind'] == 'daily':
            local = at.astimezone(ZoneInfo(schedule['timezone']))
            for days in (0, 1):
                for clock in schedule['times']:
                    hour, minute = map(int, clock.split(':'))
                    due = (local + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if 0 <= (due - local).total_seconds() <= duration + 120:
                        return True
    return False


def receipt_scope(cwd, thread_id):
    require(isinstance(thread_id, str) and bool(thread_id), 'UI_RECEIPT_NATIVE_ID_MISSING')
    thread_key = hashlib.sha256(('harry-ui-thread-v1:' + thread_id).encode()).hexdigest()
    return {'record_ref': '.ui-skill-runtime/harry-ui-sessions/' + thread_key + '.json',
            'native_thread_key': thread_key, 'project_key': hashlib.sha256(str(cwd).encode()).hexdigest()}


def receipt_bytes(path):
    """Finite no-follow read of one observer snapshot or final synthetic receipt."""
    require(path.is_absolute() and path.resolve() == path, 'UI_RECEIPT_PATH_UNSAFE')
    for directory in (path.parent, path.parent.parent):
        info = directory.stat()
        require(directory.is_dir() and info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o022,
                'UI_RECEIPT_DIRECTORY_UNSAFE')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                and not stat.S_IMODE(info.st_mode) & 0o077, 'UI_RECEIPT_FILE_UNSAFE')
        raw = stream.read(8193)
    require(0 < len(raw) <= 8192, 'UI_RECEIPT_SIZE_INVALID')
    return raw


def validate_receipt(raw, scope, expected, manifest_sha256):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'UI_RECEIPT_DUPLICATE_FIELD')
            value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as error:
        if isinstance(error, ScheduledError):
            raise
        raise ScheduledError('UI_RECEIPT_JSON_INVALID') from None
    fields = {'schema_version', 'thread_key', 'project_key', 'state', 'bundle_fingerprint', 'created_at', 'updated_at'}
    require(isinstance(value, dict) and set(value) == fields and type(value['schema_version']) is int
            and value['schema_version'] == 1 and value['thread_key'] == scope['native_thread_key']
            and value['project_key'] == scope['project_key'] and value['state'] == expected
            and value['bundle_fingerprint'] == manifest_sha256, 'UI_RECEIPT_SCOPE_OR_STATE_INVALID')
    try:
        timestamps_valid = all(isinstance(value[key], str) and len(value[key]) <= 64
                               and datetime.fromisoformat(value[key]).tzinfo is not None for key in ('created_at', 'updated_at'))
    except (ValueError, TypeError):
        timestamps_valid = False
    require(timestamps_valid, 'UI_RECEIPT_TIMESTAMP_INVALID')
    return hashlib.sha256(raw).hexdigest()


def durable_postconditions(protocol, cases, segments, public, record, probe_record, main_thread, fresh_thread):
    """Replay helper evidence and inspect native-scoped observer snapshot bytes."""
    require(protocol.get('durable_receipt_postconditions') is True
            and protocol.get('fresh_thread_same_project') is True, 'UI_DURABLE_PROTOCOL_REQUIRED')
    cwd = public / 'fixture'
    manifest = record['candidate']['global_manifest_sha256']
    snapshots, proof = {}, {}
    for frozen, case in zip(protocol['cases'], cases):
        if 'turn_id' not in case:
            continue
        replay = harness.session_trace_postcondition(frozen, segments[case['turn_id']])
        require(replay['passed'] is True and case.get('session_trace_postcondition') == replay,
                'UI_DURABLE_RAW_HELPER_EVIDENCE_INVALID')
        if frozen.get('session_check') == 'disabled_optional':
            require(type(replay.get('disabled_receipt_consulted')) is bool, 'UI_DISABLED_CONSULTATION_DIAGNOSTIC_MISSING')
            require(case.get('disabled_receipt_consulted') is replay['disabled_receipt_consulted'],
                    'UI_DISABLED_CONSULTATION_DIAGNOSTIC_MISMATCH')
        expected = frozen['receipt_expected']
        thread = fresh_thread if frozen.get('operation') == 'fresh_thread' else main_thread
        scope = receipt_scope(cwd, thread)
        reported = case.get('receipt_postcondition')
        require(isinstance(reported, dict) and reported.get('passed') is True
                and reported.get('expected_state') == expected
                and reported.get('observed_state') == expected
                and all(reported.get(key) == value for key, value in scope.items()), 'UI_DURABLE_RECEIPT_PROOF_MISSING')
        if expected == 'absent':
            path = cwd / scope['record_ref']
            require(path.resolve() == path and not path.exists() and not path.is_symlink()
                    and 'snapshot_ref' not in reported and 'content_sha256' not in reported,
                    'UI_FRESH_THREAD_RECEIPT_NOT_ABSENT')
            proof[case['id']] = {'expected_state': expected, 'native_thread_key': scope['native_thread_key']}
            continue
        snapshot = private(PRIVATE / probe_record / 'state-snapshots' / (case['id'] + '.json'))
        require(reported.get('snapshot_ref') == str(snapshot.relative_to(ROOT))
                and reported.get('owner_mode_verified') is True, 'UI_DURABLE_SNAPSHOT_REF_INVALID')
        raw = receipt_bytes(snapshot)
        actual_sha = validate_receipt(raw, scope, expected, manifest)
        require(reported.get('content_sha256') == actual_sha, 'UI_DURABLE_SNAPSHOT_DIGEST_MISMATCH')
        if frozen.get('attach_skill'):
            identity_path = cwd / 'identity.json'
            require(identity_path.stat().st_size <= 8192, 'UI_DURABLE_NATIVE_IDENTITY_INVALID')
            identity = read(identity_path)
            require(reported.get('native_identity_verified') is True and isinstance(identity, dict)
                    and set(identity) <= {'CODEX_THREAD_ID', 'CODEX_SESSION_ID'}
                    and identity.get('CODEX_THREAD_ID') == thread, 'UI_DURABLE_NATIVE_IDENTITY_INVALID')
        snapshots[case['id']] = raw
        proof[case['id']] = {'expected_state': expected, 'native_thread_key': scope['native_thread_key'],
                             'snapshot_sha256': actual_sha, 'session_trace_verified': True}
        if frozen.get('session_check') == 'disabled_optional':
            proof[case['id']]['disabled_receipt_consulted'] = replay['disabled_receipt_consulted']
    indexed = {case['id']: case for case in cases}
    require(snapshots.get('disable') and snapshots.get('disable') == snapshots.get('unnamed_disabled_after_compaction')
            and indexed['unnamed_disabled_after_compaction']['receipt_postcondition'].get('unchanged_from_disable') is True,
            'UI_DISABLED_TOMBSTONE_CHANGED')
    main_scope = receipt_scope(cwd, main_thread)
    final_main = receipt_bytes(cwd / main_scope['record_ref'])
    validate_receipt(final_main, main_scope, 'enabled', manifest)
    require(snapshots.get('reenable') == final_main
            and indexed['fresh_thread']['receipt_postcondition'].get('original_thread_receipt_unchanged') is True,
            'UI_FRESH_THREAD_CHANGED_ORIGINAL_RECEIPT')
    fresh_path = cwd / receipt_scope(cwd, fresh_thread)['record_ref']
    require(fresh_path.resolve() == fresh_path and not fresh_path.exists() and not fresh_path.is_symlink(),
            'UI_FRESH_THREAD_RECEIPT_NOT_ABSENT')
    return {'verified': True, 'same_project': str(cwd.relative_to(ROOT)), 'cases': proof,
            'disabled_tombstone_unchanged': True, 'original_thread_unchanged_after_fresh': True,
            'disabled_receipt_consulted': proof['unnamed_disabled_after_compaction'].get('disabled_receipt_consulted'),
            'final_original_sha256': hashlib.sha256(final_main).hexdigest(), 'fresh_thread_receipt_absent': True}


def postconditions(result, context, record, probe_record):
    """Reopen real RPC and artifacts; model final claims receive no credit."""
    public = PUBLIC / probe_record
    require(read(public / 'result.json') == result, 'UI_RESULT_READBACK_MISMATCH')
    protocol = read(ROOT / PROTOCOL)
    require(result.get('status') == 'pass' and result.get('stage') == 'scheduled'
            and result.get('protocol_file') == PROTOCOL
            and result.get('protocol_sha256') == record['candidate']['source_files'][PROTOCOL]
            and result.get('harness_sha256') == record['candidate']['source_files']['ui/portable/runtime_verification/run.py']
            and result.get('bundle_manifest_sha256') == record['candidate']['global_manifest_sha256']
            and result.get('bundle_unchanged_during_run') is True, 'UI_CONFORMANCE_NOT_PASSED')
    due = datetime.fromisoformat(context['scheduled_at'])
    started = datetime.fromisoformat(result['started_at'])
    ended = datetime.fromisoformat(result['ended_at'])
    require(0 <= (started - due).total_seconds() <= record['criteria']['max_start_lateness_seconds'], 'UI_START_LATE')
    require(0 <= (ended - started).total_seconds() <= record['criteria']['completion_timeout_seconds'], 'UI_COMPLETION_LATE')
    cases = result['cases']
    require([case['id'] for case in cases] == [case['id'] for case in protocol['cases']]
            and all(case['passed'] is True for case in cases), 'UI_CASE_COVERAGE_INCOMPLETE')
    traces = []
    native_turns = {}
    native_threads = []
    native_resumes = []
    compactions = []
    segments = {}
    for path in sorted((PRIVATE / probe_record).glob('server-*/rpc.jsonl')):
        require(not path.is_symlink() and path.stat().st_size <= 64 * 1024 * 1024, 'UI_TRACE_INVALID')
        entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        traces += entries
        for index, entry in enumerate(entries):
            request = entry['message']
            if entry['direction'] == 'client' and request.get('method') == 'thread/compact/start':
                end = next((i for i in range(index + 1, len(entries)) if entries[i]['direction'] == 'client'
                            and entries[i]['message'].get('method') == 'turn/start'), len(entries))
                complete = any(item['direction'] == 'server' and (item['message'].get('method') == 'thread/compacted'
                               or (item['message'].get('method') == 'item/completed'
                                   and item['message'].get('params', {}).get('item', {}).get('type') in ('contextCompaction', 'compaction')))
                               for item in entries[index + 1:end])
                compactions.append({'thread_id': request.get('params', {}).get('threadId'), 'completed': complete})
            if entry['direction'] != 'client' or request.get('method') not in ('turn/start', 'thread/start', 'thread/resume'):
                continue
            responses = [item['message'] for item in entries[index + 1:] if item['direction'] == 'server'
                         and item['message'].get('id') == request.get('id') and 'method' not in item['message']]
            require(len(responses) == 1 and 'error' not in responses[0], 'UI_NATIVE_TURN_RESPONSE_INVALID')
            if request['method'] != 'turn/start':
                binding = {'thread_id': responses[0]['result']['thread']['id'], 'params': request['params'],
                           'at': entry['at'], 'server': path.parent.name}
                (native_threads if request['method'] == 'thread/start' else native_resumes).append(binding)
                continue
            identifier = responses[0]['result']['turn']['id']
            native_turns[identifier] = request['params']
            end = next((i for i in range(index + 1, len(entries)) if entries[i]['direction'] == 'server'
                        and entries[i]['message'].get('method') == 'turn/completed'
                        and entries[i]['message'].get('params', {}).get('turn', {}).get('id') == identifier), None)
            require(end is not None, 'UI_NATIVE_TURN_COMPLETION_MISSING')
            segments[identifier] = [item['message'] for item in entries[index + 1:end + 1] if item['direction'] == 'server']
    completed = {entry['message'].get('params', {}).get('turn', {}).get('id'):
                 entry['message'].get('params', {}).get('turn', {}).get('status')
                 for entry in traces if entry['direction'] == 'server' and entry['message'].get('method') == 'turn/completed'}
    turn_ids = [case['turn_id'] for case in cases if 'turn_id' in case]
    require(len(set(turn_ids)) == result['model_turns'] == len(turn_ids) > 0
            and all(completed.get(identifier) == 'completed' for identifier in turn_ids), 'UI_NATIVE_TURN_COMPLETION_MISSING')
    require(result.get('thread_id') and result.get('fresh_thread_id') != result['thread_id'], 'UI_THREAD_BINDING_INVALID')
    require([entry['thread_id'] for entry in native_threads] == [result['thread_id'], result['fresh_thread_id']]
            and len(native_resumes) == 1 and native_resumes[0]['thread_id'] == result['thread_id']
            and native_resumes[0]['params']['threadId'] == result['thread_id']
            and native_resumes[0]['server'] != native_threads[0]['server'], 'UI_NATIVE_RESUME_BINDING_INVALID')
    fixture_cwd = str(public / 'fixture')
    require(all(entry['params'].get('cwd') == fixture_cwd
                and entry['params'].get('config', {}).get('project_doc_max_bytes') == 0 for entry in native_threads)
            and native_resumes[0]['params'].get('cwd') == fixture_cwd, 'UI_SAME_PROJECT_THREAD_BINDING_INVALID')
    require(len(compactions) == sum(case.get('operation') == 'compact' for case in protocol['cases'])
            and all(item == {'thread_id': result['thread_id'], 'completed': True} for item in compactions), 'UI_NATIVE_COMPACTION_MISSING')
    starts = [entry['at'] for entry in native_threads]
    require(starts and 0 <= (datetime.fromisoformat(starts[0]) - due).total_seconds() <= record['criteria']['max_start_lateness_seconds'],
            'UI_NATIVE_START_LATE')
    loaded = set()
    for frozen, case in zip(protocol['cases'], cases):
        if frozen.get('operation') in ('compact', 'fresh_thread'):
            loaded.clear()
        if 'turn_id' not in case:
            continue
        expected = dict(frozen)
        if record['variant']:
            for old, new in protocol['variant_substitutions'][record['variant']].items():
                expected = {key: value.replace(old, new) if isinstance(value, str) else value for key, value in expected.items()}
        request = native_turns.get(case['turn_id'], {})
        inputs = request.get('input', [])
        expected_inputs = [{'type': 'text', 'text': expected['prompt']}]
        if expected.get('attach_skill'):
            expected_inputs.append({'type': 'skill', 'name': 'harry-ui-skill-set', 'path': str(BUNDLE / 'SKILL.md')})
        require(inputs == expected_inputs and request.get('threadId') == result['fresh_thread_id' if frozen.get('operation') == 'fresh_thread' else 'thread_id']
                and request.get('model') == protocol['model'] and request.get('effort') == protocol['effort'], 'UI_NATIVE_TURN_INPUT_MISMATCH')
        replay = harness.grade(expected, segments[case['turn_id']], case['artifact_before_sha256'], case['artifact_after_sha256'], loaded)
        require(replay['passed'] is True and case.get('routing_conformance_passed') is True
                and all(case.get(key) == value for key, value in replay.items()), 'UI_RAW_TOOL_EVIDENCE_MISMATCH')
    durable = durable_postconditions(protocol, cases, segments, public, record, probe_record,
                                     result['thread_id'], result['fresh_thread_id'])
    require(result.get('processes') and all(process.get('cleanup_verified') is True for process in result['processes']),
            'UI_PROCESS_CLEANUP_UNVERIFIED')
    for process in result['processes']:
        observed = subprocess.run(['/bin/ps', '-g', str(process['pid']), '-o', 'pid='], capture_output=True, timeout=5)
        require(observed.returncode in (0, 1) and not observed.stdout.strip(), 'UI_PROCESS_REMAINS')
    for case in cases:
        require(read(public / (case['id'] + '.json')) == case, 'UI_CASE_READBACK_MISMATCH')
    final_artifacts = {}
    fixture = 'fixture'
    for frozen, case in zip(protocol['cases'], cases):
        if frozen.get('operation') == 'fresh_thread' and not protocol.get('fresh_thread_same_project'):
            fixture = 'fresh-fixture'
        if 'artifact' not in frozen:
            continue
        artifact = frozen['artifact']
        if record['variant']:
            for old, new in protocol['variant_substitutions'][record['variant']].items():
                artifact = artifact.replace(old, new)
        final_artifacts[(fixture, artifact)] = case['artifact_after_sha256']
    require(all(sha(public / fixture / artifact) == expected for (fixture, artifact), expected in final_artifacts.items()),
            'UI_FINAL_ARTIFACT_MISMATCH')
    return {'verified': True, 'thread_id': result['thread_id'], 'fresh_thread_id': result['fresh_thread_id'],
            'turn_ids': turn_ids, 'started_at': starts[0], 'harness_started_at': result['started_at'], 'ended_at': result['ended_at'],
            'requested_model': result['requested_model'], 'observed_model': result.get('observed_model'),
            'report_path': str((public / 'result.json').relative_to(ROOT)), 'report_sha256': sha(public / 'result.json'),
            'processes': result['processes'],
            'durable_state': durable,
            'trace_files': {str(path.relative_to(ROOT)): sha(path) for path in sorted((PRIVATE / probe_record).glob('server-*/rpc.jsonl'))},
            'start_lateness_seconds': (datetime.fromisoformat(starts[0]) - due).total_seconds(), 'cases': len(cases), 'process_cleanup_verified': True}


def cleanup(record, path):
    record['cleanup_requested_at'] = now().isoformat()
    atomic(path, record)
    subprocess.run(['/bin/launchctl', 'bootout', 'gui/' + str(os.getuid()) + '/' + record['label']], capture_output=True, timeout=10)


def tick(path, cancel_event=None):
    path = private(path)
    require(path.name == 'record.json' and re.fullmatch('scheduler-[a-z0-9][a-z0-9-]{0,29}', path.parent.name), 'UI_RECORD_INVALID')
    fd = os.open(path.parent / 'tick.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    cancel = cancel_event or threading.Event()
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'busy'}
        record = read(path)
        require(record['label'] == PREFIX + path.parent.name.removeprefix('scheduler-'), 'UI_LABEL_INVALID')
        require(record['retry'] == RETRY and len(record['jobs']) == 1
                and record['jobs'][0]['replay_safe'] is False
                and record['jobs'][0]['schedule']['kind'] == 'once'
                and record['protocol'] == PROTOCOL_NAME, 'UI_ONCE_POLICY_INVALID')
        if record['execution_status'] in TERMINAL:
            cleanup(record, path)
            return {'status': record['execution_status']}
        if now() >= datetime.fromisoformat(record['expires_at']):
            record.update(execution_status='unverified', failure_code='UI_SCHEDULE_EXPIRED')
            cleanup(record, path)
            return {'status': 'unverified'}
        if production_busy(record['criteria']['completion_timeout_seconds'], now()):
            record['last_yield_at'] = now().isoformat()
            atomic(path, record)
            return {'status': 'yielded_primary'}

        def dispatch(job, context):
            attempt = {'context': context, 'job_id': job['id'], 'started_at': now().isoformat()}
            record['attempts'].append(attempt)
            atomic(path, record)
            submitted = False
            timer = None
            try:
                require(fingerprint() == record['candidate'], 'UI_SCHEDULE_CANDIDATE_CHANGED')
                require(not cancel.is_set(), 'UI_SCHEDULE_CANCELLED')
                probe_record = 'scheduled-' + context['attempt_id']
                attempt['probe_record'] = probe_record
                atomic(path, record)
                timer = threading.Timer(record['criteria']['completion_timeout_seconds'], cancel.set)
                timer.daemon = True
                timer.start()
                submitted = True
                result = harness.run(argparse.Namespace(record=probe_record, stage='scheduled', protocol=PROTOCOL_NAME,
                                                        variant=record['variant'], preflight=False, resume_record=None),
                                     cancel_event=cancel)
                attempt['harness_status'] = result.get('status')
                if result.get('status') == 'conformance_failed':
                    attempt.update(status='failed', failure_code='UI_CONFORMANCE_FAILED')
                    atomic(path, record)
                    return {'status': 'failed', 'code': 'UI_CONFORMANCE_FAILED', 'receipt': attempt}
                if result.get('status') != 'pass':
                    attempt.update(status='unverified', failure_code='UI_NATIVE_RUN_INCOMPLETE')
                    atomic(path, record)
                    return {'status': 'unknown', 'code': 'UI_NATIVE_RUN_INCOMPLETE', 'receipt': attempt}
                checked = postconditions(result, context, record, probe_record)
                require(fingerprint() == record['candidate'], 'UI_SCHEDULE_CANDIDATE_CHANGED')
                attempt.update(status='passed', postcondition=checked)
                atomic(path, record)
                return {'status': 'succeeded', 'code': 'UI_PERSISTENCE_POSTCONDITIONS_VERIFIED', 'receipt': attempt}
            except Exception as error:
                code = str(error) if isinstance(error, ScheduledError) else 'UI_SCHEDULE_ATTEMPT_UNVERIFIED'
                unknown = submitted and not isinstance(error, ScheduledError)
                attempt.update(status='unverified' if unknown else 'failed', failure_code=code)
                atomic(path, record)
                return {'status': 'unknown' if unknown else 'failed', 'code': code, 'receipt': attempt}
            finally:
                if timer is not None:
                    timer.cancel()

        engine = Engine(path.parent / 'engine', record['jobs'], record['retry'], dispatch, workspace_root=ROOT, max_workers=1)
        summary = engine.tick(now())
        observed = engine.status()
        latest = observed['jobs'][0]['latest']
        record['engine_status'] = observed
        record['last_tick_at'] = now().isoformat()
        if latest and latest['status'] in ('succeeded', 'failed', 'unknown', 'running', 'missed'):
            record['execution_status'] = {'succeeded': 'passed', 'failed': 'failed'}.get(latest['status'], 'unverified')
            if latest['status'] == 'running':
                record['failure_code'] = 'UI_ABANDONED_ATTEMPT_REQUIRES_RECONCILIATION'
        atomic(path, record)
        return {'status': record['execution_status'], 'dispatch': summary}
    except Exception as error:
        if 'record' in locals():
            record.update(execution_status='failed', failure_code=str(error) if isinstance(error, ScheduledError) else 'UI_SCHEDULE_CONTROLLER_FAILED')
            atomic(path, record)
            return {'status': 'failed', 'code': record['failure_code']}
        raise ScheduledError('UI_SCHEDULE_CONTROLLER_FAILED') from None
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('environment', 'stage', 'tick', 'status'))
    parser.add_argument('--name', default='scheduled-v3')
    parser.add_argument('--delay-seconds', type=int, default=90)
    parser.add_argument('--variant', choices=('fresh-v1', 'original'), default='fresh-v1')
    parser.add_argument('--record', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    cancel = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    if args.command == 'environment':
        value = environment()
    elif args.command == 'stage':
        value = stage(args.name, args.delay_seconds, None if args.variant == 'original' else args.variant)
    else:
        require(args.record is not None, 'UI_RECORD_REQUIRED')
        if args.command == 'tick':
            value = tick(args.record, cancel)
        else:
            path = private(args.record)
            record = read(path)
            value = {'execution_status': record['execution_status'], 'email_status': record['email_status'],
                     'label': record['label'], 'attempts': len(record['attempts']), 'engine_status': record.get('engine_status')}
    print(json.dumps(value))


if __name__ == '__main__':
    main()
