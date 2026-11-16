"""Distinct provider-free producer verification; intentionally does not import policy."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[3]
_FILES = {
    "manifest": ("policy-manifest-v3.json", "298dce6f02accc92acf109fe99e65d1bdda6712c3172d1299bde21d10e211d61"),
    "manifest_schema": ("policy-manifest-v3.schema.json", "7d916861776eaea1c115ba6c4e3e022381abb71c42d5fa31baba91eb59b486fa"),
    "logical_schema": ("logical-request-v3.schema.json", "347abd0a5b22e3d582215534ee0e2f99b5b9be337cb6661a3e4e796673877d3b"),
    "translation_schema": ("translation-receipt-v3.schema.json", "788909a69d46cd77026ac1a4ae99b49e3b8a3b234ad5650e988e0b5cf318246f"),
    "settlement_schema": ("settlement-receipt-v3.schema.json", "ba44da84d9f93c3eccb73b0f0d8795e3dda421f31665a5a123cdedadc9e25bf1"),
}


class ProducerVerificationError(ValueError):
    pass


def _pairs(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ProducerVerificationError("DUPLICATE_JSON_KEY")
        out[key] = value
    return out


def _read(path: Path) -> tuple[bytes, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ProducerVerificationError("NONFINITE_JSON")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ProducerVerificationError("INVALID_JSON") from error
    canonical = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"
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
    loaded: dict[str, tuple[bytes, Any]] = {}
    for name, (filename, digest) in _FILES.items():
        raw, value = _read(_HERE / filename)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ProducerVerificationError("CANDIDATE_FILE_DRIFT_" + name.upper())
        loaded[name] = (raw, value)
    manifest = loaded["manifest"][1]
    expected_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:trading-agent:r6-frozen-tool-web-allowance:manifest-v3",
        **_schema(manifest),
    }
    if loaded["manifest_schema"][1] != expected_schema:
        raise ProducerVerificationError("STRICT_SCHEMA_MISMATCH")
    if manifest["activation"] is not False or any(manifest["effects"].values()):
        raise ProducerVerificationError("EFFECT_OR_ACTIVATION_DRIFT")
    policy = manifest["logical_policy"]
    if policy["ceilings"] != {
        "web_fetch_per_cell": 6,
        "web_policy": 2,
        "web_policy_semantics": "CONSISTENCY_ALIAS_FOR_WEB_SEARCH_NOT_AGGREGATE",
        "web_search_per_cell": 2,
    }:
        raise ProducerVerificationError("CEILING_DRIFT")
    if policy["allowed_domains"] != ["www.microsoft.com", "www.sec.gov"]:
        raise ProducerVerificationError("DOMAIN_DRIFT")
    if manifest["native_contracts"]["claude"]["search"]["exact_input_keys"] != ["query", "allowed_domains"]:
        raise ProducerVerificationError("CLAUDE_TRANSLATION_DRIFT")
    if manifest["native_contracts"]["codex"]["search"]["exact_input_keys"] != ["search_query", "response_length"]:
        raise ProducerVerificationError("CODEX_TRANSLATION_DRIFT")
    for ref in manifest["source_pins"]:
        target = _ROOT / ref["path"]
        if not target.is_file() or target.is_symlink():
            raise ProducerVerificationError("SOURCE_PIN_MISSING")
        raw = target.read_bytes()
        if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ProducerVerificationError("SOURCE_PIN_DRIFT")
    return {
        "version": "r6-frozen-tool-web-allowance-producer-verification-v3",
        "status": "PASS_PROVIDER_FREE_PENDING_INDEPENDENT_REVIEW_AND_ADOPTION_REVIEW",
        "activation": False,
        "provider_free": True,
        "source_pins_verified": len(manifest["source_pins"]),
        "manifest": {"bytes": len(loaded["manifest"][0]), "sha256": _FILES["manifest"][1]},
        "schemas": {name: {"bytes": len(loaded[name][0]), "sha256": _FILES[name][1]} for name in ("manifest_schema", "logical_schema", "translation_schema", "settlement_schema")},
        "history": manifest["history"],
        "effects_executed": dict(manifest["effects"]),
        "provider_internal_equality_claimed": False,
        "independent_review": "PENDING",
        "adoption_review": "PENDING",
        "verdict": "DISABLED_CANDIDATE_STRUCTURALLY_VERIFIED_NOT_ADOPTED_INTO_RUNTIME",
    }


if __name__ == "__main__":
    print(json.dumps(build_receipt(), sort_keys=True, separators=(",", ":")))
