"""Source-only macOS VM lifecycle adapter with an injected command boundary.

This module neither imports Virtualization.framework nor provides a host execution
fallback.  A caller must inject both a command runner and a VM helper adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import UUID

from .containment import ContainedExit, ContainedRequest, ContainmentContractError


class ContainmentLifecycleError(RuntimeError):
    """A fail-closed lifecycle refusal with a stable, non-sensitive code."""


class CommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


class VMHelper(Protocol):
    """Injected adapter; production implementations live outside this contract."""

    path: Path
    artifact_paths: Mapping[str, Path]

    def poll(self, attempt_dir: Path, request: ContainedRequest) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True)
class SwiftHelper:
    """Receipt-only adapter for the source helper; it never starts a process."""

    path: Path
    artifact_paths: Mapping[str, Path]

    def poll(self, attempt_dir: Path, request: ContainedRequest) -> Mapping[str, Any] | None:
        receipt_dir = os.open(attempt_dir / "receipts", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                              getattr(os, "O_NOFOLLOW", 0))
        try:
            try:
                value = MacOSVMLifecycle._read_private_json(receipt_dir, "helper.json")
            except FileNotFoundError:
                return None
        finally:
            os.close(receipt_dir)
        required = {"protocolVersion", "requestID", "requestSHA256", "artifactGeneration",
                    "nonceDigest", "outcome", "stopAcknowledged", "teardownConfirmed",
                    "startedAt", "stoppedAt", "elapsedMilliseconds", "outputBytes",
                    "exitCode", "terminationSignal", "errorCode"}
        if set(value) != required or value["protocolVersion"] != 1 or value["requestID"] != request.attempt_id:
            raise ContainmentLifecycleError("HELPER_RECEIPT_INVALID")
        expected_request = MacOSVMLifecycle._canonical_sha256(request.to_reference_dict())
        if (value["requestSHA256"] != expected_request or
                value["artifactGeneration"] != request.artifact_generation or
                value["nonceDigest"] != request.nonce_digest):
            raise ContainmentLifecycleError("HELPER_RECEIPT_BINDING_INVALID")
        for flag in ("stopAcknowledged", "teardownConfirmed"):
            if type(value[flag]) is not bool:
                raise ContainmentLifecycleError("HELPER_RECEIPT_INVALID")
        size = value["outputBytes"]
        if type(size) is not int or not 0 <= size <= request.ceilings.output_bytes:
            raise ContainmentLifecycleError("HELPER_RECEIPT_INVALID")
        exit_code, termination_signal = value["exitCode"], value["terminationSignal"]
        if (exit_code is not None and (type(exit_code) is not int or not -255 <= exit_code <= 255)) or (
                termination_signal is not None and
                (type(termination_signal) is not int or not 1 <= termination_signal <= 255)):
            raise ContainmentLifecycleError("HELPER_RECEIPT_INVALID")
        if value["outcome"] == "completed" and value["errorCode"] is None:
            if termination_signal is not None:
                code, details = -termination_signal, ("TERMINATED_BY_SIGNAL",)
            elif exit_code is not None:
                code, details = exit_code, ()
            else:
                raise ContainmentLifecycleError("HELPER_RECEIPT_INVALID")
            return {"code": code, "output_bytes": size, "output_truncated": False,
                    "detail_codes": details, "stop_acknowledged": value["stopAcknowledged"],
                    "teardown_confirmed": value["teardownConfirmed"]}
        code = value["errorCode"]
        if type(code) is not str or not re.fullmatch(r"[a-z_]{1,64}", code):
            raise ContainmentLifecycleError("HELPER_RECEIPT_INVALID")
        return {"code": None, "output_bytes": size, "output_truncated": False,
                "detail_codes": (code.upper(),), "stop_acknowledged": value["stopAcknowledged"],
                "teardown_confirmed": value["teardownConfirmed"]}


def _bound_exit(request: ContainedRequest, classification: str, **values: Any) -> ContainedExit:
    basis = request.to_reference_dict()
    return ContainedExit(request.attempt_id, classification, request.nonce_digest,
        hashlib.sha256(json.dumps(basis, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        request.artifact_generation, **values)


@dataclass(frozen=True)
class PreparedAttempt:
    attempt_id: str
    label: str
    state_dir: Path
    request_path: Path
    plist_path: Path
    socket_name: str
    nonce_digest: str
    request_sha256: str
    artifact_generation: str


@dataclass(frozen=True)
class ReconcileResult:
    attempt_id: str
    label: str
    launchctl_bootout_acknowledged: bool
    label_absent: bool


class MacOSVMLifecycle:
    """Own one-use launchd labels and private per-attempt state.

    ``runner`` is the only command boundary.  It receives an argv tuple and a
    mandatory timeout.  No default is supplied so importing this module cannot
    execute anything on the host.
    """

    LABEL_PREFIX = "com.local.trading-agent.containment"
    COMMAND_TIMEOUT = 5.0
    POLL_INTERVAL = 0.05
    MAX_RECEIPT_BYTES = 16 * 1024
    TRANSIENT_FILES = ("request.json", "socket.json", "vm.plist", "agent.sock")

    def __init__(self, workspace: Path | str, *, runner: Callable[..., CommandResult],
                 helper: VMHelper, uid: int | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        if runner is None or helper is None:
            raise ContainmentLifecycleError("INJECTED_BOUNDARY_REQUIRED")
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            raise ContainmentLifecycleError("WORKSPACE_INVALID")
        self.runner = runner
        self.helper = helper
        self.uid = os.getuid() if uid is None else uid
        self.clock = clock
        self.wall_clock = wall_clock
        self.sleeper = sleeper
        self.domain = f"gui/{self.uid}"
        self.workspace_identity = hashlib.sha256(
            str(self.workspace).encode("utf-8")).hexdigest()

    @property
    def state_root(self) -> Path:
        return self.workspace / ".job-runtime" / "containment"

    def _inside(self, path: Path | str, *, must_exist: bool = True) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve(strict=must_exist)
        try:
            resolved.relative_to(self.workspace)
        except ValueError:
            raise ContainmentLifecycleError("PATH_OUTSIDE_WORKSPACE") from None
        return resolved

    @staticmethod
    def _trusted_dir(fd: int, *, exact_private: bool) -> None:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ContainmentLifecycleError("STATE_DIRECTORY_UNTRUSTED")
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o022 or (exact_private and mode != 0o700):
            raise ContainmentLifecycleError("STATE_DIRECTORY_PERMISSIONS")

    def _open_state_root(self) -> int:
        root_fd = os.open(self.workspace, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        held = [root_fd]
        try:
            current = root_fd
            for name, private in ((".job-runtime", False), ("containment", True)):
                try:
                    fd = os.open(name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                                 getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
                except FileNotFoundError:
                    os.mkdir(name, 0o700, dir_fd=current)
                    fd = os.open(name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                                 getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
                held.append(fd)
                self._trusted_dir(fd, exact_private=private)
                current = fd
            result = os.dup(current)
            return result
        except OSError as exc:
            raise ContainmentLifecycleError("STATE_PATH_REFUSED") from exc
        finally:
            for fd in reversed(held):
                os.close(fd)

    @staticmethod
    def _atomic_file(dir_fd: int, name: str, data: bytes) -> None:
        if "/" in name or name in ("", ".", ".."):
            raise ContainmentLifecycleError("STATE_NAME_INVALID")
        temporary = f".write-{os.urandom(12).hex()}"
        descriptor = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=dir_fd)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            os.fsync(dir_fd)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=dir_fd)
            except FileNotFoundError:
                pass

    @classmethod
    def _json_file(cls, dir_fd: int, name: str, value: Mapping[str, Any]) -> None:
        data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(data) > cls.MAX_RECEIPT_BYTES:
            raise ContainmentLifecycleError("STATE_VALUE_TOO_LARGE")
        cls._atomic_file(dir_fd, name, data)

    @classmethod
    def _read_private_json(cls, dir_fd: int, name: str) -> dict[str, Any]:
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    stat.S_IMODE(info.st_mode) != 0o600 or
                    not 0 < info.st_size <= cls.MAX_RECEIPT_BYTES):
                raise ContainmentLifecycleError("STATE_FILE_INVALID")
            raw = os.read(fd, info.st_size + 1)
            if len(raw) != info.st_size:
                raise ContainmentLifecycleError("STATE_FILE_CHANGED")
        finally:
            os.close(fd)
        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    raise ContainmentLifecycleError("STATE_JSON_DUPLICATE_KEY")
                value[key] = item
            return value
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
        if not isinstance(value, dict):
            raise ContainmentLifecycleError("STATE_FILE_INVALID")
        return value

    def _open_attempt(self, attempt_id: str, *, create: bool) -> tuple[int, int]:
        root_fd = self._open_state_root()
        try:
            if create:
                try:
                    os.mkdir(attempt_id, 0o700, dir_fd=root_fd)
                except FileExistsError:
                    raise ContainmentLifecycleError("DUPLICATE_ATTEMPT") from None
            attempt_fd = os.open(attempt_id, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                                 getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
            self._trusted_dir(attempt_fd, exact_private=True)
            return root_fd, attempt_fd
        except BaseException:
            os.close(root_fd)
            raise

    @staticmethod
    def _claim_nonce(root_fd: int, request: ContainedRequest) -> None:
        """Consume a nonce exactly once, including when later preparation fails."""
        name = ".nonce-" + request.nonce_digest
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=root_fd)
        except FileExistsError:
            raise ContainmentLifecycleError("NONCE_REUSED") from None
        try:
            os.write(fd, request.attempt_id.encode("ascii"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(root_fd)

    @classmethod
    def _remove_tree_entry(cls, parent_fd: int, name: str) -> None:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                            getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
            try:
                cls._trusted_dir(child, exact_private=True)
                for entry in os.listdir(child):
                    cls._remove_tree_entry(child, entry)
            finally:
                os.close(child)
            os.rmdir(name, dir_fd=parent_fd)
        elif stat.S_ISREG(info.st_mode) or stat.S_ISSOCK(info.st_mode):
            os.unlink(name, dir_fd=parent_fd)
        else:
            raise ContainmentLifecycleError("ROLLBACK_ENTRY_REFUSED")

    def _remove_attempt(self, attempt_id: str) -> None:
        root_fd = self._open_state_root()
        try:
            try:
                attempt_fd = os.open(attempt_id, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                                     getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
            except FileNotFoundError:
                return
            try:
                self._trusted_dir(attempt_fd, exact_private=True)
                for name in os.listdir(attempt_fd):
                    self._remove_tree_entry(attempt_fd, name)
            finally:
                os.close(attempt_fd)
            os.rmdir(attempt_id, dir_fd=root_fd)
        finally:
            os.close(root_fd)

    def _cleanup_transient(self, attempt_fd: int) -> None:
        names = set(self.TRANSIENT_FILES) | {"artifacts", "io", "mounts", "profiles", "receipts"}
        names.update(name for name in os.listdir(attempt_fd)
                     if name.startswith("artifact-") or name.startswith("mount-"))
        for name in names:
            try:
                self._remove_tree_entry(attempt_fd, name)
            except FileNotFoundError:
                pass

    def _artifact_sources(self, request: ContainedRequest) -> dict[str, Path]:
        supplied = dict(self.helper.artifact_paths)
        supplied.setdefault("helper", Path(self.helper.path))
        if set(supplied) != set(request.artifacts.as_dict()):
            raise ContainmentLifecycleError("ARTIFACT_SET_INVALID")
        sources = {name: self._inside(Path(path), must_exist=True)
                   for name, path in supplied.items()}
        if sources["helper"] != self._inside(self.helper.path):
            raise ContainmentLifecycleError("HELPER_IDENTITY_MISMATCH")
        return sources

    def _mount_sources(self, request: ContainedRequest) -> dict[str, str]:
        return {mount.mount_id: mount.source_ref for mount in request.mounts}

    def _open_mount_nofollow(self, source_ref: str) -> int:
        """Open a workspace file through held no-follow component descriptors."""
        components = source_ref.split("/")
        held = [os.open(self.workspace, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))]
        identities: list[tuple[int, int]] = []
        try:
            current = held[0]
            for component in components[:-1]:
                descriptor = os.open(
                    component, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                    getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
                info = os.fstat(descriptor)
                if not stat.S_ISDIR(info.st_mode):
                    raise ContainmentLifecycleError("MOUNT_COMPONENT_INVALID")
                held.append(descriptor)
                identities.append((info.st_dev, info.st_ino))
                current = descriptor
            result = os.open(
                components[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                getattr(os, "O_NONBLOCK", 0), dir_fd=current)
            if not stat.S_ISREG(os.fstat(result).st_mode):
                os.close(result)
                raise ContainmentLifecycleError("MOUNT_TYPE_REFUSED")
            # Rewalk the lexical chain and require the held components still be
            # the workspace-visible components. A rename-to-symlink race fails.
            verify = [os.open(self.workspace, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))]
            try:
                current = verify[0]
                for index, component in enumerate(components[:-1]):
                    descriptor = os.open(
                        component, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                        getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
                    verify.append(descriptor)
                    info = os.fstat(descriptor)
                    if (info.st_dev, info.st_ino) != identities[index]:
                        raise ContainmentLifecycleError("MOUNT_PATH_CHANGED")
                    current = descriptor
            except BaseException:
                os.close(result)
                raise
            finally:
                for descriptor in reversed(verify):
                    os.close(descriptor)
            return result
        except OSError as exc:
            raise ContainmentLifecycleError("MOUNT_NOFOLLOW_REFUSED") from exc
        finally:
            for descriptor in reversed(held):
                os.close(descriptor)

    @staticmethod
    def _snapshot_regular(source: Path | int, attempt_fd: int, name: str,
                          expected_sha256: str | None, maximum_bytes: int, *,
                          executable: bool = False) -> int:
        """Copy and hash one held regular file into private attempt state."""
        source_fd = destination_fd = None
        temporary = ".snapshot-" + os.urandom(12).hex()
        try:
            source_fd = (os.dup(source) if type(source) is int else
                         os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                                 getattr(os, "O_NONBLOCK", 0)))
            before = os.fstat(source_fd)
            if not stat.S_ISREG(before.st_mode):
                raise ContainmentLifecycleError("SNAPSHOT_SOURCE_INVALID")
            if maximum_bytes < 0 or before.st_size > maximum_bytes:
                raise ContainmentLifecycleError("DISK_CEILING_EXCEEDED")
            destination_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                     getattr(os, "O_NOFOLLOW", 0),
                                     0o700 if executable else 0o600, dir_fd=attempt_fd)
            digest = hashlib.sha256()
            copied = 0
            while True:
                block = os.read(source_fd, 1024 * 1024)
                if not block:
                    break
                if copied + len(block) > maximum_bytes:
                    raise ContainmentLifecycleError("DISK_CEILING_EXCEEDED")
                digest.update(block)
                copied += len(block)
                view = memoryview(block)
                while view:
                    written = os.write(destination_fd, view)
                    if written <= 0:
                        raise ContainmentLifecycleError("SNAPSHOT_WRITE_FAILED")
                    view = view[written:]
            os.fsync(destination_fd)
            after = os.fstat(source_fd)
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
                raise ContainmentLifecycleError("SNAPSHOT_SOURCE_CHANGED")
            if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
                raise ContainmentLifecycleError("ARTIFACT_HASH_DRIFT")
            os.close(destination_fd)
            destination_fd = None
            os.replace(temporary, name, src_dir_fd=attempt_fd, dst_dir_fd=attempt_fd)
            os.fsync(attempt_fd)
            return copied
        except OSError as exc:
            raise ContainmentLifecycleError("SNAPSHOT_FAILED") from exc
        finally:
            if source_fd is not None:
                os.close(source_fd)
            if destination_fd is not None:
                os.close(destination_fd)
            try:
                os.unlink(temporary, dir_fd=attempt_fd)
            except FileNotFoundError:
                pass

    @staticmethod
    def _canonical_sha256(value: Mapping[str, Any]) -> str:
        data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _label_values(attempt_id: str, nonce_digest: str, workspace_identity: str) -> str:
        for value in (nonce_digest, workspace_identity):
            if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ContainmentLifecycleError("LABEL_BINDING_INVALID")
        return (f"{MacOSVMLifecycle.LABEL_PREFIX}.{workspace_identity[:12]}."
                f"{attempt_id.replace('-', '')}.{nonce_digest[:12]}")

    def _label(self, request: ContainedRequest) -> str:
        return self._label_values(request.attempt_id, request.nonce_digest,
                                  self.workspace_identity)

    def prepare(self, request: ContainedRequest) -> PreparedAttempt:
        if not isinstance(request, ContainedRequest):
            raise ContainmentContractError("REQUEST_TYPE_INVALID")
        attempt_created = False
        root_fd = attempt_fd = None
        try:
            artifacts = self._artifact_sources(request)
            mounts = self._mount_sources(request)
            root_fd, attempt_fd = self._open_attempt(request.attempt_id, create=True)
            attempt_created = True
            self._claim_nonce(root_fd, request)
            authority_fds: dict[str, int] = {}
            try:
                for directory in ("artifacts", "io", "mounts", "profiles", "receipts"):
                    os.mkdir(directory, 0o700, dir_fd=attempt_fd)
                    authority_fds[directory] = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                                                       getattr(os, "O_NOFOLLOW", 0), dir_fd=attempt_fd)
                    self._trusted_dir(authority_fds[directory], exact_private=True)
                total_bytes = 0
                identities = request.artifacts.as_dict()
                for name, source in artifacts.items():
                    total_bytes += self._snapshot_regular(source, authority_fds["artifacts"], name,
                        identities[name], request.ceilings.disk_bytes - total_bytes,
                        executable=(name == "helper"))
                for mount_id, source_ref in mounts.items():
                    os.mkdir(mount_id, 0o700, dir_fd=authority_fds["mounts"])
                    mount_fd = os.open(mount_id, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                                       getattr(os, "O_NOFOLLOW", 0), dir_fd=authority_fds["mounts"])
                    source_fd = self._open_mount_nofollow(source_ref)
                    try:
                        total_bytes += self._snapshot_regular(source_fd, mount_fd, "payload", None,
                            request.ceilings.disk_bytes - total_bytes)
                    finally:
                        os.close(source_fd); os.close(mount_fd)
                state_dir = self.state_root / request.attempt_id
                self._atomic_file(authority_fds["io"], "prompt", b"")
                basis = request.to_reference_dict()
                request_sha256 = self._canonical_sha256(basis)
                ap = lambda name: str(state_dir / "artifacts" / name)
                payload = {"protocolVersion": 1, "requestID": request.attempt_id,
                    "nonce": request.nonce, "requestSHA256": request_sha256,
                    "artifactGeneration": request.artifact_generation,
                    "artifacts": {"kernel": {"path": ap("kernel"), "sha256": identities["kernel"]},
                        "initramfs": {"path": ap("initramfs"), "sha256": identities["initramfs"]},
                        "rootDisk": {"path": ap("root_image"), "sha256": identities["root_image"]},
                        "cowDisk": {"path": ap("cow_disk"), "sha256": identities["cow_disk"]},
                        "guestAgent": {"sha256": identities["guest_agent"], "bakedInto": "rootDisk",
                            "rootManifest": {"path": ap("root_manifest"), "sha256": identities["root_manifest"]}}},
                    "execution": {"executable": request.executable_ref, "argv": list(request.argv_refs),
                        "env": [{"name": name, "reference": ref} for name, ref in sorted(request.env_refs.items())],
                        "strictContainment": True},
                    "resources": request.ceilings.as_dict(), "sockets": {"controlPort": 2201, "stdioPort": 2202},
                    "mounts": [{"role": "input", "tag": "input-" + m.mount_id,
                        "sourcePath": str(state_dir / "mounts" / m.mount_id), "guestPath": m.guest_path,
                        "readOnly": True} for m in request.mounts],
                    "network": {"mode": "disabled", "profile": None},
                    "io": {"prompt": {"path": str(state_dir / "io" / "prompt"),
                        "sha256": hashlib.sha256(b"").hexdigest()}, "outputPath": str(state_dir / "io" / "output")},
                    "receiptPath": str(state_dir / "receipts" / "helper.json")}
                self._json_file(attempt_fd, "request.json", payload)
                label = self._label(request)
                self._json_file(attempt_fd, "lifecycle.json", {"schema_version": 1,
                    "attempt_id": request.attempt_id, "label": label, "created_at": self.wall_clock(),
                    "phase": "prepared", "nonce_digest": request.nonce_digest,
                    "request_sha256": request_sha256, "artifact_generation": request.artifact_generation,
                    "workspace_identity": self.workspace_identity})
                plist = {"Label": label, "ProgramArguments": [ap("helper"), "--request-file",
                    str(state_dir / "request.json")], "WorkingDirectory": str(state_dir), "RunAtLoad": True,
                    "KeepAlive": False, "ProcessType": "Background", "Umask": 0o077,
                    "ExitTimeOut": request.ceilings.shutdown_grace_seconds,
                    "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null"}
                self._atomic_file(attempt_fd, "vm.plist", plistlib.dumps(plist, sort_keys=True))
                return PreparedAttempt(request.attempt_id, label, state_dir, state_dir / "request.json",
                    state_dir / "vm.plist", "", request.nonce_digest, request_sha256,
                    request.artifact_generation)
            finally:
                for descriptor in authority_fds.values(): os.close(descriptor)
        except BaseException:
            if attempt_created:
                try:
                    if attempt_fd is not None:
                        os.close(attempt_fd)
                        attempt_fd = None
                    if root_fd is not None:
                        os.close(root_fd)
                        root_fd = None
                    self._remove_attempt(request.attempt_id)
                except BaseException:
                    pass
            raise
        finally:
            if attempt_fd is not None:
                os.close(attempt_fd)
            if root_fd is not None:
                os.close(root_fd)

    def _command(self, argv: Sequence[str]) -> CommandResult:
        return self.runner(tuple(argv), timeout=self.COMMAND_TIMEOUT)

    def _registration_state(self, label: str) -> str:
        result = self._command(("/bin/launchctl", "print", f"{self.domain}/{label}"))
        if result.returncode == 0:
            return "present"
        # The adapter contract recognizes only the explicitly tested
        # service-not-found result. Permission and manager failures stay unknown.
        if result.returncode == 113:
            return "absent"
        return "unknown"

    def _teardown(self, label: str) -> tuple[bool, bool]:
        acknowledged = False
        absent = False
        try:
            result = self._command(("/bin/launchctl", "bootout", f"{self.domain}/{label}"))
            acknowledged = result.returncode == 0
        except BaseException:
            pass
        try:
            absent = self._registration_state(label) == "absent"
        except BaseException:
            absent = False
        return acknowledged, absent

    @staticmethod
    def _guest_exit(request: ContainedRequest, value: Mapping[str, Any]) -> ContainedExit:
        required = {"code", "output_bytes", "output_truncated", "detail_codes",
                    "stop_acknowledged", "teardown_confirmed"}
        legacy = {"code", "output_bytes", "output_truncated", "detail_codes"}
        if not isinstance(value, Mapping) or set(value) not in (required, legacy):
            raise ContainmentLifecycleError("HELPER_RECEIPT_INVALID")
        code = value["code"]
        size = value["output_bytes"]
        truncated = value["output_truncated"]
        raw_details = value["detail_codes"]
        if (isinstance(code, bool) or not isinstance(code, int) or not -255 <= code <= 255 or
                isinstance(size, bool) or not isinstance(size, int) or size < 0 or
                not isinstance(truncated, bool) or not isinstance(raw_details, (list, tuple)) or
                any(not isinstance(item, str) for item in raw_details)):
            raise ContainmentLifecycleError("HELPER_RECEIPT_INVALID")
        details = tuple(raw_details)
        if size > request.ceilings.output_bytes:
            size = request.ceilings.output_bytes
            truncated = True
            details = details + ("OUTPUT_LIMIT",)
        return _bound_exit(request, "completed", code=code,
                             output_truncated=truncated, output_bytes=size,
                             stop_acknowledged=value.get("stop_acknowledged", False),
                             teardown_confirmed=value.get("teardown_confirmed", False),
                             detail_codes=details)

    def _publish_exit(self, exit_value: ContainedExit) -> None:
        root_fd, attempt_fd = self._open_attempt(exit_value.attempt_id, create=False)
        try:
            if exit_value.teardown_confirmed and exit_value.label_absent:
                self._cleanup_transient(attempt_fd)
            self._json_file(attempt_fd, "receipt.json", exit_value.to_receipt())
            self._json_file(attempt_fd, "lifecycle.json", {
                "schema_version": 1, "attempt_id": exit_value.attempt_id,
                "phase": "terminal", "classification": exit_value.classification,
            })
        finally:
            os.close(attempt_fd)
            os.close(root_fd)

    def execute(self, request: ContainedRequest, *, cancelled: Callable[[], bool] = lambda: False) -> ContainedExit:
        prepared: PreparedAttempt | None = None
        launched = False
        try:
            prepared = self.prepare(request)
            if cancelled():
                value = _bound_exit(request, "cancelled", cancelled=True,
                                      label_absent=True, detail_codes=("CANCELLED_PRELAUNCH",))
                self._publish_exit(value)
                return value
            try:
                registration = self._registration_state(prepared.label)
            except BaseException:
                registration = "unknown"
            if registration != "absent":
                return _bound_exit(
                    request, "prelaunch_failed", label_absent=False,
                    detail_codes=(("LABEL_ALREADY_REGISTERED",) if registration == "present"
                                  else ("PRELAUNCH_PRINT_UNKNOWN",)))
            # Once bootstrap is submitted, every return and exception is treated
            # as potentially launched until a bounded print proves absence.
            launched = True
            result = self._command(("/bin/launchctl", "bootstrap", self.domain, str(prepared.plist_path)))
            if result.returncode != 0:
                raise ContainmentLifecycleError("BOOTSTRAP_OUTCOME_UNKNOWN")
            deadline = self.clock() + request.ceilings.timeout_seconds
            max_polls = max(1, math.ceil(request.ceilings.timeout_seconds / self.POLL_INTERVAL) + 1)
            value: ContainedExit | None = None
            for _ in range(max_polls):
                if cancelled():
                    value = _bound_exit(request, "cancelled", cancelled=True,
                                          detail_codes=("CANCELLED",))
                    break
                if self.clock() >= deadline:
                    value = _bound_exit(request, "timed_out", timed_out=True,
                                          detail_codes=("TIMEOUT",))
                    break
                try:
                    helper_value = self.helper.poll(prepared.state_dir, request)
                except BaseException:
                    value = _bound_exit(request, "launched_unknown",
                                          detail_codes=("HELPER_OUTCOME_UNKNOWN",))
                    break
                if helper_value is not None:
                    value = self._guest_exit(request, helper_value)
                    break
                self.sleeper(min(self.POLL_INTERVAL, max(0.0, deadline - self.clock())))
            if value is None:
                value = _bound_exit(request, "timed_out", timed_out=True,
                                      detail_codes=("POLL_BOUND_EXHAUSTED",))
        except ContainmentLifecycleError as exc:
            if prepared is None or not launched:
                if prepared is not None:
                    self._remove_attempt(request.attempt_id)
                return _bound_exit(request, "prelaunch_failed", label_absent=True,
                                     detail_codes=(str(exc),) if str(exc).isupper() else ("PRELAUNCH_FAILED",))
            value = _bound_exit(request, "launched_unknown",
                                  detail_codes=("BOOTSTRAP_OUTCOME_UNKNOWN",))
        except BaseException:
            if prepared is None:
                return _bound_exit(request, "prelaunch_failed", label_absent=True,
                                     detail_codes=("PRELAUNCH_FAILED",))
            if not launched:
                self._remove_attempt(request.attempt_id)
                return _bound_exit(request, "prelaunch_failed", label_absent=True,
                                     detail_codes=("PRELAUNCH_FAILED",))
            value = _bound_exit(request, "launched_unknown",
                                  detail_codes=("BOOTSTRAP_OUTCOME_UNKNOWN",))

        assert prepared is not None
        acknowledged, absent = self._teardown(prepared.label)
        if value.classification == "completed" and not (value.teardown_confirmed and absent):
            value = _bound_exit(request, "launched_unknown", code=value.code,
                                  output_truncated=value.output_truncated, output_bytes=value.output_bytes,
                                  stop_acknowledged=value.stop_acknowledged,
                                  teardown_confirmed=value.teardown_confirmed,
                                  detail_codes=value.detail_codes + ("TEARDOWN_OUTCOME_UNKNOWN",))
        value = replace(value, launchctl_bootout_acknowledged=acknowledged, label_absent=absent)
        self._publish_exit(value)
        return value

    def reconcile_stale(self, *, older_than_seconds: float) -> tuple[ReconcileResult, ...]:
        if older_than_seconds < 0:
            raise ValueError("STALE_AGE_INVALID")
        root_fd = self._open_state_root()
        results: list[ReconcileResult] = []
        try:
            for attempt_id in sorted(os.listdir(root_fd)):
                try:
                    if str(UUID(attempt_id)) != attempt_id:
                        continue
                    attempt_fd = os.open(attempt_id, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                                         getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
                except (ContainmentContractError, OSError, ValueError):
                    continue
                try:
                    self._trusted_dir(attempt_fd, exact_private=True)
                    metadata = self._read_private_json(attempt_fd, "lifecycle.json")
                    request_state = self._read_private_json(attempt_fd, "request.json")
                    if metadata.get("attempt_id") != attempt_id or metadata.get("phase") == "terminal":
                        continue
                    created = metadata.get("created_at")
                    now = self.wall_clock()
                    valid_time = (not isinstance(created, bool) and isinstance(created, (int, float)) and
                                  math.isfinite(created) and created <= now)
                    if valid_time and now - created < older_than_seconds:
                        continue
                    if request_state.get("requestID") != attempt_id:
                        continue
                    expected_label = self._label_values(attempt_id, metadata.get("nonce_digest"),
                                                        metadata.get("workspace_identity"))
                    label = metadata.get("label")
                    if label != expected_label:
                        continue
                    acknowledged, absent = self._teardown(label)
                    results.append(ReconcileResult(attempt_id, label, acknowledged, absent))
                    if absent:
                        self._json_file(attempt_fd, "lifecycle.json", {
                            **metadata, "phase": "reconcile_pending_vm_confirmation",
                            "classification": "launched_unknown",
                        })
                        self._json_file(attempt_fd, "receipt.json", ContainedExit(
                            attempt_id, "launched_unknown", metadata["nonce_digest"],
                            metadata["request_sha256"], metadata["artifact_generation"],
                            launchctl_bootout_acknowledged=acknowledged,
                            label_absent=True, detail_codes=("STALE_RECONCILED",)).to_receipt())
                except (OSError, ValueError, json.JSONDecodeError, ContainmentLifecycleError):
                    continue
                finally:
                    os.close(attempt_fd)
        finally:
            os.close(root_fd)
        return tuple(results)
