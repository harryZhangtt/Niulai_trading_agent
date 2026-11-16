"""Bounded, workspace-local Codex model execution for shared job infrastructure.

This adapter never chooses a fallback model, authenticates, copies credentials,
installs MCP servers, invokes a business sender, or retries an uncertain run.
Scheduling/retry decisions belong to the engine; allocation supplies the prompt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import time
from types import MappingProxyType

from .pipe_transport import pump
from .provider_contract import ProviderResultV1
from .providers.codex_cli import (
    FinalOutputResolver, NormalizedCodexRunnerEvidenceV1,
    NORMALIZED_SCHEMA, run_one_shot as normalize_codex_one_shot,
)


CODEX_TRANSLATOR_VERSION = 'sanitized-codex-jsonl-v2-0.167-source-candidate'
CODEX_CAPTURE_PROVENANCE = MappingProxyType({
    'fixture_kind': 'source_bound_candidate',
    'sanitizer_version': CODEX_TRANSLATOR_VERSION,
    'provider_cli_version': '0.167.0',
    'source_commit': '086ccc833bc9cf01024ad2dd6af7dbd421b6bf9a',
    'thread_event_sha256': '6f5dd0c113373078eef82c96bf8c6c2644dc8f08222e2fc2a96b170539cc5c44',
    'thread_item_details_sha256': 'f7a252acd64c2c71a51eb88ecefb9c3793193f7fff598e57372d912e56d340a9',
    'source_candidate_conformance_verified': True,
    'official_asset_binding_verified': False,
    'sanitized_live_capture_verified': False,
    'canonical_integration_reviewed': False,
    'raw_source_capture_retained': False,
    'production_translation': 'runtime_unverified',
    'activation_blocked': True,
})
CODEX_TRANSLATION_CAPABILITY = MappingProxyType({
    'production_translation_verified': False,
    'source_candidate_conformance_verified': CODEX_CAPTURE_PROVENANCE['source_candidate_conformance_verified'],
    'official_asset_binding_verified': False,
    'sanitized_live_capture_verified': False,
    'canonical_integration_reviewed': False,
    'runtime_unverified': True,
    'activation_blocked': True,
})


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
    try:
        os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, 'w') as stream:
        stream.write(data)


def _prompt_chunks(source, *, legacy=False):
    """Return bounded internal chunks; v2 accepts exact bytes only."""
    if legacy and type(source) is str:
        source = source.encode()
    _require(type(source) is bytes and 0 < len(source) <= 512 * 1024,
             'MODEL_PROMPT_INVALID' if legacy else 'MODEL_PROMPT_SOURCE_INVALID')
    return ((source[index:index+65536] for index in range(0,len(source),65536)),
            hashlib.sha256(source).hexdigest(),len(source))


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _output_metadata(value):
    return (value.st_dev, value.st_ino, value.st_uid, stat.S_IFMT(value.st_mode),
            stat.S_IMODE(value.st_mode), value.st_nlink, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _read_private_output(directory_fd, directory_path, name, maximum):
    descriptor = None
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
    try:
        held_directory = os.fstat(directory_fd)
        visible_directory = os.stat(directory_path, follow_symlinks=False)
        _require(stat.S_ISDIR(held_directory.st_mode)
                 and held_directory.st_uid == os.getuid()
                 and stat.S_IMODE(held_directory.st_mode) == 0o700
                 and (held_directory.st_dev, held_directory.st_ino)
                     == (visible_directory.st_dev, visible_directory.st_ino),
                 'MODEL_FINAL_OUTPUT_UNSAFE')
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        opened = os.fstat(descriptor)
        _require(stat.S_ISREG(opened.st_mode) and opened.st_uid == os.getuid()
                 and opened.st_nlink == 1, 'MODEL_FINAL_OUTPUT_UNSAFE')
        _require(0 <= opened.st_size <= maximum, 'MODEL_OUTPUT_LIMIT_EXCEEDED')
        os.fchmod(descriptor, 0o600)
        hardened = os.fstat(descriptor)
        _require(stat.S_ISREG(hardened.st_mode) and hardened.st_uid == os.getuid()
                 and stat.S_IMODE(hardened.st_mode) == 0o600
                 and hardened.st_nlink == 1
                 and (opened.st_dev, opened.st_ino) == (hardened.st_dev, hardened.st_ino),
                 'MODEL_FINAL_OUTPUT_UNSAFE')
        _require(0 <= hardened.st_size <= maximum, 'MODEL_OUTPUT_LIMIT_EXCEEDED')
        visible = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        _require(_output_metadata(hardened) == _output_metadata(visible),
                 'MODEL_FINAL_OUTPUT_UNSAFE')
        remaining = hardened.st_size
        chunks = []
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            _require(bool(chunk), 'MODEL_FINAL_OUTPUT_UNSAFE')
            chunks.append(chunk)
            remaining -= len(chunk)
        _require(os.read(descriptor, 1) == b'', 'MODEL_FINAL_OUTPUT_UNSAFE')
        after = os.fstat(descriptor)
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        current_directory = os.stat(directory_path, follow_symlinks=False)
        _require(_output_metadata(hardened) == _output_metadata(after)
                 and _output_metadata(after) == _output_metadata(current)
                 and (held_directory.st_dev, held_directory.st_ino)
                     == (current_directory.st_dev, current_directory.st_ino),
                 'MODEL_FINAL_OUTPUT_UNSAFE')
        return b''.join(chunks)
    except ModelError:
        raise
    except OSError:
        raise ModelError('MODEL_FINAL_OUTPUT_UNSAFE') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _profile(profile, workspace):
    required = {'codex_bin', 'model', 'effort', 'timeout_seconds', 'auth_home'}
    optional = {'max_output_bytes', 'strict_process_tree_containment'}
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
    _require(type(profile.get('strict_process_tree_containment', False)) is bool,
             'MODEL_STRICT_PROCESS_TREE_CONTAINMENT_INVALID')
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


def _parse(raw):
    completed, failures, messages, thread_id, usage, observed = False, [], [], None, None, None
    tool_activity = False
    parse_errors = 0
    for line in raw.decode(errors='replace').splitlines():
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


def translate_codex_jsonl(raw: bytes, configured_model: str) -> bytes:
    """Translate one source-bound Codex 0.167 JSONL stream conservatively."""
    _require(type(raw) is bytes and raw.endswith(b'\n') and raw, 'CODEX_CAPTURE_TRUNCATED')
    _require(type(configured_model) is str and re.fullmatch(
        r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', configured_model), 'MODEL_NAME_INVALID')
    def pairs(values):
        _require(len(values) == len({key for key,_ in values}), 'CODEX_CAPTURE_DUPLICATE_KEY')
        return dict(values)
    item_fields = {
        'agent_message': ({'id','type','text'}, {'text':str}),
        'reasoning': ({'id','type','text'}, {'text':str}),
        'command_execution': ({'id','type','command','status'}, {'command':str,'status':str}),
        'file_change': ({'id','type','changes','status'}, {'changes':list,'status':str}),
        'mcp_tool_call': ({'id','type','server','tool','status'}, {'server':str,'tool':str,'status':str}),
        'collab_tool_call': ({'id','type','tool','status'}, {'tool':str,'status':str}),
        'web_search': ({'id','type','query','status'}, {'query':str,'status':str}),
        'todo_list': ({'id','type','items'}, {'items':list}),
        'error': ({'id','type','message'}, {'message':str}),
    }
    tool_kinds={'command_execution':'command','mcp_tool_call':'mcp','web_search':'web_search',
                'file_change':'file_change','collab_tool_call':'collaboration'}
    translated=[];thread=False;turn=False;terminal=False;items={};emitted_tools=set()
    for encoded in raw.splitlines():
        _require(0 < len(encoded) <= 65536, 'CODEX_CAPTURE_LINE_INVALID')
        try:event=json.loads(encoded,object_pairs_hook=pairs,parse_constant=lambda _:
            (_ for _ in ()).throw(ValueError()))
        except ModelError:raise
        except (TypeError,ValueError,UnicodeError):raise ModelError('CODEX_CAPTURE_MALFORMED') from None
        _require(type(event) is dict and type(event.get('type')) is str and not terminal,
                 'CODEX_CAPTURE_EVENT_INVALID')
        _require('model' not in event, 'CODEX_CAPTURE_MODEL_INVALID')
        kind=event['type']
        if kind=='thread.started':
            _require(not thread and not turn and set(event)=={'type','thread_id'} and type(event['thread_id']) is str,
                     'CODEX_CAPTURE_ORDER_INVALID')
            thread=True;translated.append({'type':'invocation.started','opaque_identity':hashlib.sha256(raw).hexdigest()[:32]})
        elif kind=='turn.started':
            _require(thread and not turn and set(event)=={'type'},'CODEX_CAPTURE_ORDER_INVALID');turn=True
        elif kind in ('item.started','item.updated','item.completed'):
            _require(turn and set(event)=={'type','item'} and type(event['item']) is dict,
                     'CODEX_CAPTURE_EVENT_INVALID')
            item=event['item'];itype=item.get('type');spec=item_fields.get(itype)
            _require(spec is not None and set(item)==spec[0] and type(item.get('id')) is str and item['id'] and
                     all(type(item[key]) is expected for key,expected in spec[1].items()) and 'model' not in item,
                     'CODEX_CAPTURE_ITEM_UNSUPPORTED')
            ident=item['id'];state=items.get(ident)
            if kind=='item.started':_require(state is None,'CODEX_CAPTURE_ORDER_INVALID');items[ident]=(itype,'started')
            elif kind=='item.updated':_require(state==(itype,'started'),'CODEX_CAPTURE_ORDER_INVALID')
            else:
                _require(state is None or state==(itype,'started'),'CODEX_CAPTURE_ORDER_INVALID')
                items[ident]=(itype,'completed')
            if itype in tool_kinds and ident not in emitted_tools:
                emitted_tools.add(ident);translated.append({'type':'activity.observed','activity':{'kind':tool_kinds[itype]}})
        elif kind=='turn.completed':
            _require(turn and set(event)<={'type','usage'} and all(state=='completed' for _,state in items.values()),
                     'CODEX_CAPTURE_ORDER_INVALID')
            usage=event.get('usage');_require(usage is None or type(usage) is dict,'CODEX_CAPTURE_USAGE_INVALID')
            safe={}
            for key in ('input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens'):
                if usage is not None and key in usage:
                    _require(type(usage[key]) is int and usage[key]>=0,'CODEX_CAPTURE_USAGE_INVALID');safe[key]=usage[key]
            translated.append({'type':'invocation.completed','usage':safe});terminal=True
        elif kind=='turn.failed':
            _require(turn and set(event)=={'type','error'},'CODEX_CAPTURE_EVENT_INVALID')
            translated.append({'type':'invocation.failed','failure':{}});terminal=True
        elif kind=='error':
            _require(turn and set(event)=={'type','message'},'CODEX_CAPTURE_EVENT_INVALID')
            translated.append({'type':'runner.error','failure':{}});terminal=True
        else:raise ModelError('CODEX_CAPTURE_EVENT_UNSUPPORTED')
    _require(thread,'CODEX_CAPTURE_START_MISSING')
    return b''.join(json.dumps(event,sort_keys=True,separators=(',',':')).encode()+b'\n' for event in translated)


def _closed_classification(result):
    code = result.get('code')
    if code == 'MODEL_AUTH_REQUIRED': category = 'auth'
    elif code == 'MODEL_UNAVAILABLE': category = 'model'
    elif code in ('MODEL_CONFIGURATION_REJECTED','MODEL_PROFILE_INVALID'): category = 'config'
    elif code in ('MODEL_DEADLINE_EXCEEDED',): category = 'timeout'
    elif code in ('MODEL_TRANSIENT_FAILURE',): category = 'connection_reset'
    elif code in ('MODEL_TOOL_POLICY_VIOLATION',): category = 'policy'
    else: category = 'provider'
    terminal = result.get('receipt', {}).get('turn_completed') is True
    return {'category':category, 'authority':'verified_terminal' if terminal else 'none',
            'http_status':None, 'provider_should_retry':False,
            'retry_after':None, 'retry_after_source':None}


def _with_model_binding_nonclaim(result):
    receipt = {key:value for key,value in dict(result.receipt).items()
               if key != 'observed_model_verified'}
    receipt.update(model_binding_source='configured_cli_argument',
                   provider_reported_model=False,
                   translator_version=CODEX_TRANSLATOR_VERSION)
    return ProviderResultV1(
        provider=result.provider, operation_id=result.operation_id, phase=result.phase,
        submission=result.submission, terminal_proof=result.terminal_proof,
        status=result.status, code=result.code, failure_kind=result.failure_kind,
        http_status=result.http_status, provider_should_retry=result.provider_should_retry,
        retry_after_at=result.retry_after_at, retry_after_source=result.retry_after_source,
        receipt=receipt, version=result.version)


def _deadline_result(operation_id: str, deadline: datetime, *, submitted: bool) -> ProviderResultV1:
    """Return deadline authority without changing the caller's absolute deadline."""
    return ProviderResultV1(
        provider='codex_cli', operation_id=operation_id,
        phase='submitted' if submitted else 'not_started',
        submission='possibly_submitted' if submitted else 'not_submitted',
        terminal_proof='absent', status='unknown' if submitted else 'failed',
        code='MODEL_DEADLINE_EXCEEDED', failure_kind='timeout',
        provider_should_retry=False,
        receipt={'deadline_at': deadline.astimezone(timezone.utc).isoformat(),
                 'runtime_unverified': True})


