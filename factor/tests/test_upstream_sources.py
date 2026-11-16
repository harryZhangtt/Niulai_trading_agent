import copy
import json
from pathlib import Path
import tempfile
import unittest

from factor.upstream import verify


class UpstreamSourceTests(unittest.TestCase):
    def test_current_pins_sources_and_licenses_verify(self):
        result = verify.verify()
        self.assertEqual(result["status"], "FACTOR_SOURCES_OK")
        self.assertEqual([item["id"] for item in result["sources"]],
                         ["rd-agent", "qlib-rdagent-compatible", "qlib-standalone-candidate"])
        self.assertEqual(result["execution_status"], "source-only-not-installed-not-executed")

    def test_compatibility_pin_cannot_be_silently_replaced(self):
        lock = json.loads(verify.LOCK.read_text())
        changed = copy.deepcopy(lock)
        changed["sources"][1]["revision"] = changed["sources"][2]["revision"]
        with self.assertRaisesRegex(verify.VerificationError, "FACTOR_SOURCE_COMPATIBILITY"):
            verify.validate_lock(changed)

    def test_duplicate_runtime_paths_are_rejected(self):
        lock = json.loads(verify.LOCK.read_text())
        changed = copy.deepcopy(lock)
        changed["sources"][2]["runtime_path"] = changed["sources"][1]["runtime_path"]
        with self.assertRaisesRegex(verify.VerificationError, "FACTOR_SOURCE_RUNTIME_PATH"):
            verify.validate_lock(changed)


if __name__ == "__main__":
    unittest.main()
