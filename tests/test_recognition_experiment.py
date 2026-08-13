from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.recognize_office0_objects import run_experiment


def test_office0_sparse_recognition_selects_semantic_tissue_object() -> None:
    report = run_experiment(
        manifest_path=PROJECT_ROOT / "data/derived/office_0/scene_manifest.json",
        semantic_summary_path=PROJECT_ROOT / "data/derived/office_0/semantic_summary.json",
        semantic_mesh_path=PROJECT_ROOT / "data/raw/replica_v1/office_0/habitat/mesh_semantic.ply",
        target="tissue_box",
    )

    assert report["feature_source"] == ["scene_manifest", "semantic_summary", "semantic_mesh_presence"]
    assert report["recognition"]["status"] == "selected"
    assert report["recognition"]["selected_object_id"] == 28
    assert "rgb" not in json.dumps(report, ensure_ascii=False).lower()
    assert "texture" not in json.dumps(report, ensure_ascii=False).lower()
