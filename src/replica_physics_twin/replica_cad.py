"""ReplicaCAD asset conversion and coordinate/physics metadata helpers.

The upstream ReplicaCAD assets are glTF binary files.  This module intentionally
keeps the conversion path dependency-light: NumPy is already used by the
MuJoCo bridge, while GLB, PNG, OBJ, and the small RPTMESH2 interchange format
are handled here directly.  The resulting files are used by both the MuJoCo
scene compiler and the Unreal procedural mesh loader.
"""

from __future__ import annotations

import base64
import json
import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np


RPTMESH2_MAGIC = b"RPTMESH2"
_TRIANGLES_MODE = 4
_COMPONENT_DTYPES: dict[int, np.dtype[Any]] = {
    5120: np.dtype("i1"),
    5121: np.dtype("u1"),
    5122: np.dtype("<i2"),
    5123: np.dtype("<u2"),
    5125: np.dtype("<u4"),
    5126: np.dtype("<f4"),
}
_TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


@dataclass
class MeshData:
    """A triangle mesh in the coordinate system chosen by the caller."""

    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    colors: np.ndarray
    indices: np.ndarray

    def __post_init__(self) -> None:
        self.positions = np.asarray(self.positions, dtype=np.float32).reshape((-1, 3))
        self.normals = np.asarray(self.normals, dtype=np.float32).reshape((-1, 3))
        self.uvs = np.asarray(self.uvs, dtype=np.float32).reshape((-1, 2))
        self.colors = np.asarray(self.colors, dtype=np.float32).reshape((-1, 4))
        self.indices = np.asarray(self.indices, dtype=np.uint32).reshape((-1,))
        if len(self.positions) != len(self.normals):
            raise ValueError("positions and normals must have the same vertex count")
        if len(self.positions) != len(self.uvs):
            raise ValueError("positions and uvs must have the same vertex count")
        if len(self.positions) != len(self.colors):
            raise ValueError("positions and colors must have the same vertex count")
        if len(self.indices) % 3:
            raise ValueError("triangle index buffer length must be divisible by three")
        if len(self.indices) and int(self.indices.max()) >= len(self.positions):
            raise ValueError("index buffer references a missing vertex")

    @property
    def bounds_min(self) -> np.ndarray:
        return self.positions.min(axis=0) if len(self.positions) else np.zeros(3, dtype=np.float32)

    @property
    def bounds_max(self) -> np.ndarray:
        return self.positions.max(axis=0) if len(self.positions) else np.zeros(3, dtype=np.float32)


