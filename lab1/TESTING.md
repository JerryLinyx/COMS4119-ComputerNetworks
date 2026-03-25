# CSEE 4119 Spring 2026 - Assignment 1 Testing
## Yuxuan Lin

## Test Environment
- Python: `python3`
- Programs tested: `server.py`, `network.py`, `client.py`
- Dataset: `./data/bunny`
- Latency: `0.05`

## Bandwidth Files Used
- `lab1-bw.txt` (baseline)
```text
0:440000
2:920000
4:6000000
6:1600000
10:440000
```
- `lab1-bw-high.txt` (higher capacity profile)
```text
0:1200000
2:2400000
4:8000000
6:3200000
10:1200000
```
- `lab1-bw-low.txt` (lower capacity profile)
```text
0:220000
2:320000
4:700000
6:380000
10:220000
```

## Test Case 1 - Baseline dynamic bandwidth
### Parameters
- Bandwidth file: `lab1-bw.txt`
- Alpha: `0.5`

### Commands
```bash
python server.py 60041
python network.py 50041 127.0.0.1 60041 lab1-bw.txt 0.05
python client.py 127.0.0.1 50041 bunny 0.5
```

### Results
- Downloaded chunks: 30
- Log lines: 30
- Bitrates observed:
```text
292312 612790 987680 1791962 3676374
```
- Log excerpt (`testing_artifacts/log_baseline.txt`):
```text
0.054196 0.286832 438305.569864 438305.569864 292312 bunny_292312_00000.m4s
0.341932 0.336302 434895.080666 436600.325265 292312 bunny_292312_00001.m4s
12.390347 1.696504 438341.406284 982508.749773 987680 bunny_987680_00028.m4s
14.087409 0.883887 437920.205856 710214.477814 612790 bunny_612790_00029.m4s
```

## Test Case 2 - High bandwidth profile
### Parameters
- Bandwidth file: `lab1-bw-high.txt`
- Alpha: `0.5`

### Commands
```bash
python server.py 60042
python network.py 50042 127.0.0.1 60042 lab1-bw-high.txt 0.05
python client.py 127.0.0.1 50042 bunny 0.5
```

### Results
- Downloaded chunks: 30
- Log lines: 30
- Bitrates observed:
```text
292312 612790 987680 1791962 3676374
```
- Log excerpt (`testing_artifacts/log_high.txt`):
```text
0.056418 0.110420 1138561.971952 1138561.971952 292312 bunny_292312_00000.m4s
0.167332 0.274557 1102633.969225 1120597.970588 612790 bunny_612790_00001.m4s
10.344968 1.478110 1190438.889459 2180634.263842 1791962 bunny_1791962_00028.m4s
11.824478 0.627511 1193209.315528 1686921.789685 987680 bunny_987680_00029.m4s
```

## Test Case 3 - Low bandwidth profile
### Parameters
- Bandwidth file: `lab1-bw-low.txt`
- Alpha: `0.5`

### Commands
```bash
python server.py 60043
python network.py 50043 127.0.0.1 60043 lab1-bw-low.txt 0.05
python client.py 127.0.0.1 50043 bunny 0.5
```

### Results
- Downloaded chunks: 30
- Log lines: 30
- Bitrates observed:
```text
292312
```
- Log excerpt (`testing_artifacts/log_low.txt`):
```text
0.057148 0.577597 217660.446897 217660.446897 292312 bunny_292312_00000.m4s
0.635698 0.667200 219208.682349 218434.564623 292312 bunny_292312_00001.m4s
14.313402 0.874996 218039.867132 220715.248857 292312 bunny_292312_00028.m4s
15.189643 0.747849 217926.349713 219320.799285 292312 bunny_292312_00029.m4s
```

## Test Case 4 - Video not found
### Parameters
- Bandwidth file: `lab1-bw.txt`
- Alpha: `0.5`
- Requested video name: `missing`

### Commands
```bash
python server.py 60045
python network.py 50045 127.0.0.1 60045 lab1-bw.txt 0.05
python client.py 127.0.0.1 50045 missing 0.5
```

### Results
- Client output (`testing_artifacts/client_missing.out`):
```text
video not found
```
- From a clean state, no `log.txt` is generated and no chunk file is downloaded.

## Notes
- Test Case 1-3 used the real `bunny` dataset and completed all 30 chunks.
- Test Case 4 validates error handling for a non-existent video name.
- `log.txt` format follows: `<time> <duration> <tput> <avg-tput> <bitrate> <chunkname>`.
