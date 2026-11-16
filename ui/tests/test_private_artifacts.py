import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from ui.tools import private_artifacts
from ui.tools.private_artifacts import (
    PrivateArtifactConflict,
    PrivateArtifactOutcomeUnknown,
    PrivateArtifactSecurityError,
    PrivateArtifactSizeError,
    publish,
    publish_from_staging,
)

SCRIPT = private_artifacts.ROOT / "ui/tools/private_artifacts.py"
PREFIX = "ui/artifacts/future-private-v1"


class PrivateArtifactPublisherTests(unittest.TestCase):
    def setUp(self):
        self.previous_umask = os.umask(0o022)
        self.addCleanup(os.umask, self.previous_umask)
        self.temp = tempfile.TemporaryDirectory(prefix="private-artifact-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "ui").mkdir(mode=0o755)
        (self.root / "ui/artifacts").mkdir(mode=0o700)

    def destination(self, leaf):
        return f"{PREFIX}/{leaf}"

    def mode(self, path):
        return stat.S_IMODE(path.stat().st_mode)

    def pending(self):
        return list((self.root / "ui/artifacts").rglob(".private-artifact-pending-*"))

    def private_staging(self, name="staging.bin", data=b"staged bytes"):
        path = self.root / name
        path.write_bytes(data)
        path.chmod(0o600)
        return path

    def secure_parent(self, destination):
        current = self.root
        for component in Path(destination).parts[:-1]:
            current /= component
            current.mkdir(mode=0o700, exist_ok=True)
            if component not in ("ui",):
                current.chmod(0o700)
        return self.root / destination

    def test_first_create_has_exact_metadata_and_namespace(self):
        destination = self.destination("run-001/evidence.json")
        result = publish(destination, "snowman: \N{SNOWMAN}", workspace_root=self.root)
        target = self.root / destination
        self.assertEqual(target.read_bytes(), "snowman: \N{SNOWMAN}".encode())
        self.assertEqual((result.mode, result.uid, result.nlink), (0o600, os.getuid(), 1))
        self.assertEqual(self.mode(self.root / PREFIX), 0o700)
        self.assertEqual(self.mode(target.parent), 0o700)
        self.assertEqual(self.pending(), [])

    def test_historical_and_nonversioned_destinations_are_rejected(self):
        historical = self.root / "ui/artifacts/historical.json"
        historical.write_bytes(b"history")
        historical.chmod(0o644)
        attempts = [
            "ui/artifacts/historical.json",
            "ui/artifacts/future/run.json",
            "ui/artifacts/future-private-v1",
            "/ui/artifacts/future-private-v1/x",
            "ui/artifacts/future-private-v1/../x",
            "../ui/artifacts/future-private-v1/x",
            "ui/runtime/x",
        ]
        for destination in attempts:
            with self.subTest(destination=destination):
                with self.assertRaises(PrivateArtifactSecurityError):
                    publish(destination, b"secret", workspace_root=self.root)
        self.assertEqual((historical.read_bytes(), self.mode(historical)), (b"history", 0o644))

    def test_existing_future_leaf_is_stable_conflict_and_never_replaced(self):
        destination = self.destination("run-001/existing.bin")
        target = self.secure_parent(destination)
        target.write_bytes(b"prior")
        target.chmod(0o600)
        before = target.stat()
        with self.assertRaises(PrivateArtifactConflict) as caught:
            publish(destination, b"replacement", workspace_root=self.root)
        after = target.stat()
        self.assertEqual(caught.exception.destination, destination)
        self.assertEqual(target.read_bytes(), b"prior")
        self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))
        self.assertEqual(self.pending(), [])

    def test_same_inode_writer_cannot_turn_create_into_replacement(self):
        destination = self.destination("run-001/mutated.bin")
        target = self.secure_parent(destination)
        target.write_bytes(b"before")
        target.chmod(0o600)
        inode = target.stat().st_ino
        real_link = private_artifacts.os.link

        def mutate_then_link(source, leaf, **kwargs):
            target.write_bytes(b"concurrent-same-inode")
            target.chmod(0o600)
            return real_link(source, leaf, **kwargs)

        with patch.object(private_artifacts.os, "link", side_effect=mutate_then_link):
            with self.assertRaises(PrivateArtifactConflict):
                publish(destination, b"publisher", workspace_root=self.root)
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(target.read_bytes(), b"concurrent-same-inode")
        self.assertEqual(self.pending(), [])

    def test_absent_destination_race_is_conflict_without_clobber(self):
        destination = self.destination("run-001/race.bin")
        target = self.root / destination
        real_link = private_artifacts.os.link

        def race_link(source, leaf, **kwargs):
            target.write_bytes(b"concurrent")
            target.chmod(0o600)
            return real_link(source, leaf, **kwargs)

        with patch.object(private_artifacts.os, "link", side_effect=race_link):
            with self.assertRaises(PrivateArtifactConflict):
                publish(destination, b"publisher", workspace_root=self.root)
        self.assertEqual(target.read_bytes(), b"concurrent")
        self.assertEqual(self.pending(), [])

    def test_post_link_directory_fsync_failure_is_unknown_and_preserves_evidence(self):
        destination = self.destination("run-001/fsync-unknown.bin")
        target = self.root / destination
        real_fsync = private_artifacts.os.fsync
        calls = 0

        def fail_directory_fsync(descriptor):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected directory fsync failure")
            return real_fsync(descriptor)

        with patch.object(private_artifacts.os, "fsync", side_effect=fail_directory_fsync):
            with self.assertRaises(PrivateArtifactOutcomeUnknown) as caught:
                publish(destination, b"evidence", workspace_root=self.root)
        self.assertEqual(caught.exception.destination, destination)
        self.assertEqual(target.read_bytes(), b"evidence")
        self.assertEqual((self.mode(target), target.stat().st_nlink), (0o600, 1))
        self.assertEqual(self.pending(), [])

    def test_post_link_readback_failure_is_unknown_and_preserves_evidence(self):
        destination = self.destination("run-001/readback-unknown.bin")
        target = self.root / destination
        with patch.object(private_artifacts, "_readback", side_effect=OSError("injected")):
            with self.assertRaises(PrivateArtifactOutcomeUnknown):
                publish(destination, b"evidence", workspace_root=self.root)
        self.assertEqual(target.read_bytes(), b"evidence")
        self.assertEqual((self.mode(target), target.stat().st_nlink), (0o600, 1))
        self.assertEqual(self.pending(), [])

    def test_post_link_final_binding_failure_is_unknown_and_preserves_evidence(self):
        destination = self.destination("run-001/binding-unknown.bin")
        target = self.root / destination
        real_verify = private_artifacts._verify_bindings
        calls = 0

        def fail_final(bindings):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise PrivateArtifactSecurityError("injected final binding failure")
            return real_verify(bindings)

        with patch.object(private_artifacts, "_verify_bindings", side_effect=fail_final):
            with self.assertRaises(PrivateArtifactOutcomeUnknown):
                publish(destination, b"evidence", workspace_root=self.root)
        self.assertEqual(target.read_bytes(), b"evidence")
        self.assertEqual((self.mode(target), target.stat().st_nlink), (0o600, 1))

    def test_unknown_must_reconcile_and_blind_retry_conflicts(self):
        destination = self.destination("run-001/reconcile.bin")
        target = self.root / destination
        real_fsync = private_artifacts.os.fsync
        calls = 0

        def fail_once(descriptor):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("unknown")
            return real_fsync(descriptor)

        with patch.object(private_artifacts.os, "fsync", side_effect=fail_once):
            with self.assertRaises(PrivateArtifactOutcomeUnknown):
                publish(destination, b"first", workspace_root=self.root)
        with self.assertRaises(PrivateArtifactConflict):
            publish(destination, b"blind-retry", workspace_root=self.root)
        self.assertEqual(target.read_bytes(), b"first")

    def test_pre_effect_write_failure_cleans_temp_and_created_directories(self):
        historical = self.root / "ui/artifacts/historical.txt"
        historical.write_bytes(b"history")
        historical.chmod(0o644)
        with patch.object(private_artifacts.os, "write", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                publish(self.destination("new/nested/file.bin"), b"x", workspace_root=self.root)
        self.assertFalse((self.root / PREFIX).exists())
        self.assertEqual((historical.read_bytes(), self.mode(historical)), (b"history", 0o644))
        self.assertEqual(self.pending(), [])

    def test_temp_fd_is_closed_once_and_fd_reuse_is_not_double_closed(self):
        destination = self.destination("run-001/fd-owner.bin")
        real_create = private_artifacts._create_temporary
        real_close = private_artifacts.os.close
        real_open = private_artifacts.os.open
        temp_fd = None
        close_count = 0
        sentinel_fd = None

        def capture_create(parent_fd):
            nonlocal temp_fd
            result = real_create(parent_fd)
            temp_fd = result[0]
            return result

        def close_and_reuse(descriptor):
            nonlocal close_count, sentinel_fd
            if descriptor == temp_fd:
                close_count += 1
                real_close(descriptor)
                if close_count == 1:
                    sentinel_fd = real_open("/dev/null", os.O_RDONLY)
                    self.assertEqual(sentinel_fd, descriptor)
                return None
            return real_close(descriptor)

        with patch.object(private_artifacts, "_create_temporary", side_effect=capture_create), \
             patch.object(private_artifacts.os, "close", side_effect=close_and_reuse):
            publish(destination, b"evidence", workspace_root=self.root)
        self.assertEqual(close_count, 1)
        self.assertIsNotNone(sentinel_fd)
        os.fstat(sentinel_fd)
        real_close(sentinel_fd)

    def test_namespace_creation_is_exact_under_extreme_umask(self):
        for mask in (0o700, 0o777):
            with self.subTest(mask=oct(mask)):
                workspace = self.root / f"workspace-{mask:o}"
                (workspace / "ui").mkdir(parents=True, mode=0o755)
                workspace.chmod(0o700)
                previous = os.umask(mask)
                try:
                    destination = self.destination(f"run-{mask:o}/value.bin")
                    publish(destination, b"x", workspace_root=workspace)
                finally:
                    os.umask(previous)
                target = workspace / destination
                self.assertEqual(self.mode(workspace / "ui/artifacts"), 0o700)
                self.assertEqual(self.mode(workspace / PREFIX), 0o700)
                self.assertEqual(self.mode(target.parent), 0o700)
                self.assertEqual(self.mode(target), 0o600)

    def test_workspace_symlink_retarget_wrong_modes_and_owner_fail_closed(self):
        link = self.root.parent / (self.root.name + "-ancestor-link")
        link.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(link.unlink)
        with self.assertRaises(PrivateArtifactSecurityError):
            publish(self.destination("x.bin"), b"x", workspace_root=link)

        unsafe = self.root / "ui/artifacts/unsafe"
        unsafe.mkdir(mode=0o755)
        with self.assertRaises(PrivateArtifactSecurityError):
            publish(self.destination("../unsafe/x"), b"x", workspace_root=self.root)
        self.root.chmod(0o775)
        with self.assertRaises(PrivateArtifactSecurityError):
            publish(self.destination("owner/x"), b"x", workspace_root=self.root)
        self.root.chmod(0o700)
        with patch.object(private_artifacts.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(PrivateArtifactSecurityError):
                publish(self.destination("owner/x"), b"x", workspace_root=self.root)

        parent = self.root / "retarget"
        workspace = parent / "workspace"
        (workspace / "ui/artifacts").mkdir(parents=True, mode=0o700)
        (workspace / "ui").chmod(0o755)
        moved = parent / "moved"
        original = private_artifacts._open_directory
        changed = False

        def retarget(parent_fd, name, **kwargs):
            nonlocal changed
            if name == "ui" and not changed:
                changed = True
                workspace.rename(moved)
                (workspace / "ui/artifacts").mkdir(parents=True, mode=0o700)
                (workspace / "ui").chmod(0o755)
            return original(parent_fd, name, **kwargs)

        with patch.object(private_artifacts, "_open_directory", side_effect=retarget):
            with self.assertRaises(PrivateArtifactSecurityError):
                publish(self.destination("retarget/x"), b"x", workspace_root=workspace)
        self.assertFalse((workspace / PREFIX / "retarget/x").exists())
        self.assertFalse((moved / PREFIX / "retarget/x").exists())

    def test_historical_siblings_are_unchanged_and_not_deleted(self):
        artifacts = self.root / "ui/artifacts"
        historical = artifacts / "historical.json"
        historical.write_bytes(b"historical")
        historical.chmod(0o644)
        retained = artifacts / "retained"
        retained.mkdir(mode=0o700)
        receipt = retained / "receipt.txt"
        receipt.write_bytes(b"retain")
        receipt.chmod(0o640)
        before = {p.relative_to(artifacts).as_posix():
                  (p.stat().st_ino, self.mode(p), p.read_bytes() if p.is_file() else None)
                  for p in artifacts.rglob("*")}
        publish(self.destination("run-001/new.txt"), b"new", workspace_root=self.root)
        for relative, expected in before.items():
            path = artifacts / relative
            self.assertTrue(path.exists(), relative)
            actual = (path.stat().st_ino, self.mode(path), path.read_bytes() if path.is_file() else None)
            self.assertEqual(actual, expected, relative)

    def test_staging_requires_exact_0600_regular_owned_one_link_and_bound(self):
        staging = self.private_staging()
        destination = self.destination("run-001/imported.bin")
        result = publish_from_staging(destination, staging, workspace_root=self.root, max_bytes=64)
        self.assertEqual(result.size, len(b"staged bytes"))
        self.assertEqual((self.root / destination).read_bytes(), b"staged bytes")

        for mode in (0o400, 0o640, 0o644):
            staging.chmod(mode)
            with self.assertRaises(PrivateArtifactSecurityError):
                publish_from_staging(self.destination(f"mode-{mode:o}.bin"), staging,
                                     workspace_root=self.root)
        staging.chmod(0o600)
        staging.write_bytes(b"x" * 65)
        with self.assertRaises(PrivateArtifactSizeError):
            publish_from_staging(self.destination("too-large.bin"), staging,
                                 workspace_root=self.root, max_bytes=64)
        staging.write_bytes(b"hardlinked")
        alias = self.root / "staging-alias.bin"
        os.link(staging, alias)
        with self.assertRaises(PrivateArtifactSecurityError):
            publish_from_staging(self.destination("hardlink.bin"), staging,
                                 workspace_root=self.root)
        alias.unlink()
        staging_link = self.root / "staging-link.bin"
        staging_link.symlink_to(staging)
        with self.assertRaises(PrivateArtifactSecurityError):
            publish_from_staging(self.destination("symlink.bin"), staging_link,
                                 workspace_root=self.root)

    def test_staging_mutations_fail_before_publication(self):
        def same_size(path):
            before = path.stat().st_mtime_ns
            path.write_bytes(b"Z" * 32)
            path.chmod(0o600)
            os.utime(path, ns=(path.stat().st_atime_ns, before + 10_000_000))

        def transient_link(path):
            alias = self.root / "transient-link"
            os.link(path, alias)
            alias.unlink()

        def transient_mode(path):
            path.chmod(0o640)
            path.chmod(0o600)

        mutations = {
            "same-size": same_size,
            "growth": lambda path: path.write_bytes(b"x" * 64),
            "truncate": lambda path: path.write_bytes(b"x"),
            "transient-link": transient_link,
            "transient-mode": transient_mode,
        }
        for name, mutation in mutations.items():
            with self.subTest(mutation=name):
                staging = self.private_staging("stage-" + name, b"a" * 32)
                real_read = private_artifacts.os.read
                changed = False

                def mutating_read(descriptor, count):
                    nonlocal changed
                    data = real_read(descriptor, count)
                    if data and not changed:
                        changed = True
                        time.sleep(0.002)
                        mutation(staging)
                    return data

                destination = self.destination(f"mutation-{name}.bin")
                with patch.object(private_artifacts.os, "read", side_effect=mutating_read):
                    with self.assertRaises((PrivateArtifactSecurityError,
                                            PrivateArtifactSizeError)):
                        publish_from_staging(destination, staging,
                                             workspace_root=self.root, max_bytes=128)
                self.assertFalse((self.root / destination).exists())

    def test_cli_success_conflict_unknown_and_sanitized_output(self):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        destination = self.destination("cli/stdin.bin")
        payload = b"LOW_ENTROPY_SECRET"
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), destination,
             "--workspace", str(self.root), "--stdin"],
            input=payload, capture_output=True, timeout=5, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output, {"status": "PRIVATE_ARTIFACT_PUBLISHED",
                                  "destination": destination})
        self.assertNotIn(payload, result.stdout)

        conflict = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), destination,
             "--workspace", str(self.root), "--stdin"],
            input=b"retry", capture_output=True, timeout=5, env=env)
        self.assertEqual(conflict.returncode, 3)
        self.assertEqual(json.loads(conflict.stdout)["code"], "destination_already_exists")
        self.assertEqual((self.root / destination).read_bytes(), payload)

        unknown_destination = self.destination("cli/unknown.bin")
        stream = io.StringIO()
        with patch.object(private_artifacts, "publish_from_staging",
                          side_effect=PrivateArtifactOutcomeUnknown(unknown_destination)), \
             contextlib.redirect_stdout(stream):
            code = private_artifacts.main([
                unknown_destination, "--workspace", str(self.root),
                "--from-staging", str(self.root / "unused"),
            ])
        unknown = json.loads(stream.getvalue())
        self.assertEqual(code, 4)
        self.assertEqual(unknown, {
            "status": "PRIVATE_ARTIFACT_OUTCOME_UNKNOWN",
            "code": "outcome_unknown_reconcile_required",
            "destination": unknown_destination,
        })
        self.assertNotIn("sha256", unknown)
        self.assertNotIn("size", unknown)

        help_result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--help"],
                                     capture_output=True, text=True, timeout=5, env=env)
        self.assertNotIn("--text", help_result.stdout)
        self.assertNotIn("--metadata", help_result.stdout)


if __name__ == "__main__":
    unittest.main()
