"""TCP server hosted inside the Blender addon.

A single-threaded listener accepts connections on ``localhost:<port>`` and
spawns a per-connection worker thread that reads commands, hands them to the
``Dispatcher`` (which marshals to the main thread), and writes responses back.

Threading layout
----------------

    listener thread ──accept()──▶ client thread ──recv──▶ dispatcher.submit()
                                       │                         │
                                       │                   blocks on Future
                                       │                         │
                                       ◀───── reply payload ─────┘
                                       │
                                     send()

The client thread *never* touches bpy. All bpy work happens on the main
thread inside the dispatcher's ``bpy.app.timers`` callback.

Design notes:

- The listener uses ``settimeout(1.0)`` so it can poll the shutdown event in
  between ``accept()`` calls. Without this, a clean Blender quit can hang the
  process because ``accept()`` blocks indefinitely.
- On shutdown, we open a self-connect to the listener so any outstanding
  ``accept()`` returns immediately. This is the standard idiom for waking up
  a blocking ``accept`` without ``SO_LINGER`` tricks.
- Per-connection threads are non-daemon but tracked and joined on stop.
  Marking them daemon would let Blender exit while a render is mid-flight,
  losing the result.
"""

from __future__ import annotations

import socket
import threading
from typing import Callable, Final

from . import _protocol as protocol

_LISTEN_BACKLOG: Final[int] = 8
_ACCEPT_TIMEOUT_SECONDS: Final[float] = 1.0
_LOCALHOST: Final[str] = "127.0.0.1"

CommandHandler = Callable[[dict[str, object]], dict[str, object]]


class AddonServer:
    """Lifecycle-managed TCP server.

    Construct, then ``start(port)`` once. Call ``stop()`` from any thread to
    shut down cleanly (idempotent). ``is_running()`` reflects current state.
    """

    def __init__(self, on_command: CommandHandler) -> None:
        self._on_command = on_command
        self._listener: socket.socket | None = None
        self._listener_thread: threading.Thread | None = None
        self._client_threads: list[threading.Thread] = []
        self._shutdown = threading.Event()
        self._port: int | None = None
        self._logger: Callable[[str], None] = print
        self._lock = threading.Lock()

    def set_logger(self, logger: Callable[[str], None]) -> None:
        self._logger = logger

    def is_running(self) -> bool:
        return (
            self._listener_thread is not None
            and self._listener_thread.is_alive()
        )

    @property
    def port(self) -> int | None:
        return self._port

    # ---------------------------------------------------------------- start

    def start(self, port: int) -> None:
        with self._lock:
            if self.is_running():
                raise RuntimeError("server is already running")
            self._shutdown.clear()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((_LOCALHOST, port))
            sock.listen(_LISTEN_BACKLOG)
            sock.settimeout(_ACCEPT_TIMEOUT_SECONDS)
            self._listener = sock
            self._port = port
            self._client_threads = []
            t = threading.Thread(
                target=self._listener_loop,
                name="blender-mcp-listener",
                daemon=False,
            )
            self._listener_thread = t
            t.start()
            self._logger(
                f"[blender-mcp] listening on {_LOCALHOST}:{port}"
            )

    # ----------------------------------------------------------------- stop

    def stop(self) -> None:
        with self._lock:
            if not self.is_running() and self._listener is None:
                return
            self._shutdown.set()
            self._wake_listener()
            listener = self._listener
            self._listener = None

        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass

        if self._listener_thread is not None:
            self._listener_thread.join(timeout=5.0)
            self._listener_thread = None

        # Client threads exit once their socket reads fail.
        for t in list(self._client_threads):
            t.join(timeout=2.0)
        self._client_threads.clear()
        self._port = None
        self._logger("[blender-mcp] server stopped")

    def _wake_listener(self) -> None:
        """Open a self-connect to unblock a pending accept()."""
        if self._port is None:
            return
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                try:
                    s.connect((_LOCALHOST, self._port))
                except OSError:
                    pass
        except OSError:
            pass

    # ------------------------------------------------------- listener thread

    def _listener_loop(self) -> None:
        listener = self._listener
        if listener is None:
            return
        while not self._shutdown.is_set():
            try:
                client, _addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                # Listener closed during shutdown.
                break
            if self._shutdown.is_set():
                try:
                    client.close()
                except OSError:
                    pass
                break
            t = threading.Thread(
                target=self._client_loop,
                args=(client,),
                name="blender-mcp-client",
                daemon=False,
            )
            t.start()
            self._client_threads.append(t)
            # Reap any client threads that have already finished.
            self._client_threads = [t for t in self._client_threads if t.is_alive()]

    # -------------------------------------------------------- client thread

    def _client_loop(self, sock: socket.socket) -> None:
        try:
            while not self._shutdown.is_set():
                try:
                    command = protocol.recv_message(sock)
                except protocol.ProtocolError as exc:
                    self._logger(f"[blender-mcp] client read error: {exc}")
                    break

                try:
                    response = self._on_command(command)
                except Exception as exc:
                    # Should not happen — the dispatcher itself swallows
                    # handler exceptions — but defend in depth.
                    response = {
                        "status": "error",
                        "code": "internal_error",
                        "message": f"{type(exc).__name__}: {exc}",
                    }

                envelope: dict[str, object] = {
                    "id": command.get("id", ""),
                    "payload": response,
                }
                try:
                    protocol.send_message(sock, envelope)
                except (OSError, protocol.ProtocolError) as exc:
                    self._logger(f"[blender-mcp] client write error: {exc}")
                    break
        finally:
            try:
                sock.close()
            except OSError:
                pass
