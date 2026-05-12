"""Main-thread dispatcher — the bridge between socket workers and bpy.

bpy is not thread-safe. Socket worker threads cannot touch ``bpy.data`` or any
operator. They submit commands here; a single persistent ``bpy.app.timers``
callback drains the queue on the main thread, runs the handler, and signals
completion via a ``concurrent.futures.Future``.

The flow per command:

    worker thread  ─submit(cmd)─▶  queue  ─tick()─▶  handler(params)  ─▶  result
         ▲                                                                  │
         └──────────────  future.set_result(result)  ────────────────────────┘

If the handler raises, the ``finally`` block on ``_handle_one`` still resolves
the future — the worker thread never hangs.

Invariants:

- **One** timer registered for the lifetime of the addon. Re-registering per
  command would leak timers if commands queue faster than the UI ticks.
- Every handler invocation is wrapped in ``try/except`` so a raising handler
  becomes a structured ``Failure`` response — the future is *always*
  resolved, otherwise the socket thread waits forever.
- Timer callback returns the poll interval (float) to keep itself alive;
  returning ``None`` would unregister it.

External code calls ``submit(command_dict)`` from any thread and gets back the
response dict (already JSON-serializable). A maximum wait clamp prevents a
buggy handler from pinning a socket thread indefinitely.
"""

from __future__ import annotations

import queue
import time
import traceback
from concurrent.futures import Future
from typing import Any, Callable, Final

import bpy

Handler = Callable[[dict[str, Any]], dict[str, Any]]

# Poll cadence for the main-thread timer. 50 ms is a good balance: short enough
# that command latency feels instant, long enough not to starve the UI.
_TICK_INTERVAL_SECONDS: Final[float] = 0.05

# Upper bound on how long a socket thread will wait for the main thread to
# process its command. Renders are the longest operation we expect. If we
# exceed this, something is genuinely wrong.
_MAX_WAIT_SECONDS: Final[float] = 600.0


class Dispatcher:
    """Thread-safe queue + main-thread drain."""

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[dict[str, Any], Future[dict[str, Any]]]] = (
            queue.Queue()
        )
        self._handlers: dict[str, Handler] = {}
        self._timer_registered: bool = False
        self._logger: Callable[[str], None] = print

    # ------------------------------------------------------------------ setup

    def set_handlers(self, handlers: dict[str, Handler]) -> None:
        self._handlers = dict(handlers)

    def set_logger(self, logger: Callable[[str], None]) -> None:
        self._logger = logger

    def start(self) -> None:
        if self._timer_registered:
            return
        bpy.app.timers.register(self._tick, first_interval=_TICK_INTERVAL_SECONDS)
        self._timer_registered = True

    def stop(self) -> None:
        if self._timer_registered and bpy.app.timers.is_registered(self._tick):
            bpy.app.timers.unregister(self._tick)
        self._timer_registered = False
        # Drain any pending futures so socket threads don't hang.
        while True:
            try:
                _, fut = self._queue.get_nowait()
            except queue.Empty:
                break
            if not fut.done():
                fut.set_result(
                    {
                        "status": "error",
                        "code": "invalid_state",
                        "message": "dispatcher stopped before command was processed",
                    }
                )

    # -------------------------------------------------------------- submission

    def submit(self, command: dict[str, Any]) -> dict[str, Any]:
        """Submit ``command`` from any thread and block until processed.

        Returns the response dict that handlers produced (success or error
        shape; both already JSON-serializable).
        """
        fut: Future[dict[str, Any]] = Future()
        self._queue.put((command, fut))
        try:
            return fut.result(timeout=_MAX_WAIT_SECONDS)
        except TimeoutError:
            return {
                "status": "error",
                "code": "timeout",
                "message": (
                    f"main thread did not process command within "
                    f"{_MAX_WAIT_SECONDS}s"
                ),
            }

    # --------------------------------------------------------- main-thread tick

    def _tick(self) -> float:
        """Drain the queue on the main thread.

        Processes up to a bounded number of commands per tick so that a flood
        of small commands doesn't starve the Blender UI. The timer keeps
        itself alive by returning the next interval.
        """
        processed = 0
        max_per_tick = 8
        while processed < max_per_tick:
            try:
                command, fut = self._queue.get_nowait()
            except queue.Empty:
                break
            self._handle_one(command, fut)
            processed += 1
        return _TICK_INTERVAL_SECONDS

    def _handle_one(
        self, command: dict[str, Any], fut: Future[dict[str, Any]]
    ) -> None:
        """Run one command end-to-end with absolute exception safety.

        The ``finally`` clause guarantees we always resolve the future; a
        handler that raises becomes a structured ``Failure`` response.
        """
        response: dict[str, Any]
        started = time.monotonic()
        cmd_name = command.get("command", "<unknown>")
        try:
            name = command.get("command")
            params = command.get("params", {})
            if not isinstance(name, str) or not name:
                response = {
                    "status": "error",
                    "code": "unknown_command",
                    "message": "command field missing or not a string",
                }
            elif not isinstance(params, dict):
                response = {
                    "status": "error",
                    "code": "validation_error",
                    "message": "params field must be an object",
                }
            else:
                handler = self._handlers.get(name)
                if handler is None:
                    response = {
                        "status": "error",
                        "code": "unknown_command",
                        "message": f"no handler registered for {name!r}",
                    }
                else:
                    response = handler(params)
        except Exception as exc:
            self._logger(
                f"[blender-mcp] handler {cmd_name!r} raised: {exc}\n"
                + traceback.format_exc()
            )
            response = {
                "status": "error",
                "code": "blender_op_failed",
                "message": f"{type(exc).__name__}: {exc}",
            }
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            self._logger(
                f"[blender-mcp] handled {cmd_name!r} in {elapsed_ms}ms"
            )
            if not fut.done():
                fut.set_result(response)
