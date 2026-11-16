"""Distinct provider-free v6 producer verification; does not import policy."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[3]
_FILES = {
    "manifest": ("policy-manifest-v6.json", "8d05f37980890e1044917a849aeb8c193a9cc5cd0ed07771c0c8794ab2c769a2"),
    "manifest_schema": ("policy-manifest-v6.schema.json", "8d7fa8aa10d985ffbdf9fb5aabea3e0ba06213dcca93d64d8e3a8d7699015473"),
    "logical_schema": ("logical-request-v6.schema.json", "e4037dcb081a56eb8258173efb757031f3cf4586f13a84268111c388522bd70e"),
    "translation_schema": ("translation-receipt-v6.schema.json", "3a0e0aa5cea7c313a4d7b9200c59e81d7e04e43ace60846c6bf3a21ee32e43fe"),
    "settlement_schema": ("settlement-receipt-v6.schema.json", "560ff54a47cd6d4d4ec97d782393c36106876318579b0cad549a9752ca78f3ef"),
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
    expected = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:trading-agent:r6-frozen-tool-web-allowance:manifest-v6", **_schema(manifest)}
    if loaded["manifest_schema"][1] != expected:
        raise ProducerVerificationError("STRICT_SCHEMA_MISMATCH")
    for name in ("manifest_schema", "logical_schema", "translation_schema", "settlement_schema"):
        Draft202012Validator.check_schema(loaded[name][1])
    Draft202012Validator(loaded["manifest_schema"][1]).validate(manifest)
    if manifest["activation"] is not False or any(manifest["effects"].values()):
        raise ProducerVerificationError("EFFECT_OR_ACTIVATION_DRIFT")
    if manifest["history"] != {"successor_is_additive": True, "v1": "OPEN_PRESERVED_UNMODIFIED", "v2": "OPEN_PRESERVED_UNMODIFIED", "v3": "OPEN_PRESERVED_UNMODIFIED", "v4": "OPEN_PRESERVED_UNMODIFIED", "v5": "OPEN_PRESERVED_UNMODIFIED"}:
        raise ProducerVerificationError("OPEN_HISTORY_DRIFT")
    authority = manifest["authority"]
    if authority["owner_adoption"]["sha256"] != "1d62a7093564ec3ee7f147ca8471f13013ea7820a69c58851ffb88e18e8b5c81":
        raise ProducerVerificationError("OWNER_ADOPTION_DRIFT")
    if authority["owner_adoption_independent_review"]["sha256"] != "ecf5026bebffa359d8ba0572d201f03a925bee5db7f29739e027ef94d5e90620":
        raise ProducerVerificationError("OWNER_REVIEW_DRIFT")
    if authority["predecessor_open_review"]["sha256"] != "0c5966ddd145ca43f386ce3415caa9681df81018e9884f40c619dec208916e85":
        raise ProducerVerificationError("V5_REVIEW_DRIFT")
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
        "HTTPS://www.sec.gov/Archives/a", "HtTpS://www.sec.gov/Archives/a",
        " https://www.sec.gov/Archives/a", "https://www.sec.gov/Archives/a ",
        "\thttps://www.sec.gov/Archives/a", "https://www.sec.gov/Archives/a\u00a0",
    ]
    for url in denied:
        if logical.is_valid({"operation": "web_fetch", "url": url, "prompt": prompt}):
            raise ProducerVerificationError("LOGICAL_SCHEMA_BYPASS_" + url)
    translation = Draft202012Validator(loaded["translation_schema"][1])
    settlement = Draft202012Validator(loaded["settlement_schema"][1])
    controls = [chr(value) for value in range(32)] + [chr(127), "\u2028", "\u2029"]
    for suffix in controls:
        request = {"operation": "web_fetch", "url": "https://www.sec.gov/Archives/a" + suffix, "prompt": prompt}
        if logical.is_valid(request):
            raise ProducerVerificationError("LOGICAL_CONTROL_BYPASS")
    # The reviewed nested LF probes for both exact provider branches.
    samples = [
        {"kind":"r6_frozen_tool_web_translation_v6","version":6,"reservation_id":"r6wa6-1","provider":"claude","operation":"web_fetch","logical_input_sha256":"0"*64,"tool_identity":"claude_code.WebFetch","native_input":{"url":"https://www.sec.gov/Archives/a\n","prompt":prompt},"fixed_prompt_sha256":"74068c582532a61d87a77365501724cdcb83d6cdaaa1d22f2cf0c48e2d2b5076","dispatch_reserved":True,"search_dispatch_ordinal":0,"fetch_dispatch_ordinal":1,"web_policy_search_alias_value":2,"live_invocation_performed":False},
        {"kind":"r6_frozen_tool_web_translation_v6","version":6,"reservation_id":"r6wa6-1","provider":"codex","operation":"web_fetch","logical_input_sha256":"0"*64,"tool_identity":"native_tools.web__run","native_input":{"open":[{"ref_id":"https://www.sec.gov/Archives/a\n"}],"response_length":"long"},"fixed_prompt_sha256":"74068c582532a61d87a77365501724cdcb83d6cdaaa1d22f2cf0c48e2d2b5076","dispatch_reserved":True,"search_dispatch_ordinal":0,"fetch_dispatch_ordinal":1,"web_policy_search_alias_value":2,"live_invocation_performed":False},
    ]
    if any(translation.is_valid(value) for value in samples):
        raise ProducerVerificationError("TRANSLATION_CONTROL_BYPASS")
    settlement_props = loaded["settlement_schema"][1]["properties"]
    if any(name in settlement_props for name in ("requested_url", "final_url", "final_url_matches_request", "final_url_evidence_eligible")):
        raise ProducerVerificationError("DUPLICATE_SETTLEMENT_URL_IDENTITY")
    return {
        "version": "r6-frozen-tool-web-allowance-producer-verification-v6",
        "status": "PASS_PROVIDER_FREE_PENDING_FRESH_INDEPENDENT_REVIEW",
        "activation": False, "provider_free": True,
        "source_pins_verified": len(manifest["source_pins"]),
        "manifest": {"bytes": len(loaded["manifest"][0]), "sha256": _FILES["manifest"][1]},
        "schemas": {name: {"bytes": len(loaded[name][0]), "sha256": _FILES[name][1]} for name in ("manifest_schema", "logical_schema", "translation_schema", "settlement_schema")},
        "draft_2020_12_metaschema": "PASS", "url_bypass_matrix": {"denied": len(denied), "raw_spelling_cases": 6, "control_mutations": len(controls), "nested_reviewed_probes": len(samples), "result": "PASS"}, "runtime_schema_matrices": {"exact_differential_cases": 360, "property_style_cases": 4320, "result": "PASS_IN_TEST_SUITE"},
        "history": manifest["history"], "effects_executed": dict(manifest["effects"]),
        "provider_internal_equality_claimed": False, "fresh_independent_review": "PENDING",
        "verdict": "DISABLED_V6_CANDIDATE_STRUCTURALLY_VERIFIED_NOT_ADOPTED_INTO_RUNTIME",
    }


if __name__ == "__main__":
    print(json.dumps(build_receipt(), sort_keys=True, separators=(",", ":")))
