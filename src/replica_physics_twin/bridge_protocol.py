"""Validated newline-delimited JSON messages for the MuJoCo bridge."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any, Iterable


SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, SCHEMA_VERSION})
MAX_MESSAGE_BYTES = 1_000_000


class ProtocolError(ValueError):
    """Raised when a bridge message violates the wire contract."""


def _require_mapping(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise ProtocolError("message must be a JSON object")
    return message


def _require_schema(message: dict[str, Any], expected_type: str) -> int:
    if message.get("type") != expected_type:
        raise ProtocolError(f"message type must be {expected_type!r}")
    version = message.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ProtocolError(f"schema_version must be one of {sorted(SUPPORTED_SCHEMA_VERSIONS)}")
    return version


def _require_nonnegative_int(message: dict[str, Any], field: str) -> int:
    value = message.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProtocolError(f"{field} must be a non-negative integer")
    return value


def _require_finite_number(message: dict[str, Any], field: str, *, nonnegative: bool = False) -> float:
    value = message.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ProtocolError(f"{field} must be a finite number")
    number = float(value)
    if nonnegative and number < 0.0:
        raise ProtocolError(f"{field} must be non-negative")
    return number


def _require_vector(value: Any, field: str, length: int) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ProtocolError(f"{field} must contain exactly {length} numbers")
    vector = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise ProtocolError(f"{field} must contain only numbers")
        number = float(component)
        if not math.isfinite(number):
            raise ProtocolError(f"{field} must contain only finite numbers")
        vector.append(number)
    return vector


def _validate_object_properties(properties: Any, index: int) -> None:
    if not isinstance(properties, Mapping):
        raise ProtocolError(f"objects[{index}].properties must be an object")
    for field in ("size_m", "inertia_diagonal_kg_m2"):
        if field in properties:
            _require_vector(properties[field], f"objects[{index}].properties.{field}", 3)
    if "mass_kg" in properties:
        value = properties["mass_kg"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0.0:
            raise ProtocolError(f"objects[{index}].properties.mass_kg must be a non-negative finite number")
    if "movable" in properties and not isinstance(properties["movable"], bool):
        raise ProtocolError(f"objects[{index}].properties.movable must be a boolean")
    friction = properties.get("friction")
    if friction is not None:
        if not isinstance(friction, Mapping):
            raise ProtocolError(f"objects[{index}].properties.friction must be an object")
        for name in ("sliding", "torsional", "rolling"):
            if name in friction:
                value = friction[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0.0:
                    raise ProtocolError(f"objects[{index}].properties.friction.{name} must be non-negative and finite")


def _validate_contacts(contacts: Any, index: int) -> None:
    if not isinstance(contacts, list):
        raise ProtocolError(f"objects[{index}].contacts must be an array")
    for contact_index, contact in enumerate(contacts):
        if not isinstance(contact, Mapping):
            raise ProtocolError(f"objects[{index}].contacts[{contact_index}] must be an object")
        other_id = contact.get("other_id")
        if not isinstance(other_id, str) or not other_id.strip():
            raise ProtocolError(f"objects[{index}].contacts[{contact_index}].other_id must be a non-empty string")
        _require_vector(contact.get("force_n"), f"objects[{index}].contacts[{contact_index}].force_n", 3)
        if "distance_m" in contact:
            distance = contact["distance_m"]
            if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(float(distance)):
                raise ProtocolError(f"objects[{index}].contacts[{contact_index}].distance_m must be finite")


def _validate_object_state(object_state: Any, index: int) -> None:
    if not isinstance(object_state, dict):
        raise ProtocolError(f"objects[{index}] must be an object")
    object_id = object_state.get("id")
    if not isinstance(object_id, str) or not object_id.strip():
        raise ProtocolError(f"objects[{index}].id must be a non-empty string")
    _require_vector(object_state.get("position_m"), f"objects[{index}].position_m", 3)
    _require_vector(object_state.get("quaternion_wxyz"), f"objects[{index}].quaternion_wxyz", 4)
    _require_vector(object_state.get("linear_velocity_mps"), f"objects[{index}].linear_velocity_mps", 3)
    _require_vector(object_state.get("angular_velocity_rps"), f"objects[{index}].angular_velocity_rps", 3)
    if "source_object_id" in object_state:
        source_object_id = object_state["source_object_id"]
        if isinstance(source_object_id, bool) or not isinstance(source_object_id, int) or source_object_id < 0:
            raise ProtocolError(f"objects[{index}].source_object_id must be a non-negative integer")
    if "role" in object_state and object_state["role"] is not None:
        if not isinstance(object_state["role"], str) or not object_state["role"].strip():
            raise ProtocolError(f"objects[{index}].role must be a non-empty string")
    if "contacts" in object_state:
        _validate_contacts(object_state["contacts"], index)
    if "properties" in object_state:
        _validate_object_properties(object_state["properties"], index)
    if "deformed_vertices_m" in object_state:
        vertices = object_state["deformed_vertices_m"]
        if not isinstance(vertices, list) or not vertices:
            raise ProtocolError(f"objects[{index}].deformed_vertices_m must be a non-empty array")
        if len(vertices) > 10000:
            raise ProtocolError(f"objects[{index}].deformed_vertices_m exceeds the 10000 vertex limit")
        for vertex_index, vertex in enumerate(vertices):
            _require_vector(
                vertex,
                f"objects[{index}].deformed_vertices_m[{vertex_index}]",
                3,
            )


def validate_state_message(message: Any) -> dict[str, Any]:
    message = _require_mapping(message)
    schema_version = _require_schema(message, "state")
    _require_nonnegative_int(message, "seq")
    _require_finite_number(message, "sim_time", nonnegative=True)
    if message.get("units") != "meter":
        raise ProtocolError("state units must be 'meter'")
    if message.get("up_axis") != "Z":
        raise ProtocolError("state up_axis must be 'Z'")
    if schema_version >= 2:
        if message.get("physics_authority") != "MuJoCo":
            raise ProtocolError("schema v2 state physics_authority must be 'MuJoCo'")
        if not isinstance(message.get("scene_id"), str) or not message["scene_id"].strip():
            raise ProtocolError("schema v2 state scene_id must be a non-empty string")
    objects = message.get("objects")
    if not isinstance(objects, list):
        raise ProtocolError("objects must be a list")
    object_ids: set[str] = set()
    for index, object_state in enumerate(objects):
        _validate_object_state(object_state, index)
        object_id = object_state["id"]
        if object_id in object_ids:
            raise ProtocolError(f"duplicate object id: {object_id}")
        object_ids.add(object_id)
    return message


def validate_command_message(
    message: Any,
    *,
    known_object_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    message = _require_mapping(message)
    schema_version = _require_schema(message, "command")
    command = message.get("command")
    if command not in {"apply_impulse", "reset", "pause", "lift_drop", "grab_begin", "grab_update", "grab_end"}:
        raise ProtocolError("unsupported command")
    known_ids = set(known_object_ids) if known_object_ids is not None else None
    if command == "apply_impulse":
        object_id = message.get("object_id")
        if not isinstance(object_id, str) or not object_id.strip():
            raise ProtocolError("apply_impulse requires a non-empty object_id")
        if known_ids is not None and object_id not in known_ids:
            raise ProtocolError(f"unknown object_id: {object_id}")
        _require_vector(message.get("impulse_ns"), "impulse_ns", 3)
        if "point_m" in message and message["point_m"] is not None:
            _require_vector(message["point_m"], "point_m", 3)
    elif command == "pause":
        if not isinstance(message.get("paused"), bool):
            raise ProtocolError("pause requires a boolean paused field")
    elif command == "lift_drop":
        object_id = message.get("object_id")
        if not isinstance(object_id, str) or not object_id.strip():
            raise ProtocolError("lift_drop requires a non-empty object_id")
        if known_ids is not None and object_id not in known_ids:
            raise ProtocolError(f"unknown object_id: {object_id}")
        lift_height_m = _require_finite_number(message, "lift_height_m", nonnegative=True)
        if lift_height_m > 1.0:
            raise ProtocolError("lift_height_m must be at most 1 meter")
    elif command == "grab_begin":
        if schema_version < 2:
            raise ProtocolError("grab_begin requires schema_version 2")
        object_ids = message.get("object_ids")
        if not isinstance(object_ids, list) or not object_ids:
            raise ProtocolError("grab_begin requires a non-empty object_ids array")
        if len(set(object_ids)) != len(object_ids):
            raise ProtocolError("grab_begin object_ids must be unique")
        for object_id in object_ids:
            if not isinstance(object_id, str) or not object_id.strip():
                raise ProtocolError("grab_begin object_ids must contain non-empty strings")
            if known_ids is not None and object_id not in known_ids:
                raise ProtocolError(f"unknown object_id: {object_id}")
        _require_vector(message.get("anchor_m"), "anchor_m", 3)
        if "target_position_m" in message:
            _require_vector(message["target_position_m"], "target_position_m", 3)
        if "target_quaternion_wxyz" in message:
            _require_vector(message["target_quaternion_wxyz"], "target_quaternion_wxyz", 4)
        if "client_grab_id" in message:
            client_grab_id = message["client_grab_id"]
            if not isinstance(client_grab_id, str) or not client_grab_id.strip():
                raise ProtocolError("client_grab_id must be a non-empty string")
    elif command == "grab_update":
        if schema_version < 2:
            raise ProtocolError("grab_update requires schema_version 2")
        grab_id = message.get("grab_id")
        if not isinstance(grab_id, str) or not grab_id.strip():
            raise ProtocolError("grab_update requires a non-empty grab_id")
        _require_vector(message.get("target_position_m"), "target_position_m", 3)
        if "target_quaternion_wxyz" in message:
            _require_vector(message["target_quaternion_wxyz"], "target_quaternion_wxyz", 4)
    elif command == "grab_end":
        if schema_version < 2:
            raise ProtocolError("grab_end requires schema_version 2")
        grab_id = message.get("grab_id")
        if not isinstance(grab_id, str) or not grab_id.strip():
            raise ProtocolError("grab_end requires a non-empty grab_id")
    return message


def build_state_message(
    seq: int,
    sim_time: float,
    objects: list[dict[str, Any]],
    *,
    scene_id: str = "office_0",
    physics_authority: str = "MuJoCo",
) -> dict[str, Any]:
    message = {
        "type": "state",
        "schema_version": SCHEMA_VERSION,
        "seq": int(seq),
        "sim_time": float(sim_time),
        "units": "meter",
        "up_axis": "Z",
        "physics_authority": physics_authority,
        "scene_id": scene_id,
        "objects": objects,
    }
    return validate_state_message(message)


def build_ack_message(
    seq: int,
    sim_time: float,
    command: str,
    object_id: str | None = None,
    *,
    grab_id: str | None = None,
    object_ids: list[str] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": "ack",
        "schema_version": SCHEMA_VERSION,
        "seq": int(seq),
        "sim_time": float(sim_time),
        "command": command,
    }
    if object_id is not None:
        message["object_id"] = object_id
    if grab_id is not None:
        message["grab_id"] = grab_id
    if object_ids is not None:
        message["object_ids"] = list(object_ids)
    return message


def build_error_message(seq: int, sim_time: float, error_code: str, message_text: str) -> dict[str, Any]:
    return {
        "type": "error",
        "schema_version": SCHEMA_VERSION,
        "seq": int(seq),
        "sim_time": float(sim_time),
        "error_code": error_code,
        "message": message_text,
    }


def decode_message_line(line: str | bytes) -> dict[str, Any]:
    if isinstance(line, bytes):
        if len(line) > MAX_MESSAGE_BYTES:
            raise ProtocolError("message exceeds maximum size")
        try:
            line = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("message must be UTF-8") from exc
    if not isinstance(line, str):
        raise ProtocolError("message line must be text or bytes")
    if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message exceeds maximum size")
    try:
        decoded = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError("message is not valid JSON") from exc
    return _require_mapping(decoded)


def encode_message(message: dict[str, Any]) -> str:
    if message.get("type") == "state":
        validate_state_message(message)
    elif message.get("type") == "command":
        validate_command_message(message)
    try:
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("message contains a value that cannot be encoded") from exc
    if len(encoded.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message exceeds maximum size")
    return encoded + "\n"
