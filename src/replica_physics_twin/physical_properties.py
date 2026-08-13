"""Resolve physical properties from measured geometry and explicit priors.

The resolver keeps a provenance entry for every value that can affect the
MuJoCo model.  It intentionally does not pretend that Replica semantic data
contains measured mass or material parameters.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


STATIC_ROLES = frozenset({"floor", "wall", "ceiling", "desk", "table", "room"})
DYNAMIC_ROLES = frozenset(
    {
        "tissue_box",
        "book",
        "cup",
        "pc",
        "keyboard",
        "mouse",
        "dynamic_object",
    }
)
FRICTION_FIELDS = {
    "sliding": "sliding_friction",
    "torsional": "torsional_friction",
    "rolling": "rolling_friction",
}


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").replace("-", " ").split())


def _finite_float(value: Any, field: str, *, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return result


def _size_m_from_geometry(object_record: Mapping[str, Any], geometry: Mapping[str, Any]) -> tuple[list[float], str]:
    if "size_m" in geometry:
        values = geometry["size_m"]
        source = "geometry.size_m"
    elif "size_m" in object_record:
        values = object_record["size_m"]
        source = "object_record.size_m"
    else:
        bbox = geometry.get("oriented_bbox", object_record.get("oriented_bbox", {}))
        abb = bbox.get("abb", {}) if isinstance(bbox, Mapping) else {}
        values = abb.get("sizes")
        source = "oriented_bbox.abb.sizes"
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or len(values) != 3:
        raise ValueError("geometry must provide size_m or oriented_bbox.abb.sizes with three values")
    size_m = [_finite_float(value, "size_m", minimum=0.0) for value in values]
    if any(value <= 0.0 for value in size_m):
        raise ValueError("size_m values must be > 0")
    return size_m, source


def _object_id(object_record: Mapping[str, Any]) -> int:
    try:
        return int(object_record["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("object record must contain an integer id") from exc


def _lookup(mapping: Mapping[str, Any], key: Any) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    if key in mapping:
        return mapping[key]
    text_key = str(key)
    if text_key in mapping:
        return mapping[text_key]
    return None


def _material_prior(
    object_record: Mapping[str, Any],
    material_priors: Mapping[str, Any],
) -> Mapping[str, Any]:
    materials = material_priors.get("materials", {})
    class_name = str(object_record.get("class_name", "unknown"))
    if isinstance(materials, Mapping):
        exact = _lookup(materials, class_name)
        if isinstance(exact, Mapping):
            return exact
        wanted = _normalise(class_name)
        for name, value in materials.items():
            if _normalise(name) == wanted and isinstance(value, Mapping):
                return value
    defaults = material_priors.get("defaults", {})
    return defaults if isinstance(defaults, Mapping) else {}


def _override_bucket(overrides: Mapping[str, Any], source: str) -> Mapping[str, Any]:
    value = overrides.get(source, {}) if isinstance(overrides, Mapping) else {}
    return value if isinstance(value, Mapping) else {}


def _object_override(
    overrides: Mapping[str, Any],
    source: str,
    object_record: Mapping[str, Any],
) -> Mapping[str, Any]:
    bucket = _override_bucket(overrides, source)
    object_id = _object_id(object_record)
    value = _lookup(bucket, object_id)
    if value is None:
        value = _lookup(bucket, object_record.get("class_name", ""))
    if value is None:
        value = _lookup(bucket, object_record.get("role", ""))
    return value if isinstance(value, Mapping) else {}


def _field_value(
    field: str,
    *,
    measured: Mapping[str, Any],
    user: Mapping[str, Any],
    material: Mapping[str, Any],
    fallback: Any,
) -> tuple[Any, str]:
    for source, values in (
        ("measured_override", measured),
        ("user_override", user),
        ("material_prior", material),
    ):
        if field in values:
            return values[field], source
    return fallback, "mvp_estimate"


def compute_box_inertia_diagonal(mass_kg: float, size_m: Sequence[float]) -> list[float]:
    """Return the principal inertia diagonal of a uniform box at its center."""

    mass = _finite_float(mass_kg, "mass_kg", minimum=0.0)
    if not isinstance(size_m, Sequence) or isinstance(size_m, (str, bytes)) or len(size_m) != 3:
        raise ValueError("size_m must contain exactly three values")
    x, y, z = (_finite_float(value, "size_m", minimum=0.0) for value in size_m)
    if min(x, y, z) <= 0.0:
        raise ValueError("size_m values must be > 0")
    return [
        mass * (y * y + z * z) / 12.0,
        mass * (x * x + z * z) / 12.0,
        mass * (x * x + y * y) / 12.0,
    ]


def resolve_object_properties(
    object_record: Mapping[str, Any],
    geometry: Mapping[str, Any],
    material_priors: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve one object using measured > user > prior > MVP precedence."""

    object_id = _object_id(object_record)
    size_m, size_source = _size_m_from_geometry(object_record, geometry)
    volume_m3 = size_m[0] * size_m[1] * size_m[2]
    material = _material_prior(object_record, material_priors)
    measured = _object_override(overrides, "measured", object_record)
    user = _object_override(overrides, "user", object_record)
    raw_role = object_record.get("role")
    role = str(raw_role) if raw_role else None

    density, density_source = _field_value(
        "density_kg_m3",
        measured=measured,
        user=user,
        material=material,
        fallback=1000.0,
    )
    density = _finite_float(density, "density_kg_m3", minimum=0.0)
    fill_factor, fill_factor_source = _field_value(
        "fill_factor",
        measured=measured,
        user=user,
        material=material,
        fallback=1.0,
    )
    fill_factor = _finite_float(fill_factor, "fill_factor", minimum=0.0)
    if fill_factor > 1.0:
        raise ValueError("fill_factor must be <= 1")

    # Sparse recognition only promotes explicitly known movable roles.  An
    # unknown semantic object stays out of the dynamic simulation until the
    # user selects it or an explicit override promotes it.
    default_movable = role in DYNAMIC_ROLES and role not in STATIC_ROLES
    movable_value, movable_source = _field_value(
        "movable",
        measured=measured,
        user=user,
        material=material,
        fallback=default_movable,
    )
    movable = bool(movable_value)
    body_type = "dynamic" if movable else "static"

    estimated_mass = density * volume_m3 * fill_factor
    mass_value, mass_source = _field_value(
        "mass_kg",
        measured=measured,
        user=user,
        material=material,
        fallback=estimated_mass,
    )
    mass_kg = _finite_float(mass_value, "mass_kg", minimum=0.0) if movable else 0.0
    inertia = compute_box_inertia_diagonal(mass_kg, size_m)

    friction: dict[str, float] = {}
    provenance: dict[str, dict[str, Any]] = {
        "size_m": {"source": size_source, "is_measured": size_source != "object_record.size_m"},
        "density_kg_m3": {"source": density_source, "is_measured": density_source == "measured_override"},
        "fill_factor": {"source": fill_factor_source, "is_measured": fill_factor_source == "measured_override"},
        "mass_kg": {
            "source": mass_source,
            "is_measured": mass_source == "measured_override",
            "basis": "density * volume * fill_factor" if mass_source == "mvp_estimate" else None,
        },
        "inertia_diagonal_kg_m2": {
            "source": "derived_from_mass_kg_and_size_m",
            "is_measured": False,
        },
        "movable": {"source": movable_source, "is_measured": movable_source == "measured_override"},
    }
    for output_name, input_name in FRICTION_FIELDS.items():
        value, source = _field_value(
            input_name,
            measured=measured,
            user=user,
            material=material,
            fallback=0.0,
        )
        friction[output_name] = _finite_float(value, input_name, minimum=0.0)
        provenance[f"friction.{output_name}"] = {
            "source": source,
            "is_measured": source == "measured_override",
        }

    restitution, restitution_source = _field_value(
        "restitution",
        measured=measured,
        user=user,
        material=material,
        fallback=0.0,
    )
    restitution = _finite_float(restitution, "restitution", minimum=0.0)
    if restitution > 1.0:
        raise ValueError("restitution must be <= 1")
    provenance["restitution"] = {
        "source": restitution_source,
        "is_measured": restitution_source == "measured_override",
    }

    return {
        "object_id": object_id,
        "class_name": str(object_record.get("class_name", "unknown")),
        "role": role,
        "body_type": body_type,
        "movable": movable,
        "size_m": size_m,
        "volume_m3": volume_m3,
        "density_kg_m3": density,
        "fill_factor": fill_factor,
        "mass_kg": mass_kg,
        "inertia_diagonal_kg_m2": inertia,
        "friction": friction,
        "restitution": restitution,
        "provenance": provenance,
    }


