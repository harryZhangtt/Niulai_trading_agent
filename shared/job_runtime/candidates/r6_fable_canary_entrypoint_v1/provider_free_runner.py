"""Fixed provider-free TEST_ONLY runner; no SDK, provider, network, or live effect."""
from __future__ import annotations

from types import MappingProxyType

from shared.job_runtime.provider_contract import ProviderResultV1
from shared.job_runtime.retry_policy import validate_retry_policy


EXPECTED_PROFILE = MappingProxyType({
    "model": "claude-fable-5-1",
    "effort": "low",
    "max_budget_usd": 0.02,
    "timeout_seconds": 5,
    "auth_home": ".job-runtime/auth",
})
_FIXED_RETRY_POLICY = MappingProxyType({
    "version": 2,
    "max_attempts": 1,
    "base_delay_seconds": 1,
    "max_delay_seconds": 1,
})


def make_provider_free_runner(expected_config_sha256):
    """Return a lexical fake runner bound to one admitted config digest."""
    if type(expected_config_sha256) is not str or len(expected_config_sha256) != 64:
        raise ValueError("FABLE_CANARY_CONFIG_DRIFT")
    expected_profile = dict(EXPECTED_PROFILE)
    policy = validate_retry_policy(dict(_FIXED_RETRY_POLICY))
    result_type = ProviderResultV1
    config_digest = expected_config_sha256

    def run_claude_host(profile, prompt, workspace, run_dir, operation_id, context):
        if type(profile) is not dict or profile != expected_profile:
            raise ValueError("FABLE_CANARY_PROFILE_DRIFT")
        if type(prompt) is not str or type(operation_id) is not str:
            raise ValueError("FABLE_CANARY_INVOCATION_INVALID")
        if prompt == "__FABLE_CANARY_TEST_EXCEPTION__":
            raise RuntimeError("provider-free synthetic exception")
        if prompt == "__FABLE_CANARY_TEST_FAILURE__":
            return result_type(
                provider="claude_host", operation_id=operation_id, phase="terminal",
                submission="definitely_submitted", terminal_proof="verified",
                status="failed", code="CLAUDE_HOST_CAPTURED_FAILURE",
                failure_kind="provider", provider_should_retry=False,
                receipt={"fixture": True, "test_only": True, "provider_called": False,
                         "network_used": False, "sdk_imported": False})
        return result_type(
            provider="claude_host", operation_id=operation_id, phase="terminal",
            submission="definitely_submitted", terminal_proof="verified",
            status="succeeded", code="CLAUDE_HOST_CAPTURED", failure_kind="none",
            provider_should_retry=False,
            receipt={
                "fixture": True, "test_only": True, "provider_called": False,
                "network_used": False, "sdk_imported": False,
                "config_sha256": config_digest,
                "retry_policy_sha256": policy.fingerprint,
            },
        )

    return run_claude_host


__all__ = ["EXPECTED_PROFILE", "make_provider_free_runner"]
