"""Tests for the tool registry."""

from fusion360_mcp.tools import TOOLS, get_tool_by_name, get_tool_list


def test_all_tools_have_required_keys():
    for t in TOOLS:
        assert "name" in t, f"Tool missing 'name': {t}"
        assert "title" in t, f"Tool {t['name']} missing 'title'"
        assert "description" in t, f"Tool {t['name']} missing 'description'"
        assert "inputSchema" in t, f"Tool {t['name']} missing 'inputSchema'"


def test_all_schemas_are_objects():
    for t in TOOLS:
        schema = t["inputSchema"]
        assert schema.get("type") == "object", (
            f"Tool {t['name']} schema type is not 'object'"
        )


def test_required_fields_exist_in_properties():
    """Every field listed in 'required' must also appear in 'properties'."""
    for t in TOOLS:
        schema = t["inputSchema"]
        required = schema.get("required", [])
        props = schema.get("properties", {})
        for field in required:
            assert field in props, (
                f"Tool {t['name']}: required field '{field}' "
                f"not in properties {list(props)}"
            )


def test_no_duplicate_tool_names():
    names = [t["name"] for t in TOOLS]
    assert len(names) == len(set(names)), (
        f"Duplicate tool names: {[n for n in names if names.count(n) > 1]}"
    )


def test_get_tool_list_returns_mcp_types():
    tools = get_tool_list()
    assert len(tools) == len(TOOLS)
    for tool in tools:
        assert hasattr(tool, "name")
        assert hasattr(tool, "inputSchema")


def test_get_tool_by_name_found():
    assert get_tool_by_name("ping") is not None
    assert get_tool_by_name("extrude") is not None


def test_get_tool_by_name_missing():
    assert get_tool_by_name("nonexistent_tool") is None


def test_expected_tools_present():
    """Verify the full set of commands we expect."""
    names = {t["name"] for t in TOOLS}
    expected = {
        # scene / query
        "get_scene_info",
        "get_object_info",
        "get_bounding_box",
        # sketch
        "create_sketch",
        "draw_rectangle",
        "draw_circle",
        "draw_line",
        # features
        "extrude",
        "revolve",
        "fillet",
        "chamfer",
        "shell",
        "mirror",
        # body ops
        "move_body",
        "export_stl",
        "boolean_operation",
        # scene control
        "delete_all",
        "undo",
        # code execution
        "execute_code",
        # health
        "ping",
        # new geometry
        "sweep",
        "loft",
        "create_polygon",
        "draw_arc",
        "create_hole",
        "rectangular_pattern",
        "circular_pattern",
        # assembly
        "create_component",
        "add_joint",
        "list_components",
        # export
        "export_step",
        "export_f3d",
        "export_view_sheet",
        "export",
        # import
        "import_mesh",
        # parameters
        "get_parameters",
        "create_parameter",
        "set_parameter",
        "delete_parameter",
        # sketch constraints & dimensions
        "add_constraint",
        "auto_constrain",
        "add_dimension",
        # construction geometry
        "create_construction_plane",
        "create_construction_axis",
        "create_ucs",
        # splines
        "draw_spline",
        # sketch curve operations
        "offset_curve",
        "trim_curve",
        "extend_curve",
        # advanced features
        "draft_faces",
        "split_body",
        "split_face",
        "offset_faces",
        "scale_body",
        # direct primitives
        "create_box",
        "create_cylinder",
        "create_sphere",
        "create_torus",
        "create_box_parametric",
        # assembly (extended)
        "create_as_built_joint",
        "create_rigid_group",
        # inspection / analysis
        "measure_distance",
        "measure_angle",
        "get_physical_properties",
        "create_section_analysis",
        "check_interference",
        "compare_meshes",
        # appearance
        "set_appearance",
        "set_color",
        # project geometry
        "project_geometry",
        # timeline control
        "suppress_feature",
        "unsuppress_feature",
        # surface operations
        "patch_surface",
        "stitch_surfaces",
        "thicken_surface",
        # sheet metal
        # CAM / manufacturing
        "cam_create_setup",
        "cam_create_operation",
        "cam_generate_toolpath",
        "cam_list_setups",
        "cam_list_operations",
        "cam_get_operation_info",
        # design type safety
        "get_design_type",
        "set_design_type",
        # utility
        "rename_body",
        "delete_body",
        # perception
        "render_view",
        # fork: rosca, CAM e chapa metalica
        "create_thread",
        "cam_post_process",
        "flat_pattern",
        "convert_to_sheet_metal",
        "fold_sheet_metal",
        "export_flat_pattern_dxf",
    }
    missing = expected - names
    assert not missing, f"Missing tools: {missing}"
    extra = names - expected
    assert not extra, f"Unexpected tools: {extra}"


