from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scripts.build_replica_cad_pipeline import compile_replica_cad_scene  # noqa: E402
from replica_physics_twin.replica_cad_scene import render_replica_cad_mjcf  # noqa: E402


DATASET_ROOT = PROJECT_ROOT / "data" / "raw" / "replica_cad"


def test_render_replica_cad_mjcf_uses_a_deformable_flex_for_cloth(tmp_path: Path) -> None:
    """A cloth selection must be a MuJoCo flex, not one rigid freejoint mesh."""

    mesh_path = tmp_path / "cloth.obj"
    mesh_path.write_text(
        "v -0.5 0 0\n"
        "v 0.5 0 0\n"
        "v -0.5 0 1\n"
        "v 0.5 0 1\n"
        "f 1 2 4\n"
        "f 1 4 3\n",
        encoding="utf-8",
    )
    body = {
        "name": "replica_cloth_test",
        "initial_position_m": [0.0, 0.0, 1.5],
        "initial_quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        "center_of_mass_m": [0.0, 0.0, 0.0],
        "mass_kg": 1.0,
        "inertia_diagonal_kg_m2": [0.1, 0.1, 0.1],
        "friction": {"sliding": 0.8, "torsional": 0.005, "rolling": 0.001},
        "mesh_name": "cloth_test_mesh",
        "collision_mesh_file": str(mesh_path),
        "deformable": True,
        "deformable_type": "cloth",
        "cloth_grid": {
            "cols": 6,
            "rows": 10,
            "local_bounds_min_m": [-0.5, 0.0, 0.0],
            "local_bounds_max_m": [0.5, 0.0, 1.0],
        },
        "cloth_material": {
            "young_pa": 2500.0,
            "poisson": 0.3,
            "damping": 0.15,
            "thickness_m": 0.002,
            "radius_m": 0.002,
        },
    }
    manifest = {
        "stage": {
            "collision_bounds_min_m": [-4.0, -4.0, 0.0],
            "collision_bounds_max_m": [4.0, 4.0, 4.0],
        },
        "static_collision_instances": [],
        "dynamic_bodies": [body],
    }

    xml = render_replica_cad_mjcf(manifest)
    assert '<flexcomp name="replica_cloth_test"' in xml
    assert "<elasticity" in xml
    assert 'elastic2d="both"' in xml
    assert 'timestep="0.0005"' in xml
    assert "<pin" not in xml
    assert 'solref="0.05 1"' in xml
    assert '<weld name="pin_replica_cloth_test_0" body1="replica_cloth_test_9"' in xml
    assert "<freejoint name=\"replica_cloth_test_freejoint\"" not in xml
    model = mujoco.MjModel.from_xml_string(xml)
    assert model.nflex == 1
    assert model.nflexvert == body["cloth_grid"]["cols"] * body["cloth_grid"]["rows"]
    assert model.neq == body["cloth_grid"]["cols"]


def test_render_replica_cad_mjcf_preserves_initial_contact_exclusions() -> None:
    """Known scan penetrations must not become a one-frame physics impulse."""

    manifest = {
        "stage": {
            "collision_bounds_min_m": [-4.0, -4.0, 0.0],
            "collision_bounds_max_m": [4.0, 4.0, 4.0],
        },
        "static_collision_instances": [],
        "dynamic_bodies": [],
        "initial_contact_exclusions": [
            {
                "body1": "replica_bike_02_100",
                "body2": "static_frl_apartment_table_01_59",
                "reason": "initial_scan_intersection",
            }
        ],
    }

    xml = render_replica_cad_mjcf(manifest)
    assert '<contact>' in xml
    assert '<exclude body1="replica_bike_02_100" body2="static_frl_apartment_table_01_59"' in xml


