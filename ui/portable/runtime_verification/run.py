#!/usr/bin/env python3
"""Bounded real app-server multi-turn probe; no auth copies or global writes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'ui/runtime/harry-ui-persistence-20261102'
PRIVATE = ROOT / '.job-runtime/acceptance/harry-ui-persistence-20261102'
BUNDLE = Path.home() / '.agents/skills/harry-ui-skill-set'


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    path.chmod(0o600)


def terminate(process):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            continue
        if sig == signal.SIGTERM:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        break
    return process.poll() is not None


class RPC:
    def __init__(self, binary, home, private, index, cancel_event=None):
        self.cancel_event = cancel_event
        self.started_at = now()
        self.closed = False
        self.directory = private / ('server-' + str(index))
        self.directory.mkdir(mode=0o700)
        env_names = ('PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL',
                     'SSL_CERT_FILE', 'SSL_CERT_DIR', 'HTTPS_PROXY', 'HTTP_PROXY',
                     'ALL_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy', 'all_proxy', 'no_proxy')
        env = {k: os.environ[k] for k in env_names if k in os.environ}
        env.update(CODEX_HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
        for key, name in [('TMPDIR', 'tmp'), ('XDG_CACHE_HOME', 'cache'), ('CODEX_SQLITE_HOME', 'sqlite')]:
            p = self.directory / name
            p.mkdir(mode=0o700)
            env[key] = str(p)
        overrides = {'approval_policy': 'never', 'model_reasoning_effort': 'low',
                     'web_search': 'disabled', 'features.shell_tool': True,
                     'features.shell_snapshot': False, 'apps._default.enabled': False,
                     'mcp_servers': {}, 'cli_auth_credentials_store': 'file',
                     'log_dir': str(self.directory / 'logs'),
                     'sqlite_home': env['CODEX_SQLITE_HOME'], 'check_for_update_on_startup': False,
                     'features.multi_agent': False}
        command = [str(binary), 'app-server', '--listen', 'stdio://']
        for key, value in overrides.items():
            command += ['-c', key + '=' + json.dumps(value)]
        self.error = (self.directory / 'stderr.log').open('xb')
        self.log = (self.directory / 'rpc.jsonl').open('x')
        self.process = subprocess.Popen(command, cwd=ROOT, env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.error, start_new_session=True)
        self.buffer = b''
        self.messages = []
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.counter = 0
        try:
            self.request('initialize', {'clientInfo': {'name': 'harry-ui-runtime-probe', 'version': '1.0'},
                                       'capabilities': {'experimentalApi': True}})
            self.send({'method': 'initialized'})
        except BaseException:
            self.close()
            raise

    def record(self, direction, message):
        self.log.write(json.dumps({'at': now(), 'direction': direction, 'message': message}) + '\n')
        self.log.flush()

    def send(self, message):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RuntimeError('PROBE_CANCELLED_BEFORE_RPC_SEND')
        self.record('client', message)
        self.process.stdin.write((json.dumps(message) + '\n').encode())
        self.process.stdin.flush()

    def collect(self, seconds):
        if self.selector.select(min(seconds, 1)):
            data = os.read(self.process.stdout.fileno(), 1024 * 1024)
            if not data:
                raise RuntimeError('APP_SERVER_EXITED')
            self.buffer += data
            if len(self.buffer) > 16 * 1024 * 1024:
                raise RuntimeError('RPC_LINE_LIMIT')
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                if not line:
                    continue
                msg = json.loads(line)
                self.record('server', msg)
                self.messages.append(msg)
                if 'id' in msg and 'method' in msg:
                    # No approval, credential or external-effect requests are authorized.
                    self.send({'id': msg['id'], 'error': {'code': -32000, 'message': 'PROBE_REQUEST_NOT_AUTHORIZED'}})

    def wait(self, predicate, timeout):
        deadline = time.monotonic() + timeout
        while True:
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise RuntimeError('PROBE_CANCELLED')
            found = next((m for m in self.messages if predicate(m)), None)
            if found is not None:
                return found
            if time.monotonic() >= deadline:
                raise TimeoutError('APP_SERVER_WAIT_TIMEOUT')
            self.collect(deadline - time.monotonic())

    def request(self, method, params, timeout=25):
        self.counter += 1
        identifier = self.counter
        self.send({'id': identifier, 'method': method, 'params': params})
        response = self.wait(lambda m: m.get('id') == identifier and 'method' not in m, timeout)
        if 'error' in response:
            # Detailed provider error stays in private trace.
            raise RuntimeError('RPC_REJECTED_' + method.replace('/', '_'))
        return response['result']

    def close(self):
        if self.closed:
            return self.process.poll() is not None
        self.closed = True
        cleaned = terminate(self.process)
        self.selector.close()
        self.process.stdin.close()
        self.process.stdout.close()
        self.error.close()
        self.log.close()
        for p in self.directory.rglob('*'):
            if p.is_file():
                p.chmod(0o600)
        return cleaned


def commands(messages):
    found = []
    for msg in messages:
        if msg.get('method') != 'item/completed':
            continue
        item = msg.get('params', {}).get('item', {})
        if item.get('type') == 'commandExecution':
            found.append(item)
    return found


def command_text(item):
    value = item.get('command', '')
    return value if isinstance(value, str) else json.dumps(value)


def successful(item):
    return item.get('exitCode') == 0 and item.get('status') in ('completed', None)


def guide_returned(item, expert):
    if not successful(item):
        return False
    text = item.get('aggregatedOutput') or ''
    guide = BUNDLE / 'experts' / expert / 'GUIDE.md'
    if not guide.is_file():
        return False
    # Canonical workspace/global experts may share upstream text with this
    # bundle. Content equality alone must never count as bundle activity.
    if str(guide) not in command_text(item):
        return False
    # Match actual unique content returned to the model, not a path in a plan.
    lines = [line.strip() for line in guide.read_text().splitlines()
             if len(line.strip()) >= 65 and not line.startswith('description:')]
    return any(line in text for line in lines[:10])


def grade(case, messages, before, after, loaded):
    items = commands(messages)
    valid = [i for i in items if successful(i)]
    routes = [i for i in valid if 'resolve.py' in command_text(i)
              and 'harry-ui-skill-set' in command_text(i)
              and 'UI_ROUTE_OK' in (i.get('aggregatedOutput') or '')]
    activations = [i for i in valid if 'activate.py' in command_text(i)
                   and 'HARRY_UI_SESSION_ENABLED' in (i.get('aggregatedOutput') or '')]
    reads = []
    for expert in ('impeccable', 'ui-ux-pro-max', 'frontend-design', 'async-state-reliability'):
        if any(guide_returned(i, expert) for i in valid):
            reads.append(expert)
            loaded.add(expert)
    changed = after is not None and before != after
    expert = case.get('expert')
    selected = set()
    for item in routes:
        selected.update(re.findall(r'"skill"\s*:\s*"([a-z0-9-]+)"', item.get('aggregatedOutput') or ''))
    persistence_passed = bool(routes) and bool(selected & loaded) and changed
    if case.get('attach_skill'):
        persistence_passed = persistence_passed and bool(activations)
    else:
        persistence_passed = persistence_passed and not activations
    if case['expect'] == 'positive':
        passed = bool(routes) and expert in loaded and changed
        if case.get('attach_skill'):
            passed = passed and bool(activations)
        else:
            passed = passed and not activations
        if 'allowed_experts' in case:
            passed = persistence_passed and bool(set(case['allowed_experts']) & selected & loaded)
    else:
        passed = not routes and not activations and not reads and changed
    return {'id': case['id'], 'expect': case['expect'], 'passed': passed,
            'persistence_passed': persistence_passed if case['expect'] == 'positive' else None,
            'selected_experts': sorted(selected),
            'allowed_experts': case.get('allowed_experts', [expert] if expert else []),
            'preferred_expert_selected': expert in selected if expert else None,
            'preferred_guide_used': expert in (selected & loaded) if expert else None,
            'artifact_changed': changed, 'artifact_before_sha256': before,
            'artifact_after_sha256': after, 'successful_bundle_resolver_calls': len(routes),
            'successful_activation_calls': len(activations), 'guide_bodies_returned_this_turn': reads,
            'expected_guide_available': expert in loaded if expert else None,
            'command_count': len(items), 'failed_command_count': len(items)-len(valid),
            'commands': [{'id': i.get('id'), 'command': command_text(i), 'exit_code': i.get('exitCode')}
                         for i in items]}


def session_trace_postcondition(case, messages):
    """Actual helper command/status/order, independent of final announcements."""
    items = commands(messages)
    mode = case.get('session_check')
    restores, disables = [], []
    session_items = []
    for index, item in enumerate(items):
        command = command_text(item)
        if str(BUNDLE / 'scripts/session.py') not in command:
            continue
        session_items.append(index)
        if not successful(item):
            continue
        output = item.get('aggregatedOutput') or ''
        for action, found in [('restore', restores), ('disable', disables)]:
            match = re.search(r'session\.py[\"\']?\s+' + action + r'\b', command)
            if match:
                statuses = re.findall(r'"status"\s*:\s*"(HARRY_UI_SESSION_[A-Z]+)"', output)
                found.append({'command_index': index, 'command_position': match.start(),
                              'command_id': item.get('id'), 'statuses': statuses})
    expected = {'active': 'HARRY_UI_SESSION_ACTIVE', 'disabled': 'HARRY_UI_SESSION_DISABLED',
                'disabled_optional': 'HARRY_UI_SESSION_DISABLED',
                'disable': 'HARRY_UI_SESSION_DISABLED', 'inactive_optional': 'HARRY_UI_SESSION_INACTIVE'}
    if mode == 'none':
        passed = not session_items
    elif mode in ('active', 'disabled'):
        valid = [r for r in restores if expected[mode] in r['statuses']]
        passed = bool(valid)
        if mode == 'active':
            route_indices = [(i, command_text(item).find('resolve.py')) for i, item in enumerate(items)
                             if successful(item) and str(BUNDLE / 'scripts/resolve.py') in command_text(item)
                             and 'UI_ROUTE_OK' in (item.get('aggregatedOutput') or '')]
            passed = passed and bool(route_indices) and all(any(
                r['command_index'] < i or (r['command_index'] == i and r['command_position'] < position)
                for r in valid) for i, position in route_indices)
    elif mode == 'disable':
        passed = any(expected[mode] in r['statuses'] for r in disables)
    elif mode == 'disabled_optional':
        # Known off context may honor the user's stop without calling Harry.
        # If a helper is consulted, only an actual successful DISABLED restore
        # is valid. Failed, state-changing or wrong-status helper calls fail.
        passed = (not session_items or (len(restores) == len(session_items) and not disables and
                  all(r['statuses'] and set(r['statuses']) == {expected[mode]} for r in restores)))
    elif mode == 'inactive_optional':
        passed = all(r['statuses'] and set(r['statuses']) == {expected[mode]} for r in restores)
    else:
        passed = mode in (None, 'enable')
    consulted = (any(r['statuses'] and set(r['statuses']) == {'HARRY_UI_SESSION_DISABLED'} for r in restores)
                 if mode in ('disabled', 'disabled_optional') else None)
    return {'passed': passed, 'mode': mode, 'disabled_receipt_consulted': consulted,
            'session_command_count': len(session_items),
            'restore_commands': restores, 'disable_commands': disables}


def receipt_postcondition(cwd, thread_id, expected):
    """Read synthetic state directly; never trust a helper's status claim alone."""
    thread_key = hashlib.sha256(('harry-ui-thread-v1:' + thread_id).encode()).hexdigest()
    project_key = hashlib.sha256(str(cwd).encode()).hexdigest()
    path = cwd / '.ui-skill-runtime/harry-ui-sessions' / (thread_key + '.json')
    result = {'expected_state': expected, 'record_ref': str(path.relative_to(cwd)),
              'native_thread_key': thread_key, 'project_key': project_key, 'passed': False}
    raw = None
    try:
        if expected == 'absent':
            result['passed'] = not path.exists() and not path.is_symlink()
            result['observed_state'] = 'absent' if result['passed'] else 'unexpected_record'
            return result, None
        if path.resolve() != path or path.is_symlink():
            raise ValueError('UNSAFE_RECEIPT_PATH')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise ValueError('UNSAFE_RECEIPT_FILE')
            raw = stream.read(8193)
        if not 0 < len(raw) <= 8192:
            raise ValueError('RECEIPT_SIZE')
        def unique(pairs):
            output = {}
            for key, value in pairs:
                if key in output:
                    raise ValueError('DUPLICATE_RECEIPT_FIELD')
                output[key] = value
            return output
        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError('RECEIPT_NOT_OBJECT')
        expected_fields = {'schema_version', 'thread_key', 'project_key', 'state',
                           'bundle_fingerprint', 'created_at', 'updated_at'}
        valid = (set(value) == expected_fields and type(value.get('schema_version')) is int
                 and value['schema_version'] == 1 and value.get('thread_key') == thread_key
                 and value.get('project_key') == project_key and value.get('state') == expected
                 and value.get('bundle_fingerprint') == sha(BUNDLE / 'manifest.json'))
        valid = valid and all(isinstance(value.get(key), str) and
                              datetime.fromisoformat(value[key]).tzinfo is not None
                              for key in ('created_at', 'updated_at'))
        result.update(passed=valid, observed_state=value.get('state'),
                      content_sha256=hashlib.sha256(raw).hexdigest(), owner_mode_verified=True)
    except (OSError, ValueError, TypeError, KeyError):
        result['code'] = 'RECEIPT_MISSING_OR_INVALID'
    return result, raw


