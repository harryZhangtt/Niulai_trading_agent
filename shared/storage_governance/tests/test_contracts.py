import ast
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from shared.storage_governance import (
    RegistryError, load_registry, open_registry_snapshot, validate_registry,
)
from shared.storage_governance import contracts


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "shared/storage_governance/registry.json"
MARKET_DATA_MANAGER = ROOT / "shared/market_data_mcp/manage.py"
REVIEW_METRICS = {"missing", "permission_finding", "symlink_present", "scan_truncated"}


def trigger(trigger_id="missing-review", metric="missing", operator="==", threshold=True,
            rationale="Review missing current storage."):
    return {"id": trigger_id, "metric": metric, "operator": operator,
            "threshold": threshold, "rationale": rationale}


def store(store_id="alpha", root="runtime/alpha", **updates):
    value = {
        "id": store_id,
        "root": root,
        "location_scope": "workspace",
        "status": "current",
        "roles": ["evidence"],
        "sensitivity": "internal",
        "owner": "alpha-owner",
        "format": "json",
        "writer_model": "single_writer",
        "durability": "local_durable",
        "backup_unit": "file",
        "retention_class": "evidence_record",
        "generated_file_mode": None,
        "derived_from": [],
        "migration_triggers": ["Schema or owner changes."],
    }
    value.update(updates)
    return value


def registry(*stores):
    return {"schema_version": 1, "kind": "storage_governance_registry",
            "stores": list(stores) or [store()]}


