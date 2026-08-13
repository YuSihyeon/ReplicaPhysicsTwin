# Phase 2 MuJoCo 물리 검증 보고서

## 상태

**PASS — Phase 3(Unreal bridge/시각화) 시작 전 사용자 승인 대기**

검증 범위는 MuJoCo 단독입니다. Unreal Engine, Chaos 물리, 기존 `C:\URLabWorkspace\RobotLLM`에는 접근하거나 변경하지 않았습니다.

## 검증 모델

- MJCF: `outputs/mjcf/phase2_box_drop.xml`
- 물리 권위: MuJoCo
- 중력: `[0, 0, -9.81] m/s²`
- timestep: `0.002 s`
- 바닥: z=0 평면
- 박스: 반높이 `0.05 m`, 질량 `0.1 kg`, 자유 관절(freejoint)
- 초기 박스 중심 높이: `0.35 m` — 바닥에서 30cm 높이
- 접촉 설정: friction `0.8 0.1 0.1`, `solref="0.005 1"`

## 자동 검증 결과

실행 요약: `outputs/reports/phase2/phase2_summary.json`

### 낙하·접촉·정착

| 항목 | 결과 |
|---|---:|
| 전체 기록 | 2,001 samples / 4.0 s |
| 첫 접촉 | 0.25 s |
| 접촉 활성 samples | 1,850 |
| 초기 z | 0.35 m |
| 최소 중심 z | 0.0457808 m |
| 정지 중심 z | 0.05 m |
| 최대 바닥 기준 오차 | 0.0042192 m (4.22 mm) |
| 최종 z | 0.0499964 m |
| 정착 구간 최대 속도 | `1.02e-15 m/s` |
| 정착 구간 최대 위치 오차 | `3.59e-6 m` |
| 자유낙하 최대 오차 | 0.002433 m |
| 유한 상태·시간 단조성 | PASS |

`floor_not_passed`는 박스의 하단이 바닥을 넘는 이산 접촉 오차를 5mm 이내로 제한하는 조건입니다. 실제 최대 오차는 4.22mm였고, 정착 후에는 바닥 높이에 수렴했습니다.

### 수평 impulse

`[0.1, 0, 0] N·s`를 질량 `0.1 kg` 박스에 적용했습니다.

- 예상 Δv: `[1.0, 0, -0.01962] m/s`
- 측정 Δv: `[1.0, 0, -0.01962] m/s`
- 각 축 오차: `0`
- 판정: PASS

Z 속도가 0이 아닌 것은 impulse가 실패한 것이 아니라, impulse를 적용한 뒤 한 timestep 동안 중력이 작용했기 때문입니다.

## 실패 원인 분리와 수정 근거

초기 `solref="0.02 1"` 설정은 접촉 순간 최대 중심 침투가 17.02mm였습니다. 같은 모델에서 접촉 시간 상수만 바꾼 실험은 다음과 같았습니다.

| 설정 | 최대 중심 침투 |
|---|---:|
| `solref="0.02 1"` | 17.02 mm |
| `solref="0.01 1"` | 8.43 mm |
| `solref="0.005 1"` | 4.22 mm |
| `solref="0.002 1"` | 4.11 mm |

`implicitfast`만 바꾼 경우에는 17.02mm가 유지됐고, timestep만 1ms로 줄인 경우에도 기존 `solref`에서는 15.88mm가 남았습니다. 따라서 이번 MVP에서는 timestep을 바꾸지 않고 접촉 응답 시간 상수를 `0.005`로 조정했습니다. 2ms 이산 스텝에서의 최초 접촉 샘플링 오차는 별도 허용치로 계측하고 숨기지 않습니다.

## 산출물

- `src/replica_physics_twin/physics_validation.py`
- `tests/test_physics_validation.py`
- `outputs/mjcf/phase2_box_drop.xml`
- `outputs/reports/phase2/phase2_drop.jsonl`
- `outputs/reports/phase2/phase2_impulse.jsonl`
- `outputs/reports/phase2/phase2_summary.json`

## 재현 검증

- Python 테스트: **12 passed**
- PowerShell 다운로드 스크립트 startup path test: **PASS**
- Production MuJoCo validation summary: **passed=true**

다음 단계는 사용자가 이 보고서의 MuJoCo 결과를 승인한 뒤에만 진행합니다. Phase 3에서는 Replica 좌표계·스케일을 Unreal 표시용으로 연결하고, 동적 물체의 물리 계산은 계속 MuJoCo에만 두어야 합니다.
