"""Material handler: create-or-reuse a Principled BSDF and assign it.

Two helpers carry most of the weight:

- ``_get_or_make_principled``: ensures the material has both a Principled BSDF
  node and a Material Output node, and wires them — so a custom material that
  was hand-built without the default graph still renders.
- ``_set_input``: tolerant socket write. Blender 4.x renamed several Principled
  sockets between point releases; missing-socket writes are silently dropped
  rather than raising.

MCP-side wrapper: ``src/blender_mcp/tools/surface.py``.
"""

from __future__ import annotations

from typing import Any

import bpy

from . import _common as h


def _get_or_make_principled(material: Any) -> Any:
    """Ensure the material has a Principled BSDF node wired to the output.

    Returns the Principled BSDF node. Most materials we create or touch will
    already have one (Blender adds it by default), but a custom material
    might not — in that case we rebuild a minimal graph.
    """
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    principled = next(
        (n for n in nodes if n.type == "BSDF_PRINCIPLED"), None
    )
    output = next(
        (n for n in nodes if n.type == "OUTPUT_MATERIAL"), None
    )
    if principled is None:
        principled = nodes.new("ShaderNodeBsdfPrincipled")
        principled.location = (0, 0)
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (300, 0)
    # Always (re)wire the surface link so a half-built graph still renders.
    surface_in = output.inputs.get("Surface")
    bsdf_out = principled.outputs.get("BSDF")
    if surface_in is not None and bsdf_out is not None:
        links.new(bsdf_out, surface_in)
    return principled


def _set_input(node: Any, name: str, value: Any) -> bool:
    """Set a node input by name. Returns whether the input existed.

    Blender 4.x has reshuffled Principled BSDF sockets between point releases
    (e.g. "Emission" -> "Emission Color" + "Emission Strength"). We treat all
    sets as optional rather than crashing on a missing socket.
    """
    inp = node.inputs.get(name)
    if inp is None:
        return False
    inp.default_value = value
    return True


def set_material(params: dict[str, Any]) -> dict[str, Any]:
    """Create-or-reuse a Principled BSDF material and assign it to an object.

    If a material with ``material_name`` already exists it is updated in
    place (so the agent can re-call ``set_material`` to recolor). The
    ``slot_index`` field chooses the material slot: ``None`` appends a new
    slot if needed; an integer replaces the material in that slot.
    """
    object_name = params.get("object_name")
    material_name = params.get("material_name")
    if not isinstance(object_name, str) or not object_name:
        return h.err("validation_error", "missing 'object_name'")
    if not isinstance(material_name, str) or not material_name:
        return h.err("validation_error", "missing 'material_name'")

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return h.err("object_not_found", f"no object named {object_name!r}")
    if obj.type != "MESH":
        return h.err(
            "invalid_state",
            f"object {object_name!r} is type {obj.type!r}; only MESH objects "
            "support material slots",
        )

    base_color = params.get("base_color", (0.8, 0.8, 0.8))
    metallic = float(params.get("metallic", 0.0))
    roughness = float(params.get("roughness", 0.5))
    alpha = float(params.get("alpha", 1.0))
    emission_color = params.get("emission_color")
    emission_strength = float(params.get("emission_strength", 0.0))
    slot_index = params.get("slot_index")

    mat = bpy.data.materials.get(material_name)
    created_new = mat is None
    if mat is None:
        mat = bpy.data.materials.new(name=material_name)

    try:
        principled = _get_or_make_principled(mat)
        _set_input(
            principled, "Base Color", (base_color[0], base_color[1], base_color[2], alpha)
        )
        _set_input(principled, "Metallic", metallic)
        _set_input(principled, "Roughness", roughness)
        _set_input(principled, "Alpha", alpha)
        if emission_color is not None:
            _set_input(
                principled,
                "Emission Color",
                (emission_color[0], emission_color[1], emission_color[2], 1.0),
            )
        _set_input(principled, "Emission Strength", emission_strength)
    except (RuntimeError, AttributeError, TypeError) as exc:
        return h.err(
            "blender_op_failed",
            f"failed to set material parameters: {exc}",
        )

    # Assign to the chosen slot.
    if slot_index is None:
        existing = [s for s in obj.material_slots if s.material is mat]
        if existing:
            chosen = obj.material_slots[:].index(existing[0])
        else:
            obj.data.materials.append(mat)
            chosen = len(obj.data.materials) - 1
    else:
        chosen = int(slot_index)
        while len(obj.data.materials) <= chosen:
            obj.data.materials.append(None)
        obj.data.materials[chosen] = mat

    return h.ok(
        object_name=obj.name,
        material_name=mat.name,
        slot_index=chosen,
        created_new_material=created_new,
    )
