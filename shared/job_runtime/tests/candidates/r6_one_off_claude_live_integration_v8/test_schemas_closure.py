from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import itertools
import os
import json
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
PKG = ROOT / "shared/job_runtime/candidates/r6_one_off_claude_live_integration_v8"
TESTS = ROOT / "shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v8"
SCHEMAS = PKG / "schemas"
ARCH = ROOT / "tuning/architecture/r6_one_off_claude_live_integration_v8"
REVIEW = ROOT / "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-claude-live-integration-v7-independent-review-open-fable-20261112-8e9a8076.json"

from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v8 import authority as authmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v8 import runner
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v8.contracts import (
    ContractError, blank_seal, validate_seal,
)
from shared.job_runtime.tests.candidates.r6_one_off_claude_live_integration_v8.test_integration import (
    _unknown_pair, _valid_pass,
)


def _module_path(name: str) -> pathlib.Path | None:
    base = ROOT.joinpath(*name.split("."))
    file = base.with_suffix(".py")
    if file.is_file(): return file
    init = base / "__init__.py"
    return init if init.is_file() else None


def _module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__": parts.pop()
    return ".".join(parts)


def _recursive_local_imports(seeds: set[pathlib.Path]) -> set[pathlib.Path]:
    found: set[pathlib.Path] = set(); queue = list(seeds)
    while queue:
        path = queue.pop()
        if path in found: continue
        found.add(path)
        module = _module_name(path)
        package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = package.split(".") if package else []
                    keep = len(parts) - (node.level - 1)
                    prefix = parts[:max(0, keep)]
                    if node.module: prefix.extend(node.module.split("."))
                    base = ".".join(prefix)
                else:
                    base = node.module or ""
                if base: names.append(base)
                for alias in node.names:
                    candidate = base + "." + alias.name if base else alias.name
                    if _module_path(candidate): names.append(candidate)
            for name in names:
                resolved = _module_path(name)
                if resolved and resolved not in found: queue.append(resolved)
    return found


def expected_closure() -> set[str]:
    seeds = {p for base in (PKG, TESTS) for p in base.rglob("*.py")}
    imported = _recursive_local_imports(seeds)
    artifacts = imported | {p for base in (PKG, TESTS) for p in base.rglob("*") if p.is_file()}
    artifacts |= {ROOT / ref[0] for ref in (
        authmod.REGISTRY_REF, authmod.REGISTRY_REVIEW_REF, authmod.GRANT_REF,
        authmod.GRANT_REVIEW_REF, authmod.SCOPE_REF)}
    artifacts.add(ROOT / authmod.load_pinned().grant["binary_ref"])
    artifacts.add(REVIEW)
    verifier = ARCH / "verify_v8.py"
    if verifier.is_file(): artifacts.add(verifier)
    return {str(path.relative_to(ROOT)) for path in artifacts if "__pycache__" not in path.parts}


