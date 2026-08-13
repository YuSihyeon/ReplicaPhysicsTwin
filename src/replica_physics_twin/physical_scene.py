"""Build a MuJoCo scene in which selected and environment objects are dynamic."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any
from xml.sax.saxutils import escape


def _float_list(values: Any, field: str, length: int = 3) -> list[float]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or len(values) != length:
        raise ValueError(f"{field} must contain {length} values")
    result = [float(value) for value in values]
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{field} must be finite")
    return result


def _fmt(values: Sequence[float]) -> str:
    return " ".join(f"{float(value):.9g}" for value in values)


def _proxy_half_size(proxy: Mapping[str, Any]) -> list[float]:
    if "half_size_m" in proxy:
        return _float_list(proxy["half_size_m"], f"{proxy.get('name', 'proxy')}.half_size_m")
    return [value / 2.0 for value in _float_list(proxy["size_m"], f"{proxy.get('name', 'proxy')}.size_m")]


def _proxy_center(proxy: Mapping[str, Any]) -> list[float]:
    if "center_m" in proxy:
        return _float_list(proxy["center_m"], f"{proxy.get('name', 'proxy')}.center_m")
    minimum = _float_list(proxy["min_m"], f"{proxy.get('name', 'proxy')}.min_m")
    half = _proxy_half_size(proxy)
    return [minimum[index] + half[index] for index in range(3)]


def _proxy_max_z(proxy: Mapping[str, Any]) -> float:
    if "max_m" in proxy:
        return _float_list(proxy["max_m"], f"{proxy.get('name', 'proxy')}.max_m")[2]
    center = _proxy_center(proxy)
    return center[2] + _proxy_half_size(proxy)[2]


def _xy_overlaps(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    """Return whether two body AABBs overlap in the horizontal plane."""

    first_position = _float_list(first["initial_position_m"], f"{first['name']}.initial_position_m")
    second_position = _float_list(second["initial_position_m"], f"{second['name']}.initial_position_m")
    first_half = _float_list(first["half_size_m"], f"{first['name']}.half_size_m")
    second_half = _float_list(second["half_size_m"], f"{second['name']}.half_size_m")
    return all(
        abs(first_position[axis] - second_position[axis])
        < first_half[axis] + second_half[axis]
        for axis in (0, 1)
    )


def _separate_dynamic_bodies(
    dynamic_bodies: list[dict[str, Any]],
    proxies: Sequence[Mapping[str, Any]],
    *,
    clearance_m: float = 0.025,
) -> None:
    """Resolve overlapping initial placements without changing the physics authority.

    Semantic bounds are retained in ``source_bounds_m``.  Only the initial pose
    is adjusted when two selected bodies start interpenetrating on the same
    support surface.  The adjustment is recorded so the UI and later calibration
    can distinguish source pose from a valid simulation start pose.
    """

    proxy_by_name = {str(proxy.get("name")): proxy for proxy in proxies}
    for body_index, body in enumerate(dynamic_bodies):
        support_name = body.get("support_proxy")
        body.setdefault("placement_adjustment_m", [0.0, 0.0, 0.0])
        if support_name is None:
            continue
        support = proxy_by_name.get(str(support_name))
        if support is None:
            continue
        support_center = _proxy_center(support)
        support_half = _proxy_half_size(support)

        for previous in dynamic_bodies[:body_index]:
            if previous.get("support_proxy") != support_name or not _xy_overlaps(previous, body):
                continue
            previous_position = _float_list(previous["initial_position_m"], f"{previous['name']}.initial_position_m")
            previous_half = _float_list(previous["half_size_m"], f"{previous['name']}.half_size_m")
            body_position = _float_list(body["initial_position_m"], f"{body['name']}.initial_position_m")
            body_half = _float_list(body["half_size_m"], f"{body['name']}.half_size_m")

            # Prefer moving the later-selected object along Y.  This preserves
            # the source X placement and keeps desk objects visually separated.
            positive_y = previous_position[1] + previous_half[1] + body_half[1] + clearance_m
            negative_y = previous_position[1] - previous_half[1] - body_half[1] - clearance_m
            support_min_y = support_center[1] - support_half[1] + body_half[1] + clearance_m
            support_max_y = support_center[1] + support_half[1] - body_half[1] - clearance_m
            if positive_y <= support_max_y:
                body_position[1] = max(body_position[1], positive_y)
            elif negative_y >= support_min_y:
                body_position[1] = min(body_position[1], negative_y)
            else:
                # A narrow support may not have room along Y.  Fall back to X
                # before allowing an invalid interpenetrating initial state.
                positive_x = previous_position[0] + previous_half[0] + body_half[0] + clearance_m
                negative_x = previous_position[0] - previous_half[0] - body_half[0] - clearance_m
                support_min_x = support_center[0] - support_half[0] + body_half[0] + clearance_m
                support_max_x = support_center[0] + support_half[0] - body_half[0] - clearance_m
                if positive_x <= support_max_x:
                    body_position[0] = max(body_position[0], positive_x)
                elif negative_x >= support_min_x:
                    body_position[0] = min(body_position[0], negative_x)
                else:
                    raise ValueError(
                        f"Cannot place {body['name']} without overlap on support {support_name}"
                    )

            adjustment = body["placement_adjustment_m"]
            for axis in range(3):
                adjustment[axis] = float(adjustment[axis]) + body_position[axis] - float(body["initial_position_m"][axis])
            body["initial_position_m"] = body_position


def _normalise_name(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return result or "object"


def _unique_body_name(class_name: str, object_id: int, used: set[str]) -> str:
    base = _normalise_name(class_name)
    if base in {"tissue_paper", "tissue"}:
        base = "tissue_box"
    if base in {"chair", "sofa", "bin"}:
        base = f"{base}_{object_id}"
    if base in used:
        base = f"{base}_{object_id}"
    used.add(base)
    return base


def _object_by_id(physical_manifest: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    result: dict[int, Mapping[str, Any]] = {}
    for record in physical_manifest.get("objects", []):
        if not isinstance(record, Mapping):
            continue
        try:
            result[int(record["object_id"])] = record
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _bounds_from_measured(
    measured: Mapping[str, Any],
    translation_m: Sequence[float],
) -> tuple[list[float], list[float]]:
    source_min = _float_list(measured["min"], "measured.min")
    source_max = _float_list(measured["max"], "measured.max")
    translation = _float_list(translation_m, "translation_m")
    minimum = [source_min[index] + translation[index] for index in range(3)]
    maximum = [source_max[index] + translation[index] for index in range(3)]
    if any(maximum[index] <= minimum[index] for index in range(3)):
        raise ValueError("dynamic object bounds must have positive size")
    return minimum, maximum


def _support_name(
    physical: Mapping[str, Any],
    proxies: Sequence[Mapping[str, Any]],
) -> str | None:
    explicit = physical.get("support_proxy")
    names = {str(proxy.get("name")) for proxy in proxies}
    if explicit is not None and str(explicit) in names:
        return str(explicit)
    role = str(physical.get("role", ""))
    class_name = str(physical.get("class_name", "")).lower()
    if (
        role in {"tissue_box", "dynamic_object", "desk_organizer"}
        or "desk-organizer" in class_name
        or "desk organizer" in class_name
    ) and "desk_58" in names:
        return "desk_58"
    if "floor" in names:
        return "floor"
    return None


def build_interaction_scene_spec(
    collision_spec: Mapping[str, Any],
    physical_manifest: Mapping[str, Any],
    visual_metadata: Mapping[str, Any],
    measured_bounds: Mapping[int, Mapping[str, Any]],
    *,
    dynamic_object_ids: Sequence[int] | None = None,
    dynamic_mesh_assets: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Combine static collision proxies with multiple MuJoCo freejoint bodies."""

    proxies = [dict(proxy) for proxy in collision_spec.get("proxies", [])]
    translation = _float_list(visual_metadata.get("coordinate_transform", {}).get("translation_m", [0, 0, 0]), "translation_m")
    records = _object_by_id(physical_manifest)
    requested_ids = (
        [int(object_id) for object_id in dynamic_object_ids]
        if dynamic_object_ids is not None
        else [int(object_id) for object_id in physical_manifest.get("dynamic_object_ids", [])]
    )
    used_names: set[str] = set()
    dynamic_bodies: list[dict[str, Any]] = []
    for object_id in requested_ids:
        physical = records.get(object_id)
        if physical is None:
            raise ValueError(f"No physical properties for dynamic object {object_id}")
        if str(physical.get("body_type")) != "dynamic" or not bool(physical.get("movable")):
            raise ValueError(f"Object {object_id} is not marked as a dynamic movable body")
        measured = measured_bounds.get(object_id)
        if measured is None:
            raise ValueError(f"No measured semantic bounds for dynamic object {object_id}")
        minimum, maximum = _bounds_from_measured(measured, translation)
        size = [maximum[index] - minimum[index] for index in range(3)]
        half_size = [value / 2.0 for value in size]
        center = [(minimum[index] + maximum[index]) / 2.0 for index in range(3)]
        support_name = _support_name(physical, proxies)
        if support_name is not None:
            support = next(proxy for proxy in proxies if str(proxy.get("name")) == support_name)
            center[2] = _proxy_max_z(support) + half_size[2]
        body_name = _unique_body_name(str(physical.get("class_name", "object")), object_id, used_names)
        mass = float(physical.get("mass_kg", 0.0))
        inertia = _float_list(physical.get("inertia_diagonal_kg_m2"), "inertia_diagonal_kg_m2")
        if mass <= 0.0 or any(value <= 0.0 for value in inertia):
            raise ValueError(f"Dynamic object {object_id} must have positive mass and inertia")
        friction_map = physical.get("friction", {})
        friction = [
            float(friction_map.get("sliding", 0.0)),
            float(friction_map.get("torsional", 0.0)),
            float(friction_map.get("rolling", 0.0)),
        ]
        dynamic_bodies.append(
            {
                "name": body_name,
                "role": physical.get("role"),
                "source_object_id": object_id,
                "source_bounds_m": {"min": minimum, "max": maximum},
                "initial_position_m": center,
                "half_size_m": half_size,
                "size_m": size,
                "mass_kg": mass,
                "inertia_diagonal_kg_m2": inertia,
                "friction": friction,
                "restitution": float(physical.get("restitution", 0.0)),
                "support_proxy": support_name,
                "physics_authority": "MuJoCo",
                "placement_adjustment_m": [0.0, 0.0, 0.0],
                "collision_shape": (
                    "semantic_mesh_convex_hull"
                    if dynamic_mesh_assets is not None and body_name in dynamic_mesh_assets
                    else "box_aabb"
                ),
            }
        )
        if dynamic_mesh_assets is not None and body_name in dynamic_mesh_assets:
            dynamic_bodies[-1]["collision_mesh_file"] = str(dynamic_mesh_assets[body_name])

    _separate_dynamic_bodies(dynamic_bodies, proxies)
    return {
        "schema_version": 2,
        "physics_authority": "MuJoCo",
        "coordinate_system": dict(collision_spec.get("coordinate_system", {})),
        "proxies": proxies,
        "dynamic_bodies": dynamic_bodies,
        "dynamic_object_ids": [body["source_object_id"] for body in dynamic_bodies],
        "mesh_assets": {
            body["name"]: body["collision_mesh_file"]
            for body in dynamic_bodies
            if body.get("collision_mesh_file")
        },
        "source": {
            "physical_manifest": "physical_manifest",
            "semantic_bounds": "semantic_mesh_face_vertices",
            "source_data_modified": False,
        },
    }


