#!/usr/bin/env python3
"""Create future confidential UI evidence in a versioned ignored quarantine."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Union

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
PRIVATE_PREFIX = ("ui", "artifacts", "future-private-v1")
_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600
_TEMP_PREFIX = ".private-artifact-pending-"


class PrivateArtifactError(Exception):
    """Base error for rejected confidential artifact publication."""


class PrivateArtifactSecurityError(PrivateArtifactError):
    """A filesystem object did not satisfy the confidential-write contract."""


class PrivateArtifactSizeError(PrivateArtifactError):
    """Input exceeded the configured publication bound."""


class PrivateArtifactConflict(PrivateArtifactError):
    """The create-only destination already exists."""

    def __init__(self, destination: str):
        self.destination = destination
        super().__init__("destination_already_exists")


class PrivateArtifactOutcomeUnknown(PrivateArtifactError):
    """The create effect occurred but durable/readback confirmation failed."""

    def __init__(self, destination: str):
        self.destination = destination
        super().__init__("outcome_unknown_reconcile_required")


@dataclass(frozen=True)
class PublishedArtifact:
    """Metadata verified from the held final descriptor."""

    destination: str
    size: int
    sha256: str
    mode: int
    uid: int
    nlink: int


@dataclass(frozen=True)
class _FileState:
    dev: int
    ino: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int
    uid: int
    nlink: int


@dataclass(frozen=True)
class _Binding:
    parent_fd: int
    name: str
    dev: int
    ino: int
    exact_mode: int | None = None
    require_owner: bool = False


@dataclass(frozen=True)
class _CreatedDirectory:
    parent_fd: int
    name: str
    dev: int
    ino: int


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PrivateArtifactSecurityError(code)


def _state(info: os.stat_result) -> _FileState:
    return _FileState(
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        stat.S_IMODE(info.st_mode),
        info.st_uid,
        info.st_nlink,
    )


def _validate_max_bytes(max_bytes: int) -> None:
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("max_bytes_must_be_nonnegative_integer")


def _destination_parts(destination: Union[str, os.PathLike[str]]) -> tuple[str, ...]:
    if isinstance(destination, bytes):
        raise PrivateArtifactSecurityError("destination_must_be_text")
    try:
        raw = os.fspath(destination)
    except TypeError as error:
        raise PrivateArtifactSecurityError("destination_must_be_workspace_relative") from error
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise PrivateArtifactSecurityError("destination_must_be_workspace_relative")
    path = Path(raw)
    parts = path.parts
    _require(not path.is_absolute(), "destination_must_be_workspace_relative")
    _require(
        len(parts) >= len(PRIVATE_PREFIX) + 1
        and parts[:len(PRIVATE_PREFIX)] == PRIVATE_PREFIX,
        "destination_outside_future_private_namespace",
    )
    _require(all(part not in ("", ".", "..") for part in parts), "destination_path_unsafe")
    return parts


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_workspace(
    workspace_root: Union[str, os.PathLike[str]],
) -> tuple[int, list[int], list[_Binding]]:
    if isinstance(workspace_root, bytes):
        raise PrivateArtifactSecurityError("workspace_root_must_be_absolute")
    try:
        raw = os.fspath(workspace_root)
    except TypeError as error:
        raise PrivateArtifactSecurityError("workspace_root_must_be_absolute") from error
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise PrivateArtifactSecurityError("workspace_root_must_be_absolute")
    path = Path(raw)
    parts = path.parts
    _require(path.is_absolute() and parts and parts[0] == os.sep,
             "workspace_root_must_be_absolute")
    _require(all(part not in ("", ".", "..") for part in parts[1:]),
             "workspace_root_path_unsafe")

    descriptors: list[int] = []
    bindings: list[_Binding] = []
    try:
        descriptor = os.open(os.sep, _directory_flags())
        descriptors.append(descriptor)
        for component in parts[1:]:
            parent_fd = descriptor
            try:
                descriptor = os.open(component, _directory_flags(), dir_fd=parent_fd)
            except OSError as error:
                raise PrivateArtifactSecurityError("workspace_ancestor_unsafe") from error
            descriptors.append(descriptor)
            info = os.fstat(descriptor)
            _require(stat.S_ISDIR(info.st_mode), "workspace_ancestor_wrong_type")
            bindings.append(_Binding(parent_fd, component, info.st_dev, info.st_ino))
        info = os.fstat(descriptor)
        _require(info.st_uid == os.getuid(), "workspace_root_wrong_owner")
        _require(not stat.S_IMODE(info.st_mode) & 0o022,
                 "workspace_root_group_or_world_writable")
        return descriptor, descriptors, bindings
    except BaseException:
        for opened in reversed(descriptors):
            os.close(opened)
        raise


def _verify_bindings(bindings: list[_Binding]) -> None:
    for binding in bindings:
        try:
            info = os.stat(binding.name, dir_fd=binding.parent_fd, follow_symlinks=False)
        except OSError as error:
            raise PrivateArtifactSecurityError("directory_binding_changed") from error
        _require(stat.S_ISDIR(info.st_mode), "directory_binding_changed")
        _require((info.st_dev, info.st_ino) == (binding.dev, binding.ino),
                 "directory_binding_changed")
        if binding.require_owner:
            _require(info.st_uid == os.getuid(), "artifact_directory_wrong_owner")
        mode = stat.S_IMODE(info.st_mode)
        if binding.exact_mode is None and binding.require_owner:
            _require(not mode & 0o022, "artifact_directory_group_or_world_writable")
        elif binding.exact_mode is not None:
            _require(mode == binding.exact_mode, "artifact_directory_wrong_mode")


def _safe_remove_created_directory(created: _CreatedDirectory) -> None:
    try:
        info = os.stat(created.name, dir_fd=created.parent_fd, follow_symlinks=False)
        if (not stat.S_ISDIR(info.st_mode)
                or (info.st_dev, info.st_ino) != (created.dev, created.ino)):
            return
        os.rmdir(created.name, dir_fd=created.parent_fd)
    except OSError:
        pass


def _open_directory(
    parent_fd: int,
    name: str,
    *,
    exact_mode: int | None,
    create: bool = False,
) -> tuple[int, _Binding, _CreatedDirectory | None]:
    created = False
    created_identity: tuple[int, int] | None = None
    if create:
        try:
            os.mkdir(name, _DIRECTORY_MODE, dir_fd=parent_fd)
            created = True
            info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(),
                     "artifact_directory_create_failed")
            created_identity = (info.st_dev, info.st_ino)
            if stat.S_IMODE(info.st_mode) != _DIRECTORY_MODE:
                os.chmod(name, _DIRECTORY_MODE, dir_fd=parent_fd, follow_symlinks=False)
        except FileExistsError:
            pass
        except BaseException:
            if created and created_identity is not None:
                _safe_remove_created_directory(
                    _CreatedDirectory(parent_fd, name, *created_identity))
            raise
    try:
        descriptor = os.open(name, _directory_flags(), dir_fd=parent_fd)
    except OSError as error:
        if created and created_identity is not None:
            _safe_remove_created_directory(_CreatedDirectory(parent_fd, name, *created_identity))
        raise PrivateArtifactSecurityError("artifact_directory_unsafe") from error
    try:
        info = os.fstat(descriptor)
        _require(stat.S_ISDIR(info.st_mode), "artifact_directory_wrong_type")
        _require(info.st_uid == os.getuid(), "artifact_directory_wrong_owner")
        mode = stat.S_IMODE(info.st_mode)
        if exact_mode is None:
            _require(not mode & 0o022, "artifact_directory_group_or_world_writable")
        else:
            _require(mode == exact_mode, "artifact_directory_wrong_mode")
        if created_identity is not None:
            _require((info.st_dev, info.st_ino) == created_identity,
                     "artifact_directory_binding_changed")
        return (
            descriptor,
            _Binding(parent_fd, name, info.st_dev, info.st_ino, exact_mode, True),
            _CreatedDirectory(parent_fd, name, info.st_dev, info.st_ino) if created else None,
        )
    except BaseException:
        os.close(descriptor)
        if created and created_identity is not None:
            _safe_remove_created_directory(_CreatedDirectory(parent_fd, name, *created_identity))
        raise


def _open_regular(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise PrivateArtifactSecurityError("artifact_leaf_unsafe") from error
    try:
        info = os.fstat(descriptor)
        _require(stat.S_ISREG(info.st_mode), "artifact_leaf_wrong_type")
        _require(info.st_uid == os.getuid(), "artifact_leaf_wrong_owner")
        _require(info.st_nlink == 1, "artifact_leaf_hardlinked")
        _require(stat.S_IMODE(info.st_mode) == _FILE_MODE, "artifact_leaf_wrong_mode")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _name_state(parent_fd: int, name: str) -> _FileState:
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error:
        raise PrivateArtifactSecurityError("artifact_name_unavailable") from error
    _require(stat.S_ISREG(info.st_mode), "artifact_leaf_wrong_type")
    return _state(info)


def _create_temporary(parent_fd: int) -> tuple[int, str, _FileState]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    for _ in range(16):
        name = _TEMP_PREFIX + secrets.token_hex(16)
        try:
            descriptor = os.open(name, flags, _FILE_MODE, dir_fd=parent_fd)
        except FileExistsError:
            continue
        except OSError as error:
            raise PrivateArtifactSecurityError("artifact_temporary_create_failed") from error
        try:
            os.fchmod(descriptor, _FILE_MODE)
            info = os.fstat(descriptor)
            _require(stat.S_ISREG(info.st_mode), "artifact_temporary_wrong_type")
            state = _state(info)
            _require(state.uid == os.getuid(), "artifact_temporary_wrong_owner")
            _require(state.nlink == 1, "artifact_temporary_hardlinked")
            _require(state.mode == _FILE_MODE, "artifact_temporary_wrong_mode")
            return descriptor, name, state
        except BaseException:
            os.close(descriptor)
            try:
                os.unlink(name, dir_fd=parent_fd)
            except OSError:
                pass
            raise
    raise PrivateArtifactSecurityError("artifact_temporary_name_exhausted")


def _write_temporary(descriptor: int, payload: bytes) -> _FileState:
    """Write and sync without taking ownership of ``descriptor``."""

    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        _require(written > 0, "artifact_temporary_short_write")
        view = view[written:]
    os.fsync(descriptor)
    info = os.fstat(descriptor)
    _require(stat.S_ISREG(info.st_mode), "artifact_temporary_wrong_type")
    state = _state(info)
    _require(state.uid == os.getuid(), "artifact_temporary_wrong_owner")
    _require(state.nlink == 1, "artifact_temporary_hardlinked")
    _require(state.mode == _FILE_MODE, "artifact_temporary_wrong_mode")
    _require(state.size == len(payload), "artifact_temporary_size_mismatch")
    return state


def _same_inode(left: _FileState, right: _FileState) -> bool:
    return (left.dev, left.ino) == (right.dev, right.ino)


def _cleanup_owned_name(parent_fd: int, name: str, owned: _FileState) -> bool:
    try:
        current = _name_state(parent_fd, name)
        if not _same_inode(current, owned):
            return False
        os.unlink(name, dir_fd=parent_fd)
        return True
    except (OSError, PrivateArtifactError):
        return False


def _readback(
    parent_fd: int,
    name: str,
    destination: str,
    expected_size: int,
    expected_hash: str,
) -> PublishedArtifact:
    descriptor = _open_regular(parent_fd, name)
    try:
        initial = _state(os.fstat(descriptor))
        _require(initial.size == expected_size, "artifact_readback_size_mismatch")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, expected_size - total + 1))
            if not chunk:
                break
            total += len(chunk)
            _require(total <= expected_size, "artifact_readback_size_mismatch")
            digest.update(chunk)
        _require(total == expected_size, "artifact_readback_size_mismatch")
        actual_hash = digest.hexdigest()
        _require(actual_hash == expected_hash, "artifact_readback_content_mismatch")
        final = _state(os.fstat(descriptor))
        _require(final == initial, "artifact_readback_metadata_changed")
        resolved = _name_state(parent_fd, name)
        _require(resolved == final, "destination_changed_concurrently")
        return PublishedArtifact(destination, total, actual_hash, final.mode,
                                 final.uid, final.nlink)
    finally:
        os.close(descriptor)


def _coerce_payload(payload: Union[bytes, str]) -> bytes:
    if isinstance(payload, str):
        return payload.encode("utf-8", errors="strict")
    if isinstance(payload, bytes):
        return payload
    raise TypeError("payload_must_be_bytes_or_utf8_text")


def publish(
    destination: Union[str, os.PathLike[str]],
    payload: Union[bytes, str],
    *,
    workspace_root: Union[str, os.PathLike[str]] = ROOT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> PublishedArtifact:
    """Create one new artifact below ``ui/artifacts/future-private-v1``."""

    _validate_max_bytes(max_bytes)
    data = _coerce_payload(payload)
    if len(data) > max_bytes:
        raise PrivateArtifactSizeError("payload_too_large")
    parts = _destination_parts(destination)
    destination_text = "/".join(parts)
    expected_hash = hashlib.sha256(data).hexdigest()
    created_directories: list[_CreatedDirectory] = []
    effect_started = False

    with ExitStack() as stack:
        try:
            workspace_fd, workspace_descriptors, bindings = _open_workspace(workspace_root)
            for descriptor in workspace_descriptors:
                stack.callback(os.close, descriptor)
            ui_fd, ui_binding, _ = _open_directory(workspace_fd, "ui", exact_mode=None)
            stack.callback(os.close, ui_fd)
            bindings.append(ui_binding)
            _verify_bindings(bindings)
            artifacts_fd, binding, created = _open_directory(
                ui_fd, "artifacts", exact_mode=_DIRECTORY_MODE, create=True)
            stack.callback(os.close, artifacts_fd)
            bindings.append(binding)
            if created is not None:
                created_directories.append(created)
            parent_fd = artifacts_fd
            for component in parts[2:-1]:
                next_fd, binding, created = _open_directory(
                    parent_fd, component, exact_mode=_DIRECTORY_MODE, create=True)
                stack.callback(os.close, next_fd)
                bindings.append(binding)
                if created is not None:
                    created_directories.append(created)
                parent_fd = next_fd
            _verify_bindings(bindings)

            leaf = parts[-1]
            temporary_fd, temporary_name, temporary_owned = _create_temporary(parent_fd)
            temporary_exists = True
            try:
                published = _write_temporary(temporary_fd, data)
                _verify_bindings(bindings)
                try:
                    os.link(temporary_name, leaf, src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd, follow_symlinks=False)
                except FileExistsError as error:
                    raise PrivateArtifactConflict(destination_text) from error
                except OSError as error:
                    raise PrivateArtifactSecurityError("destination_no_clobber_failed") from error
                effect_started = True
                try:
                    linked = _name_state(parent_fd, leaf)
                    _require(_same_inode(linked, published), "published_link_identity_changed")
                    _require(linked.uid == os.getuid() and linked.mode == _FILE_MODE
                             and linked.nlink == 2, "published_link_metadata_invalid")
                    os.unlink(temporary_name, dir_fd=parent_fd)
                    temporary_exists = False
                    os.fsync(parent_fd)
                    result = _readback(parent_fd, leaf, destination_text,
                                       len(data), expected_hash)
                    _verify_bindings(bindings)
                    return result
                except BaseException as error:
                    if temporary_exists:
                        _cleanup_owned_name(parent_fd, temporary_name, temporary_owned)
                        temporary_exists = False
                    raise PrivateArtifactOutcomeUnknown(destination_text) from error
            finally:
                os.close(temporary_fd)
                if temporary_exists:
                    _cleanup_owned_name(parent_fd, temporary_name, temporary_owned)
        except BaseException:
            if not effect_started:
                for created in reversed(created_directories):
                    _safe_remove_created_directory(created)
            raise


def publish_from_staging(
    destination: Union[str, os.PathLike[str]],
    staging_path: Union[str, os.PathLike[str]],
    *,
    workspace_root: Union[str, os.PathLike[str]] = ROOT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> PublishedArtifact:
    """Read a stable exact-0600 staging file from a held FD and publish it."""

    _validate_max_bytes(max_bytes)
    if isinstance(staging_path, bytes):
        raise PrivateArtifactSecurityError("staging_path_must_be_text")
    try:
        raw = os.fspath(staging_path)
    except TypeError as error:
        raise PrivateArtifactSecurityError("staging_path_must_be_text") from error
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise PrivateArtifactSecurityError("staging_path_must_be_text")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(raw, flags)
    except OSError as error:
        raise PrivateArtifactSecurityError("staging_file_unsafe") from error
    try:
        before_info = os.fstat(descriptor)
        before = _state(before_info)
        _require(stat.S_ISREG(before_info.st_mode), "staging_file_wrong_type")
        _require(before.uid == os.getuid(), "staging_file_wrong_owner")
        _require(before.nlink == 1, "staging_file_hardlinked")
        _require(before.mode == _FILE_MODE, "staging_file_wrong_mode")
        if before.size > max_bytes:
            raise PrivateArtifactSizeError("staging_file_too_large")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise PrivateArtifactSizeError("staging_file_too_large")
            chunks.append(chunk)
        after_info = os.fstat(descriptor)
        after = _state(after_info)
        _require(stat.S_ISREG(after_info.st_mode), "staging_file_wrong_type")
        _require(after == before and after.size == total,
                 "staging_file_changed_during_read")
        payload = b"".join(chunks)
    finally:
        os.close(descriptor)
    return publish(destination, payload, workspace_root=workspace_root, max_bytes=max_bytes)


def _read_stdin(max_bytes: int) -> bytes:
    _validate_max_bytes(max_bytes)
    payload = sys.stdin.buffer.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise PrivateArtifactSizeError("stdin_payload_too_large")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="path below ui/artifacts/future-private-v1")
    parser.add_argument("--workspace", default=str(ROOT), help="absolute workspace root")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--stdin", action="store_true", help="publish bounded bytes from stdin")
    source.add_argument("--from-staging", help="read a validated private staging file")
    args = parser.parse_args(argv)

    try:
        if args.stdin:
            result = publish(args.destination, _read_stdin(args.max_bytes),
                             workspace_root=args.workspace, max_bytes=args.max_bytes)
        else:
            result = publish_from_staging(args.destination, args.from_staging,
                                          workspace_root=args.workspace,
                                          max_bytes=args.max_bytes)
    except PrivateArtifactOutcomeUnknown as error:
        print(json.dumps({"status": "PRIVATE_ARTIFACT_OUTCOME_UNKNOWN",
                          "code": "outcome_unknown_reconcile_required",
                          "destination": error.destination}, sort_keys=True))
        return 4
    except PrivateArtifactConflict as error:
        print(json.dumps({"status": "PRIVATE_ARTIFACT_CONFLICT",
                          "code": "destination_already_exists",
                          "destination": error.destination}, sort_keys=True))
        return 3
    except PrivateArtifactSizeError:
        print(json.dumps({"status": "PRIVATE_ARTIFACT_FAILED", "code": "size_limit"},
                         sort_keys=True))
        return 2
    except (PrivateArtifactError, OSError, ValueError, TypeError, UnicodeError):
        print(json.dumps({"status": "PRIVATE_ARTIFACT_FAILED",
                          "code": "validation_or_publish_failed"}, sort_keys=True))
        return 2

    print(json.dumps({"status": "PRIVATE_ARTIFACT_PUBLISHED",
                      "destination": result.destination}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
