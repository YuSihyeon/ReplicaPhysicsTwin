from __future__ import annotations

import json
import socket
import time
import unittest
from pathlib import Path

from replica_physics_twin.bridge_protocol import (
    ProtocolError,
    build_state_message,
    decode_message_line,
    encode_message,
    validate_command_message,
    validate_state_message,
)
from replica_physics_twin.bridge_server import MuJoCoBridgeServer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
XML_PATH = PROJECT_ROOT / "outputs" / "mjcf" / "phase2_box_drop.xml"
TISSUE_XML_PATH = PROJECT_ROOT / "outputs" / "mjcf" / "office0_tissue_box.xml"
TISSUE_METADATA_PATH = PROJECT_ROOT / "outputs" / "metadata" / "office0_tissue_box.json"


def _object_state() -> dict[str, object]:
    return {
        "id": "test_box",
        "position_m": [1.0, 2.0, 3.0],
        "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        "linear_velocity_mps": [0.0, 0.0, 0.0],
        "angular_velocity_rps": [0.0, 0.0, 0.0],
    }


class BridgeProtocolTests(unittest.TestCase):
    def test_state_message_round_trips_with_required_authority_fields(self) -> None:
        message = build_state_message(seq=12, sim_time=0.024, objects=[_object_state()])

        validate_state_message(message)
        decoded = decode_message_line(encode_message(message))

        self.assertEqual(decoded["type"], "state")
        self.assertEqual(decoded["schema_version"], 2)
        self.assertEqual(decoded["seq"], 12)
        self.assertEqual(decoded["sim_time"], 0.024)
        self.assertEqual(decoded["units"], "meter")
        self.assertEqual(decoded["up_axis"], "Z")
        self.assertEqual(decoded["objects"][0]["quaternion_wxyz"], [1.0, 0.0, 0.0, 0.0])

    def test_state_message_accepts_deformed_flex_vertices(self) -> None:
        message = build_state_message(
            seq=13,
            sim_time=0.026,
            objects=[
                {
                    **_object_state(),
                    "deformed_vertices_m": [[0.0, 0.0, 1.0], [0.1, 0.0, 0.9]],
                }
            ],
        )
        self.assertEqual(len(message["objects"][0]["deformed_vertices_m"]), 2)

        with self.assertRaises(ProtocolError):
            bad = {
                **message,
                "objects": [{**message["objects"][0], "deformed_vertices_m": [[0.0, 0.0]]}],
            }
            validate_state_message(bad)

    def test_invalid_command_rejects_unknown_object_and_bad_vector(self) -> None:
        with self.assertRaises(ProtocolError):
            validate_command_message(
                {
                    "type": "command",
                    "schema_version": 1,
                    "command": "apply_impulse",
                    "object_id": "missing_box",
                    "impulse_ns": [0.0, 0.0, 1.0],
                },
                known_object_ids={"test_box"},
            )

    def test_lift_drop_command_validates_height_and_object_id(self) -> None:
        message = validate_command_message(
            {
                "type": "command",
                "schema_version": 1,
                "command": "lift_drop",
                "object_id": "tissue_box",
                "lift_height_m": 0.30,
            },
            known_object_ids={"tissue_box"},
        )
        self.assertEqual(message["command"], "lift_drop")

        with self.assertRaises(ProtocolError):
            validate_command_message(
                {
                    "type": "command",
                    "schema_version": 1,
                    "command": "lift_drop",
                    "object_id": "tissue_box",
                    "lift_height_m": -0.1,
                },
                known_object_ids={"tissue_box"},
            )

        with self.assertRaises(ProtocolError):
            validate_command_message(
                {
                    "type": "command",
                    "schema_version": 1,
                    "command": "apply_impulse",
                    "object_id": "test_box",
                    "impulse_ns": [0.0, 0.0],
                },
                known_object_ids={"test_box"},
            )

    def test_decode_rejects_non_json_and_non_object_messages(self) -> None:
        with self.assertRaises(ProtocolError):
            decode_message_line("not-json\n")

        with self.assertRaises(ProtocolError):
            decode_message_line(json.dumps(["not", "an", "object"]) + "\n")


class BridgeServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MuJoCoBridgeServer(XML_PATH, host="127.0.0.1", port=0, state_hz=120.0)
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()

    def _connect(self) -> socket.socket:
        client = socket.create_connection((self.server.host, self.server.port), timeout=2.0)
        client.settimeout(2.0)
        return client

    @staticmethod
    def _read_until(client: socket.socket, message_type: str) -> dict[str, object]:
        buffer = b""
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            chunk = client.recv(65536)
            if not chunk:
                raise AssertionError("bridge closed the connection")
            buffer += chunk
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                if not raw:
                    continue
                message = decode_message_line(raw.decode("utf-8"))
                if message.get("type") == message_type:
                    return message
        raise AssertionError(f"did not receive message type {message_type!r}")

    def test_server_streams_state_and_accepts_impulse(self) -> None:
        client = self._connect()
        try:
            first = self._read_until(client, "state")
            self.assertEqual(first["schema_version"], 2)
            self.assertEqual(first["units"], "meter")
            self.assertEqual(first["up_axis"], "Z")
            self.assertEqual(first["objects"][0]["id"], "test_box")

            command = {
                "type": "command",
                "schema_version": 1,
                "command": "apply_impulse",
                "object_id": "test_box",
                "impulse_ns": [0.1, 0.0, 0.0],
            }
            client.sendall(encode_message(command).encode("utf-8"))
            ack = self._read_until(client, "ack")
            self.assertEqual(ack["command"], "apply_impulse")

            moved = self._read_until(client, "state")
            self.assertGreater(moved["objects"][0]["linear_velocity_mps"][0], 0.0)
            self.assertGreater(moved["seq"], first["seq"])
        finally:
            client.close()

    def test_invalid_command_returns_error_without_killing_reconnect(self) -> None:
        client = self._connect()
        try:
            self._read_until(client, "state")
            invalid = {
                "type": "command",
                "schema_version": 1,
                "command": "apply_impulse",
                "object_id": "missing_box",
                "impulse_ns": [0.0, 0.0, 1.0],
            }
            client.sendall(encode_message(invalid).encode("utf-8"))
            error = self._read_until(client, "error")
            self.assertEqual(error["error_code"], "invalid_command")
        finally:
            client.close()

        reconnected = self._connect()
        try:
            state = self._read_until(reconnected, "state")
            self.assertEqual(state["objects"][0]["id"], "test_box")
        finally:
            reconnected.close()


class TissueBridgeServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MuJoCoBridgeServer(TISSUE_XML_PATH, host="127.0.0.1", port=0, state_hz=120.0)
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()

    def test_server_streams_tissue_box_and_accepts_lift_drop(self) -> None:
        client = socket.create_connection((self.server.host, self.server.port), timeout=2.0)
        client.settimeout(2.0)
        try:
            first = BridgeServerTests._read_until(client, "state")
            self.assertEqual([item["id"] for item in first["objects"]], ["tissue_box"])
            command = {
                "type": "command",
                "schema_version": 1,
                "command": "lift_drop",
                "object_id": "tissue_box",
                "lift_height_m": 0.30,
            }
            client.sendall(encode_message(command).encode("utf-8"))
            ack = BridgeServerTests._read_until(client, "ack")
            self.assertEqual(ack["command"], "lift_drop")
            self.assertEqual(ack["object_id"], "tissue_box")
        finally:
            client.close()

    def test_reset_returns_tissue_box_to_the_rest_position(self) -> None:
        metadata = json.loads(TISSUE_METADATA_PATH.read_text(encoding="utf-8"))
        rest_z = float(metadata["tissue_box"]["rest_position_m"][2])
        client = socket.create_connection((self.server.host, self.server.port), timeout=2.0)
        client.settimeout(2.0)
        try:
            first = BridgeServerTests._read_until(client, "state")
            first_z = float(first["objects"][0]["position_m"][2])
            self.assertAlmostEqual(first_z, rest_z, delta=0.01)

            lift = {
                "type": "command",
                "schema_version": 1,
                "command": "lift_drop",
                "object_id": "tissue_box",
                "lift_height_m": 0.30,
            }
            client.sendall(encode_message(lift).encode("utf-8"))
            BridgeServerTests._read_until(client, "ack")
            lifted = BridgeServerTests._read_until(client, "state")
            self.assertGreater(float(lifted["objects"][0]["position_m"][2]), rest_z + 0.20)

            reset = {"type": "command", "schema_version": 1, "command": "reset"}
            client.sendall(encode_message(reset).encode("utf-8"))
            BridgeServerTests._read_until(client, "ack")
            reset_state = BridgeServerTests._read_until(client, "state")
            self.assertAlmostEqual(
                float(reset_state["objects"][0]["position_m"][2]),
                rest_z,
                delta=0.02,
            )
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
