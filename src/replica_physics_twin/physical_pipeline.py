"""Deterministic end-to-end checks for the MuJoCo physical-object pipeline."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Mapping

import mujoco

from .bridge_server import MuJoCoBridgeServer
from .physical_scene import render_interaction_mjcf
from .physics_validation import load_simulation


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _body_id(model: mujoco.MjModel, name: str) -> int:
    body_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name))
    if body_id < 0:
        raise ValueError(f"Unknown MuJoCo body: {name}")
    return body_id


def _geom_id(model: mujoco.MjModel, name: str) -> int:
    geom_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name))
    if geom_id < 0:
        raise ValueError(f"Unknown MuJoCo geom: {name}")
    return geom_id


def _reset(model: mujoco.MjModel, data: mujoco.MjData) -> None:
    if model.nkey > 0:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    else:
        mujoco.mj_resetData(model, data)
    mujoco.mj_forward(model, data)


def _contact_pairs(model: mujoco.MjModel, data: mujoco.MjData, body_id: int) -> list[dict[str, Any]]:
    body_geom_ids = {
        geom_id
        for geom_id in range(int(model.ngeom))
        if int(model.geom_bodyid[geom_id]) == body_id
    }
    pairs: list[dict[str, Any]] = []
    for index in range(int(data.ncon)):
        contact = data.contact[index]
        geom1 = int(contact.geom1)
        geom2 = int(contact.geom2)
        if geom1 not in body_geom_ids and geom2 not in body_geom_ids:
            continue
        other_geom = geom2 if geom1 in body_geom_ids else geom1
        pairs.append(
            {
                "body_geom": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom1 if geom1 in body_geom_ids else geom2)
                or str(geom1 if geom1 in body_geom_ids else geom2),
                "other_geom": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, other_geom) or str(other_geom),
                "distance_m": float(contact.dist),
            }
        )
    return pairs


def _run_isolated_drop(
    interaction_metadata: Mapping[str, Any],
    *,
    body_name: str,
    lift_height_m: float = 0.30,
    max_steps: int = 3000,
) -> dict[str, Any]:
    dynamic_bodies = [
        dict(body)
        for body in interaction_metadata.get("dynamic_bodies", [])
        if str(body.get("name")) == body_name
    ]
    if len(dynamic_bodies) != 1:
        raise ValueError(f"Could not isolate dynamic body {body_name}")
    isolated_spec = copy.deepcopy(dict(interaction_metadata))
    isolated_spec["dynamic_bodies"] = dynamic_bodies
    isolated_spec["dynamic_object_ids"] = [dynamic_bodies[0]["source_object_id"]]
    model = mujoco.MjModel.from_xml_string(render_interaction_mjcf(isolated_spec))
    data = mujoco.MjData(model)
    _reset(model, data)
    body_id = _body_id(model, body_name)
    joint_id = int(model.body_jntadr[body_id])
    qpos_start = int(model.jnt_qposadr[joint_id])
    dof_start = int(model.jnt_dofadr[joint_id])
    geom_id = _geom_id(model, f"{body_name}_geom")
    support_name = str(dynamic_bodies[0].get("support_proxy") or "")
    initial_position = [float(value) for value in data.xpos[body_id]]
    data.qpos[qpos_start + 2] += lift_height_m
    data.qvel[dof_start : dof_start + 6] = 0.0
    mujoco.mj_forward(model, data)
    lifted_position = [float(value) for value in data.xpos[body_id]]

    first_contact_step: int | None = None
    first_contact_pairs: list[dict[str, Any]] = []
    minimum_distance = math.inf
    minimum_z = lifted_position[2]
    tail: list[dict[str, float]] = []
    tail_contact_distances: list[float] = []
    tail_has_support_contact = False
    for step in range(1, max_steps + 1):
        mujoco.mj_step(model, data)
        pairs = _contact_pairs(model, data, body_id)
        if first_contact_step is None and pairs:
            first_contact_step = step
            first_contact_pairs = pairs
        minimum_distance = min(minimum_distance, *(pair["distance_m"] for pair in pairs)) if pairs else minimum_distance
        minimum_z = min(minimum_z, float(data.xpos[body_id][2]))
        if step > max_steps - 250:
            tail.append(
                {
                    "speed_mps": float(np_norm(data.qvel[dof_start : dof_start + 3])),
                    "z_m": float(data.xpos[body_id][2]),
                }
            )
            tail_contact_distances.extend(float(pair["distance_m"]) for pair in pairs)
            tail_has_support_contact = tail_has_support_contact or any(
                support_name and support_name in {pair["other_geom"], pair["body_geom"]}
                for pair in pairs
            )

    support_geom_id = _geom_id(model, support_name) if support_name else -1
    support_top_z = None
    if support_geom_id >= 0:
        support_top_z = float(model.geom_pos[support_geom_id][2] + model.geom_size[support_geom_id][2])
    final_position = [float(value) for value in data.xpos[body_id]]
    final_contact_pairs = _contact_pairs(model, data, body_id)
    final_has_support_contact = any(
        support_name and support_name in {pair["other_geom"], pair["body_geom"]}
        for pair in final_contact_pairs
    )
    is_mesh = int(model.geom_type[geom_id]) == int(mujoco.mjtGeom.mjGEOM_MESH)
    # A free mesh is allowed to rotate or topple during the drop.  Its body
    # centre therefore cannot be compared with a fixed upright-box Z value.
    # Keep the upright reference for box fixtures, but validate mesh bodies by
    # actual support contact, penetration and settled velocity instead.
    expected_rest_z = (
        support_top_z + float(model.geom_size[geom_id][2])
        if support_top_z is not None and not is_mesh
        else None
    )
    has_declared_support_contact = any(
        support_name and support_name in {pair["other_geom"], pair["body_geom"]}
        for pair in first_contact_pairs
    )
    tail_max_speed = max((item["speed_mps"] for item in tail), default=math.inf)
    tail_z_error = (
        max((abs(item["z_m"] - expected_rest_z) for item in tail), default=math.inf)
        if expected_rest_z is not None
        else None
    )
    tail_minimum_contact_distance = min(tail_contact_distances, default=None)
    rest_criterion = "support-contact-and-low-speed" if is_mesh else "upright-box-z-and-low-speed"
    if is_mesh:
        rest_passed = bool(
            tail_has_support_contact
            and final_has_support_contact
            and tail_max_speed <= 0.05
            and (tail_minimum_contact_distance is None or tail_minimum_contact_distance >= -0.01)
        )
    else:
        rest_passed = bool(
            expected_rest_z is not None
            and tail_max_speed <= 0.05
            and tail_z_error is not None
            and tail_z_error <= 0.01
            and minimum_distance >= -0.01
        )
    result = {
        "body_name": body_name,
        "support_proxy": support_name,
        "collision_shape": "mesh" if is_mesh else "box",
        "rest_criterion": rest_criterion,
        "initial_position_m": initial_position,
        "lifted_position_m": lifted_position,
        "final_position_m": final_position,
        "lift_height_m": lift_height_m,
        "first_contact_step": first_contact_step,
        "first_contact_time_s": None if first_contact_step is None else first_contact_step * float(model.opt.timestep),
        "first_contact_pairs": first_contact_pairs,
        "final_contact_pairs": final_contact_pairs,
        "minimum_z_m": minimum_z,
        "minimum_contact_distance_m": None if minimum_distance is math.inf else minimum_distance,
        "expected_rest_z_m": expected_rest_z,
        "tail_max_speed_mps": tail_max_speed,
        "tail_max_z_error_m": tail_z_error,
        "tail_minimum_contact_distance_m": tail_minimum_contact_distance,
        "tail_has_declared_support_contact": tail_has_support_contact,
        "final_has_declared_support_contact": final_has_support_contact,
    }
    result["passed"] = bool(
        first_contact_step is not None
        and has_declared_support_contact
        and minimum_z < lifted_position[2] - 0.05
        and rest_passed
    )
    return result


def np_norm(values: Any) -> float:
    """Small local norm helper that keeps this validation module NumPy-free."""

    return math.sqrt(sum(float(value) ** 2 for value in values))


def _run_group_grab(
    xml_path: Path,
    physical_manifest_path: Path,
    *,
    object_ids: list[str],
    delta_x_m: float = 0.20,
) -> dict[str, Any]:
    server = MuJoCoBridgeServer(xml_path, physical_manifest_path=physical_manifest_path)
    server._model, server._data = load_simulation(xml_path)  # noqa: SLF001 - deterministic in-process validation
    server._load_physical_manifest()  # noqa: SLF001
    server._reset_simulation()  # noqa: SLF001
    assert server._model is not None and server._data is not None  # noqa: S101
    before = {
        object_id: [
            float(value)
            for value in server._data.xpos[_body_id(server._model, object_id)]
        ]
        for object_id in object_ids
    }
    anchor = before[object_ids[0]]
    begin = {
        "client_grab_id": "validation-grab",
        "object_ids": object_ids,
        "anchor_m": anchor,
    }
    server._grab_begin(begin)  # noqa: SLF001
    server._grab_update(  # noqa: SLF001
        {
            "grab_id": "validation-grab",
            "target_position_m": [anchor[0] + delta_x_m, anchor[1], anchor[2]],
            "target_quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        }
    )
    for _ in range(250):
        server._step_once()  # noqa: SLF001
    after = {
        object_id: [
            float(value)
            for value in server._data.xpos[_body_id(server._model, object_id)]
        ]
        for object_id in object_ids
    }
    server._grab_end({"grab_id": "validation-grab"})  # noqa: SLF001
    movement = {
        object_id: math.sqrt(sum((after[object_id][axis] - before[object_id][axis]) ** 2 for axis in range(3)))
        for object_id in object_ids
    }
    state_objects = server._state_objects()  # noqa: SLF001
    state_by_id = {str(item["id"]): item for item in state_objects}
    return {
        "passed": all(value > 0.03 for value in movement.values()),
        "object_ids": object_ids,
        "movement_m": movement,
        "state_objects_have_contacts": all(isinstance(state_by_id[item]["contacts"], list) for item in object_ids),
        "state_objects_have_properties": all("properties" in state_by_id[item] for item in object_ids),
    }


def _property_provenance(physical_manifest: Mapping[str, Any]) -> dict[str, Any]:
    dynamic = [item for item in physical_manifest.get("objects", []) if item.get("movable")]
    required_fields = {"size_m", "mass_kg", "inertia_diagonal_kg_m2", "friction", "restitution"}
    complete = all(required_fields.issubset(item) for item in dynamic)
    sources: dict[str, set[str]] = {}
    needs_measurement = False
    for item in dynamic:
        for field, info in item.get("provenance", {}).items():
            if isinstance(info, Mapping):
                source = str(info.get("source", "unknown"))
                sources.setdefault(field, set()).add(source)
                needs_measurement = needs_measurement or source in {"mvp_estimate", "material_prior", "user_override"}
    return {
        "passed": bool(dynamic) and complete,
        "dynamic_object_count": len(dynamic),
        "required_fields_present": complete,
        "sources": {field: sorted(values) for field, values in sources.items()},
        "status": "NEEDS_MEASUREMENT" if needs_measurement else "MEASURED",
    }


def _scene_alignment(interaction_metadata: Mapping[str, Any]) -> dict[str, Any]:
    proxy_by_name = {str(item.get("name")): item for item in interaction_metadata.get("proxies", [])}
    checks: list[dict[str, Any]] = []
    for body in interaction_metadata.get("dynamic_bodies", []):
        support_name = str(body.get("support_proxy") or "")
        support = proxy_by_name.get(support_name)
        if support is None:
            checks.append({"body": body.get("name"), "passed": False, "reason": "missing support proxy"})
            continue
        bottom_z = float(body["initial_position_m"][2]) - float(body["half_size_m"][2])
        top_z = float(support["max_m"][2])
        checks.append(
            {
                "body": body.get("name"),
                "support": support_name,
                "bottom_z_m": bottom_z,
                "support_top_z_m": top_z,
                "error_m": abs(bottom_z - top_z),
                "passed": abs(bottom_z - top_z) <= 0.01,
            }
        )
    return {"passed": bool(checks) and all(item["passed"] for item in checks), "checks": checks}


def run_physical_pipeline_verification(project_root: Path) -> dict[str, Any]:
    """Run deterministic physical checks against one ReplicaPhysicsTwin project."""

    root = Path(project_root)
    xml_path = root / "outputs/mjcf/office0_interaction.xml"
    interaction_path = root / "outputs/metadata/office0_interaction.json"
    physical_manifest_path = root / "outputs/metadata/office0_physical_manifest.json"
    interaction_metadata = _read_json(interaction_path)
    physical_manifest = _read_json(physical_manifest_path)
    model, _ = load_simulation(xml_path)
    dynamic_bodies = [str(item["name"]) for item in interaction_metadata.get("dynamic_bodies", [])]
    tissue_name = next((name for name in dynamic_bodies if name == "tissue_box"), dynamic_bodies[0] if dynamic_bodies else "")
    if not tissue_name:
        raise ValueError("Interaction scene has no dynamic bodies")

    property_provenance = _property_provenance(physical_manifest)
    scene_alignment = _scene_alignment(interaction_metadata)
    contact_response = _run_isolated_drop(interaction_metadata, body_name=tissue_name)
    first_drop_final = contact_response["final_position_m"]
    repeat_drop = _run_isolated_drop(interaction_metadata, body_name=tissue_name)
    reset_reproducibility = {
        "passed": max(
            abs(first_drop_final[index] - repeat_drop["final_position_m"][index]) for index in range(3)
        ) <= 1e-6,
        "max_final_position_delta_m": max(
            abs(first_drop_final[index] - repeat_drop["final_position_m"][index]) for index in range(3)
        ),
    }
    group_ids = [
        name
        for name in ("tissue_box", "desk_organizer", "chair_4")
        if name in dynamic_bodies
    ]
    group_grab = _run_group_grab(xml_path, physical_manifest_path, object_ids=group_ids) if len(group_ids) >= 2 else {
        "passed": False,
        "reason": "requires two dynamic bodies",
    }
    compiled_scene = {
        "passed": model.nbody >= 1 + len(dynamic_bodies) and model.ngeom >= len(interaction_metadata.get("proxies", [])) + len(dynamic_bodies),
        "nbody": int(model.nbody),
        "ngeom": int(model.ngeom),
        "njnt": int(model.njnt),
        "nmocap": int(model.nmocap),
        "neq": int(model.neq),
    }
    bridge_mapping = {
        "passed": bool(group_grab.get("state_objects_have_contacts")) and bool(group_grab.get("state_objects_have_properties")),
        "physics_authority": physical_manifest.get("physics_authority"),
        "scene_id": physical_manifest.get("scene_id"),
        "group_grab": group_grab,
    }
    automated_checks = [
        property_provenance["passed"],
        scene_alignment["passed"],
        compiled_scene["passed"],
        contact_response["passed"],
        reset_reproducibility["passed"],
        bridge_mapping["passed"],
    ]
    return {
        "schema_version": 1,
        "project_root": str(root.resolve()),
        "physics_authority": "MuJoCo",
        "automated_passed": all(automated_checks),
        "property_provenance": property_provenance,
        "scene_alignment": scene_alignment,
        "compiled_scene": compiled_scene,
        "contact_response": contact_response,
        "reset_reproducibility": reset_reproducibility,
        "bridge_mapping": bridge_mapping,
        "unreal_evidence": {
            "status": "NEEDS_USER_VERIFICATION",
            "reason": "Unreal Play screen and log require a live editor check after the Development build.",
        },
    }
