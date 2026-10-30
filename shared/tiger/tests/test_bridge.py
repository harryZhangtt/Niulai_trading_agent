"""Synthetic, offline security and ambiguous-outcome controls."""
import contextlib
import io
import json
import os
import pty
import select
import subprocess
import sys
import termios
import time
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from urllib import error

from shared.tiger import bridge as t

ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / ".niulai-state" / "tests"
TESTS.mkdir(parents=True, exist_ok=True)


def policy():
    return {"project_id": "synthetic-project", "origin": "https://synthetic.chatgpt.site", "owner_email": "owner@example.test"}


def site():
    return {"id": "synthetic-project", "current_user_role": "owner", "status": "active",
            "current_live_url": "https://synthetic.chatgpt.site", "access_mode": "custom",
            "siwc_bypass_bearer_token": "synthetic-only",
            "access_policy": {"project_id": "synthetic-project", "access_mode": "custom",
              "allowed_users": [{"account_user_id": "owner", "email": "owner@example.test", "role": "owner"}],
              "allowed_account_user_ids": ["owner"], "allowed_groups": [], "allowed_workspace_group_ids": [],
              "allowed_tenant_group_ids": [], "external_visitor_count": 0}}


class TigerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TESTS)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_owner_private_context_only(self):
        self.assertEqual(t.validate_site(site(), policy())["bearer"], "synthetic-only")
        for key, value in (("current_user_role", "editor"), ("id", "other"), ("status", "suspended"),
                           ("access_mode", "public"), ("current_live_url", "https://attacker.test")):
            altered = site()
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(t.TigerBridgeError):
                t.validate_site(altered, policy())

    def test_shared_or_external_audience_rejected(self):
        mutations = [lambda a: a["allowed_users"].append({"email": "other@example.test"}),
                     lambda a: a.update(allowed_groups=[{"id": "group"}]),
                     lambda a: a.update(allowed_editors=[{"account_user_id": "other", "role": "editor"}]),
                     lambda a: a.update(external_visitor_count=1),
                     lambda a: a["allowed_users"][0].update(is_external=True),
                     lambda a: a.update(allowed_account_user_ids=["owner", "other"])]
        for mutation in mutations:
            altered = site()
            mutation(altered["access_policy"])
            with self.assertRaises(t.TigerBridgeError):
                t.validate_site(altered, policy())

    def test_origin_cannot_include_path_credentials_port_or_redirect(self):
        for origin in ("http://synthetic.chatgpt.site", "https://synthetic.chatgpt.site/path",
                       "https://synthetic.chatgpt.site?x=1", "https://u:p@synthetic.chatgpt.site",
                       "https://synthetic.chatgpt.site:443", "https://attacker.test"):
            p = policy()
            p["origin"] = origin
            with self.assertRaises(t.TigerBridgeError):
                t.validate_site(site(), p)
        self.assertIsNone(t.NoRedirect().redirect_request(None, None, None, None, None, None))

    def test_checkpoint_retry_has_identical_request_bytes(self):
        opener = Mock()
        opener.open.side_effect = [TimeoutError(), error.HTTPError("https://synthetic", 503, "", {}, None),
                                  io.BytesIO(b'{"committed":true}')]
        sleep = Mock()
        client = t.StoreClient({"origin": policy()["origin"], "bearer": "synthetic"}, opener=opener, sleep=sleep)
        body = {"lease_id": "lease", "commit_id": "stable", "profile": {"files": {"tokens/t.json": "{}"}}}
        self.assertTrue(client.rpc("/lease/checkpoint", body)["committed"])
        requests = [args.args[0] for args in opener.open.call_args_list]
        self.assertEqual(len({r.data for r in requests}), 1)
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual([x.args[0] for x in sleep.call_args_list], [1, 2])

    def test_auth_redirect_and_non_idempotent_release_are_not_retried(self):
        for path, body, exc in [("/lease/acquire", {"request_id": "same"}, error.HTTPError("u", 401, "", {}, None)),
                                 ("/lease/acquire", {"request_id": "same"}, error.HTTPError("u", 302, "", {}, None)),
                                 ("/lease/release", {"lease_id": "same"}, TimeoutError())]:
            opener = Mock()
            opener.open.side_effect = exc
            client = t.StoreClient({"origin": policy()["origin"], "bearer": "synthetic"}, opener=opener, sleep=Mock())
            with self.assertRaises(t.TigerBridgeError):
                client.rpc(path, body)
            self.assertEqual(opener.open.call_count, 1)

    def test_invalid_or_oversized_store_response_is_not_retried(self):
        for body in (b'[]', b'not-json', b'x' * (2 * 1024 * 1024 + 1)):
            opener = Mock()
            opener.open.return_value = io.BytesIO(body)
            client = t.StoreClient({"origin": policy()["origin"], "bearer": "synthetic"}, opener=opener, sleep=Mock())
            with self.assertRaisesRegex(t.TigerBridgeError, "STORE_RESPONSE_INVALID"):
                client.rpc("/lease/acquire", {"request_id": "same"})
            self.assertEqual(opener.open.call_count, 1)

    def test_missing_profile_never_becomes_empty_new_authorization(self):
        for v in (None, {}, {"files": {}}):
            with self.assertRaisesRegex(t.TigerBridgeError, "STORE_PROFILE_MISSING"):
                t.restore_profile(self.root, v)

    def test_service_auth_rejection_clears_only_preacquisition_fence(self):
        state = self.root / "state"
        out = self.root / "out"
        state.mkdir()
        out.mkdir()
        fence = state / "unresolved.json"
        for code, remains in (("STORE_HTTP_401", False), ("STORE_HTTP_403", False),
                              ("STORE_HTTP_409", True), ("STORE_NETWORK_OUTCOME_UNCONFIRMED", True)):
            with patch.object(t, "StoreClient") as cls:
                cls.return_value.rpc.side_effect = t.TigerBridgeError(code)
                with self.assertRaises(t.TigerBridgeError):
                    t._run_locked(self.root, state, out, "verify", policy(), {}, fence)
            self.assertEqual(fence.exists(), remains)
            if fence.exists():
                fence.unlink()

    def test_failure_diagnostics_never_echo_arbitrary_exception_text(self):
        failure = t.safe_failure(ValueError("secret credentials not safe"))
        self.assertNotIn("secret", json.dumps(failure))
        self.assertEqual(t.safe_failure(t.TigerBridgeError("STORE_HTTP_401"))["error"], "STORE_HTTP_401")

    def test_hidden_input_accepts_large_json_without_echo_and_restores_tty(self):
        master, slave = pty.openpty()
        before = termios.tcgetattr(slave)
        child = None
        try:
            child = subprocess.Popen([sys.executable, "-c",
                "from shared.tiger.bridge import hidden_input; "
                "v=hidden_input(timeout_seconds=10); print('RECEIVED_LENGTH='+str(len(v['payload'])))"],
                stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                env=dict(os.environ, PYTHONPATH=str(ROOT / "niulai-runtime"), PYTHONDONTWRITEBYTECODE="1"))
            captured = bytearray()
            deadline = time.monotonic() + 12
            while b"hidden stdin." not in captured:
                self.assertLess(time.monotonic(), deadline)
                if select.select([master], [], [], 0.2)[0]:
                    captured.extend(os.read(master, 65536))
            during = termios.tcgetattr(slave)
            self.assertFalse(during[3] & termios.ICANON)
            self.assertFalse(during[3] & termios.ECHO)
            self.assertEqual(during[3] & termios.ISIG, before[3] & termios.ISIG)
            value = "synthetic-secret-no-echo-" * 1200
            payload = (json.dumps({"payload": value}) + "\n").encode()
            self.assertGreater(len(payload), 16384)
            os.set_blocking(master, False)
            sent = 0
            while sent < len(payload):
                self.assertLess(time.monotonic(), deadline)
                if select.select([], [master], [], 0.2)[1]:
                    sent += os.write(master, payload[sent:sent + 2048])
            while child.poll() is None:
                self.assertLess(time.monotonic(), deadline)
                if select.select([master], [], [], 0.1)[0]:
                    captured.extend(os.read(master, 65536))
            while select.select([master], [], [], 0)[0]:
                captured.extend(os.read(master, 65536))
            self.assertEqual(child.returncode, 0, child.stderr.read().decode())
            self.assertIn(("RECEIVED_LENGTH=" + str(len(value))).encode(), captured)
            self.assertNotIn(b"synthetic-secret-no-echo", captured)
            self.assertNotIn(b"\x07", captured)
            after = termios.tcgetattr(slave)
            # Darwin may set the kernel-managed PENDIN flag while changing
            # canonical mode. Compare all application-controlled settings.
            pending = getattr(termios, "PENDIN", 0)
            after[3] &= ~pending
            before[3] &= ~pending
            self.assertEqual(after, before)
        finally:
            if child is not None:
                if child.poll() is None:
                    child.kill()
                child.wait()
                child.stderr.close()
            os.close(master)
            os.close(slave)

    def test_restore_paths_and_permissions(self):
        for path in ("../outside.json", "/tmp/outside.json", "other.json", "other/t.json", "tokens/../../bad.json"):
            with self.assertRaises(t.TigerBridgeError):
                t.restore_profile(self.root, {"files": {path: "{}"}})
        t.restore_profile(self.root, {"files": {"tokens/test.json": '{"synthetic":true}'}})
        self.assertEqual((self.root / "tokens/test.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / "tokens").stat().st_mode & 0o777, 0o700)
        (self.root / "tokens/link.json").symlink_to(self.root / "tokens/test.json")
        with self.assertRaises(t.TigerBridgeError):
            t.collect_profile(self.root)

    def test_private_paths_reject_symlink_and_escape(self):
        with self.assertRaises(t.TigerBridgeError):
            t.private_directory(self.root.parent, self.root)
        (self.root / "real").mkdir()
        (self.root / "link").symlink_to(self.root / "real")
        with self.assertRaises(t.TigerBridgeError):
            t.private_directory(self.root / "link/child", self.root)

    def test_bad_output_rejected_without_creating_or_chmodding_archive(self):
        archive = self.root / "niulai-private"
        archive.mkdir(mode=0o755)
        before = archive.stat().st_mode
        with self.assertRaisesRegex(t.TigerBridgeError, "OUTPUT_NOT_PRIVATE_STATE"):
            t.run_bridge(self.root, policy(), site(), archive / "bad")
        self.assertEqual(archive.stat().st_mode, before)
        self.assertFalse((archive / "bad").exists())
        self.assertFalse((self.root / ".niulai-state").exists())

    def fake_sdk(self):
        account = types.SimpleNamespace(account="synthetic-account", account_type="STANDARD")
        broker = Mock()
        broker.get_managed_accounts.return_value = [account]
        sdk = Mock()
        n = types.SimpleNamespace(profile_lock=lambda p: contextlib.nullcontext(),
            sdk_classes=lambda **kw: (lambda **kwargs: sdk, lambda s: broker),
            ISSUER="synthetic-issuer", SURFACE="synthetic", CLIENT_NAME="synthetic", DEFAULT_SECURITY_TYPES=("STK",),
            validate_token=lambda *a, **k: None, account_refs=lambda *a: {"synthetic-account": "synthetic-ref"},
            fetch_account=lambda *a: {"ok": True, "sourceReadStatus": "complete", "positions": [{"symbol": "SYNTH"}]},
            fetch_assets_account=lambda *a: {"ok": True, "sourceReadStatus": "complete"})
        return n

    def test_success_releases_once_and_does_not_export_bearer_to_environment(self):
        state = self.root / ".niulai-state/tiger"
        out = self.root / ".niulai-state/out"
        state.mkdir(parents=True)
        out.mkdir()
        blocker = state / "unresolved.json"
        calls = []
        def rpc(path, body):
            calls.append((path, body))
            if path == "/lease/acquire":
                return {"lease_id": "synthetic", "profile": {"files": {"tokens/test.json": "{}"}}}
            self.assertEqual(os.environ["NIULAI_PROFILE_SESSION_JSON"], "runtime-memory-callback")
            return {"committed": True}
        with patch.object(t, "StoreClient") as cls, patch.object(t, "stage_source"), \
             patch.object(t.importlib, "import_module", return_value=self.fake_sdk()):
            cls.return_value.rpc.side_effect = rpc
            result = t._run_locked(self.root, state, out, "verify", policy(), {"bearer": "secret-not-env"}, blocker)
        self.assertEqual(result["status"], "verified")
        self.assertFalse(blocker.exists())
        self.assertFalse(list(state.glob("attempt-*")))
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[-1][1]["release"])

    def test_unconfirmed_commit_retains_profile_and_prevents_next_run(self):
        state = self.root / ".niulai-state/tiger"
        out = self.root / ".niulai-state/out"
        state.mkdir(parents=True)
        out.mkdir()
        blocker = state / "unresolved.json"
        with patch.object(t, "StoreClient") as cls, patch.object(t, "stage_source"), \
             patch.object(t.importlib, "import_module", return_value=self.fake_sdk()):
            cls.return_value.rpc.side_effect = [
                {"lease_id": "synthetic", "profile": {"files": {"tokens/test.json": "{}"}}}, {"committed": False}]
            with self.assertRaisesRegex(t.TigerBridgeError, "STORE_COMMIT_UNCONFIRMED"):
                t._run_locked(self.root, state, out, "verify", policy(), {"bearer": "synthetic"}, blocker)
            self.assertEqual(cls.return_value.rpc.call_count, 2)
        self.assertTrue(blocker.exists())
        self.assertTrue(list(state.glob("attempt-*/profile/tokens/test.json")))
        with self.assertRaisesRegex(t.TigerBridgeError, "PRIOR_OUTCOME"):
            t.run_bridge(self.root, policy(), site(), out)

    def test_invalid_query_rejected_before_store_or_state_creation(self):
        invalid = [None, {}, {"tool": "place_order", "arguments": {}},
                   {"tool": "positions", "arguments": {"account": "synthetic"}},
                   {"tool": "assets", "arguments": {"security_types": ["STK"]}},
                   {"tool": "positions", "arguments": {"security_types": []}},
                   {"tool": "positions", "arguments": {"security_types": ["STK", "STK"]}},
                   {"tool": "positions", "arguments": {"security_types": [False]}},
                   {"tool": "positions", "arguments": {"security_types": ["UNKNOWN"]}}]
        with patch.object(t, "StoreClient") as store:
            for query in invalid:
                with self.subTest(query=query), self.assertRaises(t.TigerBridgeError):
                    t.run_bridge(self.root, policy(), site(), self.root / ".niulai-state/out", "query", query=query)
            store.assert_not_called()
        self.assertFalse((self.root / ".niulai-state").exists())

    def test_read_variants_and_partial_success_rejection(self):
        from shared.tiger.queries import execute_query, validate_query
        for tool, position_calls, asset_calls in (("positions", 1, 0), ("assets", 0, 1), ("snapshot", 1, 1)):
            n = self.fake_sdk()
            n.fetch_account = Mock(return_value={"ok": True, "sourceReadStatus": "complete",
                "positions": [{"amount": "0.100000000000000001"}], "marketPriceAsOf": None})
            n.fetch_assets_account = Mock(return_value={"ok": True, "sourceReadStatus": "complete"})
            query = validate_query({"tool": tool, "arguments": {}}, t.require)
            result = execute_query(n, self.root, query, t.require, t.write_json, self.root)
            self.assertEqual(result["status"], "queried")
            self.assertEqual(n.fetch_account.call_count, position_calls)
            self.assertEqual(n.fetch_assets_account.call_count, asset_calls)
            if position_calls:
                data = json.loads((self.root / "query.json").read_text())["data"]["holdings"]
                self.assertEqual(data["positions"][0]["amount"], "0.100000000000000001")
                self.assertIsNone(data["marketPriceAsOf"])
        for status in ("partial", "failed", None):
            n = self.fake_sdk()
            n.fetch_account = Mock(return_value={"ok": True, "sourceReadStatus": status, "positions": []})
            with self.assertRaisesRegex(t.TigerBridgeError, "TIGER_READ_INCOMPLETE"):
                execute_query(n, self.root, validate_query({"tool": "positions", "arguments": {}}, t.require),
                              t.require, t.write_json, self.root)

    def test_policy_permissions_and_symlink_rejected(self):
        path = self.root / ".niulai-state/config/tiger.json"
        path.parent.mkdir(parents=True)
        t.write_json(path, policy())
        self.assertEqual(t.load_policy(path, self.root), policy())
        path.chmod(0o644)
        with self.assertRaisesRegex(t.TigerBridgeError, "PRIVATE_POLICY_REQUIRED"):
            t.load_policy(path, self.root)
        path.chmod(0o600)
        link = path.with_name("link.json")
        link.symlink_to(path)
        with self.assertRaisesRegex(t.TigerBridgeError, "PRIVATE_POLICY_REQUIRED"):
            t.load_policy(link, self.root)

    def test_local_contention_does_not_acquire_remote_lease(self):
        import fcntl
        state = self.root / ".niulai-state/tiger"
        state.mkdir(parents=True)
        with (state / "bridge.lock").open("w") as lock, patch.object(t, "StoreClient") as store:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(t.TigerBridgeError, "TIGER_BRIDGE_BUSY"):
                t.run_bridge(self.root, policy(), site(), self.root / ".niulai-state/out")
            store.assert_not_called()

    def test_rotation_callback_checkpoints_under_same_lease(self):
        state = self.root / ".niulai-state/tiger"
        out = self.root / ".niulai-state/out"
        state.mkdir(parents=True)
        out.mkdir()
        calls = []
        n = self.fake_sdk()
        def fetch(broker, pin, types):
            import private_profile
            profile = next(state.glob("attempt-*/profile"))
            t.write_json(profile / "tokens/test.json", {"synthetic_rotation": 2})
            private_profile.checkpoint_from_environment(profile)
            return {"ok": True, "sourceReadStatus": "complete", "positions": []}
        n.fetch_account = Mock(side_effect=fetch)
        def rpc(path, body):
            calls.append((path, body))
            if path == "/lease/acquire":
                return {"lease_id": "only-lease", "profile": {"files": {"tokens/test.json": "{}"}}}
            self.assertEqual(body["lease_id"], "only-lease")
            self.assertEqual(json.loads(body["profile"]["files"]["tokens/test.json"]), {"synthetic_rotation": 2})
            return {"committed": True}
        with patch.object(t, "StoreClient") as store, patch.object(t, "stage_source"), \
                patch.object(t.importlib, "import_module", return_value=n):
            store.return_value.rpc.side_effect = rpc
            t._run_locked(self.root, state, out, "verify", policy(), {}, state / "unresolved.json")
        self.assertEqual(len(calls), 3)
        self.assertEqual([c[1]["release"] for c in calls[1:]], [False, True])
        self.assertNotEqual(calls[1][1]["commit_id"], calls[2][1]["commit_id"])
        n.fetch_account.assert_called_once()

    def test_reusing_query_output_rejected_before_store(self):
        out = self.root / ".niulai-state/out"
        out.mkdir(parents=True)
        t.write_json(out / "query.json", {"synthetic": "old"})
        with patch.object(t, "StoreClient") as store:
            with self.assertRaisesRegex(t.TigerBridgeError, "TIGER_OUTPUT_EXISTS"):
                t.run_bridge(self.root, policy(), site(), out, "query", query={"tool": "assets", "arguments": {}})
            store.assert_not_called()
        self.assertEqual(json.loads((out / "query.json").read_text()), {"synthetic": "old"})

    def test_deadline_bypasses_request_handlers_and_retains_recovery_state(self):
        from shared.tiger.worker import WorkerDeadline
        out = self.root / ".niulai-state/out"
        n = self.fake_sdk()
        n.fetch_account = Mock(side_effect=WorkerDeadline())
        with patch.object(t, "StoreClient") as store, patch.object(t, "stage_source"), \
                patch.object(t.importlib, "import_module", return_value=n):
            store.return_value.rpc.return_value = {
                "lease_id": "synthetic", "profile": {"files": {"tokens/test.json": "{}"}}}
            with self.assertRaises(WorkerDeadline):
                t.run_bridge(self.root, policy(), site(), out, "query", query={"tool": "snapshot", "arguments": {}})
            self.assertEqual(store.return_value.rpc.call_count, 1)
        state = self.root / ".niulai-state/tiger"
        self.assertTrue((state / "unresolved.json").exists())
        self.assertTrue(list(state.glob("attempt-*/profile/tokens/test.json")))
        receipt = json.loads((out / "tiger_status.json").read_text())
        self.assertEqual(receipt["error"], "TIGER_RUN_DEADLINE")
        self.assertTrue(receipt["reconciliation_required"])


if __name__ == "__main__":
    unittest.main()
