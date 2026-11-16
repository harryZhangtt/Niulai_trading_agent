"""Dependency-free fail-closed verifier for the inert R6 allowance candidate."""
from __future__ import annotations

import hashlib
import ipaddress
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

MANIFEST_SHA256 = "feaf02c99a6eb0c03b653566cdd9d04b801f63a35691384523badc0f2e0e42ec"
SCHEMA_SHA256 = "3d05d245e40ef456679c0e9b17146aec5ceaf6e9b81520bd7fd5e15f2f41c7c5"
_HERE = Path(__file__).resolve().parent
_MANIFEST = _HERE / "owner-private-policy-manifest-v1.json"
_SCHEMA = _HERE / "owner-private-policy-manifest-v1.schema.json"


class PolicyError(ValueError):
    """Stable fail-closed policy error."""


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


def _load(path: Path) -> tuple[bytes, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw.decode("ascii"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _deny("INVALID_CANONICAL_JSON")
    canonical = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")
    if raw != canonical:
        _deny("NONCANONICAL_JSON_BYTES")
    return raw, value


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


def _verify_hash(raw: bytes, expected: str, code: str) -> None:
    if hashlib.sha256(raw).hexdigest() != expected:
        _deny(code)


def verify_canonical_policy() -> dict[str, Any]:
    manifest_raw, manifest = _load(_MANIFEST)
    schema_raw, schema = _load(_SCHEMA)
    _verify_hash(manifest_raw, MANIFEST_SHA256, "MANIFEST_VERSION_DRIFT")
    _verify_hash(schema_raw, SCHEMA_SHA256, "SCHEMA_VERSION_DRIFT")
    expected_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:trading-agent:r6-frozen-tool-web-allowance:manifest-v1",
        **_exact_schema(manifest),
    }
    if schema != expected_schema:
        _deny("STRICT_SCHEMA_MANIFEST_MISMATCH")
    if manifest["activation"] is not False:
        _deny("UNREVIEWED_ACTIVATION")
    if manifest["matched_roster"]["executable"] is not False:
        _deny("UNREVIEWED_ACTIVATION")
    if manifest["activation_gate"]["admit_any_call_now"] is not False:
        _deny("UNREVIEWED_ACTIVATION")
    if manifest["official_domain_policy"]["exact_allowed_hosts"] != []:
        _deny("UNREVIEWED_DOMAIN_ALLOWLIST")
    if (
        manifest["ceiling_semantics"]["web_policy_call_ceiling_meaning"]
        != "OPEN_UNSPECIFIED_BY_FROZEN_SOURCES"
    ):
        _deny("UNREVIEWED_CEILING_SEMANTICS")
    if (
        manifest["version_drift"]["external_provider_version_attestation_present"]
        is not False
    ):
        _deny("UNREVIEWED_PROVIDER_VERSION")
    return {
        "version": manifest["version"],
        "status": manifest["status"],
        "activation": False,
        "executable": False,
        "manifest_sha256": MANIFEST_SHA256,
        "schema_sha256": SCHEMA_SHA256,
        "open_blockers": list(manifest["open_blockers"]),
    }


def verify_exact_candidate(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or raw != _MANIFEST.read_bytes():
        _deny("CALLER_SELECTED_POLICY_DENIED")
    return verify_canonical_policy()


def _host(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        _deny("URL_INVALID")
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        _deny("URL_INVALID")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        _deny("URL_INVALID")
    if port not in (None, 443):
        _deny("URL_INVALID")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".local", ".internal")):
        _deny("INTERNAL_OR_PRIVATE_HOST")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    _deny("IP_LITERAL_DENIED")


def authorize_call(
    *,
    provider: str,
    operation: str,
    observed_tool: str,
    adapter_dispatch_count: int,
    method: str = "PROVIDER_NATIVE_READ_ONLY",
    url: str | None = None,
    domains: tuple[str, ...] = (),
    redirect_chain: tuple[str, ...] = (),
    upload_bytes: int = 0,
    auth_export: bool = False,
    argument_bytes: int = 0,
    raw_result_bytes: int = 0,
    provider_call_seconds: int = 0,
    fallback: str = "NONE",
    provider_policy_override: Any = None,
) -> None:
    manifest_raw, manifest = _load(_MANIFEST)
    _verify_hash(manifest_raw, MANIFEST_SHA256, "MANIFEST_VERSION_DRIFT")
    if provider_policy_override is not None:
        _deny("CALLER_SELECTED_POLICY_DENIED")
    if provider not in ("claude", "codex"):
        _deny("UNKNOWN_PROVIDER")
    if operation not in ("web_search", "web_fetch"):
        _deny("UNKNOWN_OPERATION")
    if method != "PROVIDER_NATIVE_READ_ONLY":
        _deny("WRITE_CAPABLE_METHOD_DENIED")
    if type(upload_bytes) is not int or upload_bytes != 0:
        _deny("UPLOAD_DENIED")
    if auth_export is not False:
        _deny("AUTH_EXPORT_DENIED")
    if fallback != "NONE":
        _deny("INTERNAL_OR_BYTEDCLI_FALLBACK_DENIED")
    limits = {
        row["name"]: row["call_ceiling"]
        for row in manifest["frozen_bindings"]["tool_policy"]["roster"]
    }
    if (
        type(adapter_dispatch_count) is not int
        or adapter_dispatch_count < 0
        or adapter_dispatch_count >= limits[operation]
    ):
        _deny("CALL_CEILING_EXCEEDED")
    if (
        type(argument_bytes) is not int
        or argument_bytes < 0
        or argument_bytes > manifest["bounds"]["operation_argument_bytes_max"]
    ):
        _deny("ARGUMENT_BOUND_EXCEEDED")
    if (
        type(raw_result_bytes) is not int
        or raw_result_bytes < 0
        or raw_result_bytes > manifest["bounds"]["captured_raw_result_bytes_max"]
    ):
        _deny("RESPONSE_BOUND_EXCEEDED")
    if (
        type(provider_call_seconds) is not int
        or provider_call_seconds < 0
        or provider_call_seconds > manifest["bounds"]["provider_call_seconds_max"]
    ):
        _deny("TIME_BOUND_EXCEEDED")
    profile = manifest["provider_profiles"][provider]
    expected = (
        profile["search_tool"] if operation == "web_search" else profile["fetch_tool"]
    )
    if observed_tool != expected:
        _deny("PROVIDER_TOOL_IDENTITY_DRIFT")
    if redirect_chain:
        for hop in redirect_chain:
            _host(hop)
        _deny("REDIRECT_OBSERVABILITY_NOT_ESTABLISHED")
    if operation == "web_fetch":
        if url is None:
            _deny("URL_REQUIRED")
        host = _host(url)
        if host not in manifest["official_domain_policy"]["exact_allowed_hosts"]:
            _deny("UNKNOWN_DOMAIN_DENIED")
    else:
        if not domains:
            _deny("OFFICIAL_DOMAIN_FILTER_REQUIRED")
        for domain in domains:
            host = _host("https://" + domain)
            if host not in manifest["official_domain_policy"]["exact_allowed_hosts"]:
                _deny("UNKNOWN_DOMAIN_DENIED")
    if profile["external_provider_schema_version"] == "UNPINNED":
        _deny("PROVIDER_VERSION_UNPINNED")
    _deny("POLICY_OPEN_UNEXECUTABLE")
