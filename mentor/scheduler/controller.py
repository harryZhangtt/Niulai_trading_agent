"""Pure orchestration for one verified autonomous mentor cycle.

The controller owns no worker, model, job, or transport capability.  It reloads
already-durable scheduler state, validates verifier-owned evidence, delegates all
progress/loop/comparison/promotion judgments to :mod:`supervision`, and uses only
the scheduler state's verifier and terminal APIs for persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable, Mapping

from .contracts import ContractError, WorkOrder
from .state import (
    DurableSessionStore,
    StateError,
    _VERIFIER_CAPABILITY,
)
from .supervision import (
    ComparisonAssessment,
    EvidenceSnapshot,
    FailureKind,
    FrozenCriteria,
    LoopAssessment,
    LoopVerdict,
    ProgressAssessment,
    ProgressVerdict,
    PromotionDecision,
    PromotionVerdict,
    SupervisionBudget,
    VerifierCriterionObservations,
    classify_progress,
    decide_loop,
)


class ControllerStatus(str, Enum):
    CONTINUE = "continue"
    COMPLETED = "completed"
    REJECTED = "rejected"
    INCONCLUSIVE_BUDGET_EXHAUSTED = "inconclusive_budget_exhausted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    BLOCKED_PENDING_EFFECT = "blocked_pending_effect"


class NextAction(str, Enum):
    COLLECT_CRITERION_EVIDENCE = "collect_criterion_evidence"
    COMPLETE_MATCHED_COMPARISON = "complete_matched_comparison"
    VERIFY_HOLDOUT_INTEGRITY = "verify_holdout_integrity"
    CHANGE_APPROACH = "change_approach"
    RECORD_INTERVENTION = "record_intervention"


class ControllerError(RuntimeError):
    """A stable, fail-closed controller contract error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BudgetSnapshot:
    seconds_remaining: float
    turns_remaining: int
    threads_remaining: int
    variants_remaining: int
    interventions_remaining: int
    no_progress_remaining: int
    repeated_actions_remaining: int
    reused_evaluations_remaining: int


@dataclass(frozen=True)
class ControllerInput:
    work_order: WorkOrder
    store: DurableSessionStore
    cycle_id: str
    candidate_id: str
    criterion_artifact_path: str
    evaluation_assessment_sha256: str
    current_action: Any
    hypothesis_changed: bool = False
    failure_kind: FailureKind | None = None
    error_signature: str | None = None
    previous_error_signature: str | None = None
    proposed_required_criteria: Iterable[str] | None = None
    policy_rejection_artifact_sha256: str | None = None
    cancellation_artifact_sha256: str | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


@dataclass(frozen=True)
class ControllerResult:
    status: ControllerStatus
    reason_code: str
    head: Mapping[str, Any]
    observations: tuple[VerifierCriterionObservations, ...] = ()
    comparison: ComparisonAssessment | None = None
    promotion: PromotionDecision | None = None
    progress: ProgressAssessment | None = None
    loop: LoopAssessment | None = None
    budgets: BudgetSnapshot | None = None
    next_action: NextAction | None = None
    intervention_required: bool = False


_TERMINAL = {
    ControllerStatus.COMPLETED,
    ControllerStatus.REJECTED,
    ControllerStatus.INCONCLUSIVE_BUDGET_EXHAUSTED,
    ControllerStatus.EXPIRED,
    ControllerStatus.CANCELLED,
}


def _now(source: ControllerInput) -> datetime:
    try:
        value = source.clock()
    except Exception as exc:  # injected boundary; normalize without hiding cause
        raise ControllerError("clock_failed", "clock provider failed") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControllerError("invalid_clock", "clock must return a timezone-aware datetime")
    return value


def _budgets(order: WorkOrder, head: Mapping[str, Any], now: datetime) -> BudgetSnapshot:
    return BudgetSnapshot(
        max(0.0, (order.execution.ends_at - now).total_seconds()),
        max(0, order.execution.max_turns - head["turns_used"]),
        max(0, order.logical_session.max_provider_threads - len(head["provider_threads"])),
        max(0, order.evidence_policy.max_variants - len(head["variants"])),
        max(0, order.supervision.max_interventions - len(head["interventions"])),
        max(0, order.supervision.max_no_progress_cycles - head["consecutive_no_progress"]),
        max(0, order.supervision.max_repeated_actions - head["repeated_action_count"]),
        max(0, order.evidence_policy.max_reused_evaluations - len(head["reused_evaluations"])),
    )


