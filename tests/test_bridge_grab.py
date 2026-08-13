from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import mujoco
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from replica_physics_twin.bridge_protocol import decode_message_line, encode_message  # noqa: E402
from replica_physics_twin.bridge_server import MuJoCoBridgeServer  # noqa: E402
from replica_physics_twin.physics_validation import load_simulation  # noqa: E402
from scripts.build_office0_interaction_scene import run_build  # noqa: E402
PHYSICAL_MANIFEST_PATH = PROJECT_ROOT / "outputs/metadata/office0_physical_manifest.json"


def _write_mass_grab_fixture(path: Path) -> None:
    path.write_text(
        """<mujoco model="mass_grab_fixture">
  <option gravity="0 0 0" timestep="0.002" integrator="Euler"/>
  <worldbody>
    <body name="light_box" pos="-1 0 0">
      <freejoint name="light_box_freejoint"/>
      <inertial pos="0 0 0" mass="0.6" diaginertia="0.01 0.01 0.01"/>
      <geom name="light_box_geom" type="box" size="0.05 0.05 0.05"/>
    </body>
    <body name="heavy_box" pos="1 0 0">
      <freejoint name="heavy_box_freejoint"/>
      <inertial pos="0 0 0" mass="8.0" diaginertia="0.01 0.01 0.01"/>
      <geom name="heavy_box_geom" type="box" size="0.05 0.05 0.05"/>
    </body>
    <body name="mocap_light_box" mocap="true" pos="-1 0 0"/>
    <body name="mocap_heavy_box" mocap="true" pos="1 0 0"/>
  </worldbody>
  <equality>
    <weld name="grab_light_box" body1="light_box" body2="mocap_light_box" active="false"/>
    <weld name="grab_heavy_box" body1="heavy_box" body2="mocap_heavy_box" active="false"/>
  </equality>
  <keyframe>
    <key name="initial" qpos="-1 0 0 1 0 0 0 1 0 0 1 0 0 0" qvel="0 0 0 0 0 0 0 0 0 0 0 0"/>
  </keyframe>
</mujoco>
""",
        encoding="utf-8",
    )


def _read_message(client: socket.socket, message_type: str, *, minimum_seq: int = -1) -> dict:
    buffer = b""
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        buffer += client.recv(65536)
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            if not raw:
                continue
            message = decode_message_line(raw.decode("utf-8"))
            if message.get("type") == message_type and int(message.get("seq", minimum_seq)) >= minimum_seq:
                return message
    raise AssertionError(f"did not receive {message_type} after seq {minimum_seq}")


