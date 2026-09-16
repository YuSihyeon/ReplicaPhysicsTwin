# Environment Report

- 작성 시각: 2026-08-11T11:32:24+09:00
- Phase: 0 — 환경 읽기 전용 점검
- 상태: **COMPLETE_WITH_WARNINGS**
- 프로젝트 경로: `${REPLICA_ROOT}`
- 사용자 승인: 2026-08-11, Phase 0 승인

이 보고서는 Phase 0 점검 결과를 기록한다. 이번 점검에서 기존 `RobotLLM` 프로젝트, Replica 분할 다운로드 파일, Replica 원본·추출 경로를 수정하거나 삭제하지 않았다. Phase 1 데이터 추출은 시작하지 않았다.

## 1. 확정된 목표와 보호 범위

- MVP 대상은 Replica `office_0`의 `tissue_box`이다.
- MuJoCo가 중력·충돌·마찰·rigid-body 상태의 유일한 물리 권위다.
- Unreal Engine은 렌더링·입력·raycast·MuJoCo 결과 표시만 담당한다.
- Unreal Chaos Physics로 같은 동적 물체를 다시 계산하지 않는다.
- `${ROBOTLLM_ROOT}`은 읽기 전용 참조 대상으로 보호한다.
- Replica 원본은 직접 수정하지 않고, 파생 결과만 별도 경로에 기록한다.

## 2. 경로 상태

| 대상 | 확인 결과 | 비고 |
|---|---|---|
| 기존 프로젝트 | 존재 | `${ROBOTLLM_ROOT}` |
| 신규 프로젝트 | 존재 | `${REPLICA_ROOT}` |
| 기존 프로젝트 Git 저장소 | 루트에 `.git` 없음 | 브랜치·커밋 작업을 수행하지 않음 |
| 신규 프로젝트 Git 저장소 | 루트에 `.git` 없음 | 저장소 초기화를 수행하지 않음 |
| 신규 Unreal `.uproject` | 없음 | Unreal 측 골격은 아직 생성하지 않음 |

신규 프로젝트에는 다음 기존 골격이 있다.

```text
configs/
data/
outputs/
scripts/
src/
tests/
ENVIRONMENT_REPORT.md
README.md
pyproject.toml
```

## 3. 런타임 점검

| 항목 | 실제 결과 | 판정 |
|---|---|---|
| OS | Windows 11 Pro 64-bit, `10.0.26200` | PASS |
| Unreal Engine | `C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe`, `++UE5+Release-5.7-CL-51494982` | PASS |
| 기본 Python | CPython `3.13.10`, `<PYTHON313_EXECUTABLE>` | PASS_WITH_WARNING |
| uv | `uv 0.11.29` | PASS |
| uv Python 3.11 | CPython `3.11.15`, `<UV_PYTHON311_EXECUTABLE>` | PASS |
| Python 3.13 MuJoCo | `mujoco==3.10.0` import 성공 | PASS |
| Python 3.13 `mj_step` | MJCF compile, 1 step, finite state 확인 성공 | PASS |
| Python 3.11 MuJoCo | `mujoco` 및 `numpy` 미설치 | NEEDS_DECISION |

Python 3.13에서 수행한 최소 실행 결과:

```text
mujoco_version: 3.10.0
mj_step: PASS
z_before: 1.0
z_after: 0.99996076
sim_time: 0.002
finite_state: True
```

`pyproject.toml`은 `>=3.11,<3.12`를 요구하므로, Phase 2 전에 다음 중 하나를 명시적으로 결정해야 한다.

1. Python 3.11 환경에 필요한 MuJoCo·NumPy 의존성을 설치한다.
2. 현재 정상 동작하는 Python 3.13 환경을 프로젝트 실행 기준으로 예외 승인한다.

환경 변경이나 패키지 설치는 별도 사용자 확인 없이 수행하지 않는다.

## 4. 시스템 자원

점검 시 스냅샷:

- CPU: Intel Core Ultra 7 265F, 20 physical/logical cores
- RAM: 총 31.65GB, 사용 가능 약 14.9GB
- GPU: NVIDIA GeForce RTX 5060 Ti, 16,311MiB, 사용 가능 약 12,384MiB
- NVIDIA 드라이버: `591.55`
- CUDA backend: 탐지됨
- C: 총 약 952.93GiB, 사용 가능 약 524.83GiB

