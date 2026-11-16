"""Atomic, append-only state for durable logical mentor sessions."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any, Iterable

from .contracts import BoundFile, ContractError, WorkOrder, canonical_json_bytes, strict_json_loads
from .supervision import (
    ComparisonDesign, FrozenCriteria, PromotionDecision, PromotionVerdict, TrustedCancellation,
    TrustedEvaluatorAssessment, VerifierCriterionObservations,
    check_matched_comparison, _DURABLE_VERIFIER_PROOF,
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ENGINE_SLOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,255}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_STATES = {"completed", "rejected", "inconclusive_budget_exhausted", "expired", "cancelled"}
_EVENT_KINDS = {
    "provider_thread", "cycle", "effect_resolution", "intervention", "reused_evaluation",
    "criterion_observation", "evaluation_assessment", "policy_observation", "cancellation", "terminal", "completion",
}
_OUTCOMES = {"succeeded", "failed", "cancelled", "unknown"}
_EFFECT_STATES = {"none", "confirmed", "failed", "pending"}
_HEAD_KEYS = {
    "schema_version", "owner_id", "work_order_id", "logical_session_id", "plan_sha256",
    "acceptance_sha256", "created_at", "revision", "status", "turns_used",
    "provider_threads", "cycle_ids", "variants", "failed_attempts", "pending_effects",
    "verified_evidence_ids", "effect_resolutions", "interventions", "reused_evaluations", "consecutive_no_progress",
    "repeated_action_count", "last_action_sha256", "event_kinds", "last_event_hash",
    "verification_artifact", "criterion_observations", "evaluation_assessments", "policy_observations", "cancellations", "terminal_record", "updated_at",
}


class StateError(RuntimeError):
    """Raised when durable state is unsafe, inconsistent, or unauthorized."""


class _ReconciliationCapability:
    pass


_RECONCILIATION_CAPABILITY = _ReconciliationCapability()


class _VerifierCapability:
    pass


_VERIFIER_CAPABILITY = _VerifierCapability()


class _CancellationCapability:
    pass


_CANCELLATION_CAPABILITY = _CancellationCapability()


class _EvaluatorCapability:
    pass


_EVALUATOR_CAPABILITY = _EvaluatorCapability()


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise StateError(f"{label} must be a bounded identifier")
    return value


def _engine_slot_identifier(value: Any) -> str:
    if not isinstance(value, str) or not _ENGINE_SLOT_RE.fullmatch(value):
        raise StateError("engine_slot_id must be a bounded scheduler identifier")
    return value


def _aware(value: datetime | None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise StateError("timestamps must be timezone-aware")
    return value


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise StateError(f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StateError(f"{label} must be timezone-aware")
    return parsed


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise StateError(f"{label} contains missing or unknown keys")
    return value


def _safe_state_path(workspace: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise StateError("state path must be a POSIX workspace-relative path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise StateError("state path must be normalized and workspace-relative")
    root = workspace.resolve(strict=True)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise StateError("state path may not traverse a symlink")
    try:
        current.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise StateError("state path escapes the workspace") from exc
    return current


def _check_owned_private(path: Path) -> None:
    info = path.lstat()
    if info.st_uid != os.getuid():
        raise StateError(f"state path is not owned by the current OS user: {path}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise StateError(f"state path grants group/other permissions: {path}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ContractError) as exc:
        raise StateError(f"cannot read validated state file {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise StateError(f"state file {path.name} must contain an object")
    return value


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _exclusive_event(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(canonical_json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _event_hash(event: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(event)).hexdigest()


def _copy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


class DurableSessionStore:
    """Own one logical session's immutable ledger and atomically published head."""

    def __init__(self, workspace: Path | str, relative_directory: str, owner_id: str):
        self.workspace = Path(workspace).resolve(strict=True)
        self.directory = _safe_state_path(self.workspace, relative_directory)
        self.owner_id = _identifier(owner_id, "owner_id")
        self.events_directory = self.directory / "events"
        self.head_path = self.directory / "head.json"
        self.lock_path = self.directory / ".lock"

    def _initial_head(self, work_order: WorkOrder, created_at: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "owner_id": self.owner_id,
            "work_order_id": work_order.work_order_id,
            "logical_session_id": work_order.logical_session.logical_session_id,
            "plan_sha256": work_order.plan.sha256,
            "acceptance_sha256": work_order.acceptance.sha256,
            "created_at": created_at,
            "revision": 0,
            "status": "active",
            "turns_used": 0,
            "provider_threads": [],
            "cycle_ids": [],
            "variants": [],
            "failed_attempts": [],
            "pending_effects": [],
            "verified_evidence_ids": [],
            "effect_resolutions": [],
            "interventions": [],
            "reused_evaluations": [],
            "consecutive_no_progress": 0,
            "repeated_action_count": 0,
            "last_action_sha256": None,
            "event_kinds": [],
            "last_event_hash": None,
            "verification_artifact": None,
            "criterion_observations": [],
            "evaluation_assessments": [],
            "policy_observations": [],
            "cancellations": [],
            "terminal_record": None,
            "updated_at": created_at,
        }

    def create(self, work_order: WorkOrder, *, at: datetime | None = None) -> dict[str, Any]:
        if work_order.workspace != self.workspace:
            raise StateError("work order and state store must use the same workspace")
        work_order.verify_bindings()
        try:
            self.directory.mkdir(parents=True, mode=0o700)
        except FileExistsError as exc:
            raise StateError("session state already exists") from exc
        os.chmod(self.directory, 0o700)
        self.lock_path.touch(mode=0o600, exist_ok=False)
        os.chmod(self.lock_path, 0o600)
        with self._locked():
            self.events_directory.mkdir(mode=0o700)
            head = self._initial_head(work_order, _aware(at).isoformat())
            _atomic_write(self.head_path, head)
            return _copy(head)

    def load(self, work_order: WorkOrder) -> dict[str, Any]:
        with self._locked():
            return self._load_unlocked(work_order)

    def _load_unlocked(self, work_order: WorkOrder) -> dict[str, Any]:
        self._check_layout()
        work_order.verify_bindings()
        head = _read_json(self.head_path)
        self._validate_head_identity(head, work_order)
        # Schema-v1 heads written before cancellation records remain replayable,
        # but all new writes publish the explicit append-only collection.
        if "cancellations" not in head:
            head["cancellations"] = []
        events = self._event_paths()
        if len(events) != head["revision"]:
            raise StateError("ledger has missing or orphan events; explicit recovery is required")
        replayed = self._replay(work_order, head, events)
        if replayed != head:
            raise StateError("published head does not equal deterministic ledger state")
        return _copy(head)

    def recover_orphan(self, work_order: WorkOrder) -> dict[str, Any]:
        """Owner-authorized recovery of exactly one valid, fully written next event."""
        with self._locked():
            self._check_layout()
            work_order.verify_bindings()
            head = _read_json(self.head_path)
            self._validate_head_identity(head, work_order)
            if "cancellations" not in head:
                head["cancellations"] = []
            events = self._event_paths()
            if len(events) != head["revision"] + 1:
                raise StateError("recovery requires exactly one next orphan event")
            stable = self._replay(work_order, head, events[:-1])
            if stable != head:
                raise StateError("published prefix is inconsistent; recovery refused")
            recovered = self._reduce_event(work_order, stable, _read_json(events[-1]))
            _atomic_write(self.head_path, recovered)
            return _copy(recovered)

    def record_provider_thread(self, work_order: WorkOrder, *, provider: str, thread_id: str, at: datetime | None = None) -> dict[str, Any]:
        return self._append(work_order, "provider_thread", {
            "provider": _identifier(provider, "provider"),
            "thread_id": _identifier(thread_id, "thread_id"),
        }, at)

    def record_cycle(
        self, work_order: WorkOrder, *, cycle_id: str, variant_id: str,
        action_sha256: str, outcome: str, verified_evidence_artifact_path: str | None,
        effect_id: str | None = None, effect_status: str = "none",
        at: datetime | None = None,
    ) -> dict[str, Any]:
        cycle_id = _identifier(cycle_id, "cycle_id")
        if not isinstance(action_sha256, str) or not _SHA_RE.fullmatch(action_sha256):
            raise StateError("action_sha256 must be a lowercase SHA-256 digest")
        if outcome not in _OUTCOMES or effect_status not in _EFFECT_STATES:
            raise StateError("invalid cycle outcome or effect status")
        if verified_evidence_artifact_path is not None and not isinstance(verified_evidence_artifact_path, str):
            raise StateError("verified_evidence_artifact_path must be a string or None")
        if (effect_status == "pending") != (effect_id is not None):
            raise StateError("only pending effects require an effect_id")
        with self._locked():
            head = self._load_unlocked(work_order)
            artifact = (
                work_order.verify_progress_artifact(verified_evidence_artifact_path, cycle_id)
                if verified_evidence_artifact_path is not None else None
            )
            return self._append_loaded(work_order, head, "cycle", {
                "cycle_id": cycle_id,
                "variant_id": _identifier(variant_id, "variant_id"),
                "action_sha256": action_sha256,
                "outcome": outcome,
                "verified_evidence_artifact_path": artifact.path if artifact else None,
                "verified_evidence_artifact_sha256": artifact.sha256 if artifact else None,
                "verified_evidence_ids": list(artifact.evidence_ids) if artifact else [],
                "effect_id": _identifier(effect_id, "effect_id") if effect_id is not None else None,
                "effect_status": effect_status,
            }, at)

    def _resolve_effect_from_reconciliation(
        self, work_order: WorkOrder, *, reconciliation_id: str, engine_slot_id: str,
        engine_attempt_id: str, outcome: str, evidence_sha256: str,
        at: datetime | None = None, capability: object | None = None,
    ) -> dict[str, Any]:
        if capability is not _RECONCILIATION_CAPABILITY:
            raise StateError("effect reconciliation capability is required")
        data = {
            "reconciliation_id": _identifier(reconciliation_id, "reconciliation_id"),
            "engine_slot_id": _engine_slot_identifier(engine_slot_id),
            "engine_attempt_id": _identifier(engine_attempt_id, "engine_attempt_id"),
            "outcome": outcome,
            "evidence_sha256": evidence_sha256,
        }
        if outcome not in {"succeeded", "failed"}:
            raise StateError("reconciliation outcome must be succeeded or failed")
        if not isinstance(evidence_sha256, str) or not _SHA_RE.fullmatch(evidence_sha256):
            raise StateError("evidence_sha256 must be a lowercase SHA-256 digest")
        with self._locked():
            head = self._load_unlocked(work_order)
            for existing in head["effect_resolutions"]:
                same_identity = (
                    existing["reconciliation_id"] == data["reconciliation_id"]
                    or existing["engine_attempt_id"] == data["engine_attempt_id"]
                )
                if same_identity:
                    expected = {**data, "effect_state": "confirmed" if outcome == "succeeded" else "failed"}
                    if existing == expected:
                        return head
                    raise StateError("effect reconciliation conflicts with existing evidence")
            return self._append_loaded(work_order, head, "effect_resolution", data, at)

    def record_intervention(self, work_order: WorkOrder, *, intervention_id: str, reason_code: str, at: datetime | None = None) -> dict[str, Any]:
        intervention_id = _identifier(intervention_id, "intervention_id")
        reason_code = _identifier(reason_code, "reason_code")
        with self._locked():
            head = self._load_unlocked(work_order)
            for existing in head["interventions"]:
                if existing["intervention_id"] == intervention_id:
                    if existing["reason_code"] == reason_code:
                        return head
                    raise StateError("intervention identifier conflicts with existing evidence")
            return self._append_loaded(work_order, head, "intervention", {
                "intervention_id": intervention_id, "reason_code": reason_code,
            }, at)

    def record_reused_evaluation(self, work_order: WorkOrder, *, evaluation_id: str, source_cycle_id: str, at: datetime | None = None) -> dict[str, Any]:
        return self._append(work_order, "reused_evaluation", {
            "evaluation_id": _identifier(evaluation_id, "evaluation_id"),
            "source_cycle_id": _identifier(source_cycle_id, "source_cycle_id"),
        }, at)

    def _record_criterion_observation_from_verifier(
        self, work_order: WorkOrder, *, artifact_path: str, cycle_id: str, candidate_id: str,
        at: datetime | None = None, capability: object | None = None,
    ) -> dict[str, Any]:
        """Append a criterion artifact only through the verifier-owned boundary."""
        if capability is not _VERIFIER_CAPABILITY:
            raise StateError("verifier capability is required")
        with self._locked():
            head = self._load_unlocked(work_order)
            artifact = work_order.verify_criterion_observation_artifact(
                artifact_path, cycle_id=cycle_id, candidate_id=candidate_id
            )
            record = {
                "path": artifact.path,
                "sha256": artifact.sha256,
                "verifier_id": artifact.verifier_id,
                "plan_sha256": artifact.plan_sha256,
                "cycle_id": artifact.cycle_id,
                "candidate_id": artifact.candidate_id,
                "candidate_source": {
                    "path": artifact.candidate_source.path,
                    "sha256": artifact.candidate_source.sha256,
                },
                "observations": [
                    {
                        "criterion_id": item.criterion_id,
                        "verdict": item.verdict,
                        "evidence": [{"path": bound.path, "sha256": bound.sha256} for bound in item.evidence],
                    }
                    for item in artifact.observations
                ],
            }
            self._require_candidate_identity(head, cycle_id, candidate_id, record["candidate_source"])
            for existing in head["criterion_observations"]:
                same_identity = (
                    existing["cycle_id"] == cycle_id and existing["candidate_id"] == candidate_id
                )
                if same_identity:
                    if existing == record:
                        return head
                    raise StateError("criterion observation conflicts with existing verifier evidence")
                if existing["sha256"] == record["sha256"]:
                    raise StateError("criterion observation replay across identities is forbidden")
            return self._append_loaded(work_order, head, "criterion_observation", record, at)

    @staticmethod
    def _candidate_identity(head: dict[str, Any], cycle_id: str, candidate_id: str) -> dict[str, str] | None:
        records = head["criterion_observations"] + head["evaluation_assessments"] + head["policy_observations"] + head["cancellations"]
        matches = [item["candidate_source"] for item in records
                   if item["cycle_id"] == cycle_id and item["candidate_id"] == candidate_id]
        if not matches:
            return None
        if any(item != matches[0] for item in matches[1:]):
            raise StateError("durable candidate source identity is inconsistent")
        return matches[0]

    @classmethod
    def _require_candidate_identity(cls, head: dict[str, Any], cycle_id: str, candidate_id: str,
                                    candidate_source: dict[str, str]) -> None:
        existing = cls._candidate_identity(head, cycle_id, candidate_id)
        if existing is not None and existing != candidate_source:
            raise StateError("candidate source identity conflicts with durable evidence")

    @staticmethod
    def _evaluation_record(artifact: Any) -> dict[str, Any]:
        return {
            "path": artifact.path, "sha256": artifact.sha256, "evaluator_id": artifact.evaluator_id,
            "plan_sha256": artifact.plan_sha256, "cycle_id": artifact.cycle_id, "candidate_id": artifact.candidate_id,
            "candidate_source": {"path": artifact.candidate_source.path, "sha256": artifact.candidate_source.sha256},
            "case_manifest": {"path": artifact.case_manifest.path, "sha256": artifact.case_manifest.sha256},
            "candidate_cases": list(artifact.candidate_cases), "baseline_cases": list(artifact.baseline_cases),
            "usage_receipt": {"path": artifact.usage_receipt.path, "sha256": artifact.usage_receipt.sha256},
            "candidate_budget": dict(artifact.candidate_budget), "baseline_budget": dict(artifact.baseline_budget),
            "ablation_receipt": {"path": artifact.ablation_receipt.path, "sha256": artifact.ablation_receipt.sha256},
            "required_ablations": list(artifact.required_ablations), "observed_ablations": list(artifact.observed_ablations),
            "holdout_receipt": {"path": artifact.holdout_receipt.path, "sha256": artifact.holdout_receipt.sha256},
            "holdout_integrity": artifact.holdout_integrity,
            "holdout_evidence": [{"path": x.path, "sha256": x.sha256} for x in artifact.holdout_evidence],
        }

    def _record_evaluation_assessment_from_evaluator(self, work_order: WorkOrder, *, artifact_path: str,
            cycle_id: str, candidate_id: str, at: datetime | None = None,
            capability: object | None = None) -> dict[str, Any]:
        if capability is not _EVALUATOR_CAPABILITY:
            raise StateError("evaluator capability is required")
        with self._locked():
            head = self._load_unlocked(work_order)
            artifact = work_order.verify_evaluation_assessment_artifact(
                artifact_path, cycle_id=cycle_id, candidate_id=candidate_id)
            record = self._evaluation_record(artifact)
            self._require_candidate_identity(head, cycle_id, candidate_id, record["candidate_source"])
            for existing in head["evaluation_assessments"]:
                same_identity = existing["cycle_id"] == cycle_id and existing["candidate_id"] == candidate_id
                if same_identity:
                    if existing == record:
                        return head
                    raise StateError("evaluation assessment conflicts with durable evidence")
                if existing["sha256"] == record["sha256"]:
                    raise StateError("evaluation assessment replay across identities is forbidden")
            return self._append_loaded(work_order, head, "evaluation_assessment", record, at)

    def load_evaluator_assessment(self, work_order: WorkOrder, *, artifact_sha256: str,
                                  cycle_id: str, candidate_id: str) -> TrustedEvaluatorAssessment:
        if not isinstance(artifact_sha256, str) or not _SHA_RE.fullmatch(artifact_sha256):
            raise StateError("artifact_sha256 must be a lowercase SHA-256 digest")
        head = self.load(work_order)
        record = next((x for x in head["evaluation_assessments"] if x["sha256"] == artifact_sha256
                       and x["cycle_id"] == cycle_id and x["candidate_id"] == candidate_id), None)
        if record is None:
            raise StateError("durable evaluator assessment was not found")
        artifact = work_order.verify_evaluation_assessment_artifact(record["path"], cycle_id=cycle_id, candidate_id=candidate_id)
        if self._evaluation_record(artifact) != record:
            raise StateError("evaluation assessment receipt derivation drifted")
        comparison = check_matched_comparison(ComparisonDesign(
            candidate_cases=artifact.candidate_cases, baseline_cases=artifact.baseline_cases,
            candidate_budget=artifact.candidate_budget, baseline_budget=artifact.baseline_budget,
            required_ablations=frozenset(artifact.required_ablations), observed_ablations=frozenset(artifact.observed_ablations),
        ))
        holdout = {"preserved": True, "violated": False, "unverified": None}[artifact.holdout_integrity]
        return TrustedEvaluatorAssessment(
            artifact.sha256, artifact.evaluator_id, work_order.work_order_id, artifact.plan_sha256,
            work_order.acceptance.sha256, cycle_id, candidate_id, artifact.candidate_source.path,
            artifact.candidate_source.sha256, comparison, holdout, _DURABLE_VERIFIER_PROOF)

    def decide_verified_promotion(
        self, work_order: WorkOrder, *, criterion_artifact_sha256: str,
        evaluation_assessment_sha256: str, cycle_id: str, candidate_id: str,
        proposed_required_criteria: Iterable[str] | None = None,
    ) -> PromotionDecision:
        """Apply promotion semantics only after replaying both durable artifacts."""
        criteria = FrozenCriteria.from_work_order(work_order)
        verifier = self.load_verifier_observations(
            work_order, artifact_sha256=criterion_artifact_sha256,
            cycle_id=cycle_id, candidate_id=candidate_id,
        )
        evaluator = self.load_evaluator_assessment(
            work_order, artifact_sha256=evaluation_assessment_sha256,
            cycle_id=cycle_id, candidate_id=candidate_id,
        )
        if (
            verifier.work_order_id != work_order.work_order_id
            or verifier.plan_sha256 != work_order.plan.sha256
            or verifier.acceptance_sha256 != work_order.acceptance.sha256
            or evaluator.work_order_id != work_order.work_order_id
            or evaluator.plan_sha256 != work_order.plan.sha256
            or evaluator.acceptance_sha256 != work_order.acceptance.sha256
            or verifier.cycle_id != cycle_id or evaluator.cycle_id != cycle_id
            or verifier.candidate_id != candidate_id or evaluator.candidate_id != candidate_id
            or verifier.candidate_source_path != evaluator.candidate_source_path
            or verifier.candidate_source_sha256 != evaluator.candidate_source_sha256
        ):
            raise StateError("durable promotion evidence binding drift")
        observations = verifier.as_mapping(criteria)

        def decide_from_replayed_state() -> PromotionDecision:
            omitted = (
                frozenset() if proposed_required_criteria is None
                else criteria.required - frozenset(proposed_required_criteria)
            )
            failures = sorted(item for item in criteria.required if observations.get(item) is False)
            if omitted:
                return PromotionDecision(criteria.acceptance_sha256, PromotionVerdict.REJECTED,
                    ("attempted to soften frozen criteria: " + ", ".join(sorted(omitted)),),
                    "candidate rejected under the frozen gate")
            if evaluator.holdout_integrity is False:
                return PromotionDecision(criteria.acceptance_sha256, PromotionVerdict.REJECTED,
                    ("protected holdout integrity was violated",), "candidate rejected under the frozen gate")
            if failures:
                return PromotionDecision(criteria.acceptance_sha256, PromotionVerdict.REJECTED,
                    ("observed frozen-criterion violations: " + ", ".join(failures),),
                    "candidate rejected under the frozen gate")
            reasons = []
            missing = sorted(item for item in criteria.required if observations.get(item) is not True)
            if missing:
                reasons.append("missing criterion evidence: " + ", ".join(missing))
            if not evaluator.comparison.complete:
                reasons.extend(evaluator.comparison.issues)
            if evaluator.holdout_integrity is None:
                reasons.append("holdout integrity is unverified")
            if reasons:
                return PromotionDecision(criteria.acceptance_sha256, PromotionVerdict.INCONCLUSIVE,
                    tuple(reasons), "no promotion decision is supported")
            return PromotionDecision(criteria.acceptance_sha256, PromotionVerdict.ACCEPTED,
                ("all frozen criteria and protection checks passed",),
                "promotion is supported only for the evaluated scope")

        return decide_from_replayed_state()

    @staticmethod
    def _policy_record(artifact: Any) -> dict[str, Any]:
        return {
            "path": artifact.path, "sha256": artifact.sha256, "evaluator_id": artifact.evaluator_id,
            "plan_sha256": artifact.plan_sha256, "cycle_id": artifact.cycle_id, "candidate_id": artifact.candidate_id,
            "candidate_source": {"path": artifact.candidate_source.path, "sha256": artifact.candidate_source.sha256},
            "evaluation_assessment_sha256": artifact.evaluation_assessment_sha256,
            "proposed_required_criteria": list(artifact.proposed_required_criteria), "reason_code": artifact.reason_code,
        }

    def _record_policy_rejection_from_evaluator(self, work_order: WorkOrder, *, artifact_path: str,
            cycle_id: str, candidate_id: str, at: datetime | None = None,
            capability: object | None = None) -> dict[str, Any]:
        if capability is not _EVALUATOR_CAPABILITY:
            raise StateError("evaluator capability is required")
        with self._locked():
            head = self._load_unlocked(work_order)
            artifact = work_order.verify_policy_rejection_artifact(artifact_path, cycle_id=cycle_id, candidate_id=candidate_id)
            record = self._policy_record(artifact)
            assessment = next((x for x in head["evaluation_assessments"]
                if x["sha256"] == artifact.evaluation_assessment_sha256 and x["cycle_id"] == cycle_id
                and x["candidate_id"] == candidate_id), None)
            if assessment is None:
                raise StateError("policy rejection must reference the exact durable evaluation assessment")
            if assessment["evaluator_id"] != artifact.evaluator_id:
                raise StateError("policy evaluator identity conflicts with evaluation assessment")
            if assessment["candidate_source"] != record["candidate_source"]:
                raise StateError("policy candidate source conflicts with evaluation assessment")
            if artifact.reason_code == "holdout_integrity_violation" and assessment["holdout_integrity"] != "violated":
                raise StateError("holdout rejection requires a violated holdout receipt")
            if artifact.reason_code == "comparison_incomplete":
                comparison = check_matched_comparison(ComparisonDesign(
                    tuple(assessment["candidate_cases"]), tuple(assessment["baseline_cases"]),
                    assessment["candidate_budget"], assessment["baseline_budget"],
                    frozenset(assessment["required_ablations"]), frozenset(assessment["observed_ablations"])))
                if comparison.complete:
                    raise StateError("comparison rejection requires an incomplete receipt-derived assessment")
            self._require_candidate_identity(head, cycle_id, candidate_id, record["candidate_source"])
            for existing in head["policy_observations"]:
                if existing["cycle_id"] == cycle_id and existing["candidate_id"] == candidate_id:
                    if existing == record:
                        return head
                    raise StateError("policy observation conflicts with existing evaluator evidence")
                if existing["sha256"] == record["sha256"]:
                    raise StateError("policy observation replay across identities is forbidden")
            return self._append_loaded(work_order, head, "policy_observation", record, at)

    @staticmethod
    def _cancellation_record(artifact: Any) -> dict[str, Any]:
        return {
            "path": artifact.path, "sha256": artifact.sha256, "plan_sha256": artifact.plan_sha256,
            "cycle_id": artifact.cycle_id, "candidate_id": artifact.candidate_id,
            "candidate_source": {"path": artifact.candidate_source.path, "sha256": artifact.candidate_source.sha256},
            "slot_id": artifact.slot_id, "attempt_id": artifact.attempt_id,
            "cancellation_event_id": artifact.cancellation_event_id, "reason_code": artifact.reason_code,
            "cancelled_at": artifact.cancelled_at.isoformat(),
            "evidence": [{"path": x.path, "sha256": x.sha256} for x in artifact.evidence],
        }

    def _record_cancellation_from_scheduler(self, work_order: WorkOrder, *, artifact_path: str,
            cycle_id: str, candidate_id: str, slot_id: str, attempt_id: str, cancellation_event_id: str,
            at: datetime | None = None, capability: object | None = None) -> dict[str, Any]:
        if capability is not _CANCELLATION_CAPABILITY:
            raise StateError("cancellation capability is required")
        with self._locked():
            head = self._load_unlocked(work_order)
            artifact = work_order.verify_cancellation_artifact(artifact_path, cycle_id=cycle_id,
                candidate_id=candidate_id, slot_id=slot_id, attempt_id=attempt_id,
                cancellation_event_id=cancellation_event_id)
            record = self._cancellation_record(artifact)
            recorded_at = _aware(at)
            if artifact.cancelled_at < work_order.execution.starts_at:
                raise StateError("cancellation cannot predate the execution window")
            if artifact.cancelled_at > recorded_at:
                raise StateError("cancellation receipt cannot be recorded before cancelled_at")
            if cycle_id not in head["cycle_ids"] or candidate_id not in head["variants"]:
                raise StateError("cancellation must bind a recorded candidate cycle")
            self._require_candidate_identity(head, cycle_id, candidate_id, record["candidate_source"])
            for existing in head["cancellations"]:
                same = (existing["cancellation_event_id"] == cancellation_event_id
                        or existing["slot_id"] == slot_id and existing["attempt_id"] == attempt_id)
                if same:
                    if existing == record:
                        return head
                    raise StateError("cancellation conflicts with durable evidence")
                if existing["sha256"] == record["sha256"]:
                    raise StateError("cancellation replay across identities is forbidden")
            return self._append_loaded(work_order, head, "cancellation", record, at)

    def load_cancellation(self, work_order: WorkOrder, *, artifact_sha256: str,
                          cycle_id: str, candidate_id: str) -> TrustedCancellation:
        if not isinstance(artifact_sha256, str) or not _SHA_RE.fullmatch(artifact_sha256):
            raise StateError("artifact_sha256 must be a lowercase SHA-256 digest")
        head = self.load(work_order)
        record = next((x for x in head["cancellations"] if x["sha256"] == artifact_sha256
                       and x["cycle_id"] == cycle_id and x["candidate_id"] == candidate_id), None)
        if record is None:
            raise StateError("durable cancellation was not found")
        artifact = work_order.verify_cancellation_artifact(record["path"], cycle_id=cycle_id,
            candidate_id=candidate_id, slot_id=record["slot_id"], attempt_id=record["attempt_id"],
            cancellation_event_id=record["cancellation_event_id"])
        if self._cancellation_record(artifact) != record:
            raise StateError("cancellation artifact derivation drifted")
        return TrustedCancellation(artifact.sha256, work_order.work_order_id, artifact.plan_sha256,
            work_order.acceptance.sha256, cycle_id, candidate_id, artifact.candidate_source.path,
            artifact.candidate_source.sha256, artifact.slot_id, artifact.attempt_id,
            artifact.cancellation_event_id, artifact.reason_code, artifact.cancelled_at.isoformat(),
            tuple((x.path, x.sha256) for x in artifact.evidence), _DURABLE_VERIFIER_PROOF)

    def load_verifier_observations(
        self, work_order: WorkOrder, *, artifact_sha256: str, cycle_id: str, candidate_id: str,
    ) -> VerifierCriterionObservations:
        """Return only an exact verifier observation reconstructed by ledger replay."""
        if not isinstance(artifact_sha256, str) or not _SHA_RE.fullmatch(artifact_sha256):
            raise StateError("artifact_sha256 must be a lowercase SHA-256 digest")
        cycle_id = _identifier(cycle_id, "cycle_id")
        candidate_id = _identifier(candidate_id, "candidate_id")
        head = self.load(work_order)
        record = next((
            item for item in head["criterion_observations"]
            if item["sha256"] == artifact_sha256
            and item["cycle_id"] == cycle_id
            and item["candidate_id"] == candidate_id
        ), None)
        if record is None:
            raise StateError("durable verifier observation was not found")
        verdicts = {"satisfied": True, "violated": False, "inconclusive": None}
        return VerifierCriterionObservations._from_durable_state(
            work_order_id=work_order.work_order_id,
            acceptance_sha256=work_order.acceptance.sha256,
            cycle_id=cycle_id,
            candidate_id=candidate_id,
            artifact_sha256=artifact_sha256,
            plan_sha256=record["plan_sha256"],
            candidate_source_path=record["candidate_source"]["path"],
            candidate_source_sha256=record["candidate_source"]["sha256"],
            observations=tuple(
                (item["criterion_id"], verdicts[item["verdict"]]) for item in record["observations"]
            ),
        )

    def terminalize(
        self, work_order: WorkOrder, *, terminal_state: str, candidate_id: str,
        reason_code: str, cycle_id: str | None = None,
        criterion_artifact_sha256: str | None = None, policy_artifact_sha256: str | None = None,
        cancellation_artifact_sha256: str | None = None, at: datetime | None = None,
    ) -> dict[str, Any]:
        """Append one irreversible terminal decision using durable references only."""
        if terminal_state not in _TERMINAL_STATES:
            raise StateError("terminal_state is invalid")
        candidate_id = _identifier(candidate_id, "candidate_id")
        reason_code = _identifier(reason_code, "reason_code")
        cycle_id = _identifier(cycle_id, "cycle_id") if cycle_id is not None else None
        for value, label in ((criterion_artifact_sha256, "criterion_artifact_sha256"),
                             (policy_artifact_sha256, "policy_artifact_sha256"),
                             (cancellation_artifact_sha256, "cancellation_artifact_sha256")):
            if value is not None and (not isinstance(value, str) or not _SHA_RE.fullmatch(value)):
                raise StateError(f"{label} must be a lowercase SHA-256 digest")
        when = _aware(at)
        if terminal_state == "expired" and when < work_order.execution.ends_at:
            raise StateError("expired terminal state requires the trusted execution deadline")
        if terminal_state == "cancelled":
            if cycle_id is None or cancellation_artifact_sha256 is None:
                raise StateError("cancelled terminal state requires a durable cancellation reference")
        elif cancellation_artifact_sha256 is not None:
            raise StateError("cancellation reference is only valid for cancelled terminal state")
        with self._locked():
            head = self._load_unlocked(work_order)
            cancellation = None
            if cancellation_artifact_sha256 is not None:
                cancellation = next((item for item in head["cancellations"]
                    if item["sha256"] == cancellation_artifact_sha256 and item["cycle_id"] == cycle_id
                    and item["candidate_id"] == candidate_id), None)
                if cancellation is None:
                    raise StateError("cancelled terminal state must reference a recorded cancellation")
                if reason_code != cancellation["reason_code"]:
                    raise StateError("terminal cancellation reason drifts from recorded cancellation")
            data = {
                "terminal_state": terminal_state, "candidate_id": candidate_id, "cycle_id": cycle_id,
                "criterion_artifact_sha256": criterion_artifact_sha256,
                "policy_artifact_sha256": policy_artifact_sha256, "reason_code": reason_code,
                "cancellation_artifact_sha256": cancellation_artifact_sha256,
            }
            if head["terminal_record"] is not None:
                if head["terminal_record"] == data:
                    return head
                raise StateError("terminal state is immutable")
            return self._append_loaded(work_order, head, "terminal", data, when)

    def complete_verified(
        self, work_order: WorkOrder, *, candidate_id: str, cycle_id: str,
        criterion_artifact_sha256: str, at: datetime | None = None,
    ) -> dict[str, Any]:
        return self.terminalize(
            work_order, terminal_state="completed", candidate_id=candidate_id,
            cycle_id=cycle_id, criterion_artifact_sha256=criterion_artifact_sha256,
            reason_code="criteria_satisfied", at=at,
        )

    def complete(self, work_order: WorkOrder, *, verification_artifact_path: str, at: datetime | None = None) -> dict[str, Any]:
        """Reject new legacy completions; historical ledger events remain replayable."""
        raise StateError("legacy completion is replay-only; use verifier criterion evidence")

    def _append(self, work_order: WorkOrder, kind: str, data: dict[str, Any], at: datetime | None) -> dict[str, Any]:
        with self._locked():
            return self._append_loaded(work_order, self._load_unlocked(work_order), kind, data, at)

    def _append_loaded(self, work_order: WorkOrder, head: dict[str, Any], kind: str, data: dict[str, Any], at: datetime | None) -> dict[str, Any]:
        sequence = head["revision"] + 1
        event = {
            "sequence": sequence,
            "previous_event_hash": head["last_event_hash"],
            "owner_id": self.owner_id,
            "work_order_id": head["work_order_id"],
            "logical_session_id": head["logical_session_id"],
            "kind": kind,
            "data": data,
            "recorded_at": _aware(at).isoformat(),
        }
        updated = self._reduce_event(work_order, head, event)
        _exclusive_event(self.events_directory / f"{sequence:08d}.json", event)
        _atomic_write(self.head_path, updated)
        return _copy(updated)

    def _reduce_event(self, work_order: WorkOrder, head: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        _exact(event, {"sequence", "previous_event_hash", "owner_id", "work_order_id", "logical_session_id", "kind", "data", "recorded_at"}, "ledger event")
        if event["sequence"] != head["revision"] + 1 or event["previous_event_hash"] != head["last_event_hash"]:
            raise StateError("ledger sequence or hash chain is invalid")
        if event["owner_id"] != self.owner_id or event["work_order_id"] != head["work_order_id"] or event["logical_session_id"] != head["logical_session_id"]:
            raise StateError("ledger event identity is invalid")
        kind = event["kind"]
        if kind not in _EVENT_KINDS:
            raise StateError("ledger event kind is invalid")
        when = _parse_timestamp(event["recorded_at"], "event.recorded_at")
        if when < _parse_timestamp(head["updated_at"], "head.updated_at"):
            raise StateError("event timestamps must be monotonic")
        if kind in {"provider_thread", "cycle", "intervention", "reused_evaluation"}:
            if not work_order.execution.starts_at <= when <= work_order.execution.ends_at:
                raise StateError("worker event is outside the execution window")
        if head["status"] in _TERMINAL_STATES:
            raise StateError("terminal sessions are immutable")
        if kind in {"provider_thread", "cycle", "intervention", "reused_evaluation", "criterion_observation", "evaluation_assessment", "policy_observation", "cancellation", "terminal", "completion"} and head["status"] != "active":
            raise StateError("session is not continuable")
        if kind == "effect_resolution" and head["status"] not in {"active", "blocked_pending_effect"}:
            raise StateError("effect resolution is not allowed from this state")

        updated = _copy(head)
        data = event["data"]
        if kind == "provider_thread":
            _exact(data, {"provider", "thread_id"}, "provider_thread data")
            _identifier(data["provider"], "provider")
            thread_id = _identifier(data["thread_id"], "thread_id")
            if any(item["thread_id"] == thread_id for item in head["provider_threads"]):
                raise StateError("provider thread identifier already recorded")
            if len(head["provider_threads"]) >= work_order.logical_session.max_provider_threads:
                raise StateError("provider thread limit reached")
            updated["provider_threads"].append(data)
        elif kind == "cycle":
            _exact(data, {
                "cycle_id", "variant_id", "action_sha256", "outcome",
                "verified_evidence_artifact_path", "verified_evidence_artifact_sha256",
                "verified_evidence_ids", "effect_id", "effect_status",
            }, "cycle data")
            cycle_id = _identifier(data["cycle_id"], "cycle_id")
            variant_id = _identifier(data["variant_id"], "variant_id")
            action = data["action_sha256"]
            if cycle_id in head["cycle_ids"]:
                raise StateError("cycle identifier already recorded")
            if not isinstance(action, str) or not _SHA_RE.fullmatch(action) or data["outcome"] not in _OUTCOMES or data["effect_status"] not in _EFFECT_STATES:
                raise StateError("cycle data is invalid")
            artifact_path = data["verified_evidence_artifact_path"]
            artifact_sha256 = data["verified_evidence_artifact_sha256"]
            if artifact_path is None:
                if artifact_sha256 is not None or data["verified_evidence_ids"] != []:
                    raise StateError("cycle without a progress artifact may not claim evidence")
                evidence: list[str] = []
            else:
                if not isinstance(artifact_path, str):
                    raise StateError("cycle progress artifact path is invalid")
                artifact = work_order.verify_progress_artifact(artifact_path, cycle_id)
                if artifact_sha256 != artifact.sha256 or data["verified_evidence_ids"] != list(artifact.evidence_ids):
                    raise StateError("cycle progress artifact digest or derived evidence drifted")
                evidence = list(artifact.evidence_ids)
            if set(evidence) & set(head["verified_evidence_ids"]):
                raise StateError("verified evidence ID was already consumed by an earlier cycle")
            if (data["effect_status"] == "pending") != (data["effect_id"] is not None):
                raise StateError("cycle pending effect fields disagree")
            if data["effect_id"] is not None:
                _identifier(data["effect_id"], "effect_id")
            if head["turns_used"] >= work_order.execution.max_turns:
                raise StateError("turn limit reached")
            if variant_id not in head["variants"] and len(head["variants"]) >= work_order.evidence_policy.max_variants:
                raise StateError("variant budget reached")
            derived_progress = bool(evidence)
            no_progress = 0 if derived_progress else head["consecutive_no_progress"] + 1
            repeated = (
                head["repeated_action_count"] + 1
                if not derived_progress and head["last_action_sha256"] == action
                else 0
            )
            if no_progress > work_order.supervision.max_no_progress_cycles:
                raise StateError("no-progress cycle limit reached")
            if repeated > work_order.supervision.max_repeated_actions:
                raise StateError("repeated-action limit reached")
            updated["turns_used"] += 1
            updated["cycle_ids"].append(cycle_id)
            updated["verified_evidence_ids"].extend(evidence)
            if variant_id not in updated["variants"]:
                updated["variants"].append(variant_id)
            if data["outcome"] in {"failed", "cancelled", "unknown"}:
                updated["failed_attempts"].append(cycle_id)
            if data["effect_status"] == "pending":
                if data["effect_id"] in updated["pending_effects"]:
                    raise StateError("pending effect identifier already exists")
                updated["pending_effects"].append(data["effect_id"])
                updated["status"] = "blocked_pending_effect"
            updated["consecutive_no_progress"] = no_progress
            updated["repeated_action_count"] = repeated
            updated["last_action_sha256"] = action
        elif kind == "effect_resolution":
            _exact(data, {"reconciliation_id", "engine_slot_id", "engine_attempt_id", "outcome", "evidence_sha256"}, "effect_resolution data")
            reconciliation_id = _identifier(data["reconciliation_id"], "reconciliation_id")
            _engine_slot_identifier(data["engine_slot_id"])
            attempt_id = _identifier(data["engine_attempt_id"], "engine_attempt_id")
            if data["outcome"] not in {"succeeded", "failed"}:
                raise StateError("effect reconciliation outcome is invalid")
            if not isinstance(data["evidence_sha256"], str) or not _SHA_RE.fullmatch(data["evidence_sha256"]):
                raise StateError("effect reconciliation evidence digest is invalid")
            if any(item["reconciliation_id"] == reconciliation_id or item["engine_attempt_id"] == attempt_id for item in head["effect_resolutions"]):
                raise StateError("effect reconciliation identity already recorded")
            if attempt_id not in head["pending_effects"]:
                raise StateError("engine_attempt_id must equal a pending effect_id")
            record = {**data, "effect_state": "confirmed" if data["outcome"] == "succeeded" else "failed"}
            updated["pending_effects"].remove(attempt_id)
            updated["effect_resolutions"].append(record)
            updated["status"] = "active" if not updated["pending_effects"] else "blocked_pending_effect"
        elif kind == "intervention":
            _exact(data, {"intervention_id", "reason_code"}, "intervention data")
            intervention_id = _identifier(data["intervention_id"], "intervention_id")
            _identifier(data["reason_code"], "reason_code")
            if any(item["intervention_id"] == intervention_id for item in head["interventions"]):
                raise StateError("intervention identifier already recorded")
            if len(head["interventions"]) >= work_order.supervision.max_interventions:
                raise StateError("intervention limit reached")
            updated["interventions"].append(data)
        elif kind == "reused_evaluation":
            _exact(data, {"evaluation_id", "source_cycle_id"}, "reused_evaluation data")
            evaluation_id = _identifier(data["evaluation_id"], "evaluation_id")
            source = _identifier(data["source_cycle_id"], "source_cycle_id")
            if source not in head["cycle_ids"]:
                raise StateError("reused evaluation must reference an existing cycle")
            if evaluation_id in head["reused_evaluations"]:
                raise StateError("evaluation identifier already recorded")
            if len(head["reused_evaluations"]) >= work_order.evidence_policy.max_reused_evaluations:
                raise StateError("reused-evaluation limit reached")
            updated["reused_evaluations"].append(evaluation_id)
        elif kind == "criterion_observation":
            _exact(data, {
                "path", "sha256", "verifier_id", "plan_sha256", "cycle_id", "candidate_id",
                "candidate_source", "observations",
            }, "criterion_observation data")
            cycle_id = _identifier(data["cycle_id"], "cycle_id")
            candidate_id = _identifier(data["candidate_id"], "candidate_id")
            if cycle_id not in head["cycle_ids"] or candidate_id not in head["variants"]:
                raise StateError("criterion observation must bind a recorded cycle and candidate variant")
            artifact = work_order.verify_criterion_observation_artifact(
                data["path"], cycle_id=cycle_id, candidate_id=candidate_id
            )
            expected = {
                "path": artifact.path,
                "sha256": artifact.sha256,
                "verifier_id": artifact.verifier_id,
                "plan_sha256": artifact.plan_sha256,
                "cycle_id": artifact.cycle_id,
                "candidate_id": artifact.candidate_id,
                "candidate_source": {
                    "path": artifact.candidate_source.path,
                    "sha256": artifact.candidate_source.sha256,
                },
                "observations": [
                    {
                        "criterion_id": item.criterion_id,
                        "verdict": item.verdict,
                        "evidence": [{"path": bound.path, "sha256": bound.sha256} for bound in item.evidence],
                    }
                    for item in artifact.observations
                ],
            }
            if data != expected:
                raise StateError("criterion artifact digest or derived observations drifted")
            self._require_candidate_identity(head, cycle_id, candidate_id, data["candidate_source"])
            if any(
                item["cycle_id"] == cycle_id and item["candidate_id"] == candidate_id
                for item in head["criterion_observations"]
            ):
                raise StateError("criterion observation identity already recorded")
            if any(item["sha256"] == data["sha256"] for item in head["criterion_observations"]):
                raise StateError("criterion observation replay across identities is forbidden")
            updated["criterion_observations"].append(data)
        elif kind == "evaluation_assessment":
            expected_keys = {"path", "sha256", "evaluator_id", "plan_sha256", "cycle_id", "candidate_id",
                "candidate_source", "case_manifest", "candidate_cases", "baseline_cases", "usage_receipt",
                "candidate_budget", "baseline_budget", "ablation_receipt", "required_ablations", "observed_ablations",
                "holdout_receipt", "holdout_integrity", "holdout_evidence"}
            _exact(data, expected_keys, "evaluation_assessment data")
            artifact = work_order.verify_evaluation_assessment_artifact(data["path"], cycle_id=data["cycle_id"], candidate_id=data["candidate_id"])
            if data != self._evaluation_record(artifact):
                raise StateError("evaluation assessment receipt derivation drifted")
            if data["cycle_id"] not in head["cycle_ids"] or data["candidate_id"] not in head["variants"]:
                raise StateError("evaluation assessment must bind recorded candidate cycle")
            self._require_candidate_identity(head, data["cycle_id"], data["candidate_id"], data["candidate_source"])
            if any(x["cycle_id"] == data["cycle_id"] and x["candidate_id"] == data["candidate_id"] for x in head["evaluation_assessments"]):
                raise StateError("evaluation assessment identity already recorded")
            if any(x["sha256"] == data["sha256"] for x in head["evaluation_assessments"]):
                raise StateError("evaluation assessment replay across identities is forbidden")
            updated["evaluation_assessments"].append(data)
        elif kind == "policy_observation":
            _exact(data, {"path", "sha256", "evaluator_id", "plan_sha256", "cycle_id", "candidate_id",
                "candidate_source", "evaluation_assessment_sha256", "proposed_required_criteria", "reason_code"},
                "policy_observation data")
            artifact = work_order.verify_policy_rejection_artifact(data["path"], cycle_id=data["cycle_id"], candidate_id=data["candidate_id"])
            if data != self._policy_record(artifact):
                raise StateError("policy artifact digest or derived policy drifted")
            assessment = next((x for x in head["evaluation_assessments"] if x["sha256"] == data["evaluation_assessment_sha256"]
                and x["cycle_id"] == data["cycle_id"] and x["candidate_id"] == data["candidate_id"]), None)
            if assessment is None or assessment["evaluator_id"] != data["evaluator_id"]:
                raise StateError("policy rejection assessment or evaluator binding drifted")
            if assessment["candidate_source"] != data["candidate_source"]:
                raise StateError("policy candidate source conflicts with evaluation assessment")
            if data["reason_code"] == "holdout_integrity_violation" and assessment["holdout_integrity"] != "violated":
                raise StateError("holdout rejection requires a violated holdout receipt")
            if data["reason_code"] == "comparison_incomplete":
                comparison = check_matched_comparison(ComparisonDesign(
                    tuple(assessment["candidate_cases"]), tuple(assessment["baseline_cases"]),
                    assessment["candidate_budget"], assessment["baseline_budget"],
                    frozenset(assessment["required_ablations"]), frozenset(assessment["observed_ablations"])))
                if comparison.complete:
                    raise StateError("comparison rejection requires an incomplete receipt-derived assessment")
            if data["cycle_id"] not in head["cycle_ids"] or data["candidate_id"] not in head["variants"]:
                raise StateError("policy observation must bind a recorded cycle and candidate variant")
            self._require_candidate_identity(head, data["cycle_id"], data["candidate_id"], data["candidate_source"])
            if any(x["cycle_id"] == data["cycle_id"] and x["candidate_id"] == data["candidate_id"] for x in head["policy_observations"]):
                raise StateError("policy observation identity already recorded")
            if any(x["sha256"] == data["sha256"] for x in head["policy_observations"]):
                raise StateError("policy observation replay across identities is forbidden")
            updated["policy_observations"].append(data)
        elif kind == "cancellation":
            _exact(data, {"path", "sha256", "plan_sha256", "cycle_id", "candidate_id", "candidate_source",
                "slot_id", "attempt_id", "cancellation_event_id", "reason_code", "cancelled_at", "evidence"},
                "cancellation data")
            artifact = work_order.verify_cancellation_artifact(data["path"], cycle_id=data["cycle_id"],
                candidate_id=data["candidate_id"], slot_id=data["slot_id"], attempt_id=data["attempt_id"],
                cancellation_event_id=data["cancellation_event_id"])
            if data != self._cancellation_record(artifact):
                raise StateError("cancellation artifact derivation drifted")
            if artifact.cancelled_at < work_order.execution.starts_at:
                raise StateError("cancellation cannot predate the execution window")
            if artifact.cancelled_at > when:
                raise StateError("cancellation receipt cannot be recorded before cancelled_at")
            if data["cycle_id"] not in head["cycle_ids"] or data["candidate_id"] not in head["variants"]:
                raise StateError("cancellation must bind a recorded candidate cycle")
            self._require_candidate_identity(head, data["cycle_id"], data["candidate_id"], data["candidate_source"])
            if any(x["cancellation_event_id"] == data["cancellation_event_id"] or
                   x["slot_id"] == data["slot_id"] and x["attempt_id"] == data["attempt_id"] for x in head["cancellations"]):
                raise StateError("cancellation identity already recorded")
            if any(x["sha256"] == data["sha256"] for x in head["cancellations"]):
                raise StateError("cancellation replay across identities is forbidden")
            updated["cancellations"].append(data)
        elif kind == "terminal":
            _exact(data, {
                "terminal_state", "candidate_id", "cycle_id", "criterion_artifact_sha256",
                "policy_artifact_sha256", "reason_code", "cancellation_artifact_sha256",
            }, "terminal data")
            terminal_state = data["terminal_state"]
            candidate_id = _identifier(data["candidate_id"], "candidate_id")
            _identifier(data["reason_code"], "reason_code")
            if terminal_state not in _TERMINAL_STATES:
                raise StateError("terminal state is invalid")
            if terminal_state == "expired" and when < work_order.execution.ends_at:
                raise StateError("expired terminal state requires the trusted execution deadline")
            cancellation_sha = data["cancellation_artifact_sha256"]
            cancellation = None
            if terminal_state == "cancelled":
                cancellation = next((item for item in head["cancellations"]
                    if item["sha256"] == cancellation_sha and item["cycle_id"] == data["cycle_id"]
                    and item["candidate_id"] == candidate_id), None)
                if cancellation is None:
                    raise StateError("cancelled terminal state must reference a recorded cancellation")
                if data["reason_code"] != cancellation["reason_code"]:
                    raise StateError("terminal cancellation reason drifts from recorded cancellation")
            elif cancellation_sha is not None:
                raise StateError("non-cancelled terminal state may not claim cancellation provenance")
            if head["pending_effects"]:
                raise StateError("terminal state requires zero pending effects")
            cycle_id = data["cycle_id"]
            artifact_sha256 = data["criterion_artifact_sha256"]
            observation = None
            policy_observation = None
            if cycle_id is not None:
                cycle_id = _identifier(cycle_id, "cycle_id")
            if artifact_sha256 is not None:
                if not isinstance(artifact_sha256, str) or not _SHA_RE.fullmatch(artifact_sha256):
                    raise StateError("terminal criterion artifact digest is invalid")
                observation = next((
                    item for item in head["criterion_observations"]
                    if item["sha256"] == artifact_sha256
                    and item["candidate_id"] == candidate_id
                    and item["cycle_id"] == cycle_id
                ), None)
                if observation is None:
                    raise StateError("terminal decision must reference recorded verifier evidence")
            policy_sha256 = data["policy_artifact_sha256"]
            if policy_sha256 is not None:
                if not isinstance(policy_sha256, str) or not _SHA_RE.fullmatch(policy_sha256):
                    raise StateError("terminal policy artifact digest is invalid")
                policy_observation = next((item for item in head["policy_observations"]
                    if item["sha256"] == policy_sha256 and item["candidate_id"] == candidate_id
                    and item["cycle_id"] == cycle_id), None)
                if policy_observation is None:
                    raise StateError("terminal decision must reference recorded evaluator policy evidence")
            if terminal_state in {"completed", "inconclusive_budget_exhausted"} and observation is None:
                raise StateError("evidence-based terminal state requires verifier criterion evidence")
            if terminal_state == "rejected" and observation is None and policy_observation is None:
                raise StateError("rejected requires verifier or evaluator evidence")
            verdicts = {item["verdict"] for item in observation["observations"]} if observation else set()
            if terminal_state == "completed" and verdicts != {"satisfied"}:
                raise StateError("completed requires every frozen criterion to be satisfied")
            if terminal_state == "rejected" and "violated" not in verdicts and policy_observation is None:
                raise StateError("rejected requires a criterion violation or evaluator policy rejection")
            if policy_observation is not None and data["reason_code"] != policy_observation["reason_code"]:
                raise StateError("terminal rejection reason drifts from evaluator policy evidence")
            if terminal_state == "inconclusive_budget_exhausted" and "violated" in verdicts:
                raise StateError("an observed criterion violation must be rejected, not inconclusive")
            missing = set(work_order.completion.required_event_kinds) - set(head["event_kinds"])
            if terminal_state == "completed" and missing:
                raise StateError(f"required event evidence is missing: {sorted(missing)}")
            updated["terminal_record"] = data
            updated["verification_artifact"] = (
                {"path": observation["path"], "sha256": observation["sha256"]} if observation else None
            )
            updated["status"] = terminal_state
        else:
            _exact(data, {"path", "sha256"}, "completion data")
            if head["status"] != "active" or head["pending_effects"]:
                raise StateError("completion requires active state with no pending effects")
            missing = set(work_order.completion.required_event_kinds) - set(head["event_kinds"])
            if missing:
                raise StateError(f"required event evidence is missing: {sorted(missing)}")
            artifact = work_order.verify_acceptance_artifact(data["path"])
            if data["sha256"] != artifact.sha256:
                raise StateError("verification artifact digest drifted")
            updated["verification_artifact"] = {"path": artifact.path, "sha256": artifact.sha256}
            updated["terminal_record"] = {
                "terminal_state": "completed", "candidate_id": "legacy", "cycle_id": None,
                "criterion_artifact_sha256": None, "policy_artifact_sha256": None,
                "reason_code": "legacy_acceptance",
            }
            updated["status"] = "completed"

        updated["revision"] = event["sequence"]
        updated["last_event_hash"] = _event_hash(event)
        updated["event_kinds"].append(kind)
        updated["updated_at"] = event["recorded_at"]
        return updated

    def _replay(self, work_order: WorkOrder, published: dict[str, Any], paths: list[Path]) -> dict[str, Any]:
        state = self._initial_head(work_order, published["created_at"])
        for path in paths:
            if path.is_symlink():
                raise StateError("ledger events may not be symlinks")
            _check_owned_private(path)
            state = self._reduce_event(work_order, state, _read_json(path))
        return state

    def _validate_head_identity(self, head: dict[str, Any], work_order: WorkOrder) -> None:
        actual_keys = set(head)
        if actual_keys != _HEAD_KEYS and actual_keys != _HEAD_KEYS - {"cancellations"}:
            raise StateError("head contains missing or unknown keys")
        _parse_timestamp(head["created_at"], "head.created_at")
        _parse_timestamp(head["updated_at"], "head.updated_at")
        if not (
            head["schema_version"] == 1
            and head["owner_id"] == self.owner_id
            and head["work_order_id"] == work_order.work_order_id
            and head["logical_session_id"] == work_order.logical_session.logical_session_id
            and head["plan_sha256"] == work_order.plan.sha256
            and head["acceptance_sha256"] == work_order.acceptance.sha256
            and isinstance(head["revision"], int) and not isinstance(head["revision"], bool) and head["revision"] >= 0
        ):
            raise StateError("state owner, identity, revision, or frozen binding does not match")

    def _event_paths(self) -> list[Path]:
        paths = sorted(self.events_directory.glob("*.json"))
        for sequence, path in enumerate(paths, 1):
            if path.name != f"{sequence:08d}.json":
                raise StateError("ledger event names must be contiguous")
        return paths

    @contextmanager
    def _locked(self):
        try:
            descriptor = os.open(self.lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
        except OSError as exc:
            raise StateError("session lock is unavailable") from exc
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _check_layout(self) -> None:
        if self.directory.is_symlink() or self.events_directory.is_symlink() or self.head_path.is_symlink() or self.lock_path.is_symlink():
            raise StateError("state layout may not contain symlinks")
        for path in (self.directory, self.events_directory, self.head_path, self.lock_path):
            if not path.exists():
                raise StateError("session state is incomplete")
            _check_owned_private(path)
