"""Handler dispatch table.

Each command name maps to a handler function ``(params: dict) -> dict``. The
returned dict is the JSON-serializable payload sent back to the MCP server;
its ``status`` field is ``"ok"`` for success or ``"error"`` for a structured
failure.

Handlers are registered here so the addon has a single source of truth for
which commands it supports.
"""

from __future__ import annotations

from typing import Any, Callable

from . import build, lifecycle

Handler = Callable[[dict[str, Any]], dict[str, Any]]

HANDLERS: dict[str, Handler] = {
    "ping": lifecycle.ping,
    "add_primitive": build.add_primitive,
}
