"""Provider-free composition of schema-1 scheduling and mentor job execution.

The installed schema-1 service adds ``job_id`` to the Engine's four-field adapter
context.  The tests use the smallest real runnable composition: strict config
loading, Engine, a dispatcher that calls the adapter, and the real runner with
only model/verifier seams injected.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
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
from mentor.scheduler import runner as mentor_runner
from mentor.scheduler.projection import (
    EvaluationSummary,
    GateSummary,
    build_projection,
)
from mentor.scheduler.reconciliation import ReconciliationError, reconcile_unknown
from mentor.scheduler.resilience_candidate import (
    CandidateInputs,
    CandidateSource,
    build_resilience_candidate,
)
from mentor.scheduler.supervision import PromotionDecision, PromotionVerdict
from shared.job_runtime import dashboard, service
from shared.job_runtime.config import ConfigError, load
from shared.job_runtime.engine import Engine


UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / ".job-runtime" / "tests" / "mentor-scheduler-service-composition"
RETRY = {"max_attempts": 3, "backoff_seconds": 5, "max_backoff_seconds": 10}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class FakeClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Scenario:
    root: Path
    at: datetime
    clock: FakeClock
    config: dict
    jobs: list[dict]
    job: dict
    order: WorkOrder
    store: DurableSessionStore
    plan: Path
    acceptance: Path
    manifest: Path
    source: Path
    profile: dict
    cancel: threading.Event
    canaries: tuple[str, ...]


class SchedulerServiceCompositionTest(unittest.TestCase):
    def setUp(self) -> None:
        PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="composition-", dir=PRIVATE)
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name).resolve()
        self.private.chmod(0o700)
        self.base = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
        service.STOP.clear()
        self.addCleanup(service.STOP.clear)

    def _write_private_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        path.chmod(0o600)

    def _scenario(
        self,
        name: str,
        *,
        timestamps: tuple[datetime, datetime] | None = None,
        grace_seconds: int = 60,
        max_no_progress: int = 4,
        max_repeated: int = 4,
    ) -> Scenario:
        root = self.private / name
        root.mkdir(mode=0o700)
        runtime = root / ".job-runtime"
        config_dir = runtime / "config"
        auth = runtime / f"PRIVATE_AUTH_CANARY_{name}"
        plans = root / "plans"
        candidate = root / "candidate"
        for directory in (runtime, config_dir, auth, plans, candidate):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.chmod(0o700)

        at = self.base
        timestamps = timestamps or (at, at + timedelta(seconds=10))
        self.assertEqual(len(timestamps), 2)
        plan_canary = f"PRIVATE_PLAN_CANARY_{name}"
        source_canary = f"PRIVATE_SOURCE_CANARY_{name}"
        prompt_canary = f"PRIVATE_PROMPT_CANARY_{name}"
        auth_canary = auth.name

        plan = plans / "plan.md"
        plan.write_text(f"# Frozen synthetic plan\n{plan_canary}\n", encoding="utf-8")
        acceptance = plans / "acceptance.json"
        acceptance.write_text(json.dumps({
            "schema_version": 1,
            "criteria": [
                {"criterion_id": "closed-response", "critical": True},
                {"criterion_id": "frozen-binding", "critical": True},
            ],
        }), encoding="utf-8")
        source = candidate / "source.py"
        source.write_text(f'VALUE = "{source_canary}"\n', encoding="utf-8")
        manifest = candidate / "manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": 1,
            "sources": [{"path": "candidate/source.py", "sha256": digest(source)}],
        }), encoding="utf-8")

        work_order_path = plans / "work-order.json"
        identity = f"identity-{name}"
        payload = {
            "schema_version": 1,
            "work_order_id": identity,
            "logical_session": {
                "logical_session_id": identity,
                "provider_thread_mode": "ephemeral_threads",
                "max_provider_threads": 8,
            },
            "plan": {"path": "plans/plan.md", "sha256": digest(plan)},
            "acceptance": {"path": "plans/acceptance.json", "sha256": digest(acceptance)},
            "execution": {
                "starts_at": (at - timedelta(hours=1)).isoformat(),
                "ends_at": (at + timedelta(hours=2)).isoformat(),
                "turn_timeout_seconds": 60,
                "max_turns": 8,
            },
            "supervision": {
                "max_no_progress_cycles": max_no_progress,
                "max_repeated_actions": max_repeated,
                "max_interventions": 2,
            },
            "evidence_policy": {
                "record_all_variants": True,
                "max_variants": 2,
                "max_reused_evaluations": 0,
                "worker_holdout_access": False,
            },
            "completion": {
                "required_event_kinds": ["provider_thread", "cycle"],
                "require_no_pending_effects": True,
                "require_acceptance_hash_match": True,
            },
        }
        work_order_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        order = WorkOrder.from_json(work_order_path.read_text(encoding="utf-8"), root)
        store = DurableSessionStore(root, ".job-runtime/session", identity)
        store.create(order, at=at - timedelta(minutes=1))

        profile = {
            "codex_bin": "/synthetic/provider-free",
            "model": "synthetic-model",
            "effort": "high",
            "timeout_seconds": 30,
            "auth_home": str(auth),
            "executor": "readiness",
        }
        options = {
            "work_order_path": "plans/work-order.json",
            "state_directory": ".job-runtime/session",
            "owner_id": identity,
            "candidate_manifest_path": "candidate/manifest.json",
            "candidate_manifest_sha256": digest(manifest),
            "required_source_paths": ["candidate/source.py"],
            "expected_model_profile": "mentor-profile",
            "model_profile_sha256": job_adapter.profile_fingerprint(profile),
            "verifier_kind": "synthetic_bindings_v1",
        }
        prompt = config_dir / "mentor-prompt.txt"
        prompt.write_text(f"Synthetic adapter allocation. {prompt_canary}\n", encoding="utf-8")
        prompt.chmod(0o600)
        job = {
            "id": f"mentor-{name}",
            "enabled": True,
            "schedule": {
                "kind": "sequence",
                "timestamps": [value.isoformat() for value in timestamps],
                "grace_seconds": grace_seconds,
            },
            "replay_safe": True,
            "model_profile": "mentor-profile",
            "prompt_file": ".job-runtime/config/mentor-prompt.txt",
            "adapter": "mentor.scheduler.job_adapter:prepare",
            "adapter_config": options,
        }
        allocation_path = config_dir / "jobs.json"
        self._write_private_json(allocation_path, {"schema_version": 1, "jobs": [job]})
        config = {
            "schema_version": 1,
            "tick_seconds": 1,
            "heartbeat_seconds": 1,
            "stale_seconds": 30,
            "max_workers": 1,
            "retry": RETRY,
            "model_profiles": {"mentor-profile": profile},
            "allocation_files": [".job-runtime/config/jobs.json"],
            "source_paths": [],
        }
        config_path = config_dir / "runtime.json"
        self._write_private_json(config_path, config)
        loaded, jobs = load(config_path, root)
        self.assertEqual((loaded["schema_version"], len(jobs)), (1, 1))
        self.assertEqual(len(jobs[0]["schedule"]["timestamps"]), 2)
        cancel = threading.Event()
        return Scenario(
            root=root,
            at=at,
            clock=FakeClock(at),
            config=loaded,
            jobs=jobs,
            job=jobs[0],
            order=order,
            store=store,
            plan=plan,
            acceptance=acceptance,
            manifest=manifest,
            source=source,
            profile=profile,
            cancel=cancel,
            canaries=(plan_canary, source_canary, prompt_canary, auth_canary),
        )

    def _dispatcher(self, scenario: Scenario):
        def dispatch(job: dict, context: dict) -> dict:
            runtime_context = {
                "version": 1,
                "model_profile_name": job["model_profile"],
                "model_profile": scenario.config["model_profiles"][job["model_profile"]],
                "cancel_event": scenario.cancel,
            }
            return job_adapter.prepare(
                job["adapter_config"], scenario.root, context, runtime_context
            )

        return dispatch

    def _engine(self, scenario: Scenario, *, dispatcher=None) -> Engine:
        return Engine(
            scenario.root / ".job-runtime/engine",
            scenario.jobs,
            RETRY,
            dispatcher or self._dispatcher(scenario),
            workspace_root=scenario.root,
            clock=scenario.clock,
            max_workers=1,
        )

    def _tick(
        self,
        scenario: Scenario,
        engine: Engine,
        when: datetime,
        model_call,
        *,
        verifier=None,
    ) -> dict:
        scenario.clock.now = when

        def injected(work_order, store, profile, adapter_verifier, **kwargs):
            return mentor_runner.run_cycles(
                work_order,
                store,
                profile,
                verifier or adapter_verifier,
                model_call=model_call,
                clock=scenario.clock,
                **kwargs,
            )

        with mock.patch.object(job_adapter, "run_cycles", side_effect=injected):
            return engine.tick(when)

    def _successful_model(self, scenario: Scenario, calls: list[dict], effects=None):
        def model(profile, prompt, workspace, run_dir, context=None):
            parsed = json.loads(prompt)
            calls.append({"profile": dict(profile), "prompt": parsed, "run_dir": run_dir})
            if effects is not None:
                effects.append(parsed["bindings"]["cycle_id"])
            run_dir.mkdir(mode=0o700, parents=True)
            output = {
                "schema_version": 1,
                "cycle_id": context["response_schema"]["properties"]["cycle_id"]["const"],
                "variant_id": "baseline",
                "action_id": "verify-synthetic-bindings",
                "criterion_updates": job_adapter._expected_updates(scenario.order),
            }
            response = run_dir / "last-message.json"
            response.write_text(json.dumps(output, sort_keys=True), encoding="utf-8")
            return {
                "status": "succeeded",
                "code": "MODEL_TURN_COMPLETED",
                "receipt": {
                    "thread_id": f"thread-{len(calls)}",
                    "response_path": str(response.relative_to(workspace)),
                    "response_sha256": digest(response),
                    "turn_completed": True,
                    "requested_model": profile["model"],
                    "observed_model": profile["model"],
                    "automatic_retry": False,
                    "fallback_used": False,
                },
            }

        return model

    @staticmethod
    def _rows(engine: Engine, table: str) -> list[dict]:
        with engine._db() as database:
            return [dict(row) for row in database.execute(
                f"SELECT * FROM {table} ORDER BY rowid"
            )]

    def test_strict_schema1_admission_and_real_service_context_succeeds(self) -> None:
        scenario = self._scenario("service-boundary")
        allocation = scenario.root / ".job-runtime/config/jobs.json"
        invalid = json.loads(allocation.read_text(encoding="utf-8"))
        invalid["jobs"][0]["private_extra"] = True
        self._write_private_json(allocation, invalid)
        with self.assertRaisesRegex(ConfigError, "JOB_KEYS_INVALID"):
            load(scenario.root / ".job-runtime/config/runtime.json", scenario.root)
        self._write_private_json(allocation, {"schema_version": 1, "jobs": scenario.jobs})

        calls: list[dict] = []
        model = self._successful_model(scenario, calls)
        real_dispatch = service.dispatcher(scenario.config, scenario.root)
        engine = self._engine(scenario, dispatcher=real_dispatch)

        def injected(work_order, store, profile, adapter_verifier, **kwargs):
            return mentor_runner.run_cycles(
                work_order,
                store,
                profile,
                adapter_verifier,
                model_call=model,
                clock=scenario.clock,
                **kwargs,
            )

        with mock.patch.object(service, "adapter_module", return_value=job_adapter), \
                mock.patch.object(job_adapter, "run_cycles", side_effect=injected) as runner:
            summary = engine.tick(scenario.at)
        self.assertEqual(summary["succeeded"], 1)
        runner.assert_called_once()
        self.assertEqual(len(calls), 1)

        attempt = self._rows(engine, "attempts")[0]
        receipt = json.loads(attempt["receipt"])
        self.assertEqual(attempt["status"], "succeeded")
        self.assertEqual(receipt["attempt_id"], attempt["attempt_id"])
        self.assertEqual(receipt["slot_id"], attempt["slot_id"])
        self.assertNotIn("job_id", receipt)

        journal_path = next(
            (scenario.root / ".job-runtime/mentor-attempts" /
             scenario.order.logical_session.logical_session_id).glob("*/journal.json")
        )
        identity = json.loads(journal_path.read_text(encoding="utf-8"))["identity"]
        self.assertEqual(identity["external_engine_attempt_id"], attempt["attempt_id"])
        self.assertNotIn("job_id", identity)
        self.assertEqual(scenario.store.load(scenario.order)["turns_used"], 1)

    def test_built_bundle_materializes_through_engine_service_and_mentor_ledger(self) -> None:
        scenario = self._scenario("built-bundle")
        identity = scenario.order.work_order_id
        generated_root = scenario.root / ".job-runtime/acceptance/built-bundle"
        generated_root.mkdir(mode=0o700, parents=True)
        generated_root.chmod(0o700)
        prompt = scenario.root / "prompts/built-bundle.txt"
        prompt.parent.mkdir(mode=0o700)
        prompt.write_text(
            f"Generated bundle service allocation. {scenario.canaries[2]}\n",
            encoding="utf-8",
        )
        prompt.chmod(0o600)
        inputs = CandidateInputs(
            work_order_id=identity,
            logical_session_id=identity,
            job_id="built-bundle-job",
            owner_id=identity,
            work_order_path=".job-runtime/acceptance/built-bundle/work-order.json",
            state_directory=".job-runtime/acceptance/built-bundle/state",
            candidate_manifest_path=(
                ".job-runtime/acceptance/built-bundle/candidate-manifest.json"
            ),
            plan_path=str(scenario.plan.relative_to(scenario.root)),
            plan_sha256=digest(scenario.plan),
            acceptance_path=str(scenario.acceptance.relative_to(scenario.root)),
            acceptance_sha256=digest(scenario.acceptance),
            sources=(CandidateSource(
                str(scenario.source.relative_to(scenario.root)),
                digest(scenario.source),
            ),),
            expected_model_profile="mentor-profile",
            model_profile_sha256=job_adapter.profile_fingerprint(scenario.profile),
            prompt_file=str(prompt.relative_to(scenario.root)),
            slot_1=scenario.at,
            slot_2=scenario.at + timedelta(seconds=10),
            starts_at=scenario.at - timedelta(hours=1),
            ends_at=scenario.at + timedelta(hours=2),
            turn_timeout_seconds=60,
            grace_seconds=60,
        )
        bundle = build_resilience_candidate(inputs)
        documents = bundle.to_json_documents()
        work_order_path = scenario.root / inputs.work_order_path
        manifest_path = scenario.root / inputs.candidate_manifest_path
        allocation_path = scenario.root / ".job-runtime/config/jobs.json"
        for path, document in (
            (work_order_path, documents["work-order.json"]),
            (manifest_path, documents["candidate-manifest.json"]),
            (allocation_path, documents["allocation.json"]),
        ):
            path.write_bytes(document)
            path.chmod(0o600)

        config_path = scenario.root / ".job-runtime/config/runtime.json"
        loaded, jobs = load(config_path, scenario.root)
        self.assertEqual(len(jobs), 1)
        self.assertFalse(jobs[0]["enabled"])
        self.assertEqual(
            allocation_path.read_bytes(), documents["allocation.json"]
        )
        order = WorkOrder.from_json(
            documents["work-order.json"].decode("utf-8"), scenario.root
        )
        store = DurableSessionStore(scenario.root, inputs.state_directory, identity)
        store.create(order, at=scenario.at - timedelta(minutes=1))

        test_job = {**jobs[0], "enabled": True}
        generated = replace(
            scenario,
            config=loaded,
            jobs=[test_job],
            job=test_job,
            order=order,
            store=store,
            manifest=manifest_path,
        )
        calls: list[dict] = []
        model = self._successful_model(generated, calls)
        engine = self._engine(
            generated,
            dispatcher=service.dispatcher(generated.config, generated.root),
        )

        def injected(work_order, session_store, profile, adapter_verifier, **kwargs):
            return mentor_runner.run_cycles(
                work_order,
                session_store,
                profile,
                adapter_verifier,
                model_call=model,
                clock=generated.clock,
                **kwargs,
            )

        with mock.patch.object(service, "adapter_module", return_value=job_adapter), \
                mock.patch.object(job_adapter, "run_cycles", side_effect=injected):
            summary = engine.tick(generated.at)
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(len(calls), 1)

        attempt = self._rows(engine, "attempts")[0]
        receipt = json.loads(attempt["receipt"])
        head = store.load(order)
        self.assertEqual(
            (head["work_order_id"], head["logical_session_id"], head["owner_id"]),
            (identity, identity, identity),
        )
        self.assertNotEqual(test_job["id"], identity)
        self.assertEqual(head["turns_used"], 1)
        self.assertEqual(receipt["attempt_id"], attempt["attempt_id"])
        self.assertEqual(receipt["work_order_id"], identity)
        self.assertEqual(receipt["logical_session_id"], identity)
        journal_path = next(
            (scenario.root / ".job-runtime/mentor-attempts" / identity).glob(
                "*/journal.json"
            )
        )
        journal_identity = json.loads(
            journal_path.read_text(encoding="utf-8")
        )["identity"]
        self.assertEqual(
            journal_identity["external_engine_attempt_id"], attempt["attempt_id"]
        )
        serialized = json.dumps({"head": head, "receipt": receipt}, sort_keys=True)
        for canary in scenario.canaries:
            self.assertNotIn(canary, serialized)

    def test_nominal_two_slots_duplicate_ticks_and_public_projection_are_safe(self) -> None:
        scenario = self._scenario("nominal")
        engine = self._engine(scenario)
        calls: list[dict] = []
        model = self._successful_model(scenario, calls)

        first = self._tick(scenario, engine, scenario.at, model)
        duplicate_first = self._tick(scenario, engine, scenario.at, model)
        second_at = scenario.at + timedelta(seconds=10)
        second = self._tick(scenario, engine, second_at, model)
        duplicate_second = self._tick(scenario, engine, second_at, model)

        self.assertEqual((first["succeeded"], second["succeeded"]), (1, 1))
        self.assertEqual((duplicate_first["dispatched"], duplicate_second["dispatched"]), (0, 0))
        self.assertEqual(len(calls), 2)
        head = scenario.store.load(scenario.order)
        self.assertEqual((head["turns_used"], len(head["provider_threads"])), (2, 2))
        slots = self._rows(engine, "slots")
        self.assertEqual([row["status"] for row in slots], ["succeeded", "succeeded"])
        self.assertEqual(len(slots), 2)
        receipts = [json.loads(row["receipt"]) for row in self._rows(engine, "attempts")]
        self.assertEqual(
            {(item["work_order_id"], item["logical_session_id"]) for item in receipts},
            {(scenario.order.work_order_id, scenario.order.logical_session.logical_session_id)},
        )
        self.assertEqual(
            {item["candidate_fingerprint"] for item in receipts},
            {digest(scenario.manifest)},
        )

        promotion = PromotionDecision(
            scenario.order.acceptance.sha256,
            PromotionVerdict.INCONCLUSIVE,
            ("provider-free fixture only",),
            "no promotion claim",
        )
        mentor_projection = build_projection(
            scenario.order,
            scenario.store,
            generated_at=second_at,
            scheduler_status="succeeded",
            slot_id=slots[-1]["slot_id"],
            gates=GateSummary(verified=0, failed=0, pending=2),
            evaluation=EvaluationSummary(
                baseline="provider free fixture",
                holdout="protected untouched",
            ),
            promotion=promotion,
        )
        dashboard_projection = dashboard.project(
            scenario.root, job_id=scenario.job["id"], at=second_at
        )
        public = json.dumps({
            "engine": engine.status(),
            "mentor": mentor_projection,
            "dashboard": dashboard_projection,
        }, sort_keys=True)
        for canary in scenario.canaries:
            self.assertNotIn(canary, public)
        self.assertNotIn(str(scenario.root), public)
        self.assertNotIn("auth_home", public)

    def test_plan_acceptance_and_manifest_drift_block_before_model(self) -> None:
        for target in ("plan", "acceptance", "manifest"):
            with self.subTest(target=target):
                scenario = self._scenario(f"drift-{target}")
                engine = self._engine(scenario)
                calls: list[dict] = []
                model = self._successful_model(scenario, calls)
                if target == "plan":
                    scenario.plan.write_text("drifted plan\n", encoding="utf-8")
                elif target == "acceptance":
                    scenario.acceptance.write_text('{"schema_version":1,"criteria":[]}\n', encoding="utf-8")
                else:
                    scenario.manifest.write_text(
                        scenario.manifest.read_text(encoding="utf-8") + " ",
                        encoding="utf-8",
                    )
                summary = self._tick(scenario, engine, scenario.at, model)
                self.assertEqual(summary["failed"], 1)
                self.assertEqual(calls, [])
                private_head = json.loads(scenario.store.head_path.read_text(encoding="utf-8"))
                self.assertEqual(private_head["turns_used"], 0)
                expected = (
                    "MENTOR_JOB_CANDIDATE_DRIFT"
                    if target == "manifest"
                    else "MENTOR_JOB_CONTRACT_INVALID"
                )
                self.assertEqual(self._rows(engine, "attempts")[0]["code"], expected)

    def test_pre_dispatch_transient_retry_survives_engine_reconstruction(self) -> None:
        scenario = self._scenario(
            "transient-restart",
            timestamps=(scenario_at := self.base, scenario_at + timedelta(seconds=30)),
            grace_seconds=120,
        )
        calls: list[str] = []
        success = self._successful_model(scenario, [])

        def transient_then_success(profile, prompt, workspace, run_dir, context=None):
            calls.append("model")
            if len(calls) == 1:
                return {
                    "status": "retryable",
                    "code": "MODEL_AUTH_CACHE_BUSY",
                    "receipt": {"requested_model": profile["model"]},
                }
            return success(profile, prompt, workspace, run_dir, context=context)

        engine = self._engine(scenario)
        first = self._tick(scenario, engine, scenario.at, transient_then_success)
        self.assertEqual(first["retry_wait"], 1)
        self.assertEqual(scenario.store.load(scenario.order)["turns_used"], 0)

        reopened = self._engine(scenario)
        retry_at = scenario.at + timedelta(seconds=5)
        second = self._tick(scenario, reopened, retry_at, transient_then_success)
        duplicate = self._tick(scenario, reopened, retry_at, transient_then_success)
        self.assertEqual((second["succeeded"], duplicate["dispatched"]), (1, 0))
        self.assertEqual(len(calls), 2)
        head = scenario.store.load(scenario.order)
        self.assertEqual((head["turns_used"], len(head["cycle_ids"])), (1, 1))
        first_slot_attempts = [
            row for row in self._rows(reopened, "attempts")
            if row["slot_id"].endswith(":0")
        ]
        self.assertEqual([row["status"] for row in first_slot_attempts], ["retry_wait", "succeeded"])

    def test_unknown_modes_fence_partial_until_exact_reconciliation(self) -> None:
        for mode in ("no-output", "midstream-partial", "process-crash"):
            with self.subTest(mode=mode):
                scenario = self._scenario(
                    f"unknown-{mode}",
                    timestamps=(self.base, self.base + timedelta(seconds=1)),
                )
                engine = self._engine(scenario)
                calls: list[str] = []
                success = self._successful_model(scenario, [])

                def uncertain(profile, prompt, workspace, run_dir, context=None):
                    calls.append(mode)
                    if len(calls) > 1:
                        return success(profile, prompt, workspace, run_dir, context=context)
                    if mode == "process-crash":
                        raise RuntimeError("synthetic provider process crash")
                    if mode == "midstream-partial":
                        return {
                            "status": "unknown",
                            "code": "MODEL_PARTIAL_RESPONSE",
                            "receipt": {"started_at": scenario.at.isoformat(), "partial": True},
                        }
                    return {
                        "status": "failed",
                        "code": "MODEL_OUTPUT_MISSING",
                        "receipt": {"started_at": scenario.at.isoformat()},
                    }

                due = scenario.at + timedelta(seconds=1)
                first = self._tick(scenario, engine, due, uncertain)
                blocked = self._tick(scenario, engine, due, uncertain)
                self.assertEqual((first["unknown"], blocked["dispatched"]), (1, 0))
                self.assertEqual(len(calls), 1)
                head = scenario.store.load(scenario.order)
                self.assertEqual(head["status"], "blocked_pending_effect")
                self.assertEqual((head["turns_used"], head["verified_evidence_ids"]), (1, []))
                slots = self._rows(engine, "slots")
                self.assertEqual([row["status"] for row in slots], ["unknown", "ready"])
                with self.assertRaisesRegex(ReconciliationError, "unavailable"):
                    reconcile_unknown(
                        engine,
                        scenario.store,
                        scenario.order,
                        reconciliation_id=f"wrong-{mode}",
                        slot_id=slots[1]["slot_id"],
                        outcome="failed",
                        evidence_path="missing-evidence.json",
                        at=due,
                    )
                self.assertEqual(
                    scenario.store.load(scenario.order)["pending_effects"],
                    [self._rows(engine, "attempts")[0]["attempt_id"]],
                )

                evidence = scenario.root / ".job-runtime" / f"reconcile-{mode}.txt"
                evidence.write_text("exact synthetic absence evidence\n", encoding="utf-8")
                evidence.chmod(0o600)
                journal = reconcile_unknown(
                    engine,
                    scenario.store,
                    scenario.order,
                    reconciliation_id=f"reconcile-{mode}",
                    slot_id=slots[0]["slot_id"],
                    outcome="failed",
                    evidence_path=str(evidence.relative_to(scenario.root)),
                    at=due,
                )
                self.assertEqual(journal["phase"], "completed")
                self.assertEqual(scenario.store.load(scenario.order)["status"], "active")
                resumed = self._tick(scenario, engine, due, uncertain)
                self.assertEqual(resumed["succeeded"], 1)
                final = scenario.store.load(scenario.order)
                self.assertEqual((final["turns_used"], len(final["verified_evidence_ids"])), (2, 1))
                self.assertEqual(len(calls), 2)

    def test_fake_clock_jump_within_grace_once_then_outside_grace_missed(self) -> None:
        scenario = self._scenario(
            "clock-jump",
            timestamps=(self.base, self.base + timedelta(seconds=10)),
            grace_seconds=5,
        )
        engine = self._engine(scenario)
        calls: list[dict] = []
        effects: list[str] = []
        model = self._successful_model(scenario, calls, effects)
        within = scenario.at + timedelta(seconds=4)
        first = self._tick(scenario, engine, within, model)
        duplicate = self._tick(scenario, engine, within, model)
        after_sleep = scenario.at + timedelta(seconds=20)
        late = self._tick(scenario, engine, after_sleep, model)
        late_duplicate = self._tick(scenario, engine, after_sleep, model)
        self.assertEqual((first["succeeded"], duplicate["dispatched"]), (1, 0))
        self.assertEqual((late["dispatched"], late_duplicate["dispatched"]), (0, 0))
        self.assertEqual([row["status"] for row in self._rows(engine, "slots")], ["succeeded", "missed"])
        self.assertEqual((len(calls), len(effects), len(set(effects))), (1, 1, 1))

    def test_no_progress_and_repeated_action_limits_block_later_provider_call(self) -> None:
        for limit in ("no-progress", "repeated-action"):
            with self.subTest(limit=limit):
                scenario = self._scenario(
                    f"limit-{limit}",
                    max_no_progress=1 if limit == "no-progress" else 10,
                    max_repeated=4 if limit == "no-progress" else 1,
                )
                output_shape = {
                    "schema_version": 1,
                    "cycle_id": "ignored-by-semantic-hash",
                    "variant_id": "baseline",
                    "action_id": "verify-synthetic-bindings",
                    "criterion_updates": job_adapter._expected_updates(scenario.order),
                }
                action_sha = mentor_runner._semantic_action_sha(output_shape)
                if limit == "repeated-action":
                    scenario.store.record_cycle(
                        scenario.order,
                        cycle_id="seed-no-progress",
                        variant_id="baseline",
                        action_sha256=action_sha,
                        outcome="failed",
                        verified_evidence_artifact_path=None,
                        at=scenario.at - timedelta(seconds=1),
                    )
                engine = self._engine(scenario)
                calls: list[dict] = []
                model = self._successful_model(scenario, calls)
                no_progress = lambda **_kwargs: None
                first = self._tick(
                    scenario, engine, scenario.at, model, verifier=no_progress
                )
                second = self._tick(
                    scenario,
                    engine,
                    scenario.at + timedelta(seconds=10),
                    model,
                    verifier=no_progress,
                )
                self.assertEqual((first["failed"], second["failed"]), (1, 1))
                self.assertEqual(len(calls), 1)
                head = scenario.store.load(scenario.order)
                if limit == "no-progress":
                    self.assertEqual(head["consecutive_no_progress"], 1)
                else:
                    self.assertEqual(head["repeated_action_count"], 1)
                self.assertEqual(self._rows(engine, "attempts")[-1]["code"], "MENTOR_JOB_CYCLE_BLOCKED")

    def test_stop_and_cancel_are_conservative_with_zero_effects(self) -> None:
        scenario = self._scenario("cancel")
        engine = self._engine(scenario)
        effects: list[str] = []
        model = self._successful_model(scenario, [], effects)
        scenario.cancel.set()
        cancelled = self._tick(scenario, engine, scenario.at, model)
        self.assertEqual(cancelled["failed"], 1)
        self.assertEqual(effects, [])
        self.assertEqual(scenario.store.load(scenario.order)["turns_used"], 0)
        self.assertEqual(list((scenario.root / ".job-runtime/mentor-attempts" / scenario.order.logical_session.logical_session_id).glob("*/journal.json")), [])

        stopped = self._scenario("service-stop")
        stopped_effects: list[str] = []
        stopped_model = self._successful_model(stopped, [], stopped_effects)
        service.STOP.set()
        service_engine = self._engine(
            stopped,
            dispatcher=service.dispatcher(stopped.config, stopped.root),
        )
        with mock.patch.object(service, "adapter_module") as adapter_loader, \
                mock.patch.object(job_adapter, "run_cycles") as runner:
            summary = service_engine.tick(stopped.at)
        self.assertEqual(summary["retry_wait"], 1)
        adapter_loader.assert_not_called()
        runner.assert_not_called()
        self.assertEqual((stopped_effects, stopped_model is not None), ([], True))
        self.assertEqual(stopped.store.load(stopped.order)["turns_used"], 0)


if __name__ == "__main__":
    unittest.main()
