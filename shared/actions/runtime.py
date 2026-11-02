"""Small action catalog, schema boundary and bounded child-process client."""
from __future__ import annotations

from datetime import datetime, timezone
import types
from importlib.metadata import version as package_version
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from jsonschema import Draft202012Validator, FormatChecker
from shared.research_sources import fetch
from shared.job_runtime.business import _stream
from shared.research_sources.artifacts import ROOT, SourceError, digest, encoded, private_path, read, save

SOURCE_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = Path(__file__).with_name('contracts.json')
LEGACY = SOURCE_ROOT / 'niulai/skills/investment-research-financial-services/references/niulai-workflow/scripts/evidence_crosscheck.py'
MAX_REQUEST_BYTES = 1024 * 1024
FROZEN_CONTEXT = None
_PROCESS_TYPE = subprocess.Popen


class ActionError(ValueError):
    """Fixed non-content diagnostic; no raw provider exception text."""


SPECS = {
    'evidence.acquire_document': {'version': '1.1.1', 'lifecycle': 'active', 'input_schema': 'Acquire', 'output_schema': 'AcquireResult',
        'effects': ['remote_read', 'local_artifact_write'], 'retry_owner': 'source_adapter',
        'capability': 'document.read', 'limits': 'Existing allowlisted HTML routes; no PDF/table extraction or truth certification.'},
    'evidence.read': {'version': '1.1.1', 'lifecycle': 'active', 'input_schema': 'Read', 'output_schema': 'ReadResult',
        'effects': ['local_read'], 'retry_owner': 'none', 'capability': 'evidence.read',
        'limits': 'Bounded exact text offsets from a hash-verified document receipt.'},
    'evidence.compare_numeric': {'version': '1.1.1', 'lifecycle': 'active', 'input_schema': 'Compare', 'output_schema': 'ComparisonResult',
        'effects': ['pure'], 'retry_owner': 'none', 'capability': 'numeric.compare',
        'limits': 'Supplied observations only; source truth/independence remains a decision judgment.'},
}


def decode(raw):
    if not isinstance(raw, (str, bytes)) or len(raw if isinstance(raw, bytes) else raw.encode()) > MAX_REQUEST_BYTES:
        raise ActionError('ACTION_JSON_TOO_LARGE')
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ActionError('ACTION_DUPLICATE_KEY')
            out[key] = value
        return out
    def invalid(_):
        raise ActionError('ACTION_NONFINITE_NUMBER')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        raise ActionError('ACTION_JSON_INVALID') from None


def validate(name, value, *, registry=None):
    # Schemas come only from this packaged local registry; no external retrieval.
    schemas = decode(CONTRACTS.read_bytes()) if registry is None else registry
    schema = {'$schema': schemas['$schema'], '$defs': schemas['$defs'], '$ref': '#/$defs/' + name}
    try:
        encoded(value)  # reject NaN/Infinity even for Python callers
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except (ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, ActionError):
            raise
        raise ActionError('ACTION_' + name.upper() + '_INVALID') from None
    except Exception as exc:
        # jsonschema ValidationError/SchemaError intentionally do not leak input.
        raise ActionError('ACTION_' + name.upper() + '_INVALID') from None


def registry(*, include_retired=False):
    return [dict(action_id=key, **json.loads(json.dumps(value))) for key, value in SPECS.items()
            if include_retired or value['lifecycle'] == 'active']


def environment_manifest():
    import hashlib
    executable = Path(sys.executable).resolve(strict=True)
    return {'python_version': sys.version, 'python_executable': str(executable),
            'python_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'jsonschema_version': package_version('jsonschema'),
            'rfc3339_validator_version': package_version('rfc3339-validator')}


def manifest():
    import hashlib
    if FROZEN_CONTEXT is not None:
        value = json.loads(json.dumps(FROZEN_CONTEXT['manifest']))
        value['files'] = {relative: hashlib.sha256((SOURCE_ROOT / relative).read_bytes()).hexdigest()
                          for relative in value['files']}
        value['environment'] = environment_manifest()
        return value
    paths = [*Path(__file__).parent.glob('*.py'), CONTRACTS,
             ROOT / 'shared/research_sources/fetch.py', ROOT / 'shared/research_sources/artifacts.py',
             ROOT / 'shared/research_sources/requirements.txt',
             ROOT / 'shared/job_runtime/business.py', ROOT / 'shared/job_runtime/model.py', LEGACY]
    files = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    return {'schema_version': 1, 'files': files, 'environment': environment_manifest(),
        'guarantee': 'working_tree_pre_and_post_integrity; no immutable in_flight_bundle or adversarial isolation'}


