from __future__ import annotations
import ast
import copy
import hashlib
import http.server
import inspect
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from shared.job_runtime.candidates.r6_one_off_codex_direct_catalog_v1 import (
    CatalogExecutionError, ContractError, DirectCatalogExecutor, transient_bearer_scope,
)
from shared.job_runtime.candidates.r6_one_off_codex_direct_catalog_v1 import capability, contracts, transport

ROOT = Path(__file__).resolve().parents[5]
CANDIDATE = ROOT / "shared/job_runtime/candidates/r6_one_off_codex_direct_catalog_v1"
FIXTURE = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_codex_direct_catalog_v1/cases.json"
SECRET = b"synthetic-direct-catalog-secret"

class FakeUpstream:
    def __init__(self, *, body: bytes, status: int = 200, delay: float = 0.0, location: str | None = None):
        self.body, self.status, self.delay, self.location = body, status, delay, location
        self.requests = []
    def __enter__(self):
        outer = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                return
            def do_GET(self):
                length = int(self.headers.get("Content-Length", "0"))
                request_body = self.rfile.read(length) if length else b""
                outer.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "body_bytes": len(request_body),
                    "auth_exact": self.headers.get("Authorization") == "Bearer " + SECRET.decode("ascii"),
                })
                if outer.delay:
                    time.sleep(outer.delay)
                self.send_response(outer.status)
                if outer.location is not None:
                    self.send_header("Location", outer.location)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                try:
                    self.wfile.write(outer.body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="direct-catalog-fake", daemon=True)
        self.thread.start()
        return self
    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
    @property
    def endpoint(self):
        return transport._Endpoint("127.0.0.1", self.server.server_address[1], False, "fixture_loopback")

def cases():
    return json.loads(FIXTURE.read_text())

def capture_execution_error(executor, token, **kwargs):
    result = None
    try:
        executor.execute(token, **kwargs)
    except CatalogExecutionError as caught:
        result = caught
    executor = None
    token = None
    return result

def assert_exception_graph_excludes(testcase, error, forbidden):
    object_seen = set()
    traceback_seen = set()
    stack = [error]
    while stack:
        value = stack.pop()
        if value is None:
            continue
        identifier = id(value)
        if identifier in object_seen:
            continue
        object_seen.add(identifier)
        if isinstance(value, str):
            encoded = value.encode("utf-8", "ignore")
            for marker in forbidden:
                testcase.assertNotIn(marker, encoded)
        elif isinstance(value, (bytes, bytearray, memoryview)):
            raw = bytes(value)
            for marker in forbidden:
                testcase.assertNotIn(marker, raw)
        elif isinstance(value, BaseException):
            stack.extend((value.args, value.__dict__, value.__cause__, value.__context__))
            traceback = value.__traceback__
            while traceback is not None and id(traceback) not in traceback_seen:
                traceback_seen.add(id(traceback))
                stack.extend(traceback.tb_frame.f_locals.values())
                traceback = traceback.tb_next
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
                    if slot in ("__dict__", "__weakref__"):
                        continue
                    try:
                        stack.append(getattr(value, slot))
                    except (AttributeError, TypeError):
                        pass

def run(upstream: FakeUpstream, *, include_raw: bool = False):
    source = bytearray(SECRET)
    with transient_bearer_scope(source) as token:
        assert not any(source)
        with mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint):
            result = DirectCatalogExecutor().execute(token, include_owner_private_raw=include_raw)
    assert capability._active_material_count() == 0
    return result, token

