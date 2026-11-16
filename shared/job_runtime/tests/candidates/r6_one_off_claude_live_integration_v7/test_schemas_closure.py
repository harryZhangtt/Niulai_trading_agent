from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
PKG = ROOT / "shared/job_runtime/candidates/r6_one_off_claude_live_integration_v7"
TESTS = ROOT / "shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v7"
SCHEMAS = PKG / "schemas"
ARCH = ROOT / "tuning/architecture/r6_one_off_claude_live_integration_v7"
REVIEW = ROOT / "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-claude-live-integration-v6-independent-review-open-fable-20261111-8e9a8076.json"

from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v7 import authority as authmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v7 import runner
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v7.contracts import (
    ContractError, blank_seal, validate_seal,
)
from shared.job_runtime.tests.candidates.r6_one_off_claude_live_integration_v7.test_integration import (
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
    verifier = ARCH / "verify_v7.py"
    if verifier.is_file(): artifacts.add(verifier)
    return {str(path.relative_to(ROOT)) for path in artifacts if "__pycache__" not in path.parts}


class SchemasClosureV7Tests(unittest.TestCase):
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
        self.assertFalse(any("r6_one_off_claude_live_integration_v7" in p.read_text()
                             for p in runtime.glob("*.py")))

    def test_v6_open_review_exact_and_history_remains_open(self):
        raw = REVIEW.read_bytes()
        self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                         (17482, "0ee60c531e050133f3f86e1b980e7199c52018596682b245c02cb932a28a68d8"))
        review = json.loads(raw)
        self.assertEqual(review["verdict"], "OPEN")
        self.assertEqual(len(review["findings"]), 6)

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
        unknown, _ = _unknown_pair(generation)
        passed = _valid_pass(generation)
        stopped = blank_seal()
        sealv = schemas["post-run-seal-v7.schema.json"]
        for value in (passed, unknown, stopped):
            validate_seal(value); sealv.validate(value)
        for value in (passed, unknown, stopped):
            p0 = runner._p0_output(value)
            schemas["p0-output-v7.schema.json"].validate(p0)
        contradictions = []
        p0 = runner._p0_output(passed)
        for field in ("cell_id", "engine_provider", "engine_readback_digest"):
            bad = copy.deepcopy(p0); bad[field] = None; contradictions.append(bad)
        p0 = runner._p0_output(stopped); bad = copy.deepcopy(p0)
        bad.update(status="PASS", cell_id=None, engine_provider=None,
                   engine_readback_digest=None); contradictions.append(bad)
        for bad in contradictions:
            self.assertFalse(schemas["p0-output-v7.schema.json"].is_valid(bad), bad)
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
        pendingv = schemas["pending-publication-v7.schema.json"]
        pendingv.validate(pending)
        marker = runner._marker_wrapper(passed, "PASS", runner.canonical_bytes(pending))
        markerv = schemas["unknown-fence-v7.schema.json"]; markerv.validate(marker)
        for wrapper, validator in ((pending, pendingv), (marker, markerv)):
            bad = copy.deepcopy(wrapper); bad["unexpected"] = True
            self.assertFalse(validator.is_valid(bad))
            bad = copy.deepcopy(wrapper)
            key = "candidate_seal" if "candidate_seal" in bad else "seal"
            bad[key]["state_authority"]["unexpected"] = True
            self.assertFalse(validator.is_valid(bad))

    def test_recursive_closure_contains_all_dynamic_and_transitive_inputs(self):
        closure = json.loads((ARCH / "source-closure-v7.json").read_text())
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
