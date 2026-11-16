"""Strict, dependency-free contracts for bounded mentor work orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

SCHEMA_VERSION = 1
MAX_BOUND_FILE_BYTES = 1_048_576
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EVIDENCE_KINDS = {"provider_thread", "cycle", "effect_resolution", "intervention", "reused_evaluation"}


class ContractError(ValueError):
    """Raised when a work order or acceptance artifact is unsafe or malformed."""


def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_loads(text: str) -> Any:
    """Parse strict JSON, rejecting duplicate keys and non-finite numbers."""

    def reject_constant(value: str) -> None:
        raise ContractError(f"non-finite JSON number is forbidden: {value}")

    try:
        return json.loads(text, object_pairs_hook=_object_no_duplicates, parse_constant=reject_constant)
    except ContractError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise ContractError(f"invalid JSON: {exc}") from exc


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_bounded(path: Path, label: str) -> str:
    try:
        size = path.stat().st_size
        if size > MAX_BOUND_FILE_BYTES:
            raise ContractError(f"{label} exceeds {MAX_BOUND_FILE_BYTES} bytes")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"cannot read {label}: {exc}") from exc


def _exact_object(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    actual = set(value)
    if actual != keys:
        raise ContractError(f"{label} keys differ; missing={sorted(keys - actual)}, extra={sorted(actual - keys)}")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ContractError(f"{label} must be a bounded identifier")
    return value


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContractError(f"{label} must be an integer in [{minimum}, {maximum}]")
    return value


def _required_bool(value: Any, expected: bool, label: str) -> bool:
    if value is not expected:
        raise ContractError(f"{label} must be {str(expected).lower()}")
    return expected


def _aware_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"{label} must include a UTC offset")
    return parsed


def _workspace_file(workspace: Path, relative: Any, label: str) -> tuple[str, Path]:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ContractError(f"{label} must be a non-empty POSIX workspace-relative path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise ContractError(f"{label} must be normalized and workspace-relative")
    root = workspace.resolve(strict=True)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ContractError(f"{label} may not traverse a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise ContractError(f"{label} must name an existing file inside the workspace") from exc
    if not resolved.is_file():
        raise ContractError(f"{label} must name a regular file")
    return relative, resolved


@dataclass(frozen=True)
class BoundFile:
    path: str
    sha256: str


@dataclass(frozen=True)
class VerifiedProgressArtifact:
    path: str
    sha256: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CriterionObservation:
    criterion_id: str
    verdict: str
    evidence: tuple[BoundFile, ...]


@dataclass(frozen=True)
class VerifiedCriterionArtifact:
    path: str
    sha256: str
    verifier_id: str
    plan_sha256: str
    cycle_id: str
    candidate_id: str
    candidate_source: BoundFile
    observations: tuple[CriterionObservation, ...]


@dataclass(frozen=True)
class VerifiedEvaluationAssessment:
    path: str
    sha256: str
    evaluator_id: str
    plan_sha256: str
    cycle_id: str
    candidate_id: str
    candidate_source: BoundFile
    case_manifest: BoundFile
    candidate_cases: tuple[str, ...]
    baseline_cases: tuple[str, ...]
    usage_receipt: BoundFile
    candidate_budget: Mapping[str, int]
    baseline_budget: Mapping[str, int]
    ablation_receipt: BoundFile
    required_ablations: tuple[str, ...]
    observed_ablations: tuple[str, ...]
    holdout_receipt: BoundFile
    holdout_integrity: str
    holdout_evidence: tuple[BoundFile, ...]


@dataclass(frozen=True)
class VerifiedPolicyArtifact:
    path: str
    sha256: str
    evaluator_id: str
    plan_sha256: str
    cycle_id: str
    candidate_id: str
    candidate_source: BoundFile
    evaluation_assessment_sha256: str
    proposed_required_criteria: tuple[str, ...]
    reason_code: str


@dataclass(frozen=True)
class VerifiedCancellationArtifact:
    path: str
    sha256: str
    plan_sha256: str
    cycle_id: str
    candidate_id: str
    candidate_source: BoundFile
    slot_id: str
    attempt_id: str
    cancellation_event_id: str
    reason_code: str
    cancelled_at: datetime
    evidence: tuple[BoundFile, ...]


@dataclass(frozen=True)
class AcceptanceCriterion:
    criterion_id: str
    critical: bool


@dataclass(frozen=True)
class LogicalSessionSpec:
    logical_session_id: str
    provider_thread_mode: str
    max_provider_threads: int


@dataclass(frozen=True)
class ExecutionLimits:
    starts_at: datetime
    ends_at: datetime
    turn_timeout_seconds: int
    max_turns: int


@dataclass(frozen=True)
class SupervisionLimits:
    max_no_progress_cycles: int
    max_repeated_actions: int
    max_interventions: int


@dataclass(frozen=True)
class EvidencePolicy:
    record_all_variants: bool
    max_variants: int
    max_reused_evaluations: int
    worker_holdout_access: bool


@dataclass(frozen=True)
class CompletionRequirements:
    required_event_kinds: tuple[str, ...]
    require_no_pending_effects: bool
    require_acceptance_hash_match: bool


@dataclass(frozen=True)
class WorkOrder:
    """A validated work order bound to immutable plan and acceptance bytes."""

    work_order_id: str
    logical_session: LogicalSessionSpec
    plan: BoundFile
    acceptance: BoundFile
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    execution: ExecutionLimits
    supervision: SupervisionLimits
    evidence_policy: EvidencePolicy
    completion: CompletionRequirements
    workspace: Path

    @classmethod
    def from_json(cls, text: str, workspace: Path | str) -> "WorkOrder":
        data = _exact_object(strict_json_loads(text), {
            "schema_version", "work_order_id", "logical_session", "plan", "acceptance",
            "execution", "supervision", "evidence_policy", "completion",
        }, "work order")
        if data["schema_version"] != SCHEMA_VERSION:
            raise ContractError(f"schema_version must be {SCHEMA_VERSION}")
        root = Path(workspace).resolve(strict=True)

        logical = _exact_object(data["logical_session"], {
            "logical_session_id", "provider_thread_mode", "max_provider_threads",
        }, "logical_session")
        if logical["provider_thread_mode"] != "ephemeral_threads":
            raise ContractError("logical_session.provider_thread_mode must be ephemeral_threads")

        def bound_file(value: Any, label: str) -> tuple[BoundFile, Path]:
            item = _exact_object(value, {"path", "sha256"}, label)
            relative, absolute = _workspace_file(root, item["path"], f"{label}.path")
            claimed = item["sha256"]
            if not isinstance(claimed, str) or not _SHA256_RE.fullmatch(claimed):
                raise ContractError(f"{label}.sha256 must be a lowercase SHA-256 digest")
            _read_bounded(absolute, label)
            if sha256_file(absolute) != claimed:
                raise ContractError(f"{label} SHA-256 binding does not match current bytes")
            return BoundFile(relative, claimed), absolute

        plan, _ = bound_file(data["plan"], "plan")
        acceptance, acceptance_path = bound_file(data["acceptance"], "acceptance")
        acceptance_data = _exact_object(strict_json_loads(_read_bounded(acceptance_path, "acceptance")), {
            "schema_version", "criteria",
        }, "acceptance contract")
        if acceptance_data["schema_version"] != SCHEMA_VERSION:
            raise ContractError(f"acceptance contract schema_version must be {SCHEMA_VERSION}")
        raw_criteria = acceptance_data["criteria"]
        if not isinstance(raw_criteria, list) or not 1 <= len(raw_criteria) <= 128:
            raise ContractError("acceptance criteria must contain 1..128 entries")
        criteria: list[AcceptanceCriterion] = []
        for index, raw in enumerate(raw_criteria):
            criterion = _exact_object(raw, {"criterion_id", "critical"}, f"acceptance criterion {index}")
            if not isinstance(criterion["critical"], bool):
                raise ContractError("acceptance criterion critical must be boolean")
            criteria.append(AcceptanceCriterion(_identifier(criterion["criterion_id"], "criterion_id"), criterion["critical"]))
        if len({item.criterion_id for item in criteria}) != len(criteria):
            raise ContractError("acceptance criterion IDs must be unique")

        execution = _exact_object(data["execution"], {"starts_at", "ends_at", "turn_timeout_seconds", "max_turns"}, "execution")
        starts_at = _aware_timestamp(execution["starts_at"], "execution.starts_at")
        ends_at = _aware_timestamp(execution["ends_at"], "execution.ends_at")
        if ends_at <= starts_at or ends_at - starts_at > timedelta(days=7):
            raise ContractError("execution window must be positive and no longer than 7 days")

        supervision = _exact_object(data["supervision"], {
            "max_no_progress_cycles", "max_repeated_actions", "max_interventions",
        }, "supervision")
        evidence = _exact_object(data["evidence_policy"], {
            "record_all_variants", "max_variants", "max_reused_evaluations", "worker_holdout_access",
        }, "evidence_policy")
        completion = _exact_object(data["completion"], {
            "required_event_kinds", "require_no_pending_effects", "require_acceptance_hash_match",
        }, "completion")
        kinds = completion["required_event_kinds"]
        if not isinstance(kinds, list) or not 1 <= len(kinds) <= 16:
            raise ContractError("completion.required_event_kinds must contain 1..16 entries")
        normalized_kinds = tuple(_identifier(kind, "required event kind") for kind in kinds)
        if len(set(normalized_kinds)) != len(normalized_kinds) or not set(normalized_kinds) <= _EVIDENCE_KINDS:
            raise ContractError("completion.required_event_kinds must be unique supported evidence kinds")

        return cls(
            _identifier(data["work_order_id"], "work_order_id"),
            LogicalSessionSpec(
                _identifier(logical["logical_session_id"], "logical_session.logical_session_id"),
                "ephemeral_threads",
                _bounded_int(logical["max_provider_threads"], "logical_session.max_provider_threads", 1, 128),
            ),
            plan,
            acceptance,
            tuple(criteria),
            ExecutionLimits(starts_at, ends_at,
                _bounded_int(execution["turn_timeout_seconds"], "execution.turn_timeout_seconds", 1, 86_400),
                _bounded_int(execution["max_turns"], "execution.max_turns", 1, 10_000)),
            SupervisionLimits(
                _bounded_int(supervision["max_no_progress_cycles"], "supervision.max_no_progress_cycles", 0, 1_000),
                _bounded_int(supervision["max_repeated_actions"], "supervision.max_repeated_actions", 0, 1_000),
                _bounded_int(supervision["max_interventions"], "supervision.max_interventions", 0, 1_000)),
            EvidencePolicy(
                _required_bool(evidence["record_all_variants"], True, "evidence_policy.record_all_variants"),
                _bounded_int(evidence["max_variants"], "evidence_policy.max_variants", 1, 10_000),
                _bounded_int(evidence["max_reused_evaluations"], "evidence_policy.max_reused_evaluations", 0, 1_000),
                _required_bool(evidence["worker_holdout_access"], False, "evidence_policy.worker_holdout_access")),
            CompletionRequirements(normalized_kinds,
                _required_bool(completion["require_no_pending_effects"], True, "completion.require_no_pending_effects"),
                _required_bool(completion["require_acceptance_hash_match"], True, "completion.require_acceptance_hash_match")),
            root,
        )

    def verify_bindings(self) -> None:
        """Fail closed if frozen plan or acceptance bytes changed in place."""
        for label, bound in (("plan", self.plan), ("acceptance", self.acceptance)):
            _, absolute = _workspace_file(self.workspace, bound.path, f"{label}.path")
            _read_bounded(absolute, label)
            if sha256_file(absolute) != bound.sha256:
                raise ContractError(f"{label} binding drifted after work-order acceptance")

    def verify_progress_artifact(self, relative_path: str, cycle_id: str) -> VerifiedProgressArtifact:
        """Validate a cycle-bound progress artifact and every referenced evidence file."""
        cycle_id = _identifier(cycle_id, "cycle_id")
        relative, absolute = _workspace_file(self.workspace, relative_path, "verified_evidence_artifact.path")
        artifact = _exact_object(strict_json_loads(_read_bounded(absolute, "verified evidence artifact")), {
            "schema_version", "work_order_id", "plan_sha256", "acceptance_sha256", "cycle_id", "observations",
        }, "verified evidence artifact")
        if artifact["schema_version"] != SCHEMA_VERSION:
            raise ContractError(f"verified evidence artifact schema_version must be {SCHEMA_VERSION}")
        if (
            artifact["work_order_id"] != self.work_order_id
            or artifact["plan_sha256"] != self.plan.sha256
            or artifact["acceptance_sha256"] != self.acceptance.sha256
            or artifact["cycle_id"] != cycle_id
        ):
            raise ContractError("verified evidence artifact does not bind this work order and cycle")
        observations = artifact["observations"]
        if not isinstance(observations, list) or not 1 <= len(observations) <= 64:
            raise ContractError("verified evidence artifact must contain 1..64 observations")
        evidence_ids: list[str] = []
        for index, raw in enumerate(observations):
            observation = _exact_object(raw, {"evidence_id", "evidence_path", "sha256"}, f"progress observation {index}")
            evidence_id = _identifier(observation["evidence_id"], "evidence_id")
            evidence_path, evidence_absolute = _workspace_file(
                self.workspace, observation["evidence_path"], f"progress observation {index}.evidence_path"
            )
            del evidence_path
            try:
                size = evidence_absolute.stat().st_size
            except OSError as exc:
                raise ContractError("progress evidence file is unavailable") from exc
            if size > MAX_BOUND_FILE_BYTES:
                raise ContractError(f"progress evidence exceeds {MAX_BOUND_FILE_BYTES} bytes")
            claimed = observation["sha256"]
            if not isinstance(claimed, str) or not _SHA256_RE.fullmatch(claimed):
                raise ContractError("progress evidence sha256 must be a lowercase SHA-256 digest")
            if sha256_file(evidence_absolute) != claimed:
                raise ContractError("progress evidence SHA-256 binding does not match current bytes")
            evidence_ids.append(evidence_id)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ContractError("verified evidence observation IDs must be unique")
        return VerifiedProgressArtifact(relative, sha256_file(absolute), tuple(evidence_ids))

    def verify_criterion_observation_artifact(
        self, relative_path: str, *, cycle_id: str, candidate_id: str
    ) -> VerifiedCriterionArtifact:
        """Validate verifier-owned criterion observations and all evidence bytes.

        Cycle progress artifacts and worker output are deliberately not accepted by
        this contract.  Every frozen criterion must have exactly one verifier
        observation, and every observation must cite at least one immutable file.
        """
        cycle_id = _identifier(cycle_id, "cycle_id")
        candidate_id = _identifier(candidate_id, "candidate_id")
        relative, absolute = _workspace_file(self.workspace, relative_path, "criterion_artifact.path")
        artifact = _exact_object(strict_json_loads(_read_bounded(absolute, "criterion artifact")), {
            "schema_version", "artifact_kind", "producer_role", "verifier_id",
            "work_order_id", "plan_sha256", "acceptance_sha256", "cycle_id", "candidate_id",
            "candidate_source", "observations",
        }, "criterion artifact")
        if artifact["schema_version"] != SCHEMA_VERSION:
            raise ContractError(f"criterion artifact schema_version must be {SCHEMA_VERSION}")
        if artifact["artifact_kind"] != "criterion_observations" or artifact["producer_role"] != "verifier":
            raise ContractError("criterion artifact must be produced by the verifier boundary")
        verifier_id = _identifier(artifact["verifier_id"], "verifier_id")
        if (
            artifact["work_order_id"] != self.work_order_id
            or artifact["plan_sha256"] != self.plan.sha256
            or artifact["acceptance_sha256"] != self.acceptance.sha256
            or artifact["cycle_id"] != cycle_id
            or artifact["candidate_id"] != candidate_id
        ):
            raise ContractError(
                "criterion artifact does not bind this work order, plan, acceptance, cycle, and candidate"
            )
        source = _exact_object(artifact["candidate_source"], {"path", "sha256"}, "candidate_source")
        source_path, source_absolute = _workspace_file(
            self.workspace, source["path"], "candidate_source.path"
        )
        source_sha256 = source["sha256"]
        if not isinstance(source_sha256, str) or not _SHA256_RE.fullmatch(source_sha256):
            raise ContractError("candidate_source.sha256 must be a lowercase SHA-256 digest")
        _read_bounded(source_absolute, "candidate source")
        if sha256_file(source_absolute) != source_sha256:
            raise ContractError("candidate source SHA-256 binding does not match current bytes")
        raw_observations = artifact["observations"]
        if not isinstance(raw_observations, list) or len(raw_observations) != len(self.acceptance_criteria):
            raise ContractError("criterion artifact must contain one observation per frozen criterion")
        observations: list[CriterionObservation] = []
        seen_criteria: set[str] = set()
        seen_evidence: set[str] = set()
        for index, raw in enumerate(raw_observations):
            observation = _exact_object(raw, {"criterion_id", "verdict", "evidence"}, f"criterion observation {index}")
            criterion_id = _identifier(observation["criterion_id"], "criterion_id")
            if criterion_id in seen_criteria:
                raise ContractError("criterion observations may not duplicate a criterion")
            seen_criteria.add(criterion_id)
            verdict = observation["verdict"]
            if verdict not in {"satisfied", "violated", "inconclusive"}:
                raise ContractError("criterion observation verdict is invalid")
            raw_evidence = observation["evidence"]
            if not isinstance(raw_evidence, list) or not 1 <= len(raw_evidence) <= 64:
                raise ContractError("each criterion observation must bind 1..64 evidence files")
            evidence: list[BoundFile] = []
            for evidence_index, raw_file in enumerate(raw_evidence):
                item = _exact_object(raw_file, {"path", "sha256"}, f"criterion evidence {index}.{evidence_index}")
                evidence_path, evidence_absolute = _workspace_file(
                    self.workspace, item["path"], f"criterion evidence {index}.{evidence_index}.path"
                )
                claimed = item["sha256"]
                if not isinstance(claimed, str) or not _SHA256_RE.fullmatch(claimed):
                    raise ContractError("criterion evidence sha256 must be a lowercase SHA-256 digest")
                _read_bounded(evidence_absolute, "criterion evidence")
                if sha256_file(evidence_absolute) != claimed:
                    raise ContractError("criterion evidence SHA-256 binding does not match current bytes")
                if evidence_path in seen_evidence:
                    raise ContractError("criterion evidence files may not be duplicated")
                seen_evidence.add(evidence_path)
                evidence.append(BoundFile(evidence_path, claimed))
            observations.append(CriterionObservation(criterion_id, verdict, tuple(evidence)))
        expected = {item.criterion_id for item in self.acceptance_criteria}
        if seen_criteria != expected:
            raise ContractError("criterion observations do not exactly cover frozen criteria")
        return VerifiedCriterionArtifact(
            relative,
            sha256_file(absolute),
            verifier_id,
            self.plan.sha256,
            cycle_id,
            candidate_id,
            BoundFile(source_path, source_sha256),
            tuple(observations),
        )

    def _verified_bound_file(self, value: Any, label: str) -> tuple[BoundFile, Path]:
        item = _exact_object(value, {"path", "sha256"}, label)
        relative, absolute = _workspace_file(self.workspace, item["path"], f"{label}.path")
        claimed = item["sha256"]
        if not isinstance(claimed, str) or not _SHA256_RE.fullmatch(claimed):
            raise ContractError(f"{label}.sha256 must be a lowercase SHA-256 digest")
        _read_bounded(absolute, label)
        if sha256_file(absolute) != claimed:
            raise ContractError(f"{label} SHA-256 binding does not match current bytes")
        return BoundFile(relative, claimed), absolute

    def _receipt_identity(self, raw: Mapping[str, Any], *, kind: str, evaluator_id: str,
                          cycle_id: str, candidate_id: str, candidate_source: BoundFile) -> None:
        if raw["schema_version"] != SCHEMA_VERSION or raw["artifact_kind"] != kind or raw["producer_role"] != "evaluator":
            raise ContractError(f"{kind} must be evaluator-owned schema v1")
        if _identifier(raw["evaluator_id"], "evaluator_id") != evaluator_id:
            raise ContractError(f"{kind} evaluator identity drift")
        if (raw["work_order_id"], raw["plan_sha256"], raw["acceptance_sha256"], raw["cycle_id"], raw["candidate_id"]) != (
            self.work_order_id, self.plan.sha256, self.acceptance.sha256, cycle_id, candidate_id
        ):
            raise ContractError(f"{kind} binding drift")
        source, _ = self._verified_bound_file(raw["candidate_source"], f"{kind}.candidate_source")
        if source != candidate_source:
            raise ContractError(f"{kind} candidate source drift")

    def verify_evaluation_assessment_artifact(self, relative_path: str, *, cycle_id: str, candidate_id: str) -> VerifiedEvaluationAssessment:
        """Reopen evaluator receipts and derive comparison and holdout inputs."""
        cycle_id, candidate_id = _identifier(cycle_id, "cycle_id"), _identifier(candidate_id, "candidate_id")
        relative, absolute = _workspace_file(self.workspace, relative_path, "evaluation_assessment.path")
        raw = _exact_object(strict_json_loads(_read_bounded(absolute, "evaluation assessment")), {
            "schema_version", "artifact_kind", "producer_role", "evaluator_id", "work_order_id", "plan_sha256",
            "acceptance_sha256", "cycle_id", "candidate_id", "candidate_source", "case_manifest",
            "usage_receipt", "ablation_receipt", "holdout_receipt",
        }, "evaluation assessment")
        if raw["schema_version"] != SCHEMA_VERSION or raw["artifact_kind"] != "evaluation_assessment" or raw["producer_role"] != "evaluator":
            raise ContractError("evaluation assessment must be evaluator-owned schema v1")
        evaluator = _identifier(raw["evaluator_id"], "evaluator_id")
        if (raw["work_order_id"], raw["plan_sha256"], raw["acceptance_sha256"], raw["cycle_id"], raw["candidate_id"]) != (
            self.work_order_id, self.plan.sha256, self.acceptance.sha256, cycle_id, candidate_id
        ):
            raise ContractError("evaluation assessment binding drift")
        source, _ = self._verified_bound_file(raw["candidate_source"], "candidate_source")

        manifest_bound, manifest_path = self._verified_bound_file(raw["case_manifest"], "case_manifest")
        manifest = _exact_object(strict_json_loads(_read_bounded(manifest_path, "case manifest")), {
            "schema_version", "artifact_kind", "producer_role", "evaluator_id", "work_order_id", "plan_sha256",
            "acceptance_sha256", "cycle_id", "candidate_id", "candidate_source", "candidate_case_ids", "baseline_case_ids",
        }, "case manifest")
        self._receipt_identity(manifest, kind="case_manifest", evaluator_id=evaluator, cycle_id=cycle_id,
                               candidate_id=candidate_id, candidate_source=source)
        def ids(value: Any, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
            if not isinstance(value, list) or (not allow_empty and not value) or len(value) > 10000:
                raise ContractError(f"{label} is invalid")
            result = tuple(_identifier(item, label) for item in value)
            if len(result) != len(set(result)):
                raise ContractError(f"{label} contains duplicates")
            return result
        candidate_cases = ids(manifest["candidate_case_ids"], "candidate_case_id")
        baseline_cases = ids(manifest["baseline_case_ids"], "baseline_case_id")

        usage_bound, usage_path = self._verified_bound_file(raw["usage_receipt"], "usage_receipt")
        usage = _exact_object(strict_json_loads(_read_bounded(usage_path, "usage receipt")), {
            "schema_version", "artifact_kind", "producer_role", "evaluator_id", "work_order_id", "plan_sha256",
            "acceptance_sha256", "cycle_id", "candidate_id", "candidate_source", "candidate_budget", "baseline_budget",
        }, "usage receipt")
        self._receipt_identity(usage, kind="usage_receipt", evaluator_id=evaluator, cycle_id=cycle_id,
                               candidate_id=candidate_id, candidate_source=source)
        def budget(value: Any, label: str) -> Mapping[str, int]:
            if not isinstance(value, dict) or not value or len(value) > 64 or not all(
                isinstance(k, str) and k and isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10**9
                for k, v in value.items()
            ):
                raise ContractError(f"{label} is invalid")
            return dict(value)
        candidate_budget = budget(usage["candidate_budget"], "candidate_budget")
        baseline_budget = budget(usage["baseline_budget"], "baseline_budget")

        ablation_bound, ablation_path = self._verified_bound_file(raw["ablation_receipt"], "ablation_receipt")
        ablation = _exact_object(strict_json_loads(_read_bounded(ablation_path, "ablation receipt")), {
            "schema_version", "artifact_kind", "producer_role", "evaluator_id", "work_order_id", "plan_sha256",
            "acceptance_sha256", "cycle_id", "candidate_id", "candidate_source", "required_ablations", "observed_ablations",
        }, "ablation receipt")
        self._receipt_identity(ablation, kind="ablation_receipt", evaluator_id=evaluator, cycle_id=cycle_id,
                               candidate_id=candidate_id, candidate_source=source)
        required = ids(ablation["required_ablations"], "required_ablation", allow_empty=True)
        observed = ids(ablation["observed_ablations"], "observed_ablation", allow_empty=True)

        holdout_bound, holdout_path = self._verified_bound_file(raw["holdout_receipt"], "holdout_receipt")
        holdout = _exact_object(strict_json_loads(_read_bounded(holdout_path, "holdout receipt")), {
            "schema_version", "artifact_kind", "producer_role", "evaluator_id", "work_order_id", "plan_sha256",
            "acceptance_sha256", "cycle_id", "candidate_id", "candidate_source", "status", "evidence",
        }, "holdout receipt")
        self._receipt_identity(holdout, kind="holdout_receipt", evaluator_id=evaluator, cycle_id=cycle_id,
                               candidate_id=candidate_id, candidate_source=source)
        if holdout["status"] not in {"preserved", "violated", "unverified"}:
            raise ContractError("holdout receipt status is invalid")
        if not isinstance(holdout["evidence"], list) or not 1 <= len(holdout["evidence"]) <= 64:
            raise ContractError("holdout receipt evidence must contain 1..64 files")
        holdout_evidence = tuple(self._verified_bound_file(item, "holdout evidence")[0] for item in holdout["evidence"])
        if len({item.path for item in holdout_evidence}) != len(holdout_evidence):
            raise ContractError("holdout evidence files may not be duplicated")
        return VerifiedEvaluationAssessment(
            relative, sha256_file(absolute), evaluator, self.plan.sha256, cycle_id, candidate_id, source,
            manifest_bound, candidate_cases, baseline_cases, usage_bound, candidate_budget, baseline_budget,
            ablation_bound, required, observed, holdout_bound, holdout["status"], holdout_evidence,
        )

    def verify_policy_rejection_artifact(self, relative_path: str, *, cycle_id: str, candidate_id: str) -> VerifiedPolicyArtifact:
        """Validate evaluator policy evidence bound to one durable assessment."""
        cycle_id, candidate_id = _identifier(cycle_id, "cycle_id"), _identifier(candidate_id, "candidate_id")
        relative, absolute = _workspace_file(self.workspace, relative_path, "policy_artifact.path")
        raw = _exact_object(strict_json_loads(_read_bounded(absolute, "policy artifact")), {
            "schema_version", "artifact_kind", "producer_role", "evaluator_id", "work_order_id", "plan_sha256",
            "acceptance_sha256", "cycle_id", "candidate_id", "candidate_source", "evaluation_assessment_sha256",
            "proposed_required_criteria", "reason_code",
        }, "policy artifact")
        if raw["schema_version"] != SCHEMA_VERSION or raw["artifact_kind"] != "policy_rejection" or raw["producer_role"] != "evaluator":
            raise ContractError("policy artifact must be evaluator-owned policy_rejection schema v1")
        evaluator = _identifier(raw["evaluator_id"], "evaluator_id")
        if (raw["work_order_id"], raw["plan_sha256"], raw["acceptance_sha256"], raw["cycle_id"], raw["candidate_id"]) != (
            self.work_order_id, self.plan.sha256, self.acceptance.sha256, cycle_id, candidate_id
        ):
            raise ContractError("policy artifact binding drift")
        source, _ = self._verified_bound_file(raw["candidate_source"], "candidate_source")
        assessment_sha = raw["evaluation_assessment_sha256"]
        if not isinstance(assessment_sha, str) or not _SHA256_RE.fullmatch(assessment_sha):
            raise ContractError("evaluation_assessment_sha256 must be a lowercase SHA-256 digest")
        proposed_raw = raw["proposed_required_criteria"]
        if not isinstance(proposed_raw, list):
            raise ContractError("proposed_required_criteria must be a list")
        proposed = tuple(_identifier(x, "proposed criterion") for x in proposed_raw)
        if len(proposed) != len(set(proposed)):
            raise ContractError("proposed_required_criteria must contain unique identifiers")
        reason = raw["reason_code"]
        expected = {item.criterion_id for item in self.acceptance_criteria}
        if reason == "criterion_softening":
            if not expected - set(proposed):
                raise ContractError("softening rejection requires omitted frozen criteria")
        elif reason not in {"holdout_integrity_violation", "comparison_incomplete"}:
            raise ContractError("policy rejection reason_code is invalid")
        return VerifiedPolicyArtifact(relative, sha256_file(absolute), evaluator, self.plan.sha256, cycle_id,
            candidate_id, source, assessment_sha, proposed, reason)

    def verify_cancellation_artifact(self, relative_path: str, *, cycle_id: str, candidate_id: str,
                                     slot_id: str, attempt_id: str, cancellation_event_id: str) -> VerifiedCancellationArtifact:
        """Validate scheduler-owned cancellation evidence before durable recording."""
        cycle_id, candidate_id = _identifier(cycle_id, "cycle_id"), _identifier(candidate_id, "candidate_id")
        slot_id, attempt_id = _identifier(slot_id, "slot_id"), _identifier(attempt_id, "attempt_id")
        cancellation_event_id = _identifier(cancellation_event_id, "cancellation_event_id")
        relative, absolute = _workspace_file(self.workspace, relative_path, "cancellation_artifact.path")
        raw = _exact_object(strict_json_loads(_read_bounded(absolute, "cancellation artifact")), {
            "schema_version", "artifact_kind", "producer_role", "work_order_id", "plan_sha256", "acceptance_sha256",
            "candidate_id", "candidate_source", "cycle_id", "slot_id", "attempt_id", "cancellation_event_id",
            "reason_code", "cancelled_at", "evidence",
        }, "cancellation artifact")
        if raw["schema_version"] != SCHEMA_VERSION or raw["artifact_kind"] != "cancellation" or raw["producer_role"] != "scheduler":
            raise ContractError("cancellation artifact must be scheduler-owned schema v1")
        if (raw["work_order_id"], raw["plan_sha256"], raw["acceptance_sha256"], raw["cycle_id"], raw["candidate_id"],
            raw["slot_id"], raw["attempt_id"], raw["cancellation_event_id"]) != (
            self.work_order_id, self.plan.sha256, self.acceptance.sha256, cycle_id, candidate_id,
            slot_id, attempt_id, cancellation_event_id
        ):
            raise ContractError("cancellation artifact binding drift")
        source, _ = self._verified_bound_file(raw["candidate_source"], "candidate_source")
        reason = raw["reason_code"]
        if reason not in {"operator_cancelled", "deadline_exceeded", "safety_stop", "superseded", "budget_exhausted"}:
            raise ContractError("cancellation reason_code is invalid")
        cancelled_at = _aware_timestamp(raw["cancelled_at"], "cancelled_at")
        if not isinstance(raw["evidence"], list) or not 1 <= len(raw["evidence"]) <= 64:
            raise ContractError("cancellation evidence must contain 1..64 files")
        evidence = tuple(self._verified_bound_file(item, "cancellation evidence")[0] for item in raw["evidence"])
        if len({item.path for item in evidence}) != len(evidence):
            raise ContractError("cancellation evidence files may not be duplicated")
        return VerifiedCancellationArtifact(relative, sha256_file(absolute), self.plan.sha256, cycle_id, candidate_id,
            source, slot_id, attempt_id, cancellation_event_id, reason, cancelled_at, evidence)

    def verify_acceptance_artifact(self, relative_path: str) -> BoundFile:
        """Validate the legacy complete acceptance artifact.

        New terminal decisions should use ``verify_criterion_observation_artifact``;
        this parser remains for backward-compatible replay of existing ledgers.
        """
        relative, absolute = _workspace_file(self.workspace, relative_path, "verification_artifact.path")
        artifact = _exact_object(strict_json_loads(_read_bounded(absolute, "verification artifact")), {
            "schema_version", "work_order_id", "acceptance_sha256", "verdict", "observations",
        }, "verification artifact")
        if artifact["schema_version"] != SCHEMA_VERSION:
            raise ContractError(f"verification artifact schema_version must be {SCHEMA_VERSION}")
        if artifact["work_order_id"] != self.work_order_id or artifact["acceptance_sha256"] != self.acceptance.sha256:
            raise ContractError("verification artifact does not bind this work order and acceptance digest")
        if artifact["verdict"] != "accepted":
            raise ContractError("verification artifact verdict must be accepted")
        observations = artifact["observations"]
        if not isinstance(observations, list) or len(observations) != len(self.acceptance_criteria):
            raise ContractError("verification artifact must contain one observation per criterion")
        seen: dict[str, bool] = {}
        for index, raw in enumerate(observations):
            observation = _exact_object(raw, {"criterion_id", "satisfied"}, f"verification observation {index}")
            criterion_id = _identifier(observation["criterion_id"], "observation criterion_id")
            if criterion_id in seen or observation["satisfied"] is not True:
                raise ContractError("verification observations must be unique and satisfied=true")
            seen[criterion_id] = True
        expected = {item.criterion_id for item in self.acceptance_criteria}
        if set(seen) != expected:
            raise ContractError("verification observations do not exactly cover frozen criteria")
        return BoundFile(relative, sha256_file(absolute))
