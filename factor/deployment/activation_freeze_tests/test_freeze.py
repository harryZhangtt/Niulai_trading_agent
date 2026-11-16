import copy
from pathlib import Path
import shutil
import tempfile
import unittest

from factor.deployment import gcp_activation_freeze

ROOT = Path(__file__).resolve().parents[3]

class ActivationFreezeTests(unittest.TestCase):
    def test_tracked_manifest_validates_disabled_parent_binding(self):
        value = gcp_activation_freeze.load_and_validate()
        self.assertEqual(value["status"], "frozen-disabled")
        self.assertEqual(value["parent_manifest_sha256"], gcp_activation_freeze.PARENT_SHA256)

    def test_duplicate_key_and_status_weakening_fail(self):
        with self.assertRaisesRegex(gcp_activation_freeze.ActivationFreezeError, "DUPLICATE_KEY"):
            gcp_activation_freeze.loads_strict(b'{"schema_version":1,"schema_version":1}')
        value = copy.deepcopy(gcp_activation_freeze.load_and_validate())
        value["status"] = "active"
        with self.assertRaisesRegex(gcp_activation_freeze.ActivationFreezeError, "SCHEMA"):
            gcp_activation_freeze.validate(value)

    def test_file_drift_fails(self):
        value = gcp_activation_freeze.load_and_validate()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in gcp_activation_freeze.gcp_freeze.SCOPE_ROOTS:
                source, target = ROOT / relative, root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, target) if source.is_dir() else shutil.copy2(source, target)
            shutil.copy2(ROOT / "factor/deployment/gcp-freeze-v1.json", root / "factor/deployment/gcp-freeze-v1.json")
            for relative in gcp_activation_freeze.SCOPE_ROOTS:
                source, target = ROOT / relative, root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, target) if source.is_dir() else shutil.copy2(source, target)
            target = root / value["files"][0]["path"]
            target.write_bytes(target.read_bytes() + b"\n")
            with self.assertRaisesRegex(gcp_activation_freeze.ActivationFreezeError, "DRIFT"):
                gcp_activation_freeze.validate(value, root)

    def test_extra_scoped_file_fails(self):
        value = gcp_activation_freeze.load_and_validate()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in gcp_activation_freeze.gcp_freeze.SCOPE_ROOTS:
                source, target = ROOT / relative, root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, target) if source.is_dir() else shutil.copy2(source, target)
            shutil.copy2(ROOT / "factor/deployment/gcp-freeze-v1.json", root / "factor/deployment/gcp-freeze-v1.json")
            for relative in gcp_activation_freeze.SCOPE_ROOTS:
                source, target = ROOT / relative, root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, target) if source.is_dir() else shutil.copy2(source, target)
            extra = root / "factor/deployment/gcp_activation/undeclared.json"
            extra.write_text("{}")
            with self.assertRaisesRegex(gcp_activation_freeze.ActivationFreezeError, "SCOPE_DRIFT"):
                gcp_activation_freeze.validate(value, root)

if __name__ == "__main__":
    unittest.main()
