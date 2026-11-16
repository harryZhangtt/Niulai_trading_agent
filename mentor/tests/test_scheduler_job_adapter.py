from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from mentor.scheduler import DurableSessionStore, WorkOrder
from mentor.scheduler import job_adapter

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


class SchedulerJobAdapterTest(unittest.TestCase):
    def setUp(self):
        parent = ROOT / "runtime/test-tmp"; parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="job-adapter-", dir=parent); self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.runtime = self.workspace / ".job-runtime"; self.runtime.mkdir(mode=0o700)
        (self.workspace / "plans").mkdir(); (self.workspace / "candidate").mkdir()
        self.at = datetime(2026, 11, 4, 10, tzinfo=UTC)
        self.plan = self.workspace / "plans/plan.md"; self.plan.write_text("synthetic binding task\n")
        self.acceptance = self.workspace / "plans/acceptance.json"
        self.acceptance.write_text(json.dumps({"schema_version": 1, "criteria": [
            {"criterion_id": "closed-response", "critical": True},
            {"criterion_id": "frozen-binding", "critical": True}]}))
        self.order_path = self.workspace / "plans/work-order.json"
        self.order_path.write_text(json.dumps(self.payload()))
        self.order = WorkOrder.from_json(self.order_path.read_text(), self.workspace)
        self.store = DurableSessionStore(self.workspace, ".job-runtime/session", "mentor-owner")
        self.store.create(self.order, at=self.at)
        self.source = self.workspace / "candidate/source.py"; self.source.write_text("VALUE=1\n")
        self.manifest = self.workspace / "candidate/manifest.json"; self.write_manifest()
        self.profile = {"codex_bin": "/synthetic/codex", "model": "synthetic-model", "effort": "high",
                        "timeout_seconds": 30, "auth_home": str(self.runtime / "auth"), "executor": "readiness"}
        self.options = {"work_order_path": "plans/work-order.json", "state_directory": ".job-runtime/session",
            "owner_id": "mentor-owner", "candidate_manifest_path": "candidate/manifest.json",
            "candidate_manifest_sha256": self.digest(self.manifest),
            "required_source_paths": ["candidate/source.py"], "expected_model_profile": "mentor-profile",
            "model_profile_sha256": job_adapter.profile_fingerprint(self.profile),
            "verifier_kind": "synthetic_bindings_v1"}
        self.context = {"attempt_id": "attempt-17", "slot_id": "mentor:once:slot",
                        "scheduled_at": self.at.isoformat(), "attempt_no": 1}
        self.cancel = threading.Event()
        self.runtime_context = {"version": 1, "model_profile_name": "mentor-profile",
                                "model_profile": self.profile, "cancel_event": self.cancel}

    def digest(self, path): return hashlib.sha256(path.read_bytes()).hexdigest()

    def payload(self):
        return {"schema_version": 1, "work_order_id": "work-1",
            "logical_session": {"logical_session_id": "logical-1", "provider_thread_mode": "ephemeral_threads",
                                "max_provider_threads": 4},
            "plan": {"path": "plans/plan.md", "sha256": self.digest(self.plan)},
            "acceptance": {"path": "plans/acceptance.json", "sha256": self.digest(self.acceptance)},
            "execution": {"starts_at": (self.at-timedelta(hours=1)).isoformat(),
                          "ends_at": (self.at+timedelta(hours=1)).isoformat(),
                          "turn_timeout_seconds": 60, "max_turns": 4},
            "supervision": {"max_no_progress_cycles": 4, "max_repeated_actions": 4, "max_interventions": 1},
            "evidence_policy": {"record_all_variants": True, "max_variants": 2,
                                "max_reused_evaluations": 0, "worker_holdout_access": False},
            "completion": {"required_event_kinds": ["provider_thread", "cycle"],
                           "require_no_pending_effects": True, "require_acceptance_hash_match": True}}

    def write_manifest(self, sources=None):
        sources = sources if sources is not None else [{"path": "candidate/source.py", "sha256": self.digest(self.source)}]
        self.manifest.write_text(json.dumps({"schema_version": 1, "sources": sources}))

    def progress(self, work_order, cycle_id):
        directory = self.runtime / f"mentor-verifier/logical-1/{cycle_id}"; directory.mkdir(parents=True, mode=0o700)
        evidence = directory / "evidence.json"; evidence.write_text('{"binding":true}\n')
        artifact = directory / "progress.json"
        artifact.write_text(json.dumps({"schema_version": 1, "work_order_id": work_order.work_order_id,
            "plan_sha256": work_order.plan.sha256, "acceptance_sha256": work_order.acceptance.sha256,
            "cycle_id": cycle_id, "observations": [{"evidence_id": "binding-evidence",
                "evidence_path": str(evidence.relative_to(self.workspace)), "sha256": self.digest(evidence)}]}))
        return str(artifact.relative_to(self.workspace))

    def successful_runner(self, work_order, store, profile, verifier, **kwargs):
        self.assertIs(kwargs["cancel_event"], self.cancel)
        self.assertEqual(kwargs["max_cycles_this_run"], 1)
        self.assertEqual(kwargs["external_engine_attempt_id"], "attempt-17")
        self.assertEqual(profile, self.profile)
        store.record_provider_thread(work_order, provider="codex", thread_id="thread-1", at=self.at)
        cycle_id = "cycle-1"
        head = store.record_cycle(work_order, cycle_id=cycle_id, variant_id="baseline", action_sha256="a"*64,
            outcome="succeeded", verified_evidence_artifact_path=self.progress(work_order, cycle_id), at=self.at)
        journal_dir = self.runtime / "mentor-attempts/logical-1/attempt-local"; journal_dir.mkdir(parents=True, mode=0o700)
        retained = journal_dir / "retained-output.json"
        retained.write_text('{"schema_version":1}\n'); retained.chmod(0o600)
        retained_sha = self.digest(retained)
        journal = {
            "schema_version": 1,
            "phase": "ledger_committed",
            "identity": {
                "attempt_id": "attempt-local",
                "attempt_type": "scheduled_external",
                "external_engine_attempt_id": "attempt-17",
                "cycle_id": cycle_id,
                "variant_id": "baseline",
                "work_order_id": work_order.work_order_id,
                "logical_session_id": work_order.logical_session.logical_session_id,
                "plan_sha256": work_order.plan.sha256,
                "acceptance_sha256": work_order.acceptance.sha256,
            },
            "intent_sha256": "1" * 64,
            "effective_timeout_seconds": 30,
            "event_at": self.at.isoformat(),
            "created_at": self.at.isoformat(),
            "updated_at": self.at.isoformat(),
            "transport": {
                "thread_id": "thread-1",
                "response_path": ".job-runtime/synthetic-response.json",
                "response_sha256": "2" * 64,
                "run_directory": ".job-runtime/synthetic-run",
                "retained_sha256": retained_sha,
            },
            "ledger": {
                "recorded": True,
                "revision": head["revision"],
                "outcome": "succeeded",
                "progress_verified": True,
            },
        }
        journal_path = journal_dir / "journal.json"
        journal_path.write_text(json.dumps(journal)); journal_path.chmod(0o600)
        return {"status": "succeeded", "code": "MENTOR_RUN_COMPLETED", "cycles_attempted": 1,
                "cycles": [{"status": "succeeded"}], "head": head}

    def test_exact_success_and_runtime_context_forwarding(self):
        with mock.patch.object(job_adapter, "run_cycles", side_effect=self.successful_runner) as runner:
            result = job_adapter.prepare(self.options, self.workspace, self.context, self.runtime_context)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual((result["status"], result["code"]), ("succeeded", "MENTOR_JOB_CYCLE_SUCCEEDED"))
        self.assertEqual((result["receipt"]["thread_id"], result["receipt"]["cycle_id"]), ("thread-1", "cycle-1"))
        self.assertLessEqual(len(json.dumps(result["receipt"]).encode()), 4096)

    def test_service_context_job_id_reaches_same_runner_without_leakage(self):
        context = {**self.context, "job_id": "mentor.job-1"}
        self.assertEqual(job_adapter._validate_context(context), self.context)
        with mock.patch.object(job_adapter, "run_cycles", side_effect=self.successful_runner) as runner:
            result = job_adapter.prepare(self.options, self.workspace, context, self.runtime_context)
        runner.assert_called_once()
        self.assertEqual((result["status"], result["code"]), ("succeeded", "MENTOR_JOB_CYCLE_SUCCEEDED"))
        self.assertNotIn("job_id", result["receipt"])

    def test_invalid_service_job_ids_and_extra_key_fail_before_runner(self):
        cases = {
            "invalid-type": {**self.context, "job_id": 1},
            "empty": {**self.context, "job_id": ""},
            "too-long": {**self.context, "job_id": "j" * 97},
            "slash": {**self.context, "job_id": "mentor/job"},
            "extra": {**self.context, "job_id": "mentor-job", "private_extra": True},
        }
        with mock.patch.object(job_adapter, "run_cycles") as runner:
            for name, context in cases.items():
                with self.subTest(name=name):
                    result = job_adapter.prepare(
                        self.options, self.workspace, context, self.runtime_context
                    )
                    self.assertEqual(result, {
                        "status": "failed", "code": "MENTOR_JOB_CONTEXT_INVALID"
                    })
        runner.assert_not_called()

    def test_status_mapping(self):
        cases = [
            ("retryable", "MENTOR_TEST_RESULT", "retryable"),
            ("failed", "MENTOR_TEST_RESULT", "failed"),
            ("blocked", "MENTOR_STATE_REVALIDATION_FAILED", "failed"),
            ("blocked", "MENTOR_SESSION_DISPATCH_BUSY", "retryable"),
            ("unknown", "MENTOR_TEST_RESULT", "unknown"),
        ]
        for source, runner_code, expected in cases:
            with self.subTest(source=source, runner_code=runner_code), mock.patch.object(
                    job_adapter, "run_cycles", return_value={
                        "status": source, "code": runner_code, "cycles_attempted": 0}):
                result = job_adapter.prepare(self.options, self.workspace, self.context, self.runtime_context)
                self.assertEqual(result["status"], expected)

    def test_zero_attempt_receipt_does_not_inherit_prior_thread_or_cycle(self):
        with mock.patch.object(job_adapter, "run_cycles", side_effect=self.successful_runner):
            first = job_adapter.prepare(self.options, self.workspace, self.context, self.runtime_context)
        self.assertEqual((first["receipt"]["thread_id"], first["receipt"]["cycle_id"]),
                         ("thread-1", "cycle-1"))
        next_context = {**self.context, "attempt_id": "engine-attempt-18", "slot_id": "slot-2", "attempt_no": 2}
        with mock.patch.object(job_adapter, "run_cycles", return_value={
                "status": "blocked", "code": "MENTOR_SESSION_DISPATCH_BUSY", "cycles_attempted": 0}):
            blocked = job_adapter.prepare(self.options, self.workspace, next_context, self.runtime_context)
        self.assertEqual((blocked["status"], blocked["code"]),
                         ("retryable", "MENTOR_JOB_CYCLE_RETRYABLE"))
        self.assertIsNone(blocked["receipt"]["thread_id"])
        self.assertIsNone(blocked["receipt"]["cycle_id"])

    def test_profile_name_and_fingerprint_mismatch_fail_before_runner(self):
        with mock.patch.object(job_adapter, "run_cycles") as runner:
            wrong_name = job_adapter.prepare(self.options, self.workspace, self.context,
                {**self.runtime_context, "model_profile_name": "other"})
            wrong_profile = job_adapter.prepare(self.options, self.workspace, self.context,
                {**self.runtime_context, "model_profile": {**self.profile, "model": "drifted"}})
        runner.assert_not_called()
        self.assertEqual((wrong_name["code"], wrong_profile["code"]),
                         ("MENTOR_JOB_PROFILE_MISMATCH", "MENTOR_JOB_PROFILE_MISMATCH"))

    def test_manifest_digest_omission_and_pre_run_drift(self):
        with mock.patch.object(job_adapter, "run_cycles") as runner:
            bad_digest = job_adapter.prepare({**self.options, "candidate_manifest_sha256": "0"*64},
                                             self.workspace, self.context, self.runtime_context)
            omission = job_adapter.prepare({**self.options, "required_source_paths": ["candidate/source.py", "plans/plan.md"]},
                                           self.workspace, self.context, self.runtime_context)
            malformed = job_adapter.prepare({**self.options, "required_source_paths": [{"private": "value"}]},
                                             self.workspace, self.context, self.runtime_context)
            self.source.write_text("DRIFT=1\n")
            drift = job_adapter.prepare(self.options, self.workspace, self.context, self.runtime_context)
        runner.assert_not_called()
        self.assertEqual(bad_digest["code"], "MENTOR_JOB_CANDIDATE_DRIFT")
        self.assertEqual(omission["code"], "MENTOR_JOB_CANDIDATE_SOURCE_SET_INVALID")
        self.assertEqual(malformed["code"], "MENTOR_JOB_CANDIDATE_INVALID")
        self.assertEqual(drift["code"], "MENTOR_JOB_CANDIDATE_DRIFT")

    def test_inode_swap_after_run_is_unknown(self):
        def swap(*args, **kwargs):
            replacement = self.workspace / "candidate/replacement.py"; replacement.write_bytes(self.source.read_bytes())
            replacement.replace(self.source)
            return {"status": "failed", "code": "MENTOR_TEST_FAILED", "cycles_attempted": 1}
        with mock.patch.object(job_adapter, "run_cycles", side_effect=swap):
            result = job_adapter.prepare(self.options, self.workspace, self.context, self.runtime_context)
        self.assertEqual(result, {"status": "unknown", "code": "MENTOR_JOB_CANDIDATE_DRIFT"})

    def test_top_level_success_with_failed_cycle_is_unknown(self):
        def spoof(work_order, store, *args, **kwargs):
            store.record_provider_thread(work_order, provider="codex", thread_id="thread-failed", at=self.at)
            store.record_cycle(work_order, cycle_id="cycle-failed", variant_id="baseline", action_sha256="b"*64,
                               outcome="failed", verified_evidence_artifact_path=None, at=self.at)
            return {"status": "succeeded", "code": "MENTOR_RUN_COMPLETED", "cycles_attempted": 1}
        with mock.patch.object(job_adapter, "run_cycles", side_effect=spoof):
            result = job_adapter.prepare(self.options, self.workspace, self.context, self.runtime_context)
        self.assertEqual(result, {"status": "unknown", "code": "MENTOR_JOB_SUCCESS_UNCONFIRMED"})

    def test_synthetic_verifier_rejects_empty_and_accepts_exact_substantive_output_idempotently(self):
        directory = self.runtime / "mentor-verifier/logical-1/direct"; directory.mkdir(parents=True)
        base = {"schema_version": 1, "cycle_id": "direct", "variant_id": "baseline",
                "action_id": "verify-synthetic-bindings", "criterion_updates": []}
        kwargs = dict(work_order=self.order, cycle_id="direct", verifier_directory=directory,
                      deadline=self.at+timedelta(seconds=10), cancel_event=None)
        self.assertIsNone(job_adapter._synthetic_bindings_v1(output=base, **kwargs))
        exact = {**base, "criterion_updates": job_adapter._expected_updates(self.order)}
        first = job_adapter._synthetic_bindings_v1(output=exact, **kwargs)
        self.assertEqual(job_adapter._synthetic_bindings_v1(output=exact, **kwargs), first)
        self.assertIsNotNone(first)

    def test_synthetic_verifier_rejects_unsupported_quality_criteria(self):
        acceptance = self.workspace / "plans/unsupported-acceptance.json"
        acceptance.write_text(json.dumps({"schema_version": 1, "criteria": [
            {"criterion_id": "alpha-quality", "critical": True}
        ]}))
        payload = self.payload()
        payload["acceptance"] = {"path": "plans/unsupported-acceptance.json", "sha256": self.digest(acceptance)}
        order = WorkOrder.from_json(json.dumps(payload), self.workspace)
        directory = self.runtime / "mentor-verifier/unsupported/direct"; directory.mkdir(parents=True)
        output = {"schema_version": 1, "cycle_id": "direct", "variant_id": "baseline",
                  "action_id": "verify-synthetic-bindings",
                  "criterion_updates": job_adapter._expected_updates(order)}
        self.assertIsNone(job_adapter._synthetic_bindings_v1(
            work_order=order,
            cycle_id="direct",
            output=output,
            verifier_directory=directory,
            deadline=self.at + timedelta(seconds=10),
            cancel_event=None,
        ))

    def test_partial_forged_journal_cannot_confirm_success(self):
        def partial(*args, **kwargs):
            result = self.successful_runner(*args, **kwargs)
            journal_path = next((self.runtime / "mentor-attempts/logical-1").glob("*/journal.json"))
            value = json.loads(journal_path.read_text())
            value.pop("transport")
            journal_path.write_text(json.dumps(value)); journal_path.chmod(0o600)
            return result
        with mock.patch.object(job_adapter, "run_cycles", side_effect=partial):
            result = job_adapter.prepare(self.options, self.workspace, self.context, self.runtime_context)
        self.assertEqual(result, {"status": "unknown", "code": "MENTOR_JOB_SUCCESS_UNCONFIRMED"})

    def test_paths_context_and_options_are_strict(self):
        public = self.workspace / "public-state"; public.mkdir()
        cases = [({**self.options, "extra": True}, self.context, "MENTOR_JOB_OPTIONS_INVALID"),
                 ({**self.options, "state_directory": "public-state"}, self.context, "MENTOR_JOB_PRIVATE_STATE_REQUIRED"),
                 (self.options, {**self.context, "expires_at": 1}, "MENTOR_JOB_CONTEXT_INVALID")]
        with mock.patch.object(job_adapter, "run_cycles") as runner:
            for options, context, code in cases:
                self.assertEqual(job_adapter.prepare(options, self.workspace, context, self.runtime_context)["code"], code)
        runner.assert_not_called()


if __name__ == "__main__": unittest.main()
