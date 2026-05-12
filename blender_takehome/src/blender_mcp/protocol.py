"""Wire protocol for MCP-server <-> Blender-addon communication.

Length-prefixed JSON framing over a TCP socket. Each message is:

    [4 bytes: big-endian uint32 payload length] [N bytes: UTF-8 JSON]

The framing is independent of the message schema — payloads are plain dicts that
the two endpoints agree on. The MCP server sends `Command` envelopes (see
``models.CommandEnvelope``); the addon replies with `Response` envelopes.

Length prefixing avoids the embedded-newline issues of newline-delimited JSON
and makes partial reads deterministic to handle.

A byte-identical mirror lives in ``blender_addon/_protocol.py`` so the addon
zip is self-contained when installed inside Blender (which doesn't have this
package on its sys.path). Keep the two files in sync.
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any, Final

LENGTH_PREFIX_FORMAT: Final[str] = "!I"  # network (big-endian) uint32
LENGTH_PREFIX_SIZE: Final[int] = struct.calcsize(LENGTH_PREFIX_FORMAT)

# 16 MiB upper bound. Renders larger than this should be referenced by filepath,
# not embedded inline. Prevents a runaway payload from OOM-ing either endpoint.
MAX_PAYLOAD_BYTES: Final[int] = 16 * 1024 * 1024


class ProtocolError(Exception):
    """Wire-level error: malformed framing, oversized payload, connection drop."""


def encode_message(payload: dict[str, Any]) -> bytes:
    """Serialize a payload dict to a length-prefixed JSON frame."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_PAYLOAD_BYTES:
        raise ProtocolError(
            f"payload size {len(body)} exceeds maximum {MAX_PAYLOAD_BYTES}"
        )
    return struct.pack(LENGTH_PREFIX_FORMAT, len(body)) + body


def _recv_exactly(sock: socket.socket, n: int) -> bytes:
    """Read exactly ``n`` bytes from ``sock`` or raise ProtocolError on EOF."""
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
    """Send a length-prefixed JSON message over ``sock``."""
    frame = encode_message(payload)
    sock.sendall(frame)


def recv_message(sock: socket.socket) -> dict[str, Any]:
    """Receive a single length-prefixed JSON message from ``sock``.

    Raises:
        ProtocolError: on connection drop, oversized payload, or malformed JSON.
    """
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