def _aggregate(
    order: WorkOrder,
    store: DurableSessionStore,
    head: Mapping[str, Any],
) -> tuple[VerifierCriterionObservations, ...]:
    return tuple(
        store.load_verifier_observations(
            order,
            artifact_sha256=item["sha256"],
            cycle_id=item["cycle_id"],
            candidate_id=item["candidate_id"],
        )
        for item in head["criterion_observations"]
    )


def _snapshot(observations: tuple[VerifierCriterionObservations, ...]) -> EvidenceSnapshot:
    criteria = frozenset(
        f"{item.candidate_id}:{item.cycle_id}:{criterion_id}:{verdict}"
        for item in observations
        for criterion_id, verdict in item.observations
    )
    return EvidenceSnapshot(
        criteria_verified=criteria,
        validated_artifacts=frozenset(item.artifact_sha256 for item in observations),
    )


def _existing_terminal(source: ControllerInput, head: Mapping[str, Any], now: datetime) -> ControllerResult | None:
    try:
        status = ControllerStatus(head["status"])
    except ValueError:
        return None
    if status not in _TERMINAL:
        return None
    record = head["terminal_record"]
    if not isinstance(record, dict) or record["candidate_id"] != source.candidate_id:
        raise ControllerError("terminal_conflict", "terminal state is immutable for a different candidate")
    if record["cycle_id"] is not None and record["cycle_id"] != source.cycle_id:
        raise ControllerError("terminal_conflict", "terminal state is immutable for a different cycle")
    return ControllerResult(
        status,
        record["reason_code"],
        head,
        observations=_aggregate(source.work_order, source.store, head),
        budgets=_budgets(source.work_order, head, now),
    )


def _terminalize(
    source: ControllerInput,
    status: ControllerStatus,
    reason: str,
    now: datetime,
    *,
    artifact_sha256: str | None = None,
    policy_artifact_sha256: str | None = None,
) -> Mapping[str, Any]:
    if status is ControllerStatus.COMPLETED:
        if artifact_sha256 is None:
            raise ControllerError("missing_verifier_evidence", "completion requires verifier evidence")
        return source.store.complete_verified(
            source.work_order,
            candidate_id=source.candidate_id,
            cycle_id=source.cycle_id,
            criterion_artifact_sha256=artifact_sha256,
            at=now,
        )
    evidence_based = status in {
        ControllerStatus.REJECTED,
        ControllerStatus.INCONCLUSIVE_BUDGET_EXHAUSTED,
    }
    cancelled = status is ControllerStatus.CANCELLED
    if cancelled and source.cancellation_artifact_sha256 is None:
        raise ControllerError("cancellation_provenance_required", "durable cancellation provenance is required")
    return source.store.terminalize(
        source.work_order,
        terminal_state=status.value,
        candidate_id=source.candidate_id,
        reason_code=reason,
        cycle_id=source.cycle_id if evidence_based or cancelled else None,
        criterion_artifact_sha256=artifact_sha256 if evidence_based else None,
        policy_artifact_sha256=policy_artifact_sha256,
        cancellation_artifact_sha256=source.cancellation_artifact_sha256 if cancelled else None,
        at=now,
    )


def _validate_cycle_candidate(source: ControllerInput, head: Mapping[str, Any]) -> None:
    if source.cycle_id not in head["cycle_ids"]:
        raise ControllerError("cycle_drift", "controller cycle is not durably recorded")
    if source.candidate_id not in head["variants"]:
        raise ControllerError("candidate_drift", "controller candidate is not a durably recorded variant")


def _budget_exhaustion(
    source: ControllerInput,
    head: Mapping[str, Any],
    budgets: BudgetSnapshot,
    progress: ProgressAssessment,
    loop: LoopAssessment,
    next_action: NextAction,
    intervention_required: bool,
) -> str | None:
    worker_action = next_action in {NextAction.COLLECT_CRITERION_EVIDENCE, NextAction.CHANGE_APPROACH}
    if worker_action and budgets.turns_remaining == 0:
        return "turn_budget_exhausted"
    if worker_action and budgets.threads_remaining == 0:
        return "thread_budget_exhausted"
    if next_action is NextAction.CHANGE_APPROACH and budgets.variants_remaining == 0:
        return "variant_budget_exhausted"
    if intervention_required and budgets.interventions_remaining == 0:
        return "intervention_budget_exhausted"
    if progress.verdict is ProgressVerdict.NO_PROGRESS and head["consecutive_no_progress"] >= source.work_order.supervision.max_no_progress_cycles:
        return "no_progress_budget_exhausted"
    if (
        progress.verdict is ProgressVerdict.NO_PROGRESS
        and progress.repeated_action
        and head["repeated_action_count"] >= source.work_order.supervision.max_repeated_actions
    ):
        return "repeated_action_budget_exhausted"
    if next_action is NextAction.COMPLETE_MATCHED_COMPARISON and budgets.reused_evaluations_remaining == 0:
        return "reused_evaluation_budget_exhausted"
    if loop.verdict is LoopVerdict.BUDGET_EXHAUSTED:
        return "intervention_budget_exhausted"
    return None


