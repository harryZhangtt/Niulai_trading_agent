"""Small immutable, hashed artifact contract shared by fetchers and research."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_STATE = ROOT / '.niulai-state/reports/research-sources'
INVESTMENT_STATE = ROOT / '.niulai-state/reports/investment-research'
STATE_ROOTS = (SOURCE_STATE, INVESTMENT_STATE, ROOT / '.research-sources', ROOT / 'investment/runtime')
READ_ROOTS = (*STATE_ROOTS, ROOT / '.niulai-state/reports')


class SourceError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise SourceError(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def private_path(path, *, create=False):
    path = Path(os.path.abspath(path))
    roots = STATE_ROOTS if create else READ_ROOTS
    require(any(path.is_relative_to(root) and path != root for root in roots), 'ARTIFACT_PATH_REJECTED')
    require(path.resolve().is_relative_to(ROOT), 'ARTIFACT_PATH_REJECTED')
    for parent in [path, *path.parents]:
        if parent == ROOT:
            break
        require(not parent.is_symlink(), 'ARTIFACT_SYMLINK_REJECTED')
        if parent.exists():
            require(parent.stat().st_uid == os.getuid(), 'ARTIFACT_OWNER_REJECTED')
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for parent in [path, *path.parents]:
            if parent == ROOT or parent == ROOT / 'investment':
                break
            parent.chmod(0o700)
    return path


def save(directory, value, *, suffix='json'):
    raw = value if isinstance(value, bytes) else encoded(value)
    directory = private_path(directory, create=True)
    sha = hashlib.sha256(raw).hexdigest()
    path = directory / (sha + '.' + suffix)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        require(not path.is_symlink() and path.read_bytes() == raw, 'ARTIFACT_COLLISION')
    else:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return {'path': str(path), 'sha256': sha}


def read(ref, *, json_value=True):
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'ARTIFACT_REF_INVALID')
    path = private_path(ref['path'])
    require(path.is_file() and path.stat().st_size <= 8 * 1024 * 1024, 'ARTIFACT_INVALID')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ref['sha256'], 'ARTIFACT_HASH_MISMATCH')
    return json.loads(raw) if json_value else raw
