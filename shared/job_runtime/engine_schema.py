"""Canonical schema-9 DDL and exact structural verification.

This module owns the complete schema.  Runtime startup and the explicit side-file
migrator both consume this contract; neither accepts additive or subset matches.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

SCHEMA_VERSION = 9
_PROOF_COLUMNS = (
    "artifact_ref", "sha256", "length", "version", "source_identity_sha256",
    "binding_sha256", "generation", "proof_origin",
)

DDL = (
    "CREATE TABLE jobs(job_id TEXT PRIMARY KEY,schedule_hash TEXT NOT NULL,cursor REAL NOT NULL)",
    """CREATE TABLE prompt_artifacts(
         ref TEXT PRIMARY KEY,sha256 TEXT NOT NULL,length INTEGER NOT NULL,version INTEGER NOT NULL,
         source_identity_sha256 TEXT NOT NULL,generation TEXT NOT NULL,proof_origin TEXT NOT NULL
         CHECK(proof_origin IN ('native_v1','backfilled_v8')))""",
    """CREATE TABLE slots(
         slot_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,scheduled_at REAL NOT NULL,
         expires_at REAL NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
         next_attempt_at REAL,updated_at REAL NOT NULL,code TEXT NOT NULL,
         provider TEXT,operation_id TEXT,replay_contract TEXT,replay_contract_sha256 TEXT,
         retry_policy TEXT,retry_policy_fingerprint TEXT,retry_deadline REAL,
         circuit_profile TEXT,circuit_resource_hash TEXT,circuit_config TEXT,circuit_config_sha256 TEXT,
         artifact_ref TEXT,sha256 TEXT,length INTEGER,version INTEGER,
         source_identity_sha256 TEXT,binding_sha256 TEXT,generation TEXT,
         proof_origin TEXT NOT NULL DEFAULT 'legacy_unbound'
         CHECK(proof_origin IN ('native_v1','backfilled_v8','legacy_unbound')),
         FOREIGN KEY(job_id) REFERENCES jobs(job_id),
         FOREIGN KEY(artifact_ref) REFERENCES prompt_artifacts(ref))""",
    "CREATE INDEX slot_due ON slots(status,next_attempt_at,scheduled_at)",
    "CREATE UNIQUE INDEX job_one_running ON slots(job_id) WHERE status='running'",
    """CREATE TABLE attempts(
         attempt_id TEXT PRIMARY KEY,slot_id TEXT NOT NULL,attempt_no INTEGER NOT NULL,
         started_at REAL NOT NULL,ended_at REAL,status TEXT NOT NULL,code TEXT NOT NULL,receipt TEXT,
         artifact_ref TEXT,sha256 TEXT,length INTEGER,version INTEGER,
         source_identity_sha256 TEXT,binding_sha256 TEXT,generation TEXT,
         proof_origin TEXT NOT NULL DEFAULT 'legacy_unbound'
         CHECK(proof_origin IN ('native_v1','backfilled_v8','legacy_unbound')),
         FOREIGN KEY(slot_id) REFERENCES slots(slot_id),
         FOREIGN KEY(artifact_ref) REFERENCES prompt_artifacts(ref))""",
    "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
    """CREATE TABLE delivery_reconciliations(
         slot_id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL,message_id TEXT NOT NULL,
         payload_digest TEXT NOT NULL,verified_at TEXT NOT NULL,recorded_at REAL NOT NULL,
         receipt TEXT NOT NULL,prompt_binding_sha256 TEXT,
         FOREIGN KEY(attempt_id) REFERENCES attempts(attempt_id))""",
    """CREATE TABLE provider_results(
         attempt_id TEXT PRIMARY KEY,slot_id TEXT NOT NULL,canonical_json TEXT NOT NULL,
         canonical_sha256 TEXT NOT NULL,provider TEXT NOT NULL,operation_id TEXT NOT NULL,
         phase TEXT NOT NULL,submission TEXT NOT NULL,terminal_proof TEXT NOT NULL,
         status TEXT NOT NULL,failure_kind TEXT NOT NULL,recorded_at REAL NOT NULL,
         prompt_binding_sha256 TEXT,
         FOREIGN KEY(attempt_id) REFERENCES attempts(attempt_id))""",
    """CREATE TABLE retry_decisions(
         attempt_id TEXT PRIMARY KEY,slot_id TEXT NOT NULL,canonical_json TEXT NOT NULL,
         policy_fingerprint TEXT NOT NULL,policy_version INTEGER NOT NULL,
         delay_seconds REAL,retry_after_at REAL,next_attempt_at REAL,deadline REAL,
         recorded_at REAL NOT NULL,prompt_binding_sha256 TEXT)""",
    """CREATE TABLE reconciliation_records(
         reconciliation_id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL UNIQUE,slot_id TEXT NOT NULL,
         operation_id TEXT NOT NULL,slot_operation_scope TEXT NOT NULL,
         proof_json TEXT NOT NULL,proof_sha256 TEXT NOT NULL,evidence_bytes BLOB NOT NULL,
         evidence_ref TEXT NOT NULL,evidence_sha256 TEXT NOT NULL,
         adapter_identity TEXT NOT NULL,adapter_version TEXT NOT NULL,recorded_at REAL NOT NULL,
         prompt_binding_sha256 TEXT,
         FOREIGN KEY(attempt_id) REFERENCES attempts(attempt_id))""",
    """CREATE TABLE reconciliation_consumptions(
         reconciliation_id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL UNIQUE,
         retry_decision_attempt_id TEXT NOT NULL,consumed_at REAL NOT NULL,
         prompt_binding_sha256 TEXT,
         FOREIGN KEY(reconciliation_id) REFERENCES reconciliation_records(reconciliation_id),
         FOREIGN KEY(attempt_id) REFERENCES attempts(attempt_id),
         FOREIGN KEY(retry_decision_attempt_id) REFERENCES retry_decisions(attempt_id))""",
    """CREATE TABLE circuits(
         provider TEXT NOT NULL,profile TEXT NOT NULL,resource_hash TEXT NOT NULL,
         scope_sha256 TEXT NOT NULL,config_sha256 TEXT NOT NULL,generation INTEGER NOT NULL,
         state TEXT NOT NULL,transient_failures INTEGER NOT NULL,opened_until REAL,
         probe_owner TEXT,probe_expires REAL,updated_at REAL NOT NULL,
         PRIMARY KEY(provider,profile,resource_hash))""",
    "CREATE UNIQUE INDEX circuit_scope_digest ON circuits(scope_sha256)",
    """CREATE TABLE provider_output_custody(
         attempt_id TEXT PRIMARY KEY,slot_id TEXT NOT NULL,prompt_binding_sha256 TEXT,
         state TEXT NOT NULL CHECK(state IN ('pending','complete','failed','unknown')),
         output_count INTEGER NOT NULL CHECK(output_count>=0),
         output_bytes INTEGER NOT NULL CHECK(output_bytes>=0),
         started_at REAL NOT NULL,completed_at REAL,updated_at REAL NOT NULL,
         code TEXT NOT NULL CHECK(code GLOB '[A-Z]*' AND length(code) BETWEEN 1 AND 96),
         FOREIGN KEY(attempt_id) REFERENCES attempts(attempt_id))""",
    """CREATE TRIGGER slot_prompt_complete_insert BEFORE INSERT ON slots WHEN NOT (
         (NEW.proof_origin='legacy_unbound' AND NEW.artifact_ref IS NULL
          AND NEW.sha256 IS NULL AND NEW.length IS NULL AND NEW.version IS NULL
          AND NEW.source_identity_sha256 IS NULL AND NEW.binding_sha256 IS NULL AND NEW.generation IS NULL)
         OR
         (NEW.proof_origin IN ('native_v1','backfilled_v8') AND NEW.artifact_ref IS NOT NULL
          AND NEW.sha256 IS NOT NULL AND NEW.length IS NOT NULL AND NEW.version IS NOT NULL
          AND NEW.source_identity_sha256 IS NOT NULL AND NEW.binding_sha256 IS NOT NULL
          AND NEW.generation IS NOT NULL))
         BEGIN SELECT RAISE(ABORT,'slot prompt proof incomplete'); END""",
    """CREATE TRIGGER slot_prompt_artifact_match_insert BEFORE INSERT ON slots
         WHEN NEW.proof_origin IN ('native_v1','backfilled_v8') AND NOT EXISTS(
          SELECT 1 FROM prompt_artifacts p WHERE p.ref=NEW.artifact_ref
          AND p.sha256=NEW.sha256 AND p.length=NEW.length AND p.version=NEW.version
          AND p.source_identity_sha256=NEW.source_identity_sha256
          AND p.generation=NEW.generation AND p.proof_origin=NEW.proof_origin)
         BEGIN SELECT RAISE(ABORT,'slot artifact metadata mismatch'); END""",
    """CREATE TRIGGER immutable_slot_prompt_update BEFORE UPDATE OF
         artifact_ref,sha256,length,version,source_identity_sha256,binding_sha256,generation,proof_origin
         ON slots WHEN NOT (
          NEW.artifact_ref IS OLD.artifact_ref AND NEW.sha256 IS OLD.sha256
          AND NEW.length IS OLD.length AND NEW.version IS OLD.version
          AND NEW.source_identity_sha256 IS OLD.source_identity_sha256
          AND NEW.binding_sha256 IS OLD.binding_sha256 AND NEW.generation IS OLD.generation
          AND NEW.proof_origin IS OLD.proof_origin)
         BEGIN SELECT RAISE(ABORT,'slot prompt proof is immutable'); END""",
    """CREATE TRIGGER attempt_prompt_exact_insert BEFORE INSERT ON attempts WHEN NOT EXISTS(
         SELECT 1 FROM slots s WHERE s.slot_id=NEW.slot_id
         AND s.artifact_ref IS NEW.artifact_ref AND s.sha256 IS NEW.sha256
         AND s.length IS NEW.length AND s.version IS NEW.version
         AND s.source_identity_sha256 IS NEW.source_identity_sha256
         AND s.binding_sha256 IS NEW.binding_sha256 AND s.generation IS NEW.generation
         AND s.proof_origin IS NEW.proof_origin)
         BEGIN SELECT RAISE(ABORT,'attempt prompt proof mismatch'); END""",
    """CREATE TRIGGER guarded_attempt_update BEFORE UPDATE ON attempts WHEN NOT (
         (OLD.status='running' AND OLD.ended_at IS NULL
          AND NEW.status IN ('succeeded','failed','unknown','retry_wait')
          AND NEW.attempt_id=OLD.attempt_id AND NEW.slot_id=OLD.slot_id
          AND NEW.attempt_no=OLD.attempt_no AND NEW.started_at=OLD.started_at
          AND NEW.ended_at IS NOT NULL)
         OR
         (OLD.status='unknown' AND OLD.ended_at IS NOT NULL
          AND NEW.status IN ('succeeded','failed') AND NEW.code='OPERATOR_RECONCILED'
          AND NEW.receipt IS NOT NULL AND NEW.attempt_id=OLD.attempt_id
          AND NEW.slot_id=OLD.slot_id AND NEW.attempt_no=OLD.attempt_no
          AND NEW.started_at=OLD.started_at AND NEW.ended_at IS NOT NULL
          AND NEW.ended_at>=OLD.ended_at))
         OR NOT (NEW.artifact_ref IS OLD.artifact_ref AND NEW.sha256 IS OLD.sha256
          AND NEW.length IS OLD.length AND NEW.version IS OLD.version
          AND NEW.source_identity_sha256 IS OLD.source_identity_sha256
          AND NEW.binding_sha256 IS OLD.binding_sha256 AND NEW.generation IS OLD.generation
          AND NEW.proof_origin IS OLD.proof_origin)
         BEGIN SELECT RAISE(ABORT,'attempt lifecycle is immutable'); END""",
    "CREATE TRIGGER immutable_attempt_delete BEFORE DELETE ON attempts BEGIN SELECT RAISE(ABORT,'attempt lifecycle is immutable'); END",
    "CREATE TRIGGER immutable_prompt_artifacts_update BEFORE UPDATE ON prompt_artifacts BEGIN SELECT RAISE(ABORT,'prompt artifact metadata is immutable'); END",
    "CREATE TRIGGER immutable_prompt_artifacts_delete BEFORE DELETE ON prompt_artifacts BEGIN SELECT RAISE(ABORT,'prompt artifact metadata is immutable'); END",
)

_IMMUTABLE = {
    "delivery_reconciliations": "delivery reconciliation",
    "provider_results": "provider result",
    "retry_decisions": "retry decision",
    "reconciliation_records": "reconciliation",
    "reconciliation_consumptions": "reconciliation consumption",
}


def _dependent_trigger(table: str, attempt_expression: str) -> str:
    return f"""CREATE TRIGGER bind_{table}_insert BEFORE INSERT ON {table} WHEN NOT EXISTS(
        SELECT 1 FROM attempts a WHERE a.attempt_id={attempt_expression}
        AND a.slot_id=NEW.slot_id AND a.binding_sha256 IS NEW.prompt_binding_sha256)
        BEGIN SELECT RAISE(ABORT,'dependent prompt binding mismatch'); END"""


EXTRA_DDL = tuple(
    sql for table, label in _IMMUTABLE.items() for sql in (
        f"CREATE TRIGGER immutable_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'{label} is immutable'); END",
        f"CREATE TRIGGER immutable_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'{label} is immutable'); END",
    )
) + (
    _dependent_trigger("delivery_reconciliations", "NEW.attempt_id"),
    _dependent_trigger("provider_results", "NEW.attempt_id"),
    _dependent_trigger("retry_decisions", "CASE WHEN instr(NEW.attempt_id,':reconciliation')>0 THEN substr(NEW.attempt_id,1,instr(NEW.attempt_id,':reconciliation')-1) ELSE NEW.attempt_id END"),
    _dependent_trigger("reconciliation_records", "NEW.attempt_id"),
    """CREATE TRIGGER bind_reconciliation_consumptions_insert BEFORE INSERT ON reconciliation_consumptions
        WHEN NOT EXISTS(SELECT 1 FROM attempts a WHERE a.attempt_id=NEW.attempt_id
        AND a.binding_sha256 IS NEW.prompt_binding_sha256)
        BEGIN SELECT RAISE(ABORT,'dependent prompt binding mismatch'); END""",
    """CREATE TRIGGER bind_provider_output_custody_insert BEFORE INSERT ON provider_output_custody
        WHEN NOT EXISTS(SELECT 1 FROM attempts a WHERE a.attempt_id=NEW.attempt_id
        AND a.slot_id=NEW.slot_id AND a.binding_sha256 IS NEW.prompt_binding_sha256)
        BEGIN SELECT RAISE(ABORT,'dependent prompt binding mismatch'); END""",
    """CREATE TRIGGER guarded_provider_output_custody_update BEFORE UPDATE ON provider_output_custody
        WHEN NOT (OLD.state='pending' AND NEW.state IN ('complete','failed','unknown')
          AND NEW.attempt_id=OLD.attempt_id AND NEW.slot_id=OLD.slot_id
          AND NEW.prompt_binding_sha256 IS OLD.prompt_binding_sha256
          AND NEW.started_at=OLD.started_at AND NEW.completed_at IS NOT NULL
          AND NEW.updated_at>=OLD.updated_at)
        BEGIN SELECT RAISE(ABORT,'provider output custody lifecycle is immutable'); END""",
    """CREATE TRIGGER immutable_provider_output_custody_delete BEFORE DELETE ON provider_output_custody
        BEGIN SELECT RAISE(ABORT,'provider output custody is immutable'); END""",
)
ALL_DDL = DDL + EXTRA_DDL


def _normalize_sql(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def schema_document(db: sqlite3.Connection) -> dict:
    objects = []
    rows = db.execute("""SELECT type,name,tbl_name,sql FROM sqlite_master
                         WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name""").fetchall()
    for kind, name, table, sql in rows:
        item = {"type": kind, "name": name, "table": table, "sql": _normalize_sql(sql)}
        if kind == "table":
            item["columns"] = [list(row) for row in db.execute(
                f'PRAGMA table_xinfo("{name}")').fetchall()]
        if kind == "index":
            item["index"] = [list(row) for row in db.execute(
                f'PRAGMA index_xinfo("{name}")').fetchall()]
        objects.append(item)
    return {"user_version": db.execute("PRAGMA user_version").fetchone()[0],
            "objects": objects}


def prompt_binding_sha256(job_id: str, slot_id: str, values: dict) -> str:
    document = {
        "schema": 1, "job_id": job_id, "slot_id": slot_id,
        "artifact": {key: values[key] for key in _PROOF_COLUMNS if key != "binding_sha256"},
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def schema_fingerprint(db: sqlite3.Connection) -> str:
    encoded = json.dumps(schema_document(db), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def create_schema9(db: sqlite3.Connection, *, execute=None) -> None:
    execute = execute or (lambda connection, statement: connection.execute(statement))
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("BEGIN IMMEDIATE")
    try:
        for statement in ALL_DDL:
            execute(db, statement)
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _expected_fingerprint() -> str:
    db = sqlite3.connect(":memory:")
    try:
        create_schema9(db)
        return schema_fingerprint(db)
    finally:
        db.close()


SCHEMA9_FINGERPRINT = _expected_fingerprint()


def verify_schema9(db: sqlite3.Connection) -> str:
    if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise ValueError("DATABASE_SCHEMA_VERSION_MISMATCH")
    actual = schema_fingerprint(db)
    if actual != SCHEMA9_FINGERPRINT:
        raise ValueError("DATABASE_SCHEMA_FINGERPRINT_MISMATCH")
    integrity = db.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or integrity[0] != "ok":
        raise ValueError("DATABASE_INTEGRITY_CHECK_FAILED")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("DATABASE_FOREIGN_KEY_CHECK_FAILED")
    if db.execute("""SELECT 1 FROM slots s LEFT JOIN prompt_artifacts p ON p.ref=s.artifact_ref
        WHERE (s.proof_origin='legacy_unbound' AND (s.artifact_ref IS NOT NULL OR s.binding_sha256 IS NOT NULL))
        OR (s.proof_origin IN ('native_v1','backfilled_v8') AND (
          p.ref IS NULL OR p.sha256<>s.sha256 OR p.length<>s.length OR p.version<>s.version
          OR p.source_identity_sha256<>s.source_identity_sha256 OR p.generation<>s.generation
          OR p.proof_origin<>s.proof_origin)) LIMIT 1""").fetchone() is not None:
        raise ValueError("DATABASE_PROMPT_ARTIFACT_JOIN_FAILED")
    if db.execute("""SELECT 1 FROM attempts a JOIN slots s ON s.slot_id=a.slot_id WHERE
        NOT (a.artifact_ref IS s.artifact_ref AND a.sha256 IS s.sha256 AND a.length IS s.length
        AND a.version IS s.version AND a.source_identity_sha256 IS s.source_identity_sha256
        AND a.binding_sha256 IS s.binding_sha256 AND a.generation IS s.generation
        AND a.proof_origin IS s.proof_origin) LIMIT 1""").fetchone() is not None:
        raise ValueError("DATABASE_ATTEMPT_BINDING_JOIN_FAILED")
    return actual


__all__ = [
    "SCHEMA_VERSION", "SCHEMA9_FINGERPRINT", "ALL_DDL", "create_schema9",
    "schema_document", "schema_fingerprint", "prompt_binding_sha256", "verify_schema9",
]
