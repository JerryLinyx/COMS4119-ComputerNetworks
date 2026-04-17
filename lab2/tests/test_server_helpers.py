import threading
import unittest
from collections import deque

from lab2.mrt_common import FLAG_ACK, Segment
from lab2.mrt_server import Server


class ServerHelperTests(unittest.TestCase):
    def test_last_ack_closes_when_client_ack_arrives(self):
        server = Server()
        server._lock = threading.Lock()
        server._cv = threading.Condition(server._lock)
        server.state = "LAST_ACK"
        server.peer = ("127.0.0.1", 5000)
        server.srv_next = 1
        server.expected_seq = 40
        server.recv_queue_bytes = 0
        server.buffered_cost = 0
        server.data_chunks = deque()

        sent = []
        server._raw_send = lambda segment, addr, note: sent.append((segment, addr, note))

        server._handle(Segment(seq=80, ack=2, flags=FLAG_ACK), server.peer)

        self.assertEqual(server.state, "CLOSED")
        self.assertEqual(sent, [])

    def test_receive_raises_when_client_has_closed_and_no_data_remains(self):
        server = Server()
        server._lock = threading.Lock()
        server._cv = threading.Condition(server._lock)
        server.running = True
        server.client_fin = True
        server.state = "CLOSE_WAIT"
        server.data_buf = bytearray()

        with self.assertRaises(ConnectionError):
            server.receive(("127.0.0.1", 5000), 10)


if __name__ == "__main__":
    unittest.main()
