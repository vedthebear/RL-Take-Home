"""FastMCP entry point.

This module exposes the MCP server that AI agents connect to. It maintains a
single ``BlenderClient`` and registers one ``@mcp.tool`` per Blender operation.

The tools live in ``blender_mcp.tools.*`` — this module is just the wiring.
"""

from __future__ import annotations

import os
import sys

from fastmcp import FastMCP

from .client import BlenderClient
from .tools import build as _tools_build
from .tools import perceive as _tools_perceive

mcp: FastMCP = FastMCP(
    name="blender-mcp",
    instructions=(
        "Blender MCP server. Tools manipulate a live Blender scene through a "
        "local addon. Always call get_scene_summary before mutating anything, "
        "and call render_image to verify visual changes. Names returned by "
        "create-type tools may differ from the requested name if Blender "
        "deduped them — always use the returned name for subsequent calls."
    ),
)

# Shared client. Lazy-connects on first tool call; ``BLENDER_MCP_HOST`` /
# ``BLENDER_MCP_PORT`` override the defaults if the addon is on a non-standard
# port (rare; mostly useful when multiple Blender instances are running).
_client: BlenderClient = BlenderClient(
    host=os.environ.get("BLENDER_MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("BLENDER_MCP_PORT", "9876")),
)


def get_client() -> BlenderClient:
    """Used by tool modules to share the single client instance."""
    return _client


@mcp.tool()
def ping(message: str = "hello") -> dict[str, object]:
    """Round-trip a message through the Blender addon.

    Useful as a first call to verify the addon is running and reachable
    before issuing structured commands.
    """
    return _client.call("ping", {"message": message})


# Register category-grouped tools.
_tools_build.register(mcp, _client)
_tools_perceive.register(mcp, _client)


# ---------------------------------------------------------------------------
# Strategy prompt
# ---------------------------------------------------------------------------


@mcp.prompt()
def blender_design_strategy() -> str:
    """Recommended workflow for an agent designing in Blender.

    Inject this as the system or developer prompt when using the blender-mcp
    tools, or reference it from the agent's own setup instructions.
    """
    return (
        "You have tools that manipulate a live Blender scene. Follow this loop:\n"
        "\n"
        "1. **Perceive first.** Call `get_scene_summary` before doing anything; "
        "the scene may already have objects you should reuse or remove. Call "
        "`get_object` for details before transforming or modifying.\n"
        "\n"
        "2. **One mutation, one call.** Don't batch related ideas — each tool "
        "is fast and idempotent enough that small steps are cheaper than "
        "complex ones.\n"
        "\n"
        "3. **Use the returned name.** When you create an object, Blender may "
        "rename it (e.g. `Cube` -> `Cube.001`) to avoid collisions. The "
        "response always carries the *actual* assigned name — track that, "
        "not what you asked for.\n"
        "\n"
        "4. **Verify visually.** After non-trivial changes, call "
        "`render_image` and inspect the returned PNG. If composition or "
        "lighting is wrong, fix it before adding more detail.\n"
        "\n"
        "5. **Units.** Rotations are in **degrees**. Colors are linear RGB "
        "in [0, 1] (not sRGB hex). Distances are meters.\n"
        "\n"
        "6. **A scene needs a camera and at least one light.** Without an "
        "active camera, `render_image` fails. Without lighting, every render "
        "is black.\n"
    )


def main() -> None:
    """Console entry point: ``blender-mcp`` (see pyproject scripts)."""
    transport = os.environ.get("BLENDER_MCP_TRANSPORT", "stdio")
    if transport not in ("stdio", "sse", "http"):
        sys.stderr.write(
            f"unsupported transport {transport!r}; expected stdio|sse|http\n"
        )
        sys.exit(2)
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
