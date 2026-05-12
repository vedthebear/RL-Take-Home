"""Read-only handlers: scene summary, object detail, rendering.

These never mutate state — they're the "perception" side of the agent loop.
``render_image`` does write a PNG to disk (the renderer's only sane output
path), but it leaves the scene graph untouched.

MCP-side wrapper: ``src/blender_mcp/tools/perceive.py``.
"""

from __future__ import annotations

import base64
import os
import tempfile
from typing import Any

import bpy
from mathutils import Vector

from . import _common as h

# Type strings that map cleanly back to the filter values exposed to agents.
_BLENDER_TYPE_FROM_FILTER: dict[str, str] = {
    "mesh": "MESH",
    "camera": "CAMERA",
    "light": "LIGHT",
    "empty": "EMPTY",
    "curve": "CURVE",
}
_KNOWN_BLENDER_TYPES: set[str] = set(_BLENDER_TYPE_FROM_FILTER.values())

INLINE_IMAGE_CAP_BYTES: int = 4 * 1024 * 1024


def _resolve_eevee_engine() -> str:
    """Return the EEVEE engine identifier for the running Blender version.

    Blender 5.0 removed the legacy EEVEE engine and renamed
    ``BLENDER_EEVEE_NEXT`` back to ``BLENDER_EEVEE``. Older 4.x revisions
    have both engines and the "next" one carries the ``_NEXT`` suffix.
    Always ask Blender which one to use rather than guessing.
    """
    return "BLENDER_EEVEE" if bpy.app.version[0] >= 5 else "BLENDER_EEVEE_NEXT"


# ---------------------------------------------------------------------------
# get_scene_summary
# ---------------------------------------------------------------------------


def get_scene_summary(params: dict[str, Any]) -> dict[str, Any]:
    scene = bpy.context.scene

    filter_type = params.get("filter_type", "all")
    name_contains = params.get("name_contains")
    name_contains_lc = name_contains.lower() if isinstance(name_contains, str) else None
    limit = int(params.get("limit", 100))
    offset = int(params.get("offset", 0))
    include_render = bool(params.get("include_render_settings", True))

    counts_by_type: dict[str, int] = {}
    matching: list[Any] = []
    for obj in scene.objects:
        counts_by_type[obj.type] = counts_by_type.get(obj.type, 0) + 1

        if filter_type != "all":
            if filter_type == "other":
                if obj.type in _KNOWN_BLENDER_TYPES:
                    continue
            else:
                expected = _BLENDER_TYPE_FROM_FILTER.get(filter_type)
                if expected is None or obj.type != expected:
                    continue
        if name_contains_lc is not None and name_contains_lc not in obj.name.lower():
            continue
        matching.append(obj)

    total = len(matching)
    page = matching[offset : offset + limit]

    objects_brief = [
        {
            "name": obj.name,
            "type": obj.type,
            "location": list(h.vec3(obj.location)),
            "hidden": bool(obj.hide_viewport),
        }
        for obj in page
    ]

    render_brief: dict[str, Any] | None = None
    if include_render:
        r = scene.render
        engine = r.engine
        if engine == "CYCLES":
            samples = int(getattr(scene.cycles, "samples", 0))
        elif engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
            samples = int(getattr(scene.eevee, "taa_render_samples", 0))
        else:
            samples = 0
        render_brief = {
            "engine": engine,
            "resolution": [int(r.resolution_x), int(r.resolution_y)],
            "samples": samples,
            "output_filepath": r.filepath,
        }

    return h.ok(
        total_objects=total,
        returned_count=len(page),
        objects=objects_brief,
        counts_by_type=counts_by_type,
        active_camera=scene.camera.name if scene.camera is not None else None,
        render=render_brief,
    )


# ---------------------------------------------------------------------------
# get_object
# ---------------------------------------------------------------------------


def _principled_node(material: Any) -> Any | None:
    if not material or not getattr(material, "use_nodes", False):
        return None
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def _read_principled_brief(material: Any) -> dict[str, Any]:
    """Best-effort read of a few well-known Principled BSDF sockets.

    Socket names differ slightly across Blender 4.x revisions; treat all reads
    as optional so a renamed/missing socket doesn't crash the whole call.
    """
    out: dict[str, Any] = {}
    node = _principled_node(material)
    if node is None:
        return out
    inputs = node.inputs
    bc = inputs.get("Base Color")
    if bc is not None:
        rgba = bc.default_value
        out["base_color"] = [float(rgba[0]), float(rgba[1]), float(rgba[2])]
    metallic = inputs.get("Metallic")
    if metallic is not None:
        out["metallic"] = float(metallic.default_value)
    roughness = inputs.get("Roughness")
    if roughness is not None:
        out["roughness"] = float(roughness.default_value)
    return out


