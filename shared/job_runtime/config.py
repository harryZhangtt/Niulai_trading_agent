"""Strict infrastructure configuration, separate from job allocations."""
import json
import os
from pathlib import Path
import re
import stat


class ConfigError(ValueError):
    pass


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


def read_json(path):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'DUPLICATE_JSON_KEY')
            result[k] = v
        return result
    require(path.is_file() and path.stat().st_size < 1024 * 1024, 'CONFIG_FILE_INVALID')
    return json.loads(path.read_text(), object_pairs_hook=pairs)


def load(path, workspace):
    workspace = Path(workspace).resolve(strict=True)
    path = inside(path, workspace, True)
    for a in [path, *path.parents]:
        if a == workspace:
            break
        require(a.stat().st_uid == os.getuid() and stat.S_IMODE(a.stat().st_mode) & 0o077 == 0,
                'PRIVATE_CONFIG_PERMISSIONS')
    value = read_json(path)
    required={'schema_version','tick_seconds','heartbeat_seconds','stale_seconds',
              'max_workers','retry','model_profiles','allocation_files','source_paths'}
    require(required <= value.keys() and value.keys() <= required|{'python_bin'}, 'CONFIG_KEYS_INVALID')
    if 'python_bin' in value:
        require(inside(value['python_bin'],workspace,True).is_file(),'RUNTIME_PYTHON_INVALID')
    require(value['schema_version'] == 1 and type(value['schema_version']) is int, 'CONFIG_VERSION_INVALID')
    for key, low, high in [('tick_seconds',1,60),('heartbeat_seconds',1,30),('stale_seconds',30,600),('max_workers',1,8)]:
        require(type(value[key]) is int and low <= value[key] <= high, 'CONFIG_INTERVAL_INVALID')
    require(value['stale_seconds'] > 2 * value['heartbeat_seconds'], 'STALE_THRESHOLD_INVALID')
    require(isinstance(value['model_profiles'],dict) and value['model_profiles'], 'MODEL_PROFILES_REQUIRED')
    require(isinstance(value['allocation_files'],list) and value['allocation_files'], 'ALLOCATIONS_REQUIRED')
    require(isinstance(value['source_paths'],list), 'SOURCE_PATHS_INVALID')
    for relative in value['source_paths']:
        require(isinstance(relative,str) and not Path(relative).is_absolute(), 'SOURCE_PATH_INVALID')
        require(inside(workspace / relative,workspace).is_dir(), 'SOURCE_PATH_INVALID')
    for profile in value['model_profiles'].values():
        require(isinstance(profile,dict),'PROFILE_INVALID')
        inside(profile['auth_home'],workspace,True)
    jobs = []
    for relative in value['allocation_files']:
        require(isinstance(relative,str) and not Path(relative).is_absolute(),'ALLOCATION_PATH_INVALID')
        allocation = read_json(inside(workspace / relative,workspace))
        require(set(allocation) == {'schema_version','jobs'} and allocation['schema_version'] == 1,
                'ALLOCATION_SCHEMA_INVALID')
        require(isinstance(allocation['jobs'],list),'ALLOCATION_JOBS_INVALID')
        for job in allocation['jobs']:
            require(set(job) <= {'id','enabled','schedule','replay_safe','model_profile','prompt_file','adapter','adapter_config','completion_adapter'},
                    'JOB_KEYS_INVALID')
            require(job.get('model_profile') in value['model_profiles'], 'MODEL_PROFILE_NOT_FOUND')
            prompt = inside(workspace / job['prompt_file'], workspace)
            require(prompt.is_file() and prompt.stat().st_size <= 65536, 'PROMPT_INVALID')
            adapter = job.get('adapter')
            require(adapter is None or (isinstance(adapter,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*',adapter)), 'ADAPTER_INVALID')
            completion=job.get('completion_adapter')
            require(completion is None or (isinstance(completion,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*',completion)), 'COMPLETION_ADAPTER_INVALID')
            jobs.append(job)
    return value, jobs
