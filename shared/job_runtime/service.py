"""launchd-managed shared scheduler; no business-specific imports or sends."""
from datetime import datetime, timezone
import argparse
import base64
import copy
import fcntl
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import sys
import secrets
import threading
from types import MappingProxyType
import time

from .config import load, inside, ConfigError, _prompt_snapshot
from .engine import Engine
from .model import CODEX_TRANSLATION_CAPABILITY, run_codex, run_codex_one_shot
from .claude_bridge import CLAUDE_BRIDGE_CAPABILITY, run_claude_host
from .provider_contract import ProviderResultV1
from .prompt_custody import (
    CapturedPromptV1, PromptArtifactDescriptorV1, PromptArtifactStore,
    PromptCustodyError, PromptLease,
)
from .retry_policy import validate_retry_policy

_SERVICE_SOURCE = Path(__file__).resolve()
_SERVICE_SOURCE_DIGEST = globals().get('_EXECUTED_SOURCE_SHA256')
# Only an exact-loaded service may claim and require an exact-loaded business
# implementation. Ordinary library imports remain usable but unattested.
if _SERVICE_SOURCE_DIGEST is not None:
    from shared.exact_source import load_exact as _load_exact
    _load_exact(__package__ + '.business', _SERVICE_SOURCE.with_name('business.py'))
    del _load_exact
from .business import IMPLEMENTATION_SHA256 as _BUSINESS_IMPLEMENTATION_SHA256
from .business import GMAIL, run_business, _validate_gmail_claim, _consume_gmail_claim

STOP = threading.Event()
RELOAD = threading.Event()
SERVICE_PROTOCOL_VERSION = 2
RUNTIME_CONTEXT_VERSIONS = (1, 2, 3)
_PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()
_ADAPTER_GENERATIONS = {}
_ADAPTER_UNKNOWN_GENERATIONS = set()
_ADAPTER_IMPORT_LOCK = threading.RLock()
_GMAIL_CLAIM_LOCK = threading.Lock()
_GMAIL_CLAIMS = {}
_IMPLEMENTATION_PATHS = {
    'business': _SERVICE_SOURCE.with_name('business.py'),
    'delivery': _SERVICE_SOURCE.parents[2]/'niulai-runtime/niulai_runtime/delivery.py',
}
_PROVIDER_IMPLEMENTATION_PATHS = {
    'model': _SERVICE_SOURCE.with_name('model.py'),
    'provider_codex_cli': _SERVICE_SOURCE.with_name('providers')/'codex_cli.py',
    'provider_claude_host': _SERVICE_SOURCE.with_name('providers')/'claude_host.py',
    'claude_bridge': _SERVICE_SOURCE.with_name('claude_bridge.py'),
}
_IMPLEMENTATION_HASHES = {
    'business': _BUSINESS_IMPLEMENTATION_SHA256,
    'delivery': (hashlib.sha256(_IMPLEMENTATION_PATHS['delivery'].read_bytes()).hexdigest()
                 if _IMPLEMENTATION_PATHS['delivery'].is_file() else None),
}
_PROVIDER_IMPLEMENTATION_HASHES = {
    k: hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    for k,p in _PROVIDER_IMPLEMENTATION_PATHS.items()}
_DISPATCH_STATUSES = frozenset({'succeeded', 'retryable', 'failed', 'unknown'})
_DISPATCH_CODE = re.compile(r'[A-Z][A-Z0-9_]{0,95}')
_MAX_ADAPTER_SOURCE = 4 * 1024 * 1024
_MAX_ADAPTER_RECEIPT = 65536
_MAX_RECEIPT_DEPTH = 64
_MAX_RECEIPT_NODES = 4096


class AdapterImportOutcomeUnknown(RuntimeError):
    """Adapter module execution began but did not complete deterministically."""