def _copy_result(result, receipt):
    return ProviderResultV1(
        provider=result.provider, operation_id=result.operation_id, phase=result.phase,
        submission=result.submission, terminal_proof=result.terminal_proof,
        status=result.status, code=result.code, failure_kind=result.failure_kind,
        http_status=result.http_status, provider_should_retry=result.provider_should_retry,
        retry_after_at=result.retry_after_at, retry_after_source=result.retry_after_source,
        receipt=receipt, version=result.version)


def _sanitize_non_success(result):
    if result.status.value == 'succeeded':
        return result
    receipt = {key:value for key,value in dict(result.receipt).items()
               if not any(token in key.lower() for token in ('path','ref','sha256','digest'))
               and key not in ('event_stream_size','final_output_size')}
    receipt['output_disposition'] = ('retained_unknown' if result.status.value == 'unknown'
                                     else 'discarded_failure')
    return _copy_result(result, receipt)


def run_codex_one_shot(profile: dict, prompt_source, workspace: Path, run_dir: Path,
                       operation_id: str, context: dict | None = None) -> ProviderResultV1:
    """Execute v2 from a byte source/PromptLease; raw provider data stays in RAM."""
    _require(type(prompt_source) is bytes, 'MODEL_PROMPT_SOURCE_INVALID')
    context = context or {}
    _require(set(context) <= {'cancel_event','deadline_at','process_observer',
                              'strict_process_tree_containment'}, 'MODEL_CONTEXT_INVALID')
    started = datetime.now(timezone.utc)
    timeout = profile.get('timeout_seconds', 0) if isinstance(profile, dict) else 0
    deadline = context.get('deadline_at')
    if deadline is None:
        deadline = started + timedelta(seconds=timeout if type(timeout) in (int,float) and timeout > 0 else 1)
    _require(isinstance(deadline, datetime) and deadline.tzinfo is not None
             and deadline.utcoffset() is not None, 'MODEL_DEADLINE_INVALID')
    if deadline <= started:
        return _deadline_result(operation_id, deadline, submitted=False)
    artifacts = {}
    deadline_overrun = False

    def invoke():
        nonlocal deadline_overrun
        if context.get('cancel_event') is not None and context['cancel_event'].is_set():
            ended = datetime.now(timezone.utc)
            return NormalizedCodexRunnerEvidenceV1(
                NORMALIZED_SCHEMA, 'not_started', None, None, b'', 'events',
                hashlib.sha256(b'').hexdigest(), None, None, None,
                started, ended, deadline,
                {'category':'provider','authority':'not_submitted','http_status':None,
                 'provider_should_retry':True,'retry_after':None,'retry_after_source':None})
        legacy = _run_codex(profile, prompt_source, workspace, run_dir,
                            {**context, 'deadline_at':deadline}, legacy=False)
        ended = datetime.now(timezone.utc)
        deadline_overrun = ended > deadline
        artifacts.update(legacy.pop('_artifacts', {}))
        raw = legacy.pop('_events', b'')
        final_bytes = legacy.pop('_final_bytes', None)
        normalized = translate_codex_jsonl(raw, profile['model']) if raw else b''
        receipt = legacy.get('receipt', {})
        classification = _closed_classification(legacy)
        phase = 'submitted' if receipt.get('process_started') else 'not_started'
        if phase == 'not_started':
            classification['authority'] = 'not_submitted'
            if legacy.get('status') == 'retryable':
                classification['provider_should_retry'] = True
        return NormalizedCodexRunnerEvidenceV1(
            NORMALIZED_SCHEMA, phase, receipt.get('exit_code'), None, normalized, 'events',
            hashlib.sha256(normalized).hexdigest(), artifacts.get('final_ref') if final_bytes else None,
            hashlib.sha256(final_bytes).hexdigest() if final_bytes else None,
            len(final_bytes) if final_bytes else None, started, ended, deadline,
            classification)

    workspace = Path(workspace).resolve(strict=True)
    evidence_root = _private_path(Path(run_dir).parent, workspace, directory=True)
    result = normalize_codex_one_shot(operation_id=operation_id,
                                      expected_model=profile.get('model'),
                                      invocation_runner=invoke,
                                      file_resolver=FinalOutputResolver(evidence_root),
                                      configured_model_nonclaim=True)
    result = _with_model_binding_nonclaim(result)
    if deadline_overrun:
        result = _deadline_result(operation_id, deadline, submitted=True)
    final = artifacts.get('final_path')
    if result.status.value != 'unknown' and final is not None:
        try:
            final.unlink(missing_ok=True)
            _fsync_directory(final.parent)
        except OSError:
            result = ProviderResultV1(
                provider=result.provider, operation_id=result.operation_id,
                phase=result.phase, submission=result.submission, terminal_proof='absent',
                status='unknown', code='MODEL_OUTPUT_CLEANUP_UNCERTAIN',
                failure_kind='unknown', provider_should_retry=False,
                receipt=dict(result.receipt))
            return _sanitize_non_success(result)
    return _sanitize_non_success(result)


