from __future__ import annotations

import ast
import builtins
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
CANDIDATE = ROOT / "candidates" / "claude_visible_session_v1"
FIXTURES = ROOT / "tests" / "fixtures" / "claude_visible_session_v1"
NAME = "claude_visible_session_v1"


class InertnessTest(unittest.TestCase):
    def test_source_has_no_provider_process_network_or_execution_entrypoint(self):
        forbidden_imports = {
            "anthropic", "claude_agent_sdk", "subprocess", "socket", "urllib",
            "requests", "httpx", "aiohttp", "webbrowser",
        }
        forbidden_calls = {"exec", "eval", "compile", "system", "popen", "spawn"}
        for path in CANDIDATE.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(any(alias.name == name or alias.name.startswith(name + ".") for name in forbidden_imports), path.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertFalse(any(node.module == name or node.module.startswith(name + ".") for name in forbidden_imports), path.name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertNotEqual(node.name, "main", path.name)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden_calls, path.name)
            self.assertNotIn("if __name__", text)

    def test_import_performs_no_open_resolve_stat_or_invocation(self):
        name = NAME + "_import_probe"
        spec = importlib.util.spec_from_file_location(
            name, CANDIDATE / "__init__.py", submodule_search_locations=[str(CANDIDATE)]
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        fail = AssertionError("candidate import performed filesystem I/O")
        try:
            with mock.patch.object(builtins, "open", side_effect=fail), \
                 mock.patch.object(Path, "open", side_effect=fail), \
                 mock.patch.object(Path, "resolve", side_effect=fail), \
                 mock.patch.object(Path, "stat", side_effect=fail):
                spec.loader.exec_module(module)
        finally:
            sys.modules.pop(name, None)
            sys.modules.pop(name + ".contracts", None)

    def test_no_import_time_calls_except_constant_construction(self):
        for path in CANDIDATE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    self.fail("module-level expression call in {0}".format(path.name))
                if isinstance(node, (ast.With, ast.For, ast.While, ast.Try)):
                    self.fail("module-level executable block in {0}".format(path.name))

    def test_activatable_canonical_files_and_symlinks_do_not_reference_candidate(self):
        text_suffixes = {".py", ".json", ".toml", ".yaml", ".yml", ".sh", ".plist", ".service"}
        special_names = {"Dockerfile", "Makefile"}
        scanned = 0
        for path in ROOT.rglob("*"):
            normalized = path.as_posix()
            if "/candidates/" in normalized or "/tests/" in normalized or "/__pycache__/" in normalized:
                continue
            if path.is_symlink():
                scanned += 1
                self.assertNotIn(NAME, os.readlink(str(path)), normalized)
                self.assertNotIn(NAME, path.name, normalized)
                continue
            if path.suffix not in text_suffixes and path.name not in special_names:
                continue
            if not path.is_file():
                continue
            scanned += 1
            self.assertNotIn(NAME, path.read_text(encoding="utf-8"), normalized)
        self.assertGreater(scanned, 0)
        self.assertLess(scanned, 5000, "activation scan must remain bounded")

    def test_fixture_content_excludes_sensitive_domains(self):
        forbidden = ("ixic", "niulai-private", "private_state", "/private/")
        for path in FIXTURES.rglob("*"):
            if not path.is_file() or path.suffix == ".bin":
                continue
            lowered = path.read_text(encoding="utf-8").lower()
            for marker in forbidden:
                self.assertNotIn(marker, lowered, path.as_posix())


if __name__ == "__main__":
    unittest.main()
