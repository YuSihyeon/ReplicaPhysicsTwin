# Phase 3 MuJoCo ↔ Unreal 통신 검증 보고서

## 상태

**COMPLETE_WITH_USER_VERIFICATION — 자동·headless 검증 및 Unreal Play 통신 확인 완료**

Phase 3 구현은 새 프로젝트 `C:\URLabWorkspace\ReplicaPhysicsTwin\unreal`에만 추가했습니다. 기존 `C:\URLabWorkspace\RobotLLM`과 그 Unreal plugin은 읽기 전용으로 유지했습니다.

## 구현

- TCP/NDJSON protocol: `PROTOCOL.md`
- MuJoCo server: `src/replica_physics_twin/bridge_server.py`
- Python protocol validation: `src/replica_physics_twin/bridge_protocol.py`
- 실행 스크립트: `scripts/run_phase3_bridge.ps1`
- UE 5.7 receiver: `unreal/Source/ReplicaPhysicsTwin/Public/Bridge/MuJoCoStateReceiverComponent.h`
- UE message parser/mapping: `unreal/Source/ReplicaPhysicsTwin/Public/Bridge/MuJoCoBridgeTypes.h`
- UE visual-only demo actor: `unreal/Source/ReplicaPhysicsTwin/Public/Bridge/MuJoCoBridgeDemoActor.h`
- UE demo scene/GameMode: `unreal/Source/ReplicaPhysicsTwin/Public/Bridge/MuJoCoBridgeDemoGameMode.h`

## 권위·좌표·물리 분리

- MuJoCo만 중력·접촉·마찰·rigid-body state를 계산합니다.
- 상태 메시지는 `schema_version=1`, `seq`, `sim_time`, `units=meter`, `up_axis=Z`를 포함합니다.
- Unreal은 `position_m × 100`으로 centimeter 변환하고 `wxyz → FQuat(x,y,z,w)`로 변환합니다.
- demo box는 `SetSimulatePhysics(false)` 및 `NoCollision`입니다.
- Unreal은 수신 state의 `SetActorTransform`만 호출하며 자체 동적 물리를 계산하지 않습니다.
- 오래된 sequence는 무시하고, 잘못된 command는 error 응답 후 연결을 유지하며, 끊어진 TCP client는 재접속할 수 있습니다.

## 검증 증거

- Python bridge protocol/server tests: **5 passed**
- UE 5.7 Editor target build: **Succeeded**
- UE 5.7 Game target build: **Succeeded**
- UE automation `ReplicaPhysicsTwin.Bridge.MappingAndSequence`: **Success, EXIT CODE: 0**
- CLI bridge integration: state 수신, invalid object error, impulse ACK, reconnect state 수신 확인
- headless UE runtime:
  - `LogMuJoCoBridge: Connected to MuJoCo bridge 127.0.0.1:7007 for object test_box`
  - bridge state seq 1~6 기록, `sim_time` 0.0→0.044 증가

실행 로그:

- `outputs/reports/phase3/bridge_cli.jsonl`
- `outputs/reports/phase3/bridge_runtime_7007_v2.jsonl`
- `outputs/reports/phase3/ue_runtime_7007_v2.stdout.log`

## 사용자 확인 결과

사용자가 Unreal Play에서 박스 낙하와 `I` 키 수평 impulse가 정상 동작함을 확인했습니다. 따라서 Phase 3 통신·좌표·스케일 검증을 승인하고 Phase 4 공간 시각화로 진행합니다.

## 남은 참고 항목

자동 검증은 통신·파싱·빌드·headless 수신까지만 증명합니다. 다음 항목은 이후 회귀 확인 시 사용할 수 있습니다.

- 방향·회전이 실제 화면에서 올바른가
- meter→centimeter 스케일이 시각적으로 현실적인가
- 박스가 MuJoCo state 외의 방식으로 움직이지 않는가
- `I/R/P` 입력 동작과 reconnect가 화면에서 예상대로 보이는가

상세 절차는 `UNREAL_VISUAL_CHECKLIST.md`에 있습니다.
