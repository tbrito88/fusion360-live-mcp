"""
Mock responses for every Fusion 360 MCP command.

Used when the server is started with ``--mode mock`` so the full
tool→response pipeline can be tested without a running Fusion instance.
Every response includes ``"mode": "mock"`` so callers know it's simulated.

The envelope matches the real addon: success results carry ``ok: True``,
mutation results carry a ``deltas`` sub-dict, and an ``__mock_error__``
sentinel in params forces a classified error response for tests.
"""

from typing import Any

from .hints import classify as _classify

# Mutation commands that get a synthetic deltas payload in mock mode.
# Keep in sync with CommandHandler._MUTATION_COMMANDS in the addon.
_MUTATION_MOCKS: frozenset[str] = frozenset(
    {
        "extrude",
        "revolve",
        "sweep",
        "loft",
        "fillet",
        "chamfer",
        "shell",
        "mirror",
        "create_hole",
        "rectangular_pattern",
        "circular_pattern",
        "draft_faces",
        "split_body",
        "split_face",
        "offset_faces",
        "scale_body",
        "suppress_feature",
        "unsuppress_feature",
        "move_body",
        "delete_body",
        "boolean_operation",
        "create_box",
        "create_cylinder",
        "create_sphere",
        "create_torus",
        "thicken_surface",
        "patch_surface",
        "stitch_surfaces",
        "delete_all",
        "undo",
        "set_parameter",
        "execute_code",
        "auto_constrain",
        "create_ucs",
        "set_color",
        "create_thread",
        "flat_pattern",
        "convert_to_sheet_metal",
        "fold_sheet_metal",
    }
)

_MOCK_DELTAS = {
    "body_count_before": 0,
    "body_count_after": 1,
    "body_count_delta": 1,
    "mass_g_before": 0.0,
    "mass_g_after": 10.0,
    "mass_g_delta": 10.0,
    "bbox_before": None,
    "bbox_after": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
}


def mock_command(command_type: str, params: dict[str, Any] | None = None) -> dict:
    """Return a plausible mock response for *command_type*.

    If *params* contains ``__mock_error__`` (a string message), the response
    simulates an addon-side failure: ``ok: False`` plus a classified
    ``error_kind`` and contextual ``hints``.
    """
    params = params or {}

    forced = params.get("__mock_error__")
    if forced is not None:
        kind, hint_list = _classify(str(forced))
        return {
            "ok": False,
            "error_kind": kind,
            "error_message": str(forced),
            "hints": hint_list,
            "traceback": f"MockError: {forced}",
            "mode": "mock",
        }

    handler = _DISPATCH.get(command_type, _default_mock)
    result = handler(params)
    result.setdefault("ok", True)
    if command_type in _MUTATION_MOCKS and "deltas" not in result:
        result["deltas"] = dict(_MOCK_DELTAS)
    result["mode"] = "mock"
    return result


# ── individual mock handlers ──────────────────────────────────────────


def _ping(p: dict) -> dict:
    # Live, ping is answered by the add-in's event bridge (never reaches
    # CommandHandler.ping): {"ok": True, "status": "pong"}.
    return {"ok": True, "status": "pong"}


def _get_scene_info(p: dict) -> dict:
    # Mirrors CommandHandler.get_scene_info's return shape.
    return {
        "design_name": "MockDesign",
        "design_type": None,
        "bodies": ["Body1"],
        "sketches": ["Sketch1"],
        "bodies_count": 1,
        "sketches_count": 1,
        "features_count": 1,
        "timeline_count": 1,
        "camera": None,
    }


def _get_object_info(p: dict) -> dict:
    # Mirrors CommandHandler._object_info_for_body's return shape.
    name = p.get("name", "Unknown")
    return {
        "found": True,
        "type": "body",
        "name": name,
        "volume": 1.0,
        "area": 6.0,
        "material": None,
        "is_visible": True,
        "faces_count": 6,
        "edges_count": 12,
        "vertices_count": 8,
        "bounding_box": {"min": [0, 0, 0], "max": [1, 1, 1]},
    }


def _get_bounding_box(p: dict) -> dict:
    name = p.get("name", "Unknown")
    return {
        "found": True,
        "type": "body",
        "name": name,
        "min": [0.0, 0.0, 0.0],
        "max": [50.0, 30.0, 15.0],
        "size": [50.0, 30.0, 15.0],
        "center": [25.0, 15.0, 7.5],
    }


