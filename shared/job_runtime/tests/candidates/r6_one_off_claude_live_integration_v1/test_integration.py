from __future__ import annotations
from datetime import datetime, timezone
import copy
import hashlib
import inspect
import json
import os
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v1 import (
    LocalOnlyProcessEffect, p0_output, run,
)
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v1 import authority as authmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v1 import runner as runmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v1.contracts import (
    BINARY_DESCRIPTOR, BINARY_REF, GRANT_REVIEW_SHA256, GRANT_SHA256, PROVIDER,
    REGISTRY_REVIEW_SHA256, REGISTRY_SHA256, SCOPE_SHA256, canonical_bytes,
    validate_seal,
)

ROOT = pathlib.Path(__file__).resolve().parents[5]
FIX = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_claude_live_integration_v1"
NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)


class IntegrationV4Tests(unittest.TestCase):
    def case(self, scenario="nominal"):
        temp = tempfile.TemporaryDirectory(dir=FIX)
        self.addCleanup(temp.cleanup)
        base = pathlib.Path(temp.name)
        seal = run(base / "run", effect=LocalOnlyProcessEffect(True), scenario=scenario)
        return seal, base

    def test_public_api_has_no_authority_verifier_or_clock_selection(self):
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            self.assertEqual(run(pathlib.Path(temp))["code"],
                             "PINNED_AUTHORITY_AND_EFFECT_REQUIRED")
        self.assertEqual(set(inspect.signature(run).parameters),
                         {"root", "effect", "scenario"})
        self.assertEqual(set(inspect.signature(authmod.load_pinned).parameters), set())
        for keyword in ("authority", "registry", "grant", "review", "now", "clock"):
            with self.assertRaises(TypeError):
                run(pathlib.Path("x"), **{keyword: object()})

    def test_all_exact_authority_files_hash_read_and_bind(self):
        expected = {
            authmod.REGISTRY_REF: REGISTRY_SHA256,
            authmod.REGISTRY_REVIEW_REF: REGISTRY_REVIEW_SHA256,
            authmod.GRANT_REF: GRANT_SHA256,
            authmod.GRANT_REVIEW_REF: GRANT_REVIEW_SHA256,
            authmod.SCOPE_REF: SCOPE_SHA256,
        }
        for ref, digest in expected.items():
            raw = (ROOT / ref[0]).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                             (ref[1], digest))
        authority = authmod.load_pinned()
        self.assertEqual(authority.clock_id, "system_utc_time_ns")
        self.assertEqual(authority.grant["binary_ref"], BINARY_REF)
        self.assertEqual(authority.grant["binary"], BINARY_DESCRIPTOR)

    def test_authority_drift_or_stale_window_stops_before_effect(self):
        registry = authmod._held(authmod.REGISTRY_REF)
        registry_review = authmod._held(authmod.REGISTRY_REVIEW_REF)
        grant = authmod._held(authmod.GRANT_REF)
        grant_review = authmod._held(authmod.GRANT_REVIEW_REF)
        scope = authmod._held(authmod.SCOPE_REF)
        variants = []
        stale = copy.deepcopy(grant)
        stale.update(not_before="2024-01-01T00:00:00+00:00",
                     expires_at="2025-01-01T00:00:00+00:00")
        variants.append(([registry, registry_review, stale, grant_review, scope],
                         "GRANT_STALE_OR_NOT_YET_VALID"))
        bad_review = copy.deepcopy(registry_review)
        bad_review["checks"]["provider_free_only"] = False
        variants.append(([registry, bad_review, grant, grant_review, scope],
                         "REGISTRY_REVIEW_CHECKS"))
        for held, code in variants:
            with self.subTest(code=code), tempfile.TemporaryDirectory(dir=FIX) as temp:
                effect = mock.Mock()
                with mock.patch.object(authmod, "_held", side_effect=held), \
                     mock.patch.object(authmod, "_trusted_utc_now", return_value=NOW):
                    seal = run(pathlib.Path(temp), effect=effect)
                self.assertEqual((seal["status"], seal["code"]), ("STOP", code))
                effect.execute.assert_not_called()

    def test_nominal_binds_engine_ferry_model_process_and_final_publication(self):
        seal, base = self.case()
        self.assertEqual((seal["status"], seal["engine"]["provider"]),
                         ("PASS", "claude_host"))
        process = seal["process"]
        self.assertEqual((process["provider"], process["model"], process["binary_ref"]),
                         (PROVIDER, "claude-opus-5-5", BINARY_REF))
        self.assertEqual(process["binary_descriptor"], BINARY_DESCRIPTOR)
        self.assertNotEqual(process["process_start_token_sha256"], "0" * 64)
        self.assertGreater(process["private_copy_inode"], 0)
        ferry = seal["ferry"]
        self.assertEqual((ferry["provider"], ferry["transport"], ferry["host"],
                          ferry["path"], ferry["model"]),
                         ("claude_host", "claude_ferry", "127.0.0.1",
                          "/v1/messages", "claude-opus-5-5"))
        self.assertTrue(all(seal["publication"][key] for key in
                            ("file_fsynced", "directory_fsynced",
                             "final_reopened_nofollow", "readback_verified")))
        public = base / "run/public/post-run-seal-v4.json"
        self.assertEqual(json.loads(public.read_text()), seal)
        self.assertEqual(p0_output(seal)["engine_provider"], "claude_host")
        database = base / "run/engine/.job-runtime/r6-one-off-evidence-v1/engine/schedule.sqlite"
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute(
                "select provider from slots").fetchone()[0], "claude_host")
            self.assertEqual(connection.execute(
                "select provider from provider_results").fetchone()[0], "claude_host")

    def test_publication_order_is_write_fsync_link_dir_reopen_readback(self):
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            events = []
            path = pathlib.Path(temp) / "final.json"
            raw = b'{"provider_free":true}'
            real_write = runmod._write_all
            real_fsync = runmod.os.fsync
            real_link = runmod.os.link
            real_dir = runmod._fsync_directory
            real_read = runmod._read_held
            def write(fd, value):
                events.append("write")
                return real_write(fd, value)
            def fsync(fd):
                events.append("fsync")
                return real_fsync(fd)
            def link(*args, **kwargs):
                events.append("link")
                return real_link(*args, **kwargs)
            def directory(value):
                events.append("dir")
                return real_dir(value)
            def read(value):
                events.append("read")
                return real_read(value)
            with mock.patch.object(runmod, "_write_all", side_effect=write), \
                 mock.patch.object(runmod.os, "fsync", side_effect=fsync), \
                 mock.patch.object(runmod.os, "link", side_effect=link), \
                 mock.patch.object(runmod, "_fsync_directory", side_effect=directory), \
                 mock.patch.object(runmod, "_read_held", side_effect=read):
                self.assertEqual(runmod._publish_verified(path, raw), raw)
            first = {name: events.index(name) for name in ("write", "link", "dir", "read")}
            self.assertLess(first["write"], events.index("fsync"))
            self.assertLess(events.index("fsync"), first["link"])
            self.assertLess(first["link"], first["dir"])
            self.assertLess(first["dir"], first["read"])

    def test_every_post_admission_cleanup_exception_is_unknown_not_stop(self):
        for scenario in ("cleanup_stream_exception", "cleanup_probe_exception",
                         "cleanup_ferry_exception", "cleanup_unlink_exception",
                         "cleanup_fsync_exception"):
            with self.subTest(scenario=scenario):
                seal, base = self.case(scenario)
                self.assertEqual(seal["status"], "UNKNOWN")
                self.assertEqual(seal["code"], "POST_ADMISSION_CLEANUP_EXCEPTION")
                self.assertEqual(seal["unknown_fence"]["durability"], "DURABLE")
                self.assertTrue((base / "run/unknown-fence-v4.json").is_file())

    def test_fence_publication_exception_returns_unknown_non_durable(self):
        with tempfile.TemporaryDirectory(dir=FIX) as temp, \
             mock.patch.object(runmod, "_publish_verified", side_effect=OSError("injected")):
            seal = run(pathlib.Path(temp), effect=LocalOnlyProcessEffect(True),
                       scenario="timeout")
        self.assertEqual((seal["status"], seal["unknown_fence"]["durability"]),
                         ("UNKNOWN", "NON_DURABLE"))
        self.assertTrue(seal["code"].endswith("_NON_DURABLE"))

    def test_dangling_fence_never_disappears_and_stale_stage_cannot_block_unknown(self):
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            root = pathlib.Path(temp)
            (root / "unknown-fence-v4.json").symlink_to(root / "missing")
            effect = mock.Mock()
            seal = run(root, effect=effect)
            self.assertEqual((seal["status"], seal["unknown_fence"]["durability"]),
                             ("UNKNOWN", "NON_DURABLE"))
            effect.execute.assert_not_called()
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            root = pathlib.Path(temp)
            (root / ".unknown-fence-v4.json.stage.stale").write_text("stale")
            seal = run(root, effect=LocalOnlyProcessEffect(True), scenario="timeout")
            self.assertEqual((seal["status"], seal["unknown_fence"]["durability"]),
                             ("UNKNOWN", "DURABLE"))
            self.assertTrue((root / "unknown-fence-v4.json").is_file())

    def test_timeout_nonzero_second_request_and_secrets_are_durable_unknown(self):
        for scenario in ("timeout", "nonzero_success", "second_request", "secret",
                         "truncation", "readback_mismatch", "cleanup_probe_failure"):
            with self.subTest(scenario=scenario):
                seal, base = self.case(scenario)
                self.assertEqual(seal["status"], "UNKNOWN")
                raw = (base / "run/unknown-fence-v4.json").read_bytes()
                self.assertNotIn(b"sk-ant-test-secret", raw)
                self.assertNotIn(b"/Users/", raw)

    def test_parent_exit_resistant_child_uses_start_token_and_is_reaped(self):
        seal, _ = self.case("parent_exit_resistant")
        process = seal["process"]
        self.assertEqual(seal["status"], "PASS")
        self.assertGreater(process["child_pid"], 0)
        self.assertNotEqual(process["child_start_token_sha256"], "0" * 64)
        self.assertTrue(process["process_group_gone"] and process["child_pid_gone"] and
                        process["descendants_reaped"])
        with self.assertRaises(ProcessLookupError):
            os.kill(process["child_pid"], 0)

    def test_strict_identity_contract_rejects_cross_provider_or_missing_descendant_fields(self):
        seal, _ = self.case()
        bad = copy.deepcopy(seal)
        bad["engine"]["provider"] = "codex_cli"
        with self.assertRaises(Exception):
            validate_seal(bad)
        bad = copy.deepcopy(seal)
        del bad["process"]["child_pid_gone"]
        with self.assertRaises(Exception):
            validate_seal(bad)


if __name__ == "__main__":
    unittest.main()
