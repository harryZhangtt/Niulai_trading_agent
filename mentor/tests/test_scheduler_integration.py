"""Model-free atomic integration across contract, supervision, state and CLI."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mentor.scheduler import DurableSessionStore, StateError, WorkOrder
from mentor.scheduler import cli
from mentor.scheduler.reconciliation import ReconciliationError, reconcile_unknown
from mentor.scheduler.projection import (
    EvaluationSummary,
    GateSummary,
    ProjectionBuildError,
    build_projection,
)
from shared.job_runtime.engine import Engine
from mentor.scheduler.supervision import (
    ComparisonDesign,
    EvidenceSnapshot,
    FrozenCriteria,
    PromotionDecision,
    PromotionVerdict,
    canonical_action_fingerprint,
    check_matched_comparison,
    classify_progress,
    decide_promotion,
)

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


class SchedulerAtomicIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        parent = ROOT / "runtime" / "test-tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="scheduler-integration-", dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        (self.workspace / "plans").mkdir()
        (self.workspace / "evidence").mkdir()
        self.plan = self.workspace / "plans/plan.md"
        self.acceptance = self.workspace / "plans/acceptance.json"
        self.plan.write_text("# Synthetic frozen plan\n", encoding="utf-8")
        self.acceptance.write_text(
            '{"schema_version":1,"criteria":['
            '{"criterion_id":"schema","critical":false},'
            '{"criterion_id":"safety","critical":true}]}\n',
            encoding="utf-8",
        )
        self.at = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
        self.order = WorkOrder.from_json(json.dumps(self._payload()), self.workspace)
        self.store = DurableSessionStore(self.workspace, "runtime/logical-1", "mentor-owner")
        self.store.create(self.order, at=self.at)

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _progress_artifact(self, cycle_id: str, evidence_ids: list[str]) -> str:
        observations = []
        for evidence_id in evidence_ids:
            evidence_path = f"evidence/{cycle_id}-{evidence_id}.txt"
            evidence = self.workspace / evidence_path
            evidence.write_text(f"verified {evidence_id}\n", encoding="utf-8")
            observations.append({
                "evidence_id": evidence_id,
                "evidence_path": evidence_path,
                "sha256": self._digest(evidence),
            })
        artifact = {
            "schema_version": 1,
            "work_order_id": self.order.work_order_id,
            "plan_sha256": self.order.plan.sha256,
            "acceptance_sha256": self.order.acceptance.sha256,
            "cycle_id": cycle_id,
            "observations": observations,
        }
        relative = f"evidence/{cycle_id}-progress.json"
        (self.workspace / relative).write_text(json.dumps(artifact), encoding="utf-8")
        return relative

    def _payload(self) -> dict:
        return {
            "schema_version": 1,
            "work_order_id": "work-1",
            "logical_session": {
                "logical_session_id": "logical-1",
                "provider_thread_mode": "ephemeral_threads",
                "max_provider_threads": 4,
            },
            "plan": {"path": "plans/plan.md", "sha256": self._digest(self.plan)},
            "acceptance": {"path": "plans/acceptance.json", "sha256": self._digest(self.acceptance)},
            "execution": {
                "starts_at": "2026-11-04T09:00:00+00:00",
                "ends_at": "2026-11-04T12:00:00+00:00",
                "turn_timeout_seconds": 300,
                "max_turns": 6,
            },
            "supervision": {
                "max_no_progress_cycles": 2,
                "max_repeated_actions": 2,
                "max_interventions": 3,
            },
            "evidence_policy": {
                "record_all_variants": True,
                "max_variants": 4,
                "max_reused_evaluations": 1,
                "worker_holdout_access": False,
            },
            "completion": {
                "required_event_kinds": ["provider_thread", "cycle"],
                "require_no_pending_effects": True,
                "require_acceptance_hash_match": True,
            },
        }

    def _promotion(self):
        criteria = FrozenCriteria.from_work_order(self.order)
        comparison = check_matched_comparison(
            ComparisonDesign(
                candidate_cases=("case-a",),
                baseline_cases=("case-a",),
                candidate_budget={"tokens": 100},
                baseline_budget={"tokens": 100},
            )
        )
        return decide_promotion(
            criteria=criteria,
            observations={"schema": True, "safety": None},
            comparison=comparison,
            holdout_integrity=True,
        )

    def test_verified_progress_flows_to_ledger_projection_and_cli(self) -> None:
        self.store.record_provider_thread(
            self.order, provider="configured-model", thread_id="ephemeral-1", at=self.at
        )
        action = {"kind": "validate", "artifact": "synthetic-schema"}
        progress = classify_progress(
            EvidenceSnapshot(),
            EvidenceSnapshot(criteria_verified={"schema"}, validated_artifacts={"schema-report"}),
            action,
        )
        self.assertTrue(progress.delta.changed)
        head = self.store.record_cycle(
            self.order,
            cycle_id="cycle-1",
            variant_id="baseline",
            action_sha256=canonical_action_fingerprint(action),
            outcome="succeeded",
            verified_evidence_artifact_path=self._progress_artifact(
                "cycle-1", sorted(progress.delta.identifiers)
            ),
            at=self.at,
        )
        promotion = self._promotion()
        self.assertEqual(promotion.verdict, PromotionVerdict.INCONCLUSIVE)
        projection = build_projection(
            self.order,
            self.store,
            generated_at=self.at,
            scheduler_status="running",
            slot_id="slot-1",
            next_run_at=datetime(2026, 11, 4, 10, 15, tzinfo=UTC),
            gates=GateSummary(verified=1, failed=0, pending=1),
            evaluation=EvaluationSummary(
                baseline="matched",
                holdout="protected untouched",
            ),
            promotion=promotion,
        )
        state = self.workspace / "runtime/status.json"
        state.write_text(json.dumps(projection), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main([
                "--state", str(state), "--work-order-id", "work-1", "--json",
                "--at", self.at.isoformat(),
            ])
        self.assertEqual((code, err.getvalue()), (0, ""))
        rendered = json.loads(out.getvalue())
        item = rendered["work_orders"][0]
        self.assertEqual(item["task"]["gates"], {"verified": 1, "failed": 0, "pending": 1})
        self.assertEqual(item["budgets"]["cycles_used"], 1)
        self.assertEqual(item["evaluation"]["holdout"], "protected untouched")
        self.assertEqual(item["evaluation"]["promotion"], "inconclusive")
        self.assertTrue(rendered["read_only"])

    def test_projection_rejects_forged_state_and_unbound_promotion(self) -> None:
        promotion = self._promotion()
        common = {
            "generated_at": self.at,
            "scheduler_status": "waiting",
            "gates": GateSummary(verified=1, failed=0, pending=1),
            "evaluation": EvaluationSummary(baseline="matched", holdout="protected untouched"),
        }
        with self.assertRaisesRegex(ProjectionBuildError, "durable session store"):
            build_projection(self.order, {}, promotion=promotion, **common)
        with self.assertRaisesRegex(ProjectionBuildError, "does not bind"):
            build_projection(
                self.order,
                self.store,
                promotion=replace(promotion, acceptance_sha256="0" * 64),
                **common,
            )

    def test_projection_rejects_accepted_promotion_before_durable_completion(self) -> None:
        criteria = FrozenCriteria.from_work_order(self.order)
        accepted = PromotionDecision(
            criteria.acceptance_sha256,
            PromotionVerdict.ACCEPTED,
            ("synthetic accepted projection input",),
            "promotion is supported only for the evaluated scope",
        )
        self.assertEqual(accepted.verdict, PromotionVerdict.ACCEPTED)
        with self.assertRaisesRegex(ProjectionBuildError, "completed state"):
            build_projection(
                self.order,
                self.store,
                generated_at=self.at,
                scheduler_status="waiting",
                gates=GateSummary(verified=2, failed=0, pending=0),
                evaluation=EvaluationSummary(baseline="matched", holdout="protected evaluated"),
                promotion=accepted,
            )

    def test_existing_engine_claims_one_due_once_slot_and_records_one_cycle(self) -> None:
        job = {
            "id": "mentor-work-1",
            "enabled": True,
            "replay_safe": True,
            "schedule": {
                "kind": "once",
                "at": self.at.isoformat(),
                "grace_seconds": 600,
            },
        }

        def dispatch(_job, context):
            self.store.record_provider_thread(
                self.order,
                provider="synthetic-engine",
                thread_id=context["attempt_id"],
                at=self.at,
            )
            head = self.store.record_cycle(
                self.order,
                cycle_id=context["attempt_id"],
                variant_id="baseline",
                action_sha256="b" * 64,
                outcome="succeeded",
                verified_evidence_artifact_path=self._progress_artifact(
                    context["attempt_id"], ["engine-cycle-recorded"]
                ),
                at=self.at,
            )
            return {
                "status": "succeeded",
                "code": "MENTOR_CYCLE_RECORDED",
                "receipt": {
                    "work_order_id": self.order.work_order_id,
                    "logical_session_id": head["logical_session_id"],
                    "head_revision": head["revision"],
                },
            }

        engine = Engine(
            self.workspace / ".job-runtime/engine",
            [job],
            {"max_attempts": 2, "backoff_seconds": 1, "max_backoff_seconds": 2},
            dispatch,
            workspace_root=self.workspace,
            clock=lambda: self.at,
            max_workers=1,
        )
        first = engine.tick(self.at)
        second = engine.tick(self.at)
        self.assertEqual(first, {"dispatched": 1, "succeeded": 1, "retry_wait": 0, "failed": 0, "unknown": 0})
        self.assertEqual(second["dispatched"], 0)
        status = engine.status()["jobs"][0]["latest"]
        self.assertEqual(status["status"], "succeeded")
        self.assertEqual(status["attempts"], 1)
        head = self.store.load(self.order)
        self.assertEqual(head["status"], "active")
        self.assertEqual(head["turns_used"], 1)

    def test_engine_unknown_and_mentor_pending_both_block_until_reconciled(self) -> None:
        job = {
            "id": "mentor-crash-1",
            "enabled": True,
            "replay_safe": False,
            "schedule": {"kind": "once", "at": self.at.isoformat(), "grace_seconds": 600},
        }

        def crash_after_ledger(_job, context):
            self.store.record_cycle(
                self.order,
                cycle_id=context["attempt_id"],
                variant_id="baseline",
                action_sha256="c" * 64,
                outcome="unknown",
                verified_evidence_artifact_path=None,
                effect_id=context["attempt_id"],
                effect_status="pending",
                at=self.at,
            )
            raise RuntimeError("synthetic crash after durable mentor event")

        engine = Engine(
            self.workspace / ".job-runtime/crash-engine",
            [job],
            {"max_attempts": 2, "backoff_seconds": 1, "max_backoff_seconds": 2},
            crash_after_ledger,
            workspace_root=self.workspace,
            clock=lambda: self.at,
            max_workers=1,
        )
        summary = engine.tick(self.at)
        self.assertEqual(summary["unknown"], 1)
        latest = engine.status()["jobs"][0]["latest"]
        self.assertEqual(latest["status"], "unknown")
        blocked = self.store.load(self.order)
        self.assertEqual(blocked["status"], "blocked_pending_effect")
        with self.assertRaisesRegex(StateError, "not continuable"):
            self.store.record_cycle(
                self.order,
                cycle_id="unsafe-next",
                variant_id="baseline",
                action_sha256="d" * 64,
                outcome="succeeded",
                verified_evidence_artifact_path=self._progress_artifact(
                    "unsafe-next", ["unsafe-evidence"]
                ),
                at=self.at,
            )
        evidence = self.workspace / "runtime/reconciliation-evidence.json"
        evidence.write_text('{"observed":"process exited after durable mentor event"}\n')
        with mock.patch.object(
            self.store,
            "_resolve_effect_from_reconciliation",
            side_effect=OSError("synthetic post-engine crash"),
        ):
            with self.assertRaisesRegex(OSError, "post-engine crash"):
                reconcile_unknown(
                    engine,
                    self.store,
                    self.order,
                    reconciliation_id="reconcile-crash-1",
                    slot_id=latest["slot_id"],
                    outcome="failed",
                    evidence_path="runtime/reconciliation-evidence.json",
                    at=self.at,
                )
        self.assertEqual(engine.status()["jobs"][0]["latest"]["status"], "failed")
        self.assertEqual(self.store.load(self.order)["status"], "blocked_pending_effect")
        journal = reconcile_unknown(
            engine,
            self.store,
            self.order,
            reconciliation_id="reconcile-crash-1",
            slot_id=latest["slot_id"],
            outcome="failed",
            evidence_path="runtime/reconciliation-evidence.json",
            at=self.at,
        )
        self.assertEqual(journal["phase"], "completed")
        self.assertEqual(self.store.load(self.order)["status"], "active")
        with self.assertRaisesRegex(ReconciliationError, "conflicts"):
            reconcile_unknown(
                engine,
                self.store,
                self.order,
                reconciliation_id="reconcile-crash-1",
                slot_id=latest["slot_id"],
                outcome="succeeded",
                evidence_path="runtime/reconciliation-evidence.json",
                at=self.at,
            )

    def test_unknown_effect_is_visibly_fenced(self) -> None:
        head = self.store.record_cycle(
            self.order,
            cycle_id="cycle-unknown",
            variant_id="baseline",
            action_sha256="a" * 64,
            outcome="unknown",
            verified_evidence_artifact_path=None,
            effect_id="effect-1",
            effect_status="pending",
            at=self.at,
        )
        projection = build_projection(
            self.order,
            self.store,
            generated_at=self.at,
            scheduler_status="unknown",
            gates=GateSummary(verified=0, failed=0, pending=2),
            evaluation=EvaluationSummary(
                baseline="pending", holdout="protected untouched"
            ),
            promotion=self._promotion(),
        )
        task = projection["work_orders"][0]["task"]
        self.assertEqual(task["status"], "blocked_pending_effect")
        self.assertIn("reconcile", task["next_action"])


if __name__ == "__main__":
    unittest.main()