def _code_generation():
    """Stable identity for prompt custody; never bind process-instance data."""
    source_hashes = {
        'service': _SERVICE_SOURCE_DIGEST,
        'implementations': dict(_IMPLEMENTATION_HASHES),
        'provider_implementations': dict(_PROVIDER_IMPLEMENTATION_HASHES),
    }
    return hashlib.sha256(json.dumps(
        source_hashes, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()


def service_generation():
    """Return a bounded receipt for code loaded by this process."""
    return {
        'code_generation': _code_generation(),
        'implementations': dict(_IMPLEMENTATION_HASHES),
        'provider_implementations': dict(_PROVIDER_IMPLEMENTATION_HASHES),
        'pid': os.getpid(),
        'started_at': _PROCESS_STARTED_AT,
        'python': {'executable': str(Path(sys.executable).resolve()), 'version': platform.python_version()},
        'service': {
            'protocol_version': SERVICE_PROTOCOL_VERSION,
            'origin': 'shared/job_runtime/service.py',
            'source_sha256': _SERVICE_SOURCE_DIGEST,
        },
    }


def validate_reload(engine, jobs):
    """Reject changed persisted schedules before replacing the working engine."""
    import hashlib
    with engine._db() as db:
        for job in jobs:
            if not job['enabled']:
                continue
            row = db.execute('SELECT schedule_hash FROM jobs WHERE job_id=?', (job['id'],)).fetchone()
            observed = hashlib.sha256(json.dumps(job['schedule'], sort_keys=True).encode()).hexdigest()
            if row and row['schedule_hash'] != observed:
                raise ConfigError('SCHEDULE_CHANGE_REQUIRES_NEW_JOB_ID')


def _open_parent_held(path):
    """Return a held no-follow parent dirfd and all descriptors keeping it stable."""
    path = Path(path)
    descriptors = [os.open(path.anchor if path.is_absolute() else '.',
                           os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))]
    components = path.parts[1:] if path.is_absolute() else path.parts
    completed = False
    try:
        root_info = os.fstat(descriptors[0])
        if (not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid not in (0, os.getuid()) or
                root_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise OSError('untrusted directory')
        if not components or components[-1] in ('', '.', '..'):
            raise OSError('invalid path')
        for component in components[:-1]:
            if component in ('', '.', '..'):
                raise OSError('invalid path')
            descriptors.append(os.open(
                component, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
                getattr(os, 'O_NOFOLLOW', 0), dir_fd=descriptors[-1]))
            info = os.fstat(descriptors[-1])
            if (info.st_uid not in (0, os.getuid()) or
                    info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
                raise OSError('untrusted directory')
        completed = True
        return descriptors[-1], components[-1], descriptors
    finally:
        if not completed:
            for descriptor in reversed(descriptors):
                os.close(descriptor)


def atomic(path, value):
    """Atomically publish private JSON relative to one trusted held directory."""
    parent = None
    descriptors = []
    temporary = None
    try:
        parent, target, descriptors = _open_parent_held(path)
        encoded = json.dumps(value, sort_keys=True).encode()
        for _ in range(32):
            temporary = '.atomic-' + secrets.token_hex(12)
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                     getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=parent)
                break
            except FileExistsError:
                continue
        else:
            raise ConfigError('ATOMIC_TEMP_UNAVAILABLE')
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target, src_dir_fd=parent, dst_dir_fd=parent)
        temporary = None
        os.fsync(parent)
    except OSError:
        raise ConfigError('ATOMIC_PATH_INVALID') from None
    finally:
        if temporary is not None and parent is not None:
            try:
                os.unlink(temporary, dir_fd=parent)
            except OSError:
                pass
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _source_snapshot(path):
    """Read one source inode while holding no-follow descriptors for its ancestry."""
    descriptor = None
    descriptors = []
    try:
        parent, leaf, descriptors = _open_parent_held(path)
        descriptor = os.open(leaf, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0), dir_fd=parent)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & (stat.S_IWGRP|stat.S_IWOTH) or
                not 0 < info.st_size <= _MAX_ADAPTER_SOURCE):
            raise ConfigError('ADAPTER_SOURCE_INVALID')
        chunks=[];remaining=info.st_size
        while remaining:
            chunk=os.read(descriptor,min(131072,remaining))
            if not chunk:raise ConfigError('ADAPTER_SOURCE_INVALID')
            chunks.append(chunk);remaining-=len(chunk)
        after = os.fstat(descriptor)
        if ((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns) !=
                (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)):
            raise ConfigError('ADAPTER_SOURCE_INVALID')
        return b''.join(chunks),(info.st_dev,info.st_ino)
    except OSError:
        raise ConfigError('ADAPTER_SOURCE_INVALID') from None
    finally:
        if descriptor is not None:os.close(descriptor)
        for held in reversed(descriptors):os.close(held)


def _load_exact_source(name, path, source):
    """Execute the attested source bytes directly; timestamp-valid pyc is irrelevant."""
    parent_name, _, child = name.rpartition('.')
    parent = importlib.import_module(parent_name) if parent_name else None
    # A package initializer can import the requested child as a side effect.  Its
    # top-level outcome is then unobservable here; never execute that child twice.
    if parent_name and name in sys.modules:
        raise AdapterImportOutcomeUnknown
    is_package = path.name == '__init__.py'
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)] if is_package else None)
    if spec is None:raise ConfigError('ADAPTER_SOURCE_INVALID')
    try:
        code=compile(source,str(path),'exec',dont_inherit=True)
    except (SyntaxError,ValueError,OverflowError):
        raise ConfigError('ADAPTER_SOURCE_INVALID') from None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(code,module.__dict__)
        if parent is not None:setattr(parent,child,module)
        return module
    except Exception:
        sys.modules.pop(name,None)
        if parent is not None and getattr(parent,child,None) is module:delattr(parent,child)
        raise AdapterImportOutcomeUnknown from None
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        sys.modules.pop(name,None)
        if parent is not None and getattr(parent,child,None) is module:delattr(parent,child)
        raise