def render_interaction_mjcf(spec: Mapping[str, Any]) -> str:
    """Render static collision proxies and dynamic freejoint bodies to MJCF."""

    lines = [
        '<mujoco model="office0_interaction">',
        '  <compiler angle="radian" coordinate="local"/>',
        '  <option gravity="0 0 -9.81" timestep="0.002" integrator="Euler"/>',
        '  <default>',
        '    <geom friction="0.5 0.005 0.001" solref="0.005 1" solimp="0.9 0.95 0.001"/>',
        '  </default>',
    ]
    mesh_bodies = [body for body in spec.get("dynamic_bodies", []) if body.get("collision_mesh_file")]
    if mesh_bodies:
        lines.append("  <asset>")
        for body in mesh_bodies:
            name = escape(str(body["name"]))
            mesh_file = escape(str(body["collision_mesh_file"]))
            lines.append(
                f'    <mesh name="{name}_mesh" file="{mesh_file}" scale="0.01 0.01 0.01"/>'
            )
        lines.append("  </asset>")
    lines.append("  <worldbody>")
    for proxy in spec.get("proxies", []):
        name = escape(str(proxy["name"]))
        center = _proxy_center(proxy)
        half_size = _proxy_half_size(proxy)
        lines.append(
            f'    <geom name="{name}" type="box" pos="{_fmt(center)}" size="{_fmt(half_size)}" contype="1" conaffinity="1"/>'
        )
    qpos: list[float] = []
    for body in spec.get("dynamic_bodies", []):
        name = escape(str(body["name"]))
        position = _float_list(body["initial_position_m"], f"{body['name']}.initial_position_m")
        half_size = _float_list(body["half_size_m"], f"{body['name']}.half_size_m")
        friction = _float_list(body["friction"], f"{body['name']}.friction")
        mass = float(body["mass_kg"])
        lines.extend([f'    <body name="{name}" pos="{_fmt(position)}">', f'      <freejoint name="{name}_freejoint"/>'])
        inertia = _float_list(body["inertia_diagonal_kg_m2"], f"{body['name']}.inertia_diagonal_kg_m2")
        # Keep mass and inertia from the physical manifest authoritative.  A
        # mesh geom with ``mass=`` but no body inertial lets MuJoCo infer mass
        # and inertia from the visual collision mesh, which silently discards
        # the measured/user-calibrated values.
        lines.append(
            f'      <inertial pos="0 0 0" mass="{mass:.9g}" diaginertia="{_fmt(inertia)}"/>'
        )
        if body.get("collision_mesh_file"):
            lines.append(
                f'      <geom name="{name}_geom" type="mesh" mesh="{name}_mesh" friction="{_fmt(friction)}" contype="1" conaffinity="1"/> '
            )
        else:
            lines.append(
                f'      <geom name="{name}_geom" type="box" size="{_fmt(half_size)}" friction="{_fmt(friction)}" contype="1" conaffinity="1"/>'
            )
        lines.append("    </body>")
        qpos.extend([*position, 1.0, 0.0, 0.0, 0.0])
    for body in spec.get("dynamic_bodies", []):
        mocap_name = escape(f"mocap_{body['name']}")
        position = _float_list(body["initial_position_m"], f"{body['name']}.initial_position_m")
        lines.append(f'    <body name="{mocap_name}" mocap="true" pos="{_fmt(position)}"/>')
    lines.extend(["  </worldbody>", "  <equality>"])
    for body in spec.get("dynamic_bodies", []):
        body_name = escape(str(body["name"]))
        mocap_name = escape(f"mocap_{body['name']}")
        lines.append(
            f'    <weld name="grab_{body_name}" body1="{body_name}" body2="{mocap_name}" '
            'relpose="0 0 0 1 0 0 0" solref="0.02 1" solimp="0.9 0.95 0.001" active="false"/>'
        )
    lines.extend(["  </equality>", "  <keyframe>"])
    qvel = [0.0] * (6 * len(spec.get("dynamic_bodies", [])))
    lines.append(f'    <key name="initial" qpos="{_fmt(qpos)}" qvel="{_fmt(qvel)}"/>')
    lines.extend(["  </keyframe>", "</mujoco>"])
    return "\n".join(lines) + "\n"
