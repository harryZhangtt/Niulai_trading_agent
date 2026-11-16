from __future__ import annotations

import copy
import unittest

from shared.job_runtime.candidates.r6_common_four_cell_orchestrator_v1 import (
    STATUS, ClaudeFixturePort, CodexFixturePort, ContractError, DestinationSnapshot,
    FixtureProfile, FourCellFixtureOrchestrator, default_run,
)
from shared.job_runtime.candidates.r6_common_four_cell_orchestrator_v1.authority import (
    _GRANT, _ROOT, _verify_pinned_bytes, verify_authority,
)
from shared.job_runtime.candidates.r6_common_four_cell_orchestrator_v1.contracts import (
    CELL_ORDER, CELL_PLANS, validate_block_result, validate_provider_result,
)

class FakeAdapter:
    def __call__(self, _plan):
        raise AssertionError("must never run")

class OrchestratorTests(unittest.TestCase):
    def nominal(self):
        claude, codex = ClaudeFixturePort(), CodexFixturePort()
        runner = FourCellFixtureOrchestrator(claude, codex)
        return claude, codex, runner, runner.run(DestinationSnapshot.empty())

    def test_disabled_status_and_unresolved_build_time_pins(self):
        self.assertEqual(default_run(), {
            "candidate_status": STATUS, "status": "DISABLED_NO_SUCCESSOR_BINDINGS",
            "countable": False, "effects_executed": False,
        })
        authority = verify_authority()
        self.assertFalse(authority["grant"]["activation"])
        self.assertFalse(authority["review"]["authority_issued"])
        for pin in authority["grant"]["successor_pins"].values():
            self.assertIsNone(pin["sha256"])
            self.assertEqual(pin["status"], "UNRESOLVED_BUILD_TIME_PIN")

    def test_nominal_fixed_order_concurrency_one_and_exact_handoffs(self):
        claude, codex, _runner, result = self.nominal()
        self.assertEqual([item["cell_id"] for item in result["admissions"]], list(CELL_ORDER))
        self.assertEqual([item["order_index"] for item in result["admissions"]], [0, 1, 2, 3])
        self.assertEqual(claude.admission_count, 2)
        self.assertEqual(codex.admission_count, 2)
        self.assertEqual(max(claude.max_active, codex.max_active), 1)
        self.assertEqual(result["completed_cell_count"], 4)
        self.assertEqual(result["status"], "FIXTURE_COMPLETE_NON_COUNTABLE")
        self.assertFalse(result["countable"])
        self.assertFalse(result["partial_comparison"])
        self.assertFalse(result["effects_executed"])
        self.assertTrue(result["evaluation_handoff"]["all_four_present"])
        self.assertTrue(all(item["target_api"] == "execute" for item in result["p0_handoffs"]))

    def test_second_block_call_is_denied(self):
        runner = FourCellFixtureOrchestrator(ClaudeFixturePort(), CodexFixturePort())
        runner.run(DestinationSnapshot.empty())
        with self.assertRaisesRegex(ContractError, "SECOND_BLOCK_CALL_FORBIDDEN"):
            runner.run(DestinationSnapshot.empty())

    def test_order_drift_is_rejected(self):
        _claude, _codex, _runner, result = self.nominal()
        drift = copy.deepcopy(result)
        drift["cell_order"][0], drift["cell_order"][1] = drift["cell_order"][1], drift["cell_order"][0]
        with self.assertRaisesRegex(ContractError, "BLOCK_ORDER_DRIFT"):
            validate_block_result(drift)

    def test_grant_drift_is_rejected_by_source_pin(self):
        raw = bytearray((_ROOT / _GRANT.relative_path).read_bytes())
        raw[-1] = ord(" ")
        with self.assertRaisesRegex(ContractError, "PINNED_SOURCE_(SIZE|HASH)_DRIFT"):
            _verify_pinned_bytes(_GRANT, bytes(raw))

    def test_provider_swap_and_arbitrary_adapter_injection_are_rejected(self):
        claude, codex = ClaudeFixturePort(), CodexFixturePort()
        with self.assertRaisesRegex(ContractError, "ARBITRARY_CLAUDE_ADAPTER_FORBIDDEN"):
            FourCellFixtureOrchestrator(codex, codex)
        with self.assertRaisesRegex(ContractError, "ARBITRARY_CLAUDE_ADAPTER_FORBIDDEN"):
            FourCellFixtureOrchestrator(FakeAdapter(), codex)
        with self.assertRaisesRegex(ContractError, "ARBITRARY_CODEX_ADAPTER_FORBIDDEN"):
            FourCellFixtureOrchestrator(claude, FakeAdapter())
        self.assertEqual(claude.admission_count, 0)
        self.assertEqual(codex.admission_count, 0)

    def test_destination_collision_fails_before_any_admission(self):
        claude, codex = ClaudeFixturePort(), CodexFixturePort()
        runner = FourCellFixtureOrchestrator(claude, codex)
        collision = DestinationSnapshot(frozenset({"p0/R6DQ-C4A7095E"}))
        with self.assertRaisesRegex(ContractError, "DESTINATION_COLLISION"):
            runner.run(collision)
        self.assertEqual(claude.admission_count, 0)
        self.assertEqual(codex.admission_count, 0)

    def test_unknown_fences_remaining_cells_and_partial_block(self):
        claude = ClaudeFixturePort(FixtureProfile.UNKNOWN_FIRST)
        codex = CodexFixturePort()
        result = FourCellFixtureOrchestrator(claude, codex).run(DestinationSnapshot.empty())
        self.assertEqual(result["status"], "UNKNOWN_FENCED_INCOMPLETE")
        self.assertEqual(result["completed_cell_count"], 1)
        self.assertEqual(result["unknown_fence"]["blocked_cell_ids"], list(CELL_ORDER[1:]))
        self.assertFalse(result["unknown_fence"]["replay_allowed"])
        self.assertFalse(result["countable"])
        self.assertFalse(result["partial_comparison"])
        self.assertEqual(claude.admission_count, 1)
        self.assertEqual(codex.admission_count, 0)

    def test_replay_or_second_cell_admission_is_rejected(self):
        port = ClaudeFixturePort()
        plan = dict(zip(("cell_id", "order_index", "provider_port", "blind_addon_label", "checks_enabled", "destination_id"), CELL_PLANS[0]))
        port.admit(copy.deepcopy(plan))
        with self.assertRaisesRegex(ContractError, "SECOND_ADMISSION_FORBIDDEN"):
            port.admit(copy.deepcopy(plan))

    def test_effect_leakage_is_rejected(self):
        _claude, _codex, _runner, result = self.nominal()
        admission = copy.deepcopy(result["admissions"][0])
        admission["effect_evidence"]["network"] = True
        plan = dict(zip(("cell_id", "order_index", "provider_port", "blind_addon_label", "checks_enabled", "destination_id"), CELL_PLANS[0]))
        with self.assertRaisesRegex(ContractError, "EFFECT_LEAKAGE"):
            validate_provider_result(admission, plan)

if __name__ == "__main__":
    unittest.main()
