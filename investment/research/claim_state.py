"""Structural, content-bound claim evidence state validation.

The capability is deliberately provider-free. Source access is recorded separately
from the claim state; a source access failure is never converted into contradictory
evidence. Successful records are content-addressed and may be published atomically
by the CLI. Submitter-provided principal IDs and hashes establish structural
consistency, not identity, provenance, or authenticity, so this boundary never
authorizes consequential conclusions, model inputs, probabilities, actions, sizing,
or alerts. Validation errors expose stable codes only.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
VERSION = "claim-state-1.1.0"
MAX_INPUT_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_ERROR = re.compile(r"CLAIM_STATE_[A-Z0-9_]{2,80}")


class ClaimStateError(ValueError):
    """A sanitized claim-state contract failure."""

    def __init__(self, code: str):
        super().__init__(code if _ERROR.fullmatch(code) else "CLAIM_STATE_FAILED")
        self.code = str(self)


class ClaimState(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNVERIFIABLE = "unverifiable"


class SourceAccessStatus(str, Enum):
    CONTENT = "content"
    GATED = "gated"
    ZERO_TEXT = "zero_text"
    MISSING = "missing"


class EvidenceRelationship(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"


class ReviewerDisposition(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    CONTRADICTION = "contradiction"
    INCONCLUSIVE = "inconclusive"


class ReasonCode(str, Enum):
    GATED = "gated"
    ZERO_TEXT = "zero_text"
    MISSING = "missing"
    STALE = "stale"
    FUTURE = "future"
    INAPPLICABLE = "inapplicable"
    INADMISSIBLE = "inadmissible"
    UNASSESSABLE = "unassessable"
    CONFLICT = "conflict"
    MISSING_REVIEW = "missing_review"
    NO_RELEVANT_EVIDENCE = "no_relevant_evidence"


class ExclusionReason(str, Enum):
    STALE = "stale"
    FUTURE = "future"
    INAPPLICABLE = "inapplicable"
    INADMISSIBLE = "inadmissible"
    UNASSESSABLE = "unassessable"
    GATED = "gated"
    ZERO_TEXT = "zero_text"
    MISSING = "missing"


class ClaimUse(str, Enum):
    REPORT_CANDIDATE = "report_candidate"
    # These consequential values remain recognized solely so this boundary returns
    # the stable USE_FORBIDDEN error rather than implying an unknown-use typo.
    AFFIRMATIVE_CONCLUSION = "affirmative_conclusion"
    MODEL_INPUT = "model_input"
    AFFIRMATIVE_PROBABILITY = "affirmative_probability"
    AFFIRMATIVE_ACTION = "affirmative_action"
    AFFIRMATIVE_SIZING = "affirmative_sizing"
    AFFIRMATIVE_ALERT = "affirmative_alert"
    OPPOSING_EVIDENCE = "opposing_evidence"
    GAP = "gap"


_CONSEQUENTIAL_USES = frozenset({
    ClaimUse.AFFIRMATIVE_CONCLUSION.value,
    ClaimUse.MODEL_INPUT.value,
    ClaimUse.AFFIRMATIVE_PROBABILITY.value,
    ClaimUse.AFFIRMATIVE_ACTION.value,
    ClaimUse.AFFIRMATIVE_SIZING.value,
    ClaimUse.AFFIRMATIVE_ALERT.value,
})
_ALLOWED_USES = {
    ClaimState.SUPPORTED.value: (ClaimUse.REPORT_CANDIDATE.value,),
    ClaimState.UNSUPPORTED.value: (ClaimUse.OPPOSING_EVIDENCE.value,),
    ClaimState.UNVERIFIABLE.value: (ClaimUse.GAP.value,),
}
_RECORD_KEYS = {
    "schema_version", "claim", "cutoff", "operator_id", "access", "evidence",
    "review", "reason_codes", "requested_uses", "state", "record_sha256",
}
_CLAIM_KEYS = {"id", "text", "author_id", "atomicity", "sha256"}
_ACCESS_KEYS = {"source_id", "status"}
_EVIDENCE_KEYS = {
    "evidence_id", "collector_id", "source_id", "source_version",
    "current_version", "available_at", "content", "content_sha256", "quote",
    "quote_start", "quote_end", "quote_sha256", "relationship", "admissible",
    "assessable", "applicable", "claim_sha256", "binding_sha256",
}
_REVIEW_KEYS = {
    "reviewer_id", "disposition", "rationale", "reviewed_at", "claim_sha256",
    "evidence_sha256", "cutoff", "binding_sha256",
}
_COMPUTED_EVIDENCE_KEYS = {
    "content_sha256", "quote_sha256", "claim_sha256", "binding_sha256",
}
_COMPUTED_REVIEW_KEYS = {
    "claim_sha256", "evidence_sha256", "cutoff", "binding_sha256",
}


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise ClaimStateError(code)


def _closed(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    _need(isinstance(value, dict) and set(value) == keys, code)
    return value


def _identifier(value: Any, code: str) -> str:
    _need(type(value) is str and _ID.fullmatch(value) is not None, code)
    return value


def _hash(value: Any, code: str) -> str:
    _need(type(value) is str and _SHA256.fullmatch(value) is not None, code)
    return value


def _enum(value: Any, enum_type: type[Enum], code: str) -> str:
    _need(type(value) is str, code)
    try:
        return enum_type(value).value
    except (TypeError, ValueError):
        raise ClaimStateError(code) from None


def _timestamp(value: Any, code: str) -> datetime:
    _need(type(value) is str and 1 <= len(value) <= 64, code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ClaimStateError(code) from None
    _need(parsed.tzinfo is not None and parsed.utcoffset() is not None, code)
    return parsed.astimezone(timezone.utc)


def _reject_nonfinite(value: Any) -> None:
    """Bound traversal and reject non-finite numbers, surrogates, and deep trees."""
    pending = [(value, 0)]
    visited = 0
    while pending:
        node, depth = pending.pop()
        visited += 1
        _need(depth <= 64 and visited <= 100000, "CLAIM_STATE_JSON_DEPTH")
        if isinstance(node, float):
            _need(math.isfinite(node), "CLAIM_STATE_JSON_NONFINITE")
        elif type(node) is str:
            try:
                node.encode("utf-8")
            except UnicodeEncodeError:
                raise ClaimStateError("CLAIM_STATE_JSON_SURROGATE") from None
        elif isinstance(node, dict):
            for key, child in node.items():
                _need(type(key) is str, "CLAIM_STATE_JSON_INVALID")
                pending.append((key, depth + 1))
                pending.append((child, depth + 1))
        elif isinstance(node, (list, tuple)):
            pending.extend((child, depth + 1) for child in node)


def canonical_json(value: Any) -> bytes:
    """Return the one canonical JSON representation accepted for hashing."""
    _reject_nonfinite(value)
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise ClaimStateError("CLAIM_STATE_JSON_INVALID") from None


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def text_sha256(value: str) -> str:
    _need(type(value) is str, "CLAIM_STATE_TEXT_INVALID")
    try:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        raise ClaimStateError("CLAIM_STATE_JSON_SURROGATE") from None


def _pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ClaimStateError("CLAIM_STATE_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ClaimStateError("CLAIM_STATE_JSON_NONFINITE")


def loads_strict(raw: str | bytes) -> Any:
    """Parse bounded JSON while rejecting duplicate keys and non-finite numbers."""
    _need(isinstance(raw, (str, bytes)), "CLAIM_STATE_JSON_INVALID")
    if isinstance(raw, bytes):
        _need(len(raw) <= MAX_INPUT_BYTES, "CLAIM_STATE_INPUT_LIMIT")
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ClaimStateError("CLAIM_STATE_JSON_INVALID") from None
    else:
        try:
            raw_size = len(raw.encode("utf-8"))
        except UnicodeEncodeError:
            raise ClaimStateError("CLAIM_STATE_JSON_SURROGATE") from None
        _need(raw_size <= MAX_INPUT_BYTES, "CLAIM_STATE_INPUT_LIMIT")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except ClaimStateError:
        raise
    except (json.JSONDecodeError, RecursionError, UnicodeError):
        raise ClaimStateError("CLAIM_STATE_JSON_INVALID") from None
    _reject_nonfinite(value)
    return value


def _claim_hash(claim: Mapping[str, Any]) -> str:
    return canonical_sha256({key: claim[key] for key in
                             ("id", "text", "author_id", "atomicity")})


def _evidence_hash(evidence: Mapping[str, Any]) -> str:
    return canonical_sha256({key: evidence[key] for key in sorted(
        _EVIDENCE_KEYS - {"binding_sha256"})})


def _evidence_set_hash(evidence: Sequence[Mapping[str, Any]]) -> str:
    return canonical_sha256([row["binding_sha256"] for row in evidence])


def _review_hash(review: Mapping[str, Any]) -> str:
    return canonical_sha256({key: review[key] for key in sorted(
        _REVIEW_KEYS - {"binding_sha256"})})


def _put_hash(target: dict[str, Any], key: str, expected: str, code: str) -> None:
    if key in target:
        _need(target[key] == expected, code)
    else:
        target[key] = expected


def seal_record(value: Mapping[str, Any]) -> dict[str, Any]:
    """Fill absent immutable hashes without accepting mismatched existing hashes."""
    _need(isinstance(value, Mapping), "CLAIM_STATE_RECORD_INVALID")
    try:
        record = loads_strict(canonical_json(dict(value)))
    except ClaimStateError:
        raise
    allowed = _RECORD_KEYS
    _need(set(record) <= allowed and set(record) >= allowed - {"record_sha256"},
          "CLAIM_STATE_RECORD_INVALID")
    claim = record.get("claim")
    _need(isinstance(claim, dict) and set(claim) <= _CLAIM_KEYS
          and set(claim) >= _CLAIM_KEYS - {"sha256"}, "CLAIM_STATE_CLAIM_INVALID")
    _put_hash(claim, "sha256", _claim_hash(claim),
              "CLAIM_STATE_CLAIM_HASH_MISMATCH")
    evidence = record.get("evidence")
    _need(isinstance(evidence, list), "CLAIM_STATE_EVIDENCE_INVALID")
    for row in evidence:
        _need(isinstance(row, dict) and set(row) <= _EVIDENCE_KEYS
              and set(row) >= _EVIDENCE_KEYS - _COMPUTED_EVIDENCE_KEYS,
              "CLAIM_STATE_EVIDENCE_INVALID")
        _put_hash(row, "content_sha256", text_sha256(row.get("content")),
                  "CLAIM_STATE_CONTENT_HASH_MISMATCH")
        _put_hash(row, "quote_sha256", text_sha256(row.get("quote")),
                  "CLAIM_STATE_QUOTE_HASH_MISMATCH")
        _put_hash(row, "claim_sha256", claim["sha256"],
                  "CLAIM_STATE_EVIDENCE_CLAIM_MISMATCH")
        _put_hash(row, "binding_sha256", _evidence_hash(row),
                  "CLAIM_STATE_EVIDENCE_HASH_MISMATCH")
    review = record.get("review")
    if review is not None:
        _need(isinstance(review, dict) and set(review) <= _REVIEW_KEYS
              and set(review) >= _REVIEW_KEYS - _COMPUTED_REVIEW_KEYS,
              "CLAIM_STATE_REVIEW_INVALID")
        _put_hash(review, "claim_sha256", claim["sha256"],
                  "CLAIM_STATE_REVIEW_CLAIM_MISMATCH")
        _put_hash(review, "evidence_sha256", _evidence_set_hash(evidence),
                  "CLAIM_STATE_REVIEW_EVIDENCE_MISMATCH")
        _put_hash(review, "cutoff", record.get("cutoff"),
                  "CLAIM_STATE_REVIEW_CUTOFF_MISMATCH")
        _put_hash(review, "binding_sha256", _review_hash(review),
                  "CLAIM_STATE_REVIEW_HASH_MISMATCH")
    unsigned = {key: record[key] for key in sorted(_RECORD_KEYS - {"record_sha256"})}
    _put_hash(record, "record_sha256", canonical_sha256(unsigned),
              "CLAIM_STATE_RECORD_HASH_MISMATCH")
    return record


def _validate_structure(record: Any) -> tuple[dict[str, str], datetime]:
    _closed(record, _RECORD_KEYS, "CLAIM_STATE_RECORD_INVALID")
    _need(type(record["schema_version"]) is int
          and record["schema_version"] == SCHEMA_VERSION,
          "CLAIM_STATE_SCHEMA_VERSION_INVALID")
    claim = _closed(record["claim"], _CLAIM_KEYS, "CLAIM_STATE_CLAIM_INVALID")
    _identifier(claim["id"], "CLAIM_STATE_CLAIM_ID_INVALID")
    _identifier(claim["author_id"], "CLAIM_STATE_AUTHOR_ID_INVALID")
    _need(type(claim["text"]) is str and 0 < len(claim["text"].strip()) <= 10000,
          "CLAIM_STATE_CLAIM_TEXT_INVALID")
    _need(claim["atomicity"] in {"atomic", "composite"},
          "CLAIM_STATE_ATOMICITY_INVALID")
    _need(claim["atomicity"] == "atomic",
          "CLAIM_STATE_COMPOSITE_REQUIRES_SPLIT")
    _hash(claim["sha256"], "CLAIM_STATE_CLAIM_HASH_INVALID")
    _need(claim["sha256"] == _claim_hash(claim),
          "CLAIM_STATE_CLAIM_HASH_MISMATCH")
    _identifier(record["operator_id"], "CLAIM_STATE_OPERATOR_ID_INVALID")
    cutoff = _timestamp(record["cutoff"], "CLAIM_STATE_CUTOFF_INVALID")
    _enum(record.get("state"), ClaimState, "CLAIM_STATE_STATE_INVALID") if "state" in record else None
    # ``state`` belongs in the closed schema and is checked below.  This guard is
    # retained for a stable error if an old caller omitted it.
    return {}, cutoff


def _validate_record_shape(record: Any) -> tuple[dict[str, str], datetime]:
    expected = set(_RECORD_KEYS)
    _closed(record, expected, "CLAIM_STATE_RECORD_INVALID")
    _need(type(record["schema_version"]) is int
          and record["schema_version"] == SCHEMA_VERSION,
          "CLAIM_STATE_SCHEMA_VERSION_INVALID")
    claim = _closed(record["claim"], _CLAIM_KEYS, "CLAIM_STATE_CLAIM_INVALID")
    _identifier(claim["id"], "CLAIM_STATE_CLAIM_ID_INVALID")
    _identifier(claim["author_id"], "CLAIM_STATE_AUTHOR_ID_INVALID")
    _need(type(claim["text"]) is str and 0 < len(claim["text"].strip()) <= 10000,
          "CLAIM_STATE_CLAIM_TEXT_INVALID")
    _need(claim["atomicity"] in {"atomic", "composite"},
          "CLAIM_STATE_ATOMICITY_INVALID")
    _need(claim["atomicity"] == "atomic",
          "CLAIM_STATE_COMPOSITE_REQUIRES_SPLIT")
    _hash(claim["sha256"], "CLAIM_STATE_CLAIM_HASH_INVALID")
    _need(claim["sha256"] == _claim_hash(claim),
          "CLAIM_STATE_CLAIM_HASH_MISMATCH")
    _identifier(record["operator_id"], "CLAIM_STATE_OPERATOR_ID_INVALID")
    cutoff = _timestamp(record["cutoff"], "CLAIM_STATE_CUTOFF_INVALID")
    _enum(record["state"], ClaimState, "CLAIM_STATE_STATE_INVALID")

    access = record["access"]
    _need(isinstance(access, list) and len(access) <= 64,
          "CLAIM_STATE_ACCESS_INVALID")
    access_map: dict[str, str] = {}
    for item in access:
        _closed(item, _ACCESS_KEYS, "CLAIM_STATE_ACCESS_INVALID")
        source_id = _identifier(item["source_id"], "CLAIM_STATE_SOURCE_ID_INVALID")
        _need(source_id not in access_map, "CLAIM_STATE_ACCESS_DUPLICATE")
        access_map[source_id] = _enum(
            item["status"], SourceAccessStatus, "CLAIM_STATE_ACCESS_STATUS_INVALID")

    evidence = record["evidence"]
    _need(isinstance(evidence, list) and len(evidence) <= 64,
          "CLAIM_STATE_EVIDENCE_INVALID")
    seen: set[str] = set()
    for row in evidence:
        _closed(row, _EVIDENCE_KEYS, "CLAIM_STATE_EVIDENCE_INVALID")
        evidence_id = _identifier(row["evidence_id"],
                                  "CLAIM_STATE_EVIDENCE_ID_INVALID")
        _need(evidence_id not in seen, "CLAIM_STATE_EVIDENCE_DUPLICATE")
        seen.add(evidence_id)
        _identifier(row["collector_id"], "CLAIM_STATE_COLLECTOR_ID_INVALID")
        source_id = _identifier(row["source_id"], "CLAIM_STATE_SOURCE_ID_INVALID")
        _need(source_id in access_map, "CLAIM_STATE_ACCESS_MISSING")
        for key in ("source_version", "current_version"):
            _identifier(row[key], "CLAIM_STATE_SOURCE_VERSION_INVALID")
        _timestamp(row["available_at"], "CLAIM_STATE_AVAILABLE_AT_INVALID")
        _need(type(row["content"]) is str and len(row["content"]) <= 500000,
              "CLAIM_STATE_CONTENT_INVALID")
        _need(type(row["quote"]) is str and len(row["quote"]) <= 50000,
              "CLAIM_STATE_QUOTE_INVALID")
        _need(type(row["quote_start"]) is int and type(row["quote_end"]) is int
              and 0 <= row["quote_start"] <= row["quote_end"] <= len(row["content"]),
              "CLAIM_STATE_QUOTE_RANGE_INVALID")
        _need(row["content"][row["quote_start"]:row["quote_end"]] == row["quote"],
              "CLAIM_STATE_QUOTE_BINDING_MISMATCH")
        _need(row["quote"] != "", "CLAIM_STATE_QUOTE_INVALID")
        for key in ("admissible", "assessable", "applicable"):
            _need(type(row[key]) is bool, "CLAIM_STATE_EVIDENCE_FLAG_INVALID")
        _enum(row["relationship"], EvidenceRelationship,
              "CLAIM_STATE_RELATIONSHIP_INVALID")
        _need(row["content_sha256"] == text_sha256(row["content"]),
              "CLAIM_STATE_CONTENT_HASH_MISMATCH")
        _need(row["quote_sha256"] == text_sha256(row["quote"]),
              "CLAIM_STATE_QUOTE_HASH_MISMATCH")
        _need(row["claim_sha256"] == claim["sha256"],
              "CLAIM_STATE_EVIDENCE_CLAIM_MISMATCH")
        _need(row["binding_sha256"] == _evidence_hash(row),
              "CLAIM_STATE_EVIDENCE_HASH_MISMATCH")

    review = record["review"]
    if review is not None:
        _closed(review, _REVIEW_KEYS, "CLAIM_STATE_REVIEW_INVALID")
        reviewer_id = _identifier(review["reviewer_id"],
                                  "CLAIM_STATE_REVIEWER_ID_INVALID")
        principals = {claim["author_id"], record["operator_id"]}
        principals.update(row["collector_id"] for row in evidence)
        _need(reviewer_id not in principals,
              "CLAIM_STATE_REVIEWER_NOT_INDEPENDENT")
        _enum(review["disposition"], ReviewerDisposition,
              "CLAIM_STATE_REVIEW_DISPOSITION_INVALID")
        _need(type(review["rationale"]) is str
              and 0 < len(review["rationale"].strip()) <= 4000,
              "CLAIM_STATE_REVIEW_RATIONALE_INVALID")
        reviewed_at = _timestamp(review["reviewed_at"],
                                 "CLAIM_STATE_REVIEW_TIME_INVALID")
        _need(reviewed_at >= cutoff, "CLAIM_STATE_REVIEW_STALE")
        if evidence:
            newest = max(_timestamp(row["available_at"],
                                    "CLAIM_STATE_AVAILABLE_AT_INVALID")
                         for row in evidence)
            _need(reviewed_at >= newest, "CLAIM_STATE_REVIEW_STALE")
        _need(review["claim_sha256"] == claim["sha256"],
              "CLAIM_STATE_REVIEW_CLAIM_MISMATCH")
        _need(review["evidence_sha256"] == _evidence_set_hash(evidence),
              "CLAIM_STATE_REVIEW_EVIDENCE_MISMATCH")
        _need(review["cutoff"] == record["cutoff"],
              "CLAIM_STATE_REVIEW_CUTOFF_MISMATCH")
        _need(review["binding_sha256"] == _review_hash(review),
              "CLAIM_STATE_REVIEW_HASH_MISMATCH")

    reasons = record["reason_codes"]
    _need(isinstance(reasons, list)
          and all(type(reason) is str for reason in reasons),
          "CLAIM_STATE_REASON_CODES_INVALID")
    _need(len(reasons) == len(set(reasons)),
          "CLAIM_STATE_REASON_CODES_INVALID")
    for reason in reasons:
        _enum(reason, ReasonCode, "CLAIM_STATE_REASON_CODE_INVALID")
    uses = record["requested_uses"]
    _need(isinstance(uses, list) and all(type(use) is str for use in uses),
          "CLAIM_STATE_USES_INVALID")
    _need(len(uses) == len(set(uses)), "CLAIM_STATE_USES_INVALID")
    for use in uses:
        _enum(use, ClaimUse, "CLAIM_STATE_USE_INVALID")

    _hash(record["record_sha256"], "CLAIM_STATE_RECORD_HASH_INVALID")
    unsigned = {key: record[key] for key in sorted(expected - {"record_sha256"})}
    _need(record["record_sha256"] == canonical_sha256(unsigned),
          "CLAIM_STATE_RECORD_HASH_MISMATCH")
    return access_map, cutoff


def _exclusion_reasons(
        row: Mapping[str, Any], access: Mapping[str, str], cutoff: datetime,
) -> list[str]:
    """Return closed, sanitized reasons an evidence row was not state-eligible."""
    reasons: list[str] = []
    status = access.get(row["source_id"])
    if status == SourceAccessStatus.GATED.value:
        reasons.append(ExclusionReason.GATED.value)
    elif status == SourceAccessStatus.ZERO_TEXT.value:
        reasons.append(ExclusionReason.ZERO_TEXT.value)
    elif status == SourceAccessStatus.MISSING.value:
        reasons.append(ExclusionReason.MISSING.value)
    if not row["content"] and ExclusionReason.ZERO_TEXT.value not in reasons:
        reasons.append(ExclusionReason.ZERO_TEXT.value)
    if row["source_version"] != row["current_version"]:
        reasons.append(ExclusionReason.STALE.value)
    if _timestamp(row["available_at"], "CLAIM_STATE_AVAILABLE_AT_INVALID") > cutoff:
        reasons.append(ExclusionReason.FUTURE.value)
    if not row["applicable"]:
        reasons.append(ExclusionReason.INAPPLICABLE.value)
    if not row["admissible"]:
        reasons.append(ExclusionReason.INADMISSIBLE.value)
    if not row["assessable"]:
        reasons.append(ExclusionReason.UNASSESSABLE.value)
    return reasons


def _eligible(row: Mapping[str, Any], access: Mapping[str, str], cutoff: datetime) -> bool:
    return not _exclusion_reasons(row, access, cutoff)


def _observed_unverifiable_reasons(
        record: Mapping[str, Any], access: Mapping[str, str], cutoff: datetime,
        supports: list[Mapping[str, Any]], contradictions: list[Mapping[str, Any]],
) -> list[str]:
    """Derive the complete ordered reason set; callers may not select a subset."""
    observed: set[str] = set()
    if supports and contradictions:
        observed.add(ReasonCode.CONFLICT.value)
    elif supports or contradictions:
        review = record["review"]
        disposition = review.get("disposition") if isinstance(review, dict) else None
        conclusive = (
            supports and disposition == ReviewerDisposition.APPROVE.value
        ) or (
            contradictions
            and disposition in {ReviewerDisposition.REJECT.value,
                                ReviewerDisposition.CONTRADICTION.value}
        )
        if not conclusive:
            observed.add(ReasonCode.MISSING_REVIEW.value)
    else:
        access_reason = {
            SourceAccessStatus.GATED.value: ReasonCode.GATED.value,
            SourceAccessStatus.ZERO_TEXT.value: ReasonCode.ZERO_TEXT.value,
            SourceAccessStatus.MISSING.value: ReasonCode.MISSING.value,
        }
        for status in access.values():
            if status in access_reason:
                observed.add(access_reason[status])
        if not access:
            observed.add(ReasonCode.MISSING.value)
        exclusion_reason = {
            ExclusionReason.GATED.value: ReasonCode.GATED.value,
            ExclusionReason.ZERO_TEXT.value: ReasonCode.ZERO_TEXT.value,
            ExclusionReason.MISSING.value: ReasonCode.MISSING.value,
            ExclusionReason.STALE.value: ReasonCode.STALE.value,
            ExclusionReason.FUTURE.value: ReasonCode.FUTURE.value,
            ExclusionReason.INAPPLICABLE.value: ReasonCode.INAPPLICABLE.value,
            ExclusionReason.INADMISSIBLE.value: ReasonCode.INADMISSIBLE.value,
            ExclusionReason.UNASSESSABLE.value: ReasonCode.UNASSESSABLE.value,
        }
        for row in record["evidence"]:
            for reason in _exclusion_reasons(row, access, cutoff):
                observed.add(exclusion_reason[reason])
        observed.add(ReasonCode.NO_RELEVANT_EVIDENCE.value)
    return [reason.value for reason in ReasonCode if reason.value in observed]


def validate_claim_state(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one and only one state, returning a sanitized use projection."""
    access, cutoff = _validate_record_shape(record)
    state = record["state"]
    eligible = [row for row in record["evidence"] if _eligible(row, access, cutoff)]
    supports = [row for row in eligible
                if row["relationship"] == EvidenceRelationship.SUPPORTS.value]
    contradictions = [row for row in eligible
                      if row["relationship"] == EvidenceRelationship.CONTRADICTS.value]
    review = record["review"]
    disposition = review.get("disposition") if isinstance(review, dict) else None

    if state == ClaimState.SUPPORTED.value:
        _need(record["reason_codes"] == [], "CLAIM_STATE_SUPPORTED_REASONS_INVALID")
        _need(bool(supports), "CLAIM_STATE_CONTENT_SOURCE_REQUIRED")
        _need(not contradictions, "CLAIM_STATE_UNRESOLVED_CONFLICT")
        _need(disposition == ReviewerDisposition.APPROVE.value,
              "CLAIM_STATE_SUPPORT_APPROVAL_REQUIRED")
    elif state == ClaimState.UNSUPPORTED.value:
        _need(record["reason_codes"] == [], "CLAIM_STATE_UNSUPPORTED_REASONS_INVALID")
        _need(bool(contradictions), "CLAIM_STATE_CONTRADICTORY_EVIDENCE_REQUIRED")
        _need(not supports, "CLAIM_STATE_UNRESOLVED_CONFLICT")
        _need(disposition in {ReviewerDisposition.REJECT.value,
                              ReviewerDisposition.CONTRADICTION.value},
              "CLAIM_STATE_REJECTION_REQUIRED")
    else:
        observed = _observed_unverifiable_reasons(
            record, access, cutoff, supports, contradictions)
        _need(bool(record["reason_codes"]),
              "CLAIM_STATE_UNVERIFIABLE_REASON_REQUIRED")
        _need(record["reason_codes"] == observed,
              "CLAIM_STATE_UNVERIFIABLE_REASONS_MISMATCH")
        _need(bool(observed), "CLAIM_STATE_STATE_MISMATCH")

    allowed = _ALLOWED_USES[state]
    _need(all(use in allowed for use in record["requested_uses"]),
          "CLAIM_STATE_USE_FORBIDDEN")
    excluded_evidence = []
    bound_sources = set()
    for row in record["evidence"]:
        bound_sources.add(row["source_id"])
        reasons = _exclusion_reasons(row, access, cutoff)
        if reasons:
            excluded_evidence.append({
                "evidence_id": row["evidence_id"],
                "reasons": reasons,
            })
    source_access_gaps = [
        {"source_id": item["source_id"], "reason": item["status"]}
        for item in record["access"]
        if item["status"] != SourceAccessStatus.CONTENT.value
        and item["source_id"] not in bound_sources
    ]
    return {
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "status": "valid",
        "validation_scope": "structural_only",
        "authenticity_verified": False,
        "consequential_authority": False,
        "claim_id": record["claim"]["id"],
        "state": state,
        "record_sha256": record["record_sha256"],
        "allowed_uses": list(allowed),
        "requested_uses": list(record["requested_uses"]),
        "excluded_evidence": excluded_evidence,
        "source_access_gaps": source_access_gaps,
        "has_excluded_gap_inputs": bool(excluded_evidence or source_access_gaps),
        "source_access_separate": True,
    }


