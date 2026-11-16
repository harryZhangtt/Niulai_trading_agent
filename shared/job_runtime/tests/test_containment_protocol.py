"""Composition tests for the single host/guest containment protocol."""
from __future__ import annotations

import json
import plistlib
import socket
import unittest
from pathlib import Path

from shared.job_runtime.tests import test_containment as containment_fixtures
from shared.job_runtime.vm_assets import guest_agent


ROOT = Path(__file__).parents[1]
MACOS = ROOT / "vm_assets" / "macos"
SCHEMA = json.loads((MACOS / "request.schema.json").read_text())
PROTOCOL_SWIFT = (MACOS / "Protocol.swift").read_text()
HOST_SWIFT = (MACOS / "ContainmentHost.swift").read_text()


class ProtocolCompositionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = containment_fixtures.ContainmentTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_python_render_matches_closed_camel_case_schema_and_swift_keys(self):
        prepared = self.fixture.manager().prepare(self.fixture.request())
        value = json.loads(prepared.request_path.read_text())
        self.assertEqual(set(value), set(SCHEMA["required"]))
        self.assertFalse(SCHEMA["additionalProperties"])
        for key in SCHEMA["required"]:
            self.assertIn('"' + key + '"', PROTOCOL_SWIFT)
        self.assertEqual(value["protocolVersion"], 1)
        self.assertRegex(value["nonce"], r"^[0-9a-f]{64}$")
        self.assertEqual(value["artifacts"]["guestAgent"]["bakedInto"], "rootDisk")

    def test_launchd_cli_and_private_authority_tree_are_exact(self):
        prepared = self.fixture.manager().prepare(self.fixture.request())
        plist = plistlib.loads(prepared.plist_path.read_bytes())
        self.assertEqual(plist["ProgramArguments"][1:], ["--request-file", str(prepared.request_path)])
        self.assertTrue(Path(plist["ProgramArguments"][0]).is_absolute())
        for name in ("artifacts", "io", "mounts", "profiles", "receipts"):
            self.assertEqual((prepared.state_dir / name).stat().st_mode & 0o777, 0o700)

    def test_five_byte_frames_cross_host_guest_fixture(self):
        wire = guest_agent.encode_frame(guest_agent.FRAME_REQUEST, b"{}")
        self.assertEqual(len(wire[:5]), 5)
        left, right = socket.socketpair()
        try:
            right.sendall(wire)
            self.assertEqual(guest_agent.read_frame(left, 16), (guest_agent.FRAME_REQUEST, b"{}"))
        finally:
            left.close(); right.close()
        self.assertIn("readExactly(5)", HOST_SWIFT)
        self.assertIn("header.append(type)", HOST_SWIFT)

    def test_typed_state_machine_and_single_cancel(self):
        for token in ("FRAME_REQUEST", "FRAME_PROMPT", "FRAME_PROMPT_END", "FRAME_STDOUT",
                      "FRAME_STDERR", "FRAME_EXIT", "FRAME_POWEROFF", "FRAME_CANCEL"):
            self.assertIn(token, Path(ROOT / "vm_assets" / "guest_agent.py").read_text())
        self.assertIn("frameCancel", HOST_SWIFT)
        self.assertIn("stop_ack", HOST_SWIFT)

    def test_no_sensitive_values_in_plist_or_receipt_contract(self):
        prepared = self.fixture.manager().prepare(self.fixture.request())
        plist = prepared.plist_path.read_text()
        for secret in ("task-reference", "input-reference", "opaque-reference"):
            self.assertNotIn(secret, plist)
        receipt_body = PROTOCOL_SWIFT.split("struct TeardownReceipt", 1)[1].split("}", 1)[0]
        self.assertNotIn("prompt", receipt_body)
        self.assertIn("requestSHA256", receipt_body)
        self.assertIn("nonceDigest", receipt_body)


if __name__ == "__main__":
    unittest.main()