def resolve(selector, *, release_ref=None):
    if release_ref is not None:
        from .releases import resolve_frozen
        return resolve_frozen(selector, release_ref)
    if not isinstance(selector, str) or '@' not in selector:
        raise ActionError('ACTION_SELECTOR_INVALID')
    action_id, version = selector.rsplit('@', 1)
    spec = SPECS.get(action_id)
    if spec is None:
        raise ActionError('ACTION_NOT_REGISTERED')
    if spec['lifecycle'] != 'active':
        raise ActionError('ACTION_RETIRED')
    if version not in ('1', spec['version']):
        raise ActionError('ACTION_VERSION_UNAVAILABLE')
    if FROZEN_CONTEXT is not None and FROZEN_CONTEXT['manifest']['action'] != {'action_id': action_id, 'version': spec['version']}:
        raise ActionError('ACTION_RELEASE_ACTION_MISMATCH')
    release = manifest()
    return dict(action_id=action_id, **spec, release_sha256=digest(release), release_manifest=release)


def artifact_json(ref):
    validate('ArtifactRef', ref)
    return decode(read(ref, json_value=False))


def source_receipt(ref):
    receipt = artifact_json(ref)
    validate('SourceReceipt', receipt)
    read(receipt['raw'], json_value=False)
    read(receipt['text'], json_value=False).decode('utf-8')
    return receipt


def _numeric(packet):
    # Explicit single registered dependency; no model-selected module/import path.
    module = types.ModuleType('_registered_evidence_crosscheck')
    module.__file__ = str(LEGACY)
    exec(compile(LEGACY.read_bytes(), str(LEGACY), 'exec'), module.__dict__)
    try:
        return module.calculate(packet)
    except (module.CrosscheckError, ValueError, TypeError, KeyError):
        raise ActionError('ACTION_COMPARISON_INPUT_INVALID') from None


def _run(action_id, arguments, directory):
    if action_id == 'evidence.acquire_document':
        ref = (fetch.fetch_arxiv(arguments['value'], directory) if arguments['kind'] == 'arxiv'
               else fetch.fetch_document(arguments['value'], directory))
        source_receipt(ref)
        return {'source_ref': ref}
    if action_id == 'evidence.read':
        source_receipt(arguments['source_ref'])
        return {'source_ref': arguments['source_ref'], 'passage': fetch.passages(arguments['source_ref'],
            arguments.get('start', 0), arguments.get('max_chars', 6000))}
    if action_id == 'evidence.compare_numeric':
        return _numeric(artifact_json(arguments['packet_ref']))
    raise ActionError('ACTION_NOT_REGISTERED')


