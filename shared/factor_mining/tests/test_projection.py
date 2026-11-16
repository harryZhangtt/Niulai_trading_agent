import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from shared.factor_mining import manifest, projection
from shared.factor_mining.tests.test_manifest import run_manifest, run_manifest_v2, SHA_A


ROOT = Path(__file__).resolve().parents[3]


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / "shared/factor_mining/runtime/projection-tests"
        runtime.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.registry = self.base / "registry"
        self.artifacts = self.base / "artifacts"; self.artifacts.mkdir()

    def publish_success(self, run_id="success-run"):
        value = run_manifest(); value["run_id"] = run_id; value["status"] = "succeeded"
        for stage in value["stages"]:
            stage.update(status="succeeded", attempt_count=1, receipt_sha256=SHA_A)
        value["gates"][0].update(status="pass", reason_code="fixture-passed",
                                 evidence_sha256=SHA_A)
        value["limitations"] = ["token=SECRET_CANARY should redact", "/Users/private/path",
                                "/private/tmp/factor-project/run.json", "/srv/factor/run.json",
                                "/etc/passwd", "https://example.com/public-doc"]
        artifact = self.artifacts / (run_id + ".json"); artifact.write_bytes(b"artifact")
        value["artifacts"] = [{"id": "output", "kind": "factor-data", "path": artifact.name,
                               "sha256": hashlib.sha256(b"artifact").hexdigest(), "size_bytes": 8}]
        identity = manifest.publish(value, self.registry, self.artifacts)["manifest_sha256"]
        return value, identity

    def publish_failure(self):
        value = run_manifest(); value["run_id"] = "failed-run"; value["status"] = "failed"
        value["stages"][0].update(status="failed", attempt_count=1,
                                  failure_code="runtime-nonzero")
        for stage in value["stages"][1:]: stage["status"] = "skipped"
        value["gates"][0].update(status="fail", reason_code="runtime-nonzero",
                                 evidence_sha256=SHA_A)
        value["failures"] = [{"code": "runtime-nonzero", "stage_id": "propose",
                              "evidence_sha256": SHA_A}]
        return manifest.publish(value, self.registry)["manifest_sha256"]

    def test_overview_is_bounded_redacted_and_has_no_artifact_paths(self):
        self.publish_success(); self.publish_failure()
        result = projection.project(self.registry)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["runs"]), 2)
        serialized = str(result)
        self.assertNotIn("SECRET_CANARY", serialized)
        self.assertNotIn("/Users/private", serialized)
        self.assertNotIn("/path", serialized)
        self.assertNotIn("factor-project", serialized)
        self.assertNotIn("/srv/", serialized)
        self.assertNotIn("/etc/", serialized)
        self.assertIn("https://example.com/public-doc", serialized)
        self.assertIn("/[redacted]", serialized)
        self.assertNotIn("artifacts", result["runs"][0])
        self.assertLess(len(projection.json.dumps(result).encode()), projection.OVERVIEW_LIMIT)

    def test_overview_limit_selects_recently_updated_heads_not_run_ids(self):
        for run_id, timestamp in (("z-old", 1_000_000_000),
                                  ("m-middle", 2_000_000_000),
                                  ("a-new", 3_000_000_000)):
            self.publish_success(run_id)
            head = self.registry / "heads" / f"{run_id}.json"
            os.utime(head, ns=(timestamp, timestamp))
        result = projection.project(self.registry, limit=2)
        self.assertEqual([item["id"] for item in result["runs"]], ["a-new", "m-middle"])

    def test_detail_can_load_head_or_immutable_sha_without_paths(self):
        _, identity = self.publish_success()
        head = projection.project(self.registry, run_id="success-run")
        immutable = projection.project(self.registry, run_id="success-run",
                                       manifest_sha256=identity)
        self.assertEqual(head["runs"], immutable["runs"])
        artifact = head["runs"][0]["artifacts"][0]
        self.assertEqual(set(artifact), {"id", "kind", "sha256", "size_bytes"})
        self.assertNotIn("path", artifact)

    def test_empty_unavailable_and_malformed_run_are_distinct(self):
        self.registry.mkdir()
        self.assertEqual(projection.project(self.registry)["status"], "empty")
        with self.assertRaisesRegex(projection.ProjectionError, "REGISTRY_UNAVAILABLE"):
            projection.project(self.base / "missing")
        heads = self.registry / "heads"; heads.mkdir()
        (heads / "broken-run.json").write_text("{}")
        result = projection.project(self.registry)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["warnings"], [{"run_id": "broken-run", "code": "RUN_UNAVAILABLE"}])
        with self.assertRaisesRegex(projection.ProjectionError, "RUN_UNAVAILABLE"):
            projection.project(self.registry, run_id="broken-run")

    def test_v1_projection_suppresses_fixture_metrics_and_labels_reported_metrics(self):
        synthetic = run_manifest(); synthetic["run_id"] = "fixture-metrics"
        synthetic["factors"] = [{"id": "quality", "family": "fundamental",
            "formula_sha256": SHA_A, "status": "evaluated", "metrics": {"mse": 0.5}}]
        manifest.publish(synthetic, self.registry)
        fixture = projection.project(self.registry, run_id="fixture-metrics")["runs"][0]
        self.assertEqual(fixture["factors"][0]["metrics"], {})
        self.assertEqual(fixture["performance_state"], "withheld_fixture")
        self.assertEqual(fixture["manifest_schema_version"], 1)

        reported = copy.deepcopy(synthetic); reported["run_id"] = "reported-metrics"
        reported["provenance"] = {"origin": "reported_external", "evidence": "unverified"}
        manifest.publish(reported, self.registry)
        visible = projection.project(self.registry, run_id="reported-metrics")["runs"][0]
        self.assertEqual(visible["factors"][0]["metrics"], {"mse": 0.5})
        self.assertEqual(visible["performance_state"], "legacy_reported_unverified")

    def test_v2_performance_is_detail_only_and_hash_bound(self):
        artifact = self.artifacts / "evaluation.json"; artifact.write_bytes(b"evaluation")
        identity = hashlib.sha256(b"evaluation").hexdigest()
        value = run_manifest_v2(identity); value["run_id"] = "performance-run"
        manifest.publish(value, self.registry, self.artifacts)
        overview = projection.project(self.registry)["runs"][0]
        self.assertEqual(overview["manifest_schema_version"], 2)
        self.assertEqual(overview["performance_state"], "available_hash_bound")
        self.assertNotIn("performance", overview)
        detail = projection.project(self.registry, run_id="performance-run")["runs"][0]
        self.assertEqual(detail["performance"], value["performance"])
        self.assertNotIn("path", str(detail["performance"]))

    def test_invalid_filters_fail_closed(self):
        self.registry.mkdir()
        for kwargs in ({"run_id": "../bad"}, {"manifest_sha256": "a" * 64}, {"limit": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(projection.ProjectionError):
                projection.project(self.registry, **kwargs)


if __name__ == "__main__":
    unittest.main()
