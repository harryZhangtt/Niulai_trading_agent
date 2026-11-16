import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tuning.factor_mining import guard


ROOT = Path(__file__).resolve().parents[3]
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def protocol(*, experiment_id="rebound-alpha", version=1, mode="confirmatory",
             parent=None, protected_sha=SHA_D):
    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "version": version,
        "mode": mode,
        "parent_protocol_sha256": parent,
        "hypothesis": "The frozen transformed factor adds net return versus matched exposure.",
        "economic_rationale": "The transformation represents improving financing conditions without counting correlated variants twice.",
        "data": {
            "dataset_id": "point-in-time-us-index",
            "snapshot_sha256": SHA_A,
            "availability_policy": "Use release timestamps and trade only after information availability.",
            "splits": [
                {"name": "development", "role": "development", "start": "2000-01-01", "end": "2015-01-01", "fingerprint_sha256": SHA_A},
                {"name": "validation", "role": "validation", "start": "2015-01-01", "end": "2022-01-01", "fingerprint_sha256": SHA_B},
                {"name": "protected", "role": "protected", "start": "2022-01-01", "end": "2025-01-01", "fingerprint_sha256": protected_sha},
            ],
        },
        "factors": [
            {"id": "real-rate-change", "family": "rates", "transformation": "63-session difference with release lag", "max_degrees_of_freedom": 2},
            {"id": "credit-contraction", "family": "credit", "transformation": "63-session proportional spread contraction with release lag", "max_degrees_of_freedom": 1},
        ],
        "model": {"type": "ridge", "hyperparameters": {"alphas": [1.0]}},
        "execution": {"signal_lag_sessions": 1, "rebalance": "monthly", "cost_bps": 5,
                      "cash_interest": "effective-fed-funds-next-day"},
        "evaluation": {"target": "forward-excess-return", "horizon_sessions": 126,
                       "purge_sessions": 126, "embargo_sessions": 21, "baseline": "matched-exposure"},
        "multiplicity": {"family_id": "rates-family-v1", "method": "holm-plus-spa", "alpha": 0.05, "max_variants": 2},
        "budget": {"max_attempts": 3, "max_variants": 2, "max_protected_uses": 1},
        "promotion_gate": [
            {"id": "recent-net-ev", "metric": "paired-net-ev", "operator": "gt", "threshold": 0.0, "period": "recent-3y"},
            {"id": "older-guardrail", "metric": "older-period-net-ev", "operator": "ge", "threshold": -0.01, "period": "older-history"},
        ],
        "stopping_rule": "Stop after two variants or one protected-holdout use; failures remain recorded.",
        "overfit_triggers": [
            {"id": "rank-instability", "metric": "rank-flip-rate", "operator": "gt", "threshold": 0.35, "action": "quarantine"},
            {"id": "specification-sensitivity", "metric": "sign-flip-rate", "operator": "gt", "threshold": 0.25, "action": "quarantine"},
        ],
    }


class GuardTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / "tuning/runtime/factor-guard-tests"
        runtime.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / "state"

    def write_protocol(self, value, name="protocol.json"):
        path = self.base / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def seal(self, value=None, name="protocol.json"):
        return guard.seal(self.write_protocol(value or protocol(), name), self.state)["protocol_sha256"]

    def finish_testing(self, protocol_sha, *, protected=True, variant="v1"):
        splits = ["development", "validation"] + (["protected"] if protected else [])
        guard.begin_attempt(self.state, protocol_sha, variant, {"factor_ids": ["real-rate-change"]}, splits)
        guard.finish_attempt(self.state, protocol_sha, variant, "succeeded", SHA_B)
        return guard.complete_testing(self.state, protocol_sha, SHA_B)

    def test_seal_is_canonical_immutable_and_resumable(self):
        value = protocol()
        source = self.write_protocol(value)
        sealed = guard.seal(source, self.state)
        expected = hashlib.sha256(guard.canonical(value)).hexdigest()
        self.assertEqual(sealed, {"protocol_sha256": expected, "state": "sealed"})
        source.write_text("{}", encoding="utf-8")
        self.assertEqual(guard.inspect_state(self.state, expected)["state"], "sealed")
        self.assertEqual(guard.seal(self.write_protocol(value, "same.json"), self.state)["protocol_sha256"], expected)

    def test_version_conflict_fails_closed(self):
        self.seal()
        changed = protocol()
        changed["hypothesis"] = "A different hypothesis cannot reuse the version."
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_PROTOCOL_VERSION_CONFLICT"):
            self.seal(changed, "changed.json")

    def test_hidden_retry_variant_and_protected_budgets(self):
        protocol_sha = self.seal()
        config = {"factor_ids": ["real-rate-change"]}
        guard.begin_attempt(self.state, protocol_sha, "v1", config, ["development", "protected"])
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_HIDDEN_RETRY_REJECTED"):
            guard.begin_attempt(self.state, protocol_sha, "renamed-v1", config,
                                ["development", "protected"])
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_PROTECTED_HOLDOUT_EXHAUSTED"):
            guard.begin_attempt(self.state, protocol_sha, "v2", {"factor_ids": ["credit-contraction"]}, ["protected"])
        guard.finish_attempt(self.state, protocol_sha, "v1", "failed", SHA_B)
        guard.begin_attempt(self.state, protocol_sha, "v2", {"factor_ids": ["credit-contraction"]}, ["development"])
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_VARIANT_EXISTS"):
            guard.begin_attempt(self.state, protocol_sha, "v2", {"factor_ids": ["real-rate-change", "credit-contraction"]}, ["development"])

    def test_promotion_requires_complete_passing_gate_and_authorizes_use(self):
        protocol_sha = self.seal()
        self.finish_testing(protocol_sha, protected=True)
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_GATE_REPORT_INCOMPLETE"):
            guard.promote(self.state, protocol_sha, {"recent-net-ev": 0.01}, SHA_A)
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_PROMOTION_GATE_FAILED"):
            guard.promote(self.state, protocol_sha,
                          {"recent-net-ev": -0.001, "older-guardrail": 0.0}, SHA_A)
        promoted = guard.promote(self.state, protocol_sha,
                                 {"recent-net-ev": 0.01, "older-guardrail": 0.0}, SHA_A)
        self.assertEqual(promoted["state"], "promoted")
        authorization = guard.authorize_use(self.state, [protocol_sha], "kelly_publication", SHA_C)
        self.assertTrue(guard.SHA256.fullmatch(authorization["authorization_sha256"]))

    def test_quarantine_blocks_use_and_same_holdout_remediation(self):
        protocol_sha = self.seal()
        self.finish_testing(protocol_sha)
        quarantined = guard.quarantine(self.state, protocol_sha, {"rank-instability": 0.6}, SHA_A)
        self.assertEqual(quarantined["state"], "quarantined")
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_EVIDENCE_NOT_ELIGIBLE"):
            guard.authorize_use(self.state, [protocol_sha], "combination_selection", SHA_B)
        child = protocol(experiment_id="rebound-alpha-remediation", mode="remediation",
                         parent=protocol_sha, protected_sha=SHA_D)
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_REMEDIATION_HOLDOUT_REUSED"):
            self.seal(child, "bad-child.json")

    def test_fresh_remediation_preserves_parent_and_can_promote(self):
        parent_sha = self.seal()
        self.finish_testing(parent_sha)
        guard.quarantine(self.state, parent_sha, {"specification-sensitivity": 0.5}, SHA_A)
        child = protocol(experiment_id="rebound-alpha-remediation", mode="remediation",
                         parent=parent_sha, protected_sha="e" * 64)
        child["factors"][0]["max_degrees_of_freedom"] = 1
        child["multiplicity"]["family_id"] = "rates-remediation-v1"
        child_sha = self.seal(child, "child.json")
        self.assertEqual(guard.inspect_state(self.state, parent_sha)["state"], "remediation_registered")
        self.assertEqual(guard.inspect_state(self.state, child_sha)["state"], "sealed")
        self.assertEqual(self.finish_testing(child_sha, protected=True)["state"], "fresh_validation")
        guard.promote(self.state, child_sha, {"recent-net-ev": 0.01, "older-guardrail": 0.0}, SHA_B)
        self.assertEqual(guard.inspect_state(self.state, child_sha)["state"], "promoted")
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_EVIDENCE_NOT_ELIGIBLE"):
            guard.authorize_use(self.state, [parent_sha], "ev_publication", SHA_C)
        guard.authorize_use(self.state, [child_sha], "ev_publication", SHA_C)

    def test_invalid_transition_and_unmet_trigger_fail(self):
        protocol_sha = self.seal()
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_PROTOCOL_NOT_PROMOTABLE"):
            guard.promote(self.state, protocol_sha,
                          {"recent-net-ev": 0.01, "older-guardrail": 0.0}, SHA_A)
        self.finish_testing(protocol_sha)
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_OVERFIT_TRIGGER_NOT_MET"):
            guard.quarantine(self.state, protocol_sha, {"rank-instability": 0.1}, SHA_A)

    def test_ledger_tampering_is_detected(self):
        protocol_sha = self.seal()
        path = self.state / "events" / "00000000000000000001.json"
        event = json.loads(path.read_text())
        event["data"]["version"] = 999
        path.write_text(json.dumps(event))
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_LEDGER_CHAIN_INVALID"):
            guard.inspect_state(self.state, protocol_sha)

    def test_fresh_process_cli_reads_same_state(self):
        protocol_sha = self.seal()
        completed = subprocess.run(
            [sys.executable, "-I", str(ROOT / "tuning/factor_mining/cli.py"),
             "--state", str(self.state), "inspect", "--protocol-sha256", protocol_sha],
            cwd=str(Path.home()), capture_output=True, text=True, timeout=10, check=True,
        )
        output = json.loads(completed.stdout)
        self.assertEqual(output["result"]["state"], "sealed")
        self.assertEqual(output["result"]["protocol_sha256"], protocol_sha)

    def test_protocol_rejects_missing_overfit_controls_and_unsafe_budget(self):
        missing = protocol(); missing["overfit_triggers"] = []
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_OVERFIT_TRIGGERS_REQUIRED"):
            guard.validate_protocol(missing)
        unsafe = protocol(); unsafe["budget"]["max_protected_uses"] = 2
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_BUDGET_UNSAFE"):
            guard.validate_protocol(unsafe)

    def test_split_overlap_and_reused_fingerprint_are_rejected(self):
        overlap = protocol(); overlap["data"]["splits"][1]["start"] = "2014-01-01"
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_SPLIT_OVERLAP"):
            guard.validate_protocol(overlap)
        reused = protocol(); reused["data"]["splits"][1]["fingerprint_sha256"] = SHA_A
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_SPLIT_FINGERPRINT_REUSED"):
            guard.validate_protocol(reused)

    def test_symlink_in_protocol_registry_fails_closed(self):
        protocol_sha = self.seal()
        external = self.base / "external.json"
        external.write_text(json.dumps(protocol(experiment_id="external")), encoding="utf-8")
        planted = self.state / "protocols" / ("f" * 64 + ".json")
        planted.symlink_to(external)
        changed = protocol(experiment_id="second-experiment")
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_PROTOCOL_REGISTRY_INVALID"):
            self.seal(changed, "second.json")
        self.assertEqual(guard.inspect_state(self.state, protocol_sha)["state"], "sealed")

    def test_failed_or_unprotected_attempt_cannot_complete(self):
        protocol_sha = self.seal()
        guard.begin_attempt(self.state, protocol_sha, "failed-dev", {"factor_ids": ["real-rate-change"]}, ["development"])
        guard.finish_attempt(self.state, protocol_sha, "failed-dev", "failed", SHA_B)
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_PROTECTED_SUCCESS_REQUIRED"):
            guard.complete_testing(self.state, protocol_sha, SHA_B)
        guard.begin_attempt(self.state, protocol_sha, "invalid-protected", {"factor_ids": ["credit-contraction"]}, ["protected"])
        guard.finish_attempt(self.state, protocol_sha, "invalid-protected", "invalid", SHA_C)
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_PROTECTED_SUCCESS_REQUIRED"):
            guard.complete_testing(self.state, protocol_sha, SHA_C)

    def test_completion_evidence_must_bind_successful_protected_attempt(self):
        protocol_sha = self.seal()
        guard.begin_attempt(self.state, protocol_sha, "v1", {"factor_ids": ["real-rate-change"]}, ["protected"])
        guard.finish_attempt(self.state, protocol_sha, "v1", "succeeded", SHA_B)
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_COMPLETION_EVIDENCE_UNBOUND"):
            guard.complete_testing(self.state, protocol_sha, SHA_C)

    def test_post_promotion_overfit_quarantine_revokes_future_eligibility(self):
        protocol_sha = self.seal()
        self.finish_testing(protocol_sha)
        guard.promote(self.state, protocol_sha,
                      {"recent-net-ev": 0.01, "older-guardrail": 0.0}, SHA_A)
        guard.authorize_use(self.state, [protocol_sha], "combination_selection", SHA_B)
        guard.quarantine(self.state, protocol_sha, {"rank-instability": 0.6}, SHA_C)
        self.assertEqual(guard.inspect_state(self.state, protocol_sha)["state"], "quarantined")
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_EVIDENCE_NOT_ELIGIBLE"):
            guard.authorize_use(self.state, [protocol_sha], "ev_publication", SHA_D)

    def test_orphaned_protocol_file_is_recovered_on_reseal(self):
        value = protocol()
        payload = guard.canonical(value)
        protocol_sha = hashlib.sha256(payload).hexdigest()
        (self.state / "protocols").mkdir(parents=True)
        (self.state / "protocols" / (protocol_sha + ".json")).write_bytes(payload)
        recovered = guard.seal(self.write_protocol(value), self.state)
        self.assertEqual(recovered, {"protocol_sha256": protocol_sha, "state": "sealed"})
        self.assertEqual(guard.inspect_state(self.state, protocol_sha)["event_count"], 1)

    def test_symlinked_protocol_directory_cannot_escape_state_root(self):
        self.state.mkdir()
        external = self.base / "external-directory"
        external.mkdir()
        (self.state / "protocols").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_STATE_SUBDIR_INVALID"):
            self.seal()
        self.assertEqual(list(external.iterdir()), [])

    def test_malformed_dates_are_rejected(self):
        for invalid in ("2024-1-01", "not-a-date", "2024-02-30"):
            value = protocol(); value["data"]["splits"][1]["start"] = invalid
            with self.subTest(invalid=invalid), self.assertRaisesRegex(guard.GuardError, "FACTOR_SPLIT_RANGE_INVALID"):
                guard.validate_protocol(value)

    def test_cli_argument_failures_return_stable_json(self):
        completed = subprocess.run(
            [sys.executable, "-I", str(ROOT / "tuning/factor_mining/cli.py")],
            cwd=str(Path.home()), capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout),
                         {"status": "failed", "code": "FACTOR_ARGUMENTS_INVALID"})
        self.assertEqual(completed.stderr, "")

    def test_two_processes_racing_last_protected_use_only_admit_one(self):
        protocol_sha = self.seal()
        configs = []
        for index in (1, 2):
            path = self.base / f"config-{index}.json"
            factor_id = "real-rate-change" if index == 1 else "credit-contraction"
            path.write_text(json.dumps({"factor_ids": [factor_id]}), encoding="utf-8")
            configs.append(path)
        command = [sys.executable, "-I", str(ROOT / "tuning/factor_mining/cli.py"),
                   "--state", str(self.state), "begin", "--protocol-sha256", protocol_sha]
        processes = [subprocess.Popen(command + ["--variant-id", f"v{index}",
                     "--configuration", str(configs[index - 1]), "--split", "protected"],
                     cwd=str(Path.home()), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for index in (1, 2)]
        results = [process.communicate(timeout=10) + (process.returncode,) for process in processes]
        self.assertEqual(sorted(result[2] for result in results), [0, 2])
        outputs = [json.loads(result[0]) for result in results]
        self.assertEqual(sum(output["status"] == "ok" for output in outputs), 1)
        failure = next(output for output in outputs if output["status"] == "failed")
        self.assertEqual(failure["code"], "FACTOR_PROTECTED_HOLDOUT_EXHAUSTED")
        self.assertEqual(guard.inspect_state(self.state, protocol_sha)["protected_uses"], 1)

    def test_new_protocol_version_cannot_reset_family_or_holdout_budget(self):
        first_sha = self.seal()
        guard.begin_attempt(self.state, first_sha, "first", {"factor_ids": ["real-rate-change"]}, ["protected"])
        second = protocol(version=2, protected_sha=SHA_D)
        second["data"]["snapshot_sha256"] = "e" * 64
        second_sha = self.seal(second, "version-2.json")
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_PROTECTED_HOLDOUT_EXHAUSTED"):
            guard.begin_attempt(self.state, second_sha, "second", {"factor_ids": ["credit-contraction"]}, ["protected"])
        guard.begin_attempt(self.state, second_sha, "second", {"factor_ids": ["credit-contraction"]}, ["development"])
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_VARIANT_BUDGET_EXHAUSTED"):
            guard.begin_attempt(self.state, second_sha, "third", {"factor_ids": ["real-rate-change", "credit-contraction"]}, ["development"])

    def test_protocol_version_cannot_change_family_identity_or_cap(self):
        self.seal()
        changed_family = protocol(version=2)
        changed_family["multiplicity"]["family_id"] = "renamed-family"
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_FAMILY_CONTRACT_CHANGED"):
            self.seal(changed_family, "renamed-family.json")
        changed_cap = protocol(version=2)
        changed_cap["multiplicity"]["max_variants"] = 3
        changed_cap["budget"]["max_variants"] = 3
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_FAMILY_CONTRACT_CHANGED"):
            self.seal(changed_cap, "raised-cap.json")
        changed_method = protocol(version=2)
        changed_method["multiplicity"]["method"] = "uncorrected"
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_FAMILY_CONTRACT_CHANGED"):
            self.seal(changed_method, "changed-method.json")
        changed_alpha = protocol(version=2)
        changed_alpha["multiplicity"]["alpha"] = 0.99
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_FAMILY_CONTRACT_CHANGED"):
            self.seal(changed_alpha, "changed-alpha.json")

    def test_renamed_identical_factor_is_hidden_retry_across_versions(self):
        first_sha = self.seal()
        guard.begin_attempt(self.state, first_sha, "first",
                            {"factor_ids": ["real-rate-change"]}, ["development"])
        second = protocol(version=2)
        second["factors"][0]["id"] = "renamed-real-rate-change"
        second_sha = self.seal(second, "renamed-factor.json")
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_HIDDEN_RETRY_REJECTED"):
            guard.begin_attempt(self.state, second_sha, "renamed",
                                {"factor_ids": ["renamed-real-rate-change"]}, ["development"])

    def test_changed_factor_semantics_with_same_id_is_new_variant(self):
        first_sha = self.seal()
        guard.begin_attempt(self.state, first_sha, "first",
                            {"factor_ids": ["real-rate-change"]}, ["development"])
        second = protocol(version=2)
        second["factors"][0]["transformation"] = "126-session difference with release lag"
        second_sha = self.seal(second, "changed-factor.json")
        started = guard.begin_attempt(self.state, second_sha, "changed",
                                      {"factor_ids": ["real-rate-change"]}, ["development"])
        self.assertEqual(started["event"], "attempt_started")

    def test_attempt_configuration_is_limited_to_declared_factor_subset(self):
        protocol_sha = self.seal()
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_VARIANT_CONFIG_INVALID"):
            guard.begin_attempt(self.state, protocol_sha, "lookahead",
                                {"factor_ids": ["real-rate-change"], "future_sessions": 126},
                                ["development"])
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_VARIANT_FACTOR_UNDECLARED"):
            guard.begin_attempt(self.state, protocol_sha, "undeclared",
                                {"factor_ids": ["undeclared-lookahead"]}, ["development"])
        guard.begin_attempt(self.state, protocol_sha, "ordered",
                            {"factor_ids": ["real-rate-change", "credit-contraction"]},
                            ["development"])
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_HIDDEN_RETRY_REJECTED"):
            guard.begin_attempt(self.state, protocol_sha, "reversed",
                                {"factor_ids": ["credit-contraction", "real-rate-change"]},
                                ["development"])

    def test_remediation_cannot_reuse_grandparent_holdout(self):
        parent_sha = self.seal()
        self.finish_testing(parent_sha)
        guard.quarantine(self.state, parent_sha, {"rank-instability": 0.6}, SHA_A)
        child = protocol(experiment_id="child", mode="remediation", parent=parent_sha,
                         protected_sha="e" * 64)
        child["multiplicity"]["family_id"] = "child-family"
        child_sha = self.seal(child, "child-lineage.json")
        self.finish_testing(child_sha)
        guard.quarantine(self.state, child_sha, {"rank-instability": 0.6}, SHA_B)
        grandchild = protocol(experiment_id="grandchild", mode="remediation", parent=child_sha,
                              protected_sha=SHA_D)
        grandchild["multiplicity"]["family_id"] = "grandchild-family"
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_REMEDIATION_HOLDOUT_REUSED"):
            self.seal(grandchild, "grandchild.json")

    def test_duplicate_keys_and_nonfinite_json_are_rejected(self):
        duplicate = self.base / "duplicate.json"
        duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_JSON_DUPLICATE_KEY"):
            guard.seal(duplicate, self.state)
        nonfinite = protocol(); nonfinite["model"]["hyperparameters"]["alpha"] = float("nan")
        source = self.base / "nonfinite.json"
        source.write_text(json.dumps(nonfinite), encoding="utf-8")
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_JSON_NONFINITE"):
            guard.seal(source, self.state)

    def test_malformed_protocol_types_are_sanitized_by_cli(self):
        malformed = protocol(); malformed["mode"] = []
        source = self.write_protocol(malformed, "malformed.json")
        completed = subprocess.run(
            [sys.executable, "-I", str(ROOT / "tuning/factor_mining/cli.py"),
             "--state", str(self.state), "seal", "--protocol", str(source)],
            cwd=str(Path.home()), capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout),
                         {"status": "failed", "code": "FACTOR_MODE_INVALID"})
        self.assertEqual(completed.stderr, "")

    def test_open_testing_can_quarantine_and_blocks_more_attempts(self):
        protocol_sha = self.seal()
        guard.begin_attempt(self.state, protocol_sha, "v1",
                            {"factor_ids": ["real-rate-change"]}, ["development"])
        guard.finish_attempt(self.state, protocol_sha, "v1", "succeeded", SHA_B)
        guard.quarantine(self.state, protocol_sha, {"rank-instability": 0.6}, SHA_B)
        self.assertEqual(guard.inspect_state(self.state, protocol_sha)["state"], "quarantined")
        with self.assertRaisesRegex(guard.GuardError, "FACTOR_PROTOCOL_NOT_OPEN"):
            guard.begin_attempt(self.state, protocol_sha, "v2",
                                {"factor_ids": ["credit-contraction"]}, ["development"])

    def test_multi_protocol_authorization_is_one_atomic_event(self):
        first_sha = self.seal()
        self.finish_testing(first_sha)
        guard.promote(self.state, first_sha,
                      {"recent-net-ev": 0.01, "older-guardrail": 0.0}, SHA_A)
        second = protocol(experiment_id="second-alpha", protected_sha="e" * 64)
        second["multiplicity"]["family_id"] = "second-family"
        second_sha = self.seal(second, "second-alpha.json")
        self.finish_testing(second_sha)
        guard.promote(self.state, second_sha,
                      {"recent-net-ev": 0.02, "older-guardrail": 0.0}, SHA_C)
        authorization = guard.authorize_use(
            self.state, [second_sha, first_sha], "combination_selection", SHA_D)
        events = guard._events(self.state)
        authorizations = [event for event in events if event["event"] == "evidence_use_authorized"]
        self.assertEqual(len(authorizations), 1)
        self.assertEqual(authorizations[0]["data"]["protocol_sha256s"],
                         sorted([first_sha, second_sha]))
        self.assertEqual(authorization["authorization_sha256"],
                         authorizations[0]["data"]["authorization_sha256"])

    def test_unchanged_protocol_template_cannot_be_sealed(self):
        template = json.loads((ROOT / "tuning/factor_mining/protocol.template.json").read_text())
        with self.assertRaises(guard.GuardError):
            guard.validate_protocol(template)


if __name__ == "__main__":
    unittest.main()