def adapter_module(name, config, workspace):
    workspace=Path(workspace).resolve(strict=True)
    relative=Path(*name.split('.'))
    roots=[workspace,*[inside(workspace/x,workspace) for x in config['source_paths']]]
    candidates=[p for root in roots for p in (root/relative.with_suffix('.py'),root/relative/'__init__.py') if p.is_file()]
    if len(candidates)!=1:raise ConfigError('ADAPTER_SOURCE_NOT_UNIQUE')
    expected=inside(candidates[0],workspace).resolve()
    with _ADAPTER_IMPORT_LOCK:
        # Reject a previously loaded package from a different origin before use.
        for i in range(1,len(name.split('.'))+1):
            parent='.'.join(name.split('.')[:i]);loaded=sys.modules.get(parent)
            if loaded is not None and getattr(loaded,'__file__',None):
                try:loaded_origin=inside(Path(loaded.__file__).resolve(),workspace).resolve()
                except (OSError,ValueError):raise ConfigError('ADAPTER_ORIGIN_MISMATCH') from None
                if parent==name and loaded_origin!=expected:raise ConfigError('ADAPTER_ORIGIN_MISMATCH')
        source,identity=_source_snapshot(expected)
        digest=hashlib.sha256(source).hexdigest()
        key=(name,str(expected));previous=_ADAPTER_GENERATIONS.get(key)
        if key in _ADAPTER_UNKNOWN_GENERATIONS:
            raise AdapterImportOutcomeUnknown
        if previous is not None:
            if previous['source_sha256']!=digest:raise ConfigError('ADAPTER_LOADED_SOURCE_STALE')
            imported=sys.modules.get(name)
            if imported is None:raise ConfigError('ADAPTER_GENERATION_MISSING')
            return imported
        if name in sys.modules:
            # Never execute a module loaded through timestamp-based bytecode or an
            # unobserved loader. Replace it with the exact source snapshot below.
            stale=sys.modules.pop(name)
            parent_name,_,child=name.rpartition('.')
            parent=sys.modules.get(parent_name) if parent_name else None
            if parent is not None and getattr(parent,child,None) is stale:
                delattr(parent,child)
        try:
            imported=_load_exact_source(name,expected,source)
        except AdapterImportOutcomeUnknown:
            _ADAPTER_UNKNOWN_GENERATIONS.add(key)
            raise
        current,current_identity=_source_snapshot(expected)
        if current_identity!=identity or current!=source:
            sys.modules.pop(name,None)
            _ADAPTER_UNKNOWN_GENERATIONS.add(key)
            raise ConfigError('ADAPTER_SOURCE_CHANGED_DURING_IMPORT')
        _ADAPTER_GENERATIONS[key]={
            'origin':expected.relative_to(workspace).as_posix(),'source_sha256':digest}
        return imported


def adapter_generation(imported, name, workspace):
    workspace=Path(workspace).resolve(strict=True)
    origin=inside(Path(imported.__file__).resolve(),workspace).resolve()
    generation=_ADAPTER_GENERATIONS.get((name,str(origin)))
    if generation is None:raise ConfigError('ADAPTER_GENERATION_MISSING')
    return dict(generation)


def _immutable(value):
    if isinstance(value,dict):return MappingProxyType({k:_immutable(v) for k,v in value.items()})
    if isinstance(value,list):return tuple(_immutable(v) for v in value)
    return value


def _bounded_json(value, *, require_dict=False):
    """Encode bounded acyclic JSON without recursive traversal before validation."""
    if require_dict and not isinstance(value, dict):
        return None
    stack = [(value, 0)]
    containers = set()
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_RECEIPT_NODES or depth > _MAX_RECEIPT_DEPTH:
            return None
        if isinstance(current, dict):
            identity = id(current)
            if identity in containers:
                return None
            containers.add(identity)
            for key, child in current.items():
                if not isinstance(key, str):
                    return None
                stack.append((child, depth + 1))
        elif isinstance(current, (list, tuple)):
            identity = id(current)
            if identity in containers:
                return None
            containers.add(identity)
            stack.extend((child, depth + 1) for child in current)
        elif current is not None and not isinstance(current, (str, int, float, bool)):
            return None
    try:
        encoded=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
    except (TypeError,ValueError,RecursionError):
        return None
    if len(encoded.encode('utf-8')) > _MAX_ADAPTER_RECEIPT:
        return None
    try:
        return encoded, json.loads(encoded)
    except (ValueError, RecursionError):
        return None


def _terminal_adapter_result(value):
    if not isinstance(value,dict) or 'status' not in value or set(value)-{'status','code','receipt'}:
        return None
    if value['status'] not in _DISPATCH_STATUSES:
        return None
    code=value.get('code')
    if code is not None and (not isinstance(code,str) or not _DISPATCH_CODE.fullmatch(code)):
        return None
    receipt=value.get('receipt')
    bounded=_bounded_json(receipt,require_dict=True) if receipt is not None else None
    if receipt is not None and bounded is None:return None
    # Return detached JSON data so an adapter cannot mutate scheduler state after
    # validation through an aliased receipt object.
    checked={'status':value['status']}
    if code is not None:checked['code']=code
    if bounded is not None:checked['receipt']=bounded[1]
    return checked