def dispatch(request, *, output_directory):
    """Execute one registered action; use invoke() for an enforced wall deadline.

    There is no generic retry loop. Domain disagreement is a successful result.
    Local artifact side effects remain archived on failure and are not promoted
    as a successful result. Domain/Store mutation idempotency belongs to owners.
    """
    if isinstance(request, dict) and request.get('release_ref') is not None and FROZEN_CONTEXT is None:
        return invoke(request, output_directory=output_directory)
    directory = private_path(output_directory, create=True)
    started = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    release = None
    action_id = None
    execution_started = False
    try:
        validate('Request', request)
        if FROZEN_CONTEXT is not None and request.get('release_ref') != FROZEN_CONTEXT['release_ref']:
            raise ActionError('ACTION_RELEASE_REQUEST_MISMATCH')
        release = resolve(request['action'])
        action_id = release['action_id']
        if request.get('expected_release_sha256', release['release_sha256']) != release['release_sha256']:
            raise ActionError('ACTION_RELEASE_MISMATCH')
        validate(release['input_schema'], request['arguments'])
        execution_started = True
        data = _run(action_id, request['arguments'], directory)
        validate(release['output_schema'], data)
        if digest(manifest()) != release['release_sha256']:
            raise ActionError('ACTION_RELEASE_CHANGED_DURING_EXECUTION')
        result = {'schema_version': 1, 'status': 'success', 'data': data, 'error': None}
    except (ActionError, SourceError) as exc:
        code = str(exc)
        if not code or len(code) > 120 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789' for c in code):
            code = 'ACTION_REJECTED'
        result = {'schema_version': 1, 'status': 'failure', 'data': None,
                  'error': {'code': code, 'effect_state': 'unknown' if execution_started else 'not_started',
                            'retryable': code in ('SOURCE_NETWORK_FAILED', 'SOURCE_HTTP_429', 'SOURCE_HTTP_503')}}
    except Exception:
        result = {'schema_version': 1, 'status': 'failure', 'data': None,
                  'error': {'code': 'ACTION_EXECUTION_FAILED', 'effect_state': 'unknown', 'retryable': False}}
    try:
        request_sha = digest(request)
    except (TypeError, ValueError, RecursionError):
        request_sha = None
    request_id = request.get('request_id') if isinstance(request, dict) else None
    if not isinstance(request_id, str) or len(request_id) > 128:
        request_id = None
    execution = {'schema_version': 1, 'request_id': request_id,
        'action_id': action_id, 'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
        'duration_ms': round((time.monotonic() - start) * 1000, 3), 'request_sha256': request_sha,
        'release_sha256': release['release_sha256'] if release else None,
        'release_manifest_ref': save(directory, release['release_manifest']) if release else None,
        'status': result['status'], 'error': result['error'], 'data_sha256': digest(result['data'])}
    result['execution_ref'] = save(directory, execution)
    validate('Outcome', result)
    return result


class _OwnedWorker:
    """Keep our session leader unreaped until its process group is cleaned.

    The shared pipe reader calls poll/wait only after EOF or during termination.
    Deferring reaping pins the leader PID, so cleanup cannot signal a later,
    unrelated process group that reused that number. This is process cleanup,
    not an OS sandbox: children that create a new session are outside this group.
    """
    def __init__(self, process):
        self.process = process
        self.reaped = False

    def __getattr__(self, name):
        return getattr(self.process, name)

    @property
    def pid(self):
        # The shared terminator may attempt one final group signal after wait.
        # Once reaped, never expose a PID that the OS is free to reuse.
        if self.reaped:
            raise ProcessLookupError
        return self.process.pid

    def poll(self):
        return self.process.returncode if self.reaped else None

    def wait(self, timeout=None):
        if not self.reaped:
            # Before wait() reaps the leader, every process in this session's
            # original group still belongs to this invocation. A worker closing
            # its pipes while continuing work is stopped rather than accepted.
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                # Darwin reports EPERM for a group with only an exited zombie
                # leader. Its exit status may arrive just after the signal; use
                # the bounded cleanup wait rather than a racy zero-time poll.
                # An active unsignalable worker still fails cleanup visibly.
                result = self.process.wait(timeout=2 if timeout is None else min(timeout, 2))
                self.reaped = True
                return result
            try:
                return self.process.wait(timeout=timeout)
            finally:
                self.reaped = self.process.returncode is not None
        return self.process.returncode


