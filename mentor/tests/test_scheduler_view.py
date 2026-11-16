"""Fixed-provider tests for the read-only mentor scheduler projection."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from mentor.scheduler.contracts import WorkOrder
from mentor.scheduler.state import DurableSessionStore
from mentor.scheduler import scheduler_view as view
from mentor.scheduler import state as scheduler_state


class MentorSchedulerViewTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[2] / "ui/runtime/scheduler-20261103/tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.at = datetime(2026, 11, 5, 2, tzinfo=timezone.utc)
        self.owner = "mentor-fixture"
        self.job_id = "mentor.scheduler.fixture"
        base = self.root / ".job-runtime/acceptance" / self.owner
        scheduled = base / "scheduled"
        scheduled.mkdir(parents=True, mode=0o700)
        plan = scheduled / "plan.md"
        acceptance = scheduled / "acceptance.json"
        plan.write_text("SYNTHETIC_PRIVATE_PROMPT", encoding="utf-8")
        acceptance.write_text(json.dumps({"schema_version": 1, "criteria": [{"criterion_id": "gate", "critical": True}]}), encoding="utf-8")
        for path in (plan, acceptance):
            path.chmod(0o600)
        self.work_order_path = scheduled / "work-order.json"
        order_data = {
            "schema_version": 1,
            "work_order_id": self.owner,
            "logical_session": {"logical_session_id": self.owner, "provider_thread_mode": "ephemeral_threads", "max_provider_threads": 2},
            "plan": {"path": str(plan.relative_to(self.root)), "sha256": hashlib.sha256(plan.read_bytes()).hexdigest()},
            "acceptance": {"path": str(acceptance.relative_to(self.root)), "sha256": hashlib.sha256(acceptance.read_bytes()).hexdigest()},
            "execution": {"starts_at": "2026-11-05T01:00:00+00:00", "ends_at": "2026-11-05T01:10:00+00:00", "turn_timeout_seconds": 60, "max_turns": 2},
            "supervision": {"max_no_progress_cycles": 2, "max_repeated_actions": 2, "max_interventions": 0},
            "evidence_policy": {"record_all_variants": True, "max_variants": 1, "max_reused_evaluations": 0, "worker_holdout_access": False},
            "completion": {"required_event_kinds": ["provider_thread", "cycle"], "require_no_pending_effects": True, "require_acceptance_hash_match": True},
        }
        self.work_order_path.write_text(json.dumps(order_data), encoding="utf-8")
        self.work_order_path.chmod(0o600)
        order = WorkOrder.from_json(self.work_order_path.read_text(), self.root)
        self.state_directory = f".job-runtime/mentor-sessions/{self.owner}"
        DurableSessionStore(self.root, self.state_directory, self.owner).create(order, at=datetime(2026, 11, 5, 1, tzinfo=timezone.utc))
        (base / "candidate-manifest.json").write_text("{}", encoding="utf-8")
        (base / "candidate-manifest.json").chmod(0o600)
        self.record_path = base / "record.json"
        engine = self.root / ".job-runtime/engine/schedule.sqlite"
        engine.parent.mkdir(parents=True, mode=0o700)
        with sqlite3.connect(engine) as db:
            db.execute("CREATE TABLE slots(slot_id TEXT,job_id TEXT,scheduled_at REAL,status TEXT,attempts INTEGER,next_attempt_at REAL,code TEXT,updated_at REAL)")
            db.execute("CREATE TABLE attempts(attempt_id TEXT,slot_id TEXT,attempt_no INTEGER)")
            db.execute("INSERT INTO slots VALUES(?,?,?,?,?,?,?,?)", (
                "slot-current", self.job_id, self.at.timestamp(), "failed", 1, None,
                "OPERATOR_RECONCILED", self.at.timestamp(),
            ))
            db.execute("INSERT INTO attempts VALUES(?,?,?)", ("attempt-1", "slot-current", 1))
        engine.chmod(0o600)
        self.write_record()
        self.job = {
            "id": self.job_id,
            "adapter": "mentor.scheduler.job_adapter:prepare",
            "replay_safe": True,
            "adapter_config": {
                "candidate_manifest_path": str((base / "candidate-manifest.json").relative_to(self.root)),
                "candidate_manifest_sha256": "0" * 64,
                "expected_model_profile": "default",
                "model_profile_sha256": "1" * 64,
                "owner_id": self.owner,
                "required_source_paths": ["mentor/scheduler/contracts.py"],
                "state_directory": self.state_directory,
                "verifier_kind": "synthetic_bindings_v1",
                "work_order_path": str(self.work_order_path.relative_to(self.root)),
            },
        }

    def write_record(self, *, job_id=None, acceptance="failed", execution_status="failed",
                     email="pending", dispatch="definitely_not_dispatched", reconciliations=None,
                     turn_completed=False, postconditions=None):
        if reconciliations is None:
            with sqlite3.connect(self.root / ".job-runtime/engine/schedule.sqlite") as db:
                latest = db.execute(
                    "SELECT attempt_id FROM attempts WHERE slot_id='slot-current' "
                    "ORDER BY attempt_no DESC LIMIT 1"
                ).fetchone()
            attempt_id = latest[0] if latest is not None else "attempt-1"
            reconciliations = [{"classification": dispatch, "attempt_id": attempt_id,
                                "outcome": "succeeded" if dispatch == "dispatched" else "failed",
                                "verified_at": "2026-11-05T02:00:04+00:00"}]
        value = {
            "record_version": 1,
            "owner": "mentor-scheduler",
            "change_id": self.owner,
            "acceptance": acceptance,
            "email_sync": {"status": email, "recipient": "SYNTHETIC_PRIVATE_RECIPIENT"},
            "execution": {"status": execution_status, "job_id": job_id or self.job_id,
                          "scheduled_at": "2026-11-05T02:00:00+00:00",
                          "started_at": "2026-11-05T02:00:01+00:00",
                          "completed_at": "2026-11-05T02:00:03+00:00",
                          "turn_completed": turn_completed,
                          "postconditions": postconditions or [], "partial_coverage": [],
                          "codex_thread_id": None, "reconciliations": reconciliations},
        }
        self.record_path.write_text(json.dumps(value), encoding="utf-8")
        self.record_path.chmod(0o600)

    def set_engine(self, status, code, attempts=1, *, next_attempt=None):
        if status == "retry_wait" and next_attempt is None:
            next_attempt = self.at + timedelta(minutes=1)
        rendered_next = next_attempt.timestamp() if next_attempt is not None else None
        with sqlite3.connect(self.root / ".job-runtime/engine/schedule.sqlite") as db:
            db.execute(
                "UPDATE slots SET status=?,code=?,attempts=?,next_attempt_at=? WHERE job_id=?",
                (status, code, attempts, rendered_next, self.job_id),
            )
            db.execute("DELETE FROM attempts WHERE slot_id='slot-current'")
            for number in range(1, attempts + 1):
                db.execute("INSERT INTO attempts VALUES(?,?,?)", (
                    f"attempt-{number}", "slot-current", number,
                ))

    def insert_slot(self, status, *, scheduled, updated, attempts=0, code="DUE"):
        with sqlite3.connect(self.root / ".job-runtime/engine/schedule.sqlite") as db:
            db.execute("INSERT INTO slots VALUES(?,?,?,?,?,?,?,?)", (
                f"slot-{scheduled.timestamp()}", self.job_id, scheduled.timestamp(), status,
                attempts, None, code, updated.timestamp(),
            ))

    def set_limits(self, *, max_turns=4, max_no_progress=4, max_repeated=4):
        value = json.loads(self.work_order_path.read_text())
        value["execution"]["max_turns"] = max_turns
        value["supervision"]["max_no_progress_cycles"] = max_no_progress
        value["supervision"]["max_repeated_actions"] = max_repeated
        self.work_order_path.write_text(json.dumps(value), encoding="utf-8")
        self.work_order_path.chmod(0o600)

    def progress_artifact(self, order, cycle_id):
        evidence = self.work_order_path.parent / f"{cycle_id}-evidence.txt"
        evidence.write_text("synthetic verified evidence\n", encoding="utf-8")
        evidence.chmod(0o600)
        artifact = self.work_order_path.parent / f"{cycle_id}-progress.json"
        artifact.write_text(json.dumps({
            "schema_version": 1,
            "work_order_id": order.work_order_id,
            "plan_sha256": order.plan.sha256,
            "acceptance_sha256": order.acceptance.sha256,
            "cycle_id": cycle_id,
            "observations": [{
                "evidence_id": f"evidence-{cycle_id}",
                "evidence_path": str(evidence.relative_to(self.root)),
                "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            }],
        }), encoding="utf-8")
        artifact.chmod(0o600)
        return str(artifact.relative_to(self.root))

    def expected_resilience(self, **changes):
        value = {
            "generated_at": self.at.isoformat(),
            "status": "partial",
            "projection_state": "current",
            "scheduler": {"status": "failed", "attempts": 1},
            "provider_safety": {
                "latest_attempt": None, "delayed_until": None, "delay_source": None,
                "unknown_fence": False, "replay_authorization": "not_applicable",
            },
            "mentor": {
                "cycles": 0,
                "no_progress": {"used": 0, "limit": 2},
                "repeated": {"used": 0, "limit": 2},
                "evidence_reset": False,
            },
            "health": {"heartbeat_age_seconds": None, "watchdog_healthy": None},
        }
        value.update(changes)
        return value

    def complete_session(self):
        order = WorkOrder.from_json(self.work_order_path.read_text(), self.root)
        store = DurableSessionStore(self.root, self.state_directory, self.owner)
        store.record_provider_thread(order, provider="synthetic", thread_id="private-thread",
                                     at=datetime(2026, 11, 5, 1, 1, tzinfo=timezone.utc))
        store.record_cycle(order, cycle_id="cycle-1", variant_id="variant-1", action_sha256="a" * 64,
                           outcome="succeeded", verified_evidence_artifact_path=None,
                           at=datetime(2026, 11, 5, 1, 2, tzinfo=timezone.utc))
        evidence = self.work_order_path.parent / "gate-evidence.txt"
        evidence.write_text("synthetic verifier evidence\n", encoding="utf-8")
        evidence.chmod(0o600)
        candidate_source = self.work_order_path.parent / "candidate-source.txt"
        candidate_source.write_text("synthetic candidate source\n", encoding="utf-8")
        candidate_source.chmod(0o600)
        artifact = self.work_order_path.parent / "criterion-observations.json"
        artifact.write_text(json.dumps({
            "schema_version": 1, "artifact_kind": "criterion_observations",
            "producer_role": "verifier", "verifier_id": "fixture-verifier",
            "work_order_id": self.owner, "plan_sha256": order.plan.sha256,
            "acceptance_sha256": order.acceptance.sha256,
            "cycle_id": "cycle-1", "candidate_id": "variant-1",
            "candidate_source": {
                "path": str(candidate_source.relative_to(self.root)),
                "sha256": hashlib.sha256(candidate_source.read_bytes()).hexdigest(),
            },
            "observations": [{"criterion_id": "gate", "verdict": "satisfied", "evidence": [{
                "path": str(evidence.relative_to(self.root)),
                "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            }]}],
        }), encoding="utf-8")
        artifact.chmod(0o600)
        observed = store._record_criterion_observation_from_verifier(
            order, artifact_path=str(artifact.relative_to(self.root)), cycle_id="cycle-1",
            candidate_id="variant-1", at=datetime(2026, 11, 5, 1, 3, tzinfo=timezone.utc),
            capability=scheduler_state._VERIFIER_CAPABILITY,
        )
        store.complete_verified(
            order, candidate_id="variant-1", cycle_id="cycle-1",
            criterion_artifact_sha256=observed["criterion_observations"][0]["sha256"],
            at=datetime(2026, 11, 5, 1, 4, tzinfo=timezone.utc),
        )

    def describe(self, *, at=None, **changes):
        job = {**self.job, **changes}
        return view.describe(self.root, job, at or self.at, next_tick=lambda *_: None, detail=True)

    def test_current_truth_is_exact_bounded_and_contains_no_private_evidence(self):
        result = self.describe()
        self.assertEqual(result["job_type"], "mentor")
        mentor = result["mentor"]
        parity_fixture = json.loads((Path(__file__).resolve().parents[2] / "ui/datasource/src/scheduler-resilience-mvp/pythonProjectionFixture.json").read_text())
        self.assertEqual(mentor["resilience"], parity_fixture)
        self.assertEqual(set(mentor), {
            "work_order", "scheduler", "session", "progress", "safeguards", "gates",
            "evaluation", "runtime_acceptance", "recovery_timeline", "resilience",
        })
        self.assertEqual(mentor, {
            "work_order": {
                "id": self.owner, "logical_session_id": self.owner,
                "starts_at": "2026-11-05T01:00:00+00:00", "ends_at": "2026-11-05T01:10:00+00:00",
                "window_state": "expired", "acceptance_criteria_total": 1,
                "required_event_kinds": ["provider_thread", "cycle"],
            },
            "scheduler": {"status": "failed", "code": "OPERATOR_RECONCILED", "attempts": 1,
                          "dispatch": "definitely_not_dispatched"},
            "session": {"status": "active", "revision": 0},
            "progress": {
                "cycles": {"used": 0, "limit": 2}, "provider_threads": {"used": 0, "limit": 2},
                "variants": {"used": 0, "limit": 1}, "interventions": {"used": 0, "limit": 0},
                "reused_evaluations": {"used": 0, "limit": 0}, "pending_effects": 0,
            },
            "safeguards": {
                "provider_thread_mode": "ephemeral_threads", "record_all_variants": True,
                "worker_holdout_access": False, "require_no_pending_effects": True,
                "configured_replay_safe": True, "replay_authorization": "not_authorized",
            },
            "gates": {
                "future_wake": "verified", "profile_binding": "not_verified",
                "stop_propagation": "not_verified", "model_turn": "failed",
                "journal_cycle_postcondition": "not_verified", "no_duplicate_dispatch": "verified",
            },
            "evaluation": {"attempt_ledger_preserved": True, "baseline": "pending",
                           "ablation": "not_required", "holdout": "unverified", "promotion": "inconclusive"},
            "runtime_acceptance": {"execution": "failed", "acceptance": "failed",
                                   "model_turn": "not_started", "email": "pending"},
            "recovery_timeline": [
                {"event": "scheduled", "status": "recorded", "at": "2026-11-05T02:00:00+00:00"},
                {"event": "attempt_started", "status": "recorded", "at": "2026-11-05T02:00:01+00:00"},
                {"event": "dispatch_failed", "status": "failed", "at": "2026-11-05T02:00:03+00:00"},
                {"event": "operator_reconciled", "status": "resolved", "at": "2026-11-05T02:00:04+00:00"},
            ],
            "resilience": self.expected_resilience(),
        })
        body = json.dumps(result)
        for private in ("SYNTHETIC_PRIVATE_PROMPT", "SYNTHETIC_PRIVATE_RECIPIENT", "SYNTHETIC_PRIVATE_ID", str(self.root), "sha256"):
            self.assertNotIn(private, body)
        self.assertEqual(result["outputs"], [])

    def test_resilience_no_progress_threshold_uses_durable_head(self):
        self.set_limits(max_no_progress=2, max_repeated=4)
        order = WorkOrder.from_json(self.work_order_path.read_text(), self.root)
        store = DurableSessionStore(self.root, self.state_directory, self.owner)
        store.record_cycle(order, cycle_id="cycle-1", variant_id="variant-1", action_sha256="a" * 64,
                           outcome="failed", verified_evidence_artifact_path=None,
                           at=datetime(2026, 11, 5, 1, 1, tzinfo=timezone.utc))
        store.record_cycle(order, cycle_id="cycle-2", variant_id="variant-1", action_sha256="b" * 64,
                           outcome="failed", verified_evidence_artifact_path=None,
                           at=datetime(2026, 11, 5, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(self.describe()["mentor"]["resilience"]["mentor"], {
            "cycles": 2,
            "no_progress": {"used": 2, "limit": 2},
            "repeated": {"used": 0, "limit": 4},
            "evidence_reset": False,
        })

    def test_resilience_repeated_threshold_uses_durable_head(self):
        self.set_limits(max_no_progress=4, max_repeated=1)
        order = WorkOrder.from_json(self.work_order_path.read_text(), self.root)
        store = DurableSessionStore(self.root, self.state_directory, self.owner)
        for number in (1, 2):
            store.record_cycle(
                order, cycle_id=f"cycle-{number}", variant_id="variant-1",
                action_sha256="a" * 64, outcome="failed",
                verified_evidence_artifact_path=None,
                at=datetime(2026, 11, 5, 1, number, tzinfo=timezone.utc),
            )
        self.assertEqual(self.describe()["mentor"]["resilience"]["mentor"], {
            "cycles": 2,
            "no_progress": {"used": 2, "limit": 4},
            "repeated": {"used": 1, "limit": 1},
            "evidence_reset": False,
        })

    def test_resilience_verified_last_cycle_resets_loop(self):
        self.set_limits(max_no_progress=4, max_repeated=4)
        order = WorkOrder.from_json(self.work_order_path.read_text(), self.root)
        store = DurableSessionStore(self.root, self.state_directory, self.owner)
        store.record_cycle(order, cycle_id="cycle-1", variant_id="variant-1", action_sha256="a" * 64,
                           outcome="failed", verified_evidence_artifact_path=None,
                           at=datetime(2026, 11, 5, 1, 1, tzinfo=timezone.utc))
        store.record_cycle(
            order, cycle_id="cycle-2", variant_id="variant-1", action_sha256="a" * 64,
            outcome="succeeded", verified_evidence_artifact_path=self.progress_artifact(order, "cycle-2"),
            at=datetime(2026, 11, 5, 1, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(self.describe()["mentor"]["resilience"]["mentor"], {
            "cycles": 2,
            "no_progress": {"used": 0, "limit": 4},
            "repeated": {"used": 0, "limit": 4},
            "evidence_reset": True,
        })

    def test_resilience_catch_up_uses_only_latest_two_sequence_slots(self):
        older = self.at - timedelta(minutes=1)
        self.insert_slot("missed", scheduled=older, updated=older)
        self.insert_slot("coalesced", scheduled=older - timedelta(minutes=1),
                         updated=older - timedelta(minutes=1))
        wire = self.describe()["mentor"]["resilience"]
        self.assertEqual(wire, self.expected_resilience())
        for private_preflight_key in (
            "schema_version", "state", "reason", "observed_at", "snapshot",
            "provider", "recovery", "host", "catch_up", "loop",
        ):
            self.assertNotIn(private_preflight_key, wire)
        with sqlite3.connect(self.root / ".job-runtime/engine/schedule.sqlite") as db:
            db.execute("UPDATE slots SET status='coalesced' WHERE scheduled_at=?", (older.timestamp(),))
        self.assertEqual(self.describe()["mentor"]["resilience"], self.expected_resilience())

    def test_resilience_health_is_null_when_host_facts_are_not_recorded(self):
        self.assertEqual(self.describe()["mentor"]["resilience"]["health"], {
            "heartbeat_age_seconds": None, "watchdog_healthy": None,
        })

    def test_resilience_retry_unknown_and_reconcile_are_fail_safe(self):
        self.set_engine("ready", "MENTOR_JOB_CYCLE_BLOCKED", attempts=0)
        self.write_record(acceptance="unverified", execution_status="pending",
                          reconciliations=[])
        ready = self.describe()["mentor"]["resilience"]
        self.assertEqual(ready["scheduler"], {"status": "ready", "attempts": 0})
        self.assertEqual(ready["provider_safety"], {
            "latest_attempt": None, "delayed_until": None, "delay_source": None,
            "unknown_fence": False, "replay_authorization": "not_applicable",
        })

        delayed = self.at + timedelta(minutes=1)
        self.set_engine("retry_wait", "MENTOR_JOB_CYCLE_RETRYABLE", attempts=1,
                        next_attempt=delayed)
        self.write_record()
        retry = self.describe()["mentor"]["resilience"]
        self.assertEqual(retry["scheduler"], {"status": "retry_wait", "attempts": 1})
        self.assertEqual(retry["provider_safety"], {
            "latest_attempt": None, "delayed_until": delayed.isoformat(),
            "delay_source": "backoff", "unknown_fence": False,
            "replay_authorization": "not_applicable",
        })

        self.set_engine("unknown", "MENTOR_JOB_CYCLE_UNKNOWN", attempts=1)
        self.write_record(acceptance="partial", execution_status="partial", email="unknown",
                          dispatch="unknown_outcome")
        unknown = self.describe()["mentor"]
        self.assertEqual(unknown["scheduler"], {
            "status": "unknown", "code": "MENTOR_JOB_CYCLE_UNKNOWN", "attempts": 1,
            "dispatch": "possibly_dispatched",
        })
        self.assertEqual(unknown["resilience"]["provider_safety"], {
            "latest_attempt": None, "delayed_until": None, "delay_source": None,
            "unknown_fence": True, "replay_authorization": "not_authorized",
        })
        self.assertEqual(unknown["runtime_acceptance"], {
            "execution": "partial", "acceptance": "partial", "model_turn": "unknown", "email": "unknown",
        })

        self.set_engine("failed", "OPERATOR_RECONCILED", attempts=1)
        self.write_record()
        mentor = self.describe()["mentor"]
        self.assertFalse(mentor["resilience"]["provider_safety"]["unknown_fence"])
        self.assertEqual(
            mentor["resilience"]["provider_safety"]["replay_authorization"],
            "not_applicable",
        )
        self.assertEqual(mentor["safeguards"]["replay_authorization"], "not_authorized")

    def test_forged_preflight_dto_fails_whole_mentor_without_canary(self):
        canary = "SYNTHETIC_PRIVATE_PREFLIGHT_CANARY"
        forged = view.resilience.LoopAssessment("warning", canary, True)
        with mock.patch.object(view.resilience, "assess_loop", return_value=forged):
            result = self.describe()
        self.assertEqual(result["mentor"], {"status": "unavailable"})
        self.assertNotIn(canary, json.dumps(result))

    def test_engine_accepts_bounded_normal_cycle_dispatch_retry_and_reconciled_codes(self):
        cases = (
            ("succeeded", "MENTOR_JOB_CYCLE_SUCCEEDED"),
            ("failed", "MENTOR_JOB_CYCLE_FAILED"),
            ("retry_wait", "MENTOR_JOB_CYCLE_RETRYABLE"),
            ("running", "DISPATCHING"),
            ("failed", "OPERATOR_RECONCILED"),
        )
        for status, code in cases:
            with self.subTest(status=status, code=code):
                self.set_engine(status, code)
                self.assertEqual(self.describe()["mentor"]["scheduler"], {
                    "status": status, "code": code, "attempts": 1,
                    "dispatch": "definitely_not_dispatched",
                })
        self.set_engine("unknown", "MENTOR_JOB_CYCLE_UNKNOWN")
        unknown = self.describe()["mentor"]
        self.assertEqual(unknown["scheduler"], {
            "status": "unknown", "code": "MENTOR_JOB_CYCLE_UNKNOWN", "attempts": 1,
            "dispatch": "definitely_not_dispatched",
        })
        self.assertEqual(unknown["resilience"]["provider_safety"], {
            "latest_attempt": None, "delayed_until": None, "delay_source": None,
            "unknown_fence": True, "replay_authorization": "not_authorized",
        })
        self.set_engine("failed", "MENTOR_JOB_CYCLE_FAILED\nSYNTHETIC_PRIVATE")
        self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})

    def test_acceptance_domains_zero_reconciliation_and_cross_state_consistency(self):
        self.set_engine("ready", "MENTOR_JOB_CYCLE_BLOCKED", attempts=0)
        self.write_record(acceptance="unverified", execution_status="pending", email="pending", reconciliations=[])
        mentor = self.describe()["mentor"]
        self.assertEqual(mentor["runtime_acceptance"], {
            "execution": "pending", "acceptance": "unverified", "model_turn": "not_started", "email": "pending",
        })
        self.assertEqual(mentor["scheduler"]["dispatch"], "not_attempted")
        self.assertNotIn("operator_reconciled", [item["event"] for item in mentor["recovery_timeline"]])
        self.assertEqual(mentor["gates"]["no_duplicate_dispatch"], "not_verified")

        self.set_engine("unknown", "MENTOR_JOB_CYCLE_UNKNOWN")
        self.write_record(acceptance="partial", execution_status="partial", email="unknown",
                          dispatch="unknown_outcome")
        unknown = self.describe()["mentor"]
        self.assertEqual(unknown["scheduler"]["dispatch"], "possibly_dispatched")
        self.assertEqual(unknown["runtime_acceptance"], {
            "execution": "partial", "acceptance": "partial", "model_turn": "unknown", "email": "unknown",
        })
        self.assertEqual(unknown["resilience"]["provider_safety"], {
            "latest_attempt": None, "delayed_until": None, "delay_source": None,
            "unknown_fence": True, "replay_authorization": "not_authorized",
        })

        self.complete_session()
        self.set_engine("succeeded", "MENTOR_JOB_CYCLE_SUCCEEDED")
        self.write_record(acceptance="passed", execution_status="passed", email="verified",
                          dispatch="dispatched", turn_completed=True, postconditions=list(view._GATE_IDS))
        mentor = self.describe()["mentor"]
        self.assertEqual(mentor["runtime_acceptance"], {
            "execution": "passed", "acceptance": "passed", "model_turn": "completed", "email": "verified",
        })
        self.assertEqual(mentor["scheduler"]["dispatch"], "confirmed_dispatched")
        self.assertTrue(all(state == "verified" for state in mentor["gates"].values()))

        self.write_record(acceptance="pending", execution_status="pending", email="failed")
        self.assertEqual(self.describe()["mentor"]["runtime_acceptance"]["email"], "failed")

        self.write_record(acceptance="failed", execution_status="failed", email="pending")
        self.assertEqual(self.describe()["mentor"]["runtime_acceptance"]["acceptance"], "failed")

        self.write_record(acceptance="unverified", execution_status="unverified", email="unknown")
        self.assertEqual(self.describe()["mentor"]["runtime_acceptance"]["acceptance"], "unverified")

        for acceptance, execution, email in (("passed", "passed", "pending"),
                                               ("partial", "failed", "verified"),
                                               ("failed", "partial", "failed")):
            with self.subTest(acceptance=acceptance, execution=execution, email=email):
                self.write_record(acceptance=acceptance, execution_status=execution, email=email)
                self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})

    def test_resilience_generated_at_is_caller_instant_normalized_to_utc(self):
        offset_at = self.at.astimezone(timezone(timedelta(hours=8)))
        self.assertEqual(
            self.describe(at=offset_at)["mentor"]["resilience"]["generated_at"],
            self.at.isoformat(),
        )

    def test_retry_delay_must_be_strictly_future(self):
        self.set_engine(
            "retry_wait", "MENTOR_JOB_CYCLE_RETRYABLE", attempts=1,
            next_attempt=self.at,
        )
        self.write_record()
        self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})

    def test_deadline_is_expired_at_exact_end(self):
        end = datetime(2026, 11, 5, 1, 10, tzinfo=timezone.utc)
        self.assertEqual(self.describe(at=end)["mentor"]["work_order"]["window_state"], "expired")
        self.assertEqual(self.describe(at=end - timedelta(microseconds=1))["mentor"]["work_order"]["window_state"], "open")

    def test_malformed_or_identity_contradictory_evidence_keeps_mentor_sentinel(self):
        self.write_record(job_id="another.job")
        self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})
        self.write_record(turn_completed=True, dispatch="definitely_not_dispatched")
        self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})
        self.record_path.write_text("{bad", encoding="utf-8")
        self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})

    def test_failed_unknown_and_partial_gate_claims_cannot_override_authoritative_facts(self):
        cases = (
            ("failed", "failed", "model_turn"),
            ("unverified", "unverified", "journal_cycle_postcondition"),
            ("partial", "partial", "model_turn"),
        )
        for acceptance, execution, gate in cases:
            with self.subTest(execution=execution, gate=gate):
                self.write_record(acceptance=acceptance, execution_status=execution, email="unknown",
                                  dispatch="unknown_outcome", postconditions=[gate])
                self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})

    def test_reconciliation_must_bind_latest_attempt_of_current_slot(self):
        self.set_engine("failed", "OPERATOR_RECONCILED", attempts=2)
        stale = [{
            "classification": "definitely_not_dispatched", "attempt_id": "attempt-1",
            "outcome": "failed", "verified_at": "2026-11-05T02:00:04+00:00",
        }]
        self.write_record(reconciliations=stale)
        self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})

        cross_attempt = [{
            "classification": "definitely_not_dispatched", "attempt_id": "other-attempt",
            "outcome": "failed", "verified_at": "2026-11-05T02:00:04+00:00",
        }]
        with sqlite3.connect(self.root / ".job-runtime/engine/schedule.sqlite") as db:
            db.execute("INSERT INTO attempts VALUES(?,?,?)", (
                "other-attempt", "other-slot", 99,
            ))
        self.write_record(reconciliations=cross_attempt)
        self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})

        current = [{
            "classification": "definitely_not_dispatched", "attempt_id": "attempt-2",
            "outcome": "failed", "verified_at": "2026-11-05T02:00:04+00:00",
        }]
        self.write_record(reconciliations=current)
        mentor = self.describe()["mentor"]
        self.assertEqual(mentor["scheduler"]["attempts"], 2)
        self.assertNotIn("attempt-2", json.dumps(mentor))

    def test_out_of_order_recovery_timestamps_fail_closed(self):
        self.write_record()
        record = json.loads(self.record_path.read_text())
        record["execution"]["started_at"] = "2026-11-05T01:59:59+00:00"
        self.record_path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})

    def test_duplicate_attempt_fact_fails_only_the_duplicate_dispatch_gate(self):
        self.set_engine("failed", "MENTOR_JOB_CYCLE_FAILED", attempts=2)
        self.write_record()
        mentor = self.describe()["mentor"]
        self.assertEqual(mentor["scheduler"]["attempts"], 2)
        self.assertEqual(mentor["gates"]["no_duplicate_dispatch"], "failed")

    def test_symlink_and_permission_failures_are_unavailable_without_leakage(self):
        head = self.root / self.state_directory / "head.json"
        head.chmod(0o644)
        self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})
        head.chmod(0o600)
        self.record_path.chmod(0o644)
        self.assertEqual(self.describe()["mentor"], {"status": "unavailable"})
        self.record_path.chmod(0o600)
        outside = self.root / "outside.json"
        outside.write_text("SYNTHETIC_OUTSIDE")
        self.record_path.unlink()
        self.record_path.symlink_to(outside)
        result = self.describe()
        self.assertEqual(result["mentor"], {"status": "unavailable"})
        self.assertNotIn("SYNTHETIC_OUTSIDE", json.dumps(result))

    def test_read_does_not_mutate_state_engine_or_acceptance(self):
        paths = [self.root / self.state_directory / "head.json", self.record_path, self.root / ".job-runtime/engine/schedule.sqlite"]
        before = {path: path.read_bytes() for path in paths}
        self.describe()
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_output_lookup_is_never_supported(self):
        with self.assertRaisesRegex(ValueError, "DASHBOARD_OUTPUT_NOT_FOUND"):
            view.describe(self.root, self.job, self.at, next_tick=lambda *_: None, output_id="a" * 64)


if __name__ == "__main__":
    unittest.main()
