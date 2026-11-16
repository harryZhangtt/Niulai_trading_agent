"""Request-local numeric-loopback Claude Ferry with complete typed identity."""
from __future__ import annotations
import http.server
import socket
import threading
from typing import Any

from .contracts import (
    FERRY, FERRY_HOST, FERRY_PATH, MODEL, PROVIDER, canonical_bytes, sha256_bytes,
)


class LoopbackFerry:
    def __init__(self, fingerprint: str):
        self.fingerprint = fingerprint
        self.admissions = 0
        self.upstream_attempts = 0
        self.second_rejections = 0
        self._server = None
        self._thread = None
        self.port = 0
        self._lock = threading.Lock()

    def start(self) -> int:
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                with outer._lock:
                    if self.path != FERRY_PATH:
                        body = b'{"error":"PATH_REJECTED"}'
                        status = 404
                    elif outer.admissions:
                        outer.second_rejections += 1
                        body = b'{"error":"SECOND_REQUEST_REJECTED"}'
                        status = 409
                    elif self.headers.get("X-R6-Fingerprint") != outer.fingerprint:
                        body = b'{"error":"FINGERPRINT_REJECTED"}'
                        status = 400
                    else:
                        outer.admissions = 1
                        outer.upstream_attempts = 1
                        status = 200
                        body = canonical_bytes({
                            "model": MODEL, "provider": PROVIDER,
                            "request_id": "synthetic-loopback", "type": "message_stop",
                        }) + b"\n"
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = http.server.ThreadingHTTPServer((FERRY_HOST, 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True,
            name="r6-claude-ferry-provider-free-v4")
        self._thread.start()
        return self.port

    def snapshot(self, listener_closed: bool = False,
                 cleanup_exception: bool = False) -> dict:
        return {
            "provider": PROVIDER, "transport": FERRY, "host": FERRY_HOST,
            "path": FERRY_PATH, "model": MODEL, "admissions": self.admissions,
            "upstream_attempts": self.upstream_attempts,
            "second_rejections": self.second_rejections,
            "listener_closed": listener_closed, "status_calls": 0,
            "request_fingerprint_sha256": sha256_bytes(self.fingerprint.encode("ascii")),
            "cleanup_exception": cleanup_exception,
        }

    def close(self) -> dict:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        probe = socket.socket()
        try:
            probe.settimeout(0.1)
            closed = probe.connect_ex((FERRY_HOST, self.port)) != 0
        finally:
            probe.close()
        return self.snapshot(listener_closed=closed)