def _create_sketch(p: dict) -> dict:
    # Mirrors CommandHandler.create_sketch's return shape.
    plane = p.get("plane", "xy")
    return {
        "sketch_name": f"Sketch_mock_{plane}",
        "plane": plane,
        "z_offset": p.get("z_offset", 0),
    }


def _draw_rectangle(p: dict) -> dict:
    # Mirrors CommandHandler.draw_rectangle's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "width": p.get("width", 1),
        "height": p.get("height", 1),
    }


def _draw_circle(p: dict) -> dict:
    # Mirrors CommandHandler.draw_circle's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "radius": p.get("radius", 1),
        "center": [0.0, 0.0, 0.0],
    }


def _draw_line(p: dict) -> dict:
    # Mirrors CommandHandler.draw_line's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "start": [p.get("start_x", 0), p.get("start_y", 0)],
        "end": [p.get("end_x", 1), p.get("end_y", 1)],
    }


def _extrude(p: dict) -> dict:
    # Mirrors CommandHandler.extrude's return shape.
    return {
        "feature_name": "Feature_mock",
        "bodies": ["Body_mock"],
        "body_name": "Body_mock",
        "height": p.get("height", 1),
        "operation": p.get("operation", "new_body"),
        "direction": p.get("direction", None),
    }


def _revolve(p: dict) -> dict:
    return {
        "feature_name": "Feature_mock",
        "bodies": ["Body_mock_revolve"],
        "body_name": "Body_mock_revolve",
        "angle": p.get("angle", 360),
        "operation": p.get("operation", "new_body"),
    }


def _fillet(p: dict) -> dict:
    # Mirrors CommandHandler.fillet's return shape.
    return {
        "feature_name": "Fillet1",
        "radius": p.get("radius", 0.1),
        "edges_count": 1,
        "convexity": p.get("convexity", "any"),
    }


def _chamfer(p: dict) -> dict:
    # Mirrors CommandHandler.chamfer's return shape.
    return {
        "feature_name": "Chamfer1",
        "distance": p.get("distance", 0.1),
        "edges_count": 1,
        "convexity": p.get("convexity", "any"),
    }


def _shell(p: dict) -> dict:
    # Mirrors CommandHandler.shell's return shape.
    return {
        "feature_name": "Shell1",
        "thickness": p.get("thickness", 0.1),
        "faces_removed": 1,
        "removed_face_z": [0.0],
    }


def _mirror(p: dict) -> dict:
    # Mirrors CommandHandler.mirror's return shape.
    return {
        "feature_name": "Mirror1",
        "mirror_plane": p.get("mirror_plane", "yz"),
        "new_bodies": ["Body_mock_copy"],
        "new_body_name": "Body1_mirrored",
    }


def _delete_body(p: dict) -> dict:
    # Mirrors CommandHandler.delete_body's return shape.
    return {
        "deleted": True,
        "body": p.get("body_name", "Body1"),
        "volume": 1.0,
        "method": "base_feature_edit",
    }


def _rename_body(p: dict) -> dict:
    return {
        "renamed": True,
        "old_name": p.get("body_name", "Body1"),
        "new_name": p.get("new_name", "RenamedBody"),
    }


def _move_body(p: dict) -> dict:
    # Mirrors CommandHandler.move_body's return shape.
    result = {
        "feature_name": "Move1",
        "body": p.get("body_name", "Body1"),
        "translation": [p.get("x", 0), p.get("y", 0), p.get("z", 0)],
    }
    if p.get("angle"):
        result["rotation"] = {
            "angle": p["angle"],
            "axis": p.get("axis", "z"),
            "pivot": [p.get("pivot_x", 0), p.get("pivot_y", 0), p.get("pivot_z", 0)],
        }
    return result


def _export_stl(p: dict) -> dict:
    # Mirrors CommandHandler.export_stl's return shape.
    name = p.get("body_name", "Body1")
    path = p.get("file_path", f"~/Desktop/{name}.stl")
    return {"exported": True, "body": name, "file_path": path}


def _boolean_operation(p: dict) -> dict:
    # Mirrors CommandHandler.boolean_operation's return shape.
    return {
        "feature_name": "BooleanOperation1",
        "operation": p.get("operation", "join"),
        "target": p.get("target_body", "Body1"),
        "tool": p.get("tool_body", "Body2"),
    }


def _delete_all(p: dict) -> dict:
    # Mirrors CommandHandler.delete_all's return shape.
    return {
        "deleted": True,
        "remaining": None,
        "errors": [],
    }


