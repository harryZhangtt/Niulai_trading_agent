"""Canonical four-byte big-endian length-prefixed JSON frames."""
import struct
from .canonical import dumps, loads_exact
from .errors import ProtocolError

MAX_FRAME_BYTES = 65536


def encode_frame(value):
    payload = dumps(value)
    if len(payload) > MAX_FRAME_BYTES:
        raise ProtocolError("FRAME_OVERSIZE")
    return struct.pack(">I", len(payload)) + payload


class FrameDecoder:
    def __init__(self):
        self._buffer = bytearray()
        self._expected = None

    def feed(self, chunk):
        if type(chunk) is not bytes:
            raise ProtocolError("FRAME_BYTES_REQUIRED")
        if len(self._buffer) + len(chunk) > MAX_FRAME_BYTES + 4:
            raise ProtocolError("FRAME_READ_BOUND_EXCEEDED")
        self._buffer.extend(chunk)
        frames = []
        while True:
            if self._expected is None:
                if len(self._buffer) < 4:
                    break
                self._expected = struct.unpack(">I", self._buffer[:4])[0]
                del self._buffer[:4]
                if self._expected > MAX_FRAME_BYTES:
                    self._buffer.clear()
                    self._expected = None
                    raise ProtocolError("FRAME_OVERSIZE")
                if self._expected == 0:
                    self._expected = None
                    raise ProtocolError("FRAME_EMPTY")
            if len(self._buffer) < self._expected:
                break
            raw = bytes(self._buffer[:self._expected])
            del self._buffer[:self._expected]
            self._expected = None
            frames.append(loads_exact(raw))
        return frames

    def finish(self):
        if self._expected is not None or self._buffer:
            raise ProtocolError("FRAME_TRUNCATED")
