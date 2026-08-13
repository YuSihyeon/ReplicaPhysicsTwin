from __future__ import annotations

import json

import mujoco

from replica_physics_twin.office0_collision import (
    build_collision_spec,
    render_collision_mjcf,
)


def _fixture_inputs() -> tuple[dict, dict, dict[int, dict]]:
    manifest = {
        "scene_id": "office_0",
        "candidate_object_ids": {
            "floor": [63],
            "wall": [8, 18],
            "table": [12],
            "bookcase": [],
        },
        "object_records": [
            {"id": 8, "class_name": "wall", "oriented_bbox": {"abb": {"center": [0, 0, 1], "sizes": [0.2, 2, 2]}}},
            {"id": 18, "class_name": "wall", "oriented_bbox": {"abb": {"center": [0, 0, 1], "sizes": [0.01, 0.01, 0.5]}}},
            {"id": 12, "class_name": "table", "oriented_bbox": {"abb": {"center": [1, 0, 0.5], "sizes": [1, 1, 1]}}},
            {"id": 49, "class_name": "undefined", "oriented_bbox": {"abb": {"center": [0, 1, 1], "sizes": [2, 0.7, 1.8]}}},
        ],
    }
    visual_metadata = {
        "coordinate_transform": {"translation_m": [-1.0, -2.0, 1.0]},
        "source_bounds_m": {"min": [0.0, 0.0, 0.0], "max": [4.0, 5.0, 3.0]},
        "output_bounds_cm": {"min": [-100.0, -200.0, 0.0], "max": [300.0, 300.0, 300.0]},
    }
    measured_bounds = {
        8: {"min": [0.0, 0.5, 0.0], "max": [0.2, 1.5, 2.0], "face_count": 10},
        18: {"min": [0.0, 0.0, 0.0], "max": [0.01, 0.01, 0.5], "face_count": 2},
        12: {
            "min": [0.5, 0.5, 0.0],
            "max": [1.5, 1.5, 1.0],
            "face_count": 20,
            "top_surface": {"min": [0.6, 0.6, 0.9], "max": [1.4, 1.4, 1.0], "face_count": 8},
        },
        49: {"min": [0.1, 0.65, 0.1], "max": [1.5, 1.35, 1.9], "face_count": 20},
        63: {"min": [0.0, 0.0, 0.0], "max": [4.0, 5.0, 0.05], "face_count": 4},
    }
    return manifest, visual_metadata, measured_bounds


def test_collision_spec_uses_visual_transform_and_does_not_invent_bookcase() -> None:
    manifest, visual_metadata, measured_bounds = _fixture_inputs()

    spec = build_collision_spec(manifest, visual_metadata, measured_bounds)

    assert spec["coordinate_system"]["units"] == "meter"
    assert spec["alignment_check"]["passed"] is True
    assert {proxy["role"] for proxy in spec["proxies"]} >= {"floor", "wall", "desk"}

    wall = next(proxy for proxy in spec["proxies"] if proxy["name"] == "wall_8")
    assert wall["center_m"] == [-0.9, -1.0, 2.0]
    assert wall["source_object_ids"] == [8]

    desk = next(proxy for proxy in spec["proxies"] if proxy["name"] == "desk_12")
    assert desk["size_m"][2] <= 0.15
    assert "top_surface" in desk["basis"]

    assert not any(proxy["role"] == "bookcase" for proxy in spec["proxies"])
    unresolved = next(item for item in spec["unresolved_roles"] if item["role"] == "bookcase")
    assert unresolved["status"] == "not_present_in_scene"
    assert unresolved["requires_user_input"] is False
    assert 49 in unresolved["potential_unclassified_object_ids"]

    assert not any(proxy["name"] == "wall_18" for proxy in spec["proxies"])


def test_collision_mjcf_compiles_with_static_proxies_and_multiple_test_boxes() -> None:
    manifest, visual_metadata, measured_bounds = _fixture_inputs()
    spec = build_collision_spec(manifest, visual_metadata, measured_bounds)

    xml_text = render_collision_mjcf(spec)
    model = mujoco.MjModel.from_xml_string(xml_text)

    assert model.ngeom == len(spec["proxies"]) + len(spec["test_bodies"])
    assert model.nbody == 1 + len(spec["test_bodies"])
    assert "name=\"floor\"" in xml_text
    assert "name=\"drop_desk_12\"" in xml_text
    json.dumps(spec)


def test_visible_solid_semantic_furniture_gets_a_fixed_proxy() -> None:
    manifest, visual_metadata, measured_bounds = _fixture_inputs()
    manifest["object_records"].append(
        {"id": 4, "class_name": "chair", "oriented_bbox": {"abb": {"center": [1, 1, 0.5], "sizes": [1, 1, 1]}}}
    )
    measured_bounds[4] = {"min": [1.0, 1.0, 0.0], "max": [2.0, 2.0, 1.0], "face_count": 12}

    spec = build_collision_spec(manifest, visual_metadata, measured_bounds)

    chair = next(proxy for proxy in spec["proxies"] if proxy["name"] == "chair_4")
    assert chair["role"] == "furniture"
    assert chair["source_object_ids"] == [4]
    assert chair["provisional"] is True
