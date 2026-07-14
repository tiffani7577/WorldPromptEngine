"""
utility_bridge.py — WorldPromptEngine WebSocket command bridge (UE 5.8.0)

Runs an asyncio WebSocket server on port 3001 on a BACKGROUND DAEMON THREAD.

HARD RULE: this module NEVER calls unreal.* APIs directly (except log_error,
which is thread-safe for diagnostics). All engine work is deferred by pushing
JSON command payloads onto the shared thread-safe collections.deque(), which
art_engine.consume_queue_tick() drains on the main thread each frame.

Implements a minimal RFC 6455 WebSocket server using only asyncio + stdlib
(base64, hashlib, struct), so no external `websockets` dependency is required
inside the UE Python environment.
"""

import asyncio
import base64
import hashlib
import json
import struct

try:
    import unreal
    def _log_error(msg):
        try:
            unreal.log_error(msg)
        except Exception:
            print("[ERROR]", msg)
    def _log(msg):
        try:
            unreal.log(msg)
        except Exception:
            print("[LOG]", msg)
except ImportError:
    def _log_error(msg):
        print("[ERROR]", msg)
    def _log(msg):
        print("[LOG]", msg)


WS_PORT = 3001
WS_HOST = "127.0.0.1"
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

VALID_ACTIONS = frozenset({
    "move_editor_camera",
    "spawn_temporary_actor",
    "clear_temporary_actors",
    "get_landscape_bounds",
    "generate_heightmap",
    "generate_from_prompt",
    "apply_weather",
    "apply_atmosphere",
    "biome_status",
    "ensure_lighting",
    "setup_landscape_material",
    "setup_content",
    "set_content_root",
    "use_folder",
    "find_folder",
    "content_status",
})

# Set by start_server(); shared with init_unreal / art_engine.
_STATE = None


# ---------------------------------------------------------------------------
# Minimal RFC 6455 framing
# ---------------------------------------------------------------------------

async def _read_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    data = await reader.readexactly(n)
    return data


async def _ws_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
    try:
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = await reader.read(1024)
            if not chunk:
                return False
            request += chunk
            if len(request) > 16384:
                return False

        headers = {}
        lines = request.decode("utf-8", errors="replace").split("\r\n")
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        key = headers.get("sec-websocket-key")
        if not key or headers.get("upgrade", "").lower() != "websocket":
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            return False

        accept = base64.b64encode(
            hashlib.sha1((key + WS_MAGIC).encode("ascii")).digest()).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: {}\r\n\r\n".format(accept)
        )
        writer.write(response.encode("ascii"))
        await writer.drain()
        return True
    except Exception as e:
        _log_error("utility_bridge._ws_handshake failed: {}".format(e))
        return False


async def _ws_recv_text(reader: asyncio.StreamReader):
    """Receive one text message. Returns str, or None on close/error."""
    try:
        fragments = []
        while True:
            header = await _read_exact(reader, 2)
            fin = (header[0] & 0x80) != 0
            opcode = header[0] & 0x0F
            masked = (header[1] & 0x80) != 0
            length = header[1] & 0x7F

            if length == 126:
                length = struct.unpack(">H", await _read_exact(reader, 2))[0]
            elif length == 127:
                length = struct.unpack(">Q", await _read_exact(reader, 8))[0]

            if length > 1_048_576:  # 1 MB safety cap
                return None

            mask = await _read_exact(reader, 4) if masked else b"\x00" * 4
            payload = await _read_exact(reader, length)
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

            if opcode == 0x8:      # close
                return None
            if opcode == 0x9:      # ping -> ignore payload; pong handled by caller
                fragments.append(("ping", payload))
                if fin:
                    return ("__ping__", payload)
                continue
            if opcode in (0x1, 0x0):  # text / continuation
                fragments.append(("text", payload))
                if fin:
                    data = b"".join(p for t, p in fragments if t == "text")
                    return data.decode("utf-8", errors="replace")
            else:
                # binary or unknown: skip frame
                if fin:
                    return "__skip__"
    except (asyncio.IncompleteReadError, ConnectionResetError):
        return None
    except Exception as e:
        _log_error("utility_bridge._ws_recv_text failed: {}".format(e))
        return None


