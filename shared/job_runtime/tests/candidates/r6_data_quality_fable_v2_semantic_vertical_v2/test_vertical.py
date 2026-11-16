from __future__ import annotations
import ast
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.contracts import CELL_ORDER, DISPOSITIONS
from shared.job_runtime.candidates.r6_data_quality_fable_v2_semantic_vertical_v2.vertical import (
    MANIFESTS, PROMPT_BYTES, PROMPT_SHA256, SOURCE_SHA256, VerticalError,
    adapt_provider_rows, capture_prompt, execute, exercise_disposition,
)
from shared.job_runtime.config import ConfigError, load
from shared.job_runtime.engine import validate_job
from shared.job_runtime.prompt_custody import PromptArtifactStore
from shared.job_runtime.retry_policy import RetryPolicyV2

ROOT = Path(__file__).resolve().parents[5]
FIXTURE = ROOT / "shared/job_runtime/tests/fixtures/r6_data_quality_fable_v2_semantic_vertical_v2"
SOURCE = FIXTURE / "prompt-source-v2.json"
INPUT = json.loads((FIXTURE / "vertical-input-v2.json").read_text())

def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

class SemanticVerticalV2Tests(unittest.TestCase):
    def setUp(self):
        private = FIXTURE / ".runtime"
        private.mkdir(mode=0o700, exist_ok=True)
        private.chmod(0o700)
        self.temp = tempfile.TemporaryDirectory(dir=private)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir(mode=0o700)
        (self.workspace / ".job-runtime").mkdir(mode=0o700)

    def run_vertical(self, *, fault=None, output=None, source=SOURCE):
        return execute(
            repo_root=ROOT, source_path=source, workspace_root=self.workspace,
            output_root=output or self.root / ("bundles-" + (fault or "nominal")),
            evaluation=dt(INPUT["evaluation"]), not_before=dt(INPUT["not_before"]),
            scheduled=dt(INPUT["scheduled"]), deadline=dt(INPUT["deadline"]), fault=fault)

    def install_config_data(self, result):
        state = self.workspace / ".job-runtime" / "config"
        state.mkdir(mode=0o700, exist_ok=True); state.chmod(0o700)
        auth = self.workspace / result["config"]["model_profiles"]["fable-v2"]["auth_home"]
        auth.mkdir(parents=True, mode=0o700, exist_ok=True); auth.chmod(0o700)
        prompts = self.workspace / ".job-runtime" / "config" / "prompts"
        prompts.mkdir(mode=0o700, exist_ok=True); prompts.chmod(0o700)
        prompt_file = self.workspace / ".job-runtime" / "config" / "prompts" / "fable-v2.txt"
        prompt_file.write_bytes(result["prompt_bytes"]); prompt_file.chmod(0o600)
        allocation = self.workspace / result["config"]["allocation_files"][0]
        allocation.write_bytes(json.dumps(result["allocation"], sort_keys=True).encode()); allocation.chmod(0o600)
        config = state / "config.json"
        config.write_bytes(json.dumps(result["config"], sort_keys=True).encode()); config.chmod(0o600)
        return config

    def test_nominal_full_vertical_real_engine_custody_lineage_and_budget(self):
        result = self.run_vertical()
        self.assertEqual((result["prompt"]["bytes"], result["prompt"]["sha256"]),
                         (PROMPT_BYTES, PROMPT_SHA256))
        self.assertEqual(hashlib.sha256(result["prompt_bytes"]).hexdigest(), PROMPT_SHA256)
        self.assertEqual(result["bridge"]["receipt"]["row_count"], 2)
        self.assertEqual(result["bridge"]["receipt"]["source_sha256"],
                         result["bridge"]["receipt"]["snapshot_sha256"])
        self.assertEqual((result["integration"]["result"]["denominator_count"],
                          result["integration"]["result"]["publication_attempts"],
                          result["integration"]["restart_verified"]), (2, 0, True))
        self.assertEqual(result["integration"]["runtime_prompt_sha256"], PROMPT_SHA256)
        self.assertNotEqual(result["integration"]["legacy_ab_prompt_sha256"], PROMPT_SHA256)
        self.assertEqual(result["proposal"]["classification"],
                         "DATA_ONLY_NOT_CONFIG_V2_NOT_ENGINE_INSTALLABLE")
        self.assertEqual((result["materialized"]["evaluation_time"],
                          result["materialized"]["scheduled_at"],
                          result["materialized"]["window_seconds"]),
                         (INPUT["evaluation"], INPUT["scheduled"], 300))
        self.assertEqual(result["budget"], {
            "currency": "USD", "per_arm_max_budget_usd": 0.02,
            "aggregate_ceiling_usd": 0.04, "user_approved": True,
            "billed_authority": False, "prompt_utf8_bytes": 526,
            "token_evidence": "UNMEASURED_PROVIDER_FREE"})
        self.assertTrue(all(value == 0 for value in result["effects"].values()))
        self.assertFalse(result["activation"])

    def test_real_config_load_captures_526_and_engine_validate_job(self):
        result = self.run_vertical(output=self.root / "config-bundles")
        config_path = self.install_config_data(result)
        cwd = os.getcwd()
        os.chdir(self.workspace)
        try:
            config, jobs = load(config_path, self.workspace)
        finally:
            os.chdir(cwd)
        self.assertEqual(config["schema_version"], 2)
        self.assertEqual(len(jobs), 2)
        for job in jobs:
            self.assertEqual((job["_prompt_capture"].length, job["_prompt_capture"].sha256),
                             (526, PROMPT_SHA256))
            capture = job["_prompt_capture"]
            store = PromptArtifactStore(self.workspace)
            artifact = store.publish(capture, "schema9-isolated-canary-q1-ab-payload-v1", "native_v1")
            self.assertTrue(store.verify(artifact))
            with store.open(artifact) as lease:
                self.assertEqual(b"".join(lease.chunks()), result["prompt_bytes"])
            candidate = {key: value for key, value in job.items() if key != "_prompt_capture"}
            candidate.update({
                "replay_safe": False,
                "_provider": "claude_host",
                "_retry_policy": RetryPolicyV2(1, 1, 1, 240),
                "_prompt_artifact": artifact,
                "_resource_key": "fable-v2-serialized",
            })
            validate_job(candidate)

    def test_each_manifest_digest_is_consumed_by_real_output_lineage(self):
        result = self.run_vertical(output=self.root / "lineage-bundles")
        expected = [sha for _, sha in MANIFESTS]
        observed = [item["consumed_canonical_output_sha256"] for item in result["semantic_lineage"]]
        self.assertEqual(observed, expected)
        self.assertEqual([item["stage"] for item in result["semantic_lineage"]],
                         [name for name, _ in MANIFESTS])
        for index, item in enumerate(result["semantic_lineage"]):
            self.assertRegex(item["actual_output_sha256"], r"^[0-9a-f]{64}$")
            if index:
                self.assertEqual(item["parent_semantic_output_sha256"],
                                 result["semantic_lineage"][index - 1]["actual_output_sha256"])
        self.assertEqual(result["final_sha256"],
                         result["semantic_lineage"][-1]["semantic_receipt_sha256"])

    def test_all_six_reviewed_dispositions_use_bundle_contract(self):
        for terminal in ("PASS", "FAIL", "STOP", "MALFORMED", "MISSING", "UNKNOWN"):
            output = exercise_disposition(SOURCE, self.root / ("disposition-" + terminal), terminal)
            for cell in output["result"]["cells"]:
                self.assertEqual(cell["disposition"], DISPOSITIONS[terminal])
                self.assertTrue(cell["denominator_included"])
                self.assertEqual(cell["publication"]["attempts"], 0)
                self.assertEqual(cell["publication"]["unknown_fenced"], terminal == "UNKNOWN")
            self.assertEqual(output["result"]["cells"][0]["disposition"], DISPOSITIONS[terminal])
            self.assertTrue(output["restart_verified"])

    def test_prompt_boundary_rejects_hash_symlink_and_injected_fault(self):
        descriptor, prompt, custody = capture_prompt(SOURCE)
        self.assertEqual((descriptor.sha256, descriptor.length, hashlib.sha256(prompt).hexdigest()),
                         (PROMPT_SHA256, PROMPT_BYTES, PROMPT_SHA256))
        tampered = self.root / "tampered.json"
        tampered.write_bytes(SOURCE.read_bytes() + b" "); tampered.chmod(0o600)
        with self.assertRaisesRegex(VerticalError, "PROMPT_SOURCE_HASH"):
            capture_prompt(tampered)
        link = self.root / "source-link"
        link.symlink_to(SOURCE)
        with self.assertRaisesRegex(VerticalError, "PROMPT_SOURCE_CUSTODY"):
            capture_prompt(link)
        with self.assertRaisesRegex(VerticalError, "INJECTED_PROMPT_BOUNDARY"):
            self.run_vertical(fault="prompt", output=self.root / "prompt-fault")

    def test_engine_row_boundary_rejects_canonical_digest_drift(self):
        with self.assertRaisesRegex(VerticalError, "ENGINE_ROW_DIGEST"):
            self.run_vertical(fault="engine_row", output=self.root / "row-fault")

    def test_adapter_boundary_rejects_descriptor_provenance_drift(self):
        with self.assertRaisesRegex(VerticalError, "ADAPTER_DESCRIPTOR_PROVENANCE"):
            self.run_vertical(fault="adapter", output=self.root / "adapter-fault")

    def test_db_snapshot_boundary_rejects_descriptor_mismatch_and_sidecar(self):
        with self.assertRaisesRegex(VerticalError, "DB_SOURCE_DESCRIPTOR_MISMATCH"):
            self.run_vertical(fault="db_snapshot", output=self.root / "db-fault")
        database = self.workspace / ".job-runtime" / "semantic-v2-engine" / "schedule.sqlite"
        self.assertEqual(list(database.parent.glob(".*semantic-v2-snapshot")), [])

    def test_output_custody_boundary_rejects_restart_tamper(self):
        with self.assertRaisesRegex(VerticalError, "OUTPUT_CUSTODY_OR_RESTART"):
            self.run_vertical(fault="output_custody", output=self.root / "output-fault")

    def test_integration_schedule_and_config_boundaries_fail_closed(self):
        for fault, code in (("integration", "INJECTED_INTEGRATION_BOUNDARY"),
                            ("schedule", "TIME_SCHEDULED"),
                            ("config", "INJECTED_CONFIG_BOUNDARY")):
            # Each fault needs a fresh Engine workspace because one-off slots are durable.
            workspace = self.root / ("workspace-" + fault)
            workspace.mkdir(mode=0o700); (workspace / ".job-runtime").mkdir(mode=0o700)
            old = self.workspace; self.workspace = workspace
            try:
                with self.assertRaisesRegex(VerticalError, code):
                    self.run_vertical(fault=fault, output=self.root / ("fault-" + fault))
            finally:
                self.workspace = old

    def test_config_load_boundary_rejects_translation_drift(self):
        workspace = self.root / "workspace-config-drift"
        workspace.mkdir(mode=0o700); (workspace / ".job-runtime").mkdir(mode=0o700)
        old = self.workspace; self.workspace = workspace
        try:
            result = self.run_vertical(output=self.root / "config-drift-bundles")
            config_path = self.install_config_data(result)
            value = json.loads(config_path.read_text())
            value["model_profiles"]["fable-v2"]["max_budget_usd"] = 0
            config_path.write_text(json.dumps(value)); config_path.chmod(0o600)
            cwd = os.getcwd(); os.chdir(self.workspace)
            try:
                with self.assertRaisesRegex(ConfigError, "PROFILE_CLAUDE_OPTIONS_INVALID"):
                    load(config_path, self.workspace)
            finally:
                os.chdir(cwd)
        finally:
            self.workspace = old

    def test_duplicate_attempt_and_row_shape_reject(self):
        descriptor, _, _ = capture_prompt(SOURCE)
        from shared.job_runtime.candidates.r6_data_quality_fable_v2_semantic_vertical_v2.vertical import _synthetic_rows
        rows, expected = _synthetic_rows(descriptor, "PASS")
        expected[1]["attempt_id"] = expected[0]["attempt_id"]
        with self.assertRaises(VerticalError):
            adapt_provider_rows(rows, expected, self.root / "duplicate")
        rows, expected = _synthetic_rows(descriptor, "PASS")
        rows[0]["extra"] = "forbidden"
        with self.assertRaisesRegex(VerticalError, "ENGINE_ROW_SHAPE"):
            adapt_provider_rows(rows, expected, self.root / "shape")

    def test_source_fixture_is_exact_real_prompt_source(self):
        raw = SOURCE.read_bytes()
        self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (2065, SOURCE_SHA256))
        prompt = json.loads(raw)["prompt_utf8"].encode("utf-8")
        self.assertEqual((len(prompt), hashlib.sha256(prompt).hexdigest()),
                         (PROMPT_BYTES, PROMPT_SHA256))

    def test_static_provider_network_email_business_ixic_fence(self):
        source = (ROOT / "shared/job_runtime/candidates/r6_data_quality_fable_v2_semantic_vertical_v2/vertical.py").read_text()
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertTrue(imports.isdisjoint({"anthropic", "requests", "urllib", "socket", "smtplib",
                                            "subprocess", "service", "provider", "ixic"}))
        self.assertNotIn("IXIC", source.upper())

if __name__ == "__main__":
    unittest.main()
