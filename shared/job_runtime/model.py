"""Bounded, workspace-local Codex model execution for shared job infrastructure.

This adapter never chooses a fallback model, authenticates, copies credentials,
installs MCP servers, invokes a business sender, or retries an uncertain run.
Scheduling/retry decisions belong to the engine; allocation supplies the prompt.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time


class ModelError(ValueError):
    """Stable diagnostics contain no prompt, credentials or raw provider text."""


def _require(condition, code):
    if not condition:
        raise ModelError(code)


def _private_path(path, workspace, *, directory=False):
    path = Path(os.path.abspath(path))
    state = workspace / '.job-runtime'
    _require('..' not in path.parts and path.is_relative_to(state)
             and path != state and path.resolve().is_relative_to(state.resolve()), 'MODEL_PATH_OUTSIDE_STATE')
    for ancestor in [path, *path.parents]:
        if ancestor == workspace:
            break
        _require(not ancestor.is_symlink(), 'MODEL_PATH_SYMLINK')
        if ancestor.exists():
            _require(ancestor.stat().st_uid == os.getuid(), 'MODEL_PATH_OWNER_MISMATCH')
    if directory:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for ancestor in [path, *path.parents]:
            if ancestor == workspace:
                break
            ancestor.chmod(0o700)
    return path


def _write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(data)


def _profile(profile, workspace):
    required = {'codex_bin', 'model', 'effort', 'timeout_seconds', 'auth_home'}
    optional = {'max_output_bytes'}
    _require(type(profile) is dict and required <= profile.keys()
             and profile.keys() <= required | optional, 'MODEL_PROFILE_INVALID')
    binary = Path(profile['codex_bin'])
    _require(binary.is_absolute() and binary.is_file() and os.access(binary, os.X_OK), 'CODEX_BINARY_UNAVAILABLE')
    _require(type(profile['model']) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', profile['model']), 'MODEL_NAME_INVALID')
    _require(profile['effort'] in ('minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'), 'MODEL_EFFORT_INVALID')
    timeout = profile['timeout_seconds']
    _require(type(timeout) in (int, float) and 0 < timeout <= 3600, 'MODEL_TIMEOUT_INVALID')
    maximum = profile.get('max_output_bytes', 8 * 1024 * 1024)
    _require(type(maximum) is int and 1024 <= maximum <= 64 * 1024 * 1024, 'MODEL_OUTPUT_LIMIT_INVALID')
    home = _private_path(profile['auth_home'], workspace)
    _require(home.is_dir() and stat.S_IMODE(home.stat().st_mode) & 0o077 == 0, 'MODEL_AUTH_HOME_UNSAFE')
    auth = _private_path(home / 'auth.json', workspace)
    _require(auth.is_file(), 'MODEL_AUTH_REQUIRED')
    _require(stat.S_IMODE(auth.stat().st_mode) & 0o077 == 0, 'MODEL_AUTH_FILE_UNSAFE')
    return binary, home, timeout, maximum


def _environment(workspace, home, run_dir):
    # Deliberate allowlist: unrelated inherited API keys and control variables
    # must not influence a scheduled model invocation.
    names = ('PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'SSL_CERT_FILE',
             'SSL_CERT_DIR', 'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY',
             'https_proxy', 'http_proxy', 'all_proxy', 'no_proxy')
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(CODEX_HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
    for name, relative in (('TMPDIR', 'tmp'), ('XDG_CACHE_HOME', 'cache'),
                           ('CODEX_SQLITE_HOME', 'sqlite')):
        env[name] = str(_private_path(run_dir / relative, workspace, directory=True))
    return env


def _terminate(process):
    """Bounded TERM/KILL of the invocation's own process group."""
    for sig, wait in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        try:
            process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            continue
        # Even if the leader exits, clean any descendant that still holds the
        # process group. The group ID cannot be reused until it is empty.
        if sig == signal.SIGTERM:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        break
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def _classify(messages, returncode):
    """Classify known failure families, never return raw stderr/provider text."""
    value = '\n'.join(messages).lower()
    if any(token in value for token in ('not logged in', 'please log in', 'unauthorized',
                                       'authentication', 'refresh token', 'invalid_grant',
                                       'status 401', 'status code: 401', 'status 403')):
        return 'failed', 'MODEL_AUTH_REQUIRED'
    if any(token in value for token in ('model not found', 'model does not exist',
                                       'model is not supported', 'model is unsupported',
                                       'unsupported model', 'invalid model')):
        return 'failed', 'MODEL_UNAVAILABLE'
    if any(token in value for token in ('unrecognized', 'unknown field', 'invalid config',
                                       'unexpected argument', 'invalid value', 'output schema',
                                       'invalid_json_schema', 'invalid schema for response_format')):
        return 'failed', 'MODEL_CONFIGURATION_REJECTED'
    if any(token in value for token in ('rate limit', 'rate_limit', '429', 'temporarily unavailable',
                                       '503', '502', '504', 'connection reset', 'stream disconnected',
                                       'timed out', 'connection refused', 'failed to connect')):
        return 'retryable', 'MODEL_TRANSIENT_FAILURE'
    return 'unknown', 'MODEL_RUN_OUTCOME_UNCONFIRMED'


