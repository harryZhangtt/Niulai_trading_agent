"""Fixed-schema Tiger SDK 3.8 market reads; raw values remain private."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json

RAW_FILE = "market_raw.json"
MANIFEST_FILE = "market_manifest.json"
QUERY_FILE = "market_query.json"
MARKET_FILES = (RAW_FILE, MANIFEST_FILE, QUERY_FILE)


def _jsonable(value):
    if hasattr(value, "to_dict"):
        try:
            value = value.to_dict(orient="records")
        except TypeError:
            value = value.to_dict()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # Provider objects may expose numpy scalar conversion. Never stringify an
    # arbitrary object because its repr can carry request or credential state.
    item = getattr(value, "item", None)
    if callable(item):
        return _jsonable(item())
    raise TypeError("TIGER_MARKET_RESPONSE_INVALID")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _count(value):
    return len(value) if isinstance(value, list) else 0


def execute_market_query(n, profile, query, require, write_json, out):
    """Execute only the explicit quote-method allowlist under the existing lease."""
    args = query["arguments"]
    symbols = [record["symbol"] for record in args["symbols"]]
    started = datetime.now(timezone.utc).isoformat()
    with n.profile_lock(profile):
        Session, make_quote = n.quote_sdk_classes()
        sdk = Session(issuer=n.ISSUER, home=str(profile), surface=n.SURFACE, client_name=n.CLIENT_NAME)
        n.validate_token(sdk.status(), require_quotes=True)
        quote = make_quote(sdk)
        begin, end = args["corporate_action_start"], args["as_of"][:10]
        fields = args["fields"]
        raw = {
            "briefs": _jsonable(quote.get_stock_briefs(symbols, include_hour_trading=False, sec_type="STK")),
            "stock_fundamental": _jsonable(quote.get_stock_fundamental(symbols, "US", sec_type="STK")),
            "financial_daily": _jsonable(quote.get_financial_daily(symbols, "US", fields["financial_daily"], begin, end)),
            "financial_report": _jsonable(quote.get_financial_report(symbols, "US", fields["financial_report"], "ANNUAL", begin, end)),
            "financial_currency": _jsonable(quote.get_financial_currency(symbols, "US")),
            "financial_exchange_rate": _jsonable(quote.get_financial_exchange_rate(args["fx_currencies"], begin, end)),
        }
        actions = {
            "split": "get_corporate_split",
            "dividend": "get_corporate_dividend",
            "symbol_change": "get_corporate_symbol_change",
            "delisting": "get_corporate_delisting",
        }
        for action in args["corporate_actions"]:
            raw["corporate_" + action] = _jsonable(getattr(quote, actions[action])(symbols, "US", begin, end))

        # Only these private files contain provider values or sampled identities.
        write_json(out / RAW_FILE, raw)
        hashes = {name: hashlib.sha256(_canonical(value)).hexdigest() for name, value in raw.items()}
        counts = {name: _count(value) for name, value in raw.items()}
        manifest = {
            "schema_version": 1, "provider": "tiger", "sdk_version": "3.8.0",
            "request": args, "response_sha256": hashes, "response_counts": counts,
            "started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(),
            "provider_attempts": 1, "secondary": False,
        }
        write_json(out / MANIFEST_FILE, manifest)
        write_json(out / QUERY_FILE, {"schema_version": 1, "tool": "market_snapshot", "manifest": manifest})

    return {
        "status": "queried", "tool": "market_snapshot", "source_read_status": "complete",
        "symbols_count": len(symbols), "method_counts": counts,
        "response_sha256": hashes, "files": list(MARKET_FILES),
        "authorization_id": args["authorization_id"],
        "authorization_sha256": args["authorization_sha256"],
        "authorization_status": "consumed",
    }
