# 
# Columbia University - CSEE 4119 Computer Networks
# Assignment 1 - Adaptive video streaming
#
# client.py - the client program for sending request to the server and play the received video chunks
#

import math
import os
import socket
import time
import xml.etree.ElementTree as ET

import threading
from queue import Queue
import sys

try:
    from video_player import play_chunks
except Exception:
    play_chunks = None

def recv_line(sock, pending):
    """
    receive one newline-terminated header line from the server stream

    arguments:
    sock -- connected TCP socket
    pending -- buffered bytes that were already received
    """
    while b"\n" not in pending:
        data = sock.recv(4096)
        if not data:
            return None, pending
        pending += data

    line, pending = pending.split(b"\n", 1)
    return line.decode("utf-8", errors="replace").strip(), pending


def recv_exact(sock, size, pending):
    """
    receive exactly <size> payload bytes from the stream

    arguments:
    sock -- connected TCP socket
    size -- payload length to receive
    pending -- buffered bytes that were already received
    """
    chunks = []

    if pending:
        taken = pending[:size]
        chunks.append(taken)
        pending = pending[len(taken):]
        size -= len(taken)

    while size > 0:
        data = sock.recv(min(4096, size))
        if not data:
            raise ConnectionError("connection closed while receiving payload")
        chunks.append(data)
        size -= len(data)

    return b"".join(chunks), pending


def send_request(sock, request_line):
    """
    send one line-based request to the server

    arguments:
    sock -- connected TCP socket
    request_line -- plain-text request without trailing newline
    """
    sock.sendall((request_line + "\n").encode("utf-8"))


def recv_response(sock, pending):
    """
    parse one server response

    arguments:
    sock -- connected TCP socket
    pending -- buffered bytes that were already received
    """
    header, pending = recv_line(sock, pending)
    if header is None:
        raise ConnectionError("connection closed while receiving response header")

    if header.startswith("ERR "):
        return False, header[4:], pending

    parts = header.split()
    if len(parts) != 2 or parts[0] != "OK":
        return False, "invalid response", pending

    try:
        payload_len = int(parts[1])
    except ValueError:
        return False, "invalid response length", pending

    if payload_len < 0:
        return False, "invalid response length", pending

    payload, pending = recv_exact(sock, payload_len, pending)
    return True, payload, pending


def parse_manifest(manifest_bytes):
    """
    parse manifest XML and return sorted bitrates and chunk count

    arguments:
    manifest_bytes -- bytes content of manifest.mpd
    """
    root = ET.fromstring(manifest_bytes.decode("utf-8"))
    total_duration = float(root.attrib["mediaPresentationDuration"])
    segment_duration = float(root.attrib["maxSegmentDuration"])

    bitrates = []
    for representation in root.findall(".//Representation"):
        bitrates.append(int(representation.attrib["bandwidth"]))
    bitrates.sort()

    total_chunks = int(math.ceil(total_duration / segment_duration))
    return bitrates, total_chunks


def choose_bitrate(avg_tput, bitrates):
    """
    choose the highest bitrate where avg_tput >= 1.5 * bitrate

    arguments:
    avg_tput -- EWMA smoothed throughput
    bitrates -- available bitrate list (ascending)
    """
    feasible = [bitrate for bitrate in bitrates if avg_tput >= 1.5 * bitrate]
    if not feasible:
        return bitrates[0]
    return max(feasible)


def client(server_addr, server_port, video_name, alpha, chunks_queue):
    """
    the client function
    request manifest and chunks, adapt bitrate with EWMA throughput, and write log.txt

    arguments:
    server_addr -- the address of the server
    server_port -- the port number of the server
    video_name -- the name of the video
    alpha -- the alpha value for exponentially-weighted moving average
    chunks_queue -- the queue for passing the path of the chunks to the video player
    """
    # to visualize the adaptive video streaming, store the chunk in a temporary folder and
    # pass the path of the chunk to the video player
    if not os.path.exists("tmp"):
        os.makedirs("tmp")

    connection_start = time.time()
    avg_tput = None
    pending = b""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((server_addr, server_port))

        send_request(sock, f"GET_MANIFEST {video_name}")
        ok, payload_or_reason, pending = recv_response(sock, pending)
        if not ok:
            print("video not found")
            return

        try:
            bitrates, total_chunks = parse_manifest(payload_or_reason)
        except Exception:
            print("video not found")
            return

        if not bitrates or total_chunks <= 0:
            print("video not found")
            return

        with open("log.txt", "w", encoding="utf-8") as log_file:
            for chunk_idx in range(total_chunks):
                if chunk_idx == 0 or avg_tput is None:
                    bitrate = bitrates[0]
                else:
                    bitrate = choose_bitrate(avg_tput, bitrates)

                chunk_name = f"{video_name}_{bitrate}_{chunk_idx:05d}.m4s"
                req_start = time.time()
                send_request(sock, f"GET_CHUNK {video_name} {bitrate} {chunk_idx}")
                ok, payload_or_reason, pending = recv_response(sock, pending)
                req_end = time.time()

                if not ok:
                    break

                chunk = payload_or_reason
                duration = max(req_end - req_start, 1e-9)
                tput = (len(chunk) * 8) / duration
                if avg_tput is None:
                    avg_tput = tput
                else:
                    avg_tput = alpha * tput + (1 - alpha) * avg_tput

                rel_time = req_start - connection_start
                log_file.write(
                    f"{rel_time:.6f} {duration:.6f} {tput:.6f} "
                    f"{avg_tput:.6f} {bitrate} {chunk_name}\n"
                )
                log_file.flush()

                chunk_path = f"tmp/chunk_{chunk_idx}.m4s"
                with open(chunk_path, "wb") as chunk_file:
                    chunk_file.write(chunk)
                chunks_queue.put(chunk_path)


# parse input arguments and pass to the client function
if __name__ == '__main__':
    server_addr = sys.argv[1]
    server_port = int(sys.argv[2])
    video_name = sys.argv[3]
    alpha = float(sys.argv[4])

    # init queue for passing the path of the chunks to the video player
    chunks_queue = Queue()
    # start the client thread with the input arguments
    client_thread = threading.Thread(target = client, args =(server_addr, server_port, video_name, alpha, chunks_queue))
    client_thread.start()
    # start the video player (optional)
    if play_chunks is not None and os.environ.get("ENABLE_VIDEO_PLAYER") == "1":
        play_chunks(chunks_queue)
    client_thread.join()
