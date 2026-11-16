"""Disabled common execution-window authority for the frozen R6 four-cell A/B.

The public surface accepts no clock, wall time, identity, root, or window input.
Live issuance is deliberately impossible until reviewed source constants are
changed to bind a final block grant and authentic G1/G2 authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

STATUS = "DISABLED_TEMPLATE_PENDING_FINAL_PINS_AND_FRESH_REVIEW"
BLOCK_DURATION_SECONDS = 1800
BLOCK_DURATION_NS = BLOCK_DURATION_SECONDS * 1_000_000_000
CONCURRENCY = 1
CELL_ORDER = (
    "R6DQ-7F2C91A4",
    "R6DQ-1B8E43D7",
    "R6DQ-C4A7095E",
    "R6DQ-92D6F0B3",
)
ADMISSION_OFFSETS_SECONDS = (450, 900, 1350, 1800)
CLOCK_PAIR_MAX_SPAN_NS = 50_000_000
WALL_MONOTONIC_MAX_DRIFT_NS = 1_000_000_000

WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE_PATH = Path(__file__).with_name("window-template-v1.json")
RUNTIME_RELATIVE_ROOT = Path("runtime/r6_common_execution_window_v1")
CANONICAL_ROOT = WORKSPACE_ROOT / RUNTIME_RELATIVE_ROOT
RECEIPT_NAME = "canonical-window-receipt-v1.json"
MARKER_NAME = "canonical-window-receipt-v1.commit.json"
RECEIPT_STAGE_NAME = ".canonical-window-receipt-v1.stage"
MARKER_STAGE_NAME = ".canonical-window-receipt-v1.commit.stage"
ACTIVE_NAME = "active-cell-v1.json"
TERMINAL_NAMES = tuple(f"terminal-cell-{index + 1}-v1.json" for index in range(4))

# These four constants are the only activation boundary. They intentionally
# remain absent. Populating them requires a separate reviewed source change.
ACTIVATION_ENABLED = False
FINAL_BLOCK_GRANT_PIN: Mapping[str, Any] | None = None
G1_AUTHORITY_PIN: Mapping[str, Any] | None = None
G2_AUTHORITY_PIN: Mapping[str, Any] | None = None
FRESH_REVIEW_PIN: Mapping[str, Any] | None = None
P0_V10_PIN: Mapping[str, Any] | None = None
RUNNER_V2_PIN: Mapping[str, Any] | None = None
PROVIDER_AUTHORITY_PIN: Mapping[str, Any] | None = None
HUMAN_AUTHORITY_PIN: Mapping[str, Any] | None = None

_ID_RE = re.compile(r"^(block|window|job|slot|attempt|operation)_[A-Za-z0-9_-]{32,}$")
_PROCESS_INSTANCE_TOKEN = hashlib.sha256(
    f"{os.getpid()}:{time.monotonic_ns()}:{time.time_ns()}".encode("ascii")
).hexdigest()


class WindowError(RuntimeError):
    """Fail-closed protocol error with a stable machine code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise WindowError(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise WindowError("CANONICAL_JSON_INVALID") from None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw: bytes, code: str) -> Mapping[str, Any]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, WindowError):
        raise WindowError(code) from None
    _require(isinstance(value, dict), code)
    _require(canonical_bytes(value) == raw, code + "_NONCANONICAL")
    return value


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> Mapping[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise WindowError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _artifact_ref(path: str, raw: bytes) -> dict[str, Any]:
    return {"path": path, "bytes": len(raw), "sha256": _sha256(raw)}


def _verify_ref(root: Path, ref: Mapping[str, Any], code: str) -> None:
    _require(set(ref) == {"path", "bytes", "sha256"}, code + "_SHAPE")
    relative = ref.get("path")
    _require(isinstance(relative, str) and relative and not relative.startswith("/"), code + "_PATH")
    _require(".." not in Path(relative).parts, code + "_PATH")
    target = root / relative
    try:
        before = os.lstat(target)
    except OSError:
        raise WindowError(code + "_MISSING") from None
    _require(stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode), code + "_TYPE")
    _require(before.st_uid == os.getuid(), code + "_OWNER")
    fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        current = os.fstat(fd)
        _require((before.st_dev, before.st_ino) == (current.st_dev, current.st_ino), code + "_RACE")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        _require((current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) ==
                 (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), code + "_RACE")
    finally:
        os.close(fd)
    _require(ref.get("bytes") == len(raw), code + "_BYTES")
    _require(ref.get("sha256") == _sha256(raw), code + "_HASH")


