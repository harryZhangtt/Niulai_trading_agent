import hashlib
from pathlib import Path
import tempfile
import unittest

from factor.dataset import DatasetError, build_snapshot
from factor.dataset.contract import canonical
from factor.dataset.tests.helpers import (clone, descriptor, fixture_copy, read_artifact,
                                          rewrite_artifact, write_descriptor)


class DatasetContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fixture_copy(self.temp.name)

    def test_fixture_builds_with_distinct_stable_identities_and_no_claim(self):
        result = build_snapshot(self.root)
        identities = [result[key] for key in ("observation_set_sha256", "feature_snapshot_sha256",
                                               "evaluation_population_sha256",
                                               "builder_receipt_sha256")]
        self.assertEqual(len(set(identities)), 4)
        self.assertTrue(all(len(value) == 64 for value in identities))
        self.assertTrue(result["fixture_only"])
        self.assertEqual(result["performance_claim"], "withheld")
        self.assertEqual(set(result["split_fingerprints"]),
                         {"development", "validation", "protected"})

    def test_directory_and_dataset_name_do_not_relabel_observations(self):
        first = build_snapshot(self.root)
        other = fixture_copy(Path(self.temp.name) / "other")
        data = descriptor(other); data["dataset_id"] = "repackaged-fixture"
        write_descriptor(other, data)
        second = build_snapshot(other)
        self.assertEqual(first["observation_set_sha256"], second["observation_set_sha256"])
        self.assertEqual(first["evaluation_population_sha256"],
                         second["evaluation_population_sha256"])
        self.assertNotEqual(first["dataset_snapshot_sha256"], second["dataset_snapshot_sha256"])

    def test_row_reordering_is_identity_invariant(self):
        before = build_snapshot(self.root)
        rows = list(reversed(read_artifact(self.root, "observations")))
        rewrite_artifact(self.root, "observations", rows)
        after = build_snapshot(self.root)
        self.assertEqual(before["observation_set_sha256"], after["observation_set_sha256"])
        self.assertEqual(before["feature_snapshot_sha256"], after["feature_snapshot_sha256"])

    def test_changed_observation_changes_evidence_identity(self):
        before = build_snapshot(self.root)
        rows = read_artifact(self.root, "observations")
        row = next(item for item in rows if item["series_id"] == "price-close")
        row["value"] = "777"; row["source_row_sha256"] = "7" * 64
        rewrite_artifact(self.root, "observations", rows)
        after = build_snapshot(self.root)
        self.assertNotEqual(before["observation_set_sha256"], after["observation_set_sha256"])
        self.assertNotEqual(before["evaluation_population_sha256"],
                            after["evaluation_population_sha256"])

    def test_transform_change_only_changes_feature_snapshot(self):
        before = build_snapshot(self.root)
        policy = read_artifact(self.root, "transformations")
        policy["transforms"][0]["lookback_sessions"] = 1
        policy["transforms"][0]["min_periods"] = 2
        rewrite_artifact(self.root, "transformations", policy)
        after = build_snapshot(self.root)
        self.assertEqual(before["observation_set_sha256"], after["observation_set_sha256"])
        self.assertEqual(before["evaluation_population_sha256"],
                         after["evaluation_population_sha256"])
        self.assertNotEqual(before["feature_snapshot_sha256"], after["feature_snapshot_sha256"])

    def test_split_renaming_cannot_reset_population_or_membership_fence(self):
        before = build_snapshot(self.root)
        policy = read_artifact(self.root, "splits")
        for item in policy["splits"]:
            item["id"] = "renamed-" + item["id"]
        rewrite_artifact(self.root, "splits", policy)
        after = build_snapshot(self.root)
        self.assertEqual(before["evaluation_population_sha256"],
                         after["evaluation_population_sha256"])
        self.assertEqual(set(before["split_fingerprints"].values()),
                         set(after["split_fingerprints"].values()))

    def test_duplicate_keys_and_noncanonical_decimals_fail(self):
        source_ref = descriptor(self.root)["artifacts"]["sources"]
        path = self.root / source_ref["path"]
        path.write_text('{"source_id":"x","source_id":"y"}\n')
        raw = path.read_bytes(); source_ref.update(sha256=hashlib.sha256(raw).hexdigest(),
                                                   size_bytes=len(raw), rows=1)
        data = descriptor(self.root); data["artifacts"]["sources"] = source_ref
        write_descriptor(self.root, data)
        with self.assertRaisesRegex(DatasetError, "DUPLICATE_KEY"):
            build_snapshot(self.root)

        self.root = fixture_copy(Path(self.temp.name) / "decimal")
        rows = read_artifact(self.root, "observations")
        next(item for item in rows if item["value"] is not None)["value"] = "1.00"
        rewrite_artifact(self.root, "observations", rows)
        with self.assertRaisesRegex(DatasetError, "DECIMAL_INVALID"):
            build_snapshot(self.root)

    def test_path_hash_symlink_and_secret_canaries_fail(self):
        data = descriptor(self.root); data["artifacts"]["sources"]["path"] = "/tmp/source.jsonl"
        write_descriptor(self.root, data)
        with self.assertRaisesRegex(DatasetError, "PATH_INVALID"):
            build_snapshot(self.root)

        self.root = fixture_copy(Path(self.temp.name) / "hash")
        data = descriptor(self.root); data["artifacts"]["sources"]["sha256"] = "0" * 64
        write_descriptor(self.root, data)
        with self.assertRaisesRegex(DatasetError, "ARTIFACT_MISMATCH"):
            build_snapshot(self.root)

        self.root = fixture_copy(Path(self.temp.name) / "link")
        data = descriptor(self.root); ref = data["artifacts"]["sources"]
        original = self.root / ref["path"]; outside = Path(self.temp.name) / "outside"
        outside.write_bytes(original.read_bytes()); original.unlink(); original.symlink_to(outside)
        with self.assertRaisesRegex(DatasetError, "PATH_INVALID"):
            build_snapshot(self.root)

        self.root = fixture_copy(Path(self.temp.name) / "secret")
        data = descriptor(self.root); data["limitations"].append("api_key=synthetic-canary")
        write_descriptor(self.root, data)
        with self.assertRaisesRegex(DatasetError, "REDACTION_FAILED"):
            build_snapshot(self.root)

    def test_unknown_foreign_keys_and_ambiguous_vintages_fail(self):
        rows = read_artifact(self.root, "observations")
        rows[0]["series_id"] = "unknown-series"
        rewrite_artifact(self.root, "observations", rows)
        with self.assertRaisesRegex(DatasetError, "SERIES_INVALID"):
            build_snapshot(self.root)

        self.root = fixture_copy(Path(self.temp.name) / "ambiguous")
        rows = read_artifact(self.root, "observations")
        original = next(item for item in rows if item["series_id"] == "macro-level" and
                        item["period_end"] == "2026-01-07" and item["source_revision"] == "r1")
        duplicate = clone(original); duplicate["vintage_id"] = "ambiguous-vintage"
        duplicate["value"] = "123"; duplicate["source_row_sha256"] = "1" * 64
        rows.append(duplicate); rewrite_artifact(self.root, "observations", rows)
        with self.assertRaisesRegex(DatasetError, "VINTAGE_AMBIGUOUS"):
            build_snapshot(self.root, end="2026-01-09")


if __name__ == "__main__":
    unittest.main()
