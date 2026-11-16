"""Descriptor-held, no-follow, owner-private custody and admission ledger."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Dict, Iterable, Mapping, Tuple

from .contracts import ContractError, admission_key, canonical_bytes, require

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_ROLES = frozenset(("binary", "argv", "config", "parser", "prompt", "raw", "terminal", "cleanup"))


class CustodyError(ContractError):
    """Fixed, path-free custody failure."""


def _custody_require(condition: bool, code: str) -> None:
    if not condition:
        raise CustodyError(code)


def _safe_name(value: Any) -> str:
    _custody_require(type(value) is str and 1 <= len(value) <= 96 and
                     value not in (".", "..") and "/" not in value and
                     "\\" not in value and "\x00" not in value,
                     "CUSTODY_NAME_INVALID")
    return value


def _private_dir(path: Path, create: bool = False) -> int:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        before = path.lstat()
        fd = os.open(path, _DIR_FLAGS)
        after = os.fstat(fd)
    except OSError:
        raise CustodyError("CUSTODY_DIRECTORY_OPEN_FAILED") from None
    if (not stat.S_ISDIR(before.st_mode) or not stat.S_ISDIR(after.st_mode) or
            before.st_dev != after.st_dev or before.st_ino != after.st_ino or
            after.st_uid != os.getuid() or stat.S_IMODE(after.st_mode) != 0o700):
        os.close(fd)
        raise CustodyError("CUSTODY_DIRECTORY_UNSAFE")
    return fd


def _read_fd(fd: int, maximum: int = 65536) -> bytes:
    try:
        position = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(16384, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise CustodyError("CUSTODY_FILE_TOO_LARGE")
        os.lseek(fd, position, os.SEEK_SET)
        return b"".join(chunks)
    except CustodyError:
        raise
    except OSError:
        raise CustodyError("CUSTODY_READ_FAILED") from None


def _write_all(fd: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        try:
            written = os.write(fd, value[offset:])
        except OSError:
            raise CustodyError("CUSTODY_WRITE_FAILED") from None
        _custody_require(written > 0, "CUSTODY_WRITE_FAILED")
        offset += written


def atomic_private_write(root: Path, name: str, value: bytes) -> str:
    """Publish one immutable private file without following or replacing names."""
    _safe_name(name)
    _custody_require(type(value) is bytes and 1 <= len(value) <= 65536,
                     "CUSTODY_VALUE_INVALID")
    directory_fd = _private_dir(Path(root), create=True)
    stage = ".stage-" + secrets.token_hex(16)
    stage_fd = -1
    linked = False
    try:
        stage_fd = os.open(stage, _WRITE_FLAGS, 0o600, dir_fd=directory_fd)
        _write_all(stage_fd, value)
        os.fsync(stage_fd)
        meta = os.fstat(stage_fd)
        _custody_require(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid() and
                         stat.S_IMODE(meta.st_mode) == 0o600 and meta.st_nlink == 1 and
                         meta.st_size == len(value), "CUSTODY_STAGE_UNSAFE")
        os.close(stage_fd)
        stage_fd = -1
        try:
            os.link(stage, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                    follow_symlinks=False)
            linked = True
        except FileExistsError:
            raise CustodyError("CUSTODY_NO_OVERWRITE") from None
        except OSError:
            raise CustodyError("CUSTODY_PUBLISH_FAILED") from None
        os.fsync(directory_fd)
        os.unlink(stage, dir_fd=directory_fd)
        os.fsync(directory_fd)
        return hashlib.sha256(value).hexdigest()
    finally:
        if stage_fd >= 0:
            os.close(stage_fd)
        if not linked:
            try:
                os.unlink(stage, dir_fd=directory_fd)
            except OSError:
                pass
        os.close(directory_fd)


@dataclass(frozen=True)
class CustodyDescriptor:
    role: str
    name: str
    sha256: str
    bytes: int

    def public(self) -> Dict[str, Any]:
        return {"role": self.role, "name": self.name,
                "sha256": self.sha256, "bytes": self.bytes}


class HeldFile:
    def __init__(self, role: str, name: str, fd: int, directory_fd: int,
                 metadata: Tuple[int, ...], descriptor: CustodyDescriptor):
        self.role = role
        self.name = name
        self._fd = fd
        self._directory_fd = directory_fd
        self._metadata = metadata
        self.descriptor = descriptor
        self.closed = False

    @staticmethod
    def _metadata_of(value: os.stat_result) -> Tuple[int, ...]:
        return (value.st_dev, value.st_ino, value.st_uid, value.st_mode,
                value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def verify(self) -> None:
        _custody_require(not self.closed, "CUSTODY_DESCRIPTOR_CLOSED")
        try:
            held = os.fstat(self._fd)
            named = os.stat(self.name, dir_fd=self._directory_fd, follow_symlinks=False)
        except OSError:
            raise CustodyError("CUSTODY_DESCRIPTOR_UNSTABLE") from None
        _custody_require(self._metadata_of(held) == self._metadata ==
                         self._metadata_of(named), "CUSTODY_DESCRIPTOR_UNSTABLE")
        _custody_require(hashlib.sha256(_read_fd(self._fd)).hexdigest() ==
                         self.descriptor.sha256, "CUSTODY_DIGEST_DRIFT")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        os.close(self._fd)
        os.close(self._directory_fd)


class CustodySession:
    """Holds verified descriptors open across one provider-free execution."""

    def __init__(self, root: Path, held: Mapping[str, HeldFile]):
        self.root = Path(root)
        self._held = dict(held)
        self.closed = False

    @classmethod
    def seal(cls, root: Path, role_names: Mapping[str, str]) -> "CustodySession":
        _custody_require(type(role_names) is dict and role_names, "CUSTODY_ROLES_INVALID")
        directory_fd = _private_dir(Path(root), create=False)
        held = {}
        try:
            for role, name in sorted(role_names.items()):
                _custody_require(role in _ROLES and role not in held,
                                 "CUSTODY_ROLE_INVALID")
                _safe_name(name)
                fd = -1
                duplicate_dir = -1
                try:
                    try:
                        fd = os.open(name, _FILE_FLAGS, dir_fd=directory_fd)
                    except OSError:
                        raise CustodyError("CUSTODY_FILE_OPEN_FAILED") from None
                    meta = os.fstat(fd)
                    _custody_require(stat.S_ISREG(meta.st_mode) and
                                     meta.st_uid == os.getuid() and
                                     stat.S_IMODE(meta.st_mode) == 0o600 and
                                     meta.st_nlink == 1 and 1 <= meta.st_size <= 65536,
                                     "CUSTODY_FILE_UNSAFE")
                    raw = _read_fd(fd)
                    descriptor = CustodyDescriptor(
                        role, name, hashlib.sha256(raw).hexdigest(), len(raw))
                    duplicate_dir = os.dup(directory_fd)
                    held[role] = HeldFile(
                        role, name, fd, duplicate_dir,
                        HeldFile._metadata_of(meta), descriptor)
                    fd = duplicate_dir = -1
                finally:
                    if fd >= 0:
                        os.close(fd)
                    if duplicate_dir >= 0:
                        os.close(duplicate_dir)
            return cls(Path(root), held)
        except BaseException:
            for value in held.values():
                value.close()
            raise
        finally:
            os.close(directory_fd)

    @property
    def descriptors(self) -> Tuple[CustodyDescriptor, ...]:
        return tuple(self._held[key].descriptor for key in sorted(self._held))

    def descriptor(self, role: str) -> CustodyDescriptor:
        _custody_require(not self.closed and role in self._held,
                         "CUSTODY_ROLE_NOT_HELD")
        return self._held[role].descriptor

    def verify(self) -> None:
        _custody_require(not self.closed, "CUSTODY_SESSION_CLOSED")
        for value in self._held.values():
            value.verify()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for value in self._held.values():
            value.close()

    def __enter__(self) -> "CustodySession":
        self.verify()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        self.close()
        return False


class AdmissionLedger:
    """Durable exact single-use admission before an injected forward."""

    def __init__(self, root: Path):
        self.root = Path(root)
        fd = _private_dir(self.root, create=True)
        os.close(fd)

    def admit(self, operation_id: str, request_fingerprint: str,
              attempt_id: str) -> Dict[str, Any]:
        key = admission_key(operation_id, request_fingerprint)
        receipt = {
            "version": 1, "admission_key": key, "operation_id": operation_id,
            "request_fingerprint": request_fingerprint, "attempt_id": attempt_id,
            "single_use": True, "durable_before_forward": True,
        }
        atomic_private_write(self.root, key + ".json", canonical_bytes(receipt))
        return receipt


__all__ = [
    "AdmissionLedger", "CustodyDescriptor", "CustodyError", "CustodySession",
    "HeldFile", "atomic_private_write",
]
