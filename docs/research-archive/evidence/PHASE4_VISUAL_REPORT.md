# Phase 4 Replica 공간 시각화 보고서

## 상태

**COMPLETE_WITH_USER_VERIFICATION — 파생 메시 생성·UE 빌드·자동 검증·Unreal Play 확인 완료**

## 구현

- Replica 원본 `data/raw/replica_v1/office_0/mesh.ply`는 수정하지 않았습니다.
- 파생 메시 생성기: `src/replica_physics_twin/visual_mesh.py`
- 생성 스크립트: `scripts/build_office0_visual_mesh.py`
- Unreal용 OBJ: `outputs/meshes/office_0_visual.obj`
- Unreal 런타임 바이너리: `outputs/meshes/office_0_visual.rptmesh`
- 변환 메타데이터: `outputs/metadata/office_0_visual_transform.json`
- Unreal 런타임 로더: `unreal/Source/ReplicaPhysicsTwin/Private/Bridge/ReplicaOfficeVisualActor.cpp`

## 변환 기준

- 원본 단위: meter
- Unreal 출력 단위: centimeter
- Up axis: Z
- 수평 bounds 중심을 `(0, 0)`으로 이동
- 최저 vertex를 `Z=0`으로 이동
- 회전: identity
- 시각 메시에는 충돌을 부여하지 않으며, 물리 권위는 MuJoCo에 유지합니다.

## 자동 검증

- Python 전체 테스트: **18 passed**
- 파생 바이너리 magic: `RPTMESH1`
- 파생 메시: 589,517 vertices, 1,177,518 triangles
- 출력 bounds: 약 `X[-220, 220] cm`, `Y[-250.5, 250.5] cm`, `Z[0, 299.2] cm`
- UE 5.7 Editor target build: **Succeeded**
- UE 5.7 Game target build: **Succeeded**
- UE automation `ReplicaPhysicsTwin.Bridge.MappingAndSequence`: **Success / EXIT CODE: 0**

## 사용자 확인 전 항목

다음은 자동 테스트만으로 판정할 수 없으므로 Unreal Editor Play 화면에서 확인해야 합니다.

- 공간이 뒤집히지 않았는가
- 바닥·벽·가구가 올바른 방향과 높이에 있는가
- 카메라가 공간 내부를 보는가
- 메시가 검정·투명·깨짐 없이 렌더링되는가
- Play에서 크래시가 없는가

상세 절차는 `UNREAL_VISUAL_CHECKLIST.md`에 있습니다.

## 사용자 확인 결과

사용자가 Unreal Play 화면에서 Replica 공간이 밝게 보이고, 내부 공간·바닥·벽·문·소파·의자·테이블과 원점 축 마커가 정상적으로 표시됨을 확인했습니다. Phase 4 시각 검증을 승인했습니다. 다음 단계는 MuJoCo 고정 충돌 공간 구성입니다.
