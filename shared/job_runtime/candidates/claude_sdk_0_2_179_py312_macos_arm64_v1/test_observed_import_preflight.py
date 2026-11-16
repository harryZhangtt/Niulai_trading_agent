from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).with_name("observed_import_preflight.py")
SPEC = importlib.util.spec_from_file_location("observed_import_preflight", MODULE_PATH)
assert SPEC and SPEC.loader
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


class StrictJsonTests(unittest.TestCase):
    def test_duplicate_key_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / "duplicate.json"
            path.write_text('{"a":1,"a":2}\n', encoding="utf-8")
            with self.assertRaisesRegex(harness.PreflightError, "DUPLICATE_JSON_KEY:a"):
                harness._load_strict_json(path)

    def test_closed_schema_rejects_unknown_key(self):
        with self.assertRaisesRegex(harness.PreflightError, "NONCANONICAL_SCHEMA:test"):
            harness._closed_keys({"a": 1, "extra": 2}, frozenset({"a"}), "test")


class FrozenArtifactContractTests(unittest.TestCase):
    def test_frozen_hashes_and_counts_are_bound_without_sdk_import(self):
        self.assertEqual(harness._sha256(harness.PLAN_PATH), harness.EXPECTED_PLAN_SHA256)
        self.assertEqual(
            harness._sha256(harness.CANDIDATE_LOCK_PATH),
            harness.EXPECTED_CANDIDATE_LOCK_SHA256,
        )
        plan = harness._load_strict_json(harness.PLAN_PATH)
        lock = harness._load_strict_json(harness.CANDIDATE_LOCK_PATH)
        self.assertEqual(harness._validate_plan(plan), [])
        self.assertEqual(harness._validate_lock(lock, plan), [])
        self.assertEqual(len(plan["expected_output_schema"]["required"]), 21)
        self.assertEqual(len(plan["expected_ready_bindings"]["option_parameters"]), 49)
        self.assertEqual(plan["expected_ready_bindings"]["query_parameters"], ["prompt", "options", "transport"])
        self.assertEqual(lock["sealed_environment"]["package_count"], 30)
        self.assertEqual(lock["sealed_environment"]["dependency_edge_count"], 52)


class OutputContractTests(unittest.TestCase):
    def _output(self):
        return {
            "schema_version": 2,
            "status": "READY_OFFLINE",
            "blockers": [],
            "network_used": False,
            "install_performed": False,
            "declared_requirement": "claude-agent-sdk==0.2.179",
            "installed_version": "0.2.179",
            "python_version": "3.12.16",
            "minimum_python": "3.10",
            "target_runtime_python": "3.12",
            "option_parameters": ["model"],
            "query_parameters": ["prompt", "options"],
            "assistant_fields": ["error", "model"],
            "result_fields": sorted(harness.REFLECTED_REQUIRED["result_fields"]),
            "model_usage_keys": sorted(
                harness.REFLECTED_REQUIRED["model_usage_required_keys"]
                | harness.REFLECTED_REQUIRED["model_usage_optional_keys"]
            ),
            "model_usage_required_keys": sorted(harness.REFLECTED_REQUIRED["model_usage_required_keys"]),
            "model_usage_optional_keys": sorted(harness.REFLECTED_REQUIRED["model_usage_optional_keys"]),
            "package_tree_sha256": "a" * 64,
            "record_sha256": "b" * 64,
            "expected_distribution_tree_sha256": "a" * 64,
            "expected_record_sha256": "b" * 64,
        }

    def test_exact_21_key_ready_output_passes(self):
        output = self._output()
        self.assertEqual(len(output), 21)
        plan = {
            "expected_output_schema": {"required": list(output)},
            "expected_ready_bindings": {
                "schema_version": 2,
                "status": "READY_OFFLINE",
                "blockers": [],
                "network_used": False,
                "install_performed": False,
                **{key: output[key] for key in harness.REFLECTED_REQUIRED},
            },
        }
        parsed, blockers = harness._validate_output(json.dumps(output), plan)
        self.assertEqual(parsed, output)
        self.assertEqual(blockers, [])

    def test_extra_output_key_fails_closed(self):
        output = self._output()
        plan = {
            "expected_output_schema": {"required": list(output)},
            "expected_ready_bindings": {key: output[key] for key in harness.REFLECTED_REQUIRED},
        }
        output["extra"] = True
        _, blockers = harness._validate_output(json.dumps(output), plan)
        self.assertIn("OUTPUT_KEYS_NOT_EXACT_21", blockers)

    def test_nonfinite_json_is_rejected(self):
        plan = {"expected_output_schema": {"required": []}, "expected_ready_bindings": {}}
        _, blockers = harness._validate_output('{"value":NaN}', plan)
        self.assertEqual(blockers, ["CHILD_STDOUT_NOT_SINGLE_STRICT_JSON"])

    def test_reflected_superset_is_rejected(self):
        output = self._output()
        expected = {key: list(output[key]) for key in harness.REFLECTED_REQUIRED}
        plan = {
            "expected_output_schema": {"required": list(output)},
            "expected_ready_bindings": expected,
        }
        output["query_parameters"].append("unexpected")
        _, blockers = harness._validate_output(json.dumps(output), plan)
        self.assertIn("REFLECTED_SURFACE_MISMATCH:query_parameters", blockers)