def _undo(_p: dict) -> dict:
    return {
        "undone": True,
        "verified": True,
        "design_type": 1,
        "timeline_before": 8,
        "timeline_after": 7,
    }


def _execute_code(p: dict) -> dict:
    return {"executed": True, "code": p.get("code", ""), "result": "None", "output": ""}


# ── design type safety ───────────────────────────────────────────────


def _get_design_type(_p: dict) -> dict:
    return {"design_type": "parametric", "design_type_id": 1}


def _set_design_type(p: dict) -> dict:
    dt = p.get("design_type", "parametric")
    return {"changed": True, "design_type": dt}


# ── new geometry tools ────────────────────────────────────────────────


def _sweep(p: dict) -> dict:
    return {
        "feature_name": "Feature_mock",
        "bodies": ["Body_mock_sweep"],
        "body_name": "Body_mock_sweep",
        "path_sketch_name": p.get("path_sketch_name", "PathSketch"),
        "operation": p.get("operation", "new_body"),
        "profile_tilt_deg": 0.0,
        "path_curves": 1,
        "path_length": 10.0,
    }


def _loft(p: dict) -> dict:
    # Mirrors CommandHandler.loft's return shape.
    return {
        "feature_name": "Feature_mock",
        "bodies": ["Body_mock_loft"],
        "body_name": "Body_mock_loft",
        "operation": p.get("operation", "new_body"),
        "profile_count": len(p.get("profile_sketch_names") or ["S1", "S2"]),
    }


def _create_polygon(p: dict) -> dict:
    # Mirrors CommandHandler.create_polygon's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "sides": p.get("sides", 6),
        "radius": p.get("radius", 1),
    }


def _draw_arc(p: dict) -> dict:
    # Mirrors CommandHandler.draw_arc's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "sweep_angle": p.get("sweep_angle", 90),
    }


def _create_hole(p: dict) -> dict:
    body = p.get("body_name") or f"Body{p.get('body_index', 0) + 1}"
    diameter = p.get("diameter", 0.5)
    return {
        "feature_name": "Hole_mock",
        "diameter": diameter,
        "depth": p.get("depth", 1),
        "actual_diameter": diameter,
        "cut_bodies": [body],
        "resolved_center": [p.get("center_x", 0), p.get("center_y", 0), 0.0],
    }


def _rectangular_pattern(p: dict) -> dict:
    # Mirrors CommandHandler.rectangular_pattern's return shape.
    return {
        "feature_name": "RectangularPattern1",
        "x_count": p.get("x_count", 1),
        "y_count": p.get("y_count", 1),
        "new_bodies": ["Body_mock_copy"],
    }


def _circular_pattern(p: dict) -> dict:
    return {
        "new_bodies": ["Body_mock_copy"],
        "feature_name": "CircularPattern1",
        "count": p.get("count", 3),
        "total_angle": p.get("total_angle", 360),
    }


# ── assembly tools ────────────────────────────────────────────────────


def _create_component(p: dict) -> dict:
    # Mirrors CommandHandler.create_component's return shape.
    return {
        "created": True,
        "name": p.get("name", None),
    }


def _add_joint(p: dict) -> dict:
    # Mirrors CommandHandler.add_joint's return shape.
    return {
        "created": True,
        "joint_type": p.get("joint_type", "rigid"),
    }


def _list_components(p: dict) -> dict:
    # Mirrors CommandHandler.list_components's return shape.
    return {
        "components": [
            {"name": "RootComponent", "bodies": ["Body1"]},
            {"name": "SubComponent1", "bodies": []},
        ],
        "count": 1,
    }


# ── export tools ──────────────────────────────────────────────────────


def _export_step(p: dict) -> dict:
    # Mirrors CommandHandler.export_step's return shape.
    name = p.get("body_name", "Body1")
    path = p.get("file_path", f"~/Desktop/{name}.step")
    return {"exported": True, "body": name, "file_path": path}


def _export_f3d(p: dict) -> dict:
    # Mirrors CommandHandler.export_f3d's return shape.
    path = p.get("file_path", "~/Desktop/MockDesign.f3d")
    return {"exported": True, "file_path": path}


def _export_view_sheet(p: dict) -> dict:
    views = p.get("views") or ["iso", "front", "top", "right"]
    size = p.get("image_size") or [1200, 900]
    out = p.get("output_dir", "~/Desktop/MockDesign_views_mock")
    title = p.get("title", "MockDesign")
    return {
        "html_path": f"{out}/view_sheet.html",
        "output_dir": out,
        "title": title,
        "image_size": list(size),
        "views": [{"view": v, "path": f"{out}/{v}.png"} for v in views],
    }


