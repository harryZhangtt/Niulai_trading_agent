"""Explicit schema-5..8 to schema-9 side-file migration.

The engine never invokes this module.  Migration builds and verifies a private
candidate before a Darwin atomic exchange.  Diagnostics and manifests contain
counts, structural hashes, and fixed codes only.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import argparse
import ctypes
import fcntl
import errno
import hashlib
import inspect
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import sys
from typing import Callable

from .engine_schema import (
    SCHEMA_VERSION, create_schema9, prompt_binding_sha256, schema_fingerprint,
    verify_schema9,
)
from .prompt_custody import CapturedPromptV1, PromptArtifactStore

_SUPPORTED = {5, 6, 7, 8}
_RENAME_SWAP = 0x00000002
_PROOF = ("artifact_ref", "sha256", "length", "version",
          "source_identity_sha256", "binding_sha256", "generation", "proof_origin")
_COMMON_COLUMNS = {
    "jobs": ("job_id", "schedule_hash", "cursor"),
    "attempts": ("attempt_id", "slot_id", "attempt_no", "started_at", "ended_at", "status", "code", "receipt"),
    "metadata": ("key", "value"),
    "delivery_reconciliations": ("slot_id", "attempt_id", "message_id", "payload_digest", "verified_at", "recorded_at", "receipt"),
    "provider_results": ("attempt_id", "slot_id", "canonical_json", "canonical_sha256", "provider", "operation_id", "phase", "submission", "terminal_proof", "status", "failure_kind", "recorded_at"),
    "retry_decisions": ("attempt_id", "slot_id", "canonical_json", "policy_fingerprint", "policy_version", "delay_seconds", "retry_after_at", "next_attempt_at", "deadline", "recorded_at"),
    "reconciliation_records": ("reconciliation_id", "attempt_id", "slot_id", "operation_id", "slot_operation_scope", "proof_json", "proof_sha256", "evidence_bytes", "evidence_ref", "evidence_sha256", "adapter_identity", "adapter_version", "recorded_at"),
    "reconciliation_consumptions": ("reconciliation_id", "attempt_id", "retry_decision_attempt_id", "consumed_at"),
}
_SLOT_BASE = ("slot_id", "job_id", "scheduled_at", "expires_at", "status", "attempts",
              "next_attempt_at", "updated_at", "code", "provider", "operation_id",
              "replay_contract", "replay_contract_sha256", "retry_policy",
              "retry_policy_fingerprint", "retry_deadline", "circuit_profile",
              "circuit_resource_hash", "circuit_config", "circuit_config_sha256")
_CIRCUIT_BASE = ("provider", "profile", "resource_hash", "scope_sha256", "config_sha256",
                 "state", "transient_failures", "opened_until", "probe_owner", "probe_expires",
                 "updated_at")
_SOURCE_COLUMNS = {
    5: _COMMON_COLUMNS | {"slots": _SLOT_BASE, "circuits": _CIRCUIT_BASE},
    6: _COMMON_COLUMNS | {"slots": _SLOT_BASE, "circuits": _CIRCUIT_BASE},
    7: _COMMON_COLUMNS | {"slots": _SLOT_BASE,
                          "circuits": _CIRCUIT_BASE[:5] + ("generation",) + _CIRCUIT_BASE[5:]},
    8: _COMMON_COLUMNS | {"slots": _SLOT_BASE + ("prompt_sha256", "prompt_snapshot"),
                          "circuits": _CIRCUIT_BASE[:5] + ("generation",) + _CIRCUIT_BASE[5:]},
}
_TARGET_TABLES = frozenset({
    "attempts", "circuits", "delivery_reconciliations", "jobs", "metadata",
    "prompt_artifacts", "provider_output_custody", "provider_results",
    "reconciliation_consumptions", "reconciliation_records", "retry_decisions",
    "slots",
})


class Schema9MigrationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code: str):
    raise Schema9MigrationError(code)


@dataclass(frozen=True)
class MigrationManifest:
    source_version: int
    target_version: int
    source_tables: tuple[tuple[str, int, str], ...]
    target_tables: tuple[tuple[str, int, str], ...]
    source_schema_sha256: str
    target_schema_sha256: str
    source_rows_sha256: str
    target_rows_sha256: str
    active_path: str
    exchanged_legacy_path: str
    swap_method: str
    before_active_sha256: str
    before_active_inode: int
    before_candidate_sha256: str
    before_candidate_inode: int
    after_active_sha256: str
    after_active_inode: int
    after_legacy_sha256: str
    after_legacy_inode: int
    codes: tuple[str, ...]

    @staticmethod
    def _inventory(value):
        return {table: {"count": count, "sha256": digest}
                for table, count, digest in value}

    def _payload(self):
        return {
            "source_version": self.source_version,
            "target_version": self.target_version,
            "source_tables": self._inventory(self.source_tables),
            "target_tables": self._inventory(self.target_tables),
            "source_schema_sha256": self.source_schema_sha256,
            "target_schema_sha256": self.target_schema_sha256,
            "source_rows_sha256": self.source_rows_sha256,
            "target_rows_sha256": self.target_rows_sha256,
            "active_path": self.active_path,
            "exchanged_legacy_path": self.exchanged_legacy_path,
            "swap_method": self.swap_method,
            "before": {
                "active": {"sha256": self.before_active_sha256,
                           "inode": self.before_active_inode},
                "candidate": {"sha256": self.before_candidate_sha256,
                              "inode": self.before_candidate_inode},
            },
            "after": {
                "active": {"sha256": self.after_active_sha256,
                           "inode": self.after_active_inode},
                "legacy_peer": {"sha256": self.after_legacy_sha256,
                                "inode": self.after_legacy_inode},
            },
            "codes": list(self.codes),
        }

    def to_mapping(self):
        payload = self._payload()
        payload["receipt_sha256"] = _mapping_digest(payload)
        return payload

    @classmethod
    def from_mapping(cls, mapping):
        try:
            payload = dict(mapping)
            seal = payload.pop("receipt_sha256")
            if set(payload) != {
                    "source_version", "target_version", "source_tables", "target_tables",
                    "source_schema_sha256", "target_schema_sha256", "source_rows_sha256",
                    "target_rows_sha256", "active_path", "exchanged_legacy_path",
                    "swap_method", "before", "after", "codes"}:
                _fail("MIGRATION_RECEIPT_INVALID")
            if type(seal) is not str or not secrets.compare_digest(seal, _mapping_digest(payload)):
                _fail("MIGRATION_RECEIPT_INVALID")
            source_tables = _parse_inventory(payload["source_tables"])
            target_tables = _parse_inventory(payload["target_tables"])
            before, after = payload["before"], payload["after"]
            if (set(before) != {"active", "candidate"}
                    or set(after) != {"active", "legacy_peer"}):
                _fail("MIGRATION_RECEIPT_INVALID")
            identities = (before["active"], before["candidate"],
                          after["active"], after["legacy_peer"])
            if any(set(item) != {"sha256", "inode"} for item in identities):
                _fail("MIGRATION_RECEIPT_INVALID")
            result = cls(
                payload["source_version"], payload["target_version"],
                source_tables, target_tables, payload["source_schema_sha256"],
                payload["target_schema_sha256"], payload["source_rows_sha256"],
                payload["target_rows_sha256"], payload["active_path"],
                payload["exchanged_legacy_path"], payload["swap_method"],
                before["active"]["sha256"], before["active"]["inode"],
                before["candidate"]["sha256"], before["candidate"]["inode"],
                after["active"]["sha256"], after["active"]["inode"],
                after["legacy_peer"]["sha256"], after["legacy_peer"]["inode"],
                tuple(payload["codes"]),
            )
        except Schema9MigrationError:
            raise
        except (KeyError, TypeError, ValueError):
            _fail("MIGRATION_RECEIPT_INVALID")
        if (type(result.source_version) is not int or result.source_version not in _SUPPORTED
                or result.target_version != SCHEMA_VERSION
                or not _absolute_string(result.active_path)
                or not _absolute_string(result.exchanged_legacy_path)
                or type(result.swap_method) is not str or not result.swap_method
                or result.codes != ("MIGRATION_SCHEMA9_ACTIVATED",)):
            _fail("MIGRATION_RECEIPT_INVALID")
        for digest in (result.source_schema_sha256, result.target_schema_sha256,
                       result.source_rows_sha256, result.target_rows_sha256,
                       result.before_active_sha256, result.before_candidate_sha256,
                       result.after_active_sha256, result.after_legacy_sha256):
            if not _sha256_string(digest):
                _fail("MIGRATION_RECEIPT_INVALID")
        if any(type(value) is not int or value <= 0 for value in (
                result.before_active_inode, result.before_candidate_inode,
                result.after_active_inode, result.after_legacy_inode)):
            _fail("MIGRATION_RECEIPT_INVALID")
        _validate_manifest_inventory(result)
        return result


def _mapping_digest(mapping):
    encoded = json.dumps(mapping, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_string(value):
    return (type(value) is str and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def _absolute_string(value):
    return type(value) is str and Path(value).is_absolute() and not Path(value).is_symlink()


def _parse_inventory(value):
    if type(value) is not dict:
        _fail("MIGRATION_RECEIPT_INVALID")
    result = []
    for table, item in value.items():
        if (type(table) is not str or not table or type(item) is not dict
                or set(item) != {"count", "sha256"}
                or type(item["count"]) is not int or item["count"] < 0
                or not _sha256_string(item["sha256"])):
            _fail("MIGRATION_RECEIPT_INVALID")
        result.append((table, item["count"], item["sha256"]))
    return tuple(sorted(result))


def _hook(callback, phase):
    if callback is not None:
        callback(phase)


def _columns(db, table):
    return tuple(row[1] for row in db.execute(f'PRAGMA table_info("{table}")'))


def _tables(db):
    return tuple(row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))


def _value(value):
    if isinstance(value, bytes):
        return {"blob_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, float):
        return {"float_hex": value.hex()}
    return value


def _row_digest(db, table, columns):
    hasher = hashlib.sha256()
    order = ",".join(f'"{name}"' for name in columns)
    rows = db.execute(f'SELECT {order} FROM "{table}" ORDER BY rowid').fetchall()
    for row in rows:
        encoded = json.dumps([_value(item) for item in row], sort_keys=True,
                             separators=(",", ":"), ensure_ascii=True).encode("ascii")
        hasher.update(len(encoded).to_bytes(8, "big")); hasher.update(encoded)
    return hasher.hexdigest(), len(rows)


def _database_digest(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                return hasher.hexdigest()
            hasher.update(chunk)


def _safe_active(path):
    if not path.is_absolute() or path.is_symlink():
        _fail("MIGRATION_DATABASE_UNSAFE")
    try:
        value = path.stat()
        parent = path.parent.stat()
    except OSError:
        _fail("MIGRATION_DATABASE_UNSAFE")
    if (not stat.S_ISREG(value.st_mode) or value.st_uid != os.getuid()
            or stat.S_IMODE(value.st_mode) != 0o600 or value.st_nlink != 1
            or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
            or stat.S_IMODE(parent.st_mode) != 0o700):
        _fail("MIGRATION_DATABASE_UNSAFE")
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(path) + suffix).exists():
            _fail("MIGRATION_DATABASE_SIDECAR_PRESENT")


def _connect_readonly(path):
    try:
        db = sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        return db
    except sqlite3.Error:
        _fail("MIGRATION_DATABASE_OPEN_FAILED")


def _source_contract(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        _fail("MIGRATION_ALREADY_SCHEMA9")
    if version > SCHEMA_VERSION:
        _fail("DATABASE_SCHEMA_TOO_NEW")
    if version not in _SUPPORTED:
        _fail("MIGRATION_SOURCE_SCHEMA_UNSUPPORTED")
    expected = _SOURCE_COLUMNS[version]
    if set(_tables(db)) != set(expected):
        _fail("MIGRATION_SOURCE_SCHEMA_FINGERPRINT_MISMATCH")
    for table, columns in expected.items():
        if _columns(db, table) != columns:
            _fail("MIGRATION_SOURCE_SCHEMA_FINGERPRINT_MISMATCH")
    return version


def _copy_backup(source_path, backup_path):
    source = _connect_readonly(source_path)
    try:
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
    except sqlite3.Error:
        _fail("MIGRATION_BACKUP_FAILED")
    finally:
        source.close()
    os.chmod(backup_path, 0o600)


def _create_exclusive(path):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError:
        _fail("MIGRATION_CANDIDATE_CREATE_FAILED")
    os.close(fd)


def _legacy_identity(database_sha, slot_id, prompt_sha, length):
    encoded = json.dumps({"schema": 1, "legacy_database_sha256": database_sha,
                          "slot_id_sha256": hashlib.sha256(slot_id.encode("utf-8")).hexdigest(),
                          "prompt_sha256": prompt_sha, "length": length},
                         sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _slot_proofs(source, store, database_sha):
    result = {}
    has_snapshot = "prompt_snapshot" in _columns(source, "slots")
    projection = ("slot_id,job_id,provider,prompt_sha256,prompt_snapshot" if has_snapshot
                  else "slot_id,job_id,provider,NULL prompt_sha256,NULL prompt_snapshot")
    for row in source.execute(f"SELECT {projection} FROM slots"):
        snapshot, digest = row["prompt_snapshot"], row["prompt_sha256"]
        if (snapshot is None) != (digest is None):
            _fail("MIGRATION_PROMPT_PARTIAL")
        if snapshot is None or row["provider"] is None:
            result[row["slot_id"]] = {name: None for name in _PROOF[:-1]} | {
                "proof_origin": "legacy_unbound"}
            continue
        if type(snapshot) is not str:
            _fail("MIGRATION_PROMPT_UTF8_INVALID")
        try:
            raw = snapshot.encode("utf-8", errors="strict")
        except UnicodeError:
            _fail("MIGRATION_PROMPT_UTF8_INVALID")
        if not 1 <= len(raw) <= 65536:
            _fail("MIGRATION_PROMPT_SIZE_INVALID")
        actual = hashlib.sha256(raw).hexdigest()
        if type(digest) is not str or actual != digest:
            _fail("MIGRATION_PROMPT_SHA256_MISMATCH")
        identity = _legacy_identity(database_sha, row["slot_id"], actual, len(raw))
        try:
            descriptor = store.publish(CapturedPromptV1(raw, actual, len(raw), identity),
                                       "0", "backfilled_v8")
            store.verify(descriptor)
        except Exception:
            _fail("MIGRATION_ARTIFACT_PUBLISH_FAILED")
        values = {"artifact_ref": descriptor.ref, "sha256": descriptor.sha256,
                  "length": descriptor.length, "version": descriptor.version,
                  "source_identity_sha256": descriptor.source_identity_sha256,
                  "generation": descriptor.generation, "proof_origin": "backfilled_v8"}
        values["binding_sha256"] = prompt_binding_sha256(
            row["job_id"], row["slot_id"], values)
        result[row["slot_id"]] = values
    return result


def _insert_rows(source, target, table, target_columns=None, transform=None):
    source_columns = _columns(source, table)
    target_columns = target_columns or _columns(target, table)
    query = f'SELECT {",".join(source_columns)} FROM "{table}" ORDER BY rowid'
    for row in source.execute(query):
        values = {name: row[name] for name in source_columns}
        if transform is not None:
            values = transform(values)
        columns = tuple(name for name in target_columns if name in values)
        marks = ",".join("?" for _ in columns)
        target.execute(f'INSERT INTO "{table}"({",".join(columns)}) VALUES({marks})',
                       tuple(values[name] for name in columns))


def _build_candidate(source, candidate, store, database_sha, phase_hook):
    target = sqlite3.connect(candidate)
    target.row_factory = sqlite3.Row
    try:
        target.execute("PRAGMA foreign_keys=OFF")
        create_schema9(target)
        proofs = _slot_proofs(source, store, database_sha)
        _hook(phase_hook, "artifacts_published")
        _insert_rows(source, target, "jobs")
        for proof in proofs.values():
            if proof["artifact_ref"] is not None:
                values = (proof["artifact_ref"], proof["sha256"], proof["length"],
                          proof["version"], proof["source_identity_sha256"],
                          proof["generation"], proof["proof_origin"])
                existing = target.execute("SELECT * FROM prompt_artifacts WHERE ref=?",
                                          (proof["artifact_ref"],)).fetchone()
                if existing is None:
                    target.execute("""INSERT INTO prompt_artifacts
                        (ref,sha256,length,version,source_identity_sha256,generation,proof_origin)
                        VALUES(?,?,?,?,?,?,?)""", values)
                elif tuple(existing) != values:
                    _fail("MIGRATION_ARTIFACT_METADATA_CONFLICT")
        slot_target = tuple(name for name in _columns(target, "slots"))
        _insert_rows(source, target, "slots", slot_target,
                     lambda row: row | proofs[row["slot_id"]])
        attempt_target = tuple(name for name in _columns(target, "attempts"))
        _insert_rows(source, target, "attempts", attempt_target,
                     lambda row: row | proofs[row["slot_id"]])
        for table in ("metadata", "delivery_reconciliations", "provider_results",
                      "retry_decisions", "reconciliation_records",
                      "reconciliation_consumptions", "circuits"):
            def bind(row, table=table):
                if table == "circuits":
                    return row | {"generation": row.get("generation", 0)}
                if table == "reconciliation_consumptions":
                    attempt_id = row["attempt_id"]
                    proof = proofs[next(item["slot_id"] for item in source.execute(
                        "SELECT slot_id FROM attempts WHERE attempt_id=?", (attempt_id,)))]
                elif "attempt_id" in row:
                    found = source.execute("SELECT slot_id FROM attempts WHERE attempt_id=?",
                                           (row["attempt_id"],)).fetchone()
                    proof = proofs[found[0]] if found else {"binding_sha256": None}
                else:
                    proof = {"binding_sha256": None}
                return row | {"prompt_binding_sha256": proof["binding_sha256"]}
            _insert_rows(source, target, table, transform=bind)
        target.execute("PRAGMA user_version=9")
        target.commit()
        target.execute("PRAGMA foreign_keys=ON")
        verify_schema9(target)
        _hook(phase_hook, "candidate_verified")
    except Schema9MigrationError:
        raise
    except (sqlite3.Error, KeyError, StopIteration, TypeError, ValueError):
        _fail("MIGRATION_CANDIDATE_INVALID")
    finally:
        target.close()


def darwin_rename_swap(left: Path, right: Path):
    if os.uname().sysname != "Darwin" or left.parent != right.parent:
        _fail("MIGRATION_ATOMIC_SWAP_UNAVAILABLE")
    directory_fd = os.open(left.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        function = libc.renameatx_np
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                             ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(directory_fd, os.fsencode(left.name), directory_fd,
                          os.fsencode(right.name), _RENAME_SWAP)
        if result != 0:
            _fail("MIGRATION_ATOMIC_SWAP_FAILED")
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _verify_file(path):
    db = _connect_readonly(path)
    try:
        return verify_schema9(db)
    except (sqlite3.Error, ValueError):
        _fail("MIGRATION_POST_SWAP_VERIFY_FAILED")
    finally:
        db.close()


@dataclass(frozen=True)
class _FileState:
    sha256: str
    inode: int
    version: int
    schema_sha256: str


def _table_inventory(db):
    result = []
    for table in _tables(db):
        digest, count = _row_digest(db, table, _columns(db, table))
        result.append((table, count, digest))
    return tuple(result)


def _inventory_digest(inventory):
    return hashlib.sha256(json.dumps(inventory, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()


def _validate_manifest_inventory(manifest):
    source_names = {table for table, _count, _digest in manifest.source_tables}
    target_names = {table for table, _count, _digest in manifest.target_tables}
    if (manifest.source_version not in _SUPPORTED
            or source_names != set(_SOURCE_COLUMNS[manifest.source_version])
            or target_names != _TARGET_TABLES
            or manifest.source_rows_sha256 != _inventory_digest(manifest.source_tables)
            or manifest.target_rows_sha256 != _inventory_digest(manifest.target_tables)):
        _fail("MIGRATION_RECEIPT_INVALID")


def _observe_file(path):
    try:
        _safe_active(path)
        info = path.stat()
        digest = _database_digest(path)
        db = _connect_readonly(path)
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            schema = schema_fingerprint(db)
        finally:
            db.close()
        if type(version) is not int:
            return None
        return _FileState(digest, info.st_ino, version, schema)
    except (Schema9MigrationError, sqlite3.Error, OSError, ValueError, TypeError):
        return None


def _expected_source(manifest):
    return _FileState(manifest.before_active_sha256, manifest.before_active_inode,
                      manifest.source_version, manifest.source_schema_sha256)


def _expected_candidate(manifest):
    return _FileState(manifest.before_candidate_sha256, manifest.before_candidate_inode,
                      manifest.target_version, manifest.target_schema_sha256)


def _swap_source_digest(swap):
    target = swap if inspect.isfunction(swap) else type(swap).__call__
    try:
        source = inspect.getsource(target).encode("utf-8")
    except (OSError, TypeError, UnicodeError):
        _fail("MIGRATION_SWAP_IMPLEMENTATION_UNATTESTED")
    return hashlib.sha256(source).hexdigest()


def _select_swap(test_swap):
    if test_swap is None:
        return darwin_rename_swap, "darwin_rename_swap:sha256:" + _swap_source_digest(darwin_rename_swap)
    if not callable(test_swap):
        _fail("MIGRATION_SWAP_IMPLEMENTATION_UNATTESTED")
    return test_swap, "test-only:sha256:" + _swap_source_digest(test_swap)


def _private_directory(path):
    try:
        value = path.stat()
    except OSError:
        _fail("MIGRATION_WRITER_LOCK_UNSAFE")
    if (path.is_symlink() or not stat.S_ISDIR(value.st_mode)
            or value.st_uid != os.getuid() or stat.S_IMODE(value.st_mode) != 0o700):
        _fail("MIGRATION_WRITER_LOCK_UNSAFE")


@contextmanager
def _writer_quiescence(active):
    if not active.is_absolute() or len(active.parents) < 2:
        _fail("MIGRATION_DATABASE_UNSAFE")
    state = active.parent.parent
    _private_directory(state)
    lock_path = state / "service.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError:
        _fail("MIGRATION_WRITER_LOCK_UNSAFE")
    try:
        value = os.fstat(fd)
        if (not stat.S_ISREG(value.st_mode) or value.st_uid != os.getuid()
                or stat.S_IMODE(value.st_mode) != 0o600 or value.st_nlink != 1):
            _fail("MIGRATION_WRITER_LOCK_UNSAFE")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _fail("MIGRATION_WRITER_ACTIVE")
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                _fail("MIGRATION_WRITER_ACTIVE")
            _fail("MIGRATION_WRITER_LOCK_UNSAFE")
        yield
    finally:
        os.close(fd)


def _exchange_with_readback(left, right, swap, left_before, right_before,
                            *, failure_code, unknown_code):
    try:
        swap(left, right)
    except BaseException:
        pass
    observed_left, observed_right = _observe_file(left), _observe_file(right)
    if observed_left == right_before and observed_right == left_before:
        return
    if observed_left == left_before and observed_right == right_before:
        _fail(failure_code)
    _fail(unknown_code)


def _rollback_receipt(manifest, code, before_active, before_peer,
                      after_active, after_peer):
    payload = {
        "codes": [code],
        "migration_receipt_sha256": manifest.to_mapping()["receipt_sha256"],
        "active_path": manifest.active_path,
        "exchanged_peer_path": manifest.exchanged_legacy_path,
        "swap_method": manifest.swap_method,
        "before": {
            "active": {"sha256": before_active.sha256, "inode": before_active.inode,
                       "version": before_active.version,
                       "schema_sha256": before_active.schema_sha256},
            "peer": {"sha256": before_peer.sha256, "inode": before_peer.inode,
                     "version": before_peer.version,
                     "schema_sha256": before_peer.schema_sha256},
        },
        "after": {
            "active": {"sha256": after_active.sha256, "inode": after_active.inode,
                       "version": after_active.version,
                       "schema_sha256": after_active.schema_sha256},
            "peer": {"sha256": after_peer.sha256, "inode": after_peer.inode,
                     "version": after_peer.version,
                     "schema_sha256": after_peer.schema_sha256},
        },
        "source_tables": MigrationManifest._inventory(manifest.source_tables),
        "target_tables": MigrationManifest._inventory(manifest.target_tables),
    }
    payload["receipt_sha256"] = _mapping_digest(payload)
    return payload


def _restore_after_forward_failure(active, legacy, swap, source_state,
                                   candidate_inode):
    current_active, current_legacy = _observe_file(active), _observe_file(legacy)
    if (current_active is None or current_active.inode != candidate_inode
            or current_legacy != source_state):
        _fail("MIGRATION_ROLLBACK_OUTCOME_UNKNOWN")
    try:
        _exchange_with_readback(
            active, legacy, swap, current_active, source_state,
            failure_code="MIGRATION_ROLLBACK_FAILED",
            unknown_code="MIGRATION_ROLLBACK_OUTCOME_UNKNOWN")
    except Schema9MigrationError as error:
        if error.code == "MIGRATION_ROLLBACK_FAILED":
            # The schema-9 file is still active.  Both recovery sidefiles must remain.
            raise
        raise
    if _observe_file(active) != source_state:
        _fail("MIGRATION_ROLLBACK_OUTCOME_UNKNOWN")


def migrate_to_schema9(database_path, artifact_store, *, phase_hook=None,
                       _swap_for_test: Callable[[Path, Path], None] | None = None):
    active = Path(database_path)
    swap, swap_identity = _select_swap(_swap_for_test)
    if not isinstance(artifact_store, PromptArtifactStore):
        _fail("MIGRATION_ARTIFACT_STORE_REQUIRED")
    token = secrets.token_hex(12)
    backup = active.parent / (".schema9-source-" + token + ".sqlite")
    candidate = active.parent / (".schema9-candidate-" + token + ".sqlite")
    preserve_sidefiles = False
    activated = False
    with _writer_quiescence(active):
        _safe_active(active)
        _create_exclusive(backup)
        _create_exclusive(candidate)
        try:
            source = _connect_readonly(active)
            try:
                version = _source_contract(source)
                source_schema = schema_fingerprint(source)
                source_tables = _table_inventory(source)
            finally:
                source.close()
            source_state = _observe_file(active)
            if source_state is None or source_state.version != version or source_state.schema_sha256 != source_schema:
                _fail("MIGRATION_SOURCE_CHANGED")
            source_rows = _inventory_digest(source_tables)
            _hook(phase_hook, "source_verified")

            _copy_backup(active, backup)
            source = _connect_readonly(backup)
            try:
                if (_source_contract(source) != version
                        or schema_fingerprint(source) != source_schema
                        or _table_inventory(source) != source_tables):
                    _fail("MIGRATION_BACKUP_VERIFY_FAILED")
                _build_candidate(source, candidate, artifact_store,
                                 source_state.sha256, phase_hook)
            finally:
                source.close()

            with open(candidate, "rb") as stream:
                os.fsync(stream.fileno())
            directory_fd = os.open(active.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            _hook(phase_hook, "candidate_fsynced")

            candidate_db = _connect_readonly(candidate)
            try:
                target_schema = verify_schema9(candidate_db)
                target_tables = _table_inventory(candidate_db)
            except (sqlite3.Error, ValueError):
                _fail("MIGRATION_CANDIDATE_INVALID")
            finally:
                candidate_db.close()
            candidate_state = _observe_file(candidate)
            if (candidate_state is None or candidate_state.version != SCHEMA_VERSION
                    or candidate_state.schema_sha256 != target_schema):
                _fail("MIGRATION_CANDIDATE_INVALID")
            if _observe_file(active) != source_state:
                _fail("MIGRATION_SOURCE_CHANGED")

            try:
                _exchange_with_readback(
                    active, candidate, swap, source_state, candidate_state,
                    failure_code="MIGRATION_ATOMIC_SWAP_FAILED",
                    unknown_code="MIGRATION_SWAP_OUTCOME_UNKNOWN")
            except Schema9MigrationError as error:
                if error.code == "MIGRATION_SWAP_OUTCOME_UNKNOWN":
                    preserve_sidefiles = True
                raise
            activated = True
            try:
                _hook(phase_hook, "swapped")
                if (_verify_file(active) != target_schema
                        or _observe_file(active) != candidate_state
                        or _observe_file(candidate) != source_state):
                    _fail("MIGRATION_POST_SWAP_VERIFY_FAILED")
                _hook(phase_hook, "post_swap_verified")
            except BaseException as original:
                try:
                    _restore_after_forward_failure(
                        active, candidate, swap, source_state, candidate_state.inode)
                    activated = False
                except BaseException:
                    preserve_sidefiles = True
                    raise
                raise original

            after_active, after_legacy = _observe_file(active), _observe_file(candidate)
            if after_active != candidate_state or after_legacy != source_state:
                preserve_sidefiles = True
                _fail("MIGRATION_SWAP_OUTCOME_UNKNOWN")
            target_rows = _inventory_digest(target_tables)
            return MigrationManifest(
                version, SCHEMA_VERSION, source_tables, target_tables,
                source_schema, target_schema, source_rows, target_rows,
                str(active), str(candidate), swap_identity,
                source_state.sha256, source_state.inode,
                candidate_state.sha256, candidate_state.inode,
                after_active.sha256, after_active.inode,
                after_legacy.sha256, after_legacy.inode,
                ("MIGRATION_SCHEMA9_ACTIVATED",),
            )
        finally:
            if preserve_sidefiles:
                pass
            elif activated:
                try:
                    backup.unlink()
                except FileNotFoundError:
                    pass
            else:
                for path in (candidate, backup):
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass


def _coerce_manifest(receipt):
    manifest = receipt if isinstance(receipt, MigrationManifest) else MigrationManifest.from_mapping(receipt)
    _validate_manifest_inventory(manifest)
    if (manifest.before_active_sha256 != manifest.after_legacy_sha256
            or manifest.before_active_inode != manifest.after_legacy_inode
            or manifest.before_candidate_sha256 != manifest.after_active_sha256
            or manifest.before_candidate_inode != manifest.after_active_inode
            or manifest.active_path == manifest.exchanged_legacy_path):
        _fail("MIGRATION_RECEIPT_INVALID")
    return manifest


def rollback_schema9(database_path, exchanged_legacy_path, receipt, *, phase_hook=None,
                     _swap_for_test: Callable[[Path, Path], None] | None = None):
    manifest = _coerce_manifest(receipt)
    swap, swap_identity = _select_swap(_swap_for_test)
    active, legacy = Path(database_path), Path(exchanged_legacy_path)
    if str(active) != manifest.active_path or str(legacy) != manifest.exchanged_legacy_path:
        _fail("MIGRATION_ROLLBACK_PATH_MISMATCH")
    if swap_identity != manifest.swap_method:
        _fail("MIGRATION_SWAP_METHOD_MISMATCH")
    with _writer_quiescence(active):
        _safe_active(active)
        _safe_active(legacy)
        source_state, candidate_state = _expected_source(manifest), _expected_candidate(manifest)
        current_active, current_peer = _observe_file(active), _observe_file(legacy)
        if current_active is not None and current_active.version == SCHEMA_VERSION:
            db = _connect_readonly(active)
            try:
                verify_schema9(db)
                if db.execute("SELECT 1 FROM metadata WHERE key='schema9_evidence_write_at'").fetchone():
                    _fail("MIGRATION_ROLLBACK_FENCE_CROSSED")
            except Schema9MigrationError:
                raise
            except (sqlite3.Error, ValueError):
                pass
            finally:
                db.close()
        if current_active == source_state and current_peer == candidate_state:
            source = _connect_readonly(active)
            peer = _connect_readonly(legacy)
            try:
                _source_contract(source)
                verify_schema9(peer)
                if (_table_inventory(source) != manifest.source_tables
                        or _table_inventory(peer) != manifest.target_tables):
                    _fail("MIGRATION_ROLLBACK_IDENTITY_MISMATCH")
            except Schema9MigrationError:
                raise
            except (sqlite3.Error, ValueError):
                _fail("MIGRATION_ROLLBACK_IDENTITY_MISMATCH")
            finally:
                source.close()
                peer.close()
            return _rollback_receipt(
                manifest, "MIGRATION_SCHEMA9_ALREADY_ROLLED_BACK",
                current_active, current_peer, current_active, current_peer)
        if current_active != candidate_state or current_peer != source_state:
            _fail("MIGRATION_ROLLBACK_IDENTITY_MISMATCH")
        active_db = _connect_readonly(active)
        peer_db = _connect_readonly(legacy)
        try:
            verify_schema9(active_db)
            _source_contract(peer_db)
            if (_table_inventory(active_db) != manifest.target_tables
                    or _table_inventory(peer_db) != manifest.source_tables):
                _fail("MIGRATION_ROLLBACK_IDENTITY_MISMATCH")
        except Schema9MigrationError:
            raise
        except (sqlite3.Error, ValueError):
            _fail("MIGRATION_ROLLBACK_IDENTITY_MISMATCH")
        finally:
            active_db.close()
            peer_db.close()

        _exchange_with_readback(
            active, legacy, swap, candidate_state, source_state,
            failure_code="MIGRATION_ROLLBACK_SWAP_FAILED",
            unknown_code="MIGRATION_ROLLBACK_OUTCOME_UNKNOWN")
        after_active, after_peer = _observe_file(active), _observe_file(legacy)
        try:
            _hook(phase_hook, "rollback_swapped")
        except BaseException:
            pass
        # A post-effect exception is not an ordinary failure.  Exact readback decides.
        after_active, after_peer = _observe_file(active), _observe_file(legacy)
        if after_active != source_state or after_peer != candidate_state:
            _fail("MIGRATION_ROLLBACK_POST_EFFECT_OUTCOME_UNKNOWN")
        source = _connect_readonly(active)
        peer = _connect_readonly(legacy)
        try:
            _source_contract(source)
            verify_schema9(peer)
        except (sqlite3.Error, ValueError):
            _fail("MIGRATION_ROLLBACK_POST_EFFECT_OUTCOME_UNKNOWN")
        finally:
            source.close()
            peer.close()
        return _rollback_receipt(
            manifest, "MIGRATION_SCHEMA9_ROLLED_BACK",
            current_active, current_peer, after_active, after_peer)


def _load_receipt(path):
    receipt_path = Path(path)
    if not receipt_path.is_absolute() or receipt_path.is_symlink():
        _fail("MIGRATION_RECEIPT_UNSAFE")
    try:
        value, parent = receipt_path.stat(), receipt_path.parent.stat()
        if (not stat.S_ISREG(value.st_mode) or value.st_uid != os.getuid()
                or stat.S_IMODE(value.st_mode) != 0o600 or value.st_nlink != 1
                or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
                or stat.S_IMODE(parent.st_mode) != 0o700):
            _fail("MIGRATION_RECEIPT_UNSAFE")
        fd = os.open(receipt_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            raw = os.read(fd, 1024 * 1024 + 1)
        finally:
            os.close(fd)
        if len(raw) > 1024 * 1024:
            _fail("MIGRATION_RECEIPT_INVALID")
        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    _fail("MIGRATION_RECEIPT_INVALID")
                result[key] = item
            return result
        return MigrationManifest.from_mapping(json.loads(raw, object_pairs_hook=unique))
    except Schema9MigrationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        _fail("MIGRATION_RECEIPT_INVALID")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="schema9-migration")
    parser.add_argument("database")
    parser.add_argument("workspace")
    parser.add_argument("--rollback-peer")
    parser.add_argument("--receipt")
    arguments = parser.parse_args(argv)
    try:
        if arguments.rollback_peer or arguments.receipt:
            if not arguments.rollback_peer or not arguments.receipt:
                _fail("MIGRATION_RECEIPT_REQUIRED")
            result = rollback_schema9(
                arguments.database, arguments.rollback_peer,
                _load_receipt(arguments.receipt))
        else:
            result = migrate_to_schema9(
                arguments.database, PromptArtifactStore(Path(arguments.workspace).resolve()))
            result = result.to_mapping()
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Schema9MigrationError as error:
        print(error.code, file=sys.stderr)
        return 2


__all__ = ["MigrationManifest", "Schema9MigrationError", "darwin_rename_swap",
           "migrate_to_schema9", "rollback_schema9", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
