"""Build tools: ``add_primitive`` and ``add_modifier``.

Both use a discriminated union on ``kind`` so the LLM gets a clean ``oneOf``
JSON Schema (one variant per primitive / modifier type) instead of a fat
schema with many optional fields.

Addon-side counterpart: ``blender_addon/handlers/build.py``.
"""

from __future__ import annotations

from pydantic import TypeAdapter

from fastmcp import FastMCP

from ..client import BlenderClient
from ..models import (
    AddModifierInput,
    AddModifierResult,
    AddPrimitiveInput,
    AddPrimitiveResult,
)
from ._common import parse_response

_add_primitive_adapter: TypeAdapter[AddPrimitiveResult] = TypeAdapter(
    AddPrimitiveResult
)
_add_modifier_adapter: TypeAdapter[AddModifierResult] = TypeAdapter(
    AddModifierResult
)


def register(mcp: FastMCP, client: BlenderClient) -> None:
    @mcp.tool()
    def add_primitive(input: AddPrimitiveInput) -> AddPrimitiveResult:
        """Create a mesh primitive at a given transform.

        Pick the primitive ``kind`` (cube, sphere, cylinder, cone, plane) in
        the ``params`` object. The shared ``name``, ``location``,
        ``rotation_euler_deg`` (degrees), and ``scale`` fields position it.

        Important: the returned ``name`` may differ from the one you
        requested. Blender silently appends ``.001`` to collisions; always
        use the returned name for follow-up tool calls.
        """
        raw = client.call("add_primitive", input.model_dump(mode="json"))
        return parse_response(raw, _add_primitive_adapter, "add_primitive")

    @mcp.tool()
    def add_modifier(input: AddModifierInput) -> AddModifierResult:
        """Attach a modifier to an object and optionally bake it.

        Supported ``kind`` values: ``subdivision_surface``, ``bevel``,
        ``array``, ``boolean``, ``solidify``. The ``boolean`` modifier
        requires a ``target_object`` that already exists.

        Set ``apply_immediately=True`` to bake the modifier into the mesh —
        useful for booleans where you want the cut to be permanent. Without
        baking, modifiers stack non-destructively (cheaper and re-editable).
        """
        raw = client.call("add_modifier", input.model_dump(mode="json"))
        return parse_response(raw, _add_modifier_adapter, "add_modifier")
