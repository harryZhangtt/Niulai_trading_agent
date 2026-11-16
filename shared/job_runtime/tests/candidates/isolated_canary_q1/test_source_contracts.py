from pathlib import Path
import json
import unittest

from _loader import submodule


class SourceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[3] / "candidates" / "isolated_canary_q1"
        cls.closure = submodule("source_closure")

    def test_source_closure_is_reproducible(self):
        manifest = self.closure.load_source_closure()
        self.assertEqual(self.closure.verify_source_closure(self.root, manifest), manifest["closure_sha256"])

    def test_bundle_and_monitor_schema_parity_markers(self):
        bundle = json.loads((self.root / "schemas" / "bundle-v1.schema.json").read_text())
        self.assertIn("(?!.*\\.\\.)", bundle["properties"]["prompt_source_name"]["pattern"])
        self.assertEqual(bundle["properties"]["candidate_id"]["pattern"], "^icq1-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{24}$")
        monitor = json.loads((self.root / "schemas" / "monitor-event-v1.schema.json").read_text())
        self.assertEqual(set(monitor["properties"]["slot_ordinal"]["enum"]), {None, 1, 2})
        self.assertIn("slot_terminal", monitor["properties"]["event_type"]["enum"])
        self.assertEqual(monitor["properties"]["code"]["pattern"], "^CANARY_[A-Z0-9_]+$")


if __name__ == "__main__": unittest.main()
