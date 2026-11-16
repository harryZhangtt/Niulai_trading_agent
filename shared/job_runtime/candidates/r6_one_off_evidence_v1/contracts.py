"""Strict provider-free contracts for the inert R6 O1 one-off vertical."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Dict, Iterable, Mapping, Sequence

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_JOB_ID = re.compile(r"r6o1-[0-9a-f]{32}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,95}\Z")
_ENGINE_ID_KEYS = frozenset(("slot_id", "attempt_id", "operation_id"))
_EFFECT_KEYS = (
    "provider", "network", "account", "login", "private_live_root",
    "email", "socket", "subprocess", "host",
)
GRANT_KEYS = frozenset((
    "version", "kind", "logical_job_id", "preflight_nonce", "created_at",
    "slot_at", "deadline_at", "scenario", "config_sha256",
    "allocation_sha256", "prompt_sha256", "treatment_fingerprint",
    "source_generation_sha256", "custody", "max_workers", "max_attempts",
    "request_retries", "stream_retries", "replay_safe", "enabled",
    "capability_open", "provider_authorized", "countable", "effects",
))
BINDING_KEYS = frozenset((
    "version", "logical_job_id", "provider", "preflight_nonce", "scenario", "slot_id",
    "attempt_id", "operation_id", "prompt_sha256", "prompt_binding_sha256",
    "config_sha256", "allocation_sha256", "treatment_fingerprint",
    "source_generation_sha256", "result_sha256", "engine_status", "counts",
    "operation_equal", "prompt_binding_equal", "transaction", "receipt_durable",
))
EVIDENCE_KEYS = frozenset((
    "version", "scenario", "decision", "code", "countable",
    "logical_job_id", "preflight_nonce_sha256", "engine", "counters",
    "terminal", "cleanup", "second_admission", "external_effects",
    "raw_private", "public_allowlist_only",
))
PUBLIC_ALLOWLIST = tuple(sorted(EVIDENCE_KEYS))
RECEIPT_KEYS = frozenset((
    "version", "destination_name", "evidence_sha256", "publication_sha256",
    "bytes", "allowlist", "raw_included", "partial_included", "atomic",
    "no_overwrite", "primitive",
))
SCENARIOS = frozenset(("nominal", "post_admission_unknown", "pre_dispatch_stop"))
DECISIONS = frozenset(("PASS", "STOP", "UNKNOWN"))


class ContractError(ValueError):
    """Fixed, content-free contract failure."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ContractError("CANONICAL_VALUE_INVALID") from None


def sha256_bytes(value: bytes) -> str:
    require(type(value) is bytes, "BYTES_REQUIRED")
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def _exact(value: Any, keys: Iterable[str], code: str) -> Mapping[str, Any]:
    require(type(value) is dict and set(value) == set(keys), code)
    return value


def _digest(value: Any, code: str) -> str:
    require(type(value) is str and _SHA256.fullmatch(value) is not None, code)
    return value


def _instant(value: Any, code: str) -> datetime:
    require(type(value) is str and len(value) <= 64, code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ContractError(code) from None
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, code)
    return parsed.astimezone(timezone.utc)


def no_effects() -> Dict[str, bool]:
    return {key: False for key in _EFFECT_KEYS}


def validate_effects(value: Any) -> Mapping[str, Any]:
    value = _exact(value, _EFFECT_KEYS, "EFFECTS_INVALID")
    require(all(item is False for item in value.values()), "EFFECT_AUTHORITY_FORBIDDEN")
    return value


