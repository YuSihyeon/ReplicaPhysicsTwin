"""Phase 6 tissue-box rigid-body specification and MuJoCo validation."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import mujoco

from .office0_collision import (
    _candidate_ids,
    _float_list,
    _make_proxy,
    _visual_bounds,
    read_semantic_instance_bounds,
)


TISSUE_BOX_OBJECT_ID = 28
TISSUE_BOX_LIFT_M = 0.30
TISSUE_BOX_MASS_KG = 0.25
TISSUE_BOX_FRICTION = [0.8, 0.1, 0.1]
TISSUE_BOX_RESTITUTION_ESTIMATE = 0.05
TISSUE_BOX_CONTACT_SOLREF = [0.02, 1.0]
TISSUE_BOX_CONTACT_SOLIMP = [0.9, 0.95, 0.001]


def _records(manifest: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    result: dict[int, Mapping[str, Any]] = {}
    for record in manifest.get("object_records", []):
        try:
            result[int(record["id"])] = record
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _normalized_bounds(
    source_bounds: Mapping[str, Any],
    translation_m: list[float],
) -> tuple[list[float], list[float]]:
    minimum = _float_list(source_bounds["min"])
    maximum = _float_list(source_bounds["max"])
    normalized_min = [minimum[index] + translation_m[index] for index in range(3)]
    normalized_max = [maximum[index] + translation_m[index] for index in range(3)]
    return normalized_min, normalized_max


def _horizontal_contains(proxy: Mapping[str, Any], x: float, y: float, tolerance: float = 0.02) -> bool:
    return (
        float(proxy["min_m"][0]) - tolerance <= x <= float(proxy["max_m"][0]) + tolerance
        and float(proxy["min_m"][1]) - tolerance <= y <= float(proxy["max_m"][1]) + tolerance
    )


def _select_support_proxy(tissue_proxy: Mapping[str, Any], fixed_proxies: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    x = float(tissue_proxy["center_m"][0])
    y = float(tissue_proxy["center_m"][1])
    tissue_bottom = float(tissue_proxy["min_m"][2])
    candidates = [
        proxy
        for proxy in fixed_proxies
        if proxy.get("role") in {"desk", "floor"}
        and _horizontal_contains(proxy, x, y)
        and float(proxy["max_m"][2]) <= tissue_bottom + 0.10
    ]
    if not candidates:
        floor = next((proxy for proxy in fixed_proxies if proxy.get("role") == "floor"), None)
        if floor is None:
            raise ValueError("A floor or desk support proxy is required for tissue_box")
        return floor
    return max(candidates, key=lambda proxy: float(proxy["max_m"][2]))


def _box_inertia_diagonal(mass_kg: float, size_m: list[float]) -> list[float]:
    sx, sy, sz = size_m
    return [
        mass_kg * (sy * sy + sz * sz) / 12.0,
        mass_kg * (sx * sx + sz * sz) / 12.0,
        mass_kg * (sx * sx + sy * sy) / 12.0,
    ]


def build_tissue_box_spec(
    base_collision_spec: Mapping[str, Any],
    manifest: Mapping[str, Any],
    visual_metadata: Mapping[str, Any],
    measured_bounds: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """Add the manifest-selected tissue_box body to the fixed collision spec."""

    object_ids = _candidate_ids(manifest, "tissue_box")
    if object_ids != [TISSUE_BOX_OBJECT_ID]:
        raise ValueError(
            f"office_0 tissue_box candidate must be [{TISSUE_BOX_OBJECT_ID}], got {object_ids}"
        )
    tissue_bounds = measured_bounds.get(TISSUE_BOX_OBJECT_ID)
    if tissue_bounds is None:
        raise ValueError(f"No semantic mesh bounds found for tissue_box object {TISSUE_BOX_OBJECT_ID}")

    blocking_roles = [
        item
        for item in base_collision_spec.get("unresolved_roles", [])
        if item.get("status") == "unresolved" and item.get("requires_user_input")
    ]
    if blocking_roles:
        raise ValueError(f"Fixed collision spec still has unresolved roles: {blocking_roles}")

    translation_m = _float_list(
        visual_metadata["coordinate_transform"]["translation_m"]
    )
    source_min, source_max = _float_list(tissue_bounds["min"]), _float_list(tissue_bounds["max"])
    normalized_min, normalized_max = _normalized_bounds(
        {"min": source_min, "max": source_max}, translation_m
    )
    source_size = [source_max[index] - source_min[index] for index in range(3)]
    source_class_name = str(_records(manifest)[TISSUE_BOX_OBJECT_ID].get("class_name", "unknown"))
    tissue_proxy = _make_proxy(
        name="tissue_box",
        role="tissue_box",
        source_object_ids=[TISSUE_BOX_OBJECT_ID],
        source_class_names=[source_class_name],
        minimum=source_min,
        maximum=source_max,
        translation_m=translation_m,
        confidence="medium",
        basis="semantic_mesh_face_vertices",
        face_counts=[int(tissue_bounds.get("face_count", 0))],
        requires_user_confirmation=True,
    )
    # Keep the local variables as an explicit sanity check: the proxy helper
    # must use the same translation as the visual mesh and the measured mesh.
    if tissue_proxy["min_m"] != normalized_min or tissue_proxy["max_m"] != normalized_max:
        raise AssertionError("tissue_box proxy normalization mismatch")

    support_proxy = _select_support_proxy(tissue_proxy, list(base_collision_spec["proxies"]))
    half_size = _float_list(tissue_proxy["half_size_m"])
    rest_position = [
        float(tissue_proxy["center_m"][0]),
        float(tissue_proxy["center_m"][1]),
        float(support_proxy["max_m"][2]) + half_size[2],
    ]
    # The scene starts with the object resting on its support.  The 30 cm lift
    # is an explicit command scenario, not the reset/start pose.
    initial_position = list(rest_position)
    inertia_diagonal = _box_inertia_diagonal(TISSUE_BOX_MASS_KG, _float_list(tissue_proxy["size_m"]))
    volume_m3 = math.prod(source_size)
    visual_min, visual_max = _visual_bounds(visual_metadata)
    initial_bounds_min = [initial_position[index] - half_size[index] for index in range(3)]
    initial_bounds_max = [initial_position[index] + half_size[index] for index in range(3)]
    alignment_tolerance = 0.05
    initial_alignment_passed = not any(
        initial_bounds_min[index] < visual_min[index] - alignment_tolerance
        or initial_bounds_max[index] > visual_max[index] + alignment_tolerance
        for index in range(3)
    )
    if not initial_alignment_passed:
        raise ValueError("tissue_box initial body is outside the visual room bounds")

    dynamic_body = {
        "name": "tissue_box",
        "role": "tissue_box",
        "source_object_id": TISSUE_BOX_OBJECT_ID,
        "initial_position_m": initial_position,
        "rest_position_m": rest_position,
        "half_size_m": half_size,
        "mass_kg": TISSUE_BOX_MASS_KG,
        "friction": list(TISSUE_BOX_FRICTION),
        "support_proxy": support_proxy["name"],
        "inertia_diagonal_kg_m2": inertia_diagonal,
    }
    spec = dict(base_collision_spec)
    spec["schema_version"] = 1
    spec["phase"] = 6
    spec["proxies"] = [dict(proxy) for proxy in base_collision_spec["proxies"]]
    spec["test_bodies"] = []
    spec["dynamic_bodies"] = [dynamic_body]
    spec["tissue_box"] = {
        "object_id": TISSUE_BOX_OBJECT_ID,
        "class_name": source_class_name,
        "source_bounds_m": {"min": source_min, "max": source_max},
        "source_size_m": source_size,
        "source_face_count": int(tissue_bounds.get("face_count", 0)),
        "semantic_center_m": _float_list(tissue_proxy["center_m"]),
        "normalized_visual_size_cm": [value * 100.0 for value in _float_list(tissue_proxy["size_m"])],
        "support_proxy": support_proxy["name"],
        "rest_position_m": rest_position,
        "initial_position_m": initial_position,
        "lift_height_m": TISSUE_BOX_LIFT_M,
        "initial_alignment_check": {
            "passed": initial_alignment_passed,
            "tolerance_m": alignment_tolerance,
            "visual_bounds_m": {"min": visual_min, "max": visual_max},
            "initial_bounds_m": {"min": initial_bounds_min, "max": initial_bounds_max},
        },
    }
    spec["physics_parameters"] = {
        "mass_kg": TISSUE_BOX_MASS_KG,
        "mass_source": "MVP estimate; Replica office_0 provides geometry but no mass metadata",
        "size_source": "semantic mesh object_id 28 measured face vertices",
        "inertia_diagonal_kg_m2": inertia_diagonal,
        "inertia_source": "uniform-density box inertia computed from measured size and estimated mass",
        "volume_m3": volume_m3,
        "density_kg_m3_estimate": TISSUE_BOX_MASS_KG / volume_m3 if volume_m3 > 0.0 else None,
        "friction": list(TISSUE_BOX_FRICTION),
        "friction_source": "MVP contact estimate shared with fixed collision proxies",
        "restitution_estimate": TISSUE_BOX_RESTITUTION_ESTIMATE,
        "restitution_source": "MVP estimate; MuJoCo uses solref/solimp contact parameters rather than a direct restitution field",
        "contact_solref": list(TISSUE_BOX_CONTACT_SOLREF),
        "contact_solimp": list(TISSUE_BOX_CONTACT_SOLIMP),
    }
    spec["command_policy"] = {
        "object_id": "tissue_box",
        "lift_drop_command": "lift_drop",
        "lift_height_m": TISSUE_BOX_LIFT_M,
        "authority": "MuJoCo",
    }
    return spec


def run_tissue_box_lift_drop_validation(
    xml_path: Path,
    spec: Mapping[str, Any],
    output_dir: Path,
    *,
    max_steps: int = 3000,
) -> dict[str, Any]:
    """Run the configured 30 cm lift/drop and verify desk contact and rest."""

    xml_path = Path(xml_path).resolve()
    model = mujoco.MjModel.from_xml_path(str(xml_path))
    data = mujoco.MjData(model)
    if model.nkey > 0:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)

    body_spec = spec["dynamic_bodies"][0]
    body_name = str(body_spec["name"])
    body_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name))
    if body_id < 0:
        raise ValueError(f"Unknown tissue box body: {body_name}")
    joint_id = int(model.body_jntadr[body_id])
    dof_start = int(model.jnt_dofadr[joint_id])
    qpos_start = int(model.jnt_qposadr[joint_id])
    lift_height = float(spec["tissue_box"]["lift_height_m"])
    data.qpos[qpos_start + 2] += lift_height
    data.qvel[dof_start : dof_start + 6] = 0.0
    mujoco.mj_forward(model, data)
    support_name = str(body_spec["support_proxy"])
    support_proxy = next(proxy for proxy in spec["proxies"] if proxy["name"] == support_name)
    rest_z = float(body_spec["rest_position_m"][2])
    initial_z = float(data.xpos[body_id][2])
    lift_height_error = abs((initial_z - rest_z) - lift_height)
    initial_clearance = initial_z - float(body_spec["half_size_m"][2]) - float(support_proxy["max_m"][2])

    records: list[dict[str, Any]] = []
    contact_names: set[str] = set()
    first_contact_step: int | None = None
    for step in range(max_steps + 1):
        if step > 0:
            mujoco.mj_step(model, data)
        current_contacts: list[str] = []
        for contact_index in range(int(data.ncon)):
            contact = data.contact[contact_index]
            geom_ids = (int(contact.geom1), int(contact.geom2))
            if not any(int(model.geom_bodyid[geom_id]) == body_id for geom_id in geom_ids):
                continue
            for geom_id in geom_ids:
                if int(model.geom_bodyid[geom_id]) == body_id:
                    continue
                name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
                if name is not None:
                    current_contacts.append(name)
                    contact_names.add(name)
        if current_contacts and first_contact_step is None:
            first_contact_step = step
        records.append(
            {
                "step": step,
                "sim_time": float(data.time),
                "position_m": [float(value) for value in data.xpos[body_id]],
                "quaternion_wxyz": [float(value) for value in data.xquat[body_id]],
                "linear_velocity_mps": [float(data.qvel[dof_start + axis]) for axis in range(3)],
                "angular_velocity_rps": [float(data.qvel[dof_start + 3 + axis]) for axis in range(3)],
                "contacts": sorted(set(current_contacts)),
            }
        )

    final_position = [float(value) for value in data.xpos[body_id]]
    final_speed = math.sqrt(sum(float(data.qvel[dof_start + axis]) ** 2 for axis in range(3)))
    final_position_error = abs(final_position[2] - rest_z)
    finite_state = all(
        math.isfinite(value)
        for value in [
            *final_position,
            *[float(value) for value in data.xquat[body_id]],
            *[float(data.qvel[dof_start + axis]) for axis in range(6)],
        ]
    )
    passed = bool(
        lift_height_error <= 1.0e-6
        and initial_clearance > 0.01
        and first_contact_step is not None
        and support_name in contact_names
        and final_speed <= 0.05
        and final_position_error <= 0.02
        and finite_state
    )
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path = output_dir / "phase6_tissue_box_lift_drop.jsonl"
    trace_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
        newline="\n",
    )
    summary = {
        "schema_version": 1,
        "phase": 6,
        "xml_path": str(xml_path),
        "object_id": body_name,
        "source_object_id": int(body_spec["source_object_id"]),
        "support_proxy": support_name,
        "lift_height_m": float(spec["tissue_box"]["lift_height_m"]),
        "lift_height_error_m": lift_height_error,
        "initial_clearance_m": initial_clearance,
        "first_contact_step": first_contact_step,
        "contact_geom_names": sorted(contact_names),
        "final_position_m": final_position,
        "rest_z_m": rest_z,
        "final_position_error_m": final_position_error,
        "final_speed_mps": final_speed,
        "finite_state": finite_state,
        "record_count": len(records),
        "trace_path": str(trace_path),
        "passed": passed,
    }
    (output_dir / "phase6_tissue_box_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return summary


def build_tissue_box_artifact(
    scene_dir: Path,
    manifest_path: Path,
    visual_metadata_path: Path,
    collision_metadata_path: Path,
    output_xml: Path,
    output_metadata: Path,
) -> dict[str, Any]:
    """Read Phase 5 artifacts, add tissue_box, and write the Phase 6 MJCF."""

    scene_dir = Path(scene_dir).resolve()
    manifest_path = Path(manifest_path).resolve()
    visual_metadata_path = Path(visual_metadata_path).resolve()
    collision_metadata_path = Path(collision_metadata_path).resolve()
    output_xml = Path(output_xml).resolve()
    output_metadata = Path(output_metadata).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    visual_metadata = json.loads(visual_metadata_path.read_text(encoding="utf-8"))
    base_spec = json.loads(collision_metadata_path.read_text(encoding="utf-8"))
    semantic_mesh_path = scene_dir / "habitat" / "mesh_semantic.ply"
    measured_bounds = read_semantic_instance_bounds(semantic_mesh_path, {TISSUE_BOX_OBJECT_ID})
    spec = build_tissue_box_spec(base_spec, manifest, visual_metadata, measured_bounds)
    spec["source"] = {
        "scene_dir": str(scene_dir),
        "semantic_mesh": str(semantic_mesh_path),
        "manifest": str(manifest_path),
        "collision_metadata": str(collision_metadata_path),
        "visual_transform_metadata": str(visual_metadata_path),
        "source_data_modified": False,
    }
    output_xml.parent.mkdir(parents=True, exist_ok=True)
    output_metadata.parent.mkdir(parents=True, exist_ok=True)
    from .office0_collision import render_collision_mjcf

    output_xml.write_text(render_collision_mjcf(spec), encoding="utf-8", newline="\n")
    output_metadata.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return spec
