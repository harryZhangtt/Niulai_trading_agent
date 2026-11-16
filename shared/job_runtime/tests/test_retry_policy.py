from datetime import datetime, timedelta, timezone
import math
import unittest

from shared.job_runtime.provider_contract import FailureKind, ProviderResultV1
from shared.job_runtime.retry_policy import (
    RetryPolicyError, RetryPolicyV2, decide_retry, deterministic_full_jitter,
    parse_retry_after, validate_retry_policy,
)


NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
POLICY = RetryPolicyV2(max_attempts=4, base_delay_seconds=2, max_delay_seconds=30,
                       deadline_seconds=120)


def result(**changes):
    values = dict(provider="codex_cli", operation_id="slot/op", phase="connecting",
                  submission="not_submitted", terminal_proof="absent", status="retryable",
                  code="MODEL_TRANSIENT_FAILURE", failure_kind="connection")
    return ProviderResultV1(**(values | changes))


class RetryPolicyTests(unittest.TestCase):
    def test_v2_and_legacy_policy_validation_and_fingerprint(self):
        v2 = validate_retry_policy({"version": 2, "max_attempts": 4, "base_delay_seconds": 2,
                                    "max_delay_seconds": 30, "deadline_seconds": 120})
        legacy = validate_retry_policy({"max_retries": 3, "initial_delay_seconds": 2,
                                        "max_delay_seconds": 30, "deadline_seconds": 120})
        self.assertEqual(v2, legacy)
        self.assertEqual(v2.fingerprint, "e0b51c6792d8688d5a49d1f6dfb309ce46f303537b16437acaf2e9927418b6a6")
        for bad in ({}, {"version": 3},
                    {"version": True, "max_attempts": 2, "base_delay_seconds": 1, "max_delay_seconds": 2},
                    {"version": 2.0, "max_attempts": 2, "base_delay_seconds": 1, "max_delay_seconds": 2},
                    {"version": "2", "max_attempts": 2, "base_delay_seconds": 1, "max_delay_seconds": 2},
                    {"version": 2, "max_attempts": 0,
                    "base_delay_seconds": 1, "max_delay_seconds": 2},
                    {"max_attempts": 2, "max_retries": 1, "base_delay_seconds": 1,
                     "max_delay_seconds": 2},
                    {"max_attempts": 2, "base_delay_seconds": math.inf, "max_delay_seconds": 2}):
            with self.subTest(bad=bad), self.assertRaises(RetryPolicyError):
                validate_retry_policy(bad)

    def test_jitter_vectors_and_restart_determinism(self):
        vectors = [deterministic_full_jitter(slot_id="slot-A", attempt=n, policy=POLICY)
                   for n in (1, 2, 3, 4)]
        self.assertEqual([round(value, 12) for value in vectors],
                         [1.552299895824, 0.225630553351, 2.81650249565, 4.626889964859])
        recreated = RetryPolicyV2(4, 2, 30, 120)
        self.assertEqual(vectors, [deterministic_full_jitter(slot_id="slot-A", attempt=n,
                                                              policy=recreated) for n in (1, 2, 3, 4)])
        self.assertNotEqual(vectors[0], deterministic_full_jitter(slot_id="slot-B", attempt=1, policy=POLICY))
        self.assertTrue(0 <= vectors[0] < 2)

    def test_parse_retry_after_all_typed_forms(self):
        expected = NOW + timedelta(seconds=15)
        self.assertEqual(parse_retry_after(15000, "retry-after-ms", now=NOW), expected)
        self.assertEqual(parse_retry_after("15", "retry-after-seconds", now=NOW), expected)
        self.assertEqual(parse_retry_after("Thu, 05 Nov 2026 12:00:15 GMT", "http-date", now=NOW), expected)
        self.assertEqual(parse_retry_after("2026-11-05T12:00:15Z", "typed-timestamp", now=NOW), expected)
        self.assertEqual(parse_retry_after(expected, "typed-timestamp", now=NOW), expected)

    def test_retry_after_rejects_negative_nonfinite_malformed_naive_and_past(self):
        cases = [(-1, "retry-after-seconds"), (math.inf, "retry-after-seconds"),
                 (1e300, "retry-after-seconds"), (1e300, "retry-after-ms"),
                 ("NaN", "retry-after-seconds"), ("not-a-date", "http-date"),
                 ("Fri, 31 Dec 9999 23:59:59 GMT", "http-date"),
                 (datetime(9999, 12, 31, tzinfo=timezone.utc), "typed-timestamp"),
                 (datetime(2026, 1, 1), "typed-timestamp"),
                 (NOW - timedelta(seconds=2), "typed-timestamp")]
        for value, source in cases:
            with self.subTest(value=value, source=source), self.assertRaisesRegex(
                    RetryPolicyError, "RETRY_AFTER_(INVALID|PAST)"):
                parse_retry_after(value, source, now=NOW)
        self.assertEqual(parse_retry_after(NOW - timedelta(milliseconds=500), "typed-timestamp", now=NOW), NOW)

    def test_decision_truth_table(self):
        success = result(phase="terminal", submission="definitely_submitted", terminal_proof="verified",
                         status="succeeded", code="PROVIDER_SUCCEEDED", failure_kind="none")
        failed = result(phase="terminal", submission="not_submitted", terminal_proof="verified",
                        status="failed", code="PROVIDER_FAILED", failure_kind="provider")
        unknown = result(phase="streaming", submission="possibly_submitted", status="unknown",
                         code="PROVIDER_OUTCOME_UNKNOWN", failure_kind="timeout")
        self.assertEqual(decide_retry(success, POLICY, slot_id="s", attempt=1, now=NOW).disposition, "succeeded")
        self.assertEqual(decide_retry(failed, POLICY, slot_id="s", attempt=1, now=NOW).disposition, "terminal_failed")
        self.assertEqual(decide_retry(unknown, POLICY, slot_id="s", attempt=1, now=NOW).disposition, "unknown")
        decision = decide_retry(result(), POLICY, slot_id="s", attempt=1, now=NOW)
        self.assertEqual(decision.disposition, "retry")
        self.assertEqual(decision.selected_next_at, decision.persistable_next_at)

    def test_provider_false_permanent_and_http_rules(self):
        # Contract validation itself rejects retryable + explicit false.
        for code in ("MODEL_SOCKET_INVALID", "UNIX_SOCKET_INVALID", "MODEL_PATH_INVALID",
                     "LOCAL_CONFIGURATION_INVALID"):
            decision = decide_retry(result(code=code), POLICY, slot_id="s", attempt=1, now=NOW)
            self.assertEqual((decision.disposition, decision.reason),
                             ("terminal_failed", "PERMANENT_LOCAL_FAILURE"))
        ordinary = decide_retry(result(failure_kind="http", http_status=400), POLICY,
                                slot_id="s", attempt=1, now=NOW)
        self.assertEqual(ordinary.reason, "HTTP_STATUS_NOT_RETRYABLE")
        explicit = decide_retry(result(failure_kind="http", http_status=400, provider_should_retry=True), POLICY,
                                slot_id="s", attempt=1, now=NOW)
        self.assertEqual(explicit.disposition, "retry")
        for status in (408, 409, 429, 500, 529, 599):
            self.assertEqual(decide_retry(result(failure_kind="http", http_status=status), POLICY,
                                          slot_id="s", attempt=1, now=NOW).disposition, "retry")

    def test_quota_exhausted_is_terminal_while_429_retry_after_waits(self):
        quota = result(
            status="failed", code="MODEL_QUOTA_EXHAUSTED",
            failure_kind="quota_exhausted", provider_should_retry=False)
        quota_decision = decide_retry(
            quota, POLICY, slot_id="s", attempt=1, now=NOW)
        self.assertEqual(quota.failure_kind, FailureKind.QUOTA_EXHAUSTED)
        self.assertEqual((quota_decision.disposition, quota_decision.reason,
                          quota_decision.delay_seconds),
                         ("terminal_failed", "PROVIDER_QUOTA_EXHAUSTED", None))

        wait = NOW + timedelta(seconds=15)
        rate_limit = result(
            code="CODEX_HTTP_RETRY_CANDIDATE", failure_kind="http",
            http_status=429, provider_should_retry=True, retry_after_at=wait,
            retry_after_source="retry-after-seconds")
        rate_limit_decision = decide_retry(
            rate_limit, POLICY, slot_id="s", attempt=1, now=NOW)
        self.assertEqual(rate_limit.failure_kind, FailureKind.HTTP)
        self.assertEqual(rate_limit_decision.disposition, "retry")
        self.assertEqual(rate_limit_decision.selected_next_at, wait)

    def test_provider_wait_never_shortened_and_deadlines_enforced(self):
        wait = NOW + timedelta(seconds=20)
        delayed = result(retry_after_at=wait, retry_after_source="typed-timestamp")
        decision = decide_retry(delayed, POLICY, slot_id="s", attempt=1, now=NOW)
        self.assertEqual(decision.selected_next_at, wait)
        excessive = result(retry_after_at=NOW + timedelta(seconds=31), retry_after_source="typed-timestamp")
        self.assertEqual(decide_retry(excessive, POLICY, slot_id="s", attempt=1, now=NOW).reason,
                         "PROVIDER_WAIT_EXCEEDS_MAX")
        self.assertEqual(decide_retry(delayed, POLICY, slot_id="s", attempt=1, now=NOW,
                                      deadline=NOW + timedelta(seconds=10)).reason,
                         "RETRY_DEADLINE_EXCEEDED")
        self.assertEqual(decide_retry(result(), POLICY, slot_id="s", attempt=4, now=NOW).reason,
                         "ATTEMPTS_EXHAUSTED")

    def test_immutable_decision_and_no_global_time_dependency(self):
        first = decide_retry(result(), POLICY, slot_id="slot", attempt=2, now=NOW)
        second = decide_retry(result(), POLICY, slot_id="slot", attempt=2, now=NOW)
        self.assertEqual(first, second)
        with self.assertRaises((AttributeError, TypeError)):
            first.reason = "changed"


if __name__ == "__main__":
    unittest.main()
