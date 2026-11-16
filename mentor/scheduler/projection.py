"""Canonical read-only projection from mentor work-order and ledger state.

This module owns no database and performs no dispatch.  It derives the CLI/API
shape from the frozen work order, validated session head, and independently
supplied acceptance/evaluation summaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from .contracts import WorkOrder
from .state import DurableSessionStore
from .supervision import PromotionDecision, PromotionVerdict

UTC = timezone.utc
_STATUS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.:/+()-]{0,119}$")


class ProjectionBuildError(ValueError):
    """Raised when canonical status inputs do not match the frozen session."""


def _aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProjectionBuildError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _count(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000:
        raise ProjectionBuildError(f"{label} must be a bounded non-negative integer")
    return value


def _status(value: str, label: str) -> str:
    if not isinstance(value, str) or not _STATUS_RE.fullmatch(value):
        raise ProjectionBuildError(f"{label} is invalid")
    return value


@dataclass(frozen=True)
class GateSummary:
    verified: int
    failed: int
    pending: int

    def validated(self) -> "GateSummary":
        for name in ("verified", "failed", "pending"):
            _count(getattr(self, name), f"gates.{name}")
        return self


@dataclass(frozen=True)
class EvaluationSummary:
    baseline: str
    holdout: str

    def validated(self) -> "EvaluationSummary":
        for name in ("baseline", "holdout"):
            _status(getattr(self, name), f"evaluation.{name}")
        return self


def build_projection(
    work_order: WorkOrder,
    store: DurableSessionStore,
    *,
    generated_at: datetime,
    scheduler_status: str,
    gates: GateSummary,
    evaluation: EvaluationSummary,
    promotion: PromotionDecision,
    next_run_at: datetime | None = None,
    slot_id: str | None = None,
    runtime_report: str = "pending",
    email: str = "pending",
) -> dict[str, Any]:
    """Build the sole public status representation without copying private events."""

    work_order.verify_bindings()
    if not isinstance(store, DurableSessionStore):
        raise ProjectionBuildError("a durable session store is required")
    head = store.load(work_order)
    if not isinstance(promotion, PromotionDecision):
        raise ProjectionBuildError("a validated promotion decision is required")
    if promotion.acceptance_sha256 != work_order.acceptance.sha256:
        raise ProjectionBuildError("promotion decision does not bind frozen acceptance")
    generated = _aware(generated_at, "generated_at")
    next_run = _aware(next_run_at, "next_run_at") if next_run_at is not None else None
    gates.validated()
    if gates.verified + gates.failed + gates.pending != len(work_order.acceptance_criteria):
        raise ProjectionBuildError("gate counts do not cover frozen acceptance criteria")
    evaluation.validated()
    scheduler_status = _status(scheduler_status, "scheduler_status")
    runtime_report = _status(runtime_report, "runtime_report")
    email = _status(email, "email")
    if slot_id is not None and (
        not isinstance(slot_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", slot_id)
    ):
        raise ProjectionBuildError("slot_id is invalid")

    expected = {
        "work_order_id": work_order.work_order_id,
        "logical_session_id": work_order.logical_session.logical_session_id,
        "plan_sha256": work_order.plan.sha256,
        "acceptance_sha256": work_order.acceptance.sha256,
    }
    if any(head.get(key) != value for key, value in expected.items()):
        raise ProjectionBuildError("session head does not match the frozen work order")
    required = {
        "status", "turns_used", "variants", "failed_attempts", "pending_effects",
        "event_kinds",
    }
    if not required <= set(head):
        raise ProjectionBuildError("session head is incomplete")
    for field in ("variants", "failed_attempts", "pending_effects", "event_kinds"):
        if not isinstance(head[field], list):
            raise ProjectionBuildError(f"session head {field} is invalid")
    turns = _count(head["turns_used"], "turns_used")
    if turns > work_order.execution.max_turns:
        raise ProjectionBuildError("session head exceeds the turn budget")
    interventions = head["event_kinds"].count("intervention")
    variants = len(head["variants"])
    if interventions > work_order.supervision.max_interventions:
        raise ProjectionBuildError("session head exceeds the intervention budget")
    if variants > work_order.evidence_policy.max_variants:
        raise ProjectionBuildError("session head exceeds the variant budget")

    task_status = _status(head["status"], "task_status")
    accepted = promotion.verdict is PromotionVerdict.ACCEPTED
    if (task_status == "completed") != accepted:
        raise ProjectionBuildError("completed state and accepted promotion decision disagree")
    if task_status == "completed" and (gates.verified != len(work_order.acceptance_criteria) or gates.failed or gates.pending):
        raise ProjectionBuildError("completed state requires every frozen gate verified")
    if task_status == "blocked_pending_effect":
        last_progress = f"{turns} cycles recorded; latest effect outcome unresolved"
        obstacle = "pending external effect reconciliation"
        next_action = "reconcile pending effect before continuation"
    elif task_status == "completed":
        last_progress = "independent frozen-criteria acceptance recorded"
        obstacle = "none recorded"
        next_action = "none"
    else:
        last_progress = f"{turns} cycles recorded; {len(head['failed_attempts'])} failed or unknown"
        obstacle = "none recorded"
        next_action = "run next bounded cycle or independent acceptance verification"

    scheduler: dict[str, Any] = {"status": scheduler_status}
    if slot_id is not None:
        scheduler["slot_id"] = slot_id
    item = {
        "id": work_order.work_order_id,
        "logical_session": work_order.logical_session.logical_session_id,
        "schedule": {
            "start_at": work_order.execution.starts_at.astimezone(UTC).isoformat(),
            "end_at": work_order.execution.ends_at.astimezone(UTC).isoformat(),
            "next_run_at": next_run.isoformat() if next_run else None,
        },
        "scheduler": scheduler,
        "task": {
            "status": task_status,
            "gates": {
                "verified": gates.verified,
                "failed": gates.failed,
                "pending": gates.pending,
            },
            "last_verified_progress": last_progress,
            "current_obstacle": obstacle,
            "next_action": next_action,
            "goal_drift": "none",
        },
        "budgets": {
            "cycles_used": turns,
            "max_cycles": work_order.execution.max_turns,
            "interventions_used": interventions,
            "intervention_limit": work_order.supervision.max_interventions,
            "variants_used": variants,
            "variant_limit": work_order.evidence_policy.max_variants,
        },
        "evaluation": {
            "baseline": evaluation.baseline,
            "holdout": evaluation.holdout,
            "promotion": promotion.verdict.value,
        },
        "delivery": {"runtime_report": runtime_report, "email": email},
    }
    return {
        "schema_version": 1,
        "generated_at": generated.isoformat(),
        "work_orders": [item],
    }
