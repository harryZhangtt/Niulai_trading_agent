"""Provider-free failure campaign for durable scheduler retry safety.

All providers, clocks, reconciliation owners, external effects, and crashes are
synthetic.  The campaign uses private temporary workspaces and real SQLite.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from shared.job_runtime.engine import Engine, EngineError
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
from shared.job_runtime.provider_contract import (
    ContractError,
    FailureKind,
    Phase,
    ProviderResultV1,
    ReconciliationProofV1,
    ReplayContractV1,
    ReplayEffect,
    ResultStatus,
    Submission,
    TerminalProof,
)
from shared.job_runtime.retry_policy import RetryPolicyV2
from shared.job_runtime import service

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[3]
PRIVATE = ROOT / ".job-runtime" / "tests" / "provider-retry-campaign"
LEGACY_RETRY = {"max_attempts": 3, "backoff_seconds": 5, "max_backoff_seconds": 10}


def at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def result(
    provider: str,
    operation_id: str,
    *,
    status: ResultStatus = ResultStatus.SUCCEEDED,
    failure: FailureKind = FailureKind.NONE,
    code: str = "COMPLETED",
    phase: Phase = Phase.TERMINAL,
    submission: Submission = Submission.DEFINITELY_SUBMITTED,
    proof: TerminalProof = TerminalProof.VERIFIED,
    http_status: int | None = None,
    retry_after: datetime | None = None,
    receipt: dict | None = None,
) -> ProviderResultV1:
    return ProviderResultV1(
        provider,
        operation_id,
        phase,
        submission,
        proof,
        status,
        code,
        failure_kind=failure,
        http_status=http_status,
        provider_should_retry=True if status is ResultStatus.RETRYABLE else None,
        retry_after_at=retry_after,
        retry_after_source="typed-timestamp" if retry_after else None,
        receipt=receipt,
    )


def transient(
    provider: str,
    operation_id: str,
    *,
    http_status: int = 429,
    retry_after: datetime | None = None,
) -> ProviderResultV1:
    return result(
        provider,
        operation_id,
        status=ResultStatus.RETRYABLE,
        failure=FailureKind.HTTP,
        code="HTTP_RATE_LIMITED" if http_status == 429 else "HTTP_OVERLOADED",
        phase=Phase.CONNECTING,
        submission=Submission.NOT_SUBMITTED,
        proof=TerminalProof.ABSENT,
        http_status=http_status,
        retry_after=retry_after,
        receipt={"fixture": "provider-free", "http_status": http_status},
    )


def unknown(
    provider: str,
    operation_id: str,
    failure: FailureKind,
) -> ProviderResultV1:
    phase = Phase.STREAMING if failure is FailureKind.PARTIAL_RESPONSE else Phase.TERMINAL
    submission = Submission.DEFINITELY_SUBMITTED if phase is Phase.STREAMING else Submission.POSSIBLY_SUBMITTED
    return result(
        provider,
        operation_id,
        status=ResultStatus.UNKNOWN,
        failure=failure,
        code="PROVIDER_OUTCOME_UNKNOWN",
        phase=phase,
        submission=submission,
        proof=TerminalProof.ABSENT,
        receipt={"fixture": "sanitized", "terminal_seen": False},
    )


class Owner:
    def __init__(self) -> None:
        self.proof: ReconciliationProofV1 | None = None

    def reconcile(self, *, attempt_id: str, operation_id: str, slot_operation_scope: str):
        if self.proof is None:
            raise AssertionError("proof not installed")
        if (attempt_id, operation_id, slot_operation_scope) != (
                self.proof.attempt_id, self.proof.operation_id, self.proof.slot_operation_scope):
            raise AssertionError("owner binding mismatch")
        return self.proof


class CampaignCrash(BaseException):
    pass


class ProviderRetryCampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=PRIVATE)
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        self.workspace.chmod(0o700)
        self.now = at("2026-11-06T12:00:00Z")
        self.policy = RetryPolicyV2(3, 2, 30, deadline_seconds=100)
        self.owner = Owner()
        service.STOP.clear()
        self.addCleanup(service.STOP.clear)

    def state(self, name: str) -> Path:
        return self.workspace / ".job-runtime" / name

    def contract(self, scope: str, *, reconcile: bool = False) -> ReplayContractV1:
        return ReplayContractV1(
            ReplayEffect.RECONCILE_BEFORE_REPLAY if reconcile else ReplayEffect.IDEMPOTENT,
            (Phase.CONNECTING,),
            scope,
            "owner/one" if reconcile else None,
        )

    def job(
        self,
        job_id: str,
        provider: str,
        *,
        contract: ReplayContractV1 | None = None,
        policy: RetryPolicyV2 | None = None,
        circuit: dict | None = None,
        schedule: dict | None = None,
    ) -> dict:
        prompt = f"campaign prompt for {job_id}".encode()
        prompt_sha = hashlib.sha256(prompt).hexdigest()
        configured = {
            "id": job_id,
            "enabled": True,
            "replay_safe": True,
            "schedule": schedule or {"kind": "interval", "seconds": 60, "grace_seconds": 120},
            "_provider": provider,
            "_replay_contract": contract or self.contract(f"scope/{job_id}"),
            "_retry_policy": policy or self.policy,
            "_prompt_artifact": PromptArtifactDescriptorV1(
                1, f"pa1:sha256:{prompt_sha}:{len(prompt)}", prompt_sha, len(prompt),
                hashlib.sha256(f"campaign-source/{job_id}".encode()).hexdigest(),
                "0", "native_v1"),
        }
        if circuit is not None:
            configured["_circuit_scope"] = circuit
        return configured

    def engine(self, name: str, jobs: list[dict], dispatcher, *, cls=Engine, clock=None, workers=2) -> Engine:
        return cls(
            self.state(name),
            jobs,
            LEGACY_RETRY,
            dispatcher,
            workspace_root=self.workspace,
            clock=clock or (lambda: self.now),
            max_workers=workers,
            reconciliation_adapters={"owner/one": self.owner},
        )

    @staticmethod
    def rows(engine: Engine, table: str) -> list[dict]:
        with engine._db() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]

    def test_dual_provider_retry_after_restart_exact_attempts_and_operations(self):
        jobs = [self.job("codex", "codex_cli"), self.job("claude", "claude_host")]
        waits = {"codex_cli": 7, "claude_host": 11}
        calls = {"codex_cli": [], "claude_host": []}
        effects: list[tuple[str, str]] = []

        def dispatch(job, context):
            provider = job["_provider"].value
            calls[provider].append(context["operation_id"])
            if len(calls[provider]) == 1:
                return transient(provider, context["operation_id"], retry_after=self.now + timedelta(seconds=waits[provider]))
            effects.append((provider, context["operation_id"]))
            return result(provider, context["operation_id"], receipt={"effect_committed": True})

        first = self.engine("dual", jobs, dispatch)
        self.assertEqual(first.tick(self.now), {
            "dispatched": 2, "succeeded": 0, "retry_wait": 2, "failed": 0, "unknown": 0})
        slots = {row["job_id"]: row for row in self.rows(first, "slots")}
        self.assertEqual(slots["codex"]["next_attempt_at"], (self.now + timedelta(seconds=7)).timestamp())
        self.assertEqual(slots["claude"]["next_attempt_at"], (self.now + timedelta(seconds=11)).timestamp())
        self.assertEqual(len(self.rows(first, "attempts")), 2)
        self.assertEqual(len(self.rows(first, "provider_results")), 2)
        self.assertEqual(len(self.rows(first, "retry_decisions")), 2)

        reopened = self.engine("dual", jobs, dispatch)
        self.assertEqual(reopened.tick(self.now + timedelta(seconds=6))["dispatched"], 0)
        self.assertEqual(reopened.tick(self.now + timedelta(seconds=7))["succeeded"], 1)
        self.assertEqual(reopened.tick(self.now + timedelta(seconds=10))["dispatched"], 0)
        self.assertEqual(reopened.tick(self.now + timedelta(seconds=11))["succeeded"], 1)
        self.assertEqual({key: len(value) for key, value in calls.items()}, {"codex_cli": 2, "claude_host": 2})
        self.assertEqual(len({operation for values in calls.values() for operation in values}), 4)
        self.assertEqual(len(effects), 2)
        self.assertEqual(len(set(effects)), 2)
        self.assertEqual(len(self.rows(reopened, "attempts")), 4)
        self.assertEqual(len(self.rows(reopened, "provider_results")), 4)
        self.assertEqual(len(self.rows(reopened, "retry_decisions")), 4)

    def test_529_circuit_scope_open_half_open_close_and_reopen(self):
        codex_scope = {"profile": "codex-a", "resource_hash": "a" * 64,
                       "failure_threshold": 1, "open_seconds": 10, "probe_seconds": 5}
        claude_scope = {"profile": "claude-b", "resource_hash": "b" * 64,
                        "failure_threshold": 1, "open_seconds": 10, "probe_seconds": 5}
        jobs = [self.job("codex-circuit", "codex_cli", circuit=codex_scope),
                self.job("claude-free", "claude_host", circuit=claude_scope)]
        codex_calls: list[str] = []
        claude_calls: list[str] = []

        def dispatch(job, context):
            provider = job["_provider"].value
            if provider == "claude_host":
                claude_calls.append(context["operation_id"])
                return result(provider, context["operation_id"])
            codex_calls.append(context["operation_id"])
            if len(codex_calls) in (1, 3):
                return transient(provider, context["operation_id"], http_status=529)
            return result(provider, context["operation_id"])

        engine = self.engine("circuit", jobs, dispatch)
        summary = engine.tick(self.now)
        self.assertEqual((summary["retry_wait"], summary["succeeded"]), (1, 1))
        with engine._db() as db:
            db.execute("UPDATE slots SET next_attempt_at=? WHERE job_id='codex-circuit'",
                       ((self.now + timedelta(seconds=1)).timestamp(),))
        self.assertEqual(engine.tick(self.now + timedelta(seconds=1))["dispatched"], 0)
        self.assertEqual(len(codex_calls), 1)
        self.assertEqual(len(self.rows(engine, "attempts")), 2)
        self.assertEqual(engine.tick(self.now + timedelta(seconds=11))["succeeded"], 1)
        codex_circuit = next(row for row in self.rows(engine, "circuits") if row["provider"] == "codex_cli")
        self.assertEqual((codex_circuit["state"], codex_circuit["transient_failures"]), ("closed", 0))

        self.assertEqual(engine.tick(self.now + timedelta(seconds=60))["retry_wait"], 1)
        codex_circuit = next(row for row in self.rows(engine, "circuits") if row["provider"] == "codex_cli")
        self.assertEqual(codex_circuit["state"], "open")
        self.assertEqual(len(codex_calls), 3)
        self.assertEqual(len(claude_calls), 2)
        self.assertNotEqual(codex_circuit["scope_sha256"],
                            next(row for row in self.rows(engine, "circuits") if row["provider"] == "claude_host")["scope_sha256"])

    def test_post_submit_unknowns_block_and_registered_owner_proof_allows_one_retry(self):
        for index, failure in enumerate((FailureKind.TIMEOUT, FailureKind.CONNECTION_RESET,
                                         FailureKind.PARTIAL_RESPONSE)):
            with self.subTest(failure=failure.value):
                scope = f"scope/unknown-{index}"
                contract = self.contract(scope, reconcile=True)
                configured = self.job(f"unknown-{index}", "claude_host", contract=contract)
                calls: list[str] = []
                effects: list[str] = []

                def dispatch(_job, context):
                    calls.append(context["operation_id"])
                    if len(calls) == 1:
                        return unknown("claude_host", context["operation_id"], failure)
                    effects.append(context["operation_id"])
                    return result("claude_host", context["operation_id"])

                engine = self.engine(f"unknown-{index}", [configured], dispatch)
                self.assertEqual(engine.tick(self.now)["unknown"], 1)
                self.assertEqual(engine.tick(self.now + timedelta(seconds=60))["dispatched"], 0)
                self.assertEqual(calls, [self.rows(engine, "provider_results")[0]["operation_id"]])
                attempt = self.rows(engine, "attempts")[0]
                stored = self.rows(engine, "provider_results")[0]
                evidence = f"absence-{index}".encode()
                reconciled_at = self.now + timedelta(seconds=60)
                proof = ReconciliationProofV1(
                    attempt["attempt_id"], stored["operation_id"], scope,
                    stored["canonical_sha256"], "absent", hashlib.sha256(evidence).hexdigest(), reconciled_at)
                self.owner.proof = proof

                cross = ReconciliationProofV1(
                    "cross/attempt", stored["operation_id"], scope,
                    stored["canonical_sha256"], "absent", hashlib.sha256(evidence).hexdigest(), reconciled_at)
                self.owner.proof = cross
                with self.assertRaisesRegex(EngineError, "ATTEMPT_REQUIRED"):
                    engine.record_reconciliation_proof(
                        cross, evidence, "fixture://cross", "owner/one", "1", reconciled_at, adapter=self.owner)
                self.owner.proof = proof
                engine.record_reconciliation_proof(
                    proof, evidence, "fixture://absence", "owner/one", "1", reconciled_at, adapter=self.owner)
                with self.assertRaisesRegex(EngineError, "CONFLICT"):
                    conflicting_at = self.now + timedelta(seconds=61)
                    conflicting = ReconciliationProofV1(
                        attempt["attempt_id"], stored["operation_id"], scope,
                        stored["canonical_sha256"], "absent", hashlib.sha256(b"other").hexdigest(),
                        conflicting_at)
                    self.owner.proof = conflicting
                    engine.record_reconciliation_proof(
                        conflicting, b"other", "fixture://other", "owner/one", "1",
                        conflicting_at, adapter=self.owner)
                self.owner.proof = proof
                authorized = engine.authorize_reconciled_retry(
                    attempt["attempt_id"], self.now + timedelta(seconds=62))
                with self.assertRaisesRegex(EngineError, "UNKNOWN|CONSUMED"):
                    engine.authorize_reconciled_retry(attempt["attempt_id"], self.now + timedelta(seconds=63))
                due = datetime.fromisoformat(authorized["next_attempt_at"])
                reopened = self.engine(f"unknown-{index}", [configured], dispatch)
                self.assertEqual(reopened.tick(due)["succeeded"], 1)
                self.assertEqual(len(calls), 2)
                self.assertEqual(len(effects), 1)
                self.assertEqual(len(self.rows(reopened, "reconciliation_records")), 1)
                self.assertEqual(len(self.rows(reopened, "reconciliation_consumptions")), 1)
                with reopened._db() as db:
                    for statement in (
                            "UPDATE reconciliation_records SET evidence_ref=evidence_ref WHERE attempt_id=?",
                            "DELETE FROM reconciliation_records WHERE attempt_id=?",
                            "UPDATE reconciliation_consumptions SET consumed_at=consumed_at WHERE attempt_id=?",
                            "DELETE FROM reconciliation_consumptions WHERE attempt_id=?"):
                        with self.assertRaises(sqlite3.IntegrityError):
                            db.execute(statement, (attempt["attempt_id"],))

    def test_crash_points_recovery_wait_clock_deadline_stop_and_contenders(self):
        configured = self.job("crash", "codex_cli")

        class BeforeClaim(Engine):
            def _claim(self, job, now):
                raise CampaignCrash("before-claim")

        before = self.engine("before", [configured], lambda *_: self.fail("provider called"), cls=BeforeClaim)
        with self.assertRaises(CampaignCrash):
            before.tick(self.now)
        self.assertEqual(self.rows(before, "attempts"), [])
        self.assertEqual(self.rows(before, "slots")[0]["status"], "ready")

        after_claim = self.engine("after-claim", [configured], lambda *_: self.fail("provider called"))
        with after_claim._db() as db:
            db.execute("BEGIN IMMEDIATE")
            after_claim._allocate(db, configured, self.now.timestamp())
        context = after_claim._claim(after_claim.jobs["crash"], self.now.timestamp())
        self.assertIsNotNone(context)
        reopened_claim = self.engine("after-claim", [configured], lambda *_: self.fail("provider called"))
        self.assertEqual(reopened_claim.recover_running(self.now + timedelta(seconds=1)), 1)
        self.assertEqual(self.rows(reopened_claim, "slots")[0]["status"], "unknown")

        class BeforeDecision(Engine):
            def _finish_typed(self, job, context, provider_result, now):
                self.seen_result = provider_result.canonical_sha256
                raise CampaignCrash("typed-result-before-decision")

        before_decision = self.engine(
            "before-decision", [configured],
            lambda _job, ctx: result("codex_cli", ctx["operation_id"]), cls=BeforeDecision)
        with self.assertRaises(CampaignCrash):
            before_decision.tick(self.now)
        self.assertRegex(before_decision.seen_result, r"^[0-9a-f]{64}$")
        self.assertEqual(self.rows(before_decision, "provider_results"), [])
        self.assertEqual(before_decision.recover_running(self.now + timedelta(seconds=1)), 1)
        self.assertEqual(self.rows(before_decision, "slots")[0]["status"], "unknown")
        self.assertEqual(self.rows(before_decision, "attempts")[0]["status"], "unknown")
        recovered_result = self.rows(before_decision, "provider_results")
        recovered_decision = self.rows(before_decision, "retry_decisions")
        self.assertEqual((len(recovered_result), len(recovered_decision)), (1, 1))
        self.assertEqual(recovered_result[0]["status"], "unknown")
        self.assertEqual(json.loads(recovered_decision[0]["canonical_json"])["disposition"], "unknown")
        self.assertEqual(before_decision.tick(self.now + timedelta(seconds=2))["dispatched"], 0)

        class AfterCommit(Engine):
            def _finish_typed(self, job, context, provider_result, now):
                completed = super()._finish_typed(job, context, provider_result, now)
                raise CampaignCrash("after-decision-commit:" + completed)

        committed_calls: list[str] = []
        after_commit = self.engine(
            "after-commit", [configured],
            lambda _job, ctx: committed_calls.append(ctx["operation_id"]) or result("codex_cli", ctx["operation_id"]),
            cls=AfterCommit)
        with self.assertRaises(CampaignCrash):
            after_commit.tick(self.now)
        committed = self.engine("after-commit", [configured], lambda *_: self.fail("duplicate provider effect"))
        self.assertEqual(committed.tick(self.now + timedelta(seconds=1))["dispatched"], 0)
        self.assertEqual(len(committed_calls), 1)
        self.assertEqual((len(self.rows(committed, "attempts")), len(self.rows(committed, "provider_results")),
                          len(self.rows(committed, "retry_decisions"))), (1, 1, 1))

        rollback = self.engine("rollback", [configured], lambda _job, ctx: result("codex_cli", ctx["operation_id"]))
        rollback.tick(self.now)
        with self.assertRaisesRegex(EngineError, "CLOCK_MOVED_BACKWARDS"):
            rollback.tick(self.now - timedelta(seconds=1))

        deadline_policy = RetryPolicyV2(3, 2, 30, deadline_seconds=5)
        deadline_job = self.job("deadline", "codex_cli", policy=deadline_policy)
        deadline = self.engine(
            "deadline", [deadline_job],
            lambda _job, ctx: transient("codex_cli", ctx["operation_id"],
                                        retry_after=self.now + timedelta(seconds=10)))
        self.assertEqual(deadline.tick(self.now)["failed"], 1)
        self.assertIn("DEADLINE", self.rows(deadline, "slots")[0]["code"])

        expired_job = self.job(
            "expired", "codex_cli",
            schedule={"kind": "once", "at": self.now.isoformat(), "grace_seconds": 1})
        expired = self.engine("expired", [expired_job], lambda *_: self.fail("expired provider called"))
        self.assertEqual(expired.tick(self.now + timedelta(seconds=2))["dispatched"], 0)
        self.assertEqual(self.rows(expired, "slots")[0]["code"], "GRACE_EXPIRED")

        provider_called = []
        prompt = self.workspace / "prompt.md"
        prompt.write_text("synthetic")
        config = {"schema_version": 2, "model_profiles": {"p": {
            "provider": "codex_cli", "codex_bin": "/bin/false", "model": "fixture",
            "effort": "low", "timeout_seconds": 1,
            "auth_home": str(self.workspace / ".job-runtime" / "auth")}}}
        service_job = {"id": "stop", "model_profile": "p", "prompt_file": "prompt.md"}
        service.STOP.set()
        stopped = service.dispatcher(config, self.workspace, {
            "codex_cli": lambda *args: provider_called.append(args)})
        stopped_result = stopped(service_job, {"operation_id": "attempt/stop", "attempt_id": "stop"})
        self.assertEqual(stopped_result.code, "SHUTDOWN_BEFORE_DISPATCH")
        self.assertEqual(provider_called, [])
        service.STOP.clear()

        contender_calls: list[str] = []
        lock = threading.Lock()
        provider_entered = threading.Event()
        release_provider = threading.Event()
        def contender_dispatch(_job, ctx):
            with lock:
                contender_calls.append(ctx["operation_id"])
            provider_entered.set()
            if not release_provider.wait(timeout=2):
                raise AssertionError("contender release timed out")
            return result("codex_cli", ctx["operation_id"])
        one = self.engine("contenders", [configured], contender_dispatch)
        two = self.engine("contenders", [configured], contender_dispatch)
        barrier = threading.Barrier(2)
        summaries = []
        errors: list[BaseException] = []
        def contend(engine):
            try:
                barrier.wait(timeout=2)
                summaries.append(engine.tick(self.now))
            except BaseException as error:
                errors.append(error)
        threads = [threading.Thread(target=contend, args=(candidate,)) for candidate in (one, two)]
        for thread in threads:
            thread.start()
        self.assertTrue(provider_entered.wait(timeout=2), "no contender reached provider")
        release_provider.set()
        for thread in threads:
            thread.join(timeout=3)
        self.assertTrue(all(not thread.is_alive() for thread in threads), "contender thread hung")
        if errors:
            raise errors[0]
        self.assertEqual(sum(item["dispatched"] for item in summaries), 1)
        self.assertEqual(len(contender_calls), 1)
        self.assertEqual(len(self.rows(one, "attempts")), 1)

    def test_type_exception_cancel_receipt_immutability_drift_and_legacy_v1(self):
        configured = self.job("boundaries", "claude_host")
        cases = [
            ("dict", lambda *_: {"status": "succeeded", "receipt": {"ok": True}}),
            ("exception", lambda *_: (_ for _ in ()).throw(RuntimeError("SECRET-provider-body"))),
        ]
        for label, dispatcher in cases:
            with self.subTest(label=label):
                engine = self.engine(label, [configured], dispatcher)
                self.assertEqual(engine.tick(self.now)["unknown"], 1)
                canonical = self.rows(engine, "provider_results")[0]["canonical_json"]
                self.assertNotIn("SECRET", canonical)
                self.assertIn('"status":"unknown"', canonical)

        cancelled = self.engine(
            "cancelled", [configured],
            lambda *_: (_ for _ in ()).throw(asyncio.CancelledError()))
        with self.assertRaises(asyncio.CancelledError):
            cancelled.tick(self.now)
        self.assertEqual(self.rows(cancelled, "attempts")[0]["status"], "running")
        self.assertEqual(cancelled.recover_running(self.now + timedelta(seconds=1)), 1)

        with self.assertRaisesRegex(ContractError, "SECRET_KEY"):
            result("claude_host", "attempt/secret", receipt={"api_token": "not-a-real-secret"})
        with self.assertRaisesRegex(ContractError, "BOUNDS"):
            result("claude_host", "attempt/large", receipt={"safe": "x" * 3000})

        immutable = self.engine(
            "immutable", [configured],
            lambda _job, ctx: transient("claude_host", ctx["operation_id"]))
        immutable.tick(self.now)
        attempt = self.rows(immutable, "attempts")[0]
        with immutable._db() as db:
            for statement in (
                    "UPDATE provider_results SET status=status WHERE attempt_id=?",
                    "DELETE FROM provider_results WHERE attempt_id=?",
                    "UPDATE retry_decisions SET canonical_json=canonical_json WHERE attempt_id=?",
                    "DELETE FROM retry_decisions WHERE attempt_id=?"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement, (attempt["attempt_id"],))

        scope = {"profile": "drift", "resource_hash": "d" * 64,
                 "failure_threshold": 2, "open_seconds": 10, "probe_seconds": 5}
        originals = self.job("drift", "claude_host", circuit=scope)
        drift = self.engine(
            "drift", [originals],
            lambda _job, ctx: transient("claude_host", ctx["operation_id"]))
        drift.tick(self.now)
        with drift._db() as db:
            db.execute("UPDATE slots SET next_attempt_at=?", ((self.now + timedelta(seconds=1)).timestamp(),))
        changed = self.job("drift", "claude_host", circuit={**scope, "open_seconds": 11})
        reopened = self.engine("drift", [changed], lambda *_: self.fail("drift dispatched"))
        with self.assertRaisesRegex(EngineError, "CONFIG_DRIFT"):
            reopened.tick(self.now + timedelta(seconds=1))
        self.assertEqual(len(self.rows(reopened, "attempts")), 1)

        # Receipt/file consistency only; the subprocess generation suite proves
        # that a running process keeps its loaded generation across source drift.
        source_receipt_hashes = service.service_generation()["provider_implementations"]
        root = Path(service.__file__).resolve().parent
        expected = {
            "model": hashlib.sha256((root / "model.py").read_bytes()).hexdigest(),
            "provider_codex_cli": hashlib.sha256((root / "providers" / "codex_cli.py").read_bytes()).hexdigest(),
            "provider_claude_host": hashlib.sha256((root / "providers" / "claude_host.py").read_bytes()).hexdigest(),
            "claude_bridge": hashlib.sha256((root / "claude_bridge.py").read_bytes()).hexdigest(),
        }
        self.assertEqual(source_receipt_hashes, expected)

        legacy = {"id": "legacy", "enabled": True, "replay_safe": True,
                  "schedule": {"kind": "interval", "seconds": 60, "grace_seconds": 120}}
        legacy_calls = []
        def legacy_dispatch(_job, context):
            legacy_calls.append(context["attempt_no"])
            if len(legacy_calls) == 1:
                return {"status": "retryable", "code": "TEMPORARY"}
            return {"status": "succeeded", "code": "COMPLETED", "receipt": {"fixture": True}}
        legacy_engine = self.engine("legacy", [legacy], legacy_dispatch)
        self.assertEqual(legacy_engine.tick(self.now)["retry_wait"], 1)
        self.assertEqual(self.rows(legacy_engine, "slots")[0]["next_attempt_at"],
                         self.now.timestamp() + LEGACY_RETRY["backoff_seconds"])
        reopened_legacy = self.engine("legacy", [legacy], legacy_dispatch)
        self.assertEqual(reopened_legacy.tick(self.now + timedelta(seconds=5))["succeeded"], 1)
        self.assertEqual(legacy_calls, [1, 2])
        self.assertEqual(self.rows(reopened_legacy, "provider_results"), [])
        self.assertEqual(self.rows(reopened_legacy, "retry_decisions"), [])

    def test_attempt_lifecycle_guards_allow_owned_transitions_only(self):
        configured = self.job("attempt-ledger", "codex_cli")
        engine = self.engine(
            "attempt-ledger", [configured],
            lambda _job, context: result("codex_cli", context["operation_id"]))
        self.assertEqual(engine.tick(self.now)["succeeded"], 1)
        attempt = self.rows(engine, "attempts")[0]
        self.assertEqual(attempt["status"], "succeeded")
        with engine._db() as db:
            for statement in (
                    "UPDATE attempts SET code='MUTATED' WHERE attempt_id=?",
                    "DELETE FROM attempts WHERE attempt_id=?"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement, (attempt["attempt_id"],))

        unknown_job = self.job("operator-ledger", "claude_host")
        unknown_engine = self.engine(
            "operator-ledger", [unknown_job],
            lambda _job, context: unknown(
                "claude_host", context["operation_id"], FailureKind.TIMEOUT))
        self.assertEqual(unknown_engine.tick(self.now)["unknown"], 1)
        slot = self.rows(unknown_engine, "slots")[0]
        unknown_engine.resolve_unknown(
            slot["slot_id"], "failed", {"operator_evidence": True},
            self.now + timedelta(seconds=1))
        reconciled = self.rows(unknown_engine, "attempts")[0]
        self.assertEqual((reconciled["status"], reconciled["code"]),
                         ("failed", "OPERATOR_RECONCILED"))
        self.assertIsNotNone(reconciled["receipt"])
        with unknown_engine._db() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE attempts SET code='MUTATED' WHERE attempt_id=?",
                           (reconciled["attempt_id"],))


if __name__ == "__main__":
    unittest.main()
