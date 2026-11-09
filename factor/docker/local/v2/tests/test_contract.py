import ast
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from factor.docker.local.v2 import validator


ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT.parent
WORKSPACE = Path(__file__).resolve().parents[5]
PLAN = WORKSPACE / "docs/plans/factor-mining-local-docker-installation-v2-20261105.md"


PROCESS_LAUNCH_CALLS = {
    "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell",
    "os.popen", "os.spawnl", "os.spawnle", "os.spawnlp", "os.spawnlpe",
    "os.spawnv", "os.spawnve", "os.spawnvp", "os.spawnvpe", "os.system",
    "subprocess.Popen", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "subprocess.run",
}
FILESYSTEM_MUTATION_CALLS = {
    "os.chmod", "os.chown", "os.link", "os.mkdir", "os.makedirs",
    "os.remove", "os.rename", "os.renames", "os.replace", "os.rmdir",
    "os.symlink", "os.truncate", "os.unlink", "os.utime",
    "shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree",
    "shutil.move", "shutil.rmtree",
}
FILESYSTEM_MUTATION_METHODS = {
    "chmod", "hardlink_to", "link_to", "mkdir", "rename", "replace",
    "rmdir", "symlink_to", "touch", "unlink", "write_bytes", "write_text",
}
CONFIG_MUTATION_CALLS = {"os.putenv", "os.unsetenv"}
NETWORK_CALLS = {
    "asyncio.open_connection", "http.client.HTTPConnection",
    "http.client.HTTPSConnection", "socket.create_connection", "socket.socket",
    "urllib.request.urlopen",
}
NETWORK_METHODS = {
    "connect", "connect_ex", "delete", "patch", "post", "put", "request",
    "send", "sendall", "sendto", "urlopen",
}
WRITE_OPEN_FLAGS = {"os.O_APPEND", "os.O_CREAT", "os.O_RDWR", "os.O_TRUNC",
                    "os.O_WRONLY"}


