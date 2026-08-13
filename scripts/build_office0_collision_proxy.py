"""Generate and validate the derived MuJoCo collision proxy for office_0."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_office0_physical_manifest import run_build as run_physical_manifest_build

from replica_physics_twin.office0_collision import (
    build_collision_proxy,
    run_multi_drop_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, default=Path("data/raw/replica_v1/office_0"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/derived/office_0/scene_manifest.json"),
    )
    parser.add_argument(
        "--visual-metadata",
        type=Path,
        default=Path("outputs/metadata/office_0_visual_transform.json"),
    )
    parser.add_argument(
        "--output-xml",
        type=Path,
        default=Path("outputs/mjcf/office0_collision_proxy.xml"),
    )
    parser.add_argument(
        "--output-metadata",
        type=Path,
        default=Path("outputs/metadata/office0_collision_proxy.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/reports/phase5"),
    )
    parser.add_argument(
        "--physical-manifest",
        type=Path,
        default=Path("outputs/metadata/office0_physical_manifest.json"),
    )
    parser.add_argument("--max-steps", type=int, default=3000)
    args = parser.parse_args()

    physical_manifest_path = Path(args.physical_manifest)
    run_physical_manifest_build(output_path=physical_manifest_path)
    physical_manifest = json.loads(physical_manifest_path.read_text(encoding="utf-8"))
    dynamic_object_ids = [int(object_id) for object_id in physical_manifest.get("dynamic_object_ids", [])]
    spec = build_collision_proxy(
        args.scene_dir,
        args.manifest,
        args.visual_metadata,
        args.output_xml,
        args.output_metadata,
        dynamic_object_ids=dynamic_object_ids,
    )
    validation = run_multi_drop_validation(
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
                "proxy_names": [proxy["name"] for proxy in spec["proxies"]],
                "alignment_check": spec["alignment_check"],
                "validation": validation,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if validation["passed"] and spec["alignment_check"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
