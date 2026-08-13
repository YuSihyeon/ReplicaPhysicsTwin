"""Sparse, explainable object candidate recognition for Replica scenes.

The first experiment deliberately uses only semantic metadata and geometry.
It does not use RGB images, texture classification, or an external vision model.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence


def _normalise_text(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").replace("-", " ").split())


def _as_float_list(value: Any, length: int, field: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"{field} must contain exactly {length} numbers")
    result = [float(component) for component in value]
    if not all(math.isfinite(component) for component in result):
        raise ValueError(f"{field} must contain only finite numbers")
    return result


def _record_bbox(record: Mapping[str, Any]) -> tuple[list[float], list[float]]:
    try:
        abb = record["oriented_bbox"]["abb"]
        return (
            _as_float_list(abb["center"], 3, "oriented_bbox.abb.center"),
            _as_float_list(abb["sizes"], 3, "oriented_bbox.abb.sizes"),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("object record is missing oriented_bbox.abb") from exc


def _candidate_role_map(scene_manifest: Mapping[str, Any]) -> dict[int, str]:
    roles: dict[int, str] = {}
    for role, object_ids in dict(scene_manifest.get("candidate_object_ids", {})).items():
        if not isinstance(object_ids, Sequence) or isinstance(object_ids, (str, bytes)):
            continue
        for object_id in object_ids:
            try:
                roles[int(object_id)] = str(role)
            except (TypeError, ValueError):
                continue
    return roles


def _support_proxy_for(object_id: int, role: str, scene_manifest: Mapping[str, Any]) -> str | None:
    if role == "tissue_box":
        return "desk_58"
    support_map = scene_manifest.get("support_proxy_by_object_id", {})
    if isinstance(support_map, Mapping):
        value = support_map.get(str(object_id), support_map.get(object_id))
        if value is not None:
            return str(value)
    return None


def extract_sparse_object_features(
    scene_manifest: Mapping[str, Any],
    semantic_summary: Mapping[str, Any],
    semantic_mesh_path: Path,
) -> list[dict[str, Any]]:
    """Extract recognition features without loading RGB or texture data."""

    semantic_mesh_path = Path(semantic_mesh_path)
    if not semantic_mesh_path.exists():
        raise FileNotFoundError(semantic_mesh_path)

    id_counts = (
        semantic_summary.get("semantic_mesh_instance_mapping", {}).get("id_counts", {})
        if isinstance(semantic_summary.get("semantic_mesh_instance_mapping", {}), Mapping)
        else {}
    )
    roles = _candidate_role_map(scene_manifest)
    features: list[dict[str, Any]] = []
    for record in scene_manifest.get("object_records", []):
        if not isinstance(record, Mapping):
            continue
        try:
            object_id = int(record["id"])
        except (KeyError, TypeError, ValueError):
            continue
        class_name = str(record.get("class_name", "unknown"))
        if _normalise_text(class_name) in {"undefined", "unknown"}:
            continue
        center_m, size_m = _record_bbox(record)
        face_count = int(id_counts.get(str(object_id), id_counts.get(object_id, 0)))
        role = roles.get(object_id)
        features.append(
            {
                "object_id": object_id,
                "class_name": class_name,
                "center_m": center_m,
                "size_m": size_m,
                "face_count": face_count,
                "role": role,
                "support_proxy": _support_proxy_for(object_id, role or "", scene_manifest),
            }
        )
    return sorted(features, key=lambda item: int(item["object_id"]))


def _size_score(size_m: Sequence[float], ranges: Any) -> tuple[float, list[str]]:
    if not isinstance(ranges, (list, tuple)) or len(ranges) != 3:
        return 0.0, []
    matches = 0
    for value, bounds in zip(size_m, ranges):
        if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
            low, high = float(bounds[0]), float(bounds[1])
            if low <= float(value) <= high:
                matches += 1
    if matches == 3:
        return 0.25, ["size_within_target_range"]
    if matches == 2:
        return 0.12, [f"size_matches_{matches}_of_3_axes"]
    return 0.0, []


def rank_object_candidates(
    features: Sequence[Mapping[str, Any]],
    target: str,
    aliases: Mapping[str, Sequence[str]],
    target_priors: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rank object candidates and retain human-readable evidence."""

    target_key = str(target)
    target_tokens = {_normalise_text(target_key)}
    target_tokens.update(_normalise_text(alias) for alias in aliases.get(target_key, []))
    prior = target_priors.get(target_key, {})
    support_roles = {_normalise_text(role) for role in prior.get("support_roles", [])}
    ranked: list[dict[str, Any]] = []

    for feature in features:
        class_name = _normalise_text(feature.get("class_name", ""))
        evidence: list[str] = []
        score = 0.0
        if class_name in target_tokens:
            score += 0.60
            evidence.append("semantic_class_exact_or_alias")
        elif any(token and token in class_name for token in target_tokens):
            score += 0.35
            evidence.append("semantic_class_partial_alias")

        size_points, size_evidence = _size_score(feature.get("size_m", []), prior.get("size_m_range"))
        score += size_points
        evidence.extend(size_evidence)

        role = _normalise_text(feature.get("role", ""))
        support_proxy = _normalise_text(feature.get("support_proxy", ""))
        if role in support_roles or support_proxy in support_roles:
            score += 0.10
            evidence.append("supported_by_expected_surface")
        if int(feature.get("face_count", 0)) > 0:
            score += 0.05
            evidence.append("semantic_mesh_faces_present")

        ranked.append(
            {
                "object_id": int(feature["object_id"]),
                "class_name": str(feature.get("class_name", "")),
                "score": round(min(score, 1.0), 6),
                "evidence": evidence,
                "features": dict(feature),
            }
        )

    return sorted(ranked, key=lambda item: (-float(item["score"]), int(item["object_id"])))


def recognize_object(
    features: Sequence[Mapping[str, Any]],
    target: str,
    aliases: Mapping[str, Sequence[str]],
    target_priors: Mapping[str, Mapping[str, Any]],
    min_confidence: float = 0.75,
) -> dict[str, Any]:
    """Select a candidate only when sparse evidence is sufficiently clear."""

    candidates = rank_object_candidates(features, target, aliases, target_priors)
    if not candidates:
        return {
            "target": str(target),
            "status": "not_present",
            "selected_object_id": None,
            "requires_user_confirmation": False,
            "candidates": [],
        }

    top = candidates[0]
    next_score = float(candidates[1]["score"]) if len(candidates) > 1 else -1.0
    ambiguous_margin = 0.05
    is_ambiguous = float(top["score"]) < float(min_confidence) or next_score >= float(top["score"]) - ambiguous_margin
    return {
        "target": str(target),
        "status": "ambiguous" if is_ambiguous else "selected",
        "selected_object_id": None if is_ambiguous else int(top["object_id"]),
        "requires_user_confirmation": bool(is_ambiguous),
        "candidates": candidates,
    }
