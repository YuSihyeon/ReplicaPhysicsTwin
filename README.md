# Replica Physics Twin

**Replica의 스캔 공간과 ReplicaCAD의 객체 자산을 MuJoCo 물리·Unreal 시각화에 연결한 상호작용 연구.**

[영상](#영상과-설명) · [연구 질문](#연구-질문과-목표) · [구현](#구현-과정) · [결과](#결과와-분석) · [재현](#재현과-자료-안내) · [이전 README 전문](RESEARCH_REPORT.md) · [상세 한국어 보고서](docs/research-archive/README.ko.md)

## 프로젝트 개요

정적인 공간 메시에서 움직일 객체를 선별하고, 시각 형상·충돌체·물성 출처를 연결해 사용자가 힘을 가할 수 있는 환경을 구성했다.
MuJoCo가 물리를 계산하고 **Unreal Engine 5.7이 표시와 입력을 담당**한다. 동적 객체의 상태를 두 엔진이 각각 계산하지 않도록 역할을 나눈다.

| 항목 | 내용 |
|---|---|
| 입력 | 초기 Replica `office_0` 스캔, 후속 ReplicaCAD `apt_0` CAD 장면 |
| 조작 대상 | 현재 자전거 `bike_02` 1개와 의류 `cloth_01`, `cloth_02` 2개 |
| 핵심 구현 | Python 장면 컴파일러, MJCF·물리 manifest, TCP/NDJSON bridge, Unreal C++ 표시·입력 |
| 현재 생성물 | 337 bodies / 150 geoms / 2 flexes / 224 flex vertices |
| 현재 검증 | **2026-09-16 재검증 FAIL:** 자전거 낙하 판정 미통과 |
| 결과의 범위 | 재현 가능한 연결 구조와 상호작용 시연. 실제 사물 물성의 측정·동일성 검증은 미완료 |
| 읽기 기준 | 과거 보고서, 현재 생성 파일, 재검증, 후속 제안을 구분 |

## 영상과 설명

아래 이미지는 기존 영상의 실제 미리보기다. 제목이나 이미지를 누르면 MP4를 열 수 있다.

[<img src="docs/research-archive/media/replica-poster.jpg" width="820" alt="ReplicaCAD 자전거와 의류 상호작용 영상 프레임">](docs/research-archive/media/replica-demo-preview.mp4)

| 영상 | 관찰할 내용 | 해석 범위 |
|---|---|---|
| [**자전거·의류 물리 시연 · 미리보기 MP4**](docs/research-archive/media/replica-demo-preview.mp4) | 약 6.93초 동안 자전거 이동과 의류 변형 | 보이는 동작의 시연 |
| [원본 MP4](docs/research-archive/media/replica-demo-original.mp4) · [미디어 상세](docs/research-archive/MEDIA.md) | 원본 2560 × 1368, 14 FPS, 97 frames | 원본 파일명에 `reverse`가 있어 순방향 물리 시간·실시간 처리 성능을 확정할 수 없음 |

영상의 의류 변형과 현재 생성 모델의 수치 검증은 서로 다른 근거다.
시연이 존재한다는 사실을 현재 낙하 검증의 통과나 모든 재질의 물리 정확도로 해석하지 않는다.

## 연구 질문과 목표

핵심 질문은 **“스캔 공간에서 무엇을 조작 가능한 객체로 선택하고, 형상·질량·접촉·입력을 어떤 근거로 연결할 것인가?”**이다.
이 문장은 설계와 코드에서 정리한 연구 해석이며, 별도로 확인한 개인적 동기의 인용은 아니다.

| 질문 | 구현에서 취한 접근 | 확인할 기준 |
|---|---|---|
| 어떤 객체를 움직일 것인가? | semantic/instance와 dataset scene config에서 실제 후보 선별 | 객체 이름·원본 ID·형상 경로의 대응 |
| 보이는 형상을 그대로 충돌체로 써도 되는가? | render mesh와 collision geometry 분리 | 충돌체 출처, 오목 구조·얇은 면의 근사 영향 |
| 물성 값은 어디에서 왔는가? | 제공값·유도값·실험 가정값을 manifest에 기록 | source mass와 MuJoCo 질량의 일치, 미측정 값 표시 |
| 사용자 입력이 물리 상태에 반영되는가? | 선택·드래그·impulse를 bridge 명령으로 전달 | MuJoCo 상태 변화와 Unreal 표시의 일관성 |
| 다시 실행해도 성립하는가? | 단순 박스 검증과 장면 검증을 분리 | 환경·모델·판정 기준을 함께 보존 |

초기 목표는 `office_0`의 휴지곽 후보를 분리하는 것이었다. 후속 구현은 객체별 자산·배치·질량 정보가 있는 ReplicaCAD로 범위를 확장했다.
두 입력은 동일 장면의 전후 버전이 아니므로, 한 데이터셋에서 일관되게 개선한 정량 실험으로 비교하지 않는다.

## 수행 내용과 기여 범위

이 저장소의 기여는 공개 엔진과 데이터셋을 연결하고, 객체 선별·좌표 변환·물성 추적·상호작용을 검토 가능한 코드와 보고서로 남긴 데 있다.
Replica/ReplicaCAD 자산, MuJoCo 엔진, Unreal 엔진 자체의 제작을 연구의 독자 성과로 소개하지 않는다.

| 구분 | 이 연구에서 수행·구성한 내용 | 근거 |
|---|---|---|
| 장면 처리 | 입력 자산과 설정을 읽고 물리·시각 출력을 생성 | [컴파일러](src/replica_physics_twin/replica_cad_scene.py), [빌드 진입점](scripts/build_replica_cad_pipeline.py) |
| 객체·충돌 선별 | office_0 후보 검사, 벽·책상 proxy 조정, CAD 충돌 자산 반영 | [충돌 분석 코드](src/replica_physics_twin/office0_collision.py), [충돌 보고서](PHASE5_COLLISION_REPORT.md) |
| 물성 연결 | mass 출처와 inertia·재질 가정을 명시 | [물성 처리](src/replica_physics_twin/physical_properties.py), [현재 manifest 요약](docs/research-archive/evidence/inspected-manifest-summary.json) |
| 상호작용 통합 | 상태 송신, 선택·힘·reset 명령, Unreal 입력과 표시 | [bridge](src/replica_physics_twin/bridge_server.py), [Unreal 프로젝트](unreal) |
| 검증·기록 | 단순 물리 검증, 장면 검사, 과거/현재 불일치와 실패 보존 | [박스 검증](PHYSICS_VALIDATION_REPORT.md), [현재 오류](docs/research-archive/evidence/reverified-physics-2026-09-16.json) |
| 외부 기반 | 스캔/CAD 형상과 원 metadata, 물리 solver, 시각화 엔진 | 원저작권·라이선스 및 데이터 출처 유지 |

현재 [설정](configs/pipeline.yaml)은 `enable_object_recognition=false`, `enable_open3dis=false`, `physics_values_are_measured=false`다.
현재 결과는 dataset scene config를 이용하며, 새로운 영상 기반 객체 인식·물성 자동 추정의 검증 결과는 아니다.

## 데이터와 선정 과정

| 자료 | 실제 사용한 정보 | 선택 이유와 제한 |
|---|---|---|
| Replica `office_0` | 공간 PLY, semantic/instance, 배치 | 스캔 공간의 객체 분리 가능성을 시험. 명칭이 없거나 의미가 모호한 후보 존재 |
| ReplicaCAD `apt_0` | 객체별 render GLB, collision GLB, scene/object config | 시각·충돌·질량 출처를 객체 단위로 연결. 실제 연구실 사물 측정치는 아님 |
| 현재 선택 객체 | bike_02 9.0kg / cloth_01 2.0kg / cloth_02 0.6kg | scene에 실제 존재하는 객체와 source mass 사용 |
| 정적 환경 | 선택 객체 이외 110개와 room shell | 81개 convex decomposition, 29개 bounding box; room shell은 별도 proxy |

`office_0` 조사에는 19개 파일, 약 1.00GB가 포함되었다. 원본 메시의 589,517 vertices와 588,759 polygon faces를 확인했다.
polygon과 triangle을 구분해 변환했으며, 시각 메시 결과는 1,177,518 triangles로 기록되어 있다. [데이터 보고서](DATASET_REPORT.md)

| 후보·문제 | 선택 또는 제외 | 판단의 의미 |
|---|---|---|
| `tissue-paper` ID 28 | 초기 `tissue_box` 후보로 시험 | 데이터의 semantic 후보에서 출발한 제한적 실험 |
| 책장 | 일치하는 semantic instance가 없어 제외 | 원하는 이름을 모호한 객체에 임의로 부여하지 않음 |
| `undefined` 자홍색 proxy | 책장으로 잘못 승격한 표시 제거 | 시각적 편의를 객체 식별 증거로 사용하지 않음 |
| `wall_18` | 약 0.017 × 0.010 × 0.538m의 얇은 요소여서 벽 충돌에서 제외 | 큰 벽을 기대하는 proxy 규칙에 맞지 않음 |
| 책상 충돌 | 가구 전체 AABB 대신 상단 근수평 면 band 사용 | 빈 공간을 가로막는 과도한 충돌체 축소 |
| CAD 휴지곽·정리함 | 정확한 template이 없어 자전거·의류로 전환 | primitive에 원하지 않는 실물 이름을 붙이지 않음 |

선별·제외의 근거는 [충돌 보고서](PHASE5_COLLISION_REPORT.md), [휴지곽 보고서](PHASE6_TISSUE_BOX_REPORT.md), [CAD 구현 보고서](REPLICA_CAD_IMPLEMENTATION_REPORT.md)에 남아 있다.

## 구현 과정

### 1. 단순 물리에서 공간 상호작용으로

| 순서 | 수행 내용 | 분리해 확인한 문제 |
|---|---|---|
| 1 | 0.1kg 박스 낙하·정착·0.1 N·s impulse | 엔진, 단위, 접촉 응답과 힘 계산 |
| 2 | MuJoCo → TCP/NDJSON → Unreal 상태 전달 | 통신과 좌표/scale |
| 3 | office_0 시각 메시와 정적 충돌 proxy 생성 | 보이는 공간과 충돌 공간의 차이 |
| 4 | 휴지곽·정리함·의자 후보의 선택과 힘 입력 | 객체별 상태·물성·입력 대응 |
| 5 | ReplicaCAD source geometry와 설정 기반 컴파일 | 원본 자산에서 생성물까지의 추적성 |
| 6 | 의류 flex와 Unreal 표시 메시 변형 연결 | 강체 자세와 변형 정점의 구분 |

초기 reset이 30cm 들어 올린 위치로 돌아가던 문제는 rest 위치와 lift 명령을 분리해 수정한 기록이 있다.
이는 초기 상호작용의 수정 이력이며 현재 자전거 낙하 검증 실패의 해결 기록은 아니다.

### 2. 입력부터 화면까지

```text
ReplicaCAD GLB / scene config / object config
  → Python: 객체 선택·좌표 변환·물성 출처 기록
  → MJCF + 충돌 메시 + 물리 manifest + 시각 메시
  → MuJoCo: 중력·접촉·마찰·flex·입력 힘 계산
  → TCP / NDJSON: 순번·시각·pose·속도·접촉 전달
  → Unreal: procedural mesh 표시·카메라·선택 UI
  → 사용자 명령을 bridge로 반환
```

ReplicaCAD의 Y-up 좌표는 `[x,y,z] → [x,-z,y]`로 Z-up에 맞춘다. 물리는 m, Unreal 표시 교환은 cm를 사용한다.
기본 연결은 `127.0.0.1:7007`, 상태 publication 설정은 60Hz다. **60Hz 설정은 측정한 전체 시스템 60 FPS를 뜻하지 않는다.**
상태 순번·잘못된 명령·재접속을 처리하고, Unreal 동적 객체의 Chaos physics를 꺼서 물리 계산 주체를 MuJoCo로 유지한다.
[초기 프로토콜](PROTOCOL.md)과 [현재 bridge 구현](src/replica_physics_twin/bridge_server.py)을 함께 읽어 단계별 차이를 확인할 수 있다.

### 3. 강체와 천, 그리고 입력

자전거는 원본 render/collision 자산을 이용한다. 의류는 2D flex grid와 hanging-edge constraint로 표현하고, 표시 메시를 flex 변형에 대응시킨다.
질량은 source config 제공값, inertia는 collision bounds 유도값이다. 천의 탄성·두께·damping·drag 계수는 실험용 가정값이다.
현재 의류 grid는 각각 8 × 14 = 112개 정점이며, 과거 보고서의 각 240개와 다르다.

| 조작 | 행동 |
|---|---|
| 클릭 / Shift+클릭 | 단일 선택 / 선택 집합 추가·제거 |
| 클릭 드래그 | 유한한 물리 힘을 통한 이동 입력 |
| `I` / `T` | impulse / 선택 객체 들어올리기·낙하 |
| `P` / `R` | MuJoCo 일시정지·재개 / 장면 reset |
| 우클릭 드래그, `WASD/QE` | 시점 회전과 카메라 이동 |

## 결과와 분석

### 단순 박스의 과거 검증

조건은 질량 0.1kg, 반높이 0.05m, 초기 중심 높이 0.35m, timestep 0.002s, 중력 −9.81m/s²다.
아래 값은 저장된 [Phase 2 보고서](PHYSICS_VALIDATION_REPORT.md)의 결과이며 이번 문서 작업에서 새로 실행한 수치가 아니다.

| 지표 | 저장된 결과 | 판정·해석 |
|---|---:|---|
| 첫 접촉 | 0.25s | 중력 낙하 후 접촉 |
| 최대 바닥 기준 오차 | 4.22mm | 당시 5mm 허용치 만족 |
| 최종 중심 높이 | 0.0499964m | 이상적 rest 중심 0.05m에 근접 |
| +X impulse Δv | 1.0m/s | 0.1 N·s / 0.1kg와 일치 |
| solref 0.02 → 0.01 → 0.005s | 침투 17.02 → 8.43 → 4.22mm | 동일 단순 모델의 접촉 시간상수 비교 |

이 결과는 단순 모델의 수치 응답을 확인한다. 실제 자전거·의류의 물성, 전체 방의 충돌 정확도까지 검증하지는 않는다.

### 현재 생성물과 과거 보고서의 차이

| 항목 | 과거 CAD 구현 보고서 | 2026-09-16 현재 파일 대조 |
|---|---:|---:|
| bodies / geoms | 593 / 117 | 337 / 150 |
| flexes / flex vertices | 2 / 480 | 2 / 224 |
| equality constraints | 25 | 17 |
| 현재 joints | 비교값으로 사용하지 않음 | 673 |
| 질량 출처 | dataset config | 9.0 / 2.0 / 0.6kg, 제공값과 일치 기록 |
| 낙하·접촉 검증 | 과거 PASS 기록 | **현재 FAIL** |

[과거 구현 보고서](REPLICA_CAD_IMPLEMENTATION_REPORT.md)와 [현재 manifest 요약](docs/research-archive/evidence/inspected-manifest-summary.json)을 함께 보존한다.
문서의 오래된 수치를 현재 생성 모델의 실측값처럼 재사용하지 않는다.

### 현재 재검증의 실패와 해석

Python 3.13.10 / MuJoCo 3.10.0에서 모델 컴파일은 성공했지만, 기존 [검증 스크립트](scripts/verify_replica_cad_physics.py)는 아래 오류로 끝났다.

```text
body did not fall under gravity: replica_bike_02_100
```

현재 timestep 0.0005s에서 1,800 step은 0.9초다. 고정 step 수와 시간 기준, 초기 pose·접촉·constraint·엔진 버전을 함께 조사해야 한다.
**원인은 이번 대조만으로 확정되지 않았으며, 검증 기준이나 모델을 통과하도록 바꾸지 않았다.** [환경·오류 JSON](docs/research-archive/evidence/reverified-physics-2026-09-16.json)

확인된 성과는 객체의 시각 형상, 계산용 충돌체, 질량 출처, 입력과 상태를 하나의 추적 가능한 구조로 연결한 것이다.
실물 재현 정확도는 아직 제한된다. box/convex 근사는 오목 구조와 얇은 면을 단순화하고, 천의 고정 경계·격자·재질 가정은 실측 교정 전이다.

## 한계와 다음 단계

다음 항목은 향후 제안이다. 완료한 기능이나 이미 확보한 수치로 읽지 않도록 우선순위와 평가 기준을 함께 둔다.

| 우선순위 | 남은 문제 | 다음 실험 | 완료를 판단할 근거 |
|---|---|---|---|
| P0 | 현재 자전거 검증 실패 | commit·환경·XML/manifest hash 고정 후 시간·pose·접촉·constraint를 분리 | 같은 입력의 실패 재현, 원인별 로그, 수정 전후 동일 판정 비교 |
| P1 | 물성 가정의 실측 부재 | 질량·경사면 미끄럼·낙하 반발·천 처짐과 진동 측정 | 측정값·오차·반복 범위와 파라미터 출처 공개 |
| P1 | 충돌 근사의 영향 미평가 | AABB·convex decomposition·개선 메시를 동일 조건 비교 | 침투·정착·계산시간을 함께 보고 |
| P2 | bridge 지연·jitter 미계측 | 송수신 timestamp·명령 ACK·stale frame 계측 | 지연 분포와 누락/오래된 상태 비율 |
| P2 | 문서와 생성물의 수치 불일치 | build 결과에서 표 자동 생성 | 생성 manifest와 보고서의 객체·정점·제약 수 일치 |
| P3 | 연구실 GS와의 연계 미검증 | 검증된 geometry와 object transform을 GS 외관에 연결 | 물리 기준 장면의 상태·충돌 검증 유지, 외관과 물성 출처 분리 |

## 재현과 자료 안내

### 실행 경로

Python 3.11은 기존 README의 요구 환경이며, 현재 재검증은 Python 3.13.10 / MuJoCo 3.10.0이었다. 버전 차이를 기록하고 같은 조건의 결과부터 비교한다.
필요한 구성은 Python·MuJoCo, Git LFS, Unreal Engine 5.7, 별도로 준비한 ReplicaCAD 데이터다. 프로젝트의 [의존성 선언](pyproject.toml)을 함께 확인한다.
보존 원본을 덮어쓰지 않는 작업 복사본의 저장소 루트에서 실행한다.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
.\scripts\download_replica_cad.ps1
python .\scripts\build_replica_cad_pipeline.py `
  --dataset-root .\data\raw\replica_cad `
  --scene apt_0 `
  --output-root .\outputs\replica_cad
python .\scripts\verify_replica_cad_physics.py `
  --metadata .\outputs\replica_cad\metadata\replica_cad_interaction.json
.\scripts\run_replica_cad.ps1
```

검증 단계의 현재 알려진 상태는 FAIL이다. 새 출력은 기존 오류 JSON과 별도로 보관한다.
bridge 실행 후 [Unreal 프로젝트](unreal/ReplicaPhysicsTwin.uproject)를 연다. 생성 메시·MJCF·로그와 Unreal cache는 Git에서 제외되어 있다.
초기 office_0 경로는 [환경 보고서](ENVIRONMENT_REPORT.md), [물리 파이프라인](PHYSICAL_PIPELINE_REPORT.md), [Unreal 점검표](UNREAL_PHYSICAL_PIPELINE_CHECKLIST.md)를 따른다.

### 공개 저장소와 전체 원본

| 자료 | 공개 검토 경로 | 전체 보존본에서 찾을 곳 |
|---|---|---|
| 코드·설정·보고서 | [src](src), [scripts](scripts), [configs](configs), [이전 README](RESEARCH_REPORT.md) | `02-ReplicaPhysicsTwin/originals/windows/URLabWorkspace/ReplicaPhysicsTwin/` |
| Replica/ReplicaCAD 원자료 | [데이터·복원 안내](DATA_AND_RESTORE.md) | 원본 프로젝트의 `data/downloads`, `data/raw`, `data/processed`, `data/derived` |
| 생성 모델·실험 출력 | 공개 요약과 재검증 JSON | 원본 프로젝트의 `outputs/replica_cad/` 및 다른 `outputs/` |
| Unreal 에셋·빌드 상태 | 공개 C++ 프로젝트 | 원본 프로젝트의 `unreal/` 전체 |
| 영상 원본 | 위 MP4 링크 | `02-ReplicaPhysicsTwin/originals/original-videos/` |
| 환경·복사 검증 | [전체 복원 범위](DATA_AND_RESTORE.md) | 컬렉션 `_shared/`, `_control/manifests/`, 프로젝트 `RESTORE.md` |

전체 원본 프로젝트는 2,192개 파일, 48,391,237,322 bytes의 보존·SHA-256 대조 기록이 있다. 별도 영상 등의 범위는 상위 보존 기록을 따른다.
Git clone만으로 대형 입력·생성 모델·전체 Unreal 환경이 복원되지는 않는다. 현재 로컬 보존과 USB 외부 사본 검증, 초기화 후 실행 성공은 각각 별도 상태다.
ReplicaCAD 원자료는 [AI Habitat 공식 배포](https://huggingface.co/datasets/ai-habitat/ReplicaCAD_dataset)의 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 조건을 따른다.
기존 README는 같은 루트의 [RESEARCH_REPORT.md](RESEARCH_REPORT.md)에 바이트 그대로 보존해 상대 링크 기준을 유지했다. 상세 한국어 분석은 [README.ko.md](docs/research-archive/README.ko.md)에서 계속 읽을 수 있다.
