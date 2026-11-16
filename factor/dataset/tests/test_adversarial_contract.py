import decimal
from decimal import ROUND_DOWN, ROUND_UP, getcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from factor.dataset import DatasetError, build_snapshot
from factor.dataset import contract
from factor.dataset.contract import (digest, loaded_implementation_sha256,
                                     validate_builder_receipt,
                                     validate_label_authority_receipt)
from factor.dataset.tests.helpers import (descriptor, fixture_copy, read_artifact,
                                          refresh_label_authority, rewrite_artifact,
                                          validate_schema, write_descriptor)


SCHEMA_ROOT = Path(__file__).resolve().parents[1]


class DatasetAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fixture_copy(self.temp.name)

    def reset(self, name):
        self.root = fixture_copy(Path(self.temp.name) / name)

    def test_purge_embargo_and_maturity_are_enforced_from_calendar(self):
        split = read_artifact(self.root, "splits")
        split["embargo_sessions"] = 2
        rewrite_artifact(self.root, "splits", split)
        with self.assertRaisesRegex(DatasetError, "PURGE_EMBARGO_INVALID"):
            build_snapshot(self.root)

        self.reset("maturity")
        roster = read_artifact(self.root, "label_roster")
        roster[0]["maturity_at"] = roster[0]["window_end_session"] + "T21:00:00Z"
        rewrite_artifact(self.root, "label_roster", roster)
        refresh_label_authority(self.root)
        with self.assertRaisesRegex(DatasetError, "LABEL_WINDOW_INVALID"):
            build_snapshot(self.root)

    def test_split_ids_are_unique_and_roster_is_total_partition(self):
        split = read_artifact(self.root, "splits")
        split["splits"][1]["id"] = split["splits"][0]["id"]
        rewrite_artifact(self.root, "splits", split)
        with self.assertRaisesRegex(DatasetError, "SPLIT_ROLE_INVALID"):
            build_snapshot(self.root)

        self.reset("partition")
        roster = read_artifact(self.root, "label_roster")
        row = next(item for item in roster if item["sample_id"] == "dev-bbb")
        row.update(origin_session="2026-01-06", window_start_session="2026-01-07",
                   window_end_session="2026-01-08", maturity_at="2026-01-08T21:01:00Z")
        rewrite_artifact(self.root, "label_roster", roster)
        refresh_label_authority(self.root)
        with self.assertRaisesRegex(DatasetError, "SAMPLE_PARTITION_INVALID"):
            build_snapshot(self.root)

    def test_observed_at_is_an_effective_availability_bound(self):
        rows = read_artifact(self.root, "observations")
        row = next(item for item in rows if item["series_id"] == "price-close" and
                   item["entity_id"] == "aaa" and item["period_end"] == "2026-01-05")
        row["observed_at"] = "2026-01-05T22:00:00Z"
        row["available_at"] = "2026-01-05T20:00:00Z"
        row["recorded_at"] = "2026-01-05T20:00:00Z"
        rewrite_artifact(self.root, "observations", rows)
        transforms = read_artifact(self.root, "transformations")
        transforms["transforms"].append({"transform_id": "price-now", "output_series_id": "price-now",
                                          "input_series_id": "price-close", "operator": "identity",
                                          "lookback_sessions": 0, "min_periods": 1})
        rewrite_artifact(self.root, "transformations", transforms)
        with self.assertRaisesRegex(DatasetError, "REQUIRED_OBSERVATION_MISSING"):
            build_snapshot(self.root)

    def test_session_lookbacks_do_not_compress_explicit_gaps(self):
        result = build_snapshot(self.root)
        jan9 = next(row for row in result["features"]
                    if row["entity_id"] == "aaa" and row["session_date"] == "2026-01-09")
        self.assertIsNone(jan9["features"]["macro-diff-2"])
        rows = read_artifact(self.root, "observations")
        price = next(item for item in rows if item["series_id"] == "price-close" and
                     item["entity_id"] == "aaa" and item["period_end"] == "2026-01-08")
        price["value"] = None; price["missing_reason"] = "source_gap"
        rewrite_artifact(self.root, "observations", rows)
        with self.assertRaisesRegex(DatasetError, "REQUIRED_OBSERVATION_MISSING"):
            build_snapshot(self.root)

    def test_target_and_foreign_keys_fail_closed(self):
        roster = read_artifact(self.root, "label_roster")
        roster[0]["target_definition_sha256"] = "f" * 64
        rewrite_artifact(self.root, "label_roster", roster)
        refresh_label_authority(self.root)
        with self.assertRaisesRegex(DatasetError, "LABEL_WINDOW_INVALID"):
            build_snapshot(self.root)

        cases = [
            ("calendar", lambda rows: rows[0].update(source_id="missing-source"),
             "CALENDAR_FOREIGN_KEY_INVALID"),
            ("series", lambda rows: rows[0].update(calendar_id="other-calendar"),
             "SERIES_CALENDAR_INVALID"),
            ("universe", lambda rows: rows[0].update(calendar_id="other-calendar"),
             "UNIVERSE_INVALID"),
        ]
        for index, (artifact, mutate, code) in enumerate(cases):
            self.reset(f"foreign-{index}")
            rows = read_artifact(self.root, artifact); mutate(rows)
            rewrite_artifact(self.root, artifact, rows)
            with self.subTest(artifact=artifact), self.assertRaisesRegex(DatasetError, code):
                build_snapshot(self.root)

        self.reset("execution-role")
        execution = read_artifact(self.root, "execution")
        execution["price_series_id"] = "cash-rate"
        rewrite_artifact(self.root, "execution", execution)
        with self.assertRaisesRegex(DatasetError, "EXECUTION_INVALID"):
            build_snapshot(self.root)

    def test_runtime_instances_match_exact_documented_schemas(self):
        result = build_snapshot(self.root)
        documents = {
            "snapshot-v1.schema.json": descriptor(self.root),
            "builder-receipt-v1.schema.json": result["builder_receipt"],
            "label-authority-receipt-v1.schema.json": read_artifact(self.root, "label_authority"),
        }
        for name, instance in documents.items():
            schema = json.loads((SCHEMA_ROOT / name).read_text())
            self.assertEqual(set(schema["required"]), set(schema["properties"]))
            validate_schema(instance, schema)

    def test_receipt_binds_loaded_code_and_full_vs_cropped_outputs(self):
        full = build_snapshot(self.root)
        cropped = build_snapshot(self.root, start="2026-01-06", end="2026-01-14")
        for result in (full, cropped):
            receipt = result["builder_receipt"]
            self.assertEqual(receipt["builder_code_sha256"], loaded_implementation_sha256())
            self.assertEqual(receipt["output_feature_rows"], len(result["features"]))
            self.assertEqual(receipt["output_feature_artifact_sha256"], digest(result["features"]))
            self.assertEqual(receipt["full_feature_artifact_sha256"],
                             result["feature_artifact_sha256"])
            self.assertGreaterEqual(receipt["full_feature_rows"], receipt["output_feature_rows"])
        self.assertEqual(full["feature_snapshot_sha256"], cropped["feature_snapshot_sha256"])
        self.assertNotEqual(full["builder_receipt_sha256"], cropped["builder_receipt_sha256"])
        self.assertEqual(cropped["builder_receipt"]["output_scope"],
                         {"start": "2026-01-06", "end": "2026-01-14"})

    def test_calendar_session_dates_versions_and_forged_cutoffs_fail(self):
        calendar = read_artifact(self.root, "calendar")
        calendar[0]["close_at"] = "2026-01-03T21:00:00Z"
        rewrite_artifact(self.root, "calendar", calendar)
        with self.assertRaisesRegex(DatasetError, "CALENDAR_FOREIGN_KEY_INVALID"):
            build_snapshot(self.root)

        self.reset("calendar-version")
        calendar = read_artifact(self.root, "calendar")
        calendar[-1]["calendar_version"] = "forged-v2"
        rewrite_artifact(self.root, "calendar", calendar)
        with self.assertRaisesRegex(DatasetError, "CALENDAR_ID_INVALID"):
            build_snapshot(self.root)

        self.reset("future-cutoff")
        calendar = read_artifact(self.root, "calendar")
        calendar[1]["open_at"] = "2026-01-06T14:30:00Z"
        calendar[1]["close_at"] = "2026-01-06T21:00:00Z"
        rewrite_artifact(self.root, "calendar", calendar)
        with self.assertRaisesRegex(DatasetError, "CALENDAR_FOREIGN_KEY_INVALID"):
            build_snapshot(self.root)

    def test_synthetic_maturity_cannot_postdate_snapshot(self):
        roster = read_artifact(self.root, "label_roster")
        roster[0]["maturity_at"] = "2026-11-06T00:00:00Z"
        rewrite_artifact(self.root, "label_roster", roster)
        refresh_label_authority(self.root)
        with self.assertRaisesRegex(DatasetError, "LABEL_WINDOW_INVALID"):
            build_snapshot(self.root)

    def test_source_versions_revision_policies_and_immutable_vintages_are_exact(self):
        sources = read_artifact(self.root, "sources")
        sources[0]["source_version"] = 7
        rewrite_artifact(self.root, "sources", sources)
        with self.assertRaisesRegex(DatasetError, "SOURCE_VERSION_INVALID"):
            build_snapshot(self.root)

        self.reset("series-policy")
        series = read_artifact(self.root, "series")
        next(row for row in series if row["series_id"] == "price-close")["revision_policy"] = "revisable"
        rewrite_artifact(self.root, "series", series)
        with self.assertRaisesRegex(DatasetError, "SERIES_INVALID"):
            build_snapshot(self.root)

        self.reset("immutable-vintage")
        observations = read_artifact(self.root, "observations")
        row = next(item for item in observations if item["series_id"] == "price-close")
        duplicate = dict(row); duplicate["vintage_id"] = "forged-second-vintage"
        duplicate["value"] = "999"; duplicate["source_row_sha256"] = "9" * 64
        observations.append(duplicate)
        rewrite_artifact(self.root, "observations", observations)
        with self.assertRaisesRegex(DatasetError, "IMMUTABLE_VINTAGE_INVALID"):
            build_snapshot(self.root)

    def test_loaded_implementation_identity_binds_behavioral_constants(self):
        original = loaded_implementation_sha256()
        with mock.patch.object(contract, "CLOSED_OPERATORS", set(contract.CLOSED_OPERATORS) | {"forged"}):
            self.assertNotEqual(original, loaded_implementation_sha256())
        with mock.patch.object(contract, "ARTIFACT_NAMES", set(contract.ARTIFACT_NAMES) | {"forged"}):
            self.assertNotEqual(original, loaded_implementation_sha256())
        with mock.patch.object(contract, "MAX_FILE", contract.MAX_FILE + 1):
            self.assertNotEqual(original, loaded_implementation_sha256())
        self.assertEqual(original, loaded_implementation_sha256())

    def test_universe_revision_policy_controls_logical_vintages(self):
        sources = read_artifact(self.root, "sources")
        next(row for row in sources if row["source_id"] == "synthetic-universe")["revision_policy"] = "immutable"
        rewrite_artifact(self.root, "sources", sources)
        universe = read_artifact(self.root, "universe")
        original = universe[0]
        duplicate = dict(original); duplicate["vintage_id"] = "forged-universe-v2"
        duplicate["recorded_at"] = "2026-01-02T14:01:00Z"
        universe.append(duplicate); rewrite_artifact(self.root, "universe", universe)
        with self.assertRaisesRegex(DatasetError, "UNIVERSE_IMMUTABLE_VINTAGE_INVALID"):
            build_snapshot(self.root)

        self.reset("revisable-universe")
        universe = read_artifact(self.root, "universe")
        original = universe[0]
        duplicate = dict(original); duplicate["vintage_id"] = "legitimate-universe-v2"
        duplicate["recorded_at"] = "2026-01-02T14:01:00Z"
        universe.append(duplicate); rewrite_artifact(self.root, "universe", universe)
        build_snapshot(self.root)

    def test_decimal_outputs_ignore_default_and_caller_context(self):
        caller = getcontext(); caller_saved = caller.copy()
        default = decimal.DefaultContext; default_saved = default.copy()
        try:
            default.prec = 5; default.rounding = ROUND_DOWN
            default.Emin = -9; default.Emax = 9; default.capitals = 0; default.clamp = 1
            for signal in default.traps:
                default.traps[signal] = signal in {decimal.Inexact, decimal.Rounded}
                default.flags[signal] = True
            caller.prec = 6; caller.rounding = ROUND_DOWN
            caller.Emin = -12; caller.Emax = 12
            first = build_snapshot(self.root)

            default.prec = 60; default.rounding = ROUND_UP
            default.Emin = -99; default.Emax = 99; default.capitals = 1; default.clamp = 0
            for signal in default.traps:
                default.traps[signal] = signal in {decimal.Underflow, decimal.Subnormal}
                default.flags[signal] = False
            caller.prec = 50; caller.rounding = ROUND_UP
            caller.Emin = -100; caller.Emax = 100
            second = build_snapshot(self.root)
        finally:
            for target, saved in ((caller, caller_saved), (default, default_saved)):
                target.prec = saved.prec; target.rounding = saved.rounding
                target.Emin = saved.Emin; target.Emax = saved.Emax
                target.capitals = saved.capitals; target.clamp = saved.clamp
                for signal in target.traps:
                    target.traps[signal] = saved.traps[signal]
                    target.flags[signal] = saved.flags[signal]
        self.assertEqual(first["features"], second["features"])
        self.assertEqual(first["feature_artifact_sha256"], second["feature_artifact_sha256"])
        self.assertEqual(first["feature_snapshot_sha256"], second["feature_snapshot_sha256"])
        self.assertEqual(first["builder_receipt"], second["builder_receipt"])

    def test_artifact_path_runtime_schema_ascii_alignment(self):
        schema = json.loads((SCHEMA_ROOT / "snapshot-v1.schema.json").read_text())
        valid = descriptor(self.root)
        validate_schema(valid, schema); build_snapshot(self.root)
        for index, invalid_path in enumerate(("inventory/source file.jsonl",
                                              "inventory/sourcé.jsonl")):
            self.reset(f"path-syntax-{index}")
            invalid = descriptor(self.root)
            invalid["artifacts"]["sources"]["path"] = invalid_path
            with self.assertRaises(AssertionError): validate_schema(invalid, schema)
            write_descriptor(self.root, invalid)
            with self.assertRaisesRegex(DatasetError, "PATH_INVALID"):
                build_snapshot(self.root)

    def test_structural_schema_compatibility_and_runtime_cross_field_limits(self):
        result = build_snapshot(self.root)
        builder_schema = json.loads((SCHEMA_ROOT / "builder-receipt-v1.schema.json").read_text())
        zero = dict(result["builder_receipt"])
        zero["output_feature_rows"] = 0
        zero["output_feature_artifact_sha256"] = "0" * 64
        validate_builder_receipt(zero)
        validate_schema(zero, builder_schema)

        # JSON Schema validates structure; runtime remains authoritative for relational ordering.
        reversed_scope = dict(zero)
        reversed_scope["output_scope"] = {"start": "2026-01-20", "end": "2026-01-02"}
        validate_schema(reversed_scope, builder_schema)
        with self.assertRaisesRegex(DatasetError, "SCOPE_INVALID"):
            validate_builder_receipt(reversed_scope)

        authority = read_artifact(self.root, "label_authority")
        authority_schema = json.loads((SCHEMA_ROOT / "label-authority-receipt-v1.schema.json").read_text())
        validate_label_authority_receipt(authority); validate_schema(authority, authority_schema)
        authority["limitations"] = []
        with self.assertRaises(DatasetError): validate_label_authority_receipt(authority)
        with self.assertRaises(AssertionError): validate_schema(authority, authority_schema)

        snapshot = descriptor(self.root)
        snapshot_schema = json.loads((SCHEMA_ROOT / "snapshot-v1.schema.json").read_text())
        validate_schema(snapshot, snapshot_schema)
        bad_path = json.loads(json.dumps(snapshot))
        bad_path["artifacts"]["sources"]["path"] = "../escape.jsonl"
        with self.assertRaises(AssertionError): validate_schema(bad_path, snapshot_schema)
        bad_time = json.loads(json.dumps(snapshot)); bad_time["created_at"] = "2026-99-99T00:00:00Z"
        with self.assertRaises(ValueError): validate_schema(bad_time, snapshot_schema)

        extra_split = json.loads(json.dumps(result["builder_receipt"]))
        extra_split["split_fingerprints"]["renamed"] = "1" * 64
        with self.assertRaises(DatasetError): validate_builder_receipt(extra_split)
        with self.assertRaises(AssertionError): validate_schema(extra_split, builder_schema)

        bool_builder = dict(result["builder_receipt"]); bool_builder["schema_version"] = True
        with self.assertRaises(DatasetError): validate_builder_receipt(bool_builder)
        with self.assertRaises(AssertionError): validate_schema(bool_builder, builder_schema)
        bool_authority = read_artifact(self.root, "label_authority"); bool_authority["schema_version"] = True
        with self.assertRaises(DatasetError): validate_label_authority_receipt(bool_authority)
        with self.assertRaises(AssertionError): validate_schema(bool_authority, authority_schema)
        bool_snapshot = descriptor(self.root); bool_snapshot["schema_version"] = True
        with self.assertRaises(AssertionError): validate_schema(bool_snapshot, snapshot_schema)
        rewrite_artifact(self.root, "label_authority", read_artifact(self.root, "label_authority"))
        write_descriptor(self.root, bool_snapshot)
        with self.assertRaisesRegex(DatasetError, "VERSION_INVALID"):
            build_snapshot(self.root)


if __name__ == "__main__":
    unittest.main()
