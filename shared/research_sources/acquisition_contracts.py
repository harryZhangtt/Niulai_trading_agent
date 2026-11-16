"""Closed, provider-free contracts for acquisition runtime integration.

These structures freeze the vocabulary shared by the runner, controller, HostWeb,
reviewer, and checker.  They validate structural integrity only; they do not call a
provider or establish source quality, semantic support, or investment alpha.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


CONTRACT_VERSION = "acquisition-contracts-1"
TAXONOMY_VERSION = "acquisition-failures-1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}")
_SHA256 = re.compile(r"[a-f0-9]{64}")


class ContractError(ValueError):
    """A closed acquisition contract was structurally invalid."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def _identifier(value: str, code: str) -> str:
    _require(isinstance(value, str) and _ID.fullmatch(value) is not None, code)
    return value


def _sha256(value: str, code: str) -> str:
    _require(isinstance(value, str) and _SHA256.fullmatch(value) is not None, code)
    return value


@dataclass(frozen=True)
class RunIdentity:
    experiment_id: str
    execution_id: str
    trace_id: str

    def __post_init__(self) -> None:
        for field in fields(self):
            _identifier(getattr(self, field.name), "ACQ_CONTRACT_RUN_ID")


@dataclass(frozen=True)
class DispatchIdentity:
    operation_id: str
    attempt_id: str
    dispatch_id: str

    def __post_init__(self) -> None:
        for field in fields(self):
            _identifier(getattr(self, field.name), "ACQ_CONTRACT_DISPATCH_ID")


@dataclass(frozen=True)
class AcquisitionIdentity:
    run: RunIdentity
    dispatch: DispatchIdentity

    def __post_init__(self) -> None:
        _require(isinstance(self.run, RunIdentity) and isinstance(self.dispatch, DispatchIdentity),
                 "ACQ_CONTRACT_IDENTITY")


