"""Fixed-root append-only terminal authority for the disabled v8 candidate.

The ledger is opened only through held directory descriptors.  Every state change is
hash chained, fully synced, reread, then confirmed by a second claimable record.
An unconfirmed record or truncated tail permanently fences public terminal claims.
"""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Iterable, Optional

from .contracts import ContractError, canonical_bytes, validate_seal

STATE_PROTOCOL = "LOCKED_APPEND_ONLY_HASH_CHAIN_V1"
EXPECTED_UID = 501
ROOT_PATH = Path("/Users/bytedance/Desktop/Trading Agent/.job-runtime/r6-one-off-claude-live-integration-v8")
LEDGER_NAME = "terminal-generation-v8.ledger"
_ZERO = "0" * 64
_MAX_LEDGER_BYTES = 8 * 1024 * 1024
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC
_COMPONENTS = (
    ("Users", 0, 0o755, False),
    ("bytedance", 501, 0o750, False),
    ("Desktop", 501, 0o700, False),
    ("Trading Agent", 501, 0o755, False),
    (".job-runtime", 501, 0o700, True),
    ("r6-one-off-claude-live-integration-v8", 501, 0o700, True),
)


class NoTerminalClaimDurabilityError(RuntimeError):
    """A transition may be stored, but no exact claimable terminal was proved."""


class PreviousOutcomeUnknownError(RuntimeError):
    """A prior call left an unclaimable or truncated one-shot outcome."""


@dataclass(frozen=True)
class AuthorityRecord:
    generation_sha256: str
    sequence: int
    state: str
    claimable: bool
    baseline: dict
    poison: dict
    terminal: dict
    record_sha256: str


@dataclass
class _AuthorityRoot:
    fd: int
    path: Path
    created: bool

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> "_AuthorityRoot":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sync(fd: int) -> None:
    os.fsync(fd)
    full = getattr(fcntl, "F_FULLFSYNC", None)
    if full is not None:
        fcntl.fcntl(fd, full)


def _write_all(fd: int, raw: bytes) -> None:
    view = memoryview(raw)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("WRITE_ZERO")
        offset += written


def _validate_directory(fd: int, uid: int, mode: int, code: str) -> None:
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or
            stat.S_IMODE(info.st_mode) != mode):
        raise ContractError(code)


def _open_component(parent_fd: int, name: str, uid: int, mode: int,
                    allow_create: bool) -> tuple[int, bool]:
    created = False
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        if not allow_create:
            raise ContractError("STATE_ROOT_COMPONENT_ABSENT") from None
        try:
            os.mkdir(name, mode, dir_fd=parent_fd)
            created = True
            _sync(parent_fd)
        except FileExistsError:
            pass
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    try:
        _validate_directory(fd, uid, mode, "STATE_ROOT_COMPONENT_IDENTITY")
        if created:
            _sync(fd)
        return fd, created
    except BaseException:
        os.close(fd)
        raise


def _open_fixed_root(*, create: bool) -> _AuthorityRoot:
    fd = os.open("/", _DIR_FLAGS)
    created_final = False
    try:
        _validate_directory(fd, 0, 0o755, "STATE_ROOT_FILESYSTEM_IDENTITY")
        for index, (name, uid, mode, normally_creatable) in enumerate(_COMPONENTS):
            allow_create = create and normally_creatable
            child, made = _open_component(fd, name, uid, mode, allow_create)
            os.close(fd)
            fd = child
            if index == len(_COMPONENTS) - 1:
                created_final = made
        return _AuthorityRoot(fd, ROOT_PATH, created_final)
    except BaseException:
        os.close(fd)
        raise


def _ledger_info(fd: int, expected_uid: int) -> None:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid or
            stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        raise ContractError("STATE_LEDGER_IDENTITY")


