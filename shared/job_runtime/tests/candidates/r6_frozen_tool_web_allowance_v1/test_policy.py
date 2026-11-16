from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shared.job_runtime.candidates.r6_frozen_tool_web_allowance_v1 import verify as policy
from shared.job_runtime.candidates.r6_frozen_tool_web_allowance_v1.producer_verification import build_receipt


class FrozenAllowanceTests(unittest.TestCase):
    def call(self, **changes):
        args = {
            "provider": "claude",
            "operation": "web_fetch",
            "observed_tool": "claude_code.WebFetch",
            "adapter_dispatch_count": 0,
            "url": "https://www.sec.gov/Archives/example",
        }
        args.update(changes)
        return policy.authorize_call(**args)

    def denied(self, code, **changes):
        with self.assertRaisesRegex(policy.PolicyError, "^" + code + "$"):
            self.call(**changes)

    def test_canonical_candidate_is_valid_but_open(self):
        receipt = policy.verify_canonical_policy()
        self.assertEqual(receipt["status"], "OPEN_MATCHED_EXECUTABLE_ROSTER_NOT_ESTABLISHED")
        self.assertFalse(receipt["activation"])
        self.assertFalse(receipt["executable"])
        self.assertEqual(len(receipt["open_blockers"]), 8)

    def test_strict_schema_is_exact_and_closed_recursively(self):
        root = Path(policy.__file__).resolve().parent
        schema = json.loads((root / "owner-private-policy-manifest-v1.schema.json").read_text())
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        stack = [schema]
        objects = 0
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if node.get("type") == "object":
                    objects += 1
                    self.assertIs(node.get("additionalProperties"), False)
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        self.assertGreater(objects, 10)

    def test_duplicate_key_and_noncanonical_bytes_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            duplicate = Path(directory) / "duplicate.json"
            duplicate.write_text('{"a":1,"a":2}\n')
            with self.assertRaisesRegex(policy.PolicyError, "^DUPLICATE_JSON_KEY$"):
                policy._load(duplicate)
            spaced = Path(directory) / "spaced.json"
            spaced.write_text('{"a": 1}\n')
            with self.assertRaisesRegex(policy.PolicyError, "^NONCANONICAL_JSON_BYTES$"):
                policy._load(spaced)

    def test_caller_selected_policy_fails(self):
        root = Path(policy.__file__).resolve().parent
        raw = (root / "owner-private-policy-manifest-v1.json").read_bytes()
        self.assertFalse(policy.verify_exact_candidate(raw)["executable"])
        self.denied("CALLER_SELECTED_POLICY_DENIED", provider_policy_override={})
        with self.assertRaisesRegex(policy.PolicyError, "^CALLER_SELECTED_POLICY_DENIED$"):
            policy.verify_exact_candidate(raw + b" ")

    def test_unknown_domain_and_subdomain_fail(self):
        self.denied("UNKNOWN_DOMAIN_DENIED")
        self.denied("UNKNOWN_DOMAIN_DENIED", url="https://sub.sec.gov/example")
        self.denied(
            "UNKNOWN_DOMAIN_DENIED",
            provider="codex",
            observed_tool="native_tools.web__run",
            url="https://www.microsoft.com/example",
        )

    def test_private_internal_and_ip_hosts_fail(self):
        self.denied("INTERNAL_OR_PRIVATE_HOST", url="https://localhost/example")
        self.denied("INTERNAL_OR_PRIVATE_HOST", url="https://service.internal/example")
        self.denied("IP_LITERAL_DENIED", url="https://127.0.0.1/example")
        self.denied("IP_LITERAL_DENIED", url="https://8.8.8.8/example")

    def test_redirect_write_upload_and_auth_fail(self):
        self.denied(
            "REDIRECT_OBSERVABILITY_NOT_ESTABLISHED",
            redirect_chain=("https://www.sec.gov/a", "https://www.sec.gov/b"),
        )
        self.denied("WRITE_CAPABLE_METHOD_DENIED", method="POST")
        self.denied("UPLOAD_DENIED", upload_bytes=1)
        self.denied("AUTH_EXPORT_DENIED", auth_export=True)

    def test_call_argument_response_and_time_bounds_fail(self):
        self.denied("CALL_CEILING_EXCEEDED", adapter_dispatch_count=6)
        self.denied("ARGUMENT_BOUND_EXCEEDED", argument_bytes=16385)
        self.denied("RESPONSE_BOUND_EXCEEDED", raw_result_bytes=65537)
        self.denied("TIME_BOUND_EXCEEDED", provider_call_seconds=601)

    def test_version_tool_and_provider_drift_fail(self):
        self.denied("UNKNOWN_PROVIDER", provider="other")
        self.denied("UNKNOWN_OPERATION", operation="find")
        self.denied("PROVIDER_TOOL_IDENTITY_DRIFT", observed_tool="changed.WebFetch")
        root = Path(policy.__file__).resolve().parent
        raw = (root / "owner-private-policy-manifest-v1.json").read_bytes()
        changed = raw.replace(b'"external_provider_schema_version":"UNPINNED"', b'"external_provider_schema_version":"v1"', 1)
        with mock.patch.object(policy, "_MANIFEST") as path:
            path.read_bytes.return_value = changed
            with self.assertRaises(policy.PolicyError):
                policy.verify_canonical_policy()

    def test_search_requires_exact_official_domain_and_fails_closed(self):
        self.denied(
            "OFFICIAL_DOMAIN_FILTER_REQUIRED",
            operation="web_search",
            observed_tool="claude_code.WebSearch",
            url=None,
        )
        self.denied(
            "UNKNOWN_DOMAIN_DENIED",
            operation="web_search",
            observed_tool="claude_code.WebSearch",
            url=None,
            domains=("sec.gov",),
        )

    def test_bytedcli_internal_fallback_and_different_ceilings_fail(self):
        self.denied("INTERNAL_OR_BYTEDCLI_FALLBACK_DENIED", fallback="bytedcli")
        root = Path(policy.__file__).resolve().parent
        manifest = json.loads((root / "owner-private-policy-manifest-v1.json").read_text())
        self.assertFalse(manifest["ceiling_semantics"]["different_provider_ceilings_allowed"])
        self.assertFalse(manifest["ceiling_semantics"]["caller_override_allowed"])

    def test_producer_verification_is_distinct_and_provider_free(self):
        from shared.job_runtime.candidates.r6_frozen_tool_web_allowance_v1 import producer_verification
        source = inspect.getsource(producer_verification)
        self.assertNotIn("from .verify", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("subprocess.", source)
        root = Path(policy.__file__).resolve().parent
        manifest = json.loads((root / "owner-private-policy-manifest-v1.json").read_text())
        self.assertEqual(manifest["operation_policy"]["bytedcli"], "DENY")
        receipt = build_receipt()
        self.assertEqual(receipt["status"], "OPEN")
        self.assertFalse(receipt["matched_executable_roster_verified"])
        self.assertTrue(all(value is False for value in receipt["effects_executed"].values()))


if __name__ == "__main__":
    unittest.main()
