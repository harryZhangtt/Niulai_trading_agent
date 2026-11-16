"""Focused tests for strict mentor scheduler contracts and durable state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from mentor.scheduler import ContractError, DurableSessionStore, StateError, WorkOrder
from mentor.scheduler import state as scheduler_state
from mentor.scheduler.supervision import (
    ComparisonDesign, FrozenCriteria, PromotionVerdict, check_matched_comparison,
    decide_verified_promotion,
)

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)
END = START + timedelta(hours=2)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SchedulerContractTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / "runtime" / "test-tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="scheduler-", dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        (self.workspace / "plans").mkdir()
        (self.workspace / "evidence").mkdir()
        self.plan_bytes = b"frozen plan\n"
        self.acceptance_value = {
            "schema_version": 1,
            "criteria": [
                {"criterion_id": "tests-pass", "critical": True},
                {"criterion_id": "evidence-preserved", "critical": False},
            ],
        }
        self.acceptance_bytes = json.dumps(self.acceptance_value, sort_keys=True).encode()
        (self.workspace / "plans/plan.md").write_bytes(self.plan_bytes)
        (self.workspace / "plans/acceptance.json").write_bytes(self.acceptance_bytes)
        self.store_counter = 0

    def payload(self) -> dict:
        return {
            "schema_version": 1,
            "work_order_id": "wo-001",
            "logical_session": {
                "logical_session_id": "logical-001",
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
                "max_no_progress_cycles": 2,
                "max_repeated_actions": 2,
                "max_interventions": 2,
            },
            "evidence_policy": {
                "record_all_variants": True,
                "max_variants": 3,
                "max_reused_evaluations": 1,
                "worker_holdout_access": False,
            },
            "completion": {
                "required_event_kinds": ["provider_thread", "cycle"],
                "require_no_pending_effects": True,
                "require_acceptance_hash_match": True,
            },
        }

    def order(self, payload: dict | None = None) -> WorkOrder:
        return WorkOrder.from_json(json.dumps(payload or self.payload()), self.workspace)

    def store(self, owner: str = "mentor-owner") -> DurableSessionStore:
        self.store_counter += 1
        return DurableSessionStore(self.workspace, f"runtime/session-{self.store_counter}", owner)

    def artifact(self, order: WorkOrder, name: str = "verification.json", **changes) -> str:
        value = {
            "schema_version": 1,
            "work_order_id": order.work_order_id,
            "acceptance_sha256": order.acceptance.sha256,
            "verdict": "accepted",
            "observations": [
                {"criterion_id": criterion.criterion_id, "satisfied": True}
                for criterion in order.acceptance_criteria
            ],
        }
        value.update(changes)
        relative = f"evidence/{name}"
        (self.workspace / relative).write_text(json.dumps(value))
        return relative

    def progress_artifact(self, store, order, cycle_id: str, evidence_ids, name: str | None = None, **changes):
        observations = []
        for evidence_id in evidence_ids:
            evidence_path = f"evidence/{store.directory.name}-{evidence_id}.txt"
            evidence_file = self.workspace / evidence_path
            if not evidence_file.exists():
                evidence_file.write_bytes(f"verified evidence {evidence_id}\n".encode())
            observations.append({
                "evidence_id": evidence_id,
                "evidence_path": evidence_path,
                "sha256": digest(evidence_file.read_bytes()),
            })
        value = {
            "schema_version": 1,
            "work_order_id": order.work_order_id,
            "plan_sha256": order.plan.sha256,
            "acceptance_sha256": order.acceptance.sha256,
            "cycle_id": cycle_id,
            "observations": observations,
        }
        value.update(changes)
        relative = f"evidence/{name or (store.directory.name + '-' + cycle_id + '-progress.json')}"
        (self.workspace / relative).write_text(json.dumps(value))
        return relative

    def criterion_artifact(
        self, store, order, cycle_id: str, candidate_id: str = "variant-a",
        verdicts: dict[str, str] | None = None, name: str | None = None, **changes,
    ) -> str:
        verdicts = verdicts or {criterion.criterion_id: "satisfied" for criterion in order.acceptance_criteria}
        source_path = f"evidence/{store.directory.name}-{cycle_id}-{candidate_id}-source.txt"
        source_file = self.workspace / source_path
        if not source_file.exists():
            source_file.write_text(f"candidate source for {candidate_id} in {cycle_id}\n")
        observations = []
        for criterion in order.acceptance_criteria:
            evidence_path = f"evidence/{store.directory.name}-{cycle_id}-{criterion.criterion_id}.txt"
            evidence_file = self.workspace / evidence_path
            evidence_file.write_text(f"verifier evidence for {criterion.criterion_id}\n")
            observations.append({
                "criterion_id": criterion.criterion_id,
                "verdict": verdicts[criterion.criterion_id],
                "evidence": [{"path": evidence_path, "sha256": digest(evidence_file.read_bytes())}],
            })
        value = {
            "schema_version": 1,
            "artifact_kind": "criterion_observations",
            "producer_role": "verifier",
            "verifier_id": "verifier-1",
            "work_order_id": order.work_order_id,
            "plan_sha256": order.plan.sha256,
            "acceptance_sha256": order.acceptance.sha256,
            "cycle_id": cycle_id,
            "candidate_id": candidate_id,
            "candidate_source": {"path": source_path, "sha256": digest(source_file.read_bytes())},
            "observations": observations,
        }
        value.update(changes)
        relative = f"evidence/{name or (store.directory.name + '-' + cycle_id + '-criteria.json')}"
        (self.workspace / relative).write_text(json.dumps(value))
        return relative

    def evaluation_artifact(self, store, order, cycle_id: str, *, candidate_id="variant-a", source_path=None,
                            evaluator_id="evaluator-1", **changes) -> str:
        source_path = source_path or f"evidence/{store.directory.name}-{cycle_id}-evaluation-source.txt"
        if not (self.workspace / source_path).exists():
            (self.workspace / source_path).write_text("candidate source\n")
        source = {"path": source_path, "sha256": digest((self.workspace / source_path).read_bytes())}
        identity = {"schema_version": 1, "producer_role": "evaluator", "evaluator_id": evaluator_id,
            "work_order_id": order.work_order_id, "plan_sha256": order.plan.sha256,
            "acceptance_sha256": order.acceptance.sha256, "cycle_id": cycle_id,
            "candidate_id": candidate_id, "candidate_source": source}
        holdout_evidence = f"evidence/{store.directory.name}-{cycle_id}-holdout.txt"
        (self.workspace / holdout_evidence).write_text("holdout evidence\n")
        receipts = {
            "case_manifest": {**identity, "artifact_kind": "case_manifest",
                "candidate_case_ids": ["case-a"], "baseline_case_ids": ["case-a"]},
            "usage_receipt": {**identity, "artifact_kind": "usage_receipt",
                "candidate_budget": {"calls": 1}, "baseline_budget": {"calls": 1}},
            "ablation_receipt": {**identity, "artifact_kind": "ablation_receipt",
                "required_ablations": ["retrieval"], "observed_ablations": ["retrieval"]},
            "holdout_receipt": {**identity, "artifact_kind": "holdout_receipt", "status": "preserved",
                "evidence": [{"path": holdout_evidence, "sha256": digest((self.workspace / holdout_evidence).read_bytes())}]},
        }
        refs = {}
        for kind, value in receipts.items():
            path = f"evidence/{store.directory.name}-{cycle_id}-{kind}.json"
            (self.workspace / path).write_text(json.dumps(value))
            refs[kind] = {"path": path, "sha256": digest((self.workspace / path).read_bytes())}
        value = {**identity, "artifact_kind": "evaluation_assessment", **refs}
        value.update(changes)
        relative = f"evidence/{store.directory.name}-{cycle_id}-assessment.json"
        (self.workspace / relative).write_text(json.dumps(value))
        return relative

    def policy_artifact(self, store, order, cycle_id: str, *, reason_code: str,
                        assessment_sha256: str, source_path: str, proposed=None, **changes) -> str:
        value = {"schema_version": 1, "artifact_kind": "policy_rejection", "producer_role": "evaluator",
            "evaluator_id": "evaluator-1", "work_order_id": order.work_order_id,
            "plan_sha256": order.plan.sha256, "acceptance_sha256": order.acceptance.sha256,
            "cycle_id": cycle_id, "candidate_id": "variant-a",
            "candidate_source": {"path": source_path, "sha256": digest((self.workspace / source_path).read_bytes())},
            "evaluation_assessment_sha256": assessment_sha256,
            "proposed_required_criteria": proposed or [c.criterion_id for c in order.acceptance_criteria],
            "reason_code": reason_code}
        value.update(changes)
        relative = f"evidence/{store.directory.name}-{cycle_id}-policy.json"
        (self.workspace / relative).write_text(json.dumps(value))
        return relative

    def cancellation_artifact(self, store, order: WorkOrder, cycle_id: str, *,
                              event_id: str, name: str = "cancellation.json",
                              reason_code: str = "operator_cancelled") -> str:
        source_path = f"evidence/{store.directory.name}-{cycle_id}-cancel-source.txt"
        evidence_path = f"evidence/{store.directory.name}-{cycle_id}-cancel-evidence.txt"
        (self.workspace / source_path).write_text("candidate source\n")
        (self.workspace / evidence_path).write_text("scheduler cancellation evidence\n")
        value = {
            "schema_version": 1, "artifact_kind": "cancellation", "producer_role": "scheduler",
            "work_order_id": order.work_order_id, "plan_sha256": order.plan.sha256,
            "acceptance_sha256": order.acceptance.sha256, "candidate_id": "variant-a",
            "candidate_source": {"path": source_path, "sha256": digest((self.workspace / source_path).read_bytes())},
            "cycle_id": cycle_id, "slot_id": "slot-1", "attempt_id": "attempt-1",
            "cancellation_event_id": event_id, "reason_code": reason_code,
            "cancelled_at": END.isoformat(),
            "evidence": [{"path": evidence_path, "sha256": digest((self.workspace / evidence_path).read_bytes())}],
        }
        relative = f"evidence/{name}"
        (self.workspace / relative).write_text(json.dumps(value))
        return relative

    def cycle(self, store, order, number: int, *, action: str = "a", evidence=None, **changes):
        cycle_id = f"cycle-{number}"
        evidence_ids = [f"evidence-{number}"] if evidence is None else evidence
        artifact = self.progress_artifact(store, order, cycle_id, evidence_ids) if evidence_ids else None
        values = {
            "cycle_id": cycle_id,
            "variant_id": "variant-a",
            "action_sha256": action * 64,
            "outcome": "succeeded",
            "verified_evidence_artifact_path": artifact,
            "at": START + timedelta(minutes=number),
        }
        values.update(changes)
        return store.record_cycle(order, **values)

    def test_valid_contract_parses_frozen_criteria_and_forbids_holdout(self):
        order = self.order()
        self.assertEqual([(c.criterion_id, c.critical) for c in order.acceptance_criteria], [
            ("tests-pass", True), ("evidence-preserved", False),
        ])
        self.assertFalse(order.evidence_policy.worker_holdout_access)
        order.verify_bindings()

    def test_strict_contract_rejects_duplicate_unknown_and_bad_acceptance(self):
        text = json.dumps(self.payload())
        with self.assertRaisesRegex(ContractError, "duplicate JSON key"):
            WorkOrder.from_json(text[:-1] + ',"work_order_id":"replacement"}', self.workspace)
        payload = self.payload()
        payload["credential"] = "forbidden"
        with self.assertRaisesRegex(ContractError, "extra=.*credential"):
            self.order(payload)

        bad = b'{"schema_version":1,"criteria":[{"criterion_id":"same","critical":true},{"criterion_id":"same","critical":false}]}'
        (self.workspace / "plans/acceptance.json").write_bytes(bad)
        payload = self.payload()
        payload["acceptance"]["sha256"] = digest(bad)
        with self.assertRaisesRegex(ContractError, "criterion IDs must be unique"):
            self.order(payload)

    def test_contract_rejects_naive_unbounded_symlink_and_holdout(self):
        payload = self.payload()
        payload["execution"]["starts_at"] = "2026-11-04T09:00:00"
        with self.assertRaisesRegex(ContractError, "UTC offset"):
            self.order(payload)
        payload = self.payload()
        payload["execution"]["max_turns"] = 10_001
        with self.assertRaisesRegex(ContractError, "max_turns"):
            self.order(payload)
        payload = self.payload()
        payload["evidence_policy"]["worker_holdout_access"] = True
        with self.assertRaisesRegex(ContractError, "must be false"):
            self.order(payload)

        outside = self.workspace.parent / f"{self.workspace.name}-outside.json"
        outside.write_bytes(self.acceptance_bytes)
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        (self.workspace / "plans/linked.json").symlink_to(outside)
        payload = self.payload()
        payload["acceptance"] = {"path": "plans/linked.json", "sha256": digest(self.acceptance_bytes)}
        with self.assertRaisesRegex(ContractError, "symlink"):
            self.order(payload)

    def test_acceptance_drift_blocks_state_change(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        (self.workspace / "plans/acceptance.json").write_text('{"schema_version":1,"criteria":[]}')
        with self.assertRaisesRegex(ContractError, "acceptance binding drifted"):
            store.record_provider_thread(order, provider="provider", thread_id="thread-1", at=START)

    def test_worker_events_enforce_before_and_after_window(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        with self.assertRaisesRegex(StateError, "outside the execution window"):
            store.record_provider_thread(order, provider="p", thread_id="early", at=START - timedelta(seconds=1))
        store.record_provider_thread(order, provider="p", thread_id="on-time", at=START)
        with self.assertRaisesRegex(StateError, "outside the execution window"):
            self.cycle(store, order, 1, at=END + timedelta(seconds=1))
        self.cycle(store, order, 2)
        with self.assertRaisesRegex(StateError, "outside the execution window"):
            store.record_intervention(order, intervention_id="late", reason_code="review", at=END + timedelta(seconds=1))
        with self.assertRaisesRegex(StateError, "outside the execution window"):
            store.record_reused_evaluation(order, evaluation_id="late-eval", source_cycle_id="cycle-2", at=END + timedelta(seconds=1))

    def test_no_progress_and_repeated_action_limits_are_persisted(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        self.cycle(store, order, 1, action="a", evidence=[])
        head = self.cycle(store, order, 2, action="a", evidence=[])
        self.assertEqual((head["consecutive_no_progress"], head["repeated_action_count"]), (2, 1))
        with self.assertRaisesRegex(StateError, "no-progress cycle limit"):
            self.cycle(store, order, 3, action="a", evidence=[])

        progressing = self.store()
        progressing.create(order, at=START - timedelta(hours=1))
        self.cycle(progressing, order, 1, action="b", evidence=["new-1"])
        self.cycle(progressing, order, 2, action="b", evidence=["new-2"])
        head = self.cycle(progressing, order, 3, action="b", evidence=["new-3"])
        self.assertEqual(head["repeated_action_count"], 0)
        self.assertEqual(head["verified_evidence_ids"], ["new-1", "new-2", "new-3"])
        with self.assertRaisesRegex(StateError, "already consumed"):
            self.cycle(progressing, order, 4, action="b", evidence=["new-3"])

        repeated_payload = self.payload()
        repeated_payload["supervision"]["max_no_progress_cycles"] = 10
        repeated_order = self.order(repeated_payload)
        repeated = self.store()
        repeated.create(repeated_order, at=START - timedelta(hours=1))
        self.cycle(repeated, repeated_order, 1, action="c", evidence=[])
        self.cycle(repeated, repeated_order, 2, action="c", evidence=[])
        self.cycle(repeated, repeated_order, 3, action="c", evidence=[])
        with self.assertRaisesRegex(StateError, "repeated-action limit"):
            self.cycle(repeated, repeated_order, 4, action="c", evidence=[])

    def test_progress_artifact_rejects_forgery_missing_mismatch_reuse_and_drift(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))

        def record(cycle_id, artifact, minute):
            return store.record_cycle(
                order,
                cycle_id=cycle_id,
                variant_id="variant-a",
                action_sha256="a" * 64,
                outcome="succeeded",
                verified_evidence_artifact_path=artifact,
                at=START + timedelta(minutes=minute),
            )

        with self.assertRaisesRegex(ContractError, "existing file"):
            record("cycle-missing", "evidence/missing-progress.json", 1)

        forged = self.progress_artifact(
            store, order, "cycle-forged", ["forged-evidence"], "forged-progress.json",
            work_order_id="other-work-order",
        )
        with self.assertRaisesRegex(ContractError, "does not bind"):
            record("cycle-forged", forged, 1)

        mismatch = self.progress_artifact(store, order, "cycle-mismatch", ["mismatch-evidence"], "mismatch-progress.json")
        mismatch_value = json.loads((self.workspace / mismatch).read_text())
        mismatch_value["observations"][0]["sha256"] = "0" * 64
        (self.workspace / mismatch).write_text(json.dumps(mismatch_value))
        with self.assertRaisesRegex(ContractError, "binding does not match"):
            record("cycle-mismatch", mismatch, 1)

        missing_evidence = self.progress_artifact(store, order, "cycle-no-file", ["vanishing"], "missing-evidence-progress.json")
        missing_value = json.loads((self.workspace / missing_evidence).read_text())
        (self.workspace / missing_value["observations"][0]["evidence_path"]).unlink()
        with self.assertRaisesRegex(ContractError, "existing file"):
            record("cycle-no-file", missing_evidence, 1)

        first = self.cycle(store, order, 1, evidence=["bound-evidence"])
        self.assertEqual(first["verified_evidence_ids"], ["bound-evidence"])
        with self.assertRaisesRegex(StateError, "already consumed"):
            self.cycle(store, order, 2, evidence=["bound-evidence"])

        artifact_path = self.workspace / f"evidence/{store.directory.name}-cycle-1-progress.json"
        artifact_path.write_text(artifact_path.read_text() + "\n")
        with self.assertRaisesRegex(StateError, "artifact digest"):
            store.load(order)

    def test_reused_evaluation_budget_and_replay_validation(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        self.cycle(store, order, 1)
        head = store.record_reused_evaluation(order, evaluation_id="eval-1", source_cycle_id="cycle-1", at=START + timedelta(minutes=2))
        self.assertEqual(head["reused_evaluations"], ["eval-1"])
        self.assertEqual(store.load(order), head)
        with self.assertRaisesRegex(StateError, "reused-evaluation limit"):
            store.record_reused_evaluation(order, evaluation_id="eval-2", source_cycle_id="cycle-1", at=START + timedelta(minutes=3))

    def test_post_window_effect_reconciliation_and_completion_are_allowed(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        store.record_provider_thread(order, provider="p", thread_id="t", at=START)
        self.cycle(store, order, 1, outcome="unknown", evidence=[], effect_id="attempt-1", effect_status="pending")
        with self.assertRaisesRegex(StateError, "not continuable"):
            self.cycle(store, order, 2)
        resolution = {
            "reconciliation_id": "reconcile-1",
            "engine_slot_id": "slot-1",
            "engine_attempt_id": "attempt-1",
            "outcome": "succeeded",
            "evidence_sha256": "e" * 64,
        }
        with self.assertRaisesRegex(StateError, "capability"):
            store._resolve_effect_from_reconciliation(order, **resolution, at=END + timedelta(minutes=1))
        with self.assertRaisesRegex(StateError, "capability"):
            store._resolve_effect_from_reconciliation(
                order, **resolution, at=END + timedelta(minutes=1), capability=object()
            )
        resolved = store._resolve_effect_from_reconciliation(
            order, **resolution, at=END + timedelta(minutes=1),
            capability=scheduler_state._RECONCILIATION_CAPABILITY,
        )
        self.assertEqual(resolved["status"], "active")
        self.assertEqual(resolved["effect_resolutions"][0]["effect_state"], "confirmed")
        retried = store._resolve_effect_from_reconciliation(
            order, **resolution, at=END + timedelta(minutes=2),
            capability=scheduler_state._RECONCILIATION_CAPABILITY,
        )
        self.assertEqual(retried["revision"], resolved["revision"])
        with self.assertRaisesRegex(StateError, "conflicts"):
            store._resolve_effect_from_reconciliation(
                order, **{**resolution, "outcome": "failed"}, at=END + timedelta(minutes=2),
                capability=scheduler_state._RECONCILIATION_CAPABILITY,
            )
        artifact = self.criterion_artifact(store, order, "cycle-1")
        observed = store._record_criterion_observation_from_verifier(
            order, artifact_path=artifact, cycle_id="cycle-1", candidate_id="variant-a",
            at=END + timedelta(minutes=2), capability=scheduler_state._VERIFIER_CAPABILITY,
        )
        record = observed["criterion_observations"][0]
        completed = store.complete_verified(
            order, candidate_id="variant-a", cycle_id="cycle-1",
            criterion_artifact_sha256=record["sha256"], at=END + timedelta(minutes=3),
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["verification_artifact"]["sha256"], record["sha256"])

    def test_legacy_completion_is_parser_only_and_not_a_writable_transition(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        store.record_provider_thread(order, provider="p", thread_id="t", at=START)
        self.cycle(store, order, 1)
        artifact = self.artifact(order)
        self.assertEqual(order.verify_acceptance_artifact(artifact).path, artifact)
        with self.assertRaisesRegex(StateError, "replay-only"):
            store.complete(order, verification_artifact_path=artifact, at=END + timedelta(minutes=1))
        wrong = self.artifact(order, "wrong.json", acceptance_sha256="0" * 64)
        with self.assertRaisesRegex(ContractError, "does not bind"):
            order.verify_acceptance_artifact(wrong)
        incomplete = self.artifact(
            order, "incomplete.json", observations=[{"criterion_id": "tests-pass", "satisfied": True}],
        )
        with self.assertRaisesRegex(ContractError, "one observation per criterion"):
            order.verify_acceptance_artifact(incomplete)
        self.assertEqual(store.load(order)["status"], "active")

    def test_logical_session_spans_threads_and_preserves_failures_variants(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        store.record_provider_thread(order, provider="p", thread_id="ephemeral-1", at=START)
        store.record_provider_thread(order, provider="p", thread_id="ephemeral-2", at=START + timedelta(seconds=1))
        self.cycle(store, order, 1, action="a", outcome="failed", evidence=[])
        head = self.cycle(store, order, 2, action="b", variant_id="variant-b")
        self.assertEqual([item["thread_id"] for item in head["provider_threads"]], ["ephemeral-1", "ephemeral-2"])
        self.assertEqual(head["failed_attempts"], ["cycle-1"])
        self.assertEqual(head["variants"], ["variant-a", "variant-b"])

    def test_duplicate_intervention_retry_is_idempotent_and_conflict_safe(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        first = store.record_intervention(order, intervention_id="int-1", reason_code="review", at=START)
        retried = store.record_intervention(order, intervention_id="int-1", reason_code="review", at=START + timedelta(minutes=1))
        self.assertEqual(retried["revision"], first["revision"])
        self.assertEqual(len(retried["interventions"]), 1)
        with self.assertRaisesRegex(StateError, "conflicts"):
            store.record_intervention(order, intervention_id="int-1", reason_code="different", at=START + timedelta(minutes=2))

    def test_concurrent_exact_intervention_retries_serialize(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        barrier = threading.Barrier(3)
        results = []
        errors = []

        def worker():
            try:
                barrier.wait(timeout=5)
                results.append(store.record_intervention(
                    order, intervention_id="shared-int", reason_code="review", at=START
                ))
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual([head["revision"] for head in results], [1, 1])
        self.assertEqual(len(store.load(order)["interventions"]), 1)

    def test_event_before_head_crash_recovers_exactly_one_valid_orphan(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        with mock.patch("mentor.scheduler.state._atomic_write", side_effect=OSError("injected head failure")):
            with self.assertRaisesRegex(OSError, "injected"):
                store.record_provider_thread(order, provider="p", thread_id="orphan-thread", at=START)
        with self.assertRaisesRegex(StateError, "orphan events"):
            store.load(order)
        recovered = store.recover_orphan(order)
        self.assertEqual(recovered["revision"], 1)
        self.assertEqual(recovered["provider_threads"][0]["thread_id"], "orphan-thread")
        self.assertEqual(store.load(order), recovered)

    def test_recovery_rejects_malformed_and_multiple_orphans(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        event_dir = store.events_directory
        malformed = event_dir / "00000001.json"
        malformed.write_text("{}")
        malformed.chmod(0o600)
        with self.assertRaises(StateError):
            store.recover_orphan(order)

        second = event_dir / "00000002.json"
        second.write_text("{}")
        second.chmod(0o600)
        with self.assertRaisesRegex(StateError, "exactly one"):
            store.recover_orphan(order)

    def test_verifier_artifact_is_capability_owned_complete_and_drift_checked(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        store.record_provider_thread(order, provider="p", thread_id="t", at=START)
        self.cycle(store, order, 1, variant_id="variant-a")
        path = self.criterion_artifact(store, order, "cycle-1")

        with self.assertRaisesRegex(StateError, "verifier capability"):
            store._record_criterion_observation_from_verifier(
                order, artifact_path=path, cycle_id="cycle-1", candidate_id="variant-a",
                at=END + timedelta(minutes=1),
            )
        observed = store._record_criterion_observation_from_verifier(
            order, artifact_path=path, cycle_id="cycle-1", candidate_id="variant-a",
            at=END + timedelta(minutes=1), capability=scheduler_state._VERIFIER_CAPABILITY,
        )
        record = observed["criterion_observations"][0]
        terminal = store.complete_verified(
            order, candidate_id="variant-a", cycle_id="cycle-1",
            criterion_artifact_sha256=record["sha256"], at=END + timedelta(minutes=2),
        )
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(terminal["variants"], ["variant-a"])
        self.assertEqual(store.load(order), terminal)
        duplicate = store.complete_verified(
            order, candidate_id="variant-a", cycle_id="cycle-1",
            criterion_artifact_sha256=record["sha256"], at=END + timedelta(minutes=2),
        )
        self.assertEqual(duplicate["revision"], terminal["revision"])
        with self.assertRaisesRegex(StateError, "durable cancellation reference"):
            store.terminalize(
                order, terminal_state="cancelled", candidate_id="variant-a",
                reason_code="operator_cancelled", at=END + timedelta(minutes=3),
            )

        evidence_path = self.workspace / record["observations"][0]["evidence"][0]["path"]
        evidence_path.write_text("drifted verifier evidence\n")
        with self.assertRaisesRegex(ContractError, "binding does not match"):
            store.load(order)

    def test_durable_verifier_lookup_drives_promotion_and_rejects_fabrication(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        self.cycle(store, order, 1)
        path = self.criterion_artifact(store, order, "cycle-1")
        head = store._record_criterion_observation_from_verifier(
            order, artifact_path=path, cycle_id="cycle-1", candidate_id="variant-a",
            at=END, capability=scheduler_state._VERIFIER_CAPABILITY,
        )
        record = head["criterion_observations"][0]
        loaded = store.load_verifier_observations(
            order, artifact_sha256=record["sha256"], cycle_id="cycle-1", candidate_id="variant-a"
        )
        assessment_path = self.evaluation_artifact(
            store, order, "cycle-1", source_path=record["candidate_source"]["path"]
        )
        assessment_head = store._record_evaluation_assessment_from_evaluator(
            order, artifact_path=assessment_path, cycle_id="cycle-1", candidate_id="variant-a",
            at=END, capability=scheduler_state._EVALUATOR_CAPABILITY,
        )
        assessment_record = assessment_head["evaluation_assessments"][0]
        assessment = store.load_evaluator_assessment(
            order, artifact_sha256=assessment_record["sha256"],
            cycle_id="cycle-1", candidate_id="variant-a",
        )
        decision = store.decide_verified_promotion(
            order, criterion_artifact_sha256=record["sha256"],
            evaluation_assessment_sha256=assessment_record["sha256"],
            candidate_id="variant-a", cycle_id="cycle-1",
        )
        self.assertEqual(decision.verdict, PromotionVerdict.ACCEPTED)

    def test_criterion_artifact_rejects_duplicate_softened_and_identity_drift(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        self.cycle(store, order, 1)

        duplicate = self.criterion_artifact(store, order, "cycle-1", name="duplicate-criteria.json")
        value = json.loads((self.workspace / duplicate).read_text())
        value["observations"][1]["criterion_id"] = value["observations"][0]["criterion_id"]
        (self.workspace / duplicate).write_text(json.dumps(value))
        with self.assertRaisesRegex(ContractError, "duplicate"):
            order.verify_criterion_observation_artifact(
                duplicate, cycle_id="cycle-1", candidate_id="variant-a"
            )

        softened = self.criterion_artifact(store, order, "cycle-1", name="softened-criteria.json")
        value = json.loads((self.workspace / softened).read_text())
        value["observations"].pop()
        (self.workspace / softened).write_text(json.dumps(value))
        with self.assertRaisesRegex(ContractError, "one observation per frozen criterion"):
            order.verify_criterion_observation_artifact(
                softened, cycle_id="cycle-1", candidate_id="variant-a"
            )

        drifted = self.criterion_artifact(store, order, "cycle-1", name="drifted-identity.json")
        with self.assertRaisesRegex(ContractError, "does not bind"):
            order.verify_criterion_observation_artifact(
                drifted, cycle_id="cycle-1", candidate_id="variant-b"
            )

        plan_drift = self.criterion_artifact(store, order, "cycle-1", name="plan-drift.json")
        value = json.loads((self.workspace / plan_drift).read_text())
        value["plan_sha256"] = "0" * 64
        (self.workspace / plan_drift).write_text(json.dumps(value))
        with self.assertRaisesRegex(ContractError, "does not bind"):
            order.verify_criterion_observation_artifact(
                plan_drift, cycle_id="cycle-1", candidate_id="variant-a"
            )

        source_drift = self.criterion_artifact(store, order, "cycle-1", name="source-drift.json")
        value = json.loads((self.workspace / source_drift).read_text())
        value["candidate_source"]["sha256"] = "0" * 64
        (self.workspace / source_drift).write_text(json.dumps(value))
        with self.assertRaisesRegex(ContractError, "candidate source SHA-256"):
            order.verify_criterion_observation_artifact(
                source_drift, cycle_id="cycle-1", candidate_id="variant-a"
            )

    def test_all_terminal_states_are_append_only_and_require_zero_pending_effects(self):
        cases = {
            "rejected": {"tests-pass": "violated", "evidence-preserved": "satisfied"},
            "inconclusive_budget_exhausted": {"tests-pass": "inconclusive", "evidence-preserved": "satisfied"},
        }
        for terminal_state, verdicts in cases.items():
            with self.subTest(terminal_state=terminal_state):
                store = self.store()
                order = self.order()
                store.create(order, at=START - timedelta(hours=1))
                self.cycle(store, order, 1)
                path = self.criterion_artifact(store, order, "cycle-1", verdicts=verdicts)
                observed = store._record_criterion_observation_from_verifier(
                    order, artifact_path=path, cycle_id="cycle-1", candidate_id="variant-a",
                    at=END + timedelta(minutes=1), capability=scheduler_state._VERIFIER_CAPABILITY,
                )
                digest_value = observed["criterion_observations"][0]["sha256"]
                head = store.terminalize(
                    order, terminal_state=terminal_state, candidate_id="variant-a", cycle_id="cycle-1",
                    criterion_artifact_sha256=digest_value, reason_code="budget_or_gate",
                    at=END + timedelta(minutes=2),
                )
                self.assertEqual(head["status"], terminal_state)
                self.assertEqual(store.load(order), head)

        expired = self.store()
        order = self.order()
        expired.create(order, at=START - timedelta(hours=1))
        with self.assertRaisesRegex(StateError, "execution deadline"):
            expired.terminalize(
                order, terminal_state="expired", candidate_id="variant-a",
                reason_code="bounded_stop", at=END - timedelta(microseconds=1),
            )
        expired_head = expired.terminalize(
            order, terminal_state="expired", candidate_id="variant-a",
            reason_code="bounded_stop", at=END,
        )
        self.assertEqual(expired_head["status"], "expired")
        self.assertEqual(
            expired.terminalize(
                order, terminal_state="expired", candidate_id="variant-a",
                reason_code="bounded_stop", at=END,
            )["revision"],
            expired_head["revision"],
        )

        cancelled = self.store()
        cancelled.create(order, at=START - timedelta(hours=1))
        cancellation_path = self.cancellation_artifact(cancelled, order, "cycle-1", event_id="cancel-1")
        with self.assertRaisesRegex(StateError, "recorded candidate cycle"):
            cancelled._record_cancellation_from_scheduler(
                order, artifact_path=cancellation_path, cycle_id="cycle-1", candidate_id="variant-a",
                slot_id="slot-1", attempt_id="attempt-1", cancellation_event_id="cancel-1",
                capability=scheduler_state._CANCELLATION_CAPABILITY, at=END)
        self.cycle(cancelled, order, 1)
        with self.assertRaisesRegex(StateError, "cancellation capability"):
            cancelled._record_cancellation_from_scheduler(
                order, artifact_path=cancellation_path, cycle_id="cycle-1", candidate_id="variant-a",
                slot_id="slot-1", attempt_id="attempt-1", cancellation_event_id="cancel-1", at=END)
        recorded = cancelled._record_cancellation_from_scheduler(
            order, artifact_path=cancellation_path, cycle_id="cycle-1", candidate_id="variant-a",
            slot_id="slot-1", attempt_id="attempt-1", cancellation_event_id="cancel-1",
            capability=scheduler_state._CANCELLATION_CAPABILITY, at=END)
        cancellation_sha = recorded["cancellations"][0]["sha256"]
        loaded = cancelled.load_cancellation(order, artifact_sha256=cancellation_sha,
            cycle_id="cycle-1", candidate_id="variant-a")
        self.assertEqual(loaded.cancellation_event_id, "cancel-1")
        with self.assertRaisesRegex(StateError, "recorded cancellation"):
            cancelled.terminalize(order, terminal_state="cancelled", candidate_id="variant-a",
                cycle_id="cycle-1", reason_code="operator_cancelled",
                cancellation_artifact_sha256="0" * 64, at=END)
        cancelled_head = cancelled.terminalize(
            order, terminal_state="cancelled", candidate_id="variant-a", cycle_id="cycle-1",
            reason_code="operator_cancelled", cancellation_artifact_sha256=cancellation_sha, at=END)
        self.assertEqual(cancelled_head["status"], "cancelled")
        retried = cancelled.terminalize(
            order, terminal_state="cancelled", candidate_id="variant-a", cycle_id="cycle-1",
            reason_code="operator_cancelled", cancellation_artifact_sha256=cancellation_sha, at=END)
        self.assertEqual(retried["revision"], cancelled_head["revision"])

        pending = self.store()
        order = self.order()
        pending.create(order, at=START - timedelta(hours=1))
        self.cycle(pending, order, 1, outcome="unknown", evidence=[],
            effect_id="attempt-pending", effect_status="pending")
        pending_cancel = self.cancellation_artifact(pending, order, "cycle-1",
            event_id="cancel-pending", name="pending-cancellation.json")
        with self.assertRaisesRegex(StateError, "not continuable"):
            pending._record_cancellation_from_scheduler(
                order, artifact_path=pending_cancel, cycle_id="cycle-1", candidate_id="variant-a",
                slot_id="slot-1", attempt_id="attempt-1", cancellation_event_id="cancel-pending",
                capability=scheduler_state._CANCELLATION_CAPABILITY, at=END + timedelta(minutes=1))

    def test_evaluation_is_derived_from_sealed_receipts_and_detects_drift(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        self.cycle(store, order, 1)

        declaration_only = self.evaluation_artifact(store, order, "cycle-1")
        value = json.loads((self.workspace / declaration_only).read_text())
        value["candidate_budget"] = {"calls": 1}
        with self.assertRaisesRegex(ContractError, "extra=.*candidate_budget"):
            order.verify_evaluation_assessment_artifact(
                self._rewrite_json(declaration_only, value), cycle_id="cycle-1", candidate_id="variant-a")

        path = self.evaluation_artifact(store, order, "cycle-1")
        artifact = json.loads((self.workspace / path).read_text())
        usage_path = self.workspace / artifact["usage_receipt"]["path"]
        usage = json.loads(usage_path.read_text())
        usage["baseline_budget"] = {"calls": 2}
        usage_path.write_text(json.dumps(usage))
        artifact["usage_receipt"]["sha256"] = digest(usage_path.read_bytes())
        (self.workspace / path).write_text(json.dumps(artifact))
        head = store._record_evaluation_assessment_from_evaluator(
            order, artifact_path=path, cycle_id="cycle-1", candidate_id="variant-a", at=END,
            capability=scheduler_state._EVALUATOR_CAPABILITY)
        record = head["evaluation_assessments"][0]
        loaded = store.load_evaluator_assessment(order, artifact_sha256=record["sha256"],
            cycle_id="cycle-1", candidate_id="variant-a")
        self.assertFalse(loaded.comparison.complete)
        self.assertIn("budgets are not matched", loaded.comparison.issues[0])
        usage_path.write_text(usage_path.read_text() + "\n")
        with self.assertRaisesRegex(ContractError, "usage_receipt"):
            store.load(order)

    def _rewrite_json(self, relative: str, value: dict) -> str:
        (self.workspace / relative).write_text(json.dumps(value))
        return relative

    def test_evaluator_policy_rejection_is_capability_owned_durable_and_idempotent(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        self.cycle(store, order, 1)
        assessment_path = self.evaluation_artifact(store, order, "cycle-1")
        assessment_head = store._record_evaluation_assessment_from_evaluator(
            order, artifact_path=assessment_path, cycle_id="cycle-1", candidate_id="variant-a", at=END,
            capability=scheduler_state._EVALUATOR_CAPABILITY)
        assessment = assessment_head["evaluation_assessments"][0]
        loaded = store.load_evaluator_assessment(order, artifact_sha256=assessment["sha256"],
            cycle_id="cycle-1", candidate_id="variant-a")
        self.assertTrue(loaded.comparison.complete)
        path = self.policy_artifact(store, order, "cycle-1", reason_code="criterion_softening",
            assessment_sha256=assessment["sha256"], source_path=assessment["candidate_source"]["path"],
            proposed=["tests-pass"])
        with self.assertRaisesRegex(StateError, "evaluator capability"):
            store._record_policy_rejection_from_evaluator(
                order, artifact_path=path, cycle_id="cycle-1", candidate_id="variant-a", at=END)
        observed = store._record_policy_rejection_from_evaluator(
            order, artifact_path=path, cycle_id="cycle-1", candidate_id="variant-a", at=END,
            capability=scheduler_state._EVALUATOR_CAPABILITY)
        record = observed["policy_observations"][0]
        terminal = store.terminalize(
            order, terminal_state="rejected", candidate_id="variant-a", cycle_id="cycle-1",
            reason_code="criterion_softening", policy_artifact_sha256=record["sha256"], at=END)
        retry = store.terminalize(
            order, terminal_state="rejected", candidate_id="variant-a", cycle_id="cycle-1",
            reason_code="criterion_softening", policy_artifact_sha256=record["sha256"], at=END)
        self.assertEqual(retry["revision"], terminal["revision"])
        usage = self.workspace / assessment["usage_receipt"]["path"]
        usage.write_text(usage.read_text() + "\n")
        with self.assertRaisesRegex(ContractError, "usage_receipt"):
            store.load(order)

        forged = self.store()
        forged.create(order, at=START - timedelta(hours=1))
        self.cycle(forged, order, 1)
        assessment_path = self.evaluation_artifact(forged, order, "cycle-1")
        assessment_head = forged._record_evaluation_assessment_from_evaluator(
            order, artifact_path=assessment_path, cycle_id="cycle-1", candidate_id="variant-a", at=END,
            capability=scheduler_state._EVALUATOR_CAPABILITY)
        assessment = assessment_head["evaluation_assessments"][0]
        bad = self.policy_artifact(forged, order, "cycle-1", reason_code="criterion_softening",
            assessment_sha256=assessment["sha256"], source_path=assessment["candidate_source"]["path"],
            proposed=[c.criterion_id for c in order.acceptance_criteria])
        with self.assertRaisesRegex(ContractError, "omitted frozen"):
            forged._record_policy_rejection_from_evaluator(
                order, artifact_path=bad, cycle_id="cycle-1", candidate_id="variant-a", at=END,
                capability=scheduler_state._EVALUATOR_CAPABILITY)

    def test_owner_path_and_monotonic_timestamp_protections(self):
        order = self.order()
        store = self.store()
        store.create(order, at=START - timedelta(hours=1))
        store.record_provider_thread(order, provider="p", thread_id="t", at=START + timedelta(minutes=1))
        with self.assertRaisesRegex(StateError, "monotonic"):
            self.cycle(store, order, 1, at=START)
        other_owner = DurableSessionStore(self.workspace, store.directory.relative_to(self.workspace).as_posix(), "other-owner")
        with self.assertRaisesRegex(StateError, "owner"):
            other_owner.load(order)
        with self.assertRaisesRegex(StateError, "normalized"):
            DurableSessionStore(self.workspace, "runtime/../escape", "owner")


if __name__ == "__main__":
    unittest.main()
