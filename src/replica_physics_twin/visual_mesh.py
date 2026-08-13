"""Build a deterministic Unreal-ready visual mesh from Replica PLY data."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any

from .office0_analysis import _parse_ply_header, _read_property, parse_binary_ply


def _format_float(value: float) -> str:
    return format(float(value), ".9g")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_mesh_header(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    with path.open("rb") as stream:
        format_name, _, elements = _parse_ply_header(stream)
    if format_name != "binary_little_endian 1.0":
        raise ValueError(f"Unsupported PLY format: {format_name}")
    vertex_element = next((element for element in elements if element["name"] == "vertex"), None)
    face_element = next((element for element in elements if element["name"] == "face"), None)
    if vertex_element is None or face_element is None:
        raise ValueError("PLY must contain vertex and face elements")
    return elements, vertex_element, face_element


def _write_material(path: Path) -> None:
    path.write_text(
        """# Phase 4 neutral material; source textures are intentionally deferred.
newmtl Office0Neutral
Ka 0.18 0.19 0.21
Kd 0.62 0.65 0.70
Ks 0.05 0.05 0.05
Ns 24.0
d 1.0
illum 2
""",
        encoding="ascii",
        newline="\n",
    )


def build_visual_mesh(
    scene_dir: Path,
    output_obj: Path,
    transform_metadata: Path,
    *,
    mesh_relative_path: str = "mesh.ply",
    output_binary: Path | None = None,
) -> dict[str, Any]:
    """Convert a Replica binary PLY into a centered centimeter-unit OBJ.

    The source coordinates are kept right-handed with Z up. The derived mesh is
    translated so the horizontal bounds are centered at the origin and the
    lowest source vertex is at Z=0. Unreal's default centimeter unit is used for
    the OBJ output, while the transform metadata retains the source meter data.
    """

    scene_dir = Path(scene_dir).resolve()
    source_path = scene_dir / mesh_relative_path
    output_obj = Path(output_obj).resolve()
    transform_metadata = Path(transform_metadata).resolve()
    output_binary = (
        output_obj.with_suffix(".rptmesh") if output_binary is None else Path(output_binary).resolve()
    )
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if output_obj.suffix.lower() != ".obj":
        raise ValueError("output_obj must have a .obj extension")
    if output_obj == source_path or source_path in output_obj.parents:
        raise ValueError("derived OBJ must not be written inside the source scene")
    if output_binary == source_path or source_path in output_binary.parents:
        raise ValueError("derived binary mesh must not be written inside the source scene")

    mesh_stats = parse_binary_ply(source_path)
    bounds_min = [float(value) for value in mesh_stats["bounds"]["min"]]
    bounds_max = [float(value) for value in mesh_stats["bounds"]["max"]]
    horizontal_center = [
        (bounds_min[0] + bounds_max[0]) / 2.0,
        (bounds_min[1] + bounds_max[1]) / 2.0,
    ]
    translation_m = [-horizontal_center[0], -horizontal_center[1], -bounds_min[2]]
    output_bounds_min_cm = [
        (bounds_min[0] + translation_m[0]) * 100.0,
        (bounds_min[1] + translation_m[1]) * 100.0,
        (bounds_min[2] + translation_m[2]) * 100.0,
    ]
    output_bounds_max_cm = [
        (bounds_max[0] + translation_m[0]) * 100.0,
        (bounds_max[1] + translation_m[1]) * 100.0,
        (bounds_max[2] + translation_m[2]) * 100.0,
    ]

    _, vertex_element, face_element = _read_mesh_header(source_path)
    vertex_properties = vertex_element["properties"]
    vertex_property_names = {
        property_spec["name"] for property_spec in vertex_properties if property_spec["kind"] == "scalar"
    }
    has_normals = {"nx", "ny", "nz"}.issubset(vertex_property_names)
    interior_normals_flipped = has_normals

    output_obj.parent.mkdir(parents=True, exist_ok=True)
    output_binary.parent.mkdir(parents=True, exist_ok=True)
    material_path = output_obj.with_suffix(".mtl")
    _write_material(material_path)

    vertex_count = 0
    face_count = 0
    index_count = 0
    with (
        source_path.open("rb") as source,
        output_obj.open("w", encoding="ascii", newline="\n") as target,
        output_binary.open("wb") as binary,
    ):
        binary.write(b"RPTMESH1")
        binary.write(struct.pack("<II", int(vertex_element["count"]), 0))
        _parse_ply_header(source)
        target.write("# Replica office_0 derived visual mesh\n")
        target.write(f"mtllib {material_path.name}\n")
        target.write("o office_0_visual\n")
        target.write("usemtl Office0Neutral\n")
        target.write("s 1\n")

        for _ in range(int(vertex_element["count"])):
            values: dict[str, Any] = {}
            for property_spec in vertex_properties:
                values[property_spec["name"]] = _read_property(source, property_spec)
            x = (float(values["x"]) + translation_m[0]) * 100.0
            y = (float(values["y"]) + translation_m[1]) * 100.0
            z = (float(values["z"]) + translation_m[2]) * 100.0
            target.write(f"v {_format_float(x)} {_format_float(y)} {_format_float(z)}\n")
            binary.write(struct.pack("<fff", x, y, z))
            vertex_count += 1

        # Replica's room mesh stores outward-facing normals. The Phase 4 camera
        # is placed inside the room, so flip normals for interior lighting while
        # keeping source winding and positions unchanged.
        if has_normals:
            source.seek(0)
            _parse_ply_header(source)
            for _ in range(int(vertex_element["count"])):
                values = {}
                for property_spec in vertex_properties:
                    values[property_spec["name"]] = _read_property(source, property_spec)
                normal = (
                    -float(values["nx"]),
                    -float(values["ny"]),
                    -float(values["nz"]),
                )
                target.write("vn " + " ".join(_format_float(value) for value in normal) + "\n")
                binary.write(
                    struct.pack(
                        "<fff",
                        *normal,
                    )
                )

            # Skip the vertex block a second time so the face stream is aligned.
            source.seek(0)
            _parse_ply_header(source)
            for _ in range(int(vertex_element["count"])):
                for property_spec in vertex_properties:
                    _read_property(source, property_spec)
        else:
            for _ in range(vertex_count):
                binary.write(struct.pack("<fff", 0.0, 0.0, -1.0))

        face_properties = face_element["properties"]
        for _ in range(int(face_element["count"])):
            values = {}
            for property_spec in face_properties:
                values[property_spec["name"]] = _read_property(source, property_spec)
            indices = values.get("vertex_indices")
            if not isinstance(indices, list) or len(indices) < 3:
                raise ValueError("PLY face must contain at least three vertex indices")
            if any(not isinstance(index, int) or index < 0 or index >= vertex_count for index in indices):
                raise ValueError("PLY face contains an out-of-range vertex index")
            if has_normals:
                face_tokens = [f"{index + 1}//{index + 1}" for index in indices]
            else:
                face_tokens = [str(index + 1) for index in indices]
            target.write("f " + " ".join(face_tokens) + "\n")
            for index in range(1, len(indices) - 1):
                binary.write(struct.pack("<III", indices[0], indices[index], indices[index + 1]))
                index_count += 3
            face_count += 1

        binary.seek(12)
        binary.write(struct.pack("<I", index_count))

    metadata = {
        "schema_version": 1,
        "scene_id": "office_0",
        "source_mesh": mesh_relative_path,
        "source_scene": str(scene_dir),
        "source_mesh_sha256": _sha256(source_path),
        "source_units": "meter",
        "output_units": "centimeter",
        "up_axis": "Z",
        "coordinate_transform": {
            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
            "translation_m": translation_m,
            "scale_cm_per_m": 100.0,
        },
        "source_bounds_m": {"min": bounds_min, "max": bounds_max},
        "output_bounds_cm": {"min": output_bounds_min_cm, "max": output_bounds_max_cm},
        "vertex_count": vertex_count,
        "face_count": face_count,
        "index_count": index_count,
        "triangle_count": index_count // 3,
        "normal_count": vertex_count if has_normals else 0,
        "interior_normals_flipped": interior_normals_flipped,
        "material": material_path.name,
        "runtime_binary": output_binary.name,
        "visual_only": True,
    }
    transform_metadata.parent.mkdir(parents=True, exist_ok=True)
    transform_metadata.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata


def build_visual_mesh_variant(
    scene_dir: Path,
    output_obj: Path,
    transform_metadata: Path,
    *,
    output_binary: Path | None = None,
    object_ids: set[int] | None = None,
    exclude_object_ids: set[int] | None = None,
    mesh_relative_path: str = "mesh_semantic.ply",
    local_origin_m: list[float] | None = None,
) -> dict[str, Any]:
    """Build a filtered semantic visual mesh variant.

    ``object_ids`` keeps only faces belonging to the requested semantic
    instances. ``exclude_object_ids`` removes those instances from a static
    room mesh. When a selected instance has no explicit local origin, its
    selected-vertex center is used so the resulting mesh can follow a dynamic
    actor transform.
    """

    scene_dir = Path(scene_dir).resolve()
    source_path = scene_dir / mesh_relative_path
    output_obj = Path(output_obj).resolve()
    transform_metadata = Path(transform_metadata).resolve()
    output_binary = (
        output_obj.with_suffix(".rptmesh") if output_binary is None else Path(output_binary).resolve()
    )
    object_ids = None if object_ids is None else {int(value) for value in object_ids}
    exclude_object_ids = set() if exclude_object_ids is None else {int(value) for value in exclude_object_ids}
    if object_ids is not None and object_ids & exclude_object_ids:
        raise ValueError("object_ids and exclude_object_ids must be disjoint")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if output_obj.suffix.lower() != ".obj":
        raise ValueError("output_obj must have a .obj extension")
    if output_obj == source_path or source_path in output_obj.parents:
        raise ValueError("derived OBJ must not be written inside the source scene")
    if output_binary == source_path or source_path in output_binary.parents:
        raise ValueError("derived binary mesh must not be written inside the source scene")

    mesh_stats = parse_binary_ply(source_path)
    bounds_min = [float(value) for value in mesh_stats["bounds"]["min"]]
    bounds_max = [float(value) for value in mesh_stats["bounds"]["max"]]
    horizontal_center = [
        (bounds_min[0] + bounds_max[0]) / 2.0,
        (bounds_min[1] + bounds_max[1]) / 2.0,
    ]
    scene_translation_m = [-horizontal_center[0], -horizontal_center[1], -bounds_min[2]]
    elements, vertex_element, face_element = _read_mesh_header(source_path)
    del elements
    vertex_properties = vertex_element["properties"]
    face_properties = face_element["properties"]
    vertex_property_names = {
        property_spec["name"] for property_spec in vertex_properties if property_spec["kind"] == "scalar"
    }
    has_normals = {"nx", "ny", "nz"}.issubset(vertex_property_names)

    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    selected_faces: list[list[int]] = []
    selected_object_ids: set[int] = set()
    with source_path.open("rb") as source:
        _parse_ply_header(source)
        for _ in range(int(vertex_element["count"])):
            values: dict[str, Any] = {}
            for property_spec in vertex_properties:
                values[property_spec["name"]] = _read_property(source, property_spec)
            positions.append((float(values["x"]), float(values["y"]), float(values["z"])))
            normals.append(
                (
                    float(values.get("nx", 0.0)),
                    float(values.get("ny", 0.0)),
                    float(values.get("nz", 1.0)),
                )
            )

        for _ in range(int(face_element["count"])):
            values = {}
            for property_spec in face_properties:
                values[property_spec["name"]] = _read_property(source, property_spec)
            indices = values.get("vertex_indices")
            if not isinstance(indices, list) or len(indices) < 3:
                continue
            raw_object_id = values.get("object_id")
            object_id = int(raw_object_id) if isinstance(raw_object_id, (int, float)) else None
            if object_ids is not None and object_id not in object_ids:
                continue
            if object_id is not None and object_id in exclude_object_ids:
                continue
            if object_id is not None:
                selected_object_ids.add(object_id)
            selected_faces.append([int(index) for index in indices])

    if not selected_faces:
        raise ValueError("The requested visual mesh variant contains no faces")

    selected_triangles: list[tuple[int, int, int]] = []
    filtered_degenerate_triangle_count = 0
    for face in selected_faces:
        for fan_index in range(1, len(face) - 1):
            triangle = (int(face[0]), int(face[fan_index]), int(face[fan_index + 1]))
            if any(index < 0 or index >= len(positions) for index in triangle):
                raise ValueError("PLY face contains an out-of-range vertex index")
            if len(set(triangle)) != 3:
                filtered_degenerate_triangle_count += 1
                continue
            first, second, third = (positions[index] for index in triangle)
            edge_a = tuple(second[axis] - first[axis] for axis in range(3))
            edge_b = tuple(third[axis] - first[axis] for axis in range(3))
            cross = (
                edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
                edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
                edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
            )
            if sum(component * component for component in cross) <= 1.0e-16:
                filtered_degenerate_triangle_count += 1
                continue
            selected_triangles.append(triangle)

    if not selected_triangles:
        raise ValueError("The requested visual mesh variant contains no non-degenerate triangles")

    remapped_indices: dict[int, int] = {}
    selected_positions: list[tuple[float, float, float]] = []
    normal_accumulators: list[list[float]] = []
    remapped_faces: list[list[int]] = []
    for source_triangle in selected_triangles:
        remapped_face: list[int] = []
        for source_index in source_triangle:
            if source_index not in remapped_indices:
                remapped_indices[source_index] = len(selected_positions)
                selected_positions.append(positions[source_index])
                normal_accumulators.append([0.0, 0.0, 0.0])
            remapped_face.append(remapped_indices[source_index])
        remapped_faces.append(remapped_face)

        first, second, third = (positions[index] for index in source_triangle)
        edge_a = tuple(second[axis] - first[axis] for axis in range(3))
        edge_b = tuple(third[axis] - first[axis] for axis in range(3))
        cross = (
            edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
            edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
            edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
        )
        for remapped_index in remapped_face:
            for axis in range(3):
                normal_accumulators[remapped_index][axis] += cross[axis]

    selected_bounds_min = [min(position[index] for position in selected_positions) for index in range(3)]
    selected_bounds_max = [max(position[index] for position in selected_positions) for index in range(3)]
    if local_origin_m is None and object_ids is not None:
        local_origin_m = [
            (selected_bounds_min[index] + selected_bounds_max[index]) / 2.0 for index in range(3)
        ]
    origin_m = [0.0, 0.0, 0.0] if local_origin_m is None else [float(value) for value in local_origin_m]
    if len(origin_m) != 3:
        raise ValueError("local_origin_m must contain exactly three values")
    output_translation_m = (
        [-origin_m[index] for index in range(3)]
        if object_ids is not None
        else list(scene_translation_m)
    )

    output_obj.parent.mkdir(parents=True, exist_ok=True)
    output_binary.parent.mkdir(parents=True, exist_ok=True)
    material_path = output_obj.with_suffix(".mtl")
    _write_material(material_path)
    triangle_count = sum(len(face) - 2 for face in remapped_faces)
    index_count = triangle_count * 3
    output_positions = [
        tuple((position[index] + output_translation_m[index]) * 100.0 for index in range(3))
        for position in selected_positions
    ]
    output_normals: list[tuple[float, float, float]] = []
    for accumulator in normal_accumulators:
        length = math.sqrt(sum(value * value for value in accumulator))
        if length <= 1.0e-12:
            output_normals.append((0.0, 0.0, -1.0))
        else:
            # Replica room winding faces outward.  The Unreal camera is inside
            # the room, so use the inward-facing normal for stable lighting.
            output_normals.append(tuple(-value / length for value in accumulator))

    with (
        output_obj.open("w", encoding="ascii", newline="\n") as target,
        output_binary.open("wb") as binary,
    ):
        binary.write(b"RPTMESH1")
        binary.write(struct.pack("<II", len(output_positions), index_count))
        target.write("# Replica office_0 semantic visual mesh variant\n")
        target.write(f"mtllib {material_path.name}\n")
        target.write("o office_0_visual_variant\n")
        target.write("usemtl Office0Neutral\n")
        target.write("s 1\n")
        for position in output_positions:
            target.write("v " + " ".join(_format_float(value) for value in position) + "\n")
            binary.write(struct.pack("<fff", *position))
        for normal in output_normals:
            target.write("vn " + " ".join(_format_float(value) for value in normal) + "\n")
            binary.write(struct.pack("<fff", *normal))
        for face in remapped_faces:
            face_tokens = [f"{index + 1}//{index + 1}" for index in face]
            target.write("f " + " ".join(face_tokens) + "\n")
            binary.write(struct.pack("<III", face[0], face[1], face[2]))

    output_bounds_min = [min(position[index] for position in output_positions) for index in range(3)]
    output_bounds_max = [max(position[index] for position in output_positions) for index in range(3)]
    metadata = {
        "schema_version": 1,
        "scene_id": "office_0",
        "variant": "semantic_instance_filter",
        "source_mesh": mesh_relative_path,
        "source_scene": str(scene_dir),
        "source_mesh_sha256": _sha256(source_path),
        "source_units": "meter",
        "output_units": "centimeter",
        "up_axis": "Z",
        "coordinate_transform": {
            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
            "translation_m": output_translation_m,
            "scene_translation_m": scene_translation_m,
            "local_origin_m": origin_m,
            "scale_cm_per_m": 100.0,
        },
        "source_bounds_m": {"min": bounds_min, "max": bounds_max},
        "selected_source_bounds_m": {"min": selected_bounds_min, "max": selected_bounds_max},
        "output_bounds_cm": {"min": output_bounds_min, "max": output_bounds_max},
        "selected_object_ids": sorted(selected_object_ids if object_ids is not None else object_ids or []),
        "excluded_object_ids": sorted(exclude_object_ids),
        "vertex_count": len(output_positions),
        "face_count": len(remapped_faces),
        "source_face_count": len(selected_faces),
        "filtered_degenerate_triangle_count": filtered_degenerate_triangle_count,
        "index_count": index_count,
        "triangle_count": triangle_count,
        "normal_count": len(output_normals),
        "interior_normals_flipped": True,
        "material": material_path.name,
        "runtime_binary": output_binary.name,
        "visual_only": True,
    }
    transform_metadata.parent.mkdir(parents=True, exist_ok=True)
    transform_metadata.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata
