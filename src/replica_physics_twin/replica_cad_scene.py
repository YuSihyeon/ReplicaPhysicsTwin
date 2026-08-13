"""Compile a ReplicaCAD scene into MuJoCo and Unreal interchange artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.sax.saxutils import escape

import numpy as np

from .replica_cad import (
    MeshData,
    convert_replica_cad_transform,
    inertia_from_bounds,
    load_glb,
    load_glb_parts,
    merge_meshes,
    replica_cad_to_mujoco_matrix,
    transform_mesh,
    write_obj,
    write_rptmesh2,
)


DEFAULT_SELECTED_TEMPLATES = (
	# These three source-native assets are clustered in the visible apartment
	# area: the bicycle and two hanging cloths can be inspected together while
	# still using their original render and convex collision geometry.
	"frl_apartment_bike_02",
	"frl_apartment_cloth_01",
	"frl_apartment_cloth_02",
)
DATASET_URL = "https://huggingface.co/datasets/ai-habitat/ReplicaCAD_dataset"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"


@dataclass(frozen=True)
class ReplicaCadObjectTemplate:
    name: str
    config_path: Path
    render_asset: Path
    collision_asset: Path | None
    mass_kg: float | None
    center_of_mass_source: tuple[float, float, float]
    semantic_id: int | None
    config: Mapping[str, Any]


@dataclass(frozen=True)
class ReplicaCadInstance:
    scene_index: int
    template_name: str
    motion_type: str
    translation_source: tuple[float, float, float]
    rotation_source_wxyz: tuple[float, float, float, float]
    uniform_scale: float


@dataclass(frozen=True)
class CollisionMesh:
    """Cached collision mesh plus the source method used to obtain it."""

    mesh: MeshData
    shape: str
    source_asset: Path | None


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _short_template_name(value: str) -> str:
    name = str(value).replace("\\", "/").rstrip("/").split("/")[-1]
    return name.removesuffix(".object_config.json")


def _safe_name(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return result or "object"


def _resolve_reference(config_path: Path, reference: str) -> Path:
    return (config_path.parent / reference).resolve()


def load_object_template(dataset_root: Path, template_name: str) -> ReplicaCadObjectTemplate:
    short_name = _short_template_name(template_name)
    config_path = (Path(dataset_root) / "configs" / "objects" / f"{short_name}.object_config.json").resolve()
    config = _load_json(config_path)
    render_reference = config.get("render_asset")
    collision_reference = config.get("collision_asset")
    if not isinstance(render_reference, str):
        raise ValueError(f"ReplicaCAD object config has no render asset: {config_path}")
    render_asset = _resolve_reference(config_path, render_reference)
    collision_asset = _resolve_reference(config_path, collision_reference) if isinstance(collision_reference, str) else None
    for asset in (render_asset, collision_asset):
        if asset is None:
            continue
        if not asset.is_file():
            raise FileNotFoundError(f"ReplicaCAD asset is missing: {asset}")
    mass_value = config.get("mass")
    mass = float(mass_value) if mass_value is not None else None
    com = tuple(float(value) for value in config.get("COM", [0.0, 0.0, 0.0]))
    if len(com) != 3:
        raise ValueError(f"Invalid COM in {config_path}")
    semantic_id = int(config["semantic_id"]) if config.get("semantic_id") is not None else None
    return ReplicaCadObjectTemplate(
        name=short_name,
        config_path=config_path,
        render_asset=render_asset,
        collision_asset=collision_asset,
        mass_kg=mass,
        center_of_mass_source=com,
        semantic_id=semantic_id,
        config=config,
    )


def load_replica_cad_scene(dataset_root: Path, scene_id: str = "apt_0") -> tuple[dict[str, Any], list[ReplicaCadInstance]]:
    dataset_root = Path(dataset_root).resolve()
    scene_path = dataset_root / "configs" / "scenes" / f"{scene_id}.scene_instance.json"
    scene = _load_json(scene_path)
    instances: list[ReplicaCadInstance] = []
    for index, item in enumerate(scene.get("object_instances", [])):
        if not isinstance(item, dict) or not isinstance(item.get("template_name"), str):
            continue
        translation = tuple(float(value) for value in item.get("translation", [0.0, 0.0, 0.0]))
        rotation = tuple(float(value) for value in item.get("rotation", [1.0, 0.0, 0.0, 0.0]))
        if len(translation) != 3 or len(rotation) != 4:
            raise ValueError(f"Invalid transform in {scene_path} object {index}")
        instances.append(
            ReplicaCadInstance(
                scene_index=index,
                template_name=_short_template_name(str(item["template_name"])),
                motion_type=str(item.get("motion_type", "STATIC")).upper(),
                translation_source=translation,
                rotation_source_wxyz=rotation,
                uniform_scale=float(item.get("uniform_scale", 1.0)),
            )
        )
    return scene, instances


def _pose_matrix(position: Iterable[float], quaternion_wxyz: Iterable[float], scale: float = 1.0) -> np.ndarray:
    w, x, y, z = (float(value) for value in quaternion_wxyz)
    norm = max(float(np.linalg.norm([w, x, y, z])), 1e-12)
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = rotation * float(scale)
    result[:3, 3] = np.asarray(list(position), dtype=np.float64)
    return result


def _scale_matrix(scale: float) -> np.ndarray:
    result = np.eye(4, dtype=np.float64)
    result[0, 0] = result[1, 1] = result[2, 2] = float(scale)
    return result


def _fmt(values: Iterable[float]) -> str:
    return " ".join(f"{float(value):.9g}" for value in values)


def _normalize_quaternion_wxyz(quaternion: Iterable[float]) -> np.ndarray:
    value = np.asarray(list(quaternion), dtype=np.float64)
    norm = max(float(np.linalg.norm(value)), 1e-12)
    return value / norm


def _quaternion_multiply_wxyz(first: Iterable[float], second: Iterable[float]) -> np.ndarray:
    aw, ax, ay, az = _normalize_quaternion_wxyz(first)
    bw, bx, by, bz = _normalize_quaternion_wxyz(second)
    return np.asarray(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ],
        dtype=np.float64,
    )


def _quaternion_rotation_matrix_wxyz(quaternion: Iterable[float]) -> np.ndarray:
    w, x, y, z = _normalize_quaternion_wxyz(quaternion)
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _friction(sliding: float) -> dict[str, float]:
    return {"sliding": float(sliding), "torsional": 0.005, "rolling": 0.001}


def _mesh_to_unreal_cm(mesh: MeshData) -> MeshData:
    return transform_mesh(mesh, _scale_matrix(100.0))


def _convert_replica_cad_vector(vector: Iterable[float], scale: float = 1.0) -> np.ndarray:
    """Convert a local ReplicaCAD vector into the MuJoCo basis."""

    basis = replica_cad_to_mujoco_matrix()[:3, :3]
    return (basis @ np.asarray(list(vector), dtype=np.float64)) * float(scale)


def _write_provenance(path: Path, dataset_root: Path, scene_id: str, templates: Iterable[ReplicaCadObjectTemplate]) -> None:
    lines = [
        "# ReplicaCAD physics-twin provenance",
        "",
        f"- Dataset: [ReplicaCAD](<{DATASET_URL}>)",
        "- License: [CC BY 4.0](<" + LICENSE_URL + ">)",
        f"- Local source: `{dataset_root}`",
        f"- Scene: `{scene_id}`",
        "- Geometry source: ReplicaCAD GLB render assets",
        "- Collision source: ReplicaCAD convex-decomposition GLB assets",
        "- Mass authority: each selected object's `object_config.json` `mass` field",
        "- Inertia authority: derived from the collision mesh bounds when the source config has no inertia field",
        "",
        "## Selected object templates",
        "",
    ]
    for template in templates:
        lines.append(f"- `{template.name}`: mass={template.mass_kg} kg; config=`{template.config_path}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _build_manifest(
    *,
    dataset_root: Path,
    scene_id: str,
    stage_config_path: Path,
    stage_mesh: Path,
    stage_collision: Path,
    stage_collision_bounds_min: Iterable[float],
    stage_collision_bounds_max: Iterable[float],
    visual_scene_mesh: Path,
    dynamic_bodies: list[dict[str, Any]],
    static_visual_instances: list[dict[str, Any]],
    static_collision_instances: list[dict[str, Any]],
    initial_contact_exclusions: list[dict[str, Any]],
    presentation_bounds: dict[str, Any],
    provenance_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset": "ReplicaCAD",
        "source_url": DATASET_URL,
        "license": "CC BY 4.0",
        "license_url": LICENSE_URL,
        "dataset_root": str(dataset_root.resolve()),
        "scene_id": scene_id,
        "physics_authority": "MuJoCo",
        "coordinate_system": {
            "source_up_axis": "Y",
            "target_up_axis": "Z",
            "source_to_target": "[x,y,z] -> [x,-z,y]",
            "units": "meters; Unreal visual interchange is centimeters",
        },
        "stage": {
            "config_path": str(stage_config_path.resolve()),
            "visual_mesh_file": str(stage_mesh.resolve()),
            "collision_mesh_file": str(stage_collision.resolve()),
            "collision_mode": "room_shell_box_proxies",
            "collision_bounds_min_m": [float(value) for value in stage_collision_bounds_min],
            "collision_bounds_max_m": [float(value) for value in stage_collision_bounds_max],
        },
        "visual_scene_mesh": str(visual_scene_mesh.resolve()),
        "presentation_bounds": presentation_bounds,
        "dynamic_bodies": dynamic_bodies,
        "static_visual_instances": static_visual_instances,
        "static_collision_instances": static_collision_instances,
        "initial_contact_exclusions": initial_contact_exclusions,
        "objects": dynamic_bodies,
        "provenance_report": str(provenance_path.resolve()),
        "source": {
            "source_data_modified": False,
            "geometry_authority": "ReplicaCAD GLB",
            "mass_authority": "ReplicaCAD object_config.json",
            "physics_authority": "MuJoCo",
        },
    }


def render_replica_cad_mjcf(manifest: Mapping[str, Any]) -> str:
    """Render the stage, rigid selections, and true MuJoCo cloth flexes."""

    lines = [
        '<mujoco model="replica_cad_interaction">',
        '  <compiler angle="radian" coordinate="local" meshdir="."/>',
        # Wind and air density are part of the MuJoCo environment.  A cloth
        # therefore receives aerodynamic drag, rather than being keyframed or
        # moved down by a scripted animation.
        # A 2 kHz physics clock resolves the thin textile shell and hanging
        # welds without the transient QACC spike seen at 1 kHz, while the
        # bridge still publishes the state to Unreal at 60 Hz.
        '  <option gravity="0 0 -9.81" wind="0.7 0.15 0.05" density="1.225" viscosity="1.5e-5" timestep="0.0005" integrator="implicitfast" cone="elliptic"/>',
        '  <size njmax="20000" nconmax="10000"/>',
        '  <default>',
        '    <geom contype="1" conaffinity="1" friction="0.8 0.005 0.001" solref="0.005 1" solimp="0.9 0.95 0.001"/>',
        '  </default>',
        '  <asset>',
    ]
    mesh_paths: dict[str, str] = {}
    for record in manifest.get("static_collision_instances", []):
        mesh_name = record.get("mesh_name")
        mesh_path = record.get("collision_mesh_file")
        if not mesh_name or not mesh_path:
            continue
        mesh_name = str(mesh_name)
        mesh_path = str(mesh_path)
        if mesh_name not in mesh_paths:
            mesh_paths[mesh_name] = mesh_path
    for body in manifest.get("dynamic_bodies", []):
        # A flex cloth owns its collision surface through the flexcomp
        # vertices.  Declaring the source triangle mesh as a MuJoCo mesh asset
        # would ask the rigid mesh compiler for a volumetric inertia even
        # though no rigid geom uses it (a zero-thickness cloth can fail that
        # check).  Rigid selections still use their convex collision mesh.
        if bool(body.get("deformable", False)):
            continue
        mesh_name = str(body["mesh_name"])
        mesh_path = str(body["collision_mesh_file"])
        if mesh_name not in mesh_paths and mesh_path:
            mesh_paths[mesh_name] = mesh_path
        for part in body.get("collision_mesh_parts", []):
            part_name = part.get("mesh_name")
            part_path = part.get("collision_mesh_file")
            if part_name and part_path and str(part_name) not in mesh_paths:
                mesh_paths[str(part_name)] = str(part_path)
    for mesh_name, mesh_path in mesh_paths.items():
        if mesh_name == "replica_cad_stage_collision":
            continue
        lines.append(f'    <mesh name="{escape(mesh_name)}" file="{escape(mesh_path)}"/>')
    lines.extend(["  </asset>", "  <worldbody>"])
    stage = manifest["stage"]
    stage_min = np.asarray(stage["collision_bounds_min_m"], dtype=np.float64)
    stage_max = np.asarray(stage["collision_bounds_max_m"], dtype=np.float64)
    stage_size = np.maximum(stage_max - stage_min, 0.01)
    wall_thickness = min(0.08, float(np.min(stage_size[:2])) * 0.05)
    floor_thickness = min(0.08, float(stage_size[2]) * 0.03)
    shell_geoms = [
        ("floor", (stage_min + stage_max) * 0.5 * np.array([1.0, 1.0, 0.0]) + np.array([0.0, 0.0, stage_min[2] + floor_thickness * 0.5]), np.array([stage_size[0] * 0.5, stage_size[1] * 0.5, floor_thickness * 0.5])),
        ("ceiling", np.array([(stage_min[0] + stage_max[0]) * 0.5, (stage_min[1] + stage_max[1]) * 0.5, stage_max[2] - floor_thickness * 0.5]), np.array([stage_size[0] * 0.5, stage_size[1] * 0.5, floor_thickness * 0.5])),
        ("wall_x_min", np.array([stage_min[0] + wall_thickness * 0.5, (stage_min[1] + stage_max[1]) * 0.5, (stage_min[2] + stage_max[2]) * 0.5]), np.array([wall_thickness * 0.5, stage_size[1] * 0.5, stage_size[2] * 0.5])),
        ("wall_x_max", np.array([stage_max[0] - wall_thickness * 0.5, (stage_min[1] + stage_max[1]) * 0.5, (stage_min[2] + stage_max[2]) * 0.5]), np.array([wall_thickness * 0.5, stage_size[1] * 0.5, stage_size[2] * 0.5])),
        ("wall_y_min", np.array([(stage_min[0] + stage_max[0]) * 0.5, stage_min[1] + wall_thickness * 0.5, (stage_min[2] + stage_max[2]) * 0.5]), np.array([stage_size[0] * 0.5, wall_thickness * 0.5, stage_size[2] * 0.5])),
        ("wall_y_max", np.array([(stage_min[0] + stage_max[0]) * 0.5, stage_max[1] - wall_thickness * 0.5, (stage_min[2] + stage_max[2]) * 0.5]), np.array([stage_size[0] * 0.5, wall_thickness * 0.5, stage_size[2] * 0.5])),
    ]
    for name, position, half_size in shell_geoms:
        lines.append(
            f'    <geom name="replica_cad_{name}" type="box" pos="{_fmt(position)}" size="{_fmt(half_size)}" '
            'friction="0.8 0.005 0.001" contype="1" conaffinity="1"/>'
        )
    for record in manifest.get("static_collision_instances", []):
        name = escape(str(record["name"]))
        position = _fmt(record["position_m"])
        quaternion = _fmt(record["quaternion_wxyz"])
        if record.get("collision_shape") == "bounding_box":
            center = _fmt(record["collision_center_m"])
            half_size = [float(value) * 0.5 for value in record["collision_size_m"]]
            geom = (
                f'      <geom name="{name}_geom" type="box" pos="{center}" size="{_fmt(half_size)}" '
                'friction="0.8 0.005 0.001" contype="1" conaffinity="1"/>'
            )
        else:
            geom = (
                f'      <geom name="{name}_geom" type="mesh" mesh="{escape(str(record["mesh_name"]))}" '
                'friction="0.8 0.005 0.001" contype="1" conaffinity="1"/>'
            )
        lines.extend([f'    <body name="{name}" pos="{position}" quat="{quaternion}">', geom, "    </body>"])
    rigid_bodies: list[Mapping[str, Any]] = []
    cloth_bodies: list[Mapping[str, Any]] = []
    for body in manifest.get("dynamic_bodies", []):
        if bool(body.get("deformable", False)):
            cloth_bodies.append(body)
            continue
        rigid_bodies.append(body)
        name = escape(str(body["name"]))
        position = _fmt(body["initial_position_m"])
        quaternion = _fmt(body["initial_quaternion_wxyz"])
        friction = _fmt(
            [
                body["friction"]["sliding"],
                body["friction"]["torsional"],
                body["friction"]["rolling"],
            ]
        )
        inertia = _fmt(body["inertia_diagonal_kg_m2"])
        lines.extend(
            [
                f'    <body name="{name}" pos="{position}" quat="{quaternion}">',
                f'      <freejoint name="{name}_freejoint"/>',
                f'      <inertial pos="{_fmt(body["center_of_mass_m"])}" mass="{float(body["mass_kg"]):.9g}" diaginertia="{inertia}"/>',
                *(
                    [
                        f'      <geom name="{name}_geom_{index}" type="mesh" mesh="{escape(str(part["mesh_name"]))}" friction="{friction}" contype="1" conaffinity="1"/>'
                        for index, part in enumerate(body.get("collision_mesh_parts", []))
                    ]
                    or [
                        f'      <geom name="{name}_geom" type="mesh" mesh="{escape(str(body["mesh_name"]))}" friction="{friction}" '
                        'contype="1" conaffinity="1"/>'
                    ]
                ),
                "    </body>",
            ]
        )
    for body in cloth_bodies:
        name = escape(str(body["name"]))
        grid = body.get("cloth_grid")
        material = body.get("cloth_material")
        if not isinstance(grid, Mapping) or not isinstance(material, Mapping):
            raise ValueError(f"deformable body is missing cloth_grid/material metadata: {body['name']}")
        cols = max(int(grid.get("cols", 12)), 3)
        rows = max(int(grid.get("rows", 20)), 3)
        local_min = np.asarray(grid["local_bounds_min_m"], dtype=np.float64)
        local_max = np.asarray(grid["local_bounds_max_m"], dtype=np.float64)
        width = max(float(local_max[0] - local_min[0]), 0.02)
        height = max(float(local_max[2] - local_min[2]), 0.02)
        dx = width / float(cols - 1)
        dz = height / float(rows - 1)
        radius = max(float(material.get("radius_m", 0.0015)), 0.0002)
        # flexcomp's grid is an XY plane.  Rotate that plane into the source
        # object's XZ plane, then apply the object's source orientation.
        plane_quaternion = np.asarray([np.sqrt(0.5), np.sqrt(0.5), 0.0, 0.0], dtype=np.float64)
        object_quaternion = _normalize_quaternion_wxyz(body["initial_quaternion_wxyz"])
        flex_quaternion = _quaternion_multiply_wxyz(object_quaternion, plane_quaternion)
        local_center = np.asarray(
            [(local_min[0] + local_max[0]) * 0.5, 0.0, (local_min[2] + local_max[2]) * 0.5],
            dtype=np.float64,
        )
        flex_position = np.asarray(body["initial_position_m"], dtype=np.float64) + (
            _quaternion_rotation_matrix_wxyz(object_quaternion) @ local_center
        )
        friction = body.get("friction", {})
        # All cloth vertices remain physical point masses.  The top row is
        # fixed below with world weld equalities, but its mass must still be
        # retained so the source object's total mass remains authoritative.
        effective_flex_mass = float(body["mass_kg"])
        friction_values = _fmt(
            [
                friction.get("sliding", 0.8),
                friction.get("torsional", 0.005),
                friction.get("rolling", 0.001),
            ]
        )
        lines.extend(
            [
                f'    <flexcomp name="{name}" type="grid" dim="2" count="{cols} {rows} 1" '
                f'spacing="{_fmt([dx, dz, max(radius * 2.1, 0.0001)])}" pos="{_fmt(flex_position)}" '
                f'quat="{_fmt(flex_quaternion)}" mass="{effective_flex_mass:.9g}" radius="{radius:.9g}">',
                f'      <elasticity young="{float(material.get("young_pa", 2500.0)):.9g}" '
                f'poisson="{float(material.get("poisson", 0.3)):.9g}" '
                f'damping="{float(material.get("damping", 0.15)):.9g}" '
                f'thickness="{float(material.get("thickness_m", 0.002)):.9g}" elastic2d="both"/>',
                f'      <contact selfcollide="none" friction="{friction_values}" contype="1" conaffinity="1"/>',
                "    </flexcomp>",
            ]
        )
    # Each selected body gets a MuJoCo mocap marker and an inactive weld
    # constraint.  The bridge keeps the weld inactive and applies a finite
    # spring force during a mouse drag, so grabbing remains mass-sensitive
    # instead of becoming a kinematic teleport.
    for body in rigid_bodies:
        name = escape(str(body["name"]))
        lines.append(
            f'    <body name="mocap_{name}" mocap="true" pos="{_fmt(body["initial_position_m"])}" '
            f'quat="{_fmt(body["initial_quaternion_wxyz"])}"/>'
        )
    lines.extend(["  </worldbody>"])
    initial_contact_exclusions = manifest.get("initial_contact_exclusions", [])
    if initial_contact_exclusions:
        lines.append("  <contact>")
        for exclusion in initial_contact_exclusions:
            body1 = escape(str(exclusion["body1"]))
            body2 = escape(str(exclusion["body2"]))
            lines.append(f'    <exclude body1="{body1}" body2="{body2}"/>')
        lines.append("  </contact>")
    lines.append("  <equality>")
    for body in rigid_bodies:
        name = escape(str(body["name"]))
        lines.append(f'    <weld name="grab_{name}" body1="{name}" body2="mocap_{name}" active="false"/>')
    # MuJoCo's 2D bending model does not support flexcomp pin elements.  Use
    # explicit world welds for the hanging edge instead: the cloth keeps all
    # of its physical point masses, while the free rows can bend and flap.
    for body in cloth_bodies:
        name = escape(str(body["name"]))
        grid = body["cloth_grid"]
        rows = max(int(grid.get("rows", 20)), 3)
        cols = max(int(grid.get("cols", 12)), 3)
        for column in range(cols):
            vertex_id = column * rows + (rows - 1)
            lines.append(
                f'    <weld name="pin_{name}_{column}" body1="{name}_{vertex_id}" '
                'solref="0.05 1" solimp="0.95 0.99 0.001"/>'
            )
    # Initial body poses are encoded in body/flexcomp attributes.  Omitting a
    # hand-built keyframe is intentional: flexcomp expands into one slide
    # joint per vertex, so a rigid-body qpos list would reset the cloth to an
    # invalid state.  mj_resetData restores qpos0 for both model types.
    lines.extend(["  </equality>", "</mujoco>"])
    return "\n".join(lines) + "\n"


def compile_replica_cad_scene(
    *,
    dataset_root: Path,
    scene_id: str = "apt_0",
    output_root: Path,
    selected_templates: Iterable[str] = DEFAULT_SELECTED_TEMPLATES,
) -> dict[str, Any]:
    """Compile one ReplicaCAD scene and return the written manifest."""

    dataset_root = Path(dataset_root).resolve()
    output_root = Path(output_root).resolve()
    selected_names = tuple(_short_template_name(name) for name in selected_templates)
    scene, instances = load_replica_cad_scene(dataset_root, scene_id)
    stage_config_path = dataset_root / "configs" / "stages" / "frl_apartment_stage.stage_config.json"
    stage_config = _load_json(stage_config_path)
    stage_asset = _resolve_reference(stage_config_path, str(stage_config["render_asset"]))
    stage_friction = float(stage_config.get("friction_coefficient", 0.8))
    stage_restitution = float(stage_config.get("restitution_coefficient", 0.0))
    basis = replica_cad_to_mujoco_matrix()

    mesh_dir = output_root / "meshes"
    mjcf_dir = output_root / "mjcf"
    metadata_dir = output_root / "metadata"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    mjcf_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    stage_local = load_glb(stage_asset, coordinate_transform=basis)
    stage_collision_bounds_min = stage_local.bounds_min.tolist()
    stage_collision_bounds_max = stage_local.bounds_max.tolist()
    stage_visual_path = mesh_dir / "replica_cad_stage.rptmesh"
    stage_collision_path = mesh_dir / "replica_cad_stage_collision.obj"
    write_rptmesh2(_mesh_to_unreal_cm(stage_local), stage_visual_path)
    write_obj(stage_local, stage_collision_path)

    selected_instance_indices: set[int] = set()
    dynamic_instances: list[tuple[ReplicaCadInstance, ReplicaCadObjectTemplate]] = []
    templates_by_name: dict[str, ReplicaCadObjectTemplate] = {}
    for requested_name in selected_names:
        match = next((item for item in instances if item.template_name == requested_name), None)
        if match is None:
            raise ValueError(f"Selected ReplicaCAD template is not present in {scene_id}: {requested_name}")
        selected_instance_indices.add(match.scene_index)
        template = load_object_template(dataset_root, requested_name)
        templates_by_name[template.name] = template
        dynamic_instances.append((match, template))

    # The stage GLB contains the room shell, while the scene instance contains
    # the actual furniture and props.  Render every non-selected source
    # instance so the Unreal view remains a real room.  Only the selected
    # bodies and one support table become MuJoCo collision bodies in this first
    # focused physics experiment.
    environment_instances = [item for item in instances if item.scene_index not in selected_instance_indices]
    used_template_names = sorted(
        {item.template_name for item, _ in dynamic_instances}
        | {item.template_name for item in environment_instances}
    )
    for template_name in used_template_names:
        if template_name not in templates_by_name:
            templates_by_name[template_name] = load_object_template(dataset_root, template_name)

    visual_cache: dict[str, MeshData] = {}
    collision_cache: dict[str, CollisionMesh] = {}
    visual_paths: dict[str, Path] = {}
    collision_paths: dict[str, Path] = {}

    def visual_local(template: ReplicaCadObjectTemplate) -> MeshData:
        if template.name not in visual_cache:
            visual_cache[template.name] = load_glb(template.render_asset, coordinate_transform=basis)
            path = mesh_dir / f"replica_cad_{_safe_name(template.name)}.rptmesh"
            write_rptmesh2(_mesh_to_unreal_cm(visual_cache[template.name]), path)
            visual_paths[template.name] = path
        return visual_cache[template.name]

    def collision_local(template: ReplicaCadObjectTemplate) -> CollisionMesh:
        if template.name not in collision_cache:
            source_asset = template.collision_asset or template.render_asset
            collision_mesh = load_glb(source_asset, coordinate_transform=basis)
            collision_cache[template.name] = CollisionMesh(
                mesh=collision_mesh,
                shape="replica_cad_convex_decomposition" if template.collision_asset is not None else "bounding_box",
                source_asset=template.collision_asset,
            )
            path = mesh_dir / f"replica_cad_{_safe_name(template.name)}_collision.obj"
            write_obj(collision_mesh, path)
            collision_paths[template.name] = path
        return collision_cache[template.name]

    for template in templates_by_name.values():
        visual_local(template)
    for _, template in dynamic_instances:
        collision_local(template)
    for instance in environment_instances:
        collision_local(templates_by_name[instance.template_name])

    dynamic_bodies: list[dict[str, Any]] = []
    # Collision AABBs in world space are used only to detect malformed scan
    # placements before the first physics step.  ReplicaCAD source poses can
    # contain small/large mesh intersections; allowing MuJoCo to resolve one
    # after unpausing produces a startup impulse that looks like an incorrect
    # mass.  The actual rigid mesh remains the authority for all later
    # contacts; the generated contact exclusion only prevents this initial
    # overlap from injecting a non-user force.
    dynamic_initial_collision_bounds: list[tuple[str, np.ndarray, np.ndarray]] = []
    for instance, template in dynamic_instances:
        if template.mass_kg is None or template.mass_kg <= 0.0:
            raise ValueError(f"Selected ReplicaCAD object has no positive source mass: {template.name}")
        position, quaternion = convert_replica_cad_transform(
            instance.translation_source, instance.rotation_source_wxyz
        )
        initial_pose_adjustment = "source_pose"
        if template.name == "frl_apartment_bike_02":
            # The scanned bicycle is tilted by a few degrees even though its
            # two wheels are placed on the room floor.  That is a valid scan
            # pose but not a stable starting state for the explicit “push to
            # tip” interaction.  Preserve yaw while removing roll/pitch; the
            # user then supplies the torque needed to topple it.
            source_rotation = _quaternion_rotation_matrix_wxyz(quaternion)
            yaw = float(np.arctan2(source_rotation[1, 0], source_rotation[0, 0]))
            quaternion = _normalize_quaternion_wxyz(
                [np.cos(yaw * 0.5), 0.0, 0.0, np.sin(yaw * 0.5)]
            )
            initial_pose_adjustment = "upright_yaw_only_for_interaction_start"
        collision_record = collision_cache[template.name]
        collision_mesh = collision_record.mesh
        if instance.uniform_scale != 1.0:
            collision_mesh = transform_mesh(collision_mesh, _scale_matrix(instance.uniform_scale))
            collision_path = mesh_dir / f"replica_cad_{_safe_name(template.name)}_{instance.scene_index}_collision.obj"
            write_obj(collision_mesh, collision_path)
            mesh_name = f"replica_cad_{_safe_name(template.name)}_{instance.scene_index}_collision"
        else:
            collision_path = collision_paths[template.name]
            mesh_name = f"replica_cad_{_safe_name(template.name)}_collision"
        source_size = collision_mesh.bounds_max - collision_mesh.bounds_min
        center_of_mass_source = _convert_replica_cad_vector(
            template.center_of_mass_source,
            instance.uniform_scale,
        )
        center_of_mass = center_of_mass_source.tolist()
        inertia = inertia_from_bounds(template.mass_kg, collision_mesh.bounds_min, collision_mesh.bounds_max)
        body_name = f"replica_{_safe_name(template.name.removeprefix('frl_apartment_'))}_{instance.scene_index}"
        is_cloth = "cloth" in template.name.lower()
        collision_mesh_parts: list[dict[str, str]] = []
        # The bicycle collision asset is a true convex decomposition: each
        # glTF node is a wheel/frame/handlebar hull.  Keep those hulls as
        # separate MuJoCo geoms so the bicycle has two real ground supports;
        # merging them into one mesh creates a single envelope that topples
        # immediately even with the source 9 kg mass.
        if template.name == "frl_apartment_bike_02" and not is_cloth:
            source_parts = load_glb_parts(template.collision_asset, coordinate_transform=basis)
            for part_index, part_mesh in enumerate(source_parts):
                if instance.uniform_scale != 1.0:
                    part_mesh = transform_mesh(part_mesh, _scale_matrix(instance.uniform_scale))
                part_path = mesh_dir / (
                    f"replica_cad_{_safe_name(template.name)}_{instance.scene_index}_hull_{part_index}.obj"
                )
                write_obj(part_mesh, part_path)
                collision_mesh_parts.append(
                    {
                        "mesh_name": f"replica_cad_{_safe_name(template.name)}_{instance.scene_index}_hull_{part_index}",
                        "collision_mesh_file": str(part_path.resolve()),
                    }
                )
        visual_mesh = visual_cache[template.name]
        visual_bounds_min = visual_mesh.bounds_min * float(instance.uniform_scale)
        visual_bounds_max = visual_mesh.bounds_max * float(instance.uniform_scale)
        visual_size = visual_bounds_max - visual_bounds_min
        cloth_grid: dict[str, Any] | None = None
        cloth_material: dict[str, float] | None = None
        if is_cloth:
            # ReplicaCAD supplies the render mesh and object mass, but not a
            # fabric Young's modulus or aerodynamic profile.  These are an
            # explicit, conservative cloth calibration so the missing source
            # material fields are not silently treated as rigid-body inertia.
            width = max(float(visual_size[0]), 0.02)
            height = max(float(visual_size[2]), 0.02)
            # Keep enough nodes for visible folds and wind response, while
            # making the full ReplicaCAD room interactive on a desktop CPU.
            # The source render mesh remains high resolution; Unreal
            # interpolates these physical nodes onto that mesh.
            cols = 8
            rows = 14
            # The source cloth assets are scans with varying local depth and
            # pose.  The flex is a thin XZ material sheet; map its simulated
            # surface to the source mesh's X/Z silhouette while preserving
            # the source mesh's local Y thickness during Unreal remapping.
            cloth_grid = {
                "cols": cols,
                "rows": rows,
                "local_bounds_min_m": [
                    float(visual_bounds_min[0]),
                    float(visual_bounds_min[1]),
                    float(visual_bounds_min[2]),
                ],
                "local_bounds_max_m": [
                    float(visual_bounds_max[0]),
                    float(visual_bounds_max[1]),
                    float(visual_bounds_max[2]),
                ],
                "mapping_axes": "local_xz_to_flex_xy",
                "preserve_source_depth": True,
            }
            cloth_material = {
                # ReplicaCAD supplies the garment geometry and source mass,
                # but not textile test data.  These are calibrated priors for
                # a hanging garment: enough membrane/bending stiffness to
                # hold shape under gravity, while remaining flexible under
                # wind and contact.
                "young_pa": 25000.0 if "cloth_01" in template.name else 12000.0,
                "poisson": 0.30,
                "damping": 0.06 if "cloth_01" in template.name else 0.04,
                "thickness_m": 0.002 if "cloth_01" in template.name else 0.001,
                "radius_m": 0.002 if "cloth_01" in template.name else 0.001,
                "wind_drag_coefficient": 1.35,
                "wind_model": "MuJoCo option wind + air density/viscosity fluid drag",
            }
        dynamic_bodies.append(
            {
                "name": body_name,
                "display_name": template.name.removeprefix("frl_apartment_"),
                "template_name": template.name,
                "source_object_id": instance.scene_index,
                "source_scene_index": instance.scene_index,
                "initial_position_m": position.tolist(),
                "initial_quaternion_wxyz": quaternion.tolist(),
                "initial_pose_adjustment": initial_pose_adjustment,
                "center_of_mass_m": center_of_mass,
                "size_m": [float(value * instance.uniform_scale) for value in visual_size],
                "collision_size_m": source_size.tolist(),
                "mass_kg": float(template.mass_kg),
                "mass_source_value_kg": float(template.mass_kg),
                "mass_source": "ReplicaCAD object_config.json:mass",
                "inertia_diagonal_kg_m2": inertia.tolist(),
                "inertia_source": "derived_from_collision_mesh_bounds",
                "center_of_mass_source_m": [float(value) for value in template.center_of_mass_source],
                "friction": _friction(stage_friction),
                "restitution": stage_restitution,
                "movable": True,
                "collision_shape": collision_record.shape,
                "visual_mesh_file": str(visual_paths[template.name].resolve()),
                "collision_mesh_file": str(collision_path.resolve()),
                "collision_mesh_parts": collision_mesh_parts,
                "mesh_name": mesh_name,
                "deformable": is_cloth,
                "deformable_type": "cloth" if is_cloth else None,
                "cloth_grid": cloth_grid,
                "cloth_material": cloth_material,
                "source": {
                    "config_path": str(template.config_path.resolve()),
                    "render_asset": str(template.render_asset.resolve()),
                    "collision_asset": str(template.collision_asset.resolve()) if template.collision_asset else None,
                    "collision_source_fallback": "render_asset_bounding_mesh" if template.collision_asset is None else None,
                    "mass_kg": float(template.mass_kg),
                    "mass_authority": "ReplicaCAD object_config.json",
                    "inertia_authority": "derived_from_collision_mesh_bounds",
                    "center_of_mass_source_m": [float(value) for value in template.center_of_mass_source],
                    "source_motion_type": instance.motion_type,
                },
            }
        )
        if not is_cloth:
            world_collision_mesh = transform_mesh(
                collision_mesh,
                _pose_matrix(position, quaternion),
            )
            dynamic_initial_collision_bounds.append(
                (
                    body_name,
                    world_collision_mesh.bounds_min.copy(),
                    world_collision_mesh.bounds_max.copy(),
                )
            )

    static_visual_meshes: list[MeshData] = [stage_local]
    static_visual_instances: list[dict[str, Any]] = []
    static_collision_instances: list[dict[str, Any]] = []
    initial_contact_exclusions: list[dict[str, Any]] = []
    for instance in environment_instances:
        template = templates_by_name[instance.template_name]
        position, quaternion = convert_replica_cad_transform(
            instance.translation_source, instance.rotation_source_wxyz
        )
        pose = _pose_matrix(position, quaternion, instance.uniform_scale)
        world_mesh = transform_mesh(visual_cache[template.name], pose)
        static_visual_meshes.append(world_mesh)
        static_name = f"static_{_safe_name(template.name)}_{instance.scene_index}"
        static_visual_instances.append(
            {
                "name": static_name,
                "template_name": template.name,
                "source_object_id": instance.scene_index,
                "position_m": position.tolist(),
                "quaternion_wxyz": quaternion.tolist(),
                "visual_mesh_file": str(visual_paths[template.name].resolve()),
                "source_motion_type": instance.motion_type,
            }
        )
        collision_record = collision_cache[template.name]
        collision_mesh = collision_record.mesh
        if instance.uniform_scale != 1.0:
            collision_mesh = transform_mesh(collision_mesh, _scale_matrix(instance.uniform_scale))
        world_collision_mesh = transform_mesh(
            collision_mesh,
            _pose_matrix(position, quaternion),
        )
        static_bounds_min = world_collision_mesh.bounds_min
        static_bounds_max = world_collision_mesh.bounds_max
        static_name = f"static_{_safe_name(template.name)}_{instance.scene_index}"
        for dynamic_name, dynamic_min, dynamic_max in dynamic_initial_collision_bounds:
            overlap = np.minimum(dynamic_max, static_bounds_max) - np.maximum(dynamic_min, static_bounds_min)
            # A tiny positive overlap can be a convex-hull/AABB rounding
            # artifact.  Require at least 2 cm on one axis before excluding a
            # pair; a substantial overlap is the startup-impulse failure mode.
            if np.all(overlap > 0.0) and float(np.max(overlap)) >= 0.02:
                initial_contact_exclusions.append(
                    {
                        "body1": dynamic_name,
                        "body2": static_name,
                        "reason": "initial_scan_intersection",
                        "aabb_overlap_m": [float(value) for value in overlap],
                    }
                )
        collision_size = collision_mesh.bounds_max - collision_mesh.bounds_min
        collision_center = (collision_mesh.bounds_min + collision_mesh.bounds_max) * 0.5
        collision_mesh_name: str | None = None
        collision_path: Path | None = None
        if collision_record.shape == "replica_cad_convex_decomposition":
            collision_mesh_name = f"replica_cad_{_safe_name(template.name)}_collision"
            collision_path = collision_paths[template.name]
        if instance.uniform_scale != 1.0 and collision_record.shape == "replica_cad_convex_decomposition":
            collision_path = mesh_dir / f"replica_cad_{_safe_name(template.name)}_{instance.scene_index}_collision.obj"
            write_obj(collision_mesh, collision_path)
            collision_mesh_name = f"replica_cad_{_safe_name(template.name)}_{instance.scene_index}_collision"
        static_collision_instances.append(
            {
                "name": static_name,
                "template_name": template.name,
                "source_object_id": instance.scene_index,
                "position_m": position.tolist(),
                "quaternion_wxyz": quaternion.tolist(),
                "collision_mesh_file": str(collision_path.resolve()) if collision_path else None,
                "mesh_name": collision_mesh_name,
                "collision_shape": collision_record.shape,
                "collision_source_asset": str(collision_record.source_asset.resolve()) if collision_record.source_asset else None,
                "collision_center_m": collision_center.tolist(),
                "collision_size_m": collision_size.tolist(),
                "source_motion_type": instance.motion_type,
            }
        )

    # Keep the rendered mesh on the exact same pose as the MuJoCo body.  In
    # particular, the bike is intentionally started upright (yaw only) so its
    # wheel contacts, mass and visual pose agree at the first frame.
    dynamic_visual_meshes = [
        transform_mesh(
            visual_cache[template.name],
            _pose_matrix(
                dynamic_bodies[index]["initial_position_m"],
                dynamic_bodies[index]["initial_quaternion_wxyz"],
                instance.uniform_scale,
            ),
        )
        for index, (instance, template) in enumerate(dynamic_instances)
    ]
    visual_scene = merge_meshes(_mesh_to_unreal_cm(mesh) for mesh in static_visual_meshes)
    visual_scene_path = mesh_dir / "replica_cad_scene.rptmesh"
    write_rptmesh2(visual_scene, visual_scene_path)

    presentation_mesh = merge_meshes([*static_visual_meshes, *dynamic_visual_meshes])
    dynamic_presentation_mesh = merge_meshes(dynamic_visual_meshes)
    presentation_min = presentation_mesh.bounds_min
    presentation_max = presentation_mesh.bounds_max
    presentation_span = presentation_max - presentation_min
    scene_focus = (presentation_min + presentation_max) * 0.5
    objects_focus = (dynamic_presentation_mesh.bounds_min + dynamic_presentation_mesh.bounds_max) * 0.5
    presentation_bounds = {
        "min_m": [float(value) for value in presentation_min],
        "max_m": [float(value) for value in presentation_max],
        "focus_m": [float(value) for value in objects_focus],
        "scene_focus_m": [float(value) for value in scene_focus],
        "room_min_m": [float(value) for value in stage_local.bounds_min],
        "room_max_m": [float(value) for value in stage_local.bounds_max],
        "recommended_distance_m": float(max(float(np.max(presentation_span)) * 1.8, 3.0)),
        "source": "ReplicaCAD stage and all rendered scene instances",
    }

    provenance_path = output_root / "REPLICA_CAD_PROVENANCE.md"
    selected_templates_data = [template for _, template in dynamic_instances]
    _write_provenance(provenance_path, dataset_root, scene_id, selected_templates_data)
    manifest = _build_manifest(
        dataset_root=dataset_root,
        scene_id=scene_id,
        stage_config_path=stage_config_path,
        stage_mesh=stage_visual_path,
        stage_collision=stage_collision_path,
        stage_collision_bounds_min=stage_collision_bounds_min,
        stage_collision_bounds_max=stage_collision_bounds_max,
        visual_scene_mesh=visual_scene_path,
        dynamic_bodies=dynamic_bodies,
        static_visual_instances=static_visual_instances,
        static_collision_instances=static_collision_instances,
        initial_contact_exclusions=initial_contact_exclusions,
        presentation_bounds=presentation_bounds,
        provenance_path=provenance_path,
    )
    xml_path = mjcf_dir / f"replica_cad_{_safe_name(scene_id)}_interaction.xml"
    metadata_path = metadata_dir / "replica_cad_interaction.json"
    xml_path.write_text(render_replica_cad_mjcf(manifest), encoding="utf-8", newline="\n")
    manifest["xml_path"] = str(xml_path.resolve())
    manifest["metadata_path"] = str(metadata_path.resolve())
    metadata_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return manifest