validate_record = validate_claim_state


def authorize_use(record: Mapping[str, Any], use: str) -> dict[str, Any]:
    """Authorize only a structural, nonconsequential state projection.

    A future consequential consumer requires a separate trusted authority boundary;
    submitter-provided IDs and self-sealed hashes cannot supply that authority.
    """
    projection = validate_claim_state(record)
    _enum(use, ClaimUse, "CLAIM_STATE_USE_INVALID")
    _need(use not in _CONSEQUENTIAL_USES, "CLAIM_STATE_USE_FORBIDDEN")
    _need(use in projection["allowed_uses"], "CLAIM_STATE_USE_FORBIDDEN")
    return projection


def atomic_write_json(path: str | os.PathLike[str], value: Mapping[str, Any]) -> None:
    """Publish complete bytes or classify post-replace durability as unknown."""
    raw = canonical_json(dict(value)) + b"\n"
    _need(len(raw) <= MAX_OUTPUT_BYTES, "CLAIM_STATE_OUTPUT_LIMIT")
    target = Path(path)
    _need(target.name not in {"", ".", ".."} and target.parent.is_dir(),
          "CLAIM_STATE_OUTPUT_INVALID")
    _need(not target.is_symlink(), "CLAIM_STATE_OUTPUT_INVALID")
    pending: str | None = None
    pending_identity: tuple[int, int] | None = None
    replaced = False
    try:
        descriptor, pending = tempfile.mkstemp(prefix=".claim-state-", dir=target.parent)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            info = os.fstat(stream.fileno())
            pending_identity = (info.st_dev, info.st_ino)
        try:
            os.replace(pending, target)
            replaced = True
            pending = None
        except OSError:
            try:
                current = target.stat()
                replaced = pending_identity == (current.st_dev, current.st_ino)
                if replaced:
                    pending = None
            except OSError:
                pass
            raise
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except ClaimStateError:
        raise
    except OSError:
        code = ("CLAIM_STATE_OUTPUT_DURABILITY_UNKNOWN" if replaced
                else "CLAIM_STATE_OUTPUT_FAILED")
        raise ClaimStateError(code) from None
    finally:
        if pending is not None:
            try:
                os.unlink(pending)
            except OSError:
                pass


