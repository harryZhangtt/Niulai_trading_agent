"""Isolated tests for immutable prompt artifact custody."""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock

from shared.job_runtime.engine_schema import create_schema9, prompt_binding_sha256
from shared.job_runtime.prompt_custody import (
    CapturedPromptV1, PromptArtifactDescriptorV1, PromptArtifactStore,
    PromptCustodyError, SlotPromptBindingV1,
)


class PromptCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir(mode=0o700)
        runtime = self.workspace / ".job-runtime"
        runtime.mkdir(mode=0o700)
        self.config = runtime / "config"
        self.acceptance = runtime / "acceptance"
        self.config.mkdir(mode=0o700)
        self.acceptance.mkdir(mode=0o700)
        self.source = self.config / "prompt.txt"
        self.source.write_bytes(b"synthetic prompt\n")
        self.source.chmod(0o600)
        self.store = PromptArtifactStore(self.workspace)

    def capture(self, source=None):
        source = source or self.source
        return self.store.capture_source(self.workspace,
                                         source.relative_to(self.workspace).as_posix())

    def publish(self, raw=b"synthetic prompt\n", generation="g1",
                provenance="native_v1"):
        self.source.write_bytes(raw)
        self.source.chmod(0o600)
        return self.store.publish(self.capture(), generation, provenance)

    def artifact(self, descriptor):
        return (self.workspace / ".job-runtime" / "prompt-artifacts" / "v1" /
                "sha256" / descriptor.sha256[:2] / descriptor.sha256[2:4] /
                f"{descriptor.sha256}.prompt")

    def database(self, name="runtime.sqlite3", refs=(), statuses=()):
        path = self.workspace / name
        connection = sqlite3.connect(path)
        create_schema9(connection)
        descriptors = {descriptor.ref: descriptor for descriptor in refs}
        descriptors.update({descriptor.ref: descriptor for descriptor, _ in statuses})
        for descriptor in descriptors.values():
            connection.execute("""INSERT INTO prompt_artifacts
                (ref,sha256,length,version,source_identity_sha256,generation,proof_origin)
                VALUES(?,?,?,?,?,?,?)""", (
                descriptor.ref, descriptor.sha256, descriptor.length, descriptor.version,
                descriptor.source_identity_sha256, descriptor.generation,
                descriptor.provenance))
        for index, (descriptor, status) in enumerate(statuses):
            job_id, slot_id = f"j{index}", f"s{index}"
            connection.execute("INSERT INTO jobs VALUES(?,?,?)", (job_id, "schedule", 0.0))
            values = {
                "artifact_ref": descriptor.ref, "sha256": descriptor.sha256,
                "length": descriptor.length, "version": descriptor.version,
                "source_identity_sha256": descriptor.source_identity_sha256,
                "generation": descriptor.generation, "proof_origin": descriptor.provenance,
            }
            values["binding_sha256"] = prompt_binding_sha256(job_id, slot_id, values)
            connection.execute("""INSERT INTO slots(
                slot_id,job_id,scheduled_at,expires_at,status,attempts,updated_at,code,
                artifact_ref,sha256,length,version,source_identity_sha256,binding_sha256,
                generation,proof_origin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                slot_id, job_id, 1.0, 2.0, status, 1, 1.0, "TEST",
                *(values[name] for name in ("artifact_ref", "sha256", "length", "version",
                  "source_identity_sha256", "binding_sha256", "generation", "proof_origin"))))
            connection.execute("""INSERT INTO attempts(
                attempt_id,slot_id,attempt_no,started_at,ended_at,status,code,receipt,
                artifact_ref,sha256,length,version,source_identity_sha256,binding_sha256,
                generation,proof_origin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                f"a{index}", slot_id, 1, 1.0, None if status == "running" else 2.0,
                status, "TEST", None,
                *(values[name] for name in ("artifact_ref", "sha256", "length", "version",
                  "source_identity_sha256", "binding_sha256", "generation", "proof_origin"))))
        connection.commit()
        connection.close()
        path.chmod(0o600)
        return path

    def assertCode(self, code, function, *args, **kwargs):
        with self.assertRaises(PromptCustodyError) as raised:
            function(*args, **kwargs)
        self.assertEqual(str(raised.exception), code)
        self.assertNotIn(str(self.workspace), repr(raised.exception))

    def test_capture_publish_open_nominal_and_exact_modes(self):
        captured = self.capture()
        self.assertEqual(captured.raw, b"synthetic prompt\n")
        self.assertEqual(captured.length, len(captured.raw))
        descriptor = self.store.publish(captured, "generation-1", "native_v1")
        self.assertEqual(descriptor.ref,
                         f"pa1:sha256:{descriptor.sha256}:{descriptor.length}")
        path = self.artifact(descriptor)
        self.assertEqual(path.read_bytes(), captured.raw)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        for directory in (path.parent, path.parent.parent, path.parent.parent.parent,
                          self.workspace / ".job-runtime" / "prompt-artifacts" / "v1"):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        with self.store.open(descriptor) as lease:
            self.assertFalse(hasattr(lease, "fileno"))
            self.assertEqual(b"".join(lease.chunks(3)), captured.raw)
        self.assertTrue(lease.closed)
        self.assertTrue(self.store.verify(descriptor))

    def test_contracts_are_frozen_redacted_and_path_free(self):
        captured = self.capture()
        descriptor = self.store.publish(captured, "g1", "native_v1")
        binding = SlotPromptBindingV1("slot-1", descriptor)
        for value in (captured, descriptor, binding, self.store,
                      self.store.open(descriptor)):
            rendered = repr(value)
            self.assertIn("<redacted>", rendered)
            self.assertNotIn(captured.sha256, rendered)
            self.assertNotIn(captured.raw.decode().strip(), rendered)
            self.assertNotIn(str(self.workspace), rendered)
            if hasattr(value, "close"):
                value.close()
        with self.assertRaises(Exception):
            captured.length = 1

    def test_capture_rejects_path_modes_owner_types_utf8_size_and_links(self):
        self.assertCode("SOURCE_PATH_NOT_APPROVED", self.store.capture_source,
                        self.workspace, "prompt.txt")
        self.source.chmod(0o644)
        self.assertCode("SOURCE_MODE_UNSAFE", self.capture)
        self.source.unlink()
        self.source.mkdir(mode=0o700)
        self.assertCode("SOURCE_TYPE_UNSAFE", self.capture)
        self.source.rmdir()
        self.source.write_bytes(b"\xff")
        self.source.chmod(0o600)
        self.assertCode("SOURCE_UTF8_INVALID", self.capture)
        self.source.write_bytes(b"")
        self.assertCode("SOURCE_SIZE_INVALID", self.capture)
        self.source.write_bytes(b"x" * 65_537)
        self.assertCode("SOURCE_SIZE_INVALID", self.capture)
        self.source.write_bytes(b"safe")
        linked = self.config / "second.txt"
        os.link(self.source, linked)
        self.assertCode("SOURCE_LINK_UNSAFE", self.capture)
        linked.unlink()
        with mock.patch("os.getuid", return_value=os.getuid() + 1):
            self.assertCode("SOURCE_WORKSPACE_UNSAFE", self.capture)

    def test_capture_rejects_symlink_leaf_and_ancestor_swap(self):
        outside = self.workspace / "outside"
        outside.mkdir(mode=0o700)
        target = outside / "prompt.txt"
        target.write_bytes(b"outside")
        target.chmod(0o600)
        self.source.unlink()
        self.source.symlink_to(target)
        self.assertCode("SOURCE_OPEN_FAILED", self.capture)
        self.source.unlink()
        self.source.write_bytes(b"safe")
        self.source.chmod(0o600)
        moved = self.workspace / ".job-runtime" / "config-real"
        self.config.rename(moved)
        self.config.symlink_to(moved, target_is_directory=True)
        self.assertCode("SOURCE_ANCESTRY_UNSAFE", self.store.capture_source,
                        self.workspace, ".job-runtime/config/prompt.txt")

    def test_capture_detects_mutation_even_with_size_and_mtime_restored(self):
        original_read = os.read
        original = self.source.read_bytes()
        original_stat = self.source.stat()
        source_fd = None
        fired = False

        def changing_read(fd, size):
            nonlocal source_fd, fired
            value = original_read(fd, size)
            if not fired and value == original:
                source_fd = fd
                fired = True
                self.source.write_bytes(b"X" * len(original))
                self.source.write_bytes(original)
                os.utime(self.source, ns=(original_stat.st_atime_ns,
                                          original_stat.st_mtime_ns))
            return value

        with mock.patch("os.read", side_effect=changing_read):
            self.assertCode("SOURCE_MUTATED", self.capture)
        self.assertIsNotNone(source_fd)

    def test_workspace_binding_permissions_and_raw_path_ambiguity(self):
        self.workspace.chmod(0o755)
        self.assertEqual(self.capture().raw, b"synthetic prompt\n")
        other = Path(self.temp.name) / "other"
        other.mkdir(mode=0o700)
        (other / ".job-runtime").mkdir(mode=0o700)
        (other / ".job-runtime" / "config").mkdir(mode=0o700)
        alien = other / ".job-runtime" / "config" / "prompt.txt"
        alien.write_bytes(b"alien")
        alien.chmod(0o600)
        self.assertCode("SOURCE_WORKSPACE_MISMATCH", self.store.capture_source,
                        other, ".job-runtime/config/prompt.txt")
        for ambiguous in (".job-runtime//config/prompt.txt",
                          ".job-runtime/./config/prompt.txt",
                          ".job-runtime/config/prompt.txt/",
                          ".job-runtime\\config\\prompt.txt"):
            with self.subTest(ambiguous=ambiguous):
                self.assertCode("SOURCE_PATH_INVALID", self.store.capture_source,
                                self.workspace, ambiguous)
        self.workspace.chmod(0o775)
        self.assertCode("SOURCE_WORKSPACE_UNSAFE", self.capture)

    def test_rejected_intermediate_directory_fd_is_closed(self):
        bad = self.config / "bad"
        bad.mkdir(mode=0o755)
        leaf = bad / "prompt.txt"
        leaf.write_bytes(b"unsafe ancestry")
        leaf.chmod(0o600)
        real_open = os.open
        opened = []

        def recording(path, *args, **kwargs):
            fd = real_open(path, *args, **kwargs)
            if path == "bad":
                opened.append(fd)
            return fd

        with mock.patch("os.open", side_effect=recording):
            self.assertCode("SOURCE_ANCESTRY_UNSAFE", self.store.capture_source,
                            self.workspace, ".job-runtime/config/bad/prompt.txt")
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError):
            os.fstat(opened[0])

    def test_capture_requires_explicit_trailing_eof(self):
        original_read = os.read
        original = self.source.read_bytes()
        fired = False

        def growing_read(fd, size):
            nonlocal fired
            value = original_read(fd, size)
            if not fired and value == original:
                fired = True
                with self.source.open("ab") as stream:
                    stream.write(b"x")
            return value

        with mock.patch("os.read", side_effect=growing_read):
            self.assertCode("SOURCE_MUTATED", self.capture)

    def test_created_directories_are_fsynced(self):
        captured = self.capture()
        real_fsync = os.fsync
        directory_syncs = 0

        def recording(fd):
            nonlocal directory_syncs
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                directory_syncs += 1
            return real_fsync(fd)

        with mock.patch("os.fsync", side_effect=recording):
            self.store.publish(captured, "g1", "native_v1")
        self.assertGreaterEqual(directory_syncs, 6)

    def test_publish_post_fsync_rechecks_nlink_and_shard_identity(self):
        captured = self.capture()
        target = self.artifact(PromptArtifactDescriptorV1(
            1, f"pa1:sha256:{captured.sha256}:{captured.length}", captured.sha256,
            captured.length, captured.source_identity_sha256, "g1", "native_v1"))
        real_fsync = os.fsync
        linked = False

        def add_link(fd):
            nonlocal linked
            result = real_fsync(fd)
            if stat.S_ISDIR(os.fstat(fd).st_mode) and target.exists() and not linked:
                linked = True
                os.link(target, target.with_name("late-link"))
            return result

        with mock.patch("os.fsync", side_effect=add_link):
            self.assertCode("ARTIFACT_POST_FSYNC_UNSAFE", self.store.publish,
                            captured, "g1", "native_v1")

        # Use a different digest so the first injected hard link cannot interfere.
        self.source.write_bytes(b"directory replacement")
        self.source.chmod(0o600)
        captured = self.capture()
        target = self.artifact(PromptArtifactDescriptorV1(
            1, f"pa1:sha256:{captured.sha256}:{captured.length}", captured.sha256,
            captured.length, captured.source_identity_sha256, "g2", "native_v1"))
        replaced = False

        def replace_shard(fd):
            nonlocal replaced
            result = real_fsync(fd)
            if stat.S_ISDIR(os.fstat(fd).st_mode) and target.exists() and not replaced:
                replaced = True
                old = target.parent.with_name(target.parent.name + "-old")
                target.parent.rename(old)
                target.parent.mkdir(mode=0o700)
            return result

        with mock.patch("os.fsync", side_effect=replace_shard):
            self.assertCode("ARTIFACT_SHARD_REPLACED", self.store.publish,
                            captured, "g2", "native_v1")

    def test_publish_is_idempotent_and_concurrent(self):
        for round_index in range(40):
            self.source.write_bytes(f"synthetic prompt {round_index}\n".encode())
            self.source.chmod(0o600)
            captured = self.capture()
            descriptors = []
            failures = []
            barrier = threading.Barrier(6)

            def worker(index):
                try:
                    barrier.wait()
                    descriptors.append(self.store.publish(
                        captured, f"g{round_index}-{index}", "native_v1"))
                except BaseException as exc:
                    failures.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(failures, [])
            self.assertEqual(len(descriptors), 6)
            self.assertEqual({value.ref for value in descriptors}, {descriptors[0].ref})
            self.assertEqual(self.artifact(descriptors[0]).stat().st_nlink, 1)

    def test_publish_lock_and_failure_cleanup(self):
        captured = self.capture()
        shard_fd = self.store._shard_fd(captured.sha256, create=True)
        os.close(shard_fd)
        real_flock = fcntl.flock

        def lock_then_fail(fd, operation):
            real_flock(fd, operation)
            raise OSError("SECRET path")

        with mock.patch("fcntl.flock", side_effect=lock_then_fail):
            self.assertCode("ARTIFACT_LOCK_FAILED", self.store.publish,
                            captured, "g-lock", "native_v1")

        probe_fd = self.store._shard_fd(captured.sha256, create=False)
        try:
            real_flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(probe_fd)

        with mock.patch("os.write", side_effect=OSError("SECRET path")):
            self.assertCode("ARTIFACT_WRITE_FAILED", self.store.publish,
                            captured, "g-write", "native_v1")

        probe_fd = self.store._shard_fd(captured.sha256, create=False)
        try:
            real_flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(probe_fd)
        shard = self.artifact(PromptArtifactDescriptorV1(
            1, f"pa1:sha256:{captured.sha256}:{captured.length}", captured.sha256,
            captured.length, captured.source_identity_sha256, "g-final", "native_v1")).parent
        self.assertFalse(any(path.name.startswith(".tmp-") for path in shard.iterdir()))

        descriptor = self.store.publish(captured, "g-final", "native_v1")
        artifact = self.artifact(descriptor)
        self.assertEqual(artifact.read_bytes(), captured.raw)
        self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600)
        self.assertEqual(artifact.stat().st_nlink, 1)

    def test_publish_handles_short_writes(self):
        captured = self.capture()
        real_write = os.write

        def short(fd, value):
            return real_write(fd, value[:max(1, len(value) // 3)])

        with mock.patch("os.write", side_effect=short):
            descriptor = self.store.publish(captured, "g1", "native_v1")
        self.assertEqual(self.artifact(descriptor).read_bytes(), captured.raw)

    def test_publish_fsync_link_and_unlink_failures_are_fixed_codes(self):
        captured = self.capture()
        shard_fd = self.store._shard_fd(captured.sha256, create=True)
        os.close(shard_fd)
        with mock.patch("os.fsync", side_effect=OSError("SECRET path")):
            self.assertCode("ARTIFACT_FILE_FSYNC_FAILED", self.store.publish,
                            captured, "g1", "native_v1")
        real_link = os.link
        with mock.patch("os.link", side_effect=OSError("SECRET path")):
            self.assertCode("ARTIFACT_LINK_FAILED", self.store.publish,
                            captured, "g1", "native_v1")
        with mock.patch("os.link", side_effect=real_link), \
             mock.patch("os.unlink", side_effect=OSError("SECRET path")):
            self.assertCode("ARTIFACT_TEMP_UNLINK_FAILED", self.store.publish,
                            captured, "g1", "native_v1")
        shard = self.artifact(PromptArtifactDescriptorV1(
            1, f"pa1:sha256:{captured.sha256}:{captured.length}", captured.sha256,
            captured.length, captured.source_identity_sha256, "g1", "native_v1")).parent
        self.assertTrue(any(name.name.startswith(".tmp-") for name in shard.iterdir()))
        self.assertEqual((shard / f"{captured.sha256}.prompt").stat().st_nlink, 2)

    def test_existing_collision_corruption_and_nlink_fail_closed(self):
        descriptor = self.publish()
        path = self.artifact(descriptor)
        path.write_bytes(b"x" * descriptor.length)
        path.chmod(0o600)
        self.assertCode("ARTIFACT_EXISTING_MISMATCH", self.store.publish,
                        self.capture(), "g1", "native_v1")
        path.write_bytes(self.capture().raw)
        link = path.with_name("extra")
        os.link(path, link)
        self.assertCode("ARTIFACT_VERIFY_FAILED", self.store.verify, descriptor)

    def test_lease_detects_replace_truncate_and_growth(self):
        for mutation in ("replace", "truncate", "grow"):
            with self.subTest(mutation=mutation):
                raw = (mutation + " prompt").encode()
                descriptor = self.publish(raw, generation=mutation)
                path = self.artifact(descriptor)
                lease = self.store.open(descriptor)
                if mutation == "replace":
                    replacement = path.with_name("replacement")
                    replacement.write_bytes(raw)
                    replacement.chmod(0o600)
                    os.replace(replacement, path)
                elif mutation == "truncate":
                    os.truncate(path, 1)
                else:
                    with path.open("ab") as stream:
                        stream.write(b"x")
                self.assertCode("LEASE_UNSTABLE", lease.read, 1)
                lease.close()

    def test_lease_bounds_close_and_control_exception(self):
        descriptor = self.publish()
        lease = self.store.open(descriptor)
        self.assertCode("LEASE_READ_SIZE_INVALID", lease.read, 65_537)
        self.assertCode("LEASE_CHUNK_SIZE_INVALID", lambda: list(lease.chunks(0)))
        lease.close()
        self.assertCode("LEASE_CLOSED", lease.read, 1)
        lease = self.store.open(descriptor)
        with self.assertRaisesRegex(RuntimeError, "control"):
            with lease:
                raise RuntimeError("control")
        self.assertTrue(lease.closed)

    def test_gc_dry_run_grace_and_delete_unavailable(self):
        retained = self.publish(b"retained")
        orphan = self.publish(b"orphan")
        database = self.database(refs=(retained, orphan), statuses=((retained, "running"),))
        recent = self.store.collect((database,), 3600)
        self.assertTrue(recent["dry_run"])
        self.assertEqual(recent["candidate_count"], 0)
        old = time.time() - 7200
        os.utime(self.artifact(orphan), (old, old))
        report = self.store.collect((database,), 3600)
        self.assertEqual(report["candidate_count"], 1)
        self.assertTrue(self.artifact(orphan).exists())
        self.assertCode("GC_DELETE_UNAVAILABLE", self.store.collect,
                        (database,), 3600, delete=True)
        self.assertTrue(self.artifact(orphan).exists())
        self.assertTrue(self.artifact(retained).exists())
        self.assertNotIn(orphan.ref, repr(report))

    def test_gc_retains_running_unknown_retry_and_reconciliation_attempts(self):
        descriptors = [self.publish(f"prompt-{i}".encode(), generation=f"g{i}")
                       for i in range(4)]
        statuses = tuple(zip(descriptors, ("running", "unknown", "retry_wait", "reconciling")))
        database = self.database(refs=descriptors, statuses=statuses)
        for descriptor in descriptors:
            old = time.time() - 7200
            os.utime(self.artifact(descriptor), (old, old))
        report = self.store.collect((database,), 0)
        self.assertEqual(report["referenced_count"], 4)
        self.assertEqual(report["candidate_count"], 0)

    def test_gc_uses_escaped_mutable_database_uri_and_rejects_catalog_conflict(self):
        descriptor = self.publish(b"escaped-db")
        database = self.database(name="runtime ? #.sqlite3", refs=(descriptor,),
                                 statuses=((descriptor, "running"),))
        report = self.store.collect((database,), 0)
        self.assertEqual(report["referenced_count"], 1)
        conflicted = PromptArtifactDescriptorV1(
            descriptor.version, descriptor.ref, descriptor.sha256, descriptor.length,
            "f" * 64, descriptor.generation, descriptor.provenance)
        other = self.database(name="other.sqlite3", refs=(conflicted,))
        self.assertCode("GC_DATABASE_METADATA_CONFLICT", self.store.collect,
                        (database, other), 0)

    def test_gc_delete_unavailable_precedes_all_store_or_database_work(self):
        missing = self.workspace / "does-not-exist.sqlite3"
        with mock.patch.object(self.store, "_store_fd",
                               side_effect=AssertionError("must not open store")):
            self.assertCode("GC_DELETE_UNAVAILABLE", self.store.collect,
                            (missing,), 0, delete=True)

    def test_gc_lock_contention_is_bounded_and_fixed_code(self):
        descriptor = self.publish(b"lock-contention")
        database = self.database(refs=(descriptor,))
        lock = self.workspace / ".job-runtime" / "prompt-artifacts" / "v1" / ".gc.lock"
        lock_fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            started = time.monotonic()
            self.assertCode("GC_LOCK_BUSY", self.store.collect, (database,), 0)
            self.assertLess(time.monotonic() - started, 1.0)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def test_gc_requires_identical_double_mark(self):
        descriptor = self.publish(b"double-mark")
        database = self.database(refs=(descriptor,))
        catalog = {descriptor.ref: (
            descriptor.ref, descriptor.sha256, descriptor.length, descriptor.version,
            descriptor.source_identity_sha256, descriptor.generation,
            descriptor.provenance)}
        # First mark has no live refs, second gains one.
        with mock.patch.object(self.store, "_db_refs",
                               side_effect=[(set(), catalog),
                                            ({descriptor.ref}, catalog)]):
            self.assertCode("GC_MARK_CHANGED", self.store.collect, (database,), 0)

    def test_gc_rejects_corrupt_newer_missing_schema_and_unknown_store_entries(self):
        descriptor = self.publish(b"known")
        missing = self.workspace / "missing.sqlite3"
        self.assertCode("GC_DATABASE_OPEN_FAILED", self.store.collect, (missing,), 0)
        corrupt = self.workspace / "corrupt.sqlite3"
        corrupt.write_bytes(b"not sqlite")
        corrupt.chmod(0o600)
        self.assertCode("GC_DATABASE_CORRUPT", self.store.collect, (corrupt,), 0)
        newer = self.database(name="newer.sqlite3")
        connection = sqlite3.connect(newer)
        connection.execute("PRAGMA user_version=10")
        connection.close()
        self.assertCode("GC_DATABASE_SCHEMA_UNSAFE", self.store.collect, (newer,), 0)
        valid = self.database(name="valid.sqlite3")
        unknown = self.artifact(descriptor).parent / ".tmp-crash"
        unknown.write_bytes(b"residue")
        unknown.chmod(0o600)
        self.assertCode("GC_UNKNOWN_ENTRY", self.store.collect, (valid,), 0)

    def test_gc_rejects_schema_drift_and_unknown_status_database_rows(self):
        descriptor = self.publish(b"database-check")
        database = self.database(refs=(descriptor,))
        connection = sqlite3.connect(database)
        connection.execute("DROP TRIGGER immutable_prompt_artifacts_update")
        connection.commit(); connection.close()
        self.assertCode("GC_DATABASE_SCHEMA_UNSAFE", self.store.collect, (database,), 0)
        database = self.database(name="status.sqlite3", refs=(descriptor,),
                                 statuses=((descriptor, "invented"),))
        self.assertCode("GC_DATABASE_UNSAFE_STATE", self.store.collect, (database,), 0)


if __name__ == "__main__":
    unittest.main()
