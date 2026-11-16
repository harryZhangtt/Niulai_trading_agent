#!/usr/bin/env python3
"""Provider-free deterministic tests for readiness drift and expiry semantics."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("readiness_verifier", HERE / "verifier.py")
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class TimestampTests(unittest.TestCase):
    START = "2026-11-10T06:04:58.108114+00:00"
    END = "2026-11-10T06:34:58.108114+00:00"

    def test_half_open_window_before_boundary_is_fresh(self) -> None:
        self.assertTrue(
            verifier.is_fresh(
                "2026-11-10T06:34:58.108113+00:00", self.START, self.END
            )
        )

    def test_exact_expiry_boundary_is_stale(self) -> None:
        self.assertFalse(verifier.is_fresh(self.END, self.START, self.END))

    def test_after_expiry_is_stale(self) -> None:
        self.assertFalse(
            verifier.is_fresh("2026-11-13T00:00:00+00:00", self.START, self.END)
        )

    def test_naive_timestamp_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.VerificationError, "TIMESTAMP_NOT_AWARE"):
            verifier.parse_time("2026-11-10T06:34:58")


class IdentityDriftTests(unittest.TestCase):
    def test_exact_identity_passes_and_byte_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence.json"
            path.write_bytes(b'{"fixed":true}\n')
            identity = {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            verifier.verify_identity(identity)
            path.write_bytes(b'{"fixed":false}\n')
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "IDENTITY_(BYTES|SHA256)_DRIFT",
            ):
                verifier.verify_identity(identity)

    def test_symlink_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "target"
            target.write_bytes(b"x")
            link = base / "link"
            link.symlink_to(target)
            identity = {
                "path": str(link),
                "bytes": 1,
                "sha256": hashlib.sha256(b"x").hexdigest(),
            }
            with self.assertRaisesRegex(
                verifier.VerificationError, "IDENTITY_NOT_REGULAR"
            ):
                verifier.verify_identity(identity)


class StatusTests(unittest.TestCase):
    def test_v8_blocker_has_precedence_over_refresh(self) -> None:
        self.assertEqual(
            verifier.derive_status(True, True),
            "BLOCKED_PENDING_CLAUDE_V8_REVIEW",
        )

    def test_stale_without_v8_blocker_requires_refresh(self) -> None:
        self.assertEqual(verifier.derive_status(False, True), "REFRESH_REQUIRED")

    def test_current_only_when_neither_condition_applies(self) -> None:
        self.assertEqual(verifier.derive_status(False, False), "CURRENT_SUFFICIENT")


if __name__ == "__main__":
    unittest.main()
