"""Integration tests for the TCP client.

A fake addon is spun up on a random localhost port; it speaks the same
length-prefixed JSON wire protocol the real addon uses. Covers:

- Happy-path command round-trip.
- Connection refused -> ``Failure(code="connection_lost")``.
- Server hangs -> ``Failure(code="timeout")`` and the client reconnects on
  the next call.
- Mismatched response ID -> ``Failure(code="internal_error")``.
- Malformed payload -> ``Failure(code="internal_error")``.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Callable, Iterable, Iterator

import pytest

from blender_mcp import protocol
from blender_mcp.client import BlenderClient


# ---------------------------------------------------------------------------
# Fake addon helper
# ---------------------------------------------------------------------------


class FakeAddon:
    """Run a script of (predicate, response) pairs over a real TCP socket.

    Each accepted connection is handled by a thread that reads one command,
    invokes ``response_fn(command)``, and either sends the response back or
    drops the connection (if the response function returns ``None``).
    """

    def __init__(self, response_fn: Callable[[dict[str, object]], dict[str, object] | None]) -> None:
        self._response_fn = response_fn
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(4)
        self._listener.settimeout(1.0)
        self.port: int = self._listener.getsockname()[1]
        self._shutdown = threading.Event()
        self._threads: list[threading.Thread] = []
        self._listener_thread = threading.Thread(target=self._serve, daemon=True)
        self._listener_thread.start()

    def _serve(self) -> None:
        while not self._shutdown.is_set():
            try:
                client, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            t = threading.Thread(target=self._handle, args=(client,), daemon=True)
            t.start()
            self._threads.append(t)

    def _handle(self, sock: socket.socket) -> None:
        try:
            while not self._shutdown.is_set():
                try:
                    cmd = protocol.recv_message(sock)
                except protocol.ProtocolError:
                    return
                response = self._response_fn(cmd)
                if response is None:
                    return
                envelope: dict[str, object] = {
                    "id": cmd.get("id", ""),
                    "payload": response,
                }
                try:
                    protocol.send_message(sock, envelope)
                except (OSError, protocol.ProtocolError):
                    return
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def close(self) -> None:
        self._shutdown.set()
        try:
            self._listener.close()
        except OSError:
            pass
        self._listener_thread.join(timeout=2.0)


@pytest.fixture
def fake_addon() -> Iterator[Callable[[Callable[[dict[str, object]], dict[str, object] | None]], FakeAddon]]:
    spawned: list[FakeAddon] = []

    def factory(
        response_fn: Callable[[dict[str, object]], dict[str, object] | None],
    ) -> FakeAddon:
        f = FakeAddon(response_fn)
        spawned.append(f)
        return f

    try:
        yield factory
    finally:
        for f in spawned:
            f.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _pick_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestHappyPath:
    def test_round_trip(self, fake_addon) -> None:
        addon = fake_addon(
            lambda cmd: {
                "status": "ok",
                "echo": cmd["params"].get("x"),
                "command": cmd["command"],
            }
        )
        client = BlenderClient(port=addon.port)
        result = client.call("ping", {"x": 42})
        assert result == {"status": "ok", "echo": 42, "command": "ping"}
        client.close()

    def test_reuses_connection_across_calls(self, fake_addon) -> None:
        addon = fake_addon(
            lambda cmd: {"status": "ok", "id_seen": cmd["id"]}
        )
        client = BlenderClient(port=addon.port)
        r1 = client.call("a", {})
        r2 = client.call("b", {})
        assert r1["status"] == "ok"
        assert r2["status"] == "ok"
        # Different ids on each call.
        assert r1["id_seen"] != r2["id_seen"]
        client.close()


class TestErrorPaths:
    def test_connection_refused_yields_connection_lost(self) -> None:
        port = _pick_free_port()
        client = BlenderClient(port=port, connect_timeout=0.5)
        result = client.call("ping", {})
        assert result["status"] == "error"
        assert result["code"] == "connection_lost"

    def test_hung_server_yields_timeout(self, fake_addon) -> None:
        # Response function returns None -> connection dropped without reply.
        # That gives a connection_lost; for a true timeout we'd need the
        # server to never reply, so emulate that by adding a sleep then closing.
        def hung(_cmd: dict[str, object]) -> dict[str, object] | None:
            time.sleep(2.0)  # longer than the client timeout below
            return {"status": "ok"}

        addon = fake_addon(hung)
        client = BlenderClient(port=addon.port, default_call_timeout=0.3)
        result = client.call("slow", {})
        assert result["status"] == "error"
        assert result["code"] == "timeout"
        client.close()

    def test_mismatched_id(self, fake_addon) -> None:
        # Fake addon sends a wrong id.
        class _BadAddon:
            def __init__(self) -> None:
                self.s = socket.socket()
                self.s.bind(("127.0.0.1", 0))
                self.s.listen(1)
                self.port = self.s.getsockname()[1]
                self.t = threading.Thread(target=self._serve, daemon=True)
                self.t.start()

            def _serve(self) -> None:
                client, _ = self.s.accept()
                cmd = protocol.recv_message(client)
                _ = cmd
                protocol.send_message(client, {"id": "wrong-id", "payload": {"status": "ok"}})
                client.close()

            def close(self) -> None:
                self.s.close()

        bad = _BadAddon()
        try:
            client = BlenderClient(port=bad.port)
            result = client.call("ping", {})
            assert result["status"] == "error"
            assert result["code"] == "internal_error"
            client.close()
        finally:
            bad.close()

    def test_non_object_payload(self, fake_addon) -> None:
        # Send a string instead of an object for "payload".
        class _StringAddon:
            def __init__(self) -> None:
                self.s = socket.socket()
                self.s.bind(("127.0.0.1", 0))
                self.s.listen(1)
                self.port = self.s.getsockname()[1]
                self.t = threading.Thread(target=self._serve, daemon=True)
                self.t.start()

            def _serve(self) -> None:
                client, _ = self.s.accept()
                cmd = protocol.recv_message(client)
                protocol.send_message(client, {"id": cmd["id"], "payload": "oops"})  # type: ignore[dict-item]
                client.close()

            def close(self) -> None:
                self.s.close()

        bad = _StringAddon()
        try:
            client = BlenderClient(port=bad.port)
            result = client.call("ping", {})
            assert result["status"] == "error"
            assert result["code"] == "internal_error"
            client.close()
        finally:
            bad.close()

    def test_reconnect_after_failure(self, fake_addon) -> None:
        # First call: server replies (good). Second call: server closes the
        # socket without replying. Third call: server replies again. The
        # client should transparently reconnect on call #3.
        state = {"call_count": 0}

        def behavior(cmd: dict[str, object]) -> dict[str, object] | None:
            state["call_count"] += 1
            if state["call_count"] == 2:
                return None  # drop the connection without responding
            return {"status": "ok", "n": state["call_count"]}

        addon = fake_addon(behavior)
        client = BlenderClient(port=addon.port, default_call_timeout=2.0)
        r1 = client.call("a", {})
        assert r1["status"] == "ok"
        r2 = client.call("b", {})
        assert r2["status"] == "error"
        assert r2["code"] == "connection_lost"
        r3 = client.call("c", {})
        assert r3["status"] == "ok"
        assert r3["n"] == 3
        client.close()
