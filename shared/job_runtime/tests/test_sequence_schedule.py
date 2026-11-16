"""Bounded finite sequence schedule validation, allocation, and durability."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest

from shared.job_runtime.engine import Engine, EngineError


ROOT = Path(__file__).resolve().parents[3]
PRIVATE = ROOT / ".job-runtime" / "tests"
PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
UTC = timezone.utc
RETRY = {"max_attempts": 3, "backoff_seconds": 5, "max_backoff_seconds": 10}


def at(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sequence(*values, grace_seconds=60):
    return {"kind": "sequence", "timestamps": list(values), "grace_seconds": grace_seconds}


def job(schedule, replay_safe=True):
    return {"id": "sequence-job", "enabled": True, "replay_safe": replay_safe,
            "schedule": schedule, "profile": "synthetic-model", "prompt": "synthetic-only"}


def success(_job, _context):
    return {"status": "succeeded", "code": "TRANSPORT_COMPLETED",
            "receipt": {"observed_exit_code": 0}}


class SequenceScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PRIVATE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / ".job-runtime" / "engine"
        self.now = at("2026-10-30T17:00:00Z")

    def engine(self, schedule, dispatch=success, clock=None, replay_safe=True):
        return Engine(self.state, [job(schedule, replay_safe)], RETRY, dispatch,
                      workspace_root=self.root, clock=clock or (lambda: self.now))

    def slots(self, engine):
        with engine._db() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM slots ORDER BY scheduled_at,slot_id")]

    def test_schema_rejects_naive_duplicate_unsorted_oversize_and_extra_keys(self):
        invalid = [
            (sequence("2026-10-30T17:00:00"), "SCHEDULE_TIME_INVALID"),
            (sequence("2026-10-30T17:00:00Z", "2026-10-30T17:00:00+00:00"),
             "SEQUENCE_TIMESTAMPS_INVALID"),
            (sequence("2026-10-30T13:00:00-04:00"), "SCHEDULE_TIME_INVALID"),
            (sequence("2026-10-30T17:00:01Z", "2026-10-30T17:00:00Z"),
             "SEQUENCE_TIMESTAMPS_INVALID"),
            (sequence(*[(self.now + timedelta(seconds=i)).isoformat() for i in range(129)]),
             "SEQUENCE_TIMESTAMPS_INVALID"),
            (dict(sequence("2026-10-30T17:00:00Z"), timezone="UTC"),
             "SEQUENCE_KEYS_INVALID"),
        ]
        for schedule, code in invalid:
            with self.subTest(code=code), self.assertRaisesRegex(EngineError, code):
                self.engine(schedule)

    def test_schema_requires_exact_types_and_bounded_nonempty_length(self):
        invalid = [
            {"kind": "sequence", "timestamps": [], "grace_seconds": 60},
            {"kind": "sequence", "timestamps": ("2026-10-30T17:00:00Z",), "grace_seconds": 60},
            {"kind": "sequence", "timestamps": [self.now], "grace_seconds": 60},
            {"kind": "sequence", "timestamps": ["2026-10-30T17:00:00Z"], "grace_seconds": True},
            {"kind": "sequence", "grace_seconds": 60},
        ]
        for schedule in invalid:
            with self.subTest(schedule=schedule), self.assertRaises(EngineError):
                self.engine(schedule)

    def test_future_timestamp_is_never_allocated_or_dispatched_early(self):
        due = self.now + timedelta(seconds=20)
        engine = self.engine(sequence(due.isoformat()))
        self.assertEqual(engine.tick(self.now)["dispatched"], 0)
        self.assertEqual(self.slots(engine), [])
        self.assertEqual(engine.tick(due - timedelta(microseconds=1))["dispatched"], 0)
        self.assertEqual(engine.tick(due)["succeeded"], 1)
        self.assertEqual(engine.tick(due + timedelta(seconds=1))["dispatched"], 0)

    def test_multiple_due_timestamps_are_claimed_sequentially_one_per_tick(self):
        timestamps = [self.now + timedelta(seconds=i) for i in range(3)]
        contexts = []
        engine = self.engine(sequence(*(value.isoformat() for value in timestamps)),
                             lambda j, c: contexts.append(c) or success(j, c))
        due = timestamps[-1]
        for remaining in (2, 1, 0):
            self.assertEqual(engine.tick(due)["succeeded"], 1)
            self.assertEqual(sum(row["status"] == "ready" for row in self.slots(engine)), remaining)
        self.assertEqual(engine.tick(due)["dispatched"], 0)
        self.assertEqual([context["slot_id"] for context in contexts],
                         [f"sequence-job:sequence:{index}" for index in range(3)])
        self.assertEqual([context["scheduled_at"] for context in contexts],
                         [value.isoformat() for value in timestamps])

    def test_bounded_old_history_never_drops_currently_eligible_slots(self):
        old = [self.now - timedelta(seconds=1000 - index) for index in range(126)]
        eligible = [self.now - timedelta(seconds=1), self.now]
        engine = self.engine(sequence(*(value.isoformat() for value in old + eligible),
                                      grace_seconds=5))
        self.assertEqual(engine.tick(self.now)["succeeded"], 1)
        self.assertEqual(engine.tick(self.now)["succeeded"], 1)
        rows = self.slots(engine)
        self.assertEqual(len(rows), 128)
        self.assertEqual(sum(row["status"] == "missed" for row in rows), 126)
        self.assertEqual(sum(row["status"] == "succeeded" for row in rows), 2)

    def test_running_and_unknown_prior_slot_each_block_later_sequence_slot(self):
        schedule = sequence(self.now.isoformat(), (self.now + timedelta(seconds=1)).isoformat())
        engine = self.engine(schedule)
        with engine._db() as db:
            db.execute("BEGIN IMMEDIATE")
            engine._allocate(db, job(schedule), (self.now + timedelta(seconds=1)).timestamp())
        claim = engine._claim("sequence-job", (self.now + timedelta(seconds=1)).timestamp())
        self.assertEqual(claim["slot_id"], "sequence-job:sequence:0")
        self.assertEqual(engine.tick(self.now + timedelta(seconds=1))["dispatched"], 0)
        self.assertEqual(self.slots(engine)[1]["status"], "ready")

        self.state = self.root / ".job-runtime" / "unknown"
        calls = []
        engine = self.engine(schedule, lambda j, c: calls.append(c) or
                             {"status": "unknown", "code": "OUTCOME_UNKNOWN"})
        self.assertEqual(engine.tick(self.now + timedelta(seconds=1))["unknown"], 1)
        self.assertEqual(engine.tick(self.now + timedelta(seconds=1))["dispatched"], 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual([row["status"] for row in self.slots(engine)], ["unknown", "ready"])

    def test_explicit_retry_semantics_and_grace_expiry_are_preserved(self):
        schedule = sequence(self.now.isoformat(), (self.now + timedelta(seconds=1)).isoformat(),
                            grace_seconds=20)
        calls = []
        def retry_then_succeed(j, context):
            calls.append(context)
            if context["slot_id"].endswith(":0") and context["attempt_no"] == 1:
                return {"status": "retryable", "code": "TRANSIENT_TRANSPORT_ERROR"}
            return success(j, context)

        engine = self.engine(schedule, retry_then_succeed)
        self.assertEqual(engine.tick(self.now)["retry_wait"], 1)
        # Existing retry semantics do not fence a later ready slot during backoff.
        self.assertEqual(engine.tick(self.now + timedelta(seconds=1))["succeeded"], 1)
        self.assertEqual(engine.tick(self.now + timedelta(seconds=5))["succeeded"], 1)
        self.assertEqual(engine.tick(self.now + timedelta(seconds=5))["dispatched"], 0)
        self.assertEqual([context["slot_id"] for context in calls],
                         ["sequence-job:sequence:0", "sequence-job:sequence:1",
                          "sequence-job:sequence:0"])

        self.state = self.root / ".job-runtime" / "expiry"
        expired = self.engine(sequence(self.now.isoformat(), grace_seconds=4),
                              lambda j, c: {"status": "retryable", "code": "TRY_AGAIN"})
        self.assertEqual(expired.tick(self.now)["failed"], 1)
        self.assertEqual(self.slots(expired)[0]["code"], "RETRY_WINDOW_EXPIRED")
        self.assertEqual(expired.tick(self.now + timedelta(seconds=5))["dispatched"], 0)

    def test_duplicate_ticks_and_competing_processes_claim_each_slot_once(self):
        schedule = sequence(self.now.isoformat())
        entered = threading.Event()
        release = threading.Event()
        calls = []
        def blocking(j, context):
            calls.append(context)
            entered.set()
            release.wait(3)
            return success(j, context)

        first = self.engine(schedule, blocking)
        second = self.engine(schedule, blocking)
        worker = threading.Thread(target=first.tick, args=(self.now,))
        worker.start()
        self.assertTrue(entered.wait(2))
        self.assertEqual(second.tick(self.now)["dispatched"], 0)
        release.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(first.tick(self.now)["dispatched"], 0)
        self.assertEqual(len(calls), 1)

    def test_restart_persists_cursor_and_slots_and_rejects_clock_rollback(self):
        timestamps = [self.now + timedelta(seconds=value) for value in (10, 20, 30)]
        schedule = sequence(*(value.isoformat() for value in timestamps))
        calls = []
        engine = self.engine(schedule, lambda j, c: calls.append(c) or success(j, c))
        self.assertEqual(engine.tick(self.now)["dispatched"], 0)

        engine = self.engine(schedule, lambda j, c: calls.append(c) or success(j, c))
        self.assertEqual(engine.tick(timestamps[1])["succeeded"], 1)
        self.assertEqual(engine.tick(timestamps[1])["succeeded"], 1)
        self.assertEqual(len(self.slots(engine)), 2)

        engine = self.engine(schedule, lambda j, c: calls.append(c) or success(j, c))
        self.assertEqual(engine.tick(timestamps[2])["succeeded"], 1)
        self.assertEqual(engine.tick(timestamps[2])["dispatched"], 0)
        self.assertEqual(len(self.slots(engine)), 3)
        with self.assertRaisesRegex(EngineError, "CLOCK_MOVED_BACKWARDS"):
            engine.tick(timestamps[2] - timedelta(microseconds=1))
        self.assertEqual([context["slot_id"] for context in calls],
                         [f"sequence-job:sequence:{index}" for index in range(3)])

    def test_interval_daily_and_once_still_allocate_and_dispatch(self):
        schedules = [
            {"kind": "interval", "seconds": 60, "grace_seconds": 120},
            {"kind": "daily", "timezone": "UTC", "times": ["17:00"], "grace_seconds": 60},
            {"kind": "once", "at": self.now.isoformat(), "grace_seconds": 60},
        ]
        for index, schedule in enumerate(schedules):
            with self.subTest(kind=schedule["kind"]):
                self.state = self.root / ".job-runtime" / f"existing-{index}"
                self.assertEqual(self.engine(schedule).tick(self.now)["succeeded"], 1)


if __name__ == "__main__":
    unittest.main()