def fixture(path, independent=False):
    path.mkdir(parents=True)
    if independent:
        # A nested Git root plus project_doc_max_bytes=0 prevents this workspace's
        # own AGENTS from reinforcing a standalone installed-package probe.
        subprocess.run(['git', 'init', '--quiet', str(path)], cwd=ROOT,
                       check=True, capture_output=True, timeout=10)
        observed = subprocess.run(['git', '-C', str(path), 'rev-parse', '--show-toplevel'],
                                  check=True, capture_output=True, text=True, timeout=10)
        if Path(observed.stdout.strip()).resolve() != path.resolve():
            raise RuntimeError('FIXTURE_GIT_ROOT_NOT_INDEPENDENT')
    (path / 'brief.txt').write_text('Existing product tokens: background #f4f1e8; ink #20352b; accent #365f44; '
                                  'system sans-serif. Compact calm utilitarian UI. Use no external assets.\n')


def thread_start(rpc, cwd, model, protocol):
    # This only constrains effects; it never supplies persistence/routing advice.
    developer = ('This is a synthetic local artifact task. Implement requests within ' + str(cwd) + '. '
                 'Do not edit any outside file, install dependencies, access credentials or private '
                 'runtime data, inspect sibling probe runs, call external services, or delegate. '
                 'Reading existing project instructions and installed guidance is allowed. '
                 'Keep every command bounded; avoid starting a server. No network or browser effect is required.')
    return rpc.request('thread/start', {'cwd': str(cwd), 'model': model, 'sandbox': 'danger-full-access',
                                      'approvalPolicy': 'never', 'ephemeral': False,
                                      'config': {'project_doc_max_bytes': protocol.get('project_doc_max_bytes', 32768)},
                                      'developerInstructions': developer})


