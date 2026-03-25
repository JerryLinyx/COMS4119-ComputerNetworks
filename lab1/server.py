# 
# Columbia University - CSEE 4119 Computer Networks
# Assignment 1 - Adaptive video streaming
#
# server.py - the server program for taking request from the client and 
#             send the requested file back to the client
#

import os
import socket
import sys


def recv_line(sock, pending):
    """
    receive one newline-terminated request line from the client stream

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


def send_ok(sock, payload):
    """
    send a successful response with payload bytes

    arguments:
    sock -- connected TCP socket
    payload -- bytes to send
    """
    sock.sendall(f"OK {len(payload)}\n".encode("utf-8") + payload)


def send_err(sock, reason):
    """
    send an error response line to the client

    arguments:
    sock -- connected TCP socket
    reason -- plain-text reason string
    """
    sock.sendall(f"ERR {reason}\n".encode("utf-8"))


def handle_request(conn, request_line):
    """
    parse one request and send corresponding response

    arguments:
    conn -- connected TCP socket
    request_line -- one line request string
    """
    parts = request_line.split()
    if not parts:
        send_err(conn, "invalid request")
        return

    if parts[0] == "GET_MANIFEST" and len(parts) == 2:
        video_name = parts[1]
        manifest_path = os.path.join(".", "data", video_name, "manifest.mpd")
        if not os.path.exists(manifest_path):
            send_err(conn, "video not found")
            return

        with open(manifest_path, "rb") as manifest_file:
            send_ok(conn, manifest_file.read())
        return

    if parts[0] == "GET_CHUNK" and len(parts) == 4:
        video_name = parts[1]
        try:
            bitrate = int(parts[2])
            chunk_idx = int(parts[3])
        except ValueError:
            send_err(conn, "invalid request")
            return

        if bitrate < 0 or chunk_idx < 0:
            send_err(conn, "invalid request")
            return

        chunk_name = f"{video_name}_{bitrate}_{chunk_idx:05d}.m4s"
        chunk_path = os.path.join(".", "data", video_name, "chunks", chunk_name)
        if not os.path.exists(chunk_path):
            send_err(conn, "chunk not found")
            return

        with open(chunk_path, "rb") as chunk_file:
            send_ok(conn, chunk_file.read())
        return

    send_err(conn, "invalid request")


def server(listen_port):
    """
    the server function
    accept connections and return requested manifest/chunk files

    arguments:
    listen_port -- the port that the server listens on
    """
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("", listen_port))
    server_sock.listen(5)

    while True:
        conn, _ = server_sock.accept()
        pending = b""
        with conn:
            while True:
                request_line, pending = recv_line(conn, pending)
                if request_line is None:
                    break
                handle_request(conn, request_line)


# parse input arguments and pass to the server function
if __name__ == '__main__':
    listen_port = int(sys.argv[1]) 
    server(listen_port)
