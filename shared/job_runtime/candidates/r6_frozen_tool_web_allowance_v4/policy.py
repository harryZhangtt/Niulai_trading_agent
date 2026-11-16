"""Disabled, provider-free R6 frozen web allowance v4 policy.

This additive successor closes the five v3 review findings. It validates and
translates a sealed common logical contract, but performs no provider call,
network I/O, runner integration, or active-runtime mutation.
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, Iterable, Mapping, TypedDict
from urllib.parse import quote, unquote_to_bytes, urlsplit

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[3]
_MANIFEST = _HERE / "policy-manifest-v4.json"
_MANIFEST_SCHEMA = _HERE / "policy-manifest-v4.schema.json"
_LOGICAL_SCHEMA = _HERE / "logical-request-v4.schema.json"
_TRANSLATION_SCHEMA = _HERE / "translation-receipt-v4.schema.json"
_SETTLEMENT_SCHEMA = _HERE / "settlement-receipt-v4.schema.json"

_PINNED_LOCAL = {
    _MANIFEST: "249b927d2df2e3a3280a629dcbd0bc6d03d457d6852b6849aab570f193b0b244",
    _MANIFEST_SCHEMA: "9c871bf075f1ef194ff7774c557fefa0d758cdcbe271ae7af78395eade38ef27",
    _LOGICAL_SCHEMA: "7b3f48697a1a206a4ae4ad4e16c18545cdaba968a2cf4e60547af5bd7ece5727",
    _TRANSLATION_SCHEMA: "845cb403876589c5ed2e4c8dc67f94d9f9715a68c00b447aa2fae1dd0ae6f13f",
    _SETTLEMENT_SCHEMA: "a86df22b1960049b1428030339bb7d2c214ca80027a4ccb871074d54c35c9ac6",
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
_PATH_SAFE = "/!$&'()*+,-.:;=@_~"
_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")


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
    translation_receipt_sha256: str
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
    requested_url: str | None
    final_url: str | None
    final_url_matches_request: bool | None
    final_url_evidence_eligible: bool | None
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


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        _deny("VALUE_NOT_CANONICALIZABLE")


def _load_canonical(path: Path) -> tuple[bytes, Any]:
    raw = _read_bytes(path)
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _deny("INVALID_CANONICAL_JSON")
    if raw != (_canonical(value) + "\n").encode("ascii"):
        _deny("NONCANONICAL_JSON_BYTES")
    return raw, value


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _exact_schema(value: Any) -> dict[str, Any]:
    if type(value) is dict:
        properties = {key: _exact_schema(value[key]) for key in sorted(value)}
        return {"type": "object", "additionalProperties": False, "properties": properties, "required": sorted(properties)}
    if type(value) is list:
        return {"type": "array", "prefixItems": [_exact_schema(item) for item in value], "items": False, "minItems": len(value), "maxItems": len(value)}
    return {"const": value}


def _exact_mapping(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _deny(code)
    return value


def verify_candidate_sources() -> dict[str, Any]:
    """Verify sealed local contracts and workspace pins without caller-selected roots."""
    loaded: dict[Path, tuple[bytes, Any]] = {}
    for path, digest in _PINNED_LOCAL.items():
        raw, value = _load_canonical(path)
        if _sha(raw) != digest:
            _deny("LOCAL_CONTRACT_VERSION_DRIFT")
        loaded[path] = (raw, value)
    manifest = loaded[_MANIFEST][1]
    expected_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:trading-agent:r6-frozen-tool-web-allowance:manifest-v4",
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
    } or ceilings["web_policy"] != ceilings["web_search_per_cell"]:
        _deny("CEILING_SEMANTICS_DRIFT")
    authority = manifest["authority"]
    if authority["owner_adoption"]["sha256"] != "1d62a7093564ec3ee7f147ca8471f13013ea7820a69c58851ffb88e18e8b5c81":
        _deny("OWNER_ADOPTION_BINDING_DRIFT")
    if authority["owner_adoption_independent_review"]["sha256"] != "ecf5026bebffa359d8ba0572d201f03a925bee5db7f29739e027ef94d5e90620":
        _deny("OWNER_REVIEW_BINDING_DRIFT")
    if authority["predecessor_open_review"]["sha256"] != "3514cbb6a65378ceeea7197ee5d52839b3c7be4b338b049271607752ff15eac4":
        _deny("V3_OPEN_REVIEW_BINDING_DRIFT")
    for ref in manifest["source_pins"]:
        target = _ROOT / ref["path"]
        if not target.is_file() or target.is_symlink():
            _deny("SOURCE_PIN_MISSING_OR_SYMLINK")
        raw = _read_bytes(target)
        if len(raw) != ref["bytes"] or _sha(raw) != ref["sha256"]:
            _deny("SOURCE_PIN_DRIFT")
    return {
        "version": manifest["version"], "status": manifest["status"], "activation": False,
        "provider_free": True, "manifest_sha256": _PINNED_LOCAL[_MANIFEST],
        "schema_sha256": _PINNED_LOCAL[_MANIFEST_SCHEMA], "source_pins_verified": len(manifest["source_pins"]),
        "v1_history": manifest["history"]["v1"], "v2_history": manifest["history"]["v2"],
        "v3_history": manifest["history"]["v3"],
        "independent_review": authority["implementation_independent_review"],
        "owner_adoption_review": authority["owner_adoption_independent_review"]["verdict"],
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


def _has_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _canonical_path(path: str) -> str:
    if not path.startswith("/") or "\\" in path or _has_control(path):
        _deny("NONCANONICAL_PATH_DENIED")
    if "//" in path:
        _deny("REPEATED_SLASH_DENIED")
    if "%" in path:
        # Deny all path escaping: this closes single/double encoding, encoded
        # separators, encoded dots, malformed escapes, and normalization drift.
        _deny("PERCENT_ENCODING_IN_PATH_DENIED")
    segments = path.split("/")
    if any(segment in (".", "..") for segment in segments):
        _deny("DOT_SEGMENT_DENIED")
    try:
        decoded = unquote_to_bytes(path).decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _deny("NONCANONICAL_PATH_DENIED")
    if "\\" in decoded or _has_control(decoded) or _PERCENT_ESCAPE.search(decoded):
        _deny("NONCANONICAL_PATH_DENIED")
    canonical = quote(decoded, safe=_PATH_SAFE, encoding="utf-8", errors="strict")
    if canonical != path:
        _deny("NONCANONICAL_PATH_DENIED")
    return canonical


def _url_parts(url: Any, *, require_evidence_path: bool) -> tuple[str, str]:
    value = _utf8(url, "URL_INVALID")
    if _has_control(value) or "\\" in value:
        _deny("URL_INVALID")
    try:
        parsed = urlsplit(value, allow_fragments=True)
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
        host.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _deny("IDN_OR_NONASCII_HOST_DENIED")
    if parsed.netloc not in {host, host + ":443"}:
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
    path = _canonical_path(parsed.path or "/")
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


def _validate_provider(provider: Any) -> str:
    if type(provider) is not str or provider not in ("claude", "codex"):
        _deny("UNKNOWN_PROVIDER")
    return provider


def _native_translation(provider: str, request: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if request["operation"] == "web_search":
        if provider == "claude":
            return "claude_code.WebSearch", {"query": request["query"], "allowed_domains": list(ALLOWED_DOMAINS)}
        return "native_tools.web__run", {"search_query": [{"q": request["query"], "domains": list(ALLOWED_DOMAINS)}], "response_length": "long"}
    if provider == "claude":
        return "claude_code.WebFetch", {"url": request["url"], "prompt": FETCH_PROMPT}
    return "native_tools.web__run", {"open": [{"ref_id": request["url"]}], "response_length": "long"}


def _observations(value: Any) -> dict[str, Any]:
    item = _exact_mapping(value, {"http_requests", "cache", "ranking", "result_count", "equality_claimed"}, "PROVIDER_OBSERVATIONS_SHAPE")
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
    """Thread-safe fixed per-cell dispatch ledger with immutable byte receipts."""

    def __init__(self) -> None:
        self._started = time.monotonic()
        self._search = 0
        self._fetch = 0
        self._sequence = 0
        self._records: dict[str, dict[str, Any]] = {}
        self._outcomes = {"PASS": 0, "FAIL": 0, "UNKNOWN": 0}
        self._lock = threading.RLock()

    def _elapsed(self) -> float:
        return max(0.0, time.monotonic() - self._started)

    def reserve_and_translate(self, provider: str, logical_request: Any) -> TranslationReceipt:
        # All caller-controlled fields are validated before the reservation lock;
        # invalid providers/requests consume zero and produce no receipt.
        provider = _validate_provider(provider)
        request = validate_logical_request(logical_request)
        tool, native = _native_translation(provider, request)
        with self._lock:
            if self._elapsed() > CELL_WINDOW_SECONDS:
                _deny("CELL_WINDOW_EXCEEDED")
            operation = request["operation"]
            if operation == "web_search" and self._search >= SEARCH_CEILING:
                _deny("SEARCH_DISPATCH_CEILING_EXCEEDED")
            if operation == "web_fetch" and self._fetch >= FETCH_CEILING:
                _deny("FETCH_DISPATCH_CEILING_EXCEEDED")
            next_search = self._search + (operation == "web_search")
            next_fetch = self._fetch + (operation == "web_fetch")
            next_sequence = self._sequence + 1
            reservation_id = f"r6wa4-{next_sequence}"
            receipt: TranslationReceipt = {
                "kind": "r6_frozen_tool_web_translation_v4", "version": 4,
                "reservation_id": reservation_id, "provider": provider, "operation": operation,
                "logical_input_sha256": _sha(_canonical(request).encode("ascii")),
                "tool_identity": tool, "native_input": copy.deepcopy(native),
                "fixed_prompt_sha256": _sha(FETCH_PROMPT.encode("utf-8")), "dispatch_reserved": True,
                "search_dispatch_ordinal": next_search, "fetch_dispatch_ordinal": next_fetch,
                "web_policy_search_alias_value": WEB_POLICY_SEARCH_ALIAS, "live_invocation_performed": False,
            }
            # Canonical bytes are the immutable reservation receipt. Build them
            # before publishing any counter increment, then publish record and
            # counters under one lock so observers can never see capacity loss.
            receipt_bytes = (_canonical(receipt) + "\n").encode("ascii")
            record = {
                "translation_bytes": receipt_bytes,
                "translation_sha256": _sha(receipt_bytes),
                "request": copy.deepcopy(request), "settled": False, "settlement_bytes": None,
            }
            self._records[reservation_id] = record
            self._search = next_search
            self._fetch = next_fetch
            self._sequence = next_sequence
            return copy.deepcopy(receipt)

    def _finalize(self, record: dict[str, Any], receipt: SettlementReceipt) -> SettlementReceipt:
        raw = (_canonical(receipt) + "\n").encode("ascii")
        record["settlement_bytes"] = raw
        self._outcomes[receipt["outcome"]] += 1
        return copy.deepcopy(receipt)

    def settle(self, reservation_id: str, report: Any, *, captured_result: bytes = b"") -> SettlementReceipt:
        with self._lock:
            if type(reservation_id) is not str or reservation_id not in self._records:
                _deny("UNKNOWN_RESERVATION")
            record = self._records[reservation_id]
            if record["settled"]:
                _deny("RETRY_REPLAY_STATUS_QUERY_DENIED")
            record["settled"] = True
            translation = json.loads(record["translation_bytes"].decode("ascii"))
            request = record["request"]
            elapsed = self._elapsed()
            try:
                if type(captured_result) is not bytes:
                    _deny("CAPTURED_RESULT_MUST_BE_BYTES")
                item = _exact_mapping(report, {"outcome", "reason", "provider_call_seconds", "final_url", "redirect_chain", "provider_observations"}, "SETTLEMENT_REPORT_SHAPE")
                if item["outcome"] not in ("PASS", "FAIL", "UNKNOWN"):
                    _deny("SETTLEMENT_OUTCOME")
                reason = _utf8(item["reason"], "SETTLEMENT_REASON")
                seconds = item["provider_call_seconds"]
                if type(seconds) is not int or seconds < 0:
                    _deny("PROVIDER_CALL_SECONDS_INVALID")
                observations = _observations(item["provider_observations"])
                final_url = item["final_url"]
                redirects = item["redirect_chain"]
                if redirects is not None and (type(redirects) is not list or not all(type(value) is str for value in redirects)):
                    _deny("REDIRECT_EVIDENCE_INVALID")
                outcome = item["outcome"]
                operation = translation["operation"]
                requested_url = request.get("url")
                final_matches: bool | None = None
                final_eligible: bool | None = None
                if seconds > PROVIDER_CALL_SECONDS_MAX:
                    outcome, reason = "UNKNOWN", "PROVIDER_TIMEOUT_UNKNOWN_NO_REPLAY"
                elif elapsed > CELL_WINDOW_SECONDS:
                    outcome, reason = "UNKNOWN", "CELL_WINDOW_UNKNOWN_NO_REPLAY"
                elif operation == "web_fetch" and len(captured_result) > CAPTURED_FETCH_BYTES_MAX:
                    outcome, reason = "UNKNOWN", "CAPTURED_RESULT_OVERSIZE_UNKNOWN_NO_REPLAY"
                elif operation == "web_search":
                    if final_url is not None or redirects is not None:
                        _deny("SEARCH_FINAL_ORIGIN_FIELDS_DENIED")
                elif outcome == "FAIL":
                    if captured_result or final_url is not None or redirects is not None:
                        _deny("FAIL_RESULT_EVIDENCE_DENIED")
                elif final_url is None or redirects is None:
                    outcome, reason = "UNKNOWN", "FINAL_ORIGIN_UNAVAILABLE_UNKNOWN_NO_REPLAY"
                else:
                    final_matches = final_url == requested_url
                    try:
                        _url_parts(final_url, require_evidence_path=True)
                    except PolicyError:
                        final_eligible = False
                        outcome, reason = "UNKNOWN", "FINAL_ORIGIN_POLICY_UNKNOWN_NO_REPLAY"
                    else:
                        final_eligible = True
                        if redirects or not final_matches:
                            outcome, reason = "UNKNOWN", "REDIRECT_OR_FINAL_ORIGIN_DRIFT_UNKNOWN_NO_REPLAY"
                receipt: SettlementReceipt = {
                    "kind": "r6_frozen_tool_web_settlement_v4", "version": 4,
                    "reservation_id": reservation_id, "translation_receipt_sha256": record["translation_sha256"],
                    "provider": translation["provider"], "operation": translation["operation"],
                    "outcome": outcome, "reason": reason, "consumed": True,
                    "retry": False, "replay": False, "status_query": False,
                    "captured_result_bytes": len(captured_result), "captured_result_sha256": _sha(captured_result),
                    "provider_call_seconds": seconds, "cell_elapsed_seconds": elapsed,
                    "requested_url": requested_url, "final_url": final_url,
                    "final_url_matches_request": final_matches, "final_url_evidence_eligible": final_eligible,
                    "redirect_count": None if redirects is None else len(redirects),
                    "provider_observations": observations,
                }
                return self._finalize(record, receipt)
            except Exception:
                receipt = {
                    "kind": "r6_frozen_tool_web_settlement_v4", "version": 4,
                    "reservation_id": reservation_id, "translation_receipt_sha256": record["translation_sha256"],
                    "provider": translation["provider"], "operation": translation["operation"],
                    "outcome": "UNKNOWN", "reason": "MALFORMED_SETTLEMENT_CONSUMED_UNKNOWN_NO_REPLAY",
                    "consumed": True, "retry": False, "replay": False, "status_query": False,
                    "captured_result_bytes": 0, "captured_result_sha256": _sha(b""),
                    "provider_call_seconds": 0, "cell_elapsed_seconds": elapsed,
                    "requested_url": request.get("url"), "final_url": None,
                    "final_url_matches_request": None, "final_url_evidence_eligible": None,
                    "redirect_count": None,
                    "provider_observations": {"http_requests": None, "cache": None, "ranking": None, "result_count": None, "equality_claimed": False},
                }
                self._finalize(record, receipt)
                raise

    def receipt_state(self, reservation_id: str) -> dict[str, Any]:
        """Return copies for reconciliation; stored canonical receipt bytes stay immutable."""
        with self._lock:
            if type(reservation_id) is not str or reservation_id not in self._records:
                _deny("UNKNOWN_RESERVATION")
            record = self._records[reservation_id]
            return {
                "translation": json.loads(record["translation_bytes"].decode("ascii")),
                "translation_sha256": record["translation_sha256"],
                "settlement": None if record["settlement_bytes"] is None else json.loads(record["settlement_bytes"].decode("ascii")),
            }

    def counters(self) -> dict[str, Any]:
        with self._lock:
            reserved = self._search + self._fetch
            settled = sum(self._outcomes.values())
            return {
                "web_search_reserved": self._search, "web_fetch_reserved": self._fetch,
                "web_policy_search_alias": WEB_POLICY_SEARCH_ALIAS, "web_policy_is_aggregate": False,
                "outcomes": dict(self._outcomes), "reserved_total_observational_only": reserved,
                "reservation_receipts": len(self._records), "settled_total": settled,
                "unsettled_total": reserved - settled, "unreceipted_capacity_loss": reserved - len(self._records),
            }
