"""Recoverable reconciliation between shared Engine and mentor effect ledgers."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any

from shared.job_runtime.engine import Engine
from .contracts import WorkOrder, canonical_json_bytes, strict_json_loads
from .state import DurableSessionStore, _RECONCILIATION_CAPABILITY

UTC = timezone.utc
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_EVIDENCE_BYTES = 1_048_576


class ReconciliationError(RuntimeError):
    """Raised when the two durable ledgers cannot be reconciled consistently."""


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ReconciliationError(f"{label} is invalid")
    return value


def _at(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReconciliationError("reconciliation time must be timezone-aware")
    return value.astimezone(UTC)


def _evidence(workspace: Path, relative: str) -> tuple[str, str]:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ReconciliationError("evidence path is invalid")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise ReconciliationError("evidence path is invalid")
    current = workspace
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ReconciliationError("evidence path may not traverse a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(workspace)
        info = resolved.stat()
    except (OSError, ValueError) as exc:
        raise ReconciliationError("evidence file is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_EVIDENCE_BYTES:
        raise ReconciliationError("evidence file is invalid")
    return relative, hashlib.sha256(resolved.read_bytes()).hexdigest()


def _atomic(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    candidate = Path(temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(candidate, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        candidate.unlink(missing_ok=True)


@contextmanager
def _lock(path: Path):
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _attempt(engine: Engine, slot_id: str) -> dict[str, Any]:
    with engine._db() as db:  # same durable database; read-only query here
        row = db.execute(
            """SELECT s.slot_id,s.status slot_status,a.attempt_id,a.status attempt_status,a.receipt
               FROM slots s JOIN attempts a ON a.slot_id=s.slot_id
               WHERE s.slot_id=? ORDER BY a.attempt_no DESC LIMIT 1""",
            (slot_id,),
        ).fetchone()
    if row is None:
        raise ReconciliationError("engine slot or attempt is unavailable")
    receipt = None
    if row["receipt"]:
        try:
            receipt = strict_json_loads(row["receipt"])
        except Exception as exc:
            raise ReconciliationError("engine reconciliation receipt is invalid") from exc
    return {
        "slot_id": row["slot_id"],
        "slot_status": row["slot_status"],
        "attempt_id": row["attempt_id"],
        "attempt_status": row["attempt_status"],
        "receipt": receipt,
    }


def _receipt(journal: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_type": "mentor_engine_effect_reconciliation",
        "reconciliation_id": journal["reconciliation_id"],
        "work_order_id": journal["work_order_id"],
        "logical_session_id": journal["logical_session_id"],
        "slot_id": journal["slot_id"],
        "attempt_id": journal["attempt_id"],
        "effect_id": journal["effect_id"],
        "outcome": journal["outcome"],
        "evidence_path": journal["evidence_path"],
        "evidence_sha256": journal["evidence_sha256"],
    }


def reconcile_unknown(
    engine: Engine,
    store: DurableSessionStore,
    work_order: WorkOrder,
    *,
    reconciliation_id: str,
    slot_id: str,
    outcome: str,
    evidence_path: str,
    at: datetime,
) -> dict[str, Any]:
    """Resolve one unknown Engine attempt and its matching mentor pending effect.

    A private journal makes the two commits recoverable. Repeating the exact call
    resumes from its last durable phase; any identity, outcome, or evidence change
    fails before another ledger mutation.
    """

    if not isinstance(engine, Engine) or not isinstance(store, DurableSessionStore):
        raise ReconciliationError("engine and durable mentor store are required")
    workspace = Path(engine.workspace).resolve(strict=True)
    if store.workspace != workspace or work_order.workspace != workspace:
        raise ReconciliationError("engine, work order and mentor store must share a workspace")
    reconciliation_id = _identifier(reconciliation_id, "reconciliation_id")
    if outcome not in {"succeeded", "failed"}:
        raise ReconciliationError("outcome must be succeeded or failed")
    instant = _at(at)
    relative_evidence, evidence_sha256 = _evidence(workspace, evidence_path)
    attempt = _attempt(engine, slot_id)
    if attempt["attempt_id"] is None:
        raise ReconciliationError("engine attempt identity is unavailable")
    attempt_id = attempt["attempt_id"]

    root = workspace / ".job-runtime" / "mentor-reconciliations"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    journal_path = root / f"{reconciliation_id}.json"
    lock_path = root / f"{reconciliation_id}.lock"
    immutable = {
        "schema_version": 1,
        "reconciliation_id": reconciliation_id,
        "work_order_id": work_order.work_order_id,
        "logical_session_id": work_order.logical_session.logical_session_id,
        "slot_id": slot_id,
        "attempt_id": attempt_id,
        "effect_id": attempt_id,
        "outcome": outcome,
        "evidence_path": relative_evidence,
        "evidence_sha256": evidence_sha256,
    }
    with _lock(lock_path):
        if journal_path.exists():
            if journal_path.is_symlink():
                raise ReconciliationError("reconciliation journal may not be a symlink")
            try:
                journal = strict_json_loads(journal_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ReconciliationError("reconciliation journal is invalid") from exc
            if not isinstance(journal, dict) or any(journal.get(key) != value for key, value in immutable.items()):
                raise ReconciliationError("reconciliation identity, outcome, or evidence conflicts")
            if (
                set(journal) != set(immutable) | {"phase", "created_at", "updated_at"}
                or journal.get("phase") not in {"prepared", "engine_resolved", "completed"}
            ):
                raise ReconciliationError("reconciliation journal schema is invalid")
        else:
            head = store.load(work_order)
            if attempt["slot_status"] != "unknown" or attempt["attempt_status"] != "unknown":
                raise ReconciliationError("a new reconciliation requires an unknown engine attempt")
            if attempt_id not in head["pending_effects"]:
                raise ReconciliationError("engine attempt does not match a mentor pending effect")
            journal = {
                **immutable,
                "phase": "prepared",
                "created_at": instant.isoformat(),
                "updated_at": instant.isoformat(),
            }
            _atomic(journal_path, journal)

        expected_receipt = _receipt(journal)
        attempt = _attempt(engine, slot_id)
        if attempt["slot_status"] == "unknown" and attempt["attempt_status"] == "unknown":
            engine.resolve_unknown(slot_id, outcome, expected_receipt, instant)
        else:
            if (
                attempt["slot_status"] != outcome
                or attempt["attempt_status"] != outcome
                or attempt["receipt"] != expected_receipt
            ):
                raise ReconciliationError("engine ledger conflicts with shared reconciliation receipt")
        if journal["phase"] == "prepared":
            journal = {**journal, "phase": "engine_resolved", "updated_at": instant.isoformat()}
            _atomic(journal_path, journal)

        head = store.load(work_order)
        expected_resolution = {
            "reconciliation_id": reconciliation_id,
            "engine_slot_id": slot_id,
            "engine_attempt_id": attempt_id,
            "outcome": outcome,
            "evidence_sha256": evidence_sha256,
            "effect_state": "confirmed" if outcome == "succeeded" else "failed",
        }
        existing = next(
            (
                item for item in head["effect_resolutions"]
                if item["reconciliation_id"] == reconciliation_id or item["engine_attempt_id"] == attempt_id
            ),
            None,
        )
        if existing is None:
            store._resolve_effect_from_reconciliation(
                work_order,
                reconciliation_id=reconciliation_id,
                engine_slot_id=slot_id,
                engine_attempt_id=attempt_id,
                outcome=outcome,
                evidence_sha256=evidence_sha256,
                at=instant,
                capability=_RECONCILIATION_CAPABILITY,
            )
        elif existing != expected_resolution:
            raise ReconciliationError("mentor ledger conflicts with shared reconciliation receipt")
        if journal["phase"] != "completed":
            journal = {**journal, "phase": "completed", "updated_at": instant.isoformat()}
            _atomic(journal_path, journal)
        return json.loads(json.dumps(journal))