@pytest.mark.skipif(not DATASET_ROOT.is_dir(), reason="ReplicaCAD dataset is not downloaded")
def test_replica_cad_compiler_keeps_source_geometry_mass_and_convex_collision(tmp_path: Path) -> None:
    manifest = compile_replica_cad_scene(
        dataset_root=DATASET_ROOT,
        scene_id="apt_0",
        output_root=tmp_path,
        selected_templates=(
            "frl_apartment_bike_02",
            "frl_apartment_cloth_01",
            "frl_apartment_cloth_02",
        ),
    )

    expected_masses = {
        "frl_apartment_bike_02": 9.0,
        "frl_apartment_cloth_01": 2.0,
        "frl_apartment_cloth_02": 0.6,
    }
    bike = next(body for body in manifest["dynamic_bodies"] if body["template_name"] == "frl_apartment_bike_02")
    # The source scan has a small roll/pitch lean that is not self-supporting
    # on the two wheel contacts.  The interaction scenario starts with the
    # bike resting upright; the user must then drag/push it to tip it.
    assert abs(float(bike["initial_quaternion_wxyz"][1])) < 1e-6
    assert abs(float(bike["initial_quaternion_wxyz"][2])) < 1e-6
    assert bike["initial_pose_adjustment"] == "upright_yaw_only_for_interaction_start"
    assert manifest["dataset"] == "ReplicaCAD"
    assert manifest["physics_authority"] == "MuJoCo"
    assert Path(manifest["visual_scene_mesh"]).is_file()
    assert Path(manifest["xml_path"]).is_file()
    assert Path(manifest["metadata_path"]).is_file()
    assert len(manifest["static_visual_instances"]) > 0
    assert len(manifest["static_collision_instances"]) == len(manifest["static_visual_instances"])
    bike_name = next(body["name"] for body in manifest["dynamic_bodies"] if body["template_name"] == "frl_apartment_bike_02")
    assert any(
        exclusion["body1"] == bike_name
        and exclusion["body2"].startswith("static_frl_apartment_table_01_")
        for exclusion in manifest["initial_contact_exclusions"]
    )
    presentation_bounds = manifest["presentation_bounds"]
    scene_min = np.asarray(presentation_bounds["min_m"], dtype=float)
    scene_max = np.asarray(presentation_bounds["max_m"], dtype=float)
    assert np.all(scene_max > scene_min)
    assert presentation_bounds["recommended_distance_m"] > float(np.max(scene_max - scene_min))
    assert any(
        record["collision_shape"] == "bounding_box"
        for record in manifest["static_collision_instances"]
    )
    assert any(
        record["collision_shape"] == "replica_cad_convex_decomposition"
        for record in manifest["static_collision_instances"]
    )

    for body in manifest["dynamic_bodies"]:
        assert expected_masses[body["template_name"]] == pytest.approx(body["mass_kg"])
        assert body["mass_source"] == "ReplicaCAD object_config.json:mass"
        assert body["mass_source_value_kg"] == pytest.approx(body["mass_kg"])
        assert len(body["center_of_mass_source_m"]) == 3
        assert body["inertia_source"] == "derived_from_collision_mesh_bounds"
        assert body["collision_shape"] == "replica_cad_convex_decomposition"
        assert Path(body["visual_mesh_file"]).is_file()
        assert Path(body["collision_mesh_file"]).is_file()
        assert body["source_object_id"] >= 0
        assert all(float(value) > 0 for value in body["inertia_diagonal_kg_m2"])

    cloth_materials = {
        body["template_name"]: body["cloth_material"]
        for body in manifest["dynamic_bodies"]
        if body.get("deformable")
    }
    assert cloth_materials["frl_apartment_cloth_01"]["young_pa"] == pytest.approx(25000.0)
    assert cloth_materials["frl_apartment_cloth_01"]["damping"] == pytest.approx(0.06)
    assert cloth_materials["frl_apartment_cloth_02"]["young_pa"] == pytest.approx(12000.0)
    assert cloth_materials["frl_apartment_cloth_02"]["damping"] == pytest.approx(0.04)

    model = mujoco.MjModel.from_xml_path(manifest["xml_path"])
    assert model.nflex == 2
    # The runtime uses an interactive cloth resolution.  Unreal interpolates
    # these physical nodes back onto the source render mesh, so this reduces
    # solver cost without replacing the garment with a rigid primitive.
    assert all(
        int(body["cloth_grid"]["cols"]) == 8 and int(body["cloth_grid"]["rows"]) == 14
        for body in manifest["dynamic_bodies"]
        if body.get("deformable")
    )
    assert model.nflexvert == sum(
        int(body["cloth_grid"]["cols"]) * int(body["cloth_grid"]["rows"])
        for body in manifest["dynamic_bodies"]
        if body.get("deformable")
    )
    assert model.nmocap == sum(not body.get("deformable", False) for body in manifest["dynamic_bodies"])
    assert model.nbody > 1 + len(manifest["dynamic_bodies"])
    assert model.ngeom >= 1 + len(manifest["static_collision_instances"])
    xml_root = ET.parse(manifest["xml_path"]).getroot()
    for body in manifest["dynamic_bodies"]:
        if body.get("deformable"):
            flex_xml = next(node for node in xml_root.findall(".//flexcomp") if node.get("name") == body["name"])
            assert flex_xml.get("type") == "grid"
            assert flex_xml.find("elasticity") is not None
            assert flex_xml.find("contact") is not None
        else:
            body_xml = next(node for node in xml_root.findall(".//body") if node.get("name") == body["name"])
            assert body_xml.find("freejoint") is not None
            geom = body_xml.find("geom")
            assert geom is not None
            assert geom.get("type") == "mesh"
            assert geom.get("mesh")
            assert body_xml.find("inertial") is not None
            mocap_body = next(
                (node for node in xml_root.findall(".//body") if node.get("name") == f"mocap_{body['name']}"),
                None,
            )
            assert mocap_body is not None
            equality = xml_root.find("equality")
            assert equality is not None
            assert any(node.get("name") == f"grab_{body['name']}" for node in equality.findall("weld"))

    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    for body in manifest["dynamic_bodies"]:
        if not body.get("deformable"):
            continue
        flex_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_FLEX, body["name"]))
        start = int(model.flex_vertadr[flex_id])
        count = int(model.flex_vertnum[flex_id])
        initial_vertices = data.flexvert_xpos[start : start + count].copy()
        for _ in range(600):
            mujoco.mj_step(model, data)
        assert np.max(np.linalg.norm(data.flexvert_xpos[start : start + count] - initial_vertices, axis=1)) > 0.01

    table_records = [
        record
        for record in manifest["static_collision_instances"]
        if record["template_name"] == "frl_apartment_table_01"
    ]
    assert table_records
    assert any(record["collision_shape"] == "replica_cad_convex_decomposition" for record in table_records)
    assert 'name="replica_cad_floor"' in Path(manifest["xml_path"]).read_text(encoding="utf-8")


