# Blender MCP Server

A FastMCP server that exposes a Blender 4.2+ scene to AI agents via 12
structured tools, plus a thin Blender addon that hosts the receiving end of
the bridge.

```
LLM ─▶ FastMCP server (this process) ─▶ TCP :9876 ─▶ Blender addon ─▶ bpy
```

The MCP server runs as a normal Python process (started by your MCP-aware
client). The addon runs inside Blender and listens on a local TCP port. You
start each independently; the MCP server lazy-connects on the first tool
call.

---

## Install

### 1. Python deps (MCP server side)

```bash
cd blender_takehome
uv sync --extra dev   # or: pip install -e ".[dev]"
```

This installs FastMCP, Pydantic, loguru, pytest, pyright, and the
`fake-bpy-module-latest` type stubs (used at static-analysis time only).

### 2. Blender addon (the bpy side)

Blender 4.2 LTS or later is required.

1. Zip the `blender_addon/` directory: `zip -r blender_mcp_addon.zip blender_addon`
2. In Blender: **Edit → Preferences → Add-ons → Install...**, pick the zip,
   and enable "Interface: Blender MCP Server".
3. In the 3D Viewport press **N** to open the sidebar, then click the
   **MCP** tab. Set a port if you don't want the default 9876, then click
   **Start MCP Server**.

The addon prints the bound address to the system console
(`Window → Toggle System Console` on Windows; stdout where Blender was
launched from on macOS / Linux).

### 3. Connect an MCP client

Run the server in stdio mode from any MCP-aware client:

