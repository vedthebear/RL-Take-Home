"""Camera handler: add a perspective camera, optionally aimed at a target."""

from __future__ import annotations

from typing import Any

import bpy

from . import _common as h


def add_camera(params: dict[str, Any]) -> dict[str, Any]:
    """Add a perspective camera.

    If ``target_object`` is set, attach a Track-To constraint pointing the
    camera's negative-Z (its viewing axis) at that object. If ``set_active``
    is true, this camera becomes the scene's active render camera.
    """
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return h.err("validation_error", "missing 'name'")

    location = tuple(params.get("location", (7.0, -7.0, 5.0)))
    rotation_rad = h.deg_to_rad_tuple(
        tuple(params.get("rotation_euler_deg", (60.0, 0.0, 45.0)))  # type: ignore[arg-type]
    )
    focal_length = float(params.get("focal_length_mm", 50.0))
    target_name = params.get("target_object")
    set_active = bool(params.get("set_active", True))
    dof_distance = params.get("dof_focus_distance")
    dof_fstop = params.get("dof_aperture_fstop")

    if isinstance(target_name, str) and target_name:
        target = bpy.data.objects.get(target_name)
        if target is None:
            return h.err(
                "object_not_found",
                f"target_object {target_name!r} does not exist; create it first",
            )
    else:
        target = None

    try:
        bpy.ops.object.camera_add(location=location, rotation=rotation_rad)
    except RuntimeError as exc:
        return h.err("blender_op_failed", f"camera_add failed: {exc}")

    cam_obj = bpy.context.active_object
    if cam_obj is None or cam_obj.type != "CAMERA":
        return h.err(
            "blender_op_failed",
            "camera_add did not produce an active CAMERA object",
        )

    cam_obj.name = name
    cam_obj.data.lens = focal_length

    tracking: str | None = None
    if target is not None:
        constraint = cam_obj.constraints.new(type="TRACK_TO")
        constraint.target = target
        constraint.track_axis = "TRACK_NEGATIVE_Z"
        constraint.up_axis = "UP_Y"
        tracking = target.name

    if dof_distance is not None and dof_fstop is not None:
        cam_obj.data.dof.use_dof = True
        cam_obj.data.dof.focus_distance = float(dof_distance)
        cam_obj.data.dof.aperture_fstop = float(dof_fstop)

    if set_active:
        bpy.context.scene.camera = cam_obj

    return h.ok(
        name=cam_obj.name,
        location=list(h.vec3(cam_obj.location)),
        is_active=(bpy.context.scene.camera is cam_obj),
        tracking=tracking,
    )
