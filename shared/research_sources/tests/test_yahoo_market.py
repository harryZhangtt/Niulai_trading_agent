import io
import json
import unittest
from urllib import error
from shared.research_sources import yahoo_market as y

class Response(io.BytesIO):
    def __init__(self, body=b'{"ok":true}', url="https://query1.finance.yahoo.com/v8/finance/chart/AAPL"):
        super().__init__(body); self._url = url; self.headers = {"Content-Type": "application/json", "Set-Cookie": "private"}
    def geturl(self): return self._url
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
class Opener:
    def __init__(self, response): self.response=response; self.calls=0; self.request=None
    def open(self, request, timeout): self.calls += 1; self.request=request; return self.response

class YahooTests(unittest.TestCase):
    def test_chart_is_fixed_secondary_one_attempt(self):
        op = Opener(Response())
        raw = y.fetch_chart("AAPL", 1, 100, opener=op)
        self.assertTrue(raw.secondary); self.assertEqual(op.calls, 1); self.assertEqual(raw.byte_count, 11)
        self.assertNotIn("set-cookie", raw.headers)
        self.assertIn("events=div%2Csplits", op.request.full_url)
    def test_fundamentals_fixed_host_and_type(self):
        url = "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/AAPL"
        op = Opener(Response(url=url))
        y.fetch_fundamentals(["AAPL"], ["annualNetIncome"], 1, 100, opener=op)
        self.assertEqual(op.calls, 1); self.assertTrue(op.request.full_url.startswith(url))
        for types in (["arbitraryType"], [], ["annualNetIncome", "annualNetIncome"]):
            with self.assertRaises(y.YahooMarketError): y.fetch_fundamentals(["AAPL"], types, 1, 100, opener=op)
        self.assertEqual(op.calls, 1)
    def test_rejects_redirect_bad_json_caps_and_arbitrary_symbols(self):
        redirect = Opener(Response(url="https://attacker.test/data"))
        with self.assertRaisesRegex(y.YahooMarketError, "REDIRECT"): y.fetch_chart("AAPL", 1, 100, opener=redirect)
        bad = Opener(Response(body=b"not json"))
        with self.assertRaisesRegex(y.YahooMarketError, "RESPONSE_INVALID"): y.fetch_chart("AAPL", 1, 100, opener=bad)
        for symbol in ("aapl", "AAPL/../../x", "https://attacker.test"):
            with self.assertRaises(y.YahooMarketError): y.fetch_chart(symbol, 1, 100, opener=Opener(Response()))
