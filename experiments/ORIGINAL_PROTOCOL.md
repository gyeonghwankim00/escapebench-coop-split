# 원본 EscapeBench BaseAgent 기준선

이 실행 경로는 원본 `BaseAgent`의 코드·프롬프트·환경을 그대로 사용한다.
이전 `solo-v1`과 다른 실험이며 기존 결과를 이어받지 않는다. 협업용 JSON을 Solo로
합쳐 실행하지 않고, 분할 전 원본 YAML을 원본 Graph 엔진에 넣는다.

## 고정한 원본

- 저장소: https://github.com/qiancheng0/EscapeBench
- 커밋: `2d42347446a8e9ed4f058fa415d40afa194166a5`
- 위치: `vendor/escapebench/` (원본 71개 파일, 36개 게임 설정 포함)
- 파일 SHA-256 검증: `UPSTREAM.json`
- 어댑터 변경 내역: [ADAPTER_NOTES.md](../vendor/escapebench/ADAPTER_NOTES.md)

원본 파일을 직접 수정하지 않았다. 원본 BaseAgent 클래스와 실행 루프를 로드하고,
파일 경로·모델 호출·턴 저장만 어댑터로 연결한다. 공개 `call_LLM`에 남아 있는
`return "click(door)"` 디버그 구문과 API 키 파일 로딩을 우회해 실제 모델을 호출한다.
원본 `run` 루프에 턴 저장용 yield만 추가하며 정체 판정의 인덱스 계산도 보존한다.

## 설정과 입력

| 항목 | 설정 / 근거 |
|---|---|
| 에이전트 | 원본 BaseAgent, `--use_cot` |
| 시스템 프롬프트 | 원본 `BASE_SYS_PROMPT_COT`, 문구·오타까지 동일 |
| 현재 관찰 | 원본 `Graph.describe()` 결과 그대로 |
| 기억 | 원본 `add_history`: 최근 10턴 위치·행동·피드백 |
| 출력 | 짧은 `Thought: ...`와 `Action: ...` |
| 파싱 | 원본 `find_last_function_call`, 마지막 함수형 행동 추출 |
| 행동 | click / apply / input / move / craft, 원본 인접 이동 규칙 |
| 생성 | temperature=0에 대응하는 greedy, `do_sample=False`, 출력 1개 |
| 출력 상한 | 256토큰 (공개 vLLM 배포 예시) |
| 문맥 상한 | 기본 2,400토큰, 입력+출력 (공개 vLLM 배포 예시) |
| native thinking | 끔; 원본 짧은 CoT 지시는 유지 |
| 행동 상한 | 4,000 (공개 `run_base_opensource.sh`) |
| 도움 | 원본 50행동 정체 판정과 helper 처리 그대로 |
| 에피소드별 시간 제한 | 없음 |

사용자 메시지에는 원본 위치 경로와 현재 장면 묘사, `Possible Actions`의 현재
조작 가능한 물체·인접 장면 이동 라벨, `Tools in Bag`의 도구 설명이 들어간다.
행동은 JSON이 아니다. 예를 들어 `move(To the bedroom)`처럼 원본이 보여준
이동 라벨을 사용한다. 힌트 전에는 정답 로그나 보이지 않는 환경 상태를 넣지 않는다.

도움 상태에서는 원본대로 목표 위치로 직접 이동하고, 힌트 문구를 넣고, 최근 행동
기억을 생략한다. 원본 도움 카운터가 10에 도달하면 모델 호출 대신 정답 행동을
실행한다. `forced_action=true`, `generation=null`로 별도 기록한다. 이 도움으로
얻은 탈출을 독립 해결로 해석하면 안 된다. 주요 비교는 힌트 수·전체 행동 수·첫
도움 전 진행률이며, 원본 카운터를 그대로 사용한다.

기본 문제는 기존 분할 데이터와 대응되는 easy 8개다. 36개 원본 전체의 논문 평균과
직접 비교할 수 없다. `--games game1-1 game1-1-hard ...`로 포함된 다른 설정도
실행할 수 있다. 모든 조건을 동일하게 유지한 8B 재실행이 있어야 14B와 비교할 수 있다.

## 여전히 명시해야 하는 차이

추론 백엔드는 HF Transformers/SDPA, 기본 정밀도는 NF4 4비트, GPU는 한 장이다.
원본 공개 예시는 vLLM/BF16이다. Qwen3 모델과 chat template도 원본 논문 평가 모델과
다르므로 **논문 결과를 수치까지 완전히 재현했다고 주장하지 않는다.** 같은 생성
규칙이어도 백엔드·양자화가 다르면 응답이 달라질 수 있다. `--quantization none`으로
비양자화도 가능하지만 14B는 현재 3090 한 장에 맞는 설정이 아니다.

