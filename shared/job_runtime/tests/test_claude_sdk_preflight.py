import hashlib
import importlib.metadata
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from shared.job_runtime.claude_sdk_preflight import (
    MODEL_USAGE_OPTIONAL_KEYS, MODEL_USAGE_REQUIRED_KEYS, _record_digests,
    _typed_dict_shape, inspect_environment,
)


class ClaudeSdkPreflightTests(unittest.TestCase):
    def test_absent_local_sdk_blocks_without_network_or_install(self):
        requirement = Path(__file__).parents[1] / "claude-requirements.txt"
        with mock.patch(
            "shared.job_runtime.claude_sdk_preflight.importlib.metadata.distribution",
            side_effect=importlib.metadata.PackageNotFoundError,
        ):
            result = inspect_environment(requirement)
        self.assertEqual(result["status"], "BLOCKED_OFFLINE")
        self.assertIn("CLAUDE_SDK_MISSING", result["blockers"])
        self.assertIn("CLAUDE_SDK_REVIEWED_TREE_DIGEST_MISSING", result["blockers"])
        self.assertIn("CLAUDE_SDK_REVIEWED_RECORD_RAW_BYTES_DIGEST_MISSING", result["blockers"])
        self.assertIn("CLAUDE_SDK_REVIEWED_RECORD_IMPORTLIB_TEXT_DIGEST_MISSING", result["blockers"])
        self.assertFalse(result["network_used"])
        self.assertFalse(result["install_performed"])
        self.assertEqual(result["declared_requirement"], "claude-agent-sdk==0.2.179")


    def test_record_digests_bind_raw_crlf_and_importlib_text_separately(self):
        class FakeDistribution:
            files = [Path("claude_agent_sdk-0.2.179.dist-info/RECORD")]

            def __init__(self, root):
                self.root = root

            def locate_file(self, item):
                return self.root / item

            def read_text(self, name):
                raise AssertionError("text-mode distribution read must not be used")

        raw = b"alpha,sha256=one,1\r\nbeta,sha256=two,2\r\n"
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            record = root_path / FakeDistribution.files[0]
            record.parent.mkdir()
            record.write_bytes(raw)
            raw_digest, text_digest = _record_digests(FakeDistribution(root_path))
        self.assertEqual(raw_digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(text_digest, hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest())
        self.assertNotEqual(raw_digest, text_digest)

    def test_record_digest_rejects_symlink_final_entry(self):
        class FakeDistribution:
            files = [Path("claude_agent_sdk-0.2.179.dist-info/RECORD")]

            def __init__(self, root):
                self.root = root

            def locate_file(self, item):
                return self.root / item

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            dist_info = root_path / "claude_agent_sdk-0.2.179.dist-info"
            dist_info.mkdir()
            target = root_path / "outside-record"
            target.write_bytes(b"outside\n")
            (dist_info / "RECORD").symlink_to(target)
            self.assertEqual(_record_digests(FakeDistribution(root_path)), (None, None))

    def test_model_usage_typed_dict_tags_are_exact(self):
        class ExactShape:
            __annotations__ = {key: object for key in
                               MODEL_USAGE_REQUIRED_KEYS | MODEL_USAGE_OPTIONAL_KEYS}
            __required_keys__ = MODEL_USAGE_REQUIRED_KEYS
            __optional_keys__ = MODEL_USAGE_OPTIONAL_KEYS
        annotations, required, optional = _typed_dict_shape(ExactShape)
        self.assertEqual(annotations, MODEL_USAGE_REQUIRED_KEYS | MODEL_USAGE_OPTIONAL_KEYS)
        self.assertEqual(required, MODEL_USAGE_REQUIRED_KEYS)
        self.assertEqual(optional, MODEL_USAGE_OPTIONAL_KEYS)

        class WrongTags(ExactShape):
            __required_keys__ = MODEL_USAGE_REQUIRED_KEYS | {"provider"}
            __optional_keys__ = {"canonicalModel"}
        _, wrong_required, wrong_optional = _typed_dict_shape(WrongTags)
        self.assertNotEqual(wrong_required, MODEL_USAGE_REQUIRED_KEYS)
        self.assertNotEqual(wrong_optional, MODEL_USAGE_OPTIONAL_KEYS)

    def test_pin_drift_is_an_independent_blocker(self):
        with tempfile.TemporaryDirectory() as root:
            requirement = Path(root) / "requirements.txt"
            requirement.write_text("claude-agent-sdk==0.2.178\n")
            with mock.patch(
                "shared.job_runtime.claude_sdk_preflight.importlib.metadata.distribution",
                side_effect=importlib.metadata.PackageNotFoundError,
            ):
                result = inspect_environment(requirement)
        self.assertIn("CLAUDE_SDK_PIN_INVALID", result["blockers"])
        self.assertFalse(result["network_used"])


if __name__ == "__main__":
    unittest.main()
