"""Provider-free runtime-acceptance email synchronization.

This module composes a sanitized Codex/Claude acceptance summary and coordinates
an injected Gmail adapter with its own simple-text acceptance outbox. This is an
intentional domain seam from Niulai's multipart HTML-plus-two-PDF report outbox.
It performs no OAuth, network, scheduler, or credential work itself. ``send_once``
is the production runtime entrypoint; prepare, claim, accepted, unknown and exact
reconciliation preserve at-most-once delivery.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Protocol


class EmailSyncError(ValueError):
    """Stable failure code; input and provider exception text are never exposed."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EmailSyncError(code)


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_CLAIM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_GMAIL_ID = re.compile(r"[0-9a-f]{8,64}")
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}")
_AWARE_TIME_MIN = 20
def _tool_aliases(short_name: str) -> frozenset[str]:
    return frozenset({short_name, f"mcp__codex_apps__{short_name}"})


_SEND_TOOLS = _tool_aliases("gmail_send_email") | _tool_aliases("gmail_send_draft")
_READ_TOOLS = _tool_aliases("gmail_read_email")
_DRAFT_TOOLS = _tool_aliases("gmail_create_draft")
_PROFILE_TOOLS = _tool_aliases("gmail_get_profile")
_GMAIL_TOOLS = _SEND_TOOLS | _READ_TOOLS | _DRAFT_TOOLS | _PROFILE_TOOLS
_ALLOWED_NON_GMAIL_TOOLS = (frozenset({"command_execution"})
                            | _tool_aliases("sites_get_site")
                            | _tool_aliases("metadata_search"))
_ALLOWED_OPERATIONAL_TOOLS = _GMAIL_TOOLS | _ALLOWED_NON_GMAIL_TOOLS
_TEXT_EVIDENCE_FIELDS = frozenset({
    "message_id", "email_thread_id", "send_event_id", "read_event_id",
    "recipient_sha256", "subject_sha256", "body_sha256",
    "delivery_payload_sha256", "sender_identity_sha256",
    "profile_identity_sha256", "raw_readback_sha256", "readback_verified_at",
})
_ALLOWED_EXECUTION = frozenset({"pending", "passed", "partial", "failed", "unverified"})
_ALLOWED_EMAIL = frozenset({"pending", "verified", "failed", "unknown"})
_FORBIDDEN_KEY_PARTS = ("token", "secret", "credential", "oauth", "raw", "private", "password")
_FORBIDDEN_TEXT = (
    re.compile(r"(?i)\b(?:bearer|api[_ -]?key|access[_ -]?token|refresh[_ -]?token)\b"),
    re.compile(r"(?:^|\s)(?:/Users/|/home/|~[/\\]|[A-Za-z]:[/\\])"),
    re.compile(r"(?i)(?:niulai-private|\.job-runtime|\.niulai-state|private://|file://)"),
)


