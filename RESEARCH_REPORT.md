# Replica Physics Twin

## 영상과 설명

영상 제목이나 미리보기를 누르면 해당 MP4 파일을 열 수 있습니다.

| 영상 | 설명 |
|---|---|
| [**Replica 자전거·의류 물리 시연**](docs/research-archive/media/replica-demo-preview.mp4)<br>[![Replica 자전거·의류 물리 시연 미리보기](docs/research-archive/media/replica-poster.jpg)](docs/research-archive/media/replica-demo-preview.mp4) | 자전거 이동과 의류 변형을 보여주는 약 6.93초 시연입니다. 원본 파일명에 reverse가 있어 순방향 물리 시간이나 실시간 처리 성능을 이 영상만으로 확정하지 않습니다. [원본 MP4](docs/research-archive/media/replica-demo-original.mp4) |

## 한국어 연구 정리와 데모 · 2026-09-16

- [연구 의도·도구 선정·과정·결과·분석·후속 과제](docs/research-archive/README.ko.md)
- [영상 보기와 원본 MP4](docs/research-archive/MEDIA.md)
- [현재 생성 모델과 과거 보고서의 차이](docs/research-archive/evidence/inspected-manifest-summary.json)
- [2026-09-16 재검증 기록](docs/research-archive/evidence/reverified-physics-2026-09-16.json)
- [전체 원본 데이터·복원 안내](DATA_AND_RESTORE.md)

현재 보존된 생성 모델은 337 bodies / 150 geoms / 224 flex vertices로,
아래 과거 구현 보고서에 적힌 구성과 다릅니다. 이번 기존 검증 스크립트 재실행은
자전거 낙하 판정에서 실패했습니다. 과거 PASS와 현재 재검증 상태를 구분해 읽어주세요.


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
