import copy
from datetime import datetime, timedelta, timezone
import gc
import hashlib
import json
import os
import shutil
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from shared.job_runtime.candidates.r6_fable_canary_entrypoint_v1 import (
    CanaryEntrypointError, build_test_only_dispatcher,
)
import shared.job_runtime.candidates.r6_fable_canary_entrypoint_v1.entrypoint as entrypoint
import shared.job_runtime.candidates.r6_fable_canary_entrypoint_v1.provider_free_runner as runner_module


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def private_write(path, raw):
    path.write_bytes(raw)
    path.chmod(0o600)


class FableCanaryEntrypointTests(unittest.TestCase):
    NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        state = self.workspace / ".job-runtime"
        self.canary = state / "canary"
        config_dir = state / "config"
        (state / "runs").mkdir(parents=True, mode=0o700)
        state.chmod(0o700)
        self.canary.mkdir(mode=0o700)
        self.dispatch_authority = state / "r6-fable-canary-authority"
        self.dispatch_authority.mkdir(mode=0o700)
        config_dir.mkdir(mode=0o700)
        self.profile = {"provider": "claude_host", **dict(runner_module.EXPECTED_PROFILE)}
        self.config = {"schema_version": 2, "model_profiles": {"fable": self.profile}}
        self.job = {"id": "fable-canary", "model_profile": "fable",
                    "prompt_file": ".job-runtime/config/prompt.md"}
        self.source_paths = dict(entrypoint._SOURCE_PATHS)
        self.closure = self.canary / "source-closure.json"
        self.authority = self.canary / "review-authority.json"
        self.activation = self.canary / "activation.json"
        self.review = self.canary / "independent-review.json"
        self.write_closure()
        self.factory = entrypoint._make_factory(
            self.authority, self.closure, self.source_paths, lambda: self.NOW, os.fsync)
        self.publish_prompt("provider-free prompt")
        self.receipt = self.admit("review-main", "nonce-main-20261112")

    def write_closure(self):
        members = {}
        for name, path in self.source_paths.items():
            raw = Path(path).read_bytes()
            members[name] = {"sha256": sha(raw), "bytes": len(raw)}
        value = {
            "schema_version": 1,
            "candidate_id": entrypoint.CANDIDATE_ID,
            "status": "FINAL_PROVIDER_FREE_REVIEW_PENDING",
            "activation": False,
            "production_enabled": False,
            "source_mode": "uid-current-mode0600-nlink1-regular-bounded-stable-v1",
            "members": members,
            "compatibility_assertions": {
                "claude_bridge_sha256": sha((Path(entrypoint.__file__).parents[2] / "claude_bridge.py").read_bytes()),
                "sdk_import_preflight_claimed": False,
            },
        }
        private_write(self.closure, canonical(value))

    def publish_prompt(self, text):
        self.context = {
            "slot_id": "slot", "attempt_id": "attempt", "attempt_no": 1,
            "scheduled_at": "2026-11-12T12:00:00Z", "operation_id": "attempt/one",
            "prompt_artifact": text,
        }

    def admit(self, review_id, nonce, config=None, issued=None, expires=None):
        config = self.config if config is None else config
        config_sha = sha(canonical(config))
        closure_sha = sha(self.closure.read_bytes())
        profile_sha = sha(canonical(dict(runner_module.EXPECTED_PROFILE)))
        review = {
            "schema_version": 1,
            "contract": "r6-fable-canary-independent-review-v1",
            "candidate_id": entrypoint.CANDIDATE_ID,
            "review_id": review_id,
            "verdict": "CLEAN_PROVIDER_FREE_TEST_ONLY",
            "reviewer_independent": True,
            "source_closure_sha256": closure_sha,
            "config_sha256": config_sha,
            "profile_sha256": profile_sha,
            "activation": False,
            "effects": dict(entrypoint._EFFECTS),
            "reviewed_at": "2026-11-12T11:57:00+00:00",
        }
        review_raw = canonical(review)
        private_write(self.review, review_raw)
        authority = {
            "schema_version": 1, "candidate_id": entrypoint.CANDIDATE_ID,
            "expected_reviews": {review_id: sha(review_raw)},
        }
        private_write(self.authority, canonical(authority))
        issued = issued or self.NOW - timedelta(seconds=30)
        expires = expires or self.NOW + timedelta(seconds=120)
        activation = {
            "schema_version": 1, "candidate_id": entrypoint.CANDIDATE_ID,
            "test_only": True, "production_enabled": False,
            "review_id": review_id, "review_receipt_file": self.review.name,
            "review_receipt_sha256": sha(review_raw),
            "source_closure_sha256": closure_sha,
            "config_sha256": config_sha,
            "profile": dict(runner_module.EXPECTED_PROFILE),
            "nonce": nonce,
            "issued_at": issued.isoformat(), "expires_at": expires.isoformat(),
        }
        private_write(self.activation, canonical(activation))
        return activation

    def build(self, config=None, factory=None):
        return (factory or self.factory)(config or self.config, self.workspace, self.activation)

    def state_path(self, nonce=None):
        nonce = nonce or self.receipt["nonce"]
        return self.dispatch_authority / ("dispatch-" + sha(nonce.encode("ascii")) + ".json")

    def terminal_path(self, nonce=None):
        nonce = nonce or self.receipt["nonce"]
        return self.dispatch_authority / ("terminal-" + sha(nonce.encode("ascii")) + ".json")

    def test_shipped_authority_empty_and_activation_pending(self):
        package = Path(entrypoint.__file__).parent
        authority = json.loads((package / "review_authority.json").read_text())
        pending = json.loads((package / "activation_receipt.pending.json").read_text())
        self.assertEqual(authority["expected_reviews"], {})
        self.assertFalse(pending["activation"])
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_REVIEW_REQUIRED"):
            build_test_only_dispatcher(self.config, self.workspace, self.activation)

    def test_nominal_terminal_success_is_canonical_and_reopen_blocks(self):
        dispatch = self.build()
        result = dispatch(self.job, self.context)
        self.assertEqual((result.status.value, result.code), ("succeeded", "CLAUDE_HOST_CAPTURED"))
        self.assertFalse(result.receipt["provider_called"])
        raw = self.terminal_path().read_bytes()
        record = json.loads(raw)
        self.assertEqual(record["status"], "success")
        self.assertEqual(raw, canonical(record))
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_REPLAY_REJECTED"):
            dispatch(self.job, self.context)
        reopened = self.build()
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_REPLAY_REJECTED"):
            reopened(self.job, self.context)

    def test_concurrent_dispatch_invokes_exactly_once(self):
        dispatch = self.build()
        barrier = threading.Barrier(3)
        outcomes = []

        def call():
            barrier.wait()
            try:
                outcomes.append(dispatch(self.job, self.context).status.value)
            except CanaryEntrypointError as error:
                outcomes.append(str(error))

        threads = [threading.Thread(target=call) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("succeeded"), 1)
        self.assertEqual(outcomes.count("FABLE_CANARY_REPLAY_REJECTED"), 1)

    def test_dispatch_time_expiry_rejects_without_claim(self):
        clock = [self.NOW]
        factory = entrypoint._make_factory(
            self.authority, self.closure, self.source_paths, lambda: clock[0], os.fsync)
        dispatch = self.build(factory=factory)
        clock[0] = self.NOW + timedelta(seconds=121)
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_REVIEW_EXPIRED"):
            dispatch(self.job, self.context)
        self.assertFalse(self.state_path().exists())

    def test_terminal_failed_is_canonical_and_claim_remains_immutable(self):
        self.publish_prompt("__FABLE_CANARY_TEST_FAILURE__")
        result = self.build()(self.job, self.context)
        self.assertEqual(result.status.value, "failed")
        terminal_raw = self.terminal_path().read_bytes()
        terminal = json.loads(terminal_raw)
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal_raw, canonical(terminal))
        claim_raw = self.state_path().read_bytes()
        claim = json.loads(claim_raw)
        self.assertEqual(claim["status"], "CLAIMED")
        self.assertEqual(claim_raw, canonical(claim))

    def test_runner_exception_becomes_durable_unknown_without_replay(self):
        self.publish_prompt("__FABLE_CANARY_TEST_EXCEPTION__")
        result = self.build()(self.job, self.context)
        self.assertEqual(result.status.value, "unknown")
        self.assertEqual(json.loads(self.terminal_path().read_bytes())["status"], "UNKNOWN")
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_REPLAY_REJECTED"):
            self.build()(self.job, self.context)

    def test_strict_json_rejects_noncanonical_duplicate_and_nonfinite(self):
        valid = self.activation.read_bytes()
        variants = [
            b" " + valid,
            valid[:-1] + b',"nonce":"duplicate-nonce"}',
            valid[:-1] + b',"extra":NaN}',
        ]
        for raw in variants:
            private_write(self.activation, raw)
            with self.assertRaises(CanaryEntrypointError):
                self.build()
        with self.assertRaisesRegex(CanaryEntrypointError, "STABLE_JSON_ERROR"):
            entrypoint._strict_json(b'{"x":' + b'9' * 5000 + b'}', "STABLE_JSON_ERROR")
        private_write(self.activation, valid)

    def test_ttl_and_future_skew_are_bounded(self):
        self.admit("ttl-long", "nonce-ttl-long", expires=self.NOW + timedelta(seconds=301))
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_REVIEW_EXPIRED"):
            self.build()
        self.admit("future", "nonce-future-1",
                   issued=self.NOW + timedelta(seconds=6),
                   expires=self.NOW + timedelta(seconds=100))
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_REVIEW_EXPIRED"):
            self.build()
        self.admit("skew-ok", "nonce-skew-ok",
                   issued=self.NOW + timedelta(seconds=5),
                   expires=self.NOW + timedelta(seconds=100))
        self.build()

    def test_dir_fsync_failure_claims_before_runner_and_blocks_replay(self):
        calls = [0]

        def failing_fsync(fd):
            calls[0] += 1
            if calls[0] == 2:
                raise OSError("synthetic dir fsync failure")
            return os.fsync(fd)

        factory = entrypoint._make_factory(
            self.authority, self.closure, self.source_paths,
            lambda: self.NOW, failing_fsync)
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_STATE_INVALID"):
            self.build(factory=factory)(self.job, self.context)
        self.assertEqual(json.loads(self.state_path().read_bytes())["status"], "CLAIMED")
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_REPLAY_REJECTED"):
            self.build()(self.job, self.context)
        recovered = json.loads(self.terminal_path().read_bytes())
        self.assertEqual(recovered["status"], "UNKNOWN")
        self.assertEqual(recovered["result_code"], "FABLE_CANARY_PRIOR_DISPATCH_AMBIGUOUS")

    def test_terminal_dir_fsync_failure_downgrades_to_durable_unknown(self):
        calls = [0]

        def failing_fsync(fd):
            calls[0] += 1
            if calls[0] == 4:
                raise OSError("synthetic terminal dir fsync failure")
            return os.fsync(fd)

        factory = entrypoint._make_factory(
            self.authority, self.closure, self.source_paths,
            lambda: self.NOW, failing_fsync)
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_DISPATCH_UNKNOWN"):
            self.build(factory=factory)(self.job, self.context)
        self.assertEqual(json.loads(self.terminal_path().read_bytes())["status"], "UNKNOWN")

    def test_exact_mode_nlink_leaf_and_parent_symlink_reject(self):
        root = self.canary / "paths"
        root.mkdir(mode=0o700)
        good = root / "good.json"
        private_write(good, b"{}")
        bad_mode = root / "mode.json"
        private_write(bad_mode, b"{}")
        bad_mode.chmod(0o644)
        with self.assertRaises(CanaryEntrypointError):
            entrypoint._read_private(bad_mode, "DENIED", 100)
        hard = root / "hard.json"
        os.link(good, hard)
        with self.assertRaises(CanaryEntrypointError):
            entrypoint._read_private(good, "DENIED", 100)
        hard.unlink()
        leaf_link = root / "leaf.json"
        leaf_link.symlink_to(good)
        with self.assertRaises(CanaryEntrypointError):
            entrypoint._read_private(leaf_link, "DENIED", 100)
        parent_link = self.canary / "linked-parent"
        parent_link.symlink_to(root, target_is_directory=True)
        with self.assertRaises(CanaryEntrypointError):
            entrypoint._read_private(parent_link / "good.json", "DENIED", 100)

    def test_parent_replacement_and_reopened_builder_cannot_replay(self):
        dispatch = self.build()
        detached = self.canary.with_name("canary-detached")
        self.canary.rename(detached)
        self.canary.mkdir(mode=0o700)
        for name in ("source-closure.json", "review-authority.json",
                     "activation.json", "independent-review.json"):
            shutil.copyfile(detached / name, self.canary / name)
            (self.canary / name).chmod(0o600)
        result = dispatch(self.job, self.context)
        self.assertEqual(result.status.value, "succeeded")
        separate_factory = entrypoint._make_factory(
            self.authority, self.closure, self.source_paths, lambda: self.NOW, os.fsync)
        reopened = self.build(factory=separate_factory)
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_REPLAY_REJECTED"):
            reopened(self.job, self.context)
        self.assertTrue(self.state_path().exists())

    def test_leaf_replacement_during_read_is_rejected(self):
        path = self.canary / "replace.json"
        private_write(path, b"x" * 200000)
        original_read = os.read
        replaced = [False]

        def replacing_read(fd, amount):
            data = original_read(fd, amount)
            if not replaced[0]:
                replaced[0] = True
                old = self.canary / "replace-old.json"
                path.rename(old)
                private_write(path, b"y" * 200000)
            return data

        with patch.object(entrypoint.os, "read", replacing_read):
            with self.assertRaisesRegex(CanaryEntrypointError, "DENIED"):
                entrypoint._read_private(path, "DENIED", 300000)

    def test_profile_and_config_drift_reject_before_claim(self):
        drift = copy.deepcopy(self.config)
        drift["model_profiles"]["fable"]["timeout_seconds"] = 6
        self.admit("profile-drift", "nonce-profile-drift", config=drift)
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_PROFILE_DRIFT"):
            self.build(config=drift)
        self.assertFalse(self.state_path("nonce-profile-drift").exists())
        self.admit("config-drift", "nonce-config-drift")
        changed = copy.deepcopy(self.config)
        changed["extra"] = True
        with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_CONFIG_DRIFT"):
            self.build(config=changed)

    def test_global_and_callback_replacement_after_admission_has_no_effect(self):
        dispatch = self.build()
        with patch.object(entrypoint, "make_provider_free_runner", lambda *_: (_ for _ in ()).throw(RuntimeError())), \
             patch.object(runner_module, "make_provider_free_runner", lambda *_: None), \
             patch.object(entrypoint, "os", None), patch.object(entrypoint, "stat", None), \
             patch.object(entrypoint, "threading", None), patch.object(entrypoint, "datetime", None), \
             patch.object(entrypoint, "timezone", None), patch.object(entrypoint, "timedelta", None), \
             patch.object(entrypoint, "_fail", lambda *_: None), \
             patch.object(entrypoint, "_sha", lambda *_: "0" * 64), \
             patch.object(entrypoint, "_canonical", lambda *_: b"forged"), \
             patch.object(entrypoint, "_walk_parent", lambda *_: (_ for _ in ()).throw(RuntimeError())), \
             patch.object(entrypoint, "_write_state", lambda *_: None), \
             patch.object(entrypoint, "CanaryEntrypointError", RuntimeError):
            result = dispatch(self.job, self.context)
        self.assertEqual(result.code, "CLAUDE_HOST_CAPTURED")

    def test_abandoned_built_dispatcher_retains_no_descriptors(self):
        fd_dir = Path("/dev/fd")
        if not fd_dir.exists():
            self.fail("/dev/fd required for descriptor cleanup assertion")
        gc.collect()
        baseline = {entry.name for entry in fd_dir.iterdir()}
        dispatch = self.build()
        del dispatch
        gc.collect()
        self.assertEqual({entry.name for entry in fd_dir.iterdir()}, baseline)

    def test_descriptors_are_cleaned_on_success_and_failure(self):
        fd_dir = Path("/dev/fd")
        if not fd_dir.exists():
            self.fail("/dev/fd required for descriptor cleanup assertion")
        before = len(list(fd_dir.iterdir()))
        self.build()(self.job, self.context)
        after = len(list(fd_dir.iterdir()))
        self.assertLessEqual(after, before + 1)
        self.admit("bad-source", "nonce-bad-source")
        original = Path(self.source_paths["retry_policy"])
        original.chmod(0o644)
        try:
            with self.assertRaisesRegex(CanaryEntrypointError, "FABLE_CANARY_SOURCE_DRIFT"):
                self.build()
        finally:
            original.chmod(0o600)
        final = len(list(fd_dir.iterdir()))
        self.assertLessEqual(final, before + 1)

    def test_review_receipt_is_specific_external_and_noncyclic(self):
        fixture = Path(self.source_paths["fixture_profile"])
        self.assertEqual(json.loads(fixture.read_bytes()), dict(runner_module.EXPECTED_PROFILE))
        review = json.loads(self.review.read_bytes())
        activation = json.loads(self.activation.read_bytes())
        authority = json.loads(self.authority.read_bytes())
        self.assertFalse(review["activation"])
        self.assertNotIn("activation_sha256", review)
        self.assertNotIn("authority_sha256", review)
        self.assertEqual(activation["review_receipt_sha256"], sha(self.review.read_bytes()))
        self.assertEqual(authority["expected_reviews"][review["review_id"]],
                         activation["review_receipt_sha256"])


if __name__ == "__main__":
    unittest.main()
