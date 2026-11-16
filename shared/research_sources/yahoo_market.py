"""Direct, secondary-only Yahoo market HTTP boundary with frozen routes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib import error, parse, request

CHART_HOST = "query1.finance.yahoo.com"
FUNDAMENTALS_HOST = "query2.finance.yahoo.com"
CHART_PREFIX = "/v8/finance/chart/"
FUNDAMENTALS_PREFIX = "/ws/fundamentals-timeseries/v1/finance/timeseries/"
MAX_BYTES = 4 * 1024 * 1024
MAX_SYMBOLS = 8
MAX_DAYS = 366
ALLOWED_INTERVALS = frozenset(("1d", "1wk"))
ALLOWED_TYPES = frozenset((
    "annualTotalRevenue", "annualNetIncome", "annualTotalAssets",
    "annualTotalLiabilitiesNetMinorityInterest", "annualStockholdersEquity",
    "annualOperatingCashFlow", "annualDilutedAverageShares", "annualBasicAverageShares",
    "trailingMarketCap", "trailingPeRatio", "trailingPriceToBook",
))
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")


class YahooMarketError(ValueError):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@dataclass(frozen=True)
class YahooRaw:
    provider: str
    secondary: bool
    route: str
    retrieved_at: str
    byte_count: int
    sha256: str
    payload: bytes
    headers: dict

    def private_record(self):
        return {"provider": self.provider, "secondary": self.secondary, "route": self.route,
                "retrieved_at": self.retrieved_at, "byte_count": self.byte_count,
                "sha256": self.sha256, "headers": self.headers,
                "payload": json.loads(self.payload)}


def _fail(condition, code):
    if not condition:
        raise YahooMarketError(code)


def _symbols(symbols):
    _fail(isinstance(symbols, list) and 1 <= len(symbols) <= MAX_SYMBOLS, "YAHOO_SYMBOLS_INVALID")
    _fail(all(isinstance(v, str) and _SYMBOL.fullmatch(v) for v in symbols), "YAHOO_SYMBOLS_INVALID")
    _fail(len(symbols) == len(set(symbols)), "YAHOO_SYMBOLS_DUPLICATE")
    return symbols


def _periods(period1, period2):
    _fail(type(period1) is int and type(period2) is int and 0 < period1 < period2, "YAHOO_PERIOD_INVALID")
    now = int(datetime.now(timezone.utc).timestamp())
    _fail(period2 <= now and period2 - period1 <= MAX_DAYS * 86400, "YAHOO_PERIOD_INVALID")


def _open_fixed(url, expected_host, expected_prefix, *, opener, timeout):
    parts = parse.urlsplit(url)
    _fail(parts.scheme == "https" and parts.hostname == expected_host and parts.port is None
          and not parts.username and not parts.password and parts.path.startswith(expected_prefix)
          and not parts.fragment, "YAHOO_ROUTE_REJECTED")
    req = request.Request(url, method="GET", headers={"Accept": "application/json", "User-Agent": "Niulai-Market-Pilot/1"})
    try:
        response = opener.open(req, timeout=timeout)
        with response:
            final = parse.urlsplit(response.geturl())
            _fail(final.scheme == "https" and final.hostname == expected_host and final.path == parts.path,
                  "YAHOO_REDIRECT_REJECTED")
            raw = response.read(MAX_BYTES + 1)
            _fail(len(raw) <= MAX_BYTES, "YAHOO_RESPONSE_TOO_LARGE")
            value = json.loads(raw)
            _fail(isinstance(value, dict), "YAHOO_RESPONSE_INVALID")
            safe_headers = {k.lower(): v for k, v in response.headers.items()
                            if k.lower() in ("content-type", "date", "etag", "last-modified")}
    except error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise YahooMarketError("YAHOO_REDIRECT_REJECTED") from None
        raise YahooMarketError("YAHOO_HTTP_ERROR") from None
    except (error.URLError, TimeoutError):
        raise YahooMarketError("YAHOO_NETWORK_ERROR") from None
    except (UnicodeError, json.JSONDecodeError):
        raise YahooMarketError("YAHOO_RESPONSE_INVALID") from None
    return YahooRaw("yahoo", True, parts.path, datetime.now(timezone.utc).isoformat(),
                    len(raw), hashlib.sha256(raw).hexdigest(), raw, safe_headers)


def fetch_chart(symbol, period1, period2, *, interval="1d", opener=None, timeout=20):
    _symbols([symbol]); _periods(period1, period2)
    _fail(interval in ALLOWED_INTERVALS, "YAHOO_INTERVAL_INVALID")
    query = parse.urlencode({"period1": period1, "period2": period2, "interval": interval,
                             "events": "div,splits", "includePrePost": "false"})
    url = f"https://{CHART_HOST}{CHART_PREFIX}{parse.quote(symbol, safe='')}?{query}"
    return _open_fixed(url, CHART_HOST, CHART_PREFIX, opener=opener or request.build_opener(NoRedirect()), timeout=timeout)


def fetch_fundamentals(symbols, types, period1, period2, *, opener=None, timeout=20):
    symbols = _symbols(symbols); _periods(period1, period2)
    _fail(isinstance(types, list) and types and len(types) == len(set(types))
          and all(v in ALLOWED_TYPES for v in types), "YAHOO_TYPE_REJECTED")
    path = FUNDAMENTALS_PREFIX + parse.quote(",".join(symbols), safe=",")
    query = parse.urlencode({"symbol": ",".join(symbols), "type": ",".join(types),
                             "period1": period1, "period2": period2})
    return _open_fixed(f"https://{FUNDAMENTALS_HOST}{path}?{query}", FUNDAMENTALS_HOST,
                       FUNDAMENTALS_PREFIX, opener=opener or request.build_opener(NoRedirect()), timeout=timeout)