def _role_map(scene_manifest: Mapping[str, Any]) -> dict[int, str]:
    result: dict[int, str] = {}
    candidate_ids = scene_manifest.get("candidate_object_ids", {})
    if isinstance(candidate_ids, Mapping):
        for role, object_ids in candidate_ids.items():
            if not isinstance(object_ids, Sequence) or isinstance(object_ids, (str, bytes)):
                continue
            for object_id in object_ids:
                try:
                    result[int(object_id)] = str(role)
                except (TypeError, ValueError):
                    continue
    return result


def build_physical_manifest(
    scene_manifest: Mapping[str, Any],
    geometry_records: Mapping[str, Any],
    material_priors: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the physics input manifest consumed by the MuJoCo scene builder."""

    roles = _role_map(scene_manifest)
    objects: list[dict[str, Any]] = []
    for raw_record in scene_manifest.get("object_records", []):
        if not isinstance(raw_record, Mapping):
            continue
        object_id = _object_id(raw_record)
        object_record = dict(raw_record)
        object_record.setdefault("role", roles.get(object_id))
        geometry = _lookup(geometry_records, object_id)
        if not isinstance(geometry, Mapping):
            geometry = raw_record
        objects.append(resolve_object_properties(object_record, geometry, material_priors, overrides))
    objects.sort(key=lambda record: int(record["object_id"]))
    dynamic_ids = [record["object_id"] for record in objects if record["movable"]]
    static_ids = [record["object_id"] for record in objects if not record["movable"]]
    return {
        "schema_version": 1,
        "scene_id": str(scene_manifest.get("scene_id", "unknown")),
        "units": "meter",
        "up_axis": str(scene_manifest.get("up_axis", {}).get("candidate", "Z")),
        "physics_authority": "MuJoCo",
        "objects": objects,
        "dynamic_object_ids": dynamic_ids,
        "static_object_ids": static_ids,
        "source": "scene_manifest + geometry + material_priors + overrides",
    }
