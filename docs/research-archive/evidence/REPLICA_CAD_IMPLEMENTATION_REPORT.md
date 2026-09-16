# ReplicaCAD reimplementation report

The active replacement scene is compiled from the open ReplicaCAD `apt_0`
scene.  The selected objects use their source GLB render assets and
convex-decomposition collision assets; they are not replaced by primitive
cubes.  The room shell uses stable floor/ceiling/wall box proxies for MuJoCo
collision because a whole concave room mesh is not a valid single convex
collision shape.

The compiled environment contains 110 non-selected source objects as static
MuJoCo collision bodies in addition to the stage.  Of those, 81 use the
ReplicaCAD convex-decomposition GLB and 29 use the bounding-box method that
the corresponding ReplicaCAD object config explicitly requests.  Unreal uses
the source render GLBs/material colors for the visual scene; MuJoCo is the
authoritative physics state.

## Current selected objects

| Dataset template | Runtime body | Source mass |
|---|---|---:|
| `frl_apartment_bike_02` | `replica_bike_02_100` | 9.0 kg |
| `frl_apartment_cloth_01` | `replica_cloth_01_103` | 2.0 kg |
| `frl_apartment_cloth_02` | `replica_cloth_02_96` | 0.6 kg |

These values are copied from the ReplicaCAD object configuration and are
verified against `mjModel.body_mass` during every pipeline build. The
generated manifest records the source value, MuJoCo value, and a passed
validation flag for every movable body. Inertia is derived from the dataset
collision-mesh bounds because these configs do not provide a rigid-body
inertia tensor.

The two cloth selections are modeled as MuJoCo 2D `flexcomp` grids, not as
rigid freejoint meshes. Each has 240 physical vertices, `elastic2d="both"`
(stretching plus bending), thickness, Young's modulus, Poisson ratio, damping,
air density/viscosity, and a permanent weld along the hanging edge. The bridge
also distributes area-based wind drag over the current cloth triangles before
each MuJoCo step, and Unreal remaps the source high-resolution garment mesh to
the deformed flex surface while preserving its local scan depth. Source mass
remains authoritative: the flex node masses sum to `2.0 kg` and `0.6 kg`.
ReplicaCAD does not provide fabric Young's modulus, thickness, or drag
coefficients, so those fields are explicit calibration priors in the manifest,
not claims about measured textile properties.

The dataset has no exact `tissue_box` or `desk_organizer` template in this
scene.  The current visible-object experiment therefore uses the source-native
bicycle and hanging-cloth identities instead of disguising primitives as a
tissue box or organizer. These are the actual ReplicaCAD render meshes and
collision meshes, with their source dimensions and masses retained.

## Run

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_replica_cad.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run_replica_cad.ps1
```

Run Unreal with the project under `unreal/`; it reads
`outputs/replica_cad/metadata/replica_cad_interaction.json` and the compiled
`RPTMESH2` visual files.

## Interaction contract

- Normal click: replace the selection; clicking the selected object begins a
  finite-force MuJoCo drag.
- Shift+click: toggle selection only; it does not start a drag.
- `I`: apply a 0.1 N·s +X impulse to selected objects.
- `T`: lift selected objects and let gravity drop them.
- `R`: reset the MuJoCo scene to the compiled source poses.
- `P`: pause/unpause MuJoCo.
- RMB + mouse/WASD/QE: move and orbit the Unreal camera.

The initial camera frames the bike and hanging garments from a short interior
view using the dynamic-object bounds; the full room bounds are retained only as
a safety limit. It uses a 72-degree field of view so the objects remain
recognizable without clipping. Manual RMB + mouse/WASD/QE control remains
active after startup.

Each selected object also has a non-rendering MuJoCo mocap target and a
disabled weld constraint. The bridge uses these handles for finite-force mouse
dragging, so dragging remains mass-sensitive rather than teleporting.

The red/yellow/green lines from earlier runs are collision/axis diagnostics.
They are disabled in the normal ReplicaCAD presentation.

## Verification result

- Unreal `ReplicaPhysicsTwinEditor` build: succeeded.
- Python focused regression checks: passed for the Unreal input contract and the
  ReplicaCAD source-geometry compiler.
- ReplicaCAD source-to-MuJoCo mass verification: passed for `9.0 kg`, `2.0 kg`,
  and `0.6 kg`.
- MuJoCo model: `593` bodies, `117` geoms, `2` flexes / `480` flex vertices,
  `1` free joint, and `25` equality constraints (including the two hanging
  edges and the bicycle grab weld).
- Deterministic gravity/contact check: passed for all three selected bodies.
- Selected bicycle to the ReplicaCAD room-shell environment contact check: passed.
- Active bridge: `apt_0`, physics authority `MuJoCo`, port `7007`.