def _validate_template(value: Mapping[str, Any]) -> None:
    expected = {
        "version", "status", "activation", "provider_free", "countable",
        "block_duration_seconds", "concurrency", "cell_order",
        "admission_offsets_seconds", "clock", "publication", "source_pins",
        "provider_binary_identities", "pending_pins", "effects", "seal",
    }
    _require(set(value) == expected, "TEMPLATE_FIELDS")
    _require(value["version"] == "r6-common-execution-window-template-v1", "TEMPLATE_VERSION")
    _require(value["status"] == STATUS and value["activation"] is False, "TEMPLATE_STATUS")
    _require(value["provider_free"] is True and value["countable"] is False, "TEMPLATE_SCOPE")
    _require(value["block_duration_seconds"] == BLOCK_DURATION_SECONDS, "TEMPLATE_DURATION")
    _require(value["concurrency"] == CONCURRENCY, "TEMPLATE_CONCURRENCY")
    _require(value["cell_order"] == list(CELL_ORDER), "TEMPLATE_ORDER")
    _require(value["admission_offsets_seconds"] == list(ADMISSION_OFFSETS_SECONDS), "TEMPLATE_DEADLINES")
    clock = value["clock"]
    _require(isinstance(clock, dict) and clock == {
        "source": "internal-system-utc-monotonic-pair",
        "caller_injection": "FORBIDDEN",
        "rollback": "DENY",
        "jump": "DENY",
        "max_pair_span_ns": CLOCK_PAIR_MAX_SPAN_NS,
        "max_wall_monotonic_drift_ns": WALL_MONOTONIC_MAX_DRIFT_NS,
    }, "TEMPLATE_CLOCK")
    publication = value["publication"]
    _require(isinstance(publication, dict), "TEMPLATE_PUBLICATION")
    _require(publication == {
        "root": RUNTIME_RELATIVE_ROOT.as_posix(),
        "root_mode": "0700",
        "receipt": RECEIPT_NAME,
        "receipt_mode": "0600",
        "commit_marker": MARKER_NAME,
        "commit_marker_last": True,
        "no_replace": True,
        "single_issuance": True,
        "extension": "FORBIDDEN",
        "reissue": "FORBIDDEN",
        "replay": "FORBIDDEN",
    }, "TEMPLATE_PUBLICATION")
    pins = value["source_pins"]
    _require(isinstance(pins, list) and len(pins) == 11, "TEMPLATE_SOURCE_PINS")
    for index, pin in enumerate(pins):
        _require(isinstance(pin, dict), f"TEMPLATE_SOURCE_PIN_{index}")
        _verify_ref(WORKSPACE_ROOT, pin, f"SOURCE_PIN_{index}")
    identities = value["provider_binary_identities"]
    _require(isinstance(identities, dict) and set(identities) == {"claude_cli", "codex_cli"}, "TEMPLATE_BINARIES")
    for name, identity in identities.items():
        _require(isinstance(identity, dict) and set(identity) == {"path", "bytes", "sha256"}, "BINARY_IDENTITY_" + name)
        _require(isinstance(identity["path"], str) and identity["path"].startswith("/"), "BINARY_PATH_" + name)
        _require(type(identity["bytes"]) is int and identity["bytes"] > 0, "BINARY_BYTES_" + name)
        _require(isinstance(identity["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", identity["sha256"]) is not None, "BINARY_HASH_" + name)
    _require(value["pending_pins"] == ["final_reviewed_block_grant", "authentic_g1_authority", "authentic_g2_authority", "p0_v10", "runner_v2", "provider_authority", "human_authority", "fresh_independent_review"], "TEMPLATE_PENDING")
    _require(value["effects"] == {"provider": 0, "credential": 0, "network": 0, "email": 0, "business": 0, "host": 0, "bytedcli": 0}, "TEMPLATE_EFFECTS")
    seal = value["seal"]
    _require(isinstance(seal, dict) and set(seal) == {"bytes", "sha256"}, "TEMPLATE_SEAL")
    body = dict(value)
    del body["seal"]
    raw = canonical_bytes(body)
    _require(seal == {"bytes": len(raw), "sha256": _sha256(raw)}, "TEMPLATE_SEAL_INVALID")


def prepare_window_template() -> dict[str, Any]:
    """Verify and return the immutable disabled template; performs no writes."""
    try:
        raw = TEMPLATE_PATH.read_bytes()
    except OSError:
        raise WindowError("TEMPLATE_MISSING") from None
    value = _strict_json(raw, "TEMPLATE_JSON")
    _validate_template(value)
    return copy.deepcopy(dict(value))


def _verify_binary_identities(template: Mapping[str, Any]) -> None:
    for name, identity in template["provider_binary_identities"].items():
        path = Path(identity["path"])
        try:
            before = os.lstat(path)
        except OSError:
            raise WindowError("BINARY_MISSING_" + name) from None
        _require(stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode), "BINARY_TYPE_" + name)
        _require(before.st_uid == os.getuid(), "BINARY_OWNER_" + name)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            current = os.fstat(fd)
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(fd, 4 * 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
            after = os.fstat(fd)
            _require((current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) ==
                     (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "BINARY_RACE_" + name)
        finally:
            os.close(fd)
        _require(total == identity["bytes"] and digest.hexdigest() == identity["sha256"], "BINARY_DRIFT_" + name)


@dataclass(frozen=True)
class ClockPair:
    wall_utc_ns: int
    monotonic_ns: int
    pair_span_ns: int


def _trusted_clock_pair() -> ClockPair:
    before = time.monotonic_ns()
    wall = time.time_ns()
    after = time.monotonic_ns()
    _require(after >= before, "MONOTONIC_ROLLBACK")
    span = after - before
    _require(span <= CLOCK_PAIR_MAX_SPAN_NS, "CLOCK_PAIR_SPAN")
    return ClockPair(wall_utc_ns=wall, monotonic_ns=before + span // 2, pair_span_ns=span)


def _new_id(kind: str) -> str:
    value = f"{kind}_{secrets.token_urlsafe(24)}"
    _require(_ID_RE.fullmatch(value) is not None, "INTERNAL_ID_INVALID")
    return value


def _activation_preflight() -> dict[str, Any]:
    _require(ACTIVATION_ENABLED is True, STATUS)
    _require(FINAL_BLOCK_GRANT_PIN is not None, "FINAL_BLOCK_GRANT_MISSING")
    _require(G1_AUTHORITY_PIN is not None, "G1_AUTHORITY_MISSING")
    _require(G2_AUTHORITY_PIN is not None, "G2_AUTHORITY_MISSING")
    _require(FRESH_REVIEW_PIN is not None, "FRESH_REVIEW_MISSING")
    _require(P0_V10_PIN is not None, "P0_V10_MISSING")
    _require(RUNNER_V2_PIN is not None, "RUNNER_V2_MISSING")
    _require(PROVIDER_AUTHORITY_PIN is not None, "PROVIDER_AUTHORITY_MISSING")
    _require(HUMAN_AUTHORITY_PIN is not None, "HUMAN_AUTHORITY_MISSING")
    template = prepare_window_template()
    _verify_binary_identities(template)
    return template


def _build_live_receipt(template: Mapping[str, Any], pair: ClockPair) -> dict[str, Any]:
    """Activation-only builder. Provider-free tests must never call this."""
    block_id = _new_id("block")
    window_id = _new_id("window")
    jobs = []
    for index, cell_id in enumerate(CELL_ORDER):
        jobs.append({
            "ordinal": index + 1,
            "cell_id": cell_id,
            "job_id": _new_id("job"),
            "slot_id": _new_id("slot"),
            "attempt_id": _new_id("attempt"),
            "operation_id": _new_id("operation"),
            "admission_deadline_utc_ns": pair.wall_utc_ns + ADMISSION_OFFSETS_SECONDS[index] * 1_000_000_000,
            "admission_deadline_monotonic_ns": pair.monotonic_ns + ADMISSION_OFFSETS_SECONDS[index] * 1_000_000_000,
        })
    body: dict[str, Any] = {
        "version": "r6-common-execution-window-receipt-v1",
        "status": "ISSUED",
        "immutable": True,
        "block_id": block_id,
        "window_id": window_id,
        "root": RUNTIME_RELATIVE_ROOT.as_posix(),
        "block_duration_seconds": BLOCK_DURATION_SECONDS,
        "concurrency": CONCURRENCY,
        "cell_order": list(CELL_ORDER),
        "start_utc_ns": pair.wall_utc_ns,
        "deadline_utc_ns": pair.wall_utc_ns + BLOCK_DURATION_NS,
        "start_monotonic_ns": pair.monotonic_ns,
        "deadline_monotonic_ns": pair.monotonic_ns + BLOCK_DURATION_NS,
        "clock_pair_span_ns": pair.pair_span_ns,
        "issuer_pid": os.getpid(),
        "issuer_process_token": _PROCESS_INSTANCE_TOKEN,
        "jobs": jobs,
        "template_sha256": template["seal"]["sha256"],
        "authority_pins": {
            "final_block_grant": dict(FINAL_BLOCK_GRANT_PIN or {}),
            "g1": dict(G1_AUTHORITY_PIN or {}),
            "g2": dict(G2_AUTHORITY_PIN or {}),
            "fresh_review": dict(FRESH_REVIEW_PIN or {}),
            "p0_v10": dict(P0_V10_PIN or {}),
            "runner_v2": dict(RUNNER_V2_PIN or {}),
            "provider_authority": dict(PROVIDER_AUTHORITY_PIN or {}),
            "human_authority": dict(HUMAN_AUTHORITY_PIN or {}),
        },
        "reissue_allowed": False,
        "extension_allowed": False,
        "replay_allowed": False,
    }
    raw = canonical_bytes(body)
    body["seal"] = {"bytes": len(raw), "sha256": _sha256(raw)}
    return body


def _validate_live_receipt(value: Mapping[str, Any]) -> None:
    required = {
        "version", "status", "immutable", "block_id", "window_id", "root",
        "block_duration_seconds", "concurrency", "cell_order", "start_utc_ns",
        "deadline_utc_ns", "start_monotonic_ns", "deadline_monotonic_ns",
        "clock_pair_span_ns", "issuer_pid", "issuer_process_token", "jobs",
        "template_sha256", "authority_pins", "reissue_allowed",
        "extension_allowed", "replay_allowed", "seal",
    }
    _require(set(value) == required, "WINDOW_RECEIPT_FIELDS")
    _require(value["version"] == "r6-common-execution-window-receipt-v1", "WINDOW_RECEIPT_VERSION")
    _require(value["status"] == "ISSUED" and value["immutable"] is True, "WINDOW_RECEIPT_STATUS")
    for key, kind in (("block_id", "block"), ("window_id", "window")):
        _require(isinstance(value[key], str) and value[key].startswith(kind + "_") and _ID_RE.fullmatch(value[key]), "WINDOW_RECEIPT_ID")
    _require(value["root"] == RUNTIME_RELATIVE_ROOT.as_posix(), "WINDOW_ROOT")
    _require(value["block_duration_seconds"] == BLOCK_DURATION_SECONDS, "WINDOW_DURATION")
    _require(value["concurrency"] == CONCURRENCY, "WINDOW_CONCURRENCY")
    _require(value["cell_order"] == list(CELL_ORDER), "WINDOW_ORDER")
    for key in ("start_utc_ns", "deadline_utc_ns", "start_monotonic_ns", "deadline_monotonic_ns"):
        _require(type(value[key]) is int and value[key] >= 0, "WINDOW_TIME")
    _require(value["deadline_utc_ns"] - value["start_utc_ns"] == BLOCK_DURATION_NS, "WINDOW_WALL_DURATION")
    _require(value["deadline_monotonic_ns"] - value["start_monotonic_ns"] == BLOCK_DURATION_NS, "WINDOW_MONOTONIC_DURATION")
    _require(type(value["clock_pair_span_ns"]) is int and 0 <= value["clock_pair_span_ns"] <= CLOCK_PAIR_MAX_SPAN_NS, "WINDOW_PAIR_SPAN")
    _require(type(value["issuer_pid"]) is int and value["issuer_pid"] > 0, "WINDOW_PID")
    _require(isinstance(value["issuer_process_token"], str) and re.fullmatch(r"[0-9a-f]{64}", value["issuer_process_token"]), "WINDOW_PROCESS_TOKEN")
    jobs = value["jobs"]
    _require(isinstance(jobs, list) and len(jobs) == 4, "WINDOW_JOBS")
    for index, job in enumerate(jobs):
        expected_fields = {"ordinal", "cell_id", "job_id", "slot_id", "attempt_id", "operation_id", "admission_deadline_utc_ns", "admission_deadline_monotonic_ns"}
        _require(isinstance(job, dict) and set(job) == expected_fields, "WINDOW_JOB_FIELDS")
        _require(job["ordinal"] == index + 1 and job["cell_id"] == CELL_ORDER[index], "WINDOW_JOB_ORDER")
        for key, kind in (("job_id", "job"), ("slot_id", "slot"), ("attempt_id", "attempt"), ("operation_id", "operation")):
            _require(isinstance(job[key], str) and job[key].startswith(kind + "_") and _ID_RE.fullmatch(job[key]), "WINDOW_JOB_ID")
        offset_ns = ADMISSION_OFFSETS_SECONDS[index] * 1_000_000_000
        _require(job["admission_deadline_utc_ns"] == value["start_utc_ns"] + offset_ns, "WINDOW_JOB_WALL_DEADLINE")
        _require(job["admission_deadline_monotonic_ns"] == value["start_monotonic_ns"] + offset_ns, "WINDOW_JOB_MONOTONIC_DEADLINE")
    _require(isinstance(value["template_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", value["template_sha256"]), "WINDOW_TEMPLATE_HASH")
    _require(isinstance(value["authority_pins"], dict) and set(value["authority_pins"]) == {"final_block_grant", "g1", "g2", "fresh_review", "p0_v10", "runner_v2", "provider_authority", "human_authority"}, "WINDOW_AUTHORITY")
    for name, pin in value["authority_pins"].items():
        _require(isinstance(pin, dict) and set(pin) == {"path", "bytes", "sha256"}, "WINDOW_AUTHORITY_PIN_" + name)
        _require(isinstance(pin["path"], str) and pin["path"] and not pin["path"].startswith("/") and ".." not in Path(pin["path"]).parts, "WINDOW_AUTHORITY_PATH_" + name)
        _require(type(pin["bytes"]) is int and pin["bytes"] > 0, "WINDOW_AUTHORITY_BYTES_" + name)
        _require(isinstance(pin["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]), "WINDOW_AUTHORITY_HASH_" + name)
    _require(value["reissue_allowed"] is False and value["extension_allowed"] is False and value["replay_allowed"] is False, "WINDOW_REPLAY_POLICY")
    seal = value["seal"]
    _require(isinstance(seal, dict) and set(seal) == {"bytes", "sha256"}, "WINDOW_SEAL")
    body = dict(value)
    del body["seal"]
    raw = canonical_bytes(body)
    _require(seal == {"bytes": len(raw), "sha256": _sha256(raw)}, "WINDOW_SEAL_INVALID")


def _full_write(fd: int, raw: bytes, write_fn: Callable[[int, bytes], int] = os.write) -> None:
    offset = 0
    while offset < len(raw):
        written = write_fn(fd, raw[offset:])
        _require(type(written) is int and 0 < written <= len(raw) - offset, "WRITE_ZERO_OR_INVALID")
        offset += written


def _fsync_dir(fd: int) -> None:
    os.fsync(fd)


def _verify_secure_dir(path: Path) -> os.stat_result:
    try:
        before = os.lstat(path)
    except OSError:
        raise WindowError("ROOT_MISSING") from None
    _require(stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode), "ROOT_TYPE")
    _require(before.st_uid == os.getuid(), "ROOT_OWNER")
    _require(stat.S_IMODE(before.st_mode) == 0o700, "ROOT_MODE")
    return before


def _open_secure_root(path: Path) -> int:
    before = _verify_secure_dir(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    current = os.fstat(fd)
    if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
        os.close(fd)
        raise WindowError("ROOT_RACE")
    return fd


def _read_secure_name_fd(root_fd: int, name: str) -> bytes:
    try:
        before = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        _require(stat.S_ISREG(before.st_mode), "ARTIFACT_TYPE")
        _require(before.st_uid == os.getuid(), "ARTIFACT_OWNER")
        _require(stat.S_IMODE(before.st_mode) == 0o600, "ARTIFACT_MODE")
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
        try:
            current = os.fstat(fd)
            _require((before.st_dev, before.st_ino) == (current.st_dev, current.st_ino), "ARTIFACT_RACE")
            parts: list[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                parts.append(chunk)
            raw = b"".join(parts)
            after = os.fstat(fd)
            _require((current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) ==
                     (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "ARTIFACT_RACE")
            return raw
        finally:
            os.close(fd)
    except FileNotFoundError:
        raise WindowError("ARTIFACT_MISSING") from None


def _read_secure_name(root: Path, name: str) -> bytes:
    root_fd = _open_secure_root(root)
    try:
        return _read_secure_name_fd(root_fd, name)
    finally:
        os.close(root_fd)


def _create_secure_root(path: Path) -> int:
    parent = path.parent
    parent_before = os.lstat(parent)
    _require(stat.S_ISDIR(parent_before.st_mode) and not stat.S_ISLNK(parent_before.st_mode), "ROOT_PARENT_TYPE")
    _require(parent_before.st_uid == os.getuid(), "ROOT_PARENT_OWNER")
    parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        _fsync_dir(parent_fd)
    finally:
        os.close(parent_fd)
    return _open_secure_root(path)


def _write_stage(root_fd: int, name: str, raw: bytes, write_fn: Callable[[int, bytes], int]) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=root_fd)
    try:
        _full_write(fd, raw, write_fn)
        os.fsync(fd)
        current = os.fstat(fd)
        _require(stat.S_ISREG(current.st_mode) and current.st_uid == os.getuid(), "STAGE_OWNER_TYPE")
        _require(stat.S_IMODE(current.st_mode) == 0o600 and current.st_size == len(raw), "STAGE_MODE_SIZE")
    finally:
        os.close(fd)
    _fsync_dir(root_fd)


def _reopen_verify_fd(root_fd: int, name: str, raw: bytes) -> None:
    actual = _read_secure_name_fd(root_fd, name)
    _require(len(actual) == len(raw) and _sha256(actual) == _sha256(raw), "REOPEN_HASH_MISMATCH")


def _crash(stage: str, crash_after: str | None) -> None:
    if stage == crash_after:
        raise WindowError("INJECTED_CRASH_" + stage.upper())


def _publish_at(
    root: Path,
    receipt: Mapping[str, Any],
    *,
    write_fn: Callable[[int, bytes], int] = os.write,
    crash_after: str | None = None,
) -> Mapping[str, Any]:
    """Private provider-free durability harness; never generates identifiers."""
    _validate_live_receipt(receipt)
    raw = canonical_bytes(receipt)
    root_fd = _create_secure_root(root)
    try:
        names = set(os.listdir(root_fd))
        _require(not names.intersection({RECEIPT_NAME, MARKER_NAME, RECEIPT_STAGE_NAME, MARKER_STAGE_NAME}), "SINGLE_ISSUANCE_ONLY")
        _write_stage(root_fd, RECEIPT_STAGE_NAME, raw, write_fn)
        _crash("receipt_stage_fsynced", crash_after)
        _reopen_verify_fd(root_fd, RECEIPT_STAGE_NAME, raw)
        os.link(RECEIPT_STAGE_NAME, RECEIPT_NAME, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
        _fsync_dir(root_fd)
        _crash("receipt_published", crash_after)
        _reopen_verify_fd(root_fd, RECEIPT_NAME, raw)
        os.unlink(RECEIPT_STAGE_NAME, dir_fd=root_fd)
        _fsync_dir(root_fd)
        marker_body = {
            "version": "r6-common-execution-window-commit-v1",
            "receipt": RECEIPT_NAME,
            "receipt_bytes": len(raw),
            "receipt_sha256": _sha256(raw),
            "committed": True,
        }
        marker_raw = canonical_bytes(marker_body)
        _write_stage(root_fd, MARKER_STAGE_NAME, marker_raw, write_fn)
        _crash("marker_stage_fsynced", crash_after)
        _reopen_verify_fd(root_fd, MARKER_STAGE_NAME, marker_raw)
        os.link(MARKER_STAGE_NAME, MARKER_NAME, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
        _fsync_dir(root_fd)
        _crash("marker_published", crash_after)
        _reopen_verify_fd(root_fd, MARKER_NAME, marker_raw)
        os.unlink(MARKER_STAGE_NAME, dir_fd=root_fd)
        _fsync_dir(root_fd)
    except BaseException:
        raise
    finally:
        os.close(root_fd)
    return _recover_at(root)


def _recover_at(root: Path) -> Mapping[str, Any]:
    root_fd = _open_secure_root(root)
    try:
        names = set(os.listdir(root_fd))
        if MARKER_NAME not in names:
            if names.intersection({RECEIPT_NAME, RECEIPT_STAGE_NAME, MARKER_STAGE_NAME}):
                raise WindowError("INCOMPLETE_WINDOW_NO_REISSUE")
            raise WindowError("WINDOW_NOT_ISSUED")
        _require(RECEIPT_NAME in names, "COMMIT_WITHOUT_RECEIPT")
        marker_raw = _read_secure_name_fd(root_fd, MARKER_NAME)
        marker = _strict_json(marker_raw, "COMMIT_JSON")
        _require(set(marker) == {"version", "receipt", "receipt_bytes", "receipt_sha256", "committed"}, "COMMIT_FIELDS")
        _require(marker["version"] == "r6-common-execution-window-commit-v1" and marker["receipt"] == RECEIPT_NAME and marker["committed"] is True, "COMMIT_CONTENT")
        receipt_raw = _read_secure_name_fd(root_fd, RECEIPT_NAME)
        _require(marker["receipt_bytes"] == len(receipt_raw) and marker["receipt_sha256"] == _sha256(receipt_raw), "COMMIT_RECEIPT_MISMATCH")
        receipt = _strict_json(receipt_raw, "WINDOW_RECEIPT_JSON")
        _validate_live_receipt(receipt)
        return receipt
    finally:
        os.close(root_fd)


def issue_live_window() -> dict[str, Any]:
    """Issue once at the fixed root; currently hard-disabled before clocks/IDs/I/O."""
    template = _activation_preflight()
    pair = _trusted_clock_pair()
    receipt = _build_live_receipt(template, pair)
    return dict(_publish_at(CANONICAL_ROOT, receipt))


def recover_live_window() -> dict[str, Any]:
    """Recover the exact committed receipt; never issues or repairs a window."""
    return dict(_recover_at(CANONICAL_ROOT))


def _validate_clock(receipt: Mapping[str, Any], pair: ClockPair) -> None:
    _require(pair.monotonic_ns >= receipt["start_monotonic_ns"], "MONOTONIC_ROLLBACK_OR_REBOOT")
    elapsed = pair.monotonic_ns - receipt["start_monotonic_ns"]
    expected_wall = receipt["start_utc_ns"] + elapsed
    drift = pair.wall_utc_ns - expected_wall
    _require(abs(drift) <= WALL_MONOTONIC_MAX_DRIFT_NS, "WALL_CLOCK_JUMP")
    _require(receipt["start_utc_ns"] <= pair.wall_utc_ns <= receipt["deadline_utc_ns"], "WALL_WINDOW_BOUNDS")
    _require(pair.monotonic_ns <= receipt["deadline_monotonic_ns"], "MONOTONIC_WINDOW_EXPIRED")


def _validate_terminal(terminal: Mapping[str, Any], receipt: Mapping[str, Any], index: int) -> None:
    expected = {"version", "window_id", "cell_id", "ordinal", "job_id", "slot_id", "attempt_id", "operation_id", "terminal_state", "immutable", "seal"}
    _require(set(terminal) == expected, "TERMINAL_FIELDS")
    _require(terminal["version"] == "r6-common-execution-window-terminal-v1", "TERMINAL_VERSION")
    job = receipt["jobs"][index]
    for key in ("cell_id", "ordinal", "job_id", "slot_id", "attempt_id", "operation_id"):
        _require(terminal[key] == job[key], "TERMINAL_IDENTITY")
    _require(terminal["window_id"] == receipt["window_id"], "TERMINAL_WINDOW")
    _require(terminal["terminal_state"] in {"PASS", "FAIL", "STOP", "MALFORMED", "MISSING", "UNKNOWN"}, "TERMINAL_STATE")
    _require(terminal["immutable"] is True, "TERMINAL_IMMUTABLE")
    body = dict(terminal)
    seal = body.pop("seal")
    raw = canonical_bytes(body)
    _require(seal == {"bytes": len(raw), "sha256": _sha256(raw)}, "TERMINAL_SEAL")


def _evaluate_admission(
    receipt: Mapping[str, Any],
    terminals: Sequence[Mapping[str, Any]],
    active: Mapping[str, Any] | None,
    pair: ClockPair,
    *,
    current_pid: int,
    process_token: str,
) -> dict[str, Any]:
    """Private pure verifier used by provider-free tests; public API injects none."""
    _validate_live_receipt(receipt)
    _validate_clock(receipt, pair)
    _require(len(terminals) <= 4, "TOO_MANY_TERMINALS")
    unknown_seen = False
    for index, terminal in enumerate(terminals):
        _validate_terminal(terminal, receipt, index)
        if terminal["terminal_state"] == "UNKNOWN":
            unknown_seen = True
    _require(not unknown_seen or len(terminals) == 4, "UNKNOWN_FORBIDS_LATER_CELLS")
    if active is not None:
        _require(set(active) == {"version", "window_id", "ordinal", "cell_id", "pid", "process_token", "immutable"}, "ACTIVE_FIELDS")
        _require(active["version"] == "r6-common-execution-window-active-v1" and active["immutable"] is True, "ACTIVE_VERSION")
        _require(active["window_id"] == receipt["window_id"], "ACTIVE_WINDOW")
        ordinal = active["ordinal"]
        _require(type(ordinal) is int and 1 <= ordinal <= 4, "ACTIVE_ORDINAL")
        _require(active["cell_id"] == CELL_ORDER[ordinal - 1], "ACTIVE_ORDER")
        if active["pid"] == current_pid and active["process_token"] != process_token:
            raise WindowError("PID_REUSE_UNKNOWN")
        if active["pid"] != current_pid:
            raise WindowError("ACTIVE_PROCESS_RESTART_UNKNOWN")
        raise WindowError("CONCURRENCY_ONE_ACTIVE")
    index = len(terminals)
    _require(index < 4, "WINDOW_COMPLETE")
    if index > 0:
        _require(terminals[index - 1]["terminal_state"] != "UNKNOWN", "UNKNOWN_FORBIDS_LATER_CELLS")
    job = receipt["jobs"][index]
    _require(pair.monotonic_ns <= job["admission_deadline_monotonic_ns"], "CELL_MONOTONIC_DEADLINE")
    _require(pair.wall_utc_ns <= job["admission_deadline_utc_ns"], "CELL_WALL_DEADLINE")
    return {
        "version": "r6-common-execution-window-admission-v1",
        "decision": "ADMIT",
        "window_id": receipt["window_id"],
        "ordinal": index + 1,
        "cell_id": CELL_ORDER[index],
        "job_id": job["job_id"],
        "slot_id": job["slot_id"],
        "attempt_id": job["attempt_id"],
        "operation_id": job["operation_id"],
        "concurrency": 1,
        "replay_allowed": False,
    }


def _load_terminals(receipt: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    terminals: list[Mapping[str, Any]] = []
    for name in TERMINAL_NAMES:
        try:
            raw = _read_secure_name(CANONICAL_ROOT, name)
        except WindowError as exc:
            if exc.code == "ARTIFACT_MISSING":
                break
            raise
        terminals.append(_strict_json(raw, "TERMINAL_JSON"))
    return terminals


def _load_active() -> Mapping[str, Any] | None:
    try:
        return _strict_json(_read_secure_name(CANONICAL_ROOT, ACTIVE_NAME), "ACTIVE_JSON")
    except WindowError as exc:
        if exc.code == "ARTIFACT_MISSING":
            return None
        raise


def validate_live_window() -> dict[str, Any]:
    """Validate the committed fixed-root window against internal trusted time."""
    receipt = recover_live_window()
    pair = _trusted_clock_pair()
    _validate_clock(receipt, pair)
    return receipt


def admit_next_cell() -> dict[str, Any]:
    """Validate the next fixed cell; accepts no caller clock/root/identity."""
    receipt = recover_live_window()
    pair = _trusted_clock_pair()
    return _evaluate_admission(
        receipt,
        _load_terminals(receipt),
        _load_active(),
        pair,
        current_pid=os.getpid(),
        process_token=_PROCESS_INSTANCE_TOKEN,
    )
