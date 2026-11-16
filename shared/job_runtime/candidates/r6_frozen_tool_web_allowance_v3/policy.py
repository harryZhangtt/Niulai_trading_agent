"""Disabled, provider-free R6 frozen web allowance v3 policy.

This module validates and translates a sealed common logical contract.  It does
not invoke a provider, perform network I/O, or integrate with a runner.  A local
reservation is created before a caller may use the returned native input.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
from pathlib import Path
import time
from typing import Any, Iterable, Mapping, TypedDict
from urllib.parse import urlsplit

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[3]
_MANIFEST = _HERE / "policy-manifest-v3.json"
_MANIFEST_SCHEMA = _HERE / "policy-manifest-v3.schema.json"
_LOGICAL_SCHEMA = _HERE / "logical-request-v3.schema.json"
_TRANSLATION_SCHEMA = _HERE / "translation-receipt-v3.schema.json"
_SETTLEMENT_SCHEMA = _HERE / "settlement-receipt-v3.schema.json"

_PINNED_LOCAL = {
    _MANIFEST: "298dce6f02accc92acf109fe99e65d1bdda6712c3172d1299bde21d10e211d61",
    _MANIFEST_SCHEMA: "7d916861776eaea1c115ba6c4e3e022381abb71c42d5fa31baba91eb59b486fa",
    _LOGICAL_SCHEMA: "347abd0a5b22e3d582215534ee0e2f99b5b9be337cb6661a3e4e796673877d3b",
    _TRANSLATION_SCHEMA: "788909a69d46cd77026ac1a4ae99b49e3b8a3b234ad5650e988e0b5cf318246f",
    _SETTLEMENT_SCHEMA: "ba44da84d9f93c3eccb73b0f0d8795e3dda421f31665a5a123cdedadc9e25bf1",
}

ALLOWED_DOMAINS = ("www.microsoft.com", "www.sec.gov")
EVIDENCE_PREFIXES = {
    "www.microsoft.com": ("/en-us/Investor/",),
    "www.sec.gov": ("/Archives/", "/cgi-bin/", "/edgar/", "/files/", "/ixviewer/"),
}
FETCH_PROMPT = (
    "Extract only source text relevant to the frozen research question. Preserve "
    "document title, publication or filing date, section or page locator, and exact "
    "quotations. Do not infer or summarize unsupported facts."
)
SEARCH_CEILING = 2
FETCH_CEILING = 6
WEB_POLICY_SEARCH_ALIAS = 2
CAPTURED_FETCH_BYTES_MAX = 65536
PROVIDER_CALL_SECONDS_MAX = 600
CELL_WINDOW_SECONDS = 1800


class PolicyError(ValueError):
    """Stable, secret-safe fail-closed error code."""


class TranslationReceipt(TypedDict):
    kind: str
    version: int
    reservation_id: str
    provider: str
    operation: str
    logical_input_sha256: str
    tool_identity: str
    native_input: dict[str, Any]
    fixed_prompt_sha256: str
    dispatch_reserved: bool
    search_dispatch_ordinal: int
    fetch_dispatch_ordinal: int
    web_policy_search_alias_value: int
    live_invocation_performed: bool


class SettlementReceipt(TypedDict):
    kind: str
    version: int
    reservation_id: str
    provider: str
    operation: str
    outcome: str
    reason: str
    consumed: bool
    retry: bool
    replay: bool
    status_query: bool
    captured_result_bytes: int
    captured_result_sha256: str
    provider_call_seconds: int
    cell_elapsed_seconds: float
    final_url: str | None
    redirect_count: int | None
    provider_observations: dict[str, Any]


def _deny(code: str) -> None:
    raise PolicyError(code)


def _pairs(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _deny("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(_value: str) -> Any:
    _deny("NONFINITE_JSON_VALUE")


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _load_canonical(path: Path) -> tuple[bytes, Any]:
    raw = _read_bytes(path)
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _deny("INVALID_CANONICAL_JSON")
    canonical = (_canonical(value) + "\n").encode("ascii")
    if raw != canonical:
        _deny("NONCANONICAL_JSON_BYTES")
    return raw, value


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        _deny("VALUE_NOT_CANONICALIZABLE")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _exact_schema(value: Any) -> dict[str, Any]:
    if type(value) is dict:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {key: _exact_schema(value[key]) for key in sorted(value)},
            "required": sorted(value),
        }
    if type(value) is list:
        return {
            "type": "array",
            "prefixItems": [_exact_schema(item) for item in value],
            "items": False,
            "minItems": len(value),
            "maxItems": len(value),
        }
    return {"const": value}


def _exact_mapping(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _deny(code)
    return value


def verify_candidate_sources() -> dict[str, Any]:
    """Verify the one internal policy and fixed workspace source pins.

    There is intentionally no caller-supplied policy path or workspace root.
    """
    loaded: dict[Path, tuple[bytes, Any]] = {}
    for path, digest in _PINNED_LOCAL.items():
        raw, value = _load_canonical(path)
        if _sha(raw) != digest:
            _deny("LOCAL_CONTRACT_VERSION_DRIFT")
        loaded[path] = (raw, value)
    manifest = loaded[_MANIFEST][1]
    expected_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:trading-agent:r6-frozen-tool-web-allowance:manifest-v3",
        **_exact_schema(manifest),
    }
    if loaded[_MANIFEST_SCHEMA][1] != expected_schema:
        _deny("STRICT_SCHEMA_MANIFEST_MISMATCH")
    if manifest["activation"] is not False or manifest["provider_free"] is not True:
        _deny("UNREVIEWED_ACTIVATION")
    ceilings = manifest["logical_policy"]["ceilings"]
    if ceilings != {
        "web_search_per_cell": 2,
        "web_fetch_per_cell": 6,
        "web_policy": 2,
        "web_policy_semantics": "CONSISTENCY_ALIAS_FOR_WEB_SEARCH_NOT_AGGREGATE",
    }:
        _deny("CEILING_SEMANTICS_DRIFT")
    if ceilings["web_policy"] != ceilings["web_search_per_cell"]:
        _deny("WEB_POLICY_ALIAS_DRIFT")
    for ref in manifest["source_pins"]:
        target = _ROOT / ref["path"]
        if not target.is_file() or target.is_symlink():
            _deny("SOURCE_PIN_MISSING_OR_SYMLINK")
        raw = _read_bytes(target)
        if len(raw) != ref["bytes"] or _sha(raw) != ref["sha256"]:
            _deny("SOURCE_PIN_DRIFT")
    return {
        "version": manifest["version"],
        "status": manifest["status"],
        "activation": False,
        "provider_free": True,
        "manifest_sha256": _PINNED_LOCAL[_MANIFEST],
        "schema_sha256": _PINNED_LOCAL[_MANIFEST_SCHEMA],
        "source_pins_verified": len(manifest["source_pins"]),
        "v1_history": manifest["history"]["v1"],
        "v2_history": manifest["history"]["v2"],
        "independent_review": manifest["authority"]["implementation_independent_review"],
        "adoption_review": manifest["authority"]["adoption_review"],
    }


def verify_exact_manifest(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or raw != _read_bytes(_MANIFEST):
        _deny("CALLER_SELECTED_POLICY_DENIED")
    return verify_candidate_sources()


def _utf8(value: Any, code: str, *, nonempty: bool = True) -> str:
    if type(value) is not str or (nonempty and value == ""):
        _deny(code)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _deny(code)
    return value


def _url_parts(url: Any, *, require_evidence_path: bool) -> tuple[str, str]:
    value = _utf8(url, "URL_INVALID")
    if any(char.isspace() for char in value):
        _deny("URL_INVALID")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        _deny("URL_INVALID")
    if parsed.scheme != "https" or not parsed.netloc or parsed.hostname is None:
        _deny("HTTPS_REQUIRED")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        _deny("USERINFO_DENIED")
    if parsed.fragment:
        _deny("FRAGMENT_DENIED")
    if port not in (None, 443):
        _deny("NON_DEFAULT_PORT_DENIED")
    host = parsed.hostname
    try:
        host.encode("ascii")
    except UnicodeEncodeError:
        _deny("IDN_OR_NONASCII_HOST_DENIED")
    raw_authorities = {host, host + ":443"}
    if parsed.netloc not in raw_authorities:
        _deny("HOST_CASE_OR_AUTHORITY_DRIFT")
    lower = host.lower()
    if lower == "localhost" or lower.endswith((".local", ".internal", ".localhost")):
        _deny("PRIVATE_LOCAL_INTERNAL_HOST_DENIED")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        _deny("LITERAL_IP_DENIED")
    if host not in ALLOWED_DOMAINS:
        _deny("EXACT_HOST_DENIED")
    path = parsed.path or "/"
    if require_evidence_path and not any(path.startswith(prefix) for prefix in EVIDENCE_PREFIXES[host]):
        _deny("EVIDENCE_PATH_DENIED")
    return host, path


def validate_logical_request(value: Any) -> dict[str, Any]:
    if type(value) is not dict or "operation" not in value:
        _deny("LOGICAL_REQUEST_SHAPE")
    operation = value["operation"]
    if operation == "web_search":
        request = _exact_mapping(value, {"operation", "query", "allowed_domains"}, "EXTRA_PROVIDER_OPTION_DENIED")
        query = _utf8(request["query"], "QUERY_MUST_BE_NONEMPTY_UTF8")
        if type(request["allowed_domains"]) is not list or request["allowed_domains"] != list(ALLOWED_DOMAINS):
            _deny("ALLOWED_DOMAINS_DRIFT")
        return {"operation": operation, "query": query, "allowed_domains": list(ALLOWED_DOMAINS)}
    if operation == "web_fetch":
        request = _exact_mapping(value, {"operation", "url", "prompt"}, "EXTRA_PROVIDER_OPTION_DENIED")
        if request["prompt"] != FETCH_PROMPT:
            _deny("FETCH_PROMPT_DRIFT")
        _url_parts(request["url"], require_evidence_path=True)
        return {"operation": operation, "url": request["url"], "prompt": FETCH_PROMPT}
    _deny("UNKNOWN_OPERATION")


def classify_search_result_url(url: str) -> str:
    host, path = _url_parts(url, require_evidence_path=False)
    if any(path.startswith(prefix) for prefix in EVIDENCE_PREFIXES[host]):
        return "EVIDENCE_ELIGIBLE"
    return "OBSERVED_NOT_EVIDENCE_NOT_FETCHABLE"


def _native_translation(provider: str, request: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if provider not in ("claude", "codex"):
        _deny("UNKNOWN_PROVIDER")
    if request["operation"] == "web_search":
        if provider == "claude":
            return "claude_code.WebSearch", {
                "query": request["query"],
                "allowed_domains": list(ALLOWED_DOMAINS),
            }
        return "native_tools.web__run", {
            "search_query": [{"q": request["query"], "domains": list(ALLOWED_DOMAINS)}],
            "response_length": "long",
        }
    if provider == "claude":
        return "claude_code.WebFetch", {"url": request["url"], "prompt": FETCH_PROMPT}
    return "native_tools.web__run", {
        "open": [{"ref_id": request["url"]}],
        "response_length": "long",
    }


def _observations(value: Any) -> dict[str, Any]:
    keys = {"http_requests", "cache", "ranking", "result_count", "equality_claimed"}
    item = _exact_mapping(value, keys, "PROVIDER_OBSERVATIONS_SHAPE")
    for key in ("http_requests", "result_count"):
        if item[key] is not None and (type(item[key]) is not int or item[key] < 0):
            _deny("PROVIDER_OBSERVATIONS_VALUE")
    for key in ("cache", "ranking"):
        if item[key] is not None:
            _utf8(item[key], "PROVIDER_OBSERVATIONS_VALUE")
    if item["equality_claimed"] is not False:
        _deny("PROVIDER_INTERNAL_EQUALITY_CLAIM_DENIED")
    return dict(item)


class CellLedger:
    """Fixed per-cell dispatch ledger with no caller-configurable policy or limits."""

    def __init__(self) -> None:
        self._started = time.monotonic()
        self._search = 0
        self._fetch = 0
        self._sequence = 0
        self._records: dict[str, dict[str, Any]] = {}
        self._outcomes = {"PASS": 0, "FAIL": 0, "UNKNOWN": 0}

    def _elapsed(self) -> float:
        return max(0.0, time.monotonic() - self._started)

    def reserve_and_translate(self, provider: str, logical_request: Any) -> TranslationReceipt:
        request = validate_logical_request(logical_request)
        if self._elapsed() > CELL_WINDOW_SECONDS:
            _deny("CELL_WINDOW_EXCEEDED")
        operation = request["operation"]
        if operation == "web_search":
            if self._search >= SEARCH_CEILING:
                _deny("SEARCH_DISPATCH_CEILING_EXCEEDED")
            self._search += 1
        else:
            if self._fetch >= FETCH_CEILING:
                _deny("FETCH_DISPATCH_CEILING_EXCEEDED")
            self._fetch += 1
        self._sequence += 1
        reservation_id = f"r6wa3-{self._sequence}"
        tool, native = _native_translation(provider, request)
        receipt: TranslationReceipt = {
            "kind": "r6_frozen_tool_web_translation_v3",
            "version": 3,
            "reservation_id": reservation_id,
            "provider": provider,
            "operation": operation,
            "logical_input_sha256": _sha(_canonical(request).encode("ascii")),
            "tool_identity": tool,
            "native_input": native,
            "fixed_prompt_sha256": _sha(FETCH_PROMPT.encode("utf-8")),
            "dispatch_reserved": True,
            "search_dispatch_ordinal": self._search,
            "fetch_dispatch_ordinal": self._fetch,
            "web_policy_search_alias_value": WEB_POLICY_SEARCH_ALIAS,
            "live_invocation_performed": False,
        }
        self._records[reservation_id] = {
            "translation": receipt,
            "request": request,
            "settled": False,
        }
        return receipt

    def settle(self, reservation_id: str, report: Any, *, captured_result: bytes = b"") -> SettlementReceipt:
        if type(reservation_id) is not str or reservation_id not in self._records:
            _deny("UNKNOWN_RESERVATION")
        record = self._records[reservation_id]
        if record["settled"]:
            _deny("RETRY_REPLAY_STATUS_QUERY_DENIED")
        record["settled"] = True
        try:
            if type(captured_result) is not bytes:
                _deny("CAPTURED_RESULT_MUST_BE_BYTES")
            item = _exact_mapping(
                report,
                {"outcome", "reason", "provider_call_seconds", "final_url", "redirect_chain", "provider_observations"},
                "SETTLEMENT_REPORT_SHAPE",
            )
            if item["outcome"] not in ("PASS", "FAIL", "UNKNOWN"):
                _deny("SETTLEMENT_OUTCOME")
            reason = _utf8(item["reason"], "SETTLEMENT_REASON")
            seconds = item["provider_call_seconds"]
            if type(seconds) is not int or seconds < 0:
                _deny("PROVIDER_CALL_SECONDS_INVALID")
            observations = _observations(item["provider_observations"])
            final_url = item["final_url"]
            redirects = item["redirect_chain"]
            if redirects is not None and (
                type(redirects) is not list or not all(type(value) is str for value in redirects)
            ):
                _deny("REDIRECT_EVIDENCE_INVALID")
            elapsed = self._elapsed()
            outcome = item["outcome"]
            if seconds > PROVIDER_CALL_SECONDS_MAX:
                outcome, reason = "UNKNOWN", "PROVIDER_TIMEOUT_UNKNOWN_NO_REPLAY"
            elif elapsed > CELL_WINDOW_SECONDS:
                outcome, reason = "UNKNOWN", "CELL_WINDOW_UNKNOWN_NO_REPLAY"
            elif record["translation"]["operation"] == "web_fetch":
                if len(captured_result) > CAPTURED_FETCH_BYTES_MAX:
                    outcome, reason = "UNKNOWN", "CAPTURED_RESULT_OVERSIZE_UNKNOWN_NO_REPLAY"
                elif outcome == "PASS":
                    requested_url = record["request"]["url"]
                    if final_url is None or redirects is None:
                        outcome, reason = "UNKNOWN", "FINAL_ORIGIN_UNAVAILABLE_UNKNOWN_NO_REPLAY"
                    elif redirects or final_url != requested_url:
                        outcome, reason = "UNKNOWN", "REDIRECT_OR_FINAL_ORIGIN_DRIFT_UNKNOWN_NO_REPLAY"
                    else:
                        try:
                            _url_parts(final_url, require_evidence_path=True)
                        except PolicyError:
                            outcome, reason = "UNKNOWN", "FINAL_ORIGIN_POLICY_UNKNOWN_NO_REPLAY"
            elif final_url is not None or redirects is not None:
                _deny("SEARCH_FINAL_ORIGIN_FIELDS_DENIED")
            self._outcomes[outcome] += 1
            receipt: SettlementReceipt = {
                "kind": "r6_frozen_tool_web_settlement_v3",
                "version": 3,
                "reservation_id": reservation_id,
                "provider": record["translation"]["provider"],
                "operation": record["translation"]["operation"],
                "outcome": outcome,
                "reason": reason,
                "consumed": True,
                "retry": False,
                "replay": False,
                "status_query": False,
                "captured_result_bytes": len(captured_result),
                "captured_result_sha256": _sha(captured_result),
                "provider_call_seconds": seconds,
                "cell_elapsed_seconds": elapsed,
                "final_url": final_url,
                "redirect_count": None if redirects is None else len(redirects),
                "provider_observations": observations,
            }
            record["settlement"] = receipt
            return receipt
        except Exception:
            self._outcomes["UNKNOWN"] += 1
            record["settlement"] = "MALFORMED_SETTLEMENT_CONSUMED_UNKNOWN_NO_REPLAY"
            raise

    def counters(self) -> dict[str, Any]:
        return {
            "web_search_reserved": self._search,
            "web_fetch_reserved": self._fetch,
            "web_policy_search_alias": WEB_POLICY_SEARCH_ALIAS,
            "web_policy_is_aggregate": False,
            "outcomes": dict(self._outcomes),
            "reserved_total_observational_only": self._search + self._fetch,
        }
