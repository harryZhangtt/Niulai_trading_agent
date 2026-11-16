from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from mentor.scheduler.contracts import WorkOrder
from mentor.scheduler.controller import (
    ControllerError,
    ControllerInput,
    ControllerStatus,
    NextAction,
    run_controller,
)
from mentor.scheduler.state import DurableSessionStore
from mentor.scheduler import state as scheduler_state
from mentor.scheduler.supervision import (
    FailureKind,
    PromotionVerdict,
    canonical_action_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
END = START + timedelta(hours=2)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SchedulerControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        parent = ROOT / "runtime" / "test-tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="controller-", dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        (self.workspace / "plans").mkdir()
        (self.workspace / "evidence").mkdir()
        self.plan_bytes = b"frozen controller plan\n"
        self.acceptance = {
            "schema_version": 1,
            "criteria": [
                {"criterion_id": "critical-safety", "critical": True},
                {"criterion_id": "quality", "critical": False},
            ],
        }
        self.acceptance_bytes = json.dumps(self.acceptance, sort_keys=True).encode()
        (self.workspace / "plans/plan.md").write_bytes(self.plan_bytes)
        (self.workspace / "plans/acceptance.json").write_bytes(self.acceptance_bytes)
        self.counter = 0

    def invoke(self, source: ControllerInput):
        return run_controller(source, capability=scheduler_state._VERIFIER_CAPABILITY)

    def payload(self, **overrides) -> dict:
        value = {
            "schema_version": 1,
            "work_order_id": "wo-controller",
            "logical_session": {
                "logical_session_id": "logical-controller",
                "provider_thread_mode": "ephemeral_threads",
                "max_provider_threads": 4,
            },
            "plan": {"path": "plans/plan.md", "sha256": digest(self.plan_bytes)},
            "acceptance": {"path": "plans/acceptance.json", "sha256": digest(self.acceptance_bytes)},
            "execution": {
                "starts_at": START.isoformat(),
                "ends_at": END.isoformat(),
                "turn_timeout_seconds": 300,
                "max_turns": 8,
            },
            "supervision": {
                "max_no_progress_cycles": 3,
                "max_repeated_actions": 3,
                "max_interventions": 3,
            },
            "evidence_policy": {
                "record_all_variants": True,
                "max_variants": 3,
                "max_reused_evaluations": 2,
                "worker_holdout_access": False,
            },
            "completion": {
                "required_event_kinds": ["cycle"],
                "require_no_pending_effects": True,
                "require_acceptance_hash_match": True,
            },
        }
        for section, changes in overrides.items():
            value[section].update(changes)
        return value

    def setup_session(self, *, payload=None, cycles=1, same_action=False, pending=False):
        order = WorkOrder.from_json(json.dumps(payload or self.payload()), self.workspace)
        self.counter += 1
        store = DurableSessionStore(self.workspace, f"runtime/session-{self.counter}", "controller-owner")
        store.create(order, at=START - timedelta(minutes=1))
        for number in range(1, cycles + 1):
            store.record_cycle(
                order,
                cycle_id=f"cycle-{number}",
                variant_id="candidate-a",
                action_sha256=canonical_action_fingerprint(
                    {"retry": "same"} if same_action else {"action": f"cycle-{number}"}
                ),
                outcome="unknown" if pending and number == cycles else "succeeded",
                verified_evidence_artifact_path=None,
                effect_id="effect-1" if pending and number == cycles else None,
                effect_status="pending" if pending and number == cycles else "none",
                at=START + timedelta(minutes=number),
            )
        return order, store, f"cycle-{cycles}"

    def artifact(self, order, cycle_id, verdicts=None, *, candidate="candidate-a", changes=None):
        verdicts = verdicts or {item.criterion_id: "satisfied" for item in order.acceptance_criteria}
        observations = []
        suffix = f"{self.counter}-{cycle_id}-{len(list((self.workspace / 'evidence').glob('artifact-*.json')))}"
        for item in order.acceptance_criteria:
            relative = f"evidence/{suffix}-{item.criterion_id}.txt"
            evidence = self.workspace / relative
            evidence.write_text(f"verified {item.criterion_id}\n")
            observations.append({
                "criterion_id": item.criterion_id,
                "verdict": verdicts[item.criterion_id],
                "evidence": [{"path": relative, "sha256": digest(evidence.read_bytes())}],
            })
        source_path = f"evidence/{suffix}-candidate.txt"
        source_file = self.workspace / source_path
        source_file.write_text(f"candidate output for {candidate}\n")
        value = {
            "schema_version": 1,
            "artifact_kind": "criterion_observations",
            "producer_role": "verifier",
            "verifier_id": "verifier-1",
            "work_order_id": order.work_order_id,
            "plan_sha256": order.plan.sha256,
            "acceptance_sha256": order.acceptance.sha256,
            "cycle_id": cycle_id,
            "candidate_id": candidate,
            "candidate_source": {"path": source_path, "sha256": digest(source_file.read_bytes())},
            "observations": observations,
        }
        value.update(changes or {})
        relative = f"evidence/artifact-{suffix}.json"
        (self.workspace / relative).write_text(json.dumps(value))
        return relative

    def policy_artifact(self, order, store, cycle, criterion_path, *, assessment_sha, proposed, reason):
        criterion = json.loads((self.workspace / criterion_path).read_text())
        relative = f"evidence/policy-{self.counter}-{reason}.json"
        value = {
            "schema_version": 1, "artifact_kind": "policy_rejection", "producer_role": "evaluator",
            "evaluator_id": "evaluator-1", "work_order_id": order.work_order_id,
            "plan_sha256": order.plan.sha256, "acceptance_sha256": order.acceptance.sha256,
            "cycle_id": cycle, "candidate_id": "candidate-a", "candidate_source": criterion["candidate_source"],
            "evaluation_assessment_sha256": assessment_sha,
            "proposed_required_criteria": sorted(proposed), "reason_code": reason,
        }
        (self.workspace / relative).write_text(json.dumps(value))
        head = store._record_policy_rejection_from_evaluator(
            order, artifact_path=relative, cycle_id=cycle, candidate_id="candidate-a",
            at=START + timedelta(minutes=21), capability=scheduler_state._EVALUATOR_CAPABILITY,
        )
        return head["policy_observations"][0]["sha256"]

    def cancellation(self, order, store, cycle, event_id="cancel-1"):
        source_path = f"evidence/cancel-source-{self.counter}.txt"
        evidence_path = f"evidence/cancel-evidence-{self.counter}.txt"
        (self.workspace / source_path).write_text("cancelled candidate source\n")
        (self.workspace / evidence_path).write_text("scheduler cancellation evidence\n")
        relative = f"evidence/cancellation-{self.counter}.json"
        value = {
            "schema_version": 1, "artifact_kind": "cancellation", "producer_role": "scheduler",
            "work_order_id": order.work_order_id, "plan_sha256": order.plan.sha256,
            "acceptance_sha256": order.acceptance.sha256, "cycle_id": cycle,
            "candidate_id": "candidate-a", "candidate_source": {"path": source_path, "sha256": digest((self.workspace / source_path).read_bytes())},
            "slot_id": "slot-1", "attempt_id": "attempt-1", "cancellation_event_id": event_id,
            "reason_code": "operator_cancelled", "cancelled_at": (START + timedelta(minutes=2)).isoformat(),
            "evidence": [{"path": evidence_path, "sha256": digest((self.workspace / evidence_path).read_bytes())}],
        }
        (self.workspace / relative).write_text(json.dumps(value))
        head = store._record_cancellation_from_scheduler(
            order, artifact_path=relative, cycle_id=cycle, candidate_id="candidate-a",
            slot_id="slot-1", attempt_id="attempt-1", cancellation_event_id=event_id,
            at=START + timedelta(minutes=3), capability=scheduler_state._CANCELLATION_CAPABILITY,
        )
        return head["cancellations"][0]["sha256"]

    def evaluation_assessment(self, order, store, cycle, criterion_path, *, complete=True, holdout=True):
        criterion = json.loads((self.workspace / criterion_path).read_text())
        suffix = f"{self.counter}-{cycle}-{len(list((self.workspace / 'evidence').glob('evaluation-*.json')))}"
        identity = {
            "schema_version": 1, "producer_role": "evaluator", "evaluator_id": "evaluator-1",
            "work_order_id": order.work_order_id, "plan_sha256": order.plan.sha256,
            "acceptance_sha256": order.acceptance.sha256, "cycle_id": cycle,
            "candidate_id": "candidate-a", "candidate_source": criterion["candidate_source"],
        }
        holdout_evidence = f"evidence/evaluation-{suffix}-holdout.txt"
        (self.workspace / holdout_evidence).write_text("independent holdout evidence\n")
        receipts = {
            "case_manifest": {**identity, "artifact_kind": "case_manifest",
                "candidate_case_ids": ["case-a"], "baseline_case_ids": ["case-a"] if complete else ["case-b"]},
            "usage_receipt": {**identity, "artifact_kind": "usage_receipt",
                "candidate_budget": {"calls": 1}, "baseline_budget": {"calls": 1}},
            "ablation_receipt": {**identity, "artifact_kind": "ablation_receipt",
                "required_ablations": [], "observed_ablations": []},
            "holdout_receipt": {**identity, "artifact_kind": "holdout_receipt",
                "status": {True: "preserved", False: "violated", None: "unverified"}[holdout],
                "evidence": [{"path": holdout_evidence, "sha256": digest((self.workspace / holdout_evidence).read_bytes())}]},
        }
        refs = {}
        for kind, value in receipts.items():
            path = f"evidence/evaluation-{suffix}-{kind}.json"
            (self.workspace / path).write_text(json.dumps(value))
            refs[kind] = {"path": path, "sha256": digest((self.workspace / path).read_bytes())}
        relative = f"evidence/evaluation-{suffix}.json"
        (self.workspace / relative).write_text(json.dumps({**identity, "artifact_kind": "evaluation_assessment", **refs}))
        head = store._record_evaluation_assessment_from_evaluator(
            order, artifact_path=relative, cycle_id=cycle, candidate_id="candidate-a",
            at=START + timedelta(minutes=20), capability=scheduler_state._EVALUATOR_CAPABILITY,
        )
        return head["evaluation_assessments"][0]["sha256"]

    def source(self, order, store, cycle_id, artifact, **changes):
        evaluation_complete = changes.pop("evaluation_complete", True)
        evaluation_holdout = changes.pop("evaluation_holdout", True)
        evaluation_sha = changes.pop("evaluation_assessment_sha256", None)
        if evaluation_sha is None and (self.workspace / artifact).exists():
            evaluation_sha = self.evaluation_assessment(
                order, store, cycle_id, artifact,
                complete=evaluation_complete,
                holdout=evaluation_holdout,
            )
        values = dict(
            work_order=order,
            store=store,
            cycle_id=cycle_id,
            candidate_id="candidate-a",
            criterion_artifact_path=artifact,
            evaluation_assessment_sha256=evaluation_sha or "0" * 64,
            current_action={"action": cycle_id},
            clock=lambda: START + timedelta(minutes=30),
        )
        values.update(changes)
        return ControllerInput(**values)

    def test_verifier_capability_is_required(self):
        order, store, cycle = self.setup_session()
        source = self.source(order, store, cycle, self.artifact(order, cycle))
        for capability in (None, object()):
            with self.subTest(capability=capability):
                with self.assertRaises(ControllerError) as caught:
                    run_controller(source, capability=capability)
                self.assertEqual(caught.exception.code, "verifier_capability_required")
        self.assertEqual(store.load(order)["criterion_observations"], [])

    def test_acceptance_early_stops_even_when_worker_budgets_are_full(self):
        payload = self.payload()
        payload["execution"]["max_turns"] = 1
        payload["logical_session"]["max_provider_threads"] = 1
        payload["evidence_policy"]["max_variants"] = 1
        order, store, cycle = self.setup_session(payload=payload)
        store.record_provider_thread(order, provider="p", thread_id="t", at=START + timedelta(minutes=10))
        result = self.invoke(self.source(order, store, cycle, self.artifact(order, cycle)))
        self.assertEqual(result.status, ControllerStatus.COMPLETED)
        self.assertEqual(result.promotion.verdict, PromotionVerdict.ACCEPTED)
        self.assertEqual(store.load(order)["status"], "completed")

    def test_critical_false_rejects_and_is_idempotent(self):
        order, store, cycle = self.setup_session()
        path = self.artifact(order, cycle, {"critical-safety": "violated", "quality": "inconclusive"})
        source = self.source(order, store, cycle, path, evaluation_complete=False, evaluation_holdout=None)
        first = self.invoke(source)
        second = self.invoke(source)
        self.assertEqual(first.status, ControllerStatus.REJECTED)
        self.assertEqual(first.reason_code, "critical_criterion_violated")
        self.assertEqual(second.head["revision"], first.head["revision"])

    def test_incomplete_evidence_continues_with_specific_action(self):
        order, store, cycle = self.setup_session()
        path = self.artifact(order, cycle, {"critical-safety": "satisfied", "quality": "inconclusive"})
        result = self.invoke(self.source(order, store, cycle, path))
        self.assertEqual(result.status, ControllerStatus.CONTINUE)
        self.assertEqual(result.next_action, NextAction.COLLECT_CRITERION_EVIDENCE)
        self.assertEqual(len(result.observations), 1)

    def test_cancellation_reference_cannot_be_laundered(self):
        order, store, cycle = self.setup_session()
        source = self.source(
            order, store, cycle, "evidence/unused.json",
            cancellation_artifact_sha256="f" * 64,
        )
        with self.assertRaises(ControllerError) as caught:
            self.invoke(source)
        self.assertEqual(caught.exception.code, "cancellation_invalid")
        self.assertEqual(store.load(order)["status"], "active")

    def test_zero_durable_or_fabricated_evaluator_reference_is_rejected(self):
        for reference in ("0" * 64, None):
            with self.subTest(reference=reference):
                order, store, cycle = self.setup_session()
                criterion_path = self.artifact(order, cycle)
                fabricated = reference or digest((self.workspace / criterion_path).read_bytes())
                source = self.source(
                    order, store, cycle, criterion_path,
                    evaluation_assessment_sha256=fabricated,
                )
                with self.assertRaises(ControllerError) as caught:
                    self.invoke(source)
                self.assertEqual(caught.exception.code, "evaluation_assessment_invalid")

    def test_preexisting_inconclusive_evidence_expires_at_sequential_boundary(self):
        order, store, cycle = self.setup_session()
        criterion_path = self.artifact(order, cycle, {"critical-safety": "satisfied", "quality": "inconclusive"})
        source = self.source(order, store, cycle, criterion_path)
        store._record_criterion_observation_from_verifier(
            order, artifact_path=criterion_path, cycle_id=cycle, candidate_id="candidate-a",
            at=START + timedelta(minutes=21), capability=scheduler_state._VERIFIER_CAPABILITY,
        )
        times = iter((START + timedelta(minutes=30), END, END, END))
        result = self.invoke(replace(source, clock=lambda: next(times)))
        self.assertEqual(result.status, ControllerStatus.EXPIRED)
        self.assertEqual(result.budgets.seconds_remaining, 0)

    def test_preexisting_decisive_evidence_can_complete_at_boundary(self):
        order, store, cycle = self.setup_session()
        criterion_path = self.artifact(order, cycle)
        source = self.source(order, store, cycle, criterion_path)
        store._record_criterion_observation_from_verifier(
            order, artifact_path=criterion_path, cycle_id=cycle, candidate_id="candidate-a",
            at=START + timedelta(minutes=21), capability=scheduler_state._VERIFIER_CAPABILITY,
        )
        times = iter((START + timedelta(minutes=30), END, END, END))
        result = self.invoke(replace(source, clock=lambda: next(times)))
        self.assertEqual(result.status, ControllerStatus.COMPLETED)

    def test_clock_rollback_fails_closed_before_append(self):
        order, store, cycle = self.setup_session()
        criterion_path = self.artifact(order, cycle)
        source = self.source(order, store, cycle, criterion_path)
        times = iter((START + timedelta(minutes=30), START + timedelta(minutes=29)))
        with self.assertRaises(ControllerError) as caught:
            self.invoke(replace(source, clock=lambda: next(times)))
        self.assertEqual(caught.exception.code, "clock_rollback")
        self.assertEqual(store.load(order)["criterion_observations"], [])

    def test_deadline_race_cannot_record_new_verifier_evidence(self):
        order, store, cycle = self.setup_session()
        criterion_path = self.artifact(order, cycle)
        times = iter((START + timedelta(minutes=30), END, END))
        source = self.source(order, store, cycle, criterion_path, clock=lambda: next(times))
        result = self.invoke(source)
        self.assertEqual(result.status, ControllerStatus.EXPIRED)
        self.assertEqual(store.load(order)["criterion_observations"], [])

    def test_pending_effect_blocks_without_consuming_artifact(self):
        order, store, cycle = self.setup_session(pending=True)
        result = self.invoke(self.source(order, store, cycle, "evidence/does-not-exist.json"))
        self.assertEqual(result.status, ControllerStatus.BLOCKED_PENDING_EFFECT)
        self.assertEqual(result.head["criterion_observations"], [])

    def test_expired_and_cancelled_terminal_states(self):
        order, store, cycle = self.setup_session()
        artifact = self.artifact(order, cycle, {"critical-safety": "satisfied", "quality": "inconclusive"})
        expired = self.invoke(self.source(order, store, cycle, artifact, clock=lambda: END))
        self.assertEqual(expired.status, ControllerStatus.EXPIRED)

        order, store, cycle = self.setup_session()
        cancellation_sha = self.cancellation(order, store, cycle)
        cancelled = self.invoke(self.source(
            order, store, cycle, "evidence/unused.json",
            cancellation_artifact_sha256=cancellation_sha,
        ))
        self.assertEqual(cancelled.status, ControllerStatus.CANCELLED)
        self.assertEqual(store.load(order)["status"], "cancelled")

    def test_turn_thread_and_reused_evaluation_budget_exhaustion(self):
        cases = (
            ("turn_budget_exhausted", {"execution": {"max_turns": 1}}, {}),
            ("thread_budget_exhausted", {"logical_session": {"max_provider_threads": 1}}, {"thread": True}),
            ("reused_evaluation_budget_exhausted", {"evidence_policy": {"max_reused_evaluations": 0}}, {"reuse": True}),
        )
        for reason, overrides, options in cases:
            with self.subTest(reason=reason):
                payload = self.payload(**overrides)
                order, store, cycle = self.setup_session(payload=payload)
                if options.get("thread"):
                    store.record_provider_thread(order, provider="p", thread_id="t", at=START + timedelta(minutes=10))
                verdicts = (
                    {"critical-safety": "satisfied", "quality": "satisfied"}
                    if options.get("reuse") else
                    {"critical-safety": "satisfied", "quality": "inconclusive"}
                )
                path = self.artifact(order, cycle, verdicts)
                source = self.source(
                    order, store, cycle, path,
                    evaluation_complete=options.get("reuse", False) is False,
                )
                result = self.invoke(source)
                self.assertEqual(result.status, ControllerStatus.INCONCLUSIVE_BUDGET_EXHAUSTED)
                self.assertEqual(result.reason_code, reason)

    def test_variant_and_intervention_budget_exhaustion_after_stalled_retry(self):
        for reason, failure, intervention_limit in (
            ("variant_budget_exhausted", FailureKind.PERMANENT, 2),
            ("intervention_budget_exhausted", FailureKind.UNKNOWN, 0),
        ):
            with self.subTest(reason=reason):
                payload = self.payload(
                    evidence_policy={"max_variants": 1},
                    supervision={"max_interventions": intervention_limit},
                )
                order, store, cycle = self.setup_session(payload=payload, same_action=True)
                path = self.artifact(order, cycle, {"critical-safety": "satisfied", "quality": "inconclusive"})
                action = {"retry": "same"}
                fingerprint = canonical_action_fingerprint(action)
                source = self.source(
                    order, store, cycle, path,
                    current_action=action,
                    failure_kind=failure,
                    error_signature="same",
                    previous_error_signature="same",
                )
                first = self.invoke(source)
                self.assertEqual(first.status, ControllerStatus.CONTINUE)
                second = self.invoke(source)
                self.assertEqual(second.status, ControllerStatus.INCONCLUSIVE_BUDGET_EXHAUSTED)
                self.assertEqual(second.reason_code, reason)

    def test_no_progress_and_repeated_action_budget_exhaustion(self):
        cases = (
            ("no_progress_budget_exhausted", 1, 3, 1),
            ("repeated_action_budget_exhausted", 3, 1, 2),
        )
        for reason, no_progress, repeated, cycles in cases:
            with self.subTest(reason=reason):
                payload = self.payload(supervision={
                    "max_no_progress_cycles": no_progress,
                    "max_repeated_actions": repeated,
                })
                order, store, cycle = self.setup_session(payload=payload, cycles=cycles, same_action=True)
                path = self.artifact(order, cycle, {"critical-safety": "satisfied", "quality": "inconclusive"})
                action = {"retry": "same"}
                fingerprint = canonical_action_fingerprint(action)
                source = self.source(order, store, cycle, path, current_action=action)
                self.assertEqual(self.invoke(source).status, ControllerStatus.CONTINUE)
                result = self.invoke(source)
                self.assertEqual(result.status, ControllerStatus.INCONCLUSIVE_BUDGET_EXHAUSTED)
                self.assertEqual(result.reason_code, reason)

    def test_comparison_and_holdout_inconclusive_never_accept(self):
        for changes, action in (
            ({"evaluation_complete": False}, NextAction.COMPLETE_MATCHED_COMPARISON),
            ({"evaluation_holdout": None}, NextAction.VERIFY_HOLDOUT_INTEGRITY),
        ):
            with self.subTest(action=action):
                order, store, cycle = self.setup_session()
                result = self.invoke(self.source(order, store, cycle, self.artifact(order, cycle), **changes))
                self.assertEqual(result.status, ControllerStatus.CONTINUE)
                self.assertEqual(result.next_action, action)
                self.assertEqual(result.promotion.verdict, PromotionVerdict.INCONCLUSIVE)

    def test_verifier_evaluator_candidate_source_mismatch_fails_closed(self):
        order, store, cycle = self.setup_session()
        criterion_path = self.artifact(order, cycle)
        source = self.source(order, store, cycle, criterion_path)
        other_path = "evidence/other-candidate-source.txt"
        other_file = self.workspace / other_path
        other_file.write_text("different candidate bytes\n")
        criterion_file = self.workspace / criterion_path
        criterion = json.loads(criterion_file.read_text())
        criterion["candidate_source"] = {"path": other_path, "sha256": digest(other_file.read_bytes())}
        criterion_file.write_text(json.dumps(criterion))
        with self.assertRaises(ControllerError) as caught:
            self.invoke(source)
        self.assertEqual(caught.exception.code, "criterion_artifact_invalid")
        self.assertEqual(store.load(order)["status"], "active")

    def test_artifact_and_candidate_drift_fail_closed(self):
        order, store, cycle = self.setup_session()
        drifted = self.artifact(order, cycle, candidate="other-candidate")
        with self.assertRaisesRegex(ControllerError, "artifact is invalid") as caught:
            self.invoke(self.source(order, store, cycle, drifted))
        self.assertEqual(caught.exception.code, "criterion_artifact_invalid")
        order, store, cycle = self.setup_session()
        valid = self.artifact(order, cycle)
        with self.assertRaisesRegex(ControllerError, "not a durably recorded variant") as caught:
            self.invoke(self.source(order, store, cycle, valid, candidate_id="other-candidate"))
        self.assertEqual(caught.exception.code, "candidate_drift")

    def test_softening_and_holdout_rejection_are_durable(self):
        cases = (
            ({"proposed_required_criteria": {"quality"}}, True, {"quality"}, "criterion_softening"),
            ({"evaluation_holdout": False}, False, {"critical-safety", "quality"}, "holdout_integrity_violation"),
        )
        for changes, holdout, proposed, reason in cases:
            with self.subTest(reason=reason):
                order, store, cycle = self.setup_session()
                criterion_path = self.artifact(order, cycle)
                source = self.source(order, store, cycle, criterion_path, **changes)
                policy_sha = self.policy_artifact(
                    order, store, cycle, criterion_path,
                    assessment_sha=source.evaluation_assessment_sha256,
                    proposed=proposed, reason=reason,
                )
                source = replace(source, policy_rejection_artifact_sha256=policy_sha)
                result = self.invoke(source)
                self.assertEqual(result.status, ControllerStatus.REJECTED)
                self.assertEqual(result.reason_code, reason)
                head = store.load(order)
                self.assertEqual(head["status"], "rejected")
                self.assertEqual(len(head["policy_observations"]), 1)

    def test_policy_rejection_without_durable_evaluator_evidence_fails_closed(self):
        order, store, cycle = self.setup_session()
        source = self.source(
            order, store, cycle, self.artifact(order, cycle),
            evaluation_holdout=False, policy_rejection_artifact_sha256="f" * 64,
        )
        with self.assertRaises(ControllerError) as caught:
            self.invoke(source)
        self.assertEqual(caught.exception.code, "policy_rejection_drift")
        self.assertEqual(store.load(order)["status"], "active")

    def test_terminal_state_cannot_be_reactivated_or_redirected(self):
        order, store, cycle = self.setup_session()
        source = self.source(order, store, cycle, self.artifact(order, cycle))
        completed = self.invoke(source)
        duplicate = self.invoke(source)
        self.assertEqual(duplicate.status, ControllerStatus.COMPLETED)
        self.assertEqual(duplicate.head["revision"], completed.head["revision"])
        with self.assertRaises(ControllerError) as caught:
            self.invoke(self.source(order, store, cycle, "evidence/unused.json", candidate_id="other"))
        self.assertEqual(caught.exception.code, "terminal_conflict")


if __name__ == "__main__":
    unittest.main()