```bash
uv run blender-mcp
```

Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "blender": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/blender_takehome", "run", "blender-mcp"]
    }
  }
}
```

Environment overrides for non-default setups: `BLENDER_MCP_HOST`,
`BLENDER_MCP_PORT`, `BLENDER_MCP_TRANSPORT` (`stdio` | `sse` | `http`).

---

## Tools

12 structured tools, grouped by job. **Every tool returns a Pydantic
discriminated union of `<Tool>Ok | Failure` on a `status` field.**

### Perceive (the agent's eyes)

| Tool | Purpose |
|---|---|
| `get_scene_summary` | Filterable, paginated list of scene objects with counts-by-type, active camera, and render-settings snapshot |
| `get_object` | One object's transform, world-space bbox, material slots (with Principled BSDF brief), modifier stack, and mesh stats |
| `render_image` | Render the active camera via EEVEE Next or Cycles; returns the PNG inline as an MCP `Image` (≤ 4 MiB) plus filepath |

### Build

| Tool | Purpose |
|---|---|
| `add_primitive` | Discriminated union over cube / sphere / cylinder / cone / plane; per-kind validated params + shared transform |
| `add_modifier` | Discriminated union over subdivision_surface / bevel / array / boolean / solidify; optional `apply_immediately` |

### Place

| Tool | Purpose |
|---|---|
| `transform_object` | Set or delta-update location / rotation_euler_deg / scale; at least one field required |
| `duplicate_object` | Copy an object with optional offset and `linked` (shared mesh data) flag |
| `delete_object` | Remove an object by name |

### Surface

| Tool | Purpose |
|---|---|
| `set_material` | Create-or-update a Principled BSDF (base_color, metallic, roughness, alpha, emission) and assign to an object slot |

### Light

| Tool | Purpose |
|---|---|
| `add_light` | Discriminated union over point / sun / spot / area; per-kind energy, color, and shape params |

### Frame

| Tool | Purpose |
|---|---|
| `add_camera` | Add a perspective camera; optional Track-To target, optional DOF, optional set-active |

### Lifecycle

| Tool | Purpose |
|---|---|
| `clear_scene` | Remove all objects (with `keep` allowlist); optionally purge orphan meshes / materials / lights / etc. |
| `ping` | Health check (round-trips through the addon) |

The server also publishes a single `@mcp.prompt()` named
`blender_design_strategy` summarizing the loop (perceive → mutate → verify)
and the conventions (degrees, linear RGB, returned names).

---

## Design decisions

### Architecture: addon + socket, not in-process bpy

The MCP server and Blender are different processes. The addon hosts a TCP
listener; the MCP server connects on demand. This was picked over the
standalone `bpy` pip module because **the demo story matters** — an
evaluator watching the demo video sees the Blender viewport reshape itself
in real time as the agent works, which is dramatically more legible than
files appearing on disk.

The wire format is length-prefixed JSON. Encoders, partial-read handling,
and connection-drop semantics are covered by `tests/test_protocol.py`.

### Structured-only — no `execute_python` escape hatch

Existing Blender MCP servers (notably `ahujasid/blender-mcp`) ship an
`execute_blender_code` tool that takes arbitrary `bpy` Python from the agent.
It works, but it bypasses input validation entirely and exposes the LLM to
every Blender footgun. This project deliberately omits it. Every common
operation must be reachable through a structured tool with a Pydantic
schema. The tradeoff: the toolset has to be *complete enough* — corners
the agent might reach for (e.g. mesh editing primitives like extrude) are
documented limitations rather than escape-hatched.

### Discriminated unions everywhere

`add_primitive`, `add_modifier`, and `add_light` all dispatch on a `kind`
literal, with one Pydantic variant per case (`CubeParams`, `SphereParams`,
…). This gives the LLM a clean `oneOf` JSON Schema rather than one fat
schema with many optional fields, and keeps the addon-side switch
exhaustive and grep-able.

### Returned name vs. requested name

Blender silently dedupes object names: ask for `Cube` when one exists and
you get `Cube.001`. Every create-style handler returns the **actual**
assigned name, never assumes the request was honored. The strategy prompt
tells the agent to track and reuse that returned name.

### Units, conventions

- **Rotation**: degrees on the wire, converted to radians inside handlers.
- **Colors**: linear RGB in `[0, 1]`. Not sRGB hex.
- **Distances**: meters (Blender's default).
- **Target Blender**: 4.2 LTS or later. Earlier 4.x versions used different
  Principled BSDF socket names; we read tolerantly (a missing socket is
  skipped, not raised) but assume the 4.2+ layout when writing.

### Threading invariant

bpy is main-thread-only. Socket workers in the addon push commands onto a
queue; a single persistent `bpy.app.timers` callback drains it on the main
thread. Each command is paired with a `concurrent.futures.Future`; handler
exceptions are caught and become structured `Failure` payloads, so the
worker thread *always* gets a response (never hangs).

---

## Demo prompt

A short prompt that exercises every category cleanly:

> Build a still life: a wooden table-top plane, three colored spheres of
> different materials (matte red, glossy gold metal, a glowing emissive
> blue), lit by a warm sun from above-left, framed by a 50 mm camera at a
> 3/4 angle pointing at the middle sphere. Render at 1280×720 EEVEE Next
> and show me.

Expected sequence: `clear_scene` → `add_primitive` (plane) → `set_material`
(wood-ish brown) → `add_primitive` × 3 (spheres at offsets) →
`set_material` × 3 → `add_light` (sun) → `add_camera` (with
`target_object`) → `render_image`.

---

## Out of scope (v1)

Deliberate omissions, in rough order of "most likely to come back":

- **Mesh editing** (extrude / inset / bevel-by-edge). The Bevel and
  Subdivision Surface modifiers cover ~90% of "smooth and round" use cases;
  destructive mesh editing was deferred to keep the tool surface tight.
- **Animation / keyframes**. Possible follow-up — would add `set_keyframe`
  / `set_frame_range`.
- **World HDRI / asset libraries** (PolyHaven, Sketchfab). Free realism
  unlock, but requires HTTP, file management, and texture cache logic.
- **Save / open .blend files**. Snapshot the entire session; modest code
  but not in the rubric's evaluation rubric.
- **Geometry nodes**. Out of scope for a 1–2 day budget.

---

## Tests

```bash
uv run pytest -q
```

84 unit tests covering:

- All Pydantic input/output models (`tests/test_models.py`): name and
  coordinate validators, every `ErrorCode` literal, discriminator parsing
  for each tagged union, cross-field constraints (transform requires one
  field; camera DOF pair), JSON round-trips.
- Wire framing (`tests/test_protocol.py`): encode/decode, partial reads,
  mid-header / mid-body connection drops, oversized payloads, malformed
  JSON, non-object top-level.
- The TCP client (`tests/test_client.py`): happy-path round-trip,
  connection reuse, connection refused → `connection_lost`, hung server →
  `timeout`, ID mismatch / non-object payload → `internal_error`,
  transparent reconnect after a transport failure.

The bpy-touching code (the addon handlers) is exercised manually inside
Blender — see the demo prompt above.

---

## Project layout

```
blender_takehome/
├── blender_addon/                      # installed inside Blender
│   ├── __init__.py                     # bl_info, register/unregister, N-panel UI
│   ├── _protocol.py                    # length-prefixed JSON framing (mirrors src/.../protocol.py)
│   ├── server.py                       # TCP listener + per-conn worker threads
│   ├── dispatcher.py                   # main-thread queue + bpy.app.timers drain
│   └── handlers/                       # per-category bpy code
│       ├── _common.py                  # ok/err helpers, deg<->rad, select_only
│       ├── perceive.py                 # get_scene_summary, get_object, render_image
│       ├── build.py                    # add_primitive, add_modifier
│       ├── place.py                    # transform_object, duplicate_object, delete_object
│       ├── surface.py                  # set_material
│       ├── light.py                    # add_light
│       ├── frame.py                    # add_camera
│       └── lifecycle.py                # ping, clear_scene
├── src/blender_mcp/                    # the MCP server
│   ├── server.py                       # FastMCP entry, @mcp.tool registrations, @mcp.prompt
│   ├── client.py                       # thread-safe TCP client w/ structured Failure mapping
│   ├── protocol.py                     # length-prefixed JSON framing
│   ├── models.py                       # all Pydantic input/output models, Failure, ErrorCode
│   └── tools/
│       ├── _common.py                  # parse_response helper
│       ├── perceive.py / build.py / place.py / surface.py / light.py / frame.py / lifecycle.py
├── tests/                              # 84 pytest cases, no Blender required
└── example_create_cube.py              # reference shipped with the assignment (untouched)
```
