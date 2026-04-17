#
# Columbia University - CSEE 4119 Computer Networks
# Assignment 2 - Mini Reliable Transport Protocol
#
# mrt_server.py - defining server APIs of the mini reliable transport
# protocol
#

from __future__ import annotations

import socket
import threading
import time
from collections import deque

try:
    from mrt_common import (
        FLAG_SYN, FLAG_ACK, FLAG_FIN,
        HEADER_SIZE,
        DEFAULT_RTO, SOCKET_TIMEOUT, OVERALL_TIMEOUT, CLOSE_TIMEOUT,
        Segment, SegmentLogger,
    )
except ImportError:
    from lab2.mrt_common import (
        FLAG_SYN, FLAG_ACK, FLAG_FIN,
        HEADER_SIZE,
        DEFAULT_RTO, SOCKET_TIMEOUT, OVERALL_TIMEOUT, CLOSE_TIMEOUT,
        Segment, SegmentLogger,
    )


class Server:
    """
    MRT protocol server — Go-Back-N receiver with cumulative ACKs,
    checksum integrity, and flow-control via advertised receive window.
    """

    # ─── public API ───────────────────────────────────────────────────

    def init(self, src_port, receive_buffer_size):
        """
        Initialize the server, create the server socket, and configure
        the receive buffer.

        arguments:
        src_port            -- port the server listens on
        receive_buffer_size -- maximum bytes the receive buffer can hold
        """
        self.src_port = src_port
        self.buf_size = max(receive_buffer_size, 1)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", src_port))
        self.sock.settimeout(SOCKET_TIMEOUT)

        self.logger = SegmentLogger(src_port)

        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

        self.running = True
        self.state = "LISTEN"
        self.peer = None
        self.conn = None

        # server sequence numbers
        self.srv_isn = 0
        self.srv_next = 1       # next server seq (ISN + 1 for SYN)

        # client tracking
        self.expected_seq = 0   # next in-order byte expected from client

        # application data buffer
        self.data_buf = bytearray()
        self.data_chunks = deque()   # (remaining_payload_bytes, reserved_cost)
        self.client_fin = False
        self.recv_queue = deque()
        self.recv_queue_bytes = 0
        self.buffered_cost = 0

        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._segment_thread = threading.Thread(target=self._segment_loop, daemon=True)
        self._recv_thread.start()
        self._segment_thread.start()

    def accept(self):
        """
        Accept a client request.  Blocks until a client connection is
        established.

        return:
        the connection handle for this client
        """
        with self._cv:
            deadline = time.monotonic() + OVERALL_TIMEOUT
            while self.state not in ("ESTABLISHED", "CLOSE_WAIT", "CLOSED") \
                    and self.running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("accept: timed out")
                self._cv.wait(timeout=min(remaining, 0.5))
            return self.conn

    def receive(self, conn, length):
        """
        Receive data from the given client.  Blocks until *length* bytes
        are available.  Returned data is guaranteed to be in its original
        order.

        arguments:
        conn   -- connection handle (from accept)
        length -- number of bytes to receive

        return:
        bytes object of exactly *length* bytes
        """
        out = bytearray()

        with self._cv:
            deadline = time.monotonic() + OVERALL_TIMEOUT

            while len(out) < length:
                # wait until the data buffer has something to read
                while not self.data_buf:
                    if not self.running \
                            or self.client_fin \
                            or self.state in ("CLOSED",):
                        if len(out) < length:
                            raise ConnectionError(
                                "receive: connection closed before all "
                                "data was available"
                            )
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("receive: timed out")
                    self._cv.wait(timeout=min(remaining, 0.5))

                # consume available bytes
                take = min(length - len(out), len(self.data_buf))
                out.extend(self.data_buf[:take])
                del self.data_buf[:take]
                self._release_buffered_cost(take)
                deadline = time.monotonic() + OVERALL_TIMEOUT  # progress

        return bytes(out)

    def close(self):
        """
        Close the current connection.  Blocks until teardown completes
        or times out.
        """
        with self._cv:
            if self.peer is None or self.state == "LISTEN":
                self._cleanup()
                return

            if self.state in ("ESTABLISHED", "CLOSE_WAIT"):
                self.state = "LAST_ACK"

            # retransmit FIN until ACKed or timeout
            deadline = time.monotonic() + CLOSE_TIMEOUT
            first = True
            while self.state not in ("CLOSED",) and self.running:
                fin = Segment(
                    seq=self.srv_next,
                    ack=self.expected_seq,
                    flags=FLAG_FIN | FLAG_ACK,
                    rwnd=self._rwnd(),
                )
                self._raw_send(
                    fin, self.peer, "SEND" if first else "RETX",
                )
                first = False

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cv.wait(timeout=min(remaining, DEFAULT_RTO))

        self._cleanup()

    # ─── background receiver thread ──────────────────────────────────

    def _recv_loop(self):
        """Receive segments and enqueue them into the bounded receive buffer."""
        while self.running:
            try:
                raw, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break

            with self._cv:
                seg = Segment.from_bytes(raw)
                if seg is None:
                    self.logger.log(
                        addr[1], self.src_port, -1, -1, 0, len(raw), "DROP",
                    )
                    if addr and self.peer and addr == self.peer \
                            and self.state in ("ESTABLISHED", "CLOSE_WAIT"):
                        dup = Segment(
                            seq=self.srv_next,
                            ack=self.expected_seq,
                            flags=FLAG_ACK,
                            rwnd=self._rwnd(),
                        )
                        self._raw_send(dup, self.peer, "SEND")
                else:
                    self.logger.log(
                        addr[1], self.src_port, seg.seq, seg.ack,
                        seg.flags, len(seg.payload), "RECV",
                    )
                    cost = len(raw) if seg.payload else 0
                    if cost == 0 or self.recv_queue_bytes + cost <= self.buf_size:
                        self.recv_queue.append((seg, addr, cost))
                        self.recv_queue_bytes += cost
                    elif addr == self.peer and self.state in ("ESTABLISHED", "CLOSE_WAIT"):
                        ack = Segment(
                            seq=self.srv_next,
                            ack=self.expected_seq,
                            flags=FLAG_ACK,
                            rwnd=self._rwnd(),
                        )
                        self._raw_send(ack, self.peer, "SEND")
                self._cv.notify_all()

    def _segment_loop(self):
        """Process queued segments and advance the protocol state machine."""
        while self.running:
            with self._cv:
                while self.running and not self.recv_queue:
                    self._cv.wait(timeout=SOCKET_TIMEOUT)
                if not self.running:
                    break
                seg, addr, cost = self.recv_queue.popleft()
                self._handle(seg, addr, cost)
                self._cv.notify_all()

    # ─── segment handling state machine ──────────────────────────────

    def _handle(self, seg, addr, cost=0):
        """Process one valid segment.  Caller holds _lock."""

        # ── LISTEN ────────────────────────────────────────────────────
        if self.state == "LISTEN":
            if seg.flags & FLAG_SYN:
                self.peer = addr
                self.conn = addr
                self.expected_seq = seg.seq + 1  # SYN = 1 seq byte
                self.state = "SYN_RCVD"
                sa = Segment(
                    seq=self.srv_isn, ack=self.expected_seq,
                    flags=FLAG_SYN | FLAG_ACK, rwnd=self._rwnd(),
                )
                self._raw_send(sa, addr, "SEND")
            else:
                self.recv_queue_bytes -= cost
            return

        # ignore segments from unknown peers
        if addr != self.peer:
            self.recv_queue_bytes -= cost
            return

        # ── SYN_RCVD ─────────────────────────────────────────────────
        if self.state == "SYN_RCVD":
            if seg.flags & FLAG_SYN:
                # duplicate SYN — retransmit SYN-ACK
                sa = Segment(
                    seq=self.srv_isn, ack=self.expected_seq,
                    flags=FLAG_SYN | FLAG_ACK, rwnd=self._rwnd(),
                )
                self._raw_send(sa, addr, "RETX")
                return
            if seg.flags & FLAG_ACK:
                self.state = "ESTABLISHED"
                # fall through: segment may also carry data or FIN
                if not seg.payload and not (seg.flags & FLAG_FIN):
                    self.recv_queue_bytes -= cost
                    return
            else:
                self.recv_queue_bytes -= cost
                return

        # ── ESTABLISHED / CLOSE_WAIT ──────────────────────────────────
        if self.state in ("ESTABLISHED", "CLOSE_WAIT"):
            # client FIN
            if seg.flags & FLAG_FIN:
                self.recv_queue_bytes -= cost
                if seg.seq == self.expected_seq:
                    self.expected_seq += 1
                    self.client_fin = True
                    if self.state == "ESTABLISHED":
                        self.state = "CLOSE_WAIT"
                # ACK (always with current expected_seq)
                ack = Segment(
                    seq=self.srv_next, ack=self.expected_seq,
                    flags=FLAG_ACK, rwnd=self._rwnd(),
                )
                self._raw_send(ack, addr, "SEND")
                return

            # data segment
            if seg.payload:
                self.recv_queue_bytes -= cost
                if seg.seq == self.expected_seq:
                    self.data_buf.extend(seg.payload)
                    self.data_chunks.append([len(seg.payload), cost])
                    self.buffered_cost += cost
                    self.expected_seq += len(seg.payload)
                # cumulative ACK
                ack = Segment(
                    seq=self.srv_next, ack=self.expected_seq,
                    flags=FLAG_ACK, rwnd=self._rwnd(),
                )
                self._raw_send(ack, addr, "SEND")
                return

            # pure ACK (handshake completion, etc.) — nothing to do
            self.recv_queue_bytes -= cost
            return

        # ── LAST_ACK ──────────────────────────────────────────────────
        if self.state == "LAST_ACK":
            if seg.flags & FLAG_FIN:
                # re-ACK client's FIN
                if seg.seq == self.expected_seq:
                    self.expected_seq += 1
                    self.client_fin = True
                ack = Segment(
                    seq=self.srv_next, ack=self.expected_seq,
                    flags=FLAG_FIN | FLAG_ACK, rwnd=0,
                )
                self._raw_send(ack, addr, "SEND")
                self.recv_queue_bytes -= cost
                return
            if seg.flags & FLAG_ACK and seg.ack > self.srv_next:
                self.recv_queue_bytes -= cost
                self.state = "CLOSED"
                return
            self.recv_queue_bytes -= cost
            return

        # ── CLOSED ────────────────────────────────────────────────────
        if self.state == "CLOSED":
            if seg.flags & FLAG_FIN:
                ack = Segment(
                    seq=self.srv_next, ack=self.expected_seq,
                    flags=FLAG_ACK, rwnd=0,
                )
                self._raw_send(ack, addr, "SEND")
            self.recv_queue_bytes -= cost

    # ─── helpers ──────────────────────────────────────────────────────

    def _rwnd(self):
        """Available receive-buffer space."""
        return max(0, self.buf_size - self.recv_queue_bytes - self.buffered_cost)

    def _release_buffered_cost(self, consumed):
        """
        Release receive-buffer budget for bytes delivered to the application.

        arguments:
        consumed -- number of application bytes removed from data_buf
        """
        while consumed > 0 and self.data_chunks:
            chunk_len, chunk_cost = self.data_chunks[0]
            take = min(consumed, chunk_len)
            chunk_len -= take
            consumed -= take
            if chunk_len == 0:
                self.buffered_cost -= chunk_cost
                self.data_chunks.popleft()
            else:
                self.data_chunks[0][0] = chunk_len

    def _raw_send(self, seg, addr, note):
        """Send one segment and log it."""
        try:
            self.sock.sendto(seg.to_bytes(), addr)
        except OSError:
            return
        self.logger.log(
            self.src_port, addr[1], seg.seq, seg.ack,
            seg.flags, len(seg.payload), note,
        )

    def _cleanup(self):
        """Stop the background thread and close the socket."""
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass
        with self._cv:
            self._cv.notify_all()
        self._recv_thread.join(timeout=1)
        self._segment_thread.join(timeout=1)