def get_object(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return h.err("validation_error", "missing or empty 'name'")
    obj = bpy.data.objects.get(name)
    if obj is None:
        return h.err("object_not_found", f"no object named {name!r}")

    include_mesh_stats = bool(params.get("include_mesh_stats", True))

    # World-space AABB derived from local bbox + matrix_world.
    bbox_world_min: list[float] | None = None
    bbox_world_max: list[float] | None = None
    if obj.bound_box:
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        zs = [c.z for c in corners]
        bbox_world_min = [min(xs), min(ys), min(zs)]
        bbox_world_max = [max(xs), max(ys), max(zs)]

    # Material slots, with a light read of the Principled BSDF if present.
    material_slots: list[dict[str, Any]] = []
    for i, slot in enumerate(obj.material_slots):
        entry: dict[str, Any] = {
            "slot_index": i,
            "material_name": slot.material.name if slot.material else None,
        }
        if slot.material is not None:
            entry.update(_read_principled_brief(slot.material))
        material_slots.append(entry)

    modifiers = [{"name": m.name, "type": m.type} for m in obj.modifiers]

    mesh_stats: dict[str, int] | None = None
    if include_mesh_stats and obj.type == "MESH":
        mesh = obj.data
        mesh_stats = {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "faces": len(mesh.polygons),
        }

    rot = obj.rotation_euler
    return h.ok(
        name=obj.name,
        type=obj.type,
        location=list(h.vec3(obj.location)),
        rotation_euler_deg=list(h.rad_to_deg_tuple((rot[0], rot[1], rot[2]))),
        scale=list(h.vec3(obj.scale)),
        bbox_world_min=bbox_world_min,
        bbox_world_max=bbox_world_max,
        material_slots=material_slots,
        modifiers=modifiers,
        mesh_stats=mesh_stats,
    )


# ---------------------------------------------------------------------------
# render_image
# ---------------------------------------------------------------------------


def render_image(params: dict[str, Any]) -> dict[str, Any]:
    """Render the scene from the active camera; return the PNG inline."""
    scene = bpy.context.scene

    if scene.camera is None:
        return h.err(
            "invalid_state",
            "no active camera set. call add_camera (or set_active_camera) "
            "before rendering",
        )

    requested_engine = params.get("engine", "BLENDER_EEVEE")
    # Accept either EEVEE alias from any-vintage caller, then translate to
    # whatever the running Blender expects. CYCLES passes through unchanged.
    if requested_engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        engine = _resolve_eevee_engine()
    elif requested_engine == "CYCLES":
        engine = "CYCLES"
    else:
        return h.err(
            "validation_error", f"unsupported render engine: {requested_engine!r}"
        )
    resolution = params.get("resolution", (1280, 720))
    samples = int(params.get("samples", 64))
    return_image = bool(params.get("return_image", True))

    filepath = params.get("filepath")
    if not isinstance(filepath, str) or not filepath:
        fd, filepath = tempfile.mkstemp(prefix="blender_mcp_render_", suffix=".png")
        os.close(fd)

    # Apply settings.
    r = scene.render
    r.engine = engine
    r.resolution_x = int(resolution[0])
    r.resolution_y = int(resolution[1])
    r.image_settings.file_format = "PNG"
    r.filepath = filepath
    if engine == "CYCLES":
        scene.cycles.samples = samples
    else:
        scene.eevee.taa_render_samples = samples

    try:
        bpy.ops.render.render(write_still=True)
    except RuntimeError as exc:
        return h.err("blender_op_failed", f"render failed: {exc}")

    if not os.path.exists(filepath):
        return h.err(
            "blender_op_failed",
            "render completed but no file was written at the expected path",
            details={"filepath": filepath},
        )

    image_b64: str | None = None
    skipped_reason: str | None = None
    if return_image:
        size = os.path.getsize(filepath)
        if size > INLINE_IMAGE_CAP_BYTES:
            skipped_reason = (
                f"image is {size} bytes (> {INLINE_IMAGE_CAP_BYTES}); "
                "returning filepath only"
            )
        else:
            with open(filepath, "rb") as fh:
                image_b64 = base64.b64encode(fh.read()).decode("ascii")

    return h.ok(
        filepath=filepath,
        width=int(r.resolution_x),
        height=int(r.resolution_y),
        engine=engine,
        image_base64=image_b64,
        image_skipped_reason=skipped_reason,
    )
