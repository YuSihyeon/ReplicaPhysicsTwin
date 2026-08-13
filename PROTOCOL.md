# MuJoCo ↔ Unreal Bridge Protocol

## Transport

- TCP on `127.0.0.1:7007` by default.
- UTF-8 newline-delimited JSON (NDJSON); each message is one JSON object followed by `\n`.
- The bridge accepts one Unreal client at a time. A disconnected client can reconnect without restarting MuJoCo.
- Default state publication rate is 60Hz. MuJoCo remains the only source of object pose, velocity, gravity, contact, and friction results.
- The Unreal side must never enable Chaos simulation for the mapped dynamic actor. It only applies the latest received transform.

## Shared fields

- `schema_version`: integer, currently `1`.
- State `seq`: monotonically increasing bridge publication sequence.
- `sim_time`: MuJoCo simulation time in seconds.
- State `units`: always `meter`.
- State `up_axis`: always `Z`.

## State message

```json
{
  "type": "state",
  "schema_version": 1,
  "seq": 1240,
  "sim_time": 2.516,
  "units": "meter",
  "up_axis": "Z",
  "objects": [
    {
      "id": "tissue_box",
      "position_m": [0.0, 0.0, 0.12],
      "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
      "linear_velocity_mps": [0.0, 0.0, 0.0],
      "angular_velocity_rps": [0.0, 0.0, 0.0]
    }
  ]
}
```

The quaternion order on the wire is MuJoCo's `w, x, y, z`. The Phase 3 receiver maps it to Unreal's `FQuat(x, y, z, w)` and converts position from meters to centimeters.

## Command messages

Commands are validated before execution. Invalid commands receive an `error` message and do not close the connection.

### Apply a center-of-mass impulse

```json
{
  "type": "command",
  "schema_version": 1,
  "command": "apply_impulse",
  "object_id": "test_box",
  "impulse_ns": [0.0, 0.0, 1.0]
}
```

`point_m` is optional. When supplied, the bridge applies the impulse at that world-space point through MuJoCo's Cartesian force application for one timestep.

### Reset and pause

```json
{"type":"command","schema_version":1,"command":"reset"}
{"type":"command","schema_version":1,"command":"pause","paused":true}
```

`pause` with `paused:false` resumes stepping. `reset` restores the MJCF `initial` keyframe and resumes stepping.

### Phase 6 tissue-box lift/drop

The Phase 6 bridge loads `outputs/mjcf/office0_tissue_box.xml`, publishes the freejoint body as `tissue_box`, and accepts a deterministic lift command. The body is raised by the requested height and then MuJoCo continues stepping under gravity.

```json
{
  "type": "command",
  "schema_version": 1,
  "command": "lift_drop",
  "object_id": "tissue_box",
  "lift_height_m": 0.30
}
```

`lift_height_m` is finite, non-negative, and limited to 1 meter by the protocol validator. Unreal's `T` key sends the Phase 6 value `0.30`.

## Responses

Successful commands receive an acknowledgement:

```json
{
  "type": "ack",
  "schema_version": 1,
  "seq": 1240,
  "sim_time": 2.516,
  "command": "apply_impulse",
  "object_id": "test_box"
}
```

Invalid JSON, schema, command, vector, or object IDs receive:

```json
{
  "type": "error",
  "schema_version": 1,
  "seq": 1240,
  "sim_time": 2.516,
  "error_code": "invalid_command",
  "message": "unknown object_id: missing_box"
}
```

## Unreal mapping contract

For Phase 3 the coordinate basis is kept as X/Y/Z with Z up:

- `FVector(position_m.x * 100, position_m.y * 100, position_m.z * 100)`.
- `FQuat(quaternion_wxyz.x, quaternion_wxyz.y, quaternion_wxyz.z, quaternion_wxyz.w)`.
- The actor's `SetActorTransform` is the only dynamic transform write.
- `SetSimulatePhysics(false)` and `SetCollisionEnabled(ECollisionEnabled::NoCollision)` are required on the demo dynamic actor.
- Incoming `seq` values older than the last applied sequence are ignored.

## Logging and reconnect

The Python bridge writes JSONL connection, command, state-send, error, and disconnect events when `--log` is supplied. The Unreal receiver logs connect, reconnect, parse, stale-sequence, and socket errors through `LogMuJoCoBridge`.
