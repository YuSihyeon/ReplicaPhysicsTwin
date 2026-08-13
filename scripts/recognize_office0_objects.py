"""Run the first sparse, explainable object-recognition experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from replica_physics_twin.object_recognition import (  # noqa: E402
    extract_sparse_object_features,
    recognize_object,
)


DEFAULT_ALIASES: dict[str, list[str]] = {
    "tissue_box": ["tissue", "tissue-paper", "paper-box", "facial-tissue"],
}

DEFAULT_PRIORS: dict[str, dict[str, Any]] = {
    "tissue_box": {
        # The ranges are intentionally broad MVP priors, not a hidden visual classifier.
        "size_m_range": [[0.10, 0.22], [0.08, 0.20], [0.14, 0.28]],
        "support_roles": ["desk", "table"],
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def run_experiment(
    *,
    manifest_path: Path,
    semantic_summary_path: Path,
    semantic_mesh_path: Path,
    target: str,
) -> dict[str, Any]:
    """Return a reproducible recognition report for one semantic target."""

    manifest = _load_json(Path(manifest_path))
    semantic_summary = _load_json(Path(semantic_summary_path))
    features = extract_sparse_object_features(manifest, semantic_summary, Path(semantic_mesh_path))
    recognition = recognize_object(
        features,
        target=target,
        aliases=DEFAULT_ALIASES,
        target_priors=DEFAULT_PRIORS,
    )
    mesh_size_bytes = Path(semantic_mesh_path).stat().st_size
    return {
        "schema_version": 1,
        "scene_id": str(manifest.get("scene_id", "unknown")),
        "target": target,
        "feature_source": [
            "scene_manifest",
            "semantic_summary",
            "semantic_mesh_presence",
        ],
        "input_paths": {
            "scene_manifest": str(Path(manifest_path).resolve()),
            "semantic_summary": str(Path(semantic_summary_path).resolve()),
            "semantic_mesh": str(Path(semantic_mesh_path).resolve()),
        },
        "semantic_mesh_bytes": mesh_size_bytes,
        "candidate_feature_count": len(features),
        "recognition": recognition,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "data/derived/office_0/scene_manifest.json",
    )
    parser.add_argument(
        "--semantic-summary",
        type=Path,
        default=PROJECT_ROOT / "data/derived/office_0/semantic_summary.json",
    )
    parser.add_argument(
        "--semantic-mesh",
        type=Path,
        default=PROJECT_ROOT / "data/raw/replica_v1/office_0/habitat/mesh_semantic.ply",
    )
    parser.add_argument("--target", default="tissue_box")
    parser.add_argument(
        "--output-metadata",
        type=Path,
        default=PROJECT_ROOT / "outputs/metadata/office0_object_candidates.json",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=PROJECT_ROOT / "outputs/reports/object_recognition_experiment.json",
    )
    args = parser.parse_args()

    report = run_experiment(
        manifest_path=args.manifest,
        semantic_summary_path=args.semantic_summary,
        semantic_mesh_path=args.semantic_mesh,
        target=args.target,
    )
    metadata = {
        "schema_version": report["schema_version"],
        "scene_id": report["scene_id"],
        "target": report["target"],
        "feature_source": report["feature_source"],
        "candidate_feature_count": report["candidate_feature_count"],
        "candidates": report["recognition"]["candidates"],
        "selected_object_id": report["recognition"]["selected_object_id"],
        "status": report["recognition"]["status"],
        "requires_user_confirmation": report["recognition"]["requires_user_confirmation"],
    }
    _write_json(args.output_metadata, metadata)
    _write_json(args.output_report, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["recognition"]["status"] == "selected" else 2


if __name__ == "__main__":
    raise SystemExit(main())
