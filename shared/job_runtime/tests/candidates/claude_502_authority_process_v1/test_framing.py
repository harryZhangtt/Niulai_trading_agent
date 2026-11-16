import struct
import unittest
from ._support import load_package

P = load_package()
from shared.job_runtime.candidates.claude_502_authority_process_v1.canonical import dumps, loads_exact


class FramingTests(unittest.TestCase):
    def test_partial_and_multiple_frames(self):
        raw = P.encode_frame({"a": 1}) + P.encode_frame({"b": [True, None]})
        decoder = P.FrameDecoder(); out = []
        for byte in raw:
            out.extend(decoder.feed(bytes([byte])))
        decoder.finish()
        self.assertEqual(out, [{"a": 1}, {"b": [True, None]}])

    def test_oversize_prefix_rejected_before_payload(self):
        with self.assertRaisesRegex(P.ProtocolError, "FRAME_OVERSIZE"):
            P.FrameDecoder().feed(struct.pack(">I", 65537))

    def test_oversize_encoder(self):
        with self.assertRaisesRegex(P.ProtocolError, "FRAME_OVERSIZE"):
            P.encode_frame({"x": "a" * 65536})

    def test_empty_and_truncated(self):
        with self.assertRaisesRegex(P.ProtocolError, "FRAME_EMPTY"):
            P.FrameDecoder().feed(b"\0\0\0\0")
        d = P.FrameDecoder(); d.feed(b"\0\0\0\5{}")
        with self.assertRaisesRegex(P.ProtocolError, "FRAME_TRUNCATED"):
            d.finish()

    def test_duplicate_keys(self):
        with self.assertRaisesRegex(P.ProtocolError, "JSON_DUPLICATE_KEY"):
            loads_exact(b'{"a":1,"a":2}')

    def test_noncanonical_spacing_order_and_escape(self):
        for raw in (b'{"a": 1}', b'{"b":1,"a":2}', b'{"x":"\\u0061"}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(P.ProtocolError, "JSON_NONCANONICAL"):
                loads_exact(raw)

    def test_invalid_utf8_float_and_nonfinite(self):
        cases = ((b'"\xff"', "JSON_INVALID"), (b'{"x":1.0}', "JSON_FLOAT_REJECTED"), (b'{"x":NaN}', "JSON_NONFINITE_NUMBER"))
        for raw, code in cases:
            with self.subTest(raw=raw), self.assertRaisesRegex(P.ProtocolError, code):
                loads_exact(raw)

    def test_python_type_rejections(self):
        for value in (1.5, b"bytes", {1: "x"}, {"x": (1,)}):
            with self.subTest(value=value), self.assertRaises(P.ProtocolError):
                dumps(value)

    def test_nonbytes_and_depth(self):
        with self.assertRaisesRegex(P.ProtocolError, "JSON_BYTES_REQUIRED"):
            loads_exact("{}")
        value = None
        for _ in range(26): value = [value]
        with self.assertRaisesRegex(P.ProtocolError, "JSON_DEPTH_EXCEEDED"):
            dumps(value)

class BoundedReadTests(unittest.TestCase):
    def test_single_incoming_chunk_bound_before_extend(self):
        decoder=P.FrameDecoder()
        with self.assertRaisesRegex(P.ProtocolError,"FRAME_READ_BOUND_EXCEEDED"):
            decoder.feed(b"x"*(65536+5))
        self.assertEqual(len(decoder._buffer),0)
