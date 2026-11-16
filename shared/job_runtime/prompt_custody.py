"""Immutable, path-redacted prompt artifact custody.

This module is deliberately inert: callers must explicitly capture, publish, open,
or collect artifacts.  Errors are stable codes and never include prompt bytes,
digests, references, or host paths.
"""
from __future__ import annotations

from dataclasses import dataclass
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import sqlite3
import stat
import time
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import quote

from .engine_schema import prompt_binding_sha256, verify_schema9


_MAX_PROMPT_BYTES = 65_536
_GC_LOCK_TIMEOUT_SECONDS = 0.25
_GC_LOCK_POLL_SECONDS = 0.01
_MAX_CHUNK_BYTES = 65_536
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REF = re.compile(r"pa1:sha256:([0-9a-f]{64}):([1-9][0-9]{0,4})")
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_META_FIELDS = ("st_dev", "st_ino", "st_uid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")


class PromptCustodyError(ValueError):
    """A fixed, prompt-free custody failure code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise PromptCustodyError(code)


def _require(value: bool, code: str) -> None:
    if not value:
        _fail(code)


def _digest(value: Any, code: str) -> str:
    _require(type(value) is str and _SHA256.fullmatch(value) is not None, code)
    return value


def _safe(value: Any, code: str) -> str:
    _require(type(value) is str and _SAFE.fullmatch(value) is not None, code)
    return value


def _meta(value: os.stat_result) -> tuple[int, ...]:
    return tuple(getattr(value, field) for field in _META_FIELDS)


def _artifact_meta_ok(value: os.stat_result, length: int) -> bool:
    return (stat.S_ISREG(value.st_mode) and value.st_uid == os.getuid() and
            stat.S_IMODE(value.st_mode) == 0o600 and value.st_nlink == 1 and
            value.st_size == length)


def _redacted_repr(name: str) -> str:
    return f"{name}(<redacted>)"


@dataclass(frozen=True, repr=False)
class CapturedPromptV1:
    raw: bytes
    sha256: str
    length: int
    source_identity_sha256: str

    def __post_init__(self) -> None:
        _require(type(self.raw) is bytes, "CAPTURE_BYTES_INVALID")
        _require(1 <= len(self.raw) <= _MAX_PROMPT_BYTES, "CAPTURE_LENGTH_INVALID")
        _require(type(self.length) is int and not isinstance(self.length, bool) and
                 self.length == len(self.raw), "CAPTURE_LENGTH_INVALID")
        _digest(self.sha256, "CAPTURE_SHA256_INVALID")
        _digest(self.source_identity_sha256, "SOURCE_IDENTITY_INVALID")
        _require(hashlib.sha256(self.raw).hexdigest() == self.sha256,
                 "CAPTURE_SHA256_MISMATCH")
        try:
            self.raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _fail("CAPTURE_UTF8_INVALID")

    def __repr__(self) -> str:
        return _redacted_repr(type(self).__name__)


@dataclass(frozen=True, repr=False)
class PromptArtifactDescriptorV1:
    version: int
    ref: str
    sha256: str
    length: int
    source_identity_sha256: str
    generation: str
    provenance: str

    def __post_init__(self) -> None:
        _require(self.version == 1 and type(self.version) is int, "DESCRIPTOR_VERSION_INVALID")
        digest = _digest(self.sha256, "DESCRIPTOR_SHA256_INVALID")
        _digest(self.source_identity_sha256, "SOURCE_IDENTITY_INVALID")
        _require(type(self.length) is int and not isinstance(self.length, bool) and
                 1 <= self.length <= _MAX_PROMPT_BYTES, "DESCRIPTOR_LENGTH_INVALID")
        match = _REF.fullmatch(self.ref) if type(self.ref) is str else None
        _require(match is not None and match.group(1) == digest and
                 int(match.group(2)) == self.length, "DESCRIPTOR_REF_INVALID")
        _safe(self.generation, "DESCRIPTOR_GENERATION_INVALID")
        _safe(self.provenance, "DESCRIPTOR_PROVENANCE_INVALID")

    def __repr__(self) -> str:
        return _redacted_repr(type(self).__name__)


@dataclass(frozen=True, repr=False)
class SlotPromptBindingV1:
    slot_id: str
    prompt: PromptArtifactDescriptorV1

    def __post_init__(self) -> None:
        _safe(self.slot_id, "SLOT_ID_INVALID")
        _require(isinstance(self.prompt, PromptArtifactDescriptorV1),
                 "SLOT_PROMPT_INVALID")

    @property
    def prompt_ref(self) -> str:
        return self.prompt.ref

    def __repr__(self) -> str:
        return _redacted_repr(type(self).__name__)


class PromptLease:
    """A bounded reader over one verified descriptor and one held file descriptor."""

    def __init__(self, fd: int, descriptor: PromptArtifactDescriptorV1,
                 parent_fd: int, name: str, opened_meta: tuple[int, ...]):
        self._fd = fd
        self._descriptor = descriptor
        self._parent_fd = parent_fd
        self._name = name
        self._opened_meta = opened_meta
        self._closed = False

    def __repr__(self) -> str:
        return _redacted_repr(type(self).__name__)

    @property
    def closed(self) -> bool:
        return self._closed

    def _ensure_open(self) -> None:
        if self._closed:
            _fail("LEASE_CLOSED")

    def _stable(self) -> None:
        self._ensure_open()
        try:
            current = os.fstat(self._fd)
            named = os.stat(self._name, dir_fd=self._parent_fd, follow_symlinks=False)
        except OSError:
            _fail("LEASE_UNSTABLE")
        if (_meta(current) != self._opened_meta or _meta(named) != self._opened_meta or
                not _artifact_meta_ok(current, self._descriptor.length)):
            _fail("LEASE_UNSTABLE")

    def read(self, size: int = -1) -> bytes:
        self._stable()
        _require(type(size) is int and not isinstance(size, bool) and
                 (-1 <= size <= _MAX_CHUNK_BYTES), "LEASE_READ_SIZE_INVALID")
        if size == -1:
            size = min(_MAX_CHUNK_BYTES, self._descriptor.length)
        try:
            value = os.read(self._fd, size)
        except OSError:
            _fail("LEASE_READ_FAILED")
        self._stable()
        return value

    def chunks(self, chunk_size: int = 16_384) -> Iterator[bytes]:
        _require(type(chunk_size) is int and not isinstance(chunk_size, bool) and
                 1 <= chunk_size <= _MAX_CHUNK_BYTES, "LEASE_CHUNK_SIZE_INVALID")
        while True:
            value = self.read(chunk_size)
            if not value:
                break
            yield value

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        fd, parent_fd = self._fd, self._parent_fd
        self._fd = self._parent_fd = -1
        try:
            os.close(fd)
        finally:
            os.close(parent_fd)

    def __enter__(self) -> "PromptLease":
        self._ensure_open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        self.close()
        return False


class PromptArtifactStore:
    """Owner of the workspace-local v1 SHA256 prompt artifact tree."""

    _SUFFIX = (".job-runtime", "prompt-artifacts", "v1")

    def __init__(self, root: os.PathLike[str] | str):
        supplied = Path(root)
        _require(supplied.is_absolute(), "STORE_ROOT_INVALID")
        if tuple(supplied.parts[-3:]) == self._SUFFIX:
            self.root = supplied
            self.workspace = supplied.parents[2]
        else:
            self.workspace = supplied
            self.root = supplied.joinpath(*self._SUFFIX)
        self._lock_name = ".gc.lock"

    def __repr__(self) -> str:
        return _redacted_repr(type(self).__name__)

    @staticmethod
    def _check_private_dir(value: os.stat_result, code: str) -> None:
        _require(stat.S_ISDIR(value.st_mode) and value.st_uid == os.getuid() and
                 stat.S_IMODE(value.st_mode) == 0o700, code)

    @staticmethod
    def _open_base(path: Path, code: str) -> int:
        fd = -1
        try:
            fd = os.open(path, _DIR_FLAGS)
            value = os.fstat(fd)
        except OSError:
            if fd >= 0:
                os.close(fd)
            _fail(code)
        if (not stat.S_ISDIR(value.st_mode) or value.st_uid != os.getuid() or
                stat.S_IMODE(value.st_mode) & 0o022):
            os.close(fd)
            _fail(code)
        return fd

    @classmethod
    def _walk_dirs(cls, base_fd: int, parts: Sequence[str], *, create: bool,
                   code: str) -> int:
        current = os.dup(base_fd)
        try:
            for part in parts:
                _require(type(part) is str and part not in ("", ".", "..") and
                         "/" not in part and "\x00" not in part, code)
                created = False
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=current)
                        created = True
                    except FileExistsError:
                        pass
                    except OSError:
                        _fail(code)
                try:
                    child = os.open(part, _DIR_FLAGS, dir_fd=current)
                except OSError:
                    _fail(code)
                try:
                    cls._check_private_dir(os.fstat(child), code)
                    if created:
                        os.fsync(child)
                        os.fsync(current)
                except PromptCustodyError:
                    os.close(child)
                    raise
                except OSError:
                    os.close(child)
                    _fail(code)
                os.close(current)
                current = child
            return current
        except BaseException:
            os.close(current)
            raise

    def _store_fd(self, *, create: bool) -> int:
        workspace_fd = self._open_base(self.workspace, "STORE_WORKSPACE_UNSAFE")
        try:
            return self._walk_dirs(workspace_fd, self._SUFFIX, create=create,
                                   code="STORE_DIRECTORY_UNSAFE")
        finally:
            os.close(workspace_fd)

    def _sha_fd(self, *, create: bool) -> int:
        root_fd = self._store_fd(create=create)
        try:
            return self._walk_dirs(root_fd, ("sha256",), create=create,
                                   code="STORE_DIRECTORY_UNSAFE")
        finally:
            os.close(root_fd)

    def _shard_fd(self, digest: str, *, create: bool) -> int:
        sha_fd = self._sha_fd(create=create)
        try:
            return self._walk_dirs(sha_fd, (digest[:2], digest[2:4]), create=create,
                                   code="STORE_DIRECTORY_UNSAFE")
        finally:
            os.close(sha_fd)

    def capture_source(self, workspace: os.PathLike[str] | str,
                       relative: os.PathLike[str] | str) -> CapturedPromptV1:
        workspace_path = Path(workspace)
        _require(workspace_path.is_absolute(), "SOURCE_WORKSPACE_INVALID")
        value = os.fspath(relative)
        _require(type(value) is str and "\x00" not in value and "\\" not in value and
                 not value.startswith("/") and not value.endswith("/") and
                 "//" not in value and all(part not in ("", ".", "..")
                                               for part in value.split("/")),
                 "SOURCE_PATH_INVALID")
        pure = PurePosixPath(value)
        parts = pure.parts
        _require(not pure.is_absolute() and len(parts) >= 3 and
                 parts[0] == ".job-runtime" and parts[1] in ("config", "acceptance") and
                 all(part not in ("", ".", "..") for part in parts),
                 "SOURCE_PATH_NOT_APPROVED")
        workspace_fd = self._open_base(workspace_path, "SOURCE_WORKSPACE_UNSAFE")
        expected_workspace_fd = -1
        parent_fd = -1
        fd = -1
        try:
            expected_workspace_fd = self._open_base(self.workspace, "SOURCE_WORKSPACE_UNSAFE")
            _require((os.fstat(workspace_fd).st_dev, os.fstat(workspace_fd).st_ino) ==
                     (os.fstat(expected_workspace_fd).st_dev,
                      os.fstat(expected_workspace_fd).st_ino),
                     "SOURCE_WORKSPACE_MISMATCH")
            parent_fd = self._walk_dirs(workspace_fd, parts[:-1], create=False,
                                        code="SOURCE_ANCESTRY_UNSAFE")
            try:
                fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent_fd)
            except OSError:
                _fail("SOURCE_OPEN_FAILED")
            before = os.fstat(fd)
            _require(stat.S_ISREG(before.st_mode), "SOURCE_TYPE_UNSAFE")
            _require(before.st_uid == os.getuid(), "SOURCE_OWNER_UNSAFE")
            _require(stat.S_IMODE(before.st_mode) == 0o600, "SOURCE_MODE_UNSAFE")
            _require(before.st_nlink == 1, "SOURCE_LINK_UNSAFE")
            _require(1 <= before.st_size <= _MAX_PROMPT_BYTES, "SOURCE_SIZE_INVALID")
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                try:
                    chunk = os.read(fd, min(16_384, remaining))
                except OSError:
                    _fail("SOURCE_READ_FAILED")
                _require(bool(chunk), "SOURCE_MUTATED")
                chunks.append(chunk)
                remaining -= len(chunk)
            try:
                trailing = os.read(fd, 1)
            except OSError:
                _fail("SOURCE_READ_FAILED")
            _require(trailing == b"", "SOURCE_MUTATED")
            raw = b"".join(chunks)
            after = os.fstat(fd)
            _require(_meta(before) == _meta(after) and len(raw) == before.st_size,
                     "SOURCE_MUTATED")
            try:
                raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                _fail("SOURCE_UTF8_INVALID")
            digest = hashlib.sha256(raw).hexdigest()
            identity_document = {
                "schema": 2,
                "dev": before.st_dev, "ino": before.st_ino, "uid": before.st_uid,
                "type": stat.S_IFMT(before.st_mode), "mode": stat.S_IMODE(before.st_mode),
                "nlink": before.st_nlink, "size": before.st_size,
                "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns,
                "bytes_sha256": digest,
            }
            identity = hashlib.sha256(json.dumps(
                identity_document, sort_keys=True, separators=(",", ":")
            ).encode("ascii")).hexdigest()
            return CapturedPromptV1(raw, digest, len(raw), identity)
        finally:
            if fd >= 0:
                os.close(fd)
            if parent_fd >= 0:
                os.close(parent_fd)
            if expected_workspace_fd >= 0:
                os.close(expected_workspace_fd)
            os.close(workspace_fd)

    @staticmethod
    def _write_all(fd: int, raw: bytes) -> None:
        offset = 0
        while offset < len(raw):
            try:
                written = os.write(fd, raw[offset:])
            except OSError:
                _fail("ARTIFACT_WRITE_FAILED")
            _require(type(written) is int and written > 0, "ARTIFACT_SHORT_WRITE")
            offset += written

    @staticmethod
    def _verify_open_fd(fd: int, descriptor: PromptArtifactDescriptorV1,
                        code: str) -> tuple[int, ...]:
        value = os.fstat(fd)
        _require(_artifact_meta_ok(value, descriptor.length), code)
        hasher = hashlib.sha256()
        total = 0
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            while total < descriptor.length:
                chunk = os.read(fd, min(16_384, descriptor.length - total))
                _require(bool(chunk), code)
                total += len(chunk)
                hasher.update(chunk)
            _require(os.read(fd, 1) == b"", code)
        except OSError:
            _fail(code)
        after = os.fstat(fd)
        _require(_meta(value) == _meta(after) and total == descriptor.length and
                 hasher.hexdigest() == descriptor.sha256, code)
        os.lseek(fd, 0, os.SEEK_SET)
        return _meta(after)

    @staticmethod
    def _acquire_publish_lock(shard_fd: int) -> None:
        try:
            fcntl.flock(shard_fd, fcntl.LOCK_EX)
        except OSError:
            _fail("ARTIFACT_LOCK_FAILED")

    def publish(self, captured: CapturedPromptV1, generation: str,
                provenance: str) -> PromptArtifactDescriptorV1:
        _require(isinstance(captured, CapturedPromptV1), "CAPTURE_INVALID")
        generation = _safe(generation, "DESCRIPTOR_GENERATION_INVALID")
        provenance = _safe(provenance, "DESCRIPTOR_PROVENANCE_INVALID")
        descriptor = PromptArtifactDescriptorV1(
            1, f"pa1:sha256:{captured.sha256}:{captured.length}", captured.sha256,
            captured.length, captured.source_identity_sha256, generation, provenance)
        shard_fd = self._shard_fd(captured.sha256, create=True)
        shard_identity = (os.fstat(shard_fd).st_dev, os.fstat(shard_fd).st_ino)
        temp_name = ".tmp-" + secrets.token_hex(16)
        target_name = captured.sha256 + ".prompt"
        temp_fd = -1
        linked = False
        temp_exists = False
        try:
            self._acquire_publish_lock(shard_fd)
            try:
                temp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                  os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=shard_fd)
                temp_exists = True
            except OSError:
                _fail("ARTIFACT_TEMP_CREATE_FAILED")
            self._write_all(temp_fd, captured.raw)
            try:
                os.fsync(temp_fd)
            except OSError:
                _fail("ARTIFACT_FILE_FSYNC_FAILED")
            _require(_artifact_meta_ok(os.fstat(temp_fd), captured.length),
                     "ARTIFACT_TEMP_UNSAFE")
            os.close(temp_fd)
            temp_fd = -1
            try:
                os.link(temp_name, target_name, src_dir_fd=shard_fd,
                        dst_dir_fd=shard_fd, follow_symlinks=False)
                linked = True
            except FileExistsError:
                linked = False
            except OSError:
                _fail("ARTIFACT_LINK_FAILED")
            if linked:
                try:
                    linked_meta = os.stat(target_name, dir_fd=shard_fd,
                                          follow_symlinks=False)
                except OSError:
                    _fail("ARTIFACT_PUBLISH_UNCONFIRMED")
                _require(linked_meta.st_nlink == 2, "ARTIFACT_PUBLISH_UNCONFIRMED")
            try:
                os.unlink(temp_name, dir_fd=shard_fd)
                temp_exists = False
            except OSError:
                _fail("ARTIFACT_TEMP_UNLINK_FAILED")
            try:
                target_fd = os.open(target_name, _FILE_FLAGS, dir_fd=shard_fd)
            except OSError:
                _fail("ARTIFACT_OPEN_FAILED")
            try:
                self._verify_open_fd(target_fd, descriptor,
                                     "ARTIFACT_EXISTING_MISMATCH")
            finally:
                os.close(target_fd)
            try:
                os.fsync(shard_fd)
            except OSError:
                _fail("ARTIFACT_DIRECTORY_FSYNC_FAILED")
            canonical_shard_fd = self._shard_fd(captured.sha256, create=False)
            try:
                _require((os.fstat(canonical_shard_fd).st_dev,
                          os.fstat(canonical_shard_fd).st_ino) == shard_identity,
                         "ARTIFACT_SHARD_REPLACED")
            finally:
                os.close(canonical_shard_fd)
            try:
                final_fd = os.open(target_name, _FILE_FLAGS, dir_fd=shard_fd)
            except OSError:
                _fail("ARTIFACT_POST_FSYNC_UNSAFE")
            try:
                self._verify_open_fd(final_fd, descriptor,
                                     "ARTIFACT_POST_FSYNC_UNSAFE")
            finally:
                os.close(final_fd)
            return descriptor
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
            # Before linking, cleanup is safe.  After a successful link, failed
            # unlink must remain visible as nlink=2 crash evidence and fail closed.
            if temp_exists and not linked:
                try:
                    os.unlink(temp_name, dir_fd=shard_fd)
                except OSError:
                    pass
            os.close(shard_fd)

    def open(self, descriptor: PromptArtifactDescriptorV1) -> PromptLease:
        _require(isinstance(descriptor, PromptArtifactDescriptorV1),
                 "DESCRIPTOR_INVALID")
        shard_fd = self._shard_fd(descriptor.sha256, create=False)
        try:
            fd = os.open(descriptor.sha256 + ".prompt", _FILE_FLAGS, dir_fd=shard_fd)
        except OSError:
            os.close(shard_fd)
            _fail("ARTIFACT_OPEN_FAILED")
        try:
            opened_meta = self._verify_open_fd(fd, descriptor, "ARTIFACT_VERIFY_FAILED")
        except BaseException:
            os.close(fd)
            os.close(shard_fd)
            raise
        return PromptLease(fd, descriptor, shard_fd,
                           descriptor.sha256 + ".prompt", opened_meta)

    def verify(self, descriptor: PromptArtifactDescriptorV1) -> bool:
        with self.open(descriptor) as lease:
            for _ in lease.chunks():
                pass
        return True

    @staticmethod
    def _db_refs(path: Path) -> tuple[set[str], dict[str, tuple[Any, ...]]]:
        fd = -1
        connection = None
        try:
            fd = os.open(path, _FILE_FLAGS)
            before = os.fstat(fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and
                     stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1,
                     "GC_DATABASE_UNSAFE")
            uri = "file:" + quote(os.fspath(path), safe="/") + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            named = os.stat(path, follow_symlinks=False)
            _require(_meta(before) == _meta(named), "GC_DATABASE_CHANGED")
        except PromptCustodyError:
            if connection is not None:
                connection.close()
            if fd >= 0:
                os.close(fd)
            raise
        except (sqlite3.Error, OSError):
            if connection is not None:
                connection.close()
            if fd >= 0:
                os.close(fd)
            _fail("GC_DATABASE_OPEN_FAILED")
        try:
            try:
                verify_schema9(connection)
            except ValueError:
                _fail("GC_DATABASE_SCHEMA_UNSAFE")
            refs: set[str] = set()
            artifacts: dict[str, tuple[Any, ...]] = {}
            for row in connection.execute("""SELECT ref,sha256,length,version,
                    source_identity_sha256,generation,proof_origin FROM prompt_artifacts"""):
                ref, digest, length, version, identity, generation, origin = row
                _digest(identity, "GC_DATABASE_INCONSISTENT")
                match = _REF.fullmatch(ref) if type(ref) is str else None
                _require(match is not None and match.group(1) == digest and
                         int(match.group(2)) == length and version == 1 and
                         type(generation) is str and _SAFE.fullmatch(generation) and
                         origin in ("native_v1", "backfilled_v8"),
                         "GC_DATABASE_INCONSISTENT")
                value = (ref, digest, length, version, identity, generation, origin)
                _require(ref not in artifacts or artifacts[ref] == value,
                         "GC_DATABASE_METADATA_CONFLICT")
                artifacts[ref] = value
            proof_names = ("artifact_ref", "sha256", "length", "version",
                           "source_identity_sha256", "binding_sha256", "generation",
                           "proof_origin")
            for row in connection.execute("""SELECT job_id,slot_id,artifact_ref,sha256,
                    length,version,source_identity_sha256,binding_sha256,generation,
                    proof_origin FROM slots"""):
                job_id, slot_id, *proof = row
                values = dict(zip(proof_names, proof))
                if values["proof_origin"] == "legacy_unbound":
                    _require(all(values[name] is None for name in proof_names[:-1]),
                             "GC_DATABASE_INCONSISTENT")
                    continue
                ref = values["artifact_ref"]
                _require(ref in artifacts and artifacts[ref] == (
                    ref, values["sha256"], values["length"], values["version"],
                    values["source_identity_sha256"], values["generation"],
                    values["proof_origin"]), "GC_DATABASE_METADATA_CONFLICT")
                _digest(values["binding_sha256"], "GC_DATABASE_INCONSISTENT")
                _require(prompt_binding_sha256(job_id, slot_id, values) ==
                         values["binding_sha256"], "GC_DATABASE_INCONSISTENT")
                refs.add(ref)
            for row in connection.execute("""SELECT artifact_ref,sha256,length,version,
                    source_identity_sha256,binding_sha256,generation,proof_origin,status
                    FROM attempts"""):
                *proof, status = row
                values = dict(zip(proof_names, proof))
                _require(type(status) is str and status in {
                    "ready", "pending", "running", "retry_wait", "reconciling",
                    "unknown", "completed", "succeeded", "failed", "cancelled",
                    "timed_out", "missed", "coalesced"
                }, "GC_DATABASE_UNSAFE_STATE")
                if values["proof_origin"] == "legacy_unbound":
                    _require(all(values[name] is None for name in proof_names[:-1]),
                             "GC_DATABASE_INCONSISTENT")
                    continue
                ref = values["artifact_ref"]
                _require(ref in artifacts and artifacts[ref] == (
                    ref, values["sha256"], values["length"], values["version"],
                    values["source_identity_sha256"], values["generation"],
                    values["proof_origin"]), "GC_DATABASE_METADATA_CONFLICT")
                _digest(values["binding_sha256"], "GC_DATABASE_INCONSISTENT")
                refs.add(ref)
            _require(_meta(before) == _meta(os.fstat(fd)) and
                     _meta(before) == _meta(os.stat(path, follow_symlinks=False)),
                     "GC_DATABASE_CHANGED")
            return refs, artifacts
        except PromptCustodyError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OSError):
            _fail("GC_DATABASE_CORRUPT")
        finally:
            connection.close()
            os.close(fd)

    def _scan(self, now_ns: int, grace_ns: int) -> tuple[dict[str, tuple[int, int, int]], int]:
        sha_fd = self._sha_fd(create=False)
        artifacts: dict[str, tuple[int, int, int]] = {}
        total_bytes = 0
        try:
            first_names = os.listdir(sha_fd)
            for first in first_names:
                _require(re.fullmatch(r"[0-9a-f]{2}", first) is not None,
                         "GC_UNKNOWN_ENTRY")
                first_fd = self._walk_dirs(sha_fd, (first,), create=False,
                                           code="GC_STORE_UNSAFE")
                try:
                    second_names = os.listdir(first_fd)
                    for second in second_names:
                        _require(re.fullmatch(r"[0-9a-f]{2}", second) is not None,
                                 "GC_UNKNOWN_ENTRY")
                        second_fd = self._walk_dirs(first_fd, (second,), create=False,
                                                    code="GC_STORE_UNSAFE")
                        try:
                            for name in os.listdir(second_fd):
                                match = re.fullmatch(r"([0-9a-f]{64})\.prompt", name)
                                _require(match is not None, "GC_UNKNOWN_ENTRY")
                                digest = match.group(1)
                                _require(digest[:2] == first and digest[2:4] == second,
                                         "GC_UNKNOWN_ENTRY")
                                try:
                                    fd = os.open(name, _FILE_FLAGS, dir_fd=second_fd)
                                except OSError:
                                    _fail("GC_ARTIFACT_UNSAFE")
                                try:
                                    value = os.fstat(fd)
                                    _require(_artifact_meta_ok(value, value.st_size) and
                                             1 <= value.st_size <= _MAX_PROMPT_BYTES,
                                             "GC_ARTIFACT_UNSAFE")
                                    hasher = hashlib.sha256()
                                    remaining = value.st_size
                                    while remaining:
                                        chunk = os.read(fd, min(16_384, remaining))
                                        _require(bool(chunk), "GC_ARTIFACT_UNSAFE")
                                        hasher.update(chunk)
                                        remaining -= len(chunk)
                                    _require(hasher.hexdigest() == digest and
                                             _meta(value) == _meta(os.fstat(fd)),
                                             "GC_ARTIFACT_CORRUPT")
                                finally:
                                    os.close(fd)
                                ref = f"pa1:sha256:{digest}:{value.st_size}"
                                _require(ref not in artifacts, "GC_ARTIFACT_DUPLICATE")
                                age_ns = now_ns - value.st_mtime_ns
                                artifacts[ref] = (value.st_size, value.st_mtime_ns,
                                                  second_fd)
                                total_bytes += value.st_size
                        finally:
                            os.close(second_fd)
                finally:
                    os.close(first_fd)
            return artifacts, total_bytes
        finally:
            os.close(sha_fd)

    @staticmethod
    def _acquire_gc_lock(lock_fd: int) -> None:
        deadline = time.monotonic() + _GC_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    _fail("GC_LOCK_FAILED")
                if time.monotonic() >= deadline:
                    _fail("GC_LOCK_BUSY")
                time.sleep(_GC_LOCK_POLL_SECONDS)

    def collect(self, database_paths: Sequence[os.PathLike[str] | str],
                grace_seconds: int | float, delete: bool = False) -> Mapping[str, Any]:
        _require(isinstance(database_paths, Sequence) and not isinstance(database_paths, (str, bytes)) and
                 bool(database_paths), "GC_DATABASE_PATHS_INVALID")
        _require(type(grace_seconds) in (int, float) and not isinstance(grace_seconds, bool) and
                 0 <= grace_seconds <= 365 * 24 * 3600, "GC_GRACE_INVALID")
        _require(type(delete) is bool, "GC_DELETE_INVALID")
        if delete:
            _fail("GC_DELETE_UNAVAILABLE")
        root_fd = self._store_fd(create=False)
        try:
            try:
                lock_fd = os.open(self._lock_name, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC |
                                  os.O_NOFOLLOW, 0o600, dir_fd=root_fd)
            except OSError:
                _fail("GC_LOCK_FAILED")
            try:
                _require(_artifact_meta_ok(os.fstat(lock_fd), 0), "GC_LOCK_UNSAFE")
                self._acquire_gc_lock(lock_fd)
                refs_first: set[str] = set()
                catalog_first: dict[str, tuple[Any, ...]] = {}
                normalized: list[Path] = []
                for item in database_paths:
                    path = Path(item)
                    _require(path.is_absolute(), "GC_DATABASE_PATHS_INVALID")
                    normalized.append(path)
                    refs, catalog = self._db_refs(path)
                    refs_first.update(refs)
                    for ref, metadata in catalog.items():
                        _require(ref not in catalog_first or
                                 catalog_first[ref] == metadata,
                                 "GC_DATABASE_METADATA_CONFLICT")
                        catalog_first[ref] = metadata
                now_ns = time.time_ns()
                grace_ns = int(grace_seconds * 1_000_000_000)
                artifacts, total_bytes = self._scan(now_ns, grace_ns)
                refs_second: set[str] = set()
                catalog_second: dict[str, tuple[Any, ...]] = {}
                for path in normalized:
                    refs, catalog = self._db_refs(path)
                    refs_second.update(refs)
                    for ref, metadata in catalog.items():
                        _require(ref not in catalog_second or
                                 catalog_second[ref] == metadata,
                                 "GC_DATABASE_METADATA_CONFLICT")
                        catalog_second[ref] = metadata
                _require(refs_first == refs_second and
                         catalog_first == catalog_second, "GC_MARK_CHANGED")
                candidates = {
                    ref: value for ref, value in artifacts.items()
                    if ref not in refs_second and now_ns - value[1] >= grace_ns
                }
                return {
                    "schema_version": 1,
                    "dry_run": not delete,
                    "artifact_count": len(artifacts),
                    "artifact_bytes": total_bytes,
                    "referenced_count": sum(1 for ref in artifacts if ref in refs_second),
                    "candidate_count": len(candidates),
                    "candidate_bytes": sum(value[0] for value in candidates.values()),
                    "deleted_count": 0,
                    "deleted_bytes": 0,
                    "codes": (),
                }
            finally:
                os.close(lock_fd)
        finally:
            os.close(root_fd)


__all__ = [
    "CapturedPromptV1", "PromptArtifactDescriptorV1", "SlotPromptBindingV1",
    "PromptLease", "PromptArtifactStore", "PromptCustodyError",
]
