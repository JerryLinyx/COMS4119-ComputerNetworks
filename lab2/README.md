# CSEE 4119 Spring 2026, Assignment 2
## Yuxuan Lin

## Overview
This project implements a mini reliable transport protocol (MRT) on top of UDP for a single client connection. The protocol provides:
- connection establishment with a 3-way handshake
- reliable delivery with retransmission
- corruption detection with CRC32 checksums
- in-order byte-stream reconstruction
- sliding-window transmission
- receiver-driven flow control with advertised window (`rwnd`)
- explicit connection teardown with retransmission

The implementation uses a single background thread per endpoint for socket I/O, with a Go-Back-N sliding window and timer-based retransmission. All blocking APIs use bounded timeouts to prevent indefinite hangs.

## Files
- `app_client.py`: starter application client that reads `data.txt` and sends it through the MRT client APIs.
- `app_server.py`: starter application server that accepts one connection, reads 8000 bytes through the MRT server APIs, and compares them with the first 8000 bytes of `data.txt`.
- `mrt_client.py`: MRT client implementation.
- `mrt_server.py`: MRT server implementation.
- `mrt_common.py`: shared segment format, checksum logic, protocol constants, and logger.
- `network.py`: provided network simulator.
- `data.txt`: input file used by the starter applications.
- `loss_none.txt`: no-loss network profile.
- `loss_drop.txt`: packet-loss network profile.
- `loss_corrupt.txt`: bit-corruption network profile.
- `DESIGN.md`: protocol design.
- `TESTING.md`: executed tests and results.

## Protocol Summary
### Segment format
Each segment uses a fixed 20-byte header plus an optional payload.

Header fields:
- `seq`: byte-oriented sequence number
- `ack`: cumulative acknowledgment number
- `flags`: `SYN`, `ACK`, `FIN`, `PSH`
- `header_len`: fixed header size
- `rwnd`: advertised receive window
- `payload_len`: payload size in bytes
- `checksum`: CRC32 over header-with-zero-checksum plus payload
- `reserved`: unused

### Reliability
- The sender uses cumulative ACKs and Go-Back-N style retransmission.
- If the oldest unacknowledged segment times out, the client retransmits the full current unacknowledged window.
- Handshake and close control segments are retransmitted until the expected response arrives.

### Flow control
- The server advertises available receive space through `rwnd`.
- The client only injects data that fits inside `min(local_send_window, rwnd)`.
- If the available window is smaller than the next pending payload, the client splits the payload and sends only the fitting prefix.
- If `rwnd` reaches 0, the client sends a 1-byte zero-window probe periodically so the connection cannot deadlock if a window-update ACK is lost.

### Ordering
- The receiver accepts only the next expected byte sequence.
- Out-of-order payloads are discarded and the receiver re-ACKs the last in-order byte.

### Teardown
- The client sends `FIN` only after all queued data has been acknowledged.
- `Server.close()` can actively initiate teardown, and the server also handles the passive-close case when the client initiates first.
- The server sends `FIN|ACK` and keeps retransmitting it until the final ACK arrives.
- The client briefly stays alive in a `TIME_WAIT`-style state so duplicate `FIN`s can still be acknowledged if the last ACK is lost.

## How To Run
All commands below assume the current directory is `lab2/`.

1. Start the server:
```bash
python3 app_server.py 60000 4096
```

2. Start the network simulator:
```bash
python3 network.py 51000 127.0.0.1 50000 127.0.0.1 60000 loss_none.txt
```

3. Start the client:
```bash
python3 app_client.py 50000 127.0.0.1 51000 512
```

To test lossy conditions, replace `loss_none.txt` with `loss_drop.txt` or `loss_corrupt.txt`.

## Tests
End-to-end examples and observed results are documented in `TESTING.md`.

## Log Format
Each endpoint writes a log file named `log_<port>.txt`.

Columns:
```text
<time> <src_port> <dst_port> <seq> <ack> <type> <payload_length> <note>
```

`note` values used by this implementation:
- `SEND`: newly sent segment
- `RECV`: successfully received segment
- `RETX`: retransmitted segment
- `DROP`: invalid or corrupted segment rejected by parsing/checksum validation

## Assumptions
- Only one client is supported, matching the assignment scope.
- `receive_buffer_size` bounds the server-side data buffer; the server advertises `rwnd = receive_buffer_size - buffered_bytes`.
- `segment_size` is the maximum segment size including the 20-byte header; maximum payload = `segment_size - 20`.
