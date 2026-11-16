import json
from pathlib import Path
import tempfile
import unittest

from investment.factor_mining.rdagent_adapter import contracts, runner
from investment.factor_mining.rdagent_adapter.tests.test_contracts import request


ROOT = Path(__file__).resolve().parents[4]
class RunnerE2ETests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / "investment/factor_mining/runtime/adapter-tests"
        runtime.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def execute(self, mode, *, timeout=10, stdout_bytes=65536):
        req = request()
        req["request_id"] = "fixture-" + mode
        req["limits"]["timeout_seconds"] = timeout
        req["limits"]["stdout_bytes"] = stdout_bytes
        return runner.run_synthetic(req, mode, self.base), req

    def attempt_path(self, result):
        return self.base / result["attempt_id"]

    def test_real_child_success_has_independently_verified_artifacts(self):
        result, req = self.execute("success")
        self.assertEqual(result["receipt"]["status"], "succeeded")
        self.assertEqual(contracts.validate_receipt(result["receipt"], req), result["receipt"])
        self.assertFalse(self.attempt_path(result).exists())
        for artifact in result["receipt"]["artifacts"]:
            self.assertTrue((self.base / artifact["path"]).is_file())
        self.assertTrue((self.base / result["receipt_path"]).is_file())

    def test_exit_zero_missing_output_is_visible_failure(self):
        result, _ = self.execute("missing-output")
        self.assertEqual(result["receipt"]["status"], "failed")
        self.assertEqual(result["receipt"]["failure_code"], "FACTOR_OUTPUT_MISSING")
        self.assertEqual(result["receipt"]["artifacts"], [])

    def test_nonzero_and_oversized_output_fail_without_raw_diagnostics(self):
        nonzero, _ = self.execute("nonzero")
        self.assertEqual(nonzero["receipt"]["failure_code"], "RUNTIME_NONZERO")
        oversized, _ = self.execute("oversized", stdout_bytes=1024)
        self.assertEqual(oversized["receipt"]["failure_code"], "RUNTIME_OUTPUT_OVERSIZE")
        self.assertNotIn("X" * 100, json.dumps(oversized))

    def test_invalid_secret_canary_is_not_persisted(self):
        result, _ = self.execute("secret-canary")
        self.assertEqual(result["receipt"]["failure_code"], "RUNTIME_OUTPUT_INVALID")
        for path in self.base.rglob("*"):
            if path.is_file() and not path.is_symlink():
                self.assertNotIn(b"SECRET_CANARY", path.read_bytes())
        self.assertNotIn("SECRET_CANARY", json.dumps(result))

    def test_symlink_artifact_is_rejected(self):
        result, _ = self.execute("symlink")
        self.assertEqual(result["receipt"]["failure_code"], "ARTIFACT_INVALID")

    def test_timeout_kills_descendant_and_publishes_sanitized_receipt(self):
        result, _ = self.execute("timeout", timeout=1)
        self.assertEqual(result["receipt"]["status"], "timed_out")
        self.assertEqual(result["receipt"]["failure_code"], "RUNTIME_TIMEOUT")
        self.assertTrue(result["receipt"]["process_group_cleanup_verified"])
        self.assertFalse(self.attempt_path(result).exists())

    def test_attempt_identity_cannot_be_replayed(self):
        self.execute("success")
        with self.assertRaisesRegex(runner.RunnerError, "ATTEMPT_EXISTS"):
            self.execute("success")

    def test_request_cannot_select_executable_or_environment(self):
        req = request(); req["command"] = ["/bin/sh"]
        with self.assertRaises(contracts.ContractError):
            runner.run_synthetic(req, "success", self.base)
        with self.assertRaisesRegex(runner.RunnerError, "SYNTHETIC_MODE_INVALID"):
            runner.run_synthetic(request(), "arbitrary-command", self.base)

    def test_failed_child_files_and_reserved_names_are_removed(self):
        for mode in ("disk-canary-nonzero", "reserved-names"):
            result, _ = self.execute(mode)
            self.assertEqual(result["receipt"]["failure_code"], "RUNTIME_NONZERO")
            self.assertFalse(self.attempt_path(result).exists())
            for path in self.base.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    self.assertNotIn(b"SECRET_CANARY_ON_DISK", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
