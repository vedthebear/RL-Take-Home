"""Scene-lifecycle tool: ``clear_scene``."""

from __future__ import annotations

from fastmcp import FastMCP
from pydantic import TypeAdapter

from ..client import BlenderClient
from ..models import ClearSceneInput, ClearSceneResult
from ._common import parse_response

_clear_adapter: TypeAdapter[ClearSceneResult] = TypeAdapter(ClearSceneResult)


def register(mcp: FastMCP, client: BlenderClient) -> None:
    @mcp.tool()
    def clear_scene(input: ClearSceneInput) -> ClearSceneResult:
        """Remove all objects from the scene, with an optional allowlist.

        Useful as a first call when starting fresh — Blender's default scene
        ships with a Cube, a Camera, and a Light that will appear in most
        renders unless cleared. Pass names in ``keep`` to preserve specific
        objects. With ``also_remove_orphans=True`` (default), unused meshes,
        materials, lights, cameras, curves, and images are also purged.
        """
        raw = client.call("clear_scene", input.model_dump(mode="json"))
        return parse_response(raw, _clear_adapter, "clear_scene")
