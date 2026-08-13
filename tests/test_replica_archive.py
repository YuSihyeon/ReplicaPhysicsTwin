from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from replica_physics_twin.replica_archive import (
    expected_part_sizes,
    extract_office0_zip,
    extract_office0,
    office0_relative_path,
    verify_office0,
    verify_parts,
)


class ReplicaArchiveTests(unittest.TestCase):
    def test_verification_cli_exposes_help(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(project_root / "scripts/verify_replica_data.py"), "--help"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("parts", result.stdout)
        self.assertIn("extract", result.stdout)
        self.assertIn("scene", result.stdout)

    def test_expected_parts_match_official_v1_release(self) -> None:
        specs = expected_part_sizes()

        self.assertEqual(list(specs), [f"replica_v1_0.tar.gz.parta{c}" for c in "abcdefghijklmnopq"])
        self.assertEqual(list(specs.values())[:-1], [2_000_000_000] * 16)
        self.assertEqual(list(specs.values())[-1], 1_859_047_808)

    def test_verify_parts_reports_missing_and_wrong_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "replica_v1_0.tar.gz.partaa").write_bytes(b"short")

            result = verify_parts(root)

        self.assertFalse(result["complete"])
        self.assertIn("replica_v1_0.tar.gz.partaa", result["wrong_sizes"])
        self.assertIn("replica_v1_0.tar.gz.partab", result["missing"])

    def test_office0_path_accepts_prefix_and_rejects_traversal(self) -> None:
        self.assertEqual(
            office0_relative_path("Replica/office_0/habitat/info_semantic.json"),
            Path("habitat/info_semantic.json"),
        )
        self.assertIsNone(office0_relative_path("Replica/office_1/mesh.ply"))
        with self.assertRaises(ValueError):
            office0_relative_path("Replica/office_0/../../outside.txt")

    def test_extract_office0_reads_split_stream_and_ignores_other_scenes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "fixture.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                for name, content in {
                    "Replica/office_0/mesh.ply": b"office zero",
                    "Replica/office_0/semantic.json": b"{}",
                    "Replica/office_0/habitat/mesh_semantic.ply": b"semantic mesh",
                    "Replica/office_0/habitat/info_semantic.json": b"{}",
                    "Replica/office_1/mesh.ply": b"office one",
                }.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    tar.addfile(info, io.BytesIO(content))

            payload = archive.read_bytes()
            split_at = len(payload) // 2
            part_paths = [root / "partaa", root / "partab"]
            part_paths[0].write_bytes(payload[:split_at])
            part_paths[1].write_bytes(payload[split_at:])
            output = root / "output" / "office_0"

            result = extract_office0(part_paths, output)

            self.assertEqual((output / "mesh.ply").read_bytes(), b"office zero")
            self.assertFalse((root / "output" / "office_1").exists())
            self.assertEqual(result["archive_prefix"], "Replica/office_0")
            self.assertEqual(result["files_extracted"], 4)

    def test_extract_office0_zip_selects_only_requested_scene(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "habitat.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("configs/office_0/habitat/info_semantic.json", "{}")
                bundle.writestr("configs/office_1/habitat/info_semantic.json", "other")
            output = root / "output" / "office_0"

            result = extract_office0_zip(archive, output)

            self.assertEqual((output / "habitat/info_semantic.json").read_text(), "{}")
            self.assertEqual(result["files_extracted"], 1)
            self.assertFalse((root / "output" / "office_1").exists())

    def test_verify_office0_requires_all_semantic_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scene = Path(temp_dir)
            (scene / "mesh.ply").write_bytes(b"mesh")

            result = verify_office0(scene)

        self.assertFalse(result["complete"])
        self.assertEqual(
            set(result["missing"]),
            {"semantic.json", "habitat/mesh_semantic.ply", "habitat/info_semantic.json"},
        )


if __name__ == "__main__":
    unittest.main()
