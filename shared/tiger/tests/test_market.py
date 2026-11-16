"""Offline market-snapshot schema and quote-method allowlist tests."""
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from shared.tiger import queries
from shared.tiger.market import _jsonable, execute_market_query
from shared.tiger.bridge import TigerBridgeError, require, write_json


def record(symbol="AAPL", entity="entity:aapl"):
    binding = {"entity_id": entity, "security_class": "COMMON_STOCK", "symbol": symbol, "venue": "NASDAQ"}
    return {**binding, "roster_row_sha256": hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


SELECTION_PATH = Path(__file__).resolve().parents[3] / "mentor/runtime/probabilistic-manifold-leverage-20261107/evidence/market-pilot-sample-selection-20261110-v1/sample-selection-v1.json"


def arguments():
    selection = json.loads(SELECTION_PATH.read_text())
    return {"as_of": "2020-12-31T23:59:59Z", "authorization_id": "mpa_" + "1" * 32,
            "authorization_sha256": "e" * 64, "corporate_action_start": "2020-01-01",
            "corporate_actions": ["split", "dividend", "symbol_change", "delisting"],
            "contract": {"calibration_sha256": "a" * 64, "promotion_sha256": "b" * 64,
                         "roster_sha256": queries.ROSTER_PACKET_SHA256,
                         "sample_selection_sha256": queries.SELECTION_DOCUMENT_SHA256},
            "fields": {"briefs": ["latest_price", "latest_time"], "stock_fundamental": ["market_cap", "ttm_eps"],
                       "financial_daily": ["shares_outstanding"], "financial_report": ["total_revenue", "net_income"]},
            "fx_currencies": ["USD", "EUR"], "sample_selection": selection,
            "symbols": selection["cohorts"]["calibration"]["query_symbol_records"]}


class MarketQueryTests(unittest.TestCase):
    def test_fixed_schema_and_roster_binding(self):
        query = queries.validate_query({"tool": "market_snapshot", "arguments": arguments()}, require)
        self.assertEqual(query["arguments"]["symbols"][0]["symbol"], "GRFS")
        bad = arguments(); bad["account"] = "forbidden"
        with self.assertRaisesRegex(TigerBridgeError, "ARGUMENTS_INVALID"):
            queries.validate_query({"tool": "market_snapshot", "arguments": bad}, require)
        bad = arguments(); bad["symbols"][0]["roster_row_sha256"] = "0" * 64
        with self.assertRaisesRegex(TigerBridgeError, "ROSTER_BINDING"):
            queries.validate_query({"tool": "market_snapshot", "arguments": bad}, require)

    def test_duplicates_caps_fields_provider_and_url_rejected(self):
        mutations = []
        bad = arguments(); bad["symbols"] *= 9; mutations.append(bad)
        bad = arguments(); bad["symbols"].append(dict(bad["symbols"][0])); mutations.append(bad)
        bad = arguments(); bad["fields"]["financial_report"] = ["arbitrary"]; mutations.append(bad)
        bad = arguments(); bad["provider"] = "other"; mutations.append(bad)
        bad = arguments(); bad["url"] = "https://attacker.test"; mutations.append(bad)
        bad = arguments(); bad["authorization_id"] = "../private/path"; mutations.append(bad)
        bad = arguments(); bad["authorization_path"] = "/private/secret"; mutations.append(bad)
        for bad in mutations:
            with self.subTest(bad=bad), self.assertRaises(TigerBridgeError):
                queries.validate_query({"tool": "market_snapshot", "arguments": bad}, require)


    def test_jsonable_rejects_arbitrary_provider_objects_without_stringifying(self):
        class Dangerous:
            def __str__(self):
                raise AssertionError("must not stringify provider objects")
        with self.assertRaisesRegex(TypeError, "TIGER_MARKET_RESPONSE_INVALID"):
            _jsonable(Dangerous())

    def test_quote_sdk_factory_returns_quote_type_without_trade_or_profile_access(self):
        from niulai.holdings import niulai_tiger as n
        class FakeSession: pass
        class FakeAuth:
            def __init__(self, session): self.session = session
        class FakeConfig:
            def __init__(self, **kwargs): self.kwargs = kwargs
        class FakeQuoteClient:
            def __init__(self, config): self.config = config
        forbidden_trade = Mock(side_effect=AssertionError("trade factory must not run"))
        oauth = types.ModuleType("tigeropen.auth.oauth2"); oauth.OAuth2Authentication = FakeAuth
        quote = types.ModuleType("tigeropen.quote.quote_client"); quote.QuoteClient = FakeQuoteClient
        config = types.ModuleType("tigeropen.tiger_open_config"); config.TigerOpenClientConfig = FakeConfig
        urllib3 = types.ModuleType("urllib3")
        class FakeTimeout:
            def __init__(self, **kwargs): self.kwargs = kwargs
        urllib3.Timeout = FakeTimeout
        modules = {"urllib3": urllib3, "tigeropen": types.ModuleType("tigeropen"),
                   "tigeropen.auth": types.ModuleType("tigeropen.auth"), "tigeropen.auth.oauth2": oauth,
                   "tigeropen.quote": types.ModuleType("tigeropen.quote"), "tigeropen.quote.quote_client": quote,
                   "tigeropen.tiger_open_config": config}
        with patch.object(n, "sdk_classes", return_value=(FakeSession, forbidden_trade)) as sdk, patch.dict("sys.modules", modules):
            Session, factory = n.quote_sdk_classes()
            client = factory(object())
        self.assertIs(Session, FakeSession)
        self.assertIs(type(client), FakeQuoteClient)
        self.assertNotIsInstance(client, forbidden_trade.__class__)
        sdk.assert_called_once_with(include_quotes=True)
        forbidden_trade.assert_not_called()

    def test_market_multi_method_failure_publishes_no_partial_artifacts(self):
        class Dangerous:
            def __str__(self): raise AssertionError("must not stringify")
        class Session:
            def __init__(self, **kwargs): pass
            def status(self): return object()
        for failure in ("serializer", "provider"):
            calls = []
            class Quote:
                def __getattr__(self, name):
                    def method(*args, **kwargs):
                        calls.append(name)
                        if failure == "serializer" and name == "get_stock_fundamental": return Dangerous()
                        if failure == "provider" and name == "get_financial_report": raise RuntimeError("private provider text")
                        return [{"value": "1"}]
                    return method
            n = Mock(); n.profile_lock.return_value = nullcontext(); n.quote_sdk_classes.return_value = (Session, lambda sdk: Quote())
            n.validate_token = Mock(); n.ISSUER = n.SURFACE = n.CLIENT_NAME = "synthetic"
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                out = Path(temp)
                with self.assertRaises((TypeError, RuntimeError)):
                    execute_market_query(n, out, {"tool": "market_snapshot", "arguments": arguments()}, require, write_json, out)
                self.assertEqual(list(out.iterdir()), [])
                self.assertGreater(len(calls), 1)

    def test_quote_executor_never_discovers_accounts_and_receipt_has_no_values(self):
        calls = []
        class Quote:
            def __getattr__(self, name):
                if name == "get_managed_accounts": raise AssertionError("account discovery forbidden")
                def method(*args, **kwargs):
                    calls.append(name)
                    return [{"symbol": "AAPL", "value": "123.45"}]
                return method
        class Session:
            def __init__(self, **kwargs): pass
            def status(self): return object()
        n = Mock()
        n.profile_lock.return_value = nullcontext()
        n.quote_sdk_classes.return_value = (Session, lambda sdk: Quote())
        n.validate_token = Mock()
        n.ISSUER = n.SURFACE = n.CLIENT_NAME = "synthetic"
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            result = execute_market_query(n, out, {"tool": "market_snapshot", "arguments": arguments()}, require, write_json, out)
            self.assertEqual(result["symbols_count"], 8)
            self.assertNotIn("123.45", json.dumps(result))
            self.assertIn("123.45", (out / "market_raw.json").read_text())
        self.assertEqual(calls, ["get_stock_briefs", "get_stock_fundamental", "get_financial_daily",
            "get_financial_report", "get_financial_currency", "get_financial_exchange_rate",
            "get_corporate_split", "get_corporate_dividend", "get_corporate_symbol_change", "get_corporate_delisting"])
        n.validate_token.assert_called_once_with(unittest.mock.ANY, require_quotes=True)
