"""Mock-only tests for the macOS VM containment source contract."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from uuid import uuid4

from shared.job_runtime.containment import (
    ArtifactIdentities, ContainedExit, ContainedRequest, ContainmentContractError,
    MountReference, ResourceCeilings,
)
from shared.job_runtime.macos_vm import ContainmentLifecycleError, MacOSVMLifecycle, SwiftHelper


@dataclass
class Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.registered = set()
        self.bootstrap = "ok"
        self.bootout = "ok"
        self.print_unknown = False

    def __call__(self, argv, *, timeout):
        self.calls.append((tuple(argv), timeout))
        action = argv[1]
        if action == "print":
            if self.print_unknown:
                return Result(77, stderr="synthetic permission error")
            return Result(0 if argv[2].split("/", 2)[-1] in self.registered else 113)
        if action == "bootstrap":
            if self.bootstrap == "raise":
                raise TimeoutError("synthetic bootstrap timeout with SECRET_CANARY")
            if self.bootstrap == "refuse":
                return Result(5, stderr="SECRET_CANARY")
            plist = plistlib.loads(Path(argv[3]).read_bytes())
            self.registered.add(plist["Label"])
            return Result(0)
        if action == "bootout":
            label = argv[2].split("/", 2)[-1]
            if self.bootout == "raise":
                raise TimeoutError("synthetic bootout timeout with SECRET_CANARY")
            if self.bootout == "sticky":
                return Result(5)
            self.registered.discard(label)
            return Result(0)
        raise AssertionError(argv)


class FakeHelper:
    def __init__(self, path, artifacts):
        self.path = path
        self.artifact_paths = artifacts
        self.values = [{"code": 0, "output_bytes": 12,
                        "output_truncated": False, "detail_codes": [], "stop_acknowledged": True, "teardown_confirmed": True}]

    def poll(self, attempt_dir, request):
        value = self.values.pop(0) if self.values else None
        if isinstance(value, BaseException):
            raise value
        return value


class Clock:
    def __init__(self): self.value = 100.0
    def __call__(self): return self.value
    def sleep(self, amount): self.value += amount


class ContainmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir(mode=0o700)
        (self.root / ".job-runtime").mkdir(mode=0o700)
        (self.root / "inputs").mkdir()
        (self.root / "inputs" / "payload.ref").write_text("opaque-reference")
        artifacts = {}
        for name in ("helper", "kernel", "initramfs", "root_image", "cow_disk", "guest_agent", "root_manifest"):
            path = self.root / f"{name}.bin"
            path.write_bytes(("synthetic-" + name).encode())
            path.chmod(0o700 if name == "helper" else 0o600)
            artifacts[name] = path
        self.artifact_paths = artifacts
        self.identities = ArtifactIdentities(**{
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in artifacts.items()
        })
        self.runner = FakeRunner()
        self.helper = FakeHelper(artifacts["helper"], artifacts)
        self.clock = Clock()

    def request(self, **changes):
        value = dict(
            attempt_id=str(uuid4()), executable_ref="python-runtime",
            argv_refs=("task-reference",), env_refs={"JOB_INPUT": "input-reference"},
            mounts=(MountReference("input", "inputs/payload.ref", "/input/payload", True),),
            ceilings=ResourceCeilings(1, 1024, 512 * 1024**2, 2 * 1024**3, 1),
            artifacts=self.identities, nonce="a" * 64,
        )
        value.update(changes)
        return ContainedRequest(**value)

    def manager(self):
        return MacOSVMLifecycle(self.root, runner=self.runner, helper=self.helper,
                                uid=501, clock=self.clock, wall_clock=lambda: 1_000.0,
                                sleeper=self.clock.sleep)

    def test_contract_rejects_path_label_and_secret_injection(self):
        for change, code in (
            ({"attempt_id": "../../bad"}, "ATTEMPT_ID_INVALID"),
            ({"executable_ref": "x; launchctl"}, "EXECUTABLE_REF_INVALID"),
            ({"nonce": "$(bad)"}, "NONCE_INVALID"),
            ({"env_refs": {"API_TOKEN": "opaque"}}, "ENV_NAME_REFUSED"),
            ({"argv_refs": ("raw value",)}, "ARGV_REF_INVALID"),
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ContainmentContractError, code):
                self.request(**change)
        with self.assertRaisesRegex(ContainmentContractError, "MOUNT_SOURCE_INVALID"):
            MountReference("input", "../secret", "/input/payload")

    def test_prepare_uses_private_nofollow_state_and_reference_only_request(self):
        request = self.request()
        prepared = self.manager().prepare(request)
        self.assertEqual(prepared.label.count("/"), 0)
        self.assertTrue(prepared.label.startswith(MacOSVMLifecycle.LABEL_PREFIX))
        self.assertEqual(prepared.state_dir.stat().st_mode & 0o777, 0o700)
        for name in ("request.json", "lifecycle.json", "vm.plist"):
            self.assertEqual((prepared.state_dir / name).stat().st_mode & 0o777, 0o600)
        payload = json.loads(prepared.request_path.read_text())
        rendered = json.dumps(payload)
        self.assertEqual(payload["execution"]["argv"], ["task-reference"])
        self.assertEqual(payload["protocolVersion"], 1)
        self.assertNotIn("SECRET_CANARY", rendered)
        self.assertNotIn("SECRET_CANARY", rendered)

    def test_symlink_state_and_mount_are_refused_without_runner_call(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.root / ".job-runtime" / "containment").symlink_to(outside, target_is_directory=True)
        result = self.manager().execute(self.request())
        self.assertEqual(result.classification, "prelaunch_failed")
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(list(outside.iterdir()), [])
        (self.root / ".job-runtime" / "containment").unlink()
        (self.root / "linked").symlink_to(self.root / "inputs", target_is_directory=True)
        result = self.manager().execute(self.request(mounts=(MountReference(
            "input", "linked/payload.ref", "/input/payload"),)))
        self.assertEqual(result.classification, "prelaunch_failed")
        self.assertEqual(self.runner.calls, [])

    def test_artifact_hash_drift_fails_before_launch(self):
        self.artifact_paths["kernel"].write_bytes(b"drift")
        result = self.manager().execute(self.request())
        self.assertEqual(result.classification, "prelaunch_failed")
        self.assertEqual(self.runner.calls, [])

    def test_prepare_pins_artifact_and_mount_bytes_before_sources_change(self):
        request = self.request()
        prepared = self.manager().prepare(request)
        helper_snapshot = prepared.state_dir / "artifacts" / "helper"
        mount_snapshot = prepared.state_dir / "mounts" / "input" / "payload"
        self.artifact_paths["helper"].write_bytes(b"replaced-after-prepare")
        (self.root / "inputs" / "payload.ref").write_bytes(b"changed-after-prepare")
        self.assertEqual(helper_snapshot.read_bytes(), b"synthetic-helper")
        self.assertEqual(mount_snapshot.read_bytes(), b"opaque-reference")
        self.assertEqual(helper_snapshot.stat().st_mode & 0o777, 0o700)
        self.assertEqual(mount_snapshot.stat().st_mode & 0o777, 0o600)
        plist = plistlib.loads(prepared.plist_path.read_bytes())
        self.assertEqual(Path(plist["ProgramArguments"][0]), helper_snapshot)
        payload = json.loads(prepared.request_path.read_text())
        self.assertEqual(payload["mounts"][0]["sourcePath"],
                         str(prepared.state_dir / "mounts" / "input"))

    def test_snapshot_rejects_size_before_destination_allocation(self):
        folder = self.root / ".job-runtime" / "snapshot-budget-test"
        folder.mkdir(mode=0o700)
        descriptor = os.open(folder, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            with self.assertRaisesRegex(ContainmentLifecycleError, "DISK_CEILING_EXCEEDED"):
                MacOSVMLifecycle._snapshot_regular(
                    self.artifact_paths["helper"], descriptor, "too-big", None, 1)
        finally:
            os.close(descriptor)
        self.assertEqual(list(folder.iterdir()), [])

    def test_unknown_prelaunch_print_never_bootstraps_or_claims_absence(self):
        self.runner.print_unknown = True
        request = self.request()
        result = self.manager().execute(request)
        self.assertEqual(result.classification, "prelaunch_failed")
        self.assertFalse(result.label_absent)
        self.assertEqual([call[0][1] for call in self.runner.calls], ["print"])
        self.assertTrue((self.manager().state_root / request.attempt_id / "request.json").exists())

    def test_duplicate_attempt_is_refused_and_first_state_preserved(self):
        request = self.request()
        prepared = self.manager().prepare(request)
        before = prepared.request_path.read_bytes()
        with self.assertRaisesRegex(ContainmentLifecycleError, "DUPLICATE_ATTEMPT"):
            self.manager().prepare(request)
        self.assertEqual(prepared.request_path.read_bytes(), before)

    def test_nonce_is_atomically_one_use_across_attempts(self):
        first = self.request(nonce="1" * 64)
        self.manager().prepare(first)
        second = self.request(nonce="1" * 64)
        with self.assertRaisesRegex(ContainmentLifecycleError, "NONCE_REUSED"):
            self.manager().prepare(second)
        self.assertFalse((self.manager().state_root / second.attempt_id).exists())
        claims = list(self.manager().state_root.glob(".nonce-*"))
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].stat().st_mode & 0o777, 0o600)

    def test_bootstrap_refusal_is_unknown_then_torn_down_and_preserved(self):
        self.runner.bootstrap = "refuse"
        request = self.request()
        result = self.manager().execute(request)
        self.assertEqual(result.classification, "launched_unknown")
        self.assertTrue(result.label_absent)
        self.assertTrue((self.manager().state_root / request.attempt_id / "receipt.json").exists())
        self.assertEqual([call[0][1] for call in self.runner.calls],
                         ["print", "bootstrap", "bootout", "print"])

    def test_bootstrap_exception_is_launched_unknown_and_tears_down(self):
        self.runner.bootstrap = "raise"
        request = self.request()
        result = self.manager().execute(request)
        self.assertEqual(result.classification, "launched_unknown")
        self.assertTrue(result.launchctl_bootout_acknowledged)
        self.assertTrue(result.label_absent)
        self.assertEqual([call[0][1] for call in self.runner.calls],
                         ["print", "bootstrap", "bootout", "print"])

    def test_helper_and_bootout_unknown_are_classified_without_secret_text(self):
        for helper_value, bootout in ((RuntimeError("SECRET_CANARY"), "ok"),
                                      ({"code": 0, "output_bytes": 2,
                                        "output_truncated": False, "detail_codes": [], "stop_acknowledged": True, "teardown_confirmed": True}, "sticky")):
            with self.subTest(bootout=bootout):
                self.runner = FakeRunner()
                self.runner.bootout = bootout
                self.helper.values = [helper_value]
                request = self.request(nonce=("d" if bootout == "ok" else "e") * 64)
                result = self.manager().execute(request)
                if bootout == "sticky":
                    self.assertEqual(result.classification, "launched_unknown")
                    self.assertFalse(result.label_absent)
                else:
                    self.assertEqual(result.classification, "launched_unknown")
                receipt = json.dumps(result.to_receipt())
                self.assertNotIn("SECRET_CANARY", receipt)
                self.assertLess(len(receipt), 16 * 1024)

    def test_timeout_cancel_and_output_limit_flags(self):
        self.helper.values = [None] * 100
        timed = self.manager().execute(self.request(nonce="2" * 64))
        self.assertEqual(timed.classification, "timed_out")
        self.assertTrue(timed.timed_out)
        self.runner = FakeRunner()
        self.helper.values = [None]
        cancelled = self.manager().execute(self.request(nonce="c" * 64), cancelled=lambda: True)
        self.assertEqual(cancelled.classification, "cancelled")
        self.assertTrue(cancelled.cancelled)
        self.runner = FakeRunner()
        self.helper.values = [{"code": 0, "output_bytes": 50_000,
                               "output_truncated": False, "detail_codes": [], "stop_acknowledged": True, "teardown_confirmed": True}]
        limited = self.manager().execute(self.request(nonce="3" * 64))
        self.assertEqual(limited.output_bytes, 1024)
        self.assertTrue(limited.output_truncated)

    def test_success_removes_transient_state_and_receipt_has_no_canaries(self):
        request = self.request()
        result = self.manager().execute(request)
        state = self.manager().state_root / request.attempt_id
        self.assertEqual(result.classification, "completed")
        self.assertEqual(sorted(path.name for path in state.iterdir()), ["lifecycle.json", "receipt.json"])
        receipt = (state / "receipt.json").read_text()
        for canary in ("SECRET_CANARY", str(self.root), "task-reference", "input-reference", "payload.ref"):
            self.assertNotIn(canary, receipt)
        self.assertLess(len(receipt), 16 * 1024)

    def test_stale_reconciliation_is_bounded_and_verifies_absence(self):
        request = self.request()
        prepared = self.manager().prepare(request)
        self.runner.registered.add(prepared.label)
        results = self.manager().reconcile_stale(older_than_seconds=0)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].launchctl_bootout_acknowledged)
        self.assertTrue(results[0].label_absent)
        receipt = json.loads((prepared.state_dir / "receipt.json").read_text())
        self.assertEqual(receipt["classification"], "launched_unknown")
        self.assertEqual([call[0][1] for call in self.runner.calls], ["bootout", "print"])

    def test_future_timestamp_reconciles_but_wrong_label_is_never_booted_out(self):
        future = self.request(nonce="f" * 64)
        future_prepared = self.manager().prepare(future)
        metadata_path = future_prepared.state_dir / "lifecycle.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["created_at"] = 2_000.0
        metadata_path.write_text(json.dumps(metadata))
        metadata_path.chmod(0o600)
        self.runner.registered.add(future_prepared.label)
        results = self.manager().reconcile_stale(older_than_seconds=10)
        self.assertEqual([item.attempt_id for item in results], [future.attempt_id])

        wrong = self.request(nonce="4" * 64)
        wrong_prepared = self.manager().prepare(wrong)
        wrong_metadata_path = wrong_prepared.state_dir / "lifecycle.json"
        wrong_metadata = json.loads(wrong_metadata_path.read_text())
        wrong_metadata["label"] = MacOSVMLifecycle.LABEL_PREFIX + ".other"
        wrong_metadata_path.write_text(json.dumps(wrong_metadata))
        wrong_metadata_path.chmod(0o600)
        self.runner.calls.clear()
        self.runner.registered.add(wrong_prepared.label)
        repeated = self.manager().reconcile_stale(older_than_seconds=0)
        self.assertNotIn(wrong.attempt_id, [item.attempt_id for item in repeated])
        self.assertFalse(any(wrong_prepared.label in call[0][-1] for call in self.runner.calls))
        self.assertIn(wrong_prepared.label, self.runner.registered)

    def test_swift_helper_preserves_nonzero_and_signal_and_rejects_duplicate_json(self):
        for exit_code, signal_value, expected_code, details in (
                (1, None, 1, ()), (-15, 15, -15, ("TERMINATED_BY_SIGNAL",))):
            request = self.request(nonce=("6" if signal_value is None else "7") * 64)
            prepared = self.manager().prepare(request)
            receipt = {"protocolVersion": 1, "requestID": request.attempt_id,
                "requestSHA256": prepared.request_sha256,
                "artifactGeneration": request.artifact_generation,
                "nonceDigest": request.nonce_digest, "outcome": "completed",
                "stopAcknowledged": True, "teardownConfirmed": True,
                "startedAt": None, "stoppedAt": "fixture", "elapsedMilliseconds": 1,
                "outputBytes": 0, "exitCode": exit_code,
                "terminationSignal": signal_value, "errorCode": None}
            path = prepared.state_dir / "receipts" / "helper.json"
            path.write_text(json.dumps(receipt)); path.chmod(0o600)
            adapter = SwiftHelper(self.artifact_paths["helper"], self.artifact_paths)
            mapped = adapter.poll(prepared.state_dir, request)
            self.assertEqual(mapped["code"], expected_code)
            self.assertEqual(tuple(mapped["detail_codes"]), details)
        request = self.request(nonce="8" * 64)
        prepared = self.manager().prepare(request)
        path = prepared.state_dir / "receipts" / "helper.json"
        path.write_text('{"protocolVersion":1,"protocolVersion":1}'); path.chmod(0o600)
        adapter = SwiftHelper(self.artifact_paths["helper"], self.artifact_paths)
        with self.assertRaisesRegex(ContainmentLifecycleError, "STATE_JSON_DUPLICATE_KEY"):
            adapter.poll(prepared.state_dir, request)

    def test_malformed_helper_receipt_is_never_completed(self):
        malformed = {"code": 0, "output_bytes": 1,
                     "output_truncated": "false", "detail_codes": "OK"}
        self.helper.values = [malformed]
        result = self.manager().execute(self.request(nonce="5" * 64))
        self.assertEqual(result.classification, "launched_unknown")
        self.assertTrue(result.label_absent)

    def test_independent_attempts_have_unique_labels_and_state(self):
        first, second = self.request(nonce="a" * 64), self.request(nonce="b" * 64)
        one, two = self.manager().prepare(first), self.manager().prepare(second)
        self.assertNotEqual(one.label, two.label)
        self.assertNotEqual(one.state_dir, two.state_dir)
        self.assertTrue(one.request_path.exists())
        self.assertTrue(two.request_path.exists())

    def test_exit_contract_refuses_unbounded_diagnostics(self):
        attempt = str(uuid4())
        with self.assertRaisesRegex(ContainmentContractError, "EXIT_DETAIL_INVALID"):
            ContainedExit(attempt, "prelaunch_failed", "0"*64, "1"*64, "2"*64, detail_codes=("secret text /tmp/x",))
        with self.assertRaisesRegex(ContainmentContractError, "EXIT_DETAIL_INVALID"):
            ContainedExit(attempt, "prelaunch_failed", "0"*64, "1"*64, "2"*64, detail_codes=("X",) * 17)


if __name__ == "__main__":
    unittest.main()
