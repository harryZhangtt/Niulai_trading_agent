"""Descriptor-relative owner-private no-replace publication primitives."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional


class CustodyError(RuntimeError):
    pass


class UnsafeRootError(CustodyError):
    pass


class AtomicWriteError(CustodyError):
    pass


WriteFn = Callable[[int, bytes], int]
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


@dataclass(frozen=True)
class PublishedFile:
    name: str
    sha256: str
    size: int


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _safe_name(name: str) -> None:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise CustodyError("UNSAFE_DESCRIPTOR_RELATIVE_NAME")


def _sync(fd: int) -> None:
    os.fsync(fd)
    full = getattr(fcntl, "F_FULLFSYNC", None)
    if full is not None:
        fcntl.fcntl(fd, full)


def _open_owner_private_root(path: str, expected_uid: Optional[int] = None) -> int:
    target = Path(path)
    if not target.is_absolute():
        raise UnsafeRootError("FIXED_ROOT_MUST_BE_ABSOLUTE")
    fd = os.open("/", _DIR_FLAGS)
    try:
        for component in target.parts[1:]:
            child = os.open(component, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        uid = os.getuid() if expected_uid is None else expected_uid
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
            raise UnsafeRootError("FIXED_ROOT_IDENTITY_OR_MODE")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _write_all(fd: int, payload: bytes, write_fn: WriteFn = os.write) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        try:
            written = write_fn(fd, view[offset:].tobytes())
        except OSError as exc:
            raise AtomicWriteError("WRITE_FAILED") from exc
        if written <= 0 or written > len(view) - offset:
            raise AtomicWriteError("WRITE_NO_PROGRESS_OR_INVALID_LENGTH")
        offset += written


def _reopen_hash(dir_fd: int, name: str, expected_uid: Optional[int] = None) -> PublishedFile:
    _safe_name(name)
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
    digest = hashlib.sha256(); size = 0
    try:
        info = os.fstat(fd); uid = os.getuid() if expected_uid is None else expected_uid
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or
                stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise AtomicWriteError("PUBLISHED_FILE_IDENTITY")
        while True:
            chunk = os.read(fd, 65536)
            if not chunk: break
            digest.update(chunk); size += len(chunk)
    finally:
        os.close(fd)
    return PublishedFile(name, digest.hexdigest(), size)


def _publish_one(dir_fd: int, name: str, payload: bytes, *, write_fn: WriteFn = os.write) -> PublishedFile:
    _safe_name(name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, 0o600, dir_fd=dir_fd)
    except OSError as exc:
        raise AtomicWriteError("NO_REPLACE_PUBLICATION_REFUSED") from exc
    complete = False
    try:
        _write_all(fd, payload, write_fn); _sync(fd); complete = True
    finally:
        os.close(fd)
        if not complete:
            try: os.unlink(name, dir_fd=dir_fd); _sync(dir_fd)
            except OSError: pass
    item = _reopen_hash(dir_fd, name)
    if item.sha256 != hashlib.sha256(payload).hexdigest() or item.size != len(payload):
        raise AtomicWriteError("REOPEN_HASH_OR_SIZE_MISMATCH")
    _sync(dir_fd)
    return item


def _publish_bundle(root: str, payloads: Mapping[str, bytes], marker: Mapping[str, object], *, write_fn: WriteFn = os.write) -> Dict[str, PublishedFile]:
    if "commit.json" in payloads: raise CustodyError("COMMIT_MARKER_RESERVED")
    dir_fd = _open_owner_private_root(root)
    published: Dict[str, PublishedFile] = {}
    try:
        for name in sorted(payloads):
            published[name] = _publish_one(dir_fd, name, payloads[name], write_fn=write_fn)
        bound = dict(marker)
        bound["files"] = {name: {"sha256": item.sha256, "size": item.size} for name, item in sorted(published.items())}
        published["commit.json"] = _publish_one(dir_fd, "commit.json", _canonical_json(bound), write_fn=write_fn)
        _sync(dir_fd)
        return published
    finally:
        os.close(dir_fd)


def _create_transient(root: str, name: str) -> tuple[int, int]:
    _safe_name(name); root_fd = _open_owner_private_root(root)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try: file_fd = os.open(name, flags, 0o600, dir_fd=root_fd)
    except BaseException: os.close(root_fd); raise
    return root_fd, file_fd


def _read_transient(file_fd: int, limit: int) -> bytes:
    if limit <= 0: raise CustodyError("TRANSIENT_LIMIT")
    os.lseek(file_fd, 0, os.SEEK_SET); chunks = []; total = 0
    while True:
        chunk = os.read(file_fd, min(65536, limit + 1 - total))
        if not chunk: break
        chunks.append(chunk); total += len(chunk)
        if total > limit: raise CustodyError("TRANSIENT_OUTPUT_TOO_LARGE")
    return b"".join(chunks)


def _destroy_transient(root_fd: int, file_fd: int, name: str) -> None:
    try: os.close(file_fd)
    finally:
        try: os.unlink(name, dir_fd=root_fd); _sync(root_fd)
        finally: os.close(root_fd)
