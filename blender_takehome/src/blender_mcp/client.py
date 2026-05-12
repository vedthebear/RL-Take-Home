"""TCP client for the Blender addon — MCP-server half's only outbound socket.

A single ``BlenderClient`` is shared by every tool function. It maintains one
TCP connection to the addon and serializes calls behind a lock — FastMCP runs
sync tools on a threadpool, so concurrent calls are possible.

This file is the *boundary*: every socket error, timeout, malformed reply, or
ID mismatch is caught here and translated into a structured ``Failure`` dict.
Tool wrappers above this layer never see a raw exception.

The receiving end of the connection is ``blender_addon/server.py``, which
listens on ``localhost:9876`` by default. See ``blender_mcp/__init__.py`` for
the system map.

Per-tool timeout is passed in by the caller; render-class tools get a large
budget, every other tool gets a short one.
"""

from __future__ import annotations

import socket
import threading
from typing import Any, Final

from . import protocol

DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 9876
DEFAULT_CONNECT_TIMEOUT_SECONDS: Final[float] = 5.0
DEFAULT_CALL_TIMEOUT_SECONDS: Final[float] = 15.0
RENDER_CALL_TIMEOUT_SECONDS: Final[float] = 300.0


def _err(code: str, message: str) -> dict[str, Any]:
    """Build a structured failure payload matching ``models.Failure``."""
    return {"status": "error", "code": code, "message": message}


class BlenderClient:
    """Thread-safe client for the Blender addon's TCP socket.

    Lazy-connects on first call. On any transport error the socket is reset so
    the next call will reconnect; the failing call returns a structured
    ``Failure`` payload rather than raising.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        default_call_timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS,
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._default_call_timeout = default_call_timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._next_id: int = 0

    # ----------------------------------------------------------- connection

    def _connect_locked(self) -> dict[str, Any] | None:
        """Open the TCP socket. Returns a Failure dict if it can't connect."""
        try:
            sock = socket.create_connection(
                (self._host, self._port), timeout=self._connect_timeout
            )
        except OSError as exc:
            return _err(
                "connection_lost",
                f"could not connect to Blender addon at "
                f"{self._host}:{self._port} ({exc}). "
                f"Is Blender running with the MCP addon started?",
            )
        self._sock = sock
        return None

    def _reset_locked(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def close(self) -> None:
        with self._lock:
            self._reset_locked()

    # ----------------------------------------------------------------- call

    def call(
        self,
        command: str,
        params: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a command, return the JSON-ready response payload.

        Never raises. Maps every transport failure to a ``Failure`` payload.
        """
        effective_timeout = timeout if timeout is not None else self._default_call_timeout

        with self._lock:
            if self._sock is None:
                err = self._connect_locked()
                if err is not None:
                    return err

            self._next_id += 1
            cmd_id = f"cmd-{self._next_id}"
            envelope: dict[str, Any] = {
                "id": cmd_id,
                "command": command,
                "params": params,
            }

            sock = self._sock
            assert sock is not None
            try:
                sock.settimeout(effective_timeout)
                protocol.send_message(sock, envelope)
                response = protocol.recv_message(sock)
            except socket.timeout:
                self._reset_locked()
                return _err(
                    "timeout",
                    f"command {command!r} did not return within {effective_timeout:g}s",
                )
            except (OSError, protocol.ProtocolError) as exc:
                self._reset_locked()
                return _err(
                    "connection_lost",
                    f"transport error during {command!r}: {exc}",
                )

        # Envelope validation happens outside the lock: the socket is already
        # quiet by this point. The ID must match what we sent or we're reading
        # someone else's reply — drop it as ``internal_error``.
        if not isinstance(response.get("id"), str) or response["id"] != cmd_id:
            return _err(
                "internal_error",
                f"response id mismatch: got {response.get('id')!r}, expected {cmd_id!r}",
            )
        payload = response.get("payload")
        if not isinstance(payload, dict):
            return _err(
                "internal_error",
                f"addon returned non-object payload: {type(payload).__name__}",
            )
        return payload
