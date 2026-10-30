"""Recipient-bound MIME validation and an at-most-one-attempt durable outbox.

The outbox cannot guarantee exactly-once remote delivery. A process death after
claim leaves ``sending``; an ambiguous response leaves ``unknown``. Neither is
eligible for another send. Reconciliation requires independent Gmail readback.
No OAuth credentials, app integrations, or scheduled jobs are installed here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone
from typing import Callable


class DeliveryError(ValueError):
    """Sanitized, stable failure code; never include payloads in exceptions."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise DeliveryError(code)


def _email(value: object) -> str:
    _require(isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value)), "INVALID_RECIPIENT")
    return value.lower()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _bytes(body: dict, charset: str | None) -> bytes:
    _require(isinstance(body, dict), "MIME_BODY_REQUIRED")
    _require(set(body) <= {"content", "base64_url_content"}, "UNMATERIALIZED_MIME_BODY")
    content, encoded = body.get("content"), body.get("base64_url_content")
    _require((content is None) != (encoded is None), "MIME_BODY_AMBIGUOUS")
    if content is not None:
        _require(isinstance(content, str), "MIME_TEXT_INVALID")
        try:
            return content.encode(charset or "utf-8")
        except (LookupError, UnicodeError):
            raise DeliveryError("MIME_CHARSET_INVALID") from None
    _require(isinstance(encoded, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", encoded)), "MIME_BASE64_INVALID")
    try:
        return base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise DeliveryError("MIME_BASE64_INVALID") from None


def validate_payload(message: dict, recipient: str, profile_email: str) -> dict:
    """Validate a fully materialized Gmail send payload, return non-content hashes.

    Fetch attachment bytes before calling this. An attachment ID or a URL is not
    an attachment. Content completeness is verified against source hashes, not
    inferred from a minimum body length or a successful MIME parse.
    """
    recipient = _email(recipient)
    _require(_email(profile_email) == recipient, "PROFILE_RECIPIENT_MISMATCH")
    _require(isinstance(message, dict), "MESSAGE_REQUIRED")
    _require(set(message) <= {"to", "subject", "payload", "from_address"}, "UNEXPECTED_MESSAGE_FIELD")
    _require(_email(message.get("to")) == recipient, "RECIPIENT_MISMATCH")
    if message.get("from_address") is not None:
        _require(_email(message["from_address"]) == recipient, "FROM_MISMATCH")
    subject = message.get("subject")
    _require(isinstance(subject, str) and bool(subject.strip()) and not any(c in subject for c in "\r\n\0"), "SUBJECT_INVALID")
    pdfs, htmls = [], []
    count, total = 0, 0

    def visit(part: dict, depth: int = 0) -> dict:
        nonlocal count, total
        count += 1
        _require(count <= 20 and depth <= 4, "MIME_TOO_COMPLEX")
        _require(isinstance(part, dict), "MIME_PART_INVALID")
        allowed = {"mime_type", "charset", "content_disposition", "content_id", "filename", "body", "parts"}
        _require(set(part) <= allowed, "UNEXPECTED_MIME_FIELD")
        mime = part.get("mime_type")
        _require(mime in {"multipart/mixed", "multipart/alternative", "text/html", "text/plain", "application/pdf"}, "MIME_TYPE_REJECTED")
        if mime.startswith("multipart/"):
            _require(not part.get("body") and isinstance(part.get("parts"), list) and bool(part["parts"]), "MULTIPART_INVALID")
            return {"mime_type": mime, "parts": [visit(p, depth + 1) for p in part["parts"]]}
        _require(not part.get("parts"), "LEAF_HAS_CHILDREN")
        _require(not part.get("content_id"), "CONTENT_ID_UNSUPPORTED")
        data = _bytes(part.get("body"), part.get("charset"))
        total += len(data)
        _require(total <= 20 * 1024 * 1024, "MESSAGE_TOO_LARGE")
        result = {"mime_type": mime, "sha256": _hash(data), "size": len(data)}
        if mime == "application/pdf":
            name = part.get("filename")
            _require(isinstance(name, str) and bool(re.fullmatch(r"[A-Za-z0-9_. -]+\.pdf", name)) and not name.startswith("."), "PDF_FILENAME_INVALID")
            _require(part.get("content_disposition") == "attachment" and data.startswith(b"%PDF-") and b"%%EOF" in data[-2048:], "ACTUAL_PDF_REQUIRED")
            result.update(filename=name, content_disposition="attachment")
            pdfs.append(result)
        else:
            _require(bool(data.strip()) and not part.get("filename") and part.get("content_disposition") in (None, "inline"), "TEXT_BODY_INVALID")
            # Digest bytes, not normalized HTML: a truncation or visual change
            # must fail parity even when both strings render successfully.
            result["charset"] = (part.get("charset") or "utf-8").lower()
            if mime == "text/html":
                htmls.append(result)
        return result

    tree = visit(message.get("payload"))
    _require(tree["mime_type"] == "multipart/mixed", "MIXED_MESSAGE_REQUIRED")
    _require(len(pdfs) == 2 and len({p["filename"] for p in pdfs}) == 2, "TWO_DISTINCT_PDFS_REQUIRED")
    _require(len(htmls) == 1, "ONE_FULL_HTML_BODY_REQUIRED")
    content_digest = _hash(_json(tree).encode())
    digest = _hash(_json({"recipient": recipient, "subject": subject, "tree": tree}).encode())
    return {"digest": digest, "content_digest": content_digest, "html": htmls[0], "pdfs": pdfs}


def assert_content_parity(source: dict, candidate: dict, recipient: str, profile_email: str, *, same_subject: bool = True) -> dict:
    expected = validate_payload(source, recipient, profile_email)
    actual = validate_payload(candidate, recipient, profile_email)
    key = "digest" if same_subject else "content_digest"
    _require(expected[key] == actual[key], "CONTENT_PARITY_FAILED")
    return actual


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Outbox:
    """Private SQLite ledger. Keys come from config/scheduler admission.

    This class deliberately has no reset-to-prepared or retry-unknown operation.
    Prepared payloads are immutable. The JSON includes private report contents;
    callers must not log or commit the database.
    """

    def __init__(self, db_path: str | Path, workspace_root: str | Path):
        workspace = Path(workspace_root).resolve(strict=True)
        raw = Path(db_path).absolute()
        state = workspace / ".niulai-state"
        _require(".." not in raw.parts, "OUTBOX_PATH_ESCAPE")
        _require(raw.is_relative_to(state), "OUTBOX_OUTSIDE_PRIVATE_STATE")
        _require(raw.resolve().is_relative_to(state.resolve()), "OUTBOX_PATH_ESCAPE")
        _require(not any(p.is_symlink() for p in [raw, *raw.parents] if p.is_relative_to(workspace)), "OUTBOX_SYMLINK_REJECTED")
        raw.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for p in [raw.parent, *raw.parent.parents]:
            if p.is_relative_to(state):
                p.chmod(0o700)
        _require(raw.resolve().is_relative_to(state.resolve()), "OUTBOX_PATH_ESCAPE")
        fd = os.open(raw, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        raw.chmod(0o600)
        self.path = raw
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS outbox (
                key TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('prepared','sending','unknown','accepted')),
                attempt_id TEXT, message_id TEXT, prepared_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, verified_at TEXT)""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=DELETE")
        return db

    def get(self, key: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT key,digest,status,attempt_id,message_id,prepared_at,updated_at,verified_at FROM outbox WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def prepare(self, key: str, message: dict, *, recipient: str, profile_email: str) -> dict:
        _require(isinstance(key, str) and 1 <= len(key) <= 512 and not any(c in key for c in "\r\n\0"), "DELIVERY_KEY_INVALID")
        fingerprint = validate_payload(message, recipient, profile_email)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT digest FROM outbox WHERE key=?", (key,)).fetchone()
            if old:
                _require(old["digest"] == fingerprint["digest"], "IMMUTABLE_PAYLOAD_CONFLICT")
            else:
                now = _now()
                db.execute("INSERT INTO outbox VALUES (?,?,?,'prepared',NULL,NULL,?,?,NULL)", (key, fingerprint["digest"], _json(message), now, now))
        return self.get(key)

    def claim(self, key: str, attempt_id: str) -> dict:
        _require(isinstance(attempt_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{8,128}", attempt_id)), "ATTEMPT_ID_INVALID")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM outbox WHERE key=?", (key,)).fetchone()
            _require(row is not None, "OUTBOX_ITEM_MISSING")
            _require(row["status"] == "prepared", "OUTBOX_NOT_SENDABLE")
            db.execute("UPDATE outbox SET status='sending',attempt_id=?,updated_at=? WHERE key=?", (attempt_id, _now(), key))
            payload = json.loads(row["payload"])
        return payload

    def accepted(self, key: str, attempt_id: str, message_id: str) -> dict:
        _require(isinstance(message_id, str) and bool(re.fullmatch(r"[a-fA-F0-9]{8,64}", message_id)), "GMAIL_MESSAGE_ID_REQUIRED")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM outbox WHERE key=?", (key,)).fetchone()
            _require(row is not None and row["attempt_id"] == attempt_id, "ATTEMPT_MISMATCH")
            if row["status"] == "accepted":
                _require(row["message_id"] == message_id, "MESSAGE_ID_CONFLICT")
            else:
                _require(row["status"] == "sending", "ACCEPTANCE_REQUIRES_SENDING")
                db.execute("UPDATE outbox SET status='accepted',message_id=?,updated_at=? WHERE key=?", (message_id, _now(), key))
        return self.get(key)

    def unknown(self, key: str, attempt_id: str) -> dict:
        with self._connect() as db:
            cursor = db.execute("UPDATE outbox SET status='unknown',updated_at=? WHERE key=? AND attempt_id=? AND status='sending'", (_now(), key, attempt_id))
            _require(cursor.rowcount == 1, "UNKNOWN_TRANSITION_REJECTED")
        return self.get(key)

    def reconcile_accepted(self, key: str, *, message_id: str, verified_digest: str) -> dict:
        """Call only after independently reading the exact message from Gmail.

        verified_digest must come from validate_payload on readback with fetched
        attachments and checked sender/recipient. A search snippet is insufficient.
        This is an evidence handoff, not independent network verification by SQLite.
        """
        _require(isinstance(message_id, str) and bool(re.fullmatch(r"[a-fA-F0-9]{8,64}", message_id)), "GMAIL_MESSAGE_ID_REQUIRED")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM outbox WHERE key=?", (key,)).fetchone()
            _require(row is not None and row["status"] in ("sending", "unknown", "accepted"), "RECONCILIATION_REJECTED")
            _require(row["digest"] == verified_digest, "READBACK_DIGEST_MISMATCH")
            _require(row["message_id"] in (None, message_id), "MESSAGE_ID_CONFLICT")
            now = _now()
            db.execute("UPDATE outbox SET status='accepted',message_id=?,verified_at=?,updated_at=? WHERE key=?", (message_id, now, now, key))
        return self.get(key)


def dispatch_once(outbox: Outbox, key: str, attempt_id: str, sender: Callable[[dict], str], *, recipient: str, profile_email: str) -> dict:
    """One transport call. Sender returns the actual Gmail message ID.

    Both profile and policy must be verified by the caller immediately before
    this operation. No connector exception text is retained or printed.
    """
    payload = outbox.claim(key, attempt_id)
    try:
        validate_payload(payload, recipient, profile_email)
        message_id = sender(payload)
        return outbox.accepted(key, attempt_id, message_id)
    except Exception:
        outbox.unknown(key, attempt_id)
        raise DeliveryError("SEND_OUTCOME_UNKNOWN_RECONCILE_REQUIRED") from None