class AcceptanceOutbox:
    """Workspace-local durable ledger for sanitized simple-text acceptance mail.

    The digest binds the exact message and detached Gmail claim. Claims move only
    ``prepared -> sending -> unknown|accepted``; neither sending nor unknown can
    return to prepared, so an ambiguous effect is never replayed.
    """

    def __init__(self, db_path: str | Path, workspace_root: str | Path):
        try:
            workspace = Path(workspace_root).resolve(strict=True)
            raw = Path(db_path).absolute()
            state = workspace / ".job-runtime"
            _require(".." not in raw.parts, "OUTBOX_PATH_ESCAPE")
            _require(raw.is_relative_to(state), "OUTBOX_OUTSIDE_WORKSPACE_STATE")
            state.mkdir(mode=0o700, exist_ok=True)
            raw.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            for item in (raw, *raw.parents):
                if item.exists() and item.is_symlink():
                    raise EmailSyncError("OUTBOX_SYMLINK_REJECTED")
            _require(raw.resolve().is_relative_to(state.resolve()), "OUTBOX_PATH_ESCAPE")
            fd = os.open(raw, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            raw.chmod(0o600)
            for parent in (raw.parent, *raw.parent.parents):
                if parent.is_relative_to(state):
                    parent.chmod(0o700)
            self.path = raw
            with self._connect() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS outbox (
                    key TEXT PRIMARY KEY, digest TEXT NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL
                    CHECK(status IN ('prepared','sending','unknown','accepted')),
                    attempt_id TEXT, message_id TEXT, prepared_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, verified_digest TEXT,
                    verified_at TEXT)""")
        except EmailSyncError:
            raise
        except (OSError, sqlite3.Error, ValueError):
            raise EmailSyncError("OUTBOX_STORAGE_FAILED") from None

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=DELETE")
        return db

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get(self, key: str) -> Mapping[str, Any] | None:
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT key,digest,status,attempt_id,message_id,prepared_at,"
                    "updated_at,verified_digest,verified_at FROM outbox WHERE key=?",
                    (key,),
                ).fetchone()
            return dict(row) if row else None
        except (OSError, sqlite3.Error):
            raise EmailSyncError("OUTBOX_STORAGE_FAILED") from None

    def prepare(self, key: str, message: Mapping[str, str], *, recipient: str,
                profile_email: str, payload_digest: str | None = None) -> Mapping[str, Any]:
        _require(isinstance(key, str) and 1 <= len(key) <= 512
                 and not any(char in key for char in "\r\n\0"),
                 "DELIVERY_KEY_INVALID")
        checked = {"to": _recipient(message.get("to")),
                   "subject": message.get("subject"), "body": message.get("body")}
        _require(set(message) == set(checked)
                 and isinstance(checked["subject"], str)
                 and isinstance(checked["body"], str), "MESSAGE_INVALID")
        _require(checked["to"] == _recipient(recipient), "RECIPIENT_MISMATCH")
        _recipient(profile_email)
        digest = payload_digest or message_digest(checked)
        _sha_text(digest, "OUTBOX_PAYLOAD_DIGEST_INVALID")
        payload = json.dumps(checked, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT digest,payload FROM outbox WHERE key=?",
                                 (key,)).fetchone()
                if old:
                    _require(old["digest"] == digest and old["payload"] == payload,
                             "OUTBOX_PAYLOAD_CONFLICT")
                else:
                    now = self._now()
                    db.execute(
                        "INSERT INTO outbox VALUES (?,?,?,'prepared',NULL,NULL,?,?,NULL,NULL)",
                        (key, digest, payload, now, now),
                    )
        except EmailSyncError:
            raise
        except (OSError, sqlite3.Error):
            raise EmailSyncError("OUTBOX_STORAGE_FAILED") from None
        row = self.get(key)
        _require(row is not None, "OUTBOX_STORAGE_FAILED")
        return row

    def claim(self, key: str, attempt_id: str) -> Mapping[str, str]:
        _require(isinstance(attempt_id, str) and _CLAIM_ID.fullmatch(attempt_id) is not None,
                 "ATTEMPT_ID_INVALID")
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT status,payload FROM outbox WHERE key=?",
                                 (key,)).fetchone()
                _require(row is not None, "OUTBOX_ITEM_MISSING")
                _require(row["status"] == "prepared", "OUTBOX_NOT_SENDABLE")
                db.execute("UPDATE outbox SET status='sending',attempt_id=?,updated_at=? "
                           "WHERE key=?", (attempt_id, self._now(), key))
                payload = json.loads(row["payload"])
        except EmailSyncError:
            raise
        except (OSError, sqlite3.Error, ValueError):
            raise EmailSyncError("OUTBOX_STORAGE_FAILED") from None
        _require(isinstance(payload, dict), "OUTBOX_STORAGE_FAILED")
        return payload

    def accepted(self, key: str, attempt_id: str,
                 message_id: str) -> Mapping[str, Any]:
        _require(isinstance(message_id, str) and _GMAIL_ID.fullmatch(message_id) is not None,
                 "GMAIL_MESSAGE_ID_INVALID")
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT status,attempt_id,message_id FROM outbox WHERE key=?",
                                 (key,)).fetchone()
                _require(row is not None and row["attempt_id"] == attempt_id,
                         "ATTEMPT_MISMATCH")
                if row["status"] == "accepted":
                    _require(row["message_id"] == message_id, "MESSAGE_ID_CONFLICT")
                else:
                    _require(row["status"] == "sending", "ACCEPTANCE_REQUIRES_SENDING")
                    db.execute("UPDATE outbox SET status='accepted',message_id=?,updated_at=? "
                               "WHERE key=?", (message_id, self._now(), key))
        except EmailSyncError:
            raise
        except (OSError, sqlite3.Error):
            raise EmailSyncError("OUTBOX_STORAGE_FAILED") from None
        row = self.get(key)
        _require(row is not None, "OUTBOX_STORAGE_FAILED")
        return row

    def unknown(self, key: str, attempt_id: str) -> Mapping[str, Any]:
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT status,attempt_id FROM outbox WHERE key=?",
                                 (key,)).fetchone()
                _require(row is not None and row["attempt_id"] == attempt_id,
                         "ATTEMPT_MISMATCH")
                if row["status"] == "unknown":
                    pass
                else:
                    _require(row["status"] == "sending", "UNKNOWN_TRANSITION_REJECTED")
                    db.execute("UPDATE outbox SET status='unknown',updated_at=? WHERE key=?",
                               (self._now(), key))
        except EmailSyncError:
            raise
        except (OSError, sqlite3.Error):
            raise EmailSyncError("OUTBOX_STORAGE_FAILED") from None
        result = self.get(key)
        _require(result is not None, "OUTBOX_STORAGE_FAILED")
        return result

    def reconcile_accepted(self, key: str, *, message_id: str,
                           verified_digest: str) -> Mapping[str, Any]:
        _require(isinstance(message_id, str) and _GMAIL_ID.fullmatch(message_id) is not None,
                 "GMAIL_MESSAGE_ID_INVALID")
        _sha_text(verified_digest, "READBACK_DIGEST_INVALID")
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT status,digest,message_id FROM outbox WHERE key=?",
                                 (key,)).fetchone()
                _require(row is not None, "OUTBOX_ITEM_MISSING")
                _require(row["digest"] == verified_digest, "READBACK_DIGEST_MISMATCH")
                _require(row["status"] in {"sending", "unknown", "accepted"},
                         "RECONCILIATION_REJECTED")
                if row["status"] == "accepted":
                    _require(row["message_id"] == message_id, "MESSAGE_ID_CONFLICT")
                now = self._now()
                db.execute("UPDATE outbox SET status='accepted',message_id=?,"
                           "verified_digest=?,verified_at=?,updated_at=? WHERE key=?",
                           (message_id, verified_digest, now, now, key))
        except EmailSyncError:
            raise
        except (OSError, sqlite3.Error):
            raise EmailSyncError("OUTBOX_STORAGE_FAILED") from None
        result = self.get(key)
        _require(result is not None, "OUTBOX_STORAGE_FAILED")
        return result


class GmailAdapter(Protocol):
    """Existing owner-configured Gmail boundary; implementations perform I/O."""

    def oauth_ready(self) -> bool: ...
    def send(self, message: Mapping[str, str]) -> str: ...


@dataclass(frozen=True)
class AcceptanceSummary:
    change_id: str
    scope: str
    execution_status: str
    email_status: str
    sender: str
    subject: str
    body: str
    delivery_refs: tuple[str, str] | tuple[()] = ()
    verification_sha256: str | None = None

    def message(self, recipient: str) -> dict[str, str]:
        return {"to": _recipient(recipient), "subject": self.subject, "body": self.body}


@dataclass(frozen=True)
class GmailRuntimeAttestation:
    """Scheduler identity plus service/adapter source attestations.

    These hashes are a separate namespace from ``HostAcceptanceSummary``'s
    human-facing notification host/run/candidate identifiers.
    """

    job_id: str
    slot_id: str
    attempt_id: str
    service_source_sha256: str
    service_generation_sha256: str
    adapter_source_sha256: str


@dataclass(frozen=True)
class HostAcceptanceSummary:
    """One immutable host/run/candidate notification payload."""

    host: str
    run_id: str
    candidate_id: str
    scope: str
    execution_status: str
    mode: str
    request_id: str
    slot_id: str | None
    result_sha256: str
    subject: str
    body: str

    def message(self, recipient: str) -> dict[str, str]:
        return {"to": _recipient(recipient), "subject": self.subject, "body": self.body}


_ARTIFACT_REF_TOKEN = object()
_ARTIFACT_RECEIPT_REQUIRED = frozenset({
    "thread_id", "tool_names", "gmail_tool_names", "final", "final_sha256",
    "final_evidence_trust", "gmail_operational_evidence", "gmail_claim",
})
_ARTIFACT_RECEIPT_OUTER = _ARTIFACT_RECEIPT_REQUIRED | frozenset({
    "started_at", "requested_model", "observed_model", "automatic_retry",
    "fallback_used", "dispatch_phase", "ended_at", "exit_code", "phase",
    "approval_mode", "writable_roots", "run_directory", "usage",
    "turn_completed", "tool_failures", "model_final_evidence_trust",
})
_ARTIFACT_FINAL_FIELDS = frozenset({
    "status", "gmail_verified", "delivery_verified", "message_id",
    "email_message_id", "email_thread_id", "send_event_id", "read_event_id",
    "recipient_sha256", "subject_sha256", "body_sha256",
    "delivery_payload_sha256", "sender_identity_sha256",
    "profile_identity_sha256", "raw_readback_sha256", "readback_verified_at",
})
_ARTIFACT_FORBIDDEN_KEYS = ("token", "secret", "credential", "oauth", "password",
                            "private", "path", "directory", "report")


class AcceptanceArtifactRef:
    """Opaque, immutable capability issued by one exact store instance."""

    __slots__ = ("_owner", "_ref", "_digest")

    def __init__(self, owner: object, ref: str, digest: str, token: object):
        _require(token is _ARTIFACT_REF_TOKEN, "ACCEPTANCE_ARTIFACT_REF_INVALID")
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_ref", ref)
        object.__setattr__(self, "_digest", digest)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("immutable")

    @property
    def ref(self) -> str:
        return self._ref

    @property
    def digest(self) -> str:
        return self._digest


class AcceptanceArtifactStore:
    """Nominal workspace-local store for fixed, hash-only delivery records.

    Raw addresses, model/provider text, arbitrary final mappings and private paths
    are verification inputs only and are never persisted. Refs are valid only for
    the exact store object that issued them; fresh wrappers and duck readers fail.
    """

    def __init__(self, db_path: str | Path, workspace_root: str | Path):
        try:
            workspace = Path(workspace_root).resolve(strict=True)
            raw = Path(db_path).absolute()
            state = workspace / ".job-runtime"
            _require(".." not in raw.parts, "ARTIFACT_STORE_PATH_ESCAPE")
            _require(raw.is_relative_to(state), "ARTIFACT_STORE_OUTSIDE_WORKSPACE_STATE")
            state.mkdir(mode=0o700, exist_ok=True)
            raw.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            for item in (raw, *raw.parents):
                if item.exists() and item.is_symlink():
                    raise EmailSyncError("ARTIFACT_STORE_SYMLINK_REJECTED")
            _require(raw.resolve().is_relative_to(state.resolve()),
                     "ARTIFACT_STORE_PATH_ESCAPE")
            fd = os.open(raw, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            raw.chmod(0o600)
            for parent in (raw.parent, *raw.parent.parents):
                if parent.is_relative_to(state):
                    parent.chmod(0o700)
            self.path = raw
            with self._connect() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS records (
                    ref TEXT PRIMARY KEY, digest TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL)""")
        except EmailSyncError:
            raise
        except (OSError, sqlite3.Error, ValueError):
            raise EmailSyncError("ARTIFACT_STORE_FAILED") from None

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=DELETE")
        return db

    @staticmethod
    def _safe_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
        """Validate the real closed host envelope, then return its safe projection."""
        _require(isinstance(receipt, Mapping)
                 and _ARTIFACT_RECEIPT_REQUIRED <= set(receipt)
                 and set(receipt) <= _ARTIFACT_RECEIPT_OUTER,
                 "ACCEPTANCE_RECEIPT_FIELDS_UNSAFE")
        for key in set(receipt) - _ARTIFACT_RECEIPT_REQUIRED:
            normalized = str(key).lower().replace("-", "_")
            _require(not any(part in normalized for part in
                             ("token", "secret", "credential", "oauth", "password")),
                     "ACCEPTANCE_RECEIPT_FIELDS_UNSAFE")
        for key in ("started_at", "ended_at"):
            if key in receipt:
                _aware_time(receipt[key], "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        for key in ("requested_model", "observed_model"):
            value = receipt.get(key)
            _require(value is None or isinstance(value, str)
                     and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value)
                     and not any(pattern.search(value) for pattern in _FORBIDDEN_TEXT),
                     "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        for key in ("automatic_retry", "fallback_used", "turn_completed"):
            if key in receipt:
                _require(type(receipt[key]) is bool,
                         "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        if "dispatch_phase" in receipt:
            _require(receipt["dispatch_phase"] in {"reserved", "exposed", "committed"},
                     "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        if "exit_code" in receipt:
            _require(type(receipt["exit_code"]) is int,
                     "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        if "phase" in receipt:
            _require(receipt["phase"] == "business",
                     "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        if "approval_mode" in receipt:
            _require(receipt["approval_mode"] in {"never", "automatic_review"},
                     "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        if "writable_roots" in receipt:
            roots = receipt["writable_roots"]
            _require(isinstance(roots, list) and len(roots) <= 20
                     and all(isinstance(value, str) and 0 < len(value) <= 256
                             and not Path(value).is_absolute()
                             and ".." not in Path(value).parts for value in roots),
                     "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        if "run_directory" in receipt:
            run_directory = receipt["run_directory"]
            _require(isinstance(run_directory, str) and 0 < len(run_directory) <= 256
                     and not Path(run_directory).is_absolute()
                     and ".." not in Path(run_directory).parts,
                     "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        if "usage" in receipt:
            usage = receipt["usage"]
            _require(usage is None or isinstance(usage, Mapping)
                     and set(usage) <= {"input_tokens", "cached_input_tokens",
                                       "output_tokens"}
                     and all(type(value) is int and value >= 0
                             for value in usage.values()),
                     "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        if "tool_failures" in receipt:
            _require(receipt["tool_failures"] == [],
                     "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        if "model_final_evidence_trust" in receipt:
            _require(receipt["model_final_evidence_trust"] ==
                     "untrusted_model_output", "ACCEPTANCE_RECEIPT_METADATA_UNSAFE")
        final = receipt.get("final")
        _require(isinstance(final, Mapping)
                 and set(final) <= _ARTIFACT_FINAL_FIELDS,
                 "ACCEPTANCE_FINAL_FIELDS_UNSAFE")
        for key, value in final.items():
            normalized = str(key).lower().replace("-", "_")
            _require(not any(part in normalized for part in _ARTIFACT_FORBIDDEN_KEYS),
                     "ACCEPTANCE_FINAL_FIELDS_UNSAFE")
            if isinstance(value, str):
                _require(not any(pattern.search(value) for pattern in _FORBIDDEN_TEXT),
                         "ACCEPTANCE_FINAL_TEXT_UNSAFE")
        return {key: receipt[key] for key in _ARTIFACT_RECEIPT_REQUIRED}


    @staticmethod
    def _record_payload(value: Mapping[str, Any]) -> str:
        _require(set(value) == {
            "version", "change_id_sha256", "scope_sha256",
            "notification_host_sha256", "notification_run_id_sha256",
            "notification_candidate_id_sha256", "notification_key_sha256",
            "execution_status", "result_sha256", "summary_sha256",
            "runtime_attestation_sha256", "delivery_verification_sha256",
        }, "ACCEPTANCE_ARTIFACT_FIELDS_INVALID")
        try:
            return json.dumps(dict(value), ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
        except (TypeError, ValueError):
            raise EmailSyncError("ACCEPTANCE_ARTIFACT_INVALID") from None

    @staticmethod
    def _ref_id(record: Mapping[str, Any]) -> str:
        identity = _canonical_digest({
            "change_id_sha256": record["change_id_sha256"],
            "notification_host_sha256": record["notification_host_sha256"],
            "notification_key_sha256": record["notification_key_sha256"],
        })
        return f"artifact:{identity}"

    def _put_record(self, record: Mapping[str, Any]) -> AcceptanceArtifactRef:
        payload = self._record_payload(record)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        ref = self._ref_id(record)
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute(
                    "SELECT digest,payload FROM records WHERE ref=?", (ref,)
                ).fetchone()
                if old:
                    _require(old["digest"] == digest and old["payload"] == payload,
                             "ACCEPTANCE_ARTIFACT_CONFLICT")
                else:
                    db.execute("INSERT INTO records VALUES (?,?,?,?)",
                               (ref, digest, payload,
                                datetime.now(timezone.utc).isoformat()))
        except EmailSyncError:
            raise
        except (OSError, sqlite3.Error):
            raise EmailSyncError("ARTIFACT_STORE_FAILED") from None
        return AcceptanceArtifactRef(self, ref, digest, _ARTIFACT_REF_TOKEN)

    def _open_record(self, ref: AcceptanceArtifactRef) -> Mapping[str, Any]:
        _require(type(ref) is AcceptanceArtifactRef and ref._owner is self,
                 "COMBINED_ARTIFACT_REF_INVALID")
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT digest,payload FROM records WHERE ref=?", (ref.ref,)
                ).fetchone()
            _require(row is not None and row["digest"] == ref.digest,
                     "ACCEPTANCE_ARTIFACT_MISSING")
            _require(hashlib.sha256(row["payload"].encode()).hexdigest() ==
                     row["digest"], "ACCEPTANCE_ARTIFACT_CORRUPT")
            value = json.loads(row["payload"])
            _require(isinstance(value, dict), "ACCEPTANCE_ARTIFACT_CORRUPT")
            self._record_payload(value)
            return value
        except EmailSyncError:
            raise
        except (OSError, sqlite3.Error, ValueError):
            raise EmailSyncError("ARTIFACT_STORE_FAILED") from None

    def record_verified_delivery(
            self, *, change_id: str, scope: str, result: Mapping[str, Any],
            summary: HostAcceptanceSummary, recipient: str, profile_email: str,
            runtime_attestation: GmailRuntimeAttestation,
            receipt: Mapping[str, Any]) -> AcceptanceArtifactRef:
        """Verify exact transient inputs, then persist only fixed fields/hashes."""
        change_id = _safe_id(change_id, "CHANGE_ID_INVALID")
        scope = _clean_text(scope, "SCOPE_INVALID")
        _require(isinstance(summary, HostAcceptanceSummary), "HOST_SUMMARY_INVALID")
        _require(isinstance(runtime_attestation, GmailRuntimeAttestation),
                 "GMAIL_RUNTIME_ATTESTATION_INVALID")
        canonical_summary = build_host_summary(
            host=summary.host, run_id=summary.run_id,
            candidate_id=summary.candidate_id, scope=summary.scope,
            sender="codex_supervisor", mode=summary.mode,
            request_id=summary.request_id, slot_id=summary.slot_id, result=result)
        _require(summary == canonical_summary, "HOST_SUMMARY_MISMATCH")
        safe_receipt = self._safe_receipt(receipt)
        artifact = verify_codex_business_receipt(
            summary=summary, recipient=recipient, profile_email=profile_email,
            runtime_attestation=runtime_attestation, receipt=safe_receipt)
        summary_sha256 = _canonical_digest({
            "host_sha256": _digest_text(summary.host),
            "run_id_sha256": _digest_text(summary.run_id),
            "candidate_id_sha256": _digest_text(summary.candidate_id),
            "scope_sha256": _digest_text(summary.scope),
            "execution_status": summary.execution_status, "mode": summary.mode,
            "request_id": summary.request_id, "slot_id": summary.slot_id,
            "result_sha256": summary.result_sha256,
            "subject_sha256": _digest_text(summary.subject),
            "body_sha256": _digest_text(summary.body),
        })
        runtime_sha256 = _canonical_digest({
            "job_id": runtime_attestation.job_id,
            "slot_id": runtime_attestation.slot_id,
            "attempt_id": runtime_attestation.attempt_id,
            "service_source_sha256": runtime_attestation.service_source_sha256,
            "service_generation_sha256": runtime_attestation.service_generation_sha256,
            "adapter_source_sha256": runtime_attestation.adapter_source_sha256,
        })
        record = {
            "version": 1,
            "change_id_sha256": _digest_text(change_id),
            "scope_sha256": _digest_text(scope),
            "notification_host_sha256": _digest_text(summary.host),
            "notification_run_id_sha256": _digest_text(summary.run_id),
            "notification_candidate_id_sha256": _digest_text(summary.candidate_id),
            "notification_key_sha256": _digest_text(artifact["notification_key"]),
            "execution_status": summary.execution_status,
            "result_sha256": summary.result_sha256,
            "summary_sha256": summary_sha256,
            "runtime_attestation_sha256": runtime_sha256,
            "delivery_verification_sha256": artifact["verification_sha256"],
        }
        return self._put_record(record)


def _recipient(value: object) -> str:
    _require(isinstance(value, str) and _EMAIL.fullmatch(value) is not None,
             "RECIPIENT_INVALID")
    return value.lower()


def _safe_id(value: object, code: str) -> str:
    _require(isinstance(value, str) and _SAFE_ID.fullmatch(value) is not None, code)
    return value


def _clean_text(value: object, code: str, *, maximum: int = 500) -> str:
    _require(isinstance(value, str), code)
    text = " ".join(value.split())
    _require(bool(text) and len(text) <= maximum and not any(c in text for c in "\r\n\0"), code)
    _require(not any(pattern.search(text) for pattern in _FORBIDDEN_TEXT), code)
    return text


def _clean_values(values: object, code: str) -> tuple[str, ...]:
    _require(isinstance(values, (list, tuple)) and len(values) <= 20, code)
    return tuple(_clean_text(value, code) for value in values)


def _sha_text(value: object, code: str) -> str:
    _require(isinstance(value, str) and _SHA256.fullmatch(value) is not None, code)
    return value


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(value), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _aware_time(value: object, code: str) -> str:
    _require(isinstance(value, str) and _AWARE_TIME_MIN <= len(value) <= 40, code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise EmailSyncError(code) from None
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, code)
    return value


def _gmail_semantic(name: str) -> str | None:
    for short in ("gmail_send_email", "gmail_send_draft", "gmail_read_email",
                  "gmail_create_draft", "gmail_get_profile"):
        if name in _tool_aliases(short):
            return short
    return None


def _validate_gmail_tool_names(value: object, *, mode: str) -> tuple[str, ...]:
    _require(isinstance(value, (list, tuple)) and 2 <= len(value) <= 5,
             "CODEX_GMAIL_TOOL_NAMES_INVALID")
    names = tuple(value)
    semantics = tuple(_gmail_semantic(name) for name in names
                      if isinstance(name, str))
    _require(len(semantics) == len(names)
             and names == tuple(sorted(names))
             and len(set(names)) == len(names)
             and len(set(semantics)) == len(semantics),
             "CODEX_GMAIL_TOOL_NAMES_INVALID")
    observed = set(semantics)
    if mode == "text":
        _require(observed == {"gmail_get_profile", "gmail_send_email",
                              "gmail_read_email"},
                 "CODEX_GMAIL_TOOL_NAMES_INVALID")
    else:
        _require("gmail_get_profile" in observed
                 and "gmail_read_email" in observed
                 and len(observed & {"gmail_send_email", "gmail_send_draft"}) == 1
                 and ("gmail_create_draft" in observed) ==
                     ("gmail_send_draft" in observed)
                 and observed <= {"gmail_get_profile", "gmail_create_draft",
                                  "gmail_send_draft", "gmail_send_email",
                                  "gmail_read_email"},
                 "CODEX_GMAIL_TOOL_NAMES_INVALID")
    return tuple(sorted(names))


def _validate_overall_tool_names(value: object,
                                 gmail_names: tuple[str, ...]) -> tuple[str, ...]:
    _require(isinstance(value, (list, tuple)) and 2 <= len(value) <= 16,
             "CODEX_TOOL_NAMES_INVALID")
    names = tuple(value)
    observed = set(names)
    _require(all(isinstance(name, str) and _EVENT_ID.fullmatch(name) is not None
                 for name in names)
             and names == tuple(sorted(names))
             and len(observed) == len(names)
             and observed <= _ALLOWED_OPERATIONAL_TOOLS
             and observed & _GMAIL_TOOLS == set(gmail_names),
             "CODEX_TOOL_NAMES_INVALID")
    return tuple(sorted(names))


def _validate_result(provider: str, result: object) -> dict[str, Any]:
    code = f"{provider.upper()}_RESULT_INVALID"
    _require(isinstance(result, Mapping), code)
    normalized_keys = {str(key).lower().replace("-", "_") for key in result}
    _require(not any(part in key for key in normalized_keys for part in _FORBIDDEN_KEY_PARTS),
             code)
    required = {"execution_status", "scheduled_at", "actual_timing", "job_id", "session_id",
                "verified_outputs", "coverage", "failure_codes", "recovery", "evidence_refs"}
    _require(set(result) == required, code)
    status = result["execution_status"]
    _require(status in _ALLOWED_EXECUTION, code)
    verified_outputs = _clean_values(result["verified_outputs"], code)
    failure_codes = tuple(_safe_id(value, code)
                          for value in _clean_values(result["failure_codes"], code))
    evidence_refs = tuple(_safe_id(value, code)
                          for value in _clean_values(result["evidence_refs"], code))
    if status == "passed":
        _require(bool(verified_outputs) and bool(evidence_refs) and not failure_codes, code)
    return {
        "execution_status": status,
        "scheduled_at": _clean_text(result["scheduled_at"], code),
        "actual_timing": _clean_text(result["actual_timing"], code),
        "job_id": _safe_id(result["job_id"], code),
        "session_id": _safe_id(result["session_id"], code),
        "verified_outputs": verified_outputs,
        "coverage": _clean_text(result["coverage"], code),
        "failure_codes": failure_codes,
        "recovery": _clean_text(result["recovery"], code),
        "evidence_refs": evidence_refs,
    }


def _result_digest(provider: str, result: Mapping[str, Any]) -> str:
    return _canonical_digest({"provider": provider,
                              "result": _validate_result(provider, result)})


def build_host_summary(*, host: str, run_id: str, candidate_id: str,
                       scope: str, sender: str, mode: str, request_id: str,
                       slot_id: str | None, result: Mapping[str, Any]) -> HostAcceptanceSummary:
    """Build one Codex-supervised, host-specific immutable notification."""
    host = _safe_id(host, "HOST_ID_INVALID")
    run_id = _safe_id(run_id, "RUN_ID_INVALID")
    candidate_id = _safe_id(candidate_id, "CANDIDATE_ID_INVALID")
    scope = _clean_text(scope, "SCOPE_INVALID")
    _require(sender == "codex_supervisor", "SENDER_INVALID")
    _require(mode in {"manual", "scheduled"}, "EXECUTION_MODE_INVALID")
    request_id = _safe_id(request_id, "REQUEST_ID_INVALID")
    if mode == "scheduled":
        slot_id = _safe_id(slot_id, "SLOT_ID_INVALID")
    else:
        _require(slot_id is None, "SLOT_ID_INVALID")
    row = _validate_result(host, result)
    status = row["execution_status"]
    identity = f"{host}:{run_id}:{candidate_id}"
    subject = f"[CODEX] Runtime acceptance | {status} | {identity}"
    lines = [
        "Host-specific runtime acceptance result",
        f"Host: {host}", f"Run: {run_id}", f"Candidate: {candidate_id}",
        f"Scope: {scope}", f"Execution: {status}", f"Mode: {mode}",
        f"Request: {request_id}", f"Slot: {slot_id or 'not_applicable'}",
        f"Scheduled: {row['scheduled_at']}", f"Actual timing: {row['actual_timing']}",
        f"Job/session: {row['job_id']} / {row['session_id']}",
        f"Verified outputs: {', '.join(row['verified_outputs']) or 'none'}",
        f"Coverage/as-of: {row['coverage']}",
        f"Failure codes: {', '.join(row['failure_codes']) or 'none'}",
        f"Recovery/rollback: {row['recovery']}",
        f"Evidence references: {', '.join(row['evidence_refs']) or 'none'}",
        "Production boundaries remain unchanged. This message does not upgrade a partial, failed, or unverified execution.",
    ]
    body = "\n".join(lines)
    _require(len(subject) <= 300 and len(body) <= 20_000, "MESSAGE_INVALID")
    result_sha256 = _canonical_digest({"provider": host, "result": row})
    return HostAcceptanceSummary(host, run_id, candidate_id, scope, status, mode,
                                 request_id, slot_id, result_sha256, subject, body)


def _combined_execution(codex: str, claude: str) -> str:
    if codex == claude == "passed":
        return "passed"
    if "failed" in (codex, claude):
        return "failed"
    if "partial" in (codex, claude):
        return "partial"
    if "unverified" in (codex, claude):
        return "unverified"
    return "pending"


def build_summary(*, change_id: str, scope: str, sender: str,
                  codex: Mapping[str, Any], claude: Mapping[str, Any],
                  email_status: str = "pending") -> AcceptanceSummary:
    """Build the exact sanitized summary. ``sender`` is an owner-configured role."""
    change_id = _safe_id(change_id, "CHANGE_ID_INVALID")
    scope = _clean_text(scope, "SCOPE_INVALID")
    _require(sender in {"codex_supervisor", "claude_supervisor"}, "SENDER_INVALID")
    _require(email_status in _ALLOWED_EMAIL, "EMAIL_STATUS_INVALID")
    rows = {"Codex": _validate_result("codex", codex),
            "Claude": _validate_result("claude", claude)}
    execution = _combined_execution(rows["Codex"]["execution_status"],
                                    rows["Claude"]["execution_status"])
    prefix = "[CODEX] " if sender == "codex_supervisor" else ""
    subject = f"{prefix}Runtime acceptance | {execution} | {change_id}"
    lines = [
        "Combined Codex/Claude runtime acceptance summary",
        f"Change: {change_id}", f"Scope: {scope}", f"Execution verdict: {execution}",
        f"Email synchronization: {email_status}", f"Summary sender: {sender}",
    ]
    for label, row in rows.items():
        lines.extend([
            "", f"{label}:", f"- execution: {row['execution_status']}",
            f"- scheduled: {row['scheduled_at']}", f"- actual timing: {row['actual_timing']}",
            f"- job/session: {row['job_id']} / {row['session_id']}",
            f"- verified outputs: {', '.join(row['verified_outputs']) or 'none'}",
            f"- coverage/as-of: {row['coverage']}",
            f"- failure codes: {', '.join(row['failure_codes']) or 'none'}",
            f"- recovery/rollback: {row['recovery']}",
            f"- evidence references: {', '.join(row['evidence_refs']) or 'none'}",
        ])
    lines.extend(["", "Production boundaries remain unchanged. This summary does not convert a failed, partial, or unverified execution into a pass."])
    return AcceptanceSummary(change_id, scope, execution, email_status, sender,
                             subject, "\n".join(lines))


def notification_key(change_id: str) -> str:
    """Stable logical key: one combined acceptance notification per change."""
    change_id = _safe_id(change_id, "CHANGE_ID_INVALID")
    digest = hashlib.sha256(f"runtime-acceptance:combined:{change_id}".encode()).hexdigest()
    return f"runtime-acceptance:combined:{digest}"


def message_digest(message: Mapping[str, str]) -> str:
    _require(set(message) == {"to", "subject", "body"}, "MESSAGE_INVALID")
    canonical = json.dumps(dict(message), sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode()
    return hashlib.sha256(canonical).hexdigest()


def host_notification_key(host: str, run_id: str, candidate_id: str) -> str:
    """One authoritative key per host/run/candidate; never a combined-send key."""
    host = _safe_id(host, "HOST_ID_INVALID")
    run_id = _safe_id(run_id, "RUN_ID_INVALID")
    candidate_id = _safe_id(candidate_id, "CANDIDATE_ID_INVALID")
    digest = hashlib.sha256(
        f"runtime-acceptance:host:{host}:{run_id}:{candidate_id}".encode()
    ).hexdigest()
    return f"runtime-acceptance:host:{digest}"


def _runtime_attestation(value: object) -> GmailRuntimeAttestation:
    _require(isinstance(value, GmailRuntimeAttestation),
             "GMAIL_RUNTIME_ATTESTATION_INVALID")
    for field in ("job_id", "slot_id", "attempt_id"):
        item = getattr(value, field)
        _require(isinstance(item, str) and _CLAIM_ID.fullmatch(item) is not None,
                 "GMAIL_RUNTIME_ATTESTATION_INVALID")
    for field in ("service_source_sha256", "service_generation_sha256",
                  "adapter_source_sha256"):
        _sha_text(getattr(value, field), "GMAIL_RUNTIME_ATTESTATION_INVALID")
    return value


def build_gmail_claim(summary: HostAcceptanceSummary, recipient: str, *,
                      profile_email: str,
                      runtime_attestation: GmailRuntimeAttestation) -> dict[str, Any]:
    """Build the exact integrated text-mode pre-send claim.

    ``raw_readback_sha256`` is intentionally absent: it is post-send host evidence.
    """
    _require(isinstance(summary, HostAcceptanceSummary), "HOST_SUMMARY_INVALID")
    identity = _runtime_attestation(runtime_attestation)
    message = summary.message(recipient)
    sender = _recipient(profile_email)
    canonical_payload = {
        "sender": sender,
        "recipient": message["to"],
        "subject": message["subject"],
        "body": message["body"],
    }
    sender_digest = _digest_text(sender)
    claim: dict[str, Any] = {
        "schema_version": 1,
        "job_id": identity.job_id,
        "slot_id": identity.slot_id,
        "attempt_id": identity.attempt_id,
        "host": identity.service_source_sha256,
        "run": identity.service_generation_sha256,
        "candidate": identity.adapter_source_sha256,
        "mode": "text",
        "delivery_payload_sha256": _canonical_digest(canonical_payload),
        "recipient_sha256": _digest_text(message["to"]),
        "subject_sha256": _digest_text(message["subject"]),
        "sender_identity_sha256": sender_digest,
        "profile_identity_sha256": sender_digest,
        "body_sha256": _digest_text(message["body"]),
    }
    claim["payload_sha256"] = _canonical_digest(claim)
    return claim


def host_payload_digest(message: Mapping[str, str],
                        gmail_claim: Mapping[str, Any]) -> str:
    """Bind immutable outbox content to its exact scheduler/attestation claim."""
    claim_sha256 = _sha_text(gmail_claim.get("payload_sha256"),
                             "GMAIL_CLAIM_DIGEST_INVALID")
    return _canonical_digest({"message_sha256": message_digest(message),
                              "claim_sha256": claim_sha256})


def claim_host_delivery(*, summary: HostAcceptanceSummary, recipient: str,
                        profile_email: str, attempt_id: str,
                        runtime_attestation: GmailRuntimeAttestation,
                        outbox: AcceptanceOutbox) -> dict[str, Any]:
    """Prepare and claim one host payload without invoking Gmail."""
    _require(isinstance(summary, HostAcceptanceSummary), "HOST_SUMMARY_INVALID")
    recipient = _recipient(recipient)
    profile_email = _recipient(profile_email)
    attempt_id = _safe_id(attempt_id, "ATTEMPT_ID_INVALID")
    identity = _runtime_attestation(runtime_attestation)
    _require(attempt_id == identity.attempt_id, "ATTEMPT_IDENTITY_MISMATCH")
    key = host_notification_key(summary.host, summary.run_id, summary.candidate_id)
    message = summary.message(recipient)
    gmail_claim = build_gmail_claim(summary, recipient, profile_email=profile_email,
                                    runtime_attestation=identity)
    digest = host_payload_digest(message, gmail_claim)
    existing = outbox.get(key)
    if existing is not None:
        _require(existing.get("digest") == digest, "OUTBOX_PAYLOAD_CONFLICT")
        if existing.get("status") == "accepted":
            _require(existing.get("verified_digest") == digest,
                     "TRUSTED_READBACK_REQUIRED")
            return {"status": "already_verified", "key": key,
                    "message": message, "gmail_claim": gmail_claim,
                    "attempt_id": existing.get("attempt_id"),
                    "payload_digest": digest}
        _require(existing.get("status") == "prepared", "RECONCILIATION_REQUIRED")
    else:
        try:
            outbox.prepare(key, message, recipient=recipient,
                           profile_email=profile_email, payload_digest=digest)
        except Exception:
            raise EmailSyncError("OUTBOX_PREPARE_FAILED") from None
    try:
        claimed = outbox.claim(key, attempt_id)
    except Exception:
        raise EmailSyncError("OUTBOX_CLAIM_FAILED") from None
    _require(dict(claimed) == message, "OUTBOX_PAYLOAD_MISMATCH")
    return {"status": "claimed", "key": key, "message": message,
            "gmail_claim": gmail_claim, "attempt_id": attempt_id,
            "payload_digest": digest}


def mark_host_delivery_unknown(*, summary: HostAcceptanceSummary, attempt_id: str,
                               outbox: AcceptanceOutbox) -> Mapping[str, Any]:
    """Fence an ambiguous host send/read outcome; this function never resends."""
    key = host_notification_key(summary.host, summary.run_id, summary.candidate_id)
    attempt_id = _safe_id(attempt_id, "ATTEMPT_ID_INVALID")
    try:
        return outbox.unknown(key, attempt_id)
    except Exception:
        raise EmailSyncError("UNKNOWN_FENCE_FAILED") from None


def verify_codex_business_receipt(*, summary: HostAcceptanceSummary, recipient: str,
                                  profile_email: str,
                                  runtime_attestation: GmailRuntimeAttestation,
                                  receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Verify host-extracted Gmail evidence; model-authored booleans never suffice."""
    _require(isinstance(summary, HostAcceptanceSummary), "HOST_SUMMARY_INVALID")
    _require(isinstance(receipt, Mapping), "CODEX_RECEIPT_INVALID")
    required = {"thread_id", "tool_names", "gmail_tool_names", "final",
                "final_sha256", "final_evidence_trust",
                "gmail_operational_evidence", "gmail_claim"}
    _require(required <= set(receipt), "CODEX_RECEIPT_INVALID")
    _require(receipt["final_evidence_trust"] == "trusted_operational_host_evidence",
             "TRUSTED_OPERATIONAL_EVIDENCE_REQUIRED")
    thread_value = receipt["thread_id"]
    _require(isinstance(thread_value, str) and 8 <= len(thread_value) <= 128
             and _SAFE_ID.fullmatch(thread_value) is not None,
             "CODEX_THREAD_ID_INVALID")
    gmail_tool_names = _validate_gmail_tool_names(receipt["gmail_tool_names"],
                                                  mode="text")
    tool_names = _validate_overall_tool_names(receipt["tool_names"], gmail_tool_names)
    final = receipt["final"]
    _require(isinstance(final, Mapping), "CODEX_FINAL_INVALID")
    final_bytes = json.dumps(dict(final), sort_keys=True).encode()
    _require(_sha_text(receipt["final_sha256"], "CODEX_FINAL_SHA_INVALID") ==
             hashlib.sha256(final_bytes).hexdigest(), "CODEX_FINAL_SHA_MISMATCH")
    evidence = receipt["gmail_operational_evidence"]
    _require(isinstance(evidence, Mapping) and set(evidence) == _TEXT_EVIDENCE_FIELDS,
             "GMAIL_OPERATIONAL_EVIDENCE_INVALID")
    message_id = evidence["message_id"]
    email_thread_id = evidence["email_thread_id"]
    _require(isinstance(message_id, str) and _GMAIL_ID.fullmatch(message_id) is not None,
             "GMAIL_MESSAGE_ID_INVALID")
    _require(isinstance(email_thread_id, str) and
             _GMAIL_ID.fullmatch(email_thread_id) is not None,
             "GMAIL_THREAD_ID_INVALID")
    send_event_id = evidence["send_event_id"]
    read_event_id = evidence["read_event_id"]
    _require(isinstance(send_event_id, str) and _EVENT_ID.fullmatch(send_event_id),
             "GMAIL_SEND_EVENT_ID_INVALID")
    _require(isinstance(read_event_id, str) and _EVENT_ID.fullmatch(read_event_id),
             "GMAIL_READ_EVENT_ID_INVALID")
    _require(send_event_id != read_event_id, "GMAIL_EVENT_ID_CONFLICT")
    for field in ("recipient_sha256", "subject_sha256", "body_sha256",
                  "delivery_payload_sha256", "sender_identity_sha256",
                  "profile_identity_sha256", "raw_readback_sha256"):
        _sha_text(evidence[field], f"GMAIL_{field.upper()}_INVALID")
    verified_at = _aware_time(evidence["readback_verified_at"],
                              "GMAIL_READBACK_TIME_INVALID")
    expected_claim = build_gmail_claim(
        summary, recipient, profile_email=profile_email,
        runtime_attestation=runtime_attestation)
    claim = receipt["gmail_claim"]
    _require(isinstance(claim, Mapping) and dict(claim) == expected_claim,
             "GMAIL_CLAIM_MISMATCH")
    compared = ("recipient_sha256", "subject_sha256", "body_sha256",
                "delivery_payload_sha256", "sender_identity_sha256",
                "profile_identity_sha256")
    _require(all(evidence[field] == expected_claim[field] for field in compared),
             "GMAIL_PAYLOAD_DIGEST_MISMATCH")
    # The model final is retained and hash-bound but never establishes delivery.
    # If it happens to echo host evidence, the echo must not disagree.
    _require(all(field not in final or final[field] == evidence[field]
                 for field in _TEXT_EVIDENCE_FIELDS),
             "CODEX_FINAL_OPERATIONAL_MISMATCH")
    artifact = {
        "kind": "codex_gmail_operational_verification",
        "version": 3,
        "status": "verified",
        "notification_host": summary.host,
        "notification_run_id": summary.run_id,
        "notification_candidate_id": summary.candidate_id,
        "notification_key": host_notification_key(
            summary.host, summary.run_id, summary.candidate_id),
        "result_sha256": summary.result_sha256,
        "message_sha256": message_digest(summary.message(recipient)),
        "job_id": expected_claim["job_id"],
        "slot_id": expected_claim["slot_id"],
        "attempt_id": expected_claim["attempt_id"],
        "service_source_sha256": expected_claim["host"],
        "service_generation_sha256": expected_claim["run"],
        "adapter_source_sha256": expected_claim["candidate"],
        "codex_thread_id": thread_value,
        "tool_names": list(tool_names),
        "gmail_tool_names": list(gmail_tool_names),
        "message_id": message_id,
        "email_thread_id": email_thread_id,
        "send_event_id": send_event_id,
        "read_event_id": read_event_id,
        "payload_sha256": expected_claim["payload_sha256"],
        "delivery_payload_sha256": expected_claim["delivery_payload_sha256"],
        "sender_identity_sha256": expected_claim["sender_identity_sha256"],
        "profile_identity_sha256": expected_claim["profile_identity_sha256"],
        "raw_readback_sha256": evidence["raw_readback_sha256"],
        "readback_verified_at": verified_at,
        "final_evidence_trust": "trusted_operational_host_evidence",
    }
    artifact["verification_sha256"] = _verification_artifact_digest(artifact)
    return artifact


def _verification_artifact_digest(artifact: Mapping[str, Any]) -> str:
    return _canonical_digest({key: value for key, value in artifact.items()
                              if key != "verification_sha256"})


def reconcile_codex_host_delivery(*, summary: HostAcceptanceSummary, recipient: str,
                                  profile_email: str,
                                  runtime_attestation: GmailRuntimeAttestation,
                                  outbox: AcceptanceOutbox,
                                  receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Reconcile one claimed/unknown host notification without another send."""
    key = host_notification_key(summary.host, summary.run_id, summary.candidate_id)
    message = summary.message(recipient)
    gmail_claim = build_gmail_claim(
        summary, recipient, profile_email=profile_email,
        runtime_attestation=runtime_attestation)
    digest = host_payload_digest(message, gmail_claim)
    existing = outbox.get(key)
    _require(existing is not None, "OUTBOX_CLAIM_REQUIRED")
    _require(existing.get("digest") == digest, "OUTBOX_PAYLOAD_CONFLICT")
    _require(existing.get("status") in {"sending", "unknown", "accepted"},
             "RECONCILIATION_REQUIRED")
    verification = verify_codex_business_receipt(
        summary=summary, recipient=recipient, profile_email=profile_email,
        runtime_attestation=runtime_attestation, receipt=receipt)
    if existing.get("status") == "accepted":
        _require(existing.get("message_id") == verification["message_id"]
                 and existing.get("verified_digest") == digest,
                 "ACCEPTED_RECEIPT_CONFLICT")
        return {"verification": verification, "outbox": dict(existing)}
    try:
        row = outbox.reconcile_accepted(
            key, message_id=verification["message_id"], verified_digest=digest)
    except Exception:
        raise EmailSyncError("OUTBOX_RECONCILIATION_FAILED") from None
    return {"verification": verification, "outbox": dict(row)}


def _reopen_verified_delivery(*, store: AcceptanceArtifactStore,
                              ref: AcceptanceArtifactRef, expected_host: str,
                              change_id: str, scope: str) -> Mapping[str, Any]:
    record = store._open_record(ref)
    _require(record["change_id_sha256"] == _digest_text(change_id)
             and record["scope_sha256"] == _digest_text(scope),
             "COMBINED_DELIVERY_SCOPE_MISMATCH")
    _require(record["notification_host_sha256"] == _digest_text(expected_host),
             "COMBINED_DELIVERY_HOST_MISMATCH")
    _require(record["execution_status"] != "pending",
             "COMBINED_EXECUTION_NOT_TERMINAL")
    return record


def build_verified_combined_summary(*, change_id: str, scope: str, sender: str,
                                    store: AcceptanceArtifactStore,
                                    codex_delivery_ref: AcceptanceArtifactRef,
                                    claude_delivery_ref: AcceptanceArtifactRef) -> AcceptanceSummary:
    """Combine only nominal store-issued refs containing fixed hash-only records."""
    change_id = _safe_id(change_id, "CHANGE_ID_INVALID")
    scope = _clean_text(scope, "SCOPE_INVALID")
    _require(type(store) is AcceptanceArtifactStore, "COMBINED_STORE_INVALID")
    _require(type(codex_delivery_ref) is AcceptanceArtifactRef
             and type(claude_delivery_ref) is AcceptanceArtifactRef,
             "COMBINED_ARTIFACT_REF_INVALID")
    _require(codex_delivery_ref._owner is store
             and claude_delivery_ref._owner is store,
             "COMBINED_ARTIFACT_REF_INVALID")
    _require(codex_delivery_ref.ref != claude_delivery_ref.ref,
             "COMBINED_DELIVERY_REF_CONFLICT")
    codex = _reopen_verified_delivery(
        store=store, ref=codex_delivery_ref, expected_host="codex",
        change_id=change_id, scope=scope)
    claude = _reopen_verified_delivery(
        store=store, ref=claude_delivery_ref, expected_host="claude",
        change_id=change_id, scope=scope)
    execution = _combined_execution(codex["execution_status"],
                                    claude["execution_status"])
    _require(sender in {"codex_supervisor", "claude_supervisor"}, "SENDER_INVALID")
    prefix = "[CODEX] " if sender == "codex_supervisor" else ""
    subject = f"{prefix}Runtime acceptance | {execution} | {change_id}"
    body = "\n".join([
        "Combined Codex/Claude runtime acceptance summary",
        f"Change: {change_id}", f"Scope: {scope}",
        f"Execution verdict: {execution}", "Email synchronization: verified",
        f"Summary sender: {sender}", "",
        "Codex:", f"- execution: {codex['execution_status']}",
        f"- result sha256: {codex['result_sha256']}",
        f"- delivery ref: {codex_delivery_ref.ref}", "",
        "Claude:", f"- execution: {claude['execution_status']}",
        f"- result sha256: {claude['result_sha256']}",
        f"- delivery ref: {claude_delivery_ref.ref}", "",
        "Production boundaries remain unchanged. This summary does not convert a failed, partial, or unverified execution into a pass.",
    ])
    verification_sha256 = _canonical_digest({
        "change_id": change_id,
        "scope": scope,
        "delivery_refs": [codex_delivery_ref.ref, claude_delivery_ref.ref],
        "record_digests": [codex_delivery_ref.digest, claude_delivery_ref.digest],
        "result_sha256": [codex["result_sha256"], claude["result_sha256"]],
        "summary_sha256": [codex["summary_sha256"], claude["summary_sha256"]],
        "runtime_attestation_sha256": [codex["runtime_attestation_sha256"],
                                        claude["runtime_attestation_sha256"]],
        "delivery_verification_sha256": [codex["delivery_verification_sha256"],
                                           claude["delivery_verification_sha256"]],
        "combined_summary_sha256": _canonical_digest({
            "subject": subject, "body": body, "execution_status": execution,
        }),
    })
    return AcceptanceSummary(
        change_id, scope, execution, "verified", sender, subject, body,
        delivery_refs=(codex_delivery_ref.ref, claude_delivery_ref.ref),
        verification_sha256=verification_sha256)


def verify_readback(expected: Mapping[str, str], actual: Mapping[str, str]) -> str:
    """Verify exact recipient, subject, and body; return the legacy reconciler digest."""
    _require(set(actual) == {"to", "subject", "body", "message_id"},
             "READBACK_INVALID")
    _require(_recipient(actual["to"]) == _recipient(expected.get("to")),
             "READBACK_RECIPIENT_MISMATCH")
    _require(actual["subject"] == expected.get("subject"), "READBACK_SUBJECT_MISMATCH")
    _require(actual["body"] == expected.get("body"), "READBACK_BODY_MISMATCH")
    _require(isinstance(actual["message_id"], str) and
             re.fullmatch(r"[a-fA-F0-9]{8,64}", actual["message_id"]) is not None,
             "READBACK_MESSAGE_ID_INVALID")
    return message_digest(expected)


def send_once(*, summary: AcceptanceSummary, recipient: str, profile_email: str,
              attempt_id: str, outbox: AcceptanceOutbox,
              gmail: GmailAdapter) -> Mapping[str, Any]:
    """Production runtime entrypoint for one simple-text acceptance delivery.

    Existing accepted receipts suppress exact duplicates. Sending/unknown rows
    are fenced for readback reconciliation and are never replayed here. This
    dedicated outbox is intentionally separate from Niulai multipart reports.
    """
    recipient = _recipient(recipient)
    _require(_recipient(profile_email) == recipient, "PROFILE_RECIPIENT_MISMATCH")
    _safe_id(attempt_id, "ATTEMPT_ID_INVALID")
    key, message = notification_key(summary.change_id), summary.message(recipient)
    existing = outbox.get(key)
    if existing is not None:
        status = existing.get("status")
        if status == "accepted":
            _require(existing.get("digest") == message_digest(message),
                     "OUTBOX_PAYLOAD_CONFLICT")
            return existing
        _require(status == "prepared", "RECONCILIATION_REQUIRED")
    _require(gmail.oauth_ready() is True, "OAUTH_NOT_READY")
    if existing is None:
        outbox.prepare(key, message, recipient=recipient, profile_email=profile_email)
    claimed = outbox.claim(key, attempt_id)
    _require(dict(claimed) == message, "OUTBOX_PAYLOAD_MISMATCH")
    try:
        message_id = gmail.send(message)
    except Exception:
        try:
            outbox.unknown(key, attempt_id)
        except Exception:
            pass
        raise EmailSyncError("SEND_OUTCOME_UNKNOWN_RECONCILE_REQUIRED") from None
    try:
        return outbox.accepted(key, attempt_id, message_id)
    except Exception:
        try:
            current = outbox.get(key)
        except Exception:
            current = None
        if (isinstance(current, Mapping) and current.get("status") == "accepted"
                and current.get("message_id") == message_id):
            return current
        try:
            outbox.unknown(key, attempt_id)
        except Exception:
            pass
        raise EmailSyncError("SEND_OUTCOME_UNKNOWN_RECONCILE_REQUIRED") from None


def reconcile_readback(*, summary: AcceptanceSummary, recipient: str,
                       outbox: AcceptanceOutbox,
                       actual: Mapping[str, str]) -> Mapping[str, Any]:
    """Reconcile a held sending/unknown claim after exact Gmail readback."""
    key = notification_key(summary.change_id)
    expected = summary.message(recipient)
    digest = verify_readback(expected, actual)
    _require(_SHA256.fullmatch(digest) is not None, "READBACK_DIGEST_INVALID")
    return outbox.reconcile_accepted(key, message_id=actual["message_id"],
                                     verified_digest=digest)
