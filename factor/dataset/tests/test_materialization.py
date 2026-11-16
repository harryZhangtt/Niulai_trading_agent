from pathlib import Path
import tempfile
import unittest

from factor.dataset import DatasetError, build_snapshot
from factor.dataset.tests.helpers import (fixture_copy, read_artifact, refresh_label_authority,
                                          rewrite_artifact)


class DatasetMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fixture_copy(self.temp.name)

    def test_crop_and_execution_directory_are_deterministic(self):
        full = build_snapshot(self.root)
        cropped = build_snapshot(self.root, start="2026-01-06", end="2026-01-14")
        overlap = [row for row in full["features"]
                   if "2026-01-06" <= row["session_date"] <= "2026-01-14"]
        self.assertEqual(overlap, cropped["features"])
        other = fixture_copy(Path(self.temp.name) / "different-working-root")
        self.assertEqual(full["features"], build_snapshot(other)["features"])
        self.assertEqual(full["feature_snapshot_sha256"],
                         build_snapshot(other)["feature_snapshot_sha256"])

    def test_future_vintage_cannot_change_earlier_crop(self):
        before = build_snapshot(self.root, end="2026-01-09")
        rows = read_artifact(self.root, "observations")
        rows = [row for row in rows if row["vintage_id"] != "m-2026-01-07-r2"]
        rewrite_artifact(self.root, "observations", rows)
        after = build_snapshot(self.root, end="2026-01-09")
        self.assertEqual(before["features"], after["features"])
        self.assertNotEqual(before["observation_set_sha256"], after["observation_set_sha256"])

    def test_labels_never_enter_feature_or_sample_output(self):
        result = build_snapshot(self.root)
        serialized = str({"features": result["features"], "samples": result["samples"]})
        for marker in ("0.01", "0.02", "label_values", "log-return"):
            self.assertNotIn(marker, serialized)
        self.assertTrue(all("semantic_sample_sha256" in item and "sample_id" not in item and
                            "window_end_session" in item for item in result["samples"]))

    def test_label_commitment_changes_population_without_exposing_value(self):
        before = build_snapshot(self.root)
        values = read_artifact(self.root, "label_values")
        values[0]["value"] = "0.5"
        rewrite_artifact(self.root, "label_values", values)
        refresh_label_authority(self.root)
        after = build_snapshot(self.root)
        self.assertEqual(before["observation_set_sha256"], after["observation_set_sha256"])
        self.assertNotEqual(before["label_commitment_sha256"], after["label_commitment_sha256"])
        self.assertNotEqual(before["evaluation_population_sha256"],
                            after["evaluation_population_sha256"])
        self.assertNotIn("0.5", str(after["builder_receipt"]))

    def test_alias_rename_is_invariant_but_membership_removal_changes_fence(self):
        before = build_snapshot(self.root)
        roster = read_artifact(self.root, "label_roster")
        values = read_artifact(self.root, "label_values")
        next(row for row in roster if row["sample_id"] == "prot-bbb")["sample_id"] = "alias-only"
        next(row for row in values if row["sample_id"] == "prot-bbb")["sample_id"] = "alias-only"
        rewrite_artifact(self.root, "label_roster", roster)
        rewrite_artifact(self.root, "label_values", values)
        refresh_label_authority(self.root)
        renamed = build_snapshot(self.root)
        self.assertEqual(before["label_roster_sha256"], renamed["label_roster_sha256"])
        self.assertEqual(before["evaluation_population_sha256"],
                         renamed["evaluation_population_sha256"])
        self.assertEqual(before["split_fingerprints"], renamed["split_fingerprints"])

        roster = [row for row in roster if row["sample_id"] != "alias-only"]
        values = [row for row in values if row["sample_id"] != "alias-only"]
        rewrite_artifact(self.root, "label_roster", roster)
        rewrite_artifact(self.root, "label_values", values)
        refresh_label_authority(self.root)
        removed = build_snapshot(self.root)
        self.assertNotEqual(before["split_fingerprints"]["protected"],
                            removed["split_fingerprints"]["protected"])

    def test_missing_observation_is_not_coerced_to_zero(self):
        result = build_snapshot(self.root)
        macro_values = [row["features"]["macro-diff-2"] for row in result["features"]]
        self.assertIn(None, macro_values)
        self.assertNotEqual(set(macro_values), {"0"})

    def test_same_bar_execution_and_short_purge_fail_closed(self):
        execution = read_artifact(self.root, "execution")
        execution["signal_lag_sessions"] = 0; execution["trade_at"] = "session_close"
        rewrite_artifact(self.root, "execution", execution)
        with self.assertRaisesRegex(DatasetError, "EXECUTION_INVALID"):
            build_snapshot(self.root)

        self.root = fixture_copy(Path(self.temp.name) / "purge")
        split = read_artifact(self.root, "splits")
        split["horizon_sessions"] = 2; split["purge_sessions"] = 1
        rewrite_artifact(self.root, "splits", split)
        with self.assertRaisesRegex(DatasetError, "SPLIT_POLICY_INVALID"):
            build_snapshot(self.root)

    def test_supplied_label_authority_and_split_hashes_cannot_be_forged(self):
        authority = read_artifact(self.root, "label_authority")
        authority["label_commitment_sha256"] = "0" * 64
        rewrite_artifact(self.root, "label_authority", authority)
        with self.assertRaisesRegex(DatasetError, "AUTHORITY_MISMATCH"):
            build_snapshot(self.root)
        # Split fingerprints are outputs only; the split input schema rejects an asserted value.
        self.root = fixture_copy(Path(self.temp.name) / "split-assertion")
        split = read_artifact(self.root, "splits")
        split["splits"][0]["fingerprint_sha256"] = "0" * 64
        rewrite_artifact(self.root, "splits", split)
        with self.assertRaisesRegex(DatasetError, "SPLIT_ITEM_SCHEMA"):
            build_snapshot(self.root)


if __name__ == "__main__":
    unittest.main()
