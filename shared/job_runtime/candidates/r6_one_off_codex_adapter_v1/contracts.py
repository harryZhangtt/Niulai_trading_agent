"""Closed provider-free Stage A and strict validation-only Stage B contracts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Dict, Iterable, Mapping, Optional

PROVIDER = "codex_cli"
RELEASE = "0.167.0"
MODEL = "gpt-6.1-sol"
EFFORT = "low"
BINARY_REALPATH = "/Users/bytedance/.codex/packages/standalone/releases/0.167.0-aarch64-apple-darwin/bin/codex"
BINARY_BYTES = 270815376
BINARY_SHA256 = "030316ecfbb41f4e7946e584b0063ef333b7a36cd312ba349f2f6869e39b62cc"
ARCHIVE_PATH = ".research-sources/codex-0.167-official-20261109/codex-aarch64-apple-darwin.tar.gz"
ARCHIVE_BYTES = 108379331
ARCHIVE_SHA256 = "4b22a2a971be2791c3e31f912f3e77a88ebd64a65812a7289ccba65dd6425fe9"
OFFICIAL_ASSET = "/openai/codex/releases/download/rust-v0.167.0/codex-aarch64-apple-darwin.tar.gz"
PROMPT_BYTES = 526
PROMPT_SHA256 = "3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b"
CUTOFF_SHA256 = "32f28a6cea0b1053321a52782abe40d6fd8a2d58b95bb954f90794ec5b733072"
CATALOG_PARSER_ID = "r6_codex_catalog_parser_v1"
CATALOG_PARSER_SPEC = "r6_codex_catalog_parser_v1|strict-json-object|unique-model-tokens|exact-one-gpt-6.1-sol|entitlement-true|request-bound|raw-sha-bound"
CATALOG_PARSER_SOURCE_SHA256 = "2d18b806ae5dc387d6fdb065669bbeeb59daca067cb12e04cfb878feafc396f0"
OTHER_AUTHORITY_PATH = "shared/job_runtime/candidates/r6_one_off_codex_adapter_v1/other-provider-authority-v1.json"
OTHER_AUTHORITY_BYTES = 2022
OTHER_AUTHORITY_SHA256 = "ae8a289d4b00cd2f5fd1957aa8fb0b1079e08a65c42e5e0ad78f800f016f61ad"
CANONICAL_ARGV = [
    BINARY_REALPATH, "exec", "--model", MODEL, "--config",
    'model_reasoning_effort="low"', "--json", "-",
]
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z0-9][a-z0-9._/-]{7,191}\Z")
_REF_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{7,255}\Z")
SECRET_TOKENS = ("api_key", "auth_token", "authorization: bearer", "password", "secret_value", "credential_value")
EFFECTS = ("provider", "network", "account", "login", "private_live_root", "email", "socket", "subprocess", "host", "persistent_change", "business")
LIMITS = {"request_retries": 0, "stream_retries": 0, "max_attempts": 1, "concurrency": 1, "catalog_requests_max": 1, "inference_requests_max": 1, "admissions_max": 1, "replay": False, "provider_status_after_unknown": False, "countable_observation": False}
FROZEN_REFS = {
    "authorization": ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-dual-provider-user-live-authorization-v2.json", 3948, "546ad2ac707bcd21370f55783144a51f2b65d0b98175e709d5861cecc0ca9a28"),
    "authorization_review": ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-dual-provider-user-live-authorization-v2-independent-review.json", 6853, "d767dc715fef5892c8051503743fff016d72bf34482b1162c57e250c094eaa32"),
    "design": ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-live-adapter-design.json", 21988, "fcbc295924072c0af191776dc8470c2b5c52191fa8fa66bf32b3d8deb7003bca"),
    "design_review": ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-live-adapter-design-independent-review.json", 14216, "1cc4a13c8b9ecddf9aa96349adc373f0226860f67316ea87eda6a386a6ca53ee"),
    "shared_source_closure": ("tuning/architecture/r6_one_off_evidence_v1/source-closure-v1.json", 4016, "b78c88c39d79a903367bb1424443739b14fb9746a2399adb8feb7db95abf49d3"),
    "engine": ("shared/job_runtime/engine.py", 71795, "42721bf751ebe50cc0720138bfb66509cababd2b873e41192ee50d9cf8df10be"),
    "authority_manifest": ("shared/job_runtime/candidates/isolated_canary_q1/authority-manifest-v2.json", 2911, "b542ec00324f58137f7ff7662ae6c980e8df8990f3a14a2c9f759339ad9209b6"),
    "treatment_binding": ("mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-ab-treatment-binding-v1.json", 2864, "6284984d4d48796df2ba96918d983e6a998a60d3b9bff807f3639da6c97b4332"),
    "payload": ("mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-ab-payload-v1.json", 2065, "26d9a937f50dc22dade3251831e7860b4a7188c3001d5717ed4aac4d4ccac01a"),
    "cutoff": ("mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-ab-source-cutoff-v1.json", 1044, CUTOFF_SHA256),
    "asset_binding": ("mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-codex-0167-asset-binding-v2.json", 4097, "f20a2e979d680326a26f564e1c1103ea1f11f2620617a4f447be810f6e8d5729"),
}

class ContractError(ValueError):
    pass

def require(ok: bool, code: str) -> None:
    if not ok:
        raise ContractError(code)

def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")

def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def no_effects() -> Dict[str, int]:
    return {name: 0 for name in EFFECTS}

def _exact(value: Any, keys: Iterable[str], code: str) -> Mapping[str, Any]:
    require(type(value) is dict and set(value) == set(keys), code)
    return value

def _digest(value: Any, code: str) -> str:
    require(type(value) is str and _SHA.fullmatch(value) is not None, code)
    return value

def _safe(value: Any, pattern: re.Pattern, code: str) -> str:
    require(type(value) is str and pattern.fullmatch(value) is not None, code)
    require(not any(token in value.lower() for token in SECRET_TOKENS), "SECRET_VALUE_FORBIDDEN")
    return value

def _instant(value: Any, code: str) -> datetime:
    require(type(value) is str and value.endswith("Z"), code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ContractError(code) from None
    return parsed.astimezone(timezone.utc)

def artifact_ref(path: str, root: Path) -> Dict[str, Any]:
    raw = (root / path).read_bytes()
    return {"path": path, "bytes": len(raw), "sha256": sha256_bytes(raw)}

def validate_artifact_ref(value: Any, root: Path, code: str) -> Mapping[str, Any]:
    item = _exact(value, ("path", "bytes", "sha256"), code + "_KEYS")
    require(type(item["path"]) is str and item["path"] and not os.path.isabs(item["path"]) and ".." not in Path(item["path"]).parts, code + "_PATH")
    require(type(item["bytes"]) is int and item["bytes"] > 0, code + "_BYTES")
    _digest(item["sha256"], code + "_SHA")
    path = root / item["path"]
    try:
        info = os.lstat(path)
    except OSError:
        raise ContractError(code + "_MISSING") from None
    require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode), code + "_TYPE")
    raw = path.read_bytes()
    require(len(raw) == item["bytes"] and sha256_bytes(raw) == item["sha256"], code + "_DRIFT")
    return item

def validate_exact_ref(value: Any, name: str, root: Path) -> Mapping[str, Any]:
    item = validate_artifact_ref(value, root, "REF_" + name.upper())
    path, size, digest = FROZEN_REFS[name]
    require((item["path"], item["bytes"], item["sha256"]) == (path, size, digest), "REF_" + name.upper() + "_NOT_FROZEN")
    return item

def _load_json_artifact(value: Mapping[str, Any], root: Path, code: str) -> Mapping[str, Any]:
    """Load one held JSON object while rejecting duplicate keys and non-objects."""
    raw = (root / value["path"]).read_bytes()
    try:
        text = raw.decode("utf-8", "strict")
        def pairs(items):
            result = {}
            for key, item in items:
                if key in result:
                    raise ContractError(code + "_DUPLICATE_KEY")
                result[key] = item
            return result
        loaded = json.loads(text, object_pairs_hook=pairs)
    except ContractError:
        raise
    except (UnicodeError, json.JSONDecodeError):
        raise ContractError(code + "_MALFORMED") from None
    require(type(loaded) is dict, code + "_NOT_OBJECT")
    return loaded

def stage_a_template(profile_fingerprint_sha256: str, credential_reference: str) -> Dict[str, Any]:
    result = {"version": 1, "kind": "R6_CODEX_STAGE_A_PERMANENTLY_NONAUTHORIZING", "authority": "NONE", "enabled": False, "provider_authorized": False, "provider": PROVIDER, "release": RELEASE, "model": MODEL, "effort": EFFORT, "profile_fingerprint_sha256": profile_fingerprint_sha256, "credential_reference": credential_reference, "credential_reference_sha256": sha256_bytes(credential_reference.encode("utf-8")), "codex_subcap_usd": 0.01, "combined_cap_usd": 0.02, "limits": dict(LIMITS), "effects": no_effects()}
    validate_stage_a_template(result)
    return result

def validate_stage_a_template(value: Any) -> Mapping[str, Any]:
    keys = ("version", "kind", "authority", "enabled", "provider_authorized", "provider", "release", "model", "effort", "profile_fingerprint_sha256", "credential_reference", "credential_reference_sha256", "codex_subcap_usd", "combined_cap_usd", "limits", "effects")
    item = _exact(value, keys, "STAGE_A_KEYS_INVALID")
    require(item["version"] == 1 and item["kind"] == "R6_CODEX_STAGE_A_PERMANENTLY_NONAUTHORIZING", "STAGE_A_KIND_INVALID")
    require(item["authority"] == "NONE" and item["enabled"] is False and item["provider_authorized"] is False, "STAGE_A_AUTHORITY_INVALID")
    require((item["provider"], item["release"], item["model"], item["effort"]) == (PROVIDER, RELEASE, MODEL, EFFORT), "STAGE_A_TREATMENT_INVALID")
    _digest(item["profile_fingerprint_sha256"], "PROFILE_FINGERPRINT_INVALID")
    ref = _safe(item["credential_reference"], _REF_TEXT, "CREDENTIAL_REFERENCE_INVALID")
    require(item["credential_reference_sha256"] == sha256_bytes(ref.encode("utf-8")), "CREDENTIAL_REFERENCE_HASH_INVALID")
    require(item["codex_subcap_usd"] == 0.01 and item["combined_cap_usd"] == 0.02, "CAP_INVALID")
    require(item["limits"] == LIMITS and item["effects"] == no_effects(), "STAGE_A_CONSTANT_INVALID")
    return item

def _load_other_authority(root: Path) -> tuple:
    ref = {"path": OTHER_AUTHORITY_PATH, "bytes": OTHER_AUTHORITY_BYTES, "sha256": OTHER_AUTHORITY_SHA256}
    validate_artifact_ref(ref, root, "OTHER_AUTHORITY")
    registry = _load_json_artifact(ref, root, "OTHER_AUTHORITY")
    registry = _exact(registry, ("version", "status", "authority_owner", "provider", "identity", "treatment", "binary_archive", "projection", "review_policy"), "OTHER_AUTHORITY_KEYS_INVALID")
    require(registry["version"] == "r6-other-provider-authority-1" and registry["status"] == "PINNED_EXTERNAL_EXPECTED_OTHER_PROVIDER_AUTHORITY" and registry["authority_owner"] == "independent_other_provider_registry" and registry["provider"] == "claude_cli", "OTHER_AUTHORITY_IDENTITY_INVALID")
    return registry, ref

def _validate_provider_grant_pair(grant_ref: Mapping[str, Any], review_ref: Mapping[str, Any], root: Path, provider: str, seal: Mapping[str, Any], now: datetime) -> None:
    grant = _load_json_artifact(grant_ref, root, "FINAL_GRANT")
    grant = _exact(grant, ("version", "kind", "issuer_role", "self_minted", "provider", "authorization", "authorization_review", "subject"), "FINAL_GRANT_KEYS_INVALID")
    require(grant["version"] == 1 and grant["kind"] == "R6_PROVIDER_FINAL_GRANT" and grant["issuer_role"] == "independent_authorization_owner" and grant["self_minted"] is False, "FINAL_GRANT_ISSUER_INVALID")
    require(grant["provider"] == provider, "FINAL_GRANT_PROVIDER_INVALID")
    require(grant["authorization"] == seal["refs"]["authorization"] and grant["authorization_review"] == seal["refs"]["authorization_review"], "FINAL_GRANT_AUTHORIZATION_BINDING_INVALID")
    subject = _exact(grant["subject"], ("identity", "treatment", "binary_archive", "bindings", "request", "budget_window", "limits", "effects"), "FINAL_GRANT_SUBJECT_INVALID")
    identity = _exact(subject["identity"], ("provider", "release", "model", "effort", "profile_selector", "expected_account_fingerprint_sha256", "observed_account_fingerprint_sha256", "credential_reference", "credential_reference_sha256", "model_entitled"), "FINAL_GRANT_IDENTITY_INVALID")
    treatment = _exact(subject["treatment"], ("provider", "release", "model", "effort"), "FINAL_GRANT_TREATMENT_INVALID")
    binary = _exact(subject["binary_archive"], ("realpath", "bytes", "sha256", "owner_uid", "mode", "archive_path", "archive_bytes", "archive_sha256", "official_asset", "asset_binding_ref"), "FINAL_GRANT_BINARY_INVALID")
    bindings = _exact(subject["bindings"], ("argv", "config", "parser", "prompt", "engine_source", "gateway", "process", "custody", "publication", "source_closure"), "FINAL_GRANT_BINDINGS_INVALID")
    for name, value in bindings.items():
        validate_artifact_ref(value, root, "FINAL_GRANT_BINDING_" + name.upper())
    validate_artifact_ref(binary["asset_binding_ref"], root, "FINAL_GRANT_ASSET_BINDING")
    request = _exact(subject["request"], ("execution_id", "operation_id", "request_id", "request_fingerprint", "gateway_id", "process_start_identity", "custody_root_class"), "FINAL_GRANT_REQUEST_INVALID")
    for name in ("execution_id", "operation_id", "request_id", "gateway_id", "process_start_identity"):
        _safe(request[name], _ID, "FINAL_GRANT_REQUEST_ID_INVALID")
    _digest(request["request_fingerprint"], "FINAL_GRANT_REQUEST_FINGERPRINT_INVALID")
    budget = _exact(subject["budget_window"], ("currency", "provider_subcap_usd", "combined_cap_usd", "prior_dual_provider_spend_usd", "remaining_combined_budget_usd", "not_before", "deadline"), "FINAL_GRANT_BUDGET_INVALID")
    require(budget["currency"] == "USD" and budget["provider_subcap_usd"] == 0.01 and budget["combined_cap_usd"] == 0.02, "FINAL_GRANT_CAP_INVALID")
    require(type(budget["prior_dual_provider_spend_usd"]) in (int, float) and 0 <= budget["prior_dual_provider_spend_usd"] <= 0.01, "FINAL_GRANT_SPEND_INVALID")
    require(type(budget["remaining_combined_budget_usd"]) in (int, float) and budget["remaining_combined_budget_usd"] >= 0.01 and budget["prior_dual_provider_spend_usd"] + budget["remaining_combined_budget_usd"] <= 0.02, "FINAL_GRANT_REMAINING_INVALID")
    grant_start, grant_end = _instant(budget["not_before"], "FINAL_GRANT_WINDOW_START_INVALID"), _instant(budget["deadline"], "FINAL_GRANT_WINDOW_END_INVALID")
    require(grant_end - grant_start == timedelta(minutes=30) and grant_start <= now <= grant_end, "FINAL_GRANT_WINDOW_INVALID")
    require(subject["limits"] == LIMITS, "FINAL_GRANT_LIMITS_INVALID")
    effects = _exact(subject["effects"], EFFECTS, "FINAL_GRANT_EFFECTS_INVALID")
    require(all(value == {"injected": True, "default": "DENY"} for value in effects.values()), "FINAL_GRANT_EFFECTS_INVALID")
    expected = _digest(identity["expected_account_fingerprint_sha256"], "FINAL_GRANT_EXPECTED_ACCOUNT_INVALID")
    require(identity["observed_account_fingerprint_sha256"] == expected and identity["model_entitled"] is True, "FINAL_GRANT_ACCOUNT_INVALID")
    credential = _safe(identity["credential_reference"], _REF_TEXT, "FINAL_GRANT_CREDENTIAL_INVALID")
    require(identity["credential_reference_sha256"] == sha256_bytes(credential.encode("utf-8")), "FINAL_GRANT_CREDENTIAL_HASH_INVALID")
    require(treatment == {key: identity[key] for key in ("provider", "release", "model", "effort")}, "FINAL_GRANT_TREATMENT_IDENTITY_MISMATCH")
    if provider == PROVIDER:
        expected_subject = {
            "identity": seal["identity"],
            "treatment": {"provider": PROVIDER, "release": RELEASE, "model": MODEL, "effort": EFFORT},
            "binary_archive": dict(seal["binary"], asset_binding_ref=seal["refs"]["asset_binding"]),
            "bindings": {"argv": seal["held_artifacts"]["argv"], "config": seal["held_artifacts"]["config"], "parser": seal["held_artifacts"]["catalog_parser"], "prompt": seal["held_artifacts"]["prompt"], "engine_source": seal["refs"]["engine"], "gateway": seal["held_artifacts"]["gateway_receipt"], "process": seal["held_artifacts"]["process_receipt"], "custody": seal["held_artifacts"]["custody_receipt"], "publication": seal["held_artifacts"]["publication_receipt"], "source_closure": seal["refs"]["stage_a_source_closure"]},
            "request": {"execution_id": seal["engine"]["execution_id"], "operation_id": seal["engine"]["operation_id"], "request_id": seal["engine"]["request_id"], "request_fingerprint": seal["engine"]["request_fingerprint"], "gateway_id": seal["gateway"]["gateway_id"], "process_start_identity": seal["gateway"]["provider_process_start_identity"], "custody_root_class": seal["custody"]["root_class"]},
            "budget_window": {"currency": "USD", "provider_subcap_usd": seal["window_budget"]["codex_subcap_usd"], "combined_cap_usd": seal["window_budget"]["combined_cap_usd"], "prior_dual_provider_spend_usd": seal["window_budget"]["prior_dual_provider_spend_usd"], "remaining_combined_budget_usd": seal["window_budget"]["remaining_combined_budget_usd"], "not_before": seal["window_budget"]["not_before"], "deadline": seal["window_budget"]["deadline"]},
            "limits": seal["limits"], "effects": seal["effect_dependencies"],
        }
        require(subject == expected_subject, "CODEX_FINAL_GRANT_SEAL_MISMATCH")
    else:
        require(provider == "claude_cli", "OTHER_FINAL_GRANT_PROVIDER_INVALID")
        registry, registry_ref = _load_other_authority(root)
        projection = _exact(registry["projection"], ("artifact_bindings", "budget_window", "custody_root_class", "effects", "limits", "shared_request_fields"), "OTHER_AUTHORITY_PROJECTION_INVALID")
        require(projection["artifact_bindings"] == {"argv": "held.argv", "config": "held.config", "parser": "held.catalog_parser", "prompt": "held.prompt", "engine_source": "refs.engine", "gateway": "held.gateway_receipt", "process": "held.process_receipt", "custody": "held.custody_receipt", "publication": "held.publication_receipt", "source_closure": "refs.stage_a_source_closure"}, "OTHER_AUTHORITY_PROJECTION_INVALID")
        expected_subject = {
            "identity": registry["identity"], "treatment": registry["treatment"],
            "binary_archive": dict(registry["binary_archive"], asset_binding_ref=registry_ref),
            "bindings": {"argv": seal["held_artifacts"]["argv"], "config": seal["held_artifacts"]["config"], "parser": seal["held_artifacts"]["catalog_parser"], "prompt": seal["held_artifacts"]["prompt"], "engine_source": seal["refs"]["engine"], "gateway": seal["held_artifacts"]["gateway_receipt"], "process": seal["held_artifacts"]["process_receipt"], "custody": seal["held_artifacts"]["custody_receipt"], "publication": seal["held_artifacts"]["publication_receipt"], "source_closure": seal["refs"]["stage_a_source_closure"]},
            "request": {"execution_id": seal["engine"]["execution_id"], "operation_id": seal["engine"]["operation_id"], "request_id": seal["engine"]["request_id"], "request_fingerprint": seal["engine"]["request_fingerprint"], "gateway_id": seal["gateway"]["gateway_id"], "process_start_identity": seal["gateway"]["provider_process_start_identity"], "custody_root_class": projection["custody_root_class"]},
            "budget_window": {"currency": "USD", "provider_subcap_usd": seal["window_budget"]["codex_subcap_usd"], "combined_cap_usd": seal["window_budget"]["combined_cap_usd"], "prior_dual_provider_spend_usd": seal["window_budget"]["prior_dual_provider_spend_usd"], "remaining_combined_budget_usd": seal["window_budget"]["remaining_combined_budget_usd"], "not_before": seal["window_budget"]["not_before"], "deadline": seal["window_budget"]["deadline"]},
            "limits": seal["limits"], "effects": seal["effect_dependencies"],
        }
        require(subject == expected_subject, "OTHER_FINAL_GRANT_EXTERNAL_AUTHORITY_MISMATCH")
    review = _load_json_artifact(review_ref, root, "FINAL_GRANT_REVIEW")
    review = _exact(review, ("version", "kind", "reviewer_role", "verdict", "subject", "checks"), "FINAL_GRANT_REVIEW_KEYS_INVALID")
    require(review["version"] == 1 and review["kind"] == "R6_PROVIDER_FINAL_GRANT_REVIEW" and review["reviewer_role"] == "independent_reviewer" and review["verdict"] == "CLEAN", "FINAL_GRANT_REVIEW_NOT_CLEAN")
    require(review["subject"] == dict(grant_ref), "FINAL_GRANT_REVIEW_SUBJECT_MISMATCH")
    checks = _exact(review["checks"], ("authorization", "identity", "treatment", "binary_archive", "bindings", "budget_window", "limits", "effects"), "FINAL_GRANT_REVIEW_CHECKS_INVALID")
    require(all(value is True for value in checks.values()), "FINAL_GRANT_REVIEW_CHECK_FAILED")
    if provider == "claude_cli":
        registry, _ = _load_other_authority(root)
        policy = _exact(registry["review_policy"], ("checks", "reviewer_role", "verdict"), "OTHER_AUTHORITY_REVIEW_POLICY_INVALID")
        require(policy == {"checks": ["authorization", "identity", "treatment", "binary_archive", "bindings", "budget_window", "limits", "effects"], "reviewer_role": review["reviewer_role"], "verdict": review["verdict"]}, "OTHER_FINAL_GRANT_REVIEW_AUTHORITY_MISMATCH")

def validate_stage_b_seal(value: Any, root: Path, now: Optional[datetime] = None) -> Mapping[str, Any]:
    """Validate a preexisting external seal without minting authority or effects."""
    keys = ("version", "kind", "authority_owner", "self_minted", "independent_review_verdict", "refs", "identity", "binary", "held_artifacts", "command", "config", "catalog", "prompt", "window_budget", "engine", "gateway", "custody", "publication_cleanup", "terminal_policy", "effect_dependencies", "limits")
    item = _exact(value, keys, "STAGE_B_KEYS_INVALID")
    require(item["version"] == 1 and item["kind"] == "EXTERNALLY_SEALED_R6_CODEX_FINAL_GRANT_VALIDATION", "STAGE_B_KIND_INVALID")
    require(item["authority_owner"] == "independent_dual_provider_authority" and item["self_minted"] is False and item["independent_review_verdict"] == "CLEAN", "STAGE_B_NO_SELF_MINT")
    refs = _exact(item["refs"], tuple(FROZEN_REFS) + ("codex_final_grant", "codex_final_grant_review", "other_provider_final_grant", "other_provider_final_grant_review", "stage_a_source_closure"), "STAGE_B_REFS_INVALID")
    for name in FROZEN_REFS:
        validate_exact_ref(refs[name], name, root)
    for name in ("codex_final_grant", "codex_final_grant_review", "other_provider_final_grant", "other_provider_final_grant_review", "stage_a_source_closure"):
        validate_artifact_ref(refs[name], root, "REF_" + name.upper())
    auth = _load_json_artifact(refs["authorization"], root, "AUTHORIZATION")
    auth_review = _load_json_artifact(refs["authorization_review"], root, "AUTHORIZATION_REVIEW")
    require(auth.get("status") == "AUTHORIZED_DUAL_PROVIDER_EFFECT_SCOPE_PENDING_EXACT_GRANTS_AND_PREFLIGHTS", "AUTHORIZATION_STATUS_INVALID")
    require(auth_review.get("verdict") == "CLEAN_USER_AUTHORIZATION_SCOPE", "AUTHORIZATION_REVIEW_INVALID")
    require(type(auth_review.get("bindings")) is dict and auth_review["bindings"].get("subject") == dict(refs["authorization"]), "AUTHORIZATION_REVIEW_SUBJECT_INVALID")
    identity = _exact(item["identity"], ("provider", "release", "model", "effort", "profile_selector", "expected_account_fingerprint_sha256", "observed_account_fingerprint_sha256", "credential_reference", "credential_reference_sha256", "model_entitled"), "IDENTITY_INVALID")
    require((identity["provider"], identity["release"], identity["model"], identity["effort"], identity["profile_selector"]) == (PROVIDER, RELEASE, MODEL, EFFORT, "current CLI profile"), "IDENTITY_CONSTANT_INVALID")
    expected = _digest(identity["expected_account_fingerprint_sha256"], "EXPECTED_ACCOUNT_INVALID")
    require(identity["observed_account_fingerprint_sha256"] == expected and identity["model_entitled"] is True, "ACCOUNT_OR_ENTITLEMENT_INVALID")
    credential = _safe(identity["credential_reference"], _REF_TEXT, "CREDENTIAL_REFERENCE_INVALID")
    require(identity["credential_reference_sha256"] == sha256_bytes(credential.encode("utf-8")), "CREDENTIAL_REFERENCE_HASH_INVALID")
    binary = _exact(item["binary"], ("realpath", "bytes", "sha256", "owner_uid", "mode", "archive_path", "archive_bytes", "archive_sha256", "official_asset"), "BINARY_INVALID")
    require(binary == {"realpath": BINARY_REALPATH, "bytes": BINARY_BYTES, "sha256": BINARY_SHA256, "owner_uid": 501, "mode": "0o755", "archive_path": ARCHIVE_PATH, "archive_bytes": ARCHIVE_BYTES, "archive_sha256": ARCHIVE_SHA256, "official_asset": OFFICIAL_ASSET}, "BINARY_IDENTITY_DRIFT")
    held = _exact(item["held_artifacts"], ("argv", "config", "catalog", "catalog_parser", "prompt", "process_receipt", "gateway_receipt", "custody_receipt", "publication_receipt"), "HELD_ARTIFACTS_INVALID")
    for name, ref in held.items():
        validate_artifact_ref(ref, root, "HELD_" + name.upper())
    command = _exact(item["command"], ("native_exec", "shell", "prompt_transport", "prompt_occurrences", "machine_readable_terminal", "binary_realpath", "argv_ref"), "COMMAND_INVALID")
    require(command == {"native_exec": True, "shell": False, "prompt_transport": "stdin_exact_bytes", "prompt_occurrences": 1, "machine_readable_terminal": True, "binary_realpath": BINARY_REALPATH, "argv_ref": held["argv"]}, "COMMAND_SEMANTICS_INVALID")
    config = _exact(item["config"], ("provider", "release", "model", "effort", "request_retries", "stream_retries", "max_attempts", "concurrency", "countable_observation", "config_ref"), "CONFIG_INVALID")
    require(config == {"provider": PROVIDER, "release": RELEASE, "model": MODEL, "effort": EFFORT, "request_retries": 0, "stream_retries": 0, "max_attempts": 1, "concurrency": 1, "countable_observation": False, "config_ref": held["config"]}, "CONFIG_CONSTANT_INVALID")
    catalog = _exact(item["catalog"], ("request_count", "selected_model_token", "selected_model_occurrences", "entitlement_confirmed", "observed_at", "raw_ref", "parser_ref"), "CATALOG_INVALID")
    require(catalog["request_count"] == 1 and catalog["selected_model_token"] == MODEL and catalog["selected_model_occurrences"] == 1 and catalog["entitlement_confirmed"] is True and catalog["raw_ref"] == held["catalog"] and catalog["parser_ref"] == held["catalog_parser"], "CATALOG_MEMBERSHIP_INVALID")
    prompt = _exact(item["prompt"], ("bytes", "sha256", "cutoff_sha256", "mutation", "artifact_ref", "operation_binding_sha256"), "PROMPT_INVALID")
    require(prompt == {"bytes": PROMPT_BYTES, "sha256": PROMPT_SHA256, "cutoff_sha256": CUTOFF_SHA256, "mutation": "forbidden", "artifact_ref": held["prompt"], "operation_binding_sha256": PROMPT_SHA256}, "PROMPT_BINDING_INVALID")
    require(held["prompt"]["bytes"] == PROMPT_BYTES and held["prompt"]["sha256"] == PROMPT_SHA256, "PROMPT_ARTIFACT_INVALID")
    budget = _exact(item["window_budget"], ("currency", "codex_subcap_usd", "combined_cap_usd", "prior_dual_provider_spend_usd", "remaining_combined_budget_usd", "not_before", "deadline"), "WINDOW_BUDGET_INVALID")
    require(budget["currency"] == "USD" and budget["codex_subcap_usd"] == 0.01 and budget["combined_cap_usd"] == 0.02, "BUDGET_CAP_INVALID")
    require(type(budget["prior_dual_provider_spend_usd"]) in (int, float) and 0 <= budget["prior_dual_provider_spend_usd"] <= 0.01, "PRIOR_SPEND_INVALID")
    require(type(budget["remaining_combined_budget_usd"]) in (int, float) and budget["remaining_combined_budget_usd"] >= 0.01 and budget["prior_dual_provider_spend_usd"] + budget["remaining_combined_budget_usd"] <= 0.02, "REMAINING_BUDGET_INVALID")
    start, end = _instant(budget["not_before"], "WINDOW_START_INVALID"), _instant(budget["deadline"], "WINDOW_END_INVALID")
    require(end - start == timedelta(minutes=30), "WINDOW_NOT_EXACT_30_MINUTES")
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    require(start <= instant <= end, "WINDOW_NOT_CURRENT")
    observed = _instant(catalog["observed_at"], "CATALOG_TIME_INVALID")
    require(start <= observed <= instant, "CATALOG_STALE_OR_FUTURE")
    engine = _exact(item["engine"], ("generated_by", "execution_id", "job_id", "slot_id", "attempt_id", "operation_id", "request_id", "request_fingerprint", "prompt_binding_sha256", "atomic_counts"), "ENGINE_INVALID")
    require(engine["generated_by"] == "shared.job_runtime.engine" and engine["prompt_binding_sha256"] == PROMPT_SHA256, "ENGINE_AUTHORITY_INVALID")
    ids = [engine[name] for name in ("execution_id", "job_id", "slot_id", "attempt_id", "operation_id", "request_id")]
    for value_id in ids: _safe(value_id, _ID, "ENGINE_ID_INVALID")
    require(len(set(ids)) == len(ids), "ENGINE_IDS_NOT_FRESH")
    fingerprint = _digest(engine["request_fingerprint"], "REQUEST_FINGERPRINT_INVALID")
    require(engine["atomic_counts"] == {"job": 1, "slot": 1, "attempt": 1, "operation": 1, "provider_result": 1}, "ENGINE_COUNTS_INVALID")
    gateway = _exact(item["gateway"], ("gateway_id", "provider_process_start_identity", "admission_key", "request_fingerprint", "admission_count", "dispatch_count", "upstream_attempt_count", "inference_count", "terminal_presence", "status_calls", "reconciliation_dispatch"), "GATEWAY_INVALID")
    _safe(gateway["gateway_id"], _ID, "GATEWAY_ID_INVALID"); _safe(gateway["provider_process_start_identity"], _ID, "PROCESS_IDENTITY_INVALID")
    require(gateway["request_fingerprint"] == fingerprint and gateway["admission_key"] == sha256_bytes((engine["operation_id"] + fingerprint).encode("utf-8")), "ADMISSION_BINDING_INVALID")
    require((gateway["admission_count"], gateway["dispatch_count"], gateway["upstream_attempt_count"], gateway["inference_count"], gateway["status_calls"], gateway["reconciliation_dispatch"]) == (1, 1, 1, 1, 0, 0) and gateway["terminal_presence"] is True, "GATEWAY_COUNTS_INVALID")
    argv_artifact = _load_json_artifact(held["argv"], root, "HELD_ARGV")
    require(argv_artifact == {
        "version": 1, "binary_realpath": BINARY_REALPATH,
        "argv": CANONICAL_ARGV, "model": MODEL, "effort": EFFORT,
        "request_id": engine["request_id"], "operation_id": engine["operation_id"],
        "stdin": {"transport": "stdin_exact_bytes", "bytes": PROMPT_BYTES,
                  "sha256": PROMPT_SHA256, "occurrences": 1},
    }, "HELD_ARGV_CONTENT_INVALID")
    config_artifact = _load_json_artifact(held["config"], root, "HELD_CONFIG")
    require(config_artifact == {
        "version": 1, "provider": PROVIDER, "release": RELEASE,
        "configured_model": MODEL, "effort": EFFORT,
        "request_retries": 0, "stream_retries": 0, "max_attempts": 1,
        "concurrency": 1, "countable_observation": False,
        "request_id": engine["request_id"],
    }, "HELD_CONFIG_CONTENT_INVALID")
    raw_catalog = _load_json_artifact(held["catalog"], root, "HELD_CATALOG")
    raw_catalog = _exact(raw_catalog, ("version", "request_id", "observed_at", "models"), "HELD_CATALOG_KEYS_INVALID")
    require(raw_catalog["version"] == 1 and raw_catalog["request_id"] == engine["request_id"] and raw_catalog["observed_at"] == catalog["observed_at"], "HELD_CATALOG_BINDING_INVALID")
    require(type(raw_catalog["models"]) is list and len(raw_catalog["models"]) > 0, "HELD_CATALOG_MODELS_INVALID")
    target_rows = []
    seen_tokens = set()
    for row in raw_catalog["models"]:
        row = _exact(row, ("token", "entitled"), "HELD_CATALOG_MODEL_KEYS_INVALID")
        token = _safe(row["token"], _REF_TEXT, "HELD_CATALOG_MODEL_TOKEN_INVALID")
        require(type(row["entitled"]) is bool and token not in seen_tokens, "HELD_CATALOG_MODEL_INVALID")
        seen_tokens.add(token)
        if token == MODEL:
            target_rows.append(row)
    require(len(target_rows) == 1 and target_rows[0]["entitled"] is True, "HELD_CATALOG_MEMBERSHIP_INVALID")
    parser_artifact = _load_json_artifact(held["catalog_parser"], root, "HELD_PARSER")
    parser_output = {"request_id": engine["request_id"], "selected_model_token": MODEL,
                     "selected_model_occurrences": 1, "model_entitled": True}
    require(parser_artifact == {
        "version": 1, "parser_id": CATALOG_PARSER_ID,
        "parser_source_sha256": CATALOG_PARSER_SOURCE_SHA256,
        "raw_catalog_sha256": held["catalog"]["sha256"],
        "request_id": engine["request_id"], "output": parser_output,
        "output_sha256": sha256_bytes(canonical_bytes(parser_output)),
    }, "HELD_PARSER_CONTENT_INVALID")
    process_receipt = _load_json_artifact(held["process_receipt"], root, "PROCESS_RECEIPT")
    require(process_receipt == {
        "process_start_identity": gateway["provider_process_start_identity"],
        "request_id": engine["request_id"], "operation_id": engine["operation_id"],
        "binary_sha256": BINARY_SHA256, "argv_sha256": held["argv"]["sha256"],
        "config_sha256": held["config"]["sha256"], "prompt_sha256": PROMPT_SHA256,
    }, "PROCESS_RECEIPT_BINDING_INVALID")
    gateway_receipt = _load_json_artifact(held["gateway_receipt"], root, "GATEWAY_RECEIPT")
    require(gateway_receipt == {
        "gateway_id": gateway["gateway_id"],
        "provider_process_start_identity": gateway["provider_process_start_identity"],
        "request_id": engine["request_id"], "operation_id": engine["operation_id"],
        "request_fingerprint": fingerprint, "admission_key": gateway["admission_key"],
        "prompt_sha256": PROMPT_SHA256,
    }, "GATEWAY_RECEIPT_BINDING_INVALID")
    custody = _exact(item["custody"], ("root_class", "mode", "owner_uid", "nofollow_components", "provider_separate", "credential_values_forbidden", "atomic_finalization"), "CUSTODY_INVALID")
    require(custody == {"root_class": ".job-runtime/live-provider-evidence/r6-one-off/codex_cli/<execution_id>", "mode": "0700", "owner_uid": 501, "nofollow_components": True, "provider_separate": True, "credential_values_forbidden": True, "atomic_finalization": True}, "CUSTODY_CONSTANT_INVALID")
    custody_receipt = _load_json_artifact(held["custody_receipt"], root, "CUSTODY_RECEIPT")
    custody_hashes = {name: held[name]["sha256"] for name in ("argv", "config", "catalog", "catalog_parser", "prompt", "process_receipt", "gateway_receipt")}
    require(custody_receipt == {"version": 1, "kind": "R6_CODEX_CUSTODY_RECEIPT", "execution_id": engine["execution_id"], "provider": PROVIDER, "root_class": custody["root_class"], "observed_owner_uid": custody["owner_uid"], "observed_mode": custody["mode"], "nofollow_components": True, "atomic_finalization": True, "credential_values_present": False, "held_artifact_sha256": custody_hashes}, "CUSTODY_RECEIPT_BINDING_INVALID")
    publication = _exact(item["publication_cleanup"], ("allowlist_only", "recursive_secret_scan", "stage_fsync_validate_atomic_no_overwrite", "raw_private", "process_reaped", "observer_closed", "descriptors_closed", "temporary_evidence_policy", "persistent_resources"), "PUBLICATION_CLEANUP_INVALID")
    require(publication == {"allowlist_only": True, "recursive_secret_scan": True, "stage_fsync_validate_atomic_no_overwrite": True, "raw_private": True, "process_reaped": True, "observer_closed": True, "descriptors_closed": True, "temporary_evidence_policy": "removed_or_owner_private_unknown", "persistent_resources": 0}, "PUBLICATION_CLEANUP_INCOMPLETE")
    publication_receipt = _load_json_artifact(held["publication_receipt"], root, "PUBLICATION_RECEIPT")
    require(publication_receipt == {"version": 1, "kind": "R6_CODEX_PUBLICATION_CLEANUP_RECEIPT", "execution_id": engine["execution_id"], "custody_receipt_sha256": held["custody_receipt"]["sha256"], "process_receipt_sha256": held["process_receipt"]["sha256"], "gateway_receipt_sha256": held["gateway_receipt"]["sha256"], "secret_scan": {"recursive": True, "passed": True, "matches": 0}, "publication": {"allowlist_only": True, "raw_included": False, "staged": True, "fsynced": True, "validated": True, "atomic_no_overwrite": True, "complete": True}, "cleanup": {"process_reaped": True, "observer_closed": True, "descriptors_closed": True, "temporary_evidence_policy": "removed_or_owner_private_unknown", "persistent_resources": 0}}, "PUBLICATION_RECEIPT_BINDING_INVALID")
    policy = _exact(item["terminal_policy"], ("exclusive", "pass_requires", "stop_requires", "unknown_durable", "unknown_retry", "unknown_replay", "unknown_status_calls", "unknown_reconciliation_dispatch", "countable_observation"), "TERMINAL_POLICY_INVALID")
    require(policy == {"exclusive": ["PASS", "STOP", "UNKNOWN"], "pass_requires": "exact_terminal_cleanup_and_publication", "stop_requires": "definitely_not_submitted_upstream_zero", "unknown_durable": True, "unknown_retry": False, "unknown_replay": False, "unknown_status_calls": 0, "unknown_reconciliation_dispatch": False, "countable_observation": False}, "TERMINAL_POLICY_CONSTANT_INVALID")
    dependencies = _exact(item["effect_dependencies"], EFFECTS, "EFFECT_DEPENDENCIES_INVALID")
    require(all(value == {"injected": True, "default": "DENY"} for value in dependencies.values()), "EFFECT_NOT_DENY_BY_DEFAULT")
    require(item["limits"] == LIMITS, "LIMITS_INVALID")
    _validate_provider_grant_pair(refs["codex_final_grant"], refs["codex_final_grant_review"], root, PROVIDER, item, instant)
    _validate_provider_grant_pair(refs["other_provider_final_grant"], refs["other_provider_final_grant_review"], root, "claude_cli", item, instant)
    return item