def _load_glb_container(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = Path(path).read_bytes()
    if len(raw) < 20:
        raise ValueError(f"GLB is too small: {path}")
    magic, version, total_length = struct.unpack_from("<4sII", raw, 0)
    if magic != b"glTF" or version != 2:
        raise ValueError(f"Unsupported GLB header in {path}: {magic!r} v{version}")
    if total_length > len(raw):
        raise ValueError(f"GLB declares {total_length} bytes but contains {len(raw)}: {path}")
    offset = 12
    document: dict[str, Any] | None = None
    binary = b""
    while offset + 8 <= total_length:
        chunk_length, chunk_type = struct.unpack_from("<II", raw, offset)
        offset += 8
        chunk = raw[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == 0x4E4F534A:
            value = json.loads(chunk.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError(f"GLB JSON chunk is not an object: {path}")
            document = value
        elif chunk_type == 0x004E4942:
            binary = bytes(chunk)
    if document is None:
        raise ValueError(f"GLB has no JSON chunk: {path}")
    return document, binary


def _accessor_values(document: dict[str, Any], binary: bytes, accessor_index: int) -> np.ndarray:
    accessor = document["accessors"][accessor_index]
    component_type = int(accessor["componentType"])
    dtype = _COMPONENT_DTYPES.get(component_type)
    if dtype is None:
        raise ValueError(f"Unsupported glTF component type: {component_type}")
    component_count = _TYPE_COMPONENTS[accessor["type"]]
    count = int(accessor["count"])
    if "bufferView" not in accessor:
        result = np.zeros((count, component_count), dtype=dtype)
    else:
        view = document["bufferViews"][int(accessor["bufferView"])]
        view_offset = int(view.get("byteOffset", 0))
        accessor_offset = int(accessor.get("byteOffset", 0))
        stride = int(view.get("byteStride", dtype.itemsize * component_count))
        item_size = dtype.itemsize * component_count
        start = view_offset + accessor_offset
        if stride == item_size:
            result = np.frombuffer(
                binary,
                dtype=dtype,
                count=count * component_count,
                offset=start,
            ).reshape((count, component_count)).copy()
        else:
            result = np.empty((count, component_count), dtype=dtype)
            for row in range(count):
                row_start = start + row * stride
                result[row] = np.frombuffer(binary, dtype=dtype, count=component_count, offset=row_start)
    if accessor.get("normalized", False) and np.issubdtype(result.dtype, np.integer):
        if np.issubdtype(result.dtype, np.signedinteger):
            max_value = float(np.iinfo(result.dtype).max)
            result = np.maximum(result.astype(np.float32) / max_value, -1.0)
        else:
            result = result.astype(np.float32) / float(np.iinfo(result.dtype).max)
    return result


def _quaternion_xyzw_matrix(quaternion: Iterable[float]) -> np.ndarray:
    x, y, z, w = (float(value) for value in quaternion)
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm < 1e-12:
        return np.eye(3, dtype=np.float64)
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _node_matrix(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        # glTF stores matrices column-major.
        return np.asarray(node["matrix"], dtype=np.float64).reshape((4, 4), order="F")
    translation = np.asarray(node.get("translation", [0.0, 0.0, 0.0]), dtype=np.float64)
    scale = np.asarray(node.get("scale", [1.0, 1.0, 1.0]), dtype=np.float64)
    rotation = _quaternion_xyzw_matrix(node.get("rotation", [0.0, 0.0, 0.0, 1.0]))
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = rotation @ np.diag(scale)
    result[:3, 3] = translation
    return result


def _read_image(document: dict[str, Any], binary: bytes, image_index: int, base_dir: Path) -> bytes:
    image = document["images"][image_index]
    if "bufferView" in image:
        view = document["bufferViews"][int(image["bufferView"])]
        start = int(view.get("byteOffset", 0))
        return binary[start : start + int(view["byteLength"])]
    uri = image.get("uri")
    if not isinstance(uri, str):
        raise ValueError(f"Image {image_index} has no bufferView or URI")
    if uri.startswith("data:"):
        return base64.b64decode(uri.split(",", 1)[1])
    return (base_dir / uri).read_bytes()


def _decode_png_rgba(data: bytes) -> np.ndarray | None:
    """Decode the 8-bit non-interlaced PNG variants used by ReplicaCAD."""

    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    offset = 8
    width = height = bit_depth = color_type = interlace = 0
    palette: bytes | None = None
    transparency: bytes | None = None
    compressed = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif kind == b"PLTE":
            palette = bytes(payload)
        elif kind == b"tRNS":
            transparency = bytes(payload)
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    if not width or not height or bit_depth != 8 or interlace != 0:
        return None
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        return None
    try:
        decoded = zlib.decompress(bytes(compressed))
    except zlib.error:
        return None
    row_bytes = width * channels
    expected = height * (row_bytes + 1)
    if len(decoded) < expected:
        return None
    rows = np.zeros((height, row_bytes), dtype=np.uint8)
    previous = np.zeros(row_bytes, dtype=np.uint8)
    for y in range(height):
        filter_type = decoded[y * (row_bytes + 1)]
        source = np.frombuffer(decoded, dtype=np.uint8, count=row_bytes, offset=y * (row_bytes + 1) + 1).copy()
        current = np.zeros(row_bytes, dtype=np.uint8)
        for x in range(row_bytes):
            left = int(current[x - channels]) if x >= channels else 0
            up = int(previous[x])
            up_left = int(previous[x - channels]) if x >= channels else 0
            if filter_type == 0:
                value = int(source[x])
            elif filter_type == 1:
                value = int(source[x]) + left
            elif filter_type == 2:
                value = int(source[x]) + up
            elif filter_type == 3:
                value = int(source[x]) + ((left + up) // 2)
            elif filter_type == 4:
                estimate = left + up - up_left
                pa, pb, pc = abs(estimate - left), abs(estimate - up), abs(estimate - up_left)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else up_left
                value = int(source[x]) + predictor
            else:
                return None
            current[x] = value & 0xFF
        rows[y] = current
        previous = current
    pixels = rows.reshape((height, width, channels))
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    if color_type == 6:
        rgba[:] = pixels
    elif color_type == 2:
        rgba[..., :3] = pixels
        rgba[..., 3] = 255
    elif color_type == 4:
        rgba[..., :3] = pixels[..., :1]
        rgba[..., 3] = pixels[..., 1]
    elif color_type == 0:
        rgba[..., :3] = pixels
        rgba[..., 3] = 255
        if transparency and len(transparency) >= 2:
            transparent_gray = int.from_bytes(transparency[:2], "big") & 0xFF
            rgba[pixels[..., 0] == transparent_gray, 3] = 0
    else:  # indexed color
        if palette is None:
            return None
        palette_array = np.frombuffer(palette, dtype=np.uint8).reshape((-1, 3))
        indices = pixels[..., 0]
        if int(indices.max(initial=0)) >= len(palette_array):
            return None
        rgba[..., :3] = palette_array[indices]
        rgba[..., 3] = 255
        if transparency:
            alpha = np.zeros(len(palette_array), dtype=np.uint8)
            alpha[: len(transparency)] = np.frombuffer(transparency, dtype=np.uint8)
            rgba[..., 3] = alpha[indices]
    return rgba


def _sample_texture(texture: np.ndarray, uvs: np.ndarray) -> np.ndarray:
    if texture is None or not len(uvs):
        return np.ones((len(uvs), 4), dtype=np.float32)
    height, width, _ = texture.shape
    wrapped = np.mod(uvs, 1.0)
    x = np.clip((wrapped[:, 0] * (width - 1)).astype(np.int64), 0, width - 1)
    y = np.clip(((1.0 - wrapped[:, 1]) * (height - 1)).astype(np.int64), 0, height - 1)
    return texture[y, x].astype(np.float32) / 255.0


def _primitive_material_colors(
    document: dict[str, Any],
    binary: bytes,
    primitive: dict[str, Any],
    uvs: np.ndarray,
    vertex_colors: np.ndarray | None,
    base_dir: Path,
    image_cache: dict[int, np.ndarray | None],
) -> np.ndarray:
    count = len(uvs)
    material_index = primitive.get("material")
    material = document.get("materials", [])[int(material_index)] if material_index is not None else {}
    pbr = material.get("pbrMetallicRoughness", {})
    factor = np.asarray(pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0]), dtype=np.float32)
    if factor.size != 4:
        factor = np.ones(4, dtype=np.float32)
    colors = np.repeat(factor[None, :], count, axis=0)
    if vertex_colors is not None:
        vertex_colors = np.asarray(vertex_colors, dtype=np.float32)
        if vertex_colors.shape[1] == 3:
            vertex_colors = np.concatenate([vertex_colors, np.ones((count, 1), dtype=np.float32)], axis=1)
        colors *= vertex_colors[:, :4]
    texture_info = pbr.get("baseColorTexture")
    if isinstance(texture_info, dict) and "index" in texture_info:
        texture_index = int(texture_info["index"])
        texture = document.get("textures", [])[texture_index]
        source_index = texture.get("source")
        if source_index is not None:
            source_index = int(source_index)
            if source_index not in image_cache:
                try:
                    image_cache[source_index] = _decode_png_rgba(
                        _read_image(document, binary, source_index, base_dir)
                    )
                except (OSError, ValueError):
                    image_cache[source_index] = None
            if image_cache[source_index] is not None:
                colors *= _sample_texture(image_cache[source_index], uvs)
    return np.clip(colors, 0.0, 1.0)


def _transform_mesh(mesh: MeshData, transform: np.ndarray) -> MeshData:
    matrix = np.asarray(transform, dtype=np.float64).reshape((4, 4))
    linear = matrix[:3, :3]
    homogeneous = np.concatenate([mesh.positions.astype(np.float64), np.ones((len(mesh.positions), 1))], axis=1)
    positions = (homogeneous @ matrix.T)[:, :3]
    normal_matrix = np.linalg.inv(linear).T
    normals = mesh.normals.astype(np.float64) @ normal_matrix.T
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = normals / np.maximum(lengths, 1e-12)
    return MeshData(positions, normals, mesh.uvs, mesh.colors, mesh.indices)


def load_glb(path: Path, *, coordinate_transform: np.ndarray | None = None) -> MeshData:
    """Load all triangle primitives from an embedded or external-URI GLB."""

    path = Path(path)
    document, binary = _load_glb_container(path)
    image_cache: dict[int, np.ndarray | None] = {}
    positions_out: list[np.ndarray] = []
    normals_out: list[np.ndarray] = []
    uvs_out: list[np.ndarray] = []
    colors_out: list[np.ndarray] = []
    indices_out: list[np.ndarray] = []

    def visit(node_index: int, parent: np.ndarray) -> None:
        node = document.get("nodes", [])[int(node_index)]
        world = parent @ _node_matrix(node)
        mesh_index = node.get("mesh")
        if mesh_index is not None:
            for primitive in document.get("meshes", [])[int(mesh_index)].get("primitives", []):
                if int(primitive.get("mode", _TRIANGLES_MODE)) != _TRIANGLES_MODE:
                    continue
                attributes = primitive.get("attributes", {})
                if "POSITION" not in attributes:
                    continue
                raw_positions = _accessor_values(document, binary, int(attributes["POSITION"])).astype(np.float32)
                raw_positions = raw_positions[:, :3]
                if "NORMAL" in attributes:
                    raw_normals = _accessor_values(document, binary, int(attributes["NORMAL"])).astype(np.float32)[:, :3]
                else:
                    raw_normals = np.zeros_like(raw_positions)
                if "TEXCOORD_0" in attributes:
                    raw_uvs = _accessor_values(document, binary, int(attributes["TEXCOORD_0"])).astype(np.float32)[:, :2]
                else:
                    raw_uvs = np.zeros((len(raw_positions), 2), dtype=np.float32)
                raw_colors = None
                if "COLOR_0" in attributes:
                    raw_colors = _accessor_values(document, binary, int(attributes["COLOR_0"])).astype(np.float32)
                colors = _primitive_material_colors(
                    document, binary, primitive, raw_uvs, raw_colors, path.parent, image_cache
                )
                local = MeshData(
                    raw_positions,
                    raw_normals,
                    raw_uvs,
                    colors,
                    _primitive_indices(document, binary, primitive, len(raw_positions)),
                )
                transformed = _transform_mesh(local, world)
                base = sum(len(value) for value in positions_out)
                positions_out.append(transformed.positions)
                normals_out.append(transformed.normals)
                uvs_out.append(transformed.uvs)
                colors_out.append(transformed.colors)
                indices_out.append(transformed.indices + base)
        for child in node.get("children", []):
            visit(int(child), world)

    scene_index = int(document.get("scene", 0))
    scenes = document.get("scenes", [])
    if not scenes:
        raise ValueError(f"GLB has no scenes: {path}")
    for root in scenes[scene_index].get("nodes", []):
        visit(int(root), np.eye(4, dtype=np.float64))
    if not positions_out:
        raise ValueError(f"GLB has no triangle POSITION primitives: {path}")
    result = MeshData(
        np.concatenate(positions_out, axis=0),
        np.concatenate(normals_out, axis=0),
        np.concatenate(uvs_out, axis=0),
        np.concatenate(colors_out, axis=0),
        np.concatenate(indices_out, axis=0),
    )
    if not np.any(np.linalg.norm(result.normals, axis=1)):
        result.normals = _compute_vertex_normals(result.positions, result.indices)
    if coordinate_transform is not None:
        result = _transform_mesh(result, coordinate_transform)
    return result


def load_glb_parts(path: Path, *, coordinate_transform: np.ndarray | None = None) -> list[MeshData]:
    """Load each glTF mesh node as a separate triangle mesh part.

    ReplicaCAD convex-decomposition assets contain one convex hull per glTF
    node.  Keeping those nodes separate is important for MuJoCo: merging all
    hulls into one mesh makes a single convex collision envelope around the
    entire object (for example, around both bicycle wheels), which destroys
    the object's real support geometry.
    """

    path = Path(path)
    document, binary = _load_glb_container(path)
    image_cache: dict[int, np.ndarray | None] = {}
    parts: list[MeshData] = []

    def visit(node_index: int, parent: np.ndarray) -> None:
        node = document.get("nodes", [])[int(node_index)]
        world = parent @ _node_matrix(node)
        mesh_index = node.get("mesh")
        if mesh_index is not None:
            positions_out: list[np.ndarray] = []
            normals_out: list[np.ndarray] = []
            uvs_out: list[np.ndarray] = []
            colors_out: list[np.ndarray] = []
            indices_out: list[np.ndarray] = []
            for primitive in document.get("meshes", [])[int(mesh_index)].get("primitives", []):
                if int(primitive.get("mode", _TRIANGLES_MODE)) != _TRIANGLES_MODE:
                    continue
                attributes = primitive.get("attributes", {})
                if "POSITION" not in attributes:
                    continue
                raw_positions = _accessor_values(document, binary, int(attributes["POSITION"])).astype(np.float32)[:, :3]
                if "NORMAL" in attributes:
                    raw_normals = _accessor_values(document, binary, int(attributes["NORMAL"])).astype(np.float32)[:, :3]
                else:
                    raw_normals = np.zeros_like(raw_positions)
                if "TEXCOORD_0" in attributes:
                    raw_uvs = _accessor_values(document, binary, int(attributes["TEXCOORD_0"])).astype(np.float32)[:, :2]
                else:
                    raw_uvs = np.zeros((len(raw_positions), 2), dtype=np.float32)
                raw_colors = None
                if "COLOR_0" in attributes:
                    raw_colors = _accessor_values(document, binary, int(attributes["COLOR_0"])).astype(np.float32)
                colors = _primitive_material_colors(
                    document, binary, primitive, raw_uvs, raw_colors, path.parent, image_cache
                )
                base = sum(len(value) for value in positions_out)
                positions_out.append(raw_positions)
                normals_out.append(raw_normals)
                uvs_out.append(raw_uvs)
                colors_out.append(colors)
                indices_out.append(_primitive_indices(document, binary, primitive, len(raw_positions)) + base)
            if positions_out:
                part = MeshData(
                    np.concatenate(positions_out, axis=0),
                    np.concatenate(normals_out, axis=0),
                    np.concatenate(uvs_out, axis=0),
                    np.concatenate(colors_out, axis=0),
                    np.concatenate(indices_out, axis=0),
                )
                part = _transform_mesh(part, world)
                if not np.any(np.linalg.norm(part.normals, axis=1)):
                    part.normals = _compute_vertex_normals(part.positions, part.indices)
                if coordinate_transform is not None:
                    part = _transform_mesh(part, coordinate_transform)
                parts.append(part)
        for child in node.get("children", []):
            visit(int(child), world)

    scenes = document.get("scenes", [])
    if not scenes:
        raise ValueError(f"GLB has no scenes: {path}")
    scene_index = int(document.get("scene", 0))
    for root in scenes[scene_index].get("nodes", []):
        visit(int(root), np.eye(4, dtype=np.float64))
    if not parts:
        raise ValueError(f"GLB has no triangle POSITION primitives: {path}")
    return parts


def _primitive_indices(
    document: dict[str, Any], binary: bytes, primitive: dict[str, Any], vertex_count: int
) -> np.ndarray:
    if "indices" not in primitive:
        return np.arange(vertex_count, dtype=np.uint32)
    return _accessor_values(document, binary, int(primitive["indices"])).reshape((-1,)).astype(np.uint32)


def _compute_vertex_normals(positions: np.ndarray, indices: np.ndarray) -> np.ndarray:
    normals = np.zeros_like(positions, dtype=np.float32)
    triangles = indices.reshape((-1, 3))
    for a, b, c in triangles:
        face = np.cross(positions[b] - positions[a], positions[c] - positions[a])
        length = float(np.linalg.norm(face))
        if length > 1e-12:
            face /= length
        normals[a] += face
        normals[b] += face
        normals[c] += face
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals /= np.maximum(lengths, 1e-12)
    return normals


def replica_cad_to_mujoco_matrix() -> np.ndarray:
    """Return the right-handed basis change from ReplicaCAD (Y-up) to MuJoCo (Z-up)."""

    return np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, -1.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def quaternion_wxyz_to_matrix(quaternion: Iterable[float]) -> np.ndarray:
    w, x, y, z = (float(value) for value in quaternion)
    return _quaternion_xyzw_matrix([x, y, z, w])


def matrix_to_quaternion_wxyz(matrix: np.ndarray) -> np.ndarray:
    m = np.asarray(matrix, dtype=np.float64)[:3, :3]
    trace = float(np.trace(m))
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    result = np.array([w, x, y, z], dtype=np.float64)
    return result / max(float(np.linalg.norm(result)), 1e-12)


def habitat_quaternion_to_mujoco(quaternion_wxyz: Iterable[float]) -> np.ndarray:
    basis = replica_cad_to_mujoco_matrix()[:3, :3]
    source_rotation = quaternion_wxyz_to_matrix(quaternion_wxyz)
    return matrix_to_quaternion_wxyz(basis @ source_rotation @ basis.T)


def convert_replica_cad_transform(
    translation: Iterable[float], rotation_wxyz: Iterable[float]
) -> tuple[np.ndarray, np.ndarray]:
    basis = replica_cad_to_mujoco_matrix()
    source_translation = np.asarray(list(translation), dtype=np.float64)
    target_translation = (basis @ np.concatenate([source_translation, [1.0]]))[:3]
    return target_translation, habitat_quaternion_to_mujoco(rotation_wxyz)


def inertia_from_bounds(mass_kg: float, bounds_min: Iterable[float], bounds_max: Iterable[float]) -> np.ndarray:
    """Derive a diagonal box inertia from a collision-mesh bound when needed."""

    dimensions = np.maximum(
        np.asarray(list(bounds_max), dtype=np.float64) - np.asarray(list(bounds_min), dtype=np.float64),
        1e-5,
    )
    mass = float(mass_kg)
    dx, dy, dz = dimensions
    return np.array(
        [mass * (dy * dy + dz * dz) / 12.0, mass * (dx * dx + dz * dz) / 12.0, mass * (dx * dx + dy * dy) / 12.0],
        dtype=np.float64,
    )


def write_rptmesh2(mesh: MeshData, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    positions = np.ascontiguousarray(mesh.positions, dtype="<f4")
    normals = np.ascontiguousarray(mesh.normals, dtype="<f4")
    colors = np.clip(np.rint(mesh.colors * 255.0), 0.0, 255.0).astype(np.uint8)
    indices = np.ascontiguousarray(mesh.indices, dtype="<u4")
    with path.open("wb") as handle:
        handle.write(RPTMESH2_MAGIC)
        handle.write(struct.pack("<II", len(positions), len(indices)))
        handle.write(positions.tobytes())
        handle.write(normals.tobytes())
        handle.write(colors.tobytes())
        handle.write(indices.tobytes())


def read_rptmesh2(path: Path) -> MeshData:
    raw = Path(path).read_bytes()
    if raw[:8] != RPTMESH2_MAGIC:
        raise ValueError(f"Not an RPTMESH2 file: {path}")
    vertex_count, index_count = struct.unpack_from("<II", raw, 8)
    offset = 16
    positions_size = vertex_count * 3 * 4
    normals_size = vertex_count * 3 * 4
    colors_size = vertex_count * 4
    indices_size = index_count * 4
    expected = offset + positions_size + normals_size + colors_size + indices_size
    if len(raw) < expected:
        raise ValueError(f"Truncated RPTMESH2 file: {path}")
    positions = np.frombuffer(raw, dtype="<f4", count=vertex_count * 3, offset=offset).copy().reshape((-1, 3))
    offset += positions_size
    normals = np.frombuffer(raw, dtype="<f4", count=vertex_count * 3, offset=offset).copy().reshape((-1, 3))
    offset += normals_size
    colors = np.frombuffer(raw, dtype=np.uint8, count=vertex_count * 4, offset=offset).copy().reshape((-1, 4)) / 255.0
    offset += colors_size
    indices = np.frombuffer(raw, dtype="<u4", count=index_count, offset=offset).copy()
    return MeshData(positions, normals, np.zeros((vertex_count, 2), dtype=np.float32), colors, indices)


def write_obj(mesh: MeshData, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# ReplicaCAD collision mesh exported from GLB", "o replica_cad_mesh"]
    lines.extend(f"v {x:.9g} {y:.9g} {z:.9g}" for x, y, z in mesh.positions)
    lines.extend(f"vn {x:.9g} {y:.9g} {z:.9g}" for x, y, z in mesh.normals)
    for a, b, c in mesh.indices.reshape((-1, 3)):
        a_i, b_i, c_i = int(a) + 1, int(b) + 1, int(c) + 1
        lines.append(f"f {a_i}//{a_i} {b_i}//{b_i} {c_i}//{c_i}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def transform_mesh(mesh: MeshData, transform: np.ndarray) -> MeshData:
    """Apply a homogeneous transform to positions and inverse-transpose normals."""

    return _transform_mesh(mesh, transform)


def merge_meshes(meshes: Iterable[MeshData]) -> MeshData:
    """Concatenate meshes while remapping each local index buffer."""

    materialized = list(meshes)
    if not materialized:
        raise ValueError("at least one mesh is required")
    positions: list[np.ndarray] = []
    normals: list[np.ndarray] = []
    uvs: list[np.ndarray] = []
    colors: list[np.ndarray] = []
    indices: list[np.ndarray] = []
    vertex_offset = 0
    for mesh in materialized:
        positions.append(mesh.positions)
        normals.append(mesh.normals)
        uvs.append(mesh.uvs)
        colors.append(mesh.colors)
        indices.append(mesh.indices + vertex_offset)
        vertex_offset += len(mesh.positions)
    return MeshData(
        np.concatenate(positions, axis=0),
        np.concatenate(normals, axis=0),
        np.concatenate(uvs, axis=0),
        np.concatenate(colors, axis=0),
        np.concatenate(indices, axis=0),
    )
