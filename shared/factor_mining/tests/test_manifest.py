import copy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from shared.factor_mining import manifest


ROOT = Path(__file__).resolve().parents[3]
RD_REV = "484776c211e4fbbeef03e0ec00d6bbee7362a4f4"
RD_TREE = "d4444284fb4554f75f352ecb1f072cedbf4c6421"
QLIB_REV = "2fb9380b342556ddb50a4b24e4fe8655d548b2b8"
QLIB_TREE = "0f541590a9efecb9bfb5342155be50461ad7d002"
SHA_A = "a" * 64
SHA_B = "b" * 64


def run_manifest(revision=1, status="planned", previous=None, provenance=None):
    return {
        "schema_version": 1,
        "kind": "factor_run_manifest",
        "run_id": "synthetic-adapter-run",
        "revision": revision,
        "previous_manifest_sha256": previous,
        "created_at": f"2026-11-04T00:00:00.{revision:06d}Z",
        "status": status,
        "provenance": provenance or {"origin": "synthetic_fixture", "evidence": "fixture_only"},
        "engine": {
            "rdagent_revision": RD_REV,
            "rdagent_tree": RD_TREE,
            "qlib_profile": "qlib-rdagent-compatible",
            "qlib_revision": QLIB_REV,
            "qlib_tree": QLIB_TREE,
            "adapter_version": "rdagent-adapter-v1",
        },
        "protocol_sha256": None,
        "dataset_snapshot_sha256": None,
        "stages": [
            {"id": "propose", "status": "pending", "attempt_count": 0,
             "receipt_sha256": None, "failure_code": None},
            {"id": "factor-output", "status": "pending", "attempt_count": 0,
             "receipt_sha256": None, "failure_code": None},
        ],
        "artifacts": [],
        "factors": [],
        "gates": [
            {"id": "implementation", "dimension": "implementation", "status": "pending",
             "reason_code": None, "evidence_sha256": None},
            {"id": "publication", "dimension": "publication", "status": "withheld",
             "reason_code": "fixture-only", "evidence_sha256": None},
        ],
        "failures": [],
        "resources": {"wall_seconds": 0.0, "cpu_seconds": 0.0,
                      "peak_rss_bytes": 0, "cache_hit": False},
        "limitations": ["Synthetic fixture only; no upstream engine or alpha evidence."],
    }


def performance_record(evidence_sha256=SHA_A, availability="available"):
    value = {
        "id": "standalone-quality",
        "subject": {"kind": "standalone", "factor_ids": ["quality"],
                    "omitted_factor_id": None},
        "availability": availability,
        "reason_code": None,
        "metric_id": "net-log-growth",
        "estimate_unit": "decimal",
        "point_estimate": 0.01,
        "uncertainty": {"kind": "block-bootstrap", "lower": -0.01, "upper": 0.03,
                        "level": 0.95},
        "sample": {"size": 33, "unit": "monthly-origin"},
        "period": {"id": "protected", "start": "2022-01-01", "end": "2025-01-01"},
        "baseline_id": "rv20",
        "evidence_sha256": evidence_sha256,
    }
    if availability == "unavailable":
        value.update(reason_code="not-recorded", point_estimate=None, uncertainty=None,
                     sample=None, evidence_sha256=None)
    return value


def run_manifest_v2(evidence_sha256=SHA_A, *, availability="available"):
    value = run_manifest(provenance={"origin": "reproduced_local", "evidence": "hash_bound"})
    value["schema_version"] = 2
    value["protocol_sha256"] = SHA_A
    value["dataset_snapshot_sha256"] = SHA_B
    value["factors"] = [{"id": "quality", "family": "fundamental",
                         "formula_sha256": SHA_A, "status": "evaluated",
                         "metrics": {"net-log-growth": 0.01}}]
    value["artifacts"] = [{"id": "evaluation", "kind": "evaluation",
                           "path": "evaluation.json", "sha256": evidence_sha256,
                           "size_bytes": 10}]
    value["performance"] = [performance_record(evidence_sha256, availability)]
    return value


