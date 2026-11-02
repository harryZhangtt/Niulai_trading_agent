#!/usr/bin/env python3
"""Offline economic arithmetic identities, provenance rejection and CLI checks."""

import copy
from decimal import Decimal, Inexact, localcontext
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("cycle_checks.py")
SPEC = importlib.util.spec_from_file_location("cycle_checks", SCRIPT)
cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cycle)


def example_packet():
    """Synthetic arithmetic fixture, not issuer data, probabilities or a forecast."""
    observations = {}
    as_of = "2026-10-23T12:00:00Z"

    def add(oid, value, unit, start, end=None, definition=None, origin="assumption"):
        observations[oid] = {
            "value": str(value), "unit": unit,
            "period": {"start": start, "end": end or start},
            "available_at": as_of, "source_ref": "synthetic:hand-arithmetic-fixture",
            "definition": definition or oid, "origin": origin,
        }
        return oid

    for oid, value, day, definition in (
        ("supply_start", "100", "2025-10-23", "Comparable annualized widget capacity"),
        ("supply_end", "120", "2026-10-23", "Comparable annualized widget capacity"),
        ("demand_start", "80", "2025-10-23", "Comparable annualized widget demand"),
        ("demand_end", "108", "2026-10-23", "Comparable annualized widget demand"),
    ):
        add(oid, value, "quantity:widgets", day, definition=definition, origin="reported")
        observations[oid]["market_scope"] = "Synthetic global finished widgets, all applications"
        observations[oid]["measurement_basis"] = "Annualized qualified good widgets at the snapshot date"
    calculations = [{"id": "physical", "kind": "supply_demand", **{k: k for k in (
        "supply_start", "supply_end", "demand_start", "demand_end",
    )}}]

    def state(label, year, segment_inputs):
        start, end = f"{year}-01-01", f"{year}-12-31"
        segments = []
        for sid, inputs in segment_inputs:
            segment = {"id": sid}
            for field, value in zip(cycle._SEGMENT_FIELDS, inputs):
                unit = ("quantity:widgets" if field == "volume" else
                        "currency:USD/quantity:widgets" if field in ("asp", "variable_cost_per_unit") else
                        "fraction" if field == "tax_rate" else "currency:USD")
                oid = f"{label}_{sid}_{field}"
                segment[field] = add(oid, value, unit, start, end)
            segments.append(segment)
        calculation = {
            "id": label, "kind": "state_bridge", "state": label,
            "annual_basis": "calendar_year",
            "financing_excluded": True, "segments": segments,
            "approximation_notes": [
                "Synthetic constant-ASP and unit-cost assumptions; cash tax uses positive segment EBIT only.",
                "No financing, stock compensation schedule or complete balance-sheet reconciliation is modeled.",
            ],
        }
        calculations.append(calculation)
        return calculation

    state("peak", 2025, [("core", ["120", "12", "4", "100", "50", "0.25", "100", "30"])])
    state("normalized", 2027, [
        ("core", ["100", "10", "4", "100", "50", "0.25", "80", "20"]),
        ("other", ["20", "20", "5", "50", "10", "0.2", "20", "-10"]),
    ])
    state("adverse", 2027, [("core", ["80", "5", "6", "100", "50", "0.25", "40", "-30"])])
    add("price", "20", "currency:USD/share", "2026-10-23", origin="reported")
    add("current_shares", "100", "shares", "2026-10-23", origin="reported")
    add("valuation_shares", "110", "shares", "2026-10-23")
    add("net_debt", "200", "currency:USD", "2026-10-23")
    add("target_multiple", "8", "multiple", "2027-01-01", "2027-12-31")
    bridge = {k: k for k in cycle._BRIDGE_FIELDS}
    bridge["share_count_assumption"] = "10% assumed dilution; supplied net debt already includes any issuance cash effects."
    calculations.extend([
        {"id": "multiples", "kind": "valuation", "states": ["peak", "normalized", "adverse"], **bridge},
        {"id": "reverse", "kind": "reverse_ebitda", "normalized_state": "normalized", "target_ev_ebitda": "target_multiple", **bridge},
    ])
    return {"version": cycle.VERSION, "subject": "SYNTHETIC", "as_of": as_of,
            "observations": observations, "calculations": calculations}


