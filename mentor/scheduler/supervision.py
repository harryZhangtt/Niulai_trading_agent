"""Deterministic mentor supervision and promotion-gate primitives.

The contracts in this module are pure: callers supply observations and retain any
persistent state.  Activity is deliberately distinct from verified progress, and
promotion is deliberately distinct from evidence collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping


class ProgressVerdict(str, Enum):
    """Whether an observation establishes meaningful progress."""

    MEANINGFUL = "meaningful"
    NO_PROGRESS = "no_progress"


class LoopVerdict(str, Enum):
    """The next supervision decision; none implies architecture failure."""

    CONTINUE = "continue"
    CHANGE_APPROACH = "change_approach"
    STALLED = "stalled"
    BUDGET_EXHAUSTED = "budget_exhausted"


class PromotionVerdict(str, Enum):
    """Semantics for a frozen promotion decision."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class FailureKind(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class HoldoutRole(str, Enum):
    DEVELOPER = "developer"
    EVALUATOR = "evaluator"


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BudgetExhausted(ValueError):
    """Raised when a caller tries to consume an exhausted bounded budget."""


def _canonicalize(value: Any) -> Any:
    """Return a JSON-compatible, type-preserving canonical representation."""

    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__dataclass__": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": [[field.name, _canonicalize(getattr(value, field.name))] for field in fields(value)],
        }
    if isinstance(value, Enum):
        return {
            "__enum__": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonicalize(value.value),
        }
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("action fingerprints do not accept NaN or infinity")
        return {"__float__": value.hex()}
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    if isinstance(value, Mapping):
        items = [(_canonicalize(key), _canonicalize(item)) for key, item in value.items()]
        items.sort(key=lambda item: _canonical_json(item[0]))
        return {"__mapping__": [[key, item] for key, item in items]}
    if isinstance(value, (set, frozenset)):
        items = [_canonicalize(item) for item in value]
        items.sort(key=_canonical_json)
        return {"__set__": items}
    if isinstance(value, tuple):
        return {"__tuple__": [_canonicalize(item) for item in value]}
    if isinstance(value, list):
        return {"__list__": [_canonicalize(item) for item in value]}
    raise TypeError(f"unsupported action fingerprint value: {type(value).__qualname__}")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_action_fingerprint(action: Any) -> str:
    """Return a stable SHA-256 fingerprint for a supported structured action.

    Mapping and set order do not affect the result.  Sequence order and scalar
    types do affect it.  Unsupported process-local objects are rejected instead
    of being represented by unstable ``repr`` output.
    """

    payload = _canonical_json(_canonicalize(action)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class EvidenceSnapshot:
    """Verified evidence known at a supervision checkpoint.

    Entries are stable evidence identifiers, not narration or unverified claims.
    Each category corresponds to a progress mechanism allowed by the mentor
    contract.
    """

    criteria_verified: frozenset[str] = frozenset()
    validated_artifacts: frozenset[str] = frozenset()
    narrowed_root_causes: frozenset[str] = frozenset()
    resolved_hypotheses: frozenset[str] = frozenset()
    source_backed_uncertainties_reduced: frozenset[str] = frozenset()
    unknown_effects_reconciled: frozenset[str] = frozenset()
    proven_blockers: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for field in fields(self):
            raw = getattr(self, field.name)
            normalized = frozenset(raw)
            if not all(isinstance(item, str) and item for item in normalized):
                raise ValueError(f"{field.name} entries must be non-empty strings")
            object.__setattr__(self, field.name, normalized)


@dataclass(frozen=True)
class EvidenceDelta:
    """Newly verified evidence, grouped by mechanism."""

    additions: tuple[tuple[str, frozenset[str]], ...]

    @property
    def changed(self) -> bool:
        return any(values for _, values in self.additions)

    @property
    def identifiers(self) -> frozenset[str]:
        return frozenset(item for _, values in self.additions for item in values)


def evidence_delta(previous: EvidenceSnapshot, current: EvidenceSnapshot) -> EvidenceDelta:
    """Compute additions only; removal cannot manufacture progress."""

    return EvidenceDelta(
        tuple(
            (field.name, getattr(current, field.name) - getattr(previous, field.name))
            for field in fields(EvidenceSnapshot)
        )
    )


@dataclass(frozen=True)
class ProgressAssessment:
    verdict: ProgressVerdict
    delta: EvidenceDelta
    action_fingerprint: str
    repeated_action: bool
    reason: str


_NON_PROGRESS_ACTIVITY = frozenset({"narration", "plan", "tool_call"})


def classify_progress(
    previous: EvidenceSnapshot,
    current: EvidenceSnapshot,
    action: Any,
    *,
    previous_action_fingerprint: str | None = None,
    activity_kind: str = "execution_result",
) -> ProgressAssessment:
    """Classify progress from verified evidence rather than activity.

    Narration, planning, and issuing a tool call are never progress themselves.
    A caller should classify the resulting verified observation separately as an
    ``execution_result``.  Repeating an action is acceptable only if that result
    adds verified evidence.
    """

    fingerprint = canonical_action_fingerprint(action)
    delta = evidence_delta(previous, current)
    repeated = fingerprint == previous_action_fingerprint
    if activity_kind in _NON_PROGRESS_ACTIVITY:
        return ProgressAssessment(
            ProgressVerdict.NO_PROGRESS,
            delta,
            fingerprint,
            repeated,
            f"{activity_kind} is activity, not verified progress",
        )
    if delta.changed:
        return ProgressAssessment(
            ProgressVerdict.MEANINGFUL,
            delta,
            fingerprint,
            repeated,
            "verified evidence increased",
        )
    reason = "repeated action produced no new evidence" if repeated else "no verified evidence delta"
    return ProgressAssessment(ProgressVerdict.NO_PROGRESS, delta, fingerprint, repeated, reason)


@dataclass(frozen=True)
class SupervisionBudget:
    """Explicit intervention and candidate-variant limits."""

    intervention_limit: int
    variant_limit: int
    interventions_used: int = 0
    variants_used: int = 0

    def __post_init__(self) -> None:
        values = (
            self.intervention_limit,
            self.variant_limit,
            self.interventions_used,
            self.variants_used,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("budget values must be non-negative integers")
        if self.interventions_used > self.intervention_limit:
            raise ValueError("interventions_used exceeds intervention_limit")
        if self.variants_used > self.variant_limit:
            raise ValueError("variants_used exceeds variant_limit")

    @property
    def can_intervene(self) -> bool:
        return self.interventions_used < self.intervention_limit

    @property
    def can_try_variant(self) -> bool:
        return self.variants_used < self.variant_limit

    def consume_intervention(self) -> SupervisionBudget:
        if not self.can_intervene:
            raise BudgetExhausted("intervention budget exhausted")
        return replace(self, interventions_used=self.interventions_used + 1)

    def consume_variant(self) -> SupervisionBudget:
        if not self.can_try_variant:
            raise BudgetExhausted("variant budget exhausted")
        return replace(self, variants_used=self.variants_used + 1)


@dataclass(frozen=True)
class LoopAssessment:
    verdict: LoopVerdict
    reason: str
    architecture_failure_proven: bool = False


def decide_loop(
    *,
    current_action_fingerprint: str,
    previous_action_fingerprint: str | None,
    evidence_changed: bool,
    hypothesis_changed: bool,
    failure_kind: FailureKind | None,
    error_signature: str | None,
    previous_error_signature: str | None,
    budget: SupervisionBudget,
) -> LoopAssessment:
    """Choose a loop response without time- or retry-count shortcuts."""

    if evidence_changed or hypothesis_changed:
        return LoopAssessment(LoopVerdict.CONTINUE, "evidence or hypothesis changed")
    repeated_action = current_action_fingerprint == previous_action_fingerprint
    repeated_error = error_signature is not None and error_signature == previous_error_signature
    if not repeated_action:
        return LoopAssessment(LoopVerdict.CONTINUE, "materially different action")
    if not budget.can_intervene:
        return LoopAssessment(LoopVerdict.BUDGET_EXHAUSTED, "unchanged repetition exhausted intervention budget")
    if failure_kind is FailureKind.PERMANENT and repeated_error:
        return LoopAssessment(LoopVerdict.CHANGE_APPROACH, "unchanged permanent failure requires a different approach")
    return LoopAssessment(LoopVerdict.STALLED, "repeated action changed neither evidence nor hypothesis")


@dataclass(frozen=True)
class FrozenCriteria:
    acceptance_sha256: str
    required: frozenset[str]
    critical: frozenset[str] = frozenset()
    plan_sha256: str | None = None

    def __post_init__(self) -> None:
        required = frozenset(self.required)
        critical = frozenset(self.critical)
        if not isinstance(self.acceptance_sha256, str) or not _SHA256_RE.fullmatch(self.acceptance_sha256):
            raise ValueError("criteria must bind a lowercase acceptance SHA-256 digest")
        if self.plan_sha256 is not None and not _SHA256_RE.fullmatch(self.plan_sha256):
            raise ValueError("criteria plan binding must be a lowercase SHA-256 digest")
        if not required or not all(isinstance(item, str) and item for item in required | critical):
            raise ValueError("criteria must contain non-empty string identifiers")
        if not critical <= required:
            raise ValueError("critical criteria must also be required")
        object.__setattr__(self, "required", required)
        object.__setattr__(self, "critical", critical)

    @classmethod
    def from_work_order(cls, work_order: Any) -> "FrozenCriteria":
        """Build criteria only from a validated work-order acceptance binding."""

        criteria = getattr(work_order, "acceptance_criteria", None)
        acceptance = getattr(work_order, "acceptance", None)
        plan = getattr(work_order, "plan", None)
        if not criteria or acceptance is None or plan is None:
            raise ValueError("validated work-order plan and acceptance criteria are required")
        required = frozenset(item.criterion_id for item in criteria)
        critical = frozenset(item.criterion_id for item in criteria if item.critical)
        return cls(acceptance.sha256, required, critical, plan.sha256)


def softened_criteria(frozen: FrozenCriteria, proposed_required: Iterable[str]) -> frozenset[str]:
    """Return frozen criteria omitted by a proposed post-hoc gate."""

    return frozen.required - frozenset(proposed_required)


_DURABLE_VERIFIER_PROOF = object()


@dataclass(frozen=True)
class VerifierCriterionObservations:
    """Read-only reference to criterion results reconstructed from durable state."""

    work_order_id: str
    acceptance_sha256: str
    cycle_id: str
    candidate_id: str
    artifact_sha256: str
    observations: tuple[tuple[str, bool | None], ...]
    plan_sha256: str | None = None
    candidate_source_path: str | None = None
    candidate_source_sha256: str | None = None
    _durable_proof: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        identifiers = (self.work_order_id, self.cycle_id, self.candidate_id)
        if not all(isinstance(item, str) and item for item in identifiers):
            raise ValueError("verifier observation identities must be non-empty strings")
        if not _SHA256_RE.fullmatch(self.acceptance_sha256) or not _SHA256_RE.fullmatch(self.artifact_sha256):
            raise ValueError("verifier observations require lowercase SHA-256 bindings")
        seen: set[str] = set()
        normalized = tuple(self.observations)
        for criterion_id, verdict in normalized:
            if not isinstance(criterion_id, str) or not criterion_id or criterion_id in seen:
                raise ValueError("verifier criterion observations must have unique non-empty IDs")
            if verdict not in {True, False, None}:
                raise ValueError("verifier criterion verdict must be true, false, or null")
            seen.add(criterion_id)
        object.__setattr__(self, "observations", normalized)
        bindings = (self.plan_sha256, self.candidate_source_sha256)
        if any(value is not None and not _SHA256_RE.fullmatch(value) for value in bindings):
            raise ValueError("durable verifier bindings must be lowercase SHA-256 digests")
        if self.candidate_source_path is not None and (
            not isinstance(self.candidate_source_path, str) or not self.candidate_source_path
        ):
            raise ValueError("candidate source path must be a non-empty string")

    @classmethod
    def _from_durable_state(
        cls, *, work_order_id: str, acceptance_sha256: str, cycle_id: str,
        candidate_id: str, artifact_sha256: str, plan_sha256: str,
        candidate_source_path: str, candidate_source_sha256: str,
        observations: tuple[tuple[str, bool | None], ...],
    ) -> "VerifierCriterionObservations":
        return cls(
            work_order_id, acceptance_sha256, cycle_id, candidate_id, artifact_sha256,
            observations, plan_sha256, candidate_source_path, candidate_source_sha256,
            _DURABLE_VERIFIER_PROOF,
        )

    def as_mapping(self, criteria: FrozenCriteria) -> Mapping[str, bool | None]:
        if self._durable_proof is not _DURABLE_VERIFIER_PROOF:
            raise ValueError("verifier observations were not loaded from durable state")
        if self.acceptance_sha256 != criteria.acceptance_sha256:
            raise ValueError("verifier observations drift from frozen acceptance")
        if criteria.plan_sha256 is None or self.plan_sha256 != criteria.plan_sha256:
            raise ValueError("verifier observations drift from frozen plan")
        observed = dict(self.observations)
        if set(observed) != criteria.required:
            raise ValueError("verifier observations do not exactly cover frozen criteria")
        return observed


@dataclass(frozen=True)
class HoldoutAccessEvent:
    actor: str
    role: HoldoutRole
    purpose: str


@dataclass(frozen=True)
class HoldoutAccessDecision:
    allowed: bool
    reason: str
    holdout: ProtectedHoldout


@dataclass(frozen=True)
class ProtectedHoldout:
    """Access record for a protected evaluator-only holdout."""

    identifier: str
    access_events: tuple[HoldoutAccessEvent, ...] = ()
    unauthorized_attempts: tuple[HoldoutAccessEvent, ...] = ()

    @property
    def untouched(self) -> bool:
        return not self.access_events

    @property
    def integrity_preserved(self) -> bool:
        return not self.unauthorized_attempts

    def request_access(self, *, actor: str, role: HoldoutRole, purpose: str) -> HoldoutAccessDecision:
        event = HoldoutAccessEvent(actor, role, purpose)
        allowed = bool(actor) and role is HoldoutRole.EVALUATOR and purpose == "promotion_evaluation"
        if allowed:
            updated = replace(self, access_events=self.access_events + (event,))
            return HoldoutAccessDecision(True, "evaluator access authorized", updated)
        updated = replace(self, unauthorized_attempts=self.unauthorized_attempts + (event,))
        return HoldoutAccessDecision(False, "holdout is evaluator-only and limited to promotion evaluation", updated)


@dataclass(frozen=True)
class ComparisonDesign:
    """Inputs needed to verify a matched baseline and declared ablations."""

    candidate_cases: tuple[str, ...]
    baseline_cases: tuple[str, ...] | None
    candidate_budget: Mapping[str, int]
    baseline_budget: Mapping[str, int] | None
    required_ablations: frozenset[str] = frozenset()
    observed_ablations: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ComparisonAssessment:
    complete: bool
    issues: tuple[str, ...]


def check_matched_comparison(design: ComparisonDesign) -> ComparisonAssessment:
    """Validate case/budget matching and presence of all declared ablations."""

    issues: list[str] = []

    def valid_cases(cases: tuple[str, ...] | None) -> bool:
        return bool(cases) and all(isinstance(case, str) and case for case in cases) and len(cases) == len(set(cases))

    def valid_budget(budget: Mapping[str, int] | None) -> bool:
        return bool(budget) and all(
            isinstance(key, str) and key and isinstance(value, int)
            and not isinstance(value, bool) and value >= 0
            for key, value in budget.items()
        )

    if not valid_cases(design.candidate_cases) or not valid_budget(design.candidate_budget):
        issues.append("candidate comparison inputs are invalid")
    if design.baseline_cases is None or design.baseline_budget is None:
        issues.append("matched baseline is missing")
    elif not valid_cases(design.baseline_cases) or not valid_budget(design.baseline_budget):
        issues.append("baseline comparison inputs are invalid")
    else:
        if design.candidate_cases != design.baseline_cases:
            issues.append("candidate and baseline cases are not matched")
        if dict(design.candidate_budget) != dict(design.baseline_budget):
            issues.append("candidate and baseline budgets are not matched")
    required = frozenset(design.required_ablations)
    observed = frozenset(design.observed_ablations)
    if not all(isinstance(item, str) and item for item in required | observed):
        issues.append("ablation identifiers are invalid")
    missing_ablations = required - observed
    if missing_ablations:
        issues.append("missing ablations: " + ", ".join(sorted(missing_ablations)))
    return ComparisonAssessment(not issues, tuple(issues))


@dataclass(frozen=True)
class TrustedEvaluatorAssessment:
    artifact_sha256: str
    evaluator_id: str
    work_order_id: str
    plan_sha256: str
    acceptance_sha256: str
    cycle_id: str
    candidate_id: str
    candidate_source_path: str
    candidate_source_sha256: str
    comparison: ComparisonAssessment
    holdout_integrity: bool | None
    _durable_proof: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._durable_proof is not _DURABLE_VERIFIER_PROOF:
            raise ValueError("evaluator assessment was not loaded from durable state")


@dataclass(frozen=True)
class TrustedCancellation:
    artifact_sha256: str
    work_order_id: str
    plan_sha256: str
    acceptance_sha256: str
    cycle_id: str
    candidate_id: str
    candidate_source_path: str
    candidate_source_sha256: str
    slot_id: str
    attempt_id: str
    cancellation_event_id: str
    reason_code: str
    cancelled_at: str
    evidence: tuple[tuple[str, str], ...]
    _durable_proof: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._durable_proof is not _DURABLE_VERIFIER_PROOF:
            raise ValueError("cancellation was not loaded from durable state")


@dataclass(frozen=True)
class PromotionDecision:
    acceptance_sha256: str
    verdict: PromotionVerdict
    reasons: tuple[str, ...]
    allowed_claim: str


def _decide_promotion_core(
    *,
    criteria: FrozenCriteria,
    observations: Mapping[str, bool | None],
    comparison: ComparisonAssessment,
    holdout_integrity: bool | None,
    proposed_required_criteria: Iterable[str] | None = None,
) -> PromotionDecision:
    """Legacy private helper retained only as a fail-closed compatibility shim."""
    del observations, comparison, holdout_integrity, proposed_required_criteria
    return PromotionDecision(
        criteria.acceptance_sha256,
        PromotionVerdict.INCONCLUSIVE,
        ("state_lookup_required",),
        "no promotion decision is supported without durable state lookup",
    )

    omitted = (
        frozenset()
        if proposed_required_criteria is None
        else softened_criteria(criteria, proposed_required_criteria)
    )
    observed_failures = sorted(
        criterion for criterion in criteria.required if observations.get(criterion) is False
    )
    if omitted:
        return PromotionDecision(
            criteria.acceptance_sha256,
            PromotionVerdict.REJECTED,
            ("attempted to soften frozen criteria: " + ", ".join(sorted(omitted)),),
            "candidate rejected under the frozen gate",
        )
    if holdout_integrity is False:
        return PromotionDecision(
            criteria.acceptance_sha256,
            PromotionVerdict.REJECTED,
            ("protected holdout integrity was violated",),
            "candidate rejected under the frozen gate",
        )
    if observed_failures:
        return PromotionDecision(
            criteria.acceptance_sha256,
            PromotionVerdict.REJECTED,
            ("observed frozen-criterion violations: " + ", ".join(observed_failures),),
            "candidate rejected under the frozen gate",
        )

    missing = sorted(
        criterion for criterion in criteria.required if observations.get(criterion) is not True
    )
    inconclusive_reasons: list[str] = []
    if missing:
        inconclusive_reasons.append("missing criterion evidence: " + ", ".join(missing))
    if not comparison.complete:
        inconclusive_reasons.extend(comparison.issues)
    if holdout_integrity is None:
        inconclusive_reasons.append("holdout integrity is unverified")
    if inconclusive_reasons:
        return PromotionDecision(
            criteria.acceptance_sha256,
            PromotionVerdict.INCONCLUSIVE,
            tuple(inconclusive_reasons),
            "no promotion decision is supported",
        )
    return PromotionDecision(
        criteria.acceptance_sha256,
        PromotionVerdict.ACCEPTED,
        ("all frozen criteria and protection checks passed",),
        "promotion is supported only for the evaluated scope",
    )


def decide_promotion(
    *,
    criteria: FrozenCriteria,
    observations: Mapping[str, bool | None],
    comparison: ComparisonAssessment,
    holdout_integrity: bool | None,
    proposed_required_criteria: Iterable[str] | None = None,
) -> PromotionDecision:
    """Refuse promotion semantics for caller-supplied observations and policy values."""
    del observations, comparison, holdout_integrity, proposed_required_criteria
    return PromotionDecision(
        criteria.acceptance_sha256,
        PromotionVerdict.INCONCLUSIVE,
        ("untrusted_observations",),
        "no promotion decision is supported from untrusted observations",
    )


def decide_verified_promotion(
    *,
    criteria: FrozenCriteria,
    verifier_observations: VerifierCriterionObservations,
    evaluator_assessment: TrustedEvaluatorAssessment,
    work_order_id: str,
    candidate_id: str,
    cycle_id: str,
    proposed_required_criteria: Iterable[str] | None = None,
) -> PromotionDecision:
    """Refuse DTO-based authority; durable state is the promotion trust boundary."""
    del (
        verifier_observations, evaluator_assessment, work_order_id, candidate_id,
        cycle_id, proposed_required_criteria,
    )
    return PromotionDecision(
        criteria.acceptance_sha256,
        PromotionVerdict.INCONCLUSIVE,
        ("state_lookup_required",),
        "no promotion decision is supported without durable state lookup",
    )
