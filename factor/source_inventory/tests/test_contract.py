import copy
import json
from pathlib import Path
import unittest

from factor.source_inventory import contract
from factor.source_inventory.tests.schema_helper import accepts

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "candidate-real-inventory.json"
SYNTHETIC = ROOT / "fixtures/synthetic-ready-v1.json"


class SourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.candidate = contract.load_inventory(CANDIDATE)
        self.synthetic = contract.load_inventory(SYNTHETIC)

    def entry(self, role, value=None):
        value = value or self.candidate
        return next(item for item in value["entries"] if item["role"] == role)

    def route(self, role, priority, value=None):
        return next(item for item in self.entry(role, value)["provider_routes"]
                    if item["priority"] == priority)

    def test_selected_candidate_is_disabled_and_all_receipts_are_null(self):
        self.assertEqual(self.candidate["status"], "selected_disabled_unverified")
        self.assertFalse(self.candidate["real_ready"])
        self.assertFalse(self.candidate["structural_ready"])
        self.assertEqual(self.candidate["blockers"], contract.BLOCKERS)
        for entry in self.candidate["entries"]:
            self.assertTrue(all(entry[key] is None for key in contract.UNRESOLVED_FIELDS))
            for route in entry["provider_routes"]:
                self.assertTrue(all(route[key] is None
                                    for key in contract.ROUTE_RECEIPT_FIELDS))
        request = contract.create_attestation_request(self.candidate)
        self.assertEqual(request["status"], "blocked")
        self.assertEqual(request["blockers"], contract.BLOCKERS)
        self.assertFalse(request["real_ready"])

    def test_selected_primary_fallback_and_crosscheck_snapshot_is_exact(self):
        self.assertEqual(self.route("real_yield", "primary")["provider_id"], "fred")
        self.assertEqual(self.route("real_yield", "fallback")["provider_id"],
                         "federal-reserve-board")
        credit = self.route("credit_spread", "primary")
        self.assertEqual(credit["series_id"], "bamlc0a0cm")
        self.assertEqual(credit["rights_codes"],
                         ["internal-research-only", "no-redistribution",
                          "ice-license-required"])
        self.assertEqual(self.route("credit_spread", "fallback")["provider_id"], "ice")
        self.assertEqual(self.route("cash_rate", "fallback")["provider_id"],
                         "new-york-fed")
        for role in ("spy_market", "oneq_market"):
            self.assertEqual(self.route(role, "primary")["provider_id"], "databento")
            self.assertEqual(self.route(role, "primary")["product_id"], "equs-mini")
            self.assertEqual(self.route(role, "fallback")["provider_id"], "massive")
            cross = self.route(role, "cross-check")
            self.assertEqual(cross["provider_id"], "tiger")
            self.assertEqual(cross["admissibility"], "cross-check-only")
            self.assertIn("not-pit-admissible", cross["rights_codes"])

    def test_alias_order_and_packaging_do_not_reset_identity(self):
        baseline = contract.inventory_sha256(self.candidate)
        changed = copy.deepcopy(self.candidate)
        changed["inventory_id"] = "renamed-selection-package"
        changed["entries"].reverse()
        for index, entry in enumerate(changed["entries"]):
            entry["inventory_alias"] = f"renamed-entry-{index}"
            entry["provider_routes"].reverse()
            for route_index, route in enumerate(entry["provider_routes"]):
                route["route_alias"] = f"renamed-route-{index}-{route_index}"
        self.assertEqual(contract.inventory_sha256(changed), baseline)

    def test_provider_product_and_policy_changes_are_identity_bearing_and_rejected(self):
        baseline = contract.digest(contract.semantic_inventory(self.candidate))
        mutations = [
            ("provider", "real_yield", "primary", "provider_id", "other-provider"),
            ("product", "credit_spread", "fallback", "product_id", "other-product"),
            ("pit", "cash_rate", "fallback", "pit_method", "current-latest"),
            ("adjusted", "spy_market", "primary", "price_adjustment", "adjusted"),
            ("ticker-splice", "oneq_market", "primary", "security_identity_policy",
             "current-ticker-backfill"),
        ]
        for name, role, priority, field, replacement in mutations:
            changed = copy.deepcopy(self.candidate)
            self.route(role, priority, changed)[field] = replacement
            semantic = copy.deepcopy(contract.semantic_inventory(self.candidate))
            target = next(item for item in semantic["entries"] if item["role"] == role)
            next(item for item in target["provider_routes"]
                 if item["priority"] == priority)[field] = replacement
            self.assertNotEqual(contract.digest(semantic), baseline)
            with self.subTest(name=name), self.assertRaisesRegex(
                    contract.InventoryError, "SELECTED_ROUTE_DRIFT"):
                contract.validate_inventory(changed)

    def test_fallback_and_crosscheck_cannot_be_promoted(self):
        cases = []
        fallback = copy.deepcopy(self.candidate)
        self.route("spy_market", "fallback", fallback)["priority"] = "primary"
        cases.append(fallback)
        fallback_status = copy.deepcopy(self.candidate)
        self.route("cash_rate", "fallback", fallback_status)["admissibility"] = "selected-disabled"
        cases.append(fallback_status)
        tiger = copy.deepcopy(self.candidate)
        self.route("oneq_market", "cross-check", tiger)["admissibility"] = "selected-disabled"
        cases.append(tiger)
        for changed in cases:
            with self.assertRaisesRegex(contract.InventoryError, "SELECTED_ROUTE_DRIFT"):
                contract.validate_inventory(changed)

    def test_rights_retention_entitlement_and_pit_receipts_cannot_be_omitted(self):
        rights = copy.deepcopy(self.candidate)
        self.route("credit_spread", "primary", rights)["rights_codes"].remove(
            "no-redistribution")
        with self.assertRaisesRegex(contract.InventoryError, "SELECTED_ROUTE_DRIFT"):
            contract.validate_inventory(rights)
        route_field = copy.deepcopy(self.candidate)
        del self.route("spy_market", "primary", route_field)["retention_receipt_sha256"]
        with self.assertRaisesRegex(contract.InventoryError, "ROUTE_SCHEMA"):
            contract.validate_inventory(route_field)
        guessed = copy.deepcopy(self.candidate)
        self.route("real_yield", "primary", guessed)["license_receipt_sha256"] = "a" * 64
        with self.assertRaisesRegex(contract.InventoryError,
                                    "ROUTE_RECEIPT_MUST_BE_NULL"):
            contract.validate_inventory(guessed)
        missing_attestation = contract.create_attestation_request(self.candidate)
        missing_attestation["required_receipt_fields"].remove(
            "missingness_coverage_receipt_sha256")
        with self.assertRaisesRegex(contract.InventoryError, "REQUEST_INVALID"):
            contract.validate_attestation_request(missing_attestation)

    def test_synthetic_fixture_is_structural_only(self):
        self.assertEqual(self.synthetic["status"], "synthetic_fixture")
        self.assertTrue(self.synthetic["structural_ready"])
        self.assertFalse(self.synthetic["real_ready"])
        self.assertTrue(all(len(entry["provider_routes"]) == 1
                            for entry in self.synthetic["entries"]))
        request = contract.create_attestation_request(self.synthetic)
        self.assertEqual(request["status"], "fixture_only")
        self.assertEqual(request["blockers"], [])

    def test_blockers_ready_claims_hidden_data_and_arbitrary_text_fail(self):
        blockers = copy.deepcopy(self.candidate); blockers["blockers"].pop()
        with self.assertRaisesRegex(contract.InventoryError, "BLOCKERS"):
            contract.validate_inventory(blockers)
        ready = copy.deepcopy(self.candidate); ready["real_ready"] = True
        with self.assertRaisesRegex(contract.InventoryError, "REAL_READY_FORBIDDEN"):
            contract.validate_inventory(ready)
        arbitrary = copy.deepcopy(self.candidate)
        arbitrary["limitations"] = ["arbitrary free-form text"]
        with self.assertRaisesRegex(contract.InventoryError, "LIMITATIONS_INVALID"):
            contract.validate_inventory(arbitrary)
        for text in ("client_secret=synthetic", "access_token=synthetic",
                     "credential=synthetic", "session_cookie=synthetic",
                     "token=synthetic", "key=synthetic", "sharpe=9",
                     "/Users/private/source.csv", "protected_outcome=1"):
            with self.subTest(text=text), self.assertRaisesRegex(
                    contract.InventoryError, "SENSITIVE_CONTENT"):
                contract._scan({"canary": text})

    def test_duplicate_unknown_role_and_type_confusion_fail(self):
        duplicate = copy.deepcopy(self.candidate)
        duplicate["entries"][1]["role"] = duplicate["entries"][0]["role"]
        with self.assertRaises(contract.InventoryError):
            contract.validate_inventory(duplicate)
        unknown = copy.deepcopy(self.candidate); unknown["entries"][0]["role"] = "other"
        with self.assertRaisesRegex(contract.InventoryError, "ROLE_INVALID"):
            contract.validate_inventory(unknown)
        boolean = copy.deepcopy(self.candidate); boolean["schema_version"] = True
        with self.assertRaisesRegex(contract.InventoryError, "VERSION"):
            contract.validate_inventory(boolean)
        with self.assertRaisesRegex(contract.InventoryError, "DUPLICATE_KEY"):
            contract.loads_strict('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(contract.InventoryError, "NONFINITE"):
            contract.loads_strict('{"value":NaN}')

    def test_attestation_roster_covers_every_unresolved_fact(self):
        self.assertEqual(set(contract.REQUIRED_RECEIPT_FIELDS),
                         set(contract.UNRESOLVED_FIELDS) |
                         set(contract.RECEIPT_IDENTITY_FIELDS))
        request = contract.create_attestation_request(self.candidate)
        for field in contract.UNRESOLVED_FIELDS:
            self.assertIn(field, request["required_receipt_fields"])

    def test_schemas_fail_closed_on_status_routes_receipts_and_duplicates(self):
        inventory_schema = json.loads((ROOT / "inventory-v1.schema.json").read_text())
        request_schema = json.loads((ROOT / "attestation-request-v1.schema.json").read_text())
        self.assertTrue(accepts(self.candidate, inventory_schema))
        self.assertTrue(accepts(self.synthetic, inventory_schema))
        request = contract.create_attestation_request(self.candidate)
        self.assertTrue(accepts(request, request_schema))
        mutations = []
        status = copy.deepcopy(self.candidate); status["status"] = "synthetic_fixture"; mutations.append(status)
        structural = copy.deepcopy(self.candidate); structural["structural_ready"] = True; mutations.append(structural)
        blocker = copy.deepcopy(self.candidate); blocker["blockers"].pop(); mutations.append(blocker)
        priority = copy.deepcopy(self.candidate); self.route("spy_market", "fallback", priority)["admissibility"] = "selected-disabled"; mutations.append(priority)
        receipt = copy.deepcopy(self.candidate); self.route("spy_market", "primary", receipt)["license_receipt_sha256"] = "a" * 64; mutations.append(receipt)
        fred_drift = copy.deepcopy(self.candidate); self.route("real_yield", "primary", fred_drift)["product_id"] = "fred-current-only"; mutations.append(fred_drift)
        duplicate_route = copy.deepcopy(self.candidate)
        duplicate_route_entry = self.entry("real_yield", duplicate_route)
        duplicate_route_entry["provider_routes"] = [duplicate_route_entry["provider_routes"][0],
                                                     copy.deepcopy(duplicate_route_entry["provider_routes"][0])]
        mutations.append(duplicate_route)
        relabeled_fixture = copy.deepcopy(self.synthetic)
        relabeled_fixture["trust_class"] = "candidate_real"
        relabeled_fixture["status"] = "selected_disabled_unverified"
        relabeled_fixture["structural_ready"] = False
        relabeled_fixture["blockers"] = list(contract.BLOCKERS)
        mutations.append(relabeled_fixture)
        missing_fallback = copy.deepcopy(self.candidate)
        self.entry("real_yield", missing_fallback)["provider_routes"] = [
            self.route("real_yield", "primary", missing_fallback)]
        mutations.append(missing_fallback)
        missing_crosscheck = copy.deepcopy(self.candidate)
        self.entry("spy_market", missing_crosscheck)["provider_routes"] = [
            route for route in self.entry("spy_market", missing_crosscheck)["provider_routes"]
            if route["priority"] != "cross-check"]
        mutations.append(missing_crosscheck)
        duplicate_role = copy.deepcopy(self.candidate); duplicate_role["entries"][1]["role"] = duplicate_role["entries"][0]["role"]; mutations.append(duplicate_role)
        for changed in mutations:
            self.assertFalse(accepts(changed, inventory_schema))
        duplicate_roles = copy.deepcopy(request); duplicate_roles["requested_roles"][1] = duplicate_roles["requested_roles"][0]
        self.assertFalse(accepts(duplicate_roles, request_schema))
        duplicate_receipts = copy.deepcopy(request); duplicate_receipts["required_receipt_fields"][1] = duplicate_receipts["required_receipt_fields"][0]
        self.assertFalse(accepts(duplicate_receipts, request_schema))
        wrong_status = copy.deepcopy(request); wrong_status["status"] = "fixture_only"
        self.assertFalse(accepts(wrong_status, request_schema))

    def test_schemas_and_tracked_artifacts_are_structurally_exact(self):
        inventory_schema = json.loads((ROOT / "inventory-v1.schema.json").read_text())
        request_schema = json.loads((ROOT / "attestation-request-v1.schema.json").read_text())
        self.assertEqual(set(inventory_schema["required"]), set(inventory_schema["properties"]))
        self.assertEqual(set(inventory_schema["$defs"]["entry"]["required"]),
                         set(inventory_schema["$defs"]["entry"]["properties"]))
        route_variants = inventory_schema["$defs"]["route"]["oneOf"]
        self.assertGreaterEqual(len(route_variants), 17)
        for variant in route_variants:
            self.assertEqual(set(variant["required"]), set(variant["properties"]))
        self.assertEqual(set(request_schema["required"]), set(request_schema["properties"]))
        self.assertEqual(request_schema["properties"]["required_receipt_fields"]["const"],
                         contract.REQUIRED_RECEIPT_FIELDS)
        tracked = [CANDIDATE, SYNTHETIC, ROOT / "inventory-v1.schema.json",
                   ROOT / "attestation-request-v1.schema.json", ROOT / "README.md"]
        for path in tracked:
            if path.suffix == ".json":
                json.loads(path.read_text())
            contract._scan(path.read_text())


if __name__ == "__main__":
    unittest.main()