def _export(p: dict) -> dict:
    fmt = (p.get("format") or "").lower()
    path = p.get("file_path", "")
    if not fmt and path:
        fmt = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    name = p.get("body_name", "Body1")
    return {
        "exported": True,
        "format": fmt or "f3d",
        "body": name,
        "file_path": path or f"~/Desktop/{name}.{fmt or 'f3d'}",
    }


def _import_mesh(p: dict) -> dict:
    path = p.get("file_path", "/tmp/mesh.stl")
    units = p.get("units", "mm")
    component = p.get("component_name") or "RootComponent"
    return {
        "imported": True,
        "file_path": path,
        "mesh_name": "MeshBody_mock",
        "component": component,
        "units": units,
        "bounding_box": {
            "min": [0.0, 0.0, 0.0],
            "max": [10.0, 5.0, 2.0],
            "size": [10.0, 5.0, 2.0],
        },
    }


def _create_box_parametric(p: dict) -> dict:
    return {
        "created": True,
        "body_name": p.get("body_name") or "BoxParametric_mock",
        "feature_name": "Extrude_mock",
        "sketch_name": "Sketch_mock",
        "length": p.get("length", 1),
        "width": p.get("width", 1),
        "height": p.get("height", 1),
        "origin": [
            p.get("origin_x", 0),
            p.get("origin_y", 0),
            p.get("origin_z", 0),
        ],
        "plane": p.get("plane", "xy"),
        "component": p.get("component_name") or "RootComponent",
    }


# ── parameter tools ───────────────────────────────────────────────────


def _get_parameters(p: dict) -> dict:
    # Mirrors CommandHandler.get_parameters's return shape.
    return {
        "parameters": [
            {"name": "width", "value": 10.0, "unit": "mm", "comment": ""},
            {"name": "height", "value": 5.0, "unit": "mm", "comment": ""},
        ],
        "count": 1,
    }


def _create_parameter(p: dict) -> dict:
    value = p.get("value", 0)
    # The addon trims the unit and treats blank as unitless; mirror both so
    # mock and real modes agree. "unit" is required by the schema, so the
    # default only covers a caller that omitted it entirely.
    unit = ("mm" if p.get("unit") is None else p["unit"]).strip()
    return {
        "created": True,
        "name": p.get("name", "param1"),
        "value": value,
        "unit": unit,
        "expression": f"{value} {unit}" if unit else f"{value}",
    }


def _set_parameter(p: dict) -> dict:
    # The real handler reports the unit the target parameter already declares
    # and the expression Fusion stored. Mock mode holds no design, so it
    # cannot know either -- report null rather than invent "mm".
    return {
        "updated": True,
        "name": p.get("name", "param1"),
        "value": p.get("value", 0),
        "unit": None,
        "expression": None,
    }


def _delete_parameter(p: dict) -> dict:
    return {"name": p.get("name", "param1"), "deleted": True}


# ── sketch constraints & dimensions ───────────────────────────────────


def _add_constraint(p: dict) -> dict:
    # Mirrors CommandHandler.add_constraint's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "constraint_type": p.get("constraint_type", "coincident"),
    }


def _auto_constrain(p: dict) -> dict:
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "is_fully_constrained": True,
        "constraints_added": 4,
        "dimensions_added": 2,
        "entities_moved": 0,
        "result_option": p.get("result_option", 1),
    }


def _add_dimension(p: dict) -> dict:
    # Mirrors CommandHandler.add_dimension's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "dimension_type": p.get("dimension_type", "distance"),
        "value": p.get("value", 1.0),
    }


# ── construction geometry ─────────────────────────────────────────────


def _create_construction_plane(p: dict) -> dict:
    # Mirrors CommandHandler.create_construction_plane's return shape.
    return {
        "created": True,
        "name": None,
        "method": p.get("method", "offset"),
    }


def _create_construction_axis(p: dict) -> dict:
    # Mirrors CommandHandler.create_construction_axis's return shape.
    return {
        "created": True,
        "name": None,
        "method": p.get("method", "two_points"),
    }


# ── splines ───────────────────────────────────────────────────────────


def _draw_spline(p: dict) -> dict:
    # Mirrors CommandHandler.draw_spline's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "spline_type": p.get("spline_type", "fit_points"),
        "points_count": len(p.get("points") or [[0, 0], [1, 1]]),
    }