class DirectCatalogTests(unittest.TestCase):
    def test_nominal_exact_request_and_redacted_receipt(self):
        body = cases()["nominal"].encode()
        with FakeUpstream(body=body) as upstream:
            result, token = run(upstream)
        self.assertEqual(upstream.requests, [{"method": "GET", "path": contracts.TARGET, "body_bytes": 0, "auth_exact": True}])
        self.assertEqual(result.models, ("gpt-6.1-sol", "gpt-5"))
        self.assertEqual(result.receipt, {"status": "PASS", "http_status": 200,
                                         "body_sha256": hashlib.sha256(body).hexdigest(),
                                         "body_bytes": len(body), "model_count": 2})
        self.assertEqual((result.origin.kind, result.origin.host, result.origin.tls_hostname_verified),
                         ("fixture_loopback", "127.0.0.1", False))
        self.assertIsNone(result.owner_private_raw)
        dumped = repr(result) + json.dumps(result.receipt, sort_keys=True) + repr(token)
        self.assertNotIn(SECRET.decode(), dumped)
        self.assertEqual(capability._active_material_count(), 0)

    def test_wrong_method_path_query_and_body_are_impossible(self):
        source = inspect.getsource(transport.forward_once)
        self.assertIn('putrequest("GET", TARGET', source)
        self.assertNotIn("redirect", source.lower())
        self.assertNotIn("retry", source.lower())
        self.assertEqual(inspect.signature(DirectCatalogExecutor.execute).parameters.keys(),
                         {"self", "capability", "include_owner_private_raw"})
        self.assertEqual(contracts.TARGET, "/backend-api/codex/models?client_version=0.167.0")

    def test_second_execution_and_spent_capability_rejected(self):
        body = cases()["nominal"].encode()
        with FakeUpstream(body=body) as upstream, mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint):
            source = bytearray(SECRET)
            with transient_bearer_scope(source) as token:
                executor = DirectCatalogExecutor()
                executor.execute(token)
                with self.assertRaisesRegex(CatalogExecutionError, "SECOND_EXECUTION_REJECTED"):
                    executor.execute(token)
                other = DirectCatalogExecutor()
                with self.assertRaisesRegex(CatalogExecutionError, "CAPABILITY_REJECTED"):
                    other.execute(token)
            self.assertEqual(capability._active_material_count(), 0)
        self.assertEqual(len(upstream.requests), 1)

    def test_redirect_auth_rate_and_server_errors_never_retry(self):
        for status in (301, 302, 307, 308, 401, 403, 429, 500, 503):
            with self.subTest(status=status), FakeUpstream(body=b"rejected", status=status, location="http://127.0.0.1/other") as upstream:
                source = bytearray(SECRET)
                with transient_bearer_scope(source) as token:
                    with mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint):
                        with self.assertRaises(CatalogExecutionError) as caught:
                            DirectCatalogExecutor().execute(token)
                self.assertEqual(caught.exception.code, "HTTP_STATUS_REJECTED")
                self.assertEqual(caught.exception.receipt["http_status"], status)
                self.assertEqual(len(upstream.requests), 1)
                self.assertEqual(capability._active_material_count(), 0)

    def test_forged_capability_and_secret_nonpersistence(self):
        class Forged:
            def __repr__(self):
                return SECRET.decode()
        before_env = dict(os.environ)
        before_handlers = tuple(logging.getLogger().handlers)
        with self.assertRaisesRegex(CatalogExecutionError, "CAPABILITY_REJECTED") as caught:
            DirectCatalogExecutor().execute(Forged())
        self.assertNotIn(SECRET.decode(), repr(caught.exception))
        self.assertEqual(before_env, dict(os.environ))
        self.assertEqual(before_handlers, tuple(logging.getLogger().handlers))
        for path in CANDIDATE.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET, path.read_bytes())
        self.assertFalse(hasattr(capability, "TransientBearer"))
        with transient_bearer_scope(bytearray(SECRET)) as token:
            with self.assertRaises(TypeError):
                vars(token)
            self.assertNotIn(SECRET.decode(), repr(token))
            self.assertEqual(capability._active_material_count(), 1)
        self.assertEqual(capability._active_material_count(), 0)

    def test_crlf_unsafe_and_header_valueerror_sanitized(self):
        unsafe_values = (b"abc\r\nX-Evil:value", b"abc space", b"abc\xff", b"abc=def")
        for raw in unsafe_values:
            with self.subTest(raw=raw):
                source = bytearray(raw)
                with self.assertRaisesRegex(ValueError, "^transient bearer source rejected$") as caught:
                    with transient_bearer_scope(source):
                        pass
                self.assertFalse(any(source))
                self.assertNotIn(raw.decode("latin-1"), repr(caught.exception))
        class HeaderBomb:
            sock = None
            def putrequest(self, *args, **kwargs):
                return None
            def putheader(self, *args, **kwargs):
                raise ValueError("header rejected: " + SECRET.decode())
            def endheaders(self):
                raise AssertionError("must not send")
            def close(self):
                return None
        source = bytearray(SECRET)
        with transient_bearer_scope(source) as token:
            with mock.patch.object(transport, "_connection", return_value=HeaderBomb()):
                with self.assertRaises(CatalogExecutionError) as caught:
                    DirectCatalogExecutor().execute(token)
        self.assertEqual(caught.exception.code, "AUTH_HEADER_REJECTED")
        cursor = caught.exception
        while cursor is not None:
            self.assertNotIn(SECRET.decode(), repr(cursor))
            cursor = cursor.__cause__ or cursor.__context__
        self.assertEqual(caught.exception.receipt, {"status": "REJECTED", "http_status": 599,
                                                    "body_sha256": None, "body_bytes": 0,
                                                    "model_count": 0})
        self.assertEqual(capability._active_material_count(), 0)

    def test_exception_graph_traceback_locals_exclude_auth_and_oversize_body(self):
        body_marker = b"OVERSIZE-TRACEBACK-SENTINEL-39f7"
        oversize_body = (body_marker * ((contracts.MAX_BODY_BYTES // len(body_marker)) + 2))
        with FakeUpstream(body=oversize_body) as upstream, \
             mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint):
            with transient_bearer_scope(bytearray(SECRET)) as token:
                oversize_error = capture_execution_error(DirectCatalogExecutor(), token)
        self.assertIsNotNone(oversize_error)
        self.assertEqual(oversize_error.code, "BODY_OVERSIZE")
        assert_exception_graph_excludes(self, oversize_error, (body_marker, SECRET))

        class HeaderBomb:
            sock = None
            def putrequest(self, *args, **kwargs): return None
            def putheader(self, *args, **kwargs):
                raise ValueError("header-secret:" + SECRET.decode())
            def endheaders(self): raise AssertionError("must not send")
            def close(self): return None
        with transient_bearer_scope(bytearray(SECRET)) as token:
            with mock.patch.object(transport, "_connection", return_value=HeaderBomb()):
                header_error = capture_execution_error(DirectCatalogExecutor(), token)
        self.assertIsNotNone(header_error)
        self.assertEqual(header_error.code, "AUTH_HEADER_REJECTED")
        assert_exception_graph_excludes(self, header_error, (SECRET, body_marker))

    def test_bounded_failure_graphs_exclude_malformed_and_http_error_bodies(self):
        malformed_marker = b"MALFORMED-200-BODY-SENTINEL-dcv4"
        malformed_body = b'{"models":[' + malformed_marker + b']'
        with FakeUpstream(body=malformed_body, status=200) as upstream, \
             mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint):
            with transient_bearer_scope(bytearray(SECRET)) as token:
                malformed_error = capture_execution_error(DirectCatalogExecutor(), token)
        self.assertIsNotNone(malformed_error)
        self.assertEqual(malformed_error.code, "MALFORMED_JSON")
        assert_exception_graph_excludes(self, malformed_error, (malformed_marker, malformed_body, SECRET))

        status_marker = b"HTTP-503-BODY-SENTINEL-dcv4"
        status_body = b"bounded-provider-error:" + status_marker
        with FakeUpstream(body=status_body, status=503) as upstream, \
             mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint):
            with transient_bearer_scope(bytearray(SECRET)) as token:
                status_error = capture_execution_error(DirectCatalogExecutor(), token)
        self.assertIsNotNone(status_error)
        self.assertEqual(status_error.code, "HTTP_STATUS_REJECTED")
        assert_exception_graph_excludes(self, status_error, (status_marker, status_body, SECRET))
        self.assertEqual(status_error.receipt["body_bytes"], len(status_body))
        self.assertEqual(status_error.receipt["body_sha256"], hashlib.sha256(status_body).hexdigest())

    def test_explicit_capability_lifetime_is_order_independent_without_gc(self):
        class Forged:
            __slots__ = ("payload",)
            def __init__(self):
                self.payload = SECRET
        class HeaderBomb:
            sock = None
            def putrequest(self, *args, **kwargs): return None
            def putheader(self, *args, **kwargs): raise ValueError("fixed rejection")
            def endheaders(self): raise AssertionError("must not send")
            def close(self): return None
        def exercise(name):
            self.assertEqual(capability._active_material_count(), 0)
            if name == "unused_scope":
                with transient_bearer_scope(bytearray(SECRET)) as token:
                    self.assertEqual(capability._active_material_count(), 1)
                    self.assertNotIn(SECRET.decode(), repr(token))
            elif name == "forged":
                error = capture_execution_error(DirectCatalogExecutor(), Forged())
                self.assertIsNotNone(error)
                self.assertEqual(error.code, "CAPABILITY_REJECTED")
                assert_exception_graph_excludes(self, error, (SECRET,))
            elif name == "invalid_flag":
                with transient_bearer_scope(bytearray(SECRET)) as token:
                    error = capture_execution_error(DirectCatalogExecutor(), token, include_owner_private_raw=1)
                    self.assertIsNotNone(error)
                    self.assertEqual(error.code, "RAW_CUSTODY_FLAG_REJECTED")
                    self.assertEqual(capability._active_material_count(), 0)
                    assert_exception_graph_excludes(self, error, (SECRET,))
            elif name == "second_fresh":
                body = cases()["nominal"].encode()
                with FakeUpstream(body=body) as upstream, mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint):
                    executor = DirectCatalogExecutor()
                    with transient_bearer_scope(bytearray(SECRET)) as first:
                        executor.execute(first)
                    with transient_bearer_scope(bytearray(SECRET)) as second:
                        error = capture_execution_error(executor, second)
                        self.assertIsNotNone(error)
                        self.assertEqual(error.code, "SECOND_EXECUTION_REJECTED")
                        self.assertEqual(capability._active_material_count(), 0)
                        assert_exception_graph_excludes(self, error, (SECRET,))
            elif name == "header":
                with transient_bearer_scope(bytearray(SECRET)) as token:
                    with mock.patch.object(transport, "_connection", return_value=HeaderBomb()):
                        with self.assertRaisesRegex(CatalogExecutionError, "AUTH_HEADER_REJECTED"):
                            DirectCatalogExecutor().execute(token)
            else:
                raise AssertionError(name)
            self.assertEqual(capability._active_material_count(), 0)
        orders = (("unused_scope", "forged", "invalid_flag", "second_fresh", "header"),
                  ("header", "second_fresh", "invalid_flag", "forged", "unused_scope"),
                  ("forged", "unused_scope", "header", "invalid_flag", "second_fresh"))
        for order in orders:
            for name in order:
                exercise(name)

    def test_timeout_wipes_secret_and_stops(self):
        body = cases()["nominal"].encode()
        with FakeUpstream(body=body, delay=0.25) as upstream:
            source = bytearray(SECRET)
            with transient_bearer_scope(source) as token:
                with mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint), \
                     mock.patch.object(transport, "_TIMEOUT_SECONDS", 0.05):
                    with self.assertRaises(CatalogExecutionError) as caught:
                        DirectCatalogExecutor().execute(token)
        self.assertEqual(caught.exception.code, "TRANSPORT_FAILURE")
        self.assertNotIn(SECRET.decode(), repr(caught.exception) + repr(caught.exception.receipt))
        self.assertEqual(len(upstream.requests), 1)
        self.assertEqual(capability._active_material_count(), 0)

    def test_strict_schema_duplicate_target_and_oversize(self):
        data = cases()
        self.assertEqual(contracts.parse_catalog(data["nominal"].encode()), ("gpt-6.1-sol", "gpt-5"))
        for key in ("duplicate_key", "duplicate_slug", "malformed", "missing_target", "nonfinite"):
            with self.subTest(key=key), self.assertRaises(ContractError):
                contracts.parse_catalog(data[key].encode())
        with self.assertRaises(ContractError):
            contracts.parse_catalog(b"x" * (contracts.MAX_BODY_BYTES + 1))
        with FakeUpstream(body=b"x" * (contracts.MAX_BODY_BYTES + 1)) as upstream:
            source = bytearray(SECRET)
            with transient_bearer_scope(source) as token:
                with mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint):
                    with self.assertRaises(CatalogExecutionError) as caught:
                        DirectCatalogExecutor().execute(token)
        self.assertEqual(caught.exception.code, "BODY_OVERSIZE")
        self.assertEqual(caught.exception.receipt, {"status": "REJECTED", "http_status": 200,
                                                    "body_sha256": None,
                                                    "body_bytes": contracts.MAX_BODY_BYTES,
                                                    "model_count": 0})
        self.assertFalse(hasattr(caught.exception, "body"))
        self.assertNotIn("xxx", repr(caught.exception) + repr(caught.exception.receipt))
        self.assertEqual(len(upstream.requests), 1)

    def test_fixed_grant_review_default_deny_and_self_mint(self):
        contracts.load_fixed_authority()
        self.assertNotIn("grant", inspect.signature(DirectCatalogExecutor).parameters)
        original = contracts._read_bound
        grant = json.loads(original(contracts.GRANT))
        grant["limits"]["physical_forwards"] = 2
        forged = json.dumps(grant, separators=(",", ":"), sort_keys=True).encode()
        with mock.patch.object(contracts, "_read_bound", side_effect=lambda ref: forged if ref == contracts.GRANT else original(ref)):
            with self.assertRaisesRegex(ContractError, "GRANT_REJECTED"):
                DirectCatalogExecutor()
        review = json.loads(original(contracts.REVIEW))
        review["independent_from_executor"] = False
        forged_review = json.dumps(review, separators=(",", ":"), sort_keys=True).encode()
        with mock.patch.object(contracts, "_read_bound", side_effect=lambda ref: forged_review if ref == contracts.REVIEW else original(ref)):
            with self.assertRaisesRegex(ContractError, "REVIEW_REJECTED"):
                DirectCatalogExecutor()

    def test_raw_response_opt_in_and_publication_cleanup(self):
        body = cases()["nominal"].encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = tuple(root.iterdir())
            with FakeUpstream(body=body) as upstream:
                result, _ = run(upstream, include_raw=True)
            self.assertEqual(result.owner_private_raw, body)
            self.assertEqual(tuple(root.iterdir()), before)
        self.assertNotIn(body.decode(), json.dumps(result.receipt))

    def test_no_nonloopback_or_provider_effect_and_closed_artifacts(self):
        body = cases()["nominal"].encode()
        with FakeUpstream(body=body) as upstream, \
             mock.patch.object(transport.http.client, "HTTPSConnection", side_effect=AssertionError("provider route forbidden")):
            result, _ = run(upstream)
        self.assertEqual(result.receipt["status"], "PASS")
        for ref in (contracts.GRANT, contracts.REVIEW):
            raw = (ROOT / ref[0]).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), ref[1:])
        for path in CANDIDATE.glob("*.py"):
            ast.parse(path.read_text())
        active_files = [ROOT / "shared/job_runtime/config.py", ROOT / "shared/job_runtime/service.py"]
        for path in active_files:
            self.assertNotIn("r6_one_off_codex_direct_catalog_v1", path.read_text())

