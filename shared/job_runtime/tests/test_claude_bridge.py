import asyncio
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from shared.job_runtime.claude_bridge import (
    CLAUDE_BRIDGE_CAPABILITY,
    CLAUDE_MODEL_CAPABILITIES,
    run_claude_host,
)


class AssistantMessage:
    """Vendored documented AssistantMessage fields; never imports or calls the SDK."""

    def __init__(self, model, error=None):
        self.model = model
        self.error = error


_UNSET = object()


class ModelUsage:
    """Vendored SDK 0.2.179 required/optional camelCase shape."""

    def __init__(self, model, input_tokens=11, output_tokens=7, cost_usd=0.001,
                 canonical=_UNSET, provider=_UNSET):
        self.inputTokens = input_tokens
        self.outputTokens = output_tokens
        self.cacheReadInputTokens = 0
        self.cacheCreationInputTokens = 0
        self.webSearchRequests = 0
        self.costUSD = cost_usd
        self.contextWindow = 1000000
        self.maxOutputTokens = 128000
        if canonical is _UNSET:
            canonical = model
        if provider is _UNSET:
            provider = "anthropic"
        if canonical is not None:
            self.canonicalModel = canonical
        if provider is not None:
            self.provider = provider


class ResultMessage:
    """Vendored documented ResultMessage fields for provider-free parsing tests."""

    def __init__(self, **changes):
        values = {
            "subtype": "success", "is_error": False, "result": "bounded result",
            "session_id": "session-private",
            "model_usage": {"claude-opus-5-5": ModelUsage("claude-opus-5-5")},
            "usage": {"input_tokens": 11, "output_tokens": 7,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            "total_cost_usd": 0.001, "stop_reason": "end_turn",
            "api_error_status": None, "terminal_reason": "success",
        }
        values.update(changes)
        for key, value in values.items():
            setattr(self, key, value)


class Options:
    last = None

    def __init__(self, **values):
        self.values = values
        Options.last = values


class ClaudeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        state = self.root / ".job-runtime"
        (state / "runs").mkdir(parents=True, mode=0o700)
        (state / "auth").mkdir(mode=0o700)
        self.profile = {
            "model": "claude-opus-5-5", "effort": "low", "timeout_seconds": 5,
            "auth_home": str(state / "auth"), "max_budget_usd": 0.02,
        }
        self.context = {"cancel_event": None}

    def terminal(self, **changes):
        terminal = ResultMessage(**changes)
        if "model_usage" not in changes:
            terminal.model_usage = {
                self.profile["model"]: ModelUsage(self.profile["model"]),
            }
        return terminal

    def messages(self, terminal=None, *, assistant_model=None, assistant_error=None):
        return [
            AssistantMessage(assistant_model or self.profile["model"], assistant_error),
            terminal or self.terminal(),
        ]

    def invoke(self, messages=None, name="run", *, query_fn=None, options_factory=Options):
        messages = self.messages() if messages is None else messages
        if query_fn is None:
            async def query_fn(**kwargs):
                for value in messages:
                    if isinstance(value, BaseException):
                        raise value
                    yield value
        return run_claude_host(
            self.profile, b"bounded prompt", self.root,
            self.root / ".job-runtime/runs" / name, "operation/1", self.context,
            query_fn=query_fn, options_factory=options_factory,
        )

    def test_closed_table_and_production_gate_are_immutable(self):
        self.assertEqual(set(CLAUDE_MODEL_CAPABILITIES), {
            "claude-opus-5-5", "claude-fable-5-1",
        })
        fable = CLAUDE_MODEL_CAPABILITIES["claude-fable-5-1"]
        self.assertEqual(fable["efforts"], {"low"})
        self.assertEqual(fable["max_budget_usd"], 0.02)
        self.assertEqual(fable["minimum_python"], (3, 10))
        self.assertFalse(CLAUDE_BRIDGE_CAPABILITY["production_enabled"])
        with self.assertRaises(TypeError):
            fable["max_turns"] = 2  # type: ignore[index]

    def test_opus_success_uses_explicit_empty_surfaces_and_no_retry_claim(self):
        result = self.invoke()
        self.assertEqual((result.status.value, result.code), ("succeeded", "CLAUDE_HOST_CAPTURED"))
        values = Options.last
        self.assertEqual(values["tools"], [])
        self.assertEqual(values["mcp_servers"], {})
        self.assertTrue(values["strict_mcp_config"])
        self.assertEqual(values["agents"], {})
        self.assertEqual(values["skills"], [])
        self.assertEqual(values["setting_sources"], [])
        self.assertFalse(values["include_partial_messages"])
        self.assertNotIn("allowed_tools", values)
        self.assertNotIn("disallowed_tools", values)
        self.assertNotIn("plugins", values)
        self.assertEqual(values["max_turns"], 1)
        self.assertEqual(values["max_budget_usd"], 0.02)
        self.assertEqual(values["env"]["CLAUDE_CODE_MAX_RETRIES"], "0")
        self.assertTrue(result.receipt["configured_retry_zero"])
        self.assertFalse(result.receipt["typed_retry_observed_supported"])
        self.assertNotIn("retry_events_observed", result.receipt)

    def test_plugins_empty_only_when_options_signature_documents_it(self):
        captured = {}

        def factory(*, model, effort, tools, mcp_servers, strict_mcp_config, agents,
                    skills, plugins, permission_mode, max_turns, max_budget_usd,
                    env, setting_sources, include_partial_messages):
            captured.update(locals())
            return SimpleNamespace()

        result = self.invoke(options_factory=factory, name="plugins")
        self.assertEqual(result.status.value, "succeeded")
        self.assertEqual(captured["plugins"], [])

    def test_missing_required_sdk_option_surface_blocks_predispatch(self):
        calls = []

        def incomplete(*, model, effort):
            calls.append(True)

        result = self.invoke(options_factory=incomplete, name="surface")
        self.assertEqual((result.phase.value, result.submission.value, result.code),
                         ("not_started", "not_submitted", "CLAUDE_HOST_SDK_UNAVAILABLE"))
        self.assertEqual(calls, [])

    def test_fable_success_reconciles_assistant_model_usage_cost_and_usage(self):
        self.profile["model"] = "claude-fable-5-1"
        result = self.invoke(name="fable")
        self.assertEqual(result.status.value, "succeeded")
        self.assertEqual(result.receipt["configured_model"], "claude-fable-5-1")
        self.assertEqual(result.receipt["provider_reported_model"], "claude-fable-5-1")
        self.assertEqual(tuple(result.receipt["provider_model_keys"]), ("claude-fable-5-1",))
        self.assertEqual(dict(result.receipt["usage"]), {
            "input_tokens": 11, "output_tokens": 7,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})
        self.assertEqual(result.receipt["total_cost_usd"], 0.001)

    def test_optional_canonical_and_provider_fields_may_be_omitted(self):
        cases = [
            ModelUsage(self.profile["model"], canonical=None),
            ModelUsage(self.profile["model"], provider=None),
            ModelUsage(self.profile["model"], canonical=None, provider=None),
        ]
        for index, row in enumerate(cases):
            with self.subTest(index=index):
                terminal = self.terminal(model_usage={self.profile["model"]: row})
                result = self.invoke(self.messages(terminal), f"optional-{index}")
                self.assertEqual(result.status.value, "succeeded")
                if hasattr(row, "provider"):
                    self.assertRegex(result.receipt["provider_evidence_sha256"], r"^[0-9a-f]{64}$")
                else:
                    self.assertFalse(result.receipt["provider_evidence_sha256"])

    def test_required_model_usage_fields_are_all_enforced(self):
        required = ("inputTokens", "outputTokens", "cacheReadInputTokens",
                    "cacheCreationInputTokens", "webSearchRequests", "costUSD",
                    "contextWindow", "maxOutputTokens")
        for index, field in enumerate(required):
            with self.subTest(field=field):
                row = vars(ModelUsage(self.profile["model"])).copy()
                row.pop(field)
                terminal = self.terminal(model_usage={self.profile["model"]: row})
                result = self.invoke(self.messages(terminal), f"missing-required-{index}")
                self.assertEqual(result.code, "CLAUDE_HOST_IDENTITY_MISMATCH")

    def test_optional_field_conflicts_and_malformed_provider_reject(self):
        rows = [
            ModelUsage(self.profile["model"], canonical="claude-fable-5-1"),
            ModelUsage(self.profile["model"], provider=""),
            ModelUsage(self.profile["model"], provider=7),
        ]
        for index, row in enumerate(rows):
            with self.subTest(index=index):
                result = self.invoke(self.messages(self.terminal(
                    model_usage={self.profile["model"]: row})), f"optional-bad-{index}")
                self.assertEqual(result.code, "CLAUDE_HOST_IDENTITY_MISMATCH")

    def test_unknown_profiles_and_extra_controls_reject_predispatch(self):
        calls = []
        cases = [
            {**self.profile, "model": "claude-fable-5"},
            {**self.profile, "model": "claude-fable-5-1", "effort": "medium"},
            {**self.profile, "max_budget_usd": 0.020001},
            {**self.profile, "fallback": "claude-opus-5-5"},
            {**self.profile, "tools": []},
            {**self.profile, "max_retries": 0},
            {**self.profile, "thinking_budget": 1024},
            {**self.profile, "settings": {}},
        ]
        for index, profile in enumerate(cases):
            with self.subTest(index=index):
                result = run_claude_host(
                    profile, b"p", self.root, self.root / ".job-runtime/runs" / f"bad-{index}",
                    "operation/1", self.context, query_fn=lambda **kw: calls.append(kw),
                    options_factory=Options)
                self.assertEqual(result.code, "CLAUDE_HOST_PROFILE_INVALID")
        self.assertEqual(calls, [])

    def test_documented_refusal_and_generic_config_are_stable_without_raw_text(self):
        refusal = self.terminal(is_error=True, result="private raw text", stop_reason="refusal")
        result = self.invoke(self.messages(refusal), "refusal")
        self.assertEqual((result.status.value, result.code),
                         ("failed", "CLAUDE_HOST_POLICY_FAILURE"))
        generic = self.terminal(is_error=True, result="private retention text",
                                api_error_status=400, terminal_reason="undocumented")
        result = self.invoke(self.messages(generic), "generic-config")
        self.assertEqual((result.status.value, result.code),
                         ("failed", "CLAUDE_HOST_CONFIG_FAILURE"))
        self.assertEqual(result.receipt["terminal_class"], "config")
        self.assertNotIn("private", repr(dict(result.receipt)))


    def test_http_statuses_are_stable_generic_classes(self):
        for index, (status, code) in enumerate(((403, "CLAUDE_HOST_AUTH_FAILURE"),
                                                (404, "CLAUDE_HOST_CONFIG_FAILURE"),
                                                (429, "SOURCE_HTTP_429"),
                                                (503, "SOURCE_HTTP_503"))):
            terminal = self.terminal(is_error=True, result="private", api_error_status=status)
            result = self.invoke(self.messages(terminal), f"http-{index}")
            self.assertEqual((result.status.value, result.code), ("failed", code))
            self.assertNotIn("private", repr(dict(result.receipt)))

    def test_model_reconciliation_rejects_assistant_key_and_canonical_drift(self):
        wrong_assistant = self.invoke(
            self.messages(assistant_model="claude-fable-5-1"), "assistant-model")
        self.assertEqual(wrong_assistant.code, "CLAUDE_HOST_IDENTITY_MISMATCH")
        wrong_key = self.terminal(model_usage={
            "claude-fable-5-1": ModelUsage("claude-fable-5-1"),
        })
        result = self.invoke(self.messages(wrong_key), "key-model")
        self.assertEqual(result.code, "CLAUDE_HOST_IDENTITY_MISMATCH")
        canonical_drift = self.terminal(model_usage={
            "claude-opus-5-5": ModelUsage("claude-fable-5-1"),
        })
        result = self.invoke(self.messages(canonical_drift), "canonical-model")
        self.assertEqual(result.code, "CLAUDE_HOST_IDENTITY_MISMATCH")

    def test_assistant_error_and_missing_assistant_fail_generic(self):
        error = self.invoke(self.messages(assistant_error="private assistant text"), "assistant-error")
        self.assertEqual(error.code, "CLAUDE_HOST_PARTIAL_RESULT")
        self.assertNotIn("private", repr(dict(error.receipt)))
        missing = self.invoke([self.terminal()], "assistant-missing")
        self.assertEqual(missing.code, "CLAUDE_HOST_PARTIAL_RESULT")

    def test_usage_cost_and_budget_reconciliation_fail_closed(self):
        cases = [
            self.terminal(usage=None),
            self.terminal(usage={"input_tokens": 10, "output_tokens": 7}),
            self.terminal(total_cost_usd=None),
            self.terminal(total_cost_usd=0.002),
        ]
        for index, terminal in enumerate(cases):
            result = self.invoke(self.messages(terminal), f"reconcile-{index}")
            self.assertEqual((result.status.value, result.code),
                             ("failed", "CLAUDE_HOST_PARTIAL_RESULT"))
        over = self.invoke(self.messages(self.terminal(total_cost_usd=0.020001)), "budget")
        self.assertEqual(over.code, "CLAUDE_HOST_QUOTA_EXHAUSTED")
        subtype = self.invoke(self.messages(self.terminal(
            subtype="error_max_budget_usd", is_error=True)), "budget-subtype")
        self.assertEqual(subtype.code, "CLAUDE_HOST_QUOTA_EXHAUSTED")

    def test_snake_case_model_usage_row_is_rejected(self):
        old = {"claude-opus-5-5": {
            "canonicalModel": "claude-opus-5-5", "provider": "anthropic",
            "input_tokens": 11, "output_tokens": 7, "cost_usd": 0.001,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}
        result = self.invoke(self.messages(self.terminal(model_usage=old)), "old-row")
        self.assertEqual(result.code, "CLAUDE_HOST_IDENTITY_MISMATCH")

    def test_unknown_api_retry_shaped_message_is_not_claimed_as_observed(self):
        undocumented = SimpleNamespace(subtype="api_retry")
        result = self.invoke([AssistantMessage(self.profile["model"]), undocumented,
                              self.terminal()], "retry-unknown")
        self.assertEqual(result.status.value, "succeeded")
        self.assertFalse(result.receipt["typed_retry_observed_supported"])
        self.assertNotIn("automatic_retry_observed", result.receipt)

    def test_terminal_shape_timeout_and_exception_are_fenced(self):
        duplicate = self.invoke(self.messages() + [self.terminal()], "duplicate")
        self.assertEqual(duplicate.code, "CLAUDE_HOST_PARTIAL_RESULT")
        malformed = self.invoke(self.messages(self.terminal(result=b"bad")), "malformed")
        self.assertEqual(malformed.code, "CLAUDE_HOST_PARTIAL_RESULT")
        self.profile["timeout_seconds"] = 0.001

        async def slow_query(**kwargs):
            await asyncio.sleep(0.02)
            yield AssistantMessage(self.profile["model"])

        timeout = self.invoke([], "timeout", query_fn=slow_query)
        self.assertEqual((timeout.status.value, timeout.code, timeout.submission.value),
                         ("unknown", "CLAUDE_HOST_LATE_RESULT", "possibly_submitted"))
        self.profile["timeout_seconds"] = 5
        unknown = self.invoke([RuntimeError("private")], "unknown")
        self.assertEqual((unknown.status.value, unknown.code),
                         ("unknown", "CLAUDE_HOST_PARTIAL_RESULT"))
        self.assertNotIn("private", repr(dict(unknown.receipt)))

    def test_success_result_and_proof_remain_hash_bound(self):
        result = self.invoke(self.messages(self.terminal(result="custodied result")), "custody")
        private = self.root / ".job-runtime/runs/custody/private"
        raw = (private / "result.bin").read_bytes()
        proof_raw = (private / "proof.json").read_bytes()
        proof = json.loads(proof_raw)
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(digest, proof["result_sha256"])
        self.assertEqual(digest, result.receipt["result_sha256"])
        self.assertEqual(hashlib.sha256(proof_raw).hexdigest(), result.receipt["proof_sha256"])

    def test_cancel_before_dispatch_is_fixed_failure(self):
        self.context = {"cancel_event": SimpleNamespace(is_set=lambda: True)}
        result = self.invoke([], "cancel")
        self.assertEqual((result.phase.value, result.submission.value),
                         ("not_started", "not_submitted"))


if __name__ == "__main__":
    unittest.main()
