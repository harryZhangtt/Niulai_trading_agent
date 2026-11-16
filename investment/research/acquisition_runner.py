"""Provider-agnostic hosted acquisition runner with durable dispatch fencing.

The runner owns persistence, deadlines, bounded private capture, and cleanup.  The
provider is an injected callable; this module never selects or imports one.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import base64
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import tempfile
import threading
import time
from typing import Callable, Iterable

from shared.research_sources.acquisition_contracts import (
    AcquisitionIdentity,
    DispatchEvent,
    DispatchState,
    ExactArguments,
    append_dispatch_event,
    validate_dispatch_history,
)
from shared.research_sources.artifacts import SourceError, private_path, read, save


RUNNER_VERSION = "acquisition-runner-1"
_BACKEND_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


class RunnerError(RuntimeError):
    """A sanitized runner failure; the message is always a stable error code."""


def verify_dispatch_receipt(ref: dict) -> dict:
    """Independently reopen a runner receipt and its immutable hash-chain proof."""
    try:
        receipt = read(ref)
        if (not isinstance(receipt, dict)
                or receipt.get("kind") != "acquisition_dispatch_receipt"
                or receipt.get("version") != RUNNER_VERSION
                or receipt.get("invocation_started") is not True
                or receipt.get("provider_items") != 1):
            raise ValueError
        proof = read(receipt["journal_ref"])
        rows = proof.get("events")
        if (proof.get("kind") != "acquisition_dispatch_journal_proof"
                or proof.get("version") != RUNNER_VERSION
                or not isinstance(rows, list) or not rows):
            raise ValueError
        typed = []
        previous_hash = None
        for sequence, row in enumerate(rows):
            if (not isinstance(row, dict) or row.get("sequence") != sequence
                    or row.get("previous_event_sha256") != previous_hash
                    or row.get("event_sha256") != HostedAcquisitionRunner._event_hash(row)):
                raise ValueError
            typed.append(DispatchEvent(
                dispatch_id=row["dispatch_id"], sequence=sequence,
                state=DispatchState(row["state"]), evidence_sha256=row.get("evidence_sha256"),
            ))
            previous_hash = row["event_sha256"]
        validate_dispatch_history(typed)
        first, last = rows[0], rows[-1]
        identity = first.get("identity")
        canonical = base64.b64decode(first.get("arguments_b64", ""), validate=True)
        if (not isinstance(identity, dict)
                or hashlib.sha256(canonical).hexdigest() != first.get("arguments_sha256")
                or proof.get("journal_head_sha256") != last.get("event_sha256")
                or proof.get("dispatch_id") != first.get("dispatch_id")
                or last.get("state") != DispatchState.CAPTURED.value
                or any(receipt.get(key) != identity.get(key) for key in (
                    "experiment_id", "execution_id", "trace_id", "operation_id",
                    "attempt_id", "dispatch_id"))
                or receipt.get("arguments_sha256") != first.get("arguments_sha256")
                or receipt.get("configured_backend") != first.get("configured_backend")
                or receipt.get("evidence_sha256") != last.get("evidence_sha256")
                or receipt.get("status") != last.get("status")
                or receipt.get("journal_head_sha256") != last.get("event_sha256")):
            raise ValueError
        return {**receipt, "journal_events": tuple(rows), "canonical_arguments": canonical}
    except (SourceError, OSError, KeyError, TypeError, ValueError, UnicodeError):
        raise RunnerError("ACQ_RUNNER_RECEIPT_INVALID") from None


@dataclass(frozen=True)
class HostedProviderResponse:
    """A provider result whose chunks are consumed once into private storage."""

    chunks: Iterable[bytes]
    observed_backend: str | None = None


class HostedAcquisitionRunner:
    """Single-process runner around an injected hosted-provider callable.

    ``provider`` receives ``(exact_argument_bytes, absolute_deadline)``.  It must
    not be selected by this class and must honor the supplied absolute monotonic
    deadline.  Durable journal state, rather than an in-memory counter, is the
    authority for whether another invocation is permitted.
    """

    def __init__(
        self,
        directory,
        *,
        provider: Callable[[bytes, float], HostedProviderResponse],
        configured_backend: str,
        run_deadline: float,
        raw_byte_limit: int,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if not callable(provider):
            raise RunnerError("ACQ_RUNNER_PROVIDER_INVALID")
        if (not isinstance(configured_backend, str)
                or _BACKEND_IDENTITY.fullmatch(configured_backend) is None):
            raise RunnerError("ACQ_RUNNER_BACKEND_INVALID")
        if (not isinstance(run_deadline, (int, float)) or isinstance(run_deadline, bool)
                or not math.isfinite(run_deadline)):
            raise RunnerError("ACQ_RUNNER_DEADLINE_INVALID")
        if type(raw_byte_limit) is not int or not 0 < raw_byte_limit <= 8 * 1024 * 1024:
            raise RunnerError("ACQ_RUNNER_RAW_LIMIT_INVALID")
        self.directory = private_path(directory, create=True)
        self.raw_directory = private_path(self.directory / "raw", create=True)
        self.provider = provider
        self.configured_backend = configured_backend
        self.run_deadline = float(run_deadline)
        self.raw_byte_limit = raw_byte_limit
        self.monotonic = monotonic
        self._recover_incomplete_dispatches()

    @staticmethod
    def _encoded(value) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    @staticmethod
    def _event_hash(event: dict) -> str:
        return hashlib.sha256(HostedAcquisitionRunner._encoded(
            {key: value for key, value in event.items() if key != "event_sha256"}
        )).hexdigest()

    def _journal_path(self, dispatch_id: str) -> Path:
        # AcquisitionIdentity already validates this vocabulary; reject callers
        # that try to address a journal without first establishing that identity.
        if not dispatch_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
                                  for char in dispatch_id) or len(dispatch_id) > 96:
            raise RunnerError("ACQ_RUNNER_DISPATCH_ID_INVALID")
        return self.directory / f"dispatch-{dispatch_id}.jsonl"

    @contextmanager
    def _lock(self, dispatch_id: str):
        self._journal_path(dispatch_id)  # Validate before using the ID in any path.
        path = self.directory / f"dispatch-{dispatch_id}.lock"
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags, 0o600)
        except OSError:
            raise RunnerError("ACQ_RUNNER_LOCK_INVALID") from None
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RunnerError("ACQ_RUNNER_BUSY") from None
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _read_events(self, dispatch_id: str) -> list[dict]:
        path = self._journal_path(dispatch_id)
        if not path.exists():
            return []
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise RunnerError("ACQ_RUNNER_JOURNAL_INVALID")
        try:
            rows = [json.loads(line) for line in path.read_bytes().splitlines() if line]
            previous_hash = None
            typed = []
            for sequence, row in enumerate(rows):
                if (not isinstance(row, dict) or row.get("sequence") != sequence
                        or row.get("previous_event_sha256") != previous_hash
                        or row.get("event_sha256") != self._event_hash(row)):
                    raise ValueError
                typed.append(DispatchEvent(
                    dispatch_id=row["dispatch_id"], sequence=row["sequence"],
                    state=DispatchState(row["state"]), evidence_sha256=row.get("evidence_sha256"),
                ))
                previous_hash = row["event_sha256"]
            validate_dispatch_history(typed)
            return rows
        except (KeyError, TypeError, ValueError, UnicodeError):
            raise RunnerError("ACQ_RUNNER_JOURNAL_INVALID") from None

    def _append(self, dispatch_id: str, state: DispatchState, *, evidence_sha256=None, **fields) -> dict:
        rows = self._read_events(dispatch_id)
        typed = [DispatchEvent(
            row["dispatch_id"], row["sequence"], DispatchState(row["state"]),
            row.get("evidence_sha256"),
        ) for row in rows]
        if rows:
            append_dispatch_event(typed, state, evidence_sha256=evidence_sha256)
        elif state is not DispatchState.PREPARED:
            raise RunnerError("ACQ_RUNNER_STATE")
        event = {
            "runner_version": RUNNER_VERSION,
            "dispatch_id": dispatch_id,
            "sequence": len(rows),
            "state": state.value,
            "evidence_sha256": evidence_sha256,
            "previous_event_sha256": rows[-1]["event_sha256"] if rows else None,
            **fields,
        }
        event["event_sha256"] = self._event_hash(event)
        path = self._journal_path(dispatch_id)
        pending = None
        try:
            fd, pending = tempfile.mkstemp(prefix=f".{path.name}.", dir=self.directory)
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                for row in (*rows, event):
                    stream.write(self._encoded(row) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(pending, path)
            pending = None
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            raise RunnerError("ACQ_RUNNER_JOURNAL_WRITE_FAILED") from None
        finally:
            if pending is not None:
                try:
                    os.unlink(pending)
                except FileNotFoundError:
                    pass
        return event

    def prepare(self, identity: AcquisitionIdentity, arguments: ExactArguments) -> dict:
        """Durably bind one stable dispatch identity to exact argument bytes."""
        if not isinstance(identity, AcquisitionIdentity) or not isinstance(arguments, ExactArguments):
            raise RunnerError("ACQ_RUNNER_PREPARE_INVALID")
        dispatch_id = identity.dispatch.dispatch_id
        with self._lock(dispatch_id):
            rows = self._read_events(dispatch_id)
            identity_value = {
                "experiment_id": identity.run.experiment_id,
                "execution_id": identity.run.execution_id,
                "trace_id": identity.run.trace_id,
                "operation_id": identity.dispatch.operation_id,
                "attempt_id": identity.dispatch.attempt_id,
                "dispatch_id": dispatch_id,
            }
            if rows:
                first = rows[0]
                if (first.get("identity") != identity_value
                        or first.get("arguments_sha256") != arguments.sha256
                        or first.get("arguments_b64") != base64.b64encode(arguments.canonical_json).decode()
                        or first.get("configured_backend") != self.configured_backend):
                    raise RunnerError("ACQ_RUNNER_PREPARE_CONFLICT")
                return self._public_event(rows[-1])
            event = self._append(
                dispatch_id, DispatchState.PREPARED, identity=identity_value,
                arguments_sha256=arguments.sha256,
                arguments_b64=base64.b64encode(arguments.canonical_json).decode(),
                configured_backend=self.configured_backend,
            )
            return self._public_event(event)

    def claim(self, dispatch_id: str) -> bytes:
        """Claim once, or reclaim only after authoritative not-dispatched evidence."""
        with self._lock(dispatch_id):
            rows = self._read_events(dispatch_id)
            if not rows or DispatchState(rows[-1]["state"]) not in {
                DispatchState.PREPARED, DispatchState.DEFINITELY_NOT_DISPATCHED,
            }:
                raise RunnerError("ACQ_RUNNER_DISPATCH_FENCED")
            self._append(dispatch_id, DispatchState.CLAIMED)
            try:
                return base64.b64decode(rows[0]["arguments_b64"], validate=True)
            except (KeyError, ValueError):
                raise RunnerError("ACQ_RUNNER_JOURNAL_INVALID") from None

    def begin_external_invocation(self, identity: AcquisitionIdentity,
                                  arguments: ExactArguments, *,
                                  absolute_deadline: float) -> dict:
        """Bind, claim, and durably fence one cooperative host invocation."""
        if (not isinstance(absolute_deadline, (int, float))
                or isinstance(absolute_deadline, bool)
                or not math.isfinite(absolute_deadline)):
            raise RunnerError("ACQ_RUNNER_DEADLINE_INVALID")
        effective = min(float(absolute_deadline), self.run_deadline)
        self.prepare(identity, arguments)
        claimed = self.claim(identity.dispatch.dispatch_id)
        if claimed != arguments.canonical_json:
            raise RunnerError("ACQ_RUNNER_ARGUMENT_MISMATCH")
        with self._lock(identity.dispatch.dispatch_id):
            if self.monotonic() >= effective:
                self._record_preinvoke_failure(
                    identity.dispatch.dispatch_id,
                    "ACQ_RUNNER_DEADLINE_BEFORE_DISPATCH")
                raise RunnerError("ACQ_RUNNER_DEADLINE_BEFORE_DISPATCH")
            event = self._append(
                identity.dispatch.dispatch_id, DispatchState.INVOCATION_STARTED,
                absolute_deadline=effective,
                configured_backend=self.configured_backend)
        return {**self._public_event(event),
                "arguments": claimed,
                "arguments_sha256": arguments.sha256,
                "absolute_deadline": effective}

    def capture_external_result(self, dispatch_id: str, raw_bytes: bytes, *,
                                observed_backend: str | None) -> dict:
        """Capture exact cooperative-host bytes through the runner-owned journal."""
        if not isinstance(raw_bytes, bytes) or not raw_bytes:
            raise RunnerError("ACQ_RUNNER_RAW_INVALID")
        if len(raw_bytes) > self.raw_byte_limit:
            return self._known_failure(dispatch_id, "ACQ_RUNNER_RAW_LIMIT_EXCEEDED")
        try:
            raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return self._known_failure(dispatch_id, "HOST_WEB_BODY_UNPARSEABLE")
        if (observed_backend is not None
                and (not isinstance(observed_backend, str)
                     or _BACKEND_IDENTITY.fullmatch(observed_backend) is None)):
            raise RunnerError("ACQ_RUNNER_BACKEND_INVALID")
        with self._lock(dispatch_id):
            rows = self._read_events(dispatch_id)
            if not rows or rows[-1]["state"] not in {
                    DispatchState.INVOCATION_STARTED.value,
                    DispatchState.POSSIBLY_DISPATCHED.value}:
                raise RunnerError("ACQ_RUNNER_STATE")
            deadline = rows[-1].get("absolute_deadline")
            if deadline is None:
                deadline = next((row.get("absolute_deadline") for row in reversed(rows)
                                 if row.get("absolute_deadline") is not None), None)
            if deadline is None or self.monotonic() > min(float(deadline), self.run_deadline):
                if rows[-1]["state"] == DispatchState.INVOCATION_STARTED.value:
                    self._append(dispatch_id, DispatchState.POSSIBLY_DISPATCHED,
                                 code="ACQ_RUNNER_DEADLINE_AFTER_DISPATCH")
                raise RunnerError("ACQ_RUNNER_DEADLINE_AFTER_DISPATCH")
            raw_directory = private_path(self.raw_directory / dispatch_id, create=True)
            raw_ref = save(raw_directory, raw_bytes, suffix="bin")
            evidence = hashlib.sha256(raw_bytes).hexdigest()
            event = self._append(
                dispatch_id, DispatchState.CAPTURED, evidence_sha256=evidence,
                status="captured", raw_ref=raw_ref, raw_bytes=len(raw_bytes),
                configured_backend=self.configured_backend,
                observed_backend=observed_backend)
            dispatch_ref = self._save_dispatch_receipt(
                dispatch_id, status="captured", observed_backend=observed_backend)
        return self._receipt_event(event, dispatch_ref=dispatch_ref)

    def fence_external_unknown(self, dispatch_id: str, code: str) -> dict:
        """Fence a cooperative call whose outcome cannot be established."""
        if not isinstance(code, str) or not code:
            raise RunnerError("ACQ_RUNNER_UNKNOWN_CODE_INVALID")
        with self._lock(dispatch_id):
            rows = self._read_events(dispatch_id)
            if not rows:
                raise RunnerError("ACQ_RUNNER_STATE")
            if rows[-1]["state"] == DispatchState.INVOCATION_STARTED.value:
                event = self._append(
                    dispatch_id, DispatchState.POSSIBLY_DISPATCHED, code=code)
            elif rows[-1]["state"] == DispatchState.POSSIBLY_DISPATCHED.value:
                event = rows[-1]
            else:
                raise RunnerError("ACQ_RUNNER_STATE")
            self._cleanup_orphan_raw(dispatch_id)
            return self._public_event(event)

    def record_definitely_not_dispatched(self, dispatch_id: str, *, evidence_sha256: str) -> dict:
        """Reject caller assertions; only runner-owned pre-invocation proof can reopen."""
        self._journal_path(dispatch_id)
        raise RunnerError("ACQ_RUNNER_NEGATIVE_EVIDENCE_UNTRUSTED")

    def _record_preinvoke_failure(self, dispatch_id: str, code: str) -> dict:
        """Record runner-owned proof from a branch that precedes provider entry."""
        evidence = hashlib.sha256(self._encoded({
            "runner_version": RUNNER_VERSION,
            "dispatch_id": dispatch_id,
            "code": code,
            "proof_class": "runner_preinvoke",
        })).hexdigest()
        event = self._append(
            dispatch_id, DispatchState.DEFINITELY_NOT_DISPATCHED,
            evidence_sha256=evidence, code=code, proof_class="runner_preinvoke",
        )
        return self._public_event(event)

    @contextmanager
    def _provider_deadline(self, absolute_deadline: float):
        """Enforce a runner-owned wall-clock timeout without leaving a worker alive."""
        if threading.current_thread() is not threading.main_thread():
            raise RunnerError("ACQ_RUNNER_TIMEOUT_BOUNDARY_UNAVAILABLE")
        remaining = absolute_deadline - self.monotonic()
        if remaining <= 0:
            raise _ProviderDeadline
        previous_handler = signal.getsignal(signal.SIGALRM)

        def expired(_signum, _frame):
            raise _ProviderDeadline

        signal.signal(signal.SIGALRM, expired)
        previous_timer = signal.setitimer(signal.ITIMER_REAL, remaining)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)
            signal.signal(signal.SIGALRM, previous_handler)

    def invoke(self, dispatch_id: str, *, call_deadline: float) -> dict:
        """Invoke the injected provider once and privately capture bounded bytes."""
        if (not isinstance(call_deadline, (int, float)) or isinstance(call_deadline, bool)
                or not math.isfinite(call_deadline)):
            raise RunnerError("ACQ_RUNNER_DEADLINE_INVALID")
        effective_deadline = min(float(call_deadline), self.run_deadline)
        with self._lock(dispatch_id):
            rows = self._read_events(dispatch_id)
            if not rows or rows[-1]["state"] != DispatchState.CLAIMED.value:
                raise RunnerError("ACQ_RUNNER_DISPATCH_FENCED")
            if self.monotonic() >= effective_deadline:
                self._record_preinvoke_failure(dispatch_id, "ACQ_RUNNER_DEADLINE_BEFORE_DISPATCH")
                raise RunnerError("ACQ_RUNNER_DEADLINE_BEFORE_DISPATCH")
            arguments = base64.b64decode(rows[0]["arguments_b64"], validate=True)
            self._append(dispatch_id, DispatchState.INVOCATION_STARTED,
                         absolute_deadline=effective_deadline,
                         configured_backend=self.configured_backend)

        response = None
        pending = None
        dispatch_raw_directory = None
        try:
            with self._provider_deadline(effective_deadline):
                response = self.provider(arguments, effective_deadline)
            if not isinstance(response, HostedProviderResponse):
                raise TypeError
            if (response.observed_backend is not None
                    and (not isinstance(response.observed_backend, str)
                         or _BACKEND_IDENTITY.fullmatch(response.observed_backend) is None)):
                raise TypeError
            dispatch_raw_directory = private_path(
                self.raw_directory / dispatch_id, create=True)
            fd, pending = tempfile.mkstemp(prefix=".raw-pending-", dir=dispatch_raw_directory)
            total = 0
            digest = hashlib.sha256()
            with os.fdopen(fd, "wb") as stream:
                for chunk in response.chunks:
                    if not isinstance(chunk, bytes):
                        raise TypeError
                    total += len(chunk)
                    if total > self.raw_byte_limit:
                        raise _RawLimit
                    stream.write(chunk)
                    digest.update(chunk)
                    if self.monotonic() >= effective_deadline:
                        raise _DeadlineAfterInvocation
                stream.flush()
                os.fsync(stream.fileno())
            raw = Path(pending).read_bytes()
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                raise _InvalidUtf8 from None
            raw_ref = save(dispatch_raw_directory, raw, suffix="bin")
            evidence = digest.hexdigest()
            with self._lock(dispatch_id):
                event = self._append(
                    dispatch_id, DispatchState.CAPTURED, evidence_sha256=evidence,
                    status="captured", raw_ref=raw_ref, raw_bytes=total,
                    configured_backend=self.configured_backend,
                    observed_backend=response.observed_backend,
                )
                dispatch_ref = self._save_dispatch_receipt(
                    dispatch_id, status="captured", observed_backend=response.observed_backend,
                )
            return self._receipt_event(event, dispatch_ref=dispatch_ref)
        except _RawLimit:
            return self._known_failure(dispatch_id, "ACQ_RUNNER_RAW_LIMIT_EXCEEDED")
        except _InvalidUtf8:
            return self._known_failure(dispatch_id, "HOST_WEB_BODY_UNPARSEABLE")
        except (_DeadlineAfterInvocation, _ProviderDeadline):
            self._possibly_dispatched(dispatch_id, "ACQ_RUNNER_DEADLINE_AFTER_DISPATCH")
            raise RunnerError("ACQ_RUNNER_DEADLINE_AFTER_DISPATCH") from None
        except Exception:
            self._possibly_dispatched(dispatch_id, "ACQ_RUNNER_PROVIDER_OUTCOME_UNKNOWN")
            raise RunnerError("ACQ_RUNNER_PROVIDER_OUTCOME_UNKNOWN") from None
        finally:
            if isinstance(response, HostedProviderResponse):
                close = getattr(response.chunks, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            if pending is not None:
                try:
                    os.unlink(pending)
                except FileNotFoundError:
                    pass
            if dispatch_raw_directory is not None:
                try:
                    dispatch_raw_directory.rmdir()
                except OSError:
                    pass

    def _save_dispatch_receipt(self, dispatch_id: str, *, status: str,
                               observed_backend: str | None) -> dict:
        """Persist a receipt bound to an immutable copy of the validated journal."""
        rows = self._read_events(dispatch_id)
        prepared, terminal = rows[0], rows[-1]
        identity = prepared.get("identity")
        if (not isinstance(identity, dict)
                or terminal.get("state") != DispatchState.CAPTURED.value
                or terminal.get("status") != status):
            raise RunnerError("ACQ_RUNNER_JOURNAL_INVALID")
        journal_ref = save(self.directory, {
            "kind": "acquisition_dispatch_journal_proof",
            "version": RUNNER_VERSION,
            "dispatch_id": dispatch_id,
            "journal_head_sha256": terminal["event_sha256"],
            "events": rows,
        })
        return save(self.directory, {
            "kind": "acquisition_dispatch_receipt",
            "version": RUNNER_VERSION,
            **identity,
            "invocation_started": True,
            "status": status,
            "provider_items": 1,
            "arguments_sha256": prepared.get("arguments_sha256"),
            "evidence_sha256": terminal.get("evidence_sha256"),
            "configured_backend": prepared.get("configured_backend"),
            "observed_backend": observed_backend,
            "journal_head_sha256": terminal["event_sha256"],
            "journal_ref": journal_ref,
        })

    def _known_failure(self, dispatch_id: str, code: str) -> dict:
        evidence = hashlib.sha256(code.encode()).hexdigest()
        with self._lock(dispatch_id):
            event = self._append(
                dispatch_id, DispatchState.CAPTURED, evidence_sha256=evidence,
                status="failed", code=code,
                configured_backend=self.configured_backend, observed_backend=None,
            )
            dispatch_ref = self._save_dispatch_receipt(
                dispatch_id, status="failed", observed_backend=None,
            )
        return self._receipt_event(event, dispatch_ref=dispatch_ref)

    def _possibly_dispatched(self, dispatch_id: str, code: str) -> None:
        with self._lock(dispatch_id):
            rows = self._read_events(dispatch_id)
            if rows and rows[-1]["state"] == DispatchState.INVOCATION_STARTED.value:
                self._append(dispatch_id, DispatchState.POSSIBLY_DISPATCHED, code=code)

    def _recover_incomplete_dispatches(self) -> None:
        """On restart, classify every persisted invocation-start as unknown."""
        recovered = []
        for path in self.directory.glob("dispatch-*.jsonl"):
            dispatch_id = path.name[len("dispatch-"):-len(".jsonl")]
            with self._lock(dispatch_id):
                rows = self._read_events(dispatch_id)
                if rows and rows[-1]["state"] == DispatchState.INVOCATION_STARTED.value:
                    self._append(
                        dispatch_id, DispatchState.POSSIBLY_DISPATCHED,
                        code="ACQ_RUNNER_RESTART_OUTCOME_UNKNOWN",
                    )
                    recovered.append(dispatch_id)
        for dispatch_id in recovered:
            self._cleanup_orphan_raw(dispatch_id)

    def recover_started(self, dispatch_id: str) -> dict:
        """Fence a crash-left invocation as unknown and remove uncommitted raw files."""
        with self._lock(dispatch_id):
            rows = self._read_events(dispatch_id)
            if not rows:
                raise RunnerError("ACQ_RUNNER_STATE")
            state = DispatchState(rows[-1]["state"])
            if state is DispatchState.INVOCATION_STARTED:
                event = self._append(
                    dispatch_id, DispatchState.POSSIBLY_DISPATCHED,
                    code="ACQ_RUNNER_RESTART_OUTCOME_UNKNOWN",
                )
            elif state is DispatchState.POSSIBLY_DISPATCHED:
                event = rows[-1]
            else:
                raise RunnerError("ACQ_RUNNER_STATE")
            self._cleanup_orphan_raw(dispatch_id)
            return self._public_event(event)

    def _cleanup_orphan_raw(self, dispatch_id: str) -> None:
        """Delete only one fenced dispatch's uncommitted private raw directory."""
        directory = self.raw_directory / dispatch_id
        if not directory.exists():
            return
        rows = self._read_events(dispatch_id)
        referenced = {Path(ref["path"]) for row in rows
                      if isinstance((ref := row.get("raw_ref")), dict)
                      and isinstance(ref.get("path"), str)}
        for path in directory.iterdir():
            if path.name.startswith(".raw-pending-") or (
                    path.suffix == ".bin" and path not in referenced):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        try:
            directory.rmdir()
        except OSError:
            pass

    def recover_captured_receipt(self, dispatch_id: str) -> dict:
        """Rebuild the immutable receipt after a captured-journal/write gap."""
        with self._lock(dispatch_id):
            rows = self._read_events(dispatch_id)
            if not rows or rows[-1]["state"] != DispatchState.CAPTURED.value:
                raise RunnerError("ACQ_RUNNER_STATE")
            terminal = rows[-1]
            dispatch_ref = self._save_dispatch_receipt(
                dispatch_id, status=terminal.get("status"),
                observed_backend=terminal.get("observed_backend"),
            )
            return self._receipt_event(terminal, dispatch_ref=dispatch_ref)

    def reconcile_captured(self, dispatch_id: str, *, evidence_sha256: str) -> dict:
        """Close an unknown fence from authoritative host evidence, without dispatch."""
        with self._lock(dispatch_id):
            rows = self._read_events(dispatch_id)
            if not rows or rows[-1]["state"] != DispatchState.POSSIBLY_DISPATCHED.value:
                raise RunnerError("ACQ_RUNNER_STATE")
            event = self._append(
                dispatch_id, DispatchState.CAPTURED, evidence_sha256=evidence_sha256,
                status="reconciled", configured_backend=self.configured_backend,
                observed_backend=None,
            )
            dispatch_ref = self._save_dispatch_receipt(
                dispatch_id, status="reconciled", observed_backend=None,
            )
            return self._receipt_event(event, dispatch_ref=dispatch_ref)

    def dispatch_binding(self, dispatch_id: str) -> dict:
        """Return a validated sanitized binding for driver-side handoff checks."""
        with self._lock(dispatch_id):
            rows = self._read_events(dispatch_id)
            if not rows:
                raise RunnerError("ACQ_RUNNER_STATE")
            first, last = rows[0], rows[-1]
            identity = first.get("identity")
            if not isinstance(identity, dict):
                raise RunnerError("ACQ_RUNNER_JOURNAL_INVALID")
            return {
                **identity,
                "arguments_sha256": first.get("arguments_sha256"),
                "configured_backend": first.get("configured_backend"),
                "state": last.get("state"),
                "status": last.get("status"),
                "evidence_sha256": last.get("evidence_sha256"),
            }

    def journal(self, dispatch_id: str) -> tuple[dict, ...]:
        """Return a sanitized journal projection with no arguments or private paths."""
        with self._lock(dispatch_id):
            return tuple(self._public_event(row) for row in self._read_events(dispatch_id))

    @staticmethod
    def _public_event(event: dict) -> dict:
        allowed = {
            "runner_version", "dispatch_id", "sequence", "state", "evidence_sha256",
            "event_sha256", "arguments_sha256", "configured_backend", "observed_backend",
            "absolute_deadline", "status", "code", "raw_bytes",
        }
        return {key: value for key, value in event.items() if key in allowed and value is not None}

    @staticmethod
    def _receipt_event(event: dict, *, dispatch_ref: dict) -> dict:
        receipt = HostedAcquisitionRunner._public_event(event)
        if event.get("raw_ref") is not None:
            receipt["raw_ref"] = event["raw_ref"]
        receipt["dispatch_ref"] = dispatch_ref
        return receipt


class _RawLimit(Exception):
    pass


class _InvalidUtf8(Exception):
    pass


class _DeadlineAfterInvocation(Exception):
    pass


class _ProviderDeadline(BaseException):
    """Internal timeout that ordinary provider Exception handlers cannot swallow."""

    pass
