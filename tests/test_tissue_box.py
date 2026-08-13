from __future__ import annotations

import json
from pathlib import Path

import mujoco
import pytest

from replica_physics_twin.office0_collision import build_collision_spec, render_collision_mjcf
from replica_physics_twin.tissue_box import (
    TISSUE_BOX_OBJECT_ID,
    TISSUE_BOX_LIFT_M,
    build_tissue_box_spec,
    run_tissue_box_lift_drop_validation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data" / "derived" / "office_0" / "scene_manifest.json"
VISUAL_METADATA_PATH = PROJECT_ROOT / "outputs" / "metadata" / "office_0_visual_transform.json"
COLLISION_METADATA_PATH = PROJECT_ROOT / "outputs" / "metadata" / "office0_collision_proxy.json"
COLLISION_XML_PATH = PROJECT_ROOT / "outputs" / "mjcf" / "office0_collision_proxy.xml"


def test_tissue_box_spec_uses_fixed_object_id_and_manifest_initialization() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    visual_metadata = json.loads(VISUAL_METADATA_PATH.read_text(encoding="utf-8"))
    base_spec = json.loads(COLLISION_METADATA_PATH.read_text(encoding="utf-8"))
    measured_bounds = {
        TISSUE_BOX_OBJECT_ID: {
            "min": [-0.3703297972679138, -0.961015522480011, -0.5491282939910889],
            "max": [-0.2001780867576599, -0.8101433515548706, -0.3368523120880127],
            "face_count": 389,
        }
    }

    spec = build_tissue_box_spec(base_spec, manifest, visual_metadata, measured_bounds)
    body = spec["dynamic_bodies"][0]

    assert body["name"] == "tissue_box"
    assert body["source_object_id"] == TISSUE_BOX_OBJECT_ID
    assert body["support_proxy"] == "desk_58"
    assert body["initial_position_m"] == pytest.approx(body["rest_position_m"])
    assert body["mass_kg"] > 0.0
    assert len(body["inertia_diagonal_kg_m2"]) == 3
    assert spec["tissue_box"]["class_name"] == "tissue-paper"


def test_tissue_box_mjcf_compiles_and_lift_drop_settles(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    visual_metadata = json.loads(VISUAL_METADATA_PATH.read_text(encoding="utf-8"))
    base_spec = json.loads(COLLISION_METADATA_PATH.read_text(encoding="utf-8"))
    measured_bounds = {
        TISSUE_BOX_OBJECT_ID: {
            "min": [-0.3703297972679138, -0.961015522480011, -0.5491282939910889],
            "max": [-0.2001780867576599, -0.8101433515548706, -0.3368523120880127],
            "face_count": 389,
        }
    }
    spec = build_tissue_box_spec(base_spec, manifest, visual_metadata, measured_bounds)
    xml_path = tmp_path / "office0_tissue_box.xml"
    xml_path.write_text(render_collision_mjcf(spec), encoding="utf-8")
    model = mujoco.MjModel.from_xml_path(str(xml_path))

    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "tissue_box") >= 0
    assert model.nbody == 2

    validation = run_tissue_box_lift_drop_validation(xml_path, spec, tmp_path, max_steps=3000)
    assert validation["passed"], validation
    assert validation["lift_height_error_m"] <= 1.0e-6
    assert validation["support_proxy"] == "desk_58"
