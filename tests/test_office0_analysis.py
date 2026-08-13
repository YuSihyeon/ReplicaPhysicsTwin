from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from replica_physics_twin.office0_analysis import (
    classify_semantic_objects,
    parse_binary_ply,
    summarize_instance_mapping,
)


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


class Office0AnalysisTests(unittest.TestCase):
    def test_parse_binary_ply_reports_geometry_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.ply"
            _write_fixture_ply(path)

            result = parse_binary_ply(path)

        self.assertEqual(result["format"], "binary_little_endian 1.0")
        self.assertEqual(result["vertex_count"], 3)
        self.assertEqual(result["face_count"], 1)
        self.assertEqual(result["triangle_count"], 1)
        self.assertEqual(result["bounds"]["min"], [-1.0, -2.0, -0.5])
        self.assertEqual(result["bounds"]["max"], [3.0, 2.0, 1.5])

    def test_classify_semantic_objects_finds_mvp_candidates(self) -> None:
        info = {
            "objects": [
                {"id": 28, "class_name": "tissue-paper"},
                {"id": 63, "class_name": "floor"},
                {"id": 8, "class_name": "wall"},
                {"id": 12, "class_name": "table"},
            ]
        }

        result = classify_semantic_objects(info)

        self.assertEqual(result["tissue_box"], [28])
        self.assertEqual(result["floor"], [63])
        self.assertEqual(result["wall"], [8])
        self.assertEqual(result["table"], [12])
        self.assertEqual(result["bookcase"], [])

    def test_instance_mapping_reports_unknown_mesh_ids(self) -> None:
        result = summarize_instance_mapping({8: 10, 28: 20, 999: 1}, {8, 28})

        self.assertEqual(result["known_id_count"], 2)
        self.assertEqual(result["unknown_ids"], [999])
        self.assertEqual(result["face_count"], 31)


if __name__ == "__main__":
    unittest.main()
