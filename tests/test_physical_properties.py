from __future__ import annotations

import pytest

from replica_physics_twin.physical_properties import (
    build_physical_manifest,
    compute_box_inertia_diagonal,
    resolve_object_properties,
)


def _priors() -> dict:
    return {
        "defaults": {
            "density_kg_m3": 700.0,
            "fill_factor": 0.5,
            "sliding_friction": 0.45,
            "torsional_friction": 0.005,
            "rolling_friction": 0.001,
            "restitution": 0.05,
            "confidence": "low",
            "source": "test_prior",
            "is_measured": False,
        },
        "materials": {
            "tissue-paper": {
                "density_kg_m3": 500.0,
                "fill_factor": 0.4,
                "sliding_friction": 0.35,
            }
        },
    }


def test_box_inertia_uses_measured_size_and_mass() -> None:
    inertia = compute_box_inertia_diagonal(2.0, [2.0, 3.0, 4.0])

    assert inertia == pytest.approx([25.0 / 6.0, 10.0 / 3.0, 13.0 / 6.0])


def test_measured_override_wins_and_keeps_provenance() -> None:
    result = resolve_object_properties(
        {"id": 28, "class_name": "tissue-paper", "role": "tissue_box"},
        {"size_m": [0.2, 0.1, 0.3]},
        _priors(),
        {
            "user": {"28": {"mass_kg": 0.3, "sliding_friction": 0.9}},
            "measured": {"28": {"mass_kg": 0.4}},
        },
    )

    assert result["mass_kg"] == pytest.approx(0.4)
    assert result["friction"]["sliding"] == pytest.approx(0.9)
    assert result["provenance"]["mass_kg"]["source"] == "measured_override"
    assert result["provenance"]["friction.sliding"]["source"] == "user_override"
    assert result["movable"] is True
    assert result["body_type"] == "dynamic"


def test_static_environment_record_is_not_movable() -> None:
    result = resolve_object_properties(
        {"id": 58, "class_name": "table", "role": "desk"},
        {"size_m": [1.0, 1.0, 0.1]},
        _priors(),
        {},
    )

    assert result["movable"] is False
    assert result["body_type"] == "static"
    assert result["mass_kg"] == 0.0


def test_manifest_contains_dynamic_and_static_physics_records() -> None:
    manifest = build_physical_manifest(
        {
            "scene_id": "office_0",
            "object_records": [
                {"id": 28, "class_name": "tissue-paper", "role": "tissue_box"},
                {"id": 58, "class_name": "table", "role": "desk"},
            ],
        },
        {
            "28": {"size_m": [0.2, 0.1, 0.3]},
            "58": {"size_m": [1.0, 1.0, 0.1]},
        },
        _priors(),
        {},
    )

    assert manifest["physics_authority"] == "MuJoCo"
    assert [record["body_type"] for record in manifest["objects"]] == ["dynamic", "static"]
