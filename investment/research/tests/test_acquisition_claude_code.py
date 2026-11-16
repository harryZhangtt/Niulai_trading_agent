import hashlib
import json
import unittest

from investment.research.acquisition_claude_code import (
    CLAUDE_CODE_FETCH,
    CLAUDE_CODE_SEARCH,
    CODEX_NATIVE_WEB,
    FETCH_PROMPT,
    ClaudeCodeAdapterError,
    prepare_claude_code_call,
)
from shared.research_sources.acquisition_contracts import (
    AcquisitionIdentity,
    DispatchIdentity,
    RunIdentity,
)


class ClaudeCodeWebAdapterTests(unittest.TestCase):
    @staticmethod
    def identity(operation="search-one", dispatch="dispatch-one"):
        return AcquisitionIdentity(
            RunIdentity("claude-host-e2e", "execution-1", "trace-1"),
            DispatchIdentity(operation, f"{operation}:1", dispatch),
        )

    def test_search_maps_to_exact_claude_websearch_identity(self):
        arguments = {"search_query": [{"q": "site:example.com exact title"}],
                     "response_length": "long"}
        prepared = prepare_claude_code_call(self.identity(), arguments)
        call = prepared.spec.public_call()
        self.assertEqual(call["configured_backend"], CLAUDE_CODE_SEARCH)
        self.assertEqual(call["tool_input"], {"query": "site:example.com exact title"})
        self.assertEqual(call["representation_scope"], "current_search_metadata_only")
        self.assertIsNone(call["requested_url"])
        self.assertEqual(call["dispatch_id"], "dispatch-one")
        self.assertNotEqual(call["configured_backend"], CODEX_NATIVE_WEB)
        self.assertEqual(call["acquisition_arguments_sha256"],
                         prepared.spec.acquisition_arguments.sha256)

    def test_open_maps_to_frozen_webfetch_prompt_and_rendered_scope(self):
        url = "https://example.com/disclosure.html"
        arguments = {"open": [{"ref_id": url}], "response_length": "long"}
        prepared = prepare_claude_code_call(
            self.identity("open-one", "dispatch-open"), arguments)
        call = prepared.spec.public_call()
        self.assertEqual(call["configured_backend"], CLAUDE_CODE_FETCH)
        self.assertEqual(call["tool_input"], {"url": url, "prompt": FETCH_PROMPT})
        self.assertEqual(call["representation_scope"], "rendered_extracted_representation")
        self.assertEqual(call["requested_url"], url)
        self.assertTrue(any("not publisher-original bytes" in value
                            for value in call["limitations"]))

    def test_unsupported_operations_and_semantics_fail_closed(self):
        invalid = [
            {"find": [{"ref_id": "https://example.com/a", "pattern": "x"}]},
            {"search_query": [{"q": "x"}, {"q": "y"}]},
            {"search_query": [{"q": "x", "domains": ["example.com"]}]},
            {"search_query": [{"q": "x", "recency": 30}]},
            {"open": [{"ref_id": "https://example.com/a", "lineno": 4}]},
            {"open": [{"ref_id": "https://example.com/a"}], "response_length": "short"},
        ]
        for index, arguments in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ClaudeCodeAdapterError):
                prepare_claude_code_call(self.identity(), arguments)

    def test_private_ephemeral_credential_and_fragment_urls_are_rejected(self):
        invalid = [
            "turn0search0",
            "https://localhost/a",
            "https://127.0.0.1/a",
            "https://user:secret@example.com/a",
            "https://example.com/a#fragment",
            "https://example.com:8443/a",
        ]
        for url in invalid:
            with self.subTest(url=url), self.assertRaisesRegex(
                    ClaudeCodeAdapterError, "ACQ_CLAUDE_URL_INVALID"):
                prepare_claude_code_call(
                    self.identity("open-one", "dispatch-open"),
                    {"open": [{"ref_id": url}]},
                )

    def test_capture_binds_dispatch_tool_and_exact_input_once(self):
        prepared = prepare_claude_code_call(
            self.identity(), {"search_query": [{"q": "bounded query"}]})
        raw = json.dumps({"results": [{"url": "https://example.com/a"}]},
                         separators=(",", ":")).encode()
        capture = prepared.capture(
            dispatch_id="dispatch-one",
            observed_tool=CLAUDE_CODE_SEARCH,
            actual_tool_input={"query": "bounded query"},
            raw_result_json=raw,
            captured_at="2026-11-05T01:02:03+00:00",
        )
        receipt = capture.receipt()
        self.assertEqual(receipt["raw_result_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt["raw_result_bytes"], len(raw))
        self.assertFalse(receipt["raw_result_persisted_here"])
        response = capture.provider_response()
        self.assertEqual(list(response.chunks), [raw])
        self.assertEqual(response.observed_backend, CLAUDE_CODE_SEARCH)
        with self.assertRaisesRegex(ClaudeCodeAdapterError, "ACQ_CLAUDE_CAPTURE_REPLAY"):
            prepared.capture(
                dispatch_id="dispatch-one", observed_tool=CLAUDE_CODE_SEARCH,
                actual_tool_input={"query": "bounded query"}, raw_result_json=raw,
                captured_at="2026-11-05T01:02:04+00:00",
            )

    def test_capture_identity_and_argument_mismatches_fail_without_consuming(self):
        prepared = prepare_claude_code_call(
            self.identity(), {"search_query": [{"q": "bounded query"}]})
        raw = b'"safe"'
        cases = [
            {"dispatch_id": "other", "observed_tool": CLAUDE_CODE_SEARCH,
             "actual_tool_input": {"query": "bounded query"}},
            {"dispatch_id": "dispatch-one", "observed_tool": CLAUDE_CODE_FETCH,
             "actual_tool_input": {"query": "bounded query"}},
            {"dispatch_id": "dispatch-one", "observed_tool": CLAUDE_CODE_SEARCH,
             "actual_tool_input": {"query": "different"}},
        ]
        for index, values in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ClaudeCodeAdapterError):
                prepared.capture(**values, raw_result_json=raw,
                                 captured_at="2026-11-05T01:02:03+00:00")
        capture = prepared.capture(
            dispatch_id="dispatch-one", observed_tool=CLAUDE_CODE_SEARCH,
            actual_tool_input={"query": "bounded query"}, raw_result_json=raw,
            captured_at="2026-11-05T01:02:03+00:00")
        self.assertEqual(capture.receipt()["observed_backend"], CLAUDE_CODE_SEARCH)

    def test_raw_bounds_json_and_aware_time_are_enforced(self):
        for raw, captured_at, limit in [
            (b"not-json", "2026-11-05T01:02:03+00:00", 65536),
            (b'"safe"', "2026-11-05T01:02:03", 65536),
            (b'"too-long"', "2026-11-05T01:02:03+00:00", 3),
        ]:
            prepared = prepare_claude_code_call(
                self.identity(), {"search_query": [{"q": "bounded query"}]})
            with self.assertRaises(ClaudeCodeAdapterError):
                prepared.capture(
                    dispatch_id="dispatch-one", observed_tool=CLAUDE_CODE_SEARCH,
                    actual_tool_input={"query": "bounded query"},
                    raw_result_json=raw, captured_at=captured_at, raw_byte_limit=limit)

    def test_secret_shaped_raw_value_is_hash_only_in_receipt_and_errors(self):
        prepared = prepare_claude_code_call(
            self.identity(), {"search_query": [{"q": "bounded query"}]})
        secret = "sk-" + "A" * 48
        raw = json.dumps({"provider_output": secret}).encode()
        capture = prepared.capture(
            dispatch_id="dispatch-one", observed_tool=CLAUDE_CODE_SEARCH,
            actual_tool_input={"query": "bounded query"}, raw_result_json=raw,
            captured_at="2026-11-05T01:02:03+00:00")
        public = json.dumps(capture.receipt())
        self.assertNotIn(secret, public)
        self.assertNotIn(secret, repr(capture))
        prepared2 = prepare_claude_code_call(
            self.identity("search-two", "dispatch-two"),
            {"search_query": [{"q": "bounded query"}]})
        with self.assertRaises(ClaudeCodeAdapterError) as caught:
            prepared2.capture(
                dispatch_id="dispatch-two", observed_tool=CLAUDE_CODE_SEARCH,
                actual_tool_input={"query": "bounded query"},
                raw_result_json=b"bad", captured_at="2026-11-05T01:02:03+00:00")
        self.assertNotIn(secret, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
