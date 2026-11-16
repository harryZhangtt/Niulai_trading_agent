import copy
import json
from pathlib import Path
import unittest

from tuning.factor_mining.admission_policy import policy


POLICY_PATH = Path(__file__).resolve().parents[1] / "initial-confirmatory-policy.json"


class AdmissionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.value = policy.load_policy(POLICY_PATH)

    def test_tracked_policy_is_canonical_stable_and_deliberately_blocked(self):
        first = policy.digest(self.value)
        reordered = json.loads(json.dumps(self.value, sort_keys=True))
        self.assertEqual(first, policy.digest(reordered))
        self.assertRegex(first, r"^[a-f0-9]{64}$")
        self.assertEqual(self.value["status"], "draft_blocked")
        self.assertFalse(self.value["inventory"]["sealable"])
        self.assertEqual(self.value["inventory"]["blockers"], policy.BLOCKERS)
        for key, value in self.value["inventory"].items():
            if key not in {"sealable", "blockers"}:
                self.assertIsNone(value)
        self.assertFalse(self.value["publication"]["performance_allowed"])
        self.assertFalse(self.value["publication"]["ev_allowed"])
        self.assertFalse(self.value["publication"]["kelly_allowed"])

    def test_p0_authority_receipt_and_publication_prerequisites_are_explicit(self):
        required = {
            "canonical-ledger-authority-unimplemented": "canonical_authority_policy_sha256",
            "trusted-dataset-split-attestation-unimplemented": "dataset_attestation_policy_sha256",
            "guard-issued-runner-nonce-and-trusted-receipt-unimplemented": "runner_receipt_policy_sha256",
            "evaluator-derived-verdict-and-independent-receipt-unimplemented": "evaluator_receipt_policy_sha256",
            "authorization-bound-performance-publication-unimplemented": "publication_authorization_policy_sha256",
        }
        blockers = self.value["inventory"]["blockers"]
        for blocker, field in required.items():
            self.assertIn(blocker, blockers)
            self.assertIn(field, self.value["inventory"])
            self.assertIsNone(self.value["inventory"][field])
            changed = copy.deepcopy(self.value)
            changed["inventory"][field] = "a" * 64
            with self.subTest(field=field), self.assertRaises(policy.PolicyError):
                policy.validate_policy(changed)

    def test_duplicate_nonfinite_unknown_and_outcome_fields_fail(self):
        with self.assertRaisesRegex(policy.PolicyError, "DUPLICATE_KEY"):
            policy.loads_strict('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(policy.PolicyError, "NONFINITE"):
            policy.loads_strict('{"value":NaN}')
        for key, value in (("unknown", True), ("results", {}), ("performance", []),
                           ("verdict", "pass"), ("metrics", {})):
            changed = copy.deepcopy(self.value)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(policy.PolicyError):
                policy.validate_policy(changed)

    def test_policy_cannot_claim_sealed_runnable_or_resolved_inventory(self):
        cases = []
        status = copy.deepcopy(self.value); status["status"] = "sealed"; cases.append(status)
        sealable = copy.deepcopy(self.value); sealable["inventory"]["sealable"] = True; cases.append(sealable)
        no_blockers = copy.deepcopy(self.value); no_blockers["inventory"]["blockers"] = []; cases.append(no_blockers)
        fake_hash = copy.deepcopy(self.value); fake_hash["inventory"]["observation_set_sha256"] = "a" * 64; cases.append(fake_hash)
        for changed in cases:
            with self.subTest(change=changed), self.assertRaises(policy.PolicyError):
                policy.validate_policy(changed)

    def test_budgets_multiplicity_and_publication_cannot_be_weakened(self):
        mutations = [
            ("attempts", lambda value: value["budget"].update(pipeline_attempts=2)),
            ("variants", lambda value: value["budget"].update(confirmatory_variants=2)),
            ("looks", lambda value: value["budget"].update(protected_looks=2)),
            ("alpha", lambda value: value["multiplicity"].update(alpha=0.10)),
            ("method", lambda value: value["multiplicity"].update(method="uncorrected")),
            ("ev", lambda value: value["publication"].update(ev_allowed=True)),
            ("kelly", lambda value: value["publication"].update(kelly_allowed=True)),
            ("performance", lambda value: value["publication"].update(performance_allowed=True)),
        ]
        for name, mutate in mutations:
            changed = copy.deepcopy(self.value); mutate(changed)
            with self.subTest(name=name), self.assertRaises(policy.PolicyError):
                policy.validate_policy(changed)

    def test_decision_rules_controls_sensitivities_and_triggers_are_complete(self):
        mutations = [
            ("pass-threshold", lambda value: value["decision"]["pass"].update(point_estimate_gt=-1.0)),
            ("protected-count", lambda value: value["decision"]["pass"].update(protected_origins_per_asset=1)),
            ("retry", lambda value: value["decision"]["inconclusive"].update(retry_same_population_allowed=True)),
            ("drop-control", lambda value: value["controls"].pop()),
            ("promoting-control", lambda value: value["controls"][0].update(can_promote=True)),
            ("drop-sensitivity", lambda value: value["sensitivities"].pop()),
            ("weaken-trigger", lambda value: value["quarantine_triggers"][0].update(threshold=1)),
            ("drop-trigger", lambda value: value["quarantine_triggers"].pop()),
        ]
        for name, mutate in mutations:
            changed = copy.deepcopy(self.value); mutate(changed)
            with self.subTest(name=name), self.assertRaises(policy.PolicyError):
                policy.validate_policy(changed)

    def test_frozen_values_are_recursively_type_exact(self):
        mutations = [
            ("schema-bool", lambda value: value.update(schema_version=True)),
            ("version-bool", lambda value: value.update(version=True)),
            ("degrees-bool", lambda value: value["signal"].update(max_degrees_of_freedom=True)),
            ("budget-bool", lambda value: value["budget"].update(candidate_specifications=True)),
            ("trigger-zero-bool", lambda value: value["quarantine_triggers"][0].update(threshold=False)),
            ("decision-zero-bool", lambda value: value["decision"]["pass"].update(point_estimate_gt=False)),
            ("decision-zero-int", lambda value: value["decision"]["pass"].update(point_estimate_gt=0)),
            ("exposure-zero-int", lambda value: value["portfolio"].update(inactive_exposure=0)),
            ("lookback-float", lambda value: value["signal"].update(lookback_sessions=63.0)),
        ]
        for name, mutate in mutations:
            changed = copy.deepcopy(self.value); mutate(changed)
            with self.subTest(name=name), self.assertRaises(policy.PolicyError):
                policy.validate_policy(changed)

    def test_signal_execution_and_inference_are_not_tunable(self):
        mutations = [
            ("lookback", lambda value: value["signal"].update(lookback_sessions=64)),
            ("weights", lambda value: value["signal"].update(learned_weights=True)),
            ("same-bar", lambda value: value["execution"].update(same_bar_execution_allowed=True)),
            ("cost", lambda value: value["execution"].update(cost_bps_one_way=0)),
            ("purge", lambda value: value["evaluation"].update(purge_sessions=0)),
            ("bootstrap", lambda value: value["evaluation"]["uncertainty"].update(replicates=1000)),
        ]
        for name, mutate in mutations:
            changed = copy.deepcopy(self.value); mutate(changed)
            with self.subTest(name=name), self.assertRaises(policy.PolicyError):
                policy.validate_policy(changed)


if __name__ == "__main__":
    unittest.main()
