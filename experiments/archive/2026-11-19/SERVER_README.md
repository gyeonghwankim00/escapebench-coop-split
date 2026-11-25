> 2026-11-19 정리 직전의 과거 문서입니다. 현재 실행 명령은 [서버 안내](../../../server/README.md)를 사용하세요. 본문에는 당시의 현재/미검증 표현이 남아 있습니다. 상대 링크만 새 보관 위치에 맞췄습니다.

# 현재 버전: v7 / nightly-v6

출력 형식은 Solo 3줄(Thought/Role/Action), Peer 2줄(Thought/Action)로 통일했습니다.
기억은 역할별 관측 4000자·수신 1500자·피드백 500자로 분리하며 현재 관측 중복을 제외합니다.
집계는 `data/cohort_policy_v1.json`의 핵심 6개/확장 4개를 따로 사용하고 정책 해시를 저장합니다.
nightly 배열 인덱스는 유지하지만 1-4 두 조건은 자동으로 건너뜁니다. 모델당 22실험입니다.
새 결과 폴더는 `nightly-v6`입니다. 이전 버전 실행의 이어받기는 허용되지 않습니다.
업로드·제출 명령은 동일합니다. 아래 과거 안내의 결과 경로 대신 nightly-v6를 사용하세요.
상세 규칙·검증 근거는 [현재 설계](../../CURRENT_DESIGN_AND_DATASET_REVIEW.md)를 참고하세요.

---

# 현재 실행: 유연한 스케줄과 관측 기억 (프로토콜 v6 / nightly-v5)

Solo는 매 판단에서 `Role: A` 또는 `Role: B`와 `Action:`을 한 번의 모델 호출로
선택합니다. 두 위치는 유지하며, 선택한 쪽의 현재 장면에서 행동합니다. 양쪽 현재 관측과
공용 가방을 제공하고 send/give/yield는 허용하지 않습니다.

Peer는 한쪽이 최대 4판단을 연속 실행합니다. `yield()` 또는 성공한 send/give는 즉시
상대에게 넘기고, 상대도 같은 규칙을 따릅니다. 양도는 일시적이며 자동 휴면·종료가 없습니다.
오류도 연속 판단 수에 포함해 상대에게 기회가 돌아가도록 합니다. 이 상한은 정답·숨은 상태에
의존하지 않습니다. 메시지와 물건은 기존과 같이 거리 제한 없이 전달합니다.

- 기본 예산: 팀 환경 행동 500, 팀 판단 최대 1000. 각 호출의 토큰·생성 시간도 기록합니다.
- 유효한 yield는 환경 비용 0, 판단 비용 1. 다른 행동·잘못된 명령은 환경 비용 1입니다.
- Solo 역할 선택에는 추가 호출·환경 비용이 없습니다. 자유 선택의 이점도 기준선에 포함됩니다.
- 기본 도움 정책은 `none`: 정체해도 자동 정답·강제 행동·순간이동이 없습니다.
  `--help-policy original`을 명시하면 50환경 행동 정체 도움 및 10도움 판단 후 강제를 사용합니다.
  이는 분할 환경에 맞춘 도움이며 원본 실험과 완전히 동일한 프로토콜이라는 뜻은 아닙니다.
- 기억: 실제 관측한 장면의 마지막 설명·행동 목록, 받은 메시지와 행동별 마지막 피드백을 지속 저장합니다.
  프롬프트에는 최근 기록부터 총 12000문자 안에 완전한 항목만 넣고 누락 개수를 표시합니다.
  최근 행동은 역할별 10개, 도움 중에도 유지합니다. Solo는 양쪽 기억을 한도 안에서 통합합니다.
  로그의 observed_memory/received_memory가 전체 저장본이며 실제 모델 노출은 generation.messages입니다.
- 저장 관측은 마지막 관측 시점의 스냅샷입니다. 상대가 문을 열어도 숨은 전역 상태를 자동
  공개하지 않습니다. 변경 후 재방문·이전 실패 재시도가 유효하다는 지침을 두 조건에 제공합니다.
- 엄격한 Action: 한 줄만 실행합니다. send 안의 괄호·행동 예시는 문자열로 전달합니다.
  300자 초과 메시지는 오류로 반환하고 일부만 전달하지 않습니다.

결과에는 environment_actions/action_cost/decision, 역할별 행동 수·방문 장소 수,
메시지·전달·양도·오류·입출력 토큰, 힌트·강제 행동을 기록합니다. 고정 예산 집계는
판단 줄 수가 아닌 환경 행동 누적으로 자릅니다. 중단·판단 예산 소진으로 부족한 예산 관측은
0점 처리하지 않습니다. 탈출은 원본 종료 조건이고, 진행률 100%와 별개입니다.

분할 검사 `python -m scripts.audit_split_paths --output data/split_audit_v6.json`은
정답을 알고 도달 가능한 곳으로 무료 이동하는 보수적 선별 검사입니다. game1-1, game1-3,
game2-4, game3-1은 control_or_review로 분리합니다. 암호를 미리 아는 가정 때문에 정보 의존성
생략을 실제 우회로 오인할 수 있으므로, 당구장 이외 문제는 비용 있는 경로와 단서 검토가 필요합니다.
나머지 8문제도 main_candidate이며 완전히 검증됐다는 뜻은 아닙니다. 집계의 주 평균은 동일
문제·동일 예산에서 관측이 완성된 main_candidate 쌍만 사용합니다. 모든 12문제는 진단용으로
실행하며 원본 데이터를 임의 수정하지 않습니다. 검사 입력은 결과 폴더에 동결합니다.

프로토콜 `escapebench-adaptive-v6`, 새 폴더 `nightly-v5`를 사용합니다. 구 결과와 이어 돌릴 수
없으며 모델 파일은 재사용합니다. 아직 서버에 제출하지 않았습니다.

로컬 업로드: `bash server/upload.sh`.
서버 프로젝트에서 제출: `bash server/submit-nightly.sh`.
결과 다운로드 시 기존 안내의 폴더명을 `nightly-v5`로 사용합니다.

---

이하 내용은 이전 프로토콜 기록입니다. 현재 규칙은 위 정의가 우선합니다.

# 현재 실행: 공용 가방 Solo (프로토콜 v5 / nightly-v4)

Solo는 A/B 양쪽 현재 관측과 기록을 받고 **실제 가방 하나**를 공유합니다.
`send`/`give`는 금지하며, 도구 전달 없이 다른 쪽에서 바로 사용합니다.
A/B 위치·교대·장면 분할·팀 예산은 Peer와 동일합니다.
[설계 및 비교 시 해석](../../MATRIX_PROTOCOL.md)을 확인하세요.

로컬에서 업로드:

```bash
bash server/upload.sh
```

서버에서 제출:

```bash
cd ~/escape-lab
bash server/submit-nightly.sh
```

