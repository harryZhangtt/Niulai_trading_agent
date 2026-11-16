"""Materialize credential-free Codex/Claude host profiles for live acquisition.

This helper validates operational host observations and writes only sanitized public
contracts. It never reads an auth store, activates MCP, invokes a provider, creates
execution roots, or treats synthetic/model-authored evidence as live readiness.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time
from typing import Any, Mapping

from shared.research_sources.host_adapter_contracts import (
    AdapterId,
    Capability,
    CredentialReadinessReceipt,
    CredentialRef,
    CredentialSource,
    HostAdapterProfile,
    HostBudget,
    HostContractError,
    HostExecutionBinding,
    NON_CRYPTO_LIMITATION,
    Operation,
    OperationalTrustPolicy,
    RuntimeProfileRef,
    ToolBinding,
    WorkspaceFileRef,
    validate_execution_pair,
)
from shared.research_sources.live_session_custody import (
    reopen_and_validate_materialized_bundle,
)


VERSION = "host-profile-materializer-1"
INPUT_VERSION = "host-profile-materialization-input-1"
ROOT = Path(__file__).resolve().parents[4]
MAX_INPUT = 256 * 1024
MAX_OUTPUT = 256 * 1024
LOCK_TIMEOUT_SECONDS = 1.0
LOCK_POLL_SECONDS = 0.01
_ALLOWED_STATE_ROOTS = {".job-runtime", ".research-sources"}
_FORBIDDEN_KEYS = frozenset({
    "apikey", "accesstoken", "refreshtoken", "password", "clientsecret",
    "credentialvalue", "tokenvalue", "secretvalue", "cookie", "authorization",
    "privatekey", "env", "environment",
})
_UNSAFE_TEXT = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]+"),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\b(?:xox[baprs]-|gh[pousr]_)[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|"
               r"client[_-]?secret)\s*[=:]"),
    re.compile(r"(?:^|\s)(?:/Users/|/home/|[A-Za-z]:[/\\])"),
)
_URL_TEXT = re.compile(r"https?://", re.IGNORECASE)
_PROFILE_REF_ROOTS = frozenset({"runtime", "profiles"})
_ALLOWED_PATH_ROOT_SEGMENTS = _ALLOWED_STATE_ROOTS | _PROFILE_REF_ROOTS
_FORBIDDEN_PATH_SEGMENTS = frozenset({
    "env", "auth", "authentication", "oauth", "oauth2", "credential",
    "credentials", "secret", "secrets", "profile", "profiles", "aws", "ssh",
    "config", "keychain",
})
_BUNDLE_FILES = tuple(
    f"{host}-{suffix}.json"
    for host in ("codex", "claude")
    for suffix in ("profile", "credential-readiness", "binding")
)
_MANIFEST_NAME = "materialization-manifest.json"
_LOCK_NAME = ".materialize.lock"
_GENERATION_NAME = re.compile(r"^generation-[a-f0-9]{64}$")
_STAGING_NAME = re.compile(
    r"^\.generation-(?P<digest>[a-f0-9]{64})\.[0-9]+\.[a-f0-9]{16}\.tmp$")
_MAX_ORPHAN_STAGING = 16
_TEMP_NAME = re.compile(
    r"^\.(?:codex|claude)-(?:profile|credential-readiness|binding)\.json\."
    r"[0-9]+\.[a-f0-9]{16}\.[a-f0-9]{16}\.tmp$|"
    r"^\.materialization-manifest\.json\.[0-9]+\.[a-f0-9]{16}\.[a-f0-9]{16}\.tmp$"
)


class MaterializeHostError(ValueError):
    """Stable, secret-free materialization rejection."""


class _UnknownWriteOutcome(RuntimeError):
    """Internal marker for a write whose durable outcome cannot be proven."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise MaterializeHostError(code)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise MaterializeHostError("HOST_MATERIALIZE_JSON_INVALID") from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        _require(key not in value, "HOST_MATERIALIZE_INPUT_FILE")
        value[key] = item
    return value


def _path_segment_tokens(segment: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[^a-z0-9]+", segment.lower())
                 if token)


def _reject_path_field(value: str) -> None:
    parts = [part for part in re.split(r"[/\\]+", value) if part]
    for index, part in enumerate(parts):
        if index == 0 and part.lower() in _ALLOWED_PATH_ROOT_SEGMENTS:
            continue
        tokens = _path_segment_tokens(part)
        _require(not (set(tokens) & _FORBIDDEN_PATH_SEGMENTS),
                 "HOST_MATERIALIZE_SECRET_REJECTED")


def _reject_profile_ref(value: Any) -> None:
    _require(isinstance(value, str) and value,
             "HOST_MATERIALIZE_CREDENTIAL_REF")
    parts = [part for part in re.split(r"[/\\]+", value) if part]
    forbidden = {"env", "auth", "authentication", "oauth", "oauth2",
                 "credential", "credentials", "secret", "secrets"}
    file_suffixes = {".json", ".yaml", ".yml", ".toml", ".env", ".ini",
                     ".conf", ".config"}
    if len(parts) == 1:
        standalone_tokens = _path_segment_tokens(parts[0])
        _require(not (len(standalone_tokens) == 1
                      and standalone_tokens[0] in forbidden),
                 "HOST_MATERIALIZE_SECRET_REJECTED")
    path_like = (len(parts) > 1 or value.startswith(".")
                 or Path(value).suffix.lower() in file_suffixes)
    if not path_like:
        return
    for index, part in enumerate(parts):
        if index == 0 and part.lower() in _ALLOWED_PATH_ROOT_SEGMENTS:
            continue
        tokens = _path_segment_tokens(part)
        _require(not (set(tokens) & forbidden),
                 "HOST_MATERIALIZE_SECRET_REJECTED")


