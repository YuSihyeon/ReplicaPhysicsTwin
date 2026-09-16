# ReplicaCAD physics-twin provenance

- Dataset: [ReplicaCAD](<https://huggingface.co/datasets/ai-habitat/ReplicaCAD_dataset>)
- License: [CC BY 4.0](<https://creativecommons.org/licenses/by/4.0/>)
- Local source: `${REPLICA_ROOT}\data\raw\replica_cad`
- Scene: `apt_0`
- Geometry source: ReplicaCAD GLB render assets
- Collision source: ReplicaCAD convex-decomposition GLB assets
- Mass authority: each selected object's `object_config.json` `mass` field
- Inertia authority: derived from the collision mesh bounds when the source config has no inertia field

## Selected object templates

- `frl_apartment_bike_02`: mass=9.0 kg; config=`${REPLICA_ROOT}\data\raw\replica_cad\configs\objects\frl_apartment_bike_02.object_config.json`
- `frl_apartment_cloth_01`: mass=2.0 kg; config=`${REPLICA_ROOT}\data\raw\replica_cad\configs\objects\frl_apartment_cloth_01.object_config.json`
- `frl_apartment_cloth_02`: mass=0.6 kg; config=`${REPLICA_ROOT}\data\raw\replica_cad\configs\objects\frl_apartment_cloth_02.object_config.json`