모델은 기존 파일을 재사용하며 새 결과는 개인 연구실 폴더의 `outputs/nightly-v4`에 저장합니다.
새 결과를 로컬로 받기:

```bash
mkdir -p outputs/gsds
rsync -av -e 'ssh -p 22555' \
  gyeonghwankim@147.47.200.188:/shared/s2/lab04/gyeonghwankim/escape-lab/outputs/nightly-v4 \
  outputs/gsds/
```

기존 결과는 보존합니다. 이전 규칙의 중단 지점에서 재개하지 않습니다.
이하 v1/v2/v3 안내는 과거 기록이며 현재 결과 경로는 `nightly-v4`입니다.

---

# Solo 요청 제거 (프로토콜 v4 / nightly-v3)

Solo는 A/B 양쪽의 현재 관찰과 기록을 한 컨트롤러가 받습니다.
시스템 프롬프트는 원본 기본 행동 설명에 중앙 통제 규칙만 추가합니다.
Peer의 “상대 장면·가방을 볼 수 없다”는 문구는 포함하지 않습니다.

- 텍스트 요청/통신 `send`는 Solo에서 금지합니다. 엔진도 거부하며, 모델이 출력하면
  그 턴을 소비하는 오류로 기록합니다. 자동 교정이나 무료 재질문은 하지 않습니다.
- 물건 전달 `give`는 허용합니다. 가방을 역할별로 유지하므로 도구를 상대 가방으로
  옮기는 물리적 행동은 여전히 필요하며, Peer와 같은 한 팀 행동을 소비합니다.
- Solo는 A에게 다음 행동을 “요청”할 필요가 없습니다. A 차례가 오면 같은 컨트롤러가 직접
  수집/전달을 결정합니다. 이번 차례에는 현재 역할의 유효한 행동 하나만 실행합니다.
- Peer의 send/give, A/B 스케줄·시작 위치·가방·기억·예산은 기존 규칙을 유지합니다.

전체 파이프라인의 새 출력 폴더는 `nightly-v3`입니다. 기존 `nightly-v2`는 저장된 그대로 보존합니다.
모델 파일을 재다운로드할 필요는 없으며, 현재 명령으로 제출하면 새 프로토콜의 점검과 실행을 수행합니다.
아래 v2 안내는 당시 구현 기록입니다. 새 결과를 받을 때는 경로의 nightly-v2를 nightly-v3로 바꿉니다.

---

# Solo 조건 수정: 같은 A/B 환경의 중앙 통제 (protocol v3)

현재 `solo`는 **분할된 A/B 환경에서 한 에이전트가 양쪽 현재 관찰을 받는 조건**이다.
`coop`는 같은 환경의 A/B 역할이 자기 관찰·기록만 받고 send/give로 협력하는 조건이다.

| 항목 | Solo | Peer (`coop`) |
|---|---|---|
| 분할·A/B 초기 위치·장치 상태 | 동일 | 동일 |
| 가방·이동·물건 전달 규칙 | 역할별 분리, give 필요 | 역할별 분리, give 필요 |
| 스케줄·예산 | A/B 교대, 팀 500행동 | A/B 교대, 팀 500행동 |
| 관찰 | 양쪽의 현재 관찰 | 행동 역할의 현재 관찰 |
| 기억 | A 최근 10행동 + B 최근 10행동 | 각자 최근 10행동과 수신 업데이트 |
| 행동 | 이번 활성 역할의 한 행동 | 이번 활성 역할의 한 행동 |
| 프롬프트 문맥 상한 | 8192, 초과 시 오류 | 8192, 초과 시 오류 |

Solo의 전체 관찰은 실제 현재 장면에 보이는 것과 각 가방에 한정한다.
미탐색 장면, 숨은 물건, 정답·평가 주석은 공개하지 않는다.
중앙 관찰을 만드는 동안 장치 상태·진행 카운터·행동 캐시·우편함을 변경하지 않는다.
Solo는 상대에게 정보를 요청할 필요 없이 같은 정보를 직접 보지만, send도 같은 비용으로 사용할 수 있다.
원본 50행동 정체 도움과 강제 행동은 같은 분할 엔진의 역할별 도움 규칙을 사용한다.

기존 원본 단일 플레이는 `original_solo`로 실행할 수 있다.
구 프로토콜의 `solo` 파일은 **그대로 보관**하며 새 Solo로 재분류하지 않는다.
`matrix_report`는 구 Solo를 original_solo로 표시하여 새 Solo/Peer 쌍에서 제외한다.
`nightly-v1`은 과거 실험이고, 이번 수정은 `nightly-v2`에 저장한다.
Phi 준비 점검도 v2에서 다시 통과해야 한다. 다운로드한 모델 파일은 재사용한다.
실행 중인 v1 작업은 수정된 코드로 재개하지 말고 별도 결과로 보존한다.

```bash
# 로컬 Mac
bash server/upload.sh
# 서버 ~/escape-lab: 새 Solo + Peer, Qwen/Phi 각각 24회
bash server/submit-nightly.sh
# Qwen은 나중에 하고 Phi만 새 조건으로 돌릴 때
# bash server/submit-nightly.sh --phi-only
```

새 Qwen Solo뿐 아니라 Peer도 같은 8192 문맥·프로토콜로 새로 실행한다.
각 작업 최대 11시간 30분, 동시 최대 GPU 2장이다. 전체 작업은 더 오래 걸릴 수 있다.
Phi 다운로드·점검 후에만 Phi 본 작업이 시작된다.

```bash
# 로컬 Mac에서 완료된 새 결과 다운로드
mkdir -p outputs/gsds/logs
rsync -av -e 'ssh -p 22555' \
  gyeonghwankim@147.47.200.188:/shared/s2/lab04/gyeonghwankim/escape-lab/outputs/nightly-v2 \
  outputs/gsds/
rsync -av --include='nightly-*.out' --include='nightly-*.err' --exclude='*' \
  -e 'ssh -p 22555' gyeonghwankim@147.47.200.188:escape-lab/ outputs/gsds/logs/
python3 -m scripts.run_nightly --report --output-root outputs/gsds/nightly-v2
```

---

아래 내용은 이전 프로토콜의 실험 기록이다. 현재 Solo 정의와 실행은 위 안내를 따른다.

# 현재 실행: Qwen3-14B + Phi-4, 전체 easy 12문제 점검

데이터·프롬프트를 수정하지 않고 모델 계열에 따른 경향을 비교하는 **500행동 파일럿**입니다.
두 모델 × 12문제 × Solo/Peer = 48회, batch 1, 4비트, greedy, 원본 입력/50행동 정체 도움을 유지합니다.
500행동 미탈출을 최종 모델 능력이나 데이터셋 실패로 해석하지 않습니다.

```bash
# 로컬 Mac 프로젝트 폴더
bash server/upload.sh
# 서버 로그인 후
cd ~/escape-lab
bash server/submit-nightly.sh
squeue -u "$USER"
```

