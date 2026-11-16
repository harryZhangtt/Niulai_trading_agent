import json
import unittest
from shared.research_sources import market_pilot as p

AS_OF = "2020-12-31T23:59:59Z"
def mapping(source="tiger", ticker="AAPL", entity="e:aapl", cls="COMMON_STOCK", valid_from="2000-01-01", valid_to=None):
    return {"entity_id": entity, "valid_from": valid_from, "valid_to": valid_to, "venue": "NASDAQ",
            "source": source, "source_ticker": ticker, "security_class": cls, "mapping_provenance": "roster-v1"}
def row(source="tiger", value="10", **extra):
    base = {"source": source, "venue": "NASDAQ", "ticker": "AAPL", "field": "net_income", "value": value,
            "observed_date": "2020-09-30", "filing_date": "2020-11-01", "currency": "USD", "unit": "currency",
            "scale": 0, "missing_reason": None, "current_restated": False}; base.update(extra); return base
def receipt_manifest():
    return {"status": "PASS_PILOT_ONLY", "started_at": "2020-12-31T23:00:00Z", "completed_at": AS_OF,
            "provider_attempts": {"tiger": 1, "yahoo": 1}, "symbol_count": 2,
            "field_counts": {"requested": 4, "tiger_observed": 4, "yahoo_observed": 4,
                             "comparable": 3, "matched": 2, "discrepant": 1, "inconclusive": 1},
            "artifact_sha256": {"private_manifest": "a"*64, "normalized": "b"*64},
            "coverage_reasons": ["NO_INDEPENDENT_TOLERANCE"],
            "discrepancy_reasons": ["VALUE_OUTSIDE_TOLERANCE"],
            "checkpoint_committed": True, "release_requested": True,
            "symbols": ["AAPL"], "values": [123], "private_path": "/secret"}

