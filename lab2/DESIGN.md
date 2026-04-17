# CSEE 4119 Spring 2026, Assignment 2 Design File
## Yuxuan Lin

## Protocol Summary
This MRT implementation is a single-client reliable byte-stream protocol on top of UDP. It uses:
- a 3-way handshake
- CRC32 checksums for corruption detection
- byte-oriented sequence numbers and cumulative ACKs
- Go-Back-N style retransmission
- sender sliding window
- receiver-advertised flow control (`rwnd`)
- explicit close handshake with retransmission

The design goal is correctness under loss/corruption without hanging indefinitely. Each endpoint uses a single background thread for socket I/O and timer-based retransmission. All blocking APIs use bounded timeouts.

## Segment Format
Each segment has a fixed 20-byte header plus an optional payload.

Fields:
- `seq` (4 bytes): first byte number carried by the segment
- `ack` (4 bytes): next byte expected from the peer
- `flags` (1 byte): `SYN`, `ACK`, `FIN`, `PSH`
- `header_len` (1 byte): always 20
- `rwnd` (2 bytes): advertised receive window
- `payload_len` (2 bytes): payload length in bytes
- `checksum` (4 bytes): CRC32 over header-with-zero-checksum plus payload
- `reserved` (2 bytes): always 0

## Connection Lifecycle
### Open
1. Client sends `SYN(seq=0)`.
2. Server replies with `SYN-ACK(seq=0, ack=1, rwnd=...)`.
3. Client replies with `ACK` and enters `ESTABLISHED`.

If handshake packets are lost or corrupted, both sides keep retransmitting the required control segment until the handshake completes.

### Close
1. Client waits until all queued data is cumulatively acknowledged.
2. Either endpoint may initiate close.
3. If the client initiates close, the server enters `CLOSE_WAIT`, replies with `FIN|ACK`, and keeps retransmitting that segment until it receives the final ACK.
4. If the server initiates close through `Server.close()`, it enters `FIN_SENT`, sends `FIN|ACK`, and keeps retransmitting until the client ACKs it.
5. The client enters a short `TIME_WAIT`-style linger after acknowledging a server `FIN`, so duplicate `FIN`s can still be acknowledged if the last ACK is lost.

This avoids the previous failure modes where one side closed its socket too early or where `Server.close()` could block forever waiting for the peer to initiate teardown first.

## Data Transfer
The client splits application data into payload-sized chunks:

```text
max_payload = segment_size - HEADER_SIZE
```

The client tracks:
- `pending`: segments accepted from the application but not yet sent
- `unacked`: segments sent but not yet cumulatively acknowledged (OrderedDict keyed by seq)
- `send_base`: highest cumulative ACK received

The sender is not stop-and-wait. It can have multiple data segments in flight at once, bounded by:
- the local send window
- the receiver's advertised window

That is the main mechanism that keeps throughput acceptable when RTT is high.

## Loss Handling
Data, handshake, and close control segments are all retransmitted.

For data, the client uses Go-Back-N behavior:
- if the oldest unacknowledged segment times out, the client retransmits the full current unacknowledged window
- ACKs are cumulative, so one ACK can release multiple buffered segments

The background receiver thread handles all retransmission timing. When the oldest unacked segment's timer expires, all unacked segments are retransmitted (Go-Back-N). Blocking APIs use a fixed overall timeout (30s for connect/send/receive, 5s for close).

## Corruption Handling
Each segment is validated before use. A segment is rejected if:
- the header cannot be parsed
- `header_len` is invalid
- the encoded payload length does not match the datagram length
- the CRC32 checksum does not match

Corrupted segments are dropped and logged as `DROP`. Recovery happens through cumulative ACKs and retransmissions.

## Out-of-Order Delivery
The receiver is Go-Back-N style, not selective repeat.
- only the segment whose `seq` matches the next expected byte is accepted into the byte stream
- out-of-order segments are discarded
- the receiver sends an ACK for the last in-order byte position

This reconstructs the stream in order without needing a reordering buffer.

## Flow Control
The server computes:

```text
rwnd = receive_buffer_size - len(data_buffer)
```

The client respects `rwnd` when injecting new data.

Two cases matter:
- if the available window is smaller than the next pending payload, the payload is split and only the fitting prefix is sent
- if `rwnd` becomes 0, the client sends a 1-byte zero-window probe periodically until the receiver advertises space again

The zero-window probe is important because a pure ACK-based design can deadlock if the window-update ACK is the packet that gets lost.

## Server Buffering
The server maintains a single data buffer for in-order application bytes. Since the GBN receiver only accepts the next expected in-order segment, all accepted data is immediately ready for the application — no reordering buffer is needed.

`receive(conn, length)` drains exactly `length` bytes from the data buffer and sends a window-update ACK after each consumption, advertising the newly freed space.

## Logging
Each endpoint writes `log_<port>.txt` with at least:

```text
<time> <src_port> <dst_port> <seq> <ack> <type> <payload_length> <note>
```

`note` is one of `SEND`, `RECV`, `RETX`, `DROP`, or `PROBE`.