**이번에는 `cohort.sbatch`가 아니라 `submit-nightly.sh`를 사용합니다.**
스크립트는 다음 세 작업을 제출합니다.

1. Qwen 배열: 기존 개인 저장소 `models/Qwen3-14B` 사용, 24회, 동시에 GPU 1장.
2. Phi 준비: shared에 공식 `microsoft/phi-4` 고정 revision을 다운로드하고 GPU에서 실제 점검.
3. Phi 배열: 준비 작업이 성공해야 자동 시작 (`afterok`), 24회, 동시에 GPU 1장.

새 제출의 동시 GPU 사용은 최대 2장입니다. 이전에 별도로 제출한 작업은 이 제한에 포함되지 않습니다.
기존 nightly 작업이 대기/실행 중이면 제출 스크립트가 중복 제출을 거부합니다.
준비 작업 실패 시 Phi 배열은 취소되고 Qwen은 계속 진행합니다. 로그를 확인한 뒤 원인을 해결해야 합니다.

Phi revision은 `2db69c1c3e91a05d2c64a3185acfbaf36f744e25`입니다.
원본 BF16 가중치 저장 공간은 약 29GB이며 4비트 변환은 로딩할 때만 합니다.
`/shared/s2/lab04/본인계정/escape-lab/models/phi-4`에만 다운로드하며,
완료된 파일과 부분 다운로드 캐시를 재사용합니다. 개인 저장소에 Phi를 받지 않습니다.

Phi 준비는 최대 5시간(다운로드 제한 3시간, 실제 점검 runner 예산 1시간)입니다.
점검은 당구장/실험실 Solo/Peer 각각 70행동, batch 1입니다. 문제 성적을 기준으로 통과 여부를 정하지 않습니다.
실제 greedy 설정, 완결된 파싱 가능 행동, A/B 역할·평가 기록을 검사합니다.
점검 기록은 `preflight-JOBID/`에 별도로 보존하고 48회 본 파일럿에 포함하지 않습니다.

각 본 작업은 최대 11시간 30분, runner는 11시간 10분에 저장 후 중단합니다.
전체 파일럿이 하룻밤에 완료된다는 보장은 없습니다. SSH/PC를 꺼도 제출된 작업은 계속 실행됩니다.
실행 중 코드와 데이터는 수정하지 마세요. 오류는 자동으로 반복하지 않습니다.

### 결과 위치와 다운로드

두 모델의 결과는 모두 shared의 본인 폴더에 저장합니다.

```text
/shared/s2/lab04/본인계정/escape-lab/outputs/nightly-v1/
```

로그는 프로젝트 폴더의 `nightly-배열JOBID_인덱스.out/.err`,
`nightly-phi-prep-JOBID.out/.err`입니다. 완료 후 로컬 Mac에서:

```bash
mkdir -p outputs/gsds/logs
rsync -av -e 'ssh -p 22555' \
  gyeonghwankim@147.47.200.188:/shared/s2/lab04/gyeonghwankim/escape-lab/outputs/nightly-v1 \
  outputs/gsds/
rsync -av --include='nightly-*.out' --include='nightly-*.err' --exclude='*' \
  -e 'ssh -p 22555' gyeonghwankim@147.47.200.188:escape-lab/ outputs/gsds/logs/
python3 -m scripts.run_nightly --report --output-root outputs/gsds/nightly-v1
```

집계에는 GPU/모델 라이브러리가 필요하지 않습니다. `cohort-report.md`와 `cohort-results.json`에
50/200/500행동의 진행률·도움·강제 행동·환경 오류 수가 들어갑니다. 최초 도움 전 지표와 기존 협업 지표는
각 실행의 summary.json/collaboration.json에 남습니다. 모델 호출·토큰 수와 생성 감사도 기존대로 기록합니다.
모든 조건을 게임별로 비교하고, 도움 이후 진행률을 무도움 능력으로 해석하지 않습니다.

### Phi 다운로드 연결 오류 후 재개

2026-11-18 확인: Qwen 24회는 완료했지만 Phi 준비 작업 850639가 다운로드 중
`requests.exceptions.ChunkedEncodingError` / `Broken pipe`로 종료했습니다.
수정된 Phi 다운로더는 일시적 연결 오류를 최대 4번 시도하며 파일과 캐시를 보존합니다.
인증·권한·용량 오류는 자동 재시도하지 않고, 준비 작업의 총 다운로드 3시간 제한도 유지합니다.

```bash
# 로컬
bash server/upload.sh
# 서버: 기존 nightly 작업이 모두 끝난 뒤 Phi만 제출
cd ~/escape-lab
bash server/submit-nightly.sh --phi-only
```

Qwen 작업은 추가 제출하지 않습니다. Phi 준비가 성공하면 같은 500행동 설정의 24회가 시작됩니다.
데이터·프롬프트·생성 조건은 변경하지 않았습니다.

### 재개

기존 작업이 모두 종료된 뒤 `bash server/submit-nightly.sh`를 다시 실행하면
같은 코드/설정/모델의 완료 에피소드는 모델 로딩 전에 건너뛰고, 중단된 것은 기록을 재생하여 이어갑니다.
Phi 준비는 파일을 재사용하되 GPU 점검은 새로 수행합니다. 에러 상태 에피소드는 자동 재시도하지 않습니다.
특정 중단 에피소드만 재개하려면 상태표를 보고 서버에서 해당 배열 인덱스를 지정합니다.
보고서 0–23은 Qwen 배열 0–23, 24–47은 Phi 배열 0–23에 해당합니다.

```bash
# 예시: Qwen 배열 인덱스 2,3만 중단된 경우
sbatch --array=2,3%1 server/nightly.sbatch qwen14
# Phi 준비가 성공한 뒤 Phi 배열 인덱스 4만 중단된 경우
sbatch --array=4%1 server/nightly.sbatch phi14
```

---

아래 전체 코호트와 상태 진단은 이전 실행 절차입니다.

# 현재 권장: 고정된 12문제 코호트

실패 사례별 프롬프트 수정 대신 14B/32B × Solo/Peer × easy 12문제 전체를 비교합니다.
주 실험은 추가 형식 안내 없이 원본 입력과 50행동 정체 도움 규칙을 유지합니다.

```bash
# 로컬
bash server/upload.sh
# 서버 ~/escape-lab
sbatch server/cohort.sbatch
squeue -u "$USER"
```

48개 작업 중 동시 최대 2개, 각 작업은 GPU 1장·한 에피소드·최대 11시간 30분입니다.
32B 모델은 shared의 기존 다운로드를 사용하고, 결과는 두 모델 모두
`/shared/s2/lab04/본인계정/escape-lab/outputs/cohort-v1/`에 저장합니다.
로그는 프로젝트 폴더의 `cohort-배열JOBID_인덱스.out/.err`입니다.
현재 주 실험 설정·분석 기준·중단된 인덱스 재개는 [실험 프로토콜](../../MATRIX_PROTOCOL.md)을 봅니다.
이전 상태 진단은 전체 게임 성능 자료와 합치지 않습니다.

