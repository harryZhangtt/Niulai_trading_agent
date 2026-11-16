from __future__ import annotations

import inspect
import json
from pathlib import Path
import unittest
from unittest import mock

from shared.job_runtime.candidates.r6_frozen_tool_web_allowance_v3 import policy
from shared.job_runtime.candidates.r6_frozen_tool_web_allowance_v3.producer_verification import build_receipt


class FrozenWebAllowanceV3Tests(unittest.TestCase):
    def search(self, query="Microsoft filing"):
        return {"operation": "web_search", "query": query, "allowed_domains": list(policy.ALLOWED_DOMAINS)}

    def fetch(self, url="https://www.sec.gov/Archives/example.htm"):
        return {"operation": "web_fetch", "url": url, "prompt": policy.FETCH_PROMPT}

    def observations(self, **changes):
        value = {"http_requests": None, "cache": None, "ranking": None, "result_count": None, "equality_claimed": False}
        value.update(changes)
        return value

    def report(self, outcome="PASS", reason="NATIVE_TERMINAL", final_url=None, redirect_chain=None, seconds=1, observations=None):
        return {
            "outcome": outcome,
            "reason": reason,
            "provider_call_seconds": seconds,
            "final_url": final_url,
            "redirect_chain": redirect_chain,
            "provider_observations": observations or self.observations(),
        }

    def denied(self, code, function, *args, **kwargs):
        with self.assertRaisesRegex(policy.PolicyError, "^" + code + "$"):
            function(*args, **kwargs)

    def test_candidate_identity_sources_and_pending_reviews(self):
        receipt = policy.verify_candidate_sources()
        self.assertEqual(receipt["source_pins_verified"], 12)
        self.assertEqual(receipt["v1_history"], "OPEN_PRESERVED_UNMODIFIED")
        self.assertEqual(receipt["v2_history"], "OPEN_PRESERVED_UNMODIFIED")
        self.assertEqual(receipt["independent_review"], "PENDING")
        self.assertEqual(receipt["adoption_review"], "PENDING")
        self.assertFalse(receipt["activation"])

    def test_no_caller_selected_policy_or_root(self):
        self.assertEqual(list(inspect.signature(policy.verify_candidate_sources).parameters), [])
        raw = Path(policy.__file__).with_name("policy-manifest-v3.json").read_bytes()
        self.assertFalse(policy.verify_exact_manifest(raw)["activation"])
        self.denied("CALLER_SELECTED_POLICY_DENIED", policy.verify_exact_manifest, raw + b" ")
        self.assertNotIn("root", inspect.signature(policy.CellLedger).parameters)

    def test_all_json_schemas_close_every_object(self):
        root = Path(policy.__file__).resolve().parent
        objects = 0
        for path in root.glob("*.schema.json"):
            stack = [json.loads(path.read_text())]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if node.get("type") == "object":
                        objects += 1
                        self.assertIs(node.get("additionalProperties"), False, path.name)
                        self.assertEqual(set(node["required"]), set(node["properties"]), path.name)
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
        self.assertGreater(objects, 20)

    def test_search_requires_one_nonempty_utf8_query_and_exact_domains(self):
        policy.validate_logical_request(self.search("évidence"))
        self.denied("QUERY_MUST_BE_NONEMPTY_UTF8", policy.validate_logical_request, self.search(""))
        self.denied("QUERY_MUST_BE_NONEMPTY_UTF8", policy.validate_logical_request, self.search("\ud800"))
        changed = self.search(); changed["allowed_domains"] = ["www.sec.gov"]
        self.denied("ALLOWED_DOMAINS_DRIFT", policy.validate_logical_request, changed)

    def test_option_smuggling_is_rejected(self):
        for extra in ("blocked_domains", "recency", "offset", "headers", "cookies", "auth", "method", "form", "upload", "mcp", "bytedcli", "response_length"):
            value = self.search(); value[extra] = "smuggled"
            self.denied("EXTRA_PROVIDER_OPTION_DENIED", policy.validate_logical_request, value)

    def test_exact_native_search_translations(self):
        claude = policy.CellLedger().reserve_and_translate("claude", self.search("query"))
        self.assertEqual(claude["tool_identity"], "claude_code.WebSearch")
        self.assertEqual(claude["native_input"], {"query": "query", "allowed_domains": list(policy.ALLOWED_DOMAINS)})
        codex = policy.CellLedger().reserve_and_translate("codex", self.search("query"))
        self.assertEqual(codex["tool_identity"], "native_tools.web__run")
        self.assertEqual(codex["native_input"], {"search_query": [{"q": "query", "domains": list(policy.ALLOWED_DOMAINS)}], "response_length": "long"})
        self.assertTrue(codex["dispatch_reserved"])
        self.assertFalse(codex["live_invocation_performed"])

    def test_exact_native_fetch_translations_and_prompt(self):
        url = "https://www.microsoft.com/en-us/Investor/report"
        claude = policy.CellLedger().reserve_and_translate("claude", self.fetch(url))
        self.assertEqual(claude["native_input"], {"url": url, "prompt": policy.FETCH_PROMPT})
        codex = policy.CellLedger().reserve_and_translate("codex", self.fetch(url))
        self.assertEqual(codex["native_input"], {"open": [{"ref_id": url}], "response_length": "long"})
        changed = self.fetch(url); changed["prompt"] += " changed"
        self.denied("FETCH_PROMPT_DRIFT", policy.validate_logical_request, changed)

    def test_provider_and_operation_drift(self):
        self.denied("UNKNOWN_PROVIDER", policy.CellLedger().reserve_and_translate, "other", self.search())
        self.denied("UNKNOWN_OPERATION", policy.validate_logical_request, {"operation": "find"})

    def test_unequal_operation_ceilings_and_nonaggregate_alias(self):
        ledger = policy.CellLedger()
        ledger.reserve_and_translate("claude", self.search("one"))
        ledger.reserve_and_translate("codex", self.search("two"))
        self.denied("SEARCH_DISPATCH_CEILING_EXCEEDED", ledger.reserve_and_translate, "claude", self.search("three"))
        for number in range(6):
            ledger.reserve_and_translate("claude", self.fetch(f"https://www.sec.gov/Archives/{number}"))
        self.denied("FETCH_DISPATCH_CEILING_EXCEEDED", ledger.reserve_and_translate, "codex", self.fetch("https://www.sec.gov/Archives/seven"))
        counters = ledger.counters()
        self.assertEqual((counters["web_search_reserved"], counters["web_fetch_reserved"]), (2, 6))
        self.assertEqual(counters["web_policy_search_alias"], 2)
        self.assertFalse(counters["web_policy_is_aggregate"])

    def test_fail_and_unknown_both_consume_without_replay(self):
        for outcome in ("FAIL", "UNKNOWN"):
            ledger = policy.CellLedger()
            reserved = ledger.reserve_and_translate("claude", self.search())
            result = ledger.settle(reserved["reservation_id"], self.report(outcome=outcome, reason=outcome))
            self.assertEqual(result["outcome"], outcome)
            self.assertTrue(result["consumed"])
            self.assertFalse(result["retry"] or result["replay"] or result["status_query"])
            self.denied("RETRY_REPLAY_STATUS_QUERY_DENIED", ledger.settle, reserved["reservation_id"], self.report(outcome=outcome))

    def test_malformed_settlement_still_consumes_unknown(self):
        ledger = policy.CellLedger(); reserved = ledger.reserve_and_translate("claude", self.search())
        malformed = self.report(); malformed["extra"] = True
        self.denied("SETTLEMENT_REPORT_SHAPE", ledger.settle, reserved["reservation_id"], malformed)
        self.assertEqual(ledger.counters()["outcomes"]["UNKNOWN"], 1)
        self.denied("RETRY_REPLAY_STATUS_QUERY_DENIED", ledger.settle, reserved["reservation_id"], self.report())

    def test_host_subdomain_case_and_trailing_dot_drift(self):
        urls = [
            "https://sec.gov/Archives/a", "https://sub.www.sec.gov/Archives/a",
            "https://WWW.SEC.GOV/Archives/a", "https://www.sec.gov./Archives/a",
        ]
        codes = ["EXACT_HOST_DENIED", "EXACT_HOST_DENIED", "HOST_CASE_OR_AUTHORITY_DRIFT", "EXACT_HOST_DENIED"]
        for url, code in zip(urls, codes):
            self.denied(code, policy.validate_logical_request, self.fetch(url))

    def test_path_prefix_and_case_drift(self):
        policy.validate_logical_request(self.fetch("https://www.sec.gov/Archives/a"))
        policy.validate_logical_request(self.fetch("https://www.microsoft.com/en-us/Investor/a"))
        for url in ("https://www.sec.gov/archives/a", "https://www.sec.gov/about", "https://www.microsoft.com/en-us/investor/a"):
            self.denied("EVIDENCE_PATH_DENIED", policy.validate_logical_request, self.fetch(url))

    def test_ip_idn_internal_userinfo_fragment_scheme_and_port_denials(self):
        cases = [
            ("https://127.0.0.1/Archives/a", "LITERAL_IP_DENIED"),
            ("https://www.séc.gov/Archives/a", "IDN_OR_NONASCII_HOST_DENIED"),
            ("https://service.internal/Archives/a", "PRIVATE_LOCAL_INTERNAL_HOST_DENIED"),
            ("https://user@www.sec.gov/Archives/a", "USERINFO_DENIED"),
            ("https://www.sec.gov/Archives/a#x", "FRAGMENT_DENIED"),
            ("http://www.sec.gov/Archives/a", "HTTPS_REQUIRED"),
            ("https://www.sec.gov:444/Archives/a", "NON_DEFAULT_PORT_DENIED"),
        ]
        for url, code in cases:
            self.denied(code, policy.validate_logical_request, self.fetch(url))

    def test_search_result_outside_path_is_observed_not_evidence(self):
        self.assertEqual(policy.classify_search_result_url("https://www.sec.gov/about"), "OBSERVED_NOT_EVIDENCE_NOT_FETCHABLE")
        self.assertEqual(policy.classify_search_result_url("https://www.sec.gov/Archives/a"), "EVIDENCE_ELIGIBLE")
        self.denied("EVIDENCE_PATH_DENIED", policy.validate_logical_request, self.fetch("https://www.sec.gov/about"))

    def test_redirect_or_final_origin_drift_is_unknown_no_replay(self):
        ledger = policy.CellLedger(); reserved = ledger.reserve_and_translate("codex", self.fetch())
        result = ledger.settle(reserved["reservation_id"], self.report(final_url=self.fetch()["url"], redirect_chain=[self.fetch()["url"]]), captured_result=b"ok")
        self.assertEqual((result["outcome"], result["reason"]), ("UNKNOWN", "REDIRECT_OR_FINAL_ORIGIN_DRIFT_UNKNOWN_NO_REPLAY"))

    def test_unavailable_final_origin_is_unknown_no_replay(self):
        ledger = policy.CellLedger(); reserved = ledger.reserve_and_translate("claude", self.fetch())
        result = ledger.settle(reserved["reservation_id"], self.report(final_url=None, redirect_chain=None), captured_result=b"ok")
        self.assertEqual((result["outcome"], result["reason"]), ("UNKNOWN", "FINAL_ORIGIN_UNAVAILABLE_UNKNOWN_NO_REPLAY"))

    def test_exact_final_origin_fetch_can_pass(self):
        ledger = policy.CellLedger(); request = self.fetch(); reserved = ledger.reserve_and_translate("claude", request)
        result = ledger.settle(reserved["reservation_id"], self.report(final_url=request["url"], redirect_chain=[]), captured_result=b"ok")
        self.assertEqual(result["outcome"], "PASS")

    def test_captured_fetch_result_limit(self):
        for size, expected in ((65536, "PASS"), (65537, "UNKNOWN")):
            ledger = policy.CellLedger(); request = self.fetch(); reserved = ledger.reserve_and_translate("claude", request)
            result = ledger.settle(reserved["reservation_id"], self.report(final_url=request["url"], redirect_chain=[]), captured_result=b"x" * size)
            self.assertEqual(result["outcome"], expected)

    def test_provider_call_time_limit(self):
        for seconds, expected in ((600, "PASS"), (601, "UNKNOWN")):
            ledger = policy.CellLedger(); request = self.fetch(); reserved = ledger.reserve_and_translate("codex", request)
            result = ledger.settle(reserved["reservation_id"], self.report(final_url=request["url"], redirect_chain=[], seconds=seconds), captured_result=b"ok")
            self.assertEqual(result["outcome"], expected)

    def test_cell_window_limit_before_and_after_reservation(self):
        ledger = policy.CellLedger(); ledger._started -= 1801
        self.denied("CELL_WINDOW_EXCEEDED", ledger.reserve_and_translate, "claude", self.search())
        ledger = policy.CellLedger(); request = self.fetch(); reserved = ledger.reserve_and_translate("claude", request); ledger._started -= 1801
        result = ledger.settle(reserved["reservation_id"], self.report(final_url=request["url"], redirect_chain=[]), captured_result=b"ok")
        self.assertEqual((result["outcome"], result["reason"]), ("UNKNOWN", "CELL_WINDOW_UNKNOWN_NO_REPLAY"))

    def test_provider_internal_observations_are_not_equalized(self):
        ledger = policy.CellLedger(); reserved = ledger.reserve_and_translate("claude", self.search())
        result = ledger.settle(reserved["reservation_id"], self.report(observations=self.observations(http_requests=3, cache="hit", ranking="native", result_count=7)))
        self.assertEqual(result["provider_observations"]["result_count"], 7)
        ledger = policy.CellLedger(); reserved = ledger.reserve_and_translate("codex", self.search())
        self.denied("PROVIDER_INTERNAL_EQUALITY_CLAIM_DENIED", ledger.settle, reserved["reservation_id"], self.report(observations=self.observations(equality_claimed=True)))

    def test_local_manifest_and_source_pin_drift_fail_closed(self):
        original = policy._read_bytes
        with mock.patch.object(policy, "_read_bytes", side_effect=lambda path: original(path) + b" " if path == policy._MANIFEST else original(path)):
            with self.assertRaises(policy.PolicyError):
                policy.verify_candidate_sources()
        target = policy._ROOT / "docs/plans/codex-claude-acquisition-adapters.md"
        with mock.patch.object(policy, "_read_bytes", side_effect=lambda path: b"drift" if path == target else original(path)):
            self.denied("SOURCE_PIN_DRIFT", policy.verify_candidate_sources)

    def test_distinct_producer_verifier_is_provider_free(self):
        from shared.job_runtime.candidates.r6_frozen_tool_web_allowance_v3 import producer_verification
        source = inspect.getsource(producer_verification)
        self.assertNotIn("from .policy", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("import subprocess", source)
        receipt = build_receipt()
        self.assertEqual(receipt["source_pins_verified"], 12)
        self.assertTrue(all(value is False for value in receipt["effects_executed"].values()))
        self.assertEqual(receipt["independent_review"], "PENDING")
        self.assertEqual(receipt["adoption_review"], "PENDING")


if __name__ == "__main__":
    unittest.main()
