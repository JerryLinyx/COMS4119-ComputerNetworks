#
# Columbia University - CSEE 4119 Computer Networks
# Assignment 2 - Mini Reliable Transport Protocol
#
# mrt_client.py - defining client APIs of the mini reliable transport
# protocol
#

from __future__ import annotations

import socket
import threading
import time
from collections import OrderedDict, deque

try:
    from mrt_common import (
        FLAG_SYN, FLAG_ACK, FLAG_FIN, FLAG_PSH,
        HEADER_SIZE,
        DEFAULT_RTO, SOCKET_TIMEOUT, OVERALL_TIMEOUT, CLOSE_TIMEOUT,
        Segment, SegmentLogger,
    )
except ImportError:
    from lab2.mrt_common import (
        FLAG_SYN, FLAG_ACK, FLAG_FIN, FLAG_PSH,
        HEADER_SIZE,
        DEFAULT_RTO, SOCKET_TIMEOUT, OVERALL_TIMEOUT, CLOSE_TIMEOUT,
        Segment, SegmentLogger,
    )


class Client:
    """
    MRT protocol client — Go-Back-N sender with sliding window,
    checksum integrity, and receiver-advertised flow control.
    """

    # ─── public API ───────────────────────────────────────────────────

    def init(self, src_port, dst_addr, dst_port, segment_size):
        """
        Initialize the client, create the client UDP channel.

        arguments:
        src_port     -- local port for sending segments
        dst_addr     -- address of the server / network simulator
        dst_port     -- port of the server / network simulator
        segment_size -- maximum segment size (header + payload)
        """
        self.src_port = src_port
        self.dst_addr = dst_addr
        self.dst_port = dst_port
        self.peer = (dst_addr, dst_port)
        self.segment_size = segment_size
        self.max_payload = max(1, segment_size - HEADER_SIZE)
        self.window_bytes = 0xFFFF

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", src_port))
        self.sock.settimeout(SOCKET_TIMEOUT)

        self.logger = SegmentLogger(src_port)

        # single lock + condition for all shared state
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

        self.running = True
        self.state = "CLOSED"

        # sequence tracking
        self.send_base = 0          # first un-ACKed byte
        self.next_seq = 0           # next byte number to assign
        self.server_ack = 0         # next expected seq FROM server (our ACK field)
        self.remote_rwnd = 0xFFFF   # receiver-advertised window
        self.got_server_fin = False

        # GBN window
        self.unacked = OrderedDict()  # seq -> Segment
        self.pending = deque()        # segments queued but not yet in window
        self.timer_deadline = None
        self.rto = DEFAULT_RTO

        # background receiver
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def connect(self):
        """
        Connect to the server (3-way handshake).
        Blocks until the connection is established.
        """
        with self._cv:
            self.state = "SYN_SENT"
            self.next_seq = 1  # SYN consumes seq 0
            syn = Segment(seq=0, flags=FLAG_SYN)
            self._raw_send(syn, "SEND")
            self.timer_deadline = time.monotonic() + self.rto

            deadline = time.monotonic() + OVERALL_TIMEOUT
            while self.state == "SYN_SENT" and self.running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("connect: timed out")
                self._cv.wait(timeout=min(remaining, 0.5))

            if self.state != "ESTABLISHED":
                raise ConnectionError("connect: failed")

    def send(self, data):
        """
        Send a chunk of data of arbitrary size to the server.
        Blocks until all data is acknowledged.

        arguments:
        data -- bytes to send

        return:
        number of bytes sent
        """
        if not data:
            return 0

        with self._cv:
            if self.state != "ESTABLISHED":
                raise ConnectionError("send: not connected")

            # fragment application data into segments
            for i in range(0, len(data), self.max_payload):
                chunk = data[i : i + self.max_payload]
                seg = Segment(
                    seq=self.next_seq,
                    ack=self.server_ack,
                    flags=FLAG_PSH | FLAG_ACK,
                    payload=chunk,
                )
                self.pending.append(seg)
                self.next_seq += len(chunk)

            target = self.next_seq
            self._flush_window()

            # wait until every byte is cumulatively ACKed
            deadline = time.monotonic() + OVERALL_TIMEOUT
            while self.send_base < target:
                if self.state != "ESTABLISHED" or not self.running:
                    raise ConnectionError("send: connection lost")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("send: timed out")
                self._cv.wait(timeout=min(remaining, 0.5))

        return len(data)

    def close(self):
        """
        Close the connection (FIN handshake).
        Blocks until the connection is fully torn down.
        """
        with self._cv:
            # drain any pending / un-ACKed data first
            deadline = time.monotonic() + OVERALL_TIMEOUT
            while (self.pending or self.unacked) \
                    and self.running and self.state == "ESTABLISHED":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cv.wait(timeout=min(remaining, 0.5))

            if self.state not in ("ESTABLISHED", "CLOSE_WAIT"):
                self._cleanup()
                return

            # send FIN
            self.state = "FIN_WAIT"
            self.got_server_fin = False
            fin_seq = self.next_seq
            self.next_seq += 1
            fin = Segment(seq=fin_seq, ack=self.server_ack, flags=FLAG_FIN)
            self.unacked[fin_seq] = fin
            self._raw_send(fin, "SEND")
            self.timer_deadline = time.monotonic() + self.rto

            # wait for our FIN to be ACKed and for the server's FIN
            deadline = time.monotonic() + CLOSE_TIMEOUT
            while self.state not in ("TIME_WAIT", "CLOSED") and self.running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cv.wait(timeout=min(remaining, 0.5))

            # brief TIME_WAIT so duplicate FINs can be re-ACKed
            if self.state == "TIME_WAIT":
                self._cv.wait(timeout=self.rto * 2)

        self._cleanup()

    # ─── background receiver thread ──────────────────────────────────

    def _recv_loop(self):
        """Receive segments, process ACKs, retransmit, and slide the window."""
        syn = Segment(seq=0, flags=FLAG_SYN)  # cached for SYN retransmit

        while self.running:
            # 1. non-blocking receive (no lock held)
            seg = None
            try:
                raw, addr = self.sock.recvfrom(65535)
                seg = Segment.from_bytes(raw)
                if seg is None:
                    self.logger.log(
                        addr[1], self.src_port, -1, -1, 0, len(raw), "DROP"
                    )
                else:
                    self.logger.log(
                        addr[1], self.src_port, seg.seq, seg.ack,
                        seg.flags, len(seg.payload), "RECV",
                    )
            except socket.timeout:
                pass
            except OSError:
                break

            # 2. process under lock
            with self._cv:
                if seg is not None:
                    self._handle(seg)

                # 3. timer-based retransmission
                now = time.monotonic()
                if self.timer_deadline is not None and now >= self.timer_deadline:
                    if self.state == "SYN_SENT":
                        self._raw_send(syn, "RETX")
                        self.timer_deadline = now + self.rto
                    elif self.state in ("ESTABLISHED", "FIN_WAIT"):
                        self._retransmit()

                # 4. slide the window (send new pending segments)
                if self.state == "ESTABLISHED":
                    self._flush_window()

                self._cv.notify_all()

    # ─── segment handling ─────────────────────────────────────────────

    def _handle(self, seg):
        """Dispatch one received segment by current state.  Caller holds _lock."""

        if self.state == "SYN_SENT":
            if (seg.flags & FLAG_SYN) and (seg.flags & FLAG_ACK) \
                    and seg.ack >= 1:
                self.server_ack = seg.seq + 1   # SYN from server = 1 seq byte
                self.remote_rwnd = seg.rwnd
                self.send_base = 1              # our SYN (seq 0) is ACKed
                self.state = "ESTABLISHED"
                self.timer_deadline = None
                ack = Segment(
                    seq=self.send_base, ack=self.server_ack, flags=FLAG_ACK,
                )
                self._raw_send(ack, "SEND")

        elif self.state == "ESTABLISHED":
            if seg.flags & FLAG_ACK:
                self._process_ack(seg)
            if seg.flags & FLAG_FIN:
                self.server_ack = seg.seq + 1
                ack = Segment(
                    seq=self.next_seq, ack=self.server_ack, flags=FLAG_ACK,
                )
                self._raw_send(ack, "SEND")
                self.state = "CLOSE_WAIT"

        elif self.state == "FIN_WAIT":
            if seg.flags & FLAG_ACK:
                self._process_ack(seg)
            if seg.flags & FLAG_FIN:
                self.got_server_fin = True
                self.server_ack = seg.seq + 1
                ack = Segment(
                    seq=self.next_seq, ack=self.server_ack, flags=FLAG_ACK,
                )
                self._raw_send(ack, "SEND")
            # transition to TIME_WAIT only when both FINs are done
            if not self.unacked and self.got_server_fin:
                self.state = "TIME_WAIT"

        elif self.state in ("TIME_WAIT", "CLOSE_WAIT"):
            # re-ACK a duplicate FIN from the server
            if seg.flags & FLAG_FIN:
                self.server_ack = seg.seq + 1
                ack = Segment(
                    seq=self.next_seq, ack=self.server_ack, flags=FLAG_ACK,
                )
                self._raw_send(ack, "SEND")

    def _process_ack(self, seg):
        """Handle a cumulative ACK.  Caller holds _lock."""
        self.remote_rwnd = seg.rwnd
        if seg.ack <= self.send_base:
            return  # duplicate ACK — ignore
        self.send_base = seg.ack

        # remove all fully-ACKed segments
        to_del = []
        for s, stored in self.unacked.items():
            consumed = len(stored.payload)
            if stored.flags & FLAG_FIN:
                consumed += 1
            if s + consumed <= seg.ack:
                to_del.append(s)
        for s in to_del:
            del self.unacked[s]

        # reset / clear the retransmission timer
        if self.unacked:
            self.timer_deadline = time.monotonic() + self.rto
        else:
            self.timer_deadline = None

    # ─── window management ────────────────────────────────────────────

    def _flush_window(self):
        """Move pending segments into the send window.  Caller holds _lock."""
        while self.pending:
            in_flight = sum(self._flow_cost(s) for s in self.unacked.values())
            eff_wnd = min(self.window_bytes, max(self.remote_rwnd, 0))

            # zero-window probe
            if eff_wnd <= HEADER_SIZE and in_flight == 0:
                seg = self.pending.popleft()
                if len(seg.payload) > 1:
                    rest = Segment(
                        seq=seg.seq + 1, ack=seg.ack,
                        flags=seg.flags, payload=seg.payload[1:],
                    )
                    self.pending.appendleft(rest)
                    seg = Segment(
                        seq=seg.seq, ack=seg.ack,
                        flags=seg.flags, payload=seg.payload[:1],
                    )
                self.unacked[seg.seq] = seg
                self._raw_send(seg, "SEND")
                if self.timer_deadline is None:
                    self.timer_deadline = time.monotonic() + self.rto
                return  # one probe at a time

            avail = eff_wnd - in_flight
            if avail <= 0:
                break

            seg = self.pending[0]
            if self._flow_cost(seg) > avail:
                if in_flight > 0:
                    break  # wait for ACKs to free window space
                # split segment to fit the remaining window
                max_payload = max(1, avail - HEADER_SIZE)
                head = Segment(
                    seq=seg.seq, ack=self.server_ack,
                    flags=seg.flags, payload=seg.payload[:max_payload],
                )
                tail = Segment(
                    seq=seg.seq + max_payload, ack=self.server_ack,
                    flags=seg.flags, payload=seg.payload[max_payload:],
                )
                self.pending.popleft()
                self.pending.appendleft(tail)
                seg = head
            else:
                self.pending.popleft()

            self.unacked[seg.seq] = seg
            self._raw_send(seg, "SEND")
            if self.timer_deadline is None:
                self.timer_deadline = time.monotonic() + self.rto

    def _retransmit(self):
        """Go-Back-N: retransmit every un-ACKed segment.  Caller holds _lock."""
        for s in self.unacked.values():
            self._raw_send(s, "RETX")
        if self.unacked:
            self.timer_deadline = time.monotonic() + self.rto

    # ─── low-level helpers ────────────────────────────────────────────

    def _raw_send(self, seg, note):
        """Send one segment and log it."""
        try:
            self.sock.sendto(seg.to_bytes(), self.peer)
        except OSError:
            return
        self.logger.log(
            self.src_port, self.dst_port, seg.seq, seg.ack,
            seg.flags, len(seg.payload), note,
        )

    def _cleanup(self):
        """Stop the background thread and close the socket."""
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass
        self._thread.join(timeout=1)

    def _flow_cost(self, seg):
        """Bytes this data segment consumes in the receiver window."""
        if seg.payload:
            return self.segment_size
        return HEADER_SIZE
