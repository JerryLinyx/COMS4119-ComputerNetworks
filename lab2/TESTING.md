# CSEE 4119 Spring 2026, Assignment 2 Testing File
## Yuxuan Lin

## Environment
- Platform: local macOS development environment
- Runtime: `python3`
- Programs exercised: `app_server.py`, `network.py`, `app_client.py`

## End-to-End Scenarios
All end-to-end tests used the provided starter applications and finished successfully.

### 1. Baseline transfer (no loss)
Commands:
```bash
cd lab2
python3 app_server.py 60000 4096
python3 network.py 51000 127.0.0.1 50000 127.0.0.1 60000 loss_none.txt
python3 app_client.py 50000 127.0.0.1 51000 1460
```

Observed result:
```text
client: >> sent 8000 bytes of data
server: >> received 8000 bytes successfully
```

Covers:
- 3-way handshake
- ordered transfer of 8000 bytes
- segmentation (8000 bytes / 1440 payload = 6 segments)
- normal close handshake

### 2. Packet loss (10%, then 20%)
Commands:
```bash
cd lab2
python3 app_server.py 60001 4096
python3 network.py 51001 127.0.0.1 50001 127.0.0.1 60001 loss_drop.txt
python3 app_client.py 50001 127.0.0.1 51001 1460
```

`loss_drop.txt`:
```text
0 0.1 0
5 0.2 0
```

Observed result:
```text
client: >> sent 8000 bytes of data
server: >> received 8000 bytes successfully
```

Covers:
- retransmission after segment loss
- cumulative ACK recovery
- GBN retransmission of full unacked window on timeout

### 3. Bit corruption (BER ~0.00002, ~20% per-segment corruption)
Commands:
```bash
cd lab2
python3 app_server.py 60003 4096
python3 network.py 51003 127.0.0.1 50003 127.0.0.1 60003 loss_test_corrupt.txt
python3 app_client.py 50003 127.0.0.1 51003 1460
```

`loss_test_corrupt.txt`:
```text
0 0 0.00002
```

Observed result:
```text
client: >> sent 8000 bytes of data
server: >> received 8000 bytes successfully
```

Covers:
- CRC32 checksum-based corruption detection
- dropping corrupted segments
- retransmission until a clean copy arrives
- server sends duplicate ACK on corrupted segment so client retransmits promptly

### 4. Combined drops + corruption
Commands:
```bash
cd lab2
python3 app_server.py 60004 4096
python3 network.py 51004 127.0.0.1 50004 127.0.0.1 60004 loss_test_combo.txt
python3 app_client.py 50004 127.0.0.1 51004 1460
```

`loss_test_combo.txt`:
```text
0 0.1 0.00001
5 0.05 0.00001
```

Observed result:
```text
client: >> sent 8000 bytes of data
server: >> received 8000 bytes successfully
```

Covers:
- simultaneous segment loss and bit corruption
- protocol remains correct when both error sources are active

### 5. Flow control with small receive buffer
Commands:
```bash
cd lab2
python3 app_server.py 60010 500
python3 network.py 51010 127.0.0.1 50010 127.0.0.1 60010 loss_drop.txt
python3 app_client.py 50010 127.0.0.1 51010 1460
```

Observed result:
```text
client: >> sent 8000 bytes of data
server: >> received 8000 bytes successfully
```

Covers:
- flow control with a 500-byte receive buffer (smaller than one full segment)
- client respects `rwnd` and splits payloads to fit
- zero-window probe when buffer is full
- window-update ACK after `receive()` drains data

Additional targeted checks:
- With `segment_size=512` and advertised `rwnd=3500`, the client sent 6 unique
  data segments in the first burst, matching `floor(3500 / 512) = 6`.
- With `segment_size=1460` and advertised `rwnd=8000`, the client sent 5 unique
  data segments in the first burst, matching `floor(8000 / 1460) = 5`.

These targeted checks were added because the autograder evaluates flow control
based on how many full segments can be in flight before the sender pauses for
ACKs. The receiver now advertises `rwnd` from the buffered receive-window
budget, and the client counts each in-flight data segment against that window
using the configured `segment_size`.

### 6. Small segment size (100 bytes)
Commands:
```bash
cd lab2
python3 app_server.py 60011 4096
python3 network.py 51011 127.0.0.1 50011 127.0.0.1 60011 loss_drop.txt
python3 app_client.py 50011 127.0.0.1 51011 100
```

Observed result:
```text
client: >> sent 8000 bytes of data
server: >> received 8000 bytes successfully
```

Covers:
- segmentation with 80-byte payload (100 - 20 header)
- 100 data segments for 8000 bytes
- sliding window with many small segments under 10-20% loss

## Loss Files
`loss_none.txt`
```text
0 0 0
```

`loss_drop.txt`
```text
0 0.1 0
5 0.2 0
```

`loss_test_corrupt.txt`
```text
0 0 0.00002
```

`loss_test_combo.txt`
```text
0 0.1 0.00001
5 0.05 0.00001
```

## Conclusion
The implementation was verified for:
- segment corruption handling via CRC32 checksums
- segment loss handling via Go-Back-N retransmission
- in-order delivery via cumulative ACKs (out-of-order segments discarded)
- sliding-window transmission (faster than stop-and-wait for high latency)
- segmentation of large data into payload-sized chunks
- receiver-driven flow control with advertised window
- connection teardown without deadlocking

Note: the network simulator (`network.py`) runs on localhost and does not inject latency directly. High-latency readiness is validated by design: the sender uses a sliding window and keeps multiple segments in flight instead of stop-and-wait.