class FailureClass(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    POLICY_VALIDATION = "policy_validation"
    REPRESENTATION = "representation_failure"
    DEADLINE_BEFORE_DISPATCH = "deadline_before_dispatch"
    DEADLINE_AFTER_POSSIBLE_DISPATCH = "deadline_after_possible_dispatch"
    CIRCUIT_OPEN = "circuit_open"
    UNKNOWN_OUTCOME = "unknown_outcome"


class FallbackEligibility(str, Enum):
    NEVER = "never"
    SEALED_ALTERNATE = "sealed_alternate"
    SEALED_ALTERNATE_IF_PREDECLARED = "sealed_alternate_if_predeclared"


class FailureCode(str, Enum):
    HOST_WEB_BODY_TOO_LARGE = "HOST_WEB_BODY_TOO_LARGE"
    HOST_WEB_SOURCE_INACCESSIBLE = "HOST_WEB_SOURCE_INACCESSIBLE"
    HOST_WEB_BODY_UNPARSEABLE = "HOST_WEB_BODY_UNPARSEABLE"
    SOURCE_HTTP_401 = "SOURCE_HTTP_401"
    SOURCE_HTTP_403 = "SOURCE_HTTP_403"
    SOURCE_HTTP_404 = "SOURCE_HTTP_404"
    SOURCE_HTTP_429 = "SOURCE_HTTP_429"
    SOURCE_HTTP_503 = "SOURCE_HTTP_503"
    NATIVE_TRANSPORT_FAILED = "NATIVE_TRANSPORT_FAILED"
    HOST_WEB_DEADLINE_BEFORE_DISPATCH = "HOST_WEB_DEADLINE_BEFORE_DISPATCH"
    HOST_WEB_DEADLINE = "HOST_WEB_DEADLINE"
    NATIVE_TRANSPORT_CIRCUIT_OPEN = "NATIVE_TRANSPORT_CIRCUIT_OPEN"
    HOST_WEB_RESULT_UNKNOWN = "HOST_WEB_RESULT_UNKNOWN"
    HOST_WEB_UNKNOWN_OUTCOME = "HOST_WEB_UNKNOWN_OUTCOME"
    HOST_WEB_FUTURE_EXPOSURE = "HOST_WEB_FUTURE_EXPOSURE"
    HOST_WEB_SOURCE_CHANGED = "HOST_WEB_SOURCE_CHANGED"
    ACQ_PERMANENT_FAILURE = "ACQ_PERMANENT_FAILURE"


@dataclass(frozen=True)
class FailureClassification:
    taxonomy_version: str
    code: FailureCode
    failure_class: FailureClass
    fallback: FallbackEligibility

    def __post_init__(self) -> None:
        _require(self.taxonomy_version == TAXONOMY_VERSION, "ACQ_FAILURE_TAXONOMY_VERSION")
        _require(isinstance(self.code, FailureCode) and isinstance(self.failure_class, FailureClass)
                 and isinstance(self.fallback, FallbackEligibility), "ACQ_FAILURE_CLASSIFICATION")


_FAILURES = {
    FailureCode.HOST_WEB_BODY_TOO_LARGE: (FailureClass.REPRESENTATION, FallbackEligibility.SEALED_ALTERNATE),
    FailureCode.HOST_WEB_SOURCE_INACCESSIBLE: (FailureClass.REPRESENTATION, FallbackEligibility.SEALED_ALTERNATE),
    FailureCode.HOST_WEB_BODY_UNPARSEABLE: (FailureClass.REPRESENTATION, FallbackEligibility.SEALED_ALTERNATE_IF_PREDECLARED),
    FailureCode.SOURCE_HTTP_401: (FailureClass.POLICY_VALIDATION, FallbackEligibility.NEVER),
    FailureCode.SOURCE_HTTP_403: (FailureClass.POLICY_VALIDATION, FallbackEligibility.NEVER),
    FailureCode.SOURCE_HTTP_404: (FailureClass.POLICY_VALIDATION, FallbackEligibility.NEVER),
    FailureCode.SOURCE_HTTP_429: (FailureClass.TRANSIENT, FallbackEligibility.NEVER),
    FailureCode.SOURCE_HTTP_503: (FailureClass.TRANSIENT, FallbackEligibility.NEVER),
    FailureCode.NATIVE_TRANSPORT_FAILED: (FailureClass.TRANSIENT, FallbackEligibility.NEVER),
    FailureCode.HOST_WEB_DEADLINE_BEFORE_DISPATCH: (FailureClass.DEADLINE_BEFORE_DISPATCH, FallbackEligibility.NEVER),
    FailureCode.HOST_WEB_DEADLINE: (FailureClass.DEADLINE_AFTER_POSSIBLE_DISPATCH, FallbackEligibility.NEVER),
    FailureCode.NATIVE_TRANSPORT_CIRCUIT_OPEN: (FailureClass.CIRCUIT_OPEN, FallbackEligibility.NEVER),
    FailureCode.HOST_WEB_RESULT_UNKNOWN: (FailureClass.UNKNOWN_OUTCOME, FallbackEligibility.NEVER),
    FailureCode.HOST_WEB_UNKNOWN_OUTCOME: (FailureClass.UNKNOWN_OUTCOME, FallbackEligibility.NEVER),
    FailureCode.HOST_WEB_FUTURE_EXPOSURE: (FailureClass.POLICY_VALIDATION, FallbackEligibility.NEVER),
    FailureCode.HOST_WEB_SOURCE_CHANGED: (FailureClass.POLICY_VALIDATION, FallbackEligibility.NEVER),
    FailureCode.ACQ_PERMANENT_FAILURE: (FailureClass.PERMANENT, FallbackEligibility.NEVER),
}


def classify_failure(code: FailureCode | str) -> FailureClassification:
    """Return the one closed classification for a structured failure code."""
    try:
        typed_code = code if isinstance(code, FailureCode) else FailureCode(code)
    except (TypeError, ValueError) as error:
        raise ContractError("ACQ_FAILURE_CODE_UNKNOWN") from error
    failure_class, fallback = _FAILURES[typed_code]
    return FailureClassification(TAXONOMY_VERSION, typed_code, failure_class, fallback)


def fallback_allowed(code: FailureCode | str, *, unparseable_predeclared: bool = False) -> bool:
    eligibility = classify_failure(code).fallback
    return eligibility is FallbackEligibility.SEALED_ALTERNATE or (
        eligibility is FallbackEligibility.SEALED_ALTERNATE_IF_PREDECLARED
        and unparseable_predeclared is True
    )


@dataclass(frozen=True)
class ExactArguments:
    """Canonical JSON bytes, immutable and suitable for exact dispatch comparison."""

    canonical_json: bytes

    def __post_init__(self) -> None:
        _require(isinstance(self.canonical_json, bytes) and 0 < len(self.canonical_json) <= 16384,
                 "ACQ_EXACT_ARGUMENTS")
        try:
            decoded = json.loads(self.canonical_json)
            canonical = json.dumps(decoded, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False).encode()
        except (TypeError, ValueError, UnicodeDecodeError) as error:
            raise ContractError("ACQ_EXACT_ARGUMENTS") from error
        _require(isinstance(decoded, dict) and canonical == self.canonical_json, "ACQ_EXACT_ARGUMENTS")

    @classmethod
    def from_mapping(cls, arguments: Mapping[str, Any]) -> "ExactArguments":
        _require(isinstance(arguments, Mapping), "ACQ_EXACT_ARGUMENTS")
        try:
            encoded = json.dumps(dict(arguments), sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=False, allow_nan=False).encode()
        except (TypeError, ValueError) as error:
            raise ContractError("ACQ_EXACT_ARGUMENTS") from error
        return cls(encoded)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.canonical_json)


