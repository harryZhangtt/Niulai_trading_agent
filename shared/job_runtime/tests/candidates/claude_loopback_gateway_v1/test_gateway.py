from __future__ import annotations

import ast
import copy
import hashlib
import http.client
import json
import os
import pickle
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import shared.job_runtime.candidates.claude_loopback_gateway_v1.gateway as gateway_module
import shared.job_runtime.candidates.claude_loopback_gateway_v1.receipts as receipts_module

from shared.job_runtime.candidates.claude_loopback_gateway_v1 import (
    AttestationVerificationError,
    ExpectedPreForwardBinding,
    GatewayConfig,
    LoopbackGateway,
    ReceiptIntegrityError,
    ReceiptLedger,
    THREAT_MODEL,
    VerifiedPreForwardAttestation,
)


ROOT = Path(__file__).parents[5]
CANDIDATE = ROOT / "shared/job_runtime/candidates/claude_loopback_gateway_v1"
STREAM_FIXTURE = ROOT / "shared/job_runtime/tests/fixtures/claude_loopback_gateway_v1/stream.sse"
UPSTREAM_AUTHORIZATION = "Up5_x"


class _UpstreamState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list[dict[str, object]] = []

    def add(self, value: dict[str, object]) -> None:
        with self.lock:
            self.calls.append(value)

    def reset(self) -> None:
        with self.lock:
            self.calls.clear()


UPSTREAM = _UpstreamState()


