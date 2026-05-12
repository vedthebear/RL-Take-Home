"""Tools that move, duplicate, or delete existing objects."""

from __future__ import annotations

from fastmcp import FastMCP
from pydantic import TypeAdapter

from ..client import BlenderClient
from ..models import (
    DeleteObjectInput,
    DeleteObjectResult,
    DuplicateObjectInput,
    DuplicateObjectResult,
    TransformObjectInput,
    TransformObjectResult,
)
from ._common import parse_response

_transform_adapter: TypeAdapter[TransformObjectResult] = TypeAdapter(
    TransformObjectResult
)
_duplicate_adapter: TypeAdapter[DuplicateObjectResult] = TypeAdapter(
    DuplicateObjectResult
)
_delete_adapter: TypeAdapter[DeleteObjectResult] = TypeAdapter(DeleteObjectResult)


def register(mcp: FastMCP, client: BlenderClient) -> None:
    @mcp.tool()
    def transform_object(input: TransformObjectInput) -> TransformObjectResult:
        """Set or delta-update an object's transform.

        Each of ``location``, ``rotation_euler_deg`` (degrees), and ``scale``
        is optional; at least one must be provided. In ``set`` mode the value
        replaces the current one; in ``delta`` mode location/rotation are
        added componentwise and scale is multiplied componentwise.
        """
        raw = client.call("transform_object", input.model_dump(mode="json"))
        return parse_response(raw, _transform_adapter, "transform_object")

    @mcp.tool()
    def duplicate_object(input: DuplicateObjectInput) -> DuplicateObjectResult:
        """Duplicate an existing object at an optional offset.

        ``linked=False`` (default) makes an independent copy. ``linked=True``
        shares the mesh data — cheaper but edits to one affect both. Useful
        for "make 5 identical chairs" without bloating the .blend file.
        """
        raw = client.call("duplicate_object", input.model_dump(mode="json"))
        return parse_response(raw, _duplicate_adapter, "duplicate_object")

    @mcp.tool()
    def delete_object(input: DeleteObjectInput) -> DeleteObjectResult:
        """Remove an object from the scene by name."""
        raw = client.call("delete_object", input.model_dump(mode="json"))
        return parse_response(raw, _delete_adapter, "delete_object")
