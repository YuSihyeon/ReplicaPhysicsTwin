"""Build the Office 0 MuJoCo physical-property manifest."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from replica_physics_twin.physical_properties import build_physical_manifest  # noqa: E402


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"{}", "{ }"}:
        return {}
    if value == "[]":
        return []
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() in {"null", "~"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return ast.literal_eval(value)
    if (value.startswith("\"") and value.endswith("\"")) or (
        value.startswith("'") and value.endswith("'")
    ):
        return ast.literal_eval(value)
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _strip_comment(value: str) -> str:
    quote: str | None = None
    for index, character in enumerate(value):
        if character in {"'", '"'}:
            if quote == character:
                quote = None
            elif quote is None:
                quote = character
        elif character == "#" and quote is None:
            return value[:index].rstrip()
    return value.rstrip()


def load_physics_config(path: Path) -> dict[str, Any]:
    """Load the small, dependency-free YAML subset used by project configs.

    The project configuration intentionally uses only mappings, scalar lists,
    and scalar values. This keeps the pipeline runnable in the existing Python
    environment without adding a YAML runtime dependency.
    """

    raw_lines = Path(path).read_text(encoding="utf-8").splitlines()
    lines = [(len(line) - len(line.lstrip(" ")), line.strip()) for line in raw_lines]
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    block_indent: int | None = None

    for index, (indent, content) in enumerate(lines):
        if not content or content.startswith("#"):
            continue
        if block_indent is not None:
            if indent > block_indent:
                continue
            block_indent = None
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError(f"Invalid indentation in {path} line {index + 1}")
        container = stack[-1][1]
        if content.startswith("- "):
            if not isinstance(container, list):
                raise ValueError(f"List item without a list in {path} line {index + 1}")
            container.append(_parse_scalar(_strip_comment(content[2:])))
            continue
        if ":" not in content or not isinstance(container, dict):
            raise ValueError(f"Expected a mapping entry in {path} line {index + 1}")
        key, raw_value = content.split(":", 1)
        key = key.strip()
        raw_value = _strip_comment(raw_value).strip()
        if raw_value in {">-", ">", "|-", "|"}:
            container[key] = ""
            block_indent = indent
            continue
        if raw_value.strip():
            container[key] = _parse_scalar(raw_value)
            continue

        next_entry: tuple[int, str] | None = None
        for next_indent, next_content in lines[index + 1 :]:
            if next_content and not next_content.startswith("#"):
                next_entry = (next_indent, next_content)
                break
        child: Any = [] if next_entry and next_entry[0] > indent and next_entry[1].startswith("- ") else {}
        container[key] = child
        stack.append((indent, child))

    return root


def _load_json(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def run_build(*, output_path: Path) -> dict[str, Any]:
    manifest_path = PROJECT_ROOT / "data/derived/office_0/scene_manifest.json"
    material_path = PROJECT_ROOT / "configs/material_priors.yaml"
    override_path = PROJECT_ROOT / "configs/physical_overrides.yaml"
    scene_manifest = _load_json(manifest_path)
    material_priors = load_physics_config(material_path)
    overrides = load_physics_config(override_path)
    result = build_physical_manifest(scene_manifest, {}, material_priors, overrides)
    result["source_paths"] = {
        "scene_manifest": str(manifest_path.resolve()),
        "material_priors": str(material_path.resolve()),
        "physical_overrides": str(override_path.resolve()),
        "source_data_modified": False,
    }
    result["object_count"] = len(result["objects"])
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs/metadata/office0_physical_manifest.json",
    )
    args = parser.parse_args()
    result = run_build(output_path=args.output)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
