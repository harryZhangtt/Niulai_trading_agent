"""Closed provider-free contracts and sanitized parsers."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .constants import DISPLAY_MODEL, MODEL
from shared.job_runtime.candidates.r6_one_off_claude_catalog_parser_v1.parser import (
    CatalogParseError, parse_frozen_catalog_jsonl,
)

_SHA = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEYS = {
    "api_key", "apikey", "access_token", "refresh_token", "token", "secret",
    "credential", "credentials", "email", "account_id", "organization_id",
}
_ACTIVITY_KEYS = {"tool_use", "tool_calls", "permission_denials", "commands"}


class ContractError(ValueError):
    pass


class AmbiguousOutcome(ContractError):
    pass


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs: List[Tuple[str, object]]) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def strict_json(raw: bytes) -> Any:
    try:
        value = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ContractError("NONFINITE_JSON")),
        )
    except ContractError:
        raise
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ContractError("MALFORMED_JSON") from exc
    return value


def parse_utc(value: object) -> datetime:
    if type(value) is not str or not value or value[-1] not in ("Z",) and "+" not in value[10:]:
        raise ContractError("TIMESTAMP_TIMEZONE_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContractError("TIMESTAMP_MUST_BE_UTC")
    return parsed


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ContractError("CLOCK_MUST_BE_UTC")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fresh_half_open(receipt: Mapping[str, object], now: datetime) -> bool:
    checked = parse_utc(receipt.get("checked_at"))
    fresh_until = parse_utc(receipt.get("fresh_until"))
    return checked <= now < fresh_until


def require_sha(value: object, code: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ContractError(code)
    return value


def parse_auth_status(raw: bytes) -> bool:
    value = strict_json(raw)
    if type(value) is not dict or type(value.get("loggedIn")) is not bool:
        raise ContractError("AUTH_STATUS_SHAPE")
    return value["loggedIn"]


def parse_catalog_stream(raw: bytes) -> Tuple[bool, int]:
    try:
        observed = parse_frozen_catalog_jsonl(raw)
    except CatalogParseError as exc:
        raise AmbiguousOutcome("CATALOG_" + exc.code) from exc
    if observed != {
        "json_lines": 3,
        "event_type_counts": {"system": 1, "assistant": 1, "result": 1},
        "terminal_result_index": 2,
        "exact_display_token": DISPLAY_MODEL,
        "terminal_occurrences": 1,
        "assistant_occurrences_ignored": 2,
        "membership_authority": "terminal_result_only",
    }:
        raise AmbiguousOutcome("CATALOG_OBSERVED_CONTRACT_DRIFT")
    return True, 2

def validate_clean_auth_evidence(receipt: Mapping[str, object], review: Mapping[str, object], now: datetime) -> None:
    required = {
        "version", "operation", "status", "model", "checked_at", "fresh_until",
        "binary_sha256", "argv_sha256", "authority_sha256", "raw", "request_accounting", "unknown_fence",
    }
    if type(receipt) is not dict or set(receipt) != required:
        raise ContractError("AUTH_RECEIPT_CLOSED_SHAPE")
    if receipt["operation"] != "auth_status" or receipt["status"] != "READY" or receipt["model"] != MODEL:
        raise ContractError("AUTH_NOT_READY")
    if not fresh_half_open(receipt, now):
        raise ContractError("AUTH_RECEIPT_STALE")
    expected_review = {
        "kind": "SYNTHETIC_AUTH_RECEIPT_REVIEW",
        "live_authority": False,
        "receipt_sha256": sha256_bytes(canonical_bytes(receipt)),
        "reviewer": "independent-provider-free-fixture-reviewer",
        "verdict": "CLEAN_FIXTURE_ONLY",
        "version": 1,
    }
    if review != expected_review:
        raise ContractError("AUTH_REVIEW_NOT_CLEAN_EXACT")
