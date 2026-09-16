# Replica Physics Twin

스캔한 방에서 물체가 보인다는 것과 그 물체를 집거나 밀 수 있다는 것은 서로 다른 문제다. 방 전체를 표현하는 메시에는 움직일 물체의 경계, 충돌을 계산할 형상, 질량과 마찰의 출처가 함께 주어지지 않는다. 이 연구는 Replica `office_0`에서 휴지곽 후보를 분리하는 작업으로 시작해, ReplicaCAD `apt_0`의 자전거와 의류를 MuJoCo 물리 및 Unreal Engine 5.7의 표시·입력에 연결했다. 중심 과제는 **공간의 외관에서 출발해, 객체의 정체성과 물리 상태를 추적할 수 있는 상호작용 환경을 만드는 것**이었다.

[<img src="docs/research-archive/media/replica-poster.jpg" width="820" alt="ReplicaCAD 실내에서 자전거의 위치 변화와 매달린 의류의 변형을 보여주는 시연 장면">](docs/research-archive/media/replica-demo-preview.mp4)

*그림 1. [자전거·의류 상호작용 기록](docs/research-archive/media/replica-demo-preview.mp4). 자전거의 이동과 매달린 의류의 형상 변화를 한 장면에 연결한 결과다. 자전거는 강체 상태를, 의류는 flex 정점의 변형을 Unreal 표시 메시로 전달한다. [원본 영상](docs/research-archive/media/replica-demo-original.mp4)은 2560 × 1368, 14 FPS, 97 frames, 약 6.93초이며 원본 파일명에 `reverse`가 포함되어 있다. 따라서 보이는 동작은 구현 결과를 보여주지만, 순방향 물리 시간·충격량·실시간 처리 속도를 이 영상에서 산출하지 않는다. 원본 대응은 [미디어 기록](docs/research-archive/MEDIA.md)에 남아 있다.*

현재 확인된 성과는 원본 객체·시각 형상·충돌체·물성 출처·사용자 힘 입력을 연결한 구조다. 물리적 정확도의 근거는 별도로 살펴야 한다. 단순 박스 검증과 과거 CAD 보고서에는 통과 기록이 있지만, **2026-09-16 현재 생성 모델의 재검증은 자전거 낙하 판정에서 실패했다.** 이 불일치까지 포함해 무엇이 성립했고 무엇을 다시 조사해야 하는지 설명한다.

## 휴지곽 하나를 움직이기 위해 먼저 풀어야 했던 문제

[초기 환경 보고서](ENVIRONMENT_REPORT.md)는 `office_0`의 `tissue_box`를 최소 구현 대상으로 정하고, MuJoCo가 중력·충돌·마찰·강체 상태를 계산하며 Unreal은 표시와 입력을 맡도록 명시했다. 이것이 당시 문서로 확인되는 목표다. 스캔 전체를 즉시 물리 환경으로 전환하기보다 한 객체를 골라 데이터 분리, 공간 정렬, 물리 계산, 입력 반환을 끝까지 연결하는 구성이었다.

이 목표를 구현하려면 서로 다른 세 가지 판단이 필요했다. 첫째는 어떤 면들이 실제 조작 대상에 속하는지 정하는 객체 식별이다. 둘째는 그 면들을 그대로 충돌에 사용할지, 단순한 계산용 형상으로 바꿀지 정하는 기하 근사다. 셋째는 질량·관성·접촉 계수를 어느 자료에 근거해 넣을지 정하는 물성 설정이다. 객체가 화면에서 자연스럽게 움직여도 이 세 판단의 근거가 없으면, 그 동작을 실제 사물의 재현이라고 설명하기 어렵다. 초기 목표와 후속 코드를 종합하면, 이 연구는 객체 식별·기하 근사·물성 설정의 근거를 서로 연결하는 문제로 해석할 수 있다.

물리 계산 주체를 MuJoCo 하나로 둔 선택도 같은 맥락에 있다. Unreal에서 같은 객체에 Chaos physics를 적용하면 MuJoCo가 계산한 자세와 표시 엔진이 계산한 자세가 달라질 수 있다. 이 연구에서는 동적 객체의 Chaos physics를 끄고 MuJoCo 상태를 표시한다. 사용자의 드래그도 화면 좌표를 곧바로 새 물체 위치로 적용하는 대신 물리 입력으로 되돌린다. 이 분리는 단순한 엔진 조합을 넘어, 보이는 움직임의 원인을 한 계산 경로에서 찾기 위한 조건이다. [물리 파이프라인 보고서](PHYSICAL_PIPELINE_REPORT.md)에 초기 연결 구조가 남아 있다.