def _reject_secrets(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            _require(normalized not in _FORBIDDEN_KEYS,
                     "HOST_MATERIALIZE_SECRET_REJECTED")
            _reject_secrets(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _reject_secrets(item)
    elif isinstance(value, str):
        _require(not _URL_TEXT.search(value)
                 and not any(pattern.search(value) for pattern in _UNSAFE_TEXT),
                 "HOST_MATERIALIZE_SECRET_REJECTED")


def _strict(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    _require(isinstance(value, dict) and set(value) == keys, code)
    return value


def _relative(value: Any, code: str) -> Path:
    _require(isinstance(value, str) and value and len(value) <= 512, code)
    path = Path(value)
    _require(not path.is_absolute() and path.parts and ".." not in path.parts
             and all(part not in {"", "."} for part in path.parts), code)
    return path


def _safe_path(root: Path, relative: Path, code: str) -> Path:
    _require(relative.parts[0] in _ALLOWED_STATE_ROOTS, code)
    current = root
    for part in relative.parts:
        current = current / part
        _require(not current.is_symlink(), code)
    try:
        current.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        raise MaterializeHostError(code) from None
    return current


def _directory_mode(path: Path, code: str) -> None:
    try:
        info = path.stat()
        valid = (path.is_dir() and not path.is_symlink()
                 and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o700)
    except OSError:
        valid = False
    _require(valid, code)


def _private_file_signature(info: os.stat_result, *, max_size: int,
                            exact_mode: int | None, code: str) -> tuple[int, ...]:
    mode = stat.S_IMODE(info.st_mode)
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
             and info.st_nlink == 1
             and (mode == exact_mode if exact_mode is not None else mode & 0o077 == 0)
             and 0 < info.st_size <= max_size, code)
    return (info.st_mode, info.st_uid, info.st_gid, info.st_dev, info.st_ino,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory_signature(info: os.stat_result, code: str) -> tuple[int, ...]:
    mode = stat.S_IMODE(info.st_mode)
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
             and mode & 0o022 == 0, code)
    return (info.st_mode, info.st_uid, info.st_gid, info.st_dev, info.st_ino,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _validate_mutable_root(root: Path, value: str) -> Path:
    _require(isinstance(value, str), "HOST_MATERIALIZE_MUTABLE_ROOT")
    _reject_path_field(value)
    relative = _relative(value, "HOST_MATERIALIZE_MUTABLE_ROOT")
    path = _safe_path(root, relative, "HOST_MATERIALIZE_MUTABLE_ROOT")
    if path.exists():
        _directory_mode(path, "HOST_MATERIALIZE_MUTABLE_ROOT")
        _require(not any(path.iterdir()), "HOST_MATERIALIZE_MUTABLE_ROOT_NOT_EMPTY")
    return path.resolve(strict=False)


def _workspace_ref(value: Any, expected_root: str) -> WorkspaceFileRef:
    row = _strict(value, {"path", "sha256"}, "HOST_MATERIALIZE_FILE_REF")
    relative = _relative(row["path"], "HOST_MATERIALIZE_FILE_REF")
    _require(relative.parts[0] == expected_root
             and expected_root in _PROFILE_REF_ROOTS
             and all(not part.startswith(".") for part in relative.parts),
             "HOST_MATERIALIZE_FILE_REF")
    _reject_secrets(row["path"])
    _reject_path_field(row["path"])
    try:
        return WorkspaceFileRef(**row)
    except (TypeError, HostContractError) as error:
        raise MaterializeHostError("HOST_MATERIALIZE_FILE_REF") from error


def _profile(host: str, row: dict[str, Any]) -> tuple[HostExecutionBinding, str]:
    expected = {
        "host", "host_session_id", "runtime_identity", "interpreter_ref",
        "runtime_profile_ref", "credential", "execution", "observation",
    }
    _strict(row, expected, "HOST_MATERIALIZE_HOST_SCHEMA")
    _require(row["host"] == host, "HOST_MATERIALIZE_HOST_ORDER")
    credential_row = _strict(
        row["credential"],
        {"owner_ref", "source", "profile_ref", "fingerprint_sha256"},
        "HOST_MATERIALIZE_CREDENTIAL_REF",
    )
    _reject_profile_ref(credential_row["profile_ref"])
    execution = _strict(
        row["execution"],
        {"execution_id", "trace_id", "dispatch_namespace", "artifact_root",
         "cache_root", "budget"},
        "HOST_MATERIALIZE_EXECUTION",
    )
    budget_row = _strict(
        execution["budget"],
        {"search_items", "open_items", "provider_items", "concurrency",
         "call_timeout_seconds", "run_timeout_seconds"},
        "HOST_MATERIALIZE_BUDGET",
    )
    try:
        runtime = RuntimeProfileRef(
            runtime_identity=row["runtime_identity"],
            interpreter_ref=_workspace_ref(row["interpreter_ref"], "runtime"),
            profile_ref=_workspace_ref(row["runtime_profile_ref"], "profiles"),
        )
        if host == "codex":
            source = CredentialSource.CODEX_PROFILE
            _require(credential_row["source"] == source.value,
                     "HOST_MATERIALIZE_CREDENTIAL_SOURCE")
            profile = HostAdapterProfile(
                adapter_id=AdapterId.CODEX_NATIVE_WEB,
                configured_backend="native_tools.web__run",
                tool_bindings=tuple(ToolBinding(operation, "native_tools.web__run")
                                    for operation in (Operation.SEARCH, Operation.OPEN,
                                                      Operation.FIND)),
                capabilities=frozenset({Capability.SEARCH, Capability.OPEN,
                                        Capability.FIND, Capability.RAW_BODY_FIDELITY}),
                runtime=runtime,
                credential=CredentialRef(
                    credential_row["owner_ref"], source,
                    credential_row["profile_ref"],
                    credential_row["fingerprint_sha256"],
                ),
                mcp=None,
            )
        else:
            source = CredentialSource.CLAUDE_PROFILE
            _require(credential_row["source"] == source.value,
                     "HOST_MATERIALIZE_CREDENTIAL_SOURCE")
            profile = HostAdapterProfile(
                adapter_id=AdapterId.CLAUDE_CODE_WEB,
                configured_backend="claude_code.web",
                tool_bindings=(
                    ToolBinding(Operation.SEARCH, "claude_code.WebSearch"),
                    ToolBinding(Operation.OPEN, "claude_code.WebFetch"),
                ),
                capabilities=frozenset({Capability.SEARCH, Capability.OPEN,
                                        Capability.RENDERED_EXTRACT}),
                runtime=runtime,
                credential=CredentialRef(
                    credential_row["owner_ref"], source,
                    credential_row["profile_ref"],
                    credential_row["fingerprint_sha256"],
                ),
                mcp=None,
            )
        binding = HostExecutionBinding(
            profile=profile,
            execution_id=execution["execution_id"],
            trace_id=execution["trace_id"],
            dispatch_namespace=execution["dispatch_namespace"],
            artifact_root=execution["artifact_root"],
            cache_root=execution["cache_root"],
            budget=HostBudget(**budget_row),
        )
    except (TypeError, ValueError, HostContractError) as error:
        raise MaterializeHostError("HOST_MATERIALIZE_PROFILE_INVALID") from error
    return binding, row["host_session_id"]


def _receipt(row: dict[str, Any], binding: HostExecutionBinding,
             host_session_id: str, *, now: datetime) -> CredentialReadinessReceipt:
    expected = {
        "version", "adapter_id", "owner_ref", "profile_ref",
        "profile_fingerprint_sha256", "host_session_id", "capability_observed",
        "checked_at", "status", "source", "trust_policy", "limitations",
        "credential_values_present", "cryptographic_remote_attestation",
        "live_acceptance_eligible",
    }
    _strict(row, expected, "HOST_MATERIALIZE_OBSERVATION_SCHEMA")
    _require(row["credential_values_present"] is False
             and row["cryptographic_remote_attestation"] is False,
             "HOST_MATERIALIZE_CREDENTIAL_VALUE_REJECTED")
    try:
        receipt = CredentialReadinessReceipt.from_public_dict(row)
    except HostContractError as error:
        raise MaterializeHostError("HOST_MATERIALIZE_OBSERVATION_INVALID") from error
    credential = binding.profile.credential
    _require(receipt.adapter_id is binding.profile.adapter_id
             and receipt.owner_ref == credential.owner_ref
             and receipt.profile_ref == credential.profile_ref
             and receipt.profile_fingerprint_sha256 is not None
             and receipt.profile_fingerprint_sha256 == credential.fingerprint_sha256
             and receipt.host_session_id == host_session_id
             and receipt.capability_observed == binding.profile.configured_backend
             and receipt.trust_policy is OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE
             and receipt.limitations == (NON_CRYPTO_LIMITATION,),
             "HOST_MATERIALIZE_OBSERVATION_MISMATCH")
    checked = datetime.fromisoformat(receipt.checked_at.replace("Z", "+00:00"))
    now = now.astimezone(timezone.utc)
    age = (now - checked.astimezone(timezone.utc)).total_seconds()
    _require(-5 <= age <= 900, "HOST_MATERIALIZE_OBSERVATION_STALE")
    _require(row["live_acceptance_eligible"] == receipt.live_acceptance_eligible,
             "HOST_MATERIALIZE_OBSERVATION_ELIGIBILITY")
    return receipt


def _validate_generated(kind: str, value: dict[str, Any], *,
                        workspace_root: Path) -> Any:
    """Reconstruct and verify every persisted public shape against closed contracts."""
    _reject_secrets(value)
    if kind == "profile":
        _strict(value, {"version", "adapter_id", "configured_backend", "tool_bindings",
                        "capabilities", "runtime", "credential", "mcp"},
                "HOST_MATERIALIZE_PROFILE_OUTPUT")
        _require(value["version"] == "host-adapter-contracts-1"
                 and value["mcp"] is None
                 and isinstance(value["tool_bindings"], list)
                 and all(isinstance(row, dict)
                         and set(row) == {"operation", "observed_tool_identity"}
                         for row in value["tool_bindings"])
                 and isinstance(value["capabilities"], list),
                 "HOST_MATERIALIZE_PROFILE_OUTPUT")
        runtime = _strict(value["runtime"], {"runtime_identity", "interpreter_ref",
                                             "profile_ref"},
                          "HOST_MATERIALIZE_PROFILE_OUTPUT")
        credential = _strict(value["credential"],
                             {"owner_ref", "source", "profile_ref",
                              "fingerprint_sha256", "credential_value_present"},
                             "HOST_MATERIALIZE_PROFILE_OUTPUT")
        _require(credential["credential_value_present"] is False,
                 "HOST_MATERIALIZE_PROFILE_OUTPUT")
        _reject_profile_ref(credential["profile_ref"])
        try:
            parsed = HostAdapterProfile(
                adapter_id=AdapterId(value["adapter_id"]),
                configured_backend=value["configured_backend"],
                tool_bindings=tuple(ToolBinding(
                    Operation(row["operation"]), row["observed_tool_identity"])
                    for row in value["tool_bindings"]),
                capabilities=frozenset(Capability(item)
                                       for item in value["capabilities"]),
                runtime=RuntimeProfileRef(
                    runtime_identity=runtime["runtime_identity"],
                    interpreter_ref=_workspace_ref(runtime["interpreter_ref"], "runtime"),
                    profile_ref=_workspace_ref(runtime["profile_ref"], "profiles"),
                ),
                credential=CredentialRef(
                    owner_ref=credential["owner_ref"],
                    source=CredentialSource(credential["source"]),
                    profile_ref=credential["profile_ref"],
                    fingerprint_sha256=credential["fingerprint_sha256"],
                ),
                mcp=None,
            )
            parsed.verify(workspace_root)
        except (KeyError, TypeError, ValueError, HostContractError) as error:
            raise MaterializeHostError("HOST_MATERIALIZE_PROFILE_OUTPUT") from error
        _require(parsed.to_public_dict() == value,
                 "HOST_MATERIALIZE_PROFILE_OUTPUT")
        return parsed
    if kind == "credential-readiness":
        expected = {"version", "adapter_id", "owner_ref", "profile_ref",
                    "profile_fingerprint_sha256", "host_session_id",
                    "capability_observed", "checked_at", "status", "source",
                    "trust_policy", "limitations", "credential_values_present",
                    "cryptographic_remote_attestation", "live_acceptance_eligible"}
        _strict(value, expected, "HOST_MATERIALIZE_RECEIPT_OUTPUT")
        try:
            receipt = CredentialReadinessReceipt.from_public_dict(value)
        except HostContractError as error:
            raise MaterializeHostError("HOST_MATERIALIZE_RECEIPT_OUTPUT") from error
        _require(receipt.to_public_dict() == value
                 and value["limitations"] == [NON_CRYPTO_LIMITATION]
                 and value["credential_values_present"] is False
                 and value["cryptographic_remote_attestation"] is False,
                 "HOST_MATERIALIZE_RECEIPT_OUTPUT")
        return receipt
    if kind == "binding":
        _strict(value, {"version", "profile", "execution_id", "trace_id",
                        "dispatch_namespace", "artifact_root", "cache_root", "budget",
                        "binding_sha256"}, "HOST_MATERIALIZE_BINDING_OUTPUT")
        budget_row = _strict(
            value["budget"],
            {"search_items", "open_items", "provider_items", "concurrency",
             "call_timeout_seconds", "run_timeout_seconds"},
            "HOST_MATERIALIZE_BINDING_OUTPUT",
        )
        profile = _validate_generated("profile", value["profile"],
                                      workspace_root=workspace_root)
        unsigned = {key: item for key, item in value.items() if key != "binding_sha256"}
        _require(value["binding_sha256"] == hashlib.sha256(_canonical(unsigned)).hexdigest(),
                 "HOST_MATERIALIZE_BINDING_OUTPUT")
        try:
            parsed = HostExecutionBinding(
                profile=profile,
                execution_id=value["execution_id"],
                trace_id=value["trace_id"],
                dispatch_namespace=value["dispatch_namespace"],
                artifact_root=value["artifact_root"],
                cache_root=value["cache_root"],
                budget=HostBudget(**budget_row),
            )
            parsed.verify(workspace_root)
        except (KeyError, TypeError, ValueError, HostContractError) as error:
            raise MaterializeHostError("HOST_MATERIALIZE_BINDING_OUTPUT") from error
        _validate_mutable_root(workspace_root, parsed.artifact_root)
        _validate_mutable_root(workspace_root, parsed.cache_root)
        _require(parsed.to_public_dict() == value,
                 "HOST_MATERIALIZE_BINDING_OUTPUT")
        return parsed
    raise MaterializeHostError("HOST_MATERIALIZE_OUTPUT_KIND")

def _output_relative(relative_value: Any) -> Path:
    _require(isinstance(relative_value, str), "HOST_MATERIALIZE_OUTPUT_PATH")
    _reject_path_field(relative_value)
    relative = _relative(relative_value, "HOST_MATERIALIZE_OUTPUT_PATH")
    _require(relative.parts[0] in _ALLOWED_STATE_ROOTS,
             "HOST_MATERIALIZE_OUTPUT_PATH")
    return relative


def _bind_output_root(root: Path, relative: Path) -> tuple[
        int, list[tuple[int, tuple[int, ...]]], tuple[int, ...]]:
    directory_fds: list[tuple[int, tuple[int, ...]]] = []
    output_fd: int | None = None
    completed = False
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        root_signature = _directory_signature(
            os.fstat(root_fd), "HOST_MATERIALIZE_OUTPUT_PATH")
        directory_fds.append((root_fd, root_signature))
        current_fd = root_fd
        for part in relative.parts[:-1]:
            parent_before = _directory_signature(
                os.fstat(current_fd), "HOST_MATERIALIZE_OUTPUT_PATH")
            child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=current_fd)
            parent_after = _directory_signature(
                os.fstat(current_fd), "HOST_MATERIALIZE_OUTPUT_PATH")
            _require(parent_before == parent_after,
                     "HOST_MATERIALIZE_OUTPUT_PATH")
            child_signature = _directory_signature(
                os.fstat(child_fd), "HOST_MATERIALIZE_OUTPUT_PARENT")
            _require(stat.S_IMODE(os.fstat(child_fd).st_mode) == 0o700,
                     "HOST_MATERIALIZE_OUTPUT_PARENT")
            directory_fds.append((child_fd, child_signature))
            current_fd = child_fd

        parent_before = _directory_signature(
            os.fstat(current_fd), "HOST_MATERIALIZE_OUTPUT_PARENT")
        created = False
        try:
            output_fd = os.open(relative.parts[-1],
                                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=current_fd)
        except FileNotFoundError:
            os.mkdir(relative.parts[-1], 0o700, dir_fd=current_fd)
            created = True
            os.fsync(current_fd)
            output_fd = os.open(relative.parts[-1],
                                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=current_fd)
        parent_after = _directory_signature(
            os.fstat(current_fd), "HOST_MATERIALIZE_OUTPUT_PARENT")
        if created:
            directory_fds[-1] = (current_fd, parent_after)
        else:
            _require(parent_before == parent_after,
                     "HOST_MATERIALIZE_OUTPUT_PATH")
        info = os.fstat(output_fd)
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o700,
                 "HOST_MATERIALIZE_OUTPUT_INVALID")
        identity = (info.st_mode, info.st_uid, info.st_gid, info.st_dev,
                    info.st_ino)
        completed = True
        return output_fd, directory_fds, identity
    except MaterializeHostError:
        raise
    except OSError:
        raise MaterializeHostError("HOST_MATERIALIZE_OUTPUT_INVALID") from None
    finally:
        if not completed:
            if output_fd is not None:
                try:
                    os.close(output_fd)
                except OSError:
                    pass
            for directory_fd, _ in reversed(directory_fds):
                try:
                    os.close(directory_fd)
                except OSError:
                    pass


def _verify_bound_output(output_fd: int,
                         directory_fds: list[tuple[int, tuple[int, ...]]],
                         identity: tuple[int, ...]) -> None:
    for directory_fd, expected in directory_fds:
        _require(_directory_signature(os.fstat(directory_fd),
                                      "HOST_MATERIALIZE_OUTPUT_PATH") == expected,
                 "HOST_MATERIALIZE_OUTPUT_PATH")
    info = os.fstat(output_fd)
    actual = (info.st_mode, info.st_uid, info.st_gid, info.st_dev, info.st_ino)
    _require(actual == identity and stat.S_ISDIR(info.st_mode)
             and stat.S_IMODE(info.st_mode) == 0o700,
             "HOST_MATERIALIZE_OUTPUT_INVALID")


def _close_bound_output(output_fd: int | None,
                        directory_fds: list[tuple[int, tuple[int, ...]]]) -> bool:
    failed = False
    if output_fd is not None:
        try:
            os.close(output_fd)
        except OSError:
            failed = True
    for directory_fd, _ in reversed(directory_fds):
        try:
            os.close(directory_fd)
        except OSError:
            failed = True
    return failed

def _read_existing_at(directory_fd: int, name: str,
                      expected: bytes | None = None, *,
                      exact_mode: int = 0o600,
                      unknown_on_oserror: bool = False) -> bytes | None:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    except OSError:
        if unknown_on_oserror:
            raise _UnknownWriteOutcome from None
        raise MaterializeHostError("HOST_MATERIALIZE_OUTPUT_CONFLICT") from None
    try:
        before = os.fstat(descriptor)
        before_signature = _private_file_signature(
            before, max_size=MAX_OUTPUT, exact_mode=exact_mode,
            code="HOST_MATERIALIZE_OUTPUT_CONFLICT")
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            _require(bool(chunk), "HOST_MATERIALIZE_OUTPUT_CONFLICT")
            chunks.append(chunk); remaining -= len(chunk)
        after = os.fstat(descriptor)
        after_signature = _private_file_signature(
            after, max_size=MAX_OUTPUT, exact_mode=exact_mode,
            code="HOST_MATERIALIZE_OUTPUT_CONFLICT")
        _require(before_signature == after_signature,
                 "HOST_MATERIALIZE_OUTPUT_CONFLICT")
        payload = b"".join(chunks)
        if expected is not None:
            _require(payload == expected, "HOST_MATERIALIZE_OUTPUT_CONFLICT")
        return payload
    finally:
        os.close(descriptor)


def _owned_regular_mode(directory_fd: int, name: str, code: str) -> int:
    descriptor = None
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory_fd)
        info = os.fstat(descriptor)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                 and info.st_nlink == 1, code)
        return stat.S_IMODE(info.st_mode)
    except MaterializeHostError:
        raise
    except OSError:
        raise MaterializeHostError(code) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unlink_owned_regular(directory_fd: int, name: str, code: str, *,
                          exact_mode: int = 0o600) -> None:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory_fd)
        info = os.fstat(descriptor)
        os.close(descriptor)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                 and info.st_nlink == 1
                 and stat.S_IMODE(info.st_mode) == exact_mode, code)
        os.unlink(name, dir_fd=directory_fd)
    except MaterializeHostError:
        raise
    except OSError:
        raise MaterializeHostError(code) from None


