# Unreal Play 확인 체크리스트

Phase 3 상태: **COMPLETE_WITH_USER_VERIFICATION**
Phase 4 상태: **COMPLETE_WITH_USER_VERIFICATION**
Phase 5 상태: **COMPLETE_WITH_SCENE_LIMITATION**
Phase 6 상태: **NEEDS_USER_VERIFICATION**

## 실행

1. PowerShell에서 프로젝트 루트로 이동합니다.
2. Phase 6 bridge를 먼저 실행합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_phase6_tissue_box.ps1
```

3. `unreal\ReplicaPhysicsTwin.uproject`를 Unreal Engine 5.7로 엽니다.
4. Editor에서 **Play**를 누릅니다.

bridge는 Unreal client가 연결된 뒤 MuJoCo 낙하를 진행합니다. 연결이 끊기면 receiver가 0.5초 간격으로 재접속합니다.

## Play 화면에서 확인할 항목

- [ ] 바닥과 박스가 화면에 보인다.
- [ ] 박스가 초기 위치에서 시작하고 바닥 위에 정지한다.
- [ ] 박스 크기가 10cm cube로 보인다.
- [ ] 박스가 MuJoCo의 Z 방향 낙하 결과와 같은 방향으로 움직인다.
- [ ] 박스 위치가 meter→centimeter 변환으로 과도하게 크거나 작지 않다.
- [ ] 회전이 뒤집히지 않는다.
- [ ] `I` 키를 누르면 `[+X]` impulse가 MuJoCo로 전달되고 박스가 +X 방향으로 움직인다.
- [ ] `R` 키를 누르면 MuJoCo의 desk rest keyframe으로 reset된다.
- [ ] `P` 키로 MuJoCo pause/resume이 된다.
- [ ] Unreal에서 박스가 자체 중력이나 Chaos 충돌로 별도 계산되지 않는다.
- [ ] Output Log에 `LogMuJoCoBridge` 연결 오류가 없다.

## Phase 6 — tissue_box Play 확인

Phase 6 artifact는 `object_id=28`을 `tissue_box`으로 사용합니다. Unreal은 정적 방 메시지에서 분리한 semantic tissue-box 형상을 동적 actor로 표시하며, 크기는 `17.0 × 15.1 × 21.2cm`입니다. 시작·reset은 `desk_58` 상판 rest 위치입니다.

- [ ] Play 시작 시 semantic `MuJoCo tissue_box`가 한 개만 보인다.
- [ ] 시작 위치가 책상 내부나 바닥 아래가 아니다.
- [ ] `T` 키를 누르면 tissue_box가 30cm 올라간 뒤 중력으로 떨어진다.
- [ ] 놓은 뒤 `desk_58` 상판 위에서 정지한다.
- [ ] 물체가 바닥·책상을 뚫지 않는다.
- [ ] Unreal에서 별도 Chaos 중력이 적용되지 않는다.
- [ ] `R` 키 reset 후 책상 위 rest 위치에서 재현된다.
- [ ] Output Log에 `Phase 6 tissue_box` 연결·ACK 오류가 없다.

## 필요한 증거

확인 후 다음을 알려 주세요.

- Play 화면 스크린샷 1장
- Output Log에서 `LogMuJoCoBridge` 관련 구간
- 이상이 있으면 object ID, 위치/회전, 발생한 키 입력과 시점

Phase 3 확인은 완료되었습니다. 아래부터는 Phase 4 공간 메시 확인입니다.

## Phase 4 — Replica 공간 시각화 확인

Phase 3 bridge는 선택 사항입니다. 이번 확인은 공간 메시·좌표·카메라만 봅니다.

1. 에디터가 열려 있으면 `Ctrl+Alt+F11`로 Live Coding을 적용하거나, 에디터를 재시작합니다.
2. `Entry` 레벨에서 **Play**를 누릅니다.
3. 아래 항목을 확인합니다.

- [ ] 체크보드 임시 바닥 대신 Replica `office_0` 공간 메시가 보인다.
- [ ] 바닥이 수평이고 화면 아래쪽으로 뒤집히지 않는다.
- [ ] 벽·천장·공간 경계의 방향이 정상이다.
- [ ] 책상 등 가구가 바닥에 닿아 있으며 공중에 떠 있지 않다.
- [ ] 공간의 가로·세로·높이 비율과 카메라 거리가 자연스럽다.
- [ ] 카메라가 공간 바깥이 아니라 공간 안쪽을 바라본다.
- [ ] 원점 디버그 축이 보이며 `+X` 빨강, `+Y` 초록, `+Z` 파랑 방향이 맞다.
- [ ] 메시가 검정·투명·깨진 삼각형으로 표시되지 않는다.
- [ ] Play 시작과 종료에서 크래시가 없다.

사용자가 Unreal Play 화면에서 공간이 정상적으로 보임을 확인했습니다. 공간 내부 카메라, 바닥·벽·가구의 가시성, 축 마커, 메시 렌더링을 승인했으며 Phase 4를 완료합니다.

## Phase 5 — 고정 collision debug 확인

Phase 5 자동 검증은 완료되었습니다. Unreal Editor를 완전히 닫고 재빌드한 뒤 Play를 실행하면, 동일한 `outputs/metadata/office0_collision_proxy.json`에서 다음 wire box가 표시됩니다.

- 초록: `floor`
- 빨강: `wall_*`
- 노랑: `desk_*`
- 책장 프록시는 현재 표시되지 않음: semantic 책장 후보가 unresolved 상태

사용자는 바닥·벽·책상 collision의 높이와 위치가 시각 메시와 일치하는지 확인했습니다. `office_0`에는 책장 semantic 인스턴스가 없으므로 책장 프록시가 표시되지 않는 것이 정상입니다.
