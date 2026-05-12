"""Build-category handlers: primitives and modifiers."""

from __future__ import annotations

from typing import Any

import bpy

from . import _common as h


def add_primitive(params: dict[str, Any]) -> dict[str, Any]:
    """Create a mesh primitive of the requested kind.

    The MCP server has already validated the input shape via Pydantic, so we
    do light defensive defaulting here rather than full re-validation.
    """
    prim = params.get("params", {})
    kind = prim.get("kind")
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return h.err("validation_error", "missing or empty 'name'")

    location = tuple(params.get("location", (0.0, 0.0, 0.0)))
    rotation_deg = tuple(params.get("rotation_euler_deg", (0.0, 0.0, 0.0)))
    scale = tuple(params.get("scale", (1.0, 1.0, 1.0)))
    rotation_rad = h.deg_to_rad_tuple(rotation_deg)  # type: ignore[arg-type]

    try:
        if kind == "cube":
            bpy.ops.mesh.primitive_cube_add(
                size=float(prim.get("size", 2.0)),
                location=location,
                rotation=rotation_rad,
            )
        elif kind == "sphere":
            bpy.ops.mesh.primitive_uv_sphere_add(
                radius=float(prim.get("radius", 1.0)),
                segments=int(prim.get("segments", 32)),
                ring_count=int(prim.get("rings", 16)),
                location=location,
                rotation=rotation_rad,
            )
        elif kind == "cylinder":
            bpy.ops.mesh.primitive_cylinder_add(
                radius=float(prim.get("radius", 1.0)),
                depth=float(prim.get("depth", 2.0)),
                vertices=int(prim.get("vertices", 32)),
                location=location,
                rotation=rotation_rad,
            )
        elif kind == "cone":
            bpy.ops.mesh.primitive_cone_add(
                radius1=float(prim.get("radius_bottom", 1.0)),
                radius2=float(prim.get("radius_top", 0.0)),
                depth=float(prim.get("depth", 2.0)),
                vertices=int(prim.get("vertices", 32)),
                location=location,
                rotation=rotation_rad,
            )
        elif kind == "plane":
            bpy.ops.mesh.primitive_plane_add(
                size=float(prim.get("size", 2.0)),
                location=location,
                rotation=rotation_rad,
            )
        else:
            return h.err(
                "validation_error", f"unknown primitive kind: {kind!r}"
            )
    except RuntimeError as exc:
        return h.err("blender_op_failed", f"primitive_*_add failed: {exc}")

    obj = bpy.context.active_object
    if obj is None:
        return h.err(
            "blender_op_failed",
            "primitive was created but no active object after operator",
        )

    # Apply scale and rename. Blender auto-dedupes on collision: requesting
    # "Cube" when one exists yields "Cube.001". We surface the actual name.
    obj.scale = scale
    obj.name = name
    actual_name = obj.name

    return h.ok(
        name=actual_name,
        kind=kind,
        location=h.vec3(obj.location),
    )
