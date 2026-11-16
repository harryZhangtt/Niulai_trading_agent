"""Disabled-on-import, provider-free loopback observer gateway candidate."""
from __future__ import annotations

import hmac
import http.client
import json
import re
import secrets
import socket
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

from .attestation import (
    ExpectedPreForwardBinding,
    PreForwardAttestationVerifier,
    _PreForwardAttestationOwner,
)
from .receipts import ReceiptLedger, SCHEMA_VERSION

UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 8790
MESSAGE_PATH = "/v1/messages"
MODELS_PATH = "/v1/models"
MODES = frozenset({"pass_through", "synthetic_first", "forward_then_cut"})
SENSITIVE_HEADERS = frozenset({
    "authorization", "proxy-authorization", "x-api-key", "cookie", "set-cookie",
})
INTERNAL_BINDING_HEADERS = {
    "slot_binding_hash": "x-loopback-slot-binding-sha256",
    "attempt_binding_hash": "x-loopback-attempt-binding-sha256",
    "operation_binding_hash": "x-loopback-operation-binding-sha256",
    "prompt_binding_hash": "x-loopback-prompt-binding-sha256",
}
INTERNAL_HEADERS = frozenset(INTERNAL_BINDING_HEADERS.values())
HOP_HEADERS = frozenset({
    "connection", "proxy-connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
})
_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_CANONICAL_LENGTH = re.compile(r"^(0|[1-9][0-9]*)$")
_BEARER_TOKEN = re.compile(r"^[A-Za-z0-9\-._~+/]+=*$")


class _PartialWrite(OSError):
    def __init__(self, written: int) -> None:
        self.written = written
        super().__init__("socket write was interrupted")


class _PayloadWriteInterrupted(OSError):
    def __init__(self, payload_bytes: int) -> None:
        self.payload_bytes = payload_bytes
        super().__init__("payload write was interrupted")


class _ClientCancelled(Exception):
    def __init__(self, status: int, response_bytes: int, streaming: bool) -> None:
        self.status = status
        self.response_bytes = response_bytes
        self.streaming = streaming
        super().__init__("client cancelled after response commit")