def _read_input(path: str) -> Any:
    try:
        if path == "-":
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        else:
            source = Path(path)
            before = source.lstat()
            _need(stat.S_ISREG(before.st_mode), "CLAIM_STATE_INPUT_INVALID")
            _need(before.st_size <= MAX_INPUT_BYTES, "CLAIM_STATE_INPUT_LIMIT")
            flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(source, flags)
            try:
                opened = os.fstat(descriptor)
                _need(stat.S_ISREG(opened.st_mode)
                      and (opened.st_dev, opened.st_ino)
                      == (before.st_dev, before.st_ino),
                      "CLAIM_STATE_INPUT_INVALID")
                _need(opened.st_size <= MAX_INPUT_BYTES,
                      "CLAIM_STATE_INPUT_LIMIT")
                chunks = bytearray()
                while len(chunks) <= MAX_INPUT_BYTES:
                    chunk = os.read(
                        descriptor,
                        min(65536, MAX_INPUT_BYTES + 1 - len(chunks)),
                    )
                    if not chunk:
                        break
                    chunks.extend(chunk)
                raw = bytes(chunks)
            finally:
                os.close(descriptor)
    except ClaimStateError:
        raise
    except OSError:
        raise ClaimStateError("CLAIM_STATE_INPUT_INVALID") from None
    _need(len(raw) <= MAX_INPUT_BYTES, "CLAIM_STATE_INPUT_LIMIT")
    return loads_strict(raw)


