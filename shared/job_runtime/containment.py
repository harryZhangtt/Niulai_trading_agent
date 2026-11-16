"""Strict, serializable contracts for source-only job containment.

Values crossing this boundary are references, never prompts, credentials, or raw
command arguments.  The macOS adapter is intentionally implemented separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID


_SHA256 = re.compile(r"[0-9a-f]{64}")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_NONCE = re.compile(r"[0-9a-f]{64}")
_ENV = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_SECRET = re.compile(r"(?:SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE_?KEY|AUTH|COOKIE)", re.I)
_TOKEN_LITERAL = re.compile(r"(?:sk|pk|ghp|github_pat|xox[baprs]|eyJ)[-_.A-Za-z0-9]{8,}", re.I)
_ALLOWED_GUEST_PREFIXES = ("/workspace/", "/input/", "/output/")


class ContainmentContractError(ValueError):
    """The request cannot safely cross the containment boundary."""


def _uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ContainmentContractError("ATTEMPT_ID_INVALID") from None
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ContainmentContractError("ATTEMPT_ID_INVALID")
    return str(parsed)


def _has_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _reference(value: str, code: str = "REFERENCE_INVALID") -> str:
    if not isinstance(value, str) or _has_control(value) or not _REF.fullmatch(value):
        raise ContainmentContractError(code)
    return value


def _env_reference(value: str) -> str:
    value = _reference(value, "ENV_REF_INVALID")
    if _SECRET.search(value) or _TOKEN_LITERAL.fullmatch(value):
        raise ContainmentContractError("ENV_REF_SECRET_LIKE")
    return value


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 or _has_control(value):
        raise ContainmentContractError("MOUNT_SOURCE_INVALID")
    parts = value.split("/")
    if value.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise ContainmentContractError("MOUNT_SOURCE_INVALID")
    return value


def _positive(value: int, maximum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise ContainmentContractError(code)
    return value


@dataclass(frozen=True)
class MountReference:
    """One exact, workspace-relative source exposed at a fixed guest path."""

    mount_id: str
    source_ref: str
    guest_path: str
    read_only: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "mount_id", _reference(self.mount_id, "MOUNT_ID_INVALID"))
        object.__setattr__(self, "source_ref", _relative(self.source_ref))
        if (not isinstance(self.guest_path, str) or len(self.guest_path) > 256 or
                _has_control(self.guest_path) or
                not self.guest_path.startswith(_ALLOWED_GUEST_PREFIXES) or
                "//" in self.guest_path or any(p in (".", "..") for p in self.guest_path.split("/"))):
            raise ContainmentContractError("GUEST_MOUNT_INVALID")
        if self.read_only is not True:
            raise ContainmentContractError("WRITABLE_MOUNT_REFUSED")

    def to_reference(self) -> dict[str, Any]:
        return {"mount_id": self.mount_id, "source_ref": self.source_ref,
                "guest_path": self.guest_path, "read_only": True}


@dataclass(frozen=True)
class ArtifactIdentities:
    """SHA256 identities for every executable VM artifact."""

    helper: str
    kernel: str
    initramfs: str
    root_image: str
    cow_disk: str
    guest_agent: str
    root_manifest: str

    def __post_init__(self) -> None:
        for name in ("helper", "kernel", "initramfs", "root_image", "cow_disk", "guest_agent", "root_manifest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ContainmentContractError("ARTIFACT_SHA256_INVALID")

    def as_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in
                ("helper", "kernel", "initramfs", "root_image", "cow_disk", "guest_agent", "root_manifest")}


@dataclass(frozen=True)
class ResourceCeilings:
    timeout_seconds: int
    output_bytes: int
    memory_bytes: int
    disk_bytes: int
    cpu_count: int
    shutdown_grace_seconds: int = 10
    max_frame_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        _positive(self.timeout_seconds, 86_400, "TIMEOUT_CEILING_INVALID")
        _positive(self.output_bytes, 16 * 1024 * 1024, "OUTPUT_CEILING_INVALID")
        memory = _positive(self.memory_bytes, 64 * 1024**3, "MEMORY_CEILING_INVALID")
        if memory % (1024 * 1024):
            raise ContainmentContractError("MEMORY_CEILING_INVALID")
        _positive(self.disk_bytes, 1024**4, "DISK_CEILING_INVALID")
        _positive(self.cpu_count, 64, "CPU_CEILING_INVALID")
        _positive(self.shutdown_grace_seconds, 300, "SHUTDOWN_GRACE_INVALID")
        _positive(self.max_frame_bytes, 16 * 1024 * 1024, "FRAME_CEILING_INVALID")

    @property
    def memory_mib(self) -> int:
        return self.memory_bytes // (1024 * 1024)

    def as_dict(self) -> dict[str, int]:
        return {"cpuCount": self.cpu_count, "memoryMiB": self.memory_mib,
                "maxRuntimeSeconds": self.timeout_seconds,
                "shutdownGraceSeconds": self.shutdown_grace_seconds,
                "maxFrameBytes": self.max_frame_bytes,
                "maxOutputBytes": self.output_bytes, "maxDiskBytes": self.disk_bytes}


@dataclass(frozen=True)
class ContainedRequest:
    attempt_id: str
    executable_ref: str
    argv_refs: tuple[str, ...]
    env_refs: Mapping[str, str]
    mounts: tuple[MountReference, ...]
    ceilings: ResourceCeilings
    artifacts: ArtifactIdentities
    nonce: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _uuid(self.attempt_id))
        object.__setattr__(self, "executable_ref", _reference(self.executable_ref, "EXECUTABLE_REF_INVALID"))
        if not isinstance(self.argv_refs, tuple) or len(self.argv_refs) > 128:
            raise ContainmentContractError("ARGV_REFS_INVALID")
        object.__setattr__(self, "argv_refs", tuple(_reference(v, "ARGV_REF_INVALID") for v in self.argv_refs))
        if not isinstance(self.env_refs, Mapping) or len(self.env_refs) > 64:
            raise ContainmentContractError("ENV_REFS_INVALID")
        env: dict[str, str] = {}
        for name, ref in self.env_refs.items():
            if not isinstance(name, str) or not _ENV.fullmatch(name) or _SECRET.search(name):
                raise ContainmentContractError("ENV_NAME_REFUSED")
            env[name] = _env_reference(ref)
        object.__setattr__(self, "env_refs", MappingProxyType(env))
        if not isinstance(self.mounts, tuple) or not self.mounts or len(self.mounts) > 32:
            raise ContainmentContractError("MOUNTS_INVALID")
        ids = [mount.mount_id for mount in self.mounts]
        guests = [mount.guest_path for mount in self.mounts]
        sources = [mount.source_ref for mount in self.mounts]
        if len(set(ids)) != len(ids) or len(set(guests)) != len(guests) or len(set(sources)) != len(sources):
            raise ContainmentContractError("MOUNT_DUPLICATE")
        if not isinstance(self.ceilings, ResourceCeilings) or not isinstance(self.artifacts, ArtifactIdentities):
            raise ContainmentContractError("CONTRACT_TYPE_INVALID")
        if not isinstance(self.nonce, str) or not _NONCE.fullmatch(self.nonce):
            raise ContainmentContractError("NONCE_INVALID")

    @property
    def nonce_digest(self) -> str:
        return hashlib.sha256(self.nonce.encode("ascii")).hexdigest()

    @property
    def artifact_generation(self) -> str:
        data = json.dumps(self.artifacts.as_dict(), sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def to_reference_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2, "attempt_id": self.attempt_id,
            "executable_ref": self.executable_ref, "argv_refs": list(self.argv_refs),
            "env_refs": dict(self.env_refs), "mounts": [m.to_reference() for m in self.mounts],
            "ceilings": self.ceilings.as_dict(), "artifacts": self.artifacts.as_dict(),
            "nonce_digest": self.nonce_digest,
            "artifact_generation": self.artifact_generation,
        }


_EXIT_CLASSES = {"completed", "prelaunch_failed", "launched_unknown", "timed_out", "cancelled"}
_SAFE_DETAIL = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


@dataclass(frozen=True)
class ContainedExit:
    """Bounded receipt that cannot carry command, prompt, environment, or host paths."""

    attempt_id: str
    classification: str
    nonce_digest: str
    request_sha256: str
    artifact_generation: str
    code: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    output_truncated: bool = False
    stop_acknowledged: bool = False
    teardown_confirmed: bool = False
    launchctl_bootout_acknowledged: bool = False
    label_absent: bool = False
    detail_codes: tuple[str, ...] = field(default_factory=tuple)
    output_bytes: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _uuid(self.attempt_id))
        if type(self.classification) is not str or self.classification not in _EXIT_CLASSES:
            raise ContainmentContractError("EXIT_CLASS_INVALID")
        for digest in (self.nonce_digest, self.request_sha256, self.artifact_generation):
            if type(digest) is not str or not _SHA256.fullmatch(digest):
                raise ContainmentContractError("EXIT_BINDING_INVALID")
        if self.code is not None and (type(self.code) is not int or not -255 <= self.code <= 255):
            raise ContainmentContractError("EXIT_CODE_INVALID")
        for flag in (self.timed_out, self.cancelled, self.output_truncated,
                     self.stop_acknowledged, self.teardown_confirmed,
                     self.launchctl_bootout_acknowledged, self.label_absent):
            if type(flag) is not bool:
                raise ContainmentContractError("EXIT_FLAG_INVALID")
        if (not isinstance(self.detail_codes, tuple) or len(self.detail_codes) > 16 or
                any(type(v) is not str or not _SAFE_DETAIL.fullmatch(v) for v in self.detail_codes)):
            raise ContainmentContractError("EXIT_DETAIL_INVALID")
        if type(self.output_bytes) is not int or not 0 <= self.output_bytes <= 16 * 1024 * 1024:
            raise ContainmentContractError("EXIT_OUTPUT_INVALID")
        if self.timed_out != (self.classification == "timed_out"):
            raise ContainmentContractError("EXIT_TIMEOUT_INCONSISTENT")
        if self.cancelled != (self.classification == "cancelled"):
            raise ContainmentContractError("EXIT_CANCEL_INCONSISTENT")
        if self.classification == "completed" and self.code is None:
            raise ContainmentContractError("EXIT_CODE_REQUIRED")

    def to_receipt(self) -> dict[str, Any]:
        return {
            "schema_version": 2, "attempt_id": self.attempt_id,
            "nonce_digest": self.nonce_digest, "request_sha256": self.request_sha256,
            "artifact_generation": self.artifact_generation,
            "classification": self.classification, "code": self.code,
            "flags": {"timed_out": self.timed_out, "cancelled": self.cancelled,
                      "output_truncated": self.output_truncated},
            "output_bytes": self.output_bytes,
            "stopAcknowledged": self.stop_acknowledged,
            "teardownConfirmed": self.teardown_confirmed,
            "launchctlBootoutAcknowledged": self.launchctl_bootout_acknowledged,
            "labelAbsent": self.label_absent,
            "detail_codes": list(self.detail_codes),
        }
