#!/usr/bin/env python3
"""Restore explicit UI opt-in using the native Codex thread and target state."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

sys.dont_write_bytecode = True
from verify import read_file, verify

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {'schema_version', 'thread_key', 'project_key', 'state', 'bundle_fingerprint',
          'created_at', 'updated_at'}
STATUSES = {'enabled': 'HARRY_UI_SESSION_ACTIVE', 'disabled': 'HARRY_UI_SESSION_DISABLED'}


class SessionError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise SessionError(code)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'state_duplicate_field')
        result[key] = value
    return result


def identity():
    # Observed in Codex 0.166.0 tool processes. The session-tree ID is NOT a
    # substitute: distinct forked threads may share it.
    native = os.environ.get('CODEX_THREAD_ID')
    require(isinstance(native, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', native),
            'native_thread_identity_unavailable')
    return hashlib.sha256(('harry-ui-thread-v1:' + native).encode()).hexdigest()


def checked_directory(path, create=False):
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    require(path.is_dir() and path.resolve() == path, 'session_directory_unsafe')
    require(path.stat().st_uid == os.getuid(), 'session_owner_mismatch')
    require(not (stat.S_IMODE(path.stat().st_mode) & 0o022), 'session_directory_writable')


def ensure_ignore(directory):
    path = directory / '.gitignore'
    temporary = directory / ('.ignore-pending-' + uuid.uuid4().hex)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(b'*\n')
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            require(read_file(path, directory, 16) == b'*\n', 'session_ignore_policy_changed')
    finally:
        if temporary.exists():
            temporary.unlink()


def read_state(path, thread_key, project_key):
    if not path.exists() and not path.is_symlink():
        return None
    require(not path.is_symlink() and path.resolve() == path, 'session_state_unsafe')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and not (stat.S_IMODE(info.st_mode) & 0o077), 'session_state_unsafe')
        raw = source.read(8193)
    require(0 < len(raw) <= 8192, 'session_state_size')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)
    require(isinstance(value, dict) and set(value) == FIELDS
            and type(value['schema_version']) is int and value['schema_version'] == 1,
            'session_schema_invalid')
    require(value['thread_key'] == thread_key and value['project_key'] == project_key,
            'session_scope_mismatch')
    require(value['state'] in STATUSES and re.fullmatch(r'[a-f0-9]{64}', value['bundle_fingerprint']),
            'session_schema_invalid')
    for field in ('created_at', 'updated_at'):
        require(isinstance(value[field], str) and len(value[field]) <= 64,
                'session_schema_invalid')
        require(datetime.fromisoformat(value[field]).tzinfo is not None, 'session_schema_invalid')
    return value


def write_state(path, value):
    temporary = path.parent / ('.pending-' + uuid.uuid4().hex)
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            output.write(json.dumps(value, sort_keys=True) + '\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def session(project, action='restore', root=ROOT):
    try:
        require(action in {'restore', 'enable', 'disable'}, 'action_invalid')
        target = Path(project).absolute()
        require(target.is_dir() and target.resolve() == target, 'target_project_unsafe')
        require(not target.is_relative_to(root), 'target_must_not_be_bundle')
        thread_key = identity()
        require(not verify(root), 'bundle_verification_failed')
        fingerprint = hashlib.sha256(read_file(root / 'manifest.json', root, 2 * 1024 * 1024)).hexdigest()
        project_key = hashlib.sha256(str(target).encode()).hexdigest()
        runtime, create = target / '.ui-skill-runtime', action in {'enable', 'disable'}
        directory = runtime / 'harry-ui-sessions'
        for path in (runtime, directory):
            if not path.exists() and not path.is_symlink() and not create:
                return {'status': 'HARRY_UI_SESSION_INACTIVE', 'reason': 'no_opt_in_for_this_thread',
                        'persistence': 'native-thread', 'state': 'absent'}
            checked_directory(path, create)
        if create:
            ensure_ignore(directory)
        path = directory / (thread_key + '.json')
        if action == 'restore' and not path.exists() and not path.is_symlink():
            return {'status': 'HARRY_UI_SESSION_INACTIVE', 'reason': 'no_opt_in_for_this_thread',
                    'persistence': 'native-thread', 'state': 'absent'}
        lock_path = directory / (thread_key + '.lock')
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(descriptor)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and not (stat.S_IMODE(info.st_mode) & 0o077), 'session_lock_unsafe')
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SessionError('session_busy') from None
            previous = read_state(path, thread_key, project_key)
            if previous is None and action == 'restore':
                return {'status': 'HARRY_UI_SESSION_INACTIVE', 'reason': 'no_opt_in_for_this_thread',
                        'persistence': 'native-thread', 'state': 'absent'}
            desired = previous['state'] if action == 'restore' else ('enabled' if action == 'enable' else 'disabled')
            changed = (previous is None or previous['state'] != desired
                       or (desired == 'enabled' and previous['bundle_fingerprint'] != fingerprint))
            if changed:
                stamp = datetime.now(timezone.utc).isoformat()
                value = {'schema_version': 1, 'thread_key': thread_key, 'project_key': project_key,
                         'state': desired, 'bundle_fingerprint': fingerprint,
                         'created_at': previous['created_at'] if previous else stamp, 'updated_at': stamp}
                write_state(path, value)
            status = 'HARRY_UI_SESSION_ENABLED' if action == 'enable' else STATUSES[desired]
            return {'status': status, 'state': desired, 'persistence': 'native-thread',
                    'new_activation': desired == 'enabled' and (previous is None or previous['state'] == 'disabled'),
                    'state_changed': changed, 'bundle_fingerprint': fingerprint,
                    'record_ref': str(path.relative_to(target)),
                    'message': ('Harry UI skill set is enabled for this conversation.' if desired == 'enabled'
                                else 'Harry UI skill set is disabled for this conversation.')}
        finally:
            os.close(descriptor)
    except SessionError as error:
        return {'status': 'HARRY_UI_SESSION_FAILED', 'code': str(error)}
    except (OSError, ValueError, UnicodeError, RuntimeError, TypeError, KeyError):
        return {'status': 'HARRY_UI_SESSION_FAILED', 'code': 'session_validation_failed'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['restore', 'enable', 'disable'])
    parser.add_argument('--project', default=str(Path.cwd()))
    args = parser.parse_args()
    result = session(args.project, args.action)
    print(json.dumps(result, indent=2))
    raise SystemExit(result['status'] == 'HARRY_UI_SESSION_FAILED')