def _ws_encode_text(message: str) -> bytes:
    try:
        payload = message.encode("utf-8")
        length = len(payload)
        if length < 126:
            header = struct.pack(">BB", 0x81, length)
        elif length < 65536:
            header = struct.pack(">BBH", 0x81, 126, length)
        else:
            header = struct.pack(">BBQ", 0x81, 127, length)
        return header + payload
    except Exception as e:
        _log_error("utility_bridge._ws_encode_text failed: {}".format(e))
        return b""


def _ws_encode_pong(payload: bytes) -> bytes:
    return struct.pack(">BB", 0x8A, min(len(payload), 125)) + payload[:125]


# ---------------------------------------------------------------------------
# Command validation + enqueue
# ---------------------------------------------------------------------------

def _enqueue(raw_text: str) -> dict:
    """Validate the JSON payload and push onto the shared deque. Returns ack."""
    try:
        payload = json.loads(raw_text)
        action = payload.get("action", "")
        if action not in VALID_ACTIONS:
            return {"ok": False, "error": "unknown action '{}'".format(action)}
        if _STATE is None:
            return {"ok": False, "error": "bridge state not initialized"}

        # Push the raw dict — deque.append() is thread-safe (GIL-atomic).
        _STATE["command_queue"].append(payload)
        return {
            "ok": True,
            "queued": action,
            "queue_depth": len(_STATE["command_queue"]),
            "is_generating": bool(_STATE.get("is_generating", False)),
            "progress": float(_STATE.get("progress", 0.0)),
        }
    except json.JSONDecodeError as e:
        return {"ok": False, "error": "invalid JSON: {}".format(e)}
    except Exception as e:
        _log_error("utility_bridge._enqueue failed: {}".format(e))
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Connection handler + server entry
# ---------------------------------------------------------------------------

async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    try:
        if not await _ws_handshake(reader, writer):
            writer.close()
            return
        _log("WorldPromptEngine bridge: client connected {}".format(peer))

        while True:
            msg = await _ws_recv_text(reader)
            if msg is None:
                break
            if isinstance(msg, tuple) and msg[0] == "__ping__":
                writer.write(_ws_encode_pong(msg[1]))
                await writer.drain()
                continue
            if msg == "__skip__":
                continue

            ack = _enqueue(msg)
            writer.write(_ws_encode_text(json.dumps(ack)))
            await writer.drain()
    except Exception as e:
        _log_error("utility_bridge._handle_client failed: {}".format(e))
    finally:
        try:
            writer.close()
        except Exception:
            pass
        _log("WorldPromptEngine bridge: client disconnected {}".format(peer))


async def serve(state: dict):
    """Async server entry point. Runs forever on the daemon thread's loop."""
    global _STATE
    _STATE = state
    try:
        server = await asyncio.start_server(_handle_client, WS_HOST, WS_PORT)
        _log("WorldPromptEngine bridge: WebSocket listening on ws://{}:{}".format(WS_HOST, WS_PORT))
        async with server:
            await server.serve_forever()
    except OSError as e:
        _log_error("utility_bridge.serve: port {} unavailable: {}".format(WS_PORT, e))
    except Exception as e:
        _log_error("utility_bridge.serve failed: {}".format(e))


def run_server(state: dict):
    """
    Synchronous wrapper for threading.Thread(target=...). Creates a fresh
    event loop confined to the daemon thread. NO unreal API calls here.
    """
    try:
        asyncio.run(serve(state))
    except Exception as e:
        _log_error("utility_bridge.run_server failed: {}".format(e))