def unsafe_effects(source):
    tree = ast.parse(source)
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"

    def dotted(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            base = dotted(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Call):
            return dotted(node.func)
        return ""

    def environment_target(node):
        return isinstance(node, ast.Subscript) and dotted(node.value) == "os.environ"

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            tail = name.rsplit(".", 1)[-1]
            if name in PROCESS_LAUNCH_CALLS:
                violations.append(name)
            elif name in FILESYSTEM_MUTATION_CALLS or tail in FILESYSTEM_MUTATION_METHODS:
                violations.append(name)
            elif name in CONFIG_MUTATION_CALLS:
                violations.append(name)
            elif name in NETWORK_CALLS or tail in NETWORK_METHODS:
                violations.append(name)
            elif name in {"open", "builtins.open", "io.open"}:
                mode_node = node.args[1] if len(node.args) > 1 else None
                for keyword in node.keywords:
                    if keyword.arg == "mode":
                        mode_node = keyword.value
                if mode_node is not None:
                    try:
                        mode = ast.literal_eval(mode_node)
                    except (ValueError, TypeError):
                        mode = None
                    if not isinstance(mode, str) or any(flag in mode for flag in "wax+"):
                        violations.append(name)
            elif name == "os.open" and len(node.args) > 1:
                flags = {dotted(item) for item in ast.walk(node.args[1])}
                if flags & WRITE_OPEN_FLAGS:
                    violations.append(name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(environment_target(target) for target in targets):
                violations.append("os.environ-assignment")
        elif isinstance(node, ast.Delete):
            if any(environment_target(target) for target in node.targets):
                violations.append("os.environ-delete")
    return violations

def leaf_mutations(value):
    if isinstance(value, dict):
        for key, item in value.items():
            for changed_item in leaf_mutations(item):
                changed = copy.deepcopy(value)
                changed[key] = changed_item
                yield changed
        if not value:
            yield {"unexpected": True}
    elif isinstance(value, list):
        if value:
            for index, item in enumerate(value):
                for changed_item in leaf_mutations(item):
                    changed = copy.deepcopy(value)
                    changed[index] = changed_item
                    yield changed
        else:
            yield ["unexpected"]
    elif isinstance(value, bool):
        yield not value
    elif value is None:
        yield "unexpected"
    elif isinstance(value, int):
        yield value + 1
    elif isinstance(value, str):
        yield value + "-changed"
    else:
        raise AssertionError(type(value))


class V2InstallationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = validator.load_json(ROOT / "installation-receipt.json")
        cls.profile = validator.load_json(ROOT / "runtime-profile-v2.json")

    def test_bundle_is_valid_selected_disabled_and_hash_bound(self):
        hashes = validator.validate_bundle()
        self.assertEqual(hashes, {
            "installation-receipt.json": validator.EXPECTED_RECEIPT_SHA256,
            "runtime-profile-v2.json": validator.digest(self.profile),
            "frozen-v1-tree": validator.EXPECTED_V1_TREE_SHA256,
        })
        self.assertEqual(self.profile["status"], "selected-disabled")
        self.assertFalse(self.profile["runnable"])
        self.assertFalse(self.profile["apply_allowed"])

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_values(self):
        with self.assertRaisesRegex(validator.V2ContractError, "DUPLICATE_KEY"):
            validator.load_json(ROOT / "fixtures/invalid/duplicate-key.json")
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token), self.assertRaisesRegex(
                    validator.V2ContractError, "NONFINITE"):
                validator.loads_strict('{"value":' + token + '}')

    def test_json_reads_are_bounded_regular_and_recursion_safe(self):
        with tempfile.TemporaryDirectory(dir=WORKSPACE) as temporary:
            temporary = Path(temporary)
            oversized = temporary / "oversized.json"
            oversized.write_bytes(b" " * (validator.MAX_BYTES + 1))
            with self.assertRaisesRegex(validator.V2ContractError, "JSON_SIZE"):
                validator.load_json(oversized)
            fifo = temporary / "input.fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(validator.V2ContractError, "JSON_SIZE"):
                validator.load_json(fifo)
        nested = "[" * 2000 + "0" + "]" * 2000
        with self.assertRaisesRegex(validator.V2ContractError, "JSON_INVALID"):
            validator.loads_strict(nested)
        value = 0
        for _ in range(2000):
            value = [value]
        with self.assertRaisesRegex(validator.V2ContractError, "JSON_INVALID"):
            validator.canonical(value)

    def test_closed_exact_schemas_reject_unknown_fields_and_every_leaf_mutation(self):
        cases = [
            (self.receipt, "installation-receipt-v2.schema.json"),
            (self.profile, "runtime-profile-v2.schema.json"),
        ]
        mutation_count = 0
        for instance, schema_name in cases:
            schema = validator.load_json(ROOT / schema_name)
            body = {key: value for key, value in schema.items()
                    if key not in {"$schema", "$id"}}
            validator.validate_exact_schema(instance, body)
            stack = [body]
            while stack:
                node = stack.pop()
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                    stack.extend(node["properties"].values())
            changed = copy.deepcopy(instance)
            changed["unexpected"] = True
            with self.assertRaises(validator.V2ContractError):
                validator.validate_exact_schema(changed, body)
            for changed in leaf_mutations(instance):
                mutation_count += 1
                with self.assertRaises(validator.V2ContractError):
                    validator.validate_exact_schema(changed, body)
        self.assertGreaterEqual(mutation_count, 140)

    def test_installed_versions_paths_hashes_and_build_metadata_are_exact(self):
        validator.validate_receipt(self.receipt)
        for name, expected in validator.EXPECTED_TOOLS.items():
            tool = self.receipt["tools"][name]
            self.assertEqual((tool["version"], tool["executable_path"], tool["sha256"]),
                             expected)
            self.assertEqual(tool["install_state"], "installed-package-observed")
        self.assertTrue(self.receipt["tools"]["colima"]["commit"].startswith("00f6c297"))
        self.assertEqual(self.receipt["tools"]["docker"]["build"], "5457199aa5")
        self.assertEqual(self.receipt["tools"]["lima"]["dependency_role"],
                         "colima-dependency")

    def test_package_observation_does_not_claim_runtime_history(self):
        self.assertEqual(self.receipt["installation_state"],
                         "homebrew-packages-observed")
        observation = self.receipt["runtime_observation"]
        self.assertEqual(observation["colima_service_status"], "none")
        self.assertEqual(observation["matching_processes"], [])
        self.assertFalse(observation["daemon_queried"])
        self.assertEqual(observation["daemon_state"], "unqueried-unknown")
        self.assertFalse(observation["docker_context_inspected"])
        self.assertEqual(observation["docker_context_state"],
                         "uninspected-unknown")
        self.assertFalse(observation["vm_inspected"])
        self.assertEqual(observation["vm_state"], "uninspected-unknown")
        self.assertFalse(observation["runtime_history_inferred"])
        self.assertEqual(observation["service_or_process_observation_scope"],
                         "point-in-time-only")
        host = self.profile["host_state"]
        self.assertIsNone(host["docker_context"])
        self.assertEqual(host["docker_context_state"], "uninspected-unknown")
        self.assertIsNone(host["vm_identity"])
        self.assertEqual(host["vm_identity_state"], "uninspected-unknown")
        self.assertFalse(host["change_global_current_docker_context"])
        self.assertEqual(host["colima_config"], {"autoActivate": False})

    def test_docker_home_was_not_created_or_mutated_by_probes(self):
        home = self.receipt["runtime_observation"]["home_docker_config"]
        self.assertEqual(home["state_before"], "absent")
        self.assertEqual(home["state_after"], "absent")
        self.assertEqual(home["entry_count"], 0)
        self.assertTrue(home["contents_and_metadata_unchanged"])
        self.assertEqual(home["before_aggregate_sha256"],
                         home["after_aggregate_sha256"])

    def test_only_exact_v1_installation_blockers_are_resolved(self):
        self.assertEqual(self.profile["resolved_blockers"], validator.RESOLVED_BLOCKERS)
        self.assertEqual(self.profile["blockers"], validator.RETAINED_BLOCKERS)
        for blocker in (
            "docker-context-unverified", "vm-identity-unverified",
            "controller-image-digest-unresolved", "release-digest-unresolved",
            "host-headroom-unmeasured", "disposable-lifecycle-unrun",
            "pressure-behavior-unverified", "future-io-conformance-unverified",
            "internal-network-identity-unresolved", "dual-network-conformance-unverified",
            "stable-lifecycle-conformance-unverified", "oci-architecture-unresolved",
            "image-contract-conformance-unverified",
            "official-source-live-verification-receipts-unavailable",
            "runtime-acceptance-unrun",
        ):
            self.assertIn(blocker, self.profile["blockers"])

    def test_workspace_state_and_future_context_are_explicit_but_null(self):
        host = self.profile["host_state"]
        self.assertEqual(host["colima_environment"], {
            "COLIMA_HOME": "$WORKSPACE/factor/runtime/local/colima",
            "COLIMA_PROFILE": "factor-mining",
        })
        self.assertEqual(host["expected_future_docker_context"], "colima-factor-mining")
        self.assertIsNone(host["docker_context"])
        self.assertEqual(host["docker_context_state"], "uninspected-unknown")
        self.assertIsNone(host["vm_identity"])
        self.assertEqual(host["vm_identity_state"], "uninspected-unknown")

    def test_frozen_v1_tree_and_profile_are_unchanged(self):
        count, tree_hash = validator.v1_tree()
        self.assertEqual(count, len(validator.V1_MANIFEST))
        self.assertEqual(tree_hash, validator.EXPECTED_V1_TREE_SHA256)
        self.assertEqual(self.profile["frozen_v1"]["tree_sha256"], tree_hash)
        self.assertEqual(self.profile["frozen_v1"]["contract_profile_sha256"],
                         validator.EXPECTED_V1_PROFILE_SHA256)

    def test_v1_manifest_rejects_behavior_files_and_ignores_only_incidentals(self):
        with tempfile.TemporaryDirectory(dir=WORKSPACE) as temporary:
            temporary = Path(temporary)
            for relative in validator.V1_MANIFEST:
                path = temporary / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(relative.encode("utf-8"))
            baseline = validator.v1_tree(temporary)
            for relative in (".DS_Store", "editor.swp",
                             "__pycache__/validator.cpython.pyc", "v3/launcher.py"):
                path = temporary / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"incidental-or-versioned")
            self.assertEqual(validator.v1_tree(temporary), baseline)
            for relative in ("launcher.py", "compose.yaml", "docker-compose.yml"):
                path = temporary / relative
                path.write_text("behavior-bearing")
                with self.assertRaisesRegex(validator.V2ContractError,
                                            "V1_TREE_EXTRA_FILE"):
                    validator.v1_tree(temporary)
                path.unlink()
            (temporary / validator.V1_MANIFEST[0]).unlink()
            with self.assertRaisesRegex(validator.V2ContractError,
                                        "V1_TREE_UNAVAILABLE"):
                validator.v1_tree(temporary)

    def test_bundle_takes_one_v1_snapshot(self):
        with mock.patch.object(validator, "_v1_snapshot",
                               wraps=validator._v1_snapshot) as snapshot:
            validator.validate_bundle()
        self.assertEqual(snapshot.call_count, 1)

    def test_no_apply_start_server_context_or_package_mutation_commands(self):
        dangerous = (
            "colima" + " start", "docker" + " context create",
            "docker" + " context use", "docker" + " run",
            "docker" + " compose up", "brew" + " install",
            "brew" + " upgrade", "brew" + " uninstall",
        )
        texts = []
        for path in ROOT.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                texts.append(path.read_text(errors="strict"))
        texts.append(PLAN.read_text())
        combined = "\n".join(texts).lower()
        for command in dangerous:
            with self.subTest(command=command):
                self.assertNotIn(command, combined)
        production_python = [
            path for path in V1_ROOT.rglob("*.py")
            if "tests" not in path.relative_to(V1_ROOT).parts
            and "__pycache__" not in path.parts
        ]
        violations = {}
        for path in production_python:
            calls = unsafe_effects(path.read_text())
            if calls:
                violations[str(path.relative_to(V1_ROOT))] = calls
        self.assertEqual(violations, {})
        purposes = {item["purpose"] for item in self.receipt["commands"]}
        self.assertNotIn("daemon-query", purposes)
        self.assertNotIn("context-query", purposes)

    def test_ast_gate_detects_list_alias_and_shell_launches(self):
        source = """
import subprocess as sp
from os import system as shell
sp.run(["docker", "run", "image"])
shell("colima\tstart")
"""
        self.assertEqual(unsafe_effects(source),
                         ["subprocess.run", "os.system"])

    def test_ast_gate_detects_filesystem_config_and_network_bypasses(self):
        source = """
import os
import socket as net
from builtins import open as writer
from pathlib import Path as P
from urllib.request import urlopen as fetch
writer("config.json", "w")
P("config.json").write_text("changed")
os.open("config.json", os.O_WRONLY | os.O_CREAT)
os.environ["DOCKER_CONTEXT"] = "unsafe"
net.create_connection(("example.invalid", 443))
fetch("https://example.invalid")
"""
        self.assertEqual(set(unsafe_effects(source)), {
            "builtins.open", "pathlib.Path.write_text", "os.open",
            "os.environ-assignment", "socket.create_connection",
            "urllib.request.urlopen",
        })

    def test_plan_preserves_nonclaims_and_records_setup_integration(self):
        plan = PLAN.read_text().lower()
        for phrase in (
            "runtime activation history",
            "does not establish production readiness",
            "docs/local-setup.md",
            "docs/deployment/setup-inventory.json",
            "does not authorize package mutation",
        ):
            self.assertIn(phrase.lower(), plan)

    def test_cli_reports_hashes_without_runtime_action(self):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "factor.docker.local.v2.validator"],
            cwd=WORKSPACE, check=False, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["status"], "selected-disabled")
        self.assertFalse(payload["runnable"])
        self.assertFalse(payload["apply_allowed"])


if __name__ == "__main__":
    unittest.main()
