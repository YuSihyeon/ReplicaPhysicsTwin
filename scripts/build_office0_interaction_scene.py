"""Build the multi-object Office 0 MuJoCo interaction scene."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import mujoco


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from replica_physics_twin.office0_collision import read_semantic_instance_bounds  # noqa: E402
from replica_physics_twin.physical_scene import (  # noqa: E402
    build_interaction_scene_spec,
    render_interaction_mjcf,
)
from scripts.build_office0_physical_manifest import (  # noqa: E402
    run_build as run_physical_manifest_build,
)


def _load_json(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def run_build(*, xml_path: Path, metadata_path: Path) -> dict[str, Any]:
    manifest_path = PROJECT_ROOT / "data/derived/office_0/scene_manifest.json"
    visual_path = PROJECT_ROOT / "outputs/metadata/office_0_visual_transform.json"
    collision_path = PROJECT_ROOT / "outputs/metadata/office0_collision_proxy.json"
    semantic_mesh_path = PROJECT_ROOT / "data/raw/replica_v1/office_0/habitat/mesh_semantic.ply"
    physical_path = PROJECT_ROOT / "outputs/metadata/office0_physical_manifest.json"

    run_physical_manifest_build(output_path=physical_path)
    physical_manifest = _load_json(physical_path)
    collision_spec = _load_json(collision_path)
    visual_metadata = _load_json(visual_path)
    dynamic_ids = [int(object_id) for object_id in physical_manifest.get("dynamic_object_ids", [])]
    measured_bounds = read_semantic_instance_bounds(semantic_mesh_path, set(dynamic_ids))
    mesh_assets = {
        "tissue_box": str((PROJECT_ROOT / "outputs/meshes/office_0_tissue_box.obj").resolve()),
        "desk_organizer": str((PROJECT_ROOT / "outputs/meshes/office_0_desk_organizer.obj").resolve()),
        "chair_4": str((PROJECT_ROOT / "outputs/meshes/office_0_chair_4.obj").resolve()),
    }
    spec = build_interaction_scene_spec(
        collision_spec,
        physical_manifest,
        visual_metadata,
        measured_bounds,
        dynamic_mesh_assets=mesh_assets,
    )
    xml_text = render_interaction_mjcf(spec)
    xml_path = Path(xml_path)
    metadata_path = Path(metadata_path)
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(xml_text, encoding="utf-8", newline="\n")
    model = mujoco.MjModel.from_xml_path(str(xml_path.resolve()))
    spec["model_summary"] = {
        "nbody": int(model.nbody),
        "ngeom": int(model.ngeom),
        "njnt": int(model.njnt),
        "nq": int(model.nq),
        "nv": int(model.nv),
    }
    spec["source"] = {
        "manifest": str(manifest_path.resolve()),
        "physical_manifest": str(physical_path.resolve()),
        "visual_transform_metadata": str(visual_path.resolve()),
        "collision_metadata": str(collision_path.resolve()),
        "semantic_mesh": str(semantic_mesh_path.resolve()),
        "source_data_modified": False,
    }
    metadata_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--xml",
        type=Path,
        default=PROJECT_ROOT / "outputs/mjcf/office0_interaction.xml",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=PROJECT_ROOT / "outputs/metadata/office0_interaction.json",
    )
    args = parser.parse_args()
    result = run_build(xml_path=args.xml, metadata_path=args.metadata)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