class PilotTests(unittest.TestCase):
    def setUp(self): self.maps = p.validate_entity_map([mapping(), mapping("yahoo")])
    def test_point_in_time_restated_missing_negative_and_class_identity(self):
        normalized = p.normalize_observation(row(current_restated=True), entity_map=self.maps, as_of=AS_OF)
        self.assertFalse(normalized["pit_eligible"]); self.assertIn("restated", normalized["warning"])
        with self.assertRaisesRegex(p.MarketPilotError, "FILING_DATE_LEAKAGE"):
            p.normalize_observation(row(filing_date="2021-01-01"), entity_map=self.maps, as_of=AS_OF)
        missing = p.normalize_observation(row(value=None, missing_reason="provider_missing"), entity_map=self.maps, as_of=AS_OF)
        self.assertIsNone(missing["value"])
        ratio = p.normalize_observation(row(field="pe", value="-2"), entity_map=self.maps, as_of=AS_OF)
        self.assertEqual(ratio["missing_reason"], "nonpositive_denominator")
        for bad in (row(source="other"), row(current_restated=1), row(current_restated="false")):
            with self.subTest(bad=bad), self.assertRaises(p.MarketPilotError):
                p.normalize_observation(bad, entity_map=self.maps, as_of=AS_OF)
    def test_stable_map_preserves_classes_and_rejects_fuzzy_overlap_or_ambiguous(self):
        maps = p.validate_entity_map([mapping(entity="e:a"), mapping("tiger", "BRK.B", "e:brkb", "CLASS_SHARE"), mapping("tiger", "BABA", "e:baba", "ADR")])
        self.assertEqual([x["security_class"] for x in maps], ["COMMON_STOCK", "ADR", "CLASS_SHARE"])
        with self.assertRaisesRegex(p.MarketPilotError, "AMBIGUOUS"):
            p.map_entity(maps, "tiger", "NASDAQ", "BRK-B", "2020-01-01")
        overlapping = [mapping(valid_from="2000-01-01", valid_to="2020-06-30"),
                       mapping(entity="e:aapl-v2", valid_from="2020-06-30", valid_to="2021-01-01")]
        with self.assertRaisesRegex(p.MarketPilotError, "ENTITY_MAP_OVERLAP"):
            p.validate_entity_map(overlapping)
        adjacent = [mapping(valid_from="2000-01-01", valid_to="2020-06-29"),
                    mapping(entity="e:aapl-v2", valid_from="2020-06-30", valid_to="2021-01-01")]
        self.assertEqual(len(p.validate_entity_map(adjacent)), 2)
    def test_currency_unit_fx_actions_and_discrepancy_no_averaging(self):
        tiger = p.normalize_observation(row(), entity_map=self.maps, as_of=AS_OF)
        yahoo = p.normalize_observation(row("yahoo", "12"), entity_map=self.maps, as_of=AS_OF)
        result = p.compare(tiger, yahoo, absolute_tolerance="0.5")
        self.assertEqual(result["status"], "UNRESOLVED_DISCREPANCY"); self.assertFalse(result["averaged"]); self.assertIsNone(result["selected_value"])
        far = dict(yahoo); far["value"] = "999"
        for tolerance in ("Infinity", "-Infinity", "NaN", "bad", "-1", "", None, 1):
            with self.subTest(tolerance=tolerance), self.assertRaisesRegex(p.MarketPilotError, "TOLERANCE_INVALID"):
                p.compare(tiger, far, absolute_tolerance=tolerance)
        self.assertEqual(p.compare(tiger, far, absolute_tolerance="0.5")["status"], "UNRESOLVED_DISCREPANCY")
        yahoo["currency"] = "EUR"
        with self.assertRaisesRegex(p.MarketPilotError, "SEMANTIC_MISMATCH"): p.compare(tiger, yahoo, absolute_tolerance="1")
        fx = p.normalize_fx({"source": "tiger", "date": "2020-09-30", "from_currency": "EUR", "to_currency": "USD", "rate": "1.2", "direction": "EUR_PER_USD"}, as_of=AS_OF)
        self.assertEqual(fx["rate"], "1.2")
        invalid = [
            {"source": "evil", "date": "2020-09-30", "from_currency": "EUR", "to_currency": "USD", "rate": "1.2", "direction": "EUR_PER_USD"},
            {"source": "tiger", "date": "2020-09-30", "from_currency": "ZZZ", "to_currency": "USD", "rate": "1.2", "direction": "ZZZ_PER_USD"},
            {"source": "tiger", "date": "2020-09-30", "from_currency": "usd", "to_currency": "EUR", "rate": "1.2", "direction": "usd_PER_EUR"},
            {"source": "tiger", "date": "2020-09-30", "from_currency": "USD", "to_currency": "USD", "rate": "1.0", "direction": "USD_PER_USD"},
            {"source": "tiger", "date": "2020-09-30", "from_currency": "EUR", "to_currency": "USD", "rate": "NaN", "direction": "EUR_PER_USD"},
            {"source": "tiger", "date": "2020-09-30", "from_currency": "EUR", "to_currency": "USD", "rate": "-1", "direction": "EUR_PER_USD"},
            {"source": "tiger", "date": "2020-09-30", "from_currency": "EUR", "to_currency": "USD", "rate": "bad-decimal", "direction": "EUR_PER_USD"},
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(p.MarketPilotError):
                p.normalize_fx(candidate, as_of=AS_OF)
        action = {"source": "tiger", "venue": "NASDAQ", "ticker": "AAPL", "action_type": "symbol_change", "effective_date": "2020-01-01", "details": {"new": "AAPL2"}}
        actions = p.bind_corporate_actions([action], self.maps, as_of=AS_OF)
        self.assertFalse(actions[0]["automatic_ticker_stitch"])
        with self.assertRaisesRegex(p.MarketPilotError, "ACTION_AFTER_AS_OF"):
            p.bind_corporate_actions([{**action, "effective_date": "2021-01-01"}], self.maps, as_of=AS_OF)
    def test_public_receipt_exact_nested_schema_and_no_private_echo(self):
        receipt = p.sanitized_receipt(receipt_manifest())
        text = json.dumps(receipt)
        for forbidden in ("AAPL", "123", "/secret"):
            self.assertNotIn(forbidden, text)
        mutations = []
        bad = receipt_manifest(); bad["field_counts"]["secret_AAPL"] = 1; mutations.append(bad)
        bad = receipt_manifest(); bad["artifact_sha256"]["private_path"] = "c"*64; mutations.append(bad)
        bad = receipt_manifest(); bad["coverage_reasons"] = ["/private/account"]; mutations.append(bad)
        bad = receipt_manifest(); bad["discrepancy_reasons"] = ["bearer-secret"]; mutations.append(bad)
        bad = receipt_manifest(); bad["provider_attempts"]["https://evil.test/provider"] = 1; mutations.append(bad)
        bad = receipt_manifest(); bad["provider_attempts"]["tiger"] = -1; mutations.append(bad)
        bad = receipt_manifest(); bad["checkpoint_committed"] = 1; mutations.append(bad)
        bad = receipt_manifest(); bad["started_at"] = "not-utc/account"; mutations.append(bad)
        for bad in mutations:
            with self.subTest(bad=bad), self.assertRaises(p.MarketPilotError) as caught:
                p.sanitized_receipt(bad)
            message = str(caught.exception)
            for forbidden in ("AAPL", "/private/account", "bearer-secret", "evil.test"):
                self.assertNotIn(forbidden, message)
    def test_contract_inputs_match(self):
        value = {k: c*64 for k,c in (("calibration_sha256","a"),("promotion_sha256","b"),("roster_sha256","c"),("sample_selection_sha256","d"))}
        self.assertEqual(p.contract_inputs(value), value)