def run(args, *, cancel_event=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,79}', args.record):
        raise ValueError('RECORD_INVALID')
    protocol_file = {'baseline': 'protocol.json', 'candidate': 'protocol-v2.json',
                     'candidate-v3': 'protocol-v3.json',
                     'independent': 'protocol-independent-control.json',
                     'baseline-suffix': 'protocol-baseline-suffix.json'}[getattr(args, 'protocol', 'baseline')]
    protocol_path = SOURCE / protocol_file
    protocol = json.loads(protocol_path.read_text())
    profile = json.loads((ROOT / '.job-runtime/config/runtime.json').read_text())['model_profiles']['default']
    if profile['model'] != protocol['model'] or profile['effort'] != protocol['effort']:
        raise ValueError('PROFILE_MISMATCH_NO_FALLBACK')
    home = Path(profile['auth_home'])
    if home != ROOT / '.job-runtime/codex-home' or not (home / 'auth.json').is_file():
        raise ValueError('AUTH_HOME_UNAVAILABLE')
    public, private = EVIDENCE / args.record, PRIVATE / args.record
    public.mkdir(parents=True, exist_ok=False)
    private.mkdir(parents=True, exist_ok=False, mode=0o700)
    # Preserve exact loaded harness/protocol bytes for later audits after edits.
    for filename, source in [('harness-loaded-source.py', Path(__file__)),
                             ('protocol-frozen.json', protocol_path)]:
        with (public / filename).open('xb') as stream:
            stream.write(source.read_bytes())
    record = {'record': args.record, 'stage': args.stage, 'started_at': now(), 'model_turns': 0,
              'protocol_sha256': sha(protocol_path), 'protocol_file': str(protocol_path.relative_to(ROOT)),
              'harness_sha256': sha(Path(__file__)),
              'requested_model': profile['model'], 'effort': profile['effort'],
              'automatic_retry': False, 'fallback_used': False, 'automatic_hook_init_verified': False,
              'os_sandbox_claimed': False, 'raw_trace_directory': str(private.relative_to(ROOT)),
              'bundle_manifest_sha256': sha(BUNDLE / 'manifest.json'),
              'bundle_entrypoint_sha256': sha(BUNDLE / 'SKILL.md'),
              'cases': [], 'processes': [], 'variant': args.variant,
              'independent_project': protocol.get('independent_project', False),
              'project_doc_max_bytes': protocol.get('project_doc_max_bytes', 32768)}
    write_new(public / 'intent.json', record)
    fd = os.open(home / 'runtime.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    rpc = None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('MODEL_AUTH_CACHE_BUSY') from None
        rpc = RPC(profile['codex_bin'], home, private, 1, cancel_event)
        record['processes'].append({'pid': rpc.process.pid, 'server': 1, 'started_at': rpc.started_at})
        resume_record = getattr(args, 'resume_record', None)
        prior = None
        if resume_record:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,79}', resume_record):
                raise ValueError('RESUME_RECORD_INVALID')
            prior = json.loads((EVIDENCE / resume_record / 'result.json').read_text())
            cwd = EVIDENCE / resume_record / 'fixture'
            record['resumed_from_record'] = resume_record
        else:
            cwd = public / 'fixture'
            fixture(cwd, protocol.get('independent_project', False))
        discovered = rpc.request('skills/list', {'cwds': [str(cwd)], 'forceReload': True})
        found = [s for entry in discovered.get('data', []) for s in entry.get('skills', [])
                 if s.get('name') == 'harry-ui-skill-set' and s.get('path') == str(BUNDLE / 'SKILL.md')]
        record['skill_discovered_enabled'] = len(found) == 1 and found[0].get('enabled') is True
        if not record['skill_discovered_enabled']:
            raise RuntimeError('INSTALLED_SKILL_NOT_DISCOVERED')
        if args.preflight:
            record['preflight_only'] = True
            record['status'] = 'preflight_pass'
            return record
        if prior:
            start = rpc.request('thread/resume', {'threadId': prior['thread_id'], 'cwd': str(cwd),
                                'model': profile['model'], 'sandbox': 'danger-full-access',
                                'approvalPolicy': 'never'})
        else:
            start = thread_start(rpc, cwd, profile['model'], protocol)
        thread_id = start['thread']['id']
        record['thread_id'] = thread_id
        record['observed_model'] = start.get('model')
        if start['thread'].get('path'):
            history = Path(start['thread']['path'])
            if history.is_relative_to(ROOT / '.job-runtime'):
                record['thread_history_ref'] = str(history.relative_to(ROOT))
        loaded = set()
        cases = protocol['cases']
        for frozen in cases:
            case = dict(frozen)
            if args.variant:
                for old, new in protocol['variant_substitutions'][args.variant].items():
                    case = {k: v.replace(old, new) if isinstance(v, str) else v for k, v in case.items()}
            operation = case.get('operation')
            if operation == 'compact':
                offset = len(rpc.messages)
                rpc.request('thread/compact/start', {'threadId': thread_id})
                evidence = rpc.wait(lambda m: m in rpc.messages[offset:] and (
                    m.get('method') == 'thread/compacted' or
                    (m.get('method') == 'item/completed' and
                     m.get('params', {}).get('item', {}).get('type') in ('contextCompaction', 'compaction'))), 120)
                record['cases'].append({'id': case['id'], 'passed': True, 'event_method': evidence.get('method'),
                                        'item_type': evidence.get('params', {}).get('item', {}).get('type')})
                loaded.clear()
                write_new(public / (case['id'] + '.json'), record['cases'][-1])
                print(json.dumps({'case': case['id'], 'passed': True}), flush=True)
                continue
            if operation == 'restart_resume':
                record['processes'][-1]['cleanup_verified'] = rpc.close()
                record['processes'][-1]['exit_code'] = rpc.process.returncode
                rpc = RPC(profile['codex_bin'], home, private, 2, cancel_event)
                record['processes'].append({'pid': rpc.process.pid, 'server': 2, 'started_at': rpc.started_at})
                resumed = rpc.request('thread/resume', {'threadId': thread_id,
                    'cwd': str(cwd), 'model': profile['model'], 'sandbox': 'danger-full-access',
                    'approvalPolicy': 'never'})
                same = resumed['thread']['id'] == thread_id
                record['cases'].append({'id': case['id'], 'passed': same, 'same_thread_id': same})
                write_new(public / (case['id'] + '.json'), record['cases'][-1])
                print(json.dumps({'case': case['id'], 'passed': same}), flush=True)
                continue
            if operation == 'fresh_thread':
                if not protocol.get('fresh_thread_same_project'):
                    cwd = public / 'fresh-fixture'
                    fixture(cwd, protocol.get('independent_project', False))
                fresh = thread_start(rpc, cwd, profile['model'], protocol)
                thread_id = fresh['thread']['id']
                loaded.clear()
                record['fresh_thread_id'] = thread_id
            if record['model_turns'] >= protocol['max_model_turns']:
                raise RuntimeError('MODEL_TURN_BUDGET_EXHAUSTED')
            inputs = [{'type': 'text', 'text': case['prompt']}]
            if case.get('attach_skill'):
                inputs.append({'type': 'skill', 'name': 'harry-ui-skill-set', 'path': str(BUNDLE / 'SKILL.md')})
            elif '$harry-ui-skill-set' in case['prompt'] or 'resolve.py' in case['prompt']:
                raise RuntimeError('LATER_PROMPT_LEAKS_ROUTE')
            before = sha(cwd / case['artifact'])
            offset = len(rpc.messages)
            begin = time.monotonic()
            turn = rpc.request('turn/start', {'threadId': thread_id, 'input': inputs,
                                             'model': profile['model'], 'effort': profile['effort']},
                               timeout=min(25, protocol['turn_timeout_seconds']))
            record['model_turns'] += 1
            turn_id = turn['turn']['id']
            record['active_turn'] = {'case_id': case['id'], 'thread_id': thread_id,
                                     'turn_id': turn_id, 'started_at': now()}
            complete = rpc.wait(lambda m: m.get('method') == 'turn/completed' and
                                m.get('params', {}).get('turn', {}).get('id') == turn_id,
                                max(0, protocol['turn_timeout_seconds'] - (time.monotonic() - begin)))
            result = grade(case, rpc.messages[offset:], before, sha(cwd / case['artifact']), loaded)
            if protocol.get('durable_receipt_postconditions'):
                trace_check = session_trace_postcondition(case, rpc.messages[offset:])
                receipt_check, raw_receipt = receipt_postcondition(cwd, thread_id, case['receipt_expected'])
                if case.get('attach_skill'):
                    try:
                        identity = json.loads((cwd / 'identity.json').read_text())
                        identity_check = (isinstance(identity, dict) and
                                          set(identity) <= {'CODEX_THREAD_ID', 'CODEX_SESSION_ID'}
                                          and identity.get('CODEX_THREAD_ID') == thread_id)
                    except (OSError, ValueError, TypeError):
                        identity_check = False
                    receipt_check['native_identity_verified'] = identity_check
                    receipt_check['passed'] = receipt_check['passed'] and identity_check
                if raw_receipt is not None:
                    snapshots = private / 'state-snapshots'
                    snapshots.mkdir(mode=0o700, exist_ok=True)
                    snapshot = snapshots / (case['id'] + '.json')
                    descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(descriptor, 'wb') as stream:
                        stream.write(raw_receipt)
                    receipt_check['snapshot_ref'] = str(snapshot.relative_to(ROOT))
                if case['id'] == 'unnamed_disabled_after_compaction':
                    disabled = next((c.get('receipt_postcondition', {}) for c in record['cases']
                                     if c['id'] == 'disable'), {})
                    unchanged = (disabled.get('content_sha256') is not None and
                                 disabled['content_sha256'] == receipt_check.get('content_sha256'))
                    receipt_check['unchanged_from_disable'] = unchanged
                    receipt_check['passed'] = receipt_check['passed'] and unchanged
                if case['id'] == 'fresh_thread' and protocol.get('fresh_thread_same_project'):
                    original, _ = receipt_postcondition(cwd, record['thread_id'], 'enabled')
                    reenabled = next((c.get('receipt_postcondition', {}) for c in record['cases']
                                      if c['id'] == 'reenable'), {})
                    unchanged = (original['passed'] and reenabled.get('content_sha256') is not None and
                                 reenabled['content_sha256'] == original.get('content_sha256'))
                    receipt_check['original_thread_receipt_unchanged'] = unchanged
                    receipt_check['passed'] = receipt_check['passed'] and unchanged
                result['routing_conformance_passed'] = result['passed']
                result['session_trace_postcondition'] = trace_check
                result['disabled_receipt_consulted'] = trace_check['disabled_receipt_consulted']
                result['receipt_postcondition'] = receipt_check
                result['passed'] = result['passed'] and trace_check['passed'] and receipt_check['passed']
            result.update(turn_id=turn_id, turn_status=complete['params']['turn'].get('status'),
                          elapsed_seconds=round(time.monotonic()-begin, 3),
                          prompt_sha256=hashlib.sha256(case['prompt'].encode()).hexdigest(),
                          native_skill_attached=bool(case.get('attach_skill')),
                          prompt_names_skill=('harry-ui-skill-set' in case['prompt']))
            if result['turn_status'] != 'completed':
                result['passed'] = False
            record['cases'].append(result)
            record.pop('active_turn', None)
            write_new(public / (case['id'] + '.json'), result)
            print(json.dumps({'case': case['id'], 'passed': result['passed'],
                              'resolver_calls': result['successful_bundle_resolver_calls'],
                              'guides': result['guide_bodies_returned_this_turn'],
                              'artifact_changed': result['artifact_changed']}), flush=True)
            if result['turn_status'] != 'completed':
                raise RuntimeError('MODEL_TURN_NOT_COMPLETED')
        record['status'] = 'pass' if all(c['passed'] for c in record['cases']) else 'conformance_failed'
    except Exception as exc:
        record['status'] = 'incomplete'
        record['error'] = type(exc).__name__ + ': ' + str(exc)
        # No unchanged retry after timeout/transport failure; preserve unknown effects.
    finally:
        if rpc is not None:
            record['processes'][-1]['cleanup_verified'] = rpc.close()
            record['processes'][-1]['exit_code'] = rpc.process.returncode
        os.close(fd)
        record['ended_at'] = now()
        record['bundle_unchanged_during_run'] = record['bundle_manifest_sha256'] == sha(BUNDLE / 'manifest.json')
        write_new(public / 'result.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True)
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--variant', choices=['fresh-v1'])
    parser.add_argument('--protocol', choices=['baseline', 'candidate', 'candidate-v3', 'independent', 'baseline-suffix'], default='baseline')
    parser.add_argument('--resume-record')
    parser.add_argument('--stage', choices=['baseline', 'candidate', 'scheduled'], default='baseline')
    opts = parser.parse_args()
    cancellation = threading.Event()
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in handlers:
        signal.signal(sig, lambda *_: cancellation.set())
    try:
        outcome = run(opts, cancel_event=cancellation)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    print(json.dumps({'record': opts.record, 'status': outcome.get('status'),
                      'model_turns': outcome['model_turns'], 'error': outcome.get('error')}, indent=2))
    sys.exit(0 if outcome.get('status') in ('pass', 'preflight_pass') else 1)
