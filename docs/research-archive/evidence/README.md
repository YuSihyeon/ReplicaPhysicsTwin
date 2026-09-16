# Replica Physics Twin

Reproducible physics-twin prototype that connects ReplicaCAD scene assets to
MuJoCo dynamics and Unreal Engine visualization/input.

## Current pipeline

```text
ReplicaCAD (apt_0)
  -> Python scene compiler (GLB/config parsing and coordinate conversion)
  -> MuJoCo MJCF + collision meshes + physical manifest
  -> newline-delimited JSON/TCP bridge
  -> Unreal procedural mesh visual client and interaction controls
```

MuJoCo is the physics authority. Unreal displays the state and sends user
input; it does not independently simulate the selected objects.

The current ReplicaCAD experiment uses three dataset-native objects:

- `frl_apartment_bike_02` (`bike_02`, 9.0 kg)
- `frl_apartment_cloth_01` (`cloth_01`, 2.0 kg)
- `frl_apartment_cloth_02` (`cloth_02`, 0.6 kg)

ReplicaCAD provides the render assets, collision assets, scene transforms, and
source mass values. The inertia, friction, and cloth material values are
recorded as derived or experimental values in the generated manifest.

## Reproduce locally

Requirements:

- Python 3.11
- MuJoCo Python package
- Git LFS
- Unreal Engine 5.7 for the visual client
- ReplicaCAD dataset (downloaded separately; it is not committed here)

From PowerShell:

```powershell
Set-Location C:\path\to\ReplicaPhysicsTwin
$env:PYTHONPATH = Join-Path (Get-Location) 'src'

.\scripts\download_replica_cad.ps1
python .\scripts\build_replica_cad_pipeline.py `
  --dataset-root .\data\raw\replica_cad `
  --scene apt_0 `
  --output-root .\outputs\replica_cad

.\scripts\run_replica_cad.ps1
```

Open `unreal/ReplicaPhysicsTwin.uproject` in Unreal Engine after the bridge is
running. Generated meshes, MJCF, and runtime reports stay local and are
intentionally ignored by Git.

## Interaction

- Click: replace the selection with one object.
- Shift+click: add/remove an object from the selection.
- Click-drag: apply a finite physical push to the object under the cursor.
- `P`: pause/resume the MuJoCo bridge.
- `R`: reset the scene.
- `T`: lift/drop the selected object.
- `I`: apply an impulse to the selected object.
- Right-mouse drag: look around; `WASD/QE`: move the camera.

## Repository scope

This repository contains source code, tests, scripts, configuration, reports,
and Unreal C++ project files. It does not contain the 32+ GB ReplicaCAD source
checkout, generated meshes/MJCF/logs, or Unreal build caches. Run the download
and build scripts to recreate those artifacts.

Dataset: [aihabitat/ReplicaCAD_dataset](https://huggingface.co/datasets/ai-habitat/ReplicaCAD_dataset)

License: ReplicaCAD assets are distributed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
