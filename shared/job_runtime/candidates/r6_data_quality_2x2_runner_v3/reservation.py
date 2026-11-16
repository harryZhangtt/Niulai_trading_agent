"""Crash-safe execution-wide reservation for the disabled R6 runner-v3 successor."""
from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import stat
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.contracts import ContractError
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import strict_json_loads

_RESERVATION_DIRECTORY = ".r6-data-quality-runner-v3-reservations"
_LEASE_NS = 30_000_000_000
_MAX_EVENT_BYTES = 262_144
_MAX_RECOVERY_DEPTH = 64
_SHA = frozenset("0123456789abcdef")
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in _SHA for ch in value)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def _fsync(fd: int, code: str) -> None:
    try:
        os.fsync(fd)
    except OSError as exc:
        raise ContractError(code) from exc


def _open_owner_root(root: Path) -> tuple[int, str]:
    path = Path(root).absolute()
    try:
        before = os.lstat(path)
        fd = os.open(path, _DIR_FLAGS)
        after = os.fstat(fd)
    except OSError as exc:
        raise ContractError("RESERVATION_OWNER_ROOT_OPEN_FAILED") from exc
    if (
        not stat.S_ISDIR(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        or after.st_uid != os.getuid()
        or stat.S_IMODE(after.st_mode) != 0o700
    ):
        os.close(fd)
        raise ContractError("RESERVATION_OWNER_ROOT_UNSAFE")
    identity = _sha(_canonical({"device": after.st_dev, "inode": after.st_ino}))
    return fd, identity


def _open_reservation_directory(root_fd: int) -> int:
    created = False
    try:
        os.mkdir(_RESERVATION_DIRECTORY, 0o700, dir_fd=root_fd)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise ContractError("RESERVATION_DIRECTORY_CREATE_FAILED") from exc
    if created:
        _fsync(root_fd, "RESERVATION_OWNER_ROOT_FSYNC_FAILED")
    try:
        fd = os.open(_RESERVATION_DIRECTORY, _DIR_FLAGS, dir_fd=root_fd)
        meta = os.fstat(fd)
    except OSError as exc:
        raise ContractError("RESERVATION_DIRECTORY_OPEN_FAILED") from exc
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o700:
        os.close(fd)
        raise ContractError("RESERVATION_DIRECTORY_UNSAFE")
    return fd


def _read_event(directory_fd: int, name: str) -> tuple[bytes, Mapping[str, Any]]:
    fd = -1
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=directory_fd)
        meta = os.fstat(fd)
        _require(
            stat.S_ISREG(meta.st_mode)
            and meta.st_uid == os.getuid()
            and stat.S_IMODE(meta.st_mode) == 0o600
            and meta.st_nlink == 1,
            "RESERVATION_EVENT_UNSAFE",
        )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= _MAX_EVENT_BYTES, "RESERVATION_EVENT_TOO_LARGE")
            chunks.append(chunk)
    except FileNotFoundError:
        raise
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError("RESERVATION_EVENT_READ_FAILED") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    raw = b"".join(chunks)
    try:
        value = strict_json_loads(raw.decode("ascii"), "RESERVATION_EVENT_JSON")
    except Exception as exc:
        raise ContractError("RESERVATION_EVENT_JSON") from exc
    _require(type(value) is dict and _canonical(value) == raw, "RESERVATION_EVENT_NOT_CANONICAL")
    return raw, value


