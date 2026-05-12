"""Camera tool: ``add_camera``."""

from __future__ import annotations

from fastmcp import FastMCP
from pydantic import TypeAdapter

from ..client import BlenderClient
from ..models import AddCameraInput, AddCameraResult
from ._common import parse_response

_add_camera_adapter: TypeAdapter[AddCameraResult] = TypeAdapter(AddCameraResult)


def register(mcp: FastMCP, client: BlenderClient) -> None:
    @mcp.tool()
    def add_camera(input: AddCameraInput) -> AddCameraResult:
        """Add a perspective camera at a given location, optionally aimed.

        ``target_object`` (if given) must already exist; we attach a Track-To
        constraint so the camera's view-axis points at it — no trig needed.
        ``set_active=True`` (default) makes this the scene's render camera,
        so the next ``render_image`` call uses it. Set DOF by passing BOTH
        ``dof_focus_distance`` (meters) and ``dof_aperture_fstop``.
        """
        raw = client.call("add_camera", input.model_dump(mode="json"))
        return parse_response(raw, _add_camera_adapter, "add_camera")