def _parse(events_path):
    completed, failures, messages, thread_id, usage, observed = False, [], [], None, None, None
    tool_activity = False
    parse_errors = 0
    for line in events_path.read_text(errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            parse_errors += 1
            continue
        if not isinstance(event, dict):
            parse_errors += 1
            continue
        kind = event.get('type')
        if kind == 'thread.started':
            thread_id = event.get('thread_id')
        if isinstance(event.get('model'), str):
            observed = event['model']
        if kind == 'turn.completed':
            completed = True
            usage = event.get('usage') if isinstance(event.get('usage'), dict) else None
        if kind in ('turn.failed', 'error'):
            failures.append(kind)
            error = event.get('error')
            if isinstance(error, dict) and isinstance(error.get('message'), str):
                messages.append(error['message'])
            elif isinstance(event.get('message'), str):
                messages.append(event['message'])
        item = event.get('item')
        if isinstance(item, dict) and item.get('type') in ('command_execution', 'mcp_tool_call',
                'web_search', 'file_change', 'tool_call', 'collab_agent_tool_call'):
            tool_activity = True
    return {'completed': completed, 'failures': failures, 'messages': messages,
            'thread_id': thread_id, 'usage': usage, 'observed_model': observed,
            'tool_activity': tool_activity, 'parse_errors': parse_errors}


def run_codex(profile: dict, prompt: str, workspace: Path, run_dir: Path,
              context: dict | None = None) -> dict:
    """Serialize use of the one workspace-owned CLI authentication cache."""
    receipt = {'requested_model': profile.get('model') if isinstance(profile, dict) else None,
               'observed_model': None, 'automatic_retry': False, 'fallback_used': False}
    try:
        workspace = Path(workspace).resolve(strict=True)
        _, home, _, _ = _profile(profile, workspace)
        lock = _private_path(home / 'runtime.lock', workspace)
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'status': 'retryable', 'code': 'MODEL_AUTH_CACHE_BUSY', 'receipt': receipt}
            return _run_codex_locked(profile, prompt, workspace, run_dir, context, lock_fd=fd)
        finally:
            os.close(fd)
    except ModelError as error:
        return {'status': 'failed', 'code': str(error), 'receipt': receipt}
    except Exception:
        return {'status': 'unknown', 'code': 'MODEL_ADAPTER_FAILED', 'receipt': receipt}