def _serialize_output(value: Mapping[str, Any]) -> bytes:
    raw = canonical_json(dict(value)) + b"\n"
    _need(len(raw) <= MAX_OUTPUT_BYTES, "CLAIM_STATE_OUTPUT_LIMIT")
    return raw


def describe() -> dict[str, Any]:
    return {
        "version": VERSION,
        "states": [state.value for state in ClaimState],
        "reason_codes": [reason.value for reason in ReasonCode],
        "source_access_statuses": [status.value for status in SourceAccessStatus],
        "validation_scope": "structural_only",
        "authenticity_verified": False,
        "consequential_authority": False,
        "nonconsequential_projections": {
            state: list(uses) for state, uses in _ALLOWED_USES.items()
        },
        "side_effects": ["atomic_output_file_when_requested"],
        "output_failure_classes": {
            "before_replace": "failed_prior_output_preserved",
            "after_replace_before_parent_fsync": "durability_unknown_reconcile",
        },
        "prohibited": ["provider_call", "scheduler_action", "credential_read",
                       "investment_action", "consequential_claim_authorization"],
    }


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ClaimStateError("CLAIM_STATE_ARGUMENT_INVALID")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(description=__doc__, add_help=False)
    parser.add_argument("command", choices=("describe", "validate"))
    parser.add_argument("--input", default="-")
    parser.add_argument("--output", default="-")
    try:
        args = parser.parse_args(argv)
        if args.command == "describe":
            _need(args.input == "-" and args.output == "-",
                  "CLAIM_STATE_ARGUMENT_INVALID")
            result = describe()
        else:
            result = validate_claim_state(_read_input(args.input))
        if args.output == "-":
            sys.stdout.buffer.write(_serialize_output(result))
        else:
            atomic_write_json(args.output, result)
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, ClaimStateError) else "CLAIM_STATE_FAILED"
        if not _ERROR.fullmatch(code):
            code = "CLAIM_STATE_FAILED"
        sys.stdout.buffer.write(_serialize_output({"status": "failed", "code": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
