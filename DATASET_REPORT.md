# DATASET_REPORT

- 작성 시각: 2026-08-11T11:47:53+09:00
- Phase: 1 — Replica `office_0` 데이터 준비
- 상태: **NEEDS_USER_VERIFICATION**
- 원본 분할 아카이브: `C:\URLabWorkspace\ReplicaPhysicsTwin\data\downloads\replica_v1`
- 추출된 scene: `C:\URLabWorkspace\ReplicaPhysicsTwin\data\raw\replica_v1\office_0`
- 파생 결과: `C:\URLabWorkspace\ReplicaPhysicsTwin\data\derived\office_0`

## 1. 추출 및 파일 무결성

- 공식 분할 아카이브 17개: 예상 크기와 모두 일치
- 보조 Habitat 설정 ZIP: 존재 및 `office_0` 추출 성공
- 추출 파일 수: 19개
- 추출 총 크기: 1,000,725,117 bytes
- 필수 파일 4개: 모두 존재하며 0 bytes 아님
- 원본 분할 아카이브: 수정하지 않음
- `office_0` 추출은 사용자의 Phase 1 승인 후 수행됨

필수 파일 checksum:

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `mesh.ply` | 25,926,155 | `cdb6ede0b9d455f491ef8fd63cd916a86a505b777842aabd6aa428edf9ff9032` |
| `semantic.json` | 1,324,972 | `a259ba63539d6a12f9cc8c1c939d7d3431a585a1a65772e63bf7f90c60b71aa0` |
| `habitat/mesh_semantic.ply` | 27,103,742 | `9e172c36255ecd34ecd8a59c9625cda61b87cc177db2d3af9ddb7348d03dd395` |
| `habitat/info_semantic.json` | 56,790 | `8abf9fbe38c28df326c5e13a4829e3d78985546a4e361fbffd9c5c05800ec9ba` |

전체 19개 파일의 checksum은 [data/derived/office_0/checksums.sha256](data/derived/office_0/checksums.sha256)에 기록했다.

## 2. 메시 형식 및 geometry

모든 PLY는 `binary_little_endian 1.0`이다. 세 메시의 정점 수·면 수·좌표 범위는 일치한다.

| 메시 | vertices | faces | 삼각형 faces | 최대 face vertex 수 |
|---|---:|---:|---:|---:|
| `mesh.ply` | 589,517 | 588,759 | 0 | 4 |
| `habitat/mesh_semantic.ply` | 589,517 | 588,759 | 0 | 4 |
| `habitat/mesh_preseg_semantic.ply` | 589,517 | 588,759 | 0 | 4 |

현재 메시의 face는 삼각형이 아니라 최대 4개 vertex를 갖는 polygon face다. Unreal 시각 메시 변환과 MuJoCo collision proxy 생성 시 별도 triangulation 또는 polygon 처리 정책이 필요하다.

전체 공간 좌표 범위:

```text
min = [-2.0056152344, -3.1536941528, -1.1688691378]
max = [ 2.3943858147,  1.8561344147,  1.8229918480]
extent = [4.4000010490, 5.0098285675, 2.9918609858]
```

단위 후보는 **meter, confidence medium**이다. 공간 규모와 Replica gravity metadata에 근거한 후보일 뿐이며, Unreal 화면에서 최종 확인해야 한다.

## 3. Semantic 및 instance 검사

- `semantic.json` version: `0.2`
- semantic ID type: `uint32_t`
- segmentation node 수: 4,841
- `info_semantic.json` object 수: 64
- `id_to_label` class ID 불일치: 0건
- object node가 segmentation에 없는 경우: 0건
- semantic mesh의 64개 선언 object ID: 모두 mesh에 표현됨
- pre-segmentation mesh object ID 수: 508

최종 semantic mesh에는 `info_semantic.objects`에 대응 레코드가 없는 face ID가 있다.

| unmapped face ID | face 수 | `id_to_label` 값 |
|---:|---:|---:|
| 0 | 11 | -2 |
| 41 | 2 | -1 |
| 43 | 1 | 47 |
| 47 | 2 | -1 |

이 16개 face를 데이터 손상으로 확정하지 않는다. Replica의 semantic label과 level-1 object 목록의 표현 범위 차이일 수 있으므로, 실제 object 분리 전에 사용자가 확인해야 한다.

## 4. MVP 후보 object

`habitat/info_semantic.json`의 exact class name을 기준으로 후보를 추출했다.

| 역할 | dataset class | object ID | node ID | 비고 |
|---|---|---:|---:|---|
| MVP 대상 | `tissue-paper` | 28 | 170 | 휴지곽 후보. 시각 확인 필요 |
| 바닥 | `floor` | 63 | 84 | 고정 collision 후보 |
| 벽 | `wall` | 8, 18, 24, 26, 51 | — | 고정 collision 후보 |
| 책상/테이블 | `table` | 12, 58 | — | 고정 collision 후보 |
| 책장 | — | — | — | 해당 class가 없음 |

`PC 본체`, `책`, `종이컵`도 현재 object class 목록에서 직접 확인되지 않았다. 첫 MVP는 semantic label `tissue-paper` object 28을 대상으로 제한한다. `tissue-paper`가 실제 휴지곽인지와 초기 위치는 Unreal 시각 검증에서 확정하지 않는다.

휴지곽 후보의 oriented bounding box metadata:

```text
object_id: 28
class_name: tissue-paper
center: [-0.6377331018, -0.6840538979, -0.4424815774]
sizes:  [ 0.1402903199,  0.1219995618,  0.1990051269]
```

## 5. 생성된 파생 결과

- [checksums.sha256](data/derived/office_0/checksums.sha256)
- [mesh_stats.json](data/derived/office_0/mesh_stats.json)
- [semantic_summary.json](data/derived/office_0/semantic_summary.json)
- [scene_manifest.json](data/derived/office_0/scene_manifest.json)
- 분석 코드: `src/replica_physics_twin/office0_analysis.py`
- 분석 테스트: `tests/test_office0_analysis.py`

파생 결과는 `data\derived\office_0`에만 기록했다. 아직 MuJoCo MJCF, collision proxy, Unreal mesh, 물성값은 생성하지 않았다.

## 6. Phase 1 판정 및 다음 조건

- 파일 존재·크기: **PASS**
- 분할 아카이브 크기: **PASS**
- PLY 형식·정점·면·bounding box 계산: **PASS**
- semantic metadata 내부 일관성: **PASS**
- semantic mesh object ID 완전 일치: **NEEDS_USER_VERIFICATION** — unmapped face IDs 0, 41, 43, 47
- 책장 class 존재: **NOT_FOUND**
- 최종 Phase 1 상태: **NEEDS_USER_VERIFICATION**

사용자가 위 unmapped ID와 `tissue-paper` object 28 후보를 확인하고 `Phase 1 승인`이라고 답하기 전에는 MuJoCo Phase 2를 시작하지 않는다.