def _remove_staging_at(directory_fd: int, name: str) -> None:
    code = "HOST_MATERIALIZE_ORPHAN_INVALID"
    staging_fd = None
    try:
        match = _STAGING_NAME.fullmatch(name)
        _require(match is not None, code)
        staging_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=directory_fd)
        info = os.fstat(staging_fd)
        mode = stat.S_IMODE(info.st_mode)
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                 and mode in (0o700, 0o500), code)
        children = os.listdir(staging_fd)
        if mode == 0o500:
            _require(set(children) == set(_BUNDLE_FILES), code)
            payloads = {
                child: _read_existing_at(staging_fd, child, exact_mode=0o400)
                for child in sorted(children)
            }
            _require(all(payload is not None for payload in payloads.values()), code)
            file_hashes = {
                child: hashlib.sha256(payloads[child]).hexdigest()
                for child in sorted(payloads)
            }
            generation_index = {"version": VERSION, "files": file_hashes}
            expected_digest = hashlib.sha256(_canonical(generation_index)).hexdigest()
            _require(expected_digest == match.group("digest"), code)
            os.fchmod(staging_fd, 0o700)
            for child in sorted(children):
                _unlink_owned_regular(staging_fd, child, code, exact_mode=0o400)
        else:
            _require(len(children) <= len(_BUNDLE_FILES) + 8, code)
            for child in children:
                _require(child in _BUNDLE_FILES
                         or _TEMP_NAME.fullmatch(child) is not None, code)
            modes = {child: _owned_regular_mode(staging_fd, child, code)
                     for child in children}
            member_names = {child for child in children if child in _BUNDLE_FILES}
            temp_names = set(children) - member_names
            if temp_names:
                _require(all(mode_value == 0o600 for mode_value in modes.values()), code)
            elif member_names == set(_BUNDLE_FILES):
                _require(all(mode_value in (0o400, 0o600)
                             for mode_value in modes.values()), code)
            elif member_names:
                _require(all(modes[child] in (0o400, 0o600)
                             for child in member_names), code)
            for child in children:
                _unlink_owned_regular(staging_fd, child, code,
                                      exact_mode=modes[child])
        os.fsync(staging_fd)
        os.close(staging_fd); staging_fd = None
        os.rmdir(name, dir_fd=directory_fd)
    except MaterializeHostError:
        raise
    except OSError:
        raise MaterializeHostError(code) from None
    finally:
        if staging_fd is not None:
            try:
                os.close(staging_fd)
            except OSError:
                pass

