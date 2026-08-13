from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from replica_physics_twin.replica_cad import (
    MeshData,
    load_glb,
    read_rptmesh2,
    replica_cad_to_mujoco_matrix,
    write_obj,
    write_rptmesh2,
)


def _make_minimal_glb(path: Path) -> None:
    positions = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        dtype="<f4",
    )
    normals = np.tile(np.array([[0.0, 0.0, 1.0]], dtype="<f4"), (3, 1))
    uvs = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype="<f4")
    indices = np.array([0, 1, 2], dtype="<u2")
    chunks = [positions.tobytes(), normals.tobytes(), uvs.tobytes(), indices.tobytes()]
    offsets: list[int] = []
    payload = bytearray()
    for chunk in chunks:
        offsets.append(len(payload))
        payload.extend(chunk)
    json_doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "translation": [2.0, 3.0, 4.0]}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                        "indices": 3,
                        "material": 0,
                    }
                ]
            }
        ],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [0.2, 0.4, 0.6, 1.0]}}],
        "buffers": [{"byteLength": len(payload)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": offsets[0], "byteLength": positions.nbytes},
            {"buffer": 0, "byteOffset": offsets[1], "byteLength": normals.nbytes},
            {"buffer": 0, "byteOffset": offsets[2], "byteLength": uvs.nbytes},
            {"buffer": 0, "byteOffset": offsets[3], "byteLength": indices.nbytes},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": 3, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    json_bytes = json.dumps(json_doc, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_bytes = bytes(payload) + b"\0" * ((4 - len(payload) % 4) % 4)
    total_length = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    with path.open("wb") as handle:
        handle.write(struct.pack("<4sII", b"glTF", 2, total_length))
        handle.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))
        handle.write(json_bytes)
        handle.write(struct.pack("<II", len(bin_bytes), 0x004E4942))
        handle.write(bin_bytes)


def test_glb_reader_applies_node_transform_and_material_color(tmp_path: Path) -> None:
    path = tmp_path / "triangle.glb"
    _make_minimal_glb(path)

    mesh = load_glb(path)

    assert isinstance(mesh, MeshData)
    np.testing.assert_allclose(mesh.positions[0], [2.0, 3.0, 4.0])
    np.testing.assert_allclose(mesh.positions[1], [3.0, 3.0, 4.0])
    np.testing.assert_allclose(mesh.colors[0], [0.2, 0.4, 0.6, 1.0], atol=1 / 255)
    np.testing.assert_array_equal(mesh.indices, [0, 1, 2])


def test_replica_cad_basis_maps_y_up_to_mujoco_z_up() -> None:
    basis = replica_cad_to_mujoco_matrix()
    point = np.array([1.0, 2.0, 3.0, 1.0])

    np.testing.assert_allclose(basis @ point, [1.0, -3.0, 2.0, 1.0])
    assert np.linalg.det(basis[:3, :3]) == pytest.approx(1.0)


def test_rptmesh2_preserves_geometry_colors_and_indices(tmp_path: Path) -> None:
    mesh = MeshData(
        positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32),
        normals=np.tile(np.array([[0, 0, 1]], dtype=np.float32), (3, 1)),
        uvs=np.zeros((3, 2), dtype=np.float32),
        colors=np.array([[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1]], dtype=np.float32),
        indices=np.array([0, 1, 2], dtype=np.uint32),
    )
    path = tmp_path / "triangle.rptmesh"

    write_rptmesh2(mesh, path)
    decoded = read_rptmesh2(path)

    np.testing.assert_allclose(decoded.positions, mesh.positions)
    np.testing.assert_allclose(decoded.normals, mesh.normals)
    np.testing.assert_allclose(decoded.colors, mesh.colors, atol=1 / 255)
    np.testing.assert_array_equal(decoded.indices, mesh.indices)


def test_obj_export_contains_triangles_and_normals(tmp_path: Path) -> None:
    mesh = MeshData(
        positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32),
        normals=np.tile(np.array([[0, 0, 1]], dtype=np.float32), (3, 1)),
        uvs=np.zeros((3, 2), dtype=np.float32),
        colors=np.ones((3, 4), dtype=np.float32),
        indices=np.array([0, 1, 2], dtype=np.uint32),
    )
    path = tmp_path / "triangle.obj"

    write_obj(mesh, path)
    text = path.read_text(encoding="utf-8")

    assert text.count("\nv ") == 3
    assert text.count("\nvn ") == 3
    assert "\nf 1//1 2//2 3//3" in text
