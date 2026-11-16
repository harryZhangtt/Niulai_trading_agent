"""In-process byte transport for protocol tests; performs no OS I/O."""
from .errors import ProtocolError


class _Endpoint:
    def __init__(self, peer_uid):
        self.peer_uid = peer_uid
        self._peer = None
        self._incoming = bytearray()
        self.closed = False

    def send(self, data, chunk_size=None):
        if self.closed or self._peer is None or self._peer.closed:
            raise ProtocolError("TRANSPORT_CLOSED")
        if type(data) is not bytes:
            raise ProtocolError("TRANSPORT_BYTES_REQUIRED")
        size = len(data) if chunk_size is None else chunk_size
        if type(size) is not int or size < 1:
            raise ProtocolError("TRANSPORT_CHUNK_INVALID")
        for pos in range(0, len(data), size):
            part=data[pos:pos + size]
            if len(self._peer._incoming)+len(part)>65540:
                raise ProtocolError("TRANSPORT_READ_BOUND_EXCEEDED")
            self._peer._incoming.extend(part)

    def receive(self):
        data = bytes(self._incoming)
        self._incoming.clear()
        return data

    def close(self):
        self.closed = True
        for i in range(len(self._incoming)):
            self._incoming[i] = 0
        self._incoming.clear()


class MemoryTransport:
    @staticmethod
    def pair(owner_uid):
        if type(owner_uid) is not int or owner_uid < 0:
            raise ProtocolError("PEER_UID_INVALID")
        client = _Endpoint(owner_uid)
        server = _Endpoint(owner_uid)
        client._peer = server
        server._peer = client
        return client, server
