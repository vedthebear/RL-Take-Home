"""Inspection tools: ``get_scene_summary``, ``get_object``, ``render_image``."""

from __future__ import annotations

import base64
from typing import Final

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from pydantic import TypeAdapter

from ..client import (
    BlenderClient,
    RENDER_CALL_TIMEOUT_SECONDS,
)
from ..models import (
    GetObjectInput,
    GetObjectResult,
    GetSceneSummaryInput,
    GetSceneSummaryResult,
    RenderImageInput,
    RenderImageOk,
    RenderImageResult,
)
from ._common import parse_response

_scene_adapter: TypeAdapter[GetSceneSummaryResult] = TypeAdapter(
    GetSceneSummaryResult
)
_object_adapter: TypeAdapter[GetObjectResult] = TypeAdapter(GetObjectResult)
_render_adapter: TypeAdapter[RenderImageResult] = TypeAdapter(RenderImageResult)


def register(mcp: FastMCP, client: BlenderClient) -> None:
    @mcp.tool()
    def get_scene_summary(input: GetSceneSummaryInput) -> GetSceneSummaryResult:
        """List objects in the scene with light filtering and pagination.

        Use this before mutating anything: the scene may contain objects you
        should reuse or remove first. ``filter_type`` narrows by Blender type
        ("mesh", "camera", "light", "empty", "curve", "other", or "all").
        ``name_contains`` is a case-insensitive substring filter. ``limit``
        and ``offset`` paginate so big scenes never blow your context.
        """
        raw = client.call("get_scene_summary", input.model_dump(mode="json"))
        return parse_response(raw, _scene_adapter, "get_scene_summary")

    @mcp.tool()
    def get_object(input: GetObjectInput) -> GetObjectResult:
        """Return one object's transform, world-space bbox, material slots,
        modifier stack, and (for meshes) vertex/edge/face counts.

        Names are exact-match. If you got "Cube" back from ``add_primitive``
        but Blender deduped it to "Cube.001", pass the returned name.
        """
        raw = client.call("get_object", input.model_dump(mode="json"))
        return parse_response(raw, _object_adapter, "get_object")

    @mcp.tool()
    def render_image(input: RenderImageInput) -> RenderImageResult | Image:
        """Render the scene from the active camera.

        Writes a PNG to disk (``filepath`` or a temp file) and returns it
        inline as an MCP ``Image`` when ``return_image=True`` and the file
        is under ~4 MiB. Larger renders return the filepath only.

        Requires an active camera and at least one light; otherwise the
        render will fail or produce a black image. Use EEVEE Next
        (the default) for fast iteration; CYCLES for final-quality.
        """
        raw = client.call(
            "render_image",
            input.model_dump(mode="json"),
            timeout=RENDER_CALL_TIMEOUT_SECONDS,
        )
        result = parse_response(raw, _render_adapter, "render_image")

        # If the addon returned an inline image, return it as an MCP Image so
        # the agent gets a real ImageContent block instead of a base64 blob.
        # On failure or when image was skipped, return the structured result.
        if isinstance(result, RenderImageOk) and result.image_base64 is not None:
            return Image(data=base64.b64decode(result.image_base64), format="png")
        return result