약 34GB의 Replica 분할 파일이 이미 있으므로, 추출·검증 시 메모리에 전체 아카이브를 적재하지 않고 스트리밍 방식을 유지한다.

## 5. 기존 RobotLLM 읽기 전용 분석

확인한 주요 파일과 위치:

- `RobotLLM.uproject`
- `Plugins\UnrealRoboticsLab\UnrealRoboticsLab.uplugin`
- `Plugins\UnrealRoboticsLab\Source\URLab\URLab.Build.cs`
- `Plugins\UnrealRoboticsLab\Source\URLab\Public\MuJoCo\Core\AMjManager.h`
- `Plugins\UnrealRoboticsLab\Source\URLab\Private\MuJoCo\Core\AMjManager.cpp`
- `Plugins\UnrealRoboticsLab\Source\URLab\Public\Bridge\BridgeServer.h`
- `Plugins\UnrealRoboticsLab\Source\URLab\Private\Bridge\BridgeServer.cpp`
- `Plugins\UnrealRoboticsLab\Source\URLab\Public/Private\Bridge\*`
- `Plugins\UnrealRoboticsLab\Source\URLab\Public/Private\Transport\*`
- `Plugins\UnrealRoboticsLab\Source\URLab\Public/Private\MuJoCo\Core\*`
- `Plugins\UnrealRoboticsLab\docs\concepts\networking.md`
- `Plugins\UnrealRoboticsLab\docs\concepts\architecture.md`

확인된 기존 구조:

- `AMjManager`가 Unreal 내부 MuJoCo 시뮬레이션과 매니저 수명주기를 관리한다.
- `UMjPhysicsEngine`이 MuJoCo model/data와 step loop를 소유한다.
- `UURLabBridgeServer`가 ZMQ RPC 및 shared-memory transport를 관리한다.
- 기본 ZMQ RPC endpoint는 `tcp://0.0.0.0:5559`, 상태 publish는 `tcp:5555`다.
- MuJoCo·CoACD·libzmq native install이 기존 플러그인 아래에 존재한다.

따라서 기존 URLab 코드는 통신·좌표·MuJoCo API 참고 자료로만 사용하고, 새 프로젝트에 직접 연결하거나 수정하지 않는다.

## 6. Replica 데이터 현재 상태

확인 경로: `${REPLICA_ROOT}\data`

- `data\downloads\replica_v1`에 공식 릴리스 분할 파일 17개가 존재한다.
- 분할 파일 예상 크기 검사는 `complete: true`다.
- `additional_habitat_configs.zip`도 존재한다.
- 현재 분할 파일과 보조 ZIP의 합계는 약 33.9GB다.
- `data\raw\replica_v1\office_0` 디렉터리는 존재하지만 파일 수는 0개다.
- [REPLICA_DOWNLOAD_REPORT.md](outputs/reports/REPLICA_DOWNLOAD_REPORT.md)의 상태는 `DOWNLOAD_IN_PROGRESS`다.

따라서 Replica 데이터는 **다운로드 파일 존재는 확인됐지만 `office_0` 추출·필수 파일 검증은 완료되지 않은 상태**다.

## 7. Phase 0에서 변경한 파일

- `ENVIRONMENT_REPORT.md`: 현재 점검 결과로 갱신
- `RUN_LOG.md`: Phase 0 실행 기록으로 신규 생성

다음 파일은 아직 생성·수정하지 않았다.

- `DATASET_REPORT.md`
- `PROTOCOL.md`
- `PHYSICS_VALIDATION_REPORT.md`
- `UNREAL_VISUAL_CHECKLIST.md`
- `MVP_REPORT.md`
- MuJoCo simulation server, bridge, Unreal receiver, `.uproject`

## 8. 위험과 다음 승인 게이트

1. Python 3.11과 MuJoCo 의존성 불일치
2. Replica `office_0` 추출 미완료
3. 신규 Unreal 프로젝트 및 receiver 미생성
4. 기존 URLab native library를 새 프로젝트에 자동 재사용할 경우 프로젝트 보호 범위를 침범할 위험
5. 대규모 추출 작업에 충분한 디스크는 있으나, 사용자 승인과 실제 데이터 이용 조건 확인이 필요

Phase 0은 완료되었다. Phase 1을 시작하려면 사용자가 Replica 이용 조건 확인, 데이터 추출·검증 진행 승인, 실제 원본 경로를 확인해야 한다. Phase 1 승인 전에는 분할 파일을 추출하거나 `DATASET_REPORT.md`를 생성하지 않는다.