class CycleChecksTest(unittest.TestCase):
    def setUp(self):
        self.packet = example_packet()

    def reject(self, packet, code):
        with self.assertRaises(cycle.CycleCheckError) as caught:
            cycle.calculate(packet)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.as_dict()["status"], "error")

    def test_hand_arithmetic_all_four_operations(self):
        result = cycle.calculate(self.packet)
        physical = result["results"]["physical"]
        self.assertEqual(physical["supply_growth_fraction"], "0.2")
        self.assertEqual(physical["demand_growth_fraction"], "0.35")
        self.assertEqual(physical["demand_minus_supply_growth_percentage_points"], "15")
        self.assertEqual(physical["demand_to_supply_end_ratio"], "0.9")
        self.assertEqual(physical["relative_end_utilization_index_start_1"], "1.125")
        normalized = result["results"]["normalized"]
        self.assertEqual(normalized["cash_flow_measure"], "FCFF")
        self.assertEqual(normalized["totals"], {
            "revenue": "1400", "variable_cash_cost": "500", "cash_fixed_cost": "150",
            "ebitda": "750", "da": "60", "ebit": "690", "cash_tax": "160.5",
            "nopat": "529.5", "cash_capex": "100", "change_nwc": "10", "fcff": "479.5",
        })
        self.assertEqual(normalized["segments"]["core"]["fcff"], "287.5")
        valuation = result["results"]["multiples"]
        self.assertEqual(valuation["equity_bridge"]["current_market_equity_value"], "2000")
        self.assertEqual(valuation["equity_bridge"]["current_market_enterprise_value"], "2200")
        self.assertEqual(valuation["equity_bridge"]["dilution_or_buyback_fraction"], "0.1")
        self.assertEqual(valuation["states"]["adverse"]["ev_to_ebitda"]["status"], "NM")
        reverse = result["results"]["reverse"]
        self.assertEqual(reverse["target_enterprise_value_at_valuation_shares"], "2400")
        self.assertEqual(reverse["required_normalized_ebitda"], "300")
        self.assertEqual(reverse["required_minus_baseline_ebitda"], "-450")
        self.assertEqual(result["unused_observation_refs"], [])
        self.assertEqual(len(result["input_sha256"]), 64)

    def test_cash_flow_identity_segment_tax_and_no_loss_benefit(self):
        result = cycle.calculate(self.packet)["results"]
        for state in ("peak", "normalized", "adverse"):
            totals = {k: Decimal(v) for k, v in result[state]["totals"].items()}
            self.assertEqual(totals["fcff"], totals["nopat"] + totals["da"] - totals["cash_capex"] - totals["change_nwc"])
            self.assertEqual(totals["nopat"], totals["ebit"] - totals["cash_tax"])
            for metric in cycle._CASH_METRICS:
                self.assertEqual(totals[metric], sum(Decimal(s[metric]) for s in result[state]["segments"].values()))
        self.assertEqual(result["adverse"]["totals"]["cash_tax"], "0")
        self.assertEqual(result["adverse"]["totals"]["fcff"], "-190")

    def test_monetary_scaling_identity(self):
        base = cycle.calculate(self.packet)["results"]
        scaled = copy.deepcopy(self.packet)
        for observation in scaled["observations"].values():
            if observation["unit"].startswith("currency:"):
                observation["value"] = str(Decimal(observation["value"]) * 7)
        output = cycle.calculate(scaled)["results"]
        for state in ("peak", "normalized", "adverse"):
            for metric in cycle._CASH_METRICS:
                self.assertEqual(Decimal(output[state]["totals"][metric]), Decimal(base[state]["totals"][metric]) * 7)
            self.assertEqual(output[state]["ebitda_margin_fraction"], base[state]["ebitda_margin_fraction"])
        self.assertEqual(output["multiples"]["states"]["normalized"]["ev_to_ebitda"], base["multiples"]["states"]["normalized"]["ev_to_ebitda"])
        self.assertEqual(Decimal(output["reverse"]["required_normalized_ebitda"]), Decimal(base["reverse"]["required_normalized_ebitda"]) * 7)
        self.assertEqual(output["reverse"]["required_ebitda_margin_fraction"], base["reverse"]["required_ebitda_margin_fraction"])

    def test_physical_quantity_rescaling_invariance(self):
        base = cycle.calculate(self.packet)["results"]
        scaled = copy.deepcopy(self.packet)
        for observation in scaled["observations"].values():
            if observation["unit"] == "quantity:widgets":
                observation["value"] = str(Decimal(observation["value"]) * 1000)
            elif observation["unit"] == "currency:USD/quantity:widgets":
                observation["value"] = str(Decimal(observation["value"]) / 1000)
        output = cycle.calculate(scaled)["results"]
        self.assertEqual(output["physical"], base["physical"])
        for state in ("peak", "normalized", "adverse"):
            self.assertEqual(output[state]["totals"], base[state]["totals"])

    def test_input_dictionary_order_and_calculation_dependency_order(self):
        expected = cycle.calculate(self.packet)
        reordered = copy.deepcopy(self.packet)
        reordered["observations"] = dict(reversed(list(reordered["observations"].items())))
        self.assertEqual(cycle.canonical_json(cycle.calculate(reordered)), cycle.canonical_json(expected))
        reordered["calculations"].reverse()
        self.assertEqual(cycle.calculate(reordered)["results"], expected["results"])

    def test_caller_decimal_precision_does_not_affect_results(self):
        expected = cycle.calculate(self.packet)
        with localcontext() as context:
            context.prec = 3
            context.rounding = "ROUND_DOWN"
            context.Emax = 2
            context.Emin = -2
            context.traps[Inexact] = True
            self.assertEqual(cycle.calculate(self.packet), expected)

    def test_zero_demand_end_and_zero_revenue_are_defined(self):
        self.packet["observations"]["demand_end"]["value"] = "0"
        self.packet["observations"]["normalized_core_volume"]["value"] = "0"
        self.packet["observations"]["normalized_other_volume"]["value"] = "0"
        result = cycle.calculate(self.packet)["results"]
        self.assertEqual(result["physical"]["relative_end_utilization_index_start_1"], "0")
        self.assertEqual(result["normalized"]["ebitda_margin_fraction"]["status"], "NM")
        self.assertEqual(result["reverse"]["required_ebitda_margin_fraction"]["reason"], "zero_revenue")

    def test_zero_ebitda_and_net_cash_multiple_nm(self):
        self.packet["observations"]["adverse_core_asp"]["value"] = "7.25"
        result = cycle.calculate(self.packet)["results"]
        self.assertEqual(result["adverse"]["totals"]["ebitda"], "0")
        self.assertEqual(result["multiples"]["states"]["adverse"]["ev_to_ebitda"]["reason"], "nonpositive_ebitda")
        # Signed net cash is allowed. A negative EV multiple is not presented as useful.
        self.packet["calculations"] = [c for c in self.packet["calculations"] if c["id"] != "reverse"]
        self.packet["observations"]["net_debt"]["value"] = "-3000"
        result = cycle.calculate(self.packet)["results"]["multiples"]
        self.assertEqual(result["equity_bridge"]["current_market_enterprise_value"], "-1000")
        self.assertEqual(result["states"]["normalized"]["ev_to_ebitda"]["reason"], "nonpositive_enterprise_value")

    def test_exact_reported_total_control_and_rejection(self):
        self.packet["observations"]["peak_revenue_control"] = {
            "value": "1440", "unit": "currency:USD", "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "available_at": "2026-01-30T00:00:00Z", "origin": "reported",
            "source_ref": "synthetic:reported-control", "definition": "Reported synthetic segment revenue",
        }
        self.packet["calculations"][1]["reported_totals"] = {"revenue": "peak_revenue_control"}
        result = cycle.calculate(self.packet)["results"]["peak"]
        self.assertEqual(result["reported_total_reconciliation"]["revenue"]["difference"], "0")
        self.packet["observations"]["peak_revenue_control"]["value"] = "1439.99"
        self.reject(self.packet, "reconciliation")

    def test_invalid_values_booleans_floats_nonfinite_and_exponents(self):
        for value in (True, False, 12, 0.25, None, {}, [], "NaN", "Infinity", "-Infinity", "1e3", " 1", "01", ".1", "1."):
            with self.subTest(value=value):
                packet = copy.deepcopy(self.packet)
                packet["observations"]["price"]["value"] = value
                self.reject(packet, "decimal")

    def test_bad_denominators_and_negative_costs(self):
        for oid, value in (("supply_start", "0"), ("supply_end", "0"), ("demand_start", "0"),
                           ("current_shares", "0"), ("valuation_shares", "0"), ("target_multiple", "0"),
                           ("target_multiple", "-2"), ("normalized_core_cash_capex", "-1"),
                           ("normalized_core_variable_cost_per_unit", "-1"), ("demand_end", "-1")):
            with self.subTest(oid=oid, value=value):
                packet = copy.deepcopy(self.packet)
                packet["observations"][oid]["value"] = value
                self.reject(packet, "range")
        self.packet["observations"]["net_debt"]["value"] = "-2400"
        self.reject(self.packet, "range")

    def test_missing_and_unknown_references_and_ids(self):
        packet = copy.deepcopy(self.packet)
        packet["calculations"][0]["demand_end"] = "unknown"
        self.reject(packet, "unknown_reference")
        packet = copy.deepcopy(self.packet)
        del packet["calculations"][0]["supply_start"]
        self.reject(packet, "missing_field")
        packet = copy.deepcopy(self.packet)
        packet["calculations"][-1]["normalized_state"] = "unknown"
        self.reject(packet, "unknown_reference")
        packet = copy.deepcopy(self.packet)
        packet["calculations"][-1]["id"] = "physical"
        self.reject(packet, "duplicate_id")
        self.packet["calculations"][0]["probability"] = "0.8"
        self.reject(self.packet, "unknown_field")

    def test_unit_currency_and_percent_fraction_confusion(self):
        for oid, unit in (("supply_end", "quantity:bits"), ("normalized_core_asp", "currency:EUR/quantity:widgets"),
                          ("price", "currency:EUR/share"), ("normalized_core_tax_rate", "multiple")):
            with self.subTest(oid=oid, unit=unit):
                packet = copy.deepcopy(self.packet)
                packet["observations"][oid]["unit"] = unit
                self.reject(packet, "unit_mismatch")
        packet = copy.deepcopy(self.packet)
        packet["observations"]["normalized_core_tax_rate"]["unit"] = "percent"
        self.reject(packet, "unit")
        self.packet["observations"]["normalized_core_tax_rate"]["value"] = "25"
        self.reject(self.packet, "range")

    def test_measurement_definition_and_period_alignment(self):
        mutations = (
            ("supply_end", "period", {"start": "2026-10-22", "end": "2026-10-22"}, "period_mismatch"),
            ("supply_end", "definition", "Raw unqualified capacity; changed basis", "definition_mismatch"),
            ("normalized_core_da", "period", {"start": "2026-01-01", "end": "2026-12-31"}, "period_mismatch"),
            ("price", "period", {"start": "2026-10-22", "end": "2026-10-22"}, "period_mismatch"),
            ("target_multiple", "period", {"start": "2028-01-01", "end": "2028-12-31"}, "period_mismatch"),
        )
        for oid, field, value, code in mutations:
            with self.subTest(oid=oid, field=field):
                packet = copy.deepcopy(self.packet)
                packet["observations"][oid][field] = value
                self.reject(packet, code)
        packet = copy.deepcopy(self.packet)
        for oid, obs in packet["observations"].items():
            if oid.startswith("normalized_"):
                obs["period"]["end"] = "2027-06-30"
        self.reject(packet, "annual_period")

    def test_explicit_supply_demand_scope_and_basis(self):
        for field in ("market_scope", "measurement_basis"):
            for oid in ("supply_start", "supply_end", "demand_start", "demand_end"):
                with self.subTest(field=field, oid=oid):
                    packet = copy.deepcopy(self.packet)
                    del packet["observations"][oid][field]
                    self.reject(packet, "missing_field")
                    packet = copy.deepcopy(self.packet)
                    packet["observations"][oid][field] += " changed"
                    self.reject(packet, "comparability_mismatch")
                    packet["observations"][oid][field] = ""
                    self.reject(packet, "text")
        # Other observation types need not carry these fields, but supplied ones
        # are still validated. Matching text is an assertion, never verification.
        self.packet["observations"]["price"]["market_scope"] = ""
        self.reject(self.packet, "text")

    def test_declared_52_53_week_years_without_annualization(self):
        from datetime import date, timedelta
        for duration in (364, 371):
            with self.subTest(duration=duration):
                packet = copy.deepcopy(self.packet)
                start = date(2027, 1, 3)
                period = {"start": start.isoformat(), "end": (start + timedelta(days=duration - 1)).isoformat()}
                for oid, observation in packet["observations"].items():
                    if oid.startswith("normalized_") or oid == "target_multiple":
                        observation["period"] = period.copy()
                packet["calculations"][2]["annual_basis"] = "fiscal_52_53_week"
                output = cycle.calculate(packet)["results"]
                self.assertEqual(output["reverse"]["required_normalized_ebitda"], "300")
                self.assertEqual(output["reverse"]["annual_basis"], "fiscal_52_53_week")
                self.assertEqual(output["multiples"]["states"]["normalized"]["metric_period"], period)
        for duration in (363, 365, 366, 370, 372):
            with self.subTest(invalid_duration=duration):
                period = date(2027, 1, 3), date(2027, 1, 3) + timedelta(days=duration - 1)
                with self.assertRaises(cycle.CycleCheckError) as caught:
                    cycle._annual(period, "fiscal_52_53_week", "$")
                self.assertEqual(caught.exception.code, "annual_period")

    def test_unmarked_partial_year_bridge_cannot_supply_multiples(self):
        period = {"start": "2027-01-01", "end": "2027-03-31"}
        for oid, observation in self.packet["observations"].items():
            if oid.startswith("normalized_") or oid == "target_multiple":
                observation["period"] = period.copy()
        del self.packet["calculations"][2]["annual_basis"]
        self.reject(self.packet, "annual_basis")
        # A partial-year cash bridge alone is valid and stays unannualized.
        self.packet["calculations"] = self.packet["calculations"][:4]
        result = cycle.calculate(self.packet)["results"]["normalized"]
        self.assertIsNone(result["annual_basis"])
        self.assertEqual(result["period"], period)
        self.assertEqual(result["totals"]["ebitda"], "750")

    def test_timestamps_publication_cutoff_and_origin(self):
        packet = copy.deepcopy(self.packet)
        packet["observations"]["price"]["available_at"] = "2026-10-23T12:00:00.000001Z"
        self.reject(packet, "future_availability")
        # Same instant written with an offset remains available.
        packet["observations"]["price"]["available_at"] = "2026-10-23T13:00:00+01:00"
        self.assertEqual(cycle.calculate(packet)["status"], "ok")
        for value in ("2026-10-23", "2026-10-23T12:00:00", "2026-13-01T12:00:00Z",
                      "2026-10-23T12:00:00+00:99", "2026-10-23T12:00:00+24:00"):
            packet = copy.deepcopy(self.packet)
            packet["as_of"] = value
            self.reject(packet, "timestamp")
        packet = copy.deepcopy(self.packet)
        packet["observations"]["normalized_core_volume"]["origin"] = "reported"
        self.reject(packet, "future_reported_period")
        packet = copy.deepcopy(self.packet)
        packet["observations"]["price"]["source_ref"] = " "
        self.reject(packet, "text")
        del self.packet["observations"]["price"]["origin"]
        self.reject(self.packet, "missing_field")

    def test_every_observation_validated_and_no_financing(self):
        self.packet["observations"]["unused_future"] = copy.deepcopy(self.packet["observations"]["price"])
        self.packet["observations"]["unused_future"]["available_at"] = "2026-10-24T00:00:00Z"
        self.reject(self.packet, "future_availability")
        self.packet = example_packet()
        self.packet["calculations"][1]["financing_excluded"] = 1
        self.reject(self.packet, "financing_scope")
        self.packet = example_packet()
        self.packet["calculations"][1]["segments"][0]["interest"] = "net_debt"
        self.reject(self.packet, "unknown_field")

    def test_future_equity_snapshot_and_annual_leap_period(self):
        packet = copy.deepcopy(self.packet)
        for oid in cycle._BRIDGE_FIELDS:
            packet["observations"][oid]["period"] = {"start": "2026-10-24", "end": "2026-10-24"}
            packet["observations"][oid]["origin"] = "assumption"
        self.reject(packet, "future_snapshot")
        cycle._annual(cycle._period({"start": "2024-02-29", "end": "2025-02-28"}, "$"), "calendar_year", "$")
        with self.assertRaises(cycle.CycleCheckError) as caught:
            cycle._annual(cycle._period({"start": "9999-01-01", "end": "9999-12-31"}, "$"), "calendar_year", "$")
        self.assertEqual(caught.exception.code, "annual_period")

    def test_cli_determinism_atomic_preservation_and_structured_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "input.json", Path(directory) / "output.json"
            source.write_text(json.dumps(self.packet), encoding="utf-8")
            command = [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(output)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            saved = output.read_bytes()
            self.assertEqual(json.loads(saved), cycle.calculate(self.packet))
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(output.read_bytes(), saved)
            self.packet["observations"]["price"]["value"] = True
            source.write_text(json.dumps(self.packet), encoding="utf-8")
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(failed.returncode, 2)
            self.assertEqual(json.loads(failed.stderr)["error"]["code"], "decimal")
            self.assertEqual(failed.stdout, "")
            self.assertEqual(output.read_bytes(), saved)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])
            for malformed in ('{"version":1,"version":2}', '{"value":NaN}', '{bad'):
                source.write_text(malformed, encoding="utf-8")
                failed = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(failed.returncode, 2)
                self.assertEqual(json.loads(failed.stderr)["status"], "error")
                self.assertEqual(output.read_bytes(), saved)
            same_path = subprocess.run(command[:-1] + [str(source)], capture_output=True, text=True)
            self.assertEqual(same_path.returncode, 2)
            self.assertEqual(json.loads(same_path.stderr)["error"]["code"], "output_file")

    def test_atomic_replace_failure_preserves_output_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.json"
            output.write_text("previous output", encoding="utf-8")
            with mock.patch.object(cycle.os, "replace", side_effect=OSError("simulated failure")):
                with self.assertRaises(cycle.CycleCheckError) as caught:
                    cycle._atomic_output(output, {"status": "ok"})
            self.assertEqual(caught.exception.code, "output_file")
            self.assertEqual(output.read_text(encoding="utf-8"), "previous output")
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_public_byte_decoder_matches_cli_loader(self):
        encoded = json.dumps(self.packet).encode("utf-8")
        self.assertEqual(cycle.decode_packet(encoded), self.packet)
        cases = (
            (b'{"subject":"A","subject":"B"}', "duplicate_key"),
            (b'{"value":NaN}', "decimal"),
            (b'{"value":Infinity}', "decimal"),
            (b'\xff', "input_file"),
            (b'{bad', "input_file"),
            (b' ' * 2_000_001, "input_size"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "packet.json"
            for content, code in cases:
                with self.subTest(code=code, size=len(content)):
                    with self.assertRaises(cycle.CycleCheckError) as decoded:
                        cycle.decode_packet(content)
                    path.write_bytes(content)
                    with self.assertRaises(cycle.CycleCheckError) as loaded:
                        cycle.load_packet(path)
                    self.assertEqual(decoded.exception.code, code)
                    self.assertEqual(loaded.exception.as_dict(), decoded.exception.as_dict())
        with self.assertRaises(cycle.CycleCheckError) as caught:
            cycle.decode_packet('{"subject":"A"}')
        self.assertEqual(caught.exception.code, "input_file")


if __name__ == "__main__":
    unittest.main()
