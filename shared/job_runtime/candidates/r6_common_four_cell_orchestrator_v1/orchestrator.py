"""Disabled common four-cell admission orchestrator over sealed no-effect fixtures."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from .authority import verify_authority
from .contracts import (
    CELL_ORDER, CELL_PLANS, DESTINATION_IDS, P0_ARGUMENT_NAMES, STATUS,
    ContractError, require, sha256_json, validate_block_result,
    validate_evaluation_handoff, validate_p0_handoff, validate_provider_result,
)
from .ports import ClaudeFixturePort, CodexFixturePort

@dataclass(frozen=True)
class DestinationSnapshot:
    """Typed pre-effect destination observation; contains identifiers, never paths."""
    occupied_destination_ids: frozenset[str]

    def __post_init__(self) -> None:
        require(type(self.occupied_destination_ids) is frozenset, "DESTINATION_SNAPSHOT_TYPE")
        require(all(type(item) is str for item in self.occupied_destination_ids), "DESTINATION_ID_TYPE")

    @classmethod
    def empty(cls) -> "DestinationSnapshot":
        return cls(frozenset())


def _plan(item: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(("cell_id", "order_index", "provider_port", "blind_addon_label", "checks_enabled", "destination_id"), item))


def _preflight(snapshot: DestinationSnapshot) -> None:
    require(type(snapshot) is DestinationSnapshot, "DESTINATION_SNAPSHOT_INJECTION")
    require(len(DESTINATION_IDS) == len(set(DESTINATION_IDS)), "DESTINATION_PLAN_DUPLICATE")
    require(not set(DESTINATION_IDS).intersection(snapshot.occupied_destination_ids), "DESTINATION_COLLISION")


def _p0_handoff(plan: Mapping[str, Any], admission: Mapping[str, Any], pin: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = admission["p0_payload"]
    arguments = {
        "cell_id": plan["cell_id"],
        "blind_addon_label": plan["blind_addon_label"],
        "checks_enabled": plan["checks_enabled"],
        "job_id": payload["job_id"],
        "slot_id": payload["slot_id"],
        "attempt_id": payload["attempt_id"],
        "operation_id": payload["operation_id"],
        "prompt_binding_sha256": payload["prompt_binding_sha256"],
        "raw_sha256": payload["raw_sha256"],
        "publication_artifact_sha256": payload["publication_artifact_sha256"],
        "research_material_sha256": payload["research_material_sha256"],
        "terminal_state": payload["terminal_state"],
        "source_cutoff_sha256": payload["source_cutoff_sha256"],
    }
    value = {
        "version": 1,
        "candidate_status": STATUS,
        "target_package": "shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1",
        "target_api": "execute",
        "target_pin": copy.deepcopy(pin),
        "cell_id": plan["cell_id"],
        "order_index": plan["order_index"],
        "provider_port": plan["provider_port"],
        "required_argument_names": list(P0_ARGUMENT_NAMES),
        "argument_values": arguments,
        "admission_receipt_sha256": sha256_json(admission),
        "effects_executed": False,
    }
    validate_p0_handoff(value)
    return value


def _evaluation_handoff(handoffs: list[Mapping[str, Any]], pin: Mapping[str, Any]) -> Mapping[str, Any]:
    value = {
        "version": 1,
        "candidate_status": STATUS,
        "target_package": "shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1",
        "target_api": "execute_block",
        "target_pin": copy.deepcopy(pin),
        "cell_order": list(CELL_ORDER),
        "p0_handoff_sha256": [sha256_json(item) for item in handoffs],
        "completed_cell_count": len(handoffs),
        "all_four_present": len(handoffs) == 4,
        "partial_comparison": False,
        "countable": False,
        "effects_executed": False,
    }
    validate_evaluation_handoff(value)
    return value


class FourCellFixtureOrchestrator:
    """One-shot fixture orchestrator; exact concrete ports prevent callback injection."""
    __slots__ = ("_claude", "_codex", "_called")

    def __init__(self, claude_port: ClaudeFixturePort, codex_port: CodexFixturePort) -> None:
        require(type(claude_port) is ClaudeFixturePort, "ARBITRARY_CLAUDE_ADAPTER_FORBIDDEN")
        require(type(codex_port) is CodexFixturePort, "ARBITRARY_CODEX_ADAPTER_FORBIDDEN")
        self._claude = claude_port
        self._codex = codex_port
        self._called = False

    def run(self, destinations: DestinationSnapshot) -> Mapping[str, Any]:
        require(not self._called, "SECOND_BLOCK_CALL_FORBIDDEN")
        self._called = True
        authority = verify_authority()
        _preflight(destinations)
        grant = authority["grant"]
        admissions: list[Mapping[str, Any]] = []
        handoffs: list[Mapping[str, Any]] = []
        unknown_fence = None
        for item in CELL_PLANS:
            plan = _plan(item)
            port = self._claude if plan["provider_port"] == "CLAUDE" else self._codex
            admission = port.admit(copy.deepcopy(plan))
            validate_provider_result(admission, plan)
            admissions.append(admission)
            handoffs.append(_p0_handoff(plan, admission, grant["successor_pins"]["p0_attempt_envelope"]))
            if admission["terminal_state"] == "UNKNOWN":
                unknown_fence = {
                    "terminal_cell_id": plan["cell_id"],
                    "terminal_state": "UNKNOWN",
                    "blocked_cell_ids": list(CELL_ORDER[len(admissions):]),
                    "replay_allowed": False,
                }
                break
            require(admission["terminal_state"] == "PASS", "NON_PASS_TERMINAL_FENCED")
        evaluation = _evaluation_handoff(handoffs, grant["successor_pins"]["evaluation_runner"])
        complete = len(admissions) == 4 and all(item["terminal_state"] == "PASS" for item in admissions)
        value = {
            "version": 1,
            "candidate_status": STATUS,
            "scope": "PROVIDER_FREE_FIXTURE_ONLY",
            "status": "FIXTURE_COMPLETE_NON_COUNTABLE" if complete else "UNKNOWN_FENCED_INCOMPLETE",
            "countable": False,
            "cell_order": list(CELL_ORDER),
            "completed_cell_count": len(admissions),
            "admissions": admissions,
            "p0_handoffs": handoffs,
            "evaluation_handoff": evaluation,
            "unknown_fence": unknown_fence,
            "partial_comparison": False,
            "effects_executed": False,
        }
        validate_block_result(value)
        return value


def default_run() -> Mapping[str, Any]:
    return {"candidate_status": STATUS, "status": "DISABLED_NO_SUCCESSOR_BINDINGS", "countable": False, "effects_executed": False}


__all__ = ["DestinationSnapshot", "FourCellFixtureOrchestrator", "default_run"]
