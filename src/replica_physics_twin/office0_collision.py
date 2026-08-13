"""Build and validate a conservative MuJoCo collision proxy for Replica office_0."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import mujoco

from .office0_analysis import _parse_ply_header, _read_property


_BOX_HALF_SIZE_M = [0.05, 0.05, 0.05]
_FLOOR_THICKNESS_M = 0.04
_MIN_WALL_THICKNESS_M = 0.1
_MIN_GEOM_SIZE_M = 1.0e-5
_BOOKCASE_CLASS_NAMES = {
    "bookcase",
    "bookshelf",
    "shelving",
    "shelf",
    "rack",
    "cabinet",
    "base-cabinet",
    "wall-cabinet",
}

# These objects are visible solid furniture/fixtures in office_0.  They are
# promoted from semantic metadata to conservative fixed MuJoCo boxes so a
# selected dynamic object can collide with the environment instead of passing
# through the Replica visual mesh.  Small decorative objects remain excluded.
_STATIC_FURNITURE_PROXY_CLASSES = {
    "chair": "chair",
    "sofa": "sofa",
    "bin": "bin",
    "plant-stand": "plant_stand",
    "pillar": "pillar",
    "door": "door",
    "panel": "panel",
    "tv-screen": "screen",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _float_list(values: Any) -> list[float]:
    return [float(value) for value in values]


def _bounds_to_proxy(
    minimum: list[float],
    maximum: list[float],
    translation_m: list[float],
) -> dict[str, Any]:
    source_min = _float_list(minimum)
    source_max = _float_list(maximum)
    if len(source_min) != 3 or len(source_max) != 3:
        raise ValueError("A collision box must have three-dimensional bounds")
    if any(upper < lower for lower, upper in zip(source_min, source_max)):
        raise ValueError("Collision bounds must be ordered")
    normalized_min = [source_min[index] + translation_m[index] for index in range(3)]
    normalized_max = [source_max[index] + translation_m[index] for index in range(3)]
    size = [normalized_max[index] - normalized_min[index] for index in range(3)]
    if any(value <= _MIN_GEOM_SIZE_M for value in size):
        raise ValueError(f"Collision box is degenerate: {size}")
    center = [(normalized_min[index] + normalized_max[index]) / 2.0 for index in range(3)]
    return {
        "min_m": normalized_min,
        "max_m": normalized_max,
        "center_m": center,
        "size_m": size,
        "half_size_m": [value / 2.0 for value in size],
    }


def _manifest_records(manifest: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    for item in manifest.get("object_records", []):
        try:
            object_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        records[object_id] = dict(item)
    return records


def _oriented_bbox(record: Mapping[str, Any]) -> tuple[list[float], list[float]] | None:
    try:
        abb = record["oriented_bbox"]["abb"]
        center = _float_list(abb["center"])
        size = _float_list(abb["sizes"])
    except (KeyError, TypeError, ValueError):
        return None
    if len(center) != 3 or len(size) != 3 or any(value <= 0.0 for value in size):
        return None
    minimum = [center[index] - size[index] / 2.0 for index in range(3)]
    maximum = [center[index] + size[index] / 2.0 for index in range(3)]
    return minimum, maximum


def read_semantic_instance_bounds(
    semantic_mesh_path: Path,
    target_object_ids: set[int] | None = None,
) -> dict[int, dict[str, Any]]:
    """Read source-space AABBs from semantic mesh face instance IDs.

    The Replica semantic mesh has the same vertex positions as the visual mesh,
    with an ``object_id`` scalar on every face. This derives collision extents
    from the actual labeled geometry instead of trusting an annotation bbox that
    may be in a local frame.
    """

    semantic_mesh_path = Path(semantic_mesh_path).resolve()
    if not semantic_mesh_path.is_file():
        raise FileNotFoundError(semantic_mesh_path)

    with semantic_mesh_path.open("rb") as stream:
        format_name, _, elements = _parse_ply_header(stream)
        if format_name != "binary_little_endian 1.0":
            raise ValueError(f"Unsupported semantic mesh format: {format_name}")
        vertex_element = next((element for element in elements if element["name"] == "vertex"), None)
        face_element = next((element for element in elements if element["name"] == "face"), None)
        if vertex_element is None or face_element is None:
            raise ValueError("Semantic mesh must contain vertex and face elements")
        vertex_properties = vertex_element["properties"]
        face_properties = face_element["properties"]
        required_vertex_names = {"x", "y", "z"}
        if not required_vertex_names.issubset(
            {spec["name"] for spec in vertex_properties if spec["kind"] == "scalar"}
        ):
            raise ValueError("Semantic mesh is missing x/y/z vertex properties")
        if "object_id" not in {spec["name"] for spec in face_properties}:
            raise ValueError("Semantic mesh is missing face object_id property")

        vertices: list[tuple[float, float, float]] = []
        for _ in range(int(vertex_element["count"])):
            values = {
                spec["name"]: _read_property(stream, spec)
                for spec in vertex_properties
            }
            vertices.append((float(values["x"]), float(values["y"]), float(values["z"])))

        bounds: dict[int, dict[str, Any]] = {}
        for _ in range(int(face_element["count"])):
            values = {
                spec["name"]: _read_property(stream, spec)
                for spec in face_properties
            }
            object_id = int(values["object_id"])
            if target_object_ids is not None and object_id not in target_object_ids:
                continue
            record = bounds.setdefault(
                object_id,
                {
                    "min": [math.inf, math.inf, math.inf],
                    "max": [-math.inf, -math.inf, -math.inf],
                    "face_count": 0,
                },
            )
            for vertex_index in values["vertex_indices"]:
                try:
                    vertex = vertices[int(vertex_index)]
                except (IndexError, TypeError, ValueError) as error:
                    raise ValueError(f"Semantic face references invalid vertex: {vertex_index}") from error
                for axis in range(3):
                    record["min"][axis] = min(record["min"][axis], vertex[axis])
                    record["max"][axis] = max(record["max"][axis], vertex[axis])
            record["face_count"] += 1

    return {
        object_id: {
            "min": _float_list(record["min"]),
            "max": _float_list(record["max"]),
            "face_count": int(record["face_count"]),
        }
        for object_id, record in bounds.items()
        if record["face_count"] > 0 and all(math.isfinite(value) for value in [*record["min"], *record["max"]])
    }


def read_semantic_top_surface_bounds(
    semantic_mesh_path: Path,
    target_object_ids: set[int],
) -> dict[int, dict[str, Any]]:
    """Derive a thin top-surface box for table-like semantic instances.

    A full instance AABB fills the space between a tabletop and its floor,
    which is visually misleading and makes a desk proxy block objects below
    the desk. This pass keeps only near-horizontal upper faces near the highest
    z band of each requested instance.
    """

    semantic_mesh_path = Path(semantic_mesh_path).resolve()
    if not target_object_ids:
        return {}
    with semantic_mesh_path.open("rb") as stream:
        format_name, _, elements = _parse_ply_header(stream)
        if format_name != "binary_little_endian 1.0":
            raise ValueError(f"Unsupported semantic mesh format: {format_name}")
        vertex_element = next((element for element in elements if element["name"] == "vertex"), None)
        face_element = next((element for element in elements if element["name"] == "face"), None)
        if vertex_element is None or face_element is None:
            raise ValueError("Semantic mesh must contain vertex and face elements")
        vertices: list[tuple[float, float, float]] = []
        for _ in range(int(vertex_element["count"])):
            values = {
                spec["name"]: _read_property(stream, spec)
                for spec in vertex_element["properties"]
            }
            vertices.append((float(values["x"]), float(values["y"]), float(values["z"])))

        faces_by_object: dict[int, list[tuple[list[float], list[float]]]] = {
            object_id: [] for object_id in target_object_ids
        }
        for _ in range(int(face_element["count"])):
            values = {
                spec["name"]: _read_property(stream, spec)
                for spec in face_element["properties"]
            }
            object_id = int(values["object_id"])
            if object_id not in faces_by_object:
                continue
            face_vertices = [vertices[int(index)] for index in values["vertex_indices"]]
            minimum = [min(vertex[axis] for vertex in face_vertices) for axis in range(3)]
            maximum = [max(vertex[axis] for vertex in face_vertices) for axis in range(3)]
            faces_by_object[object_id].append((minimum, maximum))

    result: dict[int, dict[str, Any]] = {}
    for object_id, faces in faces_by_object.items():
        if not faces:
            continue
        object_min_z = min(face[0][2] for face in faces)
        object_max_z = max(face[1][2] for face in faces)
        object_height = object_max_z - object_min_z
        band = max(0.08, object_height * 0.15)
        face_span_limit = max(0.08, object_height * 0.2)
        selected = [
            face
            for face in faces
            if (face[0][2] + face[1][2]) / 2.0 >= object_max_z - band
            and face[1][2] - face[0][2] <= face_span_limit
        ]
        if not selected:
            selected = [face for face in faces if face[1][2] >= object_max_z - band]
        if not selected:
            continue
        minimum = [min(face[0][axis] for face in selected) for axis in range(3)]
        maximum = [max(face[1][axis] for face in selected) for axis in range(3)]
        if any(maximum[axis] - minimum[axis] <= _MIN_GEOM_SIZE_M for axis in range(3)):
            continue
        result[object_id] = {
            "min": minimum,
            "max": maximum,
            "face_count": len(selected),
            "selection": "upper near-horizontal semantic faces",
        }
    return result


def _record_bounds(
    object_id: int,
    records: Mapping[int, Mapping[str, Any]],
    measured_bounds: Mapping[int, Mapping[str, Any]],
) -> tuple[list[float], list[float], str, int]:
    measured = measured_bounds.get(object_id)
    if measured is not None:
        return (
            _float_list(measured["min"]),
            _float_list(measured["max"]),
            "semantic_mesh_face_vertices",
            int(measured.get("face_count", 0)),
        )
    fallback = _oriented_bbox(records.get(object_id, {}))
    if fallback is None:
        raise ValueError(f"No bounds available for semantic object {object_id}")
    return fallback[0], fallback[1], "manifest_oriented_bbox_fallback", 0


def _size(minimum: list[float], maximum: list[float]) -> list[float]:
    return [maximum[index] - minimum[index] for index in range(3)]


def _is_wall_box(minimum: list[float], maximum: list[float]) -> bool:
    sizes = _size(minimum, maximum)
    return max(sizes) >= 1.0 and min(sizes) >= _MIN_WALL_THICKNESS_M


def _is_valid_box(minimum: list[float], maximum: list[float]) -> bool:
    return all(value > _MIN_GEOM_SIZE_M for value in _size(minimum, maximum))


def _make_proxy(
    *,
    name: str,
    role: str,
    source_object_ids: list[int],
    source_class_names: list[str],
    minimum: list[float],
    maximum: list[float],
    translation_m: list[float],
    confidence: str,
    basis: str,
    face_counts: list[int],
    requires_user_confirmation: bool,
    provisional: bool = False,
) -> dict[str, Any]:
    proxy = _bounds_to_proxy(minimum, maximum, translation_m)
    return {
        "name": name,
        "role": role,
        "type": "box",
        "source_object_ids": source_object_ids,
        "source_class_names": source_class_names,
        "source_bounds_m": {"min": _float_list(minimum), "max": _float_list(maximum)},
        "basis": basis,
        "face_counts": face_counts,
        "confidence": confidence,
        "requires_user_confirmation": requires_user_confirmation,
        "provisional": provisional,
        **proxy,
    }


def _visual_bounds(visual_metadata: Mapping[str, Any]) -> tuple[list[float], list[float]]:
    output_bounds = visual_metadata.get("output_bounds_cm")
    if isinstance(output_bounds, Mapping):
        minimum = [float(value) / 100.0 for value in output_bounds["min"]]
        maximum = [float(value) / 100.0 for value in output_bounds["max"]]
        return minimum, maximum
    source_bounds = visual_metadata.get("source_bounds_m")
    translation = visual_metadata["coordinate_transform"]["translation_m"]
    return (
        [float(source_bounds["min"][index]) + float(translation[index]) for index in range(3)],
        [float(source_bounds["max"][index]) + float(translation[index]) for index in range(3)],
    )


def _candidate_ids(manifest: Mapping[str, Any], role: str) -> list[int]:
    raw = manifest.get("candidate_object_ids", {}).get(role, [])
    return sorted({int(object_id) for object_id in raw})


def _source_class_name(records: Mapping[int, Mapping[str, Any]], object_id: int) -> str:
    return str(records.get(object_id, {}).get("class_name", "unknown"))


def _make_test_bodies(proxies: list[dict[str, Any]], visual_min: list[float], visual_max: list[float]) -> list[dict[str, Any]]:
    by_role = {proxy["role"]: proxy for proxy in proxies}
    width = visual_max[0] - visual_min[0]
    depth = visual_max[1] - visual_min[1]
    floor = by_role["floor"]
    floor_probe = None
    # Keep the generic floor validation probe away from every visible static
    # proxy.  Once chairs/sofas/fixtures are included, the old fixed point
    # could legitimately land on a sofa and falsely report a floor failure.
    for width_fraction, depth_fraction in (
        (0.65, 0.25),
        (0.65, 0.75),
        (0.35, 0.25),
        (0.75, 0.50),
        (0.50, 0.20),
    ):
        candidate_x = visual_min[0] + width * width_fraction
        candidate_y = visual_min[1] + depth * depth_fraction
        occupied = any(
            proxy["role"] != "floor"
            and float(proxy["min_m"][0]) - 0.08 <= candidate_x <= float(proxy["max_m"][0]) + 0.08
            and float(proxy["min_m"][1]) - 0.08 <= candidate_y <= float(proxy["max_m"][1]) + 0.08
            for proxy in proxies
        )
        if not occupied:
            floor_probe = [candidate_x, candidate_y]
            break
    if floor_probe is None:
        floor_probe = [visual_min[0] + width * 0.5, visual_min[1] + depth * 0.5]
    bodies = [
        {
            "name": "drop_floor",
            "initial_position_m": [floor_probe[0], floor_probe[1], 1.2],
            "half_size_m": list(_BOX_HALF_SIZE_M),
            "mass_kg": 0.1,
            "support_proxy": floor["name"],
        }
    ]
    for proxy in proxies:
        if proxy["role"] not in {"desk", "bookcase"}:
            continue
        top_z = float(proxy["max_m"][2])
        initial_z = max(1.2, top_z + 0.6)
        if initial_z >= visual_max[2] - 0.1:
            initial_z = max(top_z + 0.2, visual_max[2] - 0.2)
        test_x = float(proxy["center_m"][0])
        test_y = float(proxy["center_m"][1])
        if proxy["role"] == "desk":
            # Some annotated tables sit immediately against a wall. Move the
            # probe a quarter-box toward the room interior while keeping it
            # over the measured tabletop footprint.
            test_x -= float(proxy["size_m"][0]) * 0.25
        else:
            # A future bookcase candidate may be against a rear wall; use its
            # room-facing quarter for a non-overlapping drop.
            test_y += float(proxy["size_m"][1]) * 0.25
        bodies.append(
            {
                "name": f"drop_{proxy['name']}",
                "initial_position_m": [test_x, test_y, initial_z],
                "half_size_m": list(_BOX_HALF_SIZE_M),
                "mass_kg": 0.1,
                "support_proxy": proxy["name"],
            }
        )
    return bodies


def build_collision_spec(
    manifest: Mapping[str, Any],
    visual_metadata: Mapping[str, Any],
    measured_bounds: Mapping[int, Mapping[str, Any]],
    *,
    dynamic_object_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Build a normalized meter-unit collision specification from derived data."""

    translation_m = _float_list(visual_metadata["coordinate_transform"]["translation_m"])
    visual_min, visual_max = _visual_bounds(visual_metadata)
    records = _manifest_records(manifest)
    proxies: list[dict[str, Any]] = []
    excluded_candidates: list[dict[str, Any]] = []
    unresolved_roles: list[dict[str, Any]] = []

    floor_ids = _candidate_ids(manifest, "floor")
    floor_min = [visual_min[0], visual_min[1], -_FLOOR_THICKNESS_M]
    floor_max = [visual_max[0], visual_max[1], 0.0]
    proxies.append(
        _make_proxy(
            name="floor",
            role="floor",
            source_object_ids=floor_ids,
            source_class_names=[_source_class_name(records, object_id) for object_id in floor_ids],
            minimum=floor_min,
            maximum=floor_max,
            translation_m=[0.0, 0.0, 0.0],
            confidence="medium",
            basis="visual_mesh_normalized_xy_bounds_with_z0_support_surface",
            face_counts=[int(measured_bounds.get(object_id, {}).get("face_count", 0)) for object_id in floor_ids],
            requires_user_confirmation=True,
        )
    )

    dynamic_ids = {int(object_id) for object_id in (dynamic_object_ids or [])}
    used_ids = set(floor_ids) | dynamic_ids
    for object_id in _candidate_ids(manifest, "wall"):
        try:
            minimum, maximum, basis, face_count = _record_bounds(object_id, records, measured_bounds)
        except ValueError as error:
            excluded_candidates.append({"role": "wall", "object_id": object_id, "reason": str(error)})
            continue
        if not _is_wall_box(minimum, maximum):
            excluded_candidates.append(
                {
                    "role": "wall",
                    "object_id": object_id,
                    "reason": "semantic geometry is too thin or too small for a wall box",
                    "source_size_m": _size(minimum, maximum),
                }
            )
            continue
        proxies.append(
            _make_proxy(
                name=f"wall_{object_id}",
                role="wall",
                source_object_ids=[object_id],
                source_class_names=[_source_class_name(records, object_id)],
                minimum=minimum,
                maximum=maximum,
                translation_m=translation_m,
                confidence="medium",
                basis=basis,
                face_counts=[face_count],
                requires_user_confirmation=True,
            )
        )
        used_ids.add(object_id)

    for object_id in _candidate_ids(manifest, "table"):
        if object_id in dynamic_ids:
            continue
        try:
            minimum, maximum, basis, face_count = _record_bounds(object_id, records, measured_bounds)
        except ValueError as error:
            excluded_candidates.append({"role": "desk", "object_id": object_id, "reason": str(error)})
            continue
        top_surface = measured_bounds.get(object_id, {}).get("top_surface")
        if isinstance(top_surface, Mapping):
            minimum = _float_list(top_surface["min"])
            maximum = _float_list(top_surface["max"])
            basis = f"{basis}_top_surface"
            face_count = int(top_surface.get("face_count", face_count))
        if not _is_valid_box(minimum, maximum):
            excluded_candidates.append({"role": "desk", "object_id": object_id, "reason": "degenerate table bounds"})
            continue
        proxies.append(
            _make_proxy(
                name=f"desk_{object_id}",
                role="desk",
                source_object_ids=[object_id],
                source_class_names=[_source_class_name(records, object_id)],
                minimum=minimum,
                maximum=maximum,
                translation_m=translation_m,
                confidence="medium",
                basis=basis,
                face_counts=[face_count],
                requires_user_confirmation=True,
            )
        )
        used_ids.add(object_id)

    # Add conservative static proxies for visible solid semantic objects that
    # are not part of the explicit floor/wall/table candidate lists.  Their
    # collision role is intentionally fixed: only objects explicitly marked
    # movable in the physical manifest become dynamic bodies.
    for object_id, record in sorted(records.items()):
        if object_id in used_ids:
            continue
        class_name = str(record.get("class_name", "")).strip().lower()
        proxy_stem = _STATIC_FURNITURE_PROXY_CLASSES.get(class_name)
        if proxy_stem is None:
            continue
        try:
            minimum, maximum, basis, face_count = _record_bounds(object_id, records, measured_bounds)
        except ValueError as error:
            excluded_candidates.append({"role": "furniture", "object_id": object_id, "reason": str(error)})
            continue
        if not _is_valid_box(minimum, maximum):
            excluded_candidates.append(
                {"role": "furniture", "object_id": object_id, "reason": "degenerate furniture bounds"}
            )
            continue
        proxies.append(
            _make_proxy(
                name=f"{proxy_stem}_{object_id}",
                role="furniture",
                source_object_ids=[object_id],
                source_class_names=[class_name],
                minimum=minimum,
                maximum=maximum,
                translation_m=translation_m,
                confidence="medium",
                basis=f"{basis}_static_furniture_aabb",
                face_counts=[face_count],
                requires_user_confirmation=True,
                provisional=True,
            )
        )
        used_ids.add(object_id)

    bookcase_ids = _candidate_ids(manifest, "bookcase")
    valid_bookcase_ids: list[int] = []
    for object_id in bookcase_ids:
        if object_id in dynamic_ids:
            continue
        try:
            minimum, maximum, basis, face_count = _record_bounds(object_id, records, measured_bounds)
        except ValueError as error:
            excluded_candidates.append({"role": "bookcase", "object_id": object_id, "reason": str(error)})
            continue
        if not _is_valid_box(minimum, maximum):
            excluded_candidates.append(
                {"role": "bookcase", "object_id": object_id, "reason": "degenerate bookcase bounds"}
            )
            continue
        proxies.append(
            _make_proxy(
                name=f"bookcase_{object_id}",
                role="bookcase",
                source_object_ids=[object_id],
                source_class_names=[_source_class_name(records, object_id)],
                minimum=minimum,
                maximum=maximum,
                translation_m=translation_m,
                confidence="medium",
                basis=basis,
                face_counts=[face_count],
                requires_user_confirmation=True,
            )
        )
        valid_bookcase_ids.append(object_id)
    if not valid_bookcase_ids:
        potential_unclassified_ids = sorted(
            object_id
            for object_id, record in records.items()
            if str(record.get("class_name", "")).lower() in {"undefined", "other"}
            and object_id in measured_bounds
        )
        semantic_class_names = {
            str(record.get("class_name", "")).strip().lower()
            for record in records.values()
            if str(record.get("class_name", "")).strip()
        }
        bookcase_labels_present = bool(semantic_class_names & _BOOKCASE_CLASS_NAMES)
        if bookcase_ids or bookcase_labels_present:
            bookcase_status = "unresolved"
            bookcase_reason = (
                "Bookcase-related semantic labels exist but no valid bookcase instance was selected; "
                "unclassified geometry is not promoted automatically"
            )
            requires_user_input = True
        else:
            bookcase_status = "not_present_in_scene"
            bookcase_reason = (
                "The office_0 semantic object inventory contains no bookcase/bookshelf/shelving/shelf/rack/cabinet instance; "
                "no collision proxy is applicable"
            )
            requires_user_input = False
        unresolved_roles.append(
            {
                "role": "bookcase",
                "status": bookcase_status,
                "reason": bookcase_reason,
                "candidate_object_ids": bookcase_ids,
                "potential_unclassified_object_ids": potential_unclassified_ids,
                "semantic_class_names_present": sorted(semantic_class_names),
                "requires_user_input": requires_user_input,
            }
        )

    outside_visual_bounds: list[str] = []
    tolerance = 0.05
    for proxy in proxies:
        minimum = proxy["min_m"]
        maximum = proxy["max_m"]
        if any(
            minimum[axis] < visual_min[axis] - tolerance or maximum[axis] > visual_max[axis] + tolerance
            for axis in (0, 1)
        ) or minimum[2] < visual_min[2] - tolerance or maximum[2] > visual_max[2] + tolerance:
            outside_visual_bounds.append(proxy["name"])

    alignment = {
        "passed": not outside_visual_bounds,
        "tolerance_m": tolerance,
        "visual_bounds_m": {"min": visual_min, "max": visual_max},
        "outside_visual_bounds": outside_visual_bounds,
    }
    test_bodies = _make_test_bodies(proxies, visual_min, visual_max)
    return {
        "schema_version": 1,
        "scene_id": str(manifest.get("scene_id", "office_0")),
        "coordinate_system": {
            "units": "meter",
            "up_axis": "Z",
            "source_to_collision_translation_m": translation_m,
            "visual_output_units": "centimeter",
            "physics_authority": "MuJoCo",
        },
        "proxy_policy": {
            "representation": "axis_aligned_box",
            "source": "Replica semantic mesh instance bounds plus visual room envelope floor",
            "visual_mesh_collision_separation": True,
            "unclassified_fallback_allowed": False,
        },
        "proxies": proxies,
        "dynamic_object_ids_excluded": sorted(dynamic_ids),
        "excluded_candidates": excluded_candidates,
        "unresolved_roles": unresolved_roles,
        "alignment_check": alignment,
        "test_bodies": test_bodies,
    }


