"""TCP bridge that publishes MuJoCo state and accepts validated commands."""

from __future__ import annotations

import argparse
import json
import logging
import socket
import threading
import time
from pathlib import Path
from typing import Any, Mapping

import mujoco
import numpy as np

from .bridge_protocol import (
    ProtocolError,
    build_ack_message,
    build_error_message,
    build_state_message,
    decode_message_line,
    encode_message,
    validate_command_message,
)
from .physics_validation import load_simulation


LOGGER = logging.getLogger(__name__)

# Mouse dragging is a physical interaction, not a teleport.  A finite spring
# force lets MuJoCo's body mass determine the resulting acceleration while the
# cap prevents the cursor from exerting an unrealistically infinite force.
GRAB_STIFFNESS_N_PER_M = 120.0
GRAB_DAMPING_NS_PER_M = 24.0
# A drag is a hand-sized push, not an infinite-strength weld.  Keep the cap
# well below the bicycle's 9 kg weight (about 88 N) so a short cursor motion
# cannot flip it instantly.  MuJoCo still converts this force through each
# body's mass and inertia.
GRAB_MAX_FORCE_N = 24.0


class MuJoCoBridgeServer:
    """Serve one newline-delimited JSON client at a time over TCP."""

    def __init__(
        self,
        xml_path: Path,
        *,
        host: str = "127.0.0.1",
        port: int = 7007,
        state_hz: float = 60.0,
        log_path: Path | None = None,
        physical_manifest_path: Path | None = None,
        scene_id: str = "office_0",
    ) -> None:
        if state_hz <= 0.0:
            raise ValueError("state_hz must be positive")
        self.xml_path = Path(xml_path)
        self.host = host
        self._requested_port = int(port)
        self.state_hz = float(state_hz)
        self.log_path = Path(log_path) if log_path is not None else None
        self.physical_manifest_path = Path(physical_manifest_path) if physical_manifest_path is not None else None
        self.scene_id = str(scene_id)
        self._model: mujoco.MjModel | None = None
        self._data: mujoco.MjData | None = None
        self._listener: socket.socket | None = None
        self._client: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._client_lock = threading.Lock()
        self._log_lock = threading.Lock()
        self._seq = 0
        # A newly opened scene is an inspection state, not an autonomous
        # simulation.  User input (grab/impulse/lift) explicitly wakes it.
        self._paused = True
        self._interaction_only = False
        self._active_simulation_ids: set[str] = set()
        self._physical_by_body_name: dict[str, dict[str, Any]] = {}
        self._dynamic_records: dict[str, dict[str, Any]] = {}
        self._active_grabs: dict[str, dict[str, Any]] = {}
        self._last_cloth_centers: dict[str, np.ndarray] = {}
        self._last_cloth_state_times: dict[str, float] = {}
        self._cloth_triangle_indices: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        self._cloth_aero_cache: dict[str, dict[str, np.ndarray]] = {}

    @property
    def port(self) -> int:
        if self._listener is None:
            return self._requested_port
        return int(self._listener.getsockname()[1])

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            raise RuntimeError("bridge server is already running")
        self._model, self._data = load_simulation(self.xml_path)
        self._load_physical_manifest()
        self._reset_simulation()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self._requested_port))
        listener.listen(1)
        listener.settimeout(0.1)
        self._listener = listener
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._serve_loop, name="MuJoCoBridgeServer", daemon=True)
        self._thread.start()
        self._write_log({"event": "server_started", "host": self.host, "port": self.port})

    def _load_physical_manifest(self) -> None:
        self._physical_by_body_name = {}
        self._dynamic_records = {}
        self._cloth_triangle_indices = {}
        self._cloth_aero_cache = {}
        if self.physical_manifest_path is None:
            return
        try:
            payload = json.loads(self.physical_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not load physical manifest: {self.physical_manifest_path}") from exc
        records = payload.get("objects")
        if not isinstance(records, list):
            records = payload.get("dynamic_bodies", [])
        for record in records:
            if not isinstance(record, dict):
                continue
            class_name = str(
                record.get("class_name", record.get("display_name", record.get("template_name", "")))
            ).lower().replace("-", "_").replace(" ", "_")
            role = str(record.get("role", record.get("display_name", "")))
            object_id = record.get("object_id", record.get("source_object_id"))
            normalized = dict(record)
            if object_id is not None:
                normalized["object_id"] = object_id
            normalized["class_name"] = class_name
            normalized["role"] = role
            body_name = record.get("name")
            if body_name:
                self._dynamic_records[str(body_name)] = normalized
            keys = {class_name}
            if body_name:
                keys.add(str(body_name))
            if object_id is not None:
                keys.add(f"{class_name}_{object_id}")
            if role == "tissue_box":
                keys.add("tissue_box")
            if class_name == "desk_organizer":
                keys.add("desk_organizer")
            for key in keys:
                if key:
                    self._physical_by_body_name[key] = normalized

    def stop(self) -> None:
        self._stop_event.set()
        listener = self._listener
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        with self._client_lock:
            client = self._client
        if client is not None:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        self._listener = None
        self._write_log({"event": "server_stopped"})

    def _reset_simulation(self) -> None:
        assert self._model is not None and self._data is not None
        if self._model.nkey > 0:
            mujoco.mj_resetDataKeyframe(self._model, self._data, 0)
        else:
            # qpos0 contains body and flexcomp source poses.  Zeroing qpos
            # would erase every cloth vertex's calibrated starting position.
            mujoco.mj_resetData(self._model, self._data)
        self._data.qfrc_applied[:] = 0.0
        self._active_grabs.clear()
        self._active_simulation_ids.clear()
        self._last_cloth_centers.clear()
        self._last_cloth_state_times.clear()
        if self._data.eq_active.size:
            # Keep the cloth's permanent hanging-edge welds active.  Only
            # the temporary mouse-grab welds are disabled during reset.
            for equality_id in range(int(self._model.neq)):
                equality_name = mujoco.mj_id2name(
                    self._model, mujoco.mjtObj.mjOBJ_EQUALITY, equality_id
                )
                self._data.eq_active[equality_id] = bool(
                    equality_name
                    and (
                        equality_name.startswith("pin_")
                        or equality_name.startswith("support_")
                    )
                )
        # Reset must return to the same deterministic, user-controlled state
        # as startup.  Otherwise a reset immediately starts gravity/wind.
        self._paused = True
        self._interaction_only = False
        mujoco.mj_forward(self._model, self._data)

    def _dynamic_body_names(self) -> list[str]:
        assert self._model is not None
        names: list[str] = []
        if self._dynamic_records:
            for name, record in self._dynamic_records.items():
                if bool(record.get("deformable", False)):
                    flex_id = int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_FLEX, name))
                    if flex_id >= 0:
                        names.append(name)
                    continue
                body_id = int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_BODY, name))
                if body_id >= 0:
                    joint_id = int(self._model.body_jntadr[body_id])
                    if joint_id >= 0 and int(self._model.jnt_type[joint_id]) == int(mujoco.mjtJoint.mjJNT_FREE):
                        names.append(name)
            return sorted(set(names))
        for body_id in range(1, int(self._model.nbody)):
            joint_id = int(self._model.body_jntadr[body_id])
            if joint_id < 0 or int(self._model.jnt_type[joint_id]) != int(mujoco.mjtJoint.mjJNT_FREE):
                continue
            name = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_BODY, body_id)
            if name:
                names.append(name)
        return sorted(names)

    def _is_deformable(self, object_id: str) -> bool:
        return bool(self._dynamic_records.get(object_id, {}).get("deformable", False))

    def _flex_vertex_slice(self, object_id: str) -> tuple[int, int]:
        assert self._model is not None
        flex_id = int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_FLEX, object_id))
        if flex_id < 0:
            raise ProtocolError(f"unknown deformable object_id: {object_id}")
        start = int(self._model.flex_vertadr[flex_id])
        count = int(self._model.flex_vertnum[flex_id])
        return start, count

    def _flex_positions(self, object_id: str) -> np.ndarray:
        assert self._data is not None
        start, count = self._flex_vertex_slice(object_id)
        return np.asarray(self._data.flexvert_xpos[start : start + count], dtype=np.float64).copy()

    def _flex_positions_view(self, object_id: str) -> np.ndarray:
        """Return the live MuJoCo flex position array without a per-step copy."""

        assert self._data is not None
        start, count = self._flex_vertex_slice(object_id)
        return np.asarray(self._data.flexvert_xpos[start : start + count], dtype=np.float64)

    def _flex_body_ids(self, object_id: str) -> np.ndarray:
        assert self._model is not None
        start, count = self._flex_vertex_slice(object_id)
        return np.asarray(self._model.flex_vertbodyid[start : start + count], dtype=np.int32)

    def _flex_pinned_body_ids(self, object_id: str) -> set[int]:
        """Return cloth node bodies held by the permanent pin welds."""

        assert self._model is not None
        pinned: set[int] = set()
        prefix = f"pin_{object_id}_"
        for equality_id in range(int(self._model.neq)):
            name = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_EQUALITY, equality_id)
            if not name or not name.startswith(prefix):
                continue
            if int(self._model.eq_objtype[equality_id]) != int(mujoco.mjtObj.mjOBJ_BODY):
                continue
            pinned.add(int(self._model.eq_obj1id[equality_id]))
        return pinned

    def _serve_loop(self) -> None:
        assert self._listener is not None
        while not self._stop_event.is_set():
            try:
                client, address = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._client_lock:
                self._client = client
            self._write_log({"event": "client_connected", "address": list(address)})
            try:
                self._serve_client(client)
            except OSError as exc:
                self._write_log({"event": "client_socket_error", "message": str(exc)})
            finally:
                self._release_all_grabs()
                with self._client_lock:
                    self._client = None
                try:
                    client.close()
                except OSError:
                    pass
                self._write_log({"event": "client_disconnected"})

    def _serve_client(self, client: socket.socket) -> None:
        client.setblocking(False)
        receive_buffer = b""
        step_period = float(self._model.opt.timestep) if self._model is not None else 0.002
        publish_period = 1.0 / self.state_hz
        last_step_wall = time.monotonic()
        last_publish_wall = 0.0
        previously_paused = self._paused
        self._send_state(client)
        while not self._stop_event.is_set():
            receive_buffer = self._receive_commands(client, receive_buffer)
            now = time.monotonic()
            if not self._paused:
                # Do not repay time accumulated while the scene was paused.
                # The first user interaction starts from the current wall
                # clock, so a long inspection pause cannot cause a burst.
                if previously_paused:
                    last_step_wall = now
                elapsed = now - last_step_wall
                if elapsed >= step_period:
                    # A larger batch limit avoids throwing away elapsed time
                    # when MuJoCo briefly spends longer than one tick.  The
                    # simulation remains fixed-step; this only removes the
                    # old 8-step/1 ms polling bottleneck.
                    steps = min(int(elapsed / step_period), 64)
                else:
                    steps = 0
                if steps:
                    self._step_once(steps)
                    last_step_wall += steps * step_period
                    if now - last_step_wall > 0.25:
                        last_step_wall = now
            else:
                last_step_wall = now
            previously_paused = self._paused
            if now - last_publish_wall >= publish_period:
                self._send_state(client)
                last_publish_wall = now
            # While active, poll frequently enough to keep the fixed-step
            # clock close to wall time.  While paused, yield more generously.
            time.sleep(0.0001 if not self._paused else 0.001)

    def _receive_commands(self, client: socket.socket, receive_buffer: bytes) -> bytes:
        while True:
            try:
                chunk = client.recv(65536)
            except BlockingIOError:
                break
            if not chunk:
                raise OSError("client disconnected")
            receive_buffer += chunk
            if len(receive_buffer) > 1_000_000:
                self._send_error(client, "message_too_large", "command buffer exceeds maximum size")
                receive_buffer = b""
                continue
            while b"\n" in receive_buffer:
                raw_line, receive_buffer = receive_buffer.split(b"\n", 1)
                if not raw_line.strip():
                    continue
                self._handle_command_line(client, raw_line)
        return receive_buffer

    def _handle_command_line(self, client: socket.socket, raw_line: bytes) -> None:
        try:
            message = decode_message_line(raw_line)
            validate_command_message(message, known_object_ids=set(self._dynamic_body_names()))
            self._execute_command(message)
        except ProtocolError as exc:
            self._send_error(client, "invalid_command", str(exc))
            self._write_log(
                {
                    "event": "invalid_command",
                    "message": str(exc),
                    "raw_length": len(raw_line),
                    "raw_hex": raw_line[:256].hex(),
                }
            )
            return
        command = str(message["command"])
        object_id = message.get("object_id")
        details = getattr(self, "_last_command_details", {})
        ack = build_ack_message(
            self._seq,
            self._sim_time(),
            command,
            object_id,
            grab_id=details.get("grab_id"),
            object_ids=details.get("object_ids"),
        )
        self._send_message(client, ack)
        self._write_log({"event": "command", "message": message})

    def _execute_command(self, message: dict[str, Any]) -> None:
        self._last_command_details: dict[str, Any] = {}
        command = message["command"]
        if command == "reset":
            self._reset_simulation()
            return
        if command == "pause":
            self._paused = bool(message["paused"])
            # P explicitly means “run the whole scene”; mouse/keyboard object
            # interactions use selective activation below instead.
            if not self._paused:
                self._interaction_only = False
            return
        if command == "apply_impulse":
            self._paused = False
            self._interaction_only = True
            self._active_simulation_ids.add(str(message["object_id"]))
            self._release_initial_support(str(message["object_id"]))
            self._apply_impulse(message)
            return
        if command == "lift_drop":
            self._paused = False
            self._interaction_only = True
            self._active_simulation_ids.add(str(message["object_id"]))
            self._release_initial_support(str(message["object_id"]))
            self._lift_drop(message)
            return
        if command == "grab_begin":
            self._paused = False
            self._interaction_only = True
            self._active_simulation_ids.update(str(value) for value in message["object_ids"])
            for object_id in message["object_ids"]:
                self._release_initial_support(str(object_id))
            self._grab_begin(message)
            return
        if command == "grab_update":
            self._grab_update(message)
            return
        if command == "grab_end":
            self._grab_end(message)
            return
        raise ProtocolError(f"unsupported command: {command}")

    def _release_all_grabs(self) -> None:
        if self._data is None:
            self._active_grabs.clear()
            return
        self._active_grabs.clear()
        if self._model is not None:
            mujoco.mj_forward(self._model, self._data)

    def _body_grab_handles(self, body_name: str) -> tuple[int, int, int]:
        assert self._model is not None
        body_id = int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_BODY, body_name))
        if body_id < 0:
            raise ProtocolError(f"unknown object_id: {body_name}")
        joint_id = int(self._model.body_jntadr[body_id])
        if joint_id < 0 or int(self._model.jnt_type[joint_id]) != int(mujoco.mjtJoint.mjJNT_FREE):
            raise ProtocolError(f"object is not a freejoint rigid body: {body_name}")
        mocap_body_id = int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_BODY, f"mocap_{body_name}"))
        equality_id = int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_EQUALITY, f"grab_{body_name}"))
        if mocap_body_id < 0 or equality_id < 0:
            raise ProtocolError(f"object has no mocap grab constraint: {body_name}")
        mocap_id = int(self._model.body_mocapid[mocap_body_id])
        if mocap_id < 0:
            raise ProtocolError(f"object has no mocap id: {body_name}")
        return body_id, mocap_id, equality_id

    def _release_initial_support(self, object_id: str) -> None:
        """Release a scan-pose parking support when the user really acts."""

        assert self._model is not None and self._data is not None
        equality_id = int(
            mujoco.mj_name2id(
                self._model,
                mujoco.mjtObj.mjOBJ_EQUALITY,
                f"support_{object_id}",
            )
        )
        if equality_id >= 0:
            self._data.eq_active[equality_id] = 0

    def _grab_begin(self, message: dict[str, Any]) -> None:
        assert self._model is not None and self._data is not None
        grab_id = str(message.get("client_grab_id") or f"grab-{self._seq + 1}")
        if grab_id in self._active_grabs:
            raise ProtocolError(f"grab_id is already active: {grab_id}")
        object_ids = [str(object_id) for object_id in message["object_ids"]]
        # Keep the lower-level method safe for tests and programmatic callers
        # that invoke it directly instead of going through _execute_command.
        self._active_simulation_ids.update(object_ids)
        self._interaction_only = True
        anchor = np.asarray(message["anchor_m"], dtype=np.float64)
        relative_positions: list[list[float]] = []
        anchor_offsets: list[list[float]] = []
        body_ids: list[int] = []
        target_positions: list[list[float]] = []
        cloth_entries: list[dict[str, Any]] = []
        for object_id in object_ids:
            if self._is_deformable(object_id):
                positions = self._flex_positions(object_id)
                node_body_ids = self._flex_body_ids(object_id)
                pinned_body_ids = self._flex_pinned_body_ids(object_id)
                cloth_entries.append(
                    {
                        "object_id": object_id,
                        "body_ids": [int(value) for value in node_body_ids],
                        "pinned_body_ids": sorted(pinned_body_ids),
                        "relative_positions": [
                            [float(value) for value in (position - anchor)] for position in positions
                        ],
                        "target_positions": [[float(value) for value in position] for position in positions],
                    }
                )
                continue
            body_id, _, _ = self._body_grab_handles(object_id)
            relative_positions.append([float(value) for value in (self._data.xpos[body_id] - anchor)])
            body_rotation = np.asarray(self._data.xmat[body_id], dtype=np.float64).reshape(3, 3)
            anchor_offset_local = body_rotation.T @ (anchor - self._data.xpos[body_id])
            anchor_offsets.append([float(value) for value in anchor_offset_local])
            body_ids.append(body_id)
            target_positions.append([float(value) for value in self._data.xpos[body_id]])
        self._active_grabs[grab_id] = {
            "object_ids": object_ids,
            "body_ids": body_ids,
            "anchor_m": [float(value) for value in anchor],
            "relative_positions": relative_positions,
            "anchor_offsets": anchor_offsets,
            "target_positions": target_positions,
            "cloth_entries": cloth_entries,
        }
        self._data.qfrc_applied[:] = 0.0
        mujoco.mj_forward(self._model, self._data)
        self._last_command_details = {"grab_id": grab_id, "object_ids": object_ids}

    def _grab_update(self, message: dict[str, Any]) -> None:
        assert self._model is not None and self._data is not None
        grab_id = str(message["grab_id"])
        grab = self._active_grabs.get(grab_id)
        if grab is None:
            raise ProtocolError(f"unknown grab_id: {grab_id}")
        target = np.asarray(message["target_position_m"], dtype=np.float64)
        anchor = np.asarray(grab["anchor_m"], dtype=np.float64)
        delta = target - anchor
        target_quat = np.asarray(message.get("target_quaternion_wxyz", [1.0, 0.0, 0.0, 0.0]), dtype=np.float64)
        grab["target_positions"] = [
            [
                float(value)
                for value in (
                    np.asarray(grab["anchor_m"], dtype=np.float64)
                    + np.asarray(grab["relative_positions"][index], dtype=np.float64)
                    + delta
                )
            ]
            for index in range(len(grab["body_ids"]))
        ]
        for cloth_entry in grab.get("cloth_entries", []):
            cloth_entry["target_positions"] = [
                [
                    float(value)
                    for value in (
                        np.asarray(grab["anchor_m"], dtype=np.float64)
                        + np.asarray(relative_position, dtype=np.float64)
                        + delta
                    )
                ]
                for relative_position in cloth_entry["relative_positions"]
            ]
        grab["target_quaternion_wxyz"] = [float(value) for value in target_quat]
        self._last_command_details = {"grab_id": grab_id, "object_ids": list(grab["object_ids"])}

    def _grab_end(self, message: dict[str, Any]) -> None:
        assert self._model is not None and self._data is not None
        grab_id = str(message["grab_id"])
        grab = self._active_grabs.pop(grab_id, None)
        if grab is None:
            raise ProtocolError(f"unknown grab_id: {grab_id}")
        self._data.qfrc_applied[:] = 0.0
        mujoco.mj_forward(self._model, self._data)
        self._last_command_details = {"grab_id": grab_id, "object_ids": list(grab["object_ids"])}

    def _apply_active_grab_forces(self) -> None:
        """Apply finite spring-damper forces for all active mouse grabs."""

        assert self._model is not None and self._data is not None
        for grab in self._active_grabs.values():
            for index, (body_id, target_values) in enumerate(zip(grab["body_ids"], grab["target_positions"])):
                body_id = int(body_id)
                target = np.asarray(target_values, dtype=np.float64)
                position = np.asarray(self._data.xpos[body_id], dtype=np.float64)
                joint_id = int(self._model.body_jntadr[body_id])
                dof_start = int(self._model.jnt_dofadr[joint_id])
                velocity = np.asarray(self._data.qvel[dof_start : dof_start + 3], dtype=np.float64)
                force = GRAB_STIFFNESS_N_PER_M * (target - position) - GRAB_DAMPING_NS_PER_M * velocity
                force_norm = float(np.linalg.norm(force))
                if force_norm > GRAB_MAX_FORCE_N:
                    force *= GRAB_MAX_FORCE_N / force_norm
                anchor_offset_local = np.asarray(
                    grab.get("anchor_offsets", [])[index] if index < len(grab.get("anchor_offsets", [])) else [0.0, 0.0, 0.0],
                    dtype=np.float64,
                )
                body_rotation = np.asarray(self._data.xmat[body_id], dtype=np.float64).reshape(3, 3)
                application_point = position + body_rotation @ anchor_offset_local
                qfrc_target = np.zeros(self._model.nv, dtype=np.float64)
                mujoco.mj_applyFT(
                    self._model,
                    self._data,
                    force,
                    np.zeros(3, dtype=np.float64),
                    application_point,
                    body_id,
                    qfrc_target,
                )
                self._data.qfrc_applied[:] += qfrc_target
            for cloth_entry in grab.get("cloth_entries", []):
                node_count = max(len(cloth_entry["body_ids"]), 1)
                for body_id, target_values in zip(cloth_entry["body_ids"], cloth_entry["target_positions"]):
                    body_id = int(body_id)
                    # Pinned flex vertices belong to the world body and have
                    # no translational DOFs.  The unpinned vertices carry the
                    # finite spring forces that make a grabbed cloth stretch,
                    # sag, and react to its surroundings.
                    if body_id <= 0 or body_id in set(cloth_entry.get("pinned_body_ids", [])):
                        continue
                    body_position = np.asarray(self._data.xpos[body_id], dtype=np.float64)
                    target = np.asarray(target_values, dtype=np.float64)
                    joint_id = int(self._model.body_jntadr[body_id])
                    dof_start = int(self._model.jnt_dofadr[joint_id])
                    velocity = np.asarray(self._data.qvel[dof_start : dof_start + 3], dtype=np.float64)
                    force = (
                        GRAB_STIFFNESS_N_PER_M * (target - body_position)
                        - GRAB_DAMPING_NS_PER_M * velocity
                    ) / float(node_count)
                    force_norm = float(np.linalg.norm(force))
                    if force_norm > GRAB_MAX_FORCE_N / float(node_count):
                        force *= (GRAB_MAX_FORCE_N / float(node_count)) / force_norm
                    qfrc_target = np.zeros(self._model.nv, dtype=np.float64)
                    mujoco.mj_applyFT(
                        self._model,
                        self._data,
                        force,
                        np.zeros(3, dtype=np.float64),
                        body_position,
                        body_id,
                        qfrc_target,
                    )
                    self._data.qfrc_applied[:] += qfrc_target

    def _apply_cloth_aerodynamic_forces(self) -> None:
        """Apply area-based wind drag to every MuJoCo cloth triangle.

        MuJoCo's global wind/air model contributes body-level fluid forces.
        A flex cloth has no ordinary geom attached to each node, so this
        supplements that model with a thin-surface drag force computed from
        the current flex triangles.  The resulting forces are still applied
        through ``qfrc_applied`` and are integrated by ``mj_step``; this is
        not a visual animation or a vertex teleport.
        """

        assert self._model is not None and self._data is not None
        wind = np.asarray(self._model.opt.wind, dtype=np.float64)
        density = float(self._model.opt.density)
        if density <= 0.0 or float(np.linalg.norm(wind)) <= 1e-8:
            return
        for object_id, record in self._dynamic_records.items():
            if not bool(record.get("deformable", False)):
                continue
            grid = record.get("cloth_grid")
            if not isinstance(grid, Mapping):
                continue
            cols = max(int(grid.get("cols", 0)), 2)
            rows = max(int(grid.get("rows", 0)), 2)
            # The aerodynamic pass only reads the current positions.  Avoid
            # copying all vertices before every fixed physics step.
            positions = self._flex_positions_view(object_id)
            body_ids = self._flex_body_ids(object_id)
            if positions.shape[0] != cols * rows:
                continue
            pinned_body_ids = self._flex_pinned_body_ids(object_id)
            drag_coefficient = float(
                record.get("cloth_material", {}).get("wind_drag_coefficient", 1.35)
            )
            cache = self._cloth_aero_cache.get(object_id)
            if cache is None:
                unique_body_ids, inverse = np.unique(body_ids, return_inverse=True)
                joint_ids = self._model.body_jntadr[unique_body_ids]
                dof_starts = np.full(unique_body_ids.shape, -1, dtype=np.int32)
                valid_joints = joint_ids >= 0
                dof_starts[valid_joints] = self._model.jnt_dofadr[joint_ids[valid_joints]]
                movable = np.array(
                    [
                        int(body_id) > 0 and int(body_id) not in pinned_body_ids and int(dof_start) >= 0
                        for body_id, dof_start in zip(unique_body_ids, dof_starts)
                    ],
                    dtype=bool,
                )
                cache = {
                    "body_ids": body_ids.copy(),
                    "inverse": inverse.astype(np.int32, copy=False),
                    "unique_body_ids": unique_body_ids.astype(np.int32, copy=False),
                    "movable_body_ids": unique_body_ids[movable].astype(np.int32, copy=False),
                    "movable_dof_starts": dof_starts[movable].astype(np.int32, copy=False),
                }
                self._cloth_aero_cache[object_id] = cache
            else:
                # A manifest's flex topology is immutable, but keep this
                # guard so a malformed/reloaded model cannot reuse stale IDs.
                if not np.array_equal(cache["body_ids"], body_ids):
                    self._cloth_aero_cache.pop(object_id, None)
                    continue

            unique_body_ids = cache["unique_body_ids"]
            inverse = cache["inverse"]
            group_velocities = np.zeros((unique_body_ids.shape[0], 3), dtype=np.float64)
            movable_body_ids = cache["movable_body_ids"]
            movable_dof_starts = cache["movable_dof_starts"]
            if movable_dof_starts.size:
                dof_indices = movable_dof_starts[:, None] + np.arange(3, dtype=np.int32)[None, :]
                group_velocities[np.isin(unique_body_ids, movable_body_ids)] = self._data.qvel[dof_indices]
            node_velocities = group_velocities[inverse]

            triangle_indices = self._cloth_triangle_indices.get(object_id)
            if triangle_indices is None:
                grid_x = np.arange(cols - 1, dtype=np.int32)[:, None]
                grid_y = np.arange(rows - 1, dtype=np.int32)[None, :]
                i00 = (grid_x * rows + grid_y).reshape(-1)
                i10 = ((grid_x + 1) * rows + grid_y).reshape(-1)
                i01 = (grid_x * rows + grid_y + 1).reshape(-1)
                i11 = ((grid_x + 1) * rows + grid_y + 1).reshape(-1)
                triangle_indices = (
                    np.concatenate((i00, i00)),
                    np.concatenate((i10, i11)),
                    np.concatenate((i11, i01)),
                )
                self._cloth_triangle_indices[object_id] = triangle_indices
            index0, index1, index2 = triangle_indices
            triangle_positions = positions[index0], positions[index1], positions[index2]
            triangle_velocities = node_velocities[index0], node_velocities[index1], node_velocities[index2]
            area_vectors = np.cross(
                triangle_positions[1] - triangle_positions[0],
                triangle_positions[2] - triangle_positions[0],
            )
            twice_areas = np.linalg.norm(area_vectors, axis=1)
            valid = twice_areas > 1e-10
            if not np.any(valid):
                continue
            normals = np.zeros_like(area_vectors)
            normals[valid] = area_vectors[valid] / twice_areas[valid, None]
            relative_wind = wind[None, :] - np.mean(triangle_velocities, axis=0)
            speeds = np.linalg.norm(relative_wind, axis=1)
            normal_speed = np.einsum("ij,ij->i", relative_wind, normals)
            tangential_wind = relative_wind - normal_speed[:, None] * normals
            dynamic_pressure = 0.5 * density * drag_coefficient * (0.5 * twice_areas)
            forces = dynamic_pressure[:, None] * (
                normal_speed[:, None] * np.abs(normal_speed[:, None]) * normals
                + 0.35 * speeds[:, None] * tangential_wind
            )
            forces[~valid] = 0.0
            forces[speeds <= 1e-8] = 0.0
            nodal_forces = np.zeros_like(positions)
            force_per_vertex = forces / 3.0
            np.add.at(nodal_forces, index0, force_per_vertex)
            np.add.at(nodal_forces, index1, force_per_vertex)
            np.add.at(nodal_forces, index2, force_per_vertex)

            # flexcomp grid nodes use three orthogonal world-space slide
            # joints.  Aggregate once by body ID, then apply only the
            # movable groups.  The previous implementation rebuilt a boolean
            # mask and a reduction for every one of the 480 nodes per step.
            body_forces = np.zeros((self._model.nbody, 3), dtype=np.float64)
            np.add.at(body_forces, body_ids, nodal_forces)
            for body_id, dof_start in zip(movable_body_ids, movable_dof_starts):
                dof_start = int(dof_start)
                self._data.qfrc_applied[dof_start : dof_start + 3] += body_forces[int(body_id)]

    def _lift_drop(self, message: dict[str, Any]) -> None:
        """Raise a rigid body or every movable cloth vertex, then drop it."""

        assert self._model is not None and self._data is not None
        object_id = str(message["object_id"])
        if self._is_deformable(object_id):
            lift = float(message["lift_height_m"])
            pinned_body_ids = self._flex_pinned_body_ids(object_id)
            for body_id in self._flex_body_ids(object_id):
                body_id = int(body_id)
                if body_id <= 0 or body_id in pinned_body_ids:
                    continue
                joint_id = int(self._model.body_jntadr[body_id])
                qpos_start = int(self._model.jnt_qposadr[joint_id])
                dof_start = int(self._model.jnt_dofadr[joint_id])
                self._data.qpos[qpos_start + 2] += lift
                self._data.qvel[dof_start : dof_start + 3] = 0.0
            self._data.qfrc_applied[:] = 0.0
            mujoco.mj_forward(self._model, self._data)
            return
        body_id = int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_BODY, object_id))
        if body_id < 0:
            raise ProtocolError(f"unknown object_id: {message['object_id']}")
        joint_id = int(self._model.body_jntadr[body_id])
        if joint_id < 0 or int(self._model.jnt_type[joint_id]) != int(mujoco.mjtJoint.mjJNT_FREE):
            raise ProtocolError("object is not a freejoint rigid body")
        dof_start = int(self._model.jnt_dofadr[joint_id])
        qpos_start = int(self._model.jnt_qposadr[joint_id])
        self._data.qpos[qpos_start + 2] += float(message["lift_height_m"])
        self._data.qvel[dof_start : dof_start + 6] = 0.0
        self._data.qfrc_applied[:] = 0.0
        mujoco.mj_forward(self._model, self._data)

    def _apply_impulse(self, message: dict[str, Any]) -> None:
        assert self._model is not None and self._data is not None
        object_id = str(message["object_id"])
        impulse = np.asarray(message["impulse_ns"], dtype=np.float64)
        if self._is_deformable(object_id):
            pinned_body_ids = self._flex_pinned_body_ids(object_id)
            node_body_ids = [
                int(value)
                for value in self._flex_body_ids(object_id)
                if int(value) > 0 and int(value) not in pinned_body_ids
            ]
            node_body_ids = list(dict.fromkeys(node_body_ids))
            if not node_body_ids:
                raise ProtocolError(f"deformable object has no movable vertices: {object_id}")
            per_node_impulse = impulse / float(len(node_body_ids))
            for body_id in node_body_ids:
                joint_id = int(self._model.body_jntadr[body_id])
                dof_start = int(self._model.jnt_dofadr[joint_id])
                node_mass = max(float(self._model.body_mass[body_id]), 1e-8)
                self._data.qvel[dof_start : dof_start + 3] += per_node_impulse / node_mass
            return
        body_id = int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_BODY, object_id))
        if body_id < 0:
            raise ProtocolError(f"unknown object_id: {message['object_id']}")
        joint_id = int(self._model.body_jntadr[body_id])
        if joint_id < 0 or int(self._model.jnt_type[joint_id]) != int(mujoco.mjtJoint.mjJNT_FREE):
            raise ProtocolError("object is not a freejoint rigid body")
        if message.get("point_m") is None:
            mass = float(self._model.body_mass[body_id])
            dof_start = int(self._model.jnt_dofadr[joint_id])
            self._data.qvel[dof_start : dof_start + 3] += impulse / mass
            return
        point = np.asarray(message["point_m"], dtype=np.float64)
        force = impulse / float(self._model.opt.timestep)
        torque = np.cross(point - self._data.xpos[body_id], force)
        qfrc_target = np.zeros(self._model.nv, dtype=np.float64)
        mujoco.mj_applyFT(self._model, self._data, force, torque, point, body_id, qfrc_target)
        self._data.qfrc_applied[:] += qfrc_target
        self._step_once()

    def _step_once(self, nstep: int = 1) -> None:
        assert self._model is not None and self._data is not None
        nstep = max(int(nstep), 1)
        self._apply_cloth_aerodynamic_forces()
        self._apply_active_grab_forces()
        frozen = self._capture_inactive_dynamic_state() if self._interaction_only else {}
        # MuJoCo keeps its fixed internal timestep for every substep.  The
        # force field is refreshed at the beginning of each bridge batch; a
        # short batch avoids Python-call overhead without turning this into a
        # teleport or a variable-timestep integrator.
        mujoco.mj_step(self._model, self._data, nstep=nstep)
        if frozen:
            newly_contacted = self._dynamic_objects_contacting_active_objects()
            self._active_simulation_ids.update(newly_contacted)
            for object_id, state in frozen.items():
                if object_id in newly_contacted:
                    continue
                self._restore_dynamic_state(state)
            mujoco.mj_forward(self._model, self._data)
        self._data.qfrc_applied[:] = 0.0

    def _joint_sizes(self, joint_type: int) -> tuple[int, int]:
        if joint_type == int(mujoco.mjtJoint.mjJNT_FREE):
            return 7, 6
        if joint_type == int(mujoco.mjtJoint.mjJNT_BALL):
            return 4, 3
        return 1, 1

    def _object_body_ids(self, object_id: str) -> list[int]:
        assert self._model is not None
        if self._is_deformable(object_id):
            return sorted(
                {
                    int(value)
                    for value in self._flex_body_ids(object_id)
                    if int(value) > 0
                }
            )
        body_id = int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_BODY, object_id))
        return [body_id] if body_id > 0 else []

    def _capture_dynamic_body_state(self, body_id: int) -> list[tuple[int, np.ndarray, int, np.ndarray]]:
        assert self._model is not None and self._data is not None
        state: list[tuple[int, np.ndarray, int, np.ndarray]] = []
        joint_start = int(self._model.body_jntadr[body_id])
        joint_count = int(self._model.body_jntnum[body_id])
        for offset in range(joint_count):
            joint_id = joint_start + offset
            qpos_size, dof_size = self._joint_sizes(int(self._model.jnt_type[joint_id]))
            qpos_start = int(self._model.jnt_qposadr[joint_id])
            dof_start = int(self._model.jnt_dofadr[joint_id])
            state.append(
                (
                    qpos_start,
                    self._data.qpos[qpos_start : qpos_start + qpos_size].copy(),
                    dof_start,
                    self._data.qvel[dof_start : dof_start + dof_size].copy(),
                )
            )
        return state

    def _capture_inactive_dynamic_state(self) -> dict[str, list[tuple[int, np.ndarray, int, np.ndarray]]]:
        state: dict[str, list[tuple[int, np.ndarray, int, np.ndarray]]] = {}
        for object_id in self._dynamic_body_names():
            if object_id in self._active_simulation_ids:
                continue
            # A programmatic grab/impulse test without a loaded physical
            # manifest still needs to simulate ordinary rigid bodies.  The
            # selective wake policy is enabled by the runtime manifest.
            if not self._dynamic_records and not self._is_deformable(object_id):
                continue
            for body_id in self._object_body_ids(object_id):
                state.setdefault(object_id, []).extend(self._capture_dynamic_body_state(body_id))
        return state

    def _restore_dynamic_state(
        self,
        state: list[tuple[int, np.ndarray, int, np.ndarray]],
    ) -> None:
        assert self._data is not None
        for qpos_start, qpos, dof_start, qvel in state:
            self._data.qpos[qpos_start : qpos_start + len(qpos)] = qpos
            self._data.qvel[dof_start : dof_start + len(qvel)] = qvel

    def _dynamic_object_for_body(self, body_id: int) -> str | None:
        assert self._model is not None
        for object_id in self._dynamic_body_names():
            if body_id in self._object_body_ids(object_id):
                return object_id
        return None

    def _dynamic_object_for_flex(self, flex_id: int) -> str | None:
        assert self._model is not None
        if flex_id < 0:
            return None
        name = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_FLEX, flex_id)
        return str(name) if name in self._dynamic_records else None

    def _dynamic_objects_contacting_active_objects(self) -> set[str]:
        assert self._model is not None and self._data is not None
        active_body_ids = {
            body_id
            for object_id in self._active_simulation_ids
            for body_id in self._object_body_ids(object_id)
        }
        active_flex_ids = {
            int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_FLEX, object_id))
            for object_id in self._active_simulation_ids
            if self._is_deformable(object_id)
        }
        contacted: set[str] = set()
        for contact_index in range(int(self._data.ncon)):
            contact = self._data.contact[contact_index]
            flex_ids = [int(value) for value in contact.flex if int(value) >= 0]
            geom_body_ids = [
                int(self._model.geom_bodyid[int(value)])
                for value in (contact.geom1, contact.geom2)
                if int(value) >= 0
            ]
            if not (set(geom_body_ids).intersection(active_body_ids) or set(flex_ids).intersection(active_flex_ids)):
                continue
            for body_id in geom_body_ids:
                object_id = self._dynamic_object_for_body(body_id)
                if object_id is not None and object_id not in self._active_simulation_ids:
                    contacted.add(object_id)
            for flex_id in flex_ids:
                object_id = self._dynamic_object_for_flex(flex_id)
                if object_id is not None and object_id not in self._active_simulation_ids:
                    contacted.add(object_id)
        return contacted

    def _sim_time(self) -> float:
        assert self._data is not None
        return float(self._data.time)

    def _state_objects(self) -> list[dict[str, Any]]:
        assert self._model is not None and self._data is not None
        objects: list[dict[str, Any]] = []
        for body_name in self._dynamic_body_names():
            physical = self._physical_by_body_name.get(body_name, self._dynamic_records.get(body_name, {}))
            if self._is_deformable(body_name):
                vertices = self._flex_positions(body_name)
                center = vertices.mean(axis=0)
                previous_center = self._last_cloth_centers.get(body_name)
                sim_time = self._sim_time()
                previous_time = self._last_cloth_state_times.get(body_name)
                state_delta = sim_time - previous_time if previous_time is not None else 0.0
                linear_velocity = (
                    (center - previous_center) / state_delta
                    if previous_center is not None and state_delta > 1e-9
                    else np.zeros(3)
                )
                self._last_cloth_centers[body_name] = center.copy()
                self._last_cloth_state_times[body_name] = sim_time
                state: dict[str, Any] = {
                    "id": body_name,
                    "position_m": [float(value) for value in center],
                    "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
                    "linear_velocity_mps": [float(value) for value in linear_velocity],
                    "angular_velocity_rps": [0.0, 0.0, 0.0],
                    "contacts": self._flex_contacts(body_name),
                    "deformed_vertices_m": [
                        [float(value) for value in vertex] for vertex in vertices
                    ],
                }
                self._attach_physical_properties(state, physical)
                objects.append(state)
                continue
            body_id = int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_BODY, body_name))
            joint_id = int(self._model.body_jntadr[body_id])
            dof_start = int(self._model.jnt_dofadr[joint_id])
            state: dict[str, Any] = {
                "id": body_name,
                "position_m": [float(value) for value in self._data.xpos[body_id]],
                "quaternion_wxyz": [float(value) for value in self._data.xquat[body_id]],
                "linear_velocity_mps": [float(self._data.qvel[dof_start + axis]) for axis in range(3)],
                "angular_velocity_rps": [float(self._data.qvel[dof_start + 3 + axis]) for axis in range(3)],
                "contacts": self._body_contacts(body_id),
            }
            self._attach_physical_properties(state, physical)
            objects.append(state)
        return objects

    @staticmethod
    def _attach_physical_properties(state: dict[str, Any], physical: Mapping[str, Any]) -> None:
        if not physical:
            return
        if "object_id" in physical:
            state["source_object_id"] = int(physical["object_id"])
        if physical.get("role"):
            state["role"] = str(physical["role"])
        state["properties"] = {
            "size_m": list(physical.get("size_m", [])),
            "mass_kg": float(physical.get("mass_kg", 0.0)),
            "inertia_diagonal_kg_m2": list(physical.get("inertia_diagonal_kg_m2", [])),
            "friction": dict(physical.get("friction", {})),
            "movable": bool(physical.get("movable", False)),
        }

    def _flex_contacts(self, object_id: str) -> list[dict[str, Any]]:
        assert self._model is not None and self._data is not None
        flex_body_ids = set(int(value) for value in self._flex_body_ids(object_id))
        contacts: list[dict[str, Any]] = []
        for contact_index in range(int(self._data.ncon)):
            contact = self._data.contact[contact_index]
            geom_ids = (int(contact.geom1), int(contact.geom2))
            contact_flex_ids = {int(value) for value in contact.flex if int(value) >= 0}
            body_ids = {
                int(self._model.geom_bodyid[geom_id])
                for geom_id in geom_ids
                if geom_id >= 0
            }
            if not body_ids.intersection(flex_body_ids) and not contact_flex_ids.intersection(
                {int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_FLEX, object_id))}
            ):
                continue
            flex_side = contact_flex_ids.intersection(
                {int(mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_FLEX, object_id))}
            )
            flex_geom_side = bool(body_ids.intersection(flex_body_ids))
            if flex_geom_side:
                other_geom_id = geom_ids[1] if geom_ids[0] >= 0 and int(self._model.geom_bodyid[geom_ids[0]]) in flex_body_ids else geom_ids[0]
            else:
                other_geom_id = geom_ids[0] if geom_ids[1] == -1 else geom_ids[1]
            other_body_id = int(self._model.geom_bodyid[other_geom_id]) if other_geom_id >= 0 else 0
            other_body_name = None
            if other_body_id > 0:
                other_body_name = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_BODY, other_body_id)
            if not other_body_name:
                other_body_name = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_GEOM, other_geom_id) or f"geom_{other_geom_id}"
            contact_force = np.zeros(6, dtype=np.float64)
            mujoco.mj_contactForce(self._model, self._data, contact_index, contact_force)
            frame = np.asarray(contact.frame, dtype=np.float64).reshape(3, 3)
            force_world = frame.T @ contact_force[:3]
            contacts.append(
                {
                    "other_id": str(other_body_name),
                    "force_n": [float(value) for value in force_world],
                    "distance_m": float(contact.dist),
                }
            )
        return contacts

    def _body_contacts(self, body_id: int) -> list[dict[str, Any]]:
        assert self._model is not None and self._data is not None
        contacts: list[dict[str, Any]] = []
        for contact_index in range(int(self._data.ncon)):
            contact = self._data.contact[contact_index]
            geom_ids = (int(contact.geom1), int(contact.geom2))
            if not any(
                geom_id >= 0 and int(self._model.geom_bodyid[geom_id]) == body_id
                for geom_id in geom_ids
            ):
                continue
            first_is_body = geom_ids[0] >= 0 and int(self._model.geom_bodyid[geom_ids[0]]) == body_id
            other_geom_id = geom_ids[1] if first_is_body else geom_ids[0]
            other_body_id = int(self._model.geom_bodyid[other_geom_id]) if other_geom_id >= 0 else 0
            # Static collision proxies live directly in the MuJoCo world body.
            # Reporting only the body name turns every wall, desk, and floor
            # contact into the unhelpful string "world".  Prefer the dynamic
            # body name, otherwise expose the actual static geom name.
            other_body_name = None
            if other_body_id > 0:
                other_body_name = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_BODY, other_body_id)
            if not other_body_name:
                other_body_name = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_GEOM, other_geom_id) or f"geom_{other_geom_id}"
            contact_force = np.zeros(6, dtype=np.float64)
            mujoco.mj_contactForce(self._model, self._data, contact_index, contact_force)
            frame = np.asarray(contact.frame, dtype=np.float64).reshape(3, 3)
            force_world = frame.T @ contact_force[:3]
            contacts.append(
                {
                    "other_id": str(other_body_name),
                    "force_n": [float(value) for value in force_world],
                    "distance_m": float(contact.dist),
                }
            )
        return contacts

    def _send_state(self, client: socket.socket) -> None:
        self._seq += 1
        message = build_state_message(
            self._seq,
            self._sim_time(),
            self._state_objects(),
            scene_id=self.scene_id,
            physics_authority="MuJoCo",
        )
        self._send_message(client, message)

    def _send_error(self, client: socket.socket, error_code: str, message_text: str) -> None:
        self._send_message(client, build_error_message(self._seq, self._sim_time(), error_code, message_text))

    def _send_message(self, client: socket.socket, message: dict[str, Any]) -> None:
        encoded = encode_message(message) if message.get("type") in {"state", "command"} else json.dumps(
            message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ) + "\n"
        payload = memoryview(encoded.encode("utf-8"))
        while payload:
            try:
                sent = client.send(payload)
            except BlockingIOError:
                # The Unreal client can briefly fall behind while it uploads
                # a deformable mesh to the render thread.  A non-blocking
                # socket must wait and retry instead of killing the physics
                # thread with WinError 10035.
                if self._stop_event.is_set():
                    raise OSError("bridge stopping while sending state")
                time.sleep(0.0005)
                continue
            if sent <= 0:
                raise OSError("client socket closed while sending message")
            payload = payload[sent:]
        # A deformable state contains hundreds of vertices and is sent many
        # times per second.  Persisting every copy turns disk I/O into a
        # physics bottleneck and can grow the log by gigabytes.  Commands,
        # acknowledgements, and errors remain auditable.
        if message.get("type") != "state":
            self._write_log({"event": "send", "message": message})

    def _write_log(self, record: dict[str, Any]) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"wall_time": time.time(), **record}
        with self._log_lock:
            with self.log_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7007)
    parser.add_argument("--state-hz", type=float, default=60.0)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--physical-manifest", type=Path, default=None)
    parser.add_argument("--scene-id", default="office_0")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    server = MuJoCoBridgeServer(
        args.xml,
        host=args.host,
        port=args.port,
        state_hz=args.state_hz,
        log_path=args.log,
        physical_manifest_path=args.physical_manifest,
        scene_id=args.scene_id,
    )
    server.start()
    print(json.dumps({"host": server.host, "port": server.port, "xml": str(args.xml.resolve())}, ensure_ascii=False), flush=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
