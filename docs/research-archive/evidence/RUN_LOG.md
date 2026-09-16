# RUN_LOG

## 2026-08-11T11:32:24+09:00

- Phase: 0 — 환경 읽기 전용 점검
- 실행자: Codex
- 실행 명령:
  - 대상 경로·상위 파일 목록 확인
  - Unreal Editor 실행 파일 버전 메타데이터 확인
  - Python/uv 설치 버전 및 MuJoCo import 확인
  - 최소 MJCF `mj_step` 실행
  - 기존 RobotLLM의 URLab·AMjManager·Bridge·Transport 위치 읽기 전용 검색
  - Replica 분할 파일 크기와 `office_0` 추출 디렉터리 상태 확인
  - 시스템 CPU·RAM·GPU·디스크 스냅샷 확인
- 작업 목적: Phase 0 선행 조건과 보호 범위 확인
- 결과: **PASS_WITH_WARNINGS**
- 생성·수정 파일:
  - `ENVIRONMENT_REPORT.md` 갱신
  - `RUN_LOG.md` 생성
- 변경하지 않은 대상:
  - `${ROBOTLLM_ROOT}` 전체
  - Replica 분할 다운로드 파일 및 `data\raw\replica_v1\office_0`
- 로그 위치: Codex 실행 출력; 별도 시뮬레이션 로그는 아직 없음
- 사용자 확인 여부: **Phase 0 승인 수신**
- 다음 작업: Replica 이용 조건·추출 승인·실제 경로 확인 후 Phase 1 데이터 검증

## 2026-08-11T11:47:53+09:00

