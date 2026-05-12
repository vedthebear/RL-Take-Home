"""Blender MCP Server — the FastMCP half of a two-process bridge.

System map
==========

    ┌────────────┐   stdio   ┌──────────────────────────┐
    │  LLM /     │──────────▶│  FastMCP server          │
    │  MCP host  │           │  (this package)          │
    └────────────┘           │                          │
                             │  src/blender_mcp/        │
                             │   ├── server.py          │  registers @mcp.tool fns
                             │   ├── tools/*.py         │  thin per-tool wrappers
                             │   ├── client.py          │  one TCP socket, shared
                             │   ├── protocol.py        │  length-prefixed JSON
                             │   └── models.py          │  Pydantic input/output
                             └────────────┬─────────────┘
                                          │  TCP :9876 (length-prefixed JSON)
                                          ▼
                             ┌──────────────────────────┐
                             │  Blender (separate proc) │
                             │  blender_addon/          │
                             │   ├── server.py          │  socket worker threads
                             │   ├── dispatcher.py      │  main-thread queue+timer
                             │   └── handlers/*.py      │  the only place bpy runs
                             └──────────────────────────┘

How the halves stay in sync
---------------------------

- ``models.py`` is the single source of truth for the wire schema. The addon
  side emits matching dicts (no Pydantic dependency inside Blender).
- ``protocol.py`` and ``blender_addon/_protocol.py`` are mirror copies of the
  same length-prefixed JSON framing — duplicated so the addon zip stays
  self-contained when installed in Blender.
- Every tool in ``tools/*.py`` is a thin shim: validate Pydantic input → call
  ``client.call(...)`` → re-parse the addon's reply into a Pydantic union.
  The actual bpy work lives in ``blender_addon/handlers/*.py``.
"""

__version__ = "0.1.0"
