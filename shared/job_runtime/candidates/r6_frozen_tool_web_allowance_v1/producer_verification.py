"""Independent provider-free producer verification; intentionally does not import verify."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

_HERE = Path(__file__).resolve().parent
_MANIFEST = _HERE / "owner-private-policy-manifest-v1.json"
_SCHEMA = _HERE / "owner-private-policy-manifest-v1.schema.json"


class ProducerVerificationError(ValueError):
    """Stable independent verification error."""


def _pairs(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProducerVerificationError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(_value: str) -> Any:
    raise ProducerVerificationError("NONFINITE_JSON_VALUE")


def _read(path: Path) -> tuple[bytes, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw.decode("ascii"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ProducerVerificationError("INVALID_JSON") from error
    canonical = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                   allow_nan=False) + "\n"
    ).encode("ascii")
    if raw != canonical:
        raise ProducerVerificationError("NONCANONICAL_JSON")
    return raw, value


def _schema(value: Any) -> dict[str, Any]:
    if type(value) is dict:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {key: _schema(value[key]) for key in sorted(value)},
            "required": sorted(value),
        }
    if type(value) is list:
        return {
            "type": "array",
            "prefixItems": [_schema(item) for item in value],
            "items": False,
            "minItems": len(value),
            "maxItems": len(value),
        }
    return {"const": value}


def build_receipt() -> dict[str, Any]:
    manifest_raw, manifest = _read(_MANIFEST)
    schema_raw, schema = _read(_SCHEMA)
    expected_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:trading-agent:r6-frozen-tool-web-allowance:manifest-v1",
        **_schema(manifest),
    }
    if schema != expected_schema:
        raise ProducerVerificationError("STRICT_SCHEMA_MISMATCH")
    expected_tools = {
        "policy_id": "FROZEN-COMMON-READONLY-TOOLS-V1",
        "roster": [
            {"name": "web_search", "version": "provider-native-frozen-v1", "call_ceiling": 2},
            {"name": "web_fetch", "version": "provider-native-frozen-v1", "call_ceiling": 6},
        ],
    }
    expected_web = {
        "policy_id": "FROZEN-OFFICIAL-DOMAINS-ONLY-V1",
        "mode": "official-domains-only",
        "call_ceiling": 2,
    }
    if manifest["frozen_bindings"]["tool_policy"] != expected_tools:
        raise ProducerVerificationError("TOOL_POLICY_DRIFT")
    if manifest["frozen_bindings"]["web_policy"] != expected_web:
        raise ProducerVerificationError("WEB_POLICY_DRIFT")
    if manifest["official_domain_policy"]["exact_allowed_hosts"] != []:
        raise ProducerVerificationError("UNREVIEWED_DOMAINS")
    if manifest["matched_roster"] != {
        "established": False,
        "executable": False,
        "same_logical_names_only": True,
        "same_operation_semantics": False,
        "same_response_representation": False,
        "same_redirect_domain_method_auth_bounds": False,
    }:
        raise ProducerVerificationError("MATCHED_ROSTER_CLAIM_DRIFT")
    if manifest["activation"] is not False or manifest["activation_gate"]["admit_any_call_now"] is not False:
        raise ProducerVerificationError("ACTIVATION_DRIFT")
    if manifest["operation_policy"]["bytedcli"] != "DENY":
        raise ProducerVerificationError("BYTEDCLI_DRIFT")
    return {
        "version": "r6-frozen-tool-web-allowance-producer-verification-v1",
        "status": "OPEN",
        "provider_free": True,
        "activation": False,
        "countable_now": False,
        "manifest": {
            "bytes": len(manifest_raw),
            "sha256": hashlib.sha256(manifest_raw).hexdigest(),
        },
        "schema": {
            "bytes": len(schema_raw),
            "sha256": hashlib.sha256(schema_raw).hexdigest(),
            "dialect": "https://json-schema.org/draft/2020-12/schema",
            "closed_objects": True,
        },
        "frozen_values_verified": True,
        "matched_executable_roster_verified": False,
        "effects_executed": {
            "account": False,
            "business": False,
            "credential": False,
            "email": False,
            "host": False,
            "network": False,
            "private_state": False,
            "provider": False,
        },
        "verdict": "OPEN_MATCHED_EXECUTABLE_ROSTER_NOT_ESTABLISHED",
    }


if __name__ == "__main__":
    print(json.dumps(build_receipt(), sort_keys=True, separators=(",", ":")))
