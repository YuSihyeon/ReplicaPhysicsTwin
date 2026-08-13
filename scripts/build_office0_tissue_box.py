"""Generate and validate the Phase 6 office_0 tissue_box MuJoCo artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from replica_physics_twin.office0_collision import build_collision_proxy
from replica_physics_twin.tissue_box import (
    build_tissue_box_artifact,
    run_tissue_box_lift_drop_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, default=Path("data/raw/replica_v1/office_0"))
    parser.add_argument("--manifest", type=Path, default=Path("data/derived/office_0/scene_manifest.json"))
    parser.add_argument(
        "--visual-metadata",
        type=Path,
        default=Path("outputs/metadata/office_0_visual_transform.json"),
    )
    parser.add_argument(
        "--collision-xml",
        type=Path,
        default=Path("outputs/mjcf/office0_collision_proxy.xml"),
    )
    parser.add_argument(
        "--collision-metadata",
        type=Path,
        default=Path("outputs/metadata/office0_collision_proxy.json"),
    )
    parser.add_argument(
        "--output-xml",
        type=Path,
        default=Path("outputs/mjcf/office0_tissue_box.xml"),
    )
    parser.add_argument(
        "--output-metadata",
        type=Path,
        default=Path("outputs/metadata/office0_tissue_box.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/reports/phase6"))
    parser.add_argument("--max-steps", type=int, default=3000)
    args = parser.parse_args()

    # Refresh Phase 5 metadata first so the phase transition records the
    # current bookcase-not-present finding and the corrected tabletop boxes.
    build_collision_proxy(
        args.scene_dir,
        args.manifest,
        args.visual_metadata,
        args.collision_xml,
        args.collision_metadata,
    )
    spec = build_tissue_box_artifact(
        args.scene_dir,
        args.manifest,
        args.visual_metadata,
        args.collision_metadata,
        args.output_xml,
        args.output_metadata,
    )
    validation = run_tissue_box_lift_drop_validation(
        args.output_xml,
        spec,
        args.output_dir,
        max_steps=args.max_steps,
    )
    print(
        json.dumps(
            {
                "metadata_path": str(args.output_metadata.resolve()),
                "xml_path": str(args.output_xml.resolve()),
                "object_id": spec["tissue_box"]["object_id"],
                "support_proxy": spec["tissue_box"]["support_proxy"],
                "initial_position_m": spec["tissue_box"]["initial_position_m"],
                "rest_position_m": spec["tissue_box"]["rest_position_m"],
                "validation": validation,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if validation["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

