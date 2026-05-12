"""Tools that create or modify mesh geometry."""

from __future__ import annotations

from pydantic import TypeAdapter

from fastmcp import FastMCP

from ..client import BlenderClient
from ..models import (
    AddPrimitiveInput,
    AddPrimitiveResult,
)
from ._common import parse_response

_add_primitive_adapter: TypeAdapter[AddPrimitiveResult] = TypeAdapter(
    AddPrimitiveResult
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