class RepresentationKind(str, Enum):
    PDF = "pdf"
    HTML = "html"


class AlternateRelationship(str, Enum):
    SEMANTICALLY_EQUIVALENT_REPRESENTATION = "semantically_equivalent_representation"


@dataclass(frozen=True)
class AlternateDescriptor:
    representation_kind: RepresentationKind
    exact_arguments: ExactArguments
    source_role: str
    required_capability: str
    required_access_level: str
    canonical_disclosure_id: str
    relationship_to_primary: AlternateRelationship
    semantic_equivalence_rationale: str
    permitted_trigger_codes: frozenset[FailureCode]
    budget_cost: int

    def __post_init__(self) -> None:
        _require(isinstance(self.representation_kind, RepresentationKind)
                 and isinstance(self.exact_arguments, ExactArguments)
                 and isinstance(self.relationship_to_primary, AlternateRelationship),
                 "ACQ_ALTERNATE_DESCRIPTOR")
        for value in (self.source_role, self.required_capability, self.required_access_level,
                      self.semantic_equivalence_rationale):
            _require(isinstance(value, str) and 0 < len(value) <= 1800, "ACQ_ALTERNATE_DESCRIPTOR")
        _identifier(self.canonical_disclosure_id, "ACQ_ALTERNATE_DISCLOSURE_ID")
        _require(type(self.permitted_trigger_codes) is frozenset and bool(self.permitted_trigger_codes)
                 and all(isinstance(code, FailureCode) for code in self.permitted_trigger_codes),
                 "ACQ_ALTERNATE_TRIGGER_CODES")
        _require(all(classify_failure(code).fallback is not FallbackEligibility.NEVER
                     for code in self.permitted_trigger_codes), "ACQ_ALTERNATE_TRIGGER_CODES")
        _require(type(self.budget_cost) is int and self.budget_cost > 0, "ACQ_ALTERNATE_BUDGET")


class DispatchState(str, Enum):
    PREPARED = "prepared"
    CLAIMED = "claimed"
    DEFINITELY_NOT_DISPATCHED = "definitely_not_dispatched"
    INVOCATION_STARTED = "invocation_started"
    CAPTURED = "captured"
    POSSIBLY_DISPATCHED = "possibly_dispatched"


_DISPATCH_TRANSITIONS = {
    DispatchState.PREPARED: frozenset({DispatchState.CLAIMED}),
    DispatchState.CLAIMED: frozenset({DispatchState.DEFINITELY_NOT_DISPATCHED, DispatchState.INVOCATION_STARTED}),
    DispatchState.DEFINITELY_NOT_DISPATCHED: frozenset({DispatchState.CLAIMED}),
    DispatchState.INVOCATION_STARTED: frozenset({DispatchState.CAPTURED, DispatchState.POSSIBLY_DISPATCHED}),
    DispatchState.POSSIBLY_DISPATCHED: frozenset({DispatchState.CAPTURED}),
    DispatchState.CAPTURED: frozenset(),
}


