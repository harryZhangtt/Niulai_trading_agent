from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[5]
CANDIDATE = ROOT / "shared/job_runtime/candidates/r6_one_off_claude_catalog_parser_v1"
EXPERIMENT = ROOT / "tuning/architecture/r6_one_off_claude_catalog_parser_v1/experiment.py"


class InertnessTests(unittest.TestCase):
    def test_no_provider_network_account_process_or_retry_surface(self):
        forbidden_imports = {"anthropic", "requests", "httpx", "socket", "urllib", "subprocess"}
        forbidden_calls = {"retry", "replay", "popen", "run", "call", "system"}
        for path in list(CANDIDATE.glob("*.py")) + [EXPERIMENT]:
            tree = ast.parse(path.read_text(), filename=str(path), feature_version=(3, 9))
            imports = set()
            calls = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
                elif isinstance(node, ast.Call):
                    target = node.func
                    if isinstance(target, ast.Name): calls.add(target.id.lower())
                    elif isinstance(target, ast.Attribute): calls.add(target.attr.lower())
            self.assertFalse(imports & forbidden_imports, path)
            self.assertFalse(calls & forbidden_calls, path)


if __name__ == "__main__":
    unittest.main()
