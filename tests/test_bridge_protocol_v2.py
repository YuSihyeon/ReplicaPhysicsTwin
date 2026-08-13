from __future__ import annotations

import pytest

from replica_physics_twin.bridge_protocol import (
    ProtocolError,
    build_state_message,
    encode_message,
    validate_command_message,
    validate_state_message,
)


def _object_state(object_id: str) -> dict:
    return {
        "id": object_id,
        "source_object_id": 28 if object_id == "tissue_box" else 44,
        "role": "tissue_box" if object_id == "tissue_box" else "dynamic_object",
        "position_m": [0.0, 0.0, 0.7],
        "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        "linear_velocity_mps": [0.0, 0.0, 0.0],
        "angular_velocity_rps": [0.0, 0.0, 0.0],
        "contacts": [{"other_id": "desk_58", "force_n": [0.0, 0.0, 1.2]}],
        "properties": {
            "size_m": [0.2, 0.1, 0.2],
            "mass_kg": 0.5,
            "inertia_diagonal_kg_m2": [0.003, 0.003, 0.003],
            "friction": {"sliding": 0.5, "torsional": 0.005, "rolling": 0.001},
            "movable": True,
        },
    }


def test_v2_state_carries_authority_contact_and_physical_properties() -> None:
    message = build_state_message(
        seq=12,
        sim_time=0.024,
        objects=[_object_state("tissue_box"), _object_state("desk_organizer")],
        scene_id="office_0",
    )

    assert message["schema_version"] == 2
    assert message["physics_authority"] == "MuJoCo"
    assert message["scene_id"] == "office_0"
    assert message["objects"][0]["contacts"][0]["other_id"] == "desk_58"
    validate_state_message(message)
    assert '"schema_version":2' in encode_message(message)


def test_v2_group_grab_commands_validate_object_set_and_targets() -> None:
    known = {"tissue_box", "desk_organizer"}
    begin = validate_command_message(
        {
            "type": "command",
            "schema_version": 2,
            "command": "grab_begin",
            "object_ids": ["tissue_box", "desk_organizer"],
            "anchor_m": [0.0, 0.0, 0.8],
        },
        known_object_ids=known,
    )
    assert begin["command"] == "grab_begin"

    update = validate_command_message(
        {
            "type": "command",
            "schema_version": 2,
            "command": "grab_update",
            "grab_id": "grab-1",
            "target_position_m": [0.2, 0.0, 0.9],
            "target_quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        },
        known_object_ids=known,
    )
    assert update["grab_id"] == "grab-1"

    end = validate_command_message(
        {
            "type": "command",
            "schema_version": 2,
            "command": "grab_end",
            "grab_id": "grab-1",
        },
        known_object_ids=known,
    )
    assert end["command"] == "grab_end"

    with pytest.raises(ProtocolError):
        validate_command_message(
            {
                "type": "command",
                "schema_version": 2,
                "command": "grab_begin",
                "object_ids": ["tissue_box", "tissue_box"],
                "anchor_m": [0.0, 0.0, 0.8],
            },
            known_object_ids=known,
        )