def test_group_grab_moves_objects_through_mocap_constraints(tmp_path: Path) -> None:
    xml_path = tmp_path / "interaction.xml"
    metadata_path = tmp_path / "interaction.json"
    run_build(xml_path=xml_path, metadata_path=metadata_path)
    server = MuJoCoBridgeServer(
        xml_path,
        physical_manifest_path=PHYSICAL_MANIFEST_PATH,
        host="127.0.0.1",
        port=0,
        state_hz=240.0,
    )
    server.start()
    try:
        client = socket.create_connection((server.host, server.port), timeout=4.0)
        client.settimeout(4.0)
        try:
            first = _read_message(client, "state")
            objects = {item["id"]: item for item in first["objects"]}
            anchor = objects["tissue_box"]["position_m"]
            begin = {
                "type": "command",
                "schema_version": 2,
                "command": "grab_begin",
                "client_grab_id": "grab-test",
                "object_ids": ["tissue_box", "desk_organizer"],
                "anchor_m": anchor,
            }
            client.sendall(encode_message(begin).encode("utf-8"))
            ack = _read_message(client, "ack")
            assert ack["grab_id"] == "grab-test"

            target = [anchor[0] + 0.30, anchor[1], anchor[2]]
            update = {
                "type": "command",
                "schema_version": 2,
                "command": "grab_update",
                "grab_id": "grab-test",
                "target_position_m": target,
                "target_quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            }
            client.sendall(encode_message(update).encode("utf-8"))
            update_ack = _read_message(client, "ack")
            assert update_ack["grab_id"] == "grab-test"
            moved = None
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                candidate = _read_message(client, "state", minimum_seq=int(first["seq"]) + 1)
                candidate_objects = {item["id"]: item for item in candidate["objects"]}
                if (
                    candidate_objects["tissue_box"]["position_m"][0] > anchor[0] + 0.05
                    and candidate_objects["desk_organizer"]["position_m"][0]
                    > objects["desk_organizer"]["position_m"][0] + 0.05
                ):
                    moved = candidate_objects
                    break
            assert moved is not None

            end = {
                "type": "command",
                "schema_version": 2,
                "command": "grab_end",
                "grab_id": "grab-test",
            }
            client.sendall(encode_message(end).encode("utf-8"))
            assert _read_message(client, "ack")["command"] == "grab_end"
        finally:
            client.close()
    finally:
        server.stop()


def test_grab_motion_is_mass_limited_instead_of_kinematic(tmp_path: Path) -> None:
    """The same mouse target must move a light body more than a heavy body."""

    xml_path = tmp_path / "mass_grab_fixture.xml"
    _write_mass_grab_fixture(xml_path)
    server = MuJoCoBridgeServer(xml_path, host="127.0.0.1", port=0)
    server._model, server._data = load_simulation(xml_path)  # noqa: SLF001
    server._reset_simulation()  # noqa: SLF001
    assert server._model is not None and server._data is not None  # noqa: S101

    def movement_after_grab(object_id: str) -> float:
        server._reset_simulation()  # noqa: SLF001
        body_id = int(mujoco.mj_name2id(server._model, mujoco.mjtObj.mjOBJ_BODY, object_id))
        anchor = [float(value) for value in server._data.xpos[body_id]]
        grab_id = f"mass-{object_id}"
        server._grab_begin(  # noqa: SLF001
            {"client_grab_id": grab_id, "object_ids": [object_id], "anchor_m": anchor}
        )
        server._grab_update(  # noqa: SLF001
            {
                "grab_id": grab_id,
                "target_position_m": [anchor[0] + 0.40, anchor[1], anchor[2]],
                "target_quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            }
        )
        for _ in range(50):
            server._step_once()  # noqa: SLF001
        movement = float(server._data.xpos[body_id][0] - anchor[0])
        server._grab_end({"grab_id": grab_id})  # noqa: SLF001
        return movement

    light_movement = movement_after_grab("light_box")
    heavy_movement = movement_after_grab("heavy_box")
    assert light_movement > heavy_movement + 0.05


def test_grab_force_is_applied_at_the_cursor_point_and_can_create_torque(tmp_path: Path) -> None:
    """Dragging an off-center point must push/rotate, not translate at COM."""

    xml_path = tmp_path / "mass_grab_fixture.xml"
    _write_mass_grab_fixture(xml_path)
    server = MuJoCoBridgeServer(xml_path, host="127.0.0.1", port=0)
    server._model, server._data = load_simulation(xml_path)  # noqa: SLF001
    server._reset_simulation()  # noqa: SLF001
    assert server._model is not None and server._data is not None  # noqa: S101

    body_id = int(mujoco.mj_name2id(server._model, mujoco.mjtObj.mjOBJ_BODY, "light_box"))
    anchor = server._data.xpos[body_id].copy() + np.asarray([0.0, 0.04, 0.0])
    server._grab_begin(  # noqa: SLF001
        {"client_grab_id": "torque-grab", "object_ids": ["light_box"], "anchor_m": anchor.tolist()}
    )
    server._grab_update(  # noqa: SLF001
        {
            "grab_id": "torque-grab",
            "target_position_m": (anchor + np.asarray([0.40, 0.0, 0.0])).tolist(),
            "target_quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        }
    )
    for _ in range(50):
        server._step_once()  # noqa: SLF001

    joint_id = int(server._model.body_jntadr[body_id])
    dof_start = int(server._model.jnt_dofadr[joint_id])
    assert np.linalg.norm(server._data.qvel[dof_start + 3 : dof_start + 6]) > 1e-5


def test_object_grab_does_not_wake_unselected_dynamic_objects(tmp_path: Path) -> None:
    """A bike drag must not make an unrelated garment start simulating."""

    xml_path = tmp_path / "mass_grab_fixture.xml"
    _write_mass_grab_fixture(xml_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dynamic_bodies": [
                    {
                        "name": "light_box",
                        "display_name": "light_box",
                        "mass_kg": 0.6,
                        "inertia_diagonal_kg_m2": [0.01, 0.01, 0.01],
                        "movable": True,
                    },
                    {
                        "name": "heavy_box",
                        "display_name": "heavy_box",
                        "mass_kg": 8.0,
                        "inertia_diagonal_kg_m2": [0.01, 0.01, 0.01],
                        "movable": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    server = MuJoCoBridgeServer(xml_path, physical_manifest_path=manifest_path, host="127.0.0.1", port=0)
    server._model, server._data = load_simulation(xml_path)  # noqa: SLF001
    server._load_physical_manifest()  # noqa: SLF001
    server._load_physical_manifest()  # noqa: SLF001
    server._reset_simulation()  # noqa: SLF001
    assert server._model is not None and server._data is not None  # noqa: S101

    heavy_id = int(mujoco.mj_name2id(server._model, mujoco.mjtObj.mjOBJ_BODY, "heavy_box"))
    light_id = int(mujoco.mj_name2id(server._model, mujoco.mjtObj.mjOBJ_BODY, "light_box"))
    heavy_start = server._data.xpos[heavy_id].copy()
    light_anchor = server._data.xpos[light_id].copy()
    server._execute_command(  # noqa: SLF001
        {
            "command": "grab_begin",
            "object_ids": ["light_box"],
            "client_grab_id": "selective-grab",
            "anchor_m": light_anchor.tolist(),
        }
    )
    server._grab_update(  # noqa: SLF001
        {
            "grab_id": "selective-grab",
            "target_position_m": (light_anchor + np.asarray([0.40, 0.0, 0.0])).tolist(),
            "target_quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        }
    )
    for _ in range(50):
        server._step_once()  # noqa: SLF001

    assert np.allclose(server._data.xpos[heavy_id], heavy_start, atol=1e-9)
    assert server._data.xpos[light_id, 0] > light_anchor[0]
