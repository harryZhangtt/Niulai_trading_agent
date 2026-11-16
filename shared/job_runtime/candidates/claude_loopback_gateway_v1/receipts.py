"""Durable sanitized receipt chain; integrity is not cryptographic authenticity.

SHA-256 chaining detects modification/reordering and, when validation is supplied an
externally retained ``(sequence, head_hash)`` checkpoint, complete-tail deletion.
It is not a MAC or signature: an attacker able to rewrite both file and checkpoint
can forge a new chain.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

GENESIS_HASH = "0" * 64
SCHEMA_VERSION = "claude-loopback-gateway-receipt-v1"
MODES = frozenset({"pass_through", "synthetic_first", "forward_then_cut"})
TERMINALS = frozenset({
    "headers_rejected", "auth_rejected", "request_rejected", "request_incomplete",
    "synthetic_fault", "rejected_before_forward", "completed", "upstream_502",
    "forward_cut", "cut_not_reached",
    "response_rejected", "response_limit_cut", "upstream_error",
    "upstream_premature_eof", "post_commit_error", "credential_reflection", "client_cancelled",
})
_ALLOWED_KEYS = {
    "schema_version", "sequence", "timestamp_ns", "method", "path", "mode",
    "states", "http_status", "arrival_count", "upstream_count",
    "duplicate_attempt", "attempt_number", "upstream_attempts", "request_bytes", "response_bytes",
    "streaming", "pre_forward_attestation", "prev_hash", "entry_hash",
}


_ATTESTATION_KEYS = frozenset({
    "proof_version", "proof_kind", "authority_id", "generation", "run_binding_hash",
    "slot_binding_hash", "attempt_binding_hash", "operation_binding_hash",
    "prompt_binding_hash", "request_ordinal", "status", "upstream_attempts",
    "upstream_count_delta", "submission", "retry_after", "signature",
})


def _valid_attestation(value: object, arrival_count: int) -> bool:
    if type(value) is not dict or set(value) != _ATTESTATION_KEYS:
        return False
    hashes = (
        value["run_binding_hash"], value["slot_binding_hash"],
        value["attempt_binding_hash"], value["operation_binding_hash"],
        value["prompt_binding_hash"], value["signature"],
    )
    return all(_is_hash(item) for item in hashes) and (
        type(value["authority_id"]) is str
        and len(value["authority_id"]) == 32
        and all(ch in "0123456789abcdef" for ch in value["authority_id"])
        and value["proof_version"] == "pre-forward-attestation-v1"
        and type(value["generation"]) is int
        and value["generation"] > 0
        and value["proof_kind"] == "adapter_hmac_pre_forward_502_v1"
        and value["request_ordinal"] == arrival_count
        and type(value["request_ordinal"]) is int
        and value["status"] == 502
        and type(value["status"]) is int
        and value["upstream_attempts"] == 0
        and type(value["upstream_attempts"]) is int
        and value["upstream_count_delta"] == 0
        and type(value["upstream_count_delta"]) is int
        and value["submission"] == "not_submitted"
        and value["retry_after"] == "1"
    )


class ReceiptIntegrityError(ValueError):
    """Raised when receipt structure, semantics, chain, or checkpoint differs."""


def _is_int(value: object) -> bool:
    return type(value) is int


def _is_hash(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _valid_states(
    states: object, status: object, method: object, path: object, mode: object
) -> bool:
    if type(states) is not list or not states or any(type(item) is not str for item in states):
        return False
    if states[0] != "arrived" or states[-1] not in TERMINALS or len(set(states)) != len(states):
        return False
    if any(item not in TERMINALS | {"arrived", "authenticated", "forwarding"} for item in states):
        return False
    is_messages = method == "POST" and path == "/v1/messages" and mode in MODES
    is_models = method == "GET" and path == "/v1/models" and mode == "pass_through"
    if not (is_messages or is_models):
        return False
    terminal = states[-1]
    if is_models and terminal not in {
        "headers_rejected", "auth_rejected", "request_rejected", "completed",
        "upstream_502", "response_rejected", "response_limit_cut", "upstream_error",
        "upstream_premature_eof", "post_commit_error", "credential_reflection",
        "client_cancelled",
    }:
        return False
    if terminal in {"headers_rejected", "auth_rejected"}:
        expected = ["arrived", terminal]
    elif terminal in {"request_rejected", "request_incomplete", "synthetic_fault", "rejected_before_forward"}:
        expected = ["arrived", "authenticated", terminal]
    else:
        expected = ["arrived", "authenticated", "forwarding", terminal]
    if states != expected:
        return False
    fixed_status = {
        "headers_rejected": 431, "auth_rejected": 401, "request_incomplete": 400,
        "response_rejected": 502, "upstream_error": 502,
        "rejected_before_forward": 502, "upstream_502": 502,
    }
    if terminal in fixed_status and status != fixed_status[terminal]:
        return False
    if terminal == "synthetic_fault" and status not in (429, 503):
        return False
    if terminal == "client_cancelled" and "forwarding" not in states and status != 499:
        return False
    return True


class ReceiptLedger:
    """Append durable JSONL records containing sanitized metadata only."""

    def __init__(
        self,
        path: Path,
        *,
        expected_sequence: Optional[int] = None,
        expected_head: Optional[str] = None,
    ) -> None:
        if (expected_sequence is None) != (expected_head is None):
            raise ValueError("expected sequence and head must be supplied together")
        self.path = Path(path)
        self._lock = threading.Lock()
        self._last_hash = GENESIS_HASH
        self._sequence = 0
        self._prior: Optional[Mapping[str, Any]] = None
        self._poisoned = False
        if self.path.exists():
            records = self.validate(
                self.path, expected_sequence=expected_sequence, expected_head=expected_head
            )
            self._sequence = len(records)
            if records:
                self._last_hash = records[-1]["entry_hash"]
                self._prior = records[-1]
        elif expected_sequence not in (None, 0) or expected_head not in (None, GENESIS_HASH):
            raise ReceiptIntegrityError("receipt checkpoint mismatch")

    def _require_healthy(self) -> None:
        if self._poisoned:
            raise ReceiptIntegrityError("ledger is poisoned after uncertain append")

    @property
    def poisoned(self) -> bool:
        with self._lock:
            return self._poisoned

    @property
    def checkpoint(self) -> Tuple[int, str]:
        with self._lock:
            self._require_healthy()
            return self._sequence, self._last_hash

    @property
    def last_timestamp_ns(self) -> int:
        with self._lock:
            self._require_healthy()
            return 0 if self._prior is None else int(self._prior["timestamp_ns"])

    @property
    def last_counts(self) -> Tuple[int, int]:
        with self._lock:
            self._require_healthy()
            if self._prior is None:
                return 0, 0
            return int(self._prior["arrival_count"]), int(self._prior["upstream_count"])

    @staticmethod
    def _encoded(record: Mapping[str, Any]) -> bytes:
        return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")

    @staticmethod
    def _write_all(fd: int, payload: bytes) -> None:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("receipt write made no progress")
            view = view[written:]

    def append(self, fields: Mapping[str, Any]) -> Mapping[str, Any]:
        forbidden = set(fields) - (_ALLOWED_KEYS - {"sequence", "prev_hash", "entry_hash"})
        if forbidden:
            raise ValueError("receipt contains non-sanitized fields")
        with self._lock:
            self._require_healthy()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            base = dict(fields)
            base["sequence"] = self._sequence + 1
            base["prev_hash"] = self._last_hash
            digest = hashlib.sha256(self._encoded(base)).hexdigest()
            record = {**base, "entry_hash": digest}
            # Validate semantics before committing any bytes. Sequence, head and
            # prior event move only after file and directory durability succeed.
            self._validate_record(record, self._sequence + 1, self._last_hash, self._prior)
            payload = self._encoded(record) + b"\n"
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            try:
                fd = os.open(str(self.path), flags, 0o600)
                try:
                    self._write_all(fd, payload)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                directory_fd = os.open(str(self.path.parent), os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except BaseException:
                # O_APPEND cannot roll back a partial or fully written record
                # whose durability is unknown. Freeze this object permanently;
                # recovery requires validating/reconciling a fresh ledger object.
                self._poisoned = True
                raise
            self._sequence += 1
            self._last_hash = digest
            self._prior = record
            return record

    @classmethod
    def _validate_record(
        cls,
        record: object,
        sequence: int,
        previous: str,
        prior: Optional[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if type(record) is not dict or set(record) != _ALLOWED_KEYS:
            raise ReceiptIntegrityError("receipt schema mismatch")
        r = record
        scalar_checks = (
            r["schema_version"] == SCHEMA_VERSION,
            r["sequence"] == sequence and _is_int(r["sequence"]),
            _is_int(r["timestamp_ns"]) and r["timestamp_ns"] >= 0,
            type(r["method"]) is str and r["method"] in {"POST", "GET"},
            type(r["path"]) is str and r["path"] in {"/v1/messages", "/v1/models"},
            type(r["mode"]) is str and r["mode"] in MODES,
            _is_int(r["http_status"]) and 100 <= r["http_status"] <= 599,
            _is_int(r["arrival_count"]) and r["arrival_count"] >= 1,
            _is_int(r["upstream_count"]) and 0 <= r["upstream_count"] <= r["arrival_count"],
            type(r["duplicate_attempt"]) is bool,
            _is_int(r["attempt_number"]) and r["attempt_number"] >= 1,
            _is_int(r["upstream_attempts"]) and r["upstream_attempts"] in (0, 1),
            _is_int(r["request_bytes"]) and r["request_bytes"] >= 0,
            _is_int(r["response_bytes"]) and r["response_bytes"] >= 0,
            type(r["streaming"]) is bool,
            r["prev_hash"] == previous and _is_hash(r["prev_hash"]),
            _is_hash(r["entry_hash"]),
            r["duplicate_attempt"] == (r["attempt_number"] > 1),
            r["upstream_attempts"] == int("forwarding" in r["states"]),
            (
                _valid_attestation(r["pre_forward_attestation"], r["arrival_count"])
                if r["states"][-1] == "rejected_before_forward"
                else r["pre_forward_attestation"] is None
            ),
            _valid_states(
                r["states"], r["http_status"], r["method"], r["path"], r["mode"]
            ),
        )
        if not all(scalar_checks):
            raise ReceiptIntegrityError("receipt field or state semantics invalid")
        if "forwarding" not in r["states"] and r["response_bytes"] != 0:
            raise ReceiptIntegrityError("response bytes require forwarding")
        if r["method"] == "GET" and r["request_bytes"] != 0:
            raise ReceiptIntegrityError("GET models receipt cannot contain request bytes")
        if prior is not None:
            if r["timestamp_ns"] < prior["timestamp_ns"]:
                raise ReceiptIntegrityError("receipt timestamp regressed")
            if r["arrival_count"] != prior["arrival_count"] + 1:
                raise ReceiptIntegrityError("arrival count is not monotonic")
            delta = r["upstream_count"] - prior["upstream_count"]
            if delta not in (0, 1):
                raise ReceiptIntegrityError("upstream count is not monotonic")
            forwarded = "forwarding" in r["states"]
            if delta != r["upstream_attempts"] or delta != int(forwarded):
                raise ReceiptIntegrityError("upstream count disagrees with state")
        elif r["arrival_count"] != 1 or r["upstream_count"] != r["upstream_attempts"]:
            raise ReceiptIntegrityError("first receipt counts invalid")
        supplied = r["entry_hash"]
        base = {key: value for key, value in r.items() if key != "entry_hash"}
        if supplied != hashlib.sha256(cls._encoded(base)).hexdigest():
            raise ReceiptIntegrityError("receipt hash mismatch")
        return r

    @classmethod
    def validate_authenticated(
        cls,
        path: Path,
        *,
        verifier: object,
        expected_binding: object,
        expected_sequence: Optional[int] = None,
        expected_head: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], list[object]]:
        from .attestation import (
            ExpectedPreForwardBinding,
            PreForwardAttestationVerifier,
        )
        if type(verifier) is not PreForwardAttestationVerifier:
            raise ReceiptIntegrityError("active owned attestation verifier required")
        if type(expected_binding) is not ExpectedPreForwardBinding:
            raise ReceiptIntegrityError("exact expected pre-forward binding required")
        records = cls.validate(
            path, expected_sequence=expected_sequence, expected_head=expected_head
        )
        verified: list[object] = []
        for record in records:
            if record["states"][-1] == "rejected_before_forward":
                try:
                    result = verifier.verify_and_consume(
                        record["pre_forward_attestation"],
                        expected_binding=expected_binding,
                        request_ordinal=record["arrival_count"],
                    )
                except ValueError as exc:
                    raise ReceiptIntegrityError("receipt attestation authentication failed") from exc
                verified.append(result)
        if not verified:
            raise ReceiptIntegrityError("receipt contains no authenticated pre-forward attestation")
        return records, verified

    @classmethod
    def validate(
        cls,
        path: Path,
        *,
        expected_sequence: Optional[int] = None,
        expected_head: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if (expected_sequence is None) != (expected_head is None):
            raise ValueError("expected sequence and head must be supplied together")
        previous = GENESIS_HASH
        records: list[dict[str, Any]] = []
        try:
            payload = Path(path).read_bytes()
            if payload and not payload.endswith(b"\n"):
                raise ReceiptIntegrityError("receipt has partial tail")
            lines = payload.splitlines()
            prior = None
            def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, value in pairs:
                    if key in result:
                        raise ReceiptIntegrityError("receipt JSON contains duplicate key")
                    result[key] = value
                return result

            for sequence, line in enumerate(lines, 1):
                raw = json.loads(line, object_pairs_hook=strict_object)
                if type(raw) is not dict or line != cls._encoded(raw):
                    raise ReceiptIntegrityError("receipt JSON is not canonical")
                record = cls._validate_record(raw, sequence, previous, prior)
                previous = record["entry_hash"]
                records.append(record)
                prior = record
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ReceiptIntegrityError("receipt is malformed") from exc
        if expected_sequence is not None:
            if not _is_int(expected_sequence) or expected_sequence < 0 or not _is_hash(expected_head):
                raise ValueError("invalid expected checkpoint")
            actual_head = records[-1]["entry_hash"] if records else GENESIS_HASH
            if len(records) != expected_sequence or actual_head != expected_head:
                raise ReceiptIntegrityError("receipt checkpoint mismatch")
        return records
