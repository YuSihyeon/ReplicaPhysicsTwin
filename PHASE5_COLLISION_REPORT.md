# Phase 5 — MuJoCo 고정 충돌 공간 구성

## 상태

**PASS_WITH_SCENE_LIMITATION** — 바닥·벽·책상 프록시와 MuJoCo 자동 검증, Unreal collision debug 정렬 확인을 완료했습니다. `office_0`에는 책장 semantic 인스턴스가 없어 책장 collision은 적용 대상이 아닙니다.

## 구현 범위

- 원본 `data/raw/replica_v1/office_0`는 읽기 전용으로 사용했습니다.
- semantic mesh face의 `object_id`별 실제 정점 bounds로 axis-aligned box 프록시를 만들었습니다.
- 책상은 전체 가구 AABB가 시각적으로 과대 표시되지 않도록 상단 근수평 face band만 추출해 얇은 상판 box로 만들었습니다.
- Unreal 시각 메시와 MuJoCo 충돌 공간은 동일한 변환을 사용합니다.

좌표 변환:

```text
source meter → translation [-0.19438529, +0.64877987, +1.16886914] meter → normalized MuJoCo meter
normalized MuJoCo meter × 100 → Unreal centimeter
```

## 생성된 프록시

| 역할 | 프록시 | 출처 | 신뢰도 |
|---|---|---|---|
| 바닥 | `floor` | visual mesh XY bounds, support z=0 | medium |
| 벽 | `wall_8`, `wall_24`, `wall_26`, `wall_51` | semantic mesh instances | medium |
| 책상 상판 | `desk_12`, `desk_58` | semantic class `table`의 상단 근수평 face band | medium |
| 책장 | 없음 | semantic object inventory에 책장·선반·랙·캐비닛 인스턴스 부재 | not present in scene |

semantic 후보 `wall_18`은 실제 labeled geometry가 약 `0.017 × 0.010 × 0.538m`인 얇은 요소라 벽 충돌체에서 제외했습니다. semantic object 64개를 점검했으며 `bookcase/bookshelf/shelving/shelf/rack/cabinet` 인스턴스가 하나도 없습니다. 이전 화면에서 보인 `bookcase_49` 자홍 박스는 `class=undefined` geometry를 책장으로 잘못 승격한 결과였으므로 제거했습니다.

## 자동 검증 결과

실행:

```powershell
$env:PYTHONPATH='src'
python scripts/build_office0_collision_proxy.py
python -m pytest -q
```

결과:

- 프록시 정렬 검사: `passed=true`, 시각 bounds 밖 프록시 없음
- MJCF: 7 fixed proxy geoms + 3 dynamic drop probes, compile 성공
- 다중 낙하: 바닥 1개, 책상 2개 모두 접촉 후 정지
- 최종 지지면 높이 오차: 약 `3.6e-6m`
- Python 전체 테스트: `24 passed` (Phase 6 테스트 포함)

산출물:

- `outputs/mjcf/office0_collision_proxy.xml`
- `outputs/metadata/office0_collision_proxy.json`
- `outputs/reports/phase5/phase5_collision_summary.json`
- `outputs/reports/phase5/phase5_collision_contacts.jsonl`

## Unreal 확인 결과

`MuJoCoBridgeDemoGameMode`가 위 JSON을 읽어 역할별 debug box를 그립니다.

- 초록: 바닥
- 빨강: 벽
- 노랑: 책상

에디터를 닫은 뒤 재빌드하고 Play 화면에서 다음을 확인해야 합니다.

1. 초록 바닥 box가 Replica 바닥과 같은 높이인가
2. 빨간 벽 box가 실제 벽 안쪽/두께와 일치하는가
3. 노란 책상 box가 상판 높이와 일치하는가
4. 책장 프록시가 표시되지 않는 것이 정상인지 semantic inventory와 대조
5. 화면에 크래시·검은 메시·추가 Chaos 물리가 없는가

사용자 확인 결과: 바닥·벽·책상은 시각 메시와 정렬되었고, 책장 자홍 오탐은 제거되었습니다. `office_0`에 책장이 없다는 데이터 근거를 확인했으므로 Phase 6으로 진행합니다.