# ── sketch curve operations ──────────────────────────────────────────


def _offset_curve(p: dict) -> dict:
    # Mirrors CommandHandler.offset_curve's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "offset_distance": p.get("offset_distance", 0.5),
    }


def _trim_curve(p: dict) -> dict:
    # Mirrors CommandHandler.trim_curve's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "trimmed": True,
    }


def _extend_curve(p: dict) -> dict:
    # Mirrors CommandHandler.extend_curve's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "extended": True,
    }


# ── advanced features ─────────────────────────────────────────────────


def _create_thread(p: dict) -> dict:
    # Mirrors CommandHandler.create_thread's return shape.
    return {
        "feature_name": "Thread_mock",
        "thread_type": p.get("thread_type", "ISO Metric profile"),
        "designation": p.get("thread_designation", "M10x1.5"),
        "class": p.get("thread_class", "6g"),
        "internal": p.get("is_internal", False),
        "modeled": p.get("is_modeled", False),
        "face_index": p.get("face_index", None),
        "axis_distance": None,
        "diameter_before": None,
        "diameter_after": None,
    }


def _draft_faces(p: dict) -> dict:
    # Mirrors CommandHandler.draft_faces's return shape.
    return {
        "feature_name": "DraftFaces1",
        "angle": p.get("angle", 5),
    }


def _split_body(p: dict) -> dict:
    # Mirrors CommandHandler.split_body's return shape.
    return {
        "feature_name": "SplitBody1",
        "splitting_plane": p.get("splitting_plane", None),
    }


def _split_face(p: dict) -> dict:
    # Mirrors CommandHandler.split_face's return shape.
    return {
        "feature_name": "SplitFace1",
    }


def _offset_faces(p: dict) -> dict:
    # Mirrors CommandHandler.offset_faces's return shape.
    return {
        "feature_name": "OffsetFaces1",
        "distance": p.get("distance", 0.5),
    }


def _scale_body(p: dict) -> dict:
    # Mirrors CommandHandler.scale_body's return shape.
    return {
        "feature_name": "ScaleBody1",
        "scale": p.get("scale", 1.0),
    }


# ── direct primitives ────────────────────────────────────────────────


def _create_box(p: dict) -> dict:
    # Mirrors CommandHandler.create_box's return shape.
    return {
        "created": True,
        "body_name": "Box_mock",
        "length": p.get("length", 1),
        "width": p.get("width", 1),
        "height": p.get("height", 1),
    }


def _create_cylinder(p: dict) -> dict:
    # Mirrors CommandHandler.create_cylinder's return shape.
    return {
        "created": True,
        "body_name": "Cylinder_mock",
        "radius": p.get("radius", 1),
        "height": p.get("height", 1),
    }


def _create_sphere(p: dict) -> dict:
    # Mirrors CommandHandler.create_sphere's return shape.
    return {
        "created": True,
        "body_name": "Sphere_mock",
        "radius": p.get("radius", 1),
    }


def _create_torus(p: dict) -> dict:
    # Mirrors CommandHandler.create_torus's return shape.
    return {
        "created": True,
        "body_name": "Torus_mock",
        "major_radius": p.get("major_radius", 2),
        "minor_radius": p.get("minor_radius", 0.5),
    }


# ── assembly (extended) ──────────────────────────────────────────────


def _create_as_built_joint(p: dict) -> dict:
    # Mirrors CommandHandler.create_as_built_joint's return shape.
    return {
        "created": True,
        "joint_type": p.get("joint_type", "rigid"),
    }


def _create_rigid_group(p: dict) -> dict:
    # Mirrors CommandHandler.create_rigid_group's return shape.
    return {
        "created": True,
        "component_count": len(p.get("component_names") or ["A", "B"]),
    }


# ── inspection / analysis ────────────────────────────────────────────


def _measure_distance(p: dict) -> dict:
    # Mirrors CommandHandler.measure_distance's return shape.
    return {
        "distance": 2.54,
        "point_one": [0, 0, 0],
        "point_two": [2.54, 0, 0],
    }


def _measure_angle(_p: dict) -> dict:
    return {"angle_degrees": 90.0}


def _get_physical_properties(p: dict) -> dict:
    # Mirrors CommandHandler.get_physical_properties's return shape.
    return {
        "mass": 0.785,
        "volume": 1.0,
        "area": 6.0,
        "density": 0.00785,
        "center_of_mass": [0.5, 0.5, 0.5],
    }


