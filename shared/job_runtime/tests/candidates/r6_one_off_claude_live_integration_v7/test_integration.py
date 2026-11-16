from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import os
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v7 import authority as authmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v7 import runner as runmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v7 import state as statemod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v7.contracts import (
    BINARY_DESCRIPTOR, CLOCK_ID, GRANT_REVIEW_SHA256, GRANT_SHA256,
    PUBLICATION_ORDERING, REGISTRY_REVIEW_SHA256, REGISTRY_SHA256, SCOPE_SHA256,
    ContractError, blank_seal, validate_seal,
)

FIX = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_claude_live_integration_v1"


def _unknown_pair(generation: str) -> tuple[dict, dict]:
    authority = authmod.load_pinned()
    baseline = runmod._unknown_seed(authority, {}, {}, generation,
                                    "GENERATION_PRECOMMIT_UNKNOWN")
    poison = runmod._unknown_seed(authority, {}, {}, generation,
                                  "GENERATION_POISONED", "POISONED")
    return baseline, poison


def _valid_pass(generation: str) -> dict:
    value = blank_seal("EXACT_CLAUDE_HOST_TERMINAL_FERRY_ENGINE_EXIT_VERIFIED")
    value["status"] = "PASS"
    value["cell_id"] = "cell/provider-free-main-authority-v4"
    value["engine"] = {
        "provider": "claude_host", "job_id": "job", "slot_id": "slot",
        "attempt_id": "attempt", "operation_id": "operation",
        "prompt_binding_sha256": "1" * 64, "readback_digest": "2" * 64,
        "status": "succeeded",
    }
    value["authority"] = {
        "grant_sha256": GRANT_SHA256,
        "grant_review_sha256": GRANT_REVIEW_SHA256,
        "registry_sha256": REGISTRY_SHA256,
        "registry_review_sha256": REGISTRY_REVIEW_SHA256,
        "scope_sha256": SCOPE_SHA256, "clock_id": CLOCK_ID,
        "validated_before_effect": True, "post_receipt_required_pregrant": False,
    }
    value["process"].update({
        "starts": 1, "exit_code": 0, "timed_out": False,
        "binary_sha256": BINARY_DESCRIPTOR["sha256"],
        "private_copy_sha256": BINARY_DESCRIPTOR["sha256"],
        "private_copy_device": 1, "private_copy_inode": 1,
        "private_copy_mode": 0o700, "private_copy_uid": BINARY_DESCRIPTOR["uid"],
        "process_start_token_sha256": "3" * 64,
        "child_start_token_sha256": "4" * 64,
        "descriptors_closed": True, "pid_gone": True, "child_pid": 123,
        "child_pid_gone": True, "cleanup_probe_after_parent_exit": True,
        "process_group_gone": True, "descendants_reaped": True,
        "cleanup_exception": False,
    })
    value["ferry"].update({
        "admissions": 1, "upstream_attempts": 1, "second_rejections": 0,
        "listener_closed": True, "status_calls": 0,
        "request_fingerprint_sha256": "5" * 64, "cleanup_exception": False,
    })
    value["custody"].update({
        "stdout_bytes": 1, "stdout_sha256": "6" * 64,
        "stderr_bytes": 0, "stderr_sha256": "0" * 64,
        "owner_private": True, "raw_public": False,
    })
    value["terminal"] = {"recognized": True, "exactly_one": True,
                         "state": "exact", "parser": "claude-stream-json-v1"}
    value["cleanup"] = {"process_group_reaped": True,
        "verified_copy_removed": True, "listener_closed": True,
        "descriptors_closed": True, "exception_count": 0}
    value["publication"] = {"sanitized": True, "atomic": True,
        "file_fsynced": True, "directory_fsynced": True,
        "final_reopened_nofollow": True, "readback_verified": True,
        "ordering": PUBLICATION_ORDERING, "public_sha256": "7" * 64}
    value["unknown_fence"] = {"durable": False, "durability": "NOT_APPLICABLE",
        "retry": False, "replay": False, "status_calls": 0}
    value["state_authority"] = {"protocol": statemod.STATE_PROTOCOL,
        "generation_sha256": generation, "state": "PASS",
        "precedence": "AUTHORITY_BEFORE_PROJECTIONS", "source_pinned": True}
    validate_seal(value)
    return value