## 스캔의 이름과 실제 형상을 대조하면서 바뀐 객체 선정

### `office_0`: semantic label만으로는 충분하지 않았다

초기 입력 조사에서는 `office_0`의 19개 파일, 약 1.00GB를 확인했다. 원본 메시에는 589,517 vertices와 588,759 polygon faces가 있었고, 변환한 시각 메시에는 1,177,518 triangles가 기록되어 있다. polygon face 수를 triangle 수로 읽지 않도록 구분한 것은 이후 객체 추출과 표시 결과가 원자료에 대응하는지 확인하기 위한 기초였다. 입력 구조와 변환 수치는 [데이터 보고서](DATASET_REPORT.md)에 보존되어 있다.

조작 후보는 semantic class `tissue-paper`, instance ID 28에서 출발했다. 이 후보를 `tissue_box`로 시험한 것은 데이터에 실제 존재하는 분할 결과를 이용한 제한적 실험이다. 모든 스캔 물체를 자동 인식했다는 의미는 없다. 반대로 책장은 조사한 semantic inventory에서 해당 instance를 찾지 못했다. 초기 화면에 나타난 자홍색 `bookcase_49` proxy는 `undefined` geometry에 책장이라는 이름을 잘못 부여한 결과였고, 이후 제거되었다. 이 수정의 핵심은 표시상의 그럴듯함보다 원본 식별 정보와의 일치를 우선한 데 있다.

벽에서도 이름만으로 충돌체를 확정할 수 없었다. `wall_18`의 실제 labeled geometry는 약 0.017 × 0.010 × 0.538m의 얇은 요소였으므로 큰 벽을 대표하는 충돌체에서 제외했다. 책상에는 다른 문제가 있었다. 가구 전체의 축 정렬 경계 상자(AABB)를 쓰면 상판 아래의 빈 공간까지 막을 수 있다. 따라서 상단의 근수평 face band를 추출해 얇은 상판 box로 바꾸었다. [충돌 분석 코드](src/replica_physics_twin/office0_collision.py)와 [Phase 5 보고서](PHASE5_COLLISION_REPORT.md)는 이 수정이 미관 조정보다 **보이는 공간과 실제 접촉 공간의 불일치**를 줄이는 작업이었음을 보여준다.

Phase 5에는 바닥·벽·책상 proxy의 정렬 검사와 세 개 낙하 probe의 접촉·정지, 최종 지지면 높이 오차 약 `3.6e-6m`가 기록되어 있다. 같은 보고서의 `24 passed` 역시 당시 코드·장면에 대한 테스트 기록이다. 이는 선별한 지지면과 probe의 관계를 확인한 결과이며, 방 안의 모든 가구 형상을 정밀하게 복원했다는 평가로 넓힐 수 없다. [휴지곽 보고서](PHASE6_TISSUE_BOX_REPORT.md)와 [실행 기록](docs/research-archive/evidence/RUN_LOG.md)에는 이후 동적 객체와 상호작용 단계가 이어진다.

### `apt_0`: 원하는 물체 이름보다 출처가 연결되는 자산을 선택했다

ReplicaCAD로 넘어가면서 입력의 성격이 달라졌다. 스캔 공간의 semantic 면에서 객체를 떼어내는 대신, 객체별 render GLB·collision GLB·scene/object config를 읽어 원래 배치와 물성 metadata를 연결할 수 있었다. [CAD 구현 보고서](REPLICA_CAD_IMPLEMENTATION_REPORT.md)는 해당 장면에 정확한 휴지곽·정리함 template이 없다고 기록한다. 후속 실험은 primitive에 그 이름을 붙이는 대신 장면에 실제 존재하는 자전거 `bike_02`와 의류 `cloth_01`, `cloth_02`를 선택했다.

