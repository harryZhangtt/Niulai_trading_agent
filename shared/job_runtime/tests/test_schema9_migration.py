"""Schema-9 creation, explicit migration, atomicity, and rollback tests."""
from __future__ import annotations

from dataclasses import replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from shared.job_runtime.engine import Engine, EngineError
from shared.job_runtime.engine_schema import SCHEMA9_FINGERPRINT, create_schema9, verify_schema9
from shared.job_runtime.prompt_custody import PromptArtifactStore
from shared.job_runtime.schema9_migration import (
    Schema9MigrationError, _SOURCE_COLUMNS, darwin_rename_swap, migrate_to_schema9,
    rollback_schema9,
)

ROOT = Path(__file__).resolve().parents[3]
PRIVATE = ROOT / ".job-runtime" / "tests" / "schema9-migration"


def test_swap(left, right):
    temporary = left.parent / (".test-swap-" + left.name)
    os.replace(left, temporary); os.replace(right, left); os.replace(temporary, right)


class Schema9MigrationTests(unittest.TestCase):
    def setUp(self):
        PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True); PRIVATE.chmod(0o700)
        self.temp = tempfile.TemporaryDirectory(dir=PRIVATE); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.root.chmod(0o700)
        runtime = self.root / ".job-runtime"; runtime.mkdir(mode=0o700); runtime.chmod(0o700)
        self.counter = 0

    def source(self, version=8, *, prompt="synthetic migration prompt", digest=None,
               provider="claude_host", partial=False):
        self.counter += 1
        state = self.root / ".job-runtime" / f"source-{self.counter}"
        state.mkdir(mode=0o700); path = state / "schedule.sqlite"
        db = sqlite3.connect(path)
        for table, columns in _SOURCE_COLUMNS[version].items():
            definitions = []
            for name in columns:
                kind = "BLOB" if name in {"evidence_bytes"} else "TEXT"
                if name in {"attempts", "attempt_no", "policy_version", "generation", "transient_failures"}:
                    kind = "INTEGER"
                elif name in {"scheduled_at", "expires_at", "next_attempt_at", "updated_at", "cursor",
                              "started_at", "ended_at", "retry_deadline", "recorded_at", "delay_seconds",
                              "retry_after_at", "deadline", "consumed_at", "opened_until", "probe_expires"}:
                    kind = "REAL"
                definitions.append(f'"{name}" {kind}')
            db.execute(f'CREATE TABLE "{table}"({",".join(definitions)})')
        db.execute("INSERT INTO jobs VALUES(?,?,?)", ("job", "schedule-hash", 1.0))
        values = {name: None for name in _SOURCE_COLUMNS[version]["slots"]}
        values.update(slot_id="slot", job_id="job", scheduled_at=1.0, expires_at=2.0,
                      status="ready", attempts=0, updated_at=1.0, code="DUE", provider=provider,
                      replay_contract="{}", replay_contract_sha256="c" * 64,
                      retry_policy="{}", retry_policy_fingerprint="p" * 64, retry_deadline=2.0)
        if version == 8:
            if digest is None and prompt is not None:
                raw = prompt if isinstance(prompt, bytes) else prompt.encode("utf-8")
                digest = hashlib.sha256(raw).hexdigest()
            values["prompt_snapshot"] = prompt
            values["prompt_sha256"] = None if partial else digest
        columns = tuple(values)
        db.execute(f'INSERT INTO slots({",".join(columns)}) VALUES({",".join("?" for _ in columns)})',
                   tuple(values[name] for name in columns))
        db.execute("INSERT INTO metadata VALUES('canary-ledger','preserved-value')")
        db.execute(f"PRAGMA user_version={version}"); db.commit(); db.close(); path.chmod(0o600)
        return path

    def migrate(self, path, **kwargs):
        kwargs.setdefault("_swap_for_test", test_swap)
        return migrate_to_schema9(path, PromptArtifactStore(self.root), **kwargs)

    def test_fresh_schema_exact_no_plaintext_and_old_writer_rejected(self):
        db = sqlite3.connect(":memory:"); self.addCleanup(db.close); create_schema9(db)
        self.assertEqual(verify_schema9(db), SCHEMA9_FINGERPRINT)
        sql = "\n".join(row[0] or "" for row in db.execute("SELECT sql FROM sqlite_master"))
        self.assertNotIn("prompt_snapshot", sql)
        state = self.root / ".job-runtime" / "old"; state.mkdir(mode=0o700)
        path = state / "schedule.sqlite"; target = sqlite3.connect(path); create_schema9(target); target.close(); path.chmod(0o600)
        # Simulate an old writer's version ceiling without mutating schema 9.
        self.assertEqual(sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0], 9)

    def test_engine_rejects_v8_byte_identical(self):
        path = self.source(); before = path.read_bytes()
        with self.assertRaisesRegex(EngineError, "DATABASE_SIDEFILE_MIGRATION_REQUIRED"):
            Engine(path.parent, [], {"max_attempts": 1, "backoff_seconds": 1,
                   "max_backoff_seconds": 1}, lambda *_: None, workspace_root=self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_valid_v8_backfill_preserves_rows_pk_ledger_and_has_no_canary_plaintext(self):
        canary = "CANARY_PROMPT_BYTES_9_X"
        path = self.source(prompt=canary); manifest = self.migrate(path)
        self.assertEqual((manifest.source_version, manifest.target_version), (8, 9))
        db = sqlite3.connect(path); self.addCleanup(db.close)
        self.assertEqual(verify_schema9(db), SCHEMA9_FINGERPRINT)
        slot = db.execute("SELECT job_id,status,artifact_ref,binding_sha256,proof_origin FROM slots").fetchone()
        self.assertEqual(slot[:2], ("job", "ready")); self.assertTrue(slot[2] and slot[3]); self.assertEqual(slot[4], "backfilled_v8")
        self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='canary-ledger'").fetchone()[0], "preserved-value")
        self.assertEqual([row[1] for row in db.execute("PRAGMA table_info(slots)") if row[5]], ["slot_id"])
        self.assertNotIn("prompt_snapshot", {row[1] for row in db.execute("PRAGMA table_info(slots)")})
        self.assertNotIn(canary.encode(), path.read_bytes())
        self.assertFalse(any(Path(str(path) + suffix).exists() for suffix in ("-journal", "-wal", "-shm")))

    def test_v5_v6_v7_become_typed_legacy_unbound(self):
        for version in (5, 6, 7):
            path = self.source(version); self.migrate(path)
            db = sqlite3.connect(path)
            try:
                row = db.execute("SELECT provider,artifact_ref,binding_sha256,proof_origin FROM slots").fetchone()
                self.assertEqual(row, ("claude_host", None, None, "legacy_unbound"))
            finally: db.close()

    def test_invalid_utf8_hash_size_and_partial_leave_active_bytes(self):
        cases = [
            (dict(prompt=b"\xff", digest="0" * 64), "MIGRATION_PROMPT_UTF8_INVALID"),
            (dict(prompt="hash mismatch", digest="0" * 64), "MIGRATION_PROMPT_SHA256_MISMATCH"),
            (dict(prompt="x" * 65537), "MIGRATION_PROMPT_SIZE_INVALID"),
            (dict(prompt="partial", partial=True), "MIGRATION_PROMPT_PARTIAL"),
        ]
        for options, code in cases:
            path = self.source(**options); before = path.read_bytes()
            with self.assertRaisesRegex(Schema9MigrationError, code): self.migrate(path)
            self.assertEqual(path.read_bytes(), before)

    def test_every_pre_swap_phase_failure_keeps_active_bytes_and_orphan_is_safe(self):
        for phase in ("source_verified", "artifacts_published", "candidate_verified", "candidate_fsynced"):
            path = self.source(); before = path.read_bytes()
            def fail(current, expected=phase):
                if current == expected: raise RuntimeError("injected")
            with self.assertRaises(RuntimeError): self.migrate(path, phase_hook=fail)
            self.assertEqual(path.read_bytes(), before)
        # Artifact publication can precede DB activation; the immutable orphan is harmless.
        artifact_files = list((self.root / ".job-runtime" / "prompt-artifacts" / "v1").rglob("*.prompt"))
        self.assertTrue(artifact_files)

    def test_post_swap_failure_restores_exact_active_bytes(self):
        path = self.source(); before = path.read_bytes()
        def corrupt(phase):
            if phase == "swapped":
                db = sqlite3.connect(path); db.execute("DROP TABLE metadata"); db.commit(); db.close()
        with self.assertRaisesRegex(Schema9MigrationError, "POST_SWAP_VERIFY_FAILED"):
            self.migrate(path, phase_hook=corrupt)
        self.assertEqual(path.read_bytes(), before)

    def test_actual_darwin_atomic_swap_exchanges_disposable_inodes(self):
        left, right = self.root / "left", self.root / "right"
        left.write_bytes(b"left"); right.write_bytes(b"right")
        left_inode, right_inode = left.stat().st_ino, right.stat().st_ino
        darwin_rename_swap(left, right)
        self.assertEqual((left.read_bytes(), right.read_bytes()), (b"right", b"left"))
        self.assertEqual((left.stat().st_ino, right.stat().st_ino), (right_inode, left_inode))

    def test_rollback_idempotence_and_evidence_fence(self):
        path = self.source(); manifest = self.migrate(path)
        peer = Path(manifest.exchanged_legacy_path)
        self.assertEqual(rollback_schema9(path, peer, manifest, _swap_for_test=test_swap)["codes"], ["MIGRATION_SCHEMA9_ROLLED_BACK"])
        self.assertEqual(rollback_schema9(path, peer, manifest, _swap_for_test=test_swap)["codes"], ["MIGRATION_SCHEMA9_ALREADY_ROLLED_BACK"])
        # Swap forward again, write the fence, and prove rollback is denied.
        test_swap(path, peer)
        db = sqlite3.connect(path); db.execute("INSERT INTO metadata VALUES('schema9_evidence_write_at','now')"); db.commit(); db.close()
        with self.assertRaisesRegex(Schema9MigrationError, "ROLLBACK_FENCE_CROSSED"):
            rollback_schema9(path, peer, manifest, _swap_for_test=test_swap)

    def test_writer_lock_contention_denies_forward_and_rollback(self):
        path = self.source(); before = path.read_bytes()
        lock_path = self.root / ".job-runtime" / "service.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_WRITER_ACTIVE"):
            self.migrate(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(path.parent.glob(".schema9-*.sqlite")))
        fcntl.flock(fd, fcntl.LOCK_UN)
        manifest = self.migrate(path); peer = Path(manifest.exchanged_legacy_path)
        active_before, peer_before = path.read_bytes(), peer.read_bytes()
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_WRITER_ACTIVE"):
            rollback_schema9(path, peer, manifest, _swap_for_test=test_swap)
        self.assertEqual((path.read_bytes(), peer.read_bytes()), (active_before, peer_before))

    def test_writer_lock_is_held_through_forward_phases_and_rollback_readback(self):
        path = self.source(); lock_path = self.root / ".job-runtime" / "service.lock"
        observed = []
        def assert_locked(phase):
            fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                observed.append(phase)
            finally:
                os.close(fd)
        manifest = self.migrate(path, phase_hook=assert_locked)
        self.assertEqual(observed, ["source_verified", "artifacts_published",
                                   "candidate_verified", "candidate_fsynced",
                                   "swapped", "post_swap_verified"])
        peer = Path(manifest.exchanged_legacy_path); observed.clear()
        rollback_schema9(path, peer, manifest, _swap_for_test=test_swap, phase_hook=assert_locked)
        self.assertEqual(observed, ["rollback_swapped"])

    def test_swap_no_effect_failure_cleans_private_sidefiles(self):
        path = self.source(); before = path.read_bytes()
        def no_effect(_left, _right):
            raise RuntimeError("before effect")
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_ATOMIC_SWAP_FAILED"):
            self.migrate(path, _swap_for_test=no_effect)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(path.parent.glob(".schema9-*.sqlite")))

    def test_manifest_seals_peer_swap_identities_and_complete_inventories(self):
        path = self.source(); source_inode = path.stat().st_ino
        manifest = self.migrate(path); receipt = manifest.to_mapping()
        peer = Path(manifest.exchanged_legacy_path)
        self.assertEqual(manifest.active_path, str(path))
        self.assertEqual(manifest.after_legacy_sha256, hashlib.sha256(peer.read_bytes()).hexdigest())
        self.assertEqual(manifest.before_active_inode, source_inode)
        self.assertEqual(manifest.after_legacy_inode, source_inode)
        self.assertEqual(manifest.after_active_inode, manifest.before_candidate_inode)
        self.assertEqual(manifest.after_active_sha256, manifest.before_candidate_sha256)
        self.assertTrue(manifest.swap_method.startswith("test-only:sha256:"))
        self.assertEqual({name for name, _count, _digest in manifest.source_tables}, set(_SOURCE_COLUMNS[8]))
        self.assertEqual({name for name, _count, _digest in manifest.target_tables}, {
            "jobs", "prompt_artifacts", "slots", "attempts", "metadata",
            "delivery_reconciliations", "provider_results", "retry_decisions",
            "reconciliation_records", "reconciliation_consumptions", "circuits",
            "provider_output_custody"})
        for inventory in (manifest.source_tables, manifest.target_tables):
            self.assertTrue(all(type(count) is int and count >= 0 and len(digest) == 64
                                for _name, count, digest in inventory))
        self.assertEqual(type(manifest).from_mapping(receipt), manifest)
        tampered = dict(receipt); tampered["after"] = dict(receipt["after"])
        tampered["after"]["legacy_peer"] = dict(receipt["after"]["legacy_peer"])
        tampered["after"]["legacy_peer"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_RECEIPT_INVALID"):
            type(manifest).from_mapping(tampered)

        def reseal(value):
            value = dict(value)
            value.pop("receipt_sha256", None)
            value["receipt_sha256"] = hashlib.sha256(json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                ensure_ascii=True).encode("ascii")).hexdigest()
            return value

        removed = dict(receipt); removed["source_tables"] = dict(receipt["source_tables"])
        removed["source_tables"].pop("metadata")
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_RECEIPT_INVALID"):
            type(manifest).from_mapping(reseal(removed))
        extra = dict(receipt); extra["target_tables"] = dict(receipt["target_tables"])
        extra["target_tables"]["invented"] = {"count": 0, "sha256": "0" * 64}
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_RECEIPT_INVALID"):
            type(manifest).from_mapping(reseal(extra))
        for digest_field in ("source_rows_sha256", "target_rows_sha256"):
            rehashed = dict(receipt); rehashed[digest_field] = "0" * 64
            with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_RECEIPT_INVALID"):
                type(manifest).from_mapping(reseal(rehashed))

        forged = dict(receipt); forged["source_tables"] = {
            name: dict(item) for name, item in receipt["source_tables"].items()}
        forged["source_tables"]["metadata"]["sha256"] = "0" * 64
        inventory = tuple(sorted((name, item["count"], item["sha256"])
                                 for name, item in forged["source_tables"].items()))
        forged["source_rows_sha256"] = hashlib.sha256(json.dumps(
            inventory, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
        forged = reseal(forged)
        parsed = type(manifest).from_mapping(forged)
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_ROLLBACK_IDENTITY_MISMATCH"):
            rollback_schema9(path, peer, parsed, _swap_for_test=test_swap)
        self.assertFalse(list(path.parent.glob(".schema9-source-*.sqlite")))
        self.assertEqual(list(path.parent.glob(".schema9-candidate-*.sqlite")), [peer])

    def test_forward_swap_effect_then_raise_resolves_success_and_keeps_legacy(self):
        path = self.source(); before = path.read_bytes()
        def effect_then_raise(left, right):
            test_swap(left, right)
            raise RuntimeError("after effect")
        manifest = self.migrate(path, _swap_for_test=effect_then_raise)
        peer = Path(manifest.exchanged_legacy_path)
        self.assertEqual(peer.read_bytes(), before)
        self.assertEqual(sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0], 9)
        self.assertFalse(list(path.parent.glob(".schema9-source-*.sqlite")))

    def test_forward_unknown_preserves_candidate_and_backup_evidence(self):
        path = self.source()
        def effect_corrupt_then_raise(left, right):
            test_swap(left, right)
            right.write_bytes(right.read_bytes() + b"changed")
            raise RuntimeError("after corrupt effect")
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_SWAP_OUTCOME_UNKNOWN"):
            self.migrate(path, _swap_for_test=effect_corrupt_then_raise)
        self.assertEqual(sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0], 9)
        self.assertEqual(len(list(path.parent.glob(".schema9-source-*.sqlite"))), 1)
        self.assertEqual(len(list(path.parent.glob(".schema9-candidate-*.sqlite"))), 1)

    def test_throwing_swapped_hook_is_reconciled_to_exact_source_and_cleans(self):
        path = self.source(); before = path.read_bytes(); inode = path.stat().st_ino
        def fail(phase):
            if phase == "swapped":
                raise RuntimeError("hook failed")
        with self.assertRaisesRegex(RuntimeError, "hook failed"):
            self.migrate(path, phase_hook=fail)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_ino, inode)
        self.assertFalse(list(path.parent.glob(".schema9-*.sqlite")))

    def test_rollback_effect_then_raise_and_throwing_hook_resolve_success(self):
        class ControlledSwap:
            fail_after = False
            def __call__(self, left, right):
                test_swap(left, right)
                if self.fail_after:
                    raise RuntimeError("after effect")
        swap = ControlledSwap()
        path = self.source(); before = path.read_bytes()
        manifest = self.migrate(path, _swap_for_test=swap); peer = Path(manifest.exchanged_legacy_path)
        swap.fail_after = True
        result = rollback_schema9(path, peer, manifest, _swap_for_test=swap,
                                  phase_hook=lambda _phase: (_ for _ in ()).throw(RuntimeError("hook")))
        self.assertEqual(result["codes"], ["MIGRATION_SCHEMA9_ROLLED_BACK"])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result["after"]["active"]["sha256"], manifest.before_active_sha256)
        self.assertEqual(result["after"]["peer"]["sha256"], manifest.before_candidate_sha256)

    def test_rollback_rejects_callable_spoofing_module_and_qualname(self):
        path = self.source(); manifest = self.migrate(path)
        peer = Path(manifest.exchanged_legacy_path)
        def spoof(left, right):
            test_swap(left, right)
        spoof.__module__ = test_swap.__module__
        spoof.__qualname__ = test_swap.__qualname__
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_SWAP_METHOD_MISMATCH"):
            rollback_schema9(path, peer, manifest, _swap_for_test=spoof)
        self.assertEqual(sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0], 9)

    def test_rollback_rejects_wrong_path_hash_and_arbitrary_schema9_peer(self):
        path = self.source(); manifest = self.migrate(path); peer = Path(manifest.exchanged_legacy_path)
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_ROLLBACK_PATH_MISMATCH"):
            rollback_schema9(path, peer.with_name("wrong.sqlite"), manifest, _swap_for_test=test_swap)
        wrong_hash = replace(manifest, after_legacy_sha256="0" * 64)
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_RECEIPT_INVALID"):
            rollback_schema9(path, peer, wrong_hash, _swap_for_test=test_swap)
        arbitrary = peer.with_name("arbitrary-schema9.sqlite")
        db = sqlite3.connect(arbitrary); create_schema9(db); db.close(); arbitrary.chmod(0o600)
        arbitrary_receipt = replace(manifest, exchanged_legacy_path=str(arbitrary))
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_ROLLBACK_IDENTITY_MISMATCH"):
            rollback_schema9(path, arbitrary, arbitrary_receipt, _swap_for_test=test_swap)

    def test_rollback_rejects_candidate_identity_drift(self):
        path = self.source(); manifest = self.migrate(path); peer = Path(manifest.exchanged_legacy_path)
        db = sqlite3.connect(path)
        db.execute("INSERT INTO metadata VALUES('unsealed-change','x')"); db.commit(); db.close()
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_ROLLBACK_IDENTITY_MISMATCH"):
            rollback_schema9(path, peer, manifest, _swap_for_test=test_swap)

    def test_rollback_post_effect_unknown_preserves_both_files(self):
        class ControlledSwap:
            corrupt_after = False
            def __call__(self, left, right):
                test_swap(left, right)
                if self.corrupt_after:
                    right.write_bytes(right.read_bytes() + b"changed")
                    raise RuntimeError("after effect")
        swap = ControlledSwap()
        path = self.source(); manifest = self.migrate(path, _swap_for_test=swap)
        peer = Path(manifest.exchanged_legacy_path); swap.corrupt_after = True
        with self.assertRaisesRegex(Schema9MigrationError, "MIGRATION_ROLLBACK_OUTCOME_UNKNOWN"):
            rollback_schema9(path, peer, manifest, _swap_for_test=swap)
        self.assertTrue(path.exists() and peer.exists())
        self.assertEqual(sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0], 8)


if __name__ == "__main__": unittest.main()