class RegistryContractTests(unittest.TestCase):
    def assert_code(self, code, value):
        with self.assertRaisesRegex(RegistryError, f"^{code}$"):
            validate_registry(value)

    def test_tracked_registry_loads_with_factual_owner_boundaries(self):
        value = load_registry(REGISTRY, ROOT)
        by_id = {item["id"]: item for item in value["stores"]}
        self.assertEqual({
            "scheduler-ledger", "delivery-outbox", "evaluation-definitions",
            "evaluation-evidence", "knowledge-corpus", "agent-memory",
            "investment-alerts-input", "investment-alert-runtime",
            "investment-daily-prices", "investment-research-evidence", "factor-registry",
            "job-runtime-credentials", "market-data-credentials",
            "market-data-schwab-credentials", "ui-artifacts", "ui-runtime-cache",
        }, set(by_id))
        self.assertEqual(".job-runtime/engine/schedule.sqlite",
                         by_id["scheduler-ledger"]["root"])
        self.assertEqual("sqlite", by_id["scheduler-ledger"]["format"])
        self.assertEqual("transactional_multi_writer",
                         by_id["scheduler-ledger"]["writer_model"])
        self.assertEqual(".niulai-state/daily-inputs/current/alerts.json",
                         by_id["investment-alerts-input"]["root"])
        self.assertEqual(["authority", "reference"],
                         by_id["investment-alerts-input"]["roles"])
        self.assertIn("rule or configuration",
                      by_id["investment-alerts-input"]["migration_triggers"][0])
        self.assertEqual(".niulai-state/daily-inputs/current/alerts.sqlite",
                         by_id["investment-alert-runtime"]["root"])
        self.assertEqual(["authority", "evidence"],
                         by_id["investment-alert-runtime"]["roles"])
        self.assertEqual("investment-alert-runtime",
                         by_id["investment-alert-runtime"]["owner"])
        self.assertEqual("sqlite", by_id["investment-alert-runtime"]["format"])
        self.assertEqual("transactional_multi_writer",
                         by_id["investment-alert-runtime"]["writer_model"])
        self.assertEqual("database", by_id["investment-alert-runtime"]["backup_unit"])
        self.assertNotEqual(by_id["investment-alerts-input"]["owner"],
                            by_id["investment-alert-runtime"]["owner"])
        self.assertEqual(".niulai-state/databases/daily-prices.sqlite",
                         by_id["investment-daily-prices"]["root"])
        self.assertEqual(".niulai-state/reports/investment-research",
                         by_id["investment-research-evidence"]["root"])
        self.assertEqual("tuning/evals", by_id["evaluation-definitions"]["root"])
        self.assertEqual(["evidence", "reference"],
                         by_id["evaluation-definitions"]["roles"])
        self.assertEqual(".job-runtime/evaluations",
                         by_id["evaluation-evidence"]["root"])
        self.assertEqual(["evidence"], by_id["evaluation-evidence"]["roles"])
        self.assertEqual("planned", by_id["factor-registry"]["status"])
        self.assertEqual(["evidence", "reference"], by_id["factor-registry"]["roles"])
        self.assertNotIn("authority", by_id["factor-registry"]["roles"])
        self.assertEqual("ui/artifacts", by_id["ui-artifacts"]["root"])
        self.assertEqual("ui/runtime", by_id["ui-runtime-cache"]["root"])
        self.assertEqual("unverified", by_id["ui-runtime-cache"]["status"])
        self.assertEqual(["evidence", "cache", "projection"],
                         by_id["ui-runtime-cache"]["roles"])
        self.assertEqual("manual_review", by_id["ui-runtime-cache"]["retention_class"])
        self.assertNotEqual("rebuildable_cache",
                            by_id["ui-runtime-cache"]["retention_class"])
        quarantined = {
            "evaluation-evidence", "investment-research-evidence", "ui-artifacts",
        }
        permission_policy = (
            "Historical permission normalization requires an owner-specific reviewed "
            "migration, backup, and rollback."
        )
        for store_id in quarantined:
            with self.subTest(store_id=store_id):
                item = by_id[store_id]
                self.assertEqual("unverified", item["status"])
                self.assertEqual("manual_review", item["retention_class"])
                self.assertEqual("0600", item["generated_file_mode"])
                self.assertIn(permission_policy, item["migration_triggers"][0])
        workspace = [item for item in value["stores"]
                     if item["location_scope"] == "workspace"]
        self.assertEqual(
            {"current": 10, "planned": 1, "unverified": 4},
            {status: sum(item["status"] == status for item in workspace)
             for status in {"current", "planned", "unverified"}},
        )
        roots = {item["root"] for item in value["stores"]}
        self.assertNotIn(".job-runtime/r8-runs", roots)
        self.assertNotIn(".niulai-state/databases/research.sqlite", roots)
        self.assertNotIn("tuning/runtime", roots)
        authority_roots = [item["root"] for item in value["stores"]
                           if "authority" in item["roles"]]
        self.assertEqual(len(authority_roots), len(set(authority_roots)))
        self.assertEqual("external", by_id["agent-memory"]["location_scope"])
        self.assertEqual("unverified", by_id["agent-memory"]["status"])
        self.assertNotIn("authority", by_id["agent-memory"]["roles"])
        self.assertNotEqual(0o600, stat.S_IMODE(REGISTRY.stat().st_mode))

    def test_workspace_stores_have_structured_review_triggers(self):
        value = load_registry(REGISTRY, ROOT)
        workspace = [item for item in value["stores"]
                     if item["location_scope"] == "workspace"]
        current = [item for item in workspace if item["status"] == "current"]
        self.assertEqual(10, len(current))
        for item in workspace:
            structured = [entry for entry in item["migration_triggers"]
                          if isinstance(entry, dict)]
            self.assertEqual(REVIEW_METRICS, {entry["metric"] for entry in structured}, item["id"])
            self.assertTrue(all(entry["operator"] == "==" and entry["threshold"] is True
                                and entry["rationale"] for entry in structured), item["id"])

    def test_exact_top_level_store_and_trigger_schemas(self):
        value = registry()
        value["extra"] = True
        self.assert_code("STORAGE_REGISTRY_SCHEMA", value)
        value = registry()
        value["stores"][0]["extra"] = True
        self.assert_code("STORAGE_REGISTRY_STORE_SCHEMA", value)
        value = registry()
        del value["stores"][0]["owner"]
        self.assert_code("STORAGE_REGISTRY_STORE_SCHEMA", value)
        bad_trigger = trigger()
        bad_trigger["extra"] = True
        self.assert_code("STORAGE_REGISTRY_MIGRATION_TRIGGER_SCHEMA",
                         registry(store(migration_triggers=[bad_trigger])))

    def test_structured_metadata_triggers_accept_safe_boolean_and_integer_forms(self):
        value = store(migration_triggers=[
            "Policy changes.",
            trigger(),
            trigger("files-review", "file_count", ">=", 100, "Review unusually large stores."),
            trigger("bytes-review", "aggregate_bytes", ">", 1024,
                    "Review storage growth beyond the declared budget."),
        ])
        validate_registry(registry(value))

    def test_structured_triggers_reject_unsafe_metrics_operators_and_thresholds(self):
        cases = [
            (trigger(metric="content_hash"), "STORAGE_REGISTRY_MIGRATION_TRIGGER_METRIC_INVALID"),
            (trigger(operator="at_least"), "STORAGE_REGISTRY_MIGRATION_TRIGGER_OPERATOR_INVALID"),
            (trigger(operator=">"), "STORAGE_REGISTRY_MIGRATION_TRIGGER_OPERATOR_INVALID"),
            (trigger(threshold=1), "STORAGE_REGISTRY_MIGRATION_TRIGGER_THRESHOLD_INVALID"),
            (trigger(metric="file_count", operator=">=", threshold=True),
             "STORAGE_REGISTRY_MIGRATION_TRIGGER_THRESHOLD_INVALID"),
            (trigger(metric="file_count", operator=">=", threshold=-1),
             "STORAGE_REGISTRY_MIGRATION_TRIGGER_THRESHOLD_INVALID"),
            (trigger(metric="aggregate_bytes", operator=">", threshold=2**63),
             "STORAGE_REGISTRY_MIGRATION_TRIGGER_THRESHOLD_INVALID"),
        ]
        for bad, code in cases:
            with self.subTest(code=code, trigger=bad):
                self.assert_code(code, registry(store(migration_triggers=[bad])))

    def test_duplicate_trigger_ids_are_rejected(self):
        self.assert_code(
            "STORAGE_REGISTRY_MIGRATION_TRIGGERS_INVALID",
            registry(store(migration_triggers=[trigger(), trigger(metric="exists")])),
        )

    def test_roots_are_relative_posix_and_normalized(self):
        for bad in ("/tmp/data", "~/data", "../data", "data/../other", "data//other",
                    "data/./other", "data\\other", "C:/data"):
            with self.subTest(root=bad):
                with self.assertRaises(RegistryError):
                    validate_registry(registry(store(root=bad)))

    def test_status_roles_and_private_output_mode_are_strict(self):
        self.assert_code("STORAGE_REGISTRY_STATUS_INVALID", registry(store(status="active")))
        self.assert_code("STORAGE_REGISTRY_STATUS_INVALID", registry(store(status=[])))
        self.assert_code("STORAGE_REGISTRY_DURABILITY_INVALID", registry(store(durability={})))
        self.assert_code("STORAGE_REGISTRY_ROLES_INVALID",
                         registry(store(roles=["projection", "evidence"])))
        self.assert_code("STORAGE_REGISTRY_AUTHORITY_ROLE_CONFLICT",
                         registry(store(roles=["authority", "cache"])))
        self.assert_code("STORAGE_REGISTRY_PLANNED_AUTHORITY_FORBIDDEN",
                         registry(store(status="planned", roles=["authority"])))
        self.assert_code("STORAGE_REGISTRY_PRIVATE_MODE_REQUIRED",
                         registry(store(sensitivity="confidential")))
        self.assert_code("STORAGE_REGISTRY_FILE_MODE_INVALID",
                         registry(store(generated_file_mode="0644")))
        self.assert_code("STORAGE_REGISTRY_FILE_MODE_INVALID",
                         registry(store(writer_model="read_only", generated_file_mode="0600")))

    def test_credential_store_is_metadata_only_and_private(self):
        valid = store(roles=["credential"], sensitivity="restricted",
                      retention_class="credential_lifecycle", generated_file_mode="0600")
        validate_registry(registry(valid))
        self.assert_code("STORAGE_REGISTRY_CREDENTIAL_STORE_INVALID",
                         registry(store(roles=["credential"], sensitivity="restricted",
                                        generated_file_mode="0600")))
        materials = (
            "password=synthetic-but-forbidden",
            "secret=synthetic-but-forbidden",
            "AKIA" + "A" * 16,
            "ASIA" + "B" * 16,
            "github_pat_" + "c" * 24,
            "glpat-" + "d" * 20,
            "npm_" + "e" * 36,
            "ghp_" + "f" * 20,
            "gho_" + "g" * 24,
            "AIza" + "h" * 35,
            "xapp-" + "1" * 24,
        )
        for material in materials:
            with self.subTest(material=material[:12]):
                self.assert_code("STORAGE_REGISTRY_CREDENTIAL_MATERIAL_FORBIDDEN",
                                 registry(store(migration_triggers=[material])))
        for private_path in (
            "Move to /Users/example/private.",
            "location=/Users/example/private.",
            "location:/home/example/private.",
            "location(C:\\Users\\example\\private)",
        ):
            with self.subTest(private_path=private_path):
                self.assert_code("STORAGE_REGISTRY_PRIVATE_PATH_FORBIDDEN",
                                 registry(store(migration_triggers=[private_path])))

    def test_cross_references_exist_and_are_acyclic(self):
        self.assert_code("STORAGE_REGISTRY_DERIVED_FROM_UNKNOWN",
                         registry(store(derived_from=["missing"])))
        left = store("left", "runtime/left", derived_from=["right"])
        right = store("right", "runtime/right", derived_from=["left"])
        self.assert_code("STORAGE_REGISTRY_DERIVATION_CYCLE", registry(left, right))

    def test_authority_cannot_claim_another_owners_domain(self):
        source = store("source", "domain/source", owner="source-owner")
        authority = store("authority", "domain/authority", owner="other-owner",
                          roles=["authority"], derived_from=["source"])
        self.assert_code("STORAGE_REGISTRY_CROSS_OWNER_AUTHORITY_FORBIDDEN",
                         registry(source, authority))
        nested = store("nested", "domain/source/nested", owner="other-owner")
        authority = store("authority", "domain/source", owner="source-owner",
                          roles=["authority"])
        self.assert_code("STORAGE_REGISTRY_CROSS_OWNER_AUTHORITY_FORBIDDEN",
                         registry(authority, nested))

        ancestor = store("ancestor", "lineage/ancestor", owner="original-owner")
        laundering = store("laundering", "lineage/laundering", owner="authority-owner",
                           derived_from=["ancestor"])
        authority = store("authority", "lineage/authority", owner="authority-owner",
                          roles=["authority"], derived_from=["laundering"])
        self.assert_code("STORAGE_REGISTRY_CROSS_OWNER_AUTHORITY_FORBIDDEN",
                         registry(ancestor, laundering, authority))

    def test_external_store_must_remain_unverified_and_non_authoritative(self):
        external = store(location_scope="external", status="unverified",
                         writer_model="external_managed", durability="external_unverified",
                         backup_unit="external_store")
        validate_registry(registry(external))
        bad = copy.deepcopy(external)
        bad["status"] = "current"
        self.assert_code("STORAGE_REGISTRY_EXTERNAL_STORE_INVALID", registry(bad))
        bad = copy.deepcopy(external)
        bad["roles"] = ["authority"]
        self.assert_code("STORAGE_REGISTRY_UNVERIFIED_AUTHORITY_FORBIDDEN", registry(bad))

    def test_market_data_credential_roots_track_manager_constant_and_usage(self):
        value = load_registry(REGISTRY, ROOT)
        registered = {item["root"] for item in value["stores"]
                      if item["owner"] == "market-data-adapter"
                      and item["roles"] == ["credential"]}

        tree = ast.parse(MARKET_DATA_MANAGER.read_text(encoding="utf-8"))
        state_directory = None
        credential_suffixes = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "STATE"
                            for target in node.targets)
                    and isinstance(node.value, ast.BinOp)
                    and isinstance(node.value.op, ast.Div)
                    and isinstance(node.value.right, ast.Constant)
                    and isinstance(node.value.right.value, str)):
                state_directory = node.value.right.value
            if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                    and isinstance(node.left, ast.Name) and node.left.id == "STATE"
                    and isinstance(node.right, ast.Constant)
                    and isinstance(node.right.value, str)
                    and node.right.value.startswith("credentials")):
                credential_suffixes.add(node.right.value)

        self.assertEqual(".market-data-mcp", state_directory)
        self.assertEqual({"credentials", "credentials.json"}, credential_suffixes)
        self.assertEqual({f"{state_directory}/{suffix}"
                          for suffix in credential_suffixes}, registered)

    def test_load_rejects_symlink_workspace_and_parent_components(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "shared/storage_governance/tests") as name:
            outer = Path(name)
            real_parent = outer / "real-parent"
            workspace = real_parent / "workspace"
            registry_parent = workspace / "registry-parent"
            registry_parent.mkdir(parents=True)
            path = registry_parent / "registry.json"
            path.write_text(json.dumps(registry()), encoding="utf-8")

            workspace_link = outer / "workspace-link"
            workspace_link.symlink_to(workspace, target_is_directory=True)
            with self.assertRaisesRegex(RegistryError, "STORAGE_REGISTRY_WORKSPACE_INVALID"):
                load_registry("registry-parent/registry.json", workspace_link)

            parent_link = outer / "parent-link"
            parent_link.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(RegistryError, "STORAGE_REGISTRY_WORKSPACE_INVALID"):
                load_registry("registry-parent/registry.json", parent_link / "workspace")

            registry_parent_link = workspace / "registry-parent-link"
            registry_parent_link.symlink_to(registry_parent, target_is_directory=True)
            with self.assertRaisesRegex(RegistryError, "STORAGE_REGISTRY_PATH_INVALID"):
                load_registry("registry-parent-link/registry.json", workspace)

    def test_load_reads_opened_fd_when_registry_path_is_swapped(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "shared/storage_governance/tests") as name:
            workspace = Path(name)
            expected = registry(store("original", "runtime/original"))
            replacement = registry(store("replacement", "runtime/replacement"))
            path = workspace / "registry.json"
            replacement_path = workspace / "replacement.json"
            path.write_text(json.dumps(expected), encoding="utf-8")
            replacement_path.write_text(json.dumps(replacement), encoding="utf-8")
            real_read = os.read
            swapped = False

            def swap_then_read(descriptor, size):
                nonlocal swapped
                if not swapped:
                    swapped = True
                    path.unlink()
                    path.symlink_to(replacement_path)
                return real_read(descriptor, size)

            with patch.object(contracts.os, "read", side_effect=swap_then_read):
                self.assertEqual(expected, load_registry(path, workspace))
            self.assertTrue(path.is_symlink())

    def test_load_bounds_growth_during_descriptor_read(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "shared/storage_governance/tests") as name:
            workspace = Path(name)
            path = workspace / "registry.json"
            path.write_text(json.dumps(registry()), encoding="utf-8")
            real_read = os.read
            grew = False

            def grow_then_read(descriptor, size):
                nonlocal grew
                chunk = real_read(descriptor, size)
                if not grew:
                    grew = True
                    with path.open("ab") as output:
                        output.write(b"x" * (contracts.MAX_REGISTRY_BYTES + 1))
                return chunk

            with patch.object(contracts.os, "read", side_effect=grow_then_read):
                with self.assertRaisesRegex(RegistryError, "STORAGE_REGISTRY_PATH_INVALID"):
                    load_registry(path, workspace)

    def test_load_rejects_duplicate_invalid_outside_and_symlink_paths(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "shared/storage_governance/tests") as name:
            workspace = Path(name)
            duplicate = workspace / "duplicate.json"
            duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "STORAGE_REGISTRY_DUPLICATE_KEY"):
                load_registry(duplicate, workspace)
            invalid = workspace / "invalid.json"
            invalid.write_text('{"schema_version":NaN}', encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "STORAGE_REGISTRY_JSON_INVALID"):
                load_registry(invalid, workspace)
            with self.assertRaisesRegex(RegistryError, "STORAGE_REGISTRY_PATH_INVALID"):
                load_registry(REGISTRY, workspace)
            target = workspace / "target.json"
            target.write_text(json.dumps(registry()), encoding="utf-8")
            link = workspace / "link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(RegistryError, "STORAGE_REGISTRY_PATH_INVALID"):
                load_registry(link, workspace)

    def test_load_accepts_workspace_relative_path_without_mutation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "shared/storage_governance/tests") as name:
            workspace = Path(name)
            expected = registry(store(migration_triggers=[trigger()]))
            path = workspace / "registry.json"
            path.write_text(json.dumps(expected), encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual(expected, load_registry("registry.json", workspace))
            self.assertEqual(before, path.read_bytes())


    def test_retained_snapshot_uses_one_workspace_identity_and_closes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "shared/storage_governance/tests") as name:
            workspace = Path(name)
            expected = registry(store("retained", "runtime/retained"))
            path = workspace / "registry.json"
            path.write_text(json.dumps(expected), encoding="utf-8")
            snapshot = open_registry_snapshot(path, workspace)
            descriptor = snapshot.workspace_fd
            identity = (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)
            self.assertEqual(identity, snapshot.workspace_identity)
            self.assertEqual(expected, snapshot.registry)
            snapshot.verify()
            snapshot.close()
            self.assertTrue(snapshot.closed)
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_load_registry_wraps_and_closes_retained_snapshot(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "shared/storage_governance/tests") as name:
            workspace = Path(name)
            expected = registry(store("wrapped", "runtime/wrapped"))
            path = workspace / "registry.json"
            path.write_text(json.dumps(expected), encoding="utf-8")
            real_open = contracts.open_registry_snapshot
            retained_fd = None

            def capture(*args, **kwargs):
                nonlocal retained_fd
                snapshot = real_open(*args, **kwargs)
                retained_fd = snapshot.workspace_fd
                return snapshot

            with patch.object(contracts, "open_registry_snapshot", side_effect=capture):
                self.assertEqual(expected, load_registry(path, workspace))
            self.assertIsNotNone(retained_fd)
            with self.assertRaises(OSError):
                os.fstat(retained_fd)


    def test_component_open_close_fault_does_not_leak_final_descriptor(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "shared/storage_governance/tests") as name:
            workspace = Path(name)
            baseline = len(os.listdir("/dev/fd"))
            real_close = os.close
            faulted = False

            def close_then_fault(descriptor):
                nonlocal faulted
                real_close(descriptor)
                if not faulted:
                    faulted = True
                    raise OSError("injected close failure")

            with patch.object(contracts.os, "close", side_effect=close_then_fault):
                with self.assertRaisesRegex(RegistryError, "STORAGE_REGISTRY_WORKSPACE_INVALID"):
                    contracts.open_workspace_snapshot(workspace)
            self.assertEqual(len(os.listdir("/dev/fd")), baseline)


if __name__ == "__main__":
    unittest.main()
