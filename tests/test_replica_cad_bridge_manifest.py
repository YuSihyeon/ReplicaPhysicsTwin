from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from replica_physics_twin.bridge_server import MuJoCoBridgeServer  # noqa: E402


def test_bridge_reads_replica_cad_dynamic_body_records(tmp_path: Path) -> None:
    xml_path = tmp_path / "scene.xml"
    xml_path.write_text(
        """<mujoco><worldbody><body name=\"replica_box_0\" pos=\"0 0 1\"><freejoint/><geom type=\"box\" size=\".1 .1 .1\"/></body></worldbody></mujoco>""",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset": "ReplicaCAD",
                "dynamic_bodies": [
                    {
                        "name": "replica_box_0",
                        "template_name": "frl_apartment_box",
                        "source_object_id": 42,
                        "display_name": "box",
                        "size_m": [0.3, 0.2, 0.1],
                        "mass_kg": 3.1,
                        "inertia_diagonal_kg_m2": [0.01, 0.02, 0.03],
                        "friction": {"sliding": 0.8, "torsional": 0.005, "rolling": 0.001},
                        "movable": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    server = MuJoCoBridgeServer(xml_path, physical_manifest_path=manifest_path)
    server._load_physical_manifest()

    record = server._physical_by_body_name["replica_box_0"]
    assert record["object_id"] == 42
    assert record["role"] == "box"
    assert record["mass_kg"] == 3.1
    assert server._physical_by_body_name["box"]["object_id"] == 42


def test_bridge_publishes_flex_vertices_for_deformable_object(tmp_path: Path) -> None:
    xml_path = tmp_path / "cloth.xml"
    xml_path.write_text(
        """<mujoco><option gravity=\"0 0 -9.81\"/><worldbody>
        <geom type=\"box\" size=\"2 2 0.05\" pos=\"0 0 -0.05\"/>
        <flexcomp name=\"replica_cloth_0\" type=\"grid\" dim=\"2\" count=\"4 6 1\" spacing=\"0.2 0.2 0.01\" pos=\"0 0 1\" mass=\"1\" radius=\"0.002\">
          <pin id=\"5 11 17 23\"/>
          <elasticity young=\"1500\" poisson=\"0.3\" damping=\"0.1\" thickness=\"0.002\"/>
          <contact selfcollide=\"none\"/>
        </flexcomp></worldbody></mujoco>""",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dynamic_bodies": [
                    {
                        "name": "replica_cloth_0",
                        "source_object_id": 7,
                        "display_name": "cloth",
                        "deformable": True,
                        "size_m": [0.6, 0.01, 1.0],
                        "mass_kg": 1.0,
                        "inertia_diagonal_kg_m2": [],
                        "friction": {"sliding": 0.8, "torsional": 0.005, "rolling": 0.001},
                        "movable": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    server = MuJoCoBridgeServer(xml_path, physical_manifest_path=manifest_path)
    server._model, server._data = __import__("mujoco").MjModel.from_xml_path(str(xml_path)), None  # noqa: SLF001
    server._data = __import__("mujoco").MjData(server._model)  # noqa: SLF001
    server._load_physical_manifest()  # noqa: SLF001
    server._reset_simulation()  # noqa: SLF001
    initial = server._state_objects()[0]  # noqa: SLF001
    assert len(initial["deformed_vertices_m"]) == 24
    for _ in range(60):
        server._step_once()  # noqa: SLF001
    moved = server._state_objects()[0]  # noqa: SLF001
    assert moved["deformed_vertices_m"] != initial["deformed_vertices_m"]


def test_bridge_applies_wind_force_to_flex_cloth(tmp_path: Path) -> None:
    xml_path = tmp_path / "wind_cloth.xml"
    xml_path.write_text(
        """<mujoco><option gravity=\"0 0 0\" wind=\"0 0 4\" density=\"1.225\" viscosity=\"0\" timestep=\"0.001\"/>
        <worldbody>
          <flexcomp name=\"replica_cloth_wind\" type=\"grid\" dim=\"2\" count=\"3 3 1\" spacing=\"0.2 0.2 0.01\" pos=\"0 0 1\" mass=\"1\" radius=\"0.002\">
            <elasticity young=\"800\" poisson=\"0.3\" damping=\"0.15\" thickness=\"0.002\" elastic2d=\"both\"/>
            <contact selfcollide=\"none\"/>
          </flexcomp>
        </worldbody>
        <equality>
          <weld name=\"pin_replica_cloth_wind_0\" body1=\"replica_cloth_wind_2\"/>
          <weld name=\"pin_replica_cloth_wind_1\" body1=\"replica_cloth_wind_5\"/>
          <weld name=\"pin_replica_cloth_wind_2\" body1=\"replica_cloth_wind_8\"/>
        </equality></mujoco>""",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dynamic_bodies": [
                    {
                        "name": "replica_cloth_wind",
                        "source_object_id": 8,
                        "display_name": "cloth",
                        "deformable": True,
                        "cloth_grid": {
                            "cols": 3,
                            "rows": 3,
                        },
                        "cloth_material": {"wind_drag_coefficient": 1.3},
                        "mass_kg": 1.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    server = MuJoCoBridgeServer(xml_path, physical_manifest_path=manifest_path)
    server._model = __import__("mujoco").MjModel.from_xml_path(str(xml_path))  # noqa: SLF001
    server._data = __import__("mujoco").MjData(server._model)  # noqa: SLF001
    server._load_physical_manifest()  # noqa: SLF001
    server._reset_simulation()  # noqa: SLF001
    server._apply_cloth_aerodynamic_forces()  # noqa: SLF001
    assert float(np.linalg.norm(server._data.qfrc_applied)) > 1e-8  # noqa: SLF001
