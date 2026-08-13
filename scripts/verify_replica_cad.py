"""Validate the small, interactive ReplicaCAD source subset used by the twin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))


DATASET_URL = "https://huggingface.co/datasets/ai-habitat/ReplicaCAD_dataset"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
DEFAULT_TEMPLATES = (
	"frl_apartment_bike_02",
	"frl_apartment_cloth_01",
	"frl_apartment_cloth_02",
)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _asset_reference(config_path: Path, reference: str) -> Path:
    """Resolve the dataset's paths, which are relative to the config file."""

    return (config_path.parent / reference).resolve()


def _object_report(dataset_root: Path, template: str) -> dict[str, Any]:
    config_path = dataset_root / "configs" / "objects" / f"{template}.object_config.json"
    result: dict[str, Any] = {
        "template": template,
        "config": str(config_path),
        "exists": config_path.is_file(),
        "missing": [],
    }
    if not config_path.is_file():
        result["missing"].append(str(config_path))
        return result

    config = _load_json(config_path)
    result["mass_kg"] = float(config["mass"])
    result["center_of_mass"] = list(config.get("COM", [0.0, 0.0, 0.0]))
    result["semantic_id"] = config.get("semantic_id")
    for key in ("render_asset", "collision_asset"):
        reference = config.get(key)
        if not isinstance(reference, str):
            result["missing"].append(f"{config_path}: missing {key}")
            continue
        resolved = _asset_reference(config_path, reference)
        result[key] = str(resolved)
        if not resolved.is_file():
            result["missing"].append(str(resolved))
    return result


def validate_replica_cad(
    dataset_root: Path,
    *,
    scene_id: str = "apt_0",
    templates: Iterable[str] = DEFAULT_TEMPLATES,
) -> dict[str, Any]:
    """Return a machine-readable report and raise only for malformed JSON."""

    dataset_root = Path(dataset_root).resolve()
    stage_config = dataset_root / "configs" / "stages" / "frl_apartment_stage.stage_config.json"
    stage = _load_json(stage_config) if stage_config.is_file() else {}
    stage_asset = _asset_reference(stage_config, str(stage["render_asset"])) if stage else stage_config.parent / ".." / ".." / "stages" / "frl_apartment_stage.glb"
    scene_path = dataset_root / "configs" / "scenes" / f"{scene_id}.scene_instance.json"
    scene = _load_json(scene_path) if scene_path.is_file() else {}

    objects = [_object_report(dataset_root, template) for template in templates]
    missing: list[str] = []
    for path in (stage_config, stage_asset, scene_path):
        if not path.is_file():
            missing.append(str(path))
    for item in objects:
        missing.extend(str(value) for value in item.get("missing", []))

    instances = scene.get("object_instances", [])
    if not isinstance(instances, list):
        instances = []

    return {
        "dataset": "ReplicaCAD",
        "source_url": DATASET_URL,
        "license": "CC BY 4.0",
        "license_url": LICENSE_URL,
        "dataset_root": str(dataset_root),
        "scene_id": scene_id,
        "stage": {
            "config": str(stage_config),
            "render_asset": str(stage_asset),
            "exists": stage_asset.is_file(),
            "up": stage.get("up", [0, 1, 0]),
            "friction_coefficient": stage.get("friction_coefficient", 0.8),
            "restitution_coefficient": stage.get("restitution_coefficient", 0.0),
        },
        "object_templates": objects,
        "scene_instance_count": len(instances),
        "missing": missing,
        "status": "ok" if not missing else "missing_assets",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--scene", default="apt_0")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    report = validate_replica_cad(args.dataset_root, scene_id=args.scene)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8", newline="\n")
    print(text, end="")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
