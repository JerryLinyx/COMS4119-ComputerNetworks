from collections import OrderedDict, deque
import threading
import time
import unittest

from lab2.mrt_client import Client
from lab2.mrt_common import FLAG_ACK, FLAG_FIN, FLAG_PSH, Segment


class ClientHelperTests(unittest.TestCase):
    def test_flush_window_uses_one_byte_zero_window_probe(self):
        client = Client()
        client.pending = deque(
            [Segment(seq=20, ack=5, flags=FLAG_PSH | FLAG_ACK, payload=b"hello")]
        )
        client.segment_size = 64
        client.unacked = OrderedDict()
        client.window_bytes = 0xFFFF
        client.remote_rwnd = 0
        client.timer_deadline = None
        client.rto = 0.25

        sent = []
        client._raw_send = lambda segment, note: sent.append((segment, note))

        client._flush_window()

        self.assertEqual(len(sent), 1)
        probe, note = sent[0]
        self.assertEqual(note, "SEND")
        self.assertEqual(probe.seq, 20)
        self.assertEqual(probe.payload, b"h")
        self.assertIn(20, client.unacked)
        self.assertEqual(client.pending[0].seq, 21)
        self.assertEqual(client.pending[0].payload, b"ello")

    def test_flush_window_respects_advertised_window_without_fixed_five_segment_cap(self):
        client = Client()
        client.pending = deque(
            [
                Segment(seq=1 + 1440 * i, ack=0, flags=FLAG_PSH | FLAG_ACK, payload=b"x" * 1440)
                for i in range(20)
            ]
        )
        client.segment_size = 1460
        client.unacked = OrderedDict()
        client.window_bytes = 0xFFFF
        client.remote_rwnd = 20000
        client.timer_deadline = None
        client.rto = 0.25

        sent = []
        client._raw_send = lambda segment, note: sent.append((segment, note))

        client._flush_window()

        self.assertGreater(len(sent), 5)
        self.assertTrue(all(len(segment.payload) == 1440 for segment, _ in sent))

    def test_time_wait_acknowledges_duplicate_fin(self):
        client = Client()
        client.state = "TIME_WAIT"
        client.next_seq = 77
        client.server_ack = 0

        sent = []
        client._raw_send = lambda segment, note: sent.append((segment, note))

        client._handle(Segment(seq=50, ack=0, flags=FLAG_FIN))

        self.assertEqual(client.server_ack, 51)
        self.assertEqual(len(sent), 1)
        ack_segment, note = sent[0]
        self.assertEqual(note, "SEND")
        self.assertEqual(ack_segment.seq, 77)
        self.assertEqual(ack_segment.ack, 51)
        self.assertEqual(ack_segment.flags, FLAG_ACK)

    def test_close_wait_acknowledges_duplicate_fin(self):
        client = Client()
        client.state = "CLOSE_WAIT"
        client.next_seq = 91
        client.server_ack = 0

        sent = []
        client._raw_send = lambda segment, note: sent.append((segment, note))

        client._handle(Segment(seq=12, ack=0, flags=FLAG_FIN))

        self.assertEqual(client.server_ack, 13)
        self.assertEqual(len(sent), 1)
        ack_segment, note = sent[0]
        self.assertEqual(note, "SEND")
        self.assertEqual(ack_segment.seq, 91)
        self.assertEqual(ack_segment.ack, 13)
        self.assertEqual(ack_segment.flags, FLAG_ACK)

    def test_send_exits_when_connection_leaves_established_state(self):
        client = Client()
        client._lock = threading.Lock()
        client._cv = threading.Condition(client._lock)
        client.state = "ESTABLISHED"
        client.running = True
        client.max_payload = 16
        client.pending = deque()
        client.unacked = OrderedDict()
        client.next_seq = 1
        client.server_ack = 0
        client.send_base = 1
        client.segment_size = 36
        client.window_bytes = 0xFFFF
        client.remote_rwnd = 32
        client.timer_deadline = None
        client.rto = 0.25
        client._raw_send = lambda segment, note: None

        result = {}

        def worker():
            try:
                client.send(b"a" * 32)
            except Exception as exc:
                result["error"] = type(exc).__name__

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        time.sleep(0.1)
        with client._cv:
            client.state = "CLOSE_WAIT"
            client._cv.notify_all()
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result.get("error"), "ConnectionError")


if __name__ == "__main__":
    unittest.main()
