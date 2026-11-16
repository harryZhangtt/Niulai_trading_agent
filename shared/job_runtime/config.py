"""Strict infrastructure configuration, separate from job allocations."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from .prompt_custody import PromptArtifactStore, PromptCustodyError
from .provider_contract import ReplayContractV1
from .retry_policy import RetryPolicyError, validate_retry_policy


class ConfigError(ValueError):
    pass


# Test-only seam; production leaves this as None. It never supplies data.
_PROMPT_READ_HOOK = None


def require(value, code):
    if not value:
        raise ConfigError(code)


def inside(path, workspace, private=False):
    p = Path(os.path.abspath(path))
    base = workspace / '.job-runtime' if private else workspace
    require('..' not in Path(path).parts and p.is_relative_to(base)
            and p.resolve().is_relative_to(base.resolve()), 'PATH_OUTSIDE_BOUNDARY')
    for a in [p, *p.parents]:
        if a == workspace:
            break
        require(not a.is_symlink(), 'SYMLINK_REJECTED')
    return p


def prompt_file(relative, workspace):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), 'PROMPT_INVALID')
    parts = Path(relative).parts
    private_state = (len(parts) >= 3 and parts[0] == '.job-runtime'
                     and parts[1] in {'config', 'acceptance'})
    checked_parts = parts[2:] if private_state else parts
    require(all(not part.startswith('.') and part != 'runtime' and part != 'private'
                and not part.endswith('-private') for part in checked_parts), 'PROMPT_INVALID')
    prompt = inside(workspace / relative, workspace)
    try:
        info = prompt.stat()
        if private_state:
            private_paths = [prompt]
            ancestor = prompt.parent
            while ancestor != workspace:
                private_paths.append(ancestor)
                ancestor = ancestor.parent
            require(all(path.stat().st_uid == os.getuid()
                        and stat.S_IMODE(path.stat().st_mode) & 0o022 == 0
                        for path in private_paths), 'PROMPT_INVALID')
    except OSError:
        raise ConfigError('PROMPT_INVALID') from None
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and info.st_size <= 65536 and prompt.suffix in ('.md', '.txt'), 'PROMPT_INVALID')
    return prompt


def _prompt_snapshot(relative, workspace):
    """Read one validated prompt inode through held no-follow descriptors."""
    prompt = prompt_file(relative, workspace)
    descriptors = []
    leaf = None
    try:
        try:
            validated = os.stat(prompt, follow_symlinks=False)
            root = os.open(workspace, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
                           | getattr(os, 'O_NOFOLLOW', 0))
            descriptors.append(root)
            root_info = os.fstat(root)
            require(root_info.st_uid in (0, os.getuid())
                    and root_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0,
                    'PROMPT_INVALID')
            parts = Path(relative).parts
            for component in parts[:-1]:
                descriptor = os.open(
                    component, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
                    | getattr(os, 'O_NOFOLLOW', 0), dir_fd=descriptors[-1])
                descriptors.append(descriptor)
                info = os.fstat(descriptor)
                require(stat.S_ISDIR(info.st_mode) and info.st_uid in (0, os.getuid())
                        and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0,
                        'PROMPT_INVALID')
            if callable(_PROMPT_READ_HOOK):
                _PROMPT_READ_HOOK('before_open', prompt)
            leaf = os.open(parts[-1], os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0),
                           dir_fd=descriptors[-1])
            before = os.fstat(leaf)
            require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                    and before.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0
                    and before.st_size <= 65536
                    and (before.st_dev, before.st_ino) == (validated.st_dev, validated.st_ino),
                    'PROMPT_INVALID')
            if callable(_PROMPT_READ_HOOK):
                _PROMPT_READ_HOOK('after_fstat', prompt)
            chunks = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(leaf, min(65536, remaining))
                require(bool(chunk), 'PROMPT_INVALID')
                chunks.append(chunk)
                remaining -= len(chunk)
            require(os.read(leaf, 1) == b'', 'PROMPT_INVALID')
            after = os.fstat(leaf)
            identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                                     info.st_mtime_ns)
            require(identity(before) == identity(after), 'PROMPT_CHANGED_DURING_READ')
            raw = b''.join(chunks)
            try:
                snapshot = raw.decode('utf-8', errors='strict')
            except UnicodeDecodeError:
                raise ConfigError('PROMPT_UTF8_INVALID') from None
            return snapshot, hashlib.sha256(raw).hexdigest()
        except OSError:
            raise ConfigError('PROMPT_INVALID') from None
    finally:
        if leaf is not None:
            os.close(leaf)
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def read_json(path):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'DUPLICATE_JSON_KEY')
            result[k] = v
        return result
    require(path.is_file() and path.stat().st_size < 1024 * 1024, 'CONFIG_FILE_INVALID')
    return json.loads(path.read_text(), object_pairs_hook=pairs)


_ROOT_KEYS = {'schema_version','tick_seconds','heartbeat_seconds','stale_seconds',
              'max_workers','retry','model_profiles','allocation_files','source_paths'}
_V1_JOB_KEYS = {'id','enabled','schedule','replay_safe','model_profile','prompt_file',
                'adapter','adapter_config','completion_adapter'}
_V2_JOB_KEYS = {'id','enabled','schedule','model_profile','prompt_file','replay_contract'}
_REPLAY_KEYS = {'version','effect','automatic_phases','slot_operation_scope','reconciliation_adapter'}
_CODEX_PROFILE_REQUIRED = {'provider','codex_bin','model','effort','timeout_seconds','auth_home'}
_CODEX_PROFILE_OPTIONAL = {'max_output_bytes','strict_process_tree_containment','circuit'}
_CLAUDE_PROFILE_REQUIRED = {'provider','model','effort','timeout_seconds','auth_home'}
_CLAUDE_PROFILE_OPTIONAL = {'max_budget_usd','circuit'}
_CIRCUIT_KEYS = {'failure_threshold','open_seconds','probe_seconds'}


def _v2_profile(profile, workspace):
    require(type(profile) is dict and profile.get('provider') in ('codex_cli','claude_host'),
            'PROFILE_INVALID')
    required, optional = ((_CODEX_PROFILE_REQUIRED, _CODEX_PROFILE_OPTIONAL)
                          if profile['provider'] == 'codex_cli'
                          else (_CLAUDE_PROFILE_REQUIRED, _CLAUDE_PROFILE_OPTIONAL))
    require(required <= set(profile) and set(profile) <= required | optional, 'PROFILE_KEYS_INVALID')
    require(isinstance(profile['model'], str) and re.fullmatch(
        r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', profile['model']), 'PROFILE_MODEL_INVALID')
    require(type(profile['timeout_seconds']) in (int, float)
            and 0 < profile['timeout_seconds'] <= 3600, 'PROFILE_TIMEOUT_INVALID')
    if profile['provider'] == 'claude_host':
        require(profile['effort'] in ('low','medium','high')
                and type(profile.get('max_budget_usd',1.0)) in (int,float)
                and 0 < profile.get('max_budget_usd',1.0) <= 100,
                'PROFILE_CLAUDE_OPTIONS_INVALID')
    auth_home = inside(profile['auth_home'], workspace, True)
    require(auth_home.is_dir(), 'PROFILE_RESOURCE_INVALID')
    circuit = profile.get('circuit', {'failure_threshold': 3, 'open_seconds': 60,
                                      'probe_seconds': 10})
    require(type(circuit) is dict and set(circuit) == _CIRCUIT_KEYS,
            'PROFILE_CIRCUIT_INVALID')
    require(type(circuit['failure_threshold']) is int and 1 <= circuit['failure_threshold'] <= 100,
            'PROFILE_CIRCUIT_INVALID')
    require(type(circuit['open_seconds']) in (int, float)
            and 0 < circuit['open_seconds'] <= 86400 * 30,
            'PROFILE_CIRCUIT_INVALID')
    require(type(circuit['probe_seconds']) in (int, float)
            and 0 < circuit['probe_seconds'] <= 3600,
            'PROFILE_CIRCUIT_INVALID')


def _replay_contract(value):
    require(type(value) is dict and set(value) == _REPLAY_KEYS, 'REPLAY_CONTRACT_INVALID')
    try:
        return ReplayContractV1(
            effect=value['effect'], automatic_phases=tuple(value['automatic_phases']),
            slot_operation_scope=value['slot_operation_scope'],
            reconciliation_adapter=value['reconciliation_adapter'], version=value['version'])
    except (TypeError, ValueError):
        raise ConfigError('REPLAY_CONTRACT_INVALID') from None


def _v2_prompt_source(relative):
    require(type(relative) is str and '\\x00' not in relative and '\\\\' not in relative
            and not relative.startswith('/') and not relative.endswith('/')
            and '//' not in relative, 'SOURCE_PATH_INVALID')
    parts = PurePosixPath(relative).parts
    require(len(parts) >= 3 and parts[:2] in (
        ('.job-runtime', 'config'), ('.job-runtime', 'acceptance'))
        and all(part not in ('', '.', '..') for part in parts),
        'SOURCE_PATH_NOT_APPROVED')
    return relative


def _load(path, workspace, *, capture_prompts):
    workspace = Path(workspace).resolve(strict=True)
    path = inside(path, workspace, True)
    for a in [path, *path.parents]:
        if a == workspace:
            break
        require(a.stat().st_uid == os.getuid() and stat.S_IMODE(a.stat().st_mode) & 0o077 == 0,
                'PRIVATE_CONFIG_PERMISSIONS')
    value = read_json(path)
    require(_ROOT_KEYS <= value.keys() and value.keys() <= _ROOT_KEYS|{'python_bin'},
            'CONFIG_KEYS_INVALID')
    if 'python_bin' in value:
        require(inside(value['python_bin'],workspace,True).is_file(),'RUNTIME_PYTHON_INVALID')
    require(type(value['schema_version']) is int and value['schema_version'] in (1, 2),
            'CONFIG_VERSION_INVALID')
    version = value['schema_version']
    for key, low, high in [('tick_seconds',1,60),('heartbeat_seconds',1,30),('stale_seconds',30,600),('max_workers',1,8)]:
        require(type(value[key]) is int and low <= value[key] <= high, 'CONFIG_INTERVAL_INVALID')
    require(value['stale_seconds'] > 2 * value['heartbeat_seconds'], 'STALE_THRESHOLD_INVALID')
    require(isinstance(value['model_profiles'],dict) and value['model_profiles'], 'MODEL_PROFILES_REQUIRED')
    require(isinstance(value['allocation_files'],list) and value['allocation_files'], 'ALLOCATIONS_REQUIRED')
    require(isinstance(value['source_paths'],list), 'SOURCE_PATHS_INVALID')
    for relative in value['source_paths']:
        require(isinstance(relative,str) and not Path(relative).is_absolute(), 'SOURCE_PATH_INVALID')
        require(inside(workspace / relative,workspace).is_dir(), 'SOURCE_PATH_INVALID')
    if version == 2:
        try:
            validate_retry_policy(value['retry'])
        except RetryPolicyError:
            raise ConfigError('RETRY_POLICY_INVALID') from None
        for name, profile in value['model_profiles'].items():
            require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', name),
                    'PROFILE_NAME_INVALID')
            _v2_profile(profile, workspace)
    else:
        for profile in value['model_profiles'].values():
            require(isinstance(profile,dict),'PROFILE_INVALID')
            inside(profile['auth_home'],workspace,True)
    jobs = []
    for relative in value['allocation_files']:
        require(isinstance(relative,str) and not Path(relative).is_absolute(),'ALLOCATION_PATH_INVALID')
        allocation = read_json(inside(workspace / relative,workspace))
        require(set(allocation) == {'schema_version','jobs'} and allocation['schema_version'] == version,
                'ALLOCATION_SCHEMA_INVALID')
        require(isinstance(allocation['jobs'],list),'ALLOCATION_JOBS_INVALID')
        for source_job in allocation['jobs']:
            require(type(source_job) is dict, 'JOB_INVALID')
            if version == 1:
                require(set(source_job) <= _V1_JOB_KEYS, 'JOB_KEYS_INVALID')
                job = source_job
            else:
                require(set(source_job) == _V2_JOB_KEYS, 'JOB_KEYS_INVALID')
                require(not any(str(key).startswith('_') for key in source_job), 'JOB_KEYS_INVALID')
                contract = _replay_contract(source_job['replay_contract'])
                job = {key: item for key, item in source_job.items() if key != 'replay_contract'}
                job['_replay_contract'] = contract
            require(job.get('model_profile') in value['model_profiles'], 'MODEL_PROFILE_NOT_FOUND')
            if version == 1:
                if capture_prompts:
                    prompt_file(job.get('prompt_file'), workspace)
                adapter = job.get('adapter')
                require(adapter is None or (isinstance(adapter,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*',adapter)), 'ADAPTER_INVALID')
                completion=job.get('completion_adapter')
                require(completion is None or (isinstance(completion,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*',completion)), 'COMPLETION_ADAPTER_INVALID')
            else:
                relative = _v2_prompt_source(job.get('prompt_file'))
                if capture_prompts:
                    try:
                        job['_prompt_capture'] = PromptArtifactStore(workspace).capture_source(
                            workspace, relative)
                    except PromptCustodyError as error:
                        raise ConfigError(error.code) from None
            jobs.append(job)
    return value, jobs


def load(path, workspace):
    """Load executable configuration and capture schema-2 prompt source bytes."""
    return _load(path, workspace, capture_prompts=True)


def load_projection(path, workspace):
    """Load the structural dashboard projection without opening prompt sources."""
    return _load(path, workspace, capture_prompts=False)
