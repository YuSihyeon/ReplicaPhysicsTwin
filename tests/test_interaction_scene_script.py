from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_office0_interaction_scene import run_build  # noqa: E402


def test_office0_interaction_scene_artifact_contains_tissue_and_environment_body(tmp_path: Path) -> None:
    xml_path = tmp_path / "office0_interaction.xml"
    metadata_path = tmp_path / "office0_interaction.json"

    spec = run_build(xml_path=xml_path, metadata_path=metadata_path)
    model = mujoco.MjModel.from_xml_path(str(xml_path))

    assert spec["physics_authority"] == "MuJoCo"
    assert {body["name"] for body in spec["dynamic_bodies"]} >= {"tissue_box", "desk_organizer", "chair_4"}
    assert len(spec["dynamic_bodies"]) >= 3
    assert all(body["collision_shape"] == "semantic_mesh_convex_hull" for body in spec["dynamic_bodies"])
    xml_root = ET.parse(xml_path).getroot()
    for body in spec["dynamic_bodies"]:
        body_xml = next(item for item in xml_root.findall(".//body") if item.get("name") == body["name"])
        inertial = body_xml.find("inertial")
        geom = body_xml.find("geom")
        assert inertial is not None
        assert float(inertial.get("mass", "0")) == pytest.approx(body["mass_kg"])
        assert geom is not None
        assert geom.get("mass") is None
    masses = {body["name"]: body["mass_kg"] for body in spec["dynamic_bodies"]}
    assert masses["desk_organizer"] == pytest.approx(0.6)
    assert model.nbody == 1 + 2 * len(spec["dynamic_bodies"])
    assert metadata_path.exists()
    assert spec["source"]["source_data_modified"] is False