이 선택으로 질문도 구체화되었다. 자전거에서는 복잡한 외관과 강체 충돌 표현의 대응을, 의류에서는 강체 자세만으로 표현할 수 없는 변형을 다룬다. 두 종류의 물체를 포함한 구조는 강체 pose와 변형 정점을 서로 다른 상태로 전송해야 한다는 구현상의 차이를 드러낸다. 다만 이 점을 두 입력 데이터셋의 성능 비교로 해석할 수는 없다. `office_0` 스캔과 `apt_0` CAD 장면은 동일 장면의 전후 버전이 아니며, 객체와 모델링 조건도 달라졌다.

선택하지 않은 110개 객체는 정적 환경으로 사용했다. 이 가운데 81개에는 데이터셋의 convex-decomposition 충돌 자산을, 29개에는 해당 object config가 요구한 bounding-box 방식을 적용했다. room shell은 별도의 바닥·천장·벽 proxy로 구성했다. 방 전체처럼 오목한 공간을 하나의 볼록 충돌체로 처리하면 내부의 빈 공간을 보존하기 어렵기 때문이다. 따라서 시각 메시의 세밀함과 충돌 표현의 계산 가능성을 분리하되, 어느 근사를 어디에 썼는지 남기는 것이 중요했다.

현재 [pipeline 설정](configs/pipeline.yaml)의 `enable_object_recognition=false`, `enable_open3dis=false`, `physics_values_are_measured=false`는 이 결과의 범위를 분명히 한다. 현재 객체 선정은 dataset scene config를 사용한다. 새로운 영상에서 객체를 인식하거나, 외관으로부터 물성을 자동 추론한 결과를 평가한 구성은 아니다.

## 복잡한 장면을 넣기 전에 낙하·접촉·힘을 따로 검증한 이유

공간 충돌체, 통신, 좌표계가 한꺼번에 들어가면 물체가 잘못 움직일 때 어느 부분이 원인인지 분리하기 어렵다. 초기 검증은 그래서 0.1kg 박스 하나로 중력 낙하와 접촉 정착, impulse 응답을 확인했다. 박스의 반높이는 0.05m, 초기 중심 높이는 0.35m, timestep은 0.002s, 중력은 −9.81m/s²였다. 바닥에서 30cm 위에 있는 박스를 떨어뜨리는 조건이며, 목표 rest 중심은 0.05m다.

| 검증 항목 | 저장된 결과 | 이 조건에서 확인한 의미 |
|---|---:|---|
| 첫 접촉 시각 | 약 0.25s | 낙하 후 바닥 접촉이 발생 |
| 최대 바닥 기준 중심 오차 | 4.22mm | 당시 5mm 허용치를 만족 |
| 최종 중심 높이 | 0.0499964m | 이상적 rest 높이에 근접 |
| +X 방향 0.1 N·s impulse의 Δv | 1.0m/s | `J/m = 0.1/0.1`과 일치 |
| `solref` 0.02 / 0.01 / 0.005s | 침투 17.02 / 8.43 / 4.22mm | 같은 단순 모델에서 접촉 시간상수 변화의 영향 |

이 표는 [Phase 2 물리 검증 보고서](PHYSICS_VALIDATION_REPORT.md)에 저장된 과거 결과다. 접촉 시간상수를 줄였을 때 침투가 줄어든 비교는 동일한 박스 모델의 수치 응답을 설명한다. 실물 휴지곽의 재료를 측정하거나 자전거·의류의 움직임을 교정한 실험은 아니다. 단순한 검증을 먼저 둔 의미는 힘과 단위, 접촉 응답의 기준점을 확보하는 데 있으며, 복잡한 장면에 그 정확도가 자동으로 이어진다고 가정하는 데 있지 않다.

상호작용에서도 초기 상태의 의미를 분리해야 했다. reset이 30cm 들어 올린 위치로 돌아가던 문제는 rest 위치와 lift 명령을 구분하는 방식으로 수정되었다. reset은 기준 장면의 복원이고 lift/drop은 낙하를 유발하는 실험 입력이므로, 두 기능이 같은 높이를 공유하면 사용자가 본 상태와 검증한 초기 조건이 어긋난다. 이 수정은 초기 상호작용에 대한 기록이며 뒤에서 다루는 현재 자전거 낙하 실패가 해결되었다는 근거는 아니다.

## 원본 자산에서 물리 상태와 화면까지 이어지는 경로

### 장면 컴파일러가 형상·배치·물성의 대응을 만든다

