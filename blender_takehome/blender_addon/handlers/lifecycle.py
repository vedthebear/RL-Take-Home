"""Lifecycle-related handlers (ping, clear_scene)."""

from __future__ import annotations

import time
from typing import Any


def ping(params: dict[str, Any]) -> dict[str, Any]:
    """Health-check round trip. Echoes any ``message`` field and adds a server
    timestamp so the caller can verify both directions of the link."""
    return {
        "status": "ok",
        "message": params.get("message", "pong"),
        "server_time": time.time(),
    }