class DistributionClosureTests(unittest.TestCase):
    def test_unrecorded_sdk_file_is_reported(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            target = Path(temp)
            site = target / "lib/python3.12/site-packages"
            package = site / "claude_agent_sdk"
            dist = site / "claude_agent_sdk-0.2.179.dist-info"
            package.mkdir(parents=True); dist.mkdir()
            (package / "__init__.py").write_text("# fixture\n")
            (package / "injected.py").write_text("# unrecorded fixture\n")
            record = dist / "RECORD"
            record.write_text(
                "claude_agent_sdk/__init__.py,,\n"
                "claude_agent_sdk-0.2.179.dist-info/RECORD,,\n"
            )
            _, _, unrecorded = harness._distribution_hashes(
                target, {"dist_info": "lib/python3.12/site-packages/claude_agent_sdk-0.2.179.dist-info"}
            )
            self.assertEqual(unrecorded, ["claude_agent_sdk/injected.py"])


@unittest.skipUnless(harness.platform.system() == "Darwin", "macOS sandbox_init only")
class SandboxObservationTests(unittest.TestCase):
    PYTHON = "/Users/bytedance/Desktop/Trading Agent/.job-runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3.12"
    LAUNCHER = str(Path(__file__).with_name("sandboxed_import_launcher.py"))

    def _run_mode(self, mode, write_path=None):
        argv = [
            "/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "PYTHONNOUSERSITE=1",
            self.PYTHON, "-P", "-X", "pycache_prefix=/private/var/empty/claude-sdk-preflight-tests",
            self.LAUNCHER, "--self-test", mode,
        ]
        if write_path is not None:
            argv.extend(["--write-path", str(write_path)])
        return harness._run_observed_child(argv, timeout_seconds=10)

    def test_sandbox_allows_local_read_and_import(self):
        result = self._run_mode("read_import")
        self.assertEqual(result["exit_code"], 0, result["stderr"])
        self.assertIsNotNone(result["sandbox_activation"])
        self.assertIn('"status": "ALLOWED"', result["stdout"])
        self.assertEqual(result["child_processes_observed"], 0)

    def test_sandbox_denies_network_write_fork_and_exec(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            write_path = Path(temp) / "forbidden.txt"
            for mode in ("network", "write", "fork", "exec"):
                with self.subTest(mode=mode):
                    result = self._run_mode(mode, write_path if mode == "write" else None)
                    self.assertEqual(result["exit_code"], 0, result["stderr"])
                    self.assertIsNotNone(result["sandbox_activation"])
                    self.assertIn('"status": "DENIED"', result["stdout"])
                    self.assertEqual(result["child_processes_observed"], 0)
                    self.assertFalse(result["bundled_cli_or_bytecli_observed"])
            self.assertFalse(write_path.exists())


class EvidenceWriteTests(unittest.TestCase):
    def test_receipt_is_canonical_fsynced_o_excl(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / "receipt.json"
            harness._write_receipt(path, {"z": 1, "a": 2})
            self.assertEqual(path.read_bytes(), b'{"a":2,"z":1}\n')
            with self.assertRaises(FileExistsError):
                harness._write_receipt(path, {"replacement": True})

    def test_fsync_failure_never_publishes_final_receipt(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / "receipt.json"
            with mock.patch.object(harness.os, "fsync", side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    harness._write_receipt(path, {"status": "BLOCKED"})
            self.assertFalse(path.exists())
            self.assertFalse((path.parent / ".receipt.json.pending").exists())

    def test_directory_fsync_failure_rolls_back_linked_receipt(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / "receipt.json"
            calls = 0
            real_fsync = harness.os.fsync
            def injected(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected directory fsync failure")
                return real_fsync(fd)
            with mock.patch.object(harness.os, "fsync", side_effect=injected):
                with self.assertRaises(OSError):
                    harness._write_receipt(path, {"status": "BLOCKED"})
            self.assertFalse(path.exists())
            self.assertFalse((path.parent / ".receipt.json.pending").exists())

    def test_evidence_directory_must_be_new(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / "evidence"
            harness._reserve_evidence_dir(path)
            with self.assertRaises(FileExistsError):
                harness._reserve_evidence_dir(path)


if __name__ == "__main__":
    unittest.main()