def _fmt(value: float) -> str:
    return format(float(value), ".9g")


def render_collision_mjcf(spec: Mapping[str, Any]) -> str:
    """Render deterministic MJCF with fixed proxy boxes and drop test bodies."""

    lines = [
        '<mujoco model="office0_collision_proxy">',
        '  <compiler angle="radian" coordinate="local"/>',
        '  <option gravity="0 0 -9.81" timestep="0.002" integrator="Euler"/>',
        '  <default>',
        '    <geom friction="0.8 0.1 0.1" solref="0.005 1" solimp="0.9 0.95 0.001"/>',
        '  </default>',
        '  <worldbody>',
    ]
    for proxy in spec["proxies"]:
        center = " ".join(_fmt(value) for value in proxy["center_m"])
        half_size = " ".join(_fmt(value) for value in proxy["half_size_m"])
        lines.append(
            f'    <geom name="{proxy["name"]}" type="box" pos="{center}" size="{half_size}" contype="1" conaffinity="1"/>'
        )
    bodies = [*spec.get("test_bodies", []), *spec.get("dynamic_bodies", [])]
    for body in bodies:
        position = " ".join(_fmt(value) for value in body["initial_position_m"])
        half_size = " ".join(_fmt(value) for value in body["half_size_m"])
        friction = body.get("friction")
        friction_attribute = ""
        if friction is not None:
            friction_attribute = f' friction="{" ".join(_fmt(value) for value in friction)}"'
        lines.extend(
            [
                f'    <body name="{body["name"]}" pos="{position}">',
                '      <freejoint/>',
                f'      <geom name="{body["name"]}_geom" type="box" size="{half_size}" mass="{_fmt(body["mass_kg"])}"{friction_attribute}/>',
                '    </body>',
            ]
        )
    lines.extend(['  </worldbody>', '  <keyframe>'])
    qpos: list[float] = []
    qvel: list[float] = []
    for body in bodies:
        qpos.extend(body["initial_position_m"])
        qpos.extend([1.0, 0.0, 0.0, 0.0])
        qvel.extend([0.0] * 6)
    lines.append(
        f'    <key name="initial" qpos="{" ".join(_fmt(value) for value in qpos)}" qvel="{" ".join(_fmt(value) for value in qvel)}"/>'
    )
    lines.extend(['  </keyframe>', '</mujoco>', ''])
    return "\n".join(lines)


