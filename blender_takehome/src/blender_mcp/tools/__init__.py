"""Tool registrations.

Each submodule exposes a ``register(mcp, client)`` function that decorates
its tool functions on the given ``FastMCP`` instance, closing over the shared
``BlenderClient``. ``blender_mcp.server`` calls them in sequence.
"""
