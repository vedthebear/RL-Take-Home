"""Handler dispatch table — the only place a command name resolves to bpy code.

Each command name maps to a handler function ``(params: dict) -> dict``. The
returned dict is the JSON-serializable payload sent back to the MCP server;
its ``status`` field is ``"ok"`` for success or ``"error"`` for a structured
failure.

Handlers are registered here so the addon has a single source of truth for
which commands it supports. Adding a tool means: (1) add a handler in the
matching ``handlers/<category>.py``, (2) register it here, (3) add the
MCP-side wrapper in ``src/blender_mcp/tools/<category>.py``.
"""

from __future__ import annotations

from typing import Any, Callable

from . import build, frame, lifecycle, light, perceive, place, surface

Handler = Callable[[dict[str, Any]], dict[str, Any]]

HANDLERS: dict[str, Handler] = {
    # Perception
    "get_scene_summary": perceive.get_scene_summary,
    "get_object": perceive.get_object,
    "render_image": perceive.render_image,
    # Build
    "add_primitive": build.add_primitive,
    "add_modifier": build.add_modifier,
    # Place
    "transform_object": place.transform_object,
    "duplicate_object": place.duplicate_object,
    "delete_object": place.delete_object,
    # Surface
    "set_material": surface.set_material,
    # Light
    "add_light": light.add_light,
    # Frame
    "add_camera": frame.add_camera,
    # Lifecycle
    "ping": lifecycle.ping,
    "clear_scene": lifecycle.clear_scene,
}
