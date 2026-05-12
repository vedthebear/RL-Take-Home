"""Wire-protocol framing tests using ``socket.socketpair``.

Exercises the length-prefixed JSON framing in ``blender_mcp.protocol`` without
involving Blender or even a real network. Covers:

- Round-trip encode/decode.
- Partial reads (recv returning chunks smaller than requested).
- Connection-drop in the middle of header or body.
- Oversized payload rejection on both encode and decode.
- Non-object top-level JSON rejection.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
from typing import Any

import pytest

from blender_mcp import protocol


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------


class TestEncode:
    def test_round_trip(self) -> None:
        payload = {"hello": "world", "n": 42, "deep": {"x": [1, 2, 3]}}
        frame = protocol.encode_message(payload)
        # 4-byte header + body
        assert len(frame) >= protocol.LENGTH_PREFIX_SIZE + 2
        length = struct.unpack(protocol.LENGTH_PREFIX_FORMAT, frame[:4])[0]
        body = frame[4:]
        assert length == len(body)
        assert json.loads(body) == payload

    def test_unicode(self) -> None:
        payload = {"name": "Café 木"}
        frame = protocol.encode_message(payload)
        body = frame[4:]
        assert json.loads(body) == payload

    def test_rejects_oversized(self) -> None:
        big = {"x": "a" * (protocol.MAX_PAYLOAD_BYTES + 1)}
        with pytest.raises(protocol.ProtocolError, match="exceeds maximum"):
            protocol.encode_message(big)


# ---------------------------------------------------------------------------
# send / recv over socketpair
# ---------------------------------------------------------------------------


def _pair() -> tuple[socket.socket, socket.socket]:
    a, b = socket.socketpair()
    return a, b


class TestSendRecv:
    def test_round_trip_basic(self) -> None:
        a, b = _pair()
        try:
            payload: dict[str, Any] = {"command": "ping", "params": {}}
            protocol.send_message(a, payload)
            received = protocol.recv_message(b)
            assert received == payload
        finally:
            a.close()
            b.close()

    def test_multiple_messages(self) -> None:
        a, b = _pair()
        try:
            sent = [{"i": i, "name": f"obj{i}"} for i in range(5)]
            for p in sent:
                protocol.send_message(a, p)
            received = [protocol.recv_message(b) for _ in sent]
            assert received == sent
        finally:
            a.close()
            b.close()

    def test_partial_writes_handled(self) -> None:
        """If the writer sends in tiny chunks, the reader must reassemble correctly."""
        a, b = _pair()
        try:
            payload = {"data": "x" * 5000}
            frame = protocol.encode_message(payload)

            def chunked_send() -> None:
                # Send 100 bytes at a time, forcing recv to handle short reads.
                for i in range(0, len(frame), 100):
                    a.sendall(frame[i : i + 100])

            sender = threading.Thread(target=chunked_send)
            sender.start()
            try:
                received = protocol.recv_message(b)
                assert received == payload
            finally:
                sender.join()
        finally:
            a.close()
            b.close()

    def test_connection_drop_mid_header(self) -> None:
        a, b = _pair()
        try:
            a.sendall(b"\x00\x00")  # only 2 of 4 header bytes
            a.close()
            with pytest.raises(protocol.ProtocolError, match="connection closed"):
                protocol.recv_message(b)
        finally:
            b.close()

    def test_connection_drop_mid_body(self) -> None:
        a, b = _pair()
        try:
            # Claim a 100-byte payload, then send only 10 bytes and close.
            a.sendall(struct.pack(protocol.LENGTH_PREFIX_FORMAT, 100))
            a.sendall(b"x" * 10)
            a.close()
            with pytest.raises(protocol.ProtocolError, match="connection closed"):
                protocol.recv_message(b)
        finally:
            b.close()

    def test_oversized_declared_length_rejected(self) -> None:
        a, b = _pair()
        try:
            a.sendall(
                struct.pack(
                    protocol.LENGTH_PREFIX_FORMAT, protocol.MAX_PAYLOAD_BYTES + 1
                )
            )
            with pytest.raises(protocol.ProtocolError, match="exceeds maximum"):
                protocol.recv_message(b)
        finally:
            a.close()
            b.close()

    def test_malformed_json_rejected(self) -> None:
        a, b = _pair()
        try:
            bad = b"{not json"
            a.sendall(struct.pack(protocol.LENGTH_PREFIX_FORMAT, len(bad)))
            a.sendall(bad)
            with pytest.raises(protocol.ProtocolError, match="invalid JSON"):
                protocol.recv_message(b)
        finally:
            a.close()
            b.close()

    def test_non_object_top_level_rejected(self) -> None:
        a, b = _pair()
        try:
            body = b"[1, 2, 3]"
            a.sendall(struct.pack(protocol.LENGTH_PREFIX_FORMAT, len(body)))
            a.sendall(body)
            with pytest.raises(protocol.ProtocolError, match="must be an object"):
                protocol.recv_message(b)
        finally:
            a.close()
            b.close()
