#!/usr/bin/env python3
"""Standalone read-only Tiger OAuth login/status/holdings. Requires tigeropen==3.8.0."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import traceback
import uuid

ISSUER = "https://openapi-oauth2.tigerfintech.com"
SCOPES = frozenset(("api.basic:read", "api.account:read", "api.trade:read"))
QUOTE_SCOPES = SCOPES | {"api.quote:read"}
SURFACE, CLIENT_NAME = "niulai-standalone", "Niulai Read Only Holdings"
DEFAULT_SECURITY_TYPES = ("STK", "OPT", "FUT")
SUPPORTED_SECURITY_TYPES = (*DEFAULT_SECURITY_TYPES, "FUND")


class ReadOnlyError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise ReadOnlyError(code)


def safe_error(error):
    return str(error) if isinstance(error, ReadOnlyError) else "TIGER_REQUEST_FAILED"


def safe_diagnostic(error):
    names = {"ReadOnlyError", "ApiException", "RequestException", "ResponseException", "OAuth2Exception", "TypeError", "AttributeError", "KeyError", "ValueError", "TimeoutError", "MaxRetryError", "SSLError", "ProtocolError"}
    code = getattr(error, "code", None)
    numeric_code = None
    try:
        if isinstance(code, (int, Decimal)) and not isinstance(code, bool) and code == int(code) and abs(code) <= 999999:
            numeric_code = int(code)
        elif isinstance(code, str) and re.fullmatch(r"-?\d{1,6}", code):
            numeric_code = int(code)
    except (ValueError, OverflowError):
        pass
    status = getattr(error, "status", None)
    return {"exceptionType": type(error).__name__ if type(error).__name__ in names else "Exception", "providerCode": numeric_code,
            "httpStatus": status if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599 else None,
            "trace": [{"function": frame.name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", frame.name) else "external", "line": frame.lineno}
                      for frame in traceback.extract_tb(error.__traceback__)[-6:]]}


def valid_ref(value):
    return isinstance(value, str) and len(value) == 32 and all(char in "0123456789abcdef" for char in value)


def amount(value):
    if value is None:
        return None
    require(not isinstance(value, bool), "INVALID_AMOUNT")
    try:
        number = Decimal(str(value))
        require(number.is_finite() and number.adjusted() <= 30 and number.as_tuple().exponent >= -18, "INVALID_AMOUNT")
    except (InvalidOperation, TypeError):
        raise ReadOnlyError("INVALID_AMOUNT") from None
    text = format(number, "f")
    return "0" if number == 0 else text.rstrip("0").rstrip(".") if "." in text else text


def write_private(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as stream:
        temporary = stream.name
        os.fchmod(stream.fileno(), 0o600)
        json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    os.replace(temporary, path)


def save_snapshot(path, result):
    path = Path(path)
    previous_success = path.with_name(path.stem + ".last_successful" + path.suffix)
    if not previous_success.exists() and path.exists():
        previous = None
        try:
            previous = json.loads(path.read_text())
        except ValueError:
            pass
        if isinstance(previous, dict) and previous.get("sourceReadStatus") == "complete":
            write_private(previous_success, previous)
    if result.get("sourceReadStatus") == "complete":
        write_private(previous_success, result)
    write_private(path, result)


@contextmanager
def snapshot_attempt(args):
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        yield
    except Exception as error:
        if args.command in ("fetch", "assets", "analytics", "transactions"):
            save_snapshot(args.out, {"schemaVersion": 1, "source": "Tiger OpenAPI", "sdkVersion": "3.8.0", "ok": False,
                "sourceReadStatus": "failed", "freshSourceResponse": False, "cachedFallbackUsed": False, "positions": None,
                "readAttemptAt": started, "readCompletedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "sourceSnapshotAt": None, "marketPriceAsOf": None, "error": safe_error(error), "diagnostic": safe_diagnostic(error)})
        raise


@contextmanager
def profile_lock(profile):
    require(not profile.is_symlink(), "PROFILE_SYMLINK_REJECTED")
    profile.mkdir(parents=True, mode=0o700, exist_ok=True)
    require(profile.stat().st_uid == os.getuid(), "PROFILE_OWNER_MISMATCH")
    profile.chmod(0o700)
    fd = os.open(profile / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReadOnlyError("PROFILE_BUSY") from None
        yield
    finally:
        os.close(fd)


def sdk_classes(include_transactions=False, include_quotes=False):
    requested_scopes = QUOTE_SCOPES if include_quotes else SCOPES
    import tigeropen
    import urllib3
    from tigeropen.auth.oauth2 import OAuth2Authentication, OAuth2SessionManager
    from tigeropen.auth.oauth2 import http_utils
    from tigeropen.common.util import web_utils
    from tigeropen.common.consts.service_types import ACCOUNTS, POSITIONS, ASSETS, PRIME_ASSETS, ANALYTICS_ASSET, ORDER_TRANSACTIONS, ORDERS
    from tigeropen.tiger_open_config import TigerOpenClientConfig
    from tigeropen.trade.trade_client import TradeClient
    require(tigeropen.__VERSION__ == "3.8.0", "SDK_VERSION_MISMATCH")
    timeout = urllib3.Timeout(connect=20, read=30, total=50)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    pool = urllib3.ProxyManager(proxy, cert_reqs="CERT_REQUIRED", timeout=timeout, retries=False) if proxy else urllib3.PoolManager(cert_reqs="CERT_REQUIRED", timeout=timeout, retries=False)
    http_utils._http_pool, http_utils._timeout, web_utils.http_pool = pool, timeout, pool

    class ReadSession(OAuth2SessionManager):
        def _scopes(self):
            metadata = self._metadata_of()
            require(not metadata.issuer or metadata.issuer.rstrip("/") == ISSUER, "ISSUER_MISMATCH")
            require(requested_scopes <= set(metadata.scopes_supported), "READ_SCOPES_UNAVAILABLE")
            for endpoint in (metadata.authorization_endpoint, metadata.token_endpoint, metadata.registration_endpoint, metadata.device_authorization_endpoint):
                require(not endpoint or endpoint.startswith(ISSUER + "/"), "OAUTH_ENDPOINT_MISMATCH")
            return " ".join(sorted(requested_scopes))

        def _persist(self, token):
            validate_token(token, require_quotes=include_quotes)
            super()._persist(token)
            if os.environ.get('NIULAI_PROFILE_SESSION_JSON'):
                from private_profile import checkpoint_from_environment
                checkpoint_from_environment(Path(self._store.home))

    class OAuthConfig(TigerOpenClientConfig):
        # Do not inherit unrelated RSA credentials, account IDs, props, or legacy tokens.
        def _load_env_vars(self): pass
        def _load_props(self): pass
        def load_token(self): return None

    class ReadClient(TradeClient):
        def _TigerOpenClient__prepare_request(self, request, url=""):
            # TradeClient.__fetch_data calls its base execute directly; guard here.
            require(request._method in ((ACCOUNTS, POSITIONS, ASSETS, PRIME_ASSETS, ANALYTICS_ASSET) + ((ORDER_TRANSACTIONS, ORDERS) if include_transactions else ())), "READ_ENDPOINT_ONLY")
            self._niulai_last_method = request._method
            return super()._TigerOpenClient__prepare_request(request, url)

        def _TigerOpenClient__parse_response(self, response_str, timestamp=None):
            # Preserve official response verification, then parse original numeric lexemes.
            super()._TigerOpenClient__parse_response(response_str, timestamp)
            response = json.loads(response_str, parse_float=Decimal, parse_int=Decimal)
            if isinstance(response.get("data"), str):
                response["data"] = json.loads(response["data"], parse_float=Decimal, parse_int=Decimal)
            self.raw_data = response.get("data")
            if getattr(self, "_niulai_last_method", None) == ANALYTICS_ASSET and isinstance(self.raw_data, dict):
                # Official SDK datetime conversion requires integer epochs; keep raw Decimal evidence untouched.
                response = {**response, "data": analytics_sdk_data(self.raw_data)}
            return response

    def client(session):
        config = OAuthConfig(enable_dynamic_domain=False)
        config.authentication = OAuth2Authentication(session)
        config.timeout, config.retry_max_tries = timeout, 0
        return ReadClient(config)
    return ReadSession, client


def validate_token(token, require_quotes=False):
    require(token is not None and token.issuer == ISSUER, "LOGIN_REQUIRED")
    granted = frozenset((token.scope or "").split())
    require(granted in (SCOPES, QUOTE_SCOPES), "TOKEN_SCOPE_REJECTED")
    require(not require_quotes or granted == QUOTE_SCOPES, "QUOTE_READ_CONSENT_REQUIRED")


def login_for_scopes(session, token, include_quotes, device, callback):
    """Explicit quote consent must not be skipped by a reusable base-scope token."""
    force = include_quotes and (token is None or 'api.quote:read' not in (token.scope or '').split())
    name = 'login_with_device_code' if device else 'login'
    method = getattr(session, name if force else name + '_if_needed')
    result = method(callback)
    validate_token(result, require_quotes=include_quotes)
    return result


def select_account(client, profile):
    accounts = client.get_managed_accounts()
    require(isinstance(accounts, list) and accounts, "ACCOUNT_LIST_UNAVAILABLE")
    identities = {item.account for item in accounts if isinstance(item.account, str) and item.account}
    require(len(identities) == len(accounts), "ACCOUNT_LIST_INVALID")
    pinfile = profile / "account-pin.json"
    require(not pinfile.is_symlink(), "ACCOUNT_PIN_SYMLINK_REJECTED")
    if pinfile.exists():
        pin = json.loads(pinfile.read_text())
        require(pin.get("account") in identities and valid_ref(pin.get("ref")), "ACCOUNT_PIN_MISMATCH")
    else:
        require(len(identities) == 1, "MULTIPLE_ACCOUNTS_REQUIRE_PRIVATE_SELECTION")
        pin = {"account": identities.pop(), "ref": uuid.uuid4().hex}
        write_private(pinfile, pin)
    return pin


def normalize_items(items, account):
    require(isinstance(items, list), "POSITIONS_ITEMS_MISSING")
    rows, seen = [], set()
    metadata = {"contractId": "contractId", "symbol": "symbol", "name": "name", "identifier": "identifier", "currency": "currency", "secType": "securityType", "market": "market", "exchange": "exchange", "localSymbol": "localSymbol", "expiry": "expiry", "right": "putCall", "updateTimestamp": "reportedUpdateTimestamp", "status": "reportedStatus"}
    numbers = {"positionQty": "quantity", "position": "reportedQuantity", "positionScale": "reportedQuantityScale", "averageCost": "averageCost", "latestPrice": "marketPrice", "marketValue": "marketValue", "unrealizedPnl": "unrealizedPnl", "multiplier": "multiplier", "strike": "strike", "lastClosePrice": "reportedLastClosePrice", "todayPnl": "reportedTodayPnl", "todayPnlPercent": "reportedTodayPnlPercent", "yesterdayPnl": "reportedYesterdayPnl", "realizedPnl": "reportedRealizedPnl"}
    for item in items:
        require(isinstance(item, dict) and item.get("account") == account, "POSITION_ACCOUNT_MISMATCH")
        row = {target: None if item.get(source) is None else str(item[source]) for source, target in metadata.items()}
        require(row["symbol"] and row["securityType"] and row["currency"], "INSTRUMENT_IDENTITY_MISSING")
        row.update({target: amount(item.get(source)) for source, target in numbers.items()})
        key = tuple(row[k] for k in ("contractId", "symbol", "securityType", "currency", "market", "expiry", "strike", "putCall", "localSymbol"))
        require(key not in seen, "DUPLICATE_POSITION")
        seen.add(key)
        row["quantitySource"] = "positionQty" if item.get("positionQty") is not None else "unknown; reportedQuantity retained without inferred scale"
        row["dailyPnlSemantics"] = "Raw provider todayPnl, if present; trading-session date and percent scale not independently supplied. Never substitute holding-period unrealized P&L."
        row["sourceObservedFieldNames"] = sorted(str(key) for key in item if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", str(key)))
        row["reportedUpdateTimestampSemantics"] = "Uninterpreted source field; not a verified market-price timestamp"
        rows.append(row)
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


def fetch(client, profile, security_types=DEFAULT_SECURITY_TYPES):
    pin = select_account(client, profile)
    return fetch_account(client, pin, security_types)


def fetch_account(client, pin, security_types=DEFAULT_SECURITY_TYPES):
    require(bool(security_types) and len(set(security_types)) == len(security_types) and all(value in SUPPORTED_SECURITY_TYPES for value in security_types), "SECURITY_TYPES_INVALID")
    attempted = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows, type_reads, seen = [], [], set()
    for security_type in security_types:
        started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            positions = client.get_positions(account=pin["account"], sec_type=security_type, currency="ALL", market="ALL")
            require(isinstance(positions, list), "POSITIONS_RESPONSE_MISSING")
            data = client.raw_data
            require(isinstance(data, dict) and isinstance(data.get("items"), list), "POSITIONS_ITEMS_MISSING")
            require(not any(data.get(key) for key in ("nextCursor", "nextPageToken", "nextToken", "nextPage", "hasMore", "hasNext", "partial", "truncated")), "PAGINATION_OR_PARTIAL_RESPONSE")
            subset = normalize_items(data["items"], pin["account"])
            require(len(subset) == len(positions), "SDK_ROW_COUNT_MISMATCH")
            require(all(row["securityType"] == security_type for row in subset), "SECURITY_TYPE_RESPONSE_MISMATCH")
            for key in ("total", "totalCount", "count"):
                require(key not in data or data[key] == len(subset), "SOURCE_ROW_COUNT_MISMATCH")
            keys = {tuple(row[key] for key in ("contractId", "symbol", "securityType", "currency", "market", "expiry", "strike", "putCall", "localSymbol")) for row in subset}
            require(not seen.intersection(keys), "DUPLICATE_POSITION_ACROSS_TYPES")
            seen.update(keys); rows.extend(subset)
            reading = {"securityType": security_type, "ok": True, "positionCount": len(subset)}
        except Exception as error:
            reading = {"securityType": security_type, "ok": False, "positionCount": None, "error": safe_error(error), "diagnostic": safe_diagnostic(error)}
        reading.update(queryAttemptAt=started, queryCompletedAt=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        type_reads.append(reading)
    succeeded = [read["securityType"] for read in type_reads if read["ok"]]
    failed = [read["securityType"] for read in type_reads if not read["ok"]]
    state = "complete" if not failed else "partial" if succeeded else "failed"
    return {"schemaVersion": 1, "source": "Tiger OpenAPI", "sdkVersion": "3.8.0", "accountRef": pin["ref"], "accountIdentityChecked": True,
            "queryAttemptAt": attempted, "queryCompletedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "sourceSnapshotAt": None, "marketPriceAsOf": None,
            "ok": bool(succeeded), "sourceReadStatus": state, "typeReads": type_reads,
            "error": None if succeeded else "ALL_REQUESTED_SECURITY_TYPES_FAILED",
            "freshSourceResponse": bool(succeeded), "cachedFallbackUsed": False, "scopes": sorted(SCOPES), "scopeEvidence": "SDK state; scope may fall back to requested scopes if omitted by provider",
            "coverage": {"requestedSecurityTypes": list(security_types), "successfulSecurityTypes": succeeded, "failedSecurityTypes": failed, "requestedMarket": "ALL", "requestedCurrency": "ALL", "positionCount": len(rows) if succeeded else None, "wholePortfolioVerified": False, "paginationCompletenessVerified": False, "cashBalance": None, "nav": None},
            "amountEncoding": "decimal strings; null means unknown; monetary amounts use each row currency; no P&L or multiplier guesses", "positions": sorted(rows, key=lambda row: json.dumps(row, sort_keys=True)) if succeeded else None}


def account_refs(profile, accounts):
    """Initialize stable private references from observed accounts, including first login."""
    require(isinstance(accounts, list) and accounts, "ACCOUNT_LIST_UNAVAILABLE")
    identities = [getattr(account, "account", None) for account in accounts]
    require(all(isinstance(value, str) and value for value in identities) and len(set(identities)) == len(identities), "ACCOUNT_LIST_INVALID")
    path = profile / "account-refs.json"
    require(not path.is_symlink(), "ACCOUNT_REFS_SYMLINK_REJECTED")
    refs = json.loads(path.read_text()) if path.exists() else {}
    require(isinstance(refs, dict) and all(valid_ref(value) for value in refs.values()) and len(set(refs.values())) == len(refs), "ACCOUNT_REFS_INVALID")
    for identity in identities:
        refs.setdefault(identity, uuid.uuid4().hex)
    write_private(path, refs)
    return refs


def fetch_all(client, profile, security_types=DEFAULT_SECURITY_TYPES, client_factory=None, progress=None, account_reader=None):
    accounts = client.get_managed_accounts()
    refs = account_refs(profile, accounts)
    completed, progress_lock = 0, threading.Lock()
    def report(status):
        nonlocal completed
        with progress_lock:
            completed += status != "started"
            if progress:
                try:
                    progress({"completedAccounts": completed, "totalAccounts": len(accounts), "status": status})
                except Exception:
                    pass
    report("started")
    def read_account(account):
        try:
            worker_client = client_factory() if client_factory else client
            result = (account_reader or fetch_account)(worker_client, {"account": account.account, "ref": refs[account.account]}, security_types)
        except Exception as error:
            result = {"ok": False, "accountRef": refs[account.account], "error": safe_error(error), "diagnostic": safe_diagnostic(error), "positions": None}
        result["sourceAccountMetadata"] = {key: None if getattr(account, key, None) is None else str(getattr(account, key)) for key in ("account_type", "status", "capability")}
        report(result.get("sourceReadStatus", "failed"))
        return result
    if client_factory:
        with ThreadPoolExecutor(max_workers=min(2, len(accounts))) as executor:
            results = list(executor.map(read_account, accounts))
    else:
        results = [read_account(account) for account in accounts]
    failed = sum(not result["ok"] for result in results)
    partial = sum(result.get("sourceReadStatus") == "partial" for result in results)
    return {"schemaVersion": 1, "source": "Tiger OpenAPI", "sdkVersion": "3.8.0", "allAccounts": True,
            "sourceReadStatus": "complete" if failed == 0 and partial == 0 else "failed" if failed == len(results) else "partial",
            "accountCount": len(results), "successfulAccountCount": len(results) - failed, "failedAccountCount": failed, "partialAccountCount": partial,
            "accountResults": results, "aggregationPerformed": False, "wholePortfolioVerified": False}



ASSET_FIELDS = {
    "netLiquidation": "netLiquidation", "grossPositionValue": "grossPositionValue",
    "stockMarketValue": "stockMarketValue", "optionMarketValue": "optionMarketValue", "futuresMarketValue": "futuresMarketValue",
    "cashValue": "cash", "cashBalance": "cash", "cash": "cash", "settledCash": "settledCash",
    "buyingPower": "buyingPower", "equityWithLoan": "equityWithLoan", "availableFunds": "availableFunds",
    "leverage": "reportedLeverage", "netLeverage": "reportedNetLeverage",
    "initMarginReq": "initialMargin", "initMargin": "initialMargin", "maintMarginReq": "maintenanceMargin", "maintainMargin": "maintenanceMargin",
    "excessLiquidity": "excessLiquidity", "excessLiquidation": "excessLiquidity", "cashAvailableForTrade": "cashAvailableForTrade",
    "totalTodayPL": "reportedTodayPnl", "realizedPL": "reportedRealizedPnl", "unrealizedPL": "reportedUnrealizedPnl", "totalTodayPnl": "reportedTodayPnl", "totalTodayPl": "reportedTodayPnl", "todayPnl": "reportedTodayPnl", "realizedPnL": "reportedRealizedPnl", "realizedPnl": "reportedRealizedPnl", "realizedPl": "reportedRealizedPnl", "unrealizedPnL": "reportedUnrealizedPnl", "unrealizedPnl": "reportedUnrealizedPnl", "unrealizedPl": "reportedUnrealizedPnl",
    "loanValue": "reportedLoanValue", "accruedCash": "accruedCash", "accruedDividend": "accruedDividend",
}


def normalize_asset_block(item, currency=None, category=None):
    require(isinstance(item, dict), "ASSET_BLOCK_INVALID")
    result = {"currency": item.get("currency", currency), "category": item.get("category", category),
              "reportedUpdateTime": str(item.get("updateTime", item.get("updateTimestamp"))) if item.get("updateTime", item.get("updateTimestamp")) is not None else None,
              "amounts": {target: None for target in set(ASSET_FIELDS.values())}, "sourceFields": {}, "invalidFields": [],
              "sourceObservedFieldNames": sorted(str(key) for key in item if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", str(key))), "sourceNumericFields": {}}
    for key, value in item.items():
        if key in set(ASSET_FIELDS) | {"lockedFunds", "uncollected", "overnightMargin", "overnightLiquidation", "unrealizedPLByCostOfCarry", "updateTimestamp", "updateTime"} and isinstance(value, (Decimal, int, float)) and not isinstance(value, bool):
            try:
                result["sourceNumericFields"][key] = amount(value)
            except ReadOnlyError:
                pass
    for source, target in ASSET_FIELDS.items():
        if source not in item or item[source] is None:
            continue
        try:
            value = amount(item[source])
        except ReadOnlyError:
            result["invalidFields"].append(source)
            continue
        require(result["amounts"][target] in (None, value), "CONFLICTING_ASSET_ALIASES")
        result["amounts"][target] = value
        result["sourceFields"][target] = source
    return result


def asset_blocks(value):
    require(isinstance(value, (dict, list)), "ASSET_GROUPS_INVALID")
    if isinstance(value, list):
        return [(None, item) for item in value]
    return list(value.items())


def normalize_assets(data, account, endpoint):
    require(isinstance(data, dict), "ASSETS_RESPONSE_MISSING")
    require(not any(data.get(key) for key in ("hasMore", "partial", "truncated", "nextCursor")), "ASSET_PARTIAL_RESPONSE")
    if endpoint == "assets":
        items = data.get("items")
        require(isinstance(items, list) and len(items) == 1, "ASSET_ACCOUNT_COUNT_MISMATCH")
        item = items[0]
        require(item.get("account") == account, "ASSET_ACCOUNT_MISMATCH")
        summary = normalize_asset_block(item)
        segments = [normalize_asset_block(v, category=k) for k, v in asset_blocks(item.get("segments", []))]
        currencies = [normalize_asset_block(v, currency=k) for k, v in asset_blocks(item.get("marketValues", []))]
    else:
        require(data.get("accountId") == account, "ASSET_ACCOUNT_MISMATCH")
        summary = None
        segments, currencies = [], []
        for key, block in asset_blocks(data.get("segments", [])):
            segment = normalize_asset_block(block, category=key)
            segments.append(segment)
            for currency, value in asset_blocks(block.get("currencyAssets", [])):
                currencies.append(normalize_asset_block(value, currency=currency, category=segment["category"]))
    require(summary is not None or segments, "ASSET_VALUES_MISSING")
    return {"summary": summary, "segments": segments, "currencyAssets": currencies,
            "sourceUpdateTime": str(data.get("updateTimestamp")) if data.get("updateTimestamp") is not None else None,
            "assetFieldSemantics": "Official SDK 3.8.0 asset mappings; source fields retained. Buying power is not cash. No cross-currency or cross-segment aggregation."}


def fetch_assets_account(client, pin, security_types=None, prefer_prime=False):
    attempts = []
    for endpoint in (("prime_assets", "assets") if prefer_prime else ("assets", "prime_assets")):
        started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            result = client.get_assets(account=pin["account"], segment=True, market_value=True) if endpoint == "assets" else client.get_prime_assets(account=pin["account"], base_currency="USD", consolidated=True)
            require(result is not None, "ASSETS_RESPONSE_MISSING")
            normalized = normalize_assets(client.raw_data, pin["account"], endpoint)
            attempts.append({"endpoint": endpoint, "ok": True, "queryAttemptAt": started, "queryCompletedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
            return {"accountRef": pin["ref"], "accountIdentityChecked": True, "ok": True, "sourceReadStatus": "complete", "endpoint": endpoint,
                    "queryAttemptAt": attempts[0]["queryAttemptAt"], "queryCompletedAt": attempts[-1]["queryCompletedAt"], "attempts": attempts, **normalized}
        except Exception as error:
            diagnostic = safe_diagnostic(error)
            attempts.append({"endpoint": endpoint, "ok": False, "queryAttemptAt": started, "queryCompletedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "error": safe_error(error), "diagnostic": diagnostic})
            # A different read-only account endpoint is a bounded compatibility fallback, not a refresh/retry loop.
            if diagnostic["exceptionType"] != "ApiException" or diagnostic["providerCode"] not in (1010,):
                break
    return {"accountRef": pin["ref"], "ok": False, "sourceReadStatus": "failed", "summary": None, "segments": [], "currencyAssets": [], "attempts": attempts,
            "queryAttemptAt": attempts[0]["queryAttemptAt"], "queryCompletedAt": attempts[-1]["queryCompletedAt"], "error": "ASSETS_UNAVAILABLE"}




def analytics_sdk_data(data):
    if not isinstance(data.get("history"), list):
        return data
    history = []
    for row in data["history"]:
        timestamp = row.get("date")
        require(isinstance(timestamp, (int, Decimal)) and not isinstance(timestamp, bool) and timestamp == int(timestamp), "ANALYTICS_DATE_INVALID")
        history.append({**row, "date": int(timestamp)})
    return {**data, "history": history}


def fetch_analytics_account(client, pin, start_date, end_date, currency="USD"):
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    base = {"accountRef": pin["ref"], "endpoint": "analytics_asset", "currency": currency, "segment": "SEC",
            "startDate": start_date, "endDate": end_date, "queryAttemptAt": started, "pnlSemanticsVerified": False,
            "pnlLimitation": "Official description says versus previous day, but published example is cumulative versus start; raw history pnl is not certified daily P&L. No current-position attribution implied."}
    try:
        result = client.get_analytics_asset(account=pin["account"], start_date=start_date, end_date=end_date, seg_type="SEC", currency=currency)
        require(result is not None and isinstance(client.raw_data, dict), "ANALYTICS_RESPONSE_MISSING")
        data = client.raw_data
        history = data.get("history")
        require(isinstance(history, list), "ANALYTICS_HISTORY_MISSING")
        fields = ("pnl", "pnlPercentage", "annualizedReturn", "overUserPercentage", "asset", "cashBalance", "grossPositionValue", "deposit", "withdrawal")
        def normalize(block):
            require(isinstance(block, dict), "ANALYTICS_BLOCK_INVALID")
            return {key: amount(block.get(key)) for key in fields}
        rows = []
        for item in history:
            row = normalize(item)
            row["dateEpochMs"] = amount(item.get("date"))
            rows.append(row)
        return {**base, "ok": True, "sourceReadStatus": "complete", "history": rows, "summary": normalize(data.get("summary", {})),
                "queryCompletedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    except Exception as error:
        return {**base, "ok": False, "sourceReadStatus": "failed", "history": None, "summary": None, "error": safe_error(error), "diagnostic": safe_diagnostic(error),
                "queryCompletedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}


def fetch_transaction_window(client, pin, start_ms, end_ms, sec_type="STK", max_pages=3):
    """Correct supported read shape: explicit security type and UTC epoch bounds."""
    import hashlib
    require(all(isinstance(v,int) and not isinstance(v,bool) for v in (start_ms,end_ms,max_pages)), "TRANSACTION_WINDOW_INVALID")
    require(0 < start_ms < end_ms and end_ms-start_ms <= 90*86400000 and 1<=max_pages<=5 and sec_type == "STK", "TRANSACTION_WINDOW_INVALID")
    output={"accountRef":pin["ref"],"endpoint":"order_transactions","startEpochMs":start_ms,"endEpochMs":end_ms,"securityType":sec_type,"queryAttemptAt":datetime.now(timezone.utc).isoformat(),"transactions":[],"pagesRead":0,"paginationComplete":False}
    token=""; seen_ids=set();seen_tokens=set()
    try:
        for _ in range(max_pages):
            client.get_transactions(account=pin["account"],sec_type=sec_type,start_time=start_ms,end_time=end_ms,limit=100,page_token=token)
            raw=client.raw_data
            require(isinstance(raw,dict) and isinstance(raw.get("items"),list),"TRANSACTION_ITEMS_MISSING")
            for item in raw['items']:
                require(str(item.get('accountId'))==pin['account'] and item.get('secType')==sec_type,"TRANSACTION_ACCOUNT_OR_TYPE_MISMATCH")
                require(item.get('id') is not None and item.get('symbol') and item.get('currency'),"TRANSACTION_IDENTITY_MISSING")
                identity=hashlib.sha256((pin['ref']+':'+str(item['id'])).encode()).hexdigest()
                require(identity not in seen_ids,"DUPLICATE_EXECUTION")
                quantity=Decimal(amount(item.get('filledQuantity')));scale=Decimal(amount(item.get('filledQuantityScale')))
                require(quantity==quantity.to_integral_value() and scale==scale.to_integral_value() and 0<=scale<=12 and quantity>0,"EXECUTION_QUANTITY_INVALID")
                quantity=quantity.scaleb(-int(scale));price=Decimal(amount(item.get('filledPrice')));stamp=Decimal(amount(item.get('transactionTime')))
                require(price>=0 and stamp==stamp.to_integral_value() and start_ms<=stamp<=end_ms,"EXECUTION_TIME_OR_PRICE_INVALID")
                value=Decimal(amount(item.get('filledAmount')))
                require(abs(quantity*price-value)<=Decimal('0.01') and item.get('action') in ('BUY','SELL'),"EXECUTION_VALUE_OR_SIDE_INVALID")
                output['transactions'].append({'executionIdHash':identity,'symbol':item['symbol'],'securityType':sec_type,'currency':item['currency'],'side':item['action'],
                    'quantity':amount(quantity),'rawQuantity':amount(item['filledQuantity']),'quantityScale':int(scale),'price':amount(price),'grossAmount':amount(value),
                    'executionEpochMs':int(stamp),'executionTimeUtc':datetime.fromtimestamp(int(stamp)/1000,timezone.utc).isoformat(),
                    'providerLocalTime':item.get('transactedAt'),'providerLocalTimeTimezone':None,'fee':None,
                    'sourceFields':sorted(item)})
                seen_ids.add(identity)
            output['pagesRead']+=1
            token=raw.get('nextPageToken')
            if not token:
                output['paginationComplete']=len(raw['items'])<100
                if not output['paginationComplete']:output['paginationLimitation']='full_page_without_exhaustion_token'
                break
            require(isinstance(token,str) and token not in seen_tokens,"TRANSACTION_PAGINATION_LOOP")
            seen_tokens.add(token)
        output.update(ok=output['paginationComplete'],sourceReadStatus='complete' if output['paginationComplete'] else 'partial',error=None if output['paginationComplete'] else 'TRANSACTION_PAGE_BUDGET_EXHAUSTED')
    except Exception as e:
        output.update(ok=False,sourceReadStatus='partial' if output['transactions'] else 'failed',error=safe_error(e),diagnostic=safe_diagnostic(e))
    output['queryCompletedAt']=datetime.now(timezone.utc).isoformat()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True, help="private mounted/persistent secret directory")
    sub = parser.add_subparsers(dest="command", required=True)
    login = sub.add_parser("login"); login.add_argument("--device", action="store_true"); login.add_argument("--include-quotes", action="store_true", help="explicitly request additional read-only market data consent")
    sub.add_parser("status")
    fetch_parser = sub.add_parser("fetch")
    fetch_parser.add_argument("--out", type=Path, required=True)
    fetch_parser.add_argument("--all-accounts", action="store_true", help="query each authorized account separately; never merge positions")
    fetch_parser.add_argument("--security-types", nargs="+", choices=SUPPORTED_SECURITY_TYPES, default=DEFAULT_SECURITY_TYPES, help="explicit types; defaults STK OPT FUT; ALL is not supported by this gateway")
    asset_parser = sub.add_parser("assets", help="read authorized account cash/NAV, separately from positions")
    asset_parser.add_argument("--out", type=Path, required=True)
    asset_parser.add_argument("--prime", action="store_true", help="prefer official Prime/Standard/Paper asset endpoint")
    asset_parser.set_defaults(all_accounts=True, security_types=DEFAULT_SECURITY_TYPES)
    analytics_parser = sub.add_parser("analytics", help="read raw historical account analytics; no inferred daily attribution")
    analytics_parser.add_argument("--out", type=Path, required=True)
    analytics_parser.add_argument("--start-date", required=True)
    analytics_parser.add_argument("--end-date", required=True)
    analytics_parser.add_argument("--currency", choices=("USD", "HKD", "CNH"), default="USD")
    analytics_parser.set_defaults(all_accounts=True, security_types=DEFAULT_SECURITY_TYPES)
    tx_parser = sub.add_parser("transactions", help="read execution window; no orders are submitted")
    tx_parser.add_argument("--out", type=Path, required=True)
    tx_parser.add_argument("--start-ms",type=int,required=True)
    tx_parser.add_argument("--end-ms",type=int,required=True)
    tx_parser.add_argument("--sec-type",choices=("STK",),default="STK")
    tx_parser.set_defaults(all_accounts=True,security_types=DEFAULT_SECURITY_TYPES)
    args = parser.parse_args()
    if args.command == "analytics":
        datetime.strptime(args.start_date, "%Y-%m-%d"); datetime.strptime(args.end_date, "%Y-%m-%d")
        require(args.start_date <= args.end_date, "ANALYTICS_DATE_RANGE_INVALID")
    logging.disable(logging.CRITICAL)  # SDK errors can otherwise include account payloads.
    try:
        with profile_lock(args.profile), snapshot_attempt(args):
            Session, make_client = sdk_classes(include_transactions=args.command == "transactions", include_quotes=getattr(args,"include_quotes",False))
            session = Session(issuer=ISSUER, home=str(args.profile), surface=SURFACE, client_name=CLIENT_NAME)
            token = session.status()
            if token is not None:
                validate_token(token)
            if args.command == "login":
                print("Check the official page: Niulai Read Only Holdings, your intended account, and read permissions only. Decline write/trading authority.", flush=True)
                if args.device:
                    token = login_for_scopes(session, token, args.include_quotes, True, lambda device: print(json.dumps({"verificationUri": device.verification_uri, "verificationUriComplete": device.verification_uri_complete, "userCode": device.user_code, "expiresInSeconds": device.expires_in}), flush=True))
                else:
                    token = login_for_scopes(session, token, args.include_quotes, False, lambda url: print(url, flush=True))
                validate_token(token)
            if args.command in ("fetch", "assets", "analytics", "transactions"):
                validate_token(token)
                result = fetch_all(make_client(session), args.profile, args.security_types, client_factory=lambda: make_client(session), progress=lambda report: print(json.dumps({"progress": report}), flush=True), account_reader=(lambda c, p, _: fetch_transaction_window(c,p,args.start_ms,args.end_ms,args.sec_type)) if args.command == "transactions" else (lambda c, p, t: fetch_assets_account(c, p, t, prefer_prime=args.prime)) if args.command == "assets" else (lambda c, p, _: fetch_analytics_account(c, p, args.start_date, args.end_date, args.currency)) if args.command == "analytics" else None) if args.all_accounts else fetch(make_client(session), args.profile, args.security_types)
                validate_token(session.status())  # Also reject a broadened refresh grant.
                save_snapshot(args.out, result)
                if args.all_accounts:
                    print(json.dumps({"ok": result["sourceReadStatus"] == "complete", "sourceReadStatus": result["sourceReadStatus"], "accountCount": result["accountCount"], "successfulAccountCount": result["successfulAccountCount"], "failedAccountCount": result["failedAccountCount"], "partialAccountCount": result["partialAccountCount"], "aggregationPerformed": False}))
                    if result["sourceReadStatus"] != "complete":
                        return 2
                else:
                    print(json.dumps({"ok": result["sourceReadStatus"] == "complete", "sourceReadStatus": result["sourceReadStatus"], "positionCount": result["coverage"]["positionCount"], "queryCompletedAt": result["queryCompletedAt"], "freshSourceResponse": result["freshSourceResponse"]}))
                    if result["sourceReadStatus"] != "complete":
                        return 2
            else:
                print(json.dumps({"ok": True, "tokenPresent": token is not None, "usableWithoutRefresh": bool(token and token.remaining_millis() > 30000), "scopes": sorted((token.scope or "").split()) if token else [], "scopeAndExpiryEvidence": "SDK state; omitted provider scope/expires_in may use SDK request/default fallbacks"}))
    except Exception as error:
        print(json.dumps({"ok": False, "error": safe_error(error), "diagnostic": safe_diagnostic(error)}), flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
