"""Unit tests for the pure scheduler resilience preflight helper."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import json
import unittest

from mentor.scheduler.resilience_preflight import (
    CatchUpAssessment,
    HostAssessment,
    LoopAssessment,
    assess_catch_up,
    assess_host,
    assess_loop,
    build_resilience_summary,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


class HostAssessmentTests(unittest.TestCase):
    def assess(self, **changes):
        values = {
            "daemon_registered": True,
            "service_generation_current": True,
            "heartbeat_at": NOW - timedelta(seconds=10),
            "last_tick_at": NOW - timedelta(seconds=20),
            "watchdog_checked_at": None,
            "watchdog_healthy": None,
            "now": NOW,
            "stale_seconds": 30,
        }
        values.update(changes)
        return assess_host(**values)

    def test_ready_requires_two_fresh_samples_and_is_immutable(self):
        result = self.assess()
        self.assertEqual(result.state, "ready")
        self.assertEqual(result.reason, "HOST_READY_STABLE")
        self.assertTrue(result.stable)
        self.assertEqual(result.sample_count, 2)
        self.assertEqual((result.heartbeat_age_seconds, result.last_tick_age_seconds), (10, 20))
        with self.assertRaises(FrozenInstanceError):
            result.state = "stale"

    def test_one_sample_cannot_be_stable(self):
        result = self.assess(last_tick_at=None)
        self.assertEqual(result.state, "unavailable")
        self.assertEqual(result.reason, "HOST_INSUFFICIENT_SAMPLES")
        self.assertFalse(result.stable)
        self.assertEqual(result.sample_count, 1)

    def test_freshness_boundary_is_inclusive_then_stale(self):
        at_boundary = self.assess(last_tick_at=NOW - timedelta(seconds=30))
        past_boundary = self.assess(last_tick_at=NOW - timedelta(seconds=31))
        self.assertEqual(at_boundary.state, "ready")
        self.assertEqual(past_boundary.state, "stale")
        self.assertEqual(past_boundary.reason, "HOST_OBSERVATION_STALE")

    def test_future_observation_or_clock_rollback_fails_closed(self):
        result = self.assess(heartbeat_at=NOW + timedelta(microseconds=1))
        self.assertEqual((result.state, result.reason), ("unavailable", "HOST_CLOCK_ROLLBACK"))

    def test_non_utc_naive_bad_range_and_bool_subclass_fail_closed(self):
        invalid = (
            {"now": NOW.replace(tzinfo=None)},
            {"now": NOW.astimezone(timezone(timedelta(hours=1)))},
            {"stale_seconds": 0},
            {"daemon_registered": 1},
            {"watchdog_checked_at": NOW, "watchdog_healthy": None},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                self.assertEqual(self.assess(**changes).reason, "HOST_INPUT_INVALID")

    def test_host_failure_reason_precedence_is_fixed(self):
        self.assertEqual(self.assess(daemon_registered=False).reason, "HOST_DAEMON_UNREGISTERED")
        self.assertEqual(self.assess(service_generation_current=False).reason, "HOST_SERVICE_GENERATION_STALE")
        self.assertEqual(
            self.assess(watchdog_checked_at=NOW, watchdog_healthy=False).reason,
            "HOST_WATCHDOG_UNHEALTHY",
        )


class CatchUpAssessmentTests(unittest.TestCase):
    def row(self, status, *, attempts=0, scheduled=None, updated=None, **extra):
        value = {
            "status": status,
            "scheduled": scheduled or NOW - timedelta(minutes=2),
            "updated": updated or NOW - timedelta(minutes=1),
            "attempts": attempts,
        }
        value.update(extra)
        return value

    def test_counts_are_exact_and_coalesced_has_state_precedence(self):
        rows = [
            self.row("ready"),
            self.row("succeeded", attempts=1),
            self.row("missed"),
            self.row("coalesced"),
        ]
        result = assess_catch_up(rows, NOW)
        self.assertEqual(result.state, "coalesced")
        self.assertEqual((result.total, result.within_grace, result.missed, result.coalesced), (4, 2, 1, 1))
        self.assertFalse(hasattr(result, "sleep_detected"))

    def test_missed_precedes_within_grace_and_nominal_is_within_grace(self):
        missed = assess_catch_up([self.row("ready"), self.row("missed")], NOW)
        nominal = assess_catch_up([self.row("ready"), self.row("running", attempts=1)], NOW)
        self.assertEqual(missed.state, "missed")
        self.assertEqual(nominal.state, "within_grace")

    def test_empty_oversized_extra_key_and_invalid_attempts_are_not_computable(self):
        invalid = (
            [],
            [self.row("ready")] * 257,
            [self.row("ready", raw_path="SYNTHETIC_PRIVATE_PATH")],
            [self.row("ready", attempts=True)],
            [self.row("running", attempts=0)],
        )
        for slots in invalid:
            with self.subTest(size=len(slots)):
                result = assess_catch_up(slots, NOW)
                self.assertEqual(result.state, "not_computable")
                self.assertEqual((result.total, result.within_grace, result.missed, result.coalesced), (0, 0, 0, 0))

    def test_future_or_reversed_slot_clock_is_not_computable(self):
        cases = (
            [self.row("ready", updated=NOW + timedelta(seconds=1))],
            [self.row("ready", scheduled=NOW, updated=NOW - timedelta(seconds=1))],
        )
        for slots in cases:
            self.assertEqual(assess_catch_up(slots, NOW).state, "not_computable")


class LoopAssessmentTests(unittest.TestCase):
    def test_exact_thresholds_and_dispatch(self):
        cases = (
            ((0, 2, 0, 3, False), ("neutral", False)),
            ((1, 2, 1, 3, False), ("info", False)),
            ((2, 2, 2, 3, False), ("warning", True)),
            ((1, 2, 3, 3, False), ("warning", True)),
            ((2, 2, 3, 3, False), ("critical", True)),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                result = assess_loop(*arguments)
                self.assertEqual((result.state, result.should_dispatch), expected)

    def test_verified_evidence_resets_even_at_both_thresholds(self):
        result = assess_loop(99, 2, 99, 3, True)
        self.assertEqual((result.state, result.reason, result.should_dispatch), (
            "neutral", "LOOP_VERIFIED_EVIDENCE_RESET", False,
        ))

    def test_invalid_values_are_unavailable_and_never_dispatch(self):
        cases = ((-1, 2, 0, 3, False), (0, 0, 0, 3, False), (0, 2, True, 3, False), (0, 2, 0, 3, 1))
        for arguments in cases:
            result = assess_loop(*arguments)
            self.assertEqual((result.state, result.reason, result.should_dispatch), (
                "unavailable", "LOOP_INPUT_INVALID", False,
            ))


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.host = assess_host(
            True, True, NOW - timedelta(seconds=1), NOW - timedelta(seconds=2),
            None, None, NOW, 30,
        )
        self.catch_up = assess_catch_up([{
            "status": "ready", "scheduled": NOW - timedelta(seconds=2),
            "updated": NOW - timedelta(seconds=1), "attempts": 0,
        }], NOW)
        self.loop = assess_loop(0, 2, 0, 2, False)

    def build(self, **changes):
        values = {
            "snapshot_state": "current",
            "scheduler_active": True,
            "provider_active": True,
            "recovery_unknown": False,
            "recovery_retry": False,
            "recovery_reconcile": False,
            "host": self.host,
            "catch_up": self.catch_up,
            "loop": self.loop,
            "observed_at": NOW,
        }
        values.update(changes)
        return build_resilience_summary(**values)

    def test_current_summary_has_exact_bounded_keys(self):
        result = self.build()
        value = result.as_dict()
        self.assertEqual((result.state, result.reason, result.recovery), ("current", "SUMMARY_CURRENT", "none"))
        self.assertEqual(set(value), {
            "schema_version", "state", "reason", "observed_at", "snapshot",
            "scheduler", "provider", "recovery", "host", "catch_up", "loop",
        })
        self.assertEqual(set(value["host"]), {
            "state", "reason", "stable", "sample_count", "heartbeat_age_seconds",
            "last_tick_age_seconds", "watchdog_age_seconds",
        })
        self.assertEqual(set(value["catch_up"]), {
            "state", "reason", "total", "within_grace", "missed", "coalesced",
        })
        self.assertEqual(set(value["loop"]), {"state", "reason", "should_dispatch"})

    def test_unknown_fence_precedes_stale_partial_retry_and_reconcile(self):
        stale = assess_host(True, True, NOW - timedelta(seconds=40), NOW - timedelta(seconds=41), None, None, NOW, 30)
        result = self.build(
            snapshot_state="stale", scheduler_active=False, provider_active=False,
            recovery_unknown=True, recovery_retry=True, recovery_reconcile=True,
            host=stale,
        )
        self.assertEqual((result.state, result.reason, result.recovery), (
            "unavailable", "SUMMARY_RECOVERY_UNKNOWN_FENCE", "unknown",
        ))

    def test_stale_then_partial_precedence(self):
        stale = assess_host(True, True, NOW - timedelta(seconds=40), NOW - timedelta(seconds=41), None, None, NOW, 30)
        self.assertEqual(self.build(host=stale, recovery_retry=True).state, "stale")
        self.assertEqual(self.build(snapshot_state="partial").state, "partial")
        self.assertEqual(self.build(recovery_retry=True).recovery, "retry")
        self.assertEqual(self.build(recovery_retry=True, recovery_reconcile=True).recovery, "reconcile")

    def test_invalid_input_or_forged_private_dtos_fail_closed_without_leakage(self):
        canaries = ("SYNTHETIC_PRIVATE_PATH", "a" * 64, "SYNTHETIC_PRIVATE_ID")
        for field, forged in (
            ("host", HostAssessment("ready", canaries[0], True, 2, 1, 2, None)),
            ("host", HostAssessment("ready", "HOST_READY_STABLE", True, 3, 1, 2, None)),
            ("host", HostAssessment("stale", "HOST_OBSERVATION_STALE", True, 2, 1, 2, None)),
            ("host", HostAssessment(canaries[2], "HOST_READY_STABLE", True, 2, 1, 2, None)),
            ("catch_up", CatchUpAssessment("within_grace", canaries[0], 1, 1, 0, 0)),
            ("catch_up", CatchUpAssessment("within_grace", "CATCH_UP_WITHIN_GRACE", 2, 1, 0, 0)),
            ("catch_up", CatchUpAssessment("missed", "CATCH_UP_COALESCED", 1, 0, 1, 0)),
            ("loop", LoopAssessment("warning", canaries[2], True)),
            ("loop", LoopAssessment("warning", "LOOP_NO_PROGRESS_THRESHOLD_REACHED", False)),
            ("loop", LoopAssessment("neutral", "LOOP_BOTH_THRESHOLDS_REACHED", False)),
        ):
            with self.subTest(field=field, forged=forged):
                result = self.build(**{field: forged})
                rendered = json.dumps(result.as_dict(), sort_keys=True)
                self.assertEqual((result.state, result.reason), ("unavailable", "SUMMARY_INPUT_INVALID"))
                for canary in canaries:
                    self.assertNotIn(canary, rendered)
        invalid = self.build(snapshot_state="fresh")
        self.assertEqual((invalid.state, invalid.reason), ("unavailable", "SUMMARY_INPUT_INVALID"))
        impossible = self.build(scheduler_active=False, provider_active=True)
        self.assertEqual((impossible.state, impossible.reason), ("unavailable", "SUMMARY_INPUT_INVALID"))

    def test_summary_and_nested_dtos_are_immutable(self):
        result = self.build()
        with self.assertRaises(FrozenInstanceError):
            result.recovery = "unknown"
        with self.assertRaises(FrozenInstanceError):
            result.loop.should_dispatch = True


if __name__ == "__main__":
    unittest.main()
