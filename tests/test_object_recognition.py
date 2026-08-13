from __future__ import annotations

from replica_physics_twin.object_recognition import recognize_object


def _candidate_features() -> list[dict]:
    return [
        {
            "object_id": 28,
            "class_name": "tissue-paper",
            "center_m": [-0.48, -0.24, 0.77],
            "size_m": [0.170, 0.151, 0.212],
            "face_count": 389,
            "support_proxy": "desk_58",
        },
        {
            "object_id": 19,
            "class_name": "bin",
            "center_m": [1.45, -0.52, -0.95],
            "size_m": [0.338, 0.375, 0.375],
            "face_count": 3959,
            "support_proxy": "floor",
        },
    ]


def test_sparse_recognition_selects_tissue_box_with_explainable_evidence() -> None:
    result = recognize_object(
        _candidate_features(),
        target="tissue_box",
        aliases={"tissue_box": ["tissue", "tissue-paper", "paper-box"]},
        target_priors={
            "tissue_box": {
                "size_m_range": [[0.12, 0.22], [0.10, 0.20], [0.15, 0.28]],
                "support_roles": ["desk", "table"],
            }
        },
    )

    assert result["status"] == "selected"
    assert result["selected_object_id"] == 28
    assert result["requires_user_confirmation"] is False
    assert result["candidates"][0]["object_id"] == 28
    assert result["candidates"][0]["evidence"]


def test_sparse_recognition_stops_when_two_candidates_are_equally_plausible() -> None:
    features = _candidate_features()
    features[1] = dict(features[0], object_id=29)

    result = recognize_object(
        features,
        target="tissue_box",
        aliases={"tissue_box": ["tissue", "tissue-paper", "paper-box"]},
        target_priors={
            "tissue_box": {
                "size_m_range": [[0.12, 0.22], [0.10, 0.20], [0.15, 0.28]],
                "support_roles": ["desk", "table"],
            }
        },
    )

    assert result["status"] == "ambiguous"
    assert result["selected_object_id"] is None
    assert result["requires_user_confirmation"] is True


def test_sparse_recognition_reports_not_present_without_candidates() -> None:
    result = recognize_object(
        [],
        target="tissue_box",
        aliases={"tissue_box": ["tissue", "tissue-paper", "paper-box"]},
        target_priors={"tissue_box": {"size_m_range": [[0.12, 0.22], [0.10, 0.20], [0.15, 0.28]]}},
    )

    assert result == {
        "target": "tissue_box",
        "status": "not_present",
        "selected_object_id": None,
        "requires_user_confirmation": False,
        "candidates": [],
    }