def _clean_owned_temps(directory_fd: int) -> None:
    names = os.listdir(directory_fd)
    staging = sorted(name for name in names if _STAGING_NAME.fullmatch(name))
    _require(len(staging) <= _MAX_ORPHAN_STAGING,
             "HOST_MATERIALIZE_ORPHAN_LIMIT")
    for name in names:
        if _TEMP_NAME.fullmatch(name):
            _unlink_owned_regular(directory_fd, name,
                                  "HOST_MATERIALIZE_ORPHAN_INVALID")
    for name in staging:
        _remove_staging_at(directory_fd, name)


def _publish_at(directory_fd: int, name: str, payload: bytes) -> bool:
    _require(0 < len(payload) <= MAX_OUTPUT, "HOST_MATERIALIZE_OUTPUT_LIMIT")
    if _read_existing_at(directory_fd, name, payload) is not None:
        return True
    digest = hashlib.sha256(payload).hexdigest()
    temporary = (f".{name}.{os.getpid()}.{digest[:16]}."
                 f"{secrets.token_hex(8)}.tmp")
    descriptor = None
    published = False
    reused = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            _require(written > 0, "HOST_MATERIALIZE_OUTPUT_WRITE")
            view = view[written:]
        os.fsync(descriptor); os.close(descriptor); descriptor = None
        try:
            os.link(temporary, name, src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd, follow_symlinks=False)
            published = True
        except FileExistsError:
            _read_existing_at(directory_fd, name, payload)
            reused = True
        os.unlink(temporary, dir_fd=directory_fd)
        os.fsync(directory_fd)
        return reused
    except _UnknownWriteOutcome:
        raise
    except MaterializeHostError:
        raise
    except OSError:
        if published:
            raise _UnknownWriteOutcome from None
        raise MaterializeHostError("HOST_MATERIALIZE_OUTPUT_WRITE") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass

