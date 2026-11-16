import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from factor.deployment import gcp_freeze


ROOT = Path(__file__).resolve().parents[3]


class GcpFreezeTests(unittest.TestCase):
    def test_tracked_manifest_validates_and_is_disabled(self):
        value = gcp_freeze.load_and_validate()
        self.assertEqual(value["status"], "frozen-disabled")
        self.assertEqual(value["blockers"], gcp_freeze.BLOCKERS)
        self.assertEqual(value["nonclaims"], gcp_freeze.NONCLAIMS)

    def test_duplicate_keys_and_status_weakening_fail(self):
        with self.assertRaisesRegex(gcp_freeze.FreezeError, "DUPLICATE_KEY"):
            gcp_freeze.loads_strict(b'{"schema_version":1,"schema_version":1}')
        value = copy.deepcopy(gcp_freeze.load_and_validate())
        value["status"] = "active"
        with self.assertRaisesRegex(gcp_freeze.FreezeError, "SCHEMA"):
            gcp_freeze.validate_manifest(value)

    def test_changed_file_fails_drift(self):
        value = gcp_freeze.load_and_validate()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in gcp_freeze.SCOPE_ROOTS:
                source = ROOT / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)
            target = root / value["files"][0]["path"]
            target.write_bytes(target.read_bytes() + b"\n")
            with self.assertRaisesRegex(gcp_freeze.FreezeError, "DRIFT"):
                gcp_freeze.validate_manifest(value, root)

    def test_extra_scoped_file_fails(self):
        value = gcp_freeze.load_and_validate()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in gcp_freeze.SCOPE_ROOTS:
                source = ROOT / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)
            extra = root / "factor/docker/gcp/undeclared.json"
            extra.write_text(json.dumps({"unexpected": True}))
            with self.assertRaisesRegex(gcp_freeze.FreezeError, "SCOPE_DRIFT"):
                gcp_freeze.validate_manifest(value, root)


if __name__ == "__main__":
    unittest.main()
