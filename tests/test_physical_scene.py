from __future__ import annotations

import mujoco

from replica_physics_twin.physical_scene import (
    build_interaction_scene_spec,
    render_interaction_mjcf,
)


def _fixture() -> tuple[dict, dict, dict, dict[int, dict]]:
    collision_spec = {
        "proxies": [
            {
                "name": "floor",
                "role": "floor",
                "center_m": [0.0, 0.0, -0.05],
                "half_size_m": [2.0, 2.0, 0.05],
                "size_m": [4.0, 4.0, 0.1],
            },
            {
                "name": "desk_58",
                "role": "desk",
                "center_m": [0.0, 0.0, 0.45],
                "half_size_m": [1.5, 1.5, 0.05],
                "size_m": [3.0, 3.0, 0.1],
                "max_m": [1.5, 1.5, 0.5],
            },
        ]
    }
    physical_manifest = {
        "physics_authority": "MuJoCo",
        "objects": [
            {
                "object_id": 28,
                "class_name": "tissue-paper",
                "role": "tissue_box",
                "body_type": "dynamic",
                "movable": True,
                "mass_kg": 0.5,
                "inertia_diagonal_kg_m2": [0.003, 0.003, 0.003],
                "friction": {"sliding": 0.5, "torsional": 0.005, "rolling": 0.001},
            },
            {
                "object_id": 44,
                "class_name": "desk-organizer",
                "role": "dynamic_object",
                "body_type": "dynamic",
                "movable": True,
                "mass_kg": 0.5,
                "inertia_diagonal_kg_m2": [0.003, 0.003, 0.003],
                "friction": {"sliding": 0.5, "torsional": 0.005, "rolling": 0.001},
            },
            {
                "object_id": 4,
                "class_name": "chair",
                "role": None,
                "body_type": "dynamic",
                "movable": True,
                "mass_kg": 8.0,
                "inertia_diagonal_kg_m2": [0.4, 0.4, 0.4],
                "friction": {"sliding": 0.6, "torsional": 0.005, "rolling": 0.001},
            },
        ],
    }
    visual_metadata = {"coordinate_transform": {"translation_m": [0.0, 0.0, 0.0]}}
    measured_bounds = {
        28: {"min": [-0.45, -0.1, 0.5], "max": [-0.25, 0.1, 0.7], "face_count": 10},
        44: {"min": [-0.15, -0.1, 0.5], "max": [0.05, 0.1, 0.7], "face_count": 10},
        4: {"min": [0.5, 0.5, 0.0], "max": [1.1, 1.5, 0.8], "face_count": 30},
    }
    return collision_spec, physical_manifest, visual_metadata, measured_bounds


def test_scene_contains_multiple_freejoint_bodies_and_static_environment() -> None:
    collision_spec, physical_manifest, visual_metadata, measured_bounds = _fixture()
    spec = build_interaction_scene_spec(
        collision_spec,
        physical_manifest,
        visual_metadata,
        measured_bounds,
        dynamic_object_ids=[28, 44],
    )
    model = mujoco.MjModel.from_xml_string(render_interaction_mjcf(spec))

    assert [body["name"] for body in spec["dynamic_bodies"]] == ["tissue_box", "desk_organizer"]
    assert model.nbody == 5
    assert model.ngeom == 4
    assert model.njnt == 2
    assert model.nmocap == 2
    assert model.neq == 2


def test_dynamic_object_pushes_dynamic_environment_object() -> None:
    collision_spec, physical_manifest, visual_metadata, measured_bounds = _fixture()
    spec = build_interaction_scene_spec(
        collision_spec,
        physical_manifest,
        visual_metadata,
        measured_bounds,
        dynamic_object_ids=[28, 44],
    )
    model = mujoco.MjModel.from_xml_string(render_interaction_mjcf(spec))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    tissue_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "tissue_box")
    organizer_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "desk_organizer")
    tissue_dof = int(model.jnt_dofadr[model.body_jntadr[tissue_id]])
    initial_x = float(data.xpos[organizer_id][0])
    data.qvel[tissue_dof] = 3.0

    for _ in range(600):
        mujoco.mj_step(model, data)

    assert float(data.xpos[organizer_id][0]) > initial_x + 0.01


def test_overlapping_dynamic_objects_are_separated_on_their_support_surface() -> None:
    collision_spec, physical_manifest, visual_metadata, measured_bounds = _fixture()
    measured_bounds[44] = {
        "min": [-0.38, -0.1, 0.5],
        "max": [0.02, 0.1, 0.7],
        "face_count": 10,
    }

    spec = build_interaction_scene_spec(
        collision_spec,
        physical_manifest,
        visual_metadata,
        measured_bounds,
        dynamic_object_ids=[28, 44],
    )

    tissue = next(body for body in spec["dynamic_bodies"] if body["name"] == "tissue_box")
    organizer = next(body for body in spec["dynamic_bodies"] if body["name"] == "desk_organizer")
    assert organizer["placement_adjustment_m"][1] > 0.0
    tissue_y_max = tissue["initial_position_m"][1] + tissue["half_size_m"][1]
    organizer_y_min = organizer["initial_position_m"][1] - organizer["half_size_m"][1]
    assert organizer_y_min >= tissue_y_max + 0.02


def test_dynamic_object_mesh_assets_are_rendered_as_mesh_geoms() -> None:
    collision_spec, physical_manifest, visual_metadata, measured_bounds = _fixture()
    spec = build_interaction_scene_spec(
        collision_spec,
        physical_manifest,
        visual_metadata,
        measured_bounds,
        dynamic_object_ids=[28, 44],
        dynamic_mesh_assets={
            "tissue_box": "../meshes/office_0_tissue_box.obj",
            "desk_organizer": "../meshes/office_0_desk_organizer.obj",
        },
    )

    xml_text = render_interaction_mjcf(spec)

    assert 'name="tissue_box_mesh"' in xml_text
    assert 'name="desk_organizer_mesh"' in xml_text
    assert 'type="mesh" mesh="tissue_box_mesh"' in xml_text
    assert 'type="mesh" mesh="desk_organizer_mesh"' in xml_text
