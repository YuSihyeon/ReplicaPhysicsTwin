"""Generate the derived Unreal visual mesh for Replica office_0."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from replica_physics_twin.visual_mesh import build_visual_mesh, build_visual_mesh_variant


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, default=Path("data/raw/replica_v1/office_0"))
    parser.add_argument("--output-obj", type=Path, default=Path("outputs/meshes/office_0_visual.obj"))
    parser.add_argument(
        "--transform-metadata",
        type=Path,
        default=Path("outputs/metadata/office_0_visual_transform.json"),
    )
    parser.add_argument(
        "--output-binary",
        type=Path,
        default=Path("outputs/meshes/office_0_visual.rptmesh"),
    )
    args = parser.parse_args()
    full_result = build_visual_mesh(
        args.scene_dir,
        args.output_obj,
        args.transform_metadata,
        output_binary=args.output_binary,
    )
    dynamic_object_names = {
        4: "chair_4",
        28: "tissue_box",
        44: "desk_organizer",
    }
    static_result = build_visual_mesh_variant(
        args.scene_dir,
        Path("outputs/meshes/office_0_visual_static.obj"),
        Path("outputs/metadata/office_0_visual_static_transform.json"),
        output_binary=Path("outputs/meshes/office_0_visual_static.rptmesh"),
        exclude_object_ids=set(dynamic_object_names),
        mesh_relative_path="habitat/mesh_semantic.ply",
    )
    dynamic_results = {}
    for object_id, object_name in dynamic_object_names.items():
        dynamic_results[object_name] = build_visual_mesh_variant(
            args.scene_dir,
            Path(f"outputs/meshes/office_0_{object_name}.obj"),
            Path(f"outputs/metadata/office_0_{object_name}_visual_transform.json"),
            output_binary=Path(f"outputs/meshes/office_0_{object_name}.rptmesh"),
            object_ids={object_id},
            mesh_relative_path="habitat/mesh_semantic.ply",
        )
    print(json.dumps({"full": full_result, "static": static_result, "dynamic": dynamic_results}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
