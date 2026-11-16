"""Sanitized allowlist publication with atomic no-overwrite semantics."""
from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Dict, Tuple

from .contracts import (
    ContractError, PUBLIC_ALLOWLIST, canonical_bytes, validate_evidence,
    validate_publication_receipt,
)

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_RENAME_EXCL = 0x00000004


class PublicationError(ContractError):
    """Fixed, content-free publication failure."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PublicationError(code)


def _directory(path: Path) -> int:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        before = path.lstat()
        fd = os.open(path, _DIR_FLAGS)
        after = os.fstat(fd)
    except OSError:
        raise PublicationError("PUBLICATION_DIRECTORY_OPEN_FAILED") from None
    if (not stat.S_ISDIR(before.st_mode) or before.st_ino != after.st_ino or
            before.st_dev != after.st_dev or after.st_uid != os.getuid() or
            stat.S_IMODE(after.st_mode) != 0o700):
        os.close(fd)
        raise PublicationError("PUBLICATION_DIRECTORY_UNSAFE")
    return fd


def _write_all(fd: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        try:
            written = os.write(fd, value[offset:])
        except OSError:
            raise PublicationError("PUBLICATION_WRITE_FAILED") from None
        _require(written > 0, "PUBLICATION_WRITE_FAILED")
        offset += written


def _read_named(directory_fd: int, name: str) -> bytes:
    fd = -1
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=directory_fd)
        meta = os.fstat(fd)
        _require(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid() and
                 stat.S_IMODE(meta.st_mode) == 0o600 and meta.st_nlink == 1 and
                 2 <= meta.st_size <= 65536, "PUBLICATION_STAGE_UNSAFE")
        chunks = []
        while True:
            chunk = os.read(fd, 16384)
            if not chunk:
                break
            chunks.append(chunk)
            _require(sum(len(item) for item in chunks) <= 65536,
                     "PUBLICATION_STAGE_UNSAFE")
        return b"".join(chunks)
    except PublicationError:
        raise
    except OSError:
        raise PublicationError("PUBLICATION_STAGE_READ_FAILED") from None
    finally:
        if fd >= 0:
            os.close(fd)


def _rename_exclusive(directory_fd: int, source: str, destination: str) -> str:
    """Use Darwin renamex_np(RENAME_EXCL), with atomic link fallback elsewhere."""
    library_name = ctypes.util.find_library("c")
    if library_name:
        library = ctypes.CDLL(library_name, use_errno=True)
        function = getattr(library, "renameatx_np", None)
        if function is not None:
            function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                                 ctypes.c_char_p, ctypes.c_uint]
            function.restype = ctypes.c_int
            result = function(directory_fd, source.encode("utf-8"), directory_fd,
                              destination.encode("utf-8"), _RENAME_EXCL)
            if result == 0:
                return "RENAME_EXCL"
            error = ctypes.get_errno()
            if error == getattr(os, "EEXIST", 17):
                raise PublicationError("PUBLICATION_NO_OVERWRITE")
            raise PublicationError("PUBLICATION_RENAME_FAILED")
    try:
        os.link(source, destination, src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd, follow_symlinks=False)
    except FileExistsError:
        raise PublicationError("PUBLICATION_NO_OVERWRITE") from None
    except OSError:
        raise PublicationError("PUBLICATION_RENAME_FAILED") from None
    try:
        os.unlink(source, dir_fd=directory_fd)
    except OSError:
        raise PublicationError("PUBLICATION_STAGE_UNLINK_FAILED") from None
    return "LINK_EXCL_FALLBACK"


def publish_evidence(evidence: Dict[str, Any], root: Path,
                     destination_name: str = "r6-evidence.json") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    validate_evidence(evidence)
    _require(type(destination_name) is str and destination_name.endswith(".json") and
             1 <= len(destination_name) <= 100 and "/" not in destination_name and
             "\\" not in destination_name, "PUBLICATION_DESTINATION_INVALID")
    public = {key: evidence[key] for key in PUBLIC_ALLOWLIST}
    _require(set(public) == set(PUBLIC_ALLOWLIST), "PUBLICATION_ALLOWLIST_INVALID")
    encoded = canonical_bytes(public)
    evidence_sha256 = hashlib.sha256(canonical_bytes(evidence)).hexdigest()
    publication_sha256 = hashlib.sha256(encoded).hexdigest()
    directory_fd = _directory(Path(root))
    stage = ".stage-" + secrets.token_hex(16)
    stage_exists = False
    stage_fd = -1
    try:
        stage_fd = os.open(stage, _WRITE_FLAGS, 0o600, dir_fd=directory_fd)
        stage_exists = True
        _write_all(stage_fd, encoded)
        os.fsync(stage_fd)
        os.close(stage_fd)
        stage_fd = -1
        reread = _read_named(directory_fd, stage)
        _require(reread == encoded and hashlib.sha256(reread).hexdigest() ==
                 publication_sha256, "PUBLICATION_STAGE_MISMATCH")
        try:
            decoded = json.loads(reread.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PublicationError("PUBLICATION_STAGE_INVALID") from None
        validate_evidence(decoded)
        primitive = _rename_exclusive(directory_fd, stage, destination_name)
        stage_exists = False
        os.fsync(directory_fd)
        receipt = {
            "version": 1, "destination_name": destination_name,
            "evidence_sha256": evidence_sha256,
            "publication_sha256": publication_sha256, "bytes": len(encoded),
            "allowlist": list(PUBLIC_ALLOWLIST), "raw_included": False,
            "partial_included": False, "atomic": True, "no_overwrite": True,
            "primitive": primitive,
        }
        validate_publication_receipt(receipt)
        return public, receipt
    finally:
        if stage_fd >= 0:
            os.close(stage_fd)
        if stage_exists:
            try:
                os.unlink(stage, dir_fd=directory_fd)
            except OSError:
                pass
        os.close(directory_fd)


__all__ = ["PublicationError", "publish_evidence"]
