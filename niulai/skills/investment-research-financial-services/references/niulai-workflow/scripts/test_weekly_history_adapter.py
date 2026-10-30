from copy import deepcopy
from datetime import datetime, timezone
import unittest

from weekly_history_adapter import ValidationError, engine_observations, parse_chart


def fixture():
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": "TEST", "currency": "USD", "exchangeTimezoneName": "America/New_York"},
        "timestamp": [1791552600, 1792157400],
        "indicators": {"quote": [{"close": [100, 110]}], "adjclose": [{"adjclose": [98, 110]}]},
    }]}}


class ParserTests(unittest.TestCase):
    def test_adjusted_close_and_actual_session_date(self):
        rows = parse_chart(fixture(), "TEST", ["2026-10-09", "2026-10-16"])["observations"]
        self.assertEqual([r["session_date"] for r in rows], ["2026-10-09", "2026-10-16"])
        self.assertEqual(rows[0]["adjusted_close"], 98)

    def test_missing_endpoint_not_nearby_substitution(self):
        with self.assertRaisesRegex(ValidationError, "missing required"):
            parse_chart(fixture(), "TEST", ["2026-10-15"])

    def test_null_endpoint_fails_coverage(self):
        value = fixture()
        value["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"][1] = None
        with self.assertRaisesRegex(ValidationError, "missing required"):
            parse_chart(value, "TEST", ["2026-10-16"])

    def test_array_length_mismatch(self):
        value = fixture()
        value["chart"]["result"][0]["indicators"]["quote"][0]["close"].pop()
        with self.assertRaisesRegex(ValidationError, "length mismatch"):
            parse_chart(value, "TEST")

    def test_duplicate_timestamp(self):
        value = fixture()
        value["chart"]["result"][0]["timestamp"][1] = value["chart"]["result"][0]["timestamp"][0]
        with self.assertRaisesRegex(ValidationError, "strictly increasing"):
            parse_chart(value, "TEST")

    def test_duplicate_session_date(self):
        value = fixture()
        value["chart"]["result"][0]["timestamp"][1] = value["chart"]["result"][0]["timestamp"][0] + 60
        with self.assertRaisesRegex(ValidationError, "duplicate session"):
            parse_chart(value, "TEST")

    def test_usd_and_new_york_required(self):
        for key, wrong in (("currency", "JPY"), ("exchangeTimezoneName", "Asia/Tokyo"), ("symbol", "OTHER")):
            with self.subTest(key=key):
                value = fixture()
                value["chart"]["result"][0]["meta"][key] = wrong
                with self.assertRaises(ValidationError):
                    parse_chart(value, "TEST")

    def test_nonpositive_nonfinite_boolean_price(self):
        for wrong in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(value=wrong):
                value = fixture()
                value["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"][1] = wrong
                with self.assertRaises(ValidationError):
                    parse_chart(value, "TEST")

    def test_future_timestamp_rejected(self):
        with self.assertRaisesRegex(ValidationError, "future observation"):
            parse_chart(fixture(), "TEST", as_of_utc=datetime(2026, 10, 10, tzinfo=timezone.utc))

    def test_provider_error_rejected(self):
        value = fixture()
        value["chart"]["error"] = {"code": "Not Found", "description": "No data"}
        with self.assertRaisesRegex(ValidationError, "provider_error"):
            parse_chart(value, "TEST")

    def test_weekday_holiday_is_not_a_session(self):
        value = fixture()
        value["chart"]["result"][0]["timestamp"] = [int(datetime(2026, 12, 25, 14, 30, tzinfo=timezone.utc).timestamp())]
        value["chart"]["result"][0]["indicators"] = {"quote": [{"close": [100]}], "adjclose": [{"adjclose": [100]}]}
        with self.assertRaisesRegex(ValidationError, "not an XNYS trading session"):
            parse_chart(value, "TEST")

    def test_flat_engine_feed_keeps_provider_adjclose_and_snapshot(self):
        parsed = parse_chart(fixture(), "TEST")
        parsed["source"] = {"sha256": "snapshot123", "url": "https://example.test/chart", "retrieved_at_utc": "2026-10-17T20:00:00Z"}
        rows = engine_observations([parsed])
        self.assertEqual(rows[0]["adjusted_close"], "98.0")
        self.assertEqual(rows[0]["adjustment_snapshot"], rows[1]["adjustment_snapshot"])
        self.assertEqual(rows[0]["observed_at"], "2026-10-17T20:00:00Z")
        self.assertEqual(rows[0]["adjustment_basis"], "split_and_dividend_adjusted_total_return")


if __name__ == "__main__":
    unittest.main()
