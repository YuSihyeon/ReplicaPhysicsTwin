from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_office0_physical_manifest import (  # noqa: E402
    load_physics_config,
    run_build,
)


def test_physics_config_loader_reads_material_and_override_files() -> None:
    material_priors = load_physics_config(PROJECT_ROOT / "configs/material_priors.yaml")
    overrides = load_physics_config(PROJECT_ROOT / "configs/physical_overrides.yaml")

    assert material_priors["materials"]["tissue-paper"]["density_kg_m3"] == 450.0
    assert overrides["user"]["44"]["movable"] is True
    assert overrides["measured"] == {}


def test_office0_physical_manifest_promotes_only_recognized_movable_role(tmp_path: Path) -> None:
    output_path = tmp_path / "office0_physical_manifest.json"
    result = run_build(output_path=output_path)

    assert result["physics_authority"] == "MuJoCo"
    tissue = next(item for item in result["objects"] if item["object_id"] == 28)
    table = next(item for item in result["objects"] if item["object_id"] == 58)
    assert tissue["body_type"] == "dynamic"
    assert table["body_type"] == "static"
    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8"))["scene_id"] == "office_0"
