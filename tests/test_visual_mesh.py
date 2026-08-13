from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from replica_physics_twin.visual_mesh import build_visual_mesh, build_visual_mesh_variant


def _write_fixture_ply(path: Path) -> None:
    header = "\n".join(
        [
            "ply",
            "format binary_little_endian 1.0",
            "element vertex 3",
            "property float x",
            "property float y",
            "property float z",
            "property float nx",
            "property float ny",
            "property float nz",
            "property uchar red",
            "property uchar green",
            "property uchar blue",
            "element face 1",
            "property list uchar int vertex_indices",
            "end_header",
            "",
        ]
    ).encode("ascii")
    vertices = b"".join(
        struct.pack("<ffffffBBB", x, y, z, 0.0, 0.0, 1.0, 255, 0, 0)
        for x, y, z in ((-1.0, 2.0, 0.5), (3.0, -2.0, 1.5), (0.0, 1.0, -0.5))
    )
    face = struct.pack("<Biii", 3, 0, 1, 2)
    path.write_bytes(header + vertices + face)


def _write_instance_fixture_ply(path: Path) -> None:
    header = "\n".join(
        [
            "ply",
            "format binary_little_endian 1.0",
            "element vertex 6",
            "property float x",
            "property float y",
            "property float z",
            "property float nx",
            "property float ny",
            "property float nz",
            "property uchar red",
            "property uchar green",
            "property uchar blue",
            "element face 3",
            "property list uchar int vertex_indices",
            "property int object_id",
            "end_header",
            "",
        ]
    ).encode("ascii")
    vertices = b"".join(
        struct.pack("<ffffffBBB", x, y, z, 0.0, 0.0, 1.0, 255, 255, 255)
        for x, y, z in (
            (-1.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (10.0, 0.0, 0.0),
            (11.0, 0.0, 0.0),
            (11.0, 1.0, 0.0),
        )
    )
    faces = b"".join(
        [
            struct.pack("<BiiiI", 3, 0, 1, 2, 1),
            struct.pack("<BiiiI", 3, 3, 4, 5, 28),
            struct.pack("<BiiiI", 3, 0, 0, 1, 28),
        ]
    )
    path.write_bytes(header + vertices + faces)


class VisualMeshTests(unittest.TestCase):
    def test_build_visual_mesh_centers_xy_and_places_lowest_vertex_on_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scene_dir = root / "scene"
            scene_dir.mkdir()
            source = scene_dir / "mesh.ply"
            _write_fixture_ply(source)
            output_obj = root / "outputs" / "office_0_visual.obj"
            output_binary = root / "outputs" / "office_0_visual.rptmesh"
            metadata_path = root / "outputs" / "office_0_visual_transform.json"

            result = build_visual_mesh(scene_dir, output_obj, metadata_path, output_binary=output_binary)

            self.assertEqual(result["vertex_count"], 3)
            self.assertEqual(result["face_count"], 1)
            self.assertEqual(result["index_count"], 3)
            self.assertEqual(result["triangle_count"], 1)
            self.assertEqual(result["coordinate_transform"]["translation_m"], [-1.0, 0.0, 0.5])
            self.assertTrue(result["interior_normals_flipped"])
            self.assertEqual(result["output_bounds_cm"]["min"], [-200.0, -200.0, 0.0])
            self.assertEqual(result["output_bounds_cm"]["max"], [200.0, 200.0, 200.0])
            self.assertTrue(output_obj.is_file())
            self.assertTrue(output_obj.with_suffix(".mtl").is_file())
            self.assertTrue(output_binary.is_file())
            self.assertTrue(metadata_path.is_file())

            binary = output_binary.read_bytes()
            self.assertEqual(binary[:8], b"RPTMESH1")
            self.assertEqual(struct.unpack("<II", binary[8:16]), (3, 3))

            lines = output_obj.read_text(encoding="ascii").splitlines()
            self.assertIn("v -200 200 100", lines)
            self.assertIn("vn -0 -0 -1", lines)
            self.assertEqual(lines[-1], "f 1//1 2//2 3//3")

    def test_build_visual_mesh_variant_selects_semantic_instance_faces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scene_dir = root / "scene"
            scene_dir.mkdir()
            source = scene_dir / "mesh.ply"
            _write_instance_fixture_ply(source)
            output_obj = root / "outputs" / "tissue_box.obj"
            output_binary = root / "outputs" / "tissue_box.rptmesh"
            metadata_path = root / "outputs" / "tissue_box_transform.json"

            result = build_visual_mesh_variant(
                scene_dir,
                output_obj,
                metadata_path,
                output_binary=output_binary,
                object_ids={28},
                mesh_relative_path="mesh.ply",
            )

            self.assertEqual(result["vertex_count"], 3)
            self.assertEqual(result["face_count"], 1)
            self.assertEqual(result["index_count"], 3)
            self.assertEqual(result["selected_object_ids"], [28])
            self.assertEqual(result["output_bounds_cm"]["min"], [-50.0, -50.0, 0.0])
            self.assertEqual(result["output_bounds_cm"]["max"], [50.0, 50.0, 0.0])
            self.assertTrue(output_binary.is_file())
            binary = output_binary.read_bytes()
            self.assertEqual(struct.unpack("<II", binary[8:16]), (3, 3))


if __name__ == "__main__":
    unittest.main()
