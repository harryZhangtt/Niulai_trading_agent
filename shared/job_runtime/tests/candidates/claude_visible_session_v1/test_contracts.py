from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
import re
import unittest

from _loader import package


ROOT = Path(__file__).resolve().parents[3]
CANDIDATE = ROOT / "candidates" / "claude_visible_session_v1"
FIXTURES = ROOT / "tests" / "fixtures" / "claude_visible_session_v1"
SCHEMAS = CANDIDATE / "schemas"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def strict_equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(right, dict):
        return set(left) == set(right) and all(strict_equal(left[key], right[key]) for key in right)
    if isinstance(right, list):
        return len(left) == len(right) and all(strict_equal(a, b) for a, b in zip(left, right))
    return left == right


class SchemaFailure(ValueError):
    pass


def validate_schema(instance, schema, schema_dir=SCHEMAS):
    """Small dependency-free checker for the frozen schema vocabulary in this candidate."""
    if "$ref" in schema:
        return validate_schema(instance, read_json(schema_dir / schema["$ref"]), schema_dir)
    if "oneOf" in schema:
        matches = 0
        for branch in schema["oneOf"]:
            try:
                validate_schema(instance, branch, schema_dir)
                matches += 1
            except SchemaFailure:
                pass
        if matches != 1:
            raise SchemaFailure("oneOf matched {0} branches".format(matches))
    if "const" in schema and not strict_equal(instance, schema["const"]):
        raise SchemaFailure("const mismatch")
    if "enum" in schema and not any(strict_equal(instance, item) for item in schema["enum"]):
        raise SchemaFailure("enum mismatch")
    expected_type = schema.get("type")
    type_checks = {
        "object": lambda value: type(value) is dict,
        "array": lambda value: type(value) is list,
        "string": lambda value: type(value) is str,
        "integer": lambda value: type(value) is int,
        "null": lambda value: value is None,
    }
    if expected_type and not type_checks[expected_type](instance):
        raise SchemaFailure("type mismatch")
    if expected_type == "object":
        required = set(schema.get("required", []))
        if not required.issubset(instance):
            raise SchemaFailure("missing key")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and not set(instance).issubset(properties):
            raise SchemaFailure("extra key")
        for key, subschema in properties.items():
            if key in instance:
                validate_schema(instance[key], subschema, schema_dir)
    if expected_type == "array":
        if len(instance) < schema.get("minItems", 0):
            raise SchemaFailure("too few items")
        for item in instance:
            validate_schema(item, schema.get("items", {}), schema_dir)
    if expected_type == "integer" and instance < schema.get("minimum", instance):
        raise SchemaFailure("below minimum")
    if expected_type == "string" and "pattern" in schema and re.fullmatch(schema["pattern"], instance) is None:
        raise SchemaFailure("pattern mismatch")


class FrozenContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = package()
        cls.cases = cls.api.load_frozen_cases()
        cls.r9 = read_json(FIXTURES / "r9" / "evidence.json")
        cls.r10 = read_json(FIXTURES / "r10" / "evidence.json")
        cls.case_schema = read_json(SCHEMAS / "case-v1.schema.json")
        cls.evidence_schema = read_json(SCHEMAS / "evidence-v1.schema.json")

    def assert_evidence_rejected(self, case_id, evidence):
        with self.assertRaises(self.api.ContractError):
            self.api.validate_evidence_bundle(self.cases[case_id], evidence)
        with self.assertRaises(SchemaFailure):
            validate_schema(evidence, self.evidence_schema)

    def assert_case_rejected(self, case):
        with self.assertRaises(self.api.ContractError):
            self.api.validate_case(case)
        with self.assertRaises(SchemaFailure):
            validate_schema(case, self.case_schema)

    def test_recursive_authorities_are_private_immutable_and_stable(self):
        authority = importlib.import_module("claude_visible_session_v1.contracts")
        self.assertFalse(any(name in authority.__dict__ for name in (
            "FROZEN_BUDGETS", "FROZEN_OBSERVED_BUDGETS", "FROZEN_TOOL_EVENTS",
        )))
        baseline_budget = authority._thaw(authority._FROZEN_BUDGETS)
        baseline_observed = authority._thaw(authority._FROZEN_OBSERVED_BUDGETS)
        baseline_tools = authority._thaw(authority._FROZEN_TOOL_EVENTS)
        with self.assertRaises(TypeError):
            authority._FROZEN_BUDGETS["R9"]["max_tool_calls"] = 99
        with self.assertRaises(TypeError):
            authority._FROZEN_OBSERVED_BUDGETS["R10"]["tool_calls"] = 99
        with self.assertRaises(TypeError):
            authority._FROZEN_TOOL_EVENTS["R10"][0]["tool"] = "Bash"
        with self.assertRaises(AttributeError):
            authority._FROZEN_TOOL_EVENTS["R10"].append("unexpected")
        self.assertEqual(authority._thaw(authority._FROZEN_BUDGETS), baseline_budget)
        self.assertEqual(authority._thaw(authority._FROZEN_OBSERVED_BUDGETS), baseline_observed)
        self.assertEqual(authority._thaw(authority._FROZEN_TOOL_EVENTS), baseline_tools)
        self.api.validate_case(self.cases["R9"])
        self.api.validate_evidence_bundle(self.cases["R10"], self.r10)

    def test_bidirectional_parity_closes_alternate_timeline_gap(self):
        alternate = copy.deepcopy(self.r10)
        alternate["polls"] = [
            {"ordinal": 1, "status": "queued", "observed_at": "2099-01-01T00:00:11Z"},
            {"ordinal": 2, "status": "running", "observed_at": "2099-01-01T00:00:12Z"},
            {"ordinal": 3, "status": "succeeded", "observed_at": "2099-01-01T00:00:13Z"},
        ]
        alternate["terminal"]["completed_at"] = "2099-01-01T00:00:13Z"
        alternate["cleanup"]["completed_at"] = "2099-01-01T00:00:14Z"

        def python_accepts(value):
            try:
                self.api.validate_evidence_bundle(self.cases["R10"], value)
                return True
            except self.api.ContractError:
                return False

        def schema_accepts(value):
            try:
                validate_schema(value, self.evidence_schema)
                return True
            except SchemaFailure:
                return False

        scenarios = [self.r10, alternate]
        altered_tool = copy.deepcopy(self.r10)
        altered_tool["tool_events"][0]["target"] = "child-2"
        scenarios.append(altered_tool)
        for evidence in scenarios:
            self.assertEqual(python_accepts(evidence), schema_accepts(evidence))
        self.assertFalse(python_accepts(alternate), "alternate frozen timeline must not be Python-accepted")
        self.assertFalse(schema_accepts(alternate), "alternate frozen timeline must not be schema-accepted")

    def test_component_schema_fixtures_match_frozen_evidence(self):
        poll_schema = read_json(SCHEMAS / "poll-v1.schema.json")
        terminal_schema = read_json(SCHEMAS / "terminal-v1.schema.json")
        cleanup_schema = read_json(SCHEMAS / "cleanup-v1.schema.json")
        for evidence in (self.r9, self.r10):
            for poll in evidence["polls"]:
                validate_schema(poll, poll_schema)
            validate_schema(evidence["terminal"], terminal_schema)
            validate_schema(evidence["cleanup"], cleanup_schema)
        altered_poll = copy.deepcopy(self.r9["polls"][0])
        altered_poll["observed_at"] = "2099-01-01T00:00:09Z"
        with self.assertRaises(SchemaFailure):
            validate_schema(altered_poll, poll_schema)
        altered_terminal = copy.deepcopy(self.r10["terminal"])
        altered_terminal["completed_at"] = "2099-01-01T00:00:09Z"
        with self.assertRaises(SchemaFailure):
            validate_schema(altered_terminal, terminal_schema)
        altered_cleanup = copy.deepcopy(self.r10["cleanup"])
        altered_cleanup["completed_at"] = "2099-01-01T00:00:09Z"
        with self.assertRaises(SchemaFailure):
            validate_schema(altered_cleanup, cleanup_schema)

    def test_frozen_cases_evidence_and_schema_parity(self):
        self.assertEqual(set(self.cases), {"R9", "R10"})
        for case_id, evidence in (("R9", self.r9), ("R10", self.r10)):
            self.api.validate_case(self.cases[case_id])
            self.api.validate_evidence_bundle(self.cases[case_id], evidence)
            validate_schema(self.cases[case_id], self.case_schema)
            validate_schema(evidence, self.evidence_schema)
        self.assertEqual([branch["properties"]["case_id"]["const"] for branch in self.case_schema["oneOf"]], ["R9", "R10"])
        self.assertEqual([branch["properties"]["case_id"]["const"] for branch in self.evidence_schema["oneOf"]], ["R9", "R10"])

    def test_r9_fixture_bytes_and_digest_are_bound(self):
        payload = (FIXTURES / "r9" / "abc.bin").read_bytes()
        self.api.validate_fixture_payloads(self.cases["R9"], {"r9/abc.bin": payload})
        self.assertEqual(payload, b"abc")
        self.assertEqual(hashlib.sha256(payload).hexdigest(), self.cases["R9"]["fixture"]["sha256"])
        with self.assertRaises(self.api.ContractError):
            self.api.validate_fixture_payloads(self.cases["R9"], {"r9/abc.bin": b"abd"})

    def test_r10_input_agent_output_hashes_and_semantics_are_bound(self):
        payloads = {
            "r10/skills-input.json": (FIXTURES / "r10" / "skills-input.json").read_bytes(),
            "r10/agent-definition.json": (FIXTURES / "r10" / "agent-definition.json").read_bytes(),
            "r10/mining-output.json": (FIXTURES / "r10" / "mining-output.json").read_bytes(),
        }
        self.api.validate_fixture_payloads(self.cases["R10"], payloads)
        fixture = self.cases["R10"]["fixture"]
        self.assertEqual(hashlib.sha256(payloads["r10/skills-input.json"]).hexdigest(), fixture["input_sha256"])
        self.assertEqual(hashlib.sha256(payloads["r10/agent-definition.json"]).hexdigest(), fixture["agent_definition_sha256"])
        self.assertEqual(hashlib.sha256(payloads["r10/mining-output.json"]).hexdigest(), fixture["output_sha256"])
        tampered = dict(payloads)
        tampered["r10/mining-output.json"] = payloads["r10/mining-output.json"].replace(b"S3", b"S4", 1)
        with self.assertRaises(self.api.ContractError):
            self.api.validate_fixture_payloads(self.cases["R10"], tampered)
        missing = dict(payloads)
        missing.pop("r10/agent-definition.json")
        with self.assertRaises(self.api.ContractError):
            self.api.validate_fixture_payloads(self.cases["R10"], missing)

    def test_budget_constants_and_observed_usage_are_exact(self):
        changed_case = copy.deepcopy(self.cases["R10"])
        changed_case["budget"]["max_output_tokens"] += 1
        self.assert_case_rejected(changed_case)
        changed_evidence = copy.deepcopy(self.r10)
        changed_evidence["budget_observed"]["output_tokens"] += 1
        self.assert_evidence_rejected("R10", changed_evidence)
        bool_budget = copy.deepcopy(self.cases["R9"])
        bool_budget["budget"]["max_tool_calls"] = True
        self.assert_case_rejected(bool_budget)

    def test_observed_tool_events_are_exact_and_read_only(self):
        for mutation in ("missing", "extra", "reordered", "denied"):
            evidence = copy.deepcopy(self.r10)
            if mutation == "missing":
                evidence["tool_events"].pop()
            elif mutation == "extra":
                evidence["tool_events"].append(copy.deepcopy(evidence["tool_events"][-1]))
            elif mutation == "reordered":
                evidence["tool_events"][1], evidence["tool_events"][2] = evidence["tool_events"][2], evidence["tool_events"][1]
            else:
                evidence["tool_events"][3]["tool"] = "Bash"
            self.assert_evidence_rejected("R10", evidence)

    def test_extra_and_missing_children_are_rejected(self):
        missing = copy.deepcopy(self.r10)
        missing["terminal"]["children"] = []
        self.assert_evidence_rejected("R10", missing)
        extra = copy.deepcopy(self.r10)
        extra["terminal"]["children"].append(copy.deepcopy(extra["terminal"]["children"][0]))
        self.assert_evidence_rejected("R10", extra)

    def test_gateway_request_accounting_and_hidden_retries_are_exact(self):
        for mutation in ("extra", "missing", "retry", "duplicate"):
            evidence = copy.deepcopy(self.r10)
            if mutation == "extra":
                evidence["request_events"].append(copy.deepcopy(evidence["request_events"][-1]))
            elif mutation == "missing":
                evidence["request_events"].pop()
            elif mutation == "retry":
                evidence["request_events"][1]["attempt"] = 2
            else:
                evidence["request_events"][1]["logical_request_id"] = "r10-parent"
            self.assert_evidence_rejected("R10", evidence)

    def test_missing_terminal_and_cleanup_fail(self):
        for key in ("terminal", "cleanup"):
            evidence = copy.deepcopy(self.r9)
            del evidence[key]
            self.assert_evidence_rejected("R9", evidence)
        evidence = copy.deepcopy(self.r10)
        evidence["cleanup"]["active_children"] = 1
        self.assert_evidence_rejected("R10", evidence)

    def test_rfc3339_format_and_monotonic_order_are_required(self):
        scenarios = []
        noncanonical = copy.deepcopy(self.r10)
        noncanonical["polls"][0]["observed_at"] = "2099-01-01T00:00:01+00:00"
        scenarios.append(noncanonical)
        duplicate = copy.deepcopy(self.r10)
        duplicate["polls"][1]["observed_at"] = duplicate["polls"][0]["observed_at"]
        scenarios.append(duplicate)
        backwards = copy.deepcopy(self.r10)
        backwards["cleanup"]["completed_at"] = "2099-01-01T00:00:02Z"
        scenarios.append(backwards)
        terminal_mismatch = copy.deepcopy(self.r10)
        terminal_mismatch["terminal"]["completed_at"] = "2099-01-01T00:00:04Z"
        scenarios.append(terminal_mismatch)
        for evidence in scenarios:
            self.assert_evidence_rejected("R10", evidence)

    def test_type_sensitive_bool_int_rejection(self):
        mutations = []
        attempt = copy.deepcopy(self.r9)
        attempt["request_events"][0]["attempt"] = True
        mutations.append(attempt)
        ordinal = copy.deepcopy(self.r9)
        ordinal["polls"][0]["ordinal"] = True
        mutations.append(ordinal)
        tokens = copy.deepcopy(self.r9)
        tokens["budget_observed"]["output_tokens"] = True
        mutations.append(tokens)
        output_bytes = copy.deepcopy(self.r9)
        output_bytes["terminal"]["output"]["bytes"] = True
        mutations.append(output_bytes)
        for evidence in mutations:
            self.assert_evidence_rejected("R9", evidence)

    def test_paths_tools_topology_and_extra_fields_are_frozen(self):
        for transform in ("tool", "depth", "path", "extra"):
            case = copy.deepcopy(self.cases["R10"])
            if transform == "tool":
                case["tools"]["child_allow"].append("Bash")
            elif transform == "depth":
                case["topology"]["max_depth"] = 2
            elif transform == "path":
                case["fixture"]["output_path"] = "../outside.json"
            else:
                case["unexpected"] = True
            self.assert_case_rejected(case)

    def test_privacy_markers_are_rejected(self):
        for marker in ("IXIC", "niulai-private", "private_state", "/private/state"):
            evidence = copy.deepcopy(self.r9)
            evidence["terminal"]["output"]["leak"] = marker
            self.assert_evidence_rejected("R9", evidence)

    def test_cli_placeholder_schema_and_validator_parity(self):
        placeholder = read_json(CANDIDATE / "cli_semantic_contract.json")
        schema = read_json(SCHEMAS / "cli-placeholder-v1.schema.json")
        self.api.validate_cli_placeholder(placeholder)
        validate_schema(placeholder, schema)
        enabled = copy.deepcopy(placeholder)
        enabled["enabled"] = True
        with self.assertRaises(self.api.ContractError):
            self.api.validate_cli_placeholder(enabled)
        with self.assertRaises(SchemaFailure):
            validate_schema(enabled, schema)

    def test_manifest_and_all_schemas_are_strict(self):
        manifest = read_json(CANDIDATE / "manifest.json")
        self.assertEqual(manifest["status"], "inert")
        self.assertFalse(manifest["provider_calls"])
        self.assertFalse(manifest["process_calls"])
        self.assertEqual(sorted(path.name for path in SCHEMAS.glob("*.json")), sorted(manifest["schemas"]))
        for path in SCHEMAS.glob("*.json"):
            schema = read_json(path)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            branches = schema.get("oneOf", [schema])
            for branch in branches:
                if branch.get("type") == "object":
                    self.assertFalse(branch.get("additionalProperties", True), path.name)


if __name__ == "__main__":
    unittest.main()
