from pathlib import Path
import ast
import unittest


class InertnessTest(unittest.TestCase):
    def test_candidate_tree_has_no_effect_entrypoint_or_effectful_import(self):
        root = Path(__file__).resolve().parents[3] / "candidates" / "isolated_canary_q1"
        forbidden = {"subprocess", "socket", "urllib", "requests", "http", "plistlib", "webbrowser", "shared.job_runtime.service", "shared.job_runtime.host"}
        for path in root.rglob("*.py"):
            text = path.read_text(); tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertTrue(all(not any(alias.name == name or alias.name.startswith(name + ".") for name in forbidden) for alias in node.names), path.name)
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertFalse(any(node.module == name or node.module.startswith(name + ".") for name in forbidden), path.name)
                if isinstance(node, ast.FunctionDef): self.assertNotEqual(node.name, "main", path.name)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name): self.assertNotEqual(node.func.id, "__import__", path.name)
            self.assertNotIn("if __name__", text)

    def test_complete_canonical_package_does_not_reference_candidate(self):
        runtime = Path(__file__).resolve().parents[3]
        for path in runtime.rglob("*.py"):
            if "candidates/isolated_canary_q1" in path.as_posix() or "/tests/" in path.as_posix():
                continue
            self.assertNotIn("isolated_canary_q1", path.read_text(), path.as_posix())


if __name__ == "__main__": unittest.main()
