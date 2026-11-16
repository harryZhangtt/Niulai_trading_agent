"""AC-O1-001 through AC-O1-004 synthetic vertical acceptance."""
from __future__ import annotations

import smtplib
import socket
import subprocess
import unittest
from unittest import mock
import urllib.request
from pathlib import Path

from shared.job_runtime.candidates.r6_one_off_evidence_v1.runner import (
    execute_provider_free, materialize_provider_free_case,
)
from shared.job_runtime.tests.candidates.r6_one_off_evidence_v1._support import (
    historical, temporary_parent, transport_for,
)


class VerticalTests(unittest.TestCase):
    def setUp(self):
        self.historical_jobs, self.historical_nonces, self.historical_engine = historical()
        self.temp = temporary_parent()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def prepare(self, name):
        return materialize_provider_free_case(
            self.base / name, name, self.historical_jobs, self.historical_nonces)

    def run_without_external_effects(self, prepared, transport):
        forbidden = AssertionError("external effect attempted")
        with mock.patch.object(socket, "socket", side_effect=forbidden), \
             mock.patch.object(socket, "create_connection", side_effect=forbidden), \
             mock.patch.object(subprocess, "Popen", side_effect=forbidden), \
             mock.patch.object(subprocess, "run", side_effect=forbidden), \
             mock.patch.object(subprocess, "call", side_effect=forbidden), \
             mock.patch.object(urllib.request, "urlopen", side_effect=forbidden), \
             mock.patch.object(smtplib, "SMTP", side_effect=forbidden):
            return execute_provider_free(
                prepared, transport, self.historical_jobs, self.historical_nonces)

    def test_nominal_future_once_exactly_one_and_engine_owned_identity(self):
        observed = []
        prepared = self.prepare("nominal")
        self.addCleanup(prepared.close)
        for forbidden in ("slot_id", "attempt_id", "operation_id"):
            self.assertNotIn(forbidden, prepared.grant)
        self.assertFalse(prepared.grant["provider_authorized"])
        result = self.run_without_external_effects(
            prepared, transport_for("nominal", observed))
        self.assertEqual(result.evidence["decision"], "PASS")
        self.assertFalse(result.evidence["countable"])
        self.assertEqual(result.evidence["counters"], {
            "dispatch": 1, "admission": 1, "admission_stop": 1,
            "upstream": 1, "retry": 0, "replay": 0, "status_query": 0,
            "reconstruction_dispatch": 0,
        })
        self.assertEqual(len(observed), 1)
        self.assertEqual(result.binding["provider"], "codex_cli")
        self.assertEqual(result.binding["counts"], {
            "job": 1, "slot": 1, "attempt": 1, "provider_result": 1})
        self.assertTrue(result.binding["operation_equal"])
        self.assertTrue(result.binding["prompt_binding_equal"])
        self.assertNotIn(result.binding["slot_id"], self.historical_engine)
        self.assertNotIn(result.binding["attempt_id"], self.historical_engine)
        self.assertNotIn(result.binding["operation_id"], self.historical_engine)
        self.assertTrue(all(value is False for value in
                            result.evidence["external_effects"].values()))


    def test_explicit_claude_host_identity_is_engine_owned_and_durable(self):
        prepared = self.prepare("nominal")
        self.addCleanup(prepared.close)
        result = execute_provider_free(
            prepared, transport_for("nominal", []), self.historical_jobs,
            self.historical_nonces, provider="claude_host")
        self.assertEqual(result.binding["provider"], "claude_host")
        import sqlite3
        with sqlite3.connect(prepared.engine_state / "schedule.sqlite") as db:
            self.assertEqual(
                db.execute("SELECT provider FROM provider_results").fetchone()[0],
                "claude_host")
            self.assertEqual(
                db.execute("SELECT provider FROM slots").fetchone()[0],
                "claude_host")

    def test_post_admission_truncation_cleanup_fault_is_durable_unknown(self):
        observed = []
        prepared = self.prepare("post_admission_unknown")
        self.addCleanup(prepared.close)
        result = self.run_without_external_effects(
            prepared, transport_for("post_admission_unknown", observed))
        self.assertEqual(result.evidence["decision"], "UNKNOWN")
        self.assertEqual(result.evidence["engine"]["status"], "unknown")
        self.assertEqual(result.evidence["terminal"], "truncated")
        self.assertEqual(result.evidence["cleanup"], "fault")
        self.assertEqual(result.evidence["counters"], {
            "dispatch": 1, "admission": 1, "admission_stop": 1,
            "upstream": 1, "retry": 0, "replay": 0, "status_query": 0,
            "reconstruction_dispatch": 0,
        })
        self.assertEqual(len(observed), 1)
        self.assertEqual(result.binding["engine_status"], "unknown")

    def test_pre_dispatch_digest_drift_stops_with_no_engine_or_effect(self):
        observed = []
        prepared = self.prepare("pre_dispatch_stop")
        self.addCleanup(prepared.close)
        prepared.inject_drift("config")
        result = self.run_without_external_effects(
            prepared, transport_for("pre_dispatch_stop", observed))
        self.assertEqual(result.evidence["decision"], "STOP")
        self.assertIsNone(result.binding)
        self.assertEqual(result.evidence["engine"], {
            "slot_id": None, "attempt_id": None, "operation_id": None,
            "status": None,
        })
        self.assertEqual(result.evidence["counters"], {
            "dispatch": 0, "admission": 0, "admission_stop": 0,
            "upstream": 0, "retry": 0, "replay": 0, "status_query": 0,
            "reconstruction_dispatch": 0,
        })
        self.assertEqual(observed, [])
        self.assertFalse(prepared.engine_state.exists())

    def test_all_three_cases_use_fresh_nonhistorical_jobs_and_nonces(self):
        prepared = [self.prepare(name) for name in (
            "nominal", "post_admission_unknown", "pre_dispatch_stop")]
        for item in prepared:
            self.addCleanup(item.close)
        jobs = [item.grant["logical_job_id"] for item in prepared]
        nonces = [item.grant["preflight_nonce"] for item in prepared]
        self.assertEqual(len(set(jobs)), 3)
        self.assertEqual(len(set(nonces)), 3)
        self.assertTrue(set(jobs).isdisjoint(self.historical_jobs))
        self.assertTrue(set(nonces).isdisjoint(self.historical_nonces))


if __name__ == "__main__":
    unittest.main()
