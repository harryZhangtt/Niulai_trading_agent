"""Pure deterministic disabled isolated-canary bundle builder."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping

from .canonical import canonical_json_bytes, canonical_sha256
from .frozen import freeze, plain


class BundleError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CanaryInputsV1:
    candidate_id: str
    candidate_version: int
    created_at: str
    slot_01_at: str
    slot_02_at: str
    prompt_source_name: str
    source_closure_sha256: str
    reserved_identity_set_sha256: str
    gmail_handoff_refs_sha256: str

    def __post_init__(self) -> None:
        string_fields = (self.candidate_id, self.created_at, self.slot_01_at, self.slot_02_at, self.prompt_source_name, self.source_closure_sha256, self.reserved_identity_set_sha256, self.gmail_handoff_refs_sha256)
        if type(self.candidate_version) is not int or any(type(value) is not str for value in string_fields):
            raise BundleError("CANARY_INPUT_INVALID")


@dataclass(frozen=True, slots=True)
class CanaryBundleV1:
    inputs: CanaryInputsV1
    config: Mapping[str, Any]
    allocation: Mapping[str, Any]
    lifecycle: Mapping[str, Any]
    monitor_contract: Mapping[str, Any]
    document_sha256: Mapping[str, str]
    bundle_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", freeze(self.config))
        object.__setattr__(self, "allocation", freeze(self.allocation))
        object.__setattr__(self, "lifecycle", freeze(self.lifecycle))
        object.__setattr__(self, "monitor_contract", freeze(self.monitor_contract))
        object.__setattr__(self, "document_sha256", freeze(self.document_sha256))


def _time(value: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise BundleError("CANARY_SCHEDULE_NOT_FUTURE")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise BundleError("CANARY_SCHEDULE_NOT_FUTURE") from None
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise BundleError("CANARY_SCHEDULE_NOT_FUTURE")
    return parsed.astimezone(timezone.utc)


def _sha(value: str) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _prompt_name(value: str) -> bool:
    return type(value) is str and re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value) is not None and "/" not in value and ".." not in value


def _documents(inputs: CanaryInputsV1) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    cid = inputs.candidate_id
    profile = cid + ".profile"
    prompt = ".job-runtime/config/isolated-canary-q1/" + inputs.prompt_source_name
    config = {"schema_version": 2, "tick_seconds": 1, "heartbeat_seconds": 1, "stale_seconds": 30, "max_workers": 1, "retry": {"version": 2, "max_attempts": 1, "base_delay_seconds": 1, "max_delay_seconds": 1, "deadline_seconds": 300, "jitter": "sha256-full-jitter-v1"}, "model_profiles": {profile: {"provider": "claude_host", "model": "synthetic-isolated-canary", "timeout_seconds": 30, "auth_home": "@workspace/.job-runtime/auth-homes/" + cid, "circuit": {"failure_threshold": 1, "open_seconds": 30, "probe_seconds": 5}}}, "allocation_files": [".job-runtime/config/jobs-v2.json"], "source_paths": []}
    jobs = []
    for ordinal, stamp in ((1, inputs.slot_01_at), (2, inputs.slot_02_at)):
        jobs.append({"id": f"{cid}.slot-0{ordinal}", "enabled": False, "schedule": {"kind": "once", "at": stamp, "grace_seconds": 300}, "model_profile": profile, "prompt_file": prompt, "replay_contract": {"version": 1, "effect": "none", "automatic_phases": ["not_started", "connecting"], "slot_operation_scope": f"{cid}/slot-0{ordinal}", "reconciliation_adapter": None}})
    allocation = {"schema_version": 2, "jobs": jobs}
    lifecycle = {"schema_version": 1, "candidate_id": cid, "profile_mode": "provider_free_synthetic", "limits": {"max_workers": 1, "max_processes": 1, "max_slots": 2, "max_claims_total": 2, "max_claims_per_slot": 1, "max_attempts_per_slot": 1, "max_replays": 0, "terminate_grace_seconds": 2, "kill_grace_seconds": 2, "slot_timeout_seconds": 30, "cleanup_timeout_seconds": 5}, "retention": {"minimum_days": 30, "unknown_until_reconciled": True, "cas_gc": "dry_run_only"}, "source_closure_sha256": inputs.source_closure_sha256, "reserved_identity_set_sha256": inputs.reserved_identity_set_sha256, "gmail_handoff_refs_sha256": inputs.gmail_handoff_refs_sha256, "prompt_source_name": inputs.prompt_source_name}
    monitor = {"schema_version": 1, "event_types": ["workspace_prepared", "bundle_verified", "database_created", "slot_claimed", "process_started", "process_terminated", "slot_terminal", "recovery_observed", "cleanup_started", "cleanup_terminal"], "slot_statuses": [None, "ready", "running", "succeeded", "failed", "unknown", "missed", "coalesced"], "forbidden_fields": ["path", "pid", "pgid", "label", "prompt", "credential", "recipient", "subject", "message_id", "stdout", "stderr", "exception"]}
    return config, allocation, lifecycle, monitor


def _bundle_digest(inputs: CanaryInputsV1, digests: Mapping[str, str]) -> str:
    return canonical_sha256({"candidate_id": inputs.candidate_id, "candidate_version": inputs.candidate_version, "created_at": inputs.created_at, "slot_01_at": inputs.slot_01_at, "slot_02_at": inputs.slot_02_at, "prompt_source_name": inputs.prompt_source_name, "source_closure_sha256": inputs.source_closure_sha256, "reserved_identity_set_sha256": inputs.reserved_identity_set_sha256, "gmail_handoff_refs_sha256": inputs.gmail_handoff_refs_sha256, "documents": dict(digests)})


def build_bundle(inputs: CanaryInputsV1) -> CanaryBundleV1:
    if type(inputs) is not CanaryInputsV1 or re.fullmatch(r"icq1-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{24}", inputs.candidate_id) is None:
        raise BundleError("CANARY_ID_INVALID")
    if type(inputs.candidate_version) is not int or inputs.candidate_version != 1 or not _prompt_name(inputs.prompt_source_name) or not all(_sha(x) for x in (inputs.source_closure_sha256, inputs.reserved_identity_set_sha256, inputs.gmail_handoff_refs_sha256)):
        raise BundleError("CANARY_INPUT_INVALID")
    created, one, two = _time(inputs.created_at), _time(inputs.slot_01_at), _time(inputs.slot_02_at)
    if not created < one < two or (one - created).total_seconds() < 120:
        raise BundleError("CANARY_SCHEDULE_NOT_FUTURE")
    config, allocation, lifecycle, monitor = _documents(inputs)
    digests = {"runtime-v2.json": canonical_sha256(config), "jobs-v2.json": canonical_sha256(allocation), "lifecycle-spec-v1.json": canonical_sha256(lifecycle), "monitor-contract-v1.json": canonical_sha256(monitor)}
    return CanaryBundleV1(inputs, config, allocation, lifecycle, monitor, digests, _bundle_digest(inputs, digests))


def validate_bundle(bundle: CanaryBundleV1) -> None:
    if type(bundle) is not CanaryBundleV1:
        raise BundleError("CANARY_SCHEMA_INVALID")
    config, allocation, lifecycle, monitor = _documents(bundle.inputs)
    actual = {"runtime-v2.json": canonical_sha256(config), "jobs-v2.json": canonical_sha256(allocation), "lifecycle-spec-v1.json": canonical_sha256(lifecycle), "monitor-contract-v1.json": canonical_sha256(monitor)}
    if plain(bundle.config) != config or plain(bundle.allocation) != allocation or plain(bundle.lifecycle) != lifecycle or plain(bundle.monitor_contract) != monitor or plain(bundle.document_sha256) != actual or bundle.bundle_sha256 != _bundle_digest(bundle.inputs, actual):
        raise BundleError("CANARY_BUNDLE_DIGEST_MISMATCH")
    if config["max_workers"] != 1 or len(allocation["jobs"]) != 2 or any(job["enabled"] is not False or job["replay_contract"]["effect"] != "none" for job in allocation["jobs"]):
        raise BundleError("CANARY_DISABLED_REQUIRED")


def render_documents(bundle: CanaryBundleV1) -> Mapping[str, bytes]:
    validate_bundle(bundle)
    return {"runtime-v2.json": canonical_json_bytes(plain(bundle.config)), "jobs-v2.json": canonical_json_bytes(plain(bundle.allocation)), "lifecycle-spec-v1.json": canonical_json_bytes(plain(bundle.lifecycle)), "monitor-contract-v1.json": canonical_json_bytes(plain(bundle.monitor_contract))}
