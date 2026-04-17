import unittest

from lab2.mrt_common import FLAG_ACK, FLAG_SYN, Segment


class SegmentTests(unittest.TestCase):
    def test_segment_round_trip_preserves_fields(self):
        segment = Segment(seq=100, ack=55, flags=FLAG_SYN | FLAG_ACK, rwnd=4096, payload=b"hello")

        parsed = Segment.from_bytes(segment.to_bytes())

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.seq, 100)
        self.assertEqual(parsed.ack, 55)
        self.assertEqual(parsed.flags, FLAG_SYN | FLAG_ACK)
        self.assertEqual(parsed.rwnd, 4096)
        self.assertEqual(parsed.payload, b"hello")

    def test_corrupted_segment_is_rejected(self):
        raw = bytearray(Segment(seq=1, ack=0, flags=0, rwnd=1024, payload=b"payload").to_bytes())
        raw[-1] ^= 0x01

        self.assertIsNone(Segment.from_bytes(bytes(raw)))

    def test_reserved_field_corruption_is_rejected(self):
        raw = bytearray(Segment(seq=7, ack=3, flags=FLAG_ACK, rwnd=32, payload=b"").to_bytes())
        raw[-1] ^= 0x01

        self.assertIsNone(Segment.from_bytes(bytes(raw)))


if __name__ == "__main__":
    unittest.main()
