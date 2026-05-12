"""Material tool: ``set_material`` (create + assign Principled BSDF).

One tool covers the common case of "make this object look like X" — create or
reuse a Principled BSDF, set its main knobs, assign it to a slot.

Addon-side counterpart: ``blender_addon/handlers/surface.py``.
"""

from __future__ import annotations

from fastmcp import FastMCP
from pydantic import TypeAdapter

from ..client import BlenderClient
from ..models import SetMaterialInput, SetMaterialResult
from ._common import parse_response

_set_material_adapter: TypeAdapter[SetMaterialResult] = TypeAdapter(
    SetMaterialResult
)


def register(mcp: FastMCP, client: BlenderClient) -> None:
    @mcp.tool()
    def set_material(input: SetMaterialInput) -> SetMaterialResult:
        """Create-or-update a Principled BSDF material and assign it to an
        object.

        Colors are linear RGB in [0, 1] — NOT sRGB hex. ``metallic`` toggles
        between dielectric (0) and metal (1); ``roughness`` is glossy (0) to
        matte (1). Set ``emission_color`` + ``emission_strength`` to make the
        material glow (useful for screens, neon, fake lights).

        Re-calling with the same ``material_name`` updates the existing
        material in place rather than creating a duplicate.
        """
        raw = client.call("set_material", input.model_dump(mode="json"))
        return parse_response(raw, _set_material_adapter, "set_material")