@dataclass(frozen=True)
class GatewayConfig:
    mode: str = "pass_through"
    synthetic_status: int = 429
    synthetic_attempts: int = 1
    connect_timeout: float = 2.0
    header_timeout: float = 1.0
    ingress_timeout: float = 2.0
    response_timeout: float = 5.0
    shutdown_timeout: float = 2.0
    max_request_bytes: int = 1_048_576
    max_response_bytes: int = 8_388_608
    chunk_bytes: int = 16_384
    cut_after_bytes: int = 32
    max_headers: int = 64
    max_header_bytes: int = 32_768
    max_attempt_ids: int = 1024

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError("unsupported mode")
        if self.synthetic_status not in (429, 502, 503):
            raise ValueError("synthetic status must be 429, 502, or 503")
        positive = (
            self.connect_timeout, self.header_timeout, self.ingress_timeout,
            self.response_timeout, self.shutdown_timeout, self.max_request_bytes,
            self.max_response_bytes, self.chunk_bytes, self.cut_after_bytes,
            self.max_headers, self.max_header_bytes, self.max_attempt_ids,
        )
        if any(value <= 0 for value in positive) or self.synthetic_attempts < 0:
            raise ValueError("bounds and timeouts must be positive")
        if self.cut_after_bytes > self.max_response_bytes:
            raise ValueError("cut bound exceeds response bound")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection that bypasses name resolution for the fixed IPv4 target."""

    def connect(self) -> None:
        if self.host != UPSTREAM_HOST or self.port != UPSTREAM_PORT:
            raise OSError("upstream target is not pinned")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect((UPSTREAM_HOST, UPSTREAM_PORT))
        except BaseException:
            sock.close()
            raise
        self.sock = sock


class _GatewayServer(HTTPServer):
    allow_reuse_address = False

    def __init__(self, gateway: "LoopbackGateway") -> None:
        self.gateway = gateway
        self._active_lock = threading.Lock()
        self._active_client: Optional[socket.socket] = None
        self._stopping = False
        super().__init__(("127.0.0.1", 0), _Handler)

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        client, address = super().get_request()
        with self._active_lock:
            if self._stopping:
                client.close()
                raise OSError("gateway is stopping")
            self._active_client = client
        return client, address

    def set_active(self, client: socket.socket) -> None:
        with self._active_lock:
            if not self._stopping:
                self._active_client = client

    def clear_active(self, client: socket.socket) -> None:
        with self._active_lock:
            if self._active_client is client:
                self._active_client = None

    def begin_stop(self) -> None:
        with self._active_lock:
            self._stopping = True
            client = self._active_client
        self._close_client(client)

    @staticmethod
    def _close_client(client: Optional[socket.socket]) -> None:
        if client is not None:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass

    def abort_active(self) -> None:
        with self._active_lock:
            client = self._active_client
        self._close_client(client)


class LoopbackGateway:
    """Explicit-lifecycle gateway; construction and import perform no I/O.

    The resolved upstream bearer exists only on the live gateway and its reference
    is dropped on every close/failure path. Python ``str`` objects cannot be
    reliably overwritten, so this is reference clearing—not a zeroization claim.
    A direct string is deliberately single-start because its source reference is
    consumed; restartable/live integration requires an owner-controlled callable.
    Upstream credential entropy, strength, rotation, and custody are the Ferry
    owner's responsibility. This upstream value is not the high-entropy one-run
    gateway client bearer, whose separate minimum length remains unchanged.
    """

    def __init__(
        self,
        config: GatewayConfig,
        ledger: ReceiptLedger,
        *,
        upstream_authorization: str | Callable[[], str],
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
        clock_ns: Callable[[], int] = time.time_ns,
        connection_factory: Callable[[str, int, float], http.client.HTTPConnection] | None = None,
        server_factory: Callable[["LoopbackGateway"], _GatewayServer] | None = None,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        self.config = config
        self.ledger = ledger
        if type(upstream_authorization) is str:
            self._validate_upstream_authorization(upstream_authorization)
        elif not callable(upstream_authorization):
            raise ValueError("upstream authorization source is required")
        self._upstream_authorization_source: str | Callable[[], str] | None = upstream_authorization
        self._upstream_authorization: Optional[str] = None
        self._token_factory = token_factory
        self._clock_ns = clock_ns
        self._connection_factory = connection_factory or (
            lambda host, port, timeout: _PinnedHTTPConnection(host, port, timeout=timeout)
        )
        self._server_factory = server_factory or _GatewayServer
        self._thread_factory = thread_factory
        self._token: Optional[str] = None
        self._server: Optional[_GatewayServer] = None
        self._thread: Optional[threading.Thread] = None
        self._shutdown_thread: Optional[threading.Thread] = None
        self._stop_failed = False
        self._attestation_owner: Optional[_PreForwardAttestationOwner] = None
        self._attestation_verifier: Optional[PreForwardAttestationVerifier] = None
        self._lock = threading.Lock()
        self._arrival_count, self._upstream_count = ledger.last_counts
        self._last_timestamp_ns = ledger.last_timestamp_ns
        self._synthetic_remaining = config.synthetic_attempts
        self._attempts: OrderedDict[str, int] = OrderedDict()
        self._active_upstreams: set[http.client.HTTPConnection] = set()

    @staticmethod
    def _validate_upstream_authorization(value: object) -> str:
        if (
            type(value) is not str
            or not 1 <= len(value) <= 4096
            or not _BEARER_TOKEN.fullmatch(value)
        ):
            raise ValueError("upstream authorization is invalid")
        return value

    def _resolve_upstream_authorization(self) -> str:
        source = self._upstream_authorization_source
        if type(source) is str:
            self._upstream_authorization_source = None
            return self._validate_upstream_authorization(source)
        if callable(source):
            try:
                value = source()
            except Exception:
                raise ValueError("upstream authorization resolution failed") from None
            return self._validate_upstream_authorization(value)
        raise ValueError("upstream authorization is unavailable")

    @property
    def bearer_token(self) -> str:
        if self._token is None:
            raise RuntimeError("gateway has not started")
        return self._token

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None:
            raise RuntimeError("gateway has not started")
        host, port = self._server.server_address
        return str(host), int(port)

    @property
    def attestation_verifier(self) -> PreForwardAttestationVerifier:
        if self._attestation_verifier is None:
            raise RuntimeError("attestation authority is not active")
        return self._attestation_verifier

    @property
    def run_binding_hash(self) -> str:
        if self._attestation_owner is None:
            raise RuntimeError("attestation authority is not active")
        return self._attestation_owner.run_binding_hash

    @property
    def stop_pending(self) -> bool:
        return self._stop_failed

    @property
    def tracked_attempt_ids(self) -> int:
        with self._lock:
            return len(self._attempts)

    def start(
        self, expected_pre_forward_binding: Optional[ExpectedPreForwardBinding] = None
    ) -> "LoopbackGateway":
        if self._stop_failed:
            raise RuntimeError("gateway stop is pending reconciliation")
        if self._server is not None:
            raise RuntimeError("gateway already started")
        token = self._token_factory(32)
        if type(token) is not str or len(token) < 32 or any(ch.isspace() for ch in token):
            raise ValueError("token factory returned an invalid token")
        needs_attestation = (
            self.config.mode == "synthetic_first" and self.config.synthetic_status == 502
        )
        if needs_attestation:
            if type(expected_pre_forward_binding) is not ExpectedPreForwardBinding:
                raise ValueError("synthetic 502 requires exact out-of-band expected binding")
            if self.config.synthetic_attempts != 1:
                raise ValueError("synthetic 502 attestation is one-shot")
        elif expected_pre_forward_binding is not None:
            raise ValueError("out-of-band binding is only valid for synthetic 502")
        upstream_authorization = self._resolve_upstream_authorization()
        if hmac.compare_digest(upstream_authorization, token):
            self._upstream_authorization = None
            raise ValueError("upstream authorization must differ from gateway client bearer") from None
        owner = (
            _PreForwardAttestationOwner(expected_pre_forward_binding)
            if needs_attestation else None
        )
        server = None
        thread = None
        self._token = token
        self._upstream_authorization = upstream_authorization
        self._attestation_owner = owner
        self._attestation_verifier = owner.verifier() if owner is not None else None
        with self._lock:
            self._synthetic_remaining = self.config.synthetic_attempts
            self._attempts.clear()
        try:
            server = self._server_factory(self)
            poll_interval = min(0.05, self.config.shutdown_timeout / 4.0)
            thread = self._thread_factory(
                target=lambda: server.serve_forever(poll_interval=poll_interval),
                name="claude-loopback-gateway-v1",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            thread.start()
        except BaseException:
            self._token = None
            self._upstream_authorization = None
            if self._attestation_owner is not None:
                self._attestation_owner.revoke()
            self._attestation_owner = None
            self._attestation_verifier = None
            if server is not None:
                self._server = server
                self._thread = thread
                if self._bounded_stop(server, thread):
                    self._server = None
                    self._thread = None
                    self._shutdown_thread = None
                else:
                    self._stop_failed = True
            else:
                self._server = None
                self._thread = None
            raise
        return self

    def _abort_upstreams(self) -> None:
        with self._lock:
            connections = tuple(self._active_upstreams)
        for connection in connections:
            try:
                connection.close()
            except OSError:
                pass

    def _bounded_stop(self, server: _GatewayServer, thread: object) -> bool:
        deadline = time.monotonic() + self.config.shutdown_timeout
        server.begin_stop()
        self._abort_upstreams()
        is_alive = getattr(thread, "is_alive", lambda: False)
        shutdown_worker = self._shutdown_thread
        if thread is not None and is_alive() and (
            shutdown_worker is None or not shutdown_worker.is_alive()
        ):
            shutdown_worker = threading.Thread(
                target=server.shutdown, name="claude-loopback-shutdown-v1", daemon=True
            )
            self._shutdown_thread = shutdown_worker
            shutdown_worker.start()
        # Closing the listener forces queued accepts to fail. The potentially
        # blocking shutdown call remains owned by the retained daemon helper.
        server.server_close()
        join = getattr(thread, "join", lambda timeout=None: None)
        if thread is not None and is_alive():
            join(max(0.0, deadline - time.monotonic()))
        if shutdown_worker is not None and shutdown_worker.is_alive():
            shutdown_worker.join(max(0.0, deadline - time.monotonic()))
        thread_alive = thread is not None and is_alive()
        helper_alive = shutdown_worker is not None and shutdown_worker.is_alive()
        return not thread_alive and not helper_alive

    def close(self) -> None:
        server, thread = self._server, self._thread
        if server is None:
            self._token = None
            self._upstream_authorization = None
            if self._attestation_owner is not None:
                self._attestation_owner.revoke()
            self._attestation_owner = None
            self._attestation_verifier = None
            return
        stopped = self._bounded_stop(server, thread)
        self._token = None
        self._upstream_authorization = None
        if self._attestation_owner is not None:
            self._attestation_owner.revoke()
        self._attestation_owner = None
        self._attestation_verifier = None
        with self._lock:
            self._attempts.clear()
        if not stopped:
            self._stop_failed = True
            # Retain server, serving-thread and shutdown-helper handles so a
            # later close() can reap them. Restart remains fenced meanwhile.
            raise RuntimeError("gateway thread did not stop within shutdown bound")
        self._server = None
        self._thread = None
        self._shutdown_thread = None
        self._stop_failed = False

    def __enter__(self) -> "LoopbackGateway":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()

    def _register_upstream(self, connection: http.client.HTTPConnection) -> None:
        with self._lock:
            self._active_upstreams.add(connection)

    def _unregister_upstream(self, connection: http.client.HTTPConnection) -> None:
        with self._lock:
            self._active_upstreams.discard(connection)

    def _arrive(self, attempt_id: Optional[str]) -> tuple[int, int, bool, int]:
        with self._lock:
            self._arrival_count += 1
            attempt_number = 1
            duplicate = False
            if attempt_id:
                attempt_number = self._attempts.pop(attempt_id, 0) + 1
                self._attempts[attempt_id] = attempt_number
                while len(self._attempts) > self.config.max_attempt_ids:
                    self._attempts.popitem(last=False)
                duplicate = attempt_number > 1
            return self._arrival_count, self._upstream_count, duplicate, attempt_number

    def _consume_expected_binding(self) -> Optional[ExpectedPreForwardBinding]:
        owner = self._attestation_owner
        return None if owner is None else owner.consume_expected_binding()

    def _synthetic_502_pending(self) -> bool:
        with self._lock:
            return (
                self.config.mode == "synthetic_first"
                and self.config.synthetic_status == 502
                and self._synthetic_remaining > 0
            )

    def _claim_synthetic(self) -> bool:
        with self._lock:
            if self.config.mode == "synthetic_first" and self._synthetic_remaining:
                self._synthetic_remaining -= 1
                return True
            return False

    def _mark_upstream(self) -> int:
        with self._lock:
            self._upstream_count += 1
            return self._upstream_count

    def _receipt(self, *, arrival: int, upstream: int, duplicate: bool, attempt_number: int,
                 states: list[str], status: int, request_bytes: int = 0,
                 response_bytes: int = 0, streaming: bool = False,
                 pre_forward_attestation: Optional[dict[str, object]] = None,
                 method: str = "POST", path: str = MESSAGE_PATH,
                 receipt_mode: Optional[str] = None) -> None:
        observed = self._clock_ns()
        if type(observed) is not int:
            raise ValueError("clock must return integer nanoseconds")
        timestamp = max(self._last_timestamp_ns, observed, 0)
        self.ledger.append({
            "schema_version": SCHEMA_VERSION,
            "timestamp_ns": timestamp, "method": method, "path": path,
            "mode": self.config.mode if receipt_mode is None else receipt_mode,
            "states": states, "http_status": status,
            "arrival_count": arrival, "upstream_count": upstream,
            "duplicate_attempt": duplicate, "attempt_number": attempt_number,
            "upstream_attempts": int("forwarding" in states),
            "request_bytes": request_bytes, "response_bytes": response_bytes,
            "streaming": streaming,
            "pre_forward_attestation": pre_forward_attestation,
        })
        self._last_timestamp_ns = timestamp


def _valid_relay_header(name: object, value: object) -> bool:
    if type(name) is not str or type(value) is not str or not _TOKEN.fullmatch(name):
        return False
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        return False
    # obs-fold necessarily contains CR/LF. HTAB is the only allowed C0 value.
    return all(char == "\t" or (" " <= char <= "~") or ord(char) >= 128 for char in value) and "\x7f" not in value


def _connection_nominees(headers: list[tuple[str, str]]) -> set[str]:
    result: set[str] = set()
    for name, value in headers:
        if name.lower() not in {"connection", "proxy-connection"}:
            continue
        for item in value.split(","):
            token = item.strip().lower()
            if _TOKEN.fullmatch(token):
                result.add(token)
    return result


class _ExactCredentialScanner:
    """Bounded exact-byte scanner retaining at most token_length-1 bytes."""

    __slots__ = ("_token", "_overlap", "_pending")

    def __init__(self, token: str) -> None:
        self._token = token.encode("ascii")
        self._overlap = len(self._token) - 1
        self._pending = b""

    def feed(self, chunk: bytes) -> tuple[bytes, bool]:
        combined = self._pending + chunk
        index = combined.find(self._token)
        if index >= 0:
            self._pending = b""
            return combined[:index], True
        if self._overlap == 0:
            self._pending = b""
            return combined, False
        if len(combined) <= self._overlap:
            self._pending = combined
            return b"", False
        emit = combined[:-self._overlap]
        self._pending = combined[-self._overlap:]
        return emit, False

    def finish(self) -> bytes:
        pending = self._pending
        self._pending = b""
        return pending


def _timer(seconds: float, callback: Callable[[], None]) -> threading.Timer:
    timer = threading.Timer(seconds, callback)
    timer.daemon = True
    timer.start()
    return timer


TERMINAL_STATES = frozenset({
    "headers_rejected", "auth_rejected", "request_rejected", "request_incomplete",
    "synthetic_fault", "rejected_before_forward", "completed", "upstream_502",
    "forward_cut", "cut_not_reached", "response_rejected", "response_limit_cut",
    "upstream_error", "upstream_premature_eof", "post_commit_error",
    "credential_reflection", "client_cancelled",
})


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = ""
    sys_version = ""

    @property
    def gateway(self) -> LoopbackGateway:
        return self.server.gateway  # type: ignore[attr-defined,no-any-return]

    def setup(self) -> None:
        super().setup()
        self._header_expired = False
        self._header_guard = _timer(self.gateway.config.header_timeout, self._expire_headers)

    def finish(self) -> None:
        self._header_guard.cancel()
        try:
            super().finish()
        finally:
            self.server.clear_active(self.connection)  # type: ignore[attr-defined]

    def _expire_headers(self) -> None:
        self._header_expired = True
        self._abort_client()

    def _abort_client(self) -> None:
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.connection.close()
        except OSError:
            pass

    def log_message(self, *_: object) -> None:
        return

    def flush_headers(self) -> None:
        if hasattr(self, "_headers_buffer"):
            payload = b"".join(self._headers_buffer)
            self._headers_buffer = []
            self._write_all(payload, flush=False)

    def _write_all(self, payload: bytes, *, flush: bool = True) -> int:
        view = memoryview(payload)
        total = 0
        try:
            while view:
                written = self.wfile.write(view)
                if written is None or written <= 0:
                    raise OSError("socket write made no progress")
                total += written
                view = view[written:]
            if flush:
                self.wfile.flush()
        except (OSError, ValueError) as exc:
            raise _PartialWrite(total) from exc
        return total

    def _begin_method(self) -> bool:
        self._header_guard.cancel()
        self.close_connection = True
        return not self._header_expired

    def do_OPTIONS(self) -> None:
        if not self._begin_method():
            return
        if self.path != MESSAGE_PATH:
            self._plain(404, b"not found")
            return
        self.send_response_only(204)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "authorization, content-type, anthropic-version, x-request-id")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_POST(self) -> None:
        if not self._begin_method():
            return
        if self.path != MESSAGE_PATH:
            self._plain(404, b"not found")
            return
        gateway = self.gateway
        attempt_id = self.headers.get("x-request-id")
        if attempt_id is not None and (len(attempt_id) > 128 or not attempt_id.isascii()):
            attempt_id = None
        arrival, upstream, duplicate, attempt_number = gateway._arrive(attempt_id)
        states = ["arrived"]
        request_bytes = response_bytes = 0
        streaming = False
        status = 500
        body_guard: Optional[threading.Timer] = None
        attestation_proof: Optional[dict[str, object]] = None
        attestation_binding: Optional[ExpectedPreForwardBinding] = None
        try:
            raw_headers = list(self.headers.raw_items())
            if any(not _valid_relay_header(name, value) for name, value in raw_headers):
                states.append("headers_rejected"); status = 431
                self._plain(status, b"invalid headers"); return
            # This is an exact post-parse bound over logical header name/value bytes,
            # separators and terminating CRLF. The stdlib parser's own 64 KiB line
            # limit applies before this candidate-level aggregate check.
            header_bytes = 2 + sum(
                len(name.encode("latin-1")) + len(value.encode("latin-1")) + 4
                for name, value in raw_headers
            )
            if len(raw_headers) > gateway.config.max_headers or header_bytes > gateway.config.max_header_bytes:
                states.append("headers_rejected"); status = 431
                self._plain(status, b"headers too large"); return
            auth = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth, "Bearer " + gateway.bearer_token):
                states.append("auth_rejected"); status = 401
                self._plain(status, b"unauthorized"); return
            states.append("authenticated")
            attestation_binding = gateway._consume_expected_binding()
            if any(self.headers.get_all(header, []) for header in INTERNAL_HEADERS):
                states.append("request_rejected"); status = 400
                self._plain(status, b"caller-supplied internal binding headers prohibited"); return
            if gateway._synthetic_502_pending() and attestation_binding is None:
                states.append("request_rejected"); status = 409
                self._plain(status, b"pre-forward binding already consumed or unavailable"); return
            transfer_values = self.headers.get_all("Transfer-Encoding", [])
            length_values = self.headers.get_all("Content-Length", [])
            if transfer_values or len(length_values) != 1 or not _CANONICAL_LENGTH.fullmatch(length_values[0]):
                states.append("request_rejected"); status = 400
                self._plain(status, b"invalid request framing"); return
            length = int(length_values[0])
            if length > gateway.config.max_request_bytes:
                states.append("request_rejected"); status = 413
                self._plain(status, b"request too large"); return
            body_guard = _timer(gateway.config.ingress_timeout, self._abort_client)
            body = self.rfile.read(length)
            body_guard.cancel(); body_guard = None
            request_bytes = len(body)
            if len(body) != length:
                states.append("request_incomplete"); status = 400
                try:
                    self._plain(status, b"incomplete request")
                except OSError:
                    pass
                return
            if gateway._claim_synthetic():
                status = gateway.config.synthetic_status
                if status == 502:
                    if attestation_binding is None or gateway._attestation_owner is None:
                        raise RuntimeError("attestation owner or consumed binding unavailable")
                    states.append("rejected_before_forward")
                    attestation_proof = dict(gateway._attestation_owner.sign_consumed(
                        attestation_binding, arrival
                    ))
                    payload = json.dumps({
                        "type": "error",
                        "error": {"type": "api_error", "message": "Synthetic gateway rejection before forward"},
                    }, separators=(",", ":")).encode("ascii")
                    self._bytes(status, payload, "application/json", {"Retry-After": "1"}); return
                states.append("synthetic_fault")
                payload = json.dumps({"type": "error", "error": {"type": "synthetic_gateway_fault"}}, separators=(",", ":")).encode("ascii")
                self._bytes(status, payload, "application/json"); return
            states.append("forwarding")
            upstream = gateway._mark_upstream()
            status, response_bytes, streaming, terminal = self._forward(
                "POST", MESSAGE_PATH, body, raw_headers, allow_cut=True
            )
            states.append(terminal)
        except _ClientCancelled as exc:
            states.append("client_cancelled")
            status = exc.status
            response_bytes = exc.response_bytes
            streaming = exc.streaming
        except http.client.HTTPException:
            states.append("upstream_error"); status = 502
            try:
                self._plain(status, b"upstream unavailable")
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        except _PartialWrite:
            if states[-1] not in {
                "headers_rejected", "auth_rejected", "request_rejected", "request_incomplete",
                "synthetic_fault", "rejected_before_forward", "completed", "upstream_502",
                "forward_cut", "cut_not_reached",
                "response_rejected", "response_limit_cut", "upstream_error",
                "upstream_premature_eof", "post_commit_error", "credential_reflection",
                "client_cancelled",
            }:
                states.append("client_cancelled"); status = 499
        except (BrokenPipeError, ConnectionResetError):
            if states[-1] not in {
                "headers_rejected", "auth_rejected", "request_rejected", "request_incomplete",
                "synthetic_fault", "rejected_before_forward", "completed", "upstream_502",
                "forward_cut", "cut_not_reached",
                "response_rejected", "response_limit_cut", "upstream_error",
                "upstream_premature_eof", "post_commit_error", "credential_reflection",
                "client_cancelled",
            }:
                states.append("client_cancelled"); status = 499
        except (OSError, socket.timeout):
            terminals = {
                "headers_rejected", "auth_rejected", "request_rejected", "request_incomplete",
                "synthetic_fault", "rejected_before_forward", "completed", "upstream_502",
                "forward_cut", "cut_not_reached",
                "response_rejected", "response_limit_cut", "upstream_error",
                "upstream_premature_eof", "post_commit_error", "credential_reflection",
                "client_cancelled",
            }
            if states[-1] not in terminals:
                if states[-1] == "forwarding":
                    states.append("upstream_error"); status = 502
                    try:
                        self._plain(status, b"upstream unavailable")
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                else:
                    states.append("client_cancelled"); status = 499
        finally:
            if body_guard is not None:
                body_guard.cancel()
            gateway._receipt(
                arrival=arrival, upstream=upstream, duplicate=duplicate,
                attempt_number=attempt_number, states=states, status=status,
                request_bytes=request_bytes, response_bytes=response_bytes,
                streaming=streaming,
                pre_forward_attestation=attestation_proof,
            )

    def _forward(
        self, method: str, path: str, body: Optional[bytes],
        request_headers: list[tuple[str, str]], *, allow_cut: bool,
    ) -> tuple[int, int, bool, str]:
        config = self.gateway.config
        upstream_authorization = self.gateway._upstream_authorization
        if upstream_authorization is None:
            raise http.client.HTTPException("upstream authorization unavailable")
        connection = self.gateway._connection_factory(UPSTREAM_HOST, UPSTREAM_PORT, config.connect_timeout)
        self.gateway._register_upstream(connection)
        committed = False
        status = 502
        total = 0
        streaming = False
        response_guard = _timer(config.response_timeout, lambda: (connection.close(), self._abort_client()))
        try:
            nominated = _connection_nominees(request_headers)
            headers: dict[str, str] = {}
            for name, value in request_headers:
                lower = name.lower()
                if lower in SENSITIVE_HEADERS | HOP_HEADERS | INTERNAL_HEADERS | nominated | {"host", "content-length"}:
                    continue
                headers[name] = value
            headers.update({
                "Authorization": "Bearer " + upstream_authorization,
                "Host": f"{UPSTREAM_HOST}:{UPSTREAM_PORT}",
                "Connection": "close",
            })
            if body is not None:
                headers["Content-Length"] = str(len(body))
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            status = response.status
            response_headers = response.getheaders()
            if any(not _valid_relay_header(name, value) for name, value in response_headers):
                self._plain(502, b"invalid upstream headers")
                return 502, 0, False, "response_rejected"
            nominees = _connection_nominees(response_headers)
            length_values = [value for name, value in response_headers if name.lower() == "content-length"]
            transfer_values = [value for name, value in response_headers if name.lower() == "transfer-encoding"]
            transfer_valid = (
                not transfer_values
                or (len(transfer_values) == 1 and transfer_values[0].strip().lower() == "chunked")
            )
            if (
                (length_values and transfer_values)
                or not transfer_valid
                or len(length_values) > 1
                or (length_values and not _CANONICAL_LENGTH.fullmatch(length_values[0]))
            ):
                self._plain(502, b"invalid upstream framing")
                return 502, 0, False, "response_rejected"
            parsed_length = int(length_values[0]) if length_values else None
            media_type = next((value for name, value in response_headers if name.lower() == "content-type"), "")
            streaming = "text/event-stream" in media_type.lower() or parsed_length is None
            if parsed_length is not None and parsed_length > config.max_response_bytes:
                self._plain(502, b"upstream response too large")
                return 502, 0, streaming, "response_rejected"
            cut_mode = allow_cut and config.mode == "forward_then_cut"
            use_chunked = parsed_length is None or cut_mode
            relay_headers: list[tuple[str, str]] = []
            for name, value in response_headers:
                lower = name.lower()
                if lower in SENSITIVE_HEADERS | HOP_HEADERS | nominees | {"content-length", "server", "date"}:
                    continue
                if upstream_authorization in value:
                    self._plain(502, b"upstream credential reflection blocked")
                    return 502, 0, streaming, "credential_reflection"
                relay_headers.append((name, value))
            self.send_response_only(status)
            for name, value in relay_headers:
                self.send_header(name, value)
            if use_chunked:
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header("Content-Length", str(parsed_length))
            self.send_header("Connection", "close")
            self.end_headers()
            committed = True

            limit = config.cut_after_bytes if cut_mode else config.max_response_bytes
            completed_terminal = "upstream_502" if status == 502 else "completed"
            scanner = _ExactCredentialScanner(upstream_authorization)
            read_total = 0

            def emit_scanned(data: bytes) -> None:
                nonlocal total
                if data:
                    self._emit_chunk(data, use_chunked)
                    total += len(data)

            while read_total < limit:
                want = min(config.chunk_bytes, limit - read_total)
                try:
                    chunk = response.read(want)
                except http.client.IncompleteRead as exc:
                    chunk = exc.partial
                    read_total += len(chunk)
                    safe, reflected = scanner.feed(chunk)
                    emit_scanned(safe)
                    if reflected:
                        return status, total, streaming, "credential_reflection"
                    emit_scanned(scanner.finish())
                    return status, total, streaming, "upstream_premature_eof"
                if not chunk:
                    emit_scanned(scanner.finish())
                    if parsed_length is not None and read_total < parsed_length:
                        return status, total, streaming, "upstream_premature_eof"
                    terminal = "cut_not_reached" if cut_mode else completed_terminal
                    if use_chunked:
                        self._emit_end()
                    return status, total, streaming, terminal
                read_total += len(chunk)
                safe, reflected = scanner.feed(chunk)
                emit_scanned(safe)
                if reflected:
                    return status, total, streaming, "credential_reflection"
            emit_scanned(scanner.finish())
            if cut_mode:
                if parsed_length is not None:
                    has_more = parsed_length > read_total
                else:
                    probe = response.read(1)
                    has_more = bool(probe)
                if has_more:
                    return status, total, streaming, "forward_cut"
                self._emit_end()
                return status, total, streaming, "cut_not_reached"
            if parsed_length is None:
                probe = response.read(1)
                if probe:
                    return status, total, streaming, "response_limit_cut"
                self._emit_end()
            return status, total, streaming, completed_terminal
        except _PayloadWriteInterrupted as exc:
            raise _ClientCancelled(status, total + exc.payload_bytes, streaming) from exc
        except _PartialWrite as exc:
            raise _ClientCancelled(status, total, streaming) from exc
        except http.client.HTTPException:
            if committed:
                return status, total, streaming, "post_commit_error"
            raise
        except (BrokenPipeError, ConnectionResetError):
            raise
        except (OSError, socket.timeout, ValueError, AttributeError):
            if committed:
                return status, total, streaming, "post_commit_error"
            raise http.client.HTTPException("upstream stream closed")
        finally:
            response_guard.cancel()
            connection.close()
            self.gateway._unregister_upstream(connection)

    def _emit_chunk(self, chunk: bytes, chunked: bool) -> None:
        try:
            if chunked:
                self._write_all(f"{len(chunk):X}\r\n".encode("ascii"))
                try:
                    self._write_all(chunk)
                except _PartialWrite as exc:
                    raise _PayloadWriteInterrupted(exc.written) from exc
                try:
                    self._write_all(b"\r\n")
                except _PartialWrite as exc:
                    raise _PayloadWriteInterrupted(len(chunk)) from exc
            else:
                try:
                    self._write_all(chunk)
                except _PartialWrite as exc:
                    raise _PayloadWriteInterrupted(exc.written) from exc
        except _PartialWrite as exc:
            raise _PayloadWriteInterrupted(0) from exc

    def _emit_end(self) -> None:
        try:
            self._write_all(b"0\r\n\r\n")
        except _PartialWrite as exc:
            raise _PayloadWriteInterrupted(0) from exc

    def _bytes(
        self, status: int, payload: bytes, content_type: str,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.send_response_only(status)
        self.send_header("Content-Type", content_type)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self._write_all(payload)

    def _plain(self, status: int, payload: bytes) -> None:
        self._bytes(status, payload, "text/plain; charset=utf-8")

    def do_GET(self) -> None:
        if not self._begin_method():
            return
        if self.path != MODELS_PATH:
            self._plain(405 if self.path == MESSAGE_PATH else 404, b"method not allowed")
            return
        gateway = self.gateway
        arrival, upstream, duplicate, attempt_number = gateway._arrive(None)
        states = ["arrived"]
        response_bytes = 0
        streaming = False
        status = 500
        try:
            raw_headers = list(self.headers.raw_items())
            if any(not _valid_relay_header(name, value) for name, value in raw_headers):
                states.append("headers_rejected"); status = 431
                self._plain(status, b"invalid headers"); return
            header_bytes = 2 + sum(
                len(name.encode("latin-1")) + len(value.encode("latin-1")) + 4
                for name, value in raw_headers
            )
            if len(raw_headers) > gateway.config.max_headers or header_bytes > gateway.config.max_header_bytes:
                states.append("headers_rejected"); status = 431
                self._plain(status, b"headers too large"); return
            auth = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth, "Bearer " + gateway.bearer_token):
                states.append("auth_rejected"); status = 401
                self._plain(status, b"unauthorized"); return
            states.append("authenticated")
            if any(self.headers.get_all(header, []) for header in INTERNAL_HEADERS):
                states.append("request_rejected"); status = 400
                self._plain(status, b"caller-supplied internal binding headers prohibited"); return
            transfer_values = self.headers.get_all("Transfer-Encoding", [])
            length_values = self.headers.get_all("Content-Length", [])
            if (
                transfer_values
                or len(length_values) > 1
                or (length_values and length_values[0] != "0")
            ):
                states.append("request_rejected"); status = 400
                self._plain(status, b"GET models request body prohibited"); return
            states.append("forwarding")
            upstream = gateway._mark_upstream()
            status, response_bytes, streaming, terminal = self._forward(
                "GET", MODELS_PATH, None, raw_headers, allow_cut=False
            )
            states.append(terminal)
        except _ClientCancelled as exc:
            states.append("client_cancelled")
            status = exc.status
            response_bytes = exc.response_bytes
            streaming = exc.streaming
        except http.client.HTTPException:
            states.append("upstream_error"); status = 502
            try:
                self._plain(status, b"upstream unavailable")
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        except _PartialWrite:
            if states[-1] not in TERMINAL_STATES:
                states.append("client_cancelled"); status = 499
        except (BrokenPipeError, ConnectionResetError):
            if states[-1] not in TERMINAL_STATES:
                states.append("client_cancelled"); status = 499
        except (OSError, socket.timeout):
            if states[-1] not in TERMINAL_STATES:
                if states[-1] == "forwarding":
                    states.append("upstream_error"); status = 502
                    try:
                        self._plain(status, b"upstream unavailable")
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                else:
                    states.append("client_cancelled"); status = 499
        finally:
            gateway._receipt(
                arrival=arrival, upstream=upstream, duplicate=duplicate,
                attempt_number=attempt_number, states=states, status=status,
                request_bytes=0, response_bytes=response_bytes, streaming=streaming,
                pre_forward_attestation=None, method="GET", path=MODELS_PATH,
                receipt_mode="pass_through",
            )

    def _reject_non_get(self) -> None:
        if not self._begin_method():
            return
        self._plain(404, b"method not allowed")

    do_PUT = _reject_non_get
    do_DELETE = _reject_non_get
    do_PATCH = _reject_non_get