def _create_section_analysis(p: dict) -> dict:
    # Mirrors CommandHandler.create_section_analysis's return shape.
    return {
        "created": True,
        "plane": p.get("plane", "yz"),
        "offset": p.get("offset", 0),
    }


def _check_interference(p: dict) -> dict:
    # Mirrors CommandHandler.check_interference's return shape.
    return {
        "interferences": [],
        "count": 1,
    }


def _compare_meshes(p: dict) -> dict:
    return {
        "mesh_a": p.get("mesh_name_a", "Mesh1"),
        "mesh_b": p.get("mesh_name_b", "Mesh2"),
        "node_count": 1200,
        "min_deviation": -0.004,
        "max_deviation": 0.006,
        "mean_abs_deviation": 0.001,
        "rms_deviation": 0.0015,
        "max_abs_deviation": 0.006,
        "units": "cm",
    }


def _create_ucs(p: dict) -> dict:
    name = p.get("name", "UCS1")
    return {
        "name": name,
        "origin": [p.get("x", 0), p.get("y", 0), p.get("z", 0)],
        "angles_deg": [
            p.get("angle_x", 0),
            p.get("angle_y", 0),
            p.get("angle_z", 0),
        ],
        "reference_sketch": f"UCS_{name}_ref",
    }


def _set_color(p: dict) -> dict:
    r, g, b = p.get("red", 255), p.get("green", 0), p.get("blue", 0)
    alpha = round(p.get("opacity", 1.0) * 255)
    return {
        "body": p.get("body_name", "Body1"),
        "color": [r, g, b],
        "opacity": p.get("opacity", 1.0),
        "appearance": f"MCP_{r}_{g}_{b}_{alpha}",
    }


# ── appearance ────────────────────────────────────────────────────────


def _set_appearance(p: dict) -> dict:
    # Mirrors CommandHandler.set_appearance's return shape.
    return {
        "applied": True,
        "target": p.get("target_name", "Body1"),
        "appearance": p.get("appearance_name", "Steel - Satin"),
    }


# ── project geometry ─────────────────────────────────────────────────


def _project_geometry(p: dict) -> dict:
    # Mirrors CommandHandler.project_geometry's return shape.
    return {
        "sketch": p.get("sketch_name", "Sketch1"),
        "source": p.get("source_name", "Body1"),
        "projected_curves": 4,
        "is_linked": bool(p.get("is_linked", True)),
    }


# ── timeline control ─────────────────────────────────────────────────


def _suppression_result(p: dict) -> dict:
    # Mirrors CommandHandler._set_suppressed's return shape.
    names = list(p.get("feature_names") or [])
    if p.get("feature_name"):
        names.insert(0, p["feature_name"])
    names = names or ["Feature1"]
    result = {"features": names, "bodies_appeared": [], "bodies_removed": []}
    if len(names) == 1:
        result["feature"] = names[0]
    return result


def _suppress_feature(p: dict) -> dict:
    return {"suppressed": True, **_suppression_result(p)}


def _unsuppress_feature(p: dict) -> dict:
    return {"unsuppressed": True, **_suppression_result(p)}


# ── surface operations ──────────────────────────────────────────────


def _patch_surface(p: dict) -> dict:
    # Mirrors CommandHandler.patch_surface's return shape.
    return {
        "feature_name": "PatchSurface1",
        "continuity": p.get("continuity", "connected"),
    }


def _stitch_surfaces(p: dict) -> dict:
    # Mirrors CommandHandler.stitch_surfaces's return shape.
    return {
        "feature_name": "StitchSurfaces1",
        "body_count": len(p.get("body_names") or ["S1", "S2"]),
    }


def _thicken_surface(p: dict) -> dict:
    # Mirrors CommandHandler.thicken_surface's return shape.
    return {
        "feature_name": "ThickenSurface1",
        "thickness": p.get("thickness", 0.1),
    }


def _ruled_surface(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Body1"),
        "edge_index": p.get("edge_index", 0),
        "distance": p.get("distance", 1.0),
        "result_body": "RuledSurface_mock",
    }


def _trim_surface(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "Surface1"),
        "tool_name": p.get("tool_name", "Tool1"),
        "trimmed": True,
    }


# ── sheet metal ─────────────────────────────────────────────────────


def _create_flange(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "SheetBody1"),
        "edge_index": p.get("edge_index", 0),
        "height": p.get("height", 1.0),
        "angle": p.get("angle", 90),
    }


