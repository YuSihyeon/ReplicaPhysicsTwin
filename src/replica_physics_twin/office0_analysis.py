"""Reproducible, dependency-free analysis for a Replica office_0 scene."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any, BinaryIO


_PLY_TYPES: dict[str, str] = {
    "char": "b",
    "int8": "b",
    "uchar": "B",
    "uint8": "B",
    "short": "h",
    "int16": "h",
    "ushort": "H",
    "uint16": "H",
    "int": "i",
    "int32": "i",
    "uint": "I",
    "uint32": "I",
    "float": "f",
    "float32": "f",
    "double": "d",
    "float64": "d",
}

_CANDIDATE_CLASS_NAMES: dict[str, set[str]] = {
    "floor": {"floor"},
    "wall": {"wall"},
    "table": {"table", "desk"},
    "bookcase": {"bookcase", "bookshelf", "shelving", "shelf"},
    "tissue_box": {
        "tissue-paper",
        "tissue-box",
        "tissue_box",
        "toilet-paper",
        "paper-towel",
    },
}


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    payload = stream.read(size)
    if len(payload) != size:
        raise ValueError(f"Unexpected EOF while reading {size} bytes")
    return payload


def _read_scalar(stream: BinaryIO, type_name: str) -> int | float:
    try:
        fmt = _PLY_TYPES[type_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported PLY scalar type: {type_name}") from exc
    return struct.unpack("<" + fmt, _read_exact(stream, struct.calcsize(fmt)))[0]


def _parse_ply_header(stream: BinaryIO) -> tuple[str, int, list[dict[str, Any]]]:
    lines: list[str] = []
    header_bytes = 0
    while True:
        raw_line = stream.readline()
        if not raw_line:
            raise ValueError("PLY header ended before end_header")
        header_bytes += len(raw_line)
        line = raw_line.decode("ascii").strip()
        lines.append(line)
        if line == "end_header":
            break

    if not lines or lines[0] != "ply":
        raise ValueError("File does not start with a PLY header")

    format_name = ""
    elements: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines[1:]:
        fields = line.split()
        if not fields or fields[0] in {"comment", "obj_info", "end_header"}:
            continue
        if fields[0] == "format" and len(fields) >= 3:
            format_name = f"{fields[1]} {fields[2]}"
        elif fields[0] == "element" and len(fields) == 3:
            current = {"name": fields[1], "count": int(fields[2]), "properties": []}
            elements.append(current)
        elif fields[0] == "property" and current is not None:
            if len(fields) == 5 and fields[1] == "list":
                current["properties"].append(
                    {
                        "kind": "list",
                        "count_type": fields[2],
                        "item_type": fields[3],
                        "name": fields[4],
                    }
                )
            elif len(fields) == 3:
                current["properties"].append(
                    {"kind": "scalar", "type": fields[1], "name": fields[2]}
                )

    if format_name != "binary_little_endian 1.0":
        raise ValueError(f"Only binary_little_endian PLY is supported, got {format_name!r}")
    if not any(element["name"] == "vertex" for element in elements):
        raise ValueError("PLY has no vertex element")
    if not any(element["name"] == "face" for element in elements):
        raise ValueError("PLY has no face element")
    return format_name, header_bytes, elements


def _read_property(stream: BinaryIO, property_spec: dict[str, Any]) -> int | float | list[int | float]:
    if property_spec["kind"] == "scalar":
        return _read_scalar(stream, property_spec["type"])
    count = int(_read_scalar(stream, property_spec["count_type"]))
    if count < 0:
        raise ValueError("PLY list property has a negative count")
    return [_read_scalar(stream, property_spec["item_type"]) for _ in range(count)]


def parse_binary_ply(path: Path) -> dict[str, Any]:
    """Read geometry statistics without loading the complete mesh into memory."""

    with path.open("rb") as stream:
        format_name, header_bytes, elements = _parse_ply_header(stream)
        vertex_element = next(element for element in elements if element["name"] == "vertex")
        face_element = next(element for element in elements if element["name"] == "face")

        bounds_min = [math.inf, math.inf, math.inf]
        bounds_max = [-math.inf, -math.inf, -math.inf]
        vertex_properties = vertex_element["properties"]
        for _ in range(vertex_element["count"]):
            values: dict[str, Any] = {}
            for property_spec in vertex_properties:
                values[property_spec["name"]] = _read_property(stream, property_spec)
            try:
                coordinates = [float(values[name]) for name in ("x", "y", "z")]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"PLY vertex has no usable x/y/z coordinates: {path}") from exc
            for index, coordinate in enumerate(coordinates):
                bounds_min[index] = min(bounds_min[index], coordinate)
                bounds_max[index] = max(bounds_max[index], coordinate)

        triangle_count = 0
        max_face_vertex_count = 0
        object_id_counts: Counter[int] = Counter()
        face_properties = face_element["properties"]
        for _ in range(face_element["count"]):
            values = {}
            for property_spec in face_properties:
                values[property_spec["name"]] = _read_property(stream, property_spec)
            indices = values.get("vertex_indices")
            if isinstance(indices, list):
                max_face_vertex_count = max(max_face_vertex_count, len(indices))
                if len(indices) == 3:
                    triangle_count += 1
            object_id = values.get("object_id")
            if isinstance(object_id, (int, float)):
                object_id_counts[int(object_id)] += 1

    extent = [bounds_max[index] - bounds_min[index] for index in range(3)]
    return {
        "format": format_name,
        "header_bytes": header_bytes,
        "elements": {element["name"]: element["count"] for element in elements},
        "vertex_count": int(vertex_element["count"]),
        "face_count": int(face_element["count"]),
        "triangle_count": triangle_count,
        "non_triangle_face_count": int(face_element["count"]) - triangle_count,
        "max_face_vertex_count": max_face_vertex_count,
        "bounds": {"min": bounds_min, "max": bounds_max},
        "extent": extent,
        "object_id_counts": dict(sorted(object_id_counts.items())),
        "vertex_properties": [property_spec["name"] for property_spec in vertex_properties],
        "face_properties": [property_spec["name"] for property_spec in face_properties],
    }


def classify_semantic_objects(info_semantic: dict[str, Any]) -> dict[str, list[int]]:
    """Return exact class-name candidates for the scene manifest."""

    candidates = {name: [] for name in _CANDIDATE_CLASS_NAMES}
    for item in info_semantic.get("objects", []):
        object_id = item.get("id")
        class_name = str(item.get("class_name", "")).strip().lower()
        if not isinstance(object_id, int):
            continue
        for candidate_name, class_names in _CANDIDATE_CLASS_NAMES.items():
            if class_name in class_names:
                candidates[candidate_name].append(object_id)
    return {name: sorted(ids) for name, ids in candidates.items()}


def summarize_instance_mapping(
    object_id_counts: dict[int, int], known_ids: set[int]
) -> dict[str, Any]:
    """Compare semantic-mesh face IDs with ids declared by info_semantic.json."""

    normalized_counts = {int(object_id): int(count) for object_id, count in object_id_counts.items()}
    present_ids = set(normalized_counts)
    return {
        "face_count": sum(normalized_counts.values()),
        "known_id_count": len(present_ids & known_ids),
        "known_ids_missing_from_mesh": sorted(known_ids - present_ids),
        "unknown_ids": sorted(present_ids - known_ids),
        "id_counts": {str(object_id): normalized_counts[object_id] for object_id in sorted(normalized_counts)},
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _object_records(info_semantic: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "id": int(item["id"]),
                "class_id": int(item["class_id"]),
                "class_name": str(item["class_name"]),
                "node_id": int(item["node_id"]),
                "oriented_bbox": item.get("oriented_bbox"),
            }
            for item in info_semantic.get("objects", [])
            if "id" in item and "class_id" in item and "class_name" in item and "node_id" in item
        ],
        key=lambda item: item["id"],
    )


def analyze_scene(scene_dir: Path, derived_dir: Path) -> dict[str, Any]:
    """Analyze office_0 and write deterministic derived JSON artifacts."""

    scene_dir = scene_dir.resolve()
    derived_dir = derived_dir.resolve()
    if not scene_dir.is_dir():
        raise FileNotFoundError(f"Scene directory does not exist: {scene_dir}")
    if derived_dir == scene_dir or scene_dir in derived_dir.parents:
        raise ValueError("Derived output must not be inside the source scene directory")

    required = [
        Path("mesh.ply"),
        Path("semantic.json"),
        Path("habitat/mesh_semantic.ply"),
        Path("habitat/info_semantic.json"),
    ]
    missing = [str(path) for path in required if not (scene_dir / path).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing required office_0 files: {', '.join(missing)}")

    files = []
    for path in sorted(scene_dir.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(scene_dir).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )

    mesh_paths = {
        "mesh": Path("mesh.ply"),
        "semantic_mesh": Path("habitat/mesh_semantic.ply"),
        "preseg_semantic_mesh": Path("habitat/mesh_preseg_semantic.ply"),
    }
    mesh_stats: dict[str, Any] = {}
    for name, relative_path in mesh_paths.items():
        path = scene_dir / relative_path
        if path.is_file():
            mesh_stats[name] = {"path": relative_path.as_posix(), **parse_binary_ply(path)}

    semantic = _load_json(scene_dir / "semantic.json")
    info_semantic = _load_json(scene_dir / "habitat/info_semantic.json")
    object_records = _object_records(info_semantic)
    known_ids = {record["id"] for record in object_records}
    candidates = classify_semantic_objects(info_semantic)
    class_counts = Counter(record["class_name"] for record in object_records)
    id_to_label = info_semantic.get("id_to_label", [])
    id_to_label_mismatches = []
    for record in object_records:
        object_id = record["id"]
        if object_id < len(id_to_label) and id_to_label[object_id] != record["class_id"]:
            id_to_label_mismatches.append(
                {
                    "id": object_id,
                    "expected_class_id": record["class_id"],
                    "actual_class_id": id_to_label[object_id],
                }
            )
    segmentation_ids = {int(item["id"]) for item in semantic.get("segmentation", []) if "id" in item}
    missing_node_ids = sorted(record["node_id"] for record in object_records if record["node_id"] not in segmentation_ids)

    semantic_mesh_mapping = summarize_instance_mapping(
        mesh_stats.get("semantic_mesh", {}).get("object_id_counts", {}), known_ids
    )
    full_bounds = mesh_stats["mesh"]["bounds"]
    full_extent = mesh_stats["mesh"]["extent"]
    max_extent = max(full_extent)
    unit_assessment = {
        "candidate": "meter" if 2.0 <= max_extent <= 100.0 else "unknown",
        "confidence": "medium" if 2.0 <= max_extent <= 100.0 else "low",
        "basis": "office-scale coordinate extent and Replica semantic gravity metadata",
        "requires_user_confirmation": True,
    }

    semantic_summary = {
        "semantic_version": semantic.get("version"),
        "semantic_id_type": semantic.get("idType"),
        "segmentation_count": len(semantic.get("segmentation", [])),
        "semantic_meta": semantic.get("meta"),
        "gravity_center": semantic.get("gravityCenter"),
        "gravity_direction": semantic.get("gravityDirection"),
        "info_semantic_object_count": len(object_records),
        "info_semantic_class_counts": dict(sorted(class_counts.items())),
        "info_semantic_object_ids": sorted(known_ids),
        "id_to_label_mismatches": id_to_label_mismatches,
        "object_node_ids_missing_from_segmentation": missing_node_ids,
        "candidate_object_ids": candidates,
        "candidate_objects": {
            name: [record for record in object_records if record["id"] in ids]
            for name, ids in candidates.items()
        },
        "semantic_mesh_instance_mapping": semantic_mesh_mapping,
    }

    scene_manifest = {
        "schema_version": 1,
        "scene_id": "office_0",
        "source_scene": str(scene_dir),
        "units": unit_assessment,
        "up_axis": {
            "candidate": "Z",
            "basis": semantic.get("gravityDirection"),
            "requires_user_confirmation": True,
        },
        "visual_mesh": "mesh.ply",
        "semantic_mesh": "habitat/mesh_semantic.ply",
        "collision_proxy_policy": "not_generated_in_phase_1",
        "physics_authority": "MuJoCo",
        "candidate_object_ids": candidates,
        "object_records": object_records,
        "mesh_bounds": full_bounds,
        "mesh_extent": full_extent,
    }

    derived_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "checksums": derived_dir / "checksums.sha256",
        "mesh_stats": derived_dir / "mesh_stats.json",
        "semantic_summary": derived_dir / "semantic_summary.json",
        "scene_manifest": derived_dir / "scene_manifest.json",
    }
    outputs["checksums"].write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in files), encoding="utf-8"
    )
    outputs["mesh_stats"].write_text(json.dumps(mesh_stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    outputs["semantic_summary"].write_text(
        json.dumps(semantic_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    outputs["scene_manifest"].write_text(
        json.dumps(scene_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "scene_dir": str(scene_dir),
        "derived_dir": str(derived_dir),
        "file_count": len(files),
        "total_bytes": sum(entry["bytes"] for entry in files),
        "required_files": {str(path): (scene_dir / path).stat().st_size for path in required},
        "files": files,
        "mesh_stats": mesh_stats,
        "semantic_summary": semantic_summary,
        "scene_manifest": scene_manifest,
        "output_files": {name: str(path) for name, path in outputs.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--derived-dir", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_scene(args.scene_dir, args.derived_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
