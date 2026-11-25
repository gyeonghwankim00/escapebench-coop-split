# Cooperative Escape Room Lab

EscapeBench의 같은 A/B 분할 환경에서 **Solo 중앙 통제와 Peer 협력**을 비교합니다.
현재 실행은 **프로토콜 v7 / `nightly-v6`**입니다. 과거 결과와 합쳐 집계하지 않습니다.

| 바로 찾기 | 문서 |
|---|---|
| 업로드 → 제출 → 상태 확인 → 다운로드 | [서버 실행 안내](server/README.md) |
| 분할 근거·프롬프트·기억·평가·문제별 적합성 | [현재 설계](experiments/CURRENT_DESIGN_AND_DATASET_REVIEW.md) |
| 현재/과거 코드와 데이터 구분 | [실험 파일 안내](experiments/README.md) |
| 분할 2D 시각화·직접 플레이 | [협력 방탈출 플레이룸](https://claude.ai/artifact/7P1za2Db48uZGcE1BNQCXr) |
| 변경 방향과 과거 문서 | [아카이브](experiments/archive/README.md) |

## 현재 비교

- Solo: 양쪽 현재 관측과 역할별 기억, 공용 가방. 매 판단 A/B와 행동 하나를 선택합니다.
- Peer: 각자 관측·기억·가방. 최대 4판단 연속 실행하며 `send`/`give`/`yield`로 제어를 넘깁니다.
- Qwen3-14B / Phi-4, NF4 4비트, greedy, 생성 256토큰, 문맥 8192, batch 1.
- 힌트 없이 팀 500환경 행동·최대 1000판단. 역할당 저장 기억 9,000자이며 현재 관측·최근 행동·가방은 별도입니다.
- 12개 easy 중 원본 결함이 있는 1-4를 제외한 11개 × Solo/Peer × 2모델 = **44에피소드**.
- [고정 분류](data/cohort_policy_v1.json): 핵심 6개, 확장 4개, 당구장 대조군 1개를 구분합니다. 핵심/확장 평균은 별도로 계산합니다.

정답 재생은 환경과 입력 구성의 검사이며 모델 성능 검증이 아닙니다.
원본 BaseAgent의 환경과 기본 프롬프트를 바탕으로 하지만 기억·역할·스케줄·기본 무힌트 조건이 달라 원 논문 실험의 그대로 재현은 아닙니다.

## 실행

로컬 프로젝트에서 `bash server/upload.sh`, 서버 `~/escape-lab`에서
`bash server/submit-nightly.sh`를 사용합니다. 상세 전제와 결과 다운로드는
[서버 안내](server/README.md)에 한 곳으로 정리했습니다.

CPU 검사:

```bash
python3 -m scripts.check_protocol --output outputs/protocol-check.json
python3 -m unittest discover -s tests
```

첫 명령은 정답을 아는 Solo 스크립트로 11개를 재생합니다. 실제 토크나이저 검사에는
`--tokenizer 로컬_모델_폴더`를 추가합니다. 가중치를 로딩하거나 추론하지 않습니다.

## 직접 플레이

현재 분할 v3를 직접 풀어보거나 2D 지도로 보려면 [협력 방탈출 플레이룸](https://claude.ai/artifact/7P1za2Db48uZGcE1BNQCXr) 아티팩트를 사용합니다.
로컬 브라우저 앱(`app.py`, `play_current.py`, `web/`)은 아티팩트로 대체해 2026-11-25에 삭제했습니다.

원본 출처와 고정 커밋은 [vendor 안내](vendor/escapebench/ADAPTER_NOTES.md),
초기 연구 구상은 [제안서](proposal.md)에 있습니다. 제안서는 현재 구현 명세가 아닙니다.
