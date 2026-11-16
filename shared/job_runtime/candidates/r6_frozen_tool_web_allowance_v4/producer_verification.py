"""Distinct provider-free v4 producer verification; does not import policy."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[3]
_FILES = {
    "manifest": ("policy-manifest-v4.json", "249b927d2df2e3a3280a629dcbd0bc6d03d457d6852b6849aab570f193b0b244"),
    "manifest_schema": ("policy-manifest-v4.schema.json", "9c871bf075f1ef194ff7774c557fefa0d758cdcbe271ae7af78395eade38ef27"),
    "logical_schema": ("logical-request-v4.schema.json", "7b3f48697a1a206a4ae4ad4e16c18545cdaba968a2cf4e60547af5bd7ece5727"),
    "translation_schema": ("translation-receipt-v4.schema.json", "845cb403876589c5ed2e4c8dc67f94d9f9715a68c00b447aa2fae1dd0ae6f13f"),
    "settlement_schema": ("settlement-receipt-v4.schema.json", "a86df22b1960049b1428030339bb7d2c214ca80027a4ccb871074d54c35c9ac6"),
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
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs,
                           parse_constant=lambda _value: (_ for _ in ()).throw(ProducerVerificationError("NONFINITE_JSON")))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ProducerVerificationError("INVALID_JSON") from error
    canonical = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    if raw != canonical:
        raise ProducerVerificationError("NONCANONICAL_JSON")
    return raw, value


def _schema(value: Any) -> dict[str, Any]:
    if type(value) is dict:
        properties = {key: _schema(value[key]) for key in sorted(value)}
        return {"type": "object", "additionalProperties": False, "properties": properties, "required": sorted(properties)}
    if type(value) is list:
        return {"type": "array", "prefixItems": [_schema(item) for item in value], "items": False, "minItems": len(value), "maxItems": len(value)}
    return {"const": value}


def build_receipt() -> dict[str, Any]:
    loaded: dict[str, tuple[bytes, Any]] = {}
    for name, (filename, digest) in _FILES.items():
        raw, value = _read(_HERE / filename)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ProducerVerificationError("CANDIDATE_FILE_DRIFT_" + name.upper())
        loaded[name] = (raw, value)
    manifest = loaded["manifest"][1]
    expected = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:trading-agent:r6-frozen-tool-web-allowance:manifest-v4", **_schema(manifest)}
    if loaded["manifest_schema"][1] != expected:
        raise ProducerVerificationError("STRICT_SCHEMA_MISMATCH")
    for name in ("manifest_schema", "logical_schema", "translation_schema", "settlement_schema"):
        Draft202012Validator.check_schema(loaded[name][1])
    Draft202012Validator(loaded["manifest_schema"][1]).validate(manifest)
    if manifest["activation"] is not False or any(manifest["effects"].values()):
        raise ProducerVerificationError("EFFECT_OR_ACTIVATION_DRIFT")
    if manifest["history"] != {"successor_is_additive": True, "v1": "OPEN_PRESERVED_UNMODIFIED", "v2": "OPEN_PRESERVED_UNMODIFIED", "v3": "OPEN_PRESERVED_UNMODIFIED"}:
        raise ProducerVerificationError("OPEN_HISTORY_DRIFT")
    authority = manifest["authority"]
    if authority["owner_adoption"]["sha256"] != "1d62a7093564ec3ee7f147ca8471f13013ea7820a69c58851ffb88e18e8b5c81":
        raise ProducerVerificationError("OWNER_ADOPTION_DRIFT")
    if authority["owner_adoption_independent_review"]["sha256"] != "ecf5026bebffa359d8ba0572d201f03a925bee5db7f29739e027ef94d5e90620":
        raise ProducerVerificationError("OWNER_REVIEW_DRIFT")
    if authority["predecessor_open_review"]["sha256"] != "3514cbb6a65378ceeea7197ee5d52839b3c7be4b338b049271607752ff15eac4":
        raise ProducerVerificationError("V3_REVIEW_DRIFT")
    for ref in manifest["source_pins"]:
        target = _ROOT / ref["path"]
        if not target.is_file() or target.is_symlink():
            raise ProducerVerificationError("SOURCE_PIN_MISSING")
        raw = target.read_bytes()
        if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ProducerVerificationError("SOURCE_PIN_DRIFT")
    logical = Draft202012Validator(loaded["logical_schema"][1])
    prompt = manifest["logical_policy"]["exact_fetch_prompt"]
    denied = [
        "http://www.sec.gov/Archives/a", "https://evil.example/Archives/a",
        "https://www.sec.gov/Archives/../about", "https://www.sec.gov/Archives/%2e%2e/about",
        "https://www.sec.gov/Archives/%252e%252e/about", "https://www.sec.gov/Archives/%2fabout",
        "https://www.sec.gov/Archives/%252fabout", "https://www.sec.gov//Archives/a",
        "https://www.sec.gov/about?next=/Archives/a",
    ]
    for url in denied:
        if logical.is_valid({"operation": "web_fetch", "url": url, "prompt": prompt}):
            raise ProducerVerificationError("LOGICAL_SCHEMA_BYPASS_" + url)
    return {
        "version": "r6-frozen-tool-web-allowance-producer-verification-v4",
        "status": "PASS_PROVIDER_FREE_PENDING_FRESH_INDEPENDENT_REVIEW",
        "activation": False, "provider_free": True,
        "source_pins_verified": len(manifest["source_pins"]),
        "manifest": {"bytes": len(loaded["manifest"][0]), "sha256": _FILES["manifest"][1]},
        "schemas": {name: {"bytes": len(loaded[name][0]), "sha256": _FILES[name][1]} for name in ("manifest_schema", "logical_schema", "translation_schema", "settlement_schema")},
        "draft_2020_12_metaschema": "PASS", "url_bypass_matrix": {"denied": len(denied), "result": "PASS"},
        "history": manifest["history"], "effects_executed": dict(manifest["effects"]),
        "provider_internal_equality_claimed": False, "fresh_independent_review": "PENDING",
        "verdict": "DISABLED_V4_CANDIDATE_STRUCTURALLY_VERIFIED_NOT_ADOPTED_INTO_RUNTIME",
    }


if __name__ == "__main__":
    print(json.dumps(build_receipt(), sort_keys=True, separators=(",", ":")))
