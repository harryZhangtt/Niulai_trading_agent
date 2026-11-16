import copy
import json
from pathlib import Path
import unittest
from unittest import mock

from factor.deployment.gcp_activation import activation


ROOT = Path(__file__).resolve().parents[1]


class GcpActivationTests(unittest.TestCase):
    def setUp(self):
        self.candidate = activation.load_profile()
        self.synthetic = activation.validate_profile(
            activation.loads_strict((ROOT / "fixtures/synthetic-populated-v1.json").read_bytes()))
        self.receipts = {
            key: activation.loads_strict((ROOT / f"fixtures/synthetic-{key}-receipt-v1.json").read_bytes())
            for key in ("conformance", "runtime", "approval")
        }

    def test_candidate_is_exact_disabled_and_live_freeze_bound(self):
        self.assertEqual(self.candidate, activation.candidate_profile())
        self.assertEqual(self.candidate["freeze_manifest_sha256"], activation.FREEZE_SHA256)
        self.assertFalse(self.candidate["apply_allowed"])
        self.assertTrue(all(value is False for value in self.candidate["activation"].values()))
        self.assertTrue(all(value is None for value in self.candidate["activation_receipts"].values()))
        with mock.patch.object(activation.gcp_freeze, "load_and_validate",
                               side_effect=ValueError("synthetic")):
            with self.assertRaisesRegex(activation.ActivationError, "FREEZE_INVALID"):
                activation.validate_profile(copy.deepcopy(self.candidate))

    def test_nonnull_candidate_or_activation_claim_fails(self):
        mutations = []
        project = copy.deepcopy(self.candidate); project["projects"]["control"] = "factor-control"; mutations.append(project)
        enable = copy.deepcopy(self.candidate); enable["activation"]["enable_apis"] = True; mutations.append(enable)
        receipt = copy.deepcopy(self.candidate); receipt["synthetic_conformance_receipt_sha256"] = "a" * 64; mutations.append(receipt)
        freeze = copy.deepcopy(self.candidate); freeze["freeze_manifest_sha256"] = "0" * 64; mutations.append(freeze)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(activation.ActivationError):
                activation.validate_profile(value)

    def test_base_terraform_has_valid_refs_exact_dag_and_zero_resources(self):
        value = activation.render_base_terraform(self.synthetic)
        self.assertEqual(set(value), {"terraform", "resource"})
        resources = [body for values in value["resource"].values() for body in values.values()]
        self.assertTrue(all(body["count"] == 0 for body in resources))
        binding = value["resource"]["google_storage_bucket_iam_member"]["executor_handoff"]
        self.assertEqual(binding["bucket"], "${google_storage_bucket.checkpoint_catalog.name}")
        self.assertEqual(binding["role"], "${google_project_iam_custom_role.executor.name}")
        self.assertEqual(binding["member"], "serviceAccount:${google_service_account.executor.email}")
        key = value["resource"]["google_kms_crypto_key_iam_member"]["checker"]
        self.assertEqual(key["crypto_key_id"], "${google_kms_crypto_key.checker.id}")
        deny = value["resource"]["google_iam_deny_policy"]["executor_forbidden_capabilities"]
        self.assertIn("${google_service_account.executor.email}",
                      deny["rules"][0]["deny_rule"]["denied_principals"][0])
        self.assertEqual(value["resource"]["google_logging_project_sink"]["audit"]["depends_on"],
                         ["google_logging_project_bucket_config.audit"])

    def test_hidden_construct_roster_dag_and_iam_mutations_fail(self):
        base = activation.render_base_terraform(self.synthetic)
        mutations = []
        provider = copy.deepcopy(base); provider["provider"] = {}; mutations.append(provider)
        provisioner = copy.deepcopy(base)
        next(iter(provisioner["resource"]["google_project"].values()))["provisioner"] = []
        mutations.append(provisioner)
        removed = copy.deepcopy(base); removed["resource"]["google_cloud_run_v2_job"].pop("executor"); mutations.append(removed)
        unknown = copy.deepcopy(base)
        unknown["resource"]["google_logging_project_sink"]["audit"]["depends_on"] = ["google_project.missing"]
        mutations.append(unknown)
        cycle = copy.deepcopy(base)
        cycle["resource"]["google_project"]["control"]["depends_on"] = ["google_logging_project_sink.audit"]
        mutations.append(cycle)
        role = copy.deepcopy(base)
        role["resource"]["google_project_iam_custom_role"]["executor"]["permissions"] = ["storage.objects.*"]
        mutations.append(role)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(activation.ActivationError):
                activation._validate_terraform(value, activation._base_document(self.synthetic),
                                               "GCP_TERRAFORM_BASE_INVALID")

    def test_five_kms_purposes_use_distinct_signer_service_accounts(self):
        base = activation.render_base_terraform(self.synthetic)
        expected = {
            "checkpoint": "checkpoint_signer", "evaluation": "evaluation_signer",
            "checker": "checker_signer", "publication": "publication_signer",
            "revocation": "revocation_signer",
        }
        members = []
        for purpose, signer in expected.items():
            binding = base["resource"]["google_kms_crypto_key_iam_member"][purpose]
            self.assertEqual(binding["member"],
                             f"serviceAccount:${{google_service_account.{signer}.email}}")
            members.append(binding["member"])
        self.assertEqual(len(set(members)), 5)
        self.assertNotEqual(expected["publication"], expected["revocation"])

    def test_activation_validator_rederives_base_and_lock_documents(self):
        base = activation.render_base_terraform(self.synthetic)
        lock = activation.render_bucket_lock_terraform(self.synthetic, self.receipts)
        tampered_base = copy.deepcopy(base)
        tampered_base["resource"]["google_project"]["control"]["project_id"] = "attacker-project"
        forged_base_plan = activation._activation_plan(self.synthetic, tampered_base, lock,
                                                       self.receipts)
        with self.assertRaisesRegex(activation.ActivationError, "BASE_INVALID"):
            activation.validate_activation_plan(forged_base_plan, self.synthetic,
                                                tampered_base, lock, self.receipts)
        tampered_lock = copy.deepcopy(lock)
        tampered_lock["resource"]["google_storage_bucket"]["checkpoint_catalog"]["name"] = "attacker-bucket"
        forged_lock_plan = activation._activation_plan(self.synthetic, base, tampered_lock,
                                                       self.receipts)
        with self.assertRaisesRegex(activation.ActivationError, "LOCK_INVALID"):
            activation.validate_activation_plan(forged_lock_plan, self.synthetic,
                                                base, tampered_lock, self.receipts)

    def test_lock_render_requires_complete_bound_receipts_and_candidate_cannot_lock(self):
        with self.assertRaises(activation.ActivationError):
            activation.render_bucket_lock_terraform(self.candidate, self.receipts)
        lock = activation.render_bucket_lock_terraform(self.synthetic, self.receipts)
        self.assertEqual(set(lock["resource"]), {"google_storage_bucket"})
        self.assertTrue(all(body["count"] == 0 and
                            body["retention_policy"][0] == {"is_locked": True,
                                                            "retention_period": 86400}
                            for body in lock["resource"]["google_storage_bucket"].values()))
        activation.validate_receipt_bundle(self.synthetic, self.receipts)

    def test_receipt_identity_time_and_policy_mismatch_fail(self):
        mutations = []
        runtime = copy.deepcopy(self.receipts); runtime["runtime"]["runtime_slot_id"] = "other-slot"; mutations.append(runtime)
        approval = copy.deepcopy(self.receipts); approval["approval"]["lock_terraform_candidate_sha256"] = "0" * 64; mutations.append(approval)
        time = copy.deepcopy(self.receipts); time["approval"]["approved_at"] = "2026-11-04T00:00:00Z"; mutations.append(time)
        policy = copy.deepcopy(self.receipts); policy["conformance"]["policy_version"] = "other"; mutations.append(policy)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(activation.ActivationError):
                activation.validate_receipt_bundle(self.synthetic, value)

    def test_bucket_lock_is_final_and_runtime_publication_is_outside_disabled_plan(self):
        candidate_plan = activation.render_activation_plan(self.candidate)
        synthetic_plan = activation.render_activation_plan(self.synthetic, self.receipts)
        self.assertFalse(candidate_plan["lock_gate_ready"])
        self.assertTrue(synthetic_plan["lock_gate_ready"])
        self.assertFalse(synthetic_plan["apply_allowed"])
        self.assertEqual(synthetic_plan["activation_order"][-1]["stage"],
                         "production-bucket-lock")
        self.assertFalse(synthetic_plan["activation_order"][-1]["enabled"])
        self.assertNotIn("runtime-and-publication",
                         [item["stage"] for item in synthetic_plan["activation_order"]])
        weakened = copy.deepcopy(synthetic_plan); weakened["activation_order"][-1]["enabled"] = True
        base = activation.render_base_terraform(self.synthetic)
        lock = activation.render_bucket_lock_terraform(self.synthetic, self.receipts)
        with self.assertRaises(activation.ActivationError):
            activation.validate_activation_plan(weakened, self.synthetic, base, lock,
                                                self.receipts)

    def test_onboarding_is_user_owned_and_never_executed(self):
        value = activation.validate_onboarding(activation.onboarding_plan())
        self.assertEqual(value["commands"], activation.ONBOARDING_COMMANDS)
        self.assertEqual(value["owner"], "human-account-owner")
        self.assertTrue(value["interactive"]); self.assertFalse(value["executed"])
        changed = copy.deepcopy(value); changed["commands"].append("gcloud projects create x")
        with self.assertRaises(activation.ActivationError):
            activation.validate_onboarding(changed)

    def test_exact_schemas_match_runtime_documents(self):
        documents = {
            "activation-profile-v1.schema.json": [self.candidate, self.synthetic],
            "terraform-plan-v1.schema.json": [activation.render_base_terraform(self.candidate),
                                                activation.render_base_terraform(self.synthetic)],
            "bucket-lock-terraform-v1.schema.json": [activation.render_bucket_lock_terraform(self.synthetic, self.receipts)],
            "activation-plan-v1.schema.json": [activation.render_activation_plan(self.candidate),
                                                 activation.render_activation_plan(self.synthetic, self.receipts)],
            "onboarding-plan-v1.schema.json": [activation.onboarding_plan()],
            "conformance-receipt-v1.schema.json": [self.receipts["conformance"]],
            "runtime-acceptance-receipt-v1.schema.json": [self.receipts["runtime"]],
            "bucket-lock-approval-v1.schema.json": [self.receipts["approval"]],
        }
        for name, expected in documents.items():
            schema = json.loads((ROOT / name).read_text())
            self.assertEqual([item["const"] for item in schema["oneOf"]], expected)


if __name__ == "__main__":
    unittest.main()
