"""Small immutable, hashed artifact contract shared by fetchers and research."""
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
SOURCE_STATE = ROOT / '.niulai-state/reports/research-sources'
INVESTMENT_STATE = ROOT / '.niulai-state/reports/investment-research'
STATE_ROOTS = (SOURCE_STATE, INVESTMENT_STATE, ROOT / '.research-sources', ROOT / 'investment/runtime')
READ_ROOTS = (*STATE_ROOTS, ROOT / '.niulai-state/reports')
_MAX_BYTES = 8 * 1024 * 1024
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDWR | os.O_NOFOLLOW


class SourceError(ValueError):
    pass


class PublicationOutcomeUnknown(SourceError):
    """The namespace mutation happened but its directory fsync was not confirmed."""

    def __init__(self, evidence):
        super().__init__('ARTIFACT_PUBLICATION_OUTCOME_UNKNOWN')
        self.evidence = evidence


def require(ok, code):
    if not ok:
        raise SourceError(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def _absolute_private_path(path, *, create, allow_root=False):
    path = Path(os.path.abspath(os.fspath(path)))
    roots = STATE_ROOTS if create else READ_ROOTS
    require(any(path == root or path.is_relative_to(root) for root in roots), 'ARTIFACT_PATH_REJECTED')
    if not allow_root:
        require(all(path != root for root in roots), 'ARTIFACT_PATH_REJECTED')
    return path


def _component_error(exc, parent_fd=None, name=None):
    if exc.errno == errno.ELOOP:
        raise SourceError('ARTIFACT_SYMLINK_REJECTED') from None
    if exc.errno == errno.ENOTDIR:
        if parent_fd is not None and name is not None:
            try:
                details = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if stat.S_ISLNK(details.st_mode):
                    raise SourceError('ARTIFACT_SYMLINK_REJECTED') from None
            except FileNotFoundError:
                pass
        raise SourceError('ARTIFACT_PATH_REJECTED') from None
    raise exc


def _open_directory(path, *, create=False, exact=False):
    """Walk from filesystem root with one held descriptor per component."""
    path = _absolute_private_path(path, create=create, allow_root=True)
    descriptor = os.open('/', _DIR_FLAGS)
    current = Path('/')
    try:
        for part in path.parts[1:]:
            child_path = current / part
            created = False
            created_identity = None
            try:
                child = os.open(part, _DIR_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                require(child_path == ROOT or child_path.is_relative_to(ROOT), 'ARTIFACT_PATH_REJECTED')
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                    created = True
                except FileExistsError:
                    pass
                if created:
                    # Extreme umasks can create mode 000. Change only the inode
                    # this invocation proved it created, then reopen no-follow.
                    created_identity = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                    require(stat.S_ISDIR(created_identity.st_mode)
                            and created_identity.st_uid == os.getuid(), 'ARTIFACT_OWNER_REJECTED')
                    os.chmod(part, 0o700, dir_fd=descriptor, follow_symlinks=False)
                try:
                    child = os.open(part, _DIR_FLAGS, dir_fd=descriptor)
                except OSError as exc:
                    _component_error(exc, descriptor, part)
                if created:
                    reopened = os.fstat(child)
                    require((reopened.st_dev, reopened.st_ino) ==
                            (created_identity.st_dev, created_identity.st_ino), 'ARTIFACT_PATH_RACE_REJECTED')
            except OSError as exc:
                _component_error(exc, descriptor, part)
            details = os.fstat(child)
            require(stat.S_ISDIR(details.st_mode), 'ARTIFACT_PATH_REJECTED')
            if child_path == ROOT or child_path.is_relative_to(ROOT):
                require(details.st_uid == os.getuid(), 'ARTIFACT_OWNER_REJECTED')
            os.close(descriptor)
            descriptor = child
            current = child_path
        details = os.fstat(descriptor)
        if exact:
            require(stat.S_IMODE(details.st_mode) == 0o700, 'ARTIFACT_DIRECTORY_MODE_REJECTED')
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _stat_entry(parent_fd, name):
    try:
        details = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    require(not stat.S_ISLNK(details.st_mode), 'ARTIFACT_SYMLINK_REJECTED')
    require(details.st_uid == os.getuid(), 'ARTIFACT_OWNER_REJECTED')
    return details


def _open_parent(path, *, create):
    path = _absolute_private_path(path, create=create)
    require(path.name not in ('', '.', '..'), 'ARTIFACT_PATH_REJECTED')
    return path, _open_directory(path.parent, create=create, exact=create)


def _path_matches_fd(path, descriptor):
    reopened = _open_directory(path, create=False, exact=False)
    try:
        expected, actual = os.fstat(descriptor), os.fstat(reopened)
        require((expected.st_dev, expected.st_ino) == (actual.st_dev, actual.st_ino),
                'ARTIFACT_PATH_RACE_REJECTED')
    finally:
        os.close(reopened)


def private_path(path, *, create=False):
    """Validate an approved path without chmodding pre-existing history."""
    path = _absolute_private_path(path, create=create)
    if create:
        descriptor = _open_directory(path, create=True, exact=True)
        os.close(descriptor)
        return path
    try:
        parent = _open_directory(path.parent, create=False, exact=False)
    except FileNotFoundError:
        return path
    try:
        details = _stat_entry(parent, path.name)
        if details is not None:
            require(stat.S_ISDIR(details.st_mode) or stat.S_ISREG(details.st_mode), 'ARTIFACT_PATH_REJECTED')
    finally:
        os.close(parent)
    return path


def _write_all(descriptor, raw):
    view = memoryview(raw)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError('short private artifact write')
        view = view[written:]


def _read_fd(descriptor, *, limit=_MAX_BYTES):
    details = os.fstat(descriptor)
    require(stat.S_ISREG(details.st_mode) and details.st_size <= limit, 'ARTIFACT_INVALID')
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks = []
    remaining = details.st_size
    while remaining:
        chunk = os.read(descriptor, min(65536, remaining))
        require(bool(chunk), 'ARTIFACT_INVALID')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _new_temp(parent_fd, prefix):
    for _ in range(128):
        name = prefix + secrets.token_hex(16)
        try:
            descriptor = os.open(name, _FILE_FLAGS | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd)
        except FileExistsError:
            continue
        try:
            os.fchmod(descriptor, 0o600)
            details = os.fstat(descriptor)
            require(stat.S_ISREG(details.st_mode) and details.st_uid == os.getuid()
                    and stat.S_IMODE(details.st_mode) == 0o600 and details.st_nlink == 1,
                    'ARTIFACT_TEMP_MODE_REJECTED')
            return name, descriptor, details
        except BaseException:
            os.close(descriptor)
            try:
                os.unlink(name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            raise
    raise SourceError('ARTIFACT_TEMP_CREATE_FAILED')


def _verify_pending(parent_fd, name, descriptor, created, raw):
    current = os.fstat(descriptor)
    entry = _stat_entry(parent_fd, name)
    require(entry is not None and stat.S_ISREG(current.st_mode) and stat.S_ISREG(entry.st_mode),
            'ARTIFACT_TEMP_CHANGED')
    require((current.st_dev, current.st_ino) == (created.st_dev, created.st_ino)
            and (entry.st_dev, entry.st_ino) == (current.st_dev, current.st_ino),
            'ARTIFACT_TEMP_CHANGED')
    require(current.st_uid == os.getuid() and entry.st_uid == os.getuid()
            and current.st_nlink == entry.st_nlink == 1
            and stat.S_IMODE(current.st_mode) == stat.S_IMODE(entry.st_mode) == 0o600
            and current.st_size == entry.st_size == len(raw), 'ARTIFACT_TEMP_CHANGED')
    require(hashlib.sha256(_read_fd(descriptor)).digest() == hashlib.sha256(raw).digest(),
            'ARTIFACT_TEMP_CHANGED')


def _open_regular(parent_fd, name, *, strict_private=False):
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as exc:
        _component_error(exc, parent_fd, name)
    details = os.fstat(descriptor)
    try:
        require(stat.S_ISREG(details.st_mode) and details.st_uid == os.getuid(), 'ARTIFACT_INVALID')
        if strict_private:
            require(stat.S_IMODE(details.st_mode) == 0o600 and details.st_nlink == 1,
                    'ARTIFACT_EXISTING_FILE_REJECTED')
        return descriptor, details
    except BaseException:
        os.close(descriptor)
        raise


def _verify_named_private_artifact(parent_fd, name, raw, *, expected_identity=None):
    """Bind one private namespace entry to the bytes and inode observed here."""
    descriptor, opened = _open_regular(parent_fd, name, strict_private=True)
    try:
        observed = _read_fd(descriptor)
        current = os.fstat(descriptor)
        entry = _stat_entry(parent_fd, name)
        require(entry is not None and stat.S_ISREG(entry.st_mode),
                'ARTIFACT_EXISTING_FILE_REJECTED')
        require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino)
                == (entry.st_dev, entry.st_ino), 'ARTIFACT_NAMESPACE_CHANGED')
        if expected_identity is not None:
            require((current.st_dev, current.st_ino) == expected_identity,
                    'ARTIFACT_NAMESPACE_CHANGED')
        require(current.st_uid == entry.st_uid == os.getuid()
                and current.st_nlink == entry.st_nlink == 1
                and stat.S_IMODE(current.st_mode) == stat.S_IMODE(entry.st_mode) == 0o600,
                'ARTIFACT_EXISTING_FILE_REJECTED')
        require(observed == raw, 'ARTIFACT_COLLISION')
        return current
    finally:
        os.close(descriptor)


def _publication_evidence(path, parent_fd, expected_sha256, operation):
    evidence = {'operation': operation, 'path': str(path), 'expected_sha256': expected_sha256,
                'destination_observed': False, 'replay_safe': False}
    try:
        descriptor, details = _open_regular(parent_fd, path.name)
        try:
            raw = _read_fd(descriptor)
            evidence.update(destination_observed=True,
                            observed_sha256=hashlib.sha256(raw).hexdigest(),
                            matches_expected=hashlib.sha256(raw).hexdigest() == expected_sha256,
                            mode=oct(stat.S_IMODE(details.st_mode)), nlink=details.st_nlink)
        finally:
            os.close(descriptor)
    except (OSError, SourceError):
        evidence['observation'] = 'destination_unavailable_or_invalid'
    return evidence


def _unknown(path, parent_fd, raw, operation, cause):
    raise PublicationOutcomeUnknown(
        _publication_evidence(path, parent_fd, hashlib.sha256(raw).hexdigest(), operation)) from cause


def atomic_write_private(path, value):
    """Atomically replace one private pointer; fsync failure is an unknown outcome."""
    raw = value if isinstance(value, bytes) else encoded(value)
    require(isinstance(raw, bytes), 'ARTIFACT_VALUE_INVALID')
    require(len(raw) <= _MAX_BYTES, 'ARTIFACT_TOO_LARGE')
    path, parent_fd = _open_parent(path, create=True)
    pending, descriptor, created = _new_temp(parent_fd, '.' + path.name + '.pending-')
    replaced = False
    try:
        prior = _stat_entry(parent_fd, path.name)
        if prior is not None:
            require(stat.S_ISREG(prior.st_mode), 'ARTIFACT_PATH_REJECTED')
        _write_all(descriptor, raw)
        os.fsync(descriptor)
        _verify_pending(parent_fd, pending, descriptor, created, raw)
        os.fsync(descriptor)
        _path_matches_fd(path.parent, parent_fd)
        current = _stat_entry(parent_fd, path.name)
        if current is not None:
            require(stat.S_ISREG(current.st_mode), 'ARTIFACT_PATH_REJECTED')
        os.replace(pending, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        replaced = True
        try:
            os.fsync(parent_fd)
            _path_matches_fd(path.parent, parent_fd)
        except (OSError, SourceError) as exc:
            _unknown(path, parent_fd, raw, 'atomic_replace', exc)
        return path
    finally:
        os.close(descriptor)
        if not replaced:
            try:
                os.unlink(pending, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def save(directory, value, *, suffix='json'):
    """Publish immutable content by no-clobber hard link and durable directory fsync."""
    raw = value if isinstance(value, bytes) else encoded(value)
    require(isinstance(suffix, str) and re.fullmatch(r'[a-z0-9]{1,16}', suffix), 'ARTIFACT_SUFFIX_INVALID')
    require(len(raw) <= _MAX_BYTES, 'ARTIFACT_TOO_LARGE')
    directory = _absolute_private_path(directory, create=True, allow_root=True)
    parent_fd = _open_directory(directory, create=True, exact=True)
    sha = hashlib.sha256(raw).hexdigest()
    name = sha + '.' + suffix
    path = directory / name
    pending, descriptor, created = _new_temp(parent_fd, '.pending-')
    linked = False
    pending_present = True
    try:
        _write_all(descriptor, raw)
        os.fsync(descriptor)
        _verify_pending(parent_fd, pending, descriptor, created, raw)
        _path_matches_fd(directory, parent_fd)
        try:
            os.link(pending, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd,
                    follow_symlinks=False)
            linked = True
        except FileExistsError:
            existing_identity = None
            for attempt in range(101):
                candidate, details = _open_regular(parent_fd, name)
                os.close(candidate)
                if stat.S_IMODE(details.st_mode) == 0o600 and details.st_nlink == 1:
                    existing_identity = (details.st_dev, details.st_ino)
                    break
                if details.st_nlink > 1 and attempt < 100:
                    time.sleep(0.001)
                    continue
                raise SourceError('ARTIFACT_EXISTING_FILE_REJECTED')
            _verify_named_private_artifact(
                parent_fd, name, raw, expected_identity=existing_identity)
            os.unlink(pending, dir_fd=parent_fd)
            pending_present = False
            _path_matches_fd(directory, parent_fd)
            return {'path': str(path), 'sha256': sha}
        try:
            os.unlink(pending, dir_fd=parent_fd)
            pending_present = False
            os.fsync(parent_fd)
            _path_matches_fd(directory, parent_fd)
            _verify_named_private_artifact(
                parent_fd, name, raw,
                expected_identity=(created.st_dev, created.st_ino))
        except (OSError, SourceError) as exc:
            _unknown(path, parent_fd, raw, 'hard_link_publish', exc)
        return {'path': str(path), 'sha256': sha}
    finally:
        os.close(descriptor)
        if not linked and pending_present:
            try:
                os.unlink(pending, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def publish_json_command(path, command, *, validator, timeout=120):
    """Buffer a producer privately; publish only successful, validated JSON."""
    require(isinstance(command, (list, tuple)) and command
            and all(isinstance(part, str) and part for part in command), 'ARTIFACT_PRODUCER_COMMAND_INVALID')
    require(callable(validator), 'ARTIFACT_VALIDATOR_INVALID')
    path, parent_fd = _open_parent(path, create=True)
    pending, descriptor, created = _new_temp(parent_fd, '.producer-')
    try:
        try:
            result = subprocess.run(list(command), stdout=descriptor, stderr=subprocess.PIPE,
                                    timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise SourceError('ARTIFACT_PRODUCER_FAILED') from None
        require(result.returncode == 0, 'ARTIFACT_PRODUCER_FAILED')
        os.fsync(descriptor)
        raw = _read_fd(descriptor)
        _verify_pending(parent_fd, pending, descriptor, created, raw)
        try:
            value = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SourceError('ARTIFACT_PRODUCER_JSON_INVALID') from None
        validator(value)
        # Publish the exact producer inode whose bytes were parsed and validated.
        _verify_pending(parent_fd, pending, descriptor, created, raw)
        os.fsync(descriptor)
        _path_matches_fd(path.parent, parent_fd)
        current = _stat_entry(parent_fd, path.name)
        if current is not None:
            require(stat.S_ISREG(current.st_mode), 'ARTIFACT_PATH_REJECTED')
        os.replace(pending, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        try:
            os.fsync(parent_fd)
            _path_matches_fd(path.parent, parent_fd)
        except (OSError, SourceError) as exc:
            _unknown(path, parent_fd, raw, 'producer_replace', exc)
        return value
    finally:
        os.close(descriptor)
        try:
            os.unlink(pending, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        os.close(parent_fd)


def read(ref, *, json_value=True):
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'ARTIFACT_REF_INVALID')
    path, parent_fd = _open_parent(ref['path'], create=False)
    try:
        descriptor, details = _open_regular(parent_fd, path.name)
        try:
            require(details.st_size <= _MAX_BYTES, 'ARTIFACT_INVALID')
            raw = _read_fd(descriptor)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)
    require(hashlib.sha256(raw).hexdigest() == ref['sha256'], 'ARTIFACT_HASH_MISMATCH')
    return json.loads(raw) if json_value else raw
