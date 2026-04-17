#
# Columbia University - CSEE 4119 Computer Networks
# Assignment 2 - Mini Reliable Transport Protocol
#
# mrt_common.py - shared protocol structures and helpers
#

from __future__ import annotations

import struct
import zlib
import threading
from datetime import datetime, timezone

# ─── flags ────────────────────────────────────────────────────────────
FLAG_SYN = 0x01
FLAG_ACK = 0x02
FLAG_FIN = 0x04
FLAG_PSH = 0x08

# ─── header layout ────────────────────────────────────────────────────
# seq(I) ack(I) flags(B) hdr_len(B) rwnd(H) payload_len(H) cksum(I) rsv(H)
HEADER_FMT = "!IIBBHHIH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 20 bytes

# ─── tuning constants ─────────────────────────────────────────────────
DEFAULT_RTO = 0.25          # retransmission timeout (seconds)
SOCKET_TIMEOUT = 0.05       # non-blocking recv poll interval
WINDOW_SEGMENTS = 5         # sliding-window size in segments
OVERALL_TIMEOUT = 30.0      # max wait for any blocking API call
CLOSE_TIMEOUT = 5.0         # max wait during connection teardown


# ─── helpers ──────────────────────────────────────────────────────────

def _utc_ms() -> str:
    """Current UTC timestamp with millisecond precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _type_label(flags: int, plen: int) -> str:
    """Human-readable segment type for logging."""
    if flags & FLAG_SYN and flags & FLAG_ACK:
        return "SYN-ACK"
    if flags & FLAG_FIN and flags & FLAG_ACK:
        return "FIN-ACK"
    if flags & FLAG_SYN:
        return "SYN"
    if flags & FLAG_FIN:
        return "FIN"
    if plen > 0:
        return "PSH"
    if flags & FLAG_ACK:
        return "ACK"
    return "UNK"


# ─── Segment ──────────────────────────────────────────────────────────

class Segment:
    """A single MRT protocol segment with CRC-32 integrity check."""

    __slots__ = ("seq", "ack", "flags", "rwnd", "payload")

    def __init__(self, seq=0, ack=0, flags=0, rwnd=0, payload=b""):
        self.seq = seq
        self.ack = ack
        self.flags = flags
        self.rwnd = rwnd
        self.payload = payload

    def to_bytes(self) -> bytes:
        plen = len(self.payload)
        hdr0 = struct.pack(
            HEADER_FMT,
            self.seq, self.ack, self.flags, HEADER_SIZE,
            min(self.rwnd, 0xFFFF), plen, 0, 0,
        )
        ck = zlib.crc32(hdr0 + self.payload) & 0xFFFFFFFF
        hdr = struct.pack(
            HEADER_FMT,
            self.seq, self.ack, self.flags, HEADER_SIZE,
            min(self.rwnd, 0xFFFF), plen, ck, 0,
        )
        return hdr + self.payload

    @classmethod
    def from_bytes(cls, raw: bytes) -> Segment | None:
        if len(raw) < HEADER_SIZE:
            return None
        try:
            seq, ack, flags, hl, rwnd, plen, ck, reserved = struct.unpack(
                HEADER_FMT, raw[:HEADER_SIZE]
            )
        except struct.error:
            return None
        if hl != HEADER_SIZE or len(raw) != hl + plen or reserved != 0:
            return None
        hdr0 = struct.pack(HEADER_FMT, seq, ack, flags, hl, rwnd, plen, 0, 0)
        if ck != (zlib.crc32(hdr0 + raw[hl:]) & 0xFFFFFFFF):
            return None
        return cls(seq=seq, ack=ack, flags=flags, rwnd=rwnd, payload=raw[hl:])


# ─── Logger ───────────────────────────────────────────────────────────

class SegmentLogger:
    """Append-only per-port log file writer."""

    def __init__(self, port: int):
        """
        Initialize the per-port log file and ensure it exists immediately.

        arguments:
        port -- local UDP port used to name the log file
        """
        self.path = f"log_{port}.txt"
        self._lock = threading.Lock()
        with open(self.path, "w", encoding="utf-8"):
            pass

    def log(self, src: int, dst: int, seq: int, ack: int,
            flags: int, plen: int, note: str = ""):
        line = (
            f"{_utc_ms()} {src} {dst} {seq} {ack} "
            f"{_type_label(flags, plen)} {plen} {note}\n"
        )
        with self._lock:
            with open(self.path, "a") as f:
                f.write(line)
