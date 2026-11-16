"""Pure, disabled authority-v2 harness configuration."""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping


class HarnessV2Error(ValueError):
    """Raised when a harness binding differs from the reviewed authority."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_BINDINGS = {
    "treatment_binding_wrapper_sha256": "6284984d4d48796df2ba96918d983e6a998a60d3b9bff807f3639da6c97b4332",
    "integration_verification_v7_sha256": "efa2c4e69fcf10994342875b7e200de665676a8ff808e3401d81563d78f1cb27",
    "treatment_fingerprint_sha256": "e77821daf101150d6340b87a70cb8c3a68438d4eebc63074282031639c477de6",
    "profile_sha256": "3f9d2fb9bef5f9adbcb54fa7f122af72adc0e8e8c290d756a0c18fcd5096ecd1",
    "payload_sha256": "3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b",
    "source_cutoff_sha256": "32f28a6cea0b1053321a52782abe40d6fd8a2d58b95bb954f90794ec5b733072",
}

_CAPABILITIES = {
    "source_authority_verified": True,
    "source_grammar_verified": True,
    "binary_asset_verified": True,
    "source_to_binary_reproducible_build_verified": False,
    "retry_zero_live_verified": False,
    "sanitized_live_capture_verified": False,
    "gateway_observer_reconciliation_verified": False,
    "capability_open": False,
}


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def expected_bindings() -> Mapping[str, str]:
    """Return the exact reviewed binding set as an immutable mapping."""
    return _freeze(dict(_BINDINGS))


def build_harness_config(bindings: Mapping[str, object]) -> Mapping[str, object]:
    """Build an immutable, disabled, effect-none harness configuration."""
    if type(bindings) is not dict or set(bindings) != set(_BINDINGS):
        raise HarnessV2Error("CODEX_Q1_AUTHORITY_V2_HARNESS_BINDINGS_INVALID")
    if any(type(bindings[key]) is not str or bindings[key] != expected for key, expected in _BINDINGS.items()):
        raise HarnessV2Error("CODEX_Q1_AUTHORITY_V2_HARNESS_BINDINGS_INVALID")

    return _freeze({
        "schema_version": "harness-v2",
        "candidate_id": "codex-rust-0.167-isolated-canary-q1-v2",
        "enabled": False,
        "bindings": dict(_BINDINGS),
        "execution": {"max_workers": 1, "max_attempts": 1},
        "retries": {"request": 0, "stream": 0},
        "capabilities": dict(_CAPABILITIES),
        "live": {
            "provider_invocation": False,
            "service_invocation": False,
            "model_invocation": False,
            "process_invocation": False,
            "network_access": False,
        },
        "effects": {"email": False, "host": False, "network": False, "provider": False},
    })
