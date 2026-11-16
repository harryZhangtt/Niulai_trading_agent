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
import sys

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v5 import (
    LocalOnlyProcessEffect, p0_output, run,
)
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v5 import authority as authmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v5 import process as processmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v5 import runner as runmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v5.contracts import (
    BINARY_DESCRIPTOR, BINARY_REF, GRANT_REVIEW_SHA256, GRANT_SHA256, PROVIDER,
    REGISTRY_REVIEW_SHA256, REGISTRY_SHA256, SCOPE_SHA256, canonical_bytes,
    validate_seal,
)

FIX = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_claude_live_integration_v1"
NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)


class IntegrationV5Tests(unittest.TestCase):
    def case(self, scenario="nominal"):
        temp = tempfile.TemporaryDirectory(dir=FIX)
        self.addCleanup(temp.cleanup)
        base = pathlib.Path(temp.name)
        seal = run(base / "run", effect=LocalOnlyProcessEffect(True), scenario=scenario)
        return seal, base

    def test_public_api_has_no_authority_verifier_clock_or_live_default(self):
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
        expected = {authmod.REGISTRY_REF: REGISTRY_SHA256,
            authmod.REGISTRY_REVIEW_REF: REGISTRY_REVIEW_SHA256,
            authmod.GRANT_REF: GRANT_SHA256,
            authmod.GRANT_REVIEW_REF: GRANT_REVIEW_SHA256,
            authmod.SCOPE_REF: SCOPE_SHA256}
        for ref, digest in expected.items():
            raw = (ROOT / ref[0]).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                             (ref[1], digest))
        authority = authmod.load_pinned()
        self.assertEqual(authority.clock_id, "system_utc_time_ns")
        self.assertEqual(authority.grant["binary_ref"], BINARY_REF)
        self.assertEqual(authority.grant["binary"], BINARY_DESCRIPTOR)

    def test_authority_drift_stops_before_effect(self):
        held = [authmod._held(ref) for ref in (authmod.REGISTRY_REF,
            authmod.REGISTRY_REVIEW_REF, authmod.GRANT_REF,
            authmod.GRANT_REVIEW_REF, authmod.SCOPE_REF)]
        stale = copy.deepcopy(held[2])
        stale.update(not_before="2024-01-01T00:00:00+00:00",
                     expires_at="2025-01-01T00:00:00+00:00")
        held[2] = stale
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            effect = mock.Mock()
            with mock.patch.object(authmod, "_held", side_effect=held), \
                 mock.patch.object(authmod, "_trusted_utc_now", return_value=NOW):
                seal = run(pathlib.Path(temp), effect=effect)
        self.assertEqual((seal["status"], seal["code"]),
                         ("STOP", "GRANT_STALE_OR_NOT_YET_VALID"))
        effect.execute.assert_not_called()

    def test_nominal_marker_bound_pass_and_second_run_no_replay(self):
        seal, base = self.case()
        root = base / "run"
        self.assertEqual((seal["version"], seal["status"], seal["engine"]["provider"]),
                         (5, "PASS", "claude_host"))
        pending_path = root / "public" / runmod.PUBLIC_PENDING_NAME
        marker_path = root / "public" / runmod.PUBLIC_NAME
        pending = json.loads(pending_path.read_text())
        marker = json.loads(marker_path.read_text())
        self.assertEqual((pending["state"], pending["authoritative"]),
                         ("PENDING_NONAUTHORITATIVE", False))
        self.assertEqual((marker["state"], marker["authoritative"], marker["seal"]),
                         ("COMMITTED_AUTHORITATIVE", True, seal))
        self.assertEqual(marker["pending_sha256"],
                         hashlib.sha256(pending_path.read_bytes()).hexdigest())
        effect = mock.Mock()
        recovered = run(root, effect=effect, scenario="engine_exception")
        self.assertEqual(recovered, seal)
        effect.execute.assert_not_called()
        self.assertEqual(p0_output(seal)["schema"],
                         "r6-one-off-claude-live-integration-v5")
        database = root / "engine/.job-runtime/r6-one-off-evidence-v1/engine/schedule.sqlite"
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute(
                "select provider from slots").fetchone()[0], "claude_host")
            self.assertEqual(connection.execute(
                "select provider from provider_results").fetchone()[0], "claude_host")

    def test_write_short_zero_fsync_link_dirfsync_reopen_readback_matrix(self):
        raw = b'{"provider_free":true}'
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            path = pathlib.Path(temp) / "short.json"
            real_write = runmod.os.write
            def short(fd, value):
                return real_write(fd, value[:7])
            with mock.patch.object(runmod.os, "write", side_effect=short):
                self.assertEqual(runmod._publish_verified(path, raw), raw)
        failures = {}
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            path = pathlib.Path(temp) / "zero.json"
            with mock.patch.object(runmod.os, "write", return_value=0):
                with self.assertRaises(OSError):
                    runmod._publish_verified(path, raw)
            failures["zero"] = not os.path.lexists(path)
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            path = pathlib.Path(temp) / "fsync.json"
            with mock.patch.object(runmod.os, "fsync", side_effect=OSError("fsync")):
                with self.assertRaises(OSError):
                    runmod._publish_verified(path, raw)
            failures["file_fsync"] = not os.path.lexists(path)
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            path = pathlib.Path(temp) / "link.json"
            with mock.patch.object(runmod.os, "link", side_effect=OSError("link")):
                with self.assertRaises(OSError):
                    runmod._publish_verified(path, raw)
            failures["link"] = not os.path.lexists(path)
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            path = pathlib.Path(temp) / "dir.json"
            real_dir = runmod._fsync_directory
            calls = [0]
            def fail_once(value):
                calls[0] += 1
                if calls[0] == 1:
                    raise OSError("dir")
                return real_dir(value)
            with mock.patch.object(runmod, "_fsync_directory", side_effect=fail_once):
                with self.assertRaises(OSError):
                    runmod._publish_verified(path, raw)
            failures["dir_fsync"] = not os.path.lexists(path)
        for label, mode in (("reopen", "raise"), ("readback", "mismatch")):
            with tempfile.TemporaryDirectory(dir=FIX) as temp:
                path = pathlib.Path(temp) / (label + ".json")
                side = OSError(label) if mode == "raise" else None
                patcher = (mock.patch.object(runmod, "_read_held", side_effect=side)
                    if side else mock.patch.object(runmod, "_read_held", return_value=b"bad"))
                with patcher:
                    with self.assertRaises((OSError, ValueError)):
                        runmod._publish_verified(path, raw)
                failures[label] = not os.path.lexists(path)
        self.assertEqual(failures, {key: True for key in failures})

    def test_postlink_pass_failure_revokes_pass_and_second_run_does_not_replay(self):
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            root = pathlib.Path(temp) / "run"
            real_read = runmod._read_held
            failed = [False]
            def reopen(path):
                if pathlib.Path(path).name == runmod.PUBLIC_NAME and not failed[0]:
                    failed[0] = True
                    raise OSError("injected public reopen")
                return real_read(path)
            with mock.patch.object(runmod, "_read_held", side_effect=reopen):
                first = run(root, effect=LocalOnlyProcessEffect(True))
            self.assertEqual(first["status"], "UNKNOWN")
            self.assertFalse(os.path.lexists(root / "public" / runmod.PUBLIC_NAME))
            self.assertTrue((root / "public" / runmod.PUBLIC_PENDING_NAME).is_file())
            effect = mock.Mock()
            second = run(root, effect=effect)
            self.assertEqual(second["status"], "UNKNOWN")
            effect.execute.assert_not_called()

    def test_postlink_fence_failure_is_nondurable_pending_only_and_no_replay(self):
        for failure in ("reopen", "dir_fsync", "link"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(dir=FIX) as temp:
                root = pathlib.Path(temp) / "run"
                if failure == "reopen":
                    real = runmod._read_held; hit = [False]
                    def injected(path):
                        if pathlib.Path(path).name == runmod.FENCE_NAME and not hit[0]:
                            hit[0] = True; raise OSError("reopen")
                        return real(path)
                    context = mock.patch.object(runmod, "_read_held", side_effect=injected)
                elif failure == "link":
                    real = runmod.os.link
                    def injected(src, dst, **kwargs):
                        if pathlib.Path(dst).name == runmod.FENCE_NAME:
                            raise OSError("link")
                        return real(src, dst, **kwargs)
                    context = mock.patch.object(runmod.os, "link", side_effect=injected)
                else:
                    real = runmod._fsync_directory; hit = [False]
                    def injected(path):
                        if os.path.lexists(root / runmod.FENCE_NAME) and not hit[0]:
                            hit[0] = True; raise OSError("dir")
                        return real(path)
                    context = mock.patch.object(runmod, "_fsync_directory", side_effect=injected)
                with context:
                    first = run(root, effect=LocalOnlyProcessEffect(True), scenario="timeout")
                self.assertEqual((first["status"], first["unknown_fence"]["durability"]),
                                 ("UNKNOWN", "NON_DURABLE"))
                self.assertFalse(os.path.lexists(root / runmod.FENCE_NAME))
                self.assertTrue((root / runmod.FENCE_PENDING_NAME).is_file())
                effect = mock.Mock()
                second = run(root, effect=effect)
                self.assertEqual((second["status"], second["unknown_fence"]["durability"]),
                                 ("UNKNOWN", "NON_DURABLE"))
                effect.execute.assert_not_called()

    def test_marker_pair_hash_mismatch_is_not_accepted_or_replayed(self):
        seal, base = self.case("timeout")
        root = base / "run"
        pending_path = root / runmod.FENCE_PENDING_NAME
        pending = json.loads(pending_path.read_text())
        pending["candidate_seal_sha256"] = "f" * 64
        pending_path.write_bytes(canonical_bytes(pending))
        effect = mock.Mock()
        recovered = run(root, effect=effect)
        self.assertEqual((recovered["status"], recovered["unknown_fence"]["durability"]),
                         ("UNKNOWN", "NON_DURABLE"))
        effect.execute.assert_not_called()

    def test_legacy_v4_artifact_is_never_accepted_or_replayed(self):
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            root = pathlib.Path(temp)
            (root / runmod.LEGACY_FENCE_NAME).write_text('{}')
            effect = mock.Mock()
            seal = run(root, effect=effect)
        self.assertEqual((seal["status"], seal["unknown_fence"]["durability"]),
                         ("UNKNOWN", "NON_DURABLE"))
        effect.execute.assert_not_called()

    def test_cleanup_fault_matrix_is_durable_unknown_and_redacted(self):
        scenarios = ("cleanup_stream_exception", "cleanup_probe_exception",
            "cleanup_ferry_exception", "cleanup_unlink_exception",
            "cleanup_fsync_exception", "cleanup_probe_failure", "secret")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                seal, base = self.case(scenario)
                self.assertEqual(seal["status"], "UNKNOWN")
                raw = (base / "run" / runmod.FENCE_NAME).read_bytes()
                self.assertNotIn(b"sk-ant-test-secret", raw)
                self.assertNotIn(b"/Users/", raw)

    def test_pid_reuse_token_mismatch_is_not_same_process(self):
        expected = "a" * 64
        with mock.patch.object(processmod, "_token_sha", return_value="b" * 64):
            self.assertFalse(processmod._same_process(4242, expected))
        with mock.patch.object(processmod, "_token_sha", return_value=expected):
            self.assertTrue(processmod._same_process(4242, expected))

    def test_parent_exit_resistant_child_is_reaped_with_start_token(self):
        seal, _ = self.case("parent_exit_resistant")
        process = seal["process"]
        self.assertEqual(seal["status"], "PASS")
        self.assertGreater(process["child_pid"], 0)
        self.assertNotEqual(process["child_start_token_sha256"], "0" * 64)
        self.assertTrue(process["process_group_gone"] and process["child_pid_gone"] and
                        process["descendants_reaped"])
        with self.assertRaises(ProcessLookupError):
            os.kill(process["child_pid"], 0)

    def test_runtime_rejects_reviewed_contradictions_and_nested_extras(self):
        seal, _ = self.case()
        mutations = []
        for path, value in ((('process','descendants_reaped'), False),
            (('process','cleanup_exception'), True),
            (('publication','readback_verified'), False),
            (('cleanup','exception_count'), 1)):
            bad = copy.deepcopy(seal); bad[path[0]][path[1]] = value; mutations.append(bad)
        bad = copy.deepcopy(seal); bad["process"]["extra"] = True; mutations.append(bad)
        for bad in mutations:
            with self.assertRaises(Exception):
                validate_seal(bad)


if __name__ == "__main__":
    unittest.main()
