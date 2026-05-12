"""Shared helpers for addon-side handlers.

Two jobs:

1. Build the success / failure response dicts (``ok`` / ``err``) that match
   ``src/blender_mcp/models.py``'s ``status`` discriminator.
2. Smooth out small bpy ergonomics: unit conversions (deg ↔ rad), the
   "select_only" invariant that operators require, and ``Vector`` ↔ tuple
   coercion for JSON.

bpy is imported lazily so this module loads cleanly in environments without
Blender (useful for static analysis and isolated tests). Every helper that
actually touches bpy will fail loudly if it isn't installed.
"""

from __future__ import annotations

import math
from typing import Any

try:
    import bpy
except ImportError:  # pragma: no cover - addon runs inside Blender
    bpy = None  # type: ignore[assignment]


def ok(**fields: Any) -> dict[str, Any]:
    """Build a success response payload."""
    return {"status": "ok", **fields}


def err(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured failure response payload.

    ``code`` should be a member of ``models.ErrorCode`` so the MCP server's
    discriminated union can parse it.
    """
    payload: dict[str, Any] = {"status": "error", "code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return payload


def deg_to_rad_tuple(deg: tuple[float, float, float]) -> tuple[float, float, float]:
    return (math.radians(deg[0]), math.radians(deg[1]), math.radians(deg[2]))


def rad_to_deg_tuple(rad: tuple[float, float, float]) -> tuple[float, float, float]:
    return (math.degrees(rad[0]), math.degrees(rad[1]), math.degrees(rad[2]))


def select_only(obj: Any) -> None:
    """Deselect everything, then select and activate ``obj``.

    Operators read selection state from the context; calling them without
    setting both ``select_set(True)`` and the view layer's ``active``
    object is the single biggest source of "operator silently no-ops" bugs.
    """
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def get_object_or_none(name: str) -> Any:
    """Look up an object by name in the current scene. Returns ``None`` if
    missing — caller decides what to do."""
    return bpy.data.objects.get(name)


def vec3(v: Any) -> tuple[float, float, float]:
    """Coerce an ``mathutils.Vector`` (or any 3-iterable) to a plain tuple
    for JSON serialization."""
    return (float(v[0]), float(v[1]), float(v[2]))