def run_codex(profile: dict, prompt: str | bytes, workspace: Path, run_dir: Path,
              context: dict | None = None) -> dict:
    """Legacy v1 API; strings are encoded and still travel only through stdin PIPE."""
    result = _run_codex(profile, prompt, workspace, run_dir, context, legacy=True)
    result.pop('_events', None)
    result.pop('_final_bytes', None)
    result.pop('_artifacts', None)
    return result


def _run_codex(profile, prompt_source, workspace, run_dir, context=None, *, legacy):
    receipt = {'requested_model': profile.get('model') if isinstance(profile, dict) else None,
               'observed_model': None, 'automatic_retry': False, 'fallback_used': False}
    fd = None
    try:
        workspace = Path(workspace).resolve(strict=True)
        _, home, _, _ = _profile(profile, workspace)
        lock = _private_path(home / 'runtime.lock', workspace)
        lock_flags = os.O_RDWR | os.O_NOFOLLOW
        try:
            fd = os.open(lock, lock_flags | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            fd = os.open(lock, lock_flags)
        else:
            try:
                os.fchmod(fd, 0o600)
            except BaseException:
                os.close(fd)
                fd = None
                raise
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status':'retryable','code':'MODEL_AUTH_CACHE_BUSY','receipt':receipt}
        return _run_codex_locked(profile, prompt_source, workspace, run_dir, context,
                                 lock_fd=fd, legacy=legacy)
    except ModelError as error:
        return {'status':'failed','code':str(error),'receipt':receipt}
    except Exception:
        return {'status':'unknown','code':'MODEL_ADAPTER_FAILED','receipt':receipt}
    finally:
        if fd is not None:
            os.close(fd)


def _run_codex_locked(profile, prompt_source, workspace: Path, run_dir: Path,
                       context: dict | None = None, *, lock_fd: int, legacy: bool) -> dict:
    """Invoke one configured Codex process with anonymous, bounded pipes."""
    receipt = {'started_at':datetime.now(timezone.utc).isoformat(),
               'requested_model':profile.get('model') if isinstance(profile,dict) else None,
               'observed_model':None,'automatic_retry':False,'fallback_used':False}
    process = None
    created = False
    final = None
    run_fd = None
    try:
        binary, home, timeout, maximum = _profile(profile, workspace)
        context = context or {}
        run_target = Path(os.path.abspath(os.fspath(run_dir)))
        evaluation_root = Path(os.path.abspath(
            os.fspath(workspace / '.job-runtime' / 'evaluations')))
        if run_target.is_relative_to(evaluation_root):
            raise ModelError('MODEL_STRICT_PROCESS_TREE_CONTAINMENT_UNAVAILABLE')
        allowed = {'response_schema','cancel_event','process_observer',
                   'strict_process_tree_containment','deadline_at'}
        _require(set(context) <= allowed, 'MODEL_CONTEXT_INVALID')
        _require(context.get('process_observer') is None or callable(context['process_observer']),
                 'MODEL_PROCESS_OBSERVER_INVALID')
        _require(type(context.get('strict_process_tree_containment',False)) is bool,
                 'MODEL_STRICT_PROCESS_TREE_CONTAINMENT_INVALID')
        if profile.get('strict_process_tree_containment',False) or context.get('strict_process_tree_containment',False):
            raise ModelError('MODEL_STRICT_PROCESS_TREE_CONTAINMENT_UNAVAILABLE')
        if context.get('cancel_event') is not None and context['cancel_event'].is_set():
            return {'status':'retryable','code':'MODEL_CANCELLED_BEFORE_START','receipt':receipt}
        run_dir = _private_path(run_dir, workspace)
        _require(not run_dir.exists(), 'MODEL_RUN_DIRECTORY_EXISTS')
        chunks, expected_hash, expected_length = _prompt_chunks(prompt_source, legacy=legacy)
        run_dir = _private_path(run_dir, workspace, directory=True)
        created = True
        directory_flags = (os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
                           | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0))
        run_fd = os.open(run_dir, directory_flags)
        run_details = os.fstat(run_fd)
        _require(stat.S_ISDIR(run_details.st_mode) and run_details.st_uid == os.getuid()
                 and stat.S_IMODE(run_details.st_mode) == 0o700,
                 'MODEL_RUN_DIRECTORY_UNSAFE')
        env = _environment(workspace, home, run_dir)
        env['RUST_LOG'] = 'off'
        final = run_dir / 'last-message.txt'
        final_fd = os.open(final.name,
                           os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600,
                           dir_fd=run_fd)
        try:
            os.fchmod(final_fd, 0o600)
        finally:
            os.close(final_fd)
        cmd = [str(binary),'exec','--ignore-user-config','--ephemeral','--strict-config',
               '--json','--color','never','--sandbox','read-only','--cd',str(workspace),
               '--model',profile['model'],'--output-last-message',str(final)]
        overrides = {'approval_policy':'never','model_reasoning_effort':profile['effort'],
                     'request_max_retries':0,'stream_max_retries':0,
                     'web_search':'disabled','features.shell_tool':False,
                     'features.shell_snapshot':False,'apps._default.enabled':False,
                     'mcp_servers':{},'cli_auth_credentials_store':'file',
                     'sqlite_home':env['CODEX_SQLITE_HOME'],'history.persistence':'none',
                     'check_for_update_on_startup':False}
        for key,value in overrides.items():
            cmd += ['-c',key+'='+json.dumps(value)]
        if 'response_schema' in context:
            _require(isinstance(context['response_schema'],dict),'MODEL_SCHEMA_INVALID')
            schema = run_dir/'response-schema.json'
            _write(schema,json.dumps(context['response_schema']))
            cmd += ['--output-schema',str(schema)]
        cmd += ['-']
        child_permissions = {'umask':0o077} if os.name == 'posix' else {}
        process = subprocess.Popen(cmd,cwd=workspace,env=env,stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                   start_new_session=True,pass_fds=(lock_fd,),
                                   **child_permissions)
        receipt['process_started'] = True
        observer = context.get('process_observer')
        if observer is not None:
            try:
                observer(process.pid)
            except Exception:
                _terminate(process)
                raise ModelError('MODEL_PROCESS_OBSERVER_FAILED') from None
        absolute = context.get('deadline_at')
        monotonic_deadline = time.monotonic()+timeout
        if absolute is not None:
            remaining = (absolute-datetime.now(timezone.utc)).total_seconds()
            monotonic_deadline = min(monotonic_deadline,time.monotonic()+max(0,remaining))
        transport = pump(process,chunks,deadline=monotonic_deadline,maximum=maximum,
                         cancel_event=context.get('cancel_event'),terminate=_terminate,
                         final_path=final)
        receipt.update(ended_at=datetime.now(timezone.utc).isoformat(),exit_code=process.returncode)
        reason = transport.reason
        if (reason is None and (not transport.source_complete
                or transport.source_length != expected_length
                or transport.source_sha256 != expected_hash)):
            reason = 'MODEL_PROMPT_BINDING_MISMATCH'
        parsed = _parse(transport.stdout)
        receipt.update(observed_model=parsed['observed_model'],thread_id=parsed['thread_id'],
                       usage=parsed['usage'],turn_completed=parsed['completed'])
        artifacts = {'final_path':final,
                     'final_ref':f'{run_dir.name}/last-message.txt'}
        final_bytes = _read_private_output(run_fd, run_dir, final.name, maximum)
        base = {'receipt':receipt,'_events':transport.stdout,'_artifacts':artifacts,
                '_final_bytes':final_bytes}
        if reason:
            return {'status':'unknown','code':reason,**base}
        if parsed['tool_activity']:
            return {'status':'failed','code':'MODEL_TOOL_POLICY_VIOLATION',**base}
        if parsed['observed_model'] is not None and parsed['observed_model'] != profile['model']:
            return {'status':'failed','code':'MODEL_IDENTITY_MISMATCH',**base}
        if process.returncode == 0 and parsed['completed'] and not parsed['failures'] and not parsed['parse_errors']:
            _require(final_bytes is not None and bool(final_bytes.strip()),'MODEL_FINAL_RESPONSE_MISSING')
            if 'response_schema' in context:
                json.loads(final_bytes)
            if legacy:
                receipt.update(run_directory=str(run_dir.relative_to(workspace)),
                               response_path=str(final.relative_to(workspace)),
                               response_sha256=hashlib.sha256(final_bytes).hexdigest())
            return {'status':'succeeded','code':'MODEL_TURN_COMPLETED',**base}
        status,code = _classify(parsed['messages']+[transport.stderr.decode(errors='replace')],process.returncode)
        return {'status':status,'code':code,**base}
    except ModelError as error:
        return {'status':'failed','code':str(error),'receipt':receipt}
    except Exception:
        if process is not None and process.poll() is None:
            _terminate(process)
        return {'status':'unknown','code':'MODEL_ADAPTER_FAILED','receipt':receipt}
    except BaseException:
        if process is not None:
            _terminate(process)
        raise
    finally:
        if process is not None:
            for pipe in (process.stdin,process.stdout,process.stderr):
                if pipe is not None and not pipe.closed:
                    pipe.close()
        if run_fd is not None:
            os.close(run_fd)
        if process is None and created:
            shutil.rmtree(run_dir,ignore_errors=True)