class _FakeUpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_: object) -> None:
        return

    def do_GET(self) -> None:
        behavior = self.headers.get("x-test-upstream-behavior", "catalog")
        UPSTREAM.add({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": b""})
        if behavior == "catalog-error":
            payload = b'{"type":"error","error":{"type":"api_error","message":"catalog unavailable"}}'
            self.send_response_only(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers(); self.wfile.write(payload); return
        if behavior == "catalog-large":
            payload = b"L" * 256
            self.send_response_only(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers(); self.wfile.write(payload); return
        if behavior == "catalog-reflect-header":
            payload = b"{}"
            self.send_response_only(200)
            self.send_header("X-Catalog-Reflection", UPSTREAM_AUTHORIZATION)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers(); self.wfile.write(payload); return
        if behavior == "catalog-reflect-body":
            payload = b"models-" + UPSTREAM_AUTHORIZATION.encode() + b"-tail"
            self.send_response_only(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers(); self.wfile.write(payload); return
        if behavior == "catalog-slow":
            self.send_response_only(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                self.wfile.write(b"1\r\nx\r\n"); self.wfile.flush()
                time.sleep(1.0)
                self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        payload = b'{"data":[{"id":"claude-fixture","type":"model"}],"has_more":false}'
        self.send_response_only(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Catalog", "fixture")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers(); self.wfile.write(payload)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        behavior = self.headers.get("x-test-upstream-behavior", "echo")
        UPSTREAM.add({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        if behavior in {"te-cl", "te-duplicate", "te-comma", "te-gzip", "te-gzip-chunked"}:
            headers = {
                "te-cl": b"Transfer-Encoding: chunked\r\nContent-Length: 1\r\n",
                "te-duplicate": b"Transfer-Encoding: chunked\r\nTransfer-Encoding: chunked\r\n",
                "te-comma": b"Transfer-Encoding: chunked, chunked\r\n",
                "te-gzip": b"Transfer-Encoding: gzip\r\n",
                "te-gzip-chunked": b"Transfer-Encoding: gzip, chunked\r\n",
            }[behavior]
            self.connection.sendall(
                b"HTTP/1.1 200 OK\r\n" + headers + b"\r\n1\r\nx\r\n0\r\n\r\n"
            )
            return
        if behavior == "bad-header-fold":
            self.connection.sendall(
                b"HTTP/1.1 200 OK\r\nX-Bad: visible\r\n folded\r\nContent-Length: 1\r\n\r\nx"
            )
            return
        if behavior == "bad-header-control":
            self.connection.sendall(
                b"HTTP/1.1 200 OK\r\nX-Bad: a\x00b\r\nContent-Length: 1\r\n\r\nx"
            )
            return
        if behavior == "disconnect":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if behavior == "redirect":
            self.send_response_only(302)
            self.send_header("Location", "http://example.invalid/forbidden")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if behavior == "stream":
            chunks = [b'event: message\ndata: {"delta":"alpha"}\n\n', b'event: message\ndata: {"delta":"beta"}\n\n']
            self.send_response_only(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
                self.wfile.flush()
                time.sleep(0.01)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return
        if behavior == "large-stream":
            self.send_response_only(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            chunk = b"x" * 65_536
            try:
                for _ in range(64):
                    self.wfile.write(b"10000\r\n" + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if behavior == "hop-response":
            payload = b"hop-ok"
            self.send_response_only(200)
            self.send_header("Connection", "x-upstream-hop")
            self.send_header("Proxy-Connection", "x-proxy-hop")
            self.send_header("X-Upstream-Hop", "remove-me")
            self.send_header("X-Proxy-Hop", "remove-me-too")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if behavior == "premature":
            self.send_response_only(200)
            self.send_header("Content-Length", "20")
            self.end_headers()
            self.wfile.write(b"short")
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if behavior in {"post-commit", "slow-drip"}:
            self.send_response_only(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                self.wfile.write(b"1\r\nx\r\n")
                self.wfile.flush()
                if behavior == "post-commit":
                    time.sleep(1.0)
                else:
                    for byte in b"abcdef":
                        time.sleep(0.08)
                        self.wfile.write(b"1\r\n" + bytes([byte]) + b"\r\n")
                        self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if behavior == "reflect-header":
            payload = b"safe-header-body"
            self.send_response_only(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("X-Upstream-Reflection", "prefix-" + UPSTREAM_AUTHORIZATION + "-suffix")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if behavior == "reflect-one-char":
            payload = b"abZcd"
            self.send_response_only(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if behavior in {"reflect-body", "reflect-body-split"}:
            payload = b"safe-prefix-" + UPSTREAM_AUTHORIZATION.encode() + b"-unsafe-suffix"
            self.send_response_only(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if behavior == "upstream-502":
            payload = b'{"type":"error","error":{"type":"api_error","message":"upstream fixture"}}'
            self.send_response_only(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if behavior == "short-cut":
            payload = b"short"
        else:
            payload = b"z" * 256 if behavior == "cut" else body
        self.send_response_only(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "upstream_secret=must_not_escape")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstreamHandler)
        cls.upstream.daemon_threads = True
        cls.upstream_thread = threading.Thread(target=cls.upstream.serve_forever, daemon=True)
        cls.upstream_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.upstream.shutdown()
        cls.upstream.server_close()
        cls.upstream_thread.join(timeout=2)

    def setUp(self) -> None:
        UPSTREAM.reset()
        self.temp = tempfile.TemporaryDirectory(dir=CANDIDATE)
        self.addCleanup(self.temp.cleanup)
        self.receipt_path = Path(self.temp.name) / "receipts.jsonl"
        self.logical_targets: list[tuple[str, int, float]] = []

    def connection_factory(self, host: str, port: int, timeout: float) -> http.client.HTTPConnection:
        self.logical_targets.append((host, port, timeout))
        fake_host, fake_port = self.upstream.server_address
        return http.client.HTTPConnection(fake_host, fake_port, timeout=timeout)

    def gateway(self, **overrides: object) -> LoopbackGateway:
        config = GatewayConfig(**overrides)
        return LoopbackGateway(
            config,
            ReceiptLedger(self.receipt_path),
            upstream_authorization=lambda: UPSTREAM_AUTHORIZATION, token_factory=lambda _: "T" * 43,
            connection_factory=self.connection_factory,
        )

    @staticmethod
    def expected_binding(prefix: str = "fixture") -> ExpectedPreForwardBinding:
        return ExpectedPreForwardBinding(
            run_binding_hash=hashlib.sha256((prefix + ":run").encode()).hexdigest(),
            slot_binding_hash=hashlib.sha256((prefix + ":slot").encode()).hexdigest(),
            attempt_binding_hash=hashlib.sha256((prefix + ":attempt").encode()).hexdigest(),
            operation_binding_hash=hashlib.sha256((prefix + ":operation").encode()).hexdigest(),
            prompt_binding_hash=hashlib.sha256((prefix + ":prompt").encode()).hexdigest(),
        )

    @staticmethod
    def call(gateway: LoopbackGateway, *, method: str = "POST", path: str = "/v1/messages",
             body: bytes = b'{"model":"fixture"}', token: str | None = None,
             headers: dict[str, str] | None = None) -> tuple[int, list[tuple[str, str]], bytes]:
        connection = http.client.HTTPConnection(*gateway.address, timeout=3)
        all_headers = dict(headers or {})
        if token is not None:
            all_headers["Authorization"] = f"Bearer {token}"
        connection.request(method, path, body=body if method == "POST" else None, headers=all_headers)
        response = connection.getresponse()
        payload = response.read()
        result = response.status, response.getheaders(), payload
        connection.close()
        return result

    def wait_for_receipts(self, minimum: int = 1, timeout: float = 1.0) -> list[dict[str, object]]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.receipt_path.exists():
                try:
                    records = ReceiptLedger.validate(self.receipt_path)
                except ReceiptIntegrityError:
                    records = []
                if len(records) >= minimum:
                    return records
            time.sleep(0.005)
        return self.records()

    def records(self) -> list[dict[str, object]]:
        return ReceiptLedger.validate(self.receipt_path)

    def test_exact_route_auth_and_request_response_fidelity(self) -> None:
        body = b'{"model":"fixture","stream":false}'
        with self.gateway() as gateway:
            status, headers, payload = self.call(
                gateway, body=body, token=gateway.bearer_token,
                headers={"Content-Type": "application/json", "x-api-key": "synthetic-api-secret", "Cookie": "session=synthetic-cookie"},
            )
        self.assertEqual((status, payload), (200, body))
        downstream_names = {key.lower() for key, _ in headers}
        self.assertNotIn("set-cookie", downstream_names)
        self.assertNotIn("authorization", downstream_names)
        self.assertEqual(len(UPSTREAM.calls), 1)
        call = UPSTREAM.calls[0]
        self.assertEqual(call["path"], "/v1/messages")
        self.assertEqual(call["body"], body)
        upstream_headers = call["headers"]
        self.assertEqual(upstream_headers["authorization"], "Bearer " + UPSTREAM_AUTHORIZATION)
        self.assertNotEqual(upstream_headers["authorization"], "Bearer " + "T" * 43)
        self.assertNotIn("x-api-key", upstream_headers)
        self.assertNotIn("cookie", upstream_headers)
        self.assertEqual(upstream_headers["host"], "127.0.0.1:8790")
        self.assertEqual(self.logical_targets, [("127.0.0.1", 8790, 2.0)])
        record = self.records()[0]
        self.assertEqual(record["states"], ["arrived", "authenticated", "forwarding", "completed"])
        self.assertEqual((record["arrival_count"], record["upstream_count"]), (1, 1))

    def test_upstream_authorization_required_validated_and_cleared_without_echo(self) -> None:
        with self.assertRaises(TypeError):
            LoopbackGateway(GatewayConfig(), ReceiptLedger(self.receipt_path))
        for invalid in ("", "bad token", "bad:token", "x" * 4097, "Bearer x"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError) as caught:
                LoopbackGateway(
                    GatewayConfig(), ReceiptLedger(self.receipt_path),
                    upstream_authorization=invalid,
                )
            self.assertEqual(str(caught.exception), "upstream authorization is invalid")
            if invalid:
                self.assertNotIn(invalid, str(caught.exception))

        before_threads = {thread.ident for thread in threading.enumerate()}
        gateway = LoopbackGateway(
            GatewayConfig(), ReceiptLedger(self.receipt_path),
            upstream_authorization=lambda: "bad callable credential",
        )
        with self.assertRaises(ValueError) as caught:
            gateway.start()
        self.assertNotIn("bad callable credential", str(caught.exception))
        self.assertIsNone(gateway._upstream_authorization)
        self.assertFalse(self.receipt_path.exists())
        self.assertEqual(before_threads, {thread.ident for thread in threading.enumerate()})

    def test_resolver_exception_is_fixed_non_echoing_and_has_no_cause(self) -> None:
        def failing_resolver() -> str:
            raise RuntimeError("resolver leaked " + UPSTREAM_AUTHORIZATION)
        gateway = LoopbackGateway(
            GatewayConfig(), ReceiptLedger(self.receipt_path),
            upstream_authorization=failing_resolver,
        )
        with self.assertRaises(ValueError) as caught:
            gateway.start()
        self.assertEqual(str(caught.exception), "upstream authorization resolution failed")
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(UPSTREAM_AUTHORIZATION, str(caught.exception))
        self.assertIsNone(gateway._upstream_authorization)
        self.assertFalse(self.receipt_path.exists())

    def test_direct_credential_is_single_start_and_callable_is_restartable(self) -> None:
        self.assertEqual(len(UPSTREAM_AUTHORIZATION), 5)
        direct = LoopbackGateway(
            GatewayConfig(), ReceiptLedger(self.receipt_path),
            upstream_authorization=UPSTREAM_AUTHORIZATION,
            connection_factory=self.connection_factory,
        )
        direct.start()
        direct.close()
        self.assertIsNone(direct._upstream_authorization)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            direct.start()

        failed_path = Path(self.temp.name) / "direct-failed.jsonl"
        def fail_server(_: LoopbackGateway):
            raise OSError("synthetic start failure")
        failed = LoopbackGateway(
            GatewayConfig(), ReceiptLedger(failed_path),
            upstream_authorization=UPSTREAM_AUTHORIZATION,
            server_factory=fail_server,
        )
        with self.assertRaises(OSError):
            failed.start()
        self.assertIsNone(failed._upstream_authorization)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            failed.start()

        resolutions = 0
        def resolver() -> str:
            nonlocal resolutions
            resolutions += 1
            return UPSTREAM_AUTHORIZATION
        restartable_path = Path(self.temp.name) / "restartable.jsonl"
        restartable = LoopbackGateway(
            GatewayConfig(), ReceiptLedger(restartable_path),
            upstream_authorization=resolver,
            connection_factory=self.connection_factory,
        )
        restartable.start(); restartable.close()
        restartable.start(); restartable.close()
        self.assertEqual(resolutions, 2)
        self.assertIsNone(restartable._upstream_authorization)

    def test_exact_upstream_credential_reflection_blocked_in_header_body_and_split(self) -> None:
        gateway = self.gateway(chunk_bytes=7)
        gateway.start()
        status, headers, payload = self.call(
            gateway, token=gateway.bearer_token,
            headers={"x-test-upstream-behavior": "reflect-header"},
        )
        self.assertEqual((status, payload), (502, b"upstream credential reflection blocked"))
        self.assertNotIn(UPSTREAM_AUTHORIZATION.encode(), payload)
        self.assertNotIn("x-upstream-reflection", {name.lower() for name, _ in headers})

        partials: list[bytes] = []
        errors: list[str] = []
        for behavior in ("reflect-body", "reflect-body-split"):
            connection = http.client.HTTPConnection(*gateway.address, timeout=2)
            connection.request("POST", "/v1/messages", body=b"{}", headers={
                "Authorization": f"Bearer {gateway.bearer_token}",
                "x-test-upstream-behavior": behavior,
            })
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            with self.assertRaises(http.client.IncompleteRead) as caught:
                response.read()
            partials.append(caught.exception.partial)
            errors.append(str(caught.exception))
            connection.close()
        gateway.close()

        self.assertEqual(len(UPSTREAM.calls), 3)
        self.assertTrue(all(call["headers"]["authorization"] == "Bearer " + UPSTREAM_AUTHORIZATION for call in UPSTREAM.calls))
        for partial in partials:
            self.assertNotIn(UPSTREAM_AUTHORIZATION.encode(), partial)
            self.assertEqual(partial, b"safe-prefix-")
        self.assertTrue(all(UPSTREAM_AUTHORIZATION not in error for error in errors))
        records = self.records()
        self.assertEqual([record["states"][-1] for record in records], [
            "credential_reflection", "credential_reflection", "credential_reflection",
        ])
        self.assertEqual(records[0]["http_status"], 502)
        self.assertEqual(records[0]["response_bytes"], 0)
        self.assertEqual([record["http_status"] for record in records[1:]], [200, 200])
        raw = self.receipt_path.read_bytes()
        self.assertNotIn(UPSTREAM_AUTHORIZATION.encode(), raw)
        self.assertNotIn(hashlib.sha256(UPSTREAM_AUTHORIZATION.encode()).hexdigest().encode(), raw)

    def test_equal_child_and_upstream_credentials_rejected_before_socket(self) -> None:
        shared = "Q" * 43
        before_threads = {thread.ident for thread in threading.enumerate()}
        for source in (shared, lambda: shared):
            with self.subTest(source_type=type(source).__name__):
                gateway = LoopbackGateway(
                    GatewayConfig(), ReceiptLedger(self.receipt_path),
                    upstream_authorization=source,
                    token_factory=lambda _: shared,
                    connection_factory=lambda *_: self.fail("upstream connection must not be created"),
                    server_factory=lambda *_: self.fail("server must not be created"),
                )
                with self.assertRaises(ValueError) as caught:
                    gateway.start()
                self.assertEqual(
                    str(caught.exception),
                    "upstream authorization must differ from gateway client bearer",
                )
                self.assertNotIn(shared, str(caught.exception))
                self.assertIsNone(gateway._upstream_authorization)
                self.assertFalse(self.receipt_path.exists())
        self.assertEqual(before_threads, {thread.ident for thread in threading.enumerate()})

    def test_one_character_scanner_streaming_and_reflection_guard(self) -> None:
        scanner = gateway_module._ExactCredentialScanner("Z")
        for chunk in (b"abc", b"def", b"ghi"):
            emitted, reflected = scanner.feed(chunk)
            self.assertEqual(emitted, chunk)
            self.assertFalse(reflected)
            self.assertEqual(scanner._pending, b"")
            self.assertLessEqual(len(scanner._pending), max(0, 1 - 1))
        emitted, reflected = scanner.feed(b"12Z34")
        self.assertEqual(emitted, b"12")
        self.assertTrue(reflected)
        self.assertEqual(scanner._pending, b"")

        stream_path = Path(self.temp.name) / "one-char-stream.jsonl"
        streaming = LoopbackGateway(
            GatewayConfig(chunk_bytes=1), ReceiptLedger(stream_path),
            upstream_authorization=lambda: "Z",
            token_factory=lambda _: "T" * 43,
            connection_factory=self.connection_factory,
        )
        streaming.start()
        status, _, payload = self.call(
            streaming, token=streaming.bearer_token,
            headers={"x-test-upstream-behavior": "stream"},
        )
        streaming.close()
        self.assertEqual((status, payload), (200, STREAM_FIXTURE.read_bytes()))

        reflected_path = Path(self.temp.name) / "one-char-reflected.jsonl"
        reflected_gateway = LoopbackGateway(
            GatewayConfig(chunk_bytes=1), ReceiptLedger(reflected_path),
            upstream_authorization=lambda: "Z",
            token_factory=lambda _: "T" * 43,
            connection_factory=self.connection_factory,
        )
        reflected_gateway.start()
        connection = http.client.HTTPConnection(*reflected_gateway.address, timeout=2)
        connection.request("POST", "/v1/messages", body=b"{}", headers={
            "Authorization": f"Bearer {reflected_gateway.bearer_token}",
            "x-test-upstream-behavior": "reflect-one-char",
        })
        response = connection.getresponse()
        with self.assertRaises(http.client.IncompleteRead) as caught:
            response.read()
        connection.close()
        reflected_gateway.close()
        self.assertEqual(caught.exception.partial, b"ab")
        self.assertNotIn(b"Z", caught.exception.partial)
        record = ReceiptLedger.validate(reflected_path)[0]
        self.assertEqual(record["states"][-1], "credential_reflection")
        self.assertEqual(record["response_bytes"], 2)

    def test_models_get_auth_separation_fidelity_and_receipt(self) -> None:
        expected = b'{"data":[{"id":"claude-fixture","type":"model"}],"has_more":false}'
        with self.gateway() as gateway:
            child = gateway.bearer_token
            status, headers, payload = self.call(
                gateway, method="GET", path="/v1/models", token=child,
                headers={"x-api-key": "child-key", "Cookie": "child-cookie"},
            )
        self.assertEqual((status, payload), (200, expected))
        returned = {name.lower(): value for name, value in headers}
        self.assertEqual(returned["x-catalog"], "fixture")
        self.assertNotIn("authorization", returned)
        self.assertEqual(len(UPSTREAM.calls), 1)
        call = UPSTREAM.calls[0]
        self.assertEqual((call["path"], call["body"]), ("/v1/models", b""))
        self.assertEqual(call["headers"]["authorization"], "Bearer " + UPSTREAM_AUTHORIZATION)
        self.assertNotEqual(call["headers"]["authorization"], "Bearer " + child)
        self.assertNotIn("x-api-key", call["headers"])
        self.assertNotIn("cookie", call["headers"])
        record = self.records()[0]
        self.assertEqual((record["method"], record["path"], record["mode"]), ("GET", "/v1/models", "pass_through"))
        self.assertEqual(record["states"], ["arrived", "authenticated", "forwarding", "completed"])
        self.assertEqual((record["request_bytes"], record["upstream_attempts"], record["upstream_count"]), (0, 1, 1))
        self.assertIsNone(record["pre_forward_attestation"])

    def test_models_get_unauthorized_has_zero_upstream_and_no_proof(self) -> None:
        with self.gateway() as gateway:
            status, _, _ = self.call(gateway, method="GET", path="/v1/models")
        self.assertEqual(status, 401)
        self.assertEqual(UPSTREAM.calls, [])
        record = self.records()[0]
        self.assertEqual(record["states"], ["arrived", "auth_rejected"])
        self.assertEqual((record["upstream_attempts"], record["upstream_count"]), (0, 0))
        self.assertIsNone(record["pre_forward_attestation"])

    def test_models_get_then_post_preserves_receipt_order_and_counts(self) -> None:
        with self.gateway() as gateway:
            self.assertEqual(self.call(gateway, method="GET", path="/v1/models", token=gateway.bearer_token)[0], 200)
            self.assertEqual(self.call(gateway, token=gateway.bearer_token)[0], 200)
        records = self.wait_for_receipts(2)
        self.assertEqual([(r["sequence"], r["method"], r["path"]) for r in records], [
            (1, "GET", "/v1/models"), (2, "POST", "/v1/messages"),
        ])
        self.assertEqual([r["arrival_count"] for r in records], [1, 2])
        self.assertEqual([r["upstream_count"] for r in records], [1, 2])
        self.assertEqual([r["upstream_attempts"] for r in records], [1, 1])
        self.assertEqual(len(UPSTREAM.calls), 2)

    def test_models_get_forces_full_pass_through_under_message_fault_modes(self) -> None:
        expected = b'{"data":[{"id":"claude-fixture","type":"model"}],"has_more":false}'
        gateway = self.gateway(mode="forward_then_cut", cut_after_bytes=5)
        gateway.start()
        status, _, payload = self.call(
            gateway, method="GET", path="/v1/models", token=gateway.bearer_token
        )
        self.assertEqual((status, payload), (200, expected))

        connection = http.client.HTTPConnection(*gateway.address, timeout=2)
        connection.request("POST", "/v1/messages", body=b'{"message":"cut-me"}', headers={
            "Authorization": f"Bearer {gateway.bearer_token}",
        })
        response = connection.getresponse()
        with self.assertRaises(http.client.IncompleteRead) as caught:
            response.read()
        connection.close(); gateway.close()
        self.assertEqual(caught.exception.partial, b'{"mes')
        records = self.wait_for_receipts(2)
        self.assertEqual(records[0]["states"][-1], "completed")
        self.assertEqual((records[0]["mode"], records[0]["response_bytes"]), ("pass_through", len(expected)))
        self.assertEqual(records[1]["states"][-1], "forward_cut")
        self.assertEqual(records[1]["mode"], "forward_then_cut")
        self.assertEqual([r["arrival_count"] for r in records], [1, 2])
        self.assertEqual([r["upstream_count"] for r in records], [1, 2])

        self.receipt_path.unlink(); UPSTREAM.reset()
        with self.gateway(mode="synthetic_first", synthetic_status=503, synthetic_attempts=1) as gateway:
            status, _, payload = self.call(
                gateway, method="GET", path="/v1/models", token=gateway.bearer_token
            )
            self.assertEqual((status, payload), (200, expected))
            post = self.call(gateway, token=gateway.bearer_token)
        self.assertEqual(post[0], 503)
        records = self.wait_for_receipts(2)
        self.assertEqual(records[0]["states"][-1], "completed")
        self.assertEqual(records[0]["mode"], "pass_through")
        self.assertEqual(records[1]["states"][-1], "synthetic_fault")
        self.assertEqual(records[1]["mode"], "synthetic_first")
        self.assertEqual([r["arrival_count"] for r in records], [1, 2])
        self.assertEqual([r["upstream_count"] for r in records], [1, 1])
        self.assertEqual([r["upstream_attempts"] for r in records], [1, 0])

    def test_models_get_forwarded_error_and_limits(self) -> None:
        with self.gateway() as gateway:
            status, _, payload = self.call(
                gateway, method="GET", path="/v1/models", token=gateway.bearer_token,
                headers={"x-test-upstream-behavior": "catalog-error"},
            )
        self.assertEqual(status, 503)
        self.assertIn(b"catalog unavailable", payload)
        record = self.records()[0]
        self.assertEqual(record["states"][-1], "completed")
        self.assertEqual((record["http_status"], record["upstream_attempts"]), (503, 1))
        self.assertIsNone(record["pre_forward_attestation"])

        self.receipt_path.unlink(); UPSTREAM.reset()
        with self.gateway(max_response_bytes=20, cut_after_bytes=10) as gateway:
            status, _, payload = self.call(
                gateway, method="GET", path="/v1/models", token=gateway.bearer_token,
                headers={"x-test-upstream-behavior": "catalog-large"},
            )
        self.assertEqual((status, payload), (502, b"upstream response too large"))
        self.assertEqual(self.records()[0]["states"][-1], "response_rejected")

        self.receipt_path.unlink(); UPSTREAM.reset()
        with self.gateway(max_header_bytes=140) as gateway:
            status, _, _ = self.call(
                gateway, method="GET", path="/v1/models", token=gateway.bearer_token,
                headers={"X-Large": "a" * 200},
            )
        self.assertEqual(status, 431)
        self.assertEqual(UPSTREAM.calls, [])
        self.assertEqual(self.records()[0]["states"][-1], "headers_rejected")

    def test_models_get_reflection_and_total_response_deadline(self) -> None:
        with self.gateway(chunk_bytes=2) as gateway:
            status, headers, payload = self.call(
                gateway, method="GET", path="/v1/models", token=gateway.bearer_token,
                headers={"x-test-upstream-behavior": "catalog-reflect-header"},
            )
        self.assertEqual((status, payload), (502, b"upstream credential reflection blocked"))
        self.assertNotIn("x-catalog-reflection", {name.lower() for name, _ in headers})
        self.assertEqual(self.records()[0]["states"][-1], "credential_reflection")

        self.receipt_path.unlink(); UPSTREAM.reset()
        gateway = self.gateway(chunk_bytes=2)
        gateway.start()
        connection = http.client.HTTPConnection(*gateway.address, timeout=2)
        connection.request("GET", "/v1/models", headers={
            "Authorization": f"Bearer {gateway.bearer_token}",
            "x-test-upstream-behavior": "catalog-reflect-body",
        })
        response = connection.getresponse()
        with self.assertRaises(http.client.IncompleteRead) as caught:
            response.read()
        connection.close(); gateway.close()
        self.assertNotIn(UPSTREAM_AUTHORIZATION.encode(), caught.exception.partial)
        self.assertEqual(self.records()[0]["states"][-1], "credential_reflection")

        self.receipt_path.unlink(); UPSTREAM.reset()
        gateway = self.gateway(response_timeout=0.10, chunk_bytes=1)
        gateway.start()
        connection = http.client.HTTPConnection(*gateway.address, timeout=2)
        connection.request("GET", "/v1/models", headers={
            "Authorization": f"Bearer {gateway.bearer_token}",
            "x-test-upstream-behavior": "catalog-slow",
        })
        response = connection.getresponse()
        try:
            response.read()
        except (http.client.IncompleteRead, ConnectionResetError):
            pass
        connection.close(); gateway.close()
        record = self.records()[0]
        self.assertEqual(record["states"][-1], "post_commit_error")
        self.assertEqual((record["method"], record["path"], record["request_bytes"]), ("GET", "/v1/models", 0))
        self.assertIsNone(record["pre_forward_attestation"])

    def test_routing_preflight_and_methods_are_closed(self) -> None:
        with self.gateway() as gateway:
            self.assertEqual(self.call(gateway, method="OPTIONS", body=b"")[0], 204)
            self.assertEqual(self.call(gateway, method="OPTIONS", path="/v1/models", body=b"")[0], 404)
            self.assertEqual(self.call(gateway, method="GET", token=gateway.bearer_token)[0], 405)
            self.assertEqual(self.call(gateway, path="/v1/messages?x=1", token=gateway.bearer_token)[0], 404)
            self.assertEqual(self.call(gateway, path="/health", token=gateway.bearer_token)[0], 404)
        self.assertEqual(UPSTREAM.calls, [])
        self.assertFalse(self.receipt_path.exists())

    def test_rejected_auth_and_oversize_never_reach_upstream(self) -> None:
        with self.gateway(max_request_bytes=8) as gateway:
            self.assertEqual(self.call(gateway, token="wrong-token")[0], 401)
            self.assertEqual(self.call(gateway, token=gateway.bearer_token, body=b"123456789")[0], 413)
        self.assertEqual(UPSTREAM.calls, [])
        records = self.records()
        self.assertEqual(records[0]["states"], ["arrived", "auth_rejected"])
        self.assertEqual(records[1]["states"][-1], "request_rejected")
        self.assertEqual(records[1]["upstream_count"], 0)

    def test_credentials_and_body_are_absent_from_receipt_bytes(self) -> None:
        body_secret = b'{"prompt":"synthetic-body-secret"}'
        with self.gateway() as gateway:
            self.call(
                gateway, token=gateway.bearer_token, body=body_secret,
                headers={"x-api-key": "synthetic-header-secret", "Cookie": "synthetic-cookie-secret"},
            )
        raw = self.receipt_path.read_bytes()
        for secret in (
            gateway.bearer_token if False else "T" * 43,
            UPSTREAM_AUTHORIZATION,
            hashlib.sha256(UPSTREAM_AUTHORIZATION.encode()).hexdigest(),
            "synthetic-body-secret", "synthetic-header-secret", "synthetic-cookie-secret",
        ):
            self.assertNotIn(secret.encode(), raw)
        candidate_source = "\n".join(
            path.read_text(encoding="utf-8") for path in CANDIDATE.glob("*.py")
        )
        self.assertNotIn(UPSTREAM_AUTHORIZATION, candidate_source)
        self.assertNotIn(hashlib.sha256(UPSTREAM_AUTHORIZATION.encode()).hexdigest(), candidate_source)
        record = self.records()[0]
        self.assertEqual(set(record), {
            "schema_version", "sequence", "timestamp_ns", "method", "path", "mode", "states",
            "http_status", "arrival_count", "upstream_count", "duplicate_attempt", "attempt_number",
            "upstream_attempts", "request_bytes", "response_bytes", "streaming",
            "pre_forward_attestation", "prev_hash", "entry_hash",
        })

    def test_sse_chunk_fidelity_and_stream_receipt(self) -> None:
        expected = STREAM_FIXTURE.read_bytes()
        with self.gateway(chunk_bytes=7) as gateway:
            status, _, payload = self.call(
                gateway, token=gateway.bearer_token,
                headers={"x-test-upstream-behavior": "stream"},
            )
        self.assertEqual((status, payload), (200, expected))
        record = self.records()[0]
        self.assertTrue(record["streaming"])
        self.assertEqual(record["response_bytes"], len(expected))
        self.assertEqual(record["states"][-1], "completed")

    def test_synthetic_first_then_duplicate_forwards_once(self) -> None:
        with self.gateway(mode="synthetic_first", synthetic_status=503, synthetic_attempts=1) as gateway:
            headers = {"x-request-id": "same-safe-attempt"}
            first = self.call(gateway, token=gateway.bearer_token, headers=headers)
            second = self.call(gateway, token=gateway.bearer_token, headers=headers)
        self.assertEqual((first[0], second[0]), (503, 200))
        self.assertEqual(len(UPSTREAM.calls), 1)
        first_record, second_record = self.records()
        self.assertEqual(first_record["states"][-1], "synthetic_fault")
        self.assertEqual(first_record["upstream_count"], 0)
        self.assertTrue(second_record["duplicate_attempt"])
        self.assertEqual(second_record["attempt_number"], 2)
        self.assertEqual((second_record["arrival_count"], second_record["upstream_count"]), (2, 1))
        self.assertNotIn(b"same-safe-attempt", self.receipt_path.read_bytes())

    def test_response_size_bound_rejects_known_oversize_before_streaming(self) -> None:
        with self.gateway(max_response_bytes=20, cut_after_bytes=10) as gateway:
            status, _, payload = self.call(
                gateway, token=gateway.bearer_token,
                headers={"x-test-upstream-behavior": "cut"},
            )
        self.assertEqual((status, payload), (502, b"upstream response too large"))
        record = self.records()[0]
        self.assertEqual(record["states"][-1], "response_rejected")
        self.assertEqual(record["response_bytes"], 0)

    def test_forward_then_cut_is_one_attempt_and_incomplete(self) -> None:
        with self.gateway(mode="forward_then_cut", cut_after_bytes=19) as gateway:
            connection = http.client.HTTPConnection(*gateway.address, timeout=3)
            connection.request("POST", "/v1/messages", body=b"{}", headers={
                "Authorization": f"Bearer {gateway.bearer_token}",
                "x-test-upstream-behavior": "cut",
            })
            response = connection.getresponse()
            with self.assertRaises(http.client.IncompleteRead) as caught:
                response.read()
            connection.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(caught.exception.partial, b"z" * 19)
        self.assertEqual(len(UPSTREAM.calls), 1)
        record = self.records()[0]
        self.assertEqual(record["states"][-1], "forward_cut")
        self.assertEqual(record["response_bytes"], 19)

    def test_redirect_is_observed_not_followed_and_disconnect_has_no_retry(self) -> None:
        with self.gateway() as gateway:
            redirect = self.call(gateway, token=gateway.bearer_token, headers={"x-test-upstream-behavior": "redirect"})
            disconnected = self.call(gateway, token=gateway.bearer_token, headers={"x-test-upstream-behavior": "disconnect"})
        self.assertEqual(redirect[0], 302)
        self.assertEqual(disconnected[0], 502)
        self.assertEqual(len(UPSTREAM.calls), 2)
        self.assertEqual(self.records()[1]["states"][-1], "upstream_error")

    def test_client_cancellation_records_state_and_server_remains_usable(self) -> None:
        with self.gateway(chunk_bytes=4096) as gateway:
            sock = socket.create_connection(gateway.address, timeout=2)
            request = (
                f"POST /v1/messages HTTP/1.1\r\nHost: {gateway.address[0]}\r\n"
                f"Authorization: Bearer {gateway.bearer_token}\r\n"
                "x-test-upstream-behavior: large-stream\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
            ).encode("ascii")
            sock.sendall(request)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            sock.close()
            deadline = time.time() + 3
            while (not self.receipt_path.exists() or not self.receipt_path.read_bytes()) and time.time() < deadline:
                time.sleep(0.01)
            status = self.call(gateway, token=gateway.bearer_token)[0]
        self.assertEqual(status, 200)
        records = self.records()
        self.assertIn("client_cancelled", records[0]["states"])
        self.assertEqual(records[0]["http_status"], 200)
        self.assertGreaterEqual(records[0]["response_bytes"], 0)
        self.assertEqual(records[1]["states"][-1], "completed")

    def test_receipt_chain_detects_modification_truncation_and_reordering(self) -> None:
        with self.gateway() as gateway:
            self.call(gateway, token=gateway.bearer_token)
            self.call(gateway, token=gateway.bearer_token)
        original = self.receipt_path.read_bytes()
        lines = original.splitlines(keepends=True)
        self.receipt_path.write_bytes(original.replace(b'"http_status":200', b'"http_status":201', 1))
        with self.assertRaises(ReceiptIntegrityError):
            ReceiptLedger.validate(self.receipt_path)
        self.receipt_path.write_bytes(lines[1] + lines[0])
        with self.assertRaises(ReceiptIntegrityError):
            ReceiptLedger.validate(self.receipt_path)
        self.receipt_path.write_bytes(original[:-5])
        with self.assertRaises(ReceiptIntegrityError):
            ReceiptLedger.validate(self.receipt_path)

    def test_constructor_import_cleanup_and_token_rotation_have_no_hidden_effects(self) -> None:
        before_threads = {thread.ident for thread in threading.enumerate()}
        ledger = ReceiptLedger(self.receipt_path)
        tokens = iter(("A" * 43, "B" * 43))
        gateway = LoopbackGateway(
            GatewayConfig(), ledger, upstream_authorization=lambda: UPSTREAM_AUTHORIZATION, token_factory=lambda _: next(tokens),
            connection_factory=self.connection_factory,
        )
        self.assertFalse(self.receipt_path.exists())
        self.assertEqual(before_threads, {thread.ident for thread in threading.enumerate()})
        with mock.patch("socket.getaddrinfo", side_effect=AssertionError("DNS must not be used")):
            gateway.start()
            first_address = gateway.address
            first_token = gateway.bearer_token
            gateway.close()
            self.assertIsNone(gateway._upstream_authorization)
            gateway.start()
            second_token = gateway.bearer_token
            gateway.close()
            self.assertIsNone(gateway._upstream_authorization)
        self.assertEqual(first_address[0], "127.0.0.1")
        self.assertNotEqual(first_token, second_token)
        self.assertFalse(self.receipt_path.exists())
        with self.assertRaises(OSError):
            socket.create_connection(first_address, timeout=0.1)
        source = (CANDIDATE / "gateway.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "serve_forever" for node in tree.body))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertTrue(imports.isdisjoint({"requests", "anthropic", "httpx", "urllib3"}))
        self.assertNotIn(UPSTREAM_AUTHORIZATION, source)
        self.assertNotIn(hashlib.sha256(UPSTREAM_AUTHORIZATION.encode()).hexdigest(), source)
        self.assertIn("class _GatewayServer(HTTPServer)", source)
        self.assertNotIn("ThreadingHTTPServer", source)

    def test_default_upstream_connection_is_numeric_ipv4_without_dns(self) -> None:
        gateway = LoopbackGateway(
            GatewayConfig(), ReceiptLedger(self.receipt_path),
            upstream_authorization=lambda: UPSTREAM_AUTHORIZATION,
        )
        connection = gateway._connection_factory("127.0.0.1", 8790, 1.0)
        fake_socket = mock.Mock()
        with mock.patch("socket.getaddrinfo", side_effect=AssertionError("resolver called")), mock.patch(
            "socket.socket", return_value=fake_socket
        ) as socket_factory:
            connection.connect()
        socket_factory.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        fake_socket.connect.assert_called_once_with(("127.0.0.1", 8790))
        connection.close()

    @staticmethod
    def raw_exchange(gateway: LoopbackGateway, header_lines: list[str], body: bytes = b"") -> bytes:
        sock = socket.create_connection(gateway.address, timeout=2)
        request = (
            "POST /v1/messages HTTP/1.1\r\n"
            f"Host: {gateway.address[0]}\r\n"
            f"Authorization: Bearer {gateway.bearer_token}\r\n"
            + "\r\n".join(header_lines)
            + "\r\n\r\n"
        ).encode("ascii") + body
        sock.sendall(request)
        sock.settimeout(2)
        chunks = []
        while True:
            try:
                chunk = sock.recv(65536)
            except (ConnectionResetError, socket.timeout):
                break
            if not chunk:
                break
            chunks.append(chunk)
        sock.close()
        return b"".join(chunks)

    def test_raw_framing_rejects_duplicate_noncanonical_and_every_transfer_encoding(self) -> None:
        with self.gateway() as gateway:
            cases = [
                (["Content-Length: 2", "Content-Length: 2"], b"{}"),
                (["Content-Length: 02"], b"{}"),
                (["Content-Length: +2"], b"{}"),
                (["Content-Length: 2,2"], b"{}"),
                (["Content-Length: 2", "Transfer-Encoding: identity"], b"{}"),
                (["Content-Length: 2", "Transfer-Encoding: chunked"], b"{}"),
            ]
            for headers, body in cases:
                with self.subTest(headers=headers):
                    raw = self.raw_exchange(gateway, headers, body)
                    self.assertIn(b"HTTP/1.1 400", raw.split(b"\r\n", 1)[0])
        self.assertEqual(UPSTREAM.calls, [])
        self.assertTrue(all(record["states"][-1] == "request_rejected" for record in self.records()))

    def test_connection_nominated_and_proxy_connection_headers_are_stripped_both_directions(self) -> None:
        with self.gateway() as gateway:
            status, response_headers, payload = self.call(
                gateway, token=gateway.bearer_token,
                headers={
                    "Connection": "x-hop", "Proxy-Connection": "x-proxy-hop",
                    "X-Hop": "request-secret", "X-Proxy-Hop": "request-secret-2",
                    "x-test-upstream-behavior": "hop-response",
                },
            )
        self.assertEqual((status, payload), (200, b"hop-ok"))
        seen = UPSTREAM.calls[0]["headers"]
        for name in ("proxy-connection", "x-hop", "x-proxy-hop"):
            self.assertNotIn(name, seen)
        self.assertEqual(seen["connection"], "close")
        returned = {name.lower() for name, _ in response_headers}
        for name in ("proxy-connection", "x-upstream-hop", "x-proxy-hop"):
            self.assertNotIn(name, returned)
        self.assertEqual(dict(response_headers).get("Connection"), "close")

    def test_header_aggregate_bound_is_exact_post_parse_and_closes(self) -> None:
        with self.gateway(max_header_bytes=180) as gateway:
            raw = self.raw_exchange(gateway, ["X-Large: " + "a" * 300, "Content-Length: 2"], b"{}")
        self.assertIn(b"HTTP/1.1 431", raw)
        self.assertIn(b"Connection: close", raw)
        self.assertEqual(self.records()[0]["states"], ["arrived", "headers_rejected"])
        self.assertEqual(UPSTREAM.calls, [])

    def test_header_aggregate_bound_accepts_exact_edge_and_rejects_one_less(self) -> None:
        token = "T" * 43
        fields = [
            ("Host", "127.0.0.1"),
            ("Authorization", "Bearer " + token),
            ("X-Edge", "v"),
            ("Content-Length", "2"),
        ]
        exact = 2 + sum(len(name) + len(value) + 4 for name, value in fields)
        with self.gateway(max_header_bytes=exact) as gateway:
            raw = self.raw_exchange(gateway, ["X-Edge: v", "Content-Length: 2"], b"{}")
        self.assertIn(b"HTTP/1.1 200", raw)

        self.receipt_path.unlink()
        UPSTREAM.reset()
        with self.gateway(max_header_bytes=exact - 1) as gateway:
            raw = self.raw_exchange(gateway, ["X-Edge: v", "Content-Length: 2"], b"{}")
        self.assertIn(b"HTTP/1.1 431", raw)
        self.assertEqual(UPSTREAM.calls, [])

    def test_stalled_headers_and_slow_body_hit_absolute_deadlines_then_recover(self) -> None:
        with self.gateway(header_timeout=0.10, ingress_timeout=0.10) as gateway:
            stalled = socket.create_connection(gateway.address, timeout=1)
            stalled.sendall(b"POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\n")
            time.sleep(0.20)
            stalled.settimeout(1)
            self.assertEqual(stalled.recv(1), b"")
            stalled.close()
            self.assertFalse(self.receipt_path.exists())

            slow = socket.create_connection(gateway.address, timeout=1)
            request = (
                f"POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {gateway.bearer_token}\r\n"
                "Content-Length: 5\r\nConnection: close\r\n\r\nx"
            ).encode("ascii")
            slow.sendall(request)
            time.sleep(0.20)
            try:
                slow.recv(1024)
            except (ConnectionResetError, socket.timeout):
                pass
            slow.close()
            deadline = time.time() + 1
            while (not self.receipt_path.exists() or not self.receipt_path.read_bytes()) and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(self.call(gateway, token=gateway.bearer_token)[0], 200)
        records = self.records()
        self.assertEqual(records[0]["states"][-1], "request_incomplete")
        self.assertEqual(records[1]["states"][-1], "completed")

    def test_close_aborts_stalled_active_socket_within_bound(self) -> None:
        gateway = self.gateway(header_timeout=10.0, shutdown_timeout=0.5).start()
        stalled = socket.create_connection(gateway.address, timeout=1)
        stalled.sendall(b"POST /v1/messages HTTP/1.1\r\n")
        started = time.monotonic()
        gateway.close()
        elapsed = time.monotonic() - started
        stalled.close()
        self.assertLess(elapsed, 1.0)
        if self.receipt_path.exists():
            ReceiptLedger.validate(self.receipt_path)

    def test_response_deadline_is_monotonic_and_post_commit_receipt_is_truthful(self) -> None:
        with self.gateway(response_timeout=0.15, chunk_bytes=1) as gateway:
            connection = http.client.HTTPConnection(*gateway.address, timeout=2)
            connection.request("POST", "/v1/messages", body=b"{}", headers={
                "Authorization": f"Bearer {gateway.bearer_token}",
                "x-test-upstream-behavior": "slow-drip",
            })
            response = connection.getresponse()
            started = time.monotonic()
            try:
                response.read()
            except (http.client.IncompleteRead, ConnectionResetError):
                pass
            elapsed = time.monotonic() - started
            connection.close()
        self.assertLess(elapsed, 0.8)
        record = self.records()[0]
        self.assertEqual(record["http_status"], 200)
        self.assertEqual(record["states"][-1], "post_commit_error")
        # The exact-match scanner safely withholds token_length-1 overlap bytes;
        # this short drip times out before any payload byte is releasable.
        self.assertEqual(record["response_bytes"], 0)

    def test_fixed_length_premature_eof_and_short_cut_semantics(self) -> None:
        with self.gateway(chunk_bytes=2) as gateway:
            connection = http.client.HTTPConnection(*gateway.address, timeout=2)
            connection.request("POST", "/v1/messages", body=b"{}", headers={
                "Authorization": f"Bearer {gateway.bearer_token}",
                "x-test-upstream-behavior": "premature",
            })
            response = connection.getresponse()
            with self.assertRaises(http.client.IncompleteRead) as caught:
                response.read()
            connection.close()
        self.assertEqual(caught.exception.partial, b"short")
        record = self.records()[0]
        self.assertEqual(record["states"][-1], "upstream_premature_eof")
        self.assertEqual((record["http_status"], record["response_bytes"]), (200, 5))

        self.receipt_path.unlink()
        UPSTREAM.reset()
        with self.gateway(mode="forward_then_cut", cut_after_bytes=10) as gateway:
            status, _, payload = self.call(
                gateway, token=gateway.bearer_token,
                headers={"x-test-upstream-behavior": "short-cut"},
            )
        self.assertEqual((status, payload), (200, b"short"))
        self.assertEqual(self.records()[0]["states"][-1], "cut_not_reached")

    def test_receipt_counts_resume_across_restart_and_new_gateway(self) -> None:
        gateway = self.gateway()
        gateway.start()
        self.call(gateway, token=gateway.bearer_token)
        gateway.close()
        gateway.start()
        self.call(gateway, token=gateway.bearer_token)
        gateway.close()
        with self.gateway() as replacement:
            self.call(replacement, token=replacement.bearer_token)
        records = self.records()
        self.assertEqual([record["arrival_count"] for record in records], [1, 2, 3])
        self.assertEqual([record["upstream_count"] for record in records], [1, 2, 3])

    def test_threat_model_exactly_closes_one_process_candidate_claims(self) -> None:
        expected = {
            "schema_version": "claude-loopback-threat-model-v1",
            "classification": "candidate_only_one_process",
            "protects_against": (
                "untrusted_http_callers",
                "serialized_receipt_or_proof_forgery",
                "copied_public_mappings_or_verifier_values",
                "non_owner_integration_callers",
            ),
            "trusts": (
                "gateway_code_in_same_python_process",
                "integration_owner_code_in_same_python_process",
            ),
            "out_of_scope": (
                "arbitrary_same_process_code_execution",
                "reflection",
                "module_private_memory_access",
                "encoded_or_derived_upstream_credential_reflection",
            ),
            "upstream_trust_boundary": "trusted_beyond_exact_credential_reflection_guard",
            "upstream_credential_responsibility": "ferry_owner_entropy_strength_rotation_and_custody",
            "upstream_credential_identity": "distinct_from_high_entropy_gateway_client_bearer",
            "credential_separation": "upstream_authorization_must_not_equal_gateway_client_bearer",
            "use_prohibition": (
                "must_not_be_used_as_intended_runtime_authority",
                "must_not_be_used_as_live_502_retry_authority",
            ),
            "promotion_requires": (
                "separate_authority_process_or_os_protected_key_custody",
                "new_security_review",
            ),
            "capability_open": False,
            "live_authority": False,
            "intended_runtime_activation": False,
        }
        self.assertEqual(dict(THREAT_MODEL), expected)
        self.assertFalse(THREAT_MODEL["capability_open"])
        self.assertFalse(THREAT_MODEL["live_authority"])
        self.assertFalse(THREAT_MODEL["intended_runtime_activation"])
        with self.assertRaises(TypeError):
            THREAT_MODEL["capability_open"] = True
        source = (CANDIDATE / "attestation.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("non-spoofable", source)
        self.assertNotIn("zero key access", source)
        self.assertIn("must not be used as intended-runtime", source)
        self.assertIn("os-protected key custody", source)
        gateway_source = (CANDIDATE / "gateway.py").read_text(encoding="utf-8")
        self.assertNotIn("shared.job_runtime.service", gateway_source)
        self.assertNotIn("shared.job_runtime.bridge", gateway_source)
        self.assertNotIn("shared.job_runtime.host", gateway_source)

    def test_attempt_id_tracking_is_bounded(self) -> None:
        with self.gateway(max_attempt_ids=2) as gateway:
            for index in range(5):
                self.call(gateway, token=gateway.bearer_token, headers={"x-request-id": f"attempt-{index}"})
            self.assertEqual(gateway.tracked_attempt_ids, 2)
        self.assertEqual(len(self.records()), 5)

    def test_startup_failure_rolls_back_token_socket_and_thread(self) -> None:
        def fail_server(_: LoopbackGateway):
            raise OSError("synthetic bind failure")

        gateway = LoopbackGateway(
            GatewayConfig(), ReceiptLedger(self.receipt_path),
            upstream_authorization=lambda: UPSTREAM_AUTHORIZATION, token_factory=lambda _: "F" * 43, server_factory=fail_server,
        )
        with self.assertRaises(OSError):
            gateway.start()
        with self.assertRaises(RuntimeError):
            _ = gateway.bearer_token
        self.assertIsNone(gateway._upstream_authorization)
        self.assertFalse(self.receipt_path.exists())

        captured: list[tuple[str, int]] = []
        def server_factory(owner: LoopbackGateway):
            server = gateway_module._GatewayServer(owner)
            captured.append(server.server_address)
            return server
        class FailingThread:
            def __init__(self, **_: object) -> None:
                pass
            def start(self) -> None:
                raise RuntimeError("synthetic thread failure")
        gateway = LoopbackGateway(
            GatewayConfig(), ReceiptLedger(self.receipt_path),
            upstream_authorization=lambda: UPSTREAM_AUTHORIZATION, token_factory=lambda _: "G" * 43, server_factory=server_factory,
            thread_factory=FailingThread,
        )
        with self.assertRaises(RuntimeError):
            gateway.start()
        with self.assertRaises(RuntimeError):
            _ = gateway.bearer_token
        with self.assertRaises(OSError):
            socket.create_connection(captured[0], timeout=0.1)

        captured.clear()
        started_wrappers: list[object] = []
        class StartsThenRaises:
            def __init__(self, **kwargs: object) -> None:
                self.inner = threading.Thread(**kwargs)
                started_wrappers.append(self)
            def start(self) -> None:
                self.inner.start()
                raise RuntimeError("synthetic post-start failure")
            def is_alive(self) -> bool:
                return self.inner.is_alive()
            def join(self, timeout: float | None = None) -> None:
                self.inner.join(timeout)
        gateway = LoopbackGateway(
            GatewayConfig(shutdown_timeout=1.0), ReceiptLedger(self.receipt_path),
            upstream_authorization=lambda: UPSTREAM_AUTHORIZATION, token_factory=lambda _: "H" * 43, server_factory=server_factory,
            thread_factory=StartsThenRaises,
        )
        with self.assertRaises(RuntimeError):
            gateway.start()
        self.assertEqual(len(started_wrappers), 1)
        self.assertFalse(started_wrappers[0].is_alive())
        with self.assertRaises(OSError):
            socket.create_connection(captured[0], timeout=0.1)

    def test_fresh_interpreter_import_is_inert(self) -> None:
        script = "\n".join([
            "import sys, socket, threading, http.client, ssl",
            f"sys.path.insert(0, {str(ROOT)!r})",
            "before = len(threading.enumerate())",
            "def forbidden(*args, **kwargs): raise AssertionError('effect during import')",
            "socket.socket = forbidden",
            "threading.Thread.start = forbidden",
            "import shared.job_runtime.candidates.claude_loopback_gateway_v1",
            "assert len(threading.enumerate()) == before",
            "print('INERT')",
        ])
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-I", "-c", script], capture_output=True, text=True,
            timeout=5, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "INERT")

    def test_receipt_fsync_partial_writes_checkpoint_and_complete_tail_detection(self) -> None:
        real_write = receipts_module.os.write
        real_fsync = receipts_module.os.fsync
        fsynced: list[int] = []
        def partial_write(fd: int, payload: bytes) -> int:
            return real_write(fd, bytes(payload[:3]))
        def checked_fsync(fd: int) -> None:
            fsynced.append(fd)
            real_fsync(fd)
        with mock.patch.object(receipts_module.os, "write", side_effect=partial_write), mock.patch.object(
            receipts_module.os, "fsync", side_effect=checked_fsync
        ):
            with self.gateway() as gateway:
                self.call(gateway, token=gateway.bearer_token)
                self.call(gateway, token=gateway.bearer_token)
        self.assertGreaterEqual(len(fsynced), 4)
        self.assertEqual(self.receipt_path.stat().st_mode & 0o777, 0o600)
        ledger = ReceiptLedger(self.receipt_path)
        expected_sequence, expected_head = ledger.checkpoint
        original = self.receipt_path.read_bytes()
        self.assertTrue(original.endswith(b"\n"))
        self.receipt_path.write_bytes(original.splitlines(keepends=True)[0])
        self.assertEqual(len(ReceiptLedger.validate(self.receipt_path)), 1)
        with self.assertRaises(ReceiptIntegrityError):
            ReceiptLedger.validate(
                self.receipt_path, expected_sequence=expected_sequence, expected_head=expected_head
            )
        with self.assertRaises(ReceiptIntegrityError):
            ReceiptLedger(
                self.receipt_path, expected_sequence=expected_sequence, expected_head=expected_head
            )
        self.receipt_path.write_bytes(original[:-1])
        with self.assertRaisesRegex(ReceiptIntegrityError, "partial tail"):
            ReceiptLedger.validate(self.receipt_path)

    def test_receipt_strict_type_enum_range_monotonic_and_state_validation(self) -> None:
        with self.gateway() as gateway:
            self.call(gateway, token=gateway.bearer_token)
            self.call(gateway, token=gateway.bearer_token)
        originals = [json.loads(line) for line in self.receipt_path.read_text().splitlines()]

        def rechain(records: list[dict[str, object]]) -> bytes:
            previous = receipts_module.GENESIS_HASH
            for index, record in enumerate(records, 1):
                record["sequence"] = index
                record["prev_hash"] = previous
                base = {key: value for key, value in record.items() if key != "entry_hash"}
                record["entry_hash"] = hashlib.sha256(ReceiptLedger._encoded(base)).hexdigest()
                previous = record["entry_hash"]
            return b"".join(ReceiptLedger._encoded(record) + b"\n" for record in records)

        mutations = {
            "type": lambda rows: rows[0].__setitem__("arrival_count", True),
            "enum": lambda rows: rows[0].__setitem__("mode", "unknown"),
            "range": lambda rows: rows[0].__setitem__("http_status", 700),
            "monotonic": lambda rows: rows[1].__setitem__("arrival_count", 1),
            "state": lambda rows: rows[0].__setitem__("states", ["arrived", "completed"]),
            "upstream": lambda rows: rows[1].__setitem__("upstream_count", 1),
            "upstream_attempts": lambda rows: rows[1].__setitem__("upstream_attempts", 0),
        }
        for name, mutate in mutations.items():
            rows = json.loads(json.dumps(originals))
            mutate(rows)
            self.receipt_path.write_bytes(rechain(rows))
            with self.subTest(name=name), self.assertRaises(ReceiptIntegrityError):
                ReceiptLedger.validate(self.receipt_path)


    def test_upstream_transfer_coding_matrix_rejected_before_commit(self) -> None:
        behaviors = ("te-cl", "te-duplicate", "te-comma", "te-gzip", "te-gzip-chunked")
        with self.gateway() as gateway:
            for behavior in behaviors:
                with self.subTest(behavior=behavior):
                    status, _, payload = self.call(
                        gateway, token=gateway.bearer_token,
                        headers={"x-test-upstream-behavior": behavior},
                    )
                    self.assertEqual((status, payload), (502, b"invalid upstream framing"))
        records = self.records()
        self.assertEqual(len(records), len(behaviors))
        self.assertTrue(all(record["states"][-1] == "response_rejected" for record in records))
        self.assertTrue(all(record["response_bytes"] == 0 for record in records))

    def test_inbound_obs_fold_and_controls_are_rejected_before_forward(self) -> None:
        with self.gateway() as gateway:
            folded = self.raw_exchange(
                gateway, ["X-Test: visible\r\n folded", "Content-Length: 2"], b"{}"
            )
            controlled = self.raw_exchange(
                gateway, ["X-Test: a\x00b", "Content-Length: 2"], b"{}"
            )
        self.assertIn(b"HTTP/1.1 431", folded)
        self.assertIn(b"HTTP/1.1 431", controlled)
        self.assertEqual(UPSTREAM.calls, [])
        self.assertTrue(all(r["states"][-1] == "headers_rejected" for r in self.records()))

    def test_upstream_obs_fold_and_controls_are_rejected_before_relay(self) -> None:
        with self.gateway() as gateway:
            for behavior in ("bad-header-fold", "bad-header-control"):
                with self.subTest(behavior=behavior):
                    status, _, payload = self.call(
                        gateway, token=gateway.bearer_token,
                        headers={"x-test-upstream-behavior": behavior},
                    )
                    self.assertEqual((status, payload), (502, b"invalid upstream headers"))
        self.assertTrue(all(r["states"][-1] == "response_rejected" for r in self.records()))

    def test_blocking_server_shutdown_retains_state_then_reconciles(self) -> None:
        release = threading.Event()
        serving_alive = threading.Event()
        serving_alive.set()
        class BlockingServer:
            def __init__(self) -> None:
                self.closed = False
            def begin_stop(self) -> None:
                pass
            def shutdown(self) -> None:
                release.wait(2.0)
            def server_close(self) -> None:
                self.closed = True
        class ReapableThread:
            def is_alive(self) -> bool:
                return serving_alive.is_set()
            def join(self, timeout: float | None = None) -> None:
                if release.wait(timeout):
                    serving_alive.clear()
        gateway = LoopbackGateway(
            GatewayConfig(shutdown_timeout=0.10), ReceiptLedger(self.receipt_path),
            upstream_authorization=lambda: UPSTREAM_AUTHORIZATION,
        )
        server = BlockingServer()
        serving = ReapableThread()
        gateway._server = server
        gateway._thread = serving
        gateway._token = "S" * 43
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "shutdown bound"):
            gateway.close()
        self.assertLess(time.monotonic() - started, 0.35)
        self.assertTrue(server.closed)
        self.assertTrue(gateway.stop_pending)
        self.assertIs(gateway._server, server)
        self.assertIs(gateway._thread, serving)
        self.assertIsNotNone(gateway._shutdown_thread)
        self.assertTrue(gateway._shutdown_thread.is_alive())
        with self.assertRaisesRegex(RuntimeError, "pending reconciliation"):
            gateway.start()
        with self.assertRaises(RuntimeError):
            _ = gateway.bearer_token

        release.set()
        gateway.close()
        self.assertFalse(gateway.stop_pending)
        self.assertIsNone(gateway._server)
        self.assertIsNone(gateway._thread)
        self.assertIsNone(gateway._shutdown_thread)
        gateway.start()
        gateway.close()

    def test_receipt_partial_append_poison_fails_closed_without_memory_commit(self) -> None:
        ledger = ReceiptLedger(self.receipt_path)
        gateway = LoopbackGateway(
            GatewayConfig(), ledger, upstream_authorization=lambda: UPSTREAM_AUTHORIZATION, token_factory=lambda _: "T" * 43,
            connection_factory=self.connection_factory,
        )
        with gateway:
            self.call(gateway, token=gateway.bearer_token)
        first = self.records()[0]
        fields = {
            key: value for key, value in first.items()
            if key not in {"sequence", "prev_hash", "entry_hash"}
        }
        fields.update({"timestamp_ns": first["timestamp_ns"] + 1, "arrival_count": 2, "upstream_count": 2})
        real_write = receipts_module.os.write
        calls = 0
        def uncertain_write(fd: int, payload: bytes) -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_write(fd, bytes(payload[:7]))
            raise OSError("synthetic append failure")
        with mock.patch.object(receipts_module.os, "write", side_effect=uncertain_write):
            with self.assertRaises(OSError):
                ledger.append(fields)
        self.assertTrue(ledger.poisoned)
        with self.assertRaisesRegex(ReceiptIntegrityError, "poisoned"):
            _ = ledger.checkpoint
        with self.assertRaisesRegex(ReceiptIntegrityError, "poisoned"):
            ledger.append(fields)
        with self.assertRaisesRegex(ReceiptIntegrityError, "partial tail"):
            ReceiptLedger.validate(self.receipt_path)

    def test_regressing_wall_clock_emits_canonical_nondecreasing_timestamps(self) -> None:
        values = iter((100, 50))
        gateway = LoopbackGateway(
            GatewayConfig(), ReceiptLedger(self.receipt_path),
            upstream_authorization=lambda: UPSTREAM_AUTHORIZATION, token_factory=lambda _: "T" * 43,
            clock_ns=lambda: next(values),
            connection_factory=self.connection_factory,
        )
        with gateway:
            self.call(gateway, token=gateway.bearer_token)
            self.call(gateway, token=gateway.bearer_token)
        records = self.records()
        self.assertEqual([r["timestamp_ns"] for r in records], [100, 100])

    def test_partial_payload_write_reports_exact_completed_payload_bytes(self) -> None:
        class PartialWriter:
            def __init__(self) -> None:
                self.calls = 0
            def write(self, payload: object) -> int:
                self.calls += 1
                size = len(payload)  # type: ignore[arg-type]
                if self.calls == 1:
                    return size  # chunk prefix
                if self.calls == 2:
                    return 2
                raise BrokenPipeError("synthetic cancellation")
            def flush(self) -> None:
                return
        handler = object.__new__(gateway_module._Handler)
        handler.wfile = PartialWriter()
        with self.assertRaises(gateway_module._PayloadWriteInterrupted) as caught:
            handler._emit_chunk(b"abcdef", True)
        self.assertEqual(caught.exception.payload_bytes, 2)


    def test_synthetic_502_rejected_before_forward_then_single_pass_through(self) -> None:
        body = b'{"model":"fixture-502"}'
        binding = self.expected_binding("valid")
        gateway = self.gateway(mode="synthetic_first", synthetic_status=502, synthetic_attempts=1)
        gateway.start(binding)
        verifier = gateway.attestation_verifier
        self.assertEqual(gateway.run_binding_hash, binding.run_binding_hash)
        first_status, first_headers, first_payload = self.call(
            gateway, token=gateway.bearer_token, body=body
        )
        self.wait_for_receipts(1)
        self.assertEqual(UPSTREAM.calls, [])
        first_raw = self.receipt_path.read_bytes()
        self.assertNotIn(UPSTREAM_AUTHORIZATION.encode(), first_raw)
        self.assertNotIn(hashlib.sha256(UPSTREAM_AUTHORIZATION.encode()).hexdigest().encode(), first_raw)
        second_status, _, second_payload = self.call(
            gateway, token=gateway.bearer_token, body=body
        )
        self.assertEqual(first_status, 502)
        headers = {name.lower(): value for name, value in first_headers}
        self.assertEqual(headers["retry-after"], "1")
        self.assertEqual(json.loads(first_payload), {
            "type": "error",
            "error": {
                "type": "api_error",
                "message": "Synthetic gateway rejection before forward",
            },
        })
        self.assertEqual((second_status, second_payload), (200, body))
        self.assertEqual(len(UPSTREAM.calls), 1)
        self.assertEqual(UPSTREAM.calls[0]["body"], body)

        first, second = self.wait_for_receipts(2)
        self.assertEqual(first["states"], ["arrived", "authenticated", "rejected_before_forward"])
        self.assertEqual((first["http_status"], first["arrival_count"], first["upstream_count"], first["upstream_attempts"]), (502, 1, 0, 0))
        self.assertEqual(second["states"], ["arrived", "authenticated", "forwarding", "completed"])
        self.assertEqual((second["http_status"], second["arrival_count"], second["upstream_count"], second["upstream_attempts"]), (200, 2, 1, 1))
        self.assertIsNone(second["pre_forward_attestation"])
        self.assertEqual((first["sequence"], second["sequence"]), (1, 2))
        self.assertEqual(second["prev_hash"], first["entry_hash"])
        records, verified_items = ReceiptLedger.validate_authenticated(
            self.receipt_path, verifier=verifier, expected_binding=binding
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(len(verified_items), 1)
        verified = verified_items[0]
        self.assertIsInstance(verified, VerifiedPreForwardAttestation)
        self.assertFalse(hasattr(verified, "__dict__"))
        self.assertIs(verified.binding, binding)
        self.assertEqual((verified.status, verified.upstream_attempts, verified.upstream_count_delta), (502, 0, 0))
        self.assertEqual((verified.submission, verified.retry_after), ("not_submitted", "1"))
        gateway.close()
        with self.assertRaises(AttestationVerificationError):
            verifier.verify_and_consume(
                first["pre_forward_attestation"], expected_binding=binding, request_ordinal=1
            )

    def test_forwarded_upstream_502_is_attempted_and_not_pre_forward_safe(self) -> None:
        expected = b'{"type":"error","error":{"type":"api_error","message":"upstream fixture"}}'
        with self.gateway() as gateway:
            status, _, payload = self.call(
                gateway, token=gateway.bearer_token,
                headers={"x-test-upstream-behavior": "upstream-502"},
            )
        self.assertEqual((status, payload), (502, expected))
        self.assertEqual(len(UPSTREAM.calls), 1)
        record = self.records()[0]
        self.assertEqual(record["states"], ["arrived", "authenticated", "forwarding", "upstream_502"])
        self.assertNotIn("rejected_before_forward", record["states"])
        self.assertEqual((record["http_status"], record["arrival_count"], record["upstream_count"], record["upstream_attempts"]), (502, 1, 1, 1))
        self.assertIsNone(record["pre_forward_attestation"])
        self.assertEqual(len(ReceiptLedger.validate(self.receipt_path)), 1)


    def test_caller_binding_headers_are_rejected_and_burn_one_shot_binding(self) -> None:
        binding = self.expected_binding("header-attack")
        gateway = self.gateway(mode="synthetic_first", synthetic_status=502)
        gateway.start(binding)
        status, _, _ = self.call(
            gateway, token=gateway.bearer_token,
            headers={"x-loopback-slot-binding-sha256": "f" * 64},
        )
        self.assertEqual(status, 400)
        status, _, _ = self.call(gateway, token=gateway.bearer_token)
        self.assertEqual(status, 409)
        gateway.close()
        records = self.records()
        self.assertEqual([r["states"][-1] for r in records], ["request_rejected", "request_rejected"])
        self.assertTrue(all(r["pre_forward_attestation"] is None for r in records))
        self.assertEqual(UPSTREAM.calls, [])

        self.receipt_path.unlink()
        with self.gateway() as normal:
            status, _, _ = self.call(
                normal, token=normal.bearer_token,
                headers={"x-loopback-prompt-binding-sha256": "0" * 64},
            )
        self.assertEqual(status, 400)
        self.assertEqual(UPSTREAM.calls, [])

    def test_attestation_owner_rejects_spoofing_replay_copy_pickle_and_revocation(self) -> None:
        binding = self.expected_binding("attack")
        gateway = self.gateway(mode="synthetic_first", synthetic_status=502)
        gateway.start(binding)
        self.addCleanup(lambda: gateway.close() if gateway._server is not None else None)
        verifier = gateway.attestation_verifier
        status, _, _ = self.call(gateway, token=gateway.bearer_token)
        self.assertEqual(status, 502)
        proof = self.wait_for_receipts()[0]["pre_forward_attestation"]

        self.assertFalse(hasattr(verifier, "_key"))
        self.assertFalse(hasattr(verifier, "__dict__"))
        copied = copy.copy(verifier)
        self.assertIs(copied, verifier)
        with self.assertRaises(TypeError):
            pickle.dumps(verifier)
        with self.assertRaises(AttestationVerificationError):
            verifier.verify_and_consume(None, expected_binding=binding, request_ordinal=1)
        unsigned = dict(proof); unsigned.pop("signature")
        with self.assertRaises(AttestationVerificationError):
            verifier.verify_and_consume(unsigned, expected_binding=binding, request_ordinal=1)
        self_attested = dict(proof)
        self_attested["proof_kind"] = "self_attested"
        self_attested["signature"] = "0" * 64
        with self.assertRaises(AttestationVerificationError):
            verifier.verify_and_consume(self_attested, expected_binding=binding, request_ordinal=1)
        forged = dict(proof); forged["signature"] = "0" * 64
        with self.assertRaises(AttestationVerificationError):
            verifier.verify_and_consume(forged, expected_binding=binding, request_ordinal=1)

        wrong_binding = self.expected_binding("wrong")
        with self.assertRaises(AttestationVerificationError):
            verifier.verify_and_consume(proof, expected_binding=wrong_binding, request_ordinal=1)
        for ordinal in (2, True, 1.0):
            with self.subTest(ordinal=ordinal), self.assertRaises(AttestationVerificationError):
                verifier.verify_and_consume(proof, expected_binding=binding, request_ordinal=ordinal)
        for field, values in {
            "status": (503,), "upstream_attempts": (1,),
            "upstream_count_delta": (1,), "retry_after": ("2",),
            "submission": ("submitted", "possibly_submitted"),
            "request_ordinal": (True, 1.0),
        }.items():
            for value in values:
                altered = dict(proof); altered[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(AttestationVerificationError):
                    verifier.verify_and_consume(altered, expected_binding=binding, request_ordinal=1)

        other_path = Path(self.temp.name) / "other-receipts.jsonl"
        other_binding = self.expected_binding("other")
        other = LoopbackGateway(
            GatewayConfig(mode="synthetic_first", synthetic_status=502),
            ReceiptLedger(other_path), upstream_authorization=lambda: UPSTREAM_AUTHORIZATION, token_factory=lambda _: "O" * 43,
            connection_factory=self.connection_factory,
        )
        other.start(other_binding)
        wrong_authority = other.attestation_verifier
        with self.assertRaises(AttestationVerificationError):
            wrong_authority.verify_and_consume(
                proof, expected_binding=other_binding, request_ordinal=1
            )
        other.close()

        verified = verifier.verify_and_consume(
            proof, expected_binding=binding, request_ordinal=1
        )
        self.assertIsInstance(verified, VerifiedPreForwardAttestation)
        with self.assertRaises(AttestationVerificationError):
            copied.verify_and_consume(proof, expected_binding=binding, request_ordinal=1)
        gateway.close()
        with self.assertRaises(AttestationVerificationError):
            verifier.verify_and_consume(proof, expected_binding=binding, request_ordinal=1)

        next_binding = self.expected_binding("next-run")
        gateway.start(next_binding)
        next_verifier = gateway.attestation_verifier
        with self.assertRaises(AttestationVerificationError):
            next_verifier.verify_and_consume(proof, expected_binding=next_binding, request_ordinal=1)
        gateway.close()
        self.assertNotIn("key", proof)

    def test_unconsumed_verifier_is_revoked_on_close_and_restart(self) -> None:
        binding = self.expected_binding("revoked")
        gateway = self.gateway(mode="synthetic_first", synthetic_status=502)
        gateway.start(binding)
        old_verifier = gateway.attestation_verifier
        owner_key_buffer = gateway._attestation_owner._key
        self.call(gateway, token=gateway.bearer_token)
        proof = self.wait_for_receipts()[0]["pre_forward_attestation"]
        gateway.close()
        self.assertTrue(owner_key_buffer)
        self.assertTrue(all(byte == 0 for byte in owner_key_buffer))
        with self.assertRaisesRegex(AttestationVerificationError, "revoked"):
            old_verifier.verify_and_consume(
                proof, expected_binding=binding, request_ordinal=1
            )

        new_binding = self.expected_binding("revoked-next")
        gateway.start(new_binding)
        new_verifier = gateway.attestation_verifier
        with self.assertRaises(AttestationVerificationError):
            new_verifier.verify_and_consume(
                proof, expected_binding=new_binding, request_ordinal=1
            )
        with self.assertRaisesRegex(AttestationVerificationError, "revoked"):
            old_verifier.verify_and_consume(
                proof, expected_binding=binding, request_ordinal=1
            )
        gateway.close()

    def test_authenticated_receipt_rejects_forged_signature_and_wrong_authority(self) -> None:
        binding = self.expected_binding("receipt-auth")
        gateway = self.gateway(mode="synthetic_first", synthetic_status=502)
        gateway.start(binding)
        self.addCleanup(lambda: gateway.close() if gateway._server is not None else None)
        verifier = gateway.attestation_verifier
        status, _, _ = self.call(gateway, token=gateway.bearer_token)
        self.assertEqual(status, 502)
        self.wait_for_receipts()
        original = self.receipt_path.read_bytes()
        record = json.loads(original)

        def rewrite(mutator) -> None:
            candidate = json.loads(json.dumps(record))
            mutator(candidate["pre_forward_attestation"])
            base = {k: v for k, v in candidate.items() if k != "entry_hash"}
            candidate["entry_hash"] = hashlib.sha256(ReceiptLedger._encoded(base)).hexdigest()
            self.receipt_path.write_bytes(ReceiptLedger._encoded(candidate) + b"\n")

        rewrite(lambda proof: proof.__setitem__("signature", "0" * 64))
        self.assertEqual(len(ReceiptLedger.validate(self.receipt_path)), 1)
        with self.assertRaises(ReceiptIntegrityError):
            ReceiptLedger.validate_authenticated(
                self.receipt_path, verifier=verifier, expected_binding=binding
            )
        rewrite(lambda proof: proof.__setitem__("authority_id", "0" * 32))
        with self.assertRaises(ReceiptIntegrityError):
            ReceiptLedger.validate_authenticated(
                self.receipt_path, verifier=verifier, expected_binding=binding
            )
        self.receipt_path.write_bytes(original)
        records, verified = ReceiptLedger.validate_authenticated(
            self.receipt_path, verifier=verifier, expected_binding=binding
        )
        self.assertEqual((len(records), len(verified)), (1, 1))
        gateway.close()

    def test_receipt_rejects_bool_float_duplicate_and_noncanonical_json(self) -> None:
        binding = self.expected_binding("strict-json")
        gateway = self.gateway(mode="synthetic_first", synthetic_status=502)
        gateway.start(binding)
        self.call(gateway, token=gateway.bearer_token)
        gateway.close()
        original = self.receipt_path.read_bytes()
        record = json.loads(original)
        for value in (True, 1.0):
            candidate = json.loads(json.dumps(record))
            candidate["pre_forward_attestation"]["request_ordinal"] = value
            base = {k: v for k, v in candidate.items() if k != "entry_hash"}
            candidate["entry_hash"] = hashlib.sha256(ReceiptLedger._encoded(base)).hexdigest()
            self.receipt_path.write_bytes(ReceiptLedger._encoded(candidate) + b"\n")
            with self.subTest(ordinal=value), self.assertRaises(ReceiptIntegrityError):
                ReceiptLedger.validate(self.receipt_path)

        text = original.decode("ascii").rstrip("\n")
        duplicate_top = text.replace('{"arrival_count":1', '{"arrival_count":1,"arrival_count":1', 1)
        self.receipt_path.write_text(duplicate_top + "\n", encoding="ascii")
        with self.assertRaisesRegex(ReceiptIntegrityError, "duplicate key"):
            ReceiptLedger.validate(self.receipt_path)
        duplicate_nested = text.replace('"attempt_binding_hash":', '"attempt_binding_hash":"0","attempt_binding_hash":', 1)
        self.receipt_path.write_text(duplicate_nested + "\n", encoding="ascii")
        with self.assertRaisesRegex(ReceiptIntegrityError, "duplicate key"):
            ReceiptLedger.validate(self.receipt_path)
        self.receipt_path.write_bytes(b" " + original)
        with self.assertRaisesRegex(ReceiptIntegrityError, "not canonical"):
            ReceiptLedger.validate(self.receipt_path)


if __name__ == "__main__":
    unittest.main()
