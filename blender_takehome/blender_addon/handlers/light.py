"""Lighting handler: create a typed light at a transform."""

from __future__ import annotations

from typing import Any

import bpy

from . import _common as h


def _configure_light(light_data: Any, kind: str, p: dict[str, Any]) -> None:
    """Apply type-specific properties to the light data block.

    Shared fields (``energy``, ``color``) are applied first; then we branch on
    ``kind`` for the variant-specific knobs. Missing/extra fields are
    tolerated — the MCP server has already validated them.
    """
    light_data.energy = float(p.get("energy", light_data.energy))
    color = p.get("color")
    if color is not None:
        light_data.color = (color[0], color[1], color[2])

    if kind == "point":
        light_data.shadow_soft_size = float(
            p.get("shadow_soft_size", light_data.shadow_soft_size)
        )
    elif kind == "sun":
        # The sun light's "angle" controls soft shadow size; stored in radians.
        angle_deg = p.get("angle_deg")
        if angle_deg is not None:
            from math import radians
            light_data.angle = radians(float(angle_deg))
    elif kind == "spot":
        from math import radians
        spot_size_deg = p.get("spot_size_deg")
        if spot_size_deg is not None:
            light_data.spot_size = radians(float(spot_size_deg))
        spot_blend = p.get("spot_blend")
        if spot_blend is not None:
            light_data.spot_blend = float(spot_blend)
        soft = p.get("shadow_soft_size")
        if soft is not None:
            light_data.shadow_soft_size = float(soft)
    elif kind == "area":
        shape = p.get("shape")
        if shape is not None:
            light_data.shape = shape
        size = p.get("size")
        if size is not None:
            light_data.size = float(size)
        size_y = p.get("size_y")
        if size_y is not None and shape in ("RECTANGLE", "ELLIPSE"):
            light_data.size_y = float(size_y)


def add_light(params: dict[str, Any]) -> dict[str, Any]:
    """Add a light of the requested kind (point/sun/spot/area)."""
    p = params.get("params", {})
    kind = p.get("kind")
    if kind not in ("point", "sun", "spot", "area"):
        return h.err("validation_error", f"unknown light kind: {kind!r}")

    name = params.get("name")
    if not isinstance(name, str) or not name:
        return h.err("validation_error", "missing 'name'")

    location = tuple(params.get("location", (0.0, 0.0, 0.0)))
    rotation_rad = h.deg_to_rad_tuple(
        tuple(params.get("rotation_euler_deg", (0.0, 0.0, 0.0)))  # type: ignore[arg-type]
    )

    blender_type = {
        "point": "POINT",
        "sun": "SUN",
        "spot": "SPOT",
        "area": "AREA",
    }[kind]

    try:
        bpy.ops.object.light_add(
            type=blender_type,
            location=location,
            rotation=rotation_rad,
        )
    except RuntimeError as exc:
        return h.err("blender_op_failed", f"light_add failed: {exc}")

    obj = bpy.context.active_object
    if obj is None or obj.type != "LIGHT":
        return h.err(
            "blender_op_failed",
            "light_add did not produce an active LIGHT object",
        )

    obj.name = name
    _configure_light(obj.data, kind, p)

    return h.ok(
        name=obj.name,
        kind=kind,
        location=list(h.vec3(obj.location)),
    )