def _event_exists(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ContractError("RESERVATION_EVENT_STAT_FAILED") from exc


def _write_event(
    directory_fd: int,
    name: str,
    value: Mapping[str, Any],
    *,
    fault: Optional[str] = None,
) -> tuple[bytes, str]:
    raw = _canonical(value)
    fd = -1
    try:
        fd = os.open(name, _WRITE_FLAGS, 0o600, dir_fd=directory_fd)
        view = memoryview(raw)
        while view:
            width = len(view)
            if fault == "short_write":
                width = max(1, width // 2)
            count = os.write(fd, view[:width])
            if count <= 0:
                raise ContractError("RESERVATION_EVENT_SHORT_WRITE")
            view = view[count:]
            if fault == "short_write":
                _fsync(fd, "RESERVATION_EVENT_FSYNC_FAILED")
                raise ContractError("RESERVATION_INJECTED_SHORT_WRITE")
        _fsync(fd, "RESERVATION_EVENT_FSYNC_FAILED")
        meta = os.fstat(fd)
        _require(
            stat.S_ISREG(meta.st_mode)
            and meta.st_uid == os.getuid()
            and stat.S_IMODE(meta.st_mode) == 0o600
            and meta.st_nlink == 1,
            "RESERVATION_EVENT_UNSAFE",
        )
    except FileExistsError:
        raise
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError("RESERVATION_EVENT_WRITE_FAILED") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    _fsync(directory_fd, "RESERVATION_DIRECTORY_FSYNC_FAILED")
    reopened, _ = _read_event(directory_fd, name)
    _require(reopened == raw and _sha(reopened) == _sha(raw), "RESERVATION_EVENT_REOPEN_MISMATCH")
    return raw, _sha(raw)


def _current_boot_identity() -> str:
    """Read one authoritative boot identity; any read failure is indeterminate."""
    linux_root = Path("/proc")
    linux = linux_root / "sys/kernel/random/boot_id"
    if linux_root.is_dir():
        try:
            value = linux.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise ContractError("RESERVATION_BOOT_OBSERVATION_INDETERMINATE") from exc
        _require(bool(value), "RESERVATION_BOOT_OBSERVATION_INDETERMINATE")
        return _sha(value.encode("ascii"))
    try:
        result = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.boottime"],
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError("RESERVATION_BOOT_OBSERVATION_INDETERMINATE") from exc
    value = result.stdout.strip()
    _require(result.returncode == 0 and bool(value), "RESERVATION_BOOT_OBSERVATION_INDETERMINATE")
    return _sha(value)


def _confirm_pid_absent(pid: int) -> tuple[str, str]:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "DEAD_EXACT_PROOF", "PID_ABSENT_ESRCH"
    except PermissionError:
        return "INDETERMINATE", "PID_PERMISSION_DENIED"
    except OSError:
        return "INDETERMINATE", "PID_PROBE_ERROR"
    return "INDETERMINATE", "PID_EXISTS_TOKEN_UNAVAILABLE"


def _observe_process_start(pid: int, boot_id: str, expected_token: str) -> Mapping[str, Any]:
    if type(pid) is not int or pid <= 0 or not _is_sha(boot_id) or not _is_sha(expected_token):
        return {"outcome": "INDETERMINATE", "reason": "PROCESS_IDENTITY_INVALID", "observed_start_token": None}
    proc_root = Path("/proc")
    if proc_root.is_dir():
        proc = proc_root / str(pid) / "stat"
        try:
            raw = proc.read_text(encoding="ascii")
        except FileNotFoundError:
            outcome, reason = _confirm_pid_absent(pid)
            return {"outcome": outcome, "reason": reason, "observed_start_token": None}
        except PermissionError:
            return {"outcome": "INDETERMINATE", "reason": "PROC_PERMISSION_DENIED", "observed_start_token": None}
        except (OSError, UnicodeError):
            return {"outcome": "INDETERMINATE", "reason": "PROC_READ_ERROR", "observed_start_token": None}
        close = raw.rfind(")")
        fields = raw[close + 2 :].split() if close >= 0 else []
        if len(fields) <= 19 or not fields[19]:
            return {"outcome": "INDETERMINATE", "reason": "PROC_START_TOKEN_INCOMPLETE", "observed_start_token": None}
        observed = _sha(_canonical({"boot_id": boot_id, "pid": pid, "start": fields[19]}))
    else:
        try:
            result = subprocess.run(
                ["/bin/ps", "-p", str(pid), "-o", "lstart="],
                capture_output=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return {"outcome": "INDETERMINATE", "reason": "PS_OBSERVATION_ERROR", "observed_start_token": None}
        started = result.stdout.strip()
        if result.returncode != 0 or not started:
            outcome, reason = _confirm_pid_absent(pid)
            return {"outcome": outcome, "reason": reason, "observed_start_token": None}
        try:
            decoded = started.decode("utf-8", "strict")
        except UnicodeError:
            return {"outcome": "INDETERMINATE", "reason": "PS_START_TOKEN_INVALID", "observed_start_token": None}
        if not decoded.strip():
            return {"outcome": "INDETERMINATE", "reason": "PS_START_TOKEN_INCOMPLETE", "observed_start_token": None}
        observed = _sha(_canonical({"boot_id": boot_id, "pid": pid, "start": decoded}))
    return {
        "outcome": "LIVE" if observed == expected_token else "DEAD_EXACT_PROOF",
        "reason": "PROCESS_START_TOKEN_MATCH" if observed == expected_token else "PROCESS_START_TOKEN_MISMATCH",
        "observed_start_token": observed,
    }


def _observe_owner(owner: Mapping[str, Any]) -> Mapping[str, Any]:
    base = {
        "version": 1,
        "owner_process_identity": owner["process_identity"],
        "pid": owner["pid"],
        "expected_boot_id": owner["boot_id"],
        "expected_start_token": owner["process_start_token"],
        "observed_boot_id": None,
        "observed_start_token": None,
        "observed_monotonic_ns": time.monotonic_ns(),
    }
    try:
        observed_boot = _current_boot_identity()
    except ContractError:
        return {**base, "outcome": "INDETERMINATE", "boot_outcome": "INDETERMINATE", "process_outcome": "INDETERMINATE", "reason": "BOOT_OBSERVATION_ERROR"}
    base["observed_boot_id"] = observed_boot
    if observed_boot != owner["boot_id"]:
        return {**base, "outcome": "DEAD_EXACT_PROOF", "boot_outcome": "DEAD_EXACT_PROOF", "process_outcome": "DEAD_EXACT_PROOF", "reason": "BOOT_ID_MISMATCH"}
    process = _observe_process_start(owner["pid"], observed_boot, owner["process_start_token"])
    return {
        **base,
        "observed_start_token": process["observed_start_token"],
        "outcome": process["outcome"],
        "boot_outcome": "LIVE",
        "process_outcome": process["outcome"],
        "reason": process["reason"],
    }


def _validate_recovery_evidence(value: Any, owner: Mapping[str, Any]) -> Mapping[str, Any]:
    keys = {
        "version", "outcome", "boot_outcome", "process_outcome", "reason",
        "owner_process_identity", "pid", "expected_boot_id", "observed_boot_id",
        "expected_start_token", "observed_start_token", "observed_monotonic_ns",
    }
    _require(type(value) is dict and set(value) == keys, "RESERVATION_RECOVERY_EVIDENCE_SHAPE")
    outcomes = {"LIVE", "DEAD_EXACT_PROOF", "INDETERMINATE"}
    _require(value["outcome"] in outcomes and value["boot_outcome"] in outcomes and value["process_outcome"] in outcomes, "RESERVATION_RECOVERY_EVIDENCE_OUTCOME")
    _require(value["outcome"] == "DEAD_EXACT_PROOF", "RESERVATION_RECOVERY_NOT_EXACT_DEAD")
    _require(value["owner_process_identity"] == owner["process_identity"] and value["pid"] == owner["pid"], "RESERVATION_RECOVERY_OWNER_BINDING")
    _require(value["expected_boot_id"] == owner["boot_id"] and value["expected_start_token"] == owner["process_start_token"], "RESERVATION_RECOVERY_TOKEN_BINDING")
    _require(value["observed_boot_id"] is None or _is_sha(value["observed_boot_id"]), "RESERVATION_RECOVERY_BOOT_OBSERVATION")
    _require(value["observed_start_token"] is None or _is_sha(value["observed_start_token"]), "RESERVATION_RECOVERY_START_OBSERVATION")
    _require(type(value["reason"]) is str and bool(value["reason"]) and type(value["observed_monotonic_ns"]) is int, "RESERVATION_RECOVERY_EVIDENCE_VALUE")
    return value


def _new_owner() -> Mapping[str, Any]:
    boot_id = _current_boot_identity()
    pid = os.getpid()
    provisional = "0" * 64
    observed = _observe_process_start(pid, boot_id, provisional)
    _require(observed["observed_start_token"] is not None, "RESERVATION_PROCESS_IDENTITY_UNAVAILABLE")
    start_token = observed["observed_start_token"]
    core = {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "pid": pid,
        "boot_id": boot_id,
        "process_start_token": start_token,
        "nonce": secrets.token_hex(32),
    }
    return {**core, "process_identity": _sha(_canonical(core))}


def _validate_owner(value: Any) -> Mapping[str, Any]:
    keys = {"uid", "gid", "pid", "boot_id", "process_start_token", "nonce", "process_identity"}
    _require(type(value) is dict and set(value) == keys, "RESERVATION_OWNER_SHAPE")
    _require(value["uid"] == os.getuid() and type(value["gid"]) is int and type(value["pid"]) is int and value["pid"] > 0, "RESERVATION_OWNER_ID")
    for key in ("boot_id", "process_start_token", "process_identity"):
        _require(_is_sha(value[key]), "RESERVATION_OWNER_TOKEN")
    _require(type(value["nonce"]) is str and len(value["nonce"]) == 64 and all(ch in _SHA for ch in value["nonce"]), "RESERVATION_OWNER_NONCE")
    core = {key: value[key] for key in ("uid", "gid", "pid", "boot_id", "process_start_token", "nonce")}
    _require(value["process_identity"] == _sha(_canonical(core)), "RESERVATION_OWNER_HASH")
    return value


def _reservation_key(bindings: Mapping[str, Any]) -> str:
    """Derive the fixed execution identity without caller-selected destination data."""
    fixed = {
        key: bindings[key]
        for key in (
            "block_id",
            "grant_content_sha256",
            "input_identity_sha256",
            "map_content_sha256",
            "runner_owner_root_id",
            "source_identity_sha256",
            "fixture",
        )
    }
    return _sha(_canonical(fixed))

def _validate_bindings(value: Any) -> Mapping[str, Any]:
    keys = {
        "block_id",
        "grant_content_sha256",
        "input_identity_sha256",
        "map_content_sha256",
        "runner_owner_root_id",
        "source_identity_sha256",
        "authority_registry_ref_sha256",
        "map_commitment_ref_sha256",
        "p0_owner_root_ids",
        "destination_identity_sha256",
        "predecessor_runner_sha256",
        "predecessor_contracts_sha256",
        "grading_harness_sha256",
        "p0_v9_contract_sha256",
        "p0_v9_review_sha256",
        "runner_v8_open_review_sha256",
        "runner_v2_open_review_sha256",
        "fixture",
    }
    _require(type(value) is dict and set(value) == keys, "RESERVATION_BINDINGS_SHAPE")
    _require(type(value["block_id"]) is str and bool(value["block_id"]), "RESERVATION_BLOCK_ID")
    for key in (
        "grant_content_sha256",
        "input_identity_sha256",
        "map_content_sha256",
        "runner_owner_root_id",
        "source_identity_sha256",
        "authority_registry_ref_sha256",
        "map_commitment_ref_sha256",
        "destination_identity_sha256",
        "predecessor_runner_sha256",
        "predecessor_contracts_sha256",
        "grading_harness_sha256",
        "p0_v9_contract_sha256",
        "p0_v9_review_sha256",
        "runner_v8_open_review_sha256",
        "runner_v2_open_review_sha256",
    ):
        _require(_is_sha(value[key]), "RESERVATION_BINDING_SHA")
    _require(type(value["p0_owner_root_ids"]) is dict and set(value["p0_owner_root_ids"]) == {"ARM-A", "ARM-B"}, "RESERVATION_P0_ROOTS")
    _require(all(_is_sha(item) for item in value["p0_owner_root_ids"].values()), "RESERVATION_P0_ROOT_ID")
    _require(type(value["fixture"]) is bool, "RESERVATION_FIXTURE")
    return value


def _validate_claim(value: Any, bindings: Mapping[str, Any], key: str, predecessor: Optional[str]) -> Mapping[str, Any]:
    keys = {
        "version",
        "event",
        "reservation_key",
        "bindings",
        "owner",
        "created_monotonic_ns",
        "deadline_monotonic_ns",
        "predecessor_claim_sha256",
        "zero_effects_proof",
        "recovery_evidence",
        "immutable",
    }
    _require(type(value) is dict and set(value) == keys, "RESERVATION_CLAIM_SHAPE")
    _require(value["version"] == 1 and value["event"] in ("INITIAL_CLAIM", "RECOVERY_CLAIM") and value["immutable"] is True, "RESERVATION_CLAIM_VERSION")
    _require(value["reservation_key"] == key and value["bindings"] == bindings, "RESERVATION_CLAIM_BINDING")
    _validate_bindings(value["bindings"])
    _validate_owner(value["owner"])
    created, deadline = value["created_monotonic_ns"], value["deadline_monotonic_ns"]
    _require(type(created) is int and type(deadline) is int and deadline - created == _LEASE_NS, "RESERVATION_DEADLINE")
    _require(value["predecessor_claim_sha256"] == predecessor, "RESERVATION_PREDECESSOR")
    if predecessor is None:
        _require(value["event"] == "INITIAL_CLAIM" and value["zero_effects_proof"] is None and value["recovery_evidence"] is None, "RESERVATION_INITIAL_PROOF")
    else:
        _require(value["event"] == "RECOVERY_CLAIM" and type(value["zero_effects_proof"]) is dict, "RESERVATION_RECOVERY_PROOF")
    return value


def _state_event(
    event: str,
    key: str,
    claim_sha: str,
    process_identity: str,
    receipt_ref: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    value: dict[str, Any] = {
        "version": 1,
        "event": event,
        "reservation_key": key,
        "claim_sha256": claim_sha,
        "owner_process_identity": process_identity,
        "observed_monotonic_ns": time.monotonic_ns(),
        "receipt_ref": None if receipt_ref is None else dict(receipt_ref),
        "immutable": True,
    }
    return value


def _validate_state_event(value: Any, event: str, key: str, claim_sha: str, process_identity: str) -> Mapping[str, Any]:
    keys = {"version", "event", "reservation_key", "claim_sha256", "owner_process_identity", "observed_monotonic_ns", "receipt_ref", "immutable"}
    _require(type(value) is dict and set(value) == keys, "RESERVATION_STATE_SHAPE")
    _require(
        value["version"] == 1
        and value["event"] == event
        and value["reservation_key"] == key
        and value["claim_sha256"] == claim_sha
        and value["owner_process_identity"] == process_identity
        and type(value["observed_monotonic_ns"]) is int
        and value["immutable"] is True,
        "RESERVATION_STATE_BINDING",
    )
    if event == "COMPLETED":
        _require(type(value["receipt_ref"]) is dict, "RESERVATION_COMPLETION_RECEIPT")
    else:
        _require(value["receipt_ref"] is None, "RESERVATION_STATE_RECEIPT")
    return value


class ReservationHandle:
    """One admitted owner candidate backed by immutable reservation events."""

    def __init__(self, manager: "ReservationManager", claim: Mapping[str, Any], claim_sha: str):
        self._manager = manager
        self.claim = claim
        self.claim_sha256 = claim_sha

    @property
    def process_identity(self) -> str:
        return self.claim["owner"]["process_identity"]

    def admit(self) -> None:
        name = self._manager._state_name("admit", self.claim_sha256)
        value = _state_event("ADMITTED", self._manager.key, self.claim_sha256, self.process_identity)
        try:
            _write_event(self._manager.directory_fd, name, value)
        except FileExistsError:
            raw, existing = _read_event(self._manager.directory_fd, name)
            _validate_state_event(existing, "ADMITTED", self._manager.key, self.claim_sha256, self.process_identity)
            _require(_sha(raw) == _sha(_canonical(value)), "RESERVATION_ADMISSION_COLLISION")

    def mark_unknown(self) -> None:
        self._manager._publish_state("unknown", "UNKNOWN_NO_REPLAY", self, None)

    def mark_completed(self, receipt_ref: Mapping[str, Any]) -> None:
        self._manager._publish_state("complete", "COMPLETED", self, receipt_ref)


class ReservationManager:
    """Owns a fixed reservation namespace derived from the runner owner root."""

    def __init__(self, owner_root: Path, bindings: Mapping[str, Any]):
        self.bindings = dict(_validate_bindings(dict(bindings)))
        self.key = _reservation_key(self.bindings)
        self.root_fd, observed_root_id = _open_owner_root(owner_root)
        try:
            _require(observed_root_id == self.bindings["runner_owner_root_id"], "RESERVATION_OWNER_ROOT_BINDING")
            self.directory_fd = _open_reservation_directory(self.root_fd)
        except Exception:
            os.close(self.root_fd)
            raise

    def close(self) -> None:
        directory_fd = getattr(self, "directory_fd", -1)
        root_fd = getattr(self, "root_fd", -1)
        if directory_fd >= 0:
            os.close(directory_fd)
            self.directory_fd = -1
        if root_fd >= 0:
            os.close(root_fd)
            self.root_fd = -1

    def __enter__(self) -> "ReservationManager":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def _claim_name(self) -> str:
        return f"claim-{self.key}.json"

    def _recovery_name(self, predecessor_sha: str) -> str:
        return f"recover-{self.key}-{predecessor_sha}.json"

    def _state_name(self, prefix: str, claim_sha: str) -> str:
        return f"{prefix}-{self.key}-{claim_sha}.json"

    def _make_claim(
        self,
        predecessor: Optional[str],
        zero_effects_proof: Optional[Mapping[str, Any]],
        recovery_evidence: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        now = time.monotonic_ns()
        return {
            "version": 1,
            "event": "INITIAL_CLAIM" if predecessor is None else "RECOVERY_CLAIM",
            "reservation_key": self.key,
            "bindings": dict(self.bindings),
            "owner": dict(_new_owner()),
            "created_monotonic_ns": now,
            "deadline_monotonic_ns": now + _LEASE_NS,
            "predecessor_claim_sha256": predecessor,
            "zero_effects_proof": None if zero_effects_proof is None else dict(zero_effects_proof),
            "recovery_evidence": None if recovery_evidence is None else dict(recovery_evidence),
            "immutable": True,
        }

    def _read_chain(self) -> tuple[Mapping[str, Any], str]:
        raw, claim = _read_event(self.directory_fd, self._claim_name())
        claim_sha = _sha(raw)
        _validate_claim(claim, self.bindings, self.key, None)
        for _ in range(_MAX_RECOVERY_DEPTH):
            name = self._recovery_name(claim_sha)
            if not _event_exists(self.directory_fd, name):
                return claim, claim_sha
            raw, successor = _read_event(self.directory_fd, name)
            successor_sha = _sha(raw)
            _validate_claim(successor, self.bindings, self.key, claim_sha)
            _validate_recovery_evidence(successor["recovery_evidence"], claim["owner"])
            current = _observe_owner(claim["owner"])
            if current["outcome"] == "LIVE":
                raise ContractError("RESERVATION_FORGED_RECOVERY_OWNER_LIVE")
            if current["outcome"] != "DEAD_EXACT_PROOF":
                raise ContractError("RESERVATION_RECOVERY_LIVENESS_INDETERMINATE")
            claim, claim_sha = successor, successor_sha
        raise ContractError("RESERVATION_RECOVERY_DEPTH")

    def _has_state(self, prefix: str, event: str, handle: ReservationHandle) -> bool:
        name = self._state_name(prefix, handle.claim_sha256)
        if not _event_exists(self.directory_fd, name):
            return False
        _raw, value = _read_event(self.directory_fd, name)
        _validate_state_event(value, event, self.key, handle.claim_sha256, handle.process_identity)
        return True

    def _publish_state(self, prefix: str, event: str, handle: ReservationHandle, receipt_ref: Optional[Mapping[str, Any]]) -> None:
        name = self._state_name(prefix, handle.claim_sha256)
        value = _state_event(event, self.key, handle.claim_sha256, handle.process_identity, receipt_ref)
        try:
            _write_event(self.directory_fd, name, value)
        except FileExistsError:
            _raw, existing = _read_event(self.directory_fd, name)
            _validate_state_event(existing, event, self.key, handle.claim_sha256, handle.process_identity)
            if event == "COMPLETED":
                _require(existing["receipt_ref"] == dict(receipt_ref or {}), "RESERVATION_COMPLETION_COLLISION")

    def acquire(self, zero_effects: Callable[[], Mapping[str, Any]], *, fault: Optional[str] = None) -> tuple[ReservationHandle, bool]:
        initial = self._make_claim(None, None)
        try:
            raw, claim_sha = _write_event(
                self.directory_fd,
                self._claim_name(),
                initial,
                fault="short_write" if fault == "claim_short_write" else None,
            )
            _require(claim_sha == _sha(raw), "RESERVATION_CLAIM_HASH")
            return ReservationHandle(self, initial, claim_sha), True
        except FileExistsError:
            pass

        for _ in range(3):
            claim, claim_sha = self._read_chain()
            handle = ReservationHandle(self, claim, claim_sha)
            if self._has_state("complete", "COMPLETED", handle):
                return handle, False
            if self._has_state("admit", "ADMITTED", handle):
                if self._has_state("unknown", "UNKNOWN_NO_REPLAY", handle):
                    raise ContractError("RESERVATION_DURABLE_UNKNOWN_NO_REPLAY")
                return handle, False
            observation = _observe_owner(claim["owner"])
            if observation["outcome"] == "LIVE":
                raise ContractError("RESERVATION_OWNER_ACTIVE_NO_TAKEOVER")
            if observation["outcome"] != "DEAD_EXACT_PROOF":
                raise ContractError("RESERVATION_OWNER_LIVENESS_INDETERMINATE_NO_TAKEOVER")
            proof = dict(zero_effects())
            required = {"zero_effects", "admission_absent", "receipt_absent", "destinations_absent", "program_order_proof"}
            _require(set(proof) == required and all(proof[key] is True for key in required), "RESERVATION_ZERO_EFFECTS_NOT_PROVEN")
            successor = self._make_claim(claim_sha, proof, observation)
            try:
                raw, successor_sha = _write_event(self.directory_fd, self._recovery_name(claim_sha), successor)
                _require(successor_sha == _sha(raw), "RESERVATION_RECOVERY_HASH")
                return ReservationHandle(self, successor, successor_sha), True
            except FileExistsError:
                continue
        raise ContractError("RESERVATION_RECOVERY_RACE")

    def admitted(self, handle: ReservationHandle) -> bool:
        return self._has_state("admit", "ADMITTED", handle)

    def completed(self, handle: ReservationHandle) -> bool:
        return self._has_state("complete", "COMPLETED", handle)

    def mark_unknown(self, handle: ReservationHandle) -> None:
        handle.mark_unknown()

    def mark_completed(self, handle: ReservationHandle, receipt_ref: Mapping[str, Any]) -> None:
        handle.mark_completed(receipt_ref)


__all__ = ["ReservationHandle", "ReservationManager"]
