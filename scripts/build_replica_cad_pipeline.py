"""Compile ReplicaCAD apt_0 assets into MuJoCo and Unreal artifacts."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import mujoco


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from replica_physics_twin.replica_cad_scene import (  # noqa: E402
    DEFAULT_SELECTED_TEMPLATES,
    compile_replica_cad_scene as _compile_replica_cad_scene,
)


def compile_replica_cad_scene(**kwargs):
    manifest = _compile_replica_cad_scene(**kwargs)
    model = mujoco.MjModel.from_xml_path(manifest["xml_path"])
    for body in manifest["dynamic_bodies"]:
        if bool(body.get("deformable", False)):
            flex_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_FLEX, body["name"])
            if flex_id < 0:
                raise RuntimeError(f"MuJoCo did not create deformable flex: {body['name']}")
            start = int(model.flex_vertadr[flex_id])
            count = int(model.flex_vertnum[flex_id])
            node_body_ids = {
                int(body_id)
                for body_id in model.flex_vertbodyid[start : start + count]
                if int(body_id) > 0
            }
            mujoco_mass = float(sum(model.body_mass[body_id] for body_id in node_body_ids))
            body["mujoco_flex_id"] = int(flex_id)
            body["mujoco_flex_vertex_count"] = count
            body["mujoco_movable_node_count"] = len(node_body_ids)
        else:
            body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body["name"])
            if body_id < 0:
                raise RuntimeError(f"MuJoCo did not create dynamic body: {body['name']}")
            mujoco_mass = float(model.body_mass[body_id])
        source_mass = float(body["mass_kg"])
        if not math.isclose(mujoco_mass, source_mass, rel_tol=1e-9, abs_tol=1e-9):
            raise RuntimeError(
                f"MuJoCo mass mismatch for {body['name']}: source={source_mass} kg model={mujoco_mass} kg"
            )
        body["mujoco_mass_kg"] = mujoco_mass
        body["mass_validation"] = "passed"
    manifest["model_summary"] = {
        "nbody": int(model.nbody),
        "ngeom": int(model.ngeom),
        "njnt": int(model.njnt),
        "nflex": int(model.nflex),
        "nflexvert": int(model.nflexvert),
        "neq": int(model.neq),
        "nq": int(model.nq),
        "nv": int(model.nv),
    }
    metadata_path = Path(manifest["metadata_path"])
    metadata_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=PROJECT_ROOT / "data/raw/replica_cad")
    parser.add_argument("--scene", default="apt_0")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "outputs/replica_cad")
    parser.add_argument("--selected", nargs="+", default=list(DEFAULT_SELECTED_TEMPLATES))
    args = parser.parse_args()
    manifest = compile_replica_cad_scene(
        dataset_root=args.dataset_root,
        scene_id=args.scene,
        output_root=args.output_root,
        selected_templates=args.selected,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