def validate_grant(value: Any, historical_job_ids: Sequence[str] = (),
                   historical_nonces: Sequence[str] = ()) -> Mapping[str, Any]:
    value = _exact(value, GRANT_KEYS, "GRANT_KEYS_INVALID")
    require(not (_ENGINE_ID_KEYS & set(value)), "ENGINE_ID_PRE_RESERVED")
    require(value["version"] == 1 and type(value["version"]) is int,
            "GRANT_VERSION_INVALID")
    require(value["kind"] == "PROVIDER_FREE_PERMANENTLY_NONAUTHORIZING",
            "GRANT_KIND_INVALID")
    require(type(value["logical_job_id"]) is str and
            _JOB_ID.fullmatch(value["logical_job_id"]) is not None,
            "LOGICAL_JOB_ID_INVALID")
    require(value["logical_job_id"] not in set(historical_job_ids),
            "HISTORICAL_JOB_ID_REUSED")
    _digest(value["preflight_nonce"], "PREFLIGHT_NONCE_INVALID")
    require(value["preflight_nonce"] not in set(historical_nonces),
            "HISTORICAL_NONCE_REUSED")
    created = _instant(value["created_at"], "CREATED_AT_INVALID")
    slot = _instant(value["slot_at"], "SLOT_AT_INVALID")
    deadline = _instant(value["deadline_at"], "DEADLINE_AT_INVALID")
    require(created < slot < deadline, "GRANT_WINDOW_INVALID")
    require(value["scenario"] in SCENARIOS, "SCENARIO_INVALID")
    for key in ("config_sha256", "allocation_sha256", "prompt_sha256",
                "treatment_fingerprint", "source_generation_sha256"):
        _digest(value[key], key.upper() + "_INVALID")
    custody = value["custody"]
    require(type(custody) is list and len(custody) == 5, "CUSTODY_INVALID")
    roles = []
    for item in custody:
        _exact(item, ("role", "name", "sha256", "bytes"), "CUSTODY_DESCRIPTOR_INVALID")
        require(item["role"] in ("binary", "argv", "config", "parser", "prompt"),
                "CUSTODY_ROLE_INVALID")
        require(type(item["name"]) is str and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", item["name"]),
            "CUSTODY_NAME_INVALID")
        _digest(item["sha256"], "CUSTODY_SHA256_INVALID")
        require(type(item["bytes"]) is int and 1 <= item["bytes"] <= 65536,
                "CUSTODY_BYTES_INVALID")
        roles.append(item["role"])
    require(sorted(roles) == ["argv", "binary", "config", "parser", "prompt"],
            "CUSTODY_ROLES_INVALID")
    expected = {
        "max_workers": 1, "max_attempts": 1, "request_retries": 0,
        "stream_retries": 0, "replay_safe": False, "enabled": False,
        "capability_open": False, "provider_authorized": False,
        "countable": False,
    }
    require(all(type(value[key]) is type(expected_value) and value[key] == expected_value
                for key, expected_value in expected.items()),
            "PROVIDER_FREE_CONSTANT_INVALID")
    validate_effects(value["effects"])
    return value


def validate_binding(value: Any) -> Mapping[str, Any]:
    value = _exact(value, BINDING_KEYS, "BINDING_KEYS_INVALID")
    require(value["version"] == 1 and type(value["version"]) is int,
            "BINDING_VERSION_INVALID")
    require(type(value["logical_job_id"]) is str and
            _JOB_ID.fullmatch(value["logical_job_id"]) is not None,
            "BINDING_JOB_INVALID")
    require(value["provider"] in ("codex_cli", "claude_host"),
            "BINDING_PROVIDER_INVALID")
    _digest(value["preflight_nonce"], "BINDING_NONCE_INVALID")
    require(value["scenario"] in ("nominal", "post_admission_unknown"),
            "BINDING_SCENARIO_INVALID")
    for key in ("slot_id", "attempt_id", "operation_id"):
        require(type(value[key]) is str and 1 <= len(value[key]) <= 512,
                "BINDING_ENGINE_ID_INVALID")
    for key in ("prompt_sha256", "prompt_binding_sha256", "config_sha256",
                "allocation_sha256", "treatment_fingerprint",
                "source_generation_sha256", "result_sha256"):
        _digest(value[key], "BINDING_DIGEST_INVALID")
    require(value["engine_status"] in ("succeeded", "unknown"),
            "BINDING_STATUS_INVALID")
    counts = _exact(value["counts"], ("job", "slot", "attempt", "provider_result"),
                    "BINDING_COUNTS_INVALID")
    require(all(type(item) is int and item == 1 for item in counts.values()),
            "BINDING_MULTIPLICITY_INVALID")
    require(value["operation_equal"] is True and
            value["prompt_binding_equal"] is True and
            value["transaction"] == "BEGIN_IMMEDIATE_SINGLE_READBACK" and
            value["receipt_durable"] is True,
            "BINDING_PROOF_INVALID")
    return value