def _open_ledger(root_fd: int, expected_uid: int, *, create: bool) -> tuple[int, bool]:
    created = False
    flags = _FILE_FLAGS
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(LEDGER_NAME, flags, 0o600, dir_fd=root_fd)
        created = create
    except FileExistsError:
        raise ContractError("STATE_LEDGER_ALREADY_EXISTS") from None
    except FileNotFoundError:
        raise ContractError("STATE_LEDGER_ABSENT") from None
    try:
        _ledger_info(fd, expected_uid)
        fcntl.flock(fd, fcntl.LOCK_EX)
        if created:
            os.fchmod(fd, 0o600)
            _sync(fd)
            _sync(root_fd)
            _ledger_info(fd, expected_uid)
        return fd, created
    except BaseException:
        os.close(fd)
        raise


def _read_bytes(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    size = 0
    while True:
        part = os.read(fd, 65536)
        if not part:
            break
        size += len(part)
        if size > _MAX_LEDGER_BYTES:
            raise ContractError("STATE_LEDGER_TOO_LARGE")
        chunks.append(part)
    return b"".join(chunks)


def _decode_seal(raw_value: object, expected_sha: object, code: str) -> dict:
    if type(raw_value) is not dict:
        raise ContractError(code + "_TYPE")
    raw = canonical_bytes(raw_value)
    if type(expected_sha) is not str or _sha(raw) != expected_sha:
        raise ContractError(code + "_HASH")
    validate_seal(raw_value)
    return raw_value


def _record_payload(sequence: int, previous: str, generation: str, state: str,
                    claimable: bool, baseline: dict, poison: dict,
                    terminal: dict) -> dict:
    return {
        "baseline": baseline,
        "baseline_sha256": _sha(canonical_bytes(baseline)),
        "claimable": claimable,
        "generation_sha256": generation,
        "poison": poison,
        "poison_sha256": _sha(canonical_bytes(poison)),
        "previous_record_sha256": previous,
        "protocol": STATE_PROTOCOL,
        "sequence": sequence,
        "state": state,
        "terminal": terminal,
        "terminal_sha256": _sha(canonical_bytes(terminal)),
        "version": 8,
    }


def _encode_record(payload: dict) -> tuple[bytes, str]:
    payload_raw = canonical_bytes(payload)
    record_sha = _sha(payload_raw)
    envelope = {"payload": payload, "record_sha256": record_sha}
    return canonical_bytes(envelope) + b"\n", record_sha


def _validate_transition(previous: Optional[AuthorityRecord], current: AuthorityRecord) -> None:
    if previous is None:
        if not (current.sequence == 1 and current.state == "UNKNOWN" and
                current.claimable is False):
            raise ContractError("STATE_LEDGER_INITIAL_TRANSITION")
        return
    if current.sequence != previous.sequence + 1:
        raise ContractError("STATE_LEDGER_SEQUENCE")
    same_terminal = (current.state == previous.state and
                     current.terminal == previous.terminal)
    if previous.claimable is False:
        if not (same_terminal and current.claimable is True):
            raise ContractError("STATE_LEDGER_UNCLAIMED_SUCCESSOR")
        return
    if current.claimable is not False:
        raise ContractError("STATE_LEDGER_TRANSITION_MUST_UNCLAIM")
    legal = ((previous.state == "UNKNOWN" and current.state in ("PASS", "POISONED")) or
             (previous.state == "PASS" and current.state == "POISONED"))
    if not legal:
        raise ContractError("STATE_LEDGER_ILLEGAL_TRANSITION")


def _parse_line(raw: bytes, previous: Optional[AuthorityRecord]) -> AuthorityRecord:
    try:
        value = json.loads(raw.decode("ascii", "strict"))
    except (UnicodeError, ValueError, TypeError):
        raise ContractError("STATE_LEDGER_JSON") from None
    if canonical_bytes(value) != raw:
        raise ContractError("STATE_LEDGER_CANONICAL")
    if type(value) is not dict or set(value) != {"payload", "record_sha256"}:
        raise ContractError("STATE_LEDGER_ENVELOPE")
    payload = value["payload"]
    keys = {"baseline", "baseline_sha256", "claimable", "generation_sha256",
            "poison", "poison_sha256", "previous_record_sha256", "protocol",
            "sequence", "state", "terminal", "terminal_sha256", "version"}
    if type(payload) is not dict or set(payload) != keys:
        raise ContractError("STATE_LEDGER_PAYLOAD")
    payload_raw = canonical_bytes(payload)
    record_sha = value["record_sha256"]
    if type(record_sha) is not str or _sha(payload_raw) != record_sha:
        raise ContractError("STATE_LEDGER_RECORD_HASH")
    expected_previous = previous.record_sha256 if previous else _ZERO
    if payload["previous_record_sha256"] != expected_previous:
        raise ContractError("STATE_LEDGER_CHAIN")
    if (payload["protocol"] != STATE_PROTOCOL or payload["version"] != 8 or
            type(payload["sequence"]) is not int or payload["sequence"] <= 0 or
            payload["state"] not in ("UNKNOWN", "PASS", "POISONED") or
            type(payload["claimable"]) is not bool):
        raise ContractError("STATE_LEDGER_HEADER")
    generation = payload["generation_sha256"]
    if (type(generation) is not str or len(generation) != 64 or
            any(char not in "0123456789abcdef" for char in generation)):
        raise ContractError("STATE_LEDGER_GENERATION")
    baseline = _decode_seal(payload["baseline"], payload["baseline_sha256"],
                            "STATE_BASELINE")
    poison = _decode_seal(payload["poison"], payload["poison_sha256"], "STATE_POISON")
    terminal = _decode_seal(payload["terminal"], payload["terminal_sha256"],
                            "STATE_TERMINAL")
    if (baseline["status"] != "UNKNOWN" or
            baseline["state_authority"]["state"] != "UNKNOWN" or
            poison["status"] != "UNKNOWN" or
            poison["state_authority"]["state"] != "POISONED"):
        raise ContractError("STATE_LEDGER_FALLBACKS")
    expected_status = "PASS" if payload["state"] == "PASS" else "UNKNOWN"
    if terminal["status"] != expected_status:
        raise ContractError("STATE_LEDGER_TERMINAL_STATUS")
    for seal in (baseline, poison, terminal):
        if seal["state_authority"]["generation_sha256"] != generation:
            raise ContractError("STATE_LEDGER_GENERATION_BINDING")
    if terminal["state_authority"]["state"] != payload["state"]:
        raise ContractError("STATE_LEDGER_STATE_BINDING")
    if previous is not None and (baseline != previous.baseline or poison != previous.poison or
                                 generation != previous.generation_sha256):
        raise ContractError("STATE_LEDGER_IMMUTABLE_GENERATION")
    record = AuthorityRecord(generation, payload["sequence"], payload["state"],
                             payload["claimable"], baseline, poison, terminal,
                             record_sha)
    _validate_transition(previous, record)
    return record


def _read_chain(fd: int, *, require_claimable: bool = True) -> list[AuthorityRecord]:
    raw = _read_bytes(fd)
    if not raw:
        raise ContractError("STATE_LEDGER_EMPTY")
    if not raw.endswith(b"\n"):
        raise PreviousOutcomeUnknownError("STATE_LEDGER_TRUNCATED_TAIL")
    records: list[AuthorityRecord] = []
    for line in raw.splitlines():
        if not line:
            raise ContractError("STATE_LEDGER_EMPTY_LINE")
        records.append(_parse_line(line, records[-1] if records else None))
    if require_claimable and not records[-1].claimable:
        raise PreviousOutcomeUnknownError("PREVIOUS_OUTCOME_UNKNOWN")
    return records


def _append_line(fd: int, raw: bytes) -> None:
    os.lseek(fd, 0, os.SEEK_END)
    _write_all(fd, raw)
    _sync(fd)


def _append_and_confirm(fd: int, current: Optional[AuthorityRecord], state: str,
                        terminal: dict, baseline: dict, poison: dict,
                        generation: str) -> AuthorityRecord:
    sequence = 1 if current is None else current.sequence + 1
    previous = _ZERO if current is None else current.record_sha256
    unclaimed_payload = _record_payload(sequence, previous, generation, state, False,
                                        baseline, poison, terminal)
    unclaimed_raw, unclaimed_sha = _encode_record(unclaimed_payload)
    transition_started = False
    try:
        transition_started = True
        _append_line(fd, unclaimed_raw)
        observed = _read_chain(fd, require_claimable=False)[-1]
        if (observed.record_sha256 != unclaimed_sha or observed.claimable is not False or
                observed.state != state or observed.terminal != terminal):
            raise ContractError("STATE_LEDGER_UNCLAIMED_READBACK")
        claimed_payload = _record_payload(sequence + 1, observed.record_sha256, generation,
                                          state, True, baseline, poison, terminal)
        claimed_raw, claimed_sha = _encode_record(claimed_payload)
        _append_line(fd, claimed_raw)
        proved = _read_chain(fd, require_claimable=True)[-1]
        if (proved.record_sha256 != claimed_sha or proved.state != state or
                proved.terminal != terminal):
            raise ContractError("STATE_LEDGER_CLAIMED_READBACK")
        return proved
    except BaseException as exc:
        if not transition_started:
            raise
        try:
            records = _read_chain(fd, require_claimable=False)
            latest = records[-1]
            if latest.claimable and latest.state == state and latest.terminal == terminal:
                return latest
            if current is not None and latest.claimable and latest == current:
                return latest
        except BaseException:
            pass
        raise NoTerminalClaimDurabilityError("NO_TERMINAL_CLAIM_DURABILITY") from exc


def _initialize(root_fd: int, generation_sha256: str, baseline: dict,
                poison: dict, expected_uid: int = EXPECTED_UID) -> AuthorityRecord:
    validate_seal(baseline)
    validate_seal(poison)
    fd, _ = _open_ledger(root_fd, expected_uid, create=True)
    try:
        if _read_bytes(fd):
            raise ContractError("STATE_LEDGER_NOT_EMPTY")
        return _append_and_confirm(fd, None, "UNKNOWN", baseline, baseline, poison,
                                   generation_sha256)
    finally:
        os.close(fd)


def _read(root_fd: int, expected_uid: int = EXPECTED_UID) -> AuthorityRecord:
    fd, _ = _open_ledger(root_fd, expected_uid, create=False)
    try:
        return _read_chain(fd, require_claimable=True)[-1]
    finally:
        os.close(fd)


def _commit(root_fd: int, generation_sha256: str, state: str, terminal: dict,
            expected_uid: int = EXPECTED_UID) -> AuthorityRecord:
    if state not in ("PASS", "POISONED"):
        raise ContractError("STATE_LEDGER_COMMIT_STATE")
    validate_seal(terminal)
    fd, _ = _open_ledger(root_fd, expected_uid, create=False)
    try:
        current = _read_chain(fd, require_claimable=True)[-1]
        if current.generation_sha256 != generation_sha256:
            raise ContractError("STATE_LEDGER_COMMIT_GENERATION")
        if current.state == state:
            if current.terminal != terminal:
                raise ContractError("STATE_LEDGER_TERMINAL_MISMATCH")
            return current
        legal = ((current.state == "UNKNOWN" and state in ("PASS", "POISONED")) or
                 (current.state == "PASS" and state == "POISONED"))
        if not legal:
            raise ContractError("STATE_LEDGER_ILLEGAL_TRANSITION")
        if state == "POISONED" and terminal != current.poison:
            raise ContractError("STATE_LEDGER_POISON_MISMATCH")
        if state == "PASS" and terminal["status"] != "PASS":
            raise ContractError("STATE_LEDGER_PASS_MISMATCH")
        return _append_and_confirm(fd, current, state, terminal, current.baseline,
                                   current.poison, current.generation_sha256)
    finally:
        os.close(fd)


def _poison(root_fd: int, record: AuthorityRecord,
            expected_uid: int = EXPECTED_UID) -> AuthorityRecord:
    return _commit(root_fd, record.generation_sha256, "POISONED", record.poison,
                   expected_uid)


def _entries(root_fd: int) -> tuple[str, ...]:
    return tuple(sorted(os.listdir(root_fd)))