@dataclass(frozen=True)
class DispatchEvent:
    dispatch_id: str
    sequence: int
    state: DispatchState
    evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.dispatch_id, "ACQ_DISPATCH_EVENT_ID")
        _require(type(self.sequence) is int and self.sequence >= 0 and isinstance(self.state, DispatchState),
                 "ACQ_DISPATCH_EVENT")
        if self.evidence_sha256 is not None:
            _sha256(self.evidence_sha256, "ACQ_DISPATCH_EVIDENCE")


def validate_dispatch_history(history: Sequence[DispatchEvent]) -> tuple[DispatchEvent, ...]:
    """Validate an append-only journal snapshot and return an immutable copy."""
    rows = tuple(history)
    _require(bool(rows) and all(isinstance(row, DispatchEvent) for row in rows), "ACQ_DISPATCH_HISTORY")
    _require(rows[0].sequence == 0 and rows[0].state is DispatchState.PREPARED,
             "ACQ_DISPATCH_HISTORY_INITIAL")
    dispatch_id = rows[0].dispatch_id
    for previous, current in zip(rows, rows[1:]):
        _require(current.dispatch_id == dispatch_id and current.sequence == previous.sequence + 1,
                 "ACQ_DISPATCH_HISTORY_APPEND_ONLY")
        _require(current.state in _DISPATCH_TRANSITIONS[previous.state], "ACQ_DISPATCH_TRANSITION")
        if current.state is DispatchState.DEFINITELY_NOT_DISPATCHED or (
                current.state is DispatchState.CAPTURED
                and previous.state is DispatchState.POSSIBLY_DISPATCHED):
            _require(current.evidence_sha256 is not None, "ACQ_DISPATCH_EVIDENCE_REQUIRED")
        if previous.state is DispatchState.DEFINITELY_NOT_DISPATCHED:
            _require(previous.evidence_sha256 is not None, "ACQ_DISPATCH_EVIDENCE_REQUIRED")
    return rows


def append_dispatch_event(history: Sequence[DispatchEvent], state: DispatchState, *,
                          evidence_sha256: str | None = None) -> tuple[DispatchEvent, ...]:
    rows = validate_dispatch_history(history)
    candidate = DispatchEvent(rows[-1].dispatch_id, rows[-1].sequence + 1, state, evidence_sha256)
    return validate_dispatch_history((*rows, candidate))


class ReviewerDisposition(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class ReviewerDecision:
    run_identity: RunIdentity
    assessment_id: str
    unit_id: str
    reviewer_id: str
    assessment_author_id: str
    live_operator_id: str
    screened_source_sha256: str
    assessment_sha256: str
    unit_sha256: str
    disposition: ReviewerDisposition
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.run_identity, RunIdentity) and isinstance(self.disposition, ReviewerDisposition),
                 "ACQ_REVIEW_DECISION")
        for value in (self.assessment_id, self.unit_id, self.reviewer_id,
                      self.assessment_author_id, self.live_operator_id):
            _identifier(value, "ACQ_REVIEW_ID")
        _require(self.reviewer_id not in {self.assessment_author_id, self.live_operator_id},
                 "ACQ_REVIEWER_NOT_INDEPENDENT")
        for value in (self.screened_source_sha256, self.assessment_sha256, self.unit_sha256):
            _sha256(value, "ACQ_REVIEW_HASH")
        _require(type(self.reason_codes) is tuple and bool(self.reason_codes)
                 and all(isinstance(value, str) and _ID.fullmatch(value)
                         for value in self.reason_codes), "ACQ_REVIEW_REASONS")


