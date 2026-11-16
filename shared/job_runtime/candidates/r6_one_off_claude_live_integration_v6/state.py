"""Durable generation authority for the provider-free Claude v6 candidate.

The SQLite row is the only terminal authority. Public markers are projections and
can never upgrade an UNKNOWN/POISONED generation. Exact terminal bytes are stored
before return and recovery never reconstructs a status from workspace contents.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
from typing import Callable

from .contracts import ContractError, canonical_bytes, validate_seal

STATE_PROTOCOL = "SQLITE_FULL_SYNC_GENERATION_AUTHORITY_V1"
AUTHORITY_DIR_NAME = "authority-v6"
AUTHORITY_DB_NAME = "terminal-generation-v6.sqlite3"
_SCHEMA = """CREATE TABLE terminal_authority (
 singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
 protocol TEXT NOT NULL,
 generation_sha256 TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('UNKNOWN','PASS','POISONED')),
 baseline BLOB NOT NULL,
 baseline_sha256 TEXT NOT NULL,
 poison BLOB NOT NULL,
 poison_sha256 TEXT NOT NULL,
 terminal BLOB NOT NULL,
 terminal_sha256 TEXT NOT NULL
)"""


@dataclass(frozen=True)
class AuthorityRecord:
    generation_sha256: str
    state: str
    baseline: dict
    poison: dict
    terminal: dict


def database_path(root: Path) -> Path:
    return Path(root) / AUTHORITY_DIR_NAME / AUTHORITY_DB_NAME


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _decode(raw: bytes, expected: str, code: str) -> dict:
    if type(raw) is not bytes or _sha(raw) != expected:
        raise ContractError(code + "_HASH")
    try:
        import json
        value = json.loads(raw.decode("ascii", "strict"))
    except (UnicodeError, ValueError, TypeError):
        raise ContractError(code + "_JSON") from None
    if canonical_bytes(value) != raw:
        raise ContractError(code + "_CANONICAL")
    validate_seal(value)
    return value


def _check_path(path: Path) -> None:
    if path.is_symlink():
        raise ContractError("STATE_AUTHORITY_SYMLINK")
    if path.exists() and not stat.S_ISREG(os.lstat(path).st_mode):
        raise ContractError("STATE_AUTHORITY_NOT_REGULAR")


def _connect(path: Path, *, create: bool) -> sqlite3.Connection:
    _check_path(path)
    if not create and not path.exists():
        raise ContractError("STATE_AUTHORITY_ABSENT")
    connection = sqlite3.connect(path, timeout=0.25, isolation_level=None)
    connection.execute("pragma trusted_schema=off")
    connection.execute("pragma foreign_keys=on")
    connection.execute("pragma journal_mode=delete")
    connection.execute("pragma synchronous=full")
    return connection


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def initialize(root: Path, generation_sha256: str, baseline: dict, poison: dict) -> AuthorityRecord:
    """Create the durable UNKNOWN generation before any provider-shaped effect."""
    root = Path(root)
    authority_dir = root / AUTHORITY_DIR_NAME
    authority_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(authority_dir, 0o700)
    path = database_path(root)
    if path.exists() or path.is_symlink():
        raise ContractError("STATE_AUTHORITY_ALREADY_EXISTS")
    baseline_raw = canonical_bytes(baseline)
    poison_raw = canonical_bytes(poison)
    validate_seal(baseline)
    validate_seal(poison)
    connection = _connect(path, create=True)
    try:
        connection.execute("begin immediate")
        connection.execute(_SCHEMA)
        connection.execute(
            "insert into terminal_authority values (1,?,?,?,?,?,?,?,?,?)",
            (STATE_PROTOCOL, generation_sha256, "UNKNOWN", baseline_raw,
             _sha(baseline_raw), poison_raw, _sha(poison_raw), baseline_raw,
             _sha(baseline_raw)),
        )
        connection.execute("pragma user_version=6")
        connection.execute("commit")
    except BaseException:
        try:
            connection.execute("rollback")
        except sqlite3.Error:
            pass
        raise
    finally:
        connection.close()
    _fsync_directory(authority_dir)
    return read(root)


def read(root: Path) -> AuthorityRecord:
    """Read exact stored terminal bytes; never infer terminal state from markers."""
    path = database_path(root)
    connection = _connect(path, create=False)
    try:
        if connection.execute("pragma user_version").fetchone() != (6,):
            raise ContractError("STATE_AUTHORITY_VERSION")
        schema = connection.execute(
            "select sql from sqlite_master where type='table' and name='terminal_authority'"
        ).fetchone()
        if schema != (_SCHEMA,):
            raise ContractError("STATE_AUTHORITY_SCHEMA")
        rows = connection.execute(
            "select protocol,generation_sha256,state,baseline,baseline_sha256,"
            "poison,poison_sha256,terminal,terminal_sha256 from terminal_authority"
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1:
        raise ContractError("STATE_AUTHORITY_CARDINALITY")
    (protocol, generation, state, baseline_raw, baseline_sha, poison_raw,
     poison_sha, terminal_raw, terminal_sha) = rows[0]
    if protocol != STATE_PROTOCOL or state not in ("UNKNOWN", "PASS", "POISONED"):
        raise ContractError("STATE_AUTHORITY_HEADER")
    if type(generation) is not str or len(generation) != 64 or any(
            char not in "0123456789abcdef" for char in generation):
        raise ContractError("STATE_AUTHORITY_GENERATION")
    baseline = _decode(baseline_raw, baseline_sha, "STATE_BASELINE")
    poison = _decode(poison_raw, poison_sha, "STATE_POISON")
    terminal = _decode(terminal_raw, terminal_sha, "STATE_TERMINAL")
    if baseline["status"] != "UNKNOWN" or poison["status"] != "UNKNOWN":
        raise ContractError("STATE_AUTHORITY_FALLBACK_STATUS")
    expected = {"UNKNOWN": "UNKNOWN", "POISONED": "UNKNOWN", "PASS": "PASS"}[state]
    if terminal["status"] != expected:
        raise ContractError("STATE_AUTHORITY_TERMINAL_STATUS")
    for seal in (baseline, poison, terminal):
        authority = seal["state_authority"]
        if authority["generation_sha256"] != generation:
            raise ContractError("STATE_AUTHORITY_GENERATION_BINDING")
    if terminal["state_authority"]["state"] != state:
        raise ContractError("STATE_AUTHORITY_STATE_BINDING")
    return AuthorityRecord(generation, state, baseline, poison, terminal)


def commit(root: Path, generation_sha256: str, state: str, terminal: dict) -> AuthorityRecord:
    """Atomically replace the exact terminal bytes for the same generation."""
    if state not in ("UNKNOWN", "PASS", "POISONED"):
        raise ContractError("STATE_AUTHORITY_COMMIT_STATE")
    validate_seal(terminal)
    raw = canonical_bytes(terminal)
    path = database_path(root)
    connection = _connect(path, create=False)
    try:
        connection.execute("begin immediate")
        current = connection.execute(
            "select generation_sha256,state from terminal_authority where singleton=1"
        ).fetchone()
        if current is None or current[0] != generation_sha256:
            raise ContractError("STATE_AUTHORITY_COMMIT_GENERATION")
        if current[1] == "POISONED" and state != "POISONED":
            raise ContractError("STATE_AUTHORITY_POISON_DOMINATES")
        connection.execute(
            "update terminal_authority set state=?,terminal=?,terminal_sha256=? "
            "where singleton=1 and generation_sha256=?",
            (state, raw, _sha(raw), generation_sha256),
        )
        connection.execute("commit")
    except BaseException:
        try:
            connection.execute("rollback")
        except sqlite3.Error:
            pass
        raise
    finally:
        connection.close()
    return read(root)


def poison(root: Path, record: AuthorityRecord) -> AuthorityRecord:
    """Persist the precomputed poison terminal; it dominates every projection."""
    return commit(root, record.generation_sha256, "POISONED", record.poison)


def reconcile_commit(
    root: Path,
    generation_sha256: str,
    state: str,
    terminal: dict,
    on_error: Callable[[AuthorityRecord], AuthorityRecord],
) -> AuthorityRecord:
    """Resolve commit ambiguity in the same call from the same authority.

    If commit raised after taking effect, exact readback returns that terminal. If it
    did not take effect, the caller-provided transition handles the stored state.
    """
    try:
        return commit(root, generation_sha256, state, terminal)
    except BaseException:
        observed = read(root)
        if observed.state == state and observed.terminal == terminal:
            return observed
        return on_error(observed)
