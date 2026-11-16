from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import experiment
from probability_guard import EventType, GuardError, MutableClock, ProbabilityAuthority, canonical, sha256


class GuardCase(unittest.TestCase):
    def setUp(self) -> None:
        self.authority, self.clock = experiment.make_authority()
        self.identity = experiment.case_identity()

    def issue(self):
        return self.authority.issue(identity=self.identity, forecast_payload=experiment.FORECAST,
                                    maturity_at=experiment.MATURITY_AT,
                                    producer_id="producer-forecast")

    def mature(self):
        issue = self.issue()
        self.clock.set(experiment.MATURITY_AT)
        return issue, self.authority.record_maturity(issue)

    def score(self):
        issue, maturity = self.mature()
        grant = self.authority.grant_protected_access(maturity, grantee_id="evidence-collector")
        outcome, access = self.authority.access_protected_outcome(
            grant, principal_id="evidence-collector")
        self.assertEqual(experiment.PROTECTED_OUTCOME, outcome)
        return issue, maturity, grant, access, self.authority.score(
            access, scorer_id="score-authority")

    def reviews(self):
        *prefix, score = self.score()
        reviews = [
            self.authority.review(score, role="data", reviewer_id="reviewer-data"),
            self.authority.review(score, role="statistics", reviewer_id="reviewer-statistics"),
            self.authority.review(score, role="methodology", reviewer_id="reviewer-methodology"),
        ]
        return (*prefix, score, reviews)

    def assert_rejected(self, code, action):
        with self.assertRaisesRegex(GuardError, f"^{code}$"):
            action()

    def test_exact_identity_rejects_missing_and_extra_fields(self):
        missing = dict(self.identity)
        missing.pop("holdout_id")
        self.assert_rejected("IDENTITY_SCHEMA", lambda: self.authority.issue(
            identity=missing, forecast_payload=experiment.FORECAST,
            maturity_at=experiment.MATURITY_AT, producer_id="producer-forecast"))
        extra = {**self.identity, "unbound": "value"}
        self.assert_rejected("IDENTITY_SCHEMA", lambda: self.authority.issue(
            identity=extra, forecast_payload=experiment.FORECAST,
            maturity_at=experiment.MATURITY_AT, producer_id="producer-forecast"))

    def test_forecast_hash_is_exactly_bound(self):
        identity = dict(self.identity)
        identity["forecast_sha256"] = hashlib.sha256(b"other").hexdigest()
        self.assert_rejected("FORECAST_HASH_MISMATCH", lambda: self.authority.issue(
            identity=identity, forecast_payload=experiment.FORECAST,
            maturity_at=experiment.MATURITY_AT, producer_id="producer-forecast"))

    def test_issue_must_be_prospective(self):
        self.clock.set(experiment.MATURITY_AT)
        self.assert_rejected("ISSUE_NOT_PROSPECTIVE", self.issue)

    def test_issue_cannot_be_replayed(self):
        self.issue()
        self.assert_rejected("ISSUE_REPLAY", self.issue)

    def test_maturity_and_outcome_access_are_ordered(self):
        issue = self.issue()
        self.assert_rejected("OUTCOME_BEFORE_MATURITY",
                             lambda: self.authority.record_maturity(issue))
        self.assert_rejected("RECEIPT_WRONG_TYPE", lambda: self.authority.access_protected_outcome(
            issue, principal_id="producer-forecast"))
        self.clock.set(experiment.MATURITY_AT)
        maturity = self.authority.record_maturity(issue)
        self.assert_rejected("PROTECTED_ACCESS_DENIED", lambda: self.authority.grant_protected_access(
            maturity, grantee_id="producer-forecast"))

    def test_explicit_grant_and_access_are_single_use(self):
        _, maturity = self.mature()
        grant = self.authority.grant_protected_access(maturity, grantee_id="evidence-collector")
        self.assert_rejected("ACCESS_GRANT_REPLAY", lambda: self.authority.grant_protected_access(
            maturity, grantee_id="evidence-collector"))
        _, access = self.authority.access_protected_outcome(
            grant, principal_id="evidence-collector")
        self.assertEqual("protected_outcome_access", access["event_type"])
        self.assert_rejected("PROTECTED_ACCESS_DUPLICATE",
                             lambda: self.authority.access_protected_outcome(
                                 grant, principal_id="evidence-collector"))

    def test_outcome_and_score_bind_forecast_and_outcome_hashes(self):
        *_, access, score = self.score()
        self.assertEqual(self.identity["forecast_sha256"], score["payload"]["forecast_sha256"])
        self.assertEqual(access["payload"]["outcome_sha256"], score["payload"]["outcome_sha256"])
        self.assertAlmostEqual(0.140625, score["payload"]["score_value"])
        self.assert_rejected("SCORE_REPLAY",
                             lambda: self.authority.score(access, scorer_id="score-authority"))

    def test_three_review_roles_and_distinct_independent_principals(self):
        *_, score = self.score()
        self.authority.review(score, role="data", reviewer_id="reviewer-data")
        self.assert_rejected("REVIEWER_NOT_DISTINCT", lambda: self.authority.review(
            score, role="statistics", reviewer_id="reviewer-data"))
        self.assert_rejected("REVIEWER_NOT_INDEPENDENT", lambda: self.authority.review(
            score, role="statistics", reviewer_id="producer-forecast"))
        self.assert_rejected("REVIEWER_NOT_INDEPENDENT", lambda: self.authority.review(
            score, role="statistics", reviewer_id="guard-operator"))
        self.assert_rejected("REVIEWER_NOT_INDEPENDENT", lambda: self.authority.review(
            score, role="statistics", reviewer_id="evidence-collector"))
        self.assert_rejected("REVIEW_NOT_APPROVED", lambda: self.authority.review(
            score, role="statistics", reviewer_id="reviewer-statistics", verdict="rejected"))

    def test_authorization_requires_complete_review_evidence(self):
        *_, score = self.score()
        one = self.authority.review(score, role="data", reviewer_id="reviewer-data")
        scope = {"source_target_id": self.identity["target_id"],
                 "destination_target_id": "tqqq.reset_loss",
                 "transport_policy_sha256": hashlib.sha256(b"transport").hexdigest()}
        self.assert_rejected("AUTHORIZATION_EVIDENCE_INCOMPLETE",
                             lambda: self.authority.authorize_transport([one], scope=scope))

    def test_transport_and_factor_authorization_bind_exact_scopes(self):
        *_, reviews = self.reviews()
        transport_scope = {"source_target_id": self.identity["target_id"],
                           "destination_target_id": "tqqq.reset_loss",
                           "transport_policy_sha256": hashlib.sha256(b"transport").hexdigest()}
        factor_scope = {"factor_id": "factor-01", "authorization_purpose": "combination_selection",
                        "use_scope_sha256": hashlib.sha256(b"use").hexdigest()}
        transport = self.authority.authorize_transport(reviews, scope=transport_scope)
        factor = self.authority.authorize_factor(reviews, scope=factor_scope)
        self.authority.verify_receipt(transport, expected_type=EventType.TRANSPORT_AUTHORIZATION,
                                      expected_identity=self.identity,
                                      expected_scope=transport_scope)
        self.authority.verify_receipt(factor, expected_type=EventType.FACTOR_AUTHORIZATION,
                                      expected_identity=self.identity, expected_scope=factor_scope)
        wrong = {**transport_scope, "destination_target_id": "spxl.reset_loss"}
        self.assert_rejected("RECEIPT_SCOPE_MISMATCH", lambda: self.authority.verify_receipt(
            transport, expected_scope=wrong))

    def test_cross_identity_reuse_fails_target_horizon_attempt_variant_holdout_and_forecast(self):
        *_, reviews = self.reviews()
        scope = {"source_target_id": self.identity["target_id"],
                 "destination_target_id": "tqqq.reset_loss",
                 "transport_policy_sha256": hashlib.sha256(b"transport").hexdigest()}
        receipt = self.authority.authorize_transport(reviews, scope=scope)
        mutations = {
            "target_id": "tqqq.reset_loss", "horizon_reset_days": 63,
            "attempt_id": "attempt-002", "variant_id": "variant-other",
            "holdout_id": "holdout-other", "forecast_sha256": hashlib.sha256(b"other").hexdigest(),
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                other = {**self.identity, field: value}
                self.assert_rejected("RECEIPT_SCOPE_MISMATCH",
                                     lambda other=other: self.authority.verify_receipt(
                                         receipt, expected_identity=other))

    def test_producer_public_sha_chain_and_backdate_fail_mac(self):
        issue = self.issue()
        for forged in (
            experiment.public_rehash(issue, payload_patch={"producer_id": "producer-forged"}),
            experiment.public_rehash(issue, occurred_at="2025-12-01T00:00:00Z"),
        ):
            with self.subTest(occurred_at=forged["occurred_at"]):
                with self.assertRaisesRegex(GuardError, "^RECEIPT_(STATE_MAC|MAC)$"):
                    self.authority.verify_receipt(forged)

    def test_state_head_or_historical_event_rewrite_fails(self):
        self.issue()
        snapshot = self.authority.public_snapshot()
        rewritten_head = copy.deepcopy(snapshot)
        rewritten_head["state_head"] = hashlib.sha256(b"rewrite").hexdigest()
        self.assert_rejected("SNAPSHOT_STATE_HEAD",
                             lambda: self.authority.validate_snapshot(rewritten_head))
        rewritten_event = copy.deepcopy(snapshot)
        rewritten_event["receipts"][0]["payload"]["producer_id"] = "producer-forged"
        self.assert_rejected("RECEIPT_EVENT_HASH",
                             lambda: self.authority.validate_snapshot(rewritten_event))

    def test_public_snapshot_contains_no_secret_or_outcome_bytes(self):
        self.issue()
        encoded = canonical(self.authority.public_snapshot())
        self.assertNotIn(experiment.SYNTHETIC_SECRET, encoded)
        self.assertNotIn(experiment.PROTECTED_OUTCOME, encoded)

    def test_producer_exec_subprocess_sees_no_parent_memory_or_files(self):
        self.issue()
        probe = experiment.producer_subprocess_probe(self.authority.public_snapshot())
        self.assertFalse(probe["secret_or_outcome_observed"])
        self.assertEqual([], probe["files"])
        self.assertEqual([], probe["sensitive_environment_names"])

    def test_wrong_process_pid_is_rejected(self):
        self.authority._owner_pid += 1
        self.assert_rejected("AUTHORITY_PROCESS_MISMATCH", self.authority.public_snapshot)

    def test_clock_cannot_rewind(self):
        self.assert_rejected("CLOCK_REWIND", lambda: self.clock.set("2026-01-01T00:00:00Z"))

    def test_nominal_event_chain_is_complete_and_valid(self):
        nominal, failures = experiment.execute()
        self.assertEqual([
            "issue", "maturity", "protected_access_grant", "protected_outcome_access", "score",
            "review_data", "review_statistics", "review_methodology",
            "transport_authorization", "factor_authorization",
        ], nominal["event_types"])
        self.assertEqual(10, nominal["event_count"])
        self.assertEqual(13, len(failures))

    def test_experiment_receipt_is_deterministic_and_self_hashed(self):
        first = experiment.build_receipt()
        second = experiment.build_receipt()
        self.assertEqual(first, second)
        claimed = first.pop("receipt_sha256")
        self.assertEqual(sha256(first), claimed)
        self.assertFalse(first["falsifier_triggered"])
        self.assertEqual("O2_NOT_FALSIFIED_IN_BOUNDED_EXPERIMENT", first["decision"])
        self.assertTrue(all(value is False for value in first["external_effects"].values()))


if __name__ == "__main__":
    unittest.main()
