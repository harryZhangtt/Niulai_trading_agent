import copy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from weekly_scan import BASIS, ValidationError, completed_week, rank_week

AS_OF = "2026-10-18T04:08:05+08:00"


def universe(count):
    return [{"symbol": f"S{i:02d}", "id": f"security:S{i:02d}", "security_type": "equity"} for i in range(count)]


def prices(symbol, end="110", baseline="100", **overrides):
    result = []
    for session, value in (("2026-10-09", baseline), ("2026-10-16", end)):
        row = {"symbol": symbol, "session": session, "adjusted_close": value,
               "currency": "USD", "price_unit": "currency_per_share",
               "adjustment_basis": BASIS, "adjustment_snapshot": "fixture-asof-20261017",
               "source": "offline fixture", "observed_at": "2026-10-17T00:00:00Z"}
        row.update(overrides)
        result.append(row)
    return result


class CalendarTests(unittest.TestCase):
    def test_shanghai_sunday_last_friday_and_baseline(self):
        w = completed_week(AS_OF)
        self.assertEqual(w["week_start"], "2026-10-12")
        self.assertEqual(w["end_session"], "2026-10-16")
        self.assertEqual(w["baseline_session"], "2026-10-09")
        self.assertEqual(w["end_close_utc"], "2026-10-16T20:00:00Z")

    def test_current_friday_not_closed_uses_previous_week(self):
        w = completed_week("2026-10-16T15:59:00-04:00")
        self.assertEqual(w["end_session"], "2026-10-09")

    def test_close_instant_is_completed(self):
        self.assertEqual(completed_week("2026-10-16T16:00:00-04:00")["end_session"], "2026-10-16")

    def test_christmas_week_complete_on_thursday_early_close(self):
        w = completed_week("2026-12-24T13:01:00-05:00")
        self.assertEqual(w["end_session"], "2026-12-24")
        self.assertEqual(w["end_close_utc"], "2026-12-24T18:00:00Z")
        self.assertEqual(len(w["sessions"]), 4)

    def test_black_friday_early_close_and_dst(self):
        self.assertEqual(completed_week("2026-11-27T12:59:00-05:00")["end_session"], "2026-11-20")
        w = completed_week("2026-11-27T13:00:00-05:00")
        self.assertEqual(w["end_session"], "2026-11-27")
        self.assertEqual(w["end_close_utc"], "2026-11-27T18:00:00Z")

    def test_future_unfinished_and_nonmonday_requests_rejected(self):
        for week in ("2026-10-19", "2026-10-13"):
            with self.assertRaises(ValidationError):
                completed_week(AS_OF, week)
        with self.assertRaises(ValidationError):
            completed_week("2026-10-16T15:00:00-04:00", "2026-10-12")

    def test_naive_clock_rejected(self):
        with self.assertRaises(ValidationError):
            completed_week("2026-10-18T04:08:05")


