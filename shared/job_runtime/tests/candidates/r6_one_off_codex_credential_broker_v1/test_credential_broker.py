from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import http.server
import inspect
import io
import json
import logging
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest import mock

from jsonschema import Draft202012Validator

from shared.job_runtime.candidates.r6_one_off_codex_credential_broker_v1 import BrokerError, execute_live
from shared.job_runtime.candidates.r6_one_off_codex_credential_broker_v1 import broker, contracts, publication
from shared.job_runtime.candidates.r6_one_off_codex_direct_catalog_v1 import capability, transport

ROOT = Path(__file__).resolve().parents[5]
CANDIDATE = ROOT / "shared/job_runtime/candidates/r6_one_off_codex_credential_broker_v1"
SECRET = b"synthetic-broker-access-token"
CATALOG = b'{"models":[{"slug":"gpt-6.1-sol"},{"slug":"gpt-5"}]}'
RESPONSE_MARKER = b"SYNTHETIC-RAW-CATALOG-MARKER-7c21"


class FakeUpstream:
    def __init__(self, body: bytes = CATALOG, status: int = 200):
        self.body = body
        self.status = status
        self.requests = []

    def __enter__(self):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_GET(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b""
                outer.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "body_bytes": len(body),
                        "auth_exact": self.headers.get("Authorization") == "Bearer " + SECRET.decode("ascii"),
                    }
                )
                self.send_response(outer.status)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    @property
    def endpoint(self):
        return transport._Endpoint("127.0.0.1", self.server.server_address[1], False, "fixture_loopback")


def auth_bytes(token: bytes = SECRET) -> bytes:
    value = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": "synthetic-id",
            "access_token": token.decode("ascii"),
            "refresh_token": "synthetic-refresh",
            "oauth_provenance": {"issuer": "synthetic", "client_id": "fixture"},
            "login_owner_id": "synthetic-login",
            "account_id": "synthetic-account",
        },
        "last_refresh": "2026-11-11T00:00:00Z",
    }
    return json.dumps(value, separators=(",", ":")).encode("ascii")


def write_auth(root: Path, raw: bytes | None = None, mode: int = 0o600) -> Path:
    home = root / "codex-home"
    home.mkdir(mode=0o700)
    source = home / "auth.json"
    source.write_bytes(auth_bytes() if raw is None else raw)
    source.chmod(mode)
    return source


def run_broker(source: Path, output: Path, upstream: FakeUpstream, **kwargs):
    with mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint):
        return broker._execute_for_test(broker._TEST_SEAM, source, output, **kwargs)


def assert_graph_excludes(testcase: unittest.TestCase, error: BaseException, forbidden: tuple[bytes, ...]) -> None:
    objects = set()
    tracebacks = set()
    stack = [error]
    while stack:
        value = stack.pop()
        if value is None or id(value) in objects:
            continue
        objects.add(id(value))
        if isinstance(value, str):
            raw = value.encode("utf-8", "ignore")
            for marker in forbidden:
                testcase.assertNotIn(marker, raw)
        elif isinstance(value, (bytes, bytearray, memoryview)):
            raw = bytes(value)
            for marker in forbidden:
                testcase.assertNotIn(marker, raw)
        elif isinstance(value, BaseException):
            stack.extend((value.args, value.__dict__, value.__cause__, value.__context__))
            cursor = value.__traceback__
            while cursor is not None and id(cursor) not in tracebacks:
                tracebacks.add(id(cursor))
                stack.extend(cursor.tb_frame.f_locals.values())
                cursor = cursor.tb_next
        elif isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, (tuple, list, set, frozenset)):
            stack.extend(value)
        else:
            state = getattr(value, "__dict__", None)
            if isinstance(state, dict):
                stack.append(state)
            for cls in type(value).__mro__:
                slots = cls.__dict__.get("__slots__", ())
                if isinstance(slots, str):
                    slots = (slots,)
                for slot in slots:
                    if slot not in ("__dict__", "__weakref__"):
                        try:
                            stack.append(getattr(value, slot))
                        except (AttributeError, TypeError):
                            pass