---

# GSDS 서버에서 첫 오픈 모델 실험


## 같은 실패 상태에서 14B/32B 비교 (현재 권장)

로컬에서 상태 복원과 프롬프트 검증을 마친 `data/state_probes/`를 업로드합니다.

```bash
# 로컬
bash server/upload.sh
# 서버 로그인 후
cd ~/escape-lab
bash server/submit-state-probes.sh
squeue -u "$USER"
```

독립적인 GPU 1장 작업 두 개입니다. 14B는 기존 모델을 사용하고, 32B 작업은 공식 Qwen3-32B
고정 revision `9216db5781bf21249d130ec9da846c4624c16137`을 먼저 다운로드한 뒤 같은 진단을 실행합니다.
[공식 가중치 인덱스](https://huggingface.co/Qwen/Qwen3-32B/blob/main/model.safetensors.index.json)의
가중치 크기는 약 65.5GB입니다. 디스크에는 BF16 원본을 저장하고, 로딩할 때만 NF4 4비트로 변환합니다.
3090 24GB 한 장·배치 1·문맥 상한 4096으로 시도하되, 실제 GPU 적합성은 로딩/첫 추론으로 확인합니다.
OOM이면 오류를 기록하고 중단하며, CPU 오프로딩이나 양자화 방식 변경으로 실험 조건을 몰래 바꾸지 않습니다.

네 상태는 이동 라벨 오류 직전, 벽의 열쇠 수집 전, 망치 수집 전, 상대의 쇠고리를 요청해야 하는 시점입니다.
각 상태의 행동 기록을 원본 엔진에서 재생하고 위치·가방·관찰·기록·메시지 일치를 검사합니다.
상태마다 original/move_labels/action_labels를 하나씩 적용해 **다음 행동 1회만** 묻습니다.
모델당 12회, 두 모델 총 24회입니다. 같은 상태를 쓰므로 다른 탐색 경로에 의한 교란을 줄입니다.
14B 실패 사례를 골랐으므로 대표 표본이 아니며, 전체 게임 성공률이나 32B의 전반적 우월성으로 해석하지 않습니다.
정답이나 상대의 숨은 상태는 프롬프트에 추가하지 않습니다. 같은 greedy·출력 256·thinking 끔·4비트 조건입니다.

### 저장 위치와 실패 처리

- 개인 quota 초과가 실제로 확인되어, 현재 32B 배치 작업은
  `/shared/s2/lab04/본인계정/escape-lab/models/Qwen3-32B`로 바로 받습니다 (`--storage shared`).
- 같은 고정 revision 다운로드의 완료 파일은 예상 크기를 검사해 재사용하고,
  빠진 파일만 받습니다. `.cache/huggingface`도 보존하여 Hub가 미완료 조각을 재개할 수 있게 합니다.
  파일 개수 기준 다운로드 진행률은 바이트 비율이 아닙니다.
- `df`의 여유는 개인 quota가 아닙니다. quota 미확인을 무제한 용량으로 간주하지 않습니다.
- 네트워크·권한 오류는 용량 부족으로 처리하지 않고 중단합니다. 연구실 경로 쓰기 권한도 검사합니다.
- 개인 폴더의 미완료 파일은 자동 삭제하지 않습니다. 아래 명시적 정리 명령은 개인 32B 폴더만 삭제합니다.
- quota 부족으로 연구실 경로를 사용하면 **32B 결과도 같은 본인 하위 폴더의 outputs/**에 저장합니다.
- 각 작업 최대 11시간 30분, 다운로드 최대 4시간, 진단 프로세스 예산 최대 6시간입니다.
  자동 재제출은 하지 않습니다. 동일 명령으로 재제출하면 완료된 개별 진단 파일을 건너뜁니다.

### 개인 quota 초과 후 32B만 재시도

기존 32B 작업이 종료된 것을 확인한 뒤 실행합니다. 개인 폴더 다운로드는 실패 시 자동으로
지워지지 않습니다. quota는 바이트 또는 파일 수 제한일 수 있어 이 로그만으로 한도값은 알 수 없습니다.
정리 스크립트는 `~/escape-lab/models/Qwen3-32B`만 대상으로 하며 symlink는 거부합니다.
개인 공간이 꽉 차 업로드가 실패할 수 있으므로 SSH 표준입력으로 먼저 정리합니다.

```bash
# 로컬 Mac의 프로젝트 폴더: 서버 파일을 정리 (비밀번호는 SSH에 직접 입력)
ssh -p 22555 gyeonghwankim@147.47.200.188 'bash -s -- --delete' < server/cleanup-personal-32b.sh
bash server/upload.sh
# 서버
cd ~/escape-lab
sbatch server/state-probes.sbatch 32B
```

`--delete`를 빼면 경로와 점유량만 표시합니다. 8B/14B, 실험 결과, shared의 32B는 삭제하지 않습니다.
새 작업은 shared의 완료 파일을 재사용하고 나머지 다운로드·파일 크기 검증 후 진단을 실행합니다.
로그는 개인 저장소에, 32B 모델과 결과는 shared의 본인 폴더에 저장합니다.

로그는 `probes-JOBID.out/.err`이며 선택된 모델·결과 경로가 출력됩니다.
결과 `state-probes-v1-14B/`, `state-probes-v1-32B/`의 `report.md`에는 행동과 환경 응답,
각 JSON에는 실제 프롬프트·생성 설정·복원된 상태가 남습니다. 첫 생성까지 완료해야 GPU 실행을 확인한 것입니다.

```bash
# 로컬: 개인 저장소 결과와 로그
mkdir -p outputs/gsds/logs
rsync -av -e 'ssh -p 22555' \
  'gyeonghwankim@147.47.200.188:escape-lab/outputs/state-probes-v1-*' outputs/gsds/
rsync -av --include='probes-*.out' --include='probes-*.err' --exclude='*' \
  -e 'ssh -p 22555' gyeonghwankim@147.47.200.188:escape-lab/ outputs/gsds/logs/
# 32B가 연구실 경로로 전환된 경우에만 추가
rsync -av -e 'ssh -p 22555' \
  gyeonghwankim@147.47.200.188:/shared/s2/lab04/gyeonghwankim/escape-lab/outputs/state-probes-v1-32B outputs/gsds/
```

다운로드와 추론은 모두 [GSDS 매뉴얼](https://gsds.gitbook.io/gsds)에 따라 할당받은 GPU 노드에서 수행합니다.
로컬 점검: `python -m unittest tests.test_state_probes` 및
`python -m scripts.run_state_probes --model preview --dry-run --output /tmp/state-probe-preview`.



## 행동 형식 진단 실험 (기존 기준선과 별도)

14B 파일럿에서 당구장 B는 화면에 보이는 `key in the wall`(턴 63), `hammer`(턴 103)를
수집하지 않고 `give`하여 실패했습니다. 두 도구 모두 자기 구역의 여행가방/판자에 사용하는 도구라서,
전달 시도 자체를 올바른 협업 전략으로 보기도 어렵습니다. 실험실 B는 이동 라벨에 목적지 설명과
따옴표를 붙이는 오류를 19회 반복했습니다.

새 조건은 원본 관찰 뒤에 현재 표시된 이름으로만 만든 형식 안내를 덧붙입니다.
엔진·파서·정답·실패 턴 소비는 그대로이며, 오답을 자동 교정하거나 물건을 자동 수집하지 않습니다.

| 조건 | 문제/실행 | 추가 안내 |
|---|---|---|
| `move_labels` | 실험실 game2-4, Solo/Peer | 실제로 입력할 수 있는 정확한 move 호출 목록 |
| `action_labels` | 당구장 game1-3, Solo/Peer | 위 이동 안내 + 현재 click 목록, 실제 가방 목록, Peer의 현재 give 목록, 수집/사용/조합/전달의 구분 |

동일한 14B/4비트/greedy/기억 10턴/4,000행동/50행동 정체 도움을 사용합니다.
각 작업은 2에피소드 배치로 GPU 1장을 사용합니다. 기존 실험실은 4에피소드 배치였으므로
배치 차이에 따른 수치 오차 가능성은 남습니다. 기존 생성 검증을 유지하며 별도 smoke는 추가하지 않습니다.
기존 기준선 결과를 보존하고, 새 표기 조건의 결과는 기본 비교표에서 제외합니다.

```bash
# 로컬
bash server/upload.sh
# 서버 ~/escape-lab
bash server/submit-interface-diagnostic.sh
squeue -u "$USER"
```

출력은 `outputs/matrix/diagnostic-v3-g2-14B-move-labels/`,
`outputs/matrix/diagnostic-v3-g2-14B-action-labels/`입니다. 실행 중 같은 명령을 중복 제출하지 마세요.
로컬에서는 `bash server/submit-interface-diagnostic.sh --dry-run`으로 제출 내용만 확인할 수 있습니다.

```bash
python -m scripts.matrix_report --interface move_labels
python -m scripts.matrix_report --interface action_labels
```

우선 `summary.json`의 `move_failures_before_first_hint`, `give_attempts_before_first_hint`,
`give_failures_before_first_hint`, 도움 전 진행률과 `collaboration.json`의 관찰·전달·사용을 봅니다.
원본 결과에 새 카운터가 없으면 원본 turns.jsonl에서 계산해야 합니다.
성능 개선이 있어도 이동/소유 안내의 효과이며 협업 능력 자체가 개선됐다고 단정하지 않습니다.
`action_labels`는 묶음 진단이므로 개별 안내의 기여를 주장하려면 추가 절제 실험이 필요합니다.

## 현재 권장: 14B 대표 3문제 Solo/Peer 파일럿 (v3 / generation 2)

로컬 Mac의 프로젝트 폴더에서:

```bash
bash server/upload.sh
```

서버 로그인 노드에서 (기존 개인 저장소의 모델·Conda 환경 재사용):

```bash
cd ~/escape-lab
bash server/submit-pilot.sh
squeue -u "$USER"
```

한 번 제출하면 PC/SSH 연결을 종료해도 됩니다. 14B 점검 작업(2게임 × Solo/Peer, 각 70행동)이
실제 greedy 설정·로그·종료 상태를 검증한 뒤에만 아래 두 작업이 시작됩니다.
점검이 실패하면 종속 작업은 취소되므로 `matrix-smoke-JOBID.err/.out`을 확인합니다.
점검의 탈출 성공을 요구하지 않으며, 생성 설정 검증이나 실행 오류가 있으면 통과하지 않습니다.

| 작업 | 에피소드 | 결과 폴더 |
|---|---|---|
| main | 거울 game1-1, 실험실 game2-4 각각 Solo/Peer (4개 배치) | `outputs/matrix/pilot-v3-g2-14B-main` |
| control | 당구장 game1-3 Solo/Peer (2개 배치, 낮은 상호의존) | `outputs/matrix/pilot-v3-g2-14B-control` |

각 본 작업은 GPU 1장, 최대 11시간 30분을 요청합니다. 러너는 11시간 10분에 저장·중단하고
종료 코드 75이면 자동 재제출(총 최대 4회)합니다. 일반 오류는 무한 재시도하지 않습니다.
대기 시간과 재할당을 포함한 전체 실험 완료 시간을 12시간 이내로 보장하지는 않습니다.
같은 제출 명령을 실행 중에 반복하지 마세요. 완료 후 재제출은 같은 결과 폴더의 완료 에피소드를 건너뜁니다.
새 독립 실행은 `RUN_TAG=pilot-v3-g2-14B-repeat1 bash server/submit-pilot.sh`처럼 이름을 바꿉니다.

로컬에서 제출 명령만 미리 보려면 `bash server/submit-pilot.sh --dry-run`을 사용합니다.

### 결과 받기와 읽기

로컬 프로젝트 폴더에서 최신 matrix와 Slurm 로그를 받습니다.

```bash
mkdir -p outputs/matrix outputs/gsds/logs
rsync -av -e 'ssh -p 22555' \
  gyeonghwankim@147.47.200.188:escape-lab/outputs/matrix/ outputs/matrix/
rsync -av --include='matrix-*.out' --include='matrix-*.err' --exclude='*' \
  -e 'ssh -p 22555' gyeonghwankim@147.47.200.188:escape-lab/ outputs/gsds/logs/
```

`report.md`/`results.json`이 전체 성적이고, `coop/<game>/collaboration.md`와 `.json`이
첫 힌트 전/전체 실행의 단서·물건별 관찰, 전달, 활용 근거입니다. `turns.jsonl`에는 실제 프롬프트와
매 생성의 `effective_generation` 검증 결과가 남습니다. 분석 입력은 `evaluation_inputs/`에 고정 저장됩니다.
모델에게 이 평가자용 파일을 입력하지 않습니다.

PyYAML이 설치된 Python 환경에서:

```bash
python -m scripts.matrix_report --status
python -m scripts.matrix_report
python -m scripts.analyze_collaboration outputs/matrix/pilot-v3-g2-14B-main
```

생성 버전 1의 기존 Solo/Peer는 `old_generation`으로 표시되고 새 비교에서 제외됩니다.
분석의 실패 단계는 검토 후보이며, 자유로운 메시지의 의미나 퍼즐 선행 조건을 자동 확정하지 않습니다.
전체 12게임 × 2모델 확장은 파일럿 확인 후 `server/submit-matrix.sh`로 할 수 있습니다.
세부 규칙은 [MATRIX_PROTOCOL.md](../../MATRIX_PROTOCOL.md)를 보세요.

아래 내용은 이전 실행 방식의 기록입니다.

## 별도 원본 BaseAgent 기준선

Mac에서 `bash server/upload.sh`, 서버 `~/escape-lab`에서
`sbatch server/original.sbatch`를 실행합니다. 개인 저장소에 이미 받은 14B를 사용해
원본 easy 8문제를 평가합니다. [원본 프로토콜과 재개 방법](../../ORIGINAL_PROTOCOL.md)을
먼저 확인하세요. 원본 프롬프트·엔진·도움 정책을 재사용하며 짧은 CoT, greedy 생성,
출력 256토큰, 기억 10턴, 최대 4,000행동입니다. 30분 에피소드 제한은 없습니다.
새 GPU 결과는 아직 없으며, 이전 8B 파일럿 결과와 직접 비교하지 않습니다.

## 이전 개발용 Solo 파일럿

### 8B와 14B를 한 번의 GPU 할당으로 실행

로컬에서 `bash server/upload.sh`를 실행한 뒤 서버의 `~/escape-lab`에서
`sbatch server/experiment-two-models.sbatch`를 제출한다. 8B의 기본 8회 실험이
완료되면 Qwen3-14B의 고정 버전을 `~/escape-lab/models/Qwen3-14B`에 받고 같은
8회를 실행한다. 모델 파일 약 30GB와 여유 공간이 개인 저장소에 필요하다.
파일시스템 `df`는 개인 quota를 보장하지 않는다.

한 작업에서 GPU 한 장을 최대 11시간 30분 요청한다. 모델별 실험은 최대 4시간
30분, 14B 다운로드는 최대 90분이다. 설치·다운로드·모델 로딩도 할당 시간에
포함되며, Slurm 강제 종료나 네트워크·quota·메모리 오류로 미완료될 수 있다.
어느 단계가 실패하면 이후 단계는 시작하지 않으며 이전 결과는 보존한다.
결과는 `outputs/two-models-JOBID/8B/`와 `14B/`에 따로 저장된다.
`tail -f experiment-JOBID.out`과 `cat experiment-JOBID.err`로 확인한다.
8B를 이미 완료하고 다운로드 또는 14B만 다시 시도하려면
`sbatch server/experiment-two-models.sbatch --14b-only`를 제출한다. 기존 14B
다운로드 파일을 재사용할 수 있으나, 14B 실험은 새 작업에서 처음부터 시작한다.
중단된 에피소드의 재실행은 [프로토콜 문서](../../README.md)의
`--resume` 설명을 참고한다.

기존 8문제의 실제 GPU 실행은 완료했습니다. 새 코드는 thinking과 힌트 효과를
분리해 보는 [실험 프로토콜](../../README.md)을 사용합니다. 새 프로토콜의
로컬 검증과 실제 GPU 실행 여부는 구분해야 하며, 새 GPU 결과는 아직 없습니다.

```bash
# Mac 프로젝트 폴더에서
bash server/upload.sh
# 서버 로그인 후
cd ~/escape-lab
sbatch server/experiment.sbatch
```

기존 `.conda-env`와 `models/Qwen3-8B`를 재사용합니다. GPU 1장을 한 번 할당받아
2문제 × 4조건을 순차 실행하며 모델도 한 번만 로딩합니다. 최대 11시간 30분을
요청하고 러너 자체는 10시간, 각 에피소드는 30분 상한입니다. 결과의 `report.md`와
실제 프롬프트를 포함한 `turns.jsonl`로 조건별 진행·실패를 확인합니다.
실행·재개·모델 크기 변경 방법은 위 프로토콜 문서를 참고하세요.

## 이전 Solo 파일럿 실행 방식

한 번 GPU를 할당받아 8개를 연속 실행하려면 `sbatch server/solo-sequential.sbatch`를
제출합니다. GPU 1개를 최대 11시간 30분 요청하고 모델을 한 번 로딩합니다.
최초 패키지 설치와 모델 다운로드도 할당 시간에 포함됩니다. 문제별 150행동,
최근 자기 행동과 피드백 30개, thinking 비활성화입니다. 실제 처리량은 미검증이며
제한 시간 내 8개 완료가 보장되지는 않습니다. 결과는
`outputs/solo-suite-시각/문제명/`에 개별 저장되고 `suite_summary.json`에 완료된
결과가 기록됩니다. 오류 발생 시 가능한 한 다음 문제로 넘어갑니다. Slurm 시간
제한 전에 중단 신호를 받으면 현재 턴 이후 중단을 시도하지만 강제 종료 시 마지막
요약이 없을 수 있습니다. 턴 로그는 매 턴 저장되며 자동 재개는 없습니다.
`--dataset data/pilot/01_mirror_workshop/environment.json` 옵션을 반복해 특정
문제만 실행할 수도 있습니다. 이 스크립트 제출 전에 대기 중인 다른 설치 작업은
취소하여 같은 가상환경에 동시 설치하지 않도록 합니다.

8개 전체를 자동 실행하려면 `sbatch server/solo-all.sbatch`를 사용합니다.
Slurm 작업 배열 8개가 각각 다른 문제를 실행하며 `%1` 제한으로 동시에 한 개만
GPU를 사용합니다. 작업별 최대 4시간이므로 각 작업은 12시간 제한 이내지만,
재대기와 설치 시간을 포함한 전체 8개 완료 시각은 보장되지 않습니다. 각 문제의
결과와 오류는 독립적이며 한 문제가 실패하거나 시간 초과되어도 나머지는
실행됩니다. 로그 이름은 `solo-배열번호_인덱스.out/.err`이고 인덱스 0~7은
문제 01~08에 대응합니다. `squeue -u "$USER"`와
`sacct -j 배열번호 --format=JobID,State,Elapsed,ExitCode`로 상태를 확인합니다.
동시에 다른 설치 작업을 제출하지 마세요.

로컬에서 `bash server/upload.sh`로 새 코드를 올린 후 서버 로그인 노드의
`~/escape-lab`에서 `sbatch server/solo.sbatch`를 실행합니다. SSH가 끊겨도
대기열과 할당된 작업은 유지됩니다. 기존 대화형 `srun` 대기는 따로 취소하세요.

GPU 한 장, 최대 4시간을 요청하며 b27을 제외합니다. 최초 실행은 GPU 노드에서
환경을 설치하고 모델을 다운로드합니다. 패키지·캐시와 약 16GB의 모델 파일에
필요한 저장 공간 및 quota를 미리 확인하세요. 같은 환경을 설치하는 작업을
동시에 제출하지 마세요. 01번 문제, Qwen3-8B 4비트, 최대 150행동, 최근 30개
자기 행동의 기록, thinking 비활성으로 실행합니다. 모델은 하나의 인벤토리로
원본의 모든 접근 가능 장면을 다룹니다. 명시적 메모 기능은 아직 없습니다.
예산은 바닥 효과를 탐색하기 위한 임시 값이며 완료를 보장하지 않습니다.

`squeue -u "$USER"`로 대기/실행을 확인하고, `tail -f solo-JOBID.out` 및
`cat solo-JOBID.err`로 로그를 봅니다. 결과는 `outputs/model-*/`에 저장됩니다.
작업 시간 제한 또는 다른 강제 종료 때 요약 파일이 없을 수 있고 재개 기능은
없지만 완료된 턴은 기록됩니다. `summary.json`의 `reference_action_match_fraction`은
효과가 있었던 행동과 정답 행동의 단순 일치율입니다. 대체 풀이와 중복 행동을
완전히 처리하는 상태 기반 진행률이 아니므로 임시 지표로만 사용합니다.

원한다면 `sbatch server/solo.sbatch --max-steps 2`로 짧게 확인할 수 있습니다.
`--dataset data/pilot/02_records_billiards/environment.json`처럼 문제를 변경할 수 있습니다.
이전 방식의 설치 및 GPU 추론은 사용자 서버에서 실행되어 결과가 내려받아졌습니다.
아래 접속·설치 절차는 신규 환경에서도 사용할 수 있도록 남겨 둡니다.

확인한 GSDS 매뉴얼(2026-11-10):

- [서버 구조](https://gsds.gitbook.io/gsds/): 로그인 노드는 접속·가벼운 편집용이며 실행 작업은 GPU 노드에 할당해야 합니다.
- [접속](https://gsds.gitbook.io/gsds/for-beginners/access-server): 학외망은 22555, 학내망은 22번 포트입니다.
- [Slurm](https://gsds.gitbook.io/gsds/for-beginners/slurm): 첫 디버깅은 `launch-shell GPU수 시간(분) [파티션]`, 반복 작업은 `sbatch`를 권장합니다. 문서상 launch-shell 최대 시간은 4시간입니다.
- [Python 환경](https://gsds.gitbook.io/gsds/for-beginners/ananconda): 개인 Anaconda 환경을 권장합니다.

## 1. 로컬 컴퓨터에서 접속 확인과 업로드

외부망 기준, Mac 터미널에서 실행합니다. 비밀번호는 SSH가 물을 때 터미널에 직접 입력합니다. 입력 문자가 보이지 않는 것이 정상입니다. 메일의 `&#x20;`는 HTML 공백 표현이며 비밀번호 자체가 아닙니다.

```bash
ssh -p 22555 gyeonghwankim@147.47.200.188
```

이번 확인에서는 22555번 연결이 인증 전에 reset되었고, 22번은 응답했으나 키 인증에 실패했습니다. 이는 이 도구 실행 환경에서의 결과이며, 사용자 터미널에서도 동일하다는 뜻은 아닙니다. 학외망에서 임의로 22번으로 바꾸는 대신 위 명령으로 먼저 확인하세요. 동일한 reset이 계속되면 관리자에게 접속 시각·외부망 여부·오류 메시지를 알려 확인해야 합니다. 비밀번호를 바꿔서 해결되는 종류의 인증 오류인지도 아직 알 수 없습니다.

최초 접속 시 표시되는 서버 호스트 키는 관리자 안내와 확인하고, `StrictHostKeyChecking=no`로 검사를 끄지 마세요. 로그인에 성공하면 업로드를 위해 `exit`으로 로컬로 돌아옵니다.

프로젝트 루트에서:

```bash
bash server/upload.sh
```

`~/escape-lab/`을 만들고 실행 코드·데이터·테스트·문서만 업로드합니다. 비밀번호나 SSH 키, 로컬 환경, 기존 실험 출력은 전송하지 않습니다. 기존 서버 실험 로그도 삭제하지 않습니다. 처음 업로드가 아니라면 같은 이름의 코드·데이터 파일은 갱신됩니다. 학내망으로 바뀐 경우에만 `ESCAPE_PORT=22 bash server/upload.sh`를 사용합니다.

## 2. 로그인 노드에서 GPU 할당

```bash
ssh -p 22555 gyeonghwankim@147.47.200.188
cd ~/escape-lab
sinfo -o '%P %a %l %D %G'
squeue -u "$USER"
launch-shell 1 120
```

GPU 한 장을 최대 120분 요청하는 첫 설치/디버깅용 예시입니다. 대기 중이면 자원이 배정될 때까지 기다립니다. 특정 파티션을 지정해야 한다면 `launch-shell 1 120 파티션명`처럼 사용합니다. 매뉴얼의 `b`는 예시이며 계정 권한을 확인하지 않았으므로 스크립트에 고정하지 않았습니다.

할당된 쉘 안에서:

```bash
hostname
nvidia-smi
printf 'SLURM_JOB_ID=%s\n' "$SLURM_JOB_ID"
cd ~/escape-lab
```

여기서 실제 GPU 종류·메모리·드라이버를 확인합니다. 설치·모델 다운로드·Python 검증·추론은 이 할당 안에서 수행하세요. 스크립트는 Slurm 할당이 없으면 모델 실행과 설치를 거부합니다. Slurm이 지정한 `CUDA_VISIBLE_DEVICES`를 임의로 바꾸지 않습니다.

## 3. GPU 노드에서 Python 환경 설치

설치 스크립트는 프로젝트 안의 `.conda-env/`에 Python 3.11 Conda 환경 하나를
만들고 패키지를 그 환경에 설치합니다. 기존 base 환경과 이전 `.venv-model/`은
변경하지 않습니다. 설치가 완료되면 다른 GPU 노드에서도 환경을 재사용합니다.
설치는 Slurm으로 할당받은 노드에서만 실행하며, 배치 작업 환경의 PATH에서
`conda`를 찾을 수 있어야 합니다.

```bash
bash server/setup.sh
```

`conda` 명령 자체가 없다면 본인의 설치 경로에 맞는 Conda 활성화가 먼저 필요합니다. Conda 설치도 필요한 경우 위 매뉴얼을 따르되 작업은 할당된 GPU 노드에서 진행합니다. 스크립트는 시스템 Python이나 NVIDIA 드라이버를 변경하지 않습니다.

설치 결과:

- 프로젝트 전용 `.conda-env/`
- PyTorch 2.7.1 CUDA 11.8 wheel
- Transformers 4.51.3, Accelerate 1.6.0, bitsandbytes 0.45.5
- 설치 버전 기록 `server/installed-packages.txt`

이 조합은 Qwen3 지원 버전으로 고정한 **시작 구성**입니다. 대상 서버에서 설치/실행 검증은 아직 하지 않았습니다. CUDA 관련 오류라면 `nvidia-smi`, 설치 로그, 오류 메시지로 드라이버 호환성을 확인해야 합니다. 관리자 GPU 드라이버를 직접 업데이트하지 마세요.

첫 모델 다운로드는 원본 16비트 체크포인트를 받은 뒤 GPU 로딩 중 4비트로 변환합니다. **4비트 실행이라고 다운로드도 4GB인 것은 아닙니다.** 모델 파일만 대략 16GB 규모이고 환경·패키지 캐시도 추가됩니다. 시작 전 `df -h .`와 계정 quota를 확인하세요. 기본 모델 캐시는 `~/escape-lab/.cache/huggingface/`이며 스토리지 정책에 맞춰 `HF_HOME`으로 다른 개인 경로를 지정할 수 있습니다.

## 4. 총 30행동 테스트

GPU 할당 쉘 안에서:

```bash
bash server/run.sh --max-steps 30
```

기본 실험 조건:

| 항목 | 설정 |
|---|---|
| 모델 | `Qwen/Qwen3-8B` 한 벌 |
| 정밀도 | bitsandbytes NF4 4비트 + double quantization |
| 생성 모드 | thinking 비활성화, temperature 0.7 / top-p 0.8 / top-k 20 |
| 문제 | 01 거울과 작업실 |
| 스케줄 | A→B 엄격 교대, 총 30행동(각 15행동) |
| 관찰 | 현재 자기 구역·소지품·접근 가능 구역·받은 메시지를 텍스트로 변환 |
| 기억 | 최근 자기 행동·결과 10개. 과거 전체 관찰은 누적하지 않음 |
| 메시지 | 받은 메시지는 전체 inbox 유지. 보낸 메시지는 자기 행동 이력에 포함 |
| 입력+출력 한도 | 8,192토큰. 입력이 길면 오래된 자기 행동 기록부터 제거하고 실제 포함 개수 기록 |
| 출력 한도 | 호출당 최대 192토큰. 잘린 JSON이나 잘못된 형식도 한 턴 소비 |
| 도움 | 정답 힌트·reference 입력 없음 |

현재 관찰+inbox만으로 문맥 한도를 넘으면 조용히 내용을 버리지 않고 오류로 종료합니다. 30행동은 실행·탐색·대화 확인용이며, 탈출 성공률을 평가하기에는 짧습니다. 이 실행기는 원본 EscapeAgent의 Reflection/Foresight를 구현하지 않은 최소 협업 실행기입니다. 원본의 전체 에이전트 구현을 그대로 재현했다는 뜻도 아닙니다.

선택 예시:

```bash
# 최초 설치 확인은 2행동만으로 더 짧게
bash server/run.sh --max-steps 2

# 100행동, 기존 출력과 겹치지 않는 새 디렉터리 사용
bash server/run.sh --max-steps 100 --output outputs/mirror-qwen3-seed42

# 다른 문제
bash server/run.sh --dataset data/pilot/08_laundry_escape/environment.json --max-steps 30

# 메모리가 더 적은 GPU를 할당받았을 때 작은 모델로 실행 구성 확인
bash server/run.sh --model Qwen/Qwen3-4B --max-steps 30
```

마지막 명령은 모델 자체가 달라지는 별도 실험입니다. 8B 결과와 혼합하지 않습니다. 모델 이름 변경 옵션은 제공하지만 모든 아키텍처의 호환성을 검증한 범용 실행기는 아닙니다. 특히 thinking 스위치는 Qwen3 기준입니다.

GPU 없는 로컬 프롬프트 확인:

```bash
python3 -m scripts.run_model --dry-run
```

이 명령은 초기 A/B 프롬프트만 저장하며 실제 모델 테스트가 아닙니다.

## 5. 로그 확인과 자원 반환

각 실행은 `outputs/model-UTC시각/`에 저장됩니다.

- `config.json`: 예산·프롬프트 정책·데이터와 지침의 SHA-256·seed
- `model.json`: 실제 모델 revision, 패키지·GPU·로딩 시간
- `turns.jsonl`: 매 턴 **실제 전달한 system/user 메시지**, 생성 원문, 입력·출력 토큰 수, 호출 시간, 행동 결과
- `events.jsonl`: 환경의 평가자용 로그. 모델에 다시 주면 안 됩니다.
- `summary.json`: 종료 이유, 실제 수행 턴 수, 유효 행동·상태 변화 수, 평균/중앙 호출 시간
- `gpu.json`: 정상 종료 시 GPU 메모리 peak

설치·다운로드·로딩 시간과 행동 생성 시간을 구분하세요. `summary.json`의 평균 호출 시간은 이미 완료된 호출만의 평균입니다. 첫 호출은 워밍업 때문에 느릴 수 있어 별도 기록합니다. 일반 예외나 Ctrl+C 때도 완료된 턴을 보존합니다. 강제 kill/시간 제한에서는 마지막 요약이 없을 수 있지만 턴 로그는 매번 flush합니다. 중단된 실험 재개 기능은 아직 없습니다.

실험과 확인이 끝났으면 할당 쉘에서 `exit`하여 GPU를 반환합니다. `squeue -u "$USER"`로 남은 작업을 확인하고, 필요할 때 **본인 job ID만** `scancel JOB_ID`로 취소합니다.

## 6. 설치 완료 후 sbatch로 반복 실행

로그인 노드의 프로젝트 루트에서 제출합니다. 설치는 한 번 완료되어 있어야 합니다.

```bash
cd ~/escape-lab
sbatch server/smoke.sbatch --max-steps 30
squeue -u "$USER"
```

파티션 지정이 필요하면 `sbatch --partition=본인파티션 server/smoke.sbatch --max-steps 30`을 사용합니다. 기본 파티션이 없거나 권한이 없으면 제출이 실패할 수 있으므로, `sinfo`와 관리자 안내로 확인하세요.

이 스크립트는 GPU 1개, CPU 4개, CPU RAM 32GB, 최대 1시간을 요청합니다. 로그는 `escape-JOBID.out`, `escape-JOBID.err`와 실행별 `outputs/`에 저장합니다. 반복 작업을 위해 로그인 노드에서 직접 `python -m scripts.run_model`을 실행하지 않습니다.

결과를 로컬로 가져오려면 로컬 프로젝트 루트에서:

```bash
mkdir -p outputs/gsds
rsync -av -e 'ssh -p 22555' \
  gyeonghwankim@147.47.200.188:escape-lab/outputs/ outputs/gsds/
```

## 구현 출처

- [Qwen3-8B 공식 모델 설명](https://huggingface.co/Qwen/Qwen3-8B): Transformers 4.51 이상, non-thinking 설정과 샘플링 권장값.
- [Transformers 4.51.3 양자화](https://huggingface.co/docs/transformers/v4.51.3/en/quantization/bitsandbytes): BitsAndBytesConfig와 4비트 로딩.
- [PyTorch 공식 이전 버전 설치](https://pytorch.org/get-started/previous-versions/): 2.7.1 CUDA 11.8 wheel.
