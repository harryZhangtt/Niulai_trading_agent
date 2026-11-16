import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from factor.docker.local.v2 import validator as v2_validator
from factor.docker.local.v3 import validator

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path("/Users/bytedance/Desktop/Trading Agent")
PLAN = WORKSPACE / "docs/plans/factor-mining-local-docker-activation-v3-20261105.md"


class V3PathRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = validator.load_json(ROOT / "runtime-profile-v3.json")
        cls.command = validator.load_json(ROOT / "activation-command-v3.json")

    def test_bundle_is_selected_disabled_and_short_path_is_exact(self):
        hashes = validator.validate_bundle()
        self.assertEqual(hashes["runtime-profile-v3.json"], validator.digest(self.profile))
        self.assertEqual(hashes["activation-command-v3.json"], validator.digest(self.command))
        self.assertEqual(validator.validate_state_root(WORKSPACE, WORKSPACE / ".c"), 94)
        self.assertFalse(self.profile["runnable"])
        self.assertFalse(self.profile["apply_allowed"])
        self.assertFalse(self.command["executed"])

    def test_original_long_main_path_and_worktree_path_are_rejected(self):
        original = WORKSPACE / "factor/runtime/local/colima"
        self.assertEqual(len(str(original / validator.SOCKET_SUFFIX).encode()), 119)
        with self.assertRaisesRegex(validator.V3ContractError, "STATE_ROOT_INVALID"):
            validator.validate_state_root(WORKSPACE, original)
        worktree = Path("/Users/bytedance/Desktop/Trading Agent/.job-runtime/codex-gmail-schema-worktree")
        candidate = worktree / "factor/runtime/local/colima"
        self.assertEqual(len(str(candidate / validator.SOCKET_SUFFIX).encode()), 160)
        with self.assertRaisesRegex(validator.V3ContractError, "WORKSPACE_INVALID"):
            validator.validate_state_root(worktree, candidate)

    def test_external_global_temp_traversal_and_wrong_root_fail(self):
        for path in (
            Path.home() / ".colima",
            Path("/tmp/factor-colima"),
            WORKSPACE.parent / "outside",
            WORKSPACE / "factor/../.c",
            WORKSPACE / ".local/colima",
        ):
            with self.subTest(path=path), self.assertRaises(validator.V3ContractError):
                validator.validate_state_root(WORKSPACE, path)

    def test_symlink_and_preexisting_state_root_fail(self):
        state = WORKSPACE / ".c"
        original_is_symlink = Path.is_symlink
        original_exists = Path.exists
        with patch.object(Path, "is_symlink", autospec=True,
                          side_effect=lambda path: True if path == state else original_is_symlink(path)):
            with self.assertRaisesRegex(validator.V3ContractError, "SYMLINK"):
                validator.validate_state_root(WORKSPACE, state)
        with patch.object(Path, "exists", autospec=True,
                          side_effect=lambda path: True if path == state else original_exists(path)):
            with self.assertRaisesRegex(validator.V3ContractError, "NOT_ABSENT"):
                validator.validate_state_root(WORKSPACE, state)

    def test_path_api_rejects_wrong_types(self):
        for workspace, root in ((str(WORKSPACE), WORKSPACE / ".c"),
                                (WORKSPACE, str(WORKSPACE / ".c")),
                                (True, WORKSPACE / ".c")):
            with self.assertRaisesRegex(validator.V3ContractError, "PATH_TYPE"):
                validator.validate_state_root(workspace, root)  # type: ignore[arg-type]

    def test_exact_schemas_and_bool_integer_substitutions_fail(self):
        for instance, schema in ((self.profile, "runtime-profile-v3.schema.json"),
                                 (self.command, "activation-command-v3.schema.json")):
            validator.validate_schema(instance, schema)
            changed = copy.deepcopy(instance)
            changed["unexpected"] = True
            with self.assertRaises(validator.V3ContractError):
                validator.validate_schema(changed, schema)
        changed = copy.deepcopy(self.profile)
        changed["platform"]["cpu"] = True
        with self.assertRaisesRegex(validator.V3ContractError, "SCHEMA_CONST"):
            validator.validate_profile(changed)
        changed = copy.deepcopy(self.profile)
        changed["runnable"] = 0
        with self.assertRaisesRegex(validator.V3ContractError, "SCHEMA_CONST"):
            validator.validate_profile(changed)

    def test_strict_json_rejects_duplicates_nonfinite_and_invalid(self):
        with self.assertRaisesRegex(validator.V3ContractError, "DUPLICATE_KEY"):
            validator.loads_strict('{"x":1,"x":2}')
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaisesRegex(validator.V3ContractError, "NONFINITE"):
                validator.loads_strict('{"x":' + token + '}')
        with self.assertRaisesRegex(validator.V3ContractError, "JSON_INVALID"):
            validator.loads_strict('{')

    def test_activation_and_rollback_argv_are_exact_data_only(self):
        validator.validate_command(self.command)
        self.assertIn("--activate=false", self.command["argv"])
        self.assertIn("--mount", self.command["argv"])
        self.assertNotIn("--edit", self.command["argv"])
        self.assertEqual(self.command["rollback_argv"], [
            "/opt/homebrew/bin/colima", "delete", "factor-mining", "--force"])

    def test_failure_is_permanent_pre_dispatch_and_not_retryable(self):
        failure = self.profile["observed_failure"]
        self.assertEqual(failure["classification"], "permanent-pre-dispatch")
        self.assertFalse(failure["retry_same_command"])
        self.assertFalse(failure["vm_created"])
        self.assertFalse(failure["vm_running"])

    def test_frozen_predecessors_are_still_valid_and_bound(self):
        self.assertEqual(validator.predecessor_v1_tree(), (18, validator.EXPECTED_V1_TREE))
        receipt = v2_validator.load_json(v2_validator.RECEIPT_PATH)
        profile = v2_validator.load_json(v2_validator.PROFILE_PATH)
        self.assertEqual(v2_validator.digest(receipt), validator.EXPECTED_V2_RECEIPT)
        self.assertEqual(v2_validator.digest(profile), validator.EXPECTED_V2_PROFILE)

    def test_root_ignore_and_plan_are_exact(self):
        ignore = (WORKSPACE / ".gitignore").read_text().splitlines()
        self.assertEqual(ignore.count("/.c/"), 1)
        plan = PLAN.read_text()
        for phrase in (
            "119 bytes", "160 bytes", "94 bytes", "permanent pre-dispatch",
            "No VM was created or started", "selected-disabled", "rollback",
        ):
            self.assertIn(phrase, plan)

    def test_cli_is_read_only_and_reports_disabled_contract(self):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "factor.docker.local.v3.validator"],
            cwd=WORKSPACE, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["socket_path_length"], 94)
        self.assertFalse(payload["runnable"])
        self.assertFalse(payload["apply_allowed"])


if __name__ == "__main__":
    unittest.main()
