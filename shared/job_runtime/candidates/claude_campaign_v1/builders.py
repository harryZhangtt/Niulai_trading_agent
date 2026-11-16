"""Exact, inert builders for three schema-2 campaign review configurations."""
import copy
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import CampaignContractError

_CAMPAIGNS = {
    "R6": {"scenario": "nominal", "max_attempts": 1},
    "R7": {"scenario": "pre_forward_transient_restart", "max_attempts": 2},
    "R8": {"scenario": "post_forward_cut_unknown", "max_attempts": 1},
}
_RECONCILIATION = "claude_campaign_v1.named_unknown_reconciliation"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _fail(code: str) -> None:
    raise CampaignContractError(code)


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _private_config_path(value: Any, suffix: str, code: str) -> str:
    if (type(value) is not str or not value or "\\" in value or "\x00" in value
            or value.startswith("/") or value.endswith("/") or "//" in value):
        _fail(code)
    parts = value.split("/")
    if parts[:2] != [".job-runtime", "config"] or len(parts) < 3:
        _fail(code)
    if any(part in ("", ".", "..") for part in parts) or not value.endswith(suffix):
        _fail(code)
    leaf = parts[-1]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}" + re.escape(suffix), leaf):
        _fail(code)
    return value


def _campaign(name: str) -> Mapping[str, Any]:
    if name not in _CAMPAIGNS:
        _fail("CAMPAIGN_NAME_INVALID")
    return _CAMPAIGNS[name]


def build_replay_contract(name: str) -> Mapping[str, Any]:
    _campaign(name)
    # R6/R7 may repeat only before forwarding. R8 has no automatic replay and
    # requires a named reconciliation authority for its unknown outcome.
    return _freeze({
        "version": 1,
        "effect": "reconcile_before_replay",
        "automatic_phases": ["connecting"] if name == "R7" else [],
        "slot_operation_scope": "claude-campaign-v1/%s/slot-operation" % name.lower(),
        "reconciliation_adapter": _RECONCILIATION,
    })


def build_job(name: str, slot: str, prompt_file: str, model_profile: str = "campaign") -> Mapping[str, Any]:
    campaign = _campaign(name)
    if type(slot) is not str or not re.fullmatch(r"slot-[12]", slot):
        _fail("SLOT_INVALID")
    if type(prompt_file) is not str or not (prompt_file.endswith(".md") or prompt_file.endswith(".txt")):
        _fail("PROMPT_CUSTODY_PATH_INVALID")
    _private_config_path(prompt_file, ".md" if prompt_file.endswith(".md") else ".txt",
                         "PROMPT_CUSTODY_PATH_INVALID")
    if type(model_profile) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model_profile):
        _fail("MODEL_PROFILE_INVALID")
    return _freeze({
        "id": "claude-campaign-v1.%s.%s" % (name.lower(), slot),
        "enabled": False,
        "schedule": {"kind": "once", "at": "2099-01-01T00:00:00+00:00", "grace_seconds": 300},
        "model_profile": model_profile,
        "prompt_file": prompt_file,
        "replay_contract": dict(build_replay_contract(name)),
    })


