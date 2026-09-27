"""
MCP tool definitions for every command the Fusion360MCP add-in supports.

Each entry becomes a tool that Claude can call.  The ``inputSchema`` is
JSON Schema that the MCP SDK validates before forwarding arguments.
"""

import mcp.types as types

# fillet/chamfer: X/Y window that isolates edges by position (e.g. only the
# outer vertical corners of a body full of internal vertical edges).
_EDGE_XY_WINDOW = {
    f"{axis}_{end}": {
        "type": "number",
        "description": (
            f"Keep only edges lying entirely at {axis.upper()} "
            f"{'>=' if end == 'min' else '<='} {axis}_{end} (cm)."
        ),
    }
    for axis in ("x", "y")
    for end in ("min", "max")
}

_EDGE_CONVEXITY = {
    "convexity": {
        "type": "string",
        "enum": ["any", "concave", "convex"],
        "default": "any",
        "description": (
            "Keep only inside-corner (concave) or outside-corner (convex) "
            "edges. Mixing both at shared vertices makes Fusion fail with "
            "ASM_BL_CANNOT_REORDER; split them into two calls."
        ),
    }
}

TOOLS: list[dict] = [
    # ── scene / query ────────────────────────────────────────────────
    {
        "name": "get_scene_info",
        "title": "Get Scene Info",
        "description": "Get design name, bodies, sketches, features, camera info",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_object_info",
        "title": "Get Object Info",
        "description": "Get detailed info about a named body or sketch",
        "inputSchema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Object name"},
            },
        },
    },
    {
        "name": "get_bounding_box",
        "title": "Get Bounding Box",
        "description": (
            "Axis-aligned bounding box for a body or component by name. "
            "Returns min, max, size, and center in cm (Fusion internal units). "
            "For components, unions bounding boxes of all contained bodies. "
            "Useful for measuring imported reference geometry."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Body or component name",
                },
            },
        },
    },
    # ── sketch ───────────────────────────────────────────────────────
    {
        "name": "create_sketch",
        "title": "Create Sketch",
        "description": "Create a new sketch on xy/yz/xz plane, optionally offset",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plane": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                    "default": "xy",
                },
                "z_offset": {
                    "type": "number",
                    "description": "Offset distance from the plane (cm)",
                },
            },
        },
    },
    {
        "name": "draw_rectangle",
        "title": "Draw Rectangle",
        "description": "Draw a rectangle in the most recent sketch",
        "inputSchema": {
            "type": "object",
            "required": ["width", "height"],
            "properties": {
                "width": {"type": "number", "minimum": 0.001},
                "height": {"type": "number", "minimum": 0.001},
                "origin_x": {"type": "number", "default": 0},
                "origin_y": {"type": "number", "default": 0},
                "origin_z": {"type": "number", "default": 0},
            },
        },
    },
    {
        "name": "draw_circle",
        "title": "Draw Circle",
        "description": "Draw a circle in the most recent sketch",
        "inputSchema": {
            "type": "object",
            "required": ["radius"],
            "properties": {
                "radius": {"type": "number", "minimum": 0.001},
                "center_x": {"type": "number", "default": 0},
                "center_y": {"type": "number", "default": 0},
                "center_z": {"type": "number", "default": 0},
            },
        },
    },
    {
        "name": "draw_line",
        "title": "Draw Line",
        "description": "Draw a line in the most recent sketch",
        "inputSchema": {
            "type": "object",
            "required": ["start_x", "start_y", "end_x", "end_y"],
            "properties": {
                "start_x": {"type": "number"},
                "start_y": {"type": "number"},
                "start_z": {"type": "number", "default": 0},
                "end_x": {"type": "number"},
                "end_y": {"type": "number"},
                "end_z": {"type": "number", "default": 0},
            },
        },
    },
    # ── features ─────────────────────────────────────────────────────
    {
        "name": "extrude",
        "title": "Extrude",
        "description": (
            "Extrude a sketch profile. For operation cut/intersect, pass "
            "target_body_name whenever the document has more than one body "
            "— confirmed live that leaving it unset cuts EVERY body the "
            "tool geometrically reaches, not just an intended target."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["height"],
            "properties": {
                "height": {"type": "number"},
                "profile_index": {"type": "integer", "default": 0, "minimum": 0},
                "operation": {
                    "type": "string",
                    "enum": ["new_body", "join", "cut", "intersect"],
                    "default": "new_body",
                },
                "direction": {
                    "type": "string",
                    "enum": ["positive", "negative", "symmetric"],
                    "default": "positive",
                },
                "target_body_name": {
                    "type": "string",
                    "description": (
                        "For operation cut/intersect: restrict the cut to "
                        "this body only. Without it, EVERY body within "
                        "geometric reach of the tool gets cut, including "
                        "unrelated ones elsewhere in the document — "
                        "confirmed live, not a theoretical risk."
                    ),
                },
            },
        },
    },
    {
        "name": "revolve",
        "title": "Revolve",
        "description": (
            "Revolve a sketch profile around an axis. For operation "
            "cut/intersect, pass target_body_name whenever the document has "
            "more than one body — confirmed live that leaving it unset cuts "
            "EVERY body within the revolve's sweep, not just an intended "
            "target (it sliced two unrelated bodies elsewhere in the "
            "document purely because they sat within the sweep radius)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["angle"],
            "properties": {
                "angle": {"type": "number", "minimum": 0.1, "maximum": 360},
                "profile_index": {"type": "integer", "default": 0},
                "axis_origin_x": {"type": "number", "default": 0},
                "axis_origin_y": {"type": "number", "default": 0},
                "axis_origin_z": {"type": "number", "default": 0},
                "axis_direction_x": {"type": "number", "default": 1},
                "axis_direction_y": {"type": "number", "default": 0},
                "axis_direction_z": {"type": "number", "default": 0},
                "operation": {
                    "type": "string",
                    "enum": ["new_body", "join", "cut", "intersect"],
                    "default": "new_body",
                },
                "target_body_name": {
                    "type": "string",
                    "description": (
                        "For operation cut/intersect: restrict the cut to "
                        "this body only. Without it, EVERY body within the "
                        "revolve's sweep radius around the axis gets cut, "
                        "including unrelated ones — confirmed live, not a "
                        "theoretical risk."
                    ),
                },
            },
        },
    },
    {
        "name": "fillet",
        "title": "Fillet Edges",
        "description": "Round edges of a body",
        "inputSchema": {
            "type": "object",
            "required": ["radius"],
            "properties": {
                "radius": {"type": "number", "minimum": 0.001},
                "body_name": {"type": "string", "description": "Body name (preferred)"},
                "body_index": {"type": "integer", "default": 0},
                "edge_selection": {
                    "type": "string",
                    "enum": ["all", "top", "bottom", "vertical"],
                    "default": "all",
                },
                "z_min": {
                    "type": "number",
                    "description": (
                        "Keep only edges lying entirely at Z >= z_min (cm). "
                        "Combine with z_max and edge_selection='all' to pick "
                        "an edge ring at an intermediate height — 'top'/"
                        "'bottom' only reach the body's extreme Z."
                    ),
                },
                "z_max": {
                    "type": "number",
                    "description": "Keep only edges lying entirely at Z <= z_max (cm).",
                },
                **_EDGE_XY_WINDOW,
                **_EDGE_CONVEXITY,
            },
        },
    },
    {
        "name": "chamfer",
        "title": "Chamfer Edges",
        "description": "Chamfer edges of a body",
        "inputSchema": {
            "type": "object",
            "required": ["distance"],
            "properties": {
                "distance": {"type": "number", "minimum": 0.001},
                "body_name": {"type": "string"},
                "body_index": {"type": "integer", "default": 0},
                "edge_selection": {
                    "type": "string",
                    "enum": ["all", "top", "bottom", "vertical"],
                    "default": "all",
                },
                "z_min": {
                    "type": "number",
                    "description": (
                        "Keep only edges lying entirely at Z >= z_min (cm). "
                        "Combine with z_max to pick an edge ring at an "
                        "intermediate height."
                    ),
                },
                "z_max": {
                    "type": "number",
                    "description": "Keep only edges lying entirely at Z <= z_max (cm).",
                },
                **_EDGE_XY_WINDOW,
                **_EDGE_CONVEXITY,
            },
        },
    },
    {
        "name": "shell",
        "title": "Shell Body",
        "description": (
            "Hollow out a body, removing the selected planar face(s) as the "
            "opening. top/bottom = the +Z/-Z facing face(s) at the body's "
            "extreme Z; up_facing/down_facing = every +Z/-Z facing planar "
            "face (e.g. a stepped rim), optionally limited by z_min/z_max. "
            "Returns faces_removed and removed_face_z."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["thickness"],
            "properties": {
                "thickness": {"type": "number", "minimum": 0.001},
                "body_name": {"type": "string"},
                "body_index": {"type": "integer", "default": 0},
                "face_selection": {
                    "type": "string",
                    "enum": ["top", "bottom", "up_facing", "down_facing"],
                    "default": "top",
                },
                "z_min": {"type": "number"},
                "z_max": {"type": "number"},
            },
        },
    },
    {
        "name": "mirror",
        "title": "Mirror Body",
        "description": "Mirror a body across a construction plane",
        "inputSchema": {
            "type": "object",
            "required": ["mirror_plane"],
            "properties": {
                "mirror_plane": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                },
                "body_name": {"type": "string"},
                "body_index": {"type": "integer", "default": 0},
            },
        },
    },
    # ── new commands ─────────────────────────────────────────────────
    {
        "name": "delete_body",
        "title": "Delete Body",
        "description": (
            "Delete one named body (searches root and all components). Use "
            "this instead of undo to remove a body: API-created features are "
            "not reliably on Fusion's UI undo stack."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string", "description": "Body to delete"},
            },
        },
    },
    {
        "name": "rename_body",
        "title": "Rename Body",
        "description": "Rename a body (searches root and all components)",
        "inputSchema": {
            "type": "object",
            "required": ["body_name", "new_name"],
            "properties": {
                "body_name": {
                    "type": "string",
                    "description": "Current body name",
                },
                "new_name": {
                    "type": "string",
                    "description": "New name for the body",
                },
            },
        },
    },
    {
        "name": "move_body",
        "title": "Move Body",
        "description": (
            "Move a named body: optional rotation (angle, degrees) about an "
            "axis parallel to x/y/z through (pivot_x, pivot_y, pivot_z), "
            "then translation by (x, y, z)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "x": {"type": "number", "default": 0},
                "y": {"type": "number", "default": 0},
                "z": {"type": "number", "default": 0},
                "angle": {
                    "type": "number",
                    "default": 0,
                    "description": "Rotation in degrees (right-hand rule about +axis)",
                },
                "axis": {"type": "string", "enum": ["x", "y", "z"], "default": "z"},
                "pivot_x": {"type": "number", "default": 0},
                "pivot_y": {"type": "number", "default": 0},
                "pivot_z": {"type": "number", "default": 0},
            },
        },
    },
    {
        "name": "export_stl",
        "title": "Export STL",
        "description": "Export a named body as an STL file",
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "file_path": {
                    "type": "string",
                    "description": "Destination path (default: ~/Desktop/<name>.stl)",
                },
            },
        },
    },
    {
        "name": "boolean_operation",
        "title": "Boolean Operation",
        "description": (
            "Combine two named bodies (join/cut/intersect). For 'join', "
            "target_body and tool_body must actually touch or overlap — "
            "confirmed live that Fusion silently discards the tool body's "
            "geometry (no error, no merge) when they don't, so this refuses "
            "up front with the real minimum distance between them instead "
            "of reporting a false success."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["target_body", "tool_body"],
            "properties": {
                "target_body": {"type": "string"},
                "tool_body": {"type": "string"},
                "operation": {
                    "type": "string",
                    "enum": ["join", "cut", "intersect"],
                    "default": "join",
                },
            },
        },
    },
    {
        "name": "delete_all",
        "title": "Delete All",
        "description": "Clear the design (delete all timeline items)",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "undo",
        "title": "Undo",
        "description": "Undo the last operation",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    # ── code execution ───────────────────────────────────────────────
    {
        "name": "execute_code",
        "title": "Execute Code",
        "description": (
            "Run arbitrary Python in Fusion 360. "
            "The last expression's value is returned (REPL-style). "
            "Pre-defined names: app, ui, design, component, adsk, math, "
            "late_results. The add-in waits 30 s by default; pass timeout_s "
            "(max 600) for a script that runs many features on a large "
            "timeline. A command that times out while running still "
            "finishes; its result is kept and late_results() returns it."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["code"],
            "properties": {
                "code": {"type": "string"},
                "timeout_s": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 600,
                    "description": "Seconds to wait for the script (default 30).",
                },
            },
        },
    },
    # ── additional geometry ───────────────────────────────────────────
    {
        "name": "sweep",
        "title": "Sweep",
        "description": "Sweep a sketch profile along a path (sketch curve)",
        "inputSchema": {
            "type": "object",
            "required": ["profile_index", "path_sketch_name"],
            "properties": {
                "target_body_name": {
                    "type": "string",
                    "description": (
                        "For operation cut/intersect: restrict it to this "
                        "body. Without it EVERY body the tool reaches is cut."
                    ),
                },
                "profile_index": {"type": "integer", "default": 0, "minimum": 0},
                "path_sketch_name": {
                    "type": "string",
                    "description": "Name of the sketch containing the sweep path",
                },
                "path_curve_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Omit to sweep along every non-construction curve of "
                        "the path sketch (curves drawn by separate calls are "
                        "joined by position). Give an index to chain only from "
                        "that curve. The result reports path_curves/path_length."
                    ),
                },
                "operation": {
                    "type": "string",
                    "enum": ["new_body", "join", "cut", "intersect"],
                    "default": "new_body",
                },
            },
        },
    },
    {
        "name": "loft",
        "title": "Loft",
        "description": "Loft between two or more sketch profiles",
        "inputSchema": {
            "type": "object",
            "required": ["profile_sketch_names"],
            "properties": {
                "target_body_name": {
                    "type": "string",
                    "description": (
                        "For operation cut/intersect: restrict it to this "
                        "body. Without it EVERY body the tool reaches is cut."
                    ),
                },
                "profile_sketch_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "description": (
                        "Ordered list of sketch names whose "
                        "first profile will be lofted"
                    ),
                },
                "operation": {
                    "type": "string",
                    "enum": ["new_body", "join", "cut", "intersect"],
                    "default": "new_body",
                },
            },
        },
    },
    {
        "name": "create_polygon",
        "title": "Create Polygon",
        "description": "Draw a regular polygon in the most recent sketch",
        "inputSchema": {
            "type": "object",
            "required": ["sides", "radius"],
            "properties": {
                "sides": {"type": "integer", "minimum": 3, "maximum": 64},
                "radius": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Circumradius (cm)",
                },
                "center_x": {"type": "number", "default": 0},
                "center_y": {"type": "number", "default": 0},
                "center_z": {"type": "number", "default": 0},
            },
        },
    },
    {
        "name": "draw_arc",
        "title": "Draw Arc",
        "description": (
            "Draw an arc in the most recent sketch (center + start point + sweep angle)"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["center_x", "center_y", "start_x", "start_y", "sweep_angle"],
            "properties": {
                "center_x": {"type": "number"},
                "center_y": {"type": "number"},
                "center_z": {"type": "number", "default": 0},
                "start_x": {"type": "number"},
                "start_y": {"type": "number"},
                "start_z": {"type": "number", "default": 0},
                "sweep_angle": {
                    "type": "number",
                    "description": "Sweep angle in degrees (positive = CCW)",
                    "minimum": -360,
                    "maximum": 360,
                },
            },
        },
    },
    {
        "name": "create_hole",
        "title": "Create Hole",
        "description": "Create a hole feature on a body face",
        "inputSchema": {
            "type": "object",
            "required": ["diameter", "depth"],
            "properties": {
                "diameter": {"type": "number", "minimum": 0.001},
                "depth": {"type": "number", "minimum": 0.001},
                "body_name": {"type": "string"},
                "body_index": {"type": "integer", "default": 0},
                "face_selection": {
                    "type": "string",
                    "enum": ["top", "bottom"],
                    "default": "top",
                    "description": (
                        "Drill into the highest up-facing (top) or lowest "
                        "down-facing (bottom) planar face, which must be "
                        "near-horizontal (within ~0.6 deg)"
                    ),
                },
                "center_x": {
                    "type": "number",
                    "default": 0,
                    "description": "Hole centre X in model space (cm)",
                },
                "center_y": {
                    "type": "number",
                    "default": 0,
                    "description": "Hole centre Y in model space (cm)",
                },
            },
        },
    },
    {
        "name": "rectangular_pattern",
        "title": "Rectangular Pattern",
        "description": "Pattern a body in rows and columns",
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "x_count": {"type": "integer", "minimum": 1, "default": 1},
                "x_spacing": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Spacing between columns (cm)",
                },
                "y_count": {"type": "integer", "minimum": 1, "default": 1},
                "y_spacing": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Spacing between rows (cm)",
                },
            },
        },
    },
    {
        "name": "circular_pattern",
        "title": "Circular Pattern",
        "description": (
            "Pattern a body OR a feature around an axis. Without "
            "feature_name, this duplicates the whole body N times as "
            "separate overlapping bodies (correct for copying a whole "
            "part, e.g. around a turntable) — it does NOT add copies of a "
            "feature to the same body. For the common case — a bolt circle, "
            "repeating a single hole around one part — pass feature_name "
            "(the feature that created it, e.g. from create_hole's "
            "feature_name) so the result stays one body with N holes."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["body_name", "count"],
            "properties": {
                "body_name": {
                    "type": "string",
                    "description": (
                        "Body to pattern. Still required even when "
                        "feature_name is given, to resolve the axis; ignored "
                        "as the pattern target in that case."
                    ),
                },
                "count": {"type": "integer", "minimum": 2},
                "axis": {
                    "type": "string",
                    "enum": ["x", "y", "z"],
                    "default": "z",
                },
                "total_angle": {
                    "type": "number",
                    "default": 360,
                    "minimum": 1,
                    "maximum": 360,
                    "description": "Total angle to distribute copies over (degrees)",
                },
                "feature_name": {
                    "type": "string",
                    "description": (
                        "Name of an existing feature (e.g. a hole feature) "
                        "to pattern instead of the whole body. This is what "
                        "keeps the result as ONE body with N copies of the "
                        "feature — a real bolt circle — instead of N "
                        "separate overlapping bodies."
                    ),
                },
            },
        },
    },
    # ── assembly ───────────────────────────────────────────────────────
    {
        "name": "create_component",
        "title": "Create Component",
        "description": "Create a new component (sub-assembly) in the design",
        "inputSchema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Component name"},
                "parent_name": {
                    "type": "string",
                    "description": "Parent component name (omit for root)",
                },
            },
        },
    },
    {
        "name": "add_joint",
        "title": "Add Joint",
        "description": "Add a joint between two components",
        "inputSchema": {
            "type": "object",
            "required": ["component_one", "component_two"],
            "properties": {
                "component_one": {"type": "string"},
                "component_two": {"type": "string"},
                "joint_type": {
                    "type": "string",
                    "enum": [
                        "rigid",
                        "revolute",
                        "slider",
                        "cylindrical",
                        "pin_slot",
                        "planar",
                        "ball",
                    ],
                    "default": "rigid",
                },
            },
        },
    },
    {
        "name": "list_components",
        "title": "List Components",
        "description": "List all components in the design",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    # ── export ─────────────────────────────────────────────────────────
    {
        "name": "export_step",
        "title": "Export STEP",
        "description": "Export a body or component as a STEP file",
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "file_path": {
                    "type": "string",
                    "description": "Destination path (default: ~/Desktop/<name>.step)",
                },
            },
        },
    },
    {
        "name": "export_f3d",
        "title": "Export F3D",
        "description": "Export the design as a native Fusion 360 archive (.f3d)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Destination path (default: ~/Desktop/<design_name>.f3d)"
                    ),
                },
            },
        },
    },
    {
        "name": "export_view_sheet",
        "title": "Export View Sheet",
        "description": (
            "Render canonical orthographic + isometric views as PNGs and "
            "emit a self-contained HTML sheet suitable for sharing with a "
            "mechanical engineer. Opens in any browser; Print -> Save as "
            "PDF for a static artifact. Restores the viewport camera "
            "after rendering."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "Heading shown on the sheet (default: document name)."
                    ),
                },
                "notes": {
                    "type": "string",
                    "description": (
                        "Free-form notes rendered below the views. "
                        "Newlines preserved; HTML is escaped."
                    ),
                },
                "views": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "iso",
                            "iso_ne",
                            "iso_nw",
                            "iso_sw",
                            "front",
                            "back",
                            "top",
                            "bottom",
                            "right",
                            "left",
                        ],
                    },
                    "description": (
                        "Ordered list of views to render "
                        "(default: iso, front, top, right)."
                    ),
                },
                "image_size": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": ("[width, height] in pixels (default [1200, 900])."),
                },
                "output_dir": {
                    "type": "string",
                    "description": (
                        "Destination folder "
                        "(default: ~/Desktop/<doc>_views_<timestamp>)."
                    ),
                },
            },
        },
    },
    {
        "name": "export",
        "title": "Export (unified)",
        "description": (
            "Unified export wrapper — dispatches to export_stl / export_step / "
            "export_f3d based on format or file extension. "
            "Format is auto-detected from file_path extension if not specified. "
            "STL and STEP require body_name; F3D exports the whole design."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["stl", "step", "stp", "f3d"],
                    "description": (
                        "Output format. Inferred from file_path extension if omitted."
                    ),
                },
                "body_name": {
                    "type": "string",
                    "description": "Body to export (required for stl/step)",
                },
                "file_path": {
                    "type": "string",
                    "description": (
                        "Destination path (default: ~/Desktop/<name>.<ext>)"
                    ),
                },
            },
        },
    },
    # ── import ─────────────────────────────────────────────────────────
    {
        "name": "import_mesh",
        "title": "Import Mesh",
        "description": (
            "Import a mesh file (STL, OBJ, or 3MF) as a mesh body. "
            "Returns the mesh name and bounding box. "
            "Use for reference geometry (e.g. exported SketchUp model)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["file_path"],
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to mesh file (.stl/.obj/.3mf)",
                },
                "component_name": {
                    "type": "string",
                    "description": ("Target component name (omit for root component)"),
                },
                "units": {
                    "type": "string",
                    "enum": ["mm", "cm", "m", "in", "ft"],
                    "default": "mm",
                    "description": "Source mesh units (default: mm)",
                },
            },
        },
    },
    # ── parameters ─────────────────────────────────────────────────────
    {
        "name": "get_parameters",
        "title": "Get Parameters",
        "description": "List all user parameters in the design",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "create_parameter",
        "title": "Create Parameter",
        "description": "Create a new user parameter",
        "inputSchema": {
            "type": "object",
            "required": ["name", "value", "unit"],
            "properties": {
                "name": {"type": "string", "description": "Parameter name"},
                "value": {
                    "type": "number",
                    "description": "Numeric value, expressed in `unit`",
                },
                "unit": {
                    "type": "string",
                    "description": (
                        "Unit the value is given in (e.g. 'mm', 'cm', 'in', "
                        "'deg'). Empty means unitless."
                    ),
                },
                "comment": {"type": "string", "description": "Optional comment"},
            },
        },
    },
    {
        "name": "set_parameter",
        "title": "Set Parameter",
        "description": "Update the value of an existing user parameter",
        "inputSchema": {
            "type": "object",
            "required": ["name", "value"],
            "properties": {
                "name": {"type": "string", "description": "Parameter name"},
                "value": {
                    "type": "number",
                    "description": (
                        "New numeric value, expressed in the unit the "
                        "parameter already declares"
                    ),
                },
            },
        },
    },
    {
        "name": "delete_parameter",
        "title": "Delete Parameter",
        "description": "Remove a user parameter",
        "inputSchema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Parameter name"},
            },
        },
    },
    # ── sketch constraints ─────────────────────────────────────────────
    {
        "name": "add_constraint",
        "title": "Add Sketch Constraint",
        "description": (
            "Add a geometric constraint in the active sketch. "
            "Entities are referenced by index within the sketch."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["constraint_type"],
            "properties": {
                "constraint_type": {
                    "type": "string",
                    "enum": [
                        "coincident",
                        "parallel",
                        "perpendicular",
                        "tangent",
                        "equal",
                        "fix",
                        "midpoint",
                        "concentric",
                        "horizontal",
                        "vertical",
                        "symmetry",
                        "collinear",
                        "smooth",
                    ],
                },
                "entity_one": {
                    "type": "integer",
                    "description": "Index of the first sketch entity",
                    "minimum": 0,
                },
                "entity_two": {
                    "type": "integer",
                    "description": (
                        "Index of the second sketch entity "
                        "(not needed for fix/horizontal/vertical)"
                    ),
                    "minimum": 0,
                },
                "symmetry_line": {
                    "type": "integer",
                    "description": (
                        "Index of the symmetry line (only for symmetry constraint)"
                    ),
                    "minimum": 0,
                },
                "sketch_name": {
                    "type": "string",
                    "description": "Sketch name (default: most recent)",
                },
            },
        },
    },
    {
        "name": "auto_constrain",
        "title": "Auto-Constrain Sketch",
        "description": (
            "Automatically add geometric constraints and dimensions to fully "
            "constrain a sketch (Fusion 2026+ AutoConstrain API). "
            "result_option: 1 = thorough/slow (default), 2 = fast, "
            "3 = may move geometry within tolerance."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sketch_name": {
                    "type": "string",
                    "description": "Sketch name (default: most recent)",
                },
                "result_option": {
                    "type": "integer",
                    "enum": [1, 2, 3],
                    "default": 1,
                    "description": (
                        "1 = most thorough (slowest), 2 = fastest, "
                        "3 = adjusts geometry within tolerance"
                    ),
                },
            },
        },
    },
    # ── sketch dimensions ──────────────────────────────────────────────
    {
        "name": "add_dimension",
        "title": "Add Sketch Dimension",
        "description": (
            "Add a driving dimension to constrain sketch geometry. "
            "Value is in cm for distances, degrees for angles."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["dimension_type", "value"],
            "properties": {
                "dimension_type": {
                    "type": "string",
                    "enum": [
                        "distance",
                        "horizontal",
                        "vertical",
                        "angular",
                        "radial",
                        "diameter",
                    ],
                },
                "value": {
                    "type": "number",
                    "description": "Dimension value (cm or degrees)",
                },
                "entity_one": {
                    "type": "integer",
                    "description": "Index of first entity (point or curve)",
                    "minimum": 0,
                },
                "entity_two": {
                    "type": "integer",
                    "description": (
                        "Index of second entity "
                        "(for distance/angular; not for radial/diameter)"
                    ),
                    "minimum": 0,
                },
                "sketch_name": {
                    "type": "string",
                    "description": "Sketch name (default: most recent)",
                },
            },
        },
    },
    # ── construction geometry ──────────────────────────────────────────
    {
        "name": "create_construction_plane",
        "title": "Create Construction Plane",
        "description": "Create a construction plane for sketching",
        "inputSchema": {
            "type": "object",
            "required": ["method"],
            "properties": {
                "method": {
                    "type": "string",
                    "enum": [
                        "offset",
                        "angle",
                        "midplane",
                        "three_points",
                        "tangent",
                    ],
                },
                "plane": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                    "description": ("Reference plane (for offset/angle)"),
                },
                "offset": {
                    "type": "number",
                    "description": "Offset distance in cm (for offset)",
                },
                "angle": {
                    "type": "number",
                    "description": "Angle in degrees (for angle method)",
                },
                "edge_name": {
                    "type": "string",
                    "description": ("Edge or axis to rotate around (for angle method)"),
                },
                "plane_one": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                    "description": "First plane (for midplane)",
                },
                "plane_two": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                    "description": "Second plane (for midplane)",
                },
                "point_one": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "[x,y,z] first point",
                },
                "point_two": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "[x,y,z] second point",
                },
                "point_three": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "[x,y,z] third point",
                },
            },
        },
    },
    {
        "name": "create_construction_axis",
        "title": "Create Construction Axis",
        "description": "Create a construction axis",
        "inputSchema": {
            "type": "object",
            "required": ["method"],
            "properties": {
                "method": {
                    "type": "string",
                    "enum": [
                        "two_points",
                        "intersection",
                        "edge",
                        "perpendicular_at_point",
                    ],
                },
                "point_one": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "point_two": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "plane_one": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                    "description": ("First plane (for intersection)"),
                },
                "plane_two": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                    "description": ("Second plane (for intersection)"),
                },
                "body_name": {
                    "type": "string",
                    "description": "Body name (for edge method)",
                },
                "edge_index": {
                    "type": "integer",
                    "description": "Edge index on the body",
                    "minimum": 0,
                },
            },
        },
    },
    {
        "name": "create_ucs",
        "title": "Create User Coordinate System",
        "description": (
            "Create a UCS at (x, y, z) with optional rotation (Fusion 2026+ "
            "UCS API, preview). A hidden reference sketch is created to anchor "
            "the UCS — do not delete it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "UCS name"},
                "x": {"type": "number", "default": 0, "description": "Origin X (cm)"},
                "y": {"type": "number", "default": 0, "description": "Origin Y (cm)"},
                "z": {"type": "number", "default": 0, "description": "Origin Z (cm)"},
                "angle_x": {
                    "type": "number",
                    "default": 0,
                    "description": "Rotation about X (degrees)",
                },
                "angle_y": {
                    "type": "number",
                    "default": 0,
                    "description": "Rotation about Y (degrees)",
                },
                "angle_z": {
                    "type": "number",
                    "default": 0,
                    "description": "Rotation about Z (degrees)",
                },
            },
        },
    },
    # ── splines ────────────────────────────────────────────────────────
    {
        "name": "draw_spline",
        "title": "Draw Spline",
        "description": (
            "Draw a spline in the most recent sketch. "
            "Use fit_points for a curve through points, or "
            "control_points for a control-polygon spline."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["spline_type", "points"],
            "properties": {
                "spline_type": {
                    "type": "string",
                    "enum": ["fit_points", "control_points"],
                },
                "points": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 3,
                    },
                    "minItems": 2,
                    "description": ("Array of [x,y] or [x,y,z] points"),
                },
                "degree": {
                    "type": "integer",
                    "enum": [3, 5],
                    "default": 3,
                    "description": ("Spline degree (only for control_points, 3 or 5)"),
                },
            },
        },
    },
    # ── sketch curve operations ────────────────────────────────────────
    {
        "name": "offset_curve",
        "title": "Offset Curve",
        "description": (
            "Offset connected sketch curves by a distance. "
            "Direction is determined by the direction_point."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["curve_index", "offset_distance"],
            "properties": {
                "curve_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": ("Index of a curve in the connected loop"),
                },
                "offset_distance": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Offset distance (cm)",
                },
                "direction_x": {
                    "type": "number",
                    "default": 1,
                    "description": "X of direction point",
                },
                "direction_y": {
                    "type": "number",
                    "default": 0,
                    "description": "Y of direction point",
                },
                "sketch_name": {
                    "type": "string",
                    "description": ("Sketch name (default: most recent)"),
                },
            },
        },
    },
    {
        "name": "trim_curve",
        "title": "Trim Curve",
        "description": (
            "Trim a sketch curve at its intersections. "
            "The segment nearest to the given point is removed."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["curve_index", "point_x", "point_y"],
            "properties": {
                "curve_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Index of the curve to trim",
                },
                "point_x": {
                    "type": "number",
                    "description": ("X near the segment to remove"),
                },
                "point_y": {
                    "type": "number",
                    "description": ("Y near the segment to remove"),
                },
                "sketch_name": {"type": "string"},
            },
        },
    },
    {
        "name": "extend_curve",
        "title": "Extend Curve",
        "description": (
            "Extend a sketch curve to the nearest intersection. "
            "The end nearest to the given point is extended."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["curve_index", "point_x", "point_y"],
            "properties": {
                "curve_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Index of the curve to extend",
                },
                "point_x": {
                    "type": "number",
                    "description": "X near the end to extend",
                },
                "point_y": {
                    "type": "number",
                    "description": "Y near the end to extend",
                },
                "sketch_name": {"type": "string"},
            },
        },
    },
    # ── advanced features ──────────────────────────────────────────────
    {
        "name": "create_thread",
        "title": "Create Thread",
        "description": ("Add threads to a cylindrical face (cosmetic or modeled)"),
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "near_x": {
                    "type": "number",
                    "description": (
                        "Instead of face_index: a point on the hole/shaft axis; "
                        "the cylindrical face whose axis passes closest is used"
                    ),
                },
                "near_y": {"type": "number"},
                "near_z": {"type": "number"},
                "body_name": {"type": "string"},
                "face_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": ("Index of the cylindrical face"),
                },
                "is_internal": {
                    "type": "boolean",
                    "description": (
                        "Internal (hole) or external (shaft) thread. Omit it: "
                        "it is inferred from the face, and a value that "
                        "contradicts the face is rejected."
                    ),
                },
                "thread_type": {
                    "type": "string",
                    "default": "ISO Metric profile",
                    "description": (
                        "Thread standard "
                        "(e.g. 'ISO Metric profile', 'ANSI Unified Screw Threads')"
                    ),
                },
                "thread_designation": {
                    "type": "string",
                    "default": "M10x1.5",
                    "description": ("Size designation (e.g. 'M10x1.5')"),
                },
                "thread_class": {
                    "type": "string",
                    "default": "6g",
                    "description": "Thread class (e.g. '6g', '6H')",
                },
                "is_modeled": {
                    "type": "boolean",
                    "default": False,
                    "description": ("True = physical geometry, False = cosmetic"),
                },
                "is_full_length": {
                    "type": "boolean",
                    "default": True,
                    "description": "Thread entire cylinder length",
                },
                "thread_length": {
                    "type": "number",
                    "description": (
                        "Thread length in cm (only if is_full_length=false)"
                    ),
                },
            },
        },
    },
    {
        "name": "draft_faces",
        "title": "Draft / Taper Faces",
        "description": (
            "Add a draft angle to faces of a body "
            "(for mold release / injection molding)"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["body_name", "angle"],
            "properties": {
                "body_name": {"type": "string"},
                "angle": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 89,
                    "description": "Draft angle in degrees",
                },
                "face_selection": {
                    "type": "string",
                    "enum": ["all", "top", "bottom", "vertical"],
                    "default": "vertical",
                    "description": "Which faces to draft",
                },
                "pull_direction_plane": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                    "default": "xy",
                    "description": "Plane defining the pull direction",
                },
                "is_tangent_chain": {
                    "type": "boolean",
                    "default": True,
                    "description": ("Include tangent-connected faces"),
                },
            },
        },
    },
    {
        "name": "split_body",
        "title": "Split Body",
        "description": "Split a body using a plane or face",
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "splitting_plane": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                    "default": "xy",
                    "description": ("Plane to split with (or use splitting_body)"),
                },
                "splitting_body": {
                    "type": "string",
                    "description": (
                        "Name of a body/surface to use "
                        "as splitting tool (overrides plane)"
                    ),
                },
                "extend_tool": {
                    "type": "boolean",
                    "default": True,
                    "description": ("Extend tool to cut through entire body"),
                },
            },
        },
    },
    {
        "name": "split_face",
        "title": "Split Face",
        "description": "Split faces of a body using a plane",
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "face_indices": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "description": ("Indices of faces to split (default: all faces)"),
                },
                "splitting_plane": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                    "default": "xy",
                },
                "extend_tool": {
                    "type": "boolean",
                    "default": True,
                },
            },
        },
    },
    {
        "name": "offset_faces",
        "title": "Offset Faces",
        "description": ("Push/pull faces of a body by a distance"),
        "inputSchema": {
            "type": "object",
            "required": ["body_name", "distance"],
            "properties": {
                "body_name": {"type": "string"},
                "distance": {
                    "type": "number",
                    "description": ("Offset distance in cm (positive = outward)"),
                },
                "face_selection": {
                    "type": "string",
                    "enum": ["all", "top", "bottom"],
                    "default": "top",
                    "description": "Which faces to offset",
                },
                "face_indices": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "description": ("Specific face indices (overrides face_selection)"),
                },
            },
        },
    },
    {
        "name": "scale_body",
        "title": "Scale Body",
        "description": "Scale a body uniformly or non-uniformly",
        "inputSchema": {
            "type": "object",
            "required": ["body_name", "scale"],
            "properties": {
                "body_name": {"type": "string"},
                "scale": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Uniform scale factor",
                },
                "scale_x": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": ("X scale (overrides uniform scale)"),
                },
                "scale_y": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Y scale",
                },
                "scale_z": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Z scale",
                },
                "anchor_x": {
                    "type": "number",
                    "default": 0,
                    "description": "Scale anchor point X",
                },
                "anchor_y": {
                    "type": "number",
                    "default": 0,
                    "description": "Scale anchor point Y",
                },
                "anchor_z": {
                    "type": "number",
                    "default": 0,
                    "description": "Scale anchor point Z",
                },
            },
        },
    },
    # ── direct primitives ──────────────────────────────────────────────
    {
        "name": "create_box",
        "title": "Create Box",
        "description": (
            "Create a box primitive (non-parametric via TemporaryBRepManager). "
            "center_x/center_y are the box CENTER, but center_z is its BOTTOM "
            "face: the box spans center_z .. center_z + height (confirmed "
            "live: center_z=6, height=12 gave Z 6..18)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["length", "width", "height"],
            "properties": {
                "length": {"type": "number", "minimum": 0.001},
                "width": {"type": "number", "minimum": 0.001},
                "height": {"type": "number", "minimum": 0.001},
                "center_x": {"type": "number", "default": 0},
                "center_y": {"type": "number", "default": 0},
                "center_z": {"type": "number", "default": 0},
            },
        },
    },
    {
        "name": "create_box_parametric",
        "title": "Create Parametric Box",
        "description": (
            "Create a history-based rectangular box via sketch rectangle + "
            "extrude (unlike create_box which uses TemporaryBRepManager). "
            "length/width/height accept a number (cm, Fusion internal unit) "
            "or a string expression referencing User Parameters "
            "(e.g. 'boxL', '56 mm', 'outer - 2 * wall_t'). "
            "Call create_parameter first to define named parameters."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["length", "width", "height"],
            "properties": {
                "length": {
                    "oneOf": [
                        {"type": "number", "minimum": 0.001},
                        {"type": "string"},
                    ],
                    "description": "Along sketch X: number (cm) or expression",
                },
                "width": {
                    "oneOf": [
                        {"type": "number", "minimum": 0.001},
                        {"type": "string"},
                    ],
                    "description": "Along sketch Y: number (cm) or expression",
                },
                "height": {
                    "oneOf": [
                        {"type": "number", "minimum": 0.001},
                        {"type": "string"},
                    ],
                    "description": "Extrude distance: number (cm) or expression",
                },
                "origin_x": {"type": "number", "default": 0},
                "origin_y": {"type": "number", "default": 0},
                "origin_z": {
                    "type": "number",
                    "default": 0,
                    "description": "Z-offset of sketch plane (cm)",
                },
                "plane": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                    "default": "xy",
                },
                "component_name": {
                    "type": "string",
                    "description": "Target component (omit for root)",
                },
                "body_name": {
                    "type": "string",
                    "description": "Optional name for the resulting body",
                },
            },
        },
    },
    {
        "name": "create_cylinder",
        "title": "Create Cylinder",
        "description": (
            "Create a cylinder (or cone, with top_radius) primitive "
            "(non-parametric via TemporaryBRepManager). The base circle is "
            "centred at (base_x, base_y, base_z); the body extends `height` "
            "along `axis`, or along (direction_x, direction_y, direction_z) "
            "when given — any direction, e.g. an inclined valve bore."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["radius", "height"],
            "properties": {
                "radius": {"type": "number", "minimum": 0.001},
                "height": {"type": "number", "minimum": 0.001},
                "base_x": {"type": "number", "default": 0},
                "base_y": {"type": "number", "default": 0},
                "base_z": {"type": "number", "default": 0},
                "axis": {
                    "type": "string",
                    "enum": ["x", "y", "z"],
                    "default": "z",
                    "description": "Cylinder axis direction",
                },
                "direction_x": {
                    "type": "number",
                    "description": "Axis direction vector (overrides axis)",
                },
                "direction_y": {"type": "number"},
                "direction_z": {"type": "number"},
                "top_radius": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Radius at the far end (cone); default = radius",
                },
            },
        },
    },
    {
        "name": "create_sphere",
        "title": "Create Sphere",
        "description": (
            "Create a sphere primitive (non-parametric via TemporaryBRepManager)"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["radius"],
            "properties": {
                "radius": {"type": "number", "minimum": 0.001},
                "center_x": {"type": "number", "default": 0},
                "center_y": {"type": "number", "default": 0},
                "center_z": {"type": "number", "default": 0},
            },
        },
    },
    {
        "name": "create_torus",
        "title": "Create Torus",
        "description": (
            "Create a torus primitive (non-parametric via TemporaryBRepManager)"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["major_radius", "minor_radius"],
            "properties": {
                "major_radius": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Distance from center to tube center",
                },
                "minor_radius": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Tube cross-section radius",
                },
                "center_x": {"type": "number", "default": 0},
                "center_y": {"type": "number", "default": 0},
                "center_z": {"type": "number", "default": 0},
                "axis": {
                    "type": "string",
                    "enum": ["x", "y", "z"],
                    "default": "z",
                },
            },
        },
    },
    # ── assembly (extended) ────────────────────────────────────────────
    {
        "name": "create_as_built_joint",
        "title": "Create As-Built Joint",
        "description": (
            "Create a joint from components' current positions "
            "(easier than geometric joints)"
        ),
        "inputSchema": {
            "type": "object",
            "required": [
                "component_one",
                "component_two",
                "joint_type",
            ],
            "properties": {
                "component_one": {"type": "string"},
                "component_two": {"type": "string"},
                "joint_type": {
                    "type": "string",
                    "enum": [
                        "rigid",
                        "revolute",
                        "slider",
                        "cylindrical",
                        "pin_slot",
                        "planar",
                        "ball",
                    ],
                    "default": "rigid",
                },
            },
        },
    },
    {
        "name": "create_rigid_group",
        "title": "Create Rigid Group",
        "description": "Lock multiple components together",
        "inputSchema": {
            "type": "object",
            "required": ["component_names"],
            "properties": {
                "component_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "description": "Names of components to group",
                },
                "include_children": {
                    "type": "boolean",
                    "default": True,
                    "description": ("Include child sub-components"),
                },
            },
        },
    },
    # ── inspection / analysis ──────────────────────────────────────────
    {
        "name": "measure_distance",
        "title": "Measure Distance",
        "description": ("Measure minimum distance between two entities"),
        "inputSchema": {
            "type": "object",
            "required": ["entity_one", "entity_two"],
            "properties": {
                "entity_one": {
                    "type": "string",
                    "description": (
                        "First entity name (body, sketch, or point 'x,y,z')"
                    ),
                },
                "entity_two": {
                    "type": "string",
                    "description": "Second entity name or point",
                },
            },
        },
    },
    {
        "name": "measure_angle",
        "title": "Measure Angle",
        "description": (
            "Measure the angle between one face of each of two bodies "
            "(picked by index — defaults to each body's first face)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["entity_one", "entity_two"],
            "properties": {
                "entity_one": {
                    "type": "string",
                    "description": "First body's name",
                },
                "entity_two": {
                    "type": "string",
                    "description": "Second body's name",
                },
                "face_index_one": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Face index on the first body",
                },
                "face_index_two": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Face index on the second body",
                },
            },
        },
    },
    {
        "name": "get_physical_properties",
        "title": "Get Physical Properties",
        "description": (
            "Get mass, volume, surface area, center of mass, and density of a body"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "accuracy": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "very_high"],
                    "default": "medium",
                },
            },
        },
    },
    {
        "name": "create_section_analysis",
        "title": "Create Section Analysis",
        "description": "Cut a section plane through the model",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plane": {
                    "type": "string",
                    "enum": ["xy", "yz", "xz"],
                    "default": "yz",
                },
                "offset": {
                    "type": "number",
                    "default": 0,
                    "description": "Offset from the plane (cm)",
                },
            },
        },
    },
    {
        "name": "check_interference",
        "title": "Check Interference",
        "description": ("Detect collisions between components/bodies"),
        "inputSchema": {
            "type": "object",
            "required": ["component_names"],
            "properties": {
                "component_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "description": ("Names of components to check"),
                },
                "include_coincident_faces": {
                    "type": "boolean",
                    "default": False,
                    "description": ("Count touching faces as interference"),
                },
            },
        },
    },
    {
        "name": "compare_meshes",
        "title": "Compare Mesh Bodies",
        "description": (
            "Compare two mesh bodies and return deviation statistics "
            "(min/max/mean/RMS signed distance in cm) — e.g. validate an "
            "imported STL against a reference mesh. Requires Fusion 2026+."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["mesh_name_a", "mesh_name_b"],
            "properties": {
                "mesh_name_a": {
                    "type": "string",
                    "description": "Name of the first mesh body",
                },
                "mesh_name_b": {
                    "type": "string",
                    "description": "Name of the reference mesh body",
                },
            },
        },
    },
    # ── appearance / material ──────────────────────────────────────────
    {
        "name": "set_appearance",
        "title": "Set Appearance",
        "description": (
            "Assign a material appearance to a body, face, "
            "or component from the Fusion appearance library"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["target_name", "appearance_name"],
            "properties": {
                "target_name": {
                    "type": "string",
                    "description": "Name of body or component",
                },
                "appearance_name": {
                    "type": "string",
                    "description": (
                        "EXACT library appearance name, in the Fusion UI's "
                        "own display language — not necessarily English. "
                        "Confirmed live: on a pt-BR install, names are "
                        "'Aço - Acetinado', not 'Steel - Satin' (English "
                        "names raise a clear 'not found' error with close "
                        "matches from the real library, not a silent "
                        "failure)."
                    ),
                },
                "target_type": {
                    "type": "string",
                    "enum": ["body", "component", "face"],
                    "default": "body",
                },
                "face_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": ("Face index (if target_type=face)"),
                },
            },
        },
    },
    {
        "name": "set_color",
        "title": "Set Body Color",
        "description": (
            "Assign a flat RGB color to a body (creates/reuses a design-local "
            "appearance). Useful for visually distinguishing parts before "
            "render_view."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["body_name", "red", "green", "blue"],
            "properties": {
                "body_name": {"type": "string", "description": "Body name"},
                "red": {"type": "integer", "minimum": 0, "maximum": 255},
                "green": {"type": "integer", "minimum": 0, "maximum": 255},
                "blue": {"type": "integer", "minimum": 0, "maximum": 255},
                "opacity": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 1,
                    "description": "1.0 = opaque, 0.0 = invisible",
                },
            },
        },
    },
    # ── project geometry ───────────────────────────────────────────────
    {
        "name": "project_geometry",
        "title": "Project Geometry",
        "description": ("Project edges or bodies onto the active sketch plane"),
        "inputSchema": {
            "type": "object",
            "required": ["source_name"],
            "properties": {
                "source_name": {
                    "type": "string",
                    "description": ("Name of body or edge to project"),
                },
                "is_linked": {
                    "type": "boolean",
                    "default": True,
                    "description": ("True = parametrically linked to source geometry"),
                },
                "sketch_name": {
                    "type": "string",
                    "description": ("Target sketch (default: most recent)"),
                },
            },
        },
    },
    # ── timeline control ──────────────────────────────────────────────
    {
        "name": "suppress_feature",
        "title": "Suppress Feature",
        "description": (
            "Suppress (disable) one or more timeline features. Pass "
            "feature_names for a batch: it recomputes the timeline ONCE "
            "(one call per feature costs a full recompute each — ~2.5 s "
            "apiece on a 200+ item timeline). Suppressing a Combine "
            "cut/join brings its tool body back; the result lists "
            "bodies_appeared so you can suppress the feature that made it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "feature_name": {"type": "string"},
                "feature_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Several features, suppressed with a single recompute"
                    ),
                },
            },
        },
    },
    {
        "name": "unsuppress_feature",
        "title": "Unsuppress Feature",
        "description": (
            "Unsuppress (re-enable) one or more timeline features; "
            "feature_names recomputes once for the whole batch."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "feature_name": {"type": "string"},
                "feature_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Several features, unsuppressed with a single "
                        "recompute"
                    ),
                },
            },
        },
    },
    # ── surface operations ─────────────────────────────────────────────
    {
        "name": "patch_surface",
        "title": "Patch Surface",
        "description": ("Create a patch surface from boundary edges"),
        "inputSchema": {
            "type": "object",
            "required": ["sketch_name"],
            "properties": {
                "sketch_name": {
                    "type": "string",
                    "description": "Sketch with boundary curves",
                },
                "profile_index": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                },
                "continuity": {
                    "type": "string",
                    "enum": ["connected", "tangent", "curvature"],
                    "default": "connected",
                },
            },
        },
    },
    {
        "name": "stitch_surfaces",
        "title": "Stitch Surfaces",
        "description": ("Stitch surface bodies into a single body"),
        "inputSchema": {
            "type": "object",
            "required": ["body_names"],
            "properties": {
                "body_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                },
                "tolerance": {
                    "type": "number",
                    "default": 0.01,
                    "description": "Stitch tolerance (cm)",
                },
            },
        },
    },
    {
        "name": "thicken_surface",
        "title": "Thicken Surface",
        "description": "Thicken a surface body into a solid",
        "inputSchema": {
            "type": "object",
            "required": ["body_name", "thickness"],
            "properties": {
                "body_name": {"type": "string"},
                "thickness": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Thickness (cm)",
                },
                "direction": {
                    "type": "string",
                    "enum": ["positive", "negative", "symmetric"],
                    "default": "symmetric",
                },
            },
        },
    },
    {
        "name": "ruled_surface",
        "title": "Ruled Surface",
        "description": ("Create a ruled surface from an edge or sketch curve"),
        "inputSchema": {
            "type": "object",
            "required": ["body_name", "edge_index"],
            "properties": {
                "body_name": {"type": "string"},
                "edge_index": {
                    "type": "integer",
                    "minimum": 0,
                },
                "distance": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Ruled surface distance (cm)",
                },
                "rule_type": {
                    "type": "string",
                    "enum": ["normal", "tangent"],
                    "default": "normal",
                },
            },
        },
    },
    {
        "name": "trim_surface",
        "title": "Trim Surface",
        "description": "Trim a surface body with another body",
        "inputSchema": {
            "type": "object",
            "required": ["body_name", "tool_name"],
            "properties": {
                "body_name": {
                    "type": "string",
                    "description": "Surface body to trim",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Trimming tool body",
                },
            },
        },
    },
    # ── sheet metal ────────────────────────────────────────────────────
    {
        "name": "create_flange",
        "title": "Create Flange",
        "description": ("Create a sheet metal flange on an edge"),
        "inputSchema": {
            "type": "object",
            "required": ["body_name", "edge_index"],
            "properties": {
                "body_name": {"type": "string"},
                "edge_index": {
                    "type": "integer",
                    "minimum": 0,
                },
                "height": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Flange height (cm)",
                },
                "angle": {
                    "type": "number",
                    "default": 90,
                    "description": "Bend angle (degrees)",
                },
                "bend_radius": {
                    "type": "number",
                    "description": "Bend radius (cm)",
                },
            },
        },
    },
    {
        "name": "create_bend",
        "title": "Create Bend",
        "description": "Add a bend to a sheet metal body",
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "bend_line_sketch": {
                    "type": "string",
                    "description": "Sketch with bend line",
                },
                "angle": {
                    "type": "number",
                    "default": 90,
                    "description": "Bend angle (degrees)",
                },
                "bend_radius": {
                    "type": "number",
                    "description": "Override bend radius (cm)",
                },
            },
        },
    },
    {
        "name": "flat_pattern",
        "title": "Flat Pattern",
        "description": (
            "Create the flat pattern of a sheet metal body "
            "(run convert_to_sheet_metal first)"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "face_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Stationary face. Default: largest planar face",
                },
            },
        },
    },
    {
        "name": "unfold",
        "title": "Unfold",
        "description": "Unfold specific bends in a sheet metal body",
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "bend_indices": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "description": ("Indices of bends to unfold (omit to unfold all)"),
                },
            },
        },
    },
    # ── CAM / manufacturing ──────────────────────────────────────────
    {
        "name": "cam_create_setup",
        "title": "Create CAM Setup",
        "description": (
            "Create a manufacturing setup for a body. "
            "Defines the stock, coordinate system, and "
            "operation type (milling/turning/cutting)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {
                    "type": "string",
                    "description": "Body to machine",
                },
                "name": {
                    "type": "string",
                    "description": "Setup name",
                },
                "operation_type": {
                    "type": "string",
                    "enum": ["milling", "turning", "cutting"],
                    "default": "milling",
                },
                "stock_mode": {
                    "type": "string",
                    "enum": [
                        "relative_box",
                        "fixed_box",
                        "from_body",
                    ],
                    "default": "relative_box",
                },
                "stock_offset_sides": {
                    "type": "number",
                    "default": 0,
                    "description": "Side offset (cm)",
                },
                "stock_offset_top": {
                    "type": "number",
                    "default": 0,
                    "description": "Top offset (cm)",
                },
                "stock_offset_bottom": {
                    "type": "number",
                    "default": 0,
                    "description": "Bottom offset (cm)",
                },
            },
        },
    },
    {
        "name": "cam_create_operation",
        "title": "Create CAM Operation",
        "description": (
            "Add a machining operation to a setup. "
            "Strategy determines the toolpath type."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["setup_name", "strategy"],
            "properties": {
                "setup_name": {
                    "type": "string",
                    "description": "Name of the parent setup",
                },
                "strategy": {
                    "type": "string",
                    "enum": [
                        "face",
                        "2d_contour",
                        "2d_pocket",
                        "2d_adaptive",
                        "3d_adaptive",
                        "3d_pocket",
                        "3d_contour",
                        "3d_scallop",
                        "3d_parallel",
                        "drilling",
                        "bore",
                        "thread_milling",
                        "slot",
                        "trace",
                        "engrave",
                    ],
                    "description": "Machining strategy",
                },
                "name": {
                    "type": "string",
                    "description": "Operation name",
                },
                "tool_number": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Tool number from library",
                },
                "tool_diameter": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": (
                        "Not supported — tool geometry comes from the CAM "
                        "tool library; select via tool_number instead. "
                        "Passing this raises an error."
                    ),
                },
                "stepdown": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Axial depth of cut (cm)",
                },
                "stepover": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": ("Radial stepover (cm)"),
                },
                "feed_rate": {
                    "type": "number",
                    "description": "Feed rate (cm/min)",
                },
                "spindle_speed": {
                    "type": "number",
                    "description": "Spindle speed (RPM)",
                },
                "coolant": {
                    "type": "string",
                    "enum": [
                        "disabled",
                        "flood",
                        "mist",
                        "through_tool",
                    ],
                    "default": "flood",
                },
                "geometry_face_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Index (0-based) of a face on the setup's model body "
                        "whose outer loop becomes the operation's chain "
                        "geometry — equivalent to clicking that face in the "
                        "Fusion UI. Required for chain-based strategies "
                        "(2d_contour, 2d_pocket, 2d_adaptive, drilling, "
                        "bore, ...) to generate a toolpath; find face "
                        "indices via get_object_info on the body."
                    ),
                },
                "tool_from_operation": {
                    "type": "string",
                    "description": (
                        "Name of an existing operation whose real library "
                        "tool should be reused, syncing the tool-search "
                        "filter to match. tool_number alone only writes a "
                        "parameter and leaves the operation without a tool — "
                        "generating it then opens a modal dialog inside "
                        "Fusion that freezes this connection until someone "
                        "dismisses it by hand."
                    ),
                },
            },
        },
    },
    {
        "name": "cam_generate_toolpath",
        "title": "Generate Toolpath",
        "description": (
            "Generate toolpaths for a specific operation or all operations in a setup"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "setup_name": {
                    "type": "string",
                    "description": ("Setup name (generates all its operations)"),
                },
                "operation_name": {
                    "type": "string",
                    "description": (
                        "Specific operation name. Requires setup_name too — "
                        "does not stand alone"
                    ),
                },
                "generate_all": {
                    "type": "boolean",
                    "default": False,
                    "description": "Generate all toolpaths",
                },
            },
        },
    },
    {
        "name": "cam_post_process",
        "title": "Post Process",
        "description": ("Post-process toolpaths to generate NC code (G-code)"),
        "inputSchema": {
            "type": "object",
            "required": ["setup_name"],
            "properties": {
                "setup_name": {
                    "type": "string",
                    "description": "Setup to post-process",
                },
                "operation_name": {
                    "type": "string",
                    "description": ("Specific operation (omit to post all in setup)"),
                },
                "post_processor": {
                    "type": "string",
                    "default": "fanuc",
                    "description": (
                        "Post processor short name ('fanuc', 'grbl', 'haas') "
                        "resolved against the local post folder when the "
                        "Fusion build provides one, or a full path to a "
                        ".cps file (required on cloud-post builds)"
                    ),
                },
                "output_folder": {
                    "type": "string",
                    "description": ("Output directory (default: ~/Desktop)"),
                },
                "output_units": {
                    "type": "string",
                    "enum": ["mm", "in"],
                    "default": "mm",
                },
                "program_name": {
                    "type": "string",
                    "default": "1001",
                    "description": (
                        "NC program name/number written into the G-code "
                        "header. Most posts (including fanuc) require a "
                        "plain integer here and reject a text label"
                    ),
                },
            },
        },
    },
    {
        "name": "cam_list_setups",
        "title": "List CAM Setups",
        "description": ("List all manufacturing setups in the document"),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "cam_list_operations",
        "title": "List CAM Operations",
        "description": ("List operations within a setup"),
        "inputSchema": {
            "type": "object",
            "required": ["setup_name"],
            "properties": {
                "setup_name": {
                    "type": "string",
                },
            },
        },
    },
    {
        "name": "cam_get_operation_info",
        "title": "Get CAM Operation Info",
        "description": (
            "Get details about a specific operation "
            "(strategy, tool, parameters, toolpath status)"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["setup_name", "operation_name"],
            "properties": {
                "setup_name": {"type": "string"},
                "operation_name": {"type": "string"},
            },
        },
    },
    # ── health ───────────────────────────────────────────────────────
    {
        "name": "ping",
        "title": "Ping",
        "description": (
            "Health check — returns immediately without touching Fusion API"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    # ── design type safety ──────────────────────────────────────────────
    {
        "name": "get_design_type",
        "title": "Get Design Type",
        "description": (
            "Check if the design is in parametric or direct mode. "
            "Use this to detect accidental mode switches."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "set_design_type",
        "title": "Set Design Type",
        "description": (
            "Switch design type between 'parametric' and 'direct'. "
            "Use 'parametric' to recover from accidental direct-mode "
            "switches (equivalent to Capture Design History in the UI)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["design_type"],
            "properties": {
                "design_type": {
                    "type": "string",
                    "enum": ["parametric", "direct"],
                    "description": "Target design type",
                },
            },
        },
    },
    # ── perception ──────────────────────────────────────────────────────
    {
        "name": "render_view",
        "title": "Render Viewport",
        "description": (
            "Capture the active viewport as a PNG so you can visually verify "
            "the model. Pass a canonical view (iso/front/top/etc.) to "
            "reposition the camera first, or 'current' to keep it as is. "
            "Returns base64-encoded image bytes alongside metadata; the MCP "
            "server delivers it as an image content block."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "view": {
                    "type": "string",
                    "enum": [
                        "current",
                        "iso",
                        "front",
                        "back",
                        "top",
                        "bottom",
                        "left",
                        "right",
                    ],
                    "default": "current",
                    "description": (
                        "Camera preset; 'current' preserves the existing view"
                    ),
                },
                "width": {
                    "type": "integer",
                    "minimum": 64,
                    "maximum": 4096,
                    "default": 1024,
                },
                "height": {
                    "type": "integer",
                    "minimum": 64,
                    "maximum": 4096,
                    "default": 768,
                },
                "fit": {
                    "type": "boolean",
                    "default": True,
                    "description": "Call Viewport.fit() before capture",
                },
            },
        },
    },
]

# ---------------------------------------------------------------------------
# FERRAMENTAS DESABILITADAS NESTE FORK
#
# Auditadas contra os stubs da API do Fusion 2704.1.53 e comprovadamente
# inviaveis nesta versao. Nao sao "bugs a corrigir": a API que elas usam
# deixou de existir ou mudou de semantica a ponto de exigir reescrita.
#
#   create_thread     ThreadFeatures.threadDataQuery nao existe
#   ruled_surface     createInput() exige 4-5 args (angulo, tipo, direcao)
#                     que a ferramenta nem coleta
#   trim_surface      createInput() aceita so o trimTool; corte agora e por
#                     selecao de celulas, semantica diferente
#   create_flange     FlangeFeatures nao tem createInput nem add
#   create_bend       Features.bendFeatures nao existe
#   flat_pattern      Features.flatPatternFeatures nao existe
#   unfold            UnfoldFeatures nao tem createInput nem add
#   cam_post_process  PostProcessInput e CAM.postProcess() substituidos pelo
#                     fluxo de NCPrograms
#
# Ficam fora da lista para o agente nao tentar usa-las e receber um erro
# confuso no meio de um trabalho.
# ---------------------------------------------------------------------------
DESABILITADAS_2704 = frozenset({
    "ruled_surface",
    "trim_surface",
    "create_flange",
    "create_bend",
    "unfold",
})
# Reabilitadas depois de conferir contra o MODULO DE RUNTIME (nao so stubs):
#   create_thread     reescrita no padrao do exemplo oficial Bolt.py
#   flat_pattern      reescrita com Component.createFlatPattern
#   cam_post_process  funcionava como estava -- PostProcessInput e
#                     CAM.postProcess existem em runtime (API aposentada)
# create_flange/create_bend foram substituidas por convert_to_sheet_metal e
# fold_sheet_metal, definidas abaixo.

TOOLS += [
    {
        "name": "convert_to_sheet_metal",
        "title": "Convert to Sheet Metal",
        "description": (
            "Convert a solid body of uniform thickness into sheet metal. "
            "Thickness is taken from the geometry, not from the rule. "
            "This replaces flange creation, which the Fusion API does not "
            "expose: model the shape with extrude/shell, then convert."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "rule_name": {
                    "type": "string",
                    "description": "Sheet metal rule. Default: first available",
                },
                "face_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Base face. Default: largest planar face",
                },
            },
        },
    },
    {
        "name": "fold_sheet_metal",
        "title": "Fold Sheet Metal",
        "description": (
            "Bend a sheet metal body along a line of the last sketch. "
            "Draw the line on the sheet face with draw_line first."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["body_name", "bend_angle"],
            "properties": {
                "body_name": {"type": "string"},
                "bend_angle": {"type": "number", "description": "Degrees"},
                "line_index": {
                    "type": "integer",
                    "description": "Line in the last sketch. Default: last line",
                },
                "line_position": {
                    "type": "string",
                    "enum": ["start", "center", "end"],
                },
                "allow_bend_relief": {"type": "boolean"},
                "face_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Stationary face. Default: largest planar face",
                },
            },
        },
    },
    {
        "name": "export_flat_pattern_dxf",
        "title": "Export Flat Pattern DXF",
        "description": (
            "Export the flat pattern of a sheet metal body as DXF, for laser, "
            "plasma or waterjet cutting (run flat_pattern first)"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["body_name"],
            "properties": {
                "body_name": {"type": "string"},
                "file_path": {"type": "string"},
            },
        },
    },
]


