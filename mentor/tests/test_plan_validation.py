"""Behavioral checks for the adapted upstream read-only plan validator."""

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/research-supervisor/scripts/validate-plan.sh"


class PlanValidationTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / "runtime/test-tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="plan with spaces ", dir=parent)
        self.directory = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def check_plan(self, text):
        path = self.directory / "task_plan.md"
        path.write_text(text)
        result = subprocess.run(["bash", str(SCRIPT), str(path)],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(path.read_text(), text, "validator changed the plan")
        return result

    def test_pending_template_is_valid_format_not_completion(self):
        text = (ROOT / "skills/research-supervisor/templates/task_plan.md").read_text()
        result = self.check_plan(text)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("format valid", result.stdout)
        self.assertNotIn("ALL PHASES COMPLETE", result.stdout)

    def test_missing_status_is_rejected(self):
        self.assertEqual(self.check_plan("### Phase 1: Work\nNo status\n").returncode, 1)

    def test_duplicate_status_is_rejected(self):
        self.assertEqual(self.check_plan("### Phase 1: Work\n**Status:** pending\n**Status:** complete\n").returncode, 1)

    def test_empty_plan_is_rejected(self):
        self.assertEqual(self.check_plan("").returncode, 1)

    def test_commands_in_plan_are_not_executed(self):
        marker = self.directory / "must-not-exist"
        text = f"### Phase 1: Work\n**Status:** complete\n```bash\ntouch '{marker}'\n```\n"
        self.assertEqual(self.check_plan(text).returncode, 0)
        self.assertFalse(marker.exists())

    def test_missing_explicit_path_does_not_fall_back(self):
        result = subprocess.run(["bash", str(SCRIPT), str(self.directory / "missing.md")],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