def _verify_bundle_members(directory_fd: int,
                           payloads: Mapping[str, bytes], *,
                           exact_mode: int = 0o600) -> None:
    before = _directory_signature(os.fstat(directory_fd),
                                  "HOST_MATERIALIZE_GENERATION_INVALID")
    _require(set(os.listdir(directory_fd)) == set(payloads),
             "HOST_MATERIALIZE_BUNDLE_INCOMPLETE")
    for name, payload in sorted(payloads.items()):
        _require(_read_existing_at(directory_fd, name, payload, exact_mode=exact_mode) is not None,
                 "HOST_MATERIALIZE_BUNDLE_INCOMPLETE")
    after = _directory_signature(os.fstat(directory_fd),
                                 "HOST_MATERIALIZE_GENERATION_INVALID")
    _require(before == after, "HOST_MATERIALIZE_GENERATION_CHANGED")


def _verify_generation_at(directory_fd: int, name: str,
                          payloads: Mapping[str, bytes], *,
                          unknown_on_oserror: bool = False) -> None:
    generation_fd = None
    try:
        generation_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory_fd)
        info = os.fstat(generation_fd)
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o500,
                 "HOST_MATERIALIZE_GENERATION_INVALID")
        _verify_bundle_members(generation_fd, payloads, exact_mode=0o400)
    except MaterializeHostError:
        raise
    except OSError:
        if unknown_on_oserror:
            raise _UnknownWriteOutcome from None
        raise MaterializeHostError("HOST_MATERIALIZE_GENERATION_INVALID") from None
    finally:
        if generation_fd is not None:
            os.close(generation_fd)