def publish_worker(registry, value, queue):
    try:
        queue.put(("ok", manifest.publish(value, registry)["manifest_sha256"]))
    except Exception as error:
        queue.put(("error", str(error)))


class ManifestTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / "shared/factor_mining/runtime/tests"
        runtime.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.registry = self.base / "registry"
        self.artifacts = self.base / "artifacts"
        self.artifacts.mkdir()

    def test_publish_is_immutable_idempotent_and_loadable(self):
        value = run_manifest()
        first = manifest.publish(value, self.registry)
        second = manifest.publish(value, self.registry)
        self.assertEqual(first, second)
        loaded = manifest.load_head(self.registry, value["run_id"])
        self.assertEqual(loaded["manifest"], value)
        path = self.registry / "manifests" / value["run_id"] / (first["manifest_sha256"] + ".json")
        before = path.read_bytes()
        manifest.load_head(self.registry, value["run_id"])
        self.assertEqual(path.read_bytes(), before)

    def test_revision_chain_and_terminal_transitions(self):
        first = run_manifest()
        first_ref = manifest.publish(first, self.registry)["manifest_sha256"]
        second = run_manifest(2, "running", first_ref)
        second["stages"][0].update(status="running", attempt_count=1)
        second_ref = manifest.publish(second, self.registry)["manifest_sha256"]
        third = run_manifest(3, "succeeded", second_ref)
        third["stages"][0].update(status="succeeded", attempt_count=1,
                                  receipt_sha256=SHA_A)
        third["stages"][1].update(status="skipped", attempt_count=0)
        manifest.publish(third, self.registry)
        fourth = run_manifest(4, "running", manifest.digest(third))
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_STATUS_TRANSITION_INVALID"):
            manifest.publish(fourth, self.registry)

    def test_wrong_or_skipped_revision_is_rejected(self):
        first_ref = manifest.publish(run_manifest(), self.registry)["manifest_sha256"]
        wrong = run_manifest(2, "running", SHA_A)
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_REVISION_CONFLICT"):
            manifest.publish(wrong, self.registry)
        skipped = run_manifest(3, "running", first_ref)
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_REVISION_CONFLICT"):
            manifest.publish(skipped, self.registry)

    def test_reported_claims_cannot_alias_reproduced_evidence(self):
        reported = run_manifest(provenance={"origin": "reported_external", "evidence": "hash_bound"})
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_PROVENANCE_INVALID"):
            manifest.validate(reported)
        reproduced = run_manifest(provenance={"origin": "reproduced_local", "evidence": "hash_bound"})
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_REPRODUCTION_BINDING_REQUIRED"):
            manifest.validate(reproduced)

    def test_artifact_hash_path_and_symlink_are_verified(self):
        artifact = self.artifacts / "factor.json"
        artifact.write_bytes(b"factor-output")
        value = run_manifest()
        value["artifacts"] = [{"id": "factor-output", "kind": "factor-data",
                               "path": "factor.json",
                               "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                               "size_bytes": artifact.stat().st_size}]
        manifest.publish(value, self.registry, self.artifacts)
        bad = run_manifest(); bad["run_id"] = "bad-artifact"
        bad["artifacts"] = [dict(value["artifacts"][0], sha256=SHA_A)]
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_ARTIFACT_MISMATCH"):
            manifest.publish(bad, self.registry, self.artifacts)
        outside = self.base / "outside"; outside.write_bytes(b"factor-output")
        link = self.artifacts / "linked.json"; link.symlink_to(outside)
        linked = run_manifest(); linked["run_id"] = "linked-artifact"
        linked["artifacts"] = [dict(value["artifacts"][0], path="linked.json")]
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_ARTIFACT_PATH_INVALID"):
            manifest.publish(linked, self.registry, self.artifacts)

    def test_duplicate_keys_nonfinite_and_oversize_fail(self):
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_DUPLICATE_KEY"):
            manifest.loads_strict('{"a":1,"a":2}')
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_NONFINITE"):
            manifest.loads_strict('{"a":NaN}')
        value = run_manifest()
        value["limitations"] = ["x" * 1001]
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_LIMITATIONS_INVALID"):
            manifest.validate(value)

    def test_stage_artifact_factor_and_failure_history_cannot_regress(self):
        first = run_manifest()
        first_ref = manifest.publish(first, self.registry)["manifest_sha256"]
        second = run_manifest(2, "running", first_ref)
        second["stages"][0].update(status="running", attempt_count=1)
        second["failures"] = [{"code": "transient", "stage_id": "propose", "evidence_sha256": None}]
        second_ref = manifest.publish(second, self.registry)["manifest_sha256"]
        third = copy.deepcopy(second)
        third.update(revision=3, previous_manifest_sha256=second_ref,
                     created_at="2026-11-04T00:00:03Z")
        third["failures"] = []
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_FAILURE_HISTORY_CHANGED"):
            manifest.publish(third, self.registry)

    def test_fifo_artifact_fails_without_blocking(self):
        fifo = self.artifacts / "blocked.fifo"
        os.mkfifo(fifo)
        value = run_manifest(); value["run_id"] = "fifo-artifact"
        value["artifacts"] = [{"id": "fifo", "kind": "factor-data", "path": "blocked.fifo",
                               "sha256": SHA_A, "size_bytes": 1}]
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_ARTIFACT_INVALID"):
            manifest.publish(value, self.registry, self.artifacts)

    def test_orphaned_immutable_manifest_is_recovered_by_publish(self):
        value = run_manifest()
        payload = manifest.canonical(value)
        identity = hashlib.sha256(payload).hexdigest()
        self.registry.mkdir()
        path = manifest._manifest_path(self.registry, value["run_id"], identity)
        manifest._atomic_write(path, payload)
        published = manifest.publish(value, self.registry)
        self.assertEqual(published["manifest_sha256"], identity)
        self.assertEqual(manifest.load_head(self.registry, value["run_id"])["manifest"], value)

    def test_malformed_head_fails_with_stable_error(self):
        value = run_manifest()
        self.registry.mkdir()
        path = manifest._head_path(self.registry, value["run_id"])
        manifest._atomic_write(path, b'{"schema_version":1}', replace=True)
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_HEAD_INVALID"):
            manifest.publish(value, self.registry)

    def test_terminal_stage_and_gate_evidence_cannot_change(self):
        first_ref = manifest.publish(run_manifest(), self.registry)["manifest_sha256"]
        second = run_manifest(2, "running", first_ref)
        second["stages"][0].update(status="running", attempt_count=1)
        second_ref = manifest.publish(second, self.registry)["manifest_sha256"]
        third = copy.deepcopy(second)
        third.update(revision=3, previous_manifest_sha256=second_ref,
                     created_at="2026-11-04T00:00:03Z")
        third["stages"][0].update(status="succeeded", receipt_sha256=SHA_A)
        third["gates"][0].update(status="pass", reason_code="verified",
                                 evidence_sha256=SHA_A)
        third_ref = manifest.publish(third, self.registry)["manifest_sha256"]
        changed_stage = copy.deepcopy(third)
        changed_stage.update(revision=4, previous_manifest_sha256=third_ref,
                             created_at="2026-11-04T00:00:04Z")
        changed_stage["stages"][0]["receipt_sha256"] = SHA_B
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_TERMINAL_STAGE_CHANGED"):
            manifest.publish(changed_stage, self.registry)
        changed_gate = copy.deepcopy(third)
        changed_gate.update(revision=4, previous_manifest_sha256=third_ref,
                            created_at="2026-11-04T00:00:04Z")
        changed_gate["gates"][0]["evidence_sha256"] = SHA_B
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_TERMINAL_GATE_CHANGED"):
            manifest.publish(changed_gate, self.registry)

    def test_malformed_code_types_raise_manifest_error(self):
        for field, value in (("failure_code", 1),):
            changed = run_manifest(); changed["stages"][0][field] = value
            with self.assertRaises(manifest.ManifestError):
                manifest.validate(changed)
        changed = run_manifest(); changed["gates"][0]["reason_code"] = []
        with self.assertRaises(manifest.ManifestError):
            manifest.validate(changed)
        changed = run_manifest(); changed["factors"] = [{"id": "x", "family": "x",
            "formula_sha256": None, "status": "pending", "metrics": {1: 2.0}}]
        with self.assertRaises(manifest.ManifestError):
            manifest.validate(changed)

    def test_concurrent_creation_of_missing_registry_is_idempotent(self):
        value = run_manifest()
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        workers = [context.Process(target=publish_worker, args=(str(self.registry), value, queue))
                   for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(10)
        results = [queue.get(timeout=2) for _ in workers]
        self.assertEqual(sum(result[0] == "ok" for result in results), 2)
        self.assertEqual(len({result[1] for result in results}), 1)

    def test_load_by_immutable_sha_does_not_depend_on_head(self):
        value = run_manifest()
        identity = manifest.publish(value, self.registry)["manifest_sha256"]
        self.assertEqual(manifest.load_manifest(self.registry, value["run_id"], identity), value)

    def test_dot_artifact_path_and_cross_run_sha_are_rejected(self):
        value = run_manifest(); value["artifacts"] = [
            {"id": "dot", "kind": "factor-data", "path": ".", "sha256": SHA_A, "size_bytes": 1}]
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_ARTIFACT_PATH_INVALID"):
            manifest.validate(value)
        first = run_manifest(); identity = manifest.publish(first, self.registry)["manifest_sha256"]
        wrong_path = manifest._manifest_path(self.registry, "other-run", identity)
        source = manifest._manifest_path(self.registry, first["run_id"], identity).read_bytes()
        manifest._atomic_write(wrong_path, source)
        with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_RUN_ID_MISMATCH"):
            manifest.load_manifest(self.registry, "other-run", identity)

    def test_write_failure_cleans_temporary_file_for_retry(self):
        directory = self.base / "atomic"; directory.mkdir()
        path = directory / "value.json"
        with mock.patch.object(manifest.os, "fsync", side_effect=OSError("synthetic")):
            with self.assertRaises(OSError):
                manifest._atomic_write(path, b"value")
        self.assertEqual(list(directory.iterdir()), [])
        manifest._atomic_write(path, b"value")
        self.assertEqual(path.read_bytes(), b"value")

    def test_artifact_growth_during_hashing_is_rejected(self):
        artifact = self.artifacts / "growing.bin"; artifact.write_bytes(b"original")
        value = run_manifest(); value["run_id"] = "growing-artifact"
        value["artifacts"] = [{"id": "growing", "kind": "factor-data", "path": "growing.bin",
                               "sha256": hashlib.sha256(b"original").hexdigest(), "size_bytes": 8}]
        original_read = manifest.os.read
        mutated = False
        def growing_read(descriptor, count):
            nonlocal mutated
            data = original_read(descriptor, count)
            if data and not mutated:
                mutated = True
                with artifact.open("ab") as stream:
                    stream.write(b"-changed")
            return data
        with mock.patch.object(manifest.os, "read", side_effect=growing_read):
            with self.assertRaisesRegex(manifest.ManifestError, "FACTOR_MANIFEST_ARTIFACT_MUTATED"):
                manifest.publish(value, self.registry, self.artifacts)

    def test_concurrent_different_revision_two_has_one_winner(self):
        first_ref = manifest.publish(run_manifest(), self.registry)["manifest_sha256"]
        candidate_a = run_manifest(2, "running", first_ref)
        candidate_a["stages"][0].update(status="running", attempt_count=1)
        candidate_b = copy.deepcopy(candidate_a)
        candidate_b["limitations"] = ["Different competing publisher."]
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        workers = [context.Process(target=publish_worker, args=(str(self.registry), value, queue))
                   for value in (candidate_a, candidate_b)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(10)
        results = [queue.get(timeout=2) for _ in workers]
        self.assertEqual(sum(result[0] == "ok" for result in results), 1)
        self.assertEqual(sum(result[0] == "error" for result in results), 1)
        self.assertEqual(manifest.load_head(self.registry, "synthetic-adapter-run")["manifest"]["revision"], 2)

    def test_v2_supports_structured_subjects_and_explicit_unavailable(self):
        value = run_manifest_v2()
        value["factors"].extend([
            {"id": "value", "family": "fundamental", "formula_sha256": SHA_A,
             "status": "evaluated", "metrics": {"net-log-growth": 0.02}},
            {"id": "momentum", "family": "price", "formula_sha256": SHA_B,
             "status": "evaluated", "metrics": {"net-log-growth": -0.01}},
        ])
        combination = copy.deepcopy(value["performance"][0])
        combination.update(id="quality-value", subject={"kind": "combination",
            "factor_ids": ["quality", "value"], "omitted_factor_id": None})
        ablation = performance_record(availability="unavailable")
        ablation.update(id="without-momentum", subject={"kind": "leave_one_out",
            "factor_ids": ["quality", "value"], "omitted_factor_id": "momentum"})
        value["performance"].extend([combination, ablation])
        self.assertIs(manifest.validate(value), value)

    def test_v2_rejects_unsafe_performance_evidence_and_values(self):
        cases = []
        synthetic = run_manifest_v2()
        synthetic["provenance"] = {"origin": "synthetic_fixture", "evidence": "fixture_only"}
        synthetic["protocol_sha256"] = None; synthetic["dataset_snapshot_sha256"] = None
        cases.append((synthetic, "SYNTHETIC_PERFORMANCE"))
        unknown = run_manifest_v2(); unknown["performance"][0]["subject"]["factor_ids"] = ["missing"]
        cases.append((unknown, "SUBJECT_INVALID"))
        reversed_bounds = run_manifest_v2()
        reversed_bounds["performance"][0]["uncertainty"].update(lower=2.0, upper=1.0)
        cases.append((reversed_bounds, "UNCERTAINTY_INVALID"))
        unsafe_sample = run_manifest_v2(); unsafe_sample["performance"][0]["sample"]["size"] = 2**53
        cases.append((unsafe_sample, "SAMPLE_INVALID"))
        wrong_evidence = run_manifest_v2(SHA_B)
        wrong_evidence["artifacts"][0]["sha256"] = SHA_A
        cases.append((wrong_evidence, "EVIDENCE_INVALID"))
        leaked_unavailable = run_manifest_v2(availability="unavailable")
        leaked_unavailable["performance"][0]["point_estimate"] = 0.0
        cases.append((leaked_unavailable, "UNAVAILABLE_INVALID"))
        for value, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(manifest.ManifestError, code):
                manifest.validate(value)

    def test_v2_performance_history_is_append_only(self):
        artifact = self.artifacts / "evaluation.json"; artifact.write_bytes(b"evaluation")
        identity = hashlib.sha256(b"evaluation").hexdigest()
        first = run_manifest_v2(identity)
        first_ref = manifest.publish(first, self.registry, self.artifacts)["manifest_sha256"]
        second = copy.deepcopy(first)
        second.update(revision=2, previous_manifest_sha256=first_ref,
                      created_at="2026-11-04T00:00:02Z", status="running")
        second["stages"][0].update(status="running", attempt_count=1)
        unavailable = performance_record(availability="unavailable")
        unavailable["id"] = "future-combination"
        second["performance"].append(unavailable)
        second_ref = manifest.publish(second, self.registry, self.artifacts)["manifest_sha256"]
        changed = copy.deepcopy(second)
        changed.update(revision=3, previous_manifest_sha256=second_ref,
                       created_at="2026-11-04T00:00:03Z")
        changed["performance"][0]["point_estimate"] = 0.02
        with self.assertRaisesRegex(manifest.ManifestError, "PERFORMANCE_HISTORY_CHANGED"):
            manifest.publish(changed, self.registry, self.artifacts)


if __name__ == "__main__":
    unittest.main()
