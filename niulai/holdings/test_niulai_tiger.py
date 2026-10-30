from contextlib import redirect_stdout
from decimal import Decimal
from io import StringIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import niulai_tiger as app


ACCOUNT = "synthetic-private-account"


def item(**updates):
    return {"account": ACCOUNT, "symbol": "TEST", "secType": "STK", "currency": "USD", "market": "US",
            "contractId": 123, "position": 773, "positionQty": Decimal("0.00773"), "positionScale": 5,
            "latestPrice": Decimal("183.52"), "marketValue": Decimal("1.4186096"), **updates}


class StandaloneTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.profile = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_unknown_zero_signed_and_scaled_quantities_are_distinct(self):
        row = app.normalize_items([item()], ACCOUNT)[0]
        self.assertEqual(row["quantity"], "0.00773")
        self.assertEqual(row["reportedQuantity"], "773")
        self.assertEqual(row["reportedQuantityScale"], "5")
        missing = item(); del missing["positionQty"]
        self.assertIsNone(app.normalize_items([missing], ACCOUNT)[0]["quantity"])
        for value, expected in ((0, "0"), (Decimal("-1.5"), "-1.5")):
            self.assertEqual(app.normalize_items([item(positionQty=value)], ACCOUNT)[0]["quantity"], expected)

    def test_derivative_identity_multiplier_and_currency_are_preserved(self):
        row = app.normalize_items([item(secType="OPT", currency="HKD", market="HK", multiplier=100, expiry="20261120", strike=25, right="CALL")], ACCOUNT)[0]
        self.assertEqual((row["securityType"], row["currency"], row["multiplier"], row["expiry"], row["putCall"]), ("OPT", "HKD", "100", "20261120", "CALL"))
        self.assertIsNone(row["unrealizedPnl"])

    def test_account_and_duplicates_are_not_silently_merged(self):
        with self.assertRaisesRegex(app.ReadOnlyError, "POSITION_ACCOUNT_MISMATCH"):
            app.normalize_items([item(account="wrong")], ACCOUNT)
        with self.assertRaisesRegex(app.ReadOnlyError, "DUPLICATE_POSITION"):
            app.normalize_items([item(), item()], ACCOUNT)

    def test_decimal_precision_and_invalid_values(self):
        self.assertEqual(app.amount(Decimal("0.123456789012345678")), "0.123456789012345678")
        for value in (True, Decimal("NaN"), Decimal("Infinity"), "secret-value"):
            with self.subTest(value=str(value)):
                with self.assertRaisesRegex(app.ReadOnlyError, "INVALID_AMOUNT"):
                    app.amount(value)

    def test_account_selection_single_pin_multiple_and_continuity(self):
        client = SimpleNamespace(get_managed_accounts=lambda: [SimpleNamespace(account=ACCOUNT)])
        pin = app.select_account(client, self.profile)
        self.assertEqual(pin, app.select_account(client, self.profile))
        self.assertNotIn(ACCOUNT, pin["ref"])
        client.get_managed_accounts = lambda: [SimpleNamespace(account="different")]
        with self.assertRaisesRegex(app.ReadOnlyError, "ACCOUNT_PIN_MISMATCH"):
            app.select_account(client, self.profile)
        (self.profile / "account-pin.json").unlink()
        client.get_managed_accounts = lambda: [SimpleNamespace(account="one"), SimpleNamespace(account="two")]
        with self.assertRaisesRegex(app.ReadOnlyError, "MULTIPLE_ACCOUNTS_REQUIRE_PRIVATE_SELECTION"):
            app.select_account(client, self.profile)
        self.assertFalse((self.profile / "account-pin.json").exists())

    def test_profile_lock_and_permissions(self):
        with app.profile_lock(self.profile):
            self.assertEqual(self.profile.stat().st_mode & 0o777, 0o700)
            self.assertEqual((self.profile / ".lock").stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(app.ReadOnlyError, "PROFILE_BUSY"):
                with app.profile_lock(self.profile): pass
        link = self.profile / "link"; link.symlink_to(self.profile, target_is_directory=True)
        with self.assertRaisesRegex(app.ReadOnlyError, "PROFILE_SYMLINK_REJECTED"):
            with app.profile_lock(link): pass

    def test_atomic_private_output_and_no_account_id_in_normalized_result(self):
        out = self.profile / "out.json"
        app.write_private(out, {"safe": "first"})
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)
        app.write_private(out, {"safe": "second"})
        self.assertEqual(json.loads(out.read_text()), {"safe": "second"})
        self.assertNotIn(ACCOUNT, json.dumps(app.normalize_items([item()], ACCOUNT)))

    def test_token_scopes_exact_read_only(self):
        valid = SimpleNamespace(issuer=app.ISSUER, scope=" ".join(app.SCOPES))
        app.validate_token(valid)
        for scope in (valid.scope + " api.trade:write", "api.basic:read", ""):
            with self.assertRaisesRegex(app.ReadOnlyError, "TOKEN_SCOPE_REJECTED"):
                app.validate_token(SimpleNamespace(issuer=app.ISSUER, scope=scope))

    def test_sdk_metadata_default_all_scopes_is_overridden_before_grant(self):
        from tigeropen.auth.oauth2.metadata import OAuth2Metadata
        Session, _ = app.sdk_classes()
        session = Session(issuer=app.ISSUER, home=str(self.profile), surface=app.SURFACE, client_name=app.CLIENT_NAME)
        session._metadata = OAuth2Metadata(issuer=app.ISSUER, authorization_endpoint=app.ISSUER + "/authorize", token_endpoint=app.ISSUER + "/token", scopes_supported=[*app.SCOPES, "api.trade:write", "api.quote:read"])
        self.assertEqual(set(session.scopes.split()), app.SCOPES)
        session._metadata.token_endpoint = "https://wrong.invalid/token"
        with self.assertRaisesRegex(app.ReadOnlyError, "OAUTH_ENDPOINT_MISMATCH"):
            session._scopes()

    def test_sdk_broadened_grant_is_not_persisted(self):
        from tigeropen.auth.oauth2.token import OAuth2Token
        Session, _ = app.sdk_classes()
        session = Session(issuer=app.ISSUER, home=str(self.profile), surface=app.SURFACE, client_name=app.CLIENT_NAME)
        token = OAuth2Token(issuer=app.ISSUER, client_id="fixture", access_token="fake-secret", scope=" ".join(app.SCOPES) + " api.trade:write")
        with self.assertRaisesRegex(app.ReadOnlyError, "TOKEN_SCOPE_REJECTED"):
            session._persist(token)
        self.assertFalse((self.profile / "tokens").exists())

    def test_sdk_oauth_and_business_share_verified_tls_proxy_with_no_retries(self):
        from tigeropen.auth.oauth2 import http_utils
        from tigeropen.common.util import web_utils
        import urllib3
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.invalid:3128"}):
            app.sdk_classes()
        self.assertIsInstance(http_utils._http_pool, urllib3.ProxyManager)
        self.assertIs(http_utils._http_pool, web_utils.http_pool)
        self.assertEqual(web_utils.http_pool.connection_pool_kw["cert_reqs"], "CERT_REQUIRED")
        self.assertIs(web_utils.http_pool.connection_pool_kw["retries"].total, False)
        self.assertEqual(http_utils._timeout.connect_timeout, 20)
        self.assertEqual(http_utils._timeout.read_timeout, 30)

    def test_official_sdk_full_fetch_offline_transport_and_read_endpoint_guard(self):
        from tigeropen.auth.oauth2.token import OAuth2Token
        from tigeropen.common.request import OpenApiRequest
        from tigeropen.common.util import web_utils
        from tigeropen.common.consts.service_types import ACCOUNTS, POSITIONS
        Session, client_factory = app.sdk_classes()
        session = Session(issuer=app.ISSUER, home=str(self.profile), surface=app.SURFACE, client_name=app.CLIENT_NAME)
        session._token = OAuth2Token(issuer=app.ISSUER, client_id="fixture", access_token="fake-secret", scope=" ".join(app.SCOPES), expires_at=int(time.time() * 1000) + 3600000)
        calls = []
        class Pool:
            def request(self, _method, **kwargs):
                request = json.loads(kwargs["body"]); calls.append(request["method"])
                if request["method"] == ACCOUNTS:
                    body = json.dumps({"code": 0, "data": {"items": [{"account": ACCOUNT, "status": "Open", "capability": "CASH"}]}})
                else:
                    self.assert_positions(request)
                    body = '{"code":0,"data":{"items":[{"account":"synthetic-private-account","symbol":"TEST","secType":"STK","currency":"USD","market":"US","positionQty":0.123456789012345678,"position":123,"latestPrice":10}]}}'
                return SimpleNamespace(status=200, data=body.encode())
            def assert_positions(self, request):
                if request["method"] != POSITIONS: raise AssertionError("unexpected endpoint")
        web_utils.http_pool = Pool()
        client = client_factory(session)
        result = app.fetch(client, self.profile, ("STK",))
        self.assertEqual(calls, [ACCOUNTS, POSITIONS])
        self.assertEqual(result["positions"][0]["quantity"], "0.123456789012345678")
        self.assertTrue(result["freshSourceResponse"])
        self.assertIsNone(result["sourceSnapshotAt"])
        self.assertFalse(result["coverage"]["wholePortfolioVerified"])
        self.assertNotIn(ACCOUNT, json.dumps(result))
        with self.assertRaisesRegex(app.ReadOnlyError, "READ_ENDPOINT_ONLY"):
            client.execute(OpenApiRequest("place_order"))
        self.assertEqual(calls, [ACCOUNTS, POSITIONS])

    def test_missing_partial_and_explicit_empty_are_distinct(self):
        def client(positions, data):
            return SimpleNamespace(get_managed_accounts=lambda: [SimpleNamespace(account=ACCOUNT)], get_positions=lambda **kwargs: positions, raw_data=data)
        for positions, data, code in ((None, {"items": []}, "POSITIONS_RESPONSE_MISSING"), ([], {}, "POSITIONS_ITEMS_MISSING"), ([], {"items": [], "hasMore": True}, "PAGINATION_OR_PARTIAL_RESPONSE")):
            with self.subTest(code=code):
                result = app.fetch(client(positions, data), self.profile, ("STK",))
                self.assertEqual(result["sourceReadStatus"], "failed")
                self.assertIsNone(result["positions"])
                self.assertEqual(result["typeReads"][0]["error"], code)
        self.assertEqual(app.fetch(client([], {"items": []}), self.profile, ("STK",))["coverage"]["positionCount"], 0)

    def test_all_accounts_two_separate_groups_stable_refs_and_source_types(self):
        identities = [ACCOUNT, "synthetic-second-account"]
        queries = []
        client = SimpleNamespace(get_managed_accounts=lambda: [SimpleNamespace(account=identities[0], account_type="REAL", status="Open", capability="CASH"), SimpleNamespace(account=identities[1], account_type="PAPER", status="Open", capability="MGRN")])
        def positions(**kwargs):
            queries.append(kwargs["account"])
            client.raw_data = {"items": [item(account=kwargs["account"])]}
            return [object()]
        client.get_positions = positions
        first = app.fetch_all(client, self.profile, ("STK",))
        second = app.fetch_all(client, self.profile, ("STK",))
        self.assertEqual(queries, identities * 2)
        self.assertEqual(first["sourceReadStatus"], "complete")
        self.assertEqual(first["accountCount"], 2)
        refs = [row["accountRef"] for row in first["accountResults"]]
        self.assertEqual(len(set(refs)), 2)
        self.assertEqual(refs, [row["accountRef"] for row in second["accountResults"]])
        self.assertEqual([row["sourceAccountMetadata"]["account_type"] for row in first["accountResults"]], ["REAL", "PAPER"])
        self.assertTrue(all(len(row["positions"]) == 1 for row in first["accountResults"]))
        self.assertFalse(first["aggregationPerformed"])
        self.assertNotIn("positions", first)
        self.assertNotIn(ACCOUNT, json.dumps(first))
        self.assertNotIn(identities[1], json.dumps(first))

    def test_all_accounts_one_failure_is_explicit_partial_not_empty(self):
        identities = [ACCOUNT, "synthetic-failed-account"]
        queries = []
        client = SimpleNamespace(get_managed_accounts=lambda: [SimpleNamespace(account=value) for value in identities])
        def positions(**kwargs):
            queries.append(kwargs["account"])
            if kwargs["account"] == identities[1]: raise RuntimeError("fake-secret-token " + identities[1])
            client.raw_data = {"items": [item(account=kwargs["account"])]}
            return [object()]
        client.get_positions = positions
        result = app.fetch_all(client, self.profile, ("STK",))
        self.assertEqual(queries, identities)
        self.assertEqual(result["sourceReadStatus"], "partial")
        self.assertEqual((result["successfulAccountCount"], result["failedAccountCount"]), (1, 1))
        self.assertTrue(result["accountResults"][0]["ok"])
        failed = result["accountResults"][1]
        self.assertFalse(failed["ok"])
        self.assertIsNone(failed["positions"])
        self.assertEqual(failed["error"], "ALL_REQUESTED_SECURITY_TYPES_FAILED")
        self.assertEqual(failed["typeReads"][0]["error"], "TIGER_REQUEST_FAILED")
        self.assertNotIn("fake-secret-token", json.dumps(result))
        self.assertNotIn(identities[1], json.dumps(result))

    def test_confirmed_provider_all_rejection_fixture_uses_explicit_types_only(self):
        from tigeropen.common.exceptions import ApiException
        calls = []
        client = SimpleNamespace()
        def positions(**kwargs):
            security_type = kwargs["sec_type"]; calls.append(security_type)
            if security_type == "ALL": raise ApiException(1010, "biz param error(sec_type unsupported value: ALL.)")
            client.raw_data = {"items": [item()] if security_type == "STK" else []}
            return [object()] if security_type == "STK" else []
        client.get_positions = positions
        result = app.fetch_account(client, {"account": ACCOUNT, "ref": "a" * 32})
        self.assertEqual(calls, ["STK", "OPT", "FUT"])
        self.assertEqual(result["sourceReadStatus"], "complete")
        self.assertEqual(result["coverage"]["requestedSecurityTypes"], ["STK", "OPT", "FUT"])
        self.assertEqual([entry["positionCount"] for entry in result["typeReads"]], [1, 0, 0])
        with self.assertRaisesRegex(app.ReadOnlyError, "SECURITY_TYPES_INVALID"):
            app.fetch_account(client, {"account": ACCOUNT, "ref": "a" * 32}, ("ALL",))
        self.assertEqual(calls, ["STK", "OPT", "FUT"])

    def test_failed_type_retains_valid_rows_and_unknown_type_coverage(self):
        from tigeropen.common.exceptions import ApiException
        calls = []
        client = SimpleNamespace()
        def positions(**kwargs):
            security_type = kwargs["sec_type"]; calls.append(security_type)
            if security_type == "OPT": raise ApiException(1010, "unsupported type; fake-secret " + ACCOUNT)
            client.raw_data = {"items": [item()] if security_type == "STK" else []}
            return [object()] if security_type == "STK" else []
        client.get_positions = positions
        result = app.fetch_account(client, {"account": ACCOUNT, "ref": "a" * 32})
        self.assertEqual(calls, ["STK", "OPT", "FUT"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["sourceReadStatus"], "partial")
        self.assertEqual(len(result["positions"]), 1)
        self.assertEqual(result["coverage"]["successfulSecurityTypes"], ["STK", "FUT"])
        self.assertEqual(result["coverage"]["failedSecurityTypes"], ["OPT"])
        self.assertIsNone(result["typeReads"][1]["positionCount"])
        self.assertEqual(result["typeReads"][1]["diagnostic"]["providerCode"], 1010)
        self.assertNotIn("fake-secret", json.dumps(result))

    def test_source_name_identifier_and_update_timestamp_preserved_without_time_claim(self):
        row = app.normalize_items([item(name="Example Company", identifier="TEST  261120C00025000", updateTimestamp=Decimal("1792900000123"), status="NORMAL")], ACCOUNT)[0]
        self.assertEqual(row["name"], "Example Company")
        self.assertEqual(row["identifier"], "TEST  261120C00025000")
        self.assertEqual(row["reportedUpdateTimestamp"], "1792900000123")
        self.assertEqual(row["reportedStatus"], "NORMAL")
        self.assertIn("not a verified market-price timestamp", row["reportedUpdateTimestampSemantics"])

    def test_success_history_survives_later_partial_and_failed_without_cached_fallback(self):
        out = self.profile / "holdings.json"
        success = {"sourceReadStatus": "complete", "queryCompletedAt": "2026-10-26T01:00:00Z", "positions": ["fixture-success"]}
        app.save_snapshot(out, success)
        backup = self.profile / "holdings.last_successful.json"
        self.assertEqual(json.loads(backup.read_text()), success)
        for state in ("partial", "failed"):
            current = {"sourceReadStatus": state, "queryCompletedAt": "2026-10-26T02:00:00Z", "positions": None, "cachedFallbackUsed": False}
            app.save_snapshot(out, current)
            self.assertEqual(json.loads(out.read_text()), current)
            self.assertEqual(json.loads(backup.read_text()), success)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_existing_success_is_seeded_before_failed_output_and_backup_failure_stops_overwrite(self):
        out = self.profile / "holdings.json"
        success = {"sourceReadStatus": "complete", "positions": ["fixture-success"]}
        app.write_private(out, success)
        original_write = app.write_private
        def failing_write(path, data):
            if "last_successful" in Path(path).name: raise OSError("fixture disk failure")
            original_write(path, data)
        with patch.object(app, "write_private", side_effect=failing_write):
            with self.assertRaises(OSError): app.save_snapshot(out, {"sourceReadStatus": "failed", "positions": None})
        self.assertEqual(json.loads(out.read_text()), success)
        with patch.object(Path, "read_text", side_effect=PermissionError("fixture unreadable prior snapshot")):
            with self.assertRaises(PermissionError): app.save_snapshot(out, {"sourceReadStatus": "failed", "positions": None})
        self.assertEqual(json.loads(out.read_text()), success)
        app.save_snapshot(out, {"sourceReadStatus": "failed", "positions": None})
        self.assertEqual(json.loads((self.profile / "holdings.last_successful.json").read_text()), success)

    def test_failed_cli_attempt_saves_failed_record_and_preserves_prior_success(self):
        out = self.profile / "holdings.json"
        success = {"sourceReadStatus": "complete", "queryCompletedAt": "2026-10-26T01:00:00Z"}
        app.write_private(out, success)
        with self.assertRaises(ValueError):
            with app.snapshot_attempt(SimpleNamespace(command="fetch", out=out)):
                raise ValueError("fake-secret-token " + ACCOUNT)
        current = json.loads(out.read_text())
        self.assertEqual(current["sourceReadStatus"], "failed")
        self.assertIsNone(current["positions"])
        self.assertFalse(current["freshSourceResponse"])
        self.assertFalse(current["cachedFallbackUsed"])
        self.assertNotIn(ACCOUNT, json.dumps(current))
        self.assertEqual(json.loads((self.profile / "holdings.last_successful.json").read_text()), success)

    def test_two_account_workers_have_separate_clients_and_safe_progress(self):
        identities = [ACCOUNT, "synthetic-second-account"]
        discovery = SimpleNamespace(get_managed_accounts=lambda: [SimpleNamespace(account=value) for value in identities])
        barrier, clients, progress = threading.Barrier(2), [], []
        class Client:
            def get_positions(self, **kwargs):
                barrier.wait(timeout=3)
                self.raw_data = {"items": [item(account=kwargs["account"])]}
                return [object()]
        def factory():
            client = Client(); clients.append(client); return client
        result = app.fetch_all(discovery, self.profile, ("STK",), client_factory=factory, progress=progress.append)
        self.assertEqual(result["sourceReadStatus"], "complete")
        self.assertEqual(len({id(client) for client in clients}), 2)
        self.assertEqual([entry["completedAccounts"] for entry in progress], [0, 1, 2])
        self.assertEqual([entry["status"] for entry in progress], ["started", "complete", "complete"])
        self.assertTrue(all(len(account["positions"]) == 1 for account in result["accountResults"]))
        self.assertNotIn(ACCOUNT, json.dumps(progress))
        self.assertNotIn(identities[1], json.dumps(progress))

    def test_status_is_offline_and_generic_errors_do_not_leak(self):
        import urllib3
        output = StringIO()
        with patch("sys.argv", ["niulai_tiger.py", "--profile", str(self.profile), "status"]), patch.object(urllib3.PoolManager, "request", side_effect=AssertionError("network forbidden")), redirect_stdout(output):
            self.assertEqual(app.main(), 0)
        self.assertFalse(json.loads(output.getvalue())["tokenPresent"])
        output = StringIO()
        with patch("sys.argv", ["niulai_tiger.py", "--profile", str(self.profile), "status"]), patch.object(app, "sdk_classes", side_effect=ValueError("VERY_SECRET_TOKEN")), redirect_stdout(output):
            self.assertEqual(app.main(), 2)
        reported = json.loads(output.getvalue())
        self.assertEqual((reported["ok"], reported["error"]), (False, "TIGER_REQUEST_FAILED"))
        self.assertEqual(reported["diagnostic"]["exceptionType"], "ValueError")
        self.assertNotIn("VERY_SECRET_TOKEN", output.getvalue())

    def test_safe_diagnostic_exposes_only_bounded_codes_and_trace_locations(self):
        from tigeropen.common.exceptions import ApiException
        try:
            raise ApiException(Decimal(1000), "fake-secret-token " + ACCOUNT)
        except Exception as error:
            reported = app.safe_diagnostic(error)
        self.assertEqual((reported["exceptionType"], reported["providerCode"]), ("ApiException", 1000))
        self.assertNotIn(ACCOUNT, json.dumps(reported))
        self.assertNotIn("fake-secret-token", json.dumps(reported))
        self.assertTrue(all(set(frame) == {"function", "line"} for frame in reported["trace"]))
        for code in (Decimal("NaN"), Decimal("Infinity"), 123456789012, "123456789012", "fake-secret"):
            self.assertIsNone(app.safe_diagnostic(ApiException(code, "private"))["providerCode"])


if __name__ == "__main__":
    unittest.main()
