# 실험 파일 안내

현재 명세는 [현재 설계와 데이터 검토](CURRENT_DESIGN_AND_DATASET_REVIEW.md),
실행 명령은 [서버 안내](../server/README.md)가 기준입니다.

회의 후 쟁점과 다음 검증은 [지금까지 고민한 문제 정리](CONCERNS_AND_NEXT_VALIDATION.md)를 참고하세요.

## 현재 사용하는 파일

| 용도 | 위치 |
|---|---|
| 원본 환경·기본 프롬프트·정답 로그 | `vendor/escapebench/` — 고정 원본, 수정하지 않음 |
| 현재 역할 분할 / 단서 평가 주석 | `data/roles/`, `data/clues.json` |
| 버전 관리 분류 정책 | `data/cohort_policy_v1.json` |
| Solo/Peer 프롬프트·기억·비용·스케줄 | `scripts/adaptive_escape.py` |
| 기반 환경·분리 가방·통신 / 공용 가방 | `scripts/coop_original.py`, `central_solo.py`, `original_escape.py` |
| 실행·생성·로그·재개 | `scripts/run_matrix.py`, `greedy_generation.py`, `run_model.py` |
| 현재 실행 목록 / 집계 | `scripts/run_nightly.py`, `run_cohort.py`, `cohort_policy.py` |
| 제출 | `server/submit-nightly.sh`, `nightly.sbatch`, `phi-prepare.sbatch` |
| 설치·전송·Phi 준비 | `server/setup.sh`, `upload.sh`, `scripts/download_phi.py`, `download_32b.py` |
| 실제 토크나이저와 합법 이동 정답 재생 검사 | `scripts/check_protocol.py` |
| 분할 생성·검사 | `scripts/make_roles.py`, `search_splits.py`, `export_roles.py`, `split_metrics.py`, `analyze_suitability.py`, `audit_split_paths.py` |
| 로그 해석 | `scripts/analyze_collaboration.py`, `matrix_report.py`, `check_matrix_smoke.py` |
| 재현 근거 | `experiments/evidence/` |
| 분할 v4 정비본 (전체 12게임: 사용 11·제외 1, 실험 연결 전) | [`data/split_v4/`](../data/split_v4/README.md), `scripts/split_v4.py`, [제안](SPLIT_V4_PROPOSAL.md) |

`run_cohort.py`의 report 함수와 `run_model.py`의 모델 로더 등은 현재 코드가 사용합니다.
이름이 옛 실험처럼 보여도 파일을 옮기면 import·재개 해시·명령 경로가 깨질 수 있습니다.
따라서 코드는 경로를 유지하고, 실행 진입점은 `submit-nightly.sh` 하나로 안내합니다.

## 과거 실험·보조 경로

| 묶음 | 위치 / 의미 |
|---|---|
| 초기 JSON 8문제 | `data/pilot/`, `data/source/`, `build_pilot.py`, `coop_escape.py`, `validate_pilot.py` |
| 초기 모델·Solo 파일럿 | `run_experiment.py`, `solo_experiment.py`, `run_solo_suite.py`, `experiments/solo_pilot.json` |
| 원본 단일 플레이 비교 | [ORIGINAL_PROTOCOL.md](ORIGINAL_PROTOCOL.md), `run_original.py`, `original_examples/` |
| 구 분할 감사 | `data/split_audit*.json` — 현재 집계 분류의 근거 파일은 아님 |
| 과거 결과·서버 로그 | `outputs/matrix/`, `outputs/gsds/` — 원본 경로·내용 보존, 새 결과에 혼합하지 않음 |
| 과거 문서 원문 | [archive](archive/README.md) |

2026-11-25에 옛 서버 제출 스크립트, 상태 진단 실험, 정적 평면도를 삭제했습니다. 필요하면 커밋 `653db7f`에서
복구합니다. 흩어진 과거 설명은 아카이브로 보관했으며, 그 안의 명령에는 삭제한 파일이 포함될 수 있습니다.
