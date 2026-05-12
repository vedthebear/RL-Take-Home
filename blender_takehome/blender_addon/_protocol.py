"""Wire framing for the addon side.

Mirrors ``blender_mcp.protocol`` but lives inside the addon so it stays
self-contained when installed into Blender's addons directory (which doesn't
have the MCP-server package on its sys.path).

Both sides MUST agree byte-for-byte. If you change one, change the other.
Keep this file in sync with ``src/blender_mcp/protocol.py``.
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any, Final

LENGTH_PREFIX_FORMAT: Final[str] = "!I"
LENGTH_PREFIX_SIZE: Final[int] = struct.calcsize(LENGTH_PREFIX_FORMAT)
MAX_PAYLOAD_BYTES: Final[int] = 16 * 1024 * 1024


class ProtocolError(Exception):
    pass


def encode_message(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_PAYLOAD_BYTES:
        raise ProtocolError(
            f"payload size {len(body)} exceeds maximum {MAX_PAYLOAD_BYTES}"
        )
    return struct.pack(LENGTH_PREFIX_FORMAT, len(body)) + body


def _recv_exactly(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ProtocolError(
                f"connection closed after {len(buf)} of {n} expected bytes"
            )
        buf.extend(chunk)
    return bytes(buf)


def send_message(sock: socket.socket, payload: dict[str, Any]) -> None:
    sock.sendall(encode_message(payload))


def recv_message(sock: socket.socket) -> dict[str, Any]:
    header = _recv_exactly(sock, LENGTH_PREFIX_SIZE)
    (length,) = struct.unpack(LENGTH_PREFIX_FORMAT, header)
    if length > MAX_PAYLOAD_BYTES:
        raise ProtocolError(
            f"payload size {length} exceeds maximum {MAX_PAYLOAD_BYTES}"
        )
    body = _recv_exactly(sock, length)
    try:
        decoded = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON payload: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ProtocolError(
            f"top-level payload must be an object, got {type(decoded).__name__}"
        )
    return decoded
