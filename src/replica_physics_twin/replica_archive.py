"""Validation and selective extraction helpers for the official Replica v1 archive."""

from __future__ import annotations

import io
import tarfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import BinaryIO


_PART_PREFIX = "replica_v1_0.tar.gz.parta"
_FINAL_PART_SIZE = 1_859_047_808
_REQUIRED_OFFICE0_FILES = (
    "mesh.ply",
    "semantic.json",
    "habitat/mesh_semantic.ply",
    "habitat/info_semantic.json",
)


def expected_part_sizes() -> dict[str, int]:
    """Return names and byte sizes published on the official v1.0 release."""

    result = {f"{_PART_PREFIX}{letter}": 2_000_000_000 for letter in "abcdefghijklmnop"}
    result[f"{_PART_PREFIX}q"] = _FINAL_PART_SIZE
    return result


def verify_parts(download_dir: Path) -> dict[str, object]:
    """Compare local split archives with the official names and sizes."""

    expected = expected_part_sizes()
    missing: list[str] = []
    wrong_sizes: dict[str, dict[str, int]] = {}
    present_bytes = 0
    for name, expected_size in expected.items():
        path = download_dir / name
        if not path.is_file():
            missing.append(name)
            continue
        actual_size = path.stat().st_size
        present_bytes += actual_size
        if actual_size != expected_size:
            wrong_sizes[name] = {"expected": expected_size, "actual": actual_size}
    return {
        "complete": not missing and not wrong_sizes,
        "missing": missing,
        "wrong_sizes": wrong_sizes,
        "present_bytes": present_bytes,
        "expected_bytes": sum(expected.values()),
    }


def office0_relative_path(member_name: str) -> Path | None:
    """Map an archive member containing office_0 to a safe scene-relative path."""

    if "\\" in member_name:
        raise ValueError(f"Backslashes are not allowed in archive paths: {member_name}")
    source = PurePosixPath(member_name)
    if source.is_absolute() or ".." in source.parts:
        raise ValueError(f"Unsafe archive path: {member_name}")
    try:
        office_index = source.parts.index("office_0")
    except ValueError:
        return None
    if office_index == len(source.parts) - 1:
        return Path()
    return Path(*source.parts[office_index + 1 :])


class _MultiPartReader(io.RawIOBase):
    def __init__(self, part_paths: Sequence[Path]) -> None:
        if not part_paths:
            raise ValueError("At least one archive part is required")
        self._paths = list(part_paths)
        self._index = 0
        self._current: BinaryIO | None = None

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray) -> int:
        view = memoryview(buffer)
        written = 0
        while written < len(view):
            if self._current is None:
                if self._index >= len(self._paths):
                    break
                self._current = self._paths[self._index].open("rb")
                self._index += 1
            count = self._current.readinto(view[written:])
            if count:
                written += count
            else:
                self._current.close()
                self._current = None
        return written

    def close(self) -> None:
        if self._current is not None:
            self._current.close()
            self._current = None
        super().close()


def extract_office0(part_paths: Sequence[Path], output_scene_dir: Path) -> dict[str, object]:
    """Stream split gzip parts and extract regular office_0 files only."""

    files_extracted = 0
    files_skipped = 0
    archive_prefix: str | None = None
    output_scene_dir.mkdir(parents=True, exist_ok=True)
    raw_reader = _MultiPartReader(part_paths)
    with io.BufferedReader(raw_reader, buffer_size=1024 * 1024) as stream:
        with tarfile.open(fileobj=stream, mode="r|gz") as archive:
            for member in archive:
                relative = office0_relative_path(member.name)
                if relative is None:
                    continue
                source_parts = PurePosixPath(member.name).parts
                office_index = source_parts.index("office_0")
                archive_prefix = "/".join(source_parts[: office_index + 1])
                if not relative.parts:
                    continue
                destination = output_scene_dir / relative
                resolved_destination = destination.resolve()
                resolved_root = output_scene_dir.resolve()
                if resolved_root not in resolved_destination.parents:
                    raise ValueError(f"Archive member escapes output root: {member.name}")
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    files_skipped += 1
                    continue
                if destination.exists():
                    if destination.is_file() and destination.stat().st_size == member.size:
                        files_skipped += 1
                        continue
                    raise FileExistsError(f"Refusing to overwrite mismatched file: {destination}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                source_file = archive.extractfile(member)
                if source_file is None:
                    raise tarfile.ExtractError(f"Could not read archive member: {member.name}")
                with source_file, destination.open("xb") as target:
                    while chunk := source_file.read(1024 * 1024):
                        target.write(chunk)
                files_extracted += 1
    if archive_prefix is None:
        raise FileNotFoundError("No office_0 path was found in the Replica archive")
    return {
        "archive_prefix": archive_prefix,
        "files_extracted": files_extracted,
        "files_skipped": files_skipped,
    }


def extract_office0_zip(zip_path: Path, output_scene_dir: Path) -> dict[str, object]:
    """Extract only office_0 regular files from an official supplemental ZIP."""

    files_extracted = 0
    files_skipped = 0
    prefixes: set[str] = set()
    output_scene_dir.mkdir(parents=True, exist_ok=True)
    resolved_root = output_scene_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            relative = office0_relative_path(member.filename)
            if relative is None or not relative.parts:
                continue
            source_parts = PurePosixPath(member.filename).parts
            office_index = source_parts.index("office_0")
            prefixes.add("/".join(source_parts[: office_index + 1]))
            destination = output_scene_dir / relative
            resolved_destination = destination.resolve()
            if resolved_root not in resolved_destination.parents:
                raise ValueError(f"ZIP member escapes output root: {member.filename}")
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if destination.exists():
                if destination.is_file() and destination.stat().st_size == member.file_size:
                    files_skipped += 1
                    continue
                raise FileExistsError(f"Refusing to overwrite mismatched file: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("xb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            files_extracted += 1
    if not prefixes:
        raise FileNotFoundError("No office_0 path was found in the supplemental ZIP")
    return {
        "archive_prefixes": sorted(prefixes),
        "files_extracted": files_extracted,
        "files_skipped": files_skipped,
    }


def verify_office0(scene_dir: Path) -> dict[str, object]:
    """Check required office_0 files and summarize the extracted tree."""

    missing = [name for name in _REQUIRED_OFFICE0_FILES if not (scene_dir / name).is_file()]
    files = [path for path in scene_dir.rglob("*") if path.is_file()] if scene_dir.is_dir() else []
    return {
        "complete": not missing,
        "missing": missing,
        "file_count": len(files),
        "total_bytes": sum(path.stat().st_size for path in files),
        "required_files": {
            name: (scene_dir / name).stat().st_size
            for name in _REQUIRED_OFFICE0_FILES
            if (scene_dir / name).is_file()
        },
    }