def _create_bend(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "SheetBody1"),
        "angle": p.get("angle", 90),
        "bend_radius": p.get("bend_radius", 0.1),
    }


def _flat_pattern(p: dict) -> dict:
    # Mirrors CommandHandler.flat_pattern's return shape.
    return {
        "created": False,
        "body": p.get("body_name", "SheetBody1"),
        "message": "Component already has a flat pattern",
    }


def _unfold(p: dict) -> dict:
    return {
        "body_name": p.get("body_name", "SheetBody1"),
        "bends_unfolded": len(p.get("bend_indices", [0, 1])),
    }


# ── CAM / manufacturing ─────────────────────────────────────────────


def _cam_create_setup(p: dict) -> dict:
    return {
        "setup_name": p.get("name", "Setup1"),
        "body_name": p.get("body_name", "Body1"),
        "operation_type": p.get("operation_type", "milling"),
        "stock_mode": p.get("stock_mode", "relative_box"),
    }


def _cam_create_operation(p: dict) -> dict:
    result = {
        "setup_name": p.get("setup_name", "Setup1"),
        "operation_name": p.get("name", "Operation1"),
        "strategy": p.get("strategy", "2d_contour"),
        "tool_diameter": p.get("tool_diameter", 0.6),
    }
    if p.get("geometry_face_index") is not None:
        result["geometry_applied"] = {
            "body": "Body1",
            "face_index": p["geometry_face_index"],
            "edge_count": 4,
        }
    if p.get("tool_from_operation"):
        result["parameters_applied"] = {
            "tool": {
                "from_operation": p["tool_from_operation"],
                "description": "Ø6mm flat end mill",
                "diameter": "6mm",
            }
        }
    return result


def _cam_generate_toolpath(p: dict) -> dict:
    # Mirrors CommandHandler.cam_generate_toolpath's return shape.
    return {
        "generated": True,
        "scope": "operation",
        "operation": p.get("operation_name"),
    }


def _cam_post_process(p: dict) -> dict:
    # Mirrors CommandHandler.cam_post_process's return shape.
    setup = p.get("setup_name", "Setup1")
    return {
        "setup": setup,
        "post_processor": p.get("post_processor", "fanuc"),
        "output_folder": p.get("output_folder", "~/Desktop"),
        "units": p.get("output_units", "mm"),
        "program_name": p.get("program_name", setup),
    }


def _cam_list_setups(p: dict) -> dict:
    # Mirrors CommandHandler.cam_list_setups's return shape.
    return {
        "setups": [
            {"name": "Setup1", "operation_type": "milling", "operation_count": 2}
        ],
        "count": 1,
    }


def _cam_list_operations(p: dict) -> dict:
    # Mirrors CommandHandler.cam_list_operations's return shape.
    return {
        "setup": p.get("setup_name", "Setup1"),
        "operations": [
            {"name": "Face1", "strategy": "face", "has_toolpath": True},
            {"name": "2D Contour1", "strategy": "2d_contour", "has_toolpath": False},
        ],
        "count": 1,
    }


def _cam_get_operation_info(p: dict) -> dict:
    return {
        "setup_name": p.get("setup_name", "Setup1"),
        "operation_name": p.get("operation_name", "Face1"),
        "strategy": "face",
        "tool_diameter": 0.6,
        "stepdown": 0.1,
        "feed_rate": 100.0,
        "spindle_speed": 10000,
        "has_toolpath": True,
        "toolpath_valid": True,
    }


# ── perception (viewport render) ─────────────────────────────────────

# 1x1 transparent PNG, enough to exercise the image-content code path.
_MOCK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
    "EQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
)


def _render_view(p: dict) -> dict:
    return {
        "view": p.get("view", "current"),
        "width": int(p.get("width", 1024)),
        "height": int(p.get("height", 768)),
        "image_format": "png",
        "image_base64": _MOCK_PNG_B64,
        "bytes": len(_MOCK_PNG_B64),
    }


# ── default fallback ─────────────────────────────────────────────────


def _default_mock(p: dict) -> dict:
    return {"warning": "no mock handler for this command", "params_received": p}


# ── dispatch table ────────────────────────────────────────────────────


def _convert_to_sheet_metal(p: dict) -> dict:
    return {
        "converted": True,
        "body": p.get("body_name", "Body1"),
        "rule": p.get("rule_name") or "Steel",
    }


def _fold_sheet_metal(p: dict) -> dict:
    return {
        "feature_name": "Fold_mock",
        "bend_angle": p.get("bend_angle", 90),
        "line_index": p.get("line_index", 0),
    }