문맥이 초과하면 기록을 잘라서 계속하지 않고 `error`로 저장한다. 원본 vLLM 예시와
같은 문맥 상한을 사용하되, 통신 오류 문자열을 모델 행동처럼 반복 실행하지 않는다.
`--context-tokens 8192`로 바꾸면 변경된 실험 설정으로 새 결과를 생성해야 한다.

## 로컬 확인 / 서버 실행

```bash
# 로컬: 원본 엔진용 의존성 필요. 가상환경에서 설치 권장.
python3 -m pip install -r requirements-original.txt
python3 -m scripts.run_original --dry-run
bash server/upload.sh
```

dry-run은 실제 초기 system/user 메시지를 문제별 JSON으로 저장하고 모델은 로딩하지
않는다. 원본 거울 문제의 예시는 `experiments/original_examples/game1-1-easy-prompt.json`이다.

```bash
# 서버: 이미 내려받은 개인 저장소의 14B 모델로 easy 8개 실행
cd ~/escape-lab
sbatch server/original.sbatch

# 같은 조건의 8B 비교는 별도 작업으로 제출
# sbatch server/original.sbatch --model "$PWD/models/Qwen3-8B"
```

기존 `.conda-env`를 재사용하고 필요한 PyYAML만 추가한다. CPU 메모리 64GB, GPU 한 장,
최대 11시간 30분을 요청한다. b12/b24/b27은 이전 CUDA 오류가 관찰된 노드여서 제외한다.
원인을 확정한 제외가 아니며, 관리자가 문제를 해결했으면 제출 시 `--exclude`로
변경할 수 있다. 긴 대기 뒤 즉시 실패를 피한다고 보장할 수는 없다.

GPU 상태, 할당 변수, CUDA 초기화와 작은 GPU 연산을 **모델 로딩과 같은 Python
프로세스·srun 단계에서** 검사한다. `gpu-check-*.json`에 결과를 저장한다. 이전의
14B 로딩 전 CUDA 실패를 진단할 수 있도록 했으며 CUDA 환경변수는 임의로 바꾸지 않는다.

로그는 `original-JOBID.out/.err`. 결과 위치는 출력 첫 부분의
`Original protocol output: .../outputs/original-시각`이다.

- `report.md`, `results.json`: 문제별 결과와 종료 사유. 미완료는 실패 성능으로 집계하지 않는다.
- `게임명/turns.jsonl`: 원본 위치·관찰·행동·피드백·진행률, 실제 system/user 메시지,
  chat template 적용 후 입력, 원문 응답과 토큰 수. 강제 정답 행동도 표시한다.
- `게임명/summary.json`: 도움 수·전체 행동 수·도움 전 진행률 등.
- `experiment.json`: 원본 커밋·소스 해시·설정·알려진 차이.
- `model-*.json`: GPU·패키지·정밀도·chat template 해시.

## 12시간 제한과 재개

러너는 전체 10시간 또는 Slurm 종료 예고 신호에서 중단을 시도한다. 이는 문제의
풀이 예산이 아니라 인프라 중단이다. 에피소드 중간 응답은 행동으로 적용하지 않고,
완료된 턴은 매번 저장한다. 별도 설정 없이 자동으로 대기열에 재제출하지는 않는다.

```bash
sbatch server/original.sbatch --resume outputs/original-실제시각
```

이미 완료된 문제는 건너뛴다. 미완료 문제는 기록된 응답을 **모델 호출 없이** 원본
엔진에 재생하고 매 턴 프롬프트·상태 기록의 일치를 확인한 뒤 다음 턴을 추론한다.
따라서 기존 실험처럼 중단 문제를 처음부터 다시 추론하지 않는다. 도중에 잘린 마지막
로그 줄은 `.partial` 파일로 보존한다. 코드·데이터·설정·모델 식별 정보가 달라지면
재개를 거부한다. 가중치는 파일 크기·수정 시각으로 식별하며 전체 가중치 해시는 아니다.

## 검증 범위

고정 응답 backend로 원본 `BaseAgent.run`과 어댑터의 각 턴 프롬프트·행동·피드백·진행률을
비교한다. 힌트 위치 변경, 기억 생략, 정답 강제 실행까지 포함한다. 도움 중 중단/재개한
실행과 처음부터 실행한 로그가 일치하는지도 검사한다. 원본 도움 정책의 강제 행동으로
8개 게임 모두 종료되는지 확인하며 이것은 모델 성능 시험이 아니다.

```bash
python3 -m unittest discover -s tests -p test_original.py
```

기존 브라우저·협업 JSON 엔진은 유지한다. 이 기준선과 협업 결과를 비교하려면 협업
러너도 원본의 관찰·행동 규칙을 기반으로 역할별 접근과 통신을 추가해야 한다. 현재
브라우저용 엔진까지 원본과 동일해졌다고 간주하지 않는다.
