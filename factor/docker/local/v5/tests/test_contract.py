import fcntl
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

from factor.docker.local.v5 import launcher

MAIN = Path("/Users/bytedance/Desktop/Trading Agent")
PLAN = MAIN / "docs/plans/factor-mining-local-docker-activation-v5-20261106.md"


class Result:
    def __init__(self, returncode):
        self.returncode = returncode


class V5OneShotTests(unittest.TestCase):
    def workspace(self, temporary):
        root = Path(temporary).resolve()
        for relative in (
            "factor/docker/local/v4/runtime-profile-v4.json",
            "factor/docker/local/v4/activation-command-v4.json",
            "factor/docker/local/v2/installation-receipt.json",
            "factor/docker/local/v2/runtime-profile-v2.json",
        ):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(MAIN / relative, target)
        return root

    def absent_status(self, env):
        return {"profile": "factor-mining", "running": False, "context": None,
                "context_config_root": env["DOCKER_CONFIG"],
                "global_context_before": "default", "global_context_after": "default"}

    def running_status(self, env):
        return {"profile": "factor-mining", "running": True,
                "context": "colima-factor-mining",
                "context_config_root": env["DOCKER_CONFIG"],
                "global_context_before": "default", "global_context_after": "default"}

    def activate(self, workspace, runner, status=None, before=None):
        # Transaction tests use isolated temporary workspaces whose random path is
        # longer than the real reviewed main path. The production API has no
        # socket-check bypass; only this test seam shortens the suffix.
        with patch.object(launcher.v4, "SOCKET_SUFFIX", Path("socket")):
            return launcher.activate(
                workspace, apply=True, capability=launcher.CAPABILITY,
                parent_approved=True, runner=runner,
                status_probe=status or self.absent_status, before_spawn=before)

    def test_default_is_plan_only_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.workspace(temp)
            result = launcher.activate(workspace)
            self.assertEqual(result["status"], "selected-disabled")
            self.assertFalse(result["apply_allowed"])
            self.assertFalse((workspace / ".c").exists())

    def test_apply_requires_exact_capability_parent_approval_and_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.workspace(temp)
            for kwargs in (
                {"apply": True},
                {"apply": True, "capability": "wrong", "parent_approved": True},
                {"apply": True, "capability": launcher.CAPABILITY, "parent_approved": False},
            ):
                with self.assertRaises(launcher.V5ContractError):
                    launcher.activate(workspace, **kwargs)

    def test_success_requires_zero_and_exact_reconciled_status(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.workspace(temp)
            observed = {}
            def runner(argv, env, cwd, timeout):
                observed.update(argv=argv, env=env, cwd=cwd, timeout=timeout)
                return Result(0)
            receipt = self.activate(workspace, runner, self.running_status)
            self.assertEqual(receipt["status"], "success")
            self.assertTrue(receipt["vm_running"])
            self.assertEqual(observed["argv"], launcher._argv())
            self.assertEqual(observed["cwd"], workspace)
            self.assertEqual(set(observed["env"]), {
                "COLIMA_HOME", "COLIMA_CACHE_HOME", "COLIMA_PROFILE", "DOCKER_CONFIG", "PATH"})
            self.assertNotIn("HOME", observed["env"])
            self.assertTrue((workspace / ".c").exists())

    def test_status_mismatch_is_unknown_and_never_retryable(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.workspace(temp)
            def mismatch(env):
                value = self.running_status(env)
                value["context"] = "default"
                return value
            receipt = self.activate(workspace, lambda *args: Result(0), mismatch)
            self.assertEqual(receipt["status"], "unknown")
            self.assertFalse(receipt["retry_allowed"])
            self.assertTrue(receipt["retained_roots"])

    def test_nonzero_and_popen_error_without_vm_fail_and_cleanup(self):
        for runner in (
            lambda *args: Result(7),
            lambda *args: (_ for _ in ()).throw(OSError("synthetic")),
        ):
            with self.subTest(runner=runner), tempfile.TemporaryDirectory() as temp:
                workspace = self.workspace(temp)
                receipt = self.activate(workspace, runner)
                self.assertEqual(receipt["status"], "failed")
                self.assertFalse(receipt["vm_running"])
                self.assertTrue(receipt["cleanup_complete"])
                self.assertEqual(receipt["retained_roots"], [])
                self.assertFalse((workspace / ".c").exists())

    def test_timeout_is_unknown_when_status_cannot_prove_absence(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.workspace(temp)
            def timeout(*args):
                raise subprocess.TimeoutExpired(cmd="colima", timeout=1)
            def unavailable(_env):
                raise RuntimeError("synthetic unavailable")
            receipt = self.activate(workspace, timeout, unavailable)
            self.assertEqual(receipt["status"], "unknown")
            self.assertTrue(receipt["timed_out"])
            self.assertIsNone(receipt["vm_running"])
            self.assertFalse(receipt["retry_allowed"])

    def test_each_root_creation_failure_rolls_back_only_created_empty_dirs(self):
        targets = {".c", "colima-cache", "docker-config"}
        for target in targets:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                workspace = self.workspace(temp)
                real_mkdir = os.mkdir
                def failing(path, mode=0o777, *, dir_fd=None):
                    if str(path) == target:
                        raise OSError("synthetic")
                    return real_mkdir(path, mode, dir_fd=dir_fd)
                with patch("factor.docker.local.v5.launcher.os.mkdir", side_effect=failing):
                    receipt = self.activate(workspace, lambda *args: Result(0))
                self.assertEqual(receipt["status"], "failed")
                self.assertFalse(receipt["spawned"])
                self.assertTrue(receipt["cleanup_complete"])

    def test_prespan_rename_and_symlink_tamper_are_caught(self):
        for mode in ("rename", "symlink"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                workspace = self.workspace(temp)
                def tamper(root):
                    original = root / ".c"
                    moved = root / ".c-moved"
                    original.rename(moved)
                    if mode == "symlink":
                        original.symlink_to(moved, target_is_directory=True)
                called = []
                receipt = self.activate(workspace, lambda *args: called.append(True) or Result(0),
                                        before=tamper)
                self.assertEqual(receipt["status"], "failed")
                self.assertFalse(receipt["spawned"])
                self.assertEqual(called, [])

    def test_lock_contention_fails_before_spawn_without_unlinking_other_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.workspace(temp)
            lock = workspace / launcher.LOCK_RELATIVE
            fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                receipt = self.activate(workspace, lambda *args: Result(0))
                self.assertEqual(receipt["status"], "failed")
                self.assertFalse(receipt["spawned"])
                self.assertTrue(lock.exists())
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                lock.unlink()

    def test_preexisting_nonempty_root_is_not_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.workspace(temp)
            root = workspace / ".c"
            root.mkdir(mode=0o700)
            marker = root / "owned-before"
            marker.write_text("keep")
            receipt = self.activate(workspace, lambda *args: Result(0))
            self.assertEqual(receipt["status"], "failed")
            self.assertTrue(marker.exists())

    def test_live_v4_and_v2_drift_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.workspace(temp)
            launcher.validate_profile(launcher.load_json(launcher.PROFILE_PATH), workspace)
            target = workspace / "factor/docker/local/v2/runtime-profile-v2.json"
            target.write_bytes(target.read_bytes() + b"\n")
            with self.assertRaisesRegex(launcher.V5ContractError, "PHYSICAL_DRIFT"):
                launcher.validate_profile(launcher.load_json(launcher.PROFILE_PATH), workspace)

    def test_receipt_schema_rejects_type_null_array_and_unknown_mutations(self):
        valid = launcher._receipt("unknown", "V5_START_OUTCOME_UNKNOWN", spawned=True,
                                  child_exit=None, timed_out=True, vm_running=None,
                                  created=[], retained=[], cleanup_complete=False)
        launcher.validate_receipt(valid)
        for key, value in (("spawned", 1), ("child_exit", True), ("created_roots", None)):
            changed = dict(valid)
            changed[key] = value
            with self.assertRaises(launcher.V5ContractError):
                launcher.validate_receipt(changed)
        changed = dict(valid)
        changed["unexpected"] = True
        with self.assertRaises(launcher.V5ContractError):
            launcher.validate_receipt(changed)

    def test_profile_schema_threat_model_and_no_overclaim(self):
        profile = launcher.validate_profile(launcher.load_json(launcher.PROFILE_PATH), MAIN)
        self.assertTrue(profile["threat_model"]["lock_is_cooperative"])
        self.assertFalse(profile["threat_model"]["malicious_same_user_mutation_prevented"])
        self.assertTrue(profile["threat_model"]["same_user_hostile_mutation_out_of_scope"])
        self.assertFalse(profile["runnable"])
        self.assertFalse(profile["apply_allowed"])

    def test_plan_records_cooperative_lock_and_unknown_fence(self):
        text = PLAN.read_text().lower()
        for phrase in ("cooperative", "same-user", "unknown", "no blind retry",
                       "explicit apply", "parent approval"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
