# Phase 6 — `tissue_box` 동적 물체

## 상태

**IMPLEMENTED / NEEDS_UNREAL_USER_VERIFICATION**

## 대상 고정

- Replica `office_0` candidate object ID: `28`
- semantic class: `tissue-paper`
- wire object ID: `tissue_box`
- 원본 mesh와 semantic mesh는 수정하지 않았습니다.

## 기하와 초기화

semantic mesh에서 object ID 28의 실제 face vertex bounds를 측정했습니다.

```text
normalized size: 0.1701517 × 0.1508722 × 0.2122760 m
Unreal display size: 17.0 × 15.1 × 21.2 cm
support proxy: desk_58
rest center z: 0.7710649 m
initial/reset center z: 0.7710649 m
lift height: 0.3000000 m
```

시작·reset 위치는 derived scene manifest의 candidate ID와 semantic mesh bounds에서 계산한 `desk_58` 상판 rest 위치입니다. `T` 명령이 rest 위치에서 30cm를 더해 lift/drop을 시작하며, 초기 물체가 책상·바닥과 겹치지 않는지 자동 검사합니다.

시각 메시도 분리했습니다. `office_0_visual_static.rptmesh`에서는 object 28을 제외하고, `office_0_tissue_box.rptmesh`에는 object 28의 semantic face만 포함해 Unreal 동적 actor가 실제 형상을 따라가도록 했습니다.

## 물리 파라미터 provenance

- 질량: `0.25kg`, Replica에 질량 메타데이터가 없어 MVP 추정값
- 관성: 측정 크기의 균일 밀도 box inertia로 계산
- 마찰: `[0.8, 0.1, 0.1]`, 고정 프록시와 공유하는 MVP 접촉 추정값
- restitution: `0.05` 추정값으로 기록; MuJoCo XML에서는 `solref/solimp` 접촉 파라미터를 사용
- 물리 권위: MuJoCo
- Unreal dynamic actor: collision과 자체 물리 비활성, state를 받아 transform만 적용

## 자동 검증

```powershell
$env:PYTHONPATH='src'
python scripts/build_office0_tissue_box.py
python -m pytest -q
```

결과:

- Phase 6 lift/drop: `passed=true`
- first contact: step `125` (`0.25s`)
- contact: `desk_58`
- final z error: 약 `3.62e-6m`
- final speed: 약 `5.52e-9m/s`
- Python 전체 테스트: `24 passed`

산출물:

- `outputs/mjcf/office0_tissue_box.xml`
- `outputs/metadata/office0_tissue_box.json`
- `outputs/reports/phase6/phase6_tissue_box_summary.json`
- `outputs/reports/phase6/phase6_tissue_box_lift_drop.jsonl`
- `outputs/reports/phase6/bridge.jsonl` (Unreal bridge 실행 시)

## Unreal 조작

1. `scripts/run_phase6_tissue_box.ps1`로 bridge를 실행합니다.
2. Unreal Editor에서 Play를 누릅니다.
3. `T`: 30cm lift/drop
4. `R`: reset
5. `P`: pause/resume
6. `I`: +X impulse

다음 단계로 넘어가기 전 사용자는 cyan tissue_box가 한 개만 보이고, T 키 후 MuJoCo 중력으로 떨어져 desk_58 위에 정지하는지 확인해야 합니다.
