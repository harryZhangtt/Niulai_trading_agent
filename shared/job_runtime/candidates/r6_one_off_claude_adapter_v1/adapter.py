"""Provider-free fake Claude CLI adapter; contains no live provider surface."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from shared.job_runtime.candidates.r6_one_off_evidence_v1 import (
    execute_provider_free,
    materialize_provider_free_case,
)
from .contracts import (
    MODEL,
    ZERO_SHA256,
    canonical_bytes,
    no_effects,
    sha256_bytes,
    validate_stage_a_evidence,
    validate_stage_a_template,
)


@dataclass
class FakeClaudeBoundary:
    catalog: bytes = b"claude-opus-5-5\n"
    terminal: str = "exact"
    cleanup: str = "complete"
    membership_checks: int = 0
    inference_requests: int = 0

    def membership(self) -> bool:
        self.membership_checks += 1
        return self.catalog.decode("utf-8", "strict").splitlines().count(MODEL) == 1

    def infer(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.inference_requests += 1
        if self.terminal == "exact":
            return {
                "terminal": "exact",
                "cleanup": self.cleanup,
                "raw": b'{"type":"fake.completed"}\n',
            }
        return {
            "terminal": "truncated",
            "cleanup": self.cleanup,
            "raw": b'{"type":"fake.delta"',
        }


@dataclass(frozen=True)
class StageAResult:
    evidence: Dict[str, Any]
    shared_execution: Any


def _stopped(code: str, checks: int = 0) -> StageAResult:
    evidence = {
        "version": 1,
        "outcome": "STOP",
        "reason_code": code,
        "countable_observation": False,
        "definitely_not_submitted": True,
        "membership_check_count": checks,
        "admission_count": 0,
        "upstream_attempt_count": 0,
        "inference_count": 0,
        "retry_count": 0,
        "replay_count": 0,
        "provider_status_calls": 0,
        "reconstruction_dispatch": 0,
        "cleanup_complete": True,
        "atomic_publication_complete": False,
        "owner_private_evidence_preserved": False,
        "durable_unknown_evidence": False,
        "effects": no_effects(),
        "shared_evidence_sha256": ZERO_SHA256,
    }
    validate_stage_a_evidence(evidence)
    return StageAResult(evidence, None)


def execute_stage_a(
    workspace: Path,
    template: Mapping[str, Any],
    boundary: FakeClaudeBoundary,
    scenario: str = "nominal",
    historical_jobs: Sequence[str] = (),
    historical_nonces: Sequence[str] = (),
) -> StageAResult:
    """Run one synthetic case. Invalid preflight always stops before fake upstream."""
    try:
        validate_stage_a_template(template)
    except ValueError as error:
        return _stopped(str(error))
    if scenario in {
        "auth_stop", "account_stop", "cost_stop", "window_stop", "config_stop",
        "custody_stop", "secret_stop", "path_swap",
    }:
        return _stopped(scenario.upper())
    try:
        member = boundary.membership()
    except (UnicodeError, ValueError):
        return _stopped("CATALOG_MALFORMED", boundary.membership_checks)
    if not member:
        return _stopped("MODEL_MEMBERSHIP_INVALID", boundary.membership_checks)
    if scenario in {"catalog_stop", "model_stop"}:
        return _stopped(scenario.upper(), boundary.membership_checks)

    shared_scenario = (
        "post_admission_unknown"
        if scenario in {"post_admission_unknown", "cleanup_failure", "publication_failure"}
        else "nominal"
    )
    prepared = materialize_provider_free_case(
        Path(workspace), shared_scenario, historical_jobs, historical_nonces,
    )
    try:
        execution = execute_provider_free(
            prepared, boundary.infer, historical_jobs, historical_nonces,
        )
        decision = execution.evidence["decision"]
        if scenario in {"cleanup_failure", "publication_failure"}:
            decision = "UNKNOWN"
        counters = execution.evidence["counters"]
        evidence = {
            "version": 1,
            "outcome": decision,
            "reason_code": "FAKE_" + scenario.upper(),
            "countable_observation": False,
            "definitely_not_submitted": False,
            "membership_check_count": boundary.membership_checks,
            "admission_count": counters["admission"],
            "upstream_attempt_count": counters["upstream"],
            "inference_count": boundary.inference_requests,
            "retry_count": counters["retry"],
            "replay_count": counters["replay"],
            "provider_status_calls": counters["status_query"],
            "reconstruction_dispatch": counters["reconstruction_dispatch"],
            "cleanup_complete": scenario != "cleanup_failure",
            "atomic_publication_complete": decision == "PASS",
            "owner_private_evidence_preserved": True,
            "durable_unknown_evidence": decision == "UNKNOWN",
            "effects": no_effects(),
            "shared_evidence_sha256": sha256_bytes(canonical_bytes(execution.evidence)),
        }
        validate_stage_a_evidence(evidence, execution.evidence)
        return StageAResult(evidence, execution)
    finally:
        prepared.close()
