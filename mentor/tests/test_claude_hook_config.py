import json
import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / ".claude/settings.json"
SCRIPT = "${CLAUDE_PROJECT_DIR}/mentor/session_init.py"


class ClaudeMentorHookConfigTests(unittest.TestCase):
    def setUp(self):
        self.value = json.loads(SETTINGS.read_text())
        self.hooks = self.value["hooks"]

    def test_nonblocking_loader_and_no_guard_registrations(self):
        self.assertNotIn("mentor/mentor_guard.py", json.dumps(self.hooks))
        loaders = [(group, command) for group in self.hooks["SessionStart"]
                   for command in group["hooks"] if SCRIPT in command.get("args", [])]
        self.assertEqual(len(loaders), 1)
        group, command = loaders[0]
        self.assertEqual(command["type"], "command")
        self.assertEqual(command["command"], "python3")
        self.assertEqual(command["timeout"], 10)
        self.assertEqual(command.get("async"), None)
        self.assertEqual(command.get("onFailure"), "continue")
        self.assertEqual(command["args"], ["-B", SCRIPT])
        self.assertEqual(group["matcher"], "startup|resume|clear|compact|fork")
        self.assertTrue((ROOT / "mentor/session_init.py").is_file())

    def test_disabled_candidate_lock_matches_maintained_sources(self):
        self.assertEqual(set(self.value), {"hooks"})
        lock = json.loads((ROOT / "mentor/enforcement-lock.json").read_text())
        self.assertEqual(lock["context_paths"], ["mentor/AGENTS.md", "mentor/ROUTING.md"])
        self.assertEqual(lock["guard_version"], "mentor-guard-v1")
        paths = {item["path"] for item in lock["files"]}
        self.assertIn("mentor/mentor_guard.py", paths)
        self.assertIn("mentor/session_init.py", paths)
        self.assertIn("CLAUDE.md", paths)
        self.assertIn("AGENTS.md", paths)
        for item in lock["files"]:
            self.assertEqual(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest(),
                             item["sha256"], item["path"])


if __name__ == "__main__":
    unittest.main()
