#!/usr/bin/env python3
"""Verify and selectively extract the official Replica v1 office_0 scene."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from replica_physics_twin.replica_archive import (  # noqa: E402
    expected_part_sizes,
    extract_office0,
    extract_office0_zip,
    verify_office0,
    verify_parts,
)


def _emit(payload: dict[str, Any], json_out: Path | None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(text + "\n", encoding="utf-8")


def _parts_command(args: argparse.Namespace) -> int:
    result = verify_parts(args.download_dir)
    _emit(result, args.json_out)
    return 0 if result["complete"] else 1


def _extract_command(args: argparse.Namespace) -> int:
    verification = verify_parts(args.download_dir)
    if not verification["complete"]:
        _emit({"extracted": False, "part_verification": verification}, args.json_out)
        return 1
    part_paths = [args.download_dir / name for name in expected_part_sizes()]
    result = extract_office0(part_paths, args.scene_dir)
    _emit({"extracted": True, **result}, args.json_out)
    return 0


def _habitat_command(args: argparse.Namespace) -> int:
    result = extract_office0_zip(args.zip_path, args.scene_dir)
    _emit({"extracted": True, **result}, args.json_out)
    return 0


def _scene_command(args: argparse.Namespace) -> int:
    result = verify_office0(args.scene_dir)
    _emit(result, args.json_out)
    return 0 if result["complete"] else 1


def _report_command(args: argparse.Namespace) -> int:
    parts = verify_parts(args.download_dir)
    scene = verify_office0(args.scene_dir)
    status = "SUCCESS" if parts["complete"] and scene["complete"] else "INCOMPLETE"
    wrong_sizes = parts["wrong_sizes"]
    lines = [
        "# Replica Download Report",
        "",
        f"- Updated UTC: {datetime.now(timezone.utc).isoformat()}",
        f"- Status: **{status}**",
        f"- Official archive parts: {len(expected_part_sizes())}",
        f"- Expected archive bytes: {parts['expected_bytes']}",
        f"- Present archive bytes: {parts['present_bytes']}",
        f"- Download directory: `{args.download_dir.resolve()}`",
        f"- Extracted scene directory: `{args.scene_dir.resolve()}`",
        f"- Extracted file count: {scene['file_count']}",
        f"- Extracted bytes: {scene['total_bytes']}",
        "",
        "## Validation",
        "",
        f"- Missing parts: {', '.join(parts['missing']) or 'none'}",
        f"- Wrong-sized parts: {', '.join(wrong_sizes) or 'none'}",
        f"- Missing required scene files: {', '.join(scene['missing']) or 'none'}",
        "",
        "## Required files",
        "",
    ]
    for name, size in scene["required_files"].items():
        lines.append(f"- `{name}`: {size} bytes")
    if not scene["required_files"]:
        lines.append("- Not available yet")
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.report_path)
    return 0 if status == "SUCCESS" else 1


def _add_json_out(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json-out", type=Path, help="Optional JSON result path")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    parts = subparsers.add_parser("parts", help="Verify partaa through partaq names and sizes")
    parts.add_argument("--download-dir", type=Path, required=True)
    _add_json_out(parts)
    parts.set_defaults(handler=_parts_command)

    extract = subparsers.add_parser("extract", help="Stream all parts and extract office_0 only")
    extract.add_argument("--download-dir", type=Path, required=True)
    extract.add_argument("--scene-dir", type=Path, required=True)
    _add_json_out(extract)
    extract.set_defaults(handler=_extract_command)

    habitat = subparsers.add_parser("habitat", help="Extract office_0 from supplemental Habitat ZIP")
    habitat.add_argument("--zip-path", type=Path, required=True)
    habitat.add_argument("--scene-dir", type=Path, required=True)
    _add_json_out(habitat)
    habitat.set_defaults(handler=_habitat_command)

    scene = subparsers.add_parser("scene", help="Verify required extracted office_0 files")
    scene.add_argument("--scene-dir", type=Path, required=True)
    _add_json_out(scene)
    scene.set_defaults(handler=_scene_command)

    report = subparsers.add_parser("report", help="Write the Markdown download report")
    report.add_argument("--download-dir", type=Path, required=True)
    report.add_argument("--scene-dir", type=Path, required=True)
    report.add_argument("--report-path", type=Path, required=True)
    report.set_defaults(handler=_report_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
