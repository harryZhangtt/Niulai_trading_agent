from __future__ import annotations

import inspect
import os
import pathlib
import stat
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

import shared.job_runtime.candidates.r6_one_off_claude_live_integration_v8 as package
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v8 import process as processmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v8 import state as statemod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v8.contracts import validate_seal


class FixedPublicBoundaryV8Tests(unittest.TestCase):
    def test_zero_argument_fixed_provider_boundary_and_second_call_no_replay(self):
        self.assertEqual(package.__all__, ["run"])
        self.assertEqual(list(inspect.signature(package.run).parameters), [])
        public = {name: value for name, value in vars(package).items()
                  if not name.startswith("_") and callable(value)}
        self.assertEqual(public, {"run": package.run})
        for args in ((pathlib.Path("/tmp/caller-root"),), (object(),)):
            with self.assertRaises(TypeError): package.run(*args)
        for kwargs in ({"root": pathlib.Path("/tmp/x")}, {"effect": object()},
                       {"scenario": "live"}, {"provider": object()}):
            with self.assertRaises(TypeError): package.run(**kwargs)
        with self.assertRaises(TypeError):
            class ForbiddenSubclass(processmod._PinnedProviderEffect):
                pass
        first = package.run(); validate_seal(first)
        self.assertEqual((first["version"], first["status"],
                          first["engine"]["provider"], first["state_authority"]["state"]),
                         (8, "PASS", "claude_host", "PASS"))
        with mock.patch.object(processmod._PinnedProviderEffect, "execute",
                               side_effect=AssertionError("second effect")) as effect:
            second = package.run()
        self.assertEqual(second, first); effect.assert_not_called()
        root_info = os.lstat(statemod.ROOT_PATH)
        self.assertTrue(stat.S_ISDIR(root_info.st_mode))
        self.assertEqual((root_info.st_uid, stat.S_IMODE(root_info.st_mode)), (501, 0o700))
        ledger = os.lstat(statemod.ROOT_PATH / statemod.LEDGER_NAME)
        self.assertTrue(stat.S_ISREG(ledger.st_mode))
        self.assertEqual((ledger.st_uid, stat.S_IMODE(ledger.st_mode)), (501, 0o600))
        self.assertEqual(first["effects"], {"provider": 0, "non_loopback_network": 0,
            "account": 0, "login": 0, "private_live_root": 0, "email": 0,
            "host": 0, "persistent": 0, "business": 0, "scheduler": 0, "r6": 0})


if __name__ == "__main__":
    unittest.main()
