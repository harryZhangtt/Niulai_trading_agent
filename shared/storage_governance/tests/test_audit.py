from __future__ import annotations

import builtins
import errno
import io
import json
import mmap
import os
import stat
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.storage_governance import audit as audit_module
from shared.storage_governance.audit import (
    ScanLimits, audit_registry, audit_snapshot, main, plan_retention, write_report,
)
from shared.storage_governance.contracts import RegistryError, open_registry_snapshot


_ROLE_ORDER = ("authority", "evidence", "cache", "credential", "projection", "reference")


class StorageAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(os.path.realpath(self.temporary.name))
        self.registry_path = self.workspace / "registry.json"

    def _store(self, store_id: str, root: str, **overrides) -> dict:
        value = {
            "id": store_id,
            "root": root,
            "location_scope": "workspace",
            "status": "current",
            "roles": ["reference"],
            "sensitivity": "internal",
            "owner": "test-owner",
            "format": "artifact-set",
            "writer_model": "read_only",
            "durability": "source_controlled",
            "backup_unit": "directory",
            "retention_class": "source_history",
            "generated_file_mode": None,
            "derived_from": [],
            "migration_triggers": ["Ownership or storage contract changes."],
        }
        value.update(overrides)
        value["roles"] = sorted(value["roles"], key=_ROLE_ORDER.index)
        return value

    def _registry(self, stores: list[dict]) -> None:
        value = {"schema_version": 1, "kind": "storage_governance_registry", "stores": stores}
        self.registry_path.write_text(json.dumps(value), encoding="utf-8")

    def _audit(self, stores: list[dict], *, limits: ScanLimits | None = None) -> dict:
        self._registry(stores)
        return audit_registry(self.registry_path, self.workspace, limits=limits)

    def test_reports_sanitized_store_level_metadata_and_plan(self) -> None:
        root = self.workspace / "evidence"
        root.mkdir(mode=0o700)
        (root / "one.bin").write_bytes(b"1234")
        os.chmod(root / "one.bin", 0o600)
        (root / "nested").mkdir(mode=0o700)
        (root / "nested" / "two.bin").write_bytes(b"12")
        os.chmod(root / "nested" / "two.bin", 0o600)
        store_spec = self._store(
            "evidence-store", "evidence", roles=["evidence"],
            retention_class="evidence_record", writer_model="immutable_publish",
            durability="local_durable", sensitivity="confidential", generated_file_mode="0600",
        )

        report = self._audit([store_spec])
        store = report["stores"][0]
        self.assertTrue(store["exists"])
        self.assertEqual(store["file_count"], 2)
        self.assertEqual(store["aggregate_bytes"], 6)
        self.assertEqual(store["classifications"], {"authority": "no", "evidence": "yes", "cache": "no"})
        self.assertEqual(store["migration_trigger_observations"][0]["status"], "not_evaluable_from_metadata")
        self.assertNotIn("path", store)
        self.assertNotIn("one.bin", json.dumps(store))
        self.assertEqual(plan_retention(report)["actions"][0]["action"], "retain")

    def test_never_opens_registered_file_contents_or_sqlite(self) -> None:
        payload = self.workspace / "credential.sqlite"
        payload.write_bytes(b"private database payload")
        self._registry([self._store(
            "private-store", "credential.sqlite", roles=["credential"], sensitivity="restricted",
            format="sqlite", writer_model="single_writer", durability="local_durable",
            backup_unit="database", retention_class="credential_lifecycle", generated_file_mode="0600",
        )])
        real_open = builtins.open

        def guarded_open(file, *args, **kwargs):
            if Path(file) == payload:
                raise AssertionError("payload content was opened")
            return real_open(file, *args, **kwargs)

        real_os_read = os.read
        payload_stat = os.lstat(payload)

        def guarded_read(descriptor, *args, **kwargs):
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) == (payload_stat.st_dev, payload_stat.st_ino):
                raise AssertionError("payload descriptor was read")
            return real_os_read(descriptor, *args, **kwargs)

        with (
            patch("builtins.open", side_effect=guarded_open),
            patch("os.read", side_effect=guarded_read),
            patch.object(sqlite3, "connect", side_effect=AssertionError("sqlite opened")),
            patch.object(mmap, "mmap", side_effect=AssertionError("payload mapped")),
        ):
            report = audit_registry(self.registry_path, self.workspace)
        self.assertEqual(report["stores"][0]["root_type"], "file")
        self.assertEqual(report["stores"][0]["aggregate_bytes"], len(b"private database payload"))

    def test_does_not_follow_root_or_nested_symlinks(self) -> None:
        outside_parent = tempfile.TemporaryDirectory()
        self.addCleanup(outside_parent.cleanup)
        outside = Path(outside_parent.name)
        (outside / "secret").write_bytes(b"do not inspect")
        root = self.workspace / "store"
        root.mkdir()
        (root / "link").symlink_to(outside, target_is_directory=True)
        report = self._audit([self._store("nested-link", "store")])
        store = report["stores"][0]
        self.assertEqual(store["file_count"], 0)
        self.assertEqual(store["aggregate_bytes"], 0)
        self.assertEqual(store["symlink_findings"]["count"], 1)

        (self.workspace / "root-link").symlink_to(outside, target_is_directory=True)
        report = self._audit([self._store("root-link", "root-link")])
        self.assertEqual(report["stores"][0]["root_type"], "symlink")
        self.assertEqual(report["stores"][0]["file_count"], 0)

    def test_external_store_is_not_mapped_into_or_inspected_in_workspace(self) -> None:
        decoy = self.workspace / "external-logical-name"
        decoy.mkdir()
        (decoy / "payload").write_bytes(b"must not be counted")
        report = self._audit([self._store(
            "external-store", "external-logical-name", location_scope="external", status="unverified",
            writer_model="external_managed", durability="external_unverified",
            backup_unit="external_store", retention_class="external_policy",
        )])
        store = report["stores"][0]
        self.assertIsNone(store["exists"])
        self.assertEqual(store["root_type"], "external_unverified")
        self.assertEqual(store["file_count"], 0)
        self.assertEqual(plan_retention(report)["actions"][0]["action"], "manual-review")

    def test_rejects_workspace_path_escape(self) -> None:
        self._registry([self._store("escape", "../outside")])
        with self.assertRaises(RegistryError):
            audit_registry(self.registry_path, self.workspace)

    def test_scan_is_bounded_by_file_depth_and_byte_limits(self) -> None:
        root = self.workspace / "bounded"
        root.mkdir()
        for index in range(5):
            (root / f"file-{index}").write_bytes(b"x")
        report = self._audit([self._store("files", "bounded")], limits=ScanLimits(2, 3, 100))
        self.assertTrue(report["stores"][0]["scan_truncated"])
        self.assertIn("max_files", report["stores"][0]["truncation_reasons"])
        self.assertLessEqual(report["stores"][0]["file_count"], 2)

        deep = self.workspace / "deep"
        (deep / "a" / "b").mkdir(parents=True)
        (deep / "a" / "b" / "payload").write_bytes(b"hidden by depth bound")
        report = self._audit([self._store("depth", "deep")], limits=ScanLimits(100, 1, 100))
        self.assertIn("max_depth", report["stores"][0]["truncation_reasons"])
        self.assertEqual(report["stores"][0]["file_count"], 0)

        byte_root = self.workspace / "bytes"
        byte_root.mkdir()
        (byte_root / "large").write_bytes(b"12345")
        report = self._audit([self._store("bytes", "bytes")], limits=ScanLimits(100, 3, 4))
        self.assertIn("max_bytes", report["stores"][0]["truncation_reasons"])

    def test_private_atomic_report_permissions_and_location(self) -> None:
        report = {"schema": "test", "stores": []}
        destination = write_report(report, self.workspace, filename="result.json")
        expected_parent = self.workspace / ".job-runtime" / "storage-governance"
        self.assertEqual(destination, expected_parent / "result.json")
        self.assertEqual(stat.S_IMODE(os.lstat(expected_parent).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.lstat(destination).st_mode), 0o600)
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), report)
        self.assertEqual([path.name for path in expected_parent.iterdir()], ["result.json"])
        with self.assertRaises(ValueError):
            write_report(report, self.workspace, filename="../escape.json")

    def test_audit_and_planner_delete_nothing_and_cache_is_review_only(self) -> None:
        root = self.workspace / "cache"
        root.mkdir()
        payload = root / "keep-me"
        payload.write_bytes(b"cache")
        spec = self._store(
            "cache-store", "cache", roles=["cache"], writer_model="generated_output",
            durability="ephemeral", retention_class="rebuildable_cache",
        )
        with patch("os.unlink", side_effect=AssertionError("delete attempted")), patch(
            "os.remove", side_effect=AssertionError("delete attempted")
        ), patch("os.rmdir", side_effect=AssertionError("delete attempted")):
            report = self._audit([spec])
            plan = plan_retention(report)
        self.assertTrue(payload.exists())
        self.assertFalse(plan["performed"])
        self.assertEqual(plan["actions"][0]["action"], "rebuildable-cache-review")

    def test_permission_and_manual_review_findings_are_store_level(self) -> None:
        root = self.workspace / "private"
        root.mkdir(mode=0o777)
        os.chmod(root, 0o777)
        spec = self._store(
            "private-store", "private", roles=["credential"], sensitivity="restricted",
            format="private-files", writer_model="single_writer", durability="local_durable",
            retention_class="credential_lifecycle", generated_file_mode="0600",
        )
        report = self._audit([spec])
        findings = report["stores"][0]["permission_findings"]
        self.assertIn("root_world_writable", findings)
        self.assertIn("private_root_group_or_world_accessible", findings)
        self.assertEqual(plan_retention(report)["actions"][0]["action"], "manual-review")

    def test_ephemeral_retention_plans_archive_without_acting(self) -> None:
        root = self.workspace / "artifacts"
        root.mkdir()
        report = self._audit([self._store(
            "artifacts", "artifacts", roles=["cache", "projection"],
            writer_model="generated_output", durability="ephemeral", retention_class="ephemeral_artifact",
        )])
        plan = plan_retention(report)
        self.assertFalse(plan["performed"])
        self.assertEqual(plan["actions"][0]["action"], "archive")


    def test_report_rejects_symlink_parent_and_insecure_parent_mode(self) -> None:
        report = {"schema": "test", "stores": []}
        outside_parent = tempfile.TemporaryDirectory()
        self.addCleanup(outside_parent.cleanup)
        outside = Path(outside_parent.name)
        (self.workspace / ".job-runtime").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RegistryError):
            write_report(report, self.workspace)
        self.assertEqual(list(outside.iterdir()), [])

        (self.workspace / ".job-runtime").unlink()
        runtime = self.workspace / ".job-runtime"
        runtime.mkdir(mode=0o700)
        output = runtime / "storage-governance"
        output.mkdir(mode=0o755)
        os.chmod(output, 0o755)
        with patch("os.chmod", side_effect=AssertionError("publisher attempted chmod")):
            with self.assertRaises(RegistryError):
                write_report(report, self.workspace)

    def test_report_retarget_race_stays_bound_to_open_descriptor(self) -> None:
        runtime = self.workspace / ".job-runtime"
        runtime.mkdir(mode=0o700)
        output = runtime / "storage-governance"
        output.mkdir(mode=0o700)
        detached = runtime / "detached-output"
        real_replace = os.replace

        def retarget_then_replace(source, destination, **kwargs):
            output.rename(detached)
            output.mkdir(mode=0o700)
            return real_replace(source, destination, **kwargs)

        with patch("os.replace", side_effect=retarget_then_replace):
            with self.assertRaises(RegistryError):
                write_report({"safe": True}, self.workspace, filename="race.json")
        self.assertEqual(list(output.iterdir()), [])
        self.assertTrue((detached / "race.json").is_file())

    def test_report_replaces_hardlink_or_symlink_without_target_chmod(self) -> None:
        runtime = self.workspace / ".job-runtime"
        runtime.mkdir(mode=0o700)
        output = runtime / "storage-governance"
        output.mkdir(mode=0o700)
        target = self.workspace / "arbitrary-target"
        target.write_text("unchanged", encoding="utf-8")
        os.chmod(target, 0o640)
        target_mode = stat.S_IMODE(os.lstat(target).st_mode)

        for kind in ("hardlink", "symlink"):
            with self.subTest(kind=kind):
                destination = output / f"{kind}.json"
                if kind == "hardlink":
                    os.link(target, destination)
                else:
                    destination.symlink_to(target)
                with patch("os.chmod", side_effect=AssertionError("publisher attempted chmod")):
                    write_report({"kind": kind}, self.workspace, filename=destination.name)
                self.assertEqual(target.read_text(encoding="utf-8"), "unchanged")
                self.assertEqual(stat.S_IMODE(os.lstat(target).st_mode), target_mode)
                self.assertFalse(destination.is_symlink())
                self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"kind": kind})

    def test_scan_oserror_classification_is_errno_specific(self) -> None:
        root = self.workspace / "errors"
        (root / "child").mkdir(parents=True)
        (root / "child" / "payload").write_bytes(b"x")
        self._registry([self._store("errors", "errors")])
        real_open = os.open
        cases = (
            (errno.EACCES, "permission_unreadable", True, False),
            (errno.ELOOP, None, True, True),
            (errno.EMFILE, "resource_limit", True, False),
            (errno.EIO, "other", True, False),
        )
        for code, error_key, truncated, symlink in cases:
            with self.subTest(errno=code):
                def guarded_open(name, flags, mode=0o777, *, dir_fd=None):
                    if name == "child" and dir_fd is not None:
                        raise OSError(code, "injected")
                    return real_open(name, flags, mode, dir_fd=dir_fd)

                with patch("os.open", side_effect=guarded_open):
                    store = audit_registry(self.registry_path, self.workspace)["stores"][0]
                self.assertEqual(store["scan_truncated"], truncated)
                self.assertEqual(store["symlink_findings"]["present"], symlink)
                if error_key is not None:
                    self.assertEqual(store["scan_error_findings"][error_key], 1)
                if code == errno.EACCES:
                    self.assertIn("entry_unreadable", store["permission_findings"])
                if code == errno.EIO:
                    self.assertIn("scan_error", store["truncation_reasons"])

    def test_depth_first_scan_bounds_open_directory_descriptors(self) -> None:
        root = self.workspace / "fd-bound"
        for branch in range(12):
            leaf = root / f"branch-{branch}" / "one" / "two" / "three"
            leaf.mkdir(parents=True)
            (leaf / "payload").write_bytes(b"x")
        self._registry([self._store("fd-bound", "fd-bound")])
        real_scandir = os.scandir
        baseline = len(os.listdir("/dev/fd"))
        peak_delta = 0

        def tracking_scandir(path):
            nonlocal peak_delta
            iterator = real_scandir(path)
            peak_delta = max(peak_delta, len(os.listdir("/dev/fd")) - baseline)
            return iterator

        limits = ScanLimits(max_files=1000, max_depth=4, max_bytes=1000)
        with patch("os.scandir", side_effect=tracking_scandir):
            audit_registry(self.registry_path, self.workspace, limits=limits)
        self.assertLessEqual(peak_delta, limits.max_depth + 1)

    def test_sqlite_sidecars_are_metadata_only_sanitized_and_bounded(self) -> None:
        database = self.workspace / "database.sqlite"
        database.write_bytes(b"db")
        journal = self.workspace / "database.sqlite-journal"
        journal.write_bytes(b"123")
        shm = self.workspace / "database.sqlite-shm"
        shm.write_bytes(b"12345")
        os.chmod(shm, 0o666)
        outside = self.workspace / "outside"
        outside.write_bytes(b"do not follow")
        (self.workspace / "database.sqlite-wal").symlink_to(outside)
        (self.workspace / "database.sqlite.wal").write_bytes(b"not an exact sidecar")
        spec = self._store(
            "sqlite-store", "database.sqlite", format="sqlite", roles=["credential"],
            sensitivity="restricted", writer_model="single_writer", durability="local_durable",
            backup_unit="database", retention_class="credential_lifecycle", generated_file_mode="0600",
        )
        self._registry([spec])
        protected = {os.lstat(path).st_ino for path in (database, journal, shm, outside)}
        real_open = os.open

        def guarded_open(name, flags, mode=0o777, *, dir_fd=None):
            descriptor = real_open(name, flags, mode, dir_fd=dir_fd)
            metadata = os.fstat(descriptor)
            if metadata.st_ino in protected:
                real_opened = descriptor
                os.close(real_opened)
                raise AssertionError("registered payload or sidecar content opened")
            return descriptor

        with patch("os.open", side_effect=guarded_open):
            store = audit_registry(self.registry_path, self.workspace)["stores"][0]
        sidecars = store["sqlite_sidecars"]
        self.assertEqual(sidecars["count"], 3)
        self.assertEqual(sidecars["aggregate_bytes"], 8)
        self.assertEqual(store["file_count"], 3)
        self.assertEqual(store["aggregate_bytes"], 10)
        self.assertIn("private_entry_group_or_world_accessible", sidecars["permission_findings"])
        self.assertEqual(sidecars["symlink_findings"], {"present": True, "count": 1})
        serialized = json.dumps(store)
        self.assertNotIn("database.sqlite-wal", serialized)
        self.assertNotIn("database.sqlite-shm", serialized)

        bounded = audit_registry(
            self.registry_path, self.workspace, limits=ScanLimits(2, 3, 1 << 20)
        )["stores"][0]
        self.assertIn("max_files", bounded["truncation_reasons"])
        self.assertLessEqual(bounded["file_count"], 2)

    def test_sqlite_sidecar_errno_is_sanitized(self) -> None:
        database = self.workspace / "state.sqlite"
        database.write_bytes(b"db")
        self._registry([self._store("sqlite", "state.sqlite", format="sqlite")])
        real_stat = os.stat

        def guarded_stat(name, *args, **kwargs):
            if name == "state.sqlite-shm" and kwargs.get("dir_fd") is not None:
                raise OSError(errno.EACCES, "injected private detail")
            return real_stat(name, *args, **kwargs)

        with patch("os.stat", side_effect=guarded_stat):
            store = audit_registry(self.registry_path, self.workspace)["stores"][0]
        self.assertEqual(store["sqlite_sidecars"]["error_findings"]["permission_unreadable"], 1)
        self.assertIn("permission_unreadable", store["truncation_reasons"])
        self.assertNotIn("injected private detail", json.dumps(store))

    def test_exists_and_missing_triggers_are_tristate_for_unverified_stores(self) -> None:
        (self.workspace / "unverified").mkdir()

        def trigger(identifier: str, metric: str, threshold: bool) -> dict:
            return {
                "id": identifier,
                "metric": metric,
                "operator": "==",
                "threshold": threshold,
                "rationale": "Metadata-only existence check.",
            }

        stores = [
            self._store(
                "external", "external-logical", location_scope="external", status="unverified",
                writer_model="external_managed", durability="external_unverified",
                backup_unit="external_store", retention_class="external_policy",
                migration_triggers=[trigger("external-exists", "exists", True)],
            ),
            self._store(
                "unverified", "unverified", status="unverified",
                migration_triggers=[trigger("unverified-missing", "missing", False)],
            ),
            self._store(
                "missing", "missing", migration_triggers=[trigger("current-missing", "missing", True)],
            ),
        ]
        by_id = {item["store_id"]: item for item in self._audit(stores)["stores"]}
        for store_id in ("external", "unverified"):
            observation = by_id[store_id]["migration_trigger_observations"][0]
            self.assertIsNone(observation["observed"])
            self.assertEqual(observation["status"], "not_evaluable_from_metadata")
        current = by_id["missing"]["migration_trigger_observations"][0]
        self.assertTrue(current["observed"])
        self.assertEqual(current["status"], "observed")

    def test_cli_rejects_malicious_scope_output_and_limits_without_report(self) -> None:
        root = self.workspace / "safe"
        root.mkdir()
        self._registry([self._store("safe", "safe")])
        outside = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(lambda: outside.rmdir())
        cases = (
            ["--registry", os.fspath(self.registry_path), "--workspace", os.fspath(outside)],
            [
                "--registry", os.fspath(self.registry_path), "--workspace", os.fspath(self.workspace),
                "--output-name", "../escape.json",
            ],
            [
                "--registry", os.fspath(self.registry_path), "--workspace", os.fspath(self.workspace),
                "--max-files", "0",
            ],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(main(arguments), 2)
        self.assertFalse((self.workspace / ".job-runtime").exists())
        self.assertFalse((self.workspace.parent / "escape.json").exists())

    def test_audit_and_planner_use_no_mutating_filesystem_syscalls(self) -> None:
        root = self.workspace / "read-only"
        root.mkdir()
        payload = root / "payload"
        payload.write_bytes(b"keep")
        self._registry([self._store("read-only", "read-only")])
        forbidden = ("unlink", "remove", "rmdir", "rename", "replace", "chmod", "chown", "truncate")
        patches = [patch(f"os.{name}", side_effect=AssertionError(f"{name} attempted")) for name in forbidden]
        for active in patches:
            active.start()
            self.addCleanup(active.stop)
        report = audit_registry(self.registry_path, self.workspace)
        plan = plan_retention(report)
        self.assertFalse(plan["performed"])
        self.assertEqual(payload.read_bytes(), b"keep")


    def test_direct_report_accepts_owner_controlled_0755_workspace(self) -> None:
        os.chmod(self.workspace, 0o755)
        destination = write_report({"safe": True}, self.workspace, filename="0755.json")
        self.assertEqual(
            destination,
            self.workspace / ".job-runtime" / "storage-governance" / "0755.json",
        )
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"safe": True})

    def test_direct_report_rejects_workspace_symlink_and_unsafe_workspace(self) -> None:
        link = self.workspace.parent / f"{self.workspace.name}-link"
        link.symlink_to(self.workspace, target_is_directory=True)
        self.addCleanup(lambda: link.unlink(missing_ok=True))
        with self.assertRaises(RegistryError):
            write_report({"safe": True}, link)
        self.assertFalse((self.workspace / ".job-runtime").exists())

        os.chmod(self.workspace, 0o775)
        with self.assertRaises(RegistryError):
            write_report({"safe": True}, self.workspace)
        os.chmod(self.workspace, 0o700)
        with patch.object(audit_module.os, "geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(RegistryError):
                write_report({"safe": True}, self.workspace)

    def test_permission_findings_are_owner_mode_and_type_specific(self) -> None:
        metadata = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=os.geteuid() + 1)
        findings = audit_module._permission_kinds(
            metadata,
            True,
            False,
            expected_uid=os.geteuid(),
            generated_file_mode="0600",
        )
        self.assertIn("entry_owner_mismatch", findings)
        self.assertIn("entry_regular_file_owner_mismatch", findings)
        self.assertIn("entry_regular_file_generated_mode_mismatch", findings)
        self.assertIn("private_entry_regular_file_group_or_world_accessible", findings)

    def test_metric_specific_evaluability_for_incomplete_snapshots(self) -> None:
        def triggers() -> list[dict]:
            boolean = ("exists", "missing", "permission_finding", "scan_truncated", "symlink_present")
            values = [
                {
                    "id": f"metric-{metric.replace(chr(95), chr(45))}", "metric": metric,
                    "operator": "==", "threshold": True,
                    "rationale": "Review incomplete metadata.",
                }
                for metric in boolean
            ]
            values.extend([
                {
                    "id": "metric-files", "metric": "file_count", "operator": ">=",
                    "threshold": 1, "rationale": "Review incomplete file count.",
                },
                {
                    "id": "metric-bytes", "metric": "aggregate_bytes", "operator": ">=",
                    "threshold": 1, "rationale": "Review incomplete byte count.",
                },
            ])
            return values

        truncated = self.workspace / "truncated"
        truncated.mkdir()
        (truncated / "one").write_bytes(b"1")
        (truncated / "two").write_bytes(b"2")
        permission = self.workspace / "permission"
        permission.mkdir()
        os.chmod(permission, 0o777)
        (permission / "one").write_bytes(b"1")
        (permission / "two").write_bytes(b"2")
        symlink_target = self.workspace / "symlink-target"
        symlink_target.mkdir()
        (self.workspace / "symlink-root").symlink_to(symlink_target, target_is_directory=True)
        stores = [
            self._store("missing-all", "missing-all", migration_triggers=triggers()),
            self._store("truncated", "truncated", migration_triggers=triggers()),
            self._store("permission", "permission", migration_triggers=triggers()),
            self._store("symlink-root", "symlink-root", migration_triggers=triggers()),
        ]
        by_id = {
            item["store_id"]: item
            for item in self._audit(stores, limits=ScanLimits(1, 3, 100))["stores"]
        }

        def observations(store_id: str) -> dict[str, dict]:
            return {
                item["metric"]: item
                for item in by_id[store_id]["migration_trigger_observations"]
            }

        missing = observations("missing-all")
        self.assertTrue(missing["missing"]["observed"])
        self.assertFalse(missing["exists"]["observed"])
        self.assertFalse(missing["scan_truncated"]["observed"])
        for metric in ("symlink_present", "permission_finding", "file_count", "aggregate_bytes"):
            self.assertIsNone(missing[metric]["observed"])

        truncated_observations = observations("truncated")
        self.assertTrue(truncated_observations["scan_truncated"]["observed"])
        self.assertTrue(truncated_observations["exists"]["observed"])
        for metric in ("symlink_present", "permission_finding", "file_count", "aggregate_bytes"):
            self.assertIsNone(truncated_observations[metric]["observed"])

        permission_observations = observations("permission")
        self.assertTrue(permission_observations["permission_finding"]["observed"])
        self.assertIsNone(permission_observations["symlink_present"]["observed"])
        self.assertIsNone(permission_observations["file_count"]["observed"])
        self.assertIsNone(permission_observations["aggregate_bytes"]["observed"])

        symlink_observations = observations("symlink-root")
        self.assertTrue(symlink_observations["symlink_present"]["observed"])
        self.assertIsNone(symlink_observations["permission_finding"]["observed"])
        self.assertIsNone(symlink_observations["file_count"]["observed"])
        self.assertIsNone(symlink_observations["aggregate_bytes"]["observed"])

    def test_unreadable_snapshot_metrics_are_not_evaluable(self) -> None:
        root = self.workspace / "unreadable"
        (root / "child").mkdir(parents=True)
        spec = self._store(
            "unreadable", "unreadable", migration_triggers=[{
                "id": "unreadable-files", "metric": "file_count", "operator": ">=",
                "threshold": 1, "rationale": "Review unreadable metadata.",
            }],
        )
        self._registry([spec])
        real_open = os.open

        def deny_child(name, flags, mode=0o777, *, dir_fd=None):
            if name == "child" and dir_fd is not None:
                raise OSError(errno.EACCES, "injected")
            return real_open(name, flags, mode, dir_fd=dir_fd)

        with patch("os.open", side_effect=deny_child):
            observation = audit_registry(self.registry_path, self.workspace)["stores"][0][
                "migration_trigger_observations"
            ][0]
        self.assertIsNone(observation["observed"])
        self.assertEqual(observation["status"], "not_evaluable_from_metadata")

    def test_planner_manual_review_precedes_role_fallthrough(self) -> None:
        report = {
            "stores": [
                {
                    "store_id": "planned-cache", "location_scope": "workspace",
                    "status": "planned", "retention_class": "rebuildable_cache",
                    "classifications": {"authority": "no", "evidence": "no", "cache": "yes"},
                    "scan_truncated": False, "symlink_findings": {"present": False},
                    "permission_findings": [], "exists": True,
                    "migration_trigger_observations": [],
                },
                {
                    "store_id": "manual-evidence", "location_scope": "workspace",
                    "status": "current", "retention_class": "manual_review",
                    "classifications": {"authority": "no", "evidence": "yes", "cache": "no"},
                    "scan_truncated": False, "symlink_findings": {"present": False},
                    "permission_findings": [], "exists": True,
                    "migration_trigger_observations": [],
                },
            ]
        }
        actions = {item["store_id"]: item for item in plan_retention(report)["actions"]}
        self.assertEqual(actions["planned-cache"]["action"], "manual-review")
        self.assertEqual(actions["manual-evidence"]["action"], "manual-review")

    def test_retained_snapshot_survives_parent_retarget_for_scan_and_report_fails_closed(self) -> None:
        parent = self.workspace / "race-parent"
        original = parent / "workspace"
        store_root = original / "store"
        store_root.mkdir(parents=True)
        (store_root / "payload").write_bytes(b"original")
        registry_path = original / "registry.json"
        registry_path.write_text(json.dumps({
            "schema_version": 1,
            "kind": "storage_governance_registry",
            "stores": [self._store("race", "store")],
        }), encoding="utf-8")
        snapshot = open_registry_snapshot(registry_path, original)
        self.addCleanup(snapshot.close)
        detached = self.workspace / "detached-parent"
        parent.rename(detached)
        replacement = parent / "workspace"
        replacement.mkdir(parents=True)
        (replacement / "store").mkdir()
        (replacement / "store" / "payload").write_bytes(b"replacement payload is longer")

        store = audit_snapshot(snapshot)["stores"][0]
        self.assertEqual(store["aggregate_bytes"], len(b"original"))
        with self.assertRaises(RegistryError):
            write_report({"safe": True}, original, snapshot=snapshot)
        self.assertFalse((replacement / ".job-runtime").exists())

    def test_cleanup_faults_preserve_primary_error_and_close_all_fds(self) -> None:
        baseline = len(os.listdir("/dev/fd"))
        real_close = os.close
        dump_started = False
        close_faulted = False

        def failing_dump(*_args, **_kwargs):
            nonlocal dump_started
            dump_started = True
            raise ValueError("primary serialization failure")

        def close_then_fault(descriptor):
            nonlocal close_faulted
            real_close(descriptor)
            if dump_started and not close_faulted:
                close_faulted = True
                raise OSError(errno.EIO, "injected close failure")

        with (
            patch.object(audit_module.json, "dump", side_effect=failing_dump),
            patch.object(audit_module.os, "close", side_effect=close_then_fault),
            patch.object(audit_module.os, "unlink", side_effect=OSError(errno.EIO, "unlink failure")),
        ):
            with self.assertRaisesRegex(ValueError, "primary serialization failure"):
                write_report({"unsafe": object()}, self.workspace)
        self.assertEqual(len(os.listdir("/dev/fd")), baseline)


    def test_cli_reuses_one_snapshot_for_audit_and_publication(self) -> None:
        root = self.workspace / "cli-store"
        root.mkdir()
        (root / "payload").write_bytes(b"x")
        self._registry([self._store("cli-store", "cli-store")])
        real_open_snapshot = audit_module.open_registry_snapshot
        real_write_report = audit_module.write_report
        captured = {}

        def capture_open(*args, **kwargs):
            snapshot = real_open_snapshot(*args, **kwargs)
            captured["snapshot"] = snapshot
            captured["identity"] = snapshot.workspace_identity
            return snapshot

        def capture_write(report, workspace, **kwargs):
            snapshot = kwargs.get("snapshot")
            self.assertIs(snapshot, captured["snapshot"])
            self.assertEqual(snapshot.workspace_identity, captured["identity"])
            return real_write_report(report, workspace, **kwargs)

        with (
            patch.object(audit_module, "open_registry_snapshot", side_effect=capture_open),
            patch.object(audit_module, "write_report", side_effect=capture_write),
        ):
            self.assertEqual(main([
                "--registry", os.fspath(self.registry_path),
                "--workspace", os.fspath(self.workspace),
                "--output-name", "cli.json",
            ]), 0)
        self.assertTrue(captured["snapshot"].closed)
        self.assertTrue(
            (self.workspace / ".job-runtime" / "storage-governance" / "cli.json").is_file()
        )


if __name__ == "__main__":
    unittest.main()
