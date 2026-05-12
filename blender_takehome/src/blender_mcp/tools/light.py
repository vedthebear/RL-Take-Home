"""Lighting tool: ``add_light``."""

from __future__ import annotations

from fastmcp import FastMCP
from pydantic import TypeAdapter

from ..client import BlenderClient
from ..models import AddLightInput, AddLightResult
from ._common import parse_response

_add_light_adapter: TypeAdapter[AddLightResult] = TypeAdapter(AddLightResult)


def register(mcp: FastMCP, client: BlenderClient) -> None:
    @mcp.tool()
    def add_light(input: AddLightInput) -> AddLightResult:
        """Add a light at a given transform.

        Pick the ``kind`` (point, sun, spot, area) in ``params``; each has its
        own knobs. Sun light energy is in W/m^2; point/spot/area are in
        watts. Color is linear RGB. A scene with no light renders entirely
        black, so add at least one before rendering.
        """
        raw = client.call("add_light", input.model_dump(mode="json"))
        return parse_response(raw, _add_light_adapter, "add_light")
