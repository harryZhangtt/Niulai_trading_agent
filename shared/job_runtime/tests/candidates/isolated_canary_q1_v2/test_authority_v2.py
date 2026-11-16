import json, tempfile, unittest
from pathlib import Path
from shared.job_runtime.candidates.isolated_canary_q1_v2.authority import EXPECTED_BYTES, EXPECTED_SHA256, MANIFEST, capability_gate, load_authority_manifest
from shared.job_runtime.candidates.isolated_canary_q1_v2.contracts import AuthorityV2Error, CapabilityGateV2

class AuthorityV2Tests(unittest.TestCase):
    def test_exact_manifest_and_partial_gate(self):
        value = load_authority_manifest()
        self.assertEqual(value["schema_version"], 2)
        gate = capability_gate()
        self.assertTrue(gate.source_authority_verified and gate.source_grammar_verified and gate.binary_asset_verified)
        self.assertFalse(gate.source_to_binary_reproducible_build_verified or gate.retry_zero_live_verified or gate.sanitized_live_capture_verified or gate.gateway_observer_reconciliation_verified or gate.capability_open)

    def test_manifest_is_immutable(self):
        value = load_authority_manifest()
        with self.assertRaises(TypeError): value["tag"] = "x"

    def test_any_manifest_mutation_fails_hash_gate(self):
        raw = bytearray(MANIFEST.read_bytes()); raw[-2] ^= 1
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "manifest.json"; path.write_bytes(raw)
            with self.assertRaises(AuthorityV2Error): load_authority_manifest(path)

    def test_symlink_manifest_fails(self):
        with tempfile.TemporaryDirectory() as td:
            link = Path(td) / "manifest.json"; link.symlink_to(MANIFEST)
            with self.assertRaises(AuthorityV2Error): load_authority_manifest(link)

    def test_open_gate_requires_all_prerequisites(self):
        with self.assertRaises(AuthorityV2Error): CapabilityGateV2(True, True, True, False, True, True, True, True)

    def test_source_contains_no_invocation_surface(self):
        import shared.job_runtime.candidates.isolated_canary_q1_v2.authority as authority
        text = Path(authority.__file__).read_text()
        for forbidden in ("subprocess", "socket", "requests", "Popen", "provider_call"):
            self.assertNotIn(forbidden, text)

    def test_reader_does_not_use_path_read_bytes(self):
        from unittest import mock
        from shared.job_runtime.candidates.isolated_canary_q1_v2.authority import _read_regular
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("pathname reopened")):
            data = _read_regular(MANIFEST, expected_sha=EXPECTED_SHA256, expected_bytes=EXPECTED_BYTES)
        self.assertEqual(len(data), EXPECTED_BYTES)

    def test_fifo_and_oversized_inputs_fail_without_unbounded_read(self):
        import os
        from shared.job_runtime.candidates.isolated_canary_q1_v2.authority import _read_regular
        with tempfile.TemporaryDirectory() as td:
            fifo = Path(td) / "fifo"; os.mkfifo(fifo, 0o600)
            with self.assertRaises(AuthorityV2Error): _read_regular(fifo, expected_sha="0"*64, expected_bytes=1)
            big = Path(td) / "big"; big.write_bytes(b"xx")
            with self.assertRaises(AuthorityV2Error): _read_regular(big, expected_sha="0"*64, expected_bytes=1)

if __name__ == "__main__": unittest.main()
