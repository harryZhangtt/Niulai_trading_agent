"""Strict Nasdaq Composite identity and exact-data availability packets.

The packet distinguishes the official ``Nasdaq Composite`` / ``COMP`` identity
from the vendor symbol ``^IXIC`` and the FRED price-series identifier
``NASDAQCOM``.  Membership, weights, component count, and valuation are separate
availability claims.  A proxy may be recorded, but never promoted into an exact
COMP field.

This module is deliberately provider-free and standard-library-only.  It validates
claims and provenance shape; it does not assert that a supplied source is truthful.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX writer unavailable
    fcntl = None
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import stat
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
KIND = "nasdaq_composite_identity_availability"
MAX_INPUT_BYTES = 1024 * 1024
_WEIGHT_TOLERANCE = Decimal("0.000001")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,15}\Z")
_SECRET = re.compile(
    r"(?i)(?:\bbearer\s+\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\b(?:sk|ghp|gho|ghu|ghs|ghr)[-_][A-Za-z0-9_-]{8,}|"
    r"\bgithub_pat_[A-Za-z0-9_]{20,}|"
    r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|"
    r"client[_ -]?secret|credential|private[_ -]?key)\b\s*[:=]\s*\S+|"
    r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"
)
_PRIVATE_PATH = re.compile(
    r"(?i)(?:/Users/|/home/|/private/|/var/folders/|/root/|/etc/|/tmp/|"
    r"/Volumes/|/mnt/|/srv/|/workspace/|(?:^|[\s'\"=(])[A-Z]:[\\/]|~[/\\]|"
    r"file:(?://)?[/\\]|\\\\[^\\/]+[\\/][^\\/]+|"
    r"(?:%2f|%5c)(?:users|home|private|root|etc|tmp)(?:%2f|%5c))"
)

_ROOT_KEYS = {
    "schema_version", "kind", "identity", "aliases", "availability", "proxies"
}
_IDENTITY_KEYS = {"official_name", "official_symbol", "basis", "source"}
_ALIAS_KEYS = {"symbol", "kind", "provider", "basis", "source"}
_SOURCE_KEYS = {
    "authority", "publisher", "url", "published_date", "retrieved_at", "sha256"
}
_FIELD_KEYS = {"status", "value", "effective_date", "source", "reason"}
_AVAILABILITY_KEYS = {
    "current_level", "history", "component_count", "membership", "weights", "valuation"
}
_LEVEL_KEYS = {"level", "basis"}
_HISTORY_KEYS = {
    "basis", "start_date", "end_date", "observation_count", "artifact_sha256",
    "series_id", "provenance"
}
_WEIGHT_KEYS = {"symbol", "weight"}
_VALUATION_KEYS = {"metric", "value", "unit", "estimate_effective_date"}
_PROXY_KEYS = {"kind", "symbol", "basis", "effective_date", "source"}
_VALUATION_METRICS = {
    "price_to_earnings", "forward_price_to_earnings", "price_to_book", "price_to_sales"
}


class IndexIdentityError(ValueError):
    """A stable, sanitized packet or publication failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise IndexIdentityError(code)


def _need(condition: bool, code: str) -> None:
    if not condition:
        _fail(code)


