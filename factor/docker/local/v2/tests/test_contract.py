import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from factor.docker.local.v2 import validator


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(__file__).resolve().parents[5]
PLAN = WORKSPACE / "docs/plans/factor-mining-local-docker-installation-v2-20261105.md"


def leaf_mutations(value):
    if isinstance(value, dict):
        for key, item in value.items():
            for changed_item in leaf_mutations(item):
                changed = copy.deepcopy(value)
                changed[key] = changed_item
                yield changed
        if not value:
            yield {"unexpected": True}
    elif isinstance(value, list):
        if value:
            for index, item in enumerate(value):
                for changed_item in leaf_mutations(item):
                    changed = copy.deepcopy(value)
                    changed[index] = changed_item
                    yield changed
        else:
            yield ["unexpected"]
    elif isinstance(value, bool):
        yield not value
    elif value is None:
        yield "unexpected"
    elif isinstance(value, int):
        yield value + 1
    elif isinstance(value, str):
        yield value + "-changed"
    else:
        raise AssertionError(type(value))


class V2InstallationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = validator.load_json(ROOT / "installation-receipt.json")
        cls.profile = validator.load_json(ROOT / "runtime-profile-v2.json")

    def test_bundle_is_valid_selected_disabled_and_hash_bound(self):
        hashes = validator.validate_bundle()
        self.assertEqual(hashes, {
            "installation-receipt.json": validator.EXPECTED_RECEIPT_SHA256,
            "runtime-profile-v2.json": validator.digest(self.profile),
            "frozen-v1-tree": validator.EXPECTED_V1_TREE_SHA256,
        })
        self.assertEqual(self.profile["status"], "selected-disabled")
        self.assertFalse(self.profile["runnable"])
        self.assertFalse(self.profile["apply_allowed"])

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_values(self):
        with self.assertRaisesRegex(validator.V2ContractError, "DUPLICATE_KEY"):
            validator.load_json(ROOT / "fixtures/invalid/duplicate-key.json")
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token), self.assertRaisesRegex(
                    validator.V2ContractError, "NONFINITE"):
                validator.loads_strict('{"value":' + token + '}')

    def test_closed_exact_schemas_reject_unknown_fields_and_every_leaf_mutation(self):
        cases = [
            (self.receipt, "installation-receipt-v2.schema.json"),
            (self.profile, "runtime-profile-v2.schema.json"),
        ]
        mutation_count = 0
        for instance, schema_name in cases:
            schema = validator.load_json(ROOT / schema_name)
            body = {key: value for key, value in schema.items()
                    if key not in {"$schema", "$id"}}
            validator.validate_exact_schema(instance, body)
            stack = [body]
            while stack:
                node = stack.pop()
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                    stack.extend(node["properties"].values())
            changed = copy.deepcopy(instance)
            changed["unexpected"] = True
            with self.assertRaises(validator.V2ContractError):
                validator.validate_exact_schema(changed, body)
            for changed in leaf_mutations(instance):
                mutation_count += 1
                with self.assertRaises(validator.V2ContractError):
                    validator.validate_exact_schema(changed, body)
        self.assertGreaterEqual(mutation_count, 140)

    def test_installed_versions_paths_hashes_and_build_metadata_are_exact(self):
        validator.validate_receipt(self.receipt)
        for name, expected in validator.EXPECTED_TOOLS.items():
            tool = self.receipt["tools"][name]
            self.assertEqual((tool["version"], tool["executable_path"], tool["sha256"]),
                             expected)
            self.assertEqual(tool["install_state"], "installed-package-observed")
        self.assertTrue(self.receipt["tools"]["colima"]["commit"].startswith("00f6c297"))
        self.assertEqual(self.receipt["tools"]["docker"]["build"], "5457199aa5")
        self.assertEqual(self.receipt["tools"]["lima"]["dependency_role"],
                         "colima-dependency")

    def test_installation_is_not_activation_and_no_runtime_identity_is_claimed(self):
        self.assertEqual(self.receipt["installation_state"],
                         "homebrew-packages-installed-not-activated")
        activation = self.receipt["activation_observation"]
        self.assertEqual(activation["colima_service_status"], "none")
        self.assertEqual(activation["matching_processes"], [])
        self.assertFalse(activation["daemon_queried"])
        self.assertFalse(activation["docker_context_inspected_or_mutated"])
        self.assertIsNone(activation["vm_identity"])
        self.assertTrue(activation["service_or_process_absence_is_not_vm_identity_evidence"])
        host = self.profile["host_state"]
        self.assertIsNone(host["docker_context"])
        self.assertIsNone(host["vm_identity"])
        self.assertFalse(host["change_global_current_docker_context"])
        self.assertEqual(host["colima_config"], {"autoActivate": False})

    def test_docker_home_was_not_created_or_mutated_by_probes(self):
        home = self.receipt["activation_observation"]["home_docker_config"]
        self.assertEqual(home["state_before"], "absent")
        self.assertEqual(home["state_after"], "absent")
        self.assertEqual(home["entry_count"], 0)
        self.assertTrue(home["contents_and_metadata_unchanged"])
        self.assertEqual(home["before_aggregate_sha256"],
                         home["after_aggregate_sha256"])

    def test_only_exact_v1_installation_blockers_are_resolved(self):
        self.assertEqual(self.profile["resolved_blockers"], validator.RESOLVED_BLOCKERS)
        self.assertEqual(self.profile["blockers"], validator.RETAINED_BLOCKERS)
        for blocker in (
            "docker-context-unverified", "vm-identity-unverified",
            "controller-image-digest-unresolved", "release-digest-unresolved",
            "host-headroom-unmeasured", "disposable-lifecycle-unrun",
            "pressure-behavior-unverified", "future-io-conformance-unverified",
            "internal-network-identity-unresolved", "dual-network-conformance-unverified",
            "stable-lifecycle-conformance-unverified", "oci-architecture-unresolved",
            "image-contract-conformance-unverified",
            "official-source-live-verification-receipts-unavailable",
            "runtime-acceptance-unrun",
        ):
            self.assertIn(blocker, self.profile["blockers"])

    def test_workspace_state_and_future_context_are_explicit_but_null(self):
        host = self.profile["host_state"]
        self.assertEqual(host["colima_environment"], {
            "COLIMA_HOME": "$WORKSPACE/factor/runtime/local/colima",
            "COLIMA_PROFILE": "factor-mining",
        })
        self.assertEqual(host["expected_future_docker_context"], "colima-factor-mining")
        self.assertIsNone(host["docker_context"])
        self.assertIsNone(host["vm_identity"])

    def test_frozen_v1_tree_and_profile_are_unchanged(self):
        count, tree_hash = validator.v1_tree()
        self.assertEqual(count, 18)
        self.assertEqual(tree_hash, validator.EXPECTED_V1_TREE_SHA256)
        self.assertEqual(self.profile["frozen_v1"]["tree_sha256"], tree_hash)
        self.assertEqual(self.profile["frozen_v1"]["contract_profile_sha256"],
                         validator.EXPECTED_V1_PROFILE_SHA256)

    def test_no_apply_start_server_context_or_package_mutation_commands(self):
        dangerous = (
            "colima" + " start", "docker" + " context create",
            "docker" + " context use", "docker" + " run",
            "docker" + " compose up", "brew" + " install",
            "brew" + " upgrade", "brew" + " uninstall",
        )
        texts = []
        for path in ROOT.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                texts.append(path.read_text(errors="strict"))
        texts.append(PLAN.read_text())
        combined = "\n".join(texts).lower()
        for command in dangerous:
            with self.subTest(command=command):
                self.assertNotIn(command, combined)
        purposes = {item["purpose"] for item in self.receipt["commands"]}
        self.assertNotIn("daemon-query", purposes)
        self.assertNotIn("context-query", purposes)

    def test_plan_preserves_nonclaims_and_defers_coordinator_docs(self):
        plan = PLAN.read_text().lower()
        for phrase in (
            "not daemon or VM activation",
            "does not establish production readiness",
            "No existing runbook, local setup, inventory, or lock file is changed",
            "after all owners freeze",
        ):
            self.assertIn(phrase.lower(), plan)

    def test_cli_reports_hashes_without_runtime_action(self):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "factor.docker.local.v2.validator"],
            cwd=WORKSPACE, check=False, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["status"], "selected-disabled")
        self.assertFalse(payload["runnable"])
        self.assertFalse(payload["apply_allowed"])


if __name__ == "__main__":
    unittest.main()
