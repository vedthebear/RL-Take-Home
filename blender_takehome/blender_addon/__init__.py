"""Blender MCP Server — addon entry point (runs *inside* Blender).

System map (Blender-side)
=========================

This is the receiving half of the bridge. The other half (FastMCP server) is
in ``src/blender_mcp/``; the two halves talk over a TCP socket on
``localhost:9876``.

    TCP :9876
       │
       ▼
    ┌──────────────────────────┐
    │  AddonServer             │  blender_addon/server.py
    │  ─ listener thread       │   accepts connections
    │  ─ N worker threads      │   one per active client conn
    └────────────┬─────────────┘
                 │  queue.put((cmd, future))     ← worker threads (not main)
                 ▼
    ┌──────────────────────────┐
    │  Dispatcher              │  blender_addon/dispatcher.py
    │  ─ bpy.app.timers tick   │   runs on the main thread
    │  ─ drains queue          │
    └────────────┬─────────────┘
                 │  HANDLERS[name](params)       ← main thread only
                 ▼
    ┌──────────────────────────┐
    │  handlers/*.py           │  blender_addon/handlers/
    │  ─ get_scene_summary     │   the only files that touch bpy
    │  ─ add_primitive ...     │
    └──────────────────────────┘

The split exists because bpy is **main-thread-only**. Socket workers can't
call bpy directly without crashing Blender, so they hand work to the
dispatcher and wait on a ``concurrent.futures.Future``.

Installation:
1. Zip the ``blender_addon`` directory.
2. In Blender 4.2+: Edit > Preferences > Add-ons > Install from Disk > pick
   the zip. Enable "Interface: Blender MCP Server".
3. Open the 3D Viewport, press N to reveal the side panel, click the "MCP"
   tab, then "Start Server".
"""

from __future__ import annotations

import bpy
from bpy.props import IntProperty
from bpy.types import Operator, Panel, PropertyGroup, Scene

from . import dispatcher as _dispatcher
from . import server as _server
from .handlers import HANDLERS

bl_info = {
    "name": "Blender MCP Server",
    "author": "Ved Vedere",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > MCP",
    "description": "Expose Blender to AI agents via a local TCP socket.",
    "category": "Interface",
}

DEFAULT_PORT: int = 9876

# Module-level singletons. The addon lifecycle (register/unregister) owns these.
# They survive between Start/Stop clicks so the dispatcher's handler table
# isn't rebuilt every time the user toggles the listener.
_dispatcher_instance: _dispatcher.Dispatcher | None = None
_server_instance: _server.AddonServer | None = None


def _log(msg: str) -> None:
    print(msg)


# ---------------------------------------------------------------------------
# Property group: stores per-scene settings (port number, last status text).
# ---------------------------------------------------------------------------


class BLENDERMCP_PG_settings(PropertyGroup):
    port: IntProperty(  # type: ignore[valid-type]
        name="Port",
        description="TCP port to listen on (localhost only)",
        default=DEFAULT_PORT,
        min=1024,
        max=65535,
    )


# ---------------------------------------------------------------------------
# Operators: Start / Stop server.
# ---------------------------------------------------------------------------


class BLENDERMCP_OT_start_server(Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Start MCP Server"
    bl_description = "Open the local TCP socket and accept MCP commands"

    def execute(self, context: bpy.types.Context) -> set[str]:
        global _dispatcher_instance, _server_instance
        if _server_instance is not None and _server_instance.is_running():
            self.report({"WARNING"}, "MCP server already running")
            return {"CANCELLED"}

        if _dispatcher_instance is None:
            _dispatcher_instance = _dispatcher.Dispatcher()
            _dispatcher_instance.set_logger(_log)
            _dispatcher_instance.set_handlers(HANDLERS)

        if _server_instance is None:
            _server_instance = _server.AddonServer(_dispatcher_instance.submit)
            _server_instance.set_logger(_log)

        _dispatcher_instance.start()
        port = int(context.scene.blendermcp.port)
        try:
            _server_instance.start(port)
        except OSError as exc:
            _dispatcher_instance.stop()
            self.report({"ERROR"}, f"Failed to bind port {port}: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"MCP server listening on 127.0.0.1:{port}")
        return {"FINISHED"}


class BLENDERMCP_OT_stop_server(Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Stop MCP Server"
    bl_description = "Close the local TCP socket and stop processing commands"

    def execute(self, context: bpy.types.Context) -> set[str]:
        global _dispatcher_instance, _server_instance
        if _server_instance is not None:
            _server_instance.stop()
        if _dispatcher_instance is not None:
            _dispatcher_instance.stop()
        self.report({"INFO"}, "MCP server stopped")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Panel: View3D > Sidebar > MCP.
# ---------------------------------------------------------------------------


class BLENDERMCP_PT_panel(Panel):
    bl_label = "Blender MCP Server"
    bl_idname = "BLENDERMCP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MCP"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        settings = context.scene.blendermcp

        running = _server_instance is not None and _server_instance.is_running()

        col = layout.column(align=True)
        col.prop(settings, "port")

        row = layout.row(align=True)
        if running:
            port = _server_instance.port if _server_instance else "?"
            row.label(text=f"Running on :{port}", icon="RADIOBUT_ON")
        else:
            row.label(text="Stopped", icon="RADIOBUT_OFF")

        # Enable/disable is set on the row, not on the operator — the value
        # returned from row.operator() is an OperatorProperties for passing
        # arguments, not the button widget itself.
        row = layout.row(align=True)
        start_row = row.row(align=True)
        start_row.enabled = not running
        start_row.operator("blendermcp.start_server", icon="PLAY")
        stop_row = row.row(align=True)
        stop_row.enabled = running
        stop_row.operator("blendermcp.stop_server", icon="PAUSE")


# ---------------------------------------------------------------------------
# Registration.
# ---------------------------------------------------------------------------

_classes = (
    BLENDERMCP_PG_settings,
    BLENDERMCP_OT_start_server,
    BLENDERMCP_OT_stop_server,
    BLENDERMCP_PT_panel,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    Scene.blendermcp = bpy.props.PointerProperty(type=BLENDERMCP_PG_settings)  # type: ignore[attr-defined]


def unregister() -> None:
    # Stop the server cleanly so we don't leak the socket or the timer when
    # the addon is disabled / Blender shuts down.
    global _server_instance, _dispatcher_instance
    if _server_instance is not None:
        _server_instance.stop()
        _server_instance = None
    if _dispatcher_instance is not None:
        _dispatcher_instance.stop()
        _dispatcher_instance = None

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    if hasattr(Scene, "blendermcp"):
        del Scene.blendermcp  # type: ignore[attr-defined]
