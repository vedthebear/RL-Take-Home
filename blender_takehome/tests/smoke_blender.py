"""End-to-end smoke test against a running Blender addon.

NOT a pytest test — needs a live Blender instance with the MCP addon's
listener started (N-panel > MCP > Start MCP Server). Run with:

    uv run python -m tests.smoke_blender

The script walks every tool category once, then renders a PNG. Each step
prints ``PASS`` or ``FAIL`` with the relevant return fields. Exit code 0
on full success, 1 on any failure.

Keep the Blender viewport visible while running — every step should be
visible live as objects, lights, and the camera appear.
"""

from __future__ import annotations

import sys
from typing import Any

from blender_mcp.client import BlenderClient


def _step(client: BlenderClient, cmd: str, params: dict[str, Any]) -> dict[str, Any]:
    """Run one command, print PASS/FAIL + a one-line summary, return the payload."""
    reply = client.call(cmd, params)
    status = reply.get("status")
    ok = status == "ok"
    tag = "PASS" if ok else "FAIL"
    # Show a couple of useful fields so failures are obvious.
    if ok:
        # Trim long fields (image_base64 etc.) for readability.
        summary = {
            k: v for k, v in reply.items()
            if k not in ("status", "image_base64") and not isinstance(v, list)
            or (isinstance(v, list) and len(v) < 6)
        }
        print(f"  {tag}  {cmd}: {summary}")
    else:
        print(f"  {tag}  {cmd}: code={reply.get('code')!r} message={reply.get('message')!r}")
    return reply


def main() -> int:
    print("Blender MCP smoke test\n----------------------")
    client = BlenderClient()
    failures: list[str] = []

    def run(cmd: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        r = _step(client, cmd, params or {})
        if r.get("status") != "ok":
            failures.append(cmd)
        return r

    # 1. Bridge alive.
    run("ping", {"message": "smoke"})

    # 2. Clean slate.
    run("clear_scene", {"keep": []})

    # 3. Read initial state (should be empty).
    run("get_scene_summary", {"include_render_settings": False})

    # 4. Build a cube + modifier + transform.
    run("add_primitive", {
        "params": {"kind": "cube", "size": 1.5},
        "name": "Hero",
        "location": [0, 0, 1],
    })
    run("add_modifier", {
        "object_name": "Hero",
        "params": {"kind": "subdivision_surface", "levels": 2},
    })
    run("transform_object", {
        "name": "Hero",
        "mode": "delta",
        "rotation_euler_deg": [0, 0, 15],
    })

    # 5. Duplicate then delete the copy.
    dup = run("duplicate_object", {
        "source_name": "Hero",
        "new_name": "HeroCopy",
        "location_offset": [2.5, 0, 0],
    })
    if dup.get("status") == "ok":
        run("delete_object", {"name": dup["new_name"]})

    # 6. Floor + material.
    run("add_primitive", {
        "params": {"kind": "plane", "size": 10.0},
        "name": "Floor",
        "location": [0, 0, 0],
    })
    run("set_material", {
        "object_name": "Floor",
        "material_name": "FloorMat",
        "base_color": [0.35, 0.2, 0.1],
        "roughness": 0.7,
    })

    # 7. Light + camera (with track-to).
    run("add_light", {
        "params": {"kind": "sun", "energy": 3.0, "color": [1.0, 0.95, 0.85]},
        "name": "Sun",
        "rotation_euler_deg": [45, 0, 30],
    })
    run("add_camera", {
        "name": "Cam",
        "location": [6, -6, 4],
        "target_object": "Hero",
        "set_active": True,
    })

    # 8. Inspect the camera we just made.
    run("get_object", {"name": "Cam"})

    # 9. Render.
    render = run("render_image", {"resolution": [800, 450], "samples": 16})
    if render.get("status") == "ok":
        print(f"  --   render saved to: {render.get('filepath')}")

    print("----------------------")
    if failures:
        print(f"FAILURES: {failures}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
