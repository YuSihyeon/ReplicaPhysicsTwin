from __future__ import annotations

import json
from pathlib import Path

from replica_physics_twin.physical_pipeline import run_physical_pipeline_verification
from replica_physics_twin.physical_scene import render_interaction_mjcf


def _write_fixture(root: Path) -> None:
    output_mjcf = root / "outputs/mjcf"
    output_metadata = root / "outputs/metadata"
    output_mjcf.mkdir(parents=True)
    output_metadata.mkdir(parents=True)
    spec = {
        "schema_version": 2,
        "physics_authority": "MuJoCo",
        "coordinate_system": {"units": "meter", "up_axis": "Z"},
        "proxies": [
            {
                "name": "floor",
                "role": "floor",
                "center_m": [0.0, 0.0, -0.05],
                "half_size_m": [2.0, 2.0, 0.05],
                "size_m": [4.0, 4.0, 0.1],
                "min_m": [-2.0, -2.0, -0.1],
                "max_m": [2.0, 2.0, 0.0],
            },
            {
                "name": "desk_58",
                "role": "desk",
                "center_m": [0.0, 0.0, 0.45],
                "half_size_m": [1.5, 1.5, 0.05],
                "size_m": [3.0, 3.0, 0.1],
                "min_m": [-1.5, -1.5, 0.4],
                "max_m": [1.5, 1.5, 0.5],
            },
        ],
        "dynamic_bodies": [
            {
                "name": "tissue_box",
                "role": "tissue_box",
                "source_object_id": 28,
                "initial_position_m": [0.0, 0.0, 0.6],
                "half_size_m": [0.1, 0.1, 0.1],
                "size_m": [0.2, 0.2, 0.2],
                "mass_kg": 0.5,
                "inertia_diagonal_kg_m2": [0.0033333333] * 3,
                "friction": [0.5, 0.005, 0.001],
                "restitution": 0.0,
                "support_proxy": "desk_58",
            },
            {
                "name": "desk_organizer",
                "role": "dynamic_object",
                "source_object_id": 44,
                "initial_position_m": [0.35, 0.0, 0.6],
                "half_size_m": [0.1, 0.1, 0.1],
                "size_m": [0.2, 0.2, 0.2],
                "mass_kg": 0.5,
                "inertia_diagonal_kg_m2": [0.0033333333] * 3,
                "friction": [0.5, 0.005, 0.001],
                "restitution": 0.0,
                "support_proxy": "desk_58",
            },
        ],
        "dynamic_object_ids": [28, 44],
    }
    (output_mjcf / "office0_interaction.xml").write_text(render_interaction_mjcf(spec), encoding="utf-8")
    (output_metadata / "office0_interaction.json").write_text(json.dumps(spec), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "scene_id": "office_0",
        "physics_authority": "MuJoCo",
        "objects": [
            {
                "object_id": 28,
                "class_name": "tissue-paper",
                "role": "tissue_box",
                "movable": True,
                "body_type": "dynamic",
                "size_m": [0.2, 0.2, 0.2],
                "mass_kg": 0.5,
                "inertia_diagonal_kg_m2": [0.0033333333] * 3,
                "friction": {"sliding": 0.5, "torsional": 0.005, "rolling": 0.001},
                "restitution": 0.0,
                "provenance": {"mass_kg": {"source": "mvp_estimate"}, "size_m": {"source": "measured"}},
            },
            {
                "object_id": 44,
                "class_name": "desk-organizer",
                "role": "dynamic_object",
                "movable": True,
                "body_type": "dynamic",
                "size_m": [0.2, 0.2, 0.2],
                "mass_kg": 0.5,
                "inertia_diagonal_kg_m2": [0.0033333333] * 3,
                "friction": {"sliding": 0.5, "torsional": 0.005, "rolling": 0.001},
                "restitution": 0.0,
                "provenance": {"mass_kg": {"source": "user_override"}, "size_m": {"source": "measured"}},
            },
        ],
    }
    (output_metadata / "office0_physical_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_physical_pipeline_validation_covers_contact_reset_and_group_grab(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    result = run_physical_pipeline_verification(tmp_path)

    assert result["automated_passed"] is True
    assert result["contact_response"]["passed"] is True
    assert result["reset_reproducibility"]["passed"] is True
    assert result["bridge_mapping"]["passed"] is True
    assert result["bridge_mapping"]["group_grab"]["movement_m"]["desk_organizer"] > 0.03
    assert result["property_provenance"]["status"] == "NEEDS_MEASUREMENT"
    assert result["unreal_evidence"]["status"] == "NEEDS_USER_VERIFICATION"
