"""Strict Nasdaq Trader listed-symbol proxy acquisition and parsing.

NASDAQ_LISTED is a current listing-status proxy only. It is never evidence of
exact Nasdaq Composite (COMP) constituents, weights, or valuation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from investment.research.index_identity import (
    canonical_json_bytes,
    write_new_bytes_atomic,
    write_new_json_atomic,
)

SOURCE_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
SOURCE_HOST = "www.nasdaqtrader.com"
SOURCE_PATH = "/dynamic/symdir/nasdaqlisted.txt"
SOURCE_TIME_ZONE = "America/New_York"
PARSER_VERSION = "nasdaq-listed-parser/v1"
MAX_RAW_BYTES = 8 * 1024 * 1024
MAX_SOURCE_AGE_CALENDAR_DAYS = 3
TIMEOUT_SECONDS = 20
HEADER = (
    "Symbol", "Security Name", "Market Category", "Test Issue",
    "Financial Status", "Round Lot Size", "ETF", "NextShares",
)
_TRAILER = re.compile(r"^File Creation Time: (\d{8})(\d{2}):(\d{2})$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.$-]{0,31}$")
_ALLOWED_MARKET = frozenset({"Q", "G", "S"})
_ALLOWED_FINANCIAL = frozenset({"", "D", "E", "Q", "G", "H", "J", "K", "N"})


class NasdaqListedError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _need(ok: bool, code: str) -> None:
    if not ok:
        raise NasdaqListedError(code)


def _utc_instant(value: str) -> datetime:
    _need(isinstance(value, str) and value.endswith("Z"), "NASDAQ_RETRIEVAL_TIME_INVALID")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise NasdaqListedError("NASDAQ_RETRIEVAL_TIME_INVALID") from None
    _need(result.utcoffset() == timezone.utc.utcoffset(result), "NASDAQ_RETRIEVAL_TIME_INVALID")
    return result


def _zulu(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_symbol(raw_symbol: str) -> str:
    """Preserve Nasdaq symbol identity; no class/ADR/special-security collapse."""
    _need(isinstance(raw_symbol, str) and raw_symbol == raw_symbol.strip()
          and _SYMBOL.fullmatch(raw_symbol) is not None, "NASDAQ_SYMBOL_INVALID")
    return raw_symbol


def _creation_time(value: str) -> tuple[str, datetime, str]:
    match = _TRAILER.fullmatch(value)
    _need(match is not None, "NASDAQ_TRAILER_INVALID")
    try:
        local = datetime.strptime(match.group(1) + match.group(2) + match.group(3),
                                  "%m%d%Y%H%M").replace(tzinfo=ZoneInfo(SOURCE_TIME_ZONE))
    except ValueError:
        raise NasdaqListedError("NASDAQ_FILE_CREATION_TIME_INVALID") from None
    return value.removeprefix("File Creation Time: "), local, _zulu(local)


def _freshness(created_local: datetime, retrieved: datetime) -> tuple[str, int]:
    created_utc = created_local.astimezone(timezone.utc)
    _need(created_utc <= retrieved, "NASDAQ_FILE_CREATION_IN_FUTURE")
    # Calendar-day arithmetic intentionally preserves the Nasdaq local wall time
    # across DST boundaries; it is not a fixed 72-hour duration.
    deadline_local = created_local + timedelta(days=MAX_SOURCE_AGE_CALENDAR_DAYS)
    deadline_utc = deadline_local.astimezone(timezone.utc)
    _need(retrieved <= deadline_utc, "NASDAQ_SOURCE_STALE")
    return _zulu(deadline_utc), int((retrieved - created_utc).total_seconds())


def parse_nasdaq_listed(raw: bytes, *, retrieved_at: str) -> dict[str, Any]:
    """Parse strict Nasdaq Trader bytes and enforce the frozen freshness gate."""
    _need(isinstance(raw, bytes) and 0 < len(raw) <= MAX_RAW_BYTES, "NASDAQ_RAW_SIZE_INVALID")
    _need(not raw.startswith(b"\xef\xbb\xbf") and b"\x00" not in raw, "NASDAQ_RAW_ENCODING_INVALID")
    retrieved = _utc_instant(retrieved_at)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise NasdaqListedError("NASDAQ_RAW_ENCODING_INVALID") from None
    lines = text.splitlines()
    _need(len(lines) >= 3 and all(line != "" for line in lines), "NASDAQ_FILE_SHAPE_INVALID")
    _need(tuple(lines[0].split("|")) == HEADER, "NASDAQ_HEADER_INVALID")
    trailer_fields = lines[-1].split("|")
    _need(len(trailer_fields) == len(HEADER) and all(x == "" for x in trailer_fields[1:]),
          "NASDAQ_TRAILER_INVALID")
    creation_raw, creation_local, creation_utc = _creation_time(trailer_fields[0])
    freshness_deadline, source_age_seconds = _freshness(creation_local, retrieved)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines[1:-1], 2):
        fields = line.split("|")
        _need(len(fields) == len(HEADER), "NASDAQ_ROW_MALFORMED")
        symbol, raw_name, market, test_issue, financial, lot, etf, next_shares = fields
        normalized = normalize_symbol(symbol)
        _need(normalized not in seen, "NASDAQ_DUPLICATE_NORMALIZED_SYMBOL")
        seen.add(normalized)
        _need(len(raw_name) <= 512 and not any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_name),
              "NASDAQ_SECURITY_NAME_INVALID")
        security_name = raw_name.strip(" ")
        _need(bool(security_name) and len(security_name) <= 512,
              "NASDAQ_SECURITY_NAME_INVALID")
        _need(market in _ALLOWED_MARKET, "NASDAQ_MARKET_CATEGORY_INVALID")
        _need(test_issue in {"Y", "N"} and etf in {"Y", "N"}
              and next_shares in {"Y", "N"}, "NASDAQ_FLAG_INVALID")
        _need(financial in _ALLOWED_FINANCIAL, "NASDAQ_FINANCIAL_STATUS_INVALID")
        _need(lot.isdigit() and 0 < int(lot) <= 1_000_000, "NASDAQ_ROUND_LOT_INVALID")
        rows.append({
            "raw_symbol": symbol,
            "normalized_symbol": normalized,
            "raw_security_name": raw_name,
            "security_name": security_name,
            "security_name_normalization": "strip_outer_ascii_space_preserve_internal",
            "market_category": market,
            "test_issue": test_issue,
            "financial_status": financial,
            "round_lot_size": int(lot),
            "etf": etf,
            "next_shares": next_shares,
            "source_line": line_number,
        })
    _need(bool(rows), "NASDAQ_ROSTER_EMPTY")
    rows.sort(key=lambda row: row["normalized_symbol"])
    return {
        "schema_version": PARSER_VERSION,
        "identity": "NASDAQ_LISTED",
        "proxy_for": "COMP",
        "not_comp_constituents": True,
        "satisfies_strict_comp_membership": False,
        "source_url": SOURCE_URL,
        "header": list(HEADER),
        "file_creation_time_raw": creation_raw,
        "file_creation_time_utc": creation_utc,
        "source_freshness_max_calendar_days": MAX_SOURCE_AGE_CALENDAR_DAYS,
        "source_freshness_deadline_utc": freshness_deadline,
        "source_age_seconds": source_age_seconds,
        "row_count": len(rows),
        "malformed_row_count": 0,
        "duplicate_normalized_symbol_count": 0,
        "normalization": "identity-preserving ASCII symbol; rows sorted by normalized_symbol",
        "normalized_rows_sha256": hashlib.sha256(canonical_json_bytes(rows)).hexdigest(),
        "rows": rows,
    }


def _header_value(headers: Any, name: str) -> str | None:
    value = headers.get(name) if hasattr(headers, "get") else None
    return str(value) if value is not None else None


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def _open_without_redirects(request: Request, *, timeout: int) -> Any:
    return build_opener(_RejectRedirects).open(request, timeout=timeout)


def acquire_nasdaq_listed(output_dir: str | os.PathLike[str], *,
                           retrieved_at: str | None = None,
                           opener: Callable[..., Any] | None = None,
                           clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """Perform one fixed-host GET with redirects rejected before following."""
    parsed_url = urlsplit(SOURCE_URL)
    _need(parsed_url.scheme == "https" and parsed_url.hostname == SOURCE_HOST
          and parsed_url.path == SOURCE_PATH and not parsed_url.query,
          "NASDAQ_SOURCE_IDENTITY_INVALID")
    if retrieved_at is None:
        now = (clock or (lambda: datetime.now(timezone.utc)))()
        _need(now.tzinfo is not None, "NASDAQ_RETRIEVAL_TIME_INVALID")
        retrieved_at = _zulu(now)
    _utc_instant(retrieved_at)
    root = Path(output_dir)
    _need(root.is_absolute() and ".." not in root.parts and not root.exists(),
          "NASDAQ_OUTPUT_EXISTS_OR_INVALID")
    _need(root.parent.is_dir() and not root.parent.is_symlink(), "NASDAQ_OUTPUT_PARENT_INVALID")
    root.mkdir(mode=0o700)
    response = None
    try:
        request = Request(SOURCE_URL, method="GET", headers={"User-Agent": "Trading-Agent-Nasdaq-Listed-Proxy/1"})
        request_opener = opener or _open_without_redirects
        try:
            response = request_opener(request, timeout=TIMEOUT_SECONDS)  # exactly one attempt
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                raise NasdaqListedError("NASDAQ_REDIRECT_REJECTED") from None
            raise NasdaqListedError("NASDAQ_HTTP_STATUS_INVALID") from None
        status = getattr(response, "status", None) or response.getcode()
        final_url = response.geturl()
        if 300 <= status < 400:
            raise NasdaqListedError("NASDAQ_REDIRECT_REJECTED")
        _need(status == 200, "NASDAQ_HTTP_STATUS_INVALID")
        _need(final_url == SOURCE_URL, "NASDAQ_REDIRECT_OR_URL_DRIFT")
        response_headers = {
            key.lower(): value for key in ("Content-Type", "Content-Length", "ETag", "Last-Modified")
            if (value := _header_value(response.headers, key)) is not None
        }
        length = response_headers.get("content-length")
        if length is not None:
            _need(length.isdigit() and int(length) <= MAX_RAW_BYTES,
                  "NASDAQ_CONTENT_LENGTH_INVALID")
        raw = response.read(MAX_RAW_BYTES + 1)
        response.close(); response = None
        parsed = parse_nasdaq_listed(raw, retrieved_at=retrieved_at)
        raw_receipt = write_new_bytes_atomic(raw, root / "nasdaqlisted.txt")
        custody = {
            "schema_version": "nasdaq-listed-raw-custody/v1",
            "source_url": SOURCE_URL,
            "fixed_host": SOURCE_HOST,
            "fixed_path": SOURCE_PATH,
            "method": "GET",
            "attempt_count": 1,
            "redirect_policy": "reject_before_follow",
            "redirect_count": 0,
            "http_status": 200,
            "retrieved_at": retrieved_at,
            "response_headers": response_headers,
            "raw_file": {"path": "nasdaqlisted.txt", **raw_receipt},
            "file_creation_time_raw": parsed["file_creation_time_raw"],
            "file_creation_time_utc": parsed["file_creation_time_utc"],
            "source_freshness_max_calendar_days": MAX_SOURCE_AGE_CALENDAR_DAYS,
            "source_freshness_deadline_utc": parsed["source_freshness_deadline_utc"],
            "source_age_seconds": parsed["source_age_seconds"],
            "parser_version": PARSER_VERSION,
            "row_count": parsed["row_count"],
            "not_comp_constituents": True,
            "satisfies_strict_comp_membership": False,
        }
        custody_receipt = write_new_json_atomic(custody, root / "raw-custody-v1.json")
        return {"custody": custody, "custody_file": custody_receipt, "parsed": parsed}
    except BaseException:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        shutil.rmtree(root, ignore_errors=True)
        raise