- Phase: 1 — Replica `office_0` 데이터 준비
- 실행자: Codex
- 실행 명령:
  - `scripts\download_replica_office0.ps1 -ProjectRoot ${REPLICA_ROOT}`
  - 실행 정책 차단 후 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...`로 재실행
  - `python -m unittest discover -s tests -p test_office0_analysis.py`
  - `python -X utf8 -m replica_physics_twin.office0_analysis --scene-dir ... --derived-dir ...`
- 작업 목적: 승인된 Replica 분할 아카이브에서 `office_0`만 추출하고 geometry·semantic·checksum을 검증
- 결과: **NEEDS_USER_VERIFICATION**
- 추출 결과: 19 files, 1,000,725,117 bytes; 필수 파일 4개 확인
- 생성·수정 파일:
  - `data\raw\replica_v1\office_0\`에 승인된 선택 추출 결과 생성
  - `data\derived\office_0\checksums.sha256`
  - `data\derived\office_0\mesh_stats.json`
  - `data\derived\office_0\semantic_summary.json`
  - `data\derived\office_0\scene_manifest.json`
  - `DATASET_REPORT.md`
  - `src\replica_physics_twin\office0_analysis.py`
  - `tests\test_office0_analysis.py`
- 변경하지 않은 대상:
  - `${ROBOTLLM_ROOT}` 전체
  - `data\downloads\replica_v1`의 분할 아카이브 및 보조 ZIP
- 검증: analyzer fixture tests 3/3 통과; 모든 PLY 589,517 vertices·588,759 faces; semantic metadata 내부 불일치 0건
- 주의: semantic mesh에 object 목록 미등록 face ID `[0, 41, 43, 47]`가 있어 최종 승인 전 사용자 확인 필요
- 사용자 확인 여부: **Phase 1 초기 승인 수신; 최종 데이터 승인 대기**
- 다음 작업: `DATASET_REPORT.md`와 unmapped semantic ID를 사용자 확인 후 Phase 2 MuJoCo 단독 검증

## 2026-08-11T12:13:42+09:00

- Phase: 2 — MuJoCo 단독 물리 검증
- 실행자: Codex
- 실행 명령:
  - `python -X utf8 -c "... run_validation(..., max_steps=2000) ..."`
  - `python -X utf8 -c "... pytest.main(['-q']) ..."`
  - `powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\test_download_script.ps1`
- 작업 목적: 30cm 낙하, 중력·접촉·마찰·정착, 수평 impulse 및 로그 재현성 검증
- 실패 원인 분석: 초기 `solref="0.02 1"`의 접촉 침투 17.02mm를 단일 변수 실험으로 확인; `solref="0.005 1"`에서 4.22mm로 감소
- 결과: **PASS**
- 핵심 결과: 첫 접촉 0.25s; 최종 z 0.0499964m; 정착 구간 최대 속도 `1.02e-15m/s`; impulse Δv 오차 0
- 생성·수정 파일:
  - `src\replica_physics_twin\physics_validation.py`
  - `tests\test_physics_validation.py`
  - `outputs\mjcf\phase2_box_drop.xml`
  - `outputs\reports\phase2\phase2_drop.jsonl`
  - `outputs\reports\phase2\phase2_impulse.jsonl`
  - `outputs\reports\phase2\phase2_summary.json`
  - `PHYSICS_VALIDATION_REPORT.md`
  - `README.md`
- 전체 검증: Python **12 passed**; PowerShell startup path test **PASS**; production summary `passed=true`
- 변경하지 않은 대상: `${ROBOTLLM_ROOT}` 전체; Unreal 프로젝트 및 bridge 코드
- 사용자 확인 여부: **Phase 3 시작 승인 대기**
- 다음 작업: 사용자 승인 후 Unreal 표시 전용 연결과 좌표계·스케일 검증

## 2026-08-11T13:09:15+09:00

- Phase: 3 — MuJoCo ↔ Unreal 통신 검증
- 실행자: Codex
- 실행 명령:
  - `python -X utf8 -c "... pytest.main(['tests/test_bridge_protocol.py', '-q']) ..."`
  - `Build.bat ReplicaPhysicsTwinEditor Win64 Development -Project=...`
  - `UnrealEditor-Cmd.exe ... -ExecCmds="Automation RunTests ReplicaPhysicsTwin.Bridge.MappingAndSequence; Quit"`
  - `Build.bat ReplicaPhysicsTwin Win64 Development -Project=...`
  - 실제 Python CLI bridge + Unreal `-game` headless 실행
- 작업 목적: schema, state stream, command ACK/error, reconnect, m→cm/wxyz→FQuat, Chaos 비활성화, UE runtime 수신 검증
- 결과: **NEEDS_USER_VERIFICATION**
- 자동 검증: Python 전체 **17 passed**; PowerShell startup path test **PASS**; UE Editor/Game build **Succeeded**; UE automation **Success / EXIT CODE: 0**
- headless 증거: UE `Connected to MuJoCo bridge 127.0.0.1:7007`; bridge `state seq 1~6`, `sim_time 0.0→0.044`
- 생성·수정 파일:
  - `PROTOCOL.md`
  - `PHASE3_BRIDGE_REPORT.md`
  - `UNREAL_VISUAL_CHECKLIST.md`
  - `src\replica_physics_twin\bridge_protocol.py`
  - `src\replica_physics_twin\bridge_server.py`
  - `tests\test_bridge_protocol.py`
  - `scripts\run_phase3_bridge.ps1`
  - `unreal\ReplicaPhysicsTwin.uproject`
  - `unreal\Config\DefaultEngine.ini`
  - `unreal\Source\ReplicaPhysicsTwin\...`
  - `outputs\reports\phase3\...`
- 런타임 수정: GameMode BeginPlay의 `FObjectFinder` 사용으로 발생한 UE fatal을 `LoadObject`로 교체; Editor/Game 재빌드와 headless 재검증 통과
- 변경하지 않은 대상: `${ROBOTLLM_ROOT}` 전체; Replica 원본 데이터
- 사용자 확인 여부: **Unreal Play 화면·Output Log 확인 대기**
- 다음 작업: 체크리스트 확인 후 `Phase 3 승인` 수신 시 Phase 4 Replica 공간 시각화

## 2026-08-11T13:58:00+09:00

- Phase: 4 — Replica `office_0` 공간 시각화 준비
- 실행자: Codex
- 작업 목적: 원본 mesh를 보존한 Unreal 파생 메시 생성, 센티미터·Z-up 변환, 런타임 로더와 내부 카메라 연결
- 생성 결과: OBJ, `.rptmesh` 런타임 바이너리, transform metadata
- 메시 규모: 589,517 vertices, 1,177,518 triangles; 출력 bounds 약 `4.40m × 5.01m × 2.99m`
- 검증: Python 전체 **18 passed**; 파생 바이너리 header/count/bounds 확인; UE Editor/Game build **Succeeded**; UE automation **Success / EXIT CODE: 0**
- Unreal 변경: `ProceduralMeshComponent` 활성화, `ReplicaOfficeVisualActor`, 원점·축 debug marker, 공간 내부 camera, visual mesh 실패 시에만 checkerboard fallback
- 변경하지 않은 대상: `${ROBOTLLM_ROOT}` 전체; Replica 원본 `data\raw\replica_v1\office_0`
- 사용자 확인 여부: **Phase 4 Unreal Play 화면 확인 대기**
- 다음 작업: `UNREAL_VISUAL_CHECKLIST.md`의 Phase 4 항목 확인 후 승인 수신

## 2026-08-11T14:35:00+09:00

- Phase: 5 — MuJoCo 고정 충돌 공간 구성 및 Unreal debug 준비
- 실행자: Codex
- 실행 명령:
  - `$env:PYTHONPATH='src'; python scripts/build_office0_collision_proxy.py`
  - `$env:PYTHONPATH='src'; python -m pytest -q`
  - UnrealBuildTool `ReplicaPhysicsTwinEditor Win64 Development -Project=...`
- 작업 목적: semantic mesh 기반 바닥·벽·책상·책장 collision proxy, visual bounds 정렬, 다중 낙하 검증, Unreal debug render 연결
- 결과: **NEEDS_USER_VERIFICATION**
- 자동 검증: 프록시 정렬 `passed=true`; MuJoCo 다중 낙하 4/4 통과; Python **20 passed**
- 생성·수정 파일:
  - `src\replica_physics_twin\office0_collision.py`
  - `tests\test_office0_collision.py`
  - `scripts\build_office0_collision_proxy.py`
  - `outputs\mjcf\office0_collision_proxy.xml`
  - `outputs\metadata\office0_collision_proxy.json`
  - `outputs\reports\phase5\phase5_collision_summary.json`
  - `outputs\reports\phase5\phase5_collision_contacts.jsonl`
  - `unreal\Source\ReplicaPhysicsTwin\Private\Bridge\MuJoCoBridgeDemoGameMode.cpp`
  - `PHASE5_COLLISION_REPORT.md`
  - `UNREAL_VISUAL_CHECKLIST.md`
  - `README.md`
- 책장 근거: semantic bookcase 후보 없음; `object_id=49`, `class=undefined`를 low-confidence provisional fallback으로 기록
- Unreal 빌드 상태: C++ compile 성공; 현재 열린 Unreal Editor가 DLL을 잠가 link가 대기 중
- 변경하지 않은 대상: `${ROBOTLLM_ROOT}` 전체; Replica 원본 데이터
- 사용자 확인 여부: Unreal Editor 종료 후 재빌드 및 collision debug 화면 확인 대기
- 다음 작업: 사용자가 Editor를 닫으면 재빌드하고 Phase 5 debug 정렬 확인 요청

## 2026-08-11T14:58:00+09:00

- Phase: 5 — collision debug 원인 분석 및 책장 fallback 제거
- 실행자: Codex
- 작업 목적: 사용자 screenshot에서 보인 잘못된 책장 프록시의 출처 확인 및 authoritative collision에서 제거
- 확정 원인: `object_id=49`, `class=undefined` geometry를 semantic 책장 후보가 없는 상태에서 가장 큰 수직 geometry라는 이유로 책장으로 자동 승격함
- 수정: unclassified fallback 자동 생성 제거; `unresolved_roles.bookcase`와 potential object IDs를 metadata에 기록
- 자동 검증: Python 전체 **20 passed**; 프록시 정렬 `passed=true`; MuJoCo floor/desk 다중 낙하 **3/3 passed**
- 생성·수정 파일:
  - `src\replica_physics_twin\office0_collision.py`
  - `tests\test_office0_collision.py`
  - `outputs\mjcf\office0_collision_proxy.xml`
  - `outputs\metadata\office0_collision_proxy.json`
  - `outputs\reports\phase5\phase5_collision_summary.json`
  - `PHASE5_COLLISION_REPORT.md`
  - `UNREAL_VISUAL_CHECKLIST.md`
  - `README.md`
- 변경하지 않은 대상: `${ROBOTLLM_ROOT}` 전체; Replica 원본 데이터
- 사용자 확인 여부: 다음 Play에서 자홍 fallback 제거 및 바닥·벽·책상 정렬 확인 대기
- 다음 작업: 책장 실제 대상/semantic ID 확인 후 Phase 5를 완료하거나 unresolved로 유지

## 2026-08-11T15:08:00+09:00

- Phase: 5 — 책상 collision proxy 과대 AABB 수정
- 실행자: Codex
- 확정 원인: `desk_12`, `desk_58`가 전체 semantic instance bounds를 사용해 바닥부터 상판까지 하나의 큰 box로 표시됨. 좌표 변환이나 JSON 로딩 오류는 로그로 배제함.
- 수정: semantic mesh의 상단 근수평 face band를 추출해 얇은 tabletop box로 변경
- 자동 검증: 프록시 정렬 `passed=true`; MuJoCo 다중 낙하 **3/3 passed**; Python **20 passed**
- 생성·수정 파일:
  - `src\replica_physics_twin\office0_collision.py`
  - `tests\test_office0_collision.py`
  - `outputs\metadata\office0_collision_proxy.json`
  - `outputs\mjcf\office0_collision_proxy.xml`
  - `outputs\reports\phase5\phase5_collision_summary.json`
  - `PHASE5_COLLISION_REPORT.md`
  - `README.md`
- 사용자 확인 여부: Play 재시작 후 얇은 노란 상판 box와 바닥·벽 정렬 확인 대기
- 다음 작업: 책상 debug 정렬 확인 후 책장 대상 입력 또는 Phase 5 unresolved 보고

## 2026-08-11T14:19:00+09:00

- Phase: 4 — Replica `office_0` 공간 시각화 사용자 확인
- 결과: **COMPLETE_WITH_USER_VERIFICATION**
- 사용자 확인: Unreal Play 화면에서 내부 공간·바닥·벽·문·소파·의자·테이블·축 마커가 정상적으로 보임
- 최종 렌더링 원인·해결: 내부 카메라용 단면 재질과 불충분한 시각 재질 문제를 확인하고, `VertexColorMaterial`(`two_sided=true`)과 중립 vertex color를 적용
- 자동 검증: Python 전체 **18 passed**; UE Editor/Game build **Succeeded**; UE automation **Success / EXIT CODE: 0**
- 다음 작업: Phase 5 MuJoCo 고정 충돌 공간 구성 준비

## 2026-08-11T16:05:19+09:00

- Phase: 5 종료 및 Phase 6 — `tissue_box` 동적 물체 구현
- 실행 명령:
  - `$env:PYTHONPATH='src'; python scripts/build_office0_collision_proxy.py`
  - `$env:PYTHONPATH='src'; python scripts/build_office0_tissue_box.py`
  - `$env:PYTHONPATH='src'; python -m pytest -q`
- 책장 판정: `office_0` semantic object inventory 64개에 bookcase/bookshelf/shelving/shelf/rack/cabinet 인스턴스가 없어 `not_present_in_scene`으로 확정; `undefined` geometry 자동 승격 금지 유지
- Phase 6 결과: object ID `28` / wire ID `tissue_box`; support `desk_58`; 30cm lift/drop; first contact step `125`; final z error 약 `3.62e-6m`; final speed 약 `5.52e-9m/s`
- 자동 검증: Phase 5 alignment `passed=true`; Phase 6 lift/drop `passed=true`; Python **24 passed**
- 사용자 확인 대기: Unreal Editor 재빌드 후 Phase 6 Play에서 cyan tissue_box 1개, `T` lift/drop, `R` reset 확인

## 2026-08-11T16:44:54+09:00

- Phase: Phase 6 reset/visual regression fix
- 실행 명령:
  - `$env:PYTHONPATH='src'; python scripts/build_office0_visual_mesh.py`
  - `$env:PYTHONPATH='src'; python scripts/build_office0_tissue_box.py`
  - `$env:PYTHONPATH='src'; python -m pytest -q`
  - UnrealBuildTool `ReplicaPhysicsTwinEditor Win64 Development -Project=...`
- 원인: Phase 6 MJCF keyframe이 30cm lift 상태라 `reset`이 T와 같은 높이에서 재시작함; Unreal actor는 Basic Cube 프록시만 표시하고 정적 메시의 object 28도 중복 표시함
- 수정: 시작/reset을 `desk_58` rest 위치로 변경, lift/drop 검증에서 T 동작을 명시적으로 적용, semantic object 28을 정적 메시에서 제외하고 별도 local dynamic visual mesh로 분리
- 결과: Python 전체 **26 passed**; Unreal Editor 빌드 **Succeeded**; Phase 6 bridge 재시작 완료
- 사용자 확인 대기: Unreal Play에서 실제 semantic tissue_box 1개, `T` lift/drop, `R` rest reset 확인