def validate_schema2_profile(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate schema-2 profile values without filesystem or runtime access.

    Path fields are type-checked only; canonical runtime retains workspace,
    existence, ownership, permission, and executable authority.
    """
    if type(profile) is not dict or profile.get("provider") not in ("claude_host", "codex_cli"):
        _fail("PROFILE_INVALID")
    provider = profile["provider"]
    common = {"provider", "model", "effort", "timeout_seconds", "auth_home"}
    required = common | ({"codex_bin"} if provider == "codex_cli" else set())
    optional = ({"max_output_bytes", "strict_process_tree_containment", "circuit"}
                if provider == "codex_cli" else {"max_budget_usd", "circuit"})
    if not required <= set(profile) or not set(profile) <= required | optional:
        _fail("PROFILE_KEYS_INVALID")
    if type(profile["model"]) is not str or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", profile["model"]) is None:
        _fail("PROFILE_MODEL_INVALID")
    if type(profile["auth_home"]) is not str or not profile["auth_home"]:
        _fail("PROFILE_AUTH_HOME_INVALID")
    timeout = profile["timeout_seconds"]
    if type(timeout) not in (int, float) or not 0 < timeout <= 3600:
        _fail("PROFILE_TIMEOUT_INVALID")
    if provider == "claude_host":
        budget = profile.get("max_budget_usd", 1.0)
        if profile["effort"] not in ("low", "medium", "high") or type(budget) not in (int, float) or not 0 < budget <= 100:
            _fail("PROFILE_CLAUDE_OPTIONS_INVALID")
    else:
        if type(profile["codex_bin"]) is not str or not profile["codex_bin"].startswith("/"):
            _fail("PROFILE_CODEX_BIN_INVALID")
        if profile["effort"] not in ("minimal", "low", "medium", "high", "xhigh", "max", "ultra"):
            _fail("PROFILE_CODEX_OPTIONS_INVALID")
        maximum = profile.get("max_output_bytes", 8 * 1024 * 1024)
        if type(maximum) is not int or not 1024 <= maximum <= 64 * 1024 * 1024:
            _fail("PROFILE_OUTPUT_LIMIT_INVALID")
        if type(profile.get("strict_process_tree_containment", False)) is not bool:
            _fail("PROFILE_PROCESS_CONTAINMENT_INVALID")
    circuit = profile.get("circuit", {"failure_threshold": 3, "open_seconds": 60,
                                      "probe_seconds": 10})
    if type(circuit) is not dict or set(circuit) != {"failure_threshold", "open_seconds", "probe_seconds"}:
        _fail("PROFILE_CIRCUIT_INVALID")
    if type(circuit["failure_threshold"]) is not int or not 1 <= circuit["failure_threshold"] <= 100:
        _fail("PROFILE_CIRCUIT_INVALID")
    if type(circuit["open_seconds"]) not in (int, float) or not 0 < circuit["open_seconds"] <= 86400 * 30:
        _fail("PROFILE_CIRCUIT_INVALID")
    if type(circuit["probe_seconds"]) not in (int, float) or not 0 < circuit["probe_seconds"] <= 3600:
        _fail("PROFILE_CIRCUIT_INVALID")
    return _freeze(copy.deepcopy(profile))


def build_schema2_config(name: str, profile: Mapping[str, Any], allocation_file: str) -> Mapping[str, Any]:
    campaign = _campaign(name)
    checked_profile = validate_schema2_profile(profile)
    _private_config_path(allocation_file, ".json", "ALLOCATION_PATH_INVALID")
    return _freeze({
        "schema_version": 2,
        "tick_seconds": 5,
        "heartbeat_seconds": 5,
        "stale_seconds": 30,
        "max_workers": 1,
        "retry": {
            "version": 2,
            "max_attempts": campaign["max_attempts"],
            "base_delay_seconds": 30.0,
            "max_delay_seconds": 30.0,
            "deadline_seconds": 300.0,
            "jitter": "sha256-full-jitter-v1",
        },
        "model_profiles": {"campaign": dict(checked_profile)},
        "allocation_files": [allocation_file],
        "source_paths": [],
    })


def build_campaign_manifest(name: str, prompt_sha256: str, source_sha256: str,
                            config_sha256: str) -> Mapping[str, Any]:
    campaign = _campaign(name)
    if any(type(value) is not str or _SHA.fullmatch(value) is None
           for value in (prompt_sha256, source_sha256, config_sha256)):
        _fail("MANIFEST_HASH_INVALID")
    value = {
        "schema_version": "claude-campaign-v1",
        "scope": {"kind": "candidate_local", "canonical_integration": False},
        "campaign_id": name,
        "scenario": campaign["scenario"],
        "enabled": False,
        "prompt_custody": {"schema_version": 2, "mode": "native_v1", "raw_prompt_forbidden": True},
        "execution": {"max_workers": 1, "max_attempts": campaign["max_attempts"]},
        "bindings": {"prompt_sha256": prompt_sha256, "source_sha256": source_sha256,
                     "config_sha256": config_sha256},
        "replay_contract": dict(build_replay_contract(name)),
        "unknown_fence": {"scope": "campaign", "blocked_slots": 2,
                          "reconciliation_adapter": _RECONCILIATION},
        "live": {"provider": False, "network": False, "process": False},
    }
    return _freeze(value)


def _validate_campaign_manifest(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate runtime manifest semantics with the same closed discriminants as its schema."""
    root = {"schema_version", "scope", "campaign_id", "scenario", "enabled",
            "prompt_custody", "execution", "bindings", "replay_contract",
            "unknown_fence", "live"}
    if type(value) is not dict or set(value) != root:
        _fail("MANIFEST_KEYS_INVALID")
    campaign = _campaign(value["campaign_id"])
    if (value["schema_version"] != "claude-campaign-v1" or type(value["enabled"]) is not bool
            or value["enabled"] is not False or value["scenario"] != campaign["scenario"]):
        _fail("MANIFEST_DISCRIMINANT_INVALID")
    expected = build_campaign_manifest(
        value["campaign_id"], value.get("bindings", {}).get("prompt_sha256"),
        value.get("bindings", {}).get("source_sha256"),
        value.get("bindings", {}).get("config_sha256"))
    def plain(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, tuple):
            return [plain(child) for child in item]
        return item
    def exact(left: Any, right: Any) -> bool:
        if type(left) is not type(right):
            return False
        if type(left) is dict:
            return set(left) == set(right) and all(exact(left[key], right[key]) for key in left)
        if type(left) is list:
            return len(left) == len(right) and all(exact(a, b) for a, b in zip(left, right))
        return left == right
    materialized = plain(value)
    if not exact(materialized, plain(expected)):
        _fail("MANIFEST_VALUE_INVALID")
    return _freeze(materialized)


def validate_campaign_manifest(value: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        return _validate_campaign_manifest(value)
    except CampaignContractError:
        raise
    except Exception:
        _fail("MANIFEST_INVALID")


def canonical_sha256(value: Mapping[str, Any]) -> str:
    def plain(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, tuple):
            return [plain(child) for child in item]
        return item
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()