[Python 장면 컴파일러](src/replica_physics_twin/replica_cad_scene.py)는 ReplicaCAD의 GLB와 설정을 읽어 MJCF, 충돌 메시, 물리 manifest, Unreal 표시용 메시를 생성한다. [빌드 진입점](scripts/build_replica_cad_pipeline.py)을 통하면 같은 처리 규칙을 다시 적용할 수 있다. 서로 다른 프로그램에서 객체를 수작업으로 다시 배치하기보다 입력 자산에서 두 엔진의 출력을 함께 만드는 구조다.

```text
ReplicaCAD render/collision GLB + scene/object config
  → 객체 선택 · 좌표 변환 · source mass와 물성 가정 기록
  → MJCF / 충돌 메시 / 물리 manifest / Unreal 시각 메시
  → MuJoCo의 강체·접촉·마찰·flex 계산
  → TCP/NDJSON으로 pose·속도·접촉·변형 상태 전달
  → Unreal 표시와 사용자 선택·힘 입력
  → 명령을 MuJoCo bridge에 반환
```

ReplicaCAD의 Y-up 좌표는 `[x,y,z] → [x,-z,y]`로 Z-up에 맞춘다. 물리 계산은 m, Unreal 표시 교환은 cm를 사용한다. 이 변환은 초기 `office_0`의 translation 정규화와 별도 경로다. 같은 장면을 쓰더라도 회전축이나 길이 단위가 어긋나면 시각 메시와 충돌체가 다른 곳에 놓이므로, 두 출력이 같은 원본 변환을 공유해야 한다.

기본 bridge 주소는 `127.0.0.1:7007`이며 상태 publication 설정은 60Hz다. 전달 상태에 순번과 simulation time을 두고, pose·속도·접촉 및 물성 출처를 연결하며 잘못된 명령과 재접속을 처리한다. [초기 프로토콜](PROTOCOL.md)과 [현재 bridge 구현](src/replica_physics_twin/bridge_server.py)은 단계별 계약을 확인할 근거다. 60Hz는 전송 설정이고 전체 시스템에서 측정한 60 FPS나 지연 보장치는 아니다. 송수신 timestamp에 따른 지연 분포와 오래된 상태의 비율은 별도 계측 과제로 남아 있다.

### 질량을 보존하는 것과 물성을 측정하는 것은 구분해야 한다

자전거와 의류의 질량은 source config에서 각각 9.0kg, 2.0kg, 0.6kg을 가져온다. 빌드에서는 원본 제공값과 MuJoCo 질량의 대응을 검사하고 manifest에 결과를 기록한다. 이 확인은 데이터 전달의 무결성에 관한 것이다. 데이터셋에 적힌 값이 연구실 실물의 측정 질량과 같다는 확인은 아니다.

관성 텐서는 source config에서 직접 제공되지 않아 collision bounds에서 유도한다. 마찰과 천의 재질 계수에는 실험용 가정이 들어간다. 따라서 [물성 처리 코드](src/replica_physics_twin/physical_properties.py)와 manifest의 출처는 숫자 자체만큼 중요하다. 제공값, 기하에서 유도한 값, 교정 전 가정값이 모두 하나의 ‘정확한 물성’으로 합쳐지면 이후 결과 오차의 원인을 판단할 수 없기 때문이다.

의류는 2D flex grid와 매달린 가장자리의 hanging-edge constraint로 모델링했다. 강체 옷 메시의 자세만 바꾸는 대신 정점들이 움직일 자유도를 주고, Unreal의 표시 메시를 flex 표면의 변형에 대응시킨다. 현재 격자는 의류마다 8 × 14 = 112개, 합계 224개 정점이다. 질량 합은 source mass를 따르지만 Young's modulus 25,000/12,000Pa, 두께 0.002/0.001m, damping 0.06/0.04, drag coefficient 1.35는 실측 검증된 직물 특성이 아니다. 그림 1에서 확인되는 변형은 이 모델과 가정에 의한 결과이며, 특정 실제 의류의 처짐이나 진동을 정확히 재현했다는 결론에는 측정 비교가 더 필요하다.

### 조작을 위치 변경 대신 물리 입력으로 다룬다

