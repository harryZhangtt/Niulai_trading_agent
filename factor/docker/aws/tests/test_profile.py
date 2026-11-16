import copy
import json
from pathlib import Path
import unittest

from factor.docker.aws import profile


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "runtime-profile.json"
FIXTURE = ROOT / "fixtures/synthetic-ready-v1.json"


class AwsFargateProfileTests(unittest.TestCase):
    def setUp(self):
        self.candidate = profile.load_profile(CANDIDATE)
        self.fixture = profile.load_profile(FIXTURE)

    def test_candidate_is_exactly_disabled_and_unprovisioned(self):
        self.assertEqual(self.candidate["status"], "selected-disabled")
        self.assertFalse(self.candidate["runnable"])
        self.assertEqual(self.candidate["blockers"], profile.BLOCKERS)
        self.assertTrue(all(value is None for value in self.candidate["accounts"].values()))
        self.assertTrue(all(value is None for value in self.candidate["regions"].values()))
        for task in self.candidate["tasks"].values():
            self.assertIsNone(task["image"])
            self.assertIsNone(task["task_role_arn"])
            self.assertEqual(task["subnet_ids"], [])
        self.assertEqual(self.candidate["activation"], {
            "runtime_invocation": False, "protected_labels": False,
            "publication": False, "production_retention_lock": False,
            "account_receipt_sha256": None, "network_receipt_sha256": None,
            "image_receipt_sha256": None, "label_policy_receipt_sha256": None,
            "publication_policy_receipt_sha256": None,
        })
        rendered = profile.render_templates(self.candidate)
        self.assertFalse(rendered["runnable"])
        self.assertTrue(all(item["image"] is None for item in rendered["task_definitions"]))
        self.assertEqual(rendered["activation"], self.candidate["activation"])

    def test_synthetic_fixture_renders_distinct_bound_templates(self):
        self.assertEqual(self.fixture["status"], "synthetic-fixture")
        rendered = profile.render_templates(self.fixture)
        self.assertEqual(len(rendered["task_definitions"]), 5)
        roles = [item["task_role_arn"] for item in rendered["task_definitions"]]
        self.assertEqual(len(set(roles)), 5)
        self.assertFalse(rendered["network"]["executor"]["default_egress"])
        self.assertFalse(rendered["runnable"])
        self.assertFalse(any(rendered["activation"][key] for key in
                             ("runtime_invocation", "protected_labels", "publication",
                              "production_retention_lock")))
        self.assertTrue(all(not any(item["active_access"].values())
                            for item in rendered["task_definitions"]))
        executor_deny = rendered["task_role_policies"]["executor"]["Statement"]
        self.assertTrue(any(item["Sid"] == "DenyProtectedLabels" for item in executor_deny))
        self.assertTrue(any(item["Sid"] == "DenySigning" for item in executor_deny))
        ecr_principals = rendered["endpoint_policies"]["ecr_api"]["Statement"][0]["Principal"]["AWS"]
        self.assertEqual(set(ecr_principals),
                         {self.fixture["tasks"][role]["execution_role_arn"]
                          for role in profile.ROLES})
        self.assertTrue(all(value not in ecr_principals for value in
                            (self.fixture["tasks"][role]["task_role_arn"]
                             for role in profile.ROLES)))
        profile.validate_templates(rendered, self.fixture)

    def test_sidecars_privilege_exec_socket_and_mutable_images_fail(self):
        mutations = [
            ("sidecar", lambda value: value["tasks"]["executor"].update(containers=2)),
            ("root", lambda value: value["tasks"]["executor"].update(user="0:0")),
            ("writable", lambda value: value["tasks"]["executor"].update(read_only_root=False)),
            ("privileged", lambda value: value["tasks"]["executor"].update(privileged=True)),
            ("exec", lambda value: value["tasks"]["executor"].update(ecs_exec=True)),
            ("socket", lambda value: value["tasks"]["executor"].update(docker_socket=True)),
            ("tag", lambda value: value["tasks"]["executor"].update(image="repo/factor:latest")),
        ]
        for name, mutate in mutations:
            changed = copy.deepcopy(self.fixture); mutate(changed)
            with self.subTest(name=name), self.assertRaises(profile.AwsProfileError):
                profile.validate_profile(changed)

    def test_executor_internet_and_broad_endpoint_policy_fail(self):
        for key in ("public_ip", "internet_gateway", "nat_gateway", "ipv6", "default_egress"):
            changed = copy.deepcopy(self.fixture); changed["network"]["executor"][key] = True
            with self.subTest(key=key), self.assertRaises(profile.AwsProfileError):
                profile.validate_profile(changed)
        changed = copy.deepcopy(self.fixture)
        changed["tasks"]["executor"]["endpoints"].append("internet")
        with self.assertRaises(profile.AwsProfileError):
            profile.validate_profile(changed)

    def test_shared_roles_and_cross_concern_access_fail(self):
        changed = copy.deepcopy(self.fixture)
        changed["tasks"]["executor"]["task_role_arn"] = changed["tasks"]["controller"]["task_role_arn"]
        with self.assertRaisesRegex(profile.AwsProfileError, "ROLE_REUSE"):
            profile.validate_profile(changed)
        changed = copy.deepcopy(self.fixture)
        changed["tasks"]["executor"]["subnet_ids"] = changed["tasks"]["controller"]["subnet_ids"]
        with self.assertRaisesRegex(profile.AwsProfileError, "NETWORK_REUSE"):
            profile.validate_profile(changed)
        changed = copy.deepcopy(self.fixture)
        changed["tasks"]["executor"]["subnet_ids"].append(
            changed["tasks"]["controller"]["subnet_ids"][0])
        with self.assertRaisesRegex(profile.AwsProfileError, "NETWORK_REUSE"):
            profile.validate_profile(changed)
        changed = copy.deepcopy(self.fixture)
        changed["tasks"]["executor"]["task_role_arn"] = (
            "arn:aws:iam::222222222222:role/factor-executor-task")
        with self.assertRaisesRegex(profile.AwsProfileError, "ACCOUNT_BINDING"):
            profile.validate_profile(changed)
        for role, key in (("executor", "protected_labels"), ("controller", "kms_sign"),
                          ("evaluator", "publication"), ("publisher", "kms_sign")):
            changed = copy.deepcopy(self.fixture)
            changed["tasks"][role]["active_access"][key] = True
            with self.subTest(role=role, key=key), self.assertRaises(profile.AwsProfileError):
                profile.validate_profile(changed)
        changed = copy.deepcopy(self.fixture)
        changed["tasks"]["executor"]["execution_role_arn"] = (
            changed["tasks"]["controller"]["task_role_arn"])
        with self.assertRaisesRegex(profile.AwsProfileError, "ROLE_REUSE"):
            profile.validate_profile(changed)

    def test_aggregate_only_boundary_and_valid_trust_startup_policies(self):
        rendered = profile.render_templates(self.fixture)
        tasks = {item["family"].removeprefix("factor-"): item
                 for item in rendered["task_definitions"]}
        for role in ("evaluator", "checker"):
            self.assertTrue(tasks[role]["aggregate_only"])
            self.assertFalse(tasks[role]["raw_joined_rows_output"])
            self.assertFalse(tasks[role]["sensitive_logging"])
            self.assertEqual(tasks[role]["stdout_policy"], "structured-sanitized-only")
            self.assertIn("aggregate", tasks[role]["output_schema_id"])
        for role in profile.ROLES:
            for kind in ("task", "execution"):
                statement = rendered["trust_policies"][role][kind]["Statement"][0]
                self.assertNotIn("Resource", statement)
                self.assertEqual(statement["Principal"], {"Service": "ecs-tasks.amazonaws.com"})
                self.assertEqual(set(statement["Condition"]), {"StringEquals", "ArnLike"})
            logs = rendered["execution_role_policies"][role]["Statement"][2]
            self.assertTrue(logs["Resource"][0].endswith(":log-stream:*"))
        self.assertEqual(
            set(rendered["endpoint_policies"]["ecr_api"]["Statement"][0]["Principal"]["AWS"]),
            {self.fixture["tasks"][role]["execution_role_arn"] for role in profile.ROLES})
        s3_statements = rendered["endpoint_policies"]["s3"]["Statement"]
        self.assertEqual(set(s3_statements[0]["Principal"]["AWS"]),
                         {self.fixture["tasks"][role]["execution_role_arn"]
                          for role in profile.ROLES})
        executor_statement = next(item for item in s3_statements
                                  if item["Sid"] == "ExecutorDatasetObjects")
        self.assertEqual(executor_statement["Principal"]["AWS"],
                         [self.fixture["tasks"]["executor"]["task_role_arn"]])
        self.assertNotIn(self.fixture["resources"]["release_bucket_arn"],
                         " ".join(executor_statement["Resource"]))

    def test_command_output_and_logging_canaries_fail(self):
        mutations = [
            ("command", lambda value: value["tasks"]["evaluator"].update(command=["sh", "-c"])),
            ("output", lambda value: value["tasks"]["evaluator"].update(output_schema_id="raw-labels")),
            ("rows", lambda value: value["tasks"]["evaluator"].update(raw_joined_rows_output=True)),
            ("logs", lambda value: value["tasks"]["checker"].update(sensitive_logging=True)),
            ("stdout", lambda value: value["tasks"]["evaluator"].update(stdout_policy="raw")),
            ("redaction", lambda value: value["tasks"]["evaluator"].update(redaction_policy_id="none")),
        ]
        for name, mutate in mutations:
            changed = copy.deepcopy(self.fixture); mutate(changed)
            with self.subTest(name=name), self.assertRaisesRegex(
                    profile.AwsProfileError, "TASK_SECURITY"):
                profile.validate_profile(changed)

    def test_inert_policy_documents_fail_on_broadening(self):
        rendered = profile.render_templates(self.fixture)
        cases = []
        wildcard = copy.deepcopy(rendered)
        wildcard["task_role_policies"]["executor"]["Statement"][0]["Resource"] = ["*"]
        cases.append(wildcard)
        ecr_task_role = copy.deepcopy(rendered)
        ecr_task_role["endpoint_policies"]["ecr_api"]["Statement"][0]["Principal"]["AWS"].append(
            self.fixture["tasks"]["executor"]["task_role_arn"])
        cases.append(ecr_task_role)
        label_version = copy.deepcopy(rendered)
        statement = next(item for item in
                         label_version["task_role_policies"]["evaluator"]["Statement"]
                         if item["Sid"] == "ReadExactLabelVersion")
        statement["Condition"]["StringEquals"].pop("s3:VersionId")
        cases.append(label_version)
        trust = copy.deepcopy(rendered)
        trust["trust_policies"]["controller"]["task"]["Statement"][0]["Principal"] = {"AWS": "*"}
        cases.append(trust)
        for changed in cases:
            with self.assertRaisesRegex(profile.AwsProfileError, "TEMPLATE_INVALID"):
                profile.validate_templates(changed, self.fixture)

    def test_unknown_credentials_and_weakened_blockers_fail(self):
        changed = copy.deepcopy(self.candidate); changed["api_key"] = "secret"
        with self.assertRaisesRegex(profile.AwsProfileError, "SCHEMA"):
            profile.validate_profile(changed)
        changed = copy.deepcopy(self.candidate); changed["blockers"].pop()
        with self.assertRaisesRegex(profile.AwsProfileError, "BLOCKED_STATUS"):
            profile.validate_profile(changed)
        changed = copy.deepcopy(self.candidate); changed["runnable"] = True
        with self.assertRaises(profile.AwsProfileError):
            profile.validate_profile(changed)
        changed = copy.deepcopy(self.candidate)
        changed["activation"]["publication"] = True
        with self.assertRaisesRegex(profile.AwsProfileError, "ACTIVATION_FORBIDDEN"):
            profile.validate_profile(changed)
        changed = copy.deepcopy(self.fixture)
        changed["activation"]["protected_labels"] = True
        with self.assertRaisesRegex(profile.AwsProfileError, "ACTIVATION_FORBIDDEN"):
            profile.validate_profile(changed)
        relabeled = copy.deepcopy(self.fixture)
        relabeled["status"] = "selected-disabled"; relabeled["trust_class"] = "candidate_real"
        relabeled["blockers"] = list(profile.BLOCKERS)
        relabeled["limitations"] = ["selected-architecture-only", "no-aws-resources",
                                    "no-credentials", "not-runnable"]
        with self.assertRaises(profile.AwsProfileError):
            profile.validate_profile(relabeled)

    def test_strict_json_and_schemas(self):
        with self.assertRaisesRegex(profile.AwsProfileError, "DUPLICATE_KEY"):
            profile.loads_strict('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(profile.AwsProfileError, "NONFINITE"):
            profile.loads_strict('{"value":NaN}')
        for name in ("runtime-profile-v1.schema.json", "templates-v1.schema.json"):
            value = json.loads((ROOT / name).read_text())
            self.assertEqual(set(value["required"]), set(value["properties"]))
        definitions = json.loads((ROOT / "runtime-profile-v1.schema.json").read_text())["$defs"]
        for role in profile.ROLES:
            self.assertEqual(set(definitions[role]["required"]),
                             set(definitions[role]["properties"]))
        runtime_schema = json.loads((ROOT / "runtime-profile-v1.schema.json").read_text())
        self.assertEqual(runtime_schema["properties"]["network"]["const"],
                         self.fixture["network"])
        self.assertEqual(runtime_schema["properties"]["activation"]["const"],
                         self.fixture["activation"])
        template_schema = json.loads((ROOT / "templates-v1.schema.json").read_text())
        template_defs = template_schema["$defs"]
        for name in ("task_definition", "iam_statement", "trust_statement",
                     "resource_statement", "trust_pair"):
            self.assertEqual(set(template_defs[name]["required"]),
                             set(template_defs[name]["properties"]))
        self.assertNotIn("Resource", template_defs["trust_statement"]["properties"])
        self.assertEqual(template_schema["properties"]["network"]["const"],
                         self.fixture["network"])


if __name__ == "__main__":
    unittest.main()