def _preflight_output(directory_fd: int, generation_name: str,
                      head_payload: bytes, payloads: Mapping[str, bytes]) -> None:
    _clean_owned_temps(directory_fd)
    names = set(os.listdir(directory_fd))
    if _MANIFEST_NAME in names:
        _read_existing_at(directory_fd, _MANIFEST_NAME, head_payload)
        if generation_name not in names:
            candidates = names - {_LOCK_NAME, _MANIFEST_NAME}
            if len(candidates) == 1:
                candidate = next(iter(candidates))
                _verify_generation_at(directory_fd, candidate, payloads)
                try:
                    _rename_generation_noclobber(
                        directory_fd, candidate, generation_name)
                except FileExistsError:
                    _verify_generation_at(directory_fd, generation_name, payloads)
                    raise MaterializeHostError(
                        "HOST_MATERIALIZE_GENERATION_RENAME_COLLISION") from None
                try:
                    os.fsync(directory_fd)
                except OSError:
                    raise _UnknownWriteOutcome from None
                names.remove(candidate)
                names.add(generation_name)
            elif candidates:
                raise MaterializeHostError("HOST_MATERIALIZE_OUTPUT_NOT_EMPTY")
            else:
                _unlink_owned_regular(directory_fd, _MANIFEST_NAME,
                                      "HOST_MATERIALIZE_HEAD_RECOVERY")
                try:
                    os.fsync(directory_fd)
                except OSError:
                    raise _UnknownWriteOutcome from None
                names.remove(_MANIFEST_NAME)
    allowed = {_LOCK_NAME, _MANIFEST_NAME, generation_name}
    _require(names <= allowed, "HOST_MATERIALIZE_OUTPUT_NOT_EMPTY")
    if generation_name in names:
        _verify_generation_at(directory_fd, generation_name, payloads)

def _rename_generation_noclobber(directory_fd: int, source: str,
                                 destination: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        function = libc.renameatx_np
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                             ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(directory_fd, os.fsencode(source), directory_fd,
                          os.fsencode(destination), 0x00000004)  # RENAME_EXCL
    elif hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                             ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(directory_fd, os.fsencode(source), directory_fd,
                          os.fsencode(destination), 0x00000001)  # RENAME_NOREPLACE
    else:
        raise MaterializeHostError("HOST_MATERIALIZE_RENAME_NOCLOBBER_UNAVAILABLE")
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in (errno.EEXIST, errno.ENOTEMPTY):
        raise FileExistsError(error, os.strerror(error), destination)
    raise OSError(error, os.strerror(error), destination)


def _materialize_generation(directory_fd: int, generation_name: str,
                            payloads: Mapping[str, bytes]) -> bool:
    if generation_name in os.listdir(directory_fd):
        _verify_generation_at(directory_fd, generation_name, payloads)
        return True
    staging_name = (f".{generation_name}.{os.getpid()}."
                    f"{secrets.token_hex(8)}.tmp")
    staging_fd = None
    staging_exists = False
    generation_published = False
    try:
        os.mkdir(staging_name, 0o700, dir_fd=directory_fd)
        staging_exists = True
        staging_fd = os.open(staging_name,
                             os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=directory_fd)
        info = os.fstat(staging_fd)
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o700,
                 "HOST_MATERIALIZE_STAGING_INVALID")
        for name, payload in sorted(payloads.items()):
            _publish_at(staging_fd, name, payload)
        _verify_bundle_members(staging_fd, payloads)
        # Seal the completed generation before publishing its head.  Removing or
        # replacing a member now requires an explicit chmod by the owner rather
        # than succeeding as an ordinary concurrent write.
        for name in sorted(payloads):
            os.chmod(name, 0o400, dir_fd=staging_fd, follow_symlinks=False)
        os.fchmod(staging_fd, 0o500)
        _verify_bundle_members(staging_fd, payloads, exact_mode=0o400)
        os.fsync(staging_fd)
        os.close(staging_fd); staging_fd = None
        try:
            _rename_generation_noclobber(
                directory_fd, staging_name, generation_name)
            staging_exists = False
            generation_published = True
        except FileExistsError:
            if staging_name in os.listdir(directory_fd):
                _remove_staging_at(directory_fd, staging_name)
            staging_exists = False
            _verify_generation_at(directory_fd, generation_name, payloads)
            return True
        os.fsync(directory_fd)
        _verify_generation_at(directory_fd, generation_name, payloads,
                              unknown_on_oserror=True)
        return False
    except MaterializeHostError:
        raise
    except OSError:
        if generation_published:
            raise _UnknownWriteOutcome from None
        raise MaterializeHostError("HOST_MATERIALIZE_GENERATION_WRITE") from None
    finally:
        if staging_fd is not None:
            try:
                os.close(staging_fd)
            except OSError:
                pass
        if staging_exists:
            try:
                _remove_staging_at(directory_fd, staging_name)
            except MaterializeHostError:
                pass


def describe() -> dict[str, Any]:
    return {
        "version": VERSION,
        "commands": ["describe", "materialize"],
        "writes": [*_BUNDLE_FILES, _MANIFEST_NAME],
        "side_effects": [],
        "mcp": "not_used",
        "credential_values_read": False,
        "claim_limit": "Operational evidence only; no cryptographic remote attestation.",
    }


def _validate_binding_pair(bindings: Mapping[str, HostExecutionBinding],
                           root: Path) -> None:
    try:
        validate_execution_pair(bindings["codex"], bindings["claude"],
                                workspace_root=root)
    except HostContractError as error:
        raise MaterializeHostError(str(error)) from error
    codex = bindings["codex"].profile.credential
    claude = bindings["claude"].profile.credential
    _require(codex.owner_ref != claude.owner_ref
             and codex.profile_ref != claude.profile_ref
             and codex.fingerprint_sha256 is not None
             and claude.fingerprint_sha256 is not None
             and codex.fingerprint_sha256 != claude.fingerprint_sha256,
             "HOST_MATERIALIZE_CREDENTIAL_SHARED")


def _verify_workspace_ref_single_link(root: Path,
                                      reference: WorkspaceFileRef) -> None:
    try:
        path = reference.verify(root)
        info = path.stat()
    except (OSError, HostContractError):
        raise MaterializeHostError("HOST_MATERIALIZE_FILE_REF") from None
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
             "HOST_MATERIALIZE_FILE_REF_LINKED")


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _validate_output_isolation(output: Path, mutable_roots: list[Path]) -> None:
    _require(all(not _paths_overlap(output, mutable) for mutable in mutable_roots),
             "HOST_MATERIALIZE_OUTPUT_ROOT_OVERLAP")


