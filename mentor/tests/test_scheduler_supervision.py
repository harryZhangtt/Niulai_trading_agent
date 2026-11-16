from __future__ import annotations

from dataclasses import replace
import unittest

from mentor.scheduler import supervision as scheduler_supervision
from mentor.scheduler.supervision import (
    BudgetExhausted,
    ComparisonDesign,
    EvidenceSnapshot,
    FailureKind,
    FrozenCriteria,
    HoldoutRole,
    LoopVerdict,
    ProgressVerdict,
    PromotionVerdict,
    ProtectedHoldout,
    SupervisionBudget,
    TrustedEvaluatorAssessment,
    VerifierCriterionObservations,
    canonical_action_fingerprint,
    check_matched_comparison,
    classify_progress,
    decide_loop,
    decide_promotion,
    decide_verified_promotion,
)


class FingerprintAndProgressTests(unittest.TestCase):
    def test_canonical_action_fingerprint_ignores_mapping_and_set_order(self) -> None:
        first = {"tool": "search", "args": {"terms": {"beta", "alpha"}, "limit": 3}}
        second = {"args": {"limit": 3, "terms": {"alpha", "beta"}}, "tool": "search"}

        self.assertEqual(canonical_action_fingerprint(first), canonical_action_fingerprint(second))
        self.assertNotEqual(
            canonical_action_fingerprint({"steps": ["a", "b"]}),
            canonical_action_fingerprint({"steps": ["b", "a"]}),
        )

    def test_healthy_progress_requires_verified_evidence_delta(self) -> None:
        before = EvidenceSnapshot()
        after = EvidenceSnapshot(
            criteria_verified={"schema"},
            validated_artifacts={"artifact:run-17"},
        )

        assessment = classify_progress(before, after, {"run": "validator"})

        self.assertEqual(assessment.verdict, ProgressVerdict.MEANINGFUL)
        self.assertEqual(assessment.delta.identifiers, {"schema", "artifact:run-17"})

    def test_duplicate_unchanged_action_is_not_progress(self) -> None:
        evidence = EvidenceSnapshot(criteria_verified={"schema"})
        action = {"run": "same-validator", "input": "same-artifact"}
        fingerprint = canonical_action_fingerprint(action)

        assessment = classify_progress(
            evidence,
            evidence,
            action,
            previous_action_fingerprint=fingerprint,
        )

        self.assertEqual(assessment.verdict, ProgressVerdict.NO_PROGRESS)
        self.assertTrue(assessment.repeated_action)
        self.assertIn("no new evidence", assessment.reason)

    def test_narration_and_tool_call_are_activity_not_progress(self) -> None:
        before = EvidenceSnapshot()
        apparent_after = EvidenceSnapshot(criteria_verified={"claimed-only"})

        for activity_kind in ("narration", "plan", "tool_call"):
            with self.subTest(activity_kind=activity_kind):
                assessment = classify_progress(
                    before,
                    apparent_after,
                    {"activity": activity_kind},
                    activity_kind=activity_kind,
                )
                self.assertEqual(assessment.verdict, ProgressVerdict.NO_PROGRESS)

    def test_transient_error_with_new_evidence_continues(self) -> None:
        action = {"query": "provider", "variant": 1}
        fingerprint = canonical_action_fingerprint(action)
        progress = classify_progress(
            EvidenceSnapshot(),
            EvidenceSnapshot(narrowed_root_causes={"provider:rate-limit-boundary"}),
            action,
            previous_action_fingerprint=fingerprint,
        )

        decision = decide_loop(
            current_action_fingerprint=fingerprint,
            previous_action_fingerprint=fingerprint,
            evidence_changed=progress.delta.changed,
            hypothesis_changed=False,
            failure_kind=FailureKind.TRANSIENT,
            error_signature="429",
            previous_error_signature="429",
            budget=SupervisionBudget(2, 2),
        )

        self.assertEqual(progress.verdict, ProgressVerdict.MEANINGFUL)
        self.assertEqual(decision.verdict, LoopVerdict.CONTINUE)

    def test_permanent_repeated_error_requires_changed_approach(self) -> None:
        fingerprint = canonical_action_fingerprint({"tool": "unsupported-operation"})

        decision = decide_loop(
            current_action_fingerprint=fingerprint,
            previous_action_fingerprint=fingerprint,
            evidence_changed=False,
            hypothesis_changed=False,
            failure_kind=FailureKind.PERMANENT,
            error_signature="operation-not-supported",
            previous_error_signature="operation-not-supported",
            budget=SupervisionBudget(2, 1),
        )

        self.assertEqual(decision.verdict, LoopVerdict.CHANGE_APPROACH)
        self.assertFalse(decision.architecture_failure_proven)