def test_all_tools_have_annotations():
    """Every tool should have annotations after module load."""
    for t in TOOLS:
        ann = t.get("annotations")
        assert ann is not None, f"Tool {t['name']} missing annotations"
        for key in ("readOnlyHint", "destructiveHint", "idempotentHint"):
            assert key in ann, f"Tool {t['name']} missing annotation '{key}'"
            assert isinstance(ann[key], bool), f"Tool {t['name']}.{key} should be bool"


def test_property_types_are_valid():
    """Every property in every schema should have a valid JSON Schema type."""
    valid_types = {"string", "number", "integer", "boolean", "array", "object"}
    for t in TOOLS:
        props = t["inputSchema"].get("properties", {})
        for field, spec in props.items():
            if "type" in spec:
                assert spec["type"] in valid_types, (
                    f"Tool {t['name']}.{field}: invalid type '{spec['type']}'"
                )


def test_enum_fields_are_lists():
    """Every 'enum' in a property should be a non-empty list."""
    for t in TOOLS:
        props = t["inputSchema"].get("properties", {})
        for field, spec in props.items():
            if "enum" in spec:
                assert isinstance(spec["enum"], list), (
                    f"Tool {t['name']}.{field}: enum not a list"
                )
                assert len(spec["enum"]) > 0, f"Tool {t['name']}.{field}: enum is empty"


def test_minimum_less_than_maximum():
    """If both min and max are set, min should be < max."""
    for t in TOOLS:
        props = t["inputSchema"].get("properties", {})
        for field, spec in props.items():
            if "minimum" in spec and "maximum" in spec:
                assert spec["minimum"] < spec["maximum"], (
                    f"Tool {t['name']}.{field}: "
                    f"min ({spec['minimum']}) >= max ({spec['maximum']})"
                )


def test_descriptions_are_nonempty():
    """Every tool should have a non-empty description."""
    for t in TOOLS:
        assert len(t["description"].strip()) > 0, (
            f"Tool {t['name']} has empty description"
        )
        assert len(t["title"].strip()) > 0, f"Tool {t['name']} has empty title"


def test_tool_names_are_snake_case():
    """Tool names should be snake_case."""
    import re

    for t in TOOLS:
        assert re.match(r"^[a-z][a-z0-9_]*$", t["name"]), (
            f"Tool name '{t['name']}' is not snake_case"
        )


def test_get_tool_list_annotations_propagated():
    """MCP Tool objects should carry annotations."""
    tools = get_tool_list()
    for tool in tools:
        assert tool.annotations is not None, f"MCP Tool {tool.name} missing annotations"


def test_get_tool_by_name_returns_correct_tool():
    """get_tool_by_name should return the exact matching tool."""
    for t in TOOLS:
        found = get_tool_by_name(t["name"])
        assert found is t, f"get_tool_by_name('{t['name']}') returned wrong object"


def test_get_tool_by_name_edge_cases():
    assert get_tool_by_name("") is None
    assert get_tool_by_name("PING") is None  # case sensitive
    assert get_tool_by_name("ping ") is None  # trailing space


def test_shell_offers_stepped_rim_selection():
    """A stepped opening (valve cover over a chain case) needs every
    down-facing face, not only the one at the lowest Z."""
    props = get_tool_by_name("shell")["inputSchema"]["properties"]
    assert set(props["face_selection"]["enum"]) == {
        "top",
        "bottom",
        "up_facing",
        "down_facing",
    }
    assert "z_min" in props and "z_max" in props


def test_fillet_and_chamfer_filter_edges_by_position():
    for name in ("fillet", "chamfer"):
        props = get_tool_by_name(name)["inputSchema"]["properties"]
        for key in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max"):
            assert props[key]["type"] == "number", (name, key)


def test_fillet_and_chamfer_filter_edges_by_convexity():
    """Concave and convex edges in one set fail (ASM_BL_CANNOT_REORDER)."""
    for name in ("fillet", "chamfer"):
        prop = get_tool_by_name(name)["inputSchema"]["properties"]["convexity"]
        assert set(prop["enum"]) == {"any", "concave", "convex"}, name
        assert prop["default"] == "any", name


def test_sweep_path_defaults_to_the_whole_sketch():
    """A default of 0 made the sweep chain from the first curve only, and
    separately drawn line+arc+line never chained: 2 of 11 cm swept."""
    props = get_tool_by_name("sweep")["inputSchema"]["properties"]
    assert "default" not in props["path_curve_index"]


def test_execute_code_accepts_a_longer_wait():
    props = get_tool_by_name("execute_code")["inputSchema"]["properties"]
    assert props["timeout_s"]["maximum"] == 600


def test_create_thread_infers_internal():
    """No default for is_internal: a default of False turned every tapped
    hole into a rejected 'external' thread request."""
    props = get_tool_by_name("create_thread")["inputSchema"]["properties"]
    assert "default" not in props["is_internal"]
