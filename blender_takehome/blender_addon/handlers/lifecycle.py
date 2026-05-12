"""Lifecycle-related handlers (ping, clear_scene)."""

from __future__ import annotations

import time
from typing import Any

import bpy

from . import _common as h


def ping(params: dict[str, Any]) -> dict[str, Any]:
    """Health-check round trip. Echoes any ``message`` field and adds a server
    timestamp so the caller can verify both directions of the link."""
    return {
        "status": "ok",
        "message": params.get("message", "pong"),
        "server_time": time.time(),
    }


def clear_scene(params: dict[str, Any]) -> dict[str, Any]:
    """Remove all objects from the scene except those named in ``keep``.

    Uses direct ``bpy.data.objects.remove`` instead of
    ``bpy.ops.wm.read_factory_settings`` — the latter would re-run addon
    registration and yank our socket out from under us.

    If ``also_remove_orphans`` is true, any meshes/materials/lights/cameras
    left dangling (zero users) are purged afterward.
    """
    keep_list = params.get("keep", [])
    if not isinstance(keep_list, list):
        return h.err("validation_error", "'keep' must be a list of names")
    keep = set(keep_list)

    removed: list[str] = []
    kept: list[str] = []
    # Materialize the iterator: removing during iteration corrupts the
    # collection.
    for obj in list(bpy.data.objects):
        if obj.name in keep:
            kept.append(obj.name)
            continue
        removed.append(obj.name)
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except RuntimeError:
            # If a single object resists removal, log and continue rather
            # than abort the whole purge.
            pass

    orphans_removed = 0
    if bool(params.get("also_remove_orphans", True)):
        for collection in (
            bpy.data.meshes,
            bpy.data.materials,
            bpy.data.lights,
            bpy.data.cameras,
            bpy.data.curves,
            bpy.data.images,
        ):
            for datablock in list(collection):
                if datablock.users == 0:
                    collection.remove(datablock)
                    orphans_removed += 1

    return h.ok(
        removed_objects=removed,
        kept_objects=kept,
        orphans_removed=orphans_removed,
    )
