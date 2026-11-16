"""Fixed direct transport: one request, no redirect/retry/replay machinery."""
from __future__ import annotations
from dataclasses import dataclass
import http.client
import socket
import time
from typing import Optional
from .contracts import MAX_BODY_BYTES, TARGET

_TIMEOUT_SECONDS = 5.0

class TransportError(RuntimeError):
    def __init__(self, code: str, status: int = 599, *, body_sha256: Optional[str] = None, body_bytes: int = 0) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.body_sha256 = body_sha256
        self.body_bytes = body_bytes

@dataclass(frozen=True)
class _Endpoint:
    host: str
    port: int
    tls: bool
    origin_kind: str

@dataclass(frozen=True)
class ForwardResult:
    status: int
    body: bytes
    origin_kind: str
    host: str
    tls_hostname_verified: bool

def _fixed_endpoint() -> _Endpoint:
    return _Endpoint("chatgpt.com", 443, True, "verified_provider_https")

def _connection(endpoint: _Endpoint, timeout: float) -> http.client.HTTPConnection:
    cls = http.client.HTTPSConnection if endpoint.tls else http.client.HTTPConnection
    return cls(endpoint.host, endpoint.port, timeout=timeout)

def forward_once(material: bytearray) -> ForwardResult:
    if type(material) is not bytearray or not material:
        raise TransportError("AUTH_MATERIAL_REJECTED")
    endpoint = _fixed_endpoint()
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    connection: Optional[http.client.HTTPConnection] = None
    response: Optional[http.client.HTTPResponse] = None
    header = bytearray(b"Bearer ")
    header.extend(material)
    try:
        connection = _connection(endpoint, _TIMEOUT_SECONDS)
        header_rejected = False
        try:
            connection.putrequest("GET", TARGET, skip_accept_encoding=True)
            connection.putheader("Authorization", header)
            connection.endheaders()
        except ValueError:
            header_rejected = True
        if header_rejected:
            raise TransportError("AUTH_HEADER_REJECTED")
        for index in range(len(header)):
            header[index] = 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TransportError("TIMEOUT")
        if connection.sock is not None:
            connection.sock.settimeout(remaining)
        response = connection.getresponse()
        if time.monotonic() >= deadline:
            raise TransportError("TIMEOUT", response.status)
        body_buffer = bytearray()
        body_view = None
        chunk = b""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportError("TIMEOUT")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(65536, MAX_BODY_BYTES + 1 - len(body_buffer)))
            if not chunk:
                break
            body_buffer.extend(chunk)
            if len(body_buffer) > MAX_BODY_BYTES:
                for index in range(len(body_buffer)):
                    body_buffer[index] = 0
                body_buffer.clear()
                chunk = b""
                body_view = None
                oversize_status = response.status
                response.close()
                response = None
                connection.close()
                connection = None
                raise TransportError("BODY_OVERSIZE", oversize_status, body_bytes=MAX_BODY_BYTES)
        body = bytes(body_buffer)
        for index in range(len(body_buffer)):
            body_buffer[index] = 0
        body_buffer.clear()
        chunk = b""
        body_view = None
        return ForwardResult(response.status, body, endpoint.origin_kind,
                             endpoint.host, endpoint.tls and endpoint.host == "chatgpt.com")
    except TransportError:
        raise
    except (OSError, socket.timeout, http.client.HTTPException) as exc:
        raise TransportError("TRANSPORT_FAILURE") from exc
    finally:
        for index in range(len(header)):
            header[index] = 0
        if response is not None:
            response.close()
        if connection is not None:
            connection.close()
