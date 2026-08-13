from __future__ import annotations

import socket
import time
from pathlib import Path

from replica_physics_twin.bridge_protocol import (
    build_state_message,
    decode_message_line,
    encode_message,
)
from replica_physics_twin.bridge_server import MuJoCoBridgeServer
from replica_physics_twin.bridge_server import GRAB_MAX_FORCE_N
from replica_physics_twin.physics_validation import load_simulation


PROJECT_ROOT = Path(__file__).resolve().parents[1]
XML_PATH = PROJECT_ROOT / "outputs/mjcf/office0_interaction.xml"
PHYSICAL_MANIFEST_PATH = PROJECT_ROOT / "outputs/metadata/office0_physical_manifest.json"


def _read_until(client: socket.socket, message_type: str) -> dict:
    buffer = b""
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        chunk = client.recv(65536)
        if not chunk:
            raise AssertionError("bridge closed the connection")
        buffer += chunk
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            if raw:
                message = decode_message_line(raw.decode("utf-8"))
                if message.get("type") == message_type:
                    return message
    raise AssertionError(f"did not receive {message_type}")


def test_interaction_bridge_publishes_multiple_objects_contacts_and_properties() -> None:
    server = MuJoCoBridgeServer(
        XML_PATH,
        physical_manifest_path=PHYSICAL_MANIFEST_PATH,
        host="127.0.0.1",
        port=0,
        state_hz=120.0,
    )
    server.start()
    try:
        client = socket.create_connection((server.host, server.port), timeout=3.0)
        client.settimeout(3.0)
        try:
            state = _read_until(client, "state")
        finally:
            client.close()
    finally:
        server.stop()

    assert state["schema_version"] == 2
    assert state["physics_authority"] == "MuJoCo"
    assert {item["id"] for item in state["objects"]} >= {"tissue_box", "desk_organizer", "chair_4"}
    assert all(item["properties"]["mass_kg"] > 0.0 for item in state["objects"])
    assert all("source_object_id" in item for item in state["objects"])
    assert any(item["contacts"] for item in state["objects"])
    assert any(
        contact["other_id"] != "world"
        for item in state["objects"]
        for contact in item["contacts"]
    )


def test_bridge_starts_paused_and_wakes_only_after_user_impulse() -> None:
    """The scene must not drift before the first explicit user interaction."""

    server = MuJoCoBridgeServer(
        XML_PATH,
        physical_manifest_path=PHYSICAL_MANIFEST_PATH,
        host="127.0.0.1",
        port=0,
        state_hz=120.0,
    )
    server.start()
    try:
        client = socket.create_connection((server.host, server.port), timeout=3.0)
        client.settimeout(3.0)
        try:
            first = _read_until(client, "state")
            second = _read_until(client, "state")
            assert second["sim_time"] == first["sim_time"]

            object_id = first["objects"][0]["id"]
            command = {
                "type": "command",
                "schema_version": 1,
                "command": "apply_impulse",
                "object_id": object_id,
                "impulse_ns": [0.1, 0.0, 0.0],
            }
            client.sendall(encode_message(command).encode("utf-8"))
            _read_until(client, "ack")

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                moved = _read_until(client, "state")
                if moved["sim_time"] > first["sim_time"]:
                    break
            else:
                raise AssertionError("physics did not resume after the user impulse")
        finally:
            client.close()
    finally:
        server.stop()


def test_drag_force_cap_is_conservative_for_a_massive_rigid_object() -> None:
    # A mouse drag is a push, not an infinite-strength weld.  Keeping the cap
    # below the weight of a 9 kg bicycle makes a short drag visibly gradual and
    # prevents a cursor jump from producing an instant flip.
    assert 0.0 < GRAB_MAX_FORCE_N <= 30.0


def test_state_messages_are_not_written_as_full_runtime_log_records(tmp_path: Path) -> None:
    """Large deformable state payloads must not become a disk-I/O bottleneck."""

    log_path = tmp_path / "bridge.jsonl"
    server = MuJoCoBridgeServer(XML_PATH, log_path=log_path)
    state = build_state_message(
        1,
        0.0,
        [
            {
                "id": "test_box",
                "position_m": [0.0, 0.0, 0.0],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
                "linear_velocity_mps": [0.0, 0.0, 0.0],
                "angular_velocity_rps": [0.0, 0.0, 0.0],
                "contacts": [],
            }
        ],
    )

    class Sink:
        def send(self, payload: memoryview) -> int:
            assert bytes(payload).endswith(b"\n")
            return len(payload)

    server._send_message(Sink(), state)  # noqa: SLF001
    assert not log_path.exists() or log_path.read_text(encoding="utf-8") == ""


def test_batched_physics_step_preserves_fixed_step_simulation_time() -> None:
    """Runtime batching must not change MuJoCo's fixed timestep semantics."""

    server = MuJoCoBridgeServer(XML_PATH, physical_manifest_path=PHYSICAL_MANIFEST_PATH)
    server._model, server._data = load_simulation(XML_PATH)  # noqa: SLF001
    server._load_physical_manifest()  # noqa: SLF001
    server._reset_simulation()  # noqa: SLF001
    before = float(server._data.time)  # noqa: SLF001
    batch_size = 4

    server._step_once(batch_size)  # noqa: SLF001

    expected = before + batch_size * float(server._model.opt.timestep)  # noqa: SLF001
    assert server._data.time == expected  # noqa: SLF001


def test_state_send_retries_when_nonblocking_socket_would_block() -> None:
    """A fast state stream must not terminate the bridge on a full socket."""

    server = MuJoCoBridgeServer(XML_PATH)
    state = build_state_message(
        1,
        0.0,
        [
            {
                "id": "test_box",
                "position_m": [0.0, 0.0, 0.0],
                "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
                "linear_velocity_mps": [0.0, 0.0, 0.0],
                "angular_velocity_rps": [0.0, 0.0, 0.0],
                "contacts": [],
            }
        ],
    )

    class FlakySink:
        def __init__(self) -> None:
            self.blocked_once = False
            self.payload = bytearray()

        def send(self, payload: memoryview) -> int:
            if not self.blocked_once:
                self.blocked_once = True
                raise BlockingIOError
            self.payload.extend(payload)
            return len(payload)

    sink = FlakySink()
    server._send_message(sink, state)  # noqa: SLF001
    assert sink.payload.endswith(b"\n")