선택은 단일 클릭 또는 Shift+클릭으로 관리하고, 드래그는 유한한 힘을 가하는 입력으로 연결한다. `I`의 impulse, `T`의 lift/drop, `P`의 일시정지·재개, `R`의 reset은 각각 힘 응답, 중력 응답, 시간 진행, 기준 상태 복원을 분리해 관찰하는 수단이다. 카메라의 우클릭 회전과 `WASD/QE` 이동은 그 상태를 바라보는 시점만 바꾼다.

이때 물체를 빠르게 움직이는 장면 하나보다 중요한 질문은 입력이 어떤 body에 적용되었으며 그 뒤 어떤 상태가 계산되었는가이다. 강체는 pose를, 의류는 변형 정점을 통해 결과를 표시하므로 두 표현을 동일한 단순 transform으로 처리할 수 없다. 객체 이름·원본 ID·형상 경로·질량 출처를 manifest와 bridge에서 이어 놓은 것은 이러한 입력과 결과를 추적하기 위한 구현상의 기여다. Replica/ReplicaCAD 원자료와 MuJoCo·Unreal 엔진 자체는 외부 기반이며, 이 연구가 새로 수행한 범위는 그 사이의 장면 처리, 충돌 선별, 물성 기록, 통신과 상호작용의 구성이다.

## 과거 PASS와 현재 자전거 FAIL이 함께 남아 있는 이유

[과거 CAD 구현 보고서](REPLICA_CAD_IMPLEMENTATION_REPORT.md)는 source-to-MuJoCo 질량 대응, 세 선택 객체의 낙하·접촉, 자전거와 room shell의 접촉 검증이 통과했다고 기록한다. 그러나 2026-09-16에 확인한 생성 모델은 그 보고서의 모델 규모와 다르다. 현재 파일을 설명하면서 과거 숫자나 판정을 그대로 가져오면 다른 조건의 결과를 같은 것으로 취급하게 된다.

| 모델·검증 항목 | 과거 CAD 구현 보고서 | 2026-09-16 현재 파일 대조 |
|---|---:|---:|
| bodies / geoms | 593 / 117 | 337 / 150 |
| flexes / 전체 flex vertices | 2 / 480 | 2 / 224 |
| equality constraints | 25 | 17 |
| 전체 joints | 동일 비교값으로 사용하지 않음 | 673 |
| source mass | dataset config | 9.0 / 2.0 / 0.6kg, 제공값과 일치 기록 |
| 낙하·접촉 검증 | 당시 PASS | **현재 자전거 낙하 판정 FAIL** |

현재 수치의 근거는 [manifest 대조 요약](docs/research-archive/evidence/inspected-manifest-summary.json)이다. 의류 정점 수가 각 240개에서 각 112개로 달라졌고 bodies·geoms·constraints도 바뀌었다는 사실은 확인된다. 그러나 이 차이만으로 어느 변경이 현재 실패를 일으켰는지 확정할 수는 없다. 과거 보고서는 수정하지 않고 해당 구성에 대한 기록으로 유지한다.

재검증에서는 Python 3.13.10 / MuJoCo 3.10.0으로 현재 모델이 컴파일되었다. 이후 기존 [물리 검증 스크립트](scripts/verify_replica_cad_physics.py)가 다음 오류로 중단되었다.

```text
body did not fall under gravity: replica_bike_02_100
```

이는 모델을 읽고 생성하는 단계의 성공과 요구한 동역학 응답의 성공이 다르다는 사례다. 또한 오류 메시지가 자전거 낙하 판정을 가리킨다는 사실과, 실제 원인이 중력 설정 하나라는 주장은 구분해야 한다. 현재 timestep 0.0005s에서 스크립트의 1,800 step은 0.9초다. 고정 step 수가 의미하는 관찰 시간, 초기 pose, 주변 접촉, constraint, 엔진 버전을 같은 입력에서 분리해 조사해야 한다. 현 기록만으로 원인은 확정되지 않았으며, 검증을 통과시키기 위한 모델 또는 판정 기준의 수정은 하지 않았다. 실행 환경과 오류는 [재검증 JSON](docs/research-archive/evidence/reverified-physics-2026-09-16.json)에 보존되어 있다.

