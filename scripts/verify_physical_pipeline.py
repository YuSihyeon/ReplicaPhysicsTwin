"""Run and persist deterministic MuJoCo physical-pipeline validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from replica_physics_twin.physical_pipeline import run_physical_pipeline_verification  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "outputs/reports/physical_pipeline_validation.json",
    )
    args = parser.parse_args()
    result = run_physical_pipeline_verification(args.project_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["automated_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
