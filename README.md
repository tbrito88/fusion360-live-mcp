# Fusion360 Live MCP

*Last updated: 2026-09-29*

> **Beta** — This project is under active development. APIs and tool behavior may change between releases. Use at your own discretion. Feedback and bug reports welcome via [GitHub Issues](https://github.com/tbrito88/fusion360-live-mcp/issues).

> **Origin** — This is a derivative of [faust-machines/fusion360-mcp-server](https://github.com/faust-machines/fusion360-mcp-server) (MIT-licensed), adapted for Autodesk Fusion 2704.1.53 with additional bug fixes found through live testing inside Fusion. See [CORRECOES.md](CORRECOES.md) for the full list of changes from upstream. The original copyright notice is preserved in [LICENSE](LICENSE) as required by its MIT license. Upstream's package, module and add-in names (`fusion360-mcp-server`, `fusion360_mcp`, `Fusion360MCP`) were renamed here so both projects can be installed side by side without clashing.

MCP server that connects AI coding agents to Autodesk Fusion 360 for CAD automation.

Live-tested with [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Works with any client that speaks the [Model Context Protocol](https://modelcontextprotocol.io) over stdio — Hermes Agent, OpenClaw, Codex, Gemini CLI, Cursor and others; see [Other agents and LLMs](#other-agents-and-llms).

> [!WARNING]
> **Check every G-code before it reaches a machine.** The agent can generate toolpaths and post-process them to G-code, but nothing here verifies them for collisions, feeds or fixturing. Simulate every toolpath in Fusion's Manufacture workspace and have a qualified person review the program before running it on any CNC. The CAM tools are marked so your MCP client asks for approval before running them; approving one is not a substitute for that review. This software comes with no warranty (see [LICENSE](LICENSE)).

## How it works

```
Any MCP Client ←(stdio MCP)→ This Server ←(TCP :9876)→ Fusion360LiveMCP Add-in ←(CustomEvent)→ Fusion Main Thread
```

Two components:

1. **MCP Server** (this repo) — Python process that speaks MCP protocol to Claude and forwards commands over TCP
2. **Fusion360LiveMCP Add-in** (installed in Fusion's AddIns folder) — runs inside Fusion 360, executes API calls safely on the main thread

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Autodesk Fusion 360
- An MCP-compatible client (Claude Code, OpenCode, Codex, Cursor, etc.)

## Security

- The add-in listens on `localhost:9876` with **no authentication**. Any program running under your user account can connect and send commands — including `execute_code`, which runs arbitrary Python inside Fusion with your permissions. Only run the add-in on machines where you trust the local software.
- Connections that don't speak the add-in's JSON protocol are dropped before any command is read. This blocks a web page from making your browser send commands to `localhost`.
- `execute_code`, `cam_generate_toolpath` and `cam_post_process` are annotated as destructive, so clients that honour MCP tool annotations ask before running them instead of auto-approving. Read the code or the CAM setup an agent wants to run before approving it.
- Binding to `0.0.0.0` (the LAN setup) extends the same trust to every machine on that network.
- Please report vulnerabilities privately through the repository's **Security → Report a vulnerability** page, not in a public issue.

## Installation

### 1. Install the Fusion 360 Add-in

**Quick install (symlink for development):**
```bash
./scripts/install-addon.sh
```

**Manual install:**
```bash
# macOS
cp -r addon ~/Library/Application\ Support/Autodesk/Autodesk\ Fusion\ 360/API/AddIns/Fusion360LiveMCP

# Windows (PowerShell)
Copy-Item -Recurse addon "$env:APPDATA\Autodesk\Autodesk Fusion 360\API\AddIns\Fusion360LiveMCP"
```

Then start it in Fusion: **Shift+S → Add-Ins → Fusion360LiveMCP → Run**

You should see `[MCP] Server listening on localhost:9876` in the TEXT COMMANDS window.

### 2. Connect your MCP client

This fork is **not** published on PyPI (upstream's `fusion360-mcp-server` package there does not include the fixes in [CORRECOES.md](CORRECOES.md)). Clone this repo and run it from source with `uv`:

```bash
git clone https://github.com/tbrito88/fusion360-live-mcp.git
cd fusion360-live-mcp
uv sync
```

#### Claude Code

```bash
claude mcp add fusion360-live -- uv run --directory /path/to/fusion360-live-mcp -m fusion360_live_mcp --mode socket
```

#### Other agents and LLMs

The server speaks standard MCP over **stdio**, so it works with any client that supports stdio servers and tool calling — which model runs behind the client doesn't matter. The launch command is always:

```
uv run --directory /path/to/fusion360-live-mcp -m fusion360_live_mcp --mode socket
```

To avoid needing `uv` at runtime, point the client at the virtual environment's Python instead: `/path/to/fusion360-live-mcp/.venv/Scripts/python.exe` on Windows (`.venv/bin/python` elsewhere) with args `-m fusion360_live_mcp --mode socket`.

Three settings matter in every client:

- **Timeouts.** Fusion operations can be slow, and on Windows the first call may start Fusion and wait up to 240 s for the add-in. Allow at least **300 s per tool call** and **60 s for startup**.
- **Environment.** Some clients (Hermes, Codex) don't pass your whole shell environment to the server. If you use `FUSION360_LIVE_MCP_HOST`, `_PORT` or `_AUTOLAUNCH`, declare them in the client's `env` block.
- **Tool count.** The 92 tool definitions take about 15k tokens. OpenAI-compatible APIs reject requests with more than 128 tools (the agent's own tools count too), and small local models get less accurate with long tool lists. When that matters, use the client's tool filter with this core set (~40 tools, ~6k tokens):

  ```
  ping, "get_*", list_components, create_sketch, "draw_*", create_polygon, extrude, revolve, fillet, chamfer, shell, create_hole, mirror, rectangular_pattern, circular_pattern, boolean_operation, move_body, rename_body, delete_body, create_box, create_cylinder, create_sphere, "measure_*", check_interference, "*_parameter", export, render_view, undo
  ```

Every tool description states its units (cm and degrees), and the server sends the same rules as MCP `instructions`, so models that never saw this README still get sizes right.

<details>
<summary><strong>Hermes Agent</strong> (<code>~/.hermes/config.yaml</code>; Windows installs: <code>%LOCALAPPDATA%\hermes\config.yaml</code>)</summary>

```yaml
mcp_servers:
  fusion360-live:
    command: "uv"
    args: ["run", "--directory", "/path/to/fusion360-live-mcp", "-m", "fusion360_live_mcp", "--mode", "socket"]
    timeout: 300
    connect_timeout: 60
    # tools:
    #   include: [ping, "get_*", extrude, ...]   # the core set above
```

Hermes registers the tools as `mcp_fusion360_live_<tool>`.
</details>

<details>
<summary><strong>OpenClaw</strong> (<code>openclaw.json</code>)</summary>

```json5
{
  mcp: {
    servers: {
      "fusion360-live": {
        transport: "stdio",
        command: "uv",
        args: ["run", "--directory", "/path/to/fusion360-live-mcp", "-m", "fusion360_live_mcp", "--mode", "socket"],
        connectionTimeoutMs: 60000,
        requestTimeoutMs: 300000,
        // toolFilter: { include: ["ping", "get_*", "extrude"] },  // the core set above
      },
    },
  },
}
```
</details>

<details>
<summary><strong>OpenAI Codex</strong> (<code>~/.codex/config.toml</code>)</summary>

```toml
[mcp_servers.fusion360-live]
command = "uv"
args = ["run", "--directory", "/path/to/fusion360-live-mcp", "-m", "fusion360_live_mcp", "--mode", "socket"]
startup_timeout_sec = 60   # default 10 is too short for the first uv run
tool_timeout_sec = 300     # default 60 is too short for auto-launch
# enabled_tools = ["ping", "get_scene_info", "extrude"]
```
</details>

<details>
<summary><strong>Gemini CLI</strong> (<code>~/.gemini/settings.json</code>)</summary>

```json
{
  "mcpServers": {
    "fusion360-live": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/fusion360-live-mcp", "-m", "fusion360_live_mcp", "--mode", "socket"],
      "timeout": 600000
    }
  }
}
```

Add `"includeTools": [...]` to limit the tool list.
</details>

<details>
<summary><strong>Cursor</strong> (<code>~/.cursor/mcp.json</code>) and other <code>mcpServers</code>-style clients</summary>

```json
{
  "mcpServers": {
    "fusion360-live": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/fusion360-live-mcp", "-m", "fusion360_live_mcp", "--mode", "socket"]
    }
  }
}
```
</details>

**What has been verified:** the MCP protocol with a generic client (the official Python SDK) running under the same filtered environment Hermes uses, and every tool schema against OpenAI's and Gemini's rules (`tests/test_client_compat.py`). Live modelling inside Fusion has so far been done with Claude only.

### Cross-machine setup (LAN)

If the MCP server and Fusion 360 run on different machines (e.g. MCP server on a Mac Mini, Fusion on a Windows PC), override the bind/connect address via environment variables on **both** sides.

**On the Fusion host** (where the add-in runs), bind to all interfaces before starting Fusion:

```powershell
# Windows
$env:FUSION360_LIVE_MCP_HOST = "0.0.0.0"
```

```bash
# macOS / Linux
export FUSION360_LIVE_MCP_HOST=0.0.0.0
```

Then start Fusion and run the `Fusion360LiveMCP` add-in. The log line `Server listening on 0.0.0.0:9876` confirms the bind.

**On the MCP-server host**, point the client at the Fusion host's LAN IP:

```bash
# Either via CLI flag
uv run --directory /path/to/fusion360-live-mcp -m fusion360_live_mcp --mode socket --host 192.168.1.42

# Or via env var (useful in MCP client configs)
FUSION360_LIVE_MCP_HOST=192.168.1.42 uv run --directory /path/to/fusion360-live-mcp -m fusion360_live_mcp --mode socket
```

**Security note:** the TCP socket has no authentication. Only expose it on a trusted LAN — never bind to `0.0.0.0` on a host reachable from the public internet. See [Security](#security).

### 3. Verify

Call the `ping` tool from your client. If it returns `{"ok": true, "status": "pong"}`, everything is connected.

### Uninstalling

1. Remove the `fusion360-live` entry from your MCP client config
2. Stop the add-in in Fusion (Shift+S → Add-Ins → Fusion360LiveMCP → Stop)
3. Delete the add-in folder from Fusion's AddIns directory

## Available Tools (92)

> Tools marked **(2026+)** require a recent Fusion build — they use APIs introduced in the January–July 2026 releases.

### Scene & Query
| Tool | Description |
|------|-------------|
| `ping` | Health check (instant, no Fusion API) |
| `get_scene_info` | Design name, bodies, sketches, features, camera |
| `get_object_info` | Detailed info about a named body or sketch |
| `get_bounding_box` | Axis-aligned bbox (min/max/size/center) for body or component; unions all bodies when called on a component |
| `list_components` | List all components in the design |

### Design Type Safety
| Tool | Description |
|------|-------------|
| `get_design_type` | Check if design is in parametric or direct mode |
| `set_design_type` | Switch design type (parametric/direct recovery) |

### Sketching
| Tool | Description |
|------|-------------|
| `create_sketch` | New sketch on xy/yz/xz plane, optional offset |
| `draw_rectangle` | Rectangle in most recent sketch |
| `draw_circle` | Circle in most recent sketch |
| `draw_line` | Line in most recent sketch |
| `draw_arc` | Arc (center + start + sweep angle) |
| `draw_spline` | Fit-point or control-point spline |
| `create_polygon` | Regular polygon (3–64 sides) |
| `add_constraint` | Geometric constraint (coincident, parallel, tangent, etc.) |
| `auto_constrain` | **(2026+)** Auto-constrain a sketch via the AutoConstrain API — 3 result options (thorough / fast / tolerance-adjusting) |
| `add_dimension` | Driving dimension (distance, angle, radial, diameter) |
| `offset_curve` | Offset connected sketch curves |
| `trim_curve` | Trim at intersections |
| `extend_curve` | Extend to nearest intersection |
| `project_geometry` | Project edges/bodies onto sketch plane |

### Features
| Tool | Description |
|------|-------------|
| `extrude` | Extrude a sketch profile |
| `revolve` | Revolve a profile around an axis |
| `sweep` | Sweep a profile along a path |
| `loft` | Loft between two or more profiles |
| `fillet` | Round edges (all/top/bottom/vertical) |
| `chamfer` | Chamfer edges |
| `shell` | Hollow out a body |
| `mirror` | Mirror a body across a plane |
| `create_hole` | Hole feature on a body face |
| `rectangular_pattern` | Pattern in rows and columns |
| `circular_pattern` | Pattern around an axis |
| `create_thread` | Add threads (cosmetic or modeled) |
| `draft_faces` | Draft/taper faces for mold release |
| `split_body` | Split a body using a plane |
| `split_face` | Split faces of a body |
| `offset_faces` | Push/pull faces by a distance |
| `scale_body` | Scale uniformly or non-uniformly |
| `suppress_feature` | Suppress a timeline feature |
| `unsuppress_feature` | Re-enable a suppressed feature |

### Body Operations
| Tool | Description |
|------|-------------|
| `move_body` | Translate a body by (x, y, z) |
| `rename_body` | Rename a body (searches root and all components) |
| `boolean_operation` | Join/cut/intersect two bodies |
| `delete_body` | Delete one named body (searches root and all components) — use instead of `undo` to remove a body |
| `delete_all` | Clear the design |
| `undo` | Undo last operation (with design-type safety guard) |

### Direct Primitives
| Tool | Description |
|------|-------------|
| `create_box` | Box (via TemporaryBRepManager, history-less) |
| `create_box_parametric` | History-based box: sketch rectangle + dimensions + extrude. `length`/`width`/`height` accept numbers (cm) or string expressions referencing User Parameters (e.g. `"boxL"`, `"outer - 2*wall_t"`) |
| `create_cylinder` | Cylinder |
| `create_sphere` | Sphere |
| `create_torus` | Torus |

### Surface Operations
| Tool | Description |
|------|-------------|
| `patch_surface` | Create a patch surface from boundary edges |
| `stitch_surfaces` | Stitch surface bodies into a single body |
| `thicken_surface` | Thicken a surface body into a solid |

### Sheet Metal
| Tool | Description |
|------|-------------|
| `convert_to_sheet_metal` | Convert a solid body of uniform thickness into sheet metal (thickness taken from the geometry) |
| `fold_sheet_metal` | Bend a sheet metal body along a line of the last sketch (draw the line with `draw_line` first) |
| `flat_pattern` | Create the flat pattern of a sheet metal body (run `convert_to_sheet_metal` first) |
| `export_flat_pattern_dxf` | Export the flat pattern as DXF for laser/plasma/waterjet cutting (run `flat_pattern` first) |

### Construction Geometry
| Tool | Description |
|------|-------------|
| `create_construction_plane` | Offset, angle, midplane, 3-point, tangent |
| `create_construction_axis` | Two-point, intersection, edge, perpendicular |
| `create_ucs` | **(2026+, preview API)** User Coordinate System at a point with optional rotation |

### Assembly
| Tool | Description |
|------|-------------|
| `create_component` | Create a sub-assembly component |
| `add_joint` | Joint between two components |
| `create_as_built_joint` | Joint from current positions |
| `create_rigid_group` | Lock components together |

### Inspection & Analysis
| Tool | Description |
|------|-------------|
| `measure_distance` | Minimum distance between entities |
| `measure_angle` | Angle between entities |
| `get_physical_properties` | Mass, volume, area, center of mass |
| `create_section_analysis` | Section plane through model |
| `check_interference` | Detect collisions between components |
| `compare_meshes` | **(2026+)** Deviation statistics between two mesh bodies (min/max/mean/RMS, cm) — e.g. validate against a reference STL |

### Appearance
| Tool | Description |
|------|-------------|
| `set_appearance` | Assign material appearance from library |
| `set_color` | **(2026+)** Assign a flat RGB color (+ opacity) to a body |

### Parameters
| Tool | Description |
|------|-------------|
| `get_parameters` | List all user parameters |
| `create_parameter` | Create a new parameter |
| `set_parameter` | Update a parameter value |
| `delete_parameter` | Remove a parameter |

### Import / Export
| Tool | Description |
|------|-------------|
| `import_mesh` | Import STL/OBJ/3MF as mesh body via `MeshBodies.add()`. Unit-aware (`mm`/`cm`/`m`/`in`/`ft`). Returns the mesh name and bounding box |
| `export_stl` | Export body as STL (supports bodies inside components) |
| `export_step` | Export body as STEP (supports bodies inside components) |
| `export_f3d` | Export design as Fusion archive |
| `export_view_sheet` | Export multi-view PNG sheet (iso/front/top/right) for visual inspection |
| `export` | Unified dispatcher — routes to `export_stl`/`export_step`/`export_f3d` based on explicit `format` or file-extension inference |

### CAM / Manufacturing
| Tool | Description |
|------|-------------|
| `cam_create_setup` | Create a manufacturing setup (milling/turning/cutting); applies stock mode/offsets |
| `cam_create_operation` | Add a machining operation (face, contour, adaptive, drilling, etc.); applies stepdown/feed/speed/coolant parameters |
| `cam_generate_toolpath` | Generate toolpaths for operations |
| `cam_post_process` | Post-process to G-code — pass a full `.cps` path (cloud-post builds don't ship local posts) |
| `cam_list_setups` | List all manufacturing setups |
| `cam_list_operations` | List operations in a setup |
| `cam_get_operation_info` | Get operation details (strategy, tool, parameters) |

### Code Execution
| Tool | Description |
|------|-------------|
| `execute_code` | Run arbitrary Python in Fusion (REPL-style) |

### Perception
| Tool | Description |
|------|-------------|
| `render_view` | Capture the active viewport as PNG (optional camera preset: iso/front/top/...). Returns an image block for visual verification |

## MCP Protocol Features

- **Tool annotations** — each tool is tagged with `readOnlyHint`, `destructiveHint`, and `idempotentHint` so MCP clients can auto-approve safe operations
- **Resources** — `fusion360://status`, `fusion360://design`, `fusion360://parameters` for passive state inspection
- **Resource templates** — `fusion360://body/{name}`, `fusion360://component/{name}` for dynamic entity lookup
- **Prompts** — `create-box`, `model-threaded-bolt`, `sheet-metal-enclosure` workflow templates
- **Structured errors** — failures carry `isError=True` plus a stable `error_kind` (e.g. `BODY_NOT_FOUND`, `TIMEOUT`), contextual `hints`, and a traceback; infrastructure errors (bridge timeout, unknown command) are classified the same way, not flattened to a generic message
- **Mock mode** — `--mode mock` returns plausible test data without Fusion running (all responses include `"mode": "mock"`)

## Development

```bash
uv sync --dev       # install deps
uv run pytest -v    # run tests (497 tests)
uv run ruff check   # lint
```

## Notes

- All Fusion API units are **centimeters** (Fusion's internal unit).
- One operation per tool call. Batching multiple operations crashes the add-in.
- Timeouts: the add-in's main-thread bridge times out after 30s and *cancels* the queued command; the client waits up to 45s so it receives that structured `TIMEOUT` error. **Mutation commands are never auto-retried** — after a timeout, call `get_scene_info` to check whether anything was applied before retrying.
- Add-in logs to `~/fusion360livemcp.log`.
- **Auto-launch (Windows):** when the add-in is unreachable on `localhost` and Fusion is not running, the server starts Fusion and marks this add-in as *run on startup* in Fusion's add-in list (`JSLoadedScriptsinfo`). If Fusion is already running it does nothing, so no unsaved work is lost. Set `FUSION360_LIVE_MCP_AUTOLAUNCH=0` to disable.
- The `undo` tool includes a design-type safety guard — it checks before/after and auto-redoes if the undo would switch from parametric to direct mode.
- This fork is tested on Fusion 2704.1.53 (Windows x86_64) — see [CORRECOES.md](CORRECOES.md) for the full validation log. Tools marked **(2026+)** need a build from 2026 or later.

## Acknowledgements

Inspired by [BlenderMCP](https://github.com/ahujasid/blender-mcp) — the socket bridge architecture originated there.

Also built on ideas from the existing Fusion 360 MCP ecosystem:
- [ArchimedesCrypto/fusion360-mcp-server](https://github.com/ArchimedesCrypto/fusion360-mcp-server)
- [Joe-Spencer/fusion-mcp-server](https://github.com/Joe-Spencer/fusion-mcp-server)
- [JustusBraitinger/FusionMCP](https://github.com/JustusBraitinger/FusionMCP)
- [zkbkb/fusion-mcp](https://github.com/zkbkb/fusion-mcp)
- [mycelia1/fusion360-mcp-server](https://github.com/mycelia1/fusion360-mcp-server)
- [sockcymbal/autodesk-fusion-mcp-python](https://github.com/sockcymbal/autodesk-fusion-mcp-python)

## License

MIT — see [LICENSE](LICENSE).

Autodesk and Fusion are registered trademarks of Autodesk, Inc. This project is not affiliated with, endorsed by, or supported by Autodesk.