class SchemaTests(unittest.TestCase):
    def test_draft202012_closed_schemas(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
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
        grant_schema = json.loads((CANDIDATE / "schemas/direct-catalog-design-grant-v1.schema.json").read_text())
        review_schema = json.loads((CANDIDATE / "schemas/direct-catalog-grant-review-v1.schema.json").read_text())
        receipt_schema = json.loads((CANDIDATE / "schemas/direct-catalog-receipt-v1.schema.json").read_text())
        Draft202012Validator(grant_schema).validate(json.loads((ROOT / contracts.GRANT[0]).read_text()))
        Draft202012Validator(review_schema).validate(json.loads((ROOT / contracts.REVIEW[0]).read_text()))
        body = cases()["nominal"].encode()
        with FakeUpstream(body=body) as upstream:
            result, _ = run(upstream)
        Draft202012Validator(receipt_schema).validate(result.receipt)

    def test_all_emitted_failure_receipts_validate(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
        schema = json.loads((CANDIDATE / "schemas/direct-catalog-receipt-v1.schema.json").read_text())
        validator = Draft202012Validator(schema)
        receipts = []
        scenarios = ((b"x" * (contracts.MAX_BODY_BYTES + 1), 200),
                     (cases()["malformed"].encode(), 200), (b"rejected", 503))
        for body, status in scenarios:
            with FakeUpstream(body=body, status=status) as upstream:
                with transient_bearer_scope(bytearray(SECRET)) as token:
                    with mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint):
                        with self.assertRaises(CatalogExecutionError) as caught:
                            DirectCatalogExecutor().execute(token)
            receipts.append(caught.exception.receipt)
        class HeaderBomb:
            sock = None
            def putrequest(self, *args, **kwargs): return None
            def putheader(self, *args, **kwargs): raise ValueError("secret-bearing detail " + SECRET.decode())
            def endheaders(self): raise AssertionError("must not send")
            def close(self): return None
        with transient_bearer_scope(bytearray(SECRET)) as token:
            with mock.patch.object(transport, "_connection", return_value=HeaderBomb()):
                with self.assertRaises(CatalogExecutionError) as caught:
                    DirectCatalogExecutor().execute(token)
        receipts.append(caught.exception.receipt)
        for receipt in receipts:
            validator.validate(receipt)
        self.assertEqual(receipts[0]["body_bytes"], contracts.MAX_BODY_BYTES)
        self.assertIsNone(receipts[0]["body_sha256"])

if __name__ == "__main__":
    unittest.main()
