from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import inspect
import json
from pathlib import Path
import unittest
from unittest import mock

from jsonschema import Draft202012Validator

from shared.job_runtime.candidates.r6_frozen_tool_web_allowance_v5 import policy
from shared.job_runtime.candidates.r6_frozen_tool_web_allowance_v5.producer_verification import build_receipt


class FrozenWebAllowanceV5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(policy.__file__).resolve().parent
        cls.schemas = {
            "logical": json.loads((root / "logical-request-v5.schema.json").read_text()),
            "translation": json.loads((root / "translation-receipt-v5.schema.json").read_text()),
            "settlement": json.loads((root / "settlement-receipt-v5.schema.json").read_text()),
            "manifest": json.loads((root / "policy-manifest-v5.schema.json").read_text()),
        }
        cls.validators = {name: Draft202012Validator(value) for name, value in cls.schemas.items()}

    def search(self, query="Microsoft filing"):
        return {"operation": "web_search", "query": query, "allowed_domains": list(policy.ALLOWED_DOMAINS)}

    def fetch(self, url="https://www.sec.gov/Archives/example.htm"):
        return {"operation": "web_fetch", "url": url, "prompt": policy.FETCH_PROMPT}

    def observations(self, **changes):
        value = {"http_requests": None, "cache": None, "ranking": None, "result_count": None, "equality_claimed": False}
        value.update(changes)
        return value

    def report(self, outcome="PASS", reason="NATIVE_TERMINAL", final_url=None, redirect_chain=None, seconds=1, observations=None):
        return {"outcome": outcome, "reason": reason, "provider_call_seconds": seconds, "final_url": final_url,
                "redirect_chain": redirect_chain, "provider_observations": observations or self.observations()}

    def denied(self, function, *args, **kwargs):
        with self.assertRaises(policy.PolicyError):
            function(*args, **kwargs)

    def assert_schema_valid(self, name, value):
        self.validators[name].validate(value)

    def assert_schema_invalid(self, name, value):
        self.assertFalse(self.validators[name].is_valid(value), value)

    def test_candidate_identity_authority_and_open_history(self):
        receipt = policy.verify_candidate_sources()
        self.assertGreaterEqual(receipt["source_pins_verified"], 16)
        self.assertEqual((receipt["v1_history"], receipt["v2_history"], receipt["v3_history"], receipt["v4_history"]),
                         ("OPEN_PRESERVED_UNMODIFIED",) * 4)
        self.assertEqual(receipt["owner_adoption_review"], "CLEAN_TOOL_POLICY_ADOPTION")
        self.assertEqual(receipt["independent_review"], "PENDING_FRESH_V5_REVIEW")
        self.assertFalse(receipt["activation"])

    def test_no_caller_policy_root_or_live_effect_surface(self):
        self.assertEqual(list(inspect.signature(policy.verify_candidate_sources).parameters), [])
        raw = Path(policy.__file__).with_name("policy-manifest-v5.json").read_bytes()
        self.assertFalse(policy.verify_exact_manifest(raw)["activation"])
        self.denied(policy.verify_exact_manifest, raw + b" ")
        self.assertNotIn("root", inspect.signature(policy.CellLedger).parameters)
        source = inspect.getsource(policy)
        for denied_import in ("import requests", "import socket", "import subprocess", "bytedcli"):
            self.assertNotIn(denied_import, source)

    def test_draft_2020_12_metaschemas_and_closed_objects(self):
        objects = 0
        for schema in self.schemas.values():
            Draft202012Validator.check_schema(schema)
            stack = [schema]
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
        self.assertGreater(objects, 20)

    def test_url_bypass_matrix_runtime_and_schema(self):
        denied = [
            "http://www.sec.gov/Archives/a",
            "https://www.sec.gov:444/Archives/a",
            "https://user@www.sec.gov/Archives/a",
            "https://www.sec.gov/Archives/a#fragment",
            "https://127.0.0.1/Archives/a",
            "https://www.séc.gov/Archives/a",
            "https://WWW.SEC.GOV/Archives/a",
            "https://www.sec.gov./Archives/a",
            "https://sub.www.sec.gov/Archives/a",
            "https://www.sec.gov/Archives/../about",
            "https://www.sec.gov/Archives/./a",
            "https://www.sec.gov/Archives/%2e%2e/about",
            "https://www.sec.gov/Archives/%2E%2E/about",
            "https://www.sec.gov/Archives/%252e%252e/about",
            "https://www.sec.gov/Archives/%2fabout",
            "https://www.sec.gov/Archives/%252fabout",
            "https://www.sec.gov/Archives/%5cabout",
            "https://www.sec.gov/Archives/%255cabout",
            "https://www.sec.gov/Archives/%3fquery",
            "https://www.sec.gov/Archives/%253fquery",
            "https://www.sec.gov/Archives//a",
            "https://www.sec.gov/Archives\\a",
            "https://www.sec.gov/Archives/\x00a",
            "https://www.sec.gov/about?path=/Archives/a",
            "https://www.sec.gov/?path=/Archives/a",
            "https://www.sec.gov/Archives?path=/Archives/a",
            "https://www.microsoft.com/en-us/Investor/../security",
            "https://www.microsoft.com/en-us/investor/a",
        ]
        observed_only = {
            "https://www.sec.gov/about?path=/Archives/a",
            "https://www.sec.gov/?path=/Archives/a",
            "https://www.sec.gov/Archives?path=/Archives/a",
            "https://www.microsoft.com/en-us/investor/a",
        }
        for url in denied:
            request = self.fetch(url)
            self.denied(policy.validate_logical_request, request)
            if url in observed_only:
                self.assertEqual(policy.classify_search_result_url(url), "OBSERVED_NOT_EVIDENCE_NOT_FETCHABLE")
            else:
                self.denied(policy.classify_search_result_url, url)
            self.assert_schema_invalid("logical", request)
        allowed = [
            "https://www.sec.gov/Archives/a",
            "https://www.sec.gov:443/edgar/a?next=../outside",
            "https://www.microsoft.com/en-us/Investor/report?path=/about",
        ]
        for url in allowed:
            request = self.fetch(url)
            self.assertEqual(policy.validate_logical_request(request)["url"], url)
            self.assertEqual(policy.classify_search_result_url(url), "EVIDENCE_ELIGIBLE")
            self.assert_schema_valid("logical", request)

    def test_search_outside_prefix_is_observable_only(self):
        url = "https://www.sec.gov/about"
        self.assertEqual(policy.classify_search_result_url(url), "OBSERVED_NOT_EVIDENCE_NOT_FETCHABLE")
        self.denied(policy.validate_logical_request, self.fetch(url))
        self.assert_schema_invalid("logical", self.fetch(url))

    def test_logical_schema_nested_and_field_mutations(self):
        search = self.search("évidence")
        fetch = self.fetch()
        self.assert_schema_valid("logical", search)
        self.assert_schema_valid("logical", fetch)
        variants = [
            {**search, "headers": {}},
            {**search, "allowed_domains": ["www.sec.gov"]},
            {**search, "query": ""},
            {**search, "query": "\ud800"},
            {**fetch, "prompt": policy.FETCH_PROMPT + " drift"},
            {**fetch, "url": "http://evil.example/Archives/a"},
            {**fetch, "url": {"value": fetch["url"], "extra": True}},
        ]
        for value in variants:
            self.assert_schema_invalid("logical", value)

    def test_invalid_provider_request_operation_consume_zero(self):
        ledger = policy.CellLedger()
        before = ledger.counters()
        for provider, request in [
            ("other", self.search()),
            (None, self.search()),
            ("claude", {"operation": "find"}),
            ("codex", {**self.search(), "headers": {}}),
            ("claude", self.fetch("https://www.sec.gov/Archives/../about")),
        ]:
            self.denied(ledger.reserve_and_translate, provider, request)
            self.assertEqual(ledger.counters(), before)
        self.assertEqual(before["reservation_receipts"], 0)
        self.assertEqual(before["unreceipted_capacity_loss"], 0)

    def test_atomic_unique_immutable_receipt_and_counter_invariants(self):
        ledger = policy.CellLedger()
        receipt = ledger.reserve_and_translate("claude", self.search("one"))
        original = copy.deepcopy(receipt)
        receipt["provider"] = "mutated"
        receipt["native_input"]["query"] = "mutated"
        state = ledger.receipt_state(original["reservation_id"])
        self.assertEqual(state["translation"], original)
        counters = ledger.counters()
        self.assertEqual(counters["reservation_receipts"], counters["reserved_total_observational_only"])
        self.assertEqual(counters["unreceipted_capacity_loss"], 0)
        self.assertEqual(counters["unsettled_total"], 1)

    def test_concurrent_reservations_are_bounded_unique_and_receipted(self):
        ledger = policy.CellLedger()
        def attempt(i):
            try:
                return ledger.reserve_and_translate("claude", self.search(str(i)))
            except policy.PolicyError:
                return None
        with ThreadPoolExecutor(max_workers=12) as pool:
            receipts = [value for value in pool.map(attempt, range(24)) if value is not None]
        self.assertEqual(len(receipts), 2)
        self.assertEqual(len({item["reservation_id"] for item in receipts}), 2)
        counters = ledger.counters()
        self.assertEqual(counters["web_search_reserved"], 2)
        self.assertEqual(counters["reservation_receipts"], 2)
        self.assertEqual(counters["unreceipted_capacity_loss"], 0)
        for item in receipts:
            ledger.settle(item["reservation_id"], self.report(outcome="UNKNOWN", reason="PROVIDER_UNKNOWN"))
        counters = ledger.counters()
        self.assertEqual(counters["settled_total"], 2)
        self.assertEqual(counters["unsettled_total"], 0)
        self.assertEqual(sum(counters["outcomes"].values()), counters["reservation_receipts"])

    def test_translation_schema_binds_provider_operation_tool_and_nested_shape(self):
        receipts = [
            policy.CellLedger().reserve_and_translate("claude", self.search()),
            policy.CellLedger().reserve_and_translate("claude", self.fetch()),
            policy.CellLedger().reserve_and_translate("codex", self.search()),
            policy.CellLedger().reserve_and_translate("codex", self.fetch()),
        ]
        for receipt in receipts:
            self.assert_schema_valid("translation", receipt)
        base = receipts[0]
        mutations = []
        for field, value in [("provider", "codex"), ("operation", "web_fetch"), ("tool_identity", "claude_code.WebFetch")]:
            changed = copy.deepcopy(base); changed[field] = value; mutations.append(changed)
        changed = copy.deepcopy(base); changed["native_input"]["extra"] = True; mutations.append(changed)
        changed = copy.deepcopy(base); changed["native_input"]["allowed_domains"] = ["www.sec.gov"]; mutations.append(changed)
        changed = copy.deepcopy(base); changed["search_dispatch_ordinal"] = 0; mutations.append(changed)
        for value in mutations:
            self.assert_schema_invalid("translation", value)

    def test_all_terminal_outcomes_settle_exactly_once(self):
        for outcome in ("PASS", "FAIL", "UNKNOWN"):
            ledger = policy.CellLedger()
            reserved = ledger.reserve_and_translate("claude", self.search())
            settled = ledger.settle(reserved["reservation_id"], self.report(outcome=outcome, reason=outcome))
            self.assertEqual(settled["outcome"], outcome)
            self.assert_schema_valid("settlement", settled)
            state = ledger.receipt_state(reserved["reservation_id"])
            self.assertIsNotNone(state["settlement"])
            counters = ledger.counters()
            self.assertEqual(counters["settled_total"], 1)
            self.assertEqual(counters["unsettled_total"], 0)
            self.denied(ledger.settle, reserved["reservation_id"], self.report(outcome=outcome))
            self.assertEqual(ledger.counters(), counters)

    def test_malformed_settlement_is_receipted_unknown_once(self):
        ledger = policy.CellLedger()
        reserved = ledger.reserve_and_translate("codex", self.fetch())
        malformed = self.report(); malformed["extra"] = True
        self.denied(ledger.settle, reserved["reservation_id"], malformed)
        state = ledger.receipt_state(reserved["reservation_id"])
        self.assertEqual(state["settlement"]["outcome"], "UNKNOWN")
        self.assertEqual(state["settlement"]["reason"], "MALFORMED_SETTLEMENT_CONSUMED_UNKNOWN_NO_REPLAY")
        self.assert_schema_valid("settlement", state["settlement"])
        counters = ledger.counters()
        self.assertEqual(counters["outcomes"], {"PASS": 0, "FAIL": 0, "UNKNOWN": 1})
        self.assertEqual(counters["unreceipted_capacity_loss"], 0)

    def test_pass_fetch_exact_final_origin_and_bounds(self):
        ledger = policy.CellLedger(); request = self.fetch(); reserved = ledger.reserve_and_translate("claude", request)
        settled = ledger.settle(reserved["reservation_id"], self.report(final_url=request["url"], redirect_chain=[]), captured_result=b"x" * 65536)
        self.assertEqual(settled["outcome"], "PASS")
        self.assertEqual(settled["verified_canonical_url"], request["url"])
        self.assertNotIn("requested_url", settled)
        self.assertNotIn("final_url", settled)
        self.assertEqual(settled["redirect_count"], 0)
        self.assert_schema_valid("settlement", settled)

    def test_breaches_and_origin_uncertainty_become_unknown_no_replay(self):
        cases = [
            (601, b"ok", self.fetch()["url"], [], "PROVIDER_TIMEOUT_UNKNOWN_NO_REPLAY"),
            (1, b"x" * 65537, self.fetch()["url"], [], "CAPTURED_RESULT_OVERSIZE_UNKNOWN_NO_REPLAY"),
            (1, b"ok", None, None, "FINAL_ORIGIN_UNAVAILABLE_UNKNOWN_NO_REPLAY"),
            (1, b"ok", "https://www.sec.gov/Archives/../about", [], "FINAL_ORIGIN_POLICY_UNKNOWN_NO_REPLAY"),
            (1, b"ok", "https://www.sec.gov/Archives/other", [], "REDIRECT_OR_FINAL_ORIGIN_DRIFT_UNKNOWN_NO_REPLAY"),
            (1, b"ok", self.fetch()["url"], [self.fetch()["url"]], "REDIRECT_OR_FINAL_ORIGIN_DRIFT_UNKNOWN_NO_REPLAY"),
        ]
        for seconds, body, final_url, chain, reason in cases:
            ledger = policy.CellLedger(); request = self.fetch(); reserved = ledger.reserve_and_translate("codex", request)
            settled = ledger.settle(reserved["reservation_id"], self.report(final_url=final_url, redirect_chain=chain, seconds=seconds), captured_result=body)
            self.assertEqual((settled["outcome"], settled["reason"]), ("UNKNOWN", reason))
            self.assertFalse(settled["retry"] or settled["replay"] or settled["status_query"])
            self.assert_schema_valid("settlement", settled)

    def test_cell_window_breach_becomes_unknown(self):
        ledger = policy.CellLedger(); request = self.fetch(); reserved = ledger.reserve_and_translate("claude", request)
        ledger._started -= 1801
        settled = ledger.settle(reserved["reservation_id"], self.report(final_url=request["url"], redirect_chain=[]), captured_result=b"ok")
        self.assertEqual((settled["outcome"], settled["reason"]), ("UNKNOWN", "CELL_WINDOW_UNKNOWN_NO_REPLAY"))
        self.assert_schema_valid("settlement", settled)

    def test_settlement_schema_rejects_impossible_and_nested_mutations(self):
        ledger = policy.CellLedger(); request = self.fetch(); reserved = ledger.reserve_and_translate("claude", request)
        base = ledger.settle(reserved["reservation_id"], self.report(final_url=request["url"], redirect_chain=[]), captured_result=b"ok")
        mutations = []
        for field, value in [
            ("captured_result_bytes", 65537), ("provider_call_seconds", 601), ("cell_elapsed_seconds", 1801),
            ("final_url", None), ("redirect_count", 1), ("final_url_matches_request", False),
            ("final_url_evidence_eligible", False), ("operation", "web_search"),
        ]:
            changed = copy.deepcopy(base); changed[field] = value; mutations.append(changed)
        changed = copy.deepcopy(base); changed["provider_observations"]["extra"] = True; mutations.append(changed)
        changed = copy.deepcopy(base); changed["reason"] = "PROVIDER_TIMEOUT_UNKNOWN_NO_REPLAY"; mutations.append(changed)
        changed = copy.deepcopy(base); changed["extra"] = True; mutations.append(changed)
        for value in mutations:
            self.assert_schema_invalid("settlement", value)

    def test_provider_observations_retained_without_equality_claim(self):
        ledger = policy.CellLedger(); reserved = ledger.reserve_and_translate("claude", self.search())
        settled = ledger.settle(reserved["reservation_id"], self.report(observations=self.observations(http_requests=3, cache="hit", ranking="native", result_count=7)))
        self.assertEqual(settled["provider_observations"]["result_count"], 7)
        ledger = policy.CellLedger(); reserved = ledger.reserve_and_translate("codex", self.search())
        self.denied(ledger.settle, reserved["reservation_id"], self.report(observations=self.observations(equality_claimed=True)))
        self.assertEqual(ledger.counters()["outcomes"]["UNKNOWN"], 1)

    def test_source_and_manifest_drift_fail_closed(self):
        original = policy._read_bytes
        with mock.patch.object(policy, "_read_bytes", side_effect=lambda path: original(path) + b" " if path == policy._MANIFEST else original(path)):
            self.denied(policy.verify_candidate_sources)
        target = policy._ROOT / "tuning/architecture/r6_frozen_tool_web_allowance_v4/source-closure-v4.json"
        with mock.patch.object(policy, "_read_bytes", side_effect=lambda path: b"drift" if path == target else original(path)):
            self.denied(policy.verify_candidate_sources)

    def test_distinct_producer_verifier_is_provider_free(self):
        from shared.job_runtime.candidates.r6_frozen_tool_web_allowance_v5 import producer_verification
        source = inspect.getsource(producer_verification)
        self.assertNotIn("from .policy", source)
        for denied_import in ("import requests", "import socket", "import subprocess"):
            self.assertNotIn(denied_import, source)
        receipt = build_receipt()
        self.assertGreaterEqual(receipt["source_pins_verified"], 16)
        self.assertEqual(receipt["draft_2020_12_metaschema"], "PASS")
        self.assertEqual(receipt["fresh_independent_review"], "PENDING")
        self.assertTrue(all(value is False for value in receipt["effects_executed"].values()))


    def test_reviewed_logical_trailing_lf_cr_and_all_controls_rejected(self):
        base = "https://www.sec.gov/Archives/a"
        controls = [chr(value) for value in range(32)] + [chr(127), "\u2028", "\u2029"]
        self.assertIn("\n", controls)
        self.assertIn("\r", controls)
        for control in controls:
            for url in (base + control, base + control + "z"):
                request = self.fetch(url)
                self.denied(policy.validate_logical_request, request)
                self.assert_schema_invalid("logical", request)

    def test_reviewed_nested_translation_controls_rejected_for_both_providers(self):
        controls = [chr(value) for value in range(32)] + [chr(127), "\u2028", "\u2029"]
        claude = policy.CellLedger().reserve_and_translate("claude", self.fetch())
        codex = policy.CellLedger().reserve_and_translate("codex", self.fetch())
        for control in controls:
            for embedded in (False, True):
                suffix = control + ("z" if embedded else "")
                changed = copy.deepcopy(claude)
                changed["native_input"]["url"] += suffix
                self.assert_schema_invalid("translation", changed)
                changed = copy.deepcopy(codex)
                changed["native_input"]["open"][0]["ref_id"] += suffix
                self.assert_schema_invalid("translation", changed)

    def test_pass_settlement_has_one_verified_url_identity_and_no_equality_pair(self):
        ledger = policy.CellLedger(); request = self.fetch(); reserved = ledger.reserve_and_translate("claude", request)
        base = ledger.settle(reserved["reservation_id"], self.report(final_url=request["url"], redirect_chain=[]), captured_result=b"ok")
        self.assert_schema_valid("settlement", base)
        self.assertEqual(base["verified_canonical_url"], request["url"])
        forbidden = {"requested_url", "final_url", "final_url_matches_request", "final_url_evidence_eligible"}
        self.assertTrue(forbidden.isdisjoint(base))
        self.assertTrue(forbidden.isdisjoint(self.schemas["settlement"]["properties"]))
        # Exact v4 review mutation cannot be represented: adding either side or
        # the caller assertion is rejected by the closed top-level object.
        for field, value in [
            ("requested_url", request["url"]),
            ("final_url", "https://www.sec.gov/Archives/different"),
            ("final_url_matches_request", True),
            ("final_url_evidence_eligible", True),
        ]:
            changed = copy.deepcopy(base); changed[field] = value
            self.assert_schema_invalid("settlement", changed)
        for control in ("\n", "\r", "\x00", "\x1f", "\x7f", "\u2028", "\u2029"):
            changed = copy.deepcopy(base); changed["verified_canonical_url"] += control
            self.assert_schema_invalid("settlement", changed)

    def test_runtime_mismatched_final_url_is_unknown_without_url_identity(self):
        ledger = policy.CellLedger(); request = self.fetch(); reserved = ledger.reserve_and_translate("codex", request)
        settled = ledger.settle(reserved["reservation_id"], self.report(final_url="https://www.sec.gov/Archives/different", redirect_chain=[]), captured_result=b"ok")
        self.assertEqual((settled["outcome"], settled["reason"]), ("UNKNOWN", "REDIRECT_OR_FINAL_ORIGIN_DRIFT_UNKNOWN_NO_REPLAY"))
        self.assertIsNone(settled["verified_canonical_url"])
        self.assertFalse(settled["retry"] or settled["replay"] or settled["status_query"])
        self.assert_schema_valid("settlement", settled)


if __name__ == "__main__":
    unittest.main()