def run_controller(source: ControllerInput, *, capability: object | None = None) -> ControllerResult:
    """Evaluate and persist one verifier-authorized post-cycle decision.

    The exact scheduler verifier capability is mandatory: this function must not
    turn a caller-authored file into verifier-owned evidence. Contract failures
    raise :class:`ControllerError`; validation exceptions remain chained only as
    internal diagnostics. Returned terminal statuses are always read from, or
    atomically written to, the durable state ledger.
    """

    if capability is not _VERIFIER_CAPABILITY:
        raise ControllerError("verifier_capability_required", "verifier capability is required")
    if not isinstance(source.work_order, WorkOrder) or not isinstance(source.store, DurableSessionStore):
        raise ControllerError("invalid_input", "work_order and store must use production scheduler types")
    now = _now(source)
    last_now = now

    def read_now() -> datetime:
        nonlocal last_now
        current = _now(source)
        if current < last_now:
            raise ControllerError("clock_rollback", "trusted clock moved backwards")
        last_now = current
        return current

    try:
        source.work_order.verify_bindings()
        head = source.store.load(source.work_order)
    except (ContractError, StateError) as exc:
        raise ControllerError("state_or_binding_invalid", "durable state or frozen binding is invalid") from exc

    existing = _existing_terminal(source, head, now)
    if existing is not None:
        return existing
    _validate_cycle_candidate(source, head)

    if head["status"] == ControllerStatus.BLOCKED_PENDING_EFFECT.value or head["pending_effects"]:
        return ControllerResult(
            ControllerStatus.BLOCKED_PENDING_EFFECT,
            "pending_effect_requires_reconciliation",
            head,
            observations=_aggregate(source.work_order, source.store, head),
            budgets=_budgets(source.work_order, head, now),
        )
    if head["status"] != "active":
        raise ControllerError("state_not_continuable", f"unsupported active state: {head['status']}")

    if source.cancellation_artifact_sha256 is not None:
        try:
            cancellation = source.store.load_cancellation(
                source.work_order,
                artifact_sha256=source.cancellation_artifact_sha256,
                cycle_id=source.cycle_id,
                candidate_id=source.candidate_id,
            )
        except (ContractError, StateError, ValueError) as exc:
            raise ControllerError("cancellation_invalid", "durable cancellation evidence is invalid") from exc
        terminal_now = read_now()
        terminal = _terminalize(source, ControllerStatus.CANCELLED, cancellation.reason_code, terminal_now)
        return ControllerResult(ControllerStatus.CANCELLED, cancellation.reason_code, terminal, budgets=_budgets(source.work_order, terminal, terminal_now))

    before = _aggregate(source.work_order, source.store, head)
    try:
        artifact = source.work_order.verify_criterion_observation_artifact(
            source.criterion_artifact_path,
            cycle_id=source.cycle_id,
            candidate_id=source.candidate_id,
        )
        existing_criterion = next((item for item in head["criterion_observations"]
            if item["sha256"] == artifact.sha256 and item["cycle_id"] == source.cycle_id
            and item["candidate_id"] == source.candidate_id), None)
        record_now = read_now()
        if existing_criterion is None and record_now >= source.work_order.execution.ends_at:
            terminal = _terminalize(source, ControllerStatus.EXPIRED, "execution_window_expired", record_now)
            return ControllerResult(
                ControllerStatus.EXPIRED, "execution_window_expired", terminal,
                observations=before, budgets=_budgets(source.work_order, terminal, record_now),
            )
        head = source.store._record_criterion_observation_from_verifier(
            source.work_order,
            artifact_path=artifact.path,
            cycle_id=source.cycle_id,
            candidate_id=source.candidate_id,
            at=record_now,
            capability=_VERIFIER_CAPABILITY,
        )
    except (ContractError, StateError) as exc:
        raise ControllerError("criterion_artifact_invalid", "verifier criterion artifact is invalid") from exc

    observations = _aggregate(source.work_order, source.store, head)
    current = next(
        (item for item in observations if item.cycle_id == source.cycle_id and item.candidate_id == source.candidate_id),
        None,
    )
    if current is None or current.artifact_sha256 != artifact.sha256:
        raise ControllerError("criterion_artifact_drift", "recorded verifier evidence differs from validated artifact")

    try:
        evaluator_assessment = source.store.load_evaluator_assessment(
            source.work_order,
            artifact_sha256=source.evaluation_assessment_sha256,
            cycle_id=source.cycle_id,
            candidate_id=source.candidate_id,
        )
        if (
            evaluator_assessment.artifact_sha256 != source.evaluation_assessment_sha256
            or evaluator_assessment.candidate_source_path != current.candidate_source_path
            or evaluator_assessment.candidate_source_sha256 != current.candidate_source_sha256
        ):
            raise ControllerError(
                "candidate_source_mismatch",
                "verifier and evaluator candidate source bindings differ",
            )
    except (ContractError, StateError, ValueError) as exc:
        raise ControllerError(
            "evaluation_assessment_invalid",
            "durable evaluator assessment is invalid",
        ) from exc

    try:
        durable_previous_fingerprint = head["last_action_sha256"]
        progress = classify_progress(
            _snapshot(before),
            _snapshot(observations),
            source.current_action,
            previous_action_fingerprint=durable_previous_fingerprint,
        )
        if progress.action_fingerprint != head["last_action_sha256"]:
            raise ControllerError(
                "action_binding_mismatch",
                "controller action does not bind the durable cycle action",
            )
        loop = decide_loop(
            current_action_fingerprint=progress.action_fingerprint,
            previous_action_fingerprint=durable_previous_fingerprint,
            evidence_changed=progress.delta.changed,
            hypothesis_changed=source.hypothesis_changed,
            failure_kind=source.failure_kind,
            error_signature=source.error_signature,
            previous_error_signature=source.previous_error_signature,
            budget=SupervisionBudget(
                source.work_order.supervision.max_interventions,
                source.work_order.evidence_policy.max_variants,
                len(head["interventions"]),
                len(head["variants"]),
            ),
        )
        comparison = evaluator_assessment.comparison
        holdout_integrity = evaluator_assessment.holdout_integrity
        criteria = FrozenCriteria.from_work_order(source.work_order)
        promotion = source.store.decide_verified_promotion(
            source.work_order,
            criterion_artifact_sha256=artifact.sha256,
            evaluation_assessment_sha256=evaluator_assessment.artifact_sha256,
            candidate_id=source.candidate_id,
            cycle_id=source.cycle_id,
            proposed_required_criteria=source.proposed_required_criteria,
        )
    except (StateError, TypeError, ValueError) as exc:
        raise ControllerError("decision_input_invalid", "supervision decision input is invalid") from exc

    decision_now = read_now()
    budgets = _budgets(source.work_order, head, decision_now)
    verdicts = dict(current.observations)
    violated = {criterion_id for criterion_id, verdict in verdicts.items() if verdict is False}
    critical_violated = violated & criteria.critical

    if promotion.verdict is PromotionVerdict.ACCEPTED:
        try:
            terminal_now = read_now()
            terminal = _terminalize(source, ControllerStatus.COMPLETED, "criteria_satisfied", terminal_now, artifact_sha256=artifact.sha256)
        except StateError as exc:
            raise ControllerError("completion_precondition_failed", "durable completion precondition failed") from exc
        return ControllerResult(ControllerStatus.COMPLETED, "criteria_satisfied", terminal, observations, comparison, promotion, progress, loop, _budgets(source.work_order, terminal, terminal_now))

    if promotion.verdict is PromotionVerdict.REJECTED:
        policy_sha256 = None
        if violated:
            reason = "critical_criterion_violated" if critical_violated else "criterion_violated"
        else:
            if source.policy_rejection_artifact_sha256 is None:
                raise ControllerError(
                    "policy_rejection_evidence_required",
                    "durable evaluator policy rejection evidence is required",
                )
            try:
                head = source.store.load(source.work_order)
                policy = next((item for item in head["policy_observations"]
                    if item["sha256"] == source.policy_rejection_artifact_sha256
                    and item["cycle_id"] == source.cycle_id
                    and item["candidate_id"] == source.candidate_id), None)
                expected_proposed = (
                    {item.criterion_id for item in source.work_order.acceptance_criteria}
                    if source.proposed_required_criteria is None
                    else set(source.proposed_required_criteria)
                )
                if policy is None or (
                    policy["candidate_source"]["path"] != current.candidate_source_path
                    or policy["candidate_source"]["sha256"] != current.candidate_source_sha256
                    or policy["evaluation_assessment_sha256"] != evaluator_assessment.artifact_sha256
                    or policy["evaluator_id"] != evaluator_assessment.evaluator_id
                    or set(policy["proposed_required_criteria"]) != expected_proposed
                ):
                    raise ControllerError(
                        "policy_rejection_drift",
                        "evaluator policy evidence drifts from the promotion decision",
                    )
                policy_sha256 = policy["sha256"]
                reason = policy["reason_code"]
            except ControllerError:
                raise
            except (ContractError, StateError) as exc:
                raise ControllerError(
                    "policy_rejection_artifact_invalid",
                    "evaluator policy rejection artifact is invalid",
                ) from exc
        try:
            terminal_now = read_now()
            terminal = _terminalize(
                source,
                ControllerStatus.REJECTED,
                reason,
                terminal_now,
                artifact_sha256=artifact.sha256,
                policy_artifact_sha256=policy_sha256,
            )
        except StateError as exc:
            raise ControllerError("rejection_precondition_failed", "durable rejection precondition failed") from exc
        return ControllerResult(ControllerStatus.REJECTED, reason, terminal, observations, comparison, promotion, progress, loop, _budgets(source.work_order, terminal, terminal_now))

    if decision_now >= source.work_order.execution.ends_at:
        try:
            terminal_now = read_now()
            terminal = _terminalize(source, ControllerStatus.EXPIRED, "execution_window_expired", terminal_now)
        except StateError as exc:
            raise ControllerError("expiration_precondition_failed", "durable expiration precondition failed") from exc
        return ControllerResult(
            ControllerStatus.EXPIRED,
            "execution_window_expired",
            terminal,
            observations,
            comparison,
            promotion,
            progress,
            loop,
            _budgets(source.work_order, terminal, terminal_now),
        )

    missing_criterion = any(verdict is None for verdict in verdicts.values())
    if loop.verdict is LoopVerdict.CHANGE_APPROACH:
        next_action = NextAction.CHANGE_APPROACH
    elif loop.verdict in {LoopVerdict.STALLED, LoopVerdict.BUDGET_EXHAUSTED}:
        next_action = NextAction.RECORD_INTERVENTION
    elif missing_criterion:
        next_action = NextAction.COLLECT_CRITERION_EVIDENCE
    elif not comparison.complete:
        next_action = NextAction.COMPLETE_MATCHED_COMPARISON
    elif holdout_integrity is None:
        next_action = NextAction.VERIFY_HOLDOUT_INTEGRITY
    else:
        next_action = NextAction.RECORD_INTERVENTION

    intervention_required = loop.verdict in {LoopVerdict.CHANGE_APPROACH, LoopVerdict.STALLED, LoopVerdict.BUDGET_EXHAUSTED}
    exhausted = _budget_exhaustion(source, head, budgets, progress, loop, next_action, intervention_required)
    if exhausted is not None:
        try:
            terminal_now = read_now()
            terminal = _terminalize(
                source,
                ControllerStatus.INCONCLUSIVE_BUDGET_EXHAUSTED,
                exhausted,
                terminal_now,
                artifact_sha256=artifact.sha256,
            )
        except StateError as exc:
            raise ControllerError("budget_terminal_precondition_failed", "durable budget terminal precondition failed") from exc
        return ControllerResult(
            ControllerStatus.INCONCLUSIVE_BUDGET_EXHAUSTED,
            exhausted,
            terminal,
            observations,
            comparison,
            promotion,
            progress,
            loop,
            _budgets(source.work_order, terminal, terminal_now),
        )

    continue_now = read_now()
    if continue_now >= source.work_order.execution.ends_at:
        try:
            terminal_now = read_now()
            terminal = _terminalize(source, ControllerStatus.EXPIRED, "execution_window_expired", terminal_now)
        except StateError as exc:
            raise ControllerError("expiration_precondition_failed", "durable expiration precondition failed") from exc
        return ControllerResult(
            ControllerStatus.EXPIRED, "execution_window_expired", terminal,
            observations, comparison, promotion, progress, loop,
            _budgets(source.work_order, terminal, terminal_now),
        )
    budgets = _budgets(source.work_order, head, continue_now)
    return ControllerResult(
        ControllerStatus.CONTINUE,
        "additional_verified_evidence_required",
        head,
        observations,
        comparison,
        promotion,
        progress,
        loop,
        budgets,
        next_action,
        intervention_required,
    )


__all__ = [
    "BudgetSnapshot",
    "ControllerError",
    "ControllerInput",
    "ControllerResult",
    "ControllerStatus",
    "NextAction",
    "run_controller",
]
