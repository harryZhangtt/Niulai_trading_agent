"""Offline schedules, duplicate claims, restart uncertainty and retry controls."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest
import sqlite3

from shared.job_runtime.engine import Engine, EngineError

ROOT = Path(__file__).resolve().parents[3]
PRIVATE = ROOT / ".job-runtime" / "tests"
PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
UTC = timezone.utc
RETRY = {"max_attempts": 3, "backoff_seconds": 5, "max_backoff_seconds": 10}


def at(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def job(schedule=None, replay_safe=True):
    return {"id": "synthetic-job", "enabled": True, "replay_safe": replay_safe,
            "schedule": schedule or {"kind": "interval", "seconds": 60, "grace_seconds": 120},
            "profile": "synthetic-model", "prompt": "synthetic-only"}


def success(_job, _context):
    return {"status": "succeeded", "code": "TRANSPORT_COMPLETED", "receipt": {"observed_exit_code": 0}}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PRIVATE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / ".job-runtime" / "engine"
        self.now = at("2026-10-30T17:00:00Z")

    def engine(self, jobs=None, dispatch=success, clock=None):
        return Engine(self.state, jobs or [job()], RETRY, dispatch,
                      workspace_root=self.root, clock=clock or (lambda: self.now))

    def slots(self, engine):
        with engine._db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM slots ORDER BY scheduled_at,slot_id")]

    def test_duplicate_tick_and_second_process_cannot_dispatch_completed_slot(self):
        calls = []
        e = self.engine(dispatch=lambda j, c: calls.append(c) or success(j, c))
        self.assertEqual(e.tick(self.now)["succeeded"], 1)
        self.assertEqual(e.tick(self.now)["dispatched"], 0)
        other = self.engine(dispatch=lambda j, c: calls.append(c) or success(j, c))
        self.assertEqual(other.tick(self.now)["dispatched"], 0)
        self.assertEqual(len(calls), 1)

    def test_interval_outage_is_coalesced_not_replayed_as_many_calls(self):
        e = self.engine()
        e.tick(self.now)
        later = self.now + timedelta(minutes=10)
        self.assertEqual(e.tick(later)["dispatched"], 1)
        rows = self.slots(e)
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(r["status"] == "coalesced" for r in rows), 1)

    def test_daily_first_wake_records_today_missed_and_admits_only_in_grace(self):
        s = {"kind": "daily", "timezone": "America/New_York", "times": ["10:00", "13:00", "19:00"], "grace_seconds": 3600}
        e = self.engine([job(s)])
        summary = e.tick(self.now + timedelta(minutes=15))  # 13:15 New York
        self.assertEqual(summary["succeeded"], 1)
        rows = self.slots(e)
        self.assertEqual([r["status"] for r in rows], ["missed", "succeeded"])
        self.assertTrue(all("2026-10-30" in r["slot_id"] for r in rows))

    def test_daily_new_york_dst_keeps_wall_clock_slot(self):
        s = {"kind": "daily", "timezone": "America/New_York", "times": ["13:00"], "grace_seconds": 3600}
        calls = []
        e = self.engine([job(s)], lambda j, c: calls.append(c) or success(j, c))
        e.tick(at("2026-10-30T17:00:00Z"))
        e.tick(at("2026-11-02T18:00:00Z"))
        self.assertEqual(calls[0]["scheduled_at"], "2026-10-30T17:00:00+00:00")
        self.assertEqual(calls[-1]["scheduled_at"], "2026-11-02T18:00:00+00:00")

    def test_ambiguous_dst_wall_time_executes_once_and_nonexistent_is_missed(self):
        s = {"kind": "daily", "timezone": "America/New_York", "times": ["01:30"], "grace_seconds": 7200}
        e = self.engine([job(s)])
        self.assertEqual(e.tick(at("2026-11-01T05:30:00Z"))["succeeded"], 1)
        self.assertEqual(e.tick(at("2026-11-01T06:30:00Z"))["dispatched"], 0)
        # A separate synthetic state tests spring-forward without backwards clock.
        self.state = self.root / ".job-runtime" / "spring"
        s["times"] = ["02:30"]
        e = self.engine([job(s)])
        self.assertEqual(e.tick(at("2026-03-08T08:00:00Z"))["dispatched"], 0)
        self.assertEqual(self.slots(e)[0]["code"], "LOCAL_TIME_NONEXISTENT")

    def test_one_time_wake_not_early_and_never_repeated(self):
        s = {"kind": "once", "at": (self.now + timedelta(seconds=20)).isoformat(), "grace_seconds": 60}
        e = self.engine([job(s)])
        self.assertEqual(e.tick(self.now)["dispatched"], 0)
        self.assertEqual(e.tick(self.now + timedelta(seconds=20))["succeeded"], 1)
        self.assertEqual(e.tick(self.now + timedelta(seconds=30))["dispatched"], 0)

    def test_explicit_safe_error_retries_bounded_with_persisted_backoff(self):
        calls = []
        def failed(j, c):
            calls.append(c)
            return {"status": "retryable", "code": "TRANSIENT_TRANSPORT_ERROR"}
        e = self.engine(dispatch=failed)
        self.assertEqual(e.tick(self.now)["retry_wait"], 1)
        self.assertEqual(e.tick(self.now + timedelta(seconds=4))["dispatched"], 0)
        e = self.engine(dispatch=failed)
        self.assertEqual(e.tick(self.now + timedelta(seconds=5))["retry_wait"], 1)
        self.assertEqual(e.tick(self.now + timedelta(seconds=14))["dispatched"], 0)
        self.assertEqual(e.tick(self.now + timedelta(seconds=15))["failed"], 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.slots(e)[0]["code"], "RETRY_LIMIT_EXHAUSTED")

    def test_non_replay_safe_job_is_never_automatically_retried(self):
        e = self.engine([job(replay_safe=False)], lambda j, c: {"status": "retryable", "code": "SAFE_ERROR"})
        self.assertEqual(e.tick(self.now)["failed"], 1)
        self.assertEqual(e.tick(self.now + timedelta(seconds=5))["dispatched"], 0)
        self.assertEqual(self.slots(e)[0]["code"], "NON_REPLAY_SAFE_RETRY_BLOCKED")

    def test_unknown_exception_blocks_later_slots_until_operator_reconciles(self):
        def error(*args):
            raise RuntimeError("must never log arbitrary credential content")
        e = self.engine(dispatch=error)
        self.assertEqual(e.tick(self.now)["unknown"], 1)
        self.assertEqual(e.tick(self.now + timedelta(minutes=1))["dispatched"], 0)
        self.assertNotIn("credential", str(e.status()))
        first = self.slots(e)[0]
        with self.assertRaises(EngineError):
            e.resolve_unknown(first["slot_id"], "failed", {}, self.now)
        e.resolve_unknown(first["slot_id"], "failed", {"independent_process_exit_receipt": "synthetic"}, self.now + timedelta(minutes=1))
        e.dispatcher = success
        self.assertEqual(e.tick(self.now + timedelta(minutes=1))["succeeded"], 1)

    def test_restart_recovery_never_releases_unknown_for_blind_retry(self):
        e = self.engine()
        with e._db() as db:
            db.execute("BEGIN IMMEDIATE")
            e._allocate(db, job(), self.now.timestamp())
        claim = e._claim(job()["id"], self.now.timestamp())
        self.assertIsNotNone(claim)
        e = self.engine()
        self.assertEqual(e.recover_running(self.now), 1)
        self.assertEqual(e.tick(self.now + timedelta(minutes=1))["dispatched"], 0)
        self.assertEqual(self.slots(e)[0]["status"], "unknown")

    def test_competing_processes_cannot_overlap_same_job(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        def blocking(j, c):
            calls.append(c)
            entered.set()
            release.wait(5)
            return success(j, c)
        e1 = self.engine(dispatch=blocking)
        e2 = self.engine(dispatch=blocking)
        worker = threading.Thread(target=e1.tick, args=(self.now,))
        worker.start()
        self.assertTrue(entered.wait(3))
        self.assertEqual(e2.tick(self.now)["dispatched"], 0)
        release.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(calls), 1)

    def test_success_requires_external_dispatch_receipt(self):
        e = self.engine(dispatch=lambda j, c: {"status": "succeeded", "code": "MODEL_SAYS_DONE"})
        self.assertEqual(e.tick(self.now)["unknown"], 1)
        self.assertEqual(self.slots(e)[0]["code"], "TRANSPORT_RECEIPT_REQUIRED")

    def test_independent_jobs_dispatch_concurrently_with_central_limit(self):
        first_started = threading.Event()
        second_finished = threading.Event()
        release = threading.Event()
        j1 = job();j1["id"] = "first"
        j2 = job();j2["id"] = "second"
        def dispatch(j, c):
            if j["id"] == "first":
                first_started.set()
                release.wait(3)
            else:
                self.assertTrue(first_started.wait(2))
                second_finished.set()
            return success(j, c)
        e = self.engine([j1, j2], dispatch)
        result = []
        worker = threading.Thread(target=lambda: result.append(e.tick(self.now)))
        worker.start()
        self.assertTrue(second_finished.wait(2))
        self.assertTrue(worker.is_alive())
        release.set();worker.join(3)
        self.assertEqual(result[0]["succeeded"], 2)
        with self.assertRaisesRegex(EngineError, "MAX_WORKERS_INVALID"):
            Engine(self.state, [j1], RETRY, success, workspace_root=self.root, max_workers=9)

    def test_shared_resources_queue_without_claim_or_retry_while_independent_group_runs(self):
        first_started = threading.Event()
        second_started = threading.Event()
        independent_started = threading.Event()
        release = threading.Event()
        j1 = dict(job(), id="shared-first", _resource_key="synthetic-auth-A")
        j2 = dict(job(), id="shared-second", _resource_key="synthetic-auth-A")
        j3 = dict(job(), id="independent", _resource_key="synthetic-auth-B")
        contexts = []
        def dispatch(j, c):
            contexts.append(c)
            if j["id"] == "shared-first":
                first_started.set()
                release.wait(3)
            elif j["id"] == "shared-second":
                second_started.set()
            else:
                independent_started.set()
            return success(j, c)
        e = self.engine([j1, j2, j3], dispatch)
        output = []
        worker = threading.Thread(target=lambda: output.append(e.tick(self.now)))
        worker.start()
        self.assertTrue(first_started.wait(2))
        self.assertTrue(independent_started.wait(2))
        self.assertFalse(second_started.is_set())
        with e._db() as db:
            row = db.execute("SELECT status,attempts FROM slots WHERE job_id='shared-second'").fetchone()
            self.assertEqual((row["status"], row["attempts"]), ("ready", 0))
        release.set();worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(second_started.is_set())
        self.assertEqual(output[0]["succeeded"], 3)
        self.assertTrue(all(c["attempt_no"] == 1 for c in contexts))

    def test_private_paths_and_schedule_mutation_fail_closed(self):
        outside = self.root / "archive"
        with self.assertRaises(EngineError):
            Engine(outside, [job()], RETRY, success, workspace_root=self.root)
        self.assertFalse(outside.exists())
        e = self.engine()
        e.tick(self.now)
        changed = job({"kind": "interval", "seconds": 30})
        altered = self.engine([changed])
        with self.assertRaisesRegex(EngineError, "SCHEDULE_CHANGE_REQUIRES_NEW_JOB_ID"):
            altered.tick(self.now)
        self.assertEqual(e.path.stat().st_mode & 0o777, 0o600)

    def test_disabled_job_and_clock_reversal_do_not_dispatch(self):
        j = job();j["enabled"] = False
        e = self.engine([j])
        self.assertEqual(e.tick(self.now)["dispatched"], 0)
        self.assertEqual(self.slots(e), [])
        e = self.engine()
        e.tick(self.now)
        with self.assertRaisesRegex(EngineError, "CLOCK_MOVED_BACKWARDS"):
            e.tick(self.now - timedelta(seconds=1))
        with self.assertRaises(EngineError):
            e.tick(datetime(2026, 10, 30))

    def delivery_evidence(self):
        return {'evidence_type': 'independent_business_delivery_verification', 'message_id': 'abcdef1234567890',
                'payload_digest': 'a' * 64, 'verified_at': (self.now + timedelta(seconds=2)).isoformat()}

    def failed_format(self, code='BUSINESS_FINAL_VALUE_INVALID', transport=None):
        transport = {'turn_completed': True, 'exit_code': 0} if transport is None else transport
        e = self.engine(dispatch=lambda j, c: {'status': 'failed', 'code': code, 'receipt': transport})
        e.tick(self.now)
        return e, self.slots(e)[0]['slot_id']

    def test_independent_delivery_reconciliation_preserves_failed_attempt_and_never_redispatches(self):
        e, slot = self.failed_format()
        with e._db() as db:
            before = tuple(db.execute('SELECT * FROM attempts WHERE slot_id=?', (slot,)).fetchone())
        result = e.reconcile_failed_delivery(slot, self.delivery_evidence(), self.now + timedelta(seconds=3))
        self.assertTrue(result['reconciliation_created'])
        self.assertEqual(self.slots(e)[0]['code'], 'OPERATOR_VERIFIED_DELIVERY')
        self.assertEqual(e.tick(self.now + timedelta(seconds=4))['dispatched'], 0)
        with e._db() as db:
            after = tuple(db.execute('SELECT * FROM attempts WHERE slot_id=?', (slot,)).fetchone())
            self.assertEqual(before, after)
            self.assertEqual(db.execute('SELECT count(*) FROM delivery_reconciliations').fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM delivery_reconciliations WHERE slot_id=?', (slot,))

    def test_delivery_reconciliation_is_idempotent_and_conflicting_evidence_rejected(self):
        e, slot = self.failed_format('BUSINESS_FINAL_JSON_REQUIRED')
        evidence = self.delivery_evidence()
        e.reconcile_failed_delivery(slot, evidence, self.now + timedelta(seconds=3))
        self.assertFalse(e.reconcile_failed_delivery(slot, evidence, self.now + timedelta(seconds=4))['reconciliation_created'])
        for changed in (dict(evidence, message_id='1234567890abcdef'), dict(evidence, payload_digest='b' * 64)):
            with self.assertRaisesRegex(EngineError, 'DELIVERY_RECONCILIATION_CONFLICT'):
                e.reconcile_failed_delivery(slot, changed, self.now + timedelta(seconds=4))

    def test_unrelated_failure_or_incomplete_transport_cannot_be_promoted(self):
        e, slot = self.failed_format('MODEL_AUTH_REQUIRED')
        with self.assertRaisesRegex(EngineError, 'FAILED_FORMAT_SLOT_REQUIRED'):
            e.reconcile_failed_delivery(slot, self.delivery_evidence(), self.now + timedelta(seconds=3))
        self.state = self.root / '.job-runtime' / 'no-transport'
        e, slot = self.failed_format(transport={'turn_completed': False, 'exit_code': 0})
        with self.assertRaisesRegex(EngineError, 'COMPLETED_MODEL_TRANSPORT_REQUIRED'):
            e.reconcile_failed_delivery(slot, self.delivery_evidence(), self.now + timedelta(seconds=3))
        for invalid in ({}, dict(self.delivery_evidence(), message_id='not-gmail'),
                        dict(self.delivery_evidence(), verified_at='2026-10-30T17:00:00')):
            with self.assertRaises(EngineError):
                e.reconcile_failed_delivery(slot, invalid, self.now + timedelta(seconds=3))


if __name__ == "__main__":
    unittest.main()
