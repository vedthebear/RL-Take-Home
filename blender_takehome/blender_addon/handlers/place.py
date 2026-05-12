"""Object placement handlers: transform, duplicate, delete.

All three look up the target via ``bpy.data.objects.get(name)`` and bail with
``object_not_found`` if missing. Mutations are direct property assignments
(no operators), which keeps these handlers fast and side-effect-free.

MCP-side wrapper: ``src/blender_mcp/tools/place.py``.
"""

from __future__ import annotations

from typing import Any

import bpy

from . import _common as h


def transform_object(params: dict[str, Any]) -> dict[str, Any]:
    """Set or delta-update an object's transform.

    In ``set`` mode each given field replaces the current value. In ``delta``
    mode the location and rotation are added componentwise and the scale is
    multiplied componentwise. Fields left unset are untouched in both modes.
    """
    name = params.get("name")
    if not isinstance(name, str):
        return h.err("validation_error", "missing 'name'")
    obj = bpy.data.objects.get(name)
    if obj is None:
        return h.err("object_not_found", f"no object named {name!r}")

    mode = params.get("mode", "set")
    if mode not in ("set", "delta"):
        return h.err("validation_error", f"unknown mode: {mode!r}")

    new_location = params.get("location")
    new_rot_deg = params.get("rotation_euler_deg")
    new_scale = params.get("scale")

    try:
        if new_location is not None:
            if mode == "set":
                obj.location = tuple(new_location)
            else:
                obj.location = (
                    obj.location[0] + new_location[0],
                    obj.location[1] + new_location[1],
                    obj.location[2] + new_location[2],
                )

        if new_rot_deg is not None:
            new_rot_rad = h.deg_to_rad_tuple(tuple(new_rot_deg))  # type: ignore[arg-type]
            if mode == "set":
                obj.rotation_euler = new_rot_rad
            else:
                obj.rotation_euler = (
                    obj.rotation_euler[0] + new_rot_rad[0],
                    obj.rotation_euler[1] + new_rot_rad[1],
                    obj.rotation_euler[2] + new_rot_rad[2],
                )

        if new_scale is not None:
            if mode == "set":
                obj.scale = tuple(new_scale)
            else:
                obj.scale = (
                    obj.scale[0] * new_scale[0],
                    obj.scale[1] * new_scale[1],
                    obj.scale[2] * new_scale[2],
                )
    except (TypeError, ValueError) as exc:
        return h.err("validation_error", f"invalid transform payload: {exc}")

    rot = obj.rotation_euler
    return h.ok(
        name=obj.name,
        location=list(h.vec3(obj.location)),
        rotation_euler_deg=list(h.rad_to_deg_tuple((rot[0], rot[1], rot[2]))),
        scale=list(h.vec3(obj.scale)),
    )


def duplicate_object(params: dict[str, Any]) -> dict[str, Any]:
    """Duplicate an object at an optional offset.

    ``linked=True`` shares the underlying mesh data with the source (cheaper,
    but edits to the data propagate). ``linked=False`` (default) copies the
    mesh too.
    """
    source_name = params.get("source_name")
    if not isinstance(source_name, str):
        return h.err("validation_error", "missing 'source_name'")
    src = bpy.data.objects.get(source_name)
    if src is None:
        return h.err("object_not_found", f"no object named {source_name!r}")

    new_name = params.get("new_name")
    offset = tuple(params.get("location_offset", (0.0, 0.0, 0.0)))
    linked = bool(params.get("linked", False))

    try:
        copy = src.copy()
        if not linked and src.data is not None:
            copy.data = src.data.copy()
        if new_name:
            copy.name = new_name
        bpy.context.collection.objects.link(copy)
        copy.location = (
            src.location[0] + offset[0],
            src.location[1] + offset[1],
            src.location[2] + offset[2],
        )
    except RuntimeError as exc:
        return h.err("blender_op_failed", f"duplicate failed: {exc}")

    return h.ok(
        source_name=src.name,
        new_name=copy.name,
        location=list(h.vec3(copy.location)),
        linked=linked,
    )


def delete_object(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str):
        return h.err("validation_error", "missing 'name'")
    obj = bpy.data.objects.get(name)
    if obj is None:
        return h.err("object_not_found", f"no object named {name!r}")
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except RuntimeError as exc:
        return h.err("blender_op_failed", f"delete failed: {exc}")
    return h.ok(name=name)