class BudgetAndHoldoutTests(unittest.TestCase):
    def test_intervention_exhaustion_is_bounded_and_not_architecture_proof(self) -> None:
        budget = SupervisionBudget(intervention_limit=1, variant_limit=1)
        exhausted = budget.consume_intervention()
        with self.assertRaises(BudgetExhausted):
            exhausted.consume_intervention()

        fingerprint = canonical_action_fingerprint({"retry": "unchanged"})
        decision = decide_loop(
            current_action_fingerprint=fingerprint,
            previous_action_fingerprint=fingerprint,
            evidence_changed=False,
            hypothesis_changed=False,
            failure_kind=FailureKind.UNKNOWN,
            error_signature="same",
            previous_error_signature="same",
            budget=exhausted,
        )
        self.assertEqual(decision.verdict, LoopVerdict.BUDGET_EXHAUSTED)
        self.assertFalse(decision.architecture_failure_proven)

    def test_untouched_holdout_is_detectable_and_evaluator_only(self) -> None:
        holdout = ProtectedHoldout("holdout:v1")
        self.assertTrue(holdout.untouched)

        decision = holdout.request_access(
            actor="independent-evaluator",
            role=HoldoutRole.EVALUATOR,
            purpose="promotion_evaluation",
        )

        self.assertTrue(decision.allowed)
        self.assertFalse(decision.holdout.untouched)
        self.assertTrue(decision.holdout.integrity_preserved)

    def test_unauthorized_holdout_access_is_denied_and_recorded(self) -> None:
        holdout = ProtectedHoldout("holdout:v1")

        decision = holdout.request_access(
            actor="candidate-developer",
            role=HoldoutRole.DEVELOPER,
            purpose="tuning",
        )

        self.assertFalse(decision.allowed)
        self.assertTrue(decision.holdout.untouched)
        self.assertFalse(decision.holdout.integrity_preserved)
        self.assertEqual(len(decision.holdout.unauthorized_attempts), 1)


class ComparisonAndPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.criteria = FrozenCriteria(
            acceptance_sha256="a" * 64,
            required={"quality", "cost", "no_critical_error"},
            critical={"no_critical_error"},
            plan_sha256="c" * 64,
        )
        self.complete_comparison = check_matched_comparison(
            ComparisonDesign(
                candidate_cases=("case-a", "case-b"),
                baseline_cases=("case-a", "case-b"),
                candidate_budget={"tokens": 1000, "calls": 4},
                baseline_budget={"calls": 4, "tokens": 1000},
                required_ablations={"retrieval"},
                observed_ablations={"retrieval"},
            )
        )

    def forged_assessment(self) -> TrustedEvaluatorAssessment:
        assessment = object.__new__(TrustedEvaluatorAssessment)
        values = {
            "artifact_sha256": "d" * 64, "evaluator_id": "evaluator-1",
            "work_order_id": "wo-1", "plan_sha256": self.criteria.plan_sha256,
            "acceptance_sha256": self.criteria.acceptance_sha256, "cycle_id": "cycle-1",
            "candidate_id": "candidate-1", "candidate_source_path": None,
            "candidate_source_sha256": None, "comparison": self.complete_comparison,
            "holdout_integrity": True, "_durable_proof": object(),
        }
        for name, value in values.items():
            object.__setattr__(assessment, name, value)
        return assessment

    def test_invalid_or_duplicate_comparison_inputs_fail_closed(self) -> None:
        comparison = check_matched_comparison(
            ComparisonDesign(
                candidate_cases=("case-a", "case-a"),
                baseline_cases=("case-a", "case-a"),
                candidate_budget={"tokens": True},
                baseline_budget={"tokens": True},
            )
        )
        self.assertFalse(comparison.complete)
        self.assertIn("candidate comparison inputs are invalid", comparison.issues)
        self.assertIn("baseline comparison inputs are invalid", comparison.issues)

    def test_missing_ablation_blocks_acceptance_as_inconclusive(self) -> None:
        comparison = check_matched_comparison(
            ComparisonDesign(
                candidate_cases=("case-a",),
                baseline_cases=("case-a",),
                candidate_budget={"tokens": 100},
                baseline_budget={"tokens": 100},
                required_ablations={"retrieval", "ranking"},
                observed_ablations={"retrieval"},
            )
        )
        decision = decide_promotion(
            criteria=self.criteria,
            observations={criterion: True for criterion in self.criteria.required},
            comparison=comparison,
            holdout_integrity=True,
        )

        self.assertFalse(comparison.complete)
        self.assertEqual(decision.verdict, PromotionVerdict.INCONCLUSIVE)
        self.assertEqual(decision.reasons, ("untrusted_observations",))

    def test_attempted_criterion_softening_rejects(self) -> None:
        decision = decide_promotion(
            criteria=self.criteria,
            observations={"quality": True, "cost": True, "no_critical_error": None},
            comparison=self.complete_comparison,
            holdout_integrity=True,
            proposed_required_criteria={"quality", "cost"},
        )

        self.assertEqual(decision.verdict, PromotionVerdict.INCONCLUSIVE)
        self.assertEqual(decision.reasons, ("untrusted_observations",))

    def test_fabricated_evaluator_assessment_constructor_rejects(self) -> None:
        with self.assertRaisesRegex(ValueError, "not loaded from durable state"):
            TrustedEvaluatorAssessment(
                "d" * 64, "evaluator-1", "wo-1", "c" * 64, "a" * 64,
                "cycle-1", "candidate-1", "source.py", "e" * 64,
                self.complete_comparison, True, object(),
            )

    def test_imported_token_factory_and_replace_cannot_bypass_state_lookup(self) -> None:
        observations = VerifierCriterionObservations._from_durable_state(
            work_order_id="wo-1", acceptance_sha256="a" * 64, cycle_id="cycle-1",
            candidate_id="candidate-1", artifact_sha256="b" * 64,
            plan_sha256="c" * 64, candidate_source_path="source.py",
            candidate_source_sha256="e" * 64,
            observations=tuple((item, True) for item in sorted(self.criteria.required)),
        )
        assessment = TrustedEvaluatorAssessment(
            "d" * 64, "evaluator-1", "wo-1", "c" * 64, "a" * 64,
            "cycle-1", "candidate-1", "source.py", "e" * 64,
            self.complete_comparison, True, scheduler_supervision._DURABLE_VERIFIER_PROOF,
        )
        decision = decide_verified_promotion(
            criteria=self.criteria, verifier_observations=replace(observations),
            evaluator_assessment=replace(assessment), work_order_id="wo-1",
            candidate_id="candidate-1", cycle_id="cycle-1",
        )
        self.assertEqual(decision.verdict, PromotionVerdict.INCONCLUSIVE)
        self.assertEqual(decision.reasons, ("state_lookup_required",))
        core = scheduler_supervision._decide_promotion_core(
            criteria=self.criteria,
            observations={item: True for item in self.criteria.required},
            comparison=self.complete_comparison,
            holdout_integrity=True,
        )
        self.assertEqual(core.verdict, PromotionVerdict.INCONCLUSIVE)
        self.assertEqual(core.reasons, ("state_lookup_required",))

    def test_fabricated_verified_promotion_rejects_without_durable_lookup(self) -> None:
        verified = VerifierCriterionObservations(
            work_order_id="wo-1",
            acceptance_sha256=self.criteria.acceptance_sha256,
            cycle_id="cycle-1",
            candidate_id="candidate-1",
            artifact_sha256="b" * 64,
            observations=tuple((criterion, True) for criterion in sorted(self.criteria.required)),
        )
        accepted = decide_verified_promotion(
            criteria=self.criteria,
            verifier_observations=verified,
            evaluator_assessment=self.forged_assessment(),
            work_order_id="wo-1",
            candidate_id="candidate-1",
            cycle_id="cycle-1",
        )
        drifted = decide_verified_promotion(
            criteria=self.criteria,
            verifier_observations=verified,
            evaluator_assessment=self.forged_assessment(),
            work_order_id="wo-1",
            candidate_id="candidate-2",
            cycle_id="cycle-1",
        )
        softened = decide_verified_promotion(
            criteria=self.criteria,
            verifier_observations=verified,
            evaluator_assessment=self.forged_assessment(),
            work_order_id="wo-1",
            candidate_id="candidate-1",
            cycle_id="cycle-1",
            proposed_required_criteria={"quality", "cost"},
        )

        for decision in (accepted, drifted, softened):
            self.assertEqual(decision.verdict, PromotionVerdict.INCONCLUSIVE)
            self.assertEqual(decision.reasons, ("state_lookup_required",))

    def test_verified_observations_reject_duplicates_and_incomplete_coverage(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            VerifierCriterionObservations(
                "wo", "a" * 64, "cycle", "candidate", "b" * 64,
                (("quality", True), ("quality", False)),
            )
        incomplete = VerifierCriterionObservations(
            "wo", "a" * 64, "cycle", "candidate", "b" * 64,
            (("quality", True),),
        )
        decision = decide_verified_promotion(
            criteria=self.criteria,
            verifier_observations=incomplete,
            evaluator_assessment=self.forged_assessment(),
            work_order_id="wo",
            candidate_id="candidate",
            cycle_id="cycle",
        )
        self.assertEqual(decision.verdict, PromotionVerdict.INCONCLUSIVE)
        self.assertEqual(decision.reasons, ("state_lookup_required",))

    def test_promotion_verdicts_distinguish_pass_failure_and_missing_evidence(self) -> None:
        accepted = decide_promotion(
            criteria=self.criteria,
            observations={criterion: True for criterion in self.criteria.required},
            comparison=self.complete_comparison,
            holdout_integrity=True,
        )
        rejected = decide_promotion(
            criteria=self.criteria,
            observations={"quality": None, "cost": True, "no_critical_error": False},
            comparison=self.complete_comparison,
            holdout_integrity=True,
        )
        inconclusive = decide_promotion(
            criteria=self.criteria,
            observations={"quality": True, "cost": None, "no_critical_error": True},
            comparison=self.complete_comparison,
            holdout_integrity=True,
        )

        for decision in (accepted, rejected, inconclusive):
            self.assertEqual(decision.verdict, PromotionVerdict.INCONCLUSIVE)
            self.assertEqual(decision.reasons, ("untrusted_observations",))
            self.assertEqual(decision.acceptance_sha256, self.criteria.acceptance_sha256)


if __name__ == "__main__":
    unittest.main()
