"""Temporary, fail-closed development campaign; production service is untouched.

One launchd label ticks an isolated Engine. Workers may write only a disposable
public-source copy. The existing authentication lock remains the sole owner.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

from .engine import Engine
from .model import _environment, _private_path, _profile, _terminate, _write, _classify
from .business import _metadata, _stream
from .service import atomic

UTC = timezone.utc
TERMINAL = {'expired', 'stopped_budget', 'stopped_stalled', 'stopped_failed',
            'stopped_manual', 'unknown', 'ready_for_review'}
COPY_ROOTS = {'docs', 'investment', 'shared', 'mentor', 'ui', 'niulai'}
EDIT_ROOTS = ('investment/', 'shared/actions/', 'shared/research_sources/', 'docs/')
IMPLEMENTATION_ROOTS = ('investment/', 'shared/actions/', 'shared/research_sources/')
GENERATED_PARTS = {'runtime', 'cache', 'tmp', 'reports', 'test-results', 'playwright-report',
                   'node_modules', '__pycache__', '.git', '.venv', 'dist', 'build'}
STEPS = [
    ('A', 'Freeze a coherent public source -> extracted fact -> numeric comparison pilot and its typed contracts/fixtures; inspect the source and existing code before implementing. Record retrieval versus source-grounded support checks.'),
    ('B', 'Implement atomic evidence CRUD, idempotency, revisions and logical withdrawal alongside existing acquisition; verify real process crash/concurrency safety with focused tests.'),
    ('C', 'Wrap existing acquisition and numeric comparison as reviewed versioned typed actions, with local schema validation, release manifests and safe staged roots; no new provider SDK.'),
    ('D', 'Implement one ordered research phase pilot with exact input/output bindings, application gates and bounded action selection. Develop the component path here; defer production scheduler integration for parent review.'),
    ('E', 'Add per-requirement due checks, bounded stale/conflict resolution and critical-input/lifecycle checks, with fake-clock cases. Reuse existing state and validators.'),
    ('F', 'Produce a sanitized versioned run export and private escaped read-only HTML report; reuse existing UI guidance and keep the report small.'),
]
# Small structural contracts for this particular campaign, owned by the
# supervisor rather than by the worker's progress JSON. These establish a
# reviewable candidate, not substantive correctness or production acceptance.
STEP_CONTRACTS = {
    'A': {'changes': ('investment/research/examples/*pilot*.json',),
          'artifacts': ('investment/research/examples/*pilot*.json',)},
    'B': {'changes': ('shared/research_sources/artifacts.py', 'shared/research_sources/store.py',
                      'shared/research_sources/tests/test_store.py'),
          'artifacts': ('shared/research_sources/store.py', 'shared/research_sources/tests/test_store.py')},
    'C': {'changes': ('shared/actions/*',),
          'artifacts': ('shared/actions/runtime.py', 'shared/actions/contracts.json', 'shared/actions/tests/test_actions.py')},
    'D': {'changes': ('investment/research/execution.py', 'investment/research/tests/test_execution.py'),
          'artifacts': ('investment/research/execution.py', 'investment/research/tests/test_execution.py')},
    'E': {'changes': ('investment/research/use_policy.py', 'investment/research/tests/test_use_policy.py',
                      'shared/research_sources/store.py', 'shared/research_sources/tests/test_store.py'),
          'artifacts': ('investment/research/use_policy.py', 'investment/research/tests/test_use_policy.py')},
    'F': {'changes': ('investment/research/report.py', 'investment/research/tests/test_report.py'),
          'artifacts': ('investment/research/report.py', 'investment/research/tests/test_report.py')},
}


def now():
    return datetime.now(UTC)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def folder(root, path):
    return _private_path(path, root, directory=True)


def controller_pin(root):
    names = ('campaign.py', 'engine.py', 'model.py', 'business.py', 'service.py')
    return {name: sha((root / 'shared/job_runtime' / name).read_bytes()) for name in names}


def sources(work):
    """Only implementation inputs qualify; checkpoints/reports are not work."""
    result = {}
    for p in work.rglob('*'):
        relative = p.relative_to(work).as_posix()
        if p.is_symlink() or not p.is_file() or any(x in p.relative_to(work).parts for x in GENERATED_PARTS):
            continue
        if relative.startswith(IMPLEMENTATION_ROOTS) and p.suffix in ('.py', '.json', '.mjs', '.ts', '.tsx', '.html', '.css'):
            if p.stat().st_size > 1024 * 1024:
                raise ValueError('SOURCE_FILE_TOO_LARGE')
            result[relative] = sha(p.read_bytes())
    return result


def digest_sources(values):
    return sha(json.dumps(values, sort_keys=True).encode())


def step_progress(step, work, before, after):
    """Check independently selected paths before trusting a completion claim."""
    contract = STEP_CONTRACTS.get(step)
    if contract is None:
        return {'passed': False, 'reason': 'unknown_step', 'missing': [], 'changed_paths': []}
    changed = [key for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)
               and any(fnmatchcase(key, pattern) for pattern in contract['changes'])]
    missing = [pattern for pattern in contract['artifacts']
               if not any(fnmatchcase(key, pattern) and (work / key).stat().st_size > 0 for key in after)]
    fixture_ok = True
    if step == 'A' and not missing:
        fixture_ok = False
        for key in after:
            if not fnmatchcase(key, contract['artifacts'][0]):
                continue
            try:
                value = load(work / key)
                fixture_ok = (isinstance(value, dict) and value.get('schema_version') == 1
                              and all(isinstance(value.get(name), str) and value[name]
                                      for name in ('case_id', 'source_url', 'entity', 'metric'))
                              and value['source_url'].startswith('https://')
                              and isinstance(value.get('observations'), list) and bool(value['observations'])
                              and isinstance(value.get('comparison'), dict) and bool(value['comparison']))
            except (OSError, ValueError, TypeError):
                fixture_ok = False
            if fixture_ok:
                break
    passed = bool(changed) and not missing and fixture_ok
    reason = ('candidate_artifacts_present' if passed else 'no_step_implementation_change' if not changed
              else 'missing_step_artifacts' if missing else 'pilot_fixture_contract_invalid')
    return {'passed': passed, 'reason': reason, 'missing': missing, 'changed_paths': changed}


def protected_sources(work):
    result = {}
    for p in work.rglob('*'):
        rel = p.relative_to(work).as_posix()
        if rel.startswith(('.niulai-state/', '.job-runtime/', '.research-sources/', 'mentor/runtime/', 'ui/runtime/')):
            continue
        if p.is_file() and not p.is_symlink() and not any(x in p.parts for x in ('.git', '__pycache__', 'node_modules')):
            if not rel.startswith(EDIT_ROOTS) and rel != 'campaign_probe.py':
                result[rel] = sha(p.read_bytes())
    return result


def decision(config, state, at):
    """Pure budget/clock guard; called again immediately before every dispatch."""
    if state['status'] in TERMINAL:
        return state['status']
    if at.timestamp() >= config['expires_at']:
        return 'expired'
    if at.timestamp() < state.get('last_tick', 0) - 5:
        return 'unknown'
    if state.get('active_attempt'):
        return 'unknown'
    if state['calls'] >= config['max_calls'] or state['model_seconds'] >= config['max_model_seconds'] or state['tokens'] >= config['max_tokens']:
        return 'stopped_budget'
    if state['no_progress'] >= 2 or state['same_failure'] >= 2:
        return 'stopped_stalled'
    return None


def apply_result(state, result, before, after, checks_ok):
    """No prose/mtime/heartbeat is accepted as implementation progress."""
    fingerprint = digest_sources(after)
    changed = before != after
    cycle = changed and fingerprint in state['seen_sources']
    progressed = changed and checks_ok and not cycle
    state['no_progress'] = 0 if progressed else state['no_progress'] + 1
    if changed:
        state['seen_sources'].append(fingerprint)
    failure = result.get('code', 'UNKNOWN') if not checks_ok else None
    state['same_failure'] = state['same_failure'] + 1 if failure and failure == state.get('last_failure') else (1 if failure else 0)
    state['last_failure'] = failure
    if cycle or state['no_progress'] >= 2 or state['same_failure'] >= 2:
        state['status'] = 'stopped_stalled'
    return progressed


def production_busy(root, duration):
    """Yield to main jobs and their next daily wake; never change their state."""
    config = load(root / '.job-runtime/config/runtime.json')
    dbpath = root / '.job-runtime/engine/schedule.sqlite'
    if dbpath.exists():
        with sqlite3.connect('file:' + str(dbpath) + '?mode=ro', uri=True) as db:
            if db.execute("SELECT 1 FROM slots WHERE status IN ('running','unknown','ready','retry_wait') LIMIT 1").fetchone():
                return True
    from zoneinfo import ZoneInfo
    at = now()
    for relative in config['allocation_files']:
        for job in load(root / relative)['jobs']:
            if not job['enabled']:
                continue
            schedule = job['schedule']
            if schedule['kind'] == 'daily':
                local = at.astimezone(ZoneInfo(schedule['timezone']))
                for days in (0, 1):
                    for clock in schedule['times']:
                        h, m = map(int, clock.split(':'))
                        due = (local + timedelta(days=days)).replace(hour=h, minute=m, second=0, microsecond=0)
                        if 0 <= (due - local).total_seconds() <= duration + 120:
                            return True
            elif schedule['kind'] == 'interval':
                # Continuous shared-auth workloads have priority; do not compete.
                return True
    return False


def checks(config, work, attempt, step):
    python = config['research_python']
    if step == 'probe':
        commands = [[python, '-c', "import campaign_probe; assert campaign_probe.answer() == '" + config['challenge'] + "'"]]
    else:
        commands = [[python, '-m', 'unittest', 'discover', '-s', d, '-q'] for d in
                    ('investment/research/tests', 'shared/research_sources/tests')]
        if (work / 'shared/actions/tests').is_dir():
            commands.append([python, '-m', 'unittest', 'discover', '-s', 'shared/actions/tests', '-q'])
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'LANG', 'SSL_CERT_FILE', 'SSL_CERT_DIR') if k in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(attempt / 'tmp'))
    rows = []
    for i, cmd in enumerate(commands):
        timeout = min(60, config['expires_at'] - now().timestamp())
        if timeout <= 0 or (attempt.parent.parent / 'stop-requested').exists():
            rows.append({'exit_code': None, 'code': 'CHECK_CANCELLED'})
            break
        try:
            with (attempt / ('check-%d.log' % i)).open('wb') as output:
                p = subprocess.Popen(cmd, cwd=work, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    p.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    _terminate(p)
                    rows.append({'exit_code': None, 'code': 'CHECK_TIMEOUT'})
                    continue
            rows.append({'exit_code': p.returncode, 'log_sha256': sha((attempt / ('check-%d.log' % i)).read_bytes())})
        except OSError:
            rows.append({'exit_code': None, 'code': 'CHECK_START_FAILED'})
    return rows


def development_turn(config, root, work, attempt, prompt, timeout):
    profile = dict(config['profile'], timeout_seconds=timeout)
    binary, home, _, maximum = _profile(profile, root)
    lock = os.open(home / 'runtime.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    p = None
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'retryable', 'code': 'MODEL_AUTH_CACHE_BUSY', 'receipt': {}}
        env = _environment(root, home, attempt)
        env['RUST_LOG'] = 'off'
        cmd = [str(binary), 'exec', '--ignore-user-config', '--ephemeral', '--strict-config', '--json',
               '--color', 'never', '--sandbox', 'workspace-write', '--cd', str(work), '--model', profile['model']]
        overrides = {'approval_policy': 'never', 'model_reasoning_effort': profile['effort'],
                     'web_search': 'disabled', 'features.shell_tool': True, 'features.shell_snapshot': False,
                     'features.apps': False, 'apps._default.enabled': False, 'mcp_servers': {},
                     'cli_auth_credentials_store': 'file', 'history.persistence': 'none',
                     'check_for_update_on_startup': False, 'sqlite_home': env['CODEX_SQLITE_HOME'],
                     'log_dir': str(attempt / 'codex-log'), 'sandbox_workspace_write.network_access': True}
        for k, v in overrides.items():
            cmd += ['-c', k + '=' + json.dumps(v)]
        cmd += ['-']
        p = subprocess.Popen(cmd, cwd=work, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True, pass_fds=(lock,))
        # Record an attributable process identity for crash reconciliation.
        atomic(attempt / 'process.json', {'pid': p.pid, 'worktree': str(work),
               'identity': subprocess.check_output(['/bin/ps', '-p', str(p.pid), '-o', 'lstart=']).decode().strip()})
        started = time.monotonic()
        class Cancel:
            def is_set(self):
                return (attempt.parent.parent / 'stop-requested').exists()
        raw, errors, reason = _stream(p, prompt.encode(), timeout, maximum, Cancel())
        meta = _metadata(raw)
        receipt = {k: meta[k] for k in ('thread_id', 'usage', 'observed_model', 'completed', 'tool_failures')}
        receipt.update(tool_names=sorted(meta['tool_names']), elapsed_seconds=time.monotonic() - started,
                       exit_code=p.returncode, event_sha256=sha(raw), requested_model=profile['model'])
        # Private raw diagnostics are bounded by the existing stream helper.
        _write(attempt / 'events.jsonl', raw.decode(errors='replace'))
        _write(attempt / 'stderr.log', errors.decode(errors='replace'))
        _write(attempt / 'final.txt', meta['final'] or '')
        if reason:
            return {'status': 'unknown', 'code': reason, 'receipt': receipt}
        if meta['observed_model'] is not None and meta['observed_model'] != profile['model']:
            return {'status': 'failed', 'code': 'MODEL_IDENTITY_MISMATCH', 'receipt': receipt}
        if p.returncode == 0 and meta['completed'] and not meta['failed'] and not meta['parse_errors']:
            if not meta['usage']:
                return {'status': 'unknown', 'code': 'USAGE_UNAVAILABLE', 'receipt': receipt}
            return {'status': 'succeeded', 'code': 'DEVELOPMENT_TURN_COMPLETED', 'receipt': receipt}
        status, code = _classify(meta['errors'] + [errors.decode(errors='replace')], p.returncode)
        return {'status': status, 'code': code, 'receipt': receipt}
    except BaseException:
        if p is not None:
            _terminate(p)
        raise
    finally:
        os.close(lock)


def execute(config, state, root, base, context):
    at = now()
    guard = decision(config, state, at)
    if guard:
        state['status'] = guard
        return {'status': 'failed', 'code': 'CAMPAIGN_GUARD_STOP', 'receipt': {'guard': guard}}
    probe = state['status'] == 'probe_pending'
    if not probe and state['status'] != 'active':
        return {'status': 'succeeded', 'code': 'CAMPAIGN_NOT_ACTIVE', 'receipt': {'state': state['status']}}
    remaining = min(config['slice_seconds'], config['expires_at'] - at.timestamp() - 10,
                    config['max_model_seconds'] - state['model_seconds'])
    if remaining < 10 or production_busy(root, remaining):
        return {'status': 'succeeded', 'code': 'CAMPAIGN_YIELDED', 'receipt': {'priority': 'existing_jobs'}}
    attempt = folder(root, base / 'attempts' / context['attempt_id'])
    folder(root, attempt / 'tmp')
    work = Path(config['worktree'])
    before, protected = sources(work), protected_sources(work)
    # Invoke canonical mentor loader explicitly; automatic hook trust is untouched.
    from mentor.session_init import initialize
    hook = initialize(work, {'hook_event_name': 'SessionStart', 'source': 'resume', 'cwd': str(work)})
    mentor_context = hook['hookSpecificOutput']['additionalContext']
    atomic(attempt / 'mentor-hook.json', hook)
    if not mentor_context.startswith('MENTOR_INIT_OK\n'):
        state['status'] = 'stopped_failed'
        return {'status': 'failed', 'code': 'CAMPAIGN_MENTOR_INIT_FAILED', 'receipt': {'attempt': context['attempt_id']}}
    step = 'probe' if probe else STEPS[state['step']][0]
    objective = ("Create campaign_probe.py defining answer() returning exactly " + repr(config['challenge']) +
                 ". Run it with Python and verify the return. Make no other changes. This is a development-worker smoke test, not investment research.") if probe else STEPS[state['step']][1]
    prompt = mentor_context + '\n\n' + (
        'Temporary authorized implementation campaign. Work only in this isolated copy. Read docs/plans/evidence-actions-pipeline-mvp.md and relevant local skills. '
        'Do not modify niulai/, shared/job_runtime/, mentor/, ui/ or AGENTS.md. No production config/auth, orders, email, MCP registrations or global installs. '
        'Do not run schedulers or detached/background processes. Do not alter this controller or its external verifier. '
        'Use existing libraries; keep temporary/cache output local. A supervisor will run fixed checks and inspect content hashes. '
        'Checkpoint in docs/campaign-progress.json with step, completed(boolean), blocker, next_action and evidence paths. '
        'Only set completed after focused checks pass. Final response must state actual work and unresolved gaps. '
        'When blocked, record the concrete dependency and stop. Read previous checkpoint before working. '
        'Remaining slice seconds: ' + str(int(remaining)) + '. Step ' + step + ': ' + objective)
    state['active_attempt'] = context['attempt_id']
    state['calls'] += 1
    atomic(base / 'state.json', state)  # reserve attempt before model dispatch
    result = development_turn(config, root, work, attempt, prompt, remaining)
    if result['code'] == 'MODEL_AUTH_CACHE_BUSY':
        state['calls'] -= 1
        state['active_attempt'] = None
        return {'status': 'succeeded', 'code': 'CAMPAIGN_YIELDED', 'receipt': {'priority': 'auth_owner'}}
    receipt = result['receipt']
    state['model_seconds'] += receipt.get('elapsed_seconds', remaining)
    usage = receipt.get('usage') or {}
    state['tokens'] += usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
    check_rows = checks(config, work, attempt, step)
    checks_ok = bool(check_rows) and all(x.get('exit_code') == 0 for x in check_rows)
    if protected_sources(work) != protected:
        result = {**result, 'status': 'failed', 'code': 'PROTECTED_COPY_CHANGED'}
    after = sources(work)
    contract = {'passed': True, 'reason': 'independent_probe_assertion', 'missing': [], 'changed_paths': []} if probe else step_progress(step, work, before, after)
    progressed = apply_result(state, result, before, after,
                              checks_ok and contract['passed'] and result['status'] == 'succeeded')
    if result['status'] != 'succeeded':
        state['status'] = 'unknown' if result['status'] == 'unknown' else 'stopped_failed'
    elif probe:
        state['status'] = 'probe_passed' if checks_ok and receipt.get('tool_names') else 'stopped_failed'
    else:
        checkpoint = work / 'docs/campaign-progress.json'
        try:
            cp = load(checkpoint)
        except (OSError, ValueError):
            cp = {}
        if cp.get('blocker'):
            state['status'] = 'stopped_failed'
        elif progressed and cp.get('step') == step and cp.get('completed') is True:
            state['step'] += 1
            if state['step'] == len(STEPS):
                state['status'] = 'ready_for_review'
    state['active_attempt'] = None
    report = {'context': context, 'step': step, 'result': result, 'checks': check_rows,
              'changed_paths': sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k)),
              'step_contract': contract,
              'source_fingerprint': digest_sources(after), 'progressed': progressed,
              'state': dict(state), 'ended_at': now().isoformat()}
    atomic(attempt / 'receipt.json', report)
    state['last_receipt'] = str((attempt / 'receipt.json').relative_to(root))
    return {'status': 'succeeded' if result['status'] == 'succeeded' else result['status'],
            'code': 'CAMPAIGN_SLICE_RECORDED', 'receipt': {'report': state['last_receipt'], 'campaign_status': state['status']}}


def tick(root, base):
    fd = os.open(base / 'campaign.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'busy'}
        config, state = load(base / 'config.json'), load(base / 'state.json')
        guard = decision(config, state, now())
        if (base / 'stop-requested').exists():
            guard = 'stopped_manual'
        if config['controller_pin'] != controller_pin(root):
            guard = 'unknown'
        if guard:
            state['status'] = guard
        state['last_tick'] = now().timestamp()
        atomic(base / 'state.json', state)
        if state['status'] in TERMINAL:
            # A previous coordinator may have died after spawning its model.
            # Kill only the exact recorded process birth and worktree identity.
            active = state.get('active_attempt')
            identity = base / 'attempts' / str(active) / 'process.json'
            if active and identity.exists():
                recorded = load(identity)
                ps = subprocess.run(['/bin/ps', '-p', str(recorded['pid']), '-o', 'lstart=', '-o', 'command='], capture_output=True, text=True, timeout=5)
                if recorded['identity'] and recorded['identity'] in ps.stdout and config['worktree'] in ps.stdout:
                    import signal
                    for sig in (signal.SIGTERM, signal.SIGKILL):
                        try:
                            os.killpg(recorded['pid'], sig)
                        except ProcessLookupError:
                            break
            subprocess.run(['/bin/launchctl', 'bootout', 'gui/%d/%s' % (os.getuid(), config['label'])], capture_output=True, timeout=10)
            return state
        jobs = config['jobs']
        engine = Engine(base / 'engine', jobs, {'max_attempts': 1, 'backoff_seconds': 30, 'max_backoff_seconds': 30},
                        lambda job, ctx: execute(config, state, root, base, ctx), workspace_root=root, max_workers=1)
        try:
            result = engine.tick(now())
        except BaseException:
            state['status'] = 'unknown'
            atomic(base / 'state.json', state)
            raise
        atomic(base / 'state.json', state)
        return {'campaign_status': state['status'], 'scheduler': result}
    finally:
        os.close(fd)


def create(root, name):
    if not name.replace('-', '').isalnum() or len(name) > 60:
        raise ValueError('CAMPAIGN_NAME_INVALID')
    base = _private_path(root / '.job-runtime/campaigns' / name, root)
    if base.exists():
        raise ValueError('CAMPAIGN_ALREADY_EXISTS')
    folder(root, base)
    work = folder(root, base / 'worktree')
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root).decode().split('\0')
    total = 0
    for name_in_repo in sorted(set(names)):
        if not name_in_repo:
            continue
        p = Path(name_in_repo)
        if p.parts[0] not in COPY_ROOTS and name_in_repo not in ('AGENTS.md', '.gitignore', 'README.md'):
            continue
        source = root / p
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(root):
            continue
        total += source.stat().st_size
        if total > 80 * 1024 * 1024:
            raise ValueError('COPY_TOO_LARGE')
        target = work / p
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    from mentor.session_init import SKILLS
    links = work / '.agents/skills'
    links.mkdir(parents=True)
    for name_in_repo in SKILLS:
        (links / name_in_repo).symlink_to('../../mentor/skills/' + name_in_repo, target_is_directory=True)
    subprocess.run(['git', '-c', 'init.defaultBranch=campaign', 'init', '-q', str(work)], check=True)
    runtime = load(root / '.job-runtime/config/runtime.json')
    profile = runtime['model_profiles']['default']
    at = now()
    label = 'com.local.trading-agent.campaign.' + name
    config = {'schema_version': 1, 'created_at': at.isoformat(), 'expires_at': (at + timedelta(hours=12)).timestamp(),
              'label': label, 'worktree': str(work), 'controller_pin': controller_pin(root),
              'profile': profile, 'research_python': str(root / '.research-sources/.venv/bin/python'),
              'slice_seconds': 600, 'max_calls': 16, 'max_model_seconds': 7200, 'max_tokens': 500000,
              'challenge': uuid.uuid4().hex, 'jobs': []}
    for i in range(48):
        due = at + timedelta(seconds=60 + i * 900)
        config['jobs'].append({'id': 'campaign.%02d' % i, 'enabled': True, 'replay_safe': False,
                              'schedule': {'kind': 'once', 'at': due.isoformat(), 'grace_seconds': 90}})
    state = {'status': 'probe_pending', 'calls': 0, 'model_seconds': 0, 'tokens': 0, 'step': 0,
             'no_progress': 0, 'same_failure': 0, 'active_attempt': None,
             'seen_sources': [digest_sources(sources(work))], 'last_tick': at.timestamp()}
    atomic(base / 'config.json', config)
    atomic(base / 'state.json', state)
    atomic(base / 'protected-baseline.json', protected_sources(work))
    return base


def install(root, base):
    config = load(base / 'config.json')
    runtime = load(root / '.job-runtime/config/runtime.json')
    value = {'Label': config['label'], 'ProgramArguments': [runtime['python_bin'], '-B', '-m', 'shared.job_runtime.campaign',
             'tick', '--workspace', str(root), '--state', str(base)], 'WorkingDirectory': str(root),
             'EnvironmentVariables': {'PYTHONPATH': str(root), 'PYTHONDONTWRITEBYTECODE': '1', 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin',
                                      'HOME': str(Path.home()), 'TMPDIR': str(root / '.job-runtime/tmp')},
             'StartInterval': 60, 'RunAtLoad': False, 'ProcessType': 'Background', 'Umask': 0o077,
             'ExitTimeOut': 5, 'StandardOutPath': str(base / 'launchd.stdout.log'), 'StandardErrorPath': str(base / 'launchd.stderr.log')}
    path = base / 'campaign.plist'
    path.write_bytes(plistlib.dumps(value)); path.chmod(0o600)
    result = subprocess.run(['/bin/launchctl', 'bootstrap', 'gui/%d' % os.getuid(), str(path)], capture_output=True, timeout=15)
    if result.returncode:
        raise ValueError('CAMPAIGN_BOOTSTRAP_FAILED')
    return {'label': config['label'], 'expires_at': datetime.fromtimestamp(config['expires_at'], UTC).isoformat()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=('create', 'install', 'tick', 'status', 'activate', 'stop'))
    p.add_argument('--workspace', default=str(Path.cwd()))
    p.add_argument('--state')
    p.add_argument('--name')
    args = p.parse_args(); root = Path(args.workspace).resolve(strict=True)
    if args.command == 'create':
        print(json.dumps({'state': str(create(root, args.name))})); return
    base = _private_path(args.state, root)
    if args.command == 'tick':
        print(json.dumps(tick(root, base))); return
    if args.command == 'install':
        print(json.dumps(install(root, base))); return
    if args.command == 'status':
        print(json.dumps(load(base / 'state.json'), indent=2)); return
    if args.command == 'stop':
        (base / 'stop-requested').touch(mode=0o600)
        print(json.dumps({'stop_requested': True, 'state': str(base)})); return
    fd = os.open(base / 'campaign.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = load(base / 'state.json'); config = load(base / 'config.json')
        if args.command == 'activate':
            if state['status'] != 'probe_passed' or decision(config, state, now()):
                raise ValueError('VERIFIED_PROBE_REQUIRED')
            # Caller must independently inspect probe receipt before this command.
            state['status'] = 'active'; state['no_progress'] = 0
        else:
            state['status'] = 'stopped_manual'
        atomic(base / 'state.json', state)
        print(json.dumps(state))
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
