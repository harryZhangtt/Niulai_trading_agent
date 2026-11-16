"""Provider-neutral durable retry, reconciliation, migration, and circuit tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest

from shared.job_runtime.config import load
from shared.job_runtime.engine import Engine, EngineError, SCHEMA_VERSION
from shared.job_runtime.service import resource_jobs
from shared.job_runtime.provider_contract import (
    FailureKind, Phase, ProviderResultV1, ReconciliationProofV1,
    ReplayContractV1, ReplayEffect, ResultStatus, Submission, TerminalProof,
)
from shared.job_runtime.retry_policy import (
    RetryPolicyV2, deterministic_full_jitter, validate_retry_policy,
)
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1

ROOT = Path(__file__).resolve().parents[3]
PRIVATE = ROOT / ".job-runtime" / "provider-retry-tests"
PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
UTC = timezone.utc
LEGACY_RETRY = {"max_attempts": 3, "backoff_seconds": 5, "max_backoff_seconds": 10}
_V0_RECEIPT = '{"legacy":true,"order":[2,1]}'
_V0_CANONICAL = json.dumps({
    "attempt": ["old-attempt", "old-slot", 1, 1700000000, 1700000001,
                "succeeded", "LEGACY_OK", _V0_RECEIPT],
    "heartbeat": "2023-11-14T22:13:20+00:00",
    "job": ["old-job", "a" * 64, 1700000000],
    "slot": ["old-slot", "old-job", 1699999900, 1700000020,
             "succeeded", 1, None, 1700000001, "LEGACY_OK"],
    "user_version": 0,
}, sort_keys=True, separators=(",", ":")).encode()
_V0_CANONICAL_SHA256 = "2377ce71b28a101d794719766ca4244ff2fdda361a134fc231b95bf7d5465fc0"


def write_v0_fixture(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.executescript('''
        CREATE TABLE jobs(job_id TEXT PRIMARY KEY,schedule_hash TEXT NOT NULL,cursor REAL NOT NULL);
        CREATE TABLE slots(slot_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,scheduled_at REAL NOT NULL,
          expires_at REAL NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at REAL,updated_at REAL NOT NULL,code TEXT NOT NULL);
        CREATE INDEX slot_due ON slots(status,next_attempt_at,scheduled_at);
        CREATE UNIQUE INDEX job_one_running ON slots(job_id) WHERE status='running';
        CREATE TABLE attempts(attempt_id TEXT PRIMARY KEY,slot_id TEXT NOT NULL,attempt_no INTEGER NOT NULL,
          started_at REAL NOT NULL,ended_at REAL,status TEXT NOT NULL,code TEXT NOT NULL,receipt TEXT);
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE delivery_reconciliations(slot_id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL,
          message_id TEXT NOT NULL,payload_digest TEXT NOT NULL,verified_at TEXT NOT NULL,
          recorded_at REAL NOT NULL,receipt TEXT NOT NULL);
        CREATE TRIGGER immutable_delivery_reconciliation_update BEFORE UPDATE ON delivery_reconciliations
          BEGIN SELECT RAISE(ABORT,'delivery reconciliation is immutable'); END;
        CREATE TRIGGER immutable_delivery_reconciliation_delete BEFORE DELETE ON delivery_reconciliations
          BEGIN SELECT RAISE(ABORT,'delivery reconciliation is immutable'); END;
        ''')
        db.execute("INSERT INTO jobs VALUES(?,?,?)", ("old-job", "a" * 64, 1700000000))
        db.execute("INSERT INTO slots VALUES(?,?,?,?,?,?,?,?,?)",
                   ("old-slot", "old-job", 1699999900, 1700000020,
                    "succeeded", 1, None, 1700000001, "LEGACY_OK"))
        db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)",
                   ("old-attempt", "old-slot", 1, 1700000000, 1700000001,
                    "succeeded", "LEGACY_OK", _V0_RECEIPT))
        db.execute("INSERT INTO metadata VALUES(?,?)",
                   ("heartbeat", "2023-11-14T22:13:20+00:00"))
        db.execute("PRAGMA user_version=0")
        db.commit()
    finally:
        db.close()
    return path


def at(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def circuit_config_sha(scope):
    encoded = json.dumps(scope, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def retry_result(operation="operation/1", retry_after=None):
    return ProviderResultV1(
        "claude_host", operation, Phase.CONNECTING, Submission.NOT_SUBMITTED,
        TerminalProof.ABSENT, ResultStatus.RETRYABLE, "HTTP_RATE_LIMITED",
        failure_kind=FailureKind.HTTP, http_status=429, provider_should_retry=True,
        retry_after_at=retry_after,
        retry_after_source="typed-timestamp" if retry_after else None,
    )


def unknown_result(operation="operation/1"):
    return ProviderResultV1(
        "claude_host", operation, Phase.TERMINAL, Submission.POSSIBLY_SUBMITTED,
        TerminalProof.ABSENT, ResultStatus.UNKNOWN, "PROVIDER_TIMEOUT",
        failure_kind=FailureKind.TIMEOUT,
    )


def prompt_artifact(prompt="pinned typed prompt", generation="allocation-a"):
    raw = prompt.encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    identity = hashlib.sha256(("fixture://" + prompt).encode()).hexdigest()
    return PromptArtifactDescriptorV1(
        1, f"pa1:sha256:{digest}:{len(raw)}", digest, len(raw), identity,
        generation, "native_v1")


class OwnedAdapter:
    def __init__(self):
        self.proof = None

    def reconcile(self, *, attempt_id, operation_id, slot_operation_scope):
        if self.proof is None:
            raise AssertionError("proof not installed")
        return self.proof


class EngineProviderRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PRIVATE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / ".job-runtime" / "engine"
        self.now = at("2026-11-06T12:00:00Z")
        self.policy = RetryPolicyV2(3, 2, 30, deadline_seconds=100)
        self.adapter = OwnedAdapter()

    def job(self, *, contract=None, circuit=None, job_id="typed-job"):
        return {
            "id": job_id, "enabled": True, "replay_safe": True,
            "schedule": {"kind": "interval", "seconds": 60, "grace_seconds": 120},
            "_provider": "claude_host",
            "_replay_contract": contract or ReplayContractV1(
                ReplayEffect.IDEMPOTENT, (Phase.CONNECTING,), "scope/typed"),
            "_retry_policy": self.policy,
            "_prompt_artifact": prompt_artifact(),
            **({"_circuit_scope": circuit} if circuit else {}),
        }

    def engine(self, dispatcher, *, jobs=None, state=None, clock=None, cls=Engine):
        return cls(state or self.state, jobs or [self.job()], LEGACY_RETRY, dispatcher,
                   workspace_root=self.root, clock=clock or (lambda: self.now), max_workers=1,
                   reconciliation_adapters={"adapter/one": self.adapter})

    def rows(self, engine, table):
        with engine._db() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]

    def test_pre_submit_429_retry_after_is_exact_and_restart_does_not_redraw(self):
        provider_at = self.now + timedelta(seconds=17)
        engine = self.engine(lambda _job, context: retry_result(
            context["operation_id"], retry_after=provider_at))
        summary = engine.tick(self.now)
        self.assertEqual(summary["retry_wait"], 1)
        slot = self.rows(engine, "slots")[0]
        decision = self.rows(engine, "retry_decisions")[0]
        self.assertEqual(slot["next_attempt_at"], provider_at.timestamp())
        self.assertEqual(decision["next_attempt_at"], provider_at.timestamp())
        restarted = self.engine(lambda *_: self.fail("not due"))
        self.assertEqual(restarted.tick(self.now + timedelta(seconds=16))["dispatched"], 0)
        self.assertEqual(self.rows(restarted, "slots")[0]["next_attempt_at"], provider_at.timestamp())

    def test_prompt_artifact_is_pinned_across_allocation_retry_and_restart(self):
        artifact_a = prompt_artifact("allocation prompt A", "allocation-a")
        artifact_b = prompt_artifact("allocation prompt B", "allocation-b")
        configured = self.job()
        configured["_prompt_artifact"] = artifact_a
        observed = []

        def first(_job, context):
            observed.append(context)
            return retry_result(context["operation_id"])

        engine = self.engine(first, jobs=[configured])
        self.assertEqual(engine.tick(self.now)["retry_wait"], 1)
        slot = self.rows(engine, "slots")[0]
        binding = slot["binding_sha256"]
        self.assertEqual(
            tuple(slot[name] for name in (
                "artifact_ref", "sha256", "length", "version",
                "source_identity_sha256", "generation", "proof_origin")),
            (artifact_a.ref, artifact_a.sha256, artifact_a.length, artifact_a.version,
             artifact_a.source_identity_sha256, artifact_a.generation, "native_v1"))
        self.assertEqual(observed[0]["prompt_artifact"], artifact_a)
        self.assertEqual(observed[0]["prompt_binding_sha256"], binding)
        self.assertEqual(observed[0]["operation_id"],
                         f"attempt/{observed[0]['attempt_id']}/prompt/{binding}")
        with engine._db() as db, self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE slots SET artifact_ref=? WHERE slot_id=?",
                       (artifact_b.ref, slot["slot_id"]))

        changed = self.job()
        changed["_prompt_artifact"] = artifact_b

        def second(_job, context):
            observed.append(context)
            return ProviderResultV1(
                "claude_host", context["operation_id"], Phase.TERMINAL,
                Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
                ResultStatus.SUCCEEDED, "MODEL_TURN_COMPLETED",
                failure_kind=FailureKind.NONE)

        restarted = self.engine(second, jobs=[changed])
        self.assertEqual(restarted.tick(self.now + timedelta(seconds=31))["succeeded"], 1)
        self.assertEqual([item["prompt_artifact"] for item in observed],
                         [artifact_a, artifact_a])
        self.assertEqual({item["prompt_binding_sha256"] for item in observed}, {binding})
        attempts = self.rows(restarted, "attempts")
        self.assertEqual({row["binding_sha256"] for row in attempts}, {binding})
        self.assertEqual({row["artifact_ref"] for row in attempts}, {artifact_a.ref})

    def test_missing_artifact_metadata_is_a_fixed_non_dispatchable_failure(self):
        engine = self.engine(lambda *_: self.fail("missing artifact must not dispatch"))
        with engine._db() as db:
            db.execute("BEGIN IMMEDIATE")
            engine._allocate(db, engine.jobs["typed-job"], self.now.timestamp())
        # Deliberately bypass runtime FK enforcement to simulate on-disk corruption.
        with sqlite3.connect(engine.path) as corrupt:
            corrupt.execute("DROP TRIGGER immutable_prompt_artifacts_delete")
            corrupt.execute("DELETE FROM prompt_artifacts")
        self.assertEqual(engine.tick(self.now)["dispatched"], 0)
        slot = self.rows(engine, "slots")[0]
        self.assertEqual((slot["status"], slot["code"]),
                         ("failed", "PROMPT_ARTIFACT_METADATA_MISSING"))
        self.assertEqual(self.rows(engine, "attempts"), [])

    def test_typed_legacy_unbound_slot_is_fixed_non_dispatchable_failure(self):
        engine = self.engine(lambda *_: self.fail("legacy-unbound slot must not dispatch"))
        with engine._db() as db:
            db.execute("BEGIN IMMEDIATE")
            engine._allocate(db, engine.jobs["typed-job"], self.now.timestamp())
            db.execute("DROP TRIGGER immutable_slot_prompt_update")
            db.execute("""UPDATE slots SET artifact_ref=NULL,sha256=NULL,length=NULL,version=NULL,
                       source_identity_sha256=NULL,binding_sha256=NULL,generation=NULL,
                       proof_origin='legacy_unbound'""")
        self.assertEqual(engine.tick(self.now)["dispatched"], 0)
        slot = self.rows(engine, "slots")[0]
        self.assertEqual((slot["status"], slot["code"], slot["proof_origin"]),
                         ("failed", "PROMPT_BINDING_NON_DISPATCHABLE", "legacy_unbound"))
        self.assertEqual(self.rows(engine, "attempts"), [])

    def test_schema9_prompt_completeness_and_binding_triggers_are_installed(self):
        engine = self.engine(lambda *_: self.fail("schema inspection only"))
        with engine._db() as db:
            names = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'")}
            self.assertTrue({
                "slot_prompt_complete_insert", "immutable_slot_prompt_update",
                "attempt_prompt_exact_insert", "immutable_prompt_artifacts_update",
                "immutable_prompt_artifacts_delete", "bind_provider_results_insert",
                "bind_retry_decisions_insert", "bind_reconciliation_records_insert",
                "bind_reconciliation_consumptions_insert",
            } <= names)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("""INSERT INTO slots(
                    slot_id,job_id,scheduled_at,expires_at,status,updated_at,code,
                    artifact_ref,proof_origin) VALUES(?,?,?,?,?,?,?,?,?)""",
                           ("incomplete", "typed-job", 1, 2, "ready", 1, "DUE",
                            "pa1:sha256:" + "0" * 64 + ":1", "native_v1"))

    def test_deterministic_jitter_deadline_attempt_limit_and_nonreplay_fence(self):
        engine = self.engine(lambda _job, context: retry_result(context["operation_id"]))
        engine.tick(self.now)
        slot = self.rows(engine, "slots")[0]
        expected = self.now.timestamp() + deterministic_full_jitter(
            slot_id=slot["slot_id"], attempt=1, policy=self.policy)
        self.assertAlmostEqual(slot["next_attempt_at"], expected, places=6)

        unsafe = self.job(contract=ReplayContractV1(ReplayEffect.NONE, (Phase.NOT_STARTED,), "scope/no"),
                          job_id="unsafe")
        other = self.engine(lambda _job, context: retry_result(context["operation_id"]),
                            jobs=[unsafe], state=self.root / ".job-runtime" / "unsafe")
        self.assertEqual(other.tick(self.now)["unknown"], 1)

        limited = self.job(job_id="limited")
        limited["_retry_policy"] = RetryPolicyV2(1, 2, 30)
        last = self.engine(lambda _job, context: retry_result(context["operation_id"]),
                           jobs=[limited], state=self.root / ".job-runtime" / "limited")
        self.assertEqual(last.tick(self.now)["failed"], 1)
        self.assertEqual(self.rows(last, "slots")[0]["code"], "ATTEMPTS_EXHAUSTED")

    def test_typed_job_rejects_legacy_dict_success_and_retry(self):
        for index, legacy_result in enumerate((
                {"status": "succeeded", "code": "LEGACY_SUCCESS", "receipt": {"ok": True}},
                {"status": "retryable", "code": "LEGACY_RETRY"})):
            state = self.root / ".job-runtime" / f"typed-dict-{index}"
            engine = self.engine(lambda *_args, value=legacy_result: value, state=state)
            self.assertEqual(engine.tick(self.now)["unknown"], 1)
            slot = self.rows(engine, "slots")[0]
            self.assertEqual((slot["status"], slot["code"]),
                             ("unknown", "PROVIDER_OUTCOME_UNKNOWN"))
            stored = self.rows(engine, "provider_results")[0]
            self.assertEqual(json.loads(stored["canonical_json"])["code"],
                             "TYPED_PROVIDER_RESULT_REQUIRED")
            self.assertEqual(len(self.rows(engine, "retry_decisions")), 1)

    def test_transient_at_attempt_limit_still_opens_circuit(self):
        scope = {"profile": "limited", "resource_hash": "c" * 64,
                 "failure_threshold": 1, "open_seconds": 10, "probe_seconds": 5}
        configured = self.job(circuit=scope, job_id="limited-circuit")
        configured["_retry_policy"] = RetryPolicyV2(1, 2, 30)
        engine = self.engine(lambda _job, context: retry_result(context["operation_id"]),
                             jobs=[configured])
        self.assertEqual(engine.tick(self.now)["failed"], 1)
        circuit = self.rows(engine, "circuits")[0]
        self.assertEqual((circuit["state"], circuit["transient_failures"]), ("open", 1))

    def test_config_v2_resource_jobs_engine_boundary_and_policy_modes(self):
        private = self.root / ".job-runtime"
        private.mkdir(mode=0o700, exist_ok=True)
        auth = private / "auth"
        auth.mkdir(mode=0o700)
        prompts = private / "config"
        prompts.mkdir(mode=0o700)
        prompts.chmod(0o700)
        prompt = prompts / "job.txt"
        prompt.write_text("synthetic provider boundary")
        prompt.chmod(0o600)
        allocation = self.root / "allocation-v2.json"
        allocation.write_text(json.dumps({
            "schema_version": 2,
            "jobs": [{
                "id": "config-v2-job", "enabled": True,
                "schedule": {"kind": "interval", "seconds": 60, "grace_seconds": 120},
                "model_profile": "primary", "prompt_file": ".job-runtime/config/job.txt",
                "replay_contract": {
                    "version": 1, "effect": "idempotent",
                    "automatic_phases": ["connecting"],
                    "slot_operation_scope": "scope/config-v2",
                    "reconciliation_adapter": None,
                },
            }],
        }))
        retry_v2 = {
            "version": 2, "max_attempts": 3, "base_delay_seconds": 2,
            "max_delay_seconds": 30, "deadline_seconds": 100,
            "jitter": "sha256-full-jitter-v1",
        }
        config_path = private / "config-v2.json"
        config_path.write_text(json.dumps({
            "schema_version": 2, "tick_seconds": 5, "heartbeat_seconds": 10,
            "stale_seconds": 60, "max_workers": 1, "retry": retry_v2,
            "model_profiles": {"primary": {
                "provider": "claude_host", "model": "synthetic-model",
                "effort": "low", "timeout_seconds": 30, "auth_home": str(auth),
                "circuit": {"failure_threshold": 2, "open_seconds": 20,
                            "probe_seconds": 5},
            }},
            "allocation_files": ["allocation-v2.json"], "source_paths": [],
        }))
        config_path.chmod(0o600)
        config, jobs = load(config_path, self.root)
        prepared = [
            {**{key: value for key, value in job.items()
                if not key.startswith("_prompt_")},
             "_prompt_artifact": prompt_artifact(
                 (self.root / job["prompt_file"]).read_text(), "config-v2")}
            for job in resource_jobs(config, jobs)
        ]
        self.assertTrue(all(
            "_provider" in job and "_retry_policy" in job
            and isinstance(job.get("_prompt_artifact"), PromptArtifactDescriptorV1)
            for job in prepared))
        engine = Engine(
            private / "boundary-engine", prepared, config["retry"],
            lambda _job, context: ProviderResultV1(
                "claude_host", context["operation_id"], Phase.TERMINAL,
                Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
                ResultStatus.SUCCEEDED, "COMPLETED"),
            workspace_root=self.root, clock=lambda: self.now, max_workers=1)
        self.assertIsNone(engine.retry)
        self.assertEqual(engine.global_retry_policy.fingerprint,
                         validate_retry_policy(retry_v2).fingerprint)
        self.assertEqual(engine.tick(self.now)["succeeded"], 1)

        object_engine = Engine(
            private / "boundary-policy-object", prepared, validate_retry_policy(retry_v2),
            lambda *_: self.fail("constructor only"), workspace_root=self.root,
            clock=lambda: self.now, max_workers=1)
        self.assertEqual(object_engine.global_retry_policy.fingerprint,
                         engine.global_retry_policy.fingerprint)
        legacy = {"id": "boundary-legacy", "enabled": True, "replay_safe": True,
                  "schedule": {"kind": "interval", "seconds": 60, "grace_seconds": 120}}
        legacy_engine = Engine(
            private / "boundary-legacy", [legacy], LEGACY_RETRY,
            lambda *_: {"status": "retryable", "code": "TEMP"},
            workspace_root=self.root, clock=lambda: self.now, max_workers=1)
        self.assertEqual(legacy_engine.tick(self.now)["retry_wait"], 1)
        self.assertEqual(legacy_engine.retry, LEGACY_RETRY)
        with self.assertRaisesRegex(EngineError, "V2_POLICY_REQUIRES_TYPED_JOBS"):
            Engine(private / "boundary-v2-untyped", [legacy], retry_v2, lambda *_: None,
                   workspace_root=self.root, clock=lambda: self.now)
        with self.assertRaisesRegex(EngineError, "MIXED_JOB_POLICY_MODES"):
            Engine(private / "boundary-mixed", [prepared[0], legacy], retry_v2, lambda *_: None,
                   workspace_root=self.root, clock=lambda: self.now)

    def test_legacy_dict_retry_behavior_is_unchanged(self):
        legacy = {"id": "legacy", "enabled": True, "replay_safe": True,
                  "schedule": {"kind": "interval", "seconds": 60, "grace_seconds": 120}}
        engine = self.engine(lambda *_: {"status": "retryable", "code": "TEMP"}, jobs=[legacy])
        self.assertEqual(engine.tick(self.now)["retry_wait"], 1)
        slot = self.rows(engine, "slots")[0]
        self.assertEqual(slot["next_attempt_at"], self.now.timestamp() + 5)
        self.assertEqual(self.rows(engine, "provider_results"), [])

    def test_unicode_provider_canonical_retry_reconciliation_and_encoding_rejection(self):
        retry_state = self.root / ".job-runtime" / "unicode-retry"
        def unicode_retry(_job, context):
            return ProviderResultV1(
                "claude_host", context["operation_id"], Phase.CONNECTING,
                Submission.NOT_SUBMITTED, TerminalProof.ABSENT,
                ResultStatus.RETRYABLE, "HTTP_RATE_LIMITED",
                failure_kind=FailureKind.HTTP, http_status=429,
                receipt={"label": "café"})
        retry_engine = self.engine(unicode_retry, state=retry_state)
        self.assertEqual(retry_engine.tick(self.now)["retry_wait"], 1)
        retry_row = self.rows(retry_engine, "provider_results")[0]
        self.assertIn("caf\\u00e9", retry_row["canonical_json"])
        self.assertEqual(hashlib.sha256(retry_row["canonical_json"].encode()).hexdigest(),
                         retry_row["canonical_sha256"])

        contract = ReplayContractV1(ReplayEffect.RECONCILE_BEFORE_REPLAY,
                                    (Phase.CONNECTING,), "scope/unicode", "adapter/one")
        captured = []
        def unicode_unknown(_job, context):
            captured.append(ProviderResultV1(
                "claude_host", context["operation_id"], Phase.TERMINAL,
                Submission.POSSIBLY_SUBMITTED, TerminalProof.ABSENT,
                ResultStatus.UNKNOWN, "PROVIDER_TIMEOUT", failure_kind=FailureKind.TIMEOUT,
                receipt={"label": "café"}))
            return captured[-1]
        reconcile_state = self.root / ".job-runtime" / "unicode-reconcile"
        reconcile_engine = self.engine(
            unicode_unknown, jobs=[self.job(contract=contract, job_id="unicode-reconcile")],
            state=reconcile_state)
        self.assertEqual(reconcile_engine.tick(self.now)["unknown"], 1)
        attempt = self.rows(reconcile_engine, "attempts")[0]
        result = captured[0]
        stored = self.rows(reconcile_engine, "provider_results")[0]
        self.assertEqual(stored["canonical_sha256"], result.canonical_sha256)
        evidence = b"unicode-absence"
        proof = ReconciliationProofV1(
            attempt["attempt_id"], result.operation_id, contract.slot_operation_scope,
            result.canonical_sha256, "absent", hashlib.sha256(evidence).hexdigest(), self.now)
        self.adapter.proof = proof
        reconcile_engine.record_reconciliation_proof(
            proof, evidence, "fixture://unicode", "adapter/one", "1", self.now,
            adapter=self.adapter)
        self.assertEqual(reconcile_engine.authorize_reconciled_retry(
            attempt["attempt_id"], self.now + timedelta(seconds=1))["status"], "retry_wait")

        corrupt_state = self.root / ".job-runtime" / "unicode-corrupt"
        corrupt_results = []
        corrupt_engine = self.engine(
            lambda _job, context: corrupt_results.append(ProviderResultV1(
                "claude_host", context["operation_id"], Phase.TERMINAL,
                Submission.POSSIBLY_SUBMITTED, TerminalProof.ABSENT,
                ResultStatus.UNKNOWN, "PROVIDER_TIMEOUT", failure_kind=FailureKind.TIMEOUT,
                receipt={"label": "café"})) or corrupt_results[-1],
            jobs=[self.job(contract=contract, job_id="unicode-corrupt")], state=corrupt_state)
        corrupt_engine.tick(self.now)
        corrupt_attempt = self.rows(corrupt_engine, "attempts")[0]
        corrupt_result = corrupt_results[0]
        with corrupt_engine._db() as db:
            db.execute("DROP TRIGGER immutable_provider_results_update")
            canonical = db.execute("SELECT canonical_json FROM provider_results WHERE attempt_id=?",
                                   (corrupt_attempt["attempt_id"],)).fetchone()[0]
            alternate = json.dumps(json.loads(canonical), sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False)
            self.assertNotEqual(alternate, canonical)
            db.execute("UPDATE provider_results SET canonical_json=? WHERE attempt_id=?",
                       (alternate, corrupt_attempt["attempt_id"]))
        corrupt_proof = ReconciliationProofV1(
            corrupt_attempt["attempt_id"], corrupt_result.operation_id,
            contract.slot_operation_scope, corrupt_result.canonical_sha256, "absent",
            hashlib.sha256(evidence).hexdigest(), self.now)
        self.adapter.proof = corrupt_proof
        with self.assertRaisesRegex(EngineError, "STORED_DIGEST_MISMATCH"):
            corrupt_engine.record_reconciliation_proof(
                corrupt_proof, evidence, "fixture://unicode", "adapter/one", "1", self.now,
                adapter=self.adapter)

    def test_post_submit_unknown_requires_exact_single_use_proof(self):
        captured = []
        contract = ReplayContractV1(ReplayEffect.RECONCILE_BEFORE_REPLAY,
                                    (Phase.CONNECTING,), "scope/typed", "adapter/one")
        def dispatch(_job, context):
            captured.append(unknown_result(context["operation_id"]))
            return captured[-1]
        engine = self.engine(dispatch, jobs=[self.job(contract=contract)])
        self.assertEqual(engine.tick(self.now)["unknown"], 1)
        result = captured[0]
        attempt = self.rows(engine, "attempts")[0]
        evidence = b'{"absence":"verified"}'
        proof = ReconciliationProofV1(
            attempt["attempt_id"], result.operation_id, contract.slot_operation_scope,
            result.canonical_sha256, "absent", hashlib.sha256(evidence).hexdigest(),
            self.now + timedelta(seconds=1))
        self.adapter.proof = proof
        recorded = engine.record_reconciliation_proof(
            proof, evidence, "fixture://absence", "adapter/one", "1",
            self.now + timedelta(seconds=2), adapter=self.adapter)
        self.assertTrue(recorded["created"])
        restarted = self.engine(lambda *_: self.fail("authority must not dispatch"),
                                jobs=[self.job(contract=contract)])
        authorized = restarted.authorize_reconciled_retry(
            attempt["attempt_id"], self.now + timedelta(seconds=3))
        self.assertEqual(authorized["status"], "retry_wait")
        binding = attempt["binding_sha256"]
        self.assertEqual(result.operation_id,
                         f"attempt/{attempt['attempt_id']}/prompt/{binding}")
        self.assertEqual(self.rows(restarted, "slots")[0]["binding_sha256"], binding)
        for table in ("provider_results", "retry_decisions", "reconciliation_records",
                      "reconciliation_consumptions"):
            rows = self.rows(restarted, table)
            self.assertTrue(rows, table)
            self.assertEqual({row["prompt_binding_sha256"] for row in rows}, {binding}, table)
        with self.assertRaisesRegex(EngineError, "UNKNOWN_SLOT_REQUIRED|ALREADY_CONSUMED"):
            restarted.authorize_reconciled_retry(
                attempt["attempt_id"], self.now + timedelta(seconds=4))
        self.assertEqual(len(self.rows(restarted, "reconciliation_consumptions")), 1)

    def test_proof_wrong_digest_cross_attempt_future_and_replacement_stay_unknown(self):
        captured = []
        contract = ReplayContractV1(ReplayEffect.RECONCILE_BEFORE_REPLAY,
                                    (Phase.CONNECTING,), "scope/typed", "adapter/one")
        engine = self.engine(lambda _job, context: captured.append(
            unknown_result(context["operation_id"])) or captured[-1], jobs=[self.job(contract=contract)])
        engine.tick(self.now)
        result = captured[0]
        attempt = self.rows(engine, "attempts")[0]
        evidence = b"absence"
        base = dict(attempt_id=attempt["attempt_id"], operation_id=result.operation_id,
                    slot_operation_scope=contract.slot_operation_scope,
                    provider_result_sha256=result.canonical_sha256, outcome="absent",
                    evidence_sha256=hashlib.sha256(evidence).hexdigest(), recorded_at=self.now)
        wrong = ReconciliationProofV1(**{**base, "evidence_sha256": "0" * 64})
        self.adapter.proof = wrong
        with self.assertRaisesRegex(EngineError, "EVIDENCE_MISMATCH"):
            engine.record_reconciliation_proof(wrong, evidence, "fixture://x", "adapter/one", "1", self.now, adapter=self.adapter)
        cross = ReconciliationProofV1(**{**base, "attempt_id": "other/attempt"})
        self.adapter.proof = cross
        with self.assertRaisesRegex(EngineError, "ATTEMPT_REQUIRED"):
            engine.record_reconciliation_proof(cross, evidence, "fixture://x", "adapter/one", "1", self.now, adapter=self.adapter)
        future = ReconciliationProofV1(**{**base, "recorded_at": self.now + timedelta(seconds=10)})
        self.adapter.proof = future
        with self.assertRaisesRegex(EngineError, "FUTURE_RECONCILIATION_PROOF"):
            engine.record_reconciliation_proof(future, evidence, "fixture://x", "adapter/one", "1", self.now, adapter=self.adapter)
        stale = ReconciliationProofV1(**{**base, "recorded_at": self.now - timedelta(seconds=1)})
        self.adapter.proof = stale
        with self.assertRaisesRegex(EngineError, "PREDATES_ATTEMPT"):
            engine.record_reconciliation_proof(stale, evidence, "fixture://x", "adapter/one", "1", self.now, adapter=self.adapter)
        valid = ReconciliationProofV1(**base)
        self.adapter.proof = valid
        engine.record_reconciliation_proof(
            valid, evidence, "fixture://x", "adapter/one", "1", self.now, adapter=self.adapter)
        conflict = ReconciliationProofV1(**{**base, "recorded_at": self.now + timedelta(seconds=1)})
        self.adapter.proof = conflict
        with self.assertRaisesRegex(EngineError, "RECONCILIATION_CONFLICT"):
            engine.record_reconciliation_proof(
                conflict, evidence, "fixture://x", "adapter/one", "1",
                self.now + timedelta(seconds=2), adapter=self.adapter)
        with engine._db() as db:
            db.execute("""INSERT INTO attempts(
                attempt_id,slot_id,attempt_no,started_at,ended_at,status,code,receipt,
                artifact_ref,sha256,length,version,source_identity_sha256,binding_sha256,
                generation,proof_origin)
                SELECT ?,slot_id,2,?,NULL,'unknown','TEST_REPLACEMENT',NULL,
                       artifact_ref,sha256,length,version,source_identity_sha256,binding_sha256,
                       generation,proof_origin
                FROM attempts WHERE attempt_id=?""",
                       ("replacement/attempt", (self.now + timedelta(seconds=2)).timestamp(),
                        attempt["attempt_id"]))
        with self.assertRaisesRegex(EngineError, "REPLACED_ATTEMPT"):
            engine.authorize_reconciled_retry(attempt["attempt_id"], self.now + timedelta(seconds=3))
        self.assertEqual(self.rows(engine, "slots")[0]["status"], "unknown")

    def test_concurrent_proof_consumption_has_one_winner(self):
        captured = []
        contract = ReplayContractV1(ReplayEffect.RECONCILE_BEFORE_REPLAY,
                                    (Phase.CONNECTING,), "scope/typed", "adapter/one")
        engine = self.engine(lambda _job, context: captured.append(
            unknown_result(context["operation_id"])) or captured[-1], jobs=[self.job(contract=contract)])
        engine.tick(self.now)
        result = captured[0]
        attempt = self.rows(engine, "attempts")[0]
        evidence = b"none"
        proof = ReconciliationProofV1(
            attempt["attempt_id"], result.operation_id, contract.slot_operation_scope,
            result.canonical_sha256, "absent", hashlib.sha256(evidence).hexdigest(), self.now)
        self.adapter.proof = proof
        engine.record_reconciliation_proof(
            proof, evidence, "fixture://x", "adapter/one", "1", self.now, adapter=self.adapter)
        outcomes = []
        barrier = threading.Barrier(2)
        def consume():
            barrier.wait()
            try:
                engine.authorize_reconciled_retry(attempt["attempt_id"], self.now + timedelta(seconds=1))
                outcomes.append("won")
            except EngineError:
                outcomes.append("lost")
        threads = [threading.Thread(target=consume) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertCountEqual(outcomes, ["won", "lost"])

    def test_shared_circuit_rejects_local_and_durable_config_conflicts(self):
        first_scope = {"profile": "shared", "resource_hash": "9" * 64,
                       "failure_threshold": 1, "open_seconds": 10, "probe_seconds": 5}
        second_scope = dict(first_scope); second_scope["open_seconds"] = 11
        with self.assertRaisesRegex(EngineError, "CIRCUIT_SCOPE_CONFIG_CONFLICT"):
            self.engine(lambda *_: None, jobs=[
                self.job(circuit=first_scope, job_id="first"),
                self.job(circuit=second_scope, job_id="second")])
        state = self.root / ".job-runtime" / "durable-circuit-conflict"
        first = self.engine(lambda _job, context: retry_result(context["operation_id"]),
                            jobs=[self.job(circuit=first_scope, job_id="first")], state=state)
        first.tick(self.now)
        second = self.engine(lambda _job, context: retry_result(context["operation_id"]),
                             jobs=[self.job(circuit=second_scope, job_id="second")], state=state)
        with self.assertRaisesRegex(EngineError, "CIRCUIT_SCOPE_CONFIG_DRIFT"):
            second.tick(self.now + timedelta(seconds=1))
        self.assertEqual(len(self.rows(second, "attempts")), 1)

    def test_circuit_open_isolated_half_open_probe_and_success_close(self):
        scope = {"profile": "primary", "resource_hash": "a" * 64,
                 "failure_threshold": 1, "open_seconds": 10, "probe_seconds": 5}
        calls = []
        def dispatch(_job, context):
            calls.append(context["attempt_id"])
            if len(calls) == 1:
                return retry_result(context["operation_id"])
            return ProviderResultV1(
                "claude_host", context["operation_id"], Phase.TERMINAL,
                Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
                ResultStatus.SUCCEEDED, "COMPLETED")
        engine = self.engine(dispatch, jobs=[self.job(circuit=scope)])
        self.assertEqual(engine.tick(self.now)["retry_wait"], 1)
        with engine._db() as db:
            db.execute("UPDATE slots SET next_attempt_at=? WHERE status='retry_wait'", ((self.now + timedelta(seconds=1)).timestamp(),))
        self.assertEqual(engine.tick(self.now + timedelta(seconds=1))["dispatched"], 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.rows(engine, "attempts")), 1)
        self.assertEqual(engine.tick(self.now + timedelta(seconds=11))["succeeded"], 1)
        circuit = self.rows(engine, "circuits")[0]
        self.assertEqual((circuit["state"], circuit["transient_failures"]), ("closed", 0))
        expected_scope = hashlib.sha256(
            ('{"profile":"primary","provider":"claude_host","resource_hash":"' + "a" * 64 + '"}').encode()
        ).hexdigest()
        self.assertEqual(circuit["scope_sha256"], expected_scope)
        self.assertNotIn("resource_key", circuit)

    def test_reconciliation_requires_registered_owner_capability(self):
        contract = ReplayContractV1(ReplayEffect.RECONCILE_BEFORE_REPLAY,
                                    (Phase.CONNECTING,), "scope/typed", "adapter/one")
        with self.assertRaisesRegex(EngineError, "ADAPTER_NOT_REGISTERED"):
            Engine(self.state, [self.job(contract=contract)], LEGACY_RETRY, lambda *_: None,
                   workspace_root=self.root, clock=lambda: self.now)
        captured = []
        engine = self.engine(lambda _job, context: captured.append(
            unknown_result(context["operation_id"])) or captured[-1], jobs=[self.job(contract=contract)])
        engine.tick(self.now)
        attempt = self.rows(engine, "attempts")[0]
        result = captured[0]
        evidence = b"owned-absence"
        proof = ReconciliationProofV1(
            attempt["attempt_id"], result.operation_id, contract.slot_operation_scope,
            result.canonical_sha256, "absent", hashlib.sha256(evidence).hexdigest(), self.now)
        self.adapter.proof = proof
        with self.assertRaisesRegex(EngineError, "CAPABILITY_REQUIRED"):
            engine.record_reconciliation_proof(
                proof, evidence, "fixture://x", "adapter/one", "1", self.now)
        impostor = OwnedAdapter(); impostor.proof = proof
        with self.assertRaisesRegex(EngineError, "CAPABILITY_REQUIRED"):
            engine.record_reconciliation_proof(
                proof, evidence, "fixture://x", "adapter/one", "1", self.now, adapter=impostor)
        self.assertEqual(self.rows(engine, "reconciliation_records"), [])

    def test_restart_rejects_pinned_policy_contract_and_circuit_drift(self):
        scope = {"profile": "primary", "resource_hash": "d" * 64,
                 "failure_threshold": 2, "open_seconds": 10, "probe_seconds": 5}
        mutations = []
        policy_job = self.job(circuit=scope, job_id="policy-drift")
        changed_policy = self.job(circuit=scope, job_id="policy-drift")
        changed_policy["_retry_policy"] = RetryPolicyV2(4, 2, 30, deadline_seconds=100)
        mutations.append((policy_job, changed_policy))
        contract_job = self.job(circuit=scope, job_id="contract-drift")
        changed_contract = self.job(circuit=scope, job_id="contract-drift")
        changed_contract["_replay_contract"] = ReplayContractV1(
            ReplayEffect.IDEMPOTENT, (Phase.CONNECTING,), "scope/changed")
        mutations.append((contract_job, changed_contract))
        circuit_job = self.job(circuit=scope, job_id="circuit-drift")
        changed_scope = dict(scope); changed_scope["open_seconds"] = 11
        mutations.append((circuit_job, self.job(circuit=changed_scope, job_id="circuit-drift")))
        for index, (original, changed) in enumerate(mutations):
            state = self.root / ".job-runtime" / f"drift-{index}"
            first = self.engine(lambda _job, context: retry_result(context["operation_id"]),
                                jobs=[original], state=state)
            self.assertEqual(first.tick(self.now)["retry_wait"], 1)
            with first._db() as db:
                db.execute("UPDATE slots SET next_attempt_at=?", ((self.now + timedelta(seconds=1)).timestamp(),))
            restarted = self.engine(lambda _job, context: retry_result(context["operation_id"]),
                                    jobs=[changed], state=state)
            with self.assertRaisesRegex(EngineError, "TYPED_SLOT_CONFIG_DRIFT"):
                restarted.tick(self.now + timedelta(seconds=1))
            self.assertEqual(len(self.rows(restarted, "attempts")), 1)

    def test_stale_operation_result_is_fenced_unknown(self):
        stale = ProviderResultV1(
            "claude_host", "stale/operation", Phase.TERMINAL,
            Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
            ResultStatus.SUCCEEDED, "COMPLETED")
        engine = self.engine(lambda *_: stale)
        self.assertEqual(engine.tick(self.now)["unknown"], 1)
        result = self.rows(engine, "provider_results")[0]
        self.assertEqual(json.loads(result["canonical_json"])["code"],
                         "PROVIDER_RESULT_BINDING_MISMATCH")
        self.assertNotEqual(result["operation_id"], stale.operation_id)

    def test_late_half_open_probe_cannot_close_new_owner(self):
        scope = {"profile": "shared", "resource_hash": "e" * 64,
                 "failure_threshold": 1, "open_seconds": 10, "probe_seconds": 5}
        jobs = [self.job(circuit=scope, job_id="probe-a"), self.job(circuit=scope, job_id="probe-b")]
        engine = self.engine(lambda *_: self.fail("manual finish"), jobs=jobs)
        with engine._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for configured in engine.jobs.values():
                engine._allocate(db, configured, self.now.timestamp())
            scope_sha = hashlib.sha256(
                ('{"profile":"shared","provider":"claude_host","resource_hash":"' + "e" * 64 + '"}').encode()
            ).hexdigest()
            db.execute("INSERT INTO circuits VALUES(?,?,?,?,?,0,'open',1,?,NULL,NULL,?)",
                       ("claude_host", "shared", "e" * 64, scope_sha,
                        circuit_config_sha(scope), self.now.timestamp(), self.now.timestamp()))
        probe_a = engine._claim(engine.jobs["probe-a"], (self.now + timedelta(seconds=1)).timestamp())
        self.assertIsNotNone(probe_a["_probe_token"])
        probe_b = engine._claim(engine.jobs["probe-b"], (self.now + timedelta(seconds=7)).timestamp())
        self.assertIsNotNone(probe_b["_probe_token"])
        success_a = ProviderResultV1(
            "claude_host", probe_a["operation_id"], Phase.TERMINAL,
            Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
            ResultStatus.SUCCEEDED, "COMPLETED")
        engine._finish(engine.jobs["probe-a"], probe_a, success_a,
                       (self.now + timedelta(seconds=8)).timestamp())
        circuit = self.rows(engine, "circuits")[0]
        self.assertEqual((circuit["state"], circuit["probe_owner"]),
                         ("half_open", probe_b["_probe_token"]))
        success_b = ProviderResultV1(
            "claude_host", probe_b["operation_id"], Phase.TERMINAL,
            Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
            ResultStatus.SUCCEEDED, "COMPLETED")
        engine._finish(engine.jobs["probe-b"], probe_b, success_b,
                       (self.now + timedelta(seconds=9)).timestamp())
        self.assertEqual(self.rows(engine, "circuits")[0]["state"], "closed")

    def test_circuit_generation_fences_old_closed_epoch_results(self):
        scope = {"profile": "generation", "resource_hash": "7" * 64,
                 "failure_threshold": 1, "open_seconds": 10, "probe_seconds": 5}
        ids = ("open-a", "old-success", "half-open", "old-transient", "old-permanent", "old-unknown")
        jobs = [self.job(circuit=scope, job_id=job_id) for job_id in ids]
        engine = self.engine(lambda *_: self.fail("manual finish"), jobs=jobs)
        with engine._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for configured in engine.jobs.values(): engine._allocate(db, configured, self.now.timestamp())
        old = {job_id: engine._claim(engine.jobs[job_id], self.now.timestamp())
               for job_id in ids if job_id != "half-open"}
        self.assertTrue(all(context["_circuit_generation"] == 0 for context in old.values()))
        engine._finish(engine.jobs["open-a"], old["open-a"],
                       retry_result(old["open-a"]["operation_id"]),
                       (self.now + timedelta(seconds=1)).timestamp())
        opened = self.rows(engine, "circuits")[0]
        self.assertEqual((opened["state"], opened["generation"]), ("open", 1))
        stale_success = ProviderResultV1(
            "claude_host", old["old-success"]["operation_id"], Phase.TERMINAL,
            Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
            ResultStatus.SUCCEEDED, "COMPLETED")
        engine._finish(engine.jobs["old-success"], old["old-success"], stale_success,
                       (self.now + timedelta(seconds=2)).timestamp())
        self.assertEqual((self.rows(engine, "circuits")[0]["state"],
                          self.rows(engine, "circuits")[0]["generation"]), ("open", 1))

        probe = engine._claim(engine.jobs["half-open"],
                              (self.now + timedelta(seconds=12)).timestamp())
        self.assertEqual((probe["_circuit_admission_state"], probe["_circuit_generation"]),
                         ("half_open", 2))
        probe_success = ProviderResultV1(
            "claude_host", probe["operation_id"], Phase.TERMINAL,
            Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
            ResultStatus.SUCCEEDED, "COMPLETED")
        engine._finish(engine.jobs["half-open"], probe, probe_success,
                       (self.now + timedelta(seconds=13)).timestamp())
        closed = self.rows(engine, "circuits")[0]
        self.assertEqual((closed["state"], closed["generation"], closed["transient_failures"]),
                         ("closed", 3, 0))
        engine._finish(engine.jobs["old-transient"], old["old-transient"],
                       retry_result(old["old-transient"]["operation_id"]),
                       (self.now + timedelta(seconds=14)).timestamp())
        stale_permanent = ProviderResultV1(
            "claude_host", old["old-permanent"]["operation_id"], Phase.TERMINAL,
            Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
            ResultStatus.FAILED, "AUTH_REJECTED", failure_kind=FailureKind.AUTH)
        engine._finish(engine.jobs["old-permanent"], old["old-permanent"], stale_permanent,
                       (self.now + timedelta(seconds=15)).timestamp())
        engine._finish(engine.jobs["old-unknown"], old["old-unknown"],
                       unknown_result(old["old-unknown"]["operation_id"]),
                       (self.now + timedelta(seconds=16)).timestamp())
        final = self.rows(engine, "circuits")[0]
        self.assertEqual((final["state"], final["generation"], final["transient_failures"]),
                         ("closed", 3, 0))

        same_scope = dict(scope)
        same_scope["resource_hash"] = "8" * 64
        same_scope["failure_threshold"] = 3
        same_jobs = [self.job(circuit=same_scope, job_id="same-transient"),
                     self.job(circuit=same_scope, job_id="same-success")]
        same = self.engine(lambda *_: self.fail("manual finish"), jobs=same_jobs,
                           state=self.root / ".job-runtime" / "same-generation")
        with same._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for configured in same.jobs.values(): same._allocate(db, configured, self.now.timestamp())
        transient_context = same._claim(same.jobs["same-transient"], self.now.timestamp())
        success_context = same._claim(same.jobs["same-success"], self.now.timestamp())
        same._finish(same.jobs["same-transient"], transient_context,
                     retry_result(transient_context["operation_id"]),
                     (self.now + timedelta(seconds=1)).timestamp())
        mid = self.rows(same, "circuits")[0]
        self.assertEqual((mid["state"], mid["generation"], mid["transient_failures"]),
                         ("closed", 0, 1))
        same_success = ProviderResultV1(
            "claude_host", success_context["operation_id"], Phase.TERMINAL,
            Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
            ResultStatus.SUCCEEDED, "COMPLETED")
        same._finish(same.jobs["same-success"], success_context, same_success,
                     (self.now + timedelta(seconds=2)).timestamp())
        reset = self.rows(same, "circuits")[0]
        self.assertEqual((reset["state"], reset["generation"], reset["transient_failures"]),
                         ("closed", 0, 0))

    def test_half_open_unknown_reopens_and_permanent_closes(self):
        scope = {"profile": "shared", "resource_hash": "f" * 64,
                 "failure_threshold": 1, "open_seconds": 10, "probe_seconds": 5}
        jobs = [self.job(circuit=scope, job_id="unknown-probe"),
                self.job(circuit=scope, job_id="permanent-probe")]
        engine = self.engine(lambda *_: self.fail("manual finish"), jobs=jobs)
        with engine._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for configured in engine.jobs.values(): engine._allocate(db, configured, self.now.timestamp())
            scope_sha = hashlib.sha256(
                ('{"profile":"shared","provider":"claude_host","resource_hash":"' + "f" * 64 + '"}').encode()
            ).hexdigest()
            db.execute("INSERT INTO circuits VALUES(?,?,?,?,?,0,'open',1,?,NULL,NULL,?)",
                       ("claude_host", "shared", "f" * 64, scope_sha,
                        circuit_config_sha(scope), self.now.timestamp(), self.now.timestamp()))
        unknown_context = engine._claim(engine.jobs["unknown-probe"], (self.now + timedelta(seconds=1)).timestamp())
        engine._finish(engine.jobs["unknown-probe"], unknown_context,
                       unknown_result(unknown_context["operation_id"]),
                       (self.now + timedelta(seconds=2)).timestamp())
        circuit = self.rows(engine, "circuits")[0]
        self.assertEqual(circuit["state"], "open")
        failures = circuit["transient_failures"]
        permanent_context = engine._claim(
            engine.jobs["permanent-probe"], (self.now + timedelta(seconds=13)).timestamp())
        permanent = ProviderResultV1(
            "claude_host", permanent_context["operation_id"], Phase.TERMINAL,
            Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
            ResultStatus.FAILED, "AUTH_REJECTED", failure_kind=FailureKind.AUTH)
        engine._finish(engine.jobs["permanent-probe"], permanent_context, permanent,
                       (self.now + timedelta(seconds=14)).timestamp())
        circuit = self.rows(engine, "circuits")[0]
        self.assertEqual((circuit["state"], circuit["transient_failures"]), ("closed", 0))
        self.assertGreaterEqual(failures, 1)

    def test_open_circuit_does_not_block_unrelated_scope_or_consume_attempt(self):
        blocked_scope = {"profile": "blocked", "resource_hash": "1" * 64,
                         "failure_threshold": 1, "open_seconds": 30, "probe_seconds": 5}
        free_scope = {"profile": "free", "resource_hash": "2" * 64,
                      "failure_threshold": 1, "open_seconds": 30, "probe_seconds": 5}
        jobs = [self.job(circuit=blocked_scope, job_id="blocked-job"),
                self.job(circuit=free_scope, job_id="free-job")]
        calls = []
        def success(_job, context):
            calls.append(context["slot_id"])
            return ProviderResultV1(
                "claude_host", context["operation_id"], Phase.TERMINAL,
                Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
                ResultStatus.SUCCEEDED, "COMPLETED")
        engine = self.engine(success, jobs=jobs)
        with engine._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for configured in engine.jobs.values(): engine._allocate(db, configured, self.now.timestamp())
            scope_sha = hashlib.sha256(
                ('{"profile":"blocked","provider":"claude_host","resource_hash":"' + "1" * 64 + '"}').encode()
            ).hexdigest()
            db.execute("INSERT INTO circuits VALUES(?,?,?,?,?,0,'open',1,?,NULL,NULL,?)",
                       ("claude_host", "blocked", "1" * 64, scope_sha,
                        circuit_config_sha(blocked_scope),
                        (self.now + timedelta(seconds=30)).timestamp(), self.now.timestamp()))
        summary = engine.tick(self.now)
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(len(calls), 1)
        attempts = self.rows(engine, "attempts")
        self.assertEqual(len(attempts), 1)
        free_slot = next(row for row in self.rows(engine, "slots") if row["job_id"] == "free-job")
        self.assertEqual(attempts[0]["slot_id"], free_slot["slot_id"])

    def test_attempt_lifecycle_triggers_allow_only_owned_transitions(self):
        success_state = self.root / ".job-runtime" / "attempt-success"
        success_engine = self.engine(
            lambda _job, context: ProviderResultV1(
                "claude_host", context["operation_id"], Phase.TERMINAL,
                Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
                ResultStatus.SUCCEEDED, "COMPLETED"), state=success_state)
        self.assertEqual(success_engine.tick(self.now)["succeeded"], 1)
        succeeded = self.rows(success_engine, "attempts")[0]
        original = tuple(succeeded.values())
        with success_engine._db() as db:
            for statement in (
                    "UPDATE attempts SET code='MUTATED' WHERE attempt_id=?",
                    "UPDATE attempts SET receipt='{}' WHERE attempt_id=?",
                    "UPDATE attempts SET ended_at=ended_at+1 WHERE attempt_id=?",
                    "UPDATE attempts SET status='failed' WHERE attempt_id=?",
                    "DELETE FROM attempts WHERE attempt_id=?"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement, (succeeded["attempt_id"],))
        self.assertEqual(tuple(self.rows(success_engine, "attempts")[0].values()), original)

        recovery_state = self.root / ".job-runtime" / "attempt-recovery"
        recovery = self.engine(lambda *_: self.fail("manual claim"), state=recovery_state)
        with recovery._db() as db:
            db.execute("BEGIN IMMEDIATE")
            recovery._allocate(db, recovery.jobs["typed-job"], self.now.timestamp())
        context = recovery._claim("typed-job", self.now.timestamp())
        with recovery._db() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("""UPDATE attempts SET slot_id='cross-slot',status='failed',
                            code='CROSS_UPDATE',ended_at=? WHERE attempt_id=?""",
                           ((self.now + timedelta(seconds=1)).timestamp(), context["attempt_id"]))
        self.assertEqual(recovery.recover_running(self.now + timedelta(seconds=1)), 1)
        recovered = self.rows(recovery, "attempts")[0]
        self.assertEqual(recovered["status"], "unknown")
        receipt = {"operator_evidence": "synthetic"}
        recovery.resolve_unknown(context["slot_id"], "succeeded", receipt,
                                 self.now + timedelta(seconds=2))
        reconciled = self.rows(recovery, "attempts")[0]
        self.assertEqual((reconciled["status"], reconciled["code"]),
                         ("succeeded", "OPERATOR_RECONCILED"))
        self.assertEqual(json.loads(reconciled["receipt"]), receipt)
        with self.assertRaisesRegex(EngineError, "UNKNOWN_SLOT_REQUIRED"):
            recovery.resolve_unknown(context["slot_id"], "failed", receipt,
                                     self.now + timedelta(seconds=3))
        with recovery._db() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE attempts SET code='SECOND_RECONCILIATION' WHERE attempt_id=?",
                           (context["attempt_id"],))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM attempts WHERE attempt_id=?", (context["attempt_id"],))

    def test_dispatch_exception_is_typed_unknown_and_process_recovery_fences(self):
        engine = self.engine(lambda *_: (_ for _ in ()).throw(RuntimeError("secret text")))
        self.assertEqual(engine.tick(self.now)["unknown"], 1)
        result = self.rows(engine, "provider_results")[0]
        self.assertEqual(result["status"], "unknown")
        self.assertNotIn("secret", result["canonical_json"])

        state = self.root / ".job-runtime" / "recovery"
        other = self.engine(lambda *_: retry_result(), state=state)
        with other._db() as db:
            db.execute("BEGIN IMMEDIATE")
            other._allocate(db, other.jobs["typed-job"], self.now.timestamp())
        claim = other._claim("typed-job", self.now.timestamp())
        self.assertIsNotNone(claim)
        self.assertEqual(other.recover_running(self.now + timedelta(seconds=1)), 1)
        self.assertEqual(self.rows(other, "slots")[0]["status"], "unknown")

    def test_provider_output_custody_is_metadata_only_and_single_transition(self):
        engine = self.engine(lambda *_: self.fail("manual claim"))
        with engine._db() as db:
            db.execute("BEGIN IMMEDIATE")
            engine._allocate(db, engine.jobs["typed-job"], self.now.timestamp())
        context = engine._claim("typed-job", self.now.timestamp())
        started = engine.begin_provider_output_custody(context["attempt_id"], self.now)
        self.assertTrue(started["created"])
        self.assertFalse(engine.begin_provider_output_custody(
            context["attempt_id"], self.now)["created"])
        sealed = engine.finish_provider_output_custody(
            context["attempt_id"], "complete", 2, 17, "OUTPUT_VERIFIED",
            self.now + timedelta(seconds=1))
        self.assertEqual((sealed["state"], sealed["output_count"], sealed["output_bytes"]),
                         ("complete", 2, 17))
        stored = engine.provider_output_custody(context["attempt_id"])
        self.assertEqual(stored["code"], "OUTPUT_VERIFIED")
        self.assertNotIn("output", set(stored) - {"output_count", "output_bytes"})
        with self.assertRaisesRegex(EngineError, "PENDING_REQUIRED"):
            engine.finish_provider_output_custody(
                context["attempt_id"], "failed", 0, 0, "SECOND", self.now)
        with engine._db() as db, self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM provider_output_custody WHERE attempt_id=?",
                       (context["attempt_id"],))

    def test_existing_schema_requires_side_file_migration_without_byte_changes(self):
        self.state.mkdir(parents=True)
        path = write_v0_fixture(self.state / "schedule.sqlite")
        before = path.read_bytes()
        self.assertEqual(hashlib.sha256(_V0_CANONICAL).hexdigest(), _V0_CANONICAL_SHA256)

        with self.assertRaisesRegex(EngineError, "DATABASE_SIDEFILE_MIGRATION_REQUIRED"):
            self.engine(lambda *_: self.fail("legacy schema must not dispatch"))

        self.assertEqual(path.read_bytes(), before)
        db = sqlite3.connect(path)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertNotIn(
            "artifact_ref", {row[1] for row in db.execute("PRAGMA table_info(slots)")})
        self.assertEqual(
            db.execute("SELECT receipt FROM attempts WHERE attempt_id='old-attempt'").fetchone()[0],
            _V0_RECEIPT)

    def test_migration_statement_failure_rolls_back_additions(self):
        class FailingEngine(Engine):
            calls = 0
            def _migration_execute(self, db, statement):
                self.calls += 1
                if self.calls == 3:
                    raise sqlite3.OperationalError("injected")
                return super()._migration_execute(db, statement)
        with self.assertRaises(sqlite3.OperationalError):
            self.engine(lambda *_: retry_result(), cls=FailingEngine)
        db = sqlite3.connect(self.state / "schedule.sqlite")
        self.addCleanup(db.close)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
        columns = {row[1] for row in db.execute("PRAGMA table_info(slots)")}
        self.assertNotIn("provider", columns)
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='slots'").fetchone())


if __name__ == "__main__":
    unittest.main()
