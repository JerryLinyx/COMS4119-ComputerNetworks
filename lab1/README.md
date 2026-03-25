# CSEE 4119 Spring 2026 - Assignment 1
## Yuxuan Lin

## Files
- `server.py`: TCP video server. Handles manifest/chunk requests and returns file bytes.
- `client.py`: TCP client with EWMA throughput estimation and ABR bitrate adaptation.
- `network.py`: Provided network simulator (unchanged).
- `video_player.py`: Optional chunk player (provided).
- `lab1-bw.txt`: Baseline dynamic bandwidth profile used in testing.
- `lab1-bw-high.txt`: Higher-capacity bandwidth profile used in testing.
- `lab1-bw-low.txt`: Lower-capacity bandwidth profile used in testing.
- `TESTING.md`: Test cases and observed outcomes.

## Request/Response Protocol
Client requests are line-based:
- `GET_MANIFEST <video_name>`
- `GET_CHUNK <video_name> <bitrate> <chunk_idx>`

Server responses:
- `OK <payload_length>\n<payload bytes>`
- `ERR <reason>\n`

## How To Run
1. Make sure the provided `data` directory is at the same level as `server.py` and `client.py`:
- `./data/<name>/manifest.mpd`
- `./data/<name>/chunks/<name>_<bitrate>_<chunk_no>.m4s`

2. Start server:
```bash
python server.py 60000
```

3. Start network simulator:
```bash
python network.py 50000 127.0.0.1 60000 bw.txt 0.05
```
For this submission, example bandwidth files are:
- `lab1-bw.txt`
- `lab1-bw-high.txt`
- `lab1-bw-low.txt`

4. Start client:
```bash
python client.py 127.0.0.1 50000 bunny 0.5
```

5. Optional playback:
```bash
ENABLE_VIDEO_PLAYER=1 python client.py 127.0.0.1 50000 bunny 0.5
```

## Output
- Client writes `log.txt` in required format:
  `<time> <duration> <tput> <avg-tput> <bitrate> <chunkname>`
- Client stores chunks in `tmp/chunk_{chunk_num}.m4s` (0-indexed).

## Assumptions and Notes
- Chunk indexing is 0-based and filename suffix is zero-padded to 5 digits.
- Number of chunks is computed from manifest as `ceil(mediaPresentationDuration / maxSegmentDuration)`.
- ABR rule is: choose highest bitrate where `avg_throughput >= 1.5 * bitrate`; otherwise choose minimum bitrate.
- If manifest request fails, client prints exactly `video not found` and exits.
- Video playback is disabled by default to avoid OpenCV/display dependency during grading.
