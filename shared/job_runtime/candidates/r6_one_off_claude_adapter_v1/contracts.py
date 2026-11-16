"""Closed provider-free Stage A and strict, non-minting Stage B contracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

MODEL = "claude-opus-5-5"
SURFACE = "claude_cli"
EFFORT = "low"
ZERO_SHA256 = "0" * 64
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z0-9][a-z0-9._/-]{7,127}\Z")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{7,255}\Z")
SECRET_TOKENS = (
    "api_key", "auth_token", "authorization:", "bearer ", "password",
    "secret_value", "credential_value", "x-api-key",
)
EFFECTS = (
    "provider", "network", "account", "login", "private_live_root",
    "email", "socket", "real_process", "host", "persistent_change",
)
LIMITS = {
    "adapter_retries": 0,
    "request_retries": 0,
    "stream_retries": 0,
    "max_attempts": 1,
    "max_workers": 1,
    "concurrency": 1,
    "membership_checks_max": 1,
    "inference_requests_max": 1,
    "replay": False,
    "provider_status_after_unknown": False,
    "countable_observation": False,
}
UNKNOWN_FENCE = {
    "retry": False,
    "replay": False,
    "provider_status_calls": 0,
    "reconstruction_dispatch": 0,
    "artifact_only_reconciliation": True,
    "durable_owner_private_evidence": True,
    "provider_local": True,
}

# Immutable identities copied from the frozen design. A caller cannot substitute
# a self-consistent file for any member of this chain.
FROZEN_REFS = {
    "authorization": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-dual-provider-user-live-authorization-v2.json",
        "bytes": 3948,
        "sha256": "546ad2ac707bcd21370f55783144a51f2b65d0b98175e709d5861cecc0ca9a28",
    },
    "authorization_review": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-dual-provider-user-live-authorization-v2-independent-review.json",
        "bytes": 6853,
        "sha256": "d767dc715fef5892c8051503743fff016d72bf34482b1162c57e250c094eaa32",
    },
    "design": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-claude-live-adapter-design.json",
        "bytes": 25713,
        "sha256": "5f7a32be9115449448d7d5515bdc9f3c0cb50797217e0eba3dd2442543df771e",
    },
    "design_review": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-claude-live-adapter-design-independent-review.json",
        "bytes": 18016,
        "sha256": "8c436c72375feb0df1cd1a2e528dc38f5ca24d96bc806962307ffbba8457ac0c",
    },
    "canonical_engine": {
        "path": "shared/job_runtime/engine.py", "bytes": 71795,
        "sha256": "42721bf751ebe50cc0720138bfb66509cababd2b873e41192ee50d9cf8df10be",
    },
    "shared_o1_architecture": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/codex-live-evidence-r6-o1-architecture-decision.json",
        "bytes": 8042,
        "sha256": "abd8bf2c245ae55727761197b2c332d81f0d7629b0f67cf09f2620e528abe67f",
    },
    "shared_o1_architecture_review": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/codex-live-evidence-r6-o1-architecture-decision-independent-review.json",
        "bytes": 8142,
        "sha256": "05fea81321364c3b913318c80a387ce64d00c79468642d9d3d9156583ae7604a",
    },
    "provider_free_decision": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/codex-live-evidence-r6-o1-provider-free-decision.json",
        "bytes": 4072,
        "sha256": "c62f12dd6196f5e996bd3cd1a3268196803f1b4fabc5e642c9fabc4ded2fc2b6",
    },
    "provider_free_decision_review": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/codex-live-evidence-r6-o1-provider-free-decision-independent-review.json",
        "bytes": 6702,
        "sha256": "d543ea4d3fe4dcae918619e97bafe5d7ec8b56af22f36d5e79e4d4ff18579fc6",
    },
    "provider_free_producer": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/codex-live-evidence-r6-o1-provider-free-v1-producer-verification.json",
        "bytes": 10201,
        "sha256": "ec23455369a5d97d7bd15c6d0543e33634a60f20745dee50483701ed0ee1cbbf",
    },
    "provider_free_producer_review": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/codex-live-evidence-r6-o1-provider-free-v1-independent-review.json",
        "bytes": 9080,
        "sha256": "733b229b36cf3b6a7f467bf794c0ac88cbd37c4f77efbe3735a8b59afa897485",
    },
    "provider_free_source_closure": {
        "path": "tuning/architecture/r6_one_off_evidence_v1/source-closure-v1.json",
        "bytes": 4016,
        "sha256": "b78c88c39d79a903367bb1424443739b14fb9746a2399adb8feb7db95abf49d3",
    },
    "blocked_generic_review": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/codex-live-evidence-r6-live-v1-security-successor-blocked-review.json",
        "bytes": 2667,
        "sha256": "3936f22deb3e85537bb807c9225295acecc8ebec16a0220eb8605f84ec941df9",
    },
    "r5_runner_historical_only": {
        "path": "runtime/claude-live-smoke-20261109-r5/run_smoke.py",
        "bytes": 15274,
        "sha256": "d199fd079b7f94ca17d9fd1d6bb9e5b2339178403948d8173dabebd948b33d78",
    },
    "r5_result_historical_only": {
        "path": "runtime/claude-live-smoke-20261109-r5/result.json",
        "bytes": 417,
        "sha256": "ae7914cf59b61d3dc915b86d364cebafd3da09827219f6154d179d35442cd9c7",
    },
    "r5_no_retrofit": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/claude-live-smoke-r5-p2-no-retrofit-v2.json",
        "bytes": 3908,
        "sha256": "08a4fd76deb27eda3572144eb4fa3ce36aac558227d5f40750a5fff143850815",
    },
    "r5_no_retrofit_review": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/claude-live-smoke-r5-p2-no-retrofit-v2-independent-review.json",
        "bytes": 4420,
        "sha256": "32bd415d544c3ae8ef75df19deac4d67e714d3b0bcef3327207e4f90b62592be",
    },
    "treatment_payload": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-ab-payload-v1.json",
        "bytes": 2065,
        "sha256": "26d9a937f50dc22dade3251831e7860b4a7188c3001d5717ed4aac4d4ccac01a",
    },
    "source_cutoff": {
        "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-ab-source-cutoff-v1.json",
        "bytes": 1044,
        "sha256": "32f28a6cea0b1053321a52782abe40d6fd8a2d58b95bb954f90794ec5b733072",
    },
}
PAYLOAD_SHA256 = "3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b"

TEMPLATE_KEYS = frozenset((
    "version", "kind", "authority", "enabled", "provider_authorized",
    "surface", "model", "effort", "profile_fingerprint_sha256",
    "credential_reference", "credential_reference_sha256",
    "claude_subcap_usd", "combined_cap_usd", "limits", "effects",
))
REF_KEYS = frozenset(("path", "bytes", "sha256"))
SEAL_KEYS = frozenset((
    "version", "kind", "authority_owner", "self_minted",
    "independent_review_clean", "frozen_bindings", "claude_final_grant",
    "claude_final_grant_review", "other_provider_final_grant",
    "other_provider_final_grant_review", "stage_a_source_closure", "surface",
    "model", "effort", "expected_profile_fingerprint_sha256",
    "observed_profile_fingerprint_sha256", "credential_reference",
    "credential_reference_sha256", "model_entitled", "membership_verified",
    "claude_subcap_usd", "combined_cap_usd", "remaining_combined_budget_usd",
    "not_before", "deadline", "execution_id", "request_id", "engine_ids",
    "held_bindings", "publication", "cleanup", "unknown_fence", "limits",
    "countable_observation", "identities_fresh",
))


class ContractError(ValueError):
    """A stable fail-closed contract rejection."""


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ContractError(code)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def no_effects() -> Dict[str, int]:
    return {name: 0 for name in EFFECTS}


def _exact(value: Any, keys: Iterable[str], code: str) -> Mapping[str, Any]:
    require(type(value) is dict and set(value) == set(keys), code)
    return value


def _digest(value: Any, code: str) -> str:
    require(type(value) is str and _SHA.fullmatch(value) is not None, code)
    return value


def _safe_text(value: Any, pattern: re.Pattern[str], code: str) -> str:
    require(type(value) is str and pattern.fullmatch(value) is not None, code)
    lower = value.lower()
    require(not any(token in lower for token in SECRET_TOKENS), "SECRET_VALUE_FORBIDDEN")
    return value


def _safe_tree(value: Any, code: str) -> None:
    try:
        encoded = canonical_bytes(value).decode("ascii").lower()
    except (TypeError, ValueError, UnicodeError):
        raise ContractError(code) from None
    require(not any(token in encoded for token in SECRET_TOKENS), code)


@dataclass(frozen=True)
class TrustedArtifactRef:
    """An immutable path/bytes/hash identity supplied outside the caller seal."""

    path: str
    bytes: int
    sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TrustedArtifactRef":
        return cls(path=value["path"], bytes=value["bytes"], sha256=value["sha256"])

    def as_mapping(self) -> Mapping[str, Any]:
        return {"path": self.path, "bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True)
class TrustedExternalGrant:
    """Runner-owned immutable expectations for one external grant and review."""

    provider: str
    grant: TrustedArtifactRef
    review: TrustedArtifactRef
    grant_authority_owner: str
    grant_signer_id: str
    review_authority_owner: str
    review_signer_id: str
    held_binding_digest_sha256: str


@dataclass(frozen=True)
class TrustedExternalGrantRegistry:
    """Immutable external authority registry; caller seals cannot add or replace entries."""

    _entries: Mapping[str, TrustedExternalGrant]

    def __init__(self, entries: Iterable[TrustedExternalGrant]):
        pinned: Dict[str, TrustedExternalGrant] = {}
        for entry in tuple(entries):
            require(isinstance(entry, TrustedExternalGrant), "TRUSTED_REGISTRY_ENTRY_INVALID")
            _safe_text(entry.provider, _ID, "TRUSTED_REGISTRY_PROVIDER_INVALID")
            require(entry.provider not in pinned, "TRUSTED_REGISTRY_PROVIDER_DUPLICATE")
            require(entry.grant_authority_owner == "external_user_authority", "TRUSTED_REGISTRY_GRANT_AUTHORITY_INVALID")
            require(entry.review_authority_owner == "external_independent_reviewer", "TRUSTED_REGISTRY_REVIEW_AUTHORITY_INVALID")
            _safe_text(entry.grant_signer_id, _ID, "TRUSTED_REGISTRY_GRANT_SIGNER_INVALID")
            _safe_text(entry.review_signer_id, _ID, "TRUSTED_REGISTRY_REVIEW_SIGNER_INVALID")
            _digest(entry.held_binding_digest_sha256, "TRUSTED_REGISTRY_HELD_DIGEST_INVALID")
            for label, ref in (("GRANT", entry.grant), ("REVIEW", entry.review)):
                require(isinstance(ref, TrustedArtifactRef), "TRUSTED_REGISTRY_" + label + "_INVALID")
                require(type(ref.path) is str and ref.path and not os.path.isabs(ref.path), "TRUSTED_REGISTRY_" + label + "_PATH")
                require(type(ref.bytes) is int and ref.bytes >= 0, "TRUSTED_REGISTRY_" + label + "_BYTES")
                _digest(ref.sha256, "TRUSTED_REGISTRY_" + label + "_SHA")
            pinned[entry.provider] = entry
        require(SURFACE in pinned and len(pinned) == 2, "TRUSTED_REGISTRY_PROVIDER_SET_INVALID")
        object.__setattr__(self, "_entries", MappingProxyType(pinned))

    @property
    def entries(self) -> Mapping[str, TrustedExternalGrant]:
        return self._entries

    def entry_for(self, provider: str) -> TrustedExternalGrant:
        entry = self._entries.get(provider)
        require(entry is not None, "TRUSTED_REGISTRY_PROVIDER_MISSING")
        return entry

    def single_other_than(self, provider: str) -> TrustedExternalGrant:
        others = tuple(entry for name, entry in self._entries.items() if name != provider)
        require(len(others) == 1, "TRUSTED_REGISTRY_PROVIDER_SET_INVALID")
        return others[0]


@dataclass(frozen=True)
class HistoricalIdentityLedger:
    """Pinned runner-owned identity history; never sourced from the caller seal."""

    artifact: TrustedArtifactRef
    identities: frozenset[str]

    def __init__(self, artifact: TrustedArtifactRef, identities: Iterable[str]):
        require(isinstance(artifact, TrustedArtifactRef), "HISTORICAL_IDENTITY_LEDGER_REF_INVALID")
        frozen = frozenset(identities)
        require(all(type(value) is str and _ID.fullmatch(value) for value in frozen), "HISTORICAL_IDENTITY_LEDGER_ID_INVALID")
        object.__setattr__(self, "artifact", artifact)
        object.__setattr__(self, "identities", frozen)


_HELD_DIGEST_SELF_GRANT = "$SELF_EXTERNAL_GRANT_SHA256"


def held_binding_digest(
    held_bindings: Mapping[str, Any],
    publication: Mapping[str, Any],
    cleanup: Mapping[str, Any],
) -> str:
    """Digest every held Stage B binding with the unavoidable grant back-edge normalized."""
    bindings = _exact(held_bindings, (
        "binary", "command", "config", "catalog", "prompt", "engine", "process",
        "observer", "custody", "request",
    ), "HELD_BINDINGS_INVALID")
    catalog = dict(bindings["catalog"])
    parser = catalog.pop("parser", None)
    observer = dict(bindings["observer"])
    require("grant_seal_sha256" in observer, "OBSERVER_KEYS_INVALID")
    observer["grant_seal_sha256"] = _HELD_DIGEST_SELF_GRANT
    return sha256_json({
        "binary": bindings["binary"],
        "argv": bindings["command"],
        "config": bindings["config"],
        "catalog": catalog,
        "parser": parser,
        "prompt": bindings["prompt"],
        "engine": bindings["engine"],
        "process": bindings["process"],
        "request": bindings["request"],
        "observer": observer,
        "custody": bindings["custody"],
        "publication": publication,
        "cleanup": cleanup,
    })


def validate_stage_a_template(value: Any) -> Mapping[str, Any]:
    item = _exact(value, TEMPLATE_KEYS, "STAGE_A_KEYS_INVALID")
    require(
        item["version"] == 1
        and item["kind"] == "R6_CLAUDE_STAGE_A_PERMANENTLY_NONAUTHORIZING",
        "STAGE_A_KIND_INVALID",
    )
    require(
        item["authority"] == "NONE" and item["enabled"] is False
        and item["provider_authorized"] is False,
        "STAGE_A_AUTHORITY_INVALID",
    )
    require(
        item["surface"] == SURFACE and item["model"] == MODEL
        and item["effort"] == EFFORT,
        "STAGE_A_TREATMENT_INVALID",
    )
    _digest(item["profile_fingerprint_sha256"], "PROFILE_FINGERPRINT_INVALID")
    reference = _safe_text(item["credential_reference"], _REF, "CREDENTIAL_REFERENCE_INVALID")
    require(
        sha256_bytes(reference.encode("utf-8")) == item["credential_reference_sha256"],
        "CREDENTIAL_REFERENCE_HASH_INVALID",
    )
    require(type(item["claude_subcap_usd"]) in (int, float) and item["claude_subcap_usd"] == 0.01, "CLAUDE_SUBCAP_INVALID")
    require(type(item["combined_cap_usd"]) in (int, float) and item["combined_cap_usd"] == 0.02, "COMBINED_CAP_INVALID")
    require(item["limits"] == LIMITS, "LIMITS_INVALID")
    require(item["effects"] == no_effects(), "EFFECTS_INVALID")
    _safe_tree(item, "SECRET_VALUE_FORBIDDEN")
    return item


def validate_stage_a_evidence(
    value: Any, shared_evidence: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    keys = (
        "version", "outcome", "reason_code", "countable_observation",
        "definitely_not_submitted", "membership_check_count", "admission_count",
        "upstream_attempt_count", "inference_count", "retry_count",
        "replay_count", "provider_status_calls", "reconstruction_dispatch",
        "cleanup_complete", "atomic_publication_complete",
        "owner_private_evidence_preserved", "durable_unknown_evidence",
        "effects", "shared_evidence_sha256",
    )
    item = _exact(value, keys, "STAGE_A_EVIDENCE_KEYS_INVALID")
    require(item["version"] == 1 and item["outcome"] in ("PASS", "STOP", "UNKNOWN"), "STAGE_A_OUTCOME_INVALID")
    require(type(item["reason_code"]) is str and item["reason_code"], "STAGE_A_REASON_INVALID")
    require(item["countable_observation"] is False, "STAGE_A_COUNTABLE_INVALID")
    for name in ("membership_check_count", "admission_count", "upstream_attempt_count", "inference_count"):
        require(type(item[name]) is int and 0 <= item[name] <= 1, "STAGE_A_COUNTER_INVALID")
    for name in ("retry_count", "replay_count", "provider_status_calls", "reconstruction_dispatch"):
        require(item[name] == 0, "STAGE_A_RETRY_FENCE_INVALID")
    require(item["effects"] == no_effects(), "STAGE_A_EFFECTS_INVALID")
    _digest(item["shared_evidence_sha256"], "STAGE_A_SHARED_HASH_INVALID")
    outcome = item["outcome"]
    if outcome == "STOP":
        require(
            item["definitely_not_submitted"] is True
            and item["admission_count"] == 0
            and item["upstream_attempt_count"] == 0
            and item["inference_count"] == 0
            and item["atomic_publication_complete"] is False
            and item["durable_unknown_evidence"] is False
            and item["shared_evidence_sha256"] == ZERO_SHA256,
            "STAGE_A_STOP_SEMANTICS_INVALID",
        )
    elif outcome == "PASS":
        require(
            item["definitely_not_submitted"] is False
            and item["membership_check_count"] == 1
            and item["admission_count"] == 1
            and item["upstream_attempt_count"] == 1
            and item["inference_count"] == 1
            and item["cleanup_complete"] is True
            and item["atomic_publication_complete"] is True
            and item["owner_private_evidence_preserved"] is True
            and item["durable_unknown_evidence"] is False
            and item["shared_evidence_sha256"] != ZERO_SHA256,
            "STAGE_A_PASS_SEMANTICS_INVALID",
        )
    else:
        require(
            item["definitely_not_submitted"] is False
            and item["membership_check_count"] == 1
            and item["admission_count"] == 1
            and item["upstream_attempt_count"] == 1
            and item["inference_count"] == 1
            and item["atomic_publication_complete"] is False
            and item["owner_private_evidence_preserved"] is True
            and item["durable_unknown_evidence"] is True
            and item["shared_evidence_sha256"] != ZERO_SHA256,
            "STAGE_A_UNKNOWN_SEMANTICS_INVALID",
        )
    if outcome in ("PASS", "UNKNOWN"):
        require(type(shared_evidence) is dict, "STAGE_A_SHARED_EVIDENCE_REQUIRED")
        require(
            sha256_bytes(canonical_bytes(shared_evidence)) == item["shared_evidence_sha256"],
            "STAGE_A_SHARED_EVIDENCE_HASH_MISMATCH",
        )
    return item


def _member_path(root: Path, relative: str, code: str) -> Path:
    require(type(relative) is str and relative and not os.path.isabs(relative), code + "_PATH")
    parts = Path(relative).parts
    require(parts and all(part not in ("", ".", "..") for part in parts), code + "_PATH")
    cursor = root
    for part in parts:
        cursor = cursor / part
        try:
            status = os.lstat(cursor)
        except OSError:
            raise ContractError(code + "_MISSING") from None
        require(not stat.S_ISLNK(status.st_mode), code + "_SYMLINK")
    return cursor


def validate_artifact_ref(value: Any, root: Path, code: str) -> Mapping[str, Any]:
    item = _exact(value, REF_KEYS, code + "_KEYS")
    _digest(item["sha256"], code + "_SHA")
    require(type(item["bytes"]) is int and item["bytes"] >= 0, code + "_BYTES")
    path = _member_path(Path(root), item["path"], code)
    status = os.lstat(path)
    require(stat.S_ISREG(status.st_mode), code + "_TYPE")
    raw = path.read_bytes()
    require(len(raw) == item["bytes"] and sha256_bytes(raw) == item["sha256"], code + "_DRIFT")
    return item


def _validate_exact_ref(value: Any, root: Path, expected: Mapping[str, Any], code: str) -> Mapping[str, Any]:
    item = _exact(value, REF_KEYS, code + "_KEYS")
    require(item == expected, code + "_IDENTITY")
    return validate_artifact_ref(item, root, code)


def _load_json_ref(value: Any, root: Path, code: str) -> Tuple[Mapping[str, Any], bytes]:
    item = validate_artifact_ref(value, root, code)
    raw = _member_path(Path(root), item["path"], code).read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ContractError(code + "_JSON") from None
    require(type(parsed) is dict, code + "_JSON")
    return parsed, raw


def _validate_historical_identity_ledger(
    value: Optional[HistoricalIdentityLedger], root: Path,
) -> HistoricalIdentityLedger:
    require(isinstance(value, HistoricalIdentityLedger), "HISTORICAL_IDENTITY_LEDGER_REQUIRED")
    doc, _ = _load_json_ref(value.artifact.as_mapping(), root, "HISTORICAL_IDENTITY_LEDGER")
    item = _exact(doc, ("version", "kind", "identities"), "HISTORICAL_IDENTITY_LEDGER_KEYS_INVALID")
    require(item["version"] == 1 and item["kind"] == "R6_HISTORICAL_IDENTITY_LEDGER", "HISTORICAL_IDENTITY_LEDGER_KIND_INVALID")
    require(
        type(item["identities"]) is list
        and item["identities"] == sorted(value.identities)
        and len(item["identities"]) == len(value.identities),
        "HISTORICAL_IDENTITY_LEDGER_CONTENT_INVALID",
    )
    return value


def _instant(value: Any, code: str) -> datetime:
    require(type(value) is str and value.endswith("Z"), code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ContractError(code) from None
    require(parsed.tzinfo is not None, code)
    return parsed.astimezone(timezone.utc)


def _validate_external_grant(
    doc: Mapping[str, Any], trusted: TrustedExternalGrant,
    frozen: Mapping[str, Any], closure_sha: str,
) -> None:
    keys = (
        "version", "kind", "provider", "authority_owner", "signer_id", "self_minted",
        "authorization_sha256", "authorization_review_sha256", "design_sha256",
        "design_review_sha256", "stage_a_source_closure_sha256", "execution_id",
        "request_id", "engine_ids", "not_before", "deadline", "claude_subcap_usd",
        "combined_cap_usd", "remaining_combined_budget_usd", "request_fingerprint_sha256",
        "held_binding_digest_sha256",
    )
    item = _exact(doc, keys, "FINAL_GRANT_KEYS_INVALID")
    require(item["version"] == 1 and item["kind"] == "R6_PROVIDER_FINAL_GRANT", "FINAL_GRANT_KIND_INVALID")
    require(item["provider"] == trusted.provider, "FINAL_GRANT_PROVIDER_INVALID")
    require(
        item["authority_owner"] == trusted.grant_authority_owner
        and item["signer_id"] == trusted.grant_signer_id
        and item["self_minted"] is False,
        "FINAL_GRANT_SELF_MINTED",
    )
    require(item["authorization_sha256"] == frozen["authorization"]["sha256"], "FINAL_GRANT_AUTHORIZATION_DRIFT")
    require(item["authorization_review_sha256"] == frozen["authorization_review"]["sha256"], "FINAL_GRANT_AUTHORIZATION_REVIEW_DRIFT")
    require(item["design_sha256"] == frozen["design"]["sha256"], "FINAL_GRANT_DESIGN_DRIFT")
    require(item["design_review_sha256"] == frozen["design_review"]["sha256"], "FINAL_GRANT_DESIGN_REVIEW_DRIFT")
    require(item["stage_a_source_closure_sha256"] == closure_sha, "FINAL_GRANT_CLOSURE_DRIFT")
    _digest(item["request_fingerprint_sha256"], "FINAL_GRANT_REQUEST_FINGERPRINT")
    _exact(item["engine_ids"], ("job_id", "slot_id", "attempt_id", "operation_id"), "FINAL_GRANT_ENGINE_IDS_INVALID")
    require(item["held_binding_digest_sha256"] == trusted.held_binding_digest_sha256, "FINAL_GRANT_HELD_BINDING_REGISTRY_DRIFT")
    require(item["claude_subcap_usd"] == 0.01 and item["combined_cap_usd"] == 0.02, "FINAL_GRANT_CAP_INVALID")
    require(type(item["remaining_combined_budget_usd"]) in (int, float) and 0.01 <= item["remaining_combined_budget_usd"] <= 0.02, "FINAL_GRANT_REMAINING_BUDGET_INVALID")


def _validate_external_review(
    doc: Mapping[str, Any],
    trusted: TrustedExternalGrant,
    grant_sha: str,
    frozen: Mapping[str, Any],
) -> None:
    keys = (
        "version", "kind", "provider", "authority_owner", "signer_id", "self_review",
        "decision", "grant_sha256", "authorization_sha256", "design_sha256",
    )
    item = _exact(doc, keys, "FINAL_GRANT_REVIEW_KEYS_INVALID")
    require(item["version"] == 1 and item["kind"] == "R6_PROVIDER_FINAL_GRANT_INDEPENDENT_REVIEW", "FINAL_GRANT_REVIEW_KIND_INVALID")
    require(item["provider"] == trusted.provider, "FINAL_GRANT_REVIEW_PROVIDER_INVALID")
    require(
        item["authority_owner"] == trusted.review_authority_owner
        and item["signer_id"] == trusted.review_signer_id
        and item["self_review"] is False,
        "FINAL_GRANT_REVIEW_SELF_MINTED",
    )
    require(item["decision"] == "CLEAN" and item["grant_sha256"] == grant_sha, "FINAL_GRANT_REVIEW_NOT_CLEAN")
    require(item["authorization_sha256"] == frozen["authorization"]["sha256"] and item["design_sha256"] == frozen["design"]["sha256"], "FINAL_GRANT_REVIEW_BINDING_DRIFT")


def _validate_frozen_bindings(value: Any, root: Path) -> Mapping[str, Any]:
    item = _exact(value, FROZEN_REFS.keys(), "FROZEN_BINDINGS_KEYS_INVALID")
    for name, expected in FROZEN_REFS.items():
        _validate_exact_ref(item[name], root, expected, "FROZEN_" + name.upper())
    return item


def _validate_binary(value: Any, root: Path) -> Mapping[str, Any]:
    item = _exact(value, (
        "artifact", "canonical_path", "descriptor_identity_sha256", "device",
        "inode", "owner_uid", "mode", "official_asset",
    ), "BINARY_KEYS_INVALID")
    validate_artifact_ref(item["artifact"], root, "BINARY_ARTIFACT")
    validate_artifact_ref(item["official_asset"], root, "BINARY_OFFICIAL_ASSET")
    require(type(item["canonical_path"]) is str and os.path.isabs(item["canonical_path"]), "BINARY_CANONICAL_PATH_INVALID")
    _digest(item["descriptor_identity_sha256"], "BINARY_DESCRIPTOR_INVALID")
    for name in ("device", "inode", "owner_uid"):
        require(type(item[name]) is int and item[name] >= 0, "BINARY_DESCRIPTOR_INVALID")
    require(type(item["mode"]) is int and item["mode"] & 0o111 != 0, "BINARY_MODE_INVALID")
    expected = sha256_json({name: item[name] for name in ("canonical_path", "device", "inode", "owner_uid", "mode")})
    require(item["descriptor_identity_sha256"] == expected, "BINARY_DESCRIPTOR_MISMATCH")
    return item


def _validate_config(value: Any, root: Path) -> Mapping[str, Any]:
    item = _exact(value, ("artifact", "environment_allowlist", "environment_allowlist_sha256"), "CONFIG_KEYS_INVALID")
    artifact = validate_artifact_ref(item["artifact"], root, "CONFIG_ARTIFACT")
    config_raw = _member_path(Path(root), artifact["path"], "CONFIG_ARTIFACT").read_bytes().lower()
    require(not any(token.encode("ascii") in config_raw for token in SECRET_TOKENS), "CONFIG_SECRET_FORBIDDEN")
    require(type(item["environment_allowlist"]) is list and item["environment_allowlist"], "ENV_ALLOWLIST_INVALID")
    require(all(type(x) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", x) for x in item["environment_allowlist"]), "ENV_ALLOWLIST_INVALID")
    require(len(set(item["environment_allowlist"])) == len(item["environment_allowlist"]), "ENV_ALLOWLIST_DUPLICATE")
    _safe_tree(item["environment_allowlist"], "ENV_ALLOWLIST_SECRET")
    require(item["environment_allowlist_sha256"] == sha256_json(item["environment_allowlist"]), "ENV_ALLOWLIST_HASH_INVALID")
    return item


def _validate_command(value: Any, root: Path, binary: Mapping[str, Any], config: Mapping[str, Any]) -> Mapping[str, Any]:
    item = _exact(value, (
        "artifact", "argv", "shell", "model_occurrences", "effort_occurrences",
        "environment_allowlist_sha256",
    ), "COMMAND_KEYS_INVALID")
    ref = validate_artifact_ref(item["artifact"], root, "COMMAND_ARTIFACT")
    require(type(item["argv"]) is list and all(type(x) is str and x for x in item["argv"]), "ARGV_INVALID")
    require(item["shell"] is False and item["argv"][0] == binary["canonical_path"], "COMMAND_SHELL_OR_BINARY_INVALID")
    model_indexes = [index for index, token in enumerate(item["argv"]) if token == "--model"]
    effort_indexes = [index for index, token in enumerate(item["argv"]) if token == "--effort"]
    require(
        item["argv"].count(MODEL) == 1 and item["model_occurrences"] == 1
        and len(model_indexes) == 1 and model_indexes[0] + 1 < len(item["argv"])
        and item["argv"][model_indexes[0] + 1] == MODEL,
        "COMMAND_MODEL_COUNT_INVALID",
    )
    require(
        item["argv"].count(EFFORT) == 1 and item["effort_occurrences"] == 1
        and len(effort_indexes) == 1 and effort_indexes[0] + 1 < len(item["argv"])
        and item["argv"][effort_indexes[0] + 1] == EFFORT,
        "COMMAND_EFFORT_COUNT_INVALID",
    )
    require(item["environment_allowlist_sha256"] == config["environment_allowlist_sha256"], "COMMAND_ENVIRONMENT_DRIFT")
    require(ref["sha256"] == sha256_bytes(canonical_bytes(item["argv"])), "COMMAND_ARGV_BYTES_INVALID")
    _safe_tree(item["argv"], "COMMAND_SECRET_FORBIDDEN")
    return item


def _validate_catalog(value: Any, root: Path) -> Mapping[str, Any]:
    item = _exact(value, (
        "artifact", "parser", "model", "model_occurrence_count", "membership_verified",
        "check_count", "entitlement_verified",
    ), "CATALOG_KEYS_INVALID")
    artifact = validate_artifact_ref(item["artifact"], root, "CATALOG_ARTIFACT")
    parser_doc, _ = _load_json_ref(item["parser"], root, "CATALOG_PARSER")
    require(
        parser_doc == {"version": 1, "kind": "R6_HELD_CATALOG_PARSER", "line_mode": "exact_unique", "model": MODEL},
        "CATALOG_PARSER_SEMANTICS_INVALID",
    )
    try:
        raw_models = _member_path(Path(root), artifact["path"], "CATALOG_ARTIFACT").read_bytes().decode("utf-8", "strict").splitlines()
    except UnicodeError:
        raise ContractError("CATALOG_RAW_MALFORMED") from None
    require(raw_models.count(MODEL) == 1, "CATALOG_RAW_MODEL_COUNT_INVALID")
    require(item["model"] == MODEL and item["model_occurrence_count"] == 1, "CATALOG_MODEL_COUNT_INVALID")
    require(item["membership_verified"] is True and item["entitlement_verified"] is True and item["check_count"] == 1, "CATALOG_MEMBERSHIP_INVALID")
    return item


def _validate_engine(value: Any, root: Path, engine_ids: Mapping[str, Any]) -> Mapping[str, Any]:
    item = _exact(value, (
        "canonical_engine", "readback", "job_count", "slot_count", "attempt_count",
        "operation_count", "operation_equal", "native_prompt_equal", "prompt_sha256",
    ), "ENGINE_BINDING_KEYS_INVALID")
    _validate_exact_ref(item["canonical_engine"], root, FROZEN_REFS["canonical_engine"], "ENGINE_CANONICAL")
    require(item["readback"] == engine_ids, "ENGINE_READBACK_ID_MISMATCH")
    require(tuple(item[name] for name in ("job_count", "slot_count", "attempt_count", "operation_count")) == (1, 1, 1, 1), "ENGINE_NOT_ONE_TO_ONE")
    require(item["operation_equal"] is True and item["native_prompt_equal"] is True, "ENGINE_EQUALITY_INVALID")
    _digest(item["prompt_sha256"], "ENGINE_PROMPT_HASH_INVALID")
    return item


def _validate_process(
    value: Any, root: Path, binary: Mapping[str, Any], engine_ids: Mapping[str, Any],
) -> Mapping[str, Any]:
    item = _exact(value, (
        "process_id", "process_group_id", "new_process_group", "shell",
        "binary_descriptor_identity_sha256", "stdout", "stderr", "terminal", "cleanup_receipt",
    ), "PROCESS_KEYS_INVALID")
    require(type(item["process_id"]) is int and item["process_id"] > 0, "PROCESS_ID_INVALID")
    require(type(item["process_group_id"]) is int and item["process_group_id"] > 0, "PROCESS_GROUP_INVALID")
    require(item["new_process_group"] is True and item["shell"] is False, "PROCESS_MODE_INVALID")
    require(item["binary_descriptor_identity_sha256"] == binary["descriptor_identity_sha256"], "PROCESS_BINARY_DRIFT")
    for name in ("stdout", "stderr"):
        validate_artifact_ref(item[name], root, "PROCESS_" + name.upper())
    terminal_doc, _ = _load_json_ref(item["terminal"], root, "PROCESS_TERMINAL")
    require(
        terminal_doc == {"version": 1, "kind": "R6_HELD_TERMINAL", "status": "COMPLETE", "process_id": item["process_id"], "attempt_id": engine_ids["attempt_id"]},
        "PROCESS_TERMINAL_SEMANTICS_INVALID",
    )
    cleanup_doc, _ = _load_json_ref(item["cleanup_receipt"], root, "PROCESS_CLEANUP_RECEIPT")
    require(
        cleanup_doc == {"version": 1, "kind": "R6_PROCESS_CLEANUP", "complete": True, "process_id": item["process_id"], "process_group_id": item["process_group_id"]},
        "PROCESS_CLEANUP_SEMANTICS_INVALID",
    )
    return item


def _validate_prompt(value: Any, root: Path, engine_ids: Mapping[str, Any], process: Mapping[str, Any]) -> Mapping[str, Any]:
    item = _exact(value, (
        "artifact", "payload_sha256", "source_cutoff_sha256", "operation_id",
        "job_id", "slot_id", "attempt_id", "provider_process_id",
    ), "PROMPT_KEYS_INVALID")
    validate_artifact_ref(item["artifact"], root, "PROMPT_ARTIFACT")
    require(item["payload_sha256"] == PAYLOAD_SHA256, "PROMPT_PAYLOAD_DRIFT")
    require(item["source_cutoff_sha256"] == FROZEN_REFS["source_cutoff"]["sha256"], "PROMPT_CUTOFF_DRIFT")
    for name in ("operation_id", "job_id", "slot_id", "attempt_id"):
        require(item[name] == engine_ids[name], "PROMPT_ENGINE_ID_DRIFT")
    require(item["provider_process_id"] == process["process_id"], "PROMPT_PROCESS_DRIFT")
    return item


def _validate_observer(
    value: Any,
    root: Path,
    engine_ids: Mapping[str, Any],
    process: Mapping[str, Any],
    request: Mapping[str, Any],
    prompt: Mapping[str, Any],
    grant_sha: str,
) -> Mapping[str, Any]:
    item = _exact(value, (
        "observer_id", "source_fingerprint_sha256", "config_fingerprint_sha256",
        "listener_fingerprint_sha256", "request", "request_fingerprint_sha256",
        "model", "native_prompt_sha256", "engine_ids", "attempt_id", "process_id",
        "admission_count", "observed_upstream_count", "grant_seal_sha256",
    ), "OBSERVER_KEYS_INVALID")
    _safe_text(item["observer_id"], _ID, "OBSERVER_ID_INVALID")
    for name in ("source_fingerprint_sha256", "config_fingerprint_sha256", "listener_fingerprint_sha256"):
        _digest(item[name], "OBSERVER_FINGERPRINT_INVALID")
    validate_artifact_ref(item["request"], root, "OBSERVER_REQUEST")
    require(item["request"] == request["artifact"], "OBSERVER_REQUEST_REF_DRIFT")
    require(item["request_fingerprint_sha256"] == request["request_fingerprint_sha256"], "OBSERVER_REQUEST_FINGERPRINT_DRIFT")
    require(item["model"] == MODEL, "OBSERVER_MODEL_DRIFT")
    require(item["native_prompt_sha256"] == prompt["artifact"]["sha256"], "OBSERVER_PROMPT_DRIFT")
    require(item["engine_ids"] == engine_ids, "OBSERVER_ENGINE_IDS_DRIFT")
    require(item["attempt_id"] == engine_ids["attempt_id"] and item["process_id"] == process["process_id"], "OBSERVER_IDENTITY_DRIFT")
    require(item["admission_count"] == 1 and item["observed_upstream_count"] == 1, "OBSERVER_COUNT_INVALID")
    require(item["grant_seal_sha256"] == grant_sha, "OBSERVER_GRANT_DRIFT")
    return item


def _validate_custody(value: Any) -> Mapping[str, Any]:
    item = _exact(value, (
        "root", "owner_uid", "mode", "nofollow_path_walk", "separate_root",
        "owner_private", "workspace_local",
    ), "CUSTODY_KEYS_INVALID")
    require(type(item["root"]) is str and item["root"].startswith(".job-runtime/live-provider-evidence/r6-one-off/claude_cli/"), "CUSTODY_ROOT_INVALID")
    require(type(item["owner_uid"]) is int and item["owner_uid"] >= 0, "CUSTODY_OWNER_INVALID")
    require(item["mode"] == 0o700, "CUSTODY_MODE_INVALID")
    require(all(item[name] is True for name in ("nofollow_path_walk", "separate_root", "owner_private", "workspace_local")), "CUSTODY_POLICY_INVALID")
    return item


def _validate_request(value: Any, root: Path, engine_ids: Mapping[str, Any], process: Mapping[str, Any]) -> Mapping[str, Any]:
    item = _exact(value, (
        "artifact", "request_fingerprint_sha256", "operation_binding_sha256",
        "operation_id", "provider_process_id",
    ), "REQUEST_KEYS_INVALID")
    request_doc, _ = _load_json_ref(item["artifact"], root, "REQUEST_ARTIFACT")
    _digest(item["request_fingerprint_sha256"], "REQUEST_FINGERPRINT_INVALID")
    expected = sha256_bytes((engine_ids["operation_id"] + item["request_fingerprint_sha256"]).encode("utf-8"))
    require(item["operation_binding_sha256"] == expected, "REQUEST_OPERATION_BINDING_INVALID")
    require(item["operation_id"] == engine_ids["operation_id"] and item["provider_process_id"] == process["process_id"], "REQUEST_IDENTITY_DRIFT")
    require(
        request_doc == {
            "version": 1, "kind": "R6_HELD_REQUEST", "model": MODEL,
            "request_fingerprint_sha256": item["request_fingerprint_sha256"],
            "operation_id": item["operation_id"], "provider_process_id": item["provider_process_id"],
        },
        "REQUEST_ARTIFACT_SEMANTICS_INVALID",
    )
    return item


def _validate_publication(value: Any, root: Path) -> Mapping[str, Any]:
    item = _exact(value, (
        "receipt", "atomic", "no_overwrite", "owner_private_complete", "sanitized_complete",
        "files_fsynced", "directories_fsynced", "closed_schema_validated", "hashes_validated",
        "modes_validated", "recursive_secret_scan_clean", "partial_final_absent",
    ), "PUBLICATION_KEYS_INVALID")
    receipt_doc, _ = _load_json_ref(item["receipt"], root, "PUBLICATION_RECEIPT")
    for name in set(item) - {"receipt"}:
        require(item[name] is True, "PUBLICATION_INCOMPLETE")
    expected = {"version": 1, "kind": "R6_PUBLICATION_RECEIPT"}
    expected.update({name: item[name] for name in item if name != "receipt"})
    require(receipt_doc == expected, "PUBLICATION_RECEIPT_SEMANTICS_INVALID")
    return item


def _validate_cleanup(value: Any, root: Path) -> Mapping[str, Any]:
    item = _exact(value, (
        "receipt", "process_group_terminated", "process_group_reaped", "observer_stopped",
        "endpoint_removed", "descriptors_closed", "only_enumerated_temps_removed",
        "residual_children", "unlisted_effects", "unknown_evidence_preserved",
    ), "CLEANUP_KEYS_INVALID")
    receipt_doc, _ = _load_json_ref(item["receipt"], root, "CLEANUP_RECEIPT")
    for name in ("process_group_terminated", "process_group_reaped", "observer_stopped", "endpoint_removed", "descriptors_closed", "only_enumerated_temps_removed", "unknown_evidence_preserved"):
        require(item[name] is True, "CLEANUP_INCOMPLETE")
    require(item["residual_children"] == 0 and item["unlisted_effects"] is False, "CLEANUP_RESIDUAL_EFFECT")
    expected = {"version": 1, "kind": "R6_CLEANUP_RECEIPT"}
    expected.update({name: item[name] for name in item if name != "receipt"})
    require(receipt_doc == expected, "CLEANUP_RECEIPT_SEMANTICS_INVALID")
    return item


def validate_stage_b_seal(
    value: Any, root: Path, now: Optional[datetime] = None,
    historical_ids: Sequence[str] = (),
    trusted_external_grants: Optional[TrustedExternalGrantRegistry] = None,
    historical_identity_ledger: Optional[HistoricalIdentityLedger] = None,
) -> Mapping[str, Any]:
    """Validate caller refs against runner-owned authority and identity registries."""
    require(isinstance(trusted_external_grants, TrustedExternalGrantRegistry), "TRUSTED_EXTERNAL_GRANT_REGISTRY_REQUIRED")
    ledger = _validate_historical_identity_ledger(historical_identity_ledger, Path(root))
    item = _exact(value, SEAL_KEYS, "STAGE_B_KEYS_INVALID")
    require(item["version"] == 1 and item["kind"] == "EXTERNALLY_SEALED_R6_CLAUDE_FINAL_GRANT", "STAGE_B_KIND_INVALID")
    require(item["authority_owner"] == "external_dual_provider_authority" and item["self_minted"] is False and item["independent_review_clean"] is True, "STAGE_B_NO_SELF_MINT")
    frozen = _validate_frozen_bindings(item["frozen_bindings"], Path(root))
    closure_doc, closure_raw = _load_json_ref(item["stage_a_source_closure"], Path(root), "STAGE_A_SOURCE_CLOSURE")
    require(item["stage_a_source_closure"]["path"] == "tuning/architecture/r6_one_off_claude_adapter_v1/source-closure-v1.json", "STAGE_A_SOURCE_CLOSURE_PATH")
    require(closure_doc.get("status") == "FROZEN_PROVIDER_FREE_CLAUDE_ADAPTER_SOURCE_CLOSURE", "STAGE_A_SOURCE_CLOSURE_STATUS")
    closure_sha = sha256_bytes(closure_raw)

    claude_trusted = trusted_external_grants.entry_for(SURFACE)
    other_trusted = trusted_external_grants.single_other_than(SURFACE)
    claude_doc, _ = _load_json_ref(item["claude_final_grant"], Path(root), "CLAUDE_FINAL_GRANT")
    other_doc, _ = _load_json_ref(item["other_provider_final_grant"], Path(root), "OTHER_PROVIDER_FINAL_GRANT")
    _validate_external_grant(claude_doc, claude_trusted, frozen, closure_sha)
    require(other_doc.get("provider") == other_trusted.provider and other_doc.get("provider") != SURFACE, "OTHER_PROVIDER_INVALID")
    _validate_external_grant(other_doc, other_trusted, frozen, closure_sha)
    claude_review, _ = _load_json_ref(item["claude_final_grant_review"], Path(root), "CLAUDE_FINAL_GRANT_REVIEW")
    other_review, _ = _load_json_ref(item["other_provider_final_grant_review"], Path(root), "OTHER_PROVIDER_FINAL_GRANT_REVIEW")
    _validate_external_review(claude_review, claude_trusted, item["claude_final_grant"]["sha256"], frozen)
    _validate_external_review(other_review, other_trusted, item["other_provider_final_grant"]["sha256"], frozen)
    _validate_exact_ref(item["claude_final_grant"], Path(root), claude_trusted.grant.as_mapping(), "CLAUDE_FINAL_GRANT_REGISTRY")
    _validate_exact_ref(item["claude_final_grant_review"], Path(root), claude_trusted.review.as_mapping(), "CLAUDE_FINAL_GRANT_REVIEW_REGISTRY")
    _validate_exact_ref(item["other_provider_final_grant"], Path(root), other_trusted.grant.as_mapping(), "OTHER_PROVIDER_FINAL_GRANT_REGISTRY")
    _validate_exact_ref(item["other_provider_final_grant_review"], Path(root), other_trusted.review.as_mapping(), "OTHER_PROVIDER_FINAL_GRANT_REVIEW_REGISTRY")

    require(item["surface"] == SURFACE and item["model"] == MODEL and item["effort"] == EFFORT, "STAGE_B_TREATMENT_INVALID")
    expected = _digest(item["expected_profile_fingerprint_sha256"], "EXPECTED_PROFILE_INVALID")
    require(_digest(item["observed_profile_fingerprint_sha256"], "OBSERVED_PROFILE_INVALID") == expected, "PROFILE_MISMATCH")
    reference = _safe_text(item["credential_reference"], _REF, "CREDENTIAL_REFERENCE_INVALID")
    require(sha256_bytes(reference.encode("utf-8")) == item["credential_reference_sha256"], "CREDENTIAL_REFERENCE_HASH_INVALID")
    require(item["model_entitled"] is True and item["membership_verified"] is True, "MODEL_ENTITLEMENT_INVALID")
    require(item["claude_subcap_usd"] == 0.01 and item["combined_cap_usd"] == 0.02, "CAP_INVALID")
    require(type(item["remaining_combined_budget_usd"]) in (int, float) and 0.01 <= item["remaining_combined_budget_usd"] <= 0.02, "REMAINING_BUDGET_INVALID")
    start = _instant(item["not_before"], "WINDOW_START_INVALID")
    end = _instant(item["deadline"], "WINDOW_END_INVALID")
    require(end - start == timedelta(minutes=30), "WINDOW_NOT_EXACT_30_MINUTES")
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    require(start <= instant <= end, "WINDOW_NOT_CURRENT")

    execution_id = _safe_text(item["execution_id"], _ID, "EXECUTION_ID_INVALID")
    request_id = _safe_text(item["request_id"], _ID, "REQUEST_ID_INVALID")
    engine_ids = _exact(item["engine_ids"], ("job_id", "slot_id", "attempt_id", "operation_id"), "ENGINE_IDS_INVALID")
    identities = [execution_id, request_id]
    for name in ("job_id", "slot_id", "attempt_id", "operation_id"):
        identities.append(_safe_text(engine_ids[name], _ID, "ENGINE_ID_INVALID"))
    historical = ledger.identities.union(historical_ids)
    require(len(set(identities)) == len(identities) and not set(identities).intersection(historical) and item["identities_fresh"] is True, "ENGINE_IDS_NOT_FRESH")
    for grant_doc in (claude_doc, other_doc):
        require(grant_doc["execution_id"] == execution_id and grant_doc["request_id"] == request_id, "FINAL_GRANT_IDENTITY_DRIFT")
        require(grant_doc["engine_ids"] == engine_ids, "FINAL_GRANT_ENGINE_IDS_DRIFT")
        require(grant_doc["not_before"] == item["not_before"] and grant_doc["deadline"] == item["deadline"], "FINAL_GRANT_WINDOW_DRIFT")
        require(grant_doc["claude_subcap_usd"] == item["claude_subcap_usd"] and grant_doc["combined_cap_usd"] == item["combined_cap_usd"] and grant_doc["remaining_combined_budget_usd"] == item["remaining_combined_budget_usd"], "FINAL_GRANT_BUDGET_DRIFT")

    bindings = _exact(item["held_bindings"], ("binary", "command", "config", "catalog", "prompt", "engine", "process", "observer", "custody", "request"), "HELD_BINDINGS_INVALID")
    binary = _validate_binary(bindings["binary"], Path(root))
    config = _validate_config(bindings["config"], Path(root))
    _validate_command(bindings["command"], Path(root), binary, config)
    _validate_catalog(bindings["catalog"], Path(root))
    engine = _validate_engine(bindings["engine"], Path(root), engine_ids)
    process = _validate_process(bindings["process"], Path(root), binary, engine_ids)
    prompt = _validate_prompt(bindings["prompt"], Path(root), engine_ids, process)
    require(engine["prompt_sha256"] == prompt["artifact"]["sha256"], "ENGINE_PROMPT_DRIFT")
    request = _validate_request(bindings["request"], Path(root), engine_ids, process)
    require(claude_doc["request_fingerprint_sha256"] == request["request_fingerprint_sha256"] and other_doc["request_fingerprint_sha256"] == request["request_fingerprint_sha256"], "FINAL_GRANT_REQUEST_DRIFT")
    _validate_observer(bindings["observer"], Path(root), engine_ids, process, request, prompt, item["claude_final_grant"]["sha256"])
    _validate_custody(bindings["custody"])
    _validate_publication(item["publication"], Path(root))
    _validate_cleanup(item["cleanup"], Path(root))
    digest = held_binding_digest(bindings, item["publication"], item["cleanup"])
    require(claude_doc["held_binding_digest_sha256"] == digest and other_doc["held_binding_digest_sha256"] == digest, "FINAL_GRANT_HELD_BINDING_DIGEST_DRIFT")
    require(item["unknown_fence"] == UNKNOWN_FENCE, "UNKNOWN_FENCE_INVALID")
    require(item["limits"] == LIMITS, "LIMITS_INVALID")
    require(item["countable_observation"] is False, "COUNTABLE_OBSERVATION_INVALID")
    _safe_tree(item, "SECRET_VALUE_FORBIDDEN")
    return item


def stage_a_template(profile_fingerprint_sha256: str, credential_reference: str) -> Dict[str, Any]:
    value = {
        "version": 1,
        "kind": "R6_CLAUDE_STAGE_A_PERMANENTLY_NONAUTHORIZING",
        "authority": "NONE",
        "enabled": False,
        "provider_authorized": False,
        "surface": SURFACE,
        "model": MODEL,
        "effort": EFFORT,
        "profile_fingerprint_sha256": profile_fingerprint_sha256,
        "credential_reference": credential_reference,
        "credential_reference_sha256": sha256_bytes(credential_reference.encode("utf-8")),
        "claude_subcap_usd": 0.01,
        "combined_cap_usd": 0.02,
        "limits": dict(LIMITS),
        "effects": no_effects(),
    }
    validate_stage_a_template(value)
    return value