class RankingTests(unittest.TestCase):
    def test_37_names_eight_each_and_decimal_return(self):
        names = universe(37)
        observations = sum([prices(row["symbol"], str(80 + i)) for i, row in enumerate(names)], [])
        result = rank_week(names, observations, AS_OF)
        self.assertEqual(result["coverage"]["tail_count_each"], 8)
        self.assertEqual(result["coverage"]["valid_count"], 37)
        self.assertEqual([r["symbol"] for r in result["top_performing"]], [f"S{i:02d}" for i in range(36, 28, -1)])
        self.assertEqual([r["symbol"] for r in result["bottom_performing"]], [f"S{i:02d}" for i in range(8)])
        self.assertEqual(Decimal(result["ranking"][0]["weekly_total_return"]), Decimal("0.16"))
        self.assertFalse(result["price_move_is_thesis_evidence"])

    def test_ties_are_disjoint_deterministic_and_order_independent(self):
        names = universe(10)
        observations = sum([prices(row["symbol"]) for row in names], [])
        first = rank_week(names, observations, AS_OF)
        second = rank_week(list(reversed(names)), list(reversed(observations)), AS_OF)
        self.assertEqual(first["ranking"], second["ranking"])
        self.assertEqual([r["symbol"] for r in first["top_performing"]], ["S00", "S01"])
        self.assertEqual([r["symbol"] for r in first["bottom_performing"]], ["S08", "S09"])
        self.assertFalse({r["symbol"] for r in first["top_performing"]} & {r["symbol"] for r in first["bottom_performing"]})

    def test_small_universe_caps_to_avoid_overlap(self):
        for count, expected in ((1, 0), (2, 1), (3, 1), (6, 2)):
            result = rank_week(universe(count), sum([prices(f"S{i:02d}") for i in range(count)], []), AS_OF)
            self.assertEqual(result["coverage"]["tail_count_each"], expected)

    def test_configured_tail_fraction_changes_actual_selection(self):
        names = universe(37)
        observations = sum([prices(row["symbol"], str(80 + i)) for i, row in enumerate(names)], [])
        result = rank_week(names, observations, AS_OF, tail_fraction="0.10")
        self.assertEqual(result["coverage"]["tail_count_each"], 4)
        self.assertEqual(len(result["top_performing"]), 4)
        self.assertEqual(len(result["bottom_performing"]), 4)
        self.assertEqual(result["method"]["selection_fraction"], "0.1")
        half = rank_week(names, observations, AS_OF, tail_fraction="0.5")
        self.assertEqual(half["coverage"]["tail_count_each"], 18)
        self.assertFalse({r["symbol"] for r in half["top_performing"]} & {r["symbol"] for r in half["bottom_performing"]})

    def test_invalid_tail_fractions_rejected(self):
        for invalid in (True, False, "0", "-0.1", "0.50001", "1", "NaN", "Infinity", "-Infinity", "oops", None, 0.2, float("nan")):
            with self.subTest(fraction=invalid), self.assertRaises(ValidationError):
                rank_week(universe(1), prices("S00"), AS_OF, tail_fraction=invalid)

    def test_missing_data_is_excluded_never_zero(self):
        result = rank_week(universe(3), prices("S00") + prices("S01")[:1], AS_OF)
        self.assertEqual(result["coverage"]["valid_count"], 1)
        self.assertFalse(result["coverage"]["complete"])
        self.assertEqual({r["symbol"] for r in result["coverage"]["excluded"]}, {"S01", "S02"})
        self.assertEqual(len(result["ranking"]), 1)

    def test_nonpositive_nonfinite_raw_and_mixed_units_excluded(self):
        cases = ("0", "-5", "NaN", "Infinity", "-Infinity", 1.1, float("nan"), float("inf"))
        for invalid in cases:
            result = rank_week(universe(1), prices("S00", end=invalid), AS_OF)
            self.assertEqual(result["coverage"]["valid_count"], 0)
            self.assertEqual(result["coverage"]["excluded"][0]["reasons"][0]["reason"], "invalid_endpoint")
        for field, value in (("currency", "JPY"), ("price_unit", "cents_per_share"),
                             ("adjustment_basis", "raw_close"), ("adjustment_snapshot", "other"), ("source", "other")):
            observation = prices("S00")
            observation[1][field] = value
            self.assertEqual(rank_week(universe(1), observation, AS_OF)["coverage"]["valid_count"], 0)

    def test_split_and_dividend_adjustment_is_required_and_used(self):
        # Raw closes could look like a 50% split loss; the adjusted series gives +2%.
        rows = prices("S00", end="51", baseline="50")
        rows[0]["raw_close"] = "100"
        rows[1]["raw_close"] = "50"
        result = rank_week(universe(1), rows, AS_OF)
        self.assertEqual(result["ranking"][0]["weekly_total_return"], "0.02")
        self.assertEqual(result["ranking"][0]["source"], "offline fixture")

    def test_ambiguous_duplicate_inputs_rejected(self):
        names = universe(2)
        names[1]["id"] = names[0]["id"]
        with self.assertRaises(ValidationError):
            rank_week(names, [], AS_OF)
        with self.assertRaises(ValidationError):
            rank_week(universe(1) * 2, [], AS_OF)
        with self.assertRaises(ValidationError):
            rank_week(universe(1), prices("S00") * 2, AS_OF)

    def test_future_and_preclose_observations_are_not_final_closes(self):
        for invalid_timestamp in ("2026-10-19T00:00:00Z", "2026-10-16T19:59:59Z"):
            rows = prices("S00")
            rows[1]["observed_at"] = invalid_timestamp
            result = rank_week(universe(1), rows, AS_OF)
            self.assertEqual(result["coverage"]["valid_count"], 0)

    def test_leverage_label_and_coverage_provenance_retained(self):
        names = [{"id": "security:SOXL", "symbol": "SOXL", "security_type": "leveraged_etf", "leverage_label": "3x daily reset"}]
        result = rank_week(names, prices("SOXL"), AS_OF)
        self.assertEqual(result["ranking"][0]["leverage_label"], "3x daily reset")
        self.assertEqual(result["input_provenance"]["calendar_version"], "4.11.2")
        self.assertEqual(len(result["input_provenance"]["endpoint_observations_sha256"]), 64)
        self.assertEqual(json.loads(json.dumps(result)), result)


if __name__ == "__main__":
    unittest.main()