def invoke(request, *, output_directory, timeout_seconds=45, max_output_bytes=1024 * 1024):
    """Controlled subprocess boundary with process-group cleanup and no retries."""
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 120:
        raise ActionError('ACTION_TIMEOUT_INVALID')
    if type(max_output_bytes) is not int or not 1024 <= max_output_bytes <= 8 * 1024 * 1024:
        raise ActionError('ACTION_OUTPUT_LIMIT_INVALID')
    if not isinstance(request, dict):
        raise ActionError('ACTION_REQUEST_INVALID')
    directory = private_path(output_directory, create=True)
    frozen = None
    frozen_schemas = None
    if request.get('release_ref') is not None:
        from .releases import verify_release
        frozen = verify_release(request['release_ref'], selector=request.get('action'))
        frozen_schemas = decode((Path(frozen['bundle_directory']) / 'shared/actions/contracts.json').read_bytes())
        validate('Request', request, registry=frozen_schemas)
        if request.get('expected_release_sha256', digest(frozen['manifest'])) != digest(frozen['manifest']):
            raise ActionError('ACTION_RELEASE_MISMATCH')
        selected = frozen['descriptor']
    else:
        validate('Request', request)
        selected = resolve(request['action'])
        if request.get('expected_release_sha256', selected['release_sha256']) != selected['release_sha256']:
            raise ActionError('ACTION_RELEASE_MISMATCH')
    validate(selected['input_schema'], request['arguments'], registry=frozen_schemas)
    envelope = encoded({'request': request, 'output_directory': str(directory)})
    if len(envelope) > MAX_REQUEST_BYTES:
        raise ActionError('ACTION_JSON_TOO_LARGE')
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'LANG', 'SSL_CERT_FILE', 'SSL_CERT_DIR') if k in os.environ}
    tmp = private_path(directory / 'worker-tmp', create=True)
    env.update(PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(tmp), PYTHONPATH=str(ROOT))
    command = [sys.executable, '-B', '-m', 'shared.actions', 'worker']
    if frozen is not None:
        command = [sys.executable, '-I', '-B', str(Path(frozen['bundle_directory']) / 'shared/actions/frozen_worker.py'),
                   request['release_ref']['path'], request['release_ref']['sha256'], str(ROOT)]
    p = subprocess.Popen(command, cwd=ROOT, env=env,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    # Injected protocol transports need not own an OS process. Real Popen
    # instances always use the unreaped-leader guard before the pipe reader.
    worker = _OwnedWorker(p) if isinstance(p, _PROCESS_TYPE) else p
    started = datetime.now(timezone.utc).isoformat()
    stream_started = time.monotonic()
    out, err, reason = b'', b'', None
    try:
        out, err, reason = _stream(worker, envelope, timeout_seconds, max_output_bytes, None)
    except Exception:
        out, err = b'', b''
        reason = ('BUSINESS_DEADLINE_EXCEEDED' if time.monotonic() - stream_started >= timeout_seconds
                  else 'ACTION_STREAM_FAILED')
    finally:
        if isinstance(worker, _OwnedWorker):
            try:
                worker.wait(timeout=2)
            except Exception:
                out, err = b'', b''
                if reason not in ('BUSINESS_DEADLINE_EXCEEDED', 'BUSINESS_OUTPUT_LIMIT_EXCEEDED'):
                    reason = 'ACTION_CLEANUP_FAILED'
            finally:
                for pipe in (p.stdin, p.stdout, p.stderr):
                    if pipe is not None and not pipe.closed:
                        pipe.close()
    if reason or p.returncode:
        code = ('ACTION_DEADLINE_EXCEEDED' if reason == 'BUSINESS_DEADLINE_EXCEEDED'
                else 'ACTION_OUTPUT_LIMIT_EXCEEDED' if reason == 'BUSINESS_OUTPUT_LIMIT_EXCEEDED'
                else 'ACTION_WORKER_FAILED')
        execution = save(directory, {'schema_version': 1, 'status': 'failure', 'code': code,
            'effect_state': 'unknown', 'started_at': started,
            'finished_at': datetime.now(timezone.utc).isoformat(), 'request_sha256': digest(request),
            'worker_exit_code': p.returncode, 'raw_response_archived': False})
        return {'schema_version': 1, 'status': 'failure', 'data': None, 'execution_ref': execution,
                'error': {'code': code, 'effect_state': 'unknown', 'retryable': False}}
    result = decode(out)
    validate('Outcome', result, registry=frozen_schemas)
    if frozen is not None:
        from .releases import verify_release
        verify_release(request['release_ref'], selector=request['action'])
    if result['execution_ref'] is None:
        raise ActionError('ACTION_WORKER_RECEIPT_MISMATCH')
    if result['execution_ref'] is not None:
        validate('ArtifactRef', result['execution_ref'], registry=frozen_schemas)
        receipt = decode(read(result['execution_ref'], json_value=False))
        if (receipt.get('request_sha256') != digest(request) or receipt.get('status') != result['status']
                or receipt.get('data_sha256') != digest(result['data'])
                or receipt.get('error') != result['error']
                or receipt.get('action_id') != selected['action_id']
                or receipt.get('release_sha256') !=
                    (digest(frozen['manifest']) if frozen is not None else selected['release_sha256'])):
            raise ActionError('ACTION_WORKER_RECEIPT_MISMATCH')
    if result['status'] == 'success':
        validate(selected['output_schema'], result['data'], registry=frozen_schemas)
    return result
