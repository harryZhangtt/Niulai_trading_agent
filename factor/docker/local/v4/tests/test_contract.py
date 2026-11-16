import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from factor.docker.local.v4 import launcher, validator

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path("/Users/bytedance/Desktop/Trading Agent")
PLAN = WORKSPACE / "docs/plans/factor-mining-local-docker-activation-v4-20261105.md"
TEMP_ROOT = WORKSPACE / ".job-runtime/tests"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)


class V4PreflightTests(unittest.TestCase):
    def make_workspace(self, root: Path) -> Path:
        workspace = root / "workspace"
        workspace.mkdir(mode=0o700)
        source = WORKSPACE / "factor/docker/local/v2"
        target = workspace / "factor/docker/local/v2"
        target.mkdir(parents=True)
        for name in ("installation-receipt.json", "runtime-profile-v2.json"):
            shutil.copy2(source / name, target / name)
        return workspace

    def test_main_bundle_is_exact_selected_disabled_and_live_v2_bound(self):
        hashes = validator.validate_bundle()
        self.assertEqual(set(hashes), {"runtime-profile-v4.json", "activation-command-v4.json"})
        profile = launcher.load_json(launcher.PROFILE_PATH)
        self.assertFalse(profile["runnable"])
        self.assertFalse(profile["apply_allowed"])
        self.assertEqual(profile["predecessors"], launcher.V2_BINDINGS)

    def test_apply_false_does_not_create_short_root(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            workspace = self.make_workspace(Path(temp))
            plan = launcher._prepare_roots(workspace, apply=False, check_socket=False)
            self.assertFalse(plan["applied"])
            self.assertFalse((workspace / ".c").exists())
            self.assertEqual(plan["roots"]["COLIMA_HOME"]["action"], "would-create")

    def test_apply_creates_exact_private_empty_roots_and_is_idempotent_when_empty(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            workspace = self.make_workspace(Path(temp))
            result = launcher._prepare_roots(workspace, apply=True, check_socket=False)
            self.assertTrue(result["applied"])
            for relative in launcher.ROOTS.values():
                path = workspace / relative
                self.assertTrue(path.is_dir())
                self.assertFalse(path.is_symlink())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
                self.assertEqual(path.stat().st_uid, os.geteuid())
                self.assertEqual(list(path.iterdir()), [])
            second = launcher._prepare_roots(workspace, apply=True, check_socket=False)
            self.assertTrue(all(not item["created"] for item in second["roots"].values()))

    def test_missing_colima_root_is_created_so_global_fallback_is_impossible(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            workspace = self.make_workspace(Path(temp))
            self.assertFalse((workspace / ".c").exists())
            launcher._prepare_roots(workspace, apply=True, check_socket=False)
            self.assertTrue((workspace / ".c").is_dir())
            command = launcher.load_json(launcher.COMMAND_PATH)
            expected = str(WORKSPACE / ".c")
            self.assertEqual(command["environment"]["COLIMA_HOME"], expected)
            self.assertNotEqual(command["environment"]["COLIMA_HOME"], str(Path.home() / ".colima"))

    def test_cache_and_docker_config_are_explicit_absolute_and_no_global_fallback(self):
        command = launcher.load_json(launcher.COMMAND_PATH)
        env = command["environment"]
        self.assertEqual(env["COLIMA_CACHE_HOME"], str(WORKSPACE / "factor/runtime/local/colima-cache"))
        self.assertEqual(env["DOCKER_CONFIG"], str(WORKSPACE / "factor/runtime/local/docker-config"))
        self.assertTrue(all(value.startswith(str(WORKSPACE)) for key, value in env.items()
                            if key != "COLIMA_PROFILE"))
        self.assertIn("--template=false", command["argv"])

    def test_existing_nonempty_file_wrong_mode_and_symlink_roots_fail(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            workspace = self.make_workspace(Path(temp))
            state = workspace / ".c"
            state.write_text("file")
            with self.assertRaises(launcher.V4ContractError):
                launcher._prepare_roots(workspace, apply=True, check_socket=False)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            workspace = self.make_workspace(Path(temp))
            state = workspace / ".c"
            state.mkdir(mode=0o755)
            with self.assertRaisesRegex(launcher.V4ContractError, "MODE"):
                launcher._prepare_roots(workspace, apply=True, check_socket=False)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            workspace = self.make_workspace(Path(temp))
            target = workspace / "target"
            target.mkdir()
            (workspace / ".c").symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(launcher.V4ContractError, "SYMLINK"):
                launcher._prepare_roots(workspace, apply=True, check_socket=False)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            workspace = self.make_workspace(Path(temp))
            launcher._prepare_roots(workspace, apply=True, check_socket=False)
            (workspace / ".c" / "unexpected").write_text("x")
            with self.assertRaisesRegex(launcher.V4ContractError, "NOT_EMPTY"):
                launcher._prepare_roots(workspace, apply=True, check_socket=False)

    def test_wrong_owner_and_race_shape_fail_sanitized(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            workspace = self.make_workspace(Path(temp))
            original = os.fstat
            with patch("factor.docker.local.v4.launcher.os.fstat",
                       side_effect=lambda fd: type("S", (), {"st_mode": stat.S_IFDIR | 0o700,
                                                              "st_uid": os.geteuid() + 1})()):
                with self.assertRaisesRegex(launcher.V4ContractError, "OWNER"):
                    launcher._prepare_roots(workspace, apply=True, check_socket=False)
            self.assertIsNotNone(original)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            workspace = self.make_workspace(Path(temp))
            with patch("factor.docker.local.v4.launcher.os.open",
                       side_effect=OSError("synthetic race")):
                with self.assertRaises(launcher.V4ContractError):
                    launcher._prepare_roots(workspace, apply=True, check_socket=False)

    def test_workspace_must_be_explicit_absolute_available_and_not_symlink(self):
        for value in (None, "", Path("relative"), True):
            with self.subTest(value=value), self.assertRaises(launcher.V4ContractError):
                launcher.validate_workspace(value)  # type: ignore[arg-type]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            target = Path(temp) / "target"
            target.mkdir()
            link = Path(temp) / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(launcher.V4ContractError, "UNSAFE"):
                launcher.validate_workspace(link)

    def test_live_v2_physical_and_canonical_drift_fail(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            workspace = self.make_workspace(Path(temp))
            launcher._validate_predecessors(workspace, launcher.V2_BINDINGS)
            receipt = workspace / launcher.V2_BINDINGS["v2_installation_receipt"]["path"]
            receipt.write_bytes(receipt.read_bytes() + b"\n")
            with self.assertRaisesRegex(launcher.V4ContractError, "PHYSICAL_DRIFT"):
                launcher._validate_predecessors(workspace, launcher.V2_BINDINGS)
        changed = dict(launcher.V2_BINDINGS)
        with self.assertRaisesRegex(launcher.V4ContractError, "DECLARATION"):
            launcher._validate_predecessors(WORKSPACE, changed | {"unexpected": {}})

    def test_socket_path_is_under_limit_and_long_path_fails(self):
        self.assertEqual(len(str(WORKSPACE / ".c" / launcher.SOCKET_SUFFIX).encode()), 94)
        with tempfile.TemporaryDirectory(prefix="x" * 80, dir=TEMP_ROOT) as temp:
            workspace = self.make_workspace(Path(temp))
            with self.assertRaisesRegex(launcher.V4ContractError, "SOCKET_PATH_TOO_LONG"):
                launcher.prepare_roots(workspace, apply=True)

    def test_schema_arrays_null_types_bool_integer_and_surrogates(self):
        launcher.validate_schema_value([None, None], {"type": "array", "items": {"type": "null"}})
        for instance, schema in ((True, {"type": "integer"}),
                                 (1, {"type": "boolean"}),
                                 (None, {"type": "array", "items": {"type": "null"}})):
            with self.assertRaisesRegex(launcher.V4ContractError, "SCHEMA_TYPE"):
                launcher.validate_schema_value(instance, schema)
        with self.assertRaisesRegex(launcher.V4ContractError, "JSON_UNICODE"):
            launcher.loads_strict('"\\ud800"')
        with self.assertRaisesRegex(launcher.V4ContractError, "JSON_UNICODE"):
            launcher.loads_strict(b'"\xff"')

    def test_json_duplicate_nonfinite_and_unknown_schema_mutation_fail(self):
        with self.assertRaisesRegex(launcher.V4ContractError, "DUPLICATE_KEY"):
            launcher.loads_strict('{"x":1,"x":2}')
        with self.assertRaisesRegex(launcher.V4ContractError, "NONFINITE"):
            launcher.loads_strict('{"x":NaN}')
        profile = launcher.load_json(launcher.PROFILE_PATH)
        profile["unexpected"] = True
        with self.assertRaisesRegex(launcher.V4ContractError, "SCHEMA_CONST"):
            launcher.validate_profile(profile, WORKSPACE)

    def test_activation_and_rollback_are_data_only_and_permanent_predispatch(self):
        command = launcher.validate_command(launcher.load_json(launcher.COMMAND_PATH), WORKSPACE)
        self.assertFalse(command["executed"])
        self.assertFalse(command["apply_allowed"])
        self.assertIn("--template=false", command["argv"])
        self.assertEqual(command["classification_on_preflight_failure"], "permanent-pre-dispatch")
        self.assertEqual(command["rollback"]["argv"], [
            "/opt/homebrew/bin/colima", "delete", "factor-mining", "--force"])

    def test_validator_cli_is_read_only(self):
        result = subprocess.run([sys.executable, "-B", "-m", "factor.docker.local.v4.validator"],
                                cwd=WORKSPACE, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["runnable"])
        self.assertFalse(payload["apply_allowed"])

    def test_plan_documents_failure_repair_and_nonclaims(self):
        text = PLAN.read_text()
        for phrase in ("119-byte", "160-byte", "94-byte", "permanent pre-dispatch",
                       "--template=false", "No VM or Docker daemon is started by this repair"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
