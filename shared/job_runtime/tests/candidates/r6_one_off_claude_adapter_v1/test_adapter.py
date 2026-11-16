from __future__ import annotations

import copy
import json
from pathlib import Path
import smtplib
import socket
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.request

from shared.job_runtime.candidates.r6_one_off_claude_adapter_v1 import (
    FakeClaudeBoundary,
    execute_stage_a,
    stage_a_template,
    validate_stage_a_evidence,
    validate_stage_a_template,
)
from shared.job_runtime.candidates.r6_one_off_claude_adapter_v1.contracts import ContractError

ROOT = Path(__file__).resolve().parents[5]
FIXTURES = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_claude_adapter_v1"


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.template = stage_a_template("a" * 64, "opaque-ref://claude/current")
        self.temp = tempfile.TemporaryDirectory(dir=FIXTURES)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.serial = 0

    def run_case(self, scenario="nominal", boundary=None, template=None):
        self.serial += 1
        forbidden = AssertionError("external effect attempted")
        with mock.patch.object(socket, "socket", side_effect=forbidden), mock.patch.object(
            socket, "create_connection", side_effect=forbidden
        ), mock.patch.object(subprocess, "Popen", side_effect=forbidden), mock.patch.object(
            subprocess, "run", side_effect=forbidden
        ), mock.patch.object(urllib.request, "urlopen", side_effect=forbidden), mock.patch.object(
            smtplib, "SMTP", side_effect=forbidden
        ):
            result = execute_stage_a(
                self.root / (scenario + str(self.serial)),
                template or self.template,
                boundary or FakeClaudeBoundary(),
                scenario,
            )
        validate_stage_a_evidence(result.evidence, result.shared_execution.evidence if result.shared_execution else None)
        return result

    def test_fixture_inventory_covers_frozen_cases(self):
        value = json.loads((FIXTURES / "cases.json").read_text())
        self.assertEqual(value["status"], "SYNTHETIC_PROVIDER_FREE_ONLY")
        self.assertEqual(len(value["cases"]), 8)

    def test_nominal_exact_once_second_admission_rejected_and_nonauthorizing(self):
        boundary = FakeClaudeBoundary()
        result = self.run_case(boundary=boundary)
        self.assertEqual(result.evidence["outcome"], "PASS")
        self.assertEqual((boundary.membership_checks, boundary.inference_requests), (1, 1))
        self.assertEqual(result.evidence["admission_count"], 1)
        self.assertEqual(result.evidence["upstream_attempt_count"], 1)
        self.assertEqual(result.shared_execution.evidence["counters"]["admission_stop"], 1)
        self.assertFalse(result.evidence["countable_observation"])
        self.assertTrue(result.evidence["atomic_publication_complete"])
        self.assertTrue(all(value == 0 for value in result.evidence["effects"].values()))

    def test_all_known_preflight_stops_have_zero_admission_and_upstream(self):
        for name in (
            "auth_stop", "account_stop", "model_stop", "cost_stop", "window_stop",
            "custody_stop", "config_stop", "secret_stop", "path_swap",
        ):
            with self.subTest(name=name):
                result = self.run_case(name)
                self.assertEqual(result.evidence["outcome"], "STOP")
                self.assertEqual(
                    (result.evidence["admission_count"], result.evidence["upstream_attempt_count"], result.evidence["inference_count"]),
                    (0, 0, 0),
                )
                self.assertEqual(result.evidence["shared_evidence_sha256"], "0" * 64)

    def test_catalog_absent_duplicate_and_malformed_stop_after_one_check(self):
        for raw in (b"other\n", b"claude-opus-5-5\nclaude-opus-5-5\n", b"\xff"):
            with self.subTest(raw=raw):
                boundary = FakeClaudeBoundary(catalog=raw)
                result = self.run_case("catalog_stop", boundary)
                self.assertEqual(result.evidence["outcome"], "STOP")
                self.assertEqual((boundary.membership_checks, boundary.inference_requests), (1, 0))

    def test_post_admission_cleanup_and_publication_failures_are_durable_unknown(self):
        expectations = {
            "post_admission_unknown": True,
            "cleanup_failure": False,
            "publication_failure": True,
        }
        for name, cleanup_complete in expectations.items():
            with self.subTest(name=name):
                boundary = FakeClaudeBoundary(terminal="truncated", cleanup="fault")
                result = self.run_case(name, boundary)
                evidence = result.evidence
                self.assertEqual(evidence["outcome"], "UNKNOWN")
                self.assertEqual(
                    (evidence["retry_count"], evidence["replay_count"], evidence["provider_status_calls"], evidence["reconstruction_dispatch"]),
                    (0, 0, 0, 0),
                )
                self.assertEqual(evidence["cleanup_complete"], cleanup_complete)
                self.assertFalse(evidence["atomic_publication_complete"])
                self.assertTrue(evidence["owner_private_evidence_preserved"])
                self.assertTrue(evidence["durable_unknown_evidence"])
                self.assertEqual(boundary.inference_requests, 1)

    def test_template_is_closed_permanently_nonauthorizing_and_secret_free(self):
        for field, value, code in (
            ("enabled", True, "STAGE_A_AUTHORITY_INVALID"),
            ("provider_authorized", True, "STAGE_A_AUTHORITY_INVALID"),
            ("model", "other", "STAGE_A_TREATMENT_INVALID"),
            ("claude_subcap_usd", 0.02, "CLAUDE_SUBCAP_INVALID"),
        ):
            bad = copy.deepcopy(self.template)
            bad[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ContractError, code):
                validate_stage_a_template(bad)
        bad = copy.deepcopy(self.template)
        bad["extra"] = 1
        with self.assertRaisesRegex(ContractError, "STAGE_A_KEYS_INVALID"):
            validate_stage_a_template(bad)
        bad = copy.deepcopy(self.template)
        bad["credential_reference"] = "secret_value/cleartext"
        with self.assertRaisesRegex(ContractError, "SECRET_VALUE_FORBIDDEN"):
            validate_stage_a_template(bad)

    def test_evidence_rejects_effect_outcome_counter_and_shared_evidence_mutations(self):
        nominal_result = self.run_case()
        nominal = nominal_result.evidence
        nominal_shared = nominal_result.shared_execution.evidence
        cases = []
        for effect in nominal["effects"]:
            cases.append(("effects." + effect, 1, "STAGE_A_EFFECTS_INVALID"))
        cases.extend((
            ("outcome", "MAYBE", "STAGE_A_OUTCOME_INVALID"),
            ("membership_check_count", 2, "STAGE_A_COUNTER_INVALID"),
            ("admission_count", 2, "STAGE_A_COUNTER_INVALID"),
            ("upstream_attempt_count", 2, "STAGE_A_COUNTER_INVALID"),
            ("inference_count", 2, "STAGE_A_COUNTER_INVALID"),
            ("retry_count", 1, "STAGE_A_RETRY_FENCE_INVALID"),
            ("replay_count", 1, "STAGE_A_RETRY_FENCE_INVALID"),
            ("provider_status_calls", 1, "STAGE_A_RETRY_FENCE_INVALID"),
            ("reconstruction_dispatch", 1, "STAGE_A_RETRY_FENCE_INVALID"),
            ("definitely_not_submitted", True, "STAGE_A_PASS_SEMANTICS_INVALID"),
            ("admission_count", 0, "STAGE_A_PASS_SEMANTICS_INVALID"),
            ("shared_evidence_sha256", "0" * 64, "STAGE_A_PASS_SEMANTICS_INVALID"),
            ("shared_evidence_sha256", "not-a-digest", "STAGE_A_SHARED_HASH_INVALID"),
        ))
        for dotted, replacement, code in cases:
            bad = copy.deepcopy(nominal)
            target = bad
            parts = dotted.split(".")
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = replacement
            with self.subTest(gate=dotted, replacement=replacement), self.assertRaisesRegex(
                ContractError, "^" + code + "$"
            ):
                validate_stage_a_evidence(bad, nominal_shared)

        valid_wrong = copy.deepcopy(nominal)
        valid_wrong["shared_evidence_sha256"] = "a" * 64
        with self.assertRaisesRegex(ContractError, "^STAGE_A_SHARED_EVIDENCE_HASH_MISMATCH$"):
            validate_stage_a_evidence(valid_wrong, nominal_shared)

        stopped = self.run_case("auth_stop").evidence
        bad = copy.deepcopy(stopped)
        bad["shared_evidence_sha256"] = "a" * 64
        with self.assertRaisesRegex(ContractError, "^STAGE_A_STOP_SEMANTICS_INVALID$"):
            validate_stage_a_evidence(bad)

        unknown_result = self.run_case(
            "post_admission_unknown",
            FakeClaudeBoundary(terminal="truncated", cleanup="fault"),
        )
        unknown = unknown_result.evidence
        bad = copy.deepcopy(unknown)
        bad["shared_evidence_sha256"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "^STAGE_A_UNKNOWN_SEMANTICS_INVALID$"):
            validate_stage_a_evidence(bad, unknown_result.shared_execution.evidence)
        bad = copy.deepcopy(unknown)
        bad["membership_check_count"] = 0
        with self.assertRaisesRegex(ContractError, "^STAGE_A_UNKNOWN_SEMANTICS_INVALID$"):
            validate_stage_a_evidence(bad, unknown_result.shared_execution.evidence)

        bad = copy.deepcopy(nominal)
        del bad["shared_evidence_sha256"]
        with self.assertRaisesRegex(ContractError, "^STAGE_A_EVIDENCE_KEYS_INVALID$"):
            validate_stage_a_evidence(bad)


if __name__ == "__main__":
    unittest.main()
