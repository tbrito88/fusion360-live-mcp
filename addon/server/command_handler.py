"""
Fusion360 Command Handler

Executes commands using the Fusion 360 API.  Every method in this class
is called on the **main thread** (via EventBridge), so Fusion API access
is safe.
"""

import ast
import base64
import io
import math
import os
import tempfile
import time
import traceback
from contextlib import redirect_stdout

import adsk.cam
import adsk.core
import adsk.fusion

from . import get_logger
from . import hints as _hints
from . import hole_geometry as _hole_geom
from . import parameter_units as _param_units

log = get_logger("handler")


class CommandHandler:
    """Runs Fusion API operations.  Instantiated once; reused across requests."""

    def __init__(self):
        self.app = adsk.core.Application.get()
        self.ui = self.app.userInterface

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    _COMMANDS = None  # populated lazily

    # Canonical camera presets, (eye_dir, up_vec) in Fusion's Z-up world.
    # Shared by render_view and export_view_sheet.
    _VIEW_DIRS = {
        "iso": ((1.0, -1.0, 1.0), (0.0, 0.0, 1.0)),
        "iso_ne": ((1.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
        "iso_nw": ((-1.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
        "iso_sw": ((-1.0, -1.0, 1.0), (0.0, 0.0, 1.0)),
        "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
        "back": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
        "bottom": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
        "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        "left": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    }

    # Commands that can change body mass / bbox / body count.  Only these
    # get before/after snapshots so agents can sanity-check without a render.
    _MUTATION_COMMANDS = frozenset(
        {
            # feature ops
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
            # body ops
            "move_body",
            "delete_body",
            "boolean_operation",
            # primitives
            "create_box",
            "create_cylinder",
            "create_sphere",
            "create_torus",
            # surface / sheet metal (can produce / thicken bodies)
            "thicken_surface",
            "patch_surface",
            "stitch_surfaces",
            # scene-wide
            "delete_all",
            "undo",
            # parametric & agent-authored changes
            "set_parameter",
            "execute_code",
            # sketch constraint mutation
            "auto_constrain",
            # construction geometry / appearance
            "create_ucs",
            "set_color",
            "create_thread",
            "flat_pattern",
            "convert_to_sheet_metal",
            "fold_sheet_metal",
        }
    )

    def execute_command(self, command: dict) -> dict:
        """Route *command* to the correct handler; return a response dict."""
        if self._COMMANDS is None:
            self.__class__._COMMANDS = {
                # scene / query
                "get_scene_info": self.get_scene_info,
                "get_object_info": self.get_object_info,
                "get_bounding_box": self.get_bounding_box,
                "list_components": self.list_components,
                # sketch
                "create_sketch": self.create_sketch,
                "draw_rectangle": self.draw_rectangle,
                "draw_circle": self.draw_circle,
                "draw_line": self.draw_line,
                "draw_arc": self.draw_arc,
                "draw_spline": self.draw_spline,
                "create_polygon": self.create_polygon,
                "add_constraint": self.add_constraint,
                "auto_constrain": self.auto_constrain,
                "add_dimension": self.add_dimension,
                "offset_curve": self.offset_curve,
                "trim_curve": self.trim_curve,
                "extend_curve": self.extend_curve,
                "project_geometry": self.project_geometry,
                # features
                "extrude": self.extrude,
                "revolve": self.revolve,
                "sweep": self.sweep,
                "loft": self.loft,
                "fillet": self.fillet,
                "chamfer": self.chamfer,
                "shell": self.shell,
                "mirror": self.mirror,
                "create_hole": self.create_hole,
                "rectangular_pattern": self.rectangular_pattern,
                "circular_pattern": self.circular_pattern,
                "draft_faces": self.draft_faces,
                "split_body": self.split_body,
                "split_face": self.split_face,
                "offset_faces": self.offset_faces,
                "scale_body": self.scale_body,
                "suppress_feature": self.suppress_feature,
                "unsuppress_feature": self.unsuppress_feature,
                # body operations
                "move_body": self.move_body,
                "rename_body": self.rename_body,
                "delete_body": self.delete_body,
                "export_stl": self.export_stl,
                "export_step": self.export_step,
                "export_f3d": self.export_f3d,
                "export_view_sheet": self.export_view_sheet,
                "export": self.export,
                "import_mesh": self.import_mesh,
                "create_box_parametric": self.create_box_parametric,
                "boolean_operation": self.boolean_operation,
                "delete_all": self.delete_all,
                "undo": self.undo,
                # direct primitives
                "create_box": self.create_box,
                "create_cylinder": self.create_cylinder,
                "create_sphere": self.create_sphere,
                "create_torus": self.create_torus,
                # construction geometry
                "create_construction_plane": self.create_construction_plane,
                "create_construction_axis": self.create_construction_axis,
                "create_ucs": self.create_ucs,
                # assembly
                "create_component": self.create_component,
                "add_joint": self.add_joint,
                "create_as_built_joint": self.create_as_built_joint,
                "create_rigid_group": self.create_rigid_group,
                # inspection / analysis
                "measure_distance": self.measure_distance,
                "measure_angle": self.measure_angle,
                "get_physical_properties": self.get_physical_properties,
                "create_section_analysis": self.create_section_analysis,
                "check_interference": self.check_interference,
                "compare_meshes": self.compare_meshes,
                # appearance
                "set_appearance": self.set_appearance,
                "set_color": self.set_color,
                # parameters
                "get_parameters": self.get_parameters,
                "create_parameter": self.create_parameter,
                "set_parameter": self.set_parameter,
                "delete_parameter": self.delete_parameter,
                # surface operations
                "patch_surface": self.patch_surface,
                "stitch_surfaces": self.stitch_surfaces,
                "thicken_surface": self.thicken_surface,
                # sheet metal
                # code execution
                "execute_code": self.execute_code,
                # CAM
                "cam_list_setups": self.cam_list_setups,
                "cam_list_operations": self.cam_list_operations,
                "cam_get_operation_info": self.cam_get_operation_info,
                "cam_create_setup": self.cam_create_setup,
                "cam_create_operation": self.cam_create_operation,
                "cam_generate_toolpath": self.cam_generate_toolpath,
                # health
                "ping": self.ping,
                # design type safety
                "get_design_type": self.get_design_type,
                "set_design_type": self.set_design_type,
                # perception
                "render_view": self.render_view,
                # fork: rosca, CAM e chapa reabilitados/reescritos
                "create_thread": self.create_thread,
                "flat_pattern": self.flat_pattern,
                "cam_post_process": self.cam_post_process,
                "convert_to_sheet_metal": self.convert_to_sheet_metal,
                "fold_sheet_metal": self.fold_sheet_metal,
                "export_flat_pattern_dxf": self.export_flat_pattern_dxf,
            }

        cmd_type = command.get("type")
        # timeout_s is consumed by the bridge (how long the socket thread
        # waits), never by the handler itself.
        params = {
            k: v for k, v in command.get("params", {}).items() if k != "timeout_s"
        }

        handler = self._COMMANDS.get(cmd_type)
        if handler is None:
            # Infrastructure-level failure (not an application error) —
            # keep the legacy error envelope so the client raises.
            return {
                "status": "error",
                "error_kind": "UNKNOWN_COMMAND",
                "message": f"Unknown command: {cmd_type}",
            }

        is_mutation = cmd_type in self._MUTATION_COMMANDS
        snap_before = self._snapshot() if is_mutation else None

        try:
            t0 = time.monotonic()
            result = handler(**params)
            elapsed = time.monotonic() - t0
            log.debug("%s completed in %.3fs", cmd_type, elapsed)
        except Exception as exc:
            log.error("%s raised: %s", cmd_type, exc)
            error_kind, hint_list = _hints.classify(exc)
            return {
                "status": "success",
                "result": {
                    "ok": False,
                    "error_kind": error_kind,
                    "error_message": str(exc) or exc.__class__.__name__,
                    "hints": hint_list,
                    "traceback": traceback.format_exc(),
                },
            }

        if not isinstance(result, dict):
            result = {"value": result}
        result.setdefault("ok", True)

        if is_mutation and snap_before is not None:
            snap_after = self._snapshot()
            if snap_after is not None:
                result["deltas"] = self._compute_deltas(snap_before, snap_after)

        return {"status": "success", "result": result}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _design(self):
        """The active document's Design product.

        Prefer the explicit DesignProductType lookup: when the Manufacture
        (or another) workspace is active, ``app.activeProduct`` returns the
        CAM product instead of the design, which breaks every handler that
        assumes a fusion.Design.
        """
        doc = self.app.activeDocument
        if doc is None:
            # FIX (fork): when Fusion is started unattended (MCP auto-launch)
            # it sits on the start page with no document, and every tool
            # failed with "No active design". Only when NO document is open
            # at all, open a blank design; an open drawing/other doc still
            # raises below rather than being silently replaced.
            doc = self.app.documents.add(
                adsk.core.DocumentTypes.FusionDesignDocumentType
            )
        if doc is not None:
            try:
                design = doc.products.itemByProductType("DesignProductType")
                if design is not None:
                    return design
            except Exception:
                pass
        d = self.app.activeProduct
        if d is None or not hasattr(d, "rootComponent"):
            raise RuntimeError("No active design")
        return d

    def _root(self):
        return self._design().rootComponent

    def _last_sketch(self):
        root = self._root()
        if root.sketches.count == 0:
            raise RuntimeError("No sketch available — create one first")
        return root.sketches.item(root.sketches.count - 1)

    def _sketch_by_name(self, name: str):
        root = self._root()
        for i in range(root.sketches.count):
            s = root.sketches.item(i)
            if s.name == name:
                return s
        raise RuntimeError(f"Sketch '{name}' not found")

    def _body_by_name(self, name: str):
        root = self._root()
        # Search root bodies first
        for i in range(root.bRepBodies.count):
            b = root.bRepBodies.item(i)
            if b.name == name:
                return b
        # Search bodies inside components via occurrence proxies (assembly design)
        # Returns proxy body in root coordinate space for correct boolean ops
        for occ in root.allOccurrences:
            for i in range(occ.bRepBodies.count):
                b = occ.bRepBodies.item(i)
                if b.name == name:
                    return b
        raise RuntimeError(f"Body '{name}' not found")

    def _component_by_name(self, name: str):
        root = self._root()
        if root.name == name:
            return root
        for occ in root.allOccurrences:
            if occ.component.name == name:
                return occ.component
        raise RuntimeError(f"Component '{name}' not found")

    def _construction_plane(self, plane: str):
        root = self._root()
        m = {
            "xy": root.xYConstructionPlane,
            "yz": root.yZConstructionPlane,
            "xz": root.xZConstructionPlane,
        }
        p = m.get(plane)
        if p is None:
            raise RuntimeError(f"Unknown plane '{plane}' — use xy, yz, or xz")
        return p

    def _construction_axis(self, axis: str):
        root = self._root()
        m = {
            "x": root.xConstructionAxis,
            "y": root.yConstructionAxis,
            "z": root.zConstructionAxis,
        }
        a = m.get(axis)
        if a is None:
            raise RuntimeError(f"Unknown axis '{axis}' — use x, y, or z")
        return a

    @staticmethod
    def _operation_type(name: str):
        m = {
            "new_body": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
            "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
            "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
            "intersect": adsk.fusion.FeatureOperations.IntersectFeatureOperation,
        }
        t = m.get(name)
        if t is None:
            raise RuntimeError(
                f"Unknown operation '{name}' — use new_body/join/cut/intersect"
            )
        return t

    def _select_edges(self, body, selection: str):
        """Return an ObjectCollection of edges based on *selection*."""
        coll = adsk.core.ObjectCollection.create()
        bbox = body.boundingBox

        if selection == "all":
            for edge in body.edges:
                coll.add(edge)
        elif selection == "top":
            threshold = bbox.maxPoint.z - 0.001
            for edge in body.edges:
                mid = edge.pointOnEdge
                if mid.z > threshold:
                    coll.add(edge)
        elif selection == "bottom":
            threshold = bbox.minPoint.z + 0.001
            for edge in body.edges:
                mid = edge.pointOnEdge
                if mid.z < threshold:
                    coll.add(edge)
        elif selection == "vertical":
            # FIX (fork): the original test was "start and end vertex share
            # the same X and Y". A CLOSED edge -- the circular rim of a hole
            # -- has start and end at the SAME point, so it passed that test
            # and every hole rim was picked as "vertical". Found live: a
            # 12x8x0.6cm plate with 5 holes reported 14 "vertical" edges
            # (4 real corners + 5 holes x 2 rims) and filleting them removed
            # 25.5 of 53.4 cm3 -- a silently wrong part, returned as success.
            # Requiring a real span in Z is what separates a vertical edge
            # from a horizontal circle.
            for edge in body.edges:
                start, end = edge.startVertex, edge.endVertex
                if start is None or end is None:
                    continue  # closed edge: no distinct endpoints
                sp, ep = start.geometry, end.geometry
                if (
                    abs(sp.x - ep.x) < 0.001
                    and abs(sp.y - ep.y) < 0.001
                    and abs(sp.z - ep.z) > 0.001
                ):
                    coll.add(edge)
        else:
            raise RuntimeError(
                f"Unknown edge_selection '{selection}' — use all/top/bottom/vertical"
            )

        if coll.count == 0:
            raise RuntimeError(f"No edges matched selection '{selection}'")
        return coll

    def _select_faces(self, body, selection: str):
        """Return an ObjectCollection of faces based on *selection*."""
        coll = adsk.core.ObjectCollection.create()
        bbox = body.boundingBox

        if selection == "all":
            for face in body.faces:
                coll.add(face)
        elif selection == "top":
            threshold = bbox.maxPoint.z - 0.001
            for face in body.faces:
                if face.boundingBox.maxPoint.z > threshold:
                    coll.add(face)
        elif selection == "bottom":
            threshold = bbox.minPoint.z + 0.001
            for face in body.faces:
                if face.boundingBox.minPoint.z < threshold:
                    coll.add(face)
        elif selection == "vertical":
            for face in body.faces:
                # Check if face normal is roughly horizontal (vertical face)
                try:
                    _, normal_vec = face.evaluator.getNormalAtPoint(face.pointOnFace)
                    if abs(normal_vec.z) < 0.1:
                        coll.add(face)
                except Exception:
                    pass
        else:
            raise RuntimeError(
                f"Unknown face_selection '{selection}' — use all/top/bottom/vertical"
            )

        if coll.count == 0:
            raise RuntimeError(f"No faces matched selection '{selection}'")
        return coll

    # ------------------------------------------------------------------
    # Scene / Query
    # ------------------------------------------------------------------

    def get_scene_info(self):
        design = self._design()
        root = self._root()

        # FIX (fork): only iterated root.bRepBodies / root.sketches -- same
        # gap as get_object_info, check_interference, measure_angle and
        # export_step: anything inside a sub-component (the normal
        # create_component / assembly pattern) was invisible to this
        # "what's in the document" overview. Confirmed live: PlacaBase, a
        # body inside the "Base" component, was completely absent from
        # get_scene_info's bodies list while every root-level body showed
        # up fine -- and PlacaBase demonstrably existed (get_object_info and
        # measure_angle both found it moments earlier). Now also walks
        # root.allOccurrences, same as the other fixed handlers.
        bodies = []
        for b in root.bRepBodies:
            bodies.append(
                {
                    "name": b.name,
                    "volume": b.volume,
                    "area": b.area,
                    "material": b.material.name if b.material else None,
                    "is_visible": b.isVisible,
                    "component": root.name,
                }
            )
        for occ in root.allOccurrences:
            for b in occ.component.bRepBodies:
                bodies.append(
                    {
                        "name": b.name,
                        "volume": b.volume,
                        "area": b.area,
                        "material": b.material.name if b.material else None,
                        "is_visible": b.isVisible,
                        "component": occ.component.name,
                    }
                )

        sketches = []
        for s in root.sketches:
            sketches.append(
                {
                    "name": s.name,
                    "profile_count": s.profiles.count,
                    "is_visible": s.isVisible,
                }
            )
        for occ in root.allOccurrences:
            for s in occ.component.sketches:
                sketches.append(
                    {
                        "name": s.name,
                        "profile_count": s.profiles.count,
                        "is_visible": s.isVisible,
                    }
                )

        return {
            "design_name": design.parentDocument.name,
            "design_type": design.productType,
            "bodies": bodies,
            "sketches": sketches,
            "bodies_count": len(bodies),
            "sketches_count": len(sketches),
            "features_count": root.features.count,
            "timeline_count": (
                design.timeline.count if hasattr(design, "timeline") else 0
            ),
            "camera": self._camera_info(),
        }

    def get_object_info(self, name: str):
        root = self._root()

        # FIX (fork): this only ever searched root.bRepBodies / root.sketches
        # -- a body or sketch inside a sub-component (created via
        # create_component, the normal assembly pattern) was never found,
        # always returning {"found": False} even for a real, valid name.
        # Confirmed live: get_bounding_box (which does traverse occurrences,
        # like _body_by_name elsewhere in this file) found "PlacaBase" fine
        # while this returned found:False for the identical name. Now
        # searches root.allOccurrences too, for both bodies and sketches.
        for b in root.bRepBodies:
            if b.name == name:
                return self._object_info_for_body(b)
        for occ in root.allOccurrences:
            for b in occ.component.bRepBodies:
                if b.name == name:
                    return self._object_info_for_body(b)

        for s in root.sketches:
            if s.name == name:
                return self._object_info_for_sketch(s)
        for occ in root.allOccurrences:
            for s in occ.component.sketches:
                if s.name == name:
                    return self._object_info_for_sketch(s)

        return {"found": False, "name": name}

    def _object_info_for_body(self, b):
        return {
            "found": True,
            "type": "body",
            "name": b.name,
            "volume": b.volume,
            "area": b.area,
            "material": b.material.name if b.material else None,
            "is_visible": b.isVisible,
            "faces_count": b.faces.count,
            "edges_count": b.edges.count,
            "vertices_count": b.vertices.count,
            "bounding_box": self._bbox_dict(b.boundingBox),
        }

    def _object_info_for_sketch(self, s):
        return {
            "found": True,
            "type": "sketch",
            "name": s.name,
            "is_visible": s.isVisible,
            "profile_count": s.profiles.count,
            "curve_count": s.sketchCurves.count,
        }

    def list_components(self):
        root = self._root()
        components = [{"name": root.name, "is_root": True}]
        for occ in root.allOccurrences:
            components.append(
                {
                    "name": occ.component.name,
                    "is_root": False,
                    "is_visible": occ.isVisible,
                }
            )
        return {"components": components, "count": len(components)}

    def get_bounding_box(self, name: str):
        """Axis-aligned bounding box for a body or component. Values in cm."""

        def _payload(obj_type, mn, mx):
            return {
                "found": True,
                "type": obj_type,
                "name": name,
                "min": mn,
                "max": mx,
                "size": [mx[i] - mn[i] for i in range(3)],
                "center": [(mn[i] + mx[i]) / 2 for i in range(3)],
            }

        # Try body first (covers root bodies + bodies inside components)
        try:
            body = self._body_by_name(name)
            bb = body.boundingBox
            return _payload(
                "body",
                [bb.minPoint.x, bb.minPoint.y, bb.minPoint.z],
                [bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z],
            )
        except RuntimeError:
            pass

        # Fall back to component: union bbox of all contained bodies
        try:
            comp = self._component_by_name(name)
        except RuntimeError:
            return {"found": False, "name": name}

        mn = [float("inf")] * 3
        mx = [float("-inf")] * 3

        def _extend(bodies):
            for i in range(bodies.count):
                bb = bodies.item(i).boundingBox
                lo = [bb.minPoint.x, bb.minPoint.y, bb.minPoint.z]
                hi = [bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z]
                for axis in range(3):
                    if lo[axis] < mn[axis]:
                        mn[axis] = lo[axis]
                    if hi[axis] > mx[axis]:
                        mx[axis] = hi[axis]

        _extend(comp.bRepBodies)
        for occ in comp.allOccurrences:
            _extend(occ.bRepBodies)

        if mn[0] == float("inf"):
            return {"found": True, "type": "component", "name": name, "empty": True}

        return _payload("component", mn, mx)

    # ------------------------------------------------------------------
    # Sketch
    # ------------------------------------------------------------------

    def create_sketch(self, plane: str = "xy", z_offset: float = None):
        root = self._root()

        if z_offset is not None and z_offset != 0:
            # Create an offset construction plane
            planes = root.constructionPlanes
            plane_input = planes.createInput()
            offset_val = adsk.core.ValueInput.createByReal(z_offset)
            plane_input.setByOffset(self._construction_plane(plane), offset_val)
            cp = planes.add(plane_input)
            sketch = root.sketches.add(cp)
        else:
            sketch = root.sketches.add(self._construction_plane(plane))

        return {"sketch_name": sketch.name, "plane": plane, "z_offset": z_offset}

    def draw_rectangle(
        self,
        width: float,
        height: float,
        origin_x: float = 0,
        origin_y: float = 0,
        origin_z: float = 0,
    ):
        sketch = self._last_sketch()
        p1 = adsk.core.Point3D.create(origin_x, origin_y, origin_z)
        p2 = adsk.core.Point3D.create(origin_x + width, origin_y + height, origin_z)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)
        return {"sketch": sketch.name, "width": width, "height": height}

    def draw_circle(
        self,
        radius: float,
        center_x: float = 0,
        center_y: float = 0,
        center_z: float = 0,
    ):
        sketch = self._last_sketch()
        c = adsk.core.Point3D.create(center_x, center_y, center_z)
        sketch.sketchCurves.sketchCircles.addByCenterRadius(c, radius)
        return {
            "sketch": sketch.name,
            "radius": radius,
            "center": [center_x, center_y, center_z],
        }

    def draw_line(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        start_z: float = 0,
        end_z: float = 0,
    ):
        sketch = self._last_sketch()
        sp = adsk.core.Point3D.create(start_x, start_y, start_z)
        ep = adsk.core.Point3D.create(end_x, end_y, end_z)
        sketch.sketchCurves.sketchLines.addByTwoPoints(sp, ep)
        return {
            "sketch": sketch.name,
            "start": [start_x, start_y, start_z],
            "end": [end_x, end_y, end_z],
        }

    def draw_arc(
        self,
        center_x: float,
        center_y: float,
        start_x: float,
        start_y: float,
        sweep_angle: float,
        center_z: float = 0,
        start_z: float = 0,
    ):
        sketch = self._last_sketch()
        center = adsk.core.Point3D.create(center_x, center_y, center_z)
        start = adsk.core.Point3D.create(start_x, start_y, start_z)
        sweep_rad = math.radians(sweep_angle)
        sketch.sketchCurves.sketchArcs.addByCenterStartSweep(center, start, sweep_rad)
        return {"sketch": sketch.name, "sweep_angle": sweep_angle}

    def draw_spline(self, spline_type: str, points: list, degree: int = 3):
        sketch = self._last_sketch()
        pts = adsk.core.ObjectCollection.create()
        for p in points:
            z = p[2] if len(p) > 2 else 0
            pts.add(adsk.core.Point3D.create(p[0], p[1], z))

        if spline_type == "fit_points":
            sketch.sketchCurves.sketchFittedSplines.add(pts)
        else:  # control_points
            sketch.sketchCurves.sketchControlPointSplines.add(pts, degree)
        return {
            "sketch": sketch.name,
            "spline_type": spline_type,
            "points_count": len(points),
        }

    def create_polygon(
        self,
        sides: int,
        radius: float,
        center_x: float = 0,
        center_y: float = 0,
        center_z: float = 0,
    ):
        sketch = self._last_sketch()
        # Draw inscribed polygon
        for i in range(sides):
            angle1 = 2 * math.pi * i / sides
            angle2 = 2 * math.pi * (i + 1) / sides
            p1 = adsk.core.Point3D.create(
                center_x + radius * math.cos(angle1),
                center_y + radius * math.sin(angle1),
                center_z,
            )
            p2 = adsk.core.Point3D.create(
                center_x + radius * math.cos(angle2),
                center_y + radius * math.sin(angle2),
                center_z,
            )
            sketch.sketchCurves.sketchLines.addByTwoPoints(p1, p2)
        return {"sketch": sketch.name, "sides": sides, "radius": radius}

    def add_constraint(
        self,
        constraint_type: str,
        entity_one: int = None,
        entity_two: int = None,
        symmetry_line: int = None,
        sketch_name: str = None,
    ):
        sketch = (
            self._sketch_by_name(sketch_name) if sketch_name else self._last_sketch()
        )
        constraints = sketch.geometricConstraints
        curves = list(sketch.sketchCurves)

        e1 = curves[entity_one] if entity_one is not None else None
        e2 = curves[entity_two] if entity_two is not None else None

        constraint_map = {
            "coincident": lambda: constraints.addCoincident(e1, e2),
            "parallel": lambda: constraints.addParallel(e1, e2),
            "perpendicular": lambda: constraints.addPerpendicular(e1, e2),
            "tangent": lambda: constraints.addTangent(e1, e2),
            "equal": lambda: constraints.addEqual(e1, e2),
            "fix": lambda: constraints.addFix(e1),
            "horizontal": lambda: constraints.addHorizontal(e1),
            "vertical": lambda: constraints.addVertical(e1),
            "concentric": lambda: constraints.addConcentric(e1, e2),
            "collinear": lambda: constraints.addCollinear(e1, e2),
            "smooth": lambda: constraints.addSmooth(e1, e2),
            "midpoint": lambda: constraints.addMidPoint(
                sketch.sketchPoints.item(entity_one), e2
            ),
            "symmetry": lambda: constraints.addSymmetry(e1, e2, curves[symmetry_line]),
        }

        if constraint_type not in constraint_map:
            raise RuntimeError(f"Unknown constraint type: {constraint_type}")

        constraint_map[constraint_type]()
        return {"sketch": sketch.name, "constraint_type": constraint_type}

    def auto_constrain(
        self,
        sketch_name: str = None,
        result_option: int = 1,
    ):
        """Auto-constrain a sketch using Fusion's AutoConstrain (Jan 2026+).

        result_option: 1 = thorough (default), 2 = fast,
        3 = may move geometry within tolerance.
        """
        sketch = (
            self._sketch_by_name(sketch_name) if sketch_name else self._last_sketch()
        )

        option_map = {
            1: adsk.fusion.AutoConstrainResultTypes.Option1AutoConstrainResultType,
            2: adsk.fusion.AutoConstrainResultTypes.Option2AutoConstrainResultType,
            3: adsk.fusion.AutoConstrainResultTypes.Option3AutoConstrainResultType,
        }
        option = option_map.get(result_option)
        if option is None:
            raise RuntimeError(
                f"Invalid result_option {result_option} — use 1 (thorough), "
                "2 (fast), or 3 (may adjust geometry within tolerance)."
            )

        ac_input = sketch.createAutoConstrainInput()
        ac_input.resultOption = option
        result = sketch.autoConstrain(ac_input)
        if result is None:
            # Option 3 returns null when the sketch is not eligible for
            # geometry adjustment.
            raise RuntimeError(
                "autoConstrain returned no result — the sketch is not "
                "eligible for geometry adjustment. Retry with "
                "result_option 1 or 2."
            )

        return {
            "sketch": sketch.name,
            "is_fully_constrained": result.isFullyConstrained,
            "constraints_added": len(result.addedConstraints),
            "dimensions_added": len(result.addedDimensions),
            "entities_moved": len(result.movedGeometry),
            "result_option": result_option,
        }

    def add_dimension(
        self,
        dimension_type: str,
        value: float,
        entity_one: int = None,
        entity_two: int = None,
        sketch_name: str = None,
    ):
        sketch = (
            self._sketch_by_name(sketch_name) if sketch_name else self._last_sketch()
        )
        dims = sketch.sketchDimensions
        curves = list(sketch.sketchCurves)

        e1 = curves[entity_one] if entity_one is not None else None
        e2 = curves[entity_two] if entity_two is not None else None
        text_pt = adsk.core.Point3D.create(0, 0, 0)

        if dimension_type == "distance":
            dim = dims.addDistanceDimension(
                e1.startSketchPoint,
                e2.startSketchPoint,
                adsk.fusion.DimensionOrientations.AlignedDimensionOrientation,
                text_pt,
            )
        elif dimension_type == "horizontal":
            dim = dims.addDistanceDimension(
                e1.startSketchPoint,
                e2.startSketchPoint,
                adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation,
                text_pt,
            )
        elif dimension_type == "vertical":
            dim = dims.addDistanceDimension(
                e1.startSketchPoint,
                e2.startSketchPoint,
                adsk.fusion.DimensionOrientations.VerticalDimensionOrientation,
                text_pt,
            )
        elif dimension_type == "angular":
            dim = dims.addAngularDimension(e1, e2, text_pt)
        elif dimension_type == "radial":
            dim = dims.addRadialDimension(e1, text_pt)
        elif dimension_type == "diameter":
            dim = dims.addDiameterDimension(e1, text_pt)
        else:
            raise RuntimeError(f"Unknown dimension type: {dimension_type}")

        dim.parameter.value = value
        return {"sketch": sketch.name, "dimension_type": dimension_type, "value": value}

    def offset_curve(
        self,
        curve_index: int,
        offset_distance: float,
        direction_x: float = 1,
        direction_y: float = 0,
        sketch_name: str = None,
    ):
        sketch = (
            self._sketch_by_name(sketch_name) if sketch_name else self._last_sketch()
        )
        curves = list(sketch.sketchCurves)
        curve = curves[curve_index]
        direction_pt = adsk.core.Point3D.create(direction_x, direction_y, 0)

        coll = adsk.core.ObjectCollection.create()
        coll.add(curve)
        sketch.offset(coll, direction_pt, offset_distance)
        return {"sketch": sketch.name, "offset_distance": offset_distance}

    def trim_curve(
        self, curve_index: int, point_x: float, point_y: float, sketch_name: str = None
    ):
        sketch = (
            self._sketch_by_name(sketch_name) if sketch_name else self._last_sketch()
        )
        curves = list(sketch.sketchCurves)
        curve = curves[curve_index]
        point = adsk.core.Point3D.create(point_x, point_y, 0)
        curve.trim(point)
        return {"sketch": sketch.name, "trimmed": True}

    def extend_curve(
        self, curve_index: int, point_x: float, point_y: float, sketch_name: str = None
    ):
        sketch = (
            self._sketch_by_name(sketch_name) if sketch_name else self._last_sketch()
        )
        curves = list(sketch.sketchCurves)
        curve = curves[curve_index]
        point = adsk.core.Point3D.create(point_x, point_y, 0)
        curve.extend(point)
        return {"sketch": sketch.name, "extended": True}

    def project_geometry(
        self, source_name: str, is_linked: bool = True, sketch_name: str = None
    ):
        sketch = (
            self._sketch_by_name(sketch_name) if sketch_name else self._last_sketch()
        )
        body = self._body_by_name(source_name)

        projected = []
        for edge in body.edges:
            proj = sketch.project(edge)
            projected.append(proj.count)

        return {
            "sketch": sketch.name,
            "source": source_name,
            "projected_curves": sum(projected),
        }

    # ------------------------------------------------------------------
    # Features
    # ------------------------------------------------------------------

    def extrude(
        self,
        height: float,
        profile_index: int = 0,
        operation: str = "new_body",
        direction: str = "positive",
        target_body_name: str = None,
    ):
        root = self._root()
        sketch = self._last_sketch()
        if sketch.profiles.count == 0:
            raise RuntimeError("No profiles in sketch")
        profile = sketch.profiles.item(profile_index)

        ext_feats = root.features.extrudeFeatures
        ext_input = ext_feats.createInput(profile, self._operation_type(operation))
        # FIX (fork): for cut/intersect, ExtrudeFeatureInput.participantBodies
        # defaults to "every body the tool geometrically touches" if left
        # unset -- confirmed live and costly: an unrelated revolve cut (see
        # revolve() below) sliced two completely unrelated bodies from an
        # earlier, unrelated part of the session just because they happened
        # to sit within its sweep radius. create_hole already guards this
        # the same way; extrude/revolve did not. target_body_name is
        # optional (existing callers that relied on the "cuts whatever it
        # touches" default keep working), but should be passed whenever the
        # document has more than the one body meant to be cut.
        if target_body_name and operation in ("cut", "intersect"):
            ext_input.participantBodies = [self._body_by_name(target_body_name)]
        dist = adsk.core.ValueInput.createByReal(height)
        if direction == "symmetric":
            ext_input.setSymmetricExtent(dist, True)
        else:
            # FIX (fusion360-mcp-server upstream bug): ExtrudeFeatureInput has
            # no setDistanceExtent() on Fusion builds 2704+ (only
            # HoleFeatureInput kept it). The replacement is setOneSideExtent()
            # with a DistanceExtentDefinition, per the current API.
            side = (adsk.fusion.ExtentDirections.NegativeExtentDirection
                    if direction == "negative"
                    else adsk.fusion.ExtentDirections.PositiveExtentDirection)
            ext_input.setOneSideExtent(
                adsk.fusion.DistanceExtentDefinition.create(dist), side
            )

        feat = ext_feats.add(ext_input)
        return {
            "feature_name": feat.name,
            "bodies": self._feature_body_names(feat),
            "body_name": (self._feature_body_names(feat) or [None])[0],
            "height": height,
            "operation": operation,
            "direction": direction,
        }

    def revolve(
        self,
        angle: float,
        profile_index: int = 0,
        axis_origin_x: float = 0,
        axis_origin_y: float = 0,
        axis_origin_z: float = 0,
        axis_direction_x: float = 1,
        axis_direction_y: float = 0,
        axis_direction_z: float = 0,
        operation: str = "new_body",
        target_body_name: str = None,
    ):
        root = self._root()
        sketch = self._last_sketch()
        if sketch.profiles.count == 0:
            raise RuntimeError("No profiles in sketch")
        profile = sketch.profiles.item(profile_index)

        # Determine axis entity first (required for createInput)
        # FIX (fork): an axis-aligned direction used to pick the root
        # construction axis THROUGH THE ORIGIN and silently drop
        # axis_origin. Confirmed live: a valve profile revolved about
        # "Z at (-19.7, 1.7)" came out as a 266 cm3 ring of radius 19.8
        # around the global Z axis. The construction axes are only correct
        # when the requested axis really passes through the origin.
        axis_entity = None
        at_origin = (
            abs(axis_origin_x) < 1e-9
            and abs(axis_origin_y) < 1e-9
            and abs(axis_origin_z) < 1e-9
        )
        is_x = abs(axis_direction_x) > 0.99 and abs(axis_direction_y) < 0.01
        is_y = abs(axis_direction_y) > 0.99 and abs(axis_direction_x) < 0.01
        is_z = abs(axis_direction_z) > 0.99 and abs(axis_direction_x) < 0.01
        if at_origin and is_x and abs(axis_direction_z) < 0.01:
            axis_entity = root.xConstructionAxis
        elif at_origin and is_y and abs(axis_direction_z) < 0.01:
            axis_entity = root.yConstructionAxis
        elif at_origin and is_z and abs(axis_direction_y) < 0.01:
            axis_entity = root.zConstructionAxis
        else:
            # Construction line in the sketch. FIX (fork): addByTwoPoints
            # takes SKETCH-space points; the model-space axis must be
            # converted, otherwise an xz/yz sketch (whose local axes are
            # rotated/flipped vs. model axes) puts the axis elsewhere.
            origin = sketch.modelToSketchSpace(
                adsk.core.Point3D.create(axis_origin_x, axis_origin_y, axis_origin_z)
            )
            end_pt = sketch.modelToSketchSpace(
                adsk.core.Point3D.create(
                    axis_origin_x + axis_direction_x * 10,
                    axis_origin_y + axis_direction_y * 10,
                    axis_origin_z + axis_direction_z * 10,
                )
            )
            line = sketch.sketchCurves.sketchLines.addByTwoPoints(origin, end_pt)
            line.isConstruction = True
            axis_entity = line
            # FIX (fork): adding a curve re-solves the sketch and
            # invalidates Profile objects fetched earlier -- revolve then
            # failed with "invalid profile(s)". Re-fetch after the edit.
            profile = sketch.profiles.item(profile_index)

        rev_feats = root.features.revolveFeatures
        rev_input = rev_feats.createInput(
            profile, axis_entity, self._operation_type(operation)
        )
        # FIX (fork): confirmed live -- a "cut" revolve with
        # participantBodies unset sliced through TWO unrelated bodies
        # (from an earlier, unrelated part of the same document) that
        # happened to sit within the revolve's sweep radius around the
        # rotation axis, in addition to the intended target. Neither body
        # was named in this call; RevolveFeatureInput.participantBodies
        # defaults to "every body the tool geometrically touches" when
        # left unset. Same fix pattern as extrude() above.
        if target_body_name and operation in ("cut", "intersect"):
            rev_input.participantBodies = [self._body_by_name(target_body_name)]

        angle_val = adsk.core.ValueInput.createByString(f"{angle} deg")
        rev_input.setAngleExtent(False, angle_val)

        feat = rev_feats.add(rev_input)
        return {
            "feature_name": feat.name,
            "bodies": self._feature_body_names(feat),
            "body_name": (self._feature_body_names(feat) or [None])[0],
            "angle": angle,
            "operation": operation,
        }

    def sweep(
        self,
        profile_index: int,
        path_sketch_name: str,
        path_curve_index: int = None,
        operation: str = "new_body",
        target_body_name: str = None,
    ):
        root = self._root()
        sketch = self._last_sketch()
        path_sketch = self._sketch_by_name(path_sketch_name)

        if sketch.profiles.count == 0:
            raise RuntimeError("No profiles in sketch")
        profile = sketch.profiles.item(profile_index)

        path_curves = [c for c in path_sketch.sketchCurves if not c.isConstruction]
        if not path_curves:
            raise RuntimeError(f"No path curves in sketch '{path_sketch_name}'")
        # FIX (fork): the path was createPath(curve_0) with automatic chaining,
        # which only follows curves sharing a SketchPoint. Curves drawn by
        # separate draw_line/draw_arc calls meet at the same coordinates but
        # have their own points, so the chain stopped at the first one and the
        # sweep silently used 2.0 of an 11.0 cm line+arc+line path (found
        # live: an intake hose came out as a short straight stub). Default
        # now: every non-construction curve of the path sketch, handed over
        # explicitly (Fusion accepts a geometrically connected set);
        # path_curve_index keeps the old "chain from this curve" behaviour.
        path = None
        if path_curve_index is None:
            coll = adsk.core.ObjectCollection.create()
            for c in path_curves:
                coll.add(c)
            try:
                path = root.features.createPath(coll, False)
            except Exception:
                path = None
        if path is None:
            path = root.features.createPath(path_curves[path_curve_index or 0])
        used = [path.item(i).entity for i in range(path.count)]
        path_length = sum(e.length for e in used)
        total_length = sum(c.length for c in path_curves)

        sweep_feats = root.features.sweepFeatures
        sweep_input = sweep_feats.createInput(
            profile, path, self._operation_type(operation)
        )
        # FIX (fork): same participantBodies gap as extrude/revolve (see
        # there) -- documented as a known remaining risk until a hollow
        # intake-manifold runner needed a sweep CUT limited to one body.
        if target_body_name and operation in ("cut", "intersect"):
            sweep_input.participantBodies = [self._body_by_name(target_body_name)]
        tilt = self._profile_path_tilt(sketch, used)
        feat = sweep_feats.add(sweep_input)
        result = {
            "feature_name": feat.name,
            "bodies": self._feature_body_names(feat),
            "body_name": (self._feature_body_names(feat) or [None])[0],
            "operation": operation,
            "profile_tilt_deg": tilt,
            "path_curves": len(used),
            "path_length": round(path_length, 6),
        }
        if len(used) < len(path_curves):
            result["path_warning"] = (
                f"The path uses {len(used)} of the {len(path_curves)} curves in "
                f"'{path_sketch_name}' ({path_length:.4f} of {total_length:.4f} "
                "cm): the others are not connected to it."
            )
        if tilt is not None and tilt > 1.0:
            result["warning"] = (
                f"Profile plane is {tilt:.2f} deg off perpendicular to the path "
                f"start: the swept cross-section is cos(tilt) = "
                f"{math.cos(math.radians(tilt)):.4f} of the drawn profile and "
                "the end faces are skewed. A fit-point spline picks its own end "
                "tangent; start the path with a straight segment normal to the "
                "profile."
            )
        return result

    @staticmethod
    def _profile_path_tilt(sketch, path_curves):
        """Angle (deg) between the profile sketch normal and the path tangent
        at the path end nearest to the profile plane (over all path curves).

        FIX (fork): the sweep reported nothing about this, and Fusion keeps
        the profile's angle to the path all along. Found live: a fit-point
        spline started 4.49 deg off the runner profile's normal, so every
        intake runner came out 0.3 % smaller in section -- detected only by
        checking the volume against Pappus -- and a PCV hose started 3.67 deg
        off its nipple, overlapping it.
        """
        try:
            m = sketch.transform
            o = sketch.origin
            n = adsk.core.Vector3D.create(
                m.getCell(0, 2), m.getCell(1, 2), m.getCell(2, 2)
            )
            n.normalize()
            best = None
            for curve in path_curves:
                ev = curve.worldGeometry.evaluator
                ok, p0, p1 = ev.getParameterExtents()
                for par in (p0, p1):
                    ok, pt = ev.getPointAtParameter(par)
                    d = abs(
                        (pt.x - o.x) * n.x + (pt.y - o.y) * n.y + (pt.z - o.z) * n.z
                    )
                    if best is None or d < best[0]:
                        best = (d, ev, par)
            ok, t = best[1].getTangent(best[2])
            t.normalize()
            c = min(1.0, abs(n.dotProduct(t)))
            return round(math.degrees(math.acos(c)), 3)
        except Exception:
            return None

    def loft(
        self,
        profile_sketch_names: list,
        operation: str = "new_body",
        target_body_name: str = None,
    ):
        root = self._root()
        loft_feats = root.features.loftFeatures
        loft_input = loft_feats.createInput(self._operation_type(operation))
        if target_body_name and operation in ("cut", "intersect"):
            loft_input.participantBodies = [self._body_by_name(target_body_name)]

        for sketch_name in profile_sketch_names:
            sketch = self._sketch_by_name(sketch_name)
            if sketch.profiles.count == 0:
                raise RuntimeError(f"No profiles in sketch '{sketch_name}'")
            loft_input.loftSections.add(sketch.profiles.item(0))

        feat = loft_feats.add(loft_input)
        return {
            "feature_name": feat.name,
            "bodies": self._feature_body_names(feat),
            "body_name": (self._feature_body_names(feat) or [None])[0],
            "operation": operation,
            "profile_count": len(profile_sketch_names),
        }

    @staticmethod
    def _feature_body_names(feat):
        """Names of the bodies a feature created/modified.

        FIX (fork): creation tools returned no body name, so every caller
        had to diff the scene or guess (confirmed live: a guessed
        "Corpo297" was really "Corpo622"). Reading feat.bodies after the
        feature exists gives the real names, including the target(s) of a
        cut -- which also exposes an unintended participant body.
        """
        try:
            return [b.name for b in feat.bodies]
        except Exception:
            return []

    @staticmethod
    def _filter_edges_z(edges, z_min=None, z_max=None):
        """Keep only edges lying entirely within [z_min, z_max].

        FIX (fork): "top"/"bottom" only reach the body's extreme Z, so an
        edge ring at an intermediate height (e.g. the front face of wheel
        spokes, recessed behind a raised hub) could not be selected at all.
        Found live building the BBS wheel: "top" picked the hub face (Z=-1.2)
        instead of the spoke windows (Z=-2.4).
        """
        return CommandHandler._filter_edges_box(edges, z_min=z_min, z_max=z_max)

    @staticmethod
    def _filter_edges_box(edges, **bounds):
        """Keep only edges lying entirely within the given x/y/z ranges.

        FIX (fork): only Z could be filtered, so on a body with internal
        detail "vertical" could not mean "the 4 outer corners": on the
        cylinder head it also took every vertical edge of the cam bed, the
        chain-case pocket and the gasket's chain slots. An X/Y window around
        the outer faces isolates them.
        """
        bounds = {k: v for k, v in bounds.items() if v is not None}
        if not bounds:
            return edges
        out = adsk.core.ObjectCollection.create()
        for edge in edges:
            bb = edge.boundingBox
            ok = True
            for axis in ("x", "y", "z"):
                lo = bounds.get(f"{axis}_min")
                hi = bounds.get(f"{axis}_max")
                if lo is not None and getattr(bb.minPoint, axis) < float(lo) - 1e-6:
                    ok = False
                if hi is not None and getattr(bb.maxPoint, axis) > float(hi) + 1e-6:
                    ok = False
            if ok:
                out.add(edge)
        if out.count == 0:
            desc = " ".join(f"{k}={v}" for k, v in sorted(bounds.items()))
            raise RuntimeError(
                f"No edges within {desc} "
                f"(of {edges.count} selected before the filter)"
            )
        return out

    @staticmethod
    def _edge_is_concave(edge, body, eps=0.01):
        """True for an inside corner, False for an outside one, None when the
        edge is tangent-continuous or not shared by two faces.

        With outward normals na, nb at the edge midpoint, the point
        p + eps*(na - nb) is outside a convex corner (q.na > 0) and inside a
        concave one (q.nb < 0), whatever the corner angle.
        """
        if edge.faces.count != 2:
            return None
        ok, p0, p1 = edge.evaluator.getParameterExtents()
        ok, p = edge.evaluator.getPointAtParameter((p0 + p1) / 2)
        if not ok:
            return None
        ok_a, na = edge.faces.item(0).evaluator.getNormalAtPoint(p)
        ok_b, nb = edge.faces.item(1).evaluator.getNormalAtPoint(p)
        if not (ok_a and ok_b):
            return None
        d = adsk.core.Vector3D.create(na.x - nb.x, na.y - nb.y, na.z - nb.z)
        if d.length < 1e-6:
            return None
        d.normalize()
        q = adsk.core.Point3D.create(
            p.x + eps * d.x, p.y + eps * d.y, p.z + eps * d.z
        )
        inside = adsk.fusion.PointContainment.PointInsidePointContainment
        return body.pointContainment(q) == inside

    @staticmethod
    def _filter_edges_convexity(edges, body, convexity="any"):
        """Keep only concave (inside-corner) or convex (outside-corner) edges.

        FIX (fork): a window of edges that mixes both kinds meeting at shared
        vertices makes Fusion fail with ASM_BL_CANNOT_REORDER. Found live
        rounding the lobed band of the engine block: the lobe/step edges
        (concave) and the step's outer edge (convex) were in the same window
        and the fillet failed; concave-only, the same 138 edges went through.
        """
        if convexity in (None, "any"):
            return edges
        if convexity not in ("concave", "convex"):
            raise ValueError("convexity must be 'any', 'concave' or 'convex'")
        want = convexity == "concave"
        out = adsk.core.ObjectCollection.create()
        for edge in edges:
            c = CommandHandler._edge_is_concave(edge, body)
            if c is not None and c == want:
                out.add(edge)
        if out.count == 0:
            raise RuntimeError(
                f"No {convexity} edges (of {edges.count} selected before the filter)"
            )
        return out

    def fillet(
        self,
        radius: float,
        body_name: str = None,
        body_index: int = 0,
        edge_selection: str = "all",
        z_min: float = None,
        z_max: float = None,
        x_min: float = None,
        x_max: float = None,
        y_min: float = None,
        y_max: float = None,
        convexity: str = "any",
    ):
        root = self._root()
        body = (
            self._body_by_name(body_name)
            if body_name
            else root.bRepBodies.item(body_index)
        )
        edges = self._filter_edges_box(
            self._select_edges(body, edge_selection),
            x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max,
            z_min=z_min, z_max=z_max,
        )
        edges = self._filter_edges_convexity(edges, body, convexity)

        fillets = root.features.filletFeatures
        inp = fillets.createInput()
        # FIX: FilletFeatureInput has no addConstantRadiusEdgeSet() of its own
        # on Fusion 2704+; the edge set goes through .edgeSetInputs instead.
        inp.edgeSetInputs.addConstantRadiusEdgeSet(
            edges, adsk.core.ValueInput.createByReal(radius), True
        )
        feat = fillets.add(inp)
        return {"feature_name": feat.name, "radius": radius, "edges_count": edges.count}

    def chamfer(
        self,
        distance: float,
        body_name: str = None,
        body_index: int = 0,
        edge_selection: str = "all",
        z_min: float = None,
        z_max: float = None,
        x_min: float = None,
        x_max: float = None,
        y_min: float = None,
        y_max: float = None,
        convexity: str = "any",
    ):
        root = self._root()
        body = (
            self._body_by_name(body_name)
            if body_name
            else root.bRepBodies.item(body_index)
        )
        edges = self._filter_edges_box(
            self._select_edges(body, edge_selection),
            x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max,
            z_min=z_min, z_max=z_max,
        )
        edges = self._filter_edges_convexity(edges, body, convexity)

        chamfers = root.features.chamferFeatures
        # FIX: ChamferFeatures.createInput(edges, isTangentChain) is GONE on
        # Fusion 2704+, replaced by createInput2() (no args) + edge sets added
        # afterward via .chamferEdgeSets. setToEqualDistance() is likewise gone
        # from ChamferFeatureInput; the equal-distance call moved to
        # ChamferEdgeSets.addEqualDistanceChamferEdgeSet(edges, distance,
        # isTangentChain).
        inp = chamfers.createInput2()
        inp.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
            edges, adsk.core.ValueInput.createByReal(distance), True
        )
        feat = chamfers.add(inp)
        return {
            "feature_name": feat.name,
            "distance": distance,
            "edges_count": edges.count,
        }

    @staticmethod
    def _z_facing(face, sign):
        """True if face is planar with its outward normal along sign*Z."""
        if face.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
            return False
        ok, n = face.evaluator.getNormalAtPoint(face.pointOnFace)
        return ok and n.z * sign > 0.999

    def shell(
        self,
        thickness: float,
        body_name: str = None,
        body_index: int = 0,
        face_selection: str = "top",
        z_min: float = None,
        z_max: float = None,
    ):
        """Hollow a body, removing the selected faces (the openings).

        FIX (fork): "top"/"bottom" took every face whose bounding box merely
        REACHED the extreme Z, i.e. also all the side walls. Confirmed live:
        shelling a 4x4x2 box with "top" removed 5 faces and left a 4.8 cm3
        bottom plate instead of a 12.348 cm3 open box. Now only planar faces
        facing +Z/-Z count; "up_facing"/"down_facing" take all of them at any
        height (a stepped rim), optionally limited by z_min/z_max.
        """
        root = self._root()
        body = (
            self._body_by_name(body_name)
            if body_name
            else root.bRepBodies.item(body_index)
        )

        faces = adsk.core.ObjectCollection.create()
        bbox = body.boundingBox
        modes = {
            "top": (1, bbox.maxPoint.z),
            "bottom": (-1, bbox.minPoint.z),
            "up_facing": (1, None),
            "down_facing": (-1, None),
        }
        if face_selection not in modes:
            raise RuntimeError(
                f"Unknown face_selection '{face_selection}' — use "
                "top/bottom/up_facing/down_facing"
            )
        sign, level = modes[face_selection]
        lo = float(z_min) if z_min is not None else -1e9
        hi = float(z_max) if z_max is not None else 1e9
        for face in body.faces:
            if not self._z_facing(face, sign):
                continue
            fz = face.boundingBox.minPoint.z
            if level is not None and abs(fz - level) > 1e-4:
                continue
            if lo - 1e-6 <= fz <= hi + 1e-6:
                faces.add(face)

        if faces.count == 0:
            raise RuntimeError(f"No faces matched '{face_selection}'")

        shells = root.features.shellFeatures
        # FIX: ShellFeatureInput has no facesToRemove on Fusion 2704+. The faces
        # to remove ARE the createInput entities -- passing the body instead
        # would produce a sealed hollow body with no opening.
        # read before shells.add(): the removed faces are dead afterwards
        removed_z = sorted({round(f.boundingBox.minPoint.z, 4) for f in faces})
        inp = shells.createInput(faces)
        inp.insideThickness = adsk.core.ValueInput.createByReal(thickness)
        feat = shells.add(inp)
        return {
            "feature_name": feat.name,
            "thickness": thickness,
            "faces_removed": faces.count,
            "removed_face_z": removed_z,
        }

    def mirror(self, mirror_plane: str, body_name: str = None, body_index: int = 0):
        root = self._root()
        body = (
            self._body_by_name(body_name)
            if body_name
            else root.bRepBodies.item(body_index)
        )

        entities = adsk.core.ObjectCollection.create()
        entities.add(body)

        mirrors = root.features.mirrorFeatures
        inp = mirrors.createInput(entities, self._construction_plane(mirror_plane))
        before = {b.name for b in root.bRepBodies}
        feat = mirrors.add(inp)
        new = sorted({b.name for b in root.bRepBodies} - before)
        return {
            "feature_name": feat.name,
            "mirror_plane": mirror_plane,
            "new_bodies": new,
            "new_body_name": new[0] if new else None,
        }

    def create_hole(
        self,
        diameter: float,
        depth: float,
        body_name: str = None,
        body_index: int = 0,
        face_selection: str = "top",
        center_x: float = 0,
        center_y: float = 0,
    ):
        root = self._root()
        body = (
            self._body_by_name(body_name)
            if body_name
            else root.bRepBodies.item(body_index)
        )

        # Find the target face.
        # Comparing bounding boxes is not enough: the side faces of a box reach
        # the body's max Z too, so the first "hit" is usually a vertical face.
        # Require a near-horizontal planar face that points up (or down).
        if face_selection not in ("top", "bottom"):
            raise RuntimeError(f"Unknown face_selection '{face_selection}'")
        want_up = face_selection == "top"

        target_face = None
        best_key = None
        for face in body.faces:
            if adsk.core.Plane.cast(face.geometry) is None:
                continue
            # Use the evaluator: it reports the face's outward normal, whereas
            # the underlying plane's normal ignores the face's orientation.
            ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
            if not ok or not _hole_geom.is_horizontal_face(normal.z, want_up):
                continue
            # Rank on the face's own extreme Z, not on an arbitrary point on
            # it: within the tilt tolerance the two are not the same.
            fbox = face.boundingBox
            edge_z = fbox.maxPoint.z if want_up else fbox.minPoint.z
            key = _hole_geom.face_rank_key(edge_z, face.area, want_up)
            if best_key is None or key > best_key:
                best_key, target_face = key, face

        if target_face is None:
            raise RuntimeError(
                f"No near-horizontal {face_selection}-facing planar face on "
                f"'{body.name}'"
            )

        # Place the hole centre. center_x / center_y are model-space XY, so the
        # caller does not have to know the sketch's own coordinate system. Solve
        # the face's plane for Z rather than reusing an arbitrary point on it.
        plane = adsk.core.Plane.cast(target_face.geometry)
        n, o = plane.normal, plane.origin
        center_z = _hole_geom.plane_z_at(
            (n.x, n.y, n.z), (o.x, o.y, o.z), center_x, center_y
        )
        sketch = root.sketches.add(target_face)
        sketch_pt = sketch.sketchPoints.add(
            sketch.modelToSketchSpace(
                adsk.core.Point3D.create(center_x, center_y, center_z)
            )
        )

        # createSimpleInput() takes the DIAMETER -- "A ValueInput object that
        # defines the diameter of the hole" -- not the radius.
        holes = root.features.holeFeatures
        hole_input = holes.createSimpleInput(
            adsk.core.ValueInput.createByReal(diameter)
        )
        hole_input.setPositionBySketchPoint(sketch_pt)
        hole_input.setDistanceExtent(adsk.core.ValueInput.createByReal(depth))
        # Without this the hole cuts every body it happens to intersect.
        # The property takes a plain list, not an ObjectCollection.
        hole_input.participantBodies = [body]

        feat = holes.add(hole_input)
        return {
            "feature_name": feat.name,
            "diameter": diameter,
            "depth": depth,
            "actual_diameter": feat.holeDiameter.value,
            "cut_bodies": [b.name for b in feat.bodies],
            # Where the request resolved to, not a measurement of the feature.
            "resolved_center": [center_x, center_y, center_z],
        }

    def rectangular_pattern(
        self,
        body_name: str,
        x_count: int = 1,
        x_spacing: float = 1.0,
        y_count: int = 1,
        y_spacing: float = 1.0,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        bodies = adsk.core.ObjectCollection.create()
        bodies.add(body)

        patterns = root.features.rectangularPatternFeatures
        inp = patterns.createInput(
            bodies,
            root.xConstructionAxis,
            adsk.core.ValueInput.createByReal(x_count),
            adsk.core.ValueInput.createByReal(x_spacing),
            adsk.fusion.PatternDistanceType.SpacingPatternDistanceType,
        )
        inp.setDirectionTwo(
            root.yConstructionAxis,
            adsk.core.ValueInput.createByReal(y_count),
            adsk.core.ValueInput.createByReal(y_spacing),
        )
        before = {b.name for b in root.bRepBodies}
        feat = patterns.add(inp)
        # FIX (fork): the copies' names were not returned (confirmed live:
        # 4 new bodies, no names in the result). feat.bodies also lists the
        # source body, so report the set difference instead.
        return {
            "feature_name": feat.name,
            "x_count": x_count,
            "y_count": y_count,
            "new_bodies": sorted({b.name for b in root.bRepBodies} - before),
        }

    def circular_pattern(
        self,
        body_name: str,
        count: int,
        axis: str = "z",
        total_angle: float = 360,
        feature_name: str = None,
    ):
        root = self._root()

        # FIX (fork): before feature_name existed, this only ever patterned
        # the whole BODY -- correct per its own description ("pattern a
        # body"), but useless for the common real case, a bolt circle: it
        # duplicated the ENTIRE part N times (each copy overlapping the
        # others in space, since the base shape is otherwise axisymmetric),
        # instead of producing one body with N holes. Confirmed live: 6
        # nearly-coincident whole-body copies, not 6 holes. Passing
        # feature_name patterns that FEATURE (e.g. a hole) instead --
        # Fusion's circularPatternFeatures.createInput() accepts a Features
        # collection as well as a Bodies collection, and only the Features
        # form keeps the result as one body.
        if feature_name:
            entities = adsk.core.ObjectCollection.create()
            found = None
            for i in range(root.features.count):
                f = root.features.item(i)
                if f.name == feature_name:
                    found = f
                    break
            if found is None:
                raise RuntimeError(
                    f"Feature '{feature_name}' not found in the timeline"
                )
            entities.add(found)
        else:
            body = self._body_by_name(body_name)
            entities = adsk.core.ObjectCollection.create()
            entities.add(body)

        patterns = root.features.circularPatternFeatures
        inp = patterns.createInput(entities, self._construction_axis(axis))
        inp.quantity = adsk.core.ValueInput.createByReal(count)
        inp.totalAngle = adsk.core.ValueInput.createByString(f"{total_angle} deg")
        before = {b.name for b in root.bRepBodies}
        feat = patterns.add(inp)
        return {
            "feature_name": feat.name,
            "count": count,
            "total_angle": total_angle,
            "new_bodies": sorted({b.name for b in root.bRepBodies} - before),
        }

    @staticmethod
    def _cylinder_face_near(body, x, y, z):
        """Cylindrical face whose axis passes closest to (x, y, z), among the
        faces whose axial extent contains the point's projection.

        FIX (fork): create_thread only took face_index. On a body with
        thousands of faces (a cylinder head) the index of "the tapped hole
        at this spot" is unknowable without code; picking it by a point on
        the hole axis is the natural selection.
        """
        best, best_d = None, None
        for i in range(body.faces.count):
            f = body.faces.item(i)
            g = f.geometry
            if not isinstance(g, adsk.core.Cylinder):
                continue
            o, a = g.origin, g.axis
            a.normalize()
            vx, vy, vz = x - o.x, y - o.y, z - o.z
            t = vx * a.x + vy * a.y + vz * a.z
            px, py, pz = vx - t * a.x, vy - t * a.y, vz - t * a.z
            d = math.sqrt(px * px + py * py + pz * pz)
            # the projection must fall within the face's own extent
            bb = f.boundingBox
            q = (o.x + t * a.x, o.y + t * a.y, o.z + t * a.z)
            tol = 1e-3
            if not (bb.minPoint.x - tol <= q[0] <= bb.maxPoint.x + tol
                    and bb.minPoint.y - tol <= q[1] <= bb.maxPoint.y + tol
                    and bb.minPoint.z - tol <= q[2] <= bb.maxPoint.z + tol):
                continue
            if best_d is None or d < best_d:
                best, best_d = i, d
        if best is None:
            raise RuntimeError(f"No cylindrical face around ({x}, {y}, {z})")
        return best, best_d

    @staticmethod
    def _cylinder_is_hole(face):
        """True if a cylindrical face bounds a hole (outward normal points
        toward the axis), False if it is a shaft/boss surface."""
        g = face.geometry
        p = face.pointOnFace
        ok, n = face.evaluator.getNormalAtPoint(p)
        o, a = g.origin, g.axis
        a.normalize()
        v = adsk.core.Vector3D.create(p.x - o.x, p.y - o.y, p.z - o.z)
        t = v.dotProduct(a)
        radial = adsk.core.Vector3D.create(
            v.x - t * a.x, v.y - t * a.y, v.z - t * a.z
        )
        return ok and n.dotProduct(radial) < 0

    def create_thread(
        self,
        body_name: str,
        face_index: int = None,
        is_internal: bool = None,
        thread_type: str = "ISO Metric profile",
        thread_designation: str = "M10x1.5",
        thread_class: str = "6g",
        is_modeled: bool = False,
        is_full_length: bool = True,
        thread_length: float = None,
        near_x: float = None,
        near_y: float = None,
        near_z: float = None,
    ):
        # FIX (fork): o original passava o ThreadDataQuery -- um objeto de
        # CONSULTA -- no lugar de um ThreadInfo, tentava atribuir threadType
        # nele, e ignorava thread_designation, thread_class e is_internal.
        # Mesmo rodando, nao faria a rosca pedida. Reescrito no padrao do
        # exemplo oficial da Autodesk (Python/Samples/Bolt/Bolt.py):
        # consulta -> createThreadInfo -> createInput(faces, info).
        root = self._root()
        body = self._body_by_name(body_name)
        axis_dist = None
        if face_index is None:
            if None in (near_x, near_y, near_z):
                raise RuntimeError(
                    "Pass face_index, or near_x/near_y/near_z on the hole axis"
                )
            face_index, axis_dist = self._cylinder_face_near(
                body, near_x, near_y, near_z
            )
        face = body.faces.item(face_index)
        diam_before = 2 * face.geometry.radius
        # FIX (fork): is_internal defaulted to False, so threading a tapped
        # hole without remembering the flag asked for an EXTERNAL thread on
        # a hole (found live: M6 6H on the head's cover-bolt holes was
        # rejected as "not valid for an external thread"). The face already
        # says which it is; infer it, and refuse a contradicting request.
        is_hole = self._cylinder_is_hole(face)
        if is_internal is None:
            is_internal = is_hole
        elif bool(is_internal) != is_hole:
            raise RuntimeError(
                f"Face {face_index} is {'a hole' if is_hole else 'a shaft'}"
                f" but is_internal={is_internal}. Omit is_internal to let it"
                " be inferred from the face."
            )

        threads = root.features.threadFeatures
        query = threads.threadDataQuery

        # Valida contra os dados de rosca instalados, com erro que diz o que
        # e valido -- em vez de uma falha opaca dentro do createThreadInfo.
        tipos = list(query.allThreadTypes)
        if thread_type not in tipos:
            raise RuntimeError(
                f"Thread type '{thread_type}' not found. "
                f"Available: {', '.join(tipos[:12])}..."
            )
        classes = list(query.allClasses(is_internal, thread_type, thread_designation))
        if not classes:
            raise RuntimeError(
                f"Designation '{thread_designation}' not found for '{thread_type}'"
            )
        if thread_class not in classes:
            lado = "internal" if is_internal else "external"
            raise RuntimeError(
                f"Class '{thread_class}' is not valid for an {lado} "
                f"{thread_designation} thread. Valid: {', '.join(classes)}"
            )

        info = threads.createThreadInfo(
            is_internal, thread_type, thread_designation, thread_class
        )
        faces = adsk.core.ObjectCollection.create()
        faces.add(face)

        inp = threads.createInput(faces, info)
        inp.isModeled = is_modeled
        inp.isFullLength = is_full_length
        if not is_full_length and thread_length:
            inp.threadLength = adsk.core.ValueInput.createByReal(thread_length)

        feat = threads.add(inp)
        # FIX (fork): Fusion resizes the threaded cylinder to the thread's
        # standard diameter (confirmed live: a 6.000 mm hole became 5.035 mm,
        # the M6 6H minor diameter; a 6.000 mm shank became 5.884 mm). That
        # silently changes the geometry -- and makes a bolt/hole pair report
        # an "interference" equal to the thread engagement. Report it.
        try:
            diam_after = 2 * feat.faces.item(0).geometry.radius
        except Exception:
            diam_after = None
        return {
            "feature_name": feat.name,
            "thread_type": thread_type,
            "designation": thread_designation,
            "class": thread_class,
            "internal": is_internal,
            "modeled": is_modeled,
            "face_index": face_index,
            "axis_distance": axis_dist,
            "diameter_before": diam_before,
            "diameter_after": diam_after,
        }

    def draft_faces(
        self,
        body_name: str,
        angle: float,
        face_selection: str = "vertical",
        pull_direction_plane: str = "xy",
        is_tangent_chain: bool = True,
    ):
        root = self._root()
        body = self._body_by_name(body_name)
        faces = self._select_faces(body, face_selection)

        drafts = root.features.draftFeatures
        # FIX: createInput() takes (inputFaces, plane, isTangentChain) on
        # Fusion 2704+ -- the angle moved out of it, into setSingleAngle().
        #
        # FIX (fork): DraftFeatures.createInput's first parameter is typed
        # std::vector<Ptr<BRepFace>> in the SWIG binding, not ObjectCollection
        # -- unlike almost every other feature API in this file (fillet's
        # edgeSetInputs, chain selections, ...), which all take
        # ObjectCollection. Passing the ObjectCollection that _select_faces
        # returns raised "Wrong number or type of arguments for overloaded
        # function 'DraftFeatures_createInput'" -- confirmed live, and
        # confirmed the fix live too: a plain Python list of the same faces
        # works. _select_faces itself is shared with other handlers that DO
        # want ObjectCollection, so the conversion happens here only.
        faces_list = [faces.item(i) for i in range(faces.count)]
        inp = drafts.createInput(
            faces_list,
            self._construction_plane(pull_direction_plane),
            is_tangent_chain,
        )
        inp.setSingleAngle(False, adsk.core.ValueInput.createByString(f"{angle} deg"))
        feat = drafts.add(inp)
        return {"feature_name": feat.name, "angle": angle}

    def split_body(
        self,
        body_name: str,
        splitting_plane: str = "xy",
        splitting_body: str = None,
        extend_tool: bool = True,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        splits = root.features.splitBodyFeatures
        if splitting_body:
            tool = self._body_by_name(splitting_body)
            inp = splits.createInput(body, tool, extend_tool)
        else:
            inp = splits.createInput(
                body, self._construction_plane(splitting_plane), extend_tool
            )
        feat = splits.add(inp)
        return {"feature_name": feat.name, "splitting_plane": splitting_plane}

    def split_face(
        self,
        body_name: str,
        face_indices: list = None,
        splitting_plane: str = "xy",
        extend_tool: bool = True,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        faces = adsk.core.ObjectCollection.create()
        if face_indices:
            for idx in face_indices:
                faces.add(body.faces.item(idx))
        else:
            for face in body.faces:
                faces.add(face)

        splits = root.features.splitFaceFeatures
        inp = splits.createInput(
            faces, self._construction_plane(splitting_plane), extend_tool
        )
        feat = splits.add(inp)
        return {"feature_name": feat.name}

    def offset_faces(
        self,
        body_name: str,
        distance: float,
        face_selection: str = "top",
        face_indices: list = None,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        if face_indices:
            faces = adsk.core.ObjectCollection.create()
            for idx in face_indices:
                faces.add(body.faces.item(idx))
        else:
            faces = self._select_faces(body, face_selection)

        offsets = root.features.offsetFeatures
        inp = offsets.createInput(
            faces,
            adsk.core.ValueInput.createByReal(distance),
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        )
        feat = offsets.add(inp)
        return {"feature_name": feat.name, "distance": distance}

    def scale_body(
        self,
        body_name: str,
        scale: float,
        scale_x: float = None,
        scale_y: float = None,
        scale_z: float = None,
        anchor_x: float = 0,
        anchor_y: float = 0,
        anchor_z: float = 0,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        bodies = adsk.core.ObjectCollection.create()
        bodies.add(body)

        anchor = adsk.core.Point3D.create(anchor_x, anchor_y, anchor_z)

        scales = root.features.scaleFeatures
        # FIX: createInput() takes exactly (inputEntities, point, scaleFactor)
        # on Fusion 2704+. Non-uniform scaling is no longer passed there --
        # it is applied afterwards through setToNonUniform().
        if scale_x is not None and scale_y is not None and scale_z is not None:
            inp = scales.createInput(
                bodies, anchor, adsk.core.ValueInput.createByReal(1.0)
            )
            inp.setToNonUniform(
                adsk.core.ValueInput.createByReal(scale_x),
                adsk.core.ValueInput.createByReal(scale_y),
                adsk.core.ValueInput.createByReal(scale_z),
            )
        else:
            inp = scales.createInput(
                bodies, anchor, adsk.core.ValueInput.createByReal(scale)
            )
        feat = scales.add(inp)
        return {"feature_name": feat.name, "scale": scale}

    def _set_suppressed(self, feature_name, feature_names, value: bool):
        """Suppress/unsuppress one or many timeline features.

        FIX (fork): each isSuppressed change recomputes everything after it
        in the timeline -- confirmed live, ~2.5 s per feature on a 220-item
        timeline, so a 24-feature cleanup blew the 30 s bridge timeout
        twice. For a batch, roll the marker back before the earliest
        feature, flip them all, and restore the marker: one recompute.
        """
        names = list(feature_names or [])
        if feature_name:
            names.insert(0, feature_name)
        if not names:
            raise RuntimeError("Pass feature_name or feature_names")
        design = self._design()
        tl = design.timeline
        index = {}
        for i in range(tl.count):
            e = tl.item(i).entity
            if e is not None:
                index.setdefault(e.name, i)
        missing = [n for n in names if n not in index]
        if missing:
            raise RuntimeError(f"Feature(s) not found in timeline: {missing}")

        root = self._root()
        before = {b.name for b in root.bRepBodies}
        marker = tl.markerPosition
        batch = len(names) > 1
        if batch:
            tl.markerPosition = min(index[n] for n in names)
        try:
            for n in names:
                tl.item(index[n]).isSuppressed = value
        finally:
            if batch:
                tl.markerPosition = marker
                # FIX (fork): restoring the marker does NOT recompute the
                # model -- confirmed live: the suppression flags were set but
                # the head kept its old volume (and the deltas said 0) until
                # design.computeAll() ran (+2110 cm3). One forced recompute
                # is still far cheaper than one per feature.
                design.computeAll()
        after = {b.name for b in root.bRepBodies}

        result = {
            "features": names,
            "bodies_appeared": sorted(after - before),
            "bodies_removed": sorted(before - after),
        }
        if len(names) == 1:
            result["feature"] = names[0]
        if value and result["bodies_appeared"]:
            # Confirmed live: suppressing a Combine cut/join brings its
            # consumed tool body back as a separate body.
            result["warning"] = (
                "Suppressing a Combine feature restores its tool body. "
                "Also suppress the feature that created that body (e.g. "
                "the preceding base feature) if it should stay gone."
            )
        return result

    def suppress_feature(self, feature_name: str = None, feature_names: list = None):
        result = self._set_suppressed(feature_name, feature_names, True)
        return {"suppressed": True, **result}

    def unsuppress_feature(self, feature_name: str = None, feature_names: list = None):
        result = self._set_suppressed(feature_name, feature_names, False)
        return {"unsuppressed": True, **result}

    # ------------------------------------------------------------------
    # Body Operations
    # ------------------------------------------------------------------

    def rename_body(self, body_name: str, new_name: str):
        body = self._body_by_name(body_name)
        old_name = body.name
        body.name = new_name
        # FIX (fork): returned the REQUESTED name. Fusion may store a
        # different one (it appends " (1)" when the name is taken -- seen
        # live on bodies created while removed bodies still held the name),
        # and every later call by that name then fails. Report what stuck.
        actual = body.name
        out = {"renamed": True, "old_name": old_name, "new_name": actual}
        if actual != new_name:
            out["warning"] = (
                f"Fusion stored the name as '{actual}', not '{new_name}' "
                "(the name is already in use)."
            )
        return out

    def delete_body(self, body_name: str):
        """Delete one named body.

        FIX (fork): there was no way to remove a single body -- only
        delete_all -- and `undo` cannot remove API-created features
        (confirmed live: it reports undone=False and the body stays).
        """
        body = self._body_by_name(body_name)
        volume = body.volume
        comp = body.parentComponent
        n_before = comp.bRepBodies.count
        # FIX (fork): body.deleteMe() returned True but the body STAYED --
        # confirmed live on a body produced by a Combine (join) feature in
        # a parametric design; only a body from a trailing base feature
        # actually went away. The parametric way is a Remove feature
        # (recorded in the timeline). Never report success without
        # checking the body really left its component.
        method = "remove_feature"
        try:
            comp.features.removeFeatures.add(body)
        except Exception:
            method = "deleteMe"
            body.deleteMe()
        if comp.bRepBodies.count != n_before - 1:
            raise RuntimeError(
                f"Body '{body_name}' is still present after {method} — "
                "Fusion did not remove it. Suppress the feature that "
                "creates it instead."
            )
        return {"deleted": True, "body": body_name, "volume": volume, "method": method}

    def move_body(
        self,
        body_name: str,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        angle: float = 0,
        axis: str = "z",
        pivot_x: float = 0,
        pivot_y: float = 0,
        pivot_z: float = 0,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        move_feats = root.features.moveFeatures
        bodies = adsk.core.ObjectCollection.create()
        bodies.add(body)

        # FIX (fork): move_body could only translate, so a part that must
        # pivot (e.g. a rocker arm swinging about its lash adjuster when the
        # cam opens the valve) had no tool. Optional rotation about an axis
        # parallel to x/y/z through (pivot_x, pivot_y, pivot_z), applied
        # BEFORE the (x, y, z) translation.
        transform = adsk.core.Matrix3D.create()
        if angle:
            axes = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}
            if axis not in axes:
                raise RuntimeError(f"axis must be x, y or z, got {axis!r}")
            transform.setToRotation(
                math.radians(float(angle)),
                adsk.core.Vector3D.create(*axes[axis]),
                adsk.core.Point3D.create(pivot_x, pivot_y, pivot_z),
            )
        t = transform.translation
        transform.translation = adsk.core.Vector3D.create(t.x + x, t.y + y, t.z + z)

        # FIX: MoveFeatures.createInput() is gone on Fusion 2704+. The current
        # API is createInput2(inputEntities), with the motion defined on the
        # input object afterwards.
        inp = move_feats.createInput2(bodies)
        inp.defineAsFreeMove(transform)
        feat = move_feats.add(inp)
        result = {
            "feature_name": feat.name,
            "body": body_name,
            "translation": [x, y, z],
        }
        if angle:
            result["rotation"] = {
                "angle": angle,
                "axis": axis,
                "pivot": [pivot_x, pivot_y, pivot_z],
            }
        return result

    def export_stl(self, body_name: str, file_path: str = None):
        body = self._body_by_name(body_name)

        if file_path is None:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            file_path = os.path.join(desktop, f"{body_name}.stl")

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        export_mgr = self._design().exportManager
        occ = body.assemblyContext  # None if body is at root

        if occ is None:
            stl_opts = export_mgr.createSTLExportOptions(body, file_path)
            stl_opts.meshRefinement = (
                adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
            )
            export_mgr.execute(stl_opts)
            return {"exported": True, "body": body_name, "file_path": file_path}

        # Body lives in a component occurrence: hide siblings so the
        # occurrence export only contains the target body. Identify
        # siblings by entityToken, not name, to handle same-name bodies.
        target_token = body.entityToken
        hidden = []
        for i in range(occ.bRepBodies.count):
            sibling = occ.bRepBodies.item(i)
            if sibling.entityToken != target_token and sibling.isVisible:
                sibling.isVisible = False
                hidden.append(sibling)

        try:
            stl_opts = export_mgr.createSTLExportOptions(occ, file_path)
            stl_opts.meshRefinement = (
                adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
            )
            export_mgr.execute(stl_opts)
        finally:
            for sibling in hidden:
                sibling.isVisible = True

        return {"exported": True, "body": body_name, "file_path": file_path}

    def export_step(self, body_name: str, file_path: str = None):
        body = self._body_by_name(body_name)

        if file_path is None:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            file_path = os.path.join(desktop, f"{body_name}.step")

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        export_mgr = self._design().exportManager
        occ = body.assemblyContext  # None if body is at root

        # FIX (fork): createSTEPExportOptions's geometry argument only
        # accepts a Component (confirmed against the runtime module's own
        # docstring: "Valid geometry for this is currently a Component
        # object") -- passing a BRepBody directly, as the root-level branch
        # did, always raised "3 : invlid argument geometry". Confirmed live.
        # This is exactly the common case for this project: a single-
        # component Part document with several bodies at the root, same gap
        # class as check_interference. Fixed the same way the occurrence
        # branch already worked around it for sub-components: hide sibling
        # bodies and export the containing component (root, here) instead
        # of the body directly.
        if occ is None:
            root = self._root()
            # FIX (fork): exporting `root` as the Component pulls in the
            # WHOLE design tree, not just root.bRepBodies -- so hiding only
            # root-level siblings (the original fix) still leaked every
            # sub-component's bodies into the file. Confirmed live: a STEP
            # exported for "Volante" (a root body) also contained
            # 'PlacaBase' (component 'Base') and 'TampaCorpo' (component
            # 'Tampa') as their own MANIFOLD_SOLID_BREP entries. Now also
            # hides bodies belonging to every other component in the
            # document, not just root.
            target_token = body.entityToken
            hidden = []
            for sibling in root.bRepBodies:
                if sibling.entityToken != target_token and sibling.isVisible:
                    sibling.isVisible = False
                    hidden.append(sibling)
            for other_occ in root.allOccurrences:
                for sibling in other_occ.component.bRepBodies:
                    if sibling.entityToken != target_token and sibling.isVisible:
                        sibling.isVisible = False
                        hidden.append(sibling)
            try:
                step_opts = export_mgr.createSTEPExportOptions(file_path, root)
                export_mgr.execute(step_opts)
            finally:
                for sibling in hidden:
                    sibling.isVisible = True
            return {"exported": True, "body": body_name, "file_path": file_path}

        # Body lives in a component occurrence: hide siblings so the
        # occurrence export only contains the target body. Identify
        # siblings by entityToken, not name, to handle same-name bodies.
        #
        # FIX (fork): passed the Occurrence itself to
        # createSTEPExportOptions, which -- same as the root-level branch
        # above -- only accepts a Component per the runtime module's own
        # docstring. Confirmed live: "3 : invlid argument geometry" for a
        # body inside an imported STEP's sub-component (an assembly
        # structure this branch had never actually been exercised against
        # before now -- every earlier export in this project happened to
        # be a root-level body). Fixed by passing occ.component.
        target_token = body.entityToken
        hidden = []
        for i in range(occ.bRepBodies.count):
            sibling = occ.bRepBodies.item(i)
            if sibling.entityToken != target_token and sibling.isVisible:
                sibling.isVisible = False
                hidden.append(sibling)

        try:
            step_opts = export_mgr.createSTEPExportOptions(file_path, occ.component)
            export_mgr.execute(step_opts)
        finally:
            for sibling in hidden:
                sibling.isVisible = True

        return {"exported": True, "body": body_name, "file_path": file_path}

    def export_f3d(self, file_path: str = None):
        design = self._design()
        doc_name = design.parentDocument.name

        if file_path is None:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            file_path = os.path.join(desktop, f"{doc_name}.f3d")

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        export_mgr = design.exportManager
        f3d_opts = export_mgr.createFusionArchiveExportOptions(file_path)
        export_mgr.execute(f3d_opts)

        return {"exported": True, "file_path": file_path}

    # ── view sheet ─────────────────────────────────────────────────────
    # Render canonical views (iso/front/top/right/...) as PNGs and emit
    # a self-contained HTML page suitable for print-to-PDF. Intended
    # audience: mechanical engineers who want a quick sense of the part.

    def _scene_center_and_radius(self):
        """Return (center, radius) covering all visible root bodies."""
        root = self._root()
        minp = [float("inf")] * 3
        maxp = [float("-inf")] * 3
        found = False

        def _grow(bb):
            nonlocal found
            for j, coord in enumerate(("x", "y", "z")):
                minp[j] = min(minp[j], getattr(bb.minPoint, coord))
                maxp[j] = max(maxp[j], getattr(bb.maxPoint, coord))
            found = True

        for i in range(root.bRepBodies.count):
            b = root.bRepBodies.item(i)
            if b.isVisible:
                _grow(b.boundingBox)
        for i in range(root.occurrences.count):
            occ = root.occurrences.item(i)
            if not occ.isVisible:
                continue
            for j in range(occ.bRepBodies.count):
                b = occ.bRepBodies.item(j)
                if b.isVisible:
                    _grow(b.boundingBox)

        if not found:
            return (0.0, 0.0, 0.0), 10.0
        center = tuple((minp[i] + maxp[i]) / 2 for i in range(3))
        span = max(maxp[i] - minp[i] for i in range(3))
        return center, max(span, 1.0)

    def _apply_view(self, view_name: str, center, radius: float):
        """Point the active viewport camera at *center* from *view_name*."""
        dir_vec, up_vec = self._VIEW_DIRS[view_name]
        length = math.sqrt(sum(c * c for c in dir_vec))
        dist = radius * 3.0  # give fit() headroom
        eye = tuple(center[i] + dir_vec[i] / length * dist for i in range(3))
        vp = self.app.activeViewport
        cam = vp.camera
        cam.isSmoothTransition = False
        cam.cameraType = adsk.core.CameraTypes.OrthographicCameraType
        cam.eye = adsk.core.Point3D.create(*eye)
        cam.target = adsk.core.Point3D.create(*center)
        cam.upVector = adsk.core.Vector3D.create(*up_vec)
        cam.isFitView = True
        vp.camera = cam
        vp.refresh()
        adsk.doEvents()

    def export_view_sheet(
        self,
        title: str = None,
        notes: str = "",
        views: list = None,
        image_size: list = None,
        output_dir: str = None,
    ):
        """Render canonical views as PNGs + a shareable HTML sheet.

        Args:
            title: heading on the sheet (default: document name).
            notes: free-form text rendered below the views (newlines
                preserved; HTML is escaped).
            views: ordered list of view names. Valid: iso, iso_ne,
                iso_nw, iso_sw, front, back, top, bottom, right, left.
                Default: ["iso", "front", "top", "right"].
            image_size: [width, height] in pixels (default [1200, 900]).
            output_dir: destination folder
                (default: ~/Desktop/<doc>_views_<timestamp>).
        """
        import base64
        import html
        import json as _json

        design = self._design()
        doc_name = design.parentDocument.name
        sheet_title = title or doc_name
        views = views or ["iso", "front", "top", "right"]
        image_size = image_size or [1200, 900]
        width, height = int(image_size[0]), int(image_size[1])

        unknown = [v for v in views if v not in self._VIEW_DIRS]
        if unknown:
            raise RuntimeError(
                f"Unknown views: {unknown}. Valid: {sorted(self._VIEW_DIRS)}"
            )

        if output_dir is None:
            ts = time.strftime("%Y%m%d_%H%M%S")
            output_dir = os.path.join(
                os.path.expanduser("~"),
                "Desktop",
                f"{doc_name}_views_{ts}",
            )
        os.makedirs(output_dir, exist_ok=True)

        vp = self.app.activeViewport
        orig = vp.camera
        orig_state = {
            "eye": (orig.eye.x, orig.eye.y, orig.eye.z),
            "target": (orig.target.x, orig.target.y, orig.target.z),
            "up": (orig.upVector.x, orig.upVector.y, orig.upVector.z),
            "type": orig.cameraType,
        }

        center, radius = self._scene_center_and_radius()

        rendered = []
        try:
            for view_name in views:
                self._apply_view(view_name, center, radius)
                png_path = os.path.join(output_dir, f"{view_name}.png")
                vp.saveAsImageFile(png_path, width, height)
                rendered.append({"view": view_name, "path": png_path})
        finally:
            cam = vp.camera
            cam.isSmoothTransition = False
            cam.cameraType = orig_state["type"]
            cam.eye = adsk.core.Point3D.create(*orig_state["eye"])
            cam.target = adsk.core.Point3D.create(*orig_state["target"])
            cam.upVector = adsk.core.Vector3D.create(*orig_state["up"])
            vp.camera = cam
            vp.refresh()

        # Build self-contained HTML with base64-embedded PNGs.
        figures = []
        for r in rendered:
            with open(r["path"], "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            label = r["view"].replace("_", " ").upper()
            figures.append(
                "<figure>"
                f'<img src="data:image/png;base64,{b64}" alt="{label}">'
                f"<figcaption>{label}</figcaption>"
                "</figure>"
            )

        notes_block = ""
        if notes:
            notes_block = (
                '<section class="notes"><h2>Notes</h2>'
                f"<pre>{html.escape(notes)}</pre></section>"
            )

        timestamp = time.strftime("%Y-%m-%d %H:%M")
        html_doc = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{html.escape(sheet_title)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
           sans-serif; color: #111; max-width: 1400px;
           margin: 2rem auto; padding: 0 2rem; }}
  header {{ border-bottom: 1px solid #d0d0d0; padding-bottom: .75rem;
            margin-bottom: 2rem; }}
  header h1 {{ margin: 0; font-weight: 500; font-size: 1.6rem; }}
  header .meta {{ color: #666; font-size: .85rem; margin-top: .25rem; }}
  .views {{ display: grid; grid-template-columns: 1fr 1fr;
            gap: 1.25rem; }}
  figure {{ margin: 0; border: 1px solid #e0e0e0; padding: .5rem;
            background: #fafafa; }}
  figure img {{ width: 100%; display: block; background: #fff; }}
  figcaption {{ text-align: center; font-size: .75rem; color: #555;
                margin-top: .35rem; letter-spacing: .15em; }}
  .notes {{ margin-top: 2rem; padding-top: 1rem;
            border-top: 1px solid #e0e0e0; }}
  .notes h2 {{ font-size: 1rem; font-weight: 500; margin: 0 0 .5rem; }}
  .notes pre {{ font-family: inherit; white-space: pre-wrap;
                margin: 0; color: #333; }}
  @media print {{
    body {{ max-width: none; margin: 0; padding: 1cm; }}
    .views {{ gap: .5cm; }}
    figure {{ break-inside: avoid; }}
  }}
</style>
</head><body>
<header>
  <h1>{html.escape(sheet_title)}</h1>
  <div class="meta">{html.escape(doc_name)} * {timestamp}</div>
</header>
<section class="views">{"".join(figures)}</section>
{notes_block}
</body></html>
"""
        html_path = os.path.join(output_dir, "view_sheet.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_doc)

        # Sidecar manifest - machine-readable record of what was emitted.
        manifest = {
            "title": sheet_title,
            "document": doc_name,
            "views": rendered,
            "html_path": html_path,
            "image_size": [width, height],
        }
        with open(os.path.join(output_dir, "manifest.json"), "w") as f:
            _json.dump(manifest, f, indent=2)

        return {
            "html_path": html_path,
            "output_dir": output_dir,
            "views": rendered,
            "title": sheet_title,
            "image_size": [width, height],
        }

    def export(self, format: str = None, body_name: str = None, file_path: str = None):
        """Unified export — dispatches to export_stl/export_step/export_f3d."""
        fmt = format.lower() if format else None
        if not fmt and file_path:
            fmt = os.path.splitext(file_path)[1].lstrip(".").lower()
        if not fmt:
            raise RuntimeError(
                "Specify format (stl/step/f3d) or file_path with extension"
            )

        if fmt == "stl":
            if not body_name:
                raise RuntimeError("body_name required for STL export")
            return self.export_stl(body_name, file_path)
        if fmt in ("step", "stp"):
            if not body_name:
                raise RuntimeError("body_name required for STEP export")
            return self.export_step(body_name, file_path)
        if fmt == "f3d":
            return self.export_f3d(file_path)

        raise RuntimeError(f"Unknown format: {fmt}. Expected: stl, step, f3d")

    def import_mesh(
        self, file_path: str, component_name: str = None, units: str = "mm"
    ):
        """Import mesh file (STL/OBJ/3MF) as mesh body. Values returned in cm."""
        if not os.path.exists(file_path):
            raise RuntimeError(f"Mesh file not found: {file_path}")

        target = (
            self._component_by_name(component_name) if component_name else self._root()
        )

        unit_map = {
            "mm": adsk.fusion.MeshUnits.MillimeterMeshUnit,
            "cm": adsk.fusion.MeshUnits.CentimeterMeshUnit,
            "m": adsk.fusion.MeshUnits.MeterMeshUnit,
            "in": adsk.fusion.MeshUnits.InchMeshUnit,
            "ft": adsk.fusion.MeshUnits.FootMeshUnit,
        }
        if units not in unit_map:
            raise RuntimeError(
                f"Unknown units '{units}'. Expected one of: {sorted(unit_map)}"
            )

        try:
            # MeshBodies.add(fullFilename, units) — the current API.
            # Returns a MeshBodyList (a file can contain several bodies).
            mesh_list = target.meshBodies.add(file_path, unit_map[units])
        except AttributeError:
            # Pre-2025 builds exposed this as addByFile returning one body.
            mesh_list = None
            mesh_body = target.meshBodies.addByFile(file_path, unit_map[units])
        if mesh_list is not None:
            if mesh_list.count == 0:
                raise RuntimeError(f"No mesh bodies imported from {file_path}")
            mesh_body = mesh_list.item(0)

        bb = mesh_body.boundingBox
        return {
            "imported": True,
            "file_path": file_path,
            "mesh_name": mesh_body.name,
            "component": target.name,
            "units": units,
            "bounding_box": {
                "min": [bb.minPoint.x, bb.minPoint.y, bb.minPoint.z],
                "max": [bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z],
                "size": [
                    bb.maxPoint.x - bb.minPoint.x,
                    bb.maxPoint.y - bb.minPoint.y,
                    bb.maxPoint.z - bb.minPoint.z,
                ],
            },
        }

    def boolean_operation(
        self, target_body: str, tool_body: str, operation: str = "join"
    ):
        root = self._root()
        target = self._body_by_name(target_body)
        tool = self._body_by_name(tool_body)

        op_map = {
            "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
            "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
            "intersect": adsk.fusion.FeatureOperations.IntersectFeatureOperation,
        }
        op = op_map.get(operation)
        if op is None:
            raise RuntimeError(
                f"Unknown boolean op '{operation}' — use join/cut/intersect"
            )

        # FIX (fork): a JOIN of two bodies that don't touch or overlap
        # silently discards the tool body instead of erroring or producing a
        # multi-lump result. Confirmed live, twice: 6 chained joins building
        # a handwheel (torus + hub + spokes + sphere) reported "OK" on every
        # call, with healthState 0 (healthy, no warning) and a real
        # Combine feature added to the timeline each time -- yet the target
        # ended up with EXACTLY the first body's volume, area, face count and
        # bounding box, as if nothing after it had ever been joined. Isolated
        # it to the very first join in that chain (hub to torus) being
        # between bodies with a genuine 5.7 cm gap -- not a coding mistake in
        # this handler, this is Fusion's own Combine behavior for
        # non-touching solids, reproduced with two plain boxes 8 cm apart:
        # the tool body vanishes from the document (consumed, as normal) but
        # its material never reaches the target. Whatever silently ate the
        # first join then also swallowed every FOLLOWING join in the chain,
        # even ones that genuinely overlapped -- so one disjoint pair
        # poisons the rest of a chained build. Two isolated joins between
        # clearly-overlapping bodies, including a second chained one, both
        # worked and matched hand-calculated volumes exactly -- confirming
        # the API call itself is correct and the trigger is specifically
        # "target and tool don't actually touch".
        #
        # Guarded here for "join" only: measure the real minimum distance
        # (not just a bounding-box overlap check, which can be wrong in
        # both directions) and refuse with a clear, actionable error before
        # silently losing material. "cut"/"intersect" of non-touching bodies
        # are legitimate no-ops (cutting nothing away; intersecting to
        # nothing) and Fusion already errors on a resulting empty body for
        # intersect, so they're left unguarded.
        if operation == "join":
            measure = self.app.measureManager
            dist_result = measure.measureMinimumDistance(target, tool)
            distance = dist_result.value if dist_result else None
            if distance is not None and distance > 1e-6:
                raise RuntimeError(
                    f"'{tool_body}' does not touch or overlap '{target_body}' "
                    f"(minimum distance {distance:.4f} cm). A join here would "
                    "silently discard the tool body's geometry instead of "
                    "merging it — confirmed live behavior, not a false "
                    "positive. Move the bodies until they touch/overlap "
                    "first, or use move_body to reposition."
                )

        root = self._root()
        combine_feats = root.features.combineFeatures
        tool_coll = adsk.core.ObjectCollection.create()
        tool_coll.add(tool)

        inp = combine_feats.createInput(target, tool_coll)
        inp.operation = op
        feat = combine_feats.add(inp)
        return {
            "feature_name": feat.name,
            "operation": operation,
            "target": target_body,
            "tool": tool_body,
        }

    def delete_all(self):
        """Clear the active design: unwind the timeline, then sweep leftovers.

        Returns counts of what was removed plus any per-item failures.  Raises
        if the design is *not* empty afterwards — a caller that believes this
        succeeded will happily build on a dirty document.
        """
        design = self._design()
        root = design.rootComponent
        deleted = {
            "timeline": 0,
            "joints": 0,
            "occurrences": 0,
            "construction": 0,
            "bodies": 0,
            "sketches": 0,
        }
        errors = []

        def _sweep(collection, stage, counter):
            """Delete every item of *collection*, newest-first."""
            for i in range(collection.count - 1, -1, -1):
                name = "?"
                try:
                    item = collection.item(i)
                    name = getattr(item, "name", "?")
                    item.deleteMe()
                    deleted[counter] += 1
                except Exception as exc:
                    errors.append(
                        {
                            "stage": stage,
                            "index": i,
                            "name": name,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

        # Parametric: unwind newest-first.  NOTE: TimelineObject has no
        # deleteMe() — that method lives on the *entity* it wraps.  Calling it
        # on the TimelineObject raises AttributeError on every item.
        tl = getattr(design, "timeline", None)
        if tl is not None and tl.count > 0:
            for i in range(tl.count - 1, -1, -1):
                name = "?"
                try:
                    item = tl.item(i)
                    name = item.name
                    entity = item.entity
                    if entity is None:
                        errors.append(
                            {
                                "stage": "timeline",
                                "index": i,
                                "name": name,
                                "error": "timeline item exposes no entity",
                            }
                        )
                        continue
                    entity.deleteMe()
                    deleted["timeline"] += 1
                except Exception as exc:
                    errors.append(
                        {
                            "stage": "timeline",
                            "index": i,
                            "name": name,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

        # Direct mode has no timeline; the sweeps below also catch anything
        # the timeline pass could not remove.  Joints go before occurrences
        # because they reference them.
        _sweep(root.rigidGroups, "rigid_group", "joints")
        _sweep(root.asBuiltJoints, "as_built_joint", "joints")
        _sweep(root.joints, "joint", "joints")
        # Deleting an occurrence removes the component it references,
        # including its bodies and sketches.
        _sweep(root.occurrences, "occurrence", "occurrences")
        _sweep(root.constructionPlanes, "construction_plane", "construction")
        _sweep(root.constructionAxes, "construction_axis", "construction")
        _sweep(root.constructionPoints, "construction_point", "construction")

        for i in range(root.bRepBodies.count - 1, -1, -1):
            name = "?"
            try:
                body = root.bRepBodies.item(i)
                name = body.name
                body.deleteMe()
                deleted["bodies"] += 1
            except Exception as exc:
                errors.append(
                    {
                        "stage": "body",
                        "index": i,
                        "name": name,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        for i in range(root.sketches.count - 1, -1, -1):
            name = "?"
            try:
                sk = root.sketches.item(i)
                name = sk.name
                sk.deleteMe()
                deleted["sketches"] += 1
            except Exception as exc:
                errors.append(
                    {
                        "stage": "sketch",
                        "index": i,
                        "name": name,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        remaining = {
            "bodies": root.bRepBodies.count,
            "sketches": root.sketches.count,
            "occurrences": root.occurrences.count,
            "joints": (
                root.joints.count + root.asBuiltJoints.count + root.rigidGroups.count
            ),
            "construction": (
                root.constructionPlanes.count
                + root.constructionAxes.count
                + root.constructionPoints.count
            ),
            "timeline": tl.count if tl is not None else 0,
        }

        if any(v for k, v in remaining.items() if k != "timeline"):
            raise RuntimeError(
                f"delete_all did not clear the design — remaining: {remaining}. "
                f"Deleted: {deleted}. Failures: {errors}"
            )

        return {"deleted": deleted, "remaining": remaining, "errors": errors}

    def undo(self):
        design = self._design()
        type_before = design.designType
        # FIX (fork): this used to return {"undone": True} unconditionally,
        # without ever checking that anything was undone. Found live: after a
        # bad fillet, undo reported success while the feature stayed in the
        # timeline -- commandDefinitions.execute() only QUEUES a UI command,
        # and what it actually undid was a camera change, not the feature.
        # The timeline length is the honest witness.
        timeline_before = design.timeline.count if design.timeline else None

        cmd_def = self.ui.commandDefinitions.itemById("UndoCommand")
        if cmd_def is None:
            raise RuntimeError(
                "Undo command is not available in the current workspace. "
                "The design was NOT modified — delete the failed feature "
                "explicitly instead."
            )
        cmd_def.execute()

        # Check if undo silently switched design type (Parametric → Direct)
        adsk.doEvents()  # let Fusion process the undo
        type_after = design.designType
        if type_before != type_after:
            # Undo the undo — redo to restore original state
            redo_def = self.ui.commandDefinitions.itemById("RedoCommand")
            if redo_def:
                redo_def.execute()
                adsk.doEvents()
            parametric = adsk.fusion.DesignTypes.ParametricDesignType
            raise RuntimeError(
                f"Undo aborted: would have changed design type from "
                f"{'Parametric' if type_before == parametric else 'Direct'} to "
                f"{'Parametric' if type_after == parametric else 'Direct'}. "
                f"The undo was automatically reversed (redo). "
                f"Delete the failed feature explicitly instead."
            )

        timeline_after = design.timeline.count if design.timeline else None
        result = {"design_type": type_after}
        if timeline_before is None or timeline_after is None:
            result["undone"] = True
            result["verified"] = False
            return result

        result["timeline_before"] = timeline_before
        result["timeline_after"] = timeline_after
        if timeline_after < timeline_before:
            result["undone"] = True
            result["verified"] = True
            return result

        # Nothing left the timeline. The UI undo may have consumed a
        # non-modelling action (a camera move, a selection) instead.
        result["undone"] = False
        result["verified"] = True
        result["warning"] = (
            "Undo ran but the timeline is unchanged — it likely undid a "
            "non-modelling action (view change, selection). The feature is "
            "still there. Use suppress_feature to disable it, which is "
            "deterministic; API-created features are not reliably on the "
            "UI undo stack."
        )
        return result

    # ------------------------------------------------------------------
    # Direct Primitives (via TemporaryBRepManager)
    # ------------------------------------------------------------------

    def create_box(
        self,
        length: float,
        width: float,
        height: float,
        center_x: float = 0,
        center_y: float = 0,
        center_z: float = 0,
    ):
        root = self._root()
        temp_brep = adsk.fusion.TemporaryBRepManager.get()

        # Box orientation matrix
        orient = adsk.core.OrientedBoundingBox3D.create(
            adsk.core.Point3D.create(center_x, center_y, center_z + height / 2),
            adsk.core.Vector3D.create(1, 0, 0),
            adsk.core.Vector3D.create(0, 1, 0),
            length,
            width,
            height,
        )

        box_body = temp_brep.createBox(orient)
        base_feat = root.features.baseFeatures.add()
        base_feat.startEdit()
        root.bRepBodies.add(box_body, base_feat)
        base_feat.finishEdit()

        return {
            "created": True,
            "body_name": base_feat.bodies.item(0).name,
            "length": length,
            "width": width,
            "height": height,
        }

    def create_box_parametric(
        self,
        length,
        width,
        height,
        origin_x: float = 0.0,
        origin_y: float = 0.0,
        origin_z: float = 0.0,
        plane: str = "xy",
        component_name: str = None,
        body_name: str = None,
    ):
        """Parametric box: sketch rectangle + dimensions + extrude.

        length/width/height may be numeric (cm) or string expressions
        (e.g. 'boxL', '56 mm'). Expressions are applied via Fusion's
        parameter system so later changes to User Parameters propagate.
        """
        comp = (
            self._component_by_name(component_name) if component_name else self._root()
        )

        base_plane = self._construction_plane(plane)
        if origin_z != 0:
            plane_input = comp.constructionPlanes.createInput()
            offset_val = adsk.core.ValueInput.createByReal(origin_z)
            plane_input.setByOffset(base_plane, offset_val)
            sketch_plane = comp.constructionPlanes.add(plane_input)
        else:
            sketch_plane = base_plane
        sketch = comp.sketches.add(sketch_plane)

        def _initial(val):
            return float(val) if isinstance(val, (int, float)) else 1.0

        p1 = adsk.core.Point3D.create(origin_x, origin_y, 0)
        p2 = adsk.core.Point3D.create(
            origin_x + _initial(length), origin_y + _initial(width), 0
        )
        rect = sketch.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)

        dims = sketch.sketchDimensions
        text_pt = adsk.core.Point3D.create(0, 0, 0)

        def _set_dim(dim, value):
            if isinstance(value, (int, float)):
                dim.parameter.value = float(value)
            else:
                dim.parameter.expression = str(value)

        bottom = rect.item(0)
        length_dim = dims.addDistanceDimension(
            bottom.startSketchPoint,
            bottom.endSketchPoint,
            adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation,
            text_pt,
        )
        _set_dim(length_dim, length)

        right = rect.item(1)
        width_dim = dims.addDistanceDimension(
            right.startSketchPoint,
            right.endSketchPoint,
            adsk.fusion.DimensionOrientations.VerticalDimensionOrientation,
            text_pt,
        )
        _set_dim(width_dim, width)

        if sketch.profiles.count == 0:
            raise RuntimeError("Rectangle sketch produced no profile")
        profile = sketch.profiles.item(0)

        ext_feats = comp.features.extrudeFeatures
        ext_input = ext_feats.createInput(
            profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        )
        if isinstance(height, (int, float)):
            h_vi = adsk.core.ValueInput.createByReal(float(height))
        else:
            h_vi = adsk.core.ValueInput.createByString(str(height))
        # FIX: same setDistanceExtent-doesn't-exist issue as extrude() above.
        ext_input.setOneSideExtent(
            adsk.fusion.DistanceExtentDefinition.create(h_vi),
            adsk.fusion.ExtentDirections.PositiveExtentDirection,
        )
        feat = ext_feats.add(ext_input)

        body = feat.bodies.item(0)
        if body_name:
            body.name = body_name

        return {
            "created": True,
            "body_name": body.name,
            "feature_name": feat.name,
            "sketch_name": sketch.name,
            "length": length,
            "width": width,
            "height": height,
            "origin": [origin_x, origin_y, origin_z],
            "plane": plane,
            "component": comp.name,
        }

    def create_cylinder(
        self,
        radius: float,
        height: float,
        base_x: float = 0,
        base_y: float = 0,
        base_z: float = 0,
        axis: str = "z",
        direction_x: float = None,
        direction_y: float = None,
        direction_z: float = None,
        top_radius: float = None,
    ):
        root = self._root()
        temp_brep = adsk.fusion.TemporaryBRepManager.get()

        base_pt = adsk.core.Point3D.create(base_x, base_y, base_z)
        # FIX (fork): only x/y/z axes were possible, so every inclined bore
        # (valve guides, throats, HLA bores of a pent-roof head) needed a
        # create + move_body rotation round trip. An explicit direction
        # vector overrides `axis`; top_radius makes a cone (valve seats,
        # tapered ports) -- both straight from createCylinderOrCone.
        if any(v is not None for v in (direction_x, direction_y, direction_z)):
            d = [float(v or 0.0) for v in (direction_x, direction_y, direction_z)]
            norm = math.sqrt(sum(c * c for c in d))
            if norm < 1e-12:
                raise RuntimeError("direction vector must be non-zero")
            axis_vec = tuple(c / norm for c in d)
        else:
            axis_vec = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
        top_pt = adsk.core.Point3D.create(
            base_x + axis_vec[0] * height,
            base_y + axis_vec[1] * height,
            base_z + axis_vec[2] * height,
        )
        r_top = radius if top_radius is None else float(top_radius)

        cyl_body = temp_brep.createCylinderOrCone(base_pt, radius, top_pt, r_top)

        base_feat = root.features.baseFeatures.add()
        base_feat.startEdit()
        root.bRepBodies.add(cyl_body, base_feat)
        base_feat.finishEdit()

        return {
            "created": True,
            "body_name": base_feat.bodies.item(0).name,
            "radius": radius,
            "height": height,
        }

    def create_sphere(
        self,
        radius: float,
        center_x: float = 0,
        center_y: float = 0,
        center_z: float = 0,
    ):
        root = self._root()
        temp_brep = adsk.fusion.TemporaryBRepManager.get()

        center = adsk.core.Point3D.create(center_x, center_y, center_z)
        sphere_body = temp_brep.createSphere(center, radius)

        base_feat = root.features.baseFeatures.add()
        base_feat.startEdit()
        root.bRepBodies.add(sphere_body, base_feat)
        base_feat.finishEdit()

        return {
            "created": True,
            "body_name": base_feat.bodies.item(0).name,
            "radius": radius,
        }

    def create_torus(
        self,
        major_radius: float,
        minor_radius: float,
        center_x: float = 0,
        center_y: float = 0,
        center_z: float = 0,
        axis: str = "z",
    ):
        root = self._root()
        temp_brep = adsk.fusion.TemporaryBRepManager.get()

        center = adsk.core.Point3D.create(center_x, center_y, center_z)
        axis_vec = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
        axis_vector = adsk.core.Vector3D.create(*axis_vec)

        torus_body = temp_brep.createTorus(
            center, axis_vector, major_radius, minor_radius
        )

        # FIX (fork): TemporaryBRepManager.createTorus() silently ignores
        # its own `center` argument -- confirmed live against the raw API,
        # not just this wrapper: calling createTorus(Point3D(200,50,10), ...)
        # directly still produces a torus with bounding box centered on the
        # ORIGIN. createSphere() with the same center-argument pattern was
        # checked side by side and places its center correctly, so this is
        # specific to createTorus, not a general TemporaryBRepManager issue.
        # Real-world cost: a torus built off-origin (e.g. as the rim of a
        # handwheel centered away from the origin) silently lands at the
        # origin instead -- no error, and every subsequent measurement that
        # doesn't check position (volume, area, face/edge count) still
        # matches expectations, so the mislocation is easy to miss entirely.
        # Worked around by moving the already-created temporary body with
        # TemporaryBRepManager.transform() before it's added to the
        # document, rather than trusting createTorus's center argument.
        if center_x != 0 or center_y != 0 or center_z != 0:
            translation = adsk.core.Matrix3D.create()
            translation.translation = adsk.core.Vector3D.create(
                center_x, center_y, center_z
            )
            temp_brep.transform(torus_body, translation)

        base_feat = root.features.baseFeatures.add()
        base_feat.startEdit()
        root.bRepBodies.add(torus_body, base_feat)
        base_feat.finishEdit()

        return {
            "created": True,
            "body_name": base_feat.bodies.item(0).name,
            "major_radius": major_radius,
            "minor_radius": minor_radius,
        }

    # ------------------------------------------------------------------
    # Construction Geometry
    # ------------------------------------------------------------------

    def create_construction_plane(
        self,
        method: str,
        plane: str = None,
        offset: float = None,
        angle: float = None,
        edge_name: str = None,
        plane_one: str = None,
        plane_two: str = None,
        point_one: list = None,
        point_two: list = None,
        point_three: list = None,
    ):
        root = self._root()
        planes = root.constructionPlanes
        inp = planes.createInput()

        if method == "offset":
            inp.setByOffset(
                self._construction_plane(plane),
                adsk.core.ValueInput.createByReal(offset),
            )
        elif method == "angle":
            inp.setByAngle(
                self._construction_axis(edge_name or "x"),
                adsk.core.ValueInput.createByString(f"{angle} deg"),
                self._construction_plane(plane),
            )
        elif method == "midplane":
            inp.setByTwoPlanes(
                self._construction_plane(plane_one), self._construction_plane(plane_two)
            )
        elif method == "three_points":
            p1 = adsk.core.Point3D.create(*point_one)
            p2 = adsk.core.Point3D.create(*point_two)
            p3 = adsk.core.Point3D.create(*point_three)
            inp.setByThreePoints(p1, p2, p3)
        elif method == "tangent":
            raise RuntimeError("Tangent plane needs face selection—use execute_code")
        else:
            raise RuntimeError(f"Unknown method: {method}")

        plane_obj = planes.add(inp)
        return {"created": True, "name": plane_obj.name, "method": method}

    def create_construction_axis(
        self,
        method: str,
        point_one: list = None,
        point_two: list = None,
        plane_one: str = None,
        plane_two: str = None,
        body_name: str = None,
        edge_index: int = None,
    ):
        root = self._root()
        axes = root.constructionAxes
        inp = axes.createInput()

        if method == "two_points":
            p1 = adsk.core.Point3D.create(*point_one)
            p2 = adsk.core.Point3D.create(*point_two)
            inp.setByTwoPoints(p1, p2)
        elif method == "intersection":
            inp.setByTwoPlanes(
                self._construction_plane(plane_one), self._construction_plane(plane_two)
            )
        elif method == "edge":
            body = self._body_by_name(body_name)
            edge = body.edges.item(edge_index)
            inp.setByEdge(edge)
        elif method == "perpendicular_at_point":
            p1 = adsk.core.Point3D.create(*point_one)
            inp.setByPerpendicularAtPoint(self._construction_plane(plane_one), p1)
        else:
            raise RuntimeError(f"Unknown method: {method}")

        axis_obj = axes.add(inp)
        return {"created": True, "name": axis_obj.name, "method": method}

    def create_ucs(
        self,
        name: str = None,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        angle_x: float = 0,
        angle_y: float = 0,
        angle_z: float = 0,
    ):
        """Create a User Coordinate System at (x, y, z), angles in degrees.

        The UCS API (May 2026, preview) is entity-based: the anchor must be
        a sketch point / vertex / construction point.  This creates a hidden
        reference sketch (``UCS_<name>_ref``) holding the anchor point; the
        UCS stays parametrically linked to it, so don't delete that sketch.
        (ConstructionPoint anchors are rejected by current builds, hence the
        sketch-point route.)
        """
        root = self._root()

        if z:
            plane_in = root.constructionPlanes.createInput()
            plane_in.setByOffset(
                root.xYConstructionPlane, adsk.core.ValueInput.createByReal(z)
            )
            base_plane = root.constructionPlanes.add(plane_in)
        else:
            base_plane = root.xYConstructionPlane

        sk = root.sketches.add(base_plane)
        pt = sk.sketchPoints.add(adsk.core.Point3D.create(x, y, 0))
        ref_name = f"UCS_{name or 'unnamed'}_ref"
        sk.name = ref_name
        sk.isVisible = False

        # FIX: was UserCoordinateSystemGeometry_createByPoint (underscore) --
        # a typo; createByPoint is a static method ON the class.
        geom = adsk.fusion.UserCoordinateSystemGeometry.createByPoint(pt)
        inp = root.userCoordinateSystems.createInput(geom)
        if angle_x:
            inp.angleX = adsk.core.ValueInput.createByReal(math.radians(angle_x))
        if angle_y:
            inp.angleY = adsk.core.ValueInput.createByReal(math.radians(angle_y))
        if angle_z:
            inp.angleZ = adsk.core.ValueInput.createByReal(math.radians(angle_z))

        ucs = root.userCoordinateSystems.add(inp)
        if name:
            try:
                ucs.name = name
            except Exception:
                pass
        return {
            "name": ucs.name,
            "origin": [x, y, z],
            "angles_deg": [angle_x, angle_y, angle_z],
            "reference_sketch": ref_name,
        }

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------

    def create_component(self, name: str, parent_name: str = None):
        root = self._root()
        parent = self._component_by_name(parent_name) if parent_name else root

        occ = parent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        occ.component.name = name
        return {"created": True, "name": name}

    def add_joint(
        self, component_one: str, component_two: str, joint_type: str = "rigid"
    ):
        root = self._root()

        occ1 = occ2 = None
        for occ in root.allOccurrences:
            if occ.component.name == component_one:
                occ1 = occ
            if occ.component.name == component_two:
                occ2 = occ

        if not occ1 or not occ2:
            raise RuntimeError("One or both components not found")

        joints = root.joints
        joint_types = {
            "rigid": adsk.fusion.JointTypes.RigidJointType,
            "revolute": adsk.fusion.JointTypes.RevoluteJointType,
            "slider": adsk.fusion.JointTypes.SliderJointType,
            "cylindrical": adsk.fusion.JointTypes.CylindricalJointType,
            "pin_slot": adsk.fusion.JointTypes.PinSlotJointType,
            "planar": adsk.fusion.JointTypes.PlanarJointType,
            "ball": adsk.fusion.JointTypes.BallJointType,
        }

        jt = joint_types.get(joint_type)
        if jt is None:
            raise RuntimeError(f"Unknown joint type: {joint_type}")

        # Create joint geometry from origin points.
        # FIX: JointGeometry.createByPoint() takes a single point argument
        # (ConstructionPoint/SketchPoint/BRepVertex) -- it never accepted the
        # occurrence as a separate parameter. The occurrence context that the
        # extra argument was presumably trying to supply belongs on the POINT
        # itself, via createForAssemblyContext(occurrence), which is how a
        # component-native entity is proxied into a specific occurrence's
        # position in the assembly.
        origin1 = occ1.component.originConstructionPoint.createForAssemblyContext(occ1)
        origin2 = occ2.component.originConstructionPoint.createForAssemblyContext(occ2)
        geo1 = adsk.fusion.JointGeometry.createByPoint(origin1)
        geo2 = adsk.fusion.JointGeometry.createByPoint(origin2)

        inp = joints.createInput(geo1, geo2)
        if joint_type == "rigid":
            inp.setAsRigidJointMotion()
        joints.add(inp)
        return {"created": True, "joint_type": joint_type}

    def create_as_built_joint(
        self, component_one: str, component_two: str, joint_type: str = "rigid"
    ):
        root = self._root()

        occ1 = occ2 = None
        for occ in root.allOccurrences:
            if occ.component.name == component_one:
                occ1 = occ
            if occ.component.name == component_two:
                occ2 = occ

        if not occ1 or not occ2:
            raise RuntimeError("One or both components not found")

        as_built = root.asBuiltJoints
        inp = as_built.createInput(occ1, occ2, None)
        as_built.add(inp)
        return {"created": True, "joint_type": joint_type}

    def create_rigid_group(self, component_names: list, include_children: bool = True):
        root = self._root()
        occs = adsk.core.ObjectCollection.create()

        for name in component_names:
            for occ in root.allOccurrences:
                if occ.component.name == name:
                    occs.add(occ)
                    break

        if occs.count < 2:
            raise RuntimeError("Need at least 2 components for rigid group")

        groups = root.rigidGroups
        groups.add(occs, include_children)
        return {"created": True, "component_count": occs.count}

    # ------------------------------------------------------------------
    # Inspection / Analysis
    # ------------------------------------------------------------------

    def measure_distance(self, entity_one: str, entity_two: str):
        root = self._root()

        def get_entity(name):
            # Try as body
            for i in range(root.bRepBodies.count):
                b = root.bRepBodies.item(i)
                if b.name == name:
                    return b
            # Try as point (x,y,z format)
            if "," in name:
                coords = [float(x.strip()) for x in name.split(",")]
                return adsk.core.Point3D.create(*coords)
            raise RuntimeError(f"Entity '{name}' not found")

        e1 = get_entity(entity_one)
        e2 = get_entity(entity_two)

        measure = self.app.measureManager
        result = measure.measureMinimumDistance(e1, e2)
        # FIX: MeasureResults exposes positionOne/positionTwo on Fusion 2704+,
        # not pointOnEntityOne/pointOnEntityTwo.
        return {
            "distance": result.value,
            "point_one": [
                result.positionOne.x,
                result.positionOne.y,
                result.positionOne.z,
            ],
            "point_two": [
                result.positionTwo.x,
                result.positionTwo.y,
                result.positionTwo.z,
            ],
        }

    def measure_angle(
        self,
        entity_one: str,
        entity_two: str,
        face_index_one: int = 0,
        face_index_two: int = 0,
    ):
        # FIX (fork): two bugs.
        # 1. get_entity only searched root.bRepBodies -- same gap as
        #    get_object_info and check_interference: a body inside a
        #    sub-component (the normal create_component pattern) was never
        #    found. Now uses _body_by_name, which already searches
        #    occurrences correctly.
        # 2. It always took faces.item(0) -- the FIRST face, hardcoded, no
        #    way to pick which one. That makes the tool useless for its most
        #    natural use (e.g. verifying a draft angle between a drafted
        #    side face and the base) whenever the target face isn't
        #    coincidentally index 0. face_index_one/two let the caller
        #    choose, the same fix pattern already used for cam geometry
        #    selection and create_thread.
        def get_entity(name, face_index):
            body = self._body_by_name(name)
            # Defensive: handler(**params) in execute_command applies zero
            # type coercion, and a caller whose cached tool schema is stale
            # can send a numeric index as a JSON string. Confirmed live:
            # "5" arrived here as str and crashed the comparison below with
            # "'<' not supported between instances of 'str' and 'int'".
            face_index = int(face_index)
            if face_index < 0 or face_index >= body.faces.count:
                raise RuntimeError(
                    f"face_index {face_index} out of range for '{name}' "
                    f"({body.faces.count} faces)"
                )
            return body.faces.item(face_index)

        e1 = get_entity(entity_one, face_index_one)
        e2 = get_entity(entity_two, face_index_two)

        measure = self.app.measureManager
        result = measure.measureAngle(e1, e2)
        return {"angle_degrees": math.degrees(result.value)}

    def get_physical_properties(self, body_name: str, accuracy: str = "medium"):
        body = self._body_by_name(body_name)

        accuracy_map = {
            "low": adsk.fusion.CalculationAccuracy.LowCalculationAccuracy,
            "medium": adsk.fusion.CalculationAccuracy.MediumCalculationAccuracy,
            "high": adsk.fusion.CalculationAccuracy.HighCalculationAccuracy,
            "very_high": adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy,
        }
        acc = accuracy_map.get(accuracy, accuracy_map["medium"])

        props = body.getPhysicalProperties(acc)
        return {
            "mass": props.mass,
            "volume": props.volume,
            "area": props.area,
            "density": props.density,
            "center_of_mass": [
                props.centerOfMass.x,
                props.centerOfMass.y,
                props.centerOfMass.z,
            ],
        }

    def create_section_analysis(self, plane: str = "yz", offset: float = 0):
        # FIX: analyses live on Design (not Component) on Fusion 2704+, and
        # section analyses have their own collection with a typed createInput
        # (cutPlaneEntity, distance) -- there is no Analyses.createInput().
        #
        # FIX (fork): the runtime module's own signature is
        # createInput(cutPlaneEntity: Base, distance: "float") -- a plain
        # float in cm, not a ValueInput. Wrapping it in
        # ValueInput.createByReal() raised "in method
        # 'SectionAnalyses_createInput', argument 3 of type 'double'" --
        # confirmed live. Unlike most distance/length parameters elsewhere
        # in the Fusion API, this one is NOT a ValueInput.
        design = self._design()
        analyses = design.analyses.sectionAnalyses

        inp = analyses.createInput(self._construction_plane(plane), float(offset))

        analyses.add(inp)
        return {"created": True, "plane": plane, "offset": offset}

    def check_interference(
        self, component_names: list, include_coincident_faces: bool = False
    ):
        root = self._root()
        bodies = adsk.core.ObjectCollection.create()

        # FIX (fork): this only ever searched root.allOccurrences, i.e.
        # components in an assembly. In a single-component Part document —
        # the common case for this project, where several bodies sit
        # directly in root.bRepBodies — no occurrence ever matches a body's
        # name, so the tool silently found nothing no matter what was
        # passed, always failing with "Need at least 2 components with
        # bodies". Confirmed live. Falls back to matching a root-level body
        # by name when no occurrence/component matches.
        for name in component_names:
            matched = False
            for occ in root.allOccurrences:
                if occ.component.name == name:
                    for b in occ.bRepBodies:
                        bodies.add(b)
                    matched = True
            if not matched:
                for b in root.bRepBodies:
                    if b.name == name:
                        bodies.add(b)
                        matched = True

        if bodies.count < 2:
            raise RuntimeError(
                "Need at least 2 bodies — checked both components (assembly "
                "occurrences) and root-level bodies (Part document) for the "
                f"given names: {component_names}"
            )

        # Interference analysis is a Design-level API.  Component has no
        # interfere() method at all, so the previous call raised
        # AttributeError for every caller.
        design = self._design()
        inp = design.createInterferenceInput(bodies)
        inp.areCoincidentFacesIncluded = bool(include_coincident_faces)
        interference = design.analyzeInterference(inp)

        results = []
        if interference is not None:
            for i in range(interference.count):
                result = interference.item(i)
                results.append(
                    {
                        "body_one": result.entityOne.name,
                        "body_two": result.entityTwo.name,
                        "volume": result.interferenceBody.volume,
                    }
                )

        return {"interferences": results, "count": len(results)}

    def compare_meshes(self, mesh_name_a: str, mesh_name_b: str):
        """Compare two mesh bodies; report per-node deviation statistics.

        Uses PolygonMesh.compareWith (Fusion 2026): for every node in mesh A,
        the signed distance to the closest point on mesh B (cm).  Positive
        means the node lies on the surface-normal side of B.
        """
        design = self._design()
        root = design.rootComponent

        def _mesh_body_by_name(name):
            for i in range(root.meshBodies.count):
                mb = root.meshBodies.item(i)
                if mb.name == name:
                    return mb
            raise RuntimeError(
                f"Mesh body '{name}' not found in root component. "
                "Use get_scene_info to list mesh bodies."
            )

        body_a = _mesh_body_by_name(mesh_name_a)
        body_b = _mesh_body_by_name(mesh_name_b)

        mesh_a = body_a.mesh or body_a.displayMesh
        mesh_b = body_b.mesh or body_b.displayMesh
        if mesh_a is None or mesh_b is None:
            raise RuntimeError("Could not obtain polygon mesh data")

        deviations = list(mesh_a.compareWith(mesh_b))
        if not deviations:
            raise RuntimeError("compareWith returned no deviation data")

        abs_dev = [abs(d) for d in deviations]
        n = len(deviations)
        mean_abs = sum(abs_dev) / n
        rms = math.sqrt(sum(d * d for d in deviations) / n)
        return {
            "mesh_a": mesh_name_a,
            "mesh_b": mesh_name_b,
            "node_count": n,
            "min_deviation": min(deviations),
            "max_deviation": max(deviations),
            "mean_abs_deviation": mean_abs,
            "rms_deviation": rms,
            "max_abs_deviation": max(abs_dev),
            "units": "cm",
        }

    # ------------------------------------------------------------------
    # Appearance
    # ------------------------------------------------------------------

    def set_appearance(
        self,
        target_name: str,
        appearance_name: str,
        target_type: str = "body",
        face_index: int = None,
    ):
        # Find appearance in library — try both known library names
        app_lib = self.app.materialLibraries.itemByName("Fusion Appearance Library")
        if app_lib is None:
            app_lib = self.app.materialLibraries.itemByName(
                "Fusion 360 Appearance Library"
            )
        if app_lib is None:
            # Fall back to searching all libraries
            for i in range(self.app.materialLibraries.count):
                lib = self.app.materialLibraries.item(i)
                if lib.appearances.count > 0:
                    app_lib = lib
                    break
        if app_lib is None:
            raise RuntimeError("No appearance library found")

        # FIX (fork): exact match only, against an English name -- but on a
        # localized Fusion install (confirmed live: pt-BR) BOTH the library
        # name ("Biblioteca de aparência do Fusion", not "Fusion Appearance
        # Library" -- the fallback search below already covers that part)
        # AND every individual appearance name are localized ("Aço -
        # Acetinado", not "Steel - Satin" -- the very example this tool's
        # own schema uses). There's no reasonable English<->pt-BR mapping to
        # add here, so this keeps exact matching but adds a case-insensitive
        # pass and, on failure, an error that shows real names from this
        # install instead of leaving the caller guessing why a
        # plausible-looking name doesn't exist.
        appearance = None
        for i in range(app_lib.appearances.count):
            app = app_lib.appearances.item(i)
            if app.name == appearance_name:
                appearance = app
                break
        if appearance is None:
            target_lower = appearance_name.lower()
            for i in range(app_lib.appearances.count):
                app = app_lib.appearances.item(i)
                if app.name.lower() == target_lower:
                    appearance = app
                    break

        if not appearance:
            all_names = [
                app_lib.appearances.item(i).name
                for i in range(app_lib.appearances.count)
            ]
            words = [w for w in appearance_name.lower().split() if len(w) > 2]
            close = [
                n for n in all_names
                if any(w in n.lower() for w in words)
            ][:10]
            raise RuntimeError(
                f"Appearance '{appearance_name}' not found in "
                f"'{app_lib.name}' ({len(all_names)} entries). Names in "
                "this library may be localized to the Fusion UI language, "
                "not English, even for a built-in library. "
                + (
                    f"Close matches: {', '.join(close)}"
                    if close
                    else f"Sample of what's available: {', '.join(all_names[:10])}"
                )
            )

        # Library appearances must be copied into the design before
        # assignment — assigning a library appearance directly is
        # version-dependent and known to fail on recent Fusion builds.
        design = self._design()
        local = design.appearances.itemByName(appearance.name)
        if local is None:
            local = design.appearances.addByCopy(appearance, appearance.name)
        if local is None:
            raise RuntimeError(
                f"Could not copy appearance '{appearance_name}' into the design"
            )

        if target_type == "body":
            body = self._body_by_name(target_name)
            body.appearance = local
        elif target_type == "component":
            comp = self._component_by_name(target_name)
            comp.appearance = local
        elif target_type == "face":
            body = self._body_by_name(target_name)
            face = body.faces.item(face_index)
            face.appearance = local

        return {"applied": True, "target": target_name, "appearance": appearance_name}

    def set_color(
        self,
        body_name: str,
        red: int,
        green: int,
        blue: int,
        opacity: float = 1.0,
    ):
        """Assign a flat RGB color to a body via a design-local appearance.

        Uses the Appearances.add + Appearance.color API (July 2026), so no
        library copy is needed.  Appearances are reused when the same color
        is requested again.  opacity 1.0 = fully opaque, 0.0 = invisible.
        """
        body = self._body_by_name(body_name)
        design = self._design()

        red = max(0, min(255, int(red)))
        green = max(0, min(255, int(green)))
        blue = max(0, min(255, int(blue)))
        alpha = max(0, min(255, round(opacity * 255)))

        color_name = f"MCP_{red}_{green}_{blue}_{alpha}"
        appearance = design.appearances.itemByName(color_name)
        if appearance is None:
            appearance = design.appearances.add(color_name)
            appearance.color = adsk.core.Color.create(red, green, blue, alpha)

        body.appearance = appearance
        return {
            "body": body_name,
            "color": [red, green, blue],
            "opacity": alpha / 255.0,
            "appearance": color_name,
        }

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------

    def get_parameters(self):
        design = self._design()
        params = []
        for param in design.userParameters:
            params.append(
                {
                    "name": param.name,
                    "value": param.value,
                    "expression": param.expression,
                    "unit": param.unit,
                    "comment": param.comment,
                }
            )
        return {"parameters": params, "count": len(params)}

    def create_parameter(self, name: str, value: float, unit: str, comment: str = None):
        design = self._design()
        params = design.userParameters
        unit = _param_units.normalise_unit(unit)
        # createByReal() is read in internal units (cm, radians), so a caller
        # asking for 1000 mm would get 1000 cm labelled "mm".
        value_input = _param_units.build_value_input(
            value,
            unit,
            adsk.core.ValueInput.createByString,
            adsk.core.ValueInput.createByReal,
        )
        param = params.add(name, value_input, unit, comment or "")
        return {
            "created": True,
            "name": name,
            "value": value,
            "unit": unit,
            "expression": param.expression,
        }

    def set_parameter(self, name: str, value: float):
        design = self._design()
        param = design.userParameters.itemByName(name)
        if not param:
            raise RuntimeError(f"Parameter '{name}' not found")
        # Assigning .value would be read in internal units, silently rescaling
        # any parameter whose unit is not the internal one. Write the
        # expression, in the unit the parameter already declares.
        unit = _param_units.normalise_unit(param.unit)
        param.expression = _param_units.expression_for(value, unit)
        return {
            "updated": True,
            "name": name,
            "value": value,
            "unit": unit,
            "expression": param.expression,
        }

    def delete_parameter(self, name: str):
        design = self._design()
        param = design.userParameters.itemByName(name)
        if not param:
            raise RuntimeError(f"Parameter '{name}' not found")
        param.deleteMe()
        return {"deleted": True, "name": name}

    # ------------------------------------------------------------------
    # Surface Operations
    # ------------------------------------------------------------------

    def patch_surface(
        self, sketch_name: str, profile_index: int = 0, continuity: str = "connected"
    ):
        root = self._root()
        sketch = self._sketch_by_name(sketch_name)

        if sketch.profiles.count == 0:
            raise RuntimeError("No profiles in sketch")
        profile = sketch.profiles.item(profile_index)

        patches = root.features.patchFeatures
        inp = patches.createInput(
            profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        )

        sct = adsk.fusion.SurfaceContinuityTypes
        cont_map = {
            "connected": sct.ConnectedSurfaceContinuityType,
            "tangent": sct.TangentSurfaceContinuityType,
            "curvature": sct.CurvatureSurfaceContinuityType,
        }
        # FIX: PatchFeatureInput has no boundaryContinuity on Fusion 2704+;
        # continuity is applied via setContinuity(continuity, weight, flipped).
        inp.setContinuity(
            cont_map.get(continuity, cont_map["connected"]), 1.0, False
        )

        feat = patches.add(inp)
        return {"feature_name": feat.name, "continuity": continuity}

    def stitch_surfaces(self, body_names: list, tolerance: float = 0.01):
        root = self._root()
        bodies = adsk.core.ObjectCollection.create()
        for name in body_names:
            bodies.add(self._body_by_name(name))

        stitches = root.features.stitchFeatures
        inp = stitches.createInput(
            bodies,
            adsk.core.ValueInput.createByReal(tolerance),
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        )
        feat = stitches.add(inp)
        return {"feature_name": feat.name, "body_count": len(body_names)}

    def thicken_surface(
        self, body_name: str, thickness: float, direction: str = "symmetric"
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        faces = adsk.core.ObjectCollection.create()
        for face in body.faces:
            faces.add(face)

        thickens = root.features.thickenFeatures
        inp = thickens.createInput(
            faces,
            adsk.core.ValueInput.createByReal(thickness),
            False,
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
            direction == "symmetric",
        )
        feat = thickens.add(inp)
        return {"feature_name": feat.name, "thickness": thickness}

    def ruled_surface(
        self,
        body_name: str,
        edge_index: int,
        distance: float = 1.0,
        rule_type: str = "normal",
    ):
        root = self._root()
        body = self._body_by_name(body_name)
        edge = body.edges.item(edge_index)

        ruled = root.features.ruledSurfaceFeatures
        inp = ruled.createInput(edge, adsk.core.ValueInput.createByReal(distance))
        feat = ruled.add(inp)
        return {"feature_name": feat.name, "distance": distance}

    def trim_surface(self, body_name: str, tool_name: str):
        root = self._root()
        body = self._body_by_name(body_name)
        tool = self._body_by_name(tool_name)

        trims = root.features.trimFeatures
        inp = trims.createInput(body, tool)
        feat = trims.add(inp)
        return {"feature_name": feat.name}

    # ------------------------------------------------------------------
    # Sheet Metal
    # ------------------------------------------------------------------

    def create_flange(
        self,
        body_name: str,
        edge_index: int,
        height: float = 1.0,
        angle: float = 90,
        bend_radius: float = None,
    ):
        root = self._root()
        body = self._body_by_name(body_name)
        edge = body.edges.item(edge_index)

        flanges = root.features.flangeFeatures
        inp = flanges.createInput(edge, True)
        inp.angle = adsk.core.ValueInput.createByString(f"{angle} deg")
        inp.height = adsk.core.ValueInput.createByReal(height)
        if bend_radius:
            inp.bendRadius = adsk.core.ValueInput.createByReal(bend_radius)

        feat = flanges.add(inp)
        return {"feature_name": feat.name, "height": height, "angle": angle}

    def create_bend(
        self,
        body_name: str,
        bend_line_sketch: str = None,
        angle: float = 90,
        bend_radius: float = None,
    ):
        root = self._root()
        body = self._body_by_name(body_name)

        if bend_line_sketch:
            sketch = self._sketch_by_name(bend_line_sketch)
            bend_line = sketch.sketchCurves.sketchLines.item(0)

            bends = root.features.bendFeatures
            inp = bends.createInput(body, bend_line, True)
            inp.bendAngle = adsk.core.ValueInput.createByString(f"{angle} deg")
            if bend_radius:
                inp.bendRadius = adsk.core.ValueInput.createByReal(bend_radius)

            feat = bends.add(inp)
            return {"feature_name": feat.name, "angle": angle}
        else:
            raise RuntimeError("bend_line_sketch is required")

    # ------------------------------------------------------------------
    # Chapa metalica (fork)
    #
    # A API do Fusion 2704 NAO expoe criacao de flange, unfold nem regra de
    # chapa (FlangeFeatures/UnfoldFeatures/SheetMetalRules sao so leitura).
    # O caminho que a API oferece, e que estas ferramentas usam:
    #
    #   1. modelar a forma como solido comum (extrude + shell para as abas)
    #   2. convert_to_sheet_metal  -> BRepBody.convertToSheetMetal
    #   3. fold_sheet_metal        -> FoldFeatures (dobra por linha de esboco)
    #   4. flat_pattern            -> Component.createFlatPattern
    #   5. export_flat_pattern_dxf -> ExportManager, DXF para corte
    # ------------------------------------------------------------------

    def _face_plana_principal(self, body, face_index: int = None):
        """Maior face plana do corpo -- a face de base de uma chapa.

        A API exige uma face de topo ou fundo, nunca de borda. O _select_faces
        do projeto nao serve aqui: "top" pega toda face que TOCA o topo,
        o que numa chapa inclui as faces de borda. A de maior area e a base
        em chapa plana e a aba principal em chapa dobrada.
        """
        if face_index is not None:
            return body.faces.item(face_index)
        melhor, area_max = None, -1.0
        plano = adsk.core.Plane.classType()
        for face in body.faces:
            if face.geometry.objectType != plano:
                continue
            if face.area > area_max:
                melhor, area_max = face, face.area
        if melhor is None:
            raise RuntimeError("Body has no planar face to use as sheet metal base")
        return melhor

    def convert_to_sheet_metal(
        self, body_name: str, rule_name: str = None, face_index: int = None
    ):
        design = self._design()
        body = self._body_by_name(body_name)
        if body.isSheetMetal:
            return {"converted": False, "body": body_name,
                    "message": "Body is already sheet metal"}

        # Regras da biblioteca primeiro; as do desenho como alternativa.
        fontes = [design.librarySheetMetalRules, design.designSheetMetalRules]
        rule = None
        if rule_name:
            for fonte in fontes:
                rule = fonte.itemByName(rule_name)
                if rule:
                    break
            if rule is None:
                nomes = [f.item(i).name for f in fontes for i in range(f.count)]
                raise RuntimeError(
                    "Sheet metal rule '%s' not found. Available: %s"
                    % (rule_name, ", ".join(nomes))
                )
        else:
            for fonte in fontes:
                if fonte.count > 0:
                    rule = fonte.item(0)
                    break
            if rule is None:
                raise RuntimeError("No sheet metal rules available in this design")

        base = self._face_plana_principal(body, face_index)
        # A espessura NAO vem da regra: convertToSheetMetal copia a regra e
        # troca a espessura pela medida na propria geometria (baseFace).
        if not body.convertToSheetMetal(base, rule):
            raise RuntimeError(
                "convertToSheetMetal failed. The body must have uniform "
                "thickness -- model it as a thin plate or a shelled solid."
            )
        return {"converted": True, "body": body_name, "rule": rule.name}

    def fold_sheet_metal(
        self,
        body_name: str,
        bend_angle: float,
        line_index: int = -1,
        line_position: str = "center",
        allow_bend_relief: bool = True,
        face_index: int = None,
    ):
        root = self._root()
        body = self._body_by_name(body_name)
        if not body.isSheetMetal:
            raise RuntimeError(
                "Body '%s' is not sheet metal. Run convert_to_sheet_metal first."
                % body_name
            )

        sketch = self._last_sketch()
        linhas = sketch.sketchCurves.sketchLines
        if linhas.count == 0:
            raise RuntimeError(
                "Last sketch has no lines. Draw the bend line on the sheet "
                "face with draw_line, then fold."
            )
        idx = line_index if line_index >= 0 else linhas.count - 1
        linha = linhas.item(idx)

        pos = adsk.fusion.FoldBendLinePositionTypes
        posicoes = {
            "start": pos.StartFoldBendLinePositionType,
            "center": pos.CenterFoldBendLinePositionType,
            "end": pos.EndFoldBendLinePositionType,
        }
        if line_position not in posicoes:
            raise RuntimeError("line_position must be start, center or end")

        folds = root.features.foldFeatures
        inp = folds.createInput(self._face_plana_principal(body, face_index))
        definicao = inp.bendLines.add(
            linha,
            adsk.core.ValueInput.createByString("%s deg" % bend_angle),
            posicoes[line_position],
            allow_bend_relief,
        )
        if definicao is None:
            raise RuntimeError(
                "Bend line was rejected. It must lie on a valid face of the "
                "sheet metal body."
            )
        feat = folds.add(inp)
        return {"feature_name": feat.name, "bend_angle": bend_angle,
                "line_index": idx}

    def flat_pattern(self, body_name: str, face_index: int = None):
        # FIX (fork): Features.flatPatternFeatures nao existe. A planificacao
        # e criada pelo componente dono do corpo: Component.createFlatPattern.
        body = self._body_by_name(body_name)
        if not body.isSheetMetal:
            raise RuntimeError(
                "Body '%s' is not sheet metal. Run convert_to_sheet_metal first."
                % body_name
            )
        comp = body.parentComponent
        # createFlatPattern falha se o componente ja tem uma planificacao.
        if comp.flatPattern:
            return {"created": False, "body": body_name,
                    "message": "Component already has a flat pattern"}
        fp = comp.createFlatPattern(self._face_plana_principal(body, face_index))
        if fp is None:
            raise RuntimeError("createFlatPattern failed")
        return {"created": True, "body": body_name}

    def export_flat_pattern_dxf(self, body_name: str, file_path: str = None):
        body = self._body_by_name(body_name)
        fp = body.parentComponent.flatPattern
        if not fp:
            raise RuntimeError(
                "No flat pattern for '%s'. Run flat_pattern first." % body_name
            )
        if file_path is None:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            file_path = os.path.join(desktop, "%s_planificado.dxf" % body_name)

        export_mgr = self._design().exportManager
        opcoes = export_mgr.createDXFFlatPatternExportOptions(file_path, fp)
        if opcoes is None or not export_mgr.execute(opcoes):
            raise RuntimeError("DXF flat pattern export failed: %s" % file_path)
        return {"exported": True, "file_path": file_path}

    def unfold(self, body_name: str, bend_indices: list = None):
        root = self._root()
        body = self._body_by_name(body_name)

        unfolds = root.features.unfoldFeatures

        bends = adsk.core.ObjectCollection.create()
        if bend_indices:
            for idx in bend_indices:
                # Get bend faces from sheet metal body
                bends.add(body.faces.item(idx))
        else:
            # Unfold all bends
            for face in body.faces:
                bends.add(face)

        # Find stationary face (first planar face)
        stationary = None
        for face in body.faces:
            if face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
                stationary = face
                break

        if not stationary:
            raise RuntimeError("No planar face found for stationary face")

        inp = unfolds.createInput(bends, stationary)
        feat = unfolds.add(inp)
        return {"feature_name": feat.name}

    # ------------------------------------------------------------------
    # CAM
    # ------------------------------------------------------------------

    def _get_cam(self):
        """Get the CAM product from the active document.

        On recent Fusion builds the CAM product is only instantiated once
        the Manufacture workspace has been activated for the document, so
        activate it on demand instead of failing outright.  Note:
        itemByProductType *raises* when the product doesn't exist yet.
        """
        doc = self.app.activeDocument

        def _find_cam_product():
            try:
                return doc.products.itemByProductType("CAMProductType")
            except Exception:
                return None

        cam_product = _find_cam_product()
        if cam_product is None:
            ws = self.ui.workspaces.itemById("CAMEnvironment")
            if ws is not None:
                try:
                    ws.activate()
                    adsk.doEvents()
                except Exception as exc:
                    log.warning("Manufacture workspace activation failed: %s", exc)
                cam_product = _find_cam_product()

        if cam_product is None:
            raise RuntimeError(
                "No CAM workspace found. Open the Manufacturing workspace "
                "in Fusion 360 at least once to initialise it."
            )
        return cam_product

    def _find_setup(self, cam, name: str):
        for i in range(cam.setups.count):
            s = cam.setups.item(i)
            if s.name == name:
                return s
        raise RuntimeError(f"Setup '{name}' not found")

    def _find_operation(self, setup, name: str):
        for i in range(setup.operations.count):
            op = setup.operations.item(i)
            if op.name == name:
                return op
        raise RuntimeError(f"Operation '{name}' not found in setup '{setup.name}'")

    def cam_list_setups(self):
        cam = self._get_cam()
        result = []
        for i in range(cam.setups.count):
            setup = cam.setups.item(i)
            ops = []
            for j in range(setup.operations.count):
                ops.append(setup.operations.item(j).name)
            result.append(
                {
                    "name": setup.name,
                    "operations": ops,
                    "is_valid": setup.isValid,
                }
            )
        return {"setups": result, "count": len(result)}

    def cam_list_operations(self, setup_name: str):
        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)
        result = []
        for i in range(setup.operations.count):
            op = setup.operations.item(i)
            result.append(
                {
                    "name": op.name,
                    "has_toolpath": op.hasToolpath,
                    "is_valid": op.isValid,
                }
            )
        return {"setup": setup_name, "operations": result, "count": len(result)}

    def cam_get_operation_info(self, setup_name: str, operation_name: str):
        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)
        op = self._find_operation(setup, operation_name)

        info = {
            "name": op.name,
            "is_valid": op.isValid,
            "has_toolpath": op.hasToolpath,
        }

        if hasattr(op, "tool") and op.tool:
            tool = op.tool
            desc = tool.description if hasattr(tool, "description") else str(tool)
            info["tool"] = {"description": desc}

        if hasattr(op, "parameters"):
            params = {}
            for param in op.parameters:
                try:
                    params[param.name] = param.expression
                except Exception:
                    pass
            info["parameters"] = params

        return info

    def cam_create_setup(
        self,
        body_name: str,
        name: str = None,
        operation_type: str = "milling",
        stock_mode: str = "relative_box",
        stock_offset_sides: float = 0,
        stock_offset_top: float = 0,
        stock_offset_bottom: float = 0,
    ):
        cam = self._get_cam()
        body = self._body_by_name(body_name)

        op_type_map = {
            "milling": adsk.cam.OperationTypes.MillingOperation,
            "turning": adsk.cam.OperationTypes.TurningOperation,
            "cutting": adsk.cam.OperationTypes.JetOperation,
        }
        op_type = op_type_map.get(operation_type)
        if op_type is None:
            raise RuntimeError(
                f"Unknown operation_type '{operation_type}' "
                "— use milling/turning/cutting"
            )

        setup_input = cam.setups.createInput(op_type)
        setup_input.models = [body]

        if name:
            setup_input.name = name

        setup = cam.setups.add(setup_input)

        # Stock parameters live on the created setup, not the input.
        # Names/enumeration values verified against Fusion 2705: the
        # "Relative size box" UI choice has the id 'default'.
        stock_mode_map = {
            "relative_box": "default",
            "fixed_box": "fixedbox",
            "relative_cylinder": "relativecylinder",
            "fixed_cylinder": "fixedcylinder",
            "from_solid": "solid",
        }
        applied_stock = {}
        failed_stock = {}
        if stock_mode:
            mode_id = stock_mode_map.get(stock_mode, stock_mode)
            if self._set_cam_parameter(setup, "job_stockMode", mode_id, by_string=True):
                applied_stock["stock_mode"] = mode_id
            else:
                failed_stock["stock_mode"] = stock_mode
        # FIX (fork): confirmed live that job_stockOffsetMode defaults to
        # 'simple', under which the side margin is actually driven by
        # job_stockOffsetSides, not job_stockOffset -- writing only
        # job_stockOffset silently left the real side margin at Fusion's
        # factory default (1mm) regardless of what was requested. Both
        # names are written so the value takes whichever offset mode is
        # active on the setup.
        for param_name, value in (
            ("job_stockOffset", stock_offset_sides),
            ("job_stockOffsetSides", stock_offset_sides),
            ("job_stockOffsetTop", stock_offset_top),
            ("job_stockOffsetBottom", stock_offset_bottom),
        ):
            if value:
                if self._set_cam_parameter(setup, param_name, value):
                    applied_stock[param_name] = value
                else:
                    failed_stock[param_name] = value

        result = {
            "name": setup.name,
            "body": body_name,
            "operation_type": operation_type,
        }
        if applied_stock:
            result["stock_applied"] = applied_stock
        if failed_stock:
            result["stock_failed"] = failed_stock
            result["warning"] = (
                "Some stock parameters could not be applied — parameter "
                "names vary by Fusion build; inspect via cam_get_operation_info"
            )
        return result

    # CAM stock/pass parameters that hold a LENGTH, in the cm this project's
    # public API always uses. FIX (fork): a bare numeric expression such as
    # "0.2" is parsed by Fusion in the *document's CAM display unit* (mm on
    # a metric document), not cm — writing 0.2 meaning 0.2 cm silently became
    # 0.2 mm, ten times too small. Confirmed on job_stockOffsetTop:
    # setup.parameters.itemByName("job_stockOffsetTop").value read back as
    # 0.02 cm after writing expression "0.2". Appending "cm" makes the
    # expression parser do the conversion regardless of document unit.
    _CAM_LENGTH_PARAMS = frozenset({
        "job_stockOffset", "job_stockOffsetSides",
        "job_stockOffsetTop", "job_stockOffsetBottom",
        "maximumStepdown", "maximumStepover",
    })

    @staticmethod
    def _set_cam_parameter(target, param_name, value, by_string=False):
        """Set a CAM parameter on a setup or operation. Returns success.

        CAMParameter.value is read-only on current Fusion builds — values
        must be assigned via the ``expression`` property.  Enum parameters
        (e.g. tool_coolant) take quoted lowercase strings ('flood').
        """
        try:
            params = getattr(target, "parameters", None)
            if params is None:
                return False
            p = params.itemByName(param_name)
            if p is None:
                return False
            if by_string:
                p.expression = f"'{value}'"
            elif param_name in CommandHandler._CAM_LENGTH_PARAMS:
                p.expression = f"{value}cm"
            else:
                p.expression = str(value)
            return True
        except Exception as exc:
            log.debug("CAM parameter %s=%r failed: %s", param_name, value, exc)
            return False

    def cam_create_operation(
        self,
        setup_name: str,
        strategy: str,
        name: str = None,
        tool_number: int = None,
        tool_diameter: float = None,
        stepdown: float = None,
        stepover: float = None,
        feed_rate: float = None,
        spindle_speed: float = None,
        coolant: str = "flood",
        geometry_face_index: int = None,
        tool_from_operation: str = None,
    ):
        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)

        if tool_diameter is not None:
            raise RuntimeError(
                "tool_diameter cannot be set on an operation — tool geometry "
                "comes from a tool in the CAM tool library. Select the tool "
                "via tool_number instead."
            )

        # FIX (fork): this tool's documented strategy names don't match
        # Fusion's real internal identifiers -- confirmed live by reading
        # setup.operations.compatibleStrategies, which returns e.g.
        # 'contour2d'/'pocket2d'/'adaptive2d', not '2d_contour'/'2d_pocket'/
        # '2d_adaptive'. createInput() rejects the documented names outright
        # with "Unknown strategy". 'face', 'bore', 'slot', 'trace', and
        # 'engrave' already matched and needed no translation.
        # 'adaptive'/'pocket_clearing' for the two 3D entries are inferred
        # from Fusion's 2D/3D naming pattern (bare name = 3D, "2d" suffix =
        # 2D) and from the compatible-strategies list, but -- unlike the
        # others -- were not exercised end-to-end.
        _STRATEGY_ALIASES = {
            "2d_contour": "contour2d",
            "2d_pocket": "pocket2d",
            "2d_adaptive": "adaptive2d",
            "3d_contour": "contour3d",
            "3d_scallop": "scallop",
            "3d_parallel": "parallel",
            "drilling": "drill",
            "thread_milling": "thread",
            "3d_adaptive": "adaptive",
            "3d_pocket": "pocket_clearing",
        }
        strategy = _STRATEGY_ALIASES.get(strategy, strategy)

        op_input = setup.operations.createInput(strategy)

        op = setup.operations.add(op_input)
        if op is None:
            raise RuntimeError(
                f"Fusion rejected strategy '{strategy}' for setup '{setup_name}'"
            )
        # FIX (fork): OperationInput has NO name property at all (confirmed
        # against the runtime module -- setting op_input.name silently does
        # nothing, no error, no effect). The name lives on OperationBase,
        # available only on the real Operation object add() returns.
        # SetupInput, by contrast, genuinely does have a name property --
        # that's why the equivalent code in cam_create_setup works and this
        # one didn't.
        if name:
            op.name = name

        # Operation parameters (stepdown, feeds, speeds...) only exist on
        # the created operation, keyed by strategy-dependent names.
        applied = {}
        failed = {}
        for param_name, value, by_string in (
            ("tool_number", tool_number, False),
            ("maximumStepdown", stepdown, False),
            ("maximumStepover", stepover, False),
            ("tool_feedCutting", feed_rate, False),
            ("tool_spindleSpeed", spindle_speed, False),
            ("tool_coolant", coolant, True),
        ):
            if value is None:
                continue
            if self._set_cam_parameter(op, param_name, value, by_string):
                applied[param_name] = value
            else:
                failed[param_name] = value

        result = {"name": op.name, "setup": setup_name, "strategy": strategy}
        if applied:
            result["parameters_applied"] = applied
        if failed:
            result["parameters_failed"] = failed
            result["warning"] = (
                "Some parameters are not available for this strategy — "
                "check available names via cam_get_operation_info"
            )

        # FIX (fork): tool_number alone only writes a PARAMETER — it does not
        # attach a real tool, leaving op.tool None and the tool filter at the
        # factory 5–10mm default. Generating such an operation makes Fusion
        # raise a MODAL error dialog ("Falha ao criar percurso; nenhuma
        # ferramenta selecionada") on the main thread, which blocks the
        # add-in's socket loop — the bridge goes dead until a human clicks
        # OK. Confirmed live, twice. Copying a real tool off another
        # operation avoids it; the local tool library is empty on this
        # install, so another operation is the practical source.
        if tool_from_operation:
            try:
                result_tool = self._copy_tool_from_operation(
                    setup, op, tool_from_operation
                )
                applied["tool"] = result_tool
            except Exception as exc:
                failed["tool"] = str(exc)

        # FIX (fork): cam_create_operation previously never selected any
        # geometry. Chain-based 2D strategies (contour2d/pocket2d/adaptive2d/
        # drill/bore...) generate no toolpath without an explicit selection —
        # confirmed live: op valid, generate() returns success, but
        # has_toolpath stayed False with geometryType 'chains' / contours
        # 'false'. Selecting a face picks its outer loop as a chain, mirroring
        # clicking a face in the Fusion UI for a 2D Contour operation.
        if geometry_face_index is not None:
            try:
                result["geometry_applied"] = self._apply_contour2d_geometry(
                    setup, op, geometry_face_index
                )
            except Exception as exc:
                result["geometry_failed"] = str(exc)
                result["warning"] = (
                    result.get("warning", "")
                    + " Geometry selection failed — toolpath will not "
                    "generate until geometry is selected (in the UI or via "
                    "a retry)."
                ).strip()

        return result

    def _copy_tool_from_operation(self, setup, op, source_operation_name: str):
        """Attach the real library tool used by another operation, and sync
        this operation's tool-search filter to match it.

        Both halves are required. Confirmed live: assigning op.tool alone
        succeeds (op.tool reads back the real tool) but leaves
        tool_exactDiameter / tool_minDiameter / tool_maxDiameter at the
        factory 5–10mm default, so Fusion still refuses to build a toolpath
        for a 1.5875mm cutter. Syncing the filter from the tool's own
        tool_diameter / tool_type is what makes generation actually work.
        """
        source = self._find_operation(setup, source_operation_name)
        tool = source.tool
        if tool is None:
            raise RuntimeError(
                f"Operation '{source_operation_name}' has no tool assigned — "
                "pick one that does, or assign a tool in the Fusion UI first"
            )

        op.tool = tool

        diameter = tool.parameters.itemByName("tool_diameter").expression
        tool_type = tool.parameters.itemByName("tool_type").expression
        for param_name, expression in (
            ("tool_exactDiameter", diameter),
            ("tool_minDiameter", diameter),
            ("tool_maxDiameter", diameter),
            ("tool_type", tool_type),
        ):
            p = op.parameters.itemByName(param_name)
            if p is not None:
                p.expression = expression

        description = None
        desc_param = tool.parameters.itemByName("tool_description")
        if desc_param is not None:
            description = desc_param.expression.strip("'")
        return {
            "from_operation": source_operation_name,
            "description": description,
            "diameter": diameter,
        }

    def _apply_contour2d_geometry(self, setup, op, face_index: int):
        """Select a face's outer loop as the chain geometry for a 2D
        chain-based CAM operation (contour2d, pocket2d, adaptive2d, ...).

        The geometry parameter is found by TYPE (CadContours2dParameterValue),
        not by a guessed name — Autodesk ships no public list of per-strategy
        parameter names, and the name is not "geometry" on every strategy.
        Confirmed against the runtime module: CadContours2dParameterValue
        exposes exactly getCurveSelections()/applyCurveSelections(), and its
        own docstring says the contour is only auto-amended "if used on
        Operations, not OperationInputs" — so this must run after
        setup.operations.add(), on the real Operation, not the OperationInput.
        """
        if setup.models.count == 0:
            raise RuntimeError("Setup has no model body to select geometry from")
        body = setup.models.item(0)
        if face_index < 0 or face_index >= body.faces.count:
            raise RuntimeError(
                f"geometry_face_index {face_index} out of range "
                f"(body '{body.name}' has {body.faces.count} faces)"
            )
        face = body.faces.item(face_index)

        # FIX: chain.inputGeometry rejects a BRepFace outright ("Chosen
        # geometry is not compatible with input type") -- confirmed live.
        # Despite the UI letting you click a face to select its contour, the
        # API's ChainSelection wants the actual edges. Use the face's outer
        # loop -- the one with isOuter True -- so inner loops (holes) are
        # excluded, matching what clicking the face outline does in the UI.
        outer_loop = None
        for i in range(face.loops.count):
            loop = face.loops.item(i)
            if loop.isOuter:
                outer_loop = loop
                break
        if outer_loop is None:
            raise RuntimeError(
                f"Face {face_index} on body '{body.name}' has no outer loop"
            )
        edges = [outer_loop.edges.item(i) for i in range(outer_loop.edges.count)]

        geometry_param = None
        for i in range(op.parameters.count):
            p = op.parameters.item(i)
            try:
                cast = adsk.cam.CadContours2dParameterValue.cast(p.value)
            except Exception:
                cast = None
            if cast is not None:
                geometry_param = cast
                break
        if geometry_param is None:
            raise RuntimeError(
                "This strategy has no contour/chain geometry parameter — "
                "geometry_face_index is not applicable"
            )

        curve_selections = geometry_param.getCurveSelections()
        curve_selections.clear()
        chain = curve_selections.createNewChainSelection()
        chain.inputGeometry = edges
        geometry_param.applyCurveSelections(curve_selections)
        return {"body": body.name, "face_index": face_index, "edge_count": len(edges)}

    @staticmethod
    def _wait_future(future, timeout: float = 25.0):
        """Wait for a CAM generation future, bounded so a runaway
        generation fails as a structured error instead of freezing the
        main thread past the bridge timeout.

        FIX (fork): GenerateToolpathFuture is not a blocking future — it has
        no wait() at all. The real property is isGenerationCompleted (not
        isCompleted), and generation runs on a background worker while the
        API's main thread needs adsk.doEvents() pumped for the future to
        ever report completion. Confirmed against the runtime module, not
        the (incomplete) stubs.

        FIX 2: right after generateToolpath()/generateAllToolpaths() returns,
        the background job has not actually been dispatched yet — reading
        isGenerationCompleted at that instant raises RuntimeError("3 :
        Generation not started"), not "not completed". A doEvents() pump is
        needed before the first read, and the same transient error is
        treated as "not done yet" rather than a real failure.

        FIX 3: found live — if generation never actually dispatches within
        the whole timeout window (observed with an operation whose geometry
        selection had failed, leaving it stuck), isGenerationCompleted keeps
        raising "not started" on every iteration, and the ORIGINAL timeout
        message crashed too: it read future.numberOfCompleted /
        numberOfOperations unconditionally, which raise the exact same
        RuntimeError in that state. Result was an unhandled crash instead of
        the intended clean timeout message. Both reads are now guarded the
        same way as isGenerationCompleted above.
        """
        adsk.doEvents()
        deadline = time.monotonic() + timeout
        while True:
            try:
                done = future.isGenerationCompleted
            except RuntimeError:
                done = False  # generation not dispatched to the worker yet
            if done:
                return
            if time.monotonic() > deadline:
                try:
                    progress = f"{future.numberOfCompleted}/{future.numberOfOperations}"
                except RuntimeError:
                    progress = "0/? (generation never started)"
                raise RuntimeError(
                    f"Toolpath generation did not finish within {timeout}s. "
                    f"{progress} operations completed. It may still finish "
                    "in the background — check with cam_list_operations "
                    "before regenerating."
                )
            time.sleep(0.1)
            adsk.doEvents()

    @staticmethod
    def _guard_toolless(ops):
        """Refuse to generate operations that have no real tool attached.

        FIX (fork): generating a toolless operation does NOT fail as an API
        error — Fusion pops a MODAL error dialog on the main thread ("Falha
        ao criar percurso; nenhuma ferramenta selecionada"). That dialog
        blocks the main thread, so the add-in stops servicing its socket and
        the whole bridge goes dead — even ping times out — until a human
        clicks OK in the Fusion window. Observed twice before being
        diagnosed. Checking op.tool up front is the only way to keep a
        recoverable error on this side of the bridge.
        """
        toolless = []
        for op in ops:
            try:
                if op.tool is None:
                    toolless.append(op.name)
            except Exception:
                continue
        if toolless:
            raise RuntimeError(
                "Refusing to generate — these operations have no tool "
                f"attached: {', '.join(toolless)}. Generating them would "
                "open a modal error dialog inside Fusion and freeze this "
                "connection until it is dismissed by hand. Attach a tool "
                "first (cam_create_operation's tool_from_operation, or the "
                "Fusion UI)."
            )

    def cam_generate_toolpath(
        self,
        setup_name: str = None,
        operation_name: str = None,
        generate_all: bool = False,
    ):
        cam = self._get_cam()

        if generate_all:
            all_ops = []
            for s in cam.setups:
                for i in range(s.operations.count):
                    all_ops.append(s.operations.item(i))
            self._guard_toolless(all_ops)
            future = cam.generateAllToolpaths(False)
            self._wait_future(future)
            return {"generated": True, "scope": "all"}

        if operation_name and setup_name:
            setup = self._find_setup(cam, setup_name)
            op = self._find_operation(setup, operation_name)
            self._guard_toolless([op])
            future = cam.generateToolpath(op)
            self._wait_future(future)
            return {
                "generated": True,
                "scope": "operation",
                "operation": operation_name,
            }

        if setup_name:
            setup = self._find_setup(cam, setup_name)
            self._guard_toolless(
                [setup.operations.item(i) for i in range(setup.operations.count)]
            )
            ops = adsk.core.ObjectCollection.create()
            for i in range(setup.operations.count):
                ops.add(setup.operations.item(i))
            future = cam.generateToolpath(ops)
            self._wait_future(future)
            return {"generated": True, "scope": "setup", "setup": setup_name}

        raise RuntimeError("Provide setup_name, operation_name, or generate_all=true")

    def cam_post_process(
        self,
        setup_name: str,
        operation_name: str = None,
        post_processor: str = "fanuc",
        output_folder: str = None,
        output_units: str = "mm",
        program_name: str = "1001",
    ):
        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)

        if not output_folder:
            output_folder = os.path.join(os.path.expanduser("~"), "Desktop")

        # Accept a full path to a .cps file, or resolve a short name against
        # the legacy local post folder when the build still provides one.
        if post_processor.endswith(".cps") or os.path.sep in post_processor:
            post_config = post_processor
        else:
            post_folder = getattr(cam, "genericPostFolder", None)
            if not post_folder:
                raise RuntimeError(
                    "This Fusion build has no local generic post folder "
                    "(posts are cloud-library based). Pass the full path to "
                    "the .cps file in 'post_processor' instead of a short "
                    "name."
                )
            post_config = os.path.join(post_folder, f"{post_processor}.cps")

        if not os.path.isfile(post_config):
            raise RuntimeError(f"Post processor not found: {post_config}")

        units = (
            adsk.cam.PostOutputUnitOptions.MillimetersOutput
            if output_units == "mm"
            else adsk.cam.PostOutputUnitOptions.InchesOutput
        )

        # FIX (fork): the first argument to PostProcessInput.create() is the
        # NC program NAME/NUMBER (PostProcessInput.programName), not a label
        # for the setup. Passing setup_name (e.g. "Setup1 (2)") here made
        # posts with programNameIsInteger=true (fanuc and most others) fail
        # with "Program number 'NaN' is out of range" -- confirmed against
        # this exact traceback on the fanuc.cps shipped with 2704.1.53.
        # program_name defaults to a plain numeric string so it works for
        # both integer- and string-accepting posts.
        post_input = adsk.cam.PostProcessInput.create(
            program_name, post_config, output_folder, units
        )
        post_input.isOpenInEditor = False

        if operation_name:
            op = self._find_operation(setup, operation_name)
            cam.postProcess(op, post_input)
        else:
            cam.postProcess(setup, post_input)

        return {
            "setup": setup_name,
            "post_processor": post_processor,
            "output_folder": output_folder,
            "units": output_units,
            "program_name": program_name,
        }

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def ping(self):
        return {"pong": True}

    # ------------------------------------------------------------------
    # Design type safety
    # ------------------------------------------------------------------

    def get_design_type(self):
        """Return current design type: 'parametric' or 'direct'."""
        design = self._design()
        dt = design.designType
        is_parametric = dt == adsk.fusion.DesignTypes.ParametricDesignType
        return {
            "design_type": "parametric" if is_parametric else "direct",
            "design_type_id": dt,
        }

    def set_design_type(self, design_type: str):
        """Switch design type. Use 'parametric' to recover from accidental
        direct-mode switches (equivalent to UI 'Capture Design History')."""
        design = self._design()
        current = design.designType

        if design_type == "parametric":
            target = adsk.fusion.DesignTypes.ParametricDesignType
            if current == target:
                return {
                    "changed": False,
                    "design_type": "parametric",
                    "message": "Already in parametric mode",
                }
            design.designType = target
            adsk.doEvents()
            # Verify it actually changed
            if design.designType != target:
                raise RuntimeError(
                    "Failed to switch to parametric mode. "
                    "Try 'Capture Design History' in the Fusion UI."
                )
            return {"changed": True, "design_type": "parametric"}

        elif design_type == "direct":
            target = adsk.fusion.DesignTypes.DirectDesignType
            if current == target:
                return {
                    "changed": False,
                    "design_type": "direct",
                    "message": "Already in direct mode",
                }
            design.designType = target
            adsk.doEvents()
            return {"changed": True, "design_type": "direct"}

        else:
            raise RuntimeError(
                f"Invalid design_type '{design_type}'. Use 'parametric' or 'direct'."
            )

    # ------------------------------------------------------------------
    # Code execution (REPL-style)
    # ------------------------------------------------------------------

    def execute_code(self, code: str):
        design = self._design()
        type_before = design.designType

        from .event_bridge import late_results

        ns = {
            "adsk": adsk,
            "app": self.app,
            "ui": self.ui,
            "design": design,
            "component": self._root(),
            "math": math,
            # results of commands that finished after their caller timed out
            "late_results": late_results,
        }

        buf = io.StringIO()

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise RuntimeError(f"SyntaxError: {exc}")

        last_expr_value = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last_node = tree.body.pop()
            if tree.body:
                with redirect_stdout(buf):
                    exec(
                        compile(
                            ast.Module(body=tree.body, type_ignores=[]), "<mcp>", "exec"
                        ),
                        ns,
                    )
            expr_code = compile(ast.Expression(body=last_node.value), "<mcp>", "eval")
            with redirect_stdout(buf):
                last_expr_value = eval(expr_code, ns)
        else:
            with redirect_stdout(buf):
                exec(compile(tree, "<mcp>", "exec"), ns)

        output = buf.getvalue()
        result = last_expr_value if last_expr_value is not None else output

        # Warn if design type changed during execution
        # FIX (fork): if the code opened/closed a document, the captured
        # `design` can be dead ("An API Object refers to a deleted Object")
        # and this post-check turned a SUCCESSFUL run into an error, losing
        # its result -- confirmed live: documents.open() replaced the empty
        # untitled document. Re-read the active design instead.
        document_changed = False
        try:
            type_after = design.designType
        except Exception:
            document_changed = True
            try:
                type_after = self._design().designType
            except Exception:
                type_after = type_before
        design_type_warning = None
        if not document_changed and type_before != type_after:
            parametric = adsk.fusion.DesignTypes.ParametricDesignType
            design_type_warning = (
                f"WARNING: Design type changed from "
                f"{'parametric' if type_before == parametric else 'direct'} to "
                f"{'parametric' if type_after == parametric else 'direct'} "
                f"during code execution. Use set_design_type to recover."
            )
            log.warning(design_type_warning)
        if result is not None:
            try:
                import json as _json

                _json.dumps(result)
            except (TypeError, ValueError):
                result = str(result)

        response = {"executed": True, "result": result, "output": output}
        if document_changed:
            response["note"] = (
                "The active document changed during execution; the "
                "pre-defined `design` name referred to the previous one."
            )
        if design_type_warning:
            response["design_type_warning"] = design_type_warning
        return response

    # ------------------------------------------------------------------
    # Camera helper
    # ------------------------------------------------------------------

    def _camera_info(self):
        try:
            cam = self.app.activeViewport.camera
            return {
                "eye": [cam.eye.x, cam.eye.y, cam.eye.z],
                "target": [cam.target.x, cam.target.y, cam.target.z],
                "up_vector": [cam.upVector.x, cam.upVector.y, cam.upVector.z],
            }
        except Exception:
            return None

    @staticmethod
    def _bbox_dict(bbox):
        return {
            "min": [bbox.minPoint.x, bbox.minPoint.y, bbox.minPoint.z],
            "max": [bbox.maxPoint.x, bbox.maxPoint.y, bbox.maxPoint.z],
        }

    # ------------------------------------------------------------------
    # Mutation snapshot (before/after deltas for feedback)
    # ------------------------------------------------------------------

    def _snapshot(self) -> dict | None:
        """Capture body_count, overall bbox, and total mass of the design.

        Best-effort — returns None if the design isn't readable yet.  Mass
        is reported in grams; bbox in cm (Fusion's internal unit).
        """
        try:
            design = self.app.activeProduct
            if design is None or not hasattr(design, "rootComponent"):
                return None
            root = design.rootComponent

            # Count bodies recursively (root + occurrences).
            body_count = root.bRepBodies.count
            try:
                for occ in design.rootComponent.allOccurrences:
                    body_count += occ.bRepBodies.count
            except Exception:
                pass  # allOccurrences can fail on empty designs

            bbox_dict = None
            if body_count > 0:
                try:
                    bbox = root.boundingBox
                    if bbox is not None:
                        bbox_dict = self._bbox_dict(bbox)
                except Exception:
                    bbox_dict = None

            mass_g = 0.0
            if body_count > 0:
                try:
                    # physicalProperties.mass is in kg.  Sum occurrence
                    # bodies explicitly so mass_g stays consistent with
                    # body_count (which includes occurrence bodies).
                    mass_kg = float(root.physicalProperties.mass)
                    for occ in root.allOccurrences:
                        try:
                            mass_kg += float(occ.physicalProperties.mass)
                        except Exception:
                            pass
                    mass_g = mass_kg * 1000.0
                except Exception:
                    mass_g = 0.0

            try:
                doc_name = self.app.activeDocument.name
            except Exception:
                doc_name = None
            return {
                "body_count": body_count,
                "bbox": bbox_dict,
                "mass_g": mass_g,
                "document": doc_name,
            }
        except Exception as exc:
            log.debug("snapshot failed: %s", exc)
            return None

    @staticmethod
    def _compute_deltas(before: dict, after: dict) -> dict:
        """Return a diff suitable for an agent: counts + masses + bboxes."""
        deltas = {
            "body_count_before": before.get("body_count", 0),
            "body_count_after": after.get("body_count", 0),
            "body_count_delta": after.get("body_count", 0)
            - before.get("body_count", 0),
            "mass_g_before": before.get("mass_g", 0.0),
            "mass_g_after": after.get("mass_g", 0.0),
            "mass_g_delta": after.get("mass_g", 0.0) - before.get("mass_g", 0.0),
            "bbox_before": before.get("bbox"),
            "bbox_after": after.get("bbox"),
        }
        # FIX (fork): when the command switched/closed documents the two
        # snapshots belong to DIFFERENT designs; "126 -> 0 bodies" read as a
        # mass deletion (confirmed live). Flag it.
        if before.get("document") != after.get("document"):
            deltas["document_changed"] = {
                "from": before.get("document"),
                "to": after.get("document"),
            }
        return deltas

    # ------------------------------------------------------------------
    # Viewport render (perception)
    # ------------------------------------------------------------------

    def render_view(
        self,
        view: str = "current",
        width: int = 1024,
        height: int = 768,
        fit: bool = True,
    ):
        """Save the active viewport to a PNG and return base64-encoded bytes.

        * ``view`` — ``"current"`` keeps the existing camera, or one of
          ``_VIEW_DIRS`` keys (iso, front, top, ...) to reposition first.
        * ``width``/``height`` — pixel dimensions.
        * ``fit`` — call viewport.fit() before capture so the model frames.

        If ``view != "current"``, the camera is restored to its prior state
        before returning so the user's view isn't disturbed.
        """
        viewport = self.app.activeViewport
        if viewport is None:
            raise RuntimeError("No active viewport")

        # Clamp dimensions — an oversized capture would stall the main
        # thread and produce an enormous base64 payload.
        width = max(16, min(int(width), 4096))
        height = max(16, min(int(height), 4096))

        repositioned = view != "current"
        if repositioned:
            spec = self._VIEW_DIRS.get(view)
            if spec is None:
                raise RuntimeError(
                    f"Unknown view '{view}'. "
                    f"Expected: current, {', '.join(self._VIEW_DIRS)}"
                )
            orig = viewport.camera
            orig_state = {
                "eye": (orig.eye.x, orig.eye.y, orig.eye.z),
                "target": (orig.target.x, orig.target.y, orig.target.z),
                "up": (orig.upVector.x, orig.upVector.y, orig.upVector.z),
                "type": orig.cameraType,
            }
            self._orient_camera(viewport, spec)

        try:
            if fit:
                try:
                    viewport.fit()
                except Exception:
                    pass  # fit() can fail on empty designs; keep going

            # saveAsImageFile requires a real path; write to a tempfile.
            fd, path = tempfile.mkstemp(suffix=".png", prefix="fusion_render_")
            os.close(fd)
            try:
                ok = viewport.saveAsImageFile(path, int(width), int(height))
                if not ok or not os.path.exists(path):
                    raise RuntimeError("saveAsImageFile returned false")
                with open(path, "rb") as f:
                    data = f.read()
            finally:
                try:
                    os.remove(path)
                except Exception:
                    pass
        finally:
            if repositioned:
                cam = viewport.camera
                cam.isSmoothTransition = False
                cam.cameraType = orig_state["type"]
                cam.eye = adsk.core.Point3D.create(*orig_state["eye"])
                cam.target = adsk.core.Point3D.create(*orig_state["target"])
                cam.upVector = adsk.core.Vector3D.create(*orig_state["up"])
                viewport.camera = cam
                try:
                    viewport.refresh()
                except Exception:
                    pass

        return {
            "view": view,
            "width": width,
            "height": height,
            "image_format": "png",
            "image_base64": base64.b64encode(data).decode("ascii"),
            "bytes": len(data),
        }

    def _orient_camera(self, viewport, spec):
        """Position the camera at a canonical view relative to the model.

        ``spec`` is ``(eye_dir, up_vec)`` from ``_VIEW_DIRS``.
        """
        eye_dir, up_vec = spec
        # FIX (fork): app.activeProduct returns whatever product is active,
        # not necessarily Design -- with the Manufacture workspace active
        # (e.g. right after any cam_* call) it returns the CAM product,
        # which has no rootComponent, crashing render_view with
        # "'CAM' object has no attribute 'rootComponent'". _design() does
        # the explicit DesignProductType lookup that the rest of this file
        # already uses for exactly this reason (see its own docstring).
        try:
            design = self._design()
        except Exception:
            design = None
        root = design.rootComponent if design is not None else None

        # Target is the model centroid (or origin if no bodies).
        target = adsk.core.Point3D.create(0.0, 0.0, 0.0)
        distance = 20.0
        if root is not None and root.bRepBodies.count > 0:
            try:
                bbox = root.boundingBox
                if bbox is not None:
                    cx = (bbox.minPoint.x + bbox.maxPoint.x) * 0.5
                    cy = (bbox.minPoint.y + bbox.maxPoint.y) * 0.5
                    cz = (bbox.minPoint.z + bbox.maxPoint.z) * 0.5
                    target = adsk.core.Point3D.create(cx, cy, cz)
                    dx = bbox.maxPoint.x - bbox.minPoint.x
                    dy = bbox.maxPoint.y - bbox.minPoint.y
                    dz = bbox.maxPoint.z - bbox.minPoint.z
                    distance = max(dx, dy, dz, 1.0) * 2.5
            except Exception:
                pass

        eye = adsk.core.Point3D.create(
            target.x + eye_dir[0] * distance,
            target.y + eye_dir[1] * distance,
            target.z + eye_dir[2] * distance,
        )
        up = adsk.core.Vector3D.create(up_vec[0], up_vec[1], up_vec[2])

        cam = viewport.camera
        cam.eye = eye
        cam.target = target
        cam.upVector = up
        cam.isSmoothTransition = False
        viewport.camera = cam
