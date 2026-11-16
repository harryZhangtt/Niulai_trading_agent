"""Disabled additive R6 runner-v4 with child-isolated reservation authority."""
from __future__ import annotations

STATUS = "P0_V10_RECLOSURE_REQUIRED"


def _build_private_runtime():
    import copy
    import hashlib
    import hmac
    import json
    import os
    import secrets
    import signal
    import stat
    import subprocess
    import sys
    import time
    from pathlib import Path
    from typing import Any, Callable, Mapping, Optional

    repo_root = Path(__file__).resolve().parents[4]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v3 import harness as grading_module
    from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1 import runner as predecessor_module
    from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1 import contracts as contracts_module
    from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.contracts import ContractError
    from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import strict_json_loads
    from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.adapters import claude_adapter, codex_adapter

    _RESERVATION_DIRECTORY = ".r6-data-quality-runner-v4-reservations"
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
            "runner_v3_open_review_sha256",
            "runner_v4_source_sha256",
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
            "runner_v3_open_review_sha256",
            "runner_v4_source_sha256",
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

    source_file = Path(__file__).resolve()
    import_source = source_file.read_bytes()
    import_source_pin = (len(import_source), hashlib.sha256(import_source).hexdigest())
    sha256_constructor = hashlib.sha256
    json_dumps = json.dumps
    cell_order = ("R6DQ-7F2C91A4", "R6DQ-1B8E43D7", "R6DQ-C4A7095E", "R6DQ-92D6F0B3")
    frozen_input_sha = "6238b65ef5734d74a06e1747f2125e75a82cdf43f6ca1ba248be4693d007d885"
    specs = (
        ("predecessor_runner", "shared/job_runtime/candidates/r6_data_quality_2x2_runner_v1/runner.py", 39451, "bc45fceff79a1106ef66c09376075f3bb72a235ac4a23ca69b7344f914ff0bff"),
        ("predecessor_contracts", "shared/job_runtime/candidates/r6_data_quality_2x2_runner_v1/contracts.py", 14745, "9f0bc41282461e64ca795cb64365e84341c029e11760efbfc68dc29d72846be7"),
        ("grading_harness", "shared/job_runtime/candidates/r6_data_quality_2x2_evaluation_v3/harness.py", 31895, "a42f1d0303857f443b5352ed7cfd244551767d347168e3ada6b7f8042cdaa7e4"),
        ("p0_v9_contract", "shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/p0-contract-v9.json", 5231, "51f36fb46eb7a74994abf0a23152ce5d1f3fd7f4e8687aa900d1328e3b9aae1e"),
        ("p0_v9_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-attempt-envelope-v1-successor-v9-independent-review-fable-20261111-clean.json", 15534, "0505e961774d325fdc6b89105215fd88cb0a71f8b942a78976d7ea1e8f49fbb2"),
        ("runner_v8_open_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-runner-v8-independent-review-fable-20261112-8e9a8076-open.json", 6255, "145265647df2a9231d7b64f3b7c70c7266403b38cb15ad98e38deef3a6d588f5"),
        ("runner_v2_open_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-runner-v2-independent-review-fable-20261113-8e9a8076-open.json", 13206, "c2669dec8fd1e32f616a6d97ce1e75f6de9a736d106814db1c99f8328215cff1"),
        ("runner_v3_open_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-runner-v3-independent-review-fable-20261113-8e9a8076-open.json", 22021, "e11ca7dd9b35a21e8d57ef9398c4aa713a77c45d00986b3f4c3d1ca693b06afe"),
        ("p0_package", "shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/__init__.py", 696, "65a1c49a5a85d8357d4f95353e3e2d24ef818ddf6c0978398a6eaab5879bf902"),
        ("p0_adapters", "shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/adapters.py", 10195, "ff20cccf263a57b939e2cb59296354466b6475b318685b08e35c8360680fccbb"),
        ("p0_artifacts", "shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/artifacts.py", 4533, "d082f83703d44c92abb92e02338d9c690477319b1122c6979c8e4f1137306fec"),
        ("p0_bundle", "shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/bundle.py", 10158, "539f3151a7d0f4b39ce8f0166f3493f5273071ff0f009ae5bc92732e82185f6a"),
        ("p0_contracts_source", "shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/contracts.py", 35374, "27c0f194866d1ecdd0f8f6311e308b87be42f6c5fd0c87d525bd10057347cffb"),
        ("p0_pipeline", "shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/pipeline.py", 9605, "9a129560ce2bcc8f90daa5b5280d0b67c75ebd21072a123493fa6d5a6cca018e"),
        ("p0_provider_manifest", "shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/provider-contracts-v9.json", 1998, "1a668419ab622aca992f1792aa730bc29e247322ba554eae6892e20ade51d423"),
        ("fixture_claude_material", "shared/job_runtime/tests/fixtures/r6_data_quality_attempt_envelope_v1/claude-research-material.json", 3988, "81398ba860d803361e39093ebd539b8a7ecb4a2148c0afdb3a5f3b1ec365fbc6"),
        ("fixture_claude_publication", "shared/job_runtime/tests/fixtures/r6_data_quality_attempt_envelope_v1/claude-sanitized-publication.json", 1059, "09a1c6f63d69dcbff713e8f4bc1f50bf856b6f725f3882e7ccab29d2716ebbef"),
        ("fixture_codex_material", "shared/job_runtime/tests/fixtures/r6_data_quality_attempt_envelope_v1/codex-research-material.json", 4078, "e1963190b527721062df7f9a6525766ed443014d16f83be05e411c7707f98c77"),
        ("fixture_codex_publication", "shared/job_runtime/tests/fixtures/r6_data_quality_attempt_envelope_v1/codex-sanitized-publication.json", 631, "7f246bec5742d30c0520bf6ed3426f1bee993ed273014db42a912083c205900b"),
    )
    expected_module_files = (
        (predecessor_module, specs[0][1]),
        (contracts_module, specs[1][1]),
        (grading_module, specs[2][1]),
    )
    authority = predecessor_module._authority
    reconcile = predecessor_module._reconcile_execution_receipt
    predecessor_execute = predecessor_module.execute_block
    predecessor_finalize = predecessor_module.finalize_block
    validate_execution_body = predecessor_module._validate_execution_body
    receipt_committed_at = predecessor_module._receipt_committed_at
    artifact_store = grading_module.ArtifactStore
    validate_map = grading_module.validate_map_commitment
    subprocess_run = subprocess.run
    executable = sys.executable
    hmac_new = hmac.new
    compare_digest = hmac.compare_digest

    def closed_canonical(value: Any) -> bytes:
        return json_dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")

    def closed_sha(raw: bytes) -> str:
        return sha256_constructor(raw).hexdigest()

    def verify_sources(expected_self: Optional[Mapping[str, Any]] = None) -> Mapping[str, str]:
        self_expected = {"bytes": import_source_pin[0], "sha256": import_source_pin[1]} if expected_self is None else dict(expected_self)
        raw_self = source_file.read_bytes()
        if set(self_expected) != {"bytes", "sha256"} or len(raw_self) != self_expected["bytes"] or closed_sha(raw_self) != self_expected["sha256"]:
            raise ContractError("RUNNER_V4_SOURCE_PIN_MISMATCH")
        observed = {"runner_v4_source": self_expected["sha256"]}
        for name, relative, expected_bytes, expected_sha in specs:
            raw = (repo_root / relative).read_bytes()
            if len(raw) != expected_bytes or closed_sha(raw) != expected_sha:
                raise ContractError("RUNNER_V4_DEPENDENCY_PIN_MISMATCH")
            observed[name] = expected_sha
        for module, relative in expected_module_files:
            module_file = getattr(module, "__file__", None)
            if module_file is None or Path(module_file).resolve() != (repo_root / relative).resolve():
                raise ContractError("RUNNER_V4_IMPORTED_SOURCE_MISMATCH")
        if closed_sha(closed_canonical(contracts_module.FROZEN_INPUTS)) != frozen_input_sha:
            raise ContractError("RUNNER_V4_FROZEN_INPUT_MUTATION")
        identity_rows = (("runner_v4_source", str(source_file.relative_to(repo_root)), self_expected["bytes"], self_expected["sha256"]),) + specs
        observed["source_identity"] = closed_sha(closed_canonical(identity_rows))
        return observed

    def root_identity(path: Path) -> str:
        candidate = Path(path).absolute()
        try:
            before = os.lstat(candidate)
            fd = os.open(candidate, _DIR_FLAGS)
            after = os.fstat(fd)
        except OSError as exc:
            raise ContractError("RESERVATION_BOUND_ROOT_OPEN_FAILED") from exc
        try:
            _require(stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode) and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino) and after.st_uid == os.getuid() and stat.S_IMODE(after.st_mode) == 0o700, "RESERVATION_BOUND_ROOT_UNSAFE")
            return closed_sha(closed_canonical({"device": after.st_dev, "inode": after.st_ino}))
        finally:
            os.close(fd)

    def destination_identity(bundle_root: Path) -> str:
        path = Path(bundle_root).absolute()
        cursor = path
        while not os.path.lexists(cursor):
            if cursor.parent == cursor:
                raise ContractError("RESERVATION_DESTINATION_ANCESTOR_MISSING")
            cursor = cursor.parent
        meta = os.lstat(cursor)
        _require(stat.S_ISDIR(meta.st_mode) and not stat.S_ISLNK(meta.st_mode) and meta.st_uid == os.getuid(), "RESERVATION_DESTINATION_ANCESTOR_UNSAFE")
        return closed_sha(closed_canonical({"absolute_path_sha256": closed_sha(os.fsencode(str(path)))}))

    def fixture_root_paths(boundaries: Optional[Mapping[str, Any]]) -> Mapping[str, str]:
        _require(type(boundaries) is dict and set(boundaries) == {"ARM-A", "ARM-B"}, "FIXTURE_BOUNDARIES")
        values = {}
        for arm in ("ARM-A", "ARM-B"):
            owner_root = getattr(getattr(boundaries[arm], "adapter", None), "owner_root", None)
            _require(owner_root is not None, "RESERVATION_P0_OWNER_ROOT_MISSING")
            values[arm] = str(Path(owner_root).absolute())
        return values

    def known_destinations_absent(owner_root: Path, bundle_root: Path) -> bool:
        owner, bundle = Path(owner_root), Path(bundle_root)
        targets = [owner / "receipt/block-v6.json", owner / "receipt/.stage-block-v6.json"]
        targets.extend(owner / ("cell%02d/ref%02d.json" % (ci, ri)) for ci in range(1, 5) for ri in range(1, 7))
        for cell_id in cell_order:
            cell = bundle / cell_id
            targets.extend((cell / (cell_id + ".attempt-bundle.json"), cell / (".stage-" + cell_id + ".attempt-bundle.json")))
        return not any(os.path.lexists(item) for item in targets)

    def bindings_from_payload(payload: Mapping[str, Any], expected_self: Mapping[str, Any]) -> tuple[Mapping[str, Any], str, bool]:
        pins = verify_sources(expected_self)
        root = Path(payload["owner_root"]).absolute()
        bundle = Path(payload["bundle_root"]).absolute()
        store = artifact_store(root)
        fixture = True
        registry_ref = payload["authority_registry_ref"]
        map_ref = payload["map_commitment_ref"]
        registry, grant, _grader_authority = authority(root, registry_ref, fixture)
        map_value = store.read(map_ref)
        validate_map(map_value)
        grant_sha, map_sha = closed_sha(closed_canonical(grant)), closed_sha(closed_canonical(map_value))
        _require(grant_sha == registry["block_grant_ref"]["canonical_content_sha256"], "RUNNER_V4_GRANT_CONTENT_BINDING")
        _require(map_sha == map_ref["canonical_content_sha256"], "RUNNER_V4_MAP_CONTENT_BINDING")
        p0_paths = payload["p0_owner_roots"]
        _require(type(p0_paths) is dict and set(p0_paths) == {"ARM-A", "ARM-B"}, "RESERVATION_P0_ROOTS")
        p0_ids = {arm: root_identity(Path(p0_paths[arm])) for arm in ("ARM-A", "ARM-B")}
        _require(p0_ids["ARM-A"] != p0_ids["ARM-B"], "RESERVATION_P0_OWNER_ROOT_ALIAS")
        values = {
            "block_id": grant["block_id"], "grant_content_sha256": grant_sha,
            "input_identity_sha256": frozen_input_sha, "map_content_sha256": map_sha,
            "runner_owner_root_id": store.root_id(), "source_identity_sha256": pins["source_identity"],
            "authority_registry_ref_sha256": closed_sha(closed_canonical(dict(registry_ref))),
            "map_commitment_ref_sha256": closed_sha(closed_canonical(dict(map_ref))),
            "p0_owner_root_ids": p0_ids, "destination_identity_sha256": destination_identity(bundle),
            "predecessor_runner_sha256": pins["predecessor_runner"],
            "predecessor_contracts_sha256": pins["predecessor_contracts"],
            "grading_harness_sha256": pins["grading_harness"],
            "p0_v9_contract_sha256": pins["p0_v9_contract"], "p0_v9_review_sha256": pins["p0_v9_review"],
            "runner_v8_open_review_sha256": pins["runner_v8_open_review"],
            "runner_v2_open_review_sha256": pins["runner_v2_open_review"],
            "runner_v3_open_review_sha256": pins["runner_v3_open_review"],
            "runner_v4_source_sha256": pins["runner_v4_source"], "fixture": fixture,
        }
        return values, grant["block_id"], fixture

    def fixture_descriptor(boundaries: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
        _require(type(boundaries) is dict and set(boundaries) == {"ARM-A", "ARM-B"}, "FIXTURE_BOUNDARIES")
        result = {}
        for arm in ("ARM-A", "ARM-B"):
            boundary = boundaries[arm]
            inner = getattr(boundary, "inner", boundary)
            adapter = getattr(inner, "adapter", getattr(boundary, "adapter", None))
            owner = getattr(adapter, "owner_root", None)
            public = getattr(adapter, "public_root", None)
            _require(owner is not None and public is not None, "FIXTURE_ADAPTER_ROOTS")
            mode = getattr(inner, "mode", None)
            _require(mode in (None, "policy", "STOP", "UNKNOWN", "missing_refs", "tampered_evidence", "engine", "grading", "tamper_owner"), "FIXTURE_MODE")
            counter = getattr(boundary, "counter", None)
            result[arm] = {
                "owner_root": str(Path(owner).absolute()),
                "public_root": str(Path(public).absolute()),
                "mode": mode,
                "counter_path": None if counter is None else str(Path(counter).absolute()),
                "crash_first": getattr(boundary, "crash_first", False) is True,
            }
        return result

    fixture_directory = repo_root / "shared/job_runtime/tests/fixtures/r6_data_quality_attempt_envelope_v1"

    def load_fixture(name: str) -> Mapping[str, Any]:
        raw = (fixture_directory / name).read_bytes()
        return strict_json_loads(raw.decode("ascii"), "RUNNER_V4_FIXTURE_JSON")

    def p0_readback(cell_id: str) -> Mapping[str, Any]:
        return {
            "version": 1, "job_id": "job-" + cell_id, "slot_id": "slot-" + cell_id,
            "attempt_id": "attempt-" + cell_id, "operation_id": "operation/" + cell_id,
            "prompt_binding_sha256": "d" * 64, "transaction": "BEGIN_IMMEDIATE_POST_WRITE_READBACK",
            "counts": {"job": 1, "slot": 1, "attempt": 1},
        }

    def fixture_material(label: str, cell_id: str, terminal: str, readback: Mapping[str, Any], artifact: Mapping[str, Any]) -> Mapping[str, Any]:
        filename = "claude-research-material.json" if label == "ARM-A" else "codex-research-material.json"
        value = copy.deepcopy(load_fixture(filename))
        binding = {
            "cell_id": cell_id, "job_id": readback["job_id"], "slot_id": readback["slot_id"],
            "attempt_id": readback["attempt_id"], "operation_id": readback["operation_id"],
            "prompt_binding_sha256": "d" * 64,
            "canonical_engine_readback_digest": contracts_module.sha256_json(readback),
            "source_cutoff_sha256": contracts_module.FROZEN_INPUTS["source_cutoff_sha256"],
            "blind_provider_label": label,
            "provider_schema": __import__("shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts", fromlist=["PROVIDER_BINDINGS"]).PROVIDER_BINDINGS[label]["provider_schema"],
            "publication_driver_identity_sha256": __import__("shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts", fromlist=["PROVIDER_BINDINGS"]).PROVIDER_BINDINGS[label]["publication_driver_identity_sha256"],
        }
        raw = b'{"raw":"runner-v6-synthetic"}'
        for body in value.values():
            body["binding"] = copy.deepcopy(binding)
            body["provider_terminal"] = terminal
            body["raw_sha256"] = closed_sha(raw)
            body["publication_artifact_sha256"] = closed_sha(closed_canonical(artifact))
        for source in value["source_inventory"]["sources"]:
            source["source_cutoff_sha256"] = contracts_module.FROZEN_INPUTS["source_cutoff_sha256"]
        if terminal != "PASS":
            value["sanitized_output"]["answer"] = "Attempt retained terminal " + terminal + "."
            value["sanitized_output"]["complete"] = False
        return value

    class ChildFixtureBoundary:
        __slots__ = ("label", "mode", "counter_path", "crash_first", "adapter")

        def __init__(self, label: str, value: Mapping[str, Any]):
            self.label = label
            self.mode = value["mode"]
            self.counter_path = value["counter_path"]
            self.crash_first = value["crash_first"]
            if label == "ARM-A":
                self.adapter = claude_adapter(Path(value["owner_root"]), Path(value["public_root"]), owner_tamper_on_publish=self.mode == "tamper_owner")
            else:
                self.adapter = codex_adapter(Path(value["owner_root"]), Path(value["public_root"]), owner_tamper_on_publish=self.mode == "tamper_owner")

        def __call__(self, plan: Mapping[str, Any]) -> Mapping[str, Any]:
            cell_id, index = plan["cell_id"], plan["order_index"]
            if self.counter_path is not None:
                raw_count = (cell_id + "\n").encode("ascii")
                fd = os.open(self.counter_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0), 0o600)
                try:
                    _require(os.write(fd, raw_count) == len(raw_count), "FIXTURE_COUNTER_SHORT_WRITE")
                    _fsync(fd, "FIXTURE_COUNTER_FSYNC")
                finally:
                    os.close(fd)
            if self.crash_first and index == 0:
                os._exit(42)
            if self.mode == "policy" and index == 0:
                plan["tool_policy"]["roster"][0]["version"] = "MUTATED"
            terminal = self.mode if self.mode in ("STOP", "UNKNOWN") and index == 0 else "PASS"
            readback = p0_readback(cell_id)
            publication_name = "claude-sanitized-publication.json" if self.label == "ARM-A" else "codex-sanitized-publication.json"
            artifact = copy.deepcopy(load_fixture(publication_name))
            material = fixture_material(self.label, cell_id, terminal, readback, artifact)
            if self.mode == "missing_refs" and index == 0:
                material.pop("factual_evidence")
            if self.mode == "tampered_evidence" and index == 0:
                material["citation_inventory"]["citations"][0]["source_id"] = "missing-source"
            output = {
                "model_readback": plan["model"],
                "engine_sha256": "e" * 64 if self.mode == "engine" and index == 0 else "d" * 64,
                "readback": {key: readback[key] for key in ("job_id", "slot_id", "attempt_id", "operation_id", "prompt_binding_sha256")},
                "p0_readback": readback, "raw": b'{"raw":"runner-v6-synthetic"}',
                "provider_publication_artifact": artifact, "research_material": material,
                "terminal_state": terminal,
                "dq_checks": [{"name": name, "status": "PASS", "code": "CHECK_PASS"} for name in contracts_module.CHECK_NAMES] if plan["checks_enabled"] else None,
                "cell_window": {"start_ms": 100 + index * 100, "end_ms": 150 + index * 100},
                "tool_readback": copy.deepcopy(plan["tool_policy"]), "web_readback": copy.deepcopy(plan["web_policy"]),
            }
            if self.mode == "grading" and index == 0:
                output["grading_inputs"] = {}
            return output

    def child_boundaries(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        values = payload["fixture_boundaries"]
        _require(type(values) is dict and set(values) == {"ARM-A", "ARM-B"}, "FIXTURE_BOUNDARIES")
        for arm in ("ARM-A", "ARM-B"):
            _require(type(values[arm]) is dict and set(values[arm]) == {"owner_root", "public_root", "mode", "counter_path", "crash_first"}, "FIXTURE_DESCRIPTOR")
        return {arm: ChildFixtureBoundary(arm, values[arm]) for arm in ("ARM-A", "ARM-B")}

    def child_operation(request: Mapping[str, Any]) -> Mapping[str, Any]:
        expected_self = request["expected_self"]
        payload = request["payload"]
        operation = request["operation"]
        if operation == "finalize":
            verify_sources(expected_self)
            ordered_grades = {cell_id: payload["grade_refs"][cell_id] for cell_id in cell_order}
            result = predecessor_finalize(payload["execution_ref"], Path(payload["owner_root"]), ordered_grades, payload["opening_ref"])
            return {"finalized": result}
        _require(operation == "execute", "RUNNER_V4_CHILD_OPERATION")
        bindings, block_id, fixture = bindings_from_payload(payload, expected_self)
        root, bundle = Path(payload["owner_root"]).absolute(), Path(payload["bundle_root"]).absolute()
        with ReservationManager(root, bindings) as manager:
            proof = lambda: {"zero_effects": known_destinations_absent(root, bundle), "admission_absent": True, "receipt_absent": known_destinations_absent(root, bundle), "destinations_absent": known_destinations_absent(root, bundle), "program_order_proof": True}
            handle, is_owner = manager.acquire(proof, fault=request.get("reservation_fault"))
            if is_owner and request.get("reservation_fault") == "crash_after_reservation":
                os._exit(43)
            if is_owner and request.get("reservation_fault") == "stop_after_reservation":
                os.kill(os.getpid(), signal.SIGSTOP)
            if not is_owner:
                receipt = reconcile(root, payload["authority_registry_ref"], payload["map_commitment_ref"], fixture, block_id)
                if receipt is not None:
                    manager.mark_completed(handle, receipt)
                    return {"receipt": receipt, "reconciled": True}
                if manager.admitted(handle):
                    manager.mark_unknown(handle)
                    raise ContractError("RESERVATION_POST_ADMISSION_UNKNOWN_NO_REPLAY")
                raise ContractError("RESERVATION_NOT_OWNER")
            handle.admit()
            if request.get("reservation_fault") in ("crash_after_admission", "crash_pre_first_boundary"):
                os._exit(43)
            boundaries = child_boundaries(payload)
            receipt_fault = request.get("receipt_fault")
            if receipt_fault in ("crash_after_stage_fsync", "crash_post_link"):
                original_commit = predecessor_module._commit_execution_receipt
                def crashing_commit(commit_root: Path, value: Mapping[str, Any], committed_at_ms: int, _fault: Optional[str] = None, _hook: Optional[Any] = None) -> Mapping[str, Any]:
                    return original_commit(commit_root, value, committed_at_ms, receipt_fault, crash_hook=lambda _phase: os._exit(44))
                predecessor_module._commit_execution_receipt = crashing_commit
            try:
                receipt = predecessor_execute(payload["authority_registry_ref"], root, payload["map_commitment_ref"], bundle, _fixture_boundaries=boundaries, _receipt_fault=None if receipt_fault in ("crash_after_stage_fsync", "crash_post_link") else receipt_fault)
            except Exception as exc:
                manager.mark_unknown(handle)
                raise ContractError("RESERVATION_POST_ADMISSION_UNKNOWN_NO_REPLAY") from exc
            manager.mark_completed(handle, receipt)
            return {"receipt": receipt, "reconciled": False}

    def authenticated_response(request_raw: bytes, request: Mapping[str, Any], result: Mapping[str, Any]) -> bytes:
        body = {"version": 1, "request_sha256": closed_sha(request_raw), "source_sha256": request["expected_self"]["sha256"], "child_pid": os.getpid(), "result": dict(result)}
        body["hmac_sha256"] = hmac_new(bytes.fromhex(request["secret"]), closed_canonical(body), sha256_constructor).hexdigest()
        return closed_canonical(body)

    def child_main() -> int:
        try:
            request_raw = sys.stdin.buffer.read(1_048_577)
            _require(len(request_raw) <= 1_048_576, "RUNNER_V4_CHILD_REQUEST_SIZE")
            request = strict_json_loads(request_raw.decode("ascii"), "RUNNER_V4_CHILD_REQUEST")
            request_keys = {"version", "operation", "payload", "expected_self", "secret", "reservation_fault", "receipt_fault"}
            _require(
                type(request) is dict
                and set(request) == request_keys
                and request["version"] == 1
                and request["operation"] in ("execute", "finalize")
                and type(request["payload"]) is dict
                and type(request["expected_self"]) is dict
                and set(request["expected_self"]) == {"bytes", "sha256"}
                and type(request["secret"]) is str
                and len(request["secret"]) == 64
                and all(ch in _SHA for ch in request["secret"])
                and (request["reservation_fault"] is None or type(request["reservation_fault"]) is str)
                and (request["receipt_fault"] is None or type(request["receipt_fault"]) is str),
                "RUNNER_V4_CHILD_REQUEST",
            )
            result = child_operation(request)
        except Exception as exc:
            if "request" not in locals() or type(request) is not dict or type(request.get("secret")) is not str or len(request.get("secret", "")) != 64:
                return 70
            result = {"error": str(exc) if isinstance(exc, ContractError) else "RUNNER_V4_CHILD_INTERNAL"}
        sys.stdout.buffer.write(authenticated_response(request_raw, request, result))
        sys.stdout.buffer.flush()
        return 0

    def run_child(operation: str, payload: Mapping[str, Any], *, reservation_fault: Optional[str] = None, receipt_fault: Optional[str] = None) -> Mapping[str, Any]:
        pins = verify_sources()
        secret = secrets.token_hex(32)
        request = {"version": 1, "operation": operation, "payload": dict(payload), "expected_self": {"bytes": import_source_pin[0], "sha256": pins["runner_v4_source"]}, "secret": secret, "reservation_fault": reservation_fault, "receipt_fault": receipt_fault}
        raw = closed_canonical(request)
        try:
            completed = subprocess_run([executable, "-I", str(source_file), "--r6-v4-child"], input=raw, capture_output=True, cwd="/", env={"PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C", "LANG": "C"}, timeout=30, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ContractError("RUNNER_V4_CHILD_TIMEOUT") from exc
        if completed.returncode != 0:
            raise ContractError("RUNNER_V4_CHILD_EXIT_%d" % completed.returncode)
        _require(not completed.stderr, "RUNNER_V4_CHILD_STDERR")
        response = strict_json_loads(completed.stdout.decode("ascii"), "RUNNER_V4_CHILD_RECEIPT")
        _require(
            type(response) is dict
            and set(response) == {"version", "request_sha256", "source_sha256", "child_pid", "result", "hmac_sha256"}
            and response["version"] == 1
            and type(response["child_pid"]) is int
            and response["child_pid"] > 0
            and response["child_pid"] != os.getpid(),
            "RUNNER_V4_CHILD_RECEIPT_SHAPE",
        )
        mac = response.pop("hmac_sha256")
        expected = hmac_new(bytes.fromhex(secret), closed_canonical(response), sha256_constructor).hexdigest()
        _require(type(mac) is str and compare_digest(mac, expected), "RUNNER_V4_CHILD_RECEIPT_AUTH")
        _require(response["request_sha256"] == closed_sha(raw) and response["source_sha256"] == pins["runner_v4_source"], "RUNNER_V4_CHILD_RECEIPT_BINDING")
        result = response["result"]
        _require(type(result) is dict, "RUNNER_V4_CHILD_RESULT")
        if "error" in result:
            raise ContractError(result["error"])
        return result

    def consume_execution_receipt(
        owner_root: Path,
        claimed: Mapping[str, Any],
        authority_registry_ref: Mapping[str, Any],
        map_commitment_ref: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ref_keys = {"kind", "path", "sha256", "canonical_content_sha256", "bytes", "immutable_at_ms"}
        _require(
            type(claimed) is dict
            and set(claimed) == ref_keys
            and claimed["kind"] == "execution_receipt_v6"
            and claimed["path"] == "receipt/block-v6.json"
            and type(claimed["bytes"]) is int
            and not isinstance(claimed["bytes"], bool)
            and claimed["bytes"] > 0
            and type(claimed["immutable_at_ms"]) is int
            and not isinstance(claimed["immutable_at_ms"], bool)
            and _is_sha(claimed["sha256"])
            and claimed["canonical_content_sha256"] == claimed["sha256"],
            "RUNNER_V4_RECEIPT_REF",
        )
        root_fd = receipt_fd = fd = -1
        try:
            root_fd, _root_id = _open_owner_root(Path(owner_root))
            receipt_fd = os.open("receipt", _DIR_FLAGS, dir_fd=root_fd)
            receipt_meta = os.fstat(receipt_fd)
            _require(
                stat.S_ISDIR(receipt_meta.st_mode)
                and receipt_meta.st_uid == os.getuid()
                and stat.S_IMODE(receipt_meta.st_mode) == 0o700,
                "RUNNER_V4_RECEIPT_DIRECTORY_UNSAFE",
            )
            fd = os.open("block-v6.json", _READ_FLAGS, dir_fd=receipt_fd)
            meta = os.fstat(fd)
            _require(
                stat.S_ISREG(meta.st_mode)
                and meta.st_uid == os.getuid()
                and stat.S_IMODE(meta.st_mode) == 0o600
                and meta.st_nlink == 1,
                "RUNNER_V4_RECEIPT_UNSAFE",
            )
            chunks = []
            total = 0
            while True:
                part = os.read(fd, 65536)
                if not part:
                    break
                total += len(part)
                _require(total <= 1_048_576, "RUNNER_V4_RECEIPT_SIZE")
                chunks.append(part)
            raw = b"".join(chunks)
        except ContractError:
            raise
        except OSError as exc:
            raise ContractError("RUNNER_V4_RECEIPT_READ_FAILED") from exc
        finally:
            for descriptor in (fd, receipt_fd, root_fd):
                if descriptor >= 0:
                    os.close(descriptor)
        _require(
            len(raw) == claimed["bytes"]
            and closed_sha(raw) == claimed["sha256"]
            and closed_sha(raw) == claimed["canonical_content_sha256"],
            "RUNNER_V4_RECEIPT_REF_BINDING",
        )
        value = strict_json_loads(raw.decode("ascii"), "RUNNER_V4_RECEIPT_JSON")
        _require(type(value) is dict and closed_canonical(value) == raw, "RUNNER_V4_RECEIPT_CANONICAL")
        validate_execution_body(Path(owner_root), value, authority_registry_ref, map_commitment_ref, True)
        _require(claimed["immutable_at_ms"] == receipt_committed_at(value), "RUNNER_V4_RECEIPT_TIME_BINDING")
        return dict(claimed)

    def make_payload(authority_registry_ref: Mapping[str, Any], owner_root: Path, map_commitment_ref: Mapping[str, Any], bundle_root: Path, boundaries: Mapping[str, Any]) -> Mapping[str, Any]:
        descriptor = fixture_descriptor(boundaries)
        return {"authority_registry_ref": dict(authority_registry_ref), "owner_root": str(Path(owner_root).absolute()), "map_commitment_ref": dict(map_commitment_ref), "bundle_root": str(Path(bundle_root).absolute()), "p0_owner_roots": {arm: descriptor[arm]["owner_root"] for arm in ("ARM-A", "ARM-B")}, "fixture_boundaries": descriptor}

    def execute_impl(authority_registry_ref: Mapping[str, Any], owner_root: Path, map_commitment_ref: Mapping[str, Any], bundle_root: Path, *, _fixture_boundaries: Optional[Mapping[str, Any]] = None, _receipt_fault: Optional[str] = None, _reservation_fault: Optional[str] = None) -> Mapping[str, Any]:
        owner_input = Path(owner_root).absolute()
        _require(not owner_input.is_symlink(), "OWNER_ROOT_SYMLINK")
        root = owner_input.resolve()
        payload = make_payload(authority_registry_ref, root, map_commitment_ref, Path(bundle_root).absolute(), _fixture_boundaries)
        claimed = run_child("execute", payload, reservation_fault=_reservation_fault, receipt_fault=_receipt_fault)["receipt"]
        return consume_execution_receipt(root, claimed, authority_registry_ref, map_commitment_ref)

    def finalize_impl(execution_ref: Mapping[str, Any], owner_root: Path, grade_refs: Mapping[str, Any], opening_ref: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = {"execution_ref": dict(execution_ref), "owner_root": str(Path(owner_root).absolute()), "grade_refs": {key: list(value) for key, value in grade_refs.items()}, "opening_ref": dict(opening_ref)}
        return run_child("finalize", payload)["finalized"]

    status_value = "P0_V10_RECLOSURE_REQUIRED"
    def default_impl(*_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
        return {"status": status_value, "p0_schema_status": "P0_V10_REQUIRED", "consumer_status": "P0_V10_RECLOSURE_REQUIRED", "countable": False, "activation": False, "orchestrator_rebind": "PENDING", "fresh_independent_review": "PENDING"}

    return default_impl, execute_impl, finalize_impl, child_main

if __name__ == "__main__" and __import__("sys").argv[1:] == ["--r6-v4-child"]:
    _child_entry = _build_private_runtime()[3]
    raise SystemExit(_child_entry())

default_run, execute_block, finalize_block, _discarded_child_entry = _build_private_runtime()
del _discarded_child_entry
del _build_private_runtime

__all__ = ["STATUS", "default_run", "execute_block", "finalize_block"]
