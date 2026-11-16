from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from mentor.scheduler import DurableSessionStore, WorkOrder
from mentor.scheduler.runner import reconcile_attempt, run_cycles

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


class Flag:
    def __init__(self, value=False): self.value = value
    def is_set(self): return self.value


class SchedulerRunnerTest(unittest.TestCase):
    def setUp(self):
        parent = ROOT / "runtime" / "test-tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="scheduler-runner-", dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        (self.workspace / "plans").mkdir()
        self.plan = self.workspace / "plans/plan.md"
        self.acceptance = self.workspace / "plans/acceptance.json"
        self.plan.write_text("# Frozen synthetic plan\nNo credentials.\n")
        self.acceptance.write_text(json.dumps({"schema_version": 1, "criteria": [
            {"criterion_id": "quality", "critical": False},
            {"criterion_id": "safety", "critical": True},
        ]}))
        self.at = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
        self.order = WorkOrder.from_json(json.dumps(self.payload()), self.workspace)
        self.store = DurableSessionStore(self.workspace, "runtime/session", "mentor-owner")
        self.store.create(self.order, at=self.at)
        self.profile = {"codex_bin": "/synthetic/codex", "model": "synthetic-model",
                        "effort": "high", "timeout_seconds": 200,
                        "auth_home": str(self.workspace / ".job-runtime/auth"),
                        "executor": "trusted-only"}
        self.calls = []

    def digest(self, path): return hashlib.sha256(path.read_bytes()).hexdigest()

    def payload(self):
        return {
            "schema_version": 1, "work_order_id": "work-1",
            "logical_session": {"logical_session_id": "logical-1",
                                "provider_thread_mode": "ephemeral_threads", "max_provider_threads": 4},
            "plan": {"path": "plans/plan.md", "sha256": self.digest(self.plan)},
            "acceptance": {"path": "plans/acceptance.json", "sha256": self.digest(self.acceptance)},
            "execution": {"starts_at": (self.at - timedelta(hours=1)).isoformat(),
                          "ends_at": (self.at + timedelta(seconds=150)).isoformat(),
                          "turn_timeout_seconds": 100, "max_turns": 4},
            "supervision": {"max_no_progress_cycles": 4, "max_repeated_actions": 4,
                            "max_interventions": 2},
            "evidence_policy": {"record_all_variants": True, "max_variants": 2,
                                "max_reused_evaluations": 0, "worker_holdout_access": False},
            "completion": {"required_event_kinds": ["provider_thread", "cycle"],
                           "require_no_pending_effects": True,
                           "require_acceptance_hash_match": True},
        }

    def fake_model(self, profile, prompt, workspace, run_dir, context=None):
        self.calls.append({"profile": profile, "prompt": json.loads(prompt), "run_dir": run_dir,
                           "context": context})
        run_dir.mkdir(parents=True)
        schema = context["response_schema"]
        cycle = schema["properties"]["cycle_id"]["const"]
        variant = schema["properties"]["variant_id"]["const"]
        output = {"schema_version": 1, "cycle_id": cycle, "variant_id": variant,
                  "action_id": "inspect-plan", "criterion_updates": []}
        response = run_dir / "last-message.txt"
        response.write_text(json.dumps(output))
        relative = str(response.relative_to(workspace))
        return {"status": "succeeded", "code": "MODEL_TURN_COMPLETED", "receipt": {
            "thread_id": f"thread-{len(self.calls)}", "response_path": relative,
            "response_sha256": self.digest(response), "turn_completed": True,
            "requested_model": profile["model"], "observed_model": profile["model"],
            "automatic_retry": False, "fallback_used": False,
        }}

    def verifier(self, *, work_order, cycle_id, output, verifier_directory, deadline, cancel_event):
        evidence = verifier_directory / "evidence.txt"
        evidence.write_text("deterministically verified\n")
        artifact = verifier_directory / "progress.json"
        artifact.write_text(json.dumps({
            "schema_version": 1, "work_order_id": work_order.work_order_id,
            "plan_sha256": work_order.plan.sha256,
            "acceptance_sha256": work_order.acceptance.sha256,
            "cycle_id": cycle_id,
            "observations": [{"evidence_id": f"evidence-{cycle_id}",
                              "evidence_path": str(evidence.relative_to(self.workspace)),
                              "sha256": self.digest(evidence)}],
        }))
        return str(artifact.relative_to(self.workspace))

    def journals(self):
        return sorted((self.workspace / ".job-runtime/mentor-attempts/logical-1").glob("*/journal.json"))

    def test_one_and_sequential_cycles_commit_unique_runs(self):
        result = run_cycles(self.order, self.store, self.profile, self.verifier,
                            model_call=self.fake_model, max_cycles_this_run=2, clock=lambda: self.at)
        self.assertEqual((result["status"], result["cycles_attempted"]), ("succeeded", 2))
        head = self.store.load(self.order)
        self.assertEqual((head["turns_used"], len(head["provider_threads"])), (2, 2))
        self.assertEqual(len({call["run_dir"] for call in self.calls}), 2)
        self.assertEqual([json.loads(path.read_text())["phase"] for path in self.journals()],
                         ["ledger_committed", "ledger_committed"])

    def test_turn_thread_window_timeout_and_profile_bounds(self):
        captured = {}
        def model(*args, **kwargs):
            captured.update(profile=args[0], context=kwargs["context"])
            return self.fake_model(*args, **kwargs)
        invalid = run_cycles(self.order, self.store, {**self.profile,
                                                      "future_transport_key": "reject-downstream"},
                             self.verifier, model_call=model, clock=lambda: self.at)
        self.assertEqual((invalid["code"], len(self.journals())),
                         ("MENTOR_MODEL_PROFILE_INVALID", 0))
        result = run_cycles(self.order, self.store, {**self.profile, "timeout_seconds": 120},
                            self.verifier, model_call=model, clock=lambda: self.at + timedelta(seconds=75))
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(captured["profile"]["timeout_seconds"], 75)
        self.assertNotIn("executor", captured["profile"])
        self.assertNotIn("future_transport_key", captured["profile"])
        event_at = self.at + timedelta(seconds=75)
        self.store.record_provider_thread(self.order, provider="x", thread_id="extra-1", at=event_at)
        self.store.record_provider_thread(self.order, provider="x", thread_id="extra-2", at=event_at)
        self.store.record_provider_thread(self.order, provider="x", thread_id="extra-3", at=event_at)
        blocked = run_cycles(self.order, self.store, self.profile, self.verifier,
                             model_call=self.fake_model, clock=lambda: self.at)
        self.assertEqual(blocked["code"], "MENTOR_PROVIDER_THREAD_BUDGET_EXHAUSTED")
        late = run_cycles(self.order, self.store, self.profile, self.verifier,
                          model_call=self.fake_model, clock=lambda: self.at + timedelta(seconds=151))
        self.assertEqual(late["status"], "blocked")

    def test_real_transport_timeout_contract_rejects_boolean(self):
        result = run_cycles(
            self.order,
            self.store,
            {**self.profile, "timeout_seconds": True},
            self.verifier,
            model_call=self.fake_model,
            clock=lambda: self.at,
        )
        self.assertEqual((result["status"], result["code"], len(self.calls)),
                         ("blocked", "MENTOR_MODEL_TIMEOUT_INVALID", 0))

    def test_frozen_drift_before_second_call_stops(self):
        original = self.store.record_cycle
        def record_then_drift(*args, **kwargs):
            value = original(*args, **kwargs)
            self.plan.write_text("drifted\n")
            return value
        with mock.patch.object(self.store, "record_cycle", side_effect=record_then_drift):
            result = run_cycles(self.order, self.store, self.profile, self.verifier,
                                model_call=self.fake_model, max_cycles_this_run=2, clock=lambda: self.at)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["code"], "MENTOR_STATE_REVALIDATION_FAILED")

    def test_closed_schema_and_hash_mismatch_are_unknown_without_retry(self):
        def malformed(profile, prompt, workspace, run_dir, context=None):
            result = self.fake_model(profile, prompt, workspace, run_dir, context=context)
            path = workspace / result["receipt"]["response_path"]
            path.write_text('{"unexpected":true}')
            result["receipt"]["response_sha256"] = self.digest(path)
            return result
        result = run_cycles(self.order, self.store, self.profile, self.verifier,
                            model_call=malformed, max_cycles_this_run=3, clock=lambda: self.at)
        self.assertEqual((result["status"], len(self.calls)), ("unknown", 1))
        self.assertEqual(self.store.load(self.order)["status"], "active")
        self.assertEqual(len(self.store.load(self.order)["provider_threads"]), 1)

    def test_hash_mismatch_is_fenced(self):
        def bad_hash(profile, prompt, workspace, run_dir, context=None):
            result = self.fake_model(profile, prompt, workspace, run_dir, context=context)
            result["receipt"]["response_sha256"] = "0" * 64
            return result
        result = run_cycles(self.order, self.store, self.profile, self.verifier,
                            model_call=bad_hash, clock=lambda: self.at)
        self.assertEqual((result["status"], result["code"]),
                         ("unknown", "MENTOR_MODEL_RESPONSE_HASH_MISMATCH"))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.store.load(self.order)["provider_threads"]), 1)

    def test_transport_unknown_exception_and_verifier_failure_stop_without_retry(self):
        def unknown(*args, **kwargs):
            self.calls.append("called")
            return {"status": "unknown", "code": "MODEL_DEADLINE_EXCEEDED", "receipt": {}}
        result = run_cycles(self.order, self.store, self.profile, self.verifier,
                            model_call=unknown, max_cycles_this_run=3, clock=lambda: self.at)
        self.assertEqual((result["status"], len(self.calls)), ("unknown", 1))

    def test_verifier_failure_claims_no_progress(self):
        def broken_verifier(**kwargs): raise RuntimeError("private verifier detail")
        result = run_cycles(self.order, self.store, self.profile, broken_verifier,
                            model_call=self.fake_model, max_cycles_this_run=2, clock=lambda: self.at)
        self.assertEqual((result["status"], result["code"]), ("failed", "MENTOR_VERIFIER_FAILED"))
        head = self.store.load(self.order)
        self.assertEqual((head["verified_evidence_ids"], head["status"]), ([], "active"))
        self.assertNotIn("private verifier detail", json.dumps(result))

    def test_pending_nonactive_and_cancellation_block_dispatch(self):
        cancelled = run_cycles(self.order, self.store, self.profile, self.verifier,
                               model_call=self.fake_model, cancel_event=Flag(True), clock=lambda: self.at)
        self.assertEqual((cancelled["code"], len(self.calls)), ("MENTOR_RUN_CANCELLED", 0))
        self.store.record_cycle(self.order, cycle_id="prior-unknown", variant_id="baseline",
                                action_sha256="a" * 64, outcome="unknown",
                                verified_evidence_artifact_path=None,
                                effect_id="prior-effect", effect_status="pending", at=self.at)
        blocked = run_cycles(self.order, self.store, self.profile, self.verifier,
                             model_call=self.fake_model, clock=lambda: self.at)
        self.assertEqual((blocked["code"], len(self.calls)), ("MENTOR_SESSION_NOT_ACTIVE", 0))

    def test_prepared_crash_blocks_replay_and_explicitly_fences(self):
        def crash(*args, **kwargs):
            self.calls.append("dispatched")
            raise KeyboardInterrupt("synthetic process death")
        with self.assertRaises(KeyboardInterrupt):
            run_cycles(self.order, self.store, self.profile, self.verifier,
                       model_call=crash, clock=lambda: self.at)
        self.assertEqual(json.loads(self.journals()[0].read_text())["phase"], "prepared")
        blocked = run_cycles(self.order, self.store, self.profile, self.verifier,
                             model_call=self.fake_model, clock=lambda: self.at)
        self.assertEqual((blocked["code"], len(self.calls)),
                         ("MENTOR_UNFINISHED_ATTEMPT_REQUIRES_RECONCILIATION", 1))
        attempt = self.journals()[0].parent.name
        recovered = reconcile_attempt(self.order, self.store, attempt, self.verifier, clock=lambda: self.at)
        self.assertEqual((recovered["status"], self.store.load(self.order)["status"]),
                         ("unknown", "active"))
        self.assertEqual(self.store.load(self.order)["pending_effects"], [])

    def test_unknown_fence_revalidates_full_journal_identity(self):
        def crash(*args, **kwargs): raise KeyboardInterrupt("crash")
        with self.assertRaises(KeyboardInterrupt):
            run_cycles(self.order, self.store, self.profile, self.verifier,
                       model_call=crash, clock=lambda: self.at)
        path = self.journals()[0]
        journal = json.loads(path.read_text())
        journal["identity"]["acceptance_sha256"] = "0" * 64
        path.write_text(json.dumps(journal)); path.chmod(0o600)
        result = reconcile_attempt(self.order, self.store, journal["identity"]["attempt_id"],
                                   self.verifier, clock=lambda: self.at)
        self.assertEqual((result["code"], self.store.load(self.order)["turns_used"]),
                         ("MENTOR_ATTEMPT_IDENTITY_MISMATCH", 0))

    def test_model_returned_crash_reconciles_without_model_replay(self):
        from mentor.scheduler import runner
        with mock.patch.object(runner, "_commit_retained", side_effect=KeyboardInterrupt("crash")):
            with self.assertRaises(KeyboardInterrupt):
                run_cycles(self.order, self.store, self.profile, self.verifier,
                           model_call=self.fake_model, clock=lambda: self.at)
        journal = json.loads(self.journals()[0].read_text())
        self.assertEqual(journal["phase"], "model_returned")
        recovered = reconcile_attempt(self.order, self.store, journal["identity"]["attempt_id"],
                                      self.verifier, clock=lambda: self.at)
        self.assertEqual((recovered["status"], len(self.calls)), ("succeeded", 1))

    def test_provider_thread_before_cycle_crash_reconciles_without_duplicate(self):
        original = self.store.record_cycle
        with mock.patch.object(self.store, "record_cycle", side_effect=KeyboardInterrupt("after-thread")):
            with self.assertRaises(KeyboardInterrupt):
                run_cycles(self.order, self.store, self.profile, self.verifier,
                           model_call=self.fake_model, clock=lambda: self.at)
        head = self.store.load(self.order)
        self.assertEqual((len(head["provider_threads"]), head["turns_used"]), (1, 0))
        journal = json.loads(self.journals()[0].read_text())
        recovered = reconcile_attempt(self.order, self.store, journal["identity"]["attempt_id"],
                                      self.verifier, clock=lambda: self.at)
        self.assertEqual((recovered["status"], len(self.calls)), ("succeeded", 1))
        self.assertEqual((len(self.store.load(self.order)["provider_threads"]),
                          self.store.load(self.order)["turns_used"]), (1, 1))

    def test_successful_journal_contains_only_sanitized_bindings(self):
        result = run_cycles(self.order, self.store, self.profile, self.verifier,
                            model_call=self.fake_model, clock=lambda: self.at)
        journal = json.loads(self.journals()[0].read_text())
        self.assertEqual((result["status"], journal["phase"]), ("succeeded", "ledger_committed"))
        serialized = json.dumps(journal)
        self.assertNotIn("Frozen synthetic plan", serialized)
        self.assertNotIn("auth_home", serialized)
        self.assertNotIn("criterion_updates", serialized)

    def test_scheduled_external_unknown_maps_only_trusted_engine_effect(self):
        def unknown(*args, **kwargs):
            self.calls.append("scheduled")
            return {"status": "unknown", "code": "MODEL_DEADLINE_EXCEEDED", "receipt": {}}
        result = run_cycles(self.order, self.store, self.profile, self.verifier,
                            model_call=unknown, external_engine_attempt_id="engine-attempt-17",
                            clock=lambda: self.at)
        head = self.store.load(self.order)
        self.assertEqual((result["status"], head["status"], head["pending_effects"]),
                         ("unknown", "blocked_pending_effect", ["engine-attempt-17"]))
        journal = json.loads(self.journals()[0].read_text())
        self.assertEqual(journal["identity"]["attempt_type"], "scheduled_external")

    def test_manual_unknown_is_fenced_without_engine_pending_effect(self):
        def unknown(*args, **kwargs):
            self.calls.append("manual")
            return {"status": "unknown", "code": "MODEL_DEADLINE_EXCEEDED", "receipt": {}}
        first = run_cycles(self.order, self.store, self.profile, self.verifier,
                           model_call=unknown, clock=lambda: self.at)
        second = run_cycles(self.order, self.store, self.profile, self.verifier,
                            model_call=self.fake_model, clock=lambda: self.at)
        self.assertEqual((first["status"], self.store.load(self.order)["pending_effects"]),
                         ("unknown", []))
        self.assertEqual((second["code"], len(self.calls)),
                         ("MENTOR_UNFINISHED_ATTEMPT_REQUIRES_RECONCILIATION", 1))

    def test_known_pre_dispatch_failure_closes_without_pending_effect(self):
        def rejected(profile, prompt, workspace, run_dir, context=None):
            self.calls.append("rejected")
            return {"status": "failed", "code": "MODEL_AUTH_REQUIRED",
                    "receipt": {"requested_model": profile["model"]}}
        result = run_cycles(self.order, self.store, self.profile, self.verifier,
                            model_call=rejected, clock=lambda: self.at)
        head = self.store.load(self.order)
        journal = json.loads(self.journals()[0].read_text())
        self.assertEqual((result["status"], result["code"]), ("failed", "MODEL_AUTH_REQUIRED"))
        self.assertEqual((head["status"], head["pending_effects"], journal["phase"]),
                         ("active", [], "ledger_committed"))

    def test_known_pre_dispatch_retryable_preserves_classification(self):
        def busy(profile, prompt, workspace, run_dir, context=None):
            self.calls.append("busy")
            return {"status": "retryable", "code": "MODEL_AUTH_CACHE_BUSY",
                    "receipt": {"requested_model": profile["model"]}}
        result = run_cycles(self.order, self.store, self.profile, self.verifier,
                            model_call=busy, clock=lambda: self.at)
        head = self.store.load(self.order)
        self.assertEqual((result["status"], result["code"], head["pending_effects"], head["turns_used"]),
                         ("retryable", "MODEL_AUTH_CACHE_BUSY", [], 0))
        self.assertEqual(json.loads(self.journals()[0].read_text())["phase"], "ledger_committed")

    def test_transient_provider_failure_remains_retryable_without_replay(self):
        def transient(profile, prompt, workspace, run_dir, context=None):
            self.calls.append("transient")
            return {
                "status": "retryable",
                "code": "MODEL_TRANSIENT_FAILURE",
                "receipt": {
                    "started_at": self.at.isoformat(),
                    "ended_at": (self.at + timedelta(seconds=1)).isoformat(),
                    "requested_model": profile["model"],
                    "automatic_retry": False,
                    "fallback_used": False,
                    "exit_code": 1,
                },
            }
        result = run_cycles(
            self.order,
            self.store,
            self.profile,
            self.verifier,
            model_call=transient,
            max_cycles_this_run=2,
            clock=lambda: self.at,
        )
        self.assertEqual((result["status"], result["code"], len(self.calls)),
                         ("retryable", "MODEL_TRANSIENT_FAILURE", 1))
        head = self.store.load(self.order)
        self.assertEqual((head["pending_effects"], head["turns_used"]), ([], 0))

    def test_real_shape_cancelled_before_start_remains_retryable(self):
        def cancelled(profile, prompt, workspace, run_dir, context=None):
            self.calls.append("cancelled")
            return {
                "status": "retryable",
                "code": "MODEL_CANCELLED_BEFORE_START",
                "receipt": {
                    "started_at": self.at.isoformat(),
                    "requested_model": profile["model"],
                    "automatic_retry": False,
                    "fallback_used": False,
                },
            }
        result = run_cycles(
            self.order,
            self.store,
            self.profile,
            self.verifier,
            model_call=cancelled,
            clock=lambda: self.at,
        )
        self.assertEqual((result["status"], result["code"]),
                         ("retryable", "MODEL_CANCELLED_BEFORE_START"))
        self.assertEqual(self.store.load(self.order)["pending_effects"], [])
        self.assertEqual(json.loads(self.journals()[0].read_text())["phase"], "ledger_committed")

    def test_concurrent_runners_allow_only_one_model_dispatch(self):
        entered, release = threading.Event(), threading.Event()
        first_result = []
        def slow(profile, prompt, workspace, run_dir, context=None):
            entered.set()
            self.assertTrue(release.wait(2))
            return self.fake_model(profile, prompt, workspace, run_dir, context=context)
        thread = threading.Thread(target=lambda: first_result.append(run_cycles(
            self.order, self.store, self.profile, self.verifier,
            model_call=slow, clock=lambda: self.at)))
        thread.start(); self.assertTrue(entered.wait(2))
        second = run_cycles(self.order, self.store, self.profile, self.verifier,
                            model_call=self.fake_model, clock=lambda: self.at)
        release.set(); thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(second["code"], "MENTOR_SESSION_DISPATCH_BUSY")
        self.assertEqual((len(self.calls), first_result[0]["status"]), (1, "succeeded"))

    def test_provider_event_orphan_recovers_without_model_replay(self):
        from mentor.scheduler import state
        with mock.patch.object(state, "_atomic_write", side_effect=KeyboardInterrupt("after-event-fsync")):
            with self.assertRaises(KeyboardInterrupt):
                run_cycles(self.order, self.store, self.profile, self.verifier,
                           model_call=self.fake_model, clock=lambda: self.at)
        journal = json.loads(self.journals()[0].read_text())
        self.assertEqual(journal["phase"], "model_returned")
        recovered = reconcile_attempt(self.order, self.store, journal["identity"]["attempt_id"],
                                      self.verifier, clock=lambda: self.at)
        head = self.store.load(self.order)
        self.assertEqual((recovered["status"], len(self.calls), len(head["provider_threads"]), head["turns_used"]),
                         ("succeeded", 1, 1, 1))

    def test_recovery_after_window_uses_original_event_timestamp(self):
        from mentor.scheduler import runner
        with mock.patch.object(runner, "_commit_retained", side_effect=KeyboardInterrupt("crash")):
            with self.assertRaises(KeyboardInterrupt):
                run_cycles(self.order, self.store, self.profile, self.verifier,
                           model_call=self.fake_model, clock=lambda: self.at)
        journal = json.loads(self.journals()[0].read_text())
        recovered = reconcile_attempt(
            self.order, self.store, journal["identity"]["attempt_id"], self.verifier,
            clock=lambda: self.order.execution.ends_at + timedelta(hours=1))
        self.assertEqual((recovered["status"], self.store.load(self.order)["turns_used"]),
                         ("succeeded", 1))

    def test_secret_bearing_plans_are_rejected_before_intent(self):
        secrets = ["api_key=abcdefghijk", "Authorization: Bearer abcdefghijk",
                   "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"]
        for index, secret in enumerate(secrets):
            with self.subTest(index=index):
                self.plan.write_text(secret)
                order = WorkOrder.from_json(json.dumps(self.payload()), self.workspace)
                store = DurableSessionStore(self.workspace, f"runtime/secret-{index}", "mentor-owner")
                store.create(order, at=self.at)
                result = run_cycles(order, store, self.profile, self.verifier,
                                    model_call=self.fake_model, clock=lambda: self.at)
                self.assertEqual(result["code"], "MENTOR_PLAN_SECRET_REJECTED")
                self.assertEqual(list((self.workspace / ".job-runtime/mentor-attempts/logical-1").glob("*/journal.json")), [])
        self.assertEqual(self.calls, [])

    def test_symlinked_runtime_root_is_rejected_before_writes(self):
        workspace = self.workspace / "symlink-workspace"
        workspace.mkdir(); (workspace / "plans").mkdir()
        plan = workspace / "plans/plan.md"; acceptance = workspace / "plans/acceptance.json"
        plan.write_text("safe plan")
        acceptance.write_text(json.dumps({"schema_version": 1, "criteria": [
            {"criterion_id": "quality", "critical": False}]}))
        target = self.workspace / "outside-state"; target.mkdir()
        (workspace / ".job-runtime").symlink_to(target, target_is_directory=True)
        payload = self.payload()
        payload["plan"] = {"path": "plans/plan.md", "sha256": self.digest(plan)}
        payload["acceptance"] = {"path": "plans/acceptance.json", "sha256": self.digest(acceptance)}
        payload["logical_session"]["logical_session_id"] = "symlink-session"
        order = WorkOrder.from_json(json.dumps(payload), workspace)
        store = DurableSessionStore(workspace, "runtime/session", "mentor-owner")
        store.create(order, at=self.at)
        result = run_cycles(order, store, self.profile, self.verifier,
                            model_call=self.fake_model, clock=lambda: self.at)
        self.assertEqual((result["code"], len(self.calls)), ("MENTOR_RUNTIME_ROOT_SYMLINK", 0))

    def test_runner_prompt_bound_fails_before_intent(self):
        self.plan.write_bytes(b"x" * 524_000)
        order = WorkOrder.from_json(json.dumps(self.payload()), self.workspace)
        store = DurableSessionStore(self.workspace, "runtime/large-plan", "mentor-owner")
        store.create(order, at=self.at)
        result = run_cycles(order, store, self.profile, self.verifier,
                            model_call=self.fake_model, clock=lambda: self.at)
        self.assertEqual((result["code"], len(self.calls), len(self.journals())),
                         ("MENTOR_MODEL_PROMPT_TOO_LARGE", 0, 0))

    def test_preflight_no_progress_and_repeated_limits_block_dispatch(self):
        payload = self.payload()
        payload["supervision"]["max_no_progress_cycles"] = 0
        order = WorkOrder.from_json(json.dumps(payload), self.workspace)
        store = DurableSessionStore(self.workspace, "runtime/no-progress-zero", "mentor-owner")
        store.create(order, at=self.at)
        result = run_cycles(order, store, self.profile, self.verifier,
                            model_call=self.fake_model, clock=lambda: self.at)
        self.assertEqual((result["code"], len(self.calls)), ("MENTOR_NO_PROGRESS_BUDGET_EXHAUSTED", 0))
        payload = self.payload(); payload["supervision"]["max_repeated_actions"] = 0
        order = WorkOrder.from_json(json.dumps(payload), self.workspace)
        store = DurableSessionStore(self.workspace, "runtime/repeated-zero", "mentor-owner")
        store.create(order, at=self.at)
        result = run_cycles(order, store, self.profile, self.verifier,
                            model_call=self.fake_model, clock=lambda: self.at)
        self.assertEqual((result["code"], len(self.calls)), ("MENTOR_REPEATED_ACTION_BUDGET_EXHAUSTED", 0))

    def test_verifier_invalid_artifact_and_timeout_commit_failed_cycle(self):
        def invalid(**kwargs):
            path = kwargs["verifier_directory"] / "invalid.json"
            path.write_text("{}")
            return str(path.relative_to(self.workspace))
        invalid_result = run_cycles(self.order, self.store, self.profile, invalid,
                                    model_call=self.fake_model, clock=lambda: self.at)
        self.assertEqual((invalid_result["status"], invalid_result["code"]),
                         ("failed", "MENTOR_VERIFIER_ARTIFACT_INVALID"))
        self.assertEqual(json.loads(self.journals()[0].read_text())["phase"], "ledger_committed")

    def test_hung_verifier_is_killed_at_parent_enforced_timeout(self):
        def timeout_verifier(**kwargs):
            time.sleep(3)
            return None
        started = time.monotonic()
        result = run_cycles(
            self.order,
            self.store,
            {**self.profile, "timeout_seconds": 1},
            timeout_verifier,
            model_call=self.fake_model,
            clock=lambda: self.at,
        )
        elapsed = time.monotonic() - started
        self.assertEqual((result["status"], result["code"]), ("failed", "MENTOR_VERIFIER_TIMEOUT"))
        self.assertLess(elapsed, 2.0)
        self.assertEqual(json.loads(self.journals()[0].read_text())["phase"], "ledger_committed")

    def test_semantic_action_hash_excludes_cycle_identity(self):
        first = run_cycles(self.order, self.store, self.profile, self.verifier,
                           model_call=self.fake_model, clock=lambda: self.at)
        second = run_cycles(self.order, self.store, self.profile, self.verifier,
                            model_call=self.fake_model, clock=lambda: self.at)
        self.assertEqual((first["status"], second["status"]), ("succeeded", "succeeded"))
        actions = []
        for path in sorted(self.store.events_directory.glob("*.json")):
            event = json.loads(path.read_text())
            if event["kind"] == "cycle": actions.append(event["data"]["action_sha256"])
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0], actions[1])

    def test_committed_failed_recovery_returns_actual_outcome(self):
        result = run_cycles(self.order, self.store, self.profile, lambda **kwargs: None,
                            model_call=self.fake_model, clock=lambda: self.at)
        journal = json.loads(self.journals()[0].read_text())
        recovered = reconcile_attempt(self.order, self.store, journal["identity"]["attempt_id"],
                                      self.verifier, clock=lambda: self.at)
        self.assertEqual((result["status"], recovered["status"], recovered["outcome"], recovered["progressed"]),
                         ("failed", "failed", "failed", False))


if __name__ == "__main__":
    unittest.main()