영상과 수치가 서로 모순된다고 단정할 필요도 없다. 보존 영상은 자전거 이동과 의류 변형의 존재를 보여주지만, 촬영 당시 입력·모델·시간 조건이 현재 검사와 같다는 근거는 부족하다. 반대로 현재 FAIL을 숨기고 영상만으로 물리 검증을 대신할 수도 없다. 이 연구의 현재 상태는 상호작용 구현과 과거 검증 기록이 존재하며, 현재 생성 모델의 낙하 재현성은 해결해야 할 문제로 남아 있다는 것이다.

## 물리 환경의 연결에서 실물 재현으로 가기 위해 남은 검증

자료가 뒷받침하는 결론은 외관, 충돌 형상, 물성 출처를 분리하면서 하나의 객체 상태로 다시 연결할 수 있다는 것이다. `office_0`의 책장 오탐 제거와 상판 proxy 수정은 객체 명칭과 충돌 근사를 자료에 맞게 고치는 과정이었다. ReplicaCAD 전환은 정확한 template이 없는 대상을 억지로 유지하기보다 원본 형상·배치·질량의 출처를 연결할 수 있는 객체로 실험을 다시 구성한 과정이었다. 두 경로 모두 시각적인 자연스러움만으로 모델의 정당성을 판단할 수 없다는 문제를 드러냈다.

물리적 동일성을 주장하려면 남은 불확실성을 순서대로 줄여야 한다. 우선 현재 자전거 실패를 같은 commit·환경·MJCF/manifest hash에서 재현하고, step 수와 관찰 시간, 시작 자세·접촉·제약의 영향을 분리해야 한다. 원인이 확인된 뒤 동일 판정으로 수정 전후를 비교해야 과거 PASS와 현재 FAIL 사이의 설명이 생긴다. 문서의 모델 규모 역시 빌드 manifest에서 자동 생성하면 현재 파일과 오래된 설명의 불일치를 줄일 수 있다.

그다음은 물성 및 충돌 근사의 교정이다. 질량, 경사면의 미끄럼 시작, 낙하 후 반발, 의류의 정적 처짐과 진동을 측정하고, 제공값·유도값·가정값 각각의 오차를 기록할 필요가 있다. AABB와 convex decomposition, 개선한 메시를 같은 장면에서 비교하면 오목 구조·얇은 면의 단순화가 침투·정착·계산시간에 미치는 영향을 나눌 수 있다. 천에서도 격자 밀도와 고정 경계, 탄성 계수를 함께 바꾸기보다 조건을 나누어 비교해야 한다. 이들은 아직 수행한 평가 결과가 아니라 현재 모델에서 도출한 후속 실험이다.

연구실의 3DGS 외관과 연결하는 경우에도 같은 원칙이 유지된다. GS는 외관을 표현하고 검증된 geometry와 object transform이 물리 상태를 담당하도록 연결할 수 있지만, 외관이 사실적이라는 이유로 질량·마찰·충돌 정확도가 확보되지는 않는다. 이 저장소가 제공하는 출발점은 그러한 역할 분리와 출처 추적 구조이며, 실측 교정된 연구실 디지털 트윈의 완성은 별도 검증을 요구한다.

## 장면을 다시 생성하고 검증하는 경로

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
| 영상 원본 | 그림 1의 MP4와 원본 링크 | `02-ReplicaPhysicsTwin/originals/original-videos/` |
| 환경·복사 검증 | [전체 복원 범위](DATA_AND_RESTORE.md) | 컬렉션 `_shared/`, `_control/manifests/`, 프로젝트 `RESTORE.md` |

전체 원본 프로젝트는 2,192개 파일, 48,391,237,322 bytes의 보존·SHA-256 대조 기록이 있다. 별도 영상 등의 범위는 상위 보존 기록을 따른다.
Git clone만으로 대형 입력·생성 모델·전체 Unreal 환경이 복원되지는 않는다. 현재 로컬 보존과 USB 외부 사본 검증, 초기화 후 실행 성공은 각각 별도 상태다.
ReplicaCAD 원자료는 [AI Habitat 공식 배포](https://huggingface.co/datasets/ai-habitat/ReplicaCAD_dataset)의 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 조건을 따른다.
기존 README는 같은 루트의 [RESEARCH_REPORT.md](RESEARCH_REPORT.md)에 바이트 그대로 보존해 상대 링크 기준을 유지했다. 상세 한국어 분석은 [README.ko.md](docs/research-archive/README.ko.md)에서 계속 읽을 수 있다.
