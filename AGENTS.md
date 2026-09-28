# AGENTS.md

## Overview

This is an MCP server (92 tools) that connects AI coding agents to Autodesk Fusion 360 for CAD automation. It consists of two pieces:

1. **MCP Server** (this repo) — speaks MCP protocol over stdio, forwards commands to Fusion via TCP
2. **Fusion 360 Add-in** — runs inside Fusion, executes commands on the main thread via CustomEvent bridge

## How the system works

```
Claude Code ──stdio──> MCP Server ──TCP :9876──> Fusion Add-in ──CustomEvent──> Main Thread
                                   <──JSON──                    <──result──
```

The add-in uses a CustomEvent + work queue pattern to safely dispatch all Fusion API calls to the main thread. Socket threads submit work items and block on a per-item `threading.Event` until the main thread completes execution.

## Available tools (92)

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

## Response shape

Every tool call returns a dict-shaped result with these conventions — read them instead of guessing whether an operation worked:

**Success:**
```json
{
  "ok": true,
  "body_name": "Body1",   // tool-specific fields
  ...,
  "deltas": {             // present only for mutations
    "body_count_before": 0,
    "body_count_after":  1,
    "body_count_delta":  1,
    "mass_g_before": 0.0,
    "mass_g_after":  7.85,
    "mass_g_delta":  7.85,
    "bbox_before": null,
    "bbox_after":  {"min": [0,0,0], "max": [1,1,1]}
  }
}
```

**Failure (no exception — the error flows back as data):**
```json
{
  "ok": false,
  "error_kind":    "PROFILE_NOT_CLOSED",     // stable tag you can branch on
  "error_message": "No profiles in sketch",  // short human-readable
  "hints":  ["close the loop", "..."],        // contextual repair suggestions
  "traceback": "..."                         // full traceback for debugging
}
```

Known `error_kind` values: `PROFILE_NOT_CLOSED`, `SKETCH_NOT_FOUND`, `BODY_NOT_FOUND`, `SELF_INTERSECTION`, `REGEN_FAILED`, `BOOLEAN_NO_OP`, `INVALID_INPUT`, `NO_ACTIVE_DESIGN`, `DESIGN_TYPE_MISMATCH`, `TIMEOUT`, `UNKNOWN_COMMAND`, `UNKNOWN`.

**Use the deltas to sanity-check without a render.** A `boolean_operation` that reports `body_count_delta: 0, mass_g_delta: 0` did nothing — follow up with `check_interference` before retrying. An `extrude` that shifts mass by three orders of magnitude is probably using the wrong units.

**Use `render_view` sparingly** — it returns ~200KB–2MB of base64 image data. Render after a logical checkpoint (finished a feature, about to commit), not after every mutation. Deltas already tell you whether the feature *did* something; `render_view` tells you whether it did the *right* something.

## MCP protocol features

- **Tool annotations** — every tool is tagged `readOnlyHint`, `destructiveHint`, `idempotentHint` so clients can auto-approve safe operations
- **Resources** — `fusion360://status`, `fusion360://design`, `fusion360://parameters`
- **Resource templates** — `fusion360://body/{name}`, `fusion360://component/{name}`
- **Prompts** — `create-box`, `model-threaded-bolt`, `sheet-metal-enclosure` workflow templates
- **Structured errors** — `isError=True` when the add-in reports failures. Error results carry `error_kind`, `hints`, and a traceback so the agent can branch on failure mode rather than parsing prose (see _Response shape_ above).
- **Mock mode** — `--mode mock` returns test data without Fusion running

## Important constraints

- **One operation per tool call.** Never batch multiple operations — Fusion's API is not thread-safe and complex scripts crash the add-in.
- **No loops inside execute_code.** If you need to create 3 similar features, make 3 separate tool calls.
- **Keep execute_code under ~15 lines.** Prefer the dedicated tools over execute_code whenever possible.
- **Units are centimeters.** Fusion's internal API uses cm, not mm.
- **30-second timeout.** Commands that take longer than 30s will return a timeout error.
- **body_name preferred over body_index.** Use named lookups when possible.
- **Verify after each step.** Call `get_scene_info` or `get_object_info` to confirm success — don't assume from lack of error.
- **Name everything.** Name every body and sketch explicitly so they can be referenced reliably in later steps.

## Troubleshooting

- If commands fail with "Not connected", the Fusion add-in isn't running. The user needs to start it in Fusion (Shift+S > Add-Ins > Run).
- If commands time out, the Fusion main thread may be blocked (modal dialog, heavy computation).
- After any error, call `get_scene_info` to check if the operation partially applied before retrying.
- Logs are written to `~/fusion360mcp.log` by the add-in.