def _object(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    _need(isinstance(value, dict) and set(value) == keys, code)
    return value


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("INDEX_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _constant(_: str) -> None:
    _fail("INDEX_JSON_NONFINITE")


def load_packet(data: str | bytes | bytearray) -> dict[str, Any]:
    """Decode strict JSON, rejecting duplicate keys and non-finite constants."""
    _need(isinstance(data, (str, bytes, bytearray)), "INDEX_JSON_INVALID")
    try:
        raw_size = len(data.encode("utf-8")) if isinstance(data, str) else len(data)
    except UnicodeError:
        raise IndexIdentityError("INDEX_JSON_UNICODE_INVALID") from None
    _need(raw_size <= MAX_INPUT_BYTES, "INDEX_JSON_TOO_LARGE")
    try:
        value = json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
    except IndexIdentityError:
        raise
    except RecursionError:
        raise IndexIdentityError("INDEX_STRUCTURE_TOO_DEEP") from None
    except UnicodeError:
        raise IndexIdentityError("INDEX_JSON_UNICODE_INVALID") from None
    except (json.JSONDecodeError, TypeError, ValueError):
        raise IndexIdentityError("INDEX_JSON_INVALID") from None
    _need(isinstance(value, dict), "INDEX_PACKET_SCHEMA")
    _scan_strings(value)
    return value


def _date(value: Any, code: str) -> str:
    _need(isinstance(value, str), code)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(code)
    _need(parsed.isoformat() == value, code)
    return value


def _instant(value: Any, code: str) -> datetime:
    _need(isinstance(value, str) and value.endswith("Z"), code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail(code)
    _need(parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed), code)
    return parsed


def _safe_text(value: Any, code: str, *, maximum: int = 512) -> str:
    _need(isinstance(value, str) and 0 < len(value) <= maximum, code)
    _need(not any(0xD800 <= ord(character) <= 0xDFFF for character in value),
          "INDEX_TEXT_UNICODE_INVALID")
    _need("\x00" not in value and not _SECRET.search(value), "INDEX_SECRET_OR_PRIVATE_DATA")
    _need(not _PRIVATE_PATH.search(value), "INDEX_SECRET_OR_PRIVATE_DATA")
    if not value.startswith(("http://", "https://")):
        _need(not value.startswith(("/", "~", "\\")), "INDEX_SECRET_OR_PRIVATE_DATA")
        _need(not PureWindowsPath(value).is_absolute(), "INDEX_SECRET_OR_PRIVATE_DATA")
    return value


def _source(value: Any, code: str) -> dict[str, Any]:
    source = _object(value, _SOURCE_KEYS, code)
    authority = source["authority"]
    _need(isinstance(authority, str)
          and authority in {"official", "vendor", "fred", "estimate", "proxy"}, code)
    _safe_text(source["publisher"], code, maximum=160)
    url = _safe_text(source["url"], code, maximum=1000)
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        _fail(code)
    _need(parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None
          and parsed.password is None and port in {None, 443}, code)
    host = parsed.hostname.lower()
    _need(host not in {"localhost", "localhost.localdomain"}
          and not host.endswith((".local", ".internal")), code)
    published = _date(source["published_date"], code)
    retrieved = _instant(source["retrieved_at"], code)
    _need(retrieved.date() >= date.fromisoformat(published), "INDEX_DATE_INCONSISTENT")
    _need(isinstance(source["sha256"], str) and _SHA256.fullmatch(source["sha256"]) is not None,
          code)
    return source


def _is_nasdaq_official(source: Mapping[str, Any]) -> bool:
    try:
        host = (urlsplit(source["url"]).hostname or "").lower()
    except (TypeError, ValueError):
        return False
    return (source["authority"] == "official"
            and source["publisher"] in {"Nasdaq", "Nasdaq, Inc."}
            and (host == "nasdaq.com" or host.endswith(".nasdaq.com")))


def _is_fred(source: Mapping[str, Any]) -> bool:
    try:
        host = (urlsplit(source["url"]).hostname or "").lower()
    except (TypeError, ValueError):
        return False
    return (source["authority"] == "fred"
            and source["publisher"] == "Federal Reserve Bank of St. Louis"
            and (host == "stlouisfed.org" or host.endswith(".stlouisfed.org")))


def _is_allowed_estimate(source: Mapping[str, Any]) -> bool:
    try:
        host = (urlsplit(source["url"]).hostname or "").lower()
    except (TypeError, ValueError):
        return False
    allowed = {
        "FactSet": "factset.com",
        "LSEG": "lseg.com",
    }
    expected = allowed.get(source["publisher"])
    return (source["authority"] == "estimate" and expected is not None
            and (host == expected or host.endswith("." + expected)))


def _decimal(value: Any, code: str, *, positive: bool = True) -> Decimal:
    _need(isinstance(value, str) and value == value.strip() and bool(value), code)
    try:
        number = Decimal(value)
    except InvalidOperation:
        _fail(code)
    _need(number.is_finite() and (number > 0 if positive else number >= 0), code)
    return number


def _availability_field(name: str, value: Any) -> dict[str, Any]:
    field = _object(value, _FIELD_KEYS, "INDEX_AVAILABILITY_SCHEMA")
    status = field["status"]
    _need(isinstance(status, str) and status in {"exact", "unverifiable"},
          "INDEX_AVAILABILITY_STATUS")
    if status == "unverifiable":
        _need(field["value"] is None and field["effective_date"] is None
              and field["source"] is None
              and isinstance(field["reason"], str)
              and field["reason"] in {"gated", "unavailable", "not_published"},
              "INDEX_UNVERIFIABLE_MUST_BE_NULL")
        return field
    _need(field["reason"] is None, "INDEX_EXACT_FIELD_INVALID")
    _date(field["effective_date"], "INDEX_EXACT_DATE_MISSING")
    source = _source(field["source"], "INDEX_EXACT_SOURCE_INVALID")
    if name in {"current_level", "component_count", "membership", "weights"}:
        _need(_is_nasdaq_official(source), "INDEX_EXACT_REQUIRES_OFFICIAL_SOURCE")
    elif name == "history":
        _need(_is_nasdaq_official(source) or _is_fred(source),
              "INDEX_HISTORY_SOURCE_INVALID")
    elif name == "valuation":
        if source["authority"] == "official":
            _need(_is_nasdaq_official(source), "INDEX_VALUATION_SOURCE_INVALID")
        else:
            _need(_is_allowed_estimate(source), "INDEX_VALUATION_ESTIMATE_SOURCE_INVALID")
        _need(source["published_date"] == field["effective_date"],
              "INDEX_VALUATION_ESTIMATE_SOURCE_UNALIGNED")
    return field


def _validate_identity(packet: dict[str, Any]) -> None:
    identity = _object(packet["identity"], _IDENTITY_KEYS, "INDEX_IDENTITY_SCHEMA")
    _need(identity["official_name"] == "Nasdaq Composite"
          and identity["official_symbol"] == "COMP", "INDEX_OFFICIAL_IDENTITY_CONFUSION")
    _need(identity["basis"] == "price_index", "INDEX_BASIS_CONFUSION")
    source = _source(identity["source"], "INDEX_IDENTITY_SOURCE_INVALID")
    _need(_is_nasdaq_official(source), "INDEX_IDENTITY_SOURCE_NOT_OFFICIAL")


def _validate_aliases(packet: dict[str, Any]) -> None:
    aliases = packet["aliases"]
    _need(isinstance(aliases, list) and len(aliases) == 2, "INDEX_ALIAS_SET_REQUIRED")
    seen: set[str] = set()
    for raw in aliases:
        alias = _object(raw, _ALIAS_KEYS, "INDEX_ALIAS_SCHEMA")
        symbol = alias["symbol"]
        _need(isinstance(symbol, str), "INDEX_ALIAS_SCHEMA")
        _need(symbol not in seen, "INDEX_ALIAS_DUPLICATE")
        seen.add(symbol)
        _safe_text(alias["provider"], "INDEX_ALIAS_SCHEMA", maximum=80)
        source = _source(alias["source"], "INDEX_ALIAS_SOURCE_INVALID")
        _need(alias["basis"] == "price_index", "INDEX_BASIS_CONFUSION")
        if symbol == "^IXIC":
            _need(alias["kind"] == "vendor_alias" and source["authority"] == "vendor",
                  "INDEX_VENDOR_ALIAS_CONFUSION")
        elif symbol == "NASDAQCOM":
            _need(alias["kind"] == "price_series_alias"
                  and alias["provider"] == "FRED"
                  and _is_fred(source), "INDEX_FRED_ALIAS_CONFUSION")
        else:
            _fail("INDEX_UNSUPPORTED_ALIAS")
    _need(seen == {"^IXIC", "NASDAQCOM"}, "INDEX_ALIAS_SET_REQUIRED")


def _validate_proxies(packet: dict[str, Any]) -> None:
    proxies = packet["proxies"]
    _need(isinstance(proxies, list) and len(proxies) <= 2, "INDEX_PROXY_SCHEMA")
    seen: set[str] = set()
    for raw in proxies:
        proxy = _object(raw, _PROXY_KEYS, "INDEX_PROXY_SCHEMA")
        kind = proxy["kind"]
        _need(isinstance(kind, str), "INDEX_PROXY_SCHEMA")
        _need(kind not in seen, "INDEX_PROXY_DUPLICATE")
        seen.add(kind)
        effective_date = _date(proxy["effective_date"], "INDEX_PROXY_DATE_INVALID")
        source = _source(proxy["source"], "INDEX_PROXY_SOURCE_INVALID")
        _need(source["authority"] == "proxy", "INDEX_PROXY_SOURCE_INVALID")
        _need(source["published_date"] == effective_date, "INDEX_PROXY_SOURCE_DATE_REQUIRED")
        if kind == "oneq_etf":
            _need(proxy["symbol"] == "ONEQ" and isinstance(proxy["basis"], str)
                  and proxy["basis"] in {"etf_market_price_return", "etf_total_return"},
                  "INDEX_PROXY_SCHEMA")
        elif kind == "nasdaq_listed_market_cap_reconstruction":
            _need(proxy["symbol"] is None and proxy["basis"] == "market_cap_reconstruction",
                  "INDEX_PROXY_SCHEMA")
        else:
            _fail("INDEX_UNSUPPORTED_PROXY")


def _validate_availability(packet: dict[str, Any]) -> None:
    availability = _object(packet["availability"], _AVAILABILITY_KEYS,
                           "INDEX_AVAILABILITY_SCHEMA")
    fields = {name: _availability_field(name, availability[name])
              for name in sorted(_AVAILABILITY_KEYS)}
    exact_dates = {field["effective_date"] for field in fields.values()
                   if field["status"] == "exact"}
    _need(len(exact_dates) <= 1, "INDEX_DATE_INCONSISTENT")

    current_level = fields["current_level"]
    history = fields["history"]
    count = fields["component_count"]
    membership = fields["membership"]
    weights = fields["weights"]
    valuation = fields["valuation"]

    if current_level["status"] == "exact":
        level = _object(current_level["value"], _LEVEL_KEYS, "INDEX_CURRENT_LEVEL_INVALID")
        _decimal(level["level"], "INDEX_CURRENT_LEVEL_INVALID")
        _need(level["basis"] == "price_index", "INDEX_BASIS_CONFUSION")
        _need(current_level["source"]["published_date"] == current_level["effective_date"],
              "INDEX_CURRENT_LEVEL_OFFICIAL_DATE_REQUIRED")

    if history["status"] == "exact":
        value = _object(history["value"], _HISTORY_KEYS, "INDEX_HISTORY_INVALID")
        _need(value["basis"] == "price_index", "INDEX_BASIS_CONFUSION")
        start = _date(value["start_date"], "INDEX_HISTORY_DATE_INVALID")
        end = _date(value["end_date"], "INDEX_HISTORY_DATE_INVALID")
        _need(start <= end and end == history["effective_date"], "INDEX_DATE_INCONSISTENT")
        _need(type(value["observation_count"]) is int and value["observation_count"] > 0,
              "INDEX_HISTORY_INVALID")
        _need(isinstance(value["artifact_sha256"], str)
              and _SHA256.fullmatch(value["artifact_sha256"]) is not None,
              "INDEX_HISTORY_INVALID")
        source = history["source"]
        _need(source["published_date"] == end, "INDEX_HISTORY_SOURCE_DATE_REQUIRED")
        if source["authority"] == "official":
            _need(_is_nasdaq_official(source) and value["series_id"] == "COMP"
                  and value["provenance"] == "official_nasdaq_comp",
                  "INDEX_HISTORY_SOURCE_INVALID")
        else:
            _need(_is_fred(source) and value["series_id"] == "NASDAQCOM"
                  and value["provenance"] == "fred_nasdaqcom_price_series",
                  "INDEX_HISTORY_SOURCE_INVALID")

    if count["status"] == "exact":
        _need(type(count["value"]) is int and count["value"] > 0,
              "INDEX_COMPONENT_COUNT_INVALID")
        _need(count["source"]["published_date"] == count["effective_date"],
              "INDEX_COMPONENT_COUNT_OFFICIAL_DATE_REQUIRED")

    members: list[str] | None = None
    if membership["status"] == "exact":
        _need(membership["source"]["published_date"] == membership["effective_date"],
              "INDEX_MEMBERSHIP_SOURCE_DATE_REQUIRED")
        members = membership["value"]
        _need(isinstance(members, list) and bool(members), "INDEX_MEMBERSHIP_INVALID")
        _need(all(isinstance(symbol, str) and _SYMBOL.fullmatch(symbol) is not None
                  for symbol in members), "INDEX_MEMBERSHIP_INVALID")
        _need(len(set(members)) == len(members), "INDEX_MEMBERSHIP_DUPLICATE")
        _need(not ({"COMP", "^IXIC", "NASDAQCOM", "ONEQ"} & set(members)),
              "INDEX_PROXY_OR_ALIAS_AS_EXACT")
        if count["status"] == "exact":
            _need(count["value"] == len(members), "INDEX_COMPONENT_COUNT_MISMATCH")

    if weights["status"] == "exact":
        _need(weights["source"]["published_date"] == weights["effective_date"],
              "INDEX_WEIGHTS_SOURCE_DATE_REQUIRED")
        _need(members is not None, "INDEX_WEIGHTS_REQUIRE_MEMBERSHIP")
        rows = weights["value"]
        _need(isinstance(rows, list) and bool(rows), "INDEX_WEIGHTS_INVALID")
        symbols: list[str] = []
        total = Decimal(0)
        for raw in rows:
            row = _object(raw, _WEIGHT_KEYS, "INDEX_WEIGHTS_INVALID")
            _need(isinstance(row["symbol"], str) and _SYMBOL.fullmatch(row["symbol"]) is not None,
                  "INDEX_WEIGHTS_INVALID")
            number = _decimal(row["weight"], "INDEX_WEIGHTS_INVALID")
            _need(number <= 1, "INDEX_WEIGHTS_INVALID")
            symbols.append(row["symbol"])
            total += number
        _need(len(set(symbols)) == len(symbols), "INDEX_WEIGHT_SYMBOL_DUPLICATE")
        _need(set(symbols) == set(members), "INDEX_WEIGHT_MEMBERSHIP_MISMATCH")
        _need(abs(total - Decimal(1)) <= _WEIGHT_TOLERANCE,
              "INDEX_WEIGHT_RECONCILIATION_FAILED")

    if valuation["status"] == "exact":
        _need(members is not None and weights["status"] == "exact",
              "INDEX_VALUATION_REQUIRES_MEMBERSHIP_AND_WEIGHTS")
        value = _object(valuation["value"], _VALUATION_KEYS, "INDEX_VALUATION_INVALID")
        _need(isinstance(value["metric"], str)
              and value["metric"] in _VALUATION_METRICS and value["unit"] == "ratio",
              "INDEX_UNSUPPORTED_VALUATION_CLAIM")
        _decimal(value["value"], "INDEX_VALUATION_INVALID")
        _need(value["estimate_effective_date"] == valuation["effective_date"],
              "INDEX_VALUATION_ESTIMATE_SOURCE_UNALIGNED")


def _scan_strings(value: Any) -> None:
    pending: list[tuple[Any, int]] = [(value, 0)]
    seen_containers: set[int] = set()
    visited = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        _need(visited <= 10000, "INDEX_STRUCTURE_TOO_LARGE")
        _need(depth <= 24, "INDEX_STRUCTURE_TOO_DEEP")
        if isinstance(item, str):
            _safe_text(item, "INDEX_TEXT_INVALID", maximum=4000)
        elif isinstance(item, dict):
            identity = id(item)
            _need(identity not in seen_containers, "INDEX_STRUCTURE_CYCLIC")
            seen_containers.add(identity)
            for key, child in item.items():
                _safe_text(key, "INDEX_PACKET_SCHEMA", maximum=80)
                pending.append((child, depth + 1))
        elif isinstance(item, list):
            identity = id(item)
            _need(identity not in seen_containers, "INDEX_STRUCTURE_CYCLIC")
            seen_containers.add(identity)
            pending.extend((child, depth + 1) for child in item)


def validate_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one already-decoded packet and return a detached canonical copy."""
    _need(isinstance(packet, dict), "INDEX_PACKET_SCHEMA")
    packet_dict = _object(packet, _ROOT_KEYS, "INDEX_PACKET_SCHEMA")
    _scan_strings(packet_dict)
    _need(packet_dict["schema_version"] == SCHEMA_VERSION and type(packet_dict["schema_version"]) is int,
          "INDEX_SCHEMA_VERSION_UNSUPPORTED")
    _need(packet_dict["kind"] == KIND, "INDEX_PACKET_KIND_UNSUPPORTED")
    _validate_identity(packet_dict)
    _validate_aliases(packet_dict)
    _validate_availability(packet_dict)
    _validate_proxies(packet_dict)
    return json.loads(json.dumps(packet_dict, allow_nan=False, sort_keys=True,
                                 separators=(",", ":")), object_pairs_hook=_pairs,
                      parse_constant=_constant)


def compile_packet(value: Mapping[str, Any] | str | bytes | bytearray) -> dict[str, Any]:
    """Strictly decode when necessary, validate, and return canonical packet data."""
    packet = load_packet(value) if isinstance(value, (str, bytes, bytearray)) else value
    return validate_packet(packet)


def encode_packet(value: Mapping[str, Any] | str | bytes | bytearray) -> bytes:
    """Compile one packet to deterministic UTF-8 JSON with a trailing newline."""
    packet = compile_packet(value)
    return (json.dumps(packet, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def packet_sha256(value: Mapping[str, Any] | str | bytes | bytearray) -> str:
    return hashlib.sha256(encode_packet(value)).hexdigest()


def _meta(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


class _HeldParent:
    """A path parent reached one no-follow directory component at a time."""

    def __init__(self, descriptors: list[int], links: list[tuple[int, str, int]],
                 leaf: str, secure_parent: tuple[int, int] | None):
        self.descriptors = descriptors
        self.links = links
        self.leaf = leaf
        self.secure_parent = secure_parent

    @property
    def fd(self) -> int:
        return self.descriptors[-1]

    def stable(self) -> bool:
        try:
            for parent_fd, name, child_fd in self.links:
                named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                opened = os.fstat(child_fd)
                if (not stat.S_ISDIR(named.st_mode)
                        or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)):
                    return False
            if self.secure_parent is not None:
                parent = os.fstat(self.fd)
                expected_uid, expected_mode = self.secure_parent
                if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != expected_uid
                        or stat.S_IMODE(parent.st_mode) != expected_mode
                        or parent.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
                    return False
            return True
        except (OSError, ValueError, TypeError):
            return False

    def close(self) -> None:
        for descriptor in reversed(self.descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.descriptors.clear()


def _open_held_parent(path_value: str | os.PathLike[str], code: str,
                      *, output: bool = False) -> _HeldParent:
    descriptors: list[int] = []
    try:
        raw = os.fspath(path_value)
        _need(isinstance(raw, str) and "\x00" not in raw, code)
        lexical = Path(raw)
        _need(".." not in lexical.parts, code)
        candidate = lexical.absolute()
        _need(candidate.is_absolute() and candidate.anchor == os.sep, code)
        parts = candidate.parts[1:]
        _need(bool(parts) and all(part not in {"", ".", ".."} for part in parts), code)
        required_flags = (getattr(os, "O_DIRECTORY", 0), getattr(os, "O_NOFOLLOW", 0),
                          getattr(os, "O_NONBLOCK", 0))
        _need(all(required_flags) and hasattr(os, "getuid"), code)
        directory_flags = (os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                           | getattr(os, "O_CLOEXEC", 0))
        descriptor = os.open(os.sep, directory_flags)
        descriptors.append(descriptor)
        links: list[tuple[int, str, int]] = []
        for part in parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=descriptor)
            descriptors.append(child)
            info = os.fstat(child)
            _need(stat.S_ISDIR(info.st_mode), code)
            links.append((descriptor, part, child))
            descriptor = child
        parent_info = os.fstat(descriptor)
        _need(stat.S_ISDIR(parent_info.st_mode), code)
        secure_parent: tuple[int, int] | None = None
        if output:
            _need(parent_info.st_uid == os.getuid()
                  and not (parent_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)), code)
            secure_parent = (parent_info.st_uid, stat.S_IMODE(parent_info.st_mode))
        held = _HeldParent(descriptors, links, parts[-1], secure_parent)
        _need(held.stable(), code)
        return held
    except IndexIdentityError:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except (OSError, ValueError, TypeError, UnicodeError):
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise IndexIdentityError(code) from None

def _leaf_matches(parent_fd: int, leaf: str, descriptor: int) -> bool:
    try:
        named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(descriptor)
        return ((named.st_dev, named.st_ino) == (opened.st_dev, opened.st_ino)
                and stat.S_ISREG(named.st_mode))
    except (OSError, ValueError, TypeError):
        return False


def _capture_existing(parent_fd: int, leaf: str) -> tuple[tuple[int, ...], int] | None:
    flags = (os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
             | getattr(os, "O_CLOEXEC", 0))
    try:
        descriptor = os.open(leaf, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise IndexIdentityError("INDEX_OUTPUT_INVALID") from None
    try:
        before = os.fstat(descriptor)
        _need(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
              and before.st_nlink == 1, "INDEX_OUTPUT_INVALID")
        _need(_leaf_matches(parent_fd, leaf, descriptor), "INDEX_OUTPUT_INVALID")
        after = os.fstat(descriptor)
        _need(_meta(before) == _meta(after), "INDEX_OUTPUT_INVALID")
        return _meta(before), descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _prior_unchanged(parent_fd: int, leaf: str,
                     prior: tuple[tuple[int, ...], int] | None) -> bool:
    try:
        current = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return prior is None
    except (OSError, ValueError, TypeError):
        return False
    return (prior is not None and stat.S_ISREG(current.st_mode)
            and _meta(current) == prior[0])


def _prior_consumed(prior: tuple[tuple[int, ...], int] | None) -> bool:
    if prior is None:
        return True
    try:
        current = os.fstat(prior[1])
    except OSError:
        return False
    return ((current.st_dev, current.st_ino) == (prior[0][0], prior[0][1])
            and current.st_nlink == 0)


def _close_prior(prior: tuple[tuple[int, ...], int] | None) -> None:
    if prior is not None:
        try:
            os.close(prior[1])
        except OSError:
            pass

def _readback_exact(parent_fd: int, leaf: str, expected: bytes) -> bool:
    flags = (os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
             | getattr(os, "O_CLOEXEC", 0))
    try:
        descriptor = os.open(leaf, flags, dir_fd=parent_fd)
    except (OSError, ValueError, TypeError):
        return False
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_nlink != 1 or before.st_size != len(expected)
                or not _leaf_matches(parent_fd, leaf, descriptor)):
            return False
        chunks: list[bytes] = []
        remaining = len(expected) + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        return (_meta(before) == _meta(after) and _leaf_matches(parent_fd, leaf, descriptor)
                and b"".join(chunks) == expected)
    except (OSError, ValueError, TypeError):
        return False
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _write_all(descriptor: int, raw: bytes) -> None:
    view = memoryview(raw)
    written = 0
    while written < len(view):
        count = os.write(descriptor, view[written:])
        if not isinstance(count, int) or count <= 0:
            raise OSError("short write")
        written += count


def _unlink_owned_temp(parent_fd: int, name: str | None,
                       identity: tuple[int, int] | None) -> None:
    if name is None or identity is None:
        return
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and (info.st_dev, info.st_ino) == identity):
            os.unlink(name, dir_fd=parent_fd)
    except OSError:
        pass


def write_packet_atomic(value: Mapping[str, Any] | str | bytes | bytearray,
                        output_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Validate and publish through one locked, held, no-follow parent descriptor."""
    packet = compile_packet(value)
    raw = (json.dumps(packet, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    held: _HeldParent | None = None
    temporary: str | None = None
    temporary_identity: tuple[int, int] | None = None
    replace_attempted = False
    replace_acknowledged = False
    prior: tuple[tuple[int, ...], int] | None = None
    locked = False
    try:
        held = _open_held_parent(output_path, "INDEX_OUTPUT_INVALID", output=True)
        _need(fcntl is not None, "INDEX_OUTPUT_INVALID")
        try:
            fcntl.flock(held.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise IndexIdentityError("INDEX_OUTPUT_FAILED") from None
        _need(held.stable(), "INDEX_OUTPUT_FAILED")
        prior = _capture_existing(held.fd, held.leaf)
        flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                 | getattr(os, "O_CLOEXEC", 0))
        descriptor: int | None = None
        for _ in range(32):
            candidate = f".index-identity-{secrets.token_hex(16)}.tmp"
            try:
                descriptor = os.open(candidate, flags, 0o600, dir_fd=held.fd)
                temporary = candidate
                break
            except FileExistsError:
                continue
        if descriptor is None or temporary is None:
            raise OSError("temporary name exhaustion")
        try:
            os.fchmod(descriptor, 0o600)
            info = os.fstat(descriptor)
            _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                  and info.st_nlink == 1, "INDEX_OUTPUT_FAILED")
            temporary_identity = (info.st_dev, info.st_ino)
            _write_all(descriptor, raw)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _need(held.stable() and _prior_unchanged(held.fd, held.leaf, prior),
              "INDEX_OUTPUT_FAILED")
        replace_attempted = True
        if prior is None:
            try:
                os.link(temporary, held.leaf, src_dir_fd=held.fd, dst_dir_fd=held.fd,
                        follow_symlinks=False)
            except FileExistsError:
                raise IndexIdentityError("INDEX_OUTPUT_FAILED") from None
            except OSError:
                if held.stable() and _prior_unchanged(held.fd, held.leaf, prior):
                    raise IndexIdentityError("INDEX_OUTPUT_FAILED") from None
                raise IndexIdentityError("INDEX_OUTPUT_OUTCOME_UNKNOWN") from None
            try:
                os.unlink(temporary, dir_fd=held.fd)
            except OSError:
                raise IndexIdentityError("INDEX_OUTPUT_OUTCOME_UNKNOWN") from None
        else:
            try:
                os.replace(temporary, held.leaf, src_dir_fd=held.fd, dst_dir_fd=held.fd)
            except OSError:
                if held.stable() and _prior_unchanged(held.fd, held.leaf, prior):
                    raise IndexIdentityError("INDEX_OUTPUT_FAILED") from None
                if (held.stable() and _prior_consumed(prior)
                        and _readback_exact(held.fd, held.leaf, raw)
                        and held.stable()):
                    raise IndexIdentityError("INDEX_OUTPUT_DURABILITY_UNVERIFIED") from None
                raise IndexIdentityError("INDEX_OUTPUT_OUTCOME_UNKNOWN") from None
            if not _prior_consumed(prior):
                raise IndexIdentityError("INDEX_OUTPUT_OUTCOME_UNKNOWN")
        temporary = None
        replace_acknowledged = True
        try:
            os.fsync(held.fd)
        except OSError:
            if (held.stable() and _prior_consumed(prior)
                    and _readback_exact(held.fd, held.leaf, raw)
                    and held.stable()):
                raise IndexIdentityError("INDEX_OUTPUT_DURABILITY_UNVERIFIED") from None
            raise IndexIdentityError("INDEX_OUTPUT_OUTCOME_UNKNOWN") from None
        _need(held.stable() and _prior_consumed(prior)
              and _readback_exact(held.fd, held.leaf, raw) and held.stable(),
              "INDEX_OUTPUT_OUTCOME_UNKNOWN")
    except IndexIdentityError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        if held is not None and (replace_acknowledged or replace_attempted):
            if held.stable() and _prior_unchanged(held.fd, held.leaf, prior):
                code = "INDEX_OUTPUT_FAILED"
            elif (held.stable() and _prior_consumed(prior)
                  and _readback_exact(held.fd, held.leaf, raw)
                  and held.stable()):
                code = "INDEX_OUTPUT_DURABILITY_UNVERIFIED"
            else:
                code = "INDEX_OUTPUT_OUTCOME_UNKNOWN"
        else:
            code = "INDEX_OUTPUT_FAILED"
        raise IndexIdentityError(code) from None
    finally:
        if held is not None:
            _unlink_owned_temp(held.fd, temporary, temporary_identity)
            _close_prior(prior)
            if locked and fcntl is not None:
                try:
                    fcntl.flock(held.fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            held.close()
    return packet

def canonical_json_bytes(value: Any) -> bytes:
    """Encode an arbitrary JSON value deterministically for immutable proxy artifacts."""
    try:
        raw = (json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise IndexIdentityError("INDEX_JSON_INVALID") from None
    _need(len(raw) <= 8 * 1024 * 1024, "INDEX_JSON_TOO_LARGE")
    return raw


def write_new_bytes_atomic(raw: bytes, output_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Publish one new immutable file; reject overwrite, links and ancestor drift."""
    _need(isinstance(raw, bytes) and len(raw) <= 8 * 1024 * 1024,
          "INDEX_OUTPUT_INVALID")
    held: _HeldParent | None = None
    temporary: str | None = None
    temporary_identity: tuple[int, int] | None = None
    descriptor: int | None = None
    locked = False
    try:
        held = _open_held_parent(output_path, "INDEX_OUTPUT_INVALID", output=True)
        _need(fcntl is not None, "INDEX_OUTPUT_INVALID")
        try:
            fcntl.flock(held.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise IndexIdentityError("INDEX_OUTPUT_FAILED") from None
        _need(held.stable(), "INDEX_OUTPUT_FAILED")
        try:
            os.stat(held.leaf, dir_fd=held.fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise IndexIdentityError("INDEX_OUTPUT_EXISTS")
        flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                 | getattr(os, "O_CLOEXEC", 0))
        for _ in range(32):
            candidate = f".proxy-artifact-{secrets.token_hex(16)}.tmp"
            try:
                descriptor = os.open(candidate, flags, 0o600, dir_fd=held.fd)
                temporary = candidate
                break
            except FileExistsError:
                continue
        _need(descriptor is not None and temporary is not None, "INDEX_OUTPUT_FAILED")
        try:
            os.fchmod(descriptor, 0o600)
            info = os.fstat(descriptor)
            _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                  and info.st_nlink == 1, "INDEX_OUTPUT_FAILED")
            temporary_identity = (info.st_dev, info.st_ino)
            _write_all(descriptor, raw)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
            descriptor = None
        _need(held.stable(), "INDEX_OUTPUT_FAILED")
        try:
            os.link(temporary, held.leaf, src_dir_fd=held.fd, dst_dir_fd=held.fd,
                    follow_symlinks=False)
        except FileExistsError:
            raise IndexIdentityError("INDEX_OUTPUT_EXISTS") from None
        except OSError:
            raise IndexIdentityError("INDEX_OUTPUT_OUTCOME_UNKNOWN") from None
        try:
            os.unlink(temporary, dir_fd=held.fd)
            temporary = None
        except OSError:
            raise IndexIdentityError("INDEX_OUTPUT_OUTCOME_UNKNOWN") from None
        os.fsync(held.fd)
        _need(held.stable() and _readback_exact(held.fd, held.leaf, raw),
              "INDEX_OUTPUT_OUTCOME_UNKNOWN")
        return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    except IndexIdentityError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError):
        raise IndexIdentityError("INDEX_OUTPUT_FAILED") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if held is not None:
            _unlink_owned_temp(held.fd, temporary, temporary_identity)
            if locked:
                try:
                    fcntl.flock(held.fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            held.close()


def write_new_json_atomic(value: Any, output_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Canonical JSON companion to :func:`write_new_bytes_atomic`."""
    return write_new_bytes_atomic(canonical_json_bytes(value), output_path)


def _cli_error(code: str) -> int:
    sys.stderr.write(json.dumps({"status": "invalid", "code": code},
                                sort_keys=True, separators=(",", ":")) + "\n")
    return 1


def _read_bounded(path: Path) -> bytes:
    held: _HeldParent | None = None
    descriptor: int | None = None
    try:
        held = _open_held_parent(path, "INDEX_INPUT_INVALID")
        flags = (os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                 | getattr(os, "O_CLOEXEC", 0))
        descriptor = os.open(held.leaf, flags, dir_fd=held.fd)
        before = os.fstat(descriptor)
        _need(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
              and before.st_nlink == 1, "INDEX_INPUT_INVALID")
        _need(held.stable() and _leaf_matches(held.fd, held.leaf, descriptor),
              "INDEX_INPUT_INVALID")
        chunks: list[bytes] = []
        remaining = MAX_INPUT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        _need(_meta(before) == _meta(after) and held.stable()
              and _leaf_matches(held.fd, held.leaf, descriptor),
              "INDEX_INPUT_INVALID")
        _need(len(raw) <= MAX_INPUT_BYTES, "INDEX_JSON_TOO_LARGE")
        _need(len(raw) == after.st_size, "INDEX_INPUT_INVALID")
        return raw
    except IndexIdentityError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError):
        raise IndexIdentityError("INDEX_INPUT_INVALID") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if held is not None:
            held.close()


def main(argv: list[str] | None = None) -> int:
    """Compile/validate strict JSON; optional output is an atomic replacement."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) not in {2, 4} or arguments[0] not in {"compile", "validate"}:
        return _cli_error("INDEX_CLI_USAGE")
    if len(arguments) == 4 and arguments[2] != "--output":
        return _cli_error("INDEX_CLI_USAGE")
    input_path = Path(arguments[1])
    output_path = Path(arguments[3]) if len(arguments) == 4 else None
    try:
        raw = _read_bounded(input_path)
        packet = compile_packet(raw)
        if output_path is not None:
            write_packet_atomic(packet, output_path)
        else:
            sys.stdout.buffer.write(encode_packet(packet))
            sys.stdout.buffer.flush()
        return 0
    except IndexIdentityError as exc:
        return _cli_error(exc.code)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return _cli_error("INDEX_INPUT_INVALID")


if __name__ == "__main__":
    raise SystemExit(main())