# ── tool annotations ──────────────────────────────────────────────────
# Applied after definition for cleanliness. Classifies each tool by its
# side-effect profile so MCP clients can auto-approve safe operations.

_READ_ONLY = {
    "get_scene_info",
    "get_object_info",
    "get_bounding_box",
    "list_components",
    "get_parameters",
    "get_physical_properties",
    "measure_distance",
    "measure_angle",
    "check_interference",
    "compare_meshes",
    "ping",
    "cam_list_setups",
    "cam_list_operations",
    "cam_get_operation_info",
    "get_design_type",
    "render_view",
}
_DESTRUCTIVE = {"delete_all", "delete_parameter", "delete_body"}
_IDEMPOTENT = {
    "ping",
    "get_scene_info",
    "get_object_info",
    "get_bounding_box",
    "list_components",
    "get_parameters",
    "get_physical_properties",
    "measure_distance",
    "measure_angle",
    "check_interference",
    "compare_meshes",
    "set_parameter",
    "set_appearance",
    "set_color",
    "cam_list_setups",
    "cam_list_operations",
    "cam_get_operation_info",
    "get_design_type",
    "set_design_type",
    "rename_body",
    "render_view",
}

for _t in TOOLS:
    _name = _t["name"]
    _t["annotations"] = {
        "readOnlyHint": _name in _READ_ONLY,
        "destructiveHint": _name in _DESTRUCTIVE,
        "idempotentHint": _name in _IDEMPOTENT,
    }


def get_tool_list() -> list[types.Tool]:
    """Convert tool dicts to MCP Tool objects."""
    result = []
    for t in TOOLS:
        ann = t.get("annotations")
        tool = types.Tool(
            name=t["name"],
            title=t["title"],
            description=t["description"],
            inputSchema=t["inputSchema"],
            annotations=types.ToolAnnotations(**ann) if ann else None,
        )
        result.append(tool)
    return result



TOOLS = [t for t in TOOLS if t["name"] not in DESABILITADAS_2704]


def get_tool_by_name(name: str) -> dict | None:
    for t in TOOLS:
        if t["name"] == name:
            return t
    return None
