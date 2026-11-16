"""Private provider-free one-shot engine; public entrypoints remain hard-disabled."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple

from . import constants as C
from .contracts import (
    AmbiguousOutcome, ContractError, canonical_bytes, iso_utc, parse_auth_status,
    parse_catalog_stream, sha256_bytes, strict_json, validate_clean_auth_evidence,
)
from .custody import (
    AtomicWriteError, _create_transient, _destroy_transient,
    _open_owner_private_root, _publish_bundle, _publish_one, _read_transient, _write_all,
)


class LocalPreflightError(RuntimeError):
    """A local contract failed before a provider-facing process."""


class PreviousOutcomeUnknown(RuntimeError):
    """A one-shot operation already started; replay is forbidden."""


@dataclass(frozen=True)
class _BinaryPin:
    path: Path
    size: int
    sha256: str
    mode: int
    uid: int


@dataclass(frozen=True)
class _HeldBinary:
    path: Path
    name: str
    device: int
    inode: int
    sha256: str
    size: int
    uid: int


@dataclass(frozen=True)
class _PinnedSource:
    path: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class _ProcessOutcome:
    returncode: Optional[int]
    timed_out: bool
    binary_stable: bool


Runner = Callable[[Sequence[str], _HeldBinary, int, int, int, Mapping[str, str]], _ProcessOutcome]
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class _Runtime:
    binary: _BinaryPin
    auth_argv: Tuple[str, ...]
    catalog_argv: Tuple[str, ...]
    auth_root: Path
    auth_review_root: Path
    catalog_root: Path
    now: Clock
    runner: Runner
    env: Mapping[str, str]


_AUTHORITY_DIR = C.WORKSPACE / "shared/job_runtime/tests/candidates/r6_claude_metadata_preflight_v1/fixtures/authority"
_REGISTRY = _PinnedSource(_AUTHORITY_DIR / "registry.json", 948, "c42c69eacdd3fa0a75afeccd00ae36e4514386299de13b1d5ed149e447be1818")
_AUTHORITY_REFS = {
    "auth_grant": _PinnedSource(_AUTHORITY_DIR / "auth-grant.json", 189, "a2f221fffbb2715e495d992b457d16e2138ce15510b02fbe9c2add9c0f80da51"),
    "auth_grant_review": _PinnedSource(_AUTHORITY_DIR / "auth-grant-review.json", 245, "bde6793f0b3ccc3d92af13cb2162fa16945e015bd42305b0eae39b0f4acceb1e"),
    "catalog_grant": _PinnedSource(_AUTHORITY_DIR / "catalog-grant.json", 194, "919a0dedc7cf605eca79d6b16e1be54b177223ccee3a2d34f4744ea47be47c31"),
    "catalog_grant_review": _PinnedSource(_AUTHORITY_DIR / "catalog-grant-review.json", 248, "b800ce65f86697a3f3b350268dbebef24d2f8c1f9ab3bbf278f97300dbf8ccba"),
    "claude_v8_review": _PinnedSource(_AUTHORITY_DIR / "claude-v8-review.json", 160, "6e727faf820b489dd2d92458ed8e30411cd7a1902f713fed51b52e9c070b8e0e"),
    "p0_v10": _PinnedSource(_AUTHORITY_DIR / "p0-v10.json", 150, "68f21604d1c96a3bc67e1999a402e4fb5de8613bd54b902291d174966a47ec12"),
}


def _read_fd(fd: int, limit: int = C.MAX_OUTPUT_BYTES) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET); chunks = []; total = 0
    while True:
        part = os.read(fd, min(65536, limit + 1 - total))
        if not part: break
        chunks.append(part); total += len(part)
        if total > limit: raise LocalPreflightError("HELD_FILE_TOO_LARGE")
    return b"".join(chunks)


def _file_identity(path: Path) -> Tuple[int, str]:
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise LocalPreflightError("HELD_FILE_NOT_REGULAR")
        raw = _read_fd(fd, 512 * 1024 * 1024)
    finally: os.close(fd)
    return len(raw), sha256_bytes(raw)


def _verify_ref(ref: Tuple[str, int, str]) -> None:
    observed = _file_identity(C.WORKSPACE / ref[0])
    if observed != (ref[1], ref[2]): raise LocalPreflightError("PINNED_SOURCE_IDENTITY_DRIFT")


def _verify_static_bindings() -> None:
    for ref in (
        C.DECISION_REF, C.PROTOCOL_REF, C.HISTORICAL_MEMBERSHIP_REF,
        C.HISTORICAL_MEMBERSHIP_REVIEW_REF, C.BINARY_IDENTITY_REF,
        C.BINARY_REVIEW_REF, C.DRIVER_DESIGN_REF, C.DRIVER_REVIEW_REF,
        C.ADAPTER_CONTRACT_REF, C.PROVIDER_CONTRACT_REF,
        C.CATALOG_PARSER_REF, C.CATALOG_PARSER_REVIEW_REF,
        C.CURRENT_V8_OPEN_REVIEW_REF,
    ): _verify_ref(ref)


def _read_pinned(source: _PinnedSource) -> dict:
    fd = os.open(str(source.path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        info = os.fstat(fd); raw = _read_fd(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                stat.S_IMODE(info.st_mode) != 0o600 or len(raw) != source.size or
                sha256_bytes(raw) != source.sha256):
            raise LocalPreflightError("TEST_AUTHORITY_IDENTITY_DRIFT")
    finally: os.close(fd)
    value = strict_json(raw)
    if type(value) is not dict or canonical_bytes(value) != raw:
        raise LocalPreflightError("TEST_AUTHORITY_NOT_CANONICAL")
    return value


def _verify_test_authority() -> str:
    registry = _read_pinned(_REGISTRY)
    expected_refs = {name: {"path": source.path.name, "bytes": source.size, "sha256": source.sha256}
                     for name, source in _AUTHORITY_REFS.items()}
    if registry != {"version": 1, "kind": "SYNTHETIC_PROVIDER_FREE_AUTHORITY_REGISTRY",
                    "status": "FIXTURE_ONLY_NO_LIVE_AUTHORITY", "activation": False,
                    "refs": expected_refs}:
        raise LocalPreflightError("TEST_AUTHORITY_REGISTRY_DRIFT")
    values = {name: _read_pinned(source) for name, source in _AUTHORITY_REFS.items()}
    for operation in ("auth", "catalog"):
        grant = values[operation + "_grant"]
        expected_grant = {"version": 1, "kind": "SYNTHETIC_" + operation.upper() + "_GRANT",
                          "issuer": "provider-free-fixture-owner",
                          "operation": "auth_status" if operation == "auth" else "model_catalog",
                          "model": C.MODEL, "max_requests": 1, "inference": 0,
                          "live_authority": False}
        if grant != expected_grant: raise LocalPreflightError("TEST_GRANT_DRIFT")
        review = values[operation + "_grant_review"]
        expected_review = {"version": 1, "kind": "SYNTHETIC_" + operation.upper() + "_GRANT_REVIEW",
                           "reviewer": "independent-provider-free-fixture-reviewer",
                           "verdict": "CLEAN_FIXTURE_ONLY",
                           "subject_sha256": _AUTHORITY_REFS[operation + "_grant"].sha256,
                           "live_authority": False}
        if review != expected_review: raise LocalPreflightError("TEST_GRANT_REVIEW_DRIFT")
    for name, kind in (("claude_v8_review", "SYNTHETIC_CLAUDE_V8_REVIEW"),
                       ("p0_v10", "SYNTHETIC_P0_V10")):
        if values[name] != {"version": 1, "kind": kind,
                            "reviewer": "independent-provider-free-fixture-reviewer",
                            "verdict": "CLEAN_FIXTURE_ONLY", "live_authority": False}:
            raise LocalPreflightError("TEST_CLEAN_FIXTURE_DRIFT")
    return _REGISTRY.sha256


def _read_verified_binary(pin: _BinaryPin) -> bytes:
    fd = os.open(str(pin.path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                info.st_uid != pin.uid or stat.S_IMODE(info.st_mode) != pin.mode):
            raise LocalPreflightError("BINARY_DESCRIPTOR_DRIFT")
        raw = _read_fd(fd, max(pin.size, 1) + 1)
        if len(raw) != pin.size or sha256_bytes(raw) != pin.sha256:
            raise LocalPreflightError("BINARY_BYTES_DRIFT")
        return raw
    finally:
        os.close(fd)


def _check_held_binary(held: _HeldBinary) -> None:
    fd = os.open(str(held.path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd); raw = _read_fd(fd, held.size + 1)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                info.st_dev != held.device or info.st_ino != held.inode or
                info.st_uid != held.uid or stat.S_IMODE(info.st_mode) != 0o700 or
                len(raw) != held.size or sha256_bytes(raw) != held.sha256):
            raise LocalPreflightError("HELD_BINARY_DRIFT")
    finally:
        os.close(fd)


def _materialize_held_binary(root: Path, raw: bytes, pin: _BinaryPin) -> _HeldBinary:
    if len(raw) != pin.size or sha256_bytes(raw) != pin.sha256:
        raise LocalPreflightError("HELD_BINARY_SOURCE_DRIFT")
    name = "held-binary-" + pin.sha256[:16]
    root_fd = _open_owner_private_root(str(root))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, 0o700, dir_fd=root_fd)
        complete = False
        try:
            _write_all(fd, raw); os.fsync(fd); complete = True
        finally:
            os.close(fd)
            if not complete:
                try: os.unlink(name, dir_fd=root_fd); os.fsync(root_fd)
                except OSError: pass
        os.fsync(root_fd)
        read_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
        try:
            info = os.fstat(read_fd); observed = _read_fd(read_fd, pin.size + 1)
        finally:
            os.close(read_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                info.st_uid != pin.uid or stat.S_IMODE(info.st_mode) != 0o700 or
                len(observed) != pin.size or sha256_bytes(observed) != pin.sha256):
            raise LocalPreflightError("HELD_BINARY_PUBLICATION_DRIFT")
        return _HeldBinary(root / name, name, info.st_dev, info.st_ino, pin.sha256, pin.size, pin.uid)
    finally:
        os.close(root_fd)


def _destroy_held_binary(root: Path, held: _HeldBinary) -> None:
    _check_held_binary(held)
    root_fd = _open_owner_private_root(str(root))
    try:
        os.unlink(held.name, dir_fd=root_fd); os.fsync(root_fd)
    finally:
        os.close(root_fd)

def _validate_runtime(runtime: _Runtime) -> str:
    _verify_static_bindings(); authority_sha = _verify_test_authority()
    if runtime.auth_argv != (str(runtime.binary.path),) + C.AUTH_ARGV[1:]: raise LocalPreflightError("AUTH_ARGV_DRIFT")
    if runtime.catalog_argv != (str(runtime.binary.path),) + C.CATALOG_ARGV[1:]: raise LocalPreflightError("CATALOG_ARGV_DRIFT")
    now = runtime.now()
    if now.tzinfo is None or now.utcoffset() != timedelta(0): raise LocalPreflightError("CLOCK_NOT_UTC")
    for root in (runtime.auth_root, runtime.auth_review_root, runtime.catalog_root):
        fd = _open_owner_private_root(str(root)); os.close(fd)
    return authority_sha


def _subprocess_runner(argv: Sequence[str], held: _HeldBinary, stdout_fd: int, stderr_fd: int,
                       timeout: int, env: Mapping[str, str]) -> _ProcessOutcome:
    proc = subprocess.Popen(tuple(argv), executable=str(held.path), stdin=subprocess.DEVNULL,
                            stdout=stdout_fd, stderr=stderr_fd, shell=False, close_fds=True,
                            start_new_session=True, env=dict(env))
    try:
        _check_held_binary(held)
    except LocalPreflightError:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        proc.wait(); return _ProcessOutcome(None, False, False)
    try: return _ProcessOutcome(proc.wait(timeout=timeout), False, True)
    except subprocess.TimeoutExpired:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        proc.wait(); return _ProcessOutcome(None, True, True)

def _claim_start(root: Path, operation: str, authority_sha256: str) -> None:
    fd = _open_owner_private_root(str(root))
    try:
        if "commit.json" in os.listdir(fd) or "started.json" in os.listdir(fd):
            raise PreviousOutcomeUnknown("SECOND_EXECUTION_REPLAY_FORBIDDEN")
        _publish_one(fd, "started.json", canonical_bytes({"authority_sha256": authority_sha256,
            "operation": operation, "request_accounting": {"attempts_reserved": 1,
            "retries": 0, "replays": 0, "status_after_unknown": 0, "second_request": 0}}))
    finally: os.close(fd)


def _capture(runtime: _Runtime, root: Path, argv: Sequence[str], timeout: int,
             held: _HeldBinary) -> Tuple[_ProcessOutcome, bytes, bytes]:
    resources = []
    outcome = _ProcessOutcome(None, False, False); stdout = stderr = b""
    active_error: Optional[BaseException] = None
    try:
        stdout_root, stdout_fd = _create_transient(str(root), "stdout.transient")
        resources.append((stdout_root, stdout_fd, "stdout.transient"))
        stderr_root, stderr_fd = _create_transient(str(root), "stderr.transient")
        resources.append((stderr_root, stderr_fd, "stderr.transient"))
        try: outcome = runtime.runner(argv, held, stdout_fd, stderr_fd, timeout, runtime.env)
        except BaseException: outcome = _ProcessOutcome(None, False, False)
        try: _check_held_binary(held)
        except LocalPreflightError: outcome = _ProcessOutcome(None, outcome.timed_out, False)
        stdout = _read_transient(stdout_fd, C.MAX_OUTPUT_BYTES)
        stderr = _read_transient(stderr_fd, C.MAX_OUTPUT_BYTES)
    except BaseException as exc:
        active_error = exc
    cleanup_errors = []
    for root_fd, file_fd, name in resources:
        try: _destroy_transient(root_fd, file_fd, name)
        except BaseException as exc: cleanup_errors.append(exc)
    try: _destroy_held_binary(root, held)
    except BaseException as exc: cleanup_errors.append(exc)
    if active_error is not None: raise active_error
    if cleanup_errors: raise AtomicWriteError("TRANSIENT_OR_HELD_CLEANUP_FAILED") from cleanup_errors[0]
    return outcome, stdout, stderr

def _raw_payload(outcome: _ProcessOutcome, stdout: bytes, stderr: bytes) -> bytes:
    return canonical_bytes({"returncode": outcome.returncode,
        "stderr_base64": base64.b64encode(stderr).decode("ascii"),
        "stdout_base64": base64.b64encode(stdout).decode("ascii"),
        "timed_out": outcome.timed_out, "binary_stable": outcome.binary_stable})


def _receipt(operation: str, status: str, checked: datetime, binary_sha: str,
             argv: Sequence[str], authority_sha: str, stdout: bytes, stderr: bytes,
             auth_reads: int, catalog_requests: int) -> dict:
    fresh_until = checked + timedelta(seconds=C.FRESHNESS_SECONDS) if status in ("READY", "NOT_READY") else checked
    return {"version": 1, "operation": operation, "status": status, "model": C.MODEL,
        "checked_at": iso_utc(checked), "fresh_until": iso_utc(fresh_until),
        "binary_sha256": binary_sha, "argv_sha256": sha256_bytes(canonical_bytes(list(argv))),
        "authority_sha256": authority_sha,
        "raw": {"owner_private": True, "raw_public": False,
            "stdout_bytes": len(stdout), "stdout_sha256": sha256_bytes(stdout),
            "stderr_bytes": len(stderr), "stderr_sha256": sha256_bytes(stderr)},
        "request_accounting": {"auth_status_reads": auth_reads,
            "catalog_requests": catalog_requests, "inference": 0, "attempts": 1,
            "retries": 0, "replays": 0, "status_after_unknown": 0,
            "second_request": 0, "concurrency": 1},
        "unknown_fence": {"durable": status == "UNKNOWN", "retry": False,
            "replay": False, "status_after_unknown": 0, "second_request": False}}


def _publish(root: Path, operation: str, status: str, receipt: dict, raw: bytes, authority_sha: str) -> None:
    _publish_bundle(str(root), {"raw.json": raw, "receipt.json": canonical_bytes(receipt)},
        {"version": 1, "operation": operation, "status": status,
         "authority_sha256": authority_sha, "commit_marker_last": True})


def _run_auth_for_test(runtime: _Runtime) -> dict:
    authority_sha = _validate_runtime(runtime); binary_raw = _read_verified_binary(runtime.binary)
    _claim_start(runtime.auth_root, "auth_status", authority_sha)
    held = _materialize_held_binary(runtime.auth_root, binary_raw, runtime.binary)
    outcome, stdout, stderr = _capture(runtime, runtime.auth_root, runtime.auth_argv,
                                       C.AUTH_TIMEOUT_SECONDS, held)
    checked = runtime.now()
    if outcome.timed_out or outcome.returncode != 0 or not outcome.binary_stable: status = "UNKNOWN"
    else:
        try: status = "READY" if parse_auth_status(stdout) else "NOT_READY"
        except ContractError: status = "UNKNOWN"
    receipt = _receipt("auth_status", status, checked, runtime.binary.sha256,
        runtime.auth_argv, authority_sha, stdout, stderr, 1, 0)
    _publish(runtime.auth_root, "auth_status", status, receipt, _raw_payload(outcome, stdout, stderr), authority_sha)
    return receipt


def _read_committed(root: Path, name: str) -> dict:
    root_fd = _open_owner_private_root(str(root))
    try:
        commit_fd = os.open("commit.json", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
        value_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
        try: commit_raw = _read_fd(commit_fd); raw = _read_fd(value_fd)
        finally: os.close(commit_fd); os.close(value_fd)
    finally: os.close(root_fd)
    commit = strict_json(commit_raw)
    if (type(commit) is not dict or commit.get("commit_marker_last") is not True or
            commit.get("files", {}).get(name, {}).get("sha256") != sha256_bytes(raw)):
        raise LocalPreflightError("COMMIT_BINDING")
    value = strict_json(raw)
    if type(value) is not dict: raise LocalPreflightError("COMMITTED_VALUE_SHAPE")
    return value


def _install_clean_test_review(runtime: _Runtime) -> dict:
    receipt = _read_committed(runtime.auth_root, "receipt.json")
    review = {"version": 1, "kind": "SYNTHETIC_AUTH_RECEIPT_REVIEW",
        "reviewer": "independent-provider-free-fixture-reviewer",
        "verdict": "CLEAN_FIXTURE_ONLY", "receipt_sha256": sha256_bytes(canonical_bytes(receipt)),
        "live_authority": False}
    _publish_bundle(str(runtime.auth_review_root), {"review.json": canonical_bytes(review)},
        {"version": 1, "operation": "auth_receipt_review", "status": "CLEAN_FIXTURE_ONLY",
         "authority_sha256": _REGISTRY.sha256, "commit_marker_last": True})
    return review


def _run_catalog_for_test(runtime: _Runtime) -> dict:
    authority_sha = _validate_runtime(runtime)
    auth_receipt = _read_committed(runtime.auth_root, "receipt.json")
    auth_review = _read_committed(runtime.auth_review_root, "review.json")
    validate_clean_auth_evidence(auth_receipt, auth_review, runtime.now())
    binary_raw = _read_verified_binary(runtime.binary)
    _claim_start(runtime.catalog_root, "model_catalog", authority_sha)
    held = _materialize_held_binary(runtime.catalog_root, binary_raw, runtime.binary)
    outcome, stdout, stderr = _capture(runtime, runtime.catalog_root, runtime.catalog_argv,
                                       C.CATALOG_TIMEOUT_SECONDS, held)
    checked = runtime.now(); terminal_index = None
    if outcome.timed_out or outcome.returncode != 0 or not outcome.binary_stable: status = "UNKNOWN"
    else:
        try:
            member, terminal_index = parse_catalog_stream(stdout)
            status = "READY" if member else "NOT_READY"
        except (ContractError, AmbiguousOutcome): status = "UNKNOWN"
    receipt = _receipt("model_catalog", status, checked, runtime.binary.sha256,
        runtime.catalog_argv, authority_sha, stdout, stderr, 0, 1)
    receipt["catalog_terminal"] = {"authority": "sole_terminal_result",
        "terminal_result_index": terminal_index, "display_model": C.DISPLAY_MODEL,
        "assistant_stream_ignored": True}
    _publish(runtime.catalog_root, "model_catalog", status, receipt,
             _raw_payload(outcome, stdout, stderr), authority_sha)
    return receipt


def _runtime_for_test(binary: Path, auth_root: Path, auth_review_root: Path,
                      catalog_root: Path, now: Clock, *, scenario: str = "ready",
                      binary_sha_override: Optional[str] = None) -> _Runtime:
    size, digest = _file_identity(binary); info = os.lstat(binary)
    return _Runtime(_BinaryPin(binary, size, binary_sha_override or digest,
        stat.S_IMODE(info.st_mode), info.st_uid),
        (str(binary),) + C.AUTH_ARGV[1:], (str(binary),) + C.CATALOG_ARGV[1:],
        auth_root, auth_review_root, catalog_root, now, _subprocess_runner,
        {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "R6_FAKE_SCENARIO": scenario})
