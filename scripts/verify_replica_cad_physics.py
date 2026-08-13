"""Run deterministic drop/contact/mass checks against the compiled ReplicaCAD scene."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import mujoco
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))


def verify(metadata_path: Path) -> dict[str, object]:
    metadata_path = Path(metadata_path).resolve()
    manifest = json.loads(metadata_path.read_text(encoding="utf-8"))
    xml_path = Path(str(manifest["xml_path"])).resolve()
    model = mujoco.MjModel.from_xml_path(str(xml_path))
    data = mujoco.MjData(model)
    bodies = list(manifest["dynamic_bodies"])
    if not bodies:
        raise ValueError("ReplicaCAD manifest contains no dynamic bodies")

    masses: dict[str, float] = {}
    contact_steps: dict[str, int] = {}
    drop_distances: dict[str, float] = {}

    def reset_data() -> None:
        if model.nkey > 0:
            mujoco.mj_resetDataKeyframe(model, data, 0)
        else:
            mujoco.mj_resetData(model, data)
        # Permanent cloth hanging-edge welds stay active; only temporary
        # interaction welds are disabled by a reset.
        for equality_id in range(int(model.neq)):
            equality_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_EQUALITY, equality_id)
            data.eq_active[equality_id] = bool(equality_name and equality_name.startswith("pin_"))
        mujoco.mj_forward(model, data)

    def pinned_flex_body_ids(object_id: str) -> set[int]:
        prefix = f"pin_{object_id}_"
        pinned: set[int] = set()
        for equality_id in range(int(model.neq)):
            equality_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_EQUALITY, equality_id)
            if not equality_name or not equality_name.startswith(prefix):
                continue
            if int(model.eq_objtype[equality_id]) == int(mujoco.mjtObj.mjOBJ_BODY):
                pinned.add(int(model.eq_obj1id[equality_id]))
        return pinned

    def set_cloth_pin_welds(object_id: str, active: bool) -> None:
        prefix = f"pin_{object_id}_"
        for equality_id in range(int(model.neq)):
            equality_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_EQUALITY, equality_id)
            if equality_name and equality_name.startswith(prefix):
                data.eq_active[equality_id] = active

    def move_body_or_cloth_out_of_probe(body: dict[str, object], offset: float) -> None:
        if bool(body.get("deformable", False)):
            flex_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_FLEX, str(body["name"])))
            start = int(model.flex_vertadr[flex_id])
            count = int(model.flex_vertnum[flex_id])
            object_id = str(body["name"])
            set_cloth_pin_welds(object_id, False)
            node_body_ids = sorted(
                set(int(value) for value in model.flex_vertbodyid[start : start + count] if int(value) > 0)
            )
            if not node_body_ids:
                return
            current_center = np.mean([data.xpos[node_body_id] for node_body_id in node_body_ids], axis=0)
            delta = np.asarray([offset, 100.0, 10.0], dtype=float) - current_center
            for node_body_id in node_body_ids:
                joint_id = int(model.body_jntadr[node_body_id])
                qpos_start = int(model.jnt_qposadr[joint_id])
                data.qpos[qpos_start : qpos_start + 3] += delta
            return
        body_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, str(body["name"])))
        joint_id = int(model.body_jntadr[body_id])
        other_qpos = int(model.jnt_qposadr[joint_id])
        data.qpos[other_qpos : other_qpos + 3] = [offset, 100.0, 10.0]

    for index, body in enumerate(bodies):
        body_name = str(body["name"])
        if bool(body.get("deformable", False)):
            flex_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_FLEX, body_name))
            if flex_id < 0:
                raise ValueError(f"MuJoCo flex missing: {body_name}")
            start = int(model.flex_vertadr[flex_id])
            count = int(model.flex_vertnum[flex_id])
            node_body_ids = {
                int(node_body_id)
                for node_body_id in model.flex_vertbodyid[start : start + count]
                if int(node_body_id) > 0
            }
            mujoco_mass = float(sum(model.body_mass[node_body_id] for node_body_id in node_body_ids))
            if not np.isclose(mujoco_mass, float(body["mass_kg"]), rtol=1e-6, atol=1e-8):
                raise AssertionError(f"mass mismatch for {body_name}: {mujoco_mass} != {body['mass_kg']}")
            reset_data()
            for other_index, other_body in enumerate(bodies):
                if other_body["name"] != body_name:
                    move_body_or_cloth_out_of_probe(other_body, 100.0 + other_index * 10.0)
            mujoco.mj_forward(model, data)
            vertices = np.asarray(data.flexvert_xpos[start : start + count], dtype=float).copy()
            initial_center = vertices.mean(axis=0)
            min_z = float(vertices[:, 2].min())
            contacts = 0
            for _ in range(1800):
                mujoco.mj_step(model, data)
                current = np.asarray(data.flexvert_xpos[start : start + count], dtype=float)
                min_z = min(min_z, float(current[:, 2].min()))
                if int(data.ncon) > 0:
                    contacts = max(contacts, int(data.ncon))
            masses[body_name] = mujoco_mass
            contact_steps[body_name] = contacts
            drop_distances[body_name] = float(initial_center[2] - current[:, 2].mean())
            if contact_steps[body_name] <= 0:
                raise AssertionError(f"no MuJoCo cloth contact observed for {body_name}")
            if drop_distances[body_name] <= 0.05:
                raise AssertionError(f"cloth did not fall/deform under gravity: {body_name}")
            continue
        body_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name))
        if body_id < 0:
            raise ValueError(f"MuJoCo body missing: {body_name}")
        joint_id = int(model.body_jntadr[body_id])
        qpos_start = int(model.jnt_qposadr[joint_id])
        reset_data()
        # Isolate the target body while keeping the real stage/table contact
        # geometry.  This avoids a source-scene prop launching the test body
        # during a deterministic drop check.
        for other_index, other_body in enumerate(bodies):
            if other_body["name"] == body_name:
                continue
            move_body_or_cloth_out_of_probe(other_body, 100.0 + other_index * 10.0)
        # Use a common neutral point over the stage for this isolated drop
        # check.  The compiled source poses remain untouched in the XML and
        # are the poses used by the interactive runtime.
        data.qpos[qpos_start : qpos_start + 3] = [0.0, 0.0, 3.5 + index * 0.4]
        mujoco.mj_forward(model, data)
        initial_z = float(data.xpos[body_id, 2])
        min_z = initial_z
        contacts = 0
        for _ in range(1800):
            mujoco.mj_step(model, data)
            min_z = min(min_z, float(data.xpos[body_id, 2]))
            body_contact_count = 0
            for contact_index in range(int(data.ncon)):
                contact = data.contact[contact_index]
                if body_id in {
                    int(model.geom_bodyid[int(contact.geom1)]),
                    int(model.geom_bodyid[int(contact.geom2)]),
                }:
                    body_contact_count += 1
            contacts = max(contacts, body_contact_count)
        masses[body_name] = float(model.body_mass[body_id])
        contact_steps[body_name] = contacts
        drop_distances[body_name] = initial_z - min_z

    expected_masses = {str(body["name"]): float(body["mass_kg"]) for body in bodies}
    for name, expected in expected_masses.items():
        if not np.isclose(masses[name], expected, rtol=1e-6, atol=1e-8):
            raise AssertionError(f"mass mismatch for {name}: {masses[name]} != {expected}")
        if contact_steps[name] <= 0:
            raise AssertionError(f"no MuJoCo contact observed for {name}")
        if drop_distances[name] <= 0.1:
            raise AssertionError(f"body did not fall under gravity: {name}")

    model_summary = manifest.get("model_summary", {})
    if int(model_summary.get("nflex", model.nflex)) != int(model.nflex):
        raise AssertionError("manifest nflex summary is stale")
    if int(model.nflex) != sum(1 for body in bodies if body.get("deformable")):
        raise AssertionError("deformable body/flex count mismatch")

    # Verify interaction with the source environment shell.  The first
    # selected source-native object is dropped into the real room bounds while
    # the other selected bodies are moved out of the probe.
    probe_body_name = str(next((body["name"] for body in bodies if not body.get("deformable", False)), bodies[0]["name"]))
    probe_body_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, probe_body_name))
    probe_joint_id = int(model.body_jntadr[probe_body_id])
    probe_qpos_start = int(model.jnt_qposadr[probe_joint_id])
    reset_data()
    for other_body in bodies:
        if other_body["name"] == probe_body_name:
            continue
        if bool(other_body.get("deformable", False)):
            move_body_or_cloth_out_of_probe(other_body, 100.0)
            continue
        other_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, other_body["name"]))
        other_qpos = int(model.jnt_qposadr[int(model.body_jntadr[other_id])])
        data.qpos[other_qpos : other_qpos + 3] = [100.0, 100.0, 10.0]
    data.qpos[probe_qpos_start : probe_qpos_start + 3] = [0.0, 0.0, 2.5]
    mujoco.mj_forward(model, data)
    environment_contact_step: int | None = None
    for step in range(1200):
        for contact_index in range(int(data.ncon)):
            contact = data.contact[contact_index]
            geom_bodies = {
                int(model.geom_bodyid[int(contact.geom1)]),
                int(model.geom_bodyid[int(contact.geom2)]),
            }
            if probe_body_id in geom_bodies and 0 in geom_bodies:
                environment_contact_step = step
                break
        if environment_contact_step is not None:
            break
        mujoco.mj_step(model, data)
    if environment_contact_step is None:
        raise AssertionError("selected source object never contacted the ReplicaCAD room shell")

    return {
        "status": "passed",
        "dataset": manifest["dataset"],
        "scene_id": manifest["scene_id"],
        "physics_authority": manifest["physics_authority"],
        "masses_kg": masses,
        "contact_steps": contact_steps,
        "drop_distances_m": drop_distances,
        "environment_contact": {
            "selected_body": probe_body_name,
            "environment_body": "replica_cad_room_shell",
            "first_contact_step": environment_contact_step,
        },
        "model_summary": manifest.get("model_summary", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata",
        type=Path,
        default=PROJECT_ROOT / "outputs/replica_cad/metadata/replica_cad_interaction.json",
    )
    args = parser.parse_args()
    result = verify(args.metadata)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