class SchemasClosureV8Tests(unittest.TestCase):
    def test_candidate_inert_unregistered_and_no_live_client(self):
        for path in PKG.glob("*.py"):
            text = path.read_text(); tree = ast.parse(text); imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): imports += [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom): imports += [node.module or ""]
            self.assertFalse(any(item.startswith(("requests", "httpx", "anthropic"))
                                 for item in imports), path)
            self.assertNotIn("bytedcli", text.lower())
            self.assertNotIn("sqlite3", imports)
        runtime = ROOT / "shared/job_runtime"
        self.assertFalse(any("r6_one_off_claude_live_integration_v8" in p.read_text()
                             for p in runtime.glob("*.py")))

    def test_v7_open_review_exact_and_history_remains_open(self):
        raw = REVIEW.read_bytes()
        self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                         (10536, "3ebc954c253ae104f97ef5fe52e0fb96ac6d70a0eb273677e022145962dc258a"))
        review = json.loads(raw)
        self.assertEqual(review["verdict"], "OPEN")
        self.assertEqual(len(review["findings"]), 1)
        self.assertEqual(review["findings"][0]["id"], "OPEN-CLAUDE-V7-001")

    def test_draft_2020_12_runtime_parity_and_nested_extras(self):
        from jsonschema import Draft202012Validator
        schemas = {}
        for path in SCHEMAS.glob("*.json"):
            schema = json.loads(path.read_text()); Draft202012Validator.check_schema(schema)
            def walk_schema(value):
                if isinstance(value, dict):
                    if value.get("type") == "object":
                        self.assertIs(value.get("additionalProperties"), False, path)
                    for child in value.values(): walk_schema(child)
                elif isinstance(value, list):
                    for child in value: walk_schema(child)
            walk_schema(schema); schemas[path.name] = Draft202012Validator(schema)

        generation = "f" * 64
        durable_unknown, durable_poison = _unknown_pair(generation)
        passed = _valid_pass(generation)
        stopped = blank_seal()
        with tempfile.TemporaryDirectory() as name:
            projection_root = pathlib.Path(name)
            (projection_root / "public").mkdir()
            (projection_root / runner.FENCE_PENDING_NAME).write_text("{}")
            fd = os.open(projection_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                projection_unknown = runner._recover(
                    types.SimpleNamespace(fd=fd, path=projection_root))
            finally:
                os.close(fd)
        self.assertIsNotNone(projection_unknown)

        sealv = schemas["post-run-seal-v8.schema.json"]
        p0v = schemas["p0-output-v8.schema.json"]
        actual = (passed, durable_unknown, durable_poison, stopped, projection_unknown)
        for value in actual:
            validate_seal(value); sealv.validate(value)
            p0v.validate(runner._p0_output(value))

        self.assertEqual(
            {key: runner._p0_output(projection_unknown)[key] for key in
             ("status", "state_authority", "durability", "cell_id",
              "engine_provider", "engine_readback_digest")},
            {"status": "UNKNOWN", "state_authority": "ABSENT",
             "durability": "NON_DURABLE", "cell_id": None,
             "engine_provider": None, "engine_readback_digest": None})
        for value, state in ((durable_unknown, "UNKNOWN"),
                             (durable_poison, "POISONED")):
            p0 = runner._p0_output(value)
            self.assertEqual((p0["status"], p0["state_authority"], p0["durability"],
                              p0["engine_provider"]),
                             ("UNKNOWN", state, "DURABLE", "claude_host"))
            self.assertTrue(all(p0[key] is not None for key in
                                ("cell_id", "engine_provider",
                                 "engine_readback_digest")))

        template = runner._p0_output(stopped)
        valid_matrix = {
            ("PASS", "PASS", "NOT_APPLICABLE", True, True, True),
            ("STOP", "ABSENT", "NOT_APPLICABLE", False, False, False),
            ("UNKNOWN", "ABSENT", "NON_DURABLE", False, False, False),
            ("UNKNOWN", "UNKNOWN", "DURABLE", True, True, True),
            ("UNKNOWN", "POISONED", "DURABLE", True, True, True),
        }
        accepted = set()
        case_count = 0
        dimensions = itertools.product(
            ("PASS", "STOP", "UNKNOWN"),
            ("ABSENT", "UNKNOWN", "PASS", "POISONED"),
            ("NOT_APPLICABLE", "DURABLE", "NON_DURABLE"),
            (False, True), (False, True), (False, True))
        for status, authority, durability, has_cell, has_provider, has_digest in dimensions:
            case_count += 1
            candidate = copy.deepcopy(template)
            candidate.update(
                status=status, state_authority=authority, durability=durability,
                cell_id="cell/bound" if has_cell else None,
                engine_provider="claude_host" if has_provider else None,
                engine_readback_digest="a" * 64 if has_digest else None)
            key = (status, authority, durability, has_cell, has_provider, has_digest)
            schema_valid = p0v.is_valid(candidate)
            self.assertEqual(schema_valid, key in valid_matrix, key)
            if schema_valid: accepted.add(key)
        self.assertEqual(accepted, valid_matrix)
        self.assertEqual(case_count, 288)

        def dict_paths(value, prefix=()):
            if isinstance(value, dict):
                yield prefix
                for key, child in value.items():
                    yield from dict_paths(child, prefix + (key,))
        for path in dict_paths(passed):
            bad = copy.deepcopy(passed); target = bad
            for key in path: target = target[key]
            target["unexpected"] = True
            self.assertFalse(sealv.is_valid(bad), path)
            with self.assertRaises(ContractError): validate_seal(bad)
        pending = runner._pending_wrapper(passed, "PASS")
        pendingv = schemas["pending-publication-v8.schema.json"]
        pendingv.validate(pending)
        marker = runner._marker_wrapper(passed, "PASS", runner.canonical_bytes(pending))
        markerv = schemas["unknown-fence-v8.schema.json"]; markerv.validate(marker)
        for wrapper, validator in ((pending, pendingv), (marker, markerv)):
            bad = copy.deepcopy(wrapper); bad["unexpected"] = True
            self.assertFalse(validator.is_valid(bad))
            bad = copy.deepcopy(wrapper)
            key = "candidate_seal" if "candidate_seal" in bad else "seal"
            bad[key]["state_authority"]["unexpected"] = True
            self.assertFalse(validator.is_valid(bad))

    def test_recursive_closure_contains_all_dynamic_and_transitive_inputs(self):
        closure = json.loads((ARCH / "source-closure-v8.json").read_text())
        expected = expected_closure()
        manifested = {item["path"] for item in closure["artifacts"]}
        self.assertEqual(manifested, expected)
        required = {
            "shared/job_runtime/candidates/r6_one_off_evidence_v1/__init__.py",
            "shared/job_runtime/candidates/r6_one_off_evidence_v1/contracts.py",
            "shared/job_runtime/candidates/r6_one_off_evidence_v1/custody.py",
            "shared/job_runtime/candidates/r6_one_off_evidence_v1/publication.py",
            "shared/job_runtime/candidates/r6_one_off_evidence_v1/runner.py",
            "shared/job_runtime/engine.py", "shared/job_runtime/engine_schema.py",
            "shared/job_runtime/prompt_custody.py", "shared/job_runtime/provider_contract.py",
            "shared/job_runtime/retry_policy.py",
            "shared/job_runtime/tests/fixtures/r6_one_off_claude_live_integration_v1/fake_claude.py",
        }
        self.assertTrue(required <= manifested, required - manifested)
        chunks = []
        for item in closure["artifacts"]:
            raw = (ROOT / item["path"]).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                             (item["bytes"], item["sha256"]), item["path"])
            chunks.append(f'{item["path"]}\0{item["bytes"]}\0{item["sha256"]}\n')
        aggregate = hashlib.sha256("".join(sorted(chunks)).encode()).hexdigest()
        self.assertEqual(aggregate, closure["aggregate_sha256"])
        self.assertEqual(closure["artifact_count"], len(expected))


if __name__ == "__main__":
    unittest.main()
