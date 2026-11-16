from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from shared.job_runtime.candidates.r6_one_off_claude_catalog_parser_v1 import (
    CatalogParseError,
    STATUS,
    interpret_frozen_catalog,
    parse_frozen_catalog_jsonl,
)

ROOT = Path(__file__).resolve().parents[5]
FIXTURE = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_claude_catalog_parser_v1/nominal.jsonl"
SOURCE = ROOT / "shared/job_runtime/candidates/r6_one_off_claude_catalog_parser_v1/parser.py"
SCHEMA = ROOT / "shared/job_runtime/candidates/r6_one_off_claude_catalog_parser_v1/interpretation-receipt-v1.schema.json"


def events():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines()]


def encode(values):
    return b"".join((json.dumps(value, separators=(",", ":")) + "\n").encode() for value in values)


class ParserTests(unittest.TestCase):
    def assert_code(self, values, code):
        with self.assertRaises(CatalogParseError) as caught:
            parse_frozen_catalog_jsonl(encode(values))
        self.assertEqual(caught.exception.code, code)

    def test_nominal_and_assistant_duplicates_are_non_authoritative(self):
        value = parse_frozen_catalog_jsonl(FIXTURE.read_bytes())
        self.assertEqual(value["terminal_occurrences"], 1)
        self.assertGreaterEqual(value["assistant_occurrences_ignored"], 2)
        self.assertEqual(value["membership_authority"], "terminal_result_only")

    def test_duplicate_json_key_rejected(self):
        raw = FIXTURE.read_bytes().replace(b'{"type":"system"', b'{"type":"system","type":"system"', 1)
        with self.assertRaises(CatalogParseError) as caught:
            parse_frozen_catalog_jsonl(raw)
        self.assertEqual(caught.exception.code, "DUPLICATE_JSON_KEY")

    def test_missing_and_multiple_result_rejected(self):
        value = events()
        self.assert_code(value[:-1], "EXACTLY_ONE_RESULT_REQUIRED")
        self.assert_code(value + [copy.deepcopy(value[-1])], "EXACTLY_ONE_RESULT_REQUIRED")

    def test_result_error_rejected(self):
        value = events(); value[-1]["is_error"] = True
        self.assert_code(value, "RESULT_ERROR")

    def test_nonzero_cost_and_usage_rejected(self):
        value = events(); value[-1]["total_cost_usd"] = 0.01
        self.assert_code(value, "NONZERO_COST_OR_INFERENCE")
        value = events(); value[-1]["usage"]["input_tokens"] = 1
        self.assert_code(value, "NONZERO_INFERENCE_USAGE")
        value = events(); value[-1]["modelUsage"] = {"claude-opus-5-5": {"inputTokens": 1}}
        self.assert_code(value, "NONZERO_MODEL_USAGE")

    def test_wrong_or_assistant_only_model_text_rejected(self):
        value = events(); value[-1]["result"] = value[-1]["result"].replace("Opus 5.5", "Sonnet 5.5")
        self.assert_code(value, "EXACT_MODEL_MEMBERSHIP_REQUIRED")
        value = events(); value[-1]["result"] = "Usage: /model <name>. Available: opus.\nNo selected model."
        self.assert_code(value, "LOCAL_COMMAND_OUTPUT_INVALID")

    def test_duplicate_terminal_membership_rejected(self):
        value = events(); value[-1]["result"] += " Opus 5.5"
        self.assert_code(value, "EXACT_MODEL_MEMBERSHIP_REQUIRED")

    def test_extra_keys_and_secret_fields_rejected(self):
        value = events(); value[-1]["extra"] = 1
        self.assert_code(value, "RESULT_SCHEMA_INVALID")
        value = events(); value[1]["message"]["api_key"] = "synthetic-not-a-secret"
        self.assert_code(value, "SECRET_FIELD_FORBIDDEN")

    def test_permission_safety_and_local_semantics_rejected(self):
        value = events(); value[-1]["permission_denials"] = [{"reason": "synthetic"}]
        self.assert_code(value, "PERMISSION_OR_SAFETY_ERROR")
        value = events(); value[-1]["safety_stops"] = 1
        self.assert_code(value, "PERMISSION_OR_SAFETY_ERROR")
        value = events(); value[-1]["local_command"] = "status"
        self.assert_code(value, "LOCAL_COMMAND_INVALID")

    def test_exact_frozen_producer_path(self):
        receipt = interpret_frozen_catalog(ROOT)
        self.assertEqual(receipt["status"], STATUS)
        self.assertEqual(receipt["original_execution_status"], "STOP_CATALOG_PREFLIGHT")
        self.assertTrue(all(value == 0 for value in receipt["effects"].values()))

    def test_standalone_experiment_from_foreign_cwd(self):
        script = ROOT / "tuning/architecture/r6_one_off_claude_catalog_parser_v1/experiment.py"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "receipt.json"
            completed = subprocess.run(
                [sys.executable, str(script), "--workspace", str(ROOT), "--output", str(output)],
                cwd=temporary, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(output.read_text()), interpret_frozen_catalog(ROOT))

    def test_python_39_grammar(self):
        ast.parse(SOURCE.read_text(), filename=str(SOURCE), feature_version=(3, 9))
        experiment = ROOT / "tuning/architecture/r6_one_off_claude_catalog_parser_v1/experiment.py"
        ast.parse(experiment.read_text(), filename=str(experiment), feature_version=(3, 9))

    def test_draft_2020_12_schema_and_closure(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
        schema = json.loads(SCHEMA.read_text())
        Draft202012Validator.check_schema(schema)
        receipt = interpret_frozen_catalog(ROOT)
        Draft202012Validator(schema).validate(receipt)
        bad = dict(receipt); bad["extra"] = True
        self.assertFalse(Draft202012Validator(schema).is_valid(bad))


if __name__ == "__main__":
    unittest.main()