def _export_flat_pattern_dxf(p: dict) -> dict:
    return {
        "exported": True,
        "file_path": p.get("file_path") or "~/Desktop/Body1_planificado.dxf",
    }


_DISPATCH: dict[str, Any] = {
    "ping": _ping,
    "get_scene_info": _get_scene_info,
    "get_object_info": _get_object_info,
    "get_bounding_box": _get_bounding_box,
    "create_sketch": _create_sketch,
    "draw_rectangle": _draw_rectangle,
    "draw_circle": _draw_circle,
    "draw_line": _draw_line,
    "extrude": _extrude,
    "revolve": _revolve,
    "fillet": _fillet,
    "chamfer": _chamfer,
    "shell": _shell,
    "mirror": _mirror,
    "rename_body": _rename_body,
    "delete_body": _delete_body,
    "move_body": _move_body,
    "export_stl": _export_stl,
    "boolean_operation": _boolean_operation,
    "delete_all": _delete_all,
    "undo": _undo,
    "execute_code": _execute_code,
    "sweep": _sweep,
    "loft": _loft,
    "create_polygon": _create_polygon,
    "draw_arc": _draw_arc,
    "create_hole": _create_hole,
    "rectangular_pattern": _rectangular_pattern,
    "circular_pattern": _circular_pattern,
    "create_component": _create_component,
    "add_joint": _add_joint,
    "list_components": _list_components,
    "export_step": _export_step,
    "export_f3d": _export_f3d,
    "export_view_sheet": _export_view_sheet,
    "export": _export,
    "import_mesh": _import_mesh,
    "create_box_parametric": _create_box_parametric,
    "get_parameters": _get_parameters,
    "create_parameter": _create_parameter,
    "set_parameter": _set_parameter,
    "delete_parameter": _delete_parameter,
    # sketch constraints & dimensions
    "add_constraint": _add_constraint,
    "auto_constrain": _auto_constrain,
    "add_dimension": _add_dimension,
    # construction geometry
    "create_construction_plane": _create_construction_plane,
    "create_construction_axis": _create_construction_axis,
    # splines
    "draw_spline": _draw_spline,
    # sketch curve operations
    "offset_curve": _offset_curve,
    "trim_curve": _trim_curve,
    "extend_curve": _extend_curve,
    # advanced features
    "draft_faces": _draft_faces,
    "split_body": _split_body,
    "split_face": _split_face,
    "offset_faces": _offset_faces,
    "scale_body": _scale_body,
    # direct primitives
    "create_box": _create_box,
    "create_cylinder": _create_cylinder,
    "create_sphere": _create_sphere,
    "create_torus": _create_torus,
    # assembly (extended)
    "create_as_built_joint": _create_as_built_joint,
    "create_rigid_group": _create_rigid_group,
    # inspection / analysis
    "measure_distance": _measure_distance,
    "measure_angle": _measure_angle,
    "get_physical_properties": _get_physical_properties,
    "create_section_analysis": _create_section_analysis,
    "check_interference": _check_interference,
    "compare_meshes": _compare_meshes,
    "create_ucs": _create_ucs,
    "set_color": _set_color,
    # appearance
    "set_appearance": _set_appearance,
    # project geometry
    "project_geometry": _project_geometry,
    # timeline control
    "suppress_feature": _suppress_feature,
    "unsuppress_feature": _unsuppress_feature,
    # surface operations
    "patch_surface": _patch_surface,
    "stitch_surfaces": _stitch_surfaces,
    "thicken_surface": _thicken_surface,
    # sheet metal
    # CAM / manufacturing
    "cam_create_setup": _cam_create_setup,
    "cam_create_operation": _cam_create_operation,
    "cam_generate_toolpath": _cam_generate_toolpath,
    "cam_list_setups": _cam_list_setups,
    "cam_list_operations": _cam_list_operations,
    "cam_get_operation_info": _cam_get_operation_info,
    # design type safety
    "get_design_type": _get_design_type,
    "set_design_type": _set_design_type,
    # perception
    "render_view": _render_view,
    "create_thread": _create_thread,
    "flat_pattern": _flat_pattern,
    "cam_post_process": _cam_post_process,
    "convert_to_sheet_metal": _convert_to_sheet_metal,
    "fold_sheet_metal": _fold_sheet_metal,
    "export_flat_pattern_dxf": _export_flat_pattern_dxf,
}