def _completion_adapter_result(value):
    """Return detached, bounded host-verification data with an exact schema."""
    if (not isinstance(value, dict) or set(value) - {'verified', 'code', 'receipt'} or
            'verified' not in value or type(value['verified']) is not bool):
        return None
    code = value.get('code')
    if code is not None and (not isinstance(code, str) or not _DISPATCH_CODE.fullmatch(code)):
        return None
    receipt = value.get('receipt')
    bounded = _bounded_json(receipt, require_dict=True) if receipt is not None else None
    if receipt is not None and bounded is None:
        return None
    checked = {'verified': value['verified']}
    if code is not None:
        checked['code'] = code
    if bounded is not None:
        checked['receipt'] = bounded[1]
    return checked


def _adapter_load_failure(error):
    code=str(error)
    if code=='ADAPTER_SOURCE_CHANGED_DURING_IMPORT':
        # Module top-level code may already have run before the post-import source
        # check detects a swap, so the effect boundary is unknown rather than a
        # proven pre-adapter failure.
        return {'status':'unknown','code':'RUNTIME_ADAPTER_SOURCE_CHANGED_DURING_IMPORT','receipt':{
            'generation_code':code,'service_generation':service_generation()}}
    if code=='ADAPTER_LOADED_SOURCE_STALE':
        public='RUNTIME_ADAPTER_GENERATION_STALE'
    elif code in ('ADAPTER_SOURCE_NOT_UNIQUE','ADAPTER_SOURCE_INVALID'):
        public='RUNTIME_ADAPTER_SOURCE_INVALID'
    elif code=='ADAPTER_ORIGIN_MISMATCH':
        public='RUNTIME_ADAPTER_ORIGIN_INVALID'
    else:
        public='RUNTIME_ADAPTER_LOAD_FAILED'
    return {'status':'failed','code':public,'receipt':{
        'generation_code':code,'service_generation':service_generation()}}