def _acquire_lock(lock_fd: int, *, timeout_seconds: float = LOCK_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise MaterializeHostError("HOST_MATERIALIZE_LOCK_BUSY") from None
            time.sleep(min(LOCK_POLL_SECONDS, max(0.0, deadline - time.monotonic())))
        except OSError:
            raise MaterializeHostError("HOST_MATERIALIZE_LOCK_INVALID") from None


def _unknown_write_result(output_directory: Path, generation_name: str,
                          generation_sha256: str,
                          manifest_sha256: str) -> dict[str, Any]:
    return {
        "version": VERSION,
        "status": "unknown_write_outcome",
        "code": "HOST_MATERIALIZE_WRITE_OUTCOME_UNKNOWN",
        "output_directory": str(output_directory),
        "retry_permitted": False,
        "reconcile_before_retry": True,
        "unknown_outcome_fence": {
            "generation": generation_name,
            "generation_sha256": generation_sha256,
            "manifest": _MANIFEST_NAME,
            "manifest_sha256": manifest_sha256,
        },
    }


def materialize(value: dict[str, Any], *, workspace_root: Path = ROOT,
                now: datetime | None = None) -> dict[str, Any]:
    """Validate two isolated hosts and publish a sanitized immutable generation."""
    _reject_secrets(value)
    _strict(value, {"schema_version", "output_directory", "mcp", "hosts"},
            "HOST_MATERIALIZE_INPUT_SCHEMA")
    _require(value["schema_version"] == INPUT_VERSION and value["mcp"] == "not_used"
             and isinstance(value["hosts"], list) and len(value["hosts"]) == 2,
             "HOST_MATERIALIZE_INPUT_INVALID")
    hosts: dict[str, dict[str, Any]] = {}
    for row in value["hosts"]:
        _require(isinstance(row, dict), "HOST_MATERIALIZE_HOSTS_INVALID")
        host_value = row.get("host")
        _require(type(host_value) is str and host_value in {"codex", "claude"}
                 and host_value not in hosts,
                 "HOST_MATERIALIZE_HOSTS_INVALID")
        hosts[host_value] = row
    _require(set(hosts) == {"codex", "claude"},
             "HOST_MATERIALIZE_HOSTS_INVALID")
    try:
        root = Path(workspace_root).resolve(strict=True)
    except OSError:
        raise MaterializeHostError("HOST_MATERIALIZE_WORKSPACE_INVALID") from None
    output_relative = _output_relative(value["output_directory"])
    output_path = root.joinpath(output_relative)
    bindings: dict[str, HostExecutionBinding] = {}
    sessions: dict[str, str] = {}
    receipts: dict[str, CredentialReadinessReceipt] = {}
    mutable_roots: list[Path] = []
    for host in ("codex", "claude"):
        binding, session = _profile(host, hosts[host])
        try:
            binding.profile.verify(root)
        except HostContractError as error:
            raise MaterializeHostError("HOST_MATERIALIZE_PROFILE_INVALID") from error
        _verify_workspace_ref_single_link(root, binding.profile.runtime.interpreter_ref)
        _verify_workspace_ref_single_link(root, binding.profile.runtime.profile_ref)
        artifact = _validate_mutable_root(root, binding.artifact_root)
        cache = _validate_mutable_root(root, binding.cache_root)
        mutable_roots.extend((artifact, cache))
        bindings[host] = binding
        sessions[host] = session
    _validate_binding_pair(bindings, root)
    _validate_output_isolation(output_path, mutable_roots)
    _require(sessions["codex"] != sessions["claude"],
             "HOST_MATERIALIZE_SESSION_SHARED")
    now = now or datetime.now(timezone.utc)
    _require(now.tzinfo is not None and now.utcoffset() is not None,
             "HOST_MATERIALIZE_TIME_INVALID")
    for host in ("codex", "claude"):
        receipts[host] = _receipt(hosts[host]["observation"], bindings[host],
                                  sessions[host], now=now)
    payloads: dict[str, bytes] = {}
    generated_bindings: dict[str, HostExecutionBinding] = {}
    for host in ("codex", "claude"):
        values = {
            "profile": bindings[host].profile.to_public_dict(),
            "credential-readiness": receipts[host].to_public_dict(),
            "binding": bindings[host].to_public_dict(),
        }
        expected_values = {
            "profile": bindings[host].profile,
            "credential-readiness": receipts[host],
            "binding": bindings[host],
        }
        for suffix, public_value in values.items():
            parsed = _validate_generated(suffix, public_value, workspace_root=root)
            _require(parsed == expected_values[suffix],
                     f"HOST_MATERIALIZE_{suffix.upper().replace('-', '_')}_DRIFT")
            if suffix == "binding":
                generated_bindings[host] = parsed
            name = f"{host}-{suffix}.json"
            payload = _canonical(public_value) + b"\n"
            _require(len(payload) <= MAX_OUTPUT, "HOST_MATERIALIZE_OUTPUT_LIMIT")
            payloads[name] = payload
    _validate_binding_pair(generated_bindings, root)
    file_hashes = {name: hashlib.sha256(payload).hexdigest()
                   for name, payload in sorted(payloads.items())}
    generation_index = {"version": VERSION, "files": file_hashes}
    generation_sha256 = hashlib.sha256(_canonical(generation_index)).hexdigest()
    generation_name = f"generation-{generation_sha256}"
    manifest = {
        "kind": "host_profile_materialization_head",
        "version": VERSION,
        "mcp": "not_used",
        "generation": generation_name,
        "generation_sha256": generation_sha256,
        "files": file_hashes,
        "hosts": {host: {"ready_for_live": receipts[host].live_acceptance_eligible}
                  for host in ("codex", "claude")},
    }
    _reject_secrets(manifest)
    manifest_payload = _canonical(manifest) + b"\n"
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()

    directory_fd: int | None = None
    directory_fds: list[tuple[int, tuple[int, ...]]] = []
    output_identity: tuple[int, ...] | None = None
    lock_fd: int | None = None
    lock_acquired = False
    write_phase = False
    unknown = False
    reused: dict[str, bool] = {}
    generation_reused = False
    manifest_reused = False
    try:
        directory_fd, directory_fds, output_identity = _bind_output_root(
            root, output_relative)
        try:
            lock_fd = os.open(_LOCK_NAME, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                              0o600, dir_fd=directory_fd)
        except OSError:
            raise MaterializeHostError("HOST_MATERIALIZE_LOCK_INVALID") from None
        lock_info = os.fstat(lock_fd)
        _require(stat.S_ISREG(lock_info.st_mode)
                 and lock_info.st_uid == os.getuid()
                 and lock_info.st_nlink == 1
                 and stat.S_IMODE(lock_info.st_mode) == 0o600,
                 "HOST_MATERIALIZE_LOCK_INVALID")
        _acquire_lock(lock_fd)
        lock_acquired = True
        write_phase = True
        _preflight_output(directory_fd, generation_name, manifest_payload, payloads)
        generation_reused = _materialize_generation(
            directory_fd, generation_name, payloads)
        for name in payloads:
            reused[name] = generation_reused
        manifest_reused = _publish_at(directory_fd, _MANIFEST_NAME, manifest_payload)
        _verify_generation_at(directory_fd, generation_name, payloads,
                              unknown_on_oserror=True)
        _read_existing_at(directory_fd, _MANIFEST_NAME, manifest_payload,
                          unknown_on_oserror=True)
        try:
            os.fsync(directory_fd)
            _verify_bound_output(directory_fd, directory_fds, output_identity)
        except OSError:
            raise _UnknownWriteOutcome from None
    except _UnknownWriteOutcome:
        unknown = True
    finally:
        if lock_fd is not None:
            if lock_acquired:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    if write_phase:
                        unknown = True
            try:
                os.close(lock_fd)
            except OSError:
                if write_phase:
                    unknown = True
        if _close_bound_output(directory_fd, directory_fds) and write_phase:
            unknown = True
    if unknown:
        return _unknown_write_result(output_relative, generation_name,
                                     generation_sha256, manifest_sha256)

    result = {"version": VERSION, "output_directory": str(output_relative),
              "mcp": "not_used", "hosts": {}}
    for host in ("codex", "claude"):
        rows = {}
        for suffix in ("profile", "credential-readiness", "binding"):
            name = f"{host}-{suffix}.json"
            rows[suffix.replace("-", "_")] = {
                "path": str(output_relative / generation_name / name),
                "sha256": hashlib.sha256(payloads[name]).hexdigest(),
                "reused": reused[name],
            }
        rows["ready_for_live"] = receipts[host].live_acceptance_eligible
        result["hosts"][host] = rows
    result["generation"] = {
        "path": str(output_relative / generation_name),
        "sha256": generation_sha256,
        "reused": generation_reused,
    }
    result["manifest"] = {
        "path": str(output_relative / _MANIFEST_NAME),
        "sha256": manifest_sha256,
        "reused": manifest_reused,
    }
    result["bundle_sha256"] = manifest_sha256
    public = json.loads(_canonical(result))
    _reject_secrets(public)
    for host in ("codex", "claude"):
        row = public["hosts"][host]
        reopen_and_validate_materialized_bundle(
            root, head_ref=public["manifest"], profile_ref=row["profile"],
            credential_ref=row["credential_readiness"], binding_ref=row["binding"],
            host=host, now=now, require_live=False)
    return public

def _load_input(path: Path, *, workspace_root: Path = ROOT) -> dict[str, Any]:
    try:
        root = Path(workspace_root).resolve(strict=True)
    except OSError:
        raise MaterializeHostError("HOST_MATERIALIZE_INPUT_FILE") from None
    candidate = Path(path)
    try:
        relative = candidate.relative_to(root) if candidate.is_absolute() else candidate
    except ValueError:
        raise MaterializeHostError("HOST_MATERIALIZE_INPUT_FILE") from None
    _require(relative.parts and ".." not in relative.parts
             and all(part not in {"", "."} for part in relative.parts),
             "HOST_MATERIALIZE_INPUT_FILE")
    _reject_path_field(str(relative))

    directory_fds: list[tuple[int, tuple[int, ...]]] = []
    descriptor: int | None = None
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        root_signature = _directory_signature(
            os.fstat(root_fd), "HOST_MATERIALIZE_INPUT_FILE")
        directory_fds.append((root_fd, root_signature))
        current_fd = root_fd
        for part in relative.parts[:-1]:
            parent_before = _directory_signature(
                os.fstat(current_fd), "HOST_MATERIALIZE_INPUT_FILE")
            child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=current_fd)
            parent_after = _directory_signature(
                os.fstat(current_fd), "HOST_MATERIALIZE_INPUT_FILE")
            _require(parent_before == parent_after, "HOST_MATERIALIZE_INPUT_FILE")
            child_signature = _directory_signature(
                os.fstat(child_fd), "HOST_MATERIALIZE_INPUT_FILE")
            directory_fds.append((child_fd, child_signature))
            current_fd = child_fd

        parent_before = _directory_signature(
            os.fstat(current_fd), "HOST_MATERIALIZE_INPUT_FILE")
        descriptor = os.open(relative.parts[-1],
                             os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=current_fd)
        parent_after = _directory_signature(
            os.fstat(current_fd), "HOST_MATERIALIZE_INPUT_FILE")
        _require(parent_before == parent_after, "HOST_MATERIALIZE_INPUT_FILE")

        before = os.fstat(descriptor)
        before_signature = _private_file_signature(
            before, max_size=MAX_INPUT, exact_mode=None,
            code="HOST_MATERIALIZE_INPUT_FILE")
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            _require(bool(chunk), "HOST_MATERIALIZE_INPUT_FILE")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        after_signature = _private_file_signature(
            after, max_size=MAX_INPUT, exact_mode=None,
            code="HOST_MATERIALIZE_INPUT_FILE")
        _require(before_signature == after_signature,
                 "HOST_MATERIALIZE_INPUT_FILE")
        for directory_fd, expected in directory_fds:
            _require(_directory_signature(os.fstat(directory_fd),
                                          "HOST_MATERIALIZE_INPUT_FILE") == expected,
                     "HOST_MATERIALIZE_INPUT_FILE")
    except MaterializeHostError:
        raise
    except OSError:
        raise MaterializeHostError("HOST_MATERIALIZE_INPUT_FILE") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        for directory_fd, _ in reversed(directory_fds):
            try:
                os.close(directory_fd)
            except OSError:
                pass
    try:
        value = json.loads(b"".join(chunks), object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError,
            MaterializeHostError):
        raise MaterializeHostError("HOST_MATERIALIZE_INPUT_FILE") from None
    _require(isinstance(value, dict), "HOST_MATERIALIZE_INPUT_FILE")
    return value

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("describe", "materialize"))
    parser.add_argument("--input-file", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "describe":
            _require(args.input_file is None, "HOST_MATERIALIZE_ARGUMENTS")
            result = describe()
        else:
            _require(args.input_file is not None, "HOST_MATERIALIZE_ARGUMENTS")
            result = materialize(_load_input(args.input_file))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 3 if result.get("status") == "unknown_write_outcome" else 0
    except MaterializeHostError as error:
        print(json.dumps({"status": "blocked", "code": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