@contextmanager
def _ledger_root():
    with tempfile.TemporaryDirectory(dir=FIX) as name:
        os.chmod(name, 0o700)
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            yield fd, pathlib.Path(name)
        finally:
            os.close(fd)


class AuthorityLedgerV7Tests(unittest.TestCase):
    def test_pinned_authority_exact_and_internal_clock(self):
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
        self.assertEqual(authority.grant["binary"], BINARY_DESCRIPTOR)

    def test_component_no_follow_exact_modes_parent_sync_and_held_race(self):
        with tempfile.TemporaryDirectory(dir=FIX) as name:
            base = pathlib.Path(name); os.chmod(base, 0o700)
            parent = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                (base / "target").mkdir(mode=0o700)
                (base / "wrong").mkdir(mode=0o755)
                (base / "link").symlink_to("target")
                with self.assertRaises(OSError):
                    statemod._open_component(parent, "link", os.getuid(), 0o700, False)
                with self.assertRaises(ContractError):
                    statemod._open_component(parent, "wrong", os.getuid(), 0o700, False)
                with mock.patch.object(statemod, "_sync", wraps=statemod._sync) as sync:
                    made, created = statemod._open_component(
                        parent, "created", os.getuid(), 0o700, True)
                    self.assertTrue(created); os.close(made)
                    self.assertTrue(any(call.args == (parent,) for call in sync.call_args_list))
                held, _ = statemod._open_component(parent, "target", os.getuid(), 0o700, False)
                moved = base / "moved"; (base / "target").rename(moved)
                (base / "decoy").mkdir(mode=0o700)
                (base / "target").symlink_to("decoy", target_is_directory=True)
                generation = "a" * 64; baseline, poison = _unknown_pair(generation)
                statemod._initialize(held, generation, baseline, poison, os.getuid())
                os.close(held)
                self.assertTrue((moved / statemod.LEDGER_NAME).is_file())
                self.assertFalse((base / "decoy" / statemod.LEDGER_NAME).exists())
            finally:
                os.close(parent)

    def test_ledger_mode_symlink_and_truncated_tail_deny(self):
        generation = "b" * 64; baseline, poison = _unknown_pair(generation)
        with _ledger_root() as (fd, path):
            record = statemod._initialize(fd, generation, baseline, poison)
            info = os.stat(statemod.LEDGER_NAME, dir_fd=fd, follow_symlinks=False)
            self.assertEqual((info.st_uid, stat.S_IMODE(info.st_mode)), (501, 0o600))
            held = os.open(statemod.LEDGER_NAME, os.O_WRONLY | os.O_APPEND |
                           os.O_NOFOLLOW, dir_fd=fd)
            try:
                os.write(held, b'{"truncated":'); os.fsync(held)
            finally:
                os.close(held)
            for _ in range(2):
                with self.assertRaises(statemod.PreviousOutcomeUnknownError):
                    statemod._read(fd)
            self.assertEqual(record.state, "UNKNOWN")
        with _ledger_root() as (fd, path):
            (path / "target").write_bytes(b"x")
            (path / statemod.LEDGER_NAME).symlink_to("target")
            with self.assertRaises(OSError):
                statemod._read(fd)

    def test_exact_transition_graph_blocks_regressions_and_mismatches(self):
        generation = "c" * 64; baseline, poison = _unknown_pair(generation)
        passed = _valid_pass(generation)
        with _ledger_root() as (fd, _):
            unknown = statemod._initialize(fd, generation, baseline, poison)
            pass_record = statemod._commit(fd, generation, "PASS", passed)
            self.assertEqual(pass_record.state, "PASS")
            self.assertEqual(statemod._commit(fd, generation, "PASS", passed), pass_record)
            mismatch = copy.deepcopy(passed); mismatch["code"] = "OTHER"
            with self.assertRaises((ContractError, ValueError)):
                statemod._commit(fd, generation, "PASS", mismatch)
            with self.assertRaises(ContractError):
                statemod._commit(fd, generation, "UNKNOWN", baseline)
            poisoned = statemod._poison(fd, pass_record)
            self.assertEqual(poisoned.state, "POISONED")
            self.assertEqual(statemod._poison(fd, poisoned), poisoned)
            with self.assertRaises(ContractError):
                statemod._commit(fd, generation, "PASS", passed)
            self.assertEqual(unknown.state, "UNKNOWN")

    def test_poison_commit_read_ambiguity_never_returns_cached_pass(self):
        generation = "d" * 64; baseline, poison = _unknown_pair(generation)
        passed = _valid_pass(generation)
        with _ledger_root() as (fd, _):
            unknown = statemod._initialize(fd, generation, baseline, poison)
            pass_record = statemod._commit(fd, generation, "PASS", passed)
            real = statemod._append_line
            def append_then_raise(file_fd, raw):
                real(file_fd, raw)
                if b'"claimable":false' in raw and b'"state":"POISONED"' in raw:
                    raise OSError("post-commit return ambiguity")
            with mock.patch.object(statemod, "_append_line", side_effect=append_then_raise):
                with self.assertRaises(statemod.NoTerminalClaimDurabilityError):
                    statemod._poison(fd, pass_record)
            for _ in range(2):
                with self.assertRaises(statemod.PreviousOutcomeUnknownError):
                    statemod._read(fd)
            self.assertEqual(unknown.state, "UNKNOWN")

    def test_recovery_precedes_freshness_and_compound_projection_failure(self):
        generation = "e" * 64; baseline, poison = _unknown_pair(generation)
        with _ledger_root() as (fd, path):
            stored = statemod._initialize(fd, generation, baseline, poison)
            (path / "collision").write_text("must not preempt recovery")
            root = statemod._AuthorityRoot(os.dup(fd), path, False)
            with root:
                self.assertEqual(runmod._recover(root), stored.terminal)
        with tempfile.TemporaryDirectory(dir=FIX) as name:
            path = pathlib.Path(name) / "projection.json"; raw = b'{"safe":true}'
            real_unlink = pathlib.Path.unlink; calls = {"unlink": 0, "rename": 0, "notice": 0}
            def unlink(item, *args, **kwargs):
                if pathlib.Path(item) == path:
                    calls["unlink"] += 1; raise OSError("unlink")
                return real_unlink(item, *args, **kwargs)
            def rename(src, dst, *args, **kwargs):
                if pathlib.Path(src) == path:
                    calls["rename"] += 1; raise OSError("rename")
                return os.rename(src, dst, *args, **kwargs)
            def notice(fd, content):
                calls["notice"] += 1; raise OSError("notice")
            with mock.patch.object(runmod, "_fsync_directory", side_effect=OSError("fsync")), \
                 mock.patch.object(pathlib.Path, "unlink", autospec=True, side_effect=unlink), \
                 mock.patch.object(runmod.os, "rename", side_effect=rename), \
                 mock.patch.object(runmod, "_quarantine_write", side_effect=notice):
                with self.assertRaises(ContractError):
                    runmod._publish_verified(path, raw)
            self.assertTrue(all(value > 0 for value in calls.values()), calls)

    def test_full_writes_survive_short_writes_and_zero_fails(self):
        raw = b"provider-free-ledger-write"
        with tempfile.TemporaryFile() as file:
            real = statemod.os.write
            with mock.patch.object(statemod.os, "write",
                                   side_effect=lambda fd, value: real(fd, value[:3])):
                statemod._write_all(file.fileno(), raw)
            file.seek(0); self.assertEqual(file.read(), raw)
        with tempfile.TemporaryFile() as file:
            with mock.patch.object(statemod.os, "write", return_value=0):
                with self.assertRaises(OSError):
                    statemod._write_all(file.fileno(), raw)


if __name__ == "__main__":
    unittest.main()