def validate_evidence(value: Any) -> Mapping[str, Any]:
    value = _exact(value, EVIDENCE_KEYS, "EVIDENCE_KEYS_INVALID")
    require(value["version"] == 1 and type(value["version"]) is int,
            "EVIDENCE_VERSION_INVALID")
    scenario, decision = value["scenario"], value["decision"]
    require(scenario in SCENARIOS and decision in DECISIONS, "EVIDENCE_DECISION_INVALID")
    require(type(value["code"]) is str and _CODE.fullmatch(value["code"]) is not None,
            "EVIDENCE_CODE_INVALID")
    require(value["countable"] is False, "R6_COUNTABLE_FORBIDDEN")
    require(type(value["logical_job_id"]) is str and
            _JOB_ID.fullmatch(value["logical_job_id"]) is not None,
            "EVIDENCE_JOB_INVALID")
    _digest(value["preflight_nonce_sha256"], "EVIDENCE_NONCE_INVALID")
    engine = _exact(value["engine"], ("slot_id", "attempt_id", "operation_id", "status"),
                    "EVIDENCE_ENGINE_INVALID")
    counters = _exact(value["counters"], (
        "dispatch", "admission", "admission_stop", "upstream", "retry",
        "replay", "status_query", "reconstruction_dispatch"),
        "EVIDENCE_COUNTERS_INVALID")
    require(all(type(item) is int and item >= 0 for item in counters.values()),
            "EVIDENCE_COUNTERS_INVALID")
    require(counters["retry"] == counters["replay"] ==
            counters["status_query"] == counters["reconstruction_dispatch"] == 0,
            "AMBIGUITY_FENCE_BROKEN")
    expected = {
        "PASS": ("nominal", "succeeded", "exact", "complete", 1),
        "UNKNOWN": ("post_admission_unknown", "unknown", "truncated", "fault", 1),
        "STOP": ("pre_dispatch_stop", None, "absent", "not_started", 0),
    }[decision]
    require((scenario, engine["status"], value["terminal"], value["cleanup"],
             counters["dispatch"]) == expected, "EVIDENCE_STATE_CONFLICT")
    if decision == "STOP":
        require(all(engine[key] is None for key in engine), "STOP_ENGINE_ID_FORBIDDEN")
        require(counters["admission"] == counters["admission_stop"] ==
                counters["upstream"] == 0 and
                value["second_admission"] == "NOT_APPLICABLE",
                "STOP_EFFECT_CONFLICT")
    else:
        require(all(type(engine[key]) is str and engine[key]
                    for key in ("slot_id", "attempt_id", "operation_id")),
                "EVIDENCE_ENGINE_ID_MISSING")
        require(counters["admission"] == counters["admission_stop"] ==
                counters["upstream"] == 1 and value["second_admission"] == "STOP",
                "ADMISSION_MULTIPLICITY_INVALID")
    validate_effects(value["external_effects"])
    require(value["raw_private"] is True and value["public_allowlist_only"] is True,
            "PUBLICATION_CLASSIFICATION_INVALID")
    return value


def validate_publication_receipt(value: Any) -> Mapping[str, Any]:
    value = _exact(value, RECEIPT_KEYS, "PUBLICATION_RECEIPT_KEYS_INVALID")
    require(value["version"] == 1 and type(value["version"]) is int,
            "PUBLICATION_RECEIPT_VERSION_INVALID")
    require(type(value["destination_name"]) is str and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.json", value["destination_name"]),
        "PUBLICATION_DESTINATION_INVALID")
    _digest(value["evidence_sha256"], "PUBLICATION_EVIDENCE_INVALID")
    _digest(value["publication_sha256"], "PUBLICATION_DIGEST_INVALID")
    require(type(value["bytes"]) is int and 2 <= value["bytes"] <= 65536,
            "PUBLICATION_BYTES_INVALID")
    require(value["allowlist"] == list(PUBLIC_ALLOWLIST), "PUBLIC_ALLOWLIST_INVALID")
    require(value["raw_included"] is False and value["partial_included"] is False and
            value["atomic"] is True and value["no_overwrite"] is True and
            value["primitive"] in ("RENAME_EXCL", "LINK_EXCL_FALLBACK"),
            "PUBLICATION_GUARANTEE_INVALID")
    return value


def request_fingerprint(request: Mapping[str, Any]) -> str:
    require(type(request) is dict, "REQUEST_INVALID")
    return sha256_json(request)


def admission_key(operation_id: str, fingerprint: str) -> str:
    require(type(operation_id) is str and operation_id and len(operation_id) <= 512,
            "OPERATION_ID_INVALID")
    _digest(fingerprint, "REQUEST_FINGERPRINT_INVALID")
    return sha256_bytes(operation_id.encode("utf-8") + fingerprint.encode("ascii"))


__all__ = [
    "BINDING_KEYS", "ContractError", "DECISIONS", "EVIDENCE_KEYS",
    "GRANT_KEYS", "PUBLIC_ALLOWLIST", "RECEIPT_KEYS", "SCENARIOS",
    "admission_key", "canonical_bytes", "no_effects", "request_fingerprint",
    "require", "sha256_bytes", "sha256_json", "validate_binding",
    "validate_effects", "validate_evidence", "validate_grant",
    "validate_publication_receipt",
]
