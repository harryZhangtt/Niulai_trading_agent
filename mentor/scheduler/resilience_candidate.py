"""Pure builder for a disabled, finite scheduler-resilience candidate.

The builder performs structural validation and returns canonical in-memory JSON
only.  It never reads or writes files.  The current runtime adapter validates its
manifest/profile bindings but does *not* verify ``spec_sha256``; an integration
that materializes or activates this candidate must independently seal and record
that broader preflight identity.  Building a bundle is not activation evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Dict, Mapping, Tuple

from .contracts import canonical_json_bytes

UTC = timezone.utc
_ADAPTER = "mentor.scheduler.job_adapter:prepare"
_VERIFIER = "synthetic_bindings_v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_ADAPTER_KEYS = frozenset({
    "work_order_path", "state_directory", "owner_id",
    "candidate_manifest_path", "candidate_manifest_sha256",
    "required_source_paths", "expected_model_profile",
    "model_profile_sha256", "verifier_kind",
})
_WORK_ORDER_KEYS = frozenset({
    "schema_version", "work_order_id", "logical_session", "plan",
    "acceptance", "execution", "supervision", "evidence_policy", "completion",
})
_JOB_KEYS = frozenset({
    "id", "enabled", "schedule", "replay_safe", "model_profile",
    "prompt_file", "adapter", "adapter_config",
})
_DOCUMENT_NAMES = (
    "work-order.json", "allocation.json", "candidate-manifest.json",
)


class CandidateValidationError(ValueError):
    """Fixed-code, path-free candidate validation failure."""


class _FrozenDict(dict):
    """JSON-compatible dict whose ordinary mutation operations are disabled."""

    @staticmethod
    def _immutable(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise TypeError("CANDIDATE_BUNDLE_IMMUTABLE")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict((key, _freeze(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _fail(code: str) -> None:
    raise CandidateValidationError(code)


def _exact(value: Any, keys: frozenset, code: str = "CANDIDATE_BUNDLE_INVALID") -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or frozenset(value.keys()) != keys:
        _fail(code)
    return value


def _strict_int(value: Any, minimum: int, maximum: int, code: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(code)
    return value


def _identifier(value: Any, *, job: bool = False) -> str:
    pattern = _JOB_ID if job else _ID
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _fail("CANDIDATE_ID_INVALID")
    return value


def _digest(value: Any) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail("CANDIDATE_HASH_INVALID")
    return value


def _parts(value: Any, *, private: bool = False, public: bool = False) -> Tuple[str, ...]:
    if not isinstance(value, str) or not value or len(value) > 1024 or "\\" in value:
        _fail("CANDIDATE_PATH_INVALID")
    pure = PurePosixPath(value)
    parts = pure.parts
    if pure.is_absolute() or not parts or any(part in ("", ".", "..") for part in parts):
        _fail("CANDIDATE_PATH_INVALID")
    approved_private = len(parts) >= 3 and parts[:2] == (".job-runtime", "acceptance")
    if private and not approved_private:
        _fail("CANDIDATE_PATH_INVALID")
    if public and (approved_private or any(part.startswith(".") for part in parts)):
        _fail("CANDIDATE_PATH_INVALID")
    if any(part.startswith(".") for part in parts) and not approved_private:
        _fail("CANDIDATE_PATH_INVALID")
    if approved_private and any(part.startswith(".") for part in parts[2:]):
        _fail("CANDIDATE_PATH_INVALID")
    return tuple(parts)


def _utc(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _fail("CANDIDATE_TIME_INVALID")
    try:
        if value.utcoffset() != timedelta(0):
            _fail("CANDIDATE_TIME_INVALID")
        return value.astimezone(UTC)
    except (OverflowError, ValueError, TypeError):
        _fail("CANDIDATE_TIME_INVALID")
    raise AssertionError("unreachable")


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, repr=False)
class CandidateSource:
    """One caller-supplied, workspace-relative source binding."""

    path: str
    sha256: str

    def __repr__(self) -> str:
        return "CandidateSource(<redacted>)"


@dataclass(frozen=True, repr=False)
class CandidateInputs:
    """Complete pure inputs for one disabled two-slot candidate."""

    work_order_id: str
    logical_session_id: str
    job_id: str
    owner_id: str
    work_order_path: str
    state_directory: str
    candidate_manifest_path: str
    plan_path: str
    plan_sha256: str
    acceptance_path: str
    acceptance_sha256: str
    sources: Tuple[CandidateSource, ...]
    expected_model_profile: str
    model_profile_sha256: str
    prompt_file: str
    slot_1: datetime
    slot_2: datetime
    starts_at: datetime
    ends_at: datetime
    turn_timeout_seconds: int
    grace_seconds: int
    forbidden_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.sources, (list, tuple)):
            object.__setattr__(self, "sources", tuple(self.sources))
        if isinstance(self.forbidden_ids, (list, tuple, frozenset)):
            object.__setattr__(self, "forbidden_ids", tuple(self.forbidden_ids))

    def __repr__(self) -> str:
        return "CandidateInputs(<redacted>)"


@dataclass(frozen=True, repr=False)
class ResilienceCandidateBundle:
    """Immutable JSON bodies and their broader canonical preflight identity."""

    work_order: Mapping[str, Any]
    allocation: Mapping[str, Any]
    candidate_manifest: Mapping[str, Any]
    spec_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "work_order", _freeze(self.work_order))
        object.__setattr__(self, "allocation", _freeze(self.allocation))
        object.__setattr__(self, "candidate_manifest", _freeze(self.candidate_manifest))

    def __repr__(self) -> str:
        return "ResilienceCandidateBundle(<redacted>)"

    def to_json_documents(self) -> Dict[str, bytes]:
        """Return canonical JSON documents by logical filename; perform no I/O."""

        validate_candidate_bundle(self)
        return {
            _DOCUMENT_NAMES[0]: canonical_json_bytes(_plain(self.work_order)),
            _DOCUMENT_NAMES[1]: canonical_json_bytes(_plain(self.allocation)),
            _DOCUMENT_NAMES[2]: canonical_json_bytes(_plain(self.candidate_manifest)),
        }


def _validate_source(source: Any) -> CandidateSource:
    if not isinstance(source, CandidateSource):
        _fail("CANDIDATE_SOURCE_INVALID")
    _parts(source.path)
    _digest(source.sha256)
    return source


def _validate_inputs(inputs: Any) -> Tuple[datetime, datetime, datetime, datetime, Tuple[CandidateSource, ...]]:
    if not isinstance(inputs, CandidateInputs):
        _fail("CANDIDATE_INPUTS_INVALID")

    identifiers = (
        _identifier(inputs.work_order_id),
        _identifier(inputs.logical_session_id),
        _identifier(inputs.job_id, job=True),
        _identifier(inputs.owner_id),
    )
    if not inputs.work_order_id == inputs.logical_session_id == inputs.owner_id:
        _fail("CANDIDATE_IDENTITY_MISMATCH")
    if not isinstance(inputs.forbidden_ids, tuple):
        _fail("CANDIDATE_ID_INVALID")
    forbidden = tuple(inputs.forbidden_ids)
    for value in forbidden:
        _identifier(value)
    if len(forbidden) != len(set(forbidden)):
        _fail("CANDIDATE_ID_INVALID")
    if any(value in set(forbidden) for value in identifiers):
        _fail("CANDIDATE_ID_REUSED")

    work_parts = _parts(inputs.work_order_path, private=True)
    state_parts = _parts(inputs.state_directory, private=True)
    manifest_parts = _parts(inputs.candidate_manifest_path, private=True)
    if not inputs.work_order_path.endswith(".json") or manifest_parts[-1] != "candidate-manifest.json":
        _fail("CANDIDATE_PATH_INVALID")
    if len({inputs.work_order_path, inputs.state_directory, inputs.candidate_manifest_path}) != 3:
        _fail("CANDIDATE_PATH_INVALID")
    if work_parts == state_parts or manifest_parts == state_parts:
        _fail("CANDIDATE_PATH_INVALID")

    _parts(inputs.plan_path)
    _parts(inputs.acceptance_path)
    prompt_parts = _parts(inputs.prompt_file, public=True)
    if PurePosixPath(inputs.prompt_file).suffix not in (".md", ".txt"):
        _fail("CANDIDATE_PATH_INVALID")
    if any(part in ("runtime", "private") or part.endswith("-private") for part in prompt_parts):
        _fail("CANDIDATE_PATH_INVALID")

    _digest(inputs.plan_sha256)
    _digest(inputs.acceptance_sha256)
    _identifier(inputs.expected_model_profile)
    _digest(inputs.model_profile_sha256)

    if not isinstance(inputs.sources, tuple) or not 1 <= len(inputs.sources) <= 256:
        _fail("CANDIDATE_SOURCE_INVALID")
    sources = tuple(_validate_source(item) for item in inputs.sources)
    if len({item.path for item in sources}) != len(sources):
        _fail("CANDIDATE_SOURCE_INVALID")
    sources = tuple(sorted(sources, key=lambda item: item.path))

    starts = _utc(inputs.starts_at)
    ends = _utc(inputs.ends_at)
    slot_1 = _utc(inputs.slot_1)
    slot_2 = _utc(inputs.slot_2)
    if not starts < ends or ends - starts > timedelta(days=7):
        _fail("CANDIDATE_WINDOW_INVALID")
    if not starts < slot_1 < slot_2 < ends:
        _fail("CANDIDATE_TIME_INVALID")
    _strict_int(inputs.turn_timeout_seconds, 1, 86_400, "CANDIDATE_TIMEOUT_INVALID")
    grace = _strict_int(inputs.grace_seconds, 1, 10_800, "CANDIDATE_GRACE_INVALID")
    if timedelta(seconds=grace) > min(ends - slot_1, ends - slot_2):
        _fail("CANDIDATE_GRACE_INVALID")
    return starts, ends, slot_1, slot_2, sources


def _spec_digest(work_order: Mapping[str, Any], allocation: Mapping[str, Any],
                 manifest: Mapping[str, Any], profile_fingerprint: str) -> str:
    value = {
        "allocation": _plain(allocation),
        "candidate_manifest": _plain(manifest),
        "profile_fingerprint": profile_fingerprint,
        "work_order": _plain(work_order),
    }
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_resilience_candidate(inputs: CandidateInputs) -> ResilienceCandidateBundle:
    """Build one deterministic, disabled candidate without touching the filesystem."""

    starts, ends, slot_1, slot_2, sources = _validate_inputs(inputs)
    manifest = {
        "schema_version": 1,
        "sources": [
            {"path": item.path, "sha256": item.sha256}
            for item in sources
        ],
    }
    manifest_sha = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    work_order = {
        "schema_version": 1,
        "work_order_id": inputs.work_order_id,
        "logical_session": {
            "logical_session_id": inputs.logical_session_id,
            "provider_thread_mode": "ephemeral_threads",
            "max_provider_threads": 2,
        },
        "plan": {"path": inputs.plan_path, "sha256": inputs.plan_sha256},
        "acceptance": {"path": inputs.acceptance_path, "sha256": inputs.acceptance_sha256},
        "execution": {
            "starts_at": _timestamp(starts),
            "ends_at": _timestamp(ends),
            "turn_timeout_seconds": inputs.turn_timeout_seconds,
            "max_turns": 2,
        },
        "supervision": {
            "max_no_progress_cycles": 2,
            "max_repeated_actions": 2,
            "max_interventions": 0,
        },
        "evidence_policy": {
            "record_all_variants": True,
            "max_variants": 1,
            "max_reused_evaluations": 0,
            "worker_holdout_access": False,
        },
        "completion": {
            "required_event_kinds": ["provider_thread", "cycle"],
            "require_no_pending_effects": True,
            "require_acceptance_hash_match": True,
        },
    }
    options = {
        "work_order_path": inputs.work_order_path,
        "state_directory": inputs.state_directory,
        "owner_id": inputs.owner_id,
        "candidate_manifest_path": inputs.candidate_manifest_path,
        "candidate_manifest_sha256": manifest_sha,
        "required_source_paths": [item.path for item in sources],
        "expected_model_profile": inputs.expected_model_profile,
        "model_profile_sha256": inputs.model_profile_sha256,
        "verifier_kind": _VERIFIER,
    }
    allocation = {
        "schema_version": 1,
        "jobs": [{
            "id": inputs.job_id,
            "enabled": False,
            "schedule": {
                "kind": "sequence",
                "timestamps": [_timestamp(slot_1), _timestamp(slot_2)],
                "grace_seconds": inputs.grace_seconds,
            },
            "replay_safe": True,
            "model_profile": inputs.expected_model_profile,
            "prompt_file": inputs.prompt_file,
            "adapter": _ADAPTER,
            "adapter_config": options,
        }],
    }
    bundle = ResilienceCandidateBundle(
        work_order=work_order,
        allocation=allocation,
        candidate_manifest=manifest,
        spec_sha256=_spec_digest(
            work_order, allocation, manifest, inputs.model_profile_sha256
        ),
    )
    validate_candidate_bundle(bundle)
    return bundle


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        _fail("CANDIDATE_BUNDLE_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail("CANDIDATE_BUNDLE_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        _fail("CANDIDATE_BUNDLE_INVALID")
    return parsed.astimezone(UTC)


def validate_candidate_bundle(bundle: ResilienceCandidateBundle) -> None:
    """Fail closed on body/schema/binding drift; return ``None`` when valid."""

    if not isinstance(bundle, ResilienceCandidateBundle):
        _fail("CANDIDATE_BUNDLE_INVALID")
    if not isinstance(bundle.spec_sha256, str) or _SHA256.fullmatch(bundle.spec_sha256) is None:
        _fail("CANDIDATE_BUNDLE_INVALID")

    work = _exact(bundle.work_order, _WORK_ORDER_KEYS)
    if type(work["schema_version"]) is not int or work["schema_version"] != 1:
        _fail("CANDIDATE_BUNDLE_INVALID")
    _identifier(work["work_order_id"])
    logical = _exact(work["logical_session"], frozenset({
        "logical_session_id", "provider_thread_mode", "max_provider_threads",
    }))
    _identifier(logical["logical_session_id"])
    if (logical["provider_thread_mode"] != "ephemeral_threads"
            or type(logical["max_provider_threads"]) is not int
            or logical["max_provider_threads"] != 2):
        _fail("CANDIDATE_BUNDLE_INVALID")
    for name in ("plan", "acceptance"):
        binding = _exact(work[name], frozenset({"path", "sha256"}))
        _parts(binding["path"])
        _digest(binding["sha256"])
    execution = _exact(work["execution"], frozenset({
        "starts_at", "ends_at", "turn_timeout_seconds", "max_turns",
    }))
    starts = _parse_utc(execution["starts_at"])
    ends = _parse_utc(execution["ends_at"])
    if (not starts < ends or ends - starts > timedelta(days=7)
            or type(execution["max_turns"]) is not int or execution["max_turns"] != 2):
        _fail("CANDIDATE_BUNDLE_INVALID")
    _strict_int(execution["turn_timeout_seconds"], 1, 86_400, "CANDIDATE_BUNDLE_INVALID")
    supervision = _exact(work["supervision"], frozenset({
        "max_no_progress_cycles", "max_repeated_actions", "max_interventions",
    }))
    if (any(type(supervision[key]) is not int for key in supervision)
            or supervision != {
                "max_no_progress_cycles": 2,
                "max_repeated_actions": 2,
                "max_interventions": 0,
            }):
        _fail("CANDIDATE_BUNDLE_INVALID")
    evidence = _exact(work["evidence_policy"], frozenset({
        "record_all_variants", "max_variants", "max_reused_evaluations", "worker_holdout_access",
    }))
    if (evidence["record_all_variants"] is not True
            or type(evidence["max_variants"]) is not int
            or evidence["max_variants"] != 1
            or type(evidence["max_reused_evaluations"]) is not int
            or evidence["max_reused_evaluations"] != 0
            or evidence["worker_holdout_access"] is not False):
        _fail("CANDIDATE_BUNDLE_INVALID")
    completion = _exact(work["completion"], frozenset({
        "required_event_kinds", "require_no_pending_effects", "require_acceptance_hash_match",
    }))
    if (not isinstance(completion["required_event_kinds"], (list, tuple))
            or list(completion["required_event_kinds"]) != ["provider_thread", "cycle"]
            or completion["require_no_pending_effects"] is not True
            or completion["require_acceptance_hash_match"] is not True):
        _fail("CANDIDATE_BUNDLE_INVALID")

    manifest = _exact(bundle.candidate_manifest, frozenset({"schema_version", "sources"}))
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or not isinstance(manifest["sources"], (list, tuple))):
        _fail("CANDIDATE_BUNDLE_INVALID")
    if not 1 <= len(manifest["sources"]) <= 256:
        _fail("CANDIDATE_BUNDLE_INVALID")
    source_paths = []
    for source in manifest["sources"]:
        item = _exact(source, frozenset({"path", "sha256"}))
        _parts(item["path"])
        _digest(item["sha256"])
        source_paths.append(item["path"])
    if len(source_paths) != len(set(source_paths)) or source_paths != sorted(source_paths):
        _fail("CANDIDATE_BUNDLE_INVALID")

    allocation = _exact(bundle.allocation, frozenset({"schema_version", "jobs"}))
    if (type(allocation["schema_version"]) is not int or allocation["schema_version"] != 1
            or not isinstance(allocation["jobs"], (list, tuple))
            or len(allocation["jobs"]) != 1):
        _fail("CANDIDATE_BUNDLE_INVALID")
    job = _exact(allocation["jobs"][0], _JOB_KEYS)
    _identifier(job["id"], job=True)
    if job["enabled"] is not False or job["replay_safe"] is not True or job["adapter"] != _ADAPTER:
        _fail("CANDIDATE_BUNDLE_INVALID")
    _identifier(job["model_profile"])
    _parts(job["prompt_file"], public=True)
    if PurePosixPath(job["prompt_file"]).suffix not in (".md", ".txt"):
        _fail("CANDIDATE_BUNDLE_INVALID")
    schedule = _exact(job["schedule"], frozenset({"kind", "timestamps", "grace_seconds"}))
    if schedule["kind"] != "sequence" or not isinstance(schedule["timestamps"], (list, tuple)) or len(schedule["timestamps"]) != 2:
        _fail("CANDIDATE_BUNDLE_INVALID")
    slots = tuple(_parse_utc(value) for value in schedule["timestamps"])
    if not starts < slots[0] < slots[1] < ends:
        _fail("CANDIDATE_BUNDLE_INVALID")
    grace = _strict_int(schedule["grace_seconds"], 1, 10_800, "CANDIDATE_BUNDLE_INVALID")
    if timedelta(seconds=grace) > min(ends - slots[0], ends - slots[1]):
        _fail("CANDIDATE_BUNDLE_INVALID")

    options = _exact(job["adapter_config"], _ADAPTER_KEYS)
    work_order_path = options["work_order_path"]
    state_directory = options["state_directory"]
    candidate_manifest_path = options["candidate_manifest_path"]
    _parts(work_order_path, private=True)
    _parts(state_directory, private=True)
    _parts(candidate_manifest_path, private=True)
    if len({work_order_path, state_directory, candidate_manifest_path}) != 3:
        _fail("CANDIDATE_BUNDLE_INVALID")
    if candidate_manifest_path.split("/")[-1] != "candidate-manifest.json":
        _fail("CANDIDATE_BUNDLE_INVALID")
    _identifier(options["owner_id"])
    if not work["work_order_id"] == logical["logical_session_id"] == options["owner_id"]:
        _fail("CANDIDATE_BUNDLE_INVALID")
    if options["verifier_kind"] != _VERIFIER or options["expected_model_profile"] != job["model_profile"]:
        _fail("CANDIDATE_BUNDLE_INVALID")
    _identifier(options["expected_model_profile"])
    profile_sha = _digest(options["model_profile_sha256"])
    manifest_sha = _digest(options["candidate_manifest_sha256"])
    required = options["required_source_paths"]
    if not isinstance(required, (list, tuple)) or list(required) != source_paths:
        _fail("CANDIDATE_BUNDLE_INVALID")
    if manifest_sha != hashlib.sha256(canonical_json_bytes(_plain(manifest))).hexdigest():
        _fail("CANDIDATE_BUNDLE_INVALID")

    expected_spec = _spec_digest(work, allocation, manifest, profile_sha)
    if bundle.spec_sha256 != expected_spec:
        _fail("CANDIDATE_SPEC_MISMATCH")
    return None


__all__ = [
    "CandidateInputs", "CandidateSource", "CandidateValidationError",
    "ResilienceCandidateBundle", "build_resilience_candidate",
    "validate_candidate_bundle",
]
