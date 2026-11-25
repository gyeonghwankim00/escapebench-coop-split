# 현재 실험 실행: v7 / nightly-v6

현재 설계는 [설계 문서](../experiments/CURRENT_DESIGN_AND_DATASET_REVIEW.md),
과거 제출 방식은 [아카이브](../experiments/archive/README.md)에 있습니다.
아래 명령은 기존 `.conda-env`, 개인 저장소의 Qwen3-14B, 연구실 개인 폴더를 사용합니다.

## 1. 로컬에서 업로드

프로젝트 폴더의 Mac 터미널에서:

```bash
bash server/upload.sh
ssh -p 22555 gyeonghwankim@147.47.200.188
```

코드·데이터·문서만 `~/escape-lab`에 갱신합니다. 모델, 로컬 환경, outputs는 업로드하지
않고 서버의 기존 결과를 삭제하지 않습니다. 실행 중인 작업이 같은 코드 경로를
읽으므로 **현재 작업이 끝난 뒤 업로드**하세요. 학내망에서는 `ESCAPE_PORT=22`를 사용합니다.

## 2. 서버에서 제출

```bash
cd ~/escape-lab
squeue -u "$USER"
bash server/submit-nightly.sh --dry-run
bash server/submit-nightly.sh
```

`conda activate`는 필요 없습니다. 스크립트가 `.conda-env/bin/python`을 직접 사용합니다.
가상환경이 없는 신규 설치는 GPU 할당 안에서 `bash server/setup.sh`로 진행합니다.
현재 nightly 실험을 위해 이미 설치한 환경을 다시 설치할 필요는 없습니다.

제출 과정:

1. Qwen 토크나이저를 로컬 모델 폴더에서 읽어 11개 Solo 정답 경로 입력을 검사합니다.
   CPU만 사용하며 가중치 로딩·추론·다운로드는 없습니다. 8192토큰에서 생성 256토큰을
   제외한 입력 한도를 넘으면 GPU 작업을 제출하기 전에 중단합니다.
2. Qwen 배열을 제출합니다. Phi는 고정 모델 다운로드(기존 파일 재사용), 같은 토크나이저 검사,
   2문제 Solo/Peer 70행동의 GPU 파이프라인 검사 후 성공해야 배열이 실행됩니다.
3. 모델당 한 번에 1GPU, 준비 작업까지 합쳐 최대 2GPU입니다. 각 에피소드는 별도
   Slurm 배열 작업이어서 문제마다 할당 대기가 생길 수 있습니다.

| 항목 | 값 |
|---|---|
| 실제 에피소드 | 11게임 × 2조건 × 2모델 = 44 |
| 배열 인덱스 | 모델별 0–23 고정; 1-4에 해당하는 6,7은 실행 없이 종료 |
| 문제 순서 | 1-1…1-5, 2-1…2-5, 3-1…3-2; 각 문제 Solo→Peer |
| 생성 | greedy, batch 1, 출력 256토큰, 입력+출력 8192 |
| 예산 | 팀 환경 행동 500, 판단 1000, 기본 무힌트 |
| 시간 | 에피소드 Slurm 11시간 30분, 러너 40,200초; Phi 준비 최대 5시간 |
| GPU | P2, 1장, b12/b24/b27 제외 |
| Qwen 모델 | `~/escape-lab/models/Qwen3-14B` |
| Phi 모델 | `/shared/s2/lab04/계정/escape-lab/models/phi-4` |
| 결과 | `/shared/s2/lab04/계정/escape-lab/outputs/nightly-v6` |

12시간 제한은 **개별 작업** 기준입니다. 전체 44회의 완료까지는 대기 때문에 며칠이
걸릴 수 있습니다. `sbatch`가 성공한 뒤에는 PC/SSH 연결을 종료해도 됩니다.
Phi만 제출하려면 `bash server/submit-nightly.sh --phi-only`를 사용합니다.

토크나이저 검사는 정답 경로의 입력을 확인할 뿐 모든 모델 행동 경로의 최대 길이를
보장하지 않습니다. 실제 실행도 매 호출 입력 길이를 검사하고, 초과 시 내용을 몰래
자르지 않고 오류로 기록합니다. 현재 로컬 검사 근거는
[protocol-v7-check.json](../experiments/evidence/protocol-v7-check.json)에 있습니다.
2-3의 연결 없는 참조 행동 1개는 건너뛴 사실을 명시하며, 전체 참조 행동의 재생 성공으로 세지 않습니다.

## 3. 상태 확인

```bash
squeue -u "$USER"
sacct -j JOB_ID --format=JobID,JobName,State,ExitCode,Elapsed,NodeList
```

Qwen/Phi 실행 로그는 프로젝트 루트의 `nightly-배열ID_인덱스.out/.err`,
Phi 준비 로그는 `nightly-phi-prep-JOB_ID.out/.err`입니다.
`COMPLETED`는 스크립트 종료 상태이며 퍼즐 탈출 여부는 결과의 summary/report로 확인합니다.

```bash
.conda-env/bin/python -m scripts.run_nightly --report \
  --output-root "/shared/s2/lab04/$USER/escape-lab/outputs/nightly-v6"
```

보고서는 핵심 6게임과 확장 4게임의 완전한 Solo/Peer 쌍에 대해
50/200/500 환경 행동 진행률과 탈출 수(k/n)를 별도 집계합니다.
당구장은 대조군, 1-4는 제외입니다. 실패·미완료를 진행률 0으로 대체하지 않습니다.
활성 작업의 쓰기와 읽기가 겹치면 불완전한 JSON 줄 검사가 실패할 수 있으므로
최종 집계와 다운로드는 관련 작업 종료 후 하세요.

## 4. 완료된 결과 다운로드

**서버가 아니라 Mac의 프로젝트 터미널**에서:

```bash
mkdir -p outputs/gsds/logs
rsync -av -e 'ssh -p 22555' \
  gyeonghwankim@147.47.200.188:/shared/s2/lab04/gyeonghwankim/escape-lab/outputs/nightly-v6 \
  outputs/gsds/
rsync -av -e 'ssh -p 22555' \
  --include='nightly-*.out' --include='nightly-*.err' --exclude='*' \
  gyeonghwankim@147.47.200.188:escape-lab/ outputs/gsds/logs/
python3 -m scripts.run_nightly --report --output-root outputs/gsds/nightly-v6
```

로컬 Python에는 원본 엔진 의존성(PyYAML)이 필요합니다. 기존 로컬 실험 환경을 사용하세요.
다운로드 폴더에는 `experiment.json`, 조건/게임별 `turns.jsonl`·`summary.json`,
집계 `cohort-report.md`·`cohort-results.json` 및 분류 스냅샷이 있습니다.
실제 모델 입력은 `turns.jsonl`의 `generation.messages`입니다.
`qwen-protocol-check.json`과 `phi-protocol-check.json`은 실제 토크나이저 검사 근거입니다.

## 5. 중단 후 재개

기존 작업이 모두 끝났는지 확인하고 같은 `submit-nightly.sh`를 다시 제출하면,
동일 코드·설정·데이터의 완료 에피소드는 건너뜁니다. 재개 가능한 중단 로그는
기존 행동 재생으로 상태를 복원합니다. 오류 상태는 원인을 먼저 확인합니다.

v7 안에서도 코드가 바뀌면 해시 검사가 재개를 거부할 수 있습니다.
이 경우 검사를 끄거나 기존 로그를 덮어쓰지 마세요. 기존 폴더를 별도 이름으로 보관한 후
새 폴더에서 시작해야 합니다. 과거 nightly-v1…v5는 현재 결과로 재집계하지 않습니다.
