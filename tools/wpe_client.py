#!/usr/bin/env python3
"""Minimal WebSocket client for WorldPromptEngine (stdlib only).

Usage:
  python3 tools/wpe_client.py "misty alpine peaks at golden hour"
  python3 tools/wpe_client.py --action generate_heightmap --seed 42
  python3 tools/wpe_client.py --action status_poll   # not a bridge action; local helper
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import uuid

HOST = "127.0.0.1"
PORT = 3001
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _handshake(sock: socket.socket) -> None:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = (
        f"GET / HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    sock.sendall(req.encode("ascii"))
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("connection closed during handshake")
        resp += chunk
    if b"101" not in resp.split(b"\r\n", 1)[0]:
        raise RuntimeError(f"handshake failed:\n{resp.decode('utf-8', errors='replace')}")
    accept = base64.b64encode(hashlib.sha1((key + WS_MAGIC).encode("ascii")).digest()).decode("ascii")
    if accept.encode("ascii") not in resp:
        # Some servers omit echoing; still require 101 above.
        pass


def _mask_payload(payload: bytes) -> bytes:
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return mask + masked


def _send_text(sock: socket.socket, message: str) -> None:
    payload = message.encode("utf-8")
    length = len(payload)
    if length < 126:
        header = struct.pack(">BB", 0x81, 0x80 | length)
    elif length < 65536:
        header = struct.pack(">BBH", 0x81, 0x80 | 126, length)
    else:
        header = struct.pack(">BBQ", 0x81, 0x80 | 127, length)
    sock.sendall(header + _mask_payload(payload))


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("connection closed while reading")
        buf += chunk
    return buf


def _recv_text(sock: socket.socket) -> str:
    header = _recv_exact(sock, 2)
    opcode = header[0] & 0x0F
    masked = (header[1] & 0x80) != 0
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _recv_exact(sock, 8))[0]
    if masked:
        mask = _recv_exact(sock, 4)
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(_recv_exact(sock, length)))
    else:
        payload = _recv_exact(sock, length)
    if opcode == 0x8:
        raise RuntimeError("server closed websocket")
    if opcode != 0x1:
        return ""
    return payload.decode("utf-8", errors="replace")


def send_command(payload: dict) -> dict:
    with socket.create_connection((HOST, PORT), timeout=5.0) as sock:
        sock.settimeout(10.0)
        _handshake(sock)
        _send_text(sock, json.dumps(payload))
        raw = _recv_text(sock)
        return json.loads(raw) if raw else {"ok": False, "error": "empty response"}


def main() -> int:
    parser = argparse.ArgumentParser(description="WorldPromptEngine WebSocket client")
    parser.add_argument("prompt", nargs="?", help="Natural language world prompt")
    parser.add_argument("--action", default=None, help="Override action name")
    parser.add_argument("--width", type=int, default=505)
    parser.add_argument("--height", type=int, default=505)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    global HOST, PORT
    HOST, PORT = args.host, args.port

    if args.action == "generate_heightmap":
        payload = {
            "action": "generate_heightmap",
            "params": {
                "width": args.width,
                "height": args.height,
                "seed": args.seed,
            },
        }
    elif args.action and args.action != "generate_from_prompt":
        payload = {"action": args.action, "params": {}, "id": str(uuid.uuid4())}
    else:
        if not args.prompt:
            parser.error("prompt text required (or use --action generate_heightmap)")
        payload = {
            "action": "generate_from_prompt",
            "prompt": args.prompt,
            "params": {
                "width": args.width,
                "height": args.height,
                "seed": args.seed,
            },
        }

    try:
        ack = send_command(payload)
    except OSError as exc:
        print(f"Could not connect to ws://{HOST}:{PORT}: {exc}", file=sys.stderr)
        print("Is Unreal Editor open with WorldPromptEngine loaded?", file=sys.stderr)
        return 1

    print(json.dumps(ack, indent=2))
    return 0 if ack.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
