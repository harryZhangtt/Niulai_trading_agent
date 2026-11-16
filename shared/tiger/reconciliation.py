"""Bounded, read-only acknowledgement diagnostic for the frozen owner service.

No acquire, release, token/profile access, fence retirement or recovery API.
Native service context is accepted only through hidden stdin in a dedicated
process. See reconciliation-acceptance.md before invoking this against a Site.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
from datetime import datetime
from urllib import error, request

from .bridge import (NoRedirect, TigerBridgeError, TigerDeadline, hidden_input,
                     load_policy, require, safe_failure, validate_site)


SOURCE_SHA256 = 'ed1b7a20b85b2444dd30039c94e67cc9594e6a7923c00b689b312b9193172ac0'
SOURCE_COMMIT = 'ce58b639c137abda72f0bdea65118300355f4478'
VERSION_ID = 'appgprj_6ae039ec7604819198c21c4d6f390f24~appgver_058750a046708191a1ed5a394d472493'
DEPLOYMENT_ID = 'appgdep_6ae03b730e048191b4c5901eadc679a5'
_UUID = re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}')
_LIMIT = 65536


def _private_bytes(path, workspace, *, limit=_LIMIT):
    root = Path(workspace).resolve() / '.niulai-state'
    path = Path(os.path.abspath(path))
    require(path.is_relative_to(root) and path.resolve().is_relative_to(root),
            'READBACK_PRIVATE_PATH_REQUIRED')
    for parent in (path, *path.parents):
        if parent == root.parent:
            break
        require(not parent.is_symlink(), 'READBACK_PRIVATE_PATH_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_mode & 0o077 == 0 and info.st_size <= limit,
                'READBACK_PRIVATE_FILE_REQUIRED')
        data = stream.read(limit + 1)
    require(len(data) <= limit, 'READBACK_SIZE_LIMIT')
    return data


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'READBACK_RESPONSE_INVALID')
            result[key] = value
        return result
    def invalid(value):
        raise TigerBridgeError('READBACK_RESPONSE_INVALID')
    try:
        result = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError):
        raise TigerBridgeError('READBACK_RESPONSE_INVALID') from None
    require(isinstance(result, dict), 'READBACK_RESPONSE_INVALID')
    return result


def validate_provenance(context, policy):
    require(isinstance(context, dict) and set(context) == {'site', 'version', 'deployment'},
            'READBACK_NATIVE_CONTEXT_REQUIRED')
    session = validate_site(context['site'], policy)
    version, deployment = context['version'], context['deployment']
    require(isinstance(version, dict) and isinstance(deployment, dict),
            'READBACK_DEPLOYMENT_UNVERIFIED')
    require(context['site'].get('latest_version_number') == 1
            and version.get('id') == VERSION_ID and version.get('project_id') == policy['project_id']
            and version.get('version_number') == 1
            and version.get('source') == {'commit_sha': SOURCE_COMMIT}
            and version.get('deployment_id') == DEPLOYMENT_ID
            and deployment.get('id') == DEPLOYMENT_ID
            and deployment.get('project_id') == policy['project_id']
            and deployment.get('version_id') == VERSION_ID
            and deployment.get('status') == 'succeeded'
            and deployment.get('failure_message') is None,
            'READBACK_DEPLOYMENT_UNVERIFIED')
    return session


class ReadbackClient:
    """Two closed routes, no redirects or retries, never reads a profile."""

    def __init__(self, session, *, opener=None):
        self.session = session
        self.opener = opener or request.build_opener(NoRedirect())
        self.attempts = 0

    def once(self, operation, *, commit_id=None, lease_id=None):
        if operation == 'health':
            require(commit_id is None and lease_id is None, 'READBACK_ROUTE_REJECTED')
            path, method, data = '/health', 'GET', None
        elif operation == 'checkpoint_ack':
            require(isinstance(commit_id, str) and _UUID.fullmatch(commit_id)
                    and isinstance(lease_id, str) and _UUID.fullmatch(lease_id),
                    'READBACK_ORIGINAL_IDS_REQUIRED')
            path, method = '/lease/checkpoint', 'POST'
            data = json.dumps({'commit_id': commit_id, 'lease_id': lease_id},
                              sort_keys=True, separators=(',', ':')).encode()
        else:
            raise TigerBridgeError('READBACK_ROUTE_REJECTED')
        req = request.Request(self.session['origin'] + path, method=method, data=data,
            headers={'OAI-Sites-Authorization': 'Bearer ' + self.session['bearer'],
                     'Content-Type': 'application/json'})
        self.attempts += 1
        try:
            with self.opener.open(req, timeout=15) as response:
                require(response.status == 200, 'READBACK_HTTP_UNEXPECTED')
                raw = response.read(_LIMIT + 1)
                require(len(raw) <= _LIMIT, 'READBACK_RESPONSE_TOO_LARGE')
                value = _json(raw)
        except error.HTTPError as exc:
            status = exc.code
            exc.close()
            require(type(status) is int and 100 <= status <= 599, 'READBACK_HTTP_UNEXPECTED')
            return {'status': 'http_rejected', 'http_status': status}
        except (error.URLError, TimeoutError):
            return {'status': 'transport_unconfirmed'}
        require(type(value.get('revision')) is int and 0 <= value['revision'] <= 2**53,
                'READBACK_RESPONSE_INVALID')
        if operation == 'health':
            require(set(value) == {'schema', 'initialized', 'revision', 'lease_busy', 'last_committed_at'}
                    and type(value['schema']) is int and value['schema'] == 1
                    and type(value['initialized']) is bool and type(value['lease_busy']) is bool,
                    'READBACK_RESPONSE_INVALID')
            moment = value['last_committed_at']
            if moment is not None:
                require(isinstance(moment, str) and len(moment) <= 35,
                        'READBACK_RESPONSE_INVALID')
                try:
                    parsed = datetime.fromisoformat(moment.replace('Z', '+00:00'))
                except ValueError:
                    raise TigerBridgeError('READBACK_RESPONSE_INVALID') from None
                require(parsed.tzinfo is not None, 'READBACK_RESPONSE_INVALID')
        else:
            require(set(value) == {'committed', 'revision', 'idempotent', 'released'}
                    and value['committed'] is True and value['idempotent'] is True
                    and type(value['released']) is bool, 'READBACK_RESPONSE_INVALID')
        return {'status': 'observed', **value}


def diagnose(workspace, policy, context, source, *, opener=None):
    workspace = Path(workspace).resolve()
    require(hashlib.sha256(_private_bytes(source, workspace)).hexdigest() == SOURCE_SHA256,
            'READBACK_SOURCE_DRIFT')
    session = validate_provenance(context, policy)
    state = workspace / '.niulai-state' / 'tiger'
    fence = state / 'unresolved.json'
    lock = state / 'bridge.lock'
    _private_bytes(lock, workspace)
    fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TigerBridgeError('TIGER_BRIDGE_BUSY') from None
        original = _private_bytes(fence, workspace)
        value = _json(original)
        require(value.get('phase') == 'checkpoint' and value.get('automatic_retry') is False
                and isinstance(value.get('attempt_id'), str) and _UUID.fullmatch(value['attempt_id'])
                and isinstance(value.get('commit_id'), str) and _UUID.fullmatch(value['commit_id']),
                'READBACK_CHECKPOINT_FENCE_REQUIRED')
        client = ReadbackClient(session, opener=opener)
        try:
            health = client.once('health')
            ack = {'status': 'not_run'}
            if health.get('status') == 'observed' and health['initialized'] is True:
                ack = client.once('checkpoint_ack', commit_id=value['commit_id'],
                                  lease_id=value['attempt_id'])
            return {'status': 'readback_observed', 'source_sha256': SOURCE_SHA256,
                    'source_commit': SOURCE_COMMIT, 'fence_sha256': hashlib.sha256(original).hexdigest(),
                    'health': health, 'checkpoint_ack': ack, 'http_attempts': client.attempts,
                    'automatic_retry': False, 'fence_retired': False,
                    'original_commit': ('latest_commit_acknowledged' if ack.get('status') == 'observed'
                                        else 'history_unavailable_or_unconfirmed'),
                    'lease_release_verified': False, 'broker_calls': 0, 'credential_writes': 0}
        finally:
            require(_private_bytes(fence, workspace) == original, 'READBACK_FENCE_DRIFT')
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    workspace = Path.cwd().resolve()
    os.umask(0o077)
    owned_out = None
    try:
        # A new, owned directory; never replace a previous diagnostic result.
        out = Path(os.path.abspath(args.out))
        root = workspace / '.niulai-state'
        require(out.is_relative_to(root) and out.resolve().is_relative_to(root),
                'READBACK_PRIVATE_PATH_REQUIRED')
        for parent in (out, *out.parents):
            if parent == workspace:
                break
            require(not parent.is_symlink(), 'READBACK_PRIVATE_PATH_REQUIRED')
        out.mkdir(mode=0o700)
        owned_out = out
        policy = load_policy(root / 'config' / 'tiger.json', workspace)
        context = hidden_input()
        def timeout(signum, frame):
            raise TigerDeadline()
        signal.signal(signal.SIGALRM, timeout)
        signal.alarm(40)
        try:
            result = diagnose(workspace, policy, context, args.source)
        finally:
            signal.alarm(0)
        with (out / 'readback.json').open('x') as stream:
            json.dump(result, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Exception, TigerDeadline) as exc:
        failure = {**safe_failure(exc), 'automatic_retry': False, 'fence_retired': False,
                   'reconciliation_required': True}
        if owned_out is not None:
            try:
                with (owned_out / 'readback-failure.json').open('x') as stream:
                    json.dump(failure, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError:
                failure['diagnostic_record_written'] = False
        print(json.dumps(failure, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