def _gmail_claim_for_dispatch(claim, job, context, generation, workspace):
    """Validate attestation without consuming the launch reservation."""
    checked=_validate_gmail_claim(claim,job_id=job['id'],context=context)
    if checked is None:return None,'RUNTIME_GMAIL_CLAIM_INVALID'
    service=service_generation()
    loaded_business=sys.modules.get(__package__+'.business')
    loaded_delivery=sys.modules.get('niulai_runtime.delivery')
    if (loaded_business is None or
            getattr(loaded_business,'IMPLEMENTATION_SHA256',None)!=_IMPLEMENTATION_HASHES['business'] or
            loaded_delivery is not None and
            getattr(loaded_delivery,'IMPLEMENTATION_SHA256',None)!=_IMPLEMENTATION_HASHES['delivery']):
        return None,'RUNTIME_GMAIL_IMPLEMENTATION_DRIFT'
    expected={'host':service['service']['source_sha256'],
              'run':hashlib.sha256(json.dumps(service,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
              'candidate':generation['source_sha256']}
    if any(checked[k]!=value for k,value in expected.items()):
        return None,'RUNTIME_GMAIL_CLAIM_ATTESTATION_MISMATCH'
    if any(not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=_IMPLEMENTATION_HASHES[k]
           for k,p in _IMPLEMENTATION_PATHS.items()):
        return None,'RUNTIME_GMAIL_IMPLEMENTATION_DRIFT'
    from .business import _check_gmail_claim
    code=_check_gmail_claim(workspace,checked,'business')
    if code:return None,code
    return _immutable(checked),None


def _typed_failure(provider, operation_id, code, *, unknown=False,
                   runtime_unverified=None):
    if runtime_unverified is None:
        runtime_unverified = provider == 'claude_host'
    return ProviderResultV1(
        provider=provider, operation_id=operation_id, phase='not_started' if not unknown else 'submitted',
        submission='not_submitted' if not unknown else 'possibly_submitted', terminal_proof='absent',
        status='failed' if not unknown else 'unknown', code=code,
        failure_kind='local_config' if not unknown else 'unknown',
        provider_should_retry=False,
        receipt={'runtime_unverified': runtime_unverified,
                 'service_generation_sha256': hashlib.sha256(json.dumps(
                     service_generation(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()})


def _codex_provider(profile, prompt, workspace, run_dir, operation_id, context):
    if not CODEX_TRANSLATION_CAPABILITY['production_translation_verified']:
        return _typed_failure(
            'codex_cli', operation_id, 'RUNTIME_CODEX_TRANSLATOR_UNVERIFIED',
            runtime_unverified=True)
    return run_codex_one_shot(profile, prompt, workspace, run_dir, operation_id, context)


def _claude_provider(profile, prompt, workspace, run_dir, operation_id, context):
    if not CLAUDE_BRIDGE_CAPABILITY['production_enabled']:
        return _typed_failure('claude_host', operation_id,
                              'RUNTIME_CLAUDE_HOST_BRIDGE_UNAVAILABLE')
    return run_claude_host(profile,prompt,workspace,run_dir,operation_id,context)


def _provider_registry(overrides=None):
    registry={'codex_cli':_codex_provider,'claude_host':_claude_provider}
    if overrides is not None:
        if type(overrides) is not dict or set(overrides)-set(registry) or any(
                not callable(value) for value in overrides.values()):
            raise ConfigError('PROVIDER_REGISTRY_INVALID')
        registry.update(overrides)
    return MappingProxyType(registry)


def dispatcher(config, workspace, provider_registry=None):
    providers = _provider_registry(provider_registry)
    def dispatch(job, context):
        if config.get('schema_version') == 2:
            profile_name=job['model_profile']
            captured=copy.deepcopy(config['model_profiles'][profile_name])
            provider=captured.pop('provider')
            captured.pop('circuit', None)
            operation_id=context['operation_id']
            if STOP.is_set():
                return ProviderResultV1(
                    provider=provider, operation_id=operation_id, phase='not_started',
                    submission='not_submitted', terminal_proof='absent', status='retryable',
                    code='SHUTDOWN_BEFORE_DISPATCH', failure_kind='provider',
                    provider_should_retry=True, receipt={'automatic_retry':False})
            artifact = context.get('prompt_artifact')
            if not isinstance(artifact, PromptArtifactDescriptorV1):
                return _typed_failure(provider, operation_id,
                                      'RUNTIME_PROMPT_ARTIFACT_INVALID')
            try:
                store = PromptArtifactStore(workspace)
                with store.open(artifact) as lease:
                    if not isinstance(lease, PromptLease):
                        raise PromptCustodyError('LEASE_INVALID')
                    raw = b''.join(lease.chunks())
                if len(raw) != artifact.length:
                    raise PromptCustodyError('ARTIFACT_LENGTH_INVALID')
                prompt = raw.decode('utf-8', errors='strict')
            except (PromptCustodyError, UnicodeDecodeError):
                return _typed_failure(provider, operation_id,
                                      'RUNTIME_PROMPT_ARTIFACT_INVALID')
            deadline_at = datetime.now(timezone.utc)
            timeout = captured.get('timeout_seconds')
            if type(timeout) in (int,float):
                from datetime import timedelta
                deadline_at += timedelta(seconds=timeout)
            provider_context={'cancel_event':STOP,'deadline_at':deadline_at}
            run_dir=workspace/'.job-runtime'/'runs'/context['attempt_id']
            adapter=providers[provider]
            try:
                result=adapter(captured,prompt,workspace,run_dir,operation_id,provider_context)
            except Exception:
                return _typed_failure(provider,operation_id,
                                      'RUNTIME_PROVIDER_INVOCATION_OUTCOME_UNKNOWN',unknown=True)
            if not isinstance(result,ProviderResultV1):
                return _typed_failure(provider,operation_id,
                                      'RUNTIME_PROVIDER_RESULT_INVALID',unknown=True)
            return result
        if STOP.is_set():return {'status':'retryable','code':'SHUTDOWN_BEFORE_DISPATCH'}
        profile_name=job['model_profile']
        captured=copy.deepcopy(config['model_profiles'][profile_name])
        executor=captured.get('executor','readiness')
        profile={k:v for k,v in captured.items() if k!='executor'}
        extra = {};gmail_claim=None;captured_prompt=None
        if job.get('adapter'):
            module, method = job['adapter'].split(':')
            try:imported = adapter_module(module,config,workspace)
            except ConfigError as error:return _adapter_load_failure(error)
            except AdapterImportOutcomeUnknown:
                return {'status':'unknown','code':'RUNTIME_ADAPTER_IMPORT_OUTCOME_UNKNOWN','receipt':{
                    'service_generation':service_generation()}}
            try:adapter=getattr(imported,method)
            except AttributeError:
                return {'status':'failed','code':'RUNTIME_ADAPTER_METHOD_MISSING','receipt':{
                    'adapter_method':method,'service_generation':service_generation()}}
            context_version=getattr(imported,'RUNTIME_CONTEXT_VERSION',None)
            required_protocol=getattr(imported,'REQUIRED_SERVICE_PROTOCOL_VERSION',None)
            if required_protocol is not None and (type(required_protocol) is not int or
                                                  required_protocol>SERVICE_PROTOCOL_VERSION):
                return {'status':'failed','code':'RUNTIME_SERVICE_PROTOCOL_STALE','receipt':{
                    'required_service_protocol_version':required_protocol if type(required_protocol) is int else 'invalid',
                    'loaded_service_protocol_version':SERVICE_PROTOCOL_VERSION,
                    'service_generation':service_generation(),
                }}
            if context_version not in (None,*RUNTIME_CONTEXT_VERSIONS):
                return {'status':'failed','code':'RUNTIME_ADAPTER_PROTOCOL_UNSUPPORTED','receipt':{
                    'requested_runtime_context_version':context_version if type(context_version) is int else 'invalid',
                    'supported_runtime_context_versions':list(RUNTIME_CONTEXT_VERSIONS),
                    'service_generation':service_generation(),
                }}
            generation=None
            if context_version in RUNTIME_CONTEXT_VERSIONS:
                runtime={'version':context_version,'model_profile_name':profile_name,
                    'model_profile':_immutable(copy.deepcopy(captured)),'cancel_event':STOP}
                if context_version>=2:
                    try:generation=adapter_generation(imported,module,workspace)
                    except ConfigError as error:
                        return {'status':'failed','code':'RUNTIME_ADAPTER_GENERATION_UNATTESTED','receipt':{
                            'generation_code':str(error),'service_generation':service_generation()}}
                    runtime.update(service_generation=_immutable(service_generation()),
                                   adapter_generation=_immutable(generation))
                if context_version==3:
                    try:
                        captured_prompt,prompt_sha256=_prompt_snapshot(job['prompt_file'],workspace)
                    except ConfigError as error:
                        return {'status':'failed','code':'RUNTIME_PROMPT_CAPTURE_INVALID','receipt':{
                            'capture_code':str(error),'service_generation':service_generation()}}
                    runtime.update(prompt_sha256=prompt_sha256,
                                   prompt_length=len(captured_prompt.encode('utf-8')))
                adapter_context={**copy.deepcopy(context),'job_id':job['id']}
                prepared=adapter(job.get('adapter_config',{}),workspace,adapter_context,MappingProxyType(runtime))
                if context_version in (1,2) or isinstance(prepared,dict) and 'status' in prepared:
                    checked=_terminal_adapter_result(prepared)
                    if checked is None:
                        return {'status':'failed','code':'RUNTIME_ADAPTER_TERMINAL_INVALID','receipt':{
                            'service_generation':service_generation()}}
                    prepared=checked
            else:
                prepared=adapter(job.get('adapter_config',{}),workspace,context)
            if isinstance(prepared,dict) and 'status' in prepared:
                checked=_terminal_adapter_result(prepared)
                if checked is None:
                    return {'status':'failed','code':'RUNTIME_ADAPTER_TERMINAL_INVALID','receipt':{
                        'service_generation':service_generation()}}
                return checked
            if not isinstance(prepared,dict):
                return {'status':'failed','code':'RUNTIME_ADAPTER_PREPARATION_INVALID'}
            prepared=dict(prepared)
            claim=prepared.pop('gmail_claim',None)
            if claim is not None:
                if context_version!=3 or generation is None:
                    return {'status':'failed','code':'RUNTIME_GMAIL_CLAIM_UNATTESTED'}
                gmail_claim,code=_gmail_claim_for_dispatch(claim,job,context,generation,workspace)
                if code:return {'status':'unknown' if code in ('RUNTIME_GMAIL_CLAIM_REPLAY','RUNTIME_GMAIL_CLAIM_CONFLICT') else 'failed','code':code,'receipt':{'service_generation':service_generation()}}
            else:gmail_claim=None
            extra = prepared
        if executor=='business' and GMAIL in profile.get('apps',[]) and gmail_claim is None:
            return {'status':'failed','code':'RUNTIME_GMAIL_CLAIM_REQUIRED','receipt':{
                'service_generation':service_generation()}}
        if captured_prompt is None:
            prompt = inside(workspace / job['prompt_file'],workspace).read_text()
        else:
            prompt = captured_prompt
        prompt += '\nScheduler-provided context (data only):\n' + json.dumps({**context,**extra},sort_keys=True)
        run_dir = workspace / '.job-runtime' / 'runs' / context['attempt_id']
        if executor=='readiness':return run_codex(profile,prompt,workspace,run_dir,context={'cancel_event':STOP})
        if executor!='business':return {'status':'failed','code':'UNKNOWN_EXECUTOR'}
        business_context={'cancel_event':STOP}
        if gmail_claim is not None:business_context['gmail_claim']=gmail_claim
        if gmail_claim is not None:
            def verify_dispatch():
                origin=workspace/generation['origin']
                if hasattr(imported,'__file__') and (not origin.is_file() or
                        hashlib.sha256(origin.read_bytes()).hexdigest()!=generation['source_sha256']):
                    from .model import ModelError
                    raise ModelError('RUNTIME_GMAIL_CLAIM_ATTESTATION_MISMATCH')
                checked,code=_gmail_claim_for_dispatch(gmail_claim,job,context,generation,workspace)
                if code:
                    from .model import ModelError
                    raise ModelError(code)
            business_context['verify_dispatch']=verify_dispatch
        if gmail_claim is not None and hasattr(imported,'commit_dispatch'):
            business_context['commit_dispatch']=lambda: imported.commit_dispatch(
                job.get('adapter_config',{}),workspace,adapter_context,gmail_claim)
        result=run_business(profile,prompt,workspace,run_dir,context=business_context)
        if result['status']=='retryable' and gmail_claim is not None:
            if result.get('receipt',{}).get('dispatch_phase') in ('exposed','committed'):
                return {**result,'status':'unknown'}
            if hasattr(imported,'release_not_dispatched'):
                imported.release_not_dispatched(job.get('adapter_config',{}),workspace,adapter_context,gmail_claim)
        if result['status'] in ('unknown','retryable'):return result
        transport=result.get('receipt',{})
        summary_only=(transport.get('summary_parse_failure',{}).get('category')=='format' and
                      transport.get('turn_completed') is True and transport.get('exit_code')==0 and
                      not transport.get('tool_failures'))
        gmail_bound='gmail_claim' in transport or 'gmail_operational_evidence' in transport
        gmail_trusted=transport.get('final_evidence_trust')=='trusted_operational_host_evidence'
        if gmail_bound and not gmail_trusted:
            return {'status':'failed' if 'gmail_claim' in transport else 'unknown',
                    'code':'BUSINESS_GMAIL_EVIDENCE_UNVERIFIED','receipt':transport}
        if job.get('completion_adapter') and (result['status']=='succeeded' or summary_only):
            module,method=job['completion_adapter'].split(':')
            candidate=getattr(adapter_module(module,config,workspace),method)(
                job.get('adapter_config',{}),workspace,context,result)
            checked=_completion_adapter_result(candidate)
            if checked is None:
                return {'status':'failed','code':'BUSINESS_POSTCONDITION_INVALID','receipt':transport}
            if checked['verified'] is True:
                result={**result,'status':'succeeded','code':'BUSINESS_POSTCONDITION_VERIFIED'}
                result['receipt']['postcondition']=checked
                return result
            return {'status':'failed','code':'BUSINESS_POSTCONDITION_FAILED','receipt':transport}
        # Model-authored final fields are sanitized handoff data, never independent
        # proof of delivery. A host-owned completion adapter must verify business
        # postconditions before the scheduler can retain success.
        if result['status']=='succeeded' and profile['phase']=='business':
            result={**result,'status':'failed','code':'BUSINESS_DELIVERY_NOT_VERIFIED'}
        return result
    return dispatch


def publish_prompt_jobs(workspace, jobs, stable_generation):
    """Publish schema-2 captures and return descriptor-only copied jobs.

    CAS publication is immutable and GC-contained. If a later publication or
    Engine construction fails, an already-published object may remain orphaned
    until the prompt-artifact collector removes it.
    """
    store=PromptArtifactStore(Path(workspace).resolve(strict=True))
    prepared=[]
    for job in jobs:
        capture=job.get('_prompt_capture')
        if not isinstance(capture,CapturedPromptV1):
            raise ConfigError('PROMPT_CAPTURE_REQUIRED')
        try:
            artifact=store.publish(capture,stable_generation,'native_v1')
        except PromptCustodyError as error:
            raise ConfigError(error.code) from None
        sanitized={key:value for key,value in job.items() if key not in {
            '_prompt_capture','_prompt_raw','_prompt_snapshot','_prompt_sha256'}}
        prepared.append({**sanitized,'_prompt_artifact':artifact})
    return prepared


def resource_jobs(config,jobs):
    # Allocation cannot choose resource capacity or retry/model policy. Shared
    # auth caches are serialized before claims consume attempt budgets.
    if config.get('schema_version') == 1:
        return [{**job,'_resource_key':str(Path(config['model_profiles'][job['model_profile']]['auth_home']).resolve())} for job in jobs]
    policy=validate_retry_policy(config['retry'])
    prepared=[]
    for job in jobs:
        profile_name=job['model_profile']
        profile=config['model_profiles'][profile_name]
        provider=profile['provider']
        identity=json.dumps({'provider':provider,
            'auth_home':str(Path(profile['auth_home']).resolve())},
            sort_keys=True,separators=(',',':')).encode()
        resource_hash=hashlib.sha256(identity).hexdigest()
        circuit=profile.get('circuit',{'failure_threshold':3,'open_seconds':60,'probe_seconds':10})
        contract=job['_replay_contract']
        prepared.append({**job,
            'replay_safe':contract.effect.value == 'none',
            '_provider':provider,
            '_retry_policy':policy,
            '_circuit_scope':{'profile':profile_name,'resource_hash':resource_hash,
                'failure_threshold':circuit['failure_threshold'],
                'open_seconds':circuit['open_seconds'],'probe_seconds':circuit['probe_seconds']},
            '_resource_key':resource_hash})
    return prepared


def serve(workspace, config_path):
    workspace = Path(workspace).resolve(strict=True)
    config,jobs = load(config_path,workspace)
    state = workspace / '.job-runtime'
    for relative in config['source_paths']:
        sys.path.insert(0,str(inside(workspace / relative,workspace)))
    lock = os.open(state/'service.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock)
        return 0
    generation=service_generation()
    atomic(state/'service-generation.json',generation)
    engine_jobs=publish_prompt_jobs(workspace,jobs,_code_generation()) if config.get('schema_version') == 2 else jobs
    engine = Engine(state/'engine',resource_jobs(config,engine_jobs),config['retry'],dispatcher(config,workspace),workspace_root=workspace,
                    max_workers=config['max_workers'])
    # launchd owns child processes as a process group; graceful stop cancels
    # model process groups. Recovery never retries an unknown external effect.
    engine.recover_running(datetime.now(timezone.utc))
    def beat():
        while not STOP.is_set():
            atomic(state/'heartbeat.json',{'pid':os.getpid(),'at':datetime.now(timezone.utc).isoformat()})
            STOP.wait(config['heartbeat_seconds'])
    worker = threading.Thread(target=beat,daemon=True);worker.start()
    signal.signal(signal.SIGTERM,lambda *_:STOP.set())
    signal.signal(signal.SIGINT,lambda *_:STOP.set())
    signal.signal(signal.SIGHUP,lambda *_:RELOAD.set())
    try:
        while not STOP.is_set():
            if RELOAD.is_set():
                # Reload only between completed ticks; running attempts retain
                # their original model and allocation. Durable slots persist.
                try:
                    candidate_config,candidate_jobs=load(config_path,workspace)
                    validate_reload(engine,candidate_jobs)
                    candidate_engine_jobs=(publish_prompt_jobs(
                        workspace,candidate_jobs,_code_generation())
                        if candidate_config.get('schema_version') == 2 else candidate_jobs)
                    candidate_engine=Engine(state/'engine',resource_jobs(candidate_config,candidate_engine_jobs),candidate_config['retry'],
                        dispatcher(candidate_config,workspace),workspace_root=workspace,max_workers=candidate_config['max_workers'])
                    for relative in candidate_config['source_paths']:
                        candidate=str(inside(workspace / relative,workspace))
                        if candidate not in sys.path:sys.path.insert(0,candidate)
                    config,jobs,engine=candidate_config,candidate_jobs,candidate_engine
                    atomic(state/'reload-status.json',{'at':datetime.now(timezone.utc).isoformat(),'accepted':True,
                        'code':'CONFIG_RELOAD_ACCEPTED','service_generation':generation})
                except Exception as exc:
                    code=str(exc) if isinstance(exc,ConfigError) else 'CONFIG_RELOAD_REJECTED'
                    atomic(state/'reload-status.json',{'at':datetime.now(timezone.utc).isoformat(),'accepted':False,
                        'code':code,'service_generation':generation})
                finally:
                    RELOAD.clear()
            started=time.monotonic()
            summary=engine.tick(datetime.now(timezone.utc))
            atomic(state/'status.json',{**engine.status(),'pid':os.getpid(),'last_tick':datetime.now(timezone.utc).isoformat(),
                                       'last_dispatch':summary,'scheduler_installed':True,
                                       'service_generation':generation})
            STOP.wait(max(0,config['tick_seconds']-(time.monotonic()-started)))
    finally:
        STOP.set();worker.join(timeout=2);os.close(lock)
    return 0


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--config',required=True)
    parser.add_argument('--service-label')
    args=parser.parse_args();os.umask(0o077)
    if args.service_label is not None and (type(args.service_label) is not str or
            re.fullmatch(r'[a-z][a-z0-9-]{0,62}(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+', args.service_label) is None or
            args.service_label.endswith('.watchdog') or len(args.service_label.encode()) > 240):
        print(json.dumps({'status':'failed','code':'SERVICE_LABEL_INVALID'}),flush=True)
        return 2
    try:
        return serve(args.workspace,args.config)
    except Exception as error:
        # No arbitrary exception text, prompts, provider content or tokens.
        code=str(error) if isinstance(error,ConfigError) else 'SERVICE_FAILED'
        print(json.dumps({'status':'failed','code':code}),flush=True)
        return 2


def _attested_main():
    """Replace ``python -m`` bytecode execution with one exact source snapshot."""
    marker='_JOB_RUNTIME_EXACT_SOURCE'
    if os.environ.get(marker)=='1':
        raise SystemExit(main())
    source,_identity=_source_snapshot(_SERVICE_SOURCE)
    env=dict(os.environ)
    env[marker]='1'
    env['_JOB_RUNTIME_SOURCE_B64']=base64.b64encode(source).decode('ascii')
    bootstrap=(
        "import base64,hashlib,os;"
        "data=base64.b64decode(os.environ.pop('_JOB_RUNTIME_SOURCE_B64'));"
        "path="+repr(str(_SERVICE_SOURCE))+";"
        "scope={'__name__':'__main__','__file__':path,'__package__':'shared.job_runtime',"
        "'_EXECUTED_SOURCE_SHA256':hashlib.sha256(data).hexdigest()};"
        "exec(compile(data,path,'exec',dont_inherit=True),scope)"
    )
    os.execve(sys.executable,[sys.executable,'-c',bootstrap,*sys.argv[1:]],env)


if __name__=='__main__':
    _attested_main()
