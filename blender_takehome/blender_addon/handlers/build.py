"""Build-category handlers: primitives and modifiers."""

from __future__ import annotations

from math import radians
from typing import Any

import bpy

from . import _common as h


_MODIFIER_TYPE_FROM_KIND: dict[str, str] = {
    "subdivision_surface": "SUBSURF",
    "bevel": "BEVEL",
    "array": "ARRAY",
    "boolean": "BOOLEAN",
    "solidify": "SOLIDIFY",
}


def _apply_modifier_settings(mod: Any, kind: str, p: dict[str, Any]) -> str | None:
    """Apply variant-specific properties to a freshly-created modifier.

    Returns an error message on failure, ``None`` on success. Each branch
    only touches the fields the Pydantic schema defines for that kind.
    """
    if kind == "subdivision_surface":
        mod.levels = int(p.get("levels", 2))
        mod.render_levels = int(p.get("render_levels", 2))
        st = p.get("subdivision_type")
        if st is not None:
            mod.subdivision_type = st
    elif kind == "bevel":
        mod.width = float(p.get("width", 0.1))
        mod.segments = int(p.get("segments", 2))
        mod.profile = float(p.get("profile", 0.5))
        lm = p.get("limit_method")
        if lm is not None:
            mod.limit_method = lm
        angle_limit_deg = p.get("angle_limit_deg")
        if angle_limit_deg is not None:
            mod.angle_limit = radians(float(angle_limit_deg))
    elif kind == "array":
        mod.count = int(p.get("count", 3))
        offset = p.get("relative_offset", (1.0, 0.0, 0.0))
        mod.relative_offset_displace = tuple(offset)
    elif kind == "boolean":
        target_name = p.get("target_object")
        if not isinstance(target_name, str):
            return f"boolean modifier requires 'target_object'"
        target = bpy.data.objects.get(target_name)
        if target is None:
            return f"target_object {target_name!r} does not exist"
        mod.object = target
        op = p.get("operation")
        if op is not None:
            mod.operation = op
        solver = p.get("solver")
        if solver is not None:
            mod.solver = solver
    elif kind == "solidify":
        mod.thickness = float(p.get("thickness", 0.05))
        mod.offset = float(p.get("offset", -1.0))
    else:
        return f"unknown modifier kind: {kind!r}"
    return None


def add_modifier(params: dict[str, Any]) -> dict[str, Any]:
    """Add a modifier to an object, optionally baking it immediately."""
    object_name = params.get("object_name")
    if not isinstance(object_name, str) or not object_name:
        return h.err("validation_error", "missing 'object_name'")
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return h.err("object_not_found", f"no object named {object_name!r}")

    p = params.get("params", {})
    kind = p.get("kind")
    mod_type = _MODIFIER_TYPE_FROM_KIND.get(kind) if isinstance(kind, str) else None
    if mod_type is None:
        return h.err("validation_error", f"unknown modifier kind: {kind!r}")

    requested_name = params.get("modifier_name") or f"{kind}"
    apply_immediately = bool(params.get("apply_immediately", False))

    try:
        mod = obj.modifiers.new(name=requested_name, type=mod_type)
    except RuntimeError as exc:
        return h.err("blender_op_failed", f"modifiers.new failed: {exc}")

    actual_name = mod.name
    config_err = _apply_modifier_settings(mod, kind, p)  # type: ignore[arg-type]
    if config_err is not None:
        # Roll back the half-configured modifier so we don't leave junk behind.
        try:
            obj.modifiers.remove(mod)
        except RuntimeError:
            pass
        return h.err("validation_error", config_err)

    applied = False
    if apply_immediately:
        try:
            h.select_only(obj)
            bpy.ops.object.modifier_apply(modifier=actual_name)
            applied = True
        except RuntimeError as exc:
            return h.err("blender_op_failed", f"modifier_apply failed: {exc}")

    return h.ok(
        object_name=obj.name,
        modifier_name=actual_name,
        kind=kind,
        applied=applied,
    )


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