def build_collision_proxy(
    scene_dir: Path,
    manifest_path: Path,
    visual_metadata_path: Path,
    output_xml: Path,
    output_metadata: Path,
    *,
    dynamic_object_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Read source data and write the Phase 5 MJCF and provenance metadata."""

    scene_dir = Path(scene_dir).resolve()
    manifest_path = Path(manifest_path).resolve()
    visual_metadata_path = Path(visual_metadata_path).resolve()
    output_xml = Path(output_xml).resolve()
    output_metadata = Path(output_metadata).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    visual_metadata = json.loads(visual_metadata_path.read_text(encoding="utf-8"))
    records = _manifest_records(manifest)
    target_ids = set(records)
    semantic_mesh_path = scene_dir / "habitat" / "mesh_semantic.ply"
    measured_bounds = read_semantic_instance_bounds(semantic_mesh_path, target_ids)
    table_top_bounds = read_semantic_top_surface_bounds(
        semantic_mesh_path,
        set(_candidate_ids(manifest, "table")),
    )
    for object_id, top_bounds in table_top_bounds.items():
        if object_id in measured_bounds:
            measured_bounds[object_id]["top_surface"] = top_bounds
    spec = build_collision_spec(
        manifest,
        visual_metadata,
        measured_bounds,
        dynamic_object_ids=dynamic_object_ids,
    )
    spec["source"] = {
        "scene_dir": str(scene_dir),
        "semantic_mesh": str(semantic_mesh_path),
        "semantic_mesh_sha256": _sha256(semantic_mesh_path),
        "manifest": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "visual_transform_metadata": str(visual_metadata_path),
        "visual_transform_metadata_sha256": _sha256(visual_metadata_path),
        "source_data_modified": False,
    }
    output_xml.parent.mkdir(parents=True, exist_ok=True)
    output_metadata.parent.mkdir(parents=True, exist_ok=True)
    output_xml.write_text(render_collision_mjcf(spec), encoding="utf-8", newline="\n")
    output_metadata.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return spec


def _body_id(model: mujoco.MjModel, body_name: str) -> int:
    body_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name))
    if body_id < 0:
        raise ValueError(f"Unknown body: {body_name}")
    return body_id


def _body_speed(model: mujoco.MjModel, data: mujoco.MjData, body_id: int) -> float:
    joint_id = int(model.body_jntadr[body_id])
    dof_start = int(model.jnt_dofadr[joint_id])
    return math.sqrt(sum(float(data.qvel[dof_start + axis]) ** 2 for axis in range(3)))


def _body_contact_names(model: mujoco.MjModel, data: mujoco.MjData, body_id: int) -> list[str]:
    names: list[str] = []
    for index in range(int(data.ncon)):
        contact = data.contact[index]
        geom_ids = (int(contact.geom1), int(contact.geom2))
        if not any(int(model.geom_bodyid[geom_id]) == body_id for geom_id in geom_ids):
            continue
        for geom_id in geom_ids:
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
            if name is not None and int(model.geom_bodyid[geom_id]) != body_id:
                names.append(name)
    return sorted(set(names))


def run_multi_drop_validation(
    xml_path: Path,
    spec: Mapping[str, Any],
    output_dir: Path,
    *,
    max_steps: int = 3000,
) -> dict[str, Any]:
    """Drop all configured probes and check support, contact, and stability."""

    model = mujoco.MjModel.from_xml_path(str(Path(xml_path).resolve()))
    data = mujoco.MjData(model)
    if model.nkey > 0:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)

    proxy_by_name = {proxy["name"]: proxy for proxy in spec["proxies"]}
    state: dict[str, dict[str, Any]] = {}
    for body in spec["test_bodies"]:
        body_id = _body_id(model, body["name"])
        state[body["name"]] = {
            "body_id": body_id,
            "initial_z_m": float(data.xpos[body_id][2]),
            "min_z_m": float(data.xpos[body_id][2]),
            "first_contact_step": None,
            "contact_geom_names": set(),
        }

    for step in range(max_steps + 1):
        if step > 0:
            mujoco.mj_step(model, data)
        for body_name, record in state.items():
            body_id = int(record["body_id"])
            current_z = float(data.xpos[body_id][2])
            record["min_z_m"] = min(float(record["min_z_m"]), current_z)
            contact_names = _body_contact_names(model, data, body_id)
            if contact_names and record["first_contact_step"] is None:
                record["first_contact_step"] = step
            record["contact_geom_names"].update(contact_names)

    results: list[dict[str, Any]] = []
    passed = True
    for body in spec["test_bodies"]:
        body_name = body["name"]
        record = state[body_name]
        body_id = int(record["body_id"])
        support = proxy_by_name[body["support_proxy"]]
        expected_z = float(support["max_m"][2]) + float(body["half_size_m"][2])
        final_z = float(data.xpos[body_id][2])
        speed = _body_speed(model, data, body_id)
        finite = all(math.isfinite(value) for value in data.xpos[body_id]) and math.isfinite(speed)
        contact = record["first_contact_step"] is not None
        position_error = abs(final_z - expected_z)
        result = {
            "body_name": body_name,
            "support_proxy": support["name"],
            "initial_position_m": _float_list(body["initial_position_m"]),
            "initial_z_m": record["initial_z_m"],
            "min_z_m": record["min_z_m"],
            "final_position_m": [float(value) for value in data.xpos[body_id]],
            "expected_support_z_m": expected_z,
            "final_position_error_m": position_error,
            "final_speed_mps": speed,
            "first_contact_step": record["first_contact_step"],
            "contact_geom_names": sorted(record["contact_geom_names"]),
            "finite_state": finite,
            "passed": bool(contact and finite and speed <= 0.05 and position_error <= 0.02),
        }
        results.append(result)
        passed = passed and bool(result["passed"])

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": 1,
        "xml_path": str(Path(xml_path).resolve()),
        "model": {
            "timestep_s": float(model.opt.timestep),
            "gravity_mps2": [float(value) for value in model.opt.gravity],
            "body_count": int(model.nbody),
            "geom_count": int(model.ngeom),
            "fixed_proxy_count": len(spec["proxies"]),
        },
        "max_steps": max_steps,
        "drops": results,
        "passed": passed,
    }
    (output_dir / "phase5_collision_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output_dir / "phase5_collision_contacts.jsonl").write_text(
        "".join(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n" for result in results),
        encoding="utf-8",
        newline="\n",
    )
    return summary