class CredentialBrokerTests(unittest.TestCase):
    def tearDown(self):
        self.assertEqual(capability._active_material_count(), 0)

    def test_public_entrypoint_is_fixed_argument_free_disabled_and_does_not_read_credentials(self):
        self.assertEqual(list(inspect.signature(execute_live).parameters), [])
        self.assertNotIn("_execute_for_test", __import__("shared.job_runtime.candidates.r6_one_off_codex_credential_broker_v1", fromlist=["x"]).__all__)
        with mock.patch.object(broker, "_read_credential", side_effect=AssertionError("credential read forbidden")):
            with self.assertRaises(BrokerError) as caught:
                execute_live()
        self.assertEqual(caught.exception.code, "SEPARATE_EXACT_LIVE_GRANT_AND_REVIEW_REQUIRED")
        self.assertEqual(caught.exception.state, "REJECTED")

    def test_nominal_one_request_wipes_token_source_and_publishes_verified_commit_last(self):
        captured = []
        real_scope = broker.transient_bearer_scope

        @contextmanager
        def observed_scope(source):
            captured.append(source)
            with real_scope(source) as value:
                yield value

        with tempfile.TemporaryDirectory() as directory, FakeUpstream() as upstream:
            root = Path(directory)
            source = write_auth(root)
            output = root / "output"
            stdout = io.StringIO()
            stderr = io.StringIO()
            before_handlers = tuple(logging.getLogger().handlers)
            with mock.patch.object(broker, "transient_bearer_scope", observed_scope), redirect_stdout(stdout), redirect_stderr(stderr):
                published = run_broker(source, output, upstream)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(tuple(logging.getLogger().handlers), before_handlers)
            self.assertEqual(captured, [bytearray()])
            self.assertEqual(upstream.requests, [{"method": "GET", "path": "/backend-api/codex/models?client_version=0.167.0", "body_bytes": 0, "auth_exact": True}])
            self.assertEqual(published.raw_catalog_path.read_bytes(), CATALOG)
            membership = json.loads(published.membership_receipt_path.read_text())
            execution = json.loads(published.execution_receipt_path.read_text())
            marker = json.loads(published.commit_marker_path.read_text())
            self.assertEqual(set(membership), {"origin", "status", "body_sha256", "body_bytes", "model_count", "gpt_6_1_sol_membership"})
            self.assertEqual(membership["gpt_6_1_sol_membership"], {"model": "gpt-6.1-sol", "count": 1, "exact": True})
            self.assertEqual(execution["physical_forwards"], 1)
            self.assertEqual((execution["retry"], execution["replay"], execution["auth_recovery"], execution["status_queries"], execution["inference_requests"], execution["bytedcli_calls"]), (0, 0, 0, 0, 0, 0))
            self.assertTrue(marker["committed"])
            for path in output.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertFalse(any("staging" in path.name for path in output.iterdir()))
            other_times = [path.stat().st_mtime_ns for path in (published.raw_catalog_path, published.membership_receipt_path, published.execution_receipt_path)]
            self.assertGreaterEqual(published.commit_marker_path.stat().st_mtime_ns, max(other_times))
            self.assertNotIn(SECRET, published.membership_receipt_path.read_bytes() + published.execution_receipt_path.read_bytes() + published.commit_marker_path.read_bytes())
            schemas = CANDIDATE / "schemas"
            Draft202012Validator(json.loads((schemas / "catalog-membership-receipt-v1.schema.json").read_text())).validate(membership)
            Draft202012Validator(json.loads((schemas / "execution-receipt-v1.schema.json").read_text())).validate(execution)
            Draft202012Validator(json.loads((schemas / "commit-marker-v1.schema.json").read_text())).validate(marker)

    def test_source_symlink_mode_owner_and_hardlink_rejected_before_executor(self):
        def forbidden_factory():
            raise AssertionError("executor must not be constructed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = write_auth(root)
            link = real.with_name("link.json")
            link.symlink_to(real)
            cases = [(link, None), (real, None)]
            real.chmod(0o644)
            for index, (source, _) in enumerate(cases):
                with self.subTest(index=index):
                    with self.assertRaises(BrokerError):
                        broker._execute_for_test(broker._TEST_SEAM, source, root / ("out-" + str(index)), executor_factory=forbidden_factory)
            real.chmod(0o600)
            with self.assertRaises(BrokerError):
                broker._execute_for_test(broker._TEST_SEAM, real, root / "owner", expected_uid=os.getuid() + 1, executor_factory=forbidden_factory)
            hard = real.with_name("hard.json")
            os.link(real, hard)
            with self.assertRaises(BrokerError):
                broker._execute_for_test(broker._TEST_SEAM, real, root / "hard-out", executor_factory=forbidden_factory)

    def test_duplicate_malformed_nonfinite_missing_and_unknown_fields_rejected(self):
        malformed = (
            b'{"tokens":{"id_token":"i","access_token":"a","refresh_token":"r"},"tokens":{}}',
            b'{"tokens":{"id_token":"i","access_token":"a","access_token":"b","refresh_token":"r"}}',
            b'{"tokens":',
            b'{"tokens":{"id_token":"i","refresh_token":"r"}}',
            b'{"tokens":{"id_token":"i","access_token":"a","refresh_token":"r"},"last_refresh":NaN}',
            b'{"tokens":{"id_token":"i","access_token":"a","refresh_token":"r"},"unknown":"x"}',
        )
        calls = 0

        def forbidden_factory():
            nonlocal calls
            calls += 1
            raise AssertionError("executor must not be constructed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, raw in enumerate(malformed):
                home = root / ("home-" + str(index))
                home.mkdir(mode=0o700)
                source = home / "auth.json"
                source.write_bytes(raw)
                source.chmod(0o600)
                with self.subTest(index=index), self.assertRaises(BrokerError) as caught:
                    broker._execute_for_test(broker._TEST_SEAM, source, root / ("out-" + str(index)), executor_factory=forbidden_factory)
                self.assertEqual(caught.exception.code, "CREDENTIAL_FORMAT_REJECTED")
                assert_graph_excludes(self, caught.exception, (SECRET,))
        self.assertEqual(calls, 0)

    def test_short_writes_complete_and_zero_write_fences_unknown_without_secret_graph(self):
        class ShortWriter:
            def __init__(self):
                self.calls = 0

            def __call__(self, descriptor, value):
                self.calls += 1
                return os.write(descriptor, value[: max(1, len(value) // 2)])

        class ZeroWriter:
            def __call__(self, descriptor, value):
                return 0

        with tempfile.TemporaryDirectory() as directory, FakeUpstream() as upstream:
            root = Path(directory)
            source = write_auth(root)
            writer = ShortWriter()
            run_broker(source, root / "short", upstream, write_fn=writer)
            self.assertGreater(writer.calls, 4)
        body = b'{"models":[{"slug":"gpt-6.1-sol","note":"' + RESPONSE_MARKER + b'"}]}'
        with tempfile.TemporaryDirectory() as directory, FakeUpstream(body) as upstream:
            root = Path(directory)
            source = write_auth(root)
            with self.assertRaises(BrokerError) as caught:
                run_broker(source, root / "zero", upstream, write_fn=ZeroWriter())
            self.assertEqual(caught.exception.state, "UNKNOWN")
            assert_graph_excludes(self, caught.exception, (SECRET, RESPONSE_MARKER))
            self.assertEqual(len(upstream.requests), 1)

    def test_crash_fences_unknown_second_execution_and_exception_graph_is_clean(self):
        class Crash(BaseException):
            pass

        def crash(stage):
            if stage == "after_parent_fsync:catalog.raw.json":
                raise Crash("synthetic crash")

        body = b'{"models":[{"slug":"gpt-6.1-sol","note":"' + RESPONSE_MARKER + b'"}]}'
        with tempfile.TemporaryDirectory() as directory, FakeUpstream(body) as upstream:
            root = Path(directory)
            source = write_auth(root)
            output = root / "crash"
            with self.assertRaises(Crash) as caught:
                run_broker(source, output, upstream, fault=crash)
            assert_graph_excludes(self, caught.exception, (SECRET, RESPONSE_MARKER))
            self.assertFalse((output / "COMMITTED.json").exists())
            with self.assertRaises(BrokerError) as second:
                run_broker(source, output, upstream)
            self.assertEqual(second.exception.code, "UNKNOWN_EXISTING_EXECUTION_FENCE")
            self.assertEqual(second.exception.state, "UNKNOWN")
            self.assertEqual(len(upstream.requests), 1)

    def test_second_execution_after_commit_rejected_before_provider(self):
        with tempfile.TemporaryDirectory() as directory, FakeUpstream() as upstream:
            root = Path(directory)
            source = write_auth(root)
            output = root / "output"
            run_broker(source, output, upstream)
            with self.assertRaises(BrokerError) as caught:
                run_broker(source, output, upstream)
            self.assertEqual(caught.exception.code, "SECOND_EXECUTION_REJECTED")
            self.assertEqual(len(upstream.requests), 1)

    def test_token_and_response_failures_have_sanitized_exception_graphs(self):
        class HeaderBomb:
            sock = None
            def putrequest(self, *args, **kwargs): return None
            def putheader(self, *args, **kwargs): raise ValueError("leak:" + SECRET.decode("ascii"))
            def endheaders(self): raise AssertionError("must not send")
            def close(self): return None

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_auth(root)
            with mock.patch.object(transport, "_connection", return_value=HeaderBomb()):
                with self.assertRaises(BrokerError) as caught:
                    broker._execute_for_test(broker._TEST_SEAM, source, root / "header")
            assert_graph_excludes(self, caught.exception, (SECRET, RESPONSE_MARKER))
        malformed_body = b'{"models":[' + RESPONSE_MARKER + b']'
        with tempfile.TemporaryDirectory() as directory, FakeUpstream(malformed_body) as upstream:
            root = Path(directory)
            source = write_auth(root)
            with self.assertRaises(BrokerError) as caught:
                run_broker(source, root / "malformed", upstream)
            assert_graph_excludes(self, caught.exception, (SECRET, RESPONSE_MARKER))

    def test_source_pins_fixed_limits_no_registration_and_no_effect_machinery(self):
        contracts.verify_frozen_contracts()
        self.assertEqual(contracts.FIXED_CREDENTIAL_PATH, Path("/Users/bytedance/Desktop/Trading Agent/.job-runtime/codex-home/auth.json"))
        self.assertEqual(contracts.DIRECT_PRODUCER[1:], (5801, "0acfd52223e9bef05550963c7ac69075e5fa7885094b49f778090e7bb54565f4"))
        self.assertEqual(contracts.DIRECT_REVIEW[1:], (8509, "479a177b63c1bd255de6a81af61ecc74d8e6dca27a6602ee62e32b27386650fa"))
        for path in (ROOT / "shared/job_runtime/config.py", ROOT / "shared/job_runtime/service.py"):
            self.assertNotIn("r6_one_off_codex_credential_broker_v1", path.read_text())
        source = "\n".join(path.read_text() for path in CANDIDATE.glob("*.py"))
        for forbidden in ("subprocess", "requests.", "urllib.", "os.system", "status_query(", "auth_recover("):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("bytedcli ", source)

    def test_closed_schemas_and_private_seam_marker(self):
        for path in (CANDIDATE / "schemas").glob("*.schema.json"):
            schema = json.loads(path.read_text())
            Draft202012Validator.check_schema(schema)
            def walk(value):
                if isinstance(value, dict):
                    if value.get("type") == "object":
                        self.assertIs(value.get("additionalProperties"), False)
                        self.assertIs(value.get("unevaluatedProperties"), False)
                    for child in value.values():
                        walk(child)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)
            walk(schema)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_auth(root)
            with self.assertRaisesRegex(BrokerError, "PRIVATE_TEST_SEAM_REJECTED"):
                broker._execute_for_test(object(), source, root / "out")


if __name__ == "__main__":
    unittest.main()