def _run_codex_locked(profile: dict, prompt: str, workspace: Path, run_dir: Path,
                       context: dict | None = None, *, lock_fd: int) -> dict:
    """Invoke one configured Codex model with no automatic retry/fallback.

    `context` may contain `response_schema` (trusted JSON Schema dict) and a
    `cancel_event` threading.Event. The process is read-only and command/app/web
    tools are disabled. All private input/output/state resides in `.job-runtime`.
    The parent must provision and coordinate the local auth home separately.
    """
    started = datetime.now(timezone.utc).isoformat()
    receipt = {'started_at': started, 'requested_model': profile.get('model') if isinstance(profile, dict) else None,
               'observed_model': None, 'automatic_retry': False, 'fallback_used': False}
    process = None
    try:
        workspace = Path(workspace).resolve(strict=True)
        _require(workspace.is_dir(), 'MODEL_WORKSPACE_INVALID')
        binary, home, timeout, maximum = _profile(profile, workspace)
        _require(type(prompt) is str and 0 < len(prompt.encode()) <= 512 * 1024, 'MODEL_PROMPT_INVALID')
        # Every attempt gets a fresh immutable run directory. Never overwrite an
        # older output and mistake it for a new success.
        run_dir = _private_path(run_dir, workspace)
        _require(not run_dir.exists(), 'MODEL_RUN_DIRECTORY_EXISTS')
        run_dir = _private_path(run_dir, workspace, directory=True)
        context = context or {}
        _require(set(context) <= {'response_schema', 'cancel_event', 'process_observer'}, 'MODEL_CONTEXT_INVALID')
        _require(context.get('process_observer') is None or callable(context['process_observer']), 'MODEL_PROCESS_OBSERVER_INVALID')
        if context.get('cancel_event') is not None and context['cancel_event'].is_set():
            return {'status': 'retryable', 'code': 'MODEL_CANCELLED_BEFORE_START', 'receipt': receipt}
        env = _environment(workspace, home, run_dir)
        logs = _private_path(run_dir / 'codex-log', workspace, directory=True)
        final = run_dir / 'last-message.txt'
        cmd = [str(binary), 'exec', '--ignore-user-config', '--ephemeral', '--strict-config',
               '--json', '--color', 'never', '--sandbox', 'read-only', '--cd', str(workspace),
               '--model', profile['model'], '--output-last-message', str(final)]
        overrides = {'approval_policy': 'never', 'model_reasoning_effort': profile['effort'],
                     'web_search': 'disabled', 'features.shell_tool': False,
                     'features.shell_snapshot': False, 'apps._default.enabled': False,
                     'mcp_servers': {}, 'cli_auth_credentials_store': 'file',
                     'log_dir': str(logs), 'sqlite_home': env['CODEX_SQLITE_HOME'],
                     'check_for_update_on_startup': False}
        for key, value in overrides.items():
            cmd += ['-c', key + '=' + json.dumps(value)]
        if 'response_schema' in context:
            _require(isinstance(context['response_schema'], dict), 'MODEL_SCHEMA_INVALID')
            schema = run_dir / 'response-schema.json'
            _write(schema, json.dumps(context['response_schema']))
            cmd += ['--output-schema', str(schema)]
        cmd += ['-']
        # Prompt never appears in argv/process listings.
        input_path = run_dir / 'prompt.txt'
        _write(input_path, prompt)
        out_path, err_path = run_dir / 'events.jsonl', run_dir / 'stderr.log'
        out_fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        err_fd = os.open(err_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        reason = None
        with input_path.open('rb') as input_stream, os.fdopen(out_fd, 'wb') as output, os.fdopen(err_fd, 'wb') as errors:
            process = subprocess.Popen(cmd, cwd=workspace, env=env, stdin=input_stream,
                                       stdout=output, stderr=errors, start_new_session=True,
                                       pass_fds=(lock_fd,))
            if context.get('process_observer') is not None:
                try:
                    context['process_observer'](process.pid)
                except BaseException:
                    _terminate(process)
                    raise ModelError('MODEL_PROCESS_OBSERVER_FAILED') from None
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    reason = 'MODEL_DEADLINE_EXCEEDED'
                elif out_path.stat().st_size + err_path.stat().st_size > maximum:
                    reason = 'MODEL_OUTPUT_LIMIT_EXCEEDED'
                elif context.get('cancel_event') is not None and context['cancel_event'].is_set():
                    reason = 'MODEL_CANCELLED'
                if reason:
                    _terminate(process)
                    break
                time.sleep(0.05)
        receipt.update(ended_at=datetime.now(timezone.utc).isoformat(), exit_code=process.returncode,
                       run_directory=str(run_dir.relative_to(workspace)))
        if out_path.stat().st_size + err_path.stat().st_size > maximum:
            reason = 'MODEL_OUTPUT_LIMIT_EXCEEDED'
        if reason:
            return {'status': 'unknown', 'code': reason, 'receipt': receipt}
        parsed = _parse(out_path)
        receipt.update(observed_model=parsed['observed_model'], thread_id=parsed['thread_id'],
                       usage=parsed['usage'], turn_completed=parsed['completed'],
                       event_stream_sha256=hashlib.sha256(out_path.read_bytes()).hexdigest())
        if parsed['tool_activity']:
            return {'status': 'failed', 'code': 'MODEL_TOOL_POLICY_VIOLATION', 'receipt': receipt}
        if parsed['observed_model'] is not None and parsed['observed_model'] != profile['model']:
            return {'status': 'failed', 'code': 'MODEL_IDENTITY_MISMATCH', 'receipt': receipt}
        if process.returncode == 0 and parsed['completed'] and not parsed['failures'] and not parsed['parse_errors']:
            _require(final.is_file() and not final.is_symlink() and final.stat().st_size <= maximum,
                     'MODEL_FINAL_RESPONSE_MISSING')
            raw = final.read_text()
            _require(bool(raw.strip()), 'MODEL_FINAL_RESPONSE_EMPTY')
            if 'response_schema' in context:
                # The CLI/provider performs schema validation; parse locally to
                # reject non-JSON even if an incompatible CLI silently ignored it.
                json.loads(raw)
            final.chmod(0o600)
            receipt.update(response_path=str(final.relative_to(workspace)),
                           response_sha256=hashlib.sha256(raw.encode()).hexdigest())
            return {'status': 'succeeded', 'code': 'MODEL_TURN_COMPLETED', 'receipt': receipt}
        status, code = _classify(parsed['messages'] + [err_path.read_text(errors='replace')], process.returncode)
        return {'status': status, 'code': code, 'receipt': receipt}
    except ModelError as error:
        return {'status': 'failed', 'code': str(error), 'receipt': receipt}
    except Exception:
        if process is not None and process.poll() is None:
            _terminate(process)
        return {'status': 'unknown', 'code': 'MODEL_ADAPTER_FAILED', 'receipt': receipt}
    except BaseException:
        if process is not None:
            _terminate(process)
        raise
