"""Durable one-time market-pilot authorization authority.

All paths are derived beneath a fixed private root; callers supply only opaque IDs.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

ROOT_PARTS = (".niulai-state", "reports", "research-sources", "market-pilot", "authorizations")
SCHEMA_VERSION = 1
MAX_LEDGER_BYTES = 64 * 1024
AUTH_ID = re.compile(r"mpa_[0-9a-f]{32}")
HEX64 = re.compile(r"[0-9a-f]{64}")
ATTEMPT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
UTC_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z")
TERMINAL = frozenset(("success", "failure", "unresolved"))


class AuthorizationError(ValueError):
    """Fixed codes only; never include private contents or paths."""


def _require(ok, code):
    if not ok:
        raise AuthorizationError(code)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _utc(value, code):
    _require(isinstance(value, str) and UTC_STAMP.fullmatch(value), code)
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise AuthorizationError(code) from None


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _receipt_fields(value):
    keys = {"schema_version", "authorization_id", "calibration_contract_sha256", "cohort_sha256", "created_at"}
    _require(isinstance(value, dict) and set(value) == keys, "AUTHORIZATION_SCHEMA_INVALID")
    _require(value["schema_version"] == SCHEMA_VERSION, "AUTHORIZATION_SCHEMA_INVALID")
    _require(isinstance(value["authorization_id"], str) and AUTH_ID.fullmatch(value["authorization_id"]), "AUTHORIZATION_ID_INVALID")
    _require(isinstance(value["calibration_contract_sha256"], str) and HEX64.fullmatch(value["calibration_contract_sha256"]), "AUTHORIZATION_CONTRACT_INVALID")
    _require(isinstance(value["cohort_sha256"], str) and HEX64.fullmatch(value["cohort_sha256"]), "AUTHORIZATION_COHORT_INVALID")
    _utc(value["created_at"], "AUTHORIZATION_TIMESTAMP_INVALID")
    return dict(value)


def authorization_sha256(receipt):
    return hashlib.sha256(_canonical(_receipt_fields(receipt))).hexdigest()


def query_sha256(query):
    return hashlib.sha256(_canonical(query)).hexdigest()


def symbols_sha256(symbols):
    return hashlib.sha256(_canonical(symbols)).hexdigest()


def _check_directory(path):
    st = os.lstat(path)
    _require(stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode), "AUTHORIZATION_DIRECTORY_INVALID")
    _require(st.st_uid == os.getuid(), "AUTHORIZATION_OWNER_INVALID")
    _require(stat.S_IMODE(st.st_mode) == 0o700, "AUTHORIZATION_MODE_INVALID")


def _root(workspace, *, create):
    workspace = Path(workspace).resolve()
    _require(workspace.is_dir(), "AUTHORIZATION_WORKSPACE_INVALID")
    current = workspace
    for name in ROOT_PARTS:
        current = current / name
        if not current.exists():
            _require(create, "AUTHORIZATION_ROOT_MISSING")
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
        _check_directory(current)
    return current


@contextmanager
def _locked_dir(workspace, *, create):
    root = _root(workspace, create=create)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    dfd = os.open(root, flags)
    lock_fd = None
    try:
        dst = os.fstat(dfd)
        _require(stat.S_ISDIR(dst.st_mode) and dst.st_uid == os.getuid()
                 and stat.S_IMODE(dst.st_mode) == 0o700, "AUTHORIZATION_DIRECTORY_INVALID")
        lock_fd = os.open(".lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=dfd)
        lock_st = os.fstat(lock_fd)
        _require(stat.S_ISREG(lock_st.st_mode) and lock_st.st_uid == os.getuid()
                 and stat.S_IMODE(lock_st.st_mode) == 0o600 and lock_st.st_nlink == 1,
                 "AUTHORIZATION_LOCK_INVALID")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield dfd
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(dfd)


def _filename(authorization_id):
    _require(isinstance(authorization_id, str) and AUTH_ID.fullmatch(authorization_id), "AUTHORIZATION_ID_INVALID")
    return authorization_id + ".json"


def _read(dfd, name):
    try:
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dfd)
    except (FileNotFoundError, OSError):
        raise AuthorizationError("AUTHORIZATION_NOT_FOUND") from None
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        _require(stat.S_ISREG(st.st_mode), "AUTHORIZATION_FILE_INVALID")
        _require(st.st_uid == os.getuid(), "AUTHORIZATION_OWNER_INVALID")
        _require(stat.S_IMODE(st.st_mode) == 0o600, "AUTHORIZATION_MODE_INVALID")
        _require(st.st_nlink == 1, "AUTHORIZATION_LINK_INVALID")
        _require(0 < st.st_size <= MAX_LEDGER_BYTES, "AUTHORIZATION_SIZE_INVALID")
        raw = stream.read(MAX_LEDGER_BYTES + 1)
    _require(len(raw) <= MAX_LEDGER_BYTES, "AUTHORIZATION_SIZE_INVALID")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise AuthorizationError("AUTHORIZATION_MALFORMED") from None
    _require(isinstance(value, dict), "AUTHORIZATION_MALFORMED")
    return value, raw


def _atomic_write(dfd, name, value, *, create):
    raw = _canonical(value)
    _require(len(raw) <= MAX_LEDGER_BYTES, "AUTHORIZATION_SIZE_INVALID")
    temp = ".write-" + uuid.uuid4().hex
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=dfd)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.close(fd); fd = -1
        if create:
            try:
                os.link(temp, name, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
            except FileExistsError:
                raise AuthorizationError("AUTHORIZATION_EXISTS") from None
            os.unlink(temp, dir_fd=dfd)
        else:
            os.replace(temp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        os.fsync(dfd)
        _, observed = _read(dfd, name)
        _require(observed == raw, "AUTHORIZATION_READBACK_INVALID")
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp, dir_fd=dfd)
        except FileNotFoundError:
            pass


def _validate_ledger(ledger):
    keys = {"receipt", "authorization_sha256", "status", "claim"}
    _require(isinstance(ledger, dict) and set(ledger) == keys, "AUTHORIZATION_LEDGER_INVALID")
    receipt = _receipt_fields(ledger["receipt"])
    expected = authorization_sha256(receipt)
    _require(ledger["authorization_sha256"] == expected, "AUTHORIZATION_HASH_DRIFT")
    _require(ledger["status"] in ("unused", "consumed"), "AUTHORIZATION_LEDGER_INVALID")
    if ledger["status"] == "unused":
        _require(ledger["claim"] is None, "AUTHORIZATION_LEDGER_INVALID")
    else:
        claim = ledger["claim"]
        required = {"attempt_id", "query_sha256", "symbols_sha256", "claimed_at", "terminal_status", "terminal_at"}
        _require(isinstance(claim, dict) and set(claim) == required, "AUTHORIZATION_LEDGER_INVALID")
        _require(isinstance(claim["attempt_id"], str) and ATTEMPT_ID.fullmatch(claim["attempt_id"]), "AUTHORIZATION_LEDGER_INVALID")
        _require(all(isinstance(claim[key], str) and HEX64.fullmatch(claim[key]) for key in ("query_sha256", "symbols_sha256")), "AUTHORIZATION_LEDGER_INVALID")
        _utc(claim["claimed_at"], "AUTHORIZATION_LEDGER_INVALID")
        _require(claim["terminal_status"] == "claimed" or claim["terminal_status"] in TERMINAL, "AUTHORIZATION_LEDGER_INVALID")
        if claim["terminal_status"] == "claimed":
            _require(claim["terminal_at"] is None, "AUTHORIZATION_LEDGER_INVALID")
        else:
            _utc(claim["terminal_at"], "AUTHORIZATION_LEDGER_INVALID")
    return receipt


def _public(ledger):
    return {"authorization_id": ledger["receipt"]["authorization_id"],
            "authorization_sha256": ledger["authorization_sha256"],
            "authorization_status": ledger["status"]}


def create_authorization(workspace, receipt):
    receipt = _receipt_fields(receipt)
    digest = authorization_sha256(receipt)
    ledger = {"receipt": receipt, "authorization_sha256": digest, "status": "unused", "claim": None}
    with _locked_dir(workspace, create=True) as dfd:
        _atomic_write(dfd, _filename(receipt["authorization_id"]), ledger, create=True)
    return _public(ledger)


def claim_authorization(workspace, *, authorization_id, authorization_sha256_value,
                        calibration_contract_sha256, cohort_sha256, attempt_id,
                        query_sha256_value, symbols_sha256_value, claimed_at=None):
    _require(isinstance(authorization_sha256_value, str) and HEX64.fullmatch(authorization_sha256_value), "AUTHORIZATION_HASH_INVALID")
    _require(isinstance(calibration_contract_sha256, str) and HEX64.fullmatch(calibration_contract_sha256), "AUTHORIZATION_CONTRACT_INVALID")
    _require(isinstance(cohort_sha256, str) and HEX64.fullmatch(cohort_sha256), "AUTHORIZATION_COHORT_INVALID")
    _require(isinstance(attempt_id, str) and ATTEMPT_ID.fullmatch(attempt_id), "AUTHORIZATION_ATTEMPT_INVALID")
    _require(isinstance(query_sha256_value, str) and HEX64.fullmatch(query_sha256_value)
             and isinstance(symbols_sha256_value, str) and HEX64.fullmatch(symbols_sha256_value), "AUTHORIZATION_QUERY_HASH_INVALID")
    claimed_at = claimed_at or _now(); _utc(claimed_at, "AUTHORIZATION_TIMESTAMP_INVALID")
    with _locked_dir(workspace, create=False) as dfd:
        name = _filename(authorization_id)
        ledger, _ = _read(dfd, name)
        receipt = _validate_ledger(ledger)
        _require(ledger["authorization_sha256"] == authorization_sha256_value, "AUTHORIZATION_HASH_MISMATCH")
        _require(receipt["calibration_contract_sha256"] == calibration_contract_sha256, "AUTHORIZATION_CONTRACT_DRIFT")
        _require(receipt["cohort_sha256"] == cohort_sha256, "AUTHORIZATION_COHORT_DRIFT")
        _require(ledger["status"] == "unused", "AUTHORIZATION_ALREADY_CONSUMED")
        ledger["status"] = "consumed"
        ledger["claim"] = {"attempt_id": attempt_id, "query_sha256": query_sha256_value,
                           "symbols_sha256": symbols_sha256_value, "claimed_at": claimed_at,
                           "terminal_status": "claimed", "terminal_at": None}
        _atomic_write(dfd, name, ledger, create=False)
    return _public(ledger)


def finalize_authorization(workspace, *, authorization_id, authorization_sha256_value,
                           attempt_id, terminal_status, terminal_at=None):
    _require(terminal_status in TERMINAL, "AUTHORIZATION_TERMINAL_INVALID")
    terminal_at = terminal_at or _now(); _utc(terminal_at, "AUTHORIZATION_TIMESTAMP_INVALID")
    with _locked_dir(workspace, create=False) as dfd:
        name = _filename(authorization_id)
        ledger, _ = _read(dfd, name)
        _validate_ledger(ledger)
        _require(ledger["authorization_sha256"] == authorization_sha256_value, "AUTHORIZATION_HASH_MISMATCH")
        _require(ledger["status"] == "consumed" and ledger["claim"]["terminal_status"] == "claimed",
                 "AUTHORIZATION_TERMINAL_ALREADY_SET")
        _require(ledger["claim"]["attempt_id"] == attempt_id, "AUTHORIZATION_ATTEMPT_MISMATCH")
        ledger["claim"]["terminal_status"] = terminal_status
        ledger["claim"]["terminal_at"] = terminal_at
        _atomic_write(dfd, name, ledger, create=False)
    return _public(ledger)


def read_authorization(workspace, authorization_id):
    """Private diagnostic API used for reconciliation and offline tests."""
    with _locked_dir(workspace, create=False) as dfd:
        ledger, _ = _read(dfd, _filename(authorization_id))
        _validate_ledger(ledger)
        return ledger
