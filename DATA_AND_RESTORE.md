# 전체 원본 데이터와 복원 범위

**2026-09-16 최종 보존 상태:** 조사한 Windows 연구 원본과 WSL 전체 export, 연구별 직접 추출본, conda·Unity·Unreal 환경 archive의 로컬 내용 검증을 마쳤다. USB 전송·외부 사본 검증과 초기화 후 전체 실행은 아직 수행하지 않았다. 실제 복사 목록·해시·확인하지 못한 자료는 개인 보존 묶음의 `PRESERVATION_STATUS.md`와 `_control/manifests/`를 기준으로 확인한다.

이 연구는 독립 저장소 `ReplicaPhysicsTwin`으로 관리한다. GitHub에는 코드·문서·공개 가능한 근거를 두며, 컴퓨터 초기화 대비 전체 보존본은 별도의 `ResearchCollection/02-ReplicaPhysicsTwin/`에 있다. 원시 데이터와 대형 자산은 Git clone만으로 복구되지 않는다.

| 자료 | 실제 역할 | 전체 보존 위치 |
|---|---|---|
| Replica 분할 다운로드와 보조 구성 | 초기 office_0 스캔 공간 입력의 원자료 | `originals/windows/URLabWorkspace/ReplicaPhysicsTwin/data/downloads/` |
| 추출·처리 데이터 | 원본 객체·형상·장면의 재처리 근거 | 같은 원본 프로젝트의 `data/raw`, `data/processed`, `data/derived` |
| ReplicaCAD apt_0 입력과 변환 결과 | 실제 객체 형상·질량 metadata와 충돌체/MJCF 생성 | 원본 프로젝트 `data/` 및 `outputs/replica_cad/` |
| Unreal 프로젝트 | Content·설정·소스·남은 빌드 산출물 | 원본 프로젝트 `unreal/` |
| 소스 이력·실험 로그 | 코드 버전과 실패·검증 기록 | 원본 프로젝트 `.git`, `outputs`, 보고서 전체 |
| 시연 영상 | 원래 파일명·바이트를 유지한 사용자 영상 | `originals/original-videos/` |

전체 프로젝트 2,192개 파일, 48,391,237,322 bytes를 복사하고 SHA-256을 대조했다. 검사 기록은 비공개 보존 묶음의 `_control/manifests/replica-full*`에 있다. 영상 파일 등 다른 별도 항목의 최종 상태는 상위 보존 보고서를 따른다.

Windows Python·MuJoCo·Unreal 실행 환경도 상위 `_shared/`에서 별도로 보존한다. 보존 폴더의 `RESTORE.md`에 원래 경로·복사 순서·실행 전 확인 항목을 적었다. 데이터의 원저작권·이용 조건은 기존 출처를 유지한다.

현재 C: 로컬 복사는 외부 백업이 아니다. USB의 용량·파일시스템을 확인하고 전체 복사·대상 재읽기 검증이 끝나야 초기화 준비가 된다. 현재 물리 모델의 자전거 낙하 검증 실패는 그대로 남아 있으며, 파일 보존 성공과 모델 검증 성공을 구분한다.
