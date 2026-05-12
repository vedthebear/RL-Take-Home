"""Tool registrations.

Each submodule exposes a ``register(mcp, client)`` function that decorates
its tool functions on the given ``FastMCP`` instance, closing over the shared
``BlenderClient``. ``blender_mcp.server`` calls them in sequence.

These wrappers are intentionally thin: they validate the input via Pydantic,
forward the dict over the socket via ``client.call(...)``, and re-parse the
addon's reply into a discriminated ``<Tool>Ok | Failure`` union. The bpy code
that actually does the work lives in ``blender_addon/handlers/`` under the
same category name (e.g. ``tools/build.py`` <-> ``handlers/build.py``).
"""
