#!/usr/bin/env python3
"""Public Yahoo chart snapshots for a weekly *screen*, with explicit coverage.

No provider data is a substitute for primary business evidence. Adjusted closes
are a provider's backward-adjusted series; raw bytes and their hash are retained.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

UTC = timezone.utc
NY = ZoneInfo("America/New_York")


class ValidationError(ValueError):
    pass


@lru_cache(maxsize=1)
def session_calendar():
    import exchange_calendars
    return exchange_calendars.get_calendar("XNYS")


def finite_positive(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field}: expected positive finite number")
    if not math.isfinite(value) or value <= 0:
        raise ValidationError(f"{field}: expected positive finite number")
    return float(value)


def parse_chart(payload, symbol, required_endpoints=(), as_of_utc=None):
    """Reject unverified currency/timezone, malformed/duplicate daily series.

    Null market observations are retained as explicit missing observations.
    Missing required endpoints fail this security, rather than substitute nearby
    dates. Caller records that security in coverage errors and keeps raw bytes.
    """
    try:
        chart = payload["chart"]
        if chart.get("error"):
            raise ValidationError(f"provider_error: {chart['error']}")
        results = chart["result"]
        if not isinstance(results, list) or len(results) != 1:
            raise ValidationError("expected exactly one chart result")
        result = results[0]
        meta = result["meta"]
        if meta.get("symbol", "").upper() != symbol.upper():
            raise ValidationError("provider symbol does not match requested symbol")
        if meta.get("currency") != "USD":
            raise ValidationError("currency must be USD")
        if meta.get("exchangeTimezoneName") != "America/New_York":
            raise ValidationError("exchangeTimezoneName must be America/New_York")
        stamps = result["timestamp"]
        quotes = result["indicators"]["quote"]
        adjusted = result["indicators"]["adjclose"]
        if not isinstance(stamps, list) or not stamps:
            raise ValidationError("empty timestamps")
        if len(quotes) != 1 or len(adjusted) != 1:
            raise ValidationError("expected one quote and adjusted-close series")
        closes = quotes[0]["close"]
        adjcloses = adjusted[0]["adjclose"]
        if not isinstance(closes, list) or not isinstance(adjcloses, list):
            raise ValidationError("close and adjusted-close must be arrays")
        if len(stamps) != len(closes) or len(stamps) != len(adjcloses):
            raise ValidationError("timestamp/close/adjusted-close array length mismatch")
        observations, missing, dates_seen = [], [], set()
        last_stamp = None
        for stamp, close, adj in zip(stamps, closes, adjcloses):
            if isinstance(stamp, bool) or not isinstance(stamp, int):
                raise ValidationError("timestamp must be integer epoch seconds")
            if last_stamp is not None and stamp <= last_stamp:
                raise ValidationError("timestamps must be strictly increasing")
            last_stamp = stamp
            instant = datetime.fromtimestamp(stamp, UTC)
            if as_of_utc and instant > as_of_utc:
                raise ValidationError("future observation timestamp")
            session = instant.astimezone(NY).date()
            if session.weekday() > 4:
                raise ValidationError("weekend session timestamp")
            iso_session = session.isoformat()
            if not session_calendar().is_session(iso_session):
                raise ValidationError("observation date is not an XNYS trading session")
            if iso_session in dates_seen:
                raise ValidationError("duplicate session date")
            dates_seen.add(iso_session)
            if close is None or adj is None:
                missing.append({"session_date": iso_session, "reason": "null_close_or_adjusted_close"})
                continue
            observations.append({
                "timestamp": stamp,
                "timestamp_utc": instant.isoformat().replace("+00:00", "Z"),
                "session_date": iso_session,
                "close": finite_positive(close, "close"),
                "adjusted_close": finite_positive(adj, "adjusted_close"),
            })
        valid_dates = {row["session_date"] for row in observations}
        absent = sorted(set(required_endpoints) - valid_dates)
        if absent:
            raise ValidationError(f"missing required valid endpoint(s): {','.join(absent)}")
        return {
            "ticker": symbol.upper(), "symbol": symbol.upper(),
            "currency": "USD", "exchange_timezone": "America/New_York",
            "observations": observations, "missing_observations": missing,
            "provider_metadata": {k: meta.get(k) for k in (
                "exchangeName", "fullExchangeName", "instrumentType", "dataGranularity")},
        }
    except (KeyError, TypeError, IndexError, OverflowError, OSError, AttributeError) as exc:
        raise ValidationError(f"malformed provider payload: {type(exc).__name__}: {exc}") from exc


def fetch_one(symbol, output_dir, start, end, required_endpoints, as_of_utc, timeout=15):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe="") + "?" + urlencode({
        "period1": int(start.timestamp()), "period2": int(end.timestamp()),
        "interval": "1d", "events": "div,splits", "includeAdjustedClose": "true",
    })
    attempts = []
    for attempt in range(1, 3):
        started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 Niulai-research-screener/1.0"})
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                http_status = response.status
            retrieved = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            filename = symbol + ".json"
            (output_dir / filename).write_bytes(raw)
            ledger = {
                "ticker": symbol, "url": url, "request_started_at_utc": started,
                "retrieved_at_utc": retrieved,
                "http_status": http_status, "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "raw_file": filename, "attempt": attempt,
            }
            attempts.append(ledger)
            try:
                parsed = parse_chart(json.loads(raw), symbol, required_endpoints, as_of_utc)
            except (ValidationError, json.JSONDecodeError) as exc:
                return None, attempts, {"ticker": symbol, "stage": "validation", "error": str(exc)}
            parsed["source"] = ledger
            return parsed, attempts, None
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            retryable = not isinstance(exc, HTTPError) or exc.code in (408, 429) or exc.code >= 500
            attempts.append({"ticker": symbol, "url": url, "request_started_at_utc": started,
                             "failed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                             "attempt": attempt, "error": f"{type(exc).__name__}: {exc}"})
            if attempt == 2 or not retryable:
                return None, attempts, {"ticker": symbol, "stage": "retrieval", "error": attempts[-1]["error"]}
    raise AssertionError("bounded retry loop exhausted")


def engine_observations(rows):
    """Flat, explicitly adjusted observations consumed by weekly_scan.rank_week."""
    result = []
    for row in rows:
        source = row["source"]
        for observation in row["observations"]:
            result.append({
                "symbol": row["symbol"], "session": observation["session_date"],
                "adjusted_close": str(observation["adjusted_close"]),
                "currency": row["currency"], "price_unit": "currency_per_share",
                "adjustment_basis": "split_and_dividend_adjusted_total_return",
                "adjustment_snapshot": "Yahoo-chart:sha256:" + source["sha256"],
                "source": "Yahoo chart", "source_url": source["url"],
                "observed_at": source["retrieved_at_utc"],
            })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--endpoint", action="append", default=[])
    parser.add_argument("--days", type=int, default=25)
    args = parser.parse_args()
    if args.days < 14 or args.days > 90:
        parser.error("--days must be between14 and90")
    for endpoint in args.endpoint:
        date.fromisoformat(endpoint)
    universe = json.loads(args.universe.read_text())["securities"]
    symbols = [row["symbol"].upper() for row in universe]
    if len(symbols) != len(set(symbols)):
        parser.error("duplicate symbol in universe")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    now = datetime.now(UTC)
    start = now - timedelta(days=args.days)
    rows, errors, ledger = [], [], []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_one, symbol, raw_dir, start, now, args.endpoint, now): symbol for symbol in symbols}
        for future in as_completed(futures):
            parsed, attempts, error = future.result()
            ledger.extend(attempts)
            if parsed:
                rows.append(parsed)
            if error:
                errors.append(error)
    rows.sort(key=lambda row: row["ticker"])
    errors.sort(key=lambda row: row["ticker"])
    ledger.sort(key=lambda row: (row["ticker"], row["attempt"]))
    completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "schema_version": 1, "provider": "Yahoo Finance chart public endpoint",
        "as_of_utc": completed_at,
        "request_window_end_utc": now.isoformat().replace("+00:00", "Z"),
        "retrieved_completed_at_utc": completed_at,
        "period_start_utc": start.isoformat().replace("+00:00", "Z"),
        "required_endpoints": args.endpoint, "requested_symbols": symbols,
        "coverage": {"requested": len(symbols), "valid": len(rows), "missing": len(errors)},
        "securities": rows, "engine_observations": engine_observations(rows), "errors": errors,
        "caveats": ["Public provider adjusted-close data is used only for ranking; raw snapshots retained.",
                    "Unavailable or invalid endpoints are excluded explicitly, never replaced by zero returns.",
                    "No paid or authenticated market-data entitlement is used."],
    }
    (args.output_dir / "history_payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    (args.output_dir / "retrieval_ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"coverage": payload["coverage"], "errors": errors, "payload": str(args.output_dir / "history_payload.json")}))


if __name__ == "__main__":
    main()