@pytest.mark.skipif(not DATASET_ROOT.is_dir(), reason="ReplicaCAD dataset is not downloaded")
def test_replica_cad_generated_scene_has_real_contacts_and_mass_inertia(tmp_path: Path) -> None:
    manifest = compile_replica_cad_scene(
        dataset_root=DATASET_ROOT,
        scene_id="apt_0",
        output_root=tmp_path,
        selected_templates=("frl_apartment_box",),
    )
    model = mujoco.MjModel.from_xml_path(manifest["xml_path"])
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    body = manifest["dynamic_bodies"][0]
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body["name"])
    assert body_id >= 0
    assert model.body_mass[body_id] == pytest.approx(3.1)
    assert body["mujoco_mass_kg"] == pytest.approx(model.body_mass[body_id])
    assert body["mass_validation"] == "passed"
    assert np.all(model.body_inertia[body_id] > 0)

    joint_id = int(model.body_jntadr[body_id])
    qpos_start = int(model.jnt_qposadr[joint_id])
    data.qpos[qpos_start : qpos_start + 3] = [0.0, 0.0, 3.5]
    data.qvel[:] = 0.0
    mujoco.mj_forward(model, data)
    initial = data.xpos[body_id].copy()
    max_contacts = 0
    minimum_z = initial[2]
    for _ in range(900):
        mujoco.mj_step(model, data)
        max_contacts = max(max_contacts, int(data.ncon))
        minimum_z = min(minimum_z, float(data.xpos[body_id, 2]))
    assert minimum_z < initial[2] - 0.1
    assert max_contacts > 0

    metadata = json.loads(Path(manifest["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["dynamic_bodies"][0]["source"]["mass_kg"] == pytest.approx(3.1)
