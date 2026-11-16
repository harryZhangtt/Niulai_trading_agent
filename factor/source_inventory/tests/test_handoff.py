import copy
import json
from pathlib import Path
import unittest

from factor.source_inventory import contract, handoff
from factor.source_inventory.tests.schema_helper import accepts

ROOT = Path(__file__).resolve().parents[1]
ALFRED = ROOT / "fixtures/synthetic-alfred-response-v1.json"
DATABENTO = ROOT / "fixtures/synthetic-databento-response-v1.json"
ALFRED_RECEIPT = ROOT / "fixtures/synthetic-alfred-receipt-v1.json"
DATABENTO_RECEIPT = ROOT / "fixtures/synthetic-databento-receipt-v1.json"


class SourceHandoffTests(unittest.TestCase):
    def setUp(self):
        self.alfred = json.loads(ALFRED.read_text())
        self.databento = json.loads(DATABENTO.read_text())

    def test_alfred_realtime_revision_maps_to_pit_vintage_selection(self):
        receipt = handoff.normalize_response(self.alfred)
        self.assertFalse(receipt["values_included"])
        early = handoff.select_as_of(receipt, "2026-01-02T00:00:00Z")
        late = handoff.select_as_of(receipt, "2026-01-04T00:00:00Z")
        self.assertEqual(len(early), 1); self.assertEqual(len(late), 1)
        self.assertNotEqual(early[0]["vintage_id"], late[0]["vintage_id"])
        self.assertEqual(late[0]["supersedes_vintage_id"], early[0]["vintage_id"])
        self.assertEqual(early[0]["observed_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(early[0]["published_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(early[0]["available_at"], "2026-01-02T00:00:00Z")
        self.assertEqual(early[0]["vintage_end_at"], "2026-01-02T00:00:00Z")

    def test_current_latest_cannot_masquerade_as_alfred_pit(self):
        current = copy.deepcopy(self.alfred); current["source_format"] = "current-latest"
        with self.assertRaisesRegex(handoff.HandoffError, "RESPONSE_INVALID"):
            handoff.validate_response(current)
        wrong_route = copy.deepcopy(self.alfred); wrong_route["route_policy_sha256"] = "0" * 64
        with self.assertRaisesRegex(handoff.HandoffError, "ROUTE_MISMATCH"):
            handoff.validate_response(wrong_route)

    def test_databento_ts_record_correction_and_cancel_are_selected_as_of(self):
        receipt = handoff.normalize_response(self.databento)
        first = handoff.select_as_of(receipt, "2026-01-02T10:00:00Z")
        corrected = handoff.select_as_of(receipt, "2026-01-03T10:00:00Z")
        cancelled = handoff.select_as_of(receipt, "2026-01-04T10:00:00Z")
        self.assertEqual(first[0]["event_action"], "new")
        self.assertEqual(corrected[0]["event_action"], "correct")
        self.assertEqual(corrected[0]["effective_start"], "2026-01-05T14:30:00Z")
        self.assertEqual(corrected[0]["supersedes_vintage_id"], first[0]["vintage_id"])
        self.assertEqual(cancelled, [])

    def test_listing_splice_mapping_drift_and_missing_event_identity_fail(self):
        splice = copy.deepcopy(self.databento); splice["records"][1]["listing_id"] = "other-listing"
        with self.assertRaisesRegex(handoff.HandoffError, "TICKER_SPLICE"):
            handoff.validate_response(splice)
        mapping = copy.deepcopy(self.databento); mapping["records"][1]["mapping_version"] = "mapping-v2"
        with self.assertRaisesRegex(handoff.HandoffError, "MAPPING_VERSION_DRIFT"):
            handoff.validate_response(mapping)
        missing = copy.deepcopy(self.databento); del missing["records"][0]["event_unique_id"]
        with self.assertRaisesRegex(handoff.HandoffError, "DATABENTO_SCHEMA"):
            handoff.validate_response(missing)
        no_receipt = copy.deepcopy(self.databento); no_receipt["acquisition_receipt_sha256"] = None
        with self.assertRaises(handoff.HandoffError):
            handoff.validate_response(no_receipt)

    def test_same_recorded_time_still_selects_native_latest_versions(self):
        alfred=copy.deepcopy(self.alfred)
        for row in alfred["records"]: row["recorded_at"]="2026-01-10T00:00:00Z"
        alfred_receipt=handoff.normalize_response(alfred)
        selected=handoff.select_as_of(alfred_receipt,"2026-01-10T00:00:00Z")
        self.assertEqual(selected[0]["provider_version_at"],"2026-01-03T00:00:00Z")
        databento=copy.deepcopy(self.databento)
        for row in databento["records"]: row["recorded_at"]="2026-01-10T00:00:00Z"
        receipt=handoff.normalize_response(databento)
        self.assertEqual(handoff.select_as_of(receipt,"2026-01-10T00:00:00Z"),[])
        post_cutoff=copy.deepcopy(self.databento); post_cutoff["records"]=post_cutoff["records"][:2]
        later=copy.deepcopy(post_cutoff["records"][1])
        later.update(record_id="spy-action-later",ts_record="2026-01-11T10:00:00Z",
                     recorded_at="2026-01-11T10:00:00Z",source_row_sha256="e"*64)
        post_cutoff["records"].append(later); later_receipt=handoff.normalize_response(post_cutoff)
        before=handoff.select_as_of(later_receipt,"2026-01-10T00:00:00Z")
        after=handoff.select_as_of(later_receipt,"2026-01-12T00:00:00Z")
        self.assertEqual(before[0]["provider_version_at"],"2026-01-03T10:00:00Z")
        self.assertEqual(after[0]["provider_version_at"],"2026-01-11T10:00:00Z")

    def test_exact_duplicate_dedupes_but_same_key_conflict_fails(self):
        duplicate=copy.deepcopy(self.databento)
        exact=copy.deepcopy(duplicate["records"][1]); exact["record_id"]="spy-action-duplicate"
        duplicate["records"].append(exact)
        receipt=handoff.normalize_response(duplicate)
        self.assertEqual(len(receipt["normalized_records"]),3)
        conflict=copy.deepcopy(duplicate)
        conflict["records"][-1]["source_row_sha256"]="f"*64
        with self.assertRaisesRegex(handoff.HandoffError,"VINTAGE_AMBIGUOUS"):
            handoff.validate_response(conflict)

    def test_ambiguous_versions_and_post_cancel_corrections_fail(self):
        ambiguous = copy.deepcopy(self.databento)
        ambiguous["records"][1]["ts_record"] = ambiguous["records"][0]["ts_record"]
        with self.assertRaisesRegex(handoff.HandoffError, "VINTAGE_AMBIGUOUS"):
            handoff.validate_response(ambiguous)
        post_cancel = copy.deepcopy(self.databento)
        post_cancel["records"].append({**copy.deepcopy(post_cancel["records"][1]),
            "record_id": "spy-action-4", "ts_record": "2026-01-05T10:00:00Z",
            "recorded_at": "2026-01-05T10:00:00Z",
            "source_row_sha256": "f" * 64})
        with self.assertRaisesRegex(handoff.HandoffError, "EVENT_LIFECYCLE"):
            handoff.validate_response(post_cancel)

    def test_adjusted_bars_ticker_splice_and_total_return_formula_drift_fail_inventory(self):
        inventory = contract.load_inventory(ROOT / "candidate-real-inventory.json")
        for field, replacement in (("price_adjustment", "adjusted"),
                                   ("security_identity_policy", "current-ticker-backfill"),
                                   ("total_return_formula_version", "formula-v2")):
            changed = copy.deepcopy(inventory)
            entry = next(item for item in changed["entries"] if item["role"] == "spy_market")
            primary = next(route for route in entry["provider_routes"] if route["priority"] == "primary")
            primary[field] = replacement
            with self.subTest(field=field), self.assertRaisesRegex(
                    contract.InventoryError, "SELECTED_ROUTE_DRIFT"):
                contract.validate_inventory(changed)

    def test_handoff_schemas_accept_only_value_free_structural_fixtures(self):
        response_schema = json.loads((ROOT / "acquisition-response-v1.schema.json").read_text())
        receipt_schema = json.loads((ROOT / "normalization-receipt-v1.schema.json").read_text())
        tracked_receipts=[json.loads(ALFRED_RECEIPT.read_text()),
                          json.loads(DATABENTO_RECEIPT.read_text())]
        for response,tracked_receipt in zip((self.alfred, self.databento),tracked_receipts):
            self.assertTrue(accepts(response, response_schema))
            receipt = handoff.normalize_response(response)
            self.assertEqual(receipt,tracked_receipt)
            self.assertTrue(accepts(receipt, receipt_schema))
            serialized = contract.canonical({"response": response, "receipt": receipt}).decode()
            self.assertNotIn('"value":', serialized)
            self.assertIn('"value_present":false', serialized)
            self.assertIn('"value_included":false', serialized)
        hidden = copy.deepcopy(self.alfred); hidden["records"][0]["value"] = "1.23"
        self.assertFalse(accepts(hidden, response_schema))
        with self.assertRaisesRegex(handoff.HandoffError, "ALFRED_SCHEMA"):
            handoff.validate_response(hidden)


if __name__ == "__main__":
    unittest.main()
