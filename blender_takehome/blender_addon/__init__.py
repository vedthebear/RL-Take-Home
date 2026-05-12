"""Blender MCP Server — addon entry point.

Provides a 3D Viewport N-panel ("MCP" tab) with Start / Stop buttons. Starting
the server binds a TCP socket on ``localhost:<port>`` and registers a
main-thread timer to drain incoming commands. Stopping releases both.

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

        row = layout.row(align=True)
        start = row.operator("blendermcp.start_server", icon="PLAY")
        start.enabled = not running  # type: ignore[attr-defined]
        stop = row.operator("blendermcp.stop_server", icon="PAUSE")
        stop.enabled = running  # type: ignore[attr-defined]


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
