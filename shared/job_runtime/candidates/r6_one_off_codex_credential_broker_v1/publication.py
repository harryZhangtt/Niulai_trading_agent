"""Owner-private one-shot publication with a commit marker written last."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
from typing import Any, Callable, Mapping, Optional

from .contracts import BrokerError, PublishedExecution, canonical_json, sha256_buffer
from .mutable_json import wipe

_RAW_NAME = "catalog.raw.json"
_MEMBERSHIP_NAME = "catalog-membership.receipt.json"
_EXECUTION_NAME = "execution.receipt.json"
_COMMIT_NAME = "COMMITTED.json"
_LOCK_NAME = "execution.lock"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_root(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError:
        raise BrokerError("OUTPUT_ROOT_UNAVAILABLE", "UNKNOWN") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise BrokerError("OUTPUT_ROOT_REJECTED", "UNKNOWN")


def _ensure_root(path: Path) -> None:
    if path.exists() or path.is_symlink():
        _validate_root(path)
        return
    parent = path.parent
    if not parent.exists():
        parent.mkdir(mode=0o700, parents=True)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        _validate_root(path)
    _validate_root(path)
    _fsync_directory(path.parent)


def claim_one_shot(root: Path) -> None:
    _ensure_root(root)
    marker = root / _COMMIT_NAME
    lock = root / _LOCK_NAME
    if marker.exists() or marker.is_symlink():
        raise BrokerError("SECOND_EXECUTION_REJECTED")
    existing = tuple(path.name for path in root.iterdir())
    if existing:
        raise BrokerError("UNKNOWN_EXISTING_EXECUTION_FENCE", "UNKNOWN")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(lock), flags, 0o600)
    except FileExistsError:
        raise BrokerError("UNKNOWN_EXISTING_EXECUTION_FENCE", "UNKNOWN") from None
    except OSError:
        raise BrokerError("ONE_SHOT_CLAIM_FAILED", "UNKNOWN") from None
    try:
        _write_full(descriptor, memoryview(b"one-shot\n"), os.write)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(root)


def _write_full(descriptor: int, source: memoryview, write_fn: Callable[[int, Any], int]) -> None:
    offset = 0
    while offset < len(source):
        try:
            written = write_fn(descriptor, source[offset:])
        except OSError:
            raise BrokerError("PUBLICATION_WRITE_FAILED", "UNKNOWN") from None
        if type(written) is not int or written <= 0 or written > len(source) - offset:
            raise BrokerError("PUBLICATION_ZERO_OR_INVALID_WRITE", "UNKNOWN")
        offset += written


def _read_exact_mutable(path: Path, expected_size: int) -> bytearray:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError:
        raise BrokerError("PUBLICATION_REOPEN_FAILED", "UNKNOWN") from None
    value = bytearray(expected_size)
    probe = bytearray(1)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size != expected_size:
            raise BrokerError("PUBLICATION_REOPEN_IDENTITY_REJECTED", "UNKNOWN")
        offset = 0
        while offset < expected_size:
            count = os.readv(descriptor, [memoryview(value)[offset:]])
            if count <= 0:
                raise BrokerError("PUBLICATION_REOPEN_SHORT_READ", "UNKNOWN")
            offset += count
        if os.readv(descriptor, [probe]) != 0:
            raise BrokerError("PUBLICATION_REOPEN_SIZE_CHANGED", "UNKNOWN")
        return value
    except BaseException:
        wipe(value)
        raise
    finally:
        wipe(probe)
        os.close(descriptor)


def _fault(callback: Optional[Callable[[str], None]], stage: str) -> None:
    if callback is not None:
        callback(stage)


def _commit_one(root: Path, name: str, content: Any, *, write_fn: Callable[[int, Any], int], fault: Optional[Callable[[str], None]]) -> tuple[str, int, Path]:
    final = root / name
    staging = root / ("." + name + ".staging")
    if final.exists() or final.is_symlink() or staging.exists() or staging.is_symlink():
        raise BrokerError("PUBLICATION_NO_REPLACE_REJECTED", "UNKNOWN")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(str(staging), flags, 0o600)
        view = memoryview(content)
        try:
            _write_full(descriptor, view, write_fn)
        finally:
            view.release()
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        _fault(fault, "after_file_fsync:" + name)
        try:
            os.link(str(staging), str(final), follow_symlinks=False)
        except FileExistsError:
            raise BrokerError("PUBLICATION_NO_REPLACE_REJECTED", "UNKNOWN") from None
        except OSError:
            raise BrokerError("PUBLICATION_LINK_FAILED", "UNKNOWN") from None
        os.unlink(staging)
        _fsync_directory(root)
        _fault(fault, "after_parent_fsync:" + name)
        verify = _read_exact_mutable(final, len(content))
        try:
            digest = sha256_buffer(verify)
        finally:
            wipe(verify)
        expected = sha256_buffer(content)
        if digest != expected:
            raise BrokerError("PUBLICATION_REOPEN_HASH_MISMATCH", "UNKNOWN")
        _fault(fault, "after_reopen_hash:" + name)
        return digest, len(content), final
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def publish(
    root: Path,
    raw_catalog: bytearray,
    membership: Mapping[str, Any],
    execution: Mapping[str, Any],
    *,
    write_fn: Callable[[int, Any], int] = os.write,
    fault: Optional[Callable[[str], None]] = None,
) -> PublishedExecution:
    if type(raw_catalog) is not bytearray or not raw_catalog:
        raise BrokerError("RAW_CATALOG_CUSTODY_REJECTED", "UNKNOWN")
    _validate_root(root)
    membership_bytes = canonical_json(membership)
    execution_bytes = canonical_json(execution)
    try:
        raw_digest, raw_size, raw_path = _commit_one(root, _RAW_NAME, raw_catalog, write_fn=write_fn, fault=fault)
        membership_digest, membership_size, membership_path = _commit_one(root, _MEMBERSHIP_NAME, membership_bytes, write_fn=write_fn, fault=fault)
        execution_digest, execution_size, execution_path = _commit_one(root, _EXECUTION_NAME, execution_bytes, write_fn=write_fn, fault=fault)
        marker = {
            "schema_version": "r6-one-off-codex-credential-broker-commit-v1",
            "committed": True,
            "artifacts": {
                "raw_catalog": {"bytes": raw_size, "sha256": raw_digest},
                "membership_receipt": {"bytes": membership_size, "sha256": membership_digest},
                "execution_receipt": {"bytes": execution_size, "sha256": execution_digest},
            },
        }
        marker_bytes = canonical_json(marker)
        _, _, marker_path = _commit_one(root, _COMMIT_NAME, marker_bytes, write_fn=write_fn, fault=fault)
        return PublishedExecution(raw_path, membership_path, execution_path, marker_path, raw_digest, membership_digest, execution_digest)
    except BrokerError:
        raise
    except Exception:
        raise BrokerError("PUBLICATION_UNCERTAIN", "UNKNOWN") from None
    finally:
        membership_bytes = b""
        execution_bytes = b""


__all__ = []
