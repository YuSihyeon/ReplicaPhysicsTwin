# MuJoCo-authoritative physical object pipeline

## Current result

The approved MVP pipeline is implemented for `office_0`:

1. Sparse recognition selects candidate objects from semantic metadata and mesh geometry.
2. A physical manifest records measured size plus estimated or overridden mass, inertia, friction, and provenance.
3. Static room/furniture collision proxies and three selected movable objects are compiled into one MuJoCo MJCF scene.
4. MuJoCo publishes pose, velocity, contact, and physical-property telemetry over the TCP bridge.
5. Unreal is a visual receiver. It does not run Chaos physics and does not author object motion.
6. Clicking and dragging sends `grab_begin`, `grab_update`, and `grab_end`. MuJoCo mocap/equality constraints and `mj_step` produce the actual motion and contacts.

## Automated evidence

Run from `${REPLICA_ROOT}`:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -X utf8 scripts/build_office0_interaction_scene.py
python -X utf8 scripts/verify_physical_pipeline.py
pytest -q
```

The validation report is written to:

`outputs/reports/physical_pipeline_validation.json`

The current automated result is `automated_passed=true`. It also reports
`property_provenance.status=NEEDS_MEASUREMENT` because tissue mass and friction
are still priors/MVP estimates, not laboratory measurements.

## Run the live bridge and Unreal

Start the bridge in one PowerShell window:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_office0_interaction.ps1
```

Build the Unreal editor target after closing the editor or using Live Coding's
compile command:

```powershell
& 'C:\Program Files\Epic Games\UE_5.7\Engine\Build\BatchFiles\Build.bat' `
  ReplicaPhysicsTwinEditor Win64 Development `
  '${REPLICA_ROOT}\unreal\ReplicaPhysicsTwin.uproject' -WaitMutex
```

Then open `unreal\ReplicaPhysicsTwin.uproject` and press **Play**.

## Expected interaction

- The semantic meshes for `tissue_box`, orange `desk_organizer`, and blue `chair_4` appear in the room.
- Left click selects one object and begins a group drag; **Shift+click** only adds/removes selection.
- The on-screen property line shows object id, `source=MuJoCo`, size, mass, velocity, and contact count.
- Dragging a selected object moves a MuJoCo mocap target. The Unreal actor is only updated from returned MuJoCo state.
- Releasing the mouse disables the equality constraint. Gravity, friction, desk contact, and dynamic-object contact continue in MuJoCo.
- `R` resets the MuJoCo keyframe, `T` runs the lift/drop test on the selection, `P` pauses/resumes, `I` applies an impulse, and `Esc` clears selection.

## Remaining acceptance gate

The only remaining gate is a live Unreal Play check after the Development build:

- no magenta missing-material actor;
- all three dynamic semantic meshes are visible at their physical rest positions;
- Shift+click selects the intended group without starting a grab;
- drag causes selected objects to respond through MuJoCo contact;
- release leaves them settling instead of snapping or continuing an Unreal-only trajectory;
- Output Log contains the MuJoCo bridge connection and no Chaos simulation errors.