class GateDisposition(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class LedgerGate:
    name: str
    disposition: GateDisposition
    reason_code: str

    def __post_init__(self) -> None:
        _identifier(self.name, "ACQ_LEDGER_GATE")
        _identifier(self.reason_code, "ACQ_LEDGER_GATE_REASON")
        _require(isinstance(self.disposition, GateDisposition), "ACQ_LEDGER_GATE")


@dataclass(frozen=True)
class CrossLedgerVerdict:
    run_identity: RunIdentity
    disposition: GateDisposition
    gates: tuple[LedgerGate, ...]
    logical_operations: int
    reserved_provider_items: int
    actual_dispatches: int
    complete_chains: int
    credited_units: int

    def __post_init__(self) -> None:
        _require(isinstance(self.run_identity, RunIdentity) and isinstance(self.disposition, GateDisposition)
                 and type(self.gates) is tuple and bool(self.gates)
                 and all(isinstance(gate, LedgerGate) for gate in self.gates), "ACQ_LEDGER_VERDICT")
        _require(len({gate.name for gate in self.gates}) == len(self.gates), "ACQ_LEDGER_GATE_DUPLICATE")
        counts = (self.logical_operations, self.reserved_provider_items, self.actual_dispatches,
                  self.complete_chains, self.credited_units)
        _require(all(type(value) is int and value >= 0 for value in counts), "ACQ_LEDGER_COUNTS")
        if self.disposition is GateDisposition.PASS:
            _require(all(gate.disposition is GateDisposition.PASS for gate in self.gates),
                     "ACQ_LEDGER_PASS_CONFLICT")
            _require(self.complete_chains == self.credited_units and self.complete_chains > 0,
                     "ACQ_LEDGER_CREDIT_CONFLICT")
        elif self.disposition is GateDisposition.FAIL:
            _require(any(gate.disposition is GateDisposition.FAIL for gate in self.gates),
                     "ACQ_LEDGER_FAIL_CONFLICT")
        else:
            _require(not any(gate.disposition is GateDisposition.FAIL for gate in self.gates)
                     and any(gate.disposition is GateDisposition.INCONCLUSIVE for gate in self.gates),
                     "ACQ_LEDGER_INCONCLUSIVE_CONFLICT")


@dataclass(frozen=True)
class EffectiveConfigInputs:
    """Hashes of every input that must be sealed into the effective config."""

    runner_sha256: str
    driver_sha256: str
    controller_sha256: str
    host_web_sha256: str
    cache_store_sha256: str
    taxonomy_sha256: str
    alternate_policy_sha256: str
    evidence_schemas_sha256: str
    checker_sha256: str
    projection_sha256: str
    backend_model_config_sha256: str
    runtime_interpreter_sha256: str
    case_packet_sha256: str
    budgets_deadlines_sha256: str
    retention_gc_policy_sha256: str
    rollback_target_sha256: str
    acceptance_policy_sha256: str
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require(self.contract_version == CONTRACT_VERSION, "ACQ_EFFECTIVE_CONFIG_VERSION")
        for field in fields(self):
            if field.name != "contract_version":
                _sha256(getattr(self, field.name), "ACQ_EFFECTIVE_CONFIG_INPUT")

# Information-yield v2 checked-case request contracts.  These values contain
# references only; acquisition remains the authority that reopens and checks
# every referenced ledger before issuing a sanitized matched-case bundle.
EIY_CHECKED_CASE_VERSION = "information-yield-checked-case-request-2"


def _artifact_ref(value: Mapping[str, Any], code: str) -> dict[str, str]:
    _require(isinstance(value, Mapping) and set(value) == {"path", "sha256"}, code)
    path = value.get("path")
    _require(isinstance(path, str) and 0 < len(path) <= 1024 and ".." not in path.split("/"), code)
    return {"path": path, "sha256": _sha256(value.get("sha256"), code)}


@dataclass(frozen=True)
class CheckedEiyArmInputs:
    driver_ref: Mapping[str, str]
    dispatch_refs: tuple[Mapping[str, str], ...]
    proposal_refs: tuple[Mapping[str, str], ...]
    review_refs: tuple[Mapping[str, str], ...]
    reconciliation_ref: Mapping[str, str]
    host_invocation_refs: tuple[Mapping[str, str], ...]
    host_profile_ref: Mapping[str, str]
    credential_readiness_ref: Mapping[str, str]
    config_ref: Mapping[str, str]
    admission_ref: Mapping[str, str]

    def __post_init__(self) -> None:
        for name in ("driver_ref", "reconciliation_ref", "host_profile_ref",
                     "credential_readiness_ref", "config_ref", "admission_ref"):
            object.__setattr__(self, name, _artifact_ref(getattr(self, name), "ACQ_EIY_ARM_REF"))
        for name in ("dispatch_refs", "proposal_refs", "review_refs", "host_invocation_refs"):
            rows = getattr(self, name)
            _require(type(rows) is tuple and len(rows) <= 64, "ACQ_EIY_ARM_REFS")
            normalized = tuple(_artifact_ref(row, "ACQ_EIY_ARM_REF") for row in rows)
            _require(len({row["sha256"] for row in normalized}) == len(normalized),
                     "ACQ_EIY_ARM_REFS_DUPLICATE")
            object.__setattr__(self, name, normalized)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CheckedEiyArmInputs":
        keys = {field.name for field in fields(cls)}
        _require(isinstance(value, Mapping) and set(value) == keys, "ACQ_EIY_ARM_FIELDS")
        return cls(**{name: (tuple(value[name]) if name.endswith("_refs") else value[name])
                      for name in keys})

    def to_dict(self) -> dict[str, Any]:
        return {field.name: (list(getattr(self, field.name))
                             if field.name.endswith("_refs") else dict(getattr(self, field.name)))
                for field in fields(self)}


@dataclass(frozen=True)
class CheckedEiyCaseRequest:
    schema_version: str
    evaluation_id: str
    case_contract_ref: Mapping[str, str]
    metric_policy_ref: Mapping[str, str]
    case_roster_ref: Mapping[str, str]
    allocation_ref: Mapping[str, str]
    baseline_ref: Mapping[str, str]
    reference_set_ref: Mapping[str, str]
    required_fields_ref: Mapping[str, str]
    freshness_targets_ref: Mapping[str, str]
    financial_element_roster_ref: Mapping[str, str]
    custody_ref: Mapping[str, str]
    arms: Mapping[str, CheckedEiyArmInputs]

    def __post_init__(self) -> None:
        _require(self.schema_version == EIY_CHECKED_CASE_VERSION, "ACQ_EIY_REQUEST_VERSION")
        _identifier(self.evaluation_id, "ACQ_EIY_EVALUATION_ID")
        for field in fields(self):
            if field.name.endswith("_ref"):
                object.__setattr__(self, field.name,
                                   _artifact_ref(getattr(self, field.name), "ACQ_EIY_REQUEST_REF"))
        _require(isinstance(self.arms, Mapping) and set(self.arms) == {"B0", "F"},
                 "ACQ_EIY_REQUEST_ARMS")
        normalized = {name: (row if isinstance(row, CheckedEiyArmInputs)
                             else CheckedEiyArmInputs.from_mapping(row))
                      for name, row in self.arms.items()}
        object.__setattr__(self, "arms", normalized)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CheckedEiyCaseRequest":
        keys = {field.name for field in fields(cls)}
        _require(isinstance(value, Mapping) and set(value) == keys, "ACQ_EIY_REQUEST_FIELDS")
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        result = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name == "arms":
                result[field.name] = {name: row.to_dict() for name, row in value.items()}
            elif field.name.endswith("_ref"):
                result[field.name] = dict(value)
            else:
                result[field.name] = value
        return result

# Information-yield v3 evaluation-time checker contracts. V1/v2 persisted
# semantic bundles are deliberately not accepted by this boundary.
EIY_V3_CHECK_REQUEST_VERSION = "information-yield-check-request-3"
EIY_V3_ARM_MANIFEST_VERSION = "information-yield-arm-manifest-3"


@dataclass(frozen=True)
class EiyV3ArmManifestRef:
    arm: str
    manifest_ref: Mapping[str, str]

    def __post_init__(self) -> None:
        _require(self.arm in {"B0", "F"}, "ACQ_EIY_V3_ARM")
        object.__setattr__(self, "manifest_ref",
                           _artifact_ref(self.manifest_ref, "ACQ_EIY_V3_ARM_REF"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EiyV3ArmManifestRef":
        _require(isinstance(value, Mapping) and set(value) == {"arm", "manifest_ref"},
                 "ACQ_EIY_V3_ARM_FIELDS")
        return cls(value["arm"], value["manifest_ref"])

    def to_dict(self) -> dict[str, Any]:
        return {"arm": self.arm, "manifest_ref": dict(self.manifest_ref)}


@dataclass(frozen=True)
class CheckedEiyV3Request:
    schema_version: str
    evaluation_id: str
    mode: str
    metric_policy_ref: Mapping[str, str]
    case_contract_ref: Mapping[str, str]
    case_roster_ref: Mapping[str, str]
    allocation_ref: Mapping[str, str]
    custody_ref: Mapping[str, str]
    baseline_ref: Mapping[str, str]
    reference_set_ref: Mapping[str, str]
    required_fields_ref: Mapping[str, str]
    freshness_targets_ref: Mapping[str, str]
    financial_element_roster_ref: Mapping[str, str]
    source_closure_ref: Mapping[str, str]
    arms: Mapping[str, EiyV3ArmManifestRef]
    request_sha256: str

    def __post_init__(self) -> None:
        _require(self.schema_version == EIY_V3_CHECK_REQUEST_VERSION,
                 "ACQ_EIY_V3_REQUEST_VERSION")
        _identifier(self.evaluation_id, "ACQ_EIY_V3_EVALUATION_ID")
        _require(self.mode in {"evaluation", "now_diagnostic"}, "ACQ_EIY_V3_MODE")
        for field in fields(self):
            if field.name.endswith("_ref"):
                object.__setattr__(self, field.name,
                                   _artifact_ref(getattr(self, field.name),
                                                 "ACQ_EIY_V3_REQUEST_REF"))
        _require(isinstance(self.arms, Mapping) and set(self.arms) == {"B0", "F"},
                 "ACQ_EIY_V3_REQUEST_ARMS")
        normalized = {name: (row if isinstance(row, EiyV3ArmManifestRef)
                             else EiyV3ArmManifestRef.from_mapping(row))
                      for name, row in self.arms.items()}
        _require(all(normalized[name].arm == name for name in ("B0", "F")),
                 "ACQ_EIY_V3_REQUEST_ARMS")
        object.__setattr__(self, "arms", normalized)
        unsigned = self.to_dict(include_digest=False)
        expected = hashlib.sha256(json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        _require(self.request_sha256 == expected, "ACQ_EIY_V3_REQUEST_DIGEST")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CheckedEiyV3Request":
        keys = {field.name for field in fields(cls)}
        _require(isinstance(value, Mapping) and set(value) == keys,
                 "ACQ_EIY_V3_REQUEST_FIELDS")
        return cls(**dict(value))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for field in fields(self):
            if field.name == "request_sha256" and not include_digest:
                continue
            value = getattr(self, field.name)
            if field.name == "arms":
                result[field.name] = {name: row.to_dict() for name, row in value.items()}
            elif field.name.endswith("_ref"):
                result[field.name] = dict(value)
            else:
                result[field.name] = value
        return result

EIY_V4_MANIFEST_VERSION = "information-yield-evaluation-manifest-4"
EIY_V4_CUSTODY_VERSION = "information-yield-evaluation-custody-4"


@dataclass(frozen=True)
class CheckedEiyEvaluationManifestV4:
    schema_version: str
    evaluation_custody_ref: Mapping[str, str]
    manifest_sha256: str

    def __post_init__(self) -> None:
        _require(self.schema_version == EIY_V4_MANIFEST_VERSION,
                 "ACQ_EIY_V4_MANIFEST_VERSION")
        object.__setattr__(self, "evaluation_custody_ref",
                           _artifact_ref(self.evaluation_custody_ref,
                                         "ACQ_EIY_V4_CUSTODY_REF"))
        unsigned = {"schema_version": self.schema_version,
                    "evaluation_custody_ref": dict(self.evaluation_custody_ref)}
        expected = hashlib.sha256(json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        _require(self.manifest_sha256 == expected, "ACQ_EIY_V4_MANIFEST_DIGEST")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CheckedEiyEvaluationManifestV4":
        _require(isinstance(value, Mapping)
                 and set(value) == {"schema_version", "evaluation_custody_ref",
                                    "manifest_sha256"},
                 "ACQ_EIY_V4_MANIFEST_FIELDS")
        return cls(**dict(value))
