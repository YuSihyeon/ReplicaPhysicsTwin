"""MuJoCo-only validation harness for the first falling-box MVP."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Sequence

import mujoco


def create_simulation_from_xml(xml_text: str) -> tuple[mujoco.MjModel, mujoco.MjData]:
    """Compile an MJCF string and allocate a fresh simulation state."""

    model = mujoco.MjModel.from_xml_string(xml_text)
    data = mujoco.MjData(model)
    return model, data


def load_simulation(xml_path: Path) -> tuple[mujoco.MjModel, mujoco.MjData]:
    return create_simulation_from_xml(xml_path.read_text(encoding="utf-8"))


def _body_id(model: mujoco.MjModel, body_name: str) -> int:
    body_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name))
    if body_id < 0:
        raise ValueError(f"Unknown body: {body_name}")
    return body_id


def _geom_id(model: mujoco.MjModel, geom_name: str) -> int:
    geom_id = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, geom_name))
    if geom_id < 0:
        raise ValueError(f"Unknown geom: {geom_name}")
    return geom_id


def _reset_to_initial(model: mujoco.MjModel, data: mujoco.MjData) -> None:
    if model.nkey > 0:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    else:
        data.qpos[:] = 0.0
        data.qpos[2] = 0.35
        data.qpos[3] = 1.0
        data.qvel[:] = 0.0
        data.act[:] = 0.0
        data.qacc[:] = 0.0
    mujoco.mj_forward(model, data)


def apply_impulse(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
    impulse_ns: Sequence[float],
) -> list[float]:
    """Apply a center-of-mass linear impulse to a free joint body."""

    if len(impulse_ns) != 3:
        raise ValueError("A linear impulse must have exactly three components")
    body_id = _body_id(model, body_name)
    joint_id = int(model.body_jntadr[body_id])
    if joint_id < 0 or int(model.jnt_type[joint_id]) != int(mujoco.mjtJoint.mjJNT_FREE):
        raise ValueError(f"Body is not attached to a free joint: {body_name}")
    dof_start = int(model.jnt_dofadr[joint_id])
    mass = float(model.body_mass[body_id])
    if mass <= 0.0:
        raise ValueError(f"Body mass must be positive: {body_name}")
    impulse = [float(value) for value in impulse_ns]
    for axis, value in enumerate(impulse):
        data.qvel[dof_start + axis] += value / mass
    return impulse


def _contact_records(model: mujoco.MjModel, data: mujoco.MjData) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []
    for index in range(int(data.ncon)):
        contact = data.contact[index]
        geom1 = int(contact.geom1)
        geom2 = int(contact.geom2)
        contacts.append(
            {
                "geom1": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom1) or str(geom1),
                "geom2": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom2) or str(geom2),
                "distance_m": float(contact.dist),
                "position_m": [float(value) for value in contact.pos],
                "normal": [float(value) for value in contact.frame[:3]],
            }
        )
    return contacts


def _capture_record(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
    step_index: int,
) -> dict[str, Any]:
    body_id = _body_id(model, body_name)
    joint_id = int(model.body_jntadr[body_id])
    dof_start = int(model.jnt_dofadr[joint_id])
    position = [float(value) for value in data.xpos[body_id]]
    quaternion = [float(value) for value in data.xquat[body_id]]
    linear_velocity = [float(data.qvel[dof_start + axis]) for axis in range(3)]
    angular_velocity = [float(data.qvel[dof_start + 3 + axis]) for axis in range(3)]
    finite_state = all(
        math.isfinite(value)
        for value in [*position, *quaternion, *linear_velocity, *angular_velocity]
    )
    return {
        "step": step_index,
        "sim_time": float(data.time),
        "position_m": position,
        "quaternion_wxyz": quaternion,
        "linear_velocity_mps": linear_velocity,
        "angular_velocity_rps": angular_velocity,
        "contact_count": int(data.ncon),
        "contacts": _contact_records(model, data),
        "finite_state": finite_state,
    }


def run_drop_scenario(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str = "test_box",
    box_geom_name: str = "test_box_geom",
    floor_geom_name: str = "floor",
    max_steps: int = 3000,
) -> dict[str, Any]:
    """Run a 30 cm center-height drop and return a JSON-serializable trace."""

    _reset_to_initial(model, data)
    box_geom_id = _geom_id(model, box_geom_name)
    floor_geom_id = _geom_id(model, floor_geom_name)
    box_half_height = float(model.geom_size[box_geom_id][2])
    floor_z = float(model.geom_pos[floor_geom_id][2])
    records = [_capture_record(model, data, body_name, 0)]
    for step_index in range(1, max_steps + 1):
        mujoco.mj_step(model, data)
        records.append(_capture_record(model, data, body_name, step_index))
    return {
        "body_name": body_name,
        "box_half_height_m": box_half_height,
        "floor_z_m": floor_z,
        "gravity_mps2": abs(float(model.opt.gravity[2])),
        "timestep_s": float(model.opt.timestep),
        "records": records,
    }


def validate_drop_result(result: dict[str, Any], settle_window_s: float = 0.5) -> dict[str, Any]:
    records = result["records"]
    if not records:
        raise ValueError("Drop result has no records")
    times = [float(record["sim_time"]) for record in records]
    positions_z = [float(record["position_m"][2]) for record in records]
    initial_z = positions_z[0]
    gravity = float(result["gravity_mps2"])
    timestep = float(result["timestep_s"])
    floor_z = float(result["floor_z_m"])
    half_height = float(result["box_half_height_m"])
    contact_indices = [index for index, record in enumerate(records) if record["contact_count"] > 0]
    first_contact_index = contact_indices[0] if contact_indices else None
    first_contact_time = times[first_contact_index] if first_contact_index is not None else None
    pre_contact_end = first_contact_index if first_contact_index is not None else len(records)
    freefall_errors = []
    for record in records[:pre_contact_end]:
        time = float(record["sim_time"])
        expected_z = initial_z - 0.5 * gravity * time * time
        freefall_errors.append(abs(float(record["position_m"][2]) - expected_z))
    max_freefall_error = max(freefall_errors, default=math.inf)
    final_time = times[-1]
    tail_records = [
        record for record in records if float(record["sim_time"]) >= final_time - settle_window_s
    ]
    tail_speeds = [
        math.sqrt(sum(float(value) ** 2 for value in record["linear_velocity_mps"]))
        for record in tail_records
    ]
    rest_z = floor_z + half_height
    tail_position_errors = [abs(float(record["position_m"][2]) - rest_z) for record in tail_records]
    min_z = min(positions_z)
    finite_state = all(bool(record["finite_state"]) for record in records)
    sim_time_monotonic = all(later > earlier for earlier, later in zip(times, times[1:]))
    gravity_drop = min_z < initial_z - 0.05 and any(
        float(record["linear_velocity_mps"][2]) < -0.01 for record in records[1:pre_contact_end]
    )
    floor_not_passed = min_z >= rest_z - 0.005
    stable_after_contact = bool(contact_indices) and max(tail_speeds, default=math.inf) <= 0.05 and max(
        tail_position_errors, default=math.inf
    ) <= 0.005
    freefall_match = bool(contact_indices) and max_freefall_error <= 0.005
    return {
        "passed": all(
            [
                gravity_drop,
                bool(contact_indices),
                floor_not_passed,
                stable_after_contact,
                freefall_match,
                sim_time_monotonic,
                finite_state,
            ]
        ),
        "gravity_drop": gravity_drop,
        "contact_count": len(contact_indices),
        "first_contact_step": records[first_contact_index]["step"] if first_contact_index is not None else None,
        "first_contact_time_s": first_contact_time,
        "floor_not_passed": floor_not_passed,
        "stable_after_contact": stable_after_contact,
        "freefall_match": freefall_match,
        "max_freefall_error_m": max_freefall_error,
        "sim_time_monotonic": sim_time_monotonic,
        "finite_state": finite_state,
        "initial_z_m": initial_z,
        "min_z_m": min_z,
        "rest_z_m": rest_z,
        "final_z_m": positions_z[-1],
        "tail_max_speed_mps": max(tail_speeds, default=math.inf),
        "tail_max_position_error_m": max(tail_position_errors, default=math.inf),
        "record_count": len(records),
        "sim_time_final_s": final_time,
        "timestep_s": timestep,
    }


def run_impulse_scenario(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
    impulse_ns: Sequence[float],
) -> dict[str, Any]:
    """Reset, apply a COM impulse, step once, and record the velocity change."""

    _reset_to_initial(model, data)
    before = _capture_record(model, data, body_name, 0)
    applied = apply_impulse(model, data, body_name, impulse_ns)
    mujoco.mj_step(model, data)
    after = _capture_record(model, data, body_name, 1)
    delta = [
        after["linear_velocity_mps"][axis] - before["linear_velocity_mps"][axis]
        for axis in range(3)
    ]
    body_id = _body_id(model, body_name)
    mass = float(model.body_mass[body_id])
    expected_delta = [
        applied[axis] / mass + float(model.opt.gravity[axis]) * float(model.opt.timestep)
        for axis in range(3)
    ]
    delta_error = [delta[axis] - expected_delta[axis] for axis in range(3)]
    direction_ok = all(abs(error) <= 1e-9 for error in delta_error)
    return {
        "body_name": body_name,
        "impulse_ns": applied,
        "before": before,
        "after": after,
        "velocity_after": after["linear_velocity_mps"],
        "velocity_delta_mps": delta,
        "expected_velocity_delta_mps": expected_delta,
        "velocity_delta_error_mps": delta_error,
        "direction_ok": direction_ok,
        "sim_time_monotonic": after["sim_time"] > before["sim_time"],
        "finite_state": before["finite_state"] and after["finite_state"],
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def run_validation(xml_path: Path, output_dir: Path, max_steps: int = 3000) -> dict[str, Any]:
    model, data = load_simulation(xml_path)
    drop = run_drop_scenario(model, data, max_steps=max_steps)
    drop_validation = validate_drop_result(drop)
    impulse = run_impulse_scenario(model, data, "test_box", [0.1, 0.0, 0.0])
    output_dir.mkdir(parents=True, exist_ok=True)
    drop_log = output_dir / "phase2_drop.jsonl"
    impulse_log = output_dir / "phase2_impulse.jsonl"
    _write_jsonl(drop_log, drop["records"])
    _write_jsonl(impulse_log, [impulse["before"], impulse["after"]])
    summary = {
        "schema_version": 1,
        "xml_path": str(xml_path.resolve()),
        "model": {
            "timestep_s": float(model.opt.timestep),
            "gravity_mps2": [float(value) for value in model.opt.gravity],
            "body_count": int(model.nbody),
            "geom_count": int(model.ngeom),
            "mass_kg": float(model.body_mass[_body_id(model, "test_box")]),
        },
        "drop": drop_validation,
        "impulse": {
            key: value
            for key, value in impulse.items()
            if key not in {"before", "after"}
        },
        "logs": {"drop": str(drop_log.resolve()), "impulse": str(impulse_log.resolve())},
    }
    summary["passed"] = bool(drop_validation["passed"] and impulse["direction_ok"] and impulse["finite_state"])
    (output_dir / "phase2_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-steps", type=int, default=3000)
    args = parser.parse_args()
    summary = run_validation(args.xml, args.output_dir, args.max_steps)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
